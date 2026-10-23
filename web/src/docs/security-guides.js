// Detailed operating guides share stable article and section IDs across languages.
const articles = { 'zh-CN': {}, 'en-US': {} }
const locales = ['zh-CN', 'en-US']
const difyConsoleReadOnlyCurl = `DIFY_CONSOLE_BASE_URL='https://dify.example.com'
DIFY_WORKSPACE_ID='<WORKSPACE_ID>'
DIFY_APP_ID='<APP_ID>'
DIFY_ADMIN_KEY='<ADMIN_KEY>'

curl --silent --show-error --include \\
  --connect-timeout 10 --max-time 30 \\
  --header "Authorization: Bearer \${DIFY_ADMIN_KEY}" \\
  --header "X-WORKSPACE-ID: \${DIFY_WORKSPACE_ID}" \\
  --header 'Accept: application/json' \\
  "\${DIFY_CONSOLE_BASE_URL%/}/console/api/apps/\${DIFY_APP_ID}"

curl --silent --show-error --include \\
  --connect-timeout 10 --max-time 30 \\
  --header "Authorization: Bearer \${DIFY_ADMIN_KEY}" \\
  --header "X-WORKSPACE-ID: \${DIFY_WORKSPACE_ID}" \\
  --header 'Accept: application/json' \\
  "\${DIFY_CONSOLE_BASE_URL%/}/console/api/apps/\${DIFY_APP_ID}/export?include_secret=false"

unset DIFY_ADMIN_KEY`
function guide(slug, titles, summaries, sections) {
  locales.forEach((locale, i) => {
    articles[locale][slug] = {
      eyebrow: i === 0 ? '智能体管理' : 'Agent management',
      title: titles[i], summary: summaries[i],
      sections: sections.map(([id, zh, en]) => ({ id, ...(i === 0 ? zh : en) })),
    }
  })
}

