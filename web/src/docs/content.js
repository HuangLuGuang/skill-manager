const zh = {
  groups: [
    { title: '开始使用', items: [
      { slug: '', title: '文档首页', summary: '认识平台并选择适合自己的使用路径' },
      { slug: 'quick-start', title: '快速上手', summary: '走通第一条 Skill 治理链路' },
    ] },
    { title: '功能指南', items: [
      { slug: 'skill-governance', title: 'Skill 治理', summary: '提交、检测、审核与版本管理' },
      { slug: 'agent-management', title: '智能体管理', summary: 'Agent 档案、能力绑定与凭证选择' },
      { slug: 'runtime-integration', title: 'Agent 运行校验接入', summary: 'Skill Verifier、事件 Hook 与结果判断' },
      { slug: 'client-management', title: '客户端管理', summary: '本地 Agent 发现、Skill 下发与持续巡检' },
      { slug: 'model-gateway', title: '模型网关', summary: '模型接入、隐私防护与 Token 压缩' },
      { slug: 'mcp-governance', title: 'MCP 治理', summary: '服务、网关、审批与调用审计' },
      { slug: 'system-management', title: '系统管理', summary: '用户、权限与系统状态' },
    ] },
    { title: '部署与运维', items: [
      { slug: 'docker-deployment', title: 'Docker 部署', summary: '在线或离线方式启动同一套 Compose 服务' },
      { slug: 'docker-operations', title: 'Docker 运维', summary: '状态、日志、备份、升级与排障' },
    ] },
    { title: '帮助', items: [
      { slug: 'faq', title: '常见问题', summary: '按现象定位常见问题' },
    ] },
  ],
  articles: {
    '': {
      eyebrow: 'Agent Manager 文档',
      title: '让 Agent 能力、模型调用与本地运行可控',
      summary: '从 Skill 准入和客户端分发，到模型隐私防护、Token 压缩与 MCP Tool 审批，平台把关键控制和审计集中到一处。',
      home: true,
      roles: [
        { title: '平台管理员', text: '先完成 Docker 部署、系统检查、用户与凭证配置。', slug: 'docker-deployment' },
        { title: '安全审核人员', text: '从 Skill 报告、审核队列和治理策略开始。', slug: 'skill-governance' },
        { title: 'Agent 与客户端运维', text: '登记 Agent、选择运行校验方式，再治理本地 Skill。', slug: 'agent-management' },
        { title: '模型网关运营人员', text: '配置模型、隐私策略、Prompt 防护和 Token 压缩。', slug: 'model-gateway' },
      ],
      sections: [
        {
          id: 'what-it-does',
          title: '这个系统解决什么问题',
          paragraphs: ['Agent Manager 不是单一的 Skill 仓库。它同时治理 Agent 使用的 Skill、本地客户端上的能力分发、进入模型的请求，以及对外开放的 MCP Tool。'],
          bullets: ['Skill 在使用前完成检测、策略判定、审核和签名，内容变化后重新验证。', 'Agent 通过绑定和专用凭证获得最小权限；客户端负责发现、下发、恢复或隔离本地 Skill。', '模型网关统一执行访问控制、Prompt 防护、隐私替换、可选 Token 压缩和用量分析。', 'MCP 网关只发布选定 Tool，并对高风险调用执行限时审批和审计。'],
          diagram: 'platform',
        },
        {
          id: 'capability-map',
          title: '按目标选择功能',
          table: {
            columns: ['你想完成的事情', '使用模块'],
            rows: [
              ['提交并检测一个 Skill', { label: 'Skill 治理 / 提交 Skill', path: '/docs/skill-governance' }],
              ['审核可疑 Skill', { label: 'Skill 治理 / Skill 审核', path: '/docs/skill-governance' }],
              ['让 Agent 只能使用指定 Skill', { label: '智能体管理 / 能力绑定与凭证', path: '/docs/agent-management' }],
              ['把验签和 Tool 检查接入 Agent', { label: 'Agent 运行校验接入', path: '/docs/runtime-integration' }],
              ['发现本机 Agent 和 Skill 目录', { label: '客户端管理 / Agent 发现', path: '/docs/client-management' }],
              ['向本地 Agent 下发、恢复或移除 Skill', { label: '客户端管理 / 管理台操作', path: '/docs/client-management' }],
              ['保护发送给模型的隐私数据', { label: '模型网关 / 隐私策略', path: '/docs/model-gateway' }],
              ['压缩模型上下文并查看节省效果', { label: '模型网关 / Token 压缩', path: '/docs/model-gateway' }],
              ['分析不同用户的 Token 使用', { label: '模型网关 / 用户 Token 分析', path: '/docs/model-gateway' }],
              ['查看模型调用声明的 Skill 是否异常', { label: '模型网关 / Skill 告警', path: '/docs/model-gateway' }],
              ['统一发布并审计 MCP Tool', { label: 'MCP 治理 / 服务与网关', path: '/docs/mcp-governance' }],
            ],
          },
        },
      ],
    },
    'quick-start': {
      eyebrow: '开始使用',
      title: '完成第一次 Skill 治理',
      summary: '使用一个不含真实密钥和隐私数据的测试 ZIP，走通提交、检测、审核、Agent 授权和运行校验。',
      sections: [
        {
          id: 'check-system',
          title: '1. 检查平台状态',
          paragraphs: ['先打开平台总览和系统总览，确认核心服务可用。LLM 与 Sandbox 是否启用取决于管理员配置，未配置的检测项会在提交页禁用。'],
          image: { name: 'dashboard', alt: '平台总览页面', caption: '平台总览用于确认待处理 Skill、风险分布和最近事件。' },
          link: { path: '/dashboard', label: '打开平台总览' },
        },
        {
          id: 'submit-zip',
          title: '2. 上传 ZIP 并选择 Skill',
          paragraphs: ['当前管理台提交入口支持 ZIP 上传和 Scanner 接入。上传 ZIP 后，系统先解析其中可导入的 Skill，再由你选择需要提交的条目。'],
          steps: [
            { title: '选择 ZIP', body: 'ZIP 中的 Skill 目录必须包含 SKILL.md。' },
            { title: '解析内容', body: '点击解析按钮，确认系统识别出的目录和 Skill。' },
            { title: '选择检测项并提交', body: '不可用的检测项会保持禁用；不要为了完成示例强行开启未配置服务。', expected: '提交结果先显示 PENDING，后台继续执行检测。' },
          ],
          image: { name: 'submit-skill', alt: '提交 Skill 页面', caption: '上传 ZIP、解析内容并选择需要检测的 Skill。' },
          link: { path: '/submit', label: '打开提交 Skill' },
        },
        {
          id: 'review-result',
          title: '3. 查看报告并处置',
          paragraphs: ['检测完成后，在 Skill 详情中查看最终风险、证据、不同分析器结论、文件内容和版本记录。VETTED 需要人工审核；APPROVED 已成为可信版本；REJECTED 不进入审核队列。'],
          image: { name: 'skill-list', alt: 'Skill 列表页面', caption: '列表展示最新内容版本、可信版本、状态和风险。' },
          link: { path: '/skills', label: '打开 Skill 列表' },
        },
        {
          id: 'verify-runtime',
          title: '4. 接入 Agent 并验证本地内容',
          paragraphs: ['创建 Agent、绑定允许使用的 Skill，并签发绑定该 Agent 的运行凭证。随后下载 Skill Verifier，在 Agent 使用 Skill 前执行签名和加载许可检查。'],
          callout: { type: 'note', title: '验证顺序', body: '先验证本地内容摘要，再检查当前 Agent 的加载许可；如果接入了事件 Hook，还应在 Tool 执行前检查 Tool 许可。' },
          image: { name: 'runtime', alt: '接入与运行页面', caption: '运行审计展示验签、加载允许或阻断、篡改和 Tool 调用事件。' },
          link: { path: '/runtime', label: '打开接入与运行' },
        },
        {
          id: 'next-paths',
          title: '5. 根据目标继续配置',
          paragraphs: ['本页只走通第一条 Skill 治理链路。接下来先选择运行校验方式，再按实际调用方式配置客户端、模型网关或 MCP 网关。'],
          table: {
            columns: ['下一步目标', '继续阅读'],
            rows: [
              ['把验证嵌入 Agent 的加载与 Tool 调用流程', { label: 'Agent 运行校验接入', path: '/docs/runtime-integration' }],
              ['集中治理多台机器上的本地 Skill', { label: '客户端管理', path: '/docs/client-management' }],
              ['保护模型请求并统计 Token 节省', { label: '模型网关', path: '/docs/model-gateway' }],
              ['受控发布 MCP Tool', { label: 'MCP 治理', path: '/docs/mcp-governance' }],
            ],
          },
        },
      ],
    },
    'skill-governance': {
      eyebrow: '功能指南',
      title: 'Skill 治理',
      summary: '管理 Skill 从提交、检测、策略判定、人工审核到可信版本维护的完整过程。',
      sections: [
        {
          id: 'submission',
          title: '提交方式',
          table: {
            columns: ['方式', '适用场景', '当前状态'],
            rows: [
              ['ZIP 上传', '管理台手动提交一个或多个 Skill', '可用'],
              ['Scanner 接入', '客户机器、服务器或 CI 批量发现和上传本地 Skill', '可用'],
            ],
          },
          callout: { type: 'note', title: '选择合适的入口', body: '少量人工提交使用 ZIP；多台客户机器、服务器或 CI 的持续发现使用 Scanner 接入。' },
        },
        {
          id: 'pipeline',
          title: '检测与判定',
          paragraphs: ['提交成功后先写入 PENDING，后台再执行已启用的分析器。最终风险由策略汇总决定，不能用单个 Sandbox 或 LLM 结果代替最终结论。'],
          bullets: ['规则和静态分析检查文件、权限与危险模式。', 'Sandbox观察受限环境中的实际行为，但不保证覆盖所有分支。', 'LLM在配置可用时综合内容和分析器证据。', '策略把结果归入自动批准、人工审核或拒绝。'],
          diagram: 'governance',
        },
        {
          id: 'states',
          title: '状态与下一步',
          table: {
            columns: ['状态', '含义', '下一步'],
            rows: [
              ['PENDING', '后台检测中', '等待状态更新或检查检测记录'],
              ['VETTED', '检测完成，等待人工审核', '在审核队列批准或拒绝'],
              ['APPROVED', '可信版本已批准', '绑定 Agent、安装或执行运行校验'],
              ['REJECTED', '已拒绝', '修复内容后提交新版本'],
              ['DEPLOYED', '已进入受管部署状态', '持续检查完整性和审计'],
            ],
          },
        },
        {
          id: 'versions',
          title: '报告与版本',
          bullets: ['查看最终风险、功能概括、风险证据、攻击链和安全框架映射。', '查看 Scanner、规则、LLM和Sandbox的独立结果及原始报告。', '查看服务端保存的文件内容，避免只依赖摘要。', '比较同名 Skill 的两个内容版本。', '“重新检测”生成新的检测记录，不创建内容版本；内容改变应提交新版本。'],
          link: { path: '/skills', label: '打开 Skill 列表' },
        },
      ],
    },
    'mcp-governance': {
      eyebrow: '功能指南',
      title: 'MCP 治理',
      summary: '把远程 MCP Server 的 Tool 组合成受控网关，并对高风险调用实施限时审批和审计。',
      sections: [
        {
          id: 'flow',
          title: '推荐配置顺序',
          steps: [
            { title: '登记 MCP 服务', body: '填写 Streamable HTTP Endpoint，连接并保存 tools/list Schema 快照。' },
            { title: '创建 MCP 网关', body: '从一个或多个服务选择需要对外发布的 Tool。' },
            { title: '创建网关凭证', body: '限制允许访问的网关、IP、有效期、请求大小和并发。' },
            { title: '使用 MCP 调试验证', body: '先完成工具发现，再使用真实网关凭证执行调用。' },
            { title: '处理高风险审批', body: '首次高风险调用返回申请 ID，管理员审核脱敏参数并签发限时授权。' },
          ],
        },
        {
          id: 'boundaries',
          title: '需要理解的边界',
          bullets: ['MCP服务保存上游连接；MCP网关决定向调用方暴露哪些Tool。', 'Schema变化后暂停暴露，重新保存网关后才批准新Schema。', '审批按凭证、网关、Tool和Schema生效，不把参数当作永久签名。', 'MCP凭证不代表Agent身份；Agent同时使用MCP时需要各自的凭证。'],
          link: { path: '/mcp-governance/servers', label: '打开 MCP 服务' },
        },
        {
          id: 'audit',
          title: '审批与调用审计',
          paragraphs: ['审批页面默认展示脱敏参数。查看原始参数会写入安全审计。批准后，原凭证可以在授权有效期内使用同一Tool和Schema；调用审计用于追踪来源、结果、耗时和错误。'],
          link: { path: '/mcp-governance/approvals', label: '打开调用审批' },
        },
      ],
    },
    'agent-management': {
      eyebrow: '功能指南',
      title: '智能体管理',
      summary: '以 Agent 为主档案绑定部门、模型和允许使用的 Skill，再签发最小权限凭证。',
      sections: [
        {
          id: 'agent-record',
          title: '先登记 Agent，再创建凭证',
          steps: [
            { title: '创建 Agent', body: '设置名称、所属部门和启用状态。' },
            { title: '绑定能力', body: '选择默认模型、Prompt和允许使用的 Skill。' },
            { title: '创建运行凭证', body: '在统一凭证中心选择 Agent 运行凭证并绑定目标 Agent。' },
            { title: '交给运行环境', body: '只把一次性显示的凭证明文交给对应 Agent，不能使用管理员登录 Token。' },
          ],
          link: { path: '/agents', label: '打开智能体列表' },
        },
        {
          id: 'credential-types',
          title: '按调用主体选择凭证',
          table: {
            columns: ['凭证', '用途'],
            rows: [
              ['Agent 运行凭证', '验签、加载许可和 Tool 调用检查'],
              ['Scanner 接入凭证', '客户侧提交和读取自己的扫描结果'],
              ['Client 接入凭证', '桌面客户端注册、心跳、任务和事件上报'],
              ['模型调用凭证', '普通应用调用模型网关'],
              ['MCP 网关凭证', 'MCP Client访问授权网关和Tool'],
            ],
          },
          callout: { type: 'warning', title: '凭证明文只展示一次', body: '丢失后不能再次查看原文，应吊销并重新创建。不要在截图、文档或代码仓库中保存真实凭证。' },
        },
        {
          id: 'next-runtime',
          title: '下一步：选择运行校验方式',
          paragraphs: ['完成Agent档案、Skill绑定和运行凭证后，再根据Agent是否支持Skill指令、生命周期事件或后台客户端，选择Verifier、Hook或Agent Manager Client。'],
          link: { path: '/docs/runtime-integration', label: '阅读 Agent 运行校验接入' },
        },
      ],
    },
    'runtime-integration': {
      eyebrow: '功能指南',
      title: 'Agent 运行校验接入',
      summary: '选择 Skill Verifier、事件 Hook 或客户端，把内容完整性、加载许可和 Tool 许可检查放到正确的执行点。',
      sections: [
        {
          id: 'integration-choice',
          title: '先选择接入方式',
          paragraphs: ['三种方式解决的问题不同。先按触发点和治理范围选择，再继续阅读对应步骤。'],
          table: {
            columns: ['方式', '触发点', '适用场景'],
            rows: [
              ['Skill Verifier', 'Agent按指令在读取或加载前执行', '快速接入支持本地Skill指令的Agent'],
              ['事件Hook', 'Agent生命周期或Tool调用事件自动触发', '需要稳定执行加载前和Tool前校验的运行环境'],
              ['Agent Manager Client', '后台服务持续巡检并接收平台任务', '集中治理多台主机上的本地Agent和Skill目录'],
            ],
          },
          link: { path: '/docs/client-management', label: '阅读客户端管理' },
        },
        {
          id: 'verifier-setup',
          title: '接入 Skill Verifier',
          paragraphs: ['Skill Verifier适合能够在读取或加载Skill前稳定执行验证指令的Agent。`verify`命令计算本地Skill的无密钥内容摘要，先校验批准版本签名，再检查该Agent是否可以加载。'],
          steps: [
            { title: '准备 Agent 和授权', body: '在智能体列表创建Agent并绑定允许使用的Skill；在统一凭证中心签发绑定该Agent的运行凭证，至少授予runtime:verify-signature和runtime:can-load。' },
            { title: '下载并安装 Verifier', body: '在“接入与运行”下载ZIP，解压到Agent的Skill目录，例如~/.codex/skills或~/.claude/skills。' },
            { title: '配置运行环境', body: '平台地址、Agent运行凭证和Agent ID必须对应同一个已登记Agent。不要使用管理员登录Token，也不要把服务端签名私钥复制到Agent。', code: 'export AGENT_MANAGER_VERIFIER_BASE_URL="https://agent-manager.example.com"\nexport AGENT_MANAGER_AGENT_RUNTIME_TOKEN="amat_xxx"\nexport AGENT_ID="your-agent-id"' },
            { title: '在使用前执行验证', body: '--path必须指向包含SKILL.md的单个Skill目录，优先使用绝对路径。只有退出码为0才继续读取、加载或执行该Skill。', code: 'python ~/.codex/skills/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \\\n  --path /absolute/path/to/skill', expected: '输出“验证通过”，并在运行审计中出现验签和加载检查记录。' },
          ],
          callout: { type: 'warning', title: '验证凭证与扫描凭证分开', body: 'verify只使用Agent运行凭证。只有执行submit或status时，才为对应命令配置独立的Scanner接入凭证。' },
          link: { path: '/runtime', label: '打开接入与运行' },
        },
        {
          id: 'verifier-result',
          title: '怎样判断 Verifier 结果',
          table: {
            columns: ['检查', '通过条件', '失败时处理'],
            rows: [
              ['本地内容摘要', '与平台批准版本一致', '使用批准版本，或将变更内容重新提交检测'],
              ['Skill 状态', 'APPROVED或DEPLOYED', '等待检测与审核完成'],
              ['Agent 授权', '运行凭证绑定的Agent已获该Skill授权', '在智能体列表补充绑定，或换用正确凭证'],
              ['命令退出码', '0', '保留原始原因并停止使用该Skill'],
            ],
          },
          bullets: ['同名不代表内容一致；本地目录可写时必须传实际Skill路径完成摘要校验。', 'Skill内容发生变化后应重新执行verify，不能复用旧的通过结论。', 'Tool许可不由verify命令代替，应由Hook或运行时适配器在每次Tool执行前调用check-tool。'],
        },
        {
          id: 'hook-integration',
          title: '接入事件 Hook',
          paragraphs: ['Hook适合能在明确事件点运行脚本的Agent：加载前执行签名与加载许可检查，Tool执行前调用check-tool。仓库提供Claude Code / Trae和OpenClaw示例，接入时必须使用真实事件验证Skill名称、目录和Agent ID映射。'],
          steps: [
            { title: 'Claude Code或Trae：配置PreToolUse', body: '安装项目SDK，设置AGENT_MANAGER_BASE_URL、AGENT_MANAGER_API_TOKEN和AGENT_ID；其中API_TOKEN的值应是绑定该Agent的运行凭证。Hook命令使用agent_guard_hook.py的绝对路径。', code: '{\n  "hooks": {\n    "PreToolUse": [{\n      "matcher": "",\n      "hooks": [{\n        "type": "command",\n        "command": "python3 /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py"\n      }]\n    }]\n  }\n}' },
            { title: '验证PreToolUse链路', body: '调用一个已授权且内容一致的Skill应返回退出码0；篡改内容、撤销Agent授权或使用错误凭证后应返回退出码2，并在stderr显示原因。日志位于~/.agent-manager/logs/agent_guard_hook.log。' },
            { title: 'OpenClaw：分开接两个事件点', body: 'agent:bootstrap内部Hook用于枚举可见Skill并执行verify-skill-signature和can-load；before_tool_call需要接入OpenClaw插件工程，在Tool执行前调用check-tool。必须把事件中的会话身份稳定映射到平台登记的Agent ID。' },
            { title: '上线前做故障演练', body: '至少验证平台不可达、凭证过期、Skill目录找不到、内容被修改和Tool未授权五类场景，并同时检查Agent侧结果、Hook日志和平台运行审计。' },
          ],
          callout: { type: 'warning', title: '先验证事件字段，再推广配置', body: 'Claude Code / Trae示例对可识别Skill的API或网络错误返回阻止；无法解析的输入或非Skill调用会直接放行。OpenClaw事件结构和Agent身份映射应在目标版本中实测后再批量部署。' },
        },
      ],
    },
    'client-management': {
      eyebrow: '功能指南',
      title: '客户端管理',
      summary: '桌面客户端负责本机 Agent 与 Skill 的发现、接管和持续治理；管理台负责集中查看客户端、配置策略并远程下发任务。',
      sections: [
        {
          id: 'desktop-and-console',
          title: '先区分桌面客户端和管理台',
          paragraphs: ['Agent Manager Client安装在需要治理Skill的用户主机或服务器上，通过客户端接入凭证注册、心跳并上报本地Agent、Skill清单和安全事件。它不是管理台的缩小版，两端承担的职责不同。'],
          table: {
            columns: ['使用位置', '主要职责'],
            rows: [
              ['桌面客户端', '发现本机Agent和Skill目录，选择接管范围，安装可信版本，持续巡检并执行恢复、隔离或只审计。'],
              ['平台管理台', '集中查看多台客户端，配置治理方式和处置策略，绑定平台Agent，远程下发安装、修复、移除和策略同步任务。'],
            ],
          },
          image: { name: 'client-app-overview', alt: 'Agent Manager桌面客户端概览', caption: '桌面客户端概览集中显示接入进度、本机 Agent、受管 Skill、平台检测能力和后台巡检状态。截图使用示例数据。' },
        },
        {
          id: 'install-register',
          title: '安装与接入顺序',
          steps: [
            { title: '下载对应平台安装包', body: '管理台当前提供macOS Apple Silicon、macOS Intel、Windows x64和Linux x64安装包，具体以当前发布列表为准。' },
            { title: '创建客户端接入凭证', body: '在统一凭证中心选择客户端类型，保留默认client:*最小权限；凭证明文只展示一次。' },
            { title: '连接平台并发现 Agent', body: '在客户端填写平台地址与凭证，确认发现的Agent、共用目录和Skill路径。' },
            { title: '确认治理范围并启用后台巡检', body: '先生成接管预览，确认需要继续启用和停用待处理的Skill，再安装后台服务。', expected: '关闭客户端窗口后，已经安装的后台服务仍会持续同步任务、巡检文件和上报事件。' },
          ],
        },
        {
          id: 'client-pages',
          title: '桌面客户端有哪些页面',
          table: {
            columns: ['页面或入口', '可以完成的事情'],
            rows: [
              ['客户端概览', '查看平台连接、接入进度、本机Agent、受管Skill、待办事项和平台检测能力。'],
              ['Agent发现', '发现内置Agent、共用Skill目录和自定义Agent，查看路径并选择纳入治理的Skill。'],
              ['Skill治理', '预览接管结果，从平台安装批准版本，把未知或未批准内容安全移入待处理区并提交检测。'],
              ['运行状态', '立即巡检，暂停或恢复持续治理，查看隔离区，并使用接管前备份进行高级恢复。'],
              ['执行记录', '区分本地巡检与处置记录，以及平台下发的安装、修复、移除和策略任务。'],
              ['安全通知', '查看自动恢复、隔离阻断和只审计提醒，并按未读或严重程度筛选。'],
              ['设置', '切换语言和默认页面，配置系统通知、后台启动、更新通道，并导出不含凭证明文的诊断报告。'],
            ],
          },
        },
        {
          id: 'discover-govern',
          title: '发现并接管本地 Skill',
          paragraphs: ['客户端默认识别Claude Code、Codex、Gemini CLI、OpenCode、OpenClaw、Hermes、TRAE、Cursor等Agent及共用Skill目录；未内置的工具可以添加为自定义Agent。'],
          bullets: ['展开Agent后检查实际扫描目录、Skill名称和校验状态，再勾选要纳入治理的Skill。', '接管预览会区分已可信、可以接管和需要停用待处理的内容；执行前需要明确确认。', '停用不是删除：内容从Agent入口移出并安全保留，可以提交平台检测。', '从平台安装时选择已批准版本和一个或多个目标Agent，客户端会验证发布签名和文件Hash。'],
          image: { name: 'client-app-discovery', alt: '桌面客户端Agent发现页面', caption: 'Agent发现页面按本地Agent展示Skill根目录、发现结果和平台状态。截图使用示例路径和数据。' },
          callout: { type: 'note', title: '共用目录的识别边界', body: '共用Skills目录可能被多个Agent读取，客户端只能治理该目录的状态和内容完整性，不能仅凭目录判断实际调用方。' },
        },
        {
          id: 'governance-modes',
          title: '治理方式与处置策略',
          table: {
            columns: ['配置', '实际作用'],
            rows: [
              ['客户端安全治理', '本地Skill只要已在平台注册为可信版本且签名一致即可使用，不要求绑定平台Agent。'],
              ['Agent强授权', '本地Agent必须绑定平台Agent，且只能安装该Agent获授权的Skill。'],
              ['只审计', '发现异常后记录并上报，不自动改动本地内容。'],
              ['自动恢复', '发现受管Skill异常时恢复平台批准版本。'],
              ['隔离阻断', '把异常内容移入隔离区，并从Agent的Skill入口移除。'],
            ],
          },
          callout: { type: 'warning', title: '先确认影响范围', body: '自动恢复和隔离阻断会修改本地Skill目录。正式启用前应先在只审计模式观察路径识别和事件结果。' },
        },
        {
          id: 'continuous-governance',
          title: '持续巡检、隔离与恢复',
          paragraphs: ['后台服务按周期同步平台策略和任务，并检查受管Skill是否被修改、撤销或替换。平台暂时不可达时，客户端使用最近一次成功同步的策略继续检查，并在恢复连接后补报事件。'],
          bullets: ['“立即执行巡检”用于主动完成一次全量检查；暂停持续治理不会删除受管内容。', '隔离区保留异常副本和处置原因，不会直接把未确认内容恢复到Agent入口。', '恢复可信内容时优先从平台选择批准版本；接管前备份只用于明确的紧急回退。', '执行记录和安全通知共同提供本地巡检、自动处置及平台任务的证据。'],
          image: { name: 'client-app-status', alt: '桌面客户端运行状态页面', caption: '运行状态页面展示后台巡检、受管与隔离数量、待补报事件以及隔离项的后续操作。截图使用示例数据。' },
        },
        {
          id: 'console-management',
          title: '管理台如何集中管理客户端',
          paragraphs: ['管理台客户端列表用于查看所有受管主机的在线状态、版本、Agent与Skill数量、安全事件和最后心跳；客户端详情再展开治理方式、本机Agent、任务与事件。'],
          image: { name: 'client-list', alt: '管理台客户端列表', caption: '管理台列表用于跨主机查看客户端状态和治理规模。示例数据以实际环境为准。' },
          bullets: ['客户端详情可以切换客户端安全治理或Agent强授权，并配置只审计、自动恢复或隔离阻断。', '按本机Agent选择平台批准Skill，可以远程下发、修复或移除。', '失败或取消的客户端任务可以重试；本地巡检和处置结果进入事件及统一审计。'],
          callout: { type: 'note', title: '任务的具体用途', body: '客户端任务用于安装、恢复、移除Skill和同步策略。执行后应在客户端详情中核对目标Agent、Skill、任务状态和最新事件。' },
          link: { path: '/clients', label: '打开客户端管理' },
        },
        {
          id: 'console-client-detail',
          title: '从客户端详情核对任务和事件',
          paragraphs: ['远程操作后，在同一详情抽屉中检查目标Agent、Skill、任务状态和最近事件，避免只根据按钮提示判断操作是否真正完成。'],
          image: { name: 'client-detail', alt: '管理台客户端详情页面', caption: '客户端详情集中展示治理方式、处置策略、本机Agent、最近任务与安全事件。' },
          link: { path: '/clients', label: '查看客户端详情' },
        },
      ],
    },
    'model-gateway': {
      eyebrow: '功能指南',
      title: '模型网关',
      summary: '统一代理模型请求，集中执行访问控制、Prompt防护、隐私替换、可选上下文压缩、用量分析和调用审计。',
      sections: [
        {
          id: 'feature-map',
          title: '页面与能力对应关系',
          table: {
            columns: ['页面', '解决的问题'],
            rows: [
              ['供应商管理 / 模型管理', '配置上游端点、密钥、模型名称、上下文窗口和输出限制。'],
              ['组策略绑定 / 隐私策略', '把用户组、模型范围、PII替换和Prompt防护规则绑定起来。'],
              ['Prompt防护测试', '在不依赖上游模型回复的情况下验证注入、提示泄露和凭据外传规则。'],
              ['Skill告警', '核对模型请求声明的Skill与平台登记、状态和Agent授权是否一致。'],
              ['隐私审计 / 隐私链路追踪', '查看请求结果及原始、替换、压缩、上游和还原阶段。'],
              ['Token压缩统计 / 用户Token分析', '查看请求量、Token消耗、压缩节省、耗时和用户用量。'],
            ],
          },
        },
        {
          id: 'setup-flow',
          title: '配置顺序',
          steps: [
            { title: '添加供应商', body: '配置OpenAI-compatible端点、API格式及供应商密钥；需要时在供应商级启用压缩。' },
            { title: '登记模型', body: '设置模型名称、上下文窗口、最大输出和启用状态。' },
            { title: '配置用户组和隐私策略', body: '决定PII实体类型、Prompt防护和会话映射策略。' },
            { title: '签发模型调用凭证', body: '限制允许模型、有效期、请求大小和并发；也可以只为指定凭证启用压缩。' },
            { title: '发起调用并查看链路', body: '通过OpenAI或Anthropic兼容入口调用，再在隐私链路追踪中核对处理结果。' },
          ],
          link: { path: '/model-gateway/providers', label: '打开供应商管理' },
        },
        {
          id: 'pipeline',
          title: '一次请求经过什么',
          bullets: ['校验凭证状态、模型范围、请求大小和并发。', '在对应策略启用时检测提示词注入、系统提示泄露和凭据外传风险。', '在匹配隐私策略时识别PII并替换为会话内伪匿名Token。', '供应商或调用凭证启用压缩时，在上游调用前压缩上下文。', '还原模型响应，并写入审计、用量和链路追踪。'],
        },
        {
          id: 'token-compression',
          title: 'Token 压缩与用量分析',
          paragraphs: ['压缩可以在供应商或模型调用凭证上启用，并选择auto、conservative或aggressive级别。平台在调用上游前处理messages，并记录压缩前后Token、节省量、压缩比例和耗时。'],
          bullets: ['Token压缩统计按时间和模型展示请求量、输入/输出Token、节省量、平均响应时间、模型耗时和平台耗时。', '用户Token分析用于查看不同用户的调用量和Token消耗。', '响应头和链路追踪可用于确认本次请求是已压缩、启用但未产生变换，还是未启用。'],
          callout: { type: 'note', title: '启用不等于每次都会节省', body: '短上下文可能无需压缩；压缩组件不可用或处理失败时会降级使用原始messages，不能把“已启用”直接当作“已节省”。' },
          image: { name: 'token-compression', alt: 'Token压缩统计页面', caption: '统计页同时展示Token用量、压缩请求、节省效果及平台和模型耗时。示例数据以实际环境为准。' },
          link: { path: '/model-gateway/stats', label: '打开 Token 压缩统计' },
        },
        {
          id: 'skill-alerts',
          title: '模型请求中的 Skill 告警',
          paragraphs: ['当调用方在模型请求中声明Skill时，平台会对照Skill登记信息、可加载状态和Agent授权，汇总缺失、未知、ID或名称不一致、不可加载和未授权等异常。'],
          callout: { type: 'warning', title: '当前是审计告警能力', body: '该功能当前不阻断模型调用。调用方声明的Skill元数据也不等于本地文件签名或内容已经验证；需要内容完整性时仍应使用Skill Verifier或客户端。' },
          link: { path: '/model-gateway/skill-alerts', label: '打开 Skill 告警' },
        },
        {
          id: 'privacy',
          title: '隐私链路和访问边界',
          paragraphs: ['链路追踪可以展示原始请求、脱敏请求、压缩请求、上游响应和最终还原结果。原始阶段可能包含PII，只应开放给管理员、超级管理员或隐私审计角色。'],
          link: { path: '/pipeline-trace', label: '打开隐私链路追踪' },
        },
      ],
    },
    'system-management': {
      eyebrow: '功能指南',
      title: '系统管理',
      summary: '管理用户与用户组，并从系统总览核对核心服务、扫描分析、模型网关和接入链路是否完整。',
      sections: [
        {
          id: 'users-groups',
          title: '用户与组',
          paragraphs: ['用户组既用于组织人员和Agent，也用于模型访问与隐私策略绑定。创建用户后，应按实际职责授予最小权限。'],
          link: { path: '/users-groups', label: '打开用户与组' },
        },
        {
          id: 'system-status',
          title: '系统状态',
          bullets: ['核心服务：确认后台API、内容完整性校验密钥和审计入口。', '扫描分析：确认Sandbox连接、LLM分析模型和深度分析能力。', '模型网关：确认可用模型、模型调用凭证、隐私策略和Prompt防护测试。', '接入链路：确认Agent运行凭证、Runtime校验接口、Scanner接入凭证和统一审计。', '依赖未配置或不可用时，提交页对应检测选项应保持禁用。'],
          image: { name: 'system', alt: '系统总览页面', caption: '先解决基础服务异常，再判断检测结果是否有问题。' },
          link: { path: '/settings', label: '打开系统总览' },
        },
        {
          id: 'docs-assistant',
          title: '文档助手',
          paragraphs: ['管理员可以在“系统管理 → 文档设置”中启用文档助手，选择一个已启用的模型，并维护中英文欢迎语、回答要求和常见问题。启用后，帮助文档顶部会出现“问问 AI”，在右侧聊天栏中根据当前文档回答并给出经过校验的站内文档链接。'],
          bullets: ['功能默认关闭；未选择可用模型时不能启用。', '浏览器先从当前语言的帮助文档中选择相关小节，再把有限的文档片段发送给所选模型。', '模型只能依据提供的文档片段回答；站内链接由文档索引生成，不采用模型自行编造的链接。', '普通登录用户可以使用文档助手，只有管理员可以修改开关、模型和常见问题。', '文档设置存在未保存修改时，切换页面、刷新或关闭标签页前会提示确认。', 'AI回答用于快速定位，文档正文和系统实际配置仍是最终依据。'],
          link: { path: '/docs-settings', label: '打开文档设置' },
        },
      ],
    },
    'docker-deployment': {
      eyebrow: '部署与运维',
      title: '使用 Docker Compose 部署',
      summary: 'Agent Manager当前统一使用Docker Compose。联网环境现场构建镜像，离线环境加载交付镜像包，启动后的服务架构一致。',
      sections: [
        {
          id: 'architecture',
          title: '服务架构',
          paragraphs: ['Nginx在80端口提供统一入口，按路径转发管理台、管理API、模型网关和MCP数据面。Frontend与Backend位于app网络；Backend通过Sandbox执行动态检测，并把数据库、上传文件、运行数据和Registry写入四个命名卷。'],
          diagram: 'docker',
        },
        {
          id: 'before-you-start',
          title: '部署前检查',
          bullets: ['确认服务器是x86_64还是arm64/aarch64。', '确认Docker和Docker Compose可用。', '确认80端口未被占用。', '生产环境准备至少32位随机SECRET_KEY、管理员一次性密码和Sandbox密钥。', '离线环境确认安装包架构与服务器一致，并预留镜像解压和数据增长空间。'],
          code: 'uname -m\ndocker --version\ndocker compose version',
          callout: { type: 'note', title: '资源要求', body: '当前仓库尚未给出经过验证的最低CPU、内存和磁盘矩阵。部署文档不应编造数值，应以交付版本的实测结果补充。' },
        },
        {
          id: 'online',
          title: '联网环境部署',
          steps: [
            { title: '准备生产配置', body: '复制环境模板，替换所有replace-with-*值，并保持ENFORCE_SECURE_STARTUP=true。', code: 'cp .env.example .env' },
            { title: '构建镜像', body: '在项目根目录构建Backend、Frontend、Sandbox和运行时镜像。', code: './build.sh --all' },
            { title: '初始化签名密钥', body: '在首次启动前显式生成Skill签名身份。', code: 'docker compose run --rm --no-deps backend agent-manager signing-key init' },
            { title: '启动并检查', body: '后台启动服务并查看健康状态。', code: 'docker compose up -d\ndocker compose ps', expected: 'backend、frontend、nginx和sandbox均为running或healthy。' },
          ],
        },
        {
          id: 'offline',
          title: '离线环境部署',
          steps: [
            { title: '选择安装包', body: 'x86_64使用x86包；aarch64或arm64使用ARM包。' },
            { title: '加载镜像', body: '将示例版本替换为实际交付版本。', code: 'xz -dc docker_images/x86/agent-manager-images-v1.0.0.tar.xz | docker load' },
            { title: '配置并初始化密钥', body: '修改.env后使用同一版本TAG初始化签名身份。', code: 'cp .env.example .env\nTAG=v1.0.0 docker compose run --rm --no-deps backend agent-manager signing-key init' },
            { title: '启动服务', body: 'TAG必须与加载的镜像版本一致。', code: 'TAG=v1.0.0 docker compose up -d\ndocker compose ps' },
          ],
        },
        {
          id: 'verify',
          title: '部署后验证',
          bullets: ['四个核心服务状态正常。', '浏览器可以访问http://服务器地址/并登录。', '系统总览没有核心组件异常。', '可以提交一个测试ZIP并完成后台检测。', '重启Compose后Skill、凭证和审计数据仍然存在。'],
          code: 'docker compose ps\ndocker compose logs --tail=100 backend sandbox nginx',
        },
      ],
    },
    'docker-operations': {
      eyebrow: '部署与运维',
      title: 'Docker 日常运维',
      summary: '围绕服务状态、日志、持久化数据、升级和常见故障维护Compose部署。',
      sections: [
        {
          id: 'daily',
          title: '状态、日志与重启',
          code: 'docker compose ps\ndocker compose logs -f\ndocker compose logs -f backend\ndocker compose logs -f sandbox\ndocker compose restart backend',
          paragraphs: ['排障时先确认哪个服务不健康，再查看对应日志。不要一开始删除容器或数据卷。'],
        },
        {
          id: 'data',
          title: '持久化数据与备份',
          bullets: ['保存.env和当前镜像TAG。', '备份backend_data、backend_uploads、backend_sqlite和agent_manager_registry四个卷。', '确保Skill签名私钥和审计签名私钥随原卷恢复。', '恢复后检查Skill版本、凭证状态和审计链，而不只是确认网页能打开。'],
          callout: { type: 'warning', title: '危险操作', body: 'docker compose down -v会删除持久化卷，不属于日常停止命令。只有在确认目标、完成备份并明确需要清空数据时才可执行。' },
        },
        {
          id: 'upgrade',
          title: '升级与回滚原则',
          steps: [
            { title: '升级前审计', body: '通过Backend容器检查已批准或部署的Skill是否缺少Tool权限声明。', code: 'docker compose run --rm --no-deps backend agent-manager registry audit-tool-permissions' },
            { title: '备份', body: '记录旧TAG并备份环境文件、四个数据卷和签名身份。' },
            { title: '更新镜像', body: '联网环境重新构建；离线环境加载目标版本镜像。' },
            { title: '使用明确TAG启动', body: '不要依赖含义不清的latest完成正式升级。' },
            { title: '验证', body: '检查镜像架构、健康状态、网页、Skill列表、签名验证和审计。' },
          ],
        },
        {
          id: 'troubleshooting',
          title: '按现象排查',
          table: {
            columns: ['现象', '首先检查'],
            rows: [
              ['80端口无法绑定', '端口占用和Nginx启动日志'],
              ['Backend持续unhealthy', '.env占位密钥、安全启动、SQLite和签名密钥'],
              ['Sandbox无法启动', 'CPU架构、容器权限和Sandbox日志'],
              ['网页能开但接口失败', 'Backend健康状态和Nginx转发日志'],
              ['离线镜像无法启动', '安装包架构、镜像TAG和xz文件完整性'],
              ['重启后数据丢失', '命名卷是否保留、是否执行过down -v'],
            ],
          },
        },
      ],
    },
    faq: {
      eyebrow: '帮助',
      title: '常见问题',
      summary: '从用户看到的现象出发，先确认状态和证据，再决定是否需要重新检测或调整配置。',
      sections: [
        { id: 'pending', title: '为什么一直停留在 PENDING？', paragraphs: ['先查看该版本的检测记录，再检查后台日志以及系统总览中的深度分析、LLM和Sandbox状态。Scanner接入凭证只影响客户侧Scanner上传，不是ZIP提交完成检测的前置条件。PENDING表示后台任务尚未得到最终结果，不应直接判断为前端缓存。'] },
        { id: 'different-results', title: '为什么 Sandbox 是低风险，最终结果却更高？', paragraphs: ['Sandbox只观察本次探测实际触发的行为。未触发的分支、静态危险模式和LLM语义证据仍可能提高最终风险，因此应查看完整证据链。'] },
        { id: 'review-queue', title: '为什么 Skill 没有进入审核队列？', paragraphs: ['只有VETTED等待人工审核。APPROVED已被策略自动批准，REJECTED已被策略拒绝，PENDING仍在检测中。'] },
        { id: 'rescan', title: '为什么重复提交没有重新检测？', paragraphs: ['同名同内容且检测上下文一致时可以复用结果。需要重新执行分析时，应在Skill版本页面使用“重新检测”；内容已经变化则提交新版本。'] },
        { id: 'agent-blocked', title: '为什么 Agent 不能加载已批准的 Skill？', paragraphs: ['检查运行凭证是否绑定当前Agent、Agent是否获授权使用该Skill、本地签名是否匹配，以及当前请求是否先完成签名验证。'] },
        { id: 'credential-lost', title: '凭证明文丢失后能否再次查看？', paragraphs: ['不能。服务端只保存Hash。应吊销旧凭证并重新创建，然后更新调用方配置。'] },
        { id: 'client-offline', title: '客户端为什么显示离线或不能下发 Skill？', paragraphs: ['先检查客户端后台服务、平台地址、客户端接入凭证和最后心跳。下发失败时继续检查Skill是否已批准、目标Agent是否支持Skill管理；Agent强授权模式还要检查本地Agent绑定和Skill授权范围。'] },
        { id: 'compression-zero', title: '为什么启用了压缩但节省 Token 为 0？', paragraphs: ['确认供应商或本次调用使用的模型凭证已启用压缩，并查看链路或响应头。短上下文可能无需变换；压缩组件不可用或处理失败时会降级使用原始messages，因此“已启用”不保证每次产生节省。'] },
        { id: 'skill-alert-blocking', title: '模型网关的 Skill 告警会阻断请求吗？', paragraphs: ['当前不会。它用于核对调用方声明的Skill与平台登记、状态和Agent授权并生成审计告警，不等同于本地内容签名验证，也不替代Skill Verifier或客户端巡检。'] },
        { id: 'docker-web', title: 'Docker容器运行但网页打不开怎么办？', paragraphs: ['检查Nginx是否健康、80端口是否映射、Backend和Frontend是否健康，再查看Nginx日志。不要先删除数据卷。'] },
      ],
    },
  },
}

