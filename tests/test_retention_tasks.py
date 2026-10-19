"""Expiry access boundaries, bounded deletion, and responsive maintenance scheduling."""
import asyncio
from datetime import datetime, timedelta
from threading import Event, get_ident

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend import models
from backend.routers import llm_gateway
from backend.services import retention
from backend.services.pipeline_trace_retention import cleanup_expired as cleanup_pipeline
from backend.services.runtime_traces import cleanup_expired as cleanup_runtime
from backend.sqlite_db import Base


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retention.db'}")

    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def trace(request_id, stage, expiry):
    return models.LlmPipelineTrace(request_id=request_id, stage=stage, tenant_id='tenant',
        conversation_id='conversation', model='test', payload_json='{"secret":"retained body"}', expires_at=expiry)


def test_empty_retention_does_not_start_write_transaction(db):
    statements = []
    engine = db.get_bind()
    def observe(_conn, _cursor, sql, *_):
        statements.append(sql)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        assert cleanup_pipeline(db) == 0
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert statements and all(sql.lstrip().startswith('SELECT') for sql in statements)


def test_retention_rechecks_expiry_after_selection(db):
    now = datetime.utcnow()
    db.add(trace('renewed', 'meta', now))
    db.commit()
    engine = db.get_bind()
    def renew(conn, _cursor, sql, *_):
        if sql.startswith('DELETE FROM llm_pipeline_traces'):
            conn.exec_driver_sql('UPDATE llm_pipeline_traces SET expires_at = ?', (now + timedelta(days=1),))
    event.listen(engine, 'before_cursor_execute', renew)
    try:
        assert cleanup_pipeline(db, now=now) == 0
    finally:
        event.remove(engine, 'before_cursor_execute', renew)
    assert db.query(models.LlmPipelineTrace).count() == 1


def test_pipeline_expiry_hides_bodies_before_bounded_deletion(db, monkeypatch):
    now = datetime.utcnow()
    monkeypatch.setattr(llm_gateway, '_now', lambda: now)
    db.add_all([trace('expired', stage, now) for stage in ['meta', 'original', 'compressed']])
    db.add_all([trace('active', 'meta', now + timedelta(days=1)), trace('active', 'compressed', now)])
    metric = models.LlmUsageMetric(request_id='expired', tenant_id='tenant', conversation_id='conversation', model='test')
    db.add(metric)
    db.add(models.LlmRequestAudit(request_id='expired', tenant_id='tenant', conversation_id='conversation',
        user_ref='test', model='test', traffic_type='pii_checked', compression_enabled=True))
    db.commit()
    listed = asyncio.run(llm_gateway.list_traces(db=db, current_user=None))
    assert listed['total'] == 1 and listed['traces'][0]['request_id'] == 'active'
    detail = asyncio.run(llm_gateway.get_trace_detail('active', db=db, current_user=None))
    assert 'compressed' not in detail['stages']
    with pytest.raises(HTTPException) as error:
        asyncio.run(llm_gateway.get_trace_detail('expired', db=db, current_user=None))
    assert error.value.status_code == 404
    diagnostics = asyncio.run(llm_gateway.get_compression_diagnostics(db=db, current_user=None))
    assert diagnostics['recent'][0]['trace_compressed_stage'] is None
    assert cleanup_pipeline(db, now=now, limit=2) == 2
    assert db.query(models.LlmPipelineTrace).count() == 3
    assert cleanup_pipeline(db, now=now, limit=2) == 2
    assert cleanup_pipeline(db, now=now, limit=2) == 0
    assert db.query(models.LlmPipelineTrace).one().request_id == 'active'
    assert db.query(models.LlmUsageMetric).one().request_id == 'expired'
    assert db.query(models.LlmRequestAudit).one().request_id == 'expired'


