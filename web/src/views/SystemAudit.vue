<template>
  <div>
    <div class="audit-header"><h2>{{ t('iam.audit') }}</h2>
      <a-button v-if="can('audit:verify')" :loading="verifying" :disabled="verifying" @click="verify">{{ t('iam.verify') }}</a-button>
    </div>
    <p>{{ t('iam.timezone') }}</p>
    <a-card>
      <a-tabs v-model:activeKey="kind">
        <a-tab-pane v-for="item in kinds" :key="item" :tab="t(`iam.${item}`)" />
      </a-tabs>
      <p class="audit-description">{{ t(`iam.auditDescriptions.${kind}`) }}</p>
      <div class="audit-filters"><a-space wrap>
        <a-input class="audit-search" v-model:value="filters.q" :placeholder="t('iam.auditKeyword')" allow-clear @pressEnter="search" />
        <a-input v-model:value="filters.actor" :placeholder="t('iam.actorExact')" allow-clear @pressEnter="search" />
        <a-auto-complete v-if="kind !== 'login'" v-model:value="filters.module" :placeholder="t('iam.module')" allow-clear :options="moduleOptions" @select="() => nextTick(search)" />
        <a-select v-if="kind !== 'login'" v-model:value="filters.action" :placeholder="t('iam.action')" allow-clear show-search option-filter-prop="label" :options="actionOptions" />
        <a-select v-model:value="filters.outcome" :placeholder="t('iam.outcome')" allow-clear :options="outcomeOptions" />
        <a-range-picker v-model:value="dates" show-time :placeholder="[t('iam.dateFrom'), t('iam.dateTo')]" />
        <a-button @click="reset">{{ t('iam.reset') }}</a-button>
      </a-space></div>
      <div class="audit-result-note"><span>{{ t('iam.total', { count: pager.total }) }}</span><span>{{ t('iam.autoFilter') }}</span></div>
      <a-alert v-if="loadError" class="audit-load-error" type="error" show-icon :message="loadError">
        <template #action><a-button size="small" :loading="loading" @click="load">{{ t('iam.retry') }}</a-button></template>
      </a-alert>
      <a-table :columns="columns" :data-source="rows" row-key="key" :scroll="{ x: kind === 'security' ? 880 : 1020 }" :loading="loading" :pagination="pagination" @change="tableChange">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'outcome'"><a-tag :color="outcomeColor(record.outcome)">{{ outcomeLabel(record.outcome) }}</a-tag><div v-if="record.reason" class="audit-secondary">{{ reasonLabel(record.reason) }}</div></template>
          <template v-else-if="column.key === 'event'"><strong>{{ eventLabel(record) }}</strong><div class="audit-secondary">{{ moduleLabel(record.module) }}</div></template>
          <template v-else-if="column.key === 'target'"><div class="audit-target">{{ targetLabel(record) }}</div><div v-if="targetLabel(record) !== record.target" class="audit-secondary">{{ record.target }}</div></template>
          <template v-else-if="column.key === 'details'"><a-button type="link" @click="detail = record">{{ t('iam.details') }}</a-button></template>
        </template>
      </a-table>
    </a-card>
    <a-drawer :open="!!detail" :title="t('iam.details')" :width="720" :styles="{ wrapper: { maxWidth: '100vw' } }" @close="detail = null">
      <a-descriptions v-if="detail" :column="1" bordered size="small">
        <a-descriptions-item :label="t('iam.event')">{{ eventLabel(detail) }}</a-descriptions-item>
        <a-descriptions-item :label="t('iam.time')">{{ formatDateTime(detail.created_at) }}</a-descriptions-item>
        <a-descriptions-item :label="t('iam.outcome')"><a-tag :color="outcomeColor(detail.outcome)">{{ outcomeLabel(detail.outcome) }}</a-tag></a-descriptions-item>
        <a-descriptions-item :label="t('iam.actor')">{{ detail.actor }}</a-descriptions-item>
        <a-descriptions-item :label="t('iam.module')">{{ moduleLabel(detail.module) }}</a-descriptions-item>
        <a-descriptions-item :label="t('iam.target')">{{ targetLabel(detail) }}</a-descriptions-item>
        <a-descriptions-item v-if="detail.event_type" :label="t('iam.eventType')">{{ detail.event_type }}</a-descriptions-item>
        <a-descriptions-item v-if="detail.event_id" :label="t('iam.eventId')">{{ detail.event_id }}</a-descriptions-item>
        <a-descriptions-item v-if="detail.request_id" :label="t('iam.requestId')">{{ detail.request_id }}</a-descriptions-item>
        <a-descriptions-item v-if="detail.client_ip" :label="t('iam.ip')">{{ detail.client_ip }}</a-descriptions-item>
        <a-descriptions-item v-if="detail.reason" :label="t('iam.reason')">{{ reasonLabel(detail.reason) }}</a-descriptions-item>
      </a-descriptions>
      <template v-if="changes.length"><h3>{{ t('iam.changes') }}</h3><a-table :columns="changeColumns" :data-source="changes" row-key="field" :pagination="false" size="small" :scroll="{ x: 560 }" /></template>
      <a-collapse class="audit-original"><a-collapse-panel key="original" :header="t('iam.original')"><pre data-no-i18n>{{ JSON.stringify(detail, null, 2) }}</pre></a-collapse-panel></a-collapse>
    </a-drawer>
    <a-modal v-model:open="verifyOpen" :title="t('iam.verify')" :footer="null">
      <a-alert v-if="verification" show-icon :type="verification.valid ? 'success' : 'error'" :message="t(verification.valid ? 'iam.chainValid' : 'iam.chainInvalid', { count: verification.checked })" />
      <pre data-no-i18n>{{ JSON.stringify(verification, null, 2) }}</pre>
    </a-modal>
  </div>
