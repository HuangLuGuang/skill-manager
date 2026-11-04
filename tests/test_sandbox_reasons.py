"""Sandbox 说明的稳定编码及历史报告只读兼容。"""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.sandbox import (
    RemoteSandboxRunner,
    SandboxConfig,
    sandbox_reason_metadata,
    with_sandbox_reason_metadata,
)
from tests.test_skill_sandbox_filter import _entry


def test_scan_report_adds_reason_metadata_without_rewriting_history(tmp_path):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path)
    report = {"sandbox_analysis": {
        "executed": True, "reason": "executed by nsjail backend",
        "summary": "Sandbox 已执行，未提取到明确运行时风险信号。",
        "recommendation": "可结合规则分析、深度分析和 LLM 分析结果综合判断。",
        "probe_results": [{"reason": "executed by nsjail backend",
                           "probe_description": "default sandbox probe strategy=default"}],
    }}
    original = deepcopy(report)
    manager.registry.add(_entry("reason", report))
    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    response = TestClient(app).get("/api/v1/skills/id-reason/scan-report")
    assert response.status_code == 200
    sandbox = response.json()["scan_report"]["sandbox_analysis"]
    assert sandbox["reason_code"] == "executed_nsjail"
    assert sandbox["probe_results"][0]["reason_code"] == "executed_nsjail"
    assert sandbox["summary_code"] == "executed_clean"
    assert sandbox["recommendation_code"] == "combine_all"
    assert sandbox["probe_results"][0]["probe_description_code"] == "default_probe"
    assert sandbox["reason"] == original["sandbox_analysis"]["reason"]
    assert manager.get_skill("id-reason").vetting.scan_report == original


REASON_CASES = [
    ("executed by nsjail backend", "executed_nsjail", {}),
    ("executed by subprocess backend", "executed_subprocess", {}),
    ("execution timed out", "execution_timeout", {}),
    ("success", "remote_processed", {}),
    ("backend unavailable", "backend_unavailable", {}),
    ("nsjail backend is not available", "named_backend_unavailable", {"backend": "nsjail"}),
    ("Remote sandbox rejected execution: subprocess backend is not available",
     "remote_backend_unavailable", {"backend": "subprocess"}),
    ("probe_strategy=default", "probe_default", {}),
    ("probe_strategy=custom", "probe_custom", {}),
    ("Sandbox probe timed out", "probe_timeout", {}),
    ("Docker is not available on this host", "docker_unavailable", {}),
    ("Unsupported sandbox runtime: other", "runtime_unsupported", {"runtime": "other"}),
    ("Unsupported sandbox entrypoint type: .rb", "entrypoint_unsupported", {"suffix": ".rb"}),
    ("Remote sandbox service URL is not configured", "remote_url_missing", {}),
    ("Unsupported remote sandbox entrypoint type: .rb", "remote_entrypoint_unsupported", {"suffix": ".rb"}),
    ("Remote sandbox request failed: 503\nhttp://localhost:8123/run-code",
     "remote_request_failed", {"detail": "503\nhttp://localhost:8123/run-code"}),
    ("Remote sandbox rejected execution: custom upstream error",
     "remote_rejected", {"detail": "custom upstream error"}),
    ("Remote sandbox returned an unsupported response shape", "remote_response_invalid", {}),
    ("Executed by remote isolated sandbox service", "executed_remote", {}),
    ("No supported executable script found. SKILL.md command examples are not executed as Sandbox probes.",
     "no_executable_script", {}),
    ("Sandbox analysis skipped: missing /tmp/输入.py", "analysis_skipped", {"detail": "missing /tmp/输入.py"}),
]


@pytest.mark.parametrize("reason,code,params", REASON_CASES)
def test_all_known_reason_templates_preserve_parameters(reason, code, params):
    analysis = {"reason": reason, "probe_results": [{"reason": reason}]}
    original = deepcopy(analysis)
    enriched = with_sandbox_reason_metadata(analysis)
    for result in (enriched, enriched["probe_results"][0]):
        assert result["reason"] == reason
        assert result["reason_code"] == code
        assert result["reason_params"] == params
    assert analysis == original


@pytest.mark.parametrize("reason", [None, "", "Unknown upstream message", "上游自定义错误", "<script>alert(1)</script>"])
def test_unknown_reason_keeps_original(reason):
    assert sandbox_reason_metadata(reason) == {}
    assert with_sandbox_reason_metadata({"reason": reason}) == {"reason": reason}


