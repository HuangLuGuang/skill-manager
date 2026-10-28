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
