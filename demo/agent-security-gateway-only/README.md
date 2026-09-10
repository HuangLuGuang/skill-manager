# Agent Security Gateway-only Demo

本示例只调用模型网关和/或 MCP Gateway，不调用 Runtime Trace SDK，不创建 Agent Turn/Step。它用于证明“网关日志”
只能形成部分轨迹，页面不能为了视觉完整性伪造 Agent 执行过程。

支持三种模式：

- `model`：只有模型网关事件，期望完整度为 `model_only`。
- `mcp`：只有 MCP 网关事件，期望完整度为 `mcp_only`。
- `combined`：模型和 MCP 事件使用同一个可信关联 `trace_id`，但仍没有 Agent SDK 事件，期望完整度为
  `gateway_partial`。这是默认模式。

## 凭证边界

示例使用绑定 Agent 的 `agent_runtime` Token，以便两个网关接受同一个 `trace_id`。Token 按运行模式至少需要
`model:chat` 和/或 `mcp:call-tools`，MCP 模式还要授权目标 Gateway。调用方传入的关联字段不决定 Agent 身份，
身份仍来自服务端校验过的 Token。脚本不会打印 Token、模型正文或 Tool 结果。

要让脚本自动回查完整度，需要额外提供当前登录用户的短期 Bearer Token `AGENT_MANAGER_TRACE_READ_TOKEN`；它只用于
受权限控制的只读查询，不用于网关调用。未提供时脚本返回 `submitted_unverified`，只给出期望状态，不把请求成功
冒充为服务端完整度已验证。

## 运行

```bash
export AGENT_MANAGER_URL=http://127.0.0.1:8000
export AGENT_RUNTIME_TOKEN=amat_replace_me
export AGENT_MANAGER_GATEWAY_ONLY_MODE=combined
export AGENT_MANAGER_MODEL=your-enabled-model
export AGENT_MANAGER_MCP_GATEWAY=your-gateway-slug
export AGENT_MANAGER_MCP_TOOL=server__tool
export AGENT_MANAGER_MCP_ARGUMENTS='{"query":"health"}'
# 可选：用于回查完整度和事件，不要写入项目文件
export AGENT_MANAGER_TRACE_READ_TOKEN=replace_with_short_lived_login_token
uv run python demo/agent-security-gateway-only/gateway_only.py
```

`model` 模式不需要 MCP 配置；`mcp` 模式不需要模型配置。MCP Tool 如果进入人工审批，脚本记录
`mcp_status=approval_pending`，仍可验证已产生的 MCP 部分轨迹，但不会把 Tool 标记为执行成功。

## 自动回查验收

提供只读令牌时，脚本会失败关闭地检查：

1. 完整度精确等于当前模式的预期值。
2. 事件来源中不存在 `agent_sdk`。
3. 所有事件的 `turn_id` 和 `step_id` 都为空。
4. 事件来源包含所选模式对应的模型/MCP 网关。

完整 Agent SDK 关联请使用 `demo/agent-security-full-integration/`。本示例不执行安全扫描，也不证明 Finding 的证据闭环。
