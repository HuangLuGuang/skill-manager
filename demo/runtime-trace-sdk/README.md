# Runtime Trace SDK 示例

本示例演示 `runtime-trace@1` 的最小接入链：Agent SDK 创建 Trace，记录 Turn、Step、用户消息、知识检索和 Tool Call/Result，并把同一组关联 ID 传给模型网关或 MCP 网关。

前置条件：

- 已创建并绑定 Agent 的 `agent_runtime` 凭证。
- 凭证包含 `runtime:trace`；需要调用模型或 MCP 时还需分别包含 `model:chat`、`mcp:call-tools`。
- 平台默认启用 Runtime Trace，无需单独配置页面开关。

运行：

```bash
export AGENT_MANAGER_URL=http://127.0.0.1:8000
export AGENT_RUNTIME_TOKEN=amat_replace_me
# 可选；设置后示例会真实调用模型网关并形成 full 轨迹
export AGENT_MANAGER_MODEL=your-enabled-model
uv run python demo/runtime-trace-sdk/example.py
```

未设置 `AGENT_MANAGER_MODEL` 时，示例只上报本地事件，不调用真实模型或 Tool；设置后会调用已配置的模型网关。调用模型网关时，把 `trace.gateway_metadata(...)` 合并进 OpenAI 请求的 `metadata`；调用 MCP 时，把它合并进 `params._meta`。模型/MCP 网关会读取这些关联字段，但 Agent 身份仍只取自服务端验证过的绑定凭证。

验证 API：

```text
GET /api/v1/runtime-traces?session_id=<session_id>
GET /api/v1/runtime-traces/<trace_id>/events
GET /api/v1/runtime-traces/<trace_id>/events/<event_id>/raw-payload
POST /api/v1/runtime-traces/<trace_id>/exports
GET /api/v1/runtime-traces/metrics
```

事件列表始终返回脱敏投影。原始 Payload 仅管理员和隐私审计角色可查看或导出，并写入防篡改安全审计链。
