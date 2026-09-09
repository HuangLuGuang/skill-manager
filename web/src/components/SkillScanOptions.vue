<template>
  <div class="skill-scan-options">
    <a-tooltip v-for="option in options" :key="option.key" :title="tooltip(option)">
      <span>
        <a-checkbox
          :checked="option.key === 'use_behavioral' || Boolean(modelValue[option.key])"
          :disabled="option.key === 'use_behavioral' || disabled || loading || !available[option.key]"
          @change="event => $emit('update:modelValue', { ...modelValue, [option.key]: event.target.checked, use_behavioral: true })"
        >{{ $t(option.label) }}</a-checkbox>
      </span>
    </a-tooltip>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { rescanCapabilities } from '../utils/skillRescan'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  status: { type: Object, default: null },
  loading: Boolean,
  disabled: Boolean,
})
defineEmits(['update:modelValue'])
const { t } = useI18n()
const available = computed(() => rescanCapabilities(props.status))
const options = [
  { key: 'use_behavioral', label: 'scanOptions.rules', hint: 'scanOptions.rulesHint' },
  { key: 'use_skillspector', label: 'scanOptions.deepScan', hint: 'scanOptions.deepScanHint', unavailable: 'skillBatch.deepUnavailable' },
  { key: 'use_sandbox', label: 'scanOptions.sandbox', hint: 'scanOptions.sandboxHint', unavailable: 'skillBatch.sandboxUnavailable' },
  { key: 'use_llm', label: 'scanOptions.llm', hint: 'scanOptions.llmHint', unavailable: 'skillBatch.llmUnavailable' },
]
const tooltip = option => {
  if (option.key === 'use_behavioral') return t(option.hint)
  if (props.loading) return t('scanOptions.loading')
  if (!props.status || !Object.keys(props.status).length) return t('skillBatch.capabilitiesFailed')
  if (!available.value[option.key]) return t(option.unavailable)
  return t(option.hint, { model: props.status.llm_model || '' })
}
</script>

<style scoped>
.skill-scan-options {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
}
</style>
