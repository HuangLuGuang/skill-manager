"""SQLite-backed concurrency leases shared by backend workers on one database."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.engine import Engine

from .sqlite_db import engine


class LeaseLimitExceeded(RuntimeError):
    pass


def acquire_lease(
    subject_type: str,
    subject_id: str | int,
    purpose: str,
    limit: int,
    *,
    ttl_seconds: int = 300,
    bind: Engine = engine,
) -> str:
    """Atomically acquire one lease using SQLite's write lock."""
    lease_id = uuid.uuid4().hex
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=max(1, ttl_seconds))
    connection = bind.connect()
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        connection.exec_driver_sql("DELETE FROM request_leases WHERE expires_at <= ?", (now,))
        active = connection.exec_driver_sql(
            """
            SELECT COUNT(*) FROM request_leases
            WHERE subject_type = ? AND subject_id = ? AND purpose = ? AND expires_at > ?
            """,
            (subject_type, str(subject_id), purpose, now),
        ).scalar_one()
        if int(active) >= max(1, int(limit)):
            connection.rollback()
            raise LeaseLimitExceeded(f"{subject_type}:{subject_id}:{purpose}")
        connection.exec_driver_sql(
            """
            INSERT INTO request_leases
                (lease_id, subject_type, subject_id, purpose, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (lease_id, subject_type, str(subject_id), purpose, expires_at, now),
        )
        connection.commit()
        return lease_id
    except Exception:
        if connection.in_transaction():
            connection.rollback()
        raise
    finally:
        connection.close()


def release_lease(lease_id: str | None, *, bind: Engine = engine) -> None:
    if not lease_id:
        return
    with bind.begin() as connection:
        connection.exec_driver_sql("DELETE FROM request_leases WHERE lease_id = ?", (lease_id,))
