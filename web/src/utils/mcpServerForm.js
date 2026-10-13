export const serverFields = ['name', 'slug', 'endpoint', 'authorization_header', 'authorization_value', 'status', 'timeout_seconds', 'max_response_kb', 'description']
export const testFields = ['endpoint', 'authorization_header', 'authorization_value', 'timeout_seconds']
const limits = { name: 128, slug: 128, endpoint: 1024, authorization_header: 128, authorization_value: 4096, description: 2000 }
const trimmed = ['name', 'slug', 'endpoint', 'authorization_header']

// 校验原始草稿；只在发送有效请求时转换数字和去除既有字段首尾空白。
export const mcpServerErrors = (data, { allowHttp = null } = {}) => {
  const issues = {}
  const fail = (field, reason, params = {}) => { issues[field] = { field, reason, ...params } }
  for (const field of serverFields) {
    const raw = data[field]
    const value = trimmed.includes(field) ? String(raw ?? '').trim() : raw
    if (trimmed.includes(field) && !value) { fail(field, 'required'); continue }
    if (limits[field] && Array.from(String(value ?? '')).length > limits[field]) {
      fail(field, 'length', { limit: limits[field] }); continue
    }
    if (field === 'slug' && !/^[a-z0-9][a-z0-9_-]{0,127}$/u.test(value)) fail(field, 'slug')
    if (field === 'authorization_header' && !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/u.test(value)) fail(field, 'header')
    if (field === 'authorization_value' && /[^\x20-\x7e]/u.test(value || '')) fail(field, 'value')
    if (field === 'status' && !['draft', 'active', 'disabled'].includes(value)) fail(field, 'status')
    if (field === 'endpoint') {
      try {
        const url = new URL(value)
        if (allowHttp === false && url.protocol === 'http:') fail(field, 'https')
        if (!/^https?:\/\//iu.test(value) || /\s/u.test(value) || !url.hostname || url.username || url.password || url.hash) fail(field, 'url')
      } catch { fail(field, 'url') }
    }
    if (['timeout_seconds', 'max_response_kb'].includes(field)) {
      const max = field === 'timeout_seconds' ? 300 : 10240
      if (!/^\d+$/u.test(String(value ?? '')) || !Number.isSafeInteger(Number(value)) || Number(value) < 1 || Number(value) > max) fail(field, 'integer', { min: 1, max })
    }
  }
  return issues
}
export const serverPayload = data => Object.fromEntries(Object.entries(data).map(([field, value]) => [field,
  trimmed.includes(field) ? value.trim() : ['timeout_seconds', 'max_response_kb'].includes(field) ? Number(value) : value,
]))
