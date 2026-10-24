<template>
  <section class="skill-policy">
    <a-space wrap>
      <a-checkbox :checked="modelValue.enabled" :disabled="disabled" @update:checked="set('enabled', $event)">{{ t('aidr.skillUse.enabled') }}</a-checkbox>
      <a-checkbox :checked="modelValue.alerts" :disabled="inactive" @update:checked="set('alerts', $event)">{{ t('aidr.skillUse.alerts') }}</a-checkbox>
    </a-space>
    <p class="muted">{{ t('aidr.skillUse.policyHelp') }}</p>
    <div class="field-grid">
      <label class="wide"><span>{{ t('aidr.skillUse.policy.check_mode') }}</span><a-select :value="modelValue.check_mode" :disabled="inactive" :aria-label="t('aidr.skillUse.policy.check_mode')" :options="modes" @update:value="set('check_mode', $event)" /></label>
      <label v-for="field in skillAuditLimits.slice(0, 2)" :key="field.key"><span>{{ t('aidr.skillUse.policy.' + field.key) }}</span><a-input-number :value="modelValue[field.key]" :min="field.min" :max="field.max" :precision="0" :disabled="inactive || (field.key === 'digest_cache_seconds' && modelValue.check_mode === 'every_use')" :aria-label="t('aidr.skillUse.policy.' + field.key)" @update:value="set(field.key, $event)" /></label>
    </div>
    <p class="muted">{{ t('aidr.skillUse.policy.frequencyHelp') }}</p>
    <details class="advanced"><summary>{{ t('aidr.skillUse.policy.resources') }}</summary>
      <div class="field-grid"><label v-for="field in skillAuditLimits.slice(2)" :key="field.key"><span>{{ t('aidr.skillUse.policy.' + field.key) }}</span><a-input-number :value="modelValue[field.key] == null ? null : modelValue[field.key] / (field.scale || 1)" :min="field.min" :max="field.max" :precision="0" :disabled="inactive" :aria-label="t('aidr.skillUse.policy.' + field.key)" @update:value="set(field.key, $event == null ? null : $event * (field.scale || 1))" /></label></div>
      <p class="muted">{{ t('aidr.skillUse.policy.resourceHelp') }}</p>
    </details>
    <p v-if="!validSkillAudit(modelValue)" class="error" role="alert">{{ t('aidr.skillUse.policy.invalid') }}</p>
    <h5>{{ t('aidr.skillUse.policy.rules') }}</h5>
    <div v-for="kind in skillAlertKinds" :key="kind" class="rule"><span>{{ t('aidr.skillUse.policy.rule.' + kind) }}</span><a-select :value="modelValue.alert_rules[kind]" :disabled="inactive || !modelValue.alerts" :aria-label="t('aidr.skillUse.policy.rule.' + kind)" :options="actions" @update:value="set('alert_rules', { ...modelValue.alert_rules, [kind]: $event })" /></div>
    <p v-if="!modelValue.alerts" class="muted">{{ t('aidr.skillUse.policy.alertsOff') }}</p>
    <p class="muted">{{ t('aidr.skillUse.policy.pendingHelp') }}</p>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { skillAuditLimits, skillAlertKinds, validSkillAudit } from '../skill-audit-policy'
const props = defineProps({ modelValue: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const inactive = computed(() => props.disabled || !props.modelValue.enabled)
const modes = computed(() => ['on_change', 'every_use'].map(value => ({ value, label: t('aidr.skillUse.policy.' + value) })))
const actions = computed(() => ['record', 'alert'].map(value => ({ value, label: t('aidr.skillUse.policy.' + value) })))
function set(key, value) { emit('update:modelValue', { ...props.modelValue, [key]: value }) }
</script>
<style scoped>
.skill-policy { margin: 12px 0; min-width: 0; }
h5 { margin: 20px 0 8px; font-size: 14px; }
.muted { color: #64748b; font-size: 12px; line-height: 1.6; margin: 10px 0; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; margin: 12px 0; }
.field-grid label { display: flex; flex-direction: column; gap: 8px; min-width: 0; } .wide { grid-column: 1 / -1; }
.ant-select, .ant-input-number { width: 100%; min-width: 0; }
.advanced { padding: 12px 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; } summary { cursor: pointer; }
.rule { display: grid; grid-template-columns: minmax(0, 1fr) 160px; gap: 12px; align-items: center; margin: 12px 0; }
.error { color: #b42318; }
@media(max-width: 560px) { .field-grid, .rule { grid-template-columns: minmax(0, 1fr); } }
</style>
