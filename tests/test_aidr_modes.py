from datetime import datetime, timezone

from tests.test_runtime_governance import setup_device, report, heartbeat, save_runtime_policy, save_device_runtime


def test_modes_inherit_override_restore_and_require_actual_receipt(tmp_path):
    api, headers = setup_device(tmp_path)
    base = '/api/v1/clients/runtime-test'
    assert api.post(base+'/heartbeat', headers=headers, json={'client_id': 'runtime-test', 'governance_protocol': 2, 'runtime_governance': report() | {'protocol': 4}}).status_code == 200
    target = api.get('/api/v1/clients/governance/default').json()['runtime_governance'] | {
        'channels': {'logs': True, 'hooks': True, 'system': True}, 'modes': {'hooks': 'audit', 'system': 'intercept'}}
    assert save_runtime_policy(api, target).status_code == 200
    state = api.get(base+'/runtime-governance').json()
    assert state['channels']['system']['target_mode'] == 'intercept'
    assert not state['channels']['system']['applied']
    override = target | {'modes': {'hooks': 'intercept', 'system': 'audit'}}
    assert save_device_runtime(api, override).status_code == 200
    assert api.get(base+'/governance').json()['runtime_governance']['modes'] == override['modes']
    assert save_device_runtime(api, None).status_code == 200
    assert api.get(base+'/governance').json()['runtime_governance']['modes'] == target['modes']
    version = api.get(base+'/runtime-governance').json()['target_version']
    channel = {'state': 'running', 'code': 'aidr_enforcement_active', 'mode': 'audit', 'enabled': True, 'policy_version': version, 'reported_at': datetime.now(timezone.utc).isoformat()}
    data = report() | {'protocol': 4, 'channels': {'system': channel}}
    assert heartbeat(api, headers, data).status_code == 200
    assert not api.get(base+'/runtime-governance').json()['channels']['system']['applied']
    channel['mode'] = 'intercept'
    assert heartbeat(api, headers, data).status_code == 200
    assert api.get(base+'/runtime-governance').json()['channels']['system']['applied']
    channel['state'] = 'failed'
    assert heartbeat(api, headers, data).status_code == 200
    assert not api.get(base+'/runtime-governance').json()['channels']['system']['applied']


def test_legacy_policy_preserved_and_old_clients_do_not_receive_mode_task(tmp_path):
    api, headers = setup_device(tmp_path)
    legacy = api.get('/api/v1/clients/governance/default').json()['runtime_governance'] | {'modes': None}
    assert save_runtime_policy(api, legacy).status_code == 200
    target = api.get('/api/v1/clients/governance/default').json()['runtime_governance']
    assert target['modes'] is None
    target |= {'modes': {'hooks': 'audit', 'system': 'audit'}}
    assert save_runtime_policy(api, target).status_code == 200
    assert heartbeat(api, headers, report() | {'protocol': 3}).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert not state['tasks']
    assert state['channels']['hooks']['health']['state'] == 'mode_upgrade_required'
    invalid = target | {'modes': {'logs': 'intercept', 'hooks': 'audit', 'system': 'audit'}}
    current = api.get('/api/v1/clients/governance/default').json()
    assert api.post('/api/v1/clients/governance/default/preview', json={'expected_version': current['version'], 'runtime_governance': invalid}).status_code == 422
