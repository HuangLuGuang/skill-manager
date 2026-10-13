import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event

from backend import models
from backend.agent_mcp import MCP_SCOPES, migrate_agent_mcp_scope
from backend.routers import agents, mcp_gateway
from tests.test_mcp_gateway import _client, _configured_gateway, _gateway_token


def setup_agent(tmp_path, monkeypatch):
    client, sessions = _client(tmp_path, monkeypatch)
    client.app.include_router(agents.router)
    gateway = _configured_gateway(client)
    created = client.post('/agents', json={
        'agent_id': 'mcp-agent', 'name': 'MCP Agent', 'allowed_mcp_gateways': ['readonly'],
    })
    assert created.status_code == 200, created.text
    return client, sessions, created.json(), gateway


def issue(client, **extra):
    return client.post('/api/v1/access/tokens', json={
        'name': 'Agent MCP', 'token_type': 'agent_runtime', 'bound_agent_id': 'mcp-agent',
        'scopes': sorted(MCP_SCOPES), 'allowed_mcp_gateways': ['readonly'], **extra,
    })


def rpc(client, secret, method='tools/list', gateway='readonly'):
    return client.post(f'/mcp/{gateway}', headers={'Authorization': f'Bearer {secret}'}, json={
        'jsonrpc': '2.0', 'id': 1, 'method': method,
        'params': {'name': 'crm__search', 'arguments': {'query': 'sample'}},
    })


def test_agent_scope_revocation_is_immediate_and_addition_does_not_expand_token(tmp_path, monkeypatch):
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    token = issue(client).json()
    assert rpc(client, token['token']).status_code == 200
    ordinary = _gateway_token(client)
    with sessions() as db:
        db.add(models.McpGateway(slug='second', name='Second', status='active'))
        db.commit()
    changed = client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': ['readonly', 'second']})
    assert changed.status_code == 200
    assert rpc(client, token['token'], gateway='second').status_code == 403
    removed = client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': []})
    assert removed.status_code == 200
    for method in ['initialize', 'ping', 'notifications/initialized', 'tools/list', 'tools/call']:
        denied = rpc(client, token['token'], method)
        assert denied.status_code == 403
        assert denied.json()['error_code'] == 'agent.mcp_scope_exceeded'
    assert rpc(client, ordinary).status_code == 200
    assert issue(client).json()['error_code'] == 'agent.mcp_scope_exceeded'
    assert client.put(f"/api/v1/access/tokens/{token['record']['id']}", json={'status': 'disabled'}).status_code == 200
    reenable = client.put(f"/api/v1/access/tokens/{token['record']['id']}", json={'status': 'active'})
    assert reenable.status_code == 403
    detail = client.get(f"/agents/{agent['id']}/mcp-access").json()
    assert detail['gateways'] == []
    assert detail['recent_calls'][0]['status'] == 'denied'


def test_gateway_selection_and_metadata_use_current_published_tools(tmp_path, monkeypatch):
    client, sessions, agent, gateway = setup_agent(tmp_path, monkeypatch)
    options = client.get('/agents/mcp-options')
    assert options.status_code == 200
    assert options.json()[0]['tools'][0]['name'] == 'crm__search'
    assert 'authorization' not in options.text and 'endpoint' not in options.text
    with sessions() as db:
        tool = db.query(models.McpTool).filter_by(name='search').one()
        tool.schema_hash = 'changed'
        db.commit()
    assert client.get('/agents/mcp-options').json()[0]['tools'] == []
    with sessions() as db:
        db.get(models.McpGateway, gateway['id']).status = 'disabled'
        db.commit()
    retained = client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': ['readonly']})
    assert retained.status_code == 200
    invalid = client.post('/agents', json={'agent_id': 'new', 'name': 'New', 'allowed_mcp_gateways': ['readonly']})
    assert invalid.status_code == 422
    assert invalid.json()['error_code'] == 'agent.mcp_gateway_unavailable'
    renamed = client.put(f"/agents/{agent['id']}", json={'name': 'Renamed'})
    assert renamed.json()['allowed_mcp_gateways'] == ['readonly']
    assert client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': None}).status_code == 422
    with sessions() as db:
        db.delete(db.get(models.McpGateway, gateway['id']))
        db.commit()
    detail = client.get(f"/agents/{agent['id']}/mcp-access").json()
    assert detail['gateways'][0]['status'] == 'missing'


