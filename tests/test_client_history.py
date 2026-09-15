import json
from datetime import datetime, timedelta

from backend import models
from backend.sqlite_db import get_db
from tests.test_clients_api import _client


def test_runtime_history_paginates_filters_and_isolates_clients(tmp_path):
    client = _client(tmp_path)
    token = client.post('/api/v1/access/tokens', json={'name': 'history', 'token_type': 'client'}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    for name in ['history-a', 'history-b']:
        registration_headers = headers if name == 'history-a' else {'Authorization': 'Bearer ' + client.post('/api/v1/access/tokens', json={'name': name, 'token_type': 'client'}).json()['token']}
        assert client.post('/api/v1/clients/register', headers=registration_headers, json={
            'client_id': name, 'name': name, 'hostname': name, 'os': 'linux', 'arch': 'amd64', 'client_version': 'dev', 'agents': [],
        }).status_code == 200
    session = next(client.app.dependency_overrides[get_db]())
    now = datetime.utcnow()
    for i in range(125):
        session.add(models.ClientEvent(client_id='history-a', event_type='skill_governance_detected',
            agent_type='codex', skill_name=f'Skill {i}', details_json='{}', created_at=now,
            last_seen_at=now, observation_count=3))
    session.add(models.ClientEvent(client_id='history-b', event_type='skill_modified', agent_type='claude-code', skill_name='other-client', details_json='{}'))
    session.add(models.ClientEvent(client_id='history-a', event_type='skill_modified', agent_type='claude-code', skill_name='old_100%', details_json='{}', created_at=now-timedelta(days=40)))
    for status in ['failed', 'succeeded']:
        session.add(models.ClientTask(client_id='history-a', task_type='install_skill', status=status,
            payload_json=json.dumps({'agent_type': 'codex', 'skill_name': 'example'}), error='example error' if status == 'failed' else None))
    session.commit()
    session.close()
    url = '/api/v1/clients/history-a/history'
    first = client.get(url, headers=headers).json()
    second = client.get(url, headers=headers, params={'page': 2}).json()
    assert first['total'] == 126 and len(first['items']) == 10
    assert not {row['id'] for row in first['items']} & {row['id'] for row in second['items']}
    last = client.get(url, headers=headers, params={'page': 999}).json()
    assert last['page'] == 13 and len(last['items']) == 6
    assert client.get(url, headers=headers, params={'days': 7}).json()['total'] == 125
    literal = client.get(url, headers=headers, params={'keyword': '100%', 'agent': 'claude-code', 'record_type': 'skill_modified'}).json()
    assert literal['total'] == 1 and literal['items'][0]['skill_name'] == 'old_100%'
    tasks = client.get(url, headers=headers, params={'kind': 'tasks', 'status': 'failed', 'keyword': 'error', 'agent': 'codex'}).json()
    assert tasks['total'] == 1 and tasks['items'][0]['status'] == 'failed'
    assert client.get(url, params={'page_size': 1000}, headers=headers).status_code == 422
    assert client.get(url).status_code in [401, 403]
    assert client.get(url, headers=registration_headers).status_code == 403


def test_runtime_history_filters_governance_actions_by_effective_type(tmp_path):
    client = _client(tmp_path)
    token = client.post('/api/v1/access/tokens', json={'name': 'action-history', 'token_type': 'client'}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    assert client.post('/api/v1/clients/register', headers=headers, json={
        'client_id': 'action-history', 'name': 'action-history', 'hostname': 'action-history',
        'os': 'linux', 'arch': 'amd64', 'client_version': 'dev', 'agents': [],
    }).status_code == 200
    session = next(client.app.dependency_overrides[get_db]())
    session.add_all([
        models.ClientEvent(client_id='action-history', event_type='skill_governance_action',
            agent_type='hermes', skill_name='automatic-quarantine',
            details_json=json.dumps({'action': 'quarantine', 'status': 'completed'})),
        models.ClientEvent(client_id='action-history', event_type='skill_quarantined',
            agent_type='codex', skill_name='legacy-quarantine', details_json='{}'),
        models.ClientEvent(client_id='action-history', event_type='skill_governance_action',
            agent_type='hermes', skill_name='automatic-uninstall',
            details_json=json.dumps({'action': 'uninstall', 'status': 'completed'})),
    ])
    session.commit()
    session.close()

    url = '/api/v1/clients/action-history/history'
    quarantine = client.get(url, headers=headers, params={'record_type': 'skill_quarantined'}).json()
    assert quarantine['total'] == 2
    assert {item['skill_name'] for item in quarantine['items']} == {'automatic-quarantine', 'legacy-quarantine'}
    assert {item['record_type'] for item in quarantine['items']} == {'skill_quarantined'}
    removed = client.get(url, headers=headers, params={'record_type': 'skill_removed'}).json()
    assert removed['total'] == 1
    assert removed['items'][0]['skill_name'] == 'automatic-uninstall'
    assert {'skill_quarantined', 'skill_removed'} <= set(removed['types'])
