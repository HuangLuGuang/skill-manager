"""Session aggregation, source-local pairing, pagination and content isolation."""
import json
from datetime import datetime

from tests.test_aidr_api import service
from tests.test_aidr_hook_queries import insert
from tests.test_aidr_operations import behavior, event, upload
from backend.aidr_models import AidrOperation
from backend.iam_routes import route_permission
from starlette.requests import Request
from backend import auth, models, iam_models

BASE = '/api/v1/clients/one/aidr'


def test_qoder_shared_session_native_call_turn_and_models(service):
    client, factory = service
    session = 'qoder-native-session'
    submit_id = insert(factory, 1, event={'agent':'qoder-hooks', 'session_id':session,
        'kind':'turn.submit', 'turn_id':'r1', 'context':{'model':'Auto'}})
    insert(factory, 2, event={'agent':'qoder-hooks','session_id':session,'turn_id':'',
        'native_call_id':'qoder-call','tool':'Bash','kind':'tool.pre','context':{'model':'Auto'}})
    insert(factory, 3, event={'agent':'qoder-hooks','session_id':session,'turn_id':'',
        'native_call_id':'qoder-call','tool':'Bash','kind':'tool.post'})
    insert(factory, 4, event={'agent':'qoder-hooks','session_id':session,'turn_id':'',
        'native_call_id':'not-recorded','tool':'Bash','kind':'tool.pre'})
    call = event('tool_call', agent='qoder-cli', session=session, turn='r1', call='qoder-call', tool='Bash', user_scope='501')
    result = event('tool_result', agent='qoder-cli', session=session, turn='r1', call='qoder-call', user_scope='501')
    assert upload(client,call,result).status_code == 200
    params = dict(agent='qoder-hooks', session_id=session)
    rows = get(client, '/sessions', agent='qoder')['items']
    assert len(rows)==1 and rows[0]['agent']=='qoder-hooks'
    assert rows[0]['log_count']==1 and rows[0]['hook_count']==4
    turns = {r['key']:r for r in get(client,'/session-turns',**params)['items']}
    assert turns['turn:r1']['prompt_id']==submit_id
    assert turns['turn:r1']['hook_count']==3 and turns['turn:r1']['log_count']==1
    assert turns['turn:r1']['hook_models'][0]['value']=='Auto'
    assert turns['unassigned']['hook_count']==1
    hooks=get(client,'/session-timeline',source='hooks',turn_key='turn:r1',**params)['items']
    assert len(hooks)==2 and all(r['turn_key']=='turn:r1' for r in hooks)
    logs=get(client,'/session-timeline',source='logs',turn_key='turn:r1',**params)['items']
    assert len(logs)==1 and logs[0]['operation']['call']['agent']=='qoder-cli'
    # Same native call under another turn is ambiguous, not a time-based match.
    assert upload(client,event('tool_call',agent='qoder-cli',session=session,turn='r2',call='qoder-call',tool='Bash',user_scope='501')).status_code==200
    turns={r['key']:r for r in get(client,'/session-turns',**params)['items']}
    assert turns['unassigned']['hook_count']==3


def test_qoder_call_link_is_snapshot_and_device_scoped(service):
    client,factory=service
    insert(factory,1,event={'agent':'qoder-hooks','session_id':'s','native_call_id':'c','tool':'Bash','turn_id':''})
    insert(factory,2,event={'agent':'qoder-hooks','session_id':'s','turn_id':'other'})
    params=dict(agent='qoder-hooks',session_id='s',limit=1)
    first=get(client,'/session-turns',**params)
    assert first['has_more']
    assert upload(client,event('tool_call',agent='qoder-cli',session='s',turn='late',call='c',tool='Bash',user_scope='501')).status_code==200
    second=get(client,'/session-turns',**params,cursor=first['next_cursor'])
    assert {r['key'] for r in first['items']+second['items']}=={'unassigned','turn:other'}


