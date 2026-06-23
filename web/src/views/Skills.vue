<template>
  <div>
    <a-page-header title="Skill 列表" sub-title="查看已提交的 Skill 并进入详情页" />

    <a-card style="margin-top: 16px">
      <a-space wrap style="margin-bottom: 16px">
        <a-input
          v-model:value="keyword"
          placeholder="搜索 Skill 名称 / ID / 审批人"
          style="width: 280px"
          allow-clear
          @pressEnter="handleKeywordSearch"
          @change="handleKeywordInputChange"
        />
        <a-select v-model:value="status" style="width: 260px">
          <a-select-option value="all">全部状态</a-select-option>
          <a-select-option v-for="item in statusOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </a-select-option>
        </a-select>
        <a-select v-model:value="risk" style="width: 160px">
          <a-select-option value="all">全部风险</a-select-option>
          <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </a-select-option>
        </a-select>
        <a-select v-model:value="sandboxFilter" style="width: 180px">
          <a-select-option value="all">全部 Sandbox</a-select-option>
          <a-select-option value="triggered">仅已触发</a-select-option>
          <a-select-option value="policy">仅策略强制</a-select-option>
        </a-select>
        <a-button type="primary" @click="handleKeywordSearch" :loading="loading">查询</a-button>
        <a-button @click="resetFilters" :disabled="loading">重置</a-button>
        <a-button @click="fetchSkills" :loading="loading">刷新</a-button>
        <a-button type="primary" @click="$router.push('/submit')">提交 Skill</a-button>
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
        :locale="{ emptyText: '暂无 Skill 数据' }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.name }}</a>
          </template>
          <template v-else-if="column.key === 'skill_id'">
            <a-tooltip :title="record.skill_id">
              <span class="short-id">{{ shortId(record.skill_id) }}</span>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusDisplay(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'risk'">
            <a-tag v-if="record.status === 'PENDING'" color="default">-</a-tag>
            <a-tag v-else-if="record.risk_level === 'malicious'" color="red">{{ riskDisplay(record.risk_level) }}</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange">{{ riskDisplay(record.risk_level) }}</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green">{{ riskDisplay(record.risk_level) }}</a-tag>
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
            <a-space class="actions-cell">
              <a @click="$router.push(`/skills/${record.skill_id}`)">详情</a>
              <a-divider type="vertical" />
              <a-dropdown>
                <a class="ant-dropdown-link" @click.prevent>
                  更多 <DownOutlined />
                </a>
                <template #overlay>
                  <a-menu>
                    <a-menu-item
                      :disabled="record.status === 'PENDING' || Boolean(actionKey)"
                      @click="handleRescan(record)"
                    >
                      {{ actionKey === `rescan:${record.skill_id}` ? '重新检测中...' : '重新检测' }}
                    </a-menu-item>
                    <a-menu-item
                      v-if="record.status === 'APPROVED'"
                      :disabled="Boolean(actionKey)"
                      @click="handleDeploy(record)"
                    >
                      {{ actionKey === `deploy:${record.skill_id}` ? '部署中...' : '标记部署' }}
                    </a-menu-item>
                    <a-menu-item
                      v-if="record.status === 'DEPLOYED'"
                      :disabled="Boolean(actionKey)"
                      @click="openRetireModal(record)"
                    >
                      退役
                    </a-menu-item>
                    <a-menu-divider />
                    <a-menu-item
                      danger
                      :disabled="Boolean(actionKey)"
                      @click="confirmDelete(record)"
                    >
                      {{ actionKey === `delete:${record.skill_id}` ? '删除中...' : '删除' }}
                    </a-menu-item>
                  </a-menu>
                </template>
              </a-dropdown>
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
      :confirm-loading="actionKey === `retire:${selectedRecord?.skill_id}`"
      @ok="submitRetire"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="selectedRecord?.name || ''" disabled />
        </a-form-item>
        <a-form-item label="退役原因" required>
          <a-textarea v-model:value="retireReason" :rows="4" placeholder="请输入退役原因" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { DownOutlined } from '@ant-design/icons-vue'

import { deleteSkill, deploySkill, listSkillsPaged, rescanSkill, retireSkill } from '../api'
import { formatDateTime } from '../utils/format'

const keyword = ref('')
const status = ref('all')
const risk = ref('all')
const sandboxFilter = ref('all')
const loading = ref(false)
const actionKey = ref('')
const rows = ref([])
const total = ref(0)
const selectedRecord = ref(null)
const retireModalOpen = ref(false)
const retireReason = ref('')
const sortState = ref({ field: 'updated_at', order: 'descend' })
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: (value) => `共 ${value} 条`,
})
const statusOptions = [
  { value: 'PENDING,VETTED', label: '待处理（Pending / Vetted）' },
  { value: 'APPROVED,DEPLOYED', label: '可使用（Approved / Deployed）' },
  { value: 'REJECTED', label: '已拒绝（Rejected）' },
]
const riskOptions = [
  { value: 'benign', label: 'benign（安全）' },
  { value: 'suspicious', label: 'suspicious（可疑）' },
  { value: 'malicious', label: 'malicious（恶意）' },
]

