export const clientSummaryMessages = {
  'zh-CN': {
    all: '客户端总数', online: '在线客户端', offline: '离线客户端', agents: '已发现 Agent', issues: '存在异常的客户端',
    offlineCount: '离线 {count} 台', governable: '支持 Skill 管理 {count} 个', visibleClients: '当前账号可见的全部设备',
    onlineHelp: '最近 10 分钟内有心跳即为在线，以最近刷新结果为准。',
    issuesHelp: '统计采集、任务、治理或运行问题尚未恢复的客户端，每台计一次。点击列表中的原因查看详情。',
    unresolvedOnly: '仅未恢复问题',
    channels: { logs: '日志', hooks: 'Hook', system: '系统采集' },
    reasons: { unreported: '尚未报告', stale: '报告超时', failed: '通道故障', stopped: '通道已停止', disabled: '采集未启用', unsupported: '通道不受支持', waiting_authorization: '等待本机授权', disable_not_applied: '停止采集未生效', mode_pending: '运行模式待应用', upload_failed: '上传失败', source_failed: '来源读取异常', transport_offline: '上传报告超时', skill_failed: 'Skill 校验或处置失败', policy_failed: '策略应用异常', active_alert: '活跃告警', task_failed: '任务失败', runtime_failed: '运行错误', product_upgrade_required: '接入需要升级客户端', mode_upgrade_required: '运行模式需要升级客户端' },
    byClient: '按设备去重', results: '筛选结果 {count} 台', clearFilters: '清空筛选',
    refreshed: '最近刷新：{time}', issueCount: '异常 {count} · 查看记录',
  },
  'en-US': {
    all: 'Total Clients', online: 'Online Clients', offline: 'Offline Clients', agents: 'Discovered Agents', issues: 'Clients with issues',
    offlineCount: '{count} offline', governable: '{count} support Skill management', visibleClients: 'All devices visible to your account',
    onlineHelp: 'A heartbeat within the last 10 minutes counts as online, based on the latest refresh.',
    issuesHelp: 'Counts each Client with unresolved collection, task, governance or runtime issues once. Select a reason in the table for details.',
    unresolvedOnly: 'Unresolved issues only',
    channels: { logs: 'Logs', hooks: 'Hook', system: 'System collection' },
    reasons: { unreported: 'Not reported', stale: 'Report overdue', failed: 'Channel failed', stopped: 'Channel stopped', disabled: 'Collection disabled', unsupported: 'Channel unsupported', waiting_authorization: 'Local authorization required', disable_not_applied: 'Collection stop not applied', mode_pending: 'Mode pending', upload_failed: 'Upload failed', source_failed: 'Source read issue', transport_offline: 'Upload report overdue', skill_failed: 'Skill verification or action failed', policy_failed: 'Policy application issue', active_alert: 'Active alerts', task_failed: 'Task failed', runtime_failed: 'Runtime error', product_upgrade_required: 'Client upgrade required for integration', mode_upgrade_required: 'Client upgrade required for mode' },
    byClient: 'Counted by device', results: '{count} matching Clients', clearFilters: 'Clear filters',
    refreshed: 'Last refreshed: {time}', issueCount: '{count} issues · View records',
  },
}
