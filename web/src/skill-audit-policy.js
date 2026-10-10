export const skillAuditLimits = [
  { key: 'digest_cache_seconds', min: 60, max: 3600 },
  { key: 'status_refresh_seconds', min: 5, max: 3600 },
  { key: 'max_concurrency', min: 1, max: 8 },
  { key: 'max_files', min: 1, max: 10000 },
  { key: 'max_file_bytes', min: 1, max: 100, scale: 1048576 },
  { key: 'max_total_bytes', min: 1, max: 1024, scale: 1048576 },
]
export const skillAlertKinds = ['content_changed', 'approval', 'unauthorized']
export function normalizeSkillAudit(value = {}) {
  return { enabled: true, alerts: true, check_mode: 'on_change', digest_cache_seconds: 300,
    status_refresh_seconds: 30, max_concurrency: 1, max_files: 256,
    max_file_bytes: 2097152, max_total_bytes: 8388608, ...value,
    alert_rules: { content_changed: 'alert', approval: 'alert', unauthorized: 'alert', ...value?.alert_rules } }
}
export function validSkillAudit(value) {
  return ['on_change', 'every_use'].includes(value.check_mode) && skillAuditLimits.every(({ key, min, max, scale = 1 }) =>
    Number.isInteger(value[key]) && value[key] >= min * scale && value[key] <= max * scale) &&
    value.max_file_bytes <= value.max_total_bytes && skillAlertKinds.every(key => ['record', 'alert'].includes(value.alert_rules[key]))
}
export function sameSkillAudit(a, b) {
  const left = normalizeSkillAudit(a), right = normalizeSkillAudit(b)
  return ['enabled', 'alerts', 'check_mode', ...skillAuditLimits.map(field => field.key)].every(key => left[key] === right[key]) &&
    skillAlertKinds.every(key => left.alert_rules[key] === right.alert_rules[key])
}
