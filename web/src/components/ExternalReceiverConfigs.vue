<template>
  <section>
    <p class="muted">{{ ct('help') }}</p>
    <div class="toolbar">
      <a-button v-if="can('external_access:create')" type="primary" @click="edit()">{{ ct('create') }}</a-button>
      <a-button :loading="loading" @click="load">{{ ct('refresh') }}</a-button>
    </div>
    <a-table :data-source="items" :columns="columns" :row-key="idField" :loading="loading" :scroll="{ x: tableWidth }" table-layout="fixed">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'">{{ record.name }}
          <a-tooltip :title="ct('idHelp')"><div class="muted" tabindex="0">{{ idField }}: {{ record[idField] }}</div></a-tooltip>
          <a-tag v-if="record.binding_required" color="orange">{{ ct('bindingRequired') }}</a-tag>
          <a-tag v-else-if="record.path_required" color="orange">{{ ct('pathRequired') }}</a-tag>
          <a-tag v-else-if="kind === 'gateway' && record.external_gateway_enabled === false" color="orange">{{ ct('gatewayDisabled') }}</a-tag>
        </template>
        <template v-else-if="column.key === 'platform_ids'">{{ record.platform_ids.map(partnerName).join(', ') }}</template>
        <template v-else-if="column.key === 'bearer_token_masked' && kind === 'gateway'"><template v-if="record.gateway_path">{{ ct('signature') }}<div class="muted">Token ID: {{ record.token_id || '—' }}</div></template><span v-else>—</span></template>
        <template v-else-if="column.key === 'notification_types'"><a-tag v-for="type in record.notification_types" :key="type">{{ t(`externalCallbacks.${type}`) }}</a-tag></template>
        <template v-else-if="column.key === 'enabled'"><a-tag :color="record.enabled ? 'green' : 'default'">{{ t(`externalAccess.${record.enabled ? 'enabled' : 'disabled'}`) }}</a-tag></template>
        <template v-else-if="column.key === 'updated_at'">{{ formatTime(record.updated_at) }}</template>
        <template v-else-if="column.key === 'actions'">
          <a-space wrap :size="[4, 4]" class="receiver-actions">
            <a-button v-if="can('external_access:update')" type="link" :disabled="!!busy" @click="edit(record)">{{ t('externalAccess.edit') }}</a-button>
            <a-popconfirm v-if="can('external_access:update') && record.enabled" :title="ct('disableConfirm')" @confirm="toggle(record)"><a-button type="link" :loading="busy === `state:${record[idField]}`" :disabled="!!busy">{{ t('externalAccess.disable') }}</a-button></a-popconfirm>
            <a-button v-else-if="can('external_access:update')" type="link" :loading="busy === `state:${record[idField]}`" :disabled="!!busy" @click="toggle(record)">{{ t('externalAccess.enable') }}</a-button>
            <a-button v-if="can('external_access:update')" type="link" :disabled="!!busy || !record.enabled || record.binding_required || record.path_required || record.external_gateway_enabled === false" @click="openTest(record)">{{ ct('test') }}</a-button>
            <a-button type="link" @click="recordsFor = record[idField]">{{ ct('records') }}</a-button>
            <a-popconfirm v-if="can('external_access:delete')" :title="ct('removeConfirm')" @confirm="remove(record)"><a-button type="link" danger :loading="busy === `delete:${record[idField]}`" :disabled="!!busy">{{ ct('remove') }}</a-button></a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>
    <a-modal v-model:open="editorOpen" :title="ct(editing ? 'edit' : 'create')" width="min(640px, 100vw)"
      :confirm-loading="saving" :ok-button-props="{ disabled: saving }" :cancel-button-props="{ disabled: saving }"
      :closable="!saving" :mask-closable="false" :ok-text="t('externalAccess.save')" @ok="save" @cancel="clearToken">
      <a-form layout="vertical" :disabled="saving">
        <a-form-item v-if="kind === 'callback'" :label="ct('name')" required :extra="ct('nameHelp')"><a-input v-model:value="form.name" /></a-form-item>
        <a-form-item v-else :label="ct('name')" required :extra="ct('gatewayHelp')">
          <a-select v-model:value="form.external_gateway_id" :options="gatewayOptions" show-search option-filter-prop="label" :placeholder="ct('selectGateway')" />
        </a-form-item>
        <a-form-item :label="ct('id')" required :extra="ct('idHelp')"><a-input v-model:value="form[idField]" :disabled="editing || saving" /></a-form-item>
        <a-alert v-if="kind === 'gateway' && editing && (form.binding_required || form.path_required)" type="info" :message="ct('bindingHelp')" show-icon style="margin-bottom: 16px" />
        <a-form-item :label="t('externalAccess.partners')" required><a-select v-model:value="form.platform_ids" mode="multiple" :options="partnerOptions" /></a-form-item>
        <template v-if="kind === 'callback'">
          <a-form-item :label="ct('url')" required :extra="ct('urlHelp')"><a-input v-model:value="form.url" /></a-form-item>
          <a-form-item :label="ct('token')" :required="!editing" :extra="ct('tokenHelp')"><a-input-password v-model:value="form.bearer_token" autocomplete="new-password" :placeholder="editing ? '********' : ''" /></a-form-item>
        </template>
        <template v-else>
          <a-form-item :label="ct('path')" required :extra="ct('pathHelp')"><a-input v-model:value="form.gateway_path" placeholder="/integration/v1/agent-evaluation-results" /></a-form-item>
          <a-form-item :label="ct('url')"><div class="muted">{{ gatewayPreview || '—' }}</div></a-form-item>
          <a-form-item :label="ct('token')" :extra="ct('tokenHelp')">{{ ct('signature') }}<div>Token ID: {{ selectedGateway?.token_id || '—' }}</div></a-form-item>
        </template>
        <a-form-item v-if="kind === 'callback'" :label="ct('types')" required><a-checkbox-group v-model:value="form.notification_types" :options="typeOptions" /></a-form-item>
        <a-form-item :label="ct('enabled')"><a-switch v-model:checked="form.enabled" /></a-form-item>
        <p class="muted">{{ ct('versionHelp') }}</p>
        <a-alert v-if="formError" type="error" :message="errorText(formError)" show-icon />
      </a-form>
    </a-modal>
    <a-modal :open="!!testConfig" :title="ct('test')" :confirm-loading="testing" :ok-button-props="{ disabled: testing }"
      :cancel-button-props="{ disabled: testing }" :closable="!testing" :mask-closable="false" :ok-text="ct('test')" @ok="sendTest" @cancel="testConfig = null">
      <p>{{ ct('testHelp') }}</p>
      <a-form layout="vertical" :disabled="testing">
        <a-form-item :label="t('externalAccess.partners')" required><a-select v-model:value="testForm.platform_id" :options="testPartnerOptions" /></a-form-item>
        <a-form-item v-if="kind === 'callback'" :label="ct('types')" required><a-select v-model:value="testForm.notification_type" :options="testTypeOptions" /></a-form-item>
        <a-alert v-if="testError" type="error" :message="errorText(testError)" show-icon />
      </a-form>
    </a-modal>
    <a-drawer :open="!!recordsFor" :title="ct('records')" width="min(1500px, 100vw)" @close="recordsFor = ''">
      <ExternalDeliveries v-if="recordsFor" :key="recordsFor" :partners="partners" :config-id="recordsFor" :kind="kind" />
    </a-drawer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { formatBeijingDateTime as formatTime } from '../utils/format'
