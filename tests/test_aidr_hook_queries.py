"""Read-only Hook navigation, filtering and exact identity isolation."""
import json
from datetime import datetime
from tests.test_aidr_api import service
from tests.test_aidr_hooks import hook_batch
from backend.aidr_models import AidrHookEvent

BASE = '/api/v1/clients/one/aidr/hooks'

def insert(factory, number, *, client='one', stream='b'*32, user='501', event=None, expired=False):
    record = hook_batch(number)['records'][0]
    record['user_scope'] = user
    if event:
        record['event'].update(event)
    record['event']['contents'] = [{'kind':'prompt','text':'PRIVATE-UNSEARCHABLE','stored_bytes':20}]
    with factory() as db:
        row = AidrHookEvent(client_id=client, stream_id=stream, event_id=record['event_id'], source_seq=number,
            content_hash='a'*64, payload_json=json.dumps(record), expired_at=datetime.utcnow() if expired else None)
        db.add(row); db.commit(); return row.id


def test_latest_snapshot_history_has_no_gaps_or_duplicates_with_concurrent_insert(service):
    client, factory = service
    expected = [insert(factory, i) for i in range(1,8)]
    first = client.get(BASE, params={'limit':2}).json()
    assert [int(row['id']) for row in first['items']] == expected[::-1][:2]
    inserted = insert(factory,8)
    seen = [int(row['id']) for row in first['items']]
    current = first
    while current['has_more']:
        current = client.get(BASE, params={'limit':2,'before':current['next_before'],'snapshot_id':first['snapshot_id']}).json()
        seen.extend(int(row['id']) for row in current['items'])
    assert seen == expected[::-1] and len(seen) == len(set(seen))
    assert int(client.get(BASE,params={'limit':2}).json()['items'][0]['id']) == inserted
    assert client.get(BASE,params={'limit':2,'snapshot_id':first['snapshot_id']}).json()['items'] == first['items']
    legacy = client.get(BASE,params={'after':0,'limit':2}).json()
    assert [int(row['id']) for row in legacy['items']] == expected[:2]
    assert legacy['next_after'] == str(expected[1])
    assert client.get(BASE,params={'after':0,'before':2}).status_code == 422


def test_filters_are_exact_or_literal_metadata_keywords_and_enforce_client_visibility(service):
    client, factory = service
    selected = insert(factory,1,event={'agent':'claude','session_id':'unique_%session','tool':'Bash','native_call_id':'call-1'})
    insert(factory,2,event={'agent':'codex','session_id':'other-session','tool':'BashExtended','native_call_id':'call-2'})
    insert(factory,3,expired=True,event={'agent':'claude','tool':'Bash'})
    insert(factory,4,client='two',event={'agent':'claude','tool':'Bash'})
    for key,value in [('agent','claude'),('session_id','unique_%session'),('tool','Bash'),('native_call_id','call-1'),('event_id',f'{1:032x}'),('keyword','_%')]:
        response=client.get(BASE,params={key:value})
        assert response.status_code == 200,response.text
        assert [int(row['id']) for row in response.json()['items']] == [selected]
    assert client.get(BASE,params={'hook_event':'NoSuchHook'}).json()['items']==[]
    assert client.get(BASE,params={'keyword':'PRIVATE-UNSEARCHABLE'}).json()['items']==[]
    assert 'PRIVATE-UNSEARCHABLE' not in client.get(BASE).text
    assert client.get('/api/v1/clients/two/aidr/hooks').status_code==404