guide('security-scan-guide', ['安全扫描操作指南', 'Security scanning guide'],
  ['从扫描目标、凭据和策略开始，逐项配置六种扫描，预览执行边界，复核任务、发现与报告。', 'Configure targets, credentials, policies, and all six scan types; preview execution boundaries and review tasks, findings, and reports.'], [
    ['page-map', {
      title: '六个工作区分别做什么',
      table: { columns: ['工作区', '功能与操作', '下一步'], rows: [
        ['扫描目标', '登记 Agent、MCP、大模型或基础设施；编辑地址与环境；按用途保存凭据；查看最新扫描和当前综合风险分。', '先登记目标，再配置策略。'],
        ['执行策略', '规定执行模式、环境、能力、预算、网络范围、租约和重试；支持启用、停用与编辑。', '确保目标和策略的环境、能力与网络范围匹配。'],
        ['扫描任务', '查看排队、执行、用例进度、累计用量和终止原因；打开详情、取消或紧急停止。', '任务结束后查看保存的用例和产物。'],
        ['定时计划', '管理周期、时区、下次执行、暂停恢复与执行记录。', '先验证一次即时扫描，再安排周期。'],
        ['安全发现', '按扫描查看严重性、状态、来源、置信度、证据及人工处置。', '回到具体用例核对触发条件。'],
        ['扫描报告', '复核风险分、覆盖、输入输出、评估理由、原始产物和可比任务差异；导出报告。', '修复后按相同范围复扫。'],
      ] }, link: { path: '/agent-security/scans', label: '打开安全扫描' },
    }, {
      title: 'What each of the six workspaces does',
      table: { columns: ['Workspace', 'Functions and actions', 'Next step'], rows: [
        ['Targets', 'Register Agents, MCP, models, or infrastructure; edit endpoint and environment; save credentials by purpose; inspect latest scans and current risk.', 'Register a target, then configure a policy.'],
        ['Policies', 'Set mode, environment, capabilities, budgets, networks, leases, and retries; edit, enable, or disable.', 'Match target environment, capabilities, and networks.'],
        ['Tasks', 'Inspect queues, execution, case progress, usage, and stop reasons; open details, cancel, or stop urgently.', 'Review persisted cases and artifacts after completion.'],
        ['Schedules', 'Manage recurrence, timezone, next execution, pause/resume, and run history.', 'Validate an immediate scan first.'],
        ['Findings', 'Review severity, status, source, confidence, evidence, and disposition by scan.', 'Verify triggering conditions in the case.'],
        ['Reports', 'Review score, coverage, input/output, evaluation, artifacts, and comparable differences; export reports.', 'Rescan the same scope after remediation.'],
      ] }, link: { path: '/agent-security/scans', label: 'Open Security Scanning' },
    }],
    ['target-fields', {
      title: '创建目标：每个字段怎么填',
      steps: [
        { title: '进入扫描目标 → 新建目标', body: '使用便于识别业务和环境的名称，例如“客服助手-测试”。资产类型决定后续可选连接器和扫描类型；已有目标的类型不能直接修改。' },
        { title: '选择连接器和环境', body: 'Agent 选择实际使用的 Dify、Coze、HTTP 等连接器；MCP 选择已登记 Gateway；大模型填写对应模型连接配置。环境必须与执行策略一致。' },
        { title: '填写运行地址并测试连通性', body: '运行地址是 Worker 实际访问的 API 入口，不是应用分享链接或编排页面。Dify 通常填写服务 API 基址（包含 /v1）；通用 HTTP 按接口填写完整路径。连通性测试只能说明检查结果，正式扫描仍需凭据、协议和模型配置正确。' },
        { title: '限制能力与内网范围', body: '只选择业务授权的能力。目标为内网时，在目标和策略两侧填写实际网段的 CIDR 白名单，并确认 Worker 的 DNS、路由和证书信任。' },
        { title: '保存目标后单独配置凭据', body: '在目标行打开“凭据”，选择用途、凭据类型，输入密钥并保存。凭据不写入高级 JSON；列表显示掩码和状态。Dify 的三个用途见专门指南。' },
      ], link: { path: '/docs/dify-security-access', label: '查看 Dify 地址、ID 与三种凭据' },
    }, {
      title: 'Create a target: field-by-field setup',
      steps: [
        { title: 'Open Targets → Create target', body: 'Choose a business/environment name such as Support Assistant — Test. Asset type determines available connectors and scans; an existing target cannot change its type directly.' },
        { title: 'Select connector and environment', body: 'Choose the actual Dify, Coze, HTTP, or other Agent connector; select a registered Gateway for MCP; configure the relevant model connection for LLM targets. Match the policy environment.' },
        { title: 'Enter the runtime endpoint and test connectivity', body: 'This is the API reached by the Worker, not a share link or workflow editor. Dify normally uses its service API base including /v1; generic HTTP uses the required endpoint path. Connectivity alone does not validate scan credentials, protocol, or model settings.' },
        { title: 'Constrain capabilities and private networks', body: 'Select authorized capabilities only. Private targets require the actual CIDR ranges in both target and policy allowlists. Check Worker DNS, routing, and certificate trust.' },
        { title: 'Save the target, then configure credentials', body: 'Open Credentials on the target row, choose purpose and credential type, enter the key, and save. Keep secrets out of advanced JSON. Lists show masks and status. The Dify guide explains its three purposes.' },
      ], link: { path: '/docs/dify-security-access', label: 'Read Dify endpoints, IDs, and credentials' },
    }],
    ['policy-fields', {
      title: '执行策略：模式、预算与生产审批',
      table: { columns: ['设置', '如何选择'], rows: [
        ['环境与执行模式', '首次接入优先测试环境和 read_only；生产 active_safe 需要生产目标白名单、UTC 维护窗口、专用身份和单次审批。只读约束按平台可观测和可拦截的调用生效；外部 Agent 内部副作用仍需目标侧隔离。'],
        ['允许能力', '目标声明与策略许可共同限制执行。所需能力不在允许范围时，先核对实际业务授权。'],
        ['轮次、Token、费用、响应字节', '从小预算开始；轮次控制测试深度，字节限制响应体量。模型红队引擎当前不采集模型接口 Token 用量，报告缺失值不能当作零消耗。'],
        ['并发、最长时长与请求超时', '并发影响目标压力；最长时长限制整个任务，请求超时限制单次等待。三者应结合目标承载能力设置。'],
        ['出站 CIDR 与重定向', '私有目标同时满足目标及策略白名单；Dify 重定向还须符合显式主机许可。不要用关闭 TLS 校验解决证书问题。'],
        ['租约与重试', 'Worker 定期续约；失联后按策略重新派发，重试耗尽转失败。长任务应结合心跳和请求超时配置。'],
      ] },
      paragraphs: ['生产主动扫描在“发起扫描”中选择审批。审批绑定当前目标、策略、维护窗口与凭据版本；改配置或换凭据后需要重新核对。预览被阻断时先阅读具体原因，再修正配置。'],
    }, {
      title: 'Execution policy: modes, budgets, and production approval',
      table: { columns: ['Setting', 'How to choose'], rows: [
        ['Environment and mode', 'Start in test with read_only. Production active_safe requires an explicit target allowlist, UTC maintenance window, dedicated identity, and single-use approval. Read-only applies to calls the platform can observe and intercept; isolate external Agent side effects at the target.'],
        ['Capabilities', 'Target declarations and policy permissions jointly bound execution. Verify business authorization before expanding them.'],
        ['Rounds, tokens, cost, response bytes', 'Start small. Rounds bound depth and bytes bound response size. The current LLM red-team engine does not collect model API token usage; missing usage is not zero consumption.'],
        ['Concurrency, duration, request timeout', 'Concurrency affects load, duration bounds the task, and request timeout bounds one wait. Size them for target capacity.'],
        ['Outbound CIDRs and redirects', 'Private destinations must match both allowlists; Dify redirects also require allowed hosts. Fix certificate trust rather than disabling TLS verification.'],
        ['Lease and retry', 'Workers renew leases; lost workers trigger policy-driven reassignment. Exhausted retries fail. Align leases with heartbeat and timeout behavior.'],
      ] }, paragraphs: ['Select approval in the scan form for production active scans. Approval binds the current target, policy, maintenance window, and credential version. Recheck after configuration or key changes. Resolve the specific preview blocker before dispatching.'],
    }],
    ['scan-kinds', {
      title: '六种扫描的输入、操作与产出',
      table: { columns: ['类型', '如何配置', '如何理解结果'], rows: [
        ['扫描链路自检', '选择目标与策略，执行前预览连接配置、许可与预算边界。', '检查任务调度、Worker 租约、心跳与结果回传。'],
        ['Agent 风险扫描', '选择测试规则，填写测试 Prompt；选择单轮或多轮。即时扫描可选择可继续的历史任务；定时扫描使用独立会话。', '查看真实测试对话、轮次和评估理由。规则名称是测试能力，不是向目标部署业务 Skill。'],
        ['Dify 资产清单', '选择在线 Console 采集或手动 DSL；按授权决定是否采集 Prompt 原文、推断意图、检查知识库内容。', '输出档案、模型、节点、Prompt、Tool、MCP、知识库及其来源和验证状态。配置存在和实际执行分别取证。'],
        ['MCP 风险扫描', '选择已登记网关或源码目标，选择元数据、源码、动态或多轮红队模式。', '源码/动态/红队选择网关模型。动态模式还需指定工具范围、调用路径和预算；真实调用证据与模型判断分别保存。'],
        ['大模型红队', '选择数据集及抽样数量、随机种子、问题变换方式，或填写自定义 Prompt；选择独立评估模型。', '计划数为各数据集实际抽样数之和乘以变换方式数。检查实际完成用例及目标回答，覆盖不足仍保留已完成用例并标记失败。'],
        ['AI 基础设施漏洞扫描', '确认目标 URL 授权，设置扫描超时与并发；HTTP 或私网按页面要求显式确认，并满足双侧 CIDR。', '主动访问以识别组件和版本，再匹配 CVE 规则；未知版本保持未验证。'],
      ] },
    }, {
      title: 'Inputs, operation, and output for six scan types',
      table: { columns: ['Type', 'Configuration', 'Interpretation'], rows: [
        ['Scan pipeline self-check', 'Choose target and policy; preview connection settings, permissions, and budgets.', 'Checks task dispatch, Worker leases, heartbeats, and result delivery.'],
        ['Agent risk scan', 'Choose test rules and a prompt; select single or multiple turns. Immediate scans can continue eligible prior tasks; scheduled scans use independent sessions.', 'Inspect real conversations, rounds, and evaluator reasons. Test-rule names identify scanning capabilities, not business Skills installed into the target.'],
        ['Dify asset inventory', 'Choose Console collection or manual DSL, then explicitly authorize prompt text, intent inference, or knowledge content as needed.', 'Produces profiles, models, nodes, prompts, tools, MCP, and knowledge references with source and verification status. Configuration and execution require separate evidence.'],
        ['MCP risk scan', 'Choose a registered gateway or source target, then metadata, source, dynamic or multi-round red-team mode.', 'Source, dynamic and red-team scans use gateway models. Dynamic scans require a tool scope, route and budget. Actual tool evidence and model assessments are retained separately.'],
        ['LLM red team', 'Choose datasets, sample counts, random seed, transformations, or a custom prompt; choose an independent evaluator.', 'Planned cases equal total actual samples across datasets times transformation count. Inspect completed cases and answers. Incomplete coverage fails while retaining completed evidence.'],
        ['AI infrastructure vulnerabilities', 'Authorize target URLs, set timeout and concurrency; confirm HTTP/private access when required and satisfy both CIDR boundaries.', 'Actively fingerprints components and versions before matching CVE rules. Unknown versions remain unverified.'],
      ] },
    }],
    ['task-review', {
      title: '预览、启动与任务详情',
      steps: [
        { title: '预览执行计划', body: '在发起扫描中选择目标、策略和扫描类型，检查预计用例、工具计划、预算及被阻断的能力；Dify 还会展示 MCP 绑定摘要。预览不会替代正式执行。' },
        { title: '提交一次并观察状态', body: 'pending 表示排队，running 表示执行。任务详情的 attempt、心跳和租约帮助区分正常长任务与 Worker 失联；失败时先看稳定错误码及停止原因。' },
        { title: '按需取消或紧急停止', body: '普通取消用于停止不再需要的任务；紧急情况由管理员填写原因启用 Kill Switch。已发出的请求按上游超时收敛，停止操作不会撤销目标已经产生的副作用。' },
        { title: '核对证据而非只看绿灯', body: '任务 succeeded 表示执行完成。逐个查看 passed、failed、blocked、error 或未验证用例，结合覆盖快照、Artifact、引擎版本和评估理由解释结论。' },
      ],
      callout: { type: 'note', title: '任务进度与最终报告是两件事', body: '实时用例完成数可能先于最终报告到达。失败且没有 Case 和 Artifact 的任务会提示未形成最终扫描报告；其中的 0 不表示没有风险。' },
    }, {
      title: 'Preview, dispatch, and inspect task details',
      steps: [
        { title: 'Preview the plan', body: 'Select target, policy, and scan type; review cases, tool plan, budgets, and blocked capabilities. Dify also shows MCP binding counts. Preview does not replace execution.' },
        { title: 'Submit once and observe', body: 'pending means queued; running means executing. Attempts, heartbeat, and lease distinguish long execution from a lost Worker. Read the stable error code and stop reason first after failure.' },
        { title: 'Cancel or stop urgently when needed', body: 'Cancel an unwanted task normally. Administrators activate Kill Switch with a reason for emergencies. In-flight calls converge through upstream timeouts; stopping cannot undo target side effects.' },
        { title: 'Review evidence, not just green status', body: 'succeeded means execution completed. Inspect passed, failed, blocked, error, and unverified cases against coverage, artifacts, engine version, and evaluator reasoning.' },
      ], callout: { type: 'note', title: 'Progress and final reporting are separate', body: 'Live case counts can precede the final report. Failed tasks without cases and artifacts explicitly lack a final report; their zeros do not establish absence of risk.' },
    }],
    ['findings-reports', {
      title: '安全发现、报告导出与版本对比',
      bullets: ['在“安全发现”先核对所属目标和扫描，再看严重性、规则来源、置信度与问题位置。置信度是来源提供的信号，不是风险利用概率。', '打开详情查看证据片段和相关用例。只有保存了有效 trace_id / event_id 的发现才能跳转对应调用事件。', '在“扫描报告”核对本次扫描风险分、完成检查数、计分范围、测试输入、模型回答、判定理由以及运行与审计信息。输入输出保持原文。', '导出前确认报告属于正确任务和资产版本；原始产物、JSON 与 PDF 的权限和脱敏范围按页面提示选择。', '版本对比先选择基线任务，再检查引擎版本、检查范围和两次完成状态。执行失败、跳过或预算提前耗尽不能证明修复；只有可比复扫才能支持“已解决”。'],
      link: { path: '/docs/security-operations', label: '继续阅读风险评分与修复验证' },
    }, {
      title: 'Findings, report exports, and comparisons',
      bullets: ['In Findings, verify target and scan before reading severity, rule source, confidence, and location. Source confidence is not exploitation probability.', 'Open evidence and related cases. Event navigation requires a stored valid trace_id / event_id pair.', 'Reports show this-scan score, completed checks, scoring scope, inputs, model answers, evaluation reasons, and runtime/audit information. Inputs and outputs remain in their original language.', 'Verify the task and asset version before export. Choose artifacts, JSON, or PDF according to the permissions and redaction scope shown in the UI.', 'Select a baseline and compare engines, scope, and completion. Failures, skips, or exhausted budgets cannot establish remediation; resolution requires comparable rescanning.'],
      link: { path: '/docs/security-operations', label: 'Read scoring and remediation verification' },
    }],
  ])

