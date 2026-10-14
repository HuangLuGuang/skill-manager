export const agentIntegrationChoices = {
  'zh-CN': [
    {
      id: 'registration-decision', title: '先判断：什么情况下需要创建智能体？',
      paragraphs: ['当你需要按某个 Agent 单独授权 Skill、限制模型或 MCP 访问，并将调用归属到这个 Agent 时，需要一个平台 Agent 身份。使用 Agent Skill Verifier 或 Agent 运行时校验接口也需要该身份。实际执行任务的仍是已有程序；平台登记保存身份、授权与责任归属。'],
      table: { columns: ['你的目标', '是否需要手动创建', '第一步'], rows: [
        ['按 Agent 做运行授权或校验，尚无身份且不通过客户端发现登记', '需要。登记一个平台 Agent。', '打开“智能体管理 → 登记智能体”。'],
        ['管理电脑上的 Agent、安装 Skill、应用配置和采集事件', '先连接客户端。客户端发现并登记支持的 Agent 后，复用该身份。', '打开“接入与运行 → 电脑上已有的 Agent”。'],
        ['已有平台创建或客户端发现的身份', '复用已有记录。新增接入能力时继续使用同一身份。', '打开该 Agent 的接入指引。'],
        ['普通应用只调用模型 / MCP，或只扫描提交 Skill', '这些用途可直接使用对应凭证，无需先登记 Agent。', '分别进入模型网关、MCP 网关或 Scanner 接入。'],
      ] },
      callout: { type: 'note', title: '目前只有一个想法，还没有运行程序？', body: '可以先登记档案规划权限。要让它处理任务，还需准备自研程序或已有 Agent 产品，并完成下面的运行端接入。选择模型和 Skill 不会生成可对话、可执行任务的程序。' },
    },
    {
      id: 'integration-route', title: '再选择：我的场景应该用什么接入方式？',
      paragraphs: ['先按实际目标选择下面一行，再按它的入口继续。电脑管理、Skill 校验、模型调用和 MCP 调用可以组合；“平台创建 / 客户端发现”表示身份来源，不决定只能使用哪一种接入方式。'],
      table: { columns: ['实际场景', '选择的方式', '身份与凭证', '接下来做什么'], rows: [
        ['自研服务或框架应用，能修改 Skill 加载和工具执行代码', '自研 Agent / 框架应用：Runtime API；需要轨迹时加 SDK。', '复用或登记 Agent，签发绑定它的运行凭证。', { path: '/runtime?scenario=custom', label: '自研接入：把检查接到加载 / 执行位置' }],
        ['管理员工电脑或工作站上的 Agent 与 Skill', 'Agent Manager Client：发现、配置、安装和事件采集。', '先用客户端接入凭证连接；使用发现的 Agent 身份。AIDR Hook 复用设备认证；Runtime API、模型或 MCP 调用另按能力配置运行凭证。', { path: '/runtime?scenario=client', label: '客户端接入：连接并上报本机清单' }],
        ['宿主支持本地 Skill 指令和脚本，希望每次使用 Skill 前校验', 'Agent Skill Verifier；按指引安装和配置启动环境。', '复用或登记 Agent，授权批准 Skill，签发两项校验权限的运行凭证。', { path: '/runtime?scenario=verifier', label: 'Verifier 接入：安装并做通过 / 拒绝验证' }],
        ['普通应用只需要调用模型，不要求按 Agent 管理', '现有应用接入模型网关 → 普通应用调用。', '无需 Agent；创建模型调用凭证。', { path: '/runtime?scenario=model&caller=ordinary', label: '模型接入：配置地址、凭证和模型名' }],
        ['普通 MCP Client 只需要调用网关工具，不要求按 Agent 管理', '现有应用接入 MCP 网关 → 普通应用调用。', '无需 Agent；创建 MCP 网关凭证并限制网关。', { path: '/runtime?scenario=mcp&caller=ordinary', label: 'MCP 接入：配置连接并验证工具调用' }],
        ['同样调用模型或 MCP，但要以某个 Agent 的身份授权和审计', '在模型 / MCP 场景中选择“按 Agent 身份治理”。', '复用或登记 Agent，使用绑定它的运行凭证，增加所需模型 / MCP 权限。', { path: '/runtime', label: '选择模型或 MCP 场景，再选择 Agent 身份' }],
        ['只想批量发现、扫描和提交本地 Skill', 'Skill Scanner。', '无需 Agent；使用 Scanner 接入凭证。', { path: '/docs/scanner-access', label: 'Scanner 接入：配置扫描与上传' }],
      ] },
      callout: { type: 'note', title: '需要“校验失败就强制阻止加载”时怎么选？', body: '能修改代码时，把 Runtime API 校验放到真实 Loader / Dispatcher，并在失败时终止。已有产品支持相应加载事件时，按开发者加载前验签指南适配脚本并验证覆盖范围。日常宿主采集与工具策略通过客户端 AIDR 插件接入。Verifier 依赖宿主每次执行校验脚本；仅安装指令不等于强制拦截。模型网关和 MCP 网关分别治理经过它们的请求，本地 Skill 加载还需单独接入。' },
      link: { path: '/docs/developer-skill-verification', label: '查看开发者加载前验签与手工脚本' },
    },
  ],
  'en-US': [
    {
      id: 'registration-decision', title: 'First decide: when do I need an Agent identity?',
      paragraphs: ['Use a platform Agent identity when you need to authorize Skills, limit model or MCP access and attribute calls to a specific Agent. Agent Skill Verifier and Agent runtime verification APIs also require this identity. Your existing program executes tasks; registration stores identity, permissions and ownership.'],
      table: { columns: ['Goal', 'Manual registration?', 'First action'], rows: [
        ['Agent-specific authorization or verification, with no identity and no Client discovery registration', 'Yes. Register a platform Agent.', 'Open Agents → Register Agent.'],
        ['Manage local Agents, install Skills, apply configuration and collect events', 'Connect the Client first. Reuse the identity it registers for a supported Agent.', 'Open Integration & runtime → Agent on a computer.'],
        ['An identity already exists through registration or Client discovery', 'Reuse it when adding integration capabilities.', 'Open that Agent’s integration guide.'],
        ['Ordinary model / MCP calls, or Skill scanning and submission only', 'Use the corresponding credential directly; Agent registration is optional for these purposes.', 'Open model gateway, MCP gateway or Scanner integration.'],
      ] },
      callout: { type: 'note', title: 'Only have an idea, without a running program yet?', body: 'You can register a record to plan permissions. To execute tasks, prepare a custom program or existing Agent product and connect its runtime below. Selecting models and Skills does not generate an executable or conversational Agent.' },
    },
    {
      id: 'integration-route', title: 'Then choose: which integration fits my scenario?',
      paragraphs: ['Choose the row matching your goal and follow its entry point. Computer management, Skill verification, model calls and MCP calls can be combined. Platform-created and Client-discovered describe identity sources, not exclusive integration modes.'],
      table: { columns: ['Actual scenario', 'Integration', 'Identity and credential', 'Next action'], rows: [
        ['Custom service or framework with editable Skill loading and tool execution code', 'Custom Agent / framework: Runtime APIs; add the SDK for traces.', 'Reuse or register an Agent and issue its bound runtime credential.', { path: '/runtime?scenario=custom', label: 'Custom integration: check at load / execution boundaries' }],
        ['Manage Agents and Skills on employee computers or workstations', 'Agent Manager Client: discovery, configuration, installation and event collection.', 'Connect with a Client credential and reuse discovered identities. AIDR Hooks reuse device authentication; Runtime APIs, model or MCP calls use purpose-specific runtime credentials.', { path: '/runtime?scenario=client', label: 'Client integration: connect and report inventory' }],
        ['A host supports local Skill instructions and scripts; verify before each Skill use', 'Agent Skill Verifier: install and configure the host launch environment.', 'Reuse or register an Agent, authorize the approved Skill and issue a runtime credential with the two verification scopes.', { path: '/runtime?scenario=verifier', label: 'Verifier integration: install and test allow / deny outcomes' }],
        ['An ordinary app only needs model calls without Agent-specific governance', 'Model gateway for an app → Ordinary application.', 'No Agent required; issue a model credential.', { path: '/runtime?scenario=model&caller=ordinary', label: 'Model integration: set endpoint, credential and model' }],
        ['An ordinary MCP Client only needs gateway tools without Agent-specific governance', 'MCP gateway for an app → Ordinary application.', 'No Agent required; issue an MCP gateway credential with gateway limits.', { path: '/runtime?scenario=mcp&caller=ordinary', label: 'MCP integration: configure and verify a tool call' }],
        ['Model or MCP calls need authorization and audit attributed to a specific Agent', 'Choose Use Agent governance in the model / MCP scenario.', 'Reuse or register an Agent; add model / MCP scopes to its bound runtime credential.', { path: '/runtime', label: 'Choose model or MCP integration, then the Agent identity' }],
        ['Only discover, scan and submit local Skills in bulk', 'Skill Scanner.', 'No Agent required; use a Scanner credential.', { path: '/docs/scanner-access', label: 'Scanner integration: configure scanning and uploads' }],
      ] },
      callout: { type: 'note', title: 'Need enforced blocking when verification fails?', body: 'When you control the code, call Runtime APIs at the real Loader / Dispatcher and stop on failure. For products with suitable load events, adapt the scripts in the developer pre-load verification guide and validate coverage. Use Client AIDR plugins for routine host collection and tool policies. Verifier depends on the host executing its script on every use; installing instructions alone does not enforce blocking. Model and MCP gateways govern requests passing through them; local Skill loading requires its own integration.' },
      link: { path: '/docs/developer-skill-verification', label: 'Read developer pre-load verification and manual scripts' },
    },
  ],
}

