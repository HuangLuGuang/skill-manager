<template>
  <div>
    <a-page-header :title="$t('legacy.13omz3w')" :sub-title="$t('legacy.1n43afx')" />

    <a-card style="margin-top: 16px">
      <a-space wrap style="margin-bottom: 16px">
        <a-input
          v-model:value="filters.keyword"
          :placeholder="$t('legacy.9c551d')"
          style="width: 320px"
          allow-clear
        />
        <a-select v-model:value="filters.eventType" style="width: 220px" @change="handleFilterChange">
          <a-select-option value="all">{{ $t("legacy.1mh2ng") }}</a-select-option>
          <a-select-option v-for="option in eventTypeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </a-select-option>
        </a-select>
        <a-select v-model:value="filters.sinceHours" style="width: 160px" @change="handleFilterChange">
          <a-select-option :value="24">{{ $t("legacy.11z4msh") }}</a-select-option>
          <a-select-option :value="168">{{ $t("legacy.o4woaw") }}</a-select-option>
          <a-select-option :value="720">{{ $t("legacy.1v9ts3m") }}</a-select-option>
        </a-select>
        <a-button type="primary" @click="fetchAudit" :loading="loading">{{ text('查询', 'Search') }}</a-button>
        <a-button @click="resetFilters" :disabled="loading">{{ text('重置', 'Reset') }}</a-button>
      </a-space>

      <div class="table-meta">
        {{ auditMetaText }}
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        rowKey="event_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: $t('legacy.1m9w9ti') }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'skill_name'">
            <a v-if="record.skill_id && record.skill_id !== 'unknown'" @click="$router.push(`/skills/${record.skill_id}`)">
              {{ record.skill_name || record.skill_id }}
            </a>
            <span v-else>{{ record.skill_name || '-' }}</span>
          </template>
          <template v-else-if="column.key === 'event_type'">
            <a-tag :color="eventColor(record.event_type)">{{ eventLabel(record.event_type) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'agent_id'">
            <span>{{ auditAgent(record) }}</span>
          </template>
          <template v-else-if="column.key === 'client_ip'">
            <span>{{ auditIp(record) }}</span>
          </template>
          <template v-else-if="column.key === 'actor'">
            <span>{{ auditActor(record) }}</span>
          </template>
          <template v-else-if="column.key === 'details'">
            <span>{{ formatAuditDetails(record.details) }}</span>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import { getAuditPaged } from '../api'
import { translateDomain } from '../i18n'
import { useLocaleText } from '../i18n/useLocaleText'
import { formatDateTime } from '../utils/format'

const { phrase, text } = useLocaleText()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const sortState = ref({ field: 'timestamp', order: 'descend' })
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: (value) => text(`共 ${value} 条`, `${value} total`),
})
const filters = reactive({
  keyword: '',
  eventType: 'all',
  sinceHours: 168,
})
const auditMetaText = computed(() => text(
  `共 ${total.value} 条，当前显示第 ${pagination.value.current} 页`,
  `${total.value} total, page ${pagination.value.current}`,
))

const columns = computed(() => [
  { title: text('时间', 'Time'), dataIndex: 'timestamp', key: 'timestamp', width: 220, sorter: true, customRender: ({ text: value }) => formatDateTime(value) },
  { title: text('事件', 'Event'), dataIndex: 'event_type', key: 'event_type', width: 180, sorter: true },
  { title: 'Skill', dataIndex: 'skill_name', key: 'skill_name', width: 220, sorter: true },
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id', width: 170 },
  { title: text('来源 IP', 'Source IP'), dataIndex: 'client_ip', key: 'client_ip', width: 140 },
  { title: text('凭证/Actor', 'Credential / Actor'), dataIndex: 'actor', key: 'actor', width: 170, sorter: true },
  { title: text('详情', 'Details'), dataIndex: 'details', key: 'details' },
])

