from datetime import datetime, timedelta
import json

from backend import auth, models
from backend.runtime_governance import Observation
from backend.client_governance import RuntimeGovernanceConfig, default_runtime_governance
from backend.sqlite_db import get_db
from tests.test_clients_api import _client


def setup_device(tmp_path):
    api = _client(tmp_path)
    token = api.post('/api/v1/access/tokens', json={'name': 'runtime-fixture', 'token_type': 'client'}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    response = api.post('/api/v1/clients/register', headers=headers, json={'client_id': 'runtime-test', 'name': 'Runtime test', 'hostname': 'isolated', 'os': 'darwin', 'arch': 'arm64', 'client_version': 'dev', 'agents': []})
    assert response.status_code == 200
    return api, headers


def report():
    return {'protocol': 1, 'plugin_version': '0.1.0', 'enabled': False, 'managed_task': '0', 'receiver_code': 'aidr_desktop_stopped', 'hosts': []}


def action(request='request1', operation='enable'):
    return {'task_type': 'aidr_plugin_action', 'payload': {'request_id': request, 'action': operation, 'agent': '', 'plugin_version': '0.1.0'}}


def heartbeat(api, headers, data=None):
    return api.post('/api/v1/clients/runtime-test/heartbeat', headers=headers, json={'client_id': 'runtime-test', 'runtime_governance': data or report()})


def test_runtime_task_capability_claim_receipt_and_idempotency(tmp_path):
    api, headers = setup_device(tmp_path)
    path = '/api/v1/clients/runtime-test/tasks'
    assert api.post(path, json=action()).status_code == 409
    assert heartbeat(api, headers).status_code == 200
    created = api.post(path, json=action())
    assert created.status_code == 200
    ident = created.json()['id']
    assert api.post(path, json=action()).json()['id'] == ident
    assert api.post(path, json=action('different', 'disable')).status_code == 409
    endpoint = f'{path}/{ident}/result'
    assert api.post(endpoint, headers=headers, json={'status': 'succeeded', 'aidr_result': report()}).json()['ignored']
    assert not api.post(endpoint, headers=headers, json={'status': 'running'}).json()['ignored']
    assert api.post(endpoint, headers=headers, json={'status': 'running'}).json()['ignored']
    assert api.post(endpoint, headers=headers, json={'status': 'succeeded', 'aidr_result': report()}).status_code == 409
    assert api.post(endpoint, headers=headers, json={'status': 'succeeded', 'aidr_result': report() | {'managed_task': str(ident)}}).status_code == 409
    applied = report() | {'enabled': True, 'managed_task': str(ident)}
    assert api.post(endpoint, headers=headers, json={'status': 'succeeded', 'aidr_result': applied}).status_code == 200
    assert api.post(endpoint, headers=headers, json={'status': 'failed'}).json()['ignored']
    observed = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert observed['report']['enabled'] is True
    assert observed['tasks'][0]['status'] == 'succeeded'
    assert all(observed['tasks'][0]['payload']['receipt'][key] == value for key, value in applied.items())


def test_runtime_supervision_has_separate_observation_and_strict_projection(tmp_path):
    api, headers = setup_device(tmp_path)
    supervision = {'attempts': 3, 'retry_count': 2, 'mode': 'fixed', 'suspended': True,
                   'code': 'aidr_desktop_receiver_failed', 'observed_at': '2026-09-01T00:00:00Z',
                   'next_retry_at': None, 'last_failure': 'aidr_store_busy', 'last_failure_at': '2026-09-01T00:00:00Z'}
    data = report() | {'protocol': 2, 'receiver_supervision': supervision}
    assert heartbeat(api, headers, data).status_code == 200
    observed = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert observed['report']['receiver_supervision'] == supervision
    assert observed['report']['receiver_code'] == 'aidr_desktop_stopped'
    assert observed['reported_at'] != supervision['observed_at']
    assert heartbeat(api, headers, data | {'receiver_supervision': supervision | {'token': 'fictional-test'}}).status_code == 422
    assert heartbeat(api, headers, data | {'receiver_supervision': supervision | {'attempts': 4294967296}}).status_code == 422
    assert heartbeat(api, headers, data | {'receiver_supervision': supervision | {'last_failure': 'raw secret'}}).status_code == 422


def save_runtime_policy(api, target):
    path = '/api/v1/clients/governance/default'
    current = api.get(path).json()
    body = {'expected_version': current['version'], 'rules': current['overrides'], 'runtime_governance': target}
    result = api.post(path+'/preview', json=body)
    assert result.status_code == 200, result.text
    return api.put(path, json=body | {'preview_id': result.json()['preview_id']})


def test_runtime_default_policy_permissions_preview_and_legacy(tmp_path):
    api, headers = setup_device(tmp_path)
    path = '/api/v1/clients/governance/default'
    before = api.get(path).json()
    assert before['runtime_governance_configured']
    assert before['runtime_governance_builtin']
    assert before['runtime_governance'] == default_runtime_governance()
    assert before['runtime_governance']['retry'] == {'mode':'fixed','retries':2,'max_interval_seconds':300}
    assert heartbeat(api, headers).status_code == 200
    target = before['runtime_governance'] | {'installation':'automatic','hosts':['codex']}
    saved = save_runtime_policy(api, target)
    assert saved.status_code == 200
    assert saved.json()['runtime_governance_configured']
    assert api.post(path+'/preview',json={'expected_version':'1:0','runtime_governance':None}).status_code == 422
    duplicate = target | {'hosts':['codex','codex']}
    assert api.post(path+'/preview',json={'expected_version':'1:0','runtime_governance':duplicate}).status_code == 422
    assert api.post('/api/v1/clients/runtime-test/governance/preview', json={'expected_version':'1:0','runtime_governance':target}).status_code == 409
    assert heartbeat(api, headers).status_code == 200
    assert not api.get('/api/v1/clients/runtime-test/runtime-governance').json()['tasks']
    api.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1,username='admin',role='admin',hashed_password='x')
    assert not api.get(path).json()['editable']
    assert api.post(path+'/preview',json={'expected_version':'1:0','runtime_governance':target}).status_code == 403
    assert api.put(path,json={'expected_version':'1:0','runtime_governance':target}).status_code == 403


