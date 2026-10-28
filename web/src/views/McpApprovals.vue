<template>
  <div class="approval-page">
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="t('mcpApproval.title')" :sub-title="t('mcpApproval.subtitle')" />
      </template>

    <div class="stats-row">
      <button v-for="card in statisticCards" :key="card.key" type="button" class="statistic-card"
        :class="{ selected: statistic === card.key }" :aria-pressed="statistic === card.key" @click="selectStatistic(card.key)">
        <a-statistic :title="card.label" :value="stats[card.key]" :value-style="{ color: card.color }" />
      </button>
    </div>

    <section class="approval-card">
      <a-tabs v-model:activeKey="activeTab" @change="handleTabChange">
        <a-tab-pane key="pending" :tab="t('mcpApproval.pending')" />
        <a-tab-pane key="processed" :tab="t('mcpApproval.processed')" />
        <a-tab-pane key="all" :tab="t('mcpApproval.all')" />
      </a-tabs>

      <div v-if="statistic" class="statistic-filter">
        <span>{{ t('mcpApproval.statisticRange') }}：</span>
        <a-tag color="blue" closable @close.prevent="clearStatistic">{{ statisticCards.find(card => card.key === statistic)?.label }}</a-tag>
      </div>
      <div class="filter-bar">
        <a-space wrap class="filters">
          <a-input-search
            v-model:value="filters.q"
            :placeholder="t('mcpApproval.searchPlaceholder')"
            allow-clear
            class="search-input"
            @search="applyFilters"
          />
          <a-select v-model:value="filters.gateway_slug" allow-clear :placeholder="t('mcpApproval.gateway')" class="filter-control" @change="applyFilters">
            <a-select-option v-for="gateway in gateways" :key="gateway.slug" :value="gateway.slug">{{ gateway.name }}</a-select-option>
          </a-select>
          <a-input v-model:value="filters.tool_name" allow-clear :placeholder="t('mcpApproval.tool')" class="filter-control" @pressEnter="applyFilters" />
          <a-input v-model:value="filters.token_name" allow-clear :placeholder="t('mcpApproval.credentialName')" class="filter-control" @pressEnter="applyFilters" />
          <a-tooltip :title="t('mcpApproval.timeHelp')">
            <a-range-picker v-model:value="filters.timeRange" show-time class="date-filter" :placeholder="[t('mcpApproval.requestedFrom'), t('mcpApproval.requestedTo')]" @change="applyFilters" />
          </a-tooltip>
          <a-button type="primary" :loading="refreshing" @click="refreshManually">{{ t('mcpApproval.refresh') }}</a-button>
        </a-space>
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        row-key="request_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: t('mcpApproval.noRequests') }"
        :scroll="{ x: 1470 }"
        size="middle"
        @change="handleTableChange"
      >
        <template #headerCell="{ column }">
          <template v-if="column.key === 'expires_at'">
            {{ column.title }} <a-tooltip :title="t('mcpApproval.deadlineHelp')"><QuestionCircleOutlined /></a-tooltip>
          </template>
        </template>
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'requested_at'">{{ formatDateTime(record.created_at) }}</template>
          <template v-else-if="column.key === 'credential'">
            <div class="primary-text">{{ credentialLabel(record) }}</div>
            <div class="secondary-text">{{ record.token_prefix }}</div>
          </template>
          <template v-else-if="column.key === 'target'">
            <div class="primary-text">{{ record.gateway_name || record.gateway_slug }}</div>
            <div class="secondary-text">{{ record.server_slug }} → {{ record.tool_name }}</div>
          </template>
          <template v-else-if="column.key === 'approval_result'">
            <a-tag :color="statusColor(record.approval_result)">{{ statusLabel(record.approval_result) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'authorization_status'">
            <a-tag v-if="record.authorization_status" :color="statusColor(record.authorization_status)">{{ statusLabel(record.authorization_status) }}</a-tag>
            <span v-else>—</span>
          </template>
          <template v-else-if="column.key === 'expires_at'">{{ record.approval_result === 'rejected' ? '—' : formatDateTime(record.expires_at) }}</template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button type="link" @click="openDetails(record)">{{ t('mcpApproval.details') }}</a-button>
              <template v-if="record.status === 'pending'">
                <a-button v-if="hasAccess('mcp:approve')" type="link" :disabled="record.schema_changed" @click="openApprove(record)">{{ t('mcpApproval.approve') }}</a-button>
                <a-button v-if="hasAccess('mcp:reject')" type="link" danger @click="openReject(record)">{{ t('mcpApproval.reject') }}</a-button>
              </template>
            </a-space>
          </template>
        </template>
      </a-table>
    </section>

    </a-card>

    <a-drawer v-model:open="detailVisible" :title="t('mcpApproval.requestDetails')" width="720" destroy-on-close>
      <a-spin :spinning="detailLoading">
        <template v-if="detail">
          <a-alert v-if="detail.schema_changed" type="error" show-icon :message="t('mcpApproval.schemaChanged')" class="detail-alert" />
          <a-descriptions :title="t('mcpApproval.callSource')" bordered :column="2" size="small">
            <a-descriptions-item :label="t('mcpApproval.requestId')" :span="2"><code>{{ detail.request_id }}</code></a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.credential')">{{ credentialLabel(detail) }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.tokenPrefix')">{{ detail.token_prefix }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.sourceIp')">{{ detail.client_ip || '-' }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.requestedAt')">{{ formatDateTime(detail.created_at) }}</a-descriptions-item>
          </a-descriptions>

          <a-descriptions :title="t('mcpApproval.toolInformation')" bordered :column="2" size="small" class="detail-section">
            <a-descriptions-item :label="t('mcpApproval.gateway')">{{ detail.gateway_name || detail.gateway_slug }}</a-descriptions-item>
            <a-descriptions-item label="MCP Server">{{ detail.server_slug }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.tool')">{{ detail.tool_name }}</a-descriptions-item>
            <!-- 风险标签使用详情接口返回的等级。 -->
            <a-descriptions-item :label="t('mcpApproval.riskLevel')"><a-tag :color="riskColor(detail.risk_level)">{{ t(`mcpApproval.${detail.risk_level}Risk`) }}</a-tag></a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.schemaHash')" :span="2"><code>{{ detail.schema_hash }}</code></a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.currentSchemaHash')" :span="2"><code>{{ detail.current_schema_hash || '-' }}</code></a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.authorizationScope')" :span="2">{{ t('mcpApproval.authorizationScopeDescription') }}</a-descriptions-item>
          </a-descriptions>

          <div class="section-heading">
            <span>{{ t('mcpApproval.arguments') }}</span>
            <a-button v-if="!detail.arguments_revealed" type="link" :loading="revealing" @click="revealArguments">
              {{ t('mcpApproval.revealArguments') }}
            </a-button>
          </div>
          <a-alert type="info" show-icon :message="t('mcpApproval.argumentsContextOnly')" class="detail-alert" />
          <a-alert v-if="!detail.arguments_revealed" type="warning" show-icon :message="t('mcpApproval.maskedArguments')" :description="t('mcpApproval.rawArgumentsWarning')" class="detail-alert" />
          <pre class="arguments-json">{{ prettyArguments }}</pre>

          <a-descriptions :title="t('mcpApproval.reviewInformation')" bordered :column="2" size="small" class="detail-section">
            <a-descriptions-item :label="t('mcpApproval.approvalResult')"><a-tag :color="statusColor(detail.approval_result)">{{ statusLabel(detail.approval_result) }}</a-tag></a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.authorizationStatus')">
              <a-tag v-if="detail.authorization_status" :color="statusColor(detail.authorization_status)">{{ statusLabel(detail.authorization_status) }}</a-tag><span v-else>—</span>
            </a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.reviewedBy')">{{ detail.reviewed_by || '—' }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.reviewedAt')">{{ formatDateTime(detail.reviewed_at) }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.reviewComment')">{{ detail.review_comment || '-' }}</a-descriptions-item>
            <template v-if="detail.approval_result === 'approved'">
              <a-descriptions-item :label="t('mcpApproval.authorizationExpiresAt')">{{ formatDateTime(detail.expires_at) }}</a-descriptions-item>
              <a-descriptions-item :label="t('mcpApproval.useCount')">{{ detail.use_count || 0 }}</a-descriptions-item>
              <a-descriptions-item :label="t('mcpApproval.lastUsedAt')">{{ detail.last_used_at ? formatDateTime(detail.last_used_at) : '—' }}</a-descriptions-item>
            </template>
            <a-descriptions-item v-if="['pending', 'timed_out'].includes(detail.approval_result)" :label="t('mcpApproval.applicationDeadline')">{{ formatDateTime(detail.expires_at) }}</a-descriptions-item>
          </a-descriptions>

          <div v-if="detail.status === 'pending'" class="drawer-actions">
            <a-button v-if="hasAccess('mcp:reject')" danger @click="openReject(detail)">{{ t('mcpApproval.reject') }}</a-button>
            <a-button v-if="hasAccess('mcp:approve')" type="primary" :disabled="detail.schema_changed" @click="openApprove(detail)">{{ t('mcpApproval.approve') }}</a-button>
          </div>
        </template>
      </a-spin>
    </a-drawer>

    <a-modal
      v-model:open="approveVisible"
      :title="t('mcpApproval.approve')"
      :confirm-loading="submitting"
      :ok-text="t('mcpApproval.approve')"
      @ok="submitApprove"
    >
      <a-alert type="warning" show-icon :message="t('mcpApproval.confirmApprove')" class="modal-alert" />
      <a-form layout="vertical">
        <a-form-item :label="t('mcpApproval.approvalDuration')">
          <a-radio-group v-model:value="approveForm.ttl_seconds">
            <a-radio-button :value="60">{{ t('mcpApproval.oneMinute') }}</a-radio-button>
            <a-radio-button :value="300">{{ t('mcpApproval.fiveMinutes') }}</a-radio-button>
            <a-radio-button :value="600">{{ t('mcpApproval.tenMinutes') }}</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <a-form-item :label="t('mcpApproval.approvalComment')">
          <a-textarea v-model:value="approveForm.comment" :rows="3" :maxlength="1000" :placeholder="t('mcpApproval.approvalCommentPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="rejectVisible"
      :title="t('mcpApproval.reject')"
      :confirm-loading="submitting"
      :ok-text="t('mcpApproval.confirmReject')"
      ok-type="danger"
      @ok="submitReject"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('mcpApproval.rejectReason')" required>
          <a-textarea v-model:value="rejectReason" :rows="4" :maxlength="1000" :placeholder="t('mcpApproval.rejectReasonPlaceholder')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { can as hasAccess } from '../access'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'

import {
  approveMcpApprovalRequest,
  getMcpApprovalRequest,
  getMcpApprovalRequestStats,
  listMcpApprovalRequests,
  listMcpGateways,
  rejectMcpApprovalRequest,
} from '../api'
import { formatBeijingDateTime as formatDateTime } from '../utils/format'

const { t, te } = useI18n()
const route = useRoute()
const loading = ref(false)
const refreshing = ref(false)
const detailLoading = ref(false)
const revealing = ref(false)
const submitting = ref(false)
const activeTab = ref('pending')
const statistic = ref(undefined)
const rows = ref([])
const gateways = ref([])
const detail = ref(null)
const selectedRequest = ref(null)
const detailVisible = ref(false)
const approveVisible = ref(false)
const rejectVisible = ref(false)
const rejectReason = ref('')
const stats = reactive({ pending: 0, approved_today: 0, rejected_today: 0, timed_out_today: 0, approved_expired_today: 0 })
const filters = reactive({ q: '', gateway_slug: undefined, tool_name: '', token_name: '', timeRange: [] })
const approveForm = reactive({ ttl_seconds: 300, comment: '' })
const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: total => t('mcpApproval.total', { total }),
})

