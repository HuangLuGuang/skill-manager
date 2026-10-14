import { useI18n } from 'vue-i18n'

export function useSkillAuditLabels() {
  const { t, te, locale } = useI18n()
  const tr = (key, args) => t('aidr.skillUse.' + key, args)
  const ui = (key, args) => tr('review.' + key, args)
  return {
    tr, ui,
    name: item => item.skill.name || item.certification?.name || tr(item.skill.path ? 'fileRecord' : 'unknownName'),
    time: value => value ? new Date(value).toLocaleString(locale.value) : '—',
    phase: item => tr(item.stage === 'host_confirmed' ? item.skill.behavior === 'invocation' ? 'loaded' : 'read' : item.stage === 'unknown' ? 'outcomeUnconfirmed' : item.stage),
    tone: status => ['verified','verified_content'].includes(status) ? 'green' : status === 'pending' ? 'orange' : 'red',
    outcomeTone: status => ['denied','failed'].includes(status) ? 'red' : status === 'host_confirmed' ? 'green' : undefined,
    reason: key => !key ? tr('unknown') : te('aidr.skillUse.' + key) ? tr(key) : te('aidr.skillUse.review.reasons.' + key) ? ui('reasons.' + key) : tr('unknown'),
    taskError: code => te('aidr.skillUse.review.taskErrors.' + code) ? ui('taskErrors.' + code) : ui('observationFailed'),
  }
}
