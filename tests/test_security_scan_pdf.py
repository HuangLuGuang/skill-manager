from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pypdf import PdfReader

from backend.security_scan_pdf import build_security_scan_pdf
from backend.api_errors import ApiError
from backend.routers import security_scans


def report_detail():
    return {
        "task": {"task_id": "tsk_pdf_demo", "target_id": "ast_demo", "scan_kind": "agent_risk_scan", "status": "succeeded", "engine": {"name": "AI-Infra-Guard", "version": "4.6.0"}},
        "cases": [{"case_id": "case_1", "title": "Prompt injection / 提示注入", "execution_status": "completed", "assessment_status": "risk", "request_summary": {"prompt": "<script>test</script>"}, "response_summary": {"response": "Evidence paragraph. 中文证据。" * 200}}],
        "findings": [{"finding_id": "finding_1", "title": "Evidence review", "severity": "high", "description": "Review the observed response.", "evidence": {"token": "secret-value"}}],
        "artifacts": [{"artifact_id": "report_1", "artifact_type": "aig-agent-scan-report", "sha256": "a" * 64, "size_bytes": 2048}],
    }


@pytest.mark.parametrize("language, heading", [("zh-CN", "安全扫描报告"), ("en-US", "Security Scan Report")])
def test_branded_security_report_handles_long_evidence(language, heading):
    document = build_security_scan_pdf(report_detail(), language=language)
    reader = PdfReader(BytesIO(document))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) >= 3
    assert heading in text
    assert "tsk_pdf_demo" in text
    assert "finding_1" in text
    assert "report_1" in text
    assert "<script>test</script>" in text
    assert any(page.images for page in reader.pages)


def test_empty_snapshot_is_not_described_as_safe():
    document = build_security_scan_pdf({"task": {"task_id": "tsk_empty", "status": "running"}}, language="en-US")
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(document)).pages)
    assert "Running" in text
    assert "does not establish" in text


@pytest.mark.parametrize("language", ["zh-CN", "en-US"])
def test_report_renders_structured_content_as_readable_sections(language):
    detail = report_detail()
    detail["cases"][0]["response_summary"] = {"response": "Observed output", "evaluator_reason": "The target followed the injected instruction.", "checks": [{"description": "Nested evidence remains readable"}]}
    detail["task"]["scan_options"] = {"datasets": ["test-dataset"], "prompt_configured": True}
    document = build_security_scan_pdf(detail, language=language)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(document)).pages)
    assert '"response":' not in text
    assert "evaluator_reason" not in text
    assert "prompt_configured" not in text
    assert "Observed output" in text
    assert "The target followed the injected instruction." in text
    assert "Nested evidence remains readable" in text
    assert text.index("<script>test</script>") < text.index("finding_1")


def realistic_report_detail(kind):
    detail = report_detail()
    detail["task"]["scan_kind"] = kind
    detail["target"] = {"endpoint_url": "https://scan-target.example.test/v1"}
    if kind == "llm_redteam_scan":
        detail["cases"] = [{"case_id": f"case_{i}", "request_summary": {"vulnerability": "Dataset A" if i < 10 else "Dataset B", "prompt_sha256": "b" * 64}, "response_summary": {"assessment_status": "jailbreak_signal_detected" if i < 13 else "attack_resisted", "evaluator_reason": "评估器观察到目标未遵循预期的安全边界，需对照原始对话人工复核。 The evaluator observed a boundary failure; review the original conversation."}, "assessment_status": "risk_signal_detected" if i < 13 else "no_risk_observed"} for i in range(20)]
        detail["findings"] = [{"finding_id": f"finding_{i}", "case_id": f"case_{i}", "severity": "high", "title": "Repeated generic engine title"} for i in range(13)]
    else:
        detail["cases"] = [{"case_id": "case_1", "title": "Ollama service", "request_summary": {"endpoint": "http://192.0.2.1:11434"}, "response_summary": {"component": "ollama", "component_version": "0.33.3"}}]
        detail["findings"] = [{"finding_id": f"finding_{i}", "case_id": "case_1", "title": "组件版本安全公告匹配 / Component advisory match", "severity": "critical" if i == 0 else "low", "description": "扫描引擎匹配到版本规则，需核对具体产品与安装组件。 Validate the installed product and component against the vendor advisory.", "evidence": {"rule_match_source": "ai-infra-guard-version-advisory", "component": "ollama", "component_version": "0.33.3"}} for i in range(2)]
    return detail


def test_redteam_summary_counts_cases_and_moves_identifiers_to_appendix():
    document = build_security_scan_pdf(realistic_report_detail("llm_redteam_scan"), language="en-US")
    pages = PdfReader(BytesIO(document)).pages
    text = "\n".join(p.extract_text() for p in pages)
    assert "65%" in pages[0].extract_text()
    assert "Repeated generic engine title" not in text
    assert "prompt sha256" not in text
    assert "Dataset A" in text and "Dataset B" in text
    assert "do not contain the full input" in text
    assert len(pages) < 15


def test_infrastructure_explains_evidence_level_and_omits_llm_parameters():
    document = build_security_scan_pdf(realistic_report_detail("ai_infrastructure_vulnerability_scan"), language="en-US")
    pages = PdfReader(BytesIO(document)).pages
    text = "\n".join(p.extract_text() for p in pages)
    assert "Exploit verification is not present" in text
    assert "Tokens" not in text
    assert "Conversation mode" not in text
    assert "public exposure" in text
    assert len(pages) <= 4


def test_pdf_endpoint_checks_access_before_reading_report(monkeypatch):
    task = SimpleNamespace(task_id="tsk_pdf_demo")
    monkeypatch.setattr(security_scans, "_task_or_404", lambda *args: task)
    read = MagicMock(return_value=report_detail())
    monkeypatch.setattr(security_scans, "_task_detail", read)
    access = MagicMock(side_effect=ApiError(403, "auth.permission_denied", "权限不足", "Permission denied"))
    monkeypatch.setattr(security_scans, "_require_task_access", access)
    with pytest.raises(ApiError):
        security_scans.export_security_scan_pdf(task.task_id, "en-US", object(), SimpleNamespace(username="reader"))
    read.assert_not_called()


def test_pdf_endpoint_download_and_audit(monkeypatch):
    task = SimpleNamespace(task_id="tsk_pdf_demo")
    monkeypatch.setattr(security_scans, "_task_or_404", lambda *args: task)
    monkeypatch.setattr(security_scans, "_require_task_access", MagicMock())
    monkeypatch.setattr(security_scans, "_task_detail", lambda *args: report_detail())
    audit = MagicMock()
    monkeypatch.setattr(security_scans, "_audit", audit)
    response = security_scans.export_security_scan_pdf(task.task_id, "en-US", object(), SimpleNamespace(username="reader"))
    assert response.body.startswith(b"%PDF")
    assert response.media_type == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert audit.call_args.kwargs["event_type"] == "security_scan_report.exported"
