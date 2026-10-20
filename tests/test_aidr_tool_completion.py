import copy
import json
import pytest
from tests.test_aidr_api import service
from tests.test_aidr_operations import event, upload, behavior, operations
from tests.test_aidr_hook_queries import insert
from tests.test_aidr_sessions import get
from backend.aidr_models import AidrHookEvent, AidrEvent
from backend.aidr_contract import Event


IDENTITY = dict(agent='codex', session_id='s', turn_id='t', native_call_id='c', tool='view_image', kind='tool.pre')


@pytest.mark.parametrize('include_questions', [False, True])
def test_session_completion_lookup_seeks_native_session_index(service, include_questions):
    from sqlalchemy import event as sql_event
    from backend.aidr_sessions import sessions
    client, factory = service
    insert(factory, 1, event=IDENTITY)
    insert(factory, 2, event={**IDENTITY, 'session_id': 'without-completion'})
    assert upload(client, completion(client)).status_code == 200
    with factory() as db:
        conn = db.connection()
        statements = []
        def capture(conn, cursor, statement, parameters, context, many):
            if statement.startswith('SELECT 1 FROM aidr_events'):
                statements.append((statement, parameters))
        sql_event.listen(conn, 'before_cursor_execute', capture)
        try:
            rows = sessions(db, 'one', include_questions=include_questions)['items']
        finally:
            sql_event.remove(conn, 'before_cursor_execute', capture)
        assert {r['session_id']: r['evidence_class'] for r in rows} == {
            's': 'native_completion_present', 'without-completion': 'hook_only_unknown'}
        assert len(statements) == 2
        for sql, params in statements:
            plan = ' '.join(r[3] for r in conn.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params))
            assert 'ix_aidr_event_completion_call (client_id=? AND agent=? AND <expr>=?)' in plan


def completion(client, command=False, **changes):
    headers = {'authorization':'Bearer test-one', 'X-AIDR-Tool-Completion':'1', 'X-AIDR-Policy-Schema':'2'}
    if command:
        headers['X-AIDR-Command-Completion'] = '1'
    policy = client.post('/api/v1/clients/one/aidr/audit-policy',
        json=dict(stream_id='a'*32, last_sequence='0'),
        headers=headers).json()
    b = behavior('unknown')
    b.update(version=4, policy=policy, actions=[], method='result_fields', content_status='not_provided', contents=[])
    return event('tool_result', session='s', turn='t', call='c', tool='Bash' if command else 'view_image',
        schema_version=2, user_scope='501', behavior=b,
        completion=dict(source='codex.item_completed', status='completed'), **changes)


def timeline(client):
    return get(client, '/session-timeline', source='hooks', agent='codex', session_id='s')['items']


@pytest.mark.parametrize('status', ['failed', 'completed'])
def test_native_completion_preserves_missing_hook_and_is_idempotent(service, status):
    client, factory = service
    pre = insert(factory, 1, event=IDENTITY)
    e = completion(client)
    e['completion']['status'] = status
    for _ in range(2):
        response = upload(client, e)
        assert response.status_code == 200, response.text
    row = timeline(client)[0]
    assert len(row['records']) == 1
    assert row['execution_evidence']['status'] == status
    assert row['execution_evidence']['hook_status'] == 'end_missing'
    assert row['execution_evidence']['source'] == 'codex.item_completed'
    relation = client.get(f'/api/v1/clients/one/aidr/hooks/{pre}/related').json()
    assert relation['relation'] == 'incomplete'
    assert relation['execution_evidence'] == row['execution_evidence']
    assert operations(client)['items'] == []
    assert get(client, '/sessions')['items'][0]['evidence_class'] == 'native_completion_present'
    with factory() as db:
        assert db.query(AidrEvent).count() == 1
        assert db.query(AidrHookEvent).count() == 1
        assert json.loads(db.get(AidrHookEvent, pre).payload_json)['event']['kind'] == 'tool.pre'
    insert(factory, 2, event={**IDENTITY, 'kind':'tool.post', 'hook_event':'PostToolUse'})
    assert 'execution_evidence' not in timeline(client)[0]


@pytest.mark.parametrize('field,value', [('user_scope','502'), ('tool','other'), ('turn_id','other'), ('session_id','other'), ('native_call_id','other')])
def test_completion_identity_isolation(service, field, value):
    client, factory = service
    insert(factory, 1, event=IDENTITY)
    e = completion(client); e[field] = value
    assert upload(client, e).status_code == 200
    assert 'execution_evidence' not in timeline(client)[0]


def test_duplicate_completion_sources_and_hook_users_are_not_merged(service):
    client, factory = service
    insert(factory, 1, event=IDENTITY)
    a = completion(client)
    b = copy.deepcopy(a); b.update(source_id='b'*64, logical_event_id='b'*64, event_id='c'*64)
    assert upload(client, a, b).status_code == 200
    assert 'execution_evidence' not in timeline(client)[0]
    insert(factory, 2, user='502', event=IDENTITY)
    assert all('execution_evidence' not in r for r in timeline(client))


