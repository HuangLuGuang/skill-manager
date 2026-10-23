import json
from types import SimpleNamespace

import pytest

from backend import client_governance as governance, models
from backend.api_errors import ApiError
from backend.client_desktop_menu import DEFAULT_MENUS
from backend.runtime_governance import record_enrollment
from tests.test_client_governance import db, add_client
from tests.test_client_long_poll import connected


def save(db, scope, **fields):
    view = governance.policy_view(db, None if scope == governance.DEFAULT_SCOPE else scope)
    change = governance.PolicyChange(**{"rules": view['overrides'], "expected_version": view['version'], **fields})
    change.preview_id = governance.preview(db, scope, change)['preview_id']
    result = governance.save_policy(db, scope, change, SimpleNamespace(username='admin'))
    db.commit()
    return result


def test_per_menu_overrides_inherit_and_preserve_runtime_version(db):
    add_client(db, 'one', protocol=2)
    add_client(db, 'two', protocol=2)
    initial = governance.policy_view(db, 'one')
    save(db, 'two', desktop_menu_visibility={'models': True, 'records': False})
    default = save(db, governance.DEFAULT_SCOPE, desktop_menu_visibility={**DEFAULT_MENUS, 'models': False})
    assert default['runtime_governance_version'] == initial['runtime_governance_version']
    assert governance.policy_view(db, 'one')['desktop_menu_visibility']['models'] is False
    two = governance.policy_view(db, 'two')
    assert two['desktop_menu_visibility'] == {**DEFAULT_MENUS, 'records': False}
    assert two['desktop_menu_sources']['models'] == 'client'
    assert two['desktop_menu_sources']['discover'] == 'default'
    assert two['scan_version'] == initial['scan_version']
    preserved = save(db, 'two', rules={})
    assert preserved['desktop_menu_overrides'] == {'models': True, 'records': False}
    inherited = save(db, 'two', desktop_menu_visibility={})
    assert inherited['desktop_menu_visibility'] == default['desktop_menu_visibility']
    assert inherited['desktop_menu_overrides'] == {}


def test_menu_tasks_remain_menu_only_when_superseded_but_preserve_pending_rule_changes(db):
    add_client(db, protocol=2)
    save(db, 'client-1', desktop_menu_visibility={'models': False})
    save(db, 'client-1', desktop_menu_visibility={'records': False})
    tasks = db.query(models.ClientTask).order_by(models.ClientTask.id).all()
    assert tasks[0].status == 'cancelled'
    assert json.loads(tasks[-1].payload_json)['reason'] == 'desktop_menu_visibility_changed'
    save(db, 'client-1', rules={'malicious': 'quarantine'})
    save(db, 'client-1', desktop_menu_visibility={'discover': False})
    task = db.query(models.ClientTask).filter_by(status='pending').one()
    assert json.loads(task.payload_json)['reason'] == 'classification_policy_changed'


def test_enrollment_still_advances_runtime_version_after_menu_edit(db):
    add_client(db, protocol=2)
    initial = save(db, 'client-1', desktop_menu_visibility={'models': False})
    record_enrollment(db, 'client-1', SimpleNamespace(user_hook_hosts=['codex']))
    db.commit()
    enrolled = governance.policy_view(db, 'client-1')
    assert enrolled['runtime_governance_version'] != initial['runtime_governance_version']
    assert enrolled['scan_version'] != initial['scan_version']


def test_old_client_can_save_menus_without_activating_governance(db):
    client = add_client(db, protocol=0, is_new=False)
    client.policy_mode = 'block'
    db.commit()
    saved = save(db, 'client-1', desktop_menu_visibility={'models': False})
    assert saved['desktop_menu_sync_status'] == 'unsupported'
    assert not db.get(models.ClientGovernancePolicy, 'client-1').enabled
    governance.record_protocol(db, 'client-1', 2)
    db.commit()
    upgraded = governance.policy_view(db, 'client-1')
    assert upgraded['rules'] == governance.legacy_policy_rules('block')
    assert upgraded['desktop_menu_visibility']['models'] is False