def test_qoder_native_call_link_requires_same_user_session_and_tool(service):
    client, factory = service
    insert(factory,1,event={'agent':'qoder-hooks','session_id':'s','native_call_id':'c','tool':'Bash','turn_id':''})
    for index, overrides in enumerate(({'user_scope':'502'}, {'session_id':'different'}, {'tool':'Read'})):
        call = event('tool_call',agent='qoder-cli',session='s',turn=f'r{index}',call='c',tool='Bash',user_scope='501')
        call.update(overrides)
        call['logical_event_id'] = str(index+1)*64
        assert upload(client,call).status_code==200
    rows=get(client,'/session-turns',agent='qoder-hooks',session_id='s')['items']
    assert next(r for r in rows if r['key']=='unassigned')['hook_count']==1


def test_qoder_session_skill_list_keeps_both_raw_sources(service, monkeypatch):
    from backend.aidr_models import AidrSkillUse
    client, factory = service
    monkeypatch.setattr('backend.aidr_skill_usage.registry_manager',lambda:None)
    monkeypatch.setattr('backend.aidr_skill_usage.refresh',lambda db,row,manager,settings=None:{'id':str(row.id),'agent':row.agent})
    with factory() as db:
        for entry in ('qoder-hooks','qoder-cli','qoder-work'):
            db.add(AidrSkillUse(client_id='one',call_key=entry,agent=entry,session_id='s',behavior='invocation',payload_json='{}'))
        db.commit()
    response=client.get(BASE+'/skill-uses',params={'agent':'qoder-hooks','session_id':'s'})
    assert response.status_code==200
    assert {r['agent'] for r in response.json()['items']}=={'qoder-hooks','qoder-cli'}


def test_qoder_product_filter_preserves_entry_identity_and_pagination(service):
    client, factory = service
    entries = ('qoder-cli', 'qoder-hooks', 'qoder-ide', 'qoder-work')
    for i, entry in enumerate((*entries, 'codex'), 1):
        insert(factory, i, event={'agent':entry,'session_id':'shared-id'})
    page = get(client, '/sessions', agent='qoder', limit=2)
    rows = page['items'][:]
    while page['has_more']:
        page = get(client, '/sessions', agent='qoder', limit=2, cursor=page['next_cursor'])
        rows.extend(page['items'])
    assert {r['agent'] for r in rows} == set(entries)
    assert len(rows) == len({r['key'] for r in rows}) == 4
    assert [r['agent'] for r in get(client, '/sessions', agent='qoder-cli')['items']] == ['qoder-cli']
    for row in rows:
        detail = get(client, '/session-timeline', source='hooks', agent=row['agent'], session_id=row['session_id'])
        assert len(detail['items']) == 1


def test_session_host_context_is_explicit_scoped_and_snapshot_bounded(service):
    from backend.aidr_sessions import session_host_context
    _, factory = service
    base = {'agent':'codex','session_id':'context-session','native_agent_id':''}
    first = insert(factory,1,event={**base,'context':{'model':'first','cwd':'/tmp/old'}})
    second = insert(factory,2,event={**base,'context':{'cwd':'/tmp/new'}})
    insert(factory,3,event={**base,'native_agent_id':'child','context':{'model':'child'}})
    insert(factory,4,event={**base,'context':{'model':'expired'}},expired=True)
    insert(factory,5,event={**base,'context':{'model':'other-device'}},client='two')
    insert(factory,6,event={**base,'agent':'claude','context':{'model':'other-product'}})
    insert(factory,7,event={**base,'session_id':'different','context':{'model':'other-session'}})
    with factory() as db:
        result=session_host_context(db,'one','codex','context-session',second)
        assert result['model']['value']=='first' and result['model']['id']==str(first)
        assert result['cwd']['value']=='/tmp/new' and result['cwd']['id']==str(second)
        assert session_host_context(db,'one','codex','',999)=={}
        assert session_host_context(db,'one','codex','missing',999)=={}
        assert session_host_context(db,'one','codex','context-session',first)['cwd']['value']=='/tmp/old'
        assert session_host_context(db,'one','codex','context-session',999)['model']['value']=='first'