import { listReceiverConfigs, getGatewayConfigOptions, createReceiverConfig, updateReceiverConfig, setReceiverConfigState, deleteReceiverConfig, testReceiverConfig } from '../api'
import ExternalDeliveries from './ExternalDeliveries.vue'

const props = defineProps({ partners: { type: Array, default: () => [] }, kind: { type: String, default: 'callback' } })
const idField = `${props.kind}_id`
const namespace = props.kind === 'gateway' ? 'externalGateways' : 'externalCallbacks'
const { t, te } = useI18n()
const ct = key => t(`${namespace}.${key}`)
const items = ref([]), loading = ref(false), editorOpen = ref(false), editing = ref(false), saving = ref(false)
const gateways = ref([])
const gatewayOptions = computed(() => gateways.value.map(row => ({ value: row.id, disabled: !row.enabled,
  label: row.enabled ? row.name : `${row.name} (${t('externalAccess.disabled')})` })))
const busy = ref(''), formError = ref(''), testError = ref(''), testConfig = ref(null), testing = ref(false), recordsFor = ref('')
const form = reactive({}), testForm = reactive({})
const selectedGateway = computed(() => gateways.value.find(row => row.id === form.external_gateway_id))
const gatewayPreview = computed(() => selectedGateway.value && form.gateway_path ? selectedGateway.value.management_base_url.replace(/\/$/, '') + form.gateway_path : '')
let sequence = 0
const partnerName = id => props.partners.find(row => row.platform_id === id)?.name || id
const partnerOptions = computed(() => props.partners.map(row => ({ value: row.platform_id, label: `${row.name} (${row.platform_id})` })))
const typeOptions = computed(() => ['skill_scan', 'agent_evaluation'].map(value => ({ value, label: t(`externalCallbacks.${value}`) })))
const testTypeOptions = computed(() => typeOptions.value.filter(row => testConfig.value?.notification_types?.includes(row.value)))
const testPartnerOptions = computed(() => partnerOptions.value.filter(row => testConfig.value?.platform_ids.includes(row.value)))
const columns = computed(() => [
  ['name', 'externalCallbacks.name', 200], ['platform_ids', 'externalAccess.partners', 160], ['url', 'externalCallbacks.url', 240],
  ['bearer_token_masked', 'externalCallbacks.token', 140], ['notification_types', 'externalCallbacks.types', 160],
  ['enabled', 'externalAccess.status', 90], ['updated_at', 'externalCallbacks.updated', 170], ['actions', 'externalAccess.actions', 220],
].filter(([key]) => props.kind === 'callback' || key !== 'notification_types')
  .map(([key, label, width]) => ({ key, dataIndex: key, title: t(label.replace('externalCallbacks', namespace)), width,
    ...(key === 'actions' ? { fixed: 'right' } : {}) })))
