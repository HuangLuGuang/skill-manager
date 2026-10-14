const node = (label, path, detail) => ({ label, path: `/docs/${path}`, detail })

const diagrams = {
  'zh-CN': {
    start: '从实际运行的产品与治理目标出发',
    hint: '沿符合你情况的分支阅读，点击方案节点打开操作文档。',
    columns: ['你要接入什么？', '具备什么接入条件？', '选择方案 · 点击查看步骤'],
    routes: [
      { id: 'client', scenario: '电脑上的现成 Agent', examples: 'Codex、Claude Code 等本地工具', condition: '能安装客户端，且目标产品已适配', links: [node('Agent Manager Client', 'client-management', '安装客户端 → 发现 Agent → 下发配置与 Skill')] },
      { id: 'runtime', scenario: '自研或服务端 Agent', examples: '自己的程序、框架应用或服务', condition: '能修改真实 Skill Loader / Tool 执行代码', links: [node('Runtime API / SDK', 'runtime-integration#verifier-setup', '登记或复用身份 → 签发凭证 → 接入校验与轨迹')] },
      { id: 'dify', scenario: 'Dify 应用', examples: 'Chatflow / Workflow', condition: '能提供相应用途的 API 授权或 DSL', links: [node('Dify API 资产纳管', 'dify-security-access', '配置目标与凭据 → 采集资产 → 执行授权扫描')] },
      { id: 'scanner', scenario: '只有 Skill 文件', examples: '客户主机、共享目录、CI 流水线', condition: '能运行扫描器并读取目标目录', links: [node('Skill Scanner', 'scanner-access', '配置 Scanner 凭证 → 扫描目录 → 查看结果')] },
      { id: 'gateway', scenario: '只接入模型或 MCP 调用', examples: '第三方应用、普通模型应用、MCP Client', condition: '能修改服务地址、鉴权和模型 / 工具连接配置', links: [node('内置模型网关', 'model-gateway', '模型流量进入平台，执行访问与隐私策略'), node('MCP 网关', 'mcp-governance', '连接已发布工具，按策略执行审批与审计'), node('客户外部 AI 网关', 'external-ai-gateway', '模型流量直接进入客户网关，平台管理接入关系')] },
    ],
    additionalTitle: '还需要运行时校验或审计？按条件组合接入',
    additional: [
      node('客户端 AIDR 插件 Hook', 'hook-integration', '平台策略 → 插件安装与宿主信任 → 新会话事件及工具策略验收。'),
      node('开发者：加载前验签', 'developer-skill-verification', '能控制 Loader 或加载事件：接入同步验签、加载授权及手工脚本。'),
      node('Agent Skill Verifier', 'runtime-integration#skill-verifier', '宿主支持 Skill 指令和脚本：每次使用前校验；实际阻断依赖宿主执行。'),
      node('AIDR 运行审计与防护', 'aidr-overview#architecture', '需要会话、工具或系统证据：按产品与权限选择日志、Hook、系统通道。'),
    ],
    identity: node('什么时候需要创建智能体？', 'agent-management#registration-decision', '按 Agent 授权与归属时需要身份；已有身份直接复用，客户端可发现登记。普通模型 / MCP 调用和 Scanner 可使用各自凭证。'),
    unavailable: '不能安装客户端时，继续按可修改的代码、宿主事件、Skill 指令或网关配置选择。缺少对应执行点时，只接入当前具备条件的能力，并保留覆盖边界。',
  },
  'en-US': {
    start: 'Start with the actual product and governance goal',
    hint: 'Follow the matching branch. Select a solution node to open its instructions.',
    columns: ['What are you connecting?', 'What can you configure?', 'Choose a solution · open its guide'],
    routes: [
      { id: 'client', scenario: 'Packaged local Agent', examples: 'Local tools such as Codex and Claude Code', condition: 'You can install the Client and the product is supported', links: [node('Agent Manager Client', 'client-management', 'Install → discover Agents → deliver configuration and Skills')] },
      { id: 'runtime', scenario: 'Custom or server-side Agent', examples: 'Your program, framework application or service', condition: 'You can change the real Skill loader / Tool execution code', links: [node('Runtime API / SDK', 'runtime-integration#verifier-setup', 'Register or reuse identity → issue credential → integrate checks and traces')] },
      { id: 'dify', scenario: 'Dify application', examples: 'Chatflow / Workflow', condition: 'You can provide purpose-specific API access or DSL', links: [node('Dify API asset governance', 'dify-security-access', 'Configure target and credentials → collect assets → run authorized scans')] },
      { id: 'scanner', scenario: 'Skill files only', examples: 'Customer hosts, shared directories or CI pipelines', condition: 'You can run Scanner and read the target directory', links: [node('Skill Scanner', 'scanner-access', 'Configure Scanner credential → scan directories → review results')] },
      { id: 'gateway', scenario: 'Model or MCP calls only', examples: 'Third-party apps, model applications or MCP Clients', condition: 'You can change service URLs, authentication and model / tool connections', links: [node('Built-in model gateway', 'model-gateway', 'Model traffic enters the platform for access and privacy controls'), node('MCP gateway', 'mcp-governance', 'Connect published tools with policy-based approval and audit'), node('Customer external AI gateway', 'external-ai-gateway', 'Model traffic goes directly to the customer gateway; the platform manages integration')] },
    ],
    additionalTitle: 'Need runtime checks or audit too? Combine supported capabilities',
    additional: [
      node('Client AIDR plugin Hooks', 'hook-integration', 'Policy → plugin installation and native trust → verify new-session events and tool decisions.'),
      node('Developer: pre-load verification', 'developer-skill-verification', 'Control the Loader or load event: integrate synchronous signature and authorization checks or adapt manual scripts.'),
      node('Agent Skill Verifier', 'runtime-integration#skill-verifier', 'The host supports Skill instructions and scripts: verify before every use; blocking depends on host execution.'),
      node('AIDR runtime audit and protection', 'aidr-overview#architecture', 'For session, tool or system evidence, choose log, Hook and system channels by product and permissions.'),
    ],
    identity: node('When do I need to register an Agent?', 'agent-management#registration-decision', 'Agent-specific authorization and attribution need an identity. Reuse an existing one or discover it through the Client. Ordinary model / MCP calls and Scanner can use their own credentials.'),
    unavailable: 'If you cannot install the Client, choose by the code, host events, Skill instructions or gateway settings you can control. Integrate capabilities whose prerequisites are met and retain their coverage boundaries.',
  },
}

// The same decision data supplies the clickable diagram, search and PDF table.
export const integrationChoiceSections = Object.fromEntries(Object.entries(diagrams).map(([locale, decision]) => [locale, {
  id: 'integration-flow',
  title: locale === 'zh-CN' ? '接入方案选择流程图' : 'Integration selection flowchart',
  paragraphs: [decision.hint],
  diagram: 'integration-choice',
  decision,
  table: {
    columns: decision.columns,
    rows: [
      ...decision.routes.flatMap(route => route.links.map(link => [route.scenario, route.condition, { label: `${link.label} — ${link.detail}`, path: link.path }])),
      ...decision.additional.map(link => [decision.additionalTitle, link.detail, { label: link.label, path: link.path }]),
    ],
  },
  callout: { type: 'note', title: decision.identity.label, body: decision.identity.detail },
  link: { label: decision.identity.label, path: decision.identity.path },
}]))
