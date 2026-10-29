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

// 待审批是本次已结束调用的响应状态，后续执行需重新发起请求。
export const isPendingDebugApproval = (method, response) => method === 'tools/call'
  && response?.error?.data?.approval_required === true
  && response.error.data.status === 'pending'

// 平台拒绝使用响应编码；直连服务的上游错误仍归为调用失败。
export const debugCallStatus = (ok, response, gateway = false, httpStatus) => {
  if (gateway && (response?.error?.call_status === 'denied' || [400, 401, 403, 404, 413, 422, 429].includes(httpStatus))) return 'denied'
  if (!ok || response?.error || response?.result?.isError === true) return 'error'
  return 'success'
}

// 根级组合、引用和动态键无法由固定 properties 表单完整表达。
export const usesRawArguments = (schema = {}) => {
  const rootStructures = [
    'oneOf', 'anyOf', 'allOf', '$ref', '$dynamicRef', 'if', 'then', 'else', 'not',
    'patternProperties', 'dependentSchemas', 'dependencies', 'unevaluatedProperties', 'const', 'enum',
  ]
  if (rootStructures.some(key => Object.hasOwn(schema, key))) return true
  if (Array.isArray(schema.type)) return true
  if (schema.additionalProperties === true || typeof schema.additionalProperties === 'object') return true
  return !Object.keys(schema.properties || {}).length && schema.additionalProperties !== false
}

// 仅检查参数传输所需的 JSON 对象格式，Tool Schema 约束由服务端校验。
export const parseRawArguments = text => {
  let value
  try { value = JSON.parse(text) }
  catch { return { error: 'mcpDebug.rawArgumentsInvalidJson' } }
  if (value === null || Array.isArray(value) || typeof value !== 'object') {
    return { error: 'mcpDebug.rawArgumentsObjectRequired' }
  }
  return { value }
}