def test_runtime_auto_tasks_are_bounded_superseded_and_retryable(tmp_path):
    api, headers = setup_device(tmp_path)
    target = RuntimeGovernanceConfig().model_dump() | {'hosts':['codex'], 'installation':'automatic'}
    assert save_runtime_policy(api,target).status_code == 200
    supported = report() | {'protocol':2}
    for _ in range(100):
        assert heartbeat(api,headers,supported).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert len(state['tasks']) == 1
    old = state['tasks'][0]['id']
    assert state['tasks'][0]['payload']['target'] == {k: v for k, v in target.items() if k != 'allow_user_enrollment'}
    assert api.post('/api/v1/clients/runtime-test/tasks',json=action('conflict','disable')).status_code == 409
    assert save_runtime_policy(api,target | {'enabled':False}).status_code == 200
    assert heartbeat(api,headers,supported).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert len(state['tasks']) == 2 and state['tasks'][1]['status'] == 'cancelled'
    assert api.post(f'/api/v1/clients/runtime-test/tasks/{old}/result',headers=headers,json={'status':'running'}).json()['ignored']
    new = state['tasks'][0]['id']
    assert api.post(f'/api/v1/clients/runtime-test/tasks/{new}/result',headers=headers,json={'status':'running'}).json()['status'] == 'running'
    assert api.post(f'/api/v1/clients/runtime-test/tasks/{new}/result',headers=headers,json={'status':'failed','error':'aidr_desktop_task_interrupted'}).status_code == 200
    for _ in range(10):
        assert heartbeat(api,headers,supported).status_code == 200
    assert len(api.get('/api/v1/clients/runtime-test/runtime-governance').json()['tasks']) == 2
    retry = api.post(f'/api/v1/clients/runtime-test/tasks/{new}/retry')
    assert retry.status_code == 200
    assert api.post(f'/api/v1/clients/runtime-test/tasks/{new}/retry').json()['id'] == retry.json()['id']