def test_existing_metadata_is_preserved():
    analysis = {"reason": "Remote sandbox request failed: Connection refused",
                "reason_code": "remote_request_failed",
                "reason_params": {"detail": "Connection refused"}}
    assert with_sandbox_reason_metadata(analysis) == analysis


@pytest.mark.parametrize("message,code,exit_code,timed_out,field", [
    ("executed by nsjail backend", "executed_nsjail", 1, False, "message"),
    ("executed by subprocess backend", "executed_subprocess", 0, False, "message"),
    ("execution timed out", "execution_timeout", None, True, "message"),
    ("custom upstream error", None, 1, False, "message"),
    ("TIMEOUT", None, 124, True, "message"),
    ("Execution TIMED OUT", None, None, True, "message"),
    ("execution timed out", "execution_timeout", None, True, "error"),
    ("TIMEOUT", None, 124, True, "error"),
])
def test_new_remote_results_include_metadata(tmp_path, monkeypatch, message, code, exit_code, timed_out, field):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "run.py").write_text("print('ok')\n")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {field: message, "exit_code": exit_code}

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", lambda *args, **kwargs: Response())
    result = RemoteSandboxRunner(SandboxConfig(
        runtime="remote", remote_url="http://sandbox.local",
    )).run_probe(skill_dir, "run.py")
    assert result.reason == message
    assert result.reason_code == code
    assert result.executed is True
    assert result.exit_code == exit_code
    assert result.timed_out == timed_out
    if timed_out:
        assert any(signal.category == "timeout" for signal in result.signals)
        assert result.max_severity == "MEDIUM"


@pytest.mark.parametrize("status,kind,location", [
    (199, "informational", None), (302, "redirect", "https://sandbox.local/new"),
    (307, "redirect", None), (400, "client", None), (502, "server", None),
    (600, "invalid", None),
])
@pytest.mark.parametrize("existing_code", [False, True])
def test_httpx_fixed_error_metadata(status, kind, location, existing_code):
    """使用 HTTP 客户端真实异常验证新结果和已编码历史报告。"""
    import httpx

    response = httpx.Response(
        status, request=httpx.Request("POST", "http://sandbox.local/run-code"),
        headers={"location": location} if location else {},
    )
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()
    detail = str(caught.value)
    record = {"reason": f"Remote sandbox request failed: {detail}"}
    if existing_code:
        record.update(reason_code="remote_request_failed", reason_params={"detail": detail})
    original = deepcopy(record)
    enriched = with_sandbox_reason_metadata({**record, "probe_results": [record]})
    for item in (enriched, enriched["probe_results"][0]):
        assert item["reason_code"] == "remote_request_failed"
        params = item["reason_params"]
        assert params["detail"] == detail
        assert params["http_error_type"] == kind
        assert params["http_status"] == f"{status} {response.reason_phrase}"
        assert params["http_url"] == str(response.url)
        assert params["http_info_url"].endswith(f"/Status/{status}")
        assert params.get("http_redirect_url") == location
    assert record == original


def test_custom_http_like_error_is_not_reinterpreted():
    detail = "Server error '502 custom upstream diagnostic'\nFor more information check: contact owner"
    metadata = sandbox_reason_metadata(f"Remote sandbox request failed: {detail}")
    assert metadata["reason_params"] == {"detail": detail}


@pytest.mark.parametrize("field,raw,code", [
    ("message", "Sandbox probe exceeded the configured timeout.", "local_timeout"),
    ("message", "Remote sandbox probe exceeded the configured timeout or was terminated.", "remote_timeout"),
    ("summary", "Sandbox 未执行。", "not_executed"),
    ("summary", "Sandbox 已执行，未提取到明确运行时风险信号。", "executed_clean"),
    ("summary", "Sandbox 未发现明确风险信号。", "no_signals"),
    ("summary", "Sandbox probe 未能完整执行：引用的示例输入文件不存在。", "missing_input"),
    ("recommendation", "先确认 Sandbox 后端可用性，再结合规则分析和深度分析结果继续评估。", "check_backend"),
    ("recommendation", "可结合规则分析、深度分析和 LLM 分析结果综合判断。", "combine_all"),
    ("recommendation", "可结合规则分析和深度分析结果继续评估。", "combine_static"),
    ("recommendation", "这通常不是 Skill 的安全行为，可补充真实测试输入后重新执行 Sandbox，或结合规则分析和深度分析结果继续判断。", "supply_input"),
    ("recommendation", "建议进入人工审核或直接拒绝，避免直接部署。", "manual_review"),
    ("recommendation", "建议结合其他扫描结果进一步确认后再决定是否批准。", "confirm_findings"),
    ("recommendation", "建议排查失败原因或依赖问题，再重新执行 sandbox 验证。", "retry_execution"),
])
def test_fixed_display_metadata(field, raw, code):
    record = {field: raw}
    original = deepcopy(record)
    if field == "message":
        record = {"signals": [record], "suspicious_events": [record]}
    enriched = with_sandbox_reason_metadata(record)
    items = [enriched["signals"][0], enriched["suspicious_events"][0]] if field == "message" else [enriched]
    for item in items:
        assert item[field] == raw
        assert item[f"{field}_code"] == code
    if field != "message":
        assert record == original


