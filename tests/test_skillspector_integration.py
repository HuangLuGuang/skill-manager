"""Tests for optional SkillSpector scanner integration."""

from __future__ import annotations

import json
import subprocess
import textwrap

from agent_manager.core.models import RiskLevel, SkillOrigin, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.scan_cache import compute_scan_context_fingerprint
from agent_manager.core.vetting import VettingPipeline


def _skill_dir(tmp_path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: suspicious-sync
        description: Sync helper
        license: MIT
        allowed-tools: Read
        ---

        # Suspicious Sync
    """), encoding="utf-8")
    return skill_dir


def test_skillspector_unavailable_is_recorded_without_blocking_scan(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)

    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: None)

    result, _violations, _name, _desc, _tools = VettingPipeline(
        CompanyPolicy({"skillspector_enabled": True})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL))

    assert result.risk_level == RiskLevel.BENIGN
    assert "skillspector:unavailable" in result.analyzers_used
    assert result.scan_report["skillspector_analysis"]["available"] is False
    assert any("SkillSpector unavailable" in note for note in result.policy_notes)


def test_skillspector_json_findings_are_merged_into_vetting(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {
        "risk_score": 78,
        "risk_severity": "HIGH",
        "risk_recommendation": "DO_NOT_INSTALL",
        "filtered_findings": [
            {
                "rule_id": "E2",
                "message": "Env Variable Harvesting",
                "severity": "HIGH",
                "confidence": 94,
                "file": "scripts/sync.py",
                "start_line": 23,
                "category": "Data Exfiltration",
                "pattern": "Env Variable Harvesting",
                "finding": "os.environ is collected",
                "explanation": "Collects environment variables.",
                "remediation": "Avoid reading secrets.",
                "code_snippet": "for key, val in os.environ.items():",
            }
        ],
    }

    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: "/usr/bin/skillspector")
    monkeypatch.setattr("agent_manager.core.skillspector.get_skillspector_version", lambda: "2.0.0")

    def fake_run(cmd, *, capture_output, text, timeout, check):
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_manager.core.skillspector.subprocess.run", fake_run)

    result, _violations, _name, _desc, _tools = VettingPipeline(
        CompanyPolicy({"skillspector_enabled": True})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL))

    assert result.risk_level == RiskLevel.MALICIOUS
    assert "skillspector:cli" in result.analyzers_used
    assert result.scan_report["skillspector_analysis"]["risk_score"] == 78
    assert result.scan_report["max_severity"] == "HIGH"
    finding = next(item for item in result.scan_report["findings"] if item["source"] == "skillspector")
    assert finding["rule"] == "E2"
    assert finding["category"] == "Data Exfiltration"
    assert finding["line"] == 23
    assert finding["remediation"] == "Avoid reading secrets."


def test_skillspector_v223_report_is_normalized(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {
        "risk_assessment": {
            "score": 50,
            "severity": "MEDIUM",
            "recommendation": "CAUTION",
        },
        "issues": [
            {
                "id": "P1",
                "category": "Prompt Injection",
                "pattern": "Instruction Override",
                "severity": "HIGH",
                "confidence": 0.8,
                "location": {"file": "SKILL.md", "start_line": 9, "end_line": None},
                "finding": "Ignore all previous instructions",
                "explanation": "Attempts to override system instructions.",
                "remediation": "Remove the override instruction.",
            }
        ],
    }

    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: "/usr/bin/skillspector")
    monkeypatch.setattr("agent_manager.core.skillspector.get_skillspector_version", lambda: "SkillSpector v2.2.3")

    def fake_run(cmd, *, capture_output, text, timeout, check):
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_manager.core.skillspector.subprocess.run", fake_run)

    result, _violations, _name, _desc, _tools = VettingPipeline(
        CompanyPolicy({"skillspector_enabled": True})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL))

    analysis = result.scan_report["skillspector_analysis"]
    assert analysis["risk_score"] == 50
    assert analysis["risk_severity"] == "MEDIUM"
    assert analysis["risk_recommendation"] == "CAUTION"
    assert analysis["max_severity"] == "HIGH"
    assert analysis["findings"] == [
        {
            "severity": "HIGH",
            "title": "Instruction Override",
            "message": "Ignore all previous instructions",
            "file": "SKILL.md",
            "source": "skillspector",
            "rule": "P1",
            "rule_id": "P1",
            "category": "Prompt Injection",
            "confidence": 0.8,
            "finding": "Ignore all previous instructions",
            "explanation": "Attempts to override system instructions.",
            "remediation": "Remove the override instruction.",
            "code_snippet": None,
            "line": 9,
        }
    ]


def test_skillspector_invalid_json_records_error_without_blocking_scan(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)

    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: "/usr/bin/skillspector")
    monkeypatch.setattr("agent_manager.core.skillspector.get_skillspector_version", lambda: "2.0.0")

    def fake_run(cmd, *, capture_output, text, timeout, check):
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write("{not-json")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_manager.core.skillspector.subprocess.run", fake_run)

    result, _violations, _name, _desc, _tools = VettingPipeline(
        CompanyPolicy({"skillspector_enabled": True})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL))

    assert result.risk_level == RiskLevel.BENIGN
    assert "skillspector:error" in result.analyzers_used
    assert "error" in result.scan_report["skillspector_analysis"]


def test_scan_context_changes_when_skillspector_settings_change():
    disabled = compute_scan_context_fingerprint(
        CompanyPolicy({"skillspector_enabled": False}),
        use_behavioral=False,
        use_llm=False,
        use_sandbox=False,
    )
    enabled = compute_scan_context_fingerprint(
        CompanyPolicy({"skillspector_enabled": True}),
        use_behavioral=False,
        use_llm=False,
        use_sandbox=False,
    )

    assert disabled != enabled
