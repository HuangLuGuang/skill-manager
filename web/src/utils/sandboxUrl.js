export const SANDBOX_URL_MAX_LENGTH = 2048

// 基础地址会拼接 /run-code，保存和测试连接共用校验。
export const sandboxUrlError = (value, runtime = 'remote') => {
  // 本地运行不使用远程地址。
  if (runtime === 'docker') return null
  if (!value) return 'url_required'
  if (value.length > SANDBOX_URL_MAX_LENGTH) return 'url_too_long'
  if (/[\s\\?#]/u.test(value) || !/^https?:\/\/[^/]/i.test(value)) return 'url_invalid'
  try {
    const url = new URL(value)
    if (!url.hostname || url.port === '0') return 'url_invalid'
  } catch {
    return 'url_invalid'
  }
  return null
}
