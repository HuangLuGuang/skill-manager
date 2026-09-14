<template>
  <div class="audit-page">
    <header class="audit-heading">
      <h1>{{ t('auditLog.title') }}</h1>
      <p>{{ t('auditLog.subtitle') }}</p>
    </header>

    <div class="audit-filters">
        <a-input
          :value="filters.keyword"
          @update:value="value => updateFilter('keyword', value)"
          class="keyword-filter"
          size="large"
          allow-clear
          :aria-label="t('auditLog.keywordPlaceholder')"
          :placeholder="t('auditLog.keywordPlaceholder')"
        >
          <template #prefix><SearchOutlined /></template>
        </a-input>
        <a-select :value="filters.eventType" @update:value="value => updateFilter('eventType', value)" size="large" class="event-filter" :aria-label="t('auditLog.eventType')">
          <a-select-option value="all">{{ t('auditLog.allEvents') }}</a-select-option>
          <a-select-option v-for="option in eventTypeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </a-select-option>
        </a-select>
        <a-select :value="filters.sinceHours" @update:value="value => updateFilter('sinceHours', value)" size="large" class="period-filter" :aria-label="t('auditLog.timeRange')">
          <a-select-option :value="24">{{ t('auditLog.last24Hours') }}</a-select-option>
          <a-select-option :value="168">{{ t('auditLog.last7Days') }}</a-select-option>
          <a-select-option :value="720">{{ t('auditLog.last30Days') }}</a-select-option>
        </a-select>
        <a-button size="large" @click="resetFilters">{{ t('auditLog.reset') }}</a-button>
    </div>

    <a-alert
      v-if="loadError"
      class="audit-error"
      type="error"
      show-icon
      :message="loadError"
      :description="t('auditLog.loadFailedHelp')"
    >
      <template #action><a-button size="small" @click="search">{{ t('auditLog.retry') }}</a-button></template>
    </a-alert>

    <a-table
        :data-source="rows"
        :columns="columns"
        :scroll="{ x: 1040 }"
        row-key="event_id"
        :loading="loading"
        :pagination="pagination"
        :expanded-row-keys="expandedRowKeys"
        :show-expand-column="false"
        :row-class-name="record => expandedRowKeys.includes(record.event_id) ? 'audit-row-expanded' : ''"
        :locale="{ emptyText: loadError ? t('auditLog.emptyAfterError') : t('auditLog.empty') }"
        @change="handleTableChange"
        @expand="handleExpand"
      >
      <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'timestamp'">
            <span class="time-value">{{ formatDateTime(record.timestamp) }}</span>
          </template>
          <template v-else-if="column.key === 'event_type'">
            <span class="event-cell">
              <i class="event-dot" :class="`event-dot--${eventTone(record.event_type)}`" aria-hidden="true" />
              <span>{{ eventLabel(record.event_type) }}</span>
            </span>
          </template>
          <template v-else-if="column.key === 'object'">
            <span class="stacked-value">
              <RouterLink v-if="record.skill_id && record.skill_id !== 'unknown'" :to="`/skills/${record.skill_id}`">
                {{ record.skill_name || record.skill_id }}
              </RouterLink>
              <span v-else>{{ record.skill_name || '-' }}</span>
              <span class="secondary-value">{{ record.skill_id || '-' }}</span>
            </span>
          </template>
          <template v-else-if="column.key === 'agent_source'">
            <span class="stacked-value">
              <span>{{ auditAgent(record) }}</span>
              <span class="secondary-value">{{ auditIp(record) }}</span>
            </span>
          </template>
          <template v-else-if="column.key === 'actor'">
            <span class="actor-value">{{ auditActor(record) }}</span>
          </template>
          <template v-else-if="column.key === 'view'">
            <a-button
              type="link"
              class="view-button"
              :aria-expanded="expandedRowKeys.includes(record.event_id)"
              :aria-label="t(expandedRowKeys.includes(record.event_id) ? 'auditLog.hideDetails' : 'auditLog.viewDetails')"
              @click="toggleExpanded(record)"
            >
              {{ t(expandedRowKeys.includes(record.event_id) ? 'auditLog.hide' : 'auditLog.view') }}
              <UpOutlined v-if="expandedRowKeys.includes(record.event_id)" />
              <DownOutlined v-else />
            </a-button>
          </template>
      </template>

      <template #expandedRowRender="{ record }">
        <div class="expanded-details">
          <dl class="detail-list">
            <template v-if="auditReason(record)">
              <dt>{{ t('auditLog.reason') }}</dt>
              <dd class="reason-value">{{ auditReason(record) }}</dd>
            </template>
            <dt>{{ t('auditLog.eventId') }}</dt>
            <dd class="event-id">{{ record.event_id || '-' }}</dd>
            <dt>{{ t('auditLog.originalJson') }}</dt>
            <dd>
              <a-button type="link" class="raw-json-link" :title="t('auditLog.rawHint')" @click="openRawRecord(record)">
                <FileSearchOutlined /> {{ t('auditLog.viewOriginalJson') }}
              </a-button>
            </dd>
          </dl>
        </div>
      </template>
    </a-table>

    <a-modal
      v-model:open="rawModalOpen"
      :title="t('auditLog.originalRecord')"
      :footer="null"
      width="min(900px, calc(100vw - 32px))"
    >
      <div class="raw-modal-actions">
        <a-button @click="copyRawRecord"><CopyOutlined /> {{ t('auditLog.copyJson') }}</a-button>
      </div>
      <pre class="raw-json">{{ rawRecordText }}</pre>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { CopyOutlined, DownOutlined, FileSearchOutlined, SearchOutlined, UpOutlined } from '@ant-design/icons-vue'