</template>
<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { iamList, iamVerify } from '../api'
import { formatBeijingDateTime as formatDateTime } from '../utils/format'
const { t, te, tm } = useI18n()
const kinds = computed(() => ['login', 'operation', 'security'].filter(value => can(`audit:${value}`)))
const kind = ref(kinds.value[0] || 'operation'), rows = ref([]), loading = ref(false), detail = ref(null), dates = ref([])
const verifying = ref(false), verifyOpen = ref(false), verification = ref(null)
const loadError = ref('')
const loadState = { version: 0 }
const filters = reactive({ q: '', actor: '', module: undefined, action: undefined, outcome: undefined })
const pager = reactive({ current: 1, pageSize: 20, total: 0 })
const pagination = computed(() => ({ ...pager, showSizeChanger: true, showTotal: count => t('iam.total', { count }) }))
const outcomeLabel = value => te(`iam.outcomes.${value}`) ? t(`iam.outcomes.${value}`) : value || '—'
const outcomeColor = value => ({ success: 'green', failed: 'red', failure: 'red', denied: 'orange', blocked: 'orange' })[value] || 'default'
const moduleLabel = value => te(`iam.modules.${value}`) ? t(`iam.modules.${value}`) : value || '—'
const reasonLabel = value => te(`iam.loginReasons.${value}`) ? t(`iam.loginReasons.${value}`) : value
const eventLabel = record => {
  if (record.module === 'audit' && te(`iam.auditActions.${record.action}`)) return t(`iam.auditActions.${record.action}`)
  if (record.event_type && te(`iam.events.${record.event_type.replaceAll('.', '_')}`)) return t(`iam.events.${record.event_type.replaceAll('.', '_')}`)
  if (record.source === 'login') return t('iam.signInEvent')
  if (record.event_type) return record.event_type
  return record.source !== 'legacy' && te(`iam.operations.${record.action}`) ? t(`iam.operations.${record.action}`) : record.action || '—'
}
const targetLabel = record => record.details?.after?.username || record.details?.before?.username || record.details?.after?.display_name || record.details?.before?.display_name || record.target || '—'
const outcomeOptions = computed(() => ['success', 'failed', 'denied', 'blocked'].map(value => ({ value, label: outcomeLabel(value) })))
const moduleOptions = computed(() => Object.keys(tm('iam.modules')).map(value => ({ value, label: t(`iam.modules.${value}`) })))
const actionOptions = computed(() => [
  'view', 'create', 'update', 'delete', 'submit', 'assign_role', 'set_status', 'reset_password',
  'change_password', 'grant', 'sort', 'verify', 'scan', 'approve', 'reject', 'deploy', 'sign',
  'execute', 'cancel', 'stop', 'raw', 'sync', 'test', 'login', 'operation', 'security',
].map(value => ({ value, label: t(`iam.actionFilters.${value}`) })))
const dateFilter = value => value ? `${value.format('YYYY-MM-DDTHH:mm:ss.SSS')}+08:00` : undefined
const columns = computed(() => [
  { key: 'created_at', dataIndex: 'created_at', title: t('iam.time'), width: 175, customRender: ({ text }) => formatDateTime(text) },
  { key: 'actor', dataIndex: 'actor', title: t('iam.actor'), width: 125 },
  { key: 'event', title: t('iam.event'), width: 220 },
  { key: 'target', title: t('iam.target'), width: 175 },
  { key: 'outcome', title: t('iam.outcome'), width: 110, fixed: 'right' },
  ...(kind.value === 'security' ? [] : [{ key: 'client_ip', dataIndex: 'client_ip', title: t('iam.ip'), width: 140 }]),
  { key: 'details', title: t('iam.details'), width: 75, fixed: 'right' },
])
const changeColumns = computed(() => ['field', 'before', 'after'].map(key => ({ key, dataIndex: key, title: t(`iam.${key}`) })))
const changes = computed(() => {
  const before = detail.value?.details?.before || {}, after = detail.value?.details?.after || {}
  const display = (field, value) => {
    if (value === undefined || value === null) return '—'
    if (field === 'is_active' && typeof value === 'boolean') return t(value ? 'iam.enabled' : 'iam.disabled')
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
  }
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter(field => JSON.stringify(before[field]) !== JSON.stringify(after[field]))
    .map(field => ({ field: te(`iam.fields.${field}`) ? t(`iam.fields.${field}`) : field, before: display(field, before[field]), after: display(field, after[field]) }))
})
let filterTimer
async function load() {
  const version = ++loadState.version
  const requestedKind = kind.value
  if (!kinds.value.length) return
  loading.value = true
  loadError.value = ''
  try {
    const query = { ...filters, since: dateFilter(dates.value?.[0]), until: dateFilter(dates.value?.[1]), page: pager.current, page_size: pager.pageSize }
    if (requestedKind === 'login') { delete query.module; delete query.action }
    const data = await iamList(`audit/${requestedKind}`, query)
    if (version !== loadState.version || requestedKind !== kind.value) return
    rows.value = data.items; pager.total = data.total
  } catch (e) {
    if (version === loadState.version) {
      rows.value = []; pager.total = 0
      loadError.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : t('iam.auditLoadFailed')
    }
  }
  finally { if (version === loadState.version) loading.value = false }
}
function search() { clearTimeout(filterTimer); pager.current = 1; load() }
function reset() { Object.assign(filters, { q: '', actor: '', module: undefined, action: undefined, outcome: undefined }); dates.value = [] }
function tableChange(p) { clearTimeout(filterTimer); Object.assign(pager, { current: p.current, pageSize: p.pageSize }); load() }
watch(() => [filters.q, filters.actor, filters.module], () => {
  clearTimeout(filterTimer)
  loadState.version += 1
  filterTimer = setTimeout(search, 300)
})
watch(() => [filters.action, filters.outcome, dates.value, kind.value], search)
async function verify() {
  if (verifying.value) return
  verifying.value = true
  try { verification.value = await iamVerify(); verifyOpen.value = true; await load() }
  catch (e) { message.error(e.response?.data?.detail || t('iam.failed')) } finally { verifying.value = false }
}
onMounted(load)
onUnmounted(() => { clearTimeout(filterTimer); loadState.version += 1 })
</script>
<style scoped>
.audit-header { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.audit-filters { margin-bottom: 20px; } .audit-filters :deep(.ant-input-affix-wrapper) { width: 170px; }
.audit-filters :deep(.ant-select) { min-width: 160px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f8fafc; padding: 16px; border-radius: 8px; }
.audit-filters :deep(.audit-search) { width: 260px; max-width: 100%; }
.audit-description, .audit-secondary { color: #64748b; }
.audit-secondary { margin-top: 5px; font-size: 12px; overflow-wrap: anywhere; }
.audit-target, :deep(.ant-descriptions-item-content) { overflow-wrap: anywhere; }
.audit-result-note { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; color: #64748b; margin-bottom: 12px; font-size: 13px; }
.audit-original { margin-top: 20px; }
.audit-load-error { margin-bottom: 16px; }
:deep(.ant-table-cell) { vertical-align: top; }
</style>
