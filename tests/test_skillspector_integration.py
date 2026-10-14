"""Tests for optional SkillSpector scanner integration."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import textwrap
from types import SimpleNamespace
import urllib.request

import pytest

from agent_manager.core.llm import LLMConfig
from agent_manager.core.models import RiskLevel, SkillOrigin, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.scan_cache import compute_scan_context_fingerprint
from agent_manager.core.skillspector import get_suppressed_findings, run_skillspector_scan
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


@pytest.fixture(autouse=True)
def _disable_system_llm_by_default(monkeypatch):
    # These cases isolate SkillSpector findings from the independently optional Cisco scanner.
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {})
    monkeypatch.setattr(
        "agent_manager.core.vetting.LLMConfig.load",
        lambda: LLMConfig(enabled=False),
    )


def test_skillspector_unavailable_is_recorded_without_blocking_scan(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)

    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: None)

    result, _violations, _name, _desc, _tools = VettingPipeline(
        CompanyPolicy({"skillspector_enabled": True})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    assert result.risk_level == RiskLevel.BENIGN
    assert "skillspector:unavailable" in result.analyzers_used
    assert result.scan_report["skillspector_analysis"]["available"] is False
    assert any("深度扫描不可用" in note for note in result.policy_notes)


@pytest.mark.parametrize("policy_options, expected_risk", [
    ({}, RiskLevel.SUSPICIOUS),
    ({"judgement_mode": "strict"}, RiskLevel.MALICIOUS),
    ({"risk_classification": {"data_exfiltration": "blocking"}}, RiskLevel.MALICIOUS),
])
def test_skillspector_json_findings_are_merged_into_vetting(tmp_path, monkeypatch, policy_options, expected_risk):
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
        CompanyPolicy({"skillspector_enabled": True, **policy_options})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    assert result.risk_level == expected_risk
    assert "skillspector:cli" in result.analyzers_used
    assert result.scan_report["skillspector_analysis"]["risk_score"] == 78
    assert result.scan_report["max_severity"] == "HIGH"
    finding = next(item for item in result.scan_report["findings"] if item.get("source") == "skillspector")
    assert finding["rule"] == "E2"
    assert finding["category"] == "Data Exfiltration"
    assert finding["line"] == 23
    assert finding["remediation"] == "Avoid reading secrets."


def test_skillspector_filters_license_and_font_noise(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {
        "risk_score": 100,
        "risk_severity": "CRITICAL",
        "risk_recommendation": "DO_NOT_INSTALL",
        "filtered_findings": [
            {"rule_id": "EA3", "message": "not limited to", "severity": "LOW", "file": "LICENSE.txt"},
            {"rule_id": "MP2", "message": "binary noise", "severity": "MEDIUM", "file": "fonts/demo.ttf"},
            {"rule_id": "E2", "message": "Env Variable Harvesting", "severity": "HIGH", "file": "scripts/sync.py"},
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
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert analysis["risk_severity"] == "HIGH"
    assert analysis["effective_risk_severity"] == "HIGH"
    assert analysis["raw_risk_severity"] == "CRITICAL"
    assert analysis["suppressed_findings_count"] == 2
    assert [finding["file"] for finding in analysis["findings"]] == ["scripts/sync.py"]


def test_skillspector_filters_raster_image_binary_noise(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    assets_dir = skill_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "cover.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 64
    )
    payload = {
        "risk_score": 100,
        "risk_severity": "CRITICAL",
        "risk_recommendation": "DO_NOT_INSTALL",
        "filtered_findings": [
            {
                "rule_id": "P2",
                "message": "\ufeff",
                "severity": "HIGH",
                "file": "assets/cover.png",
                "category": "Prompt Injection",
            },
            {
                "rule_id": "TM1",
                "message": "rm\ufffd\ufffd/",
                "severity": "HIGH",
                "file": "assets/cover.png",
                "category": "Tool Misuse",
            },
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
        CompanyPolicy({"skillspector_enabled": True, "require_sandbox_for_risk": []})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert result.risk_level == RiskLevel.BENIGN
    assert result.scan_report["risk_max_severity"] == "SAFE"
    assert analysis["raw_risk_severity"] == "CRITICAL"
    assert analysis["effective_risk_severity"] == "SAFE"
    assert analysis["risk_recommendation"] == "SAFE"
    assert analysis["findings"] == []
    assert analysis["suppressed_findings_count"] == 2


def test_skillspector_top_level_high_with_only_noise_requires_review(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {
        "risk_score": 100,
        "risk_severity": "CRITICAL",
        "risk_recommendation": "DO_NOT_INSTALL",
        "filtered_findings": [
            {"rule_id": "EA3", "message": "not limited to", "severity": "LOW", "file": "LICENSE.txt"},
            {"rule_id": "MP2", "message": "binary noise", "severity": "MEDIUM", "file": "fonts/demo.ttf"},
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
        CompanyPolicy({"skillspector_enabled": True, "require_sandbox_for_risk": []})
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert result.risk_level == RiskLevel.BENIGN
    assert result.scan_report["risk_max_severity"] == "MEDIUM"
    assert analysis["risk_score"] == 100
    assert analysis["raw_risk_severity"] == "CRITICAL"
    assert analysis["effective_risk_severity"] == "MEDIUM"
    assert analysis["risk_recommendation"] == "CAUTION"
    assert analysis["findings"] == []
    assert analysis["suppressed_findings_count"] == 2


def test_vetting_keeps_skillspector_llm_disabled_even_when_policy_requests_it(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {"risk_assessment": {"score": 0, "severity": "LOW", "recommendation": "SAFE"}, "issues": []}
    captured = {}

    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: "/usr/bin/skillspector")
    monkeypatch.setattr("agent_manager.core.skillspector.get_skillspector_version", lambda: "SkillSpector v2.2.3")

    def fake_run(cmd, *, capture_output, text, timeout, check, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_manager.core.skillspector.subprocess.run", fake_run)
    ready_llm_config = LLMConfig(
        enabled=True,
        provider="deepseek",
        api_base="https://api.deepseek.com",
        api_key="secret",
        model="deepseek-chat",
    )
    monkeypatch.setattr("agent_manager.core.vetting.LLMConfig.load", lambda: ready_llm_config)
    monkeypatch.setattr("agent_manager.core.skillspector.LLMConfig.load", lambda: ready_llm_config)

    result, _violations, _name, _desc, _tools = VettingPipeline(CompanyPolicy({
        "skillspector_enabled": True,
        "skillspector_use_llm": True,
    })).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert "--no-llm" in captured["cmd"]
    assert captured["env"] is None
    assert analysis["llm_requested"] is False
    assert analysis["llm_enabled"] is False


def test_vetting_does_not_start_internal_model_gateway_proxy_for_skillspector(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {"risk_assessment": {"score": 0, "severity": "LOW", "recommendation": "SAFE"}, "issues": []}
    captured = {}

    monkeypatch.delenv("AGENT_MANAGER_LLM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("AGENT_MANAGER_LLM_GATEWAY_API_KEY", raising=False)
    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: "/usr/bin/skillspector")
    monkeypatch.setattr("agent_manager.core.skillspector.get_skillspector_version", lambda: "SkillSpector v2.2.3")

    def fake_run(cmd, *, capture_output, text, timeout, check, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_manager.core.skillspector.subprocess.run", fake_run)
    ready_llm_config = LLMConfig(
        enabled=True,
        provider="model-gateway",
        api_base="",
        api_key=None,
        model="deepseek-chat",
    )
    monkeypatch.setattr("agent_manager.core.vetting.LLMConfig.load", lambda: ready_llm_config)
    monkeypatch.setattr("agent_manager.core.skillspector.LLMConfig.load", lambda: ready_llm_config)

    result, _violations, _name, _desc, _tools = VettingPipeline(CompanyPolicy({
        "skillspector_enabled": True,
        "skillspector_use_llm": True,
    })).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert "--no-llm" in captured["cmd"]
    assert captured["env"] is None
    assert analysis["llm_requested"] is False
    assert analysis["llm_enabled"] is False
    assert analysis["llm_note"] is None
    assert "skillspector:error" not in result.analyzers_used


def test_vetting_ignores_external_gateway_env_for_skillspector(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {"risk_assessment": {"score": 0, "severity": "LOW", "recommendation": "SAFE"}, "issues": []}
    captured = {}

    monkeypatch.setenv("AGENT_MANAGER_LLM_GATEWAY_URL", "http://127.0.0.1:8001/v1/chat/completions")
    monkeypatch.setenv("AGENT_MANAGER_LLM_GATEWAY_API_KEY", "gateway-token")
    monkeypatch.setattr("agent_manager.core.skillspector.shutil.which", lambda _name: "/usr/bin/skillspector")
    monkeypatch.setattr("agent_manager.core.skillspector.get_skillspector_version", lambda: "SkillSpector v2.2.3")

    def fake_run(cmd, *, capture_output, text, timeout, check, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        output_path = cmd[cmd.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("agent_manager.core.skillspector.subprocess.run", fake_run)
    ready_llm_config = LLMConfig(
        enabled=True,
        provider="model-gateway",
        api_base="",
        api_key=None,
        model="deepseek-chat",
    )
    monkeypatch.setattr("agent_manager.core.vetting.LLMConfig.load", lambda: ready_llm_config)
    monkeypatch.setattr("agent_manager.core.skillspector.LLMConfig.load", lambda: ready_llm_config)

    result, _violations, _name, _desc, _tools = VettingPipeline(CompanyPolicy({
        "skillspector_enabled": True,
        "skillspector_use_llm": True,
    })).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert "--no-llm" in captured["cmd"]
    assert captured["env"] is None
    assert analysis["llm_requested"] is False
    assert analysis["llm_enabled"] is False


def test_internal_model_gateway_proxy_forwards_chat_completion(monkeypatch):
    from agent_manager.core.skillspector import _internal_model_gateway_proxy

    captured = {}

    def fake_call(payload):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("agent_manager.core.llm._call_model_gateway_sync", fake_call)
    config = LLMConfig(enabled=True, provider="model-gateway", model="deepseek-chat")

    with _internal_model_gateway_proxy(config) as env:
        req = urllib.request.Request(
            f"{env['OPENAI_BASE_URL']}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {env['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            body = json.loads(response.read().decode("utf-8"))

    assert captured["payload"]["model"] == "deepseek-chat"
    assert body["choices"][0]["message"]["content"] == "ok"


def test_internal_model_gateway_proxy_adapts_deepseek_json_schema(monkeypatch):
    from agent_manager.core.skillspector import _internal_model_gateway_proxy

    captured = {}

    def fake_call(payload):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": '{"risk":"safe"}'}}]}

    monkeypatch.setattr("agent_manager.core.llm._call_model_gateway_sync", fake_call)
    config = LLMConfig(enabled=True, provider="model-gateway", model="deepseek-v4-flash")
    schema = {
        "type": "object",
        "properties": {"risk": {"type": "string"}},
        "required": ["risk"],
    }

    with _internal_model_gateway_proxy(config) as env:
        req = urllib.request.Request(
            f"{env['OPENAI_BASE_URL']}/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": "analyze"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "risk_result", "strict": True, "schema": schema},
                },
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {env['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3):
            pass

    assert captured["payload"]["model"] == "deepseek-v4-flash"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert "JSON Schema" in captured["payload"]["messages"][0]["content"]
    assert '"risk"' in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["messages"][1] == {"role": "user", "content": "analyze"}


def test_deepseek_structured_output_adapter_leaves_other_models_unchanged():
    from agent_manager.core.skillspector import _adapt_deepseek_structured_output

    payload = {
        "model": "gpt-5.4",
        "messages": [{"role": "user", "content": "analyze"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": {"type": "object"}},
        },
    }

    assert _adapt_deepseek_structured_output(payload) is payload


def test_skillspector_safe_low_without_findings_stays_benign(tmp_path, monkeypatch):
    skill_dir = _skill_dir(tmp_path)
    payload = {
        "risk_assessment": {
            "score": 0,
            "severity": "LOW",
            "recommendation": "SAFE",
        },
        "issues": [],
        "metadata": {
            "has_executable_scripts": False,
        },
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
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert result.risk_level == RiskLevel.BENIGN
    assert result.scan_report["risk_max_severity"] == "SAFE"
    assert analysis["risk_score"] == 0
    assert analysis["raw_risk_severity"] == "LOW"
    assert analysis["effective_risk_severity"] == "SAFE"
    assert analysis["risk_recommendation"] == "SAFE"
    assert analysis["findings"] == []


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
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    analysis = result.scan_report["skillspector_analysis"]
    assert analysis["risk_score"] == 50
    assert analysis["risk_severity"] == "HIGH"
    assert analysis["risk_recommendation"] == "DO_NOT_INSTALL"
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
    ).vet(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL), use_skillspector=True)

    assert result.risk_level == RiskLevel.BENIGN
    assert "skillspector:error" in result.analyzers_used
    assert "error" in result.scan_report["skillspector_analysis"]


def test_scan_context_changes_when_deep_scan_option_changes():
    disabled = compute_scan_context_fingerprint(
        CompanyPolicy.default(),
        use_behavioral=False,
        use_llm=False,
        use_sandbox=False,
        use_skillspector=False,
    )
    enabled = compute_scan_context_fingerprint(
        CompanyPolicy.default(),
        use_behavioral=False,
        use_llm=False,
        use_sandbox=False,
        use_skillspector=True,
    )

    assert disabled != enabled


@pytest.mark.parametrize(
    "finding, reason",
    [
        ({"rule_id": "EA3", "message": "not limited to", "file": "LICENSE.txt", "start_line": 28}, "license_scope_wording"),
        ({"rule_id": "MP2", "file": "fonts/demo.ttf"}, "font_file"),
        ({"rule_id": "P2", "file": "assets/cover.png"}, "raster_image"),
    ],
)
def test_suppressed_details_match_scan_count(tmp_path, monkeypatch, finding, reason):
    payload = {"filtered_findings": [finding, {"rule_id": "E2", "file": "sync.py", "severity": "HIGH"}]}
    monkeypatch.setattr("agent_manager.core.skillspector._skillspector_executable", lambda: "/mock/skillspector")
    monkeypatch.setattr("agent_manager.core.skillspector.get_skillspector_version", lambda: "test")

    def fake_run(cmd, **_kwargs):
        Path(cmd[cmd.index("--output") + 1]).write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("agent_manager.core.skillspector.subprocess.run", fake_run)
    result = run_skillspector_scan(tmp_path)
    assert result["suppressed_findings_count"] == len(result["suppressed_findings"]) == 1
    detail = result["suppressed_findings"][0]
    assert detail["suppression_reason"] == reason
    assert detail["file"] == finding["file"]
    assert detail["line"] == finding.get("start_line")
    assert result["findings"][0]["file"] == "sync.py"
    assert result["max_severity"] == "HIGH"


@pytest.mark.parametrize("field", ["filtered_findings", "findings", "issues"])
def test_historical_suppressed_details_are_read_only(field):
    from agent_manager.api.router import get_scan_report

    report = {"skillspector_analysis": {
        "suppressed_findings_count": 1,
        "findings": [],
        "raw_report": {field: [{"rule_id": "EA3", "finding": "not limited to", "file": "LICENSE.txt", "start_line": 28}]},
    }}
    before = deepcopy(report)
    entry = SimpleNamespace(family_id="family", skill_id="version", version_no=1, name="sample", vetting=SimpleNamespace(scan_report=report))
    mgr = SimpleNamespace(get_skill=lambda _id: entry)
    result = get_scan_report("family", mgr)["scan_report"]["skillspector_analysis"]
    assert result["suppressed_findings"][0]["suppression_reason"] == "license_scope_wording"
    assert result["suppressed_findings"][0]["line"] == 28
    assert report == before


def test_noise_matching_keeps_code_and_nonmatching_license_findings():
    report = {"findings": [
        {"rule_id": "EA3", "message": "not limited to", "file": "script.py"},
        {"rule_id": "E2", "message": "not limited to", "file": "LICENSE.txt"},
        {"rule_id": "EA3", "message": "unrestricted", "file": "LICENSE.txt"},
    ]}
    assert get_suppressed_findings(report) == []


@pytest.mark.parametrize("analysis", [
    {"suppressed_findings_count": 4},
    {"suppressed_findings_count": 0, "raw_report": {}},
    {"suppressed_findings_count": 1, "suppressed_findings": [
        {"file": "old.png", "suppression_reason": "raster_image"},
    ], "raw_report": {}},
])
def test_report_preserves_recorded_noise_details_and_counts(analysis):
    from agent_manager.api.router import get_scan_report

    # 读取兼容仅补齐缺失明细，不覆盖已记录的过滤结果和统计。
    before = deepcopy(analysis)
    entry = SimpleNamespace(
        family_id="family", skill_id="version", version_no=1, name="sample",
        vetting=SimpleNamespace(scan_report={"skillspector_analysis": analysis}),
    )
    result = get_scan_report(
        "family", SimpleNamespace(get_skill=lambda _id: entry),
    )["scan_report"]["skillspector_analysis"]
    assert result["suppressed_findings_count"] == before["suppressed_findings_count"]
    if "suppressed_findings" in before:
        assert result["suppressed_findings"] == before["suppressed_findings"]
    assert analysis == before
