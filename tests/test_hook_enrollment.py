from backend.client_governance import default_runtime_governance
from tests.test_runtime_governance import setup_device, heartbeat, report, save_runtime_policy


def test_self_enrollment_durable_idempotent_inherited_and_revocable(tmp_path):
    api, headers = setup_device(tmp_path)
    path = '/api/v1/clients/runtime-test/policy'
    before = api.get(path, headers=headers).json()['classification']
    assert api.get('/api/v1/clients/governance/default').json()['runtime_governance']['allow_user_enrollment'] is True
    assert 'allow_user_enrollment' not in before['runtime_governance']
    data = report() | {'protocol': 5, 'user_hook_hosts': ['workbuddy']}
    response = heartbeat(api, headers, data)
    assert response.status_code == 200, response.text
    current = response.json()['policy']['classification']
    assert current['runtime_governance']['hosts'] == ['codex', 'claude', 'workbuddy']
    assert current['runtime_governance']['allow_user_enrollment'] is True
    assert current['runtime_governance_override'] is None
    assert current['runtime_governance']['channels'] == before['runtime_governance']['channels']
    assert heartbeat(api, headers, data).json()['policy']['classification']['version'] == current['version']
    # A legacy heartbeat has no enrollment capability; it cannot erase choices.
    assert heartbeat(api, headers, report() | {'protocol': 5}).json()['policy']['classification']['runtime_user_hosts'] == ['workbuddy']
    target = default_runtime_governance() | {'hosts': ['codex'], 'allow_user_enrollment': False}
    assert save_runtime_policy(api, target).status_code == 200
    restricted = heartbeat(api, headers, data).json()['policy']['classification']
    assert restricted['runtime_governance']['hosts'] == ['codex']
    # Re-enabling delegation restores local choices without pinning globals.
    assert save_runtime_policy(api, target | {'allow_user_enrollment': True}).status_code == 200
    assert heartbeat(api, headers, data).json()['policy']['classification']['runtime_governance']['hosts'] == ['codex', 'workbuddy']
    removed = heartbeat(api, headers, data | {'user_hook_hosts': []}).json()['policy']['classification']
    assert removed['runtime_governance']['hosts'] == ['codex']
    assert removed['runtime_user_hosts'] == []
    assert removed['runtime_governance_override'] is None


def test_enrollment_cannot_enable_channel_managed_mode_or_unsupported_product(tmp_path):
    api, headers = setup_device(tmp_path)
    data = report() | {'protocol': 5, 'user_hook_hosts': ['workbuddy']}
    target = default_runtime_governance()
    for changes in [{'enabled': False}, {'channels': {'logs': True, 'hooks': False, 'system': False}}, {'access_mode': 'managed'}]:
        assert save_runtime_policy(api, target | changes).status_code == 200
        value = heartbeat(api, headers, data).json()['policy']['classification']['runtime_governance']
        assert 'workbuddy' not in value['hosts']
        assert all(value[key] == item for key, item in changes.items())
    for invalid in [['workbuddy', 'workbuddy'], ['not-a-product']]:
        assert heartbeat(api, headers, data | {'user_hook_hosts': invalid}).status_code == 422
    assert heartbeat(api, headers, data | {'protocol': 4}).status_code == 422
    assert heartbeat(api, {}, data).status_code in (401, 403)


def test_teleagent_enrollment_pairs_logs_without_changing_other_sources(tmp_path):
    api, headers = setup_device(tmp_path)
    target = default_runtime_governance() | {'log_sources': ['qoder-cli']}
    assert save_runtime_policy(api, target).status_code == 200
    data = report() | {'protocol': 5, 'user_hook_hosts': ['teleagent']}
    value = heartbeat(api, headers, data).json()['policy']['classification']['runtime_governance']
    assert value['log_sources'] == ['qoder-cli', 'teleagent']
    assert value['hosts'] == [*target['hosts'], 'teleagent']
    removed = heartbeat(api, headers, data | {'user_hook_hosts': []}).json()['policy']['classification']['runtime_governance']
    assert removed['log_sources'] == ['qoder-cli']
    for changes in [{'allow_user_enrollment': False}, {'channels': {'logs': False, 'hooks': True, 'system': False}}]:
        assert save_runtime_policy(api, target | changes).status_code == 200
        value = heartbeat(api, headers, data).json()['policy']['classification']['runtime_governance']
        assert value['log_sources'] == ['qoder-cli']