def test_turn_models_are_explicit_scoped_and_deduplicated(service):
    client, factory = service
    base = dict(agent='codex', session_id='turn-models', turn_id='t1', native_agent_id='')
    def report(n, model, **changes):
        return insert(factory, n, event={**base, 'context': {'model': model}, **changes})
    report(1, 'model-a')
    last_a = report(2, 'model-a')
    report(3, 'model-b')
    report(4, 'child-model', native_agent_id='child')
    report(5, 'subagent-model', kind='subagent.start')
    report(6, 'other-model', session_id='other')
    report(7, 'later-model', turn_id='t2')
    insert(factory, 8, event={**base, 'turn_id': 't3'})
    insert(factory, 9, event={**base, 'context': {'model': 'expired'}}, expired=True)
    insert(factory, 10, event={**base, 'context': {'model': 'other-device'}}, client='two')
    report(11, 'other-product', agent='claude')
    rows = get(client, '/session-turns', agent='codex', session_id='turn-models')['items']
    by_key = {row['key']: row['hook_models'] for row in rows}
    assert [r['value'] for r in by_key['turn:t1']] == ['model-a', 'model-b']
    assert by_key['turn:t1'][0]['id'] == str(last_a)
    assert [r['value'] for r in by_key['turn:t2']] == ['later-model']
    assert by_key['turn:t3'] == []


def test_turn_models_snapshot_and_prompt_without_native_turn(service):
    from backend.aidr_sessions import turn_hook_models
    _, factory = service
    base = dict(agent='codex', session_id='prompt-models', turn_id='', native_agent_id='')
    prompt = insert(factory, 1, event={**base, 'kind': 'turn.submit', 'context': {'model': 'prompt-model'}})
    insert(factory, 2, event={**base, 'context': {'model': 'unassigned-model'}})
    first = insert(factory, 3, event={**base, 'turn_id': 't1', 'context': {'model': 'first'}})
    insert(factory, 4, event={**base, 'turn_id': 't1', 'context': {'model': 'later'}})
    with factory() as db:
        result = turn_hook_models(db, 'one', 'codex', 'prompt-models', first, [f'prompt:{prompt}', 'turn:t1', 'unassigned'])
        assert result[f'prompt:{prompt}'][0]['value'] == 'prompt-model'
        assert [r['value'] for r in result['turn:t1']] == ['first']
        assert 'unassigned' not in result
        assert turn_hook_models(db, 'one', 'codex', '', 999, ['turn:t1']) == {}


def test_turn_hook_context_keeps_directory_and_workspace_in_their_native_turn(service):
    from backend.aidr_sessions import turn_hook_contexts
    client, factory = service
    base = dict(agent='codex', session_id='turn-directories', turn_id='t1', native_agent_id='')
    first = insert(factory, 1, event={**base, 'context': {'model': 'model-a', 'cwd': '/tmp/first', 'workspace_roots': ['/tmp/first', '/tmp/shared']}})
    insert(factory, 2, event={**base, 'context': {'cwd': '/tmp/first'}})
    insert(factory, 3, event={**base, 'turn_id': 't2', 'context': {'model': 'model-b', 'cwd': '/tmp/second'}})
    insert(factory, 4, event={**base, 'native_agent_id': 'child', 'context': {'cwd': '/tmp/child'}})
    insert(factory, 5, event={**base, 'context': {'cwd': '/tmp/expired'}}, expired=True)
    rows = get(client, '/session-turns', agent='codex', session_id='turn-directories')['items']
    by_key = {row['key']: row for row in rows}
    context = by_key['turn:t1']['hook_context']
    assert [r['value'] for r in context['cwd']] == ['/tmp/first']
    assert context['workspace_roots'][0]['value'] == ['/tmp/first', '/tmp/shared']
    assert context['model'] == by_key['turn:t1']['hook_models']
    assert by_key['turn:t2']['hook_context']['cwd'][0]['value'] == '/tmp/second'
    assert 'workspace_roots' not in by_key['turn:t2']['hook_context']
    with factory() as db:
        snapshot = turn_hook_contexts(db, 'one', 'codex', 'turn-directories', first, ['turn:t1', 'turn:t2'])
        assert snapshot['turn:t1']['cwd'][0]['id'] == str(first)
        assert 'turn:t2' not in snapshot


