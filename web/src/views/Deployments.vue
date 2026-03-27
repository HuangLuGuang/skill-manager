<template>
  <div>
    <a-page-header title="部署管理" sub-title="查看可部署 Skill 并执行部署或退役" />

    <a-card style="margin-top: 16px">
      <a-space style="margin-bottom: 16px" wrap>
        <a-segmented v-model:value="activeTab" :options="tabs" />
        <a-select v-model:value="risk" style="width: 160px">
          <a-select-option value="all">全部风险</a-select-option>
          <a-select-option value="LOW">LOW</a-select-option>
          <a-select-option value="MEDIUM">MEDIUM</a-select-option>
          <a-select-option value="HIGH">HIGH</a-select-option>
          <a-select-option value="EXTREME">EXTREME</a-select-option>
        </a-select>
        <a-input v-model:value="keyword" placeholder="搜索技能名称 / ID" style="width: 240px" allow-clear />
        <a-button type="primary" @click="fetchRows" :loading="loading">查询</a-button>
        <a-button @click="resetFilters" :disabled="loading">重置</a-button>
        <a-button @click="fetchRows" :loading="loading">刷新</a-button>
      </a-space>

      <div class="table-meta">
        共 {{ total }} 条，当前视图为 {{ activeTab === 'ready' ? '可部署' : '已部署' }}
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        rowKey="skill_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: activeTab === 'ready' ? '当前没有可部署 Skill' : '当前没有已部署 Skill' }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.name }}</a>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'risk_level'">
            <a-tag :color="riskColor(record.risk_level)">{{ record.risk_level || '-' }}</a-tag>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button
                v-if="record.status === 'APPROVED'"
                size="small"
                type="primary"
                :loading="actionLoading && selectedRecord?.skill_id === record.skill_id && deployMode"
                @click="handleDeploy(record)"
              >
                部署
              </a-button>
              <a-button
                v-if="record.status === 'DEPLOYED'"
                size="small"
                danger
                @click="openRetireModal(record)"
              >
                退役
              </a-button>
              <a-button size="small" @click="$router.push(`/skills/${record.skill_id}`)">详情</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="retireModalOpen"
      title="退役 Skill"
      ok-text="确认退役"
      cancel-text="取消"
      :confirm-loading="actionLoading"
      @ok="submitRetire"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="selectedRecord?.name || ''" disabled />
        </a-form-item>
        <a-form-item label="执行人">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item label="退役原因" required>
          <a-textarea v-model:value="retireReason" :rows="4" placeholder="请输入退役原因" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import { deploySkill, listSkillsPaged, retireSkill } from '../api'
import { formatDateTime } from '../utils/format'

const activeTab = ref('ready')
const risk = ref('all')
const keyword = ref('')
const loading = ref(false)
const actionLoading = ref(false)
const deployMode = ref(false)
const rows = ref([])
const total = ref(0)
const selectedRecord = ref(null)
const retireModalOpen = ref(false)
const retireReason = ref('')
const sortState = ref({ field: 'submitted_at', order: 'descend' })
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: (value) => `共 ${value} 条`,
})

const tabs = [
  { label: 'Ready To Deploy', value: 'ready' },
  { label: 'Deployed', value: 'deployed' },
]

const columns = [
  { title: '技能名称', dataIndex: 'name', key: 'name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', sorter: true },
  { title: '状态', dataIndex: 'status', key: 'status', width: 140, sorter: true },
  { title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 120, sorter: true },
  { title: '提交时间', dataIndex: 'submitted_at', key: 'submitted_at', width: 190, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: '操作', key: 'actions', width: 220 },
]

const fetchRows = async () => {
  loading.value = true
  try {
    const res = await listSkillsPaged({
      status: activeTab.value === 'ready' ? 'APPROVED' : 'DEPLOYED',
      risk_level: risk.value === 'all' ? undefined : risk.value,
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
    message.error(error.response?.data?.detail || '获取部署列表失败')
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const currentUser = () => localStorage.getItem('username') || 'admin'

const handleDeploy = async (record) => {
  selectedRecord.value = record
  actionLoading.value = true
  deployMode.value = true
  try {
    await deploySkill(record.skill_id)
    message.success(`已部署 ${record.name}`)
    fetchRows()
  } catch (error) {
    message.error(error.response?.data?.detail || '部署失败')
  } finally {
    actionLoading.value = false
    deployMode.value = false
  }
}

const openRetireModal = (record) => {
  selectedRecord.value = record
  retireReason.value = ''
  retireModalOpen.value = true
}

const submitRetire = async () => {
  if (!selectedRecord.value) return
  if (!retireReason.value.trim()) {
    message.warning('请输入退役原因')
    return
  }
  actionLoading.value = true
  try {
    await retireSkill(selectedRecord.value.skill_id, { actor: currentUser(), reason: retireReason.value.trim() })
    message.success(`已退役 ${selectedRecord.value.name}`)
    retireModalOpen.value = false
    fetchRows()
  } catch (error) {
    message.error(error.response?.data?.detail || '退役失败')
  } finally {
    actionLoading.value = false
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
  fetchRows()
}

const resetFilters = () => {
  risk.value = 'all'
  keyword.value = ''
  sortState.value = { field: 'submitted_at', order: 'descend' }
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchRows()
}

const statusColor = (value) =>
  ({
    APPROVED: 'green',
    DEPLOYED: 'blue',
  }[value] || 'default')

const riskColor = (value) =>
  ({
    SAFE: 'green',
    LOW: 'green',
    MEDIUM: 'orange',
    HIGH: 'red',
    EXTREME: 'magenta',
  }[value] || 'default')

onMounted(fetchRows)
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
