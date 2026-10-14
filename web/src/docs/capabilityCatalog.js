const item = (id, module, submodule, name, description, scenario, entry, boundary, docs) => ({
  id,
  module,
  submodule,
  name,
  description,
  scenario,
  entry,
  boundary,
  docs,
})

const zh = [
  item('skill-submit', 'skill', '提交与内容', '多入口导入', '支持 ZIP、本地目录、网络或 GitHub 地址、ClawHub 导入 Skill。', '接收研发团队或第三方交付的 Skill，并进入统一治理流程。', '能力治理 / 提交 Skill', '外部内容提交后仍需完成检测和准入，导入成功不代表可直接使用。', 'skill-governance'),
  item('skill-content', 'skill', '提交与内容', '安全解包与内容快照', '校验压缩包路径和文件边界，保存可追溯的待检测内容。', '阻止路径逃逸，并为后续扫描、审核和版本比较保留一致输入。', '提交 Skill', '文件大小、数量和压缩包边界受服务端限制。', 'skill-governance'),
  item('skill-analysis', 'skill', '检测与分析', '多分析器检测', '组合基础 Scanner、规则分析、深度扫描、可选 Sandbox 与 LLM 分析。', '按风险和策略选择检测手段，汇总各分析器的独立结果。', 'Skill 详情 / 重新检测', 'Sandbox 与 LLM 是辅助信号；最终风险由策略汇总决定。', 'scan-capabilities'),
  item('skill-classification', 'skill', '检测与分析', '风险项目归类', '将发现项归入阻断、结合上下文判断或仅保留提示。', '校准误报和真实风险对最终风险等级的影响。', '能力治理 / 风险项目归类', '归类影响后续汇总，但不能抹去原始证据。', 'risk-classification'),
  item('skill-version', 'skill', '版本与证据', '版本与内容指纹', '按内容指纹维护 Skill 版本族，并支持版本间文本差异查看。', '判断新提交是否改变实际内容，定位具体文件差异。', 'Skill 详情 / 版本', '二进制文件只记录清单和摘要，不提供文本差异。', 'skill-governance'),
  item('skill-review', 'skill', '审核与决策', '策略准入与人工审核', '根据风险、Manifest 阻断约束和准入策略自动批准、转人工或拒绝。', '让低风险版本自动流转，将需判断的版本集中交给审核人员。', '能力治理 / Skill 审核', '人工审核不能绕过策略定义的阻断约束。', 'skill-policy'),
  item('skill-sign', 'skill', '可信发布', '签名与运行验签', '对批准版本生成内容签名，Agent 加载前可校验状态、授权和本地内容。', '防止已批准 Skill 在落地后被替换或篡改。', 'Skill 详情 / Runtime API', '本地目录可写时应提交 skill_path 进行内容校验。', 'runtime-integration'),
  item('skill-report', 'skill', '报告与处置', '扫描报告与批量处置', '查看原始证据，导出 PDF 报告，并支持重检、取消和批量操作。', '集中复核检测结论并完成日常版本处置。', 'Skill 详情 / Skill 列表', '报告反映本次检测范围，不等同于绝对安全证明。', 'skill-governance'),

  item('agent-record', 'agent', 'Agent 管理', 'Agent 台账', '维护平台 Agent 身份、状态、归属和能力绑定。', '建立可授权、可追溯的 Agent 主体。', '智能体管理', '平台身份与客户端发现的运行实例应区分管理。', 'agent-management'),
  item('agent-skill-binding', 'agent', '授权关系', 'Skill 授权绑定', '将已准入 Skill 授权给指定 Agent。', '限制每个 Agent 能加载的 Skill 范围。', '智能体详情 / Skill 绑定', '授权只对已批准且可用的版本生效。', 'agent-management'),
  item('agent-credential', 'agent', '凭证管理', '最小权限运行凭证', '按 Agent 或调用主体签发限定范围、有效期和来源的凭证。', '让 Runtime、Hook 或 SDK 使用独立身份调用校验接口。', '统一凭证中心', '明文 Token 只在创建后展示一次，服务端保存哈希。', 'credential-management'),
  item('agent-runtime', 'agent', '运行控制', '运行时加载与 Tool 校验', '在 Skill 加载和 Tool 调用前核对 Agent、Skill、签名及授权关系。', '在执行入口阻断未授权或内容不一致的能力。', 'Runtime API', 'name-only 校验只适用于受 CI/CD 管控的只读目录。', 'runtime-integration'),
  item('agent-hook', 'agent', '外部接入', '客户端 AIDR 插件 Hook', '通过客户端策略管理插件、Hook 配置、后台接收与事件上报。', '接入现有 Agent 的宿主事件与工具策略。', '客户端管理 / 插件接入', '完成原生信任并验收真实事件；同步加载前验签另按开发者指南接入。', 'hook-integration'),
  item('agent-external-model', 'agent', '外部模型接入', '外部 AI 网关身份映射', '为 Agent 维护外部网关连接、API Key 映射和模型清单。', '让本地 Agent 在通过 Skill 校验后使用客户已有模型网关。', '外部 AI 网关', '模型流量不经过平台内置模型代理。', 'external-ai-gateway'),

  item('client-discovery', 'client', '发现与纳管', '本地 Agent 与目录发现', '客户端发现受支持 Agent、Skill 根目录和本地安装状态。', '盘点一台工作站上的多个 Agent 与 Skill 目录。', '客户端管理 / Agent Manager', '目录发现不等同于已纳管，需建立平台身份绑定。', 'client-management'),
  item('client-delivery', 'client', 'Skill 下发', '批量安装与进度', '一次下载后向多个已选择 Agent 安装同一批准版本，并展示逐目标进度。', '向一台多 Agent 主机分发统一版本。', '客户端管理 / Skill 安装', '目标目录和版本必须满足客户端授权与本地边界。', 'client-management'),
  item('client-inspection', 'client', '持续巡检', '已安装版本巡检', '比较本地内容、平台版本、签名和当前扫描状态。', '发现本地篡改、版本漂移或缺少批准记录。', '客户端管理 / 巡检', '目录可写时以实际内容签名为准。', 'client-management'),
  item('client-recovery', 'client', '恢复与隔离', '恢复、隔离和卸载', '对异常 Skill 执行恢复到批准版本、隔离或卸载任务。', '处理被篡改、撤销或不再允许使用的本地 Skill。', '客户端管理 / 任务', '恢复动作要求存在可验证的批准版本。', 'client-management'),
  item('client-connections', 'client', '连接管理', '多 Agent Manager 连接', '在桌面设置中保存并切换多个 Agent Manager 连接配置。', '让同一客户端在不同治理环境间安全切换。', 'Agent Manager 设置', '切换前验证目标连接；接口输出和日志不返回明文 Token。', 'client-management'),

  item('scanner-binary', 'scanner', '扫描器交付', 'Go 二进制扫描器', '提供单二进制扫描器，在客户主机指定目录发现并提交 Skill。', '无需在客户侧安装 Python、Node 或 Docker即可开展目录扫描。', '扫描器接入', '扫描器不在本地执行客户代码。', 'scanner-access'),
  item('scanner-discovery', 'scanner', '本地发现', 'Skill 目录发现', '递归发现包含 SKILL.md 的目录，并忽略版本库、依赖与构建产物。', '批量盘点服务器或工作站上的 Skill。', 'skill-scanner scan', '软链接和目录边界按安全打包规则处理。', 'scanner-access'),
  item('scanner-precheck', 'scanner', '本地预检', '静态风险预检', '检查大文件、危险扩展名和明显危险关键词。', '在上传前快速识别不适合打包的内容。', 'skill-scanner scan', '预检是轻量静态信号，不替代平台完整检测。', 'scanner-access'),
  item('scanner-fingerprint', 'scanner', '内容完整性', '文件清单与 SHA-256 指纹', '生成文件 Manifest 和内容指纹，服务端接收后重新计算并核对。', '证明客户端提交与平台实际扫描内容一致。', 'Scanner API', '客户端提供的指纹不能替代服务端复核。', 'scanner-access'),
  item('scanner-package', 'scanner', '安全打包', '上传包边界控制', '阻止路径逃逸和目录外软链接，并限制文件数、单文件和总大小。', '安全打包本地 Skill 目录用于远程检测。', 'skill-scanner scan', '超出限制的目录会在上传前终止。', 'scanner-access'),
  item('scanner-token', 'scanner', '访问控制', 'Scanner Token 管理', '支持一次展示、哈希存储、禁用、吊销、过期、IP、上传大小和并发限制。', '为客户主机或自动化扫描任务签发独立最小权限身份。', '扫描器接入 / Token', '最小权限仅包含提交扫描和读取自身结果、会话。', 'scanner-access'),

  item('security-target', 'security', '目标与资产', '授权目标登记', '登记 Agent、MCP、大模型、Dify 应用或 AI 基础设施目标及环境。', '明确每次安全评估的真实对象和授权边界。', '安全扫描 / 目标', '目标可见不代表凭据、Worker 或现场授权已经可用。', 'security-scan-guide'),
  item('security-policy', 'security', '策略与审批', '扫描策略、预算与预览', '配置执行模式、能力范围、预算、重试和生产审批，并在启动前预览。', '在调用目标前确认测试范围和成本上限。', '安全扫描 / 策略', '生产主动扫描受审批与执行模式约束。', 'security-scan-guide'),
  item('security-agent', 'security', '扫描类型', 'Agent 动态风险扫描', '针对授权 Agent 执行受控动态安全测试并保留证据。', '验证 Agent 在具体输入和运行路径下的风险信号。', '安全扫描 / 新建任务', '结果只覆盖实际执行的测试，不证明其他输入安全。', 'agent-security-runtime'),
  item('security-mcp', 'security', '扫描类型', 'MCP 风险扫描', '支持 MCP 元数据、源码、动态与红队相关扫描能力。', '识别 Tool 描述、Schema、执行和策略中的风险。', '安全扫描 / MCP', '元数据扫描不执行 Tool，动态能力取决于目标授权。', 'agent-security-runtime'),
  item('security-llm', 'security', '扫描类型', '大模型红队测试', '使用内置或自定义测试集、抽样和随机种子执行红队 Prompt。', '评估目标模型在本次测试中的越狱和安全风险信号。', '安全扫描 / 大模型', '单次未检出不代表模型在其他输入中安全。', 'agent-security-runtime'),
  item('security-infra', 'security', '扫描类型', 'AI 基础设施漏洞扫描', '识别组件指纹并在版本可确认时关联 CVE。', '盘点 AI 服务基础设施的已知漏洞风险。', '安全扫描 / 基础设施', '无法确认组件或版本时保持证据不足，不生成确定漏洞。', 'agent-security-runtime'),
  item('security-results', 'security', '结果与处置', 'Finding、报告与版本对比', '保存测试用例、Finding、证据和处置状态，支持报告与同条件版本比较。', '复核风险、记录误报或接受风险，并跟踪修复复测。', '安全扫描 / 报告', '只有覆盖和引擎条件可比时才能判断本次未复现。', 'security-operations'),
  item('security-schedule', 'security', '持续运行', '定时计划与资产同步', '按固定间隔、每日、每周或 Cron 执行扫描，并跟踪来源同步。', '持续发现资产变化并执行周期性安全评估。', '安全扫描 / 定时计划', '计划运行仍受目标状态、凭据、Worker 和审批条件约束。', 'security-operations'),

  item('mcp-server', 'mcp', 'Server 管理', 'MCP Server 登记与 Tool 发现', '登记远程 Server，执行 tools/list 并保存 Tool Schema 快照。', '建立可治理的 MCP 服务与 Tool 清单。', 'MCP 治理 / Server', '当前远程接入以支持的 MCP 传输协议为准。', 'mcp-governance'),
  item('mcp-gateway', 'mcp', 'Gateway 管理', '虚拟 MCP Gateway', '从多个 Server 选择 Tool 并发布统一 Gateway 地址。', '只向指定调用方暴露获准 Tool。', 'MCP 治理 / Gateway', '未发布或被策略禁用的 Tool 不应从 Gateway 暴露。', 'mcp-governance'),
  item('mcp-policy', 'mcp', 'Tool 策略', '暴露、读写与资源限制', '配置 Tool 暴露状态、读写属性、生产禁用清单、速率、并发和响应大小。', '限制高影响 Tool 和资源消耗。', 'MCP 治理 / 策略', '前端提示不能替代 Gateway 运行时强制执行。', 'mcp-governance'),
  item('mcp-credential', 'mcp', '凭证管理', 'MCP 调用凭证', '限制凭证可访问的 Gateway、来源 IP、请求大小和并发数。', '为不同 MCP Client 建立独立访问边界。', '统一凭证中心', '明文密钥只在创建后展示一次。', 'credential-management'),
  item('mcp-approval', 'mcp', '高风险调用', '调用审批与限时授权', '对高风险 Tool 调用提交脱敏参数审批，批准后签发限时匹配许可。', '在执行写操作或高影响操作前取得人工确认。', 'MCP 治理 / 审批', '许可绑定凭证、Gateway、Tool 和 Schema，超时或不匹配即失效。', 'mcp-governance'),
  item('mcp-debug', 'mcp', '排错与审计', 'MCP 调试与操作审计', '查看 Tool 发现、调用结果、原始 JSON 历史及 Server、Gateway、审批操作记录。', '排查连接和 Schema 问题，并追踪高风险调用。', 'MCP 调试 / MCP 审计', '原始数据查看受权限与审计约束。', 'mcp-governance'),

  item('model-provider', 'model', '供应商与模型', '多协议模型接入', '管理 OpenAI Chat Completions、Responses 和 Anthropic Messages 兼容供应商及模型。', '将不同上游模型统一接入平台。', '模型网关 / 供应商', '供应商启用不等于全部模型已登记或测试成功。', 'model-gateway'),
  item('model-key', 'model', '访问控制', 'LLM API Key 与模型范围', '为调用方签发限定模型、状态、有效期、请求大小和并发的 API Key。', '让应用以最小权限调用模型网关。', '统一凭证中心 / LLM API Key', '明文 Key 只展示一次，运行时持续检查状态和范围。', 'model-gateway'),
  item('model-privacy', 'model', '隐私防护', 'PII 识别与伪匿名化', '按隐私策略识别敏感字段并在请求上游前替换。', '降低 Prompt 中个人信息直接发送给模型供应商的风险。', '模型网关 / 隐私策略', '识别能力受策略、字段和文本类型限制。', 'model-gateway'),
  item('model-guard', 'model', 'Prompt 防护', 'Prompt Guard', '根据规则检查模型输入，并对命中内容执行阻断或记录。', '在模型调用前处理已定义的提示词风险。', '模型网关 / Prompt 防护', '规则信号不能替代对业务上下文的完整安全判断。', 'model-gateway'),
  item('model-compression', 'model', '上下文处理', 'Token 压缩', '在隐私处理后按策略压缩上下文，并记录压缩前后用量。', '降低长对话调用成本并保留必要上下文。', '模型网关 / Token 压缩', '效果取决于输入结构、策略和所选模型限制。', 'model-gateway'),
  item('model-trace', 'model', '用量与证据', '模型用量、Pipeline Trace 与 Runtime Trace', '记录模型调用关联信息、隐私处理阶段、用量和统一运行轨迹。', '分析调用成本，定位隐私链路和 Agent 运行事件。', '模型统计 / 隐私链路 / 调用轨迹', '原始 Payload 仅限特权角色经授权查看；普通日志不保存原始 Prompt。', 'runtime-trace-guide'),

  item('system-user', 'system', '身份权限', '账号、角色、菜单与用户组', '管理登录账号、角色权限、导航菜单和业务用户组。', '按职责控制管理台页面和操作权限。', '系统管理', '页面可见性与后端接口权限需要同时生效。', 'system-management'),
  item('system-branding', 'system', '系统配置', '品牌与系统设置', '维护中英文系统名称、企业信息、Logo 和运行配置。', '将管理台和帮助文档适配组织品牌。', '系统总览', '敏感配置不得通过普通接口或日志回显。', 'system-management'),
  item('system-docs', 'system', '帮助文档', '帮助中心与文档助手', '提供双语独立帮助中心、文档检索和基于当前文档片段的 AI 问答。', '帮助用户查找功能、操作步骤和故障入口。', '帮助文档 / 文档设置', 'AI 回答以当前文档和实际系统配置为准。', 'system-management'),
  item('system-audit', 'system', '审计', '登录、操作与安全审计', '记录登录、配置变更、关键治理操作和安全事件。', '按主体、资源和事件类型追踪管理行为。', '系统审计', '原始敏感内容受单独权限控制。', 'audit-trail'),
  item('system-export', 'system', '文档交付', '帮助文档与功能清单导出', '按选择范围导出整本帮助文档 PDF 或产品功能清单 Excel。', '生成客户交付、内部培训和产品范围确认材料。', '文档设置', '导出内容来自当前版本的内置文档和能力目录。', 'system-management'),

  item('deploy-compose', 'operations', '部署', 'Docker Compose 部署', '使用同一套 Compose 服务完成在线或离线镜像方式部署。', '在支持 Docker 的服务器启动平台。', '部署文档', '当前用户文档只覆盖 Docker Compose 部署路径。', 'docker-deployment'),
  item('deploy-health', 'operations', '运行检查', '健康检查与服务状态', '检查前端、Backend、Sandbox、Nginx 和持久化依赖状态。', '确认部署完成后各服务可访问且运行正常。', 'Docker 运维', '页面可访问不能替代所有后台服务和架构状态检查。', 'docker-operations'),
  item('deploy-backup', 'operations', '数据保护', '备份、恢复与升级回滚', '备份持久化卷和配置，按步骤执行升级、恢复或回滚。', '在版本变更和故障处理前保护业务数据。', 'Docker 运维', '删除卷属于破坏性操作，必须先完成可验证备份。', 'docker-operations'),
  item('deploy-capacity', 'operations', '容量规划', '性能与容量基线', '提供隔离环境下的并发、Skill 容量和客户端开销测试说明。', '为现场资源规划和验收准备测试口径。', '性能与容量', '隔离环境结果不能直接替代客户现场容量验证。', 'performance-benchmark'),
]