def get(client, path, **params):
    response = client.get(BASE + path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_session_union_counts_visibility_expiry_and_missing_ids(service):
    client, factory = service
    assert upload(client, event('tool_call'), event('tool_result'), event('tool_call', session=''),
                  event('tool_call', session='', call='another')).status_code == 200
    insert(factory, 1, event={'agent': 'codex', 'session_id': 'session-a'})
    insert(factory, 2, event={'agent': 'claude', 'session_id': 'session-a'})
    insert(factory, 3, expired=True, event={'session_id': 'expired'})
    insert(factory, 4, client='two', event={'session_id': 'invisible'})
    rows = get(client, '/sessions')['items']
    assert len(rows) == 4
    codex = next(r for r in rows if r['agent'] == 'codex' and r['session_id'])
    assert (codex['log_count'], codex['hook_count']) == (1, 1)
    orphans = [r for r in rows if not r['session_id']]
    assert len(orphans) == 2 and len({r['orphan_id'] for r in orphans}) == 2
    for row in orphans:
        timeline = get(client, '/session-timeline', source='logs', agent='codex', orphan_id=row['orphan_id'])
        assert len(timeline['items']) == 1
    assert get(client, '/session-timeline', source='logs', agent='codex')['items'] == []
    assert len(get(client, '/sessions', agent='claude')['items']) == 1
    assert len(get(client, '/sessions', keyword='session-a')['items']) == 2
    assert 'PRIVATE-UNSEARCHABLE' not in json.dumps(rows)
    for path in ('sessions', 'session-timeline?source=logs&agent=codex'):
        assert client.get('/api/v1/clients/two/aidr/' + path).status_code == 404
    for path in ('sessions', 'session-timeline'):
        request = Request({'type': 'http', 'method': 'GET', 'path': BASE + '/' + path, 'headers': []})
        assert route_permission(request) == 'clients:view'


def test_hook_pairs_cross_pages_search_and_identity_isolation(service):
    client, factory = service
    identity = dict(agent='claude', session_id='s', tool='Bash', native_call_id='call', turn_id='', native_agent_id='')
    pre = insert(factory, 1, event={**identity, 'kind': 'tool.pre', 'hook_event': 'PreToolUse'})
    insert(factory, 2, event={**identity, 'kind': 'turn.stop', 'hook_event': 'Stop'})
    post = insert(factory, 3, event={**identity, 'kind': 'tool.post', 'hook_event': 'PostToolUse'})
    insert(factory, 4, user='other', event={**identity, 'kind': 'tool.post', 'hook_event': 'PostToolUse'})
    insert(factory, 5, stream='c'*32, event={**identity, 'kind': 'tool.post', 'hook_event': 'PostToolUse'})
    insert(factory, 6, event={**identity, 'native_agent_id': 'sub', 'kind': 'tool.post', 'hook_event': 'PostToolUse'})
    params = dict(source='hooks', agent='claude', session_id='s', limit=1)
    page = get(client, '/session-timeline', **params)
    assert {int(r['id']) for r in page['items'][0]['records']} == {pre, post}
    insert(factory, 7, event={**identity, 'native_call_id': 'new', 'kind': 'tool.pre', 'hook_event': 'PreToolUse'})
    items = page['items'][:]
    while page['has_more']:
        page = get(client, '/session-timeline', **params, cursor=page['next_cursor'])
        items.extend(page['items'])
    assert len(items) == 5 and sum(len(item['records']) for item in items) == 6
    assert 'PRIVATE-UNSEARCHABLE' not in json.dumps(items)
    matched = get(client, '/session-timeline', **params, keyword='PreToolUse')['items'][0]
    assert {int(r['id']) for r in matched['records']} == {pre, post}
    assert get(client, '/session-timeline', **params, keyword='PRIVATE-UNSEARCHABLE')['items'] == []
    # Repeated outcomes are separate records, never an arbitrary pair.
    insert(factory, 8, event={**identity, 'kind': 'tool.failure', 'hook_event': 'PostToolUseFailure'})
    rows = get(client, '/session-timeline', source='hooks', agent='claude', session_id='s')['items']
    assert all(len(row['records']) == 1 for row in rows)


def test_log_timeline_order_search_snapshot_and_cursor_scope(service):
    client, factory = service
    events = [event('tool_call', call=f'c{i}', observed_at=f'2026-09-24T00:00:{i:02d}Z') for i in range(4)]
    assert upload(client, *events).status_code == 200
    params = dict(source='logs', agent='codex', session_id='session-a', limit=2)
    first = get(client, '/session-timeline', **params)
    assert [r['operation']['call']['native_call_id'] for r in first['items']] == ['c0', 'c1']
    assert upload(client, event('tool_call', call='late')).status_code == 200
    second = get(client, '/session-timeline', **params, cursor=first['next_cursor'])
    assert [r['operation']['call']['native_call_id'] for r in second['items']] == ['c2', 'c3']
    assert not second['has_more']
    reverse = get(client, '/session-timeline', **params, order='newest')
    assert reverse['items'][0]['operation']['call']['native_call_id'] == 'c3'
    assert len(get(client, '/session-timeline', **params, keyword='exec')['items']) == 2
    assert get(client, '/session-timeline', **params, keyword='%')['items'] == []
    invalid = client.get(BASE + '/session-timeline', params={**params, 'cursor': first['next_cursor'], 'order': 'newest'})
    assert invalid.status_code == 422 and invalid.json()['error_code'] == 'aidr.session_cursor_invalid'
    for cursor in ('invalid', 'W10', 'bnVsbA'):
        assert client.get(BASE + '/sessions', params={'cursor': cursor}).status_code == 422
    with factory() as db:
        row = db.query(AidrOperation).first(); row.expired_at = datetime.utcnow(); db.commit()
    remaining = get(client, '/session-timeline', source='logs', agent='codex', session_id='session-a')
    assert len(remaining['items']) == 4


def test_sessions_cursor_excludes_new_sessions_and_pairs_require_codex_turn(service):
    client, factory = service
    for i in range(4):
        insert(factory, i + 1, event={'agent': 'codex', 'session_id': f's{i}', 'kind': 'tool.pre', 'tool': 'exec', 'native_call_id': 'c', 'turn_id': ''})
    first = get(client, '/sessions', limit=2)
    insert(factory, 5, event={'agent': 'codex', 'session_id': 'new'})
    second = get(client, '/sessions', limit=2, cursor=first['next_cursor'])
    assert len({r['key'] for r in first['items'] + second['items']}) == 4 and not second['has_more']
    insert(factory, 6, event={'agent': 'codex', 'session_id': 's0', 'kind': 'tool.post', 'tool': 'exec', 'native_call_id': 'c', 'turn_id': ''})
    rows = get(client, '/session-timeline', source='hooks', agent='codex', session_id='s0')['items']
    assert len(rows) == 2 and all(len(row['records']) == 1 for row in rows)


def test_log_search_uses_command_and_target_metadata_without_exposing_body(service):
    client, factory = service
    action = behavior()
    action['actions'][0]['command'] = 'echo literal_%'
    assert upload(client, event('tool_call', schema_version=2, behavior=action)).status_code == 200
    with factory() as db:
        row = db.query(AidrOperation).one()
        payload = json.loads(row.payload_json)
        payload['call']['behavior']['contents'] = [{'kind': 'file_body', 'text': 'PRIVATE-BODY-ONLY'}]
        payload['call']['behavior']['actions'][0]['targets'] = [{'kind': 'file', 'value': '/tmp/target-only'}]
        row.payload_json = json.dumps(payload)
        db.commit()
    params = dict(source='logs', agent='codex', session_id='session-a')
    for keyword in ('literal_%', 'target-only'):
        result = get(client, '/session-timeline', **params, keyword=keyword)
        assert len(result['items']) == 1 and 'PRIVATE-BODY-ONLY' not in json.dumps(result)
    assert get(client, '/session-timeline', **params, keyword='PRIVATE-BODY-ONLY')['items'] == []


def test_turn_navigation_keeps_sources_counts_and_missing_ids(service):
    client, factory = service
    upload(client, event('tool_call', turn='t1'), event('tool_call', turn='t2'), event('tool_call', turn=''))
    prompt = insert(factory, 1, event={'agent': 'codex', 'session_id': 'session-a', 'kind': 'turn.submit', 'turn_id': 't1'})
    insert(factory, 2, event={'agent': 'codex', 'session_id': 'session-a', 'kind': 'turn.submit', 'turn_id': 't1'})
    missing = insert(factory, 3, event={'agent': 'codex', 'session_id': 'session-a', 'kind': 'turn.submit', 'turn_id': ''})
    insert(factory, 4, event={'agent': 'codex', 'session_id': 'session-a', 'kind': 'session.start', 'turn_id': ''})
    params = dict(agent='codex', session_id='session-a')
    data = get(client, '/session-turns', **params)
    rows = {r['key']: r for r in data['items']}
    assert set(rows) == {'turn:t1', 'turn:t2', f'prompt:{missing}', 'unassigned'}
    assert rows['turn:t1']['prompt_count'] == 2 and rows['turn:t1']['prompt_id'] == prompt
    assert (rows['turn:t1']['log_count'], rows['turn:t1']['hook_count']) == (1, 2)
    assert rows['unassigned']['log_count'] == rows['unassigned']['hook_count'] == 1
    assert 'PRIVATE-UNSEARCHABLE' not in json.dumps(data)
    assert len(get(client, '/session-timeline', **params, source='logs', turn_key='turn:t1')['items']) == 1
    assert len(get(client, '/session-timeline', **params, source='hooks', turn_key='turn:t1')['items']) == 2
    assert get(client, '/session-timeline', **params, source='logs', turn_key=f'prompt:{missing}')['items'] == []
    for source in ('logs', 'hooks'):
        assert len(get(client, '/session-timeline', **params, source=source, turn_key='unassigned')['items']) == 1
    assert client.get('/api/v1/clients/two/aidr/session-turns', params=params).status_code == 404


def test_question_permission_search_audit_and_expiry(service):
    client, factory = service
    insert(factory, 1, event={'agent': 'codex', 'session_id': 's', 'kind': 'turn.submit', 'turn_id': 't'})
    params = dict(agent='codex', session_id='s')
    assert client.get(BASE+'/sessions', params={'include_questions': True}).status_code == 403
    assert client.get(BASE+'/session-turns', params={**params, 'include_questions': True}).status_code == 403
    assert get(client, '/sessions', keyword='PRIVATE-UNSEARCHABLE')['items'] == []
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1, username='owner', role='admin', is_active=True)
    with factory() as db:
        db.add(iam_models.RolePermission(role_name='admin', permission_code='clients:read-audit-content'))
        db.commit()
    result = client.get(BASE+'/sessions', params={'include_questions': True, 'keyword': 'PRIVATE-UNSEARCHABLE'})
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'no-store'
    assert result.json()['items'][0]['question_preview'] == 'PRIVATE-UNSEARCHABLE'
    turns = get(client, '/session-turns', **params, include_questions=True)
    assert turns['items'][0]['question']['text'] == 'PRIVATE-UNSEARCHABLE'
    from backend.aidr_models import AidrHookEvent
    with factory() as db:
        audits = db.query(models.OperationLog).filter_by(action='aidr.question_view').all()
        assert len(audits) == 2 and all('PRIVATE-UNSEARCHABLE' not in row.details for row in audits)
        db.query(AidrHookEvent).update({'expired_at': datetime.utcnow()}); db.commit()
    assert get(client, '/sessions', include_questions=True)['items'] == []
    assert get(client, '/session-turns', **params, include_questions=True)['items'] == []


