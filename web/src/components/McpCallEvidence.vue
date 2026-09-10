<template>
  <div style="margin: 16px 0">
    <a-button :loading="loading" :disabled="loading" @click="load">{{ t('mcpScan.evidence') }}</a-button>
    <a-modal v-model:open="open" :title="t('mcpScan.evidence')" :footer="null" width="min(1000px, 95vw)">
      <a-alert type="info" :message="t('mcpScan.evidenceHelp')" style="margin-bottom: 16px" />
      <pre style="max-height: 65vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere">{{ content }}</pre>
    </a-modal>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { getMcpScanCalls } from '../api'
const props = defineProps({ taskId: { type: String, required: true } })
const { t } = useI18n()
const loading = ref(false), open = ref(false), content = ref('')
watch(() => props.taskId, () => { content.value = ''; open.value = false })
async function load() {
  if (loading.value) return
  const id = props.taskId
  loading.value = true
  try { const result = await getMcpScanCalls(id); if (id === props.taskId) { content.value = JSON.stringify(result, null, 2); open.value = true } }
  catch { message.error(t('mcpScan.evidenceUnavailable')) }
  finally { loading.value = false }
}
</script>
