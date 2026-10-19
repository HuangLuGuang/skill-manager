"""Regression coverage for pool starvation and lease cleanup at network boundaries."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import event, text
from sqlalchemy.pool import QueuePool

from backend import models, schemas
from backend.routers import llm_gateway, mcp_gateway
from backend.runtime_trace_schemas import RuntimeTraceInternalEvent
from backend.services import runtime_traces
from backend.services.gateway_db import run_sync
from tests.test_llm_gateway import _client as llm_client
from tests.test_mcp_gateway import _client as mcp_client
from tests.test_mcp_gateway import _configured_gateway, _gateway_token


@pytest.mark.parametrize('failure', [None, 'trace', 'session', 'commit'])
def test_model_completion_atomic_trace_and_lease_with_audit_isolation(tmp_path, monkeypatch, failure):
    client, token, factory = llm_client(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_gateway.settings, 'RUNTIME_TRACE_ENABLED', True)
    def fail(*_, **__):
        raise OSError('synthetic optional trace failure')
    if failure == 'trace':
        monkeypatch.setattr(runtime_traces, 'ingest_batch', fail)
    elif failure == 'session':
        monkeypatch.setattr(llm_gateway.gateway_sessions, 'finish', fail)
    engine = factory.kw['bind']
    final_commits = []
    deleted = set()
    def statement(conn, _cursor, sql, *_):
        if sql.startswith('DELETE FROM request_leases'):
            deleted.add(conn)
    def commit(conn):
        if conn in deleted:
            deleted.discard(conn)
            # Successful completion keeps trace writes and release in one commit.
            count = conn.exec_driver_sql('SELECT count(*) FROM runtime_trace_events').scalar_one()
            final_commits.append(count)
            if failure == 'commit' and count:
                raise OSError('synthetic optional trace failure')
    event.listen(engine, 'before_cursor_execute', statement)
    event.listen(engine, 'commit', commit)
    try:
        result = client.post('/v1/chat/completions', headers={'Authorization': f'Bearer {token}'},
                             json={'model': 'mock-model', 'messages': [{'role': 'user', 'content': 'jane@example.com'}]})
        assert result.status_code == 200, result.text
    finally:
        event.remove(engine, 'before_cursor_execute', statement)
        event.remove(engine, 'commit', commit)
    with factory() as db:
        assert db.query(models.LlmRequestAudit).one().status == 'success'
        assert db.query(models.LlmUsageMetric).count() == 1
        assert db.query(models.LlmPipelineTrace).count() > 0
        assert db.query(models.RequestLease).count() == 0
        assert db.query(models.RuntimeTraceEvent).count() == (0 if failure else 2)
        request = db.query(models.GatewaySessionRequest).one()
        assert request.status == ('running' if failure == 'session' else 'completed')
        if failure != 'session':
            assert request.completed_at is not None
            kinds = {row.kind for row in db.query(models.GatewaySessionFingerprint).filter_by(request_id=request.request_id)}
            assert {'answered_history_v1', 'title_exchange_v1'} <= kinds
            assert llm_gateway.gateway_sessions.summaries(db, [request.trace_id])[request.trace_id]['status'] == 'completed'
    assert final_commits == ([2] if failure is None else [2, 0] if failure == 'commit' else [0])


def test_mcp_exchange_reuses_tcp_and_closes_client_on_protocol_error(monkeypatch):
    requests, clients, dns_threads = [], [], []
    reject = False

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            method = body['method']
            requests.append((self.client_address[1], method, self.headers.get('Mcp-Session-Id')))
            result = {'protocolVersion': 'unsupported' if reject else '2025-11-25'} if method == 'initialize' else {}
            raw = json.dumps({'jsonrpc': '2.0', 'id': body.get('id'), 'result': result}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Mcp-Session-Id', str(self.client_address[1]))
            self.end_headers()
            self.wfile.write(raw)

    real_client = httpx.AsyncClient
    def client(**kwargs):
        instance = real_client(**kwargs)
        clients.append(instance)
        return instance

    def validate(_):
        dns_threads.append(threading.get_ident())
        return ['127.0.0.1']

    monkeypatch.setenv('NO_PROXY', '*')
    monkeypatch.setenv('no_proxy', '*')
    monkeypatch.setattr(mcp_gateway.httpx, 'AsyncClient', client)
    monkeypatch.setattr(mcp_gateway, '_validate_resolved_endpoint', validate)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = models.McpServer(endpoint=f'http://127.0.0.1:{server.server_port}/mcp', timeout_seconds=2)

    async def scenario():
        nonlocal reject
        for _ in range(2):
            await mcp_gateway._call_upstream(endpoint, 'tools/list', {})
        reject = True
        with pytest.raises(ValueError, match='协议版本'):
            await mcp_gateway._call_upstream(endpoint, 'tools/list', {})
        assert all(c.is_closed for c in clients)
        assert len(clients) == 3
        assert threading.get_ident() not in dns_threads

    try:
        asyncio.run(scenario())
        for offset in [0, 3]:
            exchange = requests[offset:offset + 3]
            port = exchange[0][0]
            assert [r[0] for r in exchange] == [port] * 3
            assert [r[1] for r in exchange] == ['initialize', 'notifications/initialized', 'tools/list']
            assert [r[2] for r in exchange] == [None, str(port), str(port)]
        assert len(set(r[0] for r in requests)) == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def one_connection(factory):
    engine = factory.kw["bind"]
    creator = engine.pool._creator
    engine.dispose()
    engine.pool = QueuePool(creator, pool_size=1, max_overflow=0, timeout=.5)
    return engine


@pytest.mark.parametrize("gateway", ["model", "mcp"])
def test_single_connection_pool_wait_and_upstream_do_not_block_loop(tmp_path, monkeypatch, gateway):
    if gateway == "model":
        client, token, factory = llm_client(tmp_path, monkeypatch)
        path = "/v1/chat/completions"
        body = {"model": "mock-model", "messages": [{"role": "user", "content": "jane@example.com"}]}
        module = llm_gateway
    else:
        client, factory = mcp_client(tmp_path, monkeypatch)
        _configured_gateway(client)
        token = _gateway_token(client)
        path = "/mcp/readonly"
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "crm__search", "arguments": {"query": "alice"}}}
        module = mcp_gateway
    original = module._call_upstream
    engine = one_connection(factory)
    upstream_checks = []

    async def upstream(*args):
        assert engine.pool.checkedout() == 0
        # The real provider-configuration lookup must also return its connection.
        if gateway == "model":
            from backend.services.gateway_db import run_db
            await run_db(args[0], llm_gateway._prepare_upstream, *args)
            assert engine.pool.checkedout() == 0
        upstream_checks.append(True)
        await asyncio.sleep(.03)
        return await original(*args)

    monkeypatch.setattr(module, "_call_upstream", upstream)

    async def scenario():
        loop_thread = threading.get_ident()
        held = engine.connect()
        checkouts = []

        def checkout(*_):
            checkouts.append(threading.get_ident())

        event.listen(engine, "checkout", checkout)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver") as transport:
                task = asyncio.create_task(transport.post(path, json=body, headers={"Authorization": f"Bearer {token}"}))
                # Only this loop can release the occupied pool. A synchronous
                # checkout on it would hit pool_timeout before this sleep ends.
                await asyncio.sleep(.05)
                held.close()
                response = await asyncio.wait_for(task, 3)
                assert response.status_code == 200, response.text
                assert "error" not in response.json()
            assert checkouts and loop_thread not in checkouts
            assert engine.pool.checkedout() == 0
        finally:
            held.close()
            event.remove(engine, "checkout", checkout)

    asyncio.run(scenario())
    assert upstream_checks
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM request_leases")).scalar_one() == 0


def test_cancelled_lease_acquisition_finishes_before_release(tmp_path, monkeypatch):
    _, token, factory = llm_client(tmp_path, monkeypatch)
    engine = one_connection(factory)
    with factory() as db:
        key = db.query(models.LlmApiKey).one()
    acquired = threading.Event()
    unblock = threading.Event()
    original = llm_gateway.acquire_lease

    def acquire(*args, **kwargs):
        lease = original(*args, **kwargs)
        acquired.set()
        assert unblock.wait(2)
        return lease

    monkeypatch.setattr(llm_gateway, "acquire_lease", acquire)

    async def scenario():
        async def request():
            try:
                await run_sync(llm_gateway._acquire_key_slot, key, bind=engine)
            finally:
                await run_sync(llm_gateway._release_key_slot, key)
        task = asyncio.create_task(request())
        while not acquired.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        await asyncio.sleep(.01)
        assert not task.done()
        unblock.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM request_leases")).scalar_one() == 0


def test_stream_releases_connection_but_holds_lease_until_close(tmp_path, monkeypatch):
    _, token, factory = llm_client(tmp_path, monkeypatch, max_concurrent_requests=1)
    engine = one_connection(factory)
    real_client = httpx.AsyncClient
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"index":0,"delta":{"content":"hello"}}]}\n\n'
            await asyncio.sleep(10)

        async def aclose(self):
            closed.append(True)

    def upstream(request):
        assert engine.pool.checkedout() == 0
        return httpx.Response(200, stream=Stream())

    monkeypatch.setattr(llm_gateway.httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(upstream)))
    payload = schemas.ChatCompletionRequest(model="mock-model", stream=True,
        messages=[{"role": "user", "content": "jane@example.com"}])

    async def call(db):
        request = Request({"type": "http", "method": "POST", "path": "/v1/chat/completions",
                           "headers": [], "client": ("127.0.0.1", 1234)})
        request._body = payload.model_dump_json().encode()
        return await llm_gateway._chat_completions_impl(payload, request, Response(), f"Bearer {token}", db)

    async def scenario():
        with factory() as db:
            response = await call(db)
            await anext(response.body_iterator)
            assert engine.pool.checkedout() == 0
            with factory() as second:
                with pytest.raises(HTTPException) as error:
                    await call(second)
                assert error.value.status_code == 429
            await response.body_iterator.aclose()
            assert closed
            with engine.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM request_leases")).scalar_one() == 0
            with factory() as second:
                replacement = await call(second)
                await anext(replacement.body_iterator)
                await replacement.body_iterator.aclose()
        assert engine.pool.checkedout() == 0

    asyncio.run(scenario())


def test_trace_publisher_waiting_for_ingest_does_not_hold_sqlite_writer(tmp_path, monkeypatch):
    _, _, factory = llm_client(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime_traces.settings, "RUNTIME_TRACE_ENABLED", True)
    flushed = threading.Event()
    started = threading.Event()
    original = runtime_traces.create_trace

    def create(*args, **kwargs):
        trace = original(*args, **kwargs)
        flushed.set()
        return trace

    monkeypatch.setattr(runtime_traces, "create_trace", create)

    def publish():
        with factory() as db:
            started.set()
            return runtime_traces.publish_events_best_effort(db, [RuntimeTraceInternalEvent(
                tenant_id="test", session_id="mcp-call", source="mcp_gateway", type="mcp.result", call_id="call-1",
                payload={"result": "ok"},
            )])

    with ThreadPoolExecutor(max_workers=1) as executor:
        with factory() as first:
            first.execute(text("PRAGMA busy_timeout=200"))
            with runtime_traces.ingest_transaction(first):
                future = executor.submit(publish)
                assert started.wait(1)
                flushed.wait(.15)
                # A model publisher already holding the ingest lock must still
                # be able to write while another publisher waits for that lock.
                first.execute(text("UPDATE llm_api_keys SET name='updated'"))
        assert future.result(timeout=3)


def test_cancelled_mcp_call_releases_both_leases_and_records_interruption(tmp_path, monkeypatch):
    client, factory = mcp_client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)
    engine = one_connection(factory)

    async def scenario():
        started = asyncio.Event()

        async def upstream(*_):
            assert engine.pool.checkedout() == 0
            started.set()
            await asyncio.sleep(10)

        monkeypatch.setattr(mcp_gateway, "_call_upstream", upstream)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver") as transport:
            task = asyncio.create_task(transport.post("/mcp/readonly",
                headers={"Authorization": f"Bearer {token}"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "crm__search", "arguments": {"query": "alice"}}}))
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    assert engine.pool.checkedout() == 0
    with factory() as db:
        assert db.execute(text("SELECT count(*) FROM request_leases")).scalar_one() == 0
        audit = db.query(models.McpCallAudit).one()
        assert audit.status == "error"
        assert audit.error == "gateway.request_interrupted"


def test_cancel_during_mcp_group_acquisition_releases_committed_slots(tmp_path, monkeypatch):
    client, factory = mcp_client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)
    entered, unblock = threading.Event(), threading.Event()
    acquire = mcp_gateway.acquire_leases

    def delayed_acquire(*args, **kwargs):
        leases = acquire(*args, **kwargs)
        entered.set()
        assert unblock.wait(3)
        return leases

    monkeypatch.setattr(mcp_gateway, 'acquire_leases', delayed_acquire)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url='http://testserver') as transport:
            task = asyncio.create_task(transport.post('/mcp/readonly',
                headers={'Authorization': f'Bearer {token}'},
                json={'jsonrpc':'2.0', 'id':1, 'method':'tools/call',
                      'params':{'name':'crm__search', 'arguments':{'query':'alice'}}}))
            for _ in range(3000):
                if entered.is_set():
                    break
                await asyncio.sleep(.001)
            assert entered.is_set()
            task.cancel()
            unblock.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    with factory() as db:
        assert db.query(models.RequestLease).count() == 0
        assert db.query(models.McpCallAudit).one().error == 'gateway.request_interrupted'


def test_mcp_audit_commit_failure_still_releases_group(tmp_path, monkeypatch):
    client, factory = mcp_client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)
    def before_commit(db):
        if any(isinstance(row, models.McpCallAudit) and row.status == 'success' for row in db.new | db.dirty):
            raise OSError('simulated audit commit failure')
    async def upstream(*_):
        return {'jsonrpc':'2.0', 'id':1, 'result':{'content':[]}}
    monkeypatch.setattr(mcp_gateway, '_call_upstream', upstream)
    event.listen(factory.class_, 'before_commit', before_commit)
    try:
        with pytest.raises(OSError, match='audit commit failure'):
            client.post('/mcp/readonly', headers={'Authorization':f'Bearer {token}'},
                json={'jsonrpc':'2.0','id':1,'method':'tools/call',
                      'params':{'name':'crm__search','arguments':{'query':'alice'}}})
    finally:
        event.remove(factory.class_, 'before_commit', before_commit)
    with factory() as db:
        assert db.query(models.RequestLease).count() == 0


@pytest.mark.parametrize('limited', ['access_token', 'mcp_tool'])
def test_mcp_group_limit_keeps_existing_error_contract(tmp_path, monkeypatch, limited):
    from backend.request_leases import acquire_lease, release_lease

    client, factory = mcp_client(tmp_path, monkeypatch)
    _configured_gateway(client)
    credential = _gateway_token(client)
    with factory() as db:
        token = db.query(models.AccessToken).one()
        tool = db.query(models.McpTool).filter_by(name='search').one()
        token.max_concurrent_requests = tool.max_concurrent = 1
        subject_id = token.id if limited == 'access_token' else tool.id
        db.commit()
    bind = factory.kw['bind']
    occupied = acquire_lease(limited, subject_id, 'request' if limited == 'access_token' else 'call', 1, bind=bind)
    async def unexpected(*_):
        pytest.fail('A rejected acquisition must not call upstream')
    monkeypatch.setattr(mcp_gateway, '_call_upstream', unexpected)
    try:
        result = client.post('/mcp/readonly', headers={'Authorization':f'Bearer {credential}'},
            json={'jsonrpc':'2.0','id':1,'method':'tools/call',
                  'params':{'name':'crm__search','arguments':{'query':'alice'}}})
        if limited == 'access_token':
            assert result.status_code == 429
            assert result.json()['error_code'] == 'credential.concurrency_limit'
        else:
            assert result.status_code == 200
            assert result.json()['error']['code'] == -32004
        with factory() as db:
            assert [row.lease_id for row in db.query(models.RequestLease)] == [occupied]
    finally:
        release_lease(occupied, bind=bind)


def test_cancel_during_trace_preparation_records_interruption(tmp_path, monkeypatch):
    _, token, factory = llm_client(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_gateway.settings, "RUNTIME_TRACE_ENABLED", True)
    entered, unblock = threading.Event(), threading.Event()
    original = llm_gateway.gateway_sessions.associate

    def associate(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert unblock.wait(3)
        return result

    monkeypatch.setattr(llm_gateway.gateway_sessions, "associate", associate)

    async def scenario():
        payload = schemas.ChatCompletionRequest(model="mock-model",
            messages=[{"role": "user", "content": "jane@example.com"}])
        request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
        request._body = payload.model_dump_json().encode()
        with factory() as db:
            task = asyncio.create_task(llm_gateway._chat_completions_impl(
                payload, request, Response(), f"Bearer {token}", db))
            while not entered.is_set():
                await asyncio.sleep(.001)
            task.cancel()
            unblock.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    with factory() as db:
        assert db.query(models.GatewaySessionRequest).one().status == "error"
        assert db.execute(text("SELECT count(*) FROM request_leases")).scalar_one() == 0


def test_rolled_back_credential_is_loaded_before_detaching(tmp_path, monkeypatch):
    from sqlalchemy import inspect

    from backend.services.gateway_db import run_db

    _, _, factory = llm_client(tmp_path, monkeypatch)
    with factory() as db:
        def authenticate():
            key = db.query(models.LlmApiKey).one()
            db.rollback()
            assert inspect(key).expired_attributes
            return key
        key = asyncio.run(run_db(db, authenticate))
        assert inspect(key).detached
        assert not inspect(key).expired_attributes
        assert key.name == "customer-key"
        assert factory.kw["bind"].pool.checkedout() == 0
