"""
Skill registry — persistent JSON-backed store for RegistryEntry records.

Storage layout (default: ~/.skill-manager/):
  registry.json   — list of RegistryEntry objects
  audit.jsonl     — append-only audit log (one JSON object per line)
  review.json     — pending human review queue
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AuditEvent, RegistryEntry, ReviewRequest, RiskLevel, SkillStatus

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".skill-manager"


class Registry:
    """Thread-safe (file-lock-free for single-process) JSON registry."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.environ.get("SKILL_MANAGER_DATA_DIR", _DEFAULT_DIR))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._registry_file = self.data_dir / "registry.json"
        self._audit_file = self.data_dir / "audit.jsonl"
        self._review_file = self.data_dir / "review.json"

    # ------------------------------------------------------------------ #
    # Internal load/save                                                   #
    # ------------------------------------------------------------------ #

    def _load_entries(self) -> list[RegistryEntry]:
        if not self._registry_file.exists():
            return []
        raw = json.loads(self._registry_file.read_text())
        return [RegistryEntry.model_validate(e) for e in raw]

    def _save_entries(self, entries: list[RegistryEntry]) -> None:
        data = [e.model_dump(mode="json") for e in entries]
        self._registry_file.write_text(json.dumps(data, indent=2, default=str))

    def _load_review_queue(self) -> list[ReviewRequest]:
        if not self._review_file.exists():
            return []
        raw = json.loads(self._review_file.read_text())
        return [ReviewRequest.model_validate(r) for r in raw]

    def _save_review_queue(self, queue: list[ReviewRequest]) -> None:
        data = [r.model_dump(mode="json") for r in queue]
        self._review_file.write_text(json.dumps(data, indent=2, default=str))

    # ------------------------------------------------------------------ #
    # Registry CRUD                                                        #
    # ------------------------------------------------------------------ #

    def add(self, entry: RegistryEntry) -> None:
        """Add a new entry. Raises if skill_id already exists."""
        entries = self._load_entries()
        if any(e.skill_id == entry.skill_id for e in entries):
            raise ValueError(f"skill_id {entry.skill_id!r} already exists in registry")
        entries.append(entry)
        self._save_entries(entries)

    def update(self, entry: RegistryEntry) -> None:
        """Replace an existing entry by skill_id."""
        entries = self._load_entries()
        for i, e in enumerate(entries):
            if e.skill_id == entry.skill_id:
                entries[i] = entry
                self._save_entries(entries)
                return
        raise KeyError(f"skill_id {entry.skill_id!r} not found")

    def get_by_id(self, skill_id: str) -> RegistryEntry | None:
        for e in self._load_entries():
            if e.skill_id == skill_id:
                return e
        return None

    def get_by_name(self, name: str) -> RegistryEntry | None:
        """Return the most recently submitted entry with matching name."""
        matches = [e for e in self._load_entries() if e.name.lower() == name.lower()]
        if not matches:
            return None
        return sorted(matches, key=lambda e: e.submitted_at, reverse=True)[0]

    def list_all(self, status: SkillStatus | None = None) -> list[RegistryEntry]:
        entries = self._load_entries()
        if status:
            entries = [e for e in entries if e.status == status]
        return sorted(entries, key=lambda e: e.submitted_at, reverse=True)

    def list_loadable(self) -> list[RegistryEntry]:
        """Return all skills that agents can load."""
        return [e for e in self._load_entries() if e.is_loadable()]

    # ------------------------------------------------------------------ #
    # Review queue                                                         #
    # ------------------------------------------------------------------ #

    def enqueue_review(self, request: ReviewRequest) -> None:
        queue = self._load_review_queue()
        queue.append(request)
        self._save_review_queue(queue)

    def dequeue_review(self, skill_id: str) -> ReviewRequest | None:
        queue = self._load_review_queue()
        for i, r in enumerate(queue):
            if r.skill_id == skill_id:
                queue.pop(i)
                self._save_review_queue(queue)
                return r
        return None

    def list_review_queue(self) -> list[ReviewRequest]:
        return sorted(self._load_review_queue(), key=lambda r: r.queued_at)

    # ------------------------------------------------------------------ #
    # Audit log                                                            #
    # ------------------------------------------------------------------ #

    def log_event(self, event: AuditEvent) -> None:
        line = json.dumps(event.model_dump(mode="json"), default=str) + "\n"
        with open(self._audit_file, "a") as f:
            f.write(line)

    def read_audit(
        self,
        since: datetime | None = None,
        skill_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        if not self._audit_file.exists():
            return []
        events: list[AuditEvent] = []
        with open(self._audit_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = AuditEvent.model_validate(json.loads(line))
                    if since and ev.timestamp < since:
                        continue
                    if skill_id and ev.skill_id != skill_id:
                        continue
                    events.append(ev)
                except Exception:
                    pass
        return events[-limit:]


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
