# Dify Runtime Adapter

节点执行内容：更新接入包并重建 API/Worker 后，节点结束事件上报输入、输出预览和失败原因，可在“智能体列表 → Dify → 行为审计”查看。用户输入、节点执行参数（含代码正文）、模型完整消息与流式回复、最终回复及错误按节点开始顺序展示，失败原因直接显示。长内容分片保存，每项上限 1,024,000 字符，超限、深度超限和未完成明确标注。常见凭证键和 Bearer 值被屏蔽；业务数据仍可能存在。附件展示 Dify 提供的元数据与引用，不下载附件二进制。旧记录缺失的内容不会补录。管控策略使用平台表单设置，支持增删、排序和组合匹配条件。

适配版本：Dify `1.15.0` / graphon `0.5.3`、Dify `1.16.1` / graphon `0.6.0`。将 Python 接入包挂载到 Dify 的 `api` 和 `worker`，通过 `sitecustomize` 安装运行检查点。平台复用运行凭证、RuntimeTask、RuntimeAction、RuntimeApproval 和运行轨迹。

1.16.1 的 Adapter 审批暂停会结束当前响应流，保留原生检查点供恢复；普通暂停和客户端断开仍沿用 Dify 行为。该版本新增的独立 Agent Backend / Local Sandbox 不在此 Python 工作流适配器的已验证范围。进程心跳中的 Dify 版本来自安装器校验的镜像版本。

## 管控范围

### Skill 上传检测与发布准入（Dify 1.16.1）

Dify 1.16.1 的新版 Agent 界面由 web 容器的 `NEXT_PUBLIC_ENABLE_AGENT_V2=true` 启用；官方入口脚本也支持 `ENABLE_AGENT_V2=true`。保留原 Compose 参数并重建 web 后刷新页面。工作流通过“添加节点 → Agent BETA → 从空白开始”创建新版节点，打开“内联配置”设置模型、提示词并“添加 Skill”；也可在左侧“Agents BETA → 创建 → 创建空白应用”创建可复用 Agent。Skill 上传接受 `.zip` 或 `.skill` 包，提示词可用 `/` 引用。已有旧版 Agent 节点不会因此转换。此开关仅打开界面入口，后端、Agent Backend、Local Sandbox 及 Adapter 仍需按各自要求部署。Community Edition 的独立 Agent 预览入口不可用，工作流可通过测试运行验证。

**English:** Enable `NEXT_PUBLIC_ENABLE_AGENT_V2=true` in the Dify 1.16.1 web container (the official entrypoint also accepts `ENABLE_AGENT_V2=true`), recreate web with the original Compose arguments, and refresh. Use Add node → Agent BETA → Start from scratch for an inline Agent, or Agents BETA → Create for a reusable Agent. Configure its model and prompt, upload a `.zip` or `.skill` package under Skills, and reference it with `/`. Existing legacy nodes are not converted. This flag only exposes the UI; backend, Agent Backend, Local Sandbox and Adapter deployment remain necessary. Standalone Agent preview is unavailable in Community Edition; use workflow test runs.

登记新版 Agent 的 App ID 后，更新接入包并重建 API/Worker。运行凭证需同时具备 `runtime:trace` 和 `runtime:govern`。上传配置 Skill 或 drive Skill 时提交规范化完整包，复用平台扫描、内容版本、审核与签名；“智能体详情 → Skill”显示已观察到的包版本和检测报告。这里是检测历史，不是实时文件清单，删除 Dify 中的 Skill 不会删除历史检测记录。

发布 Agent 草稿或含新版 Agent 的工作流时，读取本次配置实际引用的完整包，再校验其内容对应的不可变检测版本。未检测的内容会提交扫描；管控模式下，扫描中、待审批、拒绝、停用、签名不匹配均阻止发布，原发布版本保持。观察模式记录检测状态并允许发布。平台连接失败会使上传或发布校验报错，恢复后可重试；扫描后台执行，无需保持上传请求直到扫描结束。

包经 Base64 传输，受绑定运行凭证的 `max_body_kb` 限制，需为编码后请求预留约原 ZIP 大小的 4/3 加 JSON 开销；Dify 的原生包限制仍有效。扫描选项请求规则、深度扫描、AI 和 Sandbox，实际执行遵循平台开关与策略。文件编辑或导入造成的新内容在发布检查时补交检测。

**English:** On Dify 1.16.1, registered Agent apps submit complete normalized Skill packages to the existing scan/review/signing pipeline. Both runtime scopes are required. Agent details lists observed package versions and report links. Agent draft publication and workflow Agent publication check the actual referenced packages against immutable approved versions. Enforce mode blocks pending, rejected, retired or signature-mismatched content; observe mode permits publication. Unavailable admission services fail the request. Base64 requests must fit the credential body limit. Edited/imported content is checked at publication.

### Agent Backend 运行时检测（Dify 1.16.1）

