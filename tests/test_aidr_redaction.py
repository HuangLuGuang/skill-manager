import copy
import json
from datetime import datetime
from pathlib import Path

import pytest
from backend import models, aidr_policy
from backend.aidr_behavior import Behavior
from backend.aidr_redaction import redact_values
from tests.test_aidr_api import service, batch, submit


def behavior(policy, command):
    return dict(version=3, policy=policy, category='command', method='direct_fields', actions=[dict(tool='Bash',category='command',command=command,cwd='',targets=[],source_fields=['command'])], status='unknown',result_basis=[],redacted=False,truncated=False,uncertainty=[])


def test_shared_redaction_vectors():
    vectors=json.loads((Path(__file__).parents[1]/'scanner/internal/aidr/agentlog/testdata/redaction.json').read_text())
    for item in vectors:
        assert redact_values(item['input']) == item['expected']
        assert redact_values(item['expected']) == item['expected']
        for enabled in (True,False):
            p=dict(version='1',enabled=enabled,receipt='f'*32)
            command=item['expected'] if enabled else item['input']
            assert Behavior.model_validate(behavior(p,command)).actions[0].command == command


def test_receipts_switch_backlog_lost_response_and_forgery(service):
    client,factory=service
    headers={'authorization':'Bearer test-one'}
    request=dict(stream_id='a'*32,last_sequence='0')
    endpoint='/api/v1/clients/one/aidr/audit-policy'
    on=client.post(endpoint,json=request,headers=headers).json()
    assert on['enabled'] is True and on['version']=='1'
    with factory() as db:
        assert aidr_policy.current(db)['enabled']
        db.add(models.SystemConfig(key=aidr_policy.KEY,value=json.dumps(dict(enabled=False,version='2'))));db.commit()
    off=client.post(endpoint,json=request,headers=headers).json()
    assert off['enabled'] is False
    # A retry after a lost response returns the same receipt, without closing the cached policy.
    assert client.post(endpoint,json={**request,'last_sequence':'4'},headers=headers).json()==off
    with factory() as db:
        assert db.get(models.AidrPolicyReceipt,on['receipt']).end_sequence is None
    value=batch();event=value['records'][0]['payload'];event['schema_version']=2
    command='tool --password "synthetic-secret" && git status'
    event['behavior']=behavior(off,command)
    result=submit(client,value);assert result.status_code==200,result.text
    assert submit(client,value).json()==result.json()
    with factory() as db:
        row=db.get(models.SystemConfig,aidr_policy.KEY);row.value=json.dumps(dict(enabled=True,version='3'));db.commit()
    applied={**request,'last_sequence':'4','applied_receipt':off['receipt'],'applied_after':'0'}
    new=client.post(endpoint,json=applied,headers=headers).json()
    # OFF backlog remains accepted after target switches ON, until actual application is acknowledged.
    pending=copy.deepcopy(value);pending['records'][0]['sequence']='3';pending['records'][0]['record_id']='e'*64;pending['records'][0]['payload']['logical_event_id']='e'*64
    assert client.post(endpoint,json={**applied,'applied_receipt':new['receipt'],'applied_after':'4'},headers=headers).status_code==200
    assert submit(client,pending).status_code==200
    assert submit(client,value,credential='two',target='two').status_code==409
    assert submit(client,value,extra_headers={'x-aidr-stream-id':'b'*32}).status_code==409
    forged=copy.deepcopy(pending);forged['records'][0]['sequence']='5';forged['records'][0]['record_id']='d'*64;forged['records'][0]['payload']['logical_event_id']='d'*64
    assert submit(client,forged).status_code==409
    for field,val in [('version','999'),('receipt','0'*32),('enabled',True)]:
        bad=copy.deepcopy(forged);bad['records'][0]['payload']['behavior']['policy'][field]=val
        assert submit(client,bad).status_code in (422,409)
    bad=copy.deepcopy(forged);bad['records'][0]['payload']['behavior']['policy']=new
    assert submit(client,bad).status_code==422
    rows=client.get('/api/v1/clients/one/aidr/events').json()['items']
    assert 'command' not in rows[0]['event']['behavior']['actions'][0]
    assert 'synthetic-secret' not in json.dumps(rows)
    with factory() as db:
        stored = db.query(models.AidrEvent).filter_by(logical_id=rows[0]['event']['logical_event_id']).one()
        assert json.loads(stored.payload_json)['behavior']['actions'][0]['command'] == command
    assert submit(client,value).status_code==200
    assert client.post(endpoint,json=request,headers={'authorization':'Bearer test-two'}).status_code==403


def test_settings_authorization_audit_and_legacy_state(service):
    from backend import auth, iam
    from backend.routers import system
    from backend.iam_models import ManagementAudit
    client,factory=service
    client.app.include_router(system.router,prefix='/api')
    actor=models.User(id=1,username='owner',role='admin',is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user]=lambda:actor
    with factory() as db:
        iam.initialize(db)
    url='/api/system/aidr-redaction'
    first=client.get(url);assert first.status_code==200,first.text
    assert first.json()['enabled'] is True
    result=client.put(url,json={'enabled':False,'version':'1'});assert result.status_code==200,result.text
    assert result.json()['version']=='2'
    assert client.put(url,json={'enabled':True,'version':'1'}).status_code==409
    actor.role='user'
    assert client.put(url,json={'enabled':True,'version':'2'}).status_code==403
    actor.role='admin'
    assert client.put(url,json={'enabled':True,'version':'2'}).status_code==200
    state=client.get('/api/v1/clients/one/aidr/status').json()
    assert not state['health'].get('audit_policy')
    with factory() as db:
        audits=db.query(ManagementAudit).filter_by(target='aidr_audit_redaction').all()
        assert len(audits)==2


