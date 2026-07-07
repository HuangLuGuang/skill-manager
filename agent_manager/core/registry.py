"""
Skill registry — persistent SQLite-backed store for RegistryEntry records.

Storage layout (default: ~/.agent-manager/):
  agent_manager_registry.db — SQLite registry when SQLITE_PATH is not set
  registry.json             — legacy file imported on startup if the DB is empty
  audit.jsonl               — legacy audit log imported on startup if present
  review.json               — legacy review queue imported on startup if the DB is empty
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import (
    AuditEvent,
    RegistryEntry,
    ReviewRequest,
    SkillStatus,
)
from .prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".agent-manager"
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


class Registry:
    """SQLite registry with legacy JSON import support."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.environ.get("AGENT_MANAGER_DATA_DIR", _DEFAULT_DIR)).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.prompts = PromptRegistry(self)
        self._registry_file = self.data_dir / "registry.json"
        self._audit_file = self.data_dir / "audit.jsonl"
        self._review_file = self.data_dir / "review.json"

        db_path = None
        if data_dir is None:
            db_path = os.environ.get("AGENT_MANAGER_REGISTRY_SQLITE_PATH") or os.environ.get("SQLITE_PATH")
        self._db_file = Path(db_path) if db_path else self.data_dir / "agent_manager_registry.db"
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(self._db_file.resolve(), threading.RLock())
        self._init_db()
        self._migrate_legacy_files()
        self._checkpoint()

    # ------------------------------------------------------------------ #
    # Internal load/save                                                   #
    # ------------------------------------------------------------------ #

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_file, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_registry (
                    skill_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk_level TEXT,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_registry_name ON skill_registry(lower(name));
                CREATE INDEX IF NOT EXISTS idx_skill_registry_status ON skill_registry(status);
                CREATE INDEX IF NOT EXISTS idx_skill_registry_submitted_at ON skill_registry(submitted_at);
                CREATE INDEX IF NOT EXISTS idx_skill_registry_updated_at ON skill_registry(updated_at);

                CREATE TABLE IF NOT EXISTS skill_review_queue (
                    skill_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    queued_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_review_queue_queued_at ON skill_review_queue(queued_at);

                CREATE TABLE IF NOT EXISTS skill_audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    actor TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_audit_timestamp ON skill_audit_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_skill_audit_skill_id ON skill_audit_events(skill_id);

                CREATE TABLE IF NOT EXISTS prompt_registry (
                    prompt_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    risk_level TEXT,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prompt_registry_name ON prompt_registry(lower(name));
                CREATE INDEX IF NOT EXISTS idx_prompt_registry_agent ON prompt_registry(agent_id);
                CREATE INDEX IF NOT EXISTS idx_prompt_registry_status ON prompt_registry(status);

                CREATE TABLE IF NOT EXISTS prompt_review_queue (
                    prompt_id TEXT PRIMARY KEY,
                    prompt_name TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    queued_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prompt_review_queue_queued_at ON prompt_review_queue(queued_at);

                CREATE TABLE IF NOT EXISTS prompt_audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    prompt_id TEXT NOT NULL,
                    prompt_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    actor TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prompt_audit_timestamp ON prompt_audit_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_prompt_audit_prompt_id ON prompt_audit_events(prompt_id);
                """
            )

    def _migrate_legacy_files(self) -> None:
        with self._lock, self._connect() as conn:
            skill_count = conn.execute("SELECT count(*) FROM skill_registry").fetchone()[0]
            if skill_count == 0 and self._registry_file.exists():
                for item in self._load_json_array(self._registry_file):
                    entry = RegistryEntry.model_validate(item)
                    self._upsert_entry(conn, entry)
                logger.info("Migrated legacy registry.json into SQLite: %s", self._db_file)

            review_count = conn.execute("SELECT count(*) FROM skill_review_queue").fetchone()[0]
            if review_count == 0 and self._review_file.exists():
                for item in self._load_json_array(self._review_file):
                    review = ReviewRequest.model_validate(item)
                    self._upsert_review(conn, review)
                logger.info("Migrated legacy review.json into SQLite: %s", self._db_file)

            if self._audit_file.exists():
                for line in self._audit_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        event = AuditEvent.model_validate(json.loads(line))
                    except Exception:
                        continue
                    self._insert_audit(conn, event, ignore_existing=True)

    def _checkpoint(self) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            logger.debug("SQLite WAL checkpoint skipped for %s", self._db_file, exc_info=True)

    def _load_json_array(self, path: Path) -> list[Any]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            payload = self._recover_json_array(path, text, exc)
        if not isinstance(payload, list):
            raise ValueError(f"{path} must contain a JSON array")
        return payload

    def _recover_json_array(self, path: Path, text: str, error: json.JSONDecodeError) -> list[Any]:
        decoder = json.JSONDecoder()
        payloads: list[list[Any]] = []
        index = 0
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                break
            try:
                payload, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                break
            if isinstance(payload, list):
                payloads.append(payload)
            index = end

        if not payloads:
            raise error

        payload = max(enumerate(payloads), key=lambda item: (len(item[1]), item[0]))[1]
        backup = path.with_name(f"{path.name}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        backup.write_text(text, encoding="utf-8")
        logger.error("Recovered %s from JSON extra data; original backed up to %s", path, backup)
        self._atomic_write_json(path, payload)
        return payload

    def _atomic_write_json(self, path: Path, payload: list[Any]) -> None:
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp_path, path)

    def _upsert_entry(self, conn: sqlite3.Connection, entry: RegistryEntry) -> None:
        entry.updated_at = datetime.now(timezone.utc)
        payload = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, default=str)
        conn.execute(
            """
            INSERT INTO skill_registry (
                skill_id, name, status, risk_level, submitted_at, updated_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(skill_id) DO UPDATE SET
                name=excluded.name,
                status=excluded.status,
                risk_level=excluded.risk_level,
                submitted_at=excluded.submitted_at,
                updated_at=excluded.updated_at,
                payload=excluded.payload
            """,
            (
                entry.skill_id,
                entry.name,
                entry.status.value,
                entry.risk_level.value if entry.risk_level else None,
                entry.submitted_at.isoformat(),
                entry.updated_at.isoformat(),
                payload,
            ),
        )

    def _entry_from_row(self, row: sqlite3.Row) -> RegistryEntry:
        payload = json.loads(row["payload"])
        if "updated_at" not in payload and "updated_at" in row.keys():
            payload["updated_at"] = row["updated_at"]
        return RegistryEntry.model_validate(payload)

    def _entries_from_rows(self, rows: list[sqlite3.Row]) -> list[RegistryEntry]:
        entries: list[RegistryEntry] = []
        for row in rows:
            try:
                entries.append(self._entry_from_row(row))
            except (json.JSONDecodeError, ValidationError) as exc:
                row_id = row["skill_id"] if "skill_id" in row.keys() else "unknown"
                row_name = row["name"] if "name" in row.keys() else "unknown"
                logger.warning("Skipping malformed skill registry row skill_id=%s name=%s: %s", row_id, row_name, exc)
        return entries

    def _safe_entry_from_row(self, row: sqlite3.Row | None) -> RegistryEntry | None:
        if not row:
            return None
        try:
            return self._entry_from_row(row)
        except (json.JSONDecodeError, ValidationError) as exc:
            row_id = row["skill_id"] if "skill_id" in row.keys() else "unknown"
            row_name = row["name"] if "name" in row.keys() else "unknown"
            logger.warning("Skipping malformed skill registry row skill_id=%s name=%s: %s", row_id, row_name, exc)
            return None

    def _upsert_review(self, conn: sqlite3.Connection, request: ReviewRequest) -> None:
        payload = json.dumps(request.model_dump(mode="json"), ensure_ascii=False, default=str)
        conn.execute(
            """
            INSERT INTO skill_review_queue (
                skill_id, skill_name, risk_level, submitted_at, queued_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(skill_id) DO UPDATE SET
                skill_name=excluded.skill_name,
                risk_level=excluded.risk_level,
                submitted_at=excluded.submitted_at,
                queued_at=excluded.queued_at,
                payload=excluded.payload
            """,
            (
                request.skill_id,
                request.skill_name,
                request.risk_level.value,
                request.submitted_at.isoformat(),
                request.queued_at.isoformat(),
                payload,
            ),
        )

    def _insert_audit(self, conn: sqlite3.Connection, event: AuditEvent, ignore_existing: bool = False) -> None:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, default=str)
        statement = "INSERT OR IGNORE" if ignore_existing else "INSERT"
        conn.execute(
            f"""
            {statement} INTO skill_audit_events (
                event_id, event_type, skill_id, skill_name, timestamp, actor, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                event.skill_id,
                event.skill_name,
                event.timestamp.isoformat(),
                event.actor,
                payload,
            ),
        )

    # ------------------------------------------------------------------ #
    # Registry CRUD                                                        #
    # ------------------------------------------------------------------ #

    def add(self, entry: RegistryEntry) -> None:
        """Add a new entry. Raises if skill_id already exists."""
        with self._lock, self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM skill_registry WHERE skill_id = ?",
                (entry.skill_id,),
            ).fetchone()
            if exists:
                raise ValueError(f"skill_id {entry.skill_id!r} already exists in registry")
            self._upsert_entry(conn, entry)

    def update(self, entry: RegistryEntry) -> None:
        """Replace an existing entry by skill_id."""
        with self._lock, self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM skill_registry WHERE skill_id = ?",
                (entry.skill_id,),
            ).fetchone()
            if not exists:
                raise KeyError(f"skill_id {entry.skill_id!r} not found")
            self._upsert_entry(conn, entry)

    def refresh_signature_if_current(
        self,
        skill_id: str,
        old_signature: str,
        new_signature: str,
    ) -> RegistryEntry | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT skill_id, name, payload, updated_at FROM skill_registry WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            entry = self._safe_entry_from_row(row)
            if not entry or entry.signature != old_signature or not entry.is_loadable():
                return entry
            entry.signature = new_signature
            self._upsert_entry(conn, entry)
            return entry

    def delete(self, skill_id: str) -> None:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM skill_registry WHERE skill_id = ?", (skill_id,))
            if cur.rowcount == 0:
                raise KeyError(f"skill_id {skill_id!r} not found")
            conn.execute("DELETE FROM skill_review_queue WHERE skill_id = ?", (skill_id,))

    def get_by_id(self, skill_id: str) -> RegistryEntry | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT skill_id, name, payload, updated_at FROM skill_registry WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            return self._safe_entry_from_row(row)

    def get_by_name(self, name: str) -> RegistryEntry | None:
        """Return the most recently submitted entry with matching name."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT skill_id, name, payload, updated_at FROM skill_registry
                WHERE lower(name) = lower(?)
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()
            return self._safe_entry_from_row(row)

    def list_all(self, status: SkillStatus | None = None) -> list[RegistryEntry]:
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT skill_id, name, payload, updated_at FROM skill_registry
                    WHERE status = ?
                    ORDER BY updated_at DESC
                    """,
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT skill_id, name, payload, updated_at FROM skill_registry ORDER BY updated_at DESC"
                ).fetchall()
            return self._entries_from_rows(rows)

    def list_by_statuses(self, statuses: list[SkillStatus]) -> list[RegistryEntry]:
        """Return all skills whose status is in the given list."""
        if not statuses:
            return []
        with self._lock, self._connect() as conn:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"""
                SELECT skill_id, name, payload, updated_at FROM skill_registry
                WHERE status IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                tuple(s.value for s in statuses),
            ).fetchall()
            return self._entries_from_rows(rows)

    def list_loadable(self) -> list[RegistryEntry]:
        """Return all skills that agents can load."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT skill_id, name, payload, updated_at FROM skill_registry
                WHERE status IN (?, ?)
                ORDER BY submitted_at DESC
                """,
                (SkillStatus.APPROVED.value, SkillStatus.DEPLOYED.value),
            ).fetchall()
            return self._entries_from_rows(rows)

    # ------------------------------------------------------------------ #
    # Review queue                                                         #
    # ------------------------------------------------------------------ #

    def enqueue_review(self, request: ReviewRequest) -> None:
        with self._lock, self._connect() as conn:
            self._upsert_review(conn, request)

    def dequeue_review(self, skill_id: str) -> ReviewRequest | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM skill_review_queue WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM skill_review_queue WHERE skill_id = ?", (skill_id,))
            return ReviewRequest.model_validate(json.loads(row["payload"]))

    def list_review_queue(self) -> list[ReviewRequest]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM skill_review_queue ORDER BY queued_at ASC"
            ).fetchall()
            return [ReviewRequest.model_validate(json.loads(row["payload"])) for row in rows]

    # ------------------------------------------------------------------ #
    # Audit log                                                            #
    # ------------------------------------------------------------------ #

    def log_event(self, event: AuditEvent) -> None:
        with self._lock, self._connect() as conn:
            self._insert_audit(conn, event, ignore_existing=True)

    def read_audit(
        self,
        since: datetime | None = None,
        skill_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        with self._lock, self._connect() as conn:
            clauses: list[str] = []
            params: list[Any] = []
            if since:
                clauses.append("timestamp >= ?")
                params.append(since.isoformat())
            if skill_id:
                clauses.append("skill_id = ?")
                params.append(skill_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT payload FROM skill_audit_events
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            events = [AuditEvent.model_validate(json.loads(row["payload"])) for row in rows]
            return list(reversed(events))

    # ------------------------------------------------------------------ #
    # Prompt delegation                                                    #
    # ------------------------------------------------------------------ #

    def add_prompt(self, *args, **kwargs):
        return self.prompts.add(*args, **kwargs)

    def update_prompt(self, *args, **kwargs):
        return self.prompts.update(*args, **kwargs)

    def get_prompt_by_id(self, *args, **kwargs):
        return self.prompts.get_by_id(*args, **kwargs)

    def get_prompt_by_name(self, *args, **kwargs):
        return self.prompts.get_by_name(*args, **kwargs)

    def list_prompts(self, *args, **kwargs):
        return self.prompts.list(*args, **kwargs)

    def list_prompts_loadable(self, *args, **kwargs):
        return self.prompts.list_loadable(*args, **kwargs)

    def enqueue_prompt_review(self, *args, **kwargs):
        return self.prompts.enqueue_review(*args, **kwargs)

    def dequeue_prompt_review(self, *args, **kwargs):
        return self.prompts.dequeue_review(*args, **kwargs)

    def list_prompt_review_queue(self, *args, **kwargs):
        return self.prompts.list_review_queue(*args, **kwargs)

    def log_prompt_event(self, *args, **kwargs):
        return self.prompts.log_event(*args, **kwargs)

    def read_prompt_audit(self, *args, **kwargs):
        return self.prompts.read_audit(*args, **kwargs)


# --------------------------------------------------------------------------- #
# Audit helper                                                                  #
# --------------------------------------------------------------------------- #

def make_event(
    event_type: str,
    entry: RegistryEntry,
    actor: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        skill_id=entry.skill_id,
        skill_name=entry.name,
        actor=actor,
        details=details or {},
    )
