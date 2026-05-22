<template>
  <div>
    <a-page-header title="审计日志" sub-title="查看审计事件与治理痕迹" />

    <a-card style="margin-top: 16px">
      <a-space wrap style="margin-bottom: 16px">
        <a-input
          v-model:value="filters.keyword"
          placeholder="搜索技能名称 / Skill ID / Actor"
          style="width: 280px"
          allow-clear
        />
        <a-select v-model:value="filters.eventType" style="width: 220px">
          <a-select-option value="all">全部事件</a-select-option>
          <a-select-option value="skill_submitted">skill_submitted</a-select-option>
          <a-select-option value="skill_approved">skill_approved</a-select-option>
          <a-select-option value="skill_rejected">skill_rejected</a-select-option>
          <a-select-option value="skill_deployed">skill_deployed</a-select-option>
          <a-select-option value="skill_retired">skill_retired</a-select-option>
          <a-select-option value="skill_load_allowed">skill_load_allowed</a-select-option>
          <a-select-option value="skill_load_blocked">skill_load_blocked</a-select-option>
          <a-select-option value="tool_invoked">tool_invoked</a-select-option>
          <a-select-option value="tool_blocked">tool_blocked</a-select-option>
        </a-select>
        <a-select v-model:value="filters.sinceHours" style="width: 160px">
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
            <a v-if="record.skill_id" @click="$router.push(`/skills/${record.skill_id}`)">
              {{ record.skill_name || record.skill_id }}
            </a>
            <span v-else>{{ record.skill_name || '-' }}</span>
          </template>
          <template v-else-if="column.key === 'details'">
            <span>{{ formatDetails(record.details) }}</span>
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
import { formatDateTime, formatDetails } from '../utils/format'

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
  { title: '事件类型', dataIndex: 'event_type', key: 'event_type', width: 190, sorter: true },
  { title: 'Skill', dataIndex: 'skill_name', key: 'skill_name', width: 220, sorter: true },
  { title: 'Actor', dataIndex: 'actor', key: 'actor', width: 160, sorter: true },
  { title: 'Details', dataIndex: 'details', key: 'details' },
]

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

onMounted(fetchAudit)
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
