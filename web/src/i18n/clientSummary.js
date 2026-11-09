export const clientSummaryMessages = {
  'zh-CN': {
    all: '客户端总数', online: '在线客户端', offline: '离线客户端', agents: '已发现 Agent', issues: '存在异常的客户端',
    offlineCount: '离线 {count} 台', governable: '支持 Skill 管理 {count} 个', visibleClients: '当前账号可见的全部设备',
    onlineHelp: '最近 10 分钟内有心跳即为在线，以最近刷新结果为准。',
    issuesHelp: '按客户端去重统计已有 Skill 异常或活跃告警，不代表待处理工单数。点击列表中的异常数量查看设备记录。',
    byClient: '按设备去重', results: '筛选结果 {count} 台', clearFilters: '清空筛选',
    refreshed: '最近刷新：{time}', issueCount: '异常 {count} · 查看记录',
  },
  'en-US': {
    all: 'Total Clients', online: 'Online Clients', offline: 'Offline Clients', agents: 'Discovered Agents', issues: 'Clients with issues',
    offlineCount: '{count} offline', governable: '{count} support Skill management', visibleClients: 'All devices visible to your account',
    onlineHelp: 'A heartbeat within the last 10 minutes counts as online, based on the latest refresh.',
    issuesHelp: 'Counts distinct Clients with recorded Skill issues or active alerts, not pending tickets. Select an issue count in the table to view device records.',
    byClient: 'Counted by device', results: '{count} matching Clients', clearFilters: 'Clear filters',
    refreshed: 'Last refreshed: {time}', issueCount: '{count} issues · View records',
  },
}
