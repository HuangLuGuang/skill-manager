import json
from datetime import datetime

import pytest

from backend.aidr_models import AidrOperation, AidrHookEvent
from tests.test_aidr_api import service
from tests.test_aidr_hook_queries import insert
from tests.test_aidr_operations import event, upload
from tests.test_aidr_sessions import get


def hook(factory, number, **changes):
    return insert(factory, number, event={
        'agent': 'workbuddy', 'session_id': 's', 'turn_id': '',
        'native_call_id': 'c', 'tool': 'Bash', 'kind': 'tool.pre', **changes,
    })


def log(client, turn='r1', **changes):
    response = upload(client, event(
        'tool_call', agent='workbuddy', session='s', turn=turn,
        call='c', tool='Bash', user_scope='501', **changes,
    ))
    assert response.status_code == 200, response.text


def turns(client, **params):
    return get(client, '/session-turns', agent='workbuddy', session_id='s', **params)


def test_exact_workbuddy_link_and_unassigned_lifecycle(service):
    client, factory = service
    hook(factory, 1, context={'model': 'Auto'})
    hook(factory, 2, kind='tool.post')
    for number, kind in enumerate(('turn.submit', 'session.start', 'turn.stop'), 3):
        hook(factory, number, kind=kind, native_call_id='', tool='')
    log(client)
    rows = {r['key']: r for r in turns(client)['items']}
    assert set(rows) == {'turn:r1', 'unassigned'}
    assert rows['turn:r1']['hook_count'] == 2
    assert rows['turn:r1']['hook_models'][0]['value'] == 'Auto'
    assert rows['unassigned']['hook_count'] == 3
    timeline = get(client, '/session-timeline', agent='workbuddy', session_id='s',
                   source='hooks', turn_key='turn:r1')['items']
    assert len(timeline) == 1 and timeline[0]['turn_key'] == 'turn:r1'
    assert len(timeline[0]['records']) == 2
    # Correlation belongs to the read projection; native evidence stays unchanged.
    with factory() as db:
        assert all(not json.loads(row.payload_json)['event']['turn_id']
                   for row in db.query(AidrHookEvent))


@pytest.mark.parametrize('boundary', [
    'client', 'user', 'session', 'tool', 'call', 'agent', 'subagent',
    'missing_user', 'missing_call', 'expired', 'conflict', 'ambiguous',
])
def test_workbuddy_link_requires_exact_unambiguous_evidence(service, boundary):
    client, factory = service
    hook(factory, 1, **({'native_agent_id': 'child'} if boundary == 'subagent' else {}))
    log(client)
    if boundary == 'ambiguous':
        log(client, turn='r2')
    else:
        with factory() as db:
            row = db.query(AidrOperation).one()
            payload = json.loads(row.payload_json)
            if boundary == 'client': row.client_id = 'two'
            if boundary == 'user': payload['call']['user_scope'] = '502'
            if boundary == 'session': row.session_id = payload['call']['session_id'] = 'other'
            if boundary == 'tool': payload['call']['tool'] = 'Read'
            if boundary == 'call': payload['call']['native_call_id'] = 'other'
            if boundary == 'agent': row.agent = payload['call']['agent'] = 'codex'
            if boundary == 'expired': row.expired_at = datetime.utcnow()
            if boundary == 'conflict': payload['conflicting_evidence'] = True
            row.payload_json = json.dumps(payload)
            if boundary in {'missing_user', 'missing_call'}:
                h = db.query(AidrHookEvent).one()
                raw = json.loads(h.payload_json)
                if boundary == 'missing_user': raw['user_scope'] = ''
                else: raw['event']['native_call_id'] = ''
                h.payload_json = json.dumps(raw)
            db.commit()
    rows = {r['key']: r for r in turns(client)['items']}
    assert rows['unassigned']['hook_count'] == 1
    assert all(not r['hook_count'] for key, r in rows.items() if key != 'unassigned')


def test_workbuddy_native_turn_takes_precedence(service):
    client, factory = service
    hook(factory, 1, turn_id='native')
    log(client)
    rows = {r['key']: r for r in turns(client)['items']}
    assert rows['turn:native']['hook_count'] == 1
    assert rows['turn:r1']['hook_count'] == 0


def test_workbuddy_late_log_refresh_and_pagination_snapshot(service):
    client, factory = service
    hook(factory, 1)
    hook(factory, 2, turn_id='native')
    first = turns(client, limit=1)
    assert first['has_more']
    log(client)
    second = turns(client, limit=1, cursor=first['next_cursor'])
    assert {r['key'] for r in first['items'] + second['items']} == {'unassigned', 'turn:native'}
    fresh = {r['key']: r for r in turns(client)['items']}
    assert fresh['turn:r1']['hook_count'] == 1
    assert 'unassigned' not in fresh


def test_workbuddy_prompt_without_turn_is_only_unassigned(service):
    client, factory = service
    hook(factory, 1, kind='turn.submit', native_call_id='', tool='')
    rows = turns(client)['items']
    assert len(rows) == 1 and rows[0]['key'] == 'unassigned'
