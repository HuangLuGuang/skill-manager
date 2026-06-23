export const navigationItems = [
  {
    key: 'agent-governance',
    label: '智能体管理',
    icon: 'agent',
    children: [
      { key: '/agents', label: '智能体列表', icon: 'agent' },
      {
        key: 'skill-governance',
        label: 'Skill 治理',
        icon: 'fileSearch',
        children: [
          { key: '/submit', label: '提交 Skill', icon: 'upload' },
          { key: '/review', label: '审核队列', icon: 'checkSquare' },
          { key: '/skills', label: 'Skill 列表', icon: 'fileSearch' },
          { key: '/policy', label: '策略配置', icon: 'setting' },
          { key: '/audit', label: '审计日志', icon: 'audit' },
        ],
      },
      {
        key: 'prompt-governance',
        label: 'Prompt 治理',
        icon: 'fileText',
        children: [
          { key: '/prompts', label: 'Prompt 列表', icon: 'fileText' },
        ],
      },
      {
        key: 'access-runtime',
        label: '接入与运行',
        icon: 'safety',
        children: [
          { key: '/credentials', label: '凭证管理', icon: 'key' },
          { key: '/runtime', label: '运行时治理', icon: 'safety' },
          { key: '/scanner-access', label: 'Skills 扫描器', icon: 'key' },
        ],
      },
    ],
  },
  {
    key: 'model-gateway',
    label: '模型网关',
    icon: 'api',
    children: [
      { key: '/model-gateway/providers', label: '供应商管理', icon: 'api' },
      { key: '/model-gateway/models', label: '模型管理', icon: 'deployment' },
      { key: '/model-gateway/policy-bindings', label: '组策略绑定', icon: 'team' },
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
      { key: '/users-groups', label: '用户与组', icon: 'team' },
      { key: '/settings', label: '系统总览', icon: 'setting' },
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

  const findOpenPath = (items, parents = []) => {
    for (const item of items) {
      if (item.key === selectedKey) {
        return parents
      }

      if (item.children) {
        const childPath = findOpenPath(item.children, [...parents, item.key])
        if (childPath) return childPath
      }
    }

    return null
  }

  return findOpenPath(navigationItems) ?? []
}
