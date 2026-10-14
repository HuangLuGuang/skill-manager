<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('agentIntegration.title')" :sub-title="$t('agentIntegration.subtitle')" />
      </template>


    <a-tabs :active-key="activeTab" @change="changeTab">
      <a-tab-pane key="guide" :tab="$t('agentIntegration.guide')">
        <AgentIntegrationGuide :trace-enabled="traceEnabled" />
      </a-tab-pane>
      <a-tab-pane key="records" :tab="$t('agentIntegration.records')">
        <a-alert type="info" show-icon :message="$t('agentIntegration.recordsHelp')" />
        <a-space wrap style="margin-top: 16px">
          <a-button v-for="item in recordLinks.filter(item => pageAllowed(item.path) && (item.path !== '/runtime-traces' || traceEnabled))" :key="item.path" @click="router.push(item.path)">{{ $t(item.label) }}</a-button>
        </a-space>
    <a-row v-if="hasAccess('skills:view')" :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24">
        <a-card :title="$t('legacy.wz9nkl')">
          <a-space style="margin-bottom: 16px" wrap>
            <a-select v-model:value="eventFilter" style="width: 220px" @change="handleAuditFilterChange">
              <a-select-option value="all">{{ $t("legacy.1jb5dqs") }}</a-select-option>
              <a-select-option v-for="option in runtimeEventOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </a-select-option>
            </a-select>
            <a-input v-model:value="auditKeyword" :placeholder="$t('legacy.5yag5')" style="width: 240px" allow-clear />
            <a-button type="primary" @click="handleAuditFilterChange" :loading="loadingAudit">{{ $t("legacy.16mfmhy") }}</a-button>
            <a-button @click="resetAuditFilters" :disabled="loadingAudit">{{ $t("legacy.1wq9feq") }}</a-button>
          </a-space>

          <div class="table-meta">{{ $t("legacy.1vsm2qk") }} {{ auditTotal }} {{ $t("legacy.1tz183z") }}</div>

          <a-table
            :data-source="auditRows"
            :columns="auditColumns"
            rowKey="event_id"
            :scroll="{ x: 1100 }"
            :loading="loadingAudit"
            :pagination="auditPagination"
            :locale="{ emptyText: $t('legacy.1qzv31n') }"
            @change="handleAuditTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'skill_name'">
                <a v-if="record.skill_id && record.skill_id !== 'unknown'" @click="$router.push(`/skills/${record.skill_id}`)">
                  {{ record.skill_name }}
                </a>
                <span v-else>{{ record.skill_name }}</span>
              </template>
              <template v-else-if="column.key === 'event_type'">
                <a-tag :color="runtimeEventColor(record.event_type)">{{ runtimeEventLabel(record.event_type) }}</a-tag>
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
                <span>{{ formatRuntimeDetails(record.details) }}</span>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>
    </a-row>
      </a-tab-pane>
    </a-tabs>
    </a-card>

  </div>
</template>

<script setup>
import { translateLegacy as phrase, translateText as text } from '../i18n'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { can as hasAccess, pageAllowed } from '../access'
import { message } from 'ant-design-vue'

import { getAuditPaged, getSystemCapabilities } from '../api'
import AgentIntegrationGuide from '../components/AgentIntegrationGuide.vue'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const activeTab = computed(() => route.query.tab === 'records' ? 'records' : 'guide')
const changeTab = tab => router.replace({ query: { ...route.query, tab } })
const recordLinks = [
  { path: '/pipeline-trace', label: 'agentIntegration.modelRecords' },
  { path: '/mcp-governance/audit', label: 'agentIntegration.mcpRecords' },
  { path: '/runtime-traces', label: 'agentIntegration.traceRecords' },
]
watch(() => route.query.tab, tab => {
  if (tab === 'audit-policy' && hasAccess('settings:view')) router.replace({ path: '/clients', query: { policy: 'audit' } })
}, { immediate: true })

const traceEnabled = ref(false)
const loadingAudit = ref(false)

const auditRows = ref([])
const auditTotal = ref(0)
const eventFilter = ref('all')
const auditKeyword = ref(typeof route.query.q === 'string' ? route.query.q : '')
const auditSortState = ref({ field: 'timestamp', order: 'descend' })
const auditPagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: total => text(`共 ${total} 条`, `${total} total`),
})

