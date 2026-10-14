import json
import pytest
from datetime import datetime
from tests.test_aidr_api import service, submit
from tests.test_aidr_operations import event, upload
from tests.test_aidr_hook_queries import insert
from tests.test_aidr_sessions import get
from tests.test_aidr_messages import message_event, issued_policy
from backend.aidr_models import AidrEvent, AidrOperation, AidrEventTurn, AidrHookEvent
from backend import auth, models, iam_models


def repair(events, revision=1, turn='user-1'):
    source = events[0]['source_id']
    links = [dict(logical_event_id=e['logical_event_id'], session_id=e['session_id'],
                  native_call_id=e['native_call_id'], content_digest=e['content_digest'], turn_id=turn) for e in events]
    payload = dict(source_id=source, revision=str(revision), turn_links=links,
        cursor=dict(schema_version=1, parser_version='agentlog/1', source_id=source,
                    file_identity='1:2', generation='1', discarding_oversized_record=False,
                    discard_start='0', offset='100', anchor='b'*64, session_id='s', turn_id='',
                    agent_version='2.7.0', since='2026-09-23T00:00:00Z', gap_codes=[]),
        coverage=dict(status='complete', gaps=None, gap_details_truncated=False,
                      reason_codes=[], records=2, ignored=0, filtered=0, skipped_bytes=0, bytes=100))
    return dict(schema_version=1, records=[dict(sequence=str(revision), kind='coverage', record_id=source+':'+str(revision), payload=payload)])


def test_history_repair_preserves_raw_events_and_links_hooks(service):
    client, factory = service
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1, username='owner', role='admin', is_active=True)
    with factory() as db:
        db.add(iam_models.RolePermission(role_name='admin', permission_code='clients:read-audit-content'))
        db.commit()
    policy = issued_policy(client, factory)
    events = [event(k, agent='teleagent', session='s', turn='', call='c', tool='bash' if k=='tool_call' else '', user_scope='501') for k in ('tool_call', 'tool_result')]
    msg = message_event('user', 'unspecified', agent='teleagent', session='s', turn='')
    msg['message']['policy'] = policy
    events.append(msg)
    assert upload(client, *events).status_code == 200
    for n, kind in enumerate(('tool.pre', 'tool.post'), 1):
        insert(factory, n, event=dict(agent='teleagent', session_id='s', turn_id='', native_call_id='c', tool='bash', kind=kind))
    with factory() as db:
        original = {r.id: (r.payload_json, r.content_hash) for r in db.query(AidrEvent)}
    for revision in (1, 1, 2):
        response = submit(client, repair(events, revision))
        assert response.status_code == 200, response.text
    rows = get(client, '/session-turns', agent='teleagent', session_id='s', include_questions=True)['items']
    assert len(rows) == 1 and rows[0]['key'] == 'turn:user-1'
    assert (rows[0]['log_count'], rows[0]['hook_count'], rows[0]['message_count']) == (1, 2, 1)
    assert rows[0]['question']['display_text'] == 'SYNTHETIC-QUESTION'
    timeline = get(client, '/session-timeline', agent='teleagent', session_id='s', source='logs', turn_key='turn:user-1')['items']
    assert len(timeline) == 2 and all(i['turn_key'] == 'turn:user-1' for i in timeline)
    assert all(i['event']['turn_id'] == 'user-1' for i in get(client, '/events')['items'])
    with factory() as db:
        assert original == {r.id: (r.payload_json, r.content_hash) for r in db.query(AidrEvent)}
        assert db.query(AidrOperation).count() == 1
        assert db.query(AidrEventTurn).count() == 3
        assert all(not json.loads(r.payload_json)['event']['turn_id'] for r in db.query(AidrHookEvent))


@pytest.mark.parametrize('boundary', ['source_id', 'session_id', 'native_call_id', 'content_digest', 'other_product', 'conflicting_turn', 'expired', 'other_device'])
def test_repair_identity_and_retention_boundaries(service, boundary):
    client, factory = service
    e = event('tool_call', agent='codex' if boundary=='other_product' else 'teleagent', session='s', turn='', user_scope='501')
    assert upload(client, e).status_code == 200
    body = repair([e])
    if boundary == 'source_id':
        p = body['records'][0]['payload']; p['source_id'] = p['cursor']['source_id'] = 'f'*64
        body['records'][0]['record_id'] = 'f'*64+':1'
    elif boundary in ('session_id', 'native_call_id', 'content_digest'):
        body['records'][0]['payload']['turn_links'][0][boundary] = 'f'*64
    elif boundary == 'conflicting_turn':
        assert submit(client, body).status_code == 200
        body = repair([e], 2, 'different-turn')
    elif boundary in ('expired', 'other_device'):
        with factory() as db:
            row = db.query(AidrEvent).one()
            if boundary == 'expired': row.expired_at = datetime.utcnow()
            else: row.client_id = 'two'
            db.commit()
    response = submit(client, body)
    assert response.status_code == (200 if boundary in ('expired','other_device') else 409), response.text
    with factory() as db:
        assert db.query(AidrEventTurn).count() == (1 if boundary=='conflicting_turn' else 0)