const zh = {
  eyebrow: '操作指南',
  title: '智能体：何时创建、如何接入与填写步骤',
  summary: '先判断是否需要 Agent 身份，再按实际场景选择接入方式；需要手动登记时，继续填写表单、授权和配置运行端。',
  sections: [
    ...agentIntegrationChoices['zh-CN'],
    {
      id: 'source-specific-details', title: '确定需要登记后：创建过程总览',
      paragraphs: ['确认本次需要手动登记后，按下面的顺序完成配置。已有身份可直接进入它的接入指引；普通网关应用和 Scanner 按上面的对应路线继续。'],
      flow: [
        { label: '确认身份', value: '复用已有或手动登记' },
        { label: '填写表单', value: '基础信息 + 按需授权' },
        { label: '保存', value: '打开当前 Agent 指引' },
        { label: '签发凭证', value: '绑定当前 Agent' },
        { label: '接入运行端', value: '真实调用并核对记录', type: 'success' },
      ],
      link: { path: '/agents', label: '打开智能体列表' },
    },
    {
      id: 'agent-record', title: '1. 填写基本信息',
      paragraphs: ['进入“登记智能体”表单。Agent ID 和名称为必填；部门、负责人和描述用于管理归属，可按需填写。'],
      table: { columns: ['字段', '怎么填', '示例 / 含义'], rows: [
        ['Agent ID', '填写稳定且唯一的标识，运行端和凭证使用同一身份。', 'expense-assistant'],
        ['名称', '填写便于识别业务用途的展示名称。', '报销助手'],
        ['所属部门 / 负责人', '选择实际责任部门和负责人。', '用于归属管理，不代替运行凭证。'],
        ['状态', '准备接入时使用“启用”；暂存配置可选“草稿”。', '“禁用”用于停用身份；“启用”不代表已有进程运行。'],
        ['描述', '说明业务用途和实际运行位置。', '供财务团队使用，在业务服务器运行。'],
      ] },
    },
    {
      id: 'capability-selection', title: '2. 按用途选择模型、Skill 和 MCP',
      paragraphs: ['这三类能力可以分别配置或组合使用。只填本次需要的部分；保存身份后也可继续编辑。'],
      table: { columns: ['本次用途', '表单填写', '保存后还要做什么'], rows: [
        ['通过平台或外部网关调用模型', '选择模型来源和默认模型。', '授予 model:chat，并在运行端配置对应模型连接。'],
        ['让 Agent 使用受控 Skill', '在“Skill 授权”选择扫描批准的具体版本。', '在运行端安装同一版本，接入加载前校验。'],
        ['让 Agent 调用 MCP 工具', '在“允许访问的 MCP 网关”选择所需网关。', '为凭证授权网关子集，并配置 MCP 连接。'],
      ] },
      callout: { type: 'note', title: '只做 Skill 校验时怎么填？', body: '保留“内置模型网关”来源，默认模型留空，选择已批准 Skill；MCP 网关可留空。保存后进入 Agent Skill Verifier 指引。模型和 MCP 不是使用 Verifier 的前置条件。' },
    },
    {
      id: 'model-source', title: '3. 需要模型时，按来源完成选择',
      table: { columns: ['模型来源', '操作顺序', '完成条件'], rows: [
        ['内置模型网关', '从默认模型列表选择管理员已配置的模型。', '需要模型接入时选定模型；仅登记或只用 Skill / MCP 时可留空。'],
        ['外部 AI 网关', '选择网关 → 点击“准备并刷新模型” → 从返回目录选择默认模型 → 保存。', '选择外部来源后，必须准备模型目录并选定默认模型。'],
      ] },
      paragraphs: ['外部网关准备操作会先建立草稿和外部身份，以取得该身份可用的模型目录。若目录为空或准备失败，保留表单并检查网关配置和权限，成功后再选择模型。'],
      link: { path: '/docs/external-ai-gateway', label: '查看外部网关模型配置步骤' },
    },
    {
      id: 'skill-mcp-selection', title: '4. 需要 Skill 或 MCP 时，确认授权范围',
      steps: [
        { title: 'Skill：选定批准版本', body: '在“Skill 授权”核对下拉项中的名称和具体 Skill 标识。运行端应安装对应批准版本；表单中的选择只保存允许范围，不会自动安装文件。找不到目标时，先到 Skill 治理完成提交和审批。' },
        { title: 'MCP：选定已启用网关', body: '选择“允许访问的 MCP 网关”，使用“查看工具”核对工具及审批要求。需要新网关时先在 MCP 治理配置；从表单打开网关配置会使用新标签页并保留草稿。' },
        { title: '核对真正需要的权限', body: 'Agent 允许范围和运行凭证授权都要满足调用要求。后续凭证的 MCP 网关只能选择此处范围的子集；为 Agent 新增网关后，还需为相应凭证授权。' },
      ],
    },
    {
      id: 'creation-examples', title: '填写示例：按你的目标选一行',
      table: { columns: ['目标', '模型', 'Skill 授权', 'MCP 网关'], rows: [
        ['只接入 Agent Skill Verifier', '内置来源，默认模型留空。', '选择需要验证的批准版本。', '留空。'],
        ['只调用受控 MCP 工具', '内置来源，默认模型留空。', '本次不用 Skill 时留空。', '选择业务需要的网关。'],
        ['调用模型并使用 Skill', '选择内置模型，或完成外部网关模型准备。', '选择业务需要的批准版本。', '需要 MCP 工具时再选择。'],
      ] },
      paragraphs: ['例如创建“报销助手”：Agent ID 填 expense-assistant，状态选启用。如果本次只验证报销 Skill，就仅选择该 Skill；保存后为同一身份创建校验凭证，再到实际 Agent 中安装并配置 Verifier。'],
    },
    {
      id: 'credential-types', title: '5. 保存身份，再创建运行凭证',
      steps: [
        { title: '点击“保存并查看接入指引”', body: '有接入与运行页面权限时，保存后进入当前 Agent 的指引。仅能保存档案的账号可由有权限的人员继续接入。以后也可从列表或详情重新打开指引。' },
        { title: '在指引中选择实际用途', body: '只使用 Verifier 时，打开“接入与运行 → Agent Skill Verifier”并选择刚创建的身份；自研代码接入则选择相应能力。这里的选择用于生成步骤和建议权限。' },
        { title: '创建绑定当前 Agent 的运行凭证', body: '进入统一凭证中心，核对带入的 Agent、权限及模型 / 网关范围。只做 Verifier 校验时需要 runtime:verify-signature 和 runtime:can-load；模型、MCP 等权限按本次用途增加。' },
        { title: '保存一次性明文并返回指引', body: '将凭证交给对应运行环境，随后配置连接或安装校验组件。创建 Agent 时不用预先准备运行凭证。' },
      ],
      link: { path: '/docs/runtime-integration', label: '继续：配置运行端并验证接入' },
    },
    {
      id: 'status-and-binding', title: '6. 确认现在完成到了哪一步',
      table: { columns: ['看到的结果', '代表什么', '接下来'], rows: [
        ['列表出现“平台创建”记录', '身份及所选授权已保存。', '签发或核对绑定该 Agent 的运行凭证。'],
        ['详情显示关联运行凭证', '存在关联记录。', '核对有效期、状态和权限，并交给运行端配置。'],
        ['运行端请求成功并有对应审计', '本次能力调用已经接通。', '按业务场景检查拒绝路径，再投入使用。'],
      ] },
      callout: { type: 'note', title: '创建成功与接入成功是两个完成点', body: '创建完成后，Agent 程序仍需配置并发起真实调用。模型、Skill、MCP 各自核对对应记录；一个能力通过不代表其他能力已接通。' },
    },
    {
      id: 'next-runtime', title: '下一步：打开与你的用途对应的指引',
      table: { columns: ['本次用途', '继续阅读'], rows: [
        ['通过 Skill 指令使用校验脚本', { path: '/docs/runtime-integration#skill-verifier', label: 'Verifier 安装、配置与实际宿主验收' }],
        ['在自研 Agent 代码中接入校验', { path: '/docs/runtime-integration#integration-choice', label: 'Runtime API / SDK 接入' }],
        ['连接 Agent 的 MCP 工具', { path: '/docs/runtime-integration#agent-mcp-access', label: 'MCP 授权、连接与调用验证' }],
        ['管理电脑上的 Agent', { path: '/docs/client-management', label: '客户端发现与本机治理' }],
      ] },
    },
    {
      id: 'platform-created-detail', title: '创建后查看：平台配置',
      paragraphs: ['打开平台创建记录，核对 Agent ID、状态、责任归属、默认模型、Skill 授权、允许的 MCP 网关及关联运行凭证。修改授权后，继续检查凭证范围和实际调用结果。'],
      image: { name: 'agent-platform-detail', alt: '平台创建智能体详情', caption: '平台详情用于检查已保存的配置；接入结果以实际调用记录为准。' },
    },
    {
      id: 'client-discovered-detail', title: '已有客户端身份：查看本机信息',
      paragraphs: ['客户端发现项直接复用已有身份。详情显示所属客户端、Agent 类型与版本、安装和 Skill 目录及客户端上报的模型配置；本机治理在客户端管理中执行。'],
      image: { name: 'agent-client-detail', alt: '客户端发现智能体详情', caption: '客户端发现详情展示上报事实，治理操作由所属客户端执行。' },
    },
  ],
}