def test_preview_is_bound_to_menu_values_and_inheritance(db):
    add_client(db, protocol=2)
    view = governance.policy_view(db, 'client-1')
    change = governance.PolicyChange(expected_version=view['version'], desktop_menu_visibility={'models': False})
    preview = governance.preview(db, 'client-1', change)
    assert preview['desktop_menu_impacts'][0]['supported'] is False
    change.preview_id = preview['preview_id']
    change.desktop_menu_visibility['models'] = True
    with pytest.raises(ApiError) as error:
        governance.save_policy(db, 'client-1', change, SimpleNamespace(username='admin'))
    assert error.value.code == 'client.policy_preview_required'
    db.rollback()


@pytest.mark.parametrize('menus', [{'connect': False}, {'unknown': True}, {'models': 0}, {'models': 'false'}, None, []])
def test_invalid_menu_configuration_has_stable_error(menus):
    with pytest.raises(ApiError) as error:
        governance.PolicyChange(expected_version='0:0', desktop_menu_visibility=menus)
    assert error.value.code == 'client.desktop_menu_invalid'


def test_menu_receipt_and_downgrade_status(db):
    add_client(db, protocol=2)
    assert governance.policy_view(db, 'client-1')['desktop_menu_sync_status'] == 'unsupported'
    governance.record_desktop_menus(db, 'client-1', 1, None)
    db.flush()
    assert governance.policy_view(db, 'client-1')['desktop_menu_sync_status'] == 'pending'
    governance.record_desktop_menus(db, 'client-1', 1, dict(DEFAULT_MENUS))
    db.flush()
    assert governance.policy_view(db, 'client-1')['desktop_menu_sync_status'] == 'synced'
    governance.record_desktop_menus(db, 'client-1', 1, None)
    db.flush()
    assert governance.policy_view(db, 'client-1')['desktop_menu_sync_status'] == 'pending'
    db.commit()
    assert save(db, 'client-1', desktop_menu_visibility={'models': False})['desktop_menu_sync_status'] == 'pending'
    governance.record_desktop_menus(db, 'client-1', 0, None)
    db.flush()
    assert governance.policy_view(db, 'client-1')['desktop_menu_sync_status'] == 'unsupported'


def test_api_menu_sync_receipt_and_legacy_ack(tmp_path):
    client, headers = connected(tmp_path)
    path = '/api/v1/clients/waiting/governance'
    view = client.get(path).json()
    request = {'rules': view['overrides'], 'expected_version': view['version'], 'desktop_menu_visibility': {'models': False}}
    preview = client.post(path + '/preview', json=request)
    assert preview.status_code == 200, preview.text
    result = client.put(path, json={**request, 'preview_id': preview.json()['preview_id']})
    assert result.status_code == 200, result.text
    tasks = client.get('/api/v1/clients/waiting/tasks', headers=headers).json()
    task = next(item for item in tasks if item['task_type'] == 'sync_policy')
    receipt = {'status': 'succeeded', 'applied_policy_version': result.json()['version']}
    assert client.post(f"/api/v1/clients/waiting/tasks/{task['id']}/result", headers=headers, json=receipt).status_code == 200
    assert client.get(path).json()['desktop_menu_sync_status'] == 'unsupported'
    response = client.post('/api/v1/clients/waiting/heartbeat', headers=headers, json={
        'client_id': 'waiting', 'governance_protocol': 2, 'desktop_menu_protocol': 1,
        'applied_desktop_menu_visibility': {**DEFAULT_MENUS, 'models': False},
    })
    assert response.status_code == 200, response.text
    assert client.get(path).json()['desktop_menu_sync_status'] == 'synced'
    view = client.get(path).json()
    request = {'rules': view['overrides'], 'expected_version': view['version'], 'desktop_menu_visibility': {}}
    preview = client.post(path + '/preview', json=request).json()
    result = client.put(path, json={**request, 'preview_id': preview['preview_id']}).json()
    task = next(item for item in client.get('/api/v1/clients/waiting/tasks', headers=headers).json() if item['task_type'] == 'sync_policy')
    receipt = {'status': 'succeeded', 'applied_policy_version': result['version'], 'applied_desktop_menu_visibility': DEFAULT_MENUS}
    response = client.post(f"/api/v1/clients/waiting/tasks/{task['id']}/result", headers=headers, json=receipt)
    assert response.status_code == 200, response.text
    assert client.get(path).json()['desktop_menu_sync_status'] == 'synced'