const auditColumns = computed(() => [
  { title: phrase('legacy.1f90xvr'), dataIndex: 'timestamp', key: 'timestamp', width: 220, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: phrase('legacy.q8rrsk'), dataIndex: 'event_type', key: 'event_type', width: 170, sorter: true },
  { title: 'Skill', dataIndex: 'skill_name', key: 'skill_name', width: 180, sorter: true },
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id', width: 160 },
  { title: phrase('legacy.d22rf5'), dataIndex: 'client_ip', key: 'client_ip', width: 140 },
  { title: phrase('legacy.19fsh85'), dataIndex: 'actor', key: 'actor', width: 170, sorter: true },
  { title: phrase('legacy.xc5h04'), dataIndex: 'details', key: 'details' },
])

const runtimeEventOptions = computed(() => [
  { value: 'skill_signature_verified', label: phrase('legacy.niy9wk') },
  { value: 'skill_load_allowed', label: phrase('legacy.1b6ll1m') },
  { value: 'skill_load_blocked', label: phrase('legacy.qn8i26') },
  { value: 'skill_tamper_detected', label: phrase('legacy.1327pp') },
  { value: 'tool_invoked', label: phrase('legacy.1dc2waf') },
  { value: 'tool_blocked', label: phrase('legacy.b0w6ir') },
])
const runtimeEventTypes = computed(() => runtimeEventOptions.value.map(item => item.value))
const runtimeEventLabelMap = computed(() => Object.fromEntries(runtimeEventOptions.value.map(item => [item.value, item.label])))

const fetchRuntimeAudit = async () => {
  if (!hasAccess('skills:view')) { auditRows.value = []; auditTotal.value = 0; return }
  loadingAudit.value = true
  try {
    const res = await getAuditPaged({
      since_hours: 168,
      event_type: eventFilter.value === 'all' ? undefined : eventFilter.value,
      event_types: eventFilter.value === 'all' ? runtimeEventTypes.value.join(',') : undefined,
      q: auditKeyword.value.trim() || undefined,
      page: auditPagination.value.current,
      page_size: auditPagination.value.pageSize,
      sort_order: auditSortState.value.order === 'ascend' ? 'asc' : 'desc',
      limit: 1000,
    })
    auditRows.value = Array.isArray(res.items) ? res.items : []
    auditTotal.value = Number(res.total || 0)
    auditPagination.value = {
      ...auditPagination.value,
      total: auditTotal.value,
      current: Number(res.page || auditPagination.value.current),
      pageSize: Number(res.page_size || auditPagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.p00w7t'))
    auditRows.value = []
    auditTotal.value = 0
  } finally {
    loadingAudit.value = false
  }
}

const handleAuditTableChange = (pager, _filters, sorter) => {
  auditPagination.value = {
    ...auditPagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    auditSortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchRuntimeAudit()
}

const handleAuditFilterChange = () => {
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const resetAuditFilters = () => {
  eventFilter.value = 'all'
  auditKeyword.value = ''
  auditSortState.value = { field: 'timestamp', order: 'descend' }
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const runtimeEventLabel = (value) => runtimeEventLabelMap.value[value] || value || '-'
const runtimeEventColor = (value) => {
  if (['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked'].includes(value)) return 'red'
  if (['skill_load_allowed', 'skill_signature_verified', 'tool_invoked'].includes(value)) return 'green'
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
const formatRuntimeDetails = (details = {}) => {
  const labels = {
    status: phrase('legacy.1ccx4t4'),
    reason: phrase('legacy.jsgjbe'),
    tool: phrase('legacy.185ciet'),
    allowed: phrase('legacy.q9h21m'),
    verification_mode: phrase('legacy.1x88724'),
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
  return Object.entries(details || {})
    .filter(([key, value]) => !hidden.has(key) && value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${labels[key] || key}: ${value === true ? phrase('legacy.11bz44c') : value === false ? phrase('legacy.1qrntx4') : value}`)
    .join('；') || '-'
}

watch(() => [route.query.tab, route.query.q], () => {
  if (activeTab.value !== 'records') return
  auditKeyword.value = typeof route.query.q === 'string' ? route.query.q : ''
  handleAuditFilterChange()
})
onMounted(async () => {
  if (activeTab.value === 'records') fetchRuntimeAudit()
  try { traceEnabled.value = (await getSystemCapabilities()).features?.runtime_trace === true } catch { traceEnabled.value = false }
})
</script>

<style scoped>
:deep(.ant-page-header-heading-left) { flex-wrap: wrap; }
:deep(.ant-page-header-heading-title), :deep(.ant-page-header-heading-sub-title) { white-space: normal; overflow-wrap: anywhere; }
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