每次包准入检查在行为审计中保存当次 Skill 名称、认证状态、审批状态、放行/阻断结果和原因。观察模式未认证放行显示黄色“未认证”及放行原因；管控模式显示阻断原因。批准但未通过完整性校验仍为未认证，历史结论不随以后审批变化。升级平台前端及 Agent Backend Adapter 后的新检查生成这些字段，旧事件不补造认证结论。

**English:** Each admission check records the Skill name, certification and approval states, decision and reason. Observe-mode exceptions remain marked Uncertified with an explicit allow reason; enforce mode records the block. Approval alone does not establish integrity. Stored decisions describe the check at that time. These fields require the updated UI and Agent Backend adapter; older events do not invent certification results.

接入包同时挂载到 `api`、`worker`、`agent_backend`；更新后重建这三个服务。只挂载 API/Worker 不覆盖新版 Agent 的执行。运行开始、恢复会话以及发起 Shell 命令前，从 Dify 内部接口读取当前配置的 Skill 完整包，复用扫描版本、实时批准状态和内容签名校验；Skill pull 返回包给沙箱之前也校验。身份取自 Dify 请求上下文或原生已验证的 Agent Stub principal，不从模型命令推断租户或应用。

“智能体详情 → 行为审计”展示 Agent Backend 原生 Run ID、关联工作流 Run ID、Skill 检查、Shell 命令和返回内容。原生 Agent Run 与工作流 Run 分开保留，使用真实标识关联。“管控策略”可选择 Skill 加载（`skill`）或 Shell 命令（`shell`），工具条件可指定 Skill 名称，或 `run`、`input`、`_bootstrap_workspace`。审批沿用现有平台审批：Agent Backend 在调用前等待，拒绝、超时、策略变化均不执行；进程重启后需要重新运行，不能借用工作流检查点恢复这个内部调用。

管控模式下未批准、停用、内容签名异常或平台无法校验时不放行。观察模式记录检查结果并允许未批准包，但 Skill 内容校验服务不可达仍报错。已发布配置不会被自动撤回；后续运行重新检查。范围覆盖配置 Skill pull 和 Agent Shell 发起命令，不覆盖已经启动的后台进程、脚本内部逐次系统调用、任意下载文件或沙箱目录被改写后的逐文件验签；需配合隔离沙箱与出口策略。Shell `wait` 只是读取已有任务结果，`interrupt` 保持可用。

**English:** Dify 1.16.1 also requires the adapter in `agent_backend`. Run entry/resume and shell commands recheck config Skill packages against live approval and signatures; config Skill pulls are checked before bytes reach the sandbox. Behavior Audit records native Agent runs, parent workflow IDs, Skill checks, commands, results and errors. Skill/shell rules reuse allow, deny and approval; approval waits before execution and does not survive a process restart. Observe mode permits unapproved packages but unavailable Skill verification fails the request. These boundaries do not trace individual syscalls, stop existing background jobs, or verify every mutable sandbox file.

| 能力 | 执行位置 |
| --- | --- |
| 节点、模型调用观察 | 工作流节点上下文、ModelInstance |
| HTTP 目标和方法 | HTTP 节点解析参数后、发请求前 |
| 工具名称和参数摘要 | ToolEngine 调用前 |
| Code 节点代码摘要 | CodeExecutor 提交 Sandbox 前 |
| 知识库范围 | Knowledge Retrieval 节点执行前 |
| 工作流版本准入 | 标准化节点与连线的 SHA-256 |
| 人工审批 | 节点首个受控调用前暂停；通过 Dify 原生持久化检查点恢复 |
| 简单先后顺序规则 | 当前运行已有成功动作的节点类型 |

规则按列表顺序首个匹配生效。`after_node_type` 匹配同一次运行中已成功执行的动作类型。观察模式记录策略判断但允许执行；管控模式在授权服务不可达时阻止新增受控调用。结果及观察事件写入本地 SQLite 队列后重试；队列满时管控模式阻止新增调用，观察模式输出事件丢失告警。

审批绑定运行、节点执行 ID、调用序号、参数摘要和策略版本。批准不直接执行工具；恢复后还要消费一次性授权。授权消费响应丢失时，管控模式停止，避免猜测并重复执行。已开始的外部副作用不能撤回。

当前范围为经过这些检查点的调用。插件进程内部网络、Sandbox 内部系统调用、HTTP 重定向后的每次网络跳转不属于此 Adapter 的逐次授权范围。需要这些边界时应配合出口代理、Sandbox 策略及模型/MCP 网关。升级 Dify 后需重新适配，并验证各执行路径的采集与控制。

## 接入