def test_runtime_auto_task_receipt_requires_applied_revision(tmp_path):
    api,headers = setup_device(tmp_path)
    target = RuntimeGovernanceConfig().model_dump() | {'enabled':False}
    assert save_runtime_policy(api,target).status_code == 200
    assert heartbeat(api,headers,report() | {'protocol':2}).status_code == 200
    task = api.get('/api/v1/clients/runtime-test/runtime-governance').json()['tasks'][0]
    path = f"/api/v1/clients/runtime-test/tasks/{task['id']}/result"
    assert api.post(path,headers=headers,json={'status':'running'}).json()['status'] == 'running'
    receipt = report() | {'protocol':2,'managed_task':task['id'],'policy_version':'1'}
    assert api.post(path,headers=headers,json={'status':'succeeded','aidr_result':receipt}).status_code == 409
    receipt |= {'policy_applied_at':datetime.utcnow().isoformat()+'Z','policy_code':'aidr_desktop_policy_applied'}
    assert api.post(path,headers=headers,json={'status':'succeeded','aidr_result':receipt | {'enabled':True}}).status_code == 409
    assert api.post(path,headers=headers,json={'status':'succeeded','aidr_result':receipt}).status_code == 200


def test_runtime_host_changes_progress_without_timestamp_task_storms(tmp_path):
    api, headers = setup_device(tmp_path)
    target = RuntimeGovernanceConfig().model_dump() | {'installation':'automatic','hosts':['codex']}
    assert save_runtime_policy(api,target).status_code == 200
    data=report() | {'protocol':2}
    assert heartbeat(api,headers,data).status_code == 200
    state=api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    task=state['tasks'][0]
    path=f"/api/v1/clients/runtime-test/tasks/{task['id']}/result"
    assert api.post(path,headers=headers,json={'status':'running'}).status_code==200
    assert api.post(path,headers=headers,json={'status':'failed','error':'aidr_desktop_host_missing'}).status_code==200
    host={'agent':'codex','host_version':'codex-cli 0.159.0','plugin_version':None,'version_status':'adapter_target','installed':False,'enabled':None,'hook_trust':'unknown','reported_at':'2026-09-30T01:00:00Z','source_code':'aidr_plugin_not_installed'}
    appeared=data | {'enabled':True,'hosts':[host]}
    assert heartbeat(api,headers,appeared).status_code==200
    for hour in range(24):
        changed=host | {'reported_at':f'2026-09-30T{hour:02d}:00:00Z'}
        assert heartbeat(api,headers,appeared | {'hosts':[changed]}).status_code==200
    state=api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert len(state['tasks'])==2
    task=state['tasks'][0];path=f"/api/v1/clients/runtime-test/tasks/{task['id']}/result"
    assert api.post(path,headers=headers,json={'status':'running'}).status_code==200
    applied=appeared | {'managed_task':task['id'],'policy_version':state['target_version'],'policy_code':'aidr_desktop_policy_applied','policy_applied_at':'2026-09-30T02:00:00Z','hosts':[host | {'installed':True,'enabled':True,'plugin_version':'0.1.0'}]}
    assert api.post(path,headers=headers,json={'status':'succeeded','aidr_result':applied}).status_code==200
    for _ in range(10):
        assert heartbeat(api,headers,applied).status_code==200
    assert len(api.get('/api/v1/clients/runtime-test/runtime-governance').json()['tasks'])==2


def test_runtime_whitelist_expiry_visibility_and_legacy_compatibility(tmp_path):
    api, headers = setup_device(tmp_path)
    assert heartbeat(api, headers, report() | {'token': 'synthetic-secret'}).status_code == 422
    assert heartbeat(api, headers).status_code == 200
    bad = action() ; bad['payload']['host_config_dir'] = '/business'
    assert api.post('/api/v1/clients/runtime-test/tasks', json=bad).status_code == 422
    created = api.post('/api/v1/clients/runtime-test/tasks', json=action()).json()
    with next(api.app.dependency_overrides[get_db]()) as db:
        row = db.query(models.ClientTask).filter_by(id=created['id']).one()
        payload = json.loads(row.payload_json); payload['expires_at'] = (datetime.utcnow()-timedelta(seconds=1)).isoformat()+'Z'
        row.payload_json = json.dumps(payload); db.commit()
    result = api.post(f"/api/v1/clients/runtime-test/tasks/{created['id']}/result", headers=headers, json={'status': 'running'})
    assert result.json()['status'] == 'failed' and result.json()['ignored']
    assert api.post('/api/v1/clients/runtime-test/heartbeat', headers=headers, json={'client_id':'runtime-test'}).status_code == 200
    # An old heartbeat does not rewrite the previously observed projection.
    observed = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert observed['report']['protocol'] == 1
    assert not observed['supports_tasks']
    assert api.post('/api/v1/clients/runtime-test/tasks', json=action('legacy')).status_code == 409
    api.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=9, username='other-admin', role='admin', hashed_password='x')
    assert api.get('/api/v1/clients/runtime-test/runtime-governance').status_code == 404
    assert api.post('/api/v1/clients/runtime-test/tasks', json=action('unauthorized')).status_code == 404


