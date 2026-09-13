# 模型网关与隐私路由

模型网关把 `rs-router` 的隐私代理能力内置到 Agent Manager 后台中，用于统一代理 OpenAI-compatible Chat Completions 请求，并在请求进入外部模型供应商前做 PII 伪匿名化、Prompt 防护和智能上下文压缩。

它解决两类问题：

- 外部应用 / Agent 调用 LLM 时，不直接暴露真实隐私数据给模型供应商。
- Agent Manager 自己做 skill 的 LLM vetting 时，也可以走同一条隐私代理链路并留下审计。
- 真实调用时检测提示词注入、系统提示词泄露、凭据外传等 Prompt 风险，不要求用户额外上传 Prompt 模板。

---

## 客户端模型切换 / Client model switching

模型切换自动创建的运行凭证，其 Prompt 防护默认仅记录，模式与 LLM 复核开关由平台默认客户端策略或单客户端覆盖配置。保存策略会更新已有有效自动凭证；新建和轮换凭证继承当前值。网关后续请求使用新配置，桌面端通过既有长轮询同步策略和版本。LLM 复核目前只保存开关，尚未执行模型复核。详见[客户端策略](agent-manager-client.md#prompt-防护--prompt-guard)。

Prompt Guard defaults to log only for automatically issued model-switching credentials; settings come from the default or per-client policy. Saving updates active automatic credentials; issuance and rotation inherit the current values. Subsequent gateway requests use the new settings, while desktop clients synchronize the policy and version through existing long polling. The LLM review flag is stored but does not currently execute a review. See [client policies](agent-manager-client.md#prompt-防护--prompt-guard).

## 1. 管理台入口

Agent 风险扫描和大模型红队扫描在发起时必须选择评估模型。列表读取网关中模型及供应商均已启用的模型，预览、创建和执行时再次校验。
Worker 使用任务租约调用 Backend 的任务专属 OpenAI-compatible 评估接口，只能调用该任务选择的模型；租约失效、任务取消或 Worker 停用后拒绝新调用。
评估接口复用模型网关隐私处理和审计，使用任务所有者及用户组作为策略上下文，并执行请求大小与任务并发限制。供应商密钥保留在 Backend。
定时扫描保存所选模型；历史计划需要补选评估模型后重新保存。

管理台入口：

- `模型网关`：管理模型供应商、模型端点、用户组策略绑定、隐私策略和 Prompt 防护配置。
- `统一凭证中心`：创建模型调用凭证，并在凭证上开启 Prompt 防护和智能压缩。
- `隐私链路追踪`：查看一次请求的 Prompt 防护、脱敏、压缩、响应和还原过程。

“供应商与模型”统一在 `/model-gateway/providers` 管理，原 `/model-gateway/models` 地址重定向到该页面。
新建供应商保存后自动获取模型列表，也可点击“获取模型”重新读取。在获取结果中可多选并批量添加，也可逐个添加、测试模型；已添加的模型不可重复勾选，批量操作失败的条目保留勾选以便重试。
页面以供应商分组展示一个列表，头部提供凭据配置、获取模型和添加模型入口。模型列表默认收起，点击模型数量展开后显示模型名称、上下文大小、
默认标记、启用开关、编辑和逐模型测试操作。自定义添加可填写模型名称、上下文窗口、输出限制和默认模型。
默认模型及其所属供应商分别显示“默认模型”和“默认供应商”标识；列表收起时也展示默认模型名称。默认供应商由默认模型归属确定。
模型按“供应商 + 上游模型名”判重，不同供应商可以添加同名模型；发现列表中的“已添加”仅指当前供应商。每条配置另有全局唯一的网关调用名称：第一次添加时默认沿用上游模型名，重名时自动生成供应商前缀，也可以在创建时填写。创建后调用名称固定，编辑上游模型名或供应商不会改变凭证和配置中的调用绑定。

凭证可用模型、文档助手、Skill 扫描策略、智能体默认模型、客户端模型切换、MCP/Agent 安全扫描及 Dify 意图分析均使用网关调用名称；选择器同时显示供应商、上游模型和调用名称。网关 `/v1/models` 返回调用名称，转发到上游时改用上游模型名，响应、用量及审计保持网关调用名称。

统一凭证中心按供应商分组展示已添加到网关的模型，支持按供应商或模型名称搜索；同一张凭证对每个上游模型名只能选择一个供应商，不同名称的模型可跨供应商选择。进入创建配置或点击刷新会重新加载模型选项；供应商下尚未添加的模型需先在“供应商与模型”中添加。

**English:** The Credential Center groups registered gateway models by provider and supports searching by provider or model and selecting one provider per upstream model name in each credential. Models with different upstream names may use different providers. Entering credential configuration or refreshing reloads the model options. Register models under their provider before selecting them in a credential.

旧数据迁移保留原调用名称、模型 ID、默认模型及权限引用，将原名称回填为上游模型名。无需批量修改历史凭证或客户端配置。

**English:** Models are unique by provider and upstream model name. Discovery marks only models registered with the current provider as added. Each configuration has a unique gateway model name, generated from the upstream name or a provider prefix, or entered at creation. This caller-facing name remains fixed to preserve bindings. Credentials, documentation settings, Skill policies, Agent defaults, client switching and security evaluators store gateway names. Selectors show the provider and model identity. Requests use the upstream name only at the provider boundary; responses and audits keep the gateway name. Migration preserves existing names, IDs and references.

管理员接口 `GET /api/v1/model-providers/{provider_id}/models` 使用服务端保存的供应商凭据读取上游 `/models`，
支持 OpenAI Chat Completions、Responses API 的模型列表及 Anthropic 游标分页。Base URL 保留配置的版本路径，若填写完整推理端点则替换其端点后缀。
供应商不支持列表接口、连接失败或返回格式错误时，页面提示重试或自定义添加。
每个模型的“测试”入口复用供应商真实推理测试接口，显示 HTTP 状态和耗时；测试会消耗少量模型额度。

隐私链路 Trace 会保存原始 PII。统一 Runtime Trace 默认返回脱敏投影；原始 Payload 仅
`admin`、`super_admin`、`privacy_auditor` 可以显式查看或导出原始内容，相关动作写入防篡改审计链；
`security_auditor` 只查看脱敏投影。

---

## 2. 核心流程

```mermaid
sequenceDiagram
    participant Client as "Client / Agent"
    participant GW as "Agent Manager 模型网关"
    participant DB as "SQLite"
    participant LLM as "上游模型供应商"

    Client->>GW: POST /v1/chat/completions
    GW->>GW: 校验模型调用凭证 / 模型范围 / 请求大小 / 并发
    GW->>GW: Prompt 防护规则检测
    alt 高风险阻断
        GW->>DB: 写阻断审计与隐私链路追踪
        GW-->>Client: 403
    end
    GW->>DB: 加载用户组隐私策略与会话映射
    GW->>GW: PII 检测与 token 替换
    GW->>LLM: 发送替换后的 OpenAI-compatible 请求
    LLM-->>GW: 返回含 token 的响应
    GW->>GW: 按映射还原响应
    GW->>DB: 写请求审计、用量、隐私链路追踪
    GW-->>Client: 返回还原后的响应
```

Trace 阶段：

| 阶段 | 含义 |
|---|---|
| `prompt_security` | Prompt 防护结果、风险等级、处理动作和命中规则 |
| `original` | 客户端原始请求 messages，可能含 PII |
| `masked` | 发送给上游模型前的替换后 messages |
| `compressed` | 智能上下文压缩后的上游 messages |
| `masked_response` | 上游模型返回的 token 响应 |
| `final_response` | 反替换后的最终响应 |

网关会处理 OpenAI-compatible `message.content`，也会处理部分客户端或模型返回的 `reasoning_content`。因此历史 assistant 推理字段里重复出现的姓名、邮箱、手机号等敏感信息，也会进入伪匿名和响应还原流程。

---

## 3. 运行时接口

模型网关同时提供 OpenAI-compatible 和 Anthropic-compatible 入口：

| 路径 | 用途 |
|---|---|
| `POST /v1/chat/completions` | OpenAI SDK 兼容路径，适合把 `base_url` 指到 Agent Manager |
| `POST /chat/completions` | 兼容部分客户端把 `base_url` 配成不含 `/v1` 时直接拼接的路径 |
| `POST /api/v1/llm/chat/completions` | Agent Manager 命名空间路径，适合内部系统显式调用 |
| `POST /v1/messages` | Anthropic Messages 兼容路径，适合 Claude Code 和 Anthropic SDK |
| `POST /v1/responses` | OpenAI Responses 兼容路径，适合 Codex 自定义 model provider；请求在网关内转换后复用同一模型校验、隐私与审计链路 |
| `GET /v1/models` | 模型列表：Bearer 默认返回 OpenAI 格式；携带 `anthropic-version` 或 `x-api-key` 时返回 Anthropic 格式及游标分页 |
| `GET /models` | 兼容不含 `/v1` 的模型列表路径 |
| `GET /v1/models/{model_id}` | 查询当前凭证可访问的模型详情，支持包含供应商前缀的调用名称 |
| `POST /v1/messages/count_tokens` | Anthropic 格式的本地 Token 估算，返回 `input_tokens`；`x-token-count-method: estimated-utf8` 表明并非供应商精确计数 |

模型列表和详情同时过滤凭证模型范围、模型启用状态和供应商启用状态。Anthropic 列表支持 `limit`（1–1000，默认 20）、`after_id`、`before_id`，返回 `has_more`、`first_id`、`last_id`；两个游标不能同时使用。Anthropic 接口支持 `x-api-key` 和 Bearer，错误使用 `type: error` 结构。计数接口在本地估算，不发送内容到供应商、不产生推理费用，仍校验凭证、模型范围及请求大小；图片和模型专有分词可能产生较大误差。

**English:** Model lists and retrieval enforce credential scope and enabled model/provider state. Bearer requests return OpenAI model objects; `anthropic-version` or `x-api-key` selects Anthropic objects and cursor pagination (`limit`, `after_id`, `before_id`). Anthropic accepts API-key or Bearer authentication. `/v1/messages/count_tokens` returns a local UTF-8 estimate, identified by `x-token-count-method: estimated-utf8`; it does not call the provider and is not an exact tokenizer count.

客户端配置建议：

- Agent Manager 桌面客户端：不单独填写模型网关地址，而是复用客户端接入时配置的 Agent Manager 地址。Claude Code 使用该根地址；Codex 和 Hermes 自动规范化为以 `/v1` 结尾的 Base URL。该地址指向 Agent Manager 网关，不是下面“供应商”页面配置的上游模型地址。
- OpenAI SDK / Cherry Studio：Docker Compose 默认把 Base URL 配成 `http://127.0.0.1/v1`。
- Hermes 或其他从根地址自动拼接路径的客户端：可配 `http://127.0.0.1`，网关对外提供 `/chat/completions` 和 `/models`。当前 Compose 的根路径由管理台前端使用，不适合会直接 POST 根地址的客户端。
- Claude Code：设置 `ANTHROPIC_BASE_URL=http://127.0.0.1`、`ANTHROPIC_AUTH_TOKEN=amat_xxx`，并把 Claude Code 使用的模型名设置为管理台登记的模型名。
- Codex：在 `~/.codex/config.toml` 配置自定义 `model_provider`，`base_url` 使用 `http://127.0.0.1/v1`，`wire_api = "responses"`。桌面客户端“模型切换”可以自动完成该配置。

Codex 的网关配置需要 `web_search = "disabled"` 和 `[features] image_generation = false`：当前网关提供本地 function/custom/namespace 工具调用转换，不执行供应商侧的网页搜索和图片生成。客户端模型切换会写入这些配置并保留其他配置及备份。Claude Code 使用 `ANTHROPIC_MODEL` 指定已授权的网关调用名称；若使用不同档位的辅助模型，也需要把相应 `ANTHROPIC_DEFAULT_*_MODEL` 指向已授权的网关名称。

**English:** For Codex, set `web_search = "disabled"` and `image_generation = false` under `[features]`; these server-side tools are not implemented by the gateway. Managed model switching writes these settings while preserving other settings and backing up the config. Local function/custom/namespace tools remain supported. Claude Code must use authorized gateway model names, including any configured auxiliary model tiers.

请求必须携带带有模型调用能力的凭证。在管理台 `智能体管理 / 统一凭证中心` 的路线图中，普通服务或脚本选择“给应用调用模型”；已登记 Agent 选择“给 Agent 使用”，再选择包含模型能力的方案：

```http
Authorization: Bearer amat_xxx
```

最小请求示例：

```json
{
  "model": "gpt-4o-mini",
  "conversation_id": "conv-001",
  "metadata": {
    "tenant_id": "customer-a",
    "user_id": "alice",
    "agent_manager_skill_id": "skill-family-id",
    "agent_manager_skill_version_id": "skill-version-id",
    "agent_manager_skill_name": "risk-screening"
  },
  "messages": [
    {"role": "user", "content": "张三的邮箱是 zhangsan@example.com"}
  ]
}
```

### 3.1 统一轨迹事件与关联契约

如果调用方已经通过 Runtime Trace SDK 创建会话，可在请求体 `metadata` 中增加关联字段：

```json
{
  "trace_id": "trc_xxx",
  "session_id": "session-001",
  "turn_id": "turn-001",
  "step_id": "step-001",
  "call_id": "call-001",
  "parent_call_id": "call-parent"
}
```

关联字段含义和信任边界：

| 字段 | 生成/传递方 | 用途与约束 |
|---|---|---|
| `trace_id` | Runtime Trace SDK 创建，调用方透传 | 绑定 Agent 的凭证可以关联已有轨迹；普通模型凭证由服务端分配或聚合 `model_only` 轨迹，不能指定已有轨迹 ID |
| `session_id` | Agent Runtime 或模型网关 | SDK 关联路径沿用业务会话；网关聚合路径使用独立生成的 `gws-` 标识，与隐私映射 ID 分开 |
| `turn_id`、`step_id` | Agent Runtime/SDK | 只描述真实存在的 Turn 和 Step；Gateway-only 接入应省略，不能为了界面完整而构造 |
| `call_id` | 发起模型调用的 Agent Step | 关联一次模型 Call；后续 Tool/MCP 调用应生成自己的 `call_id`，并把模型 Call 写入 `parent_call_id` |
| `parent_call_id` | Agent Runtime | 表示嵌套调用父节点，不参与权限判断 |
| `request_id` | 模型网关生成 | 每次模型请求唯一标识；调用方不能指定，响应通过 `x-request-id` 返回，并写入模型审计和 Runtime Trace |
| `agent_id` | 服务端凭证绑定 | 不接受 `metadata.agent_id` 作为身份；只信任 `agent_runtime` 凭证的 `bound_agent_id` |
| `tenant_id` | 服务端凭证归属优先 | 调用方 metadata 可用于隐私映射上下文，但 Runtime Trace 的租户/组归属由已验证凭证收敛，不能用 metadata 越权 |

当前模型入口不读取 `X-Trace-ID`、`X-Turn-ID`、`X-Step-ID`、`X-Call-ID` 等自定义入站关联头；
OpenAI-compatible 请求使用 `metadata`，MCP 请求使用 `params._meta`。`X-Agent-ID` 是部分 Agent
运行治理接口的绑定校验头，也不是模型网关的轨迹关联来源。接入方不能同时维护一套未实现的自定义头并
假设平台会自动关联。

模型网关向统一轨迹发布：

| 事件 | 触发时机 | 脱敏投影中的主要字段 |
|---|---|---|
| `model.request` | 调用完成或失败时，与结果一起发布；阻断时也保留请求 | 模型、脱敏请求、Prompt Security 结果、关联 ID、网关生成的 `request_id` |
| `model.response` | 非流式响应完成，或流式响应正常结束 | 脱敏响应、Token、总耗时、上游耗时、平台耗时；流式有真实首输出时才包含 TTFT |
| `model.error` | 上游或网关处理失败 | 脱敏错误、已测得耗时和关联 ID；不把失败包装成成功响应 |

模型网关同时把 Prompt Security 的风险等级作为事件 `severity` 传入统一轨迹，轨迹按明确严重性汇总，
与 `risk_codes` 的风险分类分别保存。

平台耗时是网关总耗时减去上游耗时。流式请求从进入网关起计算 TTFT，只在首个有效文本、推理文本
或工具参数块到达时记录；非流式请求和未产生有效输出的流式请求不伪造 TTFT。仅使用普通模型凭证时
仍会产生真实 `model_only` 轨迹，但没有 Agent SDK 事件时完整度不会显示为 `full`。

轨迹发布采用 best-effort 边界：发布失败会进入 `/api/v1/runtime-traces/metrics` 的失败计数和
服务端告警日志，但不会把已经成功的模型调用改成失败。

### 3.1.1 网关会话聚合

开启 `RUNTIME_TRACE_ENABLED` 后，新模型请求会在通过凭证、请求大小、并发和模型范围校验后建立调用记录。
调用轨迹页显示聚合方式、请求数量、每次调用的状态、开始时间、消息数量和匹配依据。
每次 HTTP 请求保留独立的 `request_id`；请求序号不代表用户对话轮次。进行中的调用先显示在请求列表，
模型事件在结果可用后追加。页面每三秒刷新选中聚合会话，事件按 `after_seq` 增量读取。

轨迹主区域按请求、用户输入、助手输出和工具调用显示连续记录，右侧详情可查看内容、结果、计时及关联证据。
会话信息、统计和请求关联依据位于可展开区域。搜索定位、事件顺序概览和折叠操作作用于已加载记录，
列表采用固定行高的可视窗口渲染；滚动到底部继续加载事件，也可开启跟随最新。
网关消息历史按相邻请求的共同前缀去重，保留新增消息；历史压缩或分支后的变化部分会重新展示。
工具调用和结果按调用 ID 配对，来自模型消息历史的记录单独标记，不推断工具执行耗时。
展示记录始终引用原始脱敏事件，关联安全发现和导出权限沿用服务端审计契约。
新写入的轨迹脱敏投影保留完整消息数组，结构深度上限为 16，仍执行敏感字段遮蔽、文本裁剪和轨迹存储配额。
历史记录中已裁剪的内容保持原样，页面不自动读取原始 Payload 补齐。

聚合范围由凭证类型和 ID、租户、用户、用户组及绑定 Agent 共同限定。
已绑定 Agent 且显式提供 `metadata.trace_id` 的 SDK 路径仍按原有关联契约处理。
其他请求按以下优先级处理显式会话标识：

1. `metadata.session_id`。
2. 入站请求头 `X-Hermes-Session-Id`。
3. 请求体 `conversation_id`。
4. `metadata.conversation_id`。

同一范围内标识一致的请求归入同一轨迹，即使消息历史已经压缩或变化。
会话标识仅用于关联，不能授予访问权限。`X-Hermes-Session-Key` 表达长期记忆范围，不作为单次会话标识。
聚合请求头不会自动透传上游；隐私映射、审计和响应中的 `conversation_id` 继续按原有规则生成。

缺少显式标识时，网关对进入隐私替换和压缩之前的规范化消息计算链式 SHA-256 前缀指纹。
内容、角色、工具调用和工具结果均参与计算，指纹索引不保存消息正文。每次请求只存一条完整历史指纹，
匹配时以 `(scope_id, history_digest)` 索引批量查找前缀，每批最多 400 个指纹，不逐条查询消息或扫描历史 Payload。
仅匹配包含用户消息的历史；多个会话可以同时作为候选：

| 匹配结果 | 行为 |
|---|---|
| 唯一最长历史前缀 | 续写对应轨迹，记录匹配请求及消息数量 |
| 完全相同的历史 | 关联为重复候选，但保留独立调用，不认定为 HTTP 重试 |
| 最长前缀对应多个轨迹 | 独立建组并标记歧义 |
| 无匹配或历史已压缩、编辑 | 新建推测会话 |

这类会话在界面标为“推测聚合”：复制相同历史的新聊天仍可能被合并，压缩可能导致同一聊天被拆分。
`/new` 只有实际改变传入历史或显式会话标识时才能被网关观察到。

聚合分配使用持久化 SQLite 事务，支持多进程间的一致归组。哈希计算在写事务前完成；SQLite 仍只有一个写入者，
高并发下需要关注锁等待。匹配索引随轨迹保留期清理，旧轨迹不自动回填。

读取接口：`GET /api/v1/runtime-traces/{trace_id}/requests?after_index=0&limit=100`，
返回请求状态、关联依据及分页标记，沿用轨迹的访问权限。列表和详情接口的 `aggregation` 字段提供方式、来源、
请求总数和汇总状态。请求失败、流式断开会更新调用记录；进程被强制终止时，尚未完成的记录可能保留进行中状态。

### 3.2 响应关联与诊断头

这些响应头是诊断信号，不是授权凭证，也不能替代 Runtime Trace 事件：

| 响应头 | 含义 |
|---|---|
| `x-request-id` | 网关生成的请求 ID，可用于模型审计、隐私链路和统一轨迹检索 |
| `x-tenant-id` | 本次隐私路由上下文；不得作为客户端授权判断依据 |
| `x-conversation-id` | 本次会话映射 ID |
| `x-traffic-type` | `pii_checked` 或 `pii_bypass` |
| `x-privacy-policy` | 隐私策略是否启用 |
| `x-prompt-guard` | `off`、检测动作或 `block` |
| `x-compression` | `off`、`enabled-noop` 或 `on` |
| `x-compression-transforms` | 实际应用的压缩变换；没有变化时为 `no-op` |
| `x-compression-saved-tokens`、`x-compression-ratio`、`x-compression-ms` | 只有产生对应测量值时返回的压缩诊断 |

非流式成功响应返回完整诊断头；流式响应在 SSE 建立时返回可确定的头。上游失败时部分头可能不存在，
调用方应优先使用 `x-request-id` 和服务端审计定位，不能把缺少某个诊断头解释为安全控制未执行。

当调用方使用绑定 Agent 的运行凭证时，建议同时提交以上三个 `agent_manager_skill_*` 字段。网关会用凭证绑定关系确定 Agent，再核对 Skill Registry 状态和 Agent 的 Skill 授权范围。第一期仅记录告警，不阻断模型调用：

- `missing`：Agent 请求没有声明 Skill。
- `declared_trusted`：名称、版本、Registry 状态和 Agent 授权匹配，但未验证调用方本地内容。
- `suspicious`：Skill 未登记、名称与 ID 不一致、状态不可加载或未授权给当前 Agent。

这些结果会写入模型调用审计，并在管理台 `模型网关 / Skill 告警`（`/model-gateway/skill-alerts`）集中展示。页面默认只显示 `suspicious`，`missing` 和 `declared_trusted` 分别归入“未声明”和“观察事件”；请求 ID 可以跳转到隐私链路追踪查看上下文。`declared_trusted` 不能等同于签名验证通过。

管理接口 `GET /api/v1/model-gateway/skill-alerts` 支持按时间范围、分类、级别、告警编码、Agent、Skill 名称和模型分页筛选。接口只返回审计元数据，不返回原始 Prompt 或模型响应。

当前允许透传的 OpenAI 参数包括：

- `temperature`
- `top_p`
- `max_tokens`
- `max_completion_tokens`
- `stop`
- `n`
- `presence_penalty`
- `frequency_penalty`
- `logit_bias`
- `tools`
- `tool_choice`
- `response_format`
- `stream_options`
- `seed`
- `user`
- `reasoning_effort`
- `serviceTier`
- `verbosity`

未知字段会被拒绝，避免把高成本或未审计参数无意透传给上游供应商。

`/v1/responses` 当前兼容文本与图片输入、function/custom/namespace 工具、工具结果、`client_metadata`、并行工具开关、常用采样与 reasoning/text 参数，以及文本和工具调用 SSE。流式事件带递增 `sequence_number`，输出达到上限时返回 `response.incomplete`。请求采用无状态模式，客户端每轮携带完整历史并使用 `store: false`；`previous_response_id`、`conversation`、服务端提示模板、引用历史 item、持久化和后台任务会明确返回错误。服务端内置工具、文件输入及 WebSocket 尚未实现。

**English:** Responses supports common Codex metadata, text/image input, function/custom/namespace tools and results, parallel-tool controls, JSON output and SSE lifecycle events. Truncation produces `response.incomplete`. Send full history with `store: false`; state references, stored/background responses, server-side tools, files and WebSocket transport are not implemented. See [Codex provider configuration](https://learn.chatgpt.com/docs/config-file/config-advanced), [DeepSeek Responses compatibility](https://api-docs.deepseek.com/guides/responses_api/) and [Anthropic model pagination](https://platform.claude.com/docs/en/api/models/list).

为了兼容部分客户端的占位空值，网关会把请求字段或消息扩展字段中的 `"[undefined]"` / `"undefined"` 清理掉，不会继续透传给上游模型供应商。

`stream=true` 已支持。网关会以 OpenAI-compatible SSE 格式返回：

- 请求入站时仍先完成 API Key 校验、模型范围校验、PII 伪匿名和上游路由。
- 上游每个 `delta.content` chunk 返回时，网关会把占位符实时还原后再下发给客户端。
- 流结束后保存 audit、usage metric 和隐私链路追踪；Trace 中的 `prompt_security`、`masked_response`、`final_response` 等阶段会保存聚合后的文本片段。

---

## 4. Prompt 防护

Prompt 不再作为主流程里的独立上传资产。平台默认在模型网关运行时处理真实请求，因为这里能看到最终发给模型的 `system` / `user` / `tool` messages。

历史的独立 Prompt Registry 仅作为兼容能力保留，不再作为管理台主流程入口。新接入方应优先使用模型网关运行时 Prompt 防护。

### 开启方式

在管理台 `智能体管理 / 统一凭证中心` 选择“大模型凭证”，或为 Agent 选择包含模型能力的方案，然后在“高级安全设置”中配置 `Prompt 防护`。新建凭据默认“仅记录”，Token 压缩默认关闭。仅记录模式检测风险并记录结果，不因 Prompt 规则命中阻断请求。

普通凭据在此页面创建时配置防护模式；客户端模型切换自动创建的凭据通过“客户端策略”管理，保存策略会更新已有自动凭据，并应用于新建、轮换凭据。客户端通过长轮询同步配置及版本。

In the Credential Center, choose **LLM Credential** or an Agent option with model access, then open **Advanced security settings**. New credentials default to **Log** for Prompt Guard and have Token compression turned off. Log mode detects and records risks without blocking requests because of Prompt rule matches.

Client-issued model-switching credentials are managed through **Client policies**. Saving updates existing automatic credentials and future issuance or rotation; clients synchronize settings and versions through long polling.

![凭据默认防护设置：仅记录，压缩关闭；示例数据](../web/public/docs/screenshots/zh-CN/credential-protection.png)

![Credential protection defaults: Log, compression off; example data](../web/public/docs/screenshots/en-US/credential-protection.png)

| 模式 | 行为 |
|---|---|
| 关闭 | 不检测 Prompt 风险 |
| 仅记录 | 命中规则时写入链路追踪和统计，但不影响请求 |
| 告警放行 | 命中规则时标记告警并放行 |
| 阻断风险请求 | 命中高风险规则或不可信来源的中风险规则时返回 `403`，并写入审计和链路追踪 |

新接入方统一从 `智能体管理 / 统一凭证中心` 的对应调用路线创建和管理凭证。

### 测试方式

管理台 `模型网关 / Prompt 防护测试` 提供轻量测试台。输入一段测试 Prompt 并选择检测模式后，平台只执行同步规则检测，不调用上游大模型，也不会消耗模型 token。

测试结果会展示：

- 最终风险等级。
- 本模式下会执行的动作：仅记录、告警放行或高风险阻断。
- 命中的规则、严重度、判断原因和命中片段。

### 当前检测内容

首版使用轻量规则同步检测，避免每次调用都增加一次 LLM 审查延迟。规则覆盖：

- 忽略、覆盖或绕过系统指令。
- 泄露 system prompt、隐藏指令或内部上下文。
- 输出 API Key、token、密码、私钥等敏感凭据。
- 绕过安全策略、审计、过滤或限制。
- 工具返回内容夹带新的执行指令。

`启用 LLM 复核` 目前作为策略配置项保留，默认不进入同步主链路。后续可以只在规则命中中高风险时触发 LLM 复核，避免成本和延迟不可控。

### 查看结果

- `隐私链路追踪` 列表显示 Prompt 防护风险和处理动作。
- Trace 详情展开 `Prompt 防护` 阶段，可查看命中规则、风险等级、命中片段和是否阻断。
- `平台总览` 的模型网关卡片展示 Prompt 风险事件数和阻断次数。

---

## 5. 模型调用凭证

模型调用凭证在 `智能体管理 / 统一凭证中心` 页面创建。非 Agent 应用选择“给应用调用模型”；Agent 选择“给 Agent 使用”并按需增加模型能力：

- 明文只展示一次。
- 服务端只保存 SHA-256 hash 和 key prefix。
- 创建时自动绑定当前登录用户；运行时按该用户所属用户组解析隐私策略。
- 可配置允许模型列表、最大请求体大小 `max_body_kb`、最大并发请求数 `max_concurrent_requests`、Prompt 防护和可选压缩。
- 管理台当前提供创建、吊销和删除，不提供找回明文或就地编辑；需要调整绑定或限额时应创建替代凭证，再吊销旧凭证。
- Agent 的“只做运行校验”和“完整运行治理”方案默认不能调用模型；只有选择包含模型能力的方案，或在自定义方案中加入 `model:chat` 后，才可以调用模型网关。

运行时会检查：

- key 是否存在且状态为 `active`
- key 是否过期（仅对通过 API 设置了 `expires_at` 的兼容凭证生效；当前统一凭证中心不展示有效期字段）
- 请求模型是否在 key 的允许模型范围内
- 请求体是否超过 `max_body_kb`
- SQLite 原子租约中该 key 的活动请求数是否超过限制；多个 Worker 共享同一数据库文件时使用同一上限，异常退出后的租约会自动过期

---

## 6. 模型供应商与模型

模型供应商保存 `base_url`、上游协议（OpenAI Chat Completions、OpenAI Responses API 或 Anthropic Messages 兼容）、API Key、超时和启用状态。

- `base_url` 必须包含供应商要求的 API 版本路径；网关不会自动插入 `/v1`。
- `openai` 上游追加 `/chat/completions`，`responses_api` 上游追加 `/responses`，`anthropic` 上游追加 `/messages`；如果填写的是完整协议端点则不重复追加。
- 供应商测试要求输入真实模型名称，并向相同协议端点发送一条最多输出 128 Token 的非流式推理请求；只有 `2xx`、响应符合所选协议且包含实际输出时才判定成功，空响应或仅思考内容不算成功。该操作可能消耗少量供应商额度。
- 上游仅支持 OpenAI 时，Anthropic 入站请求会在网关边界转换为 Chat Completions，响应和 SSE 再转换回 Anthropic 格式。
- 当前核心兼容范围为文本、图片 base64、客户端工具调用、流式输出和基础 usage；Anthropic 专有的服务端工具、完整 prompt caching 语义及全部 beta 内容块不承诺兼容。

Responses 上游支持文本与图片输入、function 工具及工具结果、结构化输出、reasoning effort、文本详细程度、普通响应和 SSE。三种客户端入口都先经过网关模型权限与隐私处理，再转换成所选上游格式；Responses 请求使用 `store: false`，输入、输出、缓存和推理 Token 会转换为 Chat Completions usage 字段。`stop`、惩罚参数、`logit_bias`、`seed` 及 `n > 1` 等无法映射的 Chat Completions 参数会返回稳定错误编码。

Claude Code 使用 Responses 上游时，`output_config.effort` 转换为 `reasoning.effort`；开启或自适应 thinking 且未指定强度时使用 `high`，关闭时使用 `none`，实际支持的强度取决于供应商。Anthropic 的精确思考预算、思考展示和签名不跨协议保留；客户端的 keep-all thinking 编辑保留完整输入历史，其他上下文编辑返回不支持错误。

**English:** With a Responses upstream, Claude Code's `output_config.effort` maps to `reasoning.effort`. Enabled/adaptive thinking defaults to `high` when no effort is supplied; disabled thinking maps to `none`. Accepted effort levels depend on the provider. Exact Anthropic thinking budgets, display settings, and signatures are not preserved across protocols. The client's keep-all thinking edit retains the full input history; other context edits are rejected.

| 上游协议 | 推理 API | 模型列表 API |
| --- | --- | --- |
| OpenAI Chat Completions | `POST {base_url}/chat/completions` | `GET {base_url}/models` |
| OpenAI Responses API | `POST {base_url}/responses` | `GET {base_url}/models` |
| Anthropic Messages | `POST {base_url}/messages` | `GET {base_url}/models`，支持 `after_id` 分页 |

模型列表是独立接口，不是 `/responses/models`。兼容服务可能只实现推理接口；能列出模型也不代表当前凭据有调用权限，需要逐个测试。Responses 的响应存取、删除、后台任务、服务端内置工具和会话持久化不在此上游适配范围。

**English:** Select `openai`, `responses_api`, or `anthropic` in the provider settings. Include the API version path in the Base URL; the gateway appends `/chat/completions`, `/responses`, or `/messages`. A full inference endpoint is also accepted. All three formats discover models through the sibling `/models` endpoint; Anthropic pagination uses `after_id`. Model listing and inference are tested independently because listing does not prove permission to invoke a model.

Responses providers support text and image input, function calls and results, structured output, reasoning effort, verbosity, non-streaming responses, SSE, and token usage. Requests pass through the same gateway authorization, privacy and audit pipeline with `store: false`. Unsupported Chat Completions options return a stable error code. Stateful response retrieval/deletion, background jobs, built-in server tools and persistent conversations are outside this adapter's scope.

Provider tests request up to 128 output tokens and require a successful HTTP response with actual output. Empty results or reasoning-only results do not count as success.

协议参考：[OpenAI Responses](https://developers.openai.com/api/reference/resources/responses)、[OpenAI Models](https://developers.openai.com/api/reference/resources/models)、[Anthropic Models](https://platform.claude.com/docs/en/api/models/list)。

供应商 API Key 会加密落库：

- 加密密钥由后台 `SECRET_KEY` 派生。
- API 返回只展示掩码。
- 调用上游时才在内存中解密使用。

模型端点绑定到供应商，并配置：

- 模型名
- 显示名
- 是否启用
- 是否默认
- 上下文窗口
- 最大输出 token

如果请求未指定 `model`，网关会优先使用默认模型。

---

## 7. 隐私策略

隐私策略可绑定到用户组；API Key 创建后自动关联当前用户，运行时会按用户所在的启用用户组查找策略；没有命中用户组策略时使用默认策略。

首版策略项：

- `entity_types`：启用的实体类型
- `entity_rules`：按实体类型配置正则规则，例如为企业自定义员工号配置专用识别模式
- `detect_system_messages`：是否扫描 system 消息
- `allow_bypass`：是否允许请求通过 `metadata.bypass_pii_check=true` 绕过 PII 检测
- `mapping_ttl_days`：伪匿名映射和 Trace 保留时间
- `dp_enabled`、`dp_epsilon`、`dp_min_count`：差分隐私统计参数

默认实体类型：

```text
PERSON,CN_ID_CARD,CN_MOBILE,CN_LANDLINE,CN_BANK_CARD,EMAIL_ADDRESS,IP_ADDRESS,CN_LICENSE_PLATE,CN_USCC,CN_ADDRESS,EMPLOYEE_ID,CUSTOMER_ID,ACCOUNT_ID
```

PII 检测默认按中国业务场景精准率优先：

- 中国居民身份证校验省级地区码、出生日期和校验位。
- 银行卡号使用 Luhn 校验，统一社会信用代码校验末位校验码，IP 地址使用标准地址解析。
- 中文姓名只在“姓名、联系人、负责人”等上下文或“先生、女士、老师”等称谓中识别，不做全文姓氏猜测。
- 座机号和中国地址需要明确中文字段上下文；日期、小数、数字区间不会作为手机号。
- 管理台可继续为员工号、客户号等企业字段配置自定义正则。

---

## 8. 二次替换与多轮会话

网关会为同一 `tenant_id + conversation_id` 复用历史 token 映射。

为了避免 assistant 历史消息中重新出现真实 PII，网关会对 `assistant` / `tool` 历史消息做一次已知值替换；不会对未启用扫描的 `system` 示例文本做全局替换，避免误伤系统提示中的演示内容。

管理台 `隐私审计` 页面默认展示当前有效映射列表，支持按 `Tenant ID`、`Conversation ID`、原始值搜索；列表会显示映射过期时间，并支持删除单条映射。保留会话级映射查询和批量删除接口，供管理员在需要清理某个 conversation 时使用。

---

## 9. 差分隐私统计

差分隐私只用于管理台统计，不扰动真实 prompt 或响应。

统计接口会：

- 在样本数低于 `dp_min_count` 时返回空值。
- 在启用 `dp_enabled` 时给计数加入 Laplace noise。

原始请求审计和隐私链路追踪仍保存真实内容，仅限管理员或隐私审计员查看。

---

## 10. 内部 LLM vetting 接入

`agent_manager/core/llm.py` 和 prompt vetting 支持通过环境变量走模型网关；sandbox probe 生成也会在配置了网关时优先走隐私代理：

```bash
export AGENT_MANAGER_LLM_GATEWAY_URL="http://127.0.0.1/v1/chat/completions"
export AGENT_MANAGER_LLM_GATEWAY_API_KEY="amat_xxx"
```

可选 metadata：

```bash
export AGENT_MANAGER_LLM_GATEWAY_TENANT_ID="agent-manager-internal"
export AGENT_MANAGER_LLM_GATEWAY_USER_ID="agent-manager-vetting"
export AGENT_MANAGER_LLM_GATEWAY_CONVERSATION_ID="vetting-session"
```

如果未配置 `AGENT_MANAGER_LLM_GATEWAY_URL`，系统会保持原有 `LLMConfig` / 系统设置中的直连配置。

---

## 11. 安全边界

- Prompt Guard 支持在请求 `metadata.content_sources` 中按消息顺序传入来源数组，或按消息索引传入对象；可选值为 `system`、`user`、`assistant`、`tool`、`rag`、`file`、`web`。未声明时回退到消息 `role`，其中 `tool`、`rag`、`file`、`web` 按不可信内容处理。
- `stream=true` 支持 SSE 透传和增量反替换；如果客户端中途断开，已完成的并发槽会释放，但未完成请求可能不会写完整 Trace。
- 未知 OpenAI 参数默认拒绝。
- 模型调用凭证明文无法找回，只能吊销重建。旧 LLM API Key 仅保留查询和吊销，不再签发。
- Trace 含原始 PII，应按审计权限和 TTL 管控。
- 差分隐私仅保护统计视图，不等于删除原始审计数据。

### 11.1 隐私链路与统一轨迹不是同一份数据

| 数据面 | 默认查询内容 | 原始数据边界 | 主要用途 |
|---|---|---|---|
| 隐私链路追踪 | `prompt_security`、`original`、`masked`、`compressed`、`masked_response`、`final_response` 各阶段 | 会保存原始 Prompt、响应和 PII；仅 `admin`、`super_admin`、`privacy_auditor` 可查看，必须按高敏数据管理 | 复核 PII 替换、Prompt 防护、压缩和响应还原 |
| 统一 Runtime Trace | 列表和事件接口只返回服务端脱敏投影 | 原始 Payload 与事件索引分离并加密保存；原始查看或导出只允许 `admin`、`super_admin`、`privacy_auditor`，并写安全审计 | 跨 Agent SDK、模型、MCP、知识和治理事件关联 |
| 模型请求审计/用量 | 请求 ID、身份、模型、状态、Token、耗时和风险摘要 | 不向普通审计列表返回 Prompt、响应或 Tool 参数正文 | 运营审计、计量、故障定位和风险统计 |

`security_auditor` 可以读取授权范围内的脱敏 Runtime Trace，但不能读取原始 Payload。普通业务用户只能
读取本人或所属用户组有权访问的轨迹。原始 Runtime Trace JSON 导出还要求重新输入当前密码、确认高敏
数据责任，并使用绑定当前用户和轨迹、5 分钟有效、只能消费一次的授权令牌；PDF 只支持脱敏级别。

调用方已经在请求中拿到明文并不意味着平台可以把它写入普通日志。应用日志、Worker 日志、错误提示和
告警列表只能记录请求 ID、稳定错误码和脱敏摘要。`x-request-id` 是跨模型审计、隐私链路和 Runtime Trace
定位的首选键；它不是访问原始数据的通行证，所有读取仍重新执行角色和归属校验。

---

## 12. 智能上下文压缩

> 历史实施记录见 [headroom-compression-integration.md](headroom-compression-integration.md)，当前行为以本节和实际链路追踪为准。

模型网关集成 [Headroom](https://github.com/chopratejas/headroom) 上下文压缩，在 PII 伪匿名化之后、请求发送给上游模型之前处理 messages。实际节省量取决于内容类型和长度，短上下文可能完全不变；压缩失败时会使用原始 messages 继续调用，因此不能承诺固定节省比例或答案质量不变。

### 开启方式

在 `智能体管理 / 统一凭证中心` 创建带 `model:chat` 能力的凭据时，展开“高级安全设置”，设置上下文压缩开关及均衡（auto）、保守（conservative）或激进（aggressive）级别。网关按本次调用凭据的配置执行压缩。

客户端模型切换自动创建的运行凭据通过“客户端管理 → 客户端策略 → Token 压缩”配置，支持平台默认与单客户端覆盖。保存后更新已有自动凭据；新建和轮换凭据继承当前配置。策略通过现有长轮询同步到桌面端，网关在后续请求中读取已保存的凭据配置。

In the Credential Center, create a credential with `model:chat`, expand Advanced Security Settings, and configure context compression and its balanced (`auto`), conservative, or aggressive level. The gateway uses the calling credential's settings.

For credentials automatically created by client model switching, configure **Client Management → Client policies → Token compression**. Default settings and per-client overrides apply to existing automatic credentials and future issuance or rotation. Long polling synchronizes desktop policy state; subsequent gateway requests use the saved credential settings.

### 如何看到效果

**方式 1 — HTTP 响应头（最快）**:

```bash
curl -s -D - http://127.0.0.1/v1/chat/completions \
  -H "Authorization: Bearer amat_xxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello"}]}' \
  | grep -i x-compression
```

开启压缩且生效时的响应头:
```
x-compression: on
x-compression-saved-tokens: 2094
x-compression-ratio: 92.4
x-compression-ms: 45
```

启用但本次没有产生变换时：
```
x-compression: enabled-noop
```

未启用时返回 `x-compression: off`。

不要只根据统计页或“已启用”判断单次调用。生产验收应按同一个 `x-request-id` 交叉核对
响应头、`original`、`masked`、`compressed`、`masked_response` 和
`final_response`：PII 替换先于压缩；`masked` 和 `compressed` 不应包含原始隐私值；
只有 `x-compression: on` 才表示本次产生了压缩变换。`enabled-noop` 是有效结果，不应
填充虚假的节省量。压缩效果还需要同时验证事实保留、延迟和错误率，不能把单一样本的
压缩比例作为服务承诺。

帮助中心“场景实践 → 模型隐私与压缩”提供使用虚构客户编号、保留域名邮箱和重复客服
记录的请求样本。原始 Trace 仍会保留演练输入，因此示例也不应替换成真实客户数据。

**方式 2 — 管理台隐私链路追踪**:

进入 `隐私链路追踪` 页面，展开一次请求:

- 详情顶部显示本次是否压缩、节省 Token 和耗时；具体数值取决于请求内容
- 展开第 3 阶段「智能压缩后」可对比压缩前后的 messages 差异

## MCP 扫描模型

MCP 源码、动态和多轮红队任务从已启用的网关模型中选择评估模型，并可分别指定分析模型和攻击模型。
元数据检查不需要模型。任务冻结模型名称，Worker 使用任务租约访问
`/api/v1/agent-security/worker/tasks/{task_id}/evaluator/v1/chat/completions`；
Backend 校验任务所有者、租约、所选模型、预算和并发后复用模型网关隐私链路。供应商密钥不下发给 Worker。
MCP 服务调用证据与模型推断分开保存，真实工具响应并不自动证明模型给出的漏洞判断成立。