@pytest.mark.parametrize('kind', ['expired', 'disabled', 'partial', 'active'])
def test_detail_distinguishes_credential_coverage_and_actual_calls(tmp_path, monkeypatch, kind):
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    empty = client.get(f"/agents/{agent['id']}/mcp-access").json()
    assert empty['recent_calls'] == []
    assert empty['gateways'][0]['credential_configured'] is False
    token = issue(client).json()
    with sessions() as db:
        row = db.get(models.AccessToken, token['record']['id'])
        if kind == 'expired':
            row.expires_at = datetime.utcnow() - timedelta(days=1)
        if kind == 'disabled':
            row.status = 'disabled'
        if kind == 'partial':
            row.scopes_json = '["mcp:connect", "mcp:list-tools"]'
        db.commit()
    detail = client.get(f"/agents/{agent['id']}/mcp-access").json()
    assert detail['gateways'][0]['credential_configured'] is (kind == 'active')
    assert detail['recent_calls'] == []
    if kind == 'active':
        assert rpc(client, token['token'], 'tools/call').json()['result']
        detail = client.get(f"/agents/{agent['id']}/mcp-access").json()
        assert detail['recent_calls'][0]['status'] == 'success'
        assert client.put(f"/agents/{agent['id']}", json={'status': 'disabled'}).status_code == 200
        assert rpc(client, token['token']).json()['error_code'] == 'agent.disabled'


def test_credential_updates_cannot_exceed_agent_scope(tmp_path, monkeypatch):
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    token = issue(client).json()
    with sessions() as db:
        db.add(models.McpGateway(slug='second', name='Second', status='active'))
        db.commit()
    for request in [
        lambda: issue(client, allowed_mcp_gateways=['second']),
        lambda: client.put(f"/api/v1/access/tokens/{token['record']['id']}", json={'allowed_mcp_gateways': ['second']}),
    ]:
        response = request()
        assert response.status_code == 403
        assert response.json()['error_code'] == 'agent.mcp_scope_exceeded'
    assert client.get('/agents/assets').json()['items'][0]['allowed_mcp_gateways'] == ['readonly']


def test_client_rotation_only_copies_current_agent_and_credential_grants(tmp_path, monkeypatch):
    from backend.routers.clients import _agent_gateway_names
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    assert issue(client).status_code == 200
    with sessions() as db:
        db.add(models.McpGateway(slug='new', name='New', status='active'))
        db.commit()
    assert client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': ['readonly', 'new']}).status_code == 200
    with sessions() as db:
        assert _agent_gateway_names(db, db.get(models.ManagedAgent, agent['id'])) == ['readonly']
    assert client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': ['new']}).status_code == 200
    with sessions() as db:
        assert _agent_gateway_names(db, db.get(models.ManagedAgent, agent['id'])) == []