def test_runtime_cancel_retry_and_superseded_actions(tmp_path):
    api, headers = setup_device(tmp_path); assert heartbeat(api, headers).status_code == 200
    path = '/api/v1/clients/runtime-test/tasks'
    ident = api.post(path, json=action()).json()['id']
    assert api.post(f'{path}/{ident}/cancel').status_code == 200
    retry = api.post(f'{path}/{ident}/retry').json()['id']
    assert api.post(f'{path}/{ident}/retry').json()['id'] == retry
    assert api.post(f'{path}/{retry}/result', headers=headers, json={'status':'running'}).status_code == 200
    assert api.post(f'{path}/{retry}/cancel').status_code == 409
    assert api.post(f'{path}/{retry}/result', headers=headers, json={'status':'failed','error':'aidr_desktop_receiver_failed'}).status_code == 200
    other = api.post(path,json=action('new-target','disable')).json()['id']
    assert other > retry
    assert api.post(f'{path}/{ident}/retry').status_code == 409


def save_device_runtime(api, target):
    path = '/api/v1/clients/runtime-test/governance'
    current = api.get(path).json()
    body = {'expected_version': current['version'], 'rules': current['overrides'], 'runtime_governance': target}
    preview = api.post(path+'/preview', json=body)
    assert preview.status_code == 200, preview.text
    return api.put(path, json=body | {'preview_id': preview.json()['preview_id']})


def test_channels_inherit_override_restore_and_legacy_capability(tmp_path):
    api, headers = setup_device(tmp_path)
    assert api.post('/api/v1/clients/runtime-test/heartbeat', headers=headers, json={'client_id':'runtime-test','governance_protocol':2,'runtime_governance':report() | {'protocol':2}}).status_code == 200
    target = RuntimeGovernanceConfig().model_dump() | {'channels':{'logs':True,'hooks':False,'system':False}}
    assert save_runtime_policy(api, target).status_code == 200
    inherited = api.get('/api/v1/clients/runtime-test/governance').json()
    assert inherited['runtime_governance_source'] == 'default'
    assert inherited['runtime_governance_version'] == '1'
    override = target | {'channels':{'logs':False,'hooks':True,'system':False}}
    saved = save_device_runtime(api, override)
    assert saved.status_code == 200
    assert saved.json()['runtime_governance_source'] == 'client'
    assert saved.json()['runtime_governance_version'] == saved.json()['version']
    assert heartbeat(api, headers, report() | {'protocol':2}).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert not state['channels_supported'] and not state['tasks']
    assert all(value['report'] is None and not value['applied'] for value in state['channels'].values())
    # Classification support must be freshly reported when the device edits.
    assert api.post('/api/v1/clients/runtime-test/heartbeat', headers=headers, json={'client_id':'runtime-test','governance_protocol':2,'runtime_governance':report() | {'protocol':3}}).status_code == 200
    restored = save_device_runtime(api, None)
    assert restored.status_code == 200
    assert restored.json()['runtime_governance_source'] == 'default'
    assert restored.json()['runtime_governance'] == target
    assert restored.json()['runtime_governance_version'] == '1'
    database = next(api.app.dependency_overrides[get_db]())
    try:
        operations = database.query(models.OperationLog).filter_by(action='aidr.runtime_policy_changed').all()
        assert len(operations) == 3
    finally:
        database.close()