def test_legacy_result_supplements_without_inventing_success(service):
    client, factory = service
    insert(factory, 1, event=IDENTITY)
    assert upload(client, event('tool_call', session='s', turn='t', call='c', tool='view_image'),
        event('tool_result', session='s', turn='t', call='c')).status_code == 200
    evidence = timeline(client)[0]['execution_evidence']
    assert evidence['status'] == 'result_returned'
    assert evidence['relation'] == 'inferred'
    assert evidence['source'] == 'agent_log.tool_result'


def test_completion_contract_and_old_policy(service):
    client, _ = service
    e = completion(client)
    Event.model_validate(e)
    for change in ({'agent':'claude'}, {'kind':'tool_call'}, {'turn_id':''}, {'schema_version':1}):
        with pytest.raises(ValueError):
            Event.model_validate({**e, **change})
    del e['behavior']['policy']['completion_schema']
    with pytest.raises(ValueError):
        Event.model_validate(e)
    old = client.post('/api/v1/clients/one/aidr/audit-policy',
        json=dict(stream_id='a'*32, last_sequence='0'), headers={'authorization':'Bearer test-one'}).json()
    assert 'completion_schema' not in old


def test_completion_snapshot_and_expiry(service):
    from datetime import datetime
    from backend.aidr_tool_completion import supplement
    client, factory = service
    pre = insert(factory, 1, event=IDENTITY)
    e = completion(client)
    assert upload(client, e).status_code == 200
    with factory() as db:
        hook = db.get(AidrHookEvent, pre)
        assert supplement(db, hook, event_ceiling=0) is None
        assert supplement(db, hook)['status'] == 'completed'
        db.query(AidrEvent).update({'expired_at': datetime.utcnow()})
        db.commit()
        assert supplement(db, hook) is None


def test_conflicting_legacy_result_does_not_supplement(service):
    client, factory = service
    insert(factory, 1, event=IDENTITY)
    a = event('tool_result', session='s', turn='t', call='c')
    b = {**a, 'logical_event_id':'d'*64, 'content_digest':'e'*64}
    assert upload(client, event('tool_call', session='s', turn='t', call='c', tool='view_image'), a, b).status_code == 200
    assert 'execution_evidence' not in timeline(client)[0]


@pytest.mark.parametrize('status,code', [('completed',0), ('failed',1), ('failed',143), ('failed',0), ('completed',None), ('failed',None)])
def test_command_completion_status_exit_code_and_ordinary_result_are_separate(service, status, code):
    client, factory = service
    pre = insert(factory, 1, event={**IDENTITY, 'tool':'Bash'})
    e = completion(client, command=True)
    assert e['behavior']['policy']['completion_schema'] == 2
    e.update(logical_event_id='1'*64, event_id='2'*64)
    e['completion']['status'] = status
    if code is not None:
        e['completion']['exit_code'] = code
    assert upload(client, e).status_code == 200
    assert upload(client, e).status_code == 200
    assert upload(client, event('tool_call', session='s', turn='t', call='c', tool='Bash'),
                  event('tool_result', session='s', turn='t', call='c')).status_code == 200
    assert len(operations(client)['items']) == 1
    assert operations(client)['items'][0]['status'] == 'unknown'
    evidence = timeline(client)[0]['execution_evidence']
    assert evidence['status'] == status and evidence.get('exit_code') == code
    assert ('exit_code' in evidence) == (code is not None)
    assert evidence['hook_status'] == 'end_missing'
    assert evidence['source'] == 'codex.item_completed'
    assert client.get(f'/api/v1/clients/one/aidr/hooks/{pre}/related').json()['execution_evidence'] == evidence
    with factory() as db:
        assert db.query(AidrHookEvent).count() == 1
        assert db.query(AidrEvent).count() == 3
    insert(factory, 2, event={**IDENTITY, 'tool':'Bash', 'kind':'tool.post'})
    assert 'execution_evidence' not in timeline(client)[0]


def test_command_completion_protocol_compatibility_and_validation(service):
    from backend.aidr_contract import same_log_source
    client, _ = service
    old = completion(client)
    assert old['behavior']['policy']['completion_schema'] == 1
    parsed = Event.model_validate(old)
    # Adding the optional exit code field must not conflict with v1 stored evidence.
    assert same_log_source(json.dumps(old), parsed)
    new = completion(client, command=True)
    for invalid in (True, '0', 1.5, 2**31, -(2**31)-1):
        bad = copy.deepcopy(new); bad['completion']['exit_code'] = invalid
        with pytest.raises(ValueError):
            Event.model_validate(bad)
    new['behavior']['policy']['completion_schema'] = 1
    with pytest.raises(ValueError):
        Event.model_validate(new)
    old['completion']['exit_code'] = 0
    with pytest.raises(ValueError):
        Event.model_validate(old)
    response = client.post('/api/v1/clients/one/aidr/audit-policy',
        json=dict(stream_id='a'*32, last_sequence='0'),
        headers={'authorization':'Bearer test-one','X-AIDR-Command-Completion':'1'})
    assert response.status_code == 422
