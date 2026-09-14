import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend import client_governance as governance, models
from backend.api_errors import ApiError
from backend.routers.clients import _issue_agent_runtime_credential
from tests.test_client_governance import db, add_client
from tests.test_client_long_poll import connected, await_waiter


def save(db, scope, guard, **options):
    view = governance.policy_view(db, None if scope == governance.DEFAULT_SCOPE else scope)
    change = governance.PolicyChange(rules=view['overrides'], prompt_guard=guard, expected_version=view['version'], **options)
    change.preview_id = governance.preview(db, scope, change)['preview_id']
    result = governance.save_policy(db, scope, change, SimpleNamespace(username='admin'))
    db.commit()
    return result


def token(db, client_id, **kwargs):
    row = models.AccessToken(name='test', token_hash=f'hash-{client_id}-{kwargs}', token_prefix='test',
                             token_type='agent_runtime', created_by=f'client:{client_id}',
                             issued_by_client_token_id=42, prompt_guard_mode='block')
    for key, value in kwargs.items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    return row


def test_default_override_existing_tokens_and_policy_tasks(db):
    add_client(db, 'one', protocol=2)
    add_client(db, 'two', protocol=2)
    one, two = token(db, 'one'), token(db, 'two')
    manual = token(db, 'one', issued_by_client_token_id=None, created_by='admin')
    revoked = token(db, 'one', status='revoked')
    save(db, 'two', {'mode': 'warn', 'llm_review': False})
    view = save(db, governance.DEFAULT_SCOPE, {'mode': 'log', 'llm_review': True})
    db.refresh(one); db.refresh(two); db.refresh(manual); db.refresh(revoked)
    assert (one.prompt_guard_mode, one.prompt_guard_llm_review) == ('log', True)
    assert (two.prompt_guard_mode, two.prompt_guard_llm_review) == ('warn', False)
    assert manual.prompt_guard_mode == revoked.prompt_guard_mode == 'block'
    own = governance.policy_view(db, 'one')
    assert own['prompt_guard'] == view['prompt_guard']
    task = db.query(models.ClientTask).filter_by(client_id='one', status='pending').one()
    assert json.loads(task.payload_json)['target_version'] == own['version']
    save(db, 'two', None)
    db.refresh(two)
    assert (two.prompt_guard_mode, two.prompt_guard_llm_review) == ('log', True)


def test_prompt_guard_defaults_to_log_and_preserves_explicit_modes(db):
    add_client(db, protocol=2)
    assert governance.policy_view(db)['prompt_guard']['mode'] == 'log'
    assert governance.policy_view(db, 'client-1')['prompt_guard']['mode'] == 'log'
    save(db, 'client-1', {'mode': 'block'})
    save(db, governance.DEFAULT_SCOPE, {'mode': 'log'})
    assert governance.policy_view(db, 'client-1')['prompt_guard']['mode'] == 'block'
    save(db, 'client-1', None)
    assert governance.policy_view(db, 'client-1')['prompt_guard']['mode'] == 'log'


def test_default_updates_legacy_client_credentials_without_waiting_for_client(db):
    add_client(db, 'legacy', protocol=0)
    credential = token(db, 'legacy')
    save(db, governance.DEFAULT_SCOPE, {'mode': 'off', 'llm_review': False})
    db.refresh(credential)
    assert credential.prompt_guard_mode == 'off'


def test_prompt_only_preview_cannot_be_reused_for_different_guard(db):
    add_client(db, protocol=2)
    change = governance.PolicyChange(expected_version='0:0', prompt_guard={'mode': 'log'})
    change.preview_id = governance.preview(db, 'client-1', change)['preview_id']
    change.prompt_guard.mode = 'off'
    with pytest.raises(ApiError) as error:
        governance.save_policy(db, 'client-1', change, SimpleNamespace(username='admin'))
    assert error.value.code == 'client.policy_preview_required'
    db.rollback()


def test_omitted_field_preserves_policy_and_invalid_mode_is_rejected(db):
    add_client(db, protocol=2)
    view = save(db, 'client-1', {'mode': 'warn', 'llm_review': True})
    change = governance.PolicyChange(expected_version=view['version'], rules={'malicious': 'quarantine'})
    change.preview_id = governance.preview(db, 'client-1', change)['preview_id']
    result = governance.save_policy(db, 'client-1', change, SimpleNamespace(username='admin'))
    db.commit()
    assert result['prompt_guard'] == view['prompt_guard']
    with pytest.raises(ValidationError):
        governance.PolicyChange(expected_version='0:0', prompt_guard={'mode': 'invalid'})


def test_new_and_rotated_credentials_inherit_policy(db):
    add_client(db, protocol=2)
    save(db, 'client-1', {'mode': 'warn', 'llm_review': True}, compression={'enabled': True, 'level': 'conservative'})
    issuer = models.AccessToken(name='issuer', token_type='client', token_hash='issuer', token_prefix='issuer',
                                bound_client_id='client-1', allowed_ips_json='[]')
    agent = models.ManagedAgent(agent_id='agent-1', name='Agent', channel='Codex')
    db.add_all([issuer, agent]); db.commit()
    for mode in ['warn', 'log']:
        if mode == 'log':
            save(db, 'client-1', {'mode': mode, 'llm_review': True})
        task = models.ClientTask(client_id='client-1', task_type='apply_model_config', payload_json='{}')
        db.add(task); db.commit()
        _, issued = _issue_agent_runtime_credential(db, client_token=issuer, client_id='client-1', agent=agent,
                                                    model_name='test-model', task=task)
        assert (issued.prompt_guard_mode, issued.prompt_guard_llm_review) == (mode, True)
        assert (issued.enable_compression, issued.compression_level) == (True, 'conservative')


@pytest.mark.parametrize('field, config', [
    ('prompt_guard', {'mode': 'warn', 'llm_review': True}),
    ('compression', {'enabled': True, 'level': 'aggressive'}),
])
def test_model_policy_save_wakes_long_poll_and_confirms_version(tmp_path, field, config):
    client, headers = connected(tmp_path)
    root = '/api/v1/clients/waiting'
    policy = client.get(root + '/governance').json()
    body = {'rules': policy['overrides'], 'expected_version': policy['version'],
            field: config}
    preview = client.post(root + '/governance/preview', json=body)
    assert preview.status_code == 200
    body['preview_id'] = preview.json()['preview_id']
    with client, ThreadPoolExecutor() as pool:
        future = pool.submit(client.get, root + '/tasks?wait_seconds=30', headers=headers)
        await_waiter()
        saved = client.put(root + '/governance', json=body)
        assert saved.status_code == 200, saved.text
        response = future.result(timeout=3)
        assert response.status_code == 200
        task = response.json()[0]
        assert task['task_type'] == 'sync_policy'
        fresh = client.get(root + '/policy', headers=headers).json()['classification']
        assert fresh[field] == body[field]
        assert task['payload']['target_version'] == fresh['version']
        result_url = root + f"/tasks/{task['id']}/result"
        assert client.post(result_url, headers=headers, json={'status': 'running'}).status_code == 200
        assert client.post(result_url, headers=headers, json={
            'status': 'succeeded', 'applied_policy_version': fresh['version'],
        }).status_code == 200
