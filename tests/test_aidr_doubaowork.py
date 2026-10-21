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
