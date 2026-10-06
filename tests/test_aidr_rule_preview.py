from types import SimpleNamespace

import pytest

from backend import auth, models
from backend.aidr_hook_control import HookPolicyRow, HookApprovalRow
from backend.aidr_enforcement import AidrEnforcementRevision, AidrResponseCommand
from backend.iam_routes import route_permission
from tests.test_aidr_api import service
from tests.test_aidr_enforcement import control, policy as system_policy

BASE = '/api/v1/clients/one/aidr'


def hook_body():
    return dict(agent='claude', tool='Bash', policy=dict(expected_revision='0', default_action='allow', rules=[
        dict(id='review', agent='*', tool='*', decision='ask'),
        dict(id='deny_z', agent='claude', tool='Bash', decision='deny'),
        dict(id='deny_a', agent='claude', tool='Bash', decision='deny'),
        dict(id='other', agent='codex', tool='Read', decision='allow'),
    ]))


def test_hook_preview_priority_exact_matching_defaults_and_no_writes(control):
    api, factory, _ = control
    body = hook_body()
    response = api.post(BASE+'/hook-policy/preview', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result['decision'], result['rule_id']) == ('deny', 'deny_a')
    assert result['matched_rule_ids'] == ['deny_a', 'deny_z', 'review']
    assert result['rules'][-1]['reason'] == 'agent_and_tool'
    body['policy']['rules'] = [dict(id='exact', agent='claude', tool='Bash*', decision='deny')]
    result = api.post(BASE+'/hook-policy/preview', json=body).json()
    assert result['used_default'] and result['decision'] == 'allow'
    assert result['rules'][0]['reason'] == 'tool'
    body['tool'] = 'Bash*'
    assert api.post(BASE+'/hook-policy/preview', json=body).json()['rule_id'] == 'exact'
    with factory() as db:
        assert db.query(HookPolicyRow).count() == 0
        assert db.query(HookApprovalRow).count() == 0


def test_system_preview_unknown_attribution_overlap_and_no_path_expansion(control):
    api, factory, _ = control
    policy = system_policy()
    policy['rules'] += [dict(id='allow_overlap', path='/private/tmp/protected', actor='all', decision='allow')]
    body = dict(policy=policy, path='/private/tmp/protected', actor='agent')
    result = api.post(BASE+'/enforcement/policy/preview', json=body).json()
    assert result['basis'] == 'system_path'
    assert (result['decision'], result['rule_id']) == ('deny', 'protect')
    assert len(result['matched_rule_ids']) == 2
    body['actor'] = 'unknown'
    result = api.post(BASE+'/enforcement/policy/preview', json=body).json()
    assert result['decision'] == 'allow' and result['rules'][0]['reason'] == 'unknown_actor'
    body['policy']['unknown_actor_action'] = 'deny'
    assert api.post(BASE+'/enforcement/policy/preview', json=body).json()['decision'] == 'deny'
    body['path'] = '/private/tmp/protected/child'
    result = api.post(BASE+'/enforcement/policy/preview', json=body).json()
    assert result['decision'] == 'allow' and result['used_default']
    with factory() as db:
        assert db.query(AidrEnforcementRevision).count() == 0
        assert db.query(AidrResponseCommand).count() == 0


@pytest.mark.parametrize('channel', ['hook-policy', 'enforcement/policy'])
def test_preview_validates_draft_and_respects_device_visibility(control, channel):
    api, _, _ = control
    body = hook_body() if channel == 'hook-policy' else dict(policy=system_policy(), path='/private/tmp/protected', actor='agent')
    route = '/api/v1/clients/{client_id}/aidr/'+channel+'/preview'
    assert route_permission(SimpleNamespace(scope={'route': SimpleNamespace(path=route)}, method='POST', url=SimpleNamespace(path=route))) == 'clients:view'
    api.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1, username='owner', role='user')
    assert api.post(route.format(client_id='one'), json=body).status_code == 200
    assert api.post(route.format(client_id='two'), json=body).status_code == 404
    body['policy']['rules'].append(body['policy']['rules'][0])
    response = api.post(route.format(client_id='one'), json=body)
    assert response.status_code == 422
    assert response.json()['error_code']