1. 打开“智能体列表 → 登记智能体”，接入类型选择 Dify，填写实例标识、Workspace ID 和 App ID。每个 Dify App 对应一个平台 Agent；同一实例可登记多个 App。
2. 保存后进入智能体独立详情的“接入配置”。下载接入配置并核对容器可访问的平台地址。首次状态为待接入；收到进程心跳后才显示近期在线。
3. 在凭证中心创建绑定此 Agent 的运行凭证：`runtime:trace`，管控另需 `runtime:govern`。用户/用户组按详情显示的运行凭证归属选择。新绑定采用登记时的部门或创建者；已有绑定保留原扫描目标归属，后续编辑部门不会更改已有凭证的运行归属。
4. 准备两个权限为 `0600` 的 JSON 文件：

`config.json`：
```json
{
  "server_url": "https://agent-manager.example.com",
  "applications": [{
    "binding_id": "替换为平台绑定ID",
    "workspace_id": "替换为Dify工作区ID",
    "app_id": "替换为Dify应用ID",
    "mode": "observe"
  }]
}
```

`credentials.json`：
```json
{"替换为平台绑定ID": "替换为实际运行凭证"}
```

5. 在可访问 Docker 的宿主机生成接入目录：

```bash
python3 integrations/dify-runtime/install.py \
  --compose /srv/dify/docker/docker-compose.yaml \
  --project dify \
  --config /secure/config.json \
  --credentials /secure/credentials.json \
  --output /srv/dify/agent-manager-adapter
```

`--compose` 可重复，顺序须与原部署一致。脚本检查镜像版本与已有 `sitecustomize`，保留原 PYTHONPATH，复制无额外依赖的 Adapter，创建 API/Worker 独立队列目录。输出目录必须尚不存在。平台地址应从容器可达；容器的 `127.0.0.1` 指向容器自身。

6. 等运行中工作流结束，在维护窗口使用原部署参数并添加生成的覆盖文件：

```bash
docker compose -p dify \
  -f /srv/dify/docker/docker-compose.yaml \
  -f /srv/dify/agent-manager-adapter/compose.json \
  up -d --no-deps --force-recreate api worker
```

原部署的环境文件、其他 Compose 文件及副本配置也应保留。后续部署继续携带覆盖文件。新增挂载与环境变量需要重建容器。非默认容器用户须预先配置配置文件读取权及队列目录写入权。

API 容器地址改变后，使用静态上游解析的 Nginx 需在 API 就绪后执行 `docker compose` 加原部署参数及 `exec nginx nginx -s reload`，刷新上游地址。SQLite 队列应由同一 Docker 主机中的进程访问；macOS/Windows 宿主机不要同时直接打开运行中容器的 WAL 数据库，诊断请在容器内执行或先制作一致性备份。

7. 在观察模式确认进程检查点和实际节点事件；再对测试应用启用管控，验证拒绝目标的接收端为零请求、批准后只执行一次、拒绝/过期/策略变更后不执行。切换到管控后确认进程已收到新模式。最后收到的模式保存在队列数据库中，重启后继续使用；新建队列目录时使用交付配置中的启动模式。

## 策略示例

```json
{
  "default": "allow",
  "approved_graphs": [],
  "approval_seconds": 120,
  "max_actions": 500,
  "rules": [
    {"rule_id": "review-post", "node_type": "http-request", "method": "POST", "effect": "approval"},
    {"rule_id": "block-after-retrieval", "host": "external.example.com", "after_node_type": "knowledge-retrieval", "effect": "deny"}
  ]
}
```

`approved_graphs` 为空表示未启用版本准入；填入运行记录或 DSL 资产报告中的工作流摘要后，只允许这些版本的受控动作。调整规则时平台递增策略版本，旧的待审批或未消费授权失效。

卸载：停止新任务并等已有工作流结束，移除覆盖文件参数，使用原部署参数重建 API/Worker。保留队列直到事件补传完毕；不要直接删除正在使用的接入文件。

## English

Supports Dify 1.15.0 / graphon 0.5.3 and Dify 1.16.1 / graphon 0.6.0. Mount the generated package into API and Worker, then recreate both services with the original Compose arguments plus `compose.json`. Credentials must belong to the asset owner and have `runtime:trace` and, for enforcement, `runtime:govern`. On 1.16.1, adapter approval pauses close the current response stream while preserving the resumable checkpoint. Normal pauses and disconnects retain Dify behavior. The separate Agent Backend and Local Sandbox are outside the verified scope.

The adapter observes workflow/model events and authorizes HTTP, tool, code and retrieval calls at the listed invocation points. Policies support graph digests, ordered rules, one-time authorization and approval through Dify's persisted workflow checkpoints. Prior-step rules match completed action types, not data lineage. Verify actual side effects separately from heartbeat receipt.

Plugin internals, sandbox system calls and individual redirected HTTP hops need separate controls. Enforce mode blocks new controlled calls when authorization is unavailable. Observe mode permits execution and logs telemetry loss if its bounded queue is full. Preserve queue files for delivery; revalidate every Dify upgrade.
