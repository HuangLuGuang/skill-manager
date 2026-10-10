<template>
  <div class="model-actions">
    <a-space wrap>
      <a-button v-if="can('clients:execute')" :disabled="blocked" :title="disabledReason" @click="open"><SettingOutlined />{{ tr('modelChange') }}</a-button>
      <a-button v-if="can('clients:execute') && state.change_id" :loading="busy === 'verify_model_config'" :disabled="blocked" @click="operate('verify_model_config')">{{ tr('modelVerify') }}</a-button>
      <a-popconfirm v-if="can('clients:execute') && state.can_restore" :title="tr('restoreReview')" :disabled="blocked" @confirm="operate('restore_model_config')"><a-button :disabled="blocked" :loading="busy === 'restore_model_config'">{{ tr('modelRestore') }}</a-button></a-popconfirm>
    </a-space>
    <p v-if="disabledReason" class="muted">{{ disabledReason }}</p>
    <a-modal v-model:open="visible" :title="tr('modelChange')" :ok-text="t('clientModelConfig.apply')" :confirm-loading="!!busy" :ok-button-props="{ disabled: blocked || !form.model || catalogLoading || loading }" :cancel-button-props="{ disabled: !!busy }" :closable="!busy" :mask-closable="!busy" :keyboard="!busy" @ok="submit">
      <p>{{ tr('actionScope', { client: client.name, agent: agent.agent_type, id: agent.local_agent_id }) }}</p>
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <a-spin :spinning="loading">
        <a-form layout="vertical">
          <a-form-item :label="t('externalModel.source')"><a-radio-group v-model:value="form.source" @change="changeSource"><a-radio-button value="internal">{{ t('externalModel.internal') }}</a-radio-button><a-radio-button value="external_gateway" :disabled="!externalAllowed">{{ t('externalModel.external') }}</a-radio-button></a-radio-group></a-form-item>
          <template v-if="form.source === 'external_gateway'"><a-alert type="info" :message="t('externalModel.prepareHint')" /><a-button :disabled="catalogLoading || !!busy" :loading="catalogLoading" @click="prepareCatalog">{{ t(catalog ? 'externalModel.refresh' : 'externalModel.prepare') }}</a-button></template>
          <a-form-item :label="tr('configuredModel')" required><a-select v-model:value="form.model" show-search option-filter-prop="label" :options="modelOptions" :loading="catalogLoading" :disabled="!!busy" /></a-form-item>
          <p v-if="!modelOptions.length" class="muted">{{ tr('noModels') }}</p>
          <a-alert v-if="agent.capabilities?.model_config_contract?.parameter_status === 'version_unverified'" type="warning" :message="t('clientModelConfig.versionUnverified')" />
          <a-form-item v-for="(field, key) in parameters" :key="key" :label="t(`clientModelConfig.parameters.${key}`)"><a-select v-if="field.enum" v-model:value="form.parameters[key]" allow-clear :options="field.enum.map(value => ({ label: value, value }))" :disabled="!!busy" /><a-input-number v-else v-model:value="form.parameters[key]" :min="field.min" :max="field.max" :precision="field.type === 'integer' ? 0 : undefined" :disabled="!!busy" /></a-form-item>
          <a-alert type="info" :message="t('clientModelConfig.effect')" /><details><summary>{{ tr('preview') }}</summary><pre>{{ JSON.stringify({ path: beforeState.config_path, before: { model: beforeState.model, parameters: beforeState.parameters }, after: { model: form.model, parameters: { ...beforeState.parameters, ...Object.fromEntries(Object.entries(form.parameters).filter(([, value]) => value != null)) } } }, null, 2) }}</pre></details>
        </a-form>
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { SettingOutlined } from '@ant-design/icons-vue'
import { can } from '../access'
import { createClientTask, listModelEndpoints, prepareExternalModelCatalog } from '../api'
import { modelLabel } from '../utils/modelLabels'
const props = defineProps({ client: { type: Object, required: true }, agent: { type: Object, required: true }, pending: Boolean })
const emit = defineEmits(['created'])
const { t } = useI18n(), tr = (key, values) => t(`agentWorkspace.${key}`, values || {})
const visible = ref(false), busy = ref(''), loading = ref(false), catalogLoading = ref(false), error = ref(''), models = ref([]), externalModels = ref([]), catalog = ref(null), beforeState = ref({})
const form = reactive({ source: 'internal', model: undefined, parameters: {}, expected_revision: undefined })
const state = computed(() => props.agent.capabilities?.model_config_state || {})
const parameters = computed(() => props.agent.capabilities?.model_config_contract?.parameters || {})
const routing = computed(() => props.client.model_routing || {})
const externalAllowed = computed(() => Boolean(routing.value.external_gateway_enabled && routing.value.external_gateway_id && props.agent.managed_agent_id))
const disabledReason = computed(() => !props.agent.capabilities?.model_config_auto_apply ? t('clientModelConfig.unsupportedAgent') : props.pending ? t('clientGovernance.actionPending') : '')
const blocked = computed(() => !can('clients:execute') || !!busy.value || Boolean(disabledReason.value))
const modelOptions = computed(() => (form.source === 'external_gateway' ? externalModels.value : models.value).map(model => ({ value: model.name || model.id, label: modelLabel(model) })))
let alive = true, catalogRequest = 0
const failure = cause => typeof cause.response?.data?.detail === 'string' ? cause.response.data.detail : tr('failed')
function changeSource() { catalogRequest++; catalogLoading.value = false; form.model = undefined; externalModels.value = []; catalog.value = null; error.value = '' }
async function open() {
  if (blocked.value || loading.value) return
  form.source = externalAllowed.value ? 'external_gateway' : 'internal'; form.model = undefined; form.parameters = {}
  beforeState.value = JSON.parse(JSON.stringify(state.value)); form.expected_revision = state.value.revision
  catalog.value = null; externalModels.value = []; error.value = ''; visible.value = true
  if (!can('models:view')) return
  loading.value = true
  try { const data = await listModelEndpoints(); if (alive) models.value = data.filter(model => model.enabled) }
  catch (cause) { if (alive) error.value = failure(cause) }
  finally { if (alive) loading.value = false }
}
async function prepareCatalog() {
  if (catalogLoading.value || busy.value || !externalAllowed.value || !can('clients:execute')) return
  const request = ++catalogRequest; catalogLoading.value = true; error.value = ''
  try {
    const data = await prepareExternalModelCatalog(props.client.client_id, { local_agent_id: props.agent.local_agent_id, agent_type: props.agent.agent_type, managed_agent_id: props.agent.managed_agent_id })
    if (!alive || request !== catalogRequest) return
    catalog.value = data; externalModels.value = data.models || []; form.model = undefined
  } catch (cause) { if (alive && request === catalogRequest) error.value = failure(cause) }
  finally { if (alive && request === catalogRequest) catalogLoading.value = false }
}
async function operate(operation, payload = {}) {
  if (blocked.value) return
  busy.value = operation; error.value = ''
  const id = props.client.client_id
  try {
    const task = await createClientTask(id, { task_type: operation, payload: { agent_type: props.agent.agent_type, local_agent_id: props.agent.local_agent_id, change_id: state.value.change_id, expected_revision: state.value.revision, ...payload } })
    if (!alive) return
    visible.value = false; message.success(tr('created')); emit('created', { clientId: id, taskId: task.id })
  } catch (cause) { if (alive) { error.value = failure(cause); if (!visible.value) message.error(error.value) } }
  finally { if (alive) busy.value = '' }
}
function submit() {
  if (!form.model || catalogLoading.value || loading.value || !modelOptions.value.some(model => model.value === form.model)) return
  operate('apply_model_config', { managed_agent_id: props.agent.managed_agent_id, source: form.source, gateway_id: form.source === 'external_gateway' ? catalog.value?.gateway?.id || routing.value.external_gateway_id : null, model: form.model, parameters: Object.fromEntries(Object.entries(form.parameters).filter(([, value]) => value != null)), expected_revision: form.expected_revision })
}
onBeforeUnmount(() => { alive = false; catalogRequest++ })
</script>
<style scoped>
.model-actions { margin-top: 18px; }.muted { color: #7b8797; font-size: 12px; margin-top: 8px; }pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 14px; background: #f7f9fc; }details { margin-top: 15px; }.ant-alert { margin: 12px 0; }.ant-form { margin-top: 16px; }.model-actions :deep(.ant-btn) { white-space: normal; height: auto; min-height: 32px; }
</style>
