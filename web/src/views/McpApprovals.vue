<template>
  <div class="approval-page">
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="t('mcpApproval.title')" :sub-title="t('mcpApproval.subtitle')" />
      </template>

    <a-row :gutter="[16, 16]" class="stats-row">
      <a-col :xs="12" :lg="6">
        <a-card size="small"><a-statistic :title="t('mcpApproval.pending')" :value="stats.pending" :value-style="{ color: '#cf1322' }" /></a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card size="small"><a-statistic :title="t('mcpApproval.approvedToday')" :value="stats.approved_today" :value-style="{ color: '#3f8600' }" /></a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card size="small"><a-statistic :title="t('mcpApproval.rejectedToday')" :value="stats.rejected_today" /></a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card size="small"><a-statistic :title="t('mcpApproval.expired')" :value="stats.expired" /></a-card>
      </a-col>
    </a-row>

    <section class="approval-card">
      <a-tabs v-model:activeKey="activeTab" @change="handleTabChange">
        <a-tab-pane key="pending" :tab="t('mcpApproval.pending')" />
        <a-tab-pane key="processed" :tab="t('mcpApproval.processed')" />
        <a-tab-pane key="all" :tab="t('mcpApproval.all')" />
      </a-tabs>

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
          <a-input v-model:value="filters.token_name" allow-clear :placeholder="t('mcpApproval.credential')" class="filter-control" @pressEnter="applyFilters" />
          <a-range-picker v-model:value="filters.timeRange" show-time class="date-filter" @change="applyFilters" />
          <a-button type="primary" :loading="loading" @click="applyFilters">{{ t('mcpApproval.refresh') }}</a-button>
        </a-space>
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        row-key="request_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: t('mcpApproval.noRequests') }"
        :scroll="{ x: 1180 }"
        size="middle"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'requested_at'">{{ formatDateTime(record.created_at) }}</template>
          <template v-else-if="column.key === 'credential'">
            <div class="primary-text">{{ record.token_name }}</div>
            <div class="secondary-text">{{ record.token_prefix }}</div>
          </template>
          <template v-else-if="column.key === 'target'">
            <div class="primary-text">{{ record.gateway_name || record.gateway_slug }}</div>
            <div class="secondary-text">{{ record.server_slug }} → {{ record.tool_name }}</div>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'expires_at'">{{ formatDateTime(record.expires_at) }}</template>
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
            <a-descriptions-item :label="t('mcpApproval.credential')">{{ detail.token_name }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.tokenPrefix')">{{ detail.token_prefix }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.sourceIp')">{{ detail.client_ip || '-' }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.requestedAt')">{{ formatDateTime(detail.created_at) }}</a-descriptions-item>
          </a-descriptions>

          <a-descriptions :title="t('mcpApproval.toolInformation')" bordered :column="2" size="small" class="detail-section">
            <a-descriptions-item :label="t('mcpApproval.gateway')">{{ detail.gateway_name || detail.gateway_slug }}</a-descriptions-item>
            <a-descriptions-item label="MCP Server">{{ detail.server_slug }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.tool')">{{ detail.tool_name }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.riskLevel')"><a-tag color="red">{{ t('mcpApproval.highRisk') }}</a-tag></a-descriptions-item>
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

          <a-descriptions v-if="detail.reviewed_at" :title="t('mcpApproval.reviewInformation')" bordered :column="2" size="small" class="detail-section">
            <a-descriptions-item :label="t('mcpApproval.status')"><a-tag :color="statusColor(detail.status)">{{ statusLabel(detail.status) }}</a-tag></a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.reviewedBy')">{{ detail.reviewed_by }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.reviewedAt')">{{ formatDateTime(detail.reviewed_at) }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.reviewComment')">{{ detail.review_comment || '-' }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.useCount')">{{ detail.use_count || 0 }}</a-descriptions-item>
            <a-descriptions-item :label="t('mcpApproval.lastUsedAt')">{{ detail.last_used_at ? formatDateTime(detail.last_used_at) : '-' }}</a-descriptions-item>
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

import {
  approveMcpApprovalRequest,
  getMcpApprovalRequest,
  getMcpApprovalRequestStats,
  listMcpApprovalRequests,
  listMcpGateways,
  rejectMcpApprovalRequest,
} from '../api'
import { formatDateTime } from '../utils/format'

const { t } = useI18n()
const route = useRoute()
const loading = ref(false)
const detailLoading = ref(false)
const revealing = ref(false)
const submitting = ref(false)
const activeTab = ref('pending')
const rows = ref([])
const gateways = ref([])
const detail = ref(null)
const selectedRequest = ref(null)
const detailVisible = ref(false)
const approveVisible = ref(false)
const rejectVisible = ref(false)
const rejectReason = ref('')
const stats = reactive({ pending: 0, approved_today: 0, rejected_today: 0, expired: 0 })
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
  { title: t('mcpApproval.expiresAt'), key: 'expires_at', width: 180 },
  { title: t('mcpApproval.status'), key: 'status', width: 110 },
  { title: t('mcpApproval.actions'), key: 'actions', width: 210, fixed: 'right' },
])

const prettyArguments = computed(() => JSON.stringify(detail.value?.arguments || {}, null, 2))
const statusColor = status => ({ pending: 'orange', approved: 'blue', rejected: 'red', used: 'green', expired: 'default', cancelled: 'default', active: 'blue' }[status] || 'default')
const statusLabel = status => t(`mcpApproval.${status}`)
const statusFilter = () => ({ pending: 'pending', processed: 'approved,rejected,used,expired,cancelled', all: undefined }[activeTab.value])

const emitStats = () => window.dispatchEvent(new CustomEvent('mcp-approval-stats', { detail: { ...stats } }))

const fetchStats = async () => {
  const data = await getMcpApprovalRequestStats()
  Object.assign(stats, data)
  emitStats()
}

const fetchRows = async () => {
  loading.value = true
  try {
    const timeRange = filters.timeRange || []
    const data = await listMcpApprovalRequests({
      status: statusFilter(),
      q: filters.q.trim() || undefined,
      gateway_slug: filters.gateway_slug || undefined,
      tool_name: filters.tool_name.trim() || undefined,
      token_name: filters.token_name.trim() || undefined,
      created_from: timeRange[0]?.toISOString(),
      created_to: timeRange[1]?.toISOString(),
      page: pagination.current,
      page_size: pagination.pageSize,
    })
    rows.value = data.items || []
    pagination.total = Number(data.total || 0)
    await fetchStats()
  } catch (error) {
    message.error(error.response?.data?.detail || t('mcpApproval.loadFailed'))
  } finally {
    loading.value = false
  }
}

const applyFilters = () => {
  pagination.current = 1
  fetchRows()
}

const handleTabChange = () => applyFilters()
const handleTableChange = next => {
  pagination.current = next.current
  pagination.pageSize = next.pageSize
  fetchRows()
}

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

let refreshTimer
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
  refreshTimer = window.setInterval(() => fetchRows(), 15000)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<style scoped>
.stats-row { margin: 8px 0 16px; }
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
  .filters :deep(.ant-space-item) { width: 100%; }
  .search-input, .filter-control, .date-filter { width: 100%; }
}
@media (max-width: 480px) {
  .date-filter { flex-wrap: wrap; }
  .date-filter :deep(.ant-picker-input) { flex: 1 0 100%; }
}
</style>