const eventTypeOptions = computed(() => [
  { value: 'skill_submitted', label: text('Skill 已提交', 'Skill Submitted') },
  { value: 'skill_processing_started', label: text('开始分析 Skill', 'Skill Analysis Started') },
  { value: 'skill_processing_completed', label: text('分析完成', 'Analysis Completed') },
  { value: 'skill_vetted', label: text('进入审核', 'Queued for Review') },
  { value: 'skill_approved', label: text('审核通过', 'Approved') },
  { value: 'skill_rejected', label: text('审核拒绝', 'Rejected') },
  { value: 'skill_signature_verified', label: text('完整性校验通过', 'Integrity Verified') },
  { value: 'skill_load_allowed', label: text('允许加载 Skill', 'Skill Load Allowed') },
  { value: 'skill_load_blocked', label: text('阻止加载 Skill', 'Skill Load Blocked') },
  { value: 'skill_tamper_detected', label: text('发现内容不一致', 'Content Mismatch Detected') },
  { value: 'tool_invoked', label: text('允许工具调用', 'Tool Invocation Allowed') },
  { value: 'tool_blocked', label: text('阻止工具调用', 'Tool Invocation Blocked') },
  { value: 'unmanaged_skill_found', label: text('客户端发现未受管 Skill', 'Unmanaged Skill Found by Client') },
  { value: 'unmanaged_skill_verified', label: text('客户端校验未受管 Skill', 'Unmanaged Skill Verified by Client') },
  { value: 'skill_modified', label: text('客户端发现 Skill 修改', 'Skill Modification Detected by Client') },
  { value: 'skill_repaired', label: text('客户端已恢复批准版本', 'Approved Version Restored by Client') },
  { value: 'skill_blocked', label: text('客户端已阻止异常 Skill', 'Abnormal Skill Blocked by Client') },
  { value: 'skill_quarantined', label: text('客户端已隔离 Skill', 'Skill Quarantined by Client') },
  { value: 'skill_quarantine_restored', label: text('客户端已恢复隔离 Skill', 'Quarantined Skill Restored by Client') },
  { value: 'skill_installed', label: text('客户端已安装 Skill', 'Skill Installed by Client') },
  { value: 'skill_removed', label: text('客户端已移除 Skill', 'Skill Removed by Client') },
])

const fetchAudit = async () => {
  loading.value = true
  try {
    const res = await getAuditPaged({
      since_hours: filters.sinceHours,
      event_type: filters.eventType === 'all' ? undefined : filters.eventType,
      q: filters.keyword.trim() || undefined,
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
      sort_order: sortState.value.order === 'ascend' ? 'asc' : 'desc',
      limit: 1000,
    })
    rows.value = Array.isArray(res.items) ? res.items : []
    total.value = Number(res.total || 0)
    pagination.value = {
      ...pagination.value,
      total: total.value,
      current: Number(res.page || pagination.value.current),
      pageSize: Number(res.page_size || pagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1c7uw70'))
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const handleTableChange = (pager, _filters, sorter) => {
  pagination.value = {
    ...pagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    sortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchAudit()
}

const handleFilterChange = () => {
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchAudit()
}

const resetFilters = () => {
  filters.keyword = ''
  filters.eventType = 'all'
  filters.sinceHours = 168
  sortState.value = { field: 'timestamp', order: 'descend' }
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchAudit()
}

const eventLabel = (value) => translateDomain(
  'auditEvent',
  value,
  eventTypeOptions.value.find((item) => item.value === value)?.label || value || '-',
)
const eventColor = (value) => {
  if (['skill_rejected', 'skill_load_blocked', 'skill_tamper_detected', 'tool_blocked', 'skill_blocked', 'skill_quarantined'].includes(value)) return 'red'
  if (['skill_approved', 'skill_signature_verified', 'skill_load_allowed', 'tool_invoked', 'skill_repaired', 'skill_quarantine_restored', 'skill_installed', 'unmanaged_skill_verified'].includes(value)) return 'green'
  if (['skill_vetted', 'skill_processing_completed', 'skill_modified', 'unmanaged_skill_found'].includes(value)) return 'orange'
  return 'blue'
}
const auditDetails = (record) => (record?.details && typeof record.details === 'object' ? record.details : {})
const auditAgent = (record) => record.agent_id || auditDetails(record).agent_id || record.actor || '-'
const auditIp = (record) => record.client_ip || auditDetails(record).client_ip || '-'
const auditActor = (record) => {
  const details = auditDetails(record)
  if (details.token_name) return details.token_name
  if (details.token_prefix) return details.token_prefix
  return record.actor || '-'
}
const formatAuditDetails = (details = {}) => {
  const labels = {
    status: text('状态', 'Status'),
    reason: text('原因', 'Reason'),
    tool: text('工具', 'Tool'),
    allowed: text('结果', 'Result'),
    verification_mode: text('校验方式', 'Verification Mode'),
    risk_level: text('风险', 'Risk'),
    decision: text('结论', 'Decision'),
    reviewer: text('审核人', 'Reviewer'),
    approver: text('审批人', 'Approver'),
    source: text('来源', 'Source'),
    client_id: text('客户端 ID', 'Client ID'),
  }
  const hidden = new Set([
    'agent_id',
    'client_ip',
    'token_id',
    'token_name',
    'token_type',
    'token_prefix',
    'bound_agent_id',
    'user_id',
    'group_id',
  ])
  const displayValue = (key, value) => {
    if (key === 'source' && value === 'managed_client') return text('受管客户端', 'Managed Client')
    if (value === true) return text('允许', 'Allowed')
    if (value === false) return text('拒绝', 'Denied')
    return typeof value === 'string' ? phrase(value) : value
  }
  return Object.entries(details || {})
    .filter(([key, value]) => !hidden.has(key) && value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${labels[key] || key}: ${displayValue(key, value)}`)
    .join(text('；', '; ')) || '-'
}

onMounted(fetchAudit)
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
