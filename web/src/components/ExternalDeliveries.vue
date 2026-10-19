<template>
  <section>
    <p class="muted">{{ t('externalDelivery.help') }}</p>
    <div class="toolbar">
      <a-select v-if="!configId" v-model:value="filters.kind" allow-clear :placeholder="t('externalDelivery.kind')" :options="kindOptions" />
      <a-select v-model:value="filters.platform_id" allow-clear :placeholder="t('externalAccess.allPartners')" :options="partnerOptions" />
      <a-select v-model:value="filters.status" allow-clear :placeholder="t('externalAccess.status')" :options="statusOptions" />
      <a-input v-model:value="filters.task_id" :placeholder="t('externalDelivery.task')" @pressEnter="search" />
      <a-input v-model:value="filters.message_id" :placeholder="t('externalDelivery.message')" @pressEnter="search" />
      <a-input v-model:value="filters.business_request_id" :placeholder="t('externalAccess.businessRequestId')" @pressEnter="search" />
      <a-input v-if="!configId" v-model:value="filters.config_id" :placeholder="t('externalDelivery.config')" @pressEnter="search" />
      <a-select v-model:value="filters.purpose" allow-clear :placeholder="t('externalDelivery.purpose')" :options="purposeOptions" />
      <a-button type="primary" :loading="loading" @click="search">{{ t('externalAccess.search') }}</a-button>
    </div>
    <a-table :data-source="records" :columns="columns" row-key="delivery_id" :loading="loading" :pagination="pagination" :scroll="{ x: 1500 }" @change="changePage">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'task_id'"><a @click="showDetail(record)">{{ record.task_id || record.message_id }}</a><div class="muted">{{ record.business_request_id }}</div></template>
        <template v-else-if="column.key === 'purpose'">{{ t(`externalDelivery.purposes.${record.purpose || 'result'}`) }}<div v-if="record.task_type" class="muted">{{ t(`externalCallbacks.${record.task_type}`) }}</div></template>
        <template v-else-if="column.key === 'kind'">{{ t(`externalDelivery.${record.kind}`) }}</template>
        <template v-else-if="column.key === 'platform_id'">{{ partnerName(record.platform_id) }}</template>
        <template v-else-if="column.key === 'status'"><a-tag :color="color(record.status)">{{ statusText(record) }}</a-tag><div v-if="record.last_error_code" class="muted">{{ errorText(record.last_error_code) }}</div></template>
        <template v-else-if="column.key === 'config_id'">{{ record.config_id }} / {{ record.config_version }}</template>
        <template v-else-if="['last_attempt_at', 'next_retry_at'].includes(column.key)">{{ formatTime(record[column.key]) }}</template>
        <template v-else-if="column.key === 'actions'"><a-popconfirm v-if="can('external_access:update') && record.status === 'failed'" :title="t('externalDelivery.retryConfirm')" @confirm="retry(record)"><a-button :loading="retrying === record.delivery_id" :disabled="!!retrying" type="link">{{ t('externalDelivery.retry') }}</a-button></a-popconfirm></template>
      </template>
    </a-table>
    <a-drawer :open="!!selected" :title="t('externalDelivery.detail')" width="min(900px, 100vw)" @close="closeDetail">
      <a-descriptions v-if="selected" :column="1" bordered size="small">
        <a-descriptions-item :label="t('externalDelivery.task')">{{ selected.task_id || '—' }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalDelivery.purpose')">{{ t(`externalDelivery.purposes.${selected.purpose || 'result'}`) }}</a-descriptions-item>
        <a-descriptions-item v-if="selected.created_by" :label="t('externalDelivery.operator')">{{ selected.created_by }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalDelivery.message')">{{ selected.message_id }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalAccess.partners')">{{ partnerName(selected.platform_id) }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalDelivery.config')">{{ selected.config_id }} / {{ selected.config_version }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalAccess.status')">{{ statusText(selected) }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalAccess.errorReason')">{{ errorText(selected.last_error_code) }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalDelivery.nextRetry')">{{ formatTime(selected.next_retry_at) }}</a-descriptions-item>
        <a-descriptions-item :label="t('externalDelivery.finished')">{{ formatTime(selected.completed_at) }}</a-descriptions-item>
      </a-descriptions>
      <template v-if="selected?.receipt">
        <h3>{{ t('externalDelivery.receipt') }}</h3>
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item v-for="item in receiptFields" :key="item.key" :label="item.label">{{ item.value }}</a-descriptions-item>
        </a-descriptions>
      </template>
      <h3>{{ t('externalDelivery.records') }}</h3>
      <a-table :data-source="selected?.attempt_records || []" :columns="attemptColumns" :pagination="false" row-key="attempt_id" size="small" :scroll="{ x: 850 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">{{ t(`externalDelivery.statuses.${record.status}`) }}</template>
          <template v-else-if="column.key.endsWith('_at')">{{ formatTime(record[column.key]) }}</template>
          <template v-else-if="column.key === 'error_code'">{{ errorText(record.error_code) }}</template>
        </template>
      </a-table>
    </a-drawer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { formatBeijingDateTime as formatTime } from '../utils/format'
import { listExternalDeliveries, getExternalDelivery, retryExternalDelivery } from '../api'

const props = defineProps({ partners: { type: Array, default: () => [] }, configId: { type: String, default: '' }, kind: { type: String, default: undefined } })
const { t, te } = useI18n()
const records = ref([]), selected = ref(null)
const loading = ref(false), retrying = ref(null)
const filters = reactive({ kind: props.kind, config_id: props.configId, purpose: undefined, platform_id: undefined, status: undefined, task_id: '', message_id: '', business_request_id: '' })
const pagination = reactive({ current: 1, pageSize: 20, total: 0, showSizeChanger: true })
let sequence = 0, detailSequence = 0
const kindOptions = computed(() => ['callback', 'gateway'].map(value => ({ value, label: t(`externalDelivery.${value}`) })))
const purposeOptions = computed(() => ['result', 'test'].map(value => ({ value, label: t(`externalDelivery.purposes.${value}`) })))
const statusOptions = computed(() => ['pending', 'retrying', 'delivered', 'synced', 'failed'].map(value => ({ value, label: t(`externalDelivery.statuses.${value}`) })))
const partnerOptions = computed(() => props.partners.map(row => ({ value: row.platform_id, label: `${row.name} (${row.platform_id})` })))
const partnerName = id => props.partners.find(row => row.platform_id === id)?.name || id
const color = status => ['delivered', 'synced'].includes(status) ? 'green' : status === 'failed' ? 'red' : 'blue'
const statusText = row => t(`externalDelivery.statuses.${row.in_flight ? 'sending' : row.status}`)
const errorText = code => !code ? '—' : te(`externalDelivery.errors.${code}`) ? t(`externalDelivery.errors.${code}`) : code
const cols = definitions => definitions.map(([key, label, width]) => ({ key, dataIndex: key, title: t(label), width }))
const columns = computed(() => cols([['kind', 'externalDelivery.kind', 160], ['purpose', 'externalDelivery.purpose', 150], ['task_id', 'externalDelivery.taskOrEvent', 300], ['platform_id', 'externalAccess.partners', 170], ['status', 'externalAccess.status', 230], ['config_id', 'externalDelivery.config', 180], ['attempts', 'externalDelivery.attempts', 110], ['last_attempt_at', 'externalDelivery.lastAttempt', 180], ['next_retry_at', 'externalDelivery.nextRetry', 180], ['actions', 'externalAccess.actions', 150]]))
const attemptColumns = computed(() => cols([['number', 'externalDelivery.number', 80], ['started_at', 'externalDelivery.lastAttempt', 180], ['finished_at', 'externalDelivery.finished', 180], ['status', 'externalAccess.status', 150], ['http_status', 'externalAccess.httpStatus', 110], ['error_code', 'externalAccess.errorReason', 260]]))
const receiptFields = computed(() => {
  const r = selected.value?.receipt
  if (!r) return []
  if (r.accepted === true) return [{ key: 'event_id', label: t('externalDelivery.message'), value: r.event_id || r.sync_id }, { key: 'accepted', label: t('externalAccess.status'), value: t('externalDelivery.accepted') }]
  return [['receipt_id', 'receiptId'], ['report_id', 'report'], ['report_version', 'reportVersion']].map(([key, label]) => ({ key, label: t(`externalDelivery.${label}`), value: r[key] })).concat([
    { key: 'current', label: t('externalDelivery.current'), value: t(`externalDelivery.${r.current ? 'current' : 'historical'}`) },
    { key: 'received_at', label: t('externalDelivery.received'), value: formatTime(r.received_at) },
  ])
})
const fail = error => message.error(error?.response?.data?.detail || t('externalAccess.failed'))
async function load() {
  const own = ++sequence
  loading.value = true
  try {
    const result = await listExternalDeliveries({ ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v != null && v !== '')), page: pagination.current, page_size: pagination.pageSize })
    if (own !== sequence) return
    records.value = result.items; pagination.total = result.total
  } catch (error) { if (own === sequence) fail(error) } finally { if (own === sequence) loading.value = false }
}
function search() { pagination.current = 1; load() }
function changePage(page) { pagination.current = page.current; pagination.pageSize = page.pageSize; load() }
async function showDetail(row) {
  const own = ++detailSequence
  try { const detail = await getExternalDelivery(row.delivery_id); if (own === detailSequence) selected.value = detail } catch (error) { if (own === detailSequence) fail(error) }
}
function closeDetail() { detailSequence++; selected.value = null }
async function retry(row) {
  if (retrying.value) return
  retrying.value = row.delivery_id
  try { await retryExternalDelivery(row.delivery_id); message.success(t('externalDelivery.queued')); await load() } catch (error) { fail(error) } finally { retrying.value = null }
}
let refreshTimer
onMounted(() => {
  load()
  refreshTimer = setInterval(() => {
    if (!loading.value && records.value.some(row => row.in_flight || ['pending', 'retrying'].includes(row.status))) load()
    if (selected.value && ['pending', 'retrying'].includes(selected.value.status)) showDetail(selected.value)
  }, 3000)
})
onBeforeUnmount(() => { clearInterval(refreshTimer); sequence++; detailSequence++ })
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.toolbar > .ant-select, .toolbar > .ant-input { width: 220px; }
.muted { color: #6b7280; font-size: 12px; overflow-wrap: anywhere; }
h3 { margin-top: 20px; }
:deep(.ant-table-cell), :deep(.ant-descriptions-item-content) { overflow-wrap: anywhere; }
@media (max-width: 600px) { .toolbar > .ant-select, .toolbar > .ant-input { width: 100%; } }
</style>