def test_existing_scope_migration_is_once_only_and_excludes_inactive_credentials(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE managed_agents (agent_id TEXT)')
        conn.exec_driver_sql('CREATE TABLE mcp_call_audits (id INTEGER, token_id INTEGER)')
        conn.exec_driver_sql('INSERT INTO mcp_call_audits VALUES (1, 1)')
        conn.exec_driver_sql("INSERT INTO managed_agents VALUES ('old-agent')")
        conn.exec_driver_sql('CREATE TABLE access_tokens (bound_agent_id TEXT, token_type TEXT, status TEXT, expires_at DATETIME, allowed_mcp_gateways_json TEXT, scopes_json TEXT)')
        for name, status, expires, token_type, scopes in [
            ('existing', 'active', None, 'agent_runtime', ['mcp:list-tools']),
            ('other', 'active', None, 'agent_runtime', ['mcp:call-tools']),
            ('disabled', 'disabled', None, 'agent_runtime', ['mcp:call-tools']),
            ('revoked', 'revoked', None, 'agent_runtime', ['mcp:call-tools']),
            ('expired', 'active', '2000-01-01', 'agent_runtime', ['mcp:call-tools']),
            ('ordinary', 'active', None, 'mcp_gateway', ['mcp:call-tools']),
            ('no-scope', 'active', None, 'agent_runtime', ['model:chat']),
        ]:
            conn.exec_driver_sql('INSERT INTO access_tokens VALUES (?, ?, ?, ?, ?, ?)', ('old-agent', token_type, status, expires, json.dumps([name]), json.dumps(scopes)))
    migrate_agent_mcp_scope(engine)
    with engine.begin() as conn:
        value = conn.exec_driver_sql('SELECT allowed_mcp_gateways_json FROM managed_agents').scalar()
        assert json.loads(value) == ['existing', 'other']
        assert conn.exec_driver_sql('SELECT bound_agent_id FROM mcp_call_audits').scalar() is None
        conn.exec_driver_sql("UPDATE managed_agents SET allowed_mcp_gateways_json = '[]'")
    migrate_agent_mcp_scope(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT allowed_mcp_gateways_json FROM managed_agents').scalar() == '[]'


def test_call_identity_survives_credential_rebinding(tmp_path, monkeypatch):
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    token = issue(client).json()
    assert rpc(client, token['token'], 'tools/call').status_code == 200
    other = client.post('/agents', json={'agent_id': 'other-agent', 'name': 'Other', 'allowed_mcp_gateways': ['readonly']}).json()
    rebound = client.put(f"/api/v1/access/tokens/{token['record']['id']}", json={'bound_agent_id': 'other-agent'})
    assert rebound.status_code == 200
    assert len(client.get(f"/agents/{agent['id']}/mcp-access").json()['recent_calls']) == 1
    assert client.get(f"/agents/{other['id']}/mcp-access").json()['recent_calls'] == []


def test_mcp_detail_respects_agent_ownership(tmp_path, monkeypatch):
    from backend import auth
    client, _, agent, _ = setup_agent(tmp_path, monkeypatch)
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=2, username='other', role='admin', hashed_password='x',
    )
    assert client.get(f"/agents/{agent['id']}/mcp-access").status_code == 404


def test_approved_call_cannot_bypass_removed_agent_grant(tmp_path, monkeypatch):
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    with sessions() as db:
        db.query(models.McpTool).filter_by(name='search').one().requires_approval = True
        db.commit()
    token = issue(client).json()
    pending = rpc(client, token['token'], 'tools/call').json()
    request_id = pending['error']['data']['approval_request_id']
    approved = client.post(f'/api/v1/mcp/approval-requests/{request_id}/approve',
                           json={'ttl_seconds': 60, 'comment': 'test'})
    assert approved.status_code == 200, approved.text
    assert 'result' in rpc(client, token['token'], 'tools/call').json()
    assert client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': []}).status_code == 200
    headers = {'Authorization': f"Bearer {token['token']}"}
    status = client.get(f'/mcp/readonly/approvals/{request_id}', headers=headers)
    assert status.status_code == 403
    assert status.json()['error_code'] == 'agent.mcp_scope_exceeded'
    denied = rpc(client, token['token'], 'tools/call')
    assert denied.status_code == 403
    with sessions() as db:
        approval = db.query(models.McpToolApproval).filter_by(request_id=request_id).one()
        assert approval.use_count == 1
        assert db.query(models.McpCallAudit).filter_by(status='success').count() == 1


def test_agent_grant_is_checked_at_both_admin_approval_entries(tmp_path, monkeypatch):
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    with sessions() as db:
        db.query(models.McpTool).filter_by(name='search').one().requires_approval = True
        db.commit()
    token = issue(client).json()
    direct_body = {'token_id': token['record']['id'], 'gateway_slug': 'readonly',
                   'tool_name': 'crm__search', 'arguments': {'query': 'sample'}, 'ttl_seconds': 60}
    assert client.post('/api/v1/mcp/approvals', json=direct_body).status_code == 200
    request_id = rpc(client, token['token'], 'tools/call').json()['error']['data']['approval_request_id']
    assert client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': []}).status_code == 200
    for path, body in [('/api/v1/mcp/approvals', direct_body),
                       (f'/api/v1/mcp/approval-requests/{request_id}/approve', {'ttl_seconds': 60})]:
        denied = client.post(path, json=body)
        assert denied.status_code == 403
        assert denied.json()['error_code'] == 'agent.mcp_scope_exceeded'
    with sessions() as db:
        assert db.query(models.McpToolApproval).filter_by(request_id=request_id).one().status == 'pending'


def test_scope_migration_rolls_back_ddl_and_can_retry(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE managed_agents (agent_id TEXT)')
        conn.exec_driver_sql("INSERT INTO managed_agents VALUES ('old-agent')")
        conn.exec_driver_sql('CREATE TABLE mcp_call_audits (id INTEGER)')
        conn.exec_driver_sql('CREATE TABLE access_tokens (bound_agent_id TEXT, token_type TEXT, status TEXT, expires_at DATETIME, allowed_mcp_gateways_json TEXT, scopes_json TEXT)')
        conn.exec_driver_sql('INSERT INTO access_tokens VALUES (?, ?, ?, ?, ?, ?)',
                             ('old-agent', 'agent_runtime', 'active', None, '["readonly"]', '["mcp:call-tools"]'))

    def fail_backfill(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('UPDATE managed_agents SET allowed_mcp_gateways_json'):
            raise RuntimeError('simulated backfill failure')

    event.listen(engine, 'before_cursor_execute', fail_backfill)
    with pytest.raises(RuntimeError, match='simulated backfill failure'):
        migrate_agent_mcp_scope(engine)
    event.remove(engine, 'before_cursor_execute', fail_backfill)
    with engine.connect() as conn:
        assert 'allowed_mcp_gateways_json' not in {r[1] for r in conn.exec_driver_sql('PRAGMA table_info(managed_agents)')}
        assert 'bound_agent_id' not in {r[1] for r in conn.exec_driver_sql('PRAGMA table_info(mcp_call_audits)')}
    # Two startup workers must serialize the once-only migration and preserve its result.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: migrate_agent_mcp_scope(engine), range(2)))
    with engine.connect() as conn:
        assert json.loads(conn.exec_driver_sql('SELECT allowed_mcp_gateways_json FROM managed_agents').scalar()) == ['readonly']


@pytest.mark.parametrize('response_format', ['json', 'sse'])
def test_agent_mcp_real_http_transport_and_revocation(tmp_path, monkeypatch, response_format):
    import socket
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    real_call_upstream = mcp_gateway._call_upstream
    client, sessions, agent, _ = setup_agent(tmp_path, monkeypatch)
    token = issue(client).json()
    requests = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((payload, dict(self.headers)))
            method = payload['method']
            if method == 'notifications/initialized':
                self.send_response(202)
                self.end_headers()
                return
            result = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 'local-test', 'version': '1'}} if method == 'initialize' else {'content': [{'type': 'text', 'text': payload['params']['arguments']['query']}]}
            body = json.dumps({'jsonrpc': '2.0', 'id': payload['id'], 'result': result})
            if response_format == 'sse':
                body = f'event: message\ndata: {body}\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if response_format == 'sse' else 'application/json')
            self.send_header('Mcp-Session-Id', 'local-session')
            self.end_headers()
            self.wfile.write(body.encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(mcp_gateway, '_call_upstream', real_call_upstream)
        monkeypatch.setattr(mcp_gateway.settings, 'MCP_ALLOW_HTTP', True)
        monkeypatch.setattr(mcp_gateway.settings, 'MCP_OUTBOUND_ALLOWLIST', '127.0.0.1/32')
        original_getaddrinfo = socket.getaddrinfo
        def local_dns(host, *args, **kwargs):
            return original_getaddrinfo('127.0.0.1' if host in ('mcp.local.test', b'mcp.local.test') else host, *args, **kwargs)
        monkeypatch.setattr(socket, 'getaddrinfo', local_dns)
        monkeypatch.setenv('NO_PROXY', 'mcp.local.test')
        with sessions() as db:
            db.query(models.McpServer).filter_by(slug='crm').one().endpoint = f'http://mcp.local.test:{server.server_port}/mcp'
            db.commit()
        result = rpc(client, token['token'], 'tools/call')
        assert result.status_code == 200
        assert 'result' in result.json(), result.text
        assert result.json()['result']['content'][0]['text'] == 'sample'
        assert [r[0]['method'] for r in requests] == ['initialize', 'notifications/initialized', 'tools/call']
        assert all(r[1]['Authorization'] == 'Bearer upstream-secret' for r in requests)
        assert requests[-1][1]['MCP-Protocol-Version'] == '2025-06-18'
        assert requests[-1][1]['Mcp-Session-Id'] == 'local-session'
        detail = client.get(f"/agents/{agent['id']}/mcp-access").json()
        assert detail['recent_calls'][0]['status'] == 'success'
        assert client.put(f"/agents/{agent['id']}", json={'allowed_mcp_gateways': []}).status_code == 200
        assert rpc(client, token['token'], 'tools/call').status_code == 403
        assert len(requests) == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
