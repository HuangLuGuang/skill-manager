<template>
  <div class="protection-status">
    <a-alert v-if="failed" type="warning" show-icon :message="t('clientGovernance.protection.readFailed')" />
    <div class="status-content">
    <div class="status-modes">
    <div v-for="name in names" :key="name" class="mode-row">
      <div class="mode-title"><strong>{{ t(`clientGovernance.runtime.mode_${name}`) }}</strong><a-tag :color="!failed && state?.channels?.[name]?.applied ? current(name)?.mode === 'intercept' ? 'green' : 'default' : 'orange'">{{ t(`clientGovernance.protection.${reason(name)}`) }}</a-tag></div>
      <div class="mode-value"><span>{{ t('clientGovernance.protection.configured') }}</span><strong>{{ !failed && state?.channels?.[name] ? mode(state.channels[name].target_mode, 'legacy') : mode(null, 'unknown') }}</strong></div>
      <div class="mode-value"><span>{{ t('clientGovernance.protection.effective') }}</span><strong>{{ mode(current(name)?.mode, 'unknown') }}</strong></div>
      <p v-if="current(name)?.state === 'failed'">{{ diagnostic(current(name).code) }}</p>
      <p v-else-if="failedTask && name === 'hooks' && !state?.channels?.[name]?.applied">{{ diagnostic(failedTask.error_code) }}</p>
      <a-button v-if="name === 'hooks' && canRetry" size="small" :loading="retrying" :disabled="retrying || loading" @click="retryPolicy">{{ t('clientGovernance.protection.retryPolicy') }}</a-button>
    </div>
    </div>
    <a-button class="status-refresh" size="small" :loading="loading" :disabled="loading" @click="load">{{ t('clientGovernance.protection.refresh') }}</a-button>
    </div>
    <p>{{ t('clientGovernance.protection.savedHint') }}</p>
    <a-alert v-if="retryError" type="error" show-icon :message="retryError" />
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getClientRuntimeGovernance, retryClientTask } from '../api'
import { can } from '../access'
const props = defineProps({ clientId: { type: String, required: true }, channel: { type: String, default: '' } })
const { t, te } = useI18n()
const state = ref(null), loading = ref(false), failed = ref(false)
const retrying = ref(false), retryError = ref('')
const names = computed(() => props.channel ? [props.channel] : ['hooks', 'system'])
const failedTask = computed(() => {
  const latest = state.value?.tasks?.find(task => task.payload?.action === 'reconcile' && task.payload?.policy_version === state.value?.target_version)
  return latest?.status === 'failed' ? latest : null
})
const canRetry = computed(() => can('clients:execute') && !failed.value && state.value?.supports_tasks && failedTask.value && !state.value?.channels?.hooks?.applied && !state.value?.tasks?.some(task => ['pending', 'running'].includes(task.status)))
const mode = (value, fallback) => t(`clientGovernance.runtime.mode_${value || fallback}`)
const current = name => !failed.value && !state.value?.channels?.[name]?.stale ? state.value?.channels?.[name]?.report : null
const diagnostic = code => te(`agentRuntimeGovernance.codes.${code}`) ? t(`agentRuntimeGovernance.codes.${code}`) : code
function reason(name) {
  if (failed.value || !state.value?.channels?.[name]) return 'unknown'
  const channel = state.value?.channels?.[name]
  if (channel?.health?.state === 'mode_upgrade_required') return 'upgrade'
  if (channel?.target_enabled === false) return 'disabled'
  if (channel?.applied) return 'applied'
  if (current(name)?.state === 'failed') return 'failed'
  if (name === 'hooks' && failedTask.value) return 'failed'
  if (current(name)?.state === 'stopped') return 'stopped'
  return 'pending'
}
let sequence = 0
async function retryPolicy() {
  if (retrying.value || loading.value || !canRetry.value) return
  const id = props.clientId, task = failedTask.value
  retrying.value = true; retryError.value = ''
  try {
    await retryClientTask(id, task.id)
    if (id === props.clientId) await load()
  } catch (cause) {
    if (id === props.clientId) {
      const code = cause.response?.data?.error_code
      retryError.value = code && te(`agentRuntimeGovernance.codes.${code}`) ? diagnostic(code) : t('clientGovernance.taskFailed')
    }
  } finally { retrying.value = false }
}
async function load() {
  if (loading.value || !props.clientId) return
  const run = ++sequence, id = props.clientId
  loading.value = true
  try { const next = await getClientRuntimeGovernance(id); if (run === sequence && id === props.clientId) { state.value = next; failed.value = false } }
  catch { if (run === sequence) failed.value = true }
  finally { if (run === sequence) loading.value = false }
}
watch(() => props.clientId, () => { sequence++; loading.value = false; retryError.value = ''; state.value = null; void load() }, { immediate: true })
const timer = setInterval(() => void load(), 10000)
onBeforeUnmount(() => { sequence++; clearInterval(timer) })
</script>
<style scoped>
.protection-status { margin: 0 0 12px; padding: 16px 18px; background: var(--color-fill-quaternary, #f6f8fb); border: 1px solid #e7edf4; border-radius: 10px; }
.status-content { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.status-modes { flex: 1 1 440px; min-width: 0; }
.status-refresh { flex: 0 0 auto; margin-left: auto; }
.mode-row { display: grid; grid-template-columns: minmax(180px, 1.3fr) repeat(2, minmax(120px, 1fr)); align-items: center; gap: 8px 24px; }
.mode-title { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.mode-value { display: grid; gap: 4px; font-size: 13px; }
.mode-value > span { color: #718198; font-size: 12px; }
.mode-value > strong { color: #304561; font-weight: 500; }
.mode-row > p { grid-column: 1 / -1; }
.mode-row + .mode-row { margin-top: 14px; padding-top: 14px; border-top: 1px solid #e0e7f0; }
@media (max-width: 650px) { .mode-row { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; } .mode-title { grid-column: 1 / -1; } }
.mode-row :deep(.ant-tag) { margin-inline-end: 0; white-space: normal; }
.protection-status > :deep(.ant-alert) { margin-bottom: 10px; }
.protection-status p { margin: 6px 0 0; color: #596579; font-size: 13px; overflow-wrap: anywhere; }
</style>
