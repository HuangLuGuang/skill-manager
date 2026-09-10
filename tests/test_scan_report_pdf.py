"""Tests for branded PDF exports of Skill scan results."""

from __future__ import annotations

import re
import textwrap
from datetime import datetime, timezone
from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import (
    AuditEvent,
    RegistryEntry,
    RiskLevel,
    ScanRun,
    SkillOrigin,
    SkillStatus,
    SourceInfo,
    VettingResult,
)
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.scan_report_pdf import _analyzer_rows, build_scan_report_pdf


def _entry() -> RegistryEntry:
    now = datetime(2026, 8, 20, 2, 30, tzinfo=timezone.utc)
    return RegistryEntry(
        skill_id="12345678-1234-5678-1234-567812345678",
        family_id="87654321-4321-8765-4321-876543218765",
        version_no=3,
        name="security-review-skill",
        description="Reviews source code for security findings.",
        source=SourceInfo(
            origin=SkillOrigin.GITHUB,
            author="Security Team",
            channel="github",
            url="https://example.test/skill?token=must-not-leak",
            commit_sha="abc123",
        ),
        status=SkillStatus.VETTED,
        risk_level=RiskLevel.SUSPICIOUS,
        allowed_tools=["Read", "Grep"],
        content_fingerprint="sha256:content",
        scan_context_fingerprint="sha256:context",
        submitted_at=now,
        updated_at=now,
        vetting=VettingResult(
            risk_level=RiskLevel.SUSPICIOUS,
            findings_count=2,
            analyzers_used=["basic", "behavioral:local", "sandbox:docker", "llm:openai"],
            sandbox_triggered=True,
            sandbox_required_by_policy=True,
            sandbox_runtime="docker",
            scan_duration_seconds=4.2,
            vetted_at=now,
            policy_notes=["[WARN] manual_review: Human review required"],
            scan_report={
                "risk_level": "suspicious",
                "pre_llm_risk_level": "suspicious",
                "max_severity": "HIGH",
                "judgement_mode": "balanced",
                "execution_strategy": "parallel_analyzers_single_reconciliation",
                "scan_duration_seconds": 4.2,
                "analyzer_timings": {
                    "scanner": {"status": "completed", "duration_seconds": 0.4},
                    "behavioral": {"status": "completed", "duration_seconds": 0.8},
                    "sandbox": {"status": "completed", "duration_seconds": 1.4},
                    "llm": {"status": "completed", "duration_seconds": 1.6},
                },
                "risk_classification": {"blocking_count": 0},
                "risk_reconciliation": {
                    "strategy": "mode_aware_llm_judgement",
                    "pre_llm_risk_level": "suspicious",
                    "llm_risk_level": "suspicious",
                    "final_risk_level": "suspicious",
                    "accepted_findings": ["Subprocess execution requires review"],
                    "dismissed_findings": ["Documentation-only URL"],
                },
                "findings": [
                    {
                        "source": "behavioral",
                        "severity": "HIGH",
                        "rule": "AST4",
                        "title": "Subprocess call",
                        "file": "/tmp/skill/scripts/run.py",
                        "line": 12,
                        "explanation": "The script starts a subprocess.",
                        "evidence": "Authorization: Bearer top-secret-value",
                        "remediation": "Restrict the command and validate arguments.",
                    },
                    {
                        "source": "sandbox",
                        "severity": "MEDIUM",
                        "title": "Network attempt",
                        "file": "scripts/run.py",
                        "line": 15,
                    },
                ],
                "local_static_analysis": {
                    "scanned_file_count": 6,
                    "findings": [{"rule": "AST4"}],
                    "max_severity": "HIGH",
                },
                "skillspector_analysis": {
                    "available": True,
                    "risk_score": 6.4,
                    "risk_severity": "MEDIUM",
                    "suppressed_findings_count": 1,
                    "risk_recommendation": "Review before approval",
                },
                "sandbox_analysis": {
                    "executed": True,
                    "runtime": "docker",
                    "image": "agent-manager-sandbox-runtime:latest",
                    "entrypoint": "scripts/run.py",
                    "probe_strategy": "manifest",
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_ms": 520,
                    "network_attempts": 1,
                    "risk_level": "MEDIUM",
                    "max_severity": "MEDIUM",
                    "summary": "One outbound connection was attempted.",
                    "signals": [{"severity": "MEDIUM", "category": "network", "message": "Outbound connection"}],
                    "stdout": "api_key=another-secret\nscan complete",
                },
                "llm_analysis": {
                    "provider": "openai",
                    "model": "example-model",
                    "risk_level": "suspicious",
                    "report": "## Assessment\n- Review the subprocess call before approval.",
                },
            },
        ),
    )