def test_channel_report_is_bounded_versioned_and_keeps_its_own_time(tmp_path):
    api, headers = setup_device(tmp_path)
    target = RuntimeGovernanceConfig().model_dump() | {'channels':{'logs':True,'hooks':False,'system':True}}
    assert save_runtime_policy(api, target).status_code == 200
    old = (datetime.utcnow()-timedelta(minutes=5)).isoformat()+'Z'
    logs = {'state':'running','code':'aidr_log_running','enabled':True,'policy_version':'1','reported_at':old,'queued_records':3,'last_ack_at':old,'coverage_codes':['aidr_log_version_unverified']}
    data = report() | {'protocol':3,'channels':{'logs':logs}}
    assert heartbeat(api, headers, data).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert state['channels_supported']
    assert state['channels']['logs']['stale'] and not state['channels']['logs']['applied']
    assert state['channels']['logs']['report']['reported_at'] == old
    assert state['channels']['system']['report'] is None and not state['channels']['system']['applied']
    recent = logs | {'reported_at':datetime.utcnow().isoformat()+'Z'}
    assert heartbeat(api, headers, data | {'channels':{'logs':recent}}).status_code == 200
    assert api.get('/api/v1/clients/runtime-test/runtime-governance').json()['channels']['logs']['applied']
    failed = recent | {'state':'failed','code':'aidr_log_worker_failed'}
    assert heartbeat(api, headers, data | {'channels':{'logs':failed}}).status_code == 200
    assert not api.get('/api/v1/clients/runtime-test/runtime-governance').json()['channels']['logs']['applied']
    assert heartbeat(api, headers, data | {'protocol':2}).status_code == 422
    for bad in (recent | {'token':'synthetic'}, recent | {'coverage_codes':['invalid']}, recent | {'reported_at':'not-a-time'}, recent | {'queued_records':3000001}):
        assert heartbeat(api, headers, data | {'channels':{'logs':bad}}).status_code == 422


def test_hook_receipt_does_not_claim_other_channel_application(tmp_path):
    api, headers = setup_device(tmp_path)
    target = RuntimeGovernanceConfig().model_dump() | {'channels':{'logs':True,'hooks':False,'system':True}}
    assert save_runtime_policy(api, target).status_code == 200
    assert heartbeat(api, headers, report() | {'protocol':3}).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    task = state['tasks'][0]
    path = f"/api/v1/clients/runtime-test/tasks/{task['id']}/result"
    assert api.post(path, headers=headers,json={'status':'running'}).status_code == 200
    receipt = report() | {'protocol':3,'enabled':False,'managed_task':task['id'],'policy_version':'1','policy_applied_at':datetime.utcnow().isoformat()+'Z','policy_code':'aidr_desktop_policy_applied'}
    assert api.post(path, headers=headers,json={'status':'succeeded','aidr_result':receipt}).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert not state['channels']['logs']['applied'] and not state['channels']['system']['applied']


def test_runtime_details_return_registered_client_version_by_device_identity(tmp_path):
    api, headers = setup_device(tmp_path)
    response = api.get('/api/v1/clients/runtime-test/runtime-governance')
    assert response.status_code == 200
    assert response.json()['client_version'] == 'dev'
    # Device identity is a string distinct from the database integer primary key.
    session = api.app.dependency_overrides[get_db]()
    db = next(session)
    try:
        client = db.query(models.ManagedClient).filter_by(client_id='runtime-test').one()
        assert str(client.id) != client.client_id
        client.client_version = 'p1-local'
        db.commit()
    finally:
        session.close()
    assert heartbeat(api, headers).status_code == 200
    result = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert result['client_version'] == 'p1-local'
    assert result['compatibility']['state'] == 'legacy'


def test_host_interface_compatibility_accepts_new_and_legacy_reports(tmp_path):
    api, headers = setup_device(tmp_path)
    host = {'agent': 'codex', 'host_version': 'codex-cli 0.999.42', 'installed': False,
            'enabled': False, 'hook_trust': 'unknown', 'reported_at': '2026-10-07T01:00:00Z',
            'source_code': 'aidr_plugin_not_installed'}
    for status in ('interface_compatible', 'adapter_target', 'unverified'):
        data = report() | {'hosts': [host | {'version_status': status}]}
        assert heartbeat(api, headers, data).status_code == 200
        observed = api.get('/api/v1/clients/runtime-test/runtime-governance').json()['report']['hosts'][0]
        assert observed['version_status'] == status
        assert observed['hook_trust'] == 'unknown'