zh.push(
  item('aidr-channels', 'client', 'AIDR 接入', '三通道运行审计', '组合 Agent 原生日志、插件 Hook 和系统事件，并分别报告配置与运行状态。', '按会话语义、宿主调用和操作系统证据选择采集方式。', '客户端管理 / 设备详情 / 行为审计 / 采集状态', '产品、入口和系统支持范围分别核对；日志采集不能阻断。', 'aidr-overview'),
  item('aidr-sessions', 'client', 'AIDR 会话', '会话活动与多源证据', '按会话和轮次查看输入、回复、工具、Hook、Skill 行为及关联系统证据。', '复盘 Agent 操作并区分意图、宿主结果和 OS 事实。', '客户端管理 / 设备详情 / 行为审计 / 会话活动', '未关联事件保留未知；正文需要单独权限与采集授权。', 'aidr-platform'),
  item('aidr-desktop', 'client', 'AIDR 接入', '客户端接入工作台', '按产品管理日志来源、Hook 安装与信任，以及系统目标和权限。', '在工作站核对接入条件、运行诊断和上传状态。', '桌面客户端 / Agent 运行治理 / 接入与采集、系统采集', '安装、运行和平台接收分别验收；系统采集受原生发行条件限制。', 'aidr-client'),
  item('aidr-control', 'client', 'AIDR 防护', '工具规则、审批与独立控制模式', '为 Hook 与系统通道分别配置审计或拦截，管理工具规则与调用审批。', '对受支持的前置事件执行允许、拒绝或审批。', '客户端管理 / 设备详情 / 策略与审批', '实际控制依赖有效策略、宿主映射和原生能力；批准不等于执行成功。', 'aidr-policies'),
  item('aidr-content', 'client', 'AIDR 数据', '采集范围、脱敏与保留期', '管理正文范围、字节上限、脱敏和审计历史保留，并核对设备回执。', '平衡审计可读性、数据暴露和存储成本。', '客户端策略 / 内容与脱敏', '新策略不补回未采集或已清理的正文。', 'aidr-policies'),
  item('aidr-skill', 'client', 'AIDR Skill', 'Skill 使用认证与告警', '后台观察内容摘要，核对注册、批准、撤销、版本与授权；分别展示认证和操作结果。', '发现实际使用中的内容变化与授权问题。', '客户端管理 / 设备详情 / 行为审计 / 会话活动 / Skill 行为', '异步观察不是加载瞬间证明；路径、身份或内容不足时待确认。', 'aidr-skill-audit'),
  item('aidr-diagnostics', 'client', 'AIDR 运维', '采集诊断与链路验收', '结合策略版本、任务回执、来源发现、队列、ACK 和原因码定位问题。', '排查无事件、未生效、错误关联、性能和平台不可达。', '客户端管理 / 设备详情 / 行为审计 / 采集状态', '客户端在线或任务成功不能替代会话证据与端到端验收。', 'aidr-troubleshooting'),
)

