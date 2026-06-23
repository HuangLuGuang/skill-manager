# 模型网关与隐私路由

模型网关把 `rs-router` 的隐私代理能力内置到 Agent Manager 后台中，用于统一代理 OpenAI-compatible Chat Completions 请求，并在请求进入外部模型供应商前做 PII 伪匿名化。

它解决两类问题：

- 外部应用 / Agent 调用 LLM 时，不直接暴露真实隐私数据给模型供应商。
- Agent Manager 自己做 skill / prompt 的 LLM vetting 时，也可以走同一条隐私代理链路并留下审计。

---

## 1. 管理台入口

管理台新增两个页面：

- `模型网关`：管理模型供应商、模型端点、用户、用户组、LLM API Key 和隐私策略。
- `Pipeline Trace`：查看一次请求的四阶段报文。

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
    GW->>GW: 校验 LLM API Key / 模型范围 / 请求大小 / 并发
    GW->>DB: 加载用户组隐私策略与会话映射
    GW->>GW: PII 检测与 token 替换
    GW->>LLM: 发送替换后的 OpenAI-compatible 请求
    LLM-->>GW: 返回含 token 的响应
    GW->>GW: 按映射还原响应
    GW->>DB: 写请求审计、用量、Pipeline Trace
    GW-->>Client: 返回还原后的响应
```

四阶段 Trace：

| 阶段 | 含义 |
|---|---|
| `original` | 客户端原始请求 messages，可能含 PII |
| `masked` | 发送给上游模型前的替换后 messages |
| `masked_response` | 上游模型返回的 token 响应 |
| `final_response` | 反替换后的最终响应 |

网关会处理 OpenAI-compatible `message.content`，也会处理部分客户端或模型返回的 `reasoning_content`。因此历史 assistant 推理字段里重复出现的姓名、邮箱、手机号等敏感信息，也会进入伪匿名和响应还原流程。

---

## 3. 运行时接口

模型网关提供多个 OpenAI-compatible 运行时路径：

| 路径 | 用途 |
|---|---|
| `POST /` | 兼容把 `base_url` 当作完整请求地址直接 POST 的客户端，例如部分自定义 provider |
| `POST /v1/chat/completions` | OpenAI SDK 兼容路径，适合把 `base_url` 指到 Agent Manager |
| `POST /chat/completions` | 兼容部分客户端把 `base_url` 配成不含 `/v1` 时直接拼接的路径 |
| `POST /api/v1/llm/chat/completions` | Agent Manager 命名空间路径，适合内部系统显式调用 |
| `GET /v1/models` | OpenAI-compatible 模型列表，只返回当前 LLM API Key 允许访问的启用模型 |
| `GET /models` | 兼容不含 `/v1` 的模型列表路径 |

客户端配置建议：

- OpenAI SDK / Cherry Studio：优先把 Base URL 配成 `http://127.0.0.1:8000/v1`。
- Hermes 或其他只接受根地址的客户端：可配 `http://127.0.0.1:8000`；如果客户端直接 POST 根地址，网关会兼容 `POST /`，如果客户端自动拼接路径，网关也会兼容 `/chat/completions` 和 `/models`。

请求必须携带模型调用凭证。凭证统一在管理台 `智能体治理 / 凭证管理` 创建，类型选择 `模型调用凭证`：

```http
Authorization: Bearer amk_xxx
```

最小请求示例：

```json
{
  "model": "gpt-4o-mini",
  "conversation_id": "conv-001",
  "metadata": {
    "tenant_id": "customer-a",
    "user_id": "alice"
  },
  "messages": [
    {"role": "user", "content": "张三的邮箱是 zhangsan@example.com"}
  ]
}
```

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

为了兼容部分客户端的占位空值，网关会把请求字段或消息扩展字段中的 `"[undefined]"` / `"undefined"` 清理掉，不会继续透传给上游模型供应商。

`stream=true` 已支持。网关会以 OpenAI-compatible SSE 格式返回：

- 请求入站时仍先完成 API Key 校验、模型范围校验、PII 伪匿名和上游路由。
- 上游每个 `delta.content` chunk 返回时，网关会把占位符实时还原后再下发给客户端。
- 流结束后保存 audit、usage metric 和四阶段 Pipeline Trace；Trace 中的 `masked_response` / `final_response` 会保存聚合后的文本片段。

---

## 4. 模型调用凭证

模型调用凭证在 `智能体治理 / 凭证管理` 页面创建：