const columns = computed(() => [
  { title: t('mcpApproval.requestedAt'), key: 'requested_at', width: 180 },
  { title: t('mcpApproval.credential'), key: 'credential', width: 180 },
  { title: t('mcpApproval.tool'), key: 'target', width: 280 },
  { title: t('mcpApproval.sourceIp'), dataIndex: 'client_ip', key: 'client_ip', width: 140 },
  { title: t('mcpApproval.deadline'), key: 'expires_at', width: 180 },
  { title: t('mcpApproval.approvalResult'), key: 'approval_result', width: 120 },
  { title: t('mcpApproval.authorizationStatus'), key: 'authorization_status', width: 180 },
  { title: t('mcpApproval.actions'), key: 'actions', width: 210, fixed: 'right' },
])

// 删除状态由接口明确提供，列表和详情共用双语文案。
const credentialLabel = record => record.token_deleted ? t('mcpApproval.credentialDeleted') : record.token_name
const prettyArguments = computed(() => JSON.stringify(detail.value?.arguments || {}, null, 2))
const riskColor = risk => ({ low: 'green', medium: 'orange', high: 'red' }[risk])
const statusColor = status => ({ pending: 'orange', timed_out: 'orange', valid: 'green', approved: 'blue', rejected: 'red', used: 'green', expired: 'default', cancelled: 'default', active: 'blue' }[status] || 'default')
const statusLabel = status => te(`mcpApproval.${status}`) ? t(`mcpApproval.${status}`) : status
const statusFilter = () => ({ pending: 'pending', processed: 'approved,rejected,used,expired,cancelled', all: undefined }[activeTab.value])