def test_runtime_large_session_drains_children_before_parent_with_foreign_keys(db):
    now = datetime.utcnow()
    for name, expiry in [('old', now), ('live', now + timedelta(days=1))]:
        db.add(models.RuntimeTraceSession(trace_id=name, tenant_id='tenant', session_id=name, expires_at=expiry))
    db.add(models.GatewaySessionScope(scope_id='scope'))
    db.flush()
    db.add(models.GatewaySessionGroup(trace_id='old', scope_id='scope', method='test', source='test'))
    db.flush()
    for i in range(7):
        db.add(models.GatewaySessionRequest(request_id=f'request-{i}', trace_id='old', scope_id='scope',
            history_digest='digest', message_count=1, request_index=i, match_reason='test'))
    db.flush()
    for i in range(7):
        for kind in ['input', 'output']:
            db.add(models.GatewaySessionFingerprint(request_id=f'request-{i}', kind=kind, scope_id='scope', digest='digest', message_count=1))
        db.add(models.RuntimeTraceEvent(trace_id='old', event_id=f'event-{i}', seq=i,
            content_fingerprint='digest', schema_version='runtime-trace@1', event_time=now,
            tenant_id='tenant', session_id='old', source='model_gateway', type='model.request'))
        db.add(models.RuntimeTracePayload(trace_id='old', event_id=f'event-{i}', payload_id=f'payload-{i}',
            raw_payload_encrypted='body', raw_sha256='digest', expires_at=now))
        db.add(models.RuntimeTraceExport(trace_id='old', export_id=f'export-{i}', requested_by='admin',
            redaction_level='redacted', content_encrypted='body', sha256='digest', size_bytes=4,
            expires_at=now + timedelta(days=1)))
    db.add(models.RuntimeTracePayload(trace_id='live', event_id='live', payload_id='live',
        raw_payload_encrypted='live body', raw_sha256='digest', expires_at=now + timedelta(days=1)))
    db.commit()
    previous_fingerprints = 14
    for pass_number in range(10):
        result = cleanup_runtime(db, now=now, limit=2)
        assert all(result[key] <= 2 for key in ('events', 'payloads', 'exports', 'batches', 'authorizations', 'traces'))
        remaining = db.query(models.GatewaySessionFingerprint).count()
        assert previous_fingerprints - remaining <= 2
        previous_fingerprints = remaining
        if pass_number == 0:
            assert result['traces'] == 0 and result['more']
            assert db.query(models.RuntimeTraceSession).count() == 2
        if not result['more']:
            break
    else:
        pytest.fail('retention backlog did not drain')
    assert db.query(models.RuntimeTraceSession).one().trace_id == 'live'
    assert db.query(models.RuntimeTracePayload).one().raw_payload_encrypted == 'live body'
    for model in (models.RuntimeTraceEvent, models.RuntimeTraceExport, models.GatewaySessionRequest,
                  models.GatewaySessionFingerprint, models.GatewaySessionGroup, models.GatewaySessionScope):
        assert db.query(model).count() == 0


def test_cleanup_runs_off_event_loop_and_is_cancellable():
    async def scenario():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = Event()
        finished = Event()
        thread_ids = []

        def cleanup():
            thread_ids.append(get_ident())
            loop.call_soon_threadsafe(started.set)
            try:
                release.wait(2)
                return False
            finally:
                finished.set()

        task = asyncio.create_task(retention.retention_loop(cleanup, 'test'))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            assert not finished.is_set()
            assert len(thread_ids) == 1 and thread_ids[0] != get_ident()
        finally:
            release.set()
            await asyncio.to_thread(finished.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())


def test_backlog_retries_quickly_idle_and_failure_back_off(monkeypatch, caplog):
    results = iter([True, False, RuntimeError('sensitive body')])
    delays = []

    def cleanup():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(retention.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(retention.retention_loop(cleanup, 'test'))
    assert delays == [0.25, 60, 60]
    assert 'RuntimeError' in caplog.text and 'sensitive body' not in caplog.text


def test_async_retention_can_yield_between_database_phases(monkeypatch):
    from backend.services.gateway_db import run_sync
    completed = []

    async def cleanup():
        await run_sync(completed.append, 'first')
        await run_sync(completed.append, 'second')
        return False

    async def stop(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(retention.asyncio, 'sleep', stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(retention.retention_loop(cleanup, 'test'))
    assert completed == ['first', 'second']