- 明文只展示一次。
- 服务端只保存 SHA-256 hash 和 key prefix。
- 创建时自动绑定当前登录用户；运行时按该用户所属用户组解析隐私策略。
- 可配置允许模型列表、过期时间、最大请求体大小 `max_body_kb`、最大并发请求数 `max_concurrent_requests`。
- 可编辑名称、模型范围、过期时间、状态和限额；明文 token 仍只在创建后展示一次。
- Agent 运行凭证默认不能调用模型；只有显式勾选 `model:chat` 后，才可以调用模型网关。

运行时会检查：

- key 是否存在且状态为 `active`
- key 是否过期
- 请求模型是否在 key 的允许模型范围内
- 请求体是否超过 `max_body_kb`
- 当前进程内该 key 的并发请求数是否超过限制

---

## 5. 模型供应商与模型

模型供应商保存 OpenAI-compatible `base_url`、API Key、超时和启用状态。

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
- `entity_rules`：按实体类型配置正则规则，例如为 `PHONE_NUMBER` 或企业自定义员工号配置专用识别模式
- `detect_system_messages`：是否扫描 system 消息
- `allow_bypass`：是否允许请求通过 `metadata.bypass_pii_check=true` 绕过 PII 检测
- `mapping_ttl_days`：伪匿名映射和 Trace 保留时间
- `dp_enabled`、`dp_epsilon`、`dp_min_count`：差分隐私统计参数

默认实体类型：

```text
PERSON,CN_PERSON,PHONE_NUMBER,EMAIL_ADDRESS,CREDIT_CARD,US_SSN,ID_CARD,EMPLOYEE_ID,CUSTOMER_ID,ACCOUNT_ID
```

PII 检测是首版轻量规则：

- 邮箱、电话、信用卡、SSN、身份证、员工号、客户号、账号等使用正则。
- 中文姓名使用常见姓氏 + 1-2 字名的基础规则。
- 英文姓名使用首字母大写词组规则。
- 管理台可在 `隐私策略` 页面按“实体类型 + 正则规则”逐条配置规则。选择一个伪匿名实体类型时，会自动新增对应的实体规则行，例如 `PHONE_NUMBER` 可配置为 `(?<!\d)1[3-9]\d{9}(?!\d)`，`EMPLOYEE_ID` 可配置为 `\bSTAFF-\d{6}\b`。

这不是完整 NER 引擎。生产场景如需更高召回率，可以后续替换为 Presidio 或企业自定义识别器。

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

原始请求审计和 Pipeline Trace 仍保存真实内容，仅限管理员或隐私审计员查看。

---

## 9. 内部 LLM vetting 接入

`agent_manager/core/llm.py` 和 prompt vetting 支持通过环境变量走模型网关；sandbox probe 生成也会在配置了网关时优先走隐私代理：

```bash
export AGENT_MANAGER_LLM_GATEWAY_URL="http://127.0.0.1:8000/v1/chat/completions"
export AGENT_MANAGER_LLM_GATEWAY_API_KEY="amk_xxx"
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

- `stream=true` 支持 SSE 透传和增量反替换；如果客户端中途断开，已完成的并发槽会释放，但未完成请求可能不会写完整 Trace。
- 未知 OpenAI 参数默认拒绝。
- LLM API Key 明文无法找回，只能吊销重建。
- Trace 含原始 PII，应按审计权限和 TTL 管控。
- 差分隐私仅保护统计视图，不等于删除原始审计数据。

---

## 11. 智能上下文压缩

> 详细实施文档见 [headroom-compression-integration.md](headroom-compression-integration.md)

模型网关集成 [Headroom](https://github.com/chopratejas/headroom) 智能压缩，自动压缩发送给 LLM 的消息内容（工具输出、日志、代码等），节省 60-95% Token。压缩在 PII 伪匿名化之后执行，按模型调用凭证粒度可选开启。

### 开启方式

在管理台 `智能体治理 / 凭证管理` 创建模型调用凭证时，打开“开启智能压缩”开关并选择压缩级别（均衡/保守/激进）。

### 如何看到效果

**方式 1 — HTTP 响应头（最快）**:

```bash
curl -s -D - http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer amk_xxx" \
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

关闭或未生效时:
```
x-compression: off
```

**方式 2 — 管理台 Pipeline Trace**:

进入 `Pipeline Trace` 页面，展开一次请求:

- 详情顶部显示绿色提示条：「智能压缩: 节省 2094 tokens (92.4%), 耗时 45ms」
- 展开第 3 阶段「智能压缩后」可对比压缩前后的 messages 差异

**方式 3 — 管理台 API Key 列表**:

API Key 表格中「压缩」列显示当前状态: 紫色标签 `auto` / `conservative` / `aggressive`，或灰色「关闭」。
