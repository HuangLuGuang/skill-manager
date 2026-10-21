import json
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import models
from backend.client_task_notifications import _hubs, _lock, notify_all
from backend.sqlite_db import get_db
from tests.test_clients_api import _client
from agent_manager.core.models import SkillStatus


def connected(tmp_path):
    client = _client(tmp_path)
    token = client.post('/api/v1/access/tokens', json={'name': 'long-poll', 'token_type': 'client'}).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    response = client.post('/api/v1/clients/register', headers=headers, json={
        'client_id': 'waiting', 'name': 'Waiting', 'hostname': 'host', 'os': 'linux', 'arch': 'amd64', 'client_version': 'dev', 'governance_protocol': 2,
    })
    assert response.status_code == 200, response.text
    return client, headers


def await_waiter():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with _lock:
            if any(h.waiters.get('waiting') for h in _hubs.values()):
                return
        time.sleep(.01)
    raise AssertionError('request did not enter async wait')


def test_long_poll_returns_durable_scan_status_revisions(tmp_path):
    entry = type("Entry", (), {
        "skill_id": "version-1", "family_id": "family-1", "name": "demo",
        "status": SkillStatus.PENDING,
    })()

    class Manager:
        def get_skill(self, value, *, include_scan_report=True):
            return entry if value == entry.skill_id else None

        def list_scan_runs(self, _version_id):
            return []

    client = _client(tmp_path, Manager())
    token = client.post('/api/v1/access/tokens', json={'name': 'scan-events', 'token_type': 'client'}).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.post('/api/v1/clients/register', headers=headers, json={
        'client_id': 'waiting', 'name': 'Waiting', 'hostname': 'host', 'os': 'linux', 'arch': 'amd64', 'client_version': 'dev', 'governance_protocol': 2,
    }).status_code == 200

    first = client.get('/api/v1/clients/waiting/tasks?include_events=true&scan_ids=version-1', headers=headers).json()
    assert first['tasks'] == []
    assert first['scan_events'][0]['status'] == 'PENDING'
    revision = first['scan_events'][0]['revision']
    with client, ThreadPoolExecutor() as pool:
        started = time.monotonic()
        future = pool.submit(client.get, f'/api/v1/clients/waiting/tasks?wait_seconds=30&include_events=true&scan_ids=version-1&scan_after_revision={revision}', headers=headers)
        await_waiter()
        entry.status = SkillStatus.APPROVED
        notify_all()
        second_response = future.result(timeout=3)
        assert time.monotonic() - started < 2
    second = second_response.json()
    assert second['scan_events'][0]['status'] == 'APPROVED'
    assert second['scan_events'][0]['revision'] > revision
    replay = client.get(
        f'/api/v1/clients/waiting/tasks?include_events=true&scan_ids=version-1&scan_after_revision={second["scan_events"][0]["revision"]}',
        headers=headers,
    ).json()
    assert replay['scan_events'] == []


def test_long_poll_commit_wakes_without_holding_connection(tmp_path):
    client, headers = connected(tmp_path)
    database = next(client.app.dependency_overrides[get_db]())
    engine = database.get_bind()
    database.close()
    with client, ThreadPoolExecutor() as pool:
        future = pool.submit(client.get, '/api/v1/clients/waiting/tasks?wait_seconds=5', headers=headers)
        await_waiter()
        time.sleep(.1)
        assert engine.pool.checkedout() == 0
        started = time.monotonic()
        with Session(engine) as db:
            task = models.ClientTask(client_id='waiting', task_type='rescan', payload_json='{}')
            db.add(task)
            db.commit()
            task_id = task.id
        response = future.result(timeout=3)
        assert response.status_code == 200
        assert response.json()[0]['id'] == task_id
        assert time.monotonic() - started < 2
        # A persisted receipt cursor prevents repeatedly returning queued tasks.
        started = time.monotonic()
        empty = client.get(f'/api/v1/clients/waiting/tasks?wait_seconds=1&after_id={task_id}', headers=headers)
        assert empty.json() == []
        assert time.monotonic() - started >= .8


def test_long_poll_observes_commit_from_another_engine(tmp_path):
    client, headers = connected(tmp_path)
    other = create_engine(f"sqlite:///{tmp_path / 'clients.db'}")
    try:
        with client, ThreadPoolExecutor() as pool:
            future = pool.submit(client.get, '/api/v1/clients/waiting/tasks?wait_seconds=5', headers=headers)
            await_waiter()
            # Direct SQL bypasses the in-process notification hook, as another worker would.
            with other.begin() as connection:
                connection.execute(models.ClientTask.__table__.insert().values(client_id='waiting', task_type='rescan', payload_json='{}'))
            response = future.result(timeout=3)
            assert response.status_code == 200
            assert len(response.json()) == 1
    finally:
        other.dispose()


