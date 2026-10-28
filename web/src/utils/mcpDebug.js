// 网关连接预算覆盖整个握手；取消与完成均释放计时器。
export const validConnectionTimeout = value => Number.isInteger(value) && value >= 1 && value <= 300

export const createConnectionAttempt = seconds => {
  const controller = new AbortController()
  const timer = seconds === undefined ? undefined : setTimeout(() => controller.abort('timeout'), seconds * 1000)
  const dispose = () => clearTimeout(timer)
  return {
    seconds,
    signal: controller.signal,
    dispose,
    cancel: () => { dispose(); controller.abort('cancelled') },
  }
}

// 历史保留毫秒原值，仅按当前语言分级显示。
export const formatDebugDuration = (milliseconds, t) => {
  const unit = milliseconds < 1000 ? 'Milliseconds' : milliseconds < 60000 ? 'Seconds' : 'Minutes'
  const divisor = milliseconds < 1000 ? 1 : milliseconds < 60000 ? 1000 : 60000
  return t(`mcpDebug.duration${unit}`, { value: Number((milliseconds / divisor).toFixed(2)) })
}

const debugErrorMessages = {
  'mcp.debug.network_failed': 'mcpDebug.networkFailed',
  'mcp.debug.connection_timeout': 'mcpDebug.connectionTimeout',
}

// 仅渲染浏览器生成的错误说明，服务端响应及原始原因保持原文。
export const localizeDebugResponse = (response, t) => {
  if (!Object.hasOwn(debugErrorMessages, response?.error_code)) return response
  const key = debugErrorMessages[response.error_code]
  return {
    detail: t(key, { seconds: response.error_params?.timeout_seconds }),
    ...response,
  }
}

// 与服务端审批参数沿用相同敏感字段规则，仅脱敏历史展示副本。
export const maskDebugRequest = (value, key = '') => {
  if (/(password|passwd|secret|token|authorization|api_key|apikey|access_key|private_key|credential)/.test(key.toLowerCase().replaceAll('-', '_'))) return '******'
  if (Array.isArray(value)) return value.map(item => maskDebugRequest(item))
  if (value && typeof value === 'object') return Object.fromEntries(
    Object.entries(value).map(([name, item]) => [name, maskDebugRequest(item, name)]),
  )
  return value
}
