# 智能体治理与统一凭证实施计划

本文件用于跟踪智能体治理闭环实现进度。实施完成后保留，作为后续迭代和验收依据。

## 目标

- 统一模型调用、Agent Runtime、Scanner 接入凭证的创建入口。
- Agent 能绑定模型、Prompt 和 Skill；Agent 运行凭证在统一凭证中心签发并绑定 Agent。
- 外部 Agent 使用 `agent_id + access_token` 做运行时校验。
- 模型网关支持具备 `model:chat` 的统一凭证。
- 文档写清接入流程和运行流程。

## 进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 新增统一 Access Token 后端模型、schema、管理 API | 已完成 |
| Phase 2 | Runtime access 接口校验 token、Agent 绑定、Skill / Prompt 授权 | 已完成 |
| Phase 3 | 模型网关支持 `model:chat` 统一凭证 | 已完成 |
| Phase 4 | 新增统一凭证中心，旧 API Key / Scanner Token 创建入口收口 | 已完成 |
| Phase 5 | 文档、测试和端到端验收 | 已完成 |

## 验收清单

- [x] `统一凭证中心` 可以创建模型调用、Agent 运行、Scanner 接入、Client 接入和 MCP 网关五类凭证。
- [x] 凭证明文只在创建后展示一次。
- [x] 模型网关页面不再创建 API Key，并指向统一凭证中心。
- [x] Scanner 页面不再创建 Token，并指向统一凭证中心。
- [x] Agent 表单不再选择 Runtime Token，运行凭证统一在统一凭证中心绑定 Agent。
- [x] Runtime Token 绑定错误 Agent 时拒绝。
- [x] Agent 未绑定 Skill 时 `can-load` 拒绝。
- [x] Agent 未绑定 Prompt 时 `can-load-prompt` 拒绝。
- [x] Agent Token 无 `model:chat` 时不能调用模型网关。
- [x] Agent Token 有 `model:chat` 时能按 Agent 默认模型或 allowed_models 调用模型网关。
- [x] `docs/agent-governance.md` 写清接入流程和运行流程。
- [x] `docs/model-gateway.md`、`docs/skill-scanner.md`、`docs/external-agent-integration.md` 已同步入口变化。
- [x] 后端 targeted tests 通过。
- [x] 前端 `npm run build` 通过。
