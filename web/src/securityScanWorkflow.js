export const normalizeLlmConfigForForm = config => {
  const source = config && typeof config === 'object' && !Array.isArray(config) ? config : {}
  const { model = '', chat_completions_path = '/v1/chat/completions', timeout_ms = 30000, ...advanced } = source
  return { model, chat_completions_path, timeout_ms, advanced }
}

export const selectCompatiblePolicyId = policies => policies.length === 1 ? policies[0]?.policy_id : undefined

export const mergeLlmConfigFromForm = (advanced, form) => ({
  ...advanced,
  model: form.llm_model.trim(),
  chat_completions_path: form.llm_chat_completions_path.trim() || '/v1/chat/completions',
  timeout_ms: form.llm_timeout_ms,
})

const parseUtc = value => {
  if (!value) return Number.NaN
  const text = String(value)
  const parsed = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : `${text}Z`)
  return Number.isFinite(parsed) ? parsed : Number.NaN
}

export const comparisonCandidates = (tasks, record) => {
  const currentTime = parseUtc(record.created_at || record.completed_at)
  if (!Number.isFinite(currentTime)) return []
  return tasks.filter(item => item.task_id !== record.task_id && item.target_id === record.target_id && item.scan_kind === record.scan_kind && item.status === 'succeeded' && Number.isFinite(parseUtc(item.created_at || item.completed_at)) && parseUtc(item.created_at || item.completed_at) <= currentTime)
    .sort((a, b) => parseUtc(b.created_at || b.completed_at) - parseUtc(a.created_at || a.completed_at))
}