@pytest.mark.parametrize("strategy", ["default", "cli-help"])
def test_probe_description_and_risk_summary_metadata(strategy):
    probe = {"probe_description": f"default sandbox probe strategy={strategy}",
             "summary": "Sandbox 执行中检测到 2 个风险信号，主要涉及 timeout、network。"}
    enriched = with_sandbox_reason_metadata({"probe_results": [probe]})["probe_results"][0]
    assert enriched["probe_description_code"] == "default_probe"
    assert enriched["probe_description_params"] == {"strategy": strategy}
    assert enriched["summary_code"] == "risk_signals"
    assert enriched["summary_params"] == {"count": 2, "categories": ["timeout", "network"]}
    assert "summary_code" not in probe


def test_custom_display_text_and_existing_codes_are_preserved():
    record = {"summary": "Upstream custom summary", "recommendation": "Contact owner",
              "probe_description": "User supplied description",
              "signals": [{"message": "custom timeout diagnostic", "evidence": "raw evidence"}]}
    assert with_sandbox_reason_metadata(record) == record
    coded = {"summary": "Sandbox 未执行。", "summary_code": "not_executed", "summary_params": {}}
    assert with_sandbox_reason_metadata(coded) == coded


def test_new_scan_report_saves_display_metadata(tmp_path, monkeypatch):
    """扫描流程序列化新报告时补齐元数据；外部执行边界在此单测中替代。"""
    from agent_manager.core.sandbox import SandboxResult, _finalize_result
    from agent_manager.core.vetting import _run_sandbox_analysis

    (tmp_path / "run.py").write_text("print('ok')\n")

    class Runner:
        config = SandboxConfig(runtime="remote")

        def run_probe(self, *args, **kwargs):
            return _finalize_result(SandboxResult(
                executed=True, runtime="remote", exit_code=0,
                reason="executed by nsjail backend",
            ))

    monkeypatch.setattr("agent_manager.core.vetting.get_sandbox_runner", lambda: Runner())
    result = _run_sandbox_analysis(tmp_path).result
    assert result["summary_code"] == "executed_clean"
    assert result["recommendation_code"] == "combine_all"
    assert result["probe_results"][0]["probe_description_code"] == "default_probe"
    assert result["probe_results"][0]["summary_code"] == "executed_clean"
    assert result["executed"] is True and result["exit_code"] == 0


@pytest.mark.parametrize("stderr,code,timed_out", [
    ("Connection refused", "network_activity", False),
    ("Permission denied", "filesystem_access", False),
    ("No such file or directory", "missing_probe_input", False),
    ("", "execution_timeout", True),
])
def test_generated_signal_metadata_preserves_evidence(stderr, code, timed_out):
    """覆盖实际信号生成及超时补充路径，证据和判定保持原值。"""
    from agent_manager.core.sandbox import SandboxResult, _build_events, _finalize_result

    result = _finalize_result(SandboxResult(
        executed=True, runtime="remote", exit_code=1, timed_out=timed_out,
        suspicious_events=_build_events("", stderr),
    )).model_dump(mode="json")
    original = deepcopy(result)
    enriched = with_sandbox_reason_metadata(result)
    assert enriched["signals"][0]["message_code"] == code
    for field in ("executed", "exit_code", "timed_out", "risk_level", "max_severity"):
        assert enriched[field] == original[field]
    assert enriched["signals"][0]["message"] == original["signals"][0]["message"]
    assert enriched["signals"][0]["evidence"] == original["signals"][0]["evidence"]
    assert result == original


@pytest.mark.parametrize("value", ["待审核", " 默认 ", "\n", "custom upstream text"])
def test_custom_display_fields_preserve_exact_content(value):
    record = {"summary": value, "recommendation": value,
              "probe_description": value, "signals": [{"message": value, "evidence": value}]}
    assert with_sandbox_reason_metadata(record) == record