def test_duplicate_log_from_new_stream_keeps_original_evidence_and_drains_batch(service):
    client, factory = service
    endpoint = '/api/v1/clients/one/aidr/audit-policy'
    policies = [client.post(endpoint, json={'stream_id': stream * 32, 'last_sequence': '0'},
                            headers={'authorization': 'Bearer test-one'}).json() for stream in ('a', 'b')]
    assert policies[0]['receipt'] != policies[1]['receipt']
    value = batch()
    event = value['records'][0]['payload']
    event.update(schema_version=2, behavior=behavior(policies[0], 'printf replay-check'))
    assert submit(client, value).status_code == 200
    with factory() as db:
        original = db.query(models.AidrEvent).one()
        preserved = original.payload_json, original.content_hash, original.received_at
    replay = copy.deepcopy(value)
    replay['records'][0]['payload']['behavior']['policy'] = policies[1]
    following = copy.deepcopy(replay['records'][0])
    following.update(sequence='2', record_id='e' * 64)
    following['payload']['logical_event_id'] = 'e' * 64
    replay['records'].append(following)
    headers = {'x-aidr-stream-id': 'b' * 32}
    response = submit(client, replay, extra_headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['accepted'] == 2 and response.json()['durable']
    assert submit(client, replay, extra_headers=headers).json() == response.json()
    with factory() as db:
        original = db.query(models.AidrEvent).filter_by(logical_id=event['logical_event_id']).one()
        assert (original.payload_json, original.content_hash, original.received_at) == preserved
        assert db.query(models.AidrEvent).count() == 2
        assert db.query(models.AidrBatch).count() == 2

    forged = copy.deepcopy(replay)
    forged['records'][0]['payload']['behavior']['policy'] = policies[0]
    result = submit(client, forged, extra_headers=headers)
    assert result.status_code == 409 and result.json()['error_code'] == 'aidr.redaction_policy_invalid'
    changed = copy.deepcopy(replay)
    changed['records'][0]['payload']['behavior']['actions'][0]['command'] = 'printf changed-content'
    changed['records'][0]['payload']['content_digest'] = 'f' * 64
    result = submit(client, changed, extra_headers=headers)
    assert result.status_code == 409 and result.json()['error_code'] == 'aidr.event_conflict'
    result = submit(client, changed, extra_headers=headers, key=response.json()['batch_id'])
    assert result.status_code == 409 and result.json()['error_code'] == 'aidr.idempotency_conflict'

    expired_replay = copy.deepcopy(replay)
    expired_replay['records'][0]['sequence'] = '3'
    expired_replay['records'] = expired_replay['records'][:1]
    with factory() as db:
        original = db.query(models.AidrEvent).filter_by(logical_id=event['logical_event_id']).one()
        original.payload_json = '{}'
        original.expired_at = datetime.utcnow()
        db.commit()
    result = submit(client, expired_replay, extra_headers=headers)
    assert result.status_code == 200, result.text
    with factory() as db:
        assert db.query(models.AidrEvent).filter_by(logical_id=event['logical_event_id']).one().payload_json == '{}'


def test_same_log_with_changed_result_projection_keeps_first_result(service):
    client, factory = service
    endpoint = '/api/v1/clients/one/aidr/audit-policy'
    policies = [client.post(endpoint, json={'stream_id': stream * 32, 'last_sequence': '0'},
                            headers={'authorization': 'Bearer test-one'}).json() for stream in ('a', 'b')]
    value = batch()
    event = value['records'][0]['payload']
    result = behavior(policies[0], 'printf result-check')
    result.update(method='result_fields', actions=[], status='reported_success', exit_code=0, result_basis=['structured_exit_code'])
    event.update(schema_version=2, kind='tool_result', behavior=result)
    response = submit(client, value)
    assert response.status_code == 200, response.text
    replay = copy.deepcopy(value)
    incoming = replay['records'][0]['payload']['behavior']
    incoming.pop('exit_code')
    incoming.update(policy=policies[1], status='unknown', result_basis=[],
                    uncertainty=['multiple_result_codes', 'result_semantics_unknown'])
    response = submit(client, replay, extra_headers={'x-aidr-stream-id': 'b' * 32})
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.query(models.AidrBatch).count() == 2
        assert db.query(models.AidrEvent).count() == 1
        assert json.loads(db.query(models.AidrEvent).one().payload_json)['behavior']['exit_code'] == 0


def test_replay_under_new_valid_policy_keeps_original_projection(service):
    client, factory = service
    endpoint = '/api/v1/clients/one/aidr/audit-policy'
    headers = {'authorization': 'Bearer test-one'}
    first = client.post(endpoint, json={'stream_id': 'a' * 32, 'last_sequence': '0'}, headers=headers).json()
    value = batch()
    value['records'][0]['payload'].update(schema_version=2, behavior=behavior(first, 'printf policy-check'))
    assert submit(client, value).status_code == 200
    with factory() as db:
        db.add(models.SystemConfig(key=aidr_policy.KEY, value=json.dumps({'enabled': False, 'version': '2'})))
        db.commit()
    second = client.post(endpoint, json={'stream_id': 'b' * 32, 'last_sequence': '0'}, headers=headers).json()
    value['records'][0]['payload']['behavior']['policy'] = second
    result = submit(client, value, extra_headers={'x-aidr-stream-id': 'b' * 32})
    assert result.status_code == 200, result.text
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 1
        assert json.loads(db.query(models.AidrEvent).one().payload_json)['behavior']['policy'] == first
