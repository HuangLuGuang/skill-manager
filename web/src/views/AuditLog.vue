<template>
  <div>
    <a-page-header title="审计追踪" sub-title="按 Skill、Agent、来源 IP 和凭证追踪治理与运行事件" />

    <a-card style="margin-top: 16px">
      <a-space wrap style="margin-bottom: 16px">
        <a-input
          v-model:value="filters.keyword"
          placeholder="搜索 Skill / Agent / IP / 凭证 / Actor"
          style="width: 320px"
          allow-clear
        />
        <a-select v-model:value="filters.eventType" style="width: 220px" @change="handleFilterChange">
          <a-select-option value="all">全部事件</a-select-option>
          <a-select-option v-for="option in eventTypeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </a-select-option>
        </a-select>
        <a-select v-model:value="filters.sinceHours" style="width: 160px" @change="handleFilterChange">
          <a-select-option :value="24">最近 24 小时</a-select-option>
          <a-select-option :value="168">最近 7 天</a-select-option>
          <a-select-option :value="720">最近 30 天</a-select-option>
        </a-select>
        <a-button type="primary" @click="fetchAudit" :loading="loading">查询</a-button>
        <a-button @click="resetFilters" :disabled="loading">重置</a-button>
      </a-space>

      <div class="table-meta">
        共 {{ total }} 条，当前显示第 {{ pagination.current }} 页
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        rowKey="event_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: '当前筛选条件下没有审计事件' }"
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
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import { getAuditPaged } from '../api'
import { formatDateTime } from '../utils/format'

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
  showTotal: (value) => `共 ${value} 条`,
})
const filters = reactive({
  keyword: '',
  eventType: 'all',
  sinceHours: 168,
})

const columns = [
  { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 220, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: '事件', dataIndex: 'event_type', key: 'event_type', width: 180, sorter: true },
  { title: 'Skill', dataIndex: 'skill_name', key: 'skill_name', width: 220, sorter: true },
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id', width: 170 },
  { title: '来源 IP', dataIndex: 'client_ip', key: 'client_ip', width: 140 },
  { title: '凭证/Actor', dataIndex: 'actor', key: 'actor', width: 170, sorter: true },
  { title: '详情', dataIndex: 'details', key: 'details' },
]

const eventTypeOptions = [
  { value: 'skill_submitted', label: 'Skill 已提交' },
  { value: 'skill_processing_started', label: '开始分析 Skill' },
  { value: 'skill_processing_completed', label: '分析完成' },
  { value: 'skill_vetted', label: '进入审核' },
  { value: 'skill_approved', label: '审核通过' },
  { value: 'skill_rejected', label: '审核拒绝' },
  { value: 'skill_signature_verified', label: '完整性校验通过' },
  { value: 'skill_load_allowed', label: '允许加载 Skill' },
  { value: 'skill_load_blocked', label: '阻止加载 Skill' },
  { value: 'skill_tamper_detected', label: '发现内容不一致' },
  { value: 'tool_invoked', label: '允许工具调用' },
  { value: 'tool_blocked', label: '阻止工具调用' },
  { value: 'unmanaged_skill_found', label: '终端发现未受管 Skill' },
  { value: 'unmanaged_skill_verified', label: '终端校验未受管 Skill' },
  { value: 'skill_modified', label: '终端发现 Skill 修改' },
  { value: 'skill_repaired', label: '终端已恢复批准版本' },
  { value: 'skill_blocked', label: '终端已阻止异常 Skill' },
  { value: 'skill_quarantined', label: '终端已隔离 Skill' },
  { value: 'skill_quarantine_restored', label: '终端已恢复隔离 Skill' },
  { value: 'skill_installed', label: '终端已安装 Skill' },
  { value: 'skill_removed', label: '终端已移除 Skill' },
]
const eventLabelMap = Object.fromEntries(eventTypeOptions.map((item) => [item.value, item.label]))

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
    message.error(error.response?.data?.detail || '获取审计日志失败')
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

const eventLabel = (value) => eventLabelMap[value] || value || '-'
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
    status: '状态',
    reason: '原因',
    tool: '工具',
    allowed: '结果',
    verification_mode: '校验方式',
    risk_level: '风险',
    decision: '结论',
    reviewer: '审核人',
    approver: '审批人',
    source: '来源',
    client_id: '终端 ID',
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
    if (key === 'source' && value === 'managed_client') return '终端客户端'
    if (value === true) return '允许'
    if (value === false) return '拒绝'
    return value
  }
  return Object.entries(details || {})
    .filter(([key, value]) => !hidden.has(key) && value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${labels[key] || key}: ${displayValue(key, value)}`)
    .join('；') || '-'
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