const enCopy = {
  'aidr-channels': ['AIDR integration', 'Three-channel runtime audit', 'Combine native Agent logs, plugin Hooks and system events with separate target and runtime states.', 'Choose channels for conversation semantics, host calls and OS evidence.', 'Client management / Client details / Behavior audit / Collection status', 'Check support per product, entry and OS; log collection cannot block.'],
  'aidr-sessions': ['AIDR sessions', 'Session activity and source evidence', 'Inspect input, replies, tools, Hooks, Skill use and attributed system evidence by session and turn.', 'Distinguish intent, host-reported outcomes and OS facts.', 'Client management / Client details / Behavior audit / Session activity', 'Unassigned events remain unknown; content needs separate permission and capture authorization.'],
  'aidr-desktop': ['AIDR integration', 'Client integration workbench', 'Manage log sources, Hook installation and trust, system targets and permissions by product.', 'Check workstation prerequisites, runtime diagnostics and upload state.', 'Desktop / Agent Runtime Governance / Integration and collection, System collection', 'Verify installation, runtime and delivery separately; OS collection has native distribution requirements.'],
  'aidr-control': ['AIDR protection', 'Tool rules, approvals and channel modes', 'Configure audit or intercept independently for Hooks and system collection, with tool rules and approvals.', 'Allow, deny or request approval at supported pre-execution points.', 'Client management / Client details / Policies and approvals', 'Control requires effective policy, host mappings and native support; approval does not prove execution.'],
  'aidr-content': ['AIDR data', 'Capture scope, redaction and retention', 'Manage content scope, byte limits, redaction and history retention, then check device receipts.', 'Balance useful evidence, data exposure and storage cost.', 'Client policies / Content & redaction', 'New settings cannot restore uncaptured or deleted content.'],
  'aidr-skill': ['AIDR Skills', 'Skill-use certification and alerts', 'Observe digests in the background and check registration, approval, revocation, version and authorization; separate certification from outcomes.', 'Detect content drift and authorization issues during use.', 'Client management / Client details / Behavior audit / Session activity / Skill activity', 'Asynchronous observation is not load-time attestation; insufficient path, identity or content evidence stays pending.'],
  'aidr-diagnostics': ['AIDR operations', 'Collection diagnostics and acceptance', 'Use policy versions, task receipts, discovery, queues, ACKs and reason codes to diagnose issues.', 'Investigate missing events, unapplied policy, correlation, latency and platform outages.', 'Client management / Client details / Behavior audit / Collection status', 'Online status or task completion cannot replace session evidence and end-to-end acceptance.'],
  'skill-submit': ['Submission and content', 'Multi-source import', 'Import Skills from ZIP files, local folders, web or GitHub URLs, and ClawHub.', 'Bring internally developed or third-party Skills into one governance workflow.', 'Capability governance / Submit Skill', 'Imported content must still pass scanning and admission before use.'],
  'skill-content': ['Submission and content', 'Safe extraction and content snapshot', 'Validate archive paths and file boundaries and retain the exact submitted content.', 'Prevent path traversal and preserve consistent input for scanning and review.', 'Submit Skill', 'Server-side file-count, size, and archive limits apply.'],
  'skill-analysis': ['Scanning and analysis', 'Multi-analyzer scanning', 'Combine the base Scanner, rules, deep scan, optional Sandbox, and LLM analysis.', 'Choose analyzers by risk and policy while preserving each result.', 'Skill details / Rescan', 'Sandbox and LLM are supporting signals; policy reconciliation determines final risk.'],
  'skill-classification': ['Scanning and analysis', 'Finding classification', 'Classify findings as blocking, context-dependent, or informational.', 'Calibrate how false positives and confirmed signals affect final risk.', 'Capability governance / Finding classification', 'Classification does not remove the original evidence.'],
  'skill-version': ['Versions and evidence', 'Versions and content fingerprints', 'Maintain version families by content fingerprint and compare readable text files.', 'Identify whether a submission changed and locate exact file differences.', 'Skill details / Versions', 'Binary files expose inventory and digest rather than text diffs.'],
  'skill-review': ['Review and decision', 'Policy admission and human review', 'Approve, queue, or reject a version using risk, manifest constraints, and admission policy.', 'Automate low-risk flow and centralize cases that need human judgement.', 'Capability governance / Skill review', 'Human review cannot bypass policy-defined blocking constraints.'],
  'skill-sign': ['Trusted release', 'Signing and runtime verification', 'Sign approved content and verify status, authorization, and local content before loading.', 'Block replacement or tampering after approval.', 'Skill details / Runtime API', 'Writable local directories should be verified with skill_path.'],
  'skill-report': ['Reporting and action', 'Reports and batch actions', 'Review raw evidence, export scan PDFs, rescan, cancel, and run batch actions.', 'Complete day-to-day review and version handling in one place.', 'Skill details / Skill list', 'A report reflects the tested scope and is not proof of absolute safety.'],
  'agent-record': ['Agent management', 'Agent inventory', 'Maintain platform Agent identity, status, ownership, and capability bindings.', 'Create an Agent principal that can be authorized and audited.', 'Agent management', 'Platform identities and client-discovered runtime instances remain distinct.'],
  'agent-skill-binding': ['Authorization', 'Skill authorization binding', 'Authorize admitted Skills for a specific Agent.', 'Limit which Skills each Agent can load.', 'Agent details / Skill bindings', 'Bindings apply only to approved and available versions.'],
  'agent-credential': ['Credentials', 'Least-privilege runtime credentials', 'Issue credentials with bounded scope, expiry, and source restrictions.', 'Give Runtime, Hook, or SDK integrations an independent identity.', 'Credential center', 'Plaintext tokens are shown once; the server stores only hashes.'],
  'agent-runtime': ['Runtime controls', 'Load and Tool authorization', 'Verify Agent, Skill, signature, and binding before load or Tool use.', 'Block unauthorized or content-mismatched capabilities at execution entry points.', 'Runtime API', 'Name-only checks are appropriate only for CI/CD-controlled read-only directories.'],
  'agent-hook': ['External integration', 'Client AIDR plugin Hooks', 'Use Client policy to manage plugins, Hook configuration, background reception and event upload.', 'Connect host events and tool policies for existing Agents.', 'Client management / Plugin integration', 'Complete native trust and verify actual events. Follow the developer guide separately for synchronous pre-load verification.'],
  'agent-external-model': ['External model access', 'External AI gateway identity mapping', 'Maintain gateway connections, API-key mappings, and model catalogs for Agents.', 'Let local Agents use an existing customer gateway after Skill verification.', 'External AI gateways', 'Model traffic does not pass through the built-in model proxy.'],
  'client-discovery': ['Discovery and governance', 'Local Agent and directory discovery', 'Discover supported Agents, Skill roots, and local installation state.', 'Inventory multiple Agents and Skill directories on one workstation.', 'Client management / Agent Manager', 'Discovery alone does not establish a managed platform binding.'],
  'client-delivery': ['Skill delivery', 'Batch installation and progress', 'Download once and install an approved version to multiple selected Agents with per-target progress.', 'Distribute one governed version across a multi-Agent host.', 'Client management / Skill install', 'Target directories and versions must satisfy client authorization boundaries.'],
  'client-inspection': ['Continuous inspection', 'Installed-version inspection', 'Compare local content, platform version, signature, and current scan state.', 'Detect tampering, version drift, or missing approval evidence.', 'Client management / Inspection', 'Writable directories are evaluated from their actual content signature.'],
  'client-recovery': ['Recovery and isolation', 'Recover, isolate, and uninstall', 'Restore an approved version, isolate an abnormal Skill, or uninstall it.', 'Handle tampered, revoked, or disallowed local Skills.', 'Client management / Tasks', 'Recovery requires an available verifiable approved version.'],
  'client-connections': ['Connection management', 'Multiple Agent Manager profiles', 'Save and switch multiple Agent Manager connection profiles in desktop settings.', 'Move one client between governance environments safely.', 'Agent Manager settings', 'The target is validated before switching; APIs and logs omit plaintext tokens.'],
  'scanner-binary': ['Scanner delivery', 'Standalone Go scanner', 'Provide one binary that discovers and submits Skills from customer-host directories.', 'Scan directories without installing Python, Node, or Docker at the customer site.', 'Scanner access', 'The scanner does not execute customer code locally.'],
  'scanner-discovery': ['Local discovery', 'Skill directory discovery', 'Recursively find directories containing SKILL.md while ignoring repositories, dependencies, and builds.', 'Inventory Skills across a server or workstation.', 'skill-scanner scan', 'Symlinks and root boundaries follow safe packaging rules.'],
  'scanner-precheck': ['Local precheck', 'Static risk precheck', 'Check large files, dangerous extensions, and obvious risky keywords.', 'Reject unsuitable content before upload.', 'skill-scanner scan', 'The lightweight precheck does not replace full platform scanning.'],
  'scanner-fingerprint': ['Content integrity', 'Manifest and SHA-256 fingerprint', 'Generate a file manifest and fingerprint for server-side recomputation and comparison.', 'Show that uploaded and scanned content match.', 'Scanner API', 'Client-provided fingerprints never replace server verification.'],
  'scanner-package': ['Safe packaging', 'Upload package boundaries', 'Block path traversal and out-of-root symlinks and limit files and package size.', 'Package local Skill directories safely for remote scanning.', 'skill-scanner scan', 'The scanner stops before upload when limits are exceeded.'],
  'scanner-token': ['Access control', 'Scanner Token management', 'Support one-time display, hashing, disable, revoke, expiry, IP, size, and concurrency limits.', 'Issue independent least-privilege identities to customer hosts.', 'Scanner access / Tokens', 'Minimum scope is submit plus read-own results and sessions.'],
  'security-target': ['Targets and assets', 'Authorized target registration', 'Register Agent, MCP, model, Dify, or AI-infrastructure targets and environments.', 'Define the real assessment target and authorization boundary.', 'Security scans / Targets', 'A visible target does not prove credentials, Workers, or site authorization are available.'],
  'security-policy': ['Policy and approval', 'Scan policy, budget, and preview', 'Configure mode, capabilities, budgets, retries, and production approval and preview before launch.', 'Confirm scope and cost before calling a target.', 'Security scans / Policy', 'Production active scans remain subject to approval and execution-mode restrictions.'],
  'security-agent': ['Scan types', 'Agent dynamic risk scan', 'Run controlled dynamic security tests against an authorized Agent and retain evidence.', 'Evaluate risk signals on specific inputs and runtime paths.', 'Security scans / New task', 'Results cover only executed tests and do not prove safety for other inputs.'],
  'security-mcp': ['Scan types', 'MCP risk scanning', 'Support MCP metadata, source, dynamic, and red-team related scanning.', 'Find risk signals in Tool descriptions, schemas, execution, and policy.', 'Security scans / MCP', 'Metadata scans do not execute Tools; dynamic coverage depends on authorization.'],
  'security-llm': ['Scan types', 'Model red-team testing', 'Run red-team prompts with built-in or custom datasets, sampling, and deterministic seeds.', 'Assess jailbreak and safety signals observed in this run.', 'Security scans / Models', 'No finding in one run does not establish safety for other inputs.'],
  'security-infra': ['Scan types', 'AI infrastructure vulnerability scan', 'Identify component fingerprints and link CVEs only when versions are confirmed.', 'Inventory known vulnerability risk in AI infrastructure.', 'Security scans / Infrastructure', 'Unknown components or versions remain insufficient evidence.'],
  'security-results': ['Results and disposition', 'Findings, reports, and comparison', 'Store test cases, findings, evidence, status, reports, and comparable-version results.', 'Review risk, record disposition, and track remediation retests.', 'Security scans / Reports', 'A historical risk is not reproduced only when coverage and engine conditions are comparable.'],
  'security-schedule': ['Continuous operation', 'Schedules and asset sync', 'Run fixed-interval, daily, weekly, or Cron scans and track source synchronization.', 'Continuously discover changes and execute periodic assessments.', 'Security scans / Schedules', 'Runs still depend on target state, credentials, Workers, and approval.'],
  'mcp-server': ['Server management', 'MCP Server registration and Tool discovery', 'Register remote Servers, call tools/list, and save Tool-schema snapshots.', 'Create a governable inventory of MCP services and Tools.', 'MCP governance / Servers', 'Remote access follows the supported MCP transports.'],
  'mcp-gateway': ['Gateway management', 'Virtual MCP Gateway', 'Select Tools across Servers and publish one Gateway address.', 'Expose only approved Tools to selected callers.', 'MCP governance / Gateways', 'Unpublished or policy-disabled Tools must remain unavailable.'],
  'mcp-policy': ['Tool policy', 'Exposure, write risk, and resource limits', 'Configure exposure, read/write properties, production denylist, rate, concurrency, and response size.', 'Constrain high-impact Tools and resource use.', 'MCP governance / Policy', 'UI hints do not replace Gateway runtime enforcement.'],
  'mcp-credential': ['Credentials', 'MCP access credentials', 'Restrict accessible Gateways, source IPs, request size, and concurrency.', 'Give each MCP Client an independent access boundary.', 'Credential center', 'Plaintext keys are shown only once.'],
  'mcp-approval': ['High-risk calls', 'Approval and time-limited authorization', 'Submit redacted arguments for approval and issue a scoped, expiring permission when approved.', 'Require human confirmation before high-impact or write actions.', 'MCP governance / Approvals', 'Permissions bind credential, Gateway, Tool, and schema and expire on mismatch or timeout.'],
  'mcp-debug': ['Troubleshooting and audit', 'MCP debug and operation audit', 'Inspect discovery, call results, raw JSON history, and Server, Gateway, and approval events.', 'Troubleshoot connectivity and schemas and trace high-risk calls.', 'MCP Debug / MCP Audit', 'Raw data access is permission-controlled and audited.'],
  'model-provider': ['Providers and models', 'Multi-protocol model access', 'Manage providers and models compatible with OpenAI Chat Completions, Responses, and Anthropic Messages.', 'Connect different upstream models through one platform.', 'Model gateway / Providers', 'An enabled provider does not mean every model is registered or tested.'],
  'model-key': ['Access control', 'LLM API Key and model scope', 'Issue API keys constrained by model, status, expiry, request size, and concurrency.', 'Give applications least-privilege model access.', 'Credential center / LLM API Keys', 'Plaintext keys are shown once and runtime checks remain active.'],
  'model-privacy': ['Privacy', 'PII detection and pseudonymization', 'Detect configured sensitive fields and replace them before an upstream request.', 'Reduce direct disclosure of personal data in prompts.', 'Model gateway / Privacy policies', 'Coverage depends on policy, field, and text-type support.'],
  'model-guard': ['Prompt protection', 'Prompt Guard', 'Evaluate model input with configured rules and block or record matches.', 'Handle known prompt risks before inference.', 'Model gateway / Prompt Guard', 'Rule signals do not replace complete business-context review.'],
  'model-compression': ['Context processing', 'Token compression', 'Compress context after privacy processing and record token usage before and after.', 'Reduce long-conversation cost while retaining needed context.', 'Model gateway / Token compression', 'Results depend on input structure, policy, and model limits.'],
  'model-trace': ['Usage and evidence', 'Usage, Pipeline Trace, and Runtime Trace', 'Record correlation data, privacy stages, usage, and unified runtime events.', 'Analyze cost and locate privacy-pipeline and Agent-runtime events.', 'Model statistics / Pipeline Trace / Runtime Traces', 'Raw payloads require privileged authorization and never enter ordinary logs.'],
  'system-user': ['Identity and permission', 'Accounts, roles, menus, and groups', 'Manage login accounts, role permissions, navigation, and business groups.', 'Control console pages and actions by responsibility.', 'System administration', 'Page visibility and backend authorization must both apply.'],
  'system-branding': ['System settings', 'Branding and system settings', 'Maintain bilingual product names, company information, logo, and runtime settings.', 'Adapt the console and help center to an organization.', 'System overview', 'Sensitive settings must not be exposed by ordinary APIs or logs.'],
  'system-docs': ['Help documentation', 'Help center and Docs Assistant', 'Provide a bilingual standalone help center, search, and AI answers grounded in current excerpts.', 'Help users find features, steps, and troubleshooting entry points.', 'Help docs / Documentation settings', 'AI answers remain subordinate to the current docs and actual configuration.'],
  'system-audit': ['Audit', 'Login, operation, and security audit', 'Record login, configuration, governance operations, and security events.', 'Trace administrative behavior by principal, resource, and event type.', 'System audit', 'Raw sensitive content has separate access control.'],
  'system-export': ['Documentation delivery', 'Help and feature-list export', 'Export selected help articles to PDF or product capabilities to Excel.', 'Prepare customer delivery, training, and scope-confirmation materials.', 'Documentation settings', 'Exports use the built-in documentation and capability catalog in this release.'],
  'deploy-compose': ['Deployment', 'Docker Compose deployment', 'Deploy the same Compose services using online or offline image acquisition.', 'Start the platform on a Docker-capable server.', 'Deployment guide', 'User-facing documentation covers Docker Compose only.'],
  'deploy-health': ['Runtime checks', 'Health and service status', 'Check frontend, Backend, Sandbox, Nginx, and persistent dependencies.', 'Confirm all services are reachable and healthy after deployment.', 'Docker operations', 'A reachable page alone does not prove every backend service is healthy.'],
  'deploy-backup': ['Data protection', 'Backup, restore, upgrade, and rollback', 'Protect persistent volumes and configuration before upgrade, restore, or rollback.', 'Preserve business data through version changes and incident recovery.', 'Docker operations', 'Volume deletion is destructive and requires a verified backup first.'],
  'deploy-capacity': ['Capacity planning', 'Performance and capacity baseline', 'Document isolated-environment concurrency, Skill capacity, and client-overhead tests.', 'Prepare resource planning and site acceptance methods.', 'Performance and capacity', 'Isolated results do not replace customer-site capacity validation.'],
}

