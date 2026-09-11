export const scanTaskActionsMessages = {
  'zh-CN': {
    downloadLogs: '下载诊断日志',
    logsHelp: '包含任务状态、资源用量和执行事件，不含密钥或原始对话。历史任务可能仅有任务摘要。',
    retry: '重试扫描',
    retryHelp: '使用原配置重新扫描，原任务和报告保留。系统将重新检查当前权限和策略。',
    retryCreated: '已创建新的扫描任务。',
    retryReused: '已有重试任务正在排队或运行，已打开该任务。',
  },
  'en-US': {
    downloadLogs: 'Download diagnostic logs',
    logsHelp: 'Includes task status, resource usage and execution events, without secrets or raw conversations. Older tasks may contain only a summary.',
    retry: 'Retry scan',
    retryHelp: 'Run again with the original settings and retain the original task and report. Current permissions and policies will be checked again.',
    retryCreated: 'A new scan task has been created.',
    retryReused: 'A retry is already queued or running. Opened the existing task.',
  },
}
