const zh = {
  groups: [
    { title: '开始使用', items: [
      { slug: '', title: '文档首页', summary: '认识平台并选择适合自己的使用路径' },
      { slug: 'quick-start', title: '快速上手', summary: '走通第一条 Skill 治理链路' },
    ] },
    { title: '能力治理', items: [
      { subgroup: 'Skill 治理', slug: 'skill-governance', title: '治理流程', summary: '提交、检测、审核与版本管理' },
      { subgroup: 'Skill 治理', slug: 'scanner-access', title: 'Scanner 接入', summary: '批量发现、预检并上传本地 Skill' },
      { subgroup: 'Skill 治理', slug: 'scan-capabilities', title: '检测能力', summary: '规则、深度、Sandbox 与 LLM 分析' },
      { subgroup: 'Skill 治理', slug: 'risk-classification', title: '风险项目归类', summary: '阻断项、可疑项、噪声与最终风险' },
      { subgroup: 'Skill 治理', slug: 'skill-policy', title: '策略配置', summary: '风险判定、准入约束与分析器设置' },
      { subgroup: 'MCP 治理', slug: 'mcp-governance', title: 'MCP 治理', summary: '服务、网关、审批与调用审计' },
    ] },
    { title: '智能体管理', items: [
      { slug: 'agent-management', title: '智能体管理', summary: 'Agent 档案、能力绑定与凭证选择' },
      { slug: 'client-management', title: '客户端管理', summary: '本地 Agent 发现、Skill 下发与持续巡检' },
      { slug: 'credential-management', title: '统一凭证中心', summary: '按调用主体签发最小权限凭证' },
      { slug: 'runtime-integration', title: '接入与运行', summary: 'Skill Verifier、事件 Hook 与结果判断' },
      { slug: 'audit-trail', title: '审计追踪', summary: '查询 Skill、Agent、客户端与 Tool 事件' },
    ] },
    { title: '模型网关', items: [
      { slug: 'model-gateway', title: '模型网关', summary: '模型接入、隐私防护与 Token 压缩' },
    ] },
    { title: '系统管理', items: [
      { slug: 'system-management', title: '系统管理', summary: '用户、权限与系统状态' },
    ] },
    { title: '部署与运维', items: [
      { slug: 'docker-deployment', title: 'Docker 部署', summary: '在线或离线方式启动同一套 Compose 服务' },
      { slug: 'performance-benchmark', title: '性能与容量', summary: '隔离环境实测并发、Skill 容量与客户端开销' },
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
              ['批量接入主机或 CI 中的 Skill', { label: 'Scanner 接入', path: '/docs/scanner-access' }],
              ['选择检测方式并理解结果', { label: 'Skill 检测能力', path: '/docs/scan-capabilities' }],
              ['理解阻断项、可疑项和噪声', { label: '风险项目归类', path: '/docs/risk-classification' }],
              ['配置 Skill 风险与准入规则', { label: 'Skill 策略配置', path: '/docs/skill-policy' }],
              ['审核可疑 Skill', { label: 'Skill 治理 / Skill 审核', path: '/docs/skill-governance' }],
              ['让 Agent 只能使用指定 Skill', { label: '智能体管理 / 能力绑定与凭证', path: '/docs/agent-management' }],
              ['为不同调用方创建最小权限凭证', { label: '统一凭证中心', path: '/docs/credential-management' }],
              ['把验签和 Tool 检查接入 Agent', { label: 'Agent 运行校验接入', path: '/docs/runtime-integration' }],
              ['发现本机 Agent 和 Skill 目录', { label: '客户端管理 / Agent 发现', path: '/docs/client-management' }],
              ['向本地 Agent 下发、恢复或移除 Skill', { label: '客户端管理 / 管理台操作', path: '/docs/client-management' }],
              ['保护发送给模型的隐私数据', { label: '模型网关 / 隐私策略', path: '/docs/model-gateway' }],
              ['压缩模型上下文并查看节省效果', { label: '模型网关 / Token 压缩', path: '/docs/model-gateway' }],
              ['分析不同用户的 Token 使用', { label: '模型网关 / 用户 Token 分析', path: '/docs/model-gateway' }],
              ['查看模型调用声明的 Skill 是否异常', { label: '模型网关 / Skill 告警', path: '/docs/model-gateway' }],
              ['统一发布并审计 MCP Tool', { label: 'MCP 治理 / 服务与网关', path: '/docs/mcp-governance' }],
              ['追踪 Skill、Agent、客户端与 Tool 事件', { label: '审计追踪', path: '/docs/audit-trail' }],
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
              ['理解规则、深度扫描、Sandbox 与 LLM 的区别', { label: 'Skill 检测能力', path: '/docs/scan-capabilities' }],
              ['批量发现并提交服务器或 CI 中的 Skill', { label: 'Scanner 接入', path: '/docs/scanner-access' }],
              ['理解发现项如何归类并形成最终风险', { label: '风险项目归类', path: '/docs/risk-classification' }],
              ['按企业要求配置风险判定和准入约束', { label: 'Skill 策略配置', path: '/docs/skill-policy' }],
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
      eyebrow: 'Skill 治理',
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
          link: { path: '/docs/scan-capabilities', label: '了解每种检测能力' },
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
          id: 'review-workflow',
          title: '人工审核时看什么',
          steps: [
            { title: '确认检测完整性', body: '先看各分析器是 completed、skipped、unavailable 还是 failed；没有结果不能直接解释为没有风险。' },
            { title: '核对原始证据', body: '从阻断项和可疑项开始，打开对应文件、行号、原始报告和 Sandbox 输出，确认是否属于真实行为。' },
            { title: '检查声明与实际行为', body: '对比 SKILL.md 的用途、allowed-tools、license 与代码中的网络、凭据、动态执行和写入行为。' },
            { title: '批准或拒绝', body: '只有 VETTED 会进入审核队列。批准后生成可信版本和签名；拒绝后应修复内容并提交新版本。', expected: '审核动作、审核人和结果可在审计追踪中查询。' },
          ],
          link: { path: '/review', label: '打开 Skill 审核' },
        },
        {
          id: 'versions',
          title: '报告与版本',
          bullets: ['查看最终风险、功能概括、风险证据、攻击链和安全框架映射。', '查看 Scanner、规则、LLM和Sandbox的独立结果及原始报告。', '查看服务端保存的文件内容，避免只依赖摘要。', '比较同名 Skill 的两个内容版本。', '“重新检测”生成新的检测记录，不创建内容版本；内容改变应提交新版本。'],
          link: { path: '/skills', label: '打开 Skill 列表' },
        },
      ],
    },
    'scanner-access': {
      eyebrow: 'Skill 治理',
      title: 'Scanner 批量接入本地 Skill',
      summary: '使用单二进制 Scanner 递归发现服务器、工作站或 CI 中的 Skill，先做本地轻量预检，再以最小权限上传平台完成正式检测。',
      sections: [
        {
          id: 'when-to-use',
          title: '什么时候使用 Scanner',
          table: { columns: ['场景', '推荐入口'], rows: [
            ['少量 ZIP、由管理员手工选择', '提交 Skill 页面'],
            ['一台机器有多个 Skill 根目录', 'Scanner CLI'],
            ['服务器或 CI 定期批量提交', 'Scanner CLI + 独立 Scanner 凭证'],
            ['需要持续治理和自动修复本机 Skill', 'Agent Manager Client，不是 Scanner CLI'],
          ] },
          callout: { type: 'note', title: '本地预检不等于平台批准', body: 'Scanner 本地预检不执行客户代码，只检查打包边界和明显静态信号。APPROVED、VETTED 或 REJECTED 仍由服务端完整检测和策略决定。' },
        },
        {
          id: 'credential',
          title: '创建 Scanner 最小权限凭证',
          steps: [
            { title: '进入统一凭证中心', body: '创建“Scanner 接入凭证”，不要使用管理员登录 Token 或 Agent 运行凭证。' },
            { title: '保留默认 Scanner 权限', body: '批量上传和读取自己的结果需要 scanner:submit、scanner:read-own-results、scanner:read-own-sessions。' },
            { title: '限制使用边界', body: '按现场需要设置允许 IP / CIDR、最大上传大小和最大并发任务数。明文只展示一次。' },
          ],
          link: { path: '/credentials', label: '打开统一凭证中心' },
        },
        {
          id: 'run',
          title: '下载并执行第一次扫描',
          steps: [
            { title: '下载匹配平台的二进制', body: '当前下载页支持 macOS Apple Silicon、macOS Intel、Linux x86_64、Linux ARM64 和 Windows x86_64；实际可下载项取决于服务器发布目录。' },
            { title: '配置平台和凭证', body: '平台地址设置后才会上传；不设置时只生成本地发现和预检报告。', code: 'export SKILL_SCANNER_SERVER="https://agent-manager.example.com"\nexport SKILL_SCANNER_TOKEN="amat_xxx"\nexport SKILL_SCANNER_HOST_ID="customer-prod-01"' },
            { title: '扫描 Skill 根目录', body: 'Scanner 递归寻找包含 SKILL.md 的目录。按需显式启用规则、深度、Sandbox 或 LLM，未配置的服务端能力可能失败或跳过。', code: './skill-scanner scan /path/to/skills \\\n  --behavioral \\\n  --deep-scan \\\n  --output skill-scan-report.json', expected: '本地报告包含发现路径、fingerprint、预检结果、上传状态和平台 skill_id。' },
          ],
          link: { path: '/scanner-access', label: '打开 Scanner 接入' },
        },
        {
          id: 'packaging-safety',
          title: '打包和结果边界',
          bullets: ['默认忽略 .git、.venv、node_modules、__pycache__、dist 和 build 等目录。', '不跟随指向 Skill 目录外部的软链接，并限制单文件大小、总大小和文件数量。', '服务端解包后会重新计算 manifest 和 fingerprint，不能只信任客户端上报值。', 'Scanner 凭证只能读取自己提交的结果；403 可能是凭证所有权不匹配，不应清空或重建平台数据。', '同名同内容且扫描上下文一致时可能复用结果；需要强制执行时从 Skill 版本页面发起重新检测。'],
        },
      ],
    },
    'scan-capabilities': {
      eyebrow: 'Skill 治理',
      title: 'Skill 检测能力',
      summary: '理解基础 Scanner、规则分析、深度扫描、Sandbox 和 LLM 分析分别检查什么、何时可用，以及如何共同形成最终结论。',
      sections: [
        {
          id: 'capability-overview',
          title: '规则扫描、深度扫描、Sandbox 和 LLM 有什么区别',
          paragraphs: ['这些能力不是互相替代的“扫描档位”。静态分析负责广泛找线索，Sandbox 只观察一次受控运行真正触发的行为，LLM 最后结合内容和已有证据做语义研判；最终状态仍由风险汇总和准入策略决定。'],
          table: {
            columns: ['检测方式', '启用条件', '主要输出'],
            rows: [
              ['基础 Scanner', '每次提交都会启动；运行环境应提供 Scanner', '全目录静态规则、权限和已知危险模式'],
              ['规则分析（默认勾选）', '提交时保持“启动规则分析”勾选', '文本规则、Python AST、可疑行为意图和文件定位'],
              ['深度扫描', '运行环境可用且提交时勾选', '更细的静态发现、风险分数和原始报告'],
              ['Sandbox', '系统已启用且连接可用，或风险命中强制策略', '入口、参数、输出、退出码、超时和运行时信号'],
              ['LLM 分析', '系统已启用、已选择模型且提交时勾选', '语义风险、分析报告、证据取舍和攻击链'],
            ],
          },
          image: { name: 'submit-skill', alt: '提交 Skill 时选择检测方式', caption: '规则分析默认开启；深度扫描、Sandbox 和 LLM 只有在对应依赖可用时才能选择。' },
          link: { path: '/submit', label: '打开提交 Skill' },
        },
        {
          id: 'rule-analysis',
          title: '基础 Scanner 与规则分析',
          paragraphs: ['基础 Scanner 会扫描整个 Skill 目录，是每次检测的基础。提交页默认勾选的“规则分析”会再执行 Agent Manager 本地规则：读取 scripts、references、prompts 等目录及其他文本代码文件，并分析 Python AST；这两层都不会运行 Skill。'],
          bullets: ['重点识别提示词注入、系统提示词泄露、隐藏指令、数据外传、敏感凭据访问、下载后执行、动态执行和过宽权限等信号。', '报告会给出规则、严重度、文件和行号；命中表示需要复核的证据，不等于单条规则直接决定最终状态。', '如果基础 Scanner 不可用或执行失败，流程可以继续汇总其他分析器，但报告应显示错误，此时覆盖范围已经降低。'],
          callout: { type: 'note', title: '“行为分析”不是动态执行', body: '代码内部把这组附加规则称为 behavioral，但当前实现仍是文本模式和 AST 静态分析。真正执行 Skill 的只有 Sandbox probe。' },
        },
        {
          id: 'deep-scan',
          title: '深度扫描',
          paragraphs: ['深度扫描会对整个 Skill 做更细的静态分析，并保存有效风险等级、发现项、风险分数和原始报告。它适合第三方 Skill、内容复杂或基础规则需要补充证据的场景。'],
          bullets: ['只有运行环境支持深度扫描时，提交页才能勾选。', '当前深度扫描不会调用模型；需要语义研判时应另外勾选“LLM 分析”。', '不可用、超时或执行失败会在分析器状态和深度扫描结果中体现，不能把“没有报告”理解为“没有风险”。'],
        },
        {
          id: 'sandbox',
          title: 'Sandbox：观察被触发的运行时行为',
          paragraphs: ['Sandbox 会在本地 Docker runtime 或远程隔离服务中寻找一个真实存在的 .py、.sh 或 .js 入口并执行一次默认 probe。像命令行程序的脚本通常使用 --help，其他入口使用空参数；当前不会执行 SKILL.md 中的命令块，也不会让 LLM 生成额外 probe。'],
          bullets: ['查看 runtime、镜像或远程服务、入口、参数、stdout、stderr、退出码、超时、网络尝试和提取到的信号。', '提交时可以主动勾选；即使没有勾选，中间风险命中策略配置的强制等级后，后台也会尝试补跑 Sandbox。', '没有可执行入口会跳过；依赖缺失、输入缺失和非零退出码可能只是诊断信息，应与风险信号分开判断。'],
          callout: { type: 'warning', title: 'Sandbox 不是安全证明', body: '一次 probe 没有触发恶意分支，只能说明本次运行没有观察到该行为。规则、深度扫描或 LLM 仍可能给出更高风险。' },
        },
        {
          id: 'llm-analysis',
          title: 'LLM 分析：最后一次语义研判',
          paragraphs: ['勾选 LLM 后，系统等待已选的 Scanner、规则、深度扫描和 Sandbox 完成，再把 Skill 内容快照及分析证据交给已配置模型，进行一次最终语义研判。LLM 不直接执行 Skill。'],
          bullets: ['输出 benign、suspicious 或 malicious 风险、专业分析报告、证据接受或排除说明，以及适用时的攻击链和安全框架映射。', '阻断类证据不能被 LLM 降级；严格模式也不允许降低确定性风险。平衡或宽松模式在没有阻断项时可以降低非阻断风险，系统会记录模型提供的说明或回退原因。', '模型调用失败时保留失败状态，并回退到规则、深度扫描和 Sandbox 的确定性汇总，不能把“暂无 LLM 结果”解释为已完成且安全。'],
        },
        {
          id: 'execution-and-result',
          title: '执行顺序与结果判断',
          steps: [
            { title: '提交进入 PENDING', body: 'Skill 先入库，前端不等待所有检测同步完成。' },
            { title: '独立分析器并行执行', body: '基础 Scanner 与已选的规则分析、深度扫描、Sandbox 并行运行。' },
            { title: '策略按中间风险补充 Sandbox', body: '命中“必须执行 Sandbox”的风险等级时，即使未手动勾选也会尝试执行。' },
            { title: '汇总风险并可选调用一次 LLM', body: '先形成确定性风险；勾选 LLM 时再做一次语义研判。' },
            { title: '准入策略决定状态', body: '根据最终风险和策略进入 APPROVED、VETTED 或 REJECTED。' },
          ],
          table: {
            columns: ['报告状态', '正确理解'],
            rows: [
              ['completed，有发现项', '分析器执行完成并提供了需要复核的证据'],
              ['completed，无发现项', '本次分析范围内未命中，不代表其他分析器或未触发分支安全'],
              ['skipped / 未勾选', '本次没有执行该能力，不能据此判断风险'],
              ['unavailable / failed', '依赖不可用或执行失败，应先排障再重新检测'],
            ],
          },
          link: { path: '/skills', label: '查看 Skill 报告' },
        },
      ],
    },
    'risk-classification': {
      eyebrow: 'Skill 治理',
      title: '风险项目归类与检测逻辑',
      summary: '把分析器发现项归入阻断项、可疑项或噪声，再结合严重度、判定模式和 LLM 结果形成最终风险。',
      sections: [
        {
          id: 'four-levels',
          title: '先区分四个层次',
          paragraphs: ['报告里的“发现项归类”不是最终风险，也不是最终状态。排查误报或解释审核结果时，应从单条证据逐层看到最终准入结果。'],
          table: {
            columns: ['层次', '回答的问题', '示例'],
            rows: [
              ['发现项与严重度', '某个分析器看到了什么证据？', 'HIGH 的下载后执行规则'],
              ['风险项目归类', '这条证据是阻断项、可疑项还是噪声？', '供应链风险归为阻断项'],
              ['最终风险', '汇总后是 benign、suspicious 还是 malicious？', '平衡模式下 MEDIUM 可疑项形成 suspicious'],
              ['Skill 状态', '系统自动批准、等待审核还是拒绝？', 'APPROVED、VETTED 或 REJECTED'],
            ],
          },
        },
        {
          id: 'classification-meaning',
          title: '阻断项、可疑项和噪声',
          table: {
            columns: ['归类', '含义', '对确定性风险的作用'],
            rows: [
              ['阻断项', '高置信度且不应自动放行的行为证据', '任意一条都会把确定性风险设为 malicious，LLM 不能降级'],
              ['可疑项', '需要结合严重度和判定模式评估的安全信号', 'HIGH 及以上通常至少进入审核；MEDIUM 是否升高取决于判定模式'],
              ['噪声', '依赖、运行环境或已记录示例等诊断信号', '保留在报告中供解释和排障，但不直接抬高确定性风险'],
            ],
          },
          callout: { type: 'note', title: '噪声不是删除发现项', body: '噪声仍保留原始规则、严重度、文件和证据。它只是退出确定性风险升级路径，方便审核人员区分安全问题与运行诊断。' },
        },
        {
          id: 'default-mapping',
          title: '默认风险项目归类',
          table: {
            columns: ['默认归类', '风险项目'],
            rows: [
              ['阻断项', '数据外传、供应链风险'],
              ['可疑项', '提示词注入、工具滥用、网络访问、凭据访问、动态执行、过度权限'],
              ['噪声', '文档中的外部 API 示例、依赖问题、运行环境问题'],
            ],
          },
          paragraphs: ['管理员可以在“策略配置 / 风险判定”中把上述项目移动到其他归类。新的映射会进入扫描上下文；已经完成的历史报告不会被立即重写，需要重新检测后才按新策略产出结果。'],
          link: { path: '/policy', label: '打开策略配置' },
        },
        {
          id: 'classification-order',
          title: '一条发现项如何归类',
          steps: [
            { title: '先识别风险项目', body: '系统按规则 ID、分类、文件位置和证据文本识别数据外传、供应链、提示词注入等项目；文档中的外部 API 示例会先走专门识别。' },
            { title: '应用管理员映射', body: '只要识别到已配置的风险项目，就直接使用该项目当前所在的阻断、可疑或噪声分组。' },
            { title: '执行安全兜底', body: '没有命中配置映射时，下载后执行、凭据或数据外传、绕过治理等明确规则仍归入阻断项。' },
            { title: '过滤诊断噪声', body: '缺少依赖、运行环境问题，以及 LOW 或 MEDIUM 的低可分析性提示归入噪声。' },
            { title: '按严重度完成回退', body: '其余 MEDIUM 及以上发现项归入可疑项；低于 MEDIUM 的剩余项归入噪声。' },
          ],
        },
        {
          id: 'risk-reconciliation',
          title: '归类如何形成最终风险',
          table: {
            columns: ['发现项情况', '严格模式', '平衡模式', '宽松模式'],
            rows: [
              ['存在阻断项', 'malicious', 'malicious', 'malicious'],
              ['可疑项最高为 HIGH / CRITICAL', 'malicious', 'suspicious', 'suspicious'],
              ['可疑项最高为 MEDIUM', 'suspicious', 'suspicious', 'benign'],
              ['只有噪声或低风险项', 'benign', 'benign', 'benign'],
            ],
          },
          paragraphs: ['如果启用了 LLM，它会在确定性归类之后进行一次语义研判。LLM 可以提高风险；平衡或宽松模式下，没有阻断项时也可以降低非阻断风险，并在报告中记录降级原因。严格模式和任何含阻断项的结果都不允许降级。'],
        },
        {
          id: 'admission-result',
          title: '最终风险如何变成 Skill 状态',
          bullets: ['存在阻断型声明约束，例如命中明确禁止权限，会直接 REJECTED。', '最终风险命中“自动拒绝风险”时进入 REJECTED；如果同一风险也配置了人工审核，自动拒绝优先。', '最终风险命中“需要人工审核”时进入 VETTED。', '即使配置缺失或冲突，malicious 仍会拒绝、suspicious 仍会进入审核，只有 benign 才走 APPROVED 的安全兜底。'],
          callout: { type: 'warning', title: '不要只看发现项数量', body: '一条阻断项可以决定确定性风险；大量噪声则不应被简单累加成恶意。审核时应先看归类和证据，再看最终风险与状态。' },
          link: { path: '/docs/skill-policy', label: '继续阅读 Skill 策略配置' },
        },
      ],
    },
    'skill-policy': {
      eyebrow: 'Skill 治理',
      title: 'Skill 策略配置',
      summary: '配置扫描结果复用、风险判定、准入约束、LLM 和 Sandbox，并理解每个字段在当前 Skill 链路中的实际作用。',
      sections: [
        {
          id: 'effective-order',
          title: '策略在检测链路中的生效顺序',
          steps: [
            { title: '确定是否复用结果', body: '内容指纹和扫描上下文都一致且已启用复用时，可以沿用既有报告；策略或分析器配置变化会改变扫描上下文。' },
            { title: '运行已选分析器', body: '规则、深度扫描等先形成中间严重度；中间风险命中强制 Sandbox 等级时，后台会尝试补跑 Sandbox。' },
            { title: '归类并汇总确定性风险', body: '发现项先归入阻断项、可疑项或噪声，再由严格、平衡或宽松模式形成 LLM 前风险。' },
            { title: '可选执行 LLM 研判', body: '模型在其他分析器之后综合内容和证据；阻断项与严格模式的降级保护始终保留。' },
            { title: '执行声明约束和准入处置', body: '工具与许可证规则生成策略提示或阻断，再根据最终风险进入 APPROVED、VETTED 或 REJECTED。' },
          ],
        },
        {
          id: 'page-layout',
          title: '四个配置区域分别做什么',
          table: {
            columns: ['区域', '主要配置', '使用建议'],
            rows: [
              ['风险判定', '结果复用、判定模式、审核/拒绝风险、强制 Sandbox、风险项目归类', '先确定企业风险口径，再调整单个风险项目'],
              ['准入约束', '工具数量、允许工具、禁止权限、许可证和作者信息', '从最小权限开始，用测试 Skill 验证阻断与告警'],
              ['LLM', '启用状态、模型、超时和内容快照上限', '先在模型网关启用可用模型，再开放提交页选项'],
              ['Sandbox', '本地或远程运行、超时、网络、内存、CPU、进程和只读根文件系统', '先测试连接，再把风险等级加入强制 Sandbox'],
            ],
          },
          link: { path: '/policy', label: '打开策略配置' },
        },
        {
          id: 'decision-settings',
          title: '风险判定与处置设置',
          table: {
            columns: ['设置', '当前作用', '需要注意'],
            rows: [
              ['复用相同扫描结果', '内容和扫描上下文一致时复用既有结果', '关闭后再次提交相同内容会重新检测'],
              ['判定模式', '决定非阻断 HIGH / MEDIUM 可疑项如何映射到最终风险', '阻断项在任何模式下都是 malicious'],
              ['需要人工审核', '命中的最终风险进入 VETTED', '默认包含 suspicious'],
              ['自动拒绝风险', '命中的最终风险进入 REJECTED', '与人工审核冲突时自动拒绝优先'],
              ['必须执行 Sandbox', '中间风险命中所选等级时尝试补跑 Sandbox', '依赖必须已启用且可连接，跳过或失败不等于安全'],
              ['风险项目归类', '把 11 类风险项目分到阻断、可疑或噪声', '改变后只影响后续重新检测，不会改写历史报告'],
            ],
          },
          link: { path: '/docs/risk-classification', label: '查看归类与风险计算细节' },
        },
        {
          id: 'admission-settings',
          title: '工具与许可证约束',
          table: {
            columns: ['设置或命中', '当前结果'],
            rows: [
              ['声明工具超过数量上限', '记录非阻断策略告警'],
              ['声明工具不在允许列表', '记录非阻断策略告警，并把声明工具校验标记为无效'],
              ['声明命中禁止权限', '生成阻断型违规并直接拒绝'],
              ['要求许可证但 SKILL.md 未声明', '记录非阻断策略告警'],
              ['许可证不在接受列表', '记录非阻断策略告警'],
            ],
          },
          callout: { type: 'note', title: '先验证 SKILL.md 声明', body: '这些约束读取 SKILL.md frontmatter 中的 allowed-tools / allowed_tools 和 license。它们检查声明是否符合策略，不能代替对代码真实行为的规则、深度或 Sandbox 检测。' },
        },
        {
          id: 'analyzer-settings',
          title: 'LLM 与 Sandbox 配置',
          bullets: ['LLM 区域控制系统是否允许 Skill LLM 分析、使用哪个模型，以及超时、文件数量、单文件字符数和清单字符数上限。模型必须已在模型网关启用。', 'Sandbox 区域选择远程隔离服务或本地 Docker runtime，并限制网络、内存、CPU、进程数量、执行时长和根文件系统写入。', '“启用”只代表能力可以被选择或调用；报告中的 completed、skipped、unavailable 和 failed 才说明某次检测实际发生了什么。', '保存前先执行 Sandbox 连接测试；LLM 则用不含敏感数据的测试 Skill 验证模型可用性、超时和快照范围。'],
        },
        {
          id: 'current-boundaries',
          title: '当前生效边界',
          paragraphs: ['策略页仍保留少量兼容字段，但不能把“页面可保存”理解成“已经参与 Skill 放行”。当前 Skill 状态以自动拒绝、人工审核和安全兜底为准。'],
          bullets: ['“自动批准最高风险”当前只用于 Prompt 自动批准判断，不参与 Skill 的 APPROVED、VETTED 或 REJECTED 计算。', '“可信作者”当前会保存，但没有进入 Skill 检测或自动放行逻辑；把作者加入列表不会免检，也不会绕过人工审核。', '许可证缺失、不在接受列表、工具数量超限和工具不在允许列表目前都是非阻断告警；只有命中明确禁止权限会直接形成阻断型违规。'],
          callout: { type: 'warning', title: '不要用兼容字段作为安全承诺', body: '在实现正式接入 Skill 判定前，不要依赖“自动批准最高风险”或“可信作者”设计准入流程。以实际报告、最终风险和状态为准。' },
        },
        {
          id: 'change-workflow',
          title: '安全地调整策略',
          steps: [
            { title: '记录变更目标', body: '明确要减少哪类误报、增加哪类阻断，以及预期影响的 Skill。' },
            { title: '先用代表性样本验证', body: '至少准备一个应批准、一个应审核和一个应拒绝的测试 Skill。' },
            { title: '保存并重新检测', body: '策略不会改写已经完成的历史报告；对目标版本发起重新检测，确认新扫描上下文生效。' },
            { title: '核对完整证据链', body: '同时检查发现项归类、LLM 前风险、LLM 研判、最终风险、策略告警和最终状态。' },
          ],
          link: { path: '/skills', label: '打开 Skill 列表并重新检测' },
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
            { title: '创建网关凭证', body: '限制允许访问的网关、IP、请求大小和并发。' },
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
          id: 'credentials-and-debug',
          title: '凭证与调试边界',
          bullets: ['MCP 网关凭证必须选择允许访问的网关，默认权限为 mcp:connect、mcp:list-tools 和 mcp:call-tools。', '先用 MCP 调试确认 Tool 发现和参数 Schema，再把同一网关地址与凭证交给实际 MCP Client。', '上游默认只允许 HTTPS；需要 HTTP 时必须由部署管理员显式允许，并用出站允许列表限制目标。', '调试成功只证明当前凭证和参数可调用，不会绕过高风险审批或后续 Schema 变化。'],
          link: { path: '/mcp-governance/debug', label: '打开 MCP 调试' },
        },
        {
          id: 'audit',
          title: '审批与调用审计',
          paragraphs: ['高风险调用首次返回审批申请，而不是已经执行成功。审批页面默认展示脱敏参数；查看原始参数会写入安全审计。批准后，原凭证可以在授权有效期内使用同一 Tool 和 Schema；调用审计用于追踪来源、结果、耗时和错误。'],
          bullets: ['拒绝或审批过期后，调用方必须重新发起请求。', 'Tool Schema 变化后旧授权不自动覆盖新 Schema，应重新保存网关并按新定义审批。', '审批记录中的“已批准”不等于上游执行成功，仍需在调用审计确认结果。'],
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
            { title: '创建 Agent', body: '设置稳定且唯一的 Agent ID、名称、所属部门、负责人、客户端类型和启用状态。运行环境中的 Agent ID 必须与这里一致。' },
            { title: '绑定能力', body: '选择默认模型和允许使用的已批准或已部署 Skill。下拉项会显示具体 Skill 标识；保存后运行校验按该 Agent 的绑定范围判断。' },
            { title: '创建运行凭证', body: '在统一凭证中心选择 Agent 运行凭证并绑定目标 Agent。' },
            { title: '交给运行环境', body: '只把一次性显示的凭证明文交给对应 Agent，不能使用管理员登录 Token。' },
          ],
          link: { path: '/agents', label: '打开智能体列表' },
        },
        {
          id: 'status-and-binding',
          title: '状态、绑定和凭证分别控制什么',
          table: { columns: ['控制项', '作用', '常见误区'], rows: [
            ['Agent 状态', 'active 才应承接正式运行；disabled 或 draft 不代表已删除', '禁用状态不能用删除或凭证吊销来推断'],
            ['Skill 绑定', '定义该 Agent 被允许加载的 Skill 范围', 'Skill 已批准不等于所有 Agent 都可加载'],
            ['Agent 运行凭证', '从凭证中建立可信 Agent 身份并授予运行权限', '请求 metadata.agent_id 不能替代凭证绑定'],
            ['默认模型', '为 Agent 档案提供默认模型选择', '仍需要凭证具备 model:chat 且模型可用'],
          ] },
          link: { path: '/docs/credential-management', label: '阅读统一凭证中心' },
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
          paragraphs: ['客户端默认识别Claude Code、Codex、Gemini CLI、OpenCode、OpenClaw、Hermes、TRAE CN、TRAE、Cursor、CodeBuddy、WorkBuddy等内置Agent，并单独标记可由多个Agent读取的共用Skills目录；未内置的工具可以添加为自定义Agent。'],
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
    'credential-management': {
      eyebrow: '智能体管理',
      title: '统一凭证中心',
      summary: '按调用主体选择凭证类型、绑定对象和最小权限，并限制模型、网关、来源 IP、请求大小与并发。',
      sections: [
        {
          id: 'credential-types',
          title: '不同接入凭证类型与用途',
          table: { columns: ['凭证类型', '必须绑定或限制', '默认用途'], rows: [
            ['Agent 运行凭证', '必须绑定一个 Agent', '验签、加载许可和 Tool 调用检查；可选治理、记忆或模型调用权限'],
            ['Scanner 接入凭证', '只读取自己提交的结果', '批量上传 Skill 和轮询自己的扫描结果'],
            ['Client 接入凭证', '注册后关联具体客户端', '注册、心跳、策略、任务、清单、事件和批准版本下载'],
            ['模型调用凭证', '可限制允许模型', '调用模型网关；可选 Token 压缩和 Prompt 防护'],
            ['MCP 网关凭证', '必须选择允许访问的网关', '连接、发现和调用已发布 MCP Tool'],
          ] },
        },
        {
          id: 'create',
          title: '创建凭证的正确顺序',
          steps: [
            { title: '先创建被绑定对象', body: 'Agent 运行凭证要先创建 Agent；MCP 凭证要先创建网关。不要用空绑定绕过身份边界。' },
            { title: '选择类型和预设', body: 'Agent 运行凭证优先使用“运行校验”“治理”或“治理 + 模型”预设，再按实际需要收窄权限。' },
            { title: '设置资源边界', body: '按类型限制 Agent、MCP 网关、模型、允许 IP / CIDR、请求体或上传大小，以及请求或任务并发。' },
            { title: '保存并立即复制', body: '明文只在创建后展示一次。写入调用方的安全配置后关闭窗口，不要放进源码、截图或普通日志。', expected: '列表只显示凭证前缀、类型、绑定、权限和状态，不再显示完整明文。' },
          ],
          link: { path: '/credentials', label: '打开统一凭证中心' },
        },
        {
          id: 'model-controls',
          title: '带 model:chat 的凭证',
          bullets: ['模型调用凭证默认包含 model:chat；Agent 运行凭证只有显式选择“治理 + 模型”或手工添加后才能调用模型。', '可限制允许模型；列表为空表示不在凭证层限定模型，不代表绕过模型启用状态或组策略。', 'Token 压缩级别和 Prompt 防护模式跟随凭证；Prompt 防护可选关闭、记录、警告或阻断。', '请求仍要通过凭证状态、绑定、模型范围、请求大小、来源 IP 和并发校验。'],
        },
        {
          id: 'lifecycle',
          title: '吊销、删除与排障',
          table: { columns: ['操作或现象', '正确处理'], rows: [
            ['明文丢失', '吊销旧凭证并创建新凭证，不能恢复原文'],
            ['调用方退役或疑似泄露', '先吊销阻止继续使用，再更新调用方并核对审计'],
            ['403', '核对凭证类型、权限、Agent或网关绑定、允许模型和来源 IP'],
            ['429', '核对最大并发请求或 Scanner 最大并发任务'],
            ['请求或上传被拒绝', '核对请求体大小或最大上传大小，避免直接放宽到不受控值'],
          ] },
          link: { path: '/docs/audit-trail', label: '继续阅读审计追踪' },
        },
      ],
    },
    'audit-trail': {
      eyebrow: '智能体管理',
      title: '审计追踪',
      summary: '按时间、事件类型和关键词追踪 Skill 提交审核、运行校验、Tool 调用和客户端处置，区分请求、失败、阻断与成功。',
      sections: [
        {
          id: 'what-is-recorded',
          title: '当前可以查询哪些事件',
          table: { columns: ['链路', '常见事件'], rows: [
            ['Skill 治理', '提交、开始分析、分析完成、进入审核、批准、拒绝'],
            ['运行校验', '完整性校验通过、允许或阻止加载、发现内容不一致'],
            ['Tool 治理', '允许或阻止 Tool 调用'],
            ['客户端治理', '发现未受管 Skill、内容修改、恢复、阻断、隔离、安装和移除'],
          ] },
        },
        {
          id: 'query',
          title: '怎样定位一次事件',
          steps: [
            { title: '选择时间范围', body: '页面提供最近 24 小时、7 天和 30 天。先覆盖事件发生时间，避免把“查不到”误认为“没有发生”。' },
            { title: '选择事件类型', body: '先用阻断、内容不一致、审核或客户端处置等稳定事件类型缩小范围。' },
            { title: '使用关键词', body: '按 Skill、Agent、凭证 Actor 或事件详情中的关键值查询。' },
            { title: '交叉核对', body: '同时查看时间、事件、Skill、Agent、来源 IP、凭证 / Actor 和详情；Skill 有 ID 时可以跳转到详情。' },
          ],
          link: { path: '/audit', label: '打开审计追踪' },
        },
        {
          id: 'interpretation',
          title: '不要把一条记录过度解读',
          bullets: ['“开始分析”只表示任务启动，不代表检测成功；继续寻找“分析完成”和最终状态。', '“完整性校验通过”只证明内容匹配可信版本，还要确认加载许可。', '“允许加载”不等于后续每个 Tool 都已授权；Tool 调用需要自己的允许或阻止事件。', '客户端任务已下发不等于已执行；应结合客户端详情中的任务状态和最新事件。', '模型隐私链路和 MCP 调用还有各自的专用审计页面；统一审计不能替代原始链路详情。'],
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
            { title: '签发模型调用凭证', body: '限制允许模型、请求大小和并发；也可以只为指定凭证启用压缩。' },
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
          paragraphs: ['供应商可以全局启用压缩；带 model:chat 的模型调用凭证或 Agent 运行凭证也可以单独启用，并选择 auto、conservative 或 aggressive。只在供应商启用而凭证未指定级别时使用 auto。平台在调用上游前处理 messages，并记录压缩前后 Token、节省量、压缩比例和耗时。'],
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
          table: {
            columns: ['资源项', '生产环境推荐基线', '容量规划说明'],
            rows: [
              ['CPU', '16 vCPU', '承载Backend、扫描分析、Sandbox调度和并发请求；提高扫描并发时同步扩容。'],
              ['内存', '32 GiB', '为Worker、分析器、Sandbox服务和容器页缓存预留空间；高并发动态检测时按峰值扩容。'],
              ['磁盘', '500 GiB可用容量，优先SSD/NVMe', '保存镜像、Skill包、版本内容、报告、审计、客户端发布文件和日志；Skill越多、版本留存越久，容量需求越大。'],
            ],
          },
          code: 'uname -m\ndocker --version\ndocker compose version',
          callout: { type: 'note', title: '容量规划边界', body: '以上是单节点生产部署的推荐初始规格，不是最低门槛。共享8 vCPU隔离测试节点已经完成单节点基准，用于识别SQLite写并发和扫描队列的容量拐点；生产仍建议保留更高资源余量。详见“性能与容量”。' },
          link: { path: '/docs/performance-benchmark', label: '查看性能与容量实测' },
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
    'performance-benchmark': {
      eyebrow: '部署与运维',
      title: '性能基准与容量边界',
      summary: '基于隔离环境的实测数据设置单节点并发、扫描Worker、Skill容量和客户端巡检参数。',
      sections: [
        { id: 'environment', title: '测试环境与口径', table: { columns: ['项目', '本次环境'], rows: [['服务器', 'VMware共享虚拟机，8 vCPU，Intel Xeon E5-2678 v3 @ 2.50 GHz'], ['内存与磁盘', '31 GiB内存；195 GiB ext4，测试时可用约49 GiB'], ['系统', 'Ubuntu 24.04.4 LTS，Linux 6.8.0-137-generic，x86_64'], ['Docker', 'Client 28.5.2、Server 29.1.3、Compose v5.0.1、overlay2、cgroup v2'], ['版本', 'Backend dev-d6ec8a5b，单Uvicorn进程，SQLite WAL'], ['扫描配置', 'Scan Worker 2、分析器Worker 8、深度扫描并发2；Sandbox 1 CPU / 512 MiB']] }, bullets: ['使用独立Backend、SQLite、Registry、Sandbox和Docker网络，没有向现有平台写入测试数据。', '模型与MCP使用固定50 ms的本地模拟上游，结果主要反映平台链路；不包含外部模型生成和真实Tool业务耗时。', '“稳定”表示本轮没有错误或超时，不代表完成了长时间Soak、多实例或故障注入测试。'] },
        { id: 'recommended', title: '生产环境参数基线', paragraphs: ['本节给出单节点新部署的推荐初始参数，用于建立可观测、可逐级调优的生产配置基线。这些数值不代表系统容量上限或每秒请求数。部署后应使用真实业务负载验证延迟、错误率和资源利用率，再依据监控结果逐级调整。'], bullets: ['最大并发：同一时刻允许多少个尚未完成的请求。最大并发为5时，第6个同时到达的请求会被限流；不表示每秒只能处理5个请求。', '吞吐量（req/s）：每秒实际完成的请求数。提高最大并发不一定提高吞吐。', 'P95延迟：95%的请求在该时间以内完成，比平均值更能反映大多数用户遇到的慢请求。'], callout: { type: 'note', title: '推荐初始并发的依据', body: '模型网关并发从5提高到10后，实测吞吐没有继续增长，P95却从391.31 ms升至758.27 ms。因此将5设为推荐初始值，是为了在吞吐、延迟和突发余量之间取得平衡，并不表示系统最多只能处理5个请求。' } },
        { id: 'starting-values', title: '可配置参数与推荐初始值', table: { columns: ['设置项', '控制范围', '推荐初始值', '配置位置', '达到上限后的行为'], rows: [['模型网关凭证最大并发请求数', '同一模型API Key尚未完成的请求', '5', '模型网关的API Key新建或编辑页面', '新请求返回并发限制，已开始的请求继续执行'], ['MCP接入凭证最大并发请求数', '同一接入凭证的MCP请求', '5', '凭证管理的新建或编辑页面', '新请求返回429，是凭证级第一层限制'], ['单个MCP Tool最大并发', '指定Tool同时执行的调用', '5', 'MCP网关的Tool安全策略', '超出的调用返回JSON-RPC并发限制，不调用上游Tool'], ['Scan Worker', '同时处理的后台Skill检测任务', '2', 'Docker .env中的AGENT_MANAGER_SCAN_WORKERS', '提交可被接受，超出的任务在后台排队'], ['分析器Worker', '检测任务共用的静态规则和结构分析线程', '8', 'Docker .env中的AGENT_MANAGER_ANALYZER_WORKERS', '过小会延长检测；过大可能造成CPU争用'], ['深度扫描并发', '同时执行的深度扫描', '2', 'Docker .env中的深度扫描并发项', '超出的深度扫描等待可用槽位']] }, paragraphs: ['MCP Tool同时受凭证并发和Tool并发两层限制，实际并发取两者中较小的值。例如凭证为5、Tool为10时最多同时执行5个；凭证为10、Tool为5时最多同时执行5个。', '扫描参数的作用不同：Scan Worker控制同时处理多少个Skill，分析器Worker控制检测内部的共享线程，深度扫描并发限制资源开销更大的深度分析。三者不能相乘换算成吞吐。推荐初始组合为2 / 8 / 2，用于降低批量提交造成CPU、SQLite写入和临时空间同时出现资源尖峰的风险。'] },
        { id: 'tuning', title: '什么时候以及怎样调高', steps: [{ title: '先跑真实负载', body: '使用真实模型、真实MCP Tool和接近生产大小的Skill，按初始值连续运行30–60分钟。' }, { title: '观察关键指标', body: '记录P95、错误率、429或JSON-RPC限流、上游超时、CPU、内存、SQLite锁等待、磁盘IOPS和临时空间。' }, { title: '一次只改一个参数', body: '网关并发可按5 → 8 → 10逐级提高；扫描并发每次只增加1，然后重新测试。' }, { title: '识别容量拐点', body: '如果吞吐没有提高，但P95、超时或资源占用上升，应退回上一档，说明瓶颈不在并发上限。' }, { title: '处理20+并发需求', body: '先验证外部数据库或存储、多进程或多实例、审计写入路径和长时间稳定性，不能只把页面参数改成100。' }], callout: { type: 'warning', title: '表中还有两类数字不是配置项', body: '“运行时验签调用端并发不超过10”是集成方的调用建议；“50,000个Skill”是容量验证规模。它们都不能在管理台填写，详见后面的验签和Skill容量实测。' } },
        { id: 'gateways', title: '网关阶梯结果', table: { columns: ['场景', '并发', '成功/请求', '吞吐', 'P95'], rows: [['模型网关', '5', '40/40', '16.28 req/s', '391.31 ms'], ['模型网关', '10', '40/40', '15.23 req/s', '758.27 ms'], ['模型网关', '20', '0/40', '0', '30秒超时'], ['MCP initialize', '10', '20/20', '103.76 req/s', '115.07 ms'], ['MCP tools/list', '10', '20/20', '75.01 req/s', '156.18 ms'], ['MCP tools/call', '5', '20/20', '7.66 req/s', '699.39 ms'], ['MCP tools/call', '10', '20/20', '7.96 req/s', '1,324.51 ms'], ['MCP tools/call', '20', '0/40', '0', '30秒超时']] }, paragraphs: ['真实模型供应商的排队、首Token和生成耗时，以及真实MCP Tool的业务耗时，需要叠加到上述结果。模型网关还应按实际隐私检测、Prompt防护、Token压缩和流式响应配置复测。'] },
        { id: 'skill-performance', title: 'Skill检测与验签', table: { columns: ['场景', '并行提交', '接口接受P95', '完成P95', '报告扫描P95'], rows: [['规则扫描（热态）', '1', '129.44 ms', '293.40 ms', '22.66 ms'], ['规则扫描（热态）', '4', '554.28 ms', '797.83 ms', '21.98 ms'], ['深度扫描', '1', '5.76 s', '11.99 s', '6.08 s'], ['深度扫描', '4', '381.44 ms', '12.81 s', '6.22 s'], ['Sandbox小型Python入口', '1', '71.13 ms', '411.49 ms', '186.58 ms']] }, bullets: ['深度扫描并行4时按并发2分两批执行，完成P95约12.8秒。', 'Sandbox样例非常小；复杂入口、依赖、超时和远程网络会改变结果。', '本轮没有调用外部LLM，不把模拟数据当作真实LLM分析性能。', '运行时验签并发1/2/5/10/20/40的P95分别为39.83/74.13/192.18/376.35/881.90/1,446.71 ms。'] },
        { id: 'capacity-client', title: 'Skill容量与客户端开销', paragraphs: ['隔离Registry加载50,000个合成Skill家族后，SQLite约59.97 MiB；首屏列表P95 75.82 ms、中页111.01 ms、名称搜索89.03 ms、仪表盘聚合145.34 ms。合成数据不含真实包体、多版本、扫描报告和审计，不能据此估算生产磁盘。'], table: { columns: ['客户端本地Skill', 'Inventory P50', 'Inventory P95', 'Inventory JSON', '峰值RSS'], rows: [['100', '86.87 ms', '94.74 ms', '21.40 KiB', '15.0–15.8 MiB'], ['500', '239.86 ms', '245.01 ms', '104.99 KiB', '15.9–16.5 MiB'], ['1,000', '414.51 ms', '439.15 ms', '210.46 KiB', '16.7–17.1 MiB']] }, callout: { type: 'note', title: '客户端消耗在哪里', body: 'Inventory在客户端本机遍历Agent Skill目录、读取元数据、生成清单并写入本地SQLite，因此CPU、磁盘读取和内存主要消耗在客户端。平台承担上报、策略与任务下发和服务端检测，资源仍会随客户端数量和任务量增长。' } },
        { id: 'production', title: '生产使用建议', bullets: ['继续以16 vCPU、32 GiB、500 GiB SSD/NVMe作为单节点生产初始基线，本次8 vCPU共享机结果不用于下调规格。', '模型凭证、MCP凭证和Tool并发先设为5；根据P95、错误率、SQLite锁等待和审计增长逐级调整。', '保持Scan Worker 2和深度扫描并发2起步，提高前评估CPU、内存、Sandbox和磁盘临时空间。', '避免大量客户端在同一时刻执行全量巡检或上报。', '上线前用真实Skill、模型、MCP Tool和目标客户端系统做30–60分钟稳态测试；Linux客户端结果不能替代macOS或Windows。'] },
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
    { title: 'Capability governance', items: [
      { subgroup: 'Skill governance', slug: 'skill-governance', title: 'Governance flow', summary: 'Submission, scanning, review, and versions' },
      { subgroup: 'Skill governance', slug: 'scanner-access', title: 'Scanner access', summary: 'Discover, precheck, and upload local Skills in batches' },
      { subgroup: 'Skill governance', slug: 'scan-capabilities', title: 'Scanning capabilities', summary: 'Rules, deep scan, Sandbox, and LLM analysis' },
      { subgroup: 'Skill governance', slug: 'risk-classification', title: 'Finding classification', summary: 'Blocking, suspicious, noise, and final risk' },
      { subgroup: 'Skill governance', slug: 'skill-policy', title: 'Policy settings', summary: 'Risk decisions, admission constraints, and analyzers' },
      { subgroup: 'MCP governance', slug: 'mcp-governance', title: 'MCP governance', summary: 'Servers, gateways, approvals, and audits' },
    ] },
    { title: 'Agent management', items: [
      { slug: 'agent-management', title: 'Agent management', summary: 'Agent records, capability bindings, and credentials' },
      { slug: 'client-management', title: 'Client management', summary: 'Local Agent discovery, Skill delivery, and continuous inspection' },
      { slug: 'credential-management', title: 'Credential center', summary: 'Issue least-privilege credentials by caller' },
      { slug: 'runtime-integration', title: 'Access and runtime', summary: 'Skill Verifier, event Hooks, and result handling' },
      { slug: 'audit-trail', title: 'Audit trail', summary: 'Query Skill, Agent, Client, and Tool events' },
    ] },
    { title: 'Model gateway', items: [
      { slug: 'model-gateway', title: 'Model gateway', summary: 'Model access, privacy controls, and token compression' },
    ] },
    { title: 'System administration', items: [
      { slug: 'system-management', title: 'System management', summary: 'Users, permissions, and system status' },
    ] },
    { title: 'Deploy and operate', items: [
      { slug: 'docker-deployment', title: 'Docker deployment', summary: 'Run the same Compose stack online or offline' },
      { slug: 'performance-benchmark', title: 'Performance and capacity', summary: 'Measured gateway, Skill, and Client capacity in an isolated environment' },
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
        { id: 'capability-map', title: 'Choose a feature by goal', table: { columns: ['Goal', 'Module'], rows: [['Submit and scan a Skill', { label: 'Skill governance / Submit Skill', path: '/docs/skill-governance' }], ['Batch-import Skills from a host or CI', { label: 'Scanner access', path: '/docs/scanner-access' }], ['Choose scan methods and interpret results', { label: 'Skill scanning capabilities', path: '/docs/scan-capabilities' }], ['Understand blocking, suspicious, and noise findings', { label: 'Finding classification', path: '/docs/risk-classification' }], ['Configure Skill risk and admission rules', { label: 'Skill policy settings', path: '/docs/skill-policy' }], ['Review a suspicious Skill', { label: 'Skill governance / Skill Review', path: '/docs/skill-governance' }], ['Restrict an Agent to specific Skills', { label: 'Agent management / Bindings and credentials', path: '/docs/agent-management' }], ['Issue least-privilege credentials by caller', { label: 'Credential center', path: '/docs/credential-management' }], ['Add signature and Tool checks to an Agent', { label: 'Agent runtime integration', path: '/docs/runtime-integration' }], ['Discover local Agents and Skill roots', { label: 'Client management / Agent Discovery', path: '/docs/client-management' }], ['Deliver, restore, or remove Skills on managed hosts', { label: 'Client management / Console operations', path: '/docs/client-management' }], ['Protect private model input', { label: 'Model gateway / Privacy policies', path: '/docs/model-gateway' }], ['Compress model context and measure savings', { label: 'Model gateway / Token compression', path: '/docs/model-gateway' }], ['Analyze token usage by user', { label: 'Model gateway / User token analytics', path: '/docs/model-gateway' }], ['Audit anomalous Skills declared in model calls', { label: 'Model gateway / Skill Alerts', path: '/docs/model-gateway' }], ['Publish and audit MCP Tools', { label: 'MCP governance / Servers and gateways', path: '/docs/mcp-governance' }], ['Trace Skill, Agent, Client, and Tool events', { label: 'Audit trail', path: '/docs/audit-trail' }]] } },
      ],
    },
    'quick-start': {
      eyebrow: 'Get started', title: 'Complete your first Skill governance flow', summary: 'Use a test ZIP with no production secrets or personal data to complete submission, scanning, review, Agent authorization, and runtime verification.',
      sections: [
        { id: 'check-system', title: '1. Check platform status', paragraphs: ['Open the dashboard and system overview first. LLM and Sandbox checks depend on administrator configuration; unavailable checks remain disabled on the submission page.'], image: { name: 'dashboard', alt: 'Platform dashboard', caption: 'The dashboard highlights pending Skills, risk distribution, and recent events.' }, link: { path: '/dashboard', label: 'Open dashboard' } },
        { id: 'submit-zip', title: '2. Upload a ZIP and select Skills', paragraphs: ['The current console supports ZIP upload and Scanner access. The platform parses importable Skills first, then lets you choose which entries to submit.'], steps: [{ title: 'Choose a ZIP', body: 'Each Skill directory must contain SKILL.md.' }, { title: 'Parse content', body: 'Confirm the directories and Skills found by the platform.' }, { title: 'Choose checks and submit', body: 'Do not force-enable an unavailable dependency.', expected: 'The result starts as PENDING while background checks continue.' }], image: { name: 'submit-skill', alt: 'Submit Skill page', caption: 'Upload a ZIP, parse its content, and select the Skills to scan.' }, link: { path: '/submit', label: 'Open Submit Skill' } },
        { id: 'review-result', title: '3. Read the report and decide', paragraphs: ['Review final risk, evidence, analyzer results, files, and version history. VETTED needs human review, APPROVED is trusted, and REJECTED does not enter the review queue.'], image: { name: 'skill-list', alt: 'Skill list page', caption: 'The list shows the latest content version, trusted version, status, and risk.' }, link: { path: '/skills', label: 'Open Skill list' } },
        { id: 'verify-runtime', title: '4. Connect an Agent and verify local content', paragraphs: ['Create an Agent, bind approved Skills, issue an Agent-bound runtime credential, and run Skill Verifier before the Agent uses local content.'], callout: { type: 'note', title: 'Verification order', body: 'Verify the local content digest first, then check the current Agent load permission. With an event Hook, also check Tool permission before Tool execution.' }, image: { name: 'runtime', alt: 'Access and Runtime page', caption: 'Runtime audit shows signature, load, tamper, and Tool events.' }, link: { path: '/runtime', label: 'Open Access & Runtime' } },
        { id: 'next-paths', title: '5. Continue based on your integration', paragraphs: ['This page covers only the first Skill governance flow. Choose a runtime verification method first, then configure the Client, Model Gateway, or MCP Gateway as required.'], table: { columns: ['Next goal', 'Continue with'], rows: [['Understand rules, deep scan, Sandbox, and LLM differences', { label: 'Skill scanning capabilities', path: '/docs/scan-capabilities' }], ['Batch-discover and submit Skills from servers or CI', { label: 'Scanner access', path: '/docs/scanner-access' }], ['Understand how findings become final risk', { label: 'Finding classification', path: '/docs/risk-classification' }], ['Configure enterprise risk and admission constraints', { label: 'Skill policy settings', path: '/docs/skill-policy' }], ['Embed checks into Agent load and Tool-call flows', { label: 'Agent runtime integration', path: '/docs/runtime-integration' }], ['Govern local Skills across multiple hosts', { label: 'Client management', path: '/docs/client-management' }], ['Protect model requests and measure token savings', { label: 'Model gateway', path: '/docs/model-gateway' }], ['Publish MCP Tools through controlled gateways', { label: 'MCP governance', path: '/docs/mcp-governance' }]] } },
      ],
    },
    'skill-governance': {
      eyebrow: 'Skill governance', title: 'Skill governance', summary: 'Manage submission, scanning, policy decisions, human review, and trusted Skill versions.',
      sections: [
        { id: 'submission', title: 'Submission methods', table: { columns: ['Method', 'Use case', 'Current status'], rows: [['ZIP upload', 'Submit one or more Skills in the console', 'Available'], ['Scanner access', 'Discover and upload local Skills from customer hosts or CI', 'Available']] }, callout: { type: 'note', title: 'Choose the right entry point', body: 'Use ZIP for small manual submissions and Scanner access for continuous discovery across customer hosts, servers, or CI.' } },
        { id: 'pipeline', title: 'Scanning and decisions', paragraphs: ['A submission starts as PENDING. Enabled analyzers run in the background, and policy produces the final governance decision. No single Sandbox or LLM result replaces the final assessment.'], bullets: ['Static and rule analysis inspect files, permissions, and dangerous patterns.', 'Sandbox observes behavior triggered in a restricted run.', 'LLM may combine content and analyzer evidence when configured.', 'Policy routes the result to auto-approval, human review, or rejection.'], diagram: 'governance', link: { path: '/docs/scan-capabilities', label: 'Understand each scanning capability' } },
        { id: 'states', title: 'States and next actions', table: { columns: ['State', 'Meaning', 'Next action'], rows: [['PENDING', 'Background checks are running', 'Wait or inspect scan runs'], ['VETTED', 'Checks complete; human review required', 'Approve or reject'], ['APPROVED', 'Trusted version approved', 'Bind to an Agent or install'], ['REJECTED', 'Rejected', 'Fix content and submit a new version'], ['DEPLOYED', 'In managed deployment', 'Continue integrity checks and audits']] } },
        { id: 'review-workflow', title: 'What to inspect during human review', steps: [{ title: 'Confirm analyzer completeness', body: 'Check whether each analyzer is completed, skipped, unavailable, or failed. Missing output is not no risk.' }, { title: 'Inspect raw evidence', body: 'Start with blocking and suspicious findings, then open files, lines, raw reports, and Sandbox output to verify actual behavior.' }, { title: 'Compare declarations and behavior', body: 'Compare purpose, allowed-tools, and license in SKILL.md with network, credential, dynamic-execution, and write behavior in code.' }, { title: 'Approve or reject', body: 'Only VETTED enters the review queue. Approval creates a trusted signed version; rejected content should be fixed and submitted as a new version.', expected: 'The action, reviewer, and result are queryable in Audit trail.' }], link: { path: '/review', label: 'Open Skill Review' } },
        { id: 'versions', title: 'Reports and versions', bullets: ['Read final risk, functional summary, evidence, attack chain, and framework mappings.', 'Inspect independent Scanner, rule, LLM, and Sandbox results.', 'Open stored files and raw reports instead of relying only on summaries.', 'Compare two content versions of the same Skill.', 'Rescan creates a new scan run; changed content must be submitted as a new version.'], link: { path: '/skills', label: 'Open Skill list' } },
      ],
    },
    'scan-capabilities': {
      eyebrow: 'Skill governance', title: 'Skill scanning capabilities', summary: 'Understand what the base Scanner, rule analysis, deep scan, Sandbox, and LLM analysis inspect, when each is available, and how they contribute to the final decision.',
      sections: [
        {
          id: 'capability-overview', title: 'How rules, deep scan, Sandbox, and LLM differ',
          paragraphs: ['These capabilities are complementary, not interchangeable scan levels. Static analysis finds broad signals, Sandbox observes only behavior triggered by one controlled run, and LLM performs a final semantic assessment from content and collected evidence. Risk reconciliation and admission policy still determine the final state.'],
          table: { columns: ['Capability', 'Availability', 'Primary output'], rows: [
            ['Base Scanner', 'Starts for every submission; the runtime should provide Scanner', 'Whole-directory static rules, permissions, and known dangerous patterns'],
            ['Rule analysis (selected by default)', 'Keep Start rule analysis selected at submission', 'Text rules, Python AST, suspicious behavior intent, and file locations'],
            ['Deep scan', 'The runtime supports deep scanning and the option is selected', 'Detailed static findings, risk score, and raw report'],
            ['Sandbox', 'Enabled and reachable, or required by risk policy', 'Entrypoint, arguments, output, exit code, timeout, and runtime signals'],
            ['LLM analysis', 'Enabled with a selected model and requested at submission', 'Semantic risk, report, evidence decisions, and attack chain'],
          ] },
          image: { name: 'submit-skill', alt: 'Choose Skill scanning capabilities at submission', caption: 'Rule analysis is selected by default. Deep scan, Sandbox, and LLM are selectable only when their dependencies are available.' },
          link: { path: '/submit', label: 'Open Submit Skill' },
        },
        {
          id: 'rule-analysis', title: 'Base Scanner and rule analysis',
          paragraphs: ['The base Scanner covers the whole Skill directory and starts for every scan. Start rule analysis, selected by default on the submission page, adds Agent Manager local rules over scripts, references, prompts, other text code files, and Python AST. Neither layer executes the Skill.'],
          bullets: ['Key signals include prompt injection, system-prompt leakage, hidden instructions, data exfiltration, credential access, download-and-execute patterns, dynamic execution, and excessive permissions.', 'Reports include rule, severity, file, and line evidence. A hit requires review; one rule does not directly determine the final state.', 'If the base Scanner is unavailable or fails, other analyzers may continue, but the report should show the error and coverage is reduced.'],
          callout: { type: 'note', title: 'Behavioral does not mean dynamic execution', body: 'The implementation internally calls the added rule bundle behavioral, but it currently performs text-pattern and AST static analysis. Only Sandbox executes a Skill probe.' },
        },
        {
          id: 'deep-scan', title: 'Deep scan',
          paragraphs: ['Deep scan performs more detailed static inspection across the Skill and stores effective severity, findings, risk score, and the raw report. Use it for third-party or complex Skills, or when base rules need additional evidence.'],
          bullets: ['The option is enabled only when the runtime supports deep scanning.', 'Deep scan does not currently call a model. Select LLM analysis separately when semantic assessment is required.', 'Unavailable, timed-out, or failed scans appear in analyzer status and deep-scan results. No report must not be interpreted as no risk.'],
        },
        {
          id: 'sandbox', title: 'Sandbox: observe triggered runtime behavior',
          paragraphs: ['Sandbox uses the local Docker runtime or remote isolated service, finds one real .py, .sh, or .js entrypoint, and runs one default probe. CLI-like scripts usually receive --help; other entrypoints receive no arguments. The current pipeline does not execute command blocks from SKILL.md or ask an LLM to generate extra probes.'],
          bullets: ['Inspect runtime, image or remote service, entrypoint, arguments, stdout, stderr, exit code, timeout, network attempts, and extracted signals.', 'A user may select Sandbox at submission. Policy may also add it when interim risk matches a configured mandatory Sandbox level.', 'No supported entrypoint causes a skip. Missing dependencies, missing input, and a non-zero exit may be diagnostics rather than security findings.'],
          callout: { type: 'warning', title: 'Sandbox is not proof of safety', body: 'If one probe does not trigger a malicious branch, it only means that behavior was not observed in this run. Rules, deep scan, or LLM may still produce a higher risk.' },
        },
        {
          id: 'llm-analysis', title: 'LLM analysis: one final semantic assessment',
          paragraphs: ['When requested, the system waits for selected Scanner, rule, deep-scan, and Sandbox work, then sends a Skill content snapshot and analyzer evidence to the configured model for one final semantic assessment. The LLM does not execute the Skill.'],
          bullets: ['Outputs include benign, suspicious, or malicious risk, a security report, accepted or dismissed evidence, and—when applicable—an attack chain and security-framework mapping.', 'LLM cannot downgrade blocking evidence, and strict mode prevents deterministic risk downgrade. Balanced or permissive mode may lower non-blocking risk when no blocking finding exists; the system records the model explanation or a fallback reason.', 'If the model call fails, the attempt remains failed and the system falls back to deterministic rule, deep-scan, and Sandbox reconciliation. No LLM result does not mean completed and safe.'],
        },
        {
          id: 'execution-and-result', title: 'Execution order and result interpretation',
          steps: [
            { title: 'Submission enters PENDING', body: 'The Skill is stored first; the console does not wait synchronously for every analyzer.' },
            { title: 'Independent analyzers run in parallel', body: 'Base Scanner and selected rule analysis, deep scan, and Sandbox run independently.' },
            { title: 'Policy may add Sandbox', body: 'If interim risk matches a mandatory Sandbox level, the backend attempts Sandbox even when it was not manually selected.' },
            { title: 'Risk is reconciled and LLM may run once', body: 'Deterministic risk is produced first. One semantic model assessment follows only when selected.' },
            { title: 'Admission policy assigns the state', body: 'Final risk and policy route the Skill to APPROVED, VETTED, or REJECTED.' },
          ],
          table: { columns: ['Report status', 'Correct interpretation'], rows: [
            ['completed, with findings', 'The analyzer completed and provided evidence for review'],
            ['completed, no findings', 'No hit in this scope; other analyzers or untriggered branches may still matter'],
            ['skipped / not selected', 'This capability did not run and provides no risk conclusion'],
            ['unavailable / failed', 'The dependency or execution failed; troubleshoot and rescan'],
          ] },
          link: { path: '/skills', label: 'Open Skill reports' },
        },
      ],
    },
    'mcp-governance': {
      eyebrow: 'Feature guide', title: 'MCP governance', summary: 'Publish selected Tools from remote MCP Servers through controlled gateways with time-bound high-risk approvals and audits.',
      sections: [
        { id: 'flow', title: 'Recommended setup order', steps: [{ title: 'Register an MCP Server', body: 'Connect a Streamable HTTP endpoint and save the tools/list schema snapshot.' }, { title: 'Create an MCP Gateway', body: 'Select Tools from one or more registered servers.' }, { title: 'Issue a gateway credential', body: 'Limit allowed gateways, IPs, request size, and concurrency.' }, { title: 'Validate with MCP Debug', body: 'Discover Tools and call through a real gateway credential.' }, { title: 'Review high-risk calls', body: 'Review masked arguments and issue a short-lived authorization.' }] },
        { id: 'boundaries', title: 'Important boundaries', bullets: ['Servers store upstream connections; gateways decide what callers can see.', 'A schema change pauses exposure until the gateway is saved again.', 'Approval is scoped to credential, gateway, Tool, and schema—not a permanent argument signature.', 'MCP credentials do not establish Agent identity.'], link: { path: '/mcp-governance/servers', label: 'Open MCP Servers' } },
        { id: 'credentials-and-debug', title: 'Credential and debug boundaries', bullets: ['An MCP gateway credential must select allowed gateways. Default scopes are mcp:connect, mcp:list-tools, and mcp:call-tools.', 'Use MCP Debug to verify Tool discovery and parameter schema before configuring a real MCP Client.', 'Upstream HTTP is denied by default. A deployment administrator must explicitly allow it and constrain destinations with the outbound allowlist.', 'A successful debug call does not bypass high-risk approval or later Schema changes.'], link: { path: '/mcp-governance/debug', label: 'Open MCP Debug' } },
        { id: 'audit', title: 'Approvals and call audits', paragraphs: ['The first high-risk call returns an approval request; it has not executed successfully. Approval details show masked arguments by default. Revealing raw arguments creates a security audit event. Approved credentials may call the same Tool and Schema during the validity window.'], bullets: ['A denied or expired approval requires a new request.', 'A Tool Schema change is not covered by old authorization; save the gateway and review the new definition.', 'Approved does not mean upstream execution succeeded. Confirm the outcome in Call Audit.'], link: { path: '/mcp-governance/approvals', label: 'Open Call Approvals' } },
      ],
    },
    'agent-management': {
      eyebrow: 'Feature guide', title: 'Agent management', summary: 'Use an Agent as the primary record for department, model, and Skill bindings, then issue a least-privilege credential.',
      sections: [
        { id: 'agent-record', title: 'Register the Agent before issuing credentials', steps: [{ title: 'Create an Agent', body: 'Set a stable unique Agent ID, name, department, owner, Client type, and state. Runtime Agent ID must match this record.' }, { title: 'Bind capabilities', body: 'Choose the default model and allowed approved or deployed Skills. The list shows the concrete Skill identifier used for the binding.' }, { title: 'Issue a runtime credential', body: 'Create an Agent runtime credential bound to the Agent.' }, { title: 'Configure the runtime', body: 'Give the one-time secret only to that Agent; never use an administrator login token.' }], link: { path: '/agents', label: 'Open Agents' } },
        { id: 'status-and-binding', title: 'What state, binding, and credential control', table: { columns: ['Control', 'Effect', 'Common mistake'], rows: [['Agent state', 'Only active should carry production use; disabled or draft is not deleted', 'Do not infer state from deletion or credential revocation'], ['Skill binding', 'Defines which Skills this Agent may load', 'An approved Skill is not automatically available to every Agent'], ['Agent runtime credential', 'Establishes trusted Agent identity and runtime scopes', 'Caller metadata.agent_id cannot replace credential binding'], ['Default model', 'Records the Agent default model choice', 'model:chat scope and an enabled model are still required']] }, link: { path: '/docs/credential-management', label: 'Read Credential center' } },
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
        { id: 'discover-govern', title: 'Discover and enroll local Skills', paragraphs: ['The Client recognizes Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw, Hermes, TRAE CN, TRAE, Cursor, CodeBuddy, and WorkBuddy, and separately marks shared Skill roots that multiple Agents may read. Unsupported tools can be registered as custom Agents.'], bullets: ['Expand an Agent to review its real scan roots, Skill names, and validation state before selecting governance scope.', 'The preview separates trusted, enrollable, and pending content, and requires explicit confirmation before changes.', 'Disabled does not mean deleted: content is removed from the Agent entry point, kept safely, and can be submitted for platform scanning.', 'When installing from the platform, choose an approved version and one or more target Agents; the Client verifies release signature and file hashes.'], image: { name: 'client-app-discovery', alt: 'Desktop Client Agent Discovery page', caption: 'Agent Discovery groups Skill roots, discovery results, and platform state by local Agent. The screenshot uses example paths and data.' }, callout: { type: 'note', title: 'Shared-root identity boundary', body: 'Multiple Agents may read the same shared Skill root. The Client can govern its state and content integrity, but the directory alone does not identify the actual caller.' } },
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
        { id: 'setup-flow', title: 'Setup order', steps: [{ title: 'Add a provider', body: 'Configure an OpenAI-compatible endpoint, API format, and provider secret; enable provider-level compression if required.' }, { title: 'Register models', body: 'Set model name, context size, output limits, and enabled state.' }, { title: 'Configure groups and privacy policies', body: 'Choose PII entities, Prompt protection, and session mapping behavior.' }, { title: 'Issue a model credential', body: 'Limit models, request size, and concurrency; compression may also be enabled only for selected credentials.' }, { title: 'Call and inspect the trace', body: 'Use an OpenAI- or Anthropic-compatible endpoint, then inspect the privacy pipeline.' }], link: { path: '/model-gateway/providers', label: 'Open Providers' } },
        { id: 'pipeline', title: 'What happens to a request', bullets: ['Validate credential state, model scope, request size, and concurrency.', 'When the matching policy enables it, detect prompt injection, system prompt leakage, and credential exfiltration patterns.', 'When a privacy policy matches, replace PII with session-scoped pseudonymous tokens.', 'When the provider or credential enables compression, process context before the upstream call.', 'Restore the response and record audit, usage, and trace stages.'] },
        { id: 'token-compression', title: 'Token compression and usage analysis', paragraphs: ['A provider can enable compression globally. A model-call or Agent runtime credential with model:chat scope can also enable it and select auto, conservative, or aggressive. When only the provider enables compression and the credential does not select a level, the gateway uses auto. The platform processes messages before the upstream call and records token counts before and after compression, savings, ratio, and processing time.'], bullets: ['Token Compression Stats groups requests, input and output tokens, savings, average response time, model time, and platform time by period and model.', 'User Token Analytics compares call volume and token consumption across users.', 'Response headers and Pipeline Trace help distinguish compressed, enabled with no transformation, and disabled requests.'], callout: { type: 'note', title: 'Enabled does not mean every request saves tokens', body: 'Short context may need no transformation. If the compression component is unavailable or fails, the gateway falls back to the original messages, so enabled must not be interpreted as saved.' }, image: { name: 'token-compression', alt: 'Token Compression Stats page', caption: 'The stats page combines token usage, compression requests, savings, and platform and model timing. Values shown are example environment data.' }, link: { path: '/model-gateway/stats', label: 'Open Token Compression Stats' } },
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
        { id: 'before-you-start', title: 'Before deployment', bullets: ['Identify x86_64 or arm64/aarch64 architecture.', 'Verify Docker and Docker Compose.', 'Check that port 80 is available.', 'Prepare a strong SECRET_KEY, one-time administrator password, and Sandbox secret for production.', 'For offline delivery, match archive architecture and reserve space for image extraction and data growth.'], table: { columns: ['Resource', 'Recommended production baseline', 'Capacity-planning guidance'], rows: [['CPU', '16 vCPU', 'Runs Backend, scan analyzers, Sandbox scheduling, and concurrent requests. Scale CPU with scan concurrency.'], ['Memory', '32 GiB', 'Provides headroom for workers, analyzers, Sandbox services, and container page cache. Size for peak concurrent dynamic scans.'], ['Storage', '500 GiB usable, preferably SSD/NVMe', 'Stores images, Skill packages and versions, reports, audits, Client releases, and logs. More Skills and longer retention require a larger data volume.']] }, code: 'uname -m\ndocker --version\ndocker compose version', callout: { type: 'note', title: 'Capacity-planning boundary', body: 'These values are a production starting point, not a minimum. A separate benchmark on a shared 8-vCPU isolated test node identifies SQLite write-concurrency and scan-queue limits; keep the higher production headroom and read Performance and capacity for the full method and results.' }, link: { path: '/docs/performance-benchmark', label: 'Open performance and capacity results' } },
        { id: 'online', title: 'Online deployment', steps: [{ title: 'Prepare production configuration', body: 'Replace every replace-with-* value and keep ENFORCE_SECURE_STARTUP=true.', code: 'cp .env.example .env' }, { title: 'Build images', body: 'Build Backend, Frontend, Sandbox, and runtime images.', code: './build.sh --all' }, { title: 'Initialize the signing key', body: 'Create the Skill signing identity before first startup.', code: 'docker compose run --rm --no-deps backend agent-manager signing-key init' }, { title: 'Start and verify', body: 'Start in the background and inspect health.', code: 'docker compose up -d\ndocker compose ps', expected: 'backend, frontend, nginx, and sandbox are running or healthy.' }] },
        { id: 'offline', title: 'Offline deployment', steps: [{ title: 'Choose the archive', body: 'Use x86 for x86_64 and ARM for aarch64 or arm64.' }, { title: 'Load images', body: 'Replace the sample version with the delivered release.', code: 'xz -dc docker_images/x86/agent-manager-images-v1.0.0.tar.xz | docker load' }, { title: 'Configure and initialize signing', body: 'Edit .env and use the same TAG as the delivered images.', code: 'cp .env.example .env\nTAG=v1.0.0 docker compose run --rm --no-deps backend agent-manager signing-key init' }, { title: 'Start services', body: 'TAG must match the loaded image version.', code: 'TAG=v1.0.0 docker compose up -d\ndocker compose ps' }] },
        { id: 'verify', title: 'Post-deployment verification', bullets: ['All four core services are healthy.', 'The console opens at http://server-address/ and login succeeds.', 'System Overview shows no core dependency failures.', 'A test ZIP can complete background scanning.', 'Compose restart preserves Skills, credentials, and audits.'], code: 'docker compose ps\ndocker compose logs --tail=100 backend sandbox nginx' },
      ],
    },
    'performance-benchmark': {
      eyebrow: 'Deploy and operate', title: 'Performance benchmark and capacity boundaries', summary: 'Use measured results from an isolated benchmark stack to set single-node concurrency, scan workers, Skill capacity, and Client inventory expectations.',
      sections: [
        { id: 'environment', title: 'Environment and method', table: { columns: ['Item', 'Benchmark environment'], rows: [['Host', 'Shared VMware VM; 8 vCPU; Intel Xeon E5-2678 v3 @ 2.50 GHz'], ['Memory and disk', '31 GiB RAM; 195 GiB ext4 with about 49 GiB free'], ['OS', 'Ubuntu 24.04.4 LTS; Linux 6.8.0-137-generic; x86_64'], ['Docker', 'Client 28.5.2; Server 29.1.3; Compose v5.0.1; overlay2; cgroup v2'], ['Build', 'Backend dev-d6ec8a5b; one Uvicorn process; SQLite WAL'], ['Scan configuration', '2 scan workers, 8 analyzer workers, deep-scan concurrency 2; Sandbox 1 CPU / 512 MiB']] }, bullets: ['The benchmark used isolated Backend, SQLite, Registry, Sandbox, and Docker network resources and did not write to the existing platform.', 'Model and MCP tests used a deterministic local upstream with 50 ms processing delay. Results do not include external model generation or real Tool business latency.', 'Stable means no errors or timeouts in the bounded run; it is not a long soak, multi-instance, or fault-injection certification.'] },
        { id: 'recommended', title: 'Production configuration baseline', paragraphs: ['This section defines recommended initial parameters for a new single-node deployment, establishing an observable baseline for controlled tuning. These values are neither maximum capacity nor requests per second. Validate latency, error rate, and resource utilization with real workloads before changing them.'], bullets: ['Maximum concurrency is the number of unfinished requests allowed at the same time. With a limit of 5, the sixth simultaneous request is limited; this does not mean only five requests per second.', 'Throughput (req/s) is the number of requests actually completed per second. Raising concurrency does not necessarily raise throughput.', 'P95 latency means 95% of requests finish within that time. It exposes slow requests more clearly than an average.'], callout: { type: 'note', title: 'Basis for the recommended initial concurrency', body: 'When Model Gateway concurrency increased from 5 to 10, measured throughput did not grow while P95 rose from 391.31 ms to 758.27 ms. Five therefore provides a conservative balance of throughput, latency, and burst headroom; it is not a maximum-capacity claim.' } },
        { id: 'starting-values', title: 'Configurable parameters and recommended initial values', table: { columns: ['Setting', 'Control scope', 'Recommended initial value', 'Configuration location', 'Behavior at the limit'], rows: [['Model credential maximum concurrent requests', 'Unfinished requests using one model API key', '5', 'Create or edit an API key in Model Gateway', 'New requests are limited; in-flight requests continue'], ['MCP credential maximum concurrent requests', 'MCP requests using one access credential', '5', 'Create or edit a credential', 'New requests receive 429; this is the credential-level limit'], ['Per-Tool maximum concurrency', 'Calls executing concurrently for one Tool', '5', 'Tool security policy in MCP Gateway', 'Excess calls receive a JSON-RPC concurrency error and do not reach the upstream Tool'], ['Scan workers', 'Background Skill detection jobs processed concurrently', '2', 'AGENT_MANAGER_SCAN_WORKERS in Docker .env', 'Submissions may be accepted while excess jobs wait in the queue'], ['Analyzer workers', 'Shared threads for rule and structure analyzers', '8', 'AGENT_MANAGER_ANALYZER_WORKERS in Docker .env', 'Too few increase scan time; too many may create CPU contention'], ['Deep-scan concurrency', 'Deep scans executing at the same time', '2', 'Deep-scan concurrency setting in Docker .env', 'Excess deep scans wait for a slot']] }, paragraphs: ['An MCP Tool call is constrained by both the credential and the Tool. Effective concurrency is the lower value: credential 5 plus Tool 10 still permits only 5 concurrent calls, and credential 10 plus Tool 5 also permits only 5.', 'Scan workers control how many Skills are processed at once, analyzer workers provide a shared internal analysis pool, and deep-scan concurrency limits the more expensive deep analysis. Do not multiply these values into a throughput estimate. The recommended initial combination is 2 / 8 / 2 to reduce simultaneous CPU, SQLite-write, and temporary-storage spikes.'] },
        { id: 'tuning', title: 'When and how to raise the values', steps: [{ title: 'Run a real workload first', body: 'Use real models, MCP Tools, and production-sized Skills for 30–60 minutes at the starting values.' }, { title: 'Observe the right signals', body: 'Record P95, error rate, 429 or JSON-RPC limits, upstream timeouts, CPU, memory, SQLite lock waits, disk IOPS, and temporary storage.' }, { title: 'Change one setting at a time', body: 'Raise gateway concurrency through 5 → 8 → 10; raise scan concurrency by one, then repeat the test.' }, { title: 'Recognize the capacity knee', body: 'If throughput stays flat while P95, timeouts, or resource use rise, return to the previous value. The bottleneck is elsewhere.' }, { title: 'Plan for stable concurrency above 20', body: 'Validate external database or storage, multiple processes or instances, audit writes, and long-duration stability instead of merely setting the UI limit to 100.' }], callout: { type: 'warning', title: 'Two measured values are not settings', body: '“Caller concurrency at or below 10” for runtime verification is integration guidance. “50,000 Skills” is the tested catalog size. Neither is entered in the console; see the verification and Skill-capacity results below.' } },
        { id: 'gateways', title: 'Gateway results', table: { columns: ['Scenario', 'Concurrency', 'Success/requests', 'Throughput', 'P95'], rows: [['Model Gateway', '5', '40/40', '16.28 req/s', '391.31 ms'], ['Model Gateway', '10', '40/40', '15.23 req/s', '758.27 ms'], ['Model Gateway', '20', '0/40', '0', '30 s timeout'], ['MCP initialize', '10', '20/20', '103.76 req/s', '115.07 ms'], ['MCP tools/list', '10', '20/20', '75.01 req/s', '156.18 ms'], ['MCP tools/call', '5', '20/20', '7.66 req/s', '699.39 ms'], ['MCP tools/call', '10', '20/20', '7.96 req/s', '1,324.51 ms'], ['MCP tools/call', '20', '0/40', '0', '30 s timeout']] }, paragraphs: ['Add provider queueing, time to first token, generation time, and real MCP Tool latency to these numbers. Re-test the Model Gateway with production privacy detection, Prompt Guard, token compression, and streaming settings.'] },
        { id: 'skill-performance', title: 'Skill detection and runtime verification', table: { columns: ['Scenario', 'Parallel submissions', 'Acceptance P95', 'Completion P95', 'Reported scan P95'], rows: [['Warm rule scan', '1', '129.44 ms', '293.40 ms', '22.66 ms'], ['Warm rule scan', '4', '554.28 ms', '797.83 ms', '21.98 ms'], ['Deep scan', '1', '5.76 s', '11.99 s', '6.08 s'], ['Deep scan', '4', '381.44 ms', '12.81 s', '6.22 s'], ['Sandbox, small Python entry', '1', '71.13 ms', '411.49 ms', '186.58 ms']] }, bullets: ['Four parallel deep scans ran in two batches because deep-scan concurrency was 2.', 'The Sandbox sample was small; dependencies, complex entrypoints, timeouts, and remote networking change the result.', 'No external LLM was called, so the benchmark does not present mock data as real LLM-analysis performance.', 'Runtime verification P95 at concurrency 1/2/5/10/20/40 was 39.83/74.13/192.18/376.35/881.90/1,446.71 ms.'] },
        { id: 'capacity-client', title: 'Skill capacity and Client cost', paragraphs: ['With 50,000 synthetic Skill families, the isolated SQLite file was 59.97 MiB. P95 was 75.82 ms for the first page, 111.01 ms for a middle page, 89.03 ms for name search, and 145.34 ms for dashboard aggregation. Synthetic rows exclude real packages, versions, reports, and audits, so they do not estimate production disk use.'], table: { columns: ['Local Skills', 'Inventory P50', 'Inventory P95', 'Inventory JSON', 'Peak RSS'], rows: [['100', '86.87 ms', '94.74 ms', '21.40 KiB', '15.0–15.8 MiB'], ['500', '239.86 ms', '245.01 ms', '104.99 KiB', '15.9–16.5 MiB'], ['1,000', '414.51 ms', '439.15 ms', '210.46 KiB', '16.7–17.1 MiB']] }, callout: { type: 'note', title: 'Where Client resource use occurs', body: 'Inventory walks Agent Skill directories, reads metadata, builds the inventory, and writes local SQLite on the Client. CPU, disk reads, and memory therefore occur mainly on the endpoint. The platform still handles reports, policy and task delivery, and server-side detection, so server use grows with Clients and task volume.' } },
        { id: 'production', title: 'Production guidance', bullets: ['Keep 16 vCPU, 32 GiB, and 500 GiB SSD/NVMe as the initial single-node production baseline; do not use the smaller shared host to reduce that baseline.', 'Start Model, MCP credential, and Tool concurrency at 5, then adjust using P95, error rate, SQLite lock waits, and audit growth.', 'Start with 2 scan workers and deep-scan concurrency 2. Evaluate CPU, memory, Sandbox, and temporary disk before raising them.', 'Avoid scheduling full inventory or reporting for many Clients at the same instant.', 'Run a 30–60 minute steady-state test with real Skills, models, Tools, and target endpoint operating systems. Linux results do not replace macOS or Windows testing.'] },
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

en.articles['scanner-access'] = {
  eyebrow: 'Skill governance',
  title: 'Batch local Skill access with Scanner',
  summary: 'Use the single-binary Scanner to discover Skills on servers, workstations, or CI, run lightweight local prechecks, and upload with least privilege for full platform scanning.',
  sections: [
    {
      id: 'when-to-use', title: 'When to use Scanner',
      table: { columns: ['Scenario', 'Recommended entry'], rows: [
        ['A small ZIP selected manually by an administrator', 'Submit Skill page'],
        ['One host has multiple Skill roots', 'Scanner CLI'],
        ['A server or CI submits Skills periodically', 'Scanner CLI with a dedicated Scanner credential'],
        ['Continuous governance and automatic local repair are required', 'Agent Manager Client, not Scanner CLI'],
      ] },
      callout: { type: 'note', title: 'Local precheck is not platform approval', body: 'Scanner local precheck does not execute customer code. It checks packaging boundaries and obvious static signals. Full server analysis and policy still produce APPROVED, VETTED, or REJECTED.' },
    },
    {
      id: 'credential', title: 'Create a least-privilege Scanner credential',
      steps: [
        { title: 'Open Credential Center', body: 'Create a Scanner access credential. Do not use an administrator login token or Agent runtime credential.' },
        { title: 'Keep default Scanner scopes', body: 'Batch upload and owned-result polling use scanner:submit, scanner:read-own-results, and scanner:read-own-sessions.' },
        { title: 'Constrain the boundary', body: 'Set allowed IP / CIDR, maximum upload size, and maximum concurrent jobs where needed. The secret is shown once.' },
      ],
      link: { path: '/credentials', label: 'Open Credential Center' },
    },
    {
      id: 'run', title: 'Download and run the first scan',
      steps: [
        { title: 'Download the matching binary', body: 'The current page supports macOS Apple Silicon, macOS Intel, Linux x86_64, Linux ARM64, and Windows x86_64. Actual downloads depend on server release files.' },
        { title: 'Configure platform and credential', body: 'A platform URL enables upload. Without it, Scanner only writes local discovery and precheck output.', code: 'export SKILL_SCANNER_SERVER="https://agent-manager.example.com"\nexport SKILL_SCANNER_TOKEN="amat_xxx"\nexport SKILL_SCANNER_HOST_ID="customer-prod-01"' },
        { title: 'Scan the Skill root', body: 'Scanner recursively discovers directories containing SKILL.md. Explicitly request rules, deep scan, Sandbox, or LLM as needed; unavailable server dependencies may fail or skip.', code: './skill-scanner scan /path/to/skills \\\n  --behavioral \\\n  --deep-scan \\\n  --output skill-scan-report.json', expected: 'The local report contains paths, fingerprints, precheck findings, upload status, and platform skill_id values.' },
      ],
      link: { path: '/scanner-access', label: 'Open Scanner access' },
    },
    {
      id: 'packaging-safety', title: 'Packaging and result boundaries',
      bullets: ['Default ignores include .git, .venv, node_modules, __pycache__, dist, and build.', 'Scanner does not follow symlinks outside the Skill directory and limits individual size, total size, and file count.', 'The server recomputes manifest and fingerprint after extraction instead of trusting client values.', 'A Scanner credential reads only its own submissions. A 403 may be an ownership mismatch and is not a reason to clear platform data.', 'Identical content and scan context may reuse a result. Use rescan on the Skill version when execution must be forced.'],
    },
  ],
}

en.articles['credential-management'] = {
  eyebrow: 'Agent management',
  title: 'Credential center and access credentials',
  summary: 'Choose credential type, binding, and least-privilege scopes by caller, then constrain models, gateways, source IPs, request size, and concurrency.',
  sections: [
    {
      id: 'credential-types', title: 'Create least-privilege access credentials by type',
      table: { columns: ['Credential type', 'Required binding or boundary', 'Default purpose'], rows: [
        ['Agent runtime', 'Must bind one Agent', 'Signature, load, and Tool checks; optional governance, memory, or model scopes'],
        ['Scanner access', 'Reads only owned submissions', 'Batch Skill upload and owned-result polling'],
        ['Client access', 'Associates with a Client after registration', 'Registration, heartbeat, policy, tasks, inventory, events, and approved downloads'],
        ['Model gateway', 'May restrict allowed models', 'Model calls with optional token compression and Prompt Guard'],
        ['MCP gateway', 'Must select allowed gateways', 'Connect, discover, and call published MCP Tools'],
      ] },
    },
    {
      id: 'create', title: 'Create a credential in the right order',
      steps: [
        { title: 'Create the bound object first', body: 'Create the Agent before an Agent runtime credential and the gateway before an MCP credential. Do not use empty bindings to bypass identity.' },
        { title: 'Choose type and preset', body: 'For Agent runtime, start with Verification, Governance, or Governance + Model, then narrow scopes to actual needs.' },
        { title: 'Set resource boundaries', body: 'Constrain Agent, MCP gateways, models, allowed IP / CIDR, request or upload size, and request or job concurrency as applicable.' },
        { title: 'Save and copy immediately', body: 'The secret appears once. Store it in the caller secure configuration, never source, screenshots, or normal logs.', expected: 'The list retains only prefix, type, binding, scopes, and status—not the full secret.' },
      ],
      link: { path: '/credentials', label: 'Open Credential Center' },
    },
    {
      id: 'model-controls', title: 'Credentials with model:chat',
      bullets: ['Model gateway credentials include model:chat by default. Agent runtime credentials require Governance + Model or an explicit model:chat scope.', 'Allowed models may be restricted. An empty list means no credential-level model restriction, not a bypass of model state or group policy.', 'Token-compression level and Prompt Guard mode follow the credential. Prompt Guard supports off, log, warn, or block.', 'Requests still pass credential status, binding, model range, body size, source IP, and concurrency checks.'],
    },
    {
      id: 'lifecycle', title: 'Revoke, delete, and troubleshoot',
      table: { columns: ['Action or symptom', 'Correct response'], rows: [
        ['Secret lost', 'Revoke it and create a replacement; plaintext cannot be recovered'],
        ['Caller retired or suspected leak', 'Revoke first, update the caller, and inspect audit events'],
        ['403', 'Check type, scopes, Agent or gateway binding, allowed models, and source IP'],
        ['429', 'Check request concurrency or Scanner job concurrency'],
        ['Request or upload rejected', 'Check body or upload size instead of removing limits indiscriminately'],
      ] },
      link: { path: '/docs/audit-trail', label: 'Continue to Audit trail' },
    },
  ],
}

en.articles['audit-trail'] = {
  eyebrow: 'Agent management',
  title: 'Audit trail',
  summary: 'Trace Skill submission and review, runtime verification, Tool calls, and Client enforcement by time, event type, and keyword, distinguishing attempts, failures, blocks, and success.',
  sections: [
    {
      id: 'what-is-recorded', title: 'Events available now',
      table: { columns: ['Flow', 'Common events'], rows: [
        ['Skill governance', 'Submitted, analysis started/completed, queued for review, approved, rejected'],
        ['Runtime verification', 'Integrity verified, load allowed or blocked, content mismatch detected'],
        ['Tool governance', 'Tool invocation allowed or blocked'],
        ['Client governance', 'Unmanaged Skill found, modification, repair, block, quarantine, install, and removal'],
      ] },
    },
    {
      id: 'query', title: 'Locate one event',
      steps: [
        { title: 'Choose a time range', body: 'The page provides the last 24 hours, 7 days, and 30 days. Cover the actual event time before concluding that no event exists.' },
        { title: 'Choose an event type', body: 'Narrow by a stable type such as block, content mismatch, review, or Client enforcement.' },
        { title: 'Search by keyword', body: 'Search values related to Skill, Agent, credential Actor, or event details.' },
        { title: 'Cross-check fields', body: 'Read time, event, Skill, Agent, source IP, credential / Actor, and details together. A known Skill ID links to its details.' },
      ],
      link: { path: '/audit', label: 'Open Audit trail' },
    },
    {
      id: 'interpretation', title: 'Do not over-interpret one record',
      bullets: ['Analysis started means a task began, not that it succeeded. Find analysis completed and final state.', 'Integrity verified proves content matches a trusted version, but load permission must still pass.', 'Load allowed does not authorize every later Tool. Tool calls have separate allowed or blocked events.', 'A delivered Client task is not necessarily executed. Check task state and recent events in Client details.', 'Model privacy and MCP calls have dedicated audit pages. The unified audit does not replace raw trace detail.'],
    },
  ],
}

en.articles['risk-classification'] = {
  eyebrow: 'Skill governance',
  title: 'Risk finding classification and decision logic',
  summary: 'Classify analyzer findings as blocking, suspicious, or noise, then combine severity, judgement mode, and optional LLM output into final risk.',
  sections: [
    {
      id: 'four-levels', title: 'Separate four layers first',
      paragraphs: ['Finding classification is neither final risk nor final state. Trace a result from individual evidence through classification and risk reconciliation to admission.'],
      table: { columns: ['Layer', 'Question answered', 'Example'], rows: [
        ['Finding and severity', 'What evidence did one analyzer observe?', 'A HIGH download-and-execute rule'],
        ['Finding classification', 'Is this finding blocking, suspicious, or noise?', 'Supply-chain risk is blocking'],
        ['Final risk', 'Is the reconciled result benign, suspicious, or malicious?', 'A MEDIUM suspicious finding becomes suspicious in balanced mode'],
        ['Skill state', 'Is the Skill approved, queued for review, or rejected?', 'APPROVED, VETTED, or REJECTED'],
      ] },
    },
    {
      id: 'classification-meaning', title: 'Blocking, suspicious, and noise findings',
      table: { columns: ['Class', 'Meaning', 'Deterministic risk effect'], rows: [
        ['Blocking', 'High-confidence behavior that must not be automatically admitted', 'Any blocking finding produces malicious risk and cannot be downgraded by LLM'],
        ['Suspicious', 'A security signal evaluated with severity and judgement mode', 'HIGH or above normally requires at least review; MEDIUM depends on mode'],
        ['Noise', 'Dependency, runtime, or documented-example diagnostics', 'Retained for explanation and troubleshooting but does not directly raise deterministic risk'],
      ] },
      callout: { type: 'note', title: 'Noise is not deleted evidence', body: 'The original rule, severity, file, and evidence remain in the report. Classification only removes that item from deterministic risk escalation.' },
    },
    {
      id: 'default-mapping', title: 'Default finding classification',
      table: { columns: ['Default class', 'Risk items'], rows: [
        ['Blocking', 'Data exfiltration; supply-chain risk'],
        ['Suspicious', 'Prompt injection; Tool misuse; network, credential, or dynamic execution; excessive permissions'],
        ['Noise', 'Documented external API examples; dependency issues; runtime issues'],
      ] },
      paragraphs: ['Administrators can move these items between classes under Policy Settings / Risk Decisions. The mapping is part of scan context. Existing reports are not rewritten; rescan to apply the new policy.'],
      link: { path: '/policy', label: 'Open Policy Settings' },
    },
    {
      id: 'classification-order', title: 'How one finding is classified',
      steps: [
        { title: 'Identify the risk item', body: 'Rule ID, category, file path, and evidence text are matched to data exfiltration, supply chain, prompt injection, and other configured items. Documented API examples are recognized first.' },
        { title: 'Apply the administrator mapping', body: 'When a configured risk item is recognized, its current blocking, suspicious, or noise class wins.' },
        { title: 'Apply the security fallback', body: 'Unmapped download-and-execute, credential or data exfiltration, and governance-bypass rules remain blocking.' },
        { title: 'Filter diagnostic noise', body: 'Missing dependencies, runtime issues, and LOW or MEDIUM low-analyzability signals become noise.' },
        { title: 'Fall back by severity', body: 'Other MEDIUM-or-higher findings become suspicious; remaining lower findings become noise.' },
      ],
    },
    {
      id: 'risk-reconciliation', title: 'How classes produce final risk',
      table: { columns: ['Finding state', 'Strict', 'Balanced', 'Permissive'], rows: [
        ['Any blocking finding', 'malicious', 'malicious', 'malicious'],
        ['Highest suspicious finding is HIGH / CRITICAL', 'malicious', 'suspicious', 'suspicious'],
        ['Highest suspicious finding is MEDIUM', 'suspicious', 'suspicious', 'benign'],
        ['Only noise or lower findings', 'benign', 'benign', 'benign'],
      ] },
      paragraphs: ['When enabled, LLM runs once after deterministic classification. It may raise risk. In balanced or permissive mode, it may also lower non-blocking risk and records the model explanation or a fallback reason. Strict mode and results containing a blocking finding cannot be downgraded.'],
    },
    {
      id: 'admission-result', title: 'How final risk becomes a Skill state',
      bullets: ['A blocking manifest constraint, such as an explicitly denied permission, produces REJECTED.', 'Final risk in Automatic rejection becomes REJECTED. If the same risk is also configured for review, rejection wins.', 'Final risk in Human review becomes VETTED.', 'Fail-safe behavior still rejects malicious, sends suspicious to review, and approves only benign when policy values are missing or incomplete.'],
      callout: { type: 'warning', title: 'Do not decide by finding count', body: 'One blocking finding can determine risk, while many noise findings should not be accumulated into malicious. Review classification and evidence before final risk and state.' },
      link: { path: '/docs/skill-policy', label: 'Continue to Skill policy settings' },
    },
  ],
}

en.articles['skill-policy'] = {
  eyebrow: 'Skill governance',
  title: 'Skill policy settings',
  summary: 'Configure result reuse, risk decisions, admission constraints, LLM, and Sandbox while understanding what each setting currently enforces for Skills.',
  sections: [
    {
      id: 'effective-order', title: 'Where policy acts in the scan flow',
      steps: [
        { title: 'Decide whether a result can be reused', body: 'An existing report can be reused when both content and scan context match and reuse is enabled. Policy or analyzer changes alter scan context.' },
        { title: 'Run selected analyzers', body: 'Rules and deep scan establish interim severity. If interim risk matches a mandatory Sandbox level, the backend attempts an additional Sandbox run.' },
        { title: 'Classify and reconcile deterministic risk', body: 'Findings become blocking, suspicious, or noise; strict, balanced, or permissive mode produces pre-LLM risk.' },
        { title: 'Optionally run LLM assessment', body: 'The model runs after other evidence is available. Blocking findings and strict-mode downgrade protection remain enforced.' },
        { title: 'Apply manifest constraints and admission', body: 'Tool and license rules create policy warnings or blocks, then final risk routes the Skill to APPROVED, VETTED, or REJECTED.' },
      ],
    },
    {
      id: 'page-layout', title: 'What the four settings areas control',
      table: { columns: ['Area', 'Primary settings', 'Recommended approach'], rows: [
        ['Risk decisions', 'Result reuse, judgement mode, review/rejection risk, mandatory Sandbox, finding classification', 'Set the organization risk posture before moving individual risk items'],
        ['Admission constraints', 'Tool count, allowed Tools, denied permissions, license, and author data', 'Start least-privilege and validate with representative Skills'],
        ['LLM', 'Enabled state, model, timeout, and content snapshot limits', 'Enable a model in Model Gateway before exposing the submission option'],
        ['Sandbox', 'Local or remote runtime, timeout, network, memory, CPU, PIDs, and read-only root filesystem', 'Test connectivity before requiring Sandbox for risk levels'],
      ] },
      link: { path: '/policy', label: 'Open Policy Settings' },
    },
    {
      id: 'decision-settings', title: 'Risk decision and disposition settings',
      table: { columns: ['Setting', 'Current effect', 'Important detail'], rows: [
        ['Reuse identical scan results', 'Reuses a report when content and scan context match', 'Disable it to rescan identical content on resubmission'],
        ['Judgement mode', 'Maps non-blocking HIGH / MEDIUM suspicious findings to risk', 'Blocking findings remain malicious in every mode'],
        ['Human review', 'Matching final risk becomes VETTED', 'Default includes suspicious'],
        ['Automatic rejection', 'Matching final risk becomes REJECTED', 'Rejection wins when also configured for review'],
        ['Mandatory Sandbox', 'Attempts Sandbox when interim risk matches a selected level', 'The dependency must be enabled and reachable; skipped or failed is not safe'],
        ['Finding classification', 'Places 11 risk items into blocking, suspicious, or noise', 'Changes apply to future rescans, not completed reports'],
      ] },
      link: { path: '/docs/risk-classification', label: 'Read classification and risk calculation' },
    },
    {
      id: 'admission-settings', title: 'Tool and license constraints',
      table: { columns: ['Setting or match', 'Current result'], rows: [
        ['Declared Tool count exceeds the limit', 'Non-blocking policy warning'],
        ['Declared Tool is outside the allowlist', 'Non-blocking warning and invalid declared-Tool check'],
        ['Declaration matches a denied permission', 'Blocking violation and immediate rejection'],
        ['License is required but absent from SKILL.md', 'Non-blocking policy warning'],
        ['License is outside the accepted list', 'Non-blocking policy warning'],
      ] },
      callout: { type: 'note', title: 'Validate SKILL.md declarations first', body: 'These checks read allowed-tools / allowed_tools and license from SKILL.md frontmatter. They validate declarations and do not replace rule, deep-scan, or Sandbox inspection of actual code behavior.' },
    },
    {
      id: 'analyzer-settings', title: 'LLM and Sandbox settings',
      bullets: ['LLM settings control whether Skill LLM analysis is available, which enabled Model Gateway model is used, and timeout, file-count, per-file, and manifest snapshot limits.', 'Sandbox settings select a remote isolated service or local Docker runtime and constrain network, memory, CPU, PID count, duration, and root-filesystem writes.', 'Enabled means the capability may be selected or called. Per-run completed, skipped, unavailable, and failed statuses show what actually happened.', 'Test Sandbox connectivity before saving. Validate LLM availability, timeout, and snapshot range with a non-sensitive test Skill.'],
    },
    {
      id: 'current-boundaries', title: 'Current enforcement boundaries',
      paragraphs: ['A few compatibility fields remain visible, but saveable does not mean enforced for Skill admission. Current Skill state is determined by automatic rejection, human review, and fail-safe behavior.'],
      bullets: ['Maximum risk for automatic approval currently applies to Prompt approval, not Skill APPROVED, VETTED, or REJECTED decisions.', 'Trusted authors are stored but do not participate in Skill scanning or automatic admission. Adding an author does not skip checks or human review.', 'Missing or unaccepted licenses, excessive Tool count, and Tools outside the allowlist are currently non-blocking warnings. Only an explicitly denied permission creates an immediate blocking violation.'],
      callout: { type: 'warning', title: 'Do not build a security promise on compatibility fields', body: 'Until those fields are formally connected to Skill decisions, rely on the report, final risk, and actual state—not automatic-approval threshold or trusted-author values.' },
    },
    {
      id: 'change-workflow', title: 'Change policy safely',
      steps: [
        { title: 'State the intended change', body: 'Record which false positive should be reduced or which behavior should be blocked, and which Skills may be affected.' },
        { title: 'Validate representative samples', body: 'Prepare at least one Skill expected to approve, one to review, and one to reject.' },
        { title: 'Save and rescan', body: 'Policy does not rewrite completed reports. Rescan target versions to apply the new scan context.' },
        { title: 'Inspect the complete evidence chain', body: 'Check finding classification, pre-LLM risk, LLM assessment, final risk, policy warnings, and final state together.' },
      ],
      link: { path: '/skills', label: 'Open Skill list and rescan' },
    },
  ],
}

export const docsContent = { 'zh-CN': zh, 'en-US': en }

export const docsArticleOrder = [
  '',
  'quick-start',
  'skill-governance',
  'scanner-access',
  'scan-capabilities',
  'risk-classification',
  'skill-policy',
  'mcp-governance',
  'agent-management',
  'client-management',
  'credential-management',
  'runtime-integration',
  'audit-trail',
  'model-gateway',
  'system-management',
  'docker-deployment',
  'performance-benchmark',
  'docker-operations',
  'faq',
]
