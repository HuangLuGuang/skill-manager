# 智能体治理接入与运行流程

Agent Manager 的治理对象从单个 Skill 扩展到智能体。平台需要回答：

- 哪个部门的哪个 Agent 在运行。
- 这个 Agent 可以使用哪些模型、Prompt 和 Skill。
- 调用方是否能证明自己就是这个 Agent。
- 每次加载、调用和模型请求是否可审计。

## 登记与接入 / Registration and integration

“智能体管理”按记录来源区分“平台创建”和“客户端发现”。平台创建为外部 Agent 程序登记治理身份及模型、Skill 和 MCP 授权，任务由运行端执行。客户端发现由 Agent Manager Client 自动登记本机 Agent，清单来自客户端上报。来源分类与模型、Skill、MCP、轨迹等接入能力分别管理。

Agents distinguishes **Platform-created** identities registered for external Agent programs from **Client-discovered** identities registered automatically from Client inventory. The runtime executes tasks. Record source is independent of model, Skill, MCP and trace capabilities.

智能体列表的名称、来源、部门 / 负责人、运行位置、能力资产、状态和最近更新 / 发现支持点击列名切换升序、降序和默认顺序，按当前筛选结果整体排序后分页。来源升序为平台创建在前；部门相同时按负责人排序；运行位置按当前展示的客户端名称排序。能力资产按平台已分配或客户端发现的 Skill 数量排序，暂无当前清单的记录在升序时排在零值之前；状态按草稿、启用、停用排序；时间按列表展示的发现或更新时间排序，缺失时间在升序时排在前面。能力资产和状态列的信息图标提供排序依据说明。

**English:** Click Agent, Source, Department / Owner, Runtime location, Capability assets, Status or Last updated / discovered to cycle through ascending, descending and default order. Sorting covers the full filtered result before pagination. Source places platform-created Agents first in ascending order. Department ties are sorted by owner; runtime location uses the displayed client name. Capability assets uses assigned or discovered Skill count, with unavailable inventories before zero counts in ascending order. Status sorts draft, active, then disabled. Dates use the displayed discovery or update timestamp, with missing dates first in ascending order. Information icons explain the capability and status sort criteria.

### 何时需要创建 / When registration is needed

当你要按某个 Agent 单独授权 Skill、限制模型或 MCP 访问、记录调用归属，或使用 Agent Skill Verifier / 运行时校验接口时，需要平台 Agent 身份。**只有尚无身份且本次不通过客户端自动发现登记时，才需手动创建。** 列表中已有记录就复用；新增模型或 MCP 等能力时仍使用同一身份。

普通应用只调用模型或 MCP、Scanner 只扫描提交 Skill 时，可直接创建对应凭证。平台 Agent 档案适用于需要身份治理的运行端；任务仍由自研程序、框架应用或已有 Agent 产品执行。只有业务想法时可以先登记档案，但还需准备实际程序并完成接入才能运行任务。

**English:** A platform Agent identity is required for Agent-specific Skill authorization, model / MCP access and attribution, or Agent Skill Verifier / runtime verification APIs. **Register manually only when no identity exists and you are not registering through Client discovery.** Reuse existing records when adding capabilities. Ordinary model or MCP apps and Skill Scanner can use their respective credentials directly. Registration stores a governance record; a custom program, framework application or existing Agent product must execute tasks.

### 按场景选择接入 / Choose by scenario

在“接入与运行”按下表选路线。身份来源与能力分别管理：平台创建与客户端发现都可在其支持的运行端接入相应能力。

