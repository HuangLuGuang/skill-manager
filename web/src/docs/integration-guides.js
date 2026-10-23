import { integrationChoiceSections } from './integration-choice.js'

const zh = {
  'scenario-selection': {
    eyebrow: '开始使用',
    title: '按产品和运行方式选择接入方案',
    summary: '先判断治理对象在哪里运行、能否安装客户端、是否能修改运行时，再选择客户端托管、Runtime API、Dify API 或 Scanner。',
    sections: [
      integrationChoiceSections['zh-CN'],
      {
        id: 'decision-table',
        title: '不同产品使用不同方案',
        paragraphs: ['“创建智能体”只建立平台侧身份和授权关系，不会自动启动或接管实际产品。接入方式由产品形态和可控制的执行点决定。'],
        table: {
          columns: ['场景 / 产品', '首选方案', '主要解决的问题', '还需要什么'],
          rows: [
            ['Codex、Claude Code、Gemini CLI、OpenCode、Hermes 等本地工具', { path: '/docs/client-management', label: 'Agent Manager Client' }, '发现本地 Agent 和 Skill、模型配置、安装、隔离、恢复与巡检', '启用客户端 AIDR 插件 Hook 并完成宿主信任；同步加载前验签走开发者指南'],
            ['自研 Agent Runtime、服务端 Agent', { path: '/docs/runtime-integration', label: 'Agent 运行凭证 + Runtime API/SDK' }, '在真实 Skill Loader、Tool 调用和 Turn/Step 中执行校验与上报', '在代码中接入验签、can-load、check-tool 和 Runtime Trace'],
            ['Dify Chatflow / Workflow', { path: '/docs/dify-security-access', label: 'Dify API 资产纳管' }, '采集应用、DSL、节点、Prompt、Tool、MCP 与知识库引用并执行安全扫描', '按用途配置 Console、App 和 Knowledge API 权限'],
            ['客户主机、共享目录或 CI 中只有 Skill 文件', { path: '/docs/scanner-access', label: '二进制 Scanner' }, '批量发现、预检并提交 Skill 扫描', 'Scanner 用于提交扫描并读取自己的结果；运行校验使用 Agent 运行凭证'],
            ['只能修改模型或 MCP 地址的第三方应用', { path: '/docs/credential-management', label: '模型/MCP 数据面接入' }, '通过受限凭证调用允许的模型或 MCP Gateway', '只能形成网关侧证据，不能伪造成完整 Agent 运行轨迹'],
          ],
        },
        callout: { type: 'note', title: 'Hook 默认通过客户端 AIDR 接入', body: '客户端按策略管理受支持产品的插件、Hook 配置和后台接收器。完成原生信任后，用真实事件验收采集和工具策略；同步 Skill 加载前验签按开发者指南接入真实 Loader 或受支持事件。' },
      },
      {
        id: 'local-tools',
        title: '场景一：本地现成工具优先使用客户端',
        steps: [
          { title: '创建客户端接入凭证并安装客户端', body: '客户端凭证只负责主机注册、心跳、策略和任务，不直接调用模型或 MCP。' },
          { title: '发现本地 Agent 和 Skill 目录', body: '核对 Agent 类型、实际目录和客户端能力，不把共享目录强行归属给单一 Agent。' },
          { title: '自动登记并下发配置', body: '客户端上报后平台自动登记本机 Agent 身份；客户端执行模型配置、Skill 安装、隔离与恢复任务。' },
          { title: '启用 AIDR 插件 Hook 并验收', body: '在客户端策略选择产品和 Hook 通道，核对安装、启用、原生信任及新会话事件。工具拦截按模式和受支持执行点验收。' },
        ],
      },
      {
        id: 'custom-runtime',
        title: '场景二：自研 Agent 直接接运行时接口',
        flow: [
          { label: '平台登记', value: '创建智能体并绑定 Skill' },
          { label: '可信身份', value: '签发 Agent 运行凭证' },
          { label: '加载前', value: '验签 + can-load' },
          { label: 'Tool 前', value: 'check-tool', type: 'decision' },
          { label: '运行中', value: 'Trace 上报', type: 'success' },
        ],
        bullets: ['平台地址、Agent ID 和运行凭证必须指向同一个平台智能体。', '管理员登录 Token、Scanner Token 和外部模型 API Key 都不能替代 Agent 运行凭证。', '自研 Runtime 能控制真实 Loader、Tool 和生命周期，因此最适合形成完整运行轨迹。'],
        link: { path: '/docs/runtime-integration', label: '查看 Runtime API、Verifier 与 Hook 接入' },
      },
      {
        id: 'dify',
        title: '场景三：Dify 通过 API 做资产和风险纳管',
        paragraphs: ['平台分别使用 Dify Console、App 和 Knowledge API 获取配置证据、执行测试和按授权检查知识资产。'],
        table: { columns: ['接入点', '平台得到什么', '后续验证'], rows: [
          ['Console API / 无密钥 DSL', '应用档案、工作流、节点、Prompt 摘要、Tool、MCP 和知识库引用', '节点执行情况见运行轨迹'],
          ['App API', '对已发布应用执行授权范围内的动态测试', '单次测试不能证明全部业务路径安全'],
          ['Knowledge API', '经明确授权后的知识库元数据和有界内容风险检查', '读取内容需单独授权'],
          ['Runtime Trace', '真实节点、模型和 Tool 执行证据', '没有 Trace 时不能把 DSL 配置标记为 executed'],
        ] },
        image: { name: 'dify-target-config', alt: 'Dify 扫描目标连接配置', caption: 'Dify 目标分别填写运行 API、Console 地址、Workspace ID 和 App ID；凭据在目标保存后按用途单独配置。' },
        link: { path: '/docs/dify-security-access', label: '查看 Dify 完整纳管步骤' },
      },
      {
        id: 'model-choice',
        title: '模型接入：先区分内置数据面与外部 AI 网关',
        table: { columns: ['模式', '模型流量', '平台负责'], rows: [
          ['内置模型网关', '先进入 Agent Manager，再转发上游供应商', '模型范围、隐私策略、Prompt 防护、压缩、用量和调用审计'],
          ['外部 AI 网关', 'Agent 或客户端直接调用客户网关，不经过内置模型代理', '连接配置、外部 Agent 注册、API Key 密文、动态模型目录、任务下发和审计'],
        ] },
        link: { path: '/docs/external-ai-gateway', label: '查看外部 AI 网关接入' },
      },
    ],
  },
  'external-ai-gateway': {
    eyebrow: '模型接入',
    title: '使用客户已有的外部 AI 网关',
    summary: '连接客户网关的管理面与模型面，为平台智能体注册独立身份、保存一次性 API Key、动态获取模型，并按平台 Agent 或客户端场景交付配置。',
    sections: [
      {
        id: 'boundary',
        title: '适用范围和职责边界',
        paragraphs: ['外部 AI 网关模式不使用 Agent Manager 内置模型代理。外部网关负责 Agent 注册、API Key、模型目录和模型调用；Agent Manager 负责连接配置、平台 Agent 映射、Key 密文、客户端策略、任务与审计；Skill 扫描和运行校验仍由 Agent Manager 独立完成。'],
        table: { columns: ['对象', '使用的凭证', '用途'], rows: [
          ['AITM Backend → 外部网关管理面', '管理 Token（HMAC）', '注册、查询、更新和删除外部 Agent'],
          ['实际 Agent → AITM', '绑定 Agent 的运行凭证', '证明平台 Agent 身份并领取当前模型连接信息'],
          ['实际 Agent → 外部网关模型面', '外部网关签发的 Agent API Key', '获取模型目录并调用模型'],
        ] },
        callout: { type: 'warning', title: '两类凭证不能互换', body: '外部模型 API Key 不能调用 AITM 的 Skill 治理接口；AITM Agent 运行凭证也不能直接替代外部网关 Bearer Key。' },
      },
      {
        id: 'end-to-end-flow',
        title: '完整模型接入流程',
        paragraphs: ['平台负责建立网关连接、外部身份和凭证映射；自研 Agent 运行时先向 AITM 领取当前模型连接信息，再使用返回的外部 API Key 直接调用客户网关。'],
        flow: [
          { label: '配置网关', value: '管理面地址、模型面地址和管理 Token' },
          { label: '创建智能体', value: '选择外部网关并刷新模型目录' },
          { label: '签发凭证', value: '绑定智能体并包含 model:chat' },
          { label: '领取模型信息', value: 'GET /runtime/external-model/credential', type: 'decision' },
          { label: '调用模型', value: '使用返回的 Base URL、模型和外部 API Key', type: 'success' },
        ],
        callout: { type: 'note', title: '推荐用于自研 Agent', body: '自研 Agent 可以在启动或配置刷新时主动领取模型信息，并把凭据只保存在受控进程内。无法修改运行时代码的现成产品应使用客户端配置下发或该产品支持的供应商配置方式。' },
      },
      {
        id: 'configure',
        title: '第一步：配置并验证外部网关连接',
        steps: [
          { title: '打开“模型接入 → 外部 AI 网关”', body: '新增连接，分别填写管理面 Base URL、模型面 Base URL、Token ID、Token Value 和启用状态。两个 Base URL 可能使用不同端口。' },
          { title: '测试连接', body: '测试会使用保存的管理凭据完成签名请求，并确认模型面 /v1/models 端点可达。使用已注册 Agent 的 API Key 刷新其可用模型目录。' },
          { title: '保护管理 Token', body: 'Token Value 加密保存，页面只返回掩码；编辑时留空表示保留原值。' },
        ],
        image: { name: 'external-gateways', alt: '外部 AI 网关连接列表', caption: '外部 AI 网关页面区分管理面与模型面地址，并展示连接测试状态。' },
        link: { path: '/external-ai-gateways', label: '打开外部 AI 网关' },
      },
      {
        id: 'platform-agent',
        title: '第二步：为平台智能体注册外部身份并选择模型',
        steps: [
          { title: '新增智能体并选择“外部 AI 网关”', body: '设置稳定 Agent ID、名称、责任归属和目标网关。平台智能体本身不要求安装客户端。' },
          { title: '点击“准备并刷新模型”', body: '平台先保存草稿，再向外部网关注册独立 Agent，立即加密保存一次性 API Key，并用该 Key 请求 /v1/models。' },
          { title: '选择默认模型并保存', body: '模型列表来自该外部 Agent API Key 的实时目录，平台不维护手工模型清单。当前实现保存一个默认模型。' },
          { title: '保存智能体', body: '确认默认模型、Skill 范围、状态和责任归属后保存。运行凭证在下一步单独签发。' },
        ],
        image: { name: 'agent-external-model', alt: '新增智能体时选择外部 AI 网关并准备模型', caption: '当前页面示例：填写平台智能体基础信息并选择外部 AI 网关后，由平台完成外部身份注册和模型目录刷新。' },
        link: { path: '/agents', label: '打开智能体管理' },
      },
      {
        id: 'runtime-credential',
        title: '第三步：为自研 Agent 签发运行凭证',
        steps: [
          { title: '打开统一凭证中心', body: '选择“给 Agent 使用”，绑定刚才创建的平台智能体。凭证绑定决定它只能领取该智能体的外部模型信息。' },
          { title: '授予模型权限', body: '凭证必须包含 model:chat；如果配置了允许模型范围，其中必须包含智能体当前默认模型。Skill 验签、加载和 Tool 检查按需要另外授予 runtime:* 权限。' },
          { title: '安全交付一次性明文', body: '把 AITM Agent 运行凭证交给对应自研 Agent 的服务端运行环境。不要把它放进前端代码、普通日志、截图或代码仓库。' },
        ],
        link: { path: '/credentials', label: '打开统一凭证中心' },
      },
      {
        id: 'runtime-model-credential',
        title: '第四步：自研 Agent 获取外部模型信息并调用模型',
        paragraphs: ['自研 Agent 使用 AITM Agent 运行凭证调用以下接口。AITM 会校验凭证状态、model:chat、绑定智能体、默认模型范围、外部网关和外部身份，再返回本次运行需要的连接信息。'],
        steps: [
          { title: '调用模型凭据接口', body: 'Authorization 必须使用绑定当前智能体的 AITM Agent 运行凭证，不是管理员 Token，也不是外部网关管理 Token。响应带有 Cache-Control: no-store。', code: 'GET /api/v1/runtime/external-model/credential\nAuthorization: Bearer <Agent运行凭证>' },
          { title: '读取返回字段', body: 'model_base_url、model 和 protocol 用于初始化模型 SDK；api_key 是外部网关为该智能体签发的 Bearer Key，只能在受控运行环境中使用。', code: '{\n  "gateway_id": 1,\n  "gateway_name": "客户 AI 网关",\n  "model_base_url": "https://ai-gateway.example.com",\n  "model": "example-model",\n  "protocol": "openai-compatible",\n  "external_agent_id": "aitm-customer-assistant",\n  "key_id": "key-demo",\n  "api_key": "<外部网关 Agent API Key>"\n}' },
          { title: '调用外部模型接口', body: '使用返回的 model_base_url、model 和 api_key，按外部网关支持的 OpenAI-compatible 协议调用模型。模型请求直接进入客户网关，不经过 AITM 内置模型代理。', code: 'POST <model_base_url>/v1/chat/completions\nAuthorization: Bearer <api_key>\nContent-Type: application/json\n\n{"model":"<model>","messages":[{"role":"user","content":"hello"}]}' },
          { title: '完成真实调用验收', body: '只有实际模型请求成功，才能确认接入完成。获取到模型名称或成功写入配置，都不能代替真实调用验证。', expected: '外部网关返回模型响应；AITM 安全审计记录智能体领取过模型凭据，但不记录 API Key 明文。' },
        ],
        callout: { type: 'warning', title: '不要持久化返回的 API Key', body: '建议仅保存在服务端进程内存或受控密钥容器中，按需重新领取。禁止返回给浏览器、写入普通日志或随 Runtime Trace 上报。' },
      },
      {
        id: 'key-inventory',
        title: '第五步：查看 API Key 与使用关系',
        paragraphs: ['网关列表的“API Key”抽屉展示平台创建的 Key、Key ID、外部 Agent 身份以及使用它的平台智能体。默认只显示掩码；只有具备敏感权限的管理员输入当前密码后才能查看明文，成功或失败都会写入安全审计。'],
        image: { name: 'external-gateway-keys', alt: '外部网关 API Key 与智能体使用关系', caption: 'Key 清单用于核对哪个平台智能体正在使用哪个外部身份；文档和普通日志不得记录明文。' },
      },
      {
        id: 'client-model-switching',
        title: '第六步：客户端批量准备本机 Agent 并切换模型',
        paragraphs: ['平台默认策略启用“使用外部网关”后，已接入客户端会提示策略变化。点击“为全部 Agent 准备模型”会逐个登记本机 Agent、为每个 Agent 建立独立外部身份和托管 API Key，并读取该 Key 实际可见的模型目录，不需要逐个点击刷新。'],
        steps: [
          { title: '先修改平台默认策略', body: '在“客户端管理”的平台默认策略中启用“使用外部网关”，选择默认外部网关，并决定是否允许客户端选择模型。外部模型流量不经过内置模型网关，因此 Prompt 防护、Token 压缩和内置调用审计会被禁用。保存后在线客户端获取新策略。' },
          { title: '批量准备模型目录', body: '客户端保留当前选中的 Agent，依次准备所有支持模型配置的本机 Agent。完成后可以关闭横幅；策略或目标网关变化时会重新提示。' },
          { title: '为当前 Agent 选择模型', body: '外部网关启用时只展示当前 Agent 的外部模型目录，不混入内置网关模型。切换前备份原配置，成功后读回实际网关地址和模型。' },
          { title: '验证真实调用', body: '点击“验证真实调用”后保持处理中状态，直到目标工具返回结果。失败时显示明确错误并自动恢复原配置；目录刷新或配置写入成功不能替代真实调用验证。' },
        ],
        image: { name: 'client-external-models', alt: '客户端批量准备外部网关模型并按 Agent 切换', caption: '客户端为全部本机 Agent 准备独立外部身份；选中 Agent 后只展示其 API Key 可用的外部模型。图中为隔离演示数据。' },
        link: { path: '/clients', label: '打开客户端管理' },
      },
      {
        id: 'runtime-paths',
        title: '第七步：其他产品按自身配置方式接入',
        table: { columns: ['运行场景', '交付方式', '生效判断'], rows: [
          ['Dify', '将平台为该 Dify 应用创建的外部 Agent API Key 配置到 Dify 模型供应商', '在 Dify 发布应用中执行真实调用；当前不会自动修改 Dify 供应商配置'],
        ] },
        callout: { type: 'note', title: '写入后验证调用', body: '客户端或管理员看到模型名称，只能证明配置或目录已获取。验收必须由实际 Codex、Claude Code、Hermes、Dify 或自研 Agent 完成一次真实调用。' },
      },
      {
        id: 'limits',
        title: '当前边界和常见问题',
        table: { columns: ['问题', '正确理解'], rows: [
          ['外部网关返回多个模型', '页面展示动态目录，但平台智能体当前保存一个默认模型；“可用模型范围”和“默认模型”不是同一个概念。'],
          ['在平台选择允许模型', '客户端任务和凭证可以限制平台下发；直接调用外部网关时，强制模型范围仍取决于外部网关是否对该 Key 执行模型授权。'],
          ['停用外部 Agent', '已验证的当前网关实现中，inactive 不会使既有 Key 失效；需要吊销时删除外部 Agent。'],
          ['切回内置模型或删除平台智能体', '平台删除不再使用的外部绑定，并调用外部网关删除对应 Agent，使原 Key 失效。'],
          ['API Key 页面可查看明文', '这是受敏感权限、密码复核和审计约束的运维能力，不应作为日常分发方式。'],
        ] },
      },
    ],
  },
}

