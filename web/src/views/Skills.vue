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
          <a-select-option value="all">{{ $t('skillFilters.all') }}</a-select-option>
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
        <a-button v-if="hasAccess('skills:create')" type="primary" @click="$router.push('/submit')">{{ text('提交 Skill', 'Submit Skill') }}</a-button>
        <a-popover trigger="click" placement="bottomRight" :title="$t('skillColumns.hint')">
          <template #content>
            <a-checkbox-group v-model:value="visibleColumns" class="column-options">
              <a-checkbox v-for="column in allColumns" :key="column.key" :value="column.key">{{ column.title }}</a-checkbox>
            </a-checkbox-group>
            <a-button type="link" class="reset-columns" @click="visibleColumns = [...defaultSkillColumns]">{{ $t('skillColumns.reset') }}</a-button>
          </template>
          <a-button><SettingOutlined /> {{ $t('skillColumns.settings') }}</a-button>
        </a-popover>
      </a-space>

      <div class="batch-actions">
        <span>{{ $t('skillBatch.selected', { count: selectedRowKeys.length }) }}</span>
        <a-button v-if="hasAccess('skills:scan')" :loading="actionKey === 'batch:rescan'" :disabled="Boolean(actionKey) || !batchCount('rescan')" @click="openBatchRescan">{{ $t('skillBatch.rescan') }}</a-button>
        <a-button v-if="hasAccess('skills:update')" :loading="actionKey === 'batch:cancel'" :disabled="Boolean(actionKey) || !batchCount('cancel')" @click="confirmBatch('cancel')">{{ $t('skillBatch.cancel') }}</a-button>
        <a-button v-if="hasAccess('skills:delete')" danger :loading="actionKey === 'batch:delete'" :disabled="Boolean(actionKey) || !selectedRowKeys.length" @click="confirmBatch('delete')">{{ $t('skillBatch.delete') }}</a-button>
        <a-button :disabled="Boolean(actionKey) || !selectedRowKeys.length" @click="selectedRowKeys = []">{{ $t('skillBatch.clear') }}</a-button>
      </div>
      <a-alert v-if="batchResult" :type="batchResult.failed.length || batchResult.skipped.length ? 'warning' : 'success'" :message="$t(`skillBatch.${batchResult.action}Result`, { success: batchResult.succeeded.length, failed: batchResult.failed.length, skipped: batchResult.skipped.length })" class="batch-result" show-icon closable @close="batchResult = null">
        <template #description>
          <div v-if="batchResult.succeeded.length">{{ $t(`skillBatch.${batchResult.action}Items`, { names: batchResult.succeeded.map(record => record.name).join(', ') }) }}</div>
          <div v-for="group in batchSkipGroups" :key="group.key">{{ $t('skillBatch.skippedGroup', { count: group.names.length, status: group.status, reason: $t(`skillBatch.${group.reason}`), names: group.names.join(', ') }) }}</div>
          <div v-for="item in batchResult.failed" :key="item.record.skill_id">{{ $t('skillBatch.failedItem', { name: item.record.name, reason: item.error?.response?.data?.detail || $t('skillBatch.requestFailed') }) }}</div>
        </template>
      </a-alert>

      <a-table
        :row-selection="rowSelection"
        :data-source="rows"
        :columns="columns"
        :scroll="{ x: 'max-content' }"
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
            <SkillScanProgress v-if="record.scan_pending || record.status === 'PENDING'" :stage="record.scan_progress_stage" :analyzers="record.scan_progress_analyzers || {}" />
            <a-tag v-else :color="statusColor(record.status)">{{ statusDisplay(record.status, record) }}</a-tag>
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
            <a-tag v-if="record.scan_pending || record.status === 'PENDING'" color="default">-</a-tag>
            <a-tag v-else-if="record.risk_level === 'malicious'" color="red">{{ riskDisplay(record.risk_level) }}</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange">{{ riskDisplay(record.risk_level) }}</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green">{{ riskDisplay(record.risk_level) }}</a-tag>
            <a-tag v-else color="default">-</a-tag>
          </template>
          <template v-else-if="['llm', ...optionalAnalysisColumns].includes(column.key)">
            <a-tag :color="analysisTag(record, column.key).color">{{ analysisTag(record, column.key).label }}</a-tag>
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
                    <a-menu-item v-if="hasAccess('skills:scan')"
                      :disabled="record.scan_pending || record.status === 'PENDING' || Boolean(actionKey)"
                      @click="handleRescan(record)"
                    >
                      {{ actionKey === `rescan:${record.skill_id}` ? text('重新检测中...', 'Rescanning...') : text('重新检测', 'Rescan') }}
                    </a-menu-item>
                    <a-menu-item
                      v-if="hasAccess('skills:update') && (canRunSkillAction('cancel', record))"
                      :disabled="Boolean(actionKey)"
                      @click="confirmCancel(record)"
                    >
                      {{ actionKey === `cancel:${record.skill_id}` ? text('取消中...', 'Cancelling...') : text('取消任务', 'Cancel Task') }}
                    </a-menu-item>
                    <a-menu-divider />
                    <a-menu-item v-if="hasAccess('skills:delete')"
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
    <SkillRescanModal v-model:open="rescanModalOpen" :count="rescanRecords.length" :skill-name="singleRescanRecord?.name" :submitting="actionKey === 'batch:rescan' || actionKey.startsWith('rescan:')" @submit="submitRescan" />

  </div>
