import { securityGuides } from './security-guides.js'
import { integrationGuides } from './integration-guides.js'
import { aidrGuides, aidrGuideOrder } from './aidr-guides.js'

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
      { subgroup: 'Skill 治理', slug: 'risk-classification', title: '风险项目归类', summary: '判为恶意、结合上下文判断、仅保留提示与最终风险' },
      { subgroup: 'Skill 治理', slug: 'skill-policy', title: '策略配置', summary: '风险判定、准入约束与分析器设置' },
      { subgroup: 'MCP 治理', slug: 'mcp-governance', title: 'MCP 治理', summary: '服务、网关、审批与调用审计' },
    ] },
    { title: '智能体管理', items: [
      { slug: 'agent-management', title: '智能体管理', summary: 'Agent 档案、能力绑定与凭证选择' },
      { slug: 'client-management', title: '客户端管理', summary: '本地 Agent 发现、Skill 下发与持续巡检' },
      { slug: 'credential-management', title: '统一凭证中心', summary: '按调用主体签发最小权限凭证' },
      { slug: 'runtime-integration', title: '接入与运行', summary: '自研 Agent 的加载、Tool 与运行轨迹接入' },
      { slug: 'hook-integration', title: 'Hook 接入', summary: 'Claude Code、Codex 与 OpenClaw 事件拦截配置' },
      { slug: 'agent-security-runtime', title: 'AI 安全与调用轨迹', summary: 'Agent、MCP、大模型与 AI 基础设施测评、Worker、证据解释与统一轨迹' },
      { slug: 'audit-trail', title: '审计追踪', summary: '查询 Skill、Agent、客户端与 Tool 事件' },
    ] },
    { title: '模型网关', items: [
      { slug: 'model-gateway', title: '模型网关', summary: '模型接入、隐私防护与 Token 压缩' },
    ] },
    { title: '系统管理', items: [
      { slug: 'system-management', title: '系统管理', summary: '账号、角色、菜单、审计与品牌设置' },
    ] },
    { title: '部署与运维', items: [
      { slug: 'docker-deployment', title: 'Docker 部署', summary: '在线或离线方式启动同一套 Compose 服务' },
      { slug: 'performance-benchmark', title: '性能与容量', summary: '隔离环境实测并发、Skill 容量与客户端开销' },
      { slug: 'docker-operations', title: 'Docker 运维', summary: '状态、日志、备份、升级与排障' },
    ] },
    { title: '场景实践', items: [
      { slug: 'case-expense-skill', title: '差旅报销 Skill 上线', summary: '从业务样本到审批、授权与运行校验' },
      { slug: 'case-high-impact-skill', title: '高影响 Skill 审核', summary: '审核合法但具备文件外发能力的 Skill' },
      { slug: 'case-malicious-skill', title: '恶意 Skill 准入拒绝', summary: '按策略归类识别凭据和数据外传风险' },
      { slug: 'case-runtime-tamper', title: '本地篡改阻断', summary: '已批准 Skill 被修改后拒绝加载' },
      { slug: 'case-mcp-approval', title: 'MCP 高风险操作审批', summary: '客户查询与暂停服务的审批闭环' },
      { slug: 'case-client-modular-governance', title: '客户端模块化治理', summary: '按 Agent、目录和授权边界治理一台多 Agent 主机' },
      { slug: 'case-model-privacy-compression', title: '模型隐私与压缩', summary: '保护客服对话中的隐私并核对 Token 压缩效果' },
    ] },
    { title: '帮助', items: [
      { slug: 'faq', title: '常见问题', summary: '按现象定位常见问题' },
    ] },
  ],
  articles: {
    '': {
      eyebrow: 'Agent Manager 文档',
      title: '让 Agent 能力、模型调用与本地运行可控',
      summary: '从 Skill 准入和客户端分发，到内置模型防护、外部 AI 网关联动与 MCP Tool 审批，平台把关键控制和审计集中到一处。',
      home: true,
      roles: [
        { title: '平台管理员', text: '先完成 Docker 部署、系统检查、用户与凭证配置。', slug: 'docker-deployment' },
        { title: '安全审核人员', text: '从 Skill 报告、审核队列和治理策略开始。', slug: 'skill-governance' },
        { title: 'Agent 与客户端运维', text: '登记 Agent、选择运行校验方式，再治理本地 Skill。', slug: 'agent-management' },
        { title: '模型接入运营人员', text: '根据流量是否经过平台，选择内置模型网关或客户外部 AI 网关。', slug: 'scenario-selection' },
      ],
      sections: [
        {
          id: 'what-it-does',
          title: '这个系统解决什么问题',
          paragraphs: ['Agent Manager 不是单一的 Skill 仓库。它同时治理 Agent 使用的 Skill、本地客户端上的能力分发、模型接入关系和内置网关流量，以及对外开放的 MCP Tool。'],
          bullets: ['Skill 在使用前完成检测、策略判定、审核和签名，内容变化后重新验证。', 'Agent 通过绑定和专用凭证获得最小权限；客户端负责发现、下发、恢复或隔离本地 Skill。', '内置模型网关执行访问控制、Prompt 防护、隐私替换、可选 Token 压缩和用量分析；外部网关模式管理连接、外部 Agent 与 API Key 映射，模型流量不经过内置代理。', 'MCP 网关只发布选定 Tool，并对高风险调用执行限时审批和审计。'],
        },
        {
          id: 'system-architecture',
          title: '系统总体架构',
          paragraphs: ['平台通过统一入口连接管理人员、Scanner、Agent 与客户端、模型应用和 MCP Client。治理控制面集中管理策略、身份、授权与审计；各运行数据面分别执行 Skill 准入、本地能力治理、模型隐私处理和 MCP Tool 调用控制。'],
          bullets: ['Skill 检测在规则、深度扫描、可选 Sandbox 与 LLM 证据完成后，由策略决定准入状态。', '客户端最终管理本地 Skill；Agent 在加载前通过 Verifier 或 Hook 核对内容签名和授权。', '内置模型流量依次经过凭证与模型范围、Prompt 防护、PII 伪匿名化和可选压缩；外部网关流量由 Agent 或客户端直连客户网关，平台管理连接和身份映射。', 'MCP 调用只访问网关发布的 Tool；高风险 Tool 在执行前进入限时审批。', 'Registry、报告、任务、Trace 和安全审计形成贯穿各能力域的证据链。'],
          diagram: 'architecture',
          callout: { type: 'note', title: '控制面与执行边界', body: '平台负责准入、授权、路由与证据记录；Agent 仍从本地目录加载 Skill，Sandbox 在隔离环境执行动态检测，上游模型和 MCP Server 保持为外部运行依赖。' },
        },
        {
          id: 'capability-map',
          title: '按目标选择功能',
          table: {
            columns: ['你想完成的事情', '使用模块'],
            rows: [
              ['按产品和运行方式选择接入方案', { label: '场景选择', path: '/docs/scenario-selection' }],
              ['提交并检测一个 Skill', { label: 'Skill 治理 / 提交 Skill', path: '/docs/skill-governance' }],
              ['批量接入主机或 CI 中的 Skill', { label: 'Scanner 接入', path: '/docs/scanner-access' }],
              ['选择检测方式并理解结果', { label: 'Skill 检测能力', path: '/docs/scan-capabilities' }],
              ['理解发现项分类如何影响最终风险', { label: '风险项目归类', path: '/docs/risk-classification' }],
              ['配置 Skill 风险与准入规则', { label: 'Skill 策略配置', path: '/docs/skill-policy' }],
              ['审核可疑 Skill', { label: 'Skill 治理 / Skill 审核', path: '/docs/skill-governance' }],
              ['让 Agent 只能使用指定 Skill', { label: '智能体管理 / 能力绑定与凭证', path: '/docs/agent-management' }],
              ['为不同调用方创建最小权限凭证', { label: '统一凭证中心', path: '/docs/credential-management' }],
              ['把验签和 Tool 检查接入自研 Agent', { label: '自研 Agent 运行校验接入', path: '/docs/runtime-integration' }],
              ['配置 Claude Code、Codex 或 OpenClaw Hook', { label: 'Hook 接入', path: '/docs/hook-integration' }],
              ['发现本机 Agent 和 Skill 目录', { label: '客户端管理 / Agent 发现', path: '/docs/client-management' }],
              ['向本地 Agent 下发、恢复或移除 Skill', { label: '客户端管理 / 管理台操作', path: '/docs/client-management' }],
              ['接入客户已有的 AI 网关并为 Agent 获取模型', { label: '外部 AI 网关', path: '/docs/external-ai-gateway' }],
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
          "id": "submit-zip",
          "title": "2. 上传 ZIP 或文件夹并选择 Skill",
          "paragraphs": [
            "上传方式可切换为“ZIP 包”或“文件夹”，每次仅展示对应入口。切换时清空当前选择和解析结果，打包、上传或提交期间暂时禁用切换。文件夹中的文件较多时，建议先在本地打包为 ZIP，以减少浏览器读取和打包的资源占用。",
            "文件夹模式点击“选择文件夹”，打包前按直接子文件夹的原始大小降序展示，包含所有深层文件，根目录文件单独列出。取消勾选保留该行，可以重新选中；点击“移除”则删除当前列表中的整行及其待上传内容，不删除本地文件。需要恢复已移除内容时，重新选择文件夹。",
            "列表实时统计已选内容的原始总大小。超过 100 MiB 时禁用“打包并上传”，必须减少选择至 100 MiB 以内（含等于）才能继续，不以预计压缩大小判断。最多允许 50,000 个文件，SVG 等资源文件仍计数；仅自动跳过 __MACOSX 和 .DS_Store。选中疑似凭据文件时会提示确认，打包期间可取消。浏览器可能省略软链接、空目录及执行权限，需要保留时使用 ZIP。历史记录显示“文件夹名称.zip”。",
            "ZIP 模式选择或拖入 ZIP 后自动整理并解析，上传大小上限为 100 MiB。浏览器移除 __MACOSX/ 开头的条目后校验大小，本地原文件不变。超过上限时，页面汇总第一、第二级目录中压缩后大小最大的 10 项，便于在本地清理并重新打包。",
            "整理、上传、解压和识别按阶段展示进度；百分比表示当前阶段的进度。ZIP 包含软链接时，确认窗口列出具体路径，可跳过并继续或取消，无需再次上传。"
          ],
          "steps": [
            {
              "title": "选择目录和技能",
              "body": "每个 Skill 目录必须包含 SKILL.md。解析完成后，选择需要导入的目录和技能。"
            },
            {
              "title": "选择检测项并提交",
              "body": "规则分析强制开启，不能取消勾选；按需要选择可用的深度扫描、Sandbox、LLM 分析，然后点击“提交所选技能”。",
              "expected": "提示“后台任务已创建”，后台继续准备内容并安排检测。"
            }
          ],
          "image": {
            "name": "submit-skill",
            "alt": "ZIP 解析后的提交页面",
            "caption": "示例数据：选择技能后提交，右侧入口可打开历史提交记录。"
          },
          "link": {
            "path": "/submit",
            "label": "打开提交 Skill"
          }
        },
        {
          "id": "folder-upload",
          "title": "选择文件夹上传",
          "paragraphs": [
            "切换到“文件夹”后点击“选择文件夹”。文件较多时可先在本地打包为 ZIP，减少浏览器资源占用。"
          ],
          "image": {
            "name": "submit-folder",
            "alt": "文件夹上传模式",
            "caption": "示例界面：文件夹模式与性能提示。"
          }
        },
        {
          "id": "folder-size-selection",
          "title": "打包前检查原始大小",
          "paragraphs": [
            "子文件夹按大小降序展示。所选原始总大小超过 100 MiB 时，“打包并上传”禁用。"
          ],
          "image": {
            "name": "folder-selection",
            "alt": "文件夹超限与目录列表",
            "caption": "示例数据：179 MiB 文件夹在打包前提示超限。"
          }
        },
        {
          "id": "folder-remove-selection",
          "title": "移除与取消选中",
          "paragraphs": [
            "“移除”删除当前列表中的整行；取消勾选保留该行，可重新选中。两种操作都不删除本地文件。"
          ],
          "image": {
            "name": "folder-selection-edited",
            "alt": "移除目录并取消勾选后的列表",
            "caption": "示例数据：large/ 已移除，small/ 保留但未选中，仅 SKILL.md 待上传。"
          }
        },
        {
          "id": "submission-history",
          "title": "历史提交记录",
          "paragraphs": [
            "点击“提交所选技能”右侧的“历史提交记录”。弹窗展示最近 50 个任务的编号、ZIP 包名称、导入时间、状态及已处理/总数，刷新页面仍可查询。旧记录未保存 ZIP 名称时显示“—”。",
            "导入完成表示所选内容已处理，最终检测状态请查看导入结果或 Skill 详情。"
          ],
          "image": {
            "name": "submission-history",
            "alt": "历史提交记录弹窗",
            "caption": "示例数据：按 ZIP 名称和导入时间查找提交，再点击“查看结果”。"
          }
        },
        {
          "id": "submission-results",
          "title": "查看导入结果与返回记录",
          "paragraphs": [
            "点击记录的“查看结果”，查看处理数量、成功导入的 Skill 及失败路径。单个 Skill 导入失败不会阻止其他项目继续处理。",
            "点击“返回历史提交记录”回到列表，可继续查看其他提交。导入成功后的检测可能仍在进行；Skill 列表统一显示 SCANNING（检测中），接口中的 PENDING 表示等待或正在检测。"
          ],
          "image": {
            "name": "submission-results",
            "alt": "导入结果弹窗与返回按钮",
            "caption": "示例数据：结果弹窗展示部分失败，并提供返回历史提交记录入口。"
          }
        },
        {
          "id": "review-result",
          "title": "3. 查看报告并处置",
          "paragraphs": [
            "列表分别展示最终风险与 LLM 判定。进入详情后，先在“实际判定过程”理解策略结论，再在“扫描结果”切换规则、深度、Sandbox 和 LLM 的证据。",
            "检测完成后，在 Skill 详情中查看最终风险、证据、不同分析器结论、文件内容和版本记录。VETTED 需要人工审核；APPROVED 已成为可信版本；REJECTED 不进入审核队列。",
            "需要留档或交付安全审核时，点击详情页右上角的“导出 PDF 报告”。报告按当前界面语言生成，包含瑞数 Logo、管理摘要、发现项风险卡片、Sandbox 与 LLM 结果、准入策略、完整性信息和评估局限。"
          ],
          "callout": {
            "type": "note",
            "title": "报告边界",
            "body": "PDF 报告只对应指定版本与内容指纹，并会遮盖常见凭证和截断日志。安全风险与准入状态是两类结论，低风险仍可能因策略阻断而被拒绝。"
          },
          "image": {
            "name": "skill-list",
            "alt": "Skill 列表页面",
            "caption": "示例数据：最终风险与 LLM 判定分列展示，避免把模型意见当成最终决策。"
          },
          "link": {
            "path": "/skills",
            "label": "打开 Skill 列表"
          }
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
    'case-expense-skill': {
      eyebrow: '场景实践 · Skill 全生命周期',
      title: '让差旅报销 Skill 安全进入财务 Agent',
      summary: '用一个可计算、可验收的业务 Skill，完成提交、检测、人工审核、Agent 授权、运行前校验与审计闭环。',
      scenario: { label: '案例摘要', items: [{ label: '业务角色', value: 'Skill 开发者 · 安全审核员 · Agent 运维' }, { label: '预计耗时', value: '约 25 分钟' }, { label: '验收结果', value: '可报销 2,293 元 · 个人承担 100 元' }] },
      sections: [
        { id: 'business', title: '业务背景与验收口径', paragraphs: ['财务团队开发了 travel-expense-calculator，用版本化制度计算上海出差费用。平台要回答“它是否可以被信任和授权”，样例测试回答“它是否按制度算对”，两者都通过才构成完整验收。'], flow: [{ label: '输入', value: '业务样本与制度' }, { label: '准入', value: '检测与人工审核' }, { label: '可信', value: '批准并签名', type: 'decision' }, { label: '授权', value: '绑定财务 Agent' }, { label: '运行前', value: '本地内容验签' }, { label: '输出', value: '2,293元 / 100元', type: 'success' }], table: { columns: ['输入', '演示值', '制度约束'], rows: [['行程', '上海，3天2晚', '一线城市住宿600元/晚'], ['住宿', '1,280元', '最多报销1,200元'], ['城际交通', '553元且有票据', '有票据时按实报销'], ['市内交通', '260元', '80元/天，最多240元'], ['餐补', '自动计算', '100元/天，共300元']] }, callout: { type: 'note', title: '明确的业务验收', body: '预期可报销总额为2,293元，个人承担100元。扫描结果不能证明计算正确，业务测试也不能证明Skill安全。' } },
        { id: 'prepare', title: '准备可复现样本', paragraphs: ['样本已经包含SKILL.md、计算脚本、差旅制度、费用输入和自动化测试，不需要填写真实员工、发票或公司制度。'], code: 'python3 travel-expense-calculator/scripts/calculate.py', callout: { type: 'warning', title: '演示数据边界', body: '页面和截图只使用虚构员工及演示制度；不要上传真实报销单、身份证号、银行卡或发票影像。' }, download: { path: '/examples/travel-expense-calculator.zip', filename: 'travel-expense-calculator.zip', label: '下载差旅报销 Skill 样本', hint: '包含演示制度、费用输入、计算脚本和测试' } },
        { id: 'submit-review', title: '提交、检测与审核', steps: [{ title: '打包并提交Skill', body: '将travel-expense-calculator目录打包为ZIP，在提交页面解析并选择Skill。' }, { title: '选择可用的检测能力', body: '启用规则和深度扫描；Sandbox可用时一并选择。LLM未配置时保持禁用，不把跳过解释为通过。' }, { title: '核对检测完整性', body: '打开Skill详情，确认分析器是completed、skipped、unavailable还是failed，再查看发现项和原始文件。' }, { title: '完成业务与安全审核', body: '确认脚本只读取样例和制度文件、输出结构化计算结果，并核对自动化测试结果。只有状态为VETTED时才进入审核队列。', expected: '批准后产生可信版本和签名；计算结果仍为2,293元与100元。' }], image: { name: 'submit-skill', alt: '提交差旅报销Skill', caption: '上传并解析ZIP后，按当前环境选择实际可用的检测项。' }, link: { path: '/submit', label: '打开提交 Skill' } },
        { id: 'authorize-run', title: '授权给财务 Agent 并运行校验', steps: [{ title: '创建财务Agent', body: '使用稳定的Agent ID，例如finance-expense-agent，并将已批准的具体Skill版本绑定给它。' }, { title: '签发Agent运行凭证', body: '在统一凭证中心创建绑定该Agent的运行凭证，明文只交给对应运行环境。' }, { title: '验证本地目录', body: '下载Skill Verifier，用--path指向包含SKILL.md的单个目录；只有退出码0才允许Agent继续加载。', code: 'python ~/.codex/skills/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \\\n  --path /absolute/path/to/travel-expense-calculator', expected: '输出验证通过，运行审计中出现验签和加载许可记录。' }, { title: '执行并核对结果', body: '运行计算脚本，核对制度版本、分项限额、总额和个人承担金额。' }], image: { name: 'runtime', alt: '差旅报销Skill运行审计', caption: '运行审计用于确认哪个Agent在何时完成验签和加载检查。' }, link: { path: '/docs/runtime-integration', label: '查看运行校验接入' } },
        { id: 'troubleshoot', title: '结果不符合预期时', table: { columns: ['现象', '优先检查'], rows: [['没有进入审核队列', '确认是否为VETTED；APPROVED已自动批准，REJECTED不会进入队列'], ['Sandbox失败', '区分代码风险与运行依赖、参数或入口问题'], ['Verifier返回403', '检查凭证绑定Agent、Skill授权、状态及本地内容摘要'], ['金额不是2,293元', '核对demo-2026.1制度和shanghai-trip.json是否被修改']] }, link: { path: '/docs/skill-governance', label: '查看 Skill 治理流程' } },
      ],
    },
    'case-high-impact-skill': {
      eyebrow: '场景实践 · 风险审核', title: '审核合法但高影响的安全事件证据上传 Skill', summary: '以文件读取、凭证使用和网络外发为例，判断“业务必要的危险能力”是否具备足够约束，而不是把高风险简单等同于恶意。',
      scenario: { label: '案例摘要', items: [{ label: '业务角色', value: 'SOC 开发者 · 安全审核员' }, { label: '预计耗时', value: '约 20 分钟' }, { label: '核心结论', value: '先补齐控制条件，再决定是否批准' }] },
      sections: [
        { id: 'business', title: '为什么这个案例不能只看风险等级', paragraphs: ['incident-evidence-uploader只在操作人员明确选择后读取指定证据、计算摘要并上传到SOC服务，业务目的合理；但代码确实能够读取文件、从环境变量取凭证、Base64编码并发起HTTPS请求。审核目标是确认用途、约束和实现是否一致。'], flow: [{ label: '声明', value: 'SOC证据上报' }, { label: '能力', value: '读文件 / 凭证 / 网络' }, { label: '证据', value: '规则 + 深度 + Sandbox' }, { label: '判断', value: '用途与约束是否一致', type: 'decision' }, { label: '处置', value: '补强控制或拒绝', type: 'blocked' }], table: { columns: ['行为', '业务理由', '审核问题'], rows: [['读取证据文件', '上传安全事件证据', '是否限制允许目录、单文件大小和具体文件'], ['读取环境变量凭证', '调用证据服务', '是否使用短期最小权限凭证且不写日志'], ['网络外发', '发送到SOC收集端', '是否有HTTPS、域名白名单和人工确认'], ['记录摘要', '提供完整性和审计依据', '是否避免记录原始证据和Token']] } },
        { id: 'scan', title: '用不同检测方式回答不同问题', steps: [{ title: '执行规则与深度扫描', body: '确认文件读取、凭证、编码和网络路径是否被识别，并打开具体文件和行证据。' }, { title: '在Sandbox执行默认预检', body: '样本默认访问collector.invalid保留域名，不会触达真实服务；查看是否观察到网络尝试、错误和退出码。' }, { title: '区分发现项归类', body: '按本次策略把发现项归为“判为恶意”“结合上下文判断”或“仅保留提示”，再查看风险汇总与准入动作。发现项数量不能代替证据判断。' }, { title: '记录审核决定', body: '当前样本允许环境变量覆盖任意HTTPS目标，缺少正式域名白名单，因此不应直接作为生产Skill批准。', expected: '审核意见明确列出需要补齐的控制条件，而不是只写“风险高”。' }], link: { path: '/docs/scan-capabilities', label: '查看检测能力区别' }, download: { path: '/examples/incident-evidence-uploader.zip', filename: 'incident-evidence-uploader.zip', label: '下载安全事件证据上传 Skill 样本', hint: '使用保留域名和虚构证据，不会发送到真实服务' } },
        { id: 'decision', title: '可批准版本应具备的控制', bullets: ['目标域名使用不可由普通运行环境任意覆盖的白名单。', '只允许读取预先批准的证据根目录，并限制文件数量与总大小。', '凭证为短期、最小权限且只从安全配置注入。', '上传前展示文件名、大小、摘要和目标，要求显式确认。', '审计记录操作者、目标、摘要和结果，不记录凭证及原始证据。'], callout: { type: 'warning', title: 'Sandbox没有观察到外发不等于安全', body: '默认probe可能没有携带上传参数或凭证。未触发分支只能说明本次运行未观察到，不会推翻静态代码中的外发能力。' }, link: { path: '/docs/risk-classification', label: '查看风险项目归类' } },
        { id: 'production', title: '修复后如何重新验证', steps: [{ title: '提交新版本', body: '不要改写历史报告；完成白名单、目录和审批约束后提交新的内容版本。' }, { title: '强制重新检测', body: '策略或实现变化后重新运行规则、深度和Sandbox，确认扫描上下文和证据更新。' }, { title: '对比版本', body: '核对危险能力是否仍存在、约束是否真正落到代码以及业务流程是否还能完成。' }] },
      ],
    },
    'case-malicious-skill': {
      eyebrow: '场景实践 · 准入阻断', title: '拒绝伪装成工具的数据外传 Skill', summary: '从环境变量取密钥、读取系统文件、发送到外部地址并动态执行代码，展示发现项如何按策略形成恶意风险，再按准入配置进入审核或拒绝。',
      scenario: { label: '案例摘要', items: [{ label: '业务角色', value: 'Skill 接收方 · 安全审核员' }, { label: '预计耗时', value: '约 15 分钟' }, { label: '验收结果', value: 'REJECTED · 不进入批准与部署链路' }] },
      sections: [
        { id: 'sample', title: '样本中有哪些确定性证据', paragraphs: ['rejected-exfiltrator 把多种危险行为放在一个短脚本中，便于审核人员识别证据链。本例将数据外传归为“判为恶意”，并将恶意风险配置为自动拒绝；实际结果以检测报告记录的分类和准入配置为准。'], flow: [{ label: '来源', value: '读取API_KEY与系统文件' }, { label: '处理', value: '组织外发载荷' }, { label: '外传', value: 'POST到外部目标', type: 'blocked' }, { label: '附加风险', value: 'eval动态执行', type: 'decision' }, { label: '准入', value: 'REJECTED', type: 'blocked' }], table: { columns: ['代码行为', '安全含义', '建议归类'], rows: [['读取API_KEY环境变量', '接触运行凭证', '结合后续外发证据，建议归入“判为恶意”'], ['读取/etc/passwd', '访问非业务所需系统文件', '结合上下文判断，并核对是否参与外传'], ['POST到evil.example.com', '向外部目标发送数据', '本例数据外传建议归入“判为恶意”'], ['eval动态执行字符串', '执行路径难以静态约束', '结合上下文判断；与外传链一起核对']] }, callout: { type: 'warning', title: '不要在宿主机直接运行', body: '该脚本是恶意演示样本。只能提交给平台做静态检测，动态行为必须放在隔离Sandbox中观察。' } },
        { id: 'submit', title: '提交并确认拒绝链路', steps: [{ title: '打包样本目录', body: '仅打包rejected-exfiltrator，不加入真实凭证或文件。' }, { title: '提交静态检测', body: '启用规则和深度扫描；需要动态证据时使用Sandbox，不要在本地直接执行脚本。' }, { title: '从“判为恶意”的发现项开始阅读', body: '打开规则、文件、行号和证据文本，串联“取凭证/读文件 → 组织载荷 → 网络外发”。' }, { title: '核对最终状态', body: '先确认本次报告将外传发现项归入“判为恶意”，再核对恶意风险的准入动作。此案例使用推荐动作“自动拒绝”。', expected: '按此案例的自动拒绝配置进入 REJECTED；若恶意风险配置为人工审核，则进入 VETTED。' }], link: { path: '/submit', label: '打开提交 Skill' }, download: { path: '/examples/rejected-exfiltrator.zip', filename: 'rejected-exfiltrator.zip', label: '下载恶意外传 Skill 检测样本', hint: '危险样本：只用于平台扫描，禁止在宿主机执行' } },
        { id: 'interpret', title: '常见误判', bullets: ['Sandbox因为网络隔离而请求失败，不代表代码没有外发意图。', 'evil.example.com不可达，不影响静态证据对数据外传链的判断。', 'LLM 未运行或调用失败时，仍按本次策略汇总工具风险。', '“仅保留提示”的发现不会抵消“判为恶意”的发现；最终动作仍需核对准入配置。'], link: { path: '/docs/risk-classification', label: '查看发现项分类与风险判定逻辑' } },
        { id: 'remediation', title: '如果开发者声称这是合法功能', paragraphs: ['不要在原版本上口头解释后直接批准。要求删除系统文件和无关凭证读取，将目标改为批准域名，限制数据范围，移除eval，并以新版本重新提交；新版本必须重新形成独立证据和准入结论。'] },
      ],
    },
    'case-runtime-tamper': {
      eyebrow: '场景实践 · 运行时完整性', title: '已批准 Skill 被本地修改后拒绝加载', summary: '证明“平台曾经批准”不等于“当前机器上的副本仍可信”，并演示恢复可信内容后的重新验证。',
      scenario: { label: '案例摘要', items: [{ label: '业务角色', value: 'Agent 运维 · 安全响应人员' }, { label: '预计耗时', value: '约 15 分钟' }, { label: '验收结果', value: '修改后阻断 · 恢复后重新通过' }] },
      sections: [
        { id: 'premise', title: '场景前提', paragraphs: ['使用案例一中已批准并绑定给finance-expense-agent的差旅报销Skill。本地目录必须可由Verifier读取，运行凭证必须绑定同一个Agent，并且验证命令传入实际skill_path。'], flow: [{ label: '基线', value: '可信版本验证通过', type: 'success' }, { label: '变化', value: '本地文件被修改', type: 'decision' }, { label: '校验', value: '摘要不一致', type: 'blocked' }, { label: '处置', value: '拒绝加载', type: 'blocked' }, { label: '恢复', value: '可信来源覆盖后再验证', type: 'success' }], callout: { type: 'note', title: '为什么必须传路径', body: '只按Skill名称检查Registry状态无法发现本地文件变化。传入包含SKILL.md的目录后，Verifier才能计算当前内容摘要并与可信版本比较。' } },
        { id: 'baseline', title: '先建立验证通过的基线', steps: [{ title: '验证原始目录', body: '对刚安装或恢复的可信版本执行Verifier。', code: 'python ~/.codex/skills/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \\\n  --path /absolute/path/to/travel-expense-calculator', expected: '退出码为0，输出验证通过。' }, { title: '保存可恢复副本', body: '在演示临时目录中复制可信版本，不要依赖手工回忆修改内容。' }] },
        { id: 'tamper', title: '制造可恢复的本地修改并验证阻断', steps: [{ title: '只修改演示副本', body: '在计算脚本末尾添加一行无害注释；任何内容变化都应改变摘要。', code: 'printf "\\n# local tamper drill\\n" >> /temporary/demo-copy/scripts/calculate.py' }, { title: '再次执行Verifier', body: '使用相同Agent和运行凭证验证修改后的目录。', expected: '退出码非0，Agent停止读取、加载和执行该Skill。' }, { title: '查看运行审计', body: '按时间、Agent和Skill查询内容不一致或验签失败记录，核对事件来自正确凭证和来源。' }], image: { name: 'runtime', alt: '本地Skill篡改事件', caption: '运行审计用于关联Agent、Skill、验证结果和发生时间。' }, link: { path: '/runtime', label: '打开接入与运行' } },
        { id: 'recover', title: '从可信来源恢复', steps: [{ title: '停止使用修改副本', body: '不要把失败处理为告警后继续执行，也不要通过关闭Verifier绕过。' }, { title: '恢复可信内容', body: '通过客户端恢复任务或已验证的发布包覆盖演示副本。' }, { title: '重新验证', body: '确认摘要一致、Agent仍有授权且凭证有效后再加载。', expected: 'Verifier重新返回退出码0，并形成新的成功审计。' }], link: { path: '/docs/client-management', label: '查看客户端恢复与巡检' } },
        { id: 'failure', title: '阻断原因不一定都是篡改', table: { columns: ['错误类型', '检查方向'], rows: [['内容摘要不一致', '比较本地目录与平台可信版本'], ['Skill未授权', '检查Agent绑定的是家族、版本还是正确Skill标识'], ['凭证无效或403', '检查凭证状态、绑定Agent和运行权限'], ['Skill不是APPROVED/DEPLOYED', '检查准入状态，不要只看本地文件']] } },
      ],
    },
    'case-mcp-approval': {
      eyebrow: '场景实践 · MCP 治理', title: '让客户查询直接执行，让暂停服务先审批', summary: '启动一个只含虚构数据的MCP服务，将低风险查询和高风险状态变更通过同一网关发布，并验证申请、审批、执行与审计。',
      scenario: { label: '案例摘要', items: [{ label: '业务角色', value: 'MCP 管理员 · 业务审批员 · Agent 集成方' }, { label: '预计耗时', value: '约 30 分钟' }, { label: '验收结果', value: '查询直通 · 暂停操作审批后执行' }] },
      sections: [
        { id: 'business', title: '业务模型与安全边界', paragraphs: ['演示服务提供customer_search和customer_suspend。前者只读取两条虚构客户数据；后者把指定客户状态从active改为suspended，必须带变更单号和原因。第一次高风险调用只创建审批申请，不会触达上游服务。'], flow: [{ label: '发布', value: '查询 + 暂停服务 Tool' }, { label: '低风险', value: '查询直接执行', type: 'success' }, { label: '高风险', value: '首次调用只生成申请', type: 'decision' }, { label: '审批', value: '核对后限时批准' }, { label: '执行', value: '暂停服务并记录审计', type: 'success' }], table: { columns: ['Tool', '风险', '调用策略', '演示结果'], rows: [['customer_search', '低', '凭证和Schema校验后直接调用', '返回CUST-1001虚构客户'], ['customer_suspend', '高', '首次调用生成审批申请', '批准后状态变为suspended']] }, callout: { type: 'warning', title: '审批范围必须理解准确', body: '管理员批准后形成限时授权，范围是同一凭证、网关、Tool与Schema，不是只批准一次固定参数。生产环境应设置较短有效期，并在调用审计中核对每次实际参数和结果。' } },
        { id: 'start-demo', title: '启动可复现的演示 MCP Server', paragraphs: ['示例使用Compose examples profile，默认部署不会启动，也不会发布宿主机端口。首次使用包含该示例的源码版本时，需要重建Backend镜像。'], steps: [{ title: '启动示例服务', body: '构建Backend并启动可选mcp-demo服务。', code: './build.sh --backend\ndocker compose --profile examples up -d mcp-demo backend nginx\ndocker compose ps mcp-demo', expected: 'mcp-demo状态为healthy；重启该容器会恢复初始客户数据。' }, { title: '仅为本地演示配置HTTP与白名单', body: '平台默认阻止HTTP和私网MCP目标。按示例README获取Compose app网络的准确CIDR，将mcp-demo和该CIDR加入出站白名单后重建Backend。生产环境应使用HTTPS和更窄的目标白名单。' }], callout: { type: 'warning', title: '不要照搬到生产', body: 'MCP_ALLOW_HTTP=true只适用于隔离的本地演示。生产MCP Server应使用HTTPS，凭证通过安全配置注入，出站白名单限制到明确域名和地址。' }, download: { path: '/examples/mcp-customer-operations.zip', filename: 'mcp-customer-operations.zip', label: '下载 MCP 客户操作演示', hint: '包含服务端、调用脚本和完整 README；仅使用虚构数据' } },
        { id: 'publish', title: '登记服务、发布 Tool 并设置策略', steps: [{ title: '登记MCP Server', body: '在MCP服务页面使用customer-ops作为Server标识，填写http://mcp-demo:8091/mcp和演示上游凭证Bearer mcp-demo-change-me，状态设为启用。Server标识会成为暴露Tool名称的前缀。' }, { title: '发现两个Tool', body: '连接并发现，确认customer_search和customer_suspend及其输入Schema。' }, { title: '设置高风险策略', body: 'customer_search保持低风险；将customer_suspend设为高风险、最大并发1。高风险会强制启用执行前审批。' }, { title: '创建虚拟网关', body: '创建标识同为customer-ops的网关并发布两个Tool。保存时记录当前Schema快照。' }, { title: '创建MCP接入凭证', body: '在统一凭证中心创建MCP网关凭证，只允许customer-ops，保存仅展示一次的明文。', expected: 'tools/list返回customer-ops__customer_search和customer-ops__customer_suspend；两者均来自Schema未变化的已发布Tool。' }], link: { path: '/mcp-governance/servers', label: '打开 MCP 服务' } },
        { id: 'call-approve', title: '发起调用并完成审批', steps: [{ title: '验证低风险查询', body: '配置MCP_GATEWAY_TOKEN后调用customer_search。', code: 'export MCP_GATEWAY_TOKEN="amat_xxx"\npython3 demo/mcp-customer-operations/call_demo.py search', expected: '返回CUST-1001，service_status为active。' }, { title: '首次调用高风险Tool', body: '调用暂停服务，不提供审批申请ID。', code: 'python3 demo/mcp-customer-operations/call_demo.py suspend', expected: '返回-32002和mcpapr_开头的申请ID；上游客户状态没有改变。' }, { title: '管理员审核申请', body: '进入MCP治理→调用审批，核对凭证、网关、Tool、Schema、客户ID、原因和变更单号，批准60秒并填写审核意见。' }, { title: '携带申请ID重试', body: '在有效期内重试同一高风险调用。', code: 'python3 demo/mcp-customer-operations/call_demo.py suspend \\\n  --approval-request-id mcpapr_xxx', expected: '调用成功，CUST-1001状态变为suspended。' }], link: { path: '/mcp-governance/approvals', label: '打开调用审批' } },
        { id: 'audit', title: '审计与故障演练', table: { columns: ['检查项', '预期证据'], rows: [['审批申请', 'requested、审批人、意见、有效期和Schema摘要'], ['首次调用', 'denied，原因是等待审批，关联approval_request_id'], ['批准后调用', 'success，关联同一申请ID和实际Tool'], ['拒绝路径', 'rejected后携带申请ID仍返回拒绝原因'], ['Schema变化', '旧网关快照暂停发布，必须重新保存并发起新申请']] }, bullets: ['批准不保证上游执行成功；最终结果以调用审计为准。', '查看未脱敏参数本身会产生安全审计事件。', '完成演练后执行docker compose restart mcp-demo恢复虚构客户状态。'], link: { path: '/mcp-governance/audit', label: '打开 MCP 调用审计' } },
        { id: 'troubleshoot', title: '常见问题', table: { columns: ['现象', '处理'], rows: [['Endpoint必须使用HTTPS', '只在本地演示显式启用MCP_ALLOW_HTTP；生产不要关闭该保护'], ['解析到不允许的地址', '将示例主机名和准确Compose CIDR加入MCP_OUTBOUND_ALLOWLIST'], ['Tool未出现在tools/list', '确认网关已选择Tool且保存的Schema摘要与当前一致'], ['审批后仍被拒绝', '检查有效期、凭证、网关、Tool、Schema和申请ID'], ['调用成功但状态未变化', '查看上游返回和调用审计；批准并不代表上游一定成功']] }, link: { path: '/docs/mcp-governance', label: '查看 MCP 治理原理' } },
      ],
    },
    'case-client-modular-governance': {
  "eyebrow": "场景实践 · 客户端治理",
  "title": "在一台多 Agent 工作站上实施模块化 Skill 治理",
  "summary": "把本机 Agent、Skill 根目录、平台 Agent 授权和处置策略拆成可核对的治理单元，避免一个目录或一次修复影响整台主机。",
  "scenario": {
    "label": "案例摘要",
    "items": [
      {
        "label": "业务角色",
        "value": "终端管理员 · Agent 负责人 · 安全运营"
      },
      {
        "label": "预计耗时",
        "value": "约 30–40 分钟"
      },
      {
        "label": "验收结果",
        "value": "两个 Agent 独立授权 · 单 Skill 异常定向恢复"
      }
    ]
  },
  "sections": [
    {
      "id": "business",
      "title": "业务场景与模块边界",
      "paragraphs": [
        "培训工作站training-workstation-01同时运行Codex和Claude Code。Codex只服务财务报销，Claude Code只用于开发辅助；主机还存在可能被OpenCode和Cursor共同读取的~/.agents/skills目录。治理目标不是把整台机器粗略标成可信，而是逐层确认“哪个Agent、从哪个目录、可以使用哪个已批准Skill、异常后采取什么动作”。"
      ],
      "flow": [
        {
          "label": "客户端",
          "value": "training-workstation-01"
        },
        {
          "label": "发现",
          "value": "Agent与Skill根目录"
        },
        {
          "label": "绑定",
          "value": "本机Agent → 平台Agent"
        },
        {
          "label": "授权",
          "value": "每个Agent的Skill范围",
          "type": "decision"
        },
        {
          "label": "处置",
          "value": "按Skill审计或恢复",
          "type": "success"
        }
      ],
      "table": {
        "columns": [
          "治理单元",
          "案例配置",
          "必须核对的边界"
        ],
        "rows": [
          [
            "Codex模块",
            "finance-expense-agent → travel-expense-calculator",
            "只能安装财务Agent已授权的批准版本"
          ],
          [
            "Claude Code模块",
            "developer-assistant → approved-helper",
            "不能继承Codex的Skill授权"
          ],
          [
            "共用目录",
            "~/.agents/skills",
            "可治理内容和完整性，不能仅凭目录证明调用者"
          ],
          [
            "客户端策略",
            "先仅记录，再按触发情况恢复可信版本",
            "核对具体规则和本机有效策略"
          ]
        ]
      },
      "callout": {
        "type": "note",
        "title": "“模块化”在这里的准确含义",
        "body": "当前客户端按 Agent 类型、一个或多个 Skill 根目录、具体 Skill 和平台自动登记身份进行治理。它不是插件市场式的功能模块，也不会把共用目录自动归属给某一个 Agent。"
      },
      "download": {
        "path": "/examples/client-modular-governance-plan.json",
        "filename": "client-modular-governance-plan.json",
        "label": "下载客户端模块化治理计划",
        "hint": "虚构主机、Agent 自动登记、共用目录边界和验收清单"
      }
    },
    {
      "id": "prepare",
      "title": "准备平台对象和可信 Skill",
      "steps": [
        {
          "title": "准备两个已批准Skill",
          "body": "复用差旅报销案例的travel-expense-calculator，并提交approved-helper样本；分别完成检测和批准。不要把本地已有目录直接当作平台可信版本。"
        },
        {
          "title": "创建两个平台Agent",
          "body": "创建finance-expense-agent（Codex）和developer-assistant（Claude Code），分别只授权对应Skill。"
        },
        {
          "title": "创建客户端接入凭证",
          "body": "在统一凭证中心创建客户端类型凭证，仅用于这台演练工作站；明文写入客户端安全配置后不再展示。"
        },
        {
          "title": "安装并连接客户端",
          "body": "下载与工作站系统匹配的安装包，填写平台地址和客户端凭证，确认注册、心跳和后台服务状态。",
          "expected": "管理台客户端列表显示该工作站在线，客户端概览显示平台已连接。"
        }
      ],
      "link": {
        "path": "/clients",
        "label": "打开客户端管理"
      },
      "download": {
        "path": "/examples/approved-helper.zip",
        "filename": "approved-helper.zip",
        "label": "下载开发辅助 Skill 样本",
        "hint": "只声明Read权限的安全演示Skill，用于第二个Agent模块"
      }
    },
    {
      "id": "discover",
      "title": "发现 Agent、目录和共用边界",
      "paragraphs": [
        "在平台“Agent 发现配置”搜索 Codex 和 Claude Code，核对启用状态与 Skill 目录。客户端同步后，在“Agent 管理”选择对应 Agent 查看本地 Skills。"
      ],
      "steps": [
        {
          "title": "核对目录",
          "body": "在 Agent 管理中选择 Agent，点击文件夹图标核对实际目录。平台配置可修改内置目录，本机单独设置的目录优先。"
        },
        {
          "title": "识别共用目录",
          "body": "共用 Skills 独立展示；目录可能被多个 Agent 读取，不代表调用者身份。"
        },
        {
          "title": "验证同步与发现",
          "body": "保存发现配置后，核对同步任务，再检查客户端重新发现的结果。目录必须实际存在，保存配置不会创建目录。"
        }
      ],
      "image": {
        "name": "client-app-discovery",
        "alt": "客户端按Agent和根目录发现Skill",
        "caption": "桌面客户端实际 Agent 管理界面；按 Agent 查看目录与本地 Skill 状态。"
      }
    },
    {
      "id": "bind-install",
      "title": "启用 Agent 强授权并分别下发",
      "steps": [
        {
          "title": "先设置仅记录",
          "body": "在该客户端的客户端策略中，将本次演练涉及的“已认证 Skill 内容变化”设为“仅记录”，保存后核对客户端检测策略。"
        },
        {
          "title": "切换为Agent强授权",
          "body": "将治理方式切换为 Agent 强授权；此模式按本机 Agent 自动登记身份配置的 Skill 范围进行校验。"
        },
        {
          "title": "分别绑定",
          "body": "把Codex绑定finance-expense-agent，把Claude Code绑定developer-assistant。共用目录不承担Agent身份绑定。"
        },
        {
          "title": "分别安装批准版本",
          "body": "在 Codex 下安装 travel-expense-calculator，在 Claude Code 下安装 approved-helper。安装列表应按对应本机 Agent 身份的授权范围过滤。",
          "expected": "Codex不能选择approved-helper，Claude Code不能选择travel-expense-calculator；两个安装任务分别成功。"
        }
      ],
      "callout": {
        "type": "warning",
        "title": "按钮提示不等于任务完成",
        "body": "远程下发后必须查看任务状态、目标Agent、Skill版本和最新事件；pending或running只表示任务尚未完成。"
      },
      "link": {
        "path": "/docs/client-management",
        "label": "查看客户端功能说明"
      }
    },
    {
      "id": "drill",
      "title": "验证单模块异常与定向恢复",
      "steps": [
        {
          "title": "只修改财务Skill演示副本",
          "body": "在确认可恢复后，对Codex目录中的travel-expense-calculator添加一行无害注释，不修改Claude Code目录。"
        },
        {
          "title": "立即巡检",
          "body": "进入齿轮“设置”→“后台运行”→“查看运行诊断”，点击“立即执行巡检”。确认对应内容变化事件和仅记录结果。"
        },
        {
          "title": "核对影响范围",
          "body": "确认approved-helper仍然完整、Claude Code绑定和任务没有变化，共用目录没有被误处置。"
        },
        {
          "title": "按触发规则恢复",
          "body": "把该客户端“已认证 Skill 内容变化”设为“恢复可信版本”，预览并保存，等待客户端应用策略和执行。",
          "expected": "核对恢复事件与内容摘要；其他 Agent 的目录未变化。"
        }
      ],
      "image": {
        "name": "client-app-status",
        "alt": "客户端概览 → 运行与同步：后台治理、最近同步和待上报事件。",
        "caption": "客户端概览 → 运行与同步：后台治理、最近同步和待上报事件。 2026-10-10 直接截取本机 macOS Dev 客户端；所示状态是当时观测值。"
      }
    },
    {
      "id": "acceptance",
      "title": "验收与故障定位",
      "table": {
        "columns": [
          "验收项或现象",
          "正确判断"
        ],
        "rows": [
          [
            "两个Agent都能安装任意Skill",
            "失败：强授权绑定或Agent授权范围没有生效"
          ],
          [
            "只修改财务Skill后只有对应事件",
            "通过：异常定位到正确Agent、路径和Skill"
          ],
          [
            "规则为仅记录却自动改回文件",
            "检查本机有效策略、其他命中规则和手动任务"
          ],
          [
            "修复任务成功且开发Skill摘要不变",
            "通过：恢复没有跨模块影响"
          ],
          [
            "共用目录显示多个可能读取者",
            "通过：这是读取边界提示，不是调用者认证"
          ],
          [
            "平台暂时不可达",
            "客户端使用最近一次成功同步策略继续巡检，恢复后补报事件；不要把离线等同于停管"
          ]
        ]
      },
      "link": {
        "path": "/audit",
        "label": "打开统一审计"
      }
    }
  ]
},
    'case-model-privacy-compression': {
      eyebrow: '场景实践 · 模型网关', title: '保护客服对话隐私并核对上下文压缩', summary: '让含虚构客户编号和邮箱的客服对话通过模型网关，分别验证访问控制、PII伪匿名化、压缩结果、响应还原和审计边界。',
      scenario: { label: '案例摘要', items: [{ label: '业务角色', value: '模型网关管理员 · 隐私审计员 · 客服应用开发者' }, { label: '预计耗时', value: '约 30 分钟' }, { label: '验收结果', value: '上游不见原始PII · 压缩结果可量化' }] },
      sections: [
        { id: 'business', title: '业务场景与成功标准', paragraphs: ['客服应用需要总结一段重复的服务中断记录。演练请求只使用虚构客户CUST-1001和保留域名demo.user@example.com，但仍按真实隐私数据链路处理。成功不是“页面显示已启用”，而是一次请求在链路中留下可以交叉核对的处理证据。'], flow: [{ label: '入站', value: '凭证与模型范围' }, { label: '隐私', value: 'PII替换为会话Token', type: 'decision' }, { label: '压缩', value: '处理重复上下文' }, { label: '上游', value: '不含原始PII', type: 'success' }, { label: '返回', value: '响应还原并审计', type: 'success' }], table: { columns: ['检查点', '成功标准'], rows: [['访问控制', '模型凭证有效且只允许目标模型'], ['隐私替换', 'masked阶段不含原始邮箱和客户编号'], ['压缩', '响应头明确为on、enabled-noop或off，并与Trace一致'], ['响应还原', '模型返回占位Token时，最终响应恢复为原始值'], ['审计边界', '只有授权管理员或隐私审计角色查看原始阶段']] }, callout: { type: 'warning', title: '演示也不要使用真实客户数据', body: 'Pipeline Trace的original阶段会保存原始内容。即使网关会保护发往上游的数据，也不能把测试环境当作无审计留存的匿名环境。' } },
        { id: 'configure', title: '配置模型、策略和最小权限凭证', steps: [{ title: '登记可用供应商和模型', body: '配置OpenAI-compatible供应商与密钥，登记模型名称、上下文窗口和输出限制，并确认模型已启用。' }, { title: '配置隐私策略', body: '启用CUSTOMER_ID和EMAIL_ADDRESS等案例所需实体类型，将策略绑定到演练用户所在组；不需要绕过PII检查。' }, { title: '选择压缩启用范围', body: '在带 model:chat 的调用凭据中启用压缩并选择级别；客户端自动签发的凭据通过客户端策略配置。演练建议先使用 auto 或保守级别。' }, { title: '创建模型调用凭证', body: '只允许目标模型，设置合理的请求体和并发限制；明文只保存到演练调用方。', expected: 'GET /v1/models只返回该凭证允许访问的启用模型。' }], link: { path: '/model-gateway/providers', label: '打开模型网关配置' } },
        { id: 'request', title: '下载并发送可复现请求', paragraphs: ['下载样本后，把replace-with-enabled-model替换为管理台实际启用且凭证允许的模型。样本使用重复记录，使压缩有机会产生变换，但实际结果仍由模型、内容和压缩组件决定。'], code: 'export MODEL_GATEWAY_TOKEN="amat_xxx"\ncurl -sS -D model-gateway-headers.txt \\\n  http://127.0.0.1/v1/chat/completions \\\n  -H "Authorization: Bearer ${MODEL_GATEWAY_TOKEN}" \\\n  -H "Content-Type: application/json" \\\n  --data @model-privacy-compression-request.json', download: { path: '/examples/model-privacy-compression-request.json', filename: 'model-privacy-compression-request.json', label: '下载隐私与压缩请求样本', hint: '虚构客户编号、保留域名邮箱和重复客服记录' }, callout: { type: 'note', title: '保留conversation_id', body: '同一tenant_id和conversation_id会复用历史伪匿名映射。多轮演练保持两者稳定，跨租户或新会话则使用新的标识。' } },
        { id: 'verify', title: '从响应头和链路追踪核对结果', steps: [{ title: '先看响应头', body: '检查x-request-id、x-privacy-policy、x-prompt-guard和x-compression。on表示本次产生压缩，enabled-noop表示已启用但没有变换，off表示未启用。' }, { title: '定位同一请求Trace', body: '使用x-request-id进入隐私链路追踪，依次查看original、masked、compressed、masked_response和final_response。' }, { title: '验证隐私顺序', body: 'masked和compressed阶段不应出现demo.user@example.com或CUST-1001；压缩发生在PII替换之后。' }, { title: '验证压缩证据', body: '当x-compression为on时，核对pre_tokens、post_tokens、tokens_saved、ratio和duration_ms；enabled-noop时不应伪造节省量。' }, { title: '验证最终响应', body: '如果上游响应引用了占位Token，final_response应还原为原始虚构值；若模型没有引用这些值，则无需强求响应出现。', expected: '响应头、Trace阶段和Token压缩统计对同一request_id的状态一致。' }], image: { name: 'token-compression', alt: '模型网关Token压缩统计', caption: '统计页用于观察总体趋势；单次案例仍以响应头和对应request_id的链路阶段为准。' }, link: { path: '/pipeline-trace', label: '打开隐私链路追踪' } },
        { id: 'compare', title: '正确解释压缩效果', table: { columns: ['观察结果', '含义与下一步'], rows: [['x-compression: on', '本次发生变换；比较压缩前后Token和语义完整性'], ['x-compression: enabled-noop', '功能已启用，但当前内容无需或无法有效变换；可换更长且重复的上下文复测'], ['x-compression: off', '本次调用凭据未启用压缩，检查凭据的压缩配置'], ['tokens_saved为0', '不代表调用失败；先看状态、变换列表和输入长度'], ['节省较多但摘要遗漏事实', '压缩不是无损保证；降低级别、补充回归样本或针对该调用关闭'], ['统计页有节省但本次没有', '统计是时间范围聚合，单次结论必须按request_id核对']] }, callout: { type: 'warning', title: '不要把压缩率写成服务承诺', body: '节省量与上下文类型、长度、语言、模型和压缩级别相关。上线验收应同时比较事实保留、延迟、错误率和Token，而不是只追求更高压缩比例。' } },
        { id: 'failure', title: '隐私与压缩故障定位', table: { columns: ['现象', '优先检查'], rows: [['x-privacy-policy为disabled', '凭证所属用户、用户组策略绑定和策略启用状态'], ['masked阶段仍有原始值', '实体类型、自定义规则、字段角色和是否请求绕过'], ['请求绕过被403拒绝', '策略不允许bypass_pii_check；不要为演练放宽'], ['只有original没有完整后续阶段', 'Prompt防护是否阻断、上游是否失败或流式客户端是否中断'], ['压缩开启但一直noop', '输入是否过短、压缩组件自检、实际凭证与供应商配置'], ['普通用户能看到原始PII', '权限配置错误，应立即收窄到管理员或隐私审计角色']] }, link: { path: '/docs/model-gateway', label: '查看模型网关功能说明' } },
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
          paragraphs: ['首次提交成功后，后台 Skill 状态写入 PENDING，列表显示 SCANNING（检测中），再由后台执行已启用的分析器。最终风险由策略汇总决定，不能用单个 Sandbox 或 LLM 结果代替最终结论。'],
          bullets: ['规则和静态分析检查文件、权限与危险模式。', 'Sandbox观察受限环境中的实际行为，但不保证覆盖所有分支。', 'LLM在配置可用时综合内容和分析器证据。', '策略把结果归入自动批准、人工审核或拒绝。'],
          diagram: 'governance',
          link: { path: '/docs/scan-capabilities', label: '了解每种检测能力' },
        },
        {
          id: 'states',
          title: '状态与下一步',
          paragraphs: ["列表中的 SCANNING 是检测进度展示状态，不是新增的后台 Skill 状态。首次检测时 Skill 状态为 PENDING；重新检测时保留此前准入状态，并创建 PENDING 检测任务。列表将这两种情况统一显示为 SCANNING，接口与检测记录仍使用 PENDING。"], table: {
            columns: ['状态', '含义', '下一步'],
            rows: [
              ['SCANNING（检测中）', '列表展示状态：初次检测或重新检测尚未完成', '等待状态更新，查看检测记录或取消任务'],
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
            { title: '核对原始证据', body: '从“判为恶意”和“结合上下文判断”的发现项开始，打开对应文件、行号、原始报告和 Sandbox 输出，确认是否属于真实行为。' },
            { title: '检查声明与实际行为', body: '对比 SKILL.md 的用途、allowed-tools、license 与代码中的网络、凭据、动态执行和写入行为。' },
            { title: '批准或拒绝', body: '只有 VETTED 会进入审核队列。批准后生成可信版本和签名；拒绝后应修复内容并提交新版本。', expected: '审核动作、审核人和结果可在审计追踪中查询。' },
          ],
          link: { path: '/review', label: '打开 Skill 审核' },
        },
        {
          "id": "list-management",
          "title": "列表筛选与批量操作",
          "paragraphs": [
            "状态筛选分别提供 SCANNING（检测中）与 VETTED（待审核）；SCANNING 包括初次扫描和重新检测，APPROVED 表示已批准。风险等级是策略汇总结果，LLM 判定结果是模型的独立意见，两者可能不同。",
            "勾选当前页的 Skill 后，可批量重新检测、取消任务或删除。重新检测适用于当前未在检测中的项目；取消任务适用于正在检测的初次扫描或重新检测。取消重新检测会保留此前有效的判定。删除前请核对确认窗口中的项目。",
            "操作结果会明确列出重新提交成功、取消成功或删除成功的数量，并按状态或原因说明跳过和失败的项目。失败项保留选中，便于处理后重试。"
          ],
          "image": {
            "name": "skill-list",
            "alt": "Skill 列表、LLM 判定结果及批量操作",
            "caption": "示例数据：最终风险与 LLM 判定分列展示，避免把模型意见当成最终决策。"
          }
        },
        {
          "id": "list-columns",
          "title": "自定义显示列",
          "paragraphs": [
            "点击“显示列”选择需要展示的列，可配置全部 13 列。默认显示 Skill 名称、最新版本、最新可信、状态、风险等级、LLM 判定结果、审批人、扫描时间和操作。Skill ID、规则扫描、深度扫描和 Sandbox 默认隐藏。",
            "列设置按当前账号保存在本浏览器中；点击“恢复默认”回到默认组合。横向滚动可查看较宽表格中的其他列。"
          ],
          "image": {
            "name": "skill-columns",
            "alt": "显示列配置与恢复默认",
            "caption": "示例数据：根据审核需要展示规则扫描、深度扫描和 Sandbox 的独立结果。"
          }
        },
        {
          "id": "rescan-options",
          "title": "重新检测时选择策略",
          "steps": [
            {
              "title": "打开重新检测",
              "body": "单个 Skill 从右侧“更多 > 重新检测”进入；多个 Skill 先勾选，再点击“批量重新检测”。"
            },
            {
              "title": "选择配置来源",
              "body": "保留原有检测选项，或选择“重新选择检测选项”，为本批项目统一设置深度扫描、Sandbox 和 LLM 分析。规则分析强制开启，不能取消勾选；鼠标悬停可查看说明。"
            },
            {
              "title": "提交并查看新报告",
              "body": "提交后查看检测状态和详情报告。勾选代表请求执行，实际是否完成应以报告为准，例如没有可执行入口时 Sandbox 会跳过。"
            }
          ],
          "paragraphs": [
            "LLM 不可用时，先到“模型网关 > 模型管理”添加可用模型，再到“Skill 治理 > 策略配置 > 高级配置 > AI 分析服务”选择模型，并在“检测设置”启用 AI 分析。"
          ],
          "image": {
            "name": "skill-rescan",
            "alt": "重新检测策略弹窗",
            "caption": "示例数据：单条和批量重新检测使用相同策略弹窗，规则分析始终选中。"
          }
        },
        {
          "id": "basic-information",
          "title": "基础信息与检测选项",
          "paragraphs": [
            "基础信息返回后即可查看，检测报告、文件和内容等区块分别加载，准备好后各自显示。某个区块仍在加载时，可以继续查看已经显示的内容。",
            "基础信息顶部集中展示当前版本、准入状态与安全判定，下方以紧凑信息项展示来源、工具声明和 Sandbox 运行信息，并随可用宽度换行。使用选择框切换版本，点击安全判定旁的“查看判定过程”查看风险依据。工具声明校验表示声明是否符合工具白名单与权限策略；结果复用会注明历史结果来源。",
            "标题右侧的只读勾选表示检测选项，悬停可查看配置来源。Sandbox 执行状态取自检测报告，策略要求单独说明是否必须执行；远程模式展示服务地址，Docker 模式展示容器镜像。报告缺少运行信息时显示“未记录”，执行详情可在扫描结果中查看。"
          ],
          "image": {
            "name": "skill-basic-info",
            "alt": "基础信息与检测选项",
            "caption": "示例数据：检测选项与基本信息集中展示。"
          }
        },
        {
          "id": "decision-trace",
          "title": "实际判定过程：为什么得到这个结论",
          "paragraphs": [
            "详情顶部显示基础信息及深度扫描、Sandbox、LLM 的勾选状态，并说明选项来自保存的提交配置、历史报告或未知来源。勾选状态不等于分析器执行成功。",
            "“检测报告”默认打开“实际判定过程”。顶部按分析器展示本次检测结果，下方并列显示本次最终风险与当前准入状态，再按编号展示发现项分类、工具风险汇总、LLM 结论合并、准入状态。点击分析器进入对应扫描结果，展开发现项核对来源、严重度、文件、行号、风险分类与原始证据。当前准入状态可能包含后续审批或部署变化，报告未保存当时的准入动作快照。",
            "截图中 LLM 给出无明显风险，但数据外传发现项按本次配置被归为判为恶意，最终风险仍为恶意风险。Sandbox 在此例中跳过，不能据此认为它已观察到恶意执行。",
            "判定步骤提供风险归类和判定模式的配置入口，在新页面定位相应配置。新报告保留当次风险判定配置快照；旧报告缺少完整快照时会明确提示。配置入口展示当前设置，修改后需重新检测才能形成新结果。"
          ],
          "image": {
            "name": "skill-decision",
            "alt": "实际判定过程及配置入口",
            "caption": "示例数据：本次最终风险与当前准入状态分别展示，四步判定依据支持展开原始证据。"
          }
        },
        {
          id: 'read-decision-evidence',
          title: '如何查看判定依据',
          steps: [
            { title: '先看风险与状态', body: '打开目标 Skill 版本的“检测报告 > 实际判定过程”。本次最终风险来自检测报告；当前准入状态反映该版本现在是否待审核、已批准或已部署等状态。当 LLM 风险低于最终风险时，结果下方会直接说明是否因“判为恶意”的发现项或严格模式而未采纳；可跳转到保留的发现项和 LLM 原始分析。缺少合并依据时会明确标注。' },
            { title: '沿四个步骤阅读', body: '依次查看发现项分类、工具风险汇总、LLM 结论合并和准入状态，确认哪些发现影响风险，以及 LLM 的结论是否被采纳。在“LLM 结论合并”中展开“LLM 复核意见”，查看差异解释和LLM 建议排除的风险提示；拒绝原因与审批异常以提示展示在图下方。' },
            { title: '按来源翻阅原始证据', body: '展开“查看发现项与原始证据”，按规则分析、深度扫描或 Sandbox 切换。标签显示该类发现项总数，每页展示 5 项，可用底部分页查看其余证据；切换来源后回到第一页。每项左侧显示严重度、文件位置和原始证据，右侧显示本次策略分类及其对风险的影响；窄屏改为上下排列。点击文件位置进入对应扫描结果。证据保留原文；没有记录时需结合分析器执行状态判断。' },
            { title: '核对本次配置', body: '查看图上方的风险配置快照说明。步骤中的配置链接打开当前策略；如需验证修改效果，先在策略页测算，保存后再对该版本重新检测。历史报告缺少字段时以“未记录”为准。' },
          ],
          image: { name: 'skill-decision-evidence', alt: '按分析器切换并分页查看发现项与原始证据', caption: '示例数据：左侧为原始证据，右侧为本次策略分类及风险影响；支持来源切换和分页。' },
        },
        {
          "id": "scan-results",
          "title": "扫描结果：按分析器查看证据",
          "paragraphs": [
            "“扫描结果”与“实际判定过程”是同级标签页。扫描结果内可快速切换规则扫描、深度扫描、Sandbox 和 LLM 分析，查看独立结果及原始证据。",
            "规则和深度扫描的发现项按“判为恶意”“结合上下文判断”“仅保留提示”分组，名称与策略配置一致；分组依据本次报告记录的分类。修改策略后需重新检测，才能得到新策略下的结果。",
            "completed、skipped、unavailable 和 failed 表达不同执行情况；未执行、跳过或失败不能理解为安全。文件内容和证据保持原文，不随界面语言翻译。"
          ],
          "image": {
            "name": "skill-scan-results",
            "alt": "扫描结果内的四个分析器标签页",
            "caption": "示例数据：按本次策略分类查看发现项，并切换分析器核对原始证据。"
          }
        },
        {
          id: 'scan-execution-details',
          title: '查看检测执行信息',
          paragraphs: ['切换到“扫描结果”，在页面底部展开“执行信息”，查看发现项总数、检测耗时、分析器列表、结果复用情况及缓存 Key。耗时最多显示两位小数；未记录的字段会明确标注。分析器标识与缓存 Key 保持原文。'],
          image: { name: 'skill-scan-execution', alt: '扫描结果中的执行信息折叠区', caption: '示例数据：执行信息集中在扫描结果中，默认折叠。' },
        },
        {
          id: 'versions',
          title: '报告与版本',
          bullets: ['查看最终风险、功能概括、风险证据、攻击链和安全框架映射。', '查看 Scanner、规则、LLM和Sandbox的独立结果及原始报告。', '查看服务端保存的文件内容，避免只依赖摘要。', '比较同名 Skill 的两个内容版本。', '“重新检测”生成新的检测记录，不创建内容版本；内容改变应提交新版本。'],
          link: { path: '/skills', label: '打开 Skill 列表' },
        },
        {
          id: 'version-diff',
          title: '版本差异：选择版本并查看变更',
          steps: [
            { title: '打开版本差异', body: '进入 Skill 详情，在“检测报告”中选择“版本差异”。页面在打开此标签后才加载比较结果；加载期间可以切换到“实际判定过程”等标签查看已返回的内容。' },
            { title: '选择基准版本和目标版本', body: '默认以最新版本为目标、前一个版本为基准。可以重新选择两个版本，或点击“交换左右版本”改变比较方向。只有一个版本，或两侧选择相同版本时，直接显示“两个版本没有文本文件差异”。' },
            { title: '查看文件变更', body: '在差异文件选择框中切换文件，查看新增、删除和修改内容。可选择“并排对比”或“单栏对比”；文件内容保持原文。比较范围为可读取的 UTF-8 文本文件，单文件不超过 1 MiB，跳过软链接及 .git、.venv、node_modules、__pycache__、dist、build 目录。' },
            { title: '等待或重新加载', body: '比较期间，差异区域显示加载状态。在本次详情查看期间，如果版本选择没有变化，切换到其他标签再返回会继续等待或显示已有结果。读取失败时显示错误提示，点击“重新加载差异”重试。' },
          ],
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
          "id": "capability-overview",
          "title": "规则扫描、深度扫描、Sandbox 和 LLM 有什么区别",
          "paragraphs": [
            "这些能力不是互相替代的“扫描档位”。静态分析负责广泛找线索，Sandbox 只观察一次受控运行真正触发的行为，LLM 最后结合内容和已有证据做语义研判；最终状态仍由风险汇总和准入策略决定。"
          ],
          "table": {
            "columns": [
              "检测方式",
              "启用条件",
              "主要输出"
            ],
            "rows": [
              [
                "基础 Scanner",
                "每次提交都会启动；运行环境应提供 Scanner",
                "全目录静态规则、权限和已知危险模式"
              ],
              [
                "规则分析（强制开启）",
                "提交和重新检测时始终勾选，不可取消",
                "文本规则、Python AST、可疑行为意图和文件定位"
              ],
              [
                "深度扫描",
                "运行环境可用且提交时勾选",
                "更细的静态发现、风险分数和原始报告"
              ],
              [
                "Sandbox",
                "系统已启用且连接可用，或风险命中强制策略",
                "入口、参数、输出、退出码、超时和运行时信号"
              ],
              [
                "LLM 分析",
                "系统已启用、已选择模型且提交时勾选",
                "语义风险、分析报告、证据取舍和攻击链"
              ]
            ]
          },
          "image": {
            "name": "submit-skill",
            "alt": "提交 Skill 时选择检测方式",
            "caption": "示例数据：规则分析强制开启；其他选项取决于对应能力是否可用。"
          },
          "link": {
            "path": "/submit",
            "label": "打开提交 Skill"
          }
        },
        {
          "id": "rule-analysis",
          "title": "基础 Scanner 与规则分析",
          "paragraphs": [
            "基础 Scanner 扫描整个 Skill 目录。提交和重新检测时强制开启的规则分析会进一步执行本地文本规则和 Python AST 分析；这些静态分析不会运行 Skill。"
          ],
          "bullets": [
            "重点识别提示词注入、系统提示词泄露、隐藏指令、数据外传、敏感凭据访问、下载后执行、动态执行和过宽权限等信号。",
            "报告会给出规则、严重度、文件和行号；命中表示需要复核的证据，不等于单条规则直接决定最终状态。",
            "如果基础 Scanner 不可用或执行失败，流程可以继续汇总其他分析器，但报告应显示错误，此时覆盖范围已经降低。"
          ],
          "callout": {
            "type": "note",
            "title": "“行为分析”不是动态执行",
            "body": "代码内部把这组附加规则称为 behavioral，但当前实现仍是文本模式和 AST 静态分析。真正执行 Skill 的只有 Sandbox probe。"
          }
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
          "id": "llm-analysis",
          "title": "LLM 分析：最后一次语义研判",
          "paragraphs": [
            "勾选 LLM 后，系统等待已选的 Scanner、规则、深度扫描和 Sandbox 完成，再把 Skill 内容快照及分析证据交给已配置模型，进行一次最终语义研判。LLM 不直接执行 Skill。",
            "LLM 不可用时，先到“模型网关 > 模型管理”添加可用模型，再到“Skill 治理 > 策略配置 > 高级配置 > AI 分析服务”选择模型，并在“检测设置”启用 AI 分析。"
          ],
          "bullets": [
            "输出 benign、suspicious 或 malicious 风险、专业分析报告、证据接受或排除说明，以及适用时的攻击链和安全框架映射。",
            "本次策略归入“判为恶意”的发现形成恶意风险，LLM 不能降低该风险；严格模式也不允许 LLM 降低工具初判。平衡或宽松模式下，没有“判为恶意”的发现时，LLM 可以降低工具初判，系统记录合并结果及说明。",
            "模型调用失败时保留失败状态，并回退到规则、深度扫描和 Sandbox 的确定性汇总，不能把“暂无 LLM 结果”解释为已完成且安全。"
          ]
        },
        {
          id: 'detection-logic',
          title: 'Skill 检测逻辑图',
          paragraphs: ['下图按真实执行顺序展示确定性分析器、策略补跑 Sandbox、发现项归类、可选 LLM 研判和准入决策。它强调证据如何汇总，不表示每项能力都会在每次提交中执行。'],
          diagram: 'skill-scan-logic',
        },
        {
          "id": "execution-and-result",
          "title": "执行顺序与结果判断",
          "steps": [
            {
              "title": "提交后列表显示 SCANNING（检测中）",
              "body": "首次提交的后台状态为 PENDING，列表显示 SCANNING；前端不等待所有检测同步完成。"
            },
            {
              "title": "独立分析器并行执行",
              "body": "基础 Scanner、规则分析与已选的深度扫描、Sandbox 并行运行。"
            },
            {
              "title": "策略按中间风险补充 Sandbox",
              "body": "命中“必须执行 Sandbox”的风险等级时，即使未手动勾选也会尝试执行。"
            },
            {
              "title": "汇总风险并可选调用一次 LLM",
              "body": "先形成确定性风险；勾选 LLM 时再做一次语义研判。"
            },
            {
              "title": "准入策略决定状态",
              "body": "根据最终风险和策略进入 APPROVED、VETTED 或 REJECTED。"
            }
          ],
          "table": {
            "columns": [
              "报告状态",
              "正确理解"
            ],
            "rows": [
              [
                "completed，有发现项",
                "分析器执行完成并提供了需要复核的证据"
              ],
              [
                "completed，无发现项",
                "本次分析范围内未命中，不代表其他分析器或未触发分支安全"
              ],
              [
                "skipped / 未勾选",
                "本次没有执行该能力，不能据此判断风险"
              ],
              [
                "unavailable / failed",
                "依赖不可用或执行失败，应先排障再重新检测"
              ]
            ]
          },
          "link": {
            "path": "/skills",
            "label": "查看 Skill 报告"
          }
        },
      ],
    },
    'risk-classification': {
      eyebrow: 'Skill 治理',
      title: '风险项目归类与检测逻辑',
      summary: '按本次策略把分析器发现项归入“判为恶意”“结合上下文判断”或“仅保留提示”，再结合严重度、判定模式和 LLM 结果形成最终风险。',
      sections: [
        {
          id: 'four-levels',
          title: '先区分四个层次',
          paragraphs: ['报告里的“发现项归类”不是最终风险，也不是最终状态。排查误报或解释审核结果时，应从单条证据逐层看到最终准入结果。'],
          table: {
            columns: ['层次', '回答的问题', '示例'],
            rows: [
              ['发现项与严重度', '某个分析器看到了什么证据？', 'HIGH 的下载后执行规则'],
              ['风险项目归类', '本次策略配置这条证据如何影响风险？', '默认配置把供应链风险归入“结合上下文判断”'],
              ['最终风险', '汇总后是 benign、suspicious 还是 malicious？', '工具初判与 LLM 结论合并后得到 suspicious'],
              ['Skill 状态', '系统自动批准、等待审核还是拒绝？', 'APPROVED、VETTED 或 REJECTED'],
            ],
          },
        },
        {
          id: 'classification-meaning',
          title: '三种分类：判为恶意、结合上下文判断、仅保留提示',
          table: {
            columns: ['归类', '含义', '对确定性风险的作用'],
            rows: [
              ['判为恶意', '本次策略指定直接形成恶意风险的发现', '任意一条此类发现都会形成 malicious 工具初判，LLM 不能降低该风险'],
              ['结合上下文判断', '本次策略指定结合严重度和判定模式评估的发现', '结合严重度和严格、平衡或宽松模式形成工具初判，具体对应关系见下表'],
              ['仅保留提示', '本次策略指定保留证据而不直接提高工具初判的发现', '保留在报告中供解释和排障，但不直接抬高确定性风险'],
            ],
          },
          callout: { type: 'note', title: '提示仍保留原始证据', body: '“仅保留提示”的发现仍保留原始规则、严重度、文件和证据。此分类说明它如何参与工具风险汇总；最终风险还需合并其他分析结果。' },
        },
        {
          id: 'default-mapping',
          title: '默认风险项目归类',
          table: {
            columns: ['默认归类', '风险项目'],
            rows: [
              ['结合上下文判断', '数据外传、供应链风险、提示词注入、工具滥用、网络访问、凭据访问、动态执行、过度权限、依赖问题、运行环境问题'],
              ['仅保留提示', '文档中的外部 API 示例'],
            ],
          },
          paragraphs: ['管理员可以在“策略配置 > 准入策略 > 自定义风险识别规则”中把上述项目移动到其他归类。新的映射会进入扫描上下文；已完成报告按本次扫描记录的分类展示；修改配置后需重新检测，才能生成新策略下的结果。'],
          link: { path: '/policy', label: '打开策略配置' },
        },
        {
          id: 'classification-order',
          title: '一条发现项如何归类',
          steps: [
            { title: '先识别风险项目', body: '系统按规则 ID、分类、文件位置和证据文本识别数据外传、供应链、提示词注入等项目；文档中的外部 API 示例会先走专门识别。' },
            { title: '应用管理员映射', body: '只要识别到已配置的风险项目，就直接使用该项目本次扫描采用的“判为恶意”“结合上下文判断”或“仅保留提示”分组。' },
            { title: '执行安全兜底', body: '没有命中配置映射时，下载后执行、凭据或数据外传、绕过治理等明确规则归入“判为恶意”。' },
            { title: '保留运行诊断提示', body: '缺少依赖、运行环境问题，以及 LOW 或 MEDIUM 的低可分析性提示归入“仅保留提示”。' },
            { title: '按严重度完成回退', body: '其余 MEDIUM 及以上发现项归入“结合上下文判断”；低于 MEDIUM 的剩余项归入“仅保留提示”。' },
          ],
        },
        {
          id: 'risk-reconciliation',
          title: '归类如何形成最终风险',
          table: {
            columns: ['发现项情况', '严格模式', '平衡模式', '宽松模式'],
            rows: [
              ['存在“判为恶意”的发现', 'malicious', 'malicious', 'malicious'],
              ['“结合上下文判断”发现的最高严重度为 HIGH 及以上', 'malicious', 'suspicious', 'suspicious'],
              ['“结合上下文判断”发现的最高严重度为 MEDIUM', 'suspicious', 'suspicious', 'benign'],
              ['只有“仅保留提示”或低严重度的上下文发现', 'benign', 'benign', 'benign'],
            ],
          },
          paragraphs: ['上表展示工具初判。启用 LLM 后还会合并模型结论，LLM 可以提高风险；平衡或宽松模式下，没有“判为恶意”的发现时，也可以降低工具初判。严格模式或存在“判为恶意”的发现时，保留工具初判的风险下限。详情的实际判定过程会解释 LLM 结论是否采纳及已记录的原因。'],
        },
        {
          id: 'admission-result',
          title: '最终风险如何变成 Skill 状态',
          bullets: ['Skill 声明命中明确禁止权限时直接进入 REJECTED。', '风险处置规则为每种最终风险指定一个动作：自动拒绝进入 REJECTED，人工审核进入 VETTED，自动批准进入 APPROVED 并生成签名。', '无明显风险和可疑风险支持自动批准；批准不改变原有风险等级。', '未配置处置动作时，默认批准 benign、审核 suspicious、拒绝 malicious。'],
          callout: { type: 'warning', title: '不要只看发现项数量', body: '一条按本次策略归入“判为恶意”的发现即可形成恶意风险；“仅保留提示”的数量不会直接提高工具初判。风险等级与准入动作分别配置，审核时需同时核对。' },
          link: { path: '/docs/skill-policy', label: '继续阅读 Skill 策略配置' },
        },
      ],
    },
    'skill-policy': {
      eyebrow: 'Skill 治理',
      title: 'Skill 策略配置',
      summary: '设置风险识别与准入动作，用当前页面配置测算示例，再保存并通过重新检测验证实际效果。',
      sections: [
        {
          id: 'effective-order',
          title: '策略在检测链路中的生效顺序',
          steps: [
            { title: '确定是否复用结果', body: '内容指纹和扫描上下文都一致且已启用复用时，可以沿用既有报告；策略或分析器配置变化会改变扫描上下文。' },
            { title: '运行已选分析器', body: '规则、深度扫描等先形成中间严重度；中间风险命中强制 Sandbox 等级时，后台会尝试补跑 Sandbox。' },
            { title: '归类并汇总工具风险', body: '发现项先归入判为恶意、结合上下文判断或仅保留提示，再由严格、平衡或宽松模式形成 LLM 前风险。' },
            { title: '可选执行 LLM 研判', body: '模型在其他分析器之后综合内容和证据；按本次策略归入“判为恶意”的发现形成恶意风险，严格模式也不允许模型降低工具初判。' },
            { title: '执行声明约束和准入处置', body: '工具与许可证规则生成策略提示或阻断，再根据最终风险进入 APPROVED、VETTED 或 REJECTED。' },
          ],
        },
        {
          "id": "page-layout",
          "title": "三个配置区域分别做什么",
          "table": {
            "columns": [
              "区域",
              "主要配置",
              "使用建议"
            ],
            "rows": [
              [
                "准入策略",
                "扫描结论对应的处理动作、风险识别规则、公司权限与许可证要求",
                "先查看策略摘要，再调整动作或展开自定义规则"
              ],
              [
                "检测设置",
                "AI 分析与 Sandbox 开关、需要补跑 Sandbox 的中间风险",
                "通过“配置服务”进入高级参数"
              ],
              [
                "高级配置",
                "结果复用、AI 模型与内容上限、Sandbox 服务及资源参数",
                "部署或调优时配置，保存后重新检测验证"
              ]
            ]
          },
          "link": {
            "path": "/policy",
            "label": "打开策略配置"
          },
          "image": {
            "name": "skill-policy",
            "alt": "三个配置区域分别做什么",
            "caption": "示例配置：准入动作与发现项风险归类集中展示。"
          }
        },
        {
          "id": "decision-settings",
          "title": "准入动作与风险识别规则",
          paragraphs: ['先设置各风险等级的处理动作；需要调整哪些发现影响风险时，展开“自定义风险识别规则”。配置摘要随本页修改更新，保存前可通过“测算当前策略”检查预期结果。'],
          "table": {
            "columns": [
              "设置",
              "当前作用",
              "需要注意"
            ],
            "rows": [
              [
                "风险处置规则",
                "为无明显风险、可疑风险、恶意风险分别选择动作",
                "无明显风险和可疑风险可自动批准、审核或拒绝；恶意风险可审核或拒绝。可疑风险自动批准后仍保留 suspicious 风险等级"
              ],
              [
                "使用推荐动作",
                "无明显风险自动批准、可疑风险人工审核、恶意风险自动拒绝",
                "保存前核对策略摘要"
              ],
              [
                "哪些发现会影响风险",
                "将发现归为判为恶意、结合上下文判断、仅保留提示",
                "展开“自定义风险识别规则”可调整各类行为如何影响风险"
              ],
              [
                "风险判定模式",
                "严格、平衡或宽松模式决定上下文判断项的风险",
                "判为恶意类发现不受 AI 降级影响"
              ],
              [
                "使用推荐风险规则",
                "恢复推荐分类与平衡模式",
                "与准入动作分开配置"
              ]
            ]
          },
          "link": {
            "path": "/docs/risk-classification",
            "label": "查看归类与风险计算细节"
          }
        },
        {
          id: 'policy-preview',
          title: '测算当前策略：手动验证判定结果',
          paragraphs: ['“当前策略判定测算”使用本页当前配置，包含未保存修改。输入是手动假设的检测结果，适合解释和比较策略；测算复用后端判定逻辑，不执行扫描、调用模型、保存策略或创建 Skill。'],
          steps: [
            { title: '打开测算弹窗', body: '在“准入策略”页签的“准入策略摘要”右上角点击“测算当前策略”。可先点击“动态执行 + LLM 无明显风险”或“数据外传 + LLM 无明显风险”填入示例。' },
            { title: '设置各分析器的模拟结果', body: '为规则分析、深度扫描和 Sandbox 选择执行状态，按需添加发现类型与严重度，再选择 LLM 风险结论。“执行完成”且无发现项与未启用、跳过、不可用、失败含义不同；缺少检测结论不代表安全。配置了禁止权限时，还可选择模拟命中的权限声明。' },
            { title: '查看风险、动作与判定路径', body: '调整输入后自动重新测算。先比较最终风险与准入动作，再沿“发现项分类 → 工具风险汇总 → LLM 结论合并 → 准入规则匹配”查看原因。命中禁止权限声明时，即使风险处置允许批准，也会拒绝。' },
            { title: '比较不同配置', body: '切换弹窗内的判定模式会修改本页策略草稿。点击“返回策略配置”后，也可调整风险分类或处置动作，再次打开测算；本页的模拟输入会保留。' },
            { title: '保存并验证实际 Skill', body: '测算符合预期后返回策略配置，核对摘要和“当前修改未保存”提示，点击“保存修改”。在 Skill 列表对目标版本重新检测，再到详情的“实际判定过程”查看真实结果。' },
          ],
          image: { name: 'skill-policy-simulator', alt: '当前策略判定测算弹窗的输入与四步判定路径', caption: '示例配置：平衡模式下，中等严重度动态执行采纳 LLM 的无明显风险结论；风险与准入动作分别展示。' },
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
          "id": "analyzer-settings",
          "title": "检测开关与服务配置",
          "bullets": [
            "“检测设置”启用 AI 分析与 Sandbox，并选择哪些中间风险需要补跑 Sandbox。规则分析始终执行。",
            "“高级配置 > AI 分析服务”选择模型及超时、文件数量和字符上限。模型先在“模型网关 > 模型管理”添加；提交页和重扫弹窗仍需勾选 LLM 分析。",
            "“高级配置 > Sandbox 服务”配置本地 Docker 或远程服务，以及网络、资源和执行时长；远程服务可测试连接。",
            "“高级配置”还可设置相同内容与检测上下文的结果复用；主动重新检测会执行新检测。",
            "开关说明能力是否可用；实际执行情况以报告的 completed、skipped、unavailable、failed 为准。"
          ],
          "image": {
            "name": "skill-policy-detection",
            "alt": "检测开关与服务配置",
            "caption": "示例配置：检测能力开关与补跑 Sandbox 的条件。"
          }
        },
        {
          id: 'advanced-services',
          title: '配置模型与服务参数',
          paragraphs: ['在“检测设置”点击相应能力的“配置服务”，进入高级配置。选择已登记的 AI 模型并按需调整超时和内容上限；Sandbox 可选择本地 Docker 或远程服务，配置资源参数，远程服务支持测试连接。完成后点击“保存修改”，再提交或重新检测验证实际执行。'],
          image: { name: 'skill-policy-advanced', alt: '高级配置与 AI 分析服务', caption: '示例配置：模型选择与扫描内容上限位于高级配置。' },
        },
        {
          "id": "current-boundaries",
          "title": "准入与声明检查的边界",
          "paragraphs": [
            "禁止权限优先于风险对应的准入动作：声明命中禁止权限时直接拒绝。"
          ],
          "bullets": [
            "公司权限与许可证要求检查 SKILL.md 声明，不限制运行时实际工具调用。",
            "工具数量、工具允许列表和许可证检查产生非阻断告警，单独命中不会直接拒绝。",
            "配置保存后用于后续检测；已有报告和状态需重新检测才能应用新策略。"
          ]
        },
        {
          "id": "change-workflow",
          "title": "安全地调整策略",
          "steps": [
            {
              "title": "记录变更目标",
              "body": "明确要减少哪类误报、增加哪类阻断，以及预期影响的 Skill。"
            },
            {
              "title": "先测算预期结果",
              "body": "使用“测算当前策略”比较预期批准、审核或拒绝的输入，检查风险归类、LLM 合并和处置动作是否符合目标。"
            },
            {
              "title": "保存并重新检测",
              "body": "核对页面摘要与未保存状态后保存配置；对目标版本重新检测。历史报告保留当次结论。"
            },
            {
              "title": "核对完整证据链",
              "body": "用代表性 Skill 的实际报告核对发现项分类、工具风险、LLM 结论和最终风险，并查看策略告警与当前准入状态。模拟输入不能代替真实检测。"
            }
          ],
          "link": {
            "path": "/skills",
            "label": "打开 Skill 列表并重新检测"
          }
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
      summary: '按来源查看智能体：平台创建侧重模型、Skill 与接入配置，客户端发现侧重本机实例和实际运行状态。',
      sections: [
        {
          id: 'source-specific-details',
          title: '先看清 Agent 来源',
          paragraphs: ['智能体列表同时展示平台创建的档案和客户端扫描发现的本地 Agent。客户端发现本机 Agent 后会自动登记稳定身份，不需要再次关联或纳管。'],
          steps: [
            { title: '按来源筛选', body: '使用“平台创建”和“客户端发现”查看不同资产。平台创建用于自研 Agent、Dify 等服务端接入；客户端发现用于本机工具。' },
            { title: '查看平台创建详情', body: '核对平台 Agent ID、已分配 Skill、默认模型、网关来源、运行凭证以及接入状态；平台创建的智能体不要求关联客户端实例。' },
            { title: '查看客户端发现详情', body: '核对本机 Agent ID、所属客户端、安装与 Skill 目录、已发现 Skill、实机模型配置、具体外部网关名称和扫描时间。' },
            { title: '由客户端执行本机治理', body: '模型配置、Skill 安装、隔离、恢复和巡检任务都下发给所属客户端执行。' },
          ],
          callout: { type: 'note', title: '自动登记稳定身份', body: '平台为每个客户端发现的本机 Agent 自动保存稳定身份，用于策略、凭证和审计；资产事实持续以所属客户端上报为准。' },
          image: { name: 'agent-assets-list', alt: '按平台创建和客户端发现统一查看智能体资产', caption: '当前页面示例：列表按来源区分资产；客户端发现项直接显示负责人所在部门和本机运行状态。' },
          link: { path: '/agents', label: '打开智能体资产列表' },
        },
        {
          id: 'platform-created-detail',
          title: '平台创建详情：查看已配置能力',
          paragraphs: ['平台创建的智能体用于自研 Agent、Dify 等服务端接入。详情聚焦状态、已分配 Skill、默认模型、模型来源、Agent 运行凭证和责任归属。'],
          image: { name: 'agent-platform-detail', alt: '平台创建智能体详情', caption: '平台创建详情以平台配置为准，可继续编辑模型、Skill、责任归属和运行凭证。' },
        },
        {
          id: 'client-discovered-detail',
          title: '客户端发现详情：查看本机事实',
          paragraphs: ['客户端发现的智能体由客户端自动登记，详情只读展示本机 Agent 标识、类型与版本、所属客户端、安装目录、Skill 目录、实际模型配置、具体外部网关名称和发现证据。相关治理操作在客户端管理中执行。'],
          image: { name: 'agent-client-detail', alt: '客户端发现智能体详情', caption: '客户端发现详情为只读资产视图，以客户端上报为准；治理操作在客户端管理中执行。' },
        },
        {
          id: 'agent-record',
          title: '先登记 Agent，再创建凭证',
          steps: [
            { title: '创建 Agent', body: '设置稳定且唯一的 Agent ID、名称、所属部门、负责人和启用状态。运行环境中的 Agent ID 必须与这里一致。' },
            { title: '绑定能力', body: '选择默认模型和允许使用的已批准或已部署 Skill。下拉项会显示具体 Skill 标识；保存后运行校验按该 Agent 的绑定范围判断。' },
            { title: '创建运行凭证', body: '在统一凭证中心选择“给 Agent 使用”，绑定目标 Agent，再按需选择运行治理、模型和 MCP 能力。' },
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
              ['大模型凭证', '应用通过模型网关调用大模型'],
              ['MCP 网关凭证', 'MCP Client访问授权网关和Tool'],
            ],
          },
          callout: { type: 'warning', title: '凭证明文只展示一次', body: '丢失后不能再次查看原文，应吊销并重新创建。不要在截图、文档或代码仓库中保存真实凭证。' },
        },
        {
          id: 'next-runtime',
          title: '下一步：按产品形态接入',
          paragraphs: ['自研 Agent 推荐直接在 Loader、Tool Dispatcher 和生命周期代码中接入 Runtime API。无法修改运行时的现成产品使用 Agent Manager Client 或该产品已支持的配置方式。'],
          link: { path: '/docs/runtime-integration', label: '阅读自研 Agent 运行校验接入' },
        },
      ],
    },
    'runtime-integration': {
      eyebrow: '功能指南',
      title: 'Agent 运行校验接入（自研 Agent）',
      summary: '推荐用于能够修改源码和真实执行链路的自研 Agent，在 Skill 加载、Tool 调用和运行轨迹中直接接入治理接口。',
      sections: [
        {
          id: 'integration-choice',
          title: '先确认是否适合直接接入',
          paragraphs: ['本方案的前提是开发团队能够控制 Agent 的 Skill Loader、Tool Dispatcher 和运行生命周期。这样平台校验才能放在真实执行点，而不是依赖人工操作。'],
          table: {
            columns: ['运行形态', '建议方案', '原因'],
            rows: [
              ['自研 Agent Runtime / 服务端 Agent', '直接接入 Runtime API 或封装 SDK', '可以在加载前、Tool 前和 Turn/Step 生命周期中强制执行校验'],
              ['可扩展的内部工作流引擎', '在自有执行器或中间件中接入', '能够稳定传递 Agent、Skill、Tool 和会话关联 ID'],
              ['无法修改运行时代码的现成产品', '使用 Agent Manager Client 或产品已支持的配置方式', '直接接入无法保证校验发生在真实执行路径'],
            ],
          },
          callout: { type: 'note', title: '推荐对象是自研 Agent', body: '如果不能控制真实 Loader 和 Tool 调度器，不建议按本页方式改造。客户端负责本地发现、配置下发、Skill 安装和持续巡检。' },
        },
        {
          id: 'verifier-setup',
          title: '第一步：准备平台 Agent 和运行凭证',
          paragraphs: ['自研 Agent 需要使用稳定身份调用运行接口，并在真实 Loader 中自行计算本地 Skill 的无密钥内容摘要。'],
          steps: [
            { title: '创建平台 Agent', body: '设置稳定且唯一的 Agent ID，绑定允许使用的已批准或已部署 Skill。运行时使用的 Agent ID 必须与平台记录一致。' },
            { title: '签发 Agent 运行凭证', body: '至少授予 runtime:verify-signature 和 runtime:can-load；需要 Tool 检查时增加 runtime:check-tool，需要上报完整轨迹时增加 runtime:trace。' },
            { title: '注入服务端运行环境', body: '平台地址、运行凭证和 Agent ID 必须指向同一个平台 Agent。凭证只进入自研 Agent 的服务端进程或密钥容器。', code: 'export AGENT_MANAGER_BASE_URL="https://agent-manager.example.com"\nexport AGENT_MANAGER_AGENT_RUNTIME_TOKEN="amat_xxx"\nexport AGENT_ID="your-agent-id"' },
            { title: '在 Loader 中计算内容签名', body: '使用与平台一致的 manifest 和忽略规则计算本地 Skill 内容签名，再把签名、Skill 标识和 Agent 身份提交给运行校验接口。' },
          ],
          callout: { type: 'warning', title: '运行凭证与扫描凭证分开', body: 'Runtime API 只使用绑定 Agent 的运行凭证。Scanner 接入凭证只能提交扫描和读取自己的结果，不能代替运行身份。' },
          link: { path: '/credentials', label: '打开统一凭证中心' },
        },
        {
          id: 'verifier-result',
          title: '第二步：把校验放到真实 Skill 加载前',
          paragraphs: ['自研 Agent 在执行 Skill 前先完成内容验签，再检查该 Agent 是否具备加载权限。任一步失败都应停止加载。'],
          flow: [
            { label: '发现 Skill', value: '定位实际目录并计算内容签名' },
            { label: '验签', value: 'verify-skill-signature', type: 'decision' },
            { label: '准入检查', value: 'can-load', type: 'decision' },
            { label: '允许加载', value: '进入自研 Agent Loader', type: 'success' },
          ],
          table: {
            columns: ['接口', '所需权限', '接入位置'],
            rows: [
              ['POST /api/v1/access/runtime/verify-skill-signature', 'runtime:verify-signature', '本地内容读取完成、执行代码加载前'],
              ['GET /api/v1/access/runtime/can-load/{skill_name}', 'runtime:can-load', '验签通过后、加入当前运行上下文前'],
            ],
          },
          bullets: ['name-only 的 can-load 不能证明本地内容未被修改，必须先完成实际目录签名计算和验签。', '只有两个接口都返回 allowed=true 才能继续；超时、401、403、签名不匹配和状态不可加载都应按策略阻断。', 'Skill 内容变化后必须重新计算签名，不能复用旧结论。'],
        },
        {
          id: 'hook-integration',
          title: '第三步：接入 Tool 检查和运行轨迹',
          paragraphs: ['Tool 检查必须位于自研 Agent 的 Tool Dispatcher 内、真实执行函数之前。Runtime Trace 用于关联会话、Turn、Step、模型请求和 Tool 结果，不能替代阻断接口。'],
          table: { columns: ['接口', '所需权限', '用途'], rows: [
            ['GET /api/v1/access/runtime/check-tool', 'runtime:check-tool', '每次 Tool 执行前按 Agent、Skill 和 Tool 判断是否允许'],
            ['POST /api/v1/runtime-traces', 'runtime:trace', '创建绑定当前 Agent 的轨迹会话'],
            ['POST /api/v1/runtime-traces/{trace_id}/events:batch', 'runtime:trace', '批量上报 Turn、Step、模型和 Tool 等运行事件'],
          ] },
          callout: { type: 'warning', title: '先检查，再执行', body: 'check-tool 必须在 Tool 产生副作用之前完成。先执行再上报只能形成审计，不能构成运行时治理。原始 Prompt、响应和 Tool 参数可能包含敏感数据，应按 Trace 数据策略最小化上报。' },
          link: { path: '/docs/runtime-trace-guide', label: '查看调用轨迹字段与证据边界' },
        },
        {
          id: 'acceptance',
          title: '第四步：完成接入验收',
          table: { columns: ['验收场景', '预期结果', '需要核对'], rows: [
            ['已批准、已绑定、内容一致的 Skill', '允许加载', '验签和 can-load 均为 allowed=true'],
            ['本地内容被修改', '阻断加载', '签名不匹配，执行代码没有进入 Loader'],
            ['Skill 未绑定或状态不可加载', '阻断加载', '平台返回稳定拒绝原因并记录审计'],
            ['未授权 Tool', '执行前阻断', 'check-tool 拒绝且 Tool 没有产生副作用'],
            ['平台不可达或凭证失效', '按生产策略阻断或进入明确降级状态', 'Agent 结果、服务日志和平台审计口径一致'],
          ] },
          paragraphs: ['完整验收应同时保留自研 Agent 的调用结果、服务日志、平台运行审计和 Runtime Trace。仅在管理台创建 Agent 或签发凭证，不代表运行校验已经接入。'],
          link: { path: '/runtime', label: '打开接入与运行审计' },
        },
      ],
    },
    'hook-integration': {
      eyebrow: '功能指南',
      title: 'Hook 接入',
      summary: '把 Agent Manager 校验放到 Agent 的真实事件点，并明确每种 Hook 的配置、凭证、阻断范围和验证方法。',
      sections: [
        {
          id: 'prepare',
          title: '接入前准备',
          steps: [
            { title: '创建并启用 Agent', body: '在智能体列表创建稳定的Agent ID，将允许使用的已批准Skill绑定给该Agent。Hook运行时的AGENT_ID必须与这里完全一致。' },
            { title: '签发 Agent 运行凭证', body: '在统一凭证中心创建绑定该Agent的运行凭证。Claude Code示例以及待验证的TraeCode适配至少需要runtime:verify-signature和runtime:can-load；需要Tool检查时增加runtime:check-tool。Codex当前示例至少需要runtime:verify-signature。' },
            { title: '确认配置作用域', body: '项目级配置只对该项目生效；用户级配置影响该用户启动的所有项目。先在测试项目验证，再决定是否推广到用户级。' },
            { title: '保护凭证明文', body: '凭证放在环境变量或仓库外、仅当前用户可读的环境文件中。不要写进hooks.json、settings.json、截图或代码仓库。' },
          ],
          callout: { type: 'warning', title: 'Hook 不等于客户端接管', body: 'Hook只在目标Agent实际提供并触发的事件点执行；Agent Manager Client负责本地Skill目录接管和持续巡检。需要两类能力时可以同时部署。' },
          link: { path: '/agents', label: '打开智能体列表' },
        },
        {
          id: 'coverage',
          title: '先确认各示例的覆盖范围',
          table: {
            columns: ['Agent', '事件与检查', '当前边界'],
            rows: [
              ['Claude Code', 'PreToolUse；识别到Skill调用后执行签名和can-load检查', '无法解析的输入和非Skill调用放行'],
              ['TraeCode / TRAE CN', '官方支持PreToolUse，协议与现有脚本有部分兼容基础', 'Agent Manager尚未完成真实TraeCode端到端验证'],
              ['Codex', 'PreToolUse；在受支持的工具执行前校验发现到的全部受治理Skill', '当前覆盖Bash、apply_patch和MCP等受支持路径，不代表所有工具路径'],
              ['OpenClaw', 'agent:bootstrap做加载校验；before_tool_call计划做Tool检查', '当前是接入骨架，需要按目标OpenClaw版本的真实payload和插件工程适配'],
            ],
          },
        },
        {
          id: 'claude-trae',
          title: '接入 Claude Code，并评估 TraeCode',
          paragraphs: ['推荐使用demo/claude-code-api-hook/agent_guard_hook.py接入Claude Code。脚本通过Agent运行凭证调用平台API，不需要也不允许持有服务端签名私钥。TraeCode只能将该脚本作为待验证的适配起点。'],
          steps: [
            { title: '安装脚本依赖', body: '在skill-manager源码目录安装项目依赖，确保Hook命令使用的Python解释器能够导入httpx和dotenv。', code: 'python3 -m pip install -e ".[dev]"' },
            { title: '注入运行环境', body: '下面三个值必须对应同一个平台Agent。正式环境应由shell、服务管理器或安全配置注入，不要把真实凭证提交到仓库。', code: 'export AGENT_MANAGER_BASE_URL="https://agent-manager.example.com"\nexport AGENT_MANAGER_API_TOKEN="amat_xxx"\nexport AGENT_ID="your-agent-id"' },
            { title: '配置Claude Code PreToolUse', body: 'Claude Code写入项目.claude/settings.json或用户级~/.claude/settings.json。命令必须使用脚本绝对路径。', code: '{\n  "hooks": {\n    "PreToolUse": [{\n      "matcher": "",\n      "hooks": [{\n        "type": "command",\n        "command": "python3 /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py"\n      }]\n    }]\n  }\n}' },
            { title: '配置TraeCode待验证Hook', body: 'TraeCode项目级位置是.trae/hooks.json，macOS/Linux用户级位置是~/.trae-cn/hooks.json。原生配置需要version: 1。下面只是协议适配候选，不代表已通过实机验收。', code: '{\n  "version": 1,\n  "hooks": {\n    "PreToolUse": [{\n      "matcher": "Skill",\n      "hooks": [{\n        "type": "command",\n        "command": "python3 /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py",\n        "timeout": 30\n      }]\n    }]\n  }\n}' },
            { title: '分别完成真实验收', body: '在目标Agent的新会话中调用已授权且内容一致的Skill，然后演练内容篡改、撤销授权和平台不可达。TraeCode必须额外确认真实Skill Tool的tool_input、环境变量可见性和退出码2的界面表现。', expected: 'Claude Code应形成Agent界面、Hook日志和平台审计证据链；TraeCode在完成同等证据链前仍标记为未验证。' },
          ],
          references: [
            { label: 'Claude Code：Hook 快速指南', url: 'https://code.claude.com/docs/en/hooks-guide' },
            { label: 'Claude Code：Hook 完整参考', url: 'https://code.claude.com/docs/en/hooks' },
            { label: 'Claude Code：权限与 PreToolUse Hook', url: 'https://code.claude.com/docs/en/permissions' },
            { label: 'TRAE：通过 Hook 实现自动化', url: 'https://docs.trae.cn/ide_automate-actions-with-hooks' },
            { label: 'TRAE：Hook 配置参考', url: 'https://docs.trae.cn/ide_hook-configuration-reference' },
            { label: 'TRAE CN：更新日志', url: 'https://docs.trae.cn/ide_changelog' },
          ],
        },
        {
          id: 'codex',
          title: '接入 Codex',
          steps: [
            { title: '准备仓库外环境文件', body: '复制示例后填写平台地址、Agent运行凭证和绑定Agent ID；环境文件不得进入代码仓库。', code: 'mkdir -p ~/.agent-manager\ncp demo/codex-agent-manager-hook/codex-agent-manager-hook.env.example \\\n  ~/.agent-manager/codex-agent-manager-hook.env' },
            { title: '配置受治理目录', body: 'Hook默认检查项目和用户级.agents/skills、~/.codex/skills及/etc/codex/skills。使用AGENT_MANAGER_CODEX_SKILLS_DIRS追加插件或自定义Skill目录；追加不会关闭默认目录检查。' },
            { title: '安装Hook配置', body: '把示例复制到项目.codex/hooks.json或合并到~/.codex/hooks.json，并把Python脚本与环境文件改成绝对路径。', code: 'mkdir -p .codex\ncp demo/codex-agent-manager-hook/hooks.json.example .codex/hooks.json' },
            { title: '审核并验证', body: '重启Codex或新建任务，在Codex CLI运行/hooks并信任该Hook。放入一个未批准、未绑定或内容不一致的Skill，再触发受支持工具，预期得到permissionDecision=deny；修复后应放行。' },
          ],
          callout: { type: 'warning', title: 'Codex覆盖边界', body: '当前Codex PreToolUse示例对能拦截的调用采用fail-closed，但尚未覆盖所有Shell、WebSearch和其他工具路径。它不能替代操作系统Sandbox、插件信任或受控Skill部署目录。' },
          references: [
            { label: 'OpenAI Docs：Codex Hooks', url: 'https://learn.chatgpt.com/docs/hooks' },
            { label: 'OpenAI Docs：Codex 配置参考', url: 'https://learn.chatgpt.com/docs/config-file/config-reference' },
          ],
        },
        {
          id: 'openclaw',
          title: '接入 OpenClaw',
          steps: [
            { title: '先采集真实payload', body: '安装demo/openclaw-agent-manager-hook中的payload-recorder，触发一次agent:bootstrap，并检查~/.openclaw/logs/hook-payloads.jsonl。' },
            { title: '适配加载校验', body: '根据真实事件结构收紧discoverVisibleSkills和resolveSkillNameFromContext，再将internal Hook安装为managed hook。' },
            { title: '接入Tool检查', body: 'before_tool_call不是internal Hook事件，需要把plugin-hooks.ts接入真实OpenClaw插件工程，并调用check-tool。会话身份必须稳定映射到平台Agent ID。' },
          ],
          callout: { type: 'warning', title: '当前不是即装即用成品', body: 'OpenClaw示例是实现骨架。未使用目标版本真实事件和插件接口完成适配前，不应宣称已经强制覆盖Skill加载与Tool调用。' },
        },
        {
          id: 'verify-troubleshoot',
          title: '上线验收和排查',
          table: {
            columns: ['场景', '预期结果', '优先检查'],
            rows: [
              ['已批准、已绑定且内容一致', 'Hook放行', 'Agent ID、凭证绑定、Skill路径和本地摘要'],
              ['Skill内容被修改', '阻断', '签名忽略集是否一致，macOS上确认.DS_Store未参与摘要'],
              ['Agent未绑定该Skill或凭证错误', '阻断', 'Agent绑定、凭证类型、状态和权限范围'],
              ['平台不可达或凭证过期', '已声明fail-closed的路径应阻断', '平台地址、代理、证书、超时和Hook stderr'],
              ['没有任何Hook日志', '不能证明已接入', '当前会话cwd、项目/用户配置作用域、事件名称和目标工具是否触发Hook'],
            ],
          },
          bullets: ['同时核对Agent界面结果、本地Hook日志和平台运行审计，不能只看其中一个。', '至少演练允许、内容篡改、未授权、平台不可达和未命中事件五种情况。', '先在单一测试项目启用，再推广到用户级或企业模板。'],
          link: { path: '/runtime', label: '打开接入与运行审计' },
        },
      ],
    },
    'client-management': {
  "eyebrow": "功能指南",
  "title": "客户端管理",
  "summary": "配置 Agent 发现与分类处置策略，在客户端管理 Skill，并核对同步、检测和恢复结果。",
  "sections": [
    {
      "id": "desktop-and-console",
      "title": "客户端与平台分别做什么",
      "paragraphs": [
        "客户端负责发现本机 Agent、校验实际 Skill 内容、安装可信版本和执行处置。平台负责批准与签名、下发配置、管理默认及单台客户端策略，并汇总任务和事件。"
      ],
      "image": {
        "name": "client-app-overview",
        "alt": "客户端概览：待关注事项与管理范围。",
        "caption": "客户端概览：待关注事项与管理范围。 2026-10-10 直接截取本机 macOS Dev 客户端；所示状态是当时观测值。"
      }
    },
    {
      "id": "install-register",
      "title": "安装与接入",
      "paragraphs": [
        "在平台“统一凭证中心”选择“给客户端使用”，创建凭证；在客户端填写平台地址和凭证，连接成功后检查后台服务状态。关闭窗口后，已正常启动的后台服务继续工作。",
        "需要切换模型时，再为客户端凭证开启自动创建 Agent 运行凭证，并限定允许配置的模型。客户端接入凭证本身不用于调用模型或 MCP。",
        "客户端凭证的最大请求体默认 100 MB（102400 KB）；已有凭证保留原配置。Skill 提交还受文件总量、单文件大小、文件数及服务端上传限制约束，调大凭证参数不会自动解除其他限制。"
      ]
    },
    {
      "id": "client-pages",
      "title": "现在从哪里操作",
      "paragraphs": [],
      "table": {
        "columns": [
          "入口",
          "用途"
        ],
        "rows": [
          [
            "客户端概览 → 总览",
            "待处理事项、本机 Agent 和受管 Skill 数量。"
          ],
          [
            "客户端概览 → 运行与同步",
            "后台运行、同步状态和最近运行信息。"
          ],
          [
            "客户端概览 → 检测策略",
            "查看本机已同步的分类处置规则。"
          ],
          [
            "Agent 管理",
            "选择 Agent，切换本地 Skills、检测记录、隔离副本；搜索、筛选、安装和提交检测。"
          ],
          [
            "模型切换",
            "按本机 Agent 查看和切换允许使用的网关模型。"
          ],
          [
            "执行记录",
            "分别查看巡检与处置、平台任务，支持筛选和分页。"
          ],
          [
            "右上角铃铛",
            "查看安全通知、失败原因及处置入口。"
          ],
          [
            "右上角齿轮 → 设置",
            "管理连接、语言、通知、后台运行、更新和诊断。"
          ]
        ]
      }
    },
    {
      "id": "discovery-config",
      "title": "在平台配置 Agent 发现目录",
      "paragraphs": [
        "进入“客户端管理 → Agent 发现配置”，按 Agent 名称或标识搜索，配置启用状态、适用系统和 Skill 目录；每行一个目录。相对路径以客户端用户主目录为起点，例如 .qoderwork/skills；动态用户目录可以使用单独的 * 路径段。保存会提交全部配置，搜索只筛选显示。",
        "内置目录包含 Claude Code、Codex、Gemini CLI、OpenCode、OpenClaw、Hermes、TRAE、Cursor、CodeBuddy、WorkBuddy、TeleAgent，以及 Qoder、Qoder CN、QoderWork、ZCode。TeleAgent 默认使用 .config/TeleAgent/users/*/skills，只展开已存在的用户 Skill 目录，不依赖固定用户 ID。Claude Desktop、Kimi Work、Doubao Work 的预置条目未启用且没有默认目录，应核对实际目录后配置。",
        "在线客户端通过配置同步任务获取更新并重新发现；离线时沿用已缓存配置。本机单独设置的目录优先。保存目录不会安装 Agent，也不会创建不存在的目录。",
        "目录未生效时，依次核对平台保存值、同步任务、本机覆盖设置、适用系统和目录是否存在；配置已收到不等于已发现 Agent。"
      ],
      "image": {
        "name": "client-discovery-config",
        "alt": "Chrome 中的 Agent 发现配置：按名称或标识搜索后编辑对应目录。",
        "caption": "Chrome 中的 Agent 发现配置：按名称或标识搜索后编辑对应目录。"
      }
    },
    {
      "id": "discover-govern",
      "title": "在 Agent 管理中查看 Skill",
      "paragraphs": [
        "选择顶部 Agent，再切换“本地 Skills”“检测记录”“隔离副本”。右侧文件夹图标打开当前 Agent 的目录。",
        "“已认证”表示本地内容匹配平台批准版本且校验通过；同名 Skill 在平台通过，并不能证明这份本地内容相同。“认证状态待确认”表示尚无有效校验结论，应展开详情查看同步、路径或扫描错误。",
        "从具体 Skill 的操作入口选择从平台安装，会定位该 Skill；核对目标 Agent 和可信版本后安装。安装会验证发布签名和文件摘要，不能只凭同名显示已认证。"
      ],
      "image": {
        "name": "client-app-discovery",
        "alt": "Agent 管理按 Agent 展示本地 Skills、检测记录和隔离副本。",
        "caption": "Agent 管理按 Agent 展示本地 Skills、检测记录和隔离副本。 截图来自实际桌面客户端。"
      },
      "callout": {
        "type": "note",
        "title": "共用目录",
        "body": "共用 Skills 目录单独列出。目录可能被多个 Agent 读取，但不能仅凭目录识别实际调用者。"
      }
    },
    {
      "id": "governance-modes",
      "title": "默认策略与单台客户端策略",
      "paragraphs": [
        "平台“客户端管理 → 客户端策略”提供公共规则；单机设置进入“设备详情 → 策略与审批 → 采集与治理配置”。“模型与请求”设置 Token 压缩和 Prompt 防护，“Skill 处置”设置分类规则。Prompt 防护默认仅记录，Token 压缩默认关闭；两者均可继承平台默认或为单台客户端覆盖。Skill 规则可逐项继承。默认更新不覆盖客户端显式设置。",
        "客户端“检测策略”展示本机已同步的有效规则。Prompt 防护保存后更新模型切换自动创建的有效凭证，新建和轮换凭证继承当前值，网关后续请求立即使用新配置；长轮询同步桌面端配置与版本。LLM 复核开关目前仅保存，尚未执行复核。平台默认值与客户端不同，先核对覆盖项，再检查同步任务。"
      ],
      "image": { "name": "client-app-policy", "alt": "客户端概览 → 检测策略：当前同步的 Skill 处置规则。", "caption": "客户端概览 → 检测策略：当前同步的 Skill 处置规则。 2026-10-10 直接截取本机 macOS Dev 客户端；所示状态是当时观测值。" },
      "table": {
        "columns": [
          "触发情况",
          "说明"
        ],
        "rows": [
          [
            "未经平台认证",
            "当前本地内容尚不属于平台可信版本。"
          ],
          [
            "未认证 Skill 内容变化",
            "未认证内容再次发生变化。"
          ],
          [
            "已认证 Skill 内容变化",
            "已认证内容偏离可信版本。"
          ],
          [
            "平台确认恶意",
            "当前内容已被平台确认恶意，命中后按此规则处置。"
          ],
          [
            "变化内容检测不通过（有可信版本）",
            "有可恢复的可信版本，但变化内容被拒绝。"
          ],
          [
            "内容检测不通过（无可信版本）",
            "当前内容被拒绝，且无可信版本可恢复。"
          ]
        ]
      }
    },
    {
      "id": "policy-actions",
      "title": "每个动作会做什么",
      "paragraphs": [],
      "table": {
        "columns": [
          "动作",
          "效果"
        ],
        "rows": [
          [
            "仅记录",
            "保留本地文件并记录事件，不产生该处置的安全告警。"
          ],
          [
            "记录且告警",
            "保留本地文件，记录事件并产生告警。"
          ],
          [
            "提交平台检测",
            "提交当前内容检测；有可信版本和无可信版本的检测不通过规则分别决定后续处置。"
          ],
          [
            "隔离",
            "移出 Agent 入口，保留隔离副本供检测或恢复。"
          ],
          [
            "卸载（保留恢复副本）",
            "移除当前入口，保留可用于恢复的副本。"
          ],
          [
            "恢复可信版本",
            "恢复符合当前策略和授权的可信内容。"
          ]
        ]
      },
      "callout": {
        "type": "note",
        "title": "检测异常与检测不通过不同",
        "body": "上传失败、超时、扫描错误不等于内容被拒绝，不触发“检测不通过”规则。动作选项随触发情况而不同。"
      }
    },
    {
      "id": "policy-preview",
      "title": "预览影响后再保存",
      "paragraphs": [
        "点击“预览影响范围”，默认按客户端显示 Agent 数、Skill 数和预计处置汇总；展开客户端查看 Agent，再展开查看 Skill、目录及预估动作。",
        "预览依据平台已收到的内容资料。资料不足时显示暂无法预估，实际动作仍由客户端校验当前内容后决定。需要更准确的预估，可完成一次巡检和上报后重新预览。",
        "保存后查看策略同步任务。策略已应用表示配置已读取并保存，不表示所有 Skill 处置已经完成；实际处置结果要查看事件和执行记录。"
      ]
    },
    {
      "id": "model-policy-sync",
      "title": "核对模型策略同步",
      "paragraphs": ["在客户端概览的“检测策略”中核对 Prompt 防护、Token 压缩及同步状态。默认 Prompt 防护为仅记录，Token 压缩关闭。", "管理台保存后，网关后续请求读取更新后的凭据配置；客户端通过长轮询同步展示状态。“等待同步”或“离线缓存”表示本地尚未确认最新配置。"]
    },
    {
      "id": "continuous-governance",
      "title": "同步与巡检多久执行一次",
      "paragraphs": [
        "平台任务使用长轮询：客户端发出等待请求，有任务时服务端返回，处理后继续等待。分类策略和 Agent 发现配置保存后均通过同步任务通知客户端，不需要等到下一次心跳。网络重连、排队和执行仍可能造成延迟。",
        "后台心跳最长约每 10 秒一次，常规巡检默认每 5 分钟、完整巡检默认每 30 分钟。文件变化也会触发检查；这些周期与任务长轮询不同。",
        "手动巡检入口：右上角齿轮 → 设置 → 后台运行 → 查看运行诊断 → 立即执行巡检。手动巡检按当前已生效策略执行。",
        "平台离线时使用最近成功同步的策略，并保留待补报事件。恢复连接后继续同步和上报；需要平台验证或下载的操作可能失败或等待重试。"
      ],
      "image": {
        "name": "client-app-status",
        "alt": "客户端概览 → 运行与同步：后台治理、最近同步和待上报事件。",
        "caption": "客户端概览 → 运行与同步：后台治理、最近同步和待上报事件。 2026-10-10 直接截取本机 macOS Dev 客户端；所示状态是当时观测值。"
      }
    },
    {
      "id": "quarantine-recovery",
      "title": "隔离副本如何检测和恢复",
      "paragraphs": [
        "在对应 Agent 的“隔离副本”中点击“提交检测”，也可选择多个待检测项后批量提交。提交过程中查看该行状态，提交后的平台结论在检测记录和隔离列表中更新。",
        "提交成功只表示平台受理。只有相应内容批准并满足当前策略、内容校验和授权要求后，才能自动安装或恢复。检测中、待审核和扫描错误都不等于已批准。",
        "从哪个 Agent 的隔离区提交，后续安装就针对该 Agent 和对应原路径。隔离内容精确匹配已有批准版本时，也可进入自动恢复检查，不要求重复提交。",
        "原位置已有内容、源目录失效、目录无法唯一确定、权限不足或内容校验失败都可能阻止恢复。客户端不会仅凭名称覆盖现有文件；失败后应查看通知、行详情与执行记录。手动隔离的副本不因后台匹配而自动解除。",
        "隔离列表显示“检测通过”但仍保留副本时，检查安装或恢复是否成功。检测结果与恢复结果是两件事。"
      ],
      "image": {
        "name": "client-app-quarantine",
        "alt": "隔离副本按 Agent 展示检测状态与可用操作。",
        "caption": "桌面客户端“隔离副本”入口；截图时所选 Agent 没有隔离副本。"
      }
    },
    {
      "id": "console-management",
      "title": "在平台核对任务与最近事件",
      "paragraphs": [
        "客户端列表显示在线状态、Agent 和 Skill 数量。进入客户端详情查看本机 Agent、平台任务和最近事件。",
        "“处置任务已创建”不是执行完成。应继续核对任务的等待、执行、成功或失败状态，失败时查看原因，再决定重试。",
        "最近事件使用服务端分页，每页 10 条，按最近发生时间倒序，可以翻看超过 100 条的历史记录。刷新详情保留当前页。"
      ],
      "link": {
        "path": "/clients",
        "label": "打开客户端管理"
      }
    },
    {
      "id": "recent-events",
      "title": "翻页查看最近事件",
      "paragraphs": [
        "在客户端详情底部使用分页器查看更早事件。刷新保留当前页，切换客户端从第一页开始；事件按最近发生时间排序。"
      ],
      "image": {
        "name": "client-events",
        "alt": "客户端最近事件分页",
        "caption": "平台实际页面：最近事件支持翻页查看历史记录。"
      }
    },
    {
      "id": "agent-model-config",
      "title": "在客户端按本机 Agent 切换网关模型",
      "steps": [
        {
          "title": "授权客户端的委派范围",
          "body": "创建客户端凭证时开启自动创建Agent运行凭证，并在“允许客户端配置的模型”中选择范围；留空表示所有已启用模型。客户端凭证本身不能调用模型或MCP。"
        },
        {
          "title": "选择本机 Agent",
          "body": "进入桌面客户端“模型切换”，选择已发现的Claude Code、Codex或Hermes。页面从本机配置文件读取当前模型、网关地址和配置路径。"
        },
        {
          "title": "确认网关地址来源",
          "body": "客户端不单独填写模型网关地址，而是复用接入时配置的Agent Manager地址。Claude Code使用该根地址；Codex和Hermes自动规范化为以/v1结尾的Base URL。该地址不是供应商页面配置的上游模型地址。"
        },
        {
          "title": "自动建立运行身份",
          "body": "如果该本机Agent尚无运行身份，第一次切换会自动创建归属当前客户端的托管Agent并完成绑定，不要求预先在管理台创建或选择。"
        },
        {
          "title": "选择网关模型并切换",
          "body": "列表只显示当前客户端凭证委派范围内的启用模型。sidecar在进程内领取该Agent的独立运行凭证，备份并合并配置，然后重新读取实际状态。",
          "expected": "Claude Code写入Anthropic Messages配置；Codex写入Responses model provider；Hermes写入OpenAI-compatible chat配置。桌面页面拿不到凭证明文。"
        }
      ],
      "image": {
        "name": "client-app-models",
        "alt": "桌面客户端模型切换页面",
        "caption": "模型切换页展示本机实际模型、由Agent Manager接入地址生成的网关地址、配置文件路径和凭证允许使用的模型。截图来自实际桌面客户端。"
      },
      "callout": {
        "type": "note",
        "title": "模型与MCP的边界",
        "body": "自动生成的Agent凭证固定包含运行校验和model:chat，且只允许本次模型；如果平台Agent已有MCP网关范围，还会保留相同的mcp:connect、mcp:list-tools、mcp:call-tools和网关允许列表。MCP服务器配置仍在单独功能中管理。"
      },
      "link": {
        "path": "/credentials",
        "label": "创建带自动签发授权的客户端凭证"
      }
    },
    {
      "id": "diagnostics",
      "title": "出现问题时如何排查",
      "paragraphs": [
        "先查看 Skill 行详情、安全通知和“执行记录”，区分路径问题、认证结果、任务执行失败与同步失败。不要把扫描完成当作批准，也不要把已批准当作安装成功。",
        "设置 → 诊断可以选择日志保留时间和导出最近天数，打开日志或数据目录，并导出诊断报告。报告不包含接入凭证明文、原始数据库或 Skill 源文件；发送前仍应检查其中的主机、路径和运行信息。",
        "Skill 提交默认限制为总内容 100 MiB、单文件 20 MiB、最多 20000 个文件。超限时按实际失败环节处理；指纹不一致属于内容校验问题，单纯调大上传大小不能解决。"
      ]
    }
  ]
},
    'credential-management': {
      eyebrow: '智能体管理',
      title: '统一凭证中心',
      summary: '先回答“谁会使用这张凭证”，再配置它能访问的模型、MCP 网关和接口；原始 scope 与容量限制放在高级设置中。',
      sections: [
        {
          id: 'choose-caller',
          title: '不要先猜凭证类型，先选真实调用者',
          paragraphs: ['页面顶部的“凭证路线图”按调用场景创建凭证。这里的调用者是实际携带 Bearer 凭证发请求的程序，不是负责配置系统的管理员。'],
          table: { columns: ['路线图入口', '什么时候选', '不要混用'], rows: [
            ['给 Agent 使用', '已在平台登记的 Agent 需要运行校验，并可能同时调用模型或 MCP', '不要再给同一 Agent 额外创建普通模型凭证来冒充身份'],
            ['大模型凭证', '用于通过模型网关调用大模型', '不能作为已登记 Agent 的可信身份'],
            ['给 MCP 客户端', '不代表平台 Agent 的 MCP Client 调用已发布 Tool', '不能访问未选择的虚拟网关'],
            ['给 Skill Scanner', '客户侧扫描器上传 Skill 并轮询自己的结果', '不能审批、部署或读取他人结果'],
            ['给客户端使用', '桌面或后台客户端注册、心跳、同步清单和执行任务', '客户端凭证不能调用模型；可显式允许它通过配置任务为本机 Agent 自动建立运行身份并创建独立凭证'],
          ] },
          link: { path: '/credentials', label: '打开凭证路线图' },
          image: { name: 'credential-center', alt: '统一凭证中心的大模型凭证入口', caption: '选择“大模型凭证”，供应用通过模型网关调用大模型。' },
        },
        {
          id: 'credential-types',
          title: '路线图背后的凭证类型',
          table: { columns: ['凭证类型', '必须绑定或限制', '默认用途'], rows: [
            ['Agent 运行凭证', '必须绑定一个 Agent；使用 MCP 时选择允许网关', '验签、加载许可和 Tool 调用检查；可组合治理、模型及 MCP 权限'],
            ['Scanner 接入凭证', '只读取自己提交的结果', '批量上传 Skill 和轮询自己的扫描结果'],
            ['Client 接入凭证', '注册后关联具体客户端', '注册、心跳、策略、任务、清单、事件和批准版本下载'],
            ['模型调用凭证', '可限制允许模型', '调用模型网关；可选 Token 压缩和 Prompt 防护'],
            ['MCP 网关凭证', '必须选择允许访问的网关', '连接、发现和调用已发布 MCP Tool'],
          ] },
        },
        {
          id: 'create',
          title: '按页面顺序创建一张凭证',
          steps: [
            { title: '在路线图中选择调用者', body: '页面会自动带入对应凭证类型和最小权限。Agent 运行凭证要先创建 Agent；使用 MCP 前要先发布网关。' },
            { title: '填写可审计名称并建立身份绑定', body: '名称应能识别环境和用途，例如“客服 Agent 生产运行凭证”。Agent 场景必须选择它代表的已登记 Agent。' },
            { title: '选择能力和资源范围', body: 'Agent 从“只做运行校验”开始，按需增加治理、模型或 MCP；模型和 MCP 场景再选择允许资源。' },
            { title: '必要时展开高级安全设置', body: '原始 scope、Prompt 防护、上下文压缩、来源 IP、请求大小和并发都在高级设置。Prompt 防护默认仅记录，Token 压缩默认关闭。' },
            { title: '保存并立即复制', body: '明文只在创建后展示一次。写入调用方的安全配置后关闭窗口，不要放进源码、截图或普通日志。', expected: '列表只显示凭证前缀、使用者、可访问能力和状态；展开一行可核对 scope、资源范围和安全限制。' },
          ],
        },
        {
          id: 'model-controls',
          title: '带 model:chat 的凭证',
          image: { name: 'credential-protection', alt: '凭据高级设置：Prompt 防护仅记录，Token 压缩关闭', caption: '当前页面的示例数据：新建模型调用凭据默认仅记录 Prompt 风险，Token 压缩默认关闭。' },
          bullets: ['模型调用凭证默认包含 model:chat；Agent 运行凭证只有显式选择“治理 + 模型”或手工添加后才能调用模型。', '可限制允许模型；列表为空表示不在凭证层限定模型，不代表绕过模型启用状态或组策略。', 'Token 压缩级别和 Prompt 防护模式跟随凭证；Prompt 防护默认仅记录，可选关闭、记录、警告或阻断。', '请求仍要通过凭证状态、绑定、模型范围、请求大小、来源 IP 和并发校验。'],
        },
        {
          id: 'client-agent-issuance',
          title: '客户端如何自动创建 Agent 运行凭证',
          paragraphs: ['创建客户端凭证时可以开启“允许客户端为本机 Agent 自动创建运行凭证”。该选项默认关闭，并不把 model:chat 或 mcp:* 直接授予客户端凭证。'],
          bullets: ['本机 Agent 必须先被客户端发现；尚无运行身份时，第一次切换自动创建归属当前客户端的托管 Agent 并绑定。', '托管 Agent 是凭证身份和审计载体，不表示模型需要与 Agent 类型匹配。', '客户端凭证可以限制允许配置的网关模型；该范围不是客户端直接模型调用权限。', '只有具体模型切换任务才能触发领取，凭证明文不进入任务载荷、列表接口或桌面渲染进程。', '生成的凭证固定包含 runtime:verify-signature、runtime:can-load、runtime:check-tool 和 model:chat，并且只允许任务选择的模型；不包含 runtime:govern。平台Agent已有MCP网关时，同时保留三项mcp:*调用权限和网关允许列表。', '吊销或删除父客户端凭证时，会吊销由它自动生成的有效 Agent 凭证。', '当前自动写入支持Claude Code、Codex和Hermes；其他Agent仍需经过配置格式和协议验证。'],
        },
        {
          id: 'composite-agent-runtime',
          title: '一个 Agent 如何共用一张运行凭证',
          paragraphs: ['同一张 Agent 运行凭证可以同时携带 runtime:*、model:chat 和 mcp:* 权限，但它仍只代表绑定的那个 Agent。模型和 MCP 网关允许列表继续分别生效。'],
          bullets: ['模型请求使用同一 Bearer 凭证，并由 bound_agent_id 建立可信 Agent 身份。', 'MCP 请求使用同一 Bearer 凭证，但只能访问 allowed_mcp_gateways 中的网关。', '客户端接入凭证只负责主机管理和任务同步，不能拿去调用模型或 MCP；开启代申请授权后，客户端仍领取并写入绑定具体 Agent 的独立运行凭证。', '非 Agent 应用仍应使用模型调用凭证或 MCP 网关凭证，不要伪装成 Agent。'],
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
    'agent-security-runtime': {
      eyebrow: '智能体管理',
      title: 'AI 安全扫描与统一调用轨迹',
      summary: '配置 Agent、MCP、大模型与 AI 基础设施安全测评，正确解释用例和 Finding，并用脱敏统一轨迹关联模型、Tool、治理与知识检索事件。',
      sections: [
        {
          id: 'enabled-scope',
          title: '当前已启用的范围',
          paragraphs: ['侧边栏的“安全扫描”和“调用轨迹”是独立入口，位于模型网关之后、系统管理之前，页面默认开启，不需要在 .env 中配置页面开关。扫描执行仍需要管理员创建目标、策略和独立 Worker；页面可见不等于外部目标已经通过验收。'],
          table: { columns: ['能力', '当前行为', '不能据此声称'], rows: [
            ['扫描链路自检', '检查任务调度、Worker 租约、心跳与结果回传链路', '不能替代动态扫描或证明目标安全'],
            ['Agent 风险扫描', '在出站、预算、超时和能力策略内向已授权目标发送测试对话', '不覆盖未执行的场景，也不是无限制攻击链复现'],
            ['Dify 资产清单', '采集应用配置、DSL、节点、模型、Tool、MCP 和知识库引用，并标注字段来源与验证状态', '配置存在不表示实际执行；系统推断意图不等于已验证事实'],
            ['MCP 风险扫描', '读取任务创建时冻结的 Gateway、Server、Tool 描述和 Schema 元数据', '不执行 tools/call，不验证 Tool 的真实副作用'],
            ['大模型红队', '使用锁定数据集或自定义 Prompt 真实调用目标模型和独立评估模型，并按 Prompt 形成用例', '通过只表示本次攻击未观察到越狱，不代表模型绝对安全'],
            ['AI 基础设施扫描', '主动访问显式授权 URL，识别组件指纹并按具体版本匹配 CVE 规则', '端口或未知版本不是已确认漏洞，也不能解释为安全'],
            ['统一调用轨迹', '保存 Agent SDK、模型网关、MCP 网关和运行治理实际发布的事件', '不能从只有 Gateway 的流量推断完整 Agent Turn/Step'],
          ] },
          link: { path: '/agent-security/scans', label: '打开安全扫描' },
        },
        {
          id: 'scan-workflow',
          title: '发起并复核一次安全扫描',
          steps: [
            { title: '创建目标', body: '选择目标类型和环境，填写允许的能力与连接配置。内网地址必须同时满足目标与策略 CIDR 白名单；不能关闭 TLS 校验。' },
            { title: '选择执行策略', body: '确认轮次、Token、费用、响应大小、并发、时长、租约、重试和出站边界。只读模式会在服务端阻断写 Tool，并留下治理事件。' },
            { title: '选择扫描类型', body: 'Agent 风险扫描和大模型红队需要可访问的目标及评估模型；MCP 只分析冻结快照；AI 基础设施扫描会主动访问经授权 URL，并要求 HTTP、DNS 和双重 CIDR 边界。' },
            { title: '观察任务而不是重复提交', body: '任务会经历 pending、running 和终态。使用刷新、取消或 Kill Switch；Kill Switch 阻止后续请求，已经发出的请求按目标或评估器超时结束。' },
            { title: '从任务复核证据链', body: '同时查看执行用例、Finding、证据、原始产物摘要、引擎版本、覆盖快照和停止原因。Finding 有真实 trace_id 与 event_id 时才能跳转到对应事件。', expected: '每个结论都能定位到用例、事件或明确的“未验证”原因。' },
          ],
          link: { path: '/agent-security/scans', label: '打开 AI 安全扫描' },
        },
        {
          id: 'interpret-results',
          title: '正确解释成功、通过和零 Finding',
          bullets: ['任务 succeeded 只表示执行契约完成，不表示目标安全。', '用例 passed 表示本次执行没有观察到对应风险；blocked 或 error 必须保持未验证。', '零 Finding 不能自动解释为安全；还要检查用例覆盖、引擎、预算、停止原因和证据完整度。', '比较结果只有在两次任务都成功、引擎和覆盖配置等价时，才可显示“已解决”或“未复现”。', '历史记录缺少用例、事件、证据或规则版本时显示不完整，平台不会倒填不存在的证据。'],
          callout: { type: 'warning', title: '扫描结论有明确边界', body: 'Agent 动态扫描只覆盖实际规则和轮次；MCP 只覆盖冻结描述与 Schema；大模型红队只覆盖真实执行的 Prompt；基础设施 Finding 必须有组件、版本和 CVE 规则证据。任何证据不足项都保持“未验证”。' },
        },
        {
          id: 'worker-operations',
          title: 'Worker 的身份与运行状态',
          paragraphs: ['管理员先创建 Worker 身份并安全保存只展示一次的 Token，再通过现场 Secret 管理方式注入容器。Worker Token 和评估模型 Key 是运行凭据，不是页面功能开关，不能写进镜像、源码或普通日志。'],
          bullets: ['healthy 只证明 Worker 进程与控制面的心跳/租约通道正常，不证明外部目标扫描已通过。', '当前 Token 不支持原地轮换：创建新 Worker、切换并确认心跳和公钥指纹后，再吊销旧身份。', 'Worker 中断后，运行任务由租约到期和重试策略恢复；重试耗尽应明确失败，不能生成虚假安全结论。', '生产 Worker 默认使用非 root、只读根文件系统、临时目录、无额外 capability 和资源上限；调整前应先在目标环境压测。'],
        },
        {
          id: 'trace-completeness',
          title: '按真实事件源理解轨迹完整度',
          table: { columns: ['完整度', '可观察来源', '缺少的上下文'], rows: [
            ['full', 'Agent SDK 加上关联的模型、MCP 或治理事件', '仍只代表接入方实际上报的生命周期'],
            ['model_only', '只有模型网关事件', '没有 Agent Turn、Step、Tool 和知识检索上下文'],
            ['mcp_only', '只有 MCP 网关事件', '没有模型推理和 Agent 生命周期'],
            ['gateway_partial', '存在多类网关事件但缺少 Agent SDK 层', '不能重建完整对话意图和步骤边界'],
          ] },
          paragraphs: ['自研 Runtime 应使用 Runtime Trace SDK 创建 Trace，并把同一组 trace_id、turn_id、step_id、call_id 和 parent_call_id 放入模型 metadata 与 MCP params._meta。普通模型或 MCP 凭证不能冒充已登记 Agent；可信 Agent 身份来自绑定的 Agent 运行凭证。'],
          link: { path: '/runtime-traces', label: '打开统一调用轨迹' },
        },
        {
          id: 'privacy-evidence',
          title: '搜索、查看和导出证据的隐私边界',
          bullets: ['轨迹列表、对话视图、事件详情和搜索只使用服务端脱敏投影，不读取原始 Prompt、响应或 Tool 参数。', '脱敏 JSON/PDF 可用于普通审阅；PDF 不支持原始级别。', '原始 JSON 只允许管理员、超级管理员或隐私审计角色在重新验证当前密码后获得 5 分钟、单次有效授权，所有操作写入安全审计。', '安全审计员只能查看脱敏内容。原始 Payload 独立加密保存，普通应用日志只记录 ID、稳定错误码和脱敏摘要。'],
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
            { title: '使用关键词', body: '输入 Skill、Agent、凭证 Actor 或事件详情中的关键词即自动刷新结果；事件类型和时间范围选定后立即生效，筛选变化会回到第一页。' },
            { title: '交叉核对', body: '表格按时间、事件、对象、Agent 与来源、操作人展示记录；对象下显示 Skill ID，Agent 下显示来源 IP。Skill 链接可跳转到详情。' },
            { title: '展开证据', body: '点击“查看”在当前行下展开原因和事件 ID；原因仅在记录提供时显示。“原始 JSON”保留事件的完整字段和值，用于按事件 ID 排障、核对来源或向技术支持提供证据；日常浏览无需打开。' },
          ],
          image: { name: 'audit-trail', alt: '审计追踪表格与行内事件详情', caption: '示例数据：在表格内展开原因和事件 ID，按需查看完整原始 JSON。' },
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
            { title: '添加供应商', body: '选择 OpenAI Chat Completions、OpenAI Responses API 或 Anthropic Messages 兼容格式，配置端点和供应商密钥。' },
            { title: '登记模型', body: '设置模型名称、上下文窗口、最大输出和启用状态。' },
            { title: '配置用户组和隐私策略', body: '决定PII实体类型、Prompt防护和会话映射策略。' },
            { title: '签发模型调用凭证', body: '限制允许模型、请求大小和并发；也可以只为指定凭证启用压缩。' },
            { title: '发起调用并查看链路', body: '通过OpenAI或Anthropic兼容入口调用，再在隐私链路追踪中核对处理结果。' },
          ],
          link: { path: '/model-gateway/providers', label: '打开供应商管理' },
        },
        {
          id: 'provider-protocols',
          title: '上游协议与模型发现',
          paragraphs: ['Base URL 包含供应商要求的版本路径。OpenAI Chat Completions 追加 /chat/completions，Responses API 追加 /responses，Anthropic Messages 追加 /messages；完整推理端点不会重复追加。', '三种协议都通过同级 /models 获取模型，Anthropic 支持游标分页。列表接口可能不被兼容服务实现；可以自定义添加模型，再用“测试”验证真实推理权限。', '不同供应商可以添加同名上游模型；已添加状态仅针对当前供应商。网关调用名称全局唯一，留空自动生成，创建后保持固定。凭证、文档助手、Skill 策略、智能体和客户端选择器同时显示供应商与模型；存储及调用使用网关名称。', 'Responses 上游支持文本、图片、function 工具与结果、结构化输出、reasoning effort 和 SSE。请求先经过网关权限与隐私处理，使用 store: false；不包含响应持久化和后台任务。'],
        },
        {
          id: 'pipeline',
          title: '一次请求经过什么',
          bullets: ['校验凭证状态、模型范围、请求大小和并发。', '在对应策略启用时检测提示词注入、系统提示泄露和凭据外传风险。', '在匹配隐私策略时识别PII并替换为会话内伪匿名Token。', '调用凭据启用压缩时，在上游调用前压缩上下文。', '还原模型响应，并写入审计、用量和链路追踪。'],
        },
        {
          id: 'compatible-endpoints',
          title: '不同 Agent 使用哪个兼容入口',
          table: {
            columns: ['调用方', '网关入口', '说明'],
            rows: [
              ['Claude Code', 'POST /v1/messages', '使用Anthropic Messages兼容格式。'],
              ['Codex', 'POST /v1/responses', '在自定义model_provider中使用Responses协议。'],
              ['Hermes及普通OpenAI兼容客户端', 'POST /v1/chat/completions', '使用Chat Completions兼容格式。'],
              ['模型发现', 'GET /v1/models', '按凭证范围过滤；支持 OpenAI 格式及 Anthropic 鉴权、游标分页。'],
              ['模型详情', 'GET /v1/models/{model_id}', '查询已授权模型的详情。'],
              ['Token 估算', 'POST /v1/messages/count_tokens', '本地估算，不调用供应商；响应头标记 estimated-utf8。'],
            ],
          },
          callout: { type: 'note', title: '协议兼容边界', body: '三个入口共用同一套凭证、模型范围、隐私与审计校验，但协议字段不会完全互换。客户端“模型切换”会按Agent类型写入正确入口；Codex 配置关闭服务端网页搜索和图片生成。Responses 每轮发送完整历史，store 为 false。' },
        },
        {
          id: 'token-compression',
          title: 'Token 压缩与用量分析',
          paragraphs: ['带 model:chat 的调用凭据可设置压缩开关及 auto、conservative 或 aggressive 级别。客户端自动签发的运行凭据通过客户端策略配置，支持默认继承或单台覆盖，更新已有凭据并应用于新建及轮换凭据，通过长轮询同步桌面端状态。平台在调用上游前处理 messages，并记录压缩前后 Token、节省量、压缩比例和耗时。'],
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
      summary: '配置账号、角色、菜单与平台品牌，查询三类日志，并检查系统服务状态。',
      sections: [
        {"id": "accounts", "title": "账号管理", "paragraphs": ["在“系统管理 → 账号管理”新增账号、分配角色和用户组，或维护账号状态。"], "bullets": ["新增时填写用户名、初始密码，按需填写邮箱，并选择角色、用户组和启用状态。用户名只允许大小写英文字母、数字、下划线、点和短横线，最多 64 个字符。", "编辑可修改邮箱、角色和用户组；用户名创建后只读。重置密码使用独立入口。", "禁用账号或重置密码后，原有登录会话失效。有关联业务记录的账号可先禁用。", "可按关键词、角色、状态、用户组筛选；可按创建时间或最后登录时间排序。可执行的操作由当前账号权限决定。"], "link": {"path": "/users", "label": "打开账号管理"}, "image": {"name": "system-accounts", "alt": "账号管理", "caption": "账号管理"}},
        {"id": "account-create", "title": "新增账号填写示例", "paragraphs": ["按用户名规则填写账号信息，并选择实际需要的角色和用户组；初始密码只在创建时输入。"], "image": {"name": "system-account-create", "alt": "新增账号表单与用户名规则", "caption": "新增账号表单与用户名规则"}},
        {"id": "roles", "title": "角色与权限", "paragraphs": ["角色决定账号可以访问哪些页面、执行哪些操作。每个账号关联一个角色，用户组用于组织和业务策略绑定。"], "bullets": ["先新增角色，填写稳定标识、显示名称和描述。", "在“配置权限”中按模块选择查看、新增、编辑等操作，并设置可访问的默认首页；新角色需要配置权限后才能使用对应功能。", "权限保存后在后续请求中生效。内置管理角色保留管理权限，普通角色按职责授权。", "删除角色前先处理关联账号；自己的账号和最后一个有效管理账号受保护。"], "link": {"path": "/roles", "label": "打开角色管理"}, "image": {"name": "system-roles", "alt": "角色与权限", "caption": "角色与权限"}},
        {"id": "menus", "title": "菜单管理", "paragraphs": ["维护导航目录、页面入口和显示顺序，可展开或收起目录查看层级。"], "bullets": ["新增目录或页面入口，配置中英文名称、图标、父目录和排序，目录最多三级。", "页面入口从已有功能中选择；使用“上移／下移”调整同级顺序。", "启用或禁用控制导航展示；角色权限决定是否允许访问。", "内置菜单通过启停管理；删除自定义菜单前处理子菜单和角色默认首页关联。"], "link": {"path": "/menus", "label": "打开菜单管理"}, "image": {"name": "system-menus", "alt": "菜单管理", "caption": "菜单管理"}},
        {"id": "login-audit", "title": "登录日志", "paragraphs": ["用于查询登录成功与失败记录，定位账号和认证问题。"], "bullets": ["查看时间、操作者、登录结果、失败原因和来源 IP。", "通过关键词、操作者、结果、时间范围筛选；点击详情查看请求关联标识和完整记录。"], "link": {"path": "/system-audit?tab=login", "label": "打开登录日志"}, "image": {"name": "system-login-audit", "alt": "登录日志", "caption": "登录日志"}},
        {"id": "operation-audit", "title": "操作日志", "paragraphs": ["用于追踪管理操作、配置变更和敏感查看，例如修改账号、分配角色、更新品牌配置。"], "bullets": ["按模块和动作定位操作；相近请求动作按业务动作归类。", "详情展示事件、对象和请求信息；有变更数据时可对比修改前后的字段，并展开原始记录。"], "link": {"path": "/system-audit?tab=operation", "label": "打开操作日志"}, "image": {"name": "system-operation-audit", "alt": "操作日志", "caption": "操作日志"}},
        {"id": "security-audit", "title": "安全审计", "paragraphs": ["用于查询扫描、凭证及隐私访问等安全事件。"], "bullets": ["查看安全事件的操作者、模块、动作、对象与结果；详情包含事件类型和事件标识。", "有权限时可点击“验证审计链”，检查安全审计记录是否被修改、记录之间是否断开；鼠标悬停按钮可查看说明。", "三类日志默认按时间倒序，每页 10 条，可调整每页条数。筛选自动生效，重置清空条件。刷新页面保留当前日志页签。", "列表采用紧凑单行显示，长内容可悬停查看或打开详情；时间统一使用北京时间（UTC+8）。"], "link": {"path": "/system-audit?tab=security", "label": "打开安全审计"}, "image": {"name": "system-security-audit", "alt": "安全审计", "caption": "安全审计"}},
        {"id": "branding", "title": "Logo、系统名与公司名", "paragraphs": ["在“系统管理 → 系统总览 → 品牌与系统名称”配置平台展示信息。"], "bullets": ["分别填写中文系统名、英文系统名和公司名，点击“保存名称”。系统名按界面语言展示，公司名保持输入原文。", "点击“上传 Logo”更新图片，支持 PNG、JPEG、GIF、WebP，最大 5 MB；可恢复默认 Logo。", "保存后同步更新登录页、顶栏、帮助文档名称和浏览器标题。修改需要系统设置编辑权限。", "名称保存在数据库，Logo 保存在上传目录；Docker 部署保留对应数据卷即可保留配置。"], "link": {"path": "/settings", "label": "打开品牌设置"}, "image": {"name": "system-branding", "alt": "Logo、系统名与公司名", "caption": "Logo、系统名与公司名"}},

        {
          id: 'users-groups',
          title: '用户组',
          paragraphs: ['用户组既用于组织人员和Agent，也用于模型访问与隐私策略绑定。创建用户后，应按实际职责授予最小权限。'],
          link: { path: '/users-groups', label: '打开用户组' },
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
          title: '文档导出与文档助手',
          paragraphs: ['管理员可以在“系统管理 → 文档设置”中导出帮助材料并配置文档助手。PDF 按所选帮助模块生成可检索文档；Excel 按产品能力模块生成“功能总览”和可筛选的“功能清单”。文档助手启用后，帮助文档顶部会出现“问问 AI”，根据当前文档回答并给出经过校验的站内链接。'],
          bullets: ['PDF 支持完整文档、使用与治理、管理与运维或自定义文章范围，并可选择中文或英文。下载文件包含正文、表格、代码、截图、页面目录，以及按模块和文章分层的 PDF 侧边目录。', 'Excel 支持全部产品功能、治理核心能力、系统与运维或自定义二级能力范围，并可选择中文或英文。每行包含功能说明、使用场景、入口、能力边界和对应帮助章节。', '文档助手默认关闭；未选择可用模型时不能启用。浏览器只把当前语言下相关的有限文档片段发送给所选模型。', '模型只能依据提供的文档片段回答；站内链接由文档索引生成，不采用模型自行编造的链接。', '普通登录用户可以使用文档助手，只有管理员可以修改文档设置。', '文档助手设置存在未保存修改时，切换页面、刷新或关闭标签页前会提示确认。', 'AI回答用于快速定位，文档正文和系统实际配置仍是最终依据。'],
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
        { id: 'pending', title: '为什么一直显示 SCANNING（检测中）？', paragraphs: ['先查看该版本的检测记录，再检查后台日志以及系统总览中的深度分析、LLM和Sandbox状态。Scanner接入凭证只影响客户侧Scanner上传，不是ZIP提交完成检测的前置条件。SCANNING 表示列表检测状态尚未结束：后台 Skill 处于 PENDING，或存在状态为 PENDING 的检测任务。重新检测期间会保留此前准入状态，不应直接判断为前端缓存。'] },
        { id: 'different-results', title: '为什么 Sandbox 是低风险，最终结果却更高？', paragraphs: ['Sandbox只观察本次探测实际触发的行为。未触发的分支、静态危险模式和LLM语义证据仍可能提高最终风险，因此应查看完整证据链。'] },
        {
          id: 'llm-safe-final-malicious',
          title: '为什么 LLM 判定安全，最终判定却是恶意？',
          paragraphs: ['LLM 的“无明显风险”是模型的分析结论，最终风险由本次扫描采用的策略合并工具初判和 LLM 结论后确定。以下两种情况会保留恶意风险：'],
          bullets: [
            '存在“判为恶意”的发现：规则、深度扫描或 Sandbox 的发现按本次策略归入此类后，会形成恶意风险，LLM 不能降低。例如，数据外传发现被归为“判为恶意”，即使 LLM 认为它只是正常上传，最终仍保留恶意风险。',
            '本次采用严格模式：策略不允许 LLM 降低工具初判；如果工具初判为恶意，LLM 给出“无明显风险”也不会改变最终风险。',
          ],
          steps: [
            { title: '查看本次判定依据', body: '打开 Skill 详情 > 检测报告 > 实际判定过程，查看“LLM 结论与最终风险不同”的说明。有对应记录时，可点击“查看导致保留恶意风险的发现项”核对证据，或点击“查看 LLM 原始分析”核对模型意见。历史报告缺少合并依据时，页面会明确提示无法确认具体原因。' },
            { title: '核对分类和策略', body: '如果怀疑误报，先核对原始证据及本次扫描的配置。需要调整时，在策略配置中修改对应风险识别规则或判定模式，保存后重新检测；已有报告保留原结论。恶意风险的准入动作仍由配置决定，可以进入人工审核或自动拒绝。' },
          ],
          link: { path: '/docs/risk-classification', label: '查看发现项分类与风险合并逻辑' },
        },
        { id: 'review-queue', title: '为什么 Skill 没有进入审核队列？', paragraphs: ['列表的 VETTED（待审核）筛选只包含当前没有检测任务的待审核项目。SCANNING（检测中）包含初次检测和重新检测；重新检测期间后台仍可能保留 APPROVED、VETTED 等此前准入状态。检测完成后再查看最终状态和审核入口。'] },
        { id: 'rescan', title: '为什么重复提交没有重新检测？', paragraphs: ['同名同内容且检测上下文一致时可以复用结果。需要重新执行分析时，应在Skill版本页面使用“重新检测”；内容已经变化则提交新版本。'] },
        { id: 'agent-blocked', title: '为什么 Agent 不能加载已批准的 Skill？', paragraphs: ['检查运行凭证是否绑定当前Agent、Agent是否获授权使用该Skill、本地签名是否匹配，以及当前请求是否先完成签名验证。'] },
        { id: 'credential-lost', title: '凭证明文丢失后能否再次查看？', paragraphs: ['不能。服务端只保存Hash。应吊销旧凭证并重新创建，然后更新调用方配置。'] },
        { id: 'client-offline', title: '客户端为什么显示离线或不能下发 Skill？', paragraphs: ['先检查客户端后台服务、平台地址、客户端接入凭证和最后心跳。下发失败时继续检查 Skill 是否已批准、目标 Agent 是否支持 Skill 管理；Agent 强授权模式还要检查本机 Agent 是否已自动登记以及对应的 Skill 授权范围。'] },
        { id: 'compression-zero', title: '为什么启用了压缩但节省 Token 为 0？', paragraphs: ['确认本次调用使用的凭据已启用压缩，并查看链路或响应头。短上下文可能无需变换；压缩组件不可用或处理失败时会降级使用原始messages，因此“已启用”不保证每次产生节省。'] },
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
      { subgroup: 'Skill governance', slug: 'risk-classification', title: 'Finding classification', summary: 'Finding classification, policy configuration, and final risk' },
      { subgroup: 'Skill governance', slug: 'skill-policy', title: 'Policy settings', summary: 'Risk decisions, admission constraints, and analyzers' },
      { subgroup: 'MCP governance', slug: 'mcp-governance', title: 'MCP governance', summary: 'Servers, gateways, approvals, and audits' },
    ] },
    { title: 'Agent management', items: [
      { slug: 'agent-management', title: 'Agent management', summary: 'Agent records, capability bindings, and credentials' },
      { slug: 'client-management', title: 'Client management', summary: 'Local Agent discovery, Skill delivery, and continuous inspection' },
      { slug: 'credential-management', title: 'Credential center', summary: 'Issue least-privilege credentials by caller' },
      { slug: 'runtime-integration', title: 'Access and runtime', summary: 'Custom Agent loading, Tool checks, and runtime tracing' },
      { slug: 'hook-integration', title: 'Hook integration', summary: 'Configure event enforcement for Claude Code, Codex, and OpenClaw' },
      { slug: 'agent-security-runtime', title: 'AI security and runtime traces', summary: 'Agent, MCP, LLM, and AI infrastructure assessments, Worker operations, evidence, and unified traces' },
      { slug: 'audit-trail', title: 'Audit trail', summary: 'Query Skill, Agent, Client, and Tool events' },
    ] },
    { title: 'Model gateway', items: [
      { slug: 'model-gateway', title: 'Model gateway', summary: 'Model access, privacy controls, and token compression' },
    ] },
    { title: 'System administration', items: [
      { slug: 'system-management', title: 'System management', summary: 'Accounts, roles, menus, audit, and branding' },
    ] },
    { title: 'Deploy and operate', items: [
      { slug: 'docker-deployment', title: 'Docker deployment', summary: 'Run the same Compose stack online or offline' },
      { slug: 'performance-benchmark', title: 'Performance and capacity', summary: 'Measured gateway, Skill, and Client capacity in an isolated environment' },
      { slug: 'docker-operations', title: 'Docker operations', summary: 'Status, logs, backup, upgrade, and troubleshooting' },
    ] },
    { title: 'Scenario guides', items: [
      { slug: 'case-expense-skill', title: 'Launch an expense Skill', summary: 'From business sample to review, authorization, and runtime checks' },
      { slug: 'case-high-impact-skill', title: 'Review a high-impact Skill', summary: 'Assess a legitimate Skill with file-transfer capability' },
      { slug: 'case-malicious-skill', title: 'Reject a malicious Skill', summary: 'Use policy classification to identify credential and data exfiltration risk' },
      { slug: 'case-runtime-tamper', title: 'Block local tampering', summary: 'Reject a modified copy of an approved Skill' },
      { slug: 'case-mcp-approval', title: 'Approve a high-risk MCP action', summary: 'Close the loop for customer lookup and service suspension' },
      { slug: 'case-client-modular-governance', title: 'Govern a modular Client host', summary: 'Separate Agents, roots, permissions, and remediation on one host' },
      { slug: 'case-model-privacy-compression', title: 'Protect and compress model traffic', summary: 'Protect support-conversation privacy and verify token compression' },
    ] },
    { title: 'Help', items: [
      { slug: 'faq', title: 'FAQ', summary: 'Troubleshoot common symptoms' },
    ] },
  ],
  articles: {
    '': {
      eyebrow: 'Agent Manager docs', title: 'Govern Agent capabilities, model traffic, and local runtime',
      summary: 'From Skill admission and Client delivery to built-in model protection, external AI gateway integration, and MCP Tool approvals, the platform centralizes critical controls and audit evidence.', home: true,
      roles: [
        { title: 'Platform administrator', text: 'Start with Docker deployment, system checks, users, and credentials.', slug: 'docker-deployment' },
        { title: 'Security reviewer', text: 'Start with Skill reports, the review queue, and policy settings.', slug: 'skill-governance' },
        { title: 'Agent and client operator', text: 'Register Agents, choose a runtime check, then govern local Skills.', slug: 'agent-management' },
        { title: 'Model access operator', text: 'Choose the built-in model gateway or a customer external AI gateway based on the traffic path.', slug: 'scenario-selection' },
      ],
      sections: [
        { id: 'what-it-does', title: 'What the platform does', paragraphs: ['Agent Manager is not only a Skill registry. It governs Agent Skills, local capability delivery, model integration relationships and built-in gateway traffic, and externally exposed MCP Tools.'], bullets: ['Scan, decide, review, and sign Skills before use, then revalidate changed content.', 'Give Agents least-privilege bindings and credentials; use Clients to discover, deliver, restore, or quarantine local Skills.', 'The built-in model gateway applies access control, Prompt protection, privacy replacement, optional token compression, and usage analysis. External-gateway mode manages connections, external Agents, and API-key mapping while model traffic bypasses the built-in proxy.', 'Publish selected MCP Tools through gateways with time-bound high-risk approvals and audits.'] },
        { id: 'system-architecture', title: 'System architecture', paragraphs: ['A unified entry connects administrators, Scanners, Agents and Clients, model applications, and MCP Clients. The governance control plane centralizes policy, identity, authorization, and audit, while separate runtime data planes enforce Skill admission, endpoint governance, model privacy processing, and MCP Tool controls.'], bullets: ['Skill evidence from rules, deep scan, optional Sandbox, and LLM analysis reaches policy before an admission state is decided.', 'The Client governs local Skill content; Verifier or Hooks check digest and authorization before an Agent loads it.', 'Built-in model traffic passes credential and model scope, Prompt protection, PII pseudonymization, and optional compression. External-gateway traffic goes directly from the Agent or Client to the customer gateway while the platform manages connection and identity mapping.', 'MCP callers reach only published Tools; high-risk Tools require time-bound approval before execution.', 'Registry records, reports, tasks, traces, and signed security audit form an evidence chain across every domain.'], diagram: 'architecture', callout: { type: 'note', title: 'Control plane and execution boundaries', body: 'The platform controls admission, authorization, routing, and evidence. Agents still load local Skill directories, Sandbox runs dynamic checks in isolation, and upstream models and MCP Servers remain external runtime dependencies.' } },
        { id: 'capability-map', title: 'Choose a feature by goal', table: { columns: ['Goal', 'Module'], rows: [['Choose an integration by product and runtime', { label: 'Scenario selection', path: '/docs/scenario-selection' }], ['Submit and scan a Skill', { label: 'Skill governance / Submit Skill', path: '/docs/skill-governance' }], ['Batch-import Skills from a host or CI', { label: 'Scanner access', path: '/docs/scanner-access' }], ['Choose scan methods and interpret results', { label: 'Skill scanning capabilities', path: '/docs/scan-capabilities' }], ['Understand how finding classifications affect final risk', { label: 'Finding classification', path: '/docs/risk-classification' }], ['Configure Skill risk and admission rules', { label: 'Skill policy settings', path: '/docs/skill-policy' }], ['Review a suspicious Skill', { label: 'Skill governance / Skill Review', path: '/docs/skill-governance' }], ['Restrict an Agent to specific Skills', { label: 'Agent management / Bindings and credentials', path: '/docs/agent-management' }], ['Issue least-privilege credentials by caller', { label: 'Credential center', path: '/docs/credential-management' }], ['Add signature and Tool checks to an Agent', { label: 'Agent runtime integration', path: '/docs/runtime-integration' }], ['Configure a Claude Code, Codex, or OpenClaw Hook', { label: 'Hook integration', path: '/docs/hook-integration' }], ['Discover local Agents and Skill roots', { label: 'Client management / Agent Discovery', path: '/docs/client-management' }], ['Deliver, restore, or remove Skills on managed hosts', { label: 'Client management / Console operations', path: '/docs/client-management' }], ['Use a customer AI gateway and obtain models for an Agent', { label: 'External AI gateway', path: '/docs/external-ai-gateway' }], ['Protect private model input', { label: 'Model gateway / Privacy policies', path: '/docs/model-gateway' }], ['Compress model context and measure savings', { label: 'Model gateway / Token compression', path: '/docs/model-gateway' }], ['Analyze token usage by user', { label: 'Model gateway / User token analytics', path: '/docs/model-gateway' }], ['Audit anomalous Skills declared in model calls', { label: 'Model gateway / Skill Alerts', path: '/docs/model-gateway' }], ['Publish and audit MCP Tools', { label: 'MCP governance / Servers and gateways', path: '/docs/mcp-governance' }], ['Trace Skill, Agent, Client, and Tool events', { label: 'Audit trail', path: '/docs/audit-trail' }]] } },
      ],
    },
    'quick-start': {
      eyebrow: 'Get started', title: 'Complete your first Skill governance flow', summary: 'Use a test ZIP with no production secrets or personal data to complete submission, scanning, review, Agent authorization, and runtime verification.',
      sections: [
        { id: 'check-system', title: '1. Check platform status', paragraphs: ['Open the dashboard and system overview first. LLM and Sandbox checks depend on administrator configuration; unavailable checks remain disabled on the submission page.'], image: { name: 'dashboard', alt: 'Platform dashboard', caption: 'The dashboard highlights pending Skills, risk distribution, and recent events.' }, link: { path: '/dashboard', label: 'Open dashboard' } },
        {
          "id": "submit-zip",
          "title": "2. Upload a ZIP or folder and select Skills",
          "paragraphs": [
            "Switch between ZIP archive and Folder to show the corresponding upload entry. Switching clears the current selection and parsed results and is disabled during packaging, uploading, or submission. For folders with many files, create a ZIP locally to reduce browser resource use.",
            "In Folder mode, click Choose folder. Direct subfolders are sorted by original size, including all nested files; files in the selected root appear separately. Deselecting keeps a row available for reselection. Remove deletes the entire row and its pending upload contents from this list without deleting local files. To restore removed items, choose the folder again.",
            "The list updates the total original size of selected contents. Package and upload is disabled above 100 MiB; reduce the selection to 100 MiB or less to continue. Estimated compressed size does not determine eligibility. Up to 50,000 files are allowed, including SVG resources. Only __MACOSX and .DS_Store are skipped automatically. Possible credentials require confirmation, and packaging can be cancelled. Browsers may omit symlinks, empty directories, and executable permissions; use ZIP when these attributes are required. History shows folder-name.zip.",
            "In ZIP mode, select or drop a ZIP to prepare and parse it automatically. The upload limit is 100 MiB after removing entries starting with __MACOSX/; the local file is unchanged. Oversized archives show the 10 largest first- and second-level directories by compressed size to help you trim and repackage locally.",
            "Preparation, upload, extraction, and Skill identification display separate progress stages. Percentages apply to the current stage. If symlinks are found, a confirmation lists their paths and lets you skip them or cancel without uploading again."
          ],
          "steps": [
            {
              "title": "Select directories and Skills",
              "body": "Each Skill directory must contain SKILL.md. After parsing, select the directories and Skills to import."
            },
            {
              "title": "Choose checks and submit",
              "body": "Rule analysis is mandatory and cannot be unchecked. Choose available Deep scan, Sandbox, and LLM analysis options as needed, then submit the selected Skills.",
              "expected": "The “Background task created” message confirms acceptance. Content preparation and scan scheduling continue in the background."
            }
          ],
          "image": {
            "name": "submit-skill",
            "alt": "Submission page after ZIP parsing",
            "caption": "Example data: submit the selected Skills or open Submission history using the adjacent button."
          },
          "link": {
            "path": "/submit",
            "label": "Open Submit Skill"
          }
        },
        {
          "id": "folder-upload",
          "title": "Choose folder upload",
          "paragraphs": [
            "Switch to Folder and click Choose folder. For many files, consider packaging a ZIP locally to reduce browser resource use."
          ],
          "image": {
            "name": "submit-folder",
            "alt": "Folder upload mode",
            "caption": "Example screen: Folder mode and the performance hint."
          }
        },
        {
          "id": "folder-size-selection",
          "title": "Check original size before packaging",
          "paragraphs": [
            "Subfolders are sorted by size. Package and upload is disabled when the selected original total exceeds 100 MiB."
          ],
          "image": {
            "name": "folder-selection",
            "alt": "Oversized folder selection",
            "caption": "Example data: a 179 MiB folder exceeds the limit before packaging."
          }
        },
        {
          "id": "folder-remove-selection",
          "title": "Remove and deselect",
          "paragraphs": [
            "Remove deletes the row from the current list. Deselect keeps the row available for reselection. Neither action deletes local files."
          ],
          "image": {
            "name": "folder-selection-edited",
            "alt": "List after removing and deselecting items",
            "caption": "Example data: large/ removed, small/ retained but deselected, and only SKILL.md selected."
          }
        },
        {
          "id": "submission-history",
          "title": "Submission history",
          "paragraphs": [
            "Click Submission history next to the submit button. The dialog shows the latest 50 tasks with their IDs, ZIP filenames, import times, statuses, and processed/total counts. Records remain available after a refresh. Older records without a saved ZIP filename display “—”.",
            "Import completion means the selected content has been processed. Check import results or Skill details for the security scan status."
          ],
          "image": {
            "name": "submission-history",
            "alt": "Submission history dialog",
            "caption": "Example data: locate a submission by ZIP filename and import time, then click View results."
          }
        },
        {
          "id": "submission-results",
          "title": "View import results and return to history",
          "paragraphs": [
            "Click View results to inspect processed counts, imported Skills, and failed paths. A failure for one Skill does not stop the remaining items.",
            "Click Back to submission history to return to the list and inspect another submission. Scanning may still be running after import. The Skill list displays SCANNING; PENDING in the API indicates a queued or ongoing scan."
          ],
          "image": {
            "name": "submission-results",
            "alt": "Import results dialog with a back button",
            "caption": "Example data: a partially failed import with a button to return to submission history."
          }
        },
        {
          "id": "review-result",
          "title": "3. Read the report and decide",
          "paragraphs": [
            "The list separates final risk from LLM verdict. In the detail report, start with Decision trace to understand the policy outcome, then switch analyzers within Scan results to inspect evidence.",
            "Review final risk, evidence, analyzer results, files, and version history. VETTED needs human review, APPROVED is trusted, and REJECTED does not enter the review queue.",
            "For records or security review, use Export PDF Report in the Skill details header. The localized report includes River Security branding, an executive summary, clear finding cards, Sandbox and LLM results, admission policy, integrity information, and assessment limitations."
          ],
          "callout": {
            "type": "note",
            "title": "Report boundary",
            "body": "The PDF report applies only to the identified version and fingerprint. It redacts common credentials and truncates logs. Security risk and admission status are separate conclusions; policy can reject a low-risk Skill."
          },
          "image": {
            "name": "skill-list",
            "alt": "Skill list page",
            "caption": "Example data: final risk and LLM verdict are separate columns because model opinions do not replace policy decisions."
          },
          "link": {
            "path": "/skills",
            "label": "Open Skill list"
          }
        },
        { id: 'verify-runtime', title: '4. Connect an Agent and verify local content', paragraphs: ['Create an Agent, bind approved Skills, issue an Agent-bound runtime credential, and run Skill Verifier before the Agent uses local content.'], callout: { type: 'note', title: 'Verification order', body: 'Verify the local content digest first, then check the current Agent load permission. With an event Hook, also check Tool permission before Tool execution.' }, image: { name: 'runtime', alt: 'Access and Runtime page', caption: 'Runtime audit shows signature, load, tamper, and Tool events.' }, link: { path: '/runtime', label: 'Open Access & Runtime' } },
        { id: 'next-paths', title: '5. Continue based on your integration', paragraphs: ['This page covers only the first Skill governance flow. Choose a runtime verification method first, then configure the Client, Model Gateway, or MCP Gateway as required.'], table: { columns: ['Next goal', 'Continue with'], rows: [['Understand rules, deep scan, Sandbox, and LLM differences', { label: 'Skill scanning capabilities', path: '/docs/scan-capabilities' }], ['Batch-discover and submit Skills from servers or CI', { label: 'Scanner access', path: '/docs/scanner-access' }], ['Understand how findings become final risk', { label: 'Finding classification', path: '/docs/risk-classification' }], ['Configure enterprise risk and admission constraints', { label: 'Skill policy settings', path: '/docs/skill-policy' }], ['Embed checks into Agent load and Tool-call flows', { label: 'Agent runtime integration', path: '/docs/runtime-integration' }], ['Govern local Skills across multiple hosts', { label: 'Client management', path: '/docs/client-management' }], ['Protect model requests and measure token savings', { label: 'Model gateway', path: '/docs/model-gateway' }], ['Publish MCP Tools through controlled gateways', { label: 'MCP governance', path: '/docs/mcp-governance' }]] } },
      ],
    },
    'case-expense-skill': {
      eyebrow: 'Scenario guide · Skill lifecycle', title: 'Safely launch an expense Skill in a Finance Agent', summary: 'Use a deterministic business Skill to complete submission, scanning, human review, Agent authorization, pre-load verification, and audit.',
      scenario: { label: 'Scenario summary', items: [{ label: 'Roles', value: 'Skill developer · Security reviewer · Agent operator' }, { label: 'Estimated time', value: 'About 25 minutes' }, { label: 'Acceptance result', value: 'CNY 2,293 reimbursable · CNY 100 employee-paid' }] },
      sections: [
        { id: 'business', title: 'Business context and acceptance criteria', paragraphs: ['The Finance team built travel-expense-calculator to evaluate a Shanghai trip against a versioned policy. Platform governance answers whether the Skill may be trusted and authorized; the sample tests answer whether the calculation is correct. Complete acceptance requires both.'], flow: [{ label: 'Input', value: 'Business sample and policy' }, { label: 'Admission', value: 'Scan and human review' }, { label: 'Trust', value: 'Approve and sign', type: 'decision' }, { label: 'Authorize', value: 'Bind Finance Agent' }, { label: 'Pre-load', value: 'Verify local content' }, { label: 'Output', value: 'CNY 2,293 / CNY 100', type: 'success' }], table: { columns: ['Input', 'Demo value', 'Policy constraint'], rows: [['Trip', 'Shanghai, 3 days and 2 nights', 'Tier-1 hotel limit CNY 600/night'], ['Hotel', 'CNY 1,280', 'At most CNY 1,200 reimbursable'], ['Intercity transport', 'CNY 553 with invoice', 'Reimburse actual amount with invoice'], ['Local transport', 'CNY 260', 'CNY 80/day, at most CNY 240'], ['Meal allowance', 'Calculated', 'CNY 100/day, total CNY 300']] }, callout: { type: 'note', title: 'Concrete business acceptance', body: 'The expected reimbursable total is CNY 2,293 and the employee-paid amount is CNY 100. A scan does not prove the calculation, and a business test does not prove safety.' } },
        { id: 'prepare', title: 'Prepare the reproducible sample', paragraphs: ['The sample includes SKILL.md, a calculator, policy data, expense input, and automated tests. It requires no real employee, invoice, or company-policy data.'], code: 'python3 travel-expense-calculator/scripts/calculate.py', callout: { type: 'warning', title: 'Demo-data boundary', body: 'Use only fictitious employees and the bundled demo policy. Do not upload real expense reports, identity data, bank details, or invoice images.' }, download: { path: '/examples/travel-expense-calculator.zip', filename: 'travel-expense-calculator.zip', label: 'Download the expense Skill sample', hint: 'Demo policy, expense input, calculator, and tests' } },
        { id: 'submit-review', title: 'Submit, scan, and review', steps: [{ title: 'Package and submit the Skill', body: 'Zip the travel-expense-calculator directory, parse it on Submit Skill, and select the Skill.' }, { title: 'Choose available checks', body: 'Use rule and deep scan, plus Sandbox when available. Keep LLM disabled when it is not configured; skipped is not passed.' }, { title: 'Confirm analyzer completeness', body: 'Open Skill details, distinguish completed, skipped, unavailable, and failed, then inspect findings and source files.' }, { title: 'Complete business and security review', body: 'Confirm that the script reads only demo input and policy files, produces structured output, and passes its tests. Only VETTED enters the human review queue.', expected: 'Approval creates a trusted signed version, while the business result remains CNY 2,293 and CNY 100.' }], image: { name: 'submit-skill', alt: 'Submit the expense Skill', caption: 'Parse the ZIP and select only checks that are available in the current environment.' }, link: { path: '/submit', label: 'Open Submit Skill' } },
        { id: 'authorize-run', title: 'Authorize the Finance Agent and verify before use', steps: [{ title: 'Create a Finance Agent', body: 'Use a stable Agent ID such as finance-expense-agent and bind the approved Skill version.' }, { title: 'Issue an Agent runtime credential', body: 'Create an Agent-bound runtime credential and provide its one-time secret only to that runtime.' }, { title: 'Verify the local directory', body: 'Run Skill Verifier with --path pointing to the single directory containing SKILL.md. Continue only on exit code 0.', code: 'python ~/.codex/skills/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \\\n  --path /absolute/path/to/travel-expense-calculator', expected: 'Verification passes and runtime audit records signature and load-permission checks.' }, { title: 'Execute and confirm the result', body: 'Run the calculator and confirm the policy version, item limits, total, and employee-paid amount.' }], image: { name: 'runtime', alt: 'Expense Skill runtime audit', caption: 'Runtime audit identifies which Agent performed signature and load checks.' }, link: { path: '/docs/runtime-integration', label: 'Read runtime integration' } },
        { id: 'troubleshoot', title: 'When results differ', table: { columns: ['Symptom', 'Check first'], rows: [['Not in the review queue', 'Confirm the state: VETTED enters review, APPROVED is already trusted, and REJECTED does not enter'], ['Sandbox failed', 'Separate a security finding from dependency, argument, or entrypoint diagnostics'], ['Verifier returns 403', 'Check credential-to-Agent binding, Skill authorization, state, and local digest'], ['Total is not CNY 2,293', 'Confirm demo-2026.1 and shanghai-trip.json were not modified']] }, link: { path: '/docs/skill-governance', label: 'Read Skill governance' } },
      ],
    },
    'case-high-impact-skill': {
      eyebrow: 'Scenario guide · Risk review', title: 'Review a legitimate but high-impact incident-evidence upload Skill', summary: 'Use file access, credentials, and network transfer to decide whether a dangerous business capability has sufficient controls instead of equating high risk with malicious intent.',
      scenario: { label: 'Scenario summary', items: [{ label: 'Roles', value: 'SOC developer · Security reviewer' }, { label: 'Estimated time', value: 'About 20 minutes' }, { label: 'Core decision', value: 'Require safeguards before deciding on approval' }] },
      sections: [
        { id: 'business', title: 'Why a risk label alone is insufficient', paragraphs: ['incident-evidence-uploader reads a selected evidence file, calculates a digest, and uploads only after explicit operator intent. The purpose is legitimate, but the code can read files, obtain a credential from an environment variable, Base64-encode content, and make an HTTPS request. Review must compare declared purpose, constraints, and implementation.'], flow: [{ label: 'Claim', value: 'SOC evidence upload' }, { label: 'Capability', value: 'Files / credential / network' }, { label: 'Evidence', value: 'Rules + deep scan + Sandbox' }, { label: 'Decision', value: 'Purpose matches safeguards?', type: 'decision' }, { label: 'Disposition', value: 'Add controls or reject', type: 'blocked' }], table: { columns: ['Behavior', 'Business reason', 'Review question'], rows: [['Read evidence', 'Upload a security artifact', 'Are roots, file count, size, and exact selection constrained?'], ['Read an environment credential', 'Authenticate to the collector', 'Is it short-lived, least privilege, and absent from logs?'], ['Send data over the network', 'Reach the SOC collector', 'Are HTTPS, destination allowlist, and explicit confirmation enforced?'], ['Record a digest', 'Integrity and audit evidence', 'Are original evidence and tokens excluded from logs?']] } },
        { id: 'scan', title: 'Use each analyzer for a different question', steps: [{ title: 'Run rules and deep scan', body: 'Confirm file access, credentials, encoding, and network paths, then open exact file and line evidence.' }, { title: 'Run the default Sandbox preflight', body: 'The sample uses the reserved collector.invalid domain and cannot reach a real service. Inspect network attempt, error, and exit status.' }, { title: 'Classify findings', body: 'Use the scan policy groups: Classify as malicious, Assess in context, or Retain as a notice. Then inspect risk reconciliation and admission actions. Finding counts do not replace evidence review.' }, { title: 'Record a defensible decision', body: 'The sample permits an environment variable to override any HTTPS destination and lacks a production destination allowlist, so do not approve it unchanged for production.', expected: 'The review lists required safeguards instead of only saying “high risk”.' }], link: { path: '/docs/scan-capabilities', label: 'Compare scanning capabilities' }, download: { path: '/examples/incident-evidence-uploader.zip', filename: 'incident-evidence-uploader.zip', label: 'Download the incident-evidence upload sample', hint: 'Reserved domain and fictitious evidence; no real destination' } },
        { id: 'decision', title: 'Controls required for an approvable version', bullets: ['Use a destination allowlist that ordinary runtime configuration cannot broaden.', 'Restrict reads to approved evidence roots and enforce file-count and total-size limits.', 'Inject short-lived least-privilege credentials through secure configuration.', 'Display filename, size, digest, and destination before explicit confirmation.', 'Audit operator, destination, digest, and outcome without recording the credential or evidence body.'], callout: { type: 'warning', title: 'No observed transfer is not proof of safety', body: 'The default probe may omit upload arguments or a credential. An untriggered branch does not negate the network-transfer capability visible in source.' }, link: { path: '/docs/risk-classification', label: 'Read finding classification' } },
        { id: 'production', title: 'Revalidate the remediated version', steps: [{ title: 'Submit a new version', body: 'Do not rewrite historical reports. Add allowlist, directory, and approval controls, then submit new content.' }, { title: 'Force a new scan', body: 'Re-run rules, deep scan, and Sandbox after policy or implementation changes.' }, { title: 'Compare versions', body: 'Confirm which dangerous capabilities remain, that safeguards exist in code, and that the business flow still works.' }] },
      ],
    },
    'case-malicious-skill': {
      eyebrow: 'Scenario guide · Admission block', title: 'Reject a data-exfiltration Skill disguised as a utility', summary: 'Trace environment credentials, system-file reads, external transfer, and dynamic execution to see how policy classification produces malicious risk and admission settings route it to review or rejection.',
      scenario: { label: 'Scenario summary', items: [{ label: 'Roles', value: 'Skill recipient · Security reviewer' }, { label: 'Estimated time', value: 'About 15 minutes' }, { label: 'Acceptance result', value: 'REJECTED · no approval or deployment path' }] },
      sections: [
        { id: 'sample', title: 'Deterministic evidence in the sample', paragraphs: ['rejected-exfiltrator combines several dangerous behaviors in one short script for reviewer training. This example classifies data exfiltration as malicious and automatically rejects malicious risk. Actual outcomes depend on the recorded classifications and admission settings.'], flow: [{ label: 'Source', value: 'Read API_KEY and system file' }, { label: 'Process', value: 'Build outbound payload' }, { label: 'Transfer', value: 'POST to external target', type: 'blocked' }, { label: 'Extra risk', value: 'Dynamic eval', type: 'decision' }, { label: 'Admission', value: 'REJECTED', type: 'blocked' }], table: { columns: ['Code behavior', 'Security meaning', 'Recommended classification'], rows: [['Read API_KEY', 'Access a runtime credential', 'Classify as malicious when supported by transfer evidence'], ['Read /etc/passwd', 'Access an unrelated system file', 'Assess in context and check its role in transfer'], ['POST to evil.example.com', 'Send a payload to an external destination', 'Classify as malicious for the data transfer in this example'], ['eval a string', 'Difficult-to-constrain execution path', 'Assess in context alongside the exfiltration chain']] }, callout: { type: 'warning', title: 'Never run it directly on the host', body: 'This is an intentionally malicious sample. Submit it for static analysis; observe dynamic behavior only in an isolated Sandbox.' } },
        { id: 'submit', title: 'Submit and confirm the rejection path', steps: [{ title: 'Package only the sample', body: 'Zip rejected-exfiltrator without adding real credentials or files.' }, { title: 'Run static checks', body: 'Enable rules and deep scan. Use Sandbox for dynamic evidence, never direct host execution.' }, { title: 'Start with findings classified as malicious', body: 'Open rule, file, line, and evidence text, then connect credential/file access to payload creation and network transfer.' }, { title: 'Confirm the final state', body: 'Confirm that this scan classifies the transfer finding as malicious, then check the admission action for malicious risk. This example uses the recommended automatic rejection action.', expected: 'The automatic rejection configuration in this example produces REJECTED. Configuring manual review for malicious risk produces VETTED instead.' }], link: { path: '/submit', label: 'Open Submit Skill' }, download: { path: '/examples/rejected-exfiltrator.zip', filename: 'rejected-exfiltrator.zip', label: 'Download the malicious exfiltration sample', hint: 'Dangerous sample: scan only; never execute directly on a host' } },
        { id: 'interpret', title: 'Common misinterpretations', bullets: ['A network failure in Sandbox does not remove exfiltration intent.', 'An unreachable evil.example.com destination does not invalidate the static data-flow evidence.', 'If LLM analysis is skipped or fails, tool risk is still aggregated under the scan policy.', 'Findings retained as notices do not offset findings classified as malicious. Check admission settings for the final action.'], link: { path: '/docs/risk-classification', label: 'Read finding classification and risk logic' } },
        { id: 'remediation', title: 'If the developer claims a legitimate purpose', paragraphs: ['Do not approve the same version based on a verbal explanation. Require removal of system-file and unrelated credential access, an approved destination, narrow data scope, and no eval; submit the result as a new version with independent evidence and admission status.'] },
      ],
    },
    'case-runtime-tamper': {
      eyebrow: 'Scenario guide · Runtime integrity', title: 'Reject a locally modified copy of an approved Skill', summary: 'Show why prior platform approval does not prove the current endpoint copy is still trusted, then restore trusted content and verify again.',
      scenario: { label: 'Scenario summary', items: [{ label: 'Roles', value: 'Agent operator · Security responder' }, { label: 'Estimated time', value: 'About 15 minutes' }, { label: 'Acceptance result', value: 'Block after modification · pass after restore' }] },
      sections: [
        { id: 'premise', title: 'Prerequisites', paragraphs: ['Use the approved expense Skill from the first scenario, bound to finance-expense-agent. Skill Verifier must read the local directory, the credential must bind the same Agent, and the check must receive the actual skill_path.'], flow: [{ label: 'Baseline', value: 'Trusted version passes', type: 'success' }, { label: 'Change', value: 'Local file modified', type: 'decision' }, { label: 'Check', value: 'Digest mismatch', type: 'blocked' }, { label: 'Response', value: 'Reject load', type: 'blocked' }, { label: 'Recovery', value: 'Restore and verify again', type: 'success' }], callout: { type: 'note', title: 'Why the path matters', body: 'A registry check by Skill name cannot detect local changes. Passing the directory that contains SKILL.md lets Verifier calculate the current digest and compare it with the trusted version.' } },
        { id: 'baseline', title: 'Establish a passing baseline', steps: [{ title: 'Verify the original directory', body: 'Run Verifier against a freshly installed or restored trusted version.', code: 'python ~/.codex/skills/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \\\n  --path /absolute/path/to/travel-expense-calculator', expected: 'Exit code 0 and a successful verification message.' }, { title: 'Keep a recoverable copy', body: 'Copy the trusted version to a temporary drill location rather than relying on memory to undo changes.' }] },
        { id: 'tamper', title: 'Make a recoverable local change and confirm the block', steps: [{ title: 'Modify only the demo copy', body: 'Append a harmless comment to the calculator; any content change should alter the digest.', code: 'printf "\\n# local tamper drill\\n" >> /temporary/demo-copy/scripts/calculate.py' }, { title: 'Run Verifier again', body: 'Use the same Agent and runtime credential against the changed directory.', expected: 'Non-zero exit; the Agent stops before reading, loading, or executing the Skill.' }, { title: 'Inspect runtime audit', body: 'Filter by time, Agent, and Skill to confirm the mismatch or signature failure came from the intended credential and source.' }], image: { name: 'runtime', alt: 'Local Skill tamper event', caption: 'Runtime audit correlates Agent, Skill, verification outcome, and time.' }, link: { path: '/runtime', label: 'Open Access & Runtime' } },
        { id: 'recover', title: 'Restore from a trusted source', steps: [{ title: 'Stop using the changed copy', body: 'Do not downgrade failure to a warning or bypass Verifier.' }, { title: 'Restore trusted content', body: 'Use a Client restore task or a verified release package to replace the demo copy.' }, { title: 'Verify again', body: 'Continue only after digest, Agent authorization, state, and credential all pass.', expected: 'Verifier returns exit code 0 and creates a new success audit.' }], link: { path: '/docs/client-management', label: 'Read Client restore and inspection' } },
        { id: 'failure', title: 'A block is not always tampering', table: { columns: ['Error type', 'Investigate'], rows: [['Content digest mismatch', 'Compare local content with the trusted version'], ['Skill not authorized', 'Check the exact family, version, or Skill binding'], ['Credential invalid or 403', 'Check state, Agent binding, and runtime scopes'], ['Skill not APPROVED/DEPLOYED', 'Check admission state, not only local files']] } },
      ],
    },
    'case-client-modular-governance': {
  "eyebrow": "Scenario guide · Client governance",
  "title": "Govern Skills as modules on a multi-Agent workstation",
  "summary": "Separate local Agents, Skill roots, automatically registered Agent identities, and remediation policy into verifiable units so one directory or repair does not affect the whole host.",
  "scenario": {
    "label": "Scenario summary",
    "items": [
      {
        "label": "Roles",
        "value": "Endpoint administrator · Agent owner · Security operations"
      },
      {
        "label": "Estimated time",
        "value": "About 30–40 minutes"
      },
      {
        "label": "Acceptance result",
        "value": "Two independent Agent scopes · targeted repair"
      }
    ]
  },
  "sections": [
    {
      "id": "business",
      "title": "Business scenario and module boundaries",
      "paragraphs": [
        "The fictitious training-workstation-01 runs Codex for expense work and Claude Code for development assistance. The host also has ~/.agents/skills, which OpenCode and Cursor may both read. The objective is not to label the whole machine trusted. It is to verify which Agent reads which root, which approved Skills it may use, and what response applies to one abnormal Skill."
      ],
      "flow": [
        {
          "label": "Client",
          "value": "training-workstation-01"
        },
        {
          "label": "Discovery",
          "value": "Agents and Skill roots"
        },
        {
          "label": "Binding",
          "value": "Local → platform Agent"
        },
        {
          "label": "Authorization",
          "value": "Per-Agent Skill scope",
          "type": "decision"
        },
        {
          "label": "Response",
          "value": "Audit or repair one Skill",
          "type": "success"
        }
      ],
      "table": {
        "columns": [
          "Governance unit",
          "Scenario configuration",
          "Boundary to verify"
        ],
        "rows": [
          [
            "Codex module",
            "finance-expense-agent → travel-expense-calculator",
            "Only the approved Skill authorized for the finance Agent"
          ],
          [
            "Claude Code module",
            "developer-assistant → approved-helper",
            "Does not inherit Codex authorization"
          ],
          [
            "Shared root",
            "~/.agents/skills",
            "Govern content and integrity; do not infer caller identity"
          ],
          [
            "Client policies",
            "Record only first; restore trusted content for the selected trigger",
            "Verify the specific rule and locally effective policy"
          ]
        ]
      },
      "callout": {
        "type": "note",
        "title": "What modular means here",
        "body": "The current Client governs by Agent type, one or more Skill roots, individual Skill, and the automatically registered Agent identity. It is not a plugin-market module system, and a shared root is not automatically owned by one Agent."
      },
      "download": {
        "path": "/examples/client-modular-governance-plan.json",
        "filename": "client-modular-governance-plan.json",
        "label": "Download the modular Client governance plan",
        "hint": "Fictitious host, automatic Agent registration, shared-root boundary, and acceptance checks"
      }
    },
    {
      "id": "prepare",
      "title": "Prepare platform objects and trusted Skills",
      "steps": [
        {
          "title": "Prepare two approved Skills",
          "body": "Reuse travel-expense-calculator from the expense scenario and submit the approved-helper sample. Complete scanning and approval for both; a local directory alone is not a trusted platform version."
        },
        {
          "title": "Create two platform Agents",
          "body": "Create finance-expense-agent for Codex and developer-assistant for Claude Code, each authorized only for its intended Skill."
        },
        {
          "title": "Issue a Client credential",
          "body": "Create a Client access credential for this training workstation and store its one-time secret only in Client secure configuration."
        },
        {
          "title": "Install and connect the Client",
          "body": "Download the matching installer, enter platform URL and credential, and verify registration, heartbeat, and background-service state.",
          "expected": "The console lists the workstation online and Client Overview shows a connected platform."
        }
      ],
      "link": {
        "path": "/clients",
        "label": "Open Client management"
      },
      "download": {
        "path": "/examples/approved-helper.zip",
        "filename": "approved-helper.zip",
        "label": "Download the development-helper Skill",
        "hint": "Safe demo Skill with Read-only declaration for the second Agent module"
      }
    },
    {
      "id": "discover",
      "title": "Discover Agents, roots, and the shared boundary",
      "paragraphs": [
        "Search for Codex and Claude Code in platform Agent Discovery Configuration and verify enabled state and roots. After synchronization, select each Agent under Agent Management to inspect Local Skills."
      ],
      "steps": [
        {
          "title": "Verify roots",
          "body": "Select an Agent and use the folder icon to inspect its real root. Platform configuration supplies built-in roots; local overrides take precedence."
        },
        {
          "title": "Identify shared roots",
          "body": "Shared Skills appear separately. Several Agents may read a root; its path does not establish caller identity."
        },
        {
          "title": "Verify sync and discovery",
          "body": "After saving discovery configuration, inspect the sync task and Client discovery results. Saving configuration does not create missing directories."
        }
      ],
      "image": {
        "name": "client-app-discovery",
        "alt": "Client Skill discovery by Agent and root",
        "caption": "Actual desktop Client Agent Management window; inspect roots and local Skill states per Agent."
      }
    },
    {
      "id": "bind-install",
      "title": "Enable strict Agent authorization and deliver separately",
      "steps": [
        {
          "title": "Start with Record only",
          "body": "In this client’s classification policy, set Certified Skill content changed to Record only. Save and verify the effective rule under Scan policies."
        },
        {
          "title": "Switch to strict Agent authorization",
          "body": "This mode requires every supported local Agent to bind a platform Agent."
        },
        {
          "title": "Bind each Agent",
          "body": "Bind Codex to finance-expense-agent and Claude Code to developer-assistant. The shared directory does not provide Agent identity."
        },
        {
          "title": "Install each approved version",
          "body": "Install travel-expense-calculator under Codex and approved-helper under Claude Code. Filter the list by the automatically registered local Agent identity's authorization.",
          "expected": "Codex cannot select approved-helper, Claude Code cannot select the expense Skill, and both install tasks succeed independently."
        }
      ],
      "callout": {
        "type": "warning",
        "title": "A button message is not task completion",
        "body": "After remote delivery, verify task state, target Agent, Skill version, and latest event. pending or running means work is incomplete."
      },
      "link": {
        "path": "/docs/client-management",
        "label": "Read Client feature guidance"
      }
    },
    {
      "id": "drill",
      "title": "Verify one-module detection and targeted recovery",
      "steps": [
        {
          "title": "Modify only the finance demo copy",
          "body": "After ensuring recovery, append a harmless comment to travel-expense-calculator in the Codex root. Do not change the Claude Code root."
        },
        {
          "title": "Inspect immediately",
          "body": "Open Settings → Background Operation → View runtime diagnostics → Run Inspection Now. Verify the content-change event and Record only result."
        },
        {
          "title": "Check the impact boundary",
          "body": "Confirm approved-helper, Claude Code binding and tasks, and the shared root did not change."
        },
        {
          "title": "Restore through the trigger rule",
          "body": "Set this client’s Certified Skill content changed action to Restore trusted version. Preview and save, then wait for policy application and execution.",
          "expected": "Verify recovery events and content digests; other Agent roots remain unchanged."
        }
      ],
      "image": {
        "name": "client-app-status",
        "alt": "Client Overview → Runtime & Sync: background governance, last sync and queued events.",
        "caption": "Client Overview → Runtime & Sync: background governance, last sync and queued events. Captured directly from the installed macOS Dev client on 2026-10-10; displayed states are observations at capture time."
      }
    },
    {
      "id": "acceptance",
      "title": "Acceptance and troubleshooting",
      "table": {
        "columns": [
          "Check or symptom",
          "Correct interpretation"
        ],
        "rows": [
          [
            "Both Agents can install any Skill",
            "Fail: strict binding or Agent authorization is ineffective"
          ],
          [
            "Only the finance Skill emits an event after its change",
            "Pass: the abnormality maps to the correct Agent, path, and Skill"
          ],
          [
            "A Record only rule appears to restore files",
            "Check locally effective policy, other matching rules, and manual tasks"
          ],
          [
            "Repair succeeds and the development digest is unchanged",
            "Pass: recovery did not cross module boundaries"
          ],
          [
            "The shared root lists possible readers",
            "Pass: this is a read-boundary hint, not caller authentication"
          ],
          [
            "Platform temporarily unavailable",
            "Client continues with the last synced policy and queues events; offline does not mean unmanaged"
          ]
        ]
      },
      "link": {
        "path": "/audit",
        "label": "Open unified audit"
      }
    }
  ]
},
    'case-model-privacy-compression': {
      eyebrow: 'Scenario guide · Model gateway', title: 'Protect support-conversation privacy and verify context compression', summary: 'Send a fictitious customer ID and email through the Model Gateway, then verify access control, pseudonymization, compression, response restoration, and audit boundaries independently.',
      scenario: { label: 'Scenario summary', items: [{ label: 'Roles', value: 'Gateway administrator · Privacy auditor · Support-app developer' }, { label: 'Estimated time', value: 'About 30 minutes' }, { label: 'Acceptance result', value: 'Upstream sees no raw PII · compression is measurable' }] },
      sections: [
        { id: 'business', title: 'Business scenario and success criteria', paragraphs: ['A support application summarizes repetitive outage history. The exercise uses fictitious CUST-1001 and the reserved domain demo.user@example.com, but sends them through the same privacy path as real data. Success is not a setting labelled Enabled; it is evidence from one request across every processing stage.'], flow: [{ label: 'Ingress', value: 'Credential and model scope' }, { label: 'Privacy', value: 'PII → session tokens', type: 'decision' }, { label: 'Compression', value: 'Process repeated context' }, { label: 'Upstream', value: 'No raw PII', type: 'success' }, { label: 'Return', value: 'Restore and audit', type: 'success' }], table: { columns: ['Checkpoint', 'Success criterion'], rows: [['Access control', 'Credential is active and allows only the target model'], ['Privacy replacement', 'masked stage contains neither raw email nor customer ID'], ['Compression', 'Header reports on, enabled-noop, or off consistently with Trace'], ['Response restoration', 'If the model echoes tokens, final response restores original values'], ['Audit boundary', 'Only authorized administrators or privacy auditors see original content']] }, callout: { type: 'warning', title: 'Do not use real customers in the exercise', body: 'Pipeline Trace stores the original stage. Protecting upstream traffic does not make a test environment anonymous or remove audit retention.' } },
        { id: 'configure', title: 'Configure the model, policy, and least-privilege credential', steps: [{ title: 'Register an available provider and model', body: 'Configure an OpenAI-compatible provider, secret, model name, context window, output limit, and enabled state.' }, { title: 'Configure privacy policy', body: 'Enable CUSTOMER_ID, EMAIL_ADDRESS, and any other needed entities, then bind the policy to the exercise user group. Do not bypass PII checks.' }, { title: 'Choose compression scope', body: 'Enable compression on the calling credential with model:chat and select its level. Automatically issued client credentials use client policies. Start with auto or conservative for the exercise.' }, { title: 'Issue the model credential', body: 'Allow only the target model and set reasonable body-size and concurrency limits. Store the one-time secret only in the caller.', expected: 'GET /v1/models returns only enabled models allowed by the credential.' }], link: { path: '/model-gateway/providers', label: 'Open Model Gateway configuration' } },
        { id: 'request', title: 'Download and send a reproducible request', paragraphs: ['Replace replace-with-enabled-model with a model enabled in the console and allowed by the credential. Repeated history gives compression an opportunity to transform content, but the outcome still depends on model, text, and compression availability.'], code: 'export MODEL_GATEWAY_TOKEN="amat_xxx"\ncurl -sS -D model-gateway-headers.txt \\\n  http://127.0.0.1/v1/chat/completions \\\n  -H "Authorization: Bearer ${MODEL_GATEWAY_TOKEN}" \\\n  -H "Content-Type: application/json" \\\n  --data @model-privacy-compression-request.json', download: { path: '/examples/model-privacy-compression-request.json', filename: 'model-privacy-compression-request.json', label: 'Download the privacy and compression request', hint: 'Fictitious customer ID, reserved email domain, and repeated support history' }, callout: { type: 'note', title: 'Keep conversation_id stable', body: 'The same tenant_id and conversation_id reuse historical pseudonym mappings. Keep both stable for a multi-turn drill; use new identifiers for a new tenant or conversation.' } },
        { id: 'verify', title: 'Verify response headers and Pipeline Trace', steps: [{ title: 'Read response headers first', body: 'Inspect x-request-id, x-privacy-policy, x-prompt-guard, and x-compression. on means a transform occurred, enabled-noop means enabled without a transform, and off means disabled.' }, { title: 'Open the same request trace', body: 'Use x-request-id to inspect original, masked, compressed, masked_response, and final_response.' }, { title: 'Verify privacy order', body: 'masked and compressed must not contain demo.user@example.com or CUST-1001. Compression runs after PII replacement.' }, { title: 'Verify compression evidence', body: 'When on, compare pre_tokens, post_tokens, tokens_saved, ratio, and duration_ms. Do not invent savings for enabled-noop.' }, { title: 'Verify final response', body: 'If upstream references a placeholder, final_response should restore the fictitious original. If the model does not mention it, the final answer need not contain it.', expected: 'Headers, Trace stages, and Token Compression Stats agree for the same request_id.' }], image: { name: 'token-compression', alt: 'Model Gateway Token Compression Stats', caption: 'Stats show aggregate trends. This exercise still uses headers and the matching request_id for a single-call conclusion.' }, link: { path: '/pipeline-trace', label: 'Open Pipeline Trace' } },
        { id: 'compare', title: 'Interpret compression correctly', table: { columns: ['Observation', 'Meaning and next action'], rows: [['x-compression: on', 'This call changed context; compare token counts and semantic retention'], ['x-compression: enabled-noop', 'Enabled, but this content did not benefit; retest with longer repetitive context'], ['x-compression: off', 'The calling credential has compression disabled'], ['tokens_saved is 0', 'Not a failed call; inspect status, transforms, and input length'], ['High savings but missing facts', 'Compression is not lossless; lower the level, expand regression samples, or disable for this call'], ['Aggregate stats save tokens but this call does not', 'Stats cover a period; inspect a single call by request_id']] }, callout: { type: 'warning', title: 'Do not turn a compression ratio into an SLA', body: 'Savings depend on language, context type and length, model, and level. Production acceptance must compare fact retention, latency, error rate, and tokens—not maximize one percentage.' } },
        { id: 'failure', title: 'Privacy and compression troubleshooting', table: { columns: ['Symptom', 'Check first'], rows: [['x-privacy-policy is disabled', 'Credential owner, user-group binding, and enabled policy'], ['Raw values remain in masked', 'Entity types, custom rules, message role, and bypass metadata'], ['Bypass request receives 403', 'Policy disallows bypass_pii_check; do not relax it for this drill'], ['Only original exists without later stages', 'Prompt Guard block, upstream failure, or interrupted streaming Client'], ['Compression stays noop', 'Input length, compression self-test, actual provider, and actual credential'], ['Ordinary user can view raw PII', 'Permission defect; restrict immediately to administrators or privacy auditors']] }, link: { path: '/docs/model-gateway', label: 'Read Model Gateway guidance' } },
      ],
    },
    'case-mcp-approval': {
      eyebrow: 'Scenario guide · MCP governance', title: 'Run customer lookup directly and approve service suspension first', summary: 'Start an MCP service with fictitious data, publish a low-risk query and a high-risk state change through one gateway, then verify request, approval, execution, and audit.',
      scenario: { label: 'Scenario summary', items: [{ label: 'Roles', value: 'MCP administrator · Business approver · Agent integrator' }, { label: 'Estimated time', value: 'About 30 minutes' }, { label: 'Acceptance result', value: 'Lookup passes · suspension runs after approval' }] },
      sections: [
        { id: 'business', title: 'Business model and security boundary', paragraphs: ['The demo exposes customer_search and customer_suspend. Search reads two fictitious records. Suspend changes one status from active to suspended and requires a change-ticket ID and reason. The first high-risk call creates an approval request and never reaches the upstream service.'], flow: [{ label: 'Publish', value: 'Lookup + suspend Tools' }, { label: 'Low risk', value: 'Lookup runs directly', type: 'success' }, { label: 'High risk', value: 'First call creates request only', type: 'decision' }, { label: 'Approval', value: 'Review and grant briefly' }, { label: 'Execution', value: 'Suspend and audit', type: 'success' }], table: { columns: ['Tool', 'Risk', 'Call policy', 'Demo outcome'], rows: [['customer_search', 'Low', 'Call after credential and Schema checks', 'Return fictitious CUST-1001'], ['customer_suspend', 'High', 'First call creates an approval request', 'Status becomes suspended after approval']] }, callout: { type: 'warning', title: 'Understand approval scope', body: 'Approval creates a time-bound authorization for the same credential, gateway, Tool, and Schema. It is not restricted to one argument set. Use a short validity window and verify actual arguments and outcomes in Call Audit.' } },
        { id: 'start-demo', title: 'Start the reproducible MCP Server', paragraphs: ['The example uses the Compose examples profile. Default deployment does not start it or publish a host port. Rebuild Backend once when first using a source release that contains the example.'], steps: [{ title: 'Start the example service', body: 'Build Backend and start the optional mcp-demo service.', code: './build.sh --backend\ndocker compose --profile examples up -d mcp-demo backend nginx\ndocker compose ps mcp-demo', expected: 'mcp-demo is healthy. Restarting it restores initial customer data.' }, { title: 'Allow HTTP and the demo network only for this local exercise', body: 'The platform blocks HTTP and private MCP destinations by default. Follow the example README to obtain the exact Compose app CIDR, then allow mcp-demo and that CIDR before recreating Backend. Production should use HTTPS and a narrower destination allowlist.' }], callout: { type: 'warning', title: 'Do not copy this setting into production', body: 'MCP_ALLOW_HTTP=true is only for the isolated local demo. Production MCP Servers should use HTTPS, securely injected credentials, and an explicit outbound destination allowlist.' }, download: { path: '/examples/mcp-customer-operations.zip', filename: 'mcp-customer-operations.zip', label: 'Download the customer-operations MCP demo', hint: 'Server, caller, and full README with fictitious data only' } },
        { id: 'publish', title: 'Register the Server, publish Tools, and set policy', steps: [{ title: 'Register the MCP Server', body: 'Use customer-ops as the Server slug, enter http://mcp-demo:8091/mcp and upstream credential Bearer mcp-demo-change-me, and enable the Server. The Server slug prefixes exposed Tool names.' }, { title: 'Discover two Tools', body: 'Connect and confirm customer_search, customer_suspend, and their input Schemas.' }, { title: 'Set the high-risk policy', body: 'Keep customer_search low risk. Mark customer_suspend high risk with maximum concurrency 1; high risk forces pre-execution approval.' }, { title: 'Create a virtual gateway', body: 'Create a gateway whose slug is also customer-ops and publish both Tools. Saving records the current Schema snapshot.' }, { title: 'Issue an MCP credential', body: 'Create an MCP gateway credential allowed only to customer-ops and retain its one-time secret.', expected: 'tools/list returns customer-ops__customer_search and customer-ops__customer_suspend, both published with unchanged Schemas.' }], link: { path: '/mcp-governance/servers', label: 'Open MCP Servers' } },
        { id: 'call-approve', title: 'Call and approve the high-risk action', steps: [{ title: 'Verify the low-risk lookup', body: 'Set MCP_GATEWAY_TOKEN and call customer_search.', code: 'export MCP_GATEWAY_TOKEN="amat_xxx"\npython3 demo/mcp-customer-operations/call_demo.py search', expected: 'CUST-1001 returns with service_status active.' }, { title: 'Make the first high-risk call', body: 'Call suspend without an approval request ID.', code: 'python3 demo/mcp-customer-operations/call_demo.py suspend', expected: 'Response -32002 contains an mcpapr_ request ID; upstream customer state is unchanged.' }, { title: 'Review the request', body: 'Open MCP Governance → Call Approvals. Verify credential, gateway, Tool, Schema, customer ID, reason, and ticket. Approve for 60 seconds with a comment.' }, { title: 'Retry with the request ID', body: 'Retry the same call during the validity window.', code: 'python3 demo/mcp-customer-operations/call_demo.py suspend \\\n  --approval-request-id mcpapr_xxx', expected: 'The call succeeds and CUST-1001 becomes suspended.' }], link: { path: '/mcp-governance/approvals', label: 'Open Call Approvals' } },
        { id: 'audit', title: 'Audit and failure drills', table: { columns: ['Check', 'Expected evidence'], rows: [['Approval request', 'requested event, reviewer, comment, validity, and Schema digest'], ['First call', 'denied while waiting, linked approval_request_id'], ['Post-approval call', 'success linked to the same request ID and actual Tool'], ['Reject path', 'rejected request continues returning the recorded reason'], ['Schema drift', 'old gateway snapshot stops exposure; save again and create a new request']] }, bullets: ['Approval does not guarantee successful upstream execution; Call Audit is the final outcome.', 'Revealing unmasked arguments creates its own security audit event.', 'Run docker compose restart mcp-demo after the drill to restore fictitious state.'], link: { path: '/mcp-governance/audit', label: 'Open MCP Call Audit' } },
        { id: 'troubleshoot', title: 'Troubleshooting', table: { columns: ['Symptom', 'Resolution'], rows: [['Endpoint must use HTTPS', 'Enable MCP_ALLOW_HTTP only for the local demo; retain HTTPS enforcement in production'], ['Endpoint resolves to a disallowed address', 'Add the demo hostname and exact Compose CIDR to MCP_OUTBOUND_ALLOWLIST'], ['Tool absent from tools/list', 'Confirm gateway selection and saved Schema digest match the current Tool'], ['Still denied after approval', 'Check validity, credential, gateway, Tool, Schema, and request ID'], ['Call succeeds but state does not change', 'Inspect upstream result and Call Audit; approval does not guarantee business success']] }, link: { path: '/docs/mcp-governance', label: 'Read MCP governance' } },
      ],
    },
    'skill-governance': {
      eyebrow: 'Skill governance', title: 'Skill governance', summary: 'Manage submission, scanning, policy decisions, human review, and trusted Skill versions.',
      sections: [
        { id: 'submission', title: 'Submission methods', table: { columns: ['Method', 'Use case', 'Current status'], rows: [['ZIP upload', 'Submit one or more Skills in the console', 'Available'], ['Scanner access', 'Discover and upload local Skills from customer hosts or CI', 'Available']] }, callout: { type: 'note', title: 'Choose the right entry point', body: 'Use ZIP for small manual submissions and Scanner access for continuous discovery across customer hosts, servers, or CI.' } },
        { id: 'pipeline', title: 'Scanning and decisions', paragraphs: ['An initial submission has backend status PENDING and appears as SCANNING in the list. Enabled analyzers run in the background, and policy produces the final governance decision. No single Sandbox or LLM result replaces the final assessment.'], bullets: ['Static and rule analysis inspect files, permissions, and dangerous patterns.', 'Sandbox observes behavior triggered in a restricted run.', 'LLM may combine content and analyzer evidence when configured.', 'Policy routes the result to auto-approval, human review, or rejection.'], diagram: 'governance', link: { path: '/docs/scan-capabilities', label: 'Understand each scanning capability' } },
        { id: 'states', title: 'States and next actions', paragraphs: ["SCANNING is a list display state for scan progress, not a new backend Skill status. An initial scan has Skill status PENDING. A rescan preserves the previous admission status and creates a PENDING scan run. The list displays both cases as SCANNING; APIs and scan-run records still use PENDING."], table: { columns: ['State', 'Meaning', 'Next action'], rows: [['SCANNING', 'List display state: an initial scan or rescan is unfinished', 'Wait, inspect scan runs, or cancel the task'], ['VETTED', 'Checks complete; human review required', 'Approve or reject'], ['APPROVED', 'Trusted version approved', 'Bind to an Agent or install'], ['REJECTED', 'Rejected', 'Fix content and submit a new version'], ['DEPLOYED', 'In managed deployment', 'Continue integrity checks and audits']] } },
        { id: 'review-workflow', title: 'What to inspect during human review', steps: [{ title: 'Confirm analyzer completeness', body: 'Check whether each analyzer is completed, skipped, unavailable, or failed. Missing output is not no risk.' }, { title: 'Inspect raw evidence', body: 'Start with findings in Classify as malicious and Assess in context, then open files, lines, raw reports, and Sandbox output to verify actual behavior.' }, { title: 'Compare declarations and behavior', body: 'Compare purpose, allowed-tools, and license in SKILL.md with network, credential, dynamic-execution, and write behavior in code.' }, { title: 'Approve or reject', body: 'Only VETTED enters the review queue. Approval creates a trusted signed version; rejected content should be fixed and submitted as a new version.', expected: 'The action, reviewer, and result are queryable in Audit trail.' }], link: { path: '/review', label: 'Open Skill Review' } },
        {
          "id": "list-management",
          "title": "Filters and bulk actions",
          "paragraphs": [
            "The status filter separates SCANNING from VETTED (Awaiting review). SCANNING includes initial scans and rescans. APPROVED means approved. Final risk is the policy outcome; LLM verdict is the independent model opinion and may differ.",
            "Select Skills on the current page to rescan, cancel tasks, or delete in bulk. Rescans apply to items that are not currently scanning. Cancellation covers both initial scans and active rescans; cancelling a rescan preserves the previous effective decision. Check the selected items in the deletion confirmation.",
            "Results name the action: rescans submitted, tasks cancelled, or Skills deleted. Skips and failures are grouped by status or reason with affected items. Failed items stay selected for follow-up."
          ],
          "image": {
            "name": "skill-list",
            "alt": "Skill list with LLM verdict and bulk actions",
            "caption": "Example data: final risk and LLM verdict are separate columns because model opinions do not replace policy decisions."
          }
        },
        {
          "id": "list-columns",
          "title": "Choose visible columns",
          "paragraphs": [
            "Open Columns to configure all 13 columns. Defaults show Skill Name, Latest version, Latest trusted, Status, Risk Level, LLM verdict, Approver, Scan Time, and Actions. Skill ID, Rule scan, Deep scan, and Sandbox are hidden by default.",
            "Preferences are saved for the current account in this browser. Restore defaults resets the selection. Scroll horizontally to see additional columns in a wide table."
          ],
          "image": {
            "name": "skill-columns",
            "alt": "Column selection and Restore defaults",
            "caption": "Example data: show individual Rule scan, Deep scan, and Sandbox results when needed for review."
          }
        },
        {
          "id": "rescan-options",
          "title": "Choose options for a rescan",
          "steps": [
            {
              "title": "Open rescan",
              "body": "For one Skill, open More > Rescan on the right. For multiple Skills, select them and choose Rescan selected."
            },
            {
              "title": "Choose the source of options",
              "body": "Reuse previous scan options, or select Choose new scan options to apply Deep scan, Sandbox, and LLM analysis settings to the selected items. Rule analysis is mandatory and cannot be unchecked. Hover over an option for guidance."
            },
            {
              "title": "Submit and check the new report",
              "body": "Track scanning status and open the detail report. Selecting an analyzer requests execution; the report shows what actually ran. For example, Sandbox is skipped when there is no executable entry point."
            }
          ],
          "paragraphs": [
            "If LLM is unavailable, add an available model under Model Gateway > Model Management, select it under Skill Governance > Policy Settings > Advanced configuration > AI analysis service, and enable AI analysis in Detection settings."
          ],
          "image": {
            "name": "skill-rescan",
            "alt": "Rescan options dialog",
            "caption": "Example data: individual and bulk rescans share this dialog; Rule analysis is always selected."
          }
        },
        {
          "id": "basic-information",
          "title": "Basic information and scan options",
          "paragraphs": [
            "Basic information appears as soon as it is available. Reports, files, and content load separately and appear when ready. You can read available content while another section is still loading.",
            "The overview highlights the current version, admission status, and risk verdict. Compact metadata below shows source, tool declarations, and Sandbox runtime information, wrapping to fit the available width. Use the selector to switch versions and View decision trace beside the risk verdict to inspect its basis. Tool declaration checks compare declarations with the tool allowlist and permission policy. Reused results identify their source Skill.",
            "Read-only selections in the header show scan options; hover to inspect their source. Sandbox execution comes from the scan report, while the policy requirement separately indicates whether execution is mandatory. Remote mode shows the service URL; Docker mode shows the container image. Missing runtime information is shown as Not recorded. Inspect Scan results for execution details."
          ],
          "image": {
            "name": "skill-basic-info",
            "alt": "Basic information and scan options",
            "caption": "Example data: scan options appear beside basic information."
          }
        },
        {
          "id": "decision-trace",
          "title": "Decision trace: understand the final outcome",
          "paragraphs": [
            "The detail header shows basic information and the selected Deep scan, Sandbox, and LLM options, with their source: saved submission settings, a historical report, or unknown. A checked option does not mean execution succeeded.",
            "Detection Report opens on Decision trace. Analyzer results appear at the top, followed by separate final-risk and current-status cards. Numbered steps explain finding classification, tool risk, LLM reconciliation, and admission status. Select an analyzer to open its results, or expand findings to inspect sources, severities, files, lines, classifications, and original evidence. Current status may include later approval or deployment changes; the report has no snapshot of the admission action taken at scan time.",
            "In the screenshot, the LLM reports no apparent risk, but the data exfiltration finding is classified as malicious under the scan configuration, so final risk remains malicious. Sandbox was skipped in this example; it did not establish observed malicious execution.",
            "Policy links open a new page at the relevant risk classification or decision mode setting. New reports retain a decision configuration snapshot; older reports explicitly indicate when a complete snapshot is missing. Links show current settings. Rescan after changing configuration to obtain a new decision."
          ],
          "image": {
            "name": "skill-decision",
            "alt": "Decision trace and policy configuration links",
            "caption": "Example data: final risk and current admission status are shown separately, with four explanation steps and expandable original evidence."
          }
        },
        {
          id: 'read-decision-evidence',
          title: 'How to inspect the decision evidence',
          steps: [
            { title: 'Read risk and status first', body: 'Open Detection Report > Decision trace for the target Skill version. Final risk comes from the scan report; current admission status describes whether the version is now pending review, approved, deployed, or in another state. When LLM risk is lower than final risk, an explanation below the result identifies recorded malicious findings or strict mode as the reason, with links to retained findings and the original LLM analysis. Missing reconciliation evidence is stated explicitly.' },
            { title: 'Follow the four steps', body: 'Read finding classification, tool risk, LLM reconciliation, and admission status in order. Identify which findings affect risk and whether the LLM conclusion was accepted. Expand LLM review opinion under Reconcile LLM conclusion for the explanation and findings the LLM suggested dismissing. Rejection reasons and approval exceptions appear as notices below the diagram.' },
            { title: 'Browse original evidence by source', body: 'Expand View findings and original evidence, then switch between Rule analysis, Deep scan, and Sandbox. Each tab shows its finding count. Five findings appear per page; use the pagination below to browse the rest. Switching sources returns to page one. Each finding shows severity, file location, and original evidence on the left, with the recorded policy classification and its effect on risk on the right. Narrow screens stack these sections. Select a file location to open the corresponding analyzer results. Evidence stays in its original language. When no findings are recorded, check the analyzer execution status for context.' },
            { title: 'Check the recorded configuration', body: 'Read the snapshot notice above the diagram. Configuration links open current policy. To verify changes, preview them on the policy page, save, and rescan the version. Missing historical fields are shown as Not recorded.' },
          ],
          image: { name: 'skill-decision-evidence', alt: 'Findings and original evidence with analyzer tabs and pagination', caption: 'Example data: original evidence appears beside its recorded policy classification and effect on risk, with source tabs and pagination.' },
        },
        {
          "id": "scan-results",
          "title": "Scan results: inspect each analyzer",
          "paragraphs": [
            "Scan results is a sibling tab of Decision trace. Within Scan results, switch between Rule scan, Deep scan, Sandbox, and LLM analysis to inspect individual results and original evidence.",
            "Rule and deep-scan findings use the policy group names: Classify as malicious, Assess in context, and Retain as a notice. Groups follow the classifications recorded in this report. Rescan after changing the policy to obtain results under the new configuration.",
            "completed, skipped, unavailable, and failed describe different execution outcomes. Missing, skipped, or failed analysis is not a safe verdict. File content and evidence remain in their original language."
          ],
          "image": {
            "name": "skill-scan-results",
            "alt": "Four analyzer tabs within Scan results",
            "caption": "Example data: review findings by their recorded policy classification and switch analyzers to inspect original evidence."
          }
        },
        {
          id: 'scan-execution-details',
          title: 'Inspect scan execution details',
          paragraphs: ['Switch to Scan results and expand Execution details at the bottom to inspect total findings, scan duration, analyzer identifiers, result reuse, and the cache key. Duration shows up to two decimal places; missing fields are marked Not recorded. Analyzer identifiers and cache keys stay in their original form.'],
          image: { name: 'skill-scan-execution', alt: 'Expandable execution details within Scan results', caption: 'Example data: execution details are grouped under Scan results and collapsed by default.' },
        },
        { id: 'versions', title: 'Reports and versions', bullets: ['Read final risk, functional summary, evidence, attack chain, and framework mappings.', 'Inspect independent Scanner, rule, LLM, and Sandbox results.', 'Open stored files and raw reports instead of relying only on summaries.', 'Compare two content versions of the same Skill.', 'Rescan creates a new scan run; changed content must be submitted as a new version.'], link: { path: '/skills', label: 'Open Skill list' } },
        {
          id: 'version-diff',
          title: 'Version diff: select versions and inspect changes',
          steps: [
            { title: 'Open Diff', body: 'In Skill details, select Diff under Detection Report. Comparison results load when you open this tab. While waiting, you can switch to Decision trace or other tabs to read available content.' },
            { title: 'Select the base and target versions', body: 'The latest version is the default target and the preceding version is the base. Select different versions or use Swap versions to reverse the comparison. If only one version exists, or both selections identify the same version, the page immediately shows No text-file differences between these versions.' },
            { title: 'Inspect file changes', body: 'Choose a changed file to inspect additions, deletions, and edits. Switch between Side-by-side and Inline views; file content stays in its original language. Comparison covers readable UTF-8 text files up to 1 MiB each, skipping symlinks and the .git, .venv, node_modules, __pycache__, dist, and build directories.' },
            { title: 'Wait or retry', body: 'The comparison area shows a loading indicator while results are being prepared. During the current detail view, switching away and back with unchanged version selections continues the pending comparison or displays its existing result. If loading fails, an error appears with Retry loading changes.' },
          ],
        },
      ],
    },
    'scan-capabilities': {
      eyebrow: 'Skill governance', title: 'Skill scanning capabilities', summary: 'Understand what the base Scanner, rule analysis, deep scan, Sandbox, and LLM analysis inspect, when each is available, and how they contribute to the final decision.',
      sections: [
        {
          "id": "capability-overview",
          "title": "How rules, deep scan, Sandbox, and LLM differ",
          "paragraphs": [
            "These capabilities are complementary, not interchangeable scan levels. Static analysis finds broad signals, Sandbox observes only behavior triggered by one controlled run, and LLM performs a final semantic assessment from content and collected evidence. Risk reconciliation and admission policy still determine the final state."
          ],
          "table": {
            "columns": [
              "Capability",
              "Availability",
              "Primary output"
            ],
            "rows": [
              [
                "Base Scanner",
                "Starts for every submission; the runtime should provide Scanner",
                "Whole-directory static rules, permissions, and known dangerous patterns"
              ],
              [
                "Rule analysis (mandatory)",
                "Always selected for submission and rescans; cannot be unchecked",
                "Text rules, Python AST, suspicious behavior intent, and file locations"
              ],
              [
                "Deep scan",
                "The runtime supports deep scanning and the option is selected",
                "Detailed static findings, risk score, and raw report"
              ],
              [
                "Sandbox",
                "Enabled and reachable, or required by risk policy",
                "Entrypoint, arguments, output, exit code, timeout, and runtime signals"
              ],
              [
                "LLM analysis",
                "Enabled with a selected model and requested at submission",
                "Semantic risk, report, evidence decisions, and attack chain"
              ]
            ]
          },
          "image": {
            "name": "submit-skill",
            "alt": "Choose Skill scanning capabilities at submission",
            "caption": "Example data: Rule analysis is mandatory; other options depend on analyzer availability."
          },
          "link": {
            "path": "/submit",
            "label": "Open Submit Skill"
          }
        },
        {
          "id": "rule-analysis",
          "title": "Base Scanner and rule analysis",
          "paragraphs": [
            "The base Scanner scans the entire Skill directory. Mandatory Rule analysis adds local text rules and Python AST analysis for submissions and rescans. These static checks do not execute the Skill."
          ],
          "bullets": [
            "Key signals include prompt injection, system-prompt leakage, hidden instructions, data exfiltration, credential access, download-and-execute patterns, dynamic execution, and excessive permissions.",
            "Reports include rule, severity, file, and line evidence. A hit requires review; one rule does not directly determine the final state.",
            "If the base Scanner is unavailable or fails, other analyzers may continue, but the report should show the error and coverage is reduced."
          ],
          "callout": {
            "type": "note",
            "title": "Behavioral does not mean dynamic execution",
            "body": "The implementation internally calls the added rule bundle behavioral, but it currently performs text-pattern and AST static analysis. Only Sandbox executes a Skill probe."
          }
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
          "id": "llm-analysis",
          "title": "LLM analysis: one final semantic assessment",
          "paragraphs": [
            "When requested, the system waits for selected Scanner, rule, deep-scan, and Sandbox work, then sends a Skill content snapshot and analyzer evidence to the configured model for one final semantic assessment. The LLM does not execute the Skill.",
            "If LLM is unavailable, add an available model under Model Gateway > Model Management, select it under Skill Governance > Policy Settings > Advanced configuration > AI analysis service, and enable AI analysis in Detection settings."
          ],
          "bullets": [
            "Outputs include benign, suspicious, or malicious risk, a security report, accepted or dismissed evidence, and—when applicable—an attack chain and security-framework mapping.",
            "Findings in Classify as malicious establish malicious risk that LLM cannot lower. Strict mode also prevents LLM from lowering tool risk. Balanced or permissive mode allows a lower tool-risk assessment when no findings are classified as malicious; the report records the reconciliation result and explanation.",
            "If the model call fails, the attempt remains failed and the system falls back to deterministic rule, deep-scan, and Sandbox reconciliation. No LLM result does not mean completed and safe."
          ]
        },
        {
          id: 'detection-logic',
          title: 'Skill detection logic',
          paragraphs: ['This diagram follows the actual execution order across analyzers, policy-triggered Sandbox work, finding classification, optional LLM judgement, and admission. It shows how evidence is reconciled; not every capability runs for every submission.'],
          diagram: 'skill-scan-logic',
        },
        {
          "id": "execution-and-result",
          "title": "Execution order and result interpretation",
          "steps": [
            {
              "title": "Submission appears as SCANNING in the list",
              "body": "The Skill is stored first; the console does not wait synchronously for every analyzer."
            },
            {
              "title": "Independent analyzers run in parallel",
              "body": "The base Scanner, Rule analysis, and selected Deep scan and Sandbox analyzers run in parallel."
            },
            {
              "title": "Policy may add Sandbox",
              "body": "If interim risk matches a mandatory Sandbox level, the backend attempts Sandbox even when it was not manually selected."
            },
            {
              "title": "Risk is reconciled and LLM may run once",
              "body": "Deterministic risk is produced first. One semantic model assessment follows only when selected."
            },
            {
              "title": "Admission policy assigns the state",
              "body": "Final risk and policy route the Skill to APPROVED, VETTED, or REJECTED."
            }
          ],
          "table": {
            "columns": [
              "Report status",
              "Correct interpretation"
            ],
            "rows": [
              [
                "completed, with findings",
                "The analyzer completed and provided evidence for review"
              ],
              [
                "completed, no findings",
                "No hit in this scope; other analyzers or untriggered branches may still matter"
              ],
              [
                "skipped / not selected",
                "This capability did not run and provides no risk conclusion"
              ],
              [
                "unavailable / failed",
                "The dependency or execution failed; troubleshoot and rescan"
              ]
            ]
          },
          "link": {
            "path": "/skills",
            "label": "Open Skill reports"
          }
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
      eyebrow: 'Feature guide', title: 'Agent management', summary: 'View Agents by source: platform-created details focus on models, Skills, and access, while Client-discovered details focus on local instances and actual runtime state.',
      sections: [
        { id: 'source-specific-details', title: 'Start with Agent source', paragraphs: ['The Agent list combines platform-created records with local Agents discovered by managed Clients. A discovered local Agent is registered automatically and appears as its own asset.'], steps: [{ title: 'Filter by source', body: 'Use Platform-created for custom runtimes and server-side products such as Dify, and Client-discovered for local tools.' }, { title: 'Review platform-created details', body: 'Review the platform Agent ID, assigned Skills, default model, gateway source, runtime credential, and access state.' }, { title: 'Review Client-discovered details', body: 'Review the local Agent ID, owning Client, install and Skill paths, discovered Skills, live model configuration, the specific external gateway name, and scan time.' }, { title: 'Manage locally through the Client', body: 'Model configuration, Skill installation, quarantine, recovery, and inspection tasks are delivered to the owning Client.' }], callout: { type: 'note', title: 'Stable identity is registered automatically', body: 'The platform stores a stable identity for every Client-discovered Agent for policy, credentials, and audit. Asset facts continue to follow reports from the owning Client.' }, image: { name: 'agent-assets-list', alt: 'Agent assets separated by platform-created and Client-discovered source', caption: 'Current UI with example data: Client-discovered rows show the owner department and actual local state.' }, link: { path: '/agents', label: 'Open Agent assets' } },
        { id: 'platform-created-detail', title: 'Platform-created details: review configured capabilities', paragraphs: ['Platform-created Agents support custom runtimes and server-side products such as Dify. Their detail view focuses on state, assigned Skills, default model, model source, Agent runtime credential, and ownership.'], image: { name: 'agent-platform-detail', alt: 'Platform-created Agent detail', caption: 'Platform-created details follow platform configuration and can be edited for model, Skills, ownership, and runtime credentials.' } },
        { id: 'client-discovered-detail', title: 'Client-discovered details: review local facts', paragraphs: ['A discovered Agent is registered automatically by its Client. Its read-only detail view shows the local Agent identity, type and version, owning Client, install and Skill paths, actual model configuration, the specific external gateway name, and discovery evidence. Local governance actions remain under Client management.'], image: { name: 'agent-client-detail', alt: 'Client-discovered Agent detail', caption: 'This read-only asset view follows Client reports; governance actions run from Client management.' } },
        { id: 'agent-record', title: 'Register the Agent before issuing credentials', steps: [{ title: 'Create an Agent', body: 'Set a stable unique Agent ID, name, department, owner, and state. Runtime Agent ID must match this record.' }, { title: 'Bind capabilities', body: 'Choose the default model and allowed approved or deployed Skills. The list shows the concrete Skill identifier used for the binding.' }, { title: 'Issue a runtime credential', body: 'Create an Agent runtime credential bound to the Agent.' }, { title: 'Configure the runtime', body: 'Give the one-time secret only to that Agent; never use an administrator login token.' }], link: { path: '/agents', label: 'Open Agents' } },
        { id: 'status-and-binding', title: 'What state, binding, and credential control', table: { columns: ['Control', 'Effect', 'Common mistake'], rows: [['Agent state', 'Only active should carry production use; disabled or draft is not deleted', 'Do not infer state from deletion or credential revocation'], ['Skill binding', 'Defines which Skills this Agent may load', 'An approved Skill is not automatically available to every Agent'], ['Agent runtime credential', 'Establishes trusted Agent identity and runtime scopes', 'Caller metadata.agent_id cannot replace credential binding'], ['Default model', 'Records the Agent default model choice', 'model:chat scope and an enabled model are still required']] }, link: { path: '/docs/credential-management', label: 'Read Credential center' } },
        { id: 'credential-types', title: 'Choose credentials by caller', table: { columns: ['Credential', 'Purpose'], rows: [['Agent runtime', 'Signature, load, and Tool checks'], ['Scanner access', 'Submit and read owned scan results'], ['Client access', 'Desktop client registration, tasks, and events'], ['LLM Credential', 'Applications call large language models through the model gateway'], ['MCP gateway', 'MCP Client access to allowed gateways and Tools']] }, callout: { type: 'warning', title: 'Secrets are shown once', body: 'If lost, revoke and create a new credential. Never store real secrets in screenshots, docs, or source control.' } },
        { id: 'next-runtime', title: 'Next: integrate by product shape', paragraphs: ['For a custom Agent, integrate Runtime APIs directly in the Loader, Tool Dispatcher, and lifecycle code. For a packaged product whose runtime cannot be changed, use Agent Manager Client or the product’s supported configuration path.'], link: { path: '/docs/runtime-integration', label: 'Read custom Agent runtime integration' } },
      ],
    },
    'runtime-integration': {
      eyebrow: 'Feature guide', title: 'Agent runtime integration for custom Agents', summary: 'Recommended for custom Agents whose source and execution path can be changed, with direct governance checks in Skill loading, Tool dispatch, and runtime tracing.',
      sections: [
        {
          id: 'integration-choice',
          title: 'Confirm that direct integration is appropriate',
          paragraphs: ['This path assumes the development team controls the Agent Skill Loader, Tool Dispatcher, and runtime lifecycle. That is what allows checks to run at the real execution boundary.'],
          table: { columns: ['Runtime shape', 'Recommended path', 'Reason'], rows: [['Custom Agent Runtime or server-side Agent', 'Integrate Runtime APIs or a wrapper SDK', 'Checks can be enforced before load, before Tool execution, and across Turn/Step events'], ['Extensible internal workflow engine', 'Integrate in the owned executor or middleware', 'Stable Agent, Skill, Tool, and correlation IDs can be propagated'], ['Packaged product whose runtime cannot be changed', 'Use Agent Manager Client or the product’s supported configuration path', 'Direct integration cannot guarantee that checks run on the real execution path']] },
          callout: { type: 'note', title: 'Recommended for custom Agents', body: 'Do not use this page as the primary integration path when the real Loader and Tool dispatcher are outside your control. The Client handles local discovery, configuration delivery, Skill installation, and continuous inspection.' },
        },
        {
          id: 'verifier-setup',
          title: 'Step 1: prepare the platform Agent and runtime credential',
          paragraphs: ['The custom Agent needs a stable identity for Runtime APIs and must compute a keyless digest of the local Skill inside its real Loader.'],
          steps: [
            { title: 'Create the platform Agent', body: 'Set a stable unique Agent ID and bind the approved or deployed Skills it may use. The runtime Agent ID must match this record.' },
            { title: 'Issue an Agent runtime credential', body: 'Grant at least runtime:verify-signature and runtime:can-load. Add runtime:check-tool for Tool checks and runtime:trace for complete runtime tracing.' },
            { title: 'Inject the server-side runtime', body: 'The platform URL, runtime credential, and Agent ID must resolve to the same platform Agent. Keep the credential inside the custom Agent server process or secret container.', code: 'export AGENT_MANAGER_BASE_URL="https://agent-manager.example.com"\nexport AGENT_MANAGER_AGENT_RUNTIME_TOKEN="amat_xxx"\nexport AGENT_ID="your-agent-id"' },
            { title: 'Compute the content signature in the Loader', body: 'Use the platform-compatible manifest and ignore rules, then send the signature, Skill identifier, and Agent identity to the runtime verification endpoint.' },
          ],
          callout: { type: 'warning', title: 'Keep runtime and scanning credentials separate', body: 'Runtime APIs require the Agent-bound runtime credential. A Scanner credential can only submit scans and read its own results; it cannot establish runtime identity.' },
          link: { path: '/credentials', label: 'Open Credential Center' },
        },
        {
          id: 'verifier-result',
          title: 'Step 2: enforce checks in the real Skill load path',
          paragraphs: ['Before executing a Skill, the custom Agent verifies the local content and then checks whether the bound Agent may load it. Either failure must stop the load.'],
          flow: [{ label: 'Discover Skill', value: 'Resolve the real directory and compute its signature' }, { label: 'Verify', value: 'verify-skill-signature', type: 'decision' }, { label: 'Admission', value: 'can-load', type: 'decision' }, { label: 'Load', value: 'Enter the custom Agent Loader', type: 'success' }],
          table: { columns: ['Endpoint', 'Required scope', 'Execution point'], rows: [['POST /api/v1/access/runtime/verify-skill-signature', 'runtime:verify-signature', 'After local content is read and before executable code is loaded'], ['GET /api/v1/access/runtime/can-load/{skill_name}', 'runtime:can-load', 'After signature success and before adding the Skill to the runtime context']] },
          bullets: ['Name-only can-load does not prove that local content is unchanged. Compute and verify the actual directory signature first.', 'Continue only when both endpoints return allowed=true. Handle timeouts, 401, 403, signature mismatch, and non-loadable state according to the production deny policy.', 'Recompute the signature whenever Skill content changes.'],
        },
        {
          id: 'hook-integration',
          title: 'Step 3: integrate Tool checks and runtime tracing',
          paragraphs: ['Tool checks must run inside the custom Agent Tool Dispatcher before the real execution function. Runtime Trace correlates sessions, Turns, Steps, model requests, and Tool results; it does not replace blocking checks.'],
          table: { columns: ['Endpoint', 'Required scope', 'Purpose'], rows: [['GET /api/v1/access/runtime/check-tool', 'runtime:check-tool', 'Decide by Agent, Skill, and Tool before every Tool execution'], ['POST /api/v1/runtime-traces', 'runtime:trace', 'Create a trace session bound to the current Agent'], ['POST /api/v1/runtime-traces/{trace_id}/events:batch', 'runtime:trace', 'Batch Turn, Step, model, and Tool runtime events']] },
          callout: { type: 'warning', title: 'Check before execution', body: 'check-tool must complete before the Tool can cause side effects. Executing first and reporting later provides audit only, not runtime governance. Minimize sensitive Prompt, response, and Tool-argument data according to the Trace data policy.' },
          link: { path: '/docs/runtime-trace-guide', label: 'Read Runtime Trace fields and evidence boundaries' },
        },
        {
          id: 'acceptance', title: 'Step 4: complete integration acceptance',
          table: { columns: ['Test case', 'Expected result', 'Evidence'], rows: [['Approved, bound, unchanged Skill', 'Allow load', 'verify-signature and can-load both return allowed=true'], ['Changed local content', 'Block load', 'Signature mismatch and executable code never enters the Loader'], ['Unbound or non-loadable Skill', 'Block load', 'Stable denial reason and platform audit'], ['Unauthorized Tool', 'Block before execution', 'check-tool denies and the Tool causes no side effect'], ['Unreachable platform or invalid credential', 'Block or enter an explicit production fallback state', 'Agent result, service log, and platform audit are consistent']] },
          paragraphs: ['Keep the custom Agent result, service log, platform Runtime Audit, and Runtime Trace as the complete acceptance evidence. Creating an Agent record or issuing a credential does not establish that runtime checks are integrated.'],
          link: { path: '/runtime', label: 'Open Access & Runtime audit' },
        },
      ],
    },
    'hook-integration': {
      eyebrow: 'Feature guide', title: 'Hook integration', summary: 'Run Agent Manager checks at real Agent event points, with explicit configuration, credential, enforcement, and validation boundaries for each Hook.',
      sections: [
        { id: 'prepare', title: 'Prepare the Agent and credential', steps: [{ title: 'Create and enable the Agent', body: 'Use a stable Agent ID and bind the approved Skills it may use. AGENT_ID at runtime must match this record exactly.' }, { title: 'Issue an Agent runtime credential', body: 'The Claude Code example and the unvalidated TraeCode adapter need at least runtime:verify-signature and runtime:can-load; add runtime:check-tool when the integration performs Tool checks. The current Codex example needs at least runtime:verify-signature.' }, { title: 'Choose configuration scope', body: 'Project settings affect one project; user settings affect every project started by that user. Validate in a test project before moving to user scope.' }, { title: 'Protect the plaintext secret', body: 'Inject it through environment configuration or a user-only file outside the repository. Never put a real token in hooks.json, settings.json, screenshots, or source control.' }], callout: { type: 'warning', title: 'A Hook is not Client takeover', body: 'A Hook runs only at events the target Agent actually exposes and triggers. Agent Manager Client governs local Skill directories and performs continuous inspection. Deploy both when both boundaries are required.' }, link: { path: '/agents', label: 'Open Agents' } },
        { id: 'coverage', title: 'Understand current coverage first', table: { columns: ['Agent', 'Event and check', 'Current boundary'], rows: [['Claude Code', 'PreToolUse; verify signature and can-load after recognizing a Skill call', 'Malformed input and non-Skill calls pass through'], ['TraeCode / TRAE CN', 'Official PreToolUse support; the protocol has partial compatibility with the existing script', 'Agent Manager has not completed end-to-end validation in a real TraeCode instance'], ['Codex', 'PreToolUse; verify every discovered governed Skill before supported Tools', 'Currently covers supported paths such as Bash, apply_patch, and MCP—not every Tool path'], ['OpenClaw', 'agent:bootstrap for load checks; planned before_tool_call Tool checks', 'The repository provides a skeleton that must be adapted to the real target-version payload and plugin project']] } },
        { id: 'claude-trae', title: 'Connect Claude Code and evaluate TraeCode', paragraphs: ['Use demo/claude-code-api-hook/agent_guard_hook.py for Claude Code. It calls platform APIs with an Agent runtime credential and never needs the server signing private key. For TraeCode, treat this script only as an unvalidated adapter starting point.'], steps: [{ title: 'Install dependencies', body: 'Run this in the skill-manager source directory so the Python used by the Hook can import httpx and dotenv.', code: 'python3 -m pip install -e ".[dev]"' }, { title: 'Inject the runtime identity', body: 'All three values must resolve to the same platform Agent. Use shell or service configuration in production and keep the real token out of the repository.', code: 'export AGENT_MANAGER_BASE_URL="https://agent-manager.example.com"\nexport AGENT_MANAGER_API_TOKEN="amat_xxx"\nexport AGENT_ID="your-agent-id"' }, { title: 'Configure Claude Code PreToolUse', body: 'Claude Code uses project .claude/settings.json or user ~/.claude/settings.json. The script command must use an absolute path.', code: '{\n  "hooks": {\n    "PreToolUse": [{\n      "matcher": "",\n      "hooks": [{\n        "type": "command",\n        "command": "python3 /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py"\n      }]\n    }]\n  }\n}' }, { title: 'Configure an unvalidated TraeCode Hook', body: 'TraeCode uses project .trae/hooks.json or, on macOS/Linux, user ~/.trae-cn/hooks.json. Native configuration requires version: 1. This is a protocol adapter candidate, not a configuration that has passed real-instance acceptance.', code: '{\n  "version": 1,\n  "hooks": {\n    "PreToolUse": [{\n      "matcher": "Skill",\n      "hooks": [{\n        "type": "command",\n        "command": "python3 /absolute/path/skill-manager/demo/claude-code-api-hook/agent_guard_hook.py",\n        "timeout": 30\n      }]\n    }]\n  }\n}' }, { title: 'Run real acceptance separately', body: 'Exercise an authorized Skill, changed content, revoked authorization, and an unreachable platform in a new target-Agent session. For TraeCode, also confirm the real Skill tool_input shape, environment visibility, and exit-code-2 behavior.', expected: 'Claude Code should produce Agent UI, Hook log, and Runtime Audit evidence. Keep TraeCode marked unvalidated until the same evidence chain is complete.' }], references: [{ label: 'Claude Code: Hooks quickstart', url: 'https://code.claude.com/docs/en/hooks-guide' }, { label: 'Claude Code: Hooks reference', url: 'https://code.claude.com/docs/en/hooks' }, { label: 'Claude Code: Permissions and PreToolUse hooks', url: 'https://code.claude.com/docs/en/permissions' }, { label: 'TRAE: Automate actions with Hooks', url: 'https://docs.trae.cn/ide_automate-actions-with-hooks' }, { label: 'TRAE: Hook configuration reference', url: 'https://docs.trae.cn/ide_hook-configuration-reference' }, { label: 'TRAE CN: Changelog', url: 'https://docs.trae.cn/ide_changelog' }] },
        { id: 'codex', title: 'Connect Codex', steps: [{ title: 'Prepare an environment file outside the repository', body: 'Copy the example, then set the platform URL, Agent runtime credential, and bound Agent ID. Never commit this file.', code: 'mkdir -p ~/.agent-manager\ncp demo/codex-agent-manager-hook/codex-agent-manager-hook.env.example \\\n  ~/.agent-manager/codex-agent-manager-hook.env' }, { title: 'Configure governed roots', body: 'The Hook always checks project and user .agents/skills, ~/.codex/skills, and /etc/codex/skills when present. AGENT_MANAGER_CODEX_SKILLS_DIRS adds plugin or custom roots without disabling defaults.' }, { title: 'Install the Hook configuration', body: 'Copy the example to project .codex/hooks.json or merge it into ~/.codex/hooks.json, then replace the Python script and environment-file paths with absolute paths.', code: 'mkdir -p .codex\ncp demo/codex-agent-manager-hook/hooks.json.example .codex/hooks.json' }, { title: 'Review and validate', body: 'Restart Codex or create a new task, run /hooks in Codex CLI, and trust the Hook. A supported Tool call should return permissionDecision=deny when any governed Skill is unapproved, unbound, or modified; it should pass after correction.' }], callout: { type: 'warning', title: 'Codex coverage boundary', body: 'The current Codex PreToolUse example is fail-closed for calls it can intercept, but it does not cover every Shell, WebSearch, or other Tool path. It does not replace OS sandboxing, plugin trust, or controlled Skill deployment.' }, references: [{ label: 'OpenAI Docs: Codex Hooks', url: 'https://learn.chatgpt.com/docs/hooks' }, { label: 'OpenAI Docs: Codex configuration reference', url: 'https://learn.chatgpt.com/docs/config-file/config-reference' }] },
        { id: 'openclaw', title: 'Connect OpenClaw', steps: [{ title: 'Capture a real payload first', body: 'Install the payload recorder in demo/openclaw-agent-manager-hook, trigger agent:bootstrap, and inspect ~/.openclaw/logs/hook-payloads.jsonl.' }, { title: 'Adapt load verification', body: 'Use the real event to tighten discoverVisibleSkills and resolveSkillNameFromContext, then install the internal Hook as a managed Hook.' }, { title: 'Connect Tool checks', body: 'before_tool_call is not an internal Hook event. Integrate plugin-hooks.ts into the real OpenClaw plugin project and call check-tool. Map session identity to a stable platform Agent ID.' }], callout: { type: 'warning', title: 'Not a turnkey integration yet', body: 'The OpenClaw example is a skeleton. Do not claim enforced Skill-load and Tool-call coverage until it has been adapted and tested against the target OpenClaw event and plugin APIs.' } },
        { id: 'verify-troubleshoot', title: 'Acceptance tests and troubleshooting', table: { columns: ['Scenario', 'Expected result', 'Check first'], rows: [['Approved, bound, unchanged Skill', 'Allow', 'Agent ID, credential binding, Skill path, and digest'], ['Modified Skill content', 'Block', 'Consistent signature ignore sets; exclude .DS_Store on macOS'], ['Skill not bound or wrong credential', 'Block', 'Agent bindings, credential type, state, and scopes'], ['Platform unreachable or credential expired', 'Declared fail-closed paths block', 'URL, proxy, certificate, timeout, and Hook stderr'], ['No Hook log at all', 'Integration is not proven', 'Session cwd, project/user settings scope, event name, and whether the Tool triggers that Hook']] }, bullets: ['Check the Agent result, local Hook log, and platform Runtime Audit together.', 'Exercise allow, tamper, unauthorized, unreachable, and event-not-triggered cases.', 'Roll out to one test project before user-level or enterprise templates.'], link: { path: '/runtime', label: 'Open Access & Runtime audit' } },
      ],
    },
    'client-management': {
  "eyebrow": "Feature guide",
  "title": "Client management",
  "summary": "Configure Agent discovery and classification policies, manage local Skills, and verify synchronization, scanning, and recovery.",
  "sections": [
    {
      "id": "desktop-and-console",
      "title": "What the Client and console do",
      "paragraphs": [
        "The Client discovers local Agents, validates actual Skill content, installs trusted versions, and executes remediation. The console approves and signs content, distributes configuration, manages default and per-client rules, and collects tasks and events."
      ],
      "image": {
        "name": "client-app-overview",
        "alt": "Client Overview: items needing attention and management scope.",
        "caption": "Client Overview: items needing attention and management scope. Captured directly from the installed macOS Dev client on 2026-10-10; displayed states are observations at capture time."
      }
    },
    {
      "id": "install-register",
      "title": "Install and connect",
      "paragraphs": [
        "In Credential Center, choose the Client route and create a credential. Enter the platform URL and credential in the desktop Client, then check its background service. A running background service continues after the window closes.",
        "For model switching, explicitly allow automatic Agent credential issuance and restrict configurable models. The Client credential itself cannot call models or MCP.",
        "New Client credentials default to a 100 MB request-body limit (102400 KB); existing credentials retain their settings. Skill submissions also have content-size, per-file, file-count, and server upload limits. Raising the credential limit does not remove other limits."
      ]
    },
    {
      "id": "client-pages",
      "title": "Where to find each operation",
      "paragraphs": [],
      "table": {
        "columns": [
          "Entry",
          "Purpose"
        ],
        "rows": [
          [
            "Client Overview → Overview",
            "Action items, local Agents, and managed Skill counts."
          ],
          [
            "Client Overview → Runtime & Sync",
            "Background service, synchronization, and recent runtime information."
          ],
          [
            "Client Overview → Scan policies",
            "Effective classification rules cached on this machine."
          ],
          [
            "Agent Management",
            "Choose an Agent and switch between Local Skills, Scan Records, and Quarantine Copies; search, filter, install, and submit."
          ],
          [
            "Model Switching",
            "View and switch permitted gateway models per local Agent."
          ],
          [
            "Activity Records",
            "Filter and paginate Inspection & Remediation and Platform Tasks separately."
          ],
          [
            "Top-right bell",
            "Security notifications, failures, and remediation links."
          ],
          [
            "Top-right gear → Settings",
            "Connection, language, notifications, background operation, updates, and diagnostics."
          ]
        ]
      }
    },
    {
      "id": "discovery-config",
      "title": "Configure Agent discovery from the console",
      "paragraphs": [
        "Open Client Management → Agent Discovery. Search by Agent name or identifier and set enabled state, operating systems, and Skill roots, one root per line. Relative paths start at the client user home, for example .qoderwork/skills; dynamic user directories may use a standalone * path segment. Saving submits the complete configuration; search only filters the display.",
        "Built-in definitions cover Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw, Hermes, TRAE, Cursor, CodeBuddy, WorkBuddy, TeleAgent, Qoder, Qoder CN, QoderWork, and ZCode. TeleAgent defaults to .config/TeleAgent/users/*/skills and expands only existing user Skill directories, so it does not depend on a fixed user ID. Claude Desktop, Kimi Work, and Doubao Work are initially disabled with empty roots; verify their actual directories before enabling them.",
        "Online clients receive configuration-sync tasks and rediscover. Offline clients keep cached configuration. Local root overrides take precedence. Saving a path neither installs an Agent nor creates a missing directory.",
        "If a root does not take effect, check the saved value, synchronization task, local overrides, operating system, and directory existence. Receiving configuration and discovering an Agent are separate outcomes."
      ],
      "image": {
        "name": "client-discovery-config",
        "alt": "Agent discovery in Chrome: search by name or identifier and inspect the matching roots.",
        "caption": "Agent discovery in Chrome: search by name or identifier and inspect the matching roots."
      }
    },
    {
      "id": "discover-govern",
      "title": "Inspect Skills in Agent Management",
      "paragraphs": [
        "Select an Agent in the top bar, then choose Local Skills, Scan Records, or Recovery Copies. The folder icon opens the selected Agent directory.",
        "Certified means the local content matches an approved platform version and passes validation. Approval of a Skill with the same name is not proof that these local bytes match. Certification pending means no valid conclusion is available yet; inspect row details for sync, path, or scanning errors.",
        "Installing from a specific Skill action locates that Skill in the platform catalog. Check the target Agent and trusted version. Installation validates release signatures and file digests before certification."
      ],
      "image": {
        "name": "client-app-discovery",
        "alt": "Agent Management groups local Skills, scan records, and quarantine copies by Agent.",
        "caption": "Agent Management groups local Skills, scan records, and quarantine copies by Agent. Captured from the actual desktop Client window."
      },
      "callout": {
        "type": "note",
        "title": "Shared roots",
        "body": "Shared Skill roots appear separately. Multiple Agents may read the same root; the directory does not establish caller identity."
      }
    },
    {
      "id": "governance-modes",
      "title": "Default and per-client policies",
      "paragraphs": [
        "Client management → Client policies provides shared rules. For a device, open Client details → Policies and approvals → Collection and governance settings. Model and requests configures Token compression and Prompt Guard; Skill handling configures classification rules. Prompt Guard defaults to log only and Token compression defaults to off. Both support default inheritance or a per-client override; Skill rules inherit individually. Default updates preserve explicit client overrides.",
        "Desktop Scan policies show synchronized rules. Saving Prompt Guard updates active credentials created by model switching; new and rotated credentials inherit the current values. Subsequent gateway requests use the saved configuration, while long polling synchronizes desktop settings and versions. The LLM review flag is stored without executing a review. Check overrides and synchronization tasks when values differ."
      ],
      "image": { "name": "client-app-policy", "alt": "Client Overview → Scan policies: synchronized Skill handling rules.", "caption": "Client Overview → Scan policies: synchronized Skill handling rules. Captured directly from the installed macOS Dev client on 2026-10-10; displayed states are observations at capture time." },
      "table": {
        "columns": [
          "Trigger",
          "Meaning"
        ],
        "rows": [
          [
            "Not platform-certified",
            "Current local content is not a trusted platform version."
          ],
          [
            "Unverified Skill content changed",
            "Previously unverified content changes again."
          ],
          [
            "Certified Skill content changed",
            "Certified content differs from its trusted version."
          ],
          [
            "Platform-confirmed malicious",
            "Current content is confirmed malicious; this rule determines handling."
          ],
          [
            "Changed content rejected (trusted version available)",
            "Changed content is rejected and a trusted version is available."
          ],
          [
            "Content rejected (no trusted version)",
            "Content is rejected with no trusted version available."
          ]
        ]
      }
    },
    {
      "id": "policy-actions",
      "title": "What each action does",
      "paragraphs": [],
      "table": {
        "columns": [
          "Action",
          "Effect"
        ],
        "rows": [
          [
            "Record only",
            "Retain local files and record the event without a security alert for this action."
          ],
          [
            "Record and alert",
            "Retain files, record the event, and raise an alert."
          ],
          [
            "Submit for platform scanning",
            "Submit current content; separate rejection rules apply with and without a trusted version."
          ],
          [
            "Quarantine",
            "Remove the Agent entry point and retain a copy for scanning or recovery."
          ],
          [
            "Uninstall (keep recovery copy)",
            "Remove the current entry point and retain a recovery copy."
          ],
          [
            "Restore trusted version",
            "Restore trusted content allowed by current policy and authorization."
          ]
        ]
      },
      "callout": {
        "type": "note",
        "title": "Scanning errors are not rejection",
        "body": "Upload failures, timeouts, and scanner errors do not mean content was rejected and do not trigger rejection rules. Available actions depend on the trigger."
      }
    },
    {
      "id": "policy-preview",
      "title": "Preview impact before saving",
      "paragraphs": [
        "Preview Impact initially shows client-level Agent and Skill counts with estimated actions. Expand the client and then an Agent to inspect individual Skills, paths, and actions.",
        "Estimates use content information already reported to the platform. Insufficient information produces an unavailable estimate; actual handling still depends on client validation. Run an inspection, wait for reporting, and preview again when more evidence is needed.",
        "After saving, inspect the policy-sync task. Policy applied means configuration was retrieved and saved, not that all Skill remediation finished. Review events and activity records for actual remediation."
      ]
    },
    {
      "id": "model-policy-sync",
      "title": "Verify model policy synchronization",
      "paragraphs": ["Open Scan policies in Client Overview to inspect Prompt Guard, Token compression, and synchronization status. Prompt Guard defaults to log only and compression defaults to off.", "After saving in the console, subsequent gateway requests use the updated credential settings. Long polling synchronizes the desktop display. Pending synchronization or offline cache means the client has not confirmed the latest configuration."]
    },
    {
      "id": "continuous-governance",
      "title": "Synchronization and inspection timing",
      "paragraphs": [
        "Platform tasks use long polling: the Client waits on a request, the server returns available tasks, and the Client then waits again. Classification-policy and Agent-discovery saves create synchronization tasks, without waiting for the next heartbeat. Reconnection, queues, and execution can still add latency.",
        "Background heartbeats run at intervals of up to about 10 seconds. Regular inspection defaults to 5 minutes and full inspection to 30 minutes. File changes also trigger checks. These schedules are separate from task long polling.",
        "To inspect immediately, open the gear → Settings → Background Operation → View Runtime Diagnostics → Run Inspection Now. It executes the currently effective policy.",
        "While offline, the Client uses its last synchronized policy and retains queued events. It resumes syncing and reporting when connected; operations requiring platform validation or downloads may fail or await retry."
      ],
      "image": {
        "name": "client-app-status",
        "alt": "Client Overview → Runtime & Sync: background governance, last sync and queued events.",
        "caption": "Client Overview → Runtime & Sync: background governance, last sync and queued events. Captured directly from the installed macOS Dev client on 2026-10-10; displayed states are observations at capture time."
      }
    },
    {
      "id": "quarantine-recovery",
      "title": "Scan and restore quarantine copies",
      "paragraphs": [
        "In the target Agent’s Recovery Copies tab, submit one copy or select multiple pending copies. The row shows submission state; subsequent platform conclusions appear in Scan Records and quarantine.",
        "Submission only means the platform accepted the request. Automatic installation or recovery requires approval of the corresponding content plus current policy, content validation, and authorization checks. Scanning, pending review, and scan errors are not approval.",
        "A submission from an Agent’s quarantine targets that Agent and the corresponding original path. Exact content already matching an approved version can also be checked for automatic restoration without resubmitting.",
        "Existing destination content, invalid source paths, ambiguous roots, permissions, or failed validation may block recovery. The Client does not overwrite files merely because names match. Inspect notifications, row details, and activity records after failure. Manually quarantined copies are not automatically released by background matching.",
        "A passed scan can coexist with a remaining quarantine copy when installation or recovery has not succeeded. Scan results and restoration results are separate."
      ],
      "image": {
        "name": "client-app-quarantine",
        "alt": "Quarantine copies show scan status and available actions for the selected Agent.",
        "caption": "Recovery Copies in the desktop Client; the selected Agent had no recovery copies when captured."
      }
    },
    {
      "id": "console-management",
      "title": "Verify tasks and recent events in the console",
      "paragraphs": [
        "The client list shows online state and Agent and Skill counts. Open Client details to inspect local Agents, platform tasks, and recent events.",
        "Task created does not mean execution completed. Inspect pending, running, succeeded, or failed state and the failure reason before retrying.",
        "Recent events use server-side pagination with 10 entries per page, newest occurrence first. Older history beyond 100 entries remains accessible, and refreshing details preserves the current page."
      ],
      "link": {
        "path": "/clients",
        "label": "Open Client Management"
      }
    },
    {
      "id": "recent-events",
      "title": "Page through recent events",
      "paragraphs": [
        "Use the pagination controls at the bottom of Client details to inspect older events. Refresh preserves the current page; opening another client starts at page one. Events are sorted by latest occurrence."
      ],
      "image": {
        "name": "client-events",
        "alt": "Client recent-events pagination",
        "caption": "Live console: pagination makes older client events accessible."
      }
    },
    {
      "id": "agent-model-config",
      "title": "Switch gateway models per local Agent in the Client",
      "steps": [
        {
          "title": "Delegate a model boundary",
          "body": "Enable automatic Agent credential issuance on the Client credential and optionally restrict Models the Client may configure. An empty list means all enabled models. The Client credential itself cannot call models or MCP."
        },
        {
          "title": "Choose a local Agent",
          "body": "Open Model Switching and select discovered Claude Code, Codex, or Hermes. The page reads the current model, gateway URL, and configuration path from disk."
        },
        {
          "title": "Confirm where the gateway URL comes from",
          "body": "The Client has no separate model-gateway URL field. It reuses the Agent Manager URL entered during enrollment. Claude Code uses that root URL; Codex and Hermes normalize it to a Base URL ending in /v1. This is not the upstream provider URL configured by an administrator."
        },
        {
          "title": "Create the runtime identity automatically",
          "body": "If the local Agent has no runtime identity, the first switch creates a Client-owned managed Agent and binds it automatically. No matching Agent needs to be created or selected in advance."
        },
        {
          "title": "Select and switch",
          "body": "The catalog shows only enabled models inside the delegated Client boundary. The sidecar retrieves an Agent-bound runtime credential in-process, backs up and merges the local configuration, then reads live state again.",
          "expected": "Claude Code uses Anthropic Messages, Codex uses a Responses model provider, and Hermes uses OpenAI-compatible Chat Completions. The desktop renderer never receives the credential plaintext."
        }
      ],
      "image": {
        "name": "client-app-models",
        "alt": "Desktop Client Model Switching page",
        "caption": "Model Switching shows the live local model, the gateway URL derived from the Agent Manager enrollment URL, the configuration path, and models delegated to the credential. Captured from the actual desktop Client window."
      },
      "callout": {
        "type": "note",
        "title": "Model and MCP boundary",
        "body": "The managed Agent is an identity and audit anchor; it does not require the model to match the Agent type. Generated credentials include runtime checks and model:chat restricted to the selected model. If the managed Agent already has MCP gateways, the generated credential also preserves mcp:connect, mcp:list-tools, mcp:call-tools and the same gateway allowlist. MCP server configuration remains a separate feature."
      },
      "link": {
        "path": "/credentials",
        "label": "Create a Client credential with Agent issuance authorization"
      }
    },
    {
      "id": "diagnostics",
      "title": "Troubleshooting",
      "paragraphs": [
        "Start with Skill row details, Security Notifications, and Activity Records. Separate path errors, certification, execution failures, and synchronization failures. A completed scan is not approval; approval is not successful installation.",
        "Settings → Diagnostics lets you choose log retention and export range, open log or data directories, and export a report. The report excludes plaintext access credentials, raw databases, and Skill source files. Review machine, path, and runtime information before sharing.",
        "Skill submissions default to 100 MiB total content, 20 MiB per file, and 20000 files. Address the limit at the failing layer. Fingerprint mismatch is a content-validation issue; increasing upload size alone does not fix it."
      ]
    }
  ]
},
    'model-gateway': {
      eyebrow: 'Feature guide', title: 'Model gateway', summary: 'Proxy model traffic and centralize access control, Prompt protection, privacy replacement, optional context compression, usage analysis, and call audits.',
      sections: [
        { id: 'feature-map', title: 'Pages and capabilities', table: { columns: ['Page', 'What it controls or explains'], rows: [['Providers / Models', 'Register upstream endpoints and model limits, formats, and enabled state.'], ['Group policies / Privacy policies', 'Bind model access and PII handling to user groups.'], ['Prompt Guard', 'Test and audit prompt injection, system prompt leakage, and credential exfiltration patterns.'], ['Skill Alerts', 'Compare Skills declared by callers with registry, state, and Agent authorization.'], ['Privacy Audit / Pipeline Trace', 'Inspect results and original, replaced, compressed, upstream, and restored stages.'], ['Token Compression Stats / User Token Analytics', 'Inspect requests, token use, savings, processing time, and user-level consumption.']] } },
        { id: 'setup-flow', title: 'Setup order', steps: [{ title: 'Add a provider', body: 'Select OpenAI Chat Completions, OpenAI Responses API, or Anthropic Messages compatibility, then configure the endpoint and provider secret.' }, { title: 'Register models', body: 'Set model name, context size, output limits, and enabled state.' }, { title: 'Configure groups and privacy policies', body: 'Choose PII entities, Prompt protection, and session mapping behavior.' }, { title: 'Issue a model credential', body: 'Limit models, request size, and concurrency; compression may also be enabled only for selected credentials.' }, { title: 'Call and inspect the trace', body: 'Use an OpenAI- or Anthropic-compatible endpoint, then inspect the privacy pipeline.' }], link: { path: '/model-gateway/providers', label: 'Open Providers' } },
        { id: 'provider-protocols', title: 'Upstream protocols and model discovery', paragraphs: ['Include the provider version path in the Base URL. Chat Completions appends /chat/completions, Responses API appends /responses, and Anthropic appends /messages. Full inference endpoints are accepted.', 'All three formats discover models through the sibling /models endpoint; Anthropic supports cursor pagination. Compatible services may omit listing. Add a model manually and use Test to verify actual inference access.', 'Different providers may register the same upstream model name. Already added applies only to the current provider. Gateway model names are globally unique, generated when omitted, and fixed after creation. Credential, documentation, Skill policy, Agent and client selectors show provider identity and store the gateway name.', 'Responses supports text, images, function tools and results, structured output, reasoning effort, and SSE through the gateway authorization and privacy pipeline with store: false. Response persistence and background jobs are outside this adapter.'] },
        { id: 'pipeline', title: 'What happens to a request', bullets: ['Validate credential state, model scope, request size, and concurrency.', 'When the matching policy enables it, detect prompt injection, system prompt leakage, and credential exfiltration patterns.', 'When a privacy policy matches, replace PII with session-scoped pseudonymous tokens.', 'When the calling credential enables compression, process context before the upstream call.', 'Restore the response and record audit, usage, and trace stages.'] },
        { id: 'compatible-endpoints', title: 'Choose the compatible endpoint for each Agent', table: { columns: ['Caller', 'Gateway endpoint', 'Purpose'], rows: [['Claude Code', 'POST /v1/messages', 'Anthropic Messages-compatible requests.'], ['Codex', 'POST /v1/responses', 'Responses protocol through a custom model_provider.'], ['Hermes and regular OpenAI-compatible clients', 'POST /v1/chat/completions', 'Chat Completions-compatible requests.'], ['Model discovery', 'GET /v1/models', 'Credential-filtered OpenAI or Anthropic model lists with cursor pagination.'], ['Model details', 'GET /v1/models/{model_id}', 'Retrieve an authorized model.'], ['Token estimate', 'POST /v1/messages/count_tokens', 'Local estimate; response header identifies estimated-utf8.']] }, callout: { type: 'note', title: 'Protocol boundary', body: 'All three endpoints share credential, model-scope, privacy, and audit checks, but their wire fields are not interchangeable. Model Switching writes the correct endpoint and disables server-side web search and image generation for Codex. Send full Responses history with store set to false.' } },
        { id: 'token-compression', title: 'Token compression and usage analysis', paragraphs: ['Credentials with model:chat configure compression and its auto, conservative, or aggressive level. Automatically issued client credentials use default or per-client policies. Saving updates existing automatic credentials and future issuance or rotation; long polling synchronizes desktop state. The platform processes messages before the upstream call and records token counts before and after compression, savings, ratio, and processing time.'], bullets: ['Token Compression Stats groups requests, input and output tokens, savings, average response time, model time, and platform time by period and model.', 'User Token Analytics compares call volume and token consumption across users.', 'Response headers and Pipeline Trace help distinguish compressed, enabled with no transformation, and disabled requests.'], callout: { type: 'note', title: 'Enabled does not mean every request saves tokens', body: 'Short context may need no transformation. If the compression component is unavailable or fails, the gateway falls back to the original messages, so enabled must not be interpreted as saved.' }, image: { name: 'token-compression', alt: 'Token Compression Stats page', caption: 'The stats page combines token usage, compression requests, savings, and platform and model timing. Values shown are example environment data.' }, link: { path: '/model-gateway/stats', label: 'Open Token Compression Stats' } },
        { id: 'skill-alerts', title: 'Skill Alerts in model requests', paragraphs: ['When a caller declares Skills in a model request, the platform compares them with Skill registration, loadable state, and Agent authorization, then records missing, unknown, mismatched, unavailable, or unauthorized declarations.'], callout: { type: 'warning', title: 'Currently audit-only', body: 'Skill Alerts do not block model calls. Caller-declared Skill metadata is not local signature or content verification; use Skill Verifier or Client inspection when content integrity is required.' }, link: { path: '/model-gateway/skill-alerts', label: 'Open Skill Alerts' } },
        { id: 'privacy', title: 'Privacy trace boundaries', paragraphs: ['Pipeline Trace can show original, masked, compressed, upstream, and restored content. Original stages may contain PII and should be limited to authorized administrator or privacy auditor roles.'], link: { path: '/pipeline-trace', label: 'Open Pipeline Trace' } },
      ],
    },
    'system-management': {
      eyebrow: 'Feature guide', title: 'System management', summary: 'Configure accounts, roles, menus, and branding; inspect login, operation, and security logs; and check system health.',
      sections: [
        {"id": "accounts", "title": "Account management", "paragraphs": ["Use System Management → Accounts to create accounts, assign roles and groups, and manage account status."], "bullets": ["Enter a username and initial password, optionally add an email, and choose a role, groups, and status. Usernames allow English letters, digits, underscores, dots, and hyphens, up to 64 characters.", "Edit email, role, and groups; the username is read-only after creation. Reset passwords through the separate action.", "Disabling an account or resetting its password invalidates existing sessions. Disable accounts that still have business references when appropriate.", "Filter by keyword, role, status, or group, and sort by creation or last sign-in time. Available actions depend on your permissions."], "link": {"path": "/users", "label": "Open Accounts"}, "image": {"name": "system-accounts", "alt": "Account management", "caption": "Account management"}},
        {"id": "account-create", "title": "Create an account", "paragraphs": ["Enter account details using the username rules, select the required role and groups, and enter the initial password during creation."], "image": {"name": "system-account-create", "alt": "Account creation form and username rules", "caption": "Account creation form and username rules"}},
        {"id": "roles", "title": "Roles and permissions", "paragraphs": ["Roles control accessible pages and allowed actions. Each account has one role; groups organize accounts and bind business policies."], "bullets": ["Create a role with a stable identifier, display name, and description.", "Choose actions by module under Configure permissions and select an accessible default page. Configure permissions before using a new role.", "Saved permissions apply to subsequent requests. Built-in management roles retain management permissions; grant other roles permissions according to their duties.", "Resolve account assignments before deleting a role. Your own account and the last active administrator are protected."], "link": {"path": "/roles", "label": "Open Roles"}, "image": {"name": "system-roles", "alt": "Roles and permissions", "caption": "Roles and permissions"}},
        {"id": "menus", "title": "Menu management", "paragraphs": ["Maintain navigation directories, page entries, and display order. Expand or collapse directories to inspect their hierarchy."], "bullets": ["Add a directory or page entry with Chinese and English titles, an icon, parent directory, and order. The hierarchy supports up to three levels.", "Choose page entries from existing features; Move up and Move down reorder siblings.", "Enabled status controls navigation visibility; role permissions control access.", "Manage built-in entries through enabled status. Resolve child menus and role default-page references before deleting a custom entry."], "link": {"path": "/menus", "label": "Open Menus"}, "image": {"name": "system-menus", "alt": "Menu management", "caption": "Menu management"}},
        {"id": "login-audit", "title": "Login logs", "paragraphs": ["Review successful and failed sign-ins to investigate account and authentication issues."], "bullets": ["Inspect time, actor, result, failure reason, and source IP.", "Filter by keyword, actor, result, or time range. Open details for request identifiers and complete records."], "link": {"path": "/system-audit?tab=login", "label": "Open Login Logs"}, "image": {"name": "system-login-audit", "alt": "Login logs", "caption": "Login logs"}},
        {"id": "operation-audit", "title": "Operation logs", "paragraphs": ["Trace management actions, configuration changes, and sensitive reads, such as editing accounts, assigning roles, and updating branding."], "bullets": ["Filter by module and action; related HTTP request actions are grouped into business actions.", "Open details for the event, target, and request context. Compare before and after fields when available, or expand the original record."], "link": {"path": "/system-audit?tab=operation", "label": "Open Operation Logs"}, "image": {"name": "system-operation-audit", "alt": "Operation logs", "caption": "Operation logs"}},
        {"id": "security-audit", "title": "Security audit", "paragraphs": ["Review security events for scans, credentials, and privacy access."], "bullets": ["Inspect the actor, module, action, target, and result. Details include the event type and event identifier.", "With permission, select Verify audit chain to check for changed records or broken links between them. Hover over the button for an explanation.", "All three tabs show newest records first, with 10 records per page by default. Change the page size as needed. Filters apply automatically; Reset clears them. Reloading preserves the selected log tab.", "Compact rows shorten long values; hover or open details for the full text. Times use Beijing time (UTC+8)."], "link": {"path": "/system-audit?tab=security", "label": "Open Security Audit"}, "image": {"name": "system-security-audit", "alt": "Security audit", "caption": "Security audit"}},
        {"id": "branding", "title": "Logo, system names, and company name", "paragraphs": ["Open System Management → System Overview → Branding and system names."], "bullets": ["Enter Chinese and English system names and a company name, then select Save names. System names follow the interface language; the company name stays as entered.", "Upload a PNG, JPEG, GIF, or WebP logo up to 5 MB, or restore the default logo.", "Saved branding updates the login page, header, help name, and browser title. Changes require permission to edit system settings.", "Names are stored in the database and the logo in the uploads directory. Retain the corresponding Docker data volumes to preserve them."], "link": {"path": "/settings", "label": "Open branding settings"}, "image": {"name": "system-branding", "alt": "Logo, system names, and company name", "caption": "Logo, system names, and company name"}},

        { id: 'users-groups', title: 'User groups', paragraphs: ['Groups organize people and Agents and also drive model access and privacy policy bindings. Grant the minimum permissions required for each role.'], link: { path: '/users-groups', label: 'Open User Groups' } },
        { id: 'system-status', title: 'System status', bullets: ['Core services: verify the Backend API, content-integrity signing key, and audit entry point.', 'Scan analysis: verify Sandbox connectivity, LLM analysis model, and deep-analysis capability.', 'Model gateway: verify available models, model credentials, privacy policies, and Prompt Guard test.', 'Access chain: verify Agent runtime credentials, Runtime validation API, Scanner access credentials, and unified audit.', 'Unavailable dependencies should leave corresponding submission checks disabled.'], image: { name: 'system', alt: 'System overview page', caption: 'Resolve core service failures before diagnosing scan results.' }, link: { path: '/settings', label: 'Open System Overview' } },
        { id: 'docs-assistant', title: 'Documentation export and assistant', paragraphs: ['Administrators can export help materials and configure the Docs Assistant under System Management → Documentation settings. PDF creates a searchable document from selected help modules. Excel creates Overview and filterable Feature list sheets from selected product-capability modules. When the assistant is enabled, Ask AI appears in the help header and answers from the current docs with verified internal links.'], bullets: ['PDF supports Complete documentation, Usage and governance, Administration and operations, or a custom article scope in Chinese or English. The downloaded file includes text, tables, code, screenshots, a page contents section, and a PDF sidebar outline grouped by module and article.', 'Excel supports All product features, Core governance capabilities, System and operations, or custom capability areas in Chinese or English. Each row includes a description, usage scenario, entry point, capability boundary, and related help article.', 'The Docs Assistant is disabled by default and cannot be enabled without an available model. The browser sends only a limited set of relevant excerpts from the current-language docs.', 'The model must answer only from supplied excerpts; internal links come from the documentation index rather than model-generated URLs.', 'Signed-in users may use the assistant, while only administrators may change documentation settings.', 'If assistant settings have unsaved changes, the page asks for confirmation before navigation, reload, or tab closure.', 'AI answers help with navigation; the documentation and actual system configuration remain authoritative.'], link: { path: '/docs-settings', label: 'Open Documentation Settings' } },
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
        { id: 'pending', title: 'Why does a Skill keep showing SCANNING?', paragraphs: ['Inspect scan runs first, then check backend logs and the deep-analysis, LLM, and Sandbox state in System Overview. Scanner access credentials affect only customer-side Scanner uploads and are not a prerequisite for ZIP scanning. SCANNING means the backend Skill is PENDING or has a PENDING scan run. A rescan preserves the previous admission status while it runs; do not assume a browser cache problem.'] },
        { id: 'different-results', title: 'Why is Sandbox low risk while final risk is higher?', paragraphs: ['Sandbox only sees behavior triggered during one probe. Static patterns, untriggered branches, and LLM evidence may still raise final risk.'] },
        {
          id: 'llm-safe-final-malicious',
          title: 'Why does the LLM report no apparent risk while final risk is malicious?',
          paragraphs: ['No apparent risk is the model assessment. Final risk reconciles tool risk and the LLM conclusion under the policy used for this scan. Malicious risk is retained in these two cases:'],
          bullets: [
            'Findings are in Classify as malicious: rule, deep-scan, or Sandbox findings assigned to this group establish malicious risk that LLM cannot lower. For example, a data-transfer finding classified as malicious retains that risk even if the LLM describes it as a normal upload.',
            'The scan uses strict mode: LLM cannot lower tool risk. If tool risk is malicious, an LLM conclusion of No apparent risk does not change the final risk.',
          ],
          steps: [
            { title: 'Inspect the recorded decision', body: 'Open Skill details > Detection Report > Decision trace and read The LLM conclusion differs from final risk. When the relevant records exist, select View findings that retained malicious risk to inspect evidence, or View original LLM analysis to inspect the model opinion. Historical reports without reconciliation evidence explicitly state that the specific reason cannot be confirmed.' },
            { title: 'Check classifications and policy', body: 'If you suspect a false positive, inspect the original evidence and configuration used for this scan. If an adjustment is needed, edit the relevant risk identification rules or decision mode in policy settings, save, and rescan. Existing reports retain their conclusions. Admission settings separately route malicious risk to manual review or automatic rejection.' },
          ],
          link: { path: '/docs/risk-classification', label: 'Read risk reconciliation' },
        },
        { id: 'review-queue', title: 'Why is a Skill missing from the review queue?', paragraphs: ['The VETTED filter shows items awaiting review with no active scan. SCANNING covers initial scans and rescans. A rescan may retain the previous backend admission status, such as APPROVED or VETTED. Check the final status and review actions when scanning finishes.'] },
        { id: 'rescan', title: 'Why did an identical submission not run again?', paragraphs: ['Identical content and scan context may reuse results. Use Rescan for a fresh run; submit changed content as a new version.'] },
        { id: 'agent-blocked', title: 'Why can an Agent not load an approved Skill?', paragraphs: ['Check that the runtime credential is bound to the Agent, the Agent is authorized for the Skill, the local signature matches, and signature verification happened before the load check.'] },
        { id: 'credential-lost', title: 'Can a lost credential secret be shown again?', paragraphs: ['No. The server stores only a hash. Revoke the old credential, create a new one, and update the caller.'] },
        { id: 'client-offline', title: 'Why is a Client offline or unable to deliver a Skill?', paragraphs: ['Check the Client background service, platform address, Client access credential, and last heartbeat. If delivery fails, confirm that the Skill is approved and the target Agent supports Skill management. Strict Agent authorization also requires a completed automatic registration and the corresponding allowed Skill scope.'] },
        { id: 'compression-zero', title: 'Why are token savings zero after compression is enabled?', paragraphs: ['Confirm that compression is enabled on the credential used by this call, then inspect the trace or response headers. Short context may need no transformation; if compression is unavailable or fails, the gateway falls back to the original messages. Enabled therefore does not guarantee savings on every request.'] },
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
  summary: 'Start with who will use the credential, then define models, MCP gateways, and API access. Raw scopes and capacity limits stay in Advanced security settings.',
  sections: [
    {
      id: 'choose-caller', title: 'Choose the real caller instead of guessing a credential type',
      paragraphs: ['The Credential routes at the top create by calling scenario. The caller is the running program that sends the Bearer credential, not the administrator configuring the system.'],
      table: { columns: ['Route', 'Choose it when', 'Do not mix it with'], rows: [
        ['For an Agent', 'A registered Agent needs runtime checks and may also call models or MCP', 'Do not add a regular model credential to impersonate the same Agent'],
        ['LLM Credential', 'Call large language models through the model gateway', 'It cannot establish trusted registered-Agent identity'],
        ['For an MCP client', 'An MCP Client that is not a platform Agent calls published Tools', 'It cannot reach gateways outside its allowlist'],
        ['For Skill Scanner', 'A customer-side Scanner uploads Skills and polls its own results', 'It cannot approve, deploy, or read results owned by others'],
        ['For Agent Manager Client', 'A desktop or background Client registers, heartbeats, syncs inventory, and executes tasks', 'It cannot call models or MCP; explicit authorization may let it issue separate credentials for locally bound Agents through configuration tasks'],
      ] },
      link: { path: '/credentials', label: 'Open Credential routes' },
      image: { name: 'credential-center', alt: 'LLM Credential entry in the credential center', caption: 'Select LLM Credential for an application to call large language models through the model gateway.' },
    },
    {
      id: 'credential-types', title: 'Credential types behind the routes',
      table: { columns: ['Credential type', 'Required binding or boundary', 'Default purpose'], rows: [
        ['Agent runtime', 'Must bind one Agent; select allowed gateways when using MCP', 'Signature, load, and Tool checks; composable governance, model, and MCP scopes'],
        ['Scanner access', 'Reads only owned submissions', 'Batch Skill upload and owned-result polling'],
        ['Client access', 'Associates with a Client after registration', 'Registration, heartbeat, policy, tasks, inventory, events, and approved downloads'],
        ['Model gateway', 'May restrict allowed models', 'Model calls with optional token compression and Prompt Guard'],
        ['MCP gateway', 'Must select allowed gateways', 'Connect, discover, and call published MCP Tools'],
      ] },
    },
    {
      id: 'create', title: 'Create a credential in page order',
      steps: [
        { title: 'Choose the caller from Credential routes', body: 'The page supplies the matching credential type and minimum permissions. Create the Agent before an Agent runtime credential and publish a gateway before enabling MCP.' },
        { title: 'Use an auditable name and bind identity', body: 'Include purpose and environment, such as “Support Agent production runtime.” Agent routes must select the registered Agent represented by the credential.' },
        { title: 'Choose capabilities and resource boundaries', body: 'Start an Agent with Runtime checks only, then add governance, models, or MCP when needed. Model and MCP routes select their allowed resources.' },
        { title: 'Open Advanced security settings only when needed', body: 'Raw scopes, Prompt Guard, context compression, source IP, body size, and concurrency live there. Prompt Guard defaults to log only; Token compression defaults to off.' },
        { title: 'Save and copy immediately', body: 'The secret appears once. Store it in the caller secure configuration, never source, screenshots, or normal logs.', expected: 'The list shows prefix, caller, accessible capabilities, and status. Expand a row to verify scopes, resources, and security limits.' },
      ],
    },
    {
      id: 'model-controls', title: 'Credentials with model:chat',
      image: { name: 'credential-protection', alt: 'Credential advanced settings: log-only Prompt Guard and compression off', caption: 'Current UI with example data: new model credentials default to log-only Prompt Guard and Token compression off.' },
      bullets: ['Model gateway credentials include model:chat by default. Agent runtime credentials require Governance + Model or an explicit model:chat scope.', 'Allowed models may be restricted. An empty list means no credential-level model restriction, not a bypass of model state or group policy.', 'Token-compression level and Prompt Guard mode follow the credential. Prompt Guard defaults to log only and supports off, log, warn, or block.', 'Requests still pass credential status, binding, model range, body size, source IP, and concurrency checks.'],
    },
    {
      id: 'client-agent-issuance', title: 'How a Client automatically creates Agent runtime credentials',
      paragraphs: ['A Client credential may enable “Allow the Client to create runtime credentials for local Agents.” It is off by default and does not grant model:chat or mcp:* directly to the Client credential.'],
      bullets: ['The local Agent must first be discovered. Client registration creates its Client-owned runtime identity automatically.', 'The managed Agent is a credential identity and audit anchor; it does not mean the model must match the Agent type.', 'The Client credential may restrict the gateway models it can configure. This is not direct model-call permission for the Client.', 'Only a concrete model-switch task may retrieve the secret; plaintext never enters task payloads, list responses, or the desktop renderer.', 'The generated credential includes runtime:verify-signature, runtime:can-load, runtime:check-tool, and model:chat restricted to the selected model. It excludes runtime:govern. If the managed Agent already has MCP gateways, it preserves the three mcp:* call scopes and gateway allowlist.', 'Revoking or deleting the parent Client credential revokes active Agent credentials it generated.', 'Automatic writing currently supports Claude Code, Codex, and Hermes. Other Agents still require verified configuration and protocol adapters.'],
    },
    {
      id: 'composite-agent-runtime', title: 'Use one runtime credential for one Agent',
      paragraphs: ['One Agent runtime credential may combine runtime:*, model:chat, and mcp:* scopes, but it still represents only its bound Agent. Model and MCP gateway allowlists remain independently enforced.'],
      bullets: ['Model requests use the same Bearer credential and derive trusted Agent identity from bound_agent_id.', 'MCP requests use the same Bearer credential but can reach only allowed_mcp_gateways.', 'The Client access credential manages the host and task sync; it cannot call models or MCP. With delegated issuance enabled, the Client still installs a separate credential bound to the target Agent.', 'Non-Agent applications should keep model gateway or MCP gateway credentials instead of impersonating an Agent.'],
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

en.articles['agent-security-runtime'] = {
  eyebrow: 'Agent management',
  title: 'AI security scanning and unified runtime traces',
  summary: 'Configure Agent, MCP, LLM, and AI infrastructure security assessments, interpret cases and findings correctly, and correlate redacted model, Tool, governance, and retrieval evidence in unified traces.',
  sections: [
    {
      id: 'enabled-scope', title: 'Capabilities enabled now',
      paragraphs: ['Security Scanning and Runtime Traces are direct sidebar entries after Model Gateway and before System Management, enabled by default. No .env page flag is required. Executing scans still requires an administrator to create targets, policies, and an independent Worker; a visible page is not evidence that an external target passed acceptance.'],
      table: { columns: ['Capability', 'Current behavior', 'What it does not prove'], rows: [
        ['Scan pipeline self-check', 'Checks task dispatch, Worker leases, heartbeats, and result delivery', 'Does not replace dynamic scanning or establish target safety'],
        ['Agent risk scan', 'Sends test conversations to an authorized target within outbound, budget, timeout, and capability policy', 'It does not cover unexecuted scenarios or reproduce an unlimited attack chain'],
        ['Dify asset inventory', 'Collects app configuration, DSL, nodes, models, Tools, MCP, and knowledge references with source and verification status', 'Configuration does not prove execution; inferred intent is not a verified fact'],
        ['MCP risk scan', 'Reads the Gateway, Server, Tool descriptions, and Schema metadata frozen when the task was created', 'It does not execute tools/call or verify real Tool side effects'],
        ['LLM red team', 'Calls the target and an independent evaluator with a locked dataset or custom prompt, creating one case per prompt', 'A passed case means that attack did not observe a jailbreak; it does not prove absolute safety'],
        ['AI infrastructure scan', 'Actively visits explicitly authorized URLs, fingerprints components, and matches CVE rules to concrete versions', 'An open port or unknown version is neither a confirmed vulnerability nor proof of safety'],
        ['Unified runtime trace', 'Stores events actually published by the Agent SDK, Model Gateway, MCP Gateway, and Runtime Governance', 'Gateway-only traffic cannot establish a complete Agent Turn/Step trace'],
      ] },
      link: { path: '/agent-security/scans', label: 'Open Security Scanning' },
    },
    {
      id: 'scan-workflow', title: 'Run and review one security scan',
      steps: [
        { title: 'Create a target', body: 'Choose its type and environment, then declare allowed capabilities and connection settings. Private destinations require matching target and policy CIDR allowlists. TLS verification cannot be disabled.' },
        { title: 'Choose an execution policy', body: 'Confirm round, token, cost, response-size, concurrency, duration, lease, retry, and outbound boundaries. Read-only mode blocks write Tools at the server and records a governance event.' },
        { title: 'Choose a scan type', body: 'Agent scans and LLM red-team tasks need reachable targets and an evaluator. MCP analyzes a frozen snapshot only. AI infrastructure scans actively visit authorized URLs under HTTP, DNS, and dual-CIDR controls.' },
        { title: 'Observe the task instead of resubmitting', body: 'A task moves through pending, running, and a terminal state. Use refresh, cancel, or Kill Switch. Kill Switch prevents subsequent requests; in-flight calls end through target or evaluator timeouts.' },
        { title: 'Review the evidence chain', body: 'Read cases, findings, evidence, raw-artifact summary, engine version, coverage snapshot, and stop reason together. A Finding links to an event only when the server stored a valid trace_id and event_id pair.', expected: 'Every conclusion resolves to a case, event, or an explicit Unverified reason.' },
      ],
      link: { path: '/agent-security/scans', label: 'Open AI Security Scanning' },
    },
    {
      id: 'interpret-results', title: 'Interpret success, passed cases, and zero Findings correctly',
      bullets: ['Task succeeded means the execution contract completed; it does not mean the target is safe.', 'Case passed means that execution did not observe the risk. Blocked and error cases remain Unverified.', 'Zero Findings cannot be treated as safe without checking cases, coverage, engine, budgets, stop reason, and evidence completeness.', 'Resolved or not reproduced is valid only when both scans succeeded with equivalent engines and coverage.', 'Historical records missing a case, event, evidence, or rule version remain incomplete; the platform does not invent evidence retroactively.'],
      callout: { type: 'warning', title: 'Every scan conclusion has a boundary', body: 'Agent scans cover only executed rules and rounds; MCP covers frozen descriptions and Schemas; LLM red team covers executed prompts; infrastructure Findings require component, version, and CVE-rule evidence. Anything without sufficient evidence remains Unverified.' },
    },
    {
      id: 'worker-operations', title: 'Worker identity and runtime state',
      paragraphs: ['An administrator creates a Worker identity and stores its one-time Token, then injects it through the site Secret-management process. Worker Tokens and evaluator keys are runtime credentials, not page flags, and must not enter images, source, or normal logs.'],
      bullets: ['healthy proves only the Worker process and control-plane heartbeat/lease channel. It does not prove an external target passed scanning.', 'Tokens cannot be rotated in place. Create a new Worker, switch and verify heartbeat plus public-key fingerprint, then revoke the old identity.', 'After interruption, running tasks converge through lease expiry and retry policy. Exhausted retries fail explicitly instead of producing a false safe conclusion.', 'Production defaults use non-root, a read-only root filesystem, temporary storage, no extra capabilities, and resource limits. Tune only after tests in the target environment.'],
    },
    {
      id: 'trace-completeness', title: 'Read completeness from real event sources',
      table: { columns: ['Completeness', 'Observed sources', 'Missing context'], rows: [
        ['full', 'Agent SDK plus associated model, MCP, or governance events', 'It still represents only lifecycle events actually reported by the integration'],
        ['model_only', 'Model Gateway events only', 'No Agent Turn, Step, Tool, or retrieval context'],
        ['mcp_only', 'MCP Gateway events only', 'No model reasoning or Agent lifecycle'],
        ['gateway_partial', 'Multiple gateway event types without the Agent SDK layer', 'Cannot reconstruct complete conversational intent or Step boundaries'],
      ] },
      paragraphs: ['A custom Runtime should create the Trace with the Runtime Trace SDK and place the same trace_id, turn_id, step_id, call_id, and parent_call_id in model metadata and MCP params._meta. Ordinary model or MCP credentials cannot impersonate a registered Agent; trusted identity comes from the bound Agent runtime credential.'],
      link: { path: '/runtime-traces', label: 'Open Unified Runtime Traces' },
    },
    {
      id: 'privacy-evidence', title: 'Privacy boundaries for search, viewing, and export',
      bullets: ['Trace lists, conversation view, event details, and search use server-redacted projections and do not read raw prompts, responses, or Tool arguments.', 'Redacted JSON and PDF support ordinary review. PDF does not support raw classification.', 'Raw JSON is limited to administrators, super administrators, or privacy auditors after current-password verification creates a five-minute, one-use authorization. Every action is security-audited.', 'Security auditors see redacted content only. Raw payloads are encrypted separately; ordinary application logs contain IDs, stable error codes, and redacted summaries.'],
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
        { title: 'Search by keyword', body: 'Results refresh as you type a Skill, Agent, credential Actor, or event-detail keyword. Event and time filters apply immediately; filter changes return to page one.' },
        { title: 'Cross-check fields', body: 'The table shows time, event, object, Agent and source, and actor. Skill IDs appear below object names, and source IPs below Agents. Skill links open their details.' },
        { title: 'Expand evidence', body: 'Select View to expand the event ID and any recorded reason. Original JSON preserves every event field and value for troubleshooting by event ID, checking the source, or sharing evidence with technical support; routine review does not require opening it.' },
      ],
      image: { name: 'audit-trail', alt: 'Audit trail table with inline event details', caption: 'Example data: expand the recorded reason and event ID, then inspect the complete original JSON when needed.' },
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
  summary: 'Classify analyzer findings under the scan policy as Classify as malicious, Assess in context, or Retain as a notice, then combine severity, judgement mode, and optional LLM output into final risk.',
  sections: [
    {
      id: 'four-levels', title: 'Separate four layers first',
      paragraphs: ['Finding classification is neither final risk nor final state. Trace a result from individual evidence through classification and risk reconciliation to admission.'],
      table: { columns: ['Layer', 'Question answered', 'Example'], rows: [
        ['Finding and severity', 'What evidence did one analyzer observe?', 'A HIGH download-and-execute rule'],
        ['Finding classification', 'How does the scan policy configure this finding to affect risk?', 'Default settings assess supply-chain risk in context'],
        ['Final risk', 'Is the reconciled result benign, suspicious, or malicious?', 'Tool risk and the LLM conclusion reconcile to suspicious'],
        ['Skill state', 'Is the Skill approved, queued for review, or rejected?', 'APPROVED, VETTED, or REJECTED'],
      ] },
    },
    {
      id: 'classification-meaning', title: 'Classify as malicious, Assess in context, or Retain as a notice',
      table: { columns: ['Class', 'Meaning', 'Deterministic risk effect'], rows: [
        ['Classify as malicious', 'The scan policy assigns this finding directly to malicious risk', 'Any such finding produces malicious risk that LLM cannot lower'],
        ['Assess in context', 'The scan policy evaluates this finding using severity and judgement mode', 'Severity and strict, balanced, or permissive mode determine tool risk, as shown in the table below'],
        ['Retain as a notice', 'The scan policy retains this evidence without directly raising tool risk', 'Retained for explanation and troubleshooting but does not directly raise deterministic risk'],
      ] },
      callout: { type: 'note', title: 'Notices retain original evidence', body: 'The original rule, severity, file, and evidence remain in the report. Retain as a notice describes its contribution to tool risk; the final risk still incorporates other analysis results.' },
    },
    {
      id: 'default-mapping', title: 'Default finding classification',
      table: { columns: ['Default class', 'Risk items'], rows: [
        ['Assess in context', 'Data exfiltration; supply-chain risk; prompt injection; tool misuse; network access; credential access; dynamic execution; excessive permissions; dependency issues; runtime issues'],
        ['Retain as a notice', 'Documented external API examples'],
      ] },
      paragraphs: ['Administrators can move these items between classes under Policy Settings > Admission policy > Customize risk identification rules. The mapping is part of scan context. Existing reports are not rewritten; rescan to apply the new policy.'],
      link: { path: '/policy', label: 'Open Policy Settings' },
    },
    {
      id: 'classification-order', title: 'How one finding is classified',
      steps: [
        { title: 'Identify the risk item', body: 'Rule ID, category, file path, and evidence text are matched to data exfiltration, supply chain, prompt injection, and other configured items. Documented API examples are recognized first.' },
        { title: 'Apply the administrator mapping', body: 'When a configured risk item is recognized, the scan policy assigns it to Classify as malicious, Assess in context, or Retain as a notice.' },
        { title: 'Apply the security fallback', body: 'Unmapped download-and-execute, credential or data exfiltration, and governance-bypass rules are classified as malicious.' },
        { title: 'Retain runtime diagnostics as notices', body: 'Missing dependencies, runtime issues, and LOW or MEDIUM low-analyzability signals are retained as notices.' },
        { title: 'Fall back by severity', body: 'Other MEDIUM-or-higher findings use Assess in context; remaining lower findings use Retain as a notice.' },
      ],
    },
    {
      id: 'risk-reconciliation', title: 'How classes produce final risk',
      table: { columns: ['Finding state', 'Strict', 'Balanced', 'Permissive'], rows: [
        ['Any finding in Classify as malicious', 'malicious', 'malicious', 'malicious'],
        ['Highest severity in Assess in context is HIGH or above', 'malicious', 'suspicious', 'suspicious'],
        ['Highest severity in Assess in context is MEDIUM', 'suspicious', 'suspicious', 'benign'],
        ['Only notices or low-severity contextual findings', 'benign', 'benign', 'benign'],
      ] },
      paragraphs: ['The table shows tool risk before LLM reconciliation. When enabled, LLM may raise risk. In balanced or permissive mode, it may also lower tool risk when no findings are classified as malicious. Strict mode or findings classified as malicious retain the tool-risk floor. Decision trace explains whether the LLM conclusion was adopted and shows the recorded reason.'],
    },
    {
      id: 'admission-result', title: 'How final risk becomes a Skill state',
      bullets: ['A Skill declaration matching an explicitly denied permission produces REJECTED.', 'Risk disposition rules assign one action to each final risk: automatic rejection produces REJECTED, manual review produces VETTED, and automatic approval produces APPROVED with a signature.', 'Benign and suspicious risks support automatic approval. Approval preserves the original risk rating.', 'Risks without a configured action use the defaults: approve benign, review suspicious, and reject malicious.'],
      callout: { type: 'warning', title: 'Do not decide by finding count', body: 'One finding classified as malicious under the scan policy establishes malicious risk; notice counts do not directly raise tool risk. Risk classification and admission actions are configured separately. Review both.' },
      link: { path: '/docs/skill-policy', label: 'Continue to Skill policy settings' },
    },
  ],
}

en.articles['skill-policy'] = {
  eyebrow: 'Skill governance',
  title: 'Skill policy settings',
  summary: 'Set risk rules and admission actions, preview examples using current page settings, then save and rescan to verify real outcomes.',
  sections: [
    {
      id: 'effective-order', title: 'Where policy acts in the scan flow',
      steps: [
        { title: 'Decide whether a result can be reused', body: 'An existing report can be reused when both content and scan context match and reuse is enabled. Policy or analyzer changes alter scan context.' },
        { title: 'Run selected analyzers', body: 'Rules and deep scan establish interim severity. If interim risk matches a mandatory Sandbox level, the backend attempts an additional Sandbox run.' },
        { title: 'Classify and aggregate tool risk', body: 'Findings use Classify as malicious, Assess in context, or Retain as a notice; strict, balanced, or permissive mode produces pre-LLM risk.' },
        { title: 'Optionally run LLM assessment', body: 'The model runs after other evidence is available. Findings classified as malicious under the scan policy establish malicious risk, and strict mode also prevents the model from lowering tool risk.' },
        { title: 'Apply manifest constraints and admission', body: 'Tool and license rules create policy warnings or blocks, then final risk routes the Skill to APPROVED, VETTED, or REJECTED.' },
      ],
    },
    {
          "id": "page-layout",
          "title": "What the three settings areas control",
          "table": {
            "columns": [
              "Area",
              "Primary settings",
              "Recommended approach"
            ],
            "rows": [
              [
                "Admission policy",
                "Actions for scan conclusions, risk rules, company permissions and license requirements",
                "Read the summary, then adjust actions or expand custom rules"
              ],
              [
                "Detection settings",
                "AI and Sandbox availability; intermediate risks that require Sandbox",
                "Use Configure service to open service parameters"
              ],
              [
                "Advanced configuration",
                "Result reuse, AI model and content limits, Sandbox service and resources",
                "Configure during deployment or tuning, save, and verify with a rescan"
              ]
            ]
          },
          "link": {
            "path": "/policy",
            "label": "Open Policy Settings"
          },
          "image": {
            "name": "skill-policy",
            "alt": "What the three settings areas control",
            "caption": "Example configuration: admission actions and finding classifications are shown together."
          }
        },
    {
          "id": "decision-settings",
          "title": "Admission actions and risk rules",
          paragraphs: ['Choose the action for each risk level first. Expand Customize risk identification rules to change how findings affect risk. The summary reflects current edits; use Preview current policy to check the expected outcome before saving.'],
          "table": {
            "columns": [
              "Setting",
              "Current effect",
              "Important detail"
            ],
            "rows": [
              [
                "Risk disposition rules",
                "Choose an action for benign, suspicious, and malicious conclusions",
                "Benign and suspicious risks can be approved, reviewed, or rejected; malicious risks can be reviewed or rejected. Automatic approval preserves the suspicious risk rating"
              ],
              [
                "Use recommended actions",
                "Approve benign, review suspicious, reject malicious",
                "Check the policy summary before saving"
              ],
              [
                "Findings that affect risk",
                "Classify as malicious, Assess in context, or Retain as a notice",
                "Expand Customize risk identification rules to change how each behavior affects risk"
              ],
              [
                "Decision mode",
                "Strict, balanced, or permissive controls context-dependent findings",
                "AI cannot lower risk established by findings in Classify as malicious"
              ],
              [
                "Use recommended risk rules",
                "Restore recommended classifications and balanced mode",
                "Configured separately from admission actions"
              ]
            ]
          },
          "link": {
            "path": "/docs/risk-classification",
            "label": "Read classification and risk calculation"
          }
        },
    {
      id: 'policy-preview',
      title: 'Preview current policy: simulate a decision',
      paragraphs: ['Current policy decision preview uses the settings on this page, including unsaved changes. Manually supplied findings help explain and compare policy behavior. It reuses backend decision logic without running scans, calling models, saving policy, or creating Skills.'],
      steps: [
        { title: 'Open the preview dialog', body: 'On Admission policy, click Preview current policy in the upper right of Admission policy summary. Start with Dynamic execution + LLM: no apparent risk or Data exfiltration + LLM: no apparent risk to populate an example.' },
        { title: 'Set simulated analyzer results', body: 'Choose execution states for rule analysis, deep scan, and Sandbox, add finding types and severities as needed, then select the LLM risk conclusion. Completed with no findings differs from disabled, skipped, unavailable, or failed; missing conclusions do not establish safety. If banned permissions are configured, you can also simulate matching declarations.' },
        { title: 'Read risk, action, and the decision path', body: 'Changing inputs automatically recalculates the result. Compare final risk with admission action, then follow Classify findings → Aggregate tool risk → Reconcile LLM conclusion → Apply admission rules. A banned permission declaration causes rejection even when the risk disposition allows approval.' },
        { title: 'Compare policy settings', body: 'Changing decision mode in the dialog updates the policy draft on this page. Select Back to policy settings to adjust classifications or actions, then reopen the preview. Simulated inputs are retained for this page.' },
        { title: 'Save and verify a real Skill', body: 'Return to policy settings, check the summary and unsaved-changes notice, then select Save changes. Rescan the target version from the Skill list and inspect its actual outcome under Decision trace in Skill details.' },
      ],
      image: { name: 'skill-policy-simulator', alt: 'Current policy decision preview dialog with inputs and four decision steps', caption: 'Example configuration: balanced mode accepts the LLM’s no-apparent-risk conclusion for medium-severity dynamic execution. Risk and admission action are shown separately.' },
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
          "id": "analyzer-settings",
          "title": "Detection switches and service configuration",
          "bullets": [
            "Detection settings enables AI analysis and Sandbox, and selects intermediate risks that require Sandbox. Rule analysis always runs.",
            "Advanced configuration > AI analysis service selects the model, timeout, file count, and character limits. Add the model under Model Gateway > Model Management first. Select LLM analysis when submitting or rescanning.",
            "Advanced configuration > Sandbox service configures Docker or a remote service, network, resources, and timeout. Remote connections can be tested.",
            "Advanced configuration also controls reuse for identical content and scan context. An explicit rescan performs a new scan.",
            "Switches control availability; completed, skipped, unavailable, and failed in a report describe actual execution."
          ],
          "image": {
            "name": "skill-policy-detection",
            "alt": "Detection switches and service configuration",
            "caption": "Example configuration: analyzer switches and intermediate-risk conditions for Sandbox."
          }
        },
    {
          id: 'advanced-services',
          title: 'Configure models and service parameters',
          paragraphs: ['In Detection settings, select Configure service for the relevant capability to open advanced settings. Select a registered AI model and adjust timeout and content limits as needed. For Sandbox, choose local Docker or a remote service and configure resources; remote services support connection testing. Select Save changes, then submit or rescan to verify actual execution.'],
          image: { name: 'skill-policy-advanced', alt: 'Advanced configuration and AI analysis service', caption: 'Example configuration: model selection and scanning content limits are under Advanced configuration.' },
        },
        {
          "id": "current-boundaries",
          "title": "Admission and declaration-check boundaries",
          "paragraphs": [
            "Banned permissions take precedence over risk-based admission actions: a matching declaration causes rejection."
          ],
          "bullets": [
            "Company permission and license rules inspect SKILL.md declarations; they do not restrict actual runtime tool calls.",
            "Tool-count, tool-allowlist, and license checks produce advisory warnings; these alone do not cause rejection.",
            "Saved settings apply to later scans. Rescan existing Skills to apply the new policy to their reports and status."
          ]
        },
    {
          "id": "change-workflow",
          "title": "Change policy safely",
          "steps": [
            {
              "title": "State the intended change",
              "body": "Record which false positive should be reduced or which behavior should be blocked, and which Skills may be affected."
            },
            {
              "title": "Preview expected outcomes",
              "body": "Use Preview current policy to compare inputs expected to approve, require review, or reject. Check finding classifications, LLM reconciliation, and admission actions against the intended change."
            },
            {
              "title": "Save and rescan",
              "body": "Check the summary and unsaved state, save the configuration, and rescan the target version. Historical reports retain their original conclusions."
            },
            {
              "title": "Inspect the complete evidence chain",
              "body": "Use reports from representative Skills to verify finding classification, tool risk, LLM conclusions, and final risk, then inspect policy warnings and current admission status. Simulated inputs do not replace real detection."
            }
          ],
          "link": {
            "path": "/skills",
            "label": "Open Skill list and rescan"
          }
        },
  ],
}

for (const [locale, content] of [['zh-CN', zh], ['en-US', en]]) {
  Object.assign(content.articles, aidrGuides[locale])
  const aidrGroup = {
    title: locale === 'zh-CN' ? '运行审计与防护 · AIDR' : 'Runtime audit and protection · AIDR',
    items: aidrGuideOrder.map(slug => ({ slug, title: content.articles[slug].title, summary: content.articles[slug].summary })),
  }
  const agentGroupIndex = content.groups.findIndex(group => group.items.some(item => item.slug === 'audit-trail'))
  content.groups.splice(agentGroupIndex + 1, 0, aidrGroup)
  for (const slug of ['client-management', 'hook-integration', 'audit-trail']) {
    content.articles[slug].sections.unshift({
      id: 'aidr-operating-guides',
      title: locale === 'zh-CN' ? '客户端 AIDR 操作指南' : 'Client AIDR operating guides',
      paragraphs: [locale === 'zh-CN'
        ? '客户端运行审计包含 Agent 日志、插件 Hook 和系统事件三条独立通道。平台配置、客户端接入、会话证据、工具审批、Skill 认证和排障请查阅下列专题；自研 Agent 的同步验签示例与客户端后台审计应分别理解。'
        : 'Client runtime audit has three independent channels: Agent logs, plugin Hooks and system events. Use these guides for platform configuration, client setup, session evidence, tool approvals, Skill certification and troubleshooting. Synchronous verification in custom Agent examples differs from background client audit.'],
      table: {
        columns: locale === 'zh-CN' ? ['专题', '内容'] : ['Guide', 'Contents'],
        rows: aidrGroup.items.map(item => [{ path: `/docs/${item.slug}`, label: item.title }, item.summary]),
      },
    })
  }
  const guides = securityGuides[locale]
  Object.assign(content.articles, guides)
  const group = content.groups.find(group => group.items.some(item => item.slug === 'agent-security-runtime'))
  const index = group.items.findIndex(item => item.slug === 'agent-security-runtime')
  group.items.splice(index + 1, 0, ...Object.entries(guides).map(([slug, article]) => ({ slug, title: article.title, summary: article.summary })))
  content.articles['agent-security-runtime'].sections.unshift({
    id: 'detailed-guides',
    title: locale === 'zh-CN' ? '按操作查阅详细指南' : 'Detailed operating guides',
    paragraphs: [locale === 'zh-CN' ? '本页说明能力和证据边界。实际配置请按下列指南逐项操作，Dify 凭据获取、资产采集、定时同步和调用轨迹分别提供独立说明。' : 'This overview explains capability and evidence boundaries. Use the guides below for configuration, Dify credentials and inventory, scheduled synchronization, and trace inspection.'],
    table: {
      columns: locale === 'zh-CN' ? ['操作指南', '包含内容'] : ['Guide', 'Contents'],
      rows: Object.entries(guides).map(([slug, article]) => [{ path: `/docs/${slug}`, label: article.title }, article.summary]),
    },
  })

  const integrations = integrationGuides[locale]
  Object.assign(content.articles, integrations)

  const startGroup = content.groups.find(group => group.items.some(item => item.slug === 'quick-start'))
  const quickStartIndex = startGroup.items.findIndex(item => item.slug === 'quick-start')
  const scenarioArticle = integrations['scenario-selection']
  startGroup.items.splice(quickStartIndex + 1, 0, {
    slug: 'scenario-selection', title: scenarioArticle.title, summary: scenarioArticle.summary,
  })

  const modelGroup = content.groups.find(group => group.items.some(item => item.slug === 'model-gateway'))
  modelGroup.title = locale === 'zh-CN' ? '模型接入' : 'Model access'
  const modelIndex = modelGroup.items.findIndex(item => item.slug === 'model-gateway')
  const externalArticle = integrations['external-ai-gateway']
  modelGroup.items.splice(modelIndex + 1, 0, {
    slug: 'external-ai-gateway', title: externalArticle.title, summary: externalArticle.summary,
  })

  content.articles['agent-management'].sections.unshift({
    id: 'choose-product-path',
    title: locale === 'zh-CN' ? '先确认实际产品如何运行' : 'Start with the actual product runtime',
    paragraphs: [locale === 'zh-CN'
      ? '创建平台 Agent 只建立身份、能力和责任关系。Codex、Claude Code 等本地工具优先由客户端托管；自研 Runtime 直接接运行 API；Dify 通过独立 API 做资产和风险纳管。'
      : 'Creating a platform Agent establishes identity, capability, and ownership. Prefer the Client for local tools such as Codex and Claude Code, Runtime APIs for custom Agents, and dedicated APIs for Dify asset and risk governance.'],
    link: { path: '/docs/scenario-selection', label: locale === 'zh-CN' ? '按产品选择接入方案' : 'Choose an integration by product' },
  })

  const difyGuide = content.articles['dify-security-access']
  difyGuide.sections.unshift({
    id: 'governance-boundary',
    title: locale === 'zh-CN' ? '先明确 Dify 纳管边界' : 'Understand the Dify governance boundary first',
    paragraphs: [locale === 'zh-CN'
      ? 'Console/DSL 用于获取配置证据，App API 提供授权测试，Knowledge API 提供经授权的知识资产检查；只有 Runtime Trace 才能证明节点或 Tool 实际执行。'
      : 'Console/DSL provides configuration evidence, the App API supports authorized tests, and the Knowledge API supports authorized knowledge inspection. Only Runtime Trace can establish actual node or Tool execution.'],
    table: {
      columns: locale === 'zh-CN' ? ['目标', '使用方案'] : ['Goal', 'Use'],
      rows: locale === 'zh-CN'
        ? [['登记和盘点 Dify 应用', 'Dify 扫描目标 + Console API'], ['执行已发布应用安全测试', 'App API'], ['检查知识库内容风险', '明确授权 + 独立 Knowledge API'], ['观察真实运行', '调用轨迹 / Runtime Trace'], ['让 Dify 使用客户外部模型网关', '为该 Dify 应用创建外部 Agent Key，并配置到 Dify 模型供应商']]
        : [['Register and inventory a Dify app', 'Dify scan target + Console API'], ['Test a published app', 'App API'], ['Inspect knowledge-content risk', 'Explicit authorization + separate Knowledge API'], ['Observe actual execution', 'Runtime Trace'], ['Use a customer external AI gateway', 'Create an external Agent key for the Dify app and configure it in the Dify model provider']],
    },
    link: { path: '/docs/scenario-selection', label: locale === 'zh-CN' ? '比较其他产品的接入方式' : 'Compare other product integrations' },
  })
}

export const docsContent = { 'zh-CN': zh, 'en-US': en }

export const docsArticleOrder = [
  '',
  'quick-start',
  'scenario-selection',
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
  'hook-integration',
  'agent-security-runtime',
  'security-scan-guide',
  'dify-security-access',
  'security-operations',
  'runtime-trace-guide',
  'audit-trail',
  ...aidrGuideOrder,
  'model-gateway',
  'external-ai-gateway',
  'system-management',
  'docker-deployment',
  'performance-benchmark',
  'docker-operations',
  'case-expense-skill',
  'case-high-impact-skill',
  'case-malicious-skill',
  'case-runtime-tamper',
  'case-mcp-approval',
  'case-client-modular-governance',
  'case-model-privacy-compression',
  'faq',
]
