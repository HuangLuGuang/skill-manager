"""
Prompt registry — modularized SQLite storage for PromptEntry records.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from .prompt_models import (
    PromptAuditEvent,
    PromptEntry,
    PromptReviewRequest,
    PromptStatus,
)

if TYPE_CHECKING:
    from .registry import Registry

logger = logging.getLogger(__name__)


class PromptRegistry:
    """Handles prompt-specific database operations."""

    def __init__(self, parent: Registry):
        self.parent = parent

    def _upsert_prompt(self, conn: sqlite3.Connection, entry: PromptEntry) -> None:
        payload = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, default=str)
        conn.execute(
            """
            INSERT INTO prompt_registry (
                prompt_id, name, agent_id, status, risk_level, submitted_at, updated_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(prompt_id) DO UPDATE SET
                name=excluded.name,
                agent_id=excluded.agent_id,
                status=excluded.status,
                risk_level=excluded.risk_level,
                submitted_at=excluded.submitted_at,
                updated_at=excluded.updated_at,
                payload=excluded.payload
            """,
            (
                entry.prompt_id,
                entry.name,
                entry.agent_id,
                entry.status.value,
                entry.risk_level.value if entry.risk_level else None,
                entry.submitted_at.isoformat(),
                datetime.now(timezone.utc).isoformat(),
                payload,
            ),
        )

    def _prompt_from_row(self, row: sqlite3.Row) -> PromptEntry:
        return PromptEntry.model_validate(json.loads(row["payload"]))

    def add(self, entry: PromptEntry) -> None:
        with self.parent._lock, self.parent._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM prompt_registry WHERE prompt_id = ?",
                (entry.prompt_id,),
            ).fetchone()
            if exists:
                raise ValueError(f"prompt_id {entry.prompt_id!r} already exists")
            self._upsert_prompt(conn, entry)

    def update(self, entry: PromptEntry) -> None:
        with self.parent._lock, self.parent._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM prompt_registry WHERE prompt_id = ?",
                (entry.prompt_id,),
            ).fetchone()
            if not exists:
                raise KeyError(f"prompt_id {entry.prompt_id!r} not found")
            self._upsert_prompt(conn, entry)

    def get_by_id(self, prompt_id: str) -> PromptEntry | None:
        with self.parent._lock, self.parent._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM prompt_registry WHERE prompt_id = ?",
                (prompt_id,),
            ).fetchone()
            return self._prompt_from_row(row) if row else None

    def get_by_name(self, name: str) -> PromptEntry | None:
        with self.parent._lock, self.parent._connect() as conn:
            row = conn.execute(
                """
                SELECT payload FROM prompt_registry
                WHERE lower(name) = lower(?)
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()
            return self._prompt_from_row(row) if row else None

    def list(self, status: PromptStatus | None = None, agent_id: str | None = None) -> list[PromptEntry]:
        with self.parent._lock, self.parent._connect() as conn:
            clauses: list[str] = []
            params: list[Any] = []
            if status:
                clauses.append("status = ?")
                params.append(status.value)
            if agent_id:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT payload FROM prompt_registry {where} ORDER BY submitted_at DESC",
                params,
            ).fetchall()
            return [self._prompt_from_row(row) for row in rows]

    def list_loadable(self, agent_id: str | None = None) -> list[PromptEntry]:
        with self.parent._lock, self.parent._connect() as conn:
            clauses = [
                "status IN (?, ?)",
            ]
            params: list[Any] = [PromptStatus.APPROVED.value, PromptStatus.DEPLOYED.value]
            if agent_id:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            where = "WHERE " + " AND ".join(clauses)
            rows = conn.execute(
                f"SELECT payload FROM prompt_registry {where} ORDER BY submitted_at DESC",
                params,
            ).fetchall()
            return [self._prompt_from_row(row) for row in rows]

    def enqueue_review(self, request: PromptReviewRequest) -> None:
        with self.parent._lock, self.parent._connect() as conn:
            payload = json.dumps(request.model_dump(mode="json"), ensure_ascii=False, default=str)
            conn.execute(
                """
                INSERT INTO prompt_review_queue (
                    prompt_id, prompt_name, risk_level, submitted_at, queued_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(prompt_id) DO UPDATE SET
                    prompt_name=excluded.prompt_name,
                    risk_level=excluded.risk_level,
                    submitted_at=excluded.submitted_at,
                    queued_at=excluded.queued_at,
                    payload=excluded.payload
                """,
                (
                    request.prompt_id,
                    request.prompt_name,
                    request.risk_level.value,
                    request.submitted_at.isoformat(),
                    request.queued_at.isoformat(),
                    payload,
                ),
            )

    def dequeue_review(self, prompt_id: str) -> PromptReviewRequest | None:
        with self.parent._lock, self.parent._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM prompt_review_queue WHERE prompt_id = ?",
                (prompt_id,),
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM prompt_review_queue WHERE prompt_id = ?", (prompt_id,))
            return PromptReviewRequest.model_validate(json.loads(row["payload"]))

    def list_review_queue(self) -> list[PromptReviewRequest]:
        with self.parent._lock, self.parent._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM prompt_review_queue ORDER BY queued_at ASC"
            ).fetchall()
            return [PromptReviewRequest.model_validate(json.loads(row["payload"])) for row in rows]

    def log_event(self, event: PromptAuditEvent) -> None:
        with self.parent._lock, self.parent._connect() as conn:
            payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, default=str)
            conn.execute(
                """
                INSERT OR IGNORE INTO prompt_audit_events (
                    event_id, event_type, prompt_id, prompt_name, timestamp, actor, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.prompt_id,
                    event.prompt_name,
                    event.timestamp.isoformat(),
                    event.actor,
                    payload,
                ),
            )

    def read_audit(
        self,
        since: datetime | None = None,
        prompt_id: str | None = None,
        limit: int = 100,
    ) -> list[PromptAuditEvent]:
        with self.parent._lock, self.parent._connect() as conn:
            clauses: list[str] = []
            params: list[Any] = []
            if since:
                clauses.append("timestamp >= ?")
                params.append(since.isoformat())
            if prompt_id:
                clauses.append("prompt_id = ?")
                params.append(prompt_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT payload FROM prompt_audit_events
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            events = [PromptAuditEvent.model_validate(json.loads(row["payload"])) for row in rows]
            return list(reversed(events))
