# 智能体治理接入与运行流程

Agent Manager 的治理对象从单个 Skill 扩展到智能体。平台需要回答：

- 哪个部门的哪个 Agent 在运行。
- 这个 Agent 可以使用哪些模型、Prompt 和 Skill。
- 调用方是否能证明自己就是这个 Agent。
- 每次加载、调用和模型请求是否可审计。

## 核心对象

| 对象 | 作用 |
|---|---|
| 部门 / 用户组 | 业务归属和隐私策略边界 |
| Agent | 运行时主体，例如风险筛查智能体 |
| Skill | 经过提交、扫描、审核后的可加载能力 |
| Prompt | 经过治理后可绑定给 Agent 的提示词 |
| 模型 | 模型网关中配置的模型端点 |
| 凭证 | 证明调用方身份，并限制可执行权限 |

## 凭证类型

统一在管理台 `智能体管理 / 统一凭证中心` 创建凭证。

| 类型 | 默认权限 | 用途 |
|---|---|---|
| 模型调用凭证 | `model:chat` | 非 Agent 应用调用模型网关 |
| Agent 运行凭证 | `runtime:verify-signature`, `runtime:can-load`, `runtime:check-tool` | 已登记 Agent 的 Skill、Prompt 和 Tool 运行时校验 |
| Scanner 接入凭证 | `scanner:submit`, `scanner:read-own-results`, `scanner:read-own-sessions` | 客户侧扫描器提交 Skill |
| 客户端接入凭证 | `client:*` 最小集合 | 桌面客户端注册、心跳、策略、任务、清单和事件上报 |
| MCP 网关凭证 | `mcp:connect`, `mcp:list-tools`, `mcp:call-tools` | MCP Client 访问明确授权的虚拟网关 |

Agent 运行凭证必须绑定一个已登记 Agent。默认采用“Skill 校验接入”最小权限；需要逐次治理与受治理 Memory 时选择“完整运行治理”，需要同时调用模型时选择“完整运行治理 + 模型调用”或显式增加 `model:chat`。这样同一个 Agent 不需要再持有一枚模型调用凭证。

MCP Client 仍使用独立 MCP 网关凭证，并绑定允许访问的网关列表。它不冒充 Agent 身份；Agent 若同时使用 MCP，需要分别持有 Agent 运行凭证和 MCP 网关凭证。

对象关系上以 Agent 为主档案：先登记 Agent 并绑定默认模型、Prompt 和允许使用的 Skill；随后在统一凭证中心为这个 Agent 签发运行凭证。不要在创建 Agent 时反向选择凭证，避免出现新建流程的循环依赖。

## 接入流程

```text
创建部门 / 用户组
  ↓
配置模型网关和隐私策略
  ↓
提交并审核 Skill
  ↓
创建或审核 Prompt
  ↓
新建 Agent
  ↓
绑定默认模型、Prompt、允许 Skill
  ↓
在统一凭证中心创建 Agent 运行凭证并绑定 Agent
  ↓
外部 Agent 使用 agent_id + access_token 接入运行时校验
```

## 运行流程

外部 Agent 调用运行时接口时必须携带：

```http
Authorization: Bearer <access_token>
X-Agent-ID: risk-agent
```

也可以用 query 参数 `agent_id=risk-agent`。如果 Header 和 query 同时存在但不一致，请求会被拒绝。

运行时校验顺序：

```text
校验 access_token 是否有效
  ↓
校验 token 是否具备对应 scope
  ↓
校验 token 是否绑定当前 agent_id
  ↓
校验 Agent 是否存在且启用
  ↓
校验 Agent 是否绑定该 Skill / Prompt
  ↓
校验 Skill / Prompt 自身状态、签名和工具声明
  ↓
记录审计
```

## 运行时接口

Skill 加载前验签：

```http
POST /api/v1/access/runtime/verify-skill-signature
Authorization: Bearer <agent-runtime-token>
X-Agent-ID: risk-agent
```

Skill 加载许可：

```http
GET /api/v1/access/runtime/can-load/risk-skill
Authorization: Bearer <agent-runtime-token>
X-Agent-ID: risk-agent
```

工具调用许可：

```http
GET /api/v1/access/runtime/check-tool?skill_name=risk-skill&tool_name=Bash
Authorization: Bearer <agent-runtime-token>
X-Agent-ID: risk-agent
```

Prompt 加载许可：

```http
GET /api/v1/access/runtime/can-load-prompt/risk-system-prompt
Authorization: Bearer <agent-runtime-token>
X-Agent-ID: risk-agent
```

Prompt 内容验签：

```http
POST /api/v1/access/runtime/verify-prompt-signature?agent_id=risk-agent
Authorization: Bearer <agent-runtime-token>
```

旧的 `/api/v1/runtime/...` 治理接口已停止使用并返回 `410 Gone`；签名公钥读取接口 `/api/v1/runtime/signing-public-key` 仍保持公开。

## 模型调用

模型网关仍兼容 OpenAI-compatible 调用：

```http
POST /v1/chat/completions
Authorization: Bearer <model-or-agent-token>
```

可调用模型的凭证必须具备 `model:chat`。

Agent 运行凭证具备 `model:chat` 时：

- 若凭证配置了 `allowed_models`，请求模型必须在范围内。
- 若没有配置 `allowed_models`，只允许使用 Agent 的 `default_model`。
- 隐私策略按 Agent 所属部门 / 用户组解析。

Agent 通过模型网关调用模型时，应在请求 `metadata` 中声明 `agent_manager_skill_id`、`agent_manager_skill_version_id` 和 `agent_manager_skill_name`。网关以凭证绑定的 Agent 为可信主体，核对 Skill 是否登记、是否可加载、名称与 ID 是否一致，以及是否授权给该 Agent。当前阶段只生成审计告警，不阻断模型调用；即使登记状态完全匹配，也只标记为“内容未验证”。

## 审计字段

运行时和模型调用审计应至少记录：

- `agent_id`
- 凭证 ID / 前缀 / 名称
- Agent 所属部门
- Skill / Prompt / Tool
- 模型名称
- 允许或拒绝结果
- 拒绝原因
- 来源 IP
- 调用时间

## 旧凭证迁移边界

- 旧 LLM API Key 和旧 Scanner Token 不再允许新建。
- 已有旧凭证暂时保留查询、运行时校验和吊销能力，便于平滑迁移。
- 历史上未绑定 Agent 的 `agent_runtime` 凭证不再允许调用任何运行时或模型接口；请为目标 Agent 重新签发绑定凭证后再切换调用方。
- 新接入统一使用 `amat_` 接入凭证；管理员 JWT 只用于管理面，供应商 API Key 只保存在服务端用于请求上游模型。
