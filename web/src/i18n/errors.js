const errorMessages = {
  'auth.username_already_registered': {
    'zh-CN': '用户名已存在',
    'en-US': 'Username is already registered',
  },
  'auth.captcha_expired': {
    'zh-CN': '验证码无效或已过期',
    'en-US': 'The verification code is invalid or expired',
  },
  'auth.captcha_incorrect': {
    'zh-CN': '验证码错误',
    'en-US': 'The verification code is incorrect',
  },
  'auth.invalid_credentials': {
    'zh-CN': '用户名或密码错误',
    'en-US': 'Incorrect username or password',
  },
  'auth.invalid_token': {
    'zh-CN': '登录凭证无效',
    'en-US': 'Could not validate credentials',
  },
  'auth.session_expired_elsewhere': {
    'zh-CN': '当前账号已在其他位置登录，请重新登录',
    'en-US': 'This account signed in elsewhere. Sign in again.',
  },
  'auth.account_disabled': {
    'zh-CN': '账号已被禁用',
    'en-US': 'The account is disabled',
  },
  'auth.permission_denied': {
    'zh-CN': '权限不足',
    'en-US': 'Permission denied',
  },
  'auth.old_password_incorrect': {
    'zh-CN': '旧密码不正确',
    'en-US': 'The current password is incorrect',
  },
  'credential.missing': {
    'zh-CN': '缺少接入凭证',
    'en-US': 'Missing access credential',
  },
  'credential.invalid_or_disabled': {
    'zh-CN': '接入凭证无效或已禁用',
    'en-US': 'The access credential is invalid or disabled',
  },
  'credential.expired': {
    'zh-CN': '接入凭证已过期',
    'en-US': 'The access credential has expired',
  },
  'credential.scope_missing': {
    'zh-CN': '接入凭证缺少权限：{scopes}',
    'en-US': 'The access credential requires scope: {scopes}',
  },
  'credential.ip_not_allowed': {
    'zh-CN': '接入凭证不允许当前来源 IP',
    'en-US': 'The source IP is not allowed by this credential',
  },
  'credential.concurrency_limit': {
    'zh-CN': '接入凭证并发请求数已达上限',
    'en-US': 'The credential concurrency limit has been reached',
  },
  'credential.name_required': {
    'zh-CN': '凭证名称不能为空',
    'en-US': 'Credential name is required',
  },
  'credential.not_found': {
    'zh-CN': '接入凭证不存在',
    'en-US': 'Access credential not found',
  },
  'agent.id_missing': {
    'zh-CN': '缺少 agent_id',
    'en-US': 'Missing agent_id',
  },
  'agent.id_mismatch': {
    'zh-CN': 'agent_id 与 X-Agent-ID 不一致',
    'en-US': 'agent_id does not match X-Agent-ID',
  },
  'agent.credential_binding_mismatch': {
    'zh-CN': '接入凭证绑定的智能体不匹配',
    'en-US': 'The credential is bound to a different Agent',
  },
  'agent.not_found': {
    'zh-CN': '智能体不存在',
    'en-US': 'Agent not found',
  },
  'agent.disabled': {
    'zh-CN': '智能体未启用',
    'en-US': 'Agent is disabled',
  },
  'agent.skill_not_allowed': {
    'zh-CN': '智能体未授权使用该 Skill',
    'en-US': 'The Agent is not authorized to use this Skill',
  },
  'agent.prompt_not_allowed': {
    'zh-CN': '智能体未授权使用该 Prompt',
    'en-US': 'The Agent is not authorized to use this Prompt',
  },
}

const interpolate = (value, params = {}, locale = 'zh-CN') =>
  String(value).replace(/\{(\w+)\}/g, (_, key) => {
    const parameter = params[key]
    if (Array.isArray(parameter)) return parameter.join(locale === 'en-US' ? ' or ' : ' 或 ')
    return parameter ?? `{${key}}`
  })

export const localizeApiError = (detail, locale) => {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return detail
  const code = detail.code
  const params = detail.params || {}
  const localMessage = errorMessages[code]?.[locale]
  const serverMessage = detail.messages?.[locale] || detail.message
  return interpolate(localMessage || serverMessage || code || 'Request failed', params, locale)
}

export const getApiErrorCode = detail =>
  detail && typeof detail === 'object' && !Array.isArray(detail) ? detail.code : undefined
