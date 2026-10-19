from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine

from backend.request_leases import LeaseLimitExceeded, acquire_lease, release_lease
from backend.request_leases import LeaseRequest, acquire_leases, release_leases, cleanup_expired_leases
from backend.sqlite_db import Base


def _engine(tmp_path):
    bind = create_engine(f"sqlite:///{tmp_path / 'request-leases.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=bind)
    return bind


def test_sqlite_lease_is_shared_and_released(tmp_path):
    bind = _engine(tmp_path)
    lease_id = acquire_lease("access_token", 7, "request", 1, bind=bind)
    with pytest.raises(LeaseLimitExceeded):
        acquire_lease("access_token", 7, "request", 1, bind=bind)
    release_lease(lease_id, bind=bind)
    replacement = acquire_lease("access_token", 7, "request", 1, bind=bind)
    release_lease(replacement, bind=bind)


def test_expired_sqlite_lease_is_reclaimed(tmp_path):
    bind = _engine(tmp_path)
    with bind.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO request_leases
                (lease_id, subject_type, subject_id, purpose, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("expired", "access_token", "7", "request", datetime.utcnow() - timedelta(seconds=1), datetime.utcnow()),
        )
    lease_id = acquire_lease("access_token", 7, "request", 1, bind=bind)
    release_lease(lease_id, bind=bind)


def test_group_rejection_rolls_back_first_slot_and_preserves_other_lease(tmp_path):
    bind = _engine(tmp_path)
    occupied = acquire_lease('mcp_tool', 9, 'call', 1, bind=bind)
    requests = [LeaseRequest('access_token', 7, 'request', 1), LeaseRequest('mcp_tool', 9, 'call', 1)]
    with pytest.raises(LeaseLimitExceeded) as failure:
        acquire_leases(requests, bind=bind)
    assert failure.value.subject_type == 'mcp_tool'
    with bind.connect() as conn:
        assert conn.exec_driver_sql('SELECT lease_id FROM request_leases').scalars().all() == [occupied]
    release_lease(occupied, bind=bind)
    leases = acquire_leases(requests, bind=bind)
    release_leases(leases, bind=bind)
    with bind.connect() as conn:
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM request_leases').scalar_one() == 0


def test_group_limits_are_atomic_across_independent_engines(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    bind = _engine(tmp_path)
    binds = [create_engine(bind.url, connect_args={'check_same_thread': False}) for _ in range(8)]
    barrier = Barrier(len(binds))
    def compete(engine):
        barrier.wait(timeout=5)
        try:
            return acquire_leases([LeaseRequest('access_token', 7, 'request', 3),
                                   LeaseRequest('mcp_tool', 9, 'call', 2)], bind=engine)
        except LeaseLimitExceeded:
            return []
    with ThreadPoolExecutor(max_workers=len(binds)) as pool:
        results = list(pool.map(compete, binds))
    assert sum(bool(ids) for ids in results) == 2
    with bind.connect() as conn:
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM request_leases').scalar_one() == 4
    release_leases([lease for ids in results for lease in ids], bind=bind)
    for engine in binds:
        engine.dispose()


def test_expired_cleanup_is_bounded_and_not_in_live_acquisition(tmp_path):
    bind = _engine(tmp_path)
    now = datetime.utcnow()
    with bind.begin() as conn:
        conn.exec_driver_sql('INSERT INTO request_leases VALUES (?, ?, ?, ?, ?, ?)', [
            (f'expired-{i}', 'access_token', '7', 'request', now - timedelta(seconds=1), now)
            for i in range(5)])
    active = acquire_lease('access_token', 7, 'request', 1, bind=bind)
    with bind.connect() as conn:
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM request_leases').scalar_one() == 6
    assert cleanup_expired_leases(bind=bind, limit=2)
    assert cleanup_expired_leases(bind=bind, limit=2)
    assert not cleanup_expired_leases(bind=bind, limit=2)
    with bind.connect() as conn:
        assert conn.exec_driver_sql('SELECT lease_id FROM request_leases').scalars().all() == [active]
    release_lease(active, bind=bind)
