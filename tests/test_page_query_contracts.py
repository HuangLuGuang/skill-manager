"""Functional boundaries of the batched management-page reads."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import auth, iam, iam_models as im, models
from backend.routers import agents, clients, dashboard, runtime_traces
from backend.sqlite_db import get_db
from tests.test_aidr_api import service
from tests.test_runtime_traces import trace_api, _batch, _create


@pytest.fixture
def authenticated_pages(service, monkeypatch):
    original, factory = service
    app = FastAPI(exception_handlers=original.app.exception_handlers)
    app.dependency_overrides[get_db] = original.app.dependency_overrides[get_db]
    for router in (clients.router, agents.router, dashboard.router, runtime_traces.router):
        app.include_router(router, prefix='/api')
    # The custom role has no Skill permission, so no registry call is allowed.
    app.dependency_overrides[dashboard.get_manager] = lambda: object()
    from backend import iam_middleware
    monkeypatch.setattr(iam_middleware, 'SessionLocal', factory)
    app.middleware('http')(iam_middleware.management_audit_middleware)
    with TestClient(app) as client:
        yield client, factory


@pytest.mark.parametrize('path,permission', [
    ('/api/v1/clients', 'clients:view'),
    ('/api/agents', 'agents:view'),
    ('/api/agents/assets', 'agents:view'),
    ('/api/v1/dashboard/overview', 'dashboard:view'),
    ('/api/v1/runtime-traces', 'traces:view'),
])
def test_pages_recheck_jwt_account_session_and_role_grants(authenticated_pages, path, permission):
    client, factory = authenticated_pages
    with factory() as db:
        iam.initialize(db)
        db.add(im.Role(name='page_reader', display_name='Page reader'))
        db.flush()
        db.add(im.RolePermission(role_name='page_reader', permission_code=permission))
        db.query(models.User).filter_by(username='owner').one().role = 'page_reader'
        db.commit()
    assert client.get(path).status_code == 401
    headers = {'Authorization': 'Bearer ' + auth.create_access_token({'sub': 'owner'})}
    assert client.get(path, headers=headers).status_code == 200
    with factory() as db:
        db.query(im.RolePermission).filter_by(role_name='page_reader').delete()
        db.commit()
    denied = client.get(path, headers=headers)
    assert denied.status_code == 403 and denied.json()['error_code'] == 'iam.permission_denied'
    with factory() as db:
        audit = db.query(im.ManagementAudit).filter_by(actor='owner', target=path, outcome='denied').one()
        assert audit.module == permission.split(':')[0] and audit.action == 'view'
        db.add(im.RolePermission(role_name='page_reader', permission_code=permission))
        db.commit()
    assert client.get(path, headers=headers).status_code == 200
    with factory() as db:
        db.query(models.User).filter_by(username='owner').one().is_active = False
        db.commit()
    assert client.get(path, headers=headers).json()['error_code'] == 'auth.account_disabled'
    with factory() as db:
        user = db.query(models.User).filter_by(username='owner').one()
        user.is_active = True
        user.current_session_id = 'new-session'
        db.commit()
    assert client.get(path, headers=headers).json()['error_code'] == 'auth.session_expired_elsewhere'
    headers['Authorization'] = 'Bearer ' + auth.create_access_token({'sub': 'owner', 'session_id': 'new-session'})
    assert client.get(path, headers=headers).status_code == 200


def test_real_auth_asset_scope_changes_on_next_request(authenticated_pages):
    client, factory = authenticated_pages
    with factory() as db:
        iam.initialize(db)
        for owner in ('owner', 'another-owner'):
            db.add(models.ManagedAgent(agent_id=owner, name=owner, created_by=owner))
        db.commit()
    headers = {'Authorization': 'Bearer ' + auth.create_access_token({'sub': 'owner'})}

    def visible():
        client_rows = client.get('/api/v1/clients', headers=headers)
        agent_rows = client.get('/api/agents', headers=headers)
        assets = client.get('/api/agents/assets', headers=headers)
        assert all(response.status_code == 200 for response in (client_rows, agent_rows, assets))
        return ([row['client_id'] for row in client_rows.json()],
                [row['agent_id'] for row in agent_rows.json()],
                [row['agent_id'] for row in assets.json()['items']])

    assert visible() == (['one'], ['owner'], ['owner'])
    assert client.get('/api/v1/clients/two', headers=headers).status_code == 404
    with factory() as db:
        db.query(models.User).filter_by(username='owner').one().role = 'super_admin'
        db.commit()
    assert tuple(set(values) for values in visible()) == ({'one', 'two'}, {'owner', 'another-owner'}, {'owner', 'another-owner'})
    with factory() as db:
        db.query(models.User).filter_by(username='owner').one().role = 'admin'
        db.query(models.ManagedClient).filter_by(client_id='one').one().registered_by = 'another-owner'
        db.query(models.ManagedAgent).filter_by(agent_id='owner').one().created_by = 'another-owner'
        db.commit()
    assert visible() == ([], [], [])
    assert client.get('/api/v1/clients/one', headers=headers).status_code == 404


def test_agent_batch_boundary_keeps_token_and_gateway_metadata_current(service):
    client, factory = service
    client.app.include_router(agents.router, prefix='/api')
    with factory() as db:
        db.add(models.ExternalAIGateway(id=1, name='Gateway', management_base_url='https://example.com',
            model_base_url='https://example.com/v1', token_id='private-token-id', token_value_encrypted='private-secret'))
        for index in range(201):
            aid = f'agent-{index}'
            db.add(models.ManagedAgent(agent_id=aid, name=aid, created_by='owner', external_gateway_id=1))
            db.add(models.AccessToken(name=f'credential-{index}', token_type='agent_runtime',
                bound_agent_id=aid, token_hash=f'hash-{index}', token_prefix='test'))
        db.commit()
    response = client.get('/api/agents')
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 201
    assert all(row['runtime_token_name'] == f'credential-{index}' and row['external_gateway_name'] == 'Gateway'
               for index, row in enumerate(rows))
    assert 'private-token-id' not in response.text and 'private-secret' not in response.text
    with factory() as db:
        db.get(models.ExternalAIGateway, 1).name = 'Renamed'
        db.query(models.AccessToken).filter_by(bound_agent_id='agent-200').delete()
        db.commit()
    row = client.get('/api/agents?q=agent-200').json()[0]
    assert row['external_gateway_name'] == 'Renamed' and row['runtime_token_id'] is None


def test_client_issue_counts_follow_recovery_governance_and_alert_resolution(service):
    client, factory = service
    client.app.include_router(clients.router, prefix='/api')
    with factory() as db:
        for cid, agent, skill, kind in [
            ('one', 'codex', 'same', 'skill_modified'),
            ('one', 'claude', 'same', 'skill_blocked'),
            ('one', None, 'unknown-agent', 'unmanaged_skill_found'),
            ('one', 'codex', None, 'skill_quarantined'),
            ('two', 'codex', 'same', 'skill_modified'),
        ]:
            db.add(models.ClientEvent(client_id=cid, agent_type=agent, skill_name=skill, event_type=kind))
        db.flush()
        db.add(models.ClientEvent(client_id='one', agent_type='codex', skill_name='same', event_type='skill_verified'))
        for details in ({'active': True}, {'active': False}, {}, {'active': 'true'}):
            db.add(models.ClientEvent(client_id='one', event_type='aidr_skill_alert', details_json=json.dumps(details)))
        db.add(models.ClientGovernancePolicy(scope='one', protocol=2, enabled=False))
        db.add(models.ClientAgent(client_id='one', agent_type='codex'))
        for name, signature, observed, trigger, action, state in [
            ('action', 'a', 'a', 'malicious', 'quarantine', 'success'),
            ('failed', 'a', 'a', '', 'record_only', 'failed'),
            ('recorded', 'a', 'a', 'malicious', 'record_only', 'success'),
            ('stale', 'b', 'a', 'malicious', 'quarantine', 'failed'),
        ]:
            db.add(models.ClientSkillInstall(client_id='one', agent_type='codex', skill_name=name,
                skill_path='/same' if name == 'action' else '/' + name, signature=signature,
                governance_json=json.dumps(dict(signature=observed, trigger=trigger, action=action, action_status=state))))
        db.commit()

    def count():
        response = client.get('/api/v1/clients')
        assert response.status_code == 200, response.text
        assert [row['client_id'] for row in response.json()] == ['one']
        row = response.json()[0]
        assert client.get('/api/v1/clients/one').json()['issue_count'] == row['issue_count']
        return row['issue_count']

    assert count() == 3  # Two latest legacy issues plus one active AIDR alert.
    with factory() as db:
        db.get(models.ClientGovernancePolicy, 'one').enabled = True
        db.commit()
    assert count() == 3  # One current action and one failed action plus the alert.
    with factory() as db:
        db.query(models.ClientEvent).filter_by(client_id='one', event_type='aidr_skill_alert').update(
            {'details_json': '{"active":false}'})
        db.commit()
    assert count() == 2
    with factory() as db:
        db.query(models.ClientSkillInstall).filter_by(client_id='one', skill_name='action').one().signature = 'changed'
        db.commit()
    assert count() == 1
    with factory() as db:
        db.get(models.ClientGovernancePolicy, 'one').protocol = 0
        db.commit()
    assert count() == 2  # Unsupported clients continue using legacy event state.


def test_policy_save_is_visible_in_list_detail_and_runtime_with_stale_preview_rejected(service):
    client, factory = service
    client.app.include_router(clients.router, prefix='/api')
    with factory() as db:
        db.add(models.ClientGovernancePolicy(scope='one', protocol=2, enabled=True))
        db.query(models.AccessToken).filter_by(name='one').one().scopes_json = '["client:read-policy"]'
        db.commit()
    url = '/api/v1/clients/one/governance'
    stale = {'expected_version': '0:0', 'rules': {'malicious': 'uninstall'}}
    preview = client.post(url + '/preview', json=stale)
    assert preview.status_code == 200, preview.text
    stale['preview_id'] = preview.json()['preview_id']
    change = {'expected_version': '0:0', 'rules': {'malicious': 'quarantine'},
              'prompt_guard': {'mode': 'block', 'llm_review': False},
              'compression': {'enabled': True, 'level': 'conservative'}}
    preview = client.post(url + '/preview', json=change)
    assert preview.status_code == 200, preview.text
    change['preview_id'] = preview.json()['preview_id']
    saved = client.put(url, json=change)
    assert saved.status_code == 200, saved.text
    for body in (
        client.get('/api/v1/clients').json()[0],
        client.get('/api/v1/clients/one').json(),
        client.get('/api/v1/clients/one/policy', headers={'Authorization': 'Bearer test-one'}).json(),
    ):
        classification = body['classification']
        assert classification['version'] == saved.json()['version']
        assert classification['rules']['malicious'] == 'quarantine'
        assert classification['prompt_guard']['mode'] == 'block'
        assert classification['compression'] == {'enabled': True, 'level': 'conservative'}
    rejected = client.put(url, json=stale)
    assert rejected.status_code == 409 and rejected.json()['error_code'] == 'client.policy_changed'
    assert client.get('/api/v1/clients').json()[0]['classification']['rules']['malicious'] == 'quarantine'


def test_trace_redacted_page_and_raw_permission_revocation_use_real_auth(trace_api):
    client, factory, _, _, plain = trace_api
    trace_id = _create(client, plain)
    assert client.post(f'/api/v1/runtime-traces/{trace_id}/events:batch',
                       headers={'Authorization': f'Bearer {plain}'}, json=_batch(trace_id)).status_code == 200
    for dependency in (auth.get_current_active_user, auth.get_current_admin_user, auth.get_current_security_reader):
        client.app.dependency_overrides.pop(dependency)
    headers = {'Authorization': 'Bearer ' + auth.create_access_token({'sub': 'privacy'})}
    url = f'/api/v1/runtime-traces/{trace_id}/events'
    page = client.get(url, headers=headers)
    assert page.status_code == 200 and 'secret-value' not in page.text
    raw = client.get(url + '/event-1/raw-payload', headers=headers)
    assert raw.status_code == 200 and 'secret-value' in raw.text
    with factory() as db:
        db.query(im.RolePermission).filter_by(role_name='privacy_auditor', permission_code='traces:raw').delete()
        db.commit()
    assert client.get(url + '/event-1/raw-payload', headers=headers).status_code == 403
    assert client.get(url, headers=headers).status_code == 200
    other = {'Authorization': 'Bearer ' + auth.create_access_token({'sub': 'other'})}
    assert client.get(url, headers=other).status_code == 403
