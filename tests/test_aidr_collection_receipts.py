"""Collection status exposes delivery metadata, never conversation payloads."""
from datetime import datetime, timedelta

from backend import models
from tests.test_aidr_api import service


def test_product_receipts_are_scoped_recent_nonexpired_metadata(service):
    api, factory = service
    now = datetime.utcnow()
    with factory() as db:
        for index, (client, agent, kind, age, expired) in enumerate([
            ('one', 'workbuddy', 'assistant_message', 10, False),
            ('one', 'workbuddy', 'assistant_message', 20, False),
            ('one', 'codex', 'user_message', 30, False),
            ('one', 'codex', 'tool_call', 901, False),
            ('one', 'claude', 'tool_call', 5, True),
            ('two', 'claude', 'tool_call', 2, False),
            ('one', 'claude', 'tool_call', -100, False),
        ]):
            db.add(models.AidrEvent(client_id=client, agent=agent, kind=kind,
                logical_id=f'{index:064x}', content_hash='a'*64,
                payload_json='{"private_body":"must-not-be-returned"}',
                received_at=now-timedelta(seconds=age), expired_at=now if expired else None))
        db.commit()
    response = api.get('/api/v1/clients/one/aidr/status')
    assert response.status_code == 200
    result = response.json()
    assert result['receipt_window_seconds'] == 900
    rows = {(row['agent'], row['kind']): row for row in result['product_receipts']}
    assert set(rows) == {('workbuddy', 'assistant_message'), ('codex', 'user_message')}
    assert rows['workbuddy', 'assistant_message']['count'] == 2
    assert rows['workbuddy', 'assistant_message']['last_received_at'] == (now-timedelta(seconds=10)).isoformat()+'Z'
    assert 'private_body' not in response.text and 'must-not-be-returned' not in response.text
    assert result['log_channel']['health']['state'] == 'unreported'


def test_heartbeat_without_records_has_no_product_receipt(service):
    api, factory = service
    with factory() as db:
        db.get(models.AidrDevice, 'one').last_seen_at = datetime.utcnow()
        db.commit()
    result = api.get('/api/v1/clients/one/aidr/status').json()
    assert result['online'] is True
    assert result['product_receipts'] == []


def test_collection_status_keeps_device_visibility(service):
    api, _ = service
    assert api.get('/api/v1/clients/two/aidr/status').status_code == 404
    assert api.get('/api/v1/clients/two/aidr/status?include_retention=false').status_code == 404


def test_live_status_skips_history_counts_but_preserves_default_contract(service, monkeypatch):
    from backend import aidr_retention
    api, _ = service
    calls = []
    def history(db, client_id):
        calls.append(client_id)
        return {'expired_logs': 7}
    monkeypatch.setattr(aidr_retention, 'view', history)
    compact = api.get('/api/v1/clients/one/aidr/status?include_retention=false')
    assert compact.status_code == 200
    assert calls == []
    assert 'retention' not in compact.json()
    normal = api.get('/api/v1/clients/one/aidr/status')
    assert normal.status_code == 200
    assert calls == ['one']
    full = normal.json()
    assert full.pop('retention') == {'expired_logs': 7}
    assert full == compact.json()
