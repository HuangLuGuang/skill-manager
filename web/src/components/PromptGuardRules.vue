<template>
  <section>
    <div class="rules-heading">
      <strong>{{ t('promptGuard.ruleEditor.title') }}</strong>
      <a-space wrap>
      <a-button v-if="editable" size="small" type="primary" :disabled="loading || loadFailed || disabled || Boolean(operation)" @click="openRule({ custom: true, enabled: true, severity: 'HIGH', pattern: '', name: '', description: '', pattern_editable: true })">{{ t('promptGuard.ruleEditor.add') }}</a-button>
      <a-button size="small" :loading="loading" :disabled="loading || disabled || Boolean(operation)" @click="loadRules">{{ t('promptGuard.ruleEditor.refresh') }}</a-button></a-space>
    </div>
    <p class="rules-hint">{{ t('promptGuard.ruleEditor.hint') }}</p>
    <a-alert v-if="loadFailed" type="error" :message="t('promptGuard.ruleEditor.loadFailed')" show-icon />
    <a-table size="small" row-key="id" :columns="columns" :data-source="rules" :loading="loading" :scroll="{ x: 650 }" :pagination="{ pageSize: 10, showSizeChanger: false }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'"><span class="rule-name">{{ ruleName(record) }}</span></template>
        <template v-else-if="column.key === 'severity'">{{ t(`promptGuard.ruleEditor.severityValues.${record.severity}`) }}</template>
        <template v-else-if="column.key === 'enabled'"><a-tag :color="record.enabled ? 'green' : 'default'">{{ t(record.enabled ? 'promptGuard.ruleEditor.enabled' : 'promptGuard.ruleEditor.disabled') }}</a-tag></template>
        <template v-else-if="column.key === 'modified'">{{ t(record.custom ? 'promptGuard.ruleEditor.customRule' : (record.modified ? 'promptGuard.ruleEditor.custom' : 'promptGuard.ruleEditor.builtin')) }}</template>
        <template v-else-if="column.key === 'actions'"><a-button type="link" size="small" :disabled="disabled || loading || Boolean(operation)" @click="openRule(record)">{{ t(editable ? 'promptGuard.ruleEditor.edit' : 'promptGuard.ruleEditor.view') }}</a-button></template>
      </template>
    </a-table>
    <a-modal v-model:open="visible" :title="selected?.id ? ruleName(selected) : t('promptGuard.ruleEditor.add')" :width="760" :mask-closable="false" :closable="!operation" :keyboard="!operation" @cancel="closeRule">
      <a-form v-if="selected" layout="vertical">
        <template v-if="selected.custom">
          <a-form-item :label="t('promptGuard.ruleEditor.name')" :validate-status="nameError ? 'error' : undefined" :help="nameError || t('promptGuard.ruleEditor.nameHelp')"><a-input v-model:value="draft.name" :disabled="!editable || disabled || Boolean(operation)" /></a-form-item>
          <a-form-item :label="t('promptGuard.ruleEditor.description')" :validate-status="descriptionError ? 'error' : undefined" :help="descriptionError || t('promptGuard.ruleEditor.descriptionHelp')"><a-textarea v-model:value="draft.description" :rows="2" :disabled="!editable || disabled || Boolean(operation)" /></a-form-item>
        </template>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="t('promptGuard.ruleEditor.status')"><a-switch v-model:checked="draft.enabled" :disabled="!editable || disabled || Boolean(operation)" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="t('promptGuard.ruleEditor.severity')"><a-select v-model:value="draft.severity" :options="severityOptions" :disabled="!editable || disabled || Boolean(operation)" /></a-form-item></a-col>
        </a-row>
        <a-form-item v-if="selected.pattern_editable" :label="t('promptGuard.ruleEditor.pattern')" :validate-status="patternError ? 'error' : undefined" :help="patternError || t('promptGuard.ruleEditor.patternHelp')">
          <a-textarea v-model:value="draft.pattern" :rows="5" :disabled="!editable || disabled || Boolean(operation)" />
        </a-form-item>
        <p v-else class="rules-hint">{{ t(`promptGuard.ruleEditor.special.${selected.id}`) }}</p>
        <p class="rules-hint">{{ t('promptGuard.ruleEditor.severityHelp') }}</p>
        <a-alert v-if="editorError" type="error" :message="editorError" show-icon />
        <template v-if="editable">
          <a-form-item :label="t('promptGuard.ruleEditor.testText')"><a-textarea v-model:value="testText" :rows="3" :disabled="disabled || Boolean(operation)" /></a-form-item>
          <a-row :gutter="16">
            <a-col :span="12"><a-form-item :label="t('promptGuard.ruleEditor.mode')"><a-select v-model:value="testMode" :options="modeOptions" :disabled="disabled || Boolean(operation)" /></a-form-item></a-col>
            <a-col :span="12"><a-form-item :label="t('promptGuard.ruleEditor.source')"><a-select v-model:value="testSource" :options="sourceOptions" :disabled="disabled || Boolean(operation)" /></a-form-item></a-col>
          </a-row>
          <a-button :loading="operation === 'test'" :disabled="disabled || Boolean(operation)" @click="submit('test')">{{ t('promptGuard.ruleEditor.test') }}</a-button>
          <div v-if="testResult" class="rule-result">
            <a-alert v-if="testResult.error_code" type="error" :message="errorLabel(testResult.error_code)" show-icon />
            <template v-else>
              <p>{{ t('promptGuard.ruleEditor.result', { count: testResult.findings_count, action: t(`promptGuard.ruleEditor.actions.${testResult.action}`) }) }}</p>
              <pre v-for="(item, index) in testResult.findings" :key="index">{{ item.snippet }}</pre>
            </template>
          </div>
        </template>
      </a-form>
      <template #footer>
        <a-space wrap>
          <a-popconfirm v-if="editable && selected?.modified && !selected?.custom" :title="t('promptGuard.ruleEditor.restoreConfirm')" :disabled="disabled || Boolean(operation)" @confirm="submit('restore')">
            <a-button :loading="operation === 'restore'" :disabled="disabled || Boolean(operation)">{{ t('promptGuard.ruleEditor.restore') }}</a-button>
          </a-popconfirm>
          <a-popconfirm v-if="editable && selected?.custom && selected?.id" :title="t('promptGuard.ruleEditor.deleteConfirm')" :disabled="disabled || Boolean(operation)" @confirm="submit('delete')">
            <a-button danger :loading="operation === 'delete'" :disabled="disabled || Boolean(operation)">{{ t('promptGuard.ruleEditor.delete') }}</a-button>
          </a-popconfirm>
          <a-button :disabled="Boolean(operation)" @click="closeRule">{{ t('promptGuard.ruleEditor.close') }}</a-button>
          <a-button v-if="editable" type="primary" :loading="operation === 'save'" :disabled="disabled || Boolean(operation)" @click="submit('save')">{{ t('promptGuard.save') }}</a-button>
        </a-space>
      </template>
    </a-modal>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { createPromptGuardRule, testNewPromptGuardRule, listPromptGuardRules, savePromptGuardRule, restorePromptGuardRule, testPromptGuardRule } from '../api'

