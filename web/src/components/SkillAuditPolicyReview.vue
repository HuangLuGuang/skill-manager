<template>
  <div class="skill-review">
    <p>{{ t('aidr.skillUse.policy.previewHelp') }}</p>
    <dl>
      <template v-for="key in ['enabled', 'alerts', 'check_mode', ...skillAuditLimits.map(field => field.key)]" :key="key"><dt>{{ label(key) }}</dt><dd>{{ format(before, key) }} → {{ format(after, key) }}</dd></template>
      <template v-for="kind in skillAlertKinds" :key="kind"><dt>{{ t('aidr.skillUse.policy.rule.' + kind) }}</dt><dd>{{ t('aidr.skillUse.policy.' + before.alert_rules[kind]) }} → {{ t('aidr.skillUse.policy.' + after.alert_rules[kind]) }}</dd></template>
    </dl>
    <p>{{ t('aidr.skillUse.policy.deliveryHelp') }}</p>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { normalizeSkillAudit, skillAuditLimits, skillAlertKinds } from '../skill-audit-policy'
const props = defineProps({ current: Object, target: Object })
const { t } = useI18n()
const before = computed(() => normalizeSkillAudit(props.current)), after = computed(() => normalizeSkillAudit(props.target))
const label = key => t(['enabled', 'alerts'].includes(key) ? 'aidr.skillUse.' + key : 'aidr.skillUse.policy.' + key)
function format(value, key) {
  if (['enabled', 'alerts'].includes(key)) return t(value[key] ? 'aidr.skillUse.policy.on' : 'aidr.skillUse.policy.off')
  if (key === 'check_mode') return t('aidr.skillUse.policy.' + value[key])
  return value[key] / (skillAuditLimits.find(field => field.key === key)?.scale || 1)
}
</script>
<style scoped>
.skill-review { overflow-wrap: anywhere; } dl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; } dt { color: #64748b; } dd { margin: 0; } p { font-size: 12px; color: #64748b; }
@media(max-width: 560px) { dl { grid-template-columns: minmax(0, 1fr); gap: 6px; } dd { margin-bottom: 8px; } }
</style>
