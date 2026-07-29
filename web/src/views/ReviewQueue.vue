<template>
  <div>
    <a-page-header :title="$t('legacy.jxqkne')" :sub-title="$t('legacy.jrd9kw')" />

    <a-card style="margin-top: 16px">
      <a-space style="margin-bottom: 16px" wrap>
        <a-input
          v-model:value="keyword"
          :placeholder="$t('legacy.5eje4j')"
          style="width: 280px"
          allow-clear
          @pressEnter="handleFilterChange"
          @change="handleKeywordInputChange"
        />
        <a-select v-model:value="risk" style="width: 160px" @change="handleFilterChange">
          <a-select-option value="all">{{ $t("legacy.hah0r4") }}</a-select-option>
          <a-select-option value="benign">benign</a-select-option>
          <a-select-option value="suspicious">suspicious</a-select-option>
          <a-select-option value="malicious">malicious</a-select-option>
        </a-select>
        <a-select v-model:value="reviewStatus" style="width: 140px" @change="handleFilterChange">
          <a-select-option value="pending">{{ $t("legacy.a2uv9t") }}</a-select-option>
          <a-select-option value="reviewed">{{ $t("legacy.7j2xv0") }}</a-select-option>
          <a-select-option value="all">{{ $t("legacy.igzce8") }}</a-select-option>
        </a-select>
        <a-button type="primary" @click="handleFilterChange" :loading="loading">{{ text('查询', 'Search') }}</a-button>
        <a-button @click="resetFilters" :disabled="loading">{{ text('重置', 'Reset') }}</a-button>
        <a-button @click="fetchQueue" :loading="loading">{{ text('刷新', 'Refresh') }}</a-button>
      </a-space>

      <div class="table-meta">{{ reviewMetaText }}</div>

      <a-table
        :data-source="rows"
        :columns="dynamicColumns"
        rowKey="skill_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: text(
          `当前没有${reviewStatusLabel} Skill`,
          `No ${reviewStatusLabel || 'matching'} Skills`,
        ) }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'skill_name'">
            <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.skill_name }}</a>
          </template>
          <template v-else-if="column.key === 'risk'">
            <a-tag v-if="record.risk_level === 'malicious'" color="red" :title="$t('legacy.m36raq')">malicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange" :title="$t('legacy.1x3ukv1')">suspicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green" :title="$t('legacy.1apxo2s')">benign</a-tag>
            <a-tag v-else color="default">-</a-tag>
          </template>
          <template v-else-if="column.key === 'findings'">
            <a-space size="small" wrap>
              <a-tag
                v-for="item in findingBadges(record.findings_summary)"
                :key="item.key"
                :color="item.color"
              >
                {{ item.label }} {{ item.count }}
              </a-tag>
              <span v-if="!findingBadges(record.findings_summary).length" class="muted-text">{{ text('无', 'None') }}</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button size="small" @click="$router.push(`/skills/${record.skill_id}?tab=governance-card`)">{{ text('治理卡片', 'Governance Card') }}</a-button>
              <template v-if="record.status === 'VETTED'">
                <a-button size="small" type="primary" @click="openApproveModal(record)">{{ text('批准', 'Approve') }}</a-button>
                <a-button size="small" danger @click="openRejectModal(record)">{{ text('拒绝', 'Reject') }}</a-button>
              </template>
            </a-space>
          </template>
          <template v-else-if="column.key === 'reviewStatus'">
            <a-tag v-if="record.status === 'APPROVED'" color="green">{{ text('已批准', 'Approved') }}</a-tag>
            <a-tag v-else-if="record.status === 'REJECTED'" color="red">{{ text('已拒绝', 'Rejected') }}</a-tag>
            <a-tag v-else-if="record.status === 'VETTED'" color="blue">{{ text('待审核', 'Pending Review') }}</a-tag>
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
      :title="$t('legacy.1xa4yul')"
      :ok-text="$t('legacy.1srvmx8')"
      :cancel-text="$t('legacy.1589w37')"
      :confirm-loading="actionLoading"
      @ok="submitApprove"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="selectedRecord?.skill_name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1lakt7z')">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1v900uo')">
          <a-textarea v-model:value="approveNote" :rows="4" :placeholder="$t('legacy.y7iiel')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="rejectModalOpen"
      :title="$t('legacy.sgs3in')"
      :ok-text="$t('legacy.iwk43y')"
      :cancel-text="$t('legacy.1589w37')"
      :confirm-loading="actionLoading"
      @ok="submitReject"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="selectedRecord?.skill_name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1gs5bzm')">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1l7e57j')" required>
          <a-textarea v-model:value="rejectReason" :rows="4" :placeholder="$t('legacy.1gqmn09')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import { approveSkill, listReviewQueuePaged, rejectSkill } from '../api'
