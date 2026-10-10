import base64
import copy
import json
import hashlib
import time
import uuid
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend import auth, models
from backend.routers import aidr_enforcement
from tests.test_aidr_api import service


def test_management_routes_reuse_device_permissions():
    from backend.iam_routes import route_permission
    for suffix, permission in [('policy','clients:update'),('terminate','clients:execute')]:
        path='/api/v1/clients/{client_id}/aidr/enforcement/'+suffix
        request=SimpleNamespace(scope={'route':SimpleNamespace(path=path)},url=SimpleNamespace(path=path),method='POST')
        assert route_permission(request)==permission


@pytest.fixture
def control(service, tmp_path, monkeypatch):
    client,factory=service
    client.app.include_router(aidr_enforcement.router,prefix='/api')
    key=ec.generate_private_key(ec.SECP256R1())
    path=tmp_path/'signing.pem'
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    path.chmod(0o600);monkeypatch.setenv('AIDR_POLICY_SIGNING_KEY_FILE',str(path))
    return client,factory,key


def policy():
    return dict(expected_revision='0',lifetime_seconds=3600,unknown_actor_action='allow',expired_action='deny',agent_executables=['/private/tmp/agent'],rules=[dict(id='protect',path='/private/tmp/protected',actor='agent',decision='deny')])


def event():
    return dict(schema_version=1,boot_id=str(uuid.uuid4()),monitor_id=str(uuid.uuid4()),sequence='1',time_ns='1800000000000000000',kind='process',process=dict(pid='12345',pidversion='42',start_us='1800000000000000'),root=dict(pid='12345',pidversion='42',start_us='1800000000000000'),relation='direct',transition='exec',reason_code='aidr_process_exec')


ROOT='/api/v1/clients/one/aidr/enforcement'
HEADERS={'authorization':'Bearer test-one'}


def test_collection_bootstrap_checks_device_channel_policy_and_exposes_only_public_key(control, monkeypatch):
    from backend import client_governance
    client, factory, key = control
    target = {'enabled': True, 'channels': None}
    monkeypatch.setattr(client_governance, 'policy_view', lambda *args: {'runtime_governance': target, 'runtime_governance_version': '1'})
    assert client.get(ROOT+'/bootstrap').status_code == 401
    assert client.get(ROOT.replace('/one/', '/two/')+'/bootstrap', headers=HEADERS).status_code == 403
    response = client.get(ROOT+'/bootstrap', headers=HEADERS)
    assert response.status_code == 409 and response.json()['error_code'] == 'aidr.system_collection_disabled'
    target['channels'] = {'system': True}
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['error_code'] == 'aidr.system_policy_required'
    assert client.post(ROOT+'/policy', json=policy()).status_code == 200
    response = client.get(ROOT+'/bootstrap', headers=HEADERS)
    assert response.status_code == 200
    assert set(response.json()) == {'public_key', 'revision', 'runtime_policy_version', 'mode'}
    assert response.json()['mode'] == 'audit'
    target['modes'] = {'hooks': 'audit', 'system': 'intercept'}
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['mode'] == 'intercept'
    assert base64.b64decode(response.json()['public_key']) == key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    target['enabled'] = False
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['error_code'] == 'aidr.system_collection_disabled'