const en = {
  groups: [
    { title: 'Get started', items: [
      { slug: '', title: 'Documentation home', summary: 'Understand the platform and choose a path' },
      { slug: 'quick-start', title: 'Quick start', summary: 'Complete your first Skill governance flow' },
    ] },
    { title: 'Feature guides', items: [
      { slug: 'skill-governance', title: 'Skill governance', summary: 'Submission, scanning, review, and versions' },
      { slug: 'agent-management', title: 'Agent management', summary: 'Agent records, capability bindings, and credentials' },
      { slug: 'runtime-integration', title: 'Agent runtime integration', summary: 'Skill Verifier, event Hooks, and result handling' },
      { slug: 'client-management', title: 'Client management', summary: 'Local Agent discovery, Skill delivery, and continuous inspection' },
      { slug: 'model-gateway', title: 'Model gateway', summary: 'Model access, privacy controls, and token compression' },
      { slug: 'mcp-governance', title: 'MCP governance', summary: 'Servers, gateways, approvals, and audits' },
      { slug: 'system-management', title: 'System management', summary: 'Users, permissions, and system status' },
    ] },
    { title: 'Deploy and operate', items: [
      { slug: 'docker-deployment', title: 'Docker deployment', summary: 'Run the same Compose stack online or offline' },
      { slug: 'docker-operations', title: 'Docker operations', summary: 'Status, logs, backup, upgrade, and troubleshooting' },
    ] },
    { title: 'Help', items: [
      { slug: 'faq', title: 'FAQ', summary: 'Troubleshoot common symptoms' },
    ] },
  ],
  articles: {
    '': {
      eyebrow: 'Agent Manager docs', title: 'Govern Agent capabilities, model traffic, and local runtime',
      summary: 'From Skill admission and client delivery to model privacy controls, token compression, and MCP Tool approvals, the platform centralizes critical controls and audit evidence.', home: true,
      roles: [
        { title: 'Platform administrator', text: 'Start with Docker deployment, system checks, users, and credentials.', slug: 'docker-deployment' },
        { title: 'Security reviewer', text: 'Start with Skill reports, the review queue, and policy settings.', slug: 'skill-governance' },
        { title: 'Agent and client operator', text: 'Register Agents, choose a runtime check, then govern local Skills.', slug: 'agent-management' },
        { title: 'Model gateway operator', text: 'Configure models, privacy, Prompt protection, and token compression.', slug: 'model-gateway' },
      ],
      sections: [
        { id: 'what-it-does', title: 'What the platform does', paragraphs: ['Agent Manager is not only a Skill registry. It governs Agent Skills, local capability delivery, model traffic, and externally exposed MCP Tools.'], bullets: ['Scan, decide, review, and sign Skills before use, then revalidate changed content.', 'Give Agents least-privilege bindings and credentials; use clients to discover, deliver, restore, or quarantine local Skills.', 'Apply model access control, Prompt protection, privacy replacement, optional token compression, and usage analysis.', 'Publish selected MCP Tools through gateways with time-bound high-risk approvals and audits.'], diagram: 'platform' },
        { id: 'capability-map', title: 'Choose a feature by goal', table: { columns: ['Goal', 'Module'], rows: [['Submit and scan a Skill', { label: 'Skill governance / Submit Skill', path: '/docs/skill-governance' }], ['Review a suspicious Skill', { label: 'Skill governance / Skill Review', path: '/docs/skill-governance' }], ['Restrict an Agent to specific Skills', { label: 'Agent management / Bindings and credentials', path: '/docs/agent-management' }], ['Add signature and Tool checks to an Agent', { label: 'Agent runtime integration', path: '/docs/runtime-integration' }], ['Discover local Agents and Skill roots', { label: 'Client management / Agent Discovery', path: '/docs/client-management' }], ['Deliver, restore, or remove Skills on managed hosts', { label: 'Client management / Console operations', path: '/docs/client-management' }], ['Protect private model input', { label: 'Model gateway / Privacy policies', path: '/docs/model-gateway' }], ['Compress model context and measure savings', { label: 'Model gateway / Token compression', path: '/docs/model-gateway' }], ['Analyze token usage by user', { label: 'Model gateway / User token analytics', path: '/docs/model-gateway' }], ['Audit anomalous Skills declared in model calls', { label: 'Model gateway / Skill Alerts', path: '/docs/model-gateway' }], ['Publish and audit MCP Tools', { label: 'MCP governance / Servers and gateways', path: '/docs/mcp-governance' }]] } },
      ],
    },
    'quick-start': {
      eyebrow: 'Get started', title: 'Complete your first Skill governance flow', summary: 'Use a test ZIP with no production secrets or personal data to complete submission, scanning, review, Agent authorization, and runtime verification.',
      sections: [
        { id: 'check-system', title: '1. Check platform status', paragraphs: ['Open the dashboard and system overview first. LLM and Sandbox checks depend on administrator configuration; unavailable checks remain disabled on the submission page.'], image: { name: 'dashboard', alt: 'Platform dashboard', caption: 'The dashboard highlights pending Skills, risk distribution, and recent events.' }, link: { path: '/dashboard', label: 'Open dashboard' } },
        { id: 'submit-zip', title: '2. Upload a ZIP and select Skills', paragraphs: ['The current console supports ZIP upload and Scanner access. The platform parses importable Skills first, then lets you choose which entries to submit.'], steps: [{ title: 'Choose a ZIP', body: 'Each Skill directory must contain SKILL.md.' }, { title: 'Parse content', body: 'Confirm the directories and Skills found by the platform.' }, { title: 'Choose checks and submit', body: 'Do not force-enable an unavailable dependency.', expected: 'The result starts as PENDING while background checks continue.' }], image: { name: 'submit-skill', alt: 'Submit Skill page', caption: 'Upload a ZIP, parse its content, and select the Skills to scan.' }, link: { path: '/submit', label: 'Open Submit Skill' } },
        { id: 'review-result', title: '3. Read the report and decide', paragraphs: ['Review final risk, evidence, analyzer results, files, and version history. VETTED needs human review, APPROVED is trusted, and REJECTED does not enter the review queue.'], image: { name: 'skill-list', alt: 'Skill list page', caption: 'The list shows the latest content version, trusted version, status, and risk.' }, link: { path: '/skills', label: 'Open Skill list' } },
        { id: 'verify-runtime', title: '4. Connect an Agent and verify local content', paragraphs: ['Create an Agent, bind approved Skills, issue an Agent-bound runtime credential, and run Skill Verifier before the Agent uses local content.'], callout: { type: 'note', title: 'Verification order', body: 'Verify the local content digest first, then check the current Agent load permission. With an event Hook, also check Tool permission before Tool execution.' }, image: { name: 'runtime', alt: 'Access and Runtime page', caption: 'Runtime audit shows signature, load, tamper, and Tool events.' }, link: { path: '/runtime', label: 'Open Access & Runtime' } },
        { id: 'next-paths', title: '5. Continue based on your integration', paragraphs: ['This page covers only the first Skill governance flow. Choose a runtime verification method first, then configure the Client, Model Gateway, or MCP Gateway as required.'], table: { columns: ['Next goal', 'Continue with'], rows: [['Embed checks into Agent load and Tool-call flows', { label: 'Agent runtime integration', path: '/docs/runtime-integration' }], ['Govern local Skills across multiple hosts', { label: 'Client management', path: '/docs/client-management' }], ['Protect model requests and measure token savings', { label: 'Model gateway', path: '/docs/model-gateway' }], ['Publish MCP Tools through controlled gateways', { label: 'MCP governance', path: '/docs/mcp-governance' }]] } },
      ],
    },
    'skill-governance': {
      eyebrow: 'Feature guide', title: 'Skill governance', summary: 'Manage submission, scanning, policy decisions, human review, and trusted Skill versions.',
      sections: [
        { id: 'submission', title: 'Submission methods', table: { columns: ['Method', 'Use case', 'Current status'], rows: [['ZIP upload', 'Submit one or more Skills in the console', 'Available'], ['Scanner access', 'Discover and upload local Skills from customer hosts or CI', 'Available']] }, callout: { type: 'note', title: 'Choose the right entry point', body: 'Use ZIP for small manual submissions and Scanner access for continuous discovery across customer hosts, servers, or CI.' } },
        { id: 'pipeline', title: 'Scanning and decisions', paragraphs: ['A submission starts as PENDING. Enabled analyzers run in the background, and policy produces the final governance decision. No single Sandbox or LLM result replaces the final assessment.'], bullets: ['Static and rule analysis inspect files, permissions, and dangerous patterns.', 'Sandbox observes behavior triggered in a restricted run.', 'LLM may combine content and analyzer evidence when configured.', 'Policy routes the result to auto-approval, human review, or rejection.'], diagram: 'governance' },
        { id: 'states', title: 'States and next actions', table: { columns: ['State', 'Meaning', 'Next action'], rows: [['PENDING', 'Background checks are running', 'Wait or inspect scan runs'], ['VETTED', 'Checks complete; human review required', 'Approve or reject'], ['APPROVED', 'Trusted version approved', 'Bind to an Agent or install'], ['REJECTED', 'Rejected', 'Fix content and submit a new version'], ['DEPLOYED', 'In managed deployment', 'Continue integrity checks and audits']] } },
        { id: 'versions', title: 'Reports and versions', bullets: ['Read final risk, functional summary, evidence, attack chain, and framework mappings.', 'Inspect independent Scanner, rule, LLM, and Sandbox results.', 'Open stored files and raw reports instead of relying only on summaries.', 'Compare two content versions of the same Skill.', 'Rescan creates a new scan run; changed content must be submitted as a new version.'], link: { path: '/skills', label: 'Open Skill list' } },
      ],
    },
    'mcp-governance': {
      eyebrow: 'Feature guide', title: 'MCP governance', summary: 'Publish selected Tools from remote MCP Servers through controlled gateways with time-bound high-risk approvals and audits.',
      sections: [
        { id: 'flow', title: 'Recommended setup order', steps: [{ title: 'Register an MCP Server', body: 'Connect a Streamable HTTP endpoint and save the tools/list schema snapshot.' }, { title: 'Create an MCP Gateway', body: 'Select Tools from one or more registered servers.' }, { title: 'Issue a gateway credential', body: 'Limit gateways, IPs, expiry, request size, and concurrency.' }, { title: 'Validate with MCP Debug', body: 'Discover Tools and call through a real gateway credential.' }, { title: 'Review high-risk calls', body: 'Review masked arguments and issue a short-lived authorization.' }] },
        { id: 'boundaries', title: 'Important boundaries', bullets: ['Servers store upstream connections; gateways decide what callers can see.', 'A schema change pauses exposure until the gateway is saved again.', 'Approval is scoped to credential, gateway, Tool, and schema—not a permanent argument signature.', 'MCP credentials do not establish Agent identity.'], link: { path: '/mcp-governance/servers', label: 'Open MCP Servers' } },
        { id: 'audit', title: 'Approvals and call audits', paragraphs: ['Approval details show masked arguments by default. Revealing raw arguments creates a security audit event. Approved credentials may call the same Tool and schema during the validity window.'], link: { path: '/mcp-governance/approvals', label: 'Open Call Approvals' } },
      ],
    },
    'agent-management': {
      eyebrow: 'Feature guide', title: 'Agent management', summary: 'Use an Agent as the primary record for department, model, and Skill bindings, then issue a least-privilege credential.',
      sections: [
        { id: 'agent-record', title: 'Register the Agent before issuing credentials', steps: [{ title: 'Create an Agent', body: 'Set its name, department, and enabled state.' }, { title: 'Bind capabilities', body: 'Choose a default model, Prompt, and allowed Skills.' }, { title: 'Issue a runtime credential', body: 'Create an Agent runtime credential bound to the Agent.' }, { title: 'Configure the runtime', body: 'Give the one-time secret only to that Agent; never use an administrator login token.' }], link: { path: '/agents', label: 'Open Agents' } },
        { id: 'credential-types', title: 'Choose credentials by caller', table: { columns: ['Credential', 'Purpose'], rows: [['Agent runtime', 'Signature, load, and Tool checks'], ['Scanner access', 'Submit and read owned scan results'], ['Client access', 'Desktop client registration, tasks, and events'], ['Model gateway', 'Model calls from regular applications'], ['MCP gateway', 'MCP Client access to allowed gateways and Tools']] }, callout: { type: 'warning', title: 'Secrets are shown once', body: 'If lost, revoke and create a new credential. Never store real secrets in screenshots, docs, or source control.' } },
        { id: 'next-runtime', title: 'Next: choose a runtime verification method', paragraphs: ['After the Agent record, Skill bindings, and runtime credential are ready, choose Verifier, Hook, or Agent Manager Client based on whether the Agent supports Skill instructions, lifecycle events, or a background Client.'], link: { path: '/docs/runtime-integration', label: 'Read Agent runtime integration' } },
      ],
    },
    'runtime-integration': {
      eyebrow: 'Feature guide', title: 'Agent runtime integration', summary: 'Choose Skill Verifier, an event Hook, or the Client, and place content-integrity, load-permission, and Tool-permission checks at the correct execution points.',
      sections: [
        {
          id: 'integration-choice',
          title: 'Choose an integration method first',
          paragraphs: ['Each method solves a different problem. Choose by trigger and governance scope before following an implementation path.'],
          table: { columns: ['Method', 'Trigger', 'Best fit'], rows: [['Skill Verifier', 'The Agent follows an instruction before reading or loading', 'Fast integration for Agents with local Skill instructions'], ['Event Hook', 'Agent lifecycle or Tool events invoke it automatically', 'Runtimes that need consistent pre-load and pre-Tool checks'], ['Agent Manager Client', 'A background service inspects continuously and receives platform tasks', 'Central governance for local Agents and Skill roots across many hosts']] },
          link: { path: '/docs/client-management', label: 'Read Client management' },
        },
        {
          id: 'verifier-setup',
          title: 'Connect Skill Verifier',
          paragraphs: ['Skill Verifier fits Agents that can reliably run a verification instruction before reading or loading a Skill. The verify command computes a keyless local digest, verifies it against the approved version, then checks whether the bound Agent may load it.'],
          steps: [
            { title: 'Prepare the Agent and authorization', body: 'Create the Agent and bind its allowed Skills. Issue an Agent runtime credential with at least runtime:verify-signature and runtime:can-load.' },
            { title: 'Download and install Verifier', body: 'Download the ZIP from Access & Runtime, then extract it into the Agent Skill root, such as ~/.codex/skills or ~/.claude/skills.' },
            { title: 'Configure the runtime', body: 'The platform URL, Agent runtime credential, and Agent ID must resolve to the same registered Agent. Do not use an administrator token or copy the server signing private key to the Agent.', code: 'export AGENT_MANAGER_VERIFIER_BASE_URL="https://agent-manager.example.com"\nexport AGENT_MANAGER_AGENT_RUNTIME_TOKEN="amat_xxx"\nexport AGENT_ID="your-agent-id"' },
            { title: 'Verify before use', body: '--path must be one Skill directory containing SKILL.md; prefer an absolute path. Continue to read, load, or run the Skill only when the exit code is 0.', code: 'python ~/.codex/skills/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \\\n  --path /absolute/path/to/skill', expected: 'The command reports success and Runtime Audit contains signature and load checks.' },
          ],
          callout: { type: 'warning', title: 'Keep verification and scanning credentials separate', body: 'verify uses only the Agent runtime credential. Configure a separate Scanner access credential only for submit or status.' },
          link: { path: '/runtime', label: 'Open Access & Runtime' },
        },
        {
          id: 'verifier-result',
          title: 'Interpret Verifier results',
          table: { columns: ['Check', 'Pass condition', 'Action on failure'], rows: [['Local content digest', 'Matches an approved platform version', 'Use the approved version or submit changed content for scanning'], ['Skill state', 'APPROVED or DEPLOYED', 'Wait for scanning and review'], ['Agent authorization', 'The credential-bound Agent is allowed to use the Skill', 'Update the Agent binding or use the correct credential'], ['Command exit code', '0', 'Keep the original reason and stop using the Skill']] },
          bullets: ['A matching name does not prove matching content. Pass the real Skill path whenever the local directory is writable.', 'Run verify again whenever Skill content changes.', 'The verify command does not replace Tool authorization. A Hook or runtime adapter should call check-tool before each Tool execution.'],
        },
        {
          id: 'hook-integration',
          title: 'Connect an event Hook',
          paragraphs: ['Use a Hook when the Agent can execute code at defined lifecycle events: verify signature and load permission before loading, then call check-tool before Tool execution. The repository includes Claude Code / Trae and OpenClaw examples; validate Skill name, directory, and Agent ID mapping with real events.'],
          steps: [
            { title: 'Claude Code or Trae: configure PreToolUse', body: 'Install the project SDK and set AGENT_MANAGER_BASE_URL, AGENT_MANAGER_API_TOKEN, and AGENT_ID. AGENT_MANAGER_API_TOKEN must contain the runtime credential bound to this Agent. Use an absolute path to agent_guard_hook.py.', code: '{\n  "hooks": {\n    "PreToolUse": [{\n      "matcher": "",\n      "hooks": [{\n        "type": "command",\n        "command": "python3 /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py"\n      }]\n    }]\n  }\n}' },
            { title: 'Test the PreToolUse path', body: 'An authorized, unchanged Skill should exit 0. Tampered content, revoked authorization, or the wrong credential should exit 2 with the reason on stderr. Read ~/.agent-manager/logs/agent_guard_hook.log for diagnostics.' },
            { title: 'OpenClaw: connect two event points', body: 'The agent:bootstrap internal Hook enumerates visible Skills and calls verify-skill-signature plus can-load. Integrate before_tool_call into an OpenClaw plugin to call check-tool before execution. Map the session identity to a stable Agent ID registered in the platform.' },
            { title: 'Run failure drills before rollout', body: 'Test an unreachable platform, expired credential, missing Skill path, changed content, and unauthorized Tool. Confirm the Agent result, Hook log, and Runtime Audit for each case.' },
          ],
          callout: { type: 'warning', title: 'Validate event fields before rollout', body: 'The Claude Code / Trae example blocks API and network errors for recognized Skill calls; malformed input and non-Skill calls pass through. Test OpenClaw event fields and Agent identity mapping against the target version before broad deployment.' },
        },
      ],
    },
    'client-management': {
      eyebrow: 'Feature guide', title: 'Client management', summary: 'The desktop Client discovers, enrolls, and continuously governs local Agents and Skills; the console provides fleet visibility, policy configuration, and remote task delivery.',
      sections: [
        { id: 'desktop-and-console', title: 'Separate the desktop Client from the console', paragraphs: ['Install Agent Manager Client on every workstation or server whose local Skills need governance. It registers with a Client access credential, sends heartbeats, and reports local Agents, Skill inventory, and security events. It is not a reduced version of the admin console; the two surfaces have different responsibilities.'], table: { columns: ['Where you work', 'Primary responsibility'], rows: [['Desktop Client', 'Discover local Agents and Skill roots, choose governance scope, install trusted versions, and continuously audit, restore, or quarantine local content.'], ['Platform console', 'View multiple Clients, configure governance and enforcement, bind managed Agents, and remotely deliver install, repair, remove, and policy-sync tasks.']] }, image: { name: 'client-app-overview', alt: 'Agent Manager desktop Client overview', caption: 'Client Overview combines connection progress, local Agents, managed Skills, platform scanning capabilities, and background inspection state. The screenshot uses example data.' } },
        { id: 'install-register', title: 'Install and connect', steps: [{ title: 'Download the matching installer', body: 'The console currently lists macOS Apple Silicon, macOS Intel, Windows x64, and Linux x64 packages; actual availability depends on the current release.' }, { title: 'Create a Client access credential', body: 'Choose the Client type in Credential Center and keep the least-privilege client:* scopes. The secret is shown only once.' }, { title: 'Connect and discover Agents', body: 'Enter the platform address and credential in the Client, then confirm discovered Agents, shared roots, and Skill paths.' }, { title: 'Confirm scope and enable background inspection', body: 'Generate a governance preview, confirm which Skills remain enabled or move to pending, then install the background service.', expected: 'After the desktop window closes, an installed background service continues syncing tasks, inspecting files, and reporting events.' }] },
        { id: 'client-pages', title: 'What each desktop page provides', table: { columns: ['Page or entry', 'What you can do'], rows: [['Client Overview', 'Inspect connection, enrollment progress, local Agents, managed Skills, action items, and platform scanning capabilities.'], ['Agent Discovery', 'Discover built-in Agents, shared Skill roots, and custom Agents, then review paths and select Skills for governance.'], ['Skill Governance', 'Preview enrollment, install approved versions, move unknown or unapproved content safely to pending, and submit it for scanning.'], ['Runtime Status', 'Run an inspection, pause or resume continuous governance, inspect quarantine, and use pre-enrollment backups for advanced recovery.'], ['Activity Records', 'Separate local inspection and remediation from platform-delivered install, repair, remove, and policy tasks.'], ['Security Notifications', 'Review automatic recovery, isolation block, and audit-only alerts, filtered by unread or severity.'], ['Settings', 'Choose language and start page, configure system notifications and background start, select update channel, and export diagnostics without plaintext credentials.']] } },
        { id: 'discover-govern', title: 'Discover and enroll local Skills', paragraphs: ['The Client recognizes Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw, Hermes, TRAE, Cursor, and other supported Agents plus shared Skill roots. Unsupported tools can be registered as custom Agents.'], bullets: ['Expand an Agent to review its real scan roots, Skill names, and validation state before selecting governance scope.', 'The preview separates trusted, enrollable, and pending content, and requires explicit confirmation before changes.', 'Disabled does not mean deleted: content is removed from the Agent entry point, kept safely, and can be submitted for platform scanning.', 'When installing from the platform, choose an approved version and one or more target Agents; the Client verifies release signature and file hashes.'], image: { name: 'client-app-discovery', alt: 'Desktop Client Agent Discovery page', caption: 'Agent Discovery groups Skill roots, discovery results, and platform state by local Agent. The screenshot uses example paths and data.' }, callout: { type: 'note', title: 'Shared-root identity boundary', body: 'Multiple Agents may read the same shared Skill root. The Client can govern its state and content integrity, but the directory alone does not identify the actual caller.' } },
        { id: 'governance-modes', title: 'Governance modes and enforcement policies', table: { columns: ['Setting', 'Actual effect'], rows: [['Client security governance', 'A local Skill may be used when it is a trusted platform version and its signature matches; a platform Agent binding is not required.'], ['Strict Agent authorization', 'The local Agent must be bound to a managed Agent and may install only Skills authorized for that Agent.'], ['Audit only', 'Record and report abnormal content without changing local files.'], ['Automatic recovery', 'Restore the approved platform version when a managed Skill becomes abnormal.'], ['Isolation block', 'Move abnormal content into quarantine and remove it from the Agent Skill entry point.']] }, callout: { type: 'warning', title: 'Confirm the affected paths first', body: 'Automatic recovery and isolation modify local Skill directories. Observe path detection and events in Audit only mode before enabling them in production.' } },
        { id: 'continuous-governance', title: 'Continuous inspection, quarantine, and recovery', paragraphs: ['The background service periodically syncs platform policy and tasks, then checks whether managed Skills were modified, revoked, or replaced. If the platform is temporarily unavailable, the Client continues with the last successfully synced policy and reports queued events after reconnection.'], bullets: ['Run Inspection Now performs a full check; pausing continuous governance does not delete managed content.', 'Quarantine preserves the abnormal copy and reason without restoring unconfirmed content to the Agent entry point.', 'Prefer an approved platform version for recovery. Pre-enrollment backups are reserved for explicit emergency rollback.', 'Activity Records and Security Notifications provide evidence for local inspection, automatic remediation, and platform tasks.'], image: { name: 'client-app-status', alt: 'Desktop Client Runtime Status page', caption: 'Runtime Status shows background inspection, managed and quarantined counts, queued events, and follow-up actions for quarantined content. The screenshot uses example data.' } },
        { id: 'console-management', title: 'Manage the Client fleet from the console', paragraphs: ['The console list provides fleet-wide online state, version, Agent and Skill counts, security events, and last heartbeat. Client details then expose governance mode, local Agents, tasks, and events.'], image: { name: 'client-list', alt: 'Console Client list', caption: 'The console list compares Client state and governance scale across hosts. Values shown are example environment data.' }, bullets: ['Client details switch between Client security governance and Strict Agent authorization and configure Audit only, Automatic recovery, or Isolation block.', 'Select an approved platform Skill under a local Agent to deliver, repair, or remove it remotely.', 'Failed or cancelled Client tasks can be retried; local inspection and remediation enter events and unified audit.'], callout: { type: 'note', title: 'What Client tasks do', body: 'Client tasks install, restore, or remove Skills and synchronize policy. After execution, verify the target Agent, Skill, task state, and latest event in Client details.' }, link: { path: '/clients', label: 'Open Client management' } },
        { id: 'console-client-detail', title: 'Verify tasks and events in Client details', paragraphs: ['After a remote operation, verify the target Agent, Skill, task state, and latest event in the same details drawer instead of relying only on the button confirmation.'], image: { name: 'client-detail', alt: 'Console Client detail page', caption: 'Client details combine governance mode, enforcement policy, local Agents, recent tasks, and security events.' }, link: { path: '/clients', label: 'View Client details' } },
      ],
    },
    'model-gateway': {
      eyebrow: 'Feature guide', title: 'Model gateway', summary: 'Proxy model traffic and centralize access control, Prompt protection, privacy replacement, optional context compression, usage analysis, and call audits.',
      sections: [
        { id: 'feature-map', title: 'Pages and capabilities', table: { columns: ['Page', 'What it controls or explains'], rows: [['Providers / Models', 'Register upstream endpoints and model limits, formats, and enabled state.'], ['Group policies / Privacy policies', 'Bind model access and PII handling to user groups.'], ['Prompt Guard', 'Test and audit prompt injection, system prompt leakage, and credential exfiltration patterns.'], ['Skill Alerts', 'Compare Skills declared by callers with registry, state, and Agent authorization.'], ['Privacy Audit / Pipeline Trace', 'Inspect results and original, replaced, compressed, upstream, and restored stages.'], ['Token Compression Stats / User Token Analytics', 'Inspect requests, token use, savings, processing time, and user-level consumption.']] } },
        { id: 'setup-flow', title: 'Setup order', steps: [{ title: 'Add a provider', body: 'Configure an OpenAI-compatible endpoint, API format, and provider secret; enable provider-level compression if required.' }, { title: 'Register models', body: 'Set model name, context size, output limits, and enabled state.' }, { title: 'Configure groups and privacy policies', body: 'Choose PII entities, Prompt protection, and session mapping behavior.' }, { title: 'Issue a model credential', body: 'Limit models, expiry, request size, and concurrency; compression may also be enabled only for selected credentials.' }, { title: 'Call and inspect the trace', body: 'Use an OpenAI- or Anthropic-compatible endpoint, then inspect the privacy pipeline.' }], link: { path: '/model-gateway/providers', label: 'Open Providers' } },
        { id: 'pipeline', title: 'What happens to a request', bullets: ['Validate credential state, model scope, request size, and concurrency.', 'When the matching policy enables it, detect prompt injection, system prompt leakage, and credential exfiltration patterns.', 'When a privacy policy matches, replace PII with session-scoped pseudonymous tokens.', 'When the provider or credential enables compression, process context before the upstream call.', 'Restore the response and record audit, usage, and trace stages.'] },
        { id: 'token-compression', title: 'Token compression and usage analysis', paragraphs: ['Compression can be enabled on a provider or model credential with auto, conservative, or aggressive level. The platform processes messages before the upstream call and records token counts before and after compression, savings, ratio, and processing time.'], bullets: ['Token Compression Stats groups requests, input and output tokens, savings, average response time, model time, and platform time by period and model.', 'User Token Analytics compares call volume and token consumption across users.', 'Response headers and Pipeline Trace help distinguish compressed, enabled with no transformation, and disabled requests.'], callout: { type: 'note', title: 'Enabled does not mean every request saves tokens', body: 'Short context may need no transformation. If the compression component is unavailable or fails, the gateway falls back to the original messages, so enabled must not be interpreted as saved.' }, image: { name: 'token-compression', alt: 'Token Compression Stats page', caption: 'The stats page combines token usage, compression requests, savings, and platform and model timing. Values shown are example environment data.' }, link: { path: '/model-gateway/stats', label: 'Open Token Compression Stats' } },
        { id: 'skill-alerts', title: 'Skill Alerts in model requests', paragraphs: ['When a caller declares Skills in a model request, the platform compares them with Skill registration, loadable state, and Agent authorization, then records missing, unknown, mismatched, unavailable, or unauthorized declarations.'], callout: { type: 'warning', title: 'Currently audit-only', body: 'Skill Alerts do not block model calls. Caller-declared Skill metadata is not local signature or content verification; use Skill Verifier or Client inspection when content integrity is required.' }, link: { path: '/model-gateway/skill-alerts', label: 'Open Skill Alerts' } },
        { id: 'privacy', title: 'Privacy trace boundaries', paragraphs: ['Pipeline Trace can show original, masked, compressed, upstream, and restored content. Original stages may contain PII and should be limited to authorized administrator or privacy auditor roles.'], link: { path: '/pipeline-trace', label: 'Open Pipeline Trace' } },
      ],
    },
    'system-management': {
      eyebrow: 'Feature guide', title: 'System management', summary: 'Manage users and groups, then verify core services, scan analysis, the model gateway, and access chains from System Overview.',
      sections: [
        { id: 'users-groups', title: 'Users and groups', paragraphs: ['Groups organize people and Agents and also drive model access and privacy policy bindings. Grant the minimum permissions required for each role.'], link: { path: '/users-groups', label: 'Open Users & Groups' } },
        { id: 'system-status', title: 'System status', bullets: ['Core services: verify the Backend API, content-integrity signing key, and audit entry point.', 'Scan analysis: verify Sandbox connectivity, LLM analysis model, and deep-analysis capability.', 'Model gateway: verify available models, model credentials, privacy policies, and Prompt Guard test.', 'Access chain: verify Agent runtime credentials, Runtime validation API, Scanner access credentials, and unified audit.', 'Unavailable dependencies should leave corresponding submission checks disabled.'], image: { name: 'system', alt: 'System overview page', caption: 'Resolve core service failures before diagnosing scan results.' }, link: { path: '/settings', label: 'Open System Overview' } },
        { id: 'docs-assistant', title: 'Documentation assistant', paragraphs: ['Administrators can enable the documentation assistant under System Management → Documentation settings, select an enabled model, and maintain bilingual welcome messages, answer guidance, and common questions. Once enabled, Ask AI appears in the help header and opens a right-side chat rail that answers from the current docs and shows verified internal documentation links.'], bullets: ['The feature is disabled by default and cannot be enabled without an available model.', 'The browser selects relevant sections from the current-language help docs and sends only a limited set of excerpts to the selected model.', 'The model must answer only from supplied excerpts; internal links come from the documentation index rather than model-generated URLs.', 'Signed-in users may use the assistant, while only administrators may change its settings.', 'If documentation settings have unsaved changes, the page asks for confirmation before navigation, reload, or tab closure.', 'AI answers help with navigation; the documentation and actual system configuration remain authoritative.'], link: { path: '/docs-settings', label: 'Open Documentation Settings' } },
      ],
    },
    'docker-deployment': {
      eyebrow: 'Deploy and operate', title: 'Deploy with Docker Compose', summary: 'Agent Manager uses Docker Compose. Online environments build images locally; offline environments load delivered images. Both run the same service architecture.',
      sections: [
        { id: 'architecture', title: 'Service architecture', paragraphs: ['Nginx exposes port 80 and routes the console, management API, model gateway, and MCP data plane by path. Frontend and Backend use the app network; Backend invokes Sandbox for dynamic checks and writes databases, uploads, runtime data, and the Registry to four named volumes.'], diagram: 'docker' },
        { id: 'before-you-start', title: 'Before deployment', bullets: ['Identify x86_64 or arm64/aarch64 architecture.', 'Verify Docker and Docker Compose.', 'Check that port 80 is available.', 'Prepare a strong SECRET_KEY, one-time administrator password, and Sandbox secret for production.', 'For offline delivery, match archive architecture and reserve space for image extraction and data growth.'], code: 'uname -m\ndocker --version\ndocker compose version', callout: { type: 'note', title: 'Resource requirements', body: 'The repository does not yet contain a validated minimum CPU, memory, and disk matrix. Do not invent numbers; add tested values for each release.' } },
        { id: 'online', title: 'Online deployment', steps: [{ title: 'Prepare production configuration', body: 'Replace every replace-with-* value and keep ENFORCE_SECURE_STARTUP=true.', code: 'cp .env.example .env' }, { title: 'Build images', body: 'Build Backend, Frontend, Sandbox, and runtime images.', code: './build.sh --all' }, { title: 'Initialize the signing key', body: 'Create the Skill signing identity before first startup.', code: 'docker compose run --rm --no-deps backend agent-manager signing-key init' }, { title: 'Start and verify', body: 'Start in the background and inspect health.', code: 'docker compose up -d\ndocker compose ps', expected: 'backend, frontend, nginx, and sandbox are running or healthy.' }] },
        { id: 'offline', title: 'Offline deployment', steps: [{ title: 'Choose the archive', body: 'Use x86 for x86_64 and ARM for aarch64 or arm64.' }, { title: 'Load images', body: 'Replace the sample version with the delivered release.', code: 'xz -dc docker_images/x86/agent-manager-images-v1.0.0.tar.xz | docker load' }, { title: 'Configure and initialize signing', body: 'Edit .env and use the same TAG as the delivered images.', code: 'cp .env.example .env\nTAG=v1.0.0 docker compose run --rm --no-deps backend agent-manager signing-key init' }, { title: 'Start services', body: 'TAG must match the loaded image version.', code: 'TAG=v1.0.0 docker compose up -d\ndocker compose ps' }] },
        { id: 'verify', title: 'Post-deployment verification', bullets: ['All four core services are healthy.', 'The console opens at http://server-address/ and login succeeds.', 'System Overview shows no core dependency failures.', 'A test ZIP can complete background scanning.', 'Compose restart preserves Skills, credentials, and audits.'], code: 'docker compose ps\ndocker compose logs --tail=100 backend sandbox nginx' },
      ],
    },
    'docker-operations': {
      eyebrow: 'Deploy and operate', title: 'Docker operations', summary: 'Maintain the Compose deployment through service health, logs, persistent data, upgrades, and symptom-led troubleshooting.',
      sections: [
        { id: 'daily', title: 'Status, logs, and restart', code: 'docker compose ps\ndocker compose logs -f\ndocker compose logs -f backend\ndocker compose logs -f sandbox\ndocker compose restart backend', paragraphs: ['Identify the unhealthy service and read its logs before deleting or recreating anything.'] },
        { id: 'data', title: 'Persistent data and backup', bullets: ['Keep .env and the current image TAG.', 'Back up backend_data, backend_uploads, backend_sqlite, and agent_manager_registry.', 'Restore Skill and audit signing identities with their original volumes.', 'Verify Skill versions, credential state, and the audit chain—not only page availability.'], callout: { type: 'warning', title: 'Destructive command', body: 'docker compose down -v deletes persistent volumes. It is not a routine stop command. Use it only with an exact target, a verified backup, and explicit intent to erase data.' } },
        { id: 'upgrade', title: 'Upgrade and rollback principles', steps: [{ title: 'Pre-upgrade audit', body: 'Use the Backend container to find approved or deployed Skills without Tool permission declarations.', code: 'docker compose run --rm --no-deps backend agent-manager registry audit-tool-permissions' }, { title: 'Back up', body: 'Record the previous TAG and back up configuration, four volumes, and signing identities.' }, { title: 'Update images', body: 'Rebuild online or load the target offline image archive.' }, { title: 'Start with an explicit TAG', body: 'Do not rely on an ambiguous latest tag for a formal upgrade.' }, { title: 'Verify', body: 'Check architecture, health, console, Skills, signature verification, and audit.' }] },
        { id: 'troubleshooting', title: 'Troubleshoot by symptom', table: { columns: ['Symptom', 'Check first'], rows: [['Port 80 cannot bind', 'Port ownership and Nginx startup logs'], ['Backend stays unhealthy', '.env placeholders, secure startup, SQLite, and signing keys'], ['Sandbox does not start', 'CPU architecture, container permissions, and Sandbox logs'], ['Console opens but APIs fail', 'Backend health and Nginx proxy logs'], ['Offline images do not start', 'Archive architecture, TAG, and xz integrity'], ['Data disappears after restart', 'Named volumes and any down -v use']] } },
      ],
    },
    faq: {
      eyebrow: 'Help', title: 'Frequently asked questions', summary: 'Start from the visible symptom, confirm state and evidence, then decide whether to rescan or change configuration.',
      sections: [
        { id: 'pending', title: 'Why does a Skill remain PENDING?', paragraphs: ['Inspect scan runs first, then check backend logs and the deep-analysis, LLM, and Sandbox state in System Overview. Scanner access credentials affect only customer-side Scanner uploads and are not a prerequisite for ZIP scanning. PENDING means the background workflow has no final result yet; do not assume a browser cache problem.'] },
        { id: 'different-results', title: 'Why is Sandbox low risk while final risk is higher?', paragraphs: ['Sandbox only sees behavior triggered during one probe. Static patterns, untriggered branches, and LLM evidence may still raise final risk.'] },
        { id: 'review-queue', title: 'Why is a Skill missing from the review queue?', paragraphs: ['Only VETTED items wait for human review. APPROVED was auto-approved, REJECTED was rejected by policy, and PENDING is still scanning.'] },
        { id: 'rescan', title: 'Why did an identical submission not run again?', paragraphs: ['Identical content and scan context may reuse results. Use Rescan for a fresh run; submit changed content as a new version.'] },
        { id: 'agent-blocked', title: 'Why can an Agent not load an approved Skill?', paragraphs: ['Check that the runtime credential is bound to the Agent, the Agent is authorized for the Skill, the local signature matches, and signature verification happened before the load check.'] },
        { id: 'credential-lost', title: 'Can a lost credential secret be shown again?', paragraphs: ['No. The server stores only a hash. Revoke the old credential, create a new one, and update the caller.'] },
        { id: 'client-offline', title: 'Why is a Client offline or unable to deliver a Skill?', paragraphs: ['Check the Client background service, platform address, Client access credential, and last heartbeat. If delivery fails, confirm that the Skill is approved and the target Agent supports Skill management. Strict Agent authorization also requires the local Agent binding and allowed Skill scope.'] },
        { id: 'compression-zero', title: 'Why are token savings zero after compression is enabled?', paragraphs: ['Confirm that compression is enabled on the provider or the credential used by this call, then inspect the trace or response headers. Short context may need no transformation; if compression is unavailable or fails, the gateway falls back to the original messages. Enabled therefore does not guarantee savings on every request.'] },
        { id: 'skill-alert-blocking', title: 'Do Model Gateway Skill Alerts block requests?', paragraphs: ['Not currently. They compare caller-declared Skills with registry, state, and Agent authorization and create audit alerts. They are not local content signature verification and do not replace Skill Verifier or Client inspection.'] },
        { id: 'docker-web', title: 'Containers run but the console is unavailable', paragraphs: ['Check Nginx health, port 80 mapping, Backend and Frontend health, then read Nginx logs. Do not delete volumes first.'] },
      ],
    },
  },
}

export const docsContent = { 'zh-CN': zh, 'en-US': en }

export const docsArticleOrder = [
  '',
  'quick-start',
  'skill-governance',
  'agent-management',
  'runtime-integration',
  'client-management',
  'model-gateway',
  'mcp-governance',
  'system-management',
  'docker-deployment',
  'docker-operations',
  'faq',
]
