<template>
  <div class="protection-status">
    <a-button size="small" :loading="loading" :disabled="loading" @click="load">{{ t('clientGovernance.protection.refresh') }}</a-button>
    <a-alert v-if="failed" type="warning" show-icon :message="t('clientGovernance.protection.readFailed')" />
    <div v-for="name in names" :key="name" class="mode-row">
      <strong>{{ t(`clientGovernance.runtime.mode_${name}`) }}</strong>
      <span>{{ t('clientGovernance.protection.configured') }}: {{ !failed && state?.channels?.[name] ? mode(state.channels[name].target_mode, 'legacy') : mode(null, 'unknown') }}</span>
      <span>{{ t('clientGovernance.protection.effective') }}: {{ mode(current(name)?.mode, 'unknown') }}</span>
      <a-tag :color="!failed && state?.channels?.[name]?.applied ? 'green' : 'orange'">{{ t(`clientGovernance.protection.${reason(name)}`) }}</a-tag>
      <p v-if="current(name)?.state === 'failed'">{{ diagnostic(current(name).code) }}</p>
      <p v-else-if="failedTask && name === 'hooks' && !state?.channels?.[name]?.applied">{{ diagnostic(failedTask.error_code) }}</p>
    </div>
    <p>{{ t('clientGovernance.protection.savedHint') }}</p>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getClientRuntimeGovernance } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, channel: { type: String, default: '' } })
const { t, te } = useI18n()
const state = ref(null), loading = ref(false), failed = ref(false)
const names = computed(() => props.channel ? [props.channel] : ['hooks', 'system'])
const failedTask = computed(() => {
  const latest = state.value?.tasks?.find(task => task.payload?.policy_version === state.value?.target_version)
  return latest?.status === 'failed' ? latest : null
})
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
async function load() {
  if (loading.value || !props.clientId) return
  const run = ++sequence, id = props.clientId
  loading.value = true
  try { const next = await getClientRuntimeGovernance(id); if (run === sequence && id === props.clientId) { state.value = next; failed.value = false } }
  catch { if (run === sequence) failed.value = true }
  finally { if (run === sequence) loading.value = false }
}
watch(() => props.clientId, () => { sequence++; loading.value = false; state.value = null; void load() }, { immediate: true })
const timer = setInterval(() => void load(), 10000)
onBeforeUnmount(() => { sequence++; clearInterval(timer) })
</script>
<style scoped>
.protection-status { margin: 12px 0; padding: 12px; background: var(--color-fill-quaternary, #f6f8fb); border-radius: 8px; }
.mode-row { display: flex; align-items: center; gap: 8px 16px; flex-wrap: wrap; margin-top: 10px; }
.protection-status p { margin: 8px 0 0; color: #596579; }
</style>
