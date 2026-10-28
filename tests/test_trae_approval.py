"""Platform approval for native TRAE calls, which do not include a turn ID."""
import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from tests.test_aidr_hook_control import base_control, control
from tests.test_aidr_api import service
from tests.test_aidr_hook_control import ROOT, HEADERS, INSTANCE, decision
from tests.test_aidr_hooks import hook_batch, send


@pytest.mark.parametrize('agent', ['trae', 'trae-cn'])
@pytest.mark.parametrize('action', ['allow', 'deny'])
def test_trae_platform_approval_scope_and_signed_decision(control, agent, action):
    client, _, key = control
    policy = {'expected_revision': '0', 'lifetime_seconds': 3600, 'default_action': 'deny',
              'rules': [{'id': 'review', 'agent': agent, 'tool': 'RunCommand', 'decision': 'ask'}]}
    response = client.put(ROOT + '/hook-policy', json=policy)
    assert response.status_code == 200, response.text
    batch = hook_batch()
    record = batch['records'][0]
    record['receiver_instance'] = INSTANCE
    event = record['event']
    event.update(agent=agent, hook_event='PreToolUse', kind='tool.pre', tool='RunCommand',
                 native_call_id='native-call', native_agent_id='solo_agent', input_digest='c' * 64)
    event['behavior'] = dict(version=3, policy=event['policy'], body_omitted=False,
        category='command', method='direct_fields', actions=[], status='unknown',
        result_basis=[], redacted=False, truncated=False, uncertainty=[])
    assert send(client, batch).status_code == 200
    request = dict(expires_at=int(time.time())+180, stream_id=batch['stream_id'], event_id=record['event_id'],
                   receiver_instance=INSTANCE, policy_revision='1', rule_id='review')
    response = client.post(ROOT + '/hook-approvals', json=request, headers=HEADERS)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row['state'] == 'pending'
    assert row['scope']['turn_id'] == ''
    assert row['scope']['native_call_id'] == 'native-call'
    assert row['scope']['agent'] == agent
    assert client.post(ROOT + '/hook-approvals', json=request, headers=HEADERS).json()['id'] == row['id']
    response = decision(client, row, action)
    assert response.status_code == 200, response.text
    assert response.json()['state'] == ('approved' if action == 'allow' else 'denied')
    page = client.post(ROOT + '/hook-control/snapshot',
        json=dict(stream_id=batch['stream_id'], receiver_instance=INSTANCE), headers=HEADERS).json()
    assert len(page['grants']) == 1
    envelope = page['grants'][0]
    payload = base64.b64decode(envelope['payload'])
    key.public_key().verify(base64.b64decode(envelope['signature']), payload, ec.ECDSA(hashes.SHA256()))
    grant = json.loads(payload)
    assert grant['decision'] == action and grant['scope'] == row['scope']
