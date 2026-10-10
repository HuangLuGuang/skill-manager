import json
from datetime import datetime, timedelta, timezone

from backend import models
from backend.aidr_system_selection import SystemSelection
from backend.client_governance import RuntimeGovernanceConfig
from tests.test_aidr_enforcement import control, ROOT, HEADERS, policy
from tests.test_aidr_api import service


def configure(factory, products=None, mode='client'):
    with factory() as db:
        row = models.ClientGovernancePolicy(scope='one', protocol=2, enabled=True, revision=1)
        runtime = RuntimeGovernanceConfig(channels={'logs': True, 'hooks': True, 'system': True},
            system_targets={'selection_mode': mode, 'products': products or ['codex', 'workbuddy']})
        row.runtime_governance_json = json.dumps(runtime.model_dump())
        db.add(row)
        db.commit()


def candidate(product='codex', identity='a', availability='available'):
    return dict(id=identity * 64, product=product, path=f'/Applications/{product}/program',
                entry='cli', availability=availability, source='common_path')


def discover(client, items=None):
    response = client.post(ROOT+'/collection/discovery', headers=HEADERS, json={'items': items or [candidate()]})
    assert response.status_code == 200, response.text
    return response.json()


def select(client, state, ids=None):
    return client.post(ROOT+'/collection/selection', headers=HEADERS, json={
        'expected_version': state['version'], 'expected_revision': state['revision'], 'ids': ids or ['a'*64]})


def test_discovery_device_binding_and_selection_signed_idempotently(control):
    client, factory, _ = control
    configure(factory)
    assert client.get(ROOT+'/collection/device').status_code == 401
    assert client.post(ROOT.replace('/one/', '/two/')+'/collection/discovery', headers=HEADERS, json={'items': []}).status_code == 403
    state = discover(client)
    response = select(client, state)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state['configured_roots'] == [candidate()['path']]
    assert state['selected_ids'] == ['a'*64]
    assert select(client, state).json()['revision'] == state['revision']
    assert client.get(ROOT+'/snapshot', headers=HEADERS).json()['envelope']


def test_device_cannot_select_unreported_unavailable_or_disallowed_targets(control):
    client, factory, _ = control
    configure(factory, ['codex'])
    state = discover(client, [candidate(), candidate('workbuddy', 'b'), candidate('codex', 'c', 'unsigned') | {'path': '/tmp/unsigned'}])
    for ids in [['b'*64], ['c'*64], ['d'*64], ['a'*64, 'a'*64]]:
        response = select(client, state, ids)
        assert response.status_code == 409, response.text
    assert client.get(ROOT+'/snapshot', headers=HEADERS).json()['envelope'] is None


def test_stale_inventory_requires_new_discovery(control):
    client, factory, _ = control
    configure(factory)
    state = discover(client)
    with factory() as db:
        db.get(SystemSelection, 'one').reported_at = (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
        db.commit()
    assert select(client, state).json()['error_code'] == 'aidr.system_discovery_stale'


def test_platform_specified_requires_each_product_and_detects_concurrent_edits(control):
    client, factory, _ = control
    configure(factory, mode='platform')
    state = discover(client, [candidate(), candidate('workbuddy', 'b')])
    assert select(client, state).json()['error_code'] == 'aidr.system_required_product_missing'
    response = select(client, state, ['a'*64, 'b'*64])
    assert response.status_code == 200, response.text
    assert select(client, state, ['a'*64, 'b'*64]).json()['error_code'] == 'aidr.system_selection_conflict'


def test_narrowing_scope_updates_signed_roots_and_preserves_other_policy(control):
    client, factory, _ = control
    configure(factory)
    assert client.post(ROOT+'/policy', json=policy()).status_code == 200
    state = discover(client, [candidate(), candidate('workbuddy', 'b')])
    response = select(client, state, ['a'*64, 'b'*64])
    assert response.status_code == 200, response.text
    state = response.json()
    response = client.post(ROOT+'/collection', json={'expected_version': state['version'], 'enabled': True,
        'requirements': {'selection_mode': 'client', 'products': ['codex']}})
    assert response.status_code == 200, response.text
    assert response.json()['configured_roots'] == [candidate()['path']]
    signed = client.get(ROOT+'/policy').json()['policy']
    assert signed['rules'] == policy()['rules']
    assert signed['expired_action'] == 'deny'
    assert signed['unknown_actor_action'] == 'allow'


def test_disabling_collection_clears_signed_targets(control):
    client, factory, _ = control
    configure(factory)
    state = select(client, discover(client)).json()
    response = client.post(ROOT+'/collection', json={'expected_version': state['version'], 'enabled': False,
        'requirements': state['requirements']})
    assert response.status_code == 200, response.text
    assert response.json()['configured_roots'] == []
    assert client.get(ROOT+'/bootstrap', headers=HEADERS).json()['error_code'] == 'aidr.system_collection_disabled'


def test_discovery_does_not_select_new_programs(control):
    client, factory, _ = control
    configure(factory)
    select(client, discover(client))
    state = discover(client, [candidate(), candidate('workbuddy', 'b')])
    assert state['selected_ids'] == ['a'*64]
    assert state['configured_roots'] == [candidate()['path']]


def test_admin_save_requires_current_version(control):
    client, factory, _ = control
    configure(factory)
    response = client.post(ROOT+'/collection', json={'expected_version': '0:0', 'enabled': True,
        'requirements': {'selection_mode': 'client', 'products': ['codex']}})
    assert response.status_code == 409, response.text


def test_existing_signed_scope_requires_discovery_before_adoption(control):
    client, factory, _ = control
    configure(factory)
    assert client.post(ROOT+'/policy', json=policy()).status_code == 200
    state = client.get(ROOT+'/collection').json()
    response = client.post(ROOT+'/collection', json={'expected_version': state['version'], 'enabled': True,
        'requirements': {'selection_mode': 'client', 'products': ['codex']}})
    assert response.status_code == 409, response.text
    assert response.json()['error_code'] == 'aidr.system_discovery_required'
    assert client.get(ROOT+'/collection').json()['configured_roots'] == state['configured_roots']
