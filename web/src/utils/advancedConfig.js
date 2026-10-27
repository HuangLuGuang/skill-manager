import { sandboxUrlError } from './sandboxUrl.js'
import { localizeApiError } from '../i18n/errors.js'
import { policySettingsMessages } from '../i18n/policySettings.js'

export const integerLimits = {
  llm: { timeout_seconds: [5, 600], max_files: [1, 20], max_manifest_chars: [2000, 50000], max_file_chars: [500, 20000] },
  sandbox: { timeout_seconds: [1, 300], pids_limit: [1, 1024] },
}

// 加减只处理有效整数；手动输入由草稿校验处理，不自动替换。
export const stepInteger = (value, delta, min, max) => {
  if (!/^\d+$/u.test(String(value ?? ''))) return value
  const number = Number(value)
  const next = number + delta
  return Number.isSafeInteger(number) && number >= min && number <= max
    && next >= min && next <= max ? String(next) : value
}

export const configRequestError = (failure, locale) => failure.code || failure.message
  ? localizeApiError({ code: failure.code, message: failure.message, params: failure.params }, locale)
  : policySettingsMessages[locale].requestFailed
const component = '[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*'
const imagePattern = new RegExp(`^(?:(?:[a-zA-Z0-9.-]+|\\[[0-9a-fA-F:]+\\])(?::[0-9]+)?/)?${component}(?:/${component})*(?::[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127})?(?:@sha256:[0-9a-fA-F]{64})?$`)

// 校验原始草稿，不修改输入；提交前通过校验才转换数字。
export const advancedConfigErrors = (group, data) => {
  const errors = {}
  const issue = (field, code, params = {}) => { errors[field] = { code, params } }
  for (const [field, [min, max]] of Object.entries(integerLimits[group] || {})) {
    if (field === 'pids_limit' && data.runtime !== 'docker') continue
    const value = data[field]
    if (!/^\d+$/u.test(String(value ?? '')) || !Number.isSafeInteger(Number(value)) || Number(value) < min || Number(value) > max) {
      issue(field, 'config.integer', { min, max })
    }
  }
  if (group === 'llm') {
    if (data.enabled && !data.model) issue('model', 'config.required')
  } else if (group === 'sandbox') {
    if (!['remote', 'docker'].includes(data.runtime)) issue('runtime', 'config.choice')
    if (!['none', 'bridge'].includes(data.network_mode)) issue('network_mode', 'config.choice')
    if (data.runtime === 'docker') {
      if (!data.image || data.image.length > 255 || !imagePattern.test(data.image)) issue('image', 'config.image')
      if (!/^\d+(?:\.\d{1,2})?$/u.test(data.cpu_limit) || Number(data.cpu_limit) < 0.01 || Number(data.cpu_limit) > 64) issue('cpu_limit', 'config.cpu')
      const match = /^(\d+)([bkmg])$/iu.exec(data.memory_limit)
      const bytes = match ? Number(match[1]) * 1024 ** 'bkmg'.indexOf(match[2].toLowerCase()) : 0
      if (!Number.isSafeInteger(bytes) || bytes < 6 * 1024 ** 2 || bytes > 64 * 1024 ** 3) issue('memory_limit', 'config.memory')
    } else if (data.runtime === 'remote') {
      const url = sandboxUrlError(data.remote_url)
      if (url) issue('remote_url', `sandbox.${url}`)
      if (data.remote_api_key && (data.remote_api_key.length > 4096 || /[\s\x00-\x1f\x7f]/u.test(data.remote_api_key))) issue('remote_api_key', 'config.key')
      else if (data.remote_api_key && data.clear_remote_api_key) issue('remote_api_key', 'config.key_conflict')
    }
  }
  const boolFields = { llm: ['enabled'], sandbox: ['enabled', 'clear_remote_api_key', ...(data.runtime === 'docker' ? ['read_only_rootfs'] : [])], policy: ['scan_result_reuse_enabled'] }
  for (const field of boolFields[group] || []) {
    if (typeof data[field] !== 'boolean') issue(field, 'config.boolean')
  }
  return errors
}
