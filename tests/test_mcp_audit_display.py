"""平台固定原因展示的精确匹配与原始证据兼容。"""
import pytest
from backend.mcp_audit_display import _DENIED_REASONS, audit_reason_metadata


@pytest.mark.parametrize("message,code", _DENIED_REASONS.items())
def test_fixed_denied_reason(message, code):
    assert audit_reason_metadata("denied", message) == {"reason_code": code}
    assert audit_reason_metadata("error", message) == {}


@pytest.mark.parametrize("reason", [None, "", "upstream failure", "MCP Tool 调用等待管理员审批 extra"])
def test_unknown_reason_is_preserved(reason):
    assert audit_reason_metadata("denied", reason).get("reason_code") is None


@pytest.mark.parametrize("reason,code,params", [
    ("上游 MCP 调用超时（配置超时：1 秒）", "timeout", {"seconds": 1}),
    ("上游 MCP 响应超过限制：1024 KB", "responseLimit", {"kilobytes": 1024}),
    ("gateway.request_interrupted", "interrupted", {}),
    ("mcp.tool_execution_failed", "toolFailed", {}),
])
def test_fixed_failure_reason(reason, code, params):
    metadata = audit_reason_metadata("error", reason)
    assert metadata["reason_code"] == code
    assert metadata.get("reason_params", {}) == params
