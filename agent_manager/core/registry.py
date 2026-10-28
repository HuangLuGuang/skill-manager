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
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import (
    AuditEvent,
    RegistryEntry,
    ReviewRequest,
    ScanRun,
    SkillStatus,
)
from .prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".agent-manager"
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def _finding_source_key(finding: dict[str, Any]) -> str:
    source = str(finding.get("source") or "").lower()
    if source.startswith("llm"):
        return "llm"
    if source.startswith("sandbox"):
        return "sandbox"
    if source.startswith("skillspector") or source.startswith("deep"):
        return "skillspector"
    return "rule"


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
        self._migrate_skill_families()
        self._repair_nontrusted_approval_evidence()
        self._migrate_inline_scan_reports()
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

    @contextmanager
    def _read_connection(self):
        """Read one committed WAL snapshot without waiting for local writers."""
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            yield conn

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
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_registry_family_fingerprint
                    ON skill_registry(
                        json_extract(payload, '$.family_id'),
                        json_extract(payload, '$.content_fingerprint')
                    )
                    WHERE json_extract(payload, '$.family_id') IS NOT NULL
                      AND json_extract(payload, '$.content_fingerprint') IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_registry_family_version
                    ON skill_registry(
                        json_extract(payload, '$.family_id'),
                        CAST(json_extract(payload, '$.version_no') AS INTEGER)
                    )
                    WHERE json_extract(payload, '$.family_id') IS NOT NULL
                      AND json_extract(payload, '$.version_no') IS NOT NULL;

                CREATE TABLE IF NOT EXISTS skill_families (
                    family_id TEXT PRIMARY KEY,
                    normalized_name TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    latest_version_id TEXT,
                    latest_trusted_version_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_families_updated_at
                    ON skill_families(updated_at);

                CREATE TABLE IF NOT EXISTS registry_migrations (
                    migration_name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS skill_scan_runs (
                    scan_run_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL,
                    scan_context_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    forced INTEGER NOT NULL DEFAULT 0,
                    reused_from_scan_run_id TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    result TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_skill_scan_runs_version
                    ON skill_scan_runs(version_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS skill_scan_run_reports (
                    scan_run_id TEXT PRIMARY KEY,
                    report TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_scan_reports (
                    skill_id TEXT PRIMARY KEY,
                    report TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                -- 执行筛选直接读取索引，避免每次解析完整扫描报告。
                CREATE INDEX IF NOT EXISTS idx_skill_scan_reports_sandbox_executed
                    ON skill_scan_reports(json_type(report, '$.sandbox_analysis.executed'), skill_id);

                CREATE TABLE IF NOT EXISTS skill_finding_stats (
                    skill_id TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    critical INTEGER NOT NULL,
                    high INTEGER NOT NULL,
                    medium INTEGER NOT NULL,
                    low INTEGER NOT NULL,
                    PRIMARY KEY (skill_id, source_key)
                );

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

    def _migrate_skill_families(self) -> None:
        """Convert pre-versioning Skill rows into name families exactly once."""
        migration_name = "skill_families_v1"
        duplicate_ids: list[str] = []
        migrated_versions = 0
        created_families = 0

        with self._lock, self._connect() as conn:
            applied = conn.execute(
                "SELECT 1 FROM registry_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied:
                return

            legacy_rows = conn.execute(
                """
                SELECT skill_id, name, status, submitted_at, updated_at, payload
                FROM skill_registry
                WHERE nullif(json_extract(payload, '$.family_id'), '') IS NULL
                ORDER BY submitted_at ASC, skill_id ASC
                """
            ).fetchall()
            if not legacy_rows:
                conn.execute(
                    """
                    INSERT INTO registry_migrations (migration_name, applied_at, details)
                    VALUES (?, ?, ?)
                    """,
                    (
                        migration_name,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps({"families": 0, "versions": 0, "duplicates_removed": 0}),
                    ),
                )
                return

            groups: dict[str, list[sqlite3.Row]] = {}
            for row in legacy_rows:
                groups.setdefault(self._normalized_skill_name(row["name"]), []).append(row)

            for normalized_name, rows in groups.items():
                newest = max(rows, key=lambda row: (row["submitted_at"], row["skill_id"]))
                newest_payload = json.loads(newest["payload"])
                family = conn.execute(
                    """
                    SELECT family_id, latest_version_id, latest_trusted_version_id
                    FROM skill_families
                    WHERE normalized_name = ?
                    """,
                    (normalized_name,),
                ).fetchone()
                if family:
                    family_id = family["family_id"]
                else:
                    family_id = str(uuid.uuid4())
                    created_families += 1
                    conn.execute(
                        """
                        INSERT INTO skill_families (
                            family_id, normalized_name, name, description,
                            latest_version_id, latest_trusted_version_id,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
                        """,
                        (
                            family_id,
                            normalized_name,
                            newest["name"],
                            str(newest_payload.get("description") or ""),
                            min(row["submitted_at"] for row in rows),
                            max(row["updated_at"] for row in rows),
                        ),
                    )

                existing_rows = conn.execute(
                    """
                    SELECT skill_id,
                           json_extract(payload, '$.content_fingerprint') AS content_fingerprint,
                           CAST(coalesce(json_extract(payload, '$.version_no'), 0) AS INTEGER) AS version_no
                    FROM skill_registry
                    WHERE json_extract(payload, '$.family_id') = ?
                    """,
                    (family_id,),
                ).fetchall()
                existing_fingerprints = {
                    row["content_fingerprint"]
                    for row in existing_rows
                    if row["content_fingerprint"]
                }
                next_version_no = max((int(row["version_no"]) for row in existing_rows), default=0) + 1

                kept_by_fingerprint: dict[str, sqlite3.Row] = {}
                rows_without_fingerprint: list[sqlite3.Row] = []
                for row in rows:
                    payload = json.loads(row["payload"])
                    fingerprint = payload.get("content_fingerprint")
                    if not fingerprint:
                        rows_without_fingerprint.append(row)
                        continue
                    previous = kept_by_fingerprint.get(fingerprint)
                    if previous is None or (row["submitted_at"], row["skill_id"]) > (
                        previous["submitted_at"],
                        previous["skill_id"],
                    ):
                        if previous is not None:
                            duplicate_ids.append(previous["skill_id"])
                        kept_by_fingerprint[fingerprint] = row
                    else:
                        duplicate_ids.append(row["skill_id"])

                kept_rows = [
                    *(
                        row
                        for fingerprint, row in kept_by_fingerprint.items()
                        if fingerprint not in existing_fingerprints
                    ),
                    *rows_without_fingerprint,
                ]
                duplicate_ids.extend(
                    row["skill_id"]
                    for fingerprint, row in kept_by_fingerprint.items()
                    if fingerprint in existing_fingerprints
                )
                kept_rows.sort(key=lambda row: (row["submitted_at"], row["skill_id"]))

                if duplicate_ids:
                    self._delete_version_rows(conn, duplicate_ids)
                    duplicate_ids.clear()

                for row in kept_rows:
                    conn.execute(
                        """
                        UPDATE skill_registry
                        SET payload = json_set(
                            payload,
                            '$.family_id', ?,
                            '$.version_no', ?
                        )
                        WHERE skill_id = ?
                        """,
                        (family_id, next_version_no, row["skill_id"]),
                    )
                    next_version_no += 1
                    migrated_versions += 1

                conn.execute(
                    """
                    UPDATE skill_families
                    SET name = ?, description = ?, updated_at = ?
                    WHERE family_id = ?
                    """,
                    (
                        newest["name"],
                        str(newest_payload.get("description") or ""),
                        max(row["updated_at"] for row in rows),
                        family_id,
                    ),
                )
                self._sync_family_pointers(conn, family_id)

            details = {
                "families": created_families,
                "versions": migrated_versions,
                "duplicates_removed": len(legacy_rows) - migrated_versions,
            }
            conn.execute(
                """
                INSERT INTO registry_migrations (migration_name, applied_at, details)
                VALUES (?, ?, ?)
                """,
                (
                    migration_name,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(details, ensure_ascii=False),
                ),
            )
            logger.info(
                "Migrated legacy Skills into version families: families=%s versions=%s duplicates_removed=%s",
                details["families"],
                details["versions"],
                details["duplicates_removed"],
            )

    @staticmethod
    def _delete_version_rows(conn: sqlite3.Connection, skill_ids: list[str]) -> None:
        if not skill_ids:
            return
        unique_ids = sorted(set(skill_ids))
        placeholders = ",".join("?" for _ in unique_ids)
        params = tuple(unique_ids)
        conn.execute(f"DELETE FROM skill_registry WHERE skill_id IN ({placeholders})", params)
        conn.execute(f"DELETE FROM skill_review_queue WHERE skill_id IN ({placeholders})", params)
        conn.execute(f"DELETE FROM skill_scan_reports WHERE skill_id IN ({placeholders})", params)
        conn.execute(f"DELETE FROM skill_finding_stats WHERE skill_id IN ({placeholders})", params)
        conn.execute(f"DELETE FROM skill_scan_run_reports WHERE scan_run_id IN (SELECT scan_run_id FROM skill_scan_runs WHERE version_id IN ({placeholders}))", params)
        conn.execute(f"DELETE FROM skill_scan_runs WHERE version_id IN ({placeholders})", params)

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

    def _migrate_inline_scan_reports(self) -> None:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.skill_id, s.payload, s.updated_at
                FROM skill_registry s
                LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id
                WHERE r.skill_id IS NULL
                """
            ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping scan report migration for malformed skill row skill_id=%s: %s", row["skill_id"], exc)
                    continue
                vetting = payload.get("vetting")
                if not isinstance(vetting, dict):
                    continue
                scan_report = vetting.get("scan_report")
                if not scan_report:
                    continue
                vetting["scan_report"] = {}
                conn.execute(
                    """
                    INSERT INTO skill_scan_reports (skill_id, report, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(skill_id) DO UPDATE SET
                        report=excluded.report,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row["skill_id"],
                        json.dumps(scan_report, ensure_ascii=False, default=str),
                        row["updated_at"],
                    ),
                )
                conn.execute(
                    "UPDATE skill_registry SET payload = ? WHERE skill_id = ?",
                    (
                        json.dumps(payload, ensure_ascii=False, default=str),
                        row["skill_id"],
                    ),
                )

    def _repair_nontrusted_approval_evidence(self) -> None:
        """Remove stale trust evidence from versions that are no longer trusted."""
        migration_name = "clear_nontrusted_approval_evidence_v1"
        trusted_statuses = (SkillStatus.APPROVED.value, SkillStatus.DEPLOYED.value)

        with self._lock, self._connect() as conn:
            applied = conn.execute(
                "SELECT 1 FROM registry_migrations WHERE migration_name = ?",
                (migration_name,),
            ).fetchone()
            if applied:
                return

            cursor = conn.execute(
                """
                UPDATE skill_registry
                SET payload = json_set(
                    payload,
                    '$.signature', NULL,
                    '$.approved_at', NULL,
                    '$.approved_by', NULL,
                    '$.approval_note', NULL,
                    '$.deployed_at', NULL
                )
                WHERE status NOT IN (?, ?)
                  AND (
                      json_extract(payload, '$.signature') IS NOT NULL
                      OR json_extract(payload, '$.approved_at') IS NOT NULL
                      OR json_extract(payload, '$.approved_by') IS NOT NULL
                      OR json_extract(payload, '$.approval_note') IS NOT NULL
                      OR json_extract(payload, '$.deployed_at') IS NOT NULL
                  )
                """,
                trusted_statuses,
            )
            repaired = max(cursor.rowcount, 0)
            conn.execute(
                """
                INSERT INTO registry_migrations (migration_name, applied_at, details)
                VALUES (?, ?, ?)
                """,
                (
                    migration_name,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps({"repaired_versions": repaired}),
                ),
            )
            if repaired:
                logger.warning("Cleared stale approval evidence from %s non-trusted Skill versions", repaired)

    def _upsert_entry(self, conn: sqlite3.Connection, entry: RegistryEntry) -> None:
        self._ensure_family(conn, entry)
        entry.updated_at = datetime.now(timezone.utc)
        payload_data = entry.model_dump(mode="json")
        scan_report = None
        vetting = payload_data.get("vetting")
        if isinstance(vetting, dict):
            report = vetting.get("scan_report")
            if report:
                scan_report = report
                vetting["scan_report"] = {}
        payload = json.dumps(payload_data, ensure_ascii=False, default=str)
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
        if scan_report is not None:
            conn.execute(
                """
                INSERT INTO skill_scan_reports (skill_id, report, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    report=excluded.report,
                    updated_at=excluded.updated_at
                """,
                (
                    entry.skill_id,
                    json.dumps(scan_report, ensure_ascii=False, default=str),
                    entry.updated_at.isoformat(),
                ),
            )
            conn.execute("DELETE FROM skill_finding_stats WHERE skill_id = ?", (entry.skill_id,))
            buckets: dict[str, dict[str, int]] = {}
            for finding in scan_report.get("findings") or []:
                if not isinstance(finding, dict):
                    continue
                bucket = buckets.setdefault(
                    _finding_source_key(finding),
                    {"count": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
                )
                severity = str(finding.get("severity") or "low").lower()
                severity = "critical" if severity == "extreme" else severity
                severity = severity if severity in {"critical", "high", "medium"} else "low"
                bucket["count"] += 1
                bucket[severity] += 1
            conn.executemany(
                """
                INSERT INTO skill_finding_stats (
                    skill_id, source_key, count, critical, high, medium, low
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entry.skill_id,
                        source,
                        counts["count"],
                        counts["critical"],
                        counts["high"],
                        counts["medium"],
                        counts["low"],
                    )
                    for source, counts in buckets.items()
                ],
            )
        else:
            conn.execute("DELETE FROM skill_scan_reports WHERE skill_id = ?", (entry.skill_id,))
            conn.execute("DELETE FROM skill_finding_stats WHERE skill_id = ?", (entry.skill_id,))
        self._sync_family_pointers(conn, entry.family_id)

    @staticmethod
    def _normalized_skill_name(name: str) -> str:
        return name.strip().casefold()

    def _ensure_family(self, conn: sqlite3.Connection, entry: RegistryEntry) -> None:
        normalized = self._normalized_skill_name(entry.name)
        row = None
        if entry.family_id:
            row = conn.execute(
                "SELECT family_id FROM skill_families WHERE family_id = ?",
                (entry.family_id,),
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT family_id FROM skill_families WHERE normalized_name = ?",
                (normalized,),
            ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if row is None:
            entry.family_id = entry.family_id or str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO skill_families (
                    family_id, normalized_name, name, description,
                    latest_version_id, latest_trusted_version_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (entry.family_id, normalized, entry.name, entry.description, now, now),
            )
        else:
            entry.family_id = row["family_id"]
            conn.execute(
                """
                UPDATE skill_families
                SET name = ?, description = ?, updated_at = ?
                WHERE family_id = ?
                """,
                (entry.name, entry.description, now, entry.family_id),
            )

        if entry.version_no < 1:
            entry.version_no = 1
        existing = conn.execute(
            """
            SELECT 1 FROM skill_registry
            WHERE json_extract(payload, '$.family_id') = ?
              AND CAST(coalesce(json_extract(payload, '$.version_no'), 1) AS INTEGER) = ?
              AND skill_id != ?
            """,
            (entry.family_id, entry.version_no, entry.skill_id),
        ).fetchone()
        if existing:
            row = conn.execute(
                """
                SELECT coalesce(max(CAST(json_extract(payload, '$.version_no') AS INTEGER)), 0) + 1 AS next_no
                FROM skill_registry
                WHERE json_extract(payload, '$.family_id') = ?
                """,
                (entry.family_id,),
            ).fetchone()
            entry.version_no = int(row["next_no"])

    def _sync_family_pointers(self, conn: sqlite3.Connection, family_id: str | None) -> None:
        if not family_id:
            return
        versions = conn.execute(
            """
            SELECT skill_id, status,
                   CAST(coalesce(json_extract(payload, '$.version_no'), 1) AS INTEGER) AS version_no
            FROM skill_registry
            WHERE json_extract(payload, '$.family_id') = ?
            ORDER BY version_no DESC, submitted_at DESC
            """,
            (family_id,),
        ).fetchall()
        latest = versions[0]["skill_id"] if versions else None
        trusted = next(
            (
                row["skill_id"]
                for row in versions
                if row["status"] in (SkillStatus.APPROVED.value, SkillStatus.DEPLOYED.value)
            ),
            None,
        )
        conn.execute(
            """
            UPDATE skill_families
            SET latest_version_id = ?, latest_trusted_version_id = ?, updated_at = ?
            WHERE family_id = ?
            """,
            (latest, trusted, datetime.now(timezone.utc).isoformat(), family_id),
        )

    def _entry_from_row(self, row: sqlite3.Row) -> RegistryEntry:
        payload = json.loads(row["payload"])
        if "updated_at" not in payload and "updated_at" in row.keys():
            payload["updated_at"] = row["updated_at"]
        if "scan_report" in row.keys() and row["scan_report"] and isinstance(payload.get("vetting"), dict):
            payload["vetting"]["scan_report"] = json.loads(row["scan_report"])
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

    def update(self, entry: RegistryEntry, *, backfill_content_fingerprint: str | None = None) -> None:
        """Replace an existing entry by skill_id."""
        with self._lock, self._connect() as conn:
            if backfill_content_fingerprint is not None:
                conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM skill_registry WHERE skill_id = ?",
                (entry.skill_id,),
            ).fetchone()
            if not exists:
                raise KeyError(f"skill_id {entry.skill_id!r} not found")
            if backfill_content_fingerprint is not None and entry.content_fingerprint is None:
                owner = conn.execute(
                    """
                    SELECT skill_id FROM skill_registry
                    WHERE json_extract(payload, '$.family_id') = ?
                      AND json_extract(payload, '$.content_fingerprint') = ?
                      AND skill_id != ?
                    """,
                    (entry.family_id, backfill_content_fingerprint, entry.skill_id),
                ).fetchone()
                # Historical versions can predate content deduplication. Keep
                # their identity; each scan report records the computed digest.
                if owner is None:
                    entry.content_fingerprint = backfill_content_fingerprint
            self._upsert_entry(conn, entry)

    def grant_submission_principal(self, skill_id: str, principal: str) -> list[str]:
        """Atomically allow a scanner principal to read one immutable version."""
        if not principal:
            return []
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload FROM skill_registry WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"skill_id {skill_id!r} not found")
            payload = json.loads(row["payload"])
            principals = list(payload.get("submission_principals") or [])
            if principal not in principals:
                principals.append(principal)
                payload["submission_principals"] = principals
                conn.execute(
                    "UPDATE skill_registry SET payload = ? WHERE skill_id = ?",
                    (json.dumps(payload, ensure_ascii=False, default=str), skill_id),
                )
            return principals

    def delete(self, skill_id: str) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT json_extract(payload, '$.family_id') AS family_id FROM skill_registry WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            cur = conn.execute("DELETE FROM skill_registry WHERE skill_id = ?", (skill_id,))
            if cur.rowcount == 0:
                raise KeyError(f"skill_id {skill_id!r} not found")
            conn.execute("DELETE FROM skill_review_queue WHERE skill_id = ?", (skill_id,))
            conn.execute("DELETE FROM skill_scan_reports WHERE skill_id = ?", (skill_id,))
            conn.execute("DELETE FROM skill_finding_stats WHERE skill_id = ?", (skill_id,))
            conn.execute("DELETE FROM skill_scan_run_reports WHERE scan_run_id IN (SELECT scan_run_id FROM skill_scan_runs WHERE version_id = ?)", (skill_id,))
            conn.execute("DELETE FROM skill_scan_runs WHERE version_id = ?", (skill_id,))
            family_id = row["family_id"] if row else None
            self._sync_family_pointers(conn, family_id)
            if family_id:
                remaining = conn.execute(
                    "SELECT 1 FROM skill_registry WHERE json_extract(payload, '$.family_id') = ? LIMIT 1",
                    (family_id,),
                ).fetchone()
                if not remaining:
                    conn.execute("DELETE FROM skill_families WHERE family_id = ?", (family_id,))

    def get_by_id(self, skill_id: str, *, include_scan_report: bool = True) -> RegistryEntry | None:
        with self._read_connection() as conn:
            row = conn.execute(
                f"""
                SELECT s.skill_id, s.name, s.payload, s.updated_at, {"r.report" if include_scan_report else "NULL"} AS scan_report
                FROM skill_registry s
                {"LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id" if include_scan_report else ""}
                WHERE s.skill_id = ?
                """,
                (skill_id,),
            ).fetchone()
            return self._safe_entry_from_row(row)

    def get_by_name(self, name: str, *, include_scan_report: bool = True) -> RegistryEntry | None:
        """Return the latest version of the named Skill family."""
        with self._read_connection() as conn:
            row = conn.execute(
                f"""
                SELECT s.skill_id, s.name, s.payload, s.updated_at, {"r.report" if include_scan_report else "NULL"} AS scan_report
                FROM skill_families f
                JOIN skill_registry s ON s.skill_id = f.latest_version_id
                {"LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id" if include_scan_report else ""}
                WHERE f.normalized_name = ?
                """,
                (self._normalized_skill_name(name),),
            ).fetchone()
            return self._safe_entry_from_row(row)

    def get_trusted_by_name(self, name: str, *, include_scan_report: bool = True) -> RegistryEntry | None:
        """Return the latest approved or deployed version of the named Skill family."""
        with self._read_connection() as conn:
            row = conn.execute(
                f"""
                SELECT s.skill_id, s.name, s.payload, s.updated_at, {"r.report" if include_scan_report else "NULL"} AS scan_report
                FROM skill_families f
                JOIN skill_registry s ON s.skill_id = f.latest_trusted_version_id
                {"LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id" if include_scan_report else ""}
                WHERE f.normalized_name = ?
                """,
                (self._normalized_skill_name(name),),
            ).fetchone()
            return self._safe_entry_from_row(row)

    def get_by_family_id(self, family_id: str, *, trusted: bool = False, include_scan_report: bool = True) -> RegistryEntry | None:
        pointer = "latest_trusted_version_id" if trusted else "latest_version_id"
        with self._read_connection() as conn:
            row = conn.execute(
                f"""
                SELECT s.skill_id, s.name, s.payload, s.updated_at, {"r.report" if include_scan_report else "NULL"} AS scan_report
                FROM skill_families f
                JOIN skill_registry s ON s.skill_id = f.{pointer}
                {"LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id" if include_scan_report else ""}
                WHERE f.family_id = ?
                """,
                (family_id,),
            ).fetchone()
            return self._safe_entry_from_row(row)

    def list_versions(self, family_id_or_name: str, *, include_scan_report: bool = True) -> list[RegistryEntry]:
        with self._read_connection() as conn:
            family = conn.execute(
                """
                SELECT family_id, latest_version_id, latest_trusted_version_id
                FROM skill_families
                WHERE family_id = ? OR normalized_name = ?
                """,
                (family_id_or_name, self._normalized_skill_name(family_id_or_name)),
            ).fetchone()
            if not family:
                family = conn.execute(
                    """
                    SELECT family_id, latest_version_id, latest_trusted_version_id
                    FROM skill_families WHERE family_id = (
                        SELECT json_extract(payload, '$.family_id')
                        FROM skill_registry WHERE skill_id = ?
                    )
                    """,
                    (family_id_or_name,),
                ).fetchone()
                if not family:
                    return []
            rows = conn.execute(
                f"""
                SELECT s.skill_id, s.name, s.payload, s.updated_at, {"r.report" if include_scan_report else "NULL"} AS scan_report
                FROM skill_registry s
                {"LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id" if include_scan_report else ""}
                WHERE json_extract(s.payload, '$.family_id') = ?
                ORDER BY CAST(coalesce(json_extract(s.payload, '$.version_no'), 1) AS INTEGER) DESC
                """,
                (family["family_id"],),
            ).fetchall()
            entries = self._entries_from_rows(rows)
            for entry in entries:
                entry.latest_version = entry.skill_id == family["latest_version_id"]
                entry.latest_trusted_version = entry.skill_id == family["latest_trusted_version_id"]
            return entries

    def find_version_by_content(self, name: str, content_fingerprint: str) -> RegistryEntry | None:
        with self._read_connection() as conn:
            row = conn.execute(
                """
                SELECT s.skill_id, s.name, s.payload, s.updated_at, r.report AS scan_report
                FROM skill_registry s
                JOIN skill_families f
                  ON f.family_id = json_extract(s.payload, '$.family_id')
                LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id
                WHERE f.normalized_name = ?
                  AND json_extract(s.payload, '$.content_fingerprint') = ?
                LIMIT 1
                """,
                (self._normalized_skill_name(name), content_fingerprint),
            ).fetchone()
            return self._safe_entry_from_row(row)

    def next_version_no(self, name: str) -> tuple[str | None, int]:
        with self._read_connection() as conn:
            family = conn.execute(
                "SELECT family_id FROM skill_families WHERE normalized_name = ?",
                (self._normalized_skill_name(name),),
            ).fetchone()
            if not family:
                return None, 1
            row = conn.execute(
                """
                SELECT coalesce(max(CAST(json_extract(payload, '$.version_no') AS INTEGER)), 0) + 1 AS next_no
                FROM skill_registry
                WHERE json_extract(payload, '$.family_id') = ?
                """,
                (family["family_id"],),
            ).fetchone()
            return family["family_id"], int(row["next_no"])

    def record_scan_reuse(
        self,
        skill_id: str,
        content_fingerprint: str,
        scan_context_fingerprint: str,
    ) -> tuple[RegistryEntry, str]:
        """Atomically record reuse against the current version and report."""
        with self._lock, self._connect() as conn:
            # 同一事务重读并只更新复用字段，保留并发审批、停用等决定。
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT s.skill_id, s.name, s.payload, s.updated_at, r.report AS scan_report
                   FROM skill_registry s
                   LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id
                   WHERE s.skill_id = ?""",
                (skill_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"skill_id {skill_id!r} not found")
            entry = self._entry_from_row(row)
            pending = conn.execute(
                "SELECT 1 FROM skill_scan_runs WHERE version_id = ? AND status = 'PENDING' LIMIT 1",
                (skill_id,),
            ).fetchone()
            if pending:
                return entry, "scan_in_progress"
            if (
                entry.content_fingerprint != content_fingerprint
                or entry.scan_context_fingerprint != scan_context_fingerprint
                or entry.vetting is None
            ):
                return entry, "existing_version_rescan"

            source = conn.execute(
                """SELECT scan_run_id, reused_from_scan_run_id FROM skill_scan_runs
                   WHERE version_id = ? AND scan_context_fingerprint = ?
                     AND status IN ('COMPLETED', 'REUSED')
                   ORDER BY started_at DESC LIMIT 1""",
                (skill_id, scan_context_fingerprint),
            ).fetchone()
            entry.scan_reused = True
            entry.reused_from_skill_id = skill_id
            entry.updated_at = datetime.now(timezone.utc)
            entry.vetting.scan_report = {
                **entry.vetting.scan_report,
                "scan_reused": True,
                "reused_from_skill_id": skill_id,
            }
            stamp = entry.updated_at.isoformat()
            conn.execute(
                """UPDATE skill_registry SET updated_at = ?, payload = json_set(
                       payload, '$.scan_reused', json('true'),
                       '$.reused_from_skill_id', ?, '$.updated_at', ?)
                   WHERE skill_id = ?""",
                (stamp, skill_id, stamp, skill_id),
            )
            conn.execute(
                """INSERT INTO skill_scan_reports (skill_id, report, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(skill_id) DO UPDATE SET report=excluded.report, updated_at=excluded.updated_at""",
                (skill_id, json.dumps(entry.vetting.scan_report, ensure_ascii=False), stamp),
            )
            conn.execute(
                "UPDATE skill_families SET updated_at = ? WHERE family_id = ?",
                (stamp, entry.family_id),
            )
            # 复用记录直接进入终态，不结束其他请求创建的 PENDING 任务。
            run = ScanRun(
                scan_run_id=str(uuid.uuid4()), version_id=skill_id,
                scan_context_fingerprint=scan_context_fingerprint,
                status="REUSED", started_at=entry.updated_at, finished_at=entry.updated_at,
                reused_from_scan_run_id=(
                    source["reused_from_scan_run_id"] or source["scan_run_id"]
                ) if source else None,
                result=ScanRun.result_for(entry),
            )
            self._insert_scan_run(conn, run)
            conn.execute(
                "INSERT INTO skill_scan_run_reports (scan_run_id, report) VALUES (?, ?)",
                (run.scan_run_id, json.dumps(entry.vetting.model_dump(mode="json"), ensure_ascii=False)),
            )
            return entry, "existing_version_reused"

    def add_scan_run(self, run: ScanRun) -> None:
        with self._lock, self._connect() as conn:
            self._insert_scan_run(conn, run)

    @staticmethod
    def _insert_scan_run(conn: sqlite3.Connection, run: ScanRun) -> None:
        conn.execute(
            """
            INSERT INTO skill_scan_runs (
                scan_run_id, version_id, scan_context_fingerprint, status, forced,
                reused_from_scan_run_id, started_at, finished_at, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.scan_run_id,
                run.version_id,
                run.scan_context_fingerprint,
                run.status,
                1 if run.forced else 0,
                run.reused_from_scan_run_id,
                run.started_at.isoformat(),
                run.finished_at.isoformat() if run.finished_at else None,
                json.dumps(run.result, ensure_ascii=False, default=str),
            ),
        )

    def update_scan_progress(self, scan_run_id: str, stage: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE skill_scan_runs
                SET result = json_set(result, '$.progress_stage', ?)
                WHERE scan_run_id = ? AND status = 'PENDING'
                """,
                (stage, scan_run_id),
            )

    def update_scan_analyzer(self, scan_run_id: str, analyzer: str, status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE skill_scan_runs
                SET result = json_set(result, ?, ?)
                WHERE scan_run_id = ? AND status = 'PENDING'
                """,
                (f"$.analyzers.{analyzer}", status, scan_run_id),
            )

    def update_scan_run(self, run: ScanRun, *, report: dict | None = None) -> None:
        with self._lock, self._connect() as conn:
            if report is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO skill_scan_run_reports (scan_run_id, report) VALUES (?, ?)",
                    (run.scan_run_id, json.dumps(report, ensure_ascii=False, default=str)),
                )
            conn.execute(
                """
                UPDATE skill_scan_runs
                SET status = ?, reused_from_scan_run_id = ?, finished_at = ?, result = ?
                WHERE scan_run_id = ?
                """,
                (
                    run.status,
                    run.reused_from_scan_run_id,
                    run.finished_at.isoformat() if run.finished_at else None,
                    json.dumps(run.result, ensure_ascii=False, default=str),
                    run.scan_run_id,
                ),
            )

    def get_scan_run_report(self, scan_run_id: str) -> dict | None:
        with self._read_connection() as conn:
            row = conn.execute("SELECT report FROM skill_scan_run_reports WHERE scan_run_id = ?", (scan_run_id,)).fetchone()
        return json.loads(row["report"]) if row else None

    def list_scan_runs(self, version_id: str) -> list[ScanRun]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM skill_scan_runs
                WHERE version_id = ?
                ORDER BY started_at DESC
                """,
                (version_id,),
            ).fetchall()
        return [
            ScanRun(
                scan_run_id=row["scan_run_id"],
                version_id=row["version_id"],
                scan_context_fingerprint=row["scan_context_fingerprint"],
                status=row["status"],
                forced=bool(row["forced"]),
                reused_from_scan_run_id=row["reused_from_scan_run_id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
                result=json.loads(row["result"] or "{}"),
            )
            for row in rows
        ]

    def list_scan_runs_for_versions(self, version_ids: list[str]) -> dict[str, list[ScanRun]]:
        normalized = list(dict.fromkeys(value for value in version_ids if value))
        result: dict[str, list[ScanRun]] = {value: [] for value in normalized}
        if not normalized:
            return result
        rows = []
        with self._read_connection() as conn:
            for offset in range(0, len(normalized), 500):
                batch = normalized[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                rows.extend(conn.execute(
                    f"""
                    SELECT * FROM skill_scan_runs
                    WHERE version_id IN ({placeholders})
                    ORDER BY version_id, started_at DESC
                    """,
                    tuple(batch),
                ).fetchall())
        for row in rows:
            result[row["version_id"]].append(ScanRun(
                scan_run_id=row["scan_run_id"],
                version_id=row["version_id"],
                scan_context_fingerprint=row["scan_context_fingerprint"],
                status=row["status"],
                forced=bool(row["forced"]),
                reused_from_scan_run_id=row["reused_from_scan_run_id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
                result=json.loads(row["result"] or "{}"),
            ))
        return result

    def skill_version_activity(self, version_ids: list[str]) -> dict[str, dict[str, int | bool]]:
        normalized = list(dict.fromkeys(value for value in version_ids if value))
        result: dict[str, dict[str, int | bool]] = {
            value: {"processing_count": 0, "rescan_requested": False}
            for value in normalized
        }
        if not normalized:
            return result
        rows = []
        with self._read_connection() as conn:
            for offset in range(0, len(normalized), 500):
                batch = normalized[offset:offset + 500]
                placeholders = ",".join("?" for _ in batch)
                rows.extend(conn.execute(
                    f"""
                    SELECT
                        skill_id,
                        sum(CASE WHEN event_type = 'skill_processing_completed' THEN 1 ELSE 0 END) AS processing_count,
                        max(CASE WHEN event_type = 'skill_rescan_requested' THEN 1 ELSE 0 END) AS rescan_requested
                    FROM skill_audit_events
                    WHERE skill_id IN ({placeholders})
                      AND event_type IN ('skill_processing_completed', 'skill_rescan_requested')
                    GROUP BY skill_id
                    """,
                    tuple(batch),
                ).fetchall())
        for row in rows:
            result[row["skill_id"]] = {
                "processing_count": int(row["processing_count"] or 0),
                "rescan_requested": bool(row["rescan_requested"]),
            }
        return result

    def list_all(self, status: SkillStatus | None = None) -> list[RegistryEntry]:
        with self._read_connection() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT s.skill_id, s.name, s.payload, s.updated_at, r.report AS scan_report
                    FROM skill_registry s
                    LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id
                    WHERE s.status = ?
                    ORDER BY s.updated_at DESC
                    """,
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.skill_id, s.name, s.payload, s.updated_at, r.report AS scan_report
                    FROM skill_registry s
                    LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id
                    ORDER BY s.updated_at DESC
                    """
                ).fetchall()
            return self._entries_from_rows(rows)

    def count_skills(self) -> int:
        with self._read_connection() as conn:
            return int(conn.execute("SELECT count(*) FROM skill_families").fetchone()[0])

    def list_certification_candidates(self, *, skill_id: str | None = None, name: str | None = None) -> list[RegistryEntry]:
        """Read identity/signature metadata without loading scan reports.

        A deployment version takes precedence over a name. All exact-name
        matches remain candidates so ambiguous registrations are not hidden.
        """
        if skill_id:
            where, values = "WHERE skill_id = ?", (skill_id,)
        elif name:
            where, values = "WHERE name = ?", (name,)
        else:
            where, values = "", ()
        with self._read_connection() as conn:
            rows = conn.execute(
                f"SELECT skill_id, name, payload, updated_at FROM skill_registry {where} ORDER BY updated_at DESC",
                values,
            ).fetchall()
            return self._entries_from_rows(rows)

    def count_review_queue(self) -> int:
        with self._read_connection() as conn:
            return int(conn.execute("SELECT count(*) FROM skill_review_queue").fetchone()[0])

    def list_by_names(self, names: list[str] | set[str]) -> list[RegistryEntry]:
        normalized = sorted({name.strip().lower() for name in names if name and name.strip()})
        if not normalized:
            return []
        placeholders = ", ".join("?" for _ in normalized)
        with self._read_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT skill_id, name, payload, updated_at
                FROM skill_registry
                WHERE lower(name) IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                normalized,
            ).fetchall()
            return self._entries_from_rows(rows)

    def list_skill_summaries(
        self,
        *,
        page: int,
        page_size: int,
        statuses: list[SkillStatus] | None = None,
        scanning: bool | None = None,
        cancelled_only: bool = False,
        cancelled_reason: str = "",
        loadable_only: bool = False,
        risk_level: str | None = None,
        sandbox_triggered: bool | None = None,
        sandbox_executed: bool | None = None,
        sandbox_required_by_policy: bool | None = None,
        trusted_only: bool = False,
        q: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []

        if scanning is not None:
            scan_condition = """(s.status = 'PENDING' OR EXISTS (
                SELECT 1 FROM skill_scan_runs runs
                WHERE runs.version_id = s.skill_id AND runs.status = 'PENDING'
            ))"""
            where.append(scan_condition if scanning else f"NOT {scan_condition}")

        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"s.status IN ({placeholders})")
            params.extend(status.value for status in statuses)
        if loadable_only:
            where.append("s.status IN (?, ?)")
            params.extend([SkillStatus.APPROVED.value, SkillStatus.DEPLOYED.value])
        if cancelled_only:
            where.append("json_extract(s.payload, '$.rejection_reason') = ?")
            params.append(cancelled_reason)
        if risk_level:
            where.append("s.risk_level = ?")
            params.append(risk_level)
        if sandbox_triggered is not None:
            where.append("coalesce(json_extract(s.payload, '$.vetting.sandbox_triggered'), 0) = ?")
            params.append(1 if sandbox_triggered else 0)
        if sandbox_executed is not None:
            # 通过覆盖索引取得已执行版本集合，计数和分页共用执行依据。
            executed_condition = """s.skill_id IN (
                SELECT skill_id FROM skill_scan_reports
                WHERE json_type(report, '$.sandbox_analysis.executed') = 'true'
            )"""
            where.append(executed_condition if sandbox_executed else f"NOT {executed_condition}")
        if sandbox_required_by_policy is not None:
            where.append("coalesce(json_extract(s.payload, '$.vetting.sandbox_required_by_policy'), 0) = ?")
            params.append(1 if sandbox_required_by_policy else 0)
        if q:
            needle = f"%{q.lower()}%"
            where.append(
                "(lower(s.name) LIKE ? OR lower(f.family_id) LIKE ? OR "
                "lower(coalesce(json_extract(s.payload, '$.approved_by'), '')) LIKE ?)"
            )
            params.extend([needle, needle, needle])

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sort_columns = {
            "name": "lower(s.name)",
            "skill_id": "lower(f.family_id)",
            "status": "s.status",
            "risk_level": "coalesce(s.risk_level, '')",
            "approved_by": "lower(coalesce(json_extract(s.payload, '$.approved_by'), ''))",
            "submitted_at": "s.submitted_at",
            "updated_at": "s.updated_at",
        }
        sort_expr = sort_columns.get(sort_by, "updated_at")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        safe_page = max(page, 1)
        safe_page_size = max(1, min(page_size, 100))
        offset = (safe_page - 1) * safe_page_size

        with self._read_connection() as conn:
            version_pointer = "latest_trusted_version_id" if trusted_only else "latest_version_id"
            total = conn.execute(
                f"""
                SELECT count(*)
                FROM skill_families f
                JOIN skill_registry s ON s.skill_id = f.{version_pointer}
                {where_sql}
                """,
                tuple(params),
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT
                    f.family_id AS skill_id,
                    s.skill_id AS version_id,
                    CAST(coalesce(json_extract(s.payload, '$.version_no'), 1) AS INTEGER) AS version_no,
                    json_extract(s.payload, '$.source_version') AS source_version,
                    f.latest_trusted_version_id,
                    tv.status AS latest_trusted_status,
                    CAST(coalesce(json_extract(tv.payload, '$.version_no'), 0) AS INTEGER) AS latest_trusted_version_no,
                    s.name,
                    s.status,
                    EXISTS (
                        SELECT 1 FROM skill_scan_runs runs
                        WHERE runs.version_id = s.skill_id AND runs.status = 'PENDING'
                    ) AS scan_pending,
                    (
                        SELECT json_extract(runs.result, '$.progress_stage')
                        FROM skill_scan_runs runs
                        WHERE runs.version_id = s.skill_id AND runs.status = 'PENDING'
                        ORDER BY runs.started_at DESC LIMIT 1
                    ) AS scan_progress_stage,
                    (
                        SELECT json_extract(runs.result, '$.analyzers')
                        FROM skill_scan_runs runs
                        WHERE runs.version_id = s.skill_id AND runs.status = 'PENDING'
                        ORDER BY runs.started_at DESC LIMIT 1
                    ) AS scan_progress_analyzers,
                    s.risk_level,
                    s.submitted_at,
                    s.updated_at,
                    json_type(s.payload, '$.vetting') AS vetting_type,
                    json_extract(s.payload, '$.vetting.sandbox_triggered') AS sandbox_triggered,
                    json_extract(s.payload, '$.vetting.sandbox_required_by_policy') AS sandbox_required_by_policy,
                    json_extract(s.payload, '$.vetting.sandbox_runtime') AS sandbox_runtime,
                    json_extract(s.payload, '$.scan_options') AS scan_options,
                    json_extract(sr.report, '$.analyzer_timings') AS analyzer_timings,
                    json_extract(sr.report, '$.llm_analysis.risk_level') AS llm_risk,
                    coalesce(json_extract(sr.report, '$.skillspector_analysis.risk_severity'),
                             json_extract(sr.report, '$.skillspector_analysis.max_severity'),
                             json_extract(sr.report, '$.skillspector_analysis.risk_level')) AS deep_risk,
                    json_extract(sr.report, '$.sandbox_analysis.risk_level') AS sandbox_risk,
                    json_extract(sr.report, '$.sandbox_analysis.executed') AS sandbox_executed,
                    coalesce(fs.count, 0) AS rule_findings,
                    json_extract(s.payload, '$.approved_by') AS approved_by,
                    json_extract(s.payload, '$.source.author') AS submitted_by,
                    json_extract(s.payload, '$.rejection_reason') AS rejection_reason,
                    json_extract(s.payload, '$.approved_at') AS approved_at,
                    json_extract(s.payload, '$.deployed_at') AS deployed_at
                FROM skill_families f
                JOIN skill_registry s ON s.skill_id = f.{version_pointer}
                LEFT JOIN skill_registry tv ON tv.skill_id = f.latest_trusted_version_id
                LEFT JOIN skill_scan_reports sr ON sr.skill_id = s.skill_id
                LEFT JOIN skill_finding_stats fs ON fs.skill_id = s.skill_id AND fs.source_key = 'rule'
                {where_sql}
                ORDER BY {sort_expr} {direction}, s.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple([*params, safe_page_size, offset]),
            ).fetchall()

        items = []
        for row in rows:
            has_vetting = row["vetting_type"] is not None
            sandbox_triggered_value = bool(row["sandbox_triggered"]) if has_vetting else False
            sandbox_required_value = bool(row["sandbox_required_by_policy"]) if has_vetting else False
            sandbox_runtime_value = row["sandbox_runtime"] if has_vetting else None
            timings = json.loads(row["analyzer_timings"] or "{}")
            options = json.loads(row["scan_options"] or "{}")
            analysis_results = {}
            for key, timing_key, option in (
                ("rule", "scanner", None), ("skillspector", "skillspector", "use_skillspector"),
                ("sandbox", "sandbox", "use_sandbox"), ("llm", "llm", "use_llm"),
            ):
                state = timings.get(timing_key, {}).get("status")
                if not state:
                    state = "disabled" if option and options.get(option) is False else "unrecorded"
                analysis_results[key] = {"status": state}
            analysis_results["rule"]["findings_count"] = row["rule_findings"]
            analysis_results["llm"]["risk_level"] = row["llm_risk"]
            analysis_results["skillspector"]["risk_level"] = row["deep_risk"]
            analysis_results["sandbox"]["risk_level"] = row["sandbox_risk"] if row["sandbox_executed"] else None
            analysis_results["sandbox"]["executed"] = row["sandbox_executed"] == 1
            # 旧报告可缺少 timing；已保存的执行证据只在读取时补齐列表状态。
            if row["sandbox_executed"] and not timings.get("sandbox", {}).get("status"):
                analysis_results["sandbox"]["status"] = "completed"
            if row["llm_risk"] and not timings.get("llm", {}).get("status"):
                analysis_results["llm"]["status"] = "completed"
            items.append({
                "skill_id": row["skill_id"],
                "version_id": row["version_id"],
                "version_no": row["version_no"],
                "source_version": row["source_version"],
                "latest_trusted_version_id": row["latest_trusted_version_id"],
                "latest_trusted_version_no": row["latest_trusted_version_no"] or None,
                "latest_trusted_status": row["latest_trusted_status"],
                "name": row["name"],
                "status": row["status"],
                "scan_pending": bool(row["scan_pending"]),
                "scan_progress_stage": row["scan_progress_stage"],
                "scan_progress_analyzers": json.loads(row["scan_progress_analyzers"] or "{}"),
                "risk_level": row["risk_level"],
                "vetting": {
                    "sandbox_triggered": sandbox_triggered_value,
                    "sandbox_required_by_policy": sandbox_required_value,
                    "sandbox_runtime": sandbox_runtime_value,
                } if has_vetting else None,
                "sandbox_triggered": sandbox_triggered_value,
                "sandbox_required_by_policy": sandbox_required_value,
                "sandbox_runtime": sandbox_runtime_value,
                "analysis_results": analysis_results,
                "approved_by": row["approved_by"],
                "submitted_by": row["submitted_by"],
                "rejection_reason": row["rejection_reason"],
                "submitted_at": row["submitted_at"],
                "updated_at": row["updated_at"],
                "approved_at": row["approved_at"],
                "deployed_at": row["deployed_at"],
            })
        return {
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
        }

    def dashboard_stats(self) -> dict[str, Any]:
        """Return the dashboard's Skill aggregates without loading full scan reports."""
        with self._read_connection() as conn:
            grouped = conn.execute(
                """
                SELECT s.status, s.risk_level, count(*) AS count
                FROM skill_families f
                JOIN skill_registry s ON s.skill_id = f.latest_version_id
                GROUP BY s.status, s.risk_level
                """
            ).fetchall()
            todos = conn.execute(
                """
                SELECT s.skill_id, s.name, s.status, s.risk_level, s.submitted_at
                FROM skill_families f
                JOIN skill_registry s ON s.skill_id = f.latest_version_id
                WHERE s.status = ?
                ORDER BY s.submitted_at DESC
                LIMIT 20
                """,
                (SkillStatus.VETTED.value,),
            ).fetchall()
            findings = conn.execute(
                """
                SELECT
                    source_key,
                    sum(count) AS count,
                    count(*) AS skills,
                    sum(critical) AS critical,
                    sum(high) AS high,
                    sum(medium) AS medium,
                    sum(low) AS low
                FROM skill_finding_stats fs
                JOIN skill_families f ON f.latest_version_id = fs.skill_id
                GROUP BY source_key
                """
            ).fetchall()

            status_counts: dict[str, int] = {}
            risk_counts: dict[str, int] = {}
            total = 0
            for row in grouped:
                count = int(row["count"])
                total += count
                status_counts[row["status"]] = status_counts.get(row["status"], 0) + count
                if row["risk_level"]:
                    risk_counts[row["risk_level"]] = risk_counts.get(row["risk_level"], 0) + count

            result = {
                "total": total,
                "status_counts": status_counts,
                "risk_counts": risk_counts,
                "todos": [dict(row) for row in todos],
                "risk_sources": {row["source_key"]: dict(row) for row in findings},
            }
            return result

    def list_by_statuses(self, statuses: list[SkillStatus]) -> list[RegistryEntry]:
        """Return all skills whose status is in the given list."""
        if not statuses:
            return []
        with self._read_connection() as conn:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"""
                SELECT s.skill_id, s.name, s.payload, s.updated_at, r.report AS scan_report
                FROM skill_registry s
                LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id
                WHERE s.status IN ({placeholders})
                ORDER BY s.updated_at DESC
                """,
                tuple(s.value for s in statuses),
            ).fetchall()
            return self._entries_from_rows(rows)

    def list_loadable(self) -> list[RegistryEntry]:
        """Return all skills that agents can load."""
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                SELECT s.skill_id, s.name, s.payload, s.updated_at, r.report AS scan_report
                FROM skill_registry s
                LEFT JOIN skill_scan_reports r ON r.skill_id = s.skill_id
                WHERE s.status IN (?, ?)
                ORDER BY s.submitted_at DESC
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
        with self._read_connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM skill_review_queue ORDER BY queued_at ASC"
            ).fetchall()
            return [ReviewRequest.model_validate(json.loads(row["payload"])) for row in rows]

    def list_reviewed_summaries(self) -> list[dict[str, Any]]:
        with self._read_connection() as conn:
            rows = conn.execute(
                """
                WITH findings AS (
                    SELECT
                        skill_id,
                        sum(critical) AS critical,
                        sum(high) AS high,
                        sum(medium) AS medium,
                        sum(low) AS low
                    FROM skill_finding_stats
                    GROUP BY skill_id
                )
                SELECT
                    s.skill_id,
                    s.name AS skill_name,
                    s.risk_level,
                    s.status,
                    s.submitted_at,
                    json_extract(s.payload, '$.approved_at') AS approved_at,
                    coalesce(json_extract(s.payload, '$.approved_at'), s.updated_at) AS reviewed_at,
                    json_extract(s.payload, '$.approved_by') AS approved_by,
                    json_extract(s.payload, '$.approval_note') AS approval_note,
                    json_extract(s.payload, '$.rejection_reason') AS rejection_reason,
                    coalesce(f.critical, 0) AS critical,
                    coalesce(f.high, 0) AS high,
                    coalesce(f.medium, 0) AS medium,
                    coalesce(f.low, 0) AS low
                FROM skill_registry s
                LEFT JOIN findings f ON f.skill_id = s.skill_id
                WHERE s.status IN (?, ?)
                """,
                (SkillStatus.APPROVED.value, SkillStatus.REJECTED.value),
            ).fetchall()

        items = []
        for row in rows:
            review_note = row["rejection_reason"] if row["status"] == SkillStatus.REJECTED.value else row["approval_note"]
            findings = {key: int(row[key]) for key in ("critical", "high", "medium", "low")}
            findings["total"] = sum(findings.values())
            approved_at = row["approved_at"]
            reviewed_at = row["reviewed_at"]
            if approved_at and approved_at.endswith("Z"):
                approved_at = f"{approved_at[:-1]}+00:00"
            if reviewed_at and reviewed_at.endswith("Z"):
                reviewed_at = f"{reviewed_at[:-1]}+00:00"
            items.append({
                "skill_id": row["skill_id"],
                "skill_name": row["skill_name"],
                "risk_level": row["risk_level"],
                "status": row["status"],
                "findings_summary": findings,
                "submitted_at": row["submitted_at"],
                "queued_at": row["submitted_at"],
                "reviewed_at": reviewed_at,
                "sort_at": reviewed_at,
                "notes": review_note,
                "review_note": review_note,
                "approval_note": row["approval_note"],
                "approved_by": row["approved_by"],
                "approved_at": approved_at,
                "rejection_reason": row["rejection_reason"],
            })
        return items

    # ------------------------------------------------------------------ #
    # Audit log                                                            #
    # ------------------------------------------------------------------ #

    def log_event(self, event: AuditEvent) -> None:
        with self._lock, self._connect() as conn:
            self._insert_audit(conn, event, ignore_existing=True)

    _governance_audit_predicates = ("event_id NOT LIKE 'client-event-%'", "COALESCE(json_extract(payload, '$.details.source'), '') != 'managed_client'")

    def governance_audit_agents(self):
        with self._read_connection() as conn:
            return [row[0] for row in conn.execute(
                "SELECT DISTINCT json_extract(payload, '$.details.agent_id') FROM skill_audit_events WHERE "
                + ' AND '.join(self._governance_audit_predicates)
            ) if row[0]]

    def governance_audit_page(self, *, since=None, q='', agent='', client_id='', category='', result='', limit=10, order='desc', matching_agent_ids=()):
        """Read original registry events for the federated governance view.

        Client-event projections have an authoritative, device-scoped source in
        the management database and must not bypass its visibility rules here.
        """
        if client_id or category not in ('', 'capability') or (agent and not agent.startswith('platform:')):
            return {'items': [], 'total': 0}
        state = """CASE
            WHEN event_type IN ('skill_load_blocked','tool_blocked','skill_rejected') THEN 'deny'
            WHEN event_type IN ('skill_processing_failed','skill_auto_install_failed') THEN 'failed'
            WHEN event_type = 'skill_load_allowed' THEN 'allow'
            WHEN event_type IN ('skill_approved','skill_signature_verified','skill_processing_completed','skill_deployed') THEN 'success'
            ELSE 'recorded' END"""
        clauses = list(self._governance_audit_predicates)
        params = []
        def audit_timestamp(value):
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp.astimezone(timezone.utc).isoformat(timespec='microseconds')

        with self._read_connection() as conn:
            # Match the federated sort's precision; SQLite date functions round to milliseconds.
            conn.create_function('audit_timestamp', 1, audit_timestamp, deterministic=True)
            if since:
                clauses.append('audit_timestamp(timestamp) >= audit_timestamp(?)')
                params.append(since.isoformat())
            if q:
                clauses.append("(instr(lower(skill_name), lower(?)) > 0 OR instr(lower(skill_id), lower(?)) > 0 OR instr(lower(event_type), lower(?)) > 0 OR instr(lower(COALESCE(actor,'')), lower(?)) > 0 OR instr(lower(COALESCE(json_extract(payload, '$.details.agent_id'),'')), lower(?)) > 0)")
                params.extend([q] * 5)
                if matching_agent_ids:
                    placeholders = ','.join('?' for _ in matching_agent_ids)
                    clauses[-1] = f"({clauses[-1]} OR json_extract(payload, '$.details.agent_id') IN ({placeholders}))"
                    params.extend(matching_agent_ids)
            if agent:
                clauses.append("json_extract(payload, '$.details.agent_id') = ?")
                params.append(agent.partition(':')[2])
            if result:
                clauses.append(f'({state}) = ?')
                params.append(result)
            where = ' AND '.join(clauses)
            total = conn.execute('SELECT count(*) FROM skill_audit_events WHERE ' + where, params).fetchone()[0]
            direction = 'ASC' if order == 'asc' else 'DESC'
            rows = conn.execute(f'SELECT payload, {state} AS result FROM skill_audit_events WHERE {where} ORDER BY audit_timestamp(timestamp) {direction}, event_id {direction} LIMIT ?', [*params, limit])
            return {'items': [{**json.loads(row['payload']), 'result':row['result']} for row in rows], 'total':total}

    def read_audit(
        self,
        since: datetime | None = None,
        skill_id: str | None = None,
        limit: int = 100,
        event_types: tuple[str, ...] = (),
        exclude_preserved_failures: bool = False,
    ) -> list[AuditEvent]:
        with self._read_connection() as conn:
            clauses: list[str] = []
            params: list[Any] = []
            if since:
                clauses.append("timestamp >= ?")
                params.append(since.isoformat())
            if skill_id:
                clauses.append("skill_id = ?")
                params.append(skill_id)
            if event_types:
                placeholders = ','.join('?' for _ in event_types)
                clauses.append(f"event_type IN ({placeholders})")
                params.extend(event_types)
            if exclude_preserved_failures:
                clauses.append("NOT (event_type = 'skill_processing_failed' AND "
                               "COALESCE(json_extract(payload, '$.details.effective_result_preserved'), 0) = 1)")
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
