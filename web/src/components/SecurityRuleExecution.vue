<template>
  <section class="rule-execution" :class="{ compact }" role="status" :aria-label="t('securityRules.execution.statusLabel')">
    <div class="execution-content">
      <div class="execution-heading"><a-badge :status="state === 'ready' ? 'success' : ['global', 'disabled'].includes(state) ? 'default' : 'warning'" /><strong>{{ title }}</strong></div>
      <p v-if="context.length" class="execution-context"><span v-for="text in context" :key="text">{{ text }}</span></p>
    </div>
    <a-space v-if="!compact" class="execution-actions" :size="8" wrap>
      <a-button size="small" :loading="refreshing" :disabled="refreshing" @click="$emit('refresh')"><template #icon><ReloadOutlined /></template>{{ t('securityRules.execution.refresh') }}</a-button>
      <a-button type="link" size="small" @click="$emit('configure')">{{ t('securityRules.execution.configure') }}</a-button>
    </a-space>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ReloadOutlined } from '@ant-design/icons-vue'
const props = defineProps({ execution: { type: Object, default: null }, compact: Boolean, refreshing: Boolean })
defineEmits(['configure', 'refresh'])
const { t } = useI18n()
const now = ref(Date.now() / 1000)
const timer = setInterval(() => { now.value = Date.now() / 1000 }, 10000)
onBeforeUnmount(() => clearInterval(timer))
const state = computed(() => {
  const value = props.execution
  if (!value) return 'unknown'
  if (value.scope === 'client' && value.state !== 'disabled' && now.value > value.valid_until) return 'unknown'
  return value.state
})
const mode = value => t('securityRules.execution.modes.' + (value || 'unknown'))
const title = computed(() => {
  if (state.value === 'global') return props.execution?.enabled === false ? t('securityRules.execution.states.disabled') : t('securityRules.execution.globalMode', { mode: mode(props.execution?.target_mode) })
  if (state.value === 'unknown' && props.execution?.target_mode) return t('securityRules.execution.awaitingDevice', { mode: mode(props.execution.target_mode) })
  return t('securityRules.execution.states.' + state.value)
})
const context = computed(() => {
  if (state.value === 'global') return props.compact ? [] : [t('securityRules.execution.deviceOverride')]
  const items = props.compact ? [] : [t('securityRules.execution.sources.' + (props.execution?.source || 'unknown'))]
  if (!['unknown', 'disabled'].includes(state.value) && props.execution?.target_mode && props.execution.target_mode !== props.execution.mode) items.push(t('securityRules.execution.targetMode', { mode: mode(props.execution.target_mode) }))
  if (state.value === 'audit') items.push(t('securityRules.execution.auditEffect'))
  if (state.value === 'disabled') items.push(t('securityRules.execution.awaitingDisable'))
  return items
})
</script>
<style scoped>
.rule-execution { display:flex;align-items:center;justify-content:space-between;gap:12px 24px;flex-wrap:wrap;margin:12px 0 16px;padding:12px 16px;border:1px solid #e6eaf0;border-radius:8px;background:#fafbfc; }
.execution-content { min-width:0;flex:1 1 260px; }
.execution-heading { display:flex;align-items:baseline;gap:8px;overflow-wrap:anywhere; }
.execution-heading strong { font-size:14px;font-weight:500;color:#243247; }
.execution-context { display:flex;flex-wrap:wrap;gap:4px 12px;margin:4px 0 0 14px;font-size:13px;line-height:1.6;color:#667085;overflow-wrap:anywhere; }
.execution-context span + span { border-inline-start:1px solid #d9dfe7;padding-inline-start:12px; }
.execution-actions { flex-shrink:0; }
.execution-actions :deep(.ant-btn-link) { padding-inline:4px; }
.compact { padding:10px 12px; }
@media(max-width:600px) { .execution-content { flex-basis:100%; }.execution-actions { margin-inline-start:14px; }.rule-execution { gap:10px; } }
</style>
