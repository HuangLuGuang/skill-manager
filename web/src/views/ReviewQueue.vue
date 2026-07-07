<template>
  <div>
    <a-page-header title="审核队列" sub-title="处理待审核技能" />

    <a-card style="margin-top: 16px">
      <a-space style="margin-bottom: 16px" wrap>
        <a-input
          v-model:value="keyword"
          placeholder="搜索技能 名称 / ID / 备注"
          style="width: 280px"
          allow-clear
          @pressEnter="handleFilterChange"
          @change="handleKeywordInputChange"
        />
        <a-select v-model:value="risk" style="width: 160px" @change="handleFilterChange">
          <a-select-option value="all">全部风险</a-select-option>
          <a-select-option value="benign">benign</a-select-option>
          <a-select-option value="suspicious">suspicious</a-select-option>
          <a-select-option value="malicious">malicious</a-select-option>
        </a-select>
        <a-select v-model:value="reviewStatus" style="width: 140px" @change="handleFilterChange">
          <a-select-option value="pending">待审核</a-select-option>
          <a-select-option value="reviewed">已审核</a-select-option>
          <a-select-option value="all">全部状态</a-select-option>
        </a-select>
        <a-button type="primary" @click="handleFilterChange" :loading="loading">查询</a-button>
        <a-button @click="resetFilters" :disabled="loading">重置</a-button>
        <a-button @click="fetchQueue" :loading="loading">刷新</a-button>
      </a-space>

      <div class="table-meta">当前共有 {{ total }} 条{{ reviewStatusLabel }}技能</div>

      <a-table
        :data-source="rows"
        :columns="dynamicColumns"
        rowKey="skill_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: `当前没有${reviewStatusLabel}技能` }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'skill_name'">
            <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.skill_name }}</a>
          </template>
          <template v-else-if="column.key === 'risk'">
            <a-tag v-if="record.risk_level === 'malicious'" color="red" title="恶意">malicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange" title="可疑">suspicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green" title="安全">benign</a-tag>
            <a-tag v-else color="default">-</a-tag>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button size="small" @click="$router.push(`/skills/${record.skill_id}?tab=governance-card`)">治理卡片</a-button>
              <template v-if="record.status === 'VETTED'">
                <a-button size="small" type="primary" @click="openApproveModal(record)">批准</a-button>
                <a-button size="small" danger @click="openRejectModal(record)">拒绝</a-button>
              </template>
            </a-space>
          </template>
          <template v-else-if="column.key === 'reviewStatus'">
            <a-tag v-if="record.status === 'APPROVED'" color="green">已批准</a-tag>
            <a-tag v-else-if="record.status === 'REJECTED'" color="red">已拒绝</a-tag>
            <a-tag v-else-if="record.status === 'VETTED'" color="blue">待审核</a-tag>
            <a-tag v-else>{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'reviewer'">
            <span v-if="record.status === 'APPROVED'">{{ record.approved_by || '-' }}</span>
            <span v-else-if="record.status === 'REJECTED'">{{ record.rejection_reason || '-' }}</span>
            <span v-else>-</span>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="approveModalOpen"
      title="批准技能"
      ok-text="确认批准"
      cancel-text="取消"
      :confirm-loading="actionLoading"
      @ok="submitApprove"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="selectedRecord?.skill_name || ''" disabled />
        </a-form-item>
        <a-form-item label="审批人">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item label="审批备注">
          <a-textarea v-model:value="approveNote" :rows="4" placeholder="可留空" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="rejectModalOpen"
      title="拒绝技能"
      ok-text="确认拒绝"
      cancel-text="取消"
      :confirm-loading="actionLoading"
      @ok="submitReject"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="selectedRecord?.skill_name || ''" disabled />
        </a-form-item>
        <a-form-item label="审核人">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item label="拒绝原因" required>
          <a-textarea v-model:value="rejectReason" :rows="4" placeholder="请输入原因" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import { approveSkill, listReviewQueuePaged, rejectSkill } from '../api'
import { formatDateTime } from '../utils/format'

const loading = ref(false)
const actionLoading = ref(false)
const rows = ref([])
const total = ref(0)
const keyword = ref('')
const risk = ref('all')
const reviewStatus = ref('pending')
const sortState = ref({ field: 'sort_at', order: 'descend' })
const selectedRecord = ref(null)
const approveModalOpen = ref(false)
const rejectModalOpen = ref(false)
const approveNote = ref('')
const rejectReason = ref('')
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: (value) => `共 ${value} 条`,
})
let keywordTimer = null

