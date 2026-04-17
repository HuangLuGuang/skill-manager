"""Tests for the registry."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skill_manager.core.models import (
    AuditEvent,
    RegistryEntry,
    ReviewRequest,
    RiskLevel,
    SkillOrigin,
    SkillStatus,
    SourceInfo,
)
from skill_manager.core.registry import Registry, make_event


def _make_entry(name="my-skill", status=SkillStatus.APPROVED) -> RegistryEntry:
    return RegistryEntry(
        skill_id=f"id-{name}",
        name=name,
        description="Test skill",
        source=SourceInfo(origin=SkillOrigin.LOCAL, author="test-author"),
        status=status,
        risk_level=RiskLevel.LOW,
    )


@pytest.fixture
def registry(tmp_path):
    return Registry(data_dir=tmp_path)


class TestRegistry:
    def test_add_and_retrieve(self, registry):
        entry = _make_entry()
        registry.add(entry)
        found = registry.get_by_id("id-my-skill")
        assert found is not None
        assert found.name == "my-skill"

    def test_duplicate_id_raises(self, registry):
        entry = _make_entry()
        registry.add(entry)
        with pytest.raises(ValueError, match="already exists"):
            registry.add(entry)

    def test_get_by_name(self, registry):
        registry.add(_make_entry("skill-alpha"))
        found = registry.get_by_name("skill-alpha")
        assert found is not None

    def test_get_by_name_case_insensitive(self, registry):
        registry.add(_make_entry("MySkill"))
        assert registry.get_by_name("myskill") is not None

    def test_get_by_id_missing(self, registry):
        assert registry.get_by_id("nonexistent") is None

    def test_list_all(self, registry):
        registry.add(_make_entry("a"))
        registry.add(_make_entry("b", status=SkillStatus.DEPLOYED))
        all_entries = registry.list_all()
        assert len(all_entries) == 2

    def test_list_filtered_by_status(self, registry):
        registry.add(_make_entry("a", status=SkillStatus.APPROVED))
        registry.add(_make_entry("b", status=SkillStatus.DEPLOYED))
        approved = registry.list_all(status=SkillStatus.APPROVED)
        assert len(approved) == 1
        assert approved[0].name == "a"

    def test_update(self, registry):
        entry = _make_entry()
        registry.add(entry)
        entry.status = SkillStatus.DEPLOYED
        registry.update(entry)
        updated = registry.get_by_id(entry.skill_id)
        assert updated.status == SkillStatus.DEPLOYED

    def test_update_missing_raises(self, registry):
        entry = _make_entry("ghost")
        with pytest.raises(KeyError):
            registry.update(entry)

    def test_list_loadable(self, registry):
        registry.add(_make_entry("a", SkillStatus.APPROVED))
        registry.add(_make_entry("b", SkillStatus.DEPLOYED))
        registry.add(_make_entry("c", SkillStatus.VETTED))
        registry.add(_make_entry("d", SkillStatus.REJECTED))
        loadable = registry.list_loadable()
        assert len(loadable) == 2
        names = {e.name for e in loadable}
        assert names == {"a", "b"}

    def test_review_queue(self, registry):
        req = ReviewRequest(
            skill_id="id-my-skill",
            skill_name="my-skill",
            risk_level=RiskLevel.HIGH,
            findings_summary={"high": 2},
            submitted_at=datetime.now(timezone.utc),
        )
        registry.enqueue_review(req)
        queue = registry.list_review_queue()
        assert len(queue) == 1

        dequeued = registry.dequeue_review("id-my-skill")
        assert dequeued is not None
        assert registry.list_review_queue() == []

    def test_audit_log(self, registry):
        entry = _make_entry()
        registry.add(entry)
        ev = make_event("skill_approved", entry, actor="alice", details={"note": "ok"})
        registry.log_event(ev)

        events = registry.read_audit()
        assert len(events) == 1
        assert events[0].event_type == "skill_approved"
        assert events[0].actor == "alice"

    def test_audit_filter_by_skill_id(self, registry):
        e1 = _make_entry("skill-1")
        e2 = _make_entry("skill-2")
        registry.add(e1)
        registry.add(e2)
        registry.log_event(make_event("skill_submitted", e1))
        registry.log_event(make_event("skill_submitted", e2))

        events = registry.read_audit(skill_id=e1.skill_id)
        assert all(ev.skill_id == e1.skill_id for ev in events)

    def test_persistence(self, tmp_path):
        r1 = Registry(data_dir=tmp_path)
        r1.add(_make_entry("persistent-skill"))

        r2 = Registry(data_dir=tmp_path)
        assert r2.get_by_name("persistent-skill") is not None

    def test_recovers_registry_with_extra_json_data(self, tmp_path):
        entry = _make_entry("recoverable")
        registry_file = tmp_path / "registry.json"
        registry_file.write_text(
            json.dumps([entry.model_dump(mode="json")], default=str) + "\n[]\n",
            encoding="utf-8",
        )
        registry = Registry(data_dir=tmp_path)

        entries = registry.list_all()

        assert len(entries) == 1
        assert entries[0].name == "recoverable"
        assert json.loads(registry_file.read_text(encoding="utf-8"))[0]["name"] == "recoverable"
        assert list(tmp_path.glob("registry.json.corrupt-*"))

    def test_uses_configured_sqlite_path(self, tmp_path, monkeypatch):
        db_path = tmp_path / "shared" / "admin_starter.db"
        monkeypatch.setenv("SKILL_MANAGER_REGISTRY_SQLITE_PATH", str(db_path))

        registry = Registry(data_dir=tmp_path / "data")
        registry.add(_make_entry("sqlite-backed"))

        assert db_path.exists()
        assert Registry(data_dir=tmp_path / "other-data").get_by_name("sqlite-backed") is not None
