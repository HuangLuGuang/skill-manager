<template>
  <div>
    <a-page-header :title="$t('legacy.1k48rmt')" :sub-title="$t('legacy.trx6mc')" />

    <a-card style="margin-top: 16px">
      <a-space wrap style="margin-bottom: 16px">
        <a-input
          v-model:value="keyword"
          :placeholder="$t('legacy.kh4kre')"
          style="width: 280px"
          allow-clear
          @pressEnter="handleKeywordSearch"
          @change="handleKeywordInputChange"
        />
        <a-select v-model:value="status" style="width: 260px">
          <a-select-option value="all">{{ $t("legacy.igzce8") }}</a-select-option>
          <a-select-option v-for="item in statusOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </a-select-option>
        </a-select>
        <a-select v-model:value="risk" style="width: 160px">
          <a-select-option value="all">{{ $t("legacy.hah0r4") }}</a-select-option>
          <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </a-select-option>
        </a-select>
        <a-select v-model:value="sandboxFilter" style="width: 180px">
          <a-select-option value="all">{{ $t("legacy.1u4z956") }}</a-select-option>
          <a-select-option value="triggered">{{ $t("legacy.1da4nqr") }}</a-select-option>
          <a-select-option value="policy">{{ $t("legacy.s4jlvl") }}</a-select-option>
        </a-select>
        <a-button type="primary" @click="handleKeywordSearch" :loading="loading">{{ text('查询', 'Search') }}</a-button>
        <a-button @click="resetFilters" :disabled="loading">{{ text('重置', 'Reset') }}</a-button>
        <a-button @click="fetchSkills" :loading="loading">{{ text('刷新', 'Refresh') }}</a-button>
        <a-button type="primary" @click="$router.push('/submit')">{{ text('提交 Skill', 'Submit Skill') }}</a-button>
      </a-space>

      <div class="table-meta">
        {{ listMetaText }}
      </div>

      <a-table
        :data-source="rows"
        :columns="columns"
        rowKey="skill_id"
        :loading="loading"
        :pagination="pagination"
        :locale="{ emptyText: $t('legacy.1exbp9c') }"
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
            <a-tag :color="statusColor(record.status)">{{ statusDisplay(record.status, record) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'version'">
            <a-space wrap>
              <a-tag color="blue">v{{ record.version_no || 1 }}</a-tag>
              <a-tag v-if="record.source_version">{{ record.source_version }}</a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'trustedVersion'">
            <a-tag v-if="record.latest_trusted_version_no" color="green">
              v{{ record.latest_trusted_version_no }}
            </a-tag>
            <span v-else style="color: #8c8c8c">-</span>
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
              <a-tag v-if="record.sandbox_required_by_policy" color="orange">{{ $t("legacy.pf5db8") }}</a-tag>
              <span v-if="!record.sandbox_triggered" style="color: #8c8c8c">-</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space class="actions-cell">
              <a @click="$router.push(`/skills/${record.skill_id}`)">{{ text('详情', 'Details') }}</a>
              <a-divider type="vertical" />
              <a-dropdown>
                <a class="ant-dropdown-link" @click.prevent>
                  {{ text('更多', 'More') }} <DownOutlined />
                </a>
                <template #overlay>
                  <a-menu>
                    <a-menu-item
                      :disabled="record.status === 'PENDING' || Boolean(actionKey)"
                      @click="handleRescan(record)"
                    >
                      {{ actionKey === `rescan:${record.skill_id}` ? text('重新检测中...', 'Rescanning...') : text('重新检测', 'Rescan') }}
                    </a-menu-item>
                    <a-menu-item
                      v-if="record.status === 'PENDING'"
                      :disabled="Boolean(actionKey)"
                      @click="confirmCancel(record)"
                    >
                      {{ actionKey === `cancel:${record.skill_id}` ? text('取消中...', 'Cancelling...') : text('取消任务', 'Cancel Task') }}
                    </a-menu-item>
                    <a-menu-divider />
                    <a-menu-item
                      danger
                      :disabled="Boolean(actionKey)"
                      @click="confirmDelete(record)"
                    >
                      {{ actionKey === `delete:${record.skill_id}` ? text('删除中...', 'Deleting...') : text('删除', 'Delete') }}
                    </a-menu-item>
                  </a-menu>
                </template>
              </a-dropdown>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { DownOutlined } from '@ant-design/icons-vue'

import { deleteSkill, listSkillsPaged, rejectSkill, rescanSkill } from '../api'
import { useLocaleText } from '../i18n/useLocaleText'
import { formatDateTime } from '../utils/format'

const { isEnglish, text } = useLocaleText()
const keyword = ref('')
const status = ref('all')
const risk = ref('all')
const sandboxFilter = ref('all')
const loading = ref(false)
const actionKey = ref('')
const rows = ref([])
const total = ref(0)
const sortState = ref({ field: 'updated_at', order: 'descend' })
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: (value) => text(`共 ${value} 条`, `${value} total`),
})
const listMetaText = computed(() => text(
  `共 ${total.value} 条，当前显示第 ${pagination.value.current} 页`,
  `${total.value} total, page ${pagination.value.current}`,
))
const statusOptions = computed(() => [
  { value: 'PENDING,VETTED', label: text('待处理（Pending / Vetted）', 'Pending / Vetted') },
  { value: 'APPROVED', label: text('可使用（Approved）', 'Approved') },
  { value: 'cancelled', label: text('Cancelled（已取消）', 'Cancelled') },
  { value: 'REJECTED', label: text('已拒绝（Rejected）', 'Rejected') },
])
const riskOptions = computed(() => [
  { value: 'benign', label: text('benign（安全）', 'benign') },
  { value: 'suspicious', label: text('suspicious（可疑）', 'suspicious') },
  { value: 'malicious', label: text('malicious（恶意）', 'malicious') },
])

