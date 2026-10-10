<template>
  <a-tooltip v-if="hint" :title="hint" :overlay-inner-style="{ whiteSpace: 'pre-line', maxHeight: '70vh', overflowY: 'auto' }" :trigger="['hover', 'focus']">
    <span tabindex="0" class="sandbox-help">
      <slot>{{ display }}</slot>
      <QuestionCircleOutlined />
    </span>
  </a-tooltip>
  <span v-else><slot>{{ display }}</slot></span>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'

const props = defineProps({
  field: { type: String, required: true },
  value: { type: [String, Number, Array], default: null },
  label: { type: Boolean, default: false },
})
const { t } = useI18n()
const missing = computed(() => props.value == null || props.value === '' || props.value === '-')
const display = computed(() => {
  if (missing.value) return '-'
  if (props.field === 'runtime' && ['remote', 'docker'].includes(props.value)) return t(`skillDetail.${props.value}`)
  return props.value
})
// 术语和取值含义统一放在字段标签旁，值仅作展示。
const hint = computed(() => {
  if (!props.label) return ''
  if (['runtime', 'entrypoint', 'target', 'duration', 'command'].includes(props.field) && !missing.value) return ''
  const explanation = t(`skillDetail.sandboxHelp.${props.field}`)
  // 空数组是明确的无参数记录；字段缺失保留为信息缺失。
  if (props.field === 'args') {
    if (Array.isArray(props.value) && props.value.length === 0) return `${explanation}\n${t('skillDetail.sandboxHelp.argsEmpty')}`
    if (props.value == null) return `${explanation}\n${t('skillDetail.sandboxHelp.argsMissing')}`
  }
  return explanation
})
</script>

<style scoped>
.sandbox-help { display: inline-flex; align-items: center; gap: 4px; }
</style>