</template>

<script setup>
import { can as hasAccess } from '../access'
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { DownOutlined, SettingOutlined } from '@ant-design/icons-vue'
import { useI18n } from 'vue-i18n'

import { cancelSkillScan, deleteSkill, listSkillsPaged, rescanSkill } from '../api'
import { useLocaleText } from '../i18n/useLocaleText'
import { formatDateTime } from '../utils/format'
import { lifecycleVersionId } from '../utils/skillVersions'
import { canRunSkillAction, runSkillBatch } from '../utils/skillBatch'
import SkillRescanModal from '../components/SkillRescanModal.vue'
import SkillScanProgress from '../components/SkillScanProgress.vue'
import { analysisCell, optionalAnalysisColumns, defaultSkillColumns, readVisibleColumns } from '../utils/skillColumns'

const { isEnglish, text } = useLocaleText()
const { t, te } = useI18n()
const columnUser = localStorage.getItem('username') || 'default'
const columnStorageKey = `skill-visible-columns:${columnUser}`
const visibleColumns = ref(readVisibleColumns(localStorage, columnStorageKey, `skill-analysis-columns:${columnUser}`))
watch(visibleColumns, value => {
  try { localStorage.setItem(columnStorageKey, JSON.stringify(value)) } catch { /* Browser storage may be unavailable. */ }
})
const analysisTag = (record, key) => {
  const cell = analysisCell(record, key)
  if (cell.state) return { label: t(`decisionFlow.${cell.state}`), color: cell.state === 'failed' ? 'red' : cell.state === 'pending' ? 'gold' : 'default' }
  if (cell.count !== undefined) return { label: t('skillColumns.findings', { count: cell.count }), color: 'default' }
  const level = String(cell.risk)
  const translation = level === level.toUpperCase() ? `skillColumns.${level}` : `decisionFlow.${level}`
  return { label: te(translation) ? t(translation) : level, color: ({ benign: 'green', SAFE: 'green', LOW: 'green', INFO: 'default', suspicious: 'orange', MEDIUM: 'orange', malicious: 'red', HIGH: 'red', CRITICAL: 'red', EXTREME: 'red' })[level] || 'default' }
}
const keyword = ref('')
const status = ref('all')
const risk = ref('all')
const sandboxFilter = ref('all')
const loading = ref(false)
const actionKey = ref('')
const rows = ref([])
const selectedRowKeys = ref([])
const batchResult = ref(null)
const rescanModalOpen = ref(false)
const rescanRecords = ref([])
const singleRescanRecord = ref(null)
const selectedRows = computed(() => rows.value.filter(row => selectedRowKeys.value.includes(row.skill_id)))
const batchCount = action => selectedRows.value.filter(row => canRunSkillAction(action, row)).length
const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: keys => { selectedRowKeys.value = keys },
  getCheckboxProps: () => ({ disabled: Boolean(actionKey.value) }),
}))
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
const statusOptions = computed(() => [
  { value: 'scanning', label: t('skillFilters.scanning') },
  { value: 'VETTED', label: t('skillFilters.awaitingReview') },
  { value: 'APPROVED', label: t('skillFilters.approved') },
  { value: 'cancelled', label: t('skillFilters.cancelled') },
  { value: 'REJECTED', label: t('skillFilters.rejected') },
])
const riskOptions = computed(() => [
  { value: 'benign', label: text('benign（安全）', 'benign') },
  { value: 'suspicious', label: text('suspicious（可疑）', 'suspicious') },
  { value: 'malicious', label: text('malicious（恶意）', 'malicious') },
])

