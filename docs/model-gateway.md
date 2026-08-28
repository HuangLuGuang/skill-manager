# 模型网关与隐私路由

模型网关把 `rs-router` 的隐私代理能力内置到 Agent Manager 后台中，用于统一代理 OpenAI-compatible Chat Completions 请求，并在请求进入外部模型供应商前做 PII 伪匿名化、Prompt 防护和智能上下文压缩。

它解决两类问题：

- 外部应用 / Agent 调用 LLM 时，不直接暴露真实隐私数据给模型供应商。
- Agent Manager 自己做 skill 的 LLM vetting 时，也可以走同一条隐私代理链路并留下审计。
- 真实调用时检测提示词注入、系统提示词泄露、凭据外传等 Prompt 风险，不要求用户额外上传 Prompt 模板。

---

## 1. 管理台入口

管理台入口：

- `模型网关`：管理模型供应商、模型端点、用户组策略绑定、隐私策略和 Prompt 防护配置。
- `统一凭证中心`：创建模型调用凭证，并在凭证上开启 Prompt 防护和智能压缩。
- `隐私链路追踪`：查看一次请求的 Prompt 防护、脱敏、压缩、响应和还原过程。

Trace 会保存原始 PII，仅 `admin`、`super_admin`、`privacy_auditor` 角色应该访问。

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
| `GET /v1/models` | OpenAI-compatible 模型列表，只返回当前模型调用凭证允许访问的启用模型 |
| `GET /models` | 兼容不含 `/v1` 的模型列表路径 |

客户端配置建议：

- Agent Manager 桌面客户端：不单独填写模型网关地址，而是复用客户端接入时配置的 Agent Manager 地址。Claude Code 使用该根地址；Codex 和 Hermes 自动规范化为以 `/v1` 结尾的 Base URL。该地址指向 Agent Manager 网关，不是下面“供应商”页面配置的上游模型地址。
- OpenAI SDK / Cherry Studio：Docker Compose 默认把 Base URL 配成 `http://127.0.0.1/v1`。
- Hermes 或其他从根地址自动拼接路径的客户端：可配 `http://127.0.0.1`，网关对外提供 `/chat/completions` 和 `/models`。当前 Compose 的根路径由管理台前端使用，不适合会直接 POST 根地址的客户端。
- Claude Code：设置 `ANTHROPIC_BASE_URL=http://127.0.0.1`、`ANTHROPIC_AUTH_TOKEN=amat_xxx`，并把 Claude Code 使用的模型名设置为管理台登记的模型名。
- Codex：在 `~/.codex/config.toml` 配置自定义 `model_provider`，`base_url` 使用 `http://127.0.0.1/v1`，`wire_api = "responses"`。桌面客户端“模型切换”可以自动完成该配置。

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

`/v1/responses` 当前兼容文本与图片输入、function/custom/namespace 工具、工具结果、常用采样与 reasoning/text 参数，以及文本和工具调用 SSE。它不承诺 Responses API 的服务端内置工具、文件输入、后台任务、会话持久化或 WebSocket 语义；即使请求字段因兼容而被接收，也不会绕过模型网关的参数白名单、凭证、模型范围、请求大小、并发、隐私处理和审计。

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

在管理台 `智能体管理 / 统一凭证中心` 选择“给应用调用模型”，或为 Agent 选择包含模型能力的方案，然后在“高级安全设置”中配置 `Prompt 防护`。已签发凭证不支持就地编辑；需要调整时应创建替代凭证，再吊销旧凭证：

| 模式 | 行为 |
|---|---|
| 关闭 | 不检测 Prompt 风险 |
| 仅记录 | 命中规则时写入链路追踪和统计，但不影响请求 |
| 告警放行 | 命中规则时标记告警并放行 |
| 高风险阻断 | 命中高风险规则时返回 `403`，并写入审计和链路追踪 |

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

## 5. 模型供应商与模型

模型供应商保存 `base_url`、上游协议（OpenAI-compatible 或 Anthropic-compatible）、API Key、超时和启用状态。

- 上游支持 Anthropic 时，网关调用供应商的 `/v1/messages`。
- 上游仅支持 OpenAI 时，Anthropic 入站请求会在网关边界转换为 `/v1/chat/completions`，响应和 SSE 再转换回 Anthropic 格式。
- 当前核心兼容范围为文本、图片 base64、客户端工具调用、流式输出和基础 usage；Anthropic 专有的服务端工具、完整 prompt caching 语义及全部 beta 内容块不承诺兼容。

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

## 6. 隐私策略

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

## 7. 二次替换与多轮会话

网关会为同一 `tenant_id + conversation_id` 复用历史 token 映射。

为了避免 assistant 历史消息中重新出现真实 PII，网关会对 `assistant` / `tool` 历史消息做一次已知值替换；不会对未启用扫描的 `system` 示例文本做全局替换，避免误伤系统提示中的演示内容。

管理台 `隐私审计` 页面默认展示当前有效映射列表，支持按 `Tenant ID`、`Conversation ID`、原始值搜索；列表会显示映射过期时间，并支持删除单条映射。保留会话级映射查询和批量删除接口，供管理员在需要清理某个 conversation 时使用。

---

## 8. 差分隐私统计

差分隐私只用于管理台统计，不扰动真实 prompt 或响应。

统计接口会：

- 在样本数低于 `dp_min_count` 时返回空值。
- 在启用 `dp_enabled` 时给计数加入 Laplace noise。

原始请求审计和隐私链路追踪仍保存真实内容，仅限管理员或隐私审计员查看。

---

## 9. 内部 LLM vetting 接入

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

## 10. 安全边界

- Prompt Guard 支持在请求 `metadata.content_sources` 中按消息顺序传入来源数组，或按消息索引传入对象；可选值为 `system`、`user`、`assistant`、`tool`、`rag`、`file`、`web`。未声明时回退到消息 `role`，其中 `tool`、`rag`、`file`、`web` 按不可信内容处理。
- `stream=true` 支持 SSE 透传和增量反替换；如果客户端中途断开，已完成的并发槽会释放，但未完成请求可能不会写完整 Trace。
- 未知 OpenAI 参数默认拒绝。
- 模型调用凭证明文无法找回，只能吊销重建。旧 LLM API Key 仅保留查询和吊销，不再签发。
- Trace 含原始 PII，应按审计权限和 TTL 管控。
- 差分隐私仅保护统计视图，不等于删除原始审计数据。

---

## 11. 智能上下文压缩

> 历史实施记录见 [headroom-compression-integration.md](headroom-compression-integration.md)，当前行为以本节和实际链路追踪为准。

模型网关集成 [Headroom](https://github.com/chopratejas/headroom) 上下文压缩，在 PII 伪匿名化之后、请求发送给上游模型之前处理 messages。实际节省量取决于内容类型和长度，短上下文可能完全不变；压缩失败时会使用原始 messages 继续调用，因此不能承诺固定节省比例或答案质量不变。

### 开启方式

可以在供应商管理中全局启用压缩，也可以在 `智能体管理 / 统一凭证中心` 创建带模型能力的凭证时，展开“高级安全设置”单独启用，并选择均衡、保守或激进。只有供应商启用而凭证没有指定级别时，运行时使用 `auto`。

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
