from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine

from backend.request_leases import LeaseLimitExceeded, acquire_lease, release_lease
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