const tableWidth = computed(() => columns.value.reduce((width, column) => width + column.width, 0))
const errorText = error => {
  if (error === 'invalid') return ct('invalid')
  const code = error?.response?.data?.error_code
  const key = code?.replace(`external_${props.kind}s.`, `${namespace}.errors.`)
  return key && te(key) ? t(key) : error?.response?.data?.detail || t('externalAccess.failed')
}
async function load() {
  const own = ++sequence
  loading.value = true
  try {
    const [result, options] = await Promise.all([listReceiverConfigs(props.kind), props.kind === 'gateway' ? getGatewayConfigOptions() : null])
    if (own === sequence) { items.value = result.items; gateways.value = options?.items || [] }
  }
  catch (error) { if (own === sequence) message.error(errorText(error)) }
  finally { if (own === sequence) loading.value = false }
}
function clearToken() { form.bearer_token = '' }
function edit(row) {
  editing.value = !!row
  Object.assign(form, row ? { ...row, platform_ids: [...row.platform_ids], notification_types: [...(row.notification_types || [])], bearer_token: '' }
    : { [idField]: '', name: '', external_gateway_id: undefined, binding_required: false, path_required: false, gateway_path: '', platform_ids: [], url: '', bearer_token: '', notification_types: ['skill_scan', 'agent_evaluation'], enabled: true, revision: null })
  formError.value = ''; editorOpen.value = true
}
async function save() {
  if (saving.value) return
  let receiverValid = false
  try {
    if (props.kind === 'gateway') {
      const path = form.gateway_path || '', decoded = decodeURIComponent(path)
      receiverValid = path.startsWith('/') && !path.startsWith('//') && !/[?#]/.test(path) &&
        !/[\\\s\u0000-\u001f]/.test(decoded) && !decoded.split('/').some(part => ['.', '..'].includes(part)) && gatewayPreview.value.length <= 2048
    } else {
      const url = new URL(form.url)
      receiverValid = ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.hash && form.url.length <= 2048 &&
        ((editing.value && !form.bearer_token) || /^[!-~]{1,4096}$/.test(form.bearer_token))
    }
  } catch { formError.value = 'invalid'; return }
  if ((props.kind === 'callback' && (!form.name.trim() || [...form.name].length > 128)) ||
      (props.kind === 'gateway' && !gateways.value.some(row => row.id === form.external_gateway_id && row.enabled)) ||
      !form[idField].trim() || [...form[idField]].length > 128 || !form.platform_ids.length || (props.kind === 'callback' && !form.notification_types.length) ||
      !receiverValid) { formError.value = 'invalid'; return }
  const body = { platform_ids: form.platform_ids, enabled: form.enabled }
  if (props.kind === 'callback') {
    Object.assign(body, { notification_types: form.notification_types, name: form.name, url: form.url })
    if (form.bearer_token) body.bearer_token = form.bearer_token
  } else Object.assign(body, { external_gateway_id: form.external_gateway_id, gateway_path: form.gateway_path })
  saving.value = true; formError.value = ''
  try {
    if (editing.value) await updateReceiverConfig(props.kind, form[idField], { ...body, revision: form.revision })
    else await createReceiverConfig(props.kind, { ...body, [idField]: form[idField] })
    clearToken(); editorOpen.value = false; message.success(ct('saved')); await load()
  } catch (error) { formError.value = error } finally { saving.value = false }
}
async function toggle(row) {
  if (busy.value) return
  busy.value = `state:${row[idField]}`
  try { await setReceiverConfigState(props.kind, row[idField], { enabled: !row.enabled, revision: row.revision }); await load() }
  catch (error) { message.error(errorText(error)) } finally { busy.value = '' }
}
async function remove(row) {
  if (busy.value) return
  busy.value = `delete:${row[idField]}`
  try { await deleteReceiverConfig(props.kind, row[idField], row.revision); message.success(ct('removed')); await load() }
  catch (error) { message.error(errorText(error)) } finally { busy.value = '' }
}
function openTest(row) {
  testConfig.value = row; testError.value = ''
  Object.assign(testForm, { platform_id: row.platform_ids[0], notification_type: row.notification_types?.[0] })
}
async function sendTest() {
  if (testing.value) return
  testing.value = true; testError.value = ''
  const row = testConfig.value
  try {
    await testReceiverConfig(props.kind, row[idField], { ...testForm, revision: row.revision })
    testConfig.value = null; message.success(ct('testQueued')); recordsFor.value = row[idField]
  } catch (error) { testError.value = error } finally { testing.value = false }
}
onMounted(load)
onBeforeUnmount(() => { sequence++; clearToken() })
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.muted { color: #6b7280; font-size: 12px; overflow-wrap: anywhere; }
.receiver-actions :deep(.ant-btn) { padding-inline: 4px; }
:deep(.ant-table-cell), :deep(.ant-form-item-extra) { overflow-wrap: anywhere; }
:deep(.ant-checkbox-group) { display: flex; flex-wrap: wrap; gap: 12px; }
</style>
