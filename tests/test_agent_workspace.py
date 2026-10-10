import json
import time
import uuid
from datetime import datetime

from backend import auth, models
from backend.agent_workspace import installation_owns_path
from backend.aidr_hook_control import HookApprovalRow
from backend.sqlite_db import get_db
from tests.test_clients_api import _client
from tests.test_aidr_api import service
from tests.test_aidr_enforcement import control, event


def test_installation_paths_are_bounded_and_windows_aware():
    agent = {'skills_path': '/home/user/skills', 'capabilities': {'skill_roots': ['/shared/skills']}}
    assert installation_owns_path(agent, '/home/user/skills/demo')
    assert installation_owns_path(agent, '/shared/skills/shared')
    assert not installation_owns_path(agent, '/home/user/skills-other/demo')
    assert not installation_owns_path(agent, '/home/user/skills/../other/demo')
    assert not installation_owns_path({}, '/home/user/skills/demo')
    assert installation_owns_path({'skills_path': r'C:\Users\Demo\skills'}, r'c:\users\demo\skills\tool', 'windows')


def test_workspace_scopes_inventory_and_paginates_tasks_before_limiting(tmp_path):
    client = _client(tmp_path)
    database = client.app.dependency_overrides[get_db]()
    db = next(database)
    try:
        db.add(models.ManagedClient(client_id='one', name='demo', hostname='demo', os='darwin', arch='arm64', client_version='dev', registered_by='admin', last_seen_at=datetime.utcnow()))
        db.add_all([models.ClientAgent(client_id='one', local_agent_id=entry, agent_type='codex', skills_path=f'/home/{entry}/skills') for entry in ['cli', 'desktop']])
        db.add_all([models.ClientSkillInstall(client_id='one', agent_type='codex', skill_name=entry, skill_path=f'/home/{entry}/skills/tool') for entry in ['cli', 'desktop']])
        for target in ['cli', 'desktop', 'cli', 'desktop']:
            db.add(models.ClientTask(client_id='one', task_type='verify_model_config', payload_json=json.dumps({'local_agent_id': target}), status='succeeded'))
        db.add(models.ClientTask(client_id='one', task_type='aidr_plugin_action', payload_json=json.dumps({'agent': 'codex', 'action': 'inspect'}), status='pending'))
        db.add(models.ClientTask(client_id='one', task_type='aidr_plugin_action', payload_json=json.dumps({'agent': 'claude', 'action': 'inspect'}), status='pending'))
        db.commit()
        result = client.get('/api/v1/clients/one/agent-workspace', params={'local_agent_id': 'cli', 'limit': 2})
        assert result.status_code == 200, result.text
        data = result.json()
        assert [row['local_agent_id'] for row in data['agents']] == ['cli']
        assert [row['name'] for row in data['agents'][0]['skills']] == ['cli']
        assert len(data['tasks']) == 2 and data['tasks_has_more']
        assert data['tasks'][0]['payload']['agent'] == 'codex'
        assert data['tasks'][1]['payload']['local_agent_id'] == 'cli'
        older = client.get('/api/v1/clients/one/agent-workspace', params={'local_agent_id': 'cli', 'limit': 2, 'before': data['tasks_next_before']}).json()
        assert len(older['tasks']) == 1 and not older['tasks_has_more']
        assert not ({row['id'] for row in older['tasks']} & {row['id'] for row in data['tasks']})
        assert client.get('/api/v1/clients/one/agent-workspace', params={'local_agent_id': 'missing'}).status_code == 404
        client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=2, username='other', role='viewer')
        assert client.get('/api/v1/clients/one/agent-workspace', params={'local_agent_id': 'cli'}).status_code == 404
    finally:
        database.close()


def test_approval_filter_is_applied_before_cursor_pagination(service):
    client, factory = service
    with factory() as db:
        now = int(time.time())
        for index, agent in enumerate(['codex', 'claude', 'codex', 'claude', 'codex']):
            db.add(HookApprovalRow(id=uuid.uuid4().hex, client_id='one', stream_id=uuid.uuid4().hex, event_id=uuid.uuid4().hex,
                                  receiver_instance=uuid.uuid4().hex, nonce=uuid.uuid4().hex, scope=json.dumps({'agent': agent}),
                                  revision=1, state='pending', created_at=now + index, expires_at=now + 300))
        db.commit()
    endpoint = '/api/v1/clients/one/aidr/hook-approvals'
    first = client.get(endpoint, params={'agent': 'codex', 'limit': 2})
    assert first.status_code == 200, first.text
    data = first.json()
    assert [item['scope']['agent'] for item in data['items']] == ['codex', 'codex']
    assert data['has_more']
    older = client.get(endpoint, params={'agent': 'codex', 'limit': 2, 'before': data['next_before'], 'before_id': data['next_before_id']}).json()
    assert len(older['items']) == 1 and not older['has_more']
    assert len(client.get(endpoint).json()['items']) == 5


def test_system_events_match_only_the_selected_executable_or_app_bundle(control):
    from backend.aidr_enforcement import AidrRuntimeRecord
    client, factory, _ = control
    root = '/Applications/Work_Buddy%.app'
    paths = [root + '/Contents/MacOS/Electron', '/Applications/WorkXBuddy1.app/Contents/MacOS/Electron',
             root + '/Contents/Frameworks/helper', root + '.old/Contents/MacOS/Electron', '/usr/bin/codex']
    with factory() as db:
        for index, path in enumerate(paths):
            value = event() | {'sequence': str(index + 1), 'root_path': path}
            db.add(AidrRuntimeRecord(client_id='one', monitor_id=value['monitor_id'], sequence=value['sequence'],
                                    kind='process', payload_json=json.dumps(value), received_at='2026-10-10'))
        db.commit()
    endpoint = '/api/v1/clients/one/aidr/enforcement/records'
    first = client.get(endpoint, params={'installation_path': root, 'limit': 1})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data['items'][0]['record']['root_path'] == paths[2]
    assert data['has_more']
    second = client.get(endpoint, params={'installation_path': root, 'limit': 1, 'before': data['next_before']}).json()
    assert second['items'][0]['record']['root_path'] == paths[0]
    assert not second['has_more']
    exact = client.get(endpoint, params={'installation_path': '/usr/bin/codex'}).json()
    assert [item['record']['root_path'] for item in exact['items']] == ['/usr/bin/codex']