def test_collection_bootstrap_renews_expired_policy_without_changing_configuration(control, monkeypatch):
    from backend import aidr_enforcement as policy_module
    from backend import client_governance
    from backend.aidr_enforcement import AidrEnforcementRevision
    client, factory, _ = control
    monkeypatch.setattr(client_governance, 'policy_view', lambda *args: {
        'runtime_governance': {'enabled': True, 'channels': {'system': True}},
        'runtime_governance_version': '1',
    })
    assert client.post(ROOT+'/policy', json=policy()).status_code == 200
    with factory() as db:
        original = db.query(AidrEnforcementRevision).filter_by(client_id='one', revision=1).one()
        original_policy = json.loads(original.policy_json)
        fake_now = int(original_policy['expires_at']) + 1
    clock = SimpleNamespace(time=lambda: fake_now)
    monkeypatch.setattr(aidr_enforcement, 'time', clock)
    monkeypatch.setattr(policy_module, 'time', clock)

    response = client.get(ROOT+'/bootstrap', headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == '2'
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['revision'] == '2'
    with factory() as db:
        renewed = db.query(AidrEnforcementRevision).filter_by(client_id='one', revision=2).one()
        renewed_policy = json.loads(renewed.policy_json)
        assert renewed.created_by == 'system:auto-renew'
        assert renewed_policy['agent_executables'] == original_policy['agent_executables']
        assert renewed_policy['rules'] == original_policy['rules']
        assert renewed_policy['unknown_actor_action'] == original_policy['unknown_actor_action']
        assert renewed_policy['expired_action'] == original_policy['expired_action']
        assert int(renewed_policy['expires_at']) > fake_now

    assert client.get(ROOT+'/history').json()['items'][0]['revision'] == '1'
    current = client.get(ROOT+'/policy').json()
    assert current['revision'] == '2'
    assert current['created_by'] == 'owner'


def test_hook_key_bootstrap_is_device_authenticated_and_public_only(control):
    client, _, key = control
    path = '/api/v1/clients/one/aidr/hook-control/bootstrap'
    assert client.post(path, json={}).status_code == 401
    assert client.post(path.replace('/one/', '/two/'), headers=HEADERS, json={}).status_code == 403
    response = client.post(path, headers=HEADERS, json={})
    assert response.status_code == 200
    assert set(response.json()) == {'public_key'}
    assert base64.b64decode(response.json()['public_key']) == key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


@pytest.mark.parametrize('platform,support', [('darwin', 'macos_endpoint_security'), ('macos', 'macos_endpoint_security'), ('windows', 'unsupported_platform'), ('linux', 'unsupported_platform'), ('', 'unreported_platform')])
def test_platform_support_does_not_claim_executor_authorization(control, platform, support):
    client, factory, _ = control
    with factory() as db:
        db.query(models.ManagedClient).filter_by(client_id='one').one().os = platform
        db.commit()
    response = client.get(ROOT + '/status')
    assert response.status_code == 200
    status = response.json()
    assert status['platform'] == platform
    assert status['platform_support'] == support
    assert status['state'] == 'unknown'
    assert status['health'] is None


def test_signed_snapshot_permissions_revision_and_revoke(control):
    client,factory,key=control
    assert client.get(ROOT+'/snapshot',headers=HEADERS).json()=={'envelope':None}
    result=client.post(ROOT+'/policy',json=policy());assert result.status_code==200,result.text
    assert result.json()['revision']=='1'
    delivered=client.get(ROOT+'/snapshot',headers=HEADERS).json()['envelope']
    key.public_key().verify(base64.b64decode(delivered['signature']),base64.b64decode(delivered['payload']),ec.ECDSA(hashes.SHA256()))
    assert json.loads(base64.b64decode(delivered['payload']))['device']=='one'
    assert client.post(ROOT+'/policy',json=policy()).status_code==409
    assert client.get(ROOT.replace('/one/','/two/')+'/snapshot',headers=HEADERS).status_code==403
    revoked=policy();revoked.update(expected_revision='1',rules=[])
    assert client.post(ROOT+'/policy',json=revoked).json()['revision']=='2'
    rollback=policy();rollback['expected_revision']='2'
    assert client.post(ROOT+'/policy',json=rollback).json()['revision']=='3'
    actor=models.User(id=1,username='owner',role='user')
    client.app.dependency_overrides[auth.get_current_admin_user]=lambda:actor
    assert client.post(ROOT+'/policy',json=rollback).status_code==403
    assert client.get(ROOT.replace('/one/','/two/')+'/policy').status_code==404


def test_runtime_durable_replay_and_precise_response(control):
    client,factory,key=control
    row=event();body={'records':[row]}
    first=client.post(ROOT+'/records',json=body,headers=HEADERS);assert first.status_code==200,first.text
    assert client.post(ROOT+'/records',json=body,headers=HEADERS).json()==first.json()
    assert len(client.get(ROOT+'/records').json()['items'])==1
    assert client.get(ROOT+'/records?kind=authorization').json()['items']==[]
    assert len(client.get(ROOT+'/records?kind=process').json()['items'])==1
    conflicting=copy.deepcopy(body);conflicting['records'][0]['transition']='exit'
    assert client.post(ROOT+'/records',json=conflicting,headers=HEADERS).status_code==409
    target={k:row[k] for k in ('boot_id','monitor_id','process')};request=dict(**target,request_id=str(uuid.uuid4()))
    health={**row, 'kind':'health', 'sequence':'100', 'time_ns':str(time.time_ns()), 'reason_code':'aidr_enforcement_active'}
    assert client.post(ROOT+'/records',json={'records':[health]},headers=HEADERS).status_code==200
    result=client.post(ROOT+'/terminate',json=request);assert result.status_code==200,result.text
    assert client.post(ROOT+'/terminate',json=request).json()==result.json()
    changed=copy.deepcopy(request);changed['process']['pidversion']='43'
    assert client.post(ROOT+'/terminate',json=changed).status_code==409
    command=client.get(ROOT+'/commands',headers=HEADERS).json()['items'][0]
    key.public_key().verify(base64.b64decode(command['signature']),base64.b64decode(command['payload']),ec.ECDSA(hashes.SHA256()))
    executed={**row,'sequence':'2','kind':'response','transition':'','command_id':result.json()['id'],'result':'executed','reason_code':'aidr_response_executed'}
    assert client.post(ROOT+'/records',json={'records':[executed]},headers=HEADERS).status_code==200
    assert client.get(ROOT+'/responses').json()['items'][0]['state']=='executed'
    verified={**executed,'sequence':'3','result':'verified','reason_code':'aidr_response_exit_observed'}
    assert client.post(ROOT+'/records',json={'records':[verified]},headers=HEADERS).status_code==200
    assert client.get(ROOT+'/responses').json()['items'][0]['state']=='verified'
    wrong={**verified,'sequence':'4','boot_id':str(uuid.uuid4())}
    assert client.post(ROOT+'/records',json={'records':[wrong]},headers=HEADERS).status_code==409
    assert client.get(ROOT+'/commands',headers=HEADERS).json()['items']==[]
    assert client.post(ROOT+'/records',json=body,headers={'authorization':'Bearer test-two'}).status_code==403


def test_bad_policy_and_unknown_target_rejected(control,monkeypatch):
    client,_,_=control
    invalid=policy();invalid['rules'][0]['path']='/tmp/../secret'
    assert client.post(ROOT+'/policy',json=invalid).status_code==422
    monkeypatch.delenv('AIDR_POLICY_SIGNING_KEY_FILE')
    assert client.post(ROOT+'/policy',json=policy()).status_code==503
    row=event();request={k:row[k] for k in ('boot_id','monitor_id','process')};request['request_id']=str(uuid.uuid4())
    assert client.post(ROOT+'/terminate',json=request).status_code==409
    row['sequence']='18446744073709551616'
    result=client.post(ROOT+'/records',json={'records':[row]},headers=HEADERS)
    assert result.status_code==422 and result.json()['error_code']=='aidr.enforcement_records_invalid'


def test_health_freshness_history_and_exact_wire_ack(control):
    client, _, _ = control
    assert client.get(ROOT+'/status').json()['state'] == 'unknown'
    assert client.post(ROOT+'/policy', json=policy()).status_code == 200
    history = client.get(ROOT+'/history').json()['items']
    assert len(history) == 1 and history[0]['revision'] == '1'
    row = event()
    row.update(kind='health', transition='', revision='1', reason_code='aidr_enforcement_active', time_ns=str(time.time_ns()))
    raw = json.dumps({'records': [row]}, indent=2).encode()
    reply = client.post(ROOT+'/records', content=raw, headers={**HEADERS, 'content-type':'application/json'})
    assert reply.status_code == 200
    assert reply.json()['digest'] == hashlib.sha256(raw).hexdigest()
    assert reply.json()['durable'] is True
    assert client.get(ROOT+'/status').json()['state'] == 'active'
    row.update(sequence='2', time_ns=str(time.time_ns()-60_000_000_000))
    assert client.post(ROOT+'/records', json={'records':[row]}, headers=HEADERS).status_code == 200
    assert client.get(ROOT+'/status').json()['state'] == 'stale'
    row.update(sequence='3', time_ns=str(time.time_ns()), gaps='1')
    assert client.post(ROOT+'/records', json={'records':[row]}, headers=HEADERS).status_code == 200
    assert client.get(ROOT+'/status').json()['state'] == 'degraded'
    row.update(sequence='4', reason_code='aidr_enforcement_stopped')
    assert client.post(ROOT+'/records', json={'records':[row]}, headers=HEADERS).status_code == 200
    assert client.get(ROOT+'/status').json()['state'] == 'stopped'
    row.update(sequence='5', reason_code='aidr_enforcement_native_exit')
    assert client.post(ROOT+'/records', json={'records':[row]}, headers=HEADERS).status_code == 200
    assert client.get(ROOT+'/status').json()['state'] == 'failed'


def test_target_actionability_and_receipt_validity(control):
    client, factory, _ = control
    row = {**event(), "sequence":"10"}
    def send(value):
        assert client.post(ROOT+'/records', json={'records':[value]}, headers=HEADERS).status_code == 200
    def attempt(value=row):
        return client.post(ROOT+'/terminate',json={**{k:value[k] for k in ('boot_id','monitor_id','process')},'request_id':str(uuid.uuid4())})
    send(row)
    assert attempt().json()['error_code']=='aidr.enforcement_executor_inactive'
    health={**row,'kind':'health','sequence':'100','time_ns':str(time.time_ns()),'reason_code':'aidr_enforcement_active'}
    send(health)
    assert client.get(ROOT+'/records?kind=process').json()['items'][0]['can_terminate'] is True
    request=attempt();assert request.status_code==200
    old={**row,'monitor_id':str(uuid.uuid4())}
    assert attempt(old).json()['error_code']=='aidr.enforcement_monitor_changed'
    send({**row,'sequence':'12','transition':'exit'})
    send({**row,'sequence':'11','transition':'exec'})
    # A delayed duplicate exec must not supersede the higher source sequence exit.
    assert attempt().json()['error_code']=='aidr.enforcement_target_exited'
    assert not client.get(ROOT+'/records?kind=process').json()['items'][-1]['can_terminate']
    for n, reason in enumerate(['aidr_enforcement_stopped','aidr_enforcement_native_exit'],101):
        send({**health,'sequence':str(n),'reason_code':reason})
        assert attempt().json()['error_code']=='aidr.enforcement_executor_inactive'
    from backend.aidr_enforcement import AidrResponseCommand
    with factory() as db:
        command=db.get(AidrResponseCommand,request.json()['id']);command.expires_at=int(time.time())-1;db.commit()
    assert client.get(ROOT+'/responses').json()['items'][0]['display_state']=='expired_unconfirmed'
    with factory() as db:
        command=db.get(AidrResponseCommand,request.json()['id']);command.state='verified';db.commit()
    receipt=client.get(ROOT+'/responses').json()['items'][0]
    assert receipt['expired'] and receipt['display_state']=='verified'


def test_capability_fields_optional_and_independent():
    from backend.routers.aidr import Capability
    legacy=Capability(agent='codex',version='0.158.0-alpha.2.1',status='unavailable')
    assert legacy.parser_status is None
    current=Capability(**legacy.model_dump(exclude_none=True),parser_status='available',parser_version='agentlog/1')
    assert current.status=='unavailable' and current.parser_status=='available'


def test_collection_mode_preserves_evidence_and_rejects_response(control):
    client, factory, _ = control
    row = event()
    assert client.post(ROOT+'/records', json={'records':[row]}, headers=HEADERS).status_code == 200
    health = {**row, 'kind':'health', 'sequence':'2', 'transition':'',
              'time_ns':str(time.time_ns()), 'reason_code':'aidr_enforcement_collection_only'}
    assert client.post(ROOT+'/records', json={'records':[health]}, headers=HEADERS).status_code == 200
    assert client.get(ROOT+'/status').json()['state'] == 'collecting'
    evidence = client.get(ROOT+'/records?kind=process').json()['items'][0]
    assert evidence['record']['process'] == row['process']
    assert evidence['can_terminate'] is False
    assert evidence['termination_reason'] == 'enforcement_control_not_enabled'
    request = {**{k:row[k] for k in ('boot_id','monitor_id','process')}, 'request_id':str(uuid.uuid4())}
    rejected = client.post(ROOT+'/terminate', json=request)
    assert rejected.status_code == 409
    assert rejected.json()['error_code'] == 'aidr.enforcement_control_not_enabled'
    from backend.aidr_enforcement import AidrResponseCommand
    with factory() as db:
        assert db.query(AidrResponseCommand).count() == 0
    health.update(sequence='3', gaps='1')
    assert client.post(ROOT+'/records', json={'records':[health]}, headers=HEADERS).status_code == 200
    assert client.get(ROOT+'/status').json()['state'] == 'degraded'
    health.update(sequence='4', gaps='0', time_ns=str(time.time_ns()-60_000_000_000))
    assert client.post(ROOT+'/records', json={'records':[health]}, headers=HEADERS).status_code == 200
    assert client.get(ROOT+'/status').json()['state'] == 'stale'
    assert client.get(ROOT+'/records?kind=process').json()['items'][0]['can_terminate'] is False


def test_short_lease_renewal_preserves_editor_configuration_revision(control, monkeypatch):
    from backend import aidr_enforcement as policy_module, client_governance
    client, _, _ = control
    monkeypatch.setattr(client_governance, 'policy_view', lambda *args: {
        'runtime_governance': {'enabled': True, 'channels': {'system': True}}, 'runtime_governance_version': '1'})
    body = policy() | {'lifetime_seconds': 60, 'expected_configuration_revision': '0'}
    first = client.post(ROOT+'/policy', json=body).json()
    now = int(first['policy']['issued_at'])
    clock = SimpleNamespace(time=lambda: now)
    monkeypatch.setattr(aidr_enforcement, 'time', clock)
    monkeypatch.setattr(policy_module, 'time', clock)
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['revision'] == '1'
    now += 44
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['revision'] == '1'
    now += 1
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['revision'] == '2'
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['revision'] == '2'
    assert client.get(ROOT+'/policy').json()['configuration_revision'] == '1'
    body.update(expected_revision='1', expected_configuration_revision='1', rules=[])
    saved = client.post(ROOT+'/policy', json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['revision'] == saved.json()['configuration_revision'] == '3'
    assert client.post(ROOT+'/policy', json=body).status_code == 409


def test_operation_evidence_round_trip_context_and_filtering(control):
    client, _, _ = control
    root = event()
    records = [root | {'argv': ['/bin/sh', '-c', 'printf token=verbatim\nexit 7'], 'cwd': '/private/tmp', 'argv_truncated': False}]
    for index, operation in enumerate(('create', 'modify', 'rename', 'delete'), 2):
        records.append(root | {'sequence': str(index), 'kind': 'file', 'transition': '', 'operation': operation,
                               'path': '/private/tmp/a\nfile', 'destination_path': '/private/tmp/b' if operation == 'rename' else None,
                               'result': 'observed', 'reason_code': 'aidr_file_'+operation})
    records += [root | {'sequence': '6', 'transition': 'exit', 'exit_code': 7, 'duration_ms': '234'},
                root | {'sequence': '7', 'activity_origin': 'client_probe'},
                root | {'sequence': '8', 'transition': 'fork'},
                root | {'sequence': '9', 'process': root['process'] | {'pidversion': '43'}}]
    result = client.post(ROOT+'/records', headers=HEADERS, json={'records': records})
    assert result.status_code == 200, result.text
    assert client.post(ROOT+'/records', headers=HEADERS, json={'records': records}).status_code == 200
    all_rows = client.get(ROOT+'/records').json()['items']
    command = next(row for row in all_rows if row['record']['sequence'] == '1')
    assert command['record']['argv'] == records[0]['argv']
    visible = client.get(ROOT+'/records?kind=activity&include_probes=false').json()['items']
    assert {row['record']['sequence'] for row in visible} == {'1','2','3','4','5','6','9'}
    context = client.get(ROOT+f"/records/{command['id']}/context").json()
    assert [row['record']['sequence'] for row in context['items']] == [str(i) for i in range(1,9)]
    assert not context['truncated']
    assert client.get(ROOT.replace('/one/', '/two/')+f"/records/{command['id']}/context").status_code == 404
    legacy = next(row['record'] for row in all_rows if row['record']['sequence'] == '8')
    assert 'argv' not in legacy and 'exit_code' not in legacy
    oversized = root | {'sequence':'10', 'argv':['a'*8193]}
    assert client.post(ROOT+'/records', headers=HEADERS, json={'records':[oversized]}).status_code == 422


def test_network_snapshots_ack_filter_context_and_validation(control):
    client, factory, _ = control
    first = event()
    first.update(kind='network', transition='', reason_code='aidr_network_snapshot', network=dict(
        source='libproc_snapshot', observation_id=str(uuid.uuid4()), protocol='tcp', direction='unknown',
        local_ip='::1', local_port=43210, remote_ip='::1', remote_port=8765, state='established'))
    second = copy.deepcopy(first)
    second['sequence'] = '2'
    second['network']['observation_id'] = str(uuid.uuid4())
    second['network']['local_port'] = 43211
    payload = {'records': [first, second]}
    response = client.post(ROOT+'/records', headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    ack = response.json()
    assert client.post(ROOT+'/records', headers=HEADERS, json=payload).json() == ack
    rows = client.get(ROOT+'/records?kind=network').json()['items']
    assert len(rows) == 2
    assert len({r['record']['network']['observation_id'] for r in rows}) == 2
    assert all('bytes_sent' not in r['record']['network'] for r in rows)
    assert len(client.get(ROOT+'/records?kind=activity').json()['items']) == 2
    context = client.get(ROOT+f"/records/{rows[0]['id']}/context").json()['items']
    assert len(context) == 2
    for change in [dict(state='failed'), dict(remote_ip='guess.example'), dict(direction='outbound'), dict(protocol='udp'), dict(remote_port=65536)]:
        bad = copy.deepcopy(first); bad['network'].update(change)
        assert client.post(ROOT+'/records', headers=HEADERS, json={'records':[bad]}).status_code == 422
    legacy = event(); legacy['sequence']='3'
    assert client.post(ROOT+'/records', headers=HEADERS, json={'records':[legacy]}).status_code == 200
    assert client.get(ROOT+'/records?kind=process').json()['items'][0]['record'].get('network') is None


def test_agent_root_filter_scopes_history_pagination_and_descendants(control):
    from backend.aidr_enforcement import AidrRuntimeRecord
    client, factory, _ = control
    base = event()
    agent_a, agent_b = '/apps/Claude/claude', '/apps/Codex/codex'
    records = [
        base | {'root_path': agent_a, 'sequence': '1'},
        base | {'root_path': agent_b, 'sequence': '2'},
        base | {'root_path': agent_a, 'sequence': '3', 'activity_origin': 'client_probe'},
        base | {'root_path': agent_a, 'sequence': '4', 'relation': 'inherited', 'executable': '/bin/sh'},
        base | {'sequence': '5'},
        base | {'root_path': '/expired/agent', 'sequence': '6'},
    ]
    response = client.post(ROOT+'/records', headers=HEADERS, json={'records': records})
    assert response.status_code == 200, response.text
    with factory() as db:
        db.query(AidrRuntimeRecord).filter_by(client_id='one', sequence='6').update({'expired_at': '2026-01-01T00:00:00Z'})
        db.commit()
    assert client.get(ROOT+'/record-agents').json()['items'] == [{'root_path': agent_a}, {'root_path': agent_b}]
    params = {'root_path': agent_a, 'kind': 'process', 'include_probes': False, 'limit': 1}
    first = client.get(ROOT+'/records', params=params).json()
    assert [r['record']['sequence'] for r in first['items']] == ['4']
    assert first['has_more']
    second = client.get(ROOT+'/records', params=params | {'before': first['next_before']}).json()
    assert [r['record']['sequence'] for r in second['items']] == ['1']
    assert not second['has_more']
    assert len(client.get(ROOT+'/records', params={'root_path': agent_a}).json()['items']) == 3
    assert not client.get(ROOT+'/records', params={'root_path': '/bin/sh'}).json()['items']
    assert not client.get(ROOT+'/records', params={'root_path': '/apps/%'}).json()['items']
    assert client.get(ROOT+'/records', params={'root_path': 'x' * 1024}).status_code == 422
    assert client.get(ROOT.replace('/one/', '/two/')+'/record-agents').status_code == 404


def test_runtime_queries_seek_indexes_and_keep_full_instance_identity(control):
    from sqlalchemy import event as sql_event
    from backend.aidr_enforcement import AidrRuntimeRecord
    client, factory, _ = control
    base = event() | {'root_path': '/Applications/WorkBuddy.app/Contents/MacOS/Electron'}
    sequences = [*range(1, 206), 9007199254740993, 18446744073709551615]
    with factory() as db:
        # Insert out of sequence: arrival IDs must not replace numeric event order.
        for sequence in reversed(sequences):
            value = base | {'sequence': str(sequence)}
            db.add(AidrRuntimeRecord(client_id='one', monitor_id=value['monitor_id'],
                sequence=value['sequence'], kind='process', payload_json=json.dumps(value), received_at='2026-10-09'))
        variants = [
            {'process': base['process'] | {field: '999'}} for field in ('pid', 'pidversion', 'start_us')
        ] + [{'boot_id': str(uuid.uuid4())}, {'monitor_id': str(uuid.uuid4())}, {}, {}]
        for index, changes in enumerate(variants):
            value = base | changes | {'sequence': str(300 + index), 'root_path': f'/other/{index}'}
            db.add(AidrRuntimeRecord(client_id='two' if index == 5 else 'one', monitor_id=value['monitor_id'],
                sequence=value['sequence'], kind='process', payload_json=json.dumps(value), received_at='2026-10-09',
                expired_at='2026-10-09' if index == 6 else None))
        db.commit()
        ident = db.query(AidrRuntimeRecord.id).filter_by(client_id='one', sequence='1').scalar()
    statements = []
    engine = factory.kw['bind']
    def capture(conn, cursor, statement, parameters, context, many):
        if 'aidr_runtime_records' in statement:
            statements.append((statement, parameters))
    sql_event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = client.get(ROOT + f'/records/{ident}/context').json()
        agents = client.get(ROOT + '/record-agents').json()['items']
        for root in ('', base['root_path']):
            response = client.get(ROOT + '/records', params={'kind': 'activity', 'root_path': root})
            assert response.status_code == 200
    finally:
        sql_event.remove(engine, 'before_cursor_execute', capture)
    assert result['truncated']
    assert [int(item['record']['sequence']) for item in result['items']] == sequences[-200:]
    assert {'root_path': '/other/5'} not in agents and {'root_path': '/other/6'} not in agents
    assert agents == sorted(agents, key=lambda item: item['root_path'])
    with engine.connect() as conn:
        for sql, params in statements:
            plan = ' '.join(row[3] for row in conn.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params))
            if 'WITH RECURSIVE roots' in sql:
                assert plan.count('ix_aidr_runtime_agent_roots') == 2
                assert '<expr>>?' in plan
            elif 'ORDER BY length' in sql:
                assert 'ix_aidr_runtime_instance_sequence' in plan
                assert plan.count('<expr>=?') == 4
                assert 'TEMP B-TREE' not in plan
            elif 'ORDER BY aidr_runtime_records.id DESC' in sql:
                assert 'TEMP B-TREE' not in plan