guide('dify-security-access', ['Dify 应用纳管、三种凭据与资产清单', 'Dify application governance, credentials, and asset inventory'],
  ['按资产发现、动态测试、知识授权和运行证据分别接入 Dify；逐步配置三种凭据并执行资产采集与排错。', 'Connect Dify separately for asset discovery, dynamic testing, knowledge authorization, and runtime evidence; configure three credentials and collect inventory.'], [
    ['credential-map', {
      title: '先按操作选择凭据，三个 Key 不能混用',
      table: { columns: ['管理台凭据用途', '从哪里取得', '用于什么'], rows: [
        ['Dify App API · dify_app_api', '目标应用 → 访问 API / API Access → API 密钥。', '调用已发布应用，执行动态 Agent 扫描。通常访问 /v1/chat-messages 或 /v1/workflows/run。'],
        ['Dify Console Admin API · dify_console_api', '支持 Admin API Key 的自托管 Dify 部署配置，由部署管理员提供。', 'Console 应用信息、DSL 导出、草稿工作流与工作空间应用枚举；请求同时携带 X-WORKSPACE-ID。'],
        ['Dify Knowledge API · dify_knowledge_api', '知识库列表右上角 Service API；部分版本从单库 API Access 进入 API 密钥。', '通过 /v1/datasets 查询可见数据集、文档和分段；内容读取另需明确授权。'],
      ] }, paragraphs: ['只执行动态扫描先准备 App Key；在线资产采集准备 Console Key；需要知识库元数据补充或授权内容检查时再准备 Knowledge Key。Key 的外观或前缀不能替代用途核对。'],
    }, {
      title: 'Choose by operation: these keys are not interchangeable',
      table: { columns: ['Credential purpose', 'Where to obtain it', 'Used for'], rows: [
        ['Dify App API · dify_app_api', 'Target application → API Access → API Keys.', 'Invoke a published app for dynamic Agent scanning, typically /v1/chat-messages or /v1/workflows/run.'],
        ['Dify Console Admin API · dify_console_api', 'Deployment configuration of a self-hosted Dify version supporting Admin API Key; ask its deployment administrator.', 'Console app details, DSL export, draft workflow, and workspace app enumeration; includes X-WORKSPACE-ID.'],
        ['Dify Knowledge API · dify_knowledge_api', 'Knowledge → Service API (top right); some versions expose API Keys from a knowledge base’s API Access.', 'Use /v1/datasets for visible datasets, documents, and segments; content reads require separate authorization.'],
      ] }, paragraphs: ['Prepare an App Key for dynamic scans, a Console Key for online inventory, and a Knowledge Key for knowledge metadata or authorized content inspection. Key appearance or prefix does not establish its purpose.'],
    }],
    ['app-key', {
      title: 'Dify App API：从应用页面取得',
      steps: [
        { title: '进入正确工作空间和应用', body: '登录 Dify，在顶部工作空间选择器确认归属，进入“工作室 / Studio”，打开要扫描的应用。先确认应用已经发布且可正常运行，并验证发布 API。' },
        { title: '打开“访问 API / API Access”', body: '在应用左侧找到访问 API。记录页面给出的 API 服务器地址，例如 https://dify.example.com/v1。不要复制浏览器中的 /app/<id>/workflow 地址或公开分享链接。' },
        { title: '打开“API 密钥 / API Keys”并创建', body: '由有管理权限的人员创建专用于扫描的密钥，复制到受控密码库。密钥仅交给扫描管理员；截图中必须遮盖密钥。没有按钮时先核对角色和所在应用，不要用模型供应商密钥代替。' },
        { title: '保存到扫描目标', body: '在智能体生命周期管理系统 → 安全扫描 → 扫描目标创建 Agent / Dify，运行地址填写刚才的 /v1 基址。保存后打开目标行的凭据，选择 Dify App API 和 Bearer 令牌类型，粘贴原始 Key（不加 Bearer 前缀）并保存。' },
        { title: '核对应用类型与输入变量', body: 'Chatflow/聊天应用使用 chat；Workflow 使用 workflow。高级配置的 extra.dify_type 决定接口，extra.inputs 填必需输入变量，extra.user 填稳定测试用户标识。当前适配器把测试 Prompt 放进 query；Workflow 需要兼容该输入约定。' },
      ], code: '{\n  "extra": {\n    "dify_type": "workflow",\n    "inputs": {},\n    "user": "agent-manager-security-test"\n  }\n}',
      paragraphs: ['此配置示例用于接受 query 输入的 Workflow；实际必填业务变量应补在 inputs 中。动态扫描会调用应用并可能产生模型费用或业务动作，先用测试应用与小预算验证。'],
    }, {
      title: 'Dify App API: obtain it from the application',
      steps: [
        { title: 'Choose the correct workspace and app', body: 'Sign in to Dify, confirm the workspace selector, open Studio, and select the target application. Verify it is published and works and verify its published API.' },
        { title: 'Open API Access', body: 'Use the application sidebar. Record the API server URL, for example https://dify.example.com/v1. Do not copy the browser editor URL /app/<id>/workflow or the public share link.' },
        { title: 'Open API Keys and create a key', body: 'An authorized app administrator creates a scanning-specific key and stores it securely. Share it only with the scanning administrator and mask it in screenshots. If the button is missing, verify role and application; a model provider key is not a substitute.' },
        { title: 'Save it on the scan target', body: 'In Agent Manager → Security Scanning → Targets, create an Agent / Dify target using the /v1 API base. Save, open Credentials on its row, select Dify App API and Bearer token, and paste the raw key without a Bearer prefix.' },
        { title: 'Check app type and inputs', body: 'Chat applications/Chatflow use chat; Workflow uses workflow. Advanced extra.dify_type selects the endpoint; extra.inputs supplies required variables; extra.user identifies the test user. The current adapter puts the test prompt into query, so Workflow inputs must support that contract.' },
      ], code: '{\n  "extra": {\n    "dify_type": "workflow",\n    "inputs": {},\n    "user": "agent-manager-security-test"\n  }\n}', paragraphs: ['This example is for a Workflow accepting query. Add actual required business variables to inputs. Dynamic scanning invokes the app and can incur model costs or business actions; validate with a test app and small budgets.'],
    }],
    ['console-key', {
      title: 'Dify Console Admin API：由部署管理员配置',
      paragraphs: ['这是部署端管理凭据，不是应用“API 密钥”弹窗里的另一种 Key。已核对 Dify 1.6.0 官方源码：ADMIN_API_KEY_ENABLE 默认关闭，ADMIN_API_KEY 默认未设置；启用后使用 Bearer Key 和 X-WORKSPACE-ID，以指定工作空间 owner 身份访问。这里的获取流程适用于支持该机制的自托管版本；Dify Cloud、其他版本和定制版本须由管理员核对，不能假定都支持。'],
      steps: [
        { title: '确认部署版本和支持机制', body: '请部署管理员查看正在运行的 Dify 镜像 tag，并对照相同版本的配置与 ext_login.py。只有确认支持 Admin API Key 才继续。' },
        { title: '编辑 API 服务的环境配置文件', body: '使用分服务环境文件的部署，在 dify/docker/envs/core-services/api.env 中添加或更新以下两项。ADMIN_API_KEY 填写由安全随机源生成并妥善保管的密钥；文档中的占位值不能直接使用。确认 Compose 的 api 服务通过 env_file 引用了此文件；不同版本的配置位置以实际部署为准。', code: '# dify/docker/envs/core-services/api.env\nADMIN_API_KEY_ENABLE=true\nADMIN_API_KEY=<ADMIN_KEY_FROM_SECRET_STORE>' },
        { title: '重新创建 API 容器并验证配置生效', body: '在 dify/docker 目录使用该部署原有的 Compose 文件、项目名和 profile 执行更新。标准命令如下；若原部署使用 -f、-p 或 --profile，保留相同参数。env_file 在创建容器时注入，docker restart 或 docker compose restart api 不会重新读取修改后的值。更新后继续执行下方 Console 只读验证，不能仅凭容器启动成功判断密钥生效。', code: 'cd dify/docker\ndocker compose up -d --no-deps --force-recreate api' },
        { title: '取得 Workspace ID 和 App ID', body: 'App ID 是应用编排 URL /app/<APP_ID>/workflow（或其他应用子页面）中的 UUID。Workspace ID 是工作空间/tenant UUID，不是名称或 App ID。可让部署管理员确认；有权限的用户也可在浏览器开发者工具 Network 中查看切换工作空间请求或当前工作空间响应的 id，再核对 name。不要复制 Cookie、Authorization 或整份网络日志。' },
        { title: '保存目标连接与独立凭据', body: 'Console Base URL 填 API 所在服务根地址，例如 https://dify.example.com，不附加 /console/api 或 /v1；系统会拼接 Console 路径。填写 Workspace ID、App ID 后保存。在凭据弹窗选择 Dify Console Admin API、Bearer 令牌类型，保存原始 Admin Key。' },
        { title: '用 curl 做只读验证', body: '在有权限且能访问 Dify 的终端，将前四行替换为实际服务根地址、Workspace UUID、App UUID 和 Admin Key，然后复制整段执行（Bash / Zsh）。地址填写实际协议、域名/IP 和端口，不带 /console/api 或 /v1；Key 不加 Bearer 前缀。两次请求均为 GET，依次读取应用详情与不含密钥的 DSL 导出，不执行应用。--include 显示 HTTP 状态和响应头；连接超时 10 秒、单次请求最长 30 秒。', code: difyConsoleReadOnlyCurl, expected: '第一条返回 HTTP 200 和目标应用详情，核对 id/name；第二条返回 HTTP 200 和包含 DSL 内容的 JSON；data 字段是 YAML 字符串，解析后可看到 app、kind: app、version 和 workflow，其中 version 是 DSL 格式版本。原始 JSON 中的换行和 Unicode 转义是正常编码。401 检查 Key、开关和工作空间，403/404 检查权限、App ID 与路由；HTML 或 3xx 不是验证成功。curl 退出码 0 也可能对应 HTTP 401，必须检查显示的 HTTP 状态。' },
      ], references: [
        { label: 'Dify 1.6.0：Admin API Key 配置定义', url: 'https://github.com/langgenius/dify/blob/1.6.0/api/configs/feature/__init__.py' },
        { label: 'Dify 1.6.0：认证与 X-WORKSPACE-ID', url: 'https://github.com/langgenius/dify/blob/1.6.0/api/extensions/ext_login.py' },
      ], callout: { type: 'warning', title: '不能自动采集时的可用操作', body: '当前 Dify 版本不支持 Admin API Key 或 Console DSL 导出时，使用应用菜单导出不含密钥的 DSL，并在即时资产清单任务选择手动 DSL。平台不使用浏览器 Cookie 自动登录。手动 DSL 不能提供在线 Console 的完整验证，也不能用于定时采集。' },
    }, {
      title: 'Dify Console Admin API: configured by the deployment administrator',
      paragraphs: ['This is a deployment credential, not another key in the application API Keys dialog. Verified against official Dify 1.6.0 source: ADMIN_API_KEY_ENABLE defaults to false and ADMIN_API_KEY is unset. When enabled, Bearer Key plus X-WORKSPACE-ID authenticates as the selected workspace owner. This procedure applies to self-hosted versions supporting that mechanism; administrators must verify Cloud, other versions, and custom builds separately.'],
      steps: [
        { title: 'Verify version and authentication support', body: 'Ask the deployment administrator to identify the running image tag and inspect configuration and ext_login.py for that version. Proceed only if Admin API Key is supported.' },
        { title: 'Edit the API service environment file', body: 'For deployments with per-service environment files, add or update these settings in dify/docker/envs/core-services/api.env. Generate ADMIN_API_KEY from a secure random source and store it securely; the placeholder is not a usable key. Verify that the Compose api service references this file through env_file. Configuration locations vary by deployed version.', code: '# dify/docker/envs/core-services/api.env\nADMIN_API_KEY_ENABLE=true\nADMIN_API_KEY=<ADMIN_KEY_FROM_SECRET_STORE>' },
        { title: 'Recreate the API container and verify the configuration', body: 'Run the update from dify/docker using the deployment’s original Compose files, project name, and profiles. The standard command is below; retain any original -f, -p, or --profile options. env_file is injected at container creation; docker restart or docker compose restart api does not reload edited values. Then perform the Console read-only validation below; container startup alone does not establish key validity.', code: 'cd dify/docker\ndocker compose up -d --no-deps --force-recreate api' },
        { title: 'Obtain Workspace ID and App ID', body: 'App ID is the UUID in /app/<APP_ID>/workflow or another app subpage URL. Workspace ID is the workspace/tenant UUID, not its name or App ID. Ask the deployment administrator, or inspect the workspace-switch/current-workspace response in browser Developer Tools → Network and match id to name. Do not copy cookies, Authorization, or entire network logs.' },
        { title: 'Save connection settings and the dedicated credential', body: 'Console Base URL is the API service root, such as https://dify.example.com, without /console/api or /v1. The platform appends Console paths. Save Workspace ID and App ID. Open Credentials, select Dify Console Admin API and Bearer token, then save the raw Admin Key.' },
        { title: 'Validate read-only access with curl', body: 'In an authorized terminal with access to Dify, replace the first four values with the service root URL, Workspace UUID, App UUID, and Admin Key, then run the entire block in Bash or Zsh. Use the actual scheme, hostname/IP, and port without /console/api or /v1; omit the Bearer prefix from the key. Both GET requests read app details and secret-free DSL export without running the app. --include displays HTTP status and headers; connection timeout is 10 seconds and total timeout is 30 seconds per request.', code: difyConsoleReadOnlyCurl, expected: 'The first request returns HTTP 200 and app details; verify id/name. The second returns HTTP 200 and JSON whose data field is a YAML string containing app, kind: app, version, and workflow; version denotes the DSL format version. Newline and Unicode escapes in the raw JSON are normal encoding. For 401 check the key, switch, and workspace; for 403/404 check permissions, App ID, and routing. HTML or 3xx does not establish success. curl exit code 0 can accompany HTTP 401, so inspect the HTTP status.' },
      ], references: [
        { label: 'Dify 1.6.0: Admin API Key configuration', url: 'https://github.com/langgenius/dify/blob/1.6.0/api/configs/feature/__init__.py' },
        { label: 'Dify 1.6.0: authentication and X-WORKSPACE-ID', url: 'https://github.com/langgenius/dify/blob/1.6.0/api/extensions/ext_login.py' },
      ], callout: { type: 'warning', title: 'When online collection is unavailable', body: 'If the deployment does not support Admin API Key or Console export, export a secret-free DSL from the app menu and choose manual DSL for an immediate inventory task. The platform does not automate cookie login. Manual DSL lacks full online Console verification and is unavailable for scheduled collection.' },
    }],
    ['knowledge-key', {
      title: 'Dify Knowledge API：从知识库 API 访问取得',
      steps: [
        { title: '进入正确工作空间的知识库', body: '在 Dify 顶部打开“知识库 / Knowledge”，当前官方文档入口为列表右上角“Service API”。部分版本从具体知识库左下角“API 访问 / API Access”进入；单库 API Access 还用于控制该库是否可经 API 访问。这里的 API 文档应包含 datasets、documents、segments 接口，而不是 chat-messages。' },
        { title: '创建知识库 API Key', body: '在“API 密钥 / API Keys”由有权限的管理员创建，并存入受控密码库。按当前 Dify 版本确认其可访问的数据集范围；不要假定该 Key 只允许访问当前页面一个知识库，也不要假定它只读。' },
        { title: '验证可见性与数据集 ID', body: '使用 Knowledge API 的 GET /v1/datasets 分页查看可见数据集，核对实际 UUID。应用 DSL 中隐藏或编码的知识库引用不一定是 API 接受的 Dataset ID。' },
        { title: '在目标保存独立用途', body: '回到目标行的“凭据”，选择 Dify Knowledge API、Bearer 令牌类型，保存原始 Key。该 Key 与 Console Key 分开管理；只配置 Knowledge Key 不能代替 Console 自动导出。' },
        { title: '需要内容检查时明确授权并设限', body: '发起 Dify 资产清单任务，勾选知识库内容授权，设置最大文档数、分段数和字节数。例如首次使用默认 100 文档、1000 分段、10 MiB，并按授权范围缩小。保存凭据本身不表示已授权读取原文。' },
      ], code: 'GET /v1/datasets?page=1&limit=20\nAuthorization: Bearer <KNOWLEDGE_API_KEY>',
      references: [{ label: 'Dify 官方：获取应用与知识库 API Key', url: 'https://docs.dify.ai/en/api-reference/guides/get-started' }, { label: 'Dify 官方：Knowledge API 与单库 API 访问控制', url: 'https://docs.dify.ai/en/api-reference/guides/knowledge' }],
      paragraphs: ['系统按分页和预算读取，并保存分段哈希及脱敏元数据。知识库 API 读取失败时检查具体来源覆盖和错误码，不要把“未读取”当作“未发现问题”。'],
    }, {
      title: 'Dify Knowledge API: obtain it from knowledge API access',
      steps: [
        { title: 'Open Knowledge in the correct workspace', body: 'Open Knowledge and choose Service API at the top right, as described in current official documentation. Some versions expose API Access within a knowledge base; that per-base page also controls API availability. Its documentation should list datasets, documents, and segments rather than chat-messages.' },
        { title: 'Create a Knowledge API key', body: 'An authorized administrator creates it under API Keys and stores it securely. Verify dataset scope for the deployed version; do not assume the key is limited to the currently open dataset or is read-only.' },
        { title: 'Validate visibility and dataset IDs', body: 'Page through GET /v1/datasets and verify actual UUIDs. Hidden or encoded DSL knowledge references may not be Dataset IDs accepted by the API.' },
        { title: 'Save under the dedicated purpose', body: 'In target Credentials, choose Dify Knowledge API and Bearer token, then save the raw key. Manage it separately from Console credentials; Knowledge access does not replace Console export.' },
        { title: 'Explicitly authorize content inspection and set bounds', body: 'In the Dify inventory task, enable knowledge-content authorization and set document, segment, and byte limits. Initial defaults are 100 documents, 1000 segments, and 10 MiB; reduce them to the authorized scope. Saving a key alone does not authorize raw content reads.' },
      ], code: 'GET /v1/datasets?page=1&limit=20\nAuthorization: Bearer <KNOWLEDGE_API_KEY>', references: [{ label: 'Dify: obtain app and knowledge API keys', url: 'https://docs.dify.ai/en/api-reference/guides/get-started' }, { label: 'Dify: Knowledge API and per-base API access', url: 'https://docs.dify.ai/en/api-reference/guides/knowledge' }], paragraphs: ['Collection is paginated and budgeted, retaining segment hashes and redacted metadata. Inspect per-source coverage and error codes after failure; unread content is not evidence of no issues.'],
    }],
    ['connection-checklist', {
      title: '把地址和 ID 填到正确位置',
      table: { columns: ['字段', '示例 / 获取方法', '用途'], rows: [
        ['运行地址', 'https://dify.example.com/v1；从应用 API Access 复制。', '动态调用应用；连接器拼接 chat-messages 或 workflows/run。'],
        ['Console Base URL', 'https://dify.example.com；确认此主机转发 /console/api。', '读取 Console 配置；可与运行 API 使用不同域名。'],
        ['Workspace ID', '工作空间的 tenant UUID；管理员确认或查看当前工作空间响应。', '以 X-WORKSPACE-ID 传给 Console。'],
        ['App ID', '/app/<UUID>/workflow 等应用 URL 中的 UUID。', '锁定被采集应用；不是发布分享码。'],
        ['Workflow ID（可选）', '从当前版本受支持的工作流记录确认；无具体需求留空。', '指定导出版本；草稿与已发布配置可能不同。'],
        ['Owner / Owner Group / 声明意图', '填写实际归属和业务描述；未知信息留空。', '归属管理和人工声明；不是上游自动验证事实。'],
        ['MCP Provider 绑定', '先采集快照，再将 Provider ID 显式对应到已发现的 MCP Server。', '补充真实 tools/list 清单；不按名称猜测关系。'],
      ] },
    }, {
      title: 'Put each endpoint and ID in the correct field',
      table: { columns: ['Field', 'Example / source', 'Purpose'], rows: [
        ['Runtime endpoint', 'https://dify.example.com/v1 from app API Access.', 'Dynamic calls; connector appends chat-messages or workflows/run.'],
        ['Console Base URL', 'https://dify.example.com; verify /console/api routing.', 'Read Console configuration; may use a different host from runtime API.'],
        ['Workspace ID', 'Tenant UUID verified by the administrator or current-workspace response.', 'Sent as X-WORKSPACE-ID.'],
        ['App ID', 'UUID in /app/<UUID>/workflow or another app URL.', 'Identifies the app, not its published share code.'],
        ['Workflow ID (optional)', 'Verify in supported workflow records; leave blank when not needed.', 'Select export version; draft and published configurations can differ.'],
        ['Owner / Owner Group / declared intent', 'Enter actual ownership and business description; leave unknown information empty.', 'Ownership and administrator declaration, not automatically verified upstream facts.'],
        ['MCP Provider bindings', 'Collect a snapshot first, then explicitly map Provider ID to a discovered MCP Server.', 'Adds real tools/list evidence without name-based guessing.'],
      ] },
    }],
    ['inventory-review', {
      title: '执行资产清单并逐项阅读结果',
      steps: [
        { title: '发起扫描 → Dify 资产清单', body: '选择目标和同环境的只读策略，采集方式选 Console API。在线导出固定 include_secret=false。首次先保留 Prompt 原文、意图推断和知识库内容检查关闭，以确认基础链路。' },
        { title: '按业务需要增加采集项', body: 'Prompt 原文需管理员显式启用，保存后查看仍需确认与审计。系统推断意图可选择模型，未选则使用默认启用模型；它是推断，和已验证意图、管理员声明分别展示。知识库内容另需授权与专用 Key。' },
        { title: '打开任务详情 → 资产清单', body: '先读智能体档案与各来源覆盖，再查看模型、工作流节点、Prompt、工具、MCP 和知识库。利用分类与来源筛选定位项目，展开字段证据与验证摘要。' },
        { title: '核对来源、版本与执行证据', body: 'DSL 证明配置存在；Console 补充应用事实；Knowledge API 补充数据集证据；绑定 MCP Server 的 tools/list 证明工具发现；同应用且同归属的 Runtime Trace 才能证明 observed/executed。' },
      ],
      callout: { type: 'note', title: '知识库映射和草稿边界', body: 'DSL 隐藏 Dataset ID 时，系统按相同 knowledge-retrieval 节点 ID 读取 Console 草稿 UUID，仅在合法且唯一时映射。draft_may_differ_from_published_workflow 表示草稿可能不同于发布版本；无法映射或缺少执行轨迹的资产保持未验证。' },
    }, {
      title: 'Run inventory and review every part of the result',
      steps: [
        { title: 'New scan → Dify asset inventory', body: 'Choose the target and a same-environment read-only policy, then Console API collection. Export always uses include_secret=false. First verify the basic flow with prompt text, intent inference, and knowledge-content inspection disabled.' },
        { title: 'Add authorized collection options', body: 'Administrators explicitly enable prompt text; viewing stored text still requires confirmation and auditing. Intent inference allows model selection or uses the default enabled model. It is shown separately from verified intent and administrator declarations. Knowledge content requires authorization and its dedicated key.' },
        { title: 'Open task details → Asset inventory', body: 'Read the Agent profile and source coverage first, then models, workflow nodes, prompts, tools, MCP, and knowledge assets. Filter by category/source and inspect field evidence and verification summaries.' },
        { title: 'Check source, version, and execution evidence', body: 'DSL establishes configuration; Console adds app facts; Knowledge API adds dataset evidence; bound MCP tools/list establishes discovery; Runtime Trace from the same app and ownership establishes observed/executed behavior.' },
      ], callout: { type: 'note', title: 'Dataset mapping and draft boundaries', body: 'When DSL hides Dataset IDs, the collector matches knowledge-retrieval node IDs against Console draft UUIDs only when valid and unique. draft_may_differ_from_published_workflow flags a draft that may differ from publication. Unmapped assets or missing execution evidence remain unverified.' },
    }],
    ['dify-troubleshooting', {
      title: '按现象排查，不要反复换 Key 碰运气',
      table: { columns: ['现象 / 错误码', '排查顺序'], rows: [
        ['console_credential_required / knowledge_credential_required', '目标 → 凭据 → 对应用途是否存在且已启用；检查是否误存为 App API。'],
        ['console_auth_failed · 401', '核对 Admin Key、ADMIN_API_KEY_ENABLE、API 进程是否收到变量、Workspace UUID 是否正确；不要换成应用 Key。'],
        ['console_forbidden · 403 / app_not_found · 404', '核对工作空间归属、App ID 和 Console API 路由。'],
        ['export_not_supported / draft_workflow_unavailable', '核对 Dify 版本、应用类型和导出/草稿接口支持；即时采集可使用不含密钥的手动 DSL，草稿知识库映射缺失保持未验证。'],
        ['dataset_forbidden / dataset_not_found', '用 Knowledge Key 验证数据集分页可见性，核对实际 Dataset UUID 和工作空间。'],
        ['dataset_reference_unmapped / dataset_reference_ambiguous', '核对节点 ID 与草稿映射；必要时配置已验证的知识库绑定，不按名称或相似度猜测。'],
        ['upstream_unavailable / response_invalid', '从 Worker 网络核对 HTTPS、DNS、双侧 CIDR、重定向与超时；检查返回是否为登录 HTML 而非 JSON。'],
        ['动态调用 400 / 404', '核对已发布应用类型、/v1 基址、extra.dify_type、必填 inputs 和 query 输入契约。'],
      ] }, paragraphs: ['表中省略的错误码前缀为 dify_inventory.。凭据轮换后重新检查对应用途的状态，再发起小范围验证；不要在截图、报告或普通日志中附上密钥。'],
    }, {
      title: 'Troubleshoot by symptom',
      table: { columns: ['Symptom / error code', 'Checks in order'], rows: [
        ['console_credential_required / knowledge_credential_required', 'Verify the matching enabled purpose in target Credentials; check it was not saved as App API.'],
        ['console_auth_failed · 401', 'Verify Admin Key, ADMIN_API_KEY_ENABLE, API process environment, and Workspace UUID; do not substitute an App Key.'],
        ['console_forbidden · 403 / app_not_found · 404', 'Check workspace ownership, App ID, and Console routing.'],
        ['export_not_supported / draft_workflow_unavailable', 'Verify version, app type, and export/draft endpoint support. Immediate tasks can use secret-free manual DSL; missing draft mappings remain unverified.'],
        ['dataset_forbidden / dataset_not_found', 'Verify paginated visibility using the Knowledge Key, actual Dataset UUID, and workspace.'],
        ['dataset_reference_unmapped / dataset_reference_ambiguous', 'Check node IDs and draft mappings. Use verified explicit knowledge bindings if needed, not name similarity.'],
        ['upstream_unavailable / response_invalid', 'Check HTTPS, DNS, both CIDRs, redirects, and timeouts from the Worker network; rule out login HTML instead of JSON.'],
        ['Dynamic call 400 / 404', 'Check published app type, /v1 base, extra.dify_type, required inputs, and the query contract.'],
      ] }, paragraphs: ['Inventory error codes above use the dify_inventory. prefix. After key rotation, recheck purpose/status and run a small validation. Do not attach keys to screenshots, reports, or ordinary logs.'],
    }],
  ])

