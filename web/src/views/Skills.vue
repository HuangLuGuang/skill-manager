<template>
  <div>
    <a-page-header title="技能注册表" sub-title="查看已注册的 AI Agent 技能并进入详情页" />

    <a-card style="margin-top: 16px">
      <a-space wrap style="margin-bottom: 16px">
        <a-input
          v-model:value="keyword"
          placeholder="搜索技能名称 / ID / 审批人"
          style="width: 280px"
          allow-clear
          @pressEnter="handleKeywordSearch"
          @change="handleKeywordInputChange"
        />
        <a-select v-model:value="status" style="width: 160px">
          <a-select-option value="all">全部状态</a-select-option>
          <a-select-option value="VETTED">VETTED</a-select-option>
          <a-select-option value="APPROVED">APPROVED</a-select-option>
          <a-select-option value="DEPLOYED">DEPLOYED</a-select-option>
          <a-select-option value="REJECTED">REJECTED</a-select-option>
          <a-select-option value="RETIRED">RETIRED</a-select-option>
        </a-select>
        <a-select v-model:value="risk" style="width: 160px">
          <a-select-option value="all">全部风险</a-select-option>
          <a-select-option value="benign">安全</a-select-option>
          <a-select-option value="suspicious">可疑</a-select-option>
          <a-select-option value="malicious">恶意</a-select-option>
        </a-select>
        <a-select v-model:value="sandboxFilter" style="width: 180px">
          <a-select-option value="all">全部 Sandbox</a-select-option>
          <a-select-option value="triggered">仅已触发</a-select-option>
          <a-select-option value="policy">仅策略强制</a-select-option>
        </a-select>
        <a-button type="primary" @click="handleKeywordSearch" :loading="loading">查询</a-button>
        <a-button @click="resetFilters" :disabled="loading">重置</a-button>
        <a-button @click="fetchSkills" :loading="loading">刷新</a-button>
        <a-button type="primary" @click="$router.push('/submit')">提交技能</a-button>
      </a-space>

      <div class="table-meta">
        共 {{ total }} 条，当前显示第 {{ pagination.current }} 页
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        rowKey="skill_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: '暂无技能数据' }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.name }}</a>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'risk'">
            <a-tag v-if="record.status === 'PENDING'" color="default">-</a-tag>
            <a-tag v-else-if="record.risk_level === 'malicious'" color="red">恶意</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange">可疑</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green">安全</a-tag>
            <a-tag v-else color="default">-</a-tag>
          </template>
          <template v-else-if="column.key === 'sandbox'">
            <a-space wrap>
              <a-tag v-if="record.sandbox_triggered" color="blue">{{ record.sandbox_runtime || 'sandbox' }}</a-tag>
              <a-tag v-if="record.sandbox_required_by_policy" color="orange">策略强制</a-tag>
              <span v-if="!record.sandbox_triggered" style="color: #8c8c8c">-</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button size="small" @click="$router.push(`/skills/${record.skill_id}`)">详情</a-button>
              <a-button size="small" @click="$router.push('/deployments')">部署</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'

import { listSkillsPaged } from '../api'
import { formatDateTime } from '../utils/format'

const keyword = ref('')
const status = ref('all')
const risk = ref('all')
const sandboxFilter = ref('all')
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const sortState = ref({ field: 'submitted_at', order: 'descend' })
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: (value) => `共 ${value} 条`,
})

const columns = [
  { title: '技能名称', dataIndex: 'name', key: 'name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', sorter: true },
  { title: '状态', dataIndex: 'status', key: 'status', width: 140, sorter: true },
  { title: '风险', dataIndex: 'risk_level', key: 'risk', width: 120, sorter: true },
  { title: 'Sandbox', key: 'sandbox', width: 180 },
  { title: '审批人', dataIndex: 'approved_by', key: 'approved_by', width: 160, sorter: true },
  { title: '提交时间', dataIndex: 'submitted_at', key: 'submitted_at', width: 190, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: '操作', key: 'actions', width: 140 },
]

const fetchSkills = async () => {
  loading.value = true
  try {
    const res = await listSkillsPaged({
      status: status.value === 'all' ? undefined : status.value,
      risk_level: risk.value === 'all' ? undefined : risk.value,
      sandbox_triggered: sandboxFilter.value === 'triggered' ? true : undefined,
      sandbox_required_by_policy: sandboxFilter.value === 'policy' ? true : undefined,
      q: keyword.value.trim() || undefined,
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
      sort_by: sortState.value.field,
      sort_order: sortState.value.order === 'ascend' ? 'asc' : 'desc',
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
    message.error(error.response?.data?.detail || '获取技能注册表失败')
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const handleKeywordSearch = () => {
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchSkills()
}

const handleKeywordInputChange = (event) => {
  const nextValue = event?.target?.value ?? ''
  if (String(nextValue).trim()) return
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchSkills()
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
  fetchSkills()
}

const resetFilters = () => {
  keyword.value = ''
  status.value = 'all'
  risk.value = 'all'
  sandboxFilter.value = 'all'
  sortState.value = { field: 'submitted_at', order: 'descend' }
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchSkills()
}

const statusColor = (value) =>
  ({
    PENDING: 'gold',
    VETTED: 'orange',
    APPROVED: 'green',
    DEPLOYED: 'blue',
    REJECTED: 'red',
    RETIRED: 'default',
  }[value] || 'default')

const riskColor = (value) =>
  ({
    benign: 'green',
    suspicious: 'orange',
    malicious: 'red',
  }[value] || 'default')

onMounted(fetchSkills)

watch([status, risk, sandboxFilter], () => {
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchSkills()
})
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
