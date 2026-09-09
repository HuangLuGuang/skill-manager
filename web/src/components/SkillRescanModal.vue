<template>
  <a-modal
    :open="open"
    :width="720"
    :title="$t(skillName ? 'skillBatch.singleRescanTitle' : 'skillBatch.rescanTitle')"
    :ok-text="$t('skillBatch.submitRescan')"
    :cancel-text="$t('skillBatch.dismiss')"
    :confirm-loading="submitting"
    :ok-button-props="{ disabled: submitting || (mode === 'custom' && (loading || loadFailed)) }"
    :cancel-button-props="{ disabled: submitting }"
    :closable="!submitting"
    :mask-closable="!submitting"
    :keyboard="!submitting"
    @ok="submit"
    @cancel="$emit('update:open', false)"
  >
    <p>{{ skillName ? $t('skillBatch.singleRescanTarget', { name: skillName }) : $t('skillBatch.rescanCount', { count }) }}</p>
    <a-radio-group v-model:value="mode" :disabled="submitting" class="rescan-mode">
      <a-radio value="previous">{{ $t('skillBatch.previousOptions') }}</a-radio>
      <a-radio value="custom">{{ $t('skillBatch.customOptions') }}</a-radio>
    </a-radio-group>
    <p class="rescan-hint">{{ $t(mode === 'previous' ? 'skillBatch.previousOptionsHint' : 'skillBatch.customOptionsHint') }}</p>
    <template v-if="mode === 'custom'">
      <a-alert v-if="loadFailed" type="error" show-icon :message="$t('skillBatch.capabilitiesFailed')">
        <template #action><a-button size="small" :disabled="submitting" @click="loadStatus">{{ $t('skillBatch.retry') }}</a-button></template>
      </a-alert>
      <a-spin :spinning="loading">
        <SkillScanOptions v-model="selected" :status="status" :loading="loading" :disabled="submitting || loadFailed" class="rescan-options" />
      </a-spin>
    </template>
  </a-modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { getAgentManagerSystemStatus } from '../api'
import { rescanOptions } from '../utils/skillRescan'
import SkillScanOptions from './SkillScanOptions.vue'

const props = defineProps({ open: Boolean, submitting: Boolean, skillName: { type: String, default: '' }, count: { type: Number, default: 0 } })
const emit = defineEmits(['update:open', 'submit'])
const mode = ref('previous')
const selected = ref({})
const status = ref(null)
const loading = ref(false)
const loadFailed = ref(false)
let loadSequence = 0
const loadStatus = async () => {
  const sequence = ++loadSequence
  loading.value = true
  loadFailed.value = false
  try {
    const result = await getAgentManagerSystemStatus()
    if (sequence !== loadSequence) return
    status.value = result
    selected.value = rescanOptions('custom', selected.value, result)
  } catch {
    if (sequence !== loadSequence) return
    status.value = null
    loadFailed.value = true
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}
watch(() => props.open, open => {
  if (!open) {
    ++loadSequence
    return
  }
  mode.value = 'previous'
  selected.value = { use_behavioral: true, use_skillspector: false, use_sandbox: false, use_llm: false }
  status.value = null
  loadStatus()
})
const submit = () => {
  if (props.submitting || (mode.value === 'custom' && (loading.value || loadFailed.value))) return
  emit('submit', rescanOptions(mode.value, selected.value, status.value))
}
</script>

<style scoped>
.rescan-mode {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.rescan-options { padding: 12px 0; }
.rescan-hint { margin: 16px 0; color: #6b7280; }
</style>