const en = zh.map(row => {
  const copy = enCopy[row.id]
  if (!copy) throw new Error(`Missing English capability copy: ${row.id}`)
  const [submodule, name, description, scenario, entry, boundary] = copy
  return { ...row, submodule, name, description, scenario, entry, boundary }
})

export const capabilityModules = [
  { id: 'skill', zh: 'Skill 生命周期治理', en: 'Skill lifecycle governance' },
  { id: 'agent', zh: 'Agent 与运行身份治理', en: 'Agent and runtime identity governance' },
  { id: 'client', zh: '客户端管理', en: 'Client management' },
  { id: 'scanner', zh: '端侧 Skill 扫描', en: 'Endpoint Skill scanning' },
  { id: 'security', zh: 'AI 安全扫描与评估', en: 'AI security scanning and assessment' },
  { id: 'mcp', zh: 'MCP 治理', en: 'MCP governance' },
  { id: 'model', zh: '模型接入与隐私治理', en: 'Model access and privacy governance' },
  { id: 'system', zh: '系统管理与审计', en: 'System administration and audit' },
  { id: 'operations', zh: '部署与运维', en: 'Deployment and operations' },
]

export const capabilityCatalog = { 'zh-CN': zh, 'en-US': en }

export const capabilityModuleLabel = (moduleId, locale = 'zh-CN') => {
  const module = capabilityModules.find(item => item.id === moduleId)
  return locale === 'en-US' ? module?.en : module?.zh
}