def test_turn_cursor_snapshot_and_filter_binding(service):
    client, factory = service
    for i in range(4):
        insert(factory, i+1, event={'agent': 'codex', 'session_id': 's', 'turn_id': f't{i}'})
    params = dict(agent='codex', session_id='s', limit=2)
    first = get(client, '/session-turns', **params)
    insert(factory, 5, event={'agent': 'codex', 'session_id': 's', 'turn_id': 'new'})
    second = get(client, '/session-turns', **params, cursor=first['next_cursor'])
    assert len({r['key'] for r in first['items']+second['items']}) == 4 and not second['has_more']
    invalid = client.get(BASE+'/session-turns', params={**params, 'session_id': 'other', 'cursor': first['next_cursor']})
    assert invalid.status_code == 422
    assert route_permission(Request({'type': 'http', 'method': 'GET', 'path': BASE+'/session-turns', 'headers': []})) == 'clients:view'


def test_question_excerpt_preserves_original_and_first_available_content(service):
    client, factory = service
    from backend.aidr_models import AidrHookEvent
    from backend.aidr_sessions import sessions, turns
    first = insert(factory, 1, event={'agent': 'codex', 'session_id': 's', 'turn_id': 't1', 'kind': 'turn.submit'})
    second = insert(factory, 2, event={'agent': 'codex', 'session_id': 's', 'turn_id': 't2', 'kind': 'turn.submit'})
    original = '\n<in-app-browser-context>context</in-app-browser-context>\n## My request:\n检查采集状态'
    with factory() as db:
        row = db.get(AidrHookEvent, first); p = json.loads(row.payload_json); p['event']['contents'] = []; row.payload_json = json.dumps(p)
        row = db.get(AidrHookEvent, second); p = json.loads(row.payload_json); p['event']['contents'][0]['text'] = original; row.payload_json = json.dumps(p)
        db.commit()
        assert sessions(db, 'one', include_questions=True)['items'][0]['question_preview'] == '检查采集状态'
        question = next(r for r in turns(db, 'one', agent='codex', session_id='s', include_questions=True)['items'] if r['key']=='turn:t2')['question']
        assert question['display_text'] == '检查采集状态' and question['text'] == original