import { RouterLink } from 'vue-router'

import { getAuditPaged } from '../api'
import { translateDomain } from '../i18n'
import { domainMessages } from '../i18n/domain'
import { useLocaleText } from '../i18n/useLocaleText'
import { formatDateTime } from '../utils/format'
import { copyText, promptManualCopy } from '../utils/clipboard'

const { t } = useLocaleText()
const loading = ref(false)
const rows = ref([])
const loadError = ref('')
const expandedRowKeys = ref([])
const rawModalOpen = ref(false)
const rawRecordText = ref('')
const sortState = ref({ field: 'timestamp', order: 'descend' })
const filters = reactive({ keyword: '', eventType: 'all', sinceHours: 168 })
let requestSequence = 0

const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: value => t('auditLog.paginationTotal', { total: value }),
})

const columns = computed(() => [
  { title: t('auditLog.time'), dataIndex: 'timestamp', key: 'timestamp', width: 190, sorter: true, sortOrder: sortState.value.order },
  { title: t('auditLog.event'), dataIndex: 'event_type', key: 'event_type', width: 205 },
  { title: t('auditLog.object'), dataIndex: 'skill_name', key: 'object', width: 190 },
  { title: t('auditLog.agentSource'), dataIndex: 'agent_id', key: 'agent_source', width: 190 },
  { title: t('auditLog.actor'), dataIndex: 'actor', key: 'actor', width: 150 },
  { title: t('auditLog.view'), key: 'view', width: 100, align: 'center', fixed: 'right' },
])

const eventTypeOptions = computed(() => Object.keys(domainMessages['zh-CN'].auditEvent)
  .map(value => ({ value, label: eventLabel(value) })))

function eventLabel(value) {
  return translateDomain('auditEvent', value, t('auditLog.unknownEvent', { value: value || '-' }))
}

function eventTone(value) {
  if (['skill_rejected', 'skill_processing_failed', 'skill_load_blocked', 'skill_tamper_detected', 'tool_blocked', 'skill_blocked', 'skill_quarantined', 'skill_auto_install_failed'].includes(value)) return 'danger'
  if (['skill_approved', 'skill_signature_verified', 'skill_load_allowed', 'tool_invoked', 'skill_repaired', 'skill_quarantine_restored', 'skill_installed', 'unmanaged_skill_verified'].includes(value)) return 'success'
  if (['skill_vetted', 'skill_processing_completed', 'skill_modified', 'unmanaged_skill_found', 'skill_governance_detected'].includes(value)) return 'warning'
  return 'info'
}

function auditDetails(record) {
  return record?.details && typeof record.details === 'object' ? record.details : {}
}

function auditAgent(record) {
  return record.agent_id || auditDetails(record).agent_id || '-'
}

function auditIp(record) {
  return record.client_ip || auditDetails(record).client_ip || '-'
}

function auditActor(record) {
  const details = auditDetails(record)
  return details.token_name || details.token_prefix || record.actor || '-'
}

function auditReason(record) {
  const reason = auditDetails(record).reason
  if (reason === undefined || reason === null || reason === '') return ''
  return typeof reason === 'string' ? reason : JSON.stringify(reason, null, 2)
}

function formatJson(value) {
  if (value === undefined || value === null) return '{}'
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}

async function fetchAudit() {
  const requestId = ++requestSequence
  loading.value = true
  loadError.value = ''
  try {
    const response = await getAuditPaged({
      since_hours: filters.sinceHours,
      event_type: filters.eventType === 'all' ? undefined : filters.eventType,
      q: filters.keyword.trim() || undefined,
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
      sort_order: sortState.value.order === 'ascend' ? 'asc' : 'desc',
      limit: 1000,
    })
    if (requestId !== requestSequence) return
    rows.value = Array.isArray(response.items) ? response.items : []
    pagination.value = {
      ...pagination.value,
      current: Number(response.page || pagination.value.current),
      pageSize: Number(response.page_size || pagination.value.pageSize),
      total: Number(response.total || 0),
    }
    const availableKeys = new Set(rows.value.map(row => row.event_id))
    expandedRowKeys.value = expandedRowKeys.value.filter(key => availableKeys.has(key))
  } catch (error) {
    if (requestId !== requestSequence) return
    loadError.value = error.response?.data?.detail || t('auditLog.loadFailed')
    rows.value = []
    pagination.value = { ...pagination.value, total: 0 }
    expandedRowKeys.value = []
  } finally {
    if (requestId === requestSequence) loading.value = false
  }
}

