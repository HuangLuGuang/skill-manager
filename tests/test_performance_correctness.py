"""Correctness at retention and gateway connection-release boundaries."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy import event as sql_event

from backend import models
from backend.aidr_retention import expire_once
from tests.test_aidr_api import service
from tests.test_aidr_content import configure
from tests.test_aidr_operations import event, upload, operations
from tests.test_ai_infra_guard_mcp_adapter import p3_api, _configured_gateway, _claim
from tests.test_mcp_scan_execution import add_model


def test_operation_expiry_checks_use_selected_primary_keys(service):
    _, factory = service
    now = datetime.utcnow()
    with factory() as db:
        db.add_all([models.AidrOperation(client_id='one', operation_key=f'{i:064x}', agent='codex',
            session_id='session', tool='exec', result_status='unknown', latest_at='2026-09-24T00:00:00Z',
            payload_json='{}', received_at=now-timedelta(days=8)) for i in range(501)])
        db.commit()
    plans = []
    engine = factory.kw['bind']

    def explain(_conn, cursor, sql, parameters, *_):
        if sql.startswith('UPDATE aidr_operations '):
            probe = cursor.connection.cursor()
            try:
                plans.append(probe.execute('EXPLAIN QUERY PLAN ' + sql, parameters).fetchall())
            finally:
                probe.close()

    sql_event.listen(engine, 'before_cursor_execute', explain)
    try:
        with factory() as db:
            assert expire_once(db, now)['aidr_operations'] == 500
            assert db.query(models.AidrOperation).filter(models.AidrOperation.expired_at.is_(None)).count() == 1
    finally:
        sql_event.remove(engine, 'before_cursor_execute', explain)
    assert plans
    # Rechecking eligibility must not turn the bounded PK write into an expiry
    # range scan over old operations outside this batch.
    assert all(any('SEARCH aidr_operations USING INTEGER PRIMARY KEY' in row[-1] for row in plan) for plan in plans)


def test_full_retention_selection_keeps_busy_retry_when_candidates_are_refreshed(service, monkeypatch):
    from backend import aidr_retention, sqlite_db
    _, factory = service
    monkeypatch.setattr(sqlite_db, 'SessionLocal', factory)
    # The full selection was concurrently refreshed, so no row was expired;
    # candidates beyond that selection still require the short catch-up interval.
    monkeypatch.setattr(aidr_retention, '_expire_batches',
                        lambda *a, **k: iter([('aidr_operations', 0, True)]))
    assert asyncio.run(aidr_retention.cleanup_once()) is True


@pytest.mark.parametrize('background', [False, True])
def test_late_result_acknowledged_between_retention_selection_and_update(service, monkeypatch, background):
    client, factory = service
    configure(factory, lifecycle={'enabled': True, 'retention_days': 1})
    call, result = event('tool_call'), event('tool_result')
    assert upload(client, call).status_code == 200
    now = datetime.utcnow()
    engine = factory.kw['bind']
    with engine.begin() as conn:
        conn.exec_driver_sql('PRAGMA journal_mode=WAL')
    with factory() as db:
        for model in (models.AidrEvent, models.AidrOperation):
            db.query(model).update({'received_at': now - timedelta(days=2)})
        db.commit()

    selected = False
    fired = False

    def select_hook(_conn, _cursor, sql, *_):
        nonlocal selected
        if sql.startswith('SELECT') and 'FROM aidr_operations' in sql and 'julianday' in sql:
            selected = True

    sql_event.listen(engine, 'after_cursor_execute', select_hook)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor, factory() as db:
            original = db.flush

            def flush(*args, **kwargs):
                nonlocal fired
                if selected and not fired:
                    fired = True
                    response = executor.submit(upload, client, result).result(timeout=5)
                    assert response.status_code == 200, response.text
                    assert response.json()['durable'] is True
                return original(*args, **kwargs)

            monkeypatch.setattr(db, 'flush', flush)
            if background:
                from backend import aidr_retention, sqlite_db
                monkeypatch.setattr(sqlite_db, 'SessionLocal', lambda: db)
                assert asyncio.run(aidr_retention.cleanup_once()) is False
            else:
                counts = expire_once(db, now)
                assert counts['aidr_operations'] == 0
    finally:
        sql_event.remove(engine, 'after_cursor_execute', select_hook)
    assert fired
    with factory() as db:
        op = db.query(models.AidrOperation).one()
        assert op.expired_at is None
        assert json.loads(op.payload_json)['result'] is not None
        assert db.query(models.AidrEvent).filter(models.AidrEvent.expired_at.is_(None)).count() == 1
    # A retransmission remains idempotent for both the view and expired raw data.
    before = operations(client)['items']
    assert upload(client, call, result).status_code == 200
    rows = operations(client)['items']
    assert len(rows) == 1 and rows == before
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 2
        assert db.query(models.AidrEvent).filter(models.AidrEvent.expired_at.is_not(None)).one().payload_json == '{}'


def test_scan_gateway_rejection_preserves_error_and_finalizes_call(p3_api, monkeypatch):
    from backend.routers import security_scans
    from backend import security_scan_controls
    client, factory, upstream = p3_api
    add_model(factory)
    gateway = _configured_gateway(client, factory)
    with factory() as db:
        tool = db.query(models.McpTool).filter_by(name='lookup_customer').one()
        tool.access_mode = 'read'
        tool.requires_approval = False
        tool.risk_level = 'low'
        name = tool.exposed_name
        db.commit()
    monkeypatch.setattr(security_scans, 'resolve_target_endpoint', lambda *a, **k: ['93.184.216.34'])
    monkeypatch.setattr(security_scan_controls, 'resolve_target_endpoint', lambda *a, **k: ['93.184.216.34'])
    target = client.post('/api/v1/agent-security/targets', json={
        'name': 'Live MCP', 'target_type': 'mcp_gateway',
        'endpoint_url': 'mcp-gateway://' + gateway['slug'], 'config': {'gateway_id': gateway['id']}}).json()
    policy = client.post('/api/v1/agent-security/policies', json={'name': 'dynamic-audit'}).json()
    created = client.post('/api/v1/agent-security/tasks', json={
        'target_id': target['target_id'], 'policy_id': policy['policy_id'], 'scan_kind': 'mcp_risk_scan',
        'mcp_mode': 'dynamic', 'mcp_route': 'server', 'mcp_tools': [name], 'mcp_call_limit': 2,
        'evaluation_model': 'mcp-eval', 'idempotency_key': 'gateway-error'})
    assert created.status_code == 200, created.text
    _, claim = _claim(client)
    with factory() as db:
        db.get(models.McpGateway, gateway['id']).status = 'disabled'
        db.commit()
    path = '/api/v1/agent-security/worker/tasks/' + claim['task']['task_id'] + '/mcp'
    body = {'lease_token': claim['lease_token'], 'method': 'tools/call', 'tool_name': name,
            'call_id': 'rejected-call-001', 'arguments': {'customer_id': 'customer-1'}}
    response = client.post(path, json=body)
    assert response.status_code == 404, response.text
    with factory() as db:
        assert db.query(models.SecurityMcpScanCall).one().status == 'failed'
        assert db.query(models.RequestLease).count() == 0
    assert client.post(path, json=body).status_code == 409
    assert upstream.tool_calls == 0
    with factory() as db:
        assert db.query(models.SecurityMcpScanCall).count() == 1