const columns = computed(() => [
  { title: text('Skill 名称', 'Skill Name'), dataIndex: 'name', key: 'name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', width: 110, sorter: true },
  { title: text('最新版本', 'Latest Version'), key: 'version', width: 140 },
  { title: text('最新可信', 'Latest Trusted'), key: 'trustedVersion', width: 130 },
  { title: text('状态', 'Status'), dataIndex: 'status', key: 'status', width: 180, sorter: true },
  { title: text('风险', 'Risk'), dataIndex: 'risk_level', key: 'risk', width: 160, sorter: true },
  { title: 'Sandbox', key: 'sandbox', width: 180 },
  { title: text('审批人', 'Approver'), dataIndex: 'approved_by', key: 'approved_by', width: 160, sorter: true },
  { title: text('扫描时间', 'Scan Time'), dataIndex: 'updated_at', key: 'updated_at', width: 190, sorter: true, customRender: ({ text: value }) => formatDateTime(value) },
  { title: text('操作', 'Actions'), key: 'actions', width: 120 },
])

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
    message.error(error.response?.data?.detail || phrase('legacy.rdg3cq'))
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
    message.success(phrase('legacy.1mc7sgd'))
    fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.17vebon'))
  } finally {
    actionKey.value = ''
  }
}

const currentUser = () => localStorage.getItem('username') || 'admin'
const cancelledReason = phrase('legacy.1fphrle')
const isCancelled = (record) => record?.status === 'REJECTED' && record?.rejection_reason === cancelledReason

const confirmCancel = (record) => {
  Modal.confirm({
    title: text(`取消分析任务：${record.name}`, `Cancel analysis: ${record.name}`),
    content: phrase('legacy.1qvsm47'),
    okText: phrase('legacy.1ujkph7'),
    cancelText: phrase('legacy.omytgn'),
    onOk: () => handleCancel(record),
  })
}

const handleCancel = async (record) => {
  actionKey.value = `cancel:${record.skill_id}`
  try {
    await rejectSkill(record.skill_id, {
      reviewer: currentUser(),
      reason: cancelledReason,
    })
    message.success(phrase('legacy.lkn23t'))
    fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.nisji9'))
  } finally {
    actionKey.value = ''
  }
}

const confirmDelete = (record) => {
  Modal.confirm({
    title: text(`删除 Skill：${record.name}`, `Delete Skill: ${record.name}`),
    content: phrase('legacy.1x1o9bb'),
    okText: phrase('legacy.1t2vi4h'),
    okType: 'danger',
    cancelText: phrase('legacy.1589w37'),
    onOk: () => handleDelete(record),
  })
}

const handleDelete = async (record) => {
  actionKey.value = `delete:${record.skill_id}`
  try {
    await deleteSkill(record.skill_id)
    message.success(phrase('legacy.1xaqb1r'))
    if (rows.value.length === 1 && pagination.value.current > 1) {
      pagination.value = { ...pagination.value, current: pagination.value.current - 1 }
    }
    fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.192fss2'))
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
    PENDING: phrase('legacy.viveky'),
    VETTED: phrase('legacy.a2uv9t'),
    APPROVED: phrase('legacy.10hmnl2'),
    DEPLOYED: phrase('legacy.1t00jqn'),
    REJECTED: phrase('legacy.16h1qdk'),
    RETIRED: phrase('legacy.1vdmo1u'),
  }[value] || phrase('legacy.1lpnuh4'))
const statusDisplay = (value, record) => {
  if (isCancelled(record)) return text('Cancelled（已取消）', 'CANCELLED')
  if (isEnglish.value) return value || '-'
  return value ? `${value}（${statusTitle(value)}）` : '-'
}
const riskDisplay = (value) => {
  const text = String(value || 'unknown')
  if (isEnglish.value) return text
  const zh = {
    benign: phrase('legacy.1apxo2s'),
    suspicious: phrase('legacy.1x3ukv1'),
    malicious: phrase('legacy.m36raq'),
    unknown: phrase('legacy.1lpnuh4'),
  }[text.toLowerCase()] || phrase('legacy.1lpnuh4')
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
