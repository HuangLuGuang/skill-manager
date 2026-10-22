"""Standalone Doubao catalog and wire contract using synthetic events."""
import json
from pathlib import Path

from backend.aidr_contract import Event
from backend import aidr_adapters
from tests.test_aidr_api import service, batch, submit


def test_doubaowork_contract():
    root = Path(__file__).resolve().parents[1]
    products = json.loads((root / 'backend/aidr_products.json').read_text())
    product = next(p for p in products if p['id'] == 'doubaowork')
    assert product['log_os'] == ['darwin']
    assert not product['hooks'] and not product['block']
    assert aidr_adapters.get('doubaowork').session_call_identity
    vectors = json.loads((root / 'scanner/internal/aidr/agentlog/testdata/contracts.json').read_text())
    event = next(v['event'] for v in vectors if v['valid']).copy()
    event.update(agent='doubaowork', observed_at_source='collection')
    assert Event.model_validate(event).observed_at_source == 'collection'


def test_doubaowork_pair_and_durable_replay(service):
    client, _ = service
    value = batch()
    call = value['records'][0]['payload']
    call.update(agent='doubaowork', session_id='doubao-test-session', turn_id='',
                tool='mcp__local__probe', observed_at_source='collection')
    result = {**call, 'kind': 'tool_result', 'logical_event_id': 'd' * 64,
              'event_id': 'e' * 64, 'outcome': 'unknown'}
    value['records'].append(dict(sequence='2', kind='event',
                                 record_id=result['logical_event_id'], payload=result))
    for _ in range(2):
        response = submit(client, value)
        assert response.status_code == 200, response.text
        assert response.json()['durable']
    rows = client.get('/api/v1/clients/one/aidr/events', params={'agent': 'doubaowork'}).json()['items']
    assert len(rows) == 2
    assert {r['event']['logical_call_id'] for r in rows} == {call['logical_call_id']}
    assert {r['event']['observed_at_source'] for r in rows} == {'collection'}
    timeline = client.get('/api/v1/clients/one/aidr/session-timeline', params={
        'agent': 'doubaowork', 'session_id': 'doubao-test-session', 'source': 'logs'})
    assert timeline.status_code == 200, timeline.text


def test_doubaowork_messages_keep_session_in_timeline(service):
    from tests.test_aidr_messages import message_event, issued_policy
    from tests.test_aidr_operations import upload

    client, factory = service
    policy = issued_policy(client, factory)
    events = [message_event(role, 'unspecified', agent='doubaowork',
                            session_id='38448314780511234', turn_id='',
                            observed_at_source='collection') for role in ('user', 'assistant')]
    for event in events:
        event['message']['policy'] = policy
    response = upload(client, *events)
    assert response.status_code == 200, response.text
    sessions = client.get('/api/v1/clients/one/aidr/sessions', params={'agent': 'doubaowork'}).json()['items']
    assert len(sessions) == 1
    assert sessions[0]['session_id'] == '38448314780511234'
    assert sessions[0]['message_count'] == 2
    timeline = client.get('/api/v1/clients/one/aidr/session-timeline', params={
        'agent': 'doubaowork', 'session_id': '38448314780511234', 'source': 'logs'})
    assert timeline.status_code == 200, timeline.text
    items = timeline.json()['items']
    assert len(items) == 2
    assert {i['message']['session_id'] for i in items} == {'38448314780511234'}


def test_doubaowork_historical_native_turn_links(service):
    from tests.test_aidr_operations import event, upload
    from tests.test_teleagent_turn_links import repair
    from backend.aidr_models import AidrEvent, AidrOperation

    client, factory = service
    first = [event(k, agent='doubaowork', session='s', turn='', call='call-a', tool='Bash') for k in ('tool_call', 'tool_result')]
    second = [event(k, agent='doubaowork', session='s', turn='', call='call-b', tool='Bash') for k in ('tool_call', 'tool_result')]
    unresolved = event('tool_call', agent='doubaowork', session='s', turn='', call='mcp-a', tool='mcp__local__probe')
    assert upload(client, *first, *second, unresolved).status_code == 200
    with factory() as db:
        original = {r.id: (r.payload_json, r.content_hash) for r in db.query(AidrEvent)}
    for group, revision, turn in [(first, 1, 'message-a'), (second, 2, 'message-b'), (first, 1, 'message-a')]:
        response = submit(client, repair(group, revision, turn))
        assert response.status_code == 200, response.text
    response = client.get('/api/v1/clients/one/aidr/session-turns', params={'agent': 'doubaowork', 'session_id': 's'})
    assert response.status_code == 200, response.text
    assert {r['key'] for r in response.json()['items']} == {'turn:message-a', 'turn:message-b', 'unassigned'}
    with factory() as db:
        assert original == {r.id: (r.payload_json, r.content_hash) for r in db.query(AidrEvent)}
        assert db.query(AidrOperation).count() == 3
    conflicting = submit(client, repair(first, 3, 'message-b'))
    assert conflicting.status_code == 409