| 你的实际场景 | 是否手动创建 | 接入方式与下一步 |
|---|---|---|
| 自研服务 / 框架应用，能修改加载和执行代码 | 无身份时创建 | 选择“自研 Agent / 框架应用”；签发 Agent 运行凭证，在真实 Loader / Dispatcher 调用 Runtime API，需要轨迹时接 SDK。 |
| 管理员工电脑或工作站上的 Agent、Skill 和配置 | 先连接客户端，由发现流程登记支持的 Agent | 选择“电脑上已有的 Agent”；用客户端凭证连接并上报清单。运行能力使用独立的 Agent 运行凭证。 |
| 宿主支持本地 Skill 指令和脚本，需要逐次校验 Skill | 复用已有身份，无身份时创建 | 选择“Agent Skill Verifier 接入”；授权批准 Skill，签发两项校验权限凭证，安装、配置启动环境并验证通过与拒绝。 |
| 普通应用只调用模型，不要求 Agent 身份治理 | 无需 | 选择“现有应用接入模型网关 → 普通应用调用”；签发模型调用凭证，配置地址与模型名。 |
| 普通 MCP Client 只调用网关工具，不要求 Agent 身份治理 | 无需 | 选择“现有应用接入 MCP 网关 → 普通应用调用”；签发 MCP 网关凭证，配置允许网关与连接。 |
| 模型 / MCP 调用需要按 Agent 授权和审计 | 复用已有身份，无身份时创建 | 在模型 / MCP 场景选择“按 Agent 身份治理”；使用绑定 Agent 的运行凭证并授予对应权限。 |
| 只扫描、提交本地 Skill | 无需 | 使用 Scanner 接入凭证，按 Scanner 指引配置扫描上传。 |

**English:** Choose a route in Integration & runtime. Identity source and integration capability are independent.

| Actual scenario | Manual registration? | Integration and next action |
|---|---|---|
| Custom service / framework with editable loading and execution code | If no identity exists | Custom Agent / framework: issue a bound runtime credential and call Runtime APIs at the Loader / Dispatcher; add the SDK for traces. |
| Manage Agents, Skills and configuration on computers | Connect the Client to discover and register supported Agents first | Agent on a computer: connect using a Client credential and report inventory. Runtime capabilities use separate Agent runtime credentials. |
| Host supports local Skill instructions and scripts; verify every use | Reuse an identity or register one | Agent Skill Verifier: authorize the approved Skill, issue the two-scope credential, install, configure the launch environment and test allow / deny outcomes. |
| Ordinary model calls without Agent governance | No | Model gateway for an app → Ordinary application: issue a model credential, set endpoint and model. |
| Ordinary gateway tool calls without Agent governance | No | MCP gateway for an app → Ordinary application: issue an MCP credential and configure allowed gateways and connections. |
| Model / MCP calls require Agent-specific authorization and audit | Reuse an identity or register one | Choose Use Agent governance in the model / MCP scenario and grant the required scopes to its bound runtime credential. |
| Only scan and submit local Skills | No | Use a Scanner credential and follow Scanner scanning / upload setup. |

客户端管理、Skill 校验、模型调用和 MCP 调用可以组合。若要求校验失败后强制阻止加载，应在真实加载位置接 Runtime API，或接入宿主支持的 Hook 并验收拦截范围。Verifier 依赖宿主每次调用校验脚本；模型 / MCP 网关只覆盖经过它们的请求。详细步骤见[外部 Agent 集成](external-agent-integration.md)和[签名验签说明](agent-signature-verification.md)。

Client management, Skill verification, model calls and MCP calls can be combined. Enforced blocking requires checks at the actual loading boundary, or a supported host Hook with validated interception coverage. Verifier depends on the host executing its script each time. Model / MCP gateways govern requests passing through them. See [external Agent integration](external-agent-integration.md) and [signature verification](agent-signature-verification.md).

### 创建表单怎么填 / Fill in the registration form

1. **先查找已有身份。** 列表中已有记录或客户端已经发现时，复用该身份。尚无身份时，在“智能体管理”点击“登记智能体”。
2. **填写基本信息。** Agent ID 和名称必填，例如 `expense-assistant` / “报销助手”；部门、负责人和描述按需填写。准备接入时选择“启用”，暂存配置可选“草稿”。状态表示治理身份是否可用，不表示进程已启动。
3. **按用途选能力。** 模型、Skill、MCP 可以分别配置或组合使用。只用 Verifier 时保留内置模型来源，默认模型留空，选择批准的 Skill；只用 MCP 时选择所需网关，模型和 Skill 可留空。Skill 选择应对应运行端将安装的批准版本；MCP 可通过“查看工具”核对范围。
4. **需要模型时完成来源配置。** 内置来源直接选择管理员已配置的默认模型。外部 AI 网关须先选择网关，点击“准备并刷新模型”，从返回目录选择默认模型后再保存；准备操作会先创建草稿及外部身份。
5. **保存身份。** 点击“保存并查看接入指引”；有接入与运行权限时进入当前 Agent 的指引，也可从列表或详情重新打开。只用 Verifier 时在“接入与运行”选择“Agent Skill Verifier”和刚创建的身份。
6. **签发凭证并接入。** 指引生成建议权限，在统一凭证中心确认身份、权限和资源范围后创建。Verifier 需要 `runtime:verify-signature` 和 `runtime:can-load`；模型和 MCP 权限按用途增加。保存一次性明文后返回指引，在实际运行端安装组件、配置连接，发起调用并核对审计。

