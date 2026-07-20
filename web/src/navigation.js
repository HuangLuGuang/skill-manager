export const navigationItems = [
  { key: '/dashboard', label: '平台总览', icon: 'dashboard' },
  {
    key: 'capability-governance',
    label: '能力治理',
    icon: 'fileSearch',
    children: [
      { key: '/submit', label: '提交 Skill', icon: 'upload' },
      { key: '/review', label: 'Skill 审核', icon: 'checkSquare' },
      { key: '/skills', label: 'Skill 列表', icon: 'fileSearch' },
      { key: '/policy', label: '策略配置', icon: 'setting' },
    ],
  },
  {
    key: 'agent-management',
    label: '智能体管理',
    icon: 'agent',
    children: [
      { key: '/agents', label: '智能体列表', icon: 'agent' },
      { key: '/clients', label: '终端管理', icon: 'desktop' },
      { key: '/credentials', label: '统一凭证中心', icon: 'key' },
      { key: '/runtime', label: '接入与运行', icon: 'safety' },
      { key: '/audit', label: '审计追踪', icon: 'audit' },
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
      { key: '/model-gateway/prompt-guard', label: 'Prompt 防护测试', icon: 'safety' },
      { key: '/model-gateway/audit', label: '隐私审计', icon: 'audit' },
      { key: '/model-gateway/stats', label: 'Token 压缩统计', icon: 'barChart' },
      { key: '/model-gateway/user-stats', label: '用户 Token 分析', icon: 'team' },
      { key: '/pipeline-trace', label: '隐私链路追踪', icon: 'audit' },
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
  if (path.startsWith('/prompts/')) return '/model-gateway/policies'
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
