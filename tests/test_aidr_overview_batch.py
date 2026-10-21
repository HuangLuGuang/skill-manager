"""Projection batching preserves ambiguous evidence, counters and atomic watermarks."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from backend.aidr_models import AidrHookEvent
from backend.aidr_overview import (OverviewBucket, OverviewCommandBucket, OverviewEvidence,
    OverviewOperation, OverviewWatermark, advance, reconcile_many, remove_evidence)
from tests.test_aidr_api import service


def seed(factory, count=250):
    with factory() as db:
        db.execute(AidrHookEvent.__table__.insert(), [dict(client_id='one', stream_id='a'*32,
            event_id=f'{i:032x}', source_seq=i, content_hash='b'*64, payload_json=json.dumps({
                'user_scope':'501', 'received_at':datetime.now(timezone.utc).isoformat(),
                'event':dict(agent='codex', session_id='s', turn_id='t', native_call_id=str(i),
                             tool='Bash', kind='tool.pre')})) for i in range(1, count+1)])
        db.commit()


def test_projection_batches_statements_and_rolls_back_watermark_with_counters(service, monkeypatch):
    _, factory = service
    seed(factory)
    with factory() as db:
        def fail():
            raise OSError('projection commit failed')
        monkeypatch.setattr(db, 'commit', fail)
        with pytest.raises(OSError, match='projection commit failed'):
            advance(db)
    with factory() as db:
        assert db.query(OverviewWatermark).count() == db.query(OverviewEvidence).count() == 0
        assert db.query(OverviewOperation).count() == db.query(OverviewBucket).count() == 0

    statements = []
    engine = factory.kw['bind']
    def observe(_conn, _cursor, sql, _params, _ctx, many):
        statements.append((sql, many))
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        with factory() as db:
            assert advance(db)
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert len(statements) < 60
    assert any(many and sql.startswith('INSERT INTO aidr_overview_evidence') for sql, many in statements)
    with factory() as db:
        assert db.query(OverviewEvidence).count() == db.query(OverviewOperation).count() == 250
        assert db.query(OverviewBucket).one().calls == 250
        assert db.get(OverviewWatermark, 'hooks').position == 250
        assert not advance(db)
        assert db.query(OverviewBucket).one().calls == 250


def test_bulk_reconciliation_keeps_per_call_bound_and_net_bucket_deltas(service):
    _, factory = service
    with factory() as db:
        common = dict(source='hooks', client_id='one', agent='codex', product='codex',
            session_key='s', session_id='s', at=1700000000, tool='Bash', command='command',
            command_counts_json='{"echo":2,"printf":1}')
        rows = [dict(common, record_id=i, operation_key=str(i), phase='call', outcome='unknown') for i in range(1,101)]
        rows += [dict(common, record_id=1000+i, operation_key=str(i), phase='result', outcome='failed') for i in range(1,101,2)]
        rows += [dict(common, record_id=i, operation_key='ambiguous', phase='call', outcome='unknown') for i in (2001,2002)]
        rows += [dict(common, record_id=3000+i, operation_key='noisy', phase='result' if i else 'call', outcome='failed') for i in range(1000)]
        db.execute(OverviewEvidence.__table__.insert(), rows)
        keys = [str(i) for i in range(1,101)] + ['ambiguous','noisy','']
        reconcile_many(db, keys)
        db.commit()
        assert db.query(OverviewOperation).count() == 100
        bucket = db.query(OverviewBucket).one()
        assert (bucket.calls, bucket.failures) == (100,50)
        assert {r.program:r.occurrences for r in db.query(OverviewCommandBucket)} == {'echo':200,'printf':100}
        # One call expires completely; another loses only its failed result.
        remove_evidence(db, 'hooks', [1,1003])
        reconcile_many(db, keys)
        db.commit()
        db.expire_all()
        bucket = db.query(OverviewBucket).one()
        assert (bucket.calls, bucket.failures) == (99,48)
        assert {r.program:r.occurrences for r in db.query(OverviewCommandBucket)} == {'echo':198,'printf':99}


def test_concurrent_projection_workers_advance_each_record_once(service):
    _, factory = service
    seed(factory, 100)
    def worker(_):
        with factory() as db:
            while advance(db, 25):
                pass
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(worker, range(3)))
    with factory() as db:
        assert db.query(OverviewEvidence).count() == db.query(OverviewOperation).count() == 100
        assert db.query(OverviewBucket).one().calls == 100
        assert db.get(OverviewWatermark, 'hooks').position == 100


@pytest.mark.parametrize('concurrent_change', ['expiry', 'projection'])
def test_projection_rechecks_prepared_evidence_and_watermark(service, monkeypatch, concurrent_change):
    from backend import aidr_overview
    _, factory = service
    seed(factory, 1)
    original = aidr_overview.project
    owner = threading.get_ident()
    prepared = False

    def concurrent_writer():
        with factory() as other:
            if concurrent_change == 'expiry':
                remove_evidence(other, 'hooks', [1])
                other.query(AidrHookEvent).filter_by(id=1).update(
                    {'expired_at': datetime.now(timezone.utc), 'payload_json': '{}'})
                other.commit()
            else:
                assert not advance(other)

    def project(source, row):
        nonlocal prepared
        value = original(source, row)
        if threading.get_ident() == owner and not prepared:
            prepared = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                # This writer can commit while the first worker prepares JSON.
                pool.submit(concurrent_writer).result(timeout=3)
        return value

    monkeypatch.setattr(aidr_overview, 'project', project)
    with factory() as db:
        assert advance(db) is (concurrent_change == 'projection')
        assert not advance(db)
    assert prepared
    with factory() as db:
        expected = int(concurrent_change == 'projection')
        assert db.query(OverviewEvidence).count() == db.query(OverviewOperation).count() == expected
        assert sum(row.calls for row in db.query(OverviewBucket)) == expected
        assert db.get(OverviewWatermark, 'hooks').position == 1


def test_projection_revalidation_uses_bounded_primary_key_lookup(service):
    _, factory = service
    seed(factory)
    plans = []
    engine = factory.kw['bind']
    def explain(_conn, cursor, sql, parameters, *_):
        if sql.startswith('SELECT') and 'aidr_hook_events.id IN (' in sql:
            with_cursor = cursor.connection.cursor()
            try:
                plans.append(with_cursor.execute('EXPLAIN QUERY PLAN ' + sql, parameters).fetchall())
            finally:
                with_cursor.close()
    event.listen(engine, 'before_cursor_execute', explain)
    try:
        with factory() as db:
            assert advance(db)
    finally:
        event.remove(engine, 'before_cursor_execute', explain)
    assert plans
    assert all(any('USING INTEGER PRIMARY KEY' in row[-1] for row in plan) for plan in plans)


def test_reconciliation_reads_committed_results_ambiguity_and_expiry(service):
    _, factory = service
    common = dict(source='hooks', client_id='one', agent='codex', product='codex',
                  session_key='s', session_id='s', at=1700000000, tool='Bash', command='',
                  command_counts_json='{}', phase='call', outcome='unknown')
    with factory() as db:
        db.execute(OverviewEvidence.__table__.insert(), [
            dict(common, record_id=index, operation_key=key)
            for index, key in enumerate(('a', 'b', 'c', 'd'), 1)])
        reconcile_many(db, ['a', 'b'])
        db.commit()
    with factory() as db:
        # Reconcile a different group of operations in a new transaction.
        reconcile_many(db, ['c', 'd'])
        db.commit()
        assert {row.key for row in db.query(OverviewOperation)} == {'a', 'b', 'c', 'd'}
        assert db.query(OverviewBucket).one().calls == 4
        db.execute(OverviewEvidence.__table__.insert(), [
            dict(common, record_id=5, operation_key='a', phase='result', outcome='failed'),
            dict(common, record_id=6, operation_key='b')])
        db.commit()
    with factory() as db:
        # A newly committed result and ambiguous second call change the totals.
        reconcile_many(db, ['a', 'b'])
        db.commit()
        assert {row.key for row in db.query(OverviewOperation)} == {'a', 'c', 'd'}
        bucket = db.query(OverviewBucket).one()
        assert (bucket.calls, bucket.failures) == (3, 1)
        remove_evidence(db, 'hooks', [1, 5])
        reconcile_many(db, ['a', 'b'])
        db.commit()
        db.expire_all()
        assert {row.key for row in db.query(OverviewOperation)} == {'c', 'd'}
        bucket = db.query(OverviewBucket).one()
        assert (bucket.calls, bucket.failures) == (2, 0)


def test_expiry_and_projection_cannot_leave_orphaned_counters(service):
    _, factory = service
    seed(factory, 1)
    paused, release = threading.Event(), threading.Event()
    attempted, written = threading.Event(), threading.Event()
    cleanup_thread = []
    engine = factory.kw['bind']
    def before(_conn, _cursor, sql, *_):
        if threading.get_ident() not in cleanup_thread and sql.startswith('INSERT INTO aidr_overview_watermarks'):
            attempted.set()
    def after(_conn, _cursor, sql, *_):
        if threading.get_ident() in cleanup_thread and sql.startswith('SELECT aidr_overview_evidence.operation_key') and not paused.is_set():
            paused.set()
            assert release.wait(3)
        if threading.get_ident() not in cleanup_thread and sql.startswith('INSERT INTO aidr_overview_watermarks'):
            written.set()
    def expire():
        cleanup_thread.append(threading.get_ident())
        with factory() as db:
            remove_evidence(db, 'hooks', [1])
            db.get(AidrHookEvent, 1).expired_at = datetime.now(timezone.utc)
            db.commit()
    def project():
        with factory() as db:
            advance(db)
    event.listen(engine, 'before_cursor_execute', before)
    event.listen(engine, 'after_cursor_execute', after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            cleanup = pool.submit(expire)
            try:
                assert paused.wait(2)
                projection = pool.submit(project)
                assert attempted.wait(2)
                assert not written.wait(.3)
            finally:
                release.set()
            cleanup.result()
            projection.result()
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', before)
        event.remove(engine, 'after_cursor_execute', after)
    with factory() as db:
        assert db.query(OverviewEvidence).count() == db.query(OverviewOperation).count() == 0
        assert db.query(OverviewBucket).count() == 0