guide('security-operations', ['定时扫描与风险处置', 'Schedules and risk disposition'],
  ['配置周期扫描，理解风险分、覆盖有效期、人工审核与修复验证，并排查 Worker 执行问题。', 'Configure scheduled scans; understand scoring, coverage validity, review, remediation, and Worker diagnostics.'], [
    ['asset-sources', {
      title: '资产来源：同步后按变更触发扫描',
      paragraphs: ['在扫描目标中打开资产来源，配置 Dify 工作空间、应用范围与同步周期。启用“变更后扫描策略”时，还必须选择“自动扫描评估模型”；模型及其供应商均需启用，保存和每次派发都会检查。', '旧来源需编辑补充评估模型。模型停用、目标凭据缺失或审批未满足时，变更事件保留失败原因，修正后由后续重试继续处理。每个新应用需配置自己的调用凭据；同一资产版本的重复事件只创建一次扫描任务。'],
    }, {
      title: 'Asset sources: scan changes after synchronization',
      paragraphs: ['Open asset sources from scan targets and configure the Dify workspace, application scope, and synchronization schedule. Selecting a scan policy after changes also requires an automatic scan evaluator model. The model and provider must be enabled; both are checked on save and on every dispatch.', 'Edit older sources to add the evaluator. A disabled model, missing target credentials, or pending approval keeps the event failure reason available for retry after correction. Each new application needs its own runtime credentials. Repeated events for the same asset revision create only one scan task.'],
    }],
    ['schedules', {
      title: '定时计划：把已验证的扫描重复执行',
      steps: [
        { title: '先跑通即时扫描', body: '确认目标、专用凭据、策略和实际用例正常，再点击“发起扫描”，在执行安排选择定时执行。定时配置复用目标、规则和策略表单。' },
        { title: '设置名称、周期与时区', body: '支持固定间隔、每日、每周和五字段 Cron。选择 IANA 时区，例如 Asia/Shanghai；查看下次执行预览，确认夏令时或跨时区影响。Cron 五字段依次为分、时、日、月、星期，例如 0 9 * * 1 表示所选时区每周一 09:00。' },
        { title: '保存并决定是否立即执行一次', body: '需要验证计划时勾选保存后立即执行一次。定时任务不续接已有会话；Dify 资产采集必须使用在线 Console 配置。' },
        { title: '在定时计划检查执行记录', body: '核对启用状态、下次执行、最近结果。可编辑、暂停/恢复、立即执行一次、查看历史或删除；点击有 task_id 的执行记录可打开报告。删除计划保留历史任务与报告。' },
      ],
      bullets: ['同一计划上一轮仍排队或执行时，本轮记录为跳过；服务停机错过多轮最多补一次。手动执行一次不改变原周期。', '每轮重新验证账号、目标权限、凭据、策略与生产审批。待审批时，管理员先完成对应审批，再从计划立即执行一次。', '编辑只影响后续派发，已创建任务保留原配置；同目标同配置的自动触发可能复用活动任务，触发来源在详情保留。'],
    }, {
      title: 'Schedules: repeat a validated scan',
      steps: [
        { title: 'Validate an immediate scan first', body: 'Check target, credentials, policy, and real cases, then open New scan and choose scheduled execution. The form reuses target, rule, and policy settings.' },
        { title: 'Set name, recurrence, and timezone', body: 'Choose interval, daily, weekly, or five-field Cron with an IANA timezone such as Asia/Shanghai. Review upcoming times and daylight-saving effects. Cron fields are minute, hour, day, month, weekday; 0 9 * * 1 means Monday at 09:00 in the selected timezone.' },
        { title: 'Save and optionally run immediately', body: 'Enable run-on-save to validate dispatch. Scheduled tasks do not continue existing sessions; Dify inventory requires online Console configuration.' },
        { title: 'Inspect schedule execution history', body: 'Check enabled state, next execution, and latest result. Edit, pause/resume, run once, inspect history, or delete. A run with task_id opens its report. Deleting the schedule retains task/report history.' },
      ], bullets: ['If the previous run is queued or active, the next is skipped. Multiple missed intervals coalesce into at most one catch-up; manual runs do not shift recurrence.', 'Each run revalidates account, target access, credentials, policy, and production approval. Complete missing approval, then run once from the schedule.', 'Edits affect future dispatches; existing tasks retain configuration. Identical automatic triggers can reuse an active task while retaining trigger provenance.'],
    }],
    ['risk-scores', {
      title: '本次扫描风险分与当前综合风险分',
      table: { columns: ['指标', '读法'], rows: [
        ['本次扫描风险分', '报告中的任务终态评分快照，附完成检查数和计分范围。后续人工处置不改写本次分数。'],
        ['当前综合风险分', '目标列表的长期治理指标；汇总有效且未关闭的风险及明确关联的 MCP 风险。点击进入覆盖、贡献项、历史和处置。'],
        ['空值 —', '尚无评估，或只完成部分检查且没有计分风险；不能当作 0。'],
        ['0', '配置范围内检查完成且没有计分风险；必须同时阅读范围和有效期。'],
        ['待复扫', '资产配置已变或评估过期；未关闭旧风险仍保留分数，失败和取消不能清除旧风险。'],
      ] }, paragraphs: ['agent-risk-score@1 使用最高风险基础分，加其他去重风险的附加分（附加上限 20，总分上限 100）。低/中/高/严重基础分分别为 10/35/65/90，其他风险分别加 1/3/5/8；提示为 0。1–34 为低、35–64 为中、65–89 为高、90–100 为严重。分数用于风险处置排序。'],
    }, {
      title: 'This-scan score versus current aggregate risk',
      table: { columns: ['Metric', 'Meaning'], rows: [
        ['This-scan score', 'A terminal task snapshot in the report with completed checks and scope. Later disposition does not rewrite it.'],
        ['Current aggregate score', 'A target-level governance measure of active, unresolved issues plus explicitly linked MCP risks. Open it for coverage, contributions, history, and disposition.'],
        ['Missing —', 'No assessment, or partial checks without scoring issues; not zero.'],
        ['0', 'Configured checks completed without scoring issues; read scope and validity alongside it.'],
        ['Rescan needed', 'Configuration changed or assessment expired. Unclosed risks retain their score; failure and cancellation cannot clear them.'],
      ] }, paragraphs: ['agent-risk-score@1 takes the highest severity base plus contributions from other deduplicated risks, capped at 20 additional points and 100 total. Low/medium/high/critical bases are 10/35/65/90, with additional contributions of 1/3/5/8; informational is zero. Levels are 1–34 low, 35–64 medium, 65–89 high, 90–100 critical. Scores prioritize risk disposition.'],
    }],
    ['risk-disposition', {
      title: '从发现到修复验证的操作闭环',
      steps: [
        { title: '打开目标当前风险分', body: '查看覆盖检查是否完整、当前资产版本、贡献风险、来源与最近同步时间。需要计入 MCP 风险时，由管理员显式关联同归属范围的 MCP 目标。' },
        { title: '查看证据并选择处置', body: '在贡献项打开扫描证据，管理员填写审核意见。风险接受继续计分；误报审核后排除；声明修复进入“修复待验证”。' },
        { title: '修复实际问题并复扫', body: '按相同目标、可比资产版本、引擎与检查范围重新扫描；确认对应检查完成且用例通过。只改状态或得到一次失败扫描不足以关闭风险。' },
        { title: '引用复扫任务验证关闭', body: '审核选择验证关闭并填写对应复扫任务 ID。系统检查目标、版本、范围、完成时间与通过用例，成功后保留关闭审计。历史评分与本次报告分仍可追溯。' },
      ],
    }, {
      title: 'Close the loop from finding to verified remediation',
      steps: [
        { title: 'Open current target risk', body: 'Inspect coverage, current asset version, contributing issues, source, and latest sync. Administrators explicitly link same-ownership MCP targets when their risk should contribute.' },
        { title: 'Review evidence and choose a disposition', body: 'Open scan evidence and record an administrator review. Accepted risk still contributes; reviewed false positives are excluded; declared fixes await verification.' },
        { title: 'Fix the issue and rescan', body: 'Use the same target and comparable asset version, engine, and scope. Verify completed checks and passing cases. Status edits or failed scans cannot close issues.' },
        { title: 'Reference a rescan to verify closure', body: 'Choose verified resolution and enter the rescan task ID. The server checks target, version, scope, completion time, and passing cases, then audits closure. Historical scores remain traceable.' },
      ],
    }],
    ['worker-diagnostics', {
      title: 'Worker：排队、心跳、租约和上游错误',
      paragraphs: ['内置 Compose 默认启动 Worker 与内部引擎；独立 Worker 由管理员登记身份并注入一次性显示的 Token。Worker 的公钥用于密封传递目标凭据；运行凭据不能写入镜像或普通日志。healthy 只说明进程与控制面通道正常。'],
      table: { columns: ['现象', '检查位置与处理'], rows: [
        ['任务一直 pending', '检查 Worker 容器是否运行、控制面地址、身份是否启用、支持的扫描类型与租约领取；再看执行策略是否阻断。'],
        ['running 无进度', '任务详情查看最后心跳、租约到期、attempt 和上游会话错误；区分长请求等待与 Worker 失联。'],
        ['401/403 或 aig_model_auth_failed', '核对目标与评估模型各自的 Key、状态和模型权限；两条链路分别排查。'],
        ['aig_model_not_found / 404', '核对模型名称、运行地址和 chat_completions_path，避免重复 /v1 或使用前端根页面。'],
        ['429 / 超时 / 连接失败', '检查供应商配额、Worker 网络和请求超时；合理降低并发。不要只提高总任务预算。'],
        ['lease_expired / 重试耗尽', '先恢复 Worker 和心跳网络，再按新任务验证。旧失败记录保留，不能生成虚假完成报告。'],
        ['下载诊断日志', '报告页点击“下载诊断日志”，将 JSON 提供给支持人员。包括状态、预算和 MCP 执行事件、HTTP/RPC 状态、异常类型与源码位置；不包含密钥、原始对话或工具参数。历史任务可能只有摘要。'],
        ['重试扫描', '失败或超时任务沿用原配置重新校验权限和策略。已有重试仍在排队或运行时打开该任务；结束后再次点击创建新任务，原报告保留。'],
        ['MCP 网关等待审批', '到 MCP 网关检查待审批请求及工具授权。已结束扫描不会因审批完成自动恢复；后续任务仍按网关授权配置校验。'],
        ['MCP 报告与阶段', '执行中展示阶段进度，完成后查看用例结果。完成后 MCP 和 SARIF 报告展示发现、分析和修复建议，并可查看原始内容。模型判断标为待验证；工具参数没有认证字段不能证明服务缺失鉴权。'],
      ] }, link: { path: '/docs/docker-operations', label: '查看容器状态与日志排查' },
    }, {
      title: 'Workers: queues, heartbeat, leases, and upstream errors',
      paragraphs: ['Bundled Compose starts the Worker and internal engine by default. Administrators register standalone identities and inject the one-time Token. Public keys seal target credentials; keep runtime keys out of images and ordinary logs. healthy proves only process/control-plane connectivity.'],
      table: { columns: ['Symptom', 'Where to check and what to do'], rows: [
        ['Task stays pending', 'Check Worker container, control-plane URL, enabled identity, supported scan type, and lease acquisition; then inspect policy blockers.'],
        ['running without progress', 'Inspect heartbeat, lease expiry, attempt, and upstream session errors to distinguish long requests from Worker loss.'],
        ['401/403 or aig_model_auth_failed', 'Check target and evaluator credentials, state, and model access separately.'],
        ['aig_model_not_found / 404', 'Verify model name, endpoint, and chat_completions_path; avoid repeated /v1 or frontend routes.'],
        ['429 / timeout / connection failure', 'Check provider quota, Worker network, and request timeout; reduce concurrency as appropriate. Increasing task budgets alone is insufficient.'],
        ['Expired lease / exhausted retries', 'Restore Worker connectivity and verify with a new task. Preserve the failed record rather than inventing completion.'],
        ['Download diagnostic logs', 'Download JSON from the report page for support. It includes status, budgets, MCP execution events, HTTP/RPC status, exception types, and source locations, without secrets, raw conversations, or tool arguments. Older tasks may contain only a summary.'],
        ['Retry scan', 'Failed or timed-out tasks reuse their settings and recheck permissions and policies. Open an existing queued/running retry; create a new task after it ends. Original reports are retained.'],
        ['MCP gateway approval pending', 'Review pending approvals and tool authorization in the MCP gateway. Approval does not automatically resume an ended scan; subsequent tasks still enforce gateway authorization.'],
        ['MCP reports and stages', 'Live stages show execution progress. Review case results after completion. MCP and SARIF reports display findings, analysis, remediation, and raw content. Model assessments remain unverified; missing authentication fields in tool arguments do not prove missing server authentication.'],
      ] }, link: { path: '/docs/docker-operations', label: 'Read container and log diagnostics' },
    }],
  ])