def test_build_scan_report_pdf_contains_branding_sections_and_redaction():
    entry = _entry()
    now = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
    scan_run = ScanRun(
        scan_run_id="run-1",
        version_id=entry.skill_id,
        scan_context_fingerprint="sha256:context",
        status="COMPLETED",
        started_at=now,
        finished_at=now,
    )
    event = AuditEvent(
        event_id="event-1",
        event_type="skill_vetted",
        skill_id=entry.skill_id,
        skill_name=entry.name,
        actor="reviewer",
        details={"risk": "suspicious"},
        timestamp=now,
    )

    payload = build_scan_report_pdf(
        entry,
        scan_runs=[scan_run],
        audit_events=[event],
        language="zh-CN",
        generated_at=now,
    )

    assert payload.startswith(b"%PDF")
    reader = PdfReader(BytesIO(payload))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) >= 5
    assert "Skill 安全扫描报告" in text
    assert "1. 管理摘要" in text
    assert "5. 风险发现项" in text
    assert "10. 评估局限" in text
    assert b"/Subtype /Image" in payload
    assert "must-not-leak" not in text
    assert "top-secret-value" not in text
    assert "another-secret" not in text
    assert "[REDACTED]" in text
    assert "0.40s" in text
    assert "0.80s" in text
    assert "1.40s" in text
    assert "1.60s" in text
    assert "0.00s" not in text


def test_analyzer_rows_map_timing_keys_and_remove_alias_duplicates():
    entry = _entry()
    report = entry.vetting.scan_report

    rows = _analyzer_rows(entry, report, "zh-CN")

    assert rows == [
        ("basic", "completed", "0.40s"),
        ("behavioral:local", "completed", "0.80s"),
        ("sandbox:docker", "completed", "1.40s"),
        ("llm:openai", "completed", "1.60s"),
    ]


def test_analyzer_rows_show_missing_and_subsecond_durations_clearly():
    entry = _entry()
    entry.vetting.analyzers_used = ["basic", "skillspector:cli"]
    report = {
        "analyzer_timings": {
            "scanner": {"status": "completed", "duration_seconds": 0.0042},
        }
    }

    assert _analyzer_rows(entry, report, "zh-CN") == [
        ("basic", "completed", "4.2 ms"),
        ("skillspector:cli", "未记录", "未记录"),
    ]
    assert _analyzer_rows(entry, report, "en-US")[1] == (
        "skillspector:cli",
        "Not recorded",
        "Not recorded",
    )


def test_build_scan_report_pdf_supports_english():
    payload = build_scan_report_pdf(_entry(), language="en-US")
    reader = PdfReader(BytesIO(payload))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Skill Security Scan Report" in text
    assert "1. Executive Summary" in text
    assert "10. Assessment Limitations" in text


def test_english_pdf_localizes_generated_chinese_system_text():
    entry = _entry()
    report = entry.vetting.scan_report
    entry.vetting.policy_notes = ["[DEEP_SCAN] 深度扫描不可用，已跳过"]
    report["findings"][0].update(
        {
            "rule": "P1",
            "title": "提示词注入",
            "explanation": "Skill 内容要求忽略上级或系统指令。",
            "remediation": "请删除覆盖上级指令的内容。",
        }
    )
    report["risk_reconciliation"].update(
        {
            "reason": "需要结合代码证据进行人工判断。",
            "downgrade_reason": "未满足降级条件。",
            "accepted_findings": ["采纳提示词注入风险。"],
            "dismissed_findings": ["排除文档中的普通链接。"],
        }
    )
    report["skillspector_analysis"].update(
        {
            "risk_recommendation": "建议人工审核",
            "error": "深度扫描服务不可用",
        }
    )
    report["sandbox_analysis"].update(
        {
            "summary": "Sandbox 执行中检测到 1 个风险信号。",
            "signals": [{"severity": "MEDIUM", "category": "network", "message": "检测到网络访问。"}],
        }
    )
    report["llm_analysis"]["report"] = "# 安全分析报告\n建议结合代码证据进行人工审核。"
    now = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
    event = AuditEvent(
        event_id="event-zh",
        event_type="skill_vetted",
        skill_id=entry.skill_id,
        skill_name=entry.name,
        actor="reviewer",
        details={"message": "扫描完成，等待人工审核。"},
        timestamp=now,
    )

    payload = build_scan_report_pdf(entry, audit_events=[event], language="en-US", generated_at=now)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)

    assert re.search(r"[\u3400-\u9fff]", text) is None
    assert "Prompt injection" in text
    assert "Sandbox detected 1 runtime risk signal" in text
    assert "stored LLM narrative was generated in the original scan language" in text


def test_scan_report_pdf_api_download(tmp_path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: report-skill
            description: Generates reports
            license: MIT
            allowed-tools: Read
            ---

            # Report Skill
            """
        ),
        encoding="utf-8",
    )
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    entry = manager.submit(skill_dir, SourceInfo(origin=SkillOrigin.LOCAL))

    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    response = client.get(f"/api/v1/skills/{entry.skill_id}/scan-report.pdf", params={"language": "en-US"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "report-skill-v1-scan-report.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