const columns = [
  { title: 'Skill 名称', dataIndex: 'name', key: 'name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', width: 110, sorter: true },
  { title: '状态', dataIndex: 'status', key: 'status', width: 180, sorter: true },
  { title: '风险', dataIndex: 'risk_level', key: 'risk', width: 160, sorter: true },
  { title: 'Sandbox', key: 'sandbox', width: 180 },
  { title: '审批人', dataIndex: 'approved_by', key: 'approved_by', width: 160, sorter: true },
  { title: '扫描时间', dataIndex: 'updated_at', key: 'updated_at', width: 190, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: '操作', key: 'actions', width: 120 },
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
    message.error(error.response?.data?.detail || '获取 Skill 列表失败')
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
  sortState.value = { field: 'updated_at', order: 'descend' }
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchSkills()
}

const handleRescan = async (record) => {
  actionKey.value = `rescan:${record.skill_id}`
  try {
    await rescanSkill(record.skill_id)
    message.success('已提交重新检测')
    fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || '重新检测失败')
  } finally {
    actionKey.value = ''
  }
}

const handleDeploy = async (record) => {
  actionKey.value = `deploy:${record.skill_id}`
  try {
    await deploySkill(record.skill_id)
    message.success(`已标记部署：${record.name}`)
    fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || '部署失败')
  } finally {
    actionKey.value = ''
  }
}

const currentUser = () => localStorage.getItem('username') || 'admin'

const openRetireModal = (record) => {
  selectedRecord.value = record
  retireReason.value = ''
  retireModalOpen.value = true
}

const submitRetire = async () => {
  if (!selectedRecord.value) return
  const reason = retireReason.value.trim()
  if (!reason) {
    message.warning('请输入退役原因')
    return
  }
  actionKey.value = `retire:${selectedRecord.value.skill_id}`
  try {
    await retireSkill(selectedRecord.value.skill_id, { actor: currentUser(), reason })
    message.success(`已退役：${selectedRecord.value.name}`)
    retireModalOpen.value = false
    fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || '退役失败')
  } finally {
    actionKey.value = ''
  }
}

const confirmDelete = (record) => {
  Modal.confirm({
    title: `删除 Skill：${record.name}`,
    content: '只删除列表记录，不会删除磁盘上的 Skill 目录。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => handleDelete(record),
  })
}

const handleDelete = async (record) => {
  actionKey.value = `delete:${record.skill_id}`
  try {
    await deleteSkill(record.skill_id)
    message.success('已删除 Skill 记录')
    if (rows.value.length === 1 && pagination.value.current > 1) {
      pagination.value = { ...pagination.value, current: pagination.value.current - 1 }
    }
    fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || '删除 Skill 失败')
  } finally {
    actionKey.value = ''
  }
}

const shortId = (value) => {
  const text = String(value || '')
  return text.length > 12 ? `${text.slice(0, 8)}...` : text || '-'
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

const statusTitle = (value) =>
  ({
    PENDING: '分析中',
    VETTED: '待审核',
    APPROVED: '已批准',
    DEPLOYED: '已部署',
    REJECTED: '已拒绝',
    RETIRED: '已退役',
  }[value] || '未知')
const statusDisplay = (value) => (value ? `${value}（${statusTitle(value)}）` : '-')
const riskDisplay = (value) => {
  const text = String(value || 'unknown')
  const zh = {
    benign: '安全',
    suspicious: '可疑',
    malicious: '恶意',
    unknown: '未知',
  }[text.toLowerCase()] || '未知'
  return `${text}（${zh}）`
}

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
.short-id,
.actions-cell {
  white-space: nowrap;
}
</style>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
