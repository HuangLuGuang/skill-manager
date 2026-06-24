"""Tests for the vetting pipeline and policy enforcement."""

import textwrap
import sys
import types
from pathlib import Path

import pytest

from agent_manager.core.models import RiskLevel, SkillOrigin, SkillStatus, SourceInfo
from agent_manager.core.llm import LLMAnalysisResult, LLMConfig
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.sandbox import SandboxConfig, SandboxResult
from agent_manager.core.vetting import (
    VettingPipeline,
    _check_manifest_policy,
    _llm_probe_args_safe,
    _load_manifest,
    _normalize_llm_probe_entrypoint,
    _run_scanner,
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

    def test_load_manifest_falls_back_when_frontmatter_parser_fails(self, tmp_path, monkeypatch):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(textwrap.dedent("""\
            ---
            name: research-logger
            description: AI research pipeline with automatic logging
            license: MIT
            metadata: {"openclaw": {"emoji": "\\ud83d\\udcdd"}}
            ---
        """))

        fake_frontmatter = types.SimpleNamespace(load=lambda _path: (_ for _ in ()).throw(RuntimeError("bad yaml")))
        monkeypatch.setitem(sys.modules, "frontmatter", fake_frontmatter)

        name, desc, tools, lic = _load_manifest(tmp_path)

        assert name == "research-logger"
        assert desc == "AI research pipeline with automatic logging"
        assert tools == []
        assert lic == "MIT"

    def test_load_manifest_tolerates_non_utf8_bytes(self, tmp_path, monkeypatch):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_bytes(
            b"---\n"
            b"name: latin-skill\n"
            b"description: bad byte \x97 should not abort parsing\n"
            b"license: MIT\n"
            b"allowed-tools: Read\n"
            b"---\n"
        )

        fake_frontmatter = types.SimpleNamespace(load=lambda _path: (_ for _ in ()).throw(UnicodeDecodeError("utf-8", b"\x97", 0, 1, "bad byte")))
        monkeypatch.setitem(sys.modules, "frontmatter", fake_frontmatter)

        name, desc, tools, lic = _load_manifest(tmp_path)

        assert name == "latin-skill"
        assert "bad byte" in desc
        assert tools == ["Read"]
        assert lic == "MIT"

    def test_load_manifest_uses_markdown_h1_without_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_bytes(
            b"# Social Media Marketing & Lead Generation Specialist\r\n"
            b"\r\n"
            b"Overview with Windows dash \x97 still decodes.\r\n"
        )

        name, desc, tools, lic = _load_manifest(tmp_path)

        assert name == "Social Media Marketing & Lead Generation Specialist"
        assert desc == ""
        assert tools == []
        assert lic is None

    def test_missing_skill_md_raises(self, tmp_path):
        with pytest.raises(ValueError, match="SKILL.md not found"):
            _load_manifest(tmp_path)


class TestScannerIntegration:
    def test_run_scanner_error_does_not_abort_pipeline(self, tmp_path, monkeypatch):
        class BrokenScanner:
            def __init__(self, policy):
                self.policy = policy

            def scan_skill(self, _path):
                raise RuntimeError("bad frontmatter")

        class FakePolicy:
            @staticmethod
            def from_preset(_name):
                return object()

            @staticmethod
            def default():
                return object()

        monkeypatch.setattr("agent_manager.core.vetting._try_import_scanner", lambda: (BrokenScanner, FakePolicy))

        report = _run_scanner(tmp_path, "default")

        assert report["analyzers_used"] == ["scanner:error"]
        assert report["scanner_error"] == "bad frontmatter"


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
    def test_auto_approve_benign(self):
        policy = CompanyPolicy.default()
        status = policy.decide(RiskLevel("benign"), [])
        assert status == SkillStatus.APPROVED

    def test_suspicious_queued(self):
        policy = CompanyPolicy.default()
        status = policy.decide(RiskLevel("suspicious"), [])    
        assert status == SkillStatus.VETTED

    def test_malicious_rejected(self):
        policy = CompanyPolicy.default()
        status = policy.decide(RiskLevel("malicious"), [])
        assert status == SkillStatus.REJECTED

    def test_blocking_violation_rejects(self):
        from agent_manager.core.models import PolicyViolation
        policy = CompanyPolicy.default()
        violations = [PolicyViolation(rule="blocked_permission", message="no", blocking=True)]
        status = policy.decide("benign", violations)
        assert status == SkillStatus.REJECTED

    def test_legacy_high_severity_auto_rejects_malicious(self):
        policy = CompanyPolicy({
            "auto_reject_risk": ["HIGH", "EXTREME"],
            "require_human_review": ["MEDIUM"],
        })

        assert policy.decide(RiskLevel.MALICIOUS, []) == SkillStatus.REJECTED

    def test_legacy_medium_severity_queues_suspicious_for_review(self):
        policy = CompanyPolicy({
            "auto_reject_risk": ["HIGH", "EXTREME"],
            "require_human_review": ["LOW", "MEDIUM"],
        })

        assert policy.decide(RiskLevel.SUSPICIOUS, []) == SkillStatus.VETTED

    def test_invalid_policy_values_never_default_malicious_to_approved(self):
        policy = CompanyPolicy({
            "auto_reject_risk": ["TYPO"],
            "require_human_review": ["UNKNOWN"],
        })

        assert policy.decide(RiskLevel.MALICIOUS, []) == SkillStatus.REJECTED


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
        assert result.risk_level == RiskLevel.MALICIOUS

    def test_low_analyzability_does_not_raise_risk(self, skill_dir, monkeypatch):
        monkeypatch.setattr(
            "agent_manager.core.vetting._run_scanner",
            lambda _path, _policy: {
                "max_severity": "MEDIUM",
                "findings": [{
                    "rule": "LOW_ANALYZABILITY",
                    "severity": "MEDIUM",
                    "title": "可分析性不足",
                    "message": "部分内容无法确认安全。",
                    "source": "scanner",
                }],
                "analyzers_used": ["scanner"],
            },
        )

        result, _violations, _name, _desc, _tools = VettingPipeline(
            CompanyPolicy({"require_sandbox_for_risk": []})
        ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL))

        assert result.risk_level == RiskLevel.BENIGN
        assert result.scan_report["max_severity"] == "MEDIUM"
        assert result.scan_report["risk_max_severity"] == "SAFE"
        assert result.scan_report["findings"][0]["rule"] == "LOW_ANALYZABILITY"

    def test_high_analyzability_failure_still_raises_risk(self, skill_dir, monkeypatch):
        monkeypatch.setattr(
            "agent_manager.core.vetting._run_scanner",
            lambda _path, _policy: {
                "max_severity": "HIGH",
                "findings": [{
                    "rule": "LOW_ANALYZABILITY",
                    "severity": "HIGH",
                    "title": "可分析性严重不足",
                    "message": "大量内容无法确认安全。",
                    "source": "scanner",
                }],
                "analyzers_used": ["scanner"],
            },
        )

        result, _violations, _name, _desc, _tools = VettingPipeline(
            CompanyPolicy({"require_sandbox_for_risk": []})
        ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL))

        assert result.risk_level == RiskLevel.MALICIOUS
        assert result.scan_report["risk_max_severity"] == "HIGH"

    def test_llm_cannot_downgrade_deterministic_scan_risk(self, skill_dir, monkeypatch):
        monkeypatch.setattr(
            "agent_manager.core.vetting._run_scanner",
            lambda _path, _policy: {
                "max_severity": "HIGH",
                "findings": [{"severity": "HIGH", "title": "Opaque binary", "source": "scanner"}],
                "analyzers_used": ["scanner"],
            },
        )
        monkeypatch.setattr(
            "agent_manager.core.vetting.LLMConfig.load",
            lambda: LLMConfig(enabled=True, api_key="test-key"),
        )
        monkeypatch.setattr(
            "agent_manager.core.vetting.analyze_skill_with_llm_single_round",
            lambda **_kwargs: LLMAnalysisResult(
                provider="test",
                model="test-model",
                risk_level="benign",
                report="Known test fixture.",
            ),
        )

        result, _violations, _name, _desc, _tools = VettingPipeline(
            CompanyPolicy({"require_sandbox_for_risk": []})
        ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_llm=True)

        assert result.risk_level == RiskLevel.MALICIOUS
        assert result.scan_report["risk_reconciliation"] == {
            "strategy": "conservative_max",
            "pre_llm_risk_level": "malicious",
            "llm_risk_level": "benign",
            "final_risk_level": "malicious",
            "llm_downgrade_blocked": True,
        }
        assert any("downgrade blocked" in note for note in result.policy_notes)

    def test_sandbox_flags_are_recorded(self, skill_dir, default_policy, monkeypatch):
        class FakeRunner:
            config = SandboxConfig(runtime="docker")

            def run_probe(self, skill_path, entrypoint, args=None):
                return SandboxResult(
                    executed=True,
                    runtime="docker",
                    entrypoint=entrypoint,
                    exit_code=0,
                )

        monkeypatch.setattr("agent_manager.core.vetting.get_sandbox_runner", lambda: FakeRunner())
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
        assert _llm_probe_args_safe(["--query", "select 1"]) is True
        assert _llm_probe_args_safe(["agent-browser", "open", "https://example.com", "&&", "agent-browser", "snapshot"]) is False

    def test_sandbox_skips_skill_md_command_examples_without_script_entrypoint(self, tmp_path, default_policy, monkeypatch):
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

        class FakeRunner:
            config = SandboxConfig(runtime="docker")

            def run_probe(self, skill_path, entrypoint, args=None):
                raise AssertionError("SKILL.md command examples should not be executed as sandbox probes")

        monkeypatch.setattr("agent_manager.core.vetting.get_sandbox_runner", lambda: FakeRunner())

        pipeline = VettingPipeline(default_policy)
        source = SourceInfo(origin=SkillOrigin.LOCAL)
        result, _violations, _name, _desc, _tools = pipeline.vet(skill_dir, source, use_sandbox=True)

        sandbox_analysis = result.scan_report["sandbox_analysis"]
        assert sandbox_analysis["executed"] is False
        assert "SKILL.md command examples are not executed" in sandbox_analysis["reason"]
