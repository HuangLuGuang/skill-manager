"""Tests for the Claude Code agent hook."""

import json
import os
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

from agent_manager.core.models import (
    RegistryEntry,
    RiskLevel,
    SkillOrigin,
    SkillStatus,
    SourceInfo,
)
from agent_manager.core.registry import Registry
from agent_manager.hooks.agent_hook import (
    _extract_name,
    handle_config_change,
    handle_pre_tool_use,
    handle_session_start,
)


def _make_skill_dir(tmp_path: Path, name: str, tools: list[str] | None = None) -> Path:
    d = tmp_path / name
    d.mkdir()
    tools_line = f"allowed-tools: {', '.join(tools)}" if tools else ""
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: Test skill
        license: MIT
        {tools_line}
        ---
        # {name}
    """))
    return d


def _make_entry(registry: Registry, name: str, status=SkillStatus.DEPLOYED, tools=None):
    entry = RegistryEntry(
        skill_id=f"id-{name}",
        name=name,
        description="Test",
        source=SourceInfo(origin=SkillOrigin.LOCAL),
        status=status,
        risk_level=RiskLevel.BENIGN,
        allowed_tools=tools or [],
    )
    registry.add(entry)
    return entry


@pytest.fixture
def registry(tmp_path):
    return Registry(data_dir=tmp_path / "registry")


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    return d


# --------------------------------------------------------------------------- #
# _extract_name                                                                 #
# --------------------------------------------------------------------------- #

class TestExtractName:
    def test_reads_name_from_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: my-skill\ndescription: d\n---\n")
        assert _extract_name(skill_md) == "my-skill"

    def test_returns_none_for_missing_file(self, tmp_path):
        assert _extract_name(tmp_path / "SKILL.md") is None

    def test_returns_none_for_missing_name(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\ndescription: no name here\n---\n")
        assert _extract_name(skill_md) is None


# --------------------------------------------------------------------------- #
# handle_session_start                                                          #
# --------------------------------------------------------------------------- #

class TestSessionStart:
    def test_allows_session_with_all_registered_skills(self, registry, skills_dir, tmp_path):
        _make_skill_dir(skills_dir, "skill-a")
        _make_entry(registry, "skill-a")

        event = {"hook_event_name": "SessionStart", "cwd": str(tmp_path)}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch.dict(os.environ, {"AGENT_MANAGER_SKILLS_DIR": str(skills_dir)}):
            # Should not raise SystemExit
            handle_session_start(event)

    def test_blocks_session_with_unregistered_skill(self, registry, skills_dir, tmp_path):
        _make_skill_dir(skills_dir, "unregistered-skill")
        # Do NOT add to registry

        event = {"hook_event_name": "SessionStart", "cwd": str(tmp_path)}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch.dict(os.environ, {"AGENT_MANAGER_SKILLS_DIR": str(skills_dir)}):
            with pytest.raises(SystemExit) as exc:
                handle_session_start(event)
            assert exc.value.code == 2

    def test_blocks_session_with_retired_skill(self, registry, skills_dir, tmp_path):
        _make_skill_dir(skills_dir, "retired-skill")
        _make_entry(registry, "retired-skill", status=SkillStatus.RETIRED)

        event = {"hook_event_name": "SessionStart", "cwd": str(tmp_path)}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch.dict(os.environ, {"AGENT_MANAGER_SKILLS_DIR": str(skills_dir)}):
            with pytest.raises(SystemExit) as exc:
                handle_session_start(event)
            assert exc.value.code == 2

    def test_empty_skills_dir_allows_session(self, registry, skills_dir, tmp_path):
        event = {"hook_event_name": "SessionStart", "cwd": str(tmp_path)}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch.dict(os.environ, {"AGENT_MANAGER_SKILLS_DIR": str(skills_dir)}):
            handle_session_start(event)  # Should not raise


# --------------------------------------------------------------------------- #
# handle_config_change                                                          #
# --------------------------------------------------------------------------- #

class TestConfigChange:
    def test_allows_registered_skill(self, registry, tmp_path):
        skill_dir = _make_skill_dir(tmp_path, "good-skill")
        _make_entry(registry, "good-skill")

        event = {
            "hook_event_name": "ConfigChange",
            "source": "skills",
            "file_path": str(skill_dir / "SKILL.md"),
        }

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry):
            handle_config_change(event)  # No exception

    def test_blocks_unregistered_skill(self, registry, tmp_path):
        skill_dir = _make_skill_dir(tmp_path, "bad-skill")
        # NOT in registry

        event = {
            "hook_event_name": "ConfigChange",
            "source": "skills",
            "file_path": str(skill_dir / "SKILL.md"),
        }

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry):
            with pytest.raises(SystemExit) as exc:
                handle_config_change(event)
            assert exc.value.code == 2

    def test_blocks_vetted_skill(self, registry, tmp_path):
        skill_dir = _make_skill_dir(tmp_path, "vetted-skill")
        _make_entry(registry, "vetted-skill", status=SkillStatus.VETTED)

        event = {
            "hook_event_name": "ConfigChange",
            "source": "skills",
            "file_path": str(skill_dir / "SKILL.md"),
        }

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry):
            with pytest.raises(SystemExit) as exc:
                handle_config_change(event)
            assert exc.value.code == 2

    def test_ignores_non_skill_md(self, registry, tmp_path):
        event = {
            "hook_event_name": "ConfigChange",
            "source": "skills",
            "file_path": str(tmp_path / "CLAUDE.md"),
        }

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry):
            handle_config_change(event)  # Should not raise or block

    def test_blocks_tampered_skill(self, registry, tmp_path):
        from agent_manager.core.signer import compute_signature

        skill_dir = _make_skill_dir(tmp_path, "tampered")
        sig = compute_signature(skill_dir)

        # Now tamper
        (skill_dir / "SKILL.md").write_text("---\nname: tampered\ndescription: INJECTED\n---\n")

        entry = _make_entry(registry, "tampered")
        entry.signature = sig
        registry.update(entry)

        event = {
            "hook_event_name": "ConfigChange",
            "source": "skills",
            "file_path": str(skill_dir / "SKILL.md"),
        }

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry):
            with pytest.raises(SystemExit) as exc:
                handle_config_change(event)
            assert exc.value.code == 2


# --------------------------------------------------------------------------- #
# handle_pre_tool_use                                                           #
# --------------------------------------------------------------------------- #

class TestPreToolUse:
    def test_allows_declared_tool(self, registry):
        _make_entry(registry, "my-skill", tools=["Read", "Grep"])

        event = {"hook_event_name": "PreToolUse", "tool_name": "Read", "session_id": "s1"}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch("agent_manager.hooks.agent_hook._get_active_skills_from_state", return_value=["my-skill"]):
            handle_pre_tool_use(event)  # No exception

    def test_blocks_undeclared_tool(self, registry):
        _make_entry(registry, "read-only", tools=["Read", "Grep"])

        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s1"}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch("agent_manager.hooks.agent_hook._get_active_skills_from_state", return_value=["read-only"]):
            with pytest.raises(SystemExit) as exc:
                handle_pre_tool_use(event)
            assert exc.value.code == 2

    def test_allows_all_tools_when_no_active_skills(self, registry):
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s1"}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch("agent_manager.hooks.agent_hook._get_active_skills_from_state", return_value=[]):
            handle_pre_tool_use(event)  # No exception

    def test_blocks_all_tools_when_skill_has_no_declarations(self, registry):
        _make_entry(registry, "open-skill", tools=[])

        event = {"hook_event_name": "PreToolUse", "tool_name": "AnythingAtAll", "session_id": "s1"}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch("agent_manager.hooks.agent_hook._get_active_skills_from_state", return_value=["open-skill"]):
            with pytest.raises(SystemExit) as exc:
                handle_pre_tool_use(event)
            assert exc.value.code == 2

    def test_union_of_tools_for_multiple_active_skills(self, registry):
        _make_entry(registry, "skill-a", tools=["Read"])
        _make_entry(registry, "skill-b", tools=["Grep"])

        event = {"hook_event_name": "PreToolUse", "tool_name": "Grep", "session_id": "s1"}

        # Both active → union is {Read, Grep} → Grep is allowed
        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch("agent_manager.hooks.agent_hook._get_active_skills_from_state", return_value=["skill-a", "skill-b"]):
            handle_pre_tool_use(event)  # No exception

    def test_blocks_tool_not_in_any_active_skills(self, registry):
        _make_entry(registry, "skill-a", tools=["Read"])
        _make_entry(registry, "skill-b", tools=["Grep"])

        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s1"}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch("agent_manager.hooks.agent_hook._get_active_skills_from_state", return_value=["skill-a", "skill-b"]):
            with pytest.raises(SystemExit) as exc:
                handle_pre_tool_use(event)
            assert exc.value.code == 2

    def test_blocks_when_skill_retired_mid_session(self, registry):
        _make_entry(registry, "live-skill", status=SkillStatus.RETIRED, tools=["Read"])

        event = {"hook_event_name": "PreToolUse", "tool_name": "Read", "session_id": "s1"}

        with mock.patch("agent_manager.hooks.agent_hook._get_registry", return_value=registry), \
             mock.patch("agent_manager.hooks.agent_hook._get_active_skills_from_state", return_value=["live-skill"]):
            with pytest.raises(SystemExit) as exc:
                handle_pre_tool_use(event)
            assert exc.value.code == 2