function updateFilter(field, value) {
  filters[field] = value
  search()
}

function search() {
  pagination.value = { ...pagination.value, current: 1 }
  expandedRowKeys.value = []
  fetchAudit()
}

function resetFilters() {
  filters.keyword = ''
  filters.eventType = 'all'
  filters.sinceHours = 168
  sortState.value = { field: 'timestamp', order: 'descend' }
  search()
}

function handleTableChange(pager, _filters, sorter) {
  pagination.value = { ...pagination.value, current: pager.current, pageSize: pager.pageSize }
  if (sorter?.field === 'timestamp') {
    sortState.value = { field: 'timestamp', order: sorter.order || 'descend' }
  }
  fetchAudit()
}

function handleExpand(expanded, record) {
  const currentKeys = new Set(expandedRowKeys.value)
  if (expanded) currentKeys.add(record.event_id)
  else currentKeys.delete(record.event_id)
  expandedRowKeys.value = [...currentKeys]
}

function toggleExpanded(record) {
  handleExpand(!expandedRowKeys.value.includes(record.event_id), record)
}

function openRawRecord(record) {
  rawRecordText.value = formatJson(record)
  rawModalOpen.value = true
}

async function copyRawRecord() {
  try {
    await copyText(rawRecordText.value)
    message.success(t('auditLog.copied'))
  } catch {
    message.warning(t('auditLog.copyFailed'))
    promptManualCopy(rawRecordText.value, t('clipboard.manualCopyPrompt'))
  }
}

onMounted(fetchAudit)
</script>

<style scoped>
.audit-page { min-width: 0; padding: 0; }
.audit-heading { margin-bottom: 24px; }
.audit-heading h1 { margin: 0; color: #16243a; font-size: 28px; font-weight: 650; line-height: 1.35; }
.audit-heading p { margin: 8px 0 0; color: #778196; font-size: 15px; }
.audit-filters { display: grid; grid-template-columns: minmax(260px, 1.6fr) minmax(190px, 1fr) minmax(145px, .65fr) auto; gap: 12px; margin-bottom: 22px; }
.audit-filters :deep(.ant-select), .keyword-filter { width: 100%; }
.audit-error { margin-bottom: 16px; }
.time-value { white-space: nowrap; }
.event-cell, .stacked-value { display: inline-flex; align-items: flex-start; }
.event-cell { gap: 10px; align-items: center; }
.stacked-value { flex-direction: column; line-height: 1.5; }
.secondary-value { color: #8993a5; font-size: 13px; }
.event-dot { width: 9px; height: 9px; flex: none; border-radius: 50%; }
.event-dot--danger { background: #ef4444; }
.event-dot--success { background: #55b66b; }
.event-dot--warning { background: #f2a43a; }
.event-dot--info { background: #3184e7; }
.view-button { padding-inline: 4px; }
.expanded-details { padding: 8px 4px 8px 14px; border-left: 2px solid #3184e7; }
.detail-list { display: grid; grid-template-columns: 125px minmax(0, 1fr); gap: 10px 16px; margin: 0; }
.detail-list dt { color: #69758a; }
.detail-list dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.actor-value { overflow-wrap: anywhere; }
.reason-value { white-space: pre-wrap; }
.event-id { color: #59667c; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
.stacked-value { min-width: 0; max-width: 100%; overflow-wrap: anywhere; }
.stacked-value > * { max-width: 100%; overflow-wrap: anywhere; }
.raw-json { max-height: min(65vh, 700px); overflow: auto; margin: 0; padding: 12px; border-radius: 6px; background: #f5f7fa; color: #25344b; font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.raw-modal-actions { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.audit-page :deep(.ant-table-tbody > tr > td) { padding-top: 10px; padding-bottom: 10px; }
.audit-page :deep(.ant-table-tbody > tr.audit-row-expanded > td),
.audit-page :deep(.ant-table-tbody > tr.ant-table-expanded-row > td) { background: #f0f7ff; }
.audit-page :deep(.ant-table-cell.ant-table-column-sort) { background: inherit; }
@media (max-width: 1180px) {
  .audit-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .keyword-filter { grid-column: 1 / -1; }
}
@media (max-width: 520px) {
  .audit-heading h1 { font-size: 24px; }
  .audit-filters { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
  .audit-filters :deep(.ant-btn) { width: 100%; }
  .detail-list { grid-template-columns: 1fr; gap: 4px; }
  .detail-list dd + dt { margin-top: 8px; }
}
</style>