**English:**

1. **Find an existing identity first.** Reuse a registered or Client-discovered record. Otherwise choose **Register Agent** in Agents.
2. **Fill in basic information.** Agent ID and name are required, for example `expense-assistant` / “Expense assistant”. Department, owner and description are optional. Choose Active when ready to connect or Draft while preparing. Status describes identity availability, not a running process.
3. **Select capabilities by purpose.** Configure model, Skill and MCP access independently or together. For Verifier only, keep the internal source, leave the default model empty and select an approved Skill. For MCP only, select gateways and leave model and Skill selections empty. Match Skill selection to the approved version installed in the runtime; use **View tools** to inspect gateway access.
4. **Complete model setup when needed.** Select an administrator-configured internal model, or choose an external gateway, click **Prepare and refresh models**, then select a returned default model before saving. Preparation first creates a draft and external identity.
5. **Save the identity.** Choose **Save and view integration guide**. Access to Integration & runtime is required to continue there; list and detail views can reopen the guide. For Verifier only, select **Agent Skill Verifier** and the newly created identity in Integration & runtime.
6. **Issue a credential and connect.** Confirm the suggested identity, scopes and resource limits in Credential Center. Verifier requires `runtime:verify-signature` and `runtime:can-load`; add model or MCP scopes as needed. Save the one-time secret, return to the guide, install components and configure the actual runtime, then make a call and inspect audit records.

例如“报销助手”本次只需校验报销 Skill：填写身份和名称，选中该批准 Skill，保存后签发两项校验权限的运行凭证，再到实际 Agent 中安装并配置 Verifier。保存记录、关联凭证、实际调用成功是三个不同的进度点。

For an Expense assistant that only verifies an expense Skill, fill in identity and name, select the approved Skill, save and issue a runtime credential with the two verification scopes, then install and configure Verifier in the actual Agent. A saved record, a linked credential and a successful runtime call are separate completion points.

内置模型网关使用平台地址与运行凭证；外部网关模型先通过 `GET /api/v1/runtime/external-model/credential` 领取配置，再使用返回的 `model_base_url`、`model` 和 `api_key` 直连外部网关。Skill 文件由运行端安装，并在加载前计算摘要、调用验签与 `can-load`；工具执行前按需接入 `check-tool`。具体接口与摘要算法见[签名验签说明](agent-signature-verification.md)。

For the internal model gateway, configure the platform endpoint and runtime credential. For an external gateway model, first retrieve configuration from `GET /api/v1/runtime/external-model/credential`, then call the external gateway using its returned `model_base_url`, `model` and `api_key`. Install Skill files in the runtime, compute their digest and call signature verification plus `can-load` before loading. Add `check-tool` before tool execution as needed. See the [signature verification guide](agent-signature-verification.md).

“已有关联凭证”只表示凭证记录存在，状态、有效期及权限须在凭证中心核对。实际接入分别核对：内置模型的 Pipeline Trace、外部网关自身调用审计、Skill 运行审计、MCP 审计，以及启用后由 SDK 上报的调用轨迹。Skill 审计中的 Agent ID 搜索属于关键词检索，应继续核对记录中的实际身份。复制模板、保存配置或发现本机 Agent 都不能代替真实调用证据。

**Linked credential exists** only confirms a stored credential record; check validity, expiry and scopes in Credential Center. Verify each capability using internal model Pipeline Trace, the external gateway’s own audit, Skill runtime audit, MCP audit or SDK traces when enabled. Agent ID in Skill audit is a keyword search; verify the actual identity in each result. Copied templates, saved configuration and inventory discovery do not establish successful runtime calls.

## MCP 工具访问 / MCP tool access

