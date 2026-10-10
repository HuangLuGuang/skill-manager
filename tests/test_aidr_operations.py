import hashlib
import json
import pytest
from tests.test_aidr_api import service, batch, submit
from backend import models


def event(kind, call='same-call', session='session-a', turn='turn-a', source='a'*64, **changes):
    e=batch()['records'][0]['payload'].copy()
    identity=f'{session}:{turn}:{source}:{call}:{kind}'
    e.update(kind=kind,agent='codex',session_id=session,turn_id=turn,source_id=source,native_call_id=call,tool='exec' if kind=='tool_call' else '',outcome='unknown',logical_event_id=hashlib.sha256(identity.encode()).hexdigest(),event_id=hashlib.sha256(('e'+identity).encode()).hexdigest(),content_digest=hashlib.sha256(('c'+identity).encode()).hexdigest(),observed_at='2026-09-24T00:00:00Z' if kind=='tool_call' else '2026-09-24T00:00:02Z')
    e.update(changes)
    return e


def upload(client,*events):
    return submit(client,{'schema_version':1,'records':[{'sequence':str(i+1),'kind':'event','record_id':e['logical_event_id'],'payload':e} for i,e in enumerate(events)]})


def operations(client, **params):
    response=client.get('/api/v1/clients/one/aidr/operations',params=params)
    assert response.status_code==200,response.text
    return response.json()


def behavior(kind='command'):
    return dict(version=1,category=kind,method='direct_fields',actions=[dict(tool='exec_command',category='command',command='/bin/true',cwd='/tmp/audit',targets=[],source_fields=['cmd','workdir'])],status='unknown',result_basis=[],redacted=False,truncated=False,uncertainty=[])


def test_pairing_independent_namespace_order_and_duplicates(service):
    client,factory=service
    result=event('tool_result')
    assert upload(client,result).status_code==200
    assert operations(client)['items'][0]['status']=='missing_call'
    call=event('tool_call')
    assert upload(client,call).status_code==200
    for _ in range(3):assert upload(client,result,call).status_code==200
    pair=operations(client)['items'][0]
    assert pair['call'] and pair['result'] and pair['log_elapsed_ms']==2000
    assert pair['status']=='unknown' and pair['process_relation']=='unknown'
    other=[event('tool_call',session='session-b'),event('tool_call',turn='turn-b'),event('tool_call',source='b'*64),event('tool_call',call='parallel')]
    assert upload(client,*other).status_code==200
    rows=operations(client)['items']
    assert len(rows)==5 and sum(r['status']=='missing_result' for r in rows)==4
    assert client.get('/api/v1/clients/two/aidr/operations').status_code==404


def test_readable_contract_privacy_and_results(service):
    client,factory=service
    call=event('tool_call',schema_version=2,behavior=behavior())
    result=event('tool_result',schema_version=2,behavior=dict(version=1,category='unknown',method='result_fields',actions=[],status='reported_error',exit_code=7,result_basis=['structured_exit_code'],redacted=False,truncated=False,uncertainty=[]))
    assert upload(client,call,result).status_code==200
    row=operations(client)['items'][0]
    assert row['status']=='reported_error' and row['call']['behavior']['actions'][0]['command']=='/bin/true'
    assert row['result']['behavior']['exit_code']==7
    secret='SyntheticSensitive'*3
    for raw in ('TOKEN='+secret, 'curl --password '+secret, 'curl -H "Authorization: Bearer '+secret+'"','-----BEGIN PRIVATE KEY-----\n'+secret):
        bad=event('tool_call',call='bad',schema_version=2,behavior=behavior())
        bad['behavior']['actions'][0]['command']=raw
        response=upload(client,bad)
        assert response.status_code==422 and secret not in response.text
    bad=event('tool_call',call='raw',schema_version=2,behavior=behavior())
    bad['behavior']['actions'][0]['prompt']=secret
    assert upload(client,bad).status_code==422
    with factory() as db:
        assert db.query(models.AidrEvent).count()==2
        assert secret not in ''.join(r.payload_json for r in db.query(models.AidrOperation))


def test_operation_filters_pagination_and_late_results(service):
    client,_=service
    for i in range(25):
        assert upload(client,event('tool_call',call=f'c{i}',session='filter-session',observed_at=f'2026-09-24T00:00:{i:02d}Z')).status_code==200
    first=operations(client,limit=20,agent='codex',session='filter-session',tool='exec',result='missing_result',since='2026-09-24T00:00:00Z',until='2026-09-24T00:00:30Z')
    assert len(first['items'])==20 and first['has_more']
    second=operations(client,limit=20,cursor=first['next_cursor'])
    assert len(second['items'])==5 and not second['has_more']
    assert not {r['id'] for r in first['items']} & {r['id'] for r in second['items']}
    assert not operations(client,agent='claude')['items']
    assert upload(client,event('tool_result',call='c0',session='filter-session',observed_at='2026-09-24T00:01:00Z')).status_code==200
    assert operations(client)['items'][0]['call']['native_call_id']=='c0'
    assert client.get('/api/v1/clients/one/aidr/operations?cursor=invalid').status_code==422
    import base64
    malformed=base64.urlsafe_b64encode(b'[{},1]').decode()
    assert client.get('/api/v1/clients/one/aidr/operations',params={'cursor':malformed}).status_code==422


def test_conflicting_result_and_unknown_session_do_not_invent_success(service):
    client,_=service
    assert upload(client,event('tool_call'),event('tool_result')).status_code==200
    changed=event('tool_result',logical_event_id='d'*64,content_digest='e'*64)
    assert upload(client,changed).status_code==200
    assert operations(client)['items'][0]['status']=='conflicting_evidence'
    assert upload(client,event('tool_call',session=''),event('tool_result',session='')).status_code==200
    assert len(operations(client)['items'])==3
