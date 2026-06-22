export const navigationItems = [
  {
    key: 'workspace',
    label: '工作台',
    icon: 'dashboard',
    children: [{ key: '/dashboard', label: '总览', icon: 'dashboard' }],
  },
  {
    key: 'skill-governance',
    label: 'Skill 治理',
    icon: 'fileSearch',
    children: [
      { key: '/skills', label: '技能注册表', icon: 'fileSearch' },
      { key: '/submit', label: '提交技能', icon: 'upload' },
      { key: '/review', label: '审核队列', icon: 'checkSquare' },
      { key: '/deployments', label: '部署管理', icon: 'deployment' },
    ],
  },
  {
    key: 'prompt-governance',
    label: 'Prompt 治理',
    icon: 'fileText',
    children: [{ key: '/prompts', label: '提示词管理', icon: 'fileText' }],
  },
  {
    key: 'runtime-access',
    label: '接入与运行',
    icon: 'safety',
    children: [
      { key: '/runtime', label: '运行时治理', icon: 'safety' },
      { key: '/scanner-access', label: 'Skills 扫描器', icon: 'key' },
    ],
  },
  {
    key: 'model-gateway',
    label: '模型网关',
    icon: 'api',
    children: [
      { key: '/model-gateway/providers', label: '供应商管理', icon: 'api' },
      { key: '/model-gateway/models', label: '模型管理', icon: 'deployment' },
      { key: '/model-gateway/keys', label: 'API Key', icon: 'key' },
      { key: '/model-gateway/groups', label: '用户与组', icon: 'team' },
      { key: '/model-gateway/policies', label: '隐私策略', icon: 'setting' },
      { key: '/model-gateway/audit', label: '隐私审计', icon: 'audit' },
      { key: '/model-gateway/stats', label: '用量统计', icon: 'barChart' },
      { key: '/model-gateway/user-stats', label: '用户用量', icon: 'team' },
      { key: '/pipeline-trace', label: 'Pipeline Trace', icon: 'audit' },
    ],
  },
  {
    key: 'system-admin',
    label: '系统管理',
    icon: 'setting',
    children: [
      { key: '/policy', label: '策略配置', icon: 'setting' },
      { key: '/audit', label: '审计日志', icon: 'audit' },
      { key: '/settings', label: '系统设置', icon: 'setting' },
    ],
  },
]

export const resolveMenuKey = (path) => {
  if (path.startsWith('/skills/')) return '/skills'
  if (path.startsWith('/prompts/')) return '/prompts'
  if (path === '/model-gateway') return '/model-gateway/providers'
  return path
}

export const findMenuOpenKeys = (path) => {
  const selectedKey = resolveMenuKey(path)

  for (const item of navigationItems) {
    if (item.children?.some((child) => child.key === selectedKey)) {
      return [item.key]
    }
  }

  return []
}
