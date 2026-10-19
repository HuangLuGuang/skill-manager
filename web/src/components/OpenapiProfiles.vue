<template>
  <section class="profiles">
    <p class="muted">{{ t('openapiProfiles.help') }}</p>
    <div class="toolbar">
      <a-radio-group v-model:value="kind" button-style="solid" :disabled="saving">
        <a-radio-button value="skill">{{ t('openapiProfiles.skill') }}</a-radio-button>
        <a-radio-button value="agent">{{ t('openapiProfiles.agent') }}</a-radio-button>
      </a-radio-group>
      <a-button :loading="loading" :disabled="saving" @click="load">{{ t('externalAccess.refresh') }}</a-button>
      <a-button v-if="can('external_access:create')" type="primary" :disabled="loading || !revision || !!loadError" @click="openEditor()">{{ t('openapiProfiles.create') }}</a-button>
    </div>
    <a-alert v-if="loadError" type="error" show-icon :message="errorText(loadError)" />
    <a-table :columns="columns" :data-source="items" row-key="profile_id" :loading="loading" :scroll="{ x: 1100 }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'platform_ids'"><div v-for="id in record.platform_ids" :key="id">{{ partnerName(id) }}</div></template>
        <template v-else-if="column.key === 'checks'"><a-tag v-for="check in checks(record)" :key="check">{{ kind === 'skill' ? t(`openapiProfiles.modules.${check}`) : t(`assetLifecycle.ruleNames.${check}`) }}</a-tag></template>
        <template v-else-if="column.key === 'actions'"><a-button type="link" :disabled="loading || !!loadError" @click="openEditor(record)">{{ t(can('external_access:update') ? 'externalAccess.edit' : 'openapiProfiles.view') }}</a-button></template>
      </template>
    </a-table>
    <a-modal v-model:open="editorOpen" :title="t(readOnly ? 'openapiProfiles.view' : editing ? 'openapiProfiles.edit' : 'openapiProfiles.create')" width="min(760px, 96vw)"
      :confirm-loading="saving" :ok-button-props="{ disabled: saving }" :cancel-button-props="{ disabled: saving }" :closable="!saving" :mask-closable="false"
      :footer="readOnly ? null : undefined" :ok-text="t('externalAccess.save')" @ok="save">
      <a-form layout="vertical">
        <a-form-item :label="t('openapiProfiles.id')" required><a-input v-model:value="form.profile_id" :disabled="editing || readOnly || saving" /></a-form-item>
        <a-form-item :label="t('openapiProfiles.version')" :extra="t('openapiProfiles.versionHelp')"><span class="version">{{ form.version || t('openapiProfiles.generated') }}</span></a-form-item>
        <a-form-item :label="t('externalAccess.partners')" required :extra="t('openapiProfiles.partnersHelp')"><a-select v-model:value="form.platform_ids" mode="multiple" :options="partnerOptions" :disabled="readOnly || saving" /></a-form-item>
        <template v-if="kind === 'skill'">
          <a-form-item :label="t('openapiProfiles.checks')" :extra="t('openapiProfiles.modulesHelp')">
            <div class="switches"><span>{{ t('openapiProfiles.modules.scanner') }} · {{ t('externalAccess.enabled') }}</span>
              <a-checkbox v-for="name in moduleNames" :key="name" v-model:checked="form[`use_${name}`]" :disabled="readOnly || saving">{{ t(`openapiProfiles.modules.${name}`) }}</a-checkbox>
            </div>
          </a-form-item>
          <a-form-item :label="t('openapiProfiles.judgement_mode')" required><a-select v-model:value="form.judgement_mode" :options="choices('modes', ['balanced', 'strict', 'permissive'])" :disabled="readOnly || saving" /></a-form-item>
        </template>
        <template v-else>
          <a-form-item :label="t('openapiProfiles.policy_id')" required><a-select v-model:value="form.policy_id" show-search option-filter-prop="label" :options="policyOptions" :disabled="readOnly || saving" /></a-form-item>
          <a-form-item :label="t('openapiProfiles.evaluation_model')" required><a-select v-model:value="form.evaluation_model" show-search option-filter-prop="label" :options="modelOptions" :disabled="readOnly || saving" /></a-form-item>
          <a-form-item :label="t('openapiProfiles.checks')" required><a-select v-model:value="form.skills" mode="multiple" :options="skillOptions" :disabled="readOnly || saving" /></a-form-item>
          <div class="form-grid">
            <a-form-item :label="t('openapiProfiles.conversation_mode')" required><a-select v-model:value="form.conversation_mode" :options="choices('conversations', ['single_turn', 'multi_turn'])" :disabled="readOnly || saving" /></a-form-item>
            <a-form-item :label="t('openapiProfiles.language')" required><a-select v-model:value="form.language" :options="choices('languages', ['zh', 'en'])" :disabled="readOnly || saving" /></a-form-item>
          </div>
          <a-form-item :label="t('openapiProfiles.approval_id')" :extra="t('openapiProfiles.approvalHelp')"><a-input v-model:value="form.approval_id" :disabled="readOnly || saving" /></a-form-item>
        </template>
        <a-form-item :label="t('openapiProfiles.malicious_rule_ids')" :extra="t('openapiProfiles.rulesHelp')"><a-textarea v-model:value="rules" :rows="4" :disabled="readOnly || saving" /></a-form-item>
        <a-alert v-if="formError" type="error" show-icon :message="errorText(formError)" :description="fieldErrorText" />
      </a-form>
    </a-modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { getOpenapiProfileOptions, listOpenapiProfiles, createOpenapiProfile, updateOpenapiProfile } from '../api'