def test_question_search_keeps_whole_session_counts_title_and_pagination(service):
    """A later matching prompt selects the whole session, not just matching records."""
    client, factory = service
    from backend.aidr_models import AidrHookEvent
    from backend.aidr_sessions import sessions
    first = insert(factory, 1, event={'agent': 'codex', 'session_id': 'alpha', 'kind': 'turn.submit'})
    insert(factory, 2, event={'agent': 'codex', 'session_id': 'alpha', 'kind': 'tool.pre'})
    insert(factory, 3, event={'agent': 'codex', 'session_id': 'alpha', 'kind': 'tool.post'})
    match = insert(factory, 4, event={'agent': 'codex', 'session_id': 'alpha', 'kind': 'turn.submit'})
    other = insert(factory, 5, event={'agent': 'claude', 'session_id': 'beta', 'kind': 'turn.submit'})
    assert upload(client, event('tool_call', session='alpha'), event('tool_result', session='alpha')).status_code == 200
    with factory() as db:
        for ident, body in [(first, 'Original title'), (match, 'find-this-needle'), (other, 'find-this-needle too')]:
            row = db.get(AidrHookEvent, ident)
            payload = json.loads(row.payload_json)
            payload['event']['contents'][0]['text'] = body
            row.payload_json = json.dumps(payload)
        db.commit()
        all_items = sessions(db, 'one', include_questions=True)['items']
        params = dict(include_questions=True, keyword='find-this-needle', limit=1)
        page = sessions(db, 'one', **params)
        assert page['has_more']
        second = sessions(db, 'one', cursor=page['next_cursor'], **params)
        items = page['items'] + second['items']
        assert not second['has_more'] and items == all_items
        alpha = next(item for item in items if item['session_id'] == 'alpha')
        assert alpha['hook_count'] == 4 and alpha['log_count'] == 1
        assert alpha['question_preview'] == 'Original title'
        assert sessions(db, 'one', keyword='find-this-needle')['items'] == []


