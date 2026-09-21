<template>
  <div>
    <div class="page-header">
      <div>
        <div class="eyebrow">{{ t('externalAiGateway.eyebrow') }}</div>
        <h1>{{ t('externalAiGateway.title') }}</h1>
        <p>{{ t('externalAiGateway.description') }}</p>
      </div>
      <a-button v-if="canCreate" type="primary" @click="openForm()">{{ t('externalAiGateway.add') }}</a-button>
    </div>

    <a-alert type="info" show-icon :message="t('externalAiGateway.modelDiscoveryHint')" />
    <a-card class="gateway-card" :bordered="false">
      <a-table :data-source="gateways" :columns="columns" row-key="id" :loading="loading" size="small" :scroll="{ x: 960 }" :locale="{ emptyText: t('externalAiGateway.empty') }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <strong>{{ record.name }}</strong>
            <div class="muted endpoint">{{ record.management_base_url }}</div>
            <div class="muted endpoint">{{ record.model_base_url }}</div>
          </template>
          <template v-else-if="column.key === 'token'">
            <div>{{ record.token_id }}</div>
            <div class="muted">{{ record.token_value_masked || '••••••••' }}</div>
          </template>
          <template v-else-if="column.key === 'enabled'">
            <a-tag :color="record.enabled ? 'green' : 'default'">{{ t(record.enabled ? 'externalAiGateway.active' : 'externalAiGateway.disabled') }}</a-tag>
          </template>
          <template v-else-if="column.key === 'test'">
            <a-tag :color="testColor(record.last_test_status)">{{ testLabel(record.last_test_status) }}</a-tag>
            <div v-if="record.last_tested_at" class="muted">{{ t('externalAiGateway.lastTested', { time: formatTime(record.last_tested_at) }) }}</div>
            <div v-if="record.last_test_error" class="error-text">{{ testErrorLabel(record.last_test_error) }}</div>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space wrap>
              <a-button type="link" :disabled="!!actionId" @click="openKeys(record)">{{ t('externalAiGateway.apiKeys') }}</a-button>
              <a-button v-if="canTest" type="link" :loading="actionId === `test:${record.id}`" :disabled="!!actionId" @click="testConnection(record)">{{ t('externalAiGateway.test') }}</a-button>
              <a-button v-if="canUpdate" type="link" :disabled="!!actionId" @click="openForm(record)">{{ t('externalAiGateway.edit') }}</a-button>
              <a-popconfirm v-if="canDelete" :title="t('externalAiGateway.deleteConfirm')" @confirm="remove(record)">
                <a-button type="link" danger :loading="actionId === `delete:${record.id}`" :disabled="!!actionId">{{ t('externalAiGateway.delete') }}</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-drawer v-model:open="keysOpen" :title="t('externalAiGateway.keyDrawerTitle', { name: selectedGateway?.name || '-' })" width="min(920px, 94vw)" @close="closeKeys">
      <a-alert type="info" show-icon :message="t('externalAiGateway.keyDrawerHint')" class="drawer-hint" />
      <a-table :data-source="agentKeys" :columns="keyColumns" row-key="id" :loading="keysLoading" size="small" :pagination="false" :scroll="{ x: 980 }" :locale="{ emptyText: t('externalAiGateway.keyEmpty') }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'agent'">
            <strong>{{ record.managed_agent_name }}</strong>
            <div class="muted">{{ record.managed_agent_id }}</div>
            <a-tag v-if="record.client_id" class="client-tag">{{ t('externalAiGateway.clientBound', { id: record.client_id }) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'identity'">
            <div>{{ record.external_agent_id }}</div>
            <div class="muted">{{ t('externalAiGateway.keyIdValue', { id: record.key_id }) }}</div>
          </template>
          <template v-else-if="column.key === 'key'">
            <a-typography-text code>{{ revealedKeys[record.id] || record.api_key_masked }}</a-typography-text>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="record.status === 'active' ? 'green' : 'default'">{{ record.status }}</a-tag>
            <div class="muted">{{ t('externalAiGateway.modelCount', { count: record.model_count || 0 }) }}</div>
          </template>
          <template v-else-if="column.key === 'updated'">
            {{ formatTime(record.updated_at) }}
          </template>
          <template v-else-if="column.key === 'keyActions'">
            <a-space>
              <a-button v-if="canReveal && !revealedKeys[record.id]" type="link" @click="openReveal(record)">{{ t('externalAiGateway.reveal') }}</a-button>
              <a-button v-if="revealedKeys[record.id]" type="link" @click="copyKey(record)">{{ t('externalAiGateway.copy') }}</a-button>
              <a-button v-if="revealedKeys[record.id]" type="link" @click="hideKey(record)">{{ t('externalAiGateway.hide') }}</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-drawer>

    <a-modal v-model:open="revealOpen" :title="t('externalAiGateway.revealTitle')" :ok-text="t('externalAiGateway.reveal')" :cancel-text="t('externalAiGateway.cancel')" :confirm-loading="revealing" @ok="revealKey" @cancel="revealPassword = ''">
      <a-alert type="warning" show-icon :message="t('externalAiGateway.revealWarning')" class="drawer-hint" />
      <a-form layout="vertical">
        <a-form-item :label="t('externalAiGateway.currentPassword')" required>
          <a-input-password v-model:value="revealPassword" autocomplete="current-password" @pressEnter="revealKey" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="formOpen" centered wrap-class-name="external-gateway-modal" :title="t(editingId ? 'externalAiGateway.edit' : 'externalAiGateway.add')" :ok-text="t('externalAiGateway.save')" :cancel-text="t('externalAiGateway.cancel')" :confirm-loading="saving" @ok="save">
      <a-form layout="vertical" :model="form">
        <a-form-item :label="t('externalAiGateway.name')" required><a-input v-model:value="form.name" :disabled="saving" /></a-form-item>
        <a-form-item :label="t('externalAiGateway.managementBaseUrl')" :extra="t('externalAiGateway.urlHint')" required><a-input v-model:value="form.management_base_url" :disabled="saving" placeholder="http://gateway.example:4005" /></a-form-item>
        <a-form-item :label="t('externalAiGateway.modelBaseUrl')" :extra="t('externalAiGateway.urlHint')" required><a-input v-model:value="form.model_base_url" :disabled="saving" placeholder="http://gateway.example:8080" /></a-form-item>
        <a-form-item :label="t('externalAiGateway.tokenId')" required><a-input v-model:value="form.token_id" :disabled="saving" autocomplete="off" /></a-form-item>
        <a-form-item :label="t('externalAiGateway.tokenValue')" :extra="editingMasked ? t('externalAiGateway.tokenMasked', { value: editingMasked }) : undefined" :required="!editingId">
          <a-input-password v-model:value="form.token_value" :disabled="saving" autocomplete="new-password" :placeholder="t(editingId ? 'externalAiGateway.tokenPlaceholderEdit' : 'externalAiGateway.tokenPlaceholderCreate')" />
        </a-form-item>
        <a-form-item :label="t('externalAiGateway.enabled')"><a-switch v-model:checked="form.enabled" :disabled="saving" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useI18n } from 'vue-i18n'
import { can } from '../access'
import { createExternalAiGateway, deleteExternalAiGateway, listExternalAiGateways, listExternalGatewayAgentKeys, revealExternalGatewayAgentKey, testExternalAiGateway, updateExternalAiGateway } from '../api'

const { t } = useI18n()
const gateways = ref([])
const loading = ref(false)
const saving = ref(false)
const actionId = ref('')
const formOpen = ref(false)
const editingId = ref(null)
const editingMasked = ref('')
const keysOpen = ref(false)
const keysLoading = ref(false)
const selectedGateway = ref(null)
const agentKeys = ref([])
const revealedKeys = reactive({})
const revealOpen = ref(false)
const revealBinding = ref(null)
const revealPassword = ref('')
const revealing = ref(false)
const form = reactive({ name: '', management_base_url: '', model_base_url: '', token_id: '', token_value: '', enabled: true })
const canCreate = computed(() => can('external_gateways:create'))
const canUpdate = computed(() => can('external_gateways:update'))
const canDelete = computed(() => can('external_gateways:delete'))
const canTest = computed(() => can('external_gateways:test'))
const canReveal = computed(() => can('external_gateways:reveal'))
const columns = computed(() => [
  { title: t('externalAiGateway.name'), key: 'name', width: 320 },
  { title: t('externalAiGateway.tokenId'), key: 'token', width: 210 },
  { title: t('externalAiGateway.enabled'), key: 'enabled', width: 100 },
  { title: t('externalAiGateway.status'), key: 'test', width: 220 },
  { title: t('externalAiGateway.actions'), key: 'actions', width: 300, fixed: 'right' },
])
const keyColumns = computed(() => [
  { title: t('externalAiGateway.usedByAgent'), key: 'agent', width: 220 },
  { title: t('externalAiGateway.externalIdentity'), key: 'identity', width: 260 },
  { title: t('externalAiGateway.apiKey'), key: 'key', width: 210 },
  { title: t('externalAiGateway.status'), key: 'status', width: 120 },
  { title: t('externalAiGateway.updatedAt'), key: 'updated', width: 170 },
  { title: t('externalAiGateway.actions'), key: 'keyActions', width: 180, fixed: 'right' },
])
const formatTime = value => value ? new Date(value).toLocaleString() : '-'
const testColor = status => ({ success: 'green', succeeded: 'green', failed: 'red', error: 'red', testing: 'blue' }[status] || 'default')
const testLabel = status => t(`externalAiGateway.${({ succeeded: 'success', error: 'failed' }[status] || status || 'untested')}`)
const testErrorLabel = code => code === 'external_gateway.connection_test_failed'
  ? t('externalAiGateway.connectionTestFailedDetail')
  : t('externalAiGateway.testFailed')
const validUrl = value => { try { return ['http:', 'https:'].includes(new URL(value).protocol) } catch { return false } }

async function load() {
  loading.value = true
  try { gateways.value = await listExternalAiGateways() || [] }
  catch (error) { message.error(error.response?.data?.detail || t('externalAiGateway.loadFailed')) }
  finally { loading.value = false }
}
function openForm(record) {
  editingId.value = record?.id || null
  editingMasked.value = record?.token_value_masked || ''
  Object.assign(form, record ? { name: record.name, management_base_url: record.management_base_url, model_base_url: record.model_base_url, token_id: record.token_id, token_value: '', enabled: record.enabled } : { name: '', management_base_url: '', model_base_url: '', token_id: '', token_value: '', enabled: true })
  formOpen.value = true
}
async function save() {
  if (saving.value) return
  if (!form.name.trim() || !form.management_base_url.trim() || !form.model_base_url.trim() || !form.token_id.trim() || (!editingId.value && !form.token_value)) return message.warning(t('externalAiGateway.required'))
  if (!validUrl(form.management_base_url) || !validUrl(form.model_base_url)) return message.warning(t('externalAiGateway.invalidUrl'))
  const payload = { name: form.name.trim(), management_base_url: form.management_base_url.trim().replace(/\/$/, ''), model_base_url: form.model_base_url.trim().replace(/\/$/, ''), token_id: form.token_id.trim(), enabled: form.enabled }
  if (form.token_value) payload.token_value = form.token_value
  saving.value = true
  try {
    if (editingId.value) await updateExternalAiGateway(editingId.value, payload)
    else await createExternalAiGateway(payload)
    formOpen.value = false
    message.success(t('externalAiGateway.saved'))
    await load()
  } catch (error) { message.error(error.response?.data?.detail || t('externalAiGateway.saveFailed')) }
  finally { saving.value = false }
}
async function testConnection(record) {
  if (actionId.value) return
  actionId.value = `test:${record.id}`
  try { await testExternalAiGateway(record.id); message.success(t('externalAiGateway.testSucceeded')); await load() }
  catch (error) { message.error(error.response?.data?.detail || t('externalAiGateway.testFailed')); await load() }
  finally { actionId.value = '' }
}
async function remove(record) {
  if (actionId.value) return
  actionId.value = `delete:${record.id}`
  try { await deleteExternalAiGateway(record.id); message.success(t('externalAiGateway.deleted')); await load() }
  catch (error) { message.error(error.response?.data?.detail || t('externalAiGateway.deleteFailed')) }
  finally { actionId.value = '' }
}
async function openKeys(record) {
  selectedGateway.value = record
  keysOpen.value = true
  keysLoading.value = true
  try { agentKeys.value = await listExternalGatewayAgentKeys(record.id) || [] }
  catch (error) { message.error(error.response?.data?.detail || t('externalAiGateway.keyLoadFailed')) }
  finally { keysLoading.value = false }
}
function closeKeys() {
  Object.keys(revealedKeys).forEach(key => delete revealedKeys[key])
  agentKeys.value = []
  selectedGateway.value = null
  revealOpen.value = false
  revealPassword.value = ''
}
function openReveal(record) {
  revealBinding.value = record
  revealPassword.value = ''
  revealOpen.value = true
}
async function revealKey() {
  if (revealing.value || !selectedGateway.value || !revealBinding.value) return
  if (!revealPassword.value) return message.warning(t('externalAiGateway.passwordRequired'))
  revealing.value = true
  try {
    const result = await revealExternalGatewayAgentKey(selectedGateway.value.id, revealBinding.value.id, { password: revealPassword.value })
    revealedKeys[revealBinding.value.id] = result.api_key
    revealOpen.value = false
    revealPassword.value = ''
    message.success(t('externalAiGateway.revealed'))
  } catch (error) { message.error(error.response?.data?.detail || t('externalAiGateway.revealFailed')) }
  finally { revealing.value = false }
}
async function copyKey(record) {
  try { await navigator.clipboard.writeText(revealedKeys[record.id]); message.success(t('externalAiGateway.copied')) }
  catch { message.error(t('externalAiGateway.copyFailed')) }
}
function hideKey(record) { delete revealedKeys[record.id] }
onMounted(load)
</script>

<style scoped>
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
.page-header h1 { margin: 4px 0 6px; font-size: 24px; }
.page-header p { max-width: 760px; margin: 0; color: #65758b; line-height: 1.6; }
.eyebrow { color: #1677ff; font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
.gateway-card { margin-top: 16px; }
.muted { color: #7a869a; font-size: 12px; }
.endpoint { overflow-wrap: anywhere; margin-top: 3px; }
.error-text { max-width: 220px; margin-top: 4px; color: #cf1322; font-size: 12px; overflow-wrap: anywhere; }
.drawer-hint { margin-bottom: 16px; }
.client-tag { margin-top: 6px; }
@media (max-width: 600px) { .page-header { flex-direction: column; } .page-header > button { width: 100%; } }
:global(.external-gateway-modal .ant-modal-content) { display: flex; max-height: calc(100vh - 32px); flex-direction: column; }
:global(.external-gateway-modal .ant-modal-body) { overflow-y: auto; }
:global(.external-gateway-modal .ant-form-item) { margin-bottom: 16px; }
</style>
