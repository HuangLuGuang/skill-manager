import base64
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from backend import auth, models
from backend.aidr_hook_control import HookPolicyRow
from backend.aidr_hook_runtime import HookRuntimeRow
from backend.aidr_tool_policy_scope import ToolPolicyConfig, initialize_global_policy
from tests.test_aidr_api import service
from tests.test_aidr_enforcement import control

GLOBAL = '/api/v1/aidr/tool-policy'
ROOT = '/api/v1/clients/one/aidr'
HEADERS = {'authorization': 'Bearer test-one'}
REQUEST = {'stream_id': 'b' * 32, 'receiver_instance': 'e' * 32}


def rules(revision='0', action='allow'):
    return {'expected_revision': revision, 'default_action': action,
            'rules': [{'id': 'review', 'agent': 'codex', 'tool': 'Bash', 'decision': 'ask'}]}


def sync(client):
    result = client.post(ROOT + '/hook-control/snapshot', json=REQUEST, headers=HEADERS)
    assert result.status_code == 200, result.text
    return result.json()


def test_initial_global_revision_is_published_and_inherited(control):
    client, factory, _ = control
    with factory() as db:
        initialize_global_policy(db)
        db.commit()
    view = client.get(GLOBAL).json()
    assert view['revision'] == '1'
    assert view['policy'] == {'default_action': 'allow', 'rules': []}
    assert view['analysis']['published_by'] == 'system'
    device = client.get(ROOT + '/hook-policy').json()
    assert device['inherit'] and device['distribution'] == 'pending'
    envelope = sync(client)['policy']
    payload = json.loads(base64.b64decode(envelope['payload']))
    assert payload['default_action'] == 'allow' and payload['rules'] == []
    with factory() as db:
        initialize_global_policy(db)
        db.commit()
        assert db.query(ToolPolicyConfig).filter_by(scope='global').count() == 1
        assert db.query(HookPolicyRow).count() == 1
    assert sync(client)['policy'] == envelope


def test_initialization_preserves_published_rules_and_legacy_override(control):
    from backend.aidr_hook_control import publish, ToolPolicyInput
    client, factory, _ = control
    with factory() as db:
        publish(db, 'one', ToolPolicyInput(**rules(action='deny')), 'owner')
        initialize_global_policy(db)
        db.commit()
    local = client.get(ROOT + '/hook-policy').json()
    assert not local['inherit'] and local['policy']['default_action'] == 'deny'
    assert client.put(GLOBAL, json=rules('1', 'ask')).status_code == 200
    before = client.get(GLOBAL).json()
    with factory() as db:
        initialize_global_policy(db)
        db.commit()
        assert db.query(ToolPolicyConfig).filter_by(scope='global').count() == 2
    assert client.get(GLOBAL).json() == before
    assert client.get(ROOT + '/hook-policy').json() == local | {'global_revision': '2', 'global_policy': before['policy']}


def test_parallel_initialization_creates_one_revision(control):
    from concurrent.futures import ThreadPoolExecutor
    client, factory, _ = control

    def initialize(_):
        with factory() as db:
            initialize_global_policy(db)
            db.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(initialize, range(4)))
    with factory() as db:
        assert db.query(ToolPolicyConfig).filter_by(scope='global').count() == 1
    assert client.get(GLOBAL).json()['revision'] == '1'


def test_global_lazy_device_signing_idempotent_and_new_revision(control):
    client, factory, key = control
    assert client.get(GLOBAL).json()['impact'] == {'inherited': 2, 'overridden': 0}
    assert client.put(GLOBAL, json=rules()).status_code == 200
    with factory() as db:
        assert db.query(HookPolicyRow).count() == 0
    assert client.get(ROOT + '/hook-policy').json()['distribution'] == 'pending'
    envelope = sync(client)['policy']
    raw = base64.b64decode(envelope['payload'])
    key.public_key().verify(base64.b64decode(envelope['signature']), raw, ec.ECDSA(hashes.SHA256()))
    assert json.loads(raw)['device'] == 'one'
    assert sync(client)['policy'] == envelope
    assert client.get(GLOBAL).json()['impact']['inherited'] == 2
    assert client.put(GLOBAL, json=rules()).status_code == 409
    assert client.put(GLOBAL, json=rules('1', 'deny')).status_code == 200
    assert client.get(ROOT + '/hook-policy').json()['distribution'] == 'pending'
    with factory() as db:
        assert db.query(HookPolicyRow).count() == 1
    newer = json.loads(base64.b64decode(sync(client)['policy']['payload']))
    assert newer['revision'] == '2' and newer['default_action'] == 'deny'
    with factory() as db:
        assert db.query(HookPolicyRow).count() == 2