const reviewStatusLabel = computed(() => {
  const map = { pending: '待审核', reviewed: '已审核', all: '' }
  return map[reviewStatus.value] || ''
})

const baseColumns = [
  { title: '技能名称', dataIndex: 'skill_name', key: 'skill_name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', sorter: true },
  { title: '风险', dataIndex: 'risk_level', key: 'risk', width: 120, sorter: true },
  { title: 'Findings', dataIndex: 'findings', key: 'findings', width: 140 },
  { title: '时间', dataIndex: 'display_time', key: 'time', width: 190, sorter: true, customRender: ({ text }) => formatDateTime(text) },
]

const reviewedColumns = [
  { title: '审核状态', key: 'reviewStatus', width: 100 },
  { title: '审核信息', key: 'reviewer', width: 160, ellipsis: true },
]

const dynamicColumns = computed(() => {
  const cols = [...baseColumns]
  if (reviewStatus.value === 'reviewed' || reviewStatus.value === 'all') {
    cols.push(...reviewedColumns)
  }
  cols.push({ title: '操作', key: 'actions', width: reviewStatus.value === 'pending' ? 280 : 160 })
  return cols
})

const fetchQueue = async () => {
  loading.value = true
  try {
    const res = await listReviewQueuePaged({
      q: keyword.value.trim() || undefined,
      risk_level: risk.value === 'all' ? undefined : risk.value,
      review_status: reviewStatus.value,
      sort_by: sortState.value.field,
      sort_order: sortState.value.order === 'descend' ? 'desc' : 'asc',
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
    })
    rows.value = (Array.isArray(res.items) ? res.items : []).map((item) => ({
      ...item,
      display_time: item.sort_at || item.reviewed_at || item.queued_at,
      findings: `${item.findings_summary?.critical || 0}/${item.findings_summary?.high || 0}/${item.findings_summary?.medium || 0}/${item.findings_summary?.low || 0}`,
    }))
    total.value = Number(res.total || 0)
    pagination.value = {
      ...pagination.value,
      total: total.value,
      current: Number(res.page || pagination.value.current),
      pageSize: Number(res.page_size || pagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || '获取审核队列失败')
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const currentUser = () => localStorage.getItem('username') || 'admin'

const openApproveModal = (record) => {
  selectedRecord.value = record
  approveNote.value = ''
  approveModalOpen.value = true
}

const openRejectModal = (record) => {
  selectedRecord.value = record
  rejectReason.value = ''
  rejectModalOpen.value = true
}

const submitApprove = async () => {
  if (!selectedRecord.value) return
  actionLoading.value = true
  try {
    await approveSkill(selectedRecord.value.skill_id, {
      approver: currentUser(),
      note: approveNote.value.trim() || null,
    })
    message.success('已批准')
    approveModalOpen.value = false
    fetchQueue()
  } catch (error) {
    message.error(error.response?.data?.detail || '批准失败')
  } finally {
    actionLoading.value = false
  }
}

const submitReject = async () => {
  if (!selectedRecord.value) return
  if (!rejectReason.value.trim()) {
    message.warning('请输入拒绝原因')
    return
  }
  actionLoading.value = true
  try {
    await rejectSkill(selectedRecord.value.skill_id, {
      reviewer: currentUser(),
      reason: rejectReason.value.trim(),
    })
    message.success('已拒绝')
    rejectModalOpen.value = false
    fetchQueue()
  } catch (error) {
    message.error(error.response?.data?.detail || '拒绝失败')
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
      field: sorter.field === 'display_time' ? 'sort_at' : sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchQueue()
}

const handleFilterChange = () => {
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchQueue()
}

const handleKeywordInputChange = () => {
  if (keywordTimer) window.clearTimeout(keywordTimer)
  keywordTimer = window.setTimeout(() => {
    handleFilterChange()
  }, 300)
}

const resetFilters = () => {
  keyword.value = ''
  risk.value = 'all'
  reviewStatus.value = 'pending'
  sortState.value = { field: 'sort_at', order: 'descend' }
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchQueue()
}

onMounted(fetchQueue)

onBeforeUnmount(() => {
  if (keywordTimer) window.clearTimeout(keywordTimer)
})
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
