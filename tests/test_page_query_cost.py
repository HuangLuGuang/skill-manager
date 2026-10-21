"""Page reads preserve scope and live metadata while bounding related queries."""
import json
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from sqlalchemy import event

from backend import auth, models, client_governance
from backend.routers import clients, agents
from backend.runtime_governance import HookEnrollment
from tests.test_aidr_api import service
from tests.test_runtime_traces import trace_api, _create, _batch


@contextmanager
def statements(factory):
    sql = []
    engine = factory.kw['bind']
    def observe(_conn, _cursor, statement, *_):
        sql.append(statement)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        yield sql
    finally:
        event.remove(engine, 'before_cursor_execute', observe)


def test_client_list_batches_scope_policies_latest_issues_and_recovery(service):
    client, factory = service
    client.app.include_router(clients.router, prefix='/api')
    with factory() as db:
        db.add(models.ClientGovernancePolicy(scope='@default', revision=3, prompt_guard_json='{"mode":"warn","llm_review":false}'))
        db.add(models.ClientGovernancePolicy(scope='one', protocol=2, enabled=True, revision=2))
        db.add(HookEnrollment(client_id='one', hosts_json='["qoder-hooks"]'))
        db.add(models.ClientAgent(client_id='one', agent_type='codex'))
        # Two observations of one path count once; stale signatures do not count.
        for index, signature, observed in [(1, 'a', 'a'), (2, 'a', 'a'), (3, 'b', 'a')]:
            db.add(models.ClientSkillInstall(client_id='one', agent_type='codex', skill_name=str(index),
                skill_path='/same' if index < 3 else '/stale', signature=signature,
                governance_json=json.dumps(dict(signature=observed, trigger='malicious', action='quarantine'))))
        db.add(models.ClientRecoveryRecord(client_id='one', record_id='r', details_json='{"path":"/same"}'))
        for cid in ('one', 'two'):
            db.add(models.ClientEvent(client_id=cid, agent_type='codex', skill_name='shared', event_type='skill_modified'))
        db.flush()
        db.add(models.ClientEvent(client_id='one', agent_type='codex', skill_name='shared', event_type='skill_verified'))
        for active in (True, False):
            db.add(models.ClientEvent(client_id='one', event_type='aidr_skill_alert', details_json=json.dumps({'active': active})))
        for index in range(204):
            cid = f'bulk-{index}'
            db.add(models.ManagedClient(client_id=cid, name=cid, hostname=cid, os='darwin', arch='arm64', client_version='test', registered_by='owner'))
        db.commit()
    with statements(factory) as sql:
        response = client.get('/api/v1/clients')
    assert response.status_code == 200, response.text
    assert len(response.json()) == 205
    assert len(sql) <= 15  # Two bounded groups, rather than per-client queries.
    assert all(s.lstrip().upper().startswith('SELECT') for s in sql)
    rows = {row['client_id']: row for row in response.json()}
    assert 'two' not in rows
    row = rows['one']
    assert row['issue_count'] == 2
    assert row['recovery'] == [{'path': '/same'}]
    assert len(row['agents'][0]['skills']) == 3
    with factory() as db:
        assert row['classification']['runtime_governance'] == client_governance.policy_view(db, 'one')['runtime_governance']
        db.get(models.ClientGovernancePolicy, '@default').prompt_guard_json = '{"mode":"block","llm_review":false}'
        db.commit()
    row = next(r for r in client.get('/api/v1/clients').json() if r['client_id'] == 'one')
    assert row['classification']['prompt_guard']['mode'] == 'block'
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(username='root', role='super_admin')
    rows = {r['client_id']: r for r in client.get('/api/v1/clients').json()}
    assert rows['two']['issue_count'] == 1  # Same agent/Skill in another client stays independent.


def test_agent_list_and_assets_keep_latest_token_scope_and_current_names(service):
    client, factory = service
    client.app.include_router(agents.router, prefix='/api')
    with factory() as db:
        db.add(models.UserGroup(id=1, name='department'))
        for index in range(100):
            db.add(models.ManagedAgent(agent_id=f'a-{index}', name=f'Agent {index}', created_by='owner', department_group_id=1))
        db.add(models.ManagedAgent(agent_id='hidden', name='hidden', created_by='another-owner'))
        db.flush()
        for index, kind in enumerate(('agent_runtime', 'agent_runtime', 'scanner')):
            db.add(models.AccessToken(name=f'token-{index}', token_type=kind, token_hash=str(index), token_prefix='test',
                                      bound_agent_id='a-0', status='revoked' if index == 1 else 'active'))
        db.commit()
    with statements(factory) as sql:
        response = client.get('/api/agents')
    assert response.status_code == 200, response.text
    assert len(sql) == 4
    rows = response.json()
    assert len(rows) == 100
    assert rows[0]['runtime_token_name'] == 'token-1'
    assert rows[1]['runtime_token_id'] is None
    with factory() as db:
        db.get(models.UserGroup, 1).name = 'renamed'
        db.commit()
    assert client.get('/api/agents?q=Agent%200').json()[0]['department_name'] == 'renamed'
    with statements(factory) as sql:
        response = client.get('/api/agents/assets')
    assert response.status_code == 200, response.text
    assert len(sql) <= 10
    assert len(response.json()['items']) == 100


@pytest.mark.parametrize('path', ['/api/agents', '/api/agents/assets'])
def test_agent_page_database_wait_does_not_block_event_loop(service, path):
    client, factory = service
    client.app.include_router(agents.router, prefix='/api')
    @client.app.get('/page-probe')
    async def probe():
        return {'ok': True}
    entered, release, responsive = Event(), Event(), Event()
    def pause(_conn, _cursor, statement, *_):
        if 'FROM managed_agents' in statement:
            entered.set()
            assert release.wait(5)
    def ping():
        result = client.get('/page-probe')
        if result.status_code == 200:
            responsive.set()
    engine = factory.kw['bind']
    event.listen(engine, 'before_cursor_execute', pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(client.get, path)
            try:
                assert entered.wait(3)
                probe_result = pool.submit(ping)
                assert responsive.wait(2)
            finally:
                release.set()
            assert pending.result().status_code == 200
            probe_result.result()
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', pause)


def test_runtime_event_page_reads_redacted_payload_only_and_preserves_raw_permissions(trace_api):
    client, factory, state, users, plain = trace_api
    trace_id = _create(client, plain)
    batch = _batch(trace_id)
    response = client.post(f'/api/v1/runtime-traces/{trace_id}/events:batch',
                           headers={'Authorization': f'Bearer {plain}'}, json=batch)
    assert response.status_code == 200, response.text
    with statements(factory) as sql:
        response = client.get(f'/api/v1/runtime-traces/{trace_id}/events?page_size=1')
    assert response.status_code == 200, response.text
    assert len(response.json()['items']) == 1 and response.json()['has_more']
    payload_sql = [s for s in sql if 'FROM runtime_trace_payloads' in s]
    assert len(payload_sql) == 1
    assert 'redacted_json' in payload_sql[0] and 'raw_payload_encrypted' not in payload_sql[0]
    assert 'secret-value' not in response.text
    state['user'] = users['other']
    assert client.get(f'/api/v1/runtime-traces/{trace_id}/events').status_code == 403
    state['user'] = users['owner']
    assert client.get(f'/api/v1/runtime-traces/{trace_id}/events/event-1/raw-payload').status_code == 403
    state['user'] = users['privacy']
    raw = client.get(f'/api/v1/runtime-traces/{trace_id}/events/event-1/raw-payload')
    assert raw.status_code == 200 and 'secret-value' in raw.text
