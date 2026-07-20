"""Tests for the runtime guard."""

import tempfile
from pathlib import Path

import pytest

from agent_manager.core.models import (
    RegistryEntry,
    RiskLevel,
    SkillOrigin,
    SkillStatus,
    SourceInfo,
)
from agent_manager.core.registry import Registry
from agent_manager.core.runtime import RuntimeGuard
from agent_manager.core.signer import compute_content_digest, compute_signature


def _make_entry(name, status=SkillStatus.APPROVED, tools=None, sig=None):
    return RegistryEntry(
        skill_id=f"id-{name}",
        name=name,
        description="Test",
        source=SourceInfo(origin=SkillOrigin.LOCAL),
        status=status,
        risk_level=RiskLevel.BENIGN,
        allowed_tools=tools or [],
        signature=sig,
    )


@pytest.fixture
def registry(tmp_path):
    return Registry(data_dir=tmp_path)


@pytest.fixture
def guard(registry):
    return RuntimeGuard(registry=registry)


class TestRuntimeGuard:
    def test_allows_approved_skill(self, guard, registry):
        registry.add(_make_entry("good-skill"))
        allowed, entry, reason = guard.can_load("good-skill", verify_sig=False)
        assert allowed
        assert entry is not None

    def test_allows_deployed_skill(self, guard, registry):
        registry.add(_make_entry("deployed-skill", SkillStatus.DEPLOYED))
        allowed, _, _ = guard.can_load("deployed-skill", verify_sig=False)
        assert allowed

    def test_blocks_unregistered_skill(self, guard):
        allowed, entry, reason = guard.can_load("ghost-skill", verify_sig=False)
        assert not allowed
        assert entry is None
        assert "not in the registry" in reason

    def test_blocks_vetted_skill(self, guard, registry):
        registry.add(_make_entry("unreviewed", SkillStatus.VETTED))
        allowed, _, reason = guard.can_load("unreviewed", verify_sig=False)
        assert not allowed
        assert "VETTED" in reason

    def test_blocks_retired_skill(self, guard, registry):
        registry.add(_make_entry("old-skill", SkillStatus.RETIRED))
        allowed, _, _ = guard.can_load("old-skill", verify_sig=False)
        assert not allowed

    def test_blocks_rejected_skill(self, guard, registry):
        registry.add(_make_entry("bad-skill", SkillStatus.REJECTED))
        allowed, _, _ = guard.can_load("bad-skill", verify_sig=False)
        assert not allowed

    def test_signature_verified_correctly(self, guard, registry, tmp_path):
        """A skill with correct signature passes verification."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: signed\ndescription: d\n---\n")

        sig = compute_signature(skill_dir)
        entry = _make_entry("signed", sig=sig)
        entry.skill_path = str(skill_dir)
        registry.add(entry)

        allowed, _, reason = guard.can_load("signed", skill_path=str(skill_dir))
        assert allowed, reason

    def test_signature_mismatch_blocks(self, guard, registry, tmp_path):
        """Tampered skill content is detected and blocked."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: tampered\ndescription: d\n---\n")

        sig = compute_signature(skill_dir)
        # Now tamper the file
        (skill_dir / "SKILL.md").write_text("---\nname: tampered\ndescription: INJECTED\n---\n")

        entry = _make_entry("tampered", sig=sig)
        registry.add(entry)

        allowed, _, reason = guard.can_load("tampered", skill_path=str(skill_dir))
        assert not allowed
        assert "tamper" in reason.lower() or "mismatch" in reason.lower()

    def test_verify_local_signature_allows_match(self, guard, registry, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: signed\ndescription: d\n---\n")

        sig = compute_signature(skill_dir)
        entry = _make_entry("signed", sig=sig)
        registry.add(entry)

        allowed, matched_entry, reason = guard.verify_local_signature("signed", sig, agent_id="agent-1")
        assert allowed, reason
        assert matched_entry is not None
        assert matched_entry.name == "signed"

    def test_verify_local_signature_blocks_mismatch(self, guard, registry, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: signed\ndescription: d\n---\n")

        sig = compute_signature(skill_dir)
        entry = _make_entry("signed", sig=sig)
        registry.add(entry)

        allowed, _, reason = guard.verify_local_signature("signed", "not-the-real-signature", agent_id="agent-1")
        assert not allowed
        assert "tamper" in reason.lower() or "mismatch" in reason.lower()

    def test_verify_local_signature_refreshes_legacy_mojibake_signature(self, guard, registry, tmp_path):
        local_dir = tmp_path / "local"
        stored_dir = tmp_path / "stored"
        (local_dir / "references").mkdir(parents=True)
        (stored_dir / "references").mkdir(parents=True)
        (local_dir / "references" / "常用查询模板.md").write_text("select 1", encoding="utf-8")
        (stored_dir / "references" / "σ╕╕τö¿µƒÑΦ»óµ¿íµ¥┐.md").write_text("select 1", encoding="utf-8")
        local_sig = compute_signature(local_dir)
        entry = _make_entry("signed", sig="legacy-signature")
        entry.skill_path = str(stored_dir)
        registry.add(entry)

        allowed, matched_entry, reason = guard.verify_local_signature("signed", local_sig, agent_id="agent-1")

        assert allowed
        assert reason == "signature verified"
        assert matched_entry.signature == local_sig
        assert registry.get_by_id(entry.skill_id).signature == local_sig

    def test_verify_local_signature_refresh_io_error_is_not_tamper(self, guard, registry, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: signed\n---\n", encoding="utf-8")
        entry = _make_entry("signed", sig="legacy-signature")
        entry.skill_path = str(tmp_path / "missing")
        registry.add(entry)

        allowed, _, reason = guard.verify_local_signature("signed", compute_signature(skill_dir), agent_id="agent-1")

        assert not allowed
        assert "could not be refreshed" in reason
        assert "skill_tamper_detected" not in {event.event_type for event in registry.read_audit()}

    def test_verify_local_signature_reports_missing_client_signing_key(self, guard, registry, tmp_path, monkeypatch):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: signed\n---\n", encoding="utf-8")
        monkeypatch.setenv("AGENT_MANAGER_SIGNING_KEY", "server-key")
        entry = _make_entry("signed", sig=compute_signature(skill_dir))
        entry.skill_path = str(skill_dir)
        registry.add(entry)

        allowed, _, reason = guard.verify_local_signature(
            "signed", compute_content_digest(skill_dir), agent_id="agent-1"
        )

        assert not allowed
        assert "AGENT_MANAGER_SIGNING_KEY" in reason
        assert "skill_tamper_detected" not in {event.event_type for event in registry.read_audit()}

    def test_verify_local_signature_blocks_non_loadable_status(self, guard, registry, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: reviewed\ndescription: d\n---\n")

        sig = compute_signature(skill_dir)
        entry = _make_entry("reviewed", status=SkillStatus.VETTED, sig=sig)
        registry.add(entry)

        allowed, _, reason = guard.verify_local_signature("reviewed", sig)
        assert not allowed
        assert "VETTED" in reason

    def test_check_tool_declared(self, guard, registry):
        registry.add(_make_entry("tool-skill", tools=["Read", "Grep"]))
        assert guard.check_tool("tool-skill", "Read")
        assert guard.check_tool("tool-skill", "Grep")
        assert not guard.check_tool("tool-skill", "Bash")

    def test_check_tool_matches_parent_and_child_tool_permissions(self, guard, registry):
        registry.add(_make_entry("bash-parent", tools=["Bash"]))
        registry.add(_make_entry("bash-child", tools=["Bash(python:*)"]))

        assert guard.check_tool("bash-parent", "Bash(python:*)")
        assert guard.check_tool("bash-child", "Bash")

    def test_check_tool_no_declarations_allows_all(self, guard, registry):
        registry.add(_make_entry("open-skill", tools=[]))
        assert guard.check_tool("open-skill", "AnythingAtAll")

    def test_check_tool_unregistered_blocks(self, guard):
        assert not guard.check_tool("ghost", "Read")

    def test_signature_normalizes_legacy_zip_mojibake_paths(self, tmp_path):
        normal = tmp_path / "normal"
        mojibake = tmp_path / "mojibake"
        (normal / "references").mkdir(parents=True)
        (mojibake / "references").mkdir(parents=True)
        (normal / "references" / "常用查询模板.md").write_text("select 1", encoding="utf-8")
        (mojibake / "references" / "σ╕╕τö¿µƒÑΦ»óµ¿íµ¥┐.md").write_text("select 1", encoding="utf-8")

        assert compute_signature(normal) == compute_signature(mojibake)

    def test_signature_ignores_runtime_cache_dirs(self, tmp_path):
        skill_dir = tmp_path / "skill"
        (skill_dir / "scripts" / "__pycache__").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: cache-test\n---\n", encoding="utf-8")
        before = compute_signature(skill_dir)
        (skill_dir / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"cache")

        assert compute_signature(skill_dir) == before

    def test_get_loadable_skills(self, guard, registry):
        registry.add(_make_entry("a", SkillStatus.APPROVED))
        registry.add(_make_entry("b", SkillStatus.DEPLOYED))
        registry.add(_make_entry("c", SkillStatus.VETTED))
        loadable = guard.get_loadable_skills()
        names = {e.name for e in loadable}
        assert names == {"a", "b"}

    def test_audit_logged_on_load(self, guard, registry, tmp_path):
        registry.add(_make_entry("logged-skill"))
        guard.can_load("logged-skill", verify_sig=False)
        events = registry.read_audit()
        event_types = {e.event_type for e in events}
        assert "skill_load_allowed" in event_types

    def test_audit_logged_on_block(self, guard, registry):
        guard.can_load("nonexistent", verify_sig=False)
        events = registry.read_audit()
        event_types = {e.event_type for e in events}
        assert "skill_load_blocked" in event_types
