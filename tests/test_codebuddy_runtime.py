"""Opt-in ingestion of batches captured by the local CodeBuddy IDE harness."""
import json
import os
from pathlib import Path

import pytest

from tests.test_aidr_api import service, submit
from tests.test_aidr_hooks import send
from tests.test_aidr_content import configure
from backend import aidr_policy


def test_codebuddy_captured_batches(service):
    output = os.environ.get('CODEBUDDY_TEST_OUTPUT')
    if not output:
        pytest.skip('real IDE batches not requested')
    client, factory = service
    root = Path(output)
    logs = json.loads((root / 'log-batch.json').read_text())
    hooks = json.loads((root / 'hook-batch.json').read_text())
    configure(factory, capture=dict(prompt=True, tool_output=True, file_body=True, model_response=True))
    # Rebind only the isolated harness receipts to this test backend's streams.
    with factory() as db:
        log_policy = aidr_policy.issue(db, 'one', 'a' * 32, 0, content_supported=True, message_supported=True, model_context_supported=True)
        hook_policy = aidr_policy.issue(db, 'one', hooks['stream_id'], 0, content_supported=True, message_supported=True)
        db.commit()
    for record in logs['records']:
        if record['kind'] == 'event':
            for field in ('behavior', 'message'):
                if record['payload'].get(field):
                    record['payload'][field]['policy'] = log_policy
    for record in hooks['records']:
        record['event']['policy'] = hook_policy
        if record['event'].get('behavior'):
            record['event']['behavior']['policy'] = hook_policy
    events = [r['payload'] for r in logs['records'] if r['kind'] == 'event']
    assert events and all(e['agent'] == 'codebuddy' for e in events)
    assert any(e.get('skill_use') for e in events)
    assert any(r['event'].get('control_decision', {}).get('decision') == 'deny' for r in hooks['records'])
    for _ in range(2):
        result = submit(client, logs)
        assert result.status_code == 200, result.text
        assert result.json()['durable']
        result = send(client, hooks)
        assert result.status_code == 200, result.text
        assert result.json()['durable']
    for source in ('logs', 'hooks'):
        result = client.get('/api/v1/clients/one/aidr/session-timeline', params={
            'agent': 'codebuddy', 'session_id': events[0]['session_id'], 'source': source,
        })
        assert result.status_code == 200, result.text
        assert result.json()['items']