const props = defineProps({ partners: { type: Array, default: () => [] } })
const { t, te } = useI18n()
const kind = ref('skill'), items = ref([]), revision = ref(''), options = ref({ skills: [], policies: [], models: [] })
const loading = ref(false), saving = ref(false), editorOpen = ref(false), editing = ref(false)
const loadError = ref(''), formError = ref(''), errorFields = ref([]), rules = ref(''), editRevision = ref('')
const form = reactive({})
const moduleNames = ['skillspector', 'behavioral', 'sandbox', 'llm']
let sequence = 0
const readOnly = computed(() => editing.value && !can('external_access:update'))
const partnerName = id => props.partners.find(p => p.platform_id === id)?.name || id
const partnerOptions = computed(() => [...new Set([...props.partners.map(p => p.platform_id), ...(form.platform_ids || [])])].map(value => ({ value, label: `${partnerName(value)} (${value})` })))
const withCurrent = (values, current) => current && !values.some(o => o.value === current) ? [...values, { value: current, label: `${current} (${t('openapiProfiles.unavailable')})`, disabled: true }] : values
const policyOptions = computed(() => withCurrent(options.value.policies.map(p => ({ ...p, disabled: !p.enabled })), form.policy_id))
const modelOptions = computed(() => withCurrent(options.value.models, form.evaluation_model))
const skillOptions = computed(() => options.value.skills.map(value => ({ value, label: t(`assetLifecycle.ruleNames.${value}`) })))
const choices = (group, values) => values.map(value => ({ value, label: t(`openapiProfiles.${group}.${value}`) }))
const checks = row => kind.value === 'skill' ? ['scanner', ...moduleNames.filter(key => row[`use_${key}`])] : row.skills
const columns = computed(() => ['profile_id', 'version', 'platform_ids', 'checks', 'actions'].map((key, i) => ({ key, dataIndex: key,
  title: t(['openapiProfiles.id', 'openapiProfiles.version', 'externalAccess.partners', 'openapiProfiles.checks', 'externalAccess.actions'][i]), width: [190, 270, 200, 330, 100][i] })))
const errorCode = error => error?.response?.data?.error_code?.replace(/^openapi_profiles\./, '') || 'failed'
const errorText = code => t(te(`openapiProfiles.errors.${code}`) ? `openapiProfiles.errors.${code}` : 'openapiProfiles.errors.failed')
const fieldErrorText = computed(() => errorFields.value.map(key => te(`openapiProfiles.${key}`) ? t(`openapiProfiles.${key}`) : key).join(', '))

async function load() {
  const current = ++sequence
  loading.value = true
  loadError.value = ''
  try {
    const [result, choices] = await Promise.all([listOpenapiProfiles(kind.value), getOpenapiProfileOptions()])
    if (current !== sequence) return
    items.value = result.items
    revision.value = result.revision
    options.value = choices
  } catch (error) {
    if (current === sequence) loadError.value = errorCode(error)
  } finally { if (current === sequence) loading.value = false }
}
function openEditor(row) {
  if (saving.value) return
  editing.value = !!row
  Object.keys(form).forEach(key => delete form[key])
  Object.assign(form, row ? JSON.parse(JSON.stringify(row)) : {
    profile_id: '', version: '', platform_ids: [], malicious_rule_ids: [],
    ...(kind.value === 'skill' ? { use_behavioral: false, use_llm: false, use_sandbox: true, use_skillspector: false, judgement_mode: 'balanced' }
      : { policy_id: undefined, evaluation_model: undefined, skills: [], conversation_mode: 'single_turn', language: 'zh', approval_id: null }),
  })
  rules.value = form.malicious_rule_ids.join('\n')
  editRevision.value = revision.value
  formError.value = ''
  errorFields.value = []
  editorOpen.value = true
}
async function save() {
  if (saving.value || readOnly.value) return
  formError.value = ''
  errorFields.value = []
  if (!form.profile_id?.trim() || form.profile_id !== form.profile_id.trim() || Array.from(form.profile_id).length > 128) errorFields.value.push('profile_id')
  if (!form.platform_ids.length) errorFields.value.push('platform_ids')
  if (kind.value === 'agent') {
    if (!form.policy_id) errorFields.value.push('policy_id')
    if (!form.evaluation_model) errorFields.value.push('evaluation_model')
    if (!form.skills.length) errorFields.value.push('skills')
  }
  const ruleIds = rules.value.split('\n').filter(value => value !== '')
  if (new Set(ruleIds).size !== ruleIds.length || ruleIds.some(value => !value.trim() || value !== value.trim())) errorFields.value.push('malicious_rule_ids')
  if (errorFields.value.length) { formError.value = 'invalid_fields'; return }
  const { profile_id, version, ...settings } = form
  settings.malicious_rule_ids = ruleIds
  if (kind.value === 'agent' && !settings.approval_id) settings.approval_id = null
  saving.value = true
  try {
    const result = await (editing.value ? updateOpenapiProfile : createOpenapiProfile)(kind.value, { profile_id, revision: editRevision.value, settings })
    items.value = result.items
    revision.value = result.revision
    editorOpen.value = false
    message.success(t('openapiProfiles.saved'))
  } catch (error) {
    formError.value = errorCode(error)
    errorFields.value = error?.response?.data?.error_params?.fields || []
  } finally { saving.value = false }
}
watch(kind, () => { items.value = []; revision.value = ''; editorOpen.value = false; load() })
onMounted(load)
onBeforeUnmount(() => { sequence += 1 })
</script>

<style scoped>
.muted { color: var(--ant-color-text-secondary, #777); }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 16px; }
.switches { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.switches :deep(.ant-checkbox-wrapper) { margin-inline-start: 0; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.version, .profiles :deep(td) { overflow-wrap: anywhere; }
.profiles :deep(.ant-tag) { white-space: normal; margin-bottom: 6px; }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; gap: 0; } }
</style>