const en = {
  'scenario-selection': {
    eyebrow: 'Get started',
    title: 'Choose an integration by product and runtime',
    summary: 'Identify where the governed product runs, whether a Client can be installed, and whether its runtime can be changed before choosing Client management, Runtime APIs, Dify APIs, or Scanner.',
    sections: [
      integrationChoiceSections['en-US'],
      {
        id: 'decision-table', title: 'Use a different path for each product',
        paragraphs: ['Creating an Agent establishes a platform identity and authorization record. It does not start or take over the actual product. The product shape and controllable execution points determine the integration.'],
        table: { columns: ['Scenario / product', 'Primary path', 'What it solves', 'What else is needed'], rows: [
          ['Local Codex, Claude Code, Gemini CLI, OpenCode, or Hermes', { path: '/docs/client-management', label: 'Agent Manager Client' }, 'Discover local Agents and Skills; configure models; install, quarantine, restore, and inspect', 'Enable Client AIDR plugin Hooks and complete native trust; use the developer guide for synchronous pre-load verification'],
          ['Custom Agent Runtime or server-side Agent', { path: '/docs/runtime-integration', label: 'Agent runtime credential + Runtime API/SDK' }, 'Check the real Skill loader and Tool path and report Turn/Step events', 'Integrate signature, can-load, check-tool, and Runtime Trace calls in code'],
          ['Dify Chatflow / Workflow', { path: '/docs/dify-security-access', label: 'Dify API asset governance' }, 'Collect apps, DSL, nodes, prompts, tools, MCP, and knowledge references and run security scans', 'Configure Console, App, and Knowledge API access by purpose'],
          ['Skill files on a customer host, shared directory, or CI', { path: '/docs/scanner-access', label: 'Binary Scanner' }, 'Discover, precheck, and submit Skills in batches', 'Scanner submits scans and reads its own results; runtime checks use an Agent runtime credential'],
          ['Third-party app where only a model or MCP URL can change', { path: '/docs/credential-management', label: 'Model/MCP data-plane integration' }, 'Call authorized models or MCP gateways with scoped credentials', 'Gateway evidence is partial and cannot be presented as a full Agent trace'],
        ] },
        callout: { type: 'note', title: 'Use Client AIDR for Hook integration by default', body: 'The Client manages supported plugins, Hook configuration and the background receiver according to policy. Complete native trust and verify actual events and tool decisions. For synchronous Skill verification, follow the developer guide at the real Loader or a supported event.' },
      },
      {
        id: 'local-tools', title: 'Scenario 1: prefer the Client for local packaged tools',
        steps: [
          { title: 'Create a Client credential and install the Client', body: 'A Client credential handles host registration, heartbeat, policy, and tasks. It cannot call a model or MCP directly.' },
          { title: 'Discover local Agents and Skill roots', body: 'Verify Agent type, real directories, and reported capabilities. Do not assign a shared directory to one Agent without evidence.' },
          { title: 'Register automatically and deliver configuration', body: 'The platform registers each local Agent automatically after Client reporting. The Client executes model configuration and Skill install, quarantine, and restore tasks.' },
          { title: 'Enable and verify AIDR plugin Hooks', body: 'Select products and the Hook channel in Client policy. Verify installation, enablement, native trust and new-session events. Test tool interception by mode and supported execution point.' },
        ],
      },
      {
        id: 'custom-runtime', title: 'Scenario 2: connect a custom Agent through Runtime APIs',
        flow: [
          { label: 'Register', value: 'Create Agent and bind Skills' },
          { label: 'Identity', value: 'Issue Agent runtime credential' },
          { label: 'Before load', value: 'Signature + can-load' },
          { label: 'Before Tool', value: 'check-tool', type: 'decision' },
          { label: 'During run', value: 'Trace events', type: 'success' },
        ],
        bullets: ['The platform URL, Agent ID, and runtime credential must resolve to the same platform Agent.', 'An administrator token, Scanner token, or external-model API key cannot replace the Agent runtime credential.', 'A custom Runtime controls the real loader, Tool path, and lifecycle, so it is the best route to a complete runtime trace.'],
        link: { path: '/docs/runtime-integration', label: 'Read Runtime API, Verifier, and Hook integration' },
      },
      {
        id: 'dify', title: 'Scenario 3: govern Dify assets and risks through APIs',
        paragraphs: ['Dify Console, App, and Knowledge APIs provide configuration evidence, authorized tests, and bounded knowledge inspection.'],
        table: { columns: ['Integration point', 'Evidence obtained', 'Further verification'], rows: [
          ['Console API / secret-free DSL', 'App profile, workflow, nodes, prompt metadata, tools, MCP, and knowledge references', 'Review runtime traces for node execution'],
          ['App API', 'Authorized dynamic tests against the published app', 'One test does not cover every business path'],
          ['Knowledge API', 'Authorized knowledge metadata and bounded content-risk checks', 'Content reads require separate authorization'],
          ['Runtime Trace', 'Actual node, model, and Tool execution evidence', 'Without Trace, DSL configuration cannot be marked executed'],
        ] },
        image: { name: 'dify-target-config', alt: 'Dify scan-target connection settings', caption: 'Configure runtime API, Console URL, Workspace ID, and App ID separately; add credentials by purpose after saving the target.' },
        link: { path: '/docs/dify-security-access', label: 'Read the complete Dify governance path' },
      },
      {
        id: 'model-choice', title: 'Model access: distinguish the built-in data plane from an external AI gateway',
        table: { columns: ['Mode', 'Model traffic', 'Platform responsibility'], rows: [
          ['Built-in model gateway', 'Enters Agent Manager before forwarding to an upstream provider', 'Model scopes, privacy, Prompt protection, compression, usage, and call audit'],
          ['External AI gateway', 'Agent or Client calls the customer gateway directly', 'Connection settings, external Agent registration, encrypted API keys, dynamic model catalog, tasks, and audit'],
        ] },
        link: { path: '/docs/external-ai-gateway', label: 'Read external AI gateway integration' },
      },
    ],
  },
  'external-ai-gateway': {
    eyebrow: 'Model access', title: 'Use an existing customer AI gateway',
    summary: 'Connect the customer gateway management and model planes, register one external identity per platform Agent, retain its one-time API key, discover models dynamically, and deliver configuration by runtime scenario.',
    sections: [
      {
        id: 'boundary', title: 'Scope and responsibility boundary',
        paragraphs: ['External-gateway mode bypasses the Agent Manager built-in model proxy. The external gateway owns Agent registration, API keys, model catalog, and model calls. Agent Manager owns connection settings, platform-Agent mapping, encrypted keys, Client policy, tasks, and audit. Skill scanning and runtime checks remain independent Agent Manager controls.'],
        table: { columns: ['Caller', 'Credential', 'Purpose'], rows: [
          ['AITM Backend → external management API', 'HMAC management token', 'Register, query, update, and delete external Agents'],
          ['Runtime Agent → AITM', 'Agent-bound runtime credential', 'Prove platform Agent identity and resolve current model connection'],
          ['Runtime Agent → external model API', 'External Agent API key', 'List models and invoke the model'],
        ] },
        callout: { type: 'warning', title: 'The two credentials are not interchangeable', body: 'An external model key cannot call AITM Skill-governance APIs. An AITM runtime credential cannot replace the external gateway Bearer key.' },
      },
      {
        id: 'end-to-end-flow', title: 'Complete model integration flow',
        paragraphs: ['The platform establishes the gateway connection, external identity, and credential mapping. At runtime, a custom Agent resolves its current model connection from AITM, then calls the customer gateway directly with the returned external API key.'],
        flow: [
          { label: 'Configure gateway', value: 'Management URL, model URL, and management token' },
          { label: 'Create Agent', value: 'Select the gateway and refresh the model catalog' },
          { label: 'Issue credential', value: 'Bind the Agent and include model:chat' },
          { label: 'Resolve model access', value: 'GET /runtime/external-model/credential', type: 'decision' },
          { label: 'Invoke model', value: 'Use the returned Base URL, model, and external API key', type: 'success' },
        ],
        callout: { type: 'note', title: 'Recommended for custom Agents', body: 'A custom Agent can resolve model access during startup or configuration refresh and keep the secret inside a controlled process. Packaged products whose runtime cannot be changed should use Client delivery or their supported provider-configuration path.' },
      },
      {
        id: 'configure', title: 'Step 1: configure and test the external gateway',
        steps: [
          { title: 'Open Model access → External AI gateways', body: 'Create a connection with separate management and model Base URLs, Token ID, Token Value, and enabled state. The two URLs may use different ports.' },
          { title: 'Test the connection', body: 'The test signs a management request with the saved credential and confirms that the model-plane /v1/models endpoint is reachable. Refresh the available model catalog with a registered Agent API key.' },
          { title: 'Protect the management token', body: 'Token Value is encrypted and only a mask is returned. Leaving it empty while editing preserves the existing value.' },
        ],
        image: { name: 'external-gateways', alt: 'External AI gateway connection list', caption: 'The page separates management and model endpoints and reports connection-test state.' },
        link: { path: '/external-ai-gateways', label: 'Open External AI gateways' },
      },
      {
        id: 'platform-agent', title: 'Step 2: register an external identity and choose a model',
        steps: [
          { title: 'Create an Agent and choose External AI gateway', body: 'Set a stable Agent ID, name, ownership, and target gateway. A platform Agent does not require the desktop Client.' },
          { title: 'Select Prepare and refresh models', body: 'The platform saves a draft, registers a dedicated external Agent, immediately encrypts the one-time key, and calls /v1/models with that key.' },
          { title: 'Choose the default model and save', body: 'The catalog comes from this external Agent key. The platform does not maintain a manual catalog. The current Agent record stores one default model.' },
          { title: 'Save the Agent', body: 'Confirm its default model, Skill scope, state, and ownership. Issue the runtime credential separately in the next step.' },
        ],
        image: { name: 'agent-external-model', alt: 'Adding a platform Agent with an external AI gateway and dynamic model catalog', caption: 'Current UI with example data: enter the platform Agent identity and choose an external AI gateway. The platform registers the external identity and refreshes its model catalog.' },
        link: { path: '/agents', label: 'Open Agent management' },
      },
      {
        id: 'runtime-credential', title: 'Step 3: issue a runtime credential for the custom Agent',
        steps: [
          { title: 'Open Credential Center', body: 'Choose Agent usage and bind the platform Agent created above. The binding ensures this credential can resolve only that Agent’s external model information.' },
          { title: 'Grant model access', body: 'The credential must include model:chat. If an allowed-model range is configured, it must include the Agent’s current default model. Add runtime:* scopes separately when Skill signature, load, or Tool checks are needed.' },
          { title: 'Deliver the one-time secret safely', body: 'Inject the AITM Agent runtime credential into the custom Agent’s server-side runtime. Never place it in frontend code, ordinary logs, screenshots, or source control.' },
        ],
        link: { path: '/credentials', label: 'Open Credential Center' },
      },
      {
        id: 'runtime-model-credential', title: 'Step 4: resolve external model information and invoke the model',
        paragraphs: ['The custom Agent calls this endpoint with its AITM Agent runtime credential. AITM validates credential state, model:chat, the bound Agent, default-model scope, gateway state, and external identity before returning the connection details.'],
        steps: [
          { title: 'Call the model credential endpoint', body: 'Authorization must contain the AITM Agent runtime credential bound to this Agent—not an administrator token or the gateway management token. The response includes Cache-Control: no-store.', code: 'GET /api/v1/runtime/external-model/credential\nAuthorization: Bearer <Agent runtime credential>' },
          { title: 'Read the returned fields', body: 'Use model_base_url, model, and protocol to initialize the model SDK. api_key is the external gateway Bearer key issued for this Agent and must remain inside the controlled runtime.', code: '{\n  "gateway_id": 1,\n  "gateway_name": "Customer AI Gateway",\n  "model_base_url": "https://ai-gateway.example.com",\n  "model": "example-model",\n  "protocol": "openai-compatible",\n  "external_agent_id": "aitm-customer-assistant",\n  "key_id": "key-demo",\n  "api_key": "<external Agent API key>"\n}' },
          { title: 'Call the external model endpoint', body: 'Use the returned model_base_url, model, and api_key with the OpenAI-compatible protocol supported by the external gateway. Model traffic goes directly to the customer gateway and bypasses the AITM built-in model proxy.', code: 'POST <model_base_url>/v1/chat/completions\nAuthorization: Bearer <api_key>\nContent-Type: application/json\n\n{"model":"<model>","messages":[{"role":"user","content":"hello"}]}' },
          { title: 'Complete a real-call acceptance test', body: 'Integration is complete only after a real model request succeeds. A visible model name or a successful configuration write is not sufficient.', expected: 'The external gateway returns a model response. AITM Security Audit records that the Agent resolved model access without recording the API key plaintext.' },
        ],
        callout: { type: 'warning', title: 'Do not persist the returned API key', body: 'Prefer process memory or a controlled secret container and resolve again when needed. Never return it to a browser, write it to ordinary logs, or include it in Runtime Trace payloads.' },
      },
      {
        id: 'key-inventory', title: 'Step 5: inspect API keys and usage',
        paragraphs: ['The API Keys drawer lists the key, key ID, external Agent identity, and platform Agent using it. Keys are masked by default. A user with sensitive permission must confirm the current password before reveal, and every successful or failed reveal is audited.'],
        image: { name: 'external-gateway-keys', alt: 'External gateway API keys and Agent usage', caption: 'Use the inventory to map platform Agents to external identities. Never record plaintext keys in docs or ordinary logs.' },
      },
      {
        id: 'client-model-switching', title: 'Step 6: prepare every local Agent and switch models in the Client',
        paragraphs: ['After the platform default policy enables Use external gateway, connected Clients report the policy change. Prepare models for all Agents registers every supported local Agent, creates a dedicated external identity and escrowed API key for each one, and reads the model catalog visible to that key. You do not need to refresh Agents individually.'],
        steps: [
          { title: 'Change the platform default policy first', body: 'In the Clients platform default policy, enable Use external gateway, select the default external gateway, and decide whether Clients may select models. External model traffic bypasses the built-in model gateway, so Prompt Guard, Token compression, and built-in call auditing are disabled. Online Clients receive the new policy after it is saved.' },
          { title: 'Prepare model catalogs in one batch', body: 'The Client preserves the selected Agent while it prepares every supported local Agent. The banner can be dismissed after completion and returns when the policy or target gateway changes.' },
          { title: 'Select a model for the current Agent', body: 'While external-gateway mode is active, the list contains only the selected Agent’s external models and does not mix in built-in-gateway models. The Client backs up the current configuration and reads back the actual gateway URL and model after the switch.' },
          { title: 'Verify a real call', body: 'Verify real call remains in progress until the target tool returns. A failure reports a specific reason and restores the previous configuration automatically. Catalog refresh or a successful configuration write is not sufficient acceptance evidence.' },
        ],
        image: { name: 'client-external-models', alt: 'Client preparing external-gateway models for all local Agents and switching per Agent', caption: 'The Client prepares a dedicated external identity for every local Agent, then shows only the models visible to the selected Agent API key. The screenshot uses isolated fixture data.' },
        link: { path: '/clients', label: 'Open Clients' },
      },
      {
        id: 'runtime-paths', title: 'Step 7: integrate other products through their supported configuration path',
        table: { columns: ['Runtime', 'Delivery path', 'Proof of success'], rows: [
          ['Dify', 'Configure the external Agent API key created for the Dify app in its model provider', 'A published Dify app completes a real call; current integration does not edit Dify provider settings automatically'],
        ] },
        callout: { type: 'note', title: 'Verify a call after writing configuration', body: 'A visible model name proves only that configuration or discovery succeeded. Acceptance requires a real call from Codex, Claude Code, Hermes, Dify, or the custom Agent.' },
      },
      {
        id: 'limits', title: 'Current boundaries and common questions',
        table: { columns: ['Question', 'Correct interpretation'], rows: [
          ['The external gateway returns multiple models', 'The page shows a dynamic catalog, but the Agent currently stores one default model. Available range and default choice are different concepts.'],
          ['The platform selects allowed models', 'Platform tasks and credentials can constrain delivery. Hard enforcement on direct external calls still depends on the external gateway enforcing per-key model scope.'],
          ['The external Agent is set inactive', 'In the verified current gateway, inactive does not revoke an existing key. Delete the external Agent to revoke it.'],
          ['The Agent switches back to built-in models or is deleted', 'The platform removes unused bindings and deletes the corresponding external Agent so the old key becomes invalid.'],
          ['A key can be revealed in the UI', 'Reveal is a password-confirmed, permission-gated, audited operational action—not a normal distribution channel.'],
        ] },
      },
    ],
  },
}

export const integrationGuides = { 'zh-CN': zh, 'en-US': en }
