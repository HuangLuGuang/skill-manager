<template>
  <a-space direction="vertical" style="width: 100%">
    <a-upload accept=".zip" :show-upload-list="false" :before-upload="upload" :disabled="busy">
      <a-button :loading="busy" :disabled="busy">{{ t('mcpScan.upload') }}</a-button>
    </a-upload>
    <a-input v-model:value="url" :placeholder="t('mcpScan.repository')" :disabled="busy" />
    <a-input v-model:value="revision" :placeholder="t('mcpScan.revision')" :disabled="busy" />
    <a-button :loading="busy" :disabled="busy || !url.trim()" @click="importRepository">{{ t('mcpScan.import') }}</a-button>
    <a-typography-text type="secondary">{{ t('mcpScan.sourceHint') }}</a-typography-text>
    <a-typography-text v-if="modelValue" style="overflow-wrap: anywhere">{{ t('mcpScan.snapshot') }}: {{ modelValue }}</a-typography-text>
  </a-space>
</template>
<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { uploadMcpScanSource, importMcpScanSource } from '../api'
defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'imported'])
const { t } = useI18n()
const busy = ref(false)
const url = ref('')
const revision = ref('')
async function run(action) {
  if (busy.value) return
  busy.value = true
  try {
    const result = await action()
    emit('update:modelValue', result.source_id)
    emit('imported', result)
  } catch { message.error(t('mcpScan.importFailed')) }
  finally { busy.value = false }
}
const upload = file => { void run(() => uploadMcpScanSource(file)); return false }
const importRepository = () => run(() => importMcpScanSource({ url: url.value.trim(), ref: revision.value.trim() || 'HEAD' }))
</script>