const allColumns = computed(() => [
  { title: text('Skill 名称', 'Skill Name'), dataIndex: 'name', key: 'name', sorter: true },
  { title: 'Skill ID', dataIndex: 'skill_id', key: 'skill_id', width: 110, sorter: true },
  { title: text('最新版本', 'Latest Version'), key: 'version', width: 110 },
  { title: text('最新可信', 'Latest Trusted'), key: 'trustedVersion', width: 110 },
  { title: text('状态', 'Status'), dataIndex: 'status', key: 'status', width: 220, sorter: true },
  { title: text('风险', 'Risk'), dataIndex: 'risk_level', key: 'risk', width: 160, sorter: true },
  { title: t('skillColumns.llm'), key: 'llm', width: 180 },
  ...optionalAnalysisColumns.map(key => ({ title: t(`skillColumns.${key}`), key, width: 160 })),
  { title: text('审批人', 'Approver'), dataIndex: 'approved_by', key: 'approved_by', width: 160, sorter: true },
  { title: text('扫描时间', 'Scan Time'), dataIndex: 'updated_at', key: 'updated_at', width: 190, sorter: true, customRender: ({ text: value }) => formatDateTime(value) },
  { title: text('操作', 'Actions'), key: 'actions', width: 120, fixed: 'right' },
])
const columns = computed(() => allColumns.value.filter(column => visibleColumns.value.includes(column.key)))

let refreshTimer
let fetchSequence = 0
let disposed = false
const fetchSkills = async ({ background = false } = {}) => {
  clearTimeout(refreshTimer)
  const sequence = ++fetchSequence
  if (!background) loading.value = true
  try {
    const res = await listSkillsPaged({
      status: ['all', 'scanning'].includes(status.value) ? undefined : status.value,
      scanning: status.value === 'scanning' ? true : status.value === 'VETTED' ? false : undefined,
      risk_level: risk.value === 'all' ? undefined : risk.value,
      sandbox_triggered: sandboxFilter.value === 'triggered' ? true : undefined,
      sandbox_required_by_policy: sandboxFilter.value === 'policy' ? true : undefined,
      q: keyword.value.trim() || undefined,
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
      sort_by: sortState.value.field,
      sort_order: sortState.value.order === 'ascend' ? 'asc' : 'desc',
    })
    if (disposed || sequence !== fetchSequence) return
    rows.value = Array.isArray(res.items) ? res.items : []
    selectedRowKeys.value = selectedRowKeys.value.filter(key => rows.value.some(row => row.skill_id === key))
    total.value = Number(res.total || 0)
    pagination.value = {
      ...pagination.value,
      total: total.value,
      current: Number(res.page || pagination.value.current),
      pageSize: Number(res.page_size || pagination.value.pageSize),
    }
  } catch (error) {
    if (disposed || sequence !== fetchSequence) return
    if (!background) {
      message.error(error.response?.data?.detail || phrase('legacy.rdg3cq'))
      rows.value = []
      total.value = 0
    }
  } finally {
    if (!disposed && sequence === fetchSequence) {
      loading.value = false
      if (rows.value.some(row => row.scan_pending || row.status === 'PENDING')) {
        refreshTimer = setTimeout(() => fetchSkills({ background: true }), 3000)
      }
    }
  }
}

