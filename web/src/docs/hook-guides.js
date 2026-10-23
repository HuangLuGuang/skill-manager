export const hookGuides = {
  'zh-CN': {
    'hook-integration': {
      eyebrow: '操作指南',
      title: 'Hook 接入：客户端 AIDR 插件',
      summary: '通过客户端连接设备、应用插件策略、完成宿主信任，再用真实事件验收采集与工具控制。',
      sections: [
        {
          id: 'prepare', title: '1. 连接客户端并确认设备权限',
          paragraphs: ['默认使用 Agent Manager Client 的 AIDR 插件 Hook。客户端使用随包适配器和已有设备认证，按策略安装插件或写入受支持产品的 Hook 配置，主后台服务管理接收器和上传。'],
          steps: [
            { title: '在 Agent 所在电脑连接客户端', body: '安装客户端并完成设备认证。在客户端管理确认设备在线，核对本机 Agent 的发现结果和客户端版本。' },
            { title: '管理员确认 AIDR 上报权限', body: '允许设备 AIDR 上报，并确认设备凭证具有 aidr:heartbeat 和 aidr:report-events。' },
          ],
          callout: { type: 'note', title: '普通自动接入所需配置', body: '客户端负责插件、连接路径和接收器，无需手工复制脚本、填写桥接环境变量或另建 Agent 运行凭证。宿主原生信任、启用和必要授权仍需按提示完成。开发者 Runtime API、模型和 MCP 网关按各自能力配置凭证。' },
          link: { path: '/docs/client-management', label: '查看客户端安装与连接步骤' },
        },
        {
          id: 'policy', title: '2. 启用插件 Hook 通道并选择产品',
          paragraphs: ['在客户端策略中启用插件 Hook 通道，选择实际使用且已适配的产品，确认设备继承默认策略还是使用设备覆盖。Agent 日志与系统事件是独立通道，按需要配置。'],
          table: { columns: ['接入方式', '在哪里做、做什么', '如何确认'], rows: [
            ['普通自动安装', '平台选择自动安装；客户端检查宿主兼容性，按需安装随包插件或写入 Hook 配置。更新由更新策略控制。', '设备详情查看实际应用版本、安装状态和任务回执。'],
            ['显式安装', '从设备详情的“插件接入”下发安装任务。', '核对客户端任务结果，再检查宿主启用和信任。'],
            ['企业受管接入', '按受管模式完成原生授权及策略应用，确认目标产品和版本支持该模式。', '核对原生授权结果及客户端报告，不能用普通安装结果代替。'],
          ] },
          link: { path: '/docs/aidr-platform', label: '查看平台配置与设备验收' },
        },
        {
          id: 'activate', title: '3. 完成宿主信任并新建会话',
          steps: [
            { title: '核对插件和接收器状态', body: '在客户端“Agent 运行治理”和平台设备详情“插件接入”查看安装、启用、信任、接收器、报告时间和实际策略版本。未知或过期报告需要重新检查。' },
            { title: '完成目标产品的原生确认', body: '按宿主提示完成审阅或授权，例如 Codex 在原生 /hooks 审阅信任。重启宿主或新建会话，让配置生效。' },
          ],
          paragraphs: ['Hook 接收器和日志采集运行在 agent-manager-client run 主后台服务内。关闭窗口、退出或重启桌面界面不会停止它们；主后台服务重启会短暂重建接收器。运行目标仍由有效策略控制。'],
          link: { path: '/docs/aidr-client', label: '查看客户端操作和通道状态' },
        },
        {
          id: 'verify-troubleshoot', title: '4. 用真实工具事件验收',
          table: { columns: ['验收项', '操作与确认'], rows: [
            ['接入与投递', '在新宿主会话触发受支持的工具操作，核对客户端接收状态、平台同一设备和产品的 Hook 事件及事件批次 ACK。'],
            ['仅审计', '确认事件到达，会话和工具证据可查看；仅审计模式不执行策略阻断。'],
            ['工具拦截', '对提供相应执行前控制点的产品，在拦截模式发布测试规则，分别核对允许、拒绝，以及需要时的人工审批结果与实际工具行为。'],
            ['状态缺失', '检查产品兼容性、原生信任、新会话、有效策略版本与报告时间；从“插件接入”发起重新检查。'],
            ['上传中断', '检查设备上报许可、凭证、队列、重试原因及最近事件 ACK；恢复后确认待发事件实际到达。'],
          ] },
          callout: { type: 'note', title: '按通道和执行点验收', body: 'Hook、Agent 日志和系统采集分别验收。插件安装、设备在线或一次事件到达，各自只证明对应步骤；工具阻断覆盖以目标产品真实支持的执行点和实际结果为准。' },
          link: { path: '/docs/aidr-troubleshooting', label: '查看 AIDR 排障步骤' },
        },
        {
          id: 'skill-verification', title: '5. 需要 Skill 加载前验签时',
          paragraphs: ['AIDR Hook 根据工具策略做运行决策；Skill 使用审计由后台内容观察和平台状态核对形成异步结论。要求在加载前验证 Skill 内容与授权时，在真实 Loader 或受支持的宿主事件接入同步校验。'],
          bullets: ['手工脚本、环境变量、Agent 运行凭证和宿主配置示例集中在“开发者：加载前验签”。', '需要治理模型或 MCP 请求时，分别配置对应网关并验证调用。'],
          link: { path: '/docs/developer-skill-verification', label: '开发者：加载前验签与手工脚本' },
        },
      ],
    },
  },
  'en-US': {
    'hook-integration': {
      eyebrow: 'Operating guide',
      title: 'Hook integration: Client AIDR plugins',
      summary: 'Connect the device, apply plugin policy, complete native host trust, then verify event collection and tool controls with real calls.',
      sections: [
        {
          id: 'prepare', title: '1. Connect the Client and confirm device permissions',
          paragraphs: ['Use Agent Manager Client AIDR plugin Hooks by default. Bundled adapters and existing device authentication install native plugins or configure supported Hooks according to policy. The main background service manages reception and upload.'],
          steps: [
            { title: 'Connect the Client on the Agent host', body: 'Install the Client and authenticate the device. Confirm it is online in Client management and inspect discovered Agents and the Client version.' },
            { title: 'Confirm AIDR reporting permissions', body: 'An administrator allows device AIDR reporting and verifies that the device credential has aidr:heartbeat and aidr:report-events.' },
          ],
          callout: { type: 'note', title: 'Ordinary automatic setup', body: 'The Client manages plugins, connection paths and the receiver. You do not need copied scripts, bridge environment variables or a separate Agent runtime credential. Complete native trust, enablement and required authorization when prompted. Developer Runtime APIs, model and MCP gateways use their own credential setup.' },
          link: { path: '/docs/client-management', label: 'Read Client installation and connection steps' },
        },
        {
          id: 'policy', title: '2. Enable plugin Hooks and select products',
          paragraphs: ['Enable the plugin Hook channel in Client policy and select the supported products in use. Confirm inherited defaults or device overrides. Agent logs and system events are separate channels configured by need.'],
          table: { columns: ['Mode', 'Where and what to configure', 'How to confirm'], rows: [
            ['Ordinary automatic installation', 'Select automatic installation on the platform. The Client checks compatibility and installs bundled plugins or configures Hooks as needed. Update policy controls upgrades.', 'Inspect applied versions, installation state and task receipts in device details.'],
            ['Explicit installation', 'Dispatch an installation task from Plugin integration in device details.', 'Check the task result, then verify native enablement and trust.'],
            ['Managed integration', 'Complete native authorization and policy application for managed mode. Confirm product and version support.', 'Check native authorization and Client reports; ordinary installation results do not establish managed readiness.'],
          ] },
          link: { path: '/docs/aidr-platform', label: 'Read platform configuration and device acceptance' },
        },
        {
          id: 'activate', title: '3. Complete native trust and start a new session',
          steps: [
            { title: 'Inspect plugin and receiver state', body: 'Use Agent runtime governance in the Client and Plugin integration in platform device details. Check installation, enablement, trust, receiver state, report age and the applied policy version. Reinspect unknown or stale reports.' },
            { title: 'Complete host confirmation', body: 'Review and authorize in the target product when prompted, such as native /hooks review in Codex. Restart the host or start a new session to activate configuration.' },
          ],
          paragraphs: ['The Hook receiver and log collector run inside the main agent-manager-client run background service. Closing or restarting the desktop UI leaves them running. Restarting the background service briefly recreates the receiver. Effective policy controls their runtime targets.'],
          link: { path: '/docs/aidr-client', label: 'Read Client operations and channel states' },
        },
        {
          id: 'verify-troubleshoot', title: '4. Verify with real tool events',
          table: { columns: ['Check', 'Action and evidence'], rows: [
            ['Integration and delivery', 'Trigger a supported tool in a new host session. Correlate local receiver state, the same device/product Hook event on the platform and the event-batch ACK.'],
            ['Audit only', 'Confirm delivered events and accessible session/tool evidence. Audit-only mode does not enforce policy blocking.'],
            ['Tool interception', 'For products with the required pre-execution control point, publish a test rule in interception mode. Verify allow, deny and any human approval outcome against actual tool behavior.'],
            ['Missing state', 'Check compatibility, native trust, the new session, effective policy version and report age. Request reinspection from Plugin integration.'],
            ['Upload interruption', 'Check reporting permission, credentials, queues, retry reasons and the latest event ACK. Confirm queued events reach the platform after recovery.'],
          ] },
          callout: { type: 'note', title: 'Verify each channel and execution point', body: 'Test Hooks, Agent logs and system collection separately. Installation, device online state and one delivered event each establish only that step. Blocking coverage depends on real supported execution points and observed outcomes.' },
          link: { path: '/docs/aidr-troubleshooting', label: 'Read AIDR troubleshooting steps' },
        },
        {
          id: 'skill-verification', title: '5. When you need pre-load Skill verification',
          paragraphs: ['AIDR Hooks make tool-policy decisions. Skill usage audit combines background content observations with platform state checks asynchronously. For content and authorization checks before loading, integrate synchronous verification at the real Loader or a supported host event.'],
          bullets: ['Manual scripts, environment variables, Agent runtime credentials and host configuration examples are in Developer: pre-load verification.', 'To govern model or MCP requests, configure the corresponding gateway and verify calls.'],
          link: { path: '/docs/developer-skill-verification', label: 'Developer: pre-load verification and manual scripts' },
        },
      ],
    },
  },
}
