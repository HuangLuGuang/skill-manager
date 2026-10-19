"""SQLite-backed concurrency leases shared by backend workers on one database."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.engine import Engine

from .sqlite_db import engine


class LeaseLimitExceeded(RuntimeError):
    def __init__(self, message: str, *, subject_type: str | None = None):
        super().__init__(message)
        self.subject_type = subject_type


@dataclass(frozen=True)
class LeaseRequest:
    subject_type: str
    subject_id: str | int
    purpose: str
    limit: int
    ttl_seconds: int = 300


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
    return acquire_leases([LeaseRequest(subject_type, subject_id, purpose, limit, ttl_seconds)], bind=bind)[0]


def acquire_leases(requests: list[LeaseRequest], *, bind: Engine = engine) -> list[str]:
    """Acquire all limits atomically, or leave every requested slot unoccupied."""
    if not requests:
        return []
    leases = []
    connection = bind.connect()
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        now = datetime.utcnow()
        for request in requests:
            active = connection.exec_driver_sql(
                """
                SELECT COUNT(*) FROM request_leases
                WHERE subject_type = ? AND subject_id = ? AND purpose = ? AND expires_at > ?
                """,
                (request.subject_type, str(request.subject_id), request.purpose, now),
            ).scalar_one()
            if int(active) >= max(1, int(request.limit)):
                raise LeaseLimitExceeded(
                    f"{request.subject_type}:{request.subject_id}:{request.purpose}", subject_type=request.subject_type,
                )
            lease_id = uuid.uuid4().hex
            expires_at = now + timedelta(seconds=max(1, request.ttl_seconds))
            connection.exec_driver_sql(
                """
                INSERT INTO request_leases
                    (lease_id, subject_type, subject_id, purpose, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (lease_id, request.subject_type, str(request.subject_id), request.purpose, expires_at, now),
            )
            leases.append(lease_id)
        connection.commit()
        return leases
    except Exception:
        if connection.in_transaction():
            connection.rollback()
        raise
    finally:
        connection.close()


def release_lease(lease_id: str | None, *, bind: Engine = engine) -> None:
    release_leases([lease_id] if lease_id else [], bind=bind)


def release_leases(lease_ids: list[str], *, bind: Engine = engine) -> None:
    if not lease_ids:
        return
    with bind.begin() as connection:
        delete_leases(connection, lease_ids)


def delete_leases(connection, lease_ids: list[str]) -> None:
    """Release slots in a caller-owned transaction; the caller must commit."""
    if lease_ids:
        placeholders = ','.join('?' for _ in lease_ids)
        connection.exec_driver_sql(f"DELETE FROM request_leases WHERE lease_id IN ({placeholders})", tuple(lease_ids))


def cleanup_expired_leases(*, bind: Engine = engine, limit: int = 500) -> bool:
    """Bound expiry work independently of acquiring a live request slot."""
    if not 1 <= limit <= 500:
        raise ValueError('request_lease_retention_budget_invalid')
    with bind.begin() as connection:
        result = connection.exec_driver_sql(
            "DELETE FROM request_leases WHERE lease_id IN "
            "(SELECT lease_id FROM request_leases WHERE expires_at <= ? ORDER BY expires_at, lease_id LIMIT ?)",
            (datetime.utcnow(), limit),
        )
        return result.rowcount == limit