def test_session_list_counts_use_indexes_and_prompts_respect_page_ceiling(service):
    from sqlalchemy import event as sql_event
    from backend.aidr_sessions import sessions
    client, factory = service
    insert(factory, 1, event={'agent': 'codex', 'session_id': 'alpha', 'kind': 'tool.pre'})
    insert(factory, 2, event={'agent': 'codex', 'session_id': 'beta', 'kind': 'tool.pre'})
    with factory() as db:
        statements = []
        conn = db.connection()
        def capture(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().startswith('WITH evidence'):
                statements.append((statement, parameters))
        sql_event.listen(conn, 'before_cursor_execute', capture)
        first = sessions(db, 'one', include_questions=True, limit=1)
        sql_event.remove(conn, 'before_cursor_execute', capture)
        sql, params = statements[0]
        assert 'json_each' not in sql
        plan = conn.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params).all()
        for name in ('operation', 'hook', 'message'):
            assert any(f'ix_aidr_{name}_session_list' in row[3] for row in plan)
    # A new prompt for the next session must not leak into an older page snapshot.
    remaining = 'alpha' if first['items'][0]['session_id'] == 'beta' else 'beta'
    insert(factory, 3, event={'agent': 'codex', 'session_id': remaining, 'kind': 'turn.submit'})
    with factory() as db:
        second = sessions(db, 'one', include_questions=True, limit=1, cursor=first['next_cursor'])
        assert second['items'][0]['session_id'] == remaining
        assert second['items'][0]['prompt_id'] is None
        assert second['items'][0]['question_preview'] == ''
        assert second['items'][0]['hook_count'] == 1
        refreshed = sessions(db, 'one', include_questions=True)
        assert next(i for i in refreshed['items'] if i['session_id'] == remaining)['question_preview']