在平台智能体的创建或编辑页，使用 **MCP 工具访问（可选）** 多选已启用的虚拟网关，并通过“查看工具”核对来源服务和审批要求。工具清单只展示当前已发布、Schema 与批准快照一致且策略允许的工具；清单随网关配置变化。原有已停用或删除的网关会保留提示，可由用户移除。去配置网关的链接在新标签页打开，保留当前表单草稿。

**English:** In Agent registration or editing, use **MCP tool access (optional)** to select active virtual gateways. **View tools** shows source servers and approval requirements for currently published, schema-approved, policy-allowed tools. The list follows gateway changes. Existing disabled or missing gateways remain visible for removal. Gateway configuration opens in a new tab to preserve the form draft.

保存后，接入步骤按所选能力生成。在统一凭证中心创建绑定该 Agent 的运行凭证，确认 `mcp:connect`、`mcp:list-tools`、`mcp:call-tools` 和网关子集。凭证只能授权智能体范围内的网关；新增 Agent 网关不会自动扩大旧凭证。移除网关或停用 Agent 后，后续 MCP 请求重新校验并拒绝访问。实际工具调用还受网关发布范围、Schema 和审批策略约束。

**English:** After saving, the guide generates steps for selected capabilities. Issue an Agent-bound runtime credential with `mcp:connect`, `mcp:list-tools`, `mcp:call-tools` and a subset of the Agent's gateways. Adding an Agent gateway does not widen existing credentials. Removing one or disabling the Agent is enforced on subsequent MCP requests. Published tools, approved schemas and approval policies still govern calls.

凭证表单的 MCP 操作分为网关操作和智能体配置两组：先在新标签页编辑智能体 MCP 授权，返回后点击“刷新配置”读取最新授权；“刷新网关”更新网关与工具清单。两组操作独立排列，窄屏自动换行。

**English:** The credential form separates gateway actions from Agent configuration actions. Edit the Agent's MCP grants in a new tab, then return and refresh configuration to retrieve the latest grants. Refresh gateways to update the gateway and tool list. The action groups are spaced separately and wrap on narrow screens.

“连接 MCP 工具”步骤为每个网关提供 `${PLATFORM_URL}/mcp/${GATEWAY_SLUG}`、Streamable HTTP 传输和 `Authorization: Bearer <AGENT_RUNTIME_TOKEN>`。在实际运行环境中配置后，先读取工具列表，再按需试用合适的工具并查看结果；需要审批的调用先完成审批。普通非 Agent MCP 应用仍使用独立 MCP 网关凭证。

**English:** **Connect MCP tools** provides each gateway's `${PLATFORM_URL}/mcp/${GATEWAY_SLUG}` URL, Streamable HTTP transport and `Authorization: Bearer <AGENT_RUNTIME_TOKEN>` header. Configure the actual runtime, read its tool list, then try an appropriate tool as needed and inspect the result. Obtain approval where required. Ordinary non-Agent MCP apps continue to use MCP gateway credentials.

高风险工具审批同时支持 Agent 运行凭证和普通 MCP 网关凭证。管理员审批时与实际调用时都会校验 Agent 当前允许的网关范围；已有审批不会恢复已移除的授权。

**English:** High-risk tool approvals support both Agent runtime credentials and ordinary MCP gateway credentials. Approval and execution both check the Agent's current gateway grants; an existing approval does not restore a removed grant.

客户端自动换发运行凭证时，MCP 范围取现有凭证与 Agent 当前授权的交集，并只保留已启用的网关。

**English:** When a Client automatically rotates a runtime credential, MCP access is restricted to active gateways in both the existing credential and the Agent's current grants.

详情页的 MCP 区域分别显示网关配置、有效凭证的权限覆盖情况和最近 10 条工具调用。凭证权限已配置表示存在已启用、未过期且具备上述三个权限的凭证；来源 IP、Agent 状态及网关策略仍可能限制运行。新调用按调用时凭证绑定的 Agent 身份记录，后续改绑不会改变归属；未记录身份的历史调用仅保留在全局 MCP 审计中。平台配置和工具列表读取均不代表工具调用成功。

**English:** Agent details separates gateway configuration, valid credential coverage and the latest ten tool calls. Configured coverage requires an active, unexpired credential with all three MCP scopes; IP rules, Agent state and gateway policies still apply. New calls capture the Agent binding at call time, preserving attribution if credentials are rebound. Historical calls without an identity remain in global MCP audit. Saved settings and tool listing do not prove a successful tool call.