const en = {
  eyebrow: 'Operating guide',
  title: 'Agents: when to register, how to connect and what to fill in',
  summary: 'Decide whether you need an Agent identity and choose the integration for your scenario. If manual registration is needed, fill in the form, authorize resources and configure the runtime.',
  sections: [
    ...agentIntegrationChoices['en-US'],
    {
      id: 'source-specific-details', title: 'When registration is needed: creation overview',
      paragraphs: ['If manual registration is needed, follow the sequence below. Existing identities can open their integration guide directly; ordinary gateway apps and Scanner users can continue on the routes above.'],
      flow: [
        { label: 'Identity', value: 'Reuse or register' },
        { label: 'Form', value: 'Details and required access' },
        { label: 'Save', value: 'Open this Agent’s guide' },
        { label: 'Credential', value: 'Bind to this Agent' },
        { label: 'Runtime', value: 'Call and inspect records', type: 'success' },
      ],
      link: { path: '/agents', label: 'Open Agents' },
    },
    {
      id: 'agent-record', title: '1. Fill in basic information',
      paragraphs: ['Open Register Agent. Agent ID and name are required. Department, owner and description provide optional management context.'],
      table: { columns: ['Field', 'What to enter', 'Example / meaning'], rows: [
        ['Agent ID', 'Use a stable, unique identifier shared by the runtime and its bound credential.', 'expense-assistant'],
        ['Name', 'Use a display name that identifies its business purpose.', 'Expense assistant'],
        ['Department / Owner', 'Select the responsible department and person.', 'Records ownership; does not replace runtime credentials.'],
        ['Status', 'Use Active when ready to connect, or Draft while preparing configuration.', 'Disabled suspends the identity. Active does not indicate a running process.'],
        ['Description', 'Describe the purpose and actual runtime location.', 'Used by Finance on a business server.'],
      ] },
    },
    {
      id: 'capability-selection', title: '2. Choose model, Skill and MCP access by purpose',
      paragraphs: ['Configure these capabilities independently or combine them. Fill in only what this integration needs; you can edit the identity later.'],
      table: { columns: ['Purpose', 'Form selection', 'After saving'], rows: [
        ['Call models through the platform or an external gateway', 'Select the model source and default model.', 'Grant model:chat and configure the appropriate runtime connection.'],
        ['Use governed Skills', 'Select specific approved versions under Skill permissions.', 'Install the same versions and integrate pre-load verification.'],
        ['Call MCP tools', 'Select the allowed MCP gateways.', 'Grant a gateway subset to the credential and configure MCP connections.'],
      ] },
      callout: { type: 'note', title: 'Only need Skill verification?', body: 'Keep the internal model source and leave the default model empty. Select an approved Skill and leave MCP gateways empty. After saving, open the Agent Skill Verifier guide. Model and MCP configuration are optional for Verifier.' },
    },
    {
      id: 'model-source', title: '3. If using models, complete the source-specific setup',
      table: { columns: ['Source', 'Sequence', 'Completion condition'], rows: [
        ['Built-in model gateway', 'Choose a model already configured by an administrator.', 'Select a model when needed; leave it empty for identity-only, Skill-only or MCP-only setup.'],
        ['External AI gateway', 'Select gateway → Prepare and refresh models → Select a returned default model → Save.', 'The external source requires a prepared catalog and a selected default model.'],
      ] },
      paragraphs: ['Preparing external models first creates a draft and an external identity to obtain its available catalog. If preparation fails or returns no models, retain the form and check gateway configuration and permissions before selecting a model.'],
      link: { path: '/docs/external-ai-gateway', label: 'Read external gateway model setup' },
    },
    {
      id: 'skill-mcp-selection', title: '4. If using Skills or MCP, confirm resource access',
      steps: [
        { title: 'Skills: select approved versions', body: 'Check the name and specific Skill identifier in the selector. Install the corresponding approved version in the runtime. Selection saves permissions; it does not install files. Submit and approve a missing Skill through Skill governance first.' },
        { title: 'MCP: select enabled gateways', body: 'Choose allowed gateways and use View tools to inspect tools and approval requirements. Configure new gateways in MCP governance. Opening gateway configuration from the form uses a new tab and retains the draft.' },
        { title: 'Confirm the permissions actually needed', body: 'Both Agent access and credential grants must permit a call. Credential gateways must be a subset of the Agent’s allowed gateways. Adding a gateway to the Agent also requires granting it to the relevant credential.' },
      ],
    },
    {
      id: 'creation-examples', title: 'Examples: choose the row matching your goal',
      table: { columns: ['Goal', 'Model', 'Skill permissions', 'MCP gateways'], rows: [
        ['Agent Skill Verifier only', 'Internal source, no default model.', 'Select the approved version to verify.', 'Leave empty.'],
        ['Governed MCP tools only', 'Internal source, no default model.', 'Leave empty when no Skill is needed.', 'Select the required gateways.'],
        ['Model calls and Skills', 'Choose an internal model or prepare an external gateway model.', 'Select the required approved versions.', 'Select gateways if MCP tools are needed.'],
      ] },
      paragraphs: ['For example, register Expense assistant with Agent ID expense-assistant and Active status. If this integration only verifies an expense Skill, select that Skill alone. Save, issue a verification credential bound to the same identity, then install and configure Verifier in the actual Agent runtime.'],
    },
    {
      id: 'credential-types', title: '5. Save the identity, then issue a runtime credential',
      steps: [
        { title: 'Choose Save and view integration guide', body: 'With access to Integration & runtime, saving opens this Agent’s guide. If your account can only save the record, an authorized operator can continue integration. Reopen the guide later from the list or details.' },
        { title: 'Select the actual integration purpose', body: 'For Verifier only, open Integration & runtime → Agent Skill Verifier and select the identity you just created. For custom code, select the relevant capabilities. These choices generate steps and suggested permissions.' },
        { title: 'Create a credential bound to this Agent', body: 'In Credential Center, confirm the preselected Agent, scopes and model / gateway limits. Verifier requires runtime:verify-signature and runtime:can-load. Add model, MCP or other scopes only for the intended integration.' },
        { title: 'Save the one-time secret and return', body: 'Deliver the credential to its runtime, then configure connections or verification components. A runtime credential is created after the Agent identity.' },
      ],
      link: { path: '/docs/runtime-integration', label: 'Continue: configure and verify the runtime' },
    },
    {
      id: 'status-and-binding', title: '6. Check which completion point you have reached',
      table: { columns: ['Observed result', 'Meaning', 'Next action'], rows: [
        ['A Platform-created record appears', 'Identity and selected permissions are saved.', 'Issue or inspect a runtime credential bound to this Agent.'],
        ['Details show a linked runtime credential', 'A credential record is linked.', 'Check expiry, status and scopes, then configure the runtime.'],
        ['A runtime call succeeds with matching audit', 'This capability has connected for this invocation.', 'Test denial paths for the business scenario before use.'],
      ] },
      callout: { type: 'note', title: 'Registration and integration are separate completion points', body: 'After registration, configure the Agent program and make real calls. Check model, Skill and MCP records separately; success for one capability does not establish the others.' },
    },
    {
      id: 'next-runtime', title: 'Next: open the guide for your integration',
      table: { columns: ['Purpose', 'Continue with'], rows: [
        ['Run a verification script through Skill instructions', { path: '/docs/runtime-integration#skill-verifier', label: 'Verifier installation, configuration and host acceptance' }],
        ['Integrate checks in custom Agent code', { path: '/docs/runtime-integration#integration-choice', label: 'Runtime API / SDK integration' }],
        ['Connect this Agent to MCP tools', { path: '/docs/runtime-integration#agent-mcp-access', label: 'MCP authorization, connection and verification' }],
        ['Manage Agents on a computer', { path: '/docs/client-management', label: 'Client discovery and local governance' }],
      ] },
    },
    {
      id: 'platform-created-detail', title: 'After creation: review platform configuration',
      paragraphs: ['Inspect Agent ID, status, ownership, default model, Skill permissions, allowed MCP gateways and linked runtime credentials. After changing access, check credential grants and actual calls.'],
      image: { name: 'agent-platform-detail', alt: 'Platform-created Agent details', caption: 'Platform details show saved configuration. Actual call records establish integration results.' },
    },
    {
      id: 'client-discovered-detail', title: 'Existing Client identity: review local information',
      paragraphs: ['Reuse a Client-discovered identity. Details show the owning Client, Agent type and version, install and Skill directories, and reported model configuration. Perform local governance in Clients.'],
      image: { name: 'agent-client-detail', alt: 'Client-discovered Agent details', caption: 'Client-discovered details show reported facts; the owning Client performs governance operations.' },
    },
  ],
}

export const agentRegistrationGuides = { 'zh-CN': zh, 'en-US': en }