import { useLocaleText } from '../i18n/useLocaleText'
import { formatDateTime } from '../utils/format'

const { text } = useLocaleText()
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
  showTotal: (value) => text(`共 ${value} 条`, `${value} total`),
})
let keywordTimer = null

const reviewStatusLabel = computed(() => {
  const map = {
    pending: text('待审核', 'pending review'),
    reviewed: text('已审核', 'reviewed'),
    all: '',
  }
  return map[reviewStatus.value] || ''
})
const reviewMetaText = computed(() => (
  text(
    `当前共有 ${total.value} 条${reviewStatusLabel.value}技能`,
    `${total.value} ${reviewStatusLabel.value || 'matching'} Skills`,
  )
))

const baseColumns = computed(() => [
  { title: text('技能名称', 'Skill Name'), dataIndex: 'skill_name', key: 'skill_name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', sorter: true },
  { title: text('风险', 'Risk'), dataIndex: 'risk_level', key: 'risk', width: 120, sorter: true },
  { title: text('发现项', 'Findings'), dataIndex: 'findings_summary', key: 'findings', width: 190 },
  { title: text('时间', 'Time'), dataIndex: 'display_time', key: 'time', width: 190, sorter: true, customRender: ({ text: value }) => formatDateTime(value) },
])

const findingBadges = (summary = {}) => [
  { key: 'critical', label: text('严重', 'Critical'), color: 'red', count: Number(summary.critical || 0) },
  { key: 'high', label: text('高', 'High'), color: 'volcano', count: Number(summary.high || 0) },
  { key: 'medium', label: text('中', 'Medium'), color: 'orange', count: Number(summary.medium || 0) },
  { key: 'low', label: text('低', 'Low'), color: 'blue', count: Number(summary.low || 0) },
].filter((item) => item.count > 0)

const reviewedColumns = computed(() => [
  { title: text('审核状态', 'Review Status'), key: 'reviewStatus', width: 100 },
  { title: text('审核信息', 'Review Details'), key: 'reviewer', width: 160, ellipsis: true },
])

const dynamicColumns = computed(() => {
  const cols = [...baseColumns.value]
  if (reviewStatus.value === 'reviewed' || reviewStatus.value === 'all') {
    cols.push(...reviewedColumns.value)
  }
  cols.push({ title: text('操作', 'Actions'), key: 'actions', width: reviewStatus.value === 'pending' ? 280 : 160 })
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
    }))
    total.value = Number(res.total || 0)
    pagination.value = {
      ...pagination.value,
      total: total.value,
      current: Number(res.page || pagination.value.current),
      pageSize: Number(res.page_size || pagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1z0342t'))
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
    message.success(phrase('legacy.10hmnl2'))
    approveModalOpen.value = false
    fetchQueue()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.xx2z1c'))
  } finally {
    actionLoading.value = false
  }
}

const submitReject = async () => {
  if (!selectedRecord.value) return
  if (!rejectReason.value.trim()) {
    message.warning(phrase('legacy.erwuhg'))
    return
  }
  actionLoading.value = true
  try {
    await rejectSkill(selectedRecord.value.skill_id, {
      reviewer: currentUser(),
      reason: rejectReason.value.trim(),
    })
    message.success(phrase('legacy.16h1qdk'))
    rejectModalOpen.value = false
    fetchQueue()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.36obuy'))
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

.muted-text {
  color: #9ca3af;
}
</style>