const handleKeywordSearch = () => {
  selectedRowKeys.value = []
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
  selectedRowKeys.value = []
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

const handleRescan = (record) => {
  if (actionKey.value || record.scan_pending || record.status === 'PENDING') return
  singleRescanRecord.value = record
  rescanRecords.value = [record]
  rescanModalOpen.value = true
}

const submitSingleRescan = async (record, options) => {
  if (actionKey.value) return
  actionKey.value = `rescan:${record.skill_id}`
  try {
    await rescanSkill(lifecycleVersionId(record), options)
    message.success(phrase('legacy.1mc7sgd'))
    rescanModalOpen.value = false
    await fetchSkills()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.17vebon'))
  } finally {
    actionKey.value = ''
  }
}

const currentUser = () => localStorage.getItem('username') || 'admin'
const cancelledReason = phrase('legacy.1fphrle')
const isCancelled = (record) => record?.status === 'REJECTED' && record?.rejection_reason === cancelledReason

const openBatchRescan = () => {
  if (actionKey.value || !batchCount('rescan')) return
  singleRescanRecord.value = null
  rescanRecords.value = [...selectedRows.value]
  rescanModalOpen.value = true
}

const submitRescan = async options => {
  if (actionKey.value) return
  if (singleRescanRecord.value) return submitSingleRescan(singleRescanRecord.value, options)
  await handleBatch('rescan', rescanRecords.value, options)
  rescanModalOpen.value = false
}

const handleBatch = async (action, records = [...selectedRows.value], options = {}) => {
  if (actionKey.value || !records.length) return
  actionKey.value = `batch:${action}`
  batchResult.value = null
  try {
    const result = await runSkillBatch(records, action, record => {
      if (action === 'rescan') return rescanSkill(lifecycleVersionId(record), options)
      if (action === 'cancel') return cancelSkillScan(lifecycleVersionId(record), {
        reviewer: currentUser(),
      })
      return deleteSkill(record.skill_id)
    })
    batchResult.value = result
    selectedRowKeys.value = result.failed.map(item => item.record.skill_id)
    if (action === 'delete') {
      const remaining = Math.max(0, total.value - result.succeeded.length)
      pagination.value.current = Math.min(pagination.value.current, Math.max(1, Math.ceil(remaining / pagination.value.pageSize)))
    }
    await fetchSkills()
  } finally {
    actionKey.value = ''
  }
}

const confirmBatch = action => {
  if (actionKey.value || !batchCount(action)) return
  const records = [...selectedRows.value]
  Modal.confirm({
    title: t(`skillBatch.${action}Confirm`, { count: batchCount(action) }),
    content: t(`skillBatch.${action}Warning`),
    okText: t('skillBatch.confirm'),
    cancelText: t('skillBatch.dismiss'),
    okType: action === 'delete' ? 'danger' : 'primary',
    onOk: () => handleBatch(action, records),
  })
}

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
  if (actionKey.value || !canRunSkillAction('cancel', record)) return
  actionKey.value = `cancel:${record.skill_id}`
  try {
    await cancelSkillScan(lifecycleVersionId(record), {
      reviewer: currentUser(),
    })
    message.success(phrase('legacy.lkn23t'))
    await fetchSkills()
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

const statusDisplay = (value, record) => {
  if (isCancelled(record)) return t('skillFilters.cancelled')
  const key = {
    PENDING: 'scanning', VETTED: 'awaitingReview', APPROVED: 'approved',
    DEPLOYED: 'deployed', REJECTED: 'rejected', RETIRED: 'retired',
  }[value]
  return key ? t(`skillFilters.${key}`) : value || '-'
}
const batchSkipGroups = computed(() => {
  const groups = new Map()
  for (const { record, reason } of batchResult.value?.skipped || []) {
    const state = reason === 'already_scanning' || record.scan_pending || record.status === 'PENDING' ? 'SCANNING' : record.status
    const key = `${reason}:${state}`
    if (!groups.has(key)) groups.set(key, {
      key, reason, names: [],
      status: state === 'SCANNING' ? t('skillFilters.scanning') : statusDisplay(record.status, record),
    })
    groups.get(key).names.push(record.name)
  }
  return [...groups.values()]
})
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
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(refreshTimer)
})

watch([status, risk, sandboxFilter], () => {
  selectedRowKeys.value = []
  pagination.value = {
    ...pagination.value,
    current: 1,
  }
  fetchSkills()
})
</script>

<style scoped>
.column-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 4px 0; width: 300px; max-width: calc(100vw - 64px); }
.reset-columns { margin-top: 12px; padding-left: 0; }
.column-options :deep(.ant-checkbox-wrapper) { margin-inline-start: 0; }
.short-id,
.actions-cell {
  white-space: nowrap;
}
</style>

<style scoped>
.batch-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding-bottom: 16px;
}
.batch-result {
  margin-bottom: 12px;
  overflow-wrap: anywhere;
}
</style>