const statisticCards = computed(() => [
  { key: 'pending', label: t('mcpApproval.pending'), color: '#cf1322' },
  { key: 'approved_today', label: t('mcpApproval.approvedToday'), color: '#3f8600' },
  { key: 'rejected_today', label: t('mcpApproval.rejectedToday') },
  { key: 'timed_out_today', label: t('mcpApproval.timedOutToday') },
  { key: 'approved_expired_today', label: t('mcpApproval.approvedExpiredToday') },
])

const emitStats = () => window.dispatchEvent(new CustomEvent('mcp-approval-stats', { detail: { ...stats } }))

let requestVersion = 0
let filterTimer
let disposed = false

const fetchStats = async version => {
  const data = await getMcpApprovalRequestStats()
  if (version !== requestVersion) return
  Object.assign(stats, data)
  emitStats()
}

const fetchRows = async () => {
  if (disposed) return
  const version = ++requestVersion
  loading.value = true
  try {
    const timeRange = filters.timeRange || []
    const data = await listMcpApprovalRequests({
      status: statusFilter(),
      statistic: statistic.value,
      q: filters.q.trim() || undefined,
      gateway_slug: filters.gateway_slug || undefined,
      tool_name: filters.tool_name.trim() || undefined,
      token_name: filters.token_name.trim() || undefined,
      // 按日期框可见的北京时间精确到秒，去掉不可见毫秒，保持筛选边界一致。
      created_from: timeRange[0] ? `${timeRange[0].format('YYYY-MM-DDTHH:mm:ss')}+08:00` : undefined,
      created_to: timeRange[1] ? `${timeRange[1].format('YYYY-MM-DDTHH:mm:ss')}+08:00` : undefined,
      page: pagination.current,
      page_size: pagination.pageSize,
    })
    // 连续筛选时只采用最新请求，避免旧列表与统计覆盖当前结果。
    if (version !== requestVersion) return
    rows.value = data.items || []
    pagination.total = Number(data.total || 0)
    await fetchStats(version)
  } catch (error) {
    if (version !== requestVersion) return
    message.error(error.response?.data?.detail || t('mcpApproval.loadFailed'))
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

const applyFilters = () => {
  window.clearTimeout(filterTimer)
  filterTimer = undefined
  pagination.current = 1
  return fetchRows()
}

const refreshManually = async () => {
  if (refreshing.value) return
  // 仅手动刷新驱动按钮转圈，筛选及标签切换仍使用列表加载状态。
  refreshing.value = true
  try {
    await applyFilters()
  } finally {
    refreshing.value = false
  }
}

const handleTabChange = () => {
  statistic.value = undefined
  return applyFilters()
}
const selectStatistic = key => {
  statistic.value = key
  activeTab.value = 'all'
  // 清空后统一查询，取消文本监听产生的防抖任务，保留每页数量。
  Object.assign(filters, { q: '', gateway_slug: undefined, tool_name: '', token_name: '', timeRange: [] })
  return applyFilters()
}
const clearStatistic = () => {
  statistic.value = undefined
  activeTab.value = 'all'
  return applyFilters()
}
const handleTableChange = next => {
  pagination.pageSize = next.pageSize
  // 待执行筛选优先回第一页，避免翻页取消防抖后查询错误页码。
  if (filterTimer !== undefined) {
    applyFilters()
    return
  }
  pagination.current = next.current
  fetchRows()
}

// 文本输入停止300毫秒后查询；回车、选择及刷新沿用立即查询入口。
watch(() => [filters.q, filters.tool_name, filters.token_name], () => {
  window.clearTimeout(filterTimer)
  requestVersion += 1
  filterTimer = window.setTimeout(applyFilters, 300)
}, { flush: 'sync' })

const openDetails = async record => {
  detailVisible.value = true
  detailLoading.value = true
  try {
    detail.value = await getMcpApprovalRequest(record.request_id)
  } catch (error) {
    message.error(error.response?.data?.detail || t('mcpApproval.loadFailed'))
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

const revealArguments = async () => {
  if (!detail.value || revealing.value) return
  revealing.value = true
  try {
    detail.value = await getMcpApprovalRequest(detail.value.request_id, true)
  } catch (error) {
    message.error(error.response?.data?.detail || t('mcpApproval.revealFailed'))
  } finally {
    revealing.value = false
  }
}

const openApprove = record => {
  selectedRequest.value = record
  approveForm.ttl_seconds = 300
  approveForm.comment = ''
  approveVisible.value = true
}

const openReject = record => {
  selectedRequest.value = record
  rejectReason.value = ''
  rejectVisible.value = true
}

const refreshAfterReview = async requestId => {
  await fetchRows()
  if (detailVisible.value && detail.value?.request_id === requestId) {
    detail.value = await getMcpApprovalRequest(requestId)
  }
}

const submitApprove = async () => {
  if (!selectedRequest.value || submitting.value) return
  submitting.value = true
  const requestId = selectedRequest.value.request_id
  try {
    await approveMcpApprovalRequest(requestId, { ...approveForm })
    approveVisible.value = false
    message.success(t('mcpApproval.approveSucceeded'))
    await refreshAfterReview(requestId)
  } catch (error) {
    message.error(error.response?.data?.detail || t('mcpApproval.operationFailed'))
  } finally {
    submitting.value = false
  }
}

const submitReject = async () => {
  if (!selectedRequest.value || submitting.value) return
  const reason = rejectReason.value.trim()
  if (!reason) {
    message.error(t('mcpApproval.rejectReasonPlaceholder'))
    return
  }
  submitting.value = true
  const requestId = selectedRequest.value.request_id
  try {
    await rejectMcpApprovalRequest(requestId, { reason })
    rejectVisible.value = false
    message.success(t('mcpApproval.rejectSucceeded'))
    await refreshAfterReview(requestId)
  } catch (error) {
    message.error(error.response?.data?.detail || t('mcpApproval.operationFailed'))
  } finally {
    submitting.value = false
  }
}

const openRequestedDetails = () => {
  const requestId = route.query.request_id
  if (typeof requestId === 'string' && requestId) openDetails({ request_id: requestId })
}
watch(() => route.query.request_id, openRequestedDetails)
onMounted(async () => {
  try {
    gateways.value = await listMcpGateways()
  } catch {
    gateways.value = []
  }
  await fetchRows()
  openRequestedDetails()
})

onUnmounted(() => {
  disposed = true
  requestVersion += 1
  window.clearTimeout(filterTimer)
})
</script>

<style scoped>
.stats-row { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 16px; margin: 8px 0 16px; }
.statistic-card { padding: 16px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; text-align: left; cursor: pointer; font: inherit; }
.statistic-card:hover, .statistic-card.selected { border-color: #1677ff; background: #f0f5ff; }
.statistic-card:focus-visible { outline: 2px solid #1677ff; outline-offset: 2px; }
.statistic-filter { margin-bottom: 12px; }
.approval-card { min-height: 520px; }
.filter-bar { display: block; width: 100%; margin-bottom: 16px; }
.filters { display: flex; width: 100%; }
.search-input { width: 300px; }
.filter-control { width: 180px; }
/* 为两个包含秒数的完整日期时间预留空间，筛选栏不足时整项换行。 */
.date-filter { width: 420px; max-width: 100%; }
.primary-text { color: rgba(0, 0, 0, 0.88); font-weight: 500; }
.secondary-text { color: rgba(0, 0, 0, 0.45); font-size: 12px; margin-top: 2px; }
.detail-section { margin-top: 20px; }
.detail-alert { margin-bottom: 16px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; margin: 20px 0 8px; font-weight: 600; }
.arguments-json { max-height: 360px; overflow: auto; margin: 0; padding: 14px; border: 1px solid #e5e7eb; border-radius: 6px; background: #f7f8fa; white-space: pre-wrap; word-break: break-word; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 24px; padding-top: 16px; border-top: 1px solid #f0f0f0; }
.modal-alert { margin-bottom: 16px; }
@media (max-width: 768px) {
  .stats-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filters :deep(.ant-space-item) { width: 100%; }
  .search-input, .filter-control, .date-filter { width: 100%; }
}
@media (max-width: 480px) {
  .date-filter { flex-wrap: wrap; }
  .date-filter :deep(.ant-picker-input) { flex: 1 0 100%; }
}
</style>