const props = defineProps({ editable: Boolean, disabled: Boolean })
const emit = defineEmits(['changed', 'busy'])
const { t, te } = useI18n()
const rules = ref([]), loading = ref(false), loadFailed = ref(false)
const visible = ref(false), selected = ref(null), operation = ref('')
const draft = reactive({ enabled: true, severity: 'HIGH', pattern: '', name: '', description: '' })
const testText = ref(''), testMode = ref('block'), testSource = ref('user'), testResult = ref(null)
const editorErrorCode = ref(''), editorErrorDetail = ref(''), attempted = ref(false)
const errorLabel = code => te(`promptGuard.errors.${String(code).split('.').pop()}`) ? t(`promptGuard.errors.${String(code).split('.').pop()}`) : t('promptGuard.ruleEditor.failed')
const editorError = computed(() => editorErrorCode.value ? errorLabel(editorErrorCode.value) : editorErrorDetail.value)
const ruleName = rule => rule.custom ? rule.name : t(`promptGuard.rules.${rule.id}`)
const nameError = computed(() => attempted.value && selected.value?.custom && (!draft.name.trim() || [...draft.name].length > 100) ? t('promptGuard.ruleEditor.nameHelp') : '')
const descriptionError = computed(() => attempted.value && selected.value?.custom && [...draft.description].length > 500 ? t('promptGuard.ruleEditor.descriptionHelp') : '')
const patternError = computed(() => attempted.value && selected.value?.pattern_editable && (!draft.pattern.trim() || draft.pattern.length > 2048) ? t('promptGuard.ruleEditor.patternLength') : '')
const columns = computed(() => [
  { key: 'name', title: t('promptGuard.ruleEditor.name') },
  { key: 'severity', title: t('promptGuard.ruleEditor.severity'), width: 100 },
  { key: 'enabled', title: t('promptGuard.ruleEditor.status'), width: 100 },
  { key: 'modified', title: t('promptGuard.ruleEditor.configuration'), width: 130 },
  { key: 'actions', title: t('promptGuard.ruleEditor.operation'), width: 100 },
])
const severityOptions = computed(() => ['LOW', 'MEDIUM', 'HIGH'].map(value => ({ value, label: t(`promptGuard.ruleEditor.severityValues.${value}`) })))
const modeOptions = computed(() => ['log', 'warn', 'block'].map(value => ({ value, label: t(`promptGuard.ruleEditor.modes.${value}`) })))
const sourceOptions = computed(() => ['user', 'tool', 'rag', 'file', 'web'].map(value => ({ value, label: t(`promptGuard.ruleEditor.sources.${value}`) })))
watch(() => [draft.enabled, draft.severity, draft.pattern, draft.name, draft.description, testText.value, testMode.value, testSource.value], () => {
  testResult.value = null
  editorErrorCode.value = ''
  editorErrorDetail.value = ''
})
const loadRules = async () => {
  if (loading.value) return
  loading.value = true
  loadFailed.value = false
  try { rules.value = await listPromptGuardRules() } catch { loadFailed.value = true } finally { loading.value = false }
}
const openRule = rule => {
  selected.value = rule
  Object.assign(draft, { enabled: rule.enabled, severity: rule.severity, pattern: rule.pattern, name: rule.name || '', description: rule.description || '' })
  testText.value = ''
  testResult.value = null
  editorErrorCode.value = ''
  editorErrorDetail.value = ''
  attempted.value = false
  visible.value = true
}
const closeRule = () => { if (!operation.value) visible.value = false }
const submit = async action => {
  if (operation.value || props.disabled || !props.editable) return
  attempted.value = !['restore', 'delete'].includes(action)
  if (attempted.value && (patternError.value || nameError.value || descriptionError.value)) return
  if (action === 'test' && (!testText.value.trim() || testText.value.length > 20000)) {
    editorErrorCode.value = 'prompt_guard.rule_test_text'
    return
  }
  operation.value = action
  emit('busy', true)
  editorErrorCode.value = ''
  editorErrorDetail.value = ''
  try {
    const config = { enabled: draft.enabled, severity: draft.severity, pattern: selected.value.pattern_editable ? draft.pattern : null }
    if (selected.value.custom) Object.assign(config, { name: draft.name, description: draft.description })
    if (action === 'test') {
      const payload = { config, text: testText.value, mode: testMode.value, source: testSource.value }
      testResult.value = selected.value.id ? await testPromptGuardRule(selected.value.id, payload) : await testNewPromptGuardRule(payload)
    } else {
      const updated = ['restore', 'delete'].includes(action) ? await restorePromptGuardRule(selected.value.id) : selected.value.id ? await savePromptGuardRule(selected.value.id, config) : await createPromptGuardRule(config)
      if (action === 'delete') rules.value = rules.value.filter(rule => rule.id !== updated.id)
      else if (!selected.value.id) rules.value.push(updated)
      else rules.value = rules.value.map(rule => rule.id === updated.id ? updated : rule)
      visible.value = false
      emit('changed')
      message.success(t('promptGuard.saved'))
    }
  } catch (error) {
    const data = error.response?.data
    editorErrorCode.value = data?.error_code || ''
    editorErrorDetail.value = typeof data?.detail === 'string' ? data.detail : t('promptGuard.ruleEditor.failed')
  } finally {
    operation.value = ''
    emit('busy', false)
  }
}
onMounted(loadRules)
</script>

<style scoped>
.rules-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.rule-name { overflow-wrap: anywhere; }
.rules-hint { color: var(--ant-color-text-secondary, #666); margin: 8px 0 12px; }
.rule-result { margin-top: 12px; }
.rule-result pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 180px; overflow: auto; }
</style>