def test_discovery_save_wakes_waiting_client(tmp_path):
    client, headers = connected(tmp_path)
    url = '/api/v1/clients/discovery-config'
    catalog = client.get(url).json()
    with client, ThreadPoolExecutor() as pool:
        future = pool.submit(client.get, '/api/v1/clients/waiting/tasks?wait_seconds=30', headers=headers)
        await_waiter()
        saved = client.put(url, json={'expected_version': catalog['version'], 'agents': []})
        assert saved.status_code == 200, saved.text
        response = future.result(timeout=3)
        assert response.status_code == 200
        task = response.json()[0]
        assert task['task_type'] == 'sync_policy'
        assert task['payload']['agent_discovery_version'] == saved.json()['version']


def test_policy_tasks_skip_overrides_supersede_and_require_version_ack(tmp_path):
    client, headers = connected(tmp_path)
    root = '/api/v1/clients/waiting'

    def save(scope, rules):
        current = client.get(scope).json()
        body = {'rules': rules, 'expected_version': current['version']}
        preview = client.post(scope + '/preview', json=body)
        assert preview.status_code == 200, preview.text
        body['preview_id'] = preview.json()['preview_id']
        response = client.put(scope, json=body)
        assert response.status_code == 200, response.text
        return response.json()['version']

    first = save(root + '/governance', {'unverified': 'quarantine'})
    tasks = client.get(root + '/tasks', headers=headers).json()
    assert len(tasks) == 1 and tasks[0]['payload']['target_version'] == first
    save('/api/v1/clients/governance/default', {'unverified': 'record_only'})
    assert len(client.get(root + '/tasks', headers=headers).json()) == 1
    second = save(root + '/governance', {'unverified': 'record'})
    tasks = client.get(root + '/tasks', headers=headers).json()
    assert len(tasks) == 1 and tasks[0]['payload']['target_version'] == second
    records = client.get(root).json()['tasks']
    assert any(t['status'] == 'cancelled' and t['error'] == 'policy_superseded' for t in records)
    old = next(t for t in records if t['error'] == 'policy_superseded')
    assert client.post(root + f"/tasks/{old['id']}/retry").status_code == 409
    task_id = tasks[0]['id']
    report = root + f'/tasks/{task_id}/result'
    assert client.post(report, headers=headers, json={'status': 'running'}).status_code == 200
    wrong = client.post(report, headers=headers, json={'status': 'succeeded'})
    assert wrong.status_code == 409
    assert next(t for t in client.get(root).json()['tasks'] if t['id'] == task_id)['status'] == 'failed'
    third = save(root + '/governance', {'unverified': 'record_only'})
    task_id = client.get(root + '/tasks', headers=headers).json()[0]['id']
    report = root + f'/tasks/{task_id}/result'
    assert client.post(report, headers=headers, json={'status': 'running'}).status_code == 200
    assert client.post(report, headers=headers, json={'status': 'succeeded', 'applied_policy_version': third}).status_code == 200
    assert next(t for t in client.get(root).json()['tasks'] if t['id'] == task_id)['status'] == 'succeeded'


def test_long_poll_rejects_unauthorized_without_waiting(tmp_path):
    client, _ = connected(tmp_path)
    started = time.monotonic()
    assert client.get('/api/v1/clients/waiting/tasks?wait_seconds=30').status_code in (401, 403)
    assert time.monotonic() - started < 2


def test_multiple_waiters_share_monitor_and_ignore_rollback(tmp_path):
    client, headers = connected(tmp_path)
    database = next(client.app.dependency_overrides[get_db]())
    engine = database.get_bind()
    database.close()
    with client, ThreadPoolExecutor() as pool:
        futures = [pool.submit(client.get, '/api/v1/clients/waiting/tasks?wait_seconds=5', headers=headers) for _ in range(3)]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with _lock:
                hubs = [h for h in _hubs.values() if h.engine is engine]
                ready = len(hubs) == 1 and len(hubs[0].waiters.get('waiting', ())) == 3
            if ready:
                break
            time.sleep(.01)
        assert ready
        with Session(engine) as db:
            db.add(models.ClientTask(client_id='waiting', task_type='rescan', payload_json='{}'))
            db.flush()
            db.rollback()
        time.sleep(.2)
        assert not any(f.done() for f in futures)
        with Session(engine) as db:
            db.add(models.ClientTask(client_id='waiting', task_type='rescan', payload_json='{}'))
            db.commit()
        responses = [f.result(timeout=3) for f in futures]
        assert all(r.status_code == 200 and len(r.json()) == 1 for r in responses)
