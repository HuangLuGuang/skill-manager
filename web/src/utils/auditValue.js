export const formatAuditValue = (key, value, translate) => {
  const category = {
    status: 'skillStatus',
    risk_level: 'risk',
    pre_llm_risk_level: 'risk',
    max_severity: 'risk',
  }[key]
  if (category && typeof value === 'string') return translate(category, category === 'risk' ? value.toLowerCase() : value, value)
  if (value && typeof value === 'object') return JSON.stringify(value)
  return value
}
