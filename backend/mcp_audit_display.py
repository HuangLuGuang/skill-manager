"""调用审计固定原因的读取展示编码；保留存储原文。"""
import re

# 只匹配平台拒绝分支的完整固定文本，未知原因保持原文。
_DENIED_REASONS = {
    'MCP Tool 调用等待管理员审批': 'pending',
    'MCP Tool 调用已被管理员拒绝': 'rejected',
    'Tool 未授权或不存在': 'toolUnavailable',
    '生产 MCP 网关禁止使用完整主动模式': 'productionMode',
    '被动 MCP 网关禁止调用 Tool': 'passiveMode',
    '只读 MCP 网关禁止调用非只读 Tool': 'readOnlyMode',
    'Tool 已被生产环境 denylist 阻断': 'denylist',
    'Tool Schema 已变化，需要重新审核': 'schemaChanged',
    'Tool 参数不符合 Schema': 'argumentsInvalid',
    '高风险 Tool 审批申请无效': 'approvalInvalid',
    '高风险 Tool 审批申请已过期': 'approvalExpired',
    '高风险 Tool 审批申请已被使用': 'approvalUsed',
    '高风险 Tool 审批申请状态无效': 'approvalStatusInvalid',
    '高风险 Tool 审批时的 Schema 已变化': 'approvalSchemaChanged',
    '高风险 Tool 审批凭证无效或已过期': 'approvalTokenInvalid',
    '高风险 Tool 审批参数与调用参数不一致': 'approvalArgumentsChanged',
    '高风险 Tool 审批凭证已被使用': 'approvalTokenUsed',
    '该 MCP 凭证的待审批申请数量已达上限': 'pendingLimit',
    'MCP Tool 每分钟调用次数已达上限': 'rateLimit',
    'MCP Tool 并发调用数已达上限': 'toolConcurrency',
    'credential.concurrency_limit': 'credentialConcurrency',
    'agent.not_found': 'agentMissing',
    'agent.disabled': 'agentDisabled',
    'agent.mcp_scope_exceeded': 'agentScope',
}


def audit_reason_metadata(status: str, error: str | None) -> dict:
    """读取时补齐展示信息，不改变历史结果、原因或审批状态。"""
    if status == "denied":
        return {"reason_code": _DENIED_REASONS.get(error)}
    if status == "error":
        code = {
            "mcp.tool_execution_failed": "toolFailed",
            "gateway.request_interrupted": "interrupted",
        }.get(error)
        if code:
            return {"reason_code": code}
        for pattern, code, parameter in [
            (r"上游 MCP 调用超时（配置超时：(\d+) 秒）", "timeout", "seconds"),
            (r"上游 MCP 响应超过限制：(\d+) KB", "responseLimit", "kilobytes"),
        ]:
            match = re.fullmatch(pattern, error or "")
            if match:
                return {"reason_code": code, "reason_params": {parameter: int(match.group(1))}}
    return {}
