"""Codex asynchronous completion and conservative session classification."""
import json
import pytest
from sqlalchemy import text
from tests.test_aidr_api import service
from tests.test_aidr_hook_queries import insert, BASE
from tests.test_aidr_sessions import get
from tests.test_aidr_operations import event, upload
from backend.aidr_models import AidrHookEvent
from backend import auth, models, iam_models
from backend.aidr_hook_identity import turn_expression


def pair(factory):
    identity = dict(agent='codex', session_id='s', native_call_id='c', tool='Bash')
    pre = insert(factory, 1, event={**identity, 'turn_id':'original', 'kind':'tool.pre', 'hook_event':'PreToolUse'})
    post = insert(factory, 2, event={**identity, 'turn_id':'later', 'kind':'tool.post', 'hook_event':'PostToolUse'})
    return identity, pre, post


def test_cross_turn_detail_timeline_and_log_link_preserve_originals(service):
    client, factory = service
    identity, pre, post = pair(factory)
    for row in (pre, post):
        result = client.get(f'{BASE}/{row}/related').json()
        assert result['code'] == 'cross_turn_native_identity_matched'
        assert [int(r['id']) for r in result['items']] == [pre, post]
        assert {r['record']['event']['turn_id'] for r in result['items']} == {'original', 'later'}
    params = dict(agent='codex', session_id='s')
    rows = get(client, '/session-timeline', source='hooks', **params)['items']
    assert len(rows) == 1 and rows[0]['turn_key'] == 'turn:original'
    assert rows[0]['association'] == 'cross_turn_native_identity_matched'
    assert len(rows[0]['records']) == 2
    assert len(get(client, '/session-timeline', source='hooks', turn_key='turn:original', **params)['items']) == 1
    assert not get(client, '/session-timeline', source='hooks', turn_key='turn:later', **params)['items']
    turns = get(client, '/session-turns', **params)['items']
    assert len(turns) == 1 and turns[0]['hook_count'] == 2
    call = event('tool_call', agent='codex', session='s', turn='original', call='c', tool='Bash', user_scope='501')
    assert upload(client, call).status_code == 200
    link = client.get('/api/v1/clients/one/aidr/operations').json()['items'][0]['hook_evidence']
    assert len(link['items']) == 2
    with factory() as db:
        assert json.loads(db.get(AidrHookEvent, post).payload_json)['event']['turn_id'] == 'later'
        resolved = db.execute(text(f'SELECT {turn_expression(str(pre))} FROM aidr_hook_events WHERE id=:id'), {'id':post}).scalar()
        assert resolved == 'later'  # A later peer cannot rewrite a previous snapshot.


@pytest.mark.parametrize('change', [
    {'user':'502'}, {'stream':'c'*32}, {'client':'two'},
    {'event':{'session_id':'other'}}, {'event':{'tool':'Read'}},
    {'event':{'native_agent_id':'child'}}, {'event':{'native_call_id':'other'}},
])
def test_cross_turn_scope_isolation(service, change):
    client, factory = service
    identity = dict(agent='codex', session_id='s', native_call_id='c', tool='Bash')
    pre = insert(factory, 1, event={**identity, 'turn_id':'a', 'kind':'tool.pre'})
    changes = dict(change)
    override = changes.pop('event', {})
    insert(factory, 2, event={**identity, 'turn_id':'b', 'kind':'tool.post', **override}, **changes)
    assert client.get(f'{BASE}/{pre}/related').json()['relation'] == 'incomplete'


def test_duplicate_across_turns_is_not_paired(service):
    client, factory = service
    identity, pre, post = pair(factory)
    insert(factory, 3, event={**identity, 'turn_id':'third', 'kind':'tool.pre'})
    assert client.get(f'{BASE}/{post}/related').json()['relation'] == 'conflicting'
    rows = get(client, '/session-timeline', source='hooks', agent='codex', session_id='s')['items']
    assert len(rows) == 3 and all(len(r['records']) == 1 for r in rows)


@pytest.mark.parametrize('prompt,expected', [
    ('This is an app-generated request for a suggested next user message. The user did not write this message.\nContext', 'hook_only_suggestion_inferred'),
    ('# Overview\n\nGenerate 0 to 3 hyperpersonalized suggestions for what this user can do with Codex in this local project: /tmp', 'hook_only_suggestion_inferred'),
    ('Please explain this: This is an app-generated request for a suggested next user message.', 'hook_only_unknown'),
    ('', 'hook_only_unknown'),
])
def test_hook_only_classification_is_content_authorized_and_read_only(service, prompt, expected):
    client, factory = service
    ident = insert(factory, 1, event={'agent':'codex','session_id':'s','kind':'turn.submit' if prompt else 'session.end'})
    with factory() as db:
        row = db.get(AidrHookEvent, ident)
        data = json.loads(row.payload_json)
        data['event']['contents'] = [{'kind':'prompt','text':prompt}]
        row.payload_json = json.dumps(data)
        db.commit()
        original = row.payload_json
    assert get(client, '/sessions')['items'][0]['evidence_class'] == 'hook_only_unknown'
    assert client.get('/api/v1/clients/one/aidr/sessions', params={'include_questions':True}).status_code == 403
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1, username='owner', role='admin', is_active=True)
    with factory() as db:
        db.add(iam_models.RolePermission(role_name='admin', permission_code='clients:read-audit-content'))
        db.commit()
    assert get(client, '/sessions', include_questions=True)['items'][0]['evidence_class'] == expected
    with factory() as db:
        assert db.get(AidrHookEvent, ident).payload_json == original
    assert upload(client, event('tool_call',agent='codex',session='s',turn='t',call='c')).status_code == 200
    assert get(client, '/sessions', include_questions=True)['items'][0]['evidence_class'] == 'logs_present'


@pytest.mark.parametrize('agent,turn,kind,expired,expected', [
    ('codex','original','tool.post',False,'matched'),
    ('codex','later','tool.failure',False,'matched'),
    ('codex','','tool.post',False,'unknown'),
    ('codex','later','tool.post',True,'incomplete'),
    ('claude','later','tool.post',False,'incomplete'),
    ('claude','original','tool.post',False,'matched'),
])
def test_legacy_turns_failures_and_expiry(service, agent, turn, kind, expired, expected):
    client, factory = service
    identity = dict(agent=agent, session_id='s', native_call_id='c', tool='Bash')
    pre = insert(factory, 1, event={**identity,'turn_id':'original','kind':'tool.pre'})
    insert(factory, 2, event={**identity,'turn_id':turn,'kind':kind}, expired=expired)
    assert client.get(f'{BASE}/{pre}/related').json()['relation'] == expected


def test_timeline_snapshot_does_not_pull_in_late_completion(service):
    client, factory = service
    identity = dict(agent='codex', session_id='s', native_call_id='c', tool='Bash')
    insert(factory, 1, event={**identity, 'turn_id':'a', 'kind':'tool.pre'})
    insert(factory, 2, event={**identity, 'turn_id':'b', 'native_call_id':'d','kind':'tool.pre'})
    params = dict(source='hooks',agent='codex',session_id='s',limit=1)
    page = get(client, '/session-timeline', **params)
    assert page['has_more']
    insert(factory, 3, event={**identity,'native_call_id':'d','turn_id':'late','kind':'tool.post'})
    next_page = get(client, '/session-timeline', cursor=page['next_cursor'], **params)
    assert len(next_page['items'][0]['records']) == 1
    assert next_page['items'][0]['turn_key'] == 'turn:b'
