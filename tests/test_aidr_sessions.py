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