def test_native_call_pairing_requires_source_user_namespace_and_unique_evidence(service):
    client,factory=service
    identity={'agent':'claude','session_id':'s','native_call_id':'c','tool':'Bash','turn_id':'','native_agent_id':''}
    pre=insert(factory,1,event={**identity,'kind':'tool.pre','hook_event':'PreToolUse'})
    post=insert(factory,2,event={**identity,'kind':'tool.post','hook_event':'PostToolUse','behavior':{'status':'unknown','result_basis':[]}})
    insert(factory,3,user='502',event={**identity,'kind':'tool.post','hook_event':'PostToolUse'})
    insert(factory,4,stream='c'*32,event={**identity,'kind':'tool.post','hook_event':'PostToolUse'})
    insert(factory,5,event={**identity,'native_agent_id':'subagent','kind':'tool.post','hook_event':'PostToolUse'})
    pair=client.get(f'{BASE}/{pre}/related').json()
    assert pair['relation']=='matched' and pair['process_relation']=='unknown'
    assert [int(row['id']) for row in pair['items']]==[pre,post]
    assert 'PRIVATE-UNSEARCHABLE' not in json.dumps(pair)
    insert(factory,6,event={**identity,'kind':'tool.failure','hook_event':'PostToolUseFailure'})
    assert client.get(f'{BASE}/{pre}/related').json()['relation']=='conflicting'
    missing=insert(factory,7,event={**identity,'native_call_id':'','kind':'tool.pre','hook_event':'PreToolUse'})
    assert client.get(f'{BASE}/{missing}/related').json()['code']=='identity_missing'
    codex=insert(factory,8,event={**identity,'agent':'codex','kind':'tool.pre','hook_event':'PreToolUse'})
    assert client.get(f'{BASE}/{codex}/related').json()['code']=='identity_missing'
    unrelated=insert(factory,9,client='two',event={**identity,'kind':'tool.pre','hook_event':'PreToolUse'})
    assert client.get(f'{BASE}/{unrelated}/related').status_code==404
    assert client.get(f'{BASE}/{2**63}/related').status_code==422


def test_related_lookup_seeks_native_call_without_scanning_client_history(service):
    from sqlalchemy import event as sql_event
    from backend.aidr_hook_queries import related
    _, factory = service
    identity = dict(agent='codex', session_id='s', turn_id='t', native_call_id='selected', tool='Bash')
    pre = insert(factory, 1, event={**identity, 'kind': 'tool.pre'})
    post = insert(factory, 2, event={**identity, 'kind': 'tool.post'})
    with factory() as db:
        template = json.loads(db.get(AidrHookEvent, pre).payload_json)
        for i in range(1000):
            raw = {**template, 'event': {**template['event'], 'native_call_id': f'unrelated-{i}'}}
            db.add(AidrHookEvent(client_id='one', stream_id='b'*32, event_id=f'{i+100:032x}',
                                source_seq=i+100, content_hash='a'*64, payload_json=json.dumps(raw)))
        db.commit()
        row = db.get(AidrHookEvent, pre)
        conn = db.connection()
        statements = []
        def capture(conn, cursor, statement, parameters, context, many):
            statements.append((statement, parameters))
        sql_event.listen(conn, 'before_cursor_execute', capture)
        try:
            result = related(db, 'one', row)
        finally:
            sql_event.remove(conn, 'before_cursor_execute', capture)
        assert result['relation'] == 'matched'
        assert [int(item['id']) for item in result['items']] == [pre, post]
        sql, params = next((sql, params) for sql, params in statements if 'ORDER BY aidr_hook_events.id' in sql)
        plan = ' '.join(r[3] for r in conn.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params))
        assert 'ix_aidr_hook_source_call (client_id=? AND stream_id=? AND <expr>=?)' in plan
        assert 'TEMP B-TREE' not in plan


def test_relation_evidence_budget_and_expired_counterpart_do_not_claim_a_pair(service):
    client, factory = service
    identity = {'agent':'claude','session_id':'s','native_call_id':'c','tool':'Bash','kind':'tool.pre','hook_event':'PreToolUse'}
    pre = insert(factory,1,event=identity)
    insert(factory,2,expired=True,event={**identity,'kind':'tool.post','hook_event':'PostToolUse'})
    assert client.get(f'{BASE}/{pre}/related').json()['relation'] == 'incomplete'
    for number in range(3,35):
        insert(factory,number,event=identity)
    data = client.get(f'{BASE}/{pre}/related').json()
    assert data['code'] == 'evidence_budget' and data['truncated'] and data['items'] == []