guide('runtime-trace-guide', ['调用轨迹查询、事件详情与导出', 'Runtime trace search, event details, and export'],
  ['按会话定位模型、Tool、知识检索和治理事件，理解轨迹聚合、性能与完整度，导出可审阅的证据。', 'Locate model, Tool, retrieval, and governance events by session; understand aggregation, performance, completeness, and evidence exports.'], [
    ['trace-layout', {
      title: '会话列表、执行视图和详情面板',
      table: { columns: ['区域', '功能', '阅读顺序'], rows: [
        ['顶部搜索', '按 Turn ID、Tool 名称、风险等级、Request ID、仅错误和时间范围筛选；展示当前筛选条件并支持逐项移除或重置。', '先按时间/请求缩小范围。时间选择器按北京时间解释。'],
        ['左侧会话列表', '展示会话、Agent、聚合方式、完整度、风险、事件/请求数量和更新时间，支持翻页。', '核对主体与完整度后选中会话。'],
        ['中央执行视图', '组织可观察到的对话、模型请求、Tool 调用、检索与治理事件；选择节点打开详情。', '沿用户请求到结果的顺序查找异常步骤。'],
        ['详情面板', '摘要、Payload、参数或选项、结果、Schema、时间与安全信息按节点类型显示。', '用 ID 和证据确认具体调用，避免仅看标签。'],
        ['补充信息 / 性能概览', '展示安全摘要、完整度、治理情况和已加载事件的性能统计。', '先确认加载范围，再分析耗时。'],
      ] }, link: { path: '/runtime-traces', label: '打开调用轨迹' },
    }, {
      title: 'Session list, execution view, and detail panel',
      table: { columns: ['Area', 'Function', 'Reading order'], rows: [
        ['Search', 'Filter by Turn ID, Tool name, risk, Request ID, errors, and time. Remove individual filters or reset all.', 'Narrow by time/request; the date picker interprets Beijing time.'],
        ['Session list', 'Shows session, Agent, aggregation method, completeness, risk, event/request count, update time, and pagination.', 'Verify identity and completeness before selecting.'],
        ['Execution view', 'Organizes observed conversations, model requests, Tool calls, retrievals, and governance events; select nodes for detail.', 'Follow the user request to its result and locate the abnormal step.'],
        ['Detail panel', 'Shows summary, payload, arguments/options, result, Schema, timing, and security as applicable to the node.', 'Verify IDs and evidence, not labels alone.'],
        ['Additional details / performance', 'Shows security, completeness, governance, and performance across loaded events.', 'Check loaded scope before drawing timing conclusions.'],
      ] }, link: { path: '/runtime-traces', label: 'Open Runtime Traces' },
    }],
    ['trace-search', {
      title: '示例：定位一次 Tool 调用失败',
      steps: [
        { title: '收集定位信息', body: '从调用方取得出错时间、request_id 或 turn_id 以及 Tool 名称即可；不必复制包含原始 Prompt 和密钥的整份日志。' },
        { title: '打开搜索并设置范围', body: '先覆盖出错时间，输入 Request ID 或 Turn ID，必要时勾选仅错误并填写 Tool 名。点击查询；若无结果，逐项移除过窄条件，并核对当前账号权限。' },
        { title: '选中会话和 Tool 节点', body: '查看调用时间、状态、错误码、call_id 以及父调用关系，再看参数、结果与安全页签。被治理阻断与已发往上游后失败是不同状态。' },
        { title: '回溯父步骤和关联请求', body: '使用 parent_call_id、step_id 和 request_id 理解调用来源。若是聚合会话，展开网关请求查看每次请求的匹配原因和消息数量。' },
        { title: '导出脱敏证据', body: '记录会话/事件 ID、问题时间和稳定错误码，导出脱敏 JSON 或 PDF 交给对应负责人。仅在必要且有权限时申请原始 JSON。' },
      ],
    }, {
      title: 'Example: locate a failed Tool call',
      steps: [
        { title: 'Collect identifiers', body: 'Obtain failure time, request_id or turn_id, and Tool name. A complete log containing raw prompts and secrets is unnecessary.' },
        { title: 'Open search and narrow the scope', body: 'Cover the failure time and enter Request ID or Turn ID; optionally enable errors-only and Tool name. Search, then remove overly narrow filters individually if empty and verify account permissions.' },
        { title: 'Select the session and Tool node', body: 'Inspect time, status, error code, call_id, parent relationships, arguments, results, and security. Governance blocking differs from an upstream execution failure.' },
        { title: 'Trace parent steps and related requests', body: 'Use parent_call_id, step_id, and request_id. For aggregated sessions, expand gateway requests to inspect match reasons and message counts per request.' },
        { title: 'Export redacted evidence', body: 'Record session/event IDs, time, and stable error code, then export redacted JSON/PDF for the responsible reviewer. Request raw JSON only when necessary and permitted.' },
      ],
    }],
    ['event-fields', {
      title: '事件详情每个部分解决什么问题',
      table: { columns: ['页签 / 字段', '用途'], rows: [
        ['摘要', '定位事件类型、状态、来源、目标与关联 ID。trace_id 关联整条轨迹，turn_id 关联一轮，step_id 关联步骤，call_id 标识调用，parent_call_id 标识父调用。'],
        ['Payload', '查看服务端脱敏后的结构化事件，字段缺失表示未上报或不可见，不能补猜原始内容。'],
        ['参数 / 请求选项', '查看 Tool 输入或模型请求选项，识别参数错误与实际请求配置；展示值仍遵循脱敏规则。'],
        ['结果', '查看调用输出、错误或返回摘要；没有输出时结合状态与结束事件排查。'],
        ['Schema', '核对工具/事件结构与参数要求，识别输入与声明结构不一致。'],
        ['时间', '核对开始、结束与耗时。节点类型和是否仅为观察事件决定此页签是否可见。'],
        ['安全', '查看风险码、治理裁决、关联 Finding 与证据。治理裁决记录本次检查决定，上游执行结果见对应调用事件。'],
      ] },
    }, {
      title: 'What each event detail section answers',
      table: { columns: ['Tab / field', 'Purpose'], rows: [
        ['Summary', 'Identify event type, state, source, target, and IDs. trace_id groups the trace, turn_id a turn, step_id a step, call_id a call, and parent_call_id its parent.'],
        ['Payload', 'Inspect the server-redacted event structure. Missing fields indicate absent reporting or visibility, not an invitation to infer original content.'],
        ['Arguments / request options', 'Inspect Tool inputs or model options for incorrect parameters and actual request settings under redaction rules.'],
        ['Result', 'Inspect output, errors, or summaries; check status and completion events if no output exists.'],
        ['Schema', 'Compare declared Tool/event structure with inputs.'],
        ['Timing', 'Inspect start, end, and duration; availability depends on node type and whether it is only an observation.'],
        ['Security', 'Inspect risk codes, governance decisions, Findings, and evidence. Governance decisions record the checks performed. Review the corresponding call events for upstream execution results.'],
      ] },
    }],
    ['trace-sources', {
      title: '完整度与会话聚合：有哪些证据，缺哪些证据',
      table: { columns: ['标识', '说明'], rows: [
        ['full', '存在 Agent SDK 及关联事件；覆盖仍以实际生命周期上报为准。'],
        ['model_only', '只有模型网关；能解释模型请求，但没有完整 Agent Turn、Step 和 Tool 运行上下文。'],
        ['mcp_only', '只有 MCP 网关；能解释工具网关事件，缺少模型及 Agent 生命周期。'],
        ['gateway_partial', '多类网关事件但缺少 Agent SDK；不能据此重建完整业务意图。'],
        ['网关请求聚合', '将有显式会话关联或符合消息匹配规则的请求组织起来；展开请求列表核对匹配原因、数量和状态。聚合不把 model_only 自动升级为 full。'],
      ] }, paragraphs: ['Dify 资产采集不会自动产生完整调用轨迹。要看到动态事件，需让实际模型/MCP 调用经过相应网关；要看到完整 Agent 步骤，接入方还需要上报生命周期与关联 ID。同一 App 的资产配置只能说明已配置了什么，不能证明这些节点在某次会话执行过。'],
      link: { path: '/docs/model-gateway', label: '查看模型网关接入' },
    }, {
      title: 'Completeness and aggregation: available and missing evidence',
      table: { columns: ['Label', 'Meaning'], rows: [
        ['full', 'Agent SDK plus associated events; scope still depends on actual lifecycle reporting.'],
        ['model_only', 'Model Gateway only: explains model requests without full Agent Turn, Step, or Tool context.'],
        ['mcp_only', 'MCP Gateway only: explains tool gateway events without model or Agent lifecycle.'],
        ['gateway_partial', 'Multiple gateway sources without Agent SDK: insufficient to reconstruct complete business intent.'],
        ['Gateway request aggregation', 'Organizes requests by explicit session association or message matching. Expand requests to inspect match reason, counts, and state. Aggregation does not upgrade model_only to full.'],
      ] }, paragraphs: ['Dify inventory does not automatically create complete runtime traces. Route real model/MCP calls through the corresponding gateways to observe them; lifecycle reporting and correlation IDs are needed for full Agent steps. App configuration establishes configured nodes, not their execution in a particular session.'],
      link: { path: '/docs/model-gateway', label: 'Read Model Gateway integration' },
    }],
    ['performance', {
      title: '性能概览与持续加载',
      paragraphs: ['性能统计注明已加载事件数和总事件数。长会话需加载完整事件后评估总耗时；并发调用按时间重叠关系分析用户等待时长。'],
      bullets: ['模型慢：先定位模型请求的时间与返回状态，再看目标服务和请求选项。', '工具慢：检查 Tool 调用及父步骤，区分等待审批、网关阻断、网络等待和工具执行。', '事件不全：检查接入方是否发送开始/结束事件和一致 ID，再确认时间筛选、权限和分页。', '页面刷新只读取已上报数据，不会补录缺失的 Agent 内部步骤。'],
    }, {
      title: 'Performance and incremental loading',
      paragraphs: ['Performance statistics show loaded and total event counts. Load all events before assessing total session time; account for overlapping concurrent calls when analyzing user wait time.'],
      bullets: ['Slow model: locate request timing/status, then inspect upstream service and request options.', 'Slow Tool: inspect the call and parent step; distinguish approval waits, blocking, network waits, and execution.', 'Incomplete events: check start/end reporting and consistent IDs, then filters, permissions, and pagination.', 'Refresh retrieves reported data; it does not reconstruct missing internal Agent steps.'],
    }],
    ['trace-export', {
      title: '脱敏导出与原始 JSON 授权',
      steps: [
        { title: '选中会话并点击导出', body: '核对会话主体、时间范围及关联事件，日常复核选择脱敏 JSON 或 PDF。PDF 只支持脱敏内容。' },
        { title: '确有需要时选择原始 JSON', body: '仅管理员、超级管理员或隐私审计角色可以申请。按弹窗再次验证当前密码，服务端签发 5 分钟、单次有效的授权。普通安全审计员只能查看脱敏数据。' },
        { title: '完成下载并保留审计线索', body: '在有效期内完成一次原始导出；授权失效或已用需重新验证。记录导出对应 Trace ID；原始文件可能包含 PII，应交给获授权的审阅者。' },
      ], paragraphs: ['列表、搜索、执行视图和详情使用服务端脱敏投影。原始 Payload 独立加密保存；原始导出流程会产生安全审计。调用轨迹用于跨模型、Tool、检索和治理定位；模型网关“隐私链路追踪”用于查看单次请求的隐私处理阶段，两者用途不同。'],
    }, {
      title: 'Redacted exports and raw JSON authorization',
      steps: [
        { title: 'Select the session and Export', body: 'Verify identity, time, and events. Use redacted JSON or PDF for routine review. PDF supports redacted content only.' },
        { title: 'Choose raw JSON only when required', body: 'Only administrators, super administrators, and privacy auditors can request it. Reverify the current password to receive a five-minute, single-use authorization. Security auditors have redacted access only.' },
        { title: 'Download and retain audit identifiers', body: 'Complete the raw export within validity; expired or consumed authorization requires revalidation. Record Trace ID. Raw files can contain PII and should go only to authorized reviewers.' },
      ], paragraphs: ['Lists, search, execution views, and details use server-redacted projections. Raw payloads are encrypted separately and export is audited. Runtime Traces correlates model, Tool, retrieval, and governance events; Model Gateway Pipeline Trace inspects privacy processing within a request.'],
    }],
  ])

const screenshots = [
  ['security-scan-guide', 'page-map', 'security-targets', '扫描目标与六个工作区', 'Scan targets and six workspaces'],
  ['dify-security-access', 'credential-map', 'dify-credentials', 'Dify 三种用途的目标凭据', 'Target credentials for three Dify purposes'],
  ['dify-security-access', 'connection-checklist', 'dify-target-config', 'Dify 运行地址、Console 地址与应用 ID', 'Dify runtime URL, Console URL, and app IDs'],
  ['security-operations', 'schedules', 'security-schedules', '定时计划与执行记录入口', 'Schedules and execution history entry points'],
  ['runtime-trace-guide', 'trace-layout', 'runtime-trace-search', '调用轨迹与证据检索', 'Runtime traces and evidence search'],
]
for (const [slug, id, name, zh, en] of screenshots) {
  locales.forEach((locale, i) => {
    const alt = i === 0 ? zh : en
    articles[locale][slug].sections.find(section => section.id === id).image = {
      name, alt,
      caption: i === 0 ? `${alt}。当前页面组件的文档演示截图，数据与 ID 均为示例；点击可放大。` : `${alt}. Documentation capture of current UI components with sample data and IDs; click to enlarge.`,
    }
  })
}

export const securityGuides = articles