升级时，已有 Agent 的 MCP 范围一次性取其已启用、未过期且具有 MCP 权限的运行凭证网关并集；每张凭证自身的范围保持不变。后续启动不会重新补回已移除的授权。新 Agent 默认未配置 MCP 网关。

**English:** On upgrade, existing Agents receive the union of gateway grants from active, unexpired runtime credentials with MCP scopes once. Individual credential scopes remain unchanged. Later startups do not restore removed grants. New Agents start with no MCP gateways configured.

## 核心对象

| 对象 | 作用 |
|---|---|
| 部门 / 用户组 | 业务归属和隐私策略边界 |
| Agent | 外部运行主体的平台治理身份，例如风险筛查智能体 |
| Skill | 经过提交、扫描、审核后的可加载能力 |
| Prompt | 经过治理后可绑定给 Agent 的提示词 |
| 模型 | 模型网关中配置的模型端点 |
| 凭证 | 证明调用方身份，并限制可执行权限 |

## 凭证类型

统一在管理台 `智能体管理 / 统一凭证中心` 创建凭证。页面先按真实调用者提供五条路线：Agent、普通模型应用、非 Agent MCP Client、Skill Scanner 和客户端；选择路线后再配置身份绑定、资源范围与高级安全限制，不需要先记住内部凭证类型。

| 类型 | 默认权限 | 用途 |
|---|---|---|
| 模型调用凭证 | `model:chat` | 非 Agent 应用调用模型网关 |
| Agent 运行凭证 | `runtime:*`；可增加 `model:chat`、`mcp:*` | 已登记 Agent 的 Skill、Prompt、Tool、模型和 MCP 运行时访问 |
| Scanner 接入凭证 | `scanner:submit`, `scanner:read-own-results`, `scanner:read-own-sessions` | 客户侧扫描器提交 Skill |
| 客户端接入凭证 | `client:*` 最小集合 | 桌面客户端注册、心跳、策略、任务、清单和事件上报 |
| MCP 网关凭证 | `mcp:connect`, `mcp:list-tools`, `mcp:call-tools` | MCP Client 访问明确授权的虚拟网关 |

Agent 运行凭证必须绑定一个已登记 Agent。默认采用“Skill 校验接入”最小权限；需要逐次治理时选择“完整运行治理”，需要同时调用模型和 MCP 时选择“完整运行治理 + 模型 + MCP”，或显式增加 `model:chat`、所需 `mcp:*`，并限制允许模型与网关。这样同一个 Agent 可以使用一张复合运行凭证，身份仍由 `bound_agent_id` 唯一确定。Memory 接口当前不在默认方案中，只有明确接入时才应通过自定义权限授予 `runtime:memory`。

非 Agent MCP Client 仍使用独立 MCP 网关凭证，并绑定允许访问的网关列表。已登记 Agent 可以直接使用带 MCP scope 和网关允许列表的复合运行凭证，不需要再持有第二张 MCP 凭证。客户端接入凭证只负责主机注册和任务同步，不能替代 Agent 运行凭证调用模型或 MCP；创建客户端凭证时可显式允许它通过具体配置任务，为本机已绑定 Agent 自动创建独立运行凭证。该授权默认关闭，吊销父客户端凭证时会自动吊销它生成的运行凭证。

先登记 Agent 身份，按实际用途选择模型、Skill 和 MCP 范围；随后在统一凭证中心为这个 Agent 签发运行凭证。

Register the Agent identity and select model, Skill and MCP access as needed, then issue its runtime credential in Credential Center.

## 接入流程 / Integration sequence

```text
查找已有 Agent 身份，或填写 Agent ID 和名称登记
  ↓
按需准备并选择模型、批准的 Skill、MCP 网关
  ↓
保存身份和授权，打开接入指引
  ↓
按用途选择步骤，在凭证中心签发绑定该 Agent 的运行凭证
  ↓
在实际运行端安装组件、配置地址与凭证
  ↓
发起真实调用，核对结果与审计
```

**English:** Reuse or register an identity → select capabilities as needed → save and open the guide → issue an Agent-bound runtime credential → configure the actual runtime → make a real call and inspect its result and audit.

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
