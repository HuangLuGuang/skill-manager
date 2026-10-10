"""Effective audit policy isolation, delivery revisions and device retention."""
from datetime import datetime, timedelta, timezone

import pytest

from backend import aidr_policy, auth, iam, models
from backend.aidr_enforcement import AidrRuntimeRecord
from backend.aidr_models import AidrOperation
from backend.aidr_retention import expire_once
from backend.routers import system
from tests.test_aidr_api import service, submit
from tests.test_aidr_redaction import behavior
from tests.test_aidr_api import batch

GLOBAL = '/api/system/aidr-redaction'
LOCAL = '/api/v1/clients/one/aidr/audit-policy'


@pytest.fixture
def policies(service):
    client, factory = service
    client.app.include_router(system.router, prefix='/api')
    actor = models.User(id=1, username='owner', role='admin', is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: actor
    with factory() as db:
        iam.initialize(db)
    return client, factory, actor


def draft(value, inherit=False, **changes):
    return {**{key: value[key] for key in ('enabled', 'capture', 'lifecycle', 'version')},
            'inherit': inherit, 'global_version': value['global_policy']['version'], **changes}


def delivered(client, target='one', **changes):
    response = client.post(f'/api/v1/clients/{target}/aidr/audit-policy',
        json={'stream_id': 'a' * 32, 'last_sequence': '0', **changes},
        headers={'authorization': f'Bearer test-{target}', 'X-AIDR-Policy-Schema': '2', 'X-AIDR-Audit-Lifecycle': '1'})
    assert response.status_code == 200, response.text
    return response.json()


def test_override_global_changes_restore_and_delivery(policies):
    client, factory, _ = policies
    initial = client.get(LOCAL).json()
    assert initial['inherit'] and initial['can_edit'] and initial['version'] == '1'
    override = client.put(LOCAL, json=draft(initial, enabled=False, capture={'prompt': True, 'tool_output': False, 'file_body': False},
        lifecycle={'enabled': True, 'retention_days': 30}))
    assert override.status_code == 200, override.text
    override = override.json()
    assert not override['inherit'] and override['version'] == '2'
    assert client.get(GLOBAL).json()['version'] == '1'
    receipt = delivered(client)
    assert receipt['version'] == '2' and receipt['capture']['prompt'] and not receipt['enabled']
    assert delivered(client, 'two')['version'] == '1'
    assert client.put(GLOBAL, json={'version': '1', 'enabled': True, 'lifecycle': {'enabled': False, 'retention_days': 2}}).status_code == 200
    assert client.get(LOCAL).json()['version'] == '2'
    assert delivered(client) == receipt
    assert delivered(client, 'two')['lifecycle'] == {'enabled': False, 'retention_days': 2}
    # Restoring inheritance must review the latest global values.
    assert client.put(LOCAL, json=draft(override, inherit=True)).status_code == 409
    refreshed = client.get(LOCAL).json()
    response = client.put(LOCAL, json=draft(refreshed, inherit=True))
    assert response.status_code == 200, response.text
    restored = response.json()
    assert restored['inherit'] and restored['version'] == '4'
    assert restored['lifecycle'] == {'enabled': False, 'retention_days': 2}
    assert delivered(client)['version'] == '4'
    # The next global update reaches inherited devices with a newer numeric revision.
    assert client.put(GLOBAL, json={'version': '3', 'enabled': False}).json()['version'] == '5'
    assert delivered(client)['version'] == '5'
    assert delivered(client, 'two')['version'] == '5'
    with factory() as db:
        assert aidr_policy.current(db, 'one')['inherit']
        from backend.iam_models import ManagementAudit
        assert db.query(ManagementAudit).filter_by(target=aidr_policy.CLIENT_KEY + 'one').count() == 2


def test_same_values_override_is_persistent_and_stale_saves_fail(policies):
    client, _, _ = policies
    initial = client.get(LOCAL).json()
    local = client.put(LOCAL, json=draft(initial)).json()
    assert not local['inherit'] and local['version'] == '2'
    assert client.put(LOCAL, json=draft(initial, enabled=False)).status_code == 409
    assert client.put(LOCAL, json=draft(local)).json()['version'] == '2'
    assert client.put(GLOBAL, json={'version': '1', 'enabled': False}).status_code == 200
    assert delivered(client)['enabled'] is True
    assert delivered(client, 'two')['enabled'] is False


def test_policy_permissions_and_validation(policies):
    client, factory, actor = policies
    value = draft(client.get(LOCAL).json())
    assert client.put(LOCAL, json={**value, 'lifecycle': {'enabled': True, 'retention_days': 0}}).status_code == 422
    assert client.put(LOCAL, json={**value, 'inherit': 'false'}).status_code == 422
    assert client.get(LOCAL.replace('/one/', '/missing/')).status_code == 404
    assert client.get(LOCAL.replace('/one/', '/two/')).status_code == 404
    assert client.put(LOCAL.replace('/one/', '/two/'), json=value).status_code == 404
    from backend.iam_models import RolePermission
    with factory() as db:
        db.query(RolePermission).filter_by(role_name='admin', permission_code='clients:update').delete()
        db.commit()
    assert not client.get(LOCAL).json()['can_edit']
    assert client.put(LOCAL, json=value).status_code == 403
    actor.role = 'user'
    assert client.put(LOCAL, json=value).status_code == 403


def test_policy_switch_preserves_authorized_backlog(policies):
    client, _, _ = policies
    # Legacy content negotiation keeps the existing behavior wire contract.
    def legacy(**changes):
        return client.post(LOCAL, json={'stream_id': 'a' * 32, 'last_sequence': '1', **changes},
                           headers={'authorization': 'Bearer test-one'}).json()
    first = client.post(LOCAL, json={'stream_id': 'a' * 32, 'last_sequence': '0'}, headers={'authorization': 'Bearer test-one'}).json()
    local = client.put(LOCAL, json=draft(client.get(LOCAL).json(), enabled=False)).json()
    second = legacy()
    pending = batch()
    pending['records'][0]['payload'].update(schema_version=2, behavior=behavior(first, 'printf audit-policy-check'))
    assert submit(client, pending).status_code == 200
    restored = client.put(LOCAL, json=draft(local, inherit=True)).json()
    third = legacy(applied_receipt=second['receipt'], applied_after='1')
    assert int(third['version']) > int(second['version']) and third['version'] == restored['version']
    assert submit(client, pending).status_code == 200


def test_retention_uses_each_device_policy_before_row_budget(policies):
    client, factory, _ = policies
    long = client.put(LOCAL, json=draft(client.get(LOCAL).json(), lifecycle={'enabled': True, 'retention_days': 30})).json()
    now = datetime.utcnow()
    with factory() as db:
        for cid, age in [('one', 10), ('two', 8)]:
            for i in range(3):
                received = now - timedelta(days=age)
                db.add(AidrOperation(client_id=cid, operation_key=f'{i:064x}', agent='codex', session_id='test', tool='exec', result_status='unknown', latest_at=received.isoformat(), payload_json='{}', received_at=received))
                db.add(AidrRuntimeRecord(client_id=cid, monitor_id='test', sequence=str(i), kind='exec', payload_json='{"test":true}', received_at=received.replace(tzinfo=timezone.utc).isoformat()))
        db.commit()
        counts = expire_once(db, now, limit=2)
        assert counts['aidr_operations'] == counts['aidr_runtime_records'] == 2
        assert db.query(AidrOperation).filter_by(client_id='one', expired_at=None).count() == 3
        assert db.query(AidrRuntimeRecord).filter_by(client_id='one', expired_at=None).count() == 3
        assert expire_once(db, now, limit=2)['aidr_operations'] == 1
    # A shorter device override applies to its existing history as well.
    assert client.put(LOCAL, json=draft(long, lifecycle={'enabled': True, 'retention_days': 1})).status_code == 200
    with factory() as db:
        counts = expire_once(db, now)
        assert counts['aidr_operations'] == counts['aidr_runtime_records'] == 3
