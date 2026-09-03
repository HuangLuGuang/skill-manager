# Agent Security Full Integration Demo

本示例将一个 Agent Turn 串联到 Agent Manager 的四类观测源：

1. Agent SDK 创建 Trace，记录 Turn、Step、用户消息和脱敏知识检索。
2. 模型请求经过 OpenAI-compatible 模型网关，并携带同一组关联字段。
3. 本地 Tool 不经过 MCP，但由 SDK 记录 Call/Result。
4. 远程 Tool 经过 MCP Gateway，并使用与 SDK Tool Call 相同的 `call_id`。

模型网关和 MCP 网关使用服务端验证过的 `agent_runtime` 凭证建立身份；调用方传入的关联字段只用于将事件归入
同一 Trace，不用于伪造 Agent 身份。原始 Prompt、响应和 Tool 参数由服务端加密保存，普通页面和查询只返回脱敏投影。

## 前置配置

- 创建绑定 Agent 的 `agent_runtime` Token。
- Token 至少包含 `runtime:trace`、`model:chat` 和 `mcp:call-tools`。
- Token 的 MCP 网关允许列表必须包含示例使用的 Gateway。
- 模型、MCP Gateway、Server 和 Tool 已启用，Tool Schema 已审核。

## 运行

```bash
export AGENT_MANAGER_URL=http://127.0.0.1:8000
export AGENT_RUNTIME_TOKEN=amat_replace_me
export AGENT_MANAGER_MODEL=your-enabled-model
export AGENT_MANAGER_MCP_GATEWAY=your-gateway-slug
export AGENT_MANAGER_MCP_TOOL=server__tool
export AGENT_MANAGER_MCP_ARGUMENTS='{"query":"智能体安全"}'
uv run python demo/agent-security-full-integration/full_agent.py
```

脚本只输出关联 ID、状态和事件接收数量，不输出 Token、模型正文或 Tool 结果。成功后在“调用轨迹”页面按输出的
`trace_id` 查看，完整轨迹应同时包含 `agent_sdk`、`model_gateway`、`mcp_gateway` 和 `knowledge_connector` 来源。

如果 Tool 需要审批，脚本返回 `status=approval_pending` 和 `approval_request_id` 后停止，不会绕过审批或自动重放。
管理员在 MCP 审批页面批准后，将返回的 ID 作为 `AGENT_MANAGER_MCP_APPROVAL_REQUEST` 再运行一次：

```bash
export AGENT_MANAGER_MCP_APPROVAL_REQUEST=mcpapr_replace_me
uv run python demo/agent-security-full-integration/full_agent.py
```

服务端会再次核对 Token、Gateway、Tool、Schema、状态和有效期，并记录审批使用。每次运行都会创建新的 Trace，
避免将审批前后的两次执行错误拼接为一次完整轨迹。

## 验收边界

- 本 Demo 验证关联协议和接入路径，不代表目标 Agent 已通过安全扫描。
- 本地 Tool 结果和知识正文使用固定脱敏摘要，不把敏感原文写入普通日志。
- Gateway-only 部分轨迹属于 P7-02，不在本示例中冒充完整 SDK 轨迹。
- Worker 扫描 Finding 到 Runtime Trace 证据的端到端联调属于 P7-03；本 Demo 不提前勾选 A6-04。