def test_legacy_override_opt_in_restore_and_conflicts(control):
    client, factory, _ = control
    # A policy issued before scoped configuration remains a device override.
    from backend.aidr_hook_control import publish, ToolPolicyInput
    with factory() as db:
        publish(db, 'one', ToolPolicyInput(**rules()), 'owner')
        db.commit()
    assert client.put(GLOBAL, json=rules(action='deny')).status_code == 200
    view = client.get(ROOT + '/hook-policy').json()
    assert not view['inherit'] and view['policy']['default_action'] == 'allow'
    assert client.get(GLOBAL).json()['impact'] == {'inherited': 1, 'overridden': 1}
    body = {**rules('1'), 'inherit': True, 'expected_global_revision': '0', 'expected_scope_revision': '0'}
    assert client.put(ROOT + '/hook-policy', json=body).status_code == 409
    body['expected_global_revision'] = '1'
    assert client.put(ROOT + '/hook-policy', json=body).status_code == 200
    assert client.put(ROOT + '/hook-policy', json=body).status_code == 409
    assert json.loads(base64.b64decode(sync(client)['policy']['payload']))['default_action'] == 'deny'
    local = {**rules('2'), 'inherit': False, 'expected_scope_revision': '1'}
    assert client.put(ROOT + '/hook-policy', json=local).status_code == 200
    assert client.put(GLOBAL, json=rules('1', 'ask')).status_code == 200
    assert json.loads(base64.b64decode(sync(client)['policy']['payload']))['default_action'] == 'allow'
    local.update(inherit=True, expected_revision='3', expected_scope_revision='2', expected_global_revision='2')
    assert client.put(ROOT + '/hook-policy', json=local).status_code == 200
    assert json.loads(base64.b64decode(sync(client)['policy']['payload']))['default_action'] == 'ask'


def test_command_capability_pending_keeps_previous_and_resumes(control):
    client, factory, _ = control
    assert client.put(GLOBAL, json=rules()).status_code == 200
    original = sync(client)['policy']
    body = rules('1')
    body['rules'][0].update(decision='deny', command={'executable': 'rm'})
    assert client.put(GLOBAL, json=body).status_code == 200
    assert sync(client)['policy'] is None
    with factory() as db:
        assert db.query(HookPolicyRow).count() == 1
        assert db.query(HookPolicyRow).first().envelope == json.dumps(original, sort_keys=True, separators=(',', ':'))
        db.add(HookRuntimeRow(client_id='one', stream_id='b' * 32, receiver_instance='e' * 32, sequence=1,
            payload=json.dumps({'command_rules_schema': 1}), received_at=int(time.time())))
        db.commit()
    assert json.loads(base64.b64decode(sync(client)['policy']['payload']))['schema'] == 3


def test_global_permissions_preview_and_pending_approval_rejection(control):
    client, factory, _ = control
    assert client.put(GLOBAL, json=rules()).status_code == 200
    sync(client)
    assert client.put(GLOBAL, json=rules('1')).status_code == 200
    request = {**REQUEST, 'event_id': 'a' * 32, 'policy_revision': '1', 'rule_id': 'review'}
    assert client.post(ROOT + '/hook-approvals', json=request, headers=HEADERS).status_code == 409
    result = client.post(GLOBAL + '/preview', json={'policy': rules(), 'agent': 'codex', 'tool': 'Bash'})
    assert result.status_code == 200
    with factory() as db:
        assert db.query(ToolPolicyConfig).filter_by(scope='global').count() == 2
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1, username='owner', role='user')
    assert client.get(GLOBAL).status_code == 403
    assert client.put(GLOBAL, json=rules('2')).status_code == 403
    assert client.post(GLOBAL + '/preview', json={'policy': rules(), 'agent': 'codex', 'tool': 'Bash'}).status_code == 403


def test_pending_global_revision_invalidates_platform_approval(control):
    from tests.test_aidr_hook_control import pending, decision
    client, _, _ = control
    assert client.put(GLOBAL, json=rules()).status_code == 200
    sync(client)
    approval, _ = pending(client)
    assert client.put(GLOBAL, json=rules('1', 'deny')).status_code == 200
    assert decision(client, approval, 'allow').status_code == 409
    sync(client)
    assert decision(client, approval, 'allow').status_code == 409


def test_parallel_publication_has_one_winner(control):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client, factory, _ = control
    barrier = Barrier(2)

    def publish(action):
        barrier.wait(timeout=10)
        return client.put(GLOBAL, json=rules(action=action)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(publish, ['allow', 'deny'])) == [200, 409]
    with factory() as db:
        assert db.query(ToolPolicyConfig).filter_by(scope='global').count() == 1