def test_builtin_collection_policy_reconciles_new_client_without_manual_enable(tmp_path):
    api, headers = setup_device(tmp_path)
    initial = api.get('/api/v1/clients/governance/default').json()
    assert initial['runtime_governance'] == default_runtime_governance()
    assert initial['runtime_governance']['channels'] == {'logs': True, 'hooks': True, 'system': False}
    assert heartbeat(api, headers, report() | {'protocol': 4}).status_code == 200
    state = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert len(state['tasks']) == 1
    assert state['tasks'][0]['payload']['action'] == 'reconcile'
    assert state['tasks'][0]['payload']['target'] == {k: v for k, v in default_runtime_governance().items() if k != 'allow_user_enrollment'}
    for _ in range(3):
        assert heartbeat(api, headers, report() | {'protocol': 4}).status_code == 200
    assert len(api.get('/api/v1/clients/runtime-test/runtime-governance').json()['tasks']) == 1
    disabled = default_runtime_governance() | {'enabled': False}
    assert save_runtime_policy(api, disabled).status_code == 200
    assert api.get('/api/v1/clients/governance/default').json()['runtime_governance'] == disabled
    assert not api.get('/api/v1/clients/governance/default').json()['runtime_governance_builtin']


def test_device_collection_override_survives_builtin_default(tmp_path):
    api, headers = setup_device(tmp_path)
    from backend.client_governance import policy_view
    with api.app.dependency_overrides[get_db]().__next__() as db:
        row = db.get(models.ClientGovernancePolicy, 'runtime-test')
        if row is None:
            row = models.ClientGovernancePolicy(scope='runtime-test')
            db.add(row)
        explicit = RuntimeGovernanceConfig(enabled=False).model_dump()
        row.runtime_governance_json = json.dumps(explicit)
        db.commit()
        effective = policy_view(db, 'runtime-test')
        assert effective['runtime_governance'] == explicit
        assert effective['runtime_governance_source'] == 'client'
        assert not effective['runtime_governance_builtin']


def test_hook_connection_states_do_not_infer_authorization_from_receiver():
    from backend.runtime_governance import hook_connections
    at = datetime.utcnow().isoformat()+'Z'
    policy = {'runtime_governance': default_runtime_governance()}
    host = {'agent':'codex','installed':False,'enabled':False,'hook_trust':'unknown','reported_at':at,'source_code':'aidr_plugin_not_installed'}
    observation = {'hosts':[host], 'channels':{'hooks':{'state':'running','reported_at':at}}}
    def state(data=observation, stale=False, target=policy):
        return hook_connections(target, data, stale, {'hosts':[]})[1]
    assert state()['installation'] == 'not_installed'
    assert state()['authorization'] == 'unknown'
    assert state()['receiver'] == 'running'
    assert state()['event_received_at'] is None
    observation['hosts'][0] = host | {'installed':True,'enabled':True,'hook_trust':'needs_review'}
    assert state()['authorization'] == 'review_required'
    observation['hosts'][0]['hook_trust'] = 'trusted'
    assert state()['authorization'] == 'authorized'
    assert state(stale=True)['authorization'] == state(stale=True)['installation'] == 'unknown'
    assert state(stale=True)['receiver'] == 'unknown'
    observation['hosts'][0] = host | {'source_code':'aidr_desktop_host_missing','installed':None,'enabled':None}
    assert state()['installation'] == 'host_missing'
    observation['hosts'][0] = host
    observation['policy_code'] = 'aidr_managed_authorization_cancelled'
    assert state(target={'runtime_governance': default_runtime_governance() | {'access_mode':'managed'}})['authorization'] == 'cancelled'
    observation['hosts'][0]['reported_at'] = (datetime.utcnow()-timedelta(minutes=4)).isoformat()+'Z'
    assert state()['installation'] == 'not_installed'
    observation['hosts'][0]['reported_at'] = (datetime.utcnow()-timedelta(minutes=9)).isoformat()+'Z'
    assert state()['installation'] == 'unknown'
