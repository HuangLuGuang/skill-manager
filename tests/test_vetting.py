"""Tests for the vetting pipeline and policy enforcement."""

import textwrap
from pathlib import Path

import pytest

from agent_manager.core.models import RiskLevel, SkillOrigin, SkillStatus, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.sandbox import SandboxConfig, SandboxResult
from agent_manager.core.vetting import (
    VettingPipeline,
    _check_manifest_policy,
    _load_manifest,
    _normalize_llm_probe_entrypoint,
)


@pytest.fixture
def skill_dir(tmp_path):
    """Create a minimal valid skill directory."""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(textwrap.dedent("""\
        ---
        name: test-skill
        description: A simple test skill
        license: MIT
        allowed-tools: Read, Grep
        ---

        # Test Skill

        This skill reads files.
    """))
    return tmp_path


@pytest.fixture
def default_policy():
    return CompanyPolicy.default()


class TestManifestLoading:
    def test_load_valid_manifest(self, skill_dir):
        name, desc, tools, lic = _load_manifest(skill_dir)
        assert name == "test-skill"
        assert "test" in desc.lower()
        assert tools == ["Read", "Grep"]
        assert lic == "MIT"

    def test_load_manifest_supports_yaml_list_allowed_tools_without_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
            ---
            name: yaml-list-skill
            description: YAML list test
            license: MIT
            allowed-tools:
              - Read
              - Bash
            ---
        """))

        name, desc, tools, lic = _load_manifest(tmp_path)

        assert name == "yaml-list-skill"
        assert desc == "YAML list test"
        assert tools == ["Read", "Bash"]
        assert lic == "MIT"

    def test_missing_skill_md_raises(self, tmp_path):
        with pytest.raises(ValueError, match="SKILL.md not found"):
            _load_manifest(tmp_path)


class TestPolicyChecks:
    def test_allowed_tools_pass(self):
        policy = CompanyPolicy.default()
        violations = _check_manifest_policy(["Read", "Grep"], "MIT", policy)
        # No violations for default policy with standard tools
        blocking = [v for v in violations if v.blocking]
        assert not blocking

    def test_blocked_permission(self):
        policy = CompanyPolicy({
            "blocked_permissions": ["read_credentials"],
            "allowed_tools_allowlist": ["read_credentials", "Read"],
        })
        violations = _check_manifest_policy(["read_credentials"], "MIT", policy)
        assert any(v.rule == "blocked_permission" for v in violations)

    def test_tool_not_in_allowlist(self):
        policy = CompanyPolicy({"allowed_tools_allowlist": ["Read"]})
        violations = _check_manifest_policy(["SomeDangerousTool"], "MIT", policy)
        assert any(v.rule == "tool_not_in_allowlist" for v in violations)

    def test_require_license_missing(self):
        policy = CompanyPolicy({"require_license": True})
        violations = _check_manifest_policy([], None, policy)
        assert any(v.rule == "require_license" for v in violations)

    def test_unaccepted_license(self):
        policy = CompanyPolicy({
            "require_license": True,
            "accepted_licenses": ["MIT"],
        })
        violations = _check_manifest_policy([], "GPL-3.0", policy)
        assert any(v.rule == "unaccepted_license" for v in violations)

    def test_max_tools_exceeded(self):
        policy = CompanyPolicy({
            "max_allowed_tools": 2,
            "allowed_tools_allowlist": ["A", "B", "C", "D"],
        })
        violations = _check_manifest_policy(["A", "B", "C"], "MIT", policy)
        assert any(v.rule == "max_allowed_tools" for v in violations)


class TestPolicyDecide:
    def test_auto_approve_low_risk(self):
        policy = CompanyPolicy.default()
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        status = policy.decide(RiskLevel.LOW, source, [])
        assert status == SkillStatus.APPROVED

    def test_medium_risk_queued(self):
        policy = CompanyPolicy({"auto_approve_max_risk": "LOW", "require_human_review": ["MEDIUM", "HIGH", "EXTREME"]})
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        status = policy.decide(RiskLevel.MEDIUM, source, [])
        assert status == SkillStatus.VETTED

    def test_extreme_risk_rejected(self):
        policy = CompanyPolicy.default()
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        status = policy.decide(RiskLevel.EXTREME, source, [])
        assert status == SkillStatus.REJECTED

    def test_blocking_violation_rejects(self):
        from agent_manager.core.models import PolicyViolation
        policy = CompanyPolicy.default()
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        violations = [PolicyViolation(rule="blocked_permission", message="no", blocking=True)]
        status = policy.decide(RiskLevel.LOW, source, violations)
        assert status == SkillStatus.REJECTED

    def test_trusted_author_medium_auto_approves(self):
        policy = CompanyPolicy({
            "auto_approve_max_risk": "LOW",
            "require_human_review": ["HIGH", "EXTREME"],
            "trusted_authors": ["trusted-vendor"],
        })
        source = SourceInfo(origin=SkillOrigin.GITHUB, author="trusted-vendor")
        status = policy.decide(RiskLevel.MEDIUM, source, [])
        assert status == SkillStatus.APPROVED


class TestVettingPipeline:
    def test_vet_valid_skill(self, skill_dir, default_policy):
        """End-to-end vet with skill-scanner absent (falls back to basic check)."""
        pipeline = VettingPipeline(default_policy)
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        result, violations, name, desc, tools = pipeline.vet(skill_dir, source)

        assert name == "test-skill"
        assert result.risk_level in RiskLevel.__members__.values()
        assert isinstance(violations, list)

    def test_vet_missing_skill_raises(self, tmp_path, default_policy):
        pipeline = VettingPipeline(default_policy)
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        with pytest.raises(ValueError):
            pipeline.vet(tmp_path / "nonexistent", source)

    def test_behavioral_analysis_disabled_by_default(self, skill_dir, default_policy):
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text(
            "import subprocess\nsubprocess.run('rm -rf /tmp/demo', shell=True)\n",
            encoding="utf-8",
        )

        pipeline = VettingPipeline(default_policy)
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        result, _violations, _name, _desc, _tools = pipeline.vet(skill_dir, source, use_behavioral=False)

        assert "behavioral:local" not in result.analyzers_used
        assert "behavioral_analysis" not in result.scan_report

    def test_behavioral_analysis_finds_script_patterns(self, skill_dir, default_policy):
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text(
            "import os\nimport subprocess\n"
            "subprocess.run('cat ~/.aws/credentials', shell=True)\n"
            "os.system('echo hi')\n",
            encoding="utf-8",
        )

        pipeline = VettingPipeline(default_policy)
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        result, _violations, _name, _desc, _tools = pipeline.vet(skill_dir, source, use_behavioral=True)

        assert "behavioral:local" in result.analyzers_used
        assert result.scan_report["behavioral_analysis"]["scanned_file_count"] >= 1
        assert any(f["source"] == "behavioral" for f in result.scan_report["findings"])
        assert result.risk_level in (RiskLevel.HIGH, RiskLevel.EXTREME)

    def test_sandbox_flags_are_recorded(self, skill_dir, default_policy):
        pipeline = VettingPipeline(default_policy)
        source = SourceInfo(origin=SkillOrigin.LOCAL)

        result, _violations, _name, _desc, _tools = pipeline.vet(skill_dir, source, use_sandbox=True)

        assert result.sandbox_triggered is True
        assert result.sandbox_required_by_policy is False
        assert result.sandbox_runtime == "docker"
        assert "sandbox_analysis" in result.scan_report

    def test_llm_probe_entrypoint_must_be_existing_supported_file(self, skill_dir):
        tools_dir = skill_dir / "tools"
        tools_dir.mkdir()
        (tools_dir / "check.py").write_text("print('ok')\n", encoding="utf-8")
        (tools_dir / "data.txt").write_text("text\n", encoding="utf-8")

        assert _normalize_llm_probe_entrypoint(skill_dir, "tools/check.py", "tools/check.py") == "tools/check.py"
        assert _normalize_llm_probe_entrypoint(skill_dir, None, "tools/check.py") == "tools/check.py"
        assert _normalize_llm_probe_entrypoint(skill_dir, "../escape.py", "tools/check.py") is None
        assert _normalize_llm_probe_entrypoint(skill_dir, "tools/data.txt", "tools/check.py") is None
        assert _normalize_llm_probe_entrypoint(skill_dir, "missing.py", "tools/check.py") is None

    def test_sandbox_runs_skill_md_command_probe_without_script_entrypoint(self, tmp_path, default_policy, monkeypatch):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: markdown-only
            description: d
            ---

            ```bash
            clawdbot --version
            ```
        """), encoding="utf-8")
        captured = {}

        class FakeRunner:
            config = SandboxConfig(runtime="docker")

            def run_probe(self, skill_path, entrypoint, args=None):
                captured["skill_path"] = str(skill_path)
                captured["entrypoint"] = entrypoint
                captured["args"] = args or []
                return SandboxResult(
                    executed=True,
                    runtime="docker",
                    entrypoint=entrypoint,
                    exit_code=127,
                    stderr="sh: clawdbot: not found",
                )

        monkeypatch.setattr("agent_manager.core.vetting.get_sandbox_runner", lambda: FakeRunner())

        pipeline = VettingPipeline(default_policy)
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        result, _violations, _name, _desc, _tools = pipeline.vet(skill_dir, source, use_sandbox=True)

        assert captured["entrypoint"].startswith(".agent-manager-sandbox-probes/")
        assert result.scan_report["sandbox_analysis"]["probe_cases"][0]["generated_by"] == "skill-md"
        assert result.scan_report["sandbox_analysis"]["probe_results"][0]["probe_entrypoint"] == captured["entrypoint"]