def test_product_session_queries_seek_product_snapshot_and_prompt_indexes(service):
    from sqlalchemy import event as sql_event
    from backend.aidr_sessions import sessions
    _, factory = service
    insert(factory, 1, event={'agent': 'codex', 'session_id': 'selected', 'kind': 'turn.submit'})
    insert(factory, 2, event={'agent': 'codex', 'session_id': 'selected', 'kind': 'tool.pre'})
    insert(factory, 3, event={'agent': 'claude', 'session_id': 'other-product', 'kind': 'turn.submit'})
    insert(factory, 4, event={'agent': 'codex', 'session_id': 'other-device'}, client='two')
    insert(factory, 5, event={'agent': 'codex', 'session_id': 'expired'}, expired=True)
    with factory() as db:
        conn = db.connection()
        statements = []
        def capture(conn, cursor, statement, parameters, context, many):
            statements.append((statement, parameters))
        sql_event.listen(conn, 'before_cursor_execute', capture)
        try:
            result = sessions(db, 'one', agent='codex', include_questions=True)
        finally:
            sql_event.remove(conn, 'before_cursor_execute', capture)
        assert len(result['items']) == 1
        assert result['items'][0]['session_id'] == 'selected'
        assert result['items'][0]['hook_count'] == 2
        assert result['items'][0]['question_preview']
        plans = {
            sql: ' '.join(row[3] for row in conn.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params))
            for sql, params in statements
        }
        aggregate = next(plan for sql, plan in plans.items() if sql.lstrip().startswith('WITH evidence'))
        assert 'ix_aidr_operation_product_sessions (client_id=? AND expired_at=? AND agent=? AND id<?)' in aggregate
        assert 'ix_aidr_hook_session_list (client_id=? AND expired_at=? AND <expr>=?)' in aggregate
        assert 'ix_aidr_message_session_list (client_id=? AND expired_at=? AND agent=?)' in aggregate
        ceiling = next(plan for sql, plan in plans.items() if sql.startswith('SELECT max(aidr_operations.id)'))
        assert 'ix_aidr_operation_device_page (client_id=?)' in ceiling
        prompt = next(plan for sql, plan in plans.items() if 'aidr_hook_events.id IN (' in sql)
        assert ('ix_aidr_hook_active_page (client_id=? AND expired_at=? AND id=?' in prompt
                or 'USING INTEGER PRIMARY KEY (rowid=?)' in prompt)


def test_turn_query_scopes_indexes_to_selected_session(service):
    from sqlalchemy import event as sql_event
    from backend.aidr_sessions import turns
    _, factory = service
    for n in range(1, 4):
        insert(factory, n, event={'agent': 'codex', 'session_id': f'session-{n}', 'turn_id': 't1'})
    with factory() as db:
        conn = db.connection()
        statements = []
        def capture(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().startswith('WITH evidence'):
                statements.append((statement, parameters))
        sql_event.listen(conn, 'before_cursor_execute', capture)
        try:
            result = turns(db, 'one', agent='codex', session_id='session-2')
        finally:
            sql_event.remove(conn, 'before_cursor_execute', capture)
        assert result['items'][0]['hook_count'] == 1
        sql, params = statements[0]
        plan = ' '.join(row[3] for row in conn.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params))
        assert 'ix_aidr_operation_session_turns (client_id=? AND agent=? AND session_id=? AND expired_at=? AND id<?)' in plan
        assert 'ix_aidr_hook_session_turns (client_id=? AND expired_at=? AND <expr>=? AND <expr>=? AND id<?)' in plan
