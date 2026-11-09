<template>
  <a-spin :spinning="loading">
    <p>{{ t('clientDiagnostics.description') }}</p>
    <a-alert v-if="error" type="error" :message="error" show-icon>
      <template v-if="!ready" #action><a-button size="small" :disabled="busy" @click="load">{{ t('clientDiagnostics.retry') }}</a-button></template>
    </a-alert>
    <a-form layout="vertical">
      <a-form-item :label="t('clientDiagnostics.upload')">
        <a-select v-model:value="level" :options="options" :disabled="loading || busy || !ready || !hasAccess('clients:update')" style="width: 100%; max-width: 320px" />
        <div v-if="['DEBUG', 'INFO'].includes(level)">{{ t('clientDiagnostics.temporaryHelp') }}</div>
      </a-form-item>
    </a-form>
    <p v-if="ready">{{ t('clientDiagnostics.effective', { level: t(`clientDiagnostics.${effective}`) }) }}</p>
    <p v-if="ready && expiresAt">{{ t('clientDiagnostics.expires', { time: new Date(expiresAt).toLocaleString(locale, { hour12: false }) }) }}</p>
  </a-spin>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { getClientDiagnosticSettings, saveClientDiagnosticSettings } from '../api'
import { can as hasAccess } from '../access'
const props = defineProps({ clientId: { type: String, default: '' } })
const emit = defineEmits(['saved'])
const { t, locale } = useI18n()
const level = ref('ERROR'), effective = ref('ERROR'), saved = ref('ERROR'), expiresAt = ref(null), ready = ref(false), loading = ref(false), busy = ref(false), error = ref('')
const options = computed(() => [...(props.clientId ? ['INHERIT'] : []), 'OFF', 'ERROR', 'WARN', 'INFO', 'DEBUG'].map(value => ({ value, label: t(`clientDiagnostics.${value}`) })))
const canSave = computed(() => ready.value && !loading.value && !busy.value && (level.value !== saved.value || ['DEBUG', 'INFO'].includes(level.value)) && hasAccess('clients:update'))
let request = 0
async function load() {
  const current = ++request
  loading.value = true; ready.value = false; error.value = ''
  try {
    const data = await getClientDiagnosticSettings(props.clientId)
    if (current !== request) return
    level.value = saved.value = data.level; effective.value = data.effective_level; ready.value = true
    expiresAt.value = data.expires_at
  } catch { if (current === request) error.value = t('clientDiagnostics.failed') }
  finally { if (current === request) loading.value = false }
}
async function save() {
  if (!canSave.value) return
  busy.value = true; error.value = ''
  try {
    const data = await saveClientDiagnosticSettings(props.clientId, { level: level.value })
    saved.value = data.level; effective.value = data.effective_level
    expiresAt.value = data.expires_at
    message.success(t('clientDiagnostics.saved')); emit('saved')
  } catch { error.value = t('clientDiagnostics.saveFailed') }
  finally { busy.value = false }
}
watch(() => props.clientId, load, { immediate: true })
defineExpose({ busy, canSave, save })
</script>
