<template>
  <div class="skill-alerts-page">
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="t('skillAlerts.title')" :sub-title="t('skillAlerts.subtitle')" />
      </template>

    <a-row :gutter="12" class="summary-row">
      <a-col :xs="12" :lg="6">
        <a-card class="summary-card summary-card--danger" size="small">
          <a-statistic :title="t('skillAlerts.actionable')" :value="summary.actionable" />
        </a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card class="summary-card summary-card--neutral" size="small">
          <a-statistic :title="t('skillAlerts.missing')" :value="summary.missing" />
        </a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card class="summary-card summary-card--observe" size="small">
          <a-statistic :title="t('skillAlerts.observations')" :value="summary.observations" />
        </a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card class="summary-card summary-card--agent" size="small">
          <a-statistic :title="t('skillAlerts.affectedAgents')" :value="summary.affected_agents" />
        </a-card>
      </a-col>
    </a-row>

    <section class="alert-list-card">
      <div class="filter-bar">
        <a-segmented v-model:value="filters.category" :options="categoryOptions" @change="applyFilters" />
        <div class="filter-fields">
          <a-select v-model:value="filters.days" class="days-select" :aria-label="t('skillAlerts.timeRange')" @change="applyFilters">
            <a-select-option :value="1">{{ t('skillAlerts.oneDay') }}</a-select-option>
            <a-select-option :value="7">{{ t('skillAlerts.sevenDays') }}</a-select-option>
            <a-select-option :value="30">{{ t('skillAlerts.thirtyDays') }}</a-select-option>
            <a-select-option :value="90">{{ t('skillAlerts.ninetyDays') }}</a-select-option>
          </a-select>
          <a-input
            v-model:value="filters.skill_name"
            allow-clear
            class="filter-input"
            :placeholder="t('skillAlerts.skillPlaceholder')"
            @pressEnter="applyFilters"
            @change="clearFilterIfEmpty('skill_name')"
          />
          <a-input
            v-model:value="filters.model"
            allow-clear
            class="filter-input"
            :placeholder="t('skillAlerts.modelPlaceholder')"
            @pressEnter="applyFilters"
            @change="clearFilterIfEmpty('model')"
          />
          <a-input-search
            v-model:value="filters.q"
            allow-clear
            class="search-input"
            :placeholder="t('skillAlerts.searchPlaceholder')"
            :loading="loading"
            @search="applyFilters"
          />
        </div>
      </div>

      <a-table
        :data-source="items"
        :columns="columns"
        row-key="id"
        :loading="loading"
        :pagination="pagination"
        :scroll="{ x: 1340 }"
        size="small"
        :locale="{ emptyText: t('skillAlerts.noData') }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'severity'">
            <a-tag :color="severityColor(record.severity)">{{ severityLabel(record.severity) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'agent'">
            <div>{{ record.agent_name || record.agent_id || '-' }}</div>
            <div v-if="record.agent_name && record.agent_id" class="muted">{{ record.agent_id }}</div>
          </template>
          <template v-else-if="column.key === 'skill'">
            <div>{{ record.skill_name || '-' }}</div>
            <div v-if="record.skill_version_id || record.skill_id" class="muted id-text">
              {{ record.skill_version_id || record.skill_id }}
            </div>
          </template>
          <template v-else-if="column.key === 'reason'">
            <a-space size="small" wrap>
              <a-tag v-for="code in record.alert_codes" :key="code" :color="severityColor(record.severity)">
                {{ alertLabel(code) }}
              </a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'credential'">
            <div>{{ record.credential_name || '-' }}</div>
            <div class="muted">{{ record.credential_type || '-' }}</div>
          </template>
          <template v-else-if="column.key === 'requestStatus'">
            <a-tag :color="record.request_status === 'success' ? 'green' : 'red'">{{ record.request_status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'time'">{{ formatBeijingDateTime(record.created_at) }}</template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button type="link" size="small" @click="openDetails(record)">{{ t('skillAlerts.details') }}</a-button>
              <a-button type="link" size="small" @click="openTrace(record)">{{ t('skillAlerts.viewTrace') }}</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </section>

    </a-card>

    <a-drawer v-model:open="drawerOpen" :title="t('skillAlerts.details')" width="720" destroy-on-close>
      <a-descriptions v-if="selected" bordered :column="2" size="small">
        <a-descriptions-item :label="t('skillAlerts.requestId')" :span="2"><code>{{ selected.request_id }}</code></a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.severity')">
          <a-tag :color="severityColor(selected.severity)">{{ severityLabel(selected.severity) }}</a-tag>
        </a-descriptions-item>
        <a-descriptions-item :label="t('gatewaySkill.trustState')">{{ trustStateLabel(selected.trust_state) }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.agent')">{{ selected.agent_name || selected.agent_id || '-' }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.model')">{{ selected.model }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.skill')">{{ selected.skill_name || '-' }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.contextSource')">{{ selected.context_source || '-' }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.skillFamilyId')" :span="2"><code>{{ selected.skill_id || '-' }}</code></a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.skillVersionId')" :span="2"><code>{{ selected.skill_version_id || '-' }}</code></a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.credential')">{{ selected.credential_name || '-' }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.credentialType')">{{ selected.credential_type || '-' }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.requestStatus')">{{ selected.request_status }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.time')">{{ formatBeijingDateTime(selected.created_at) }}</a-descriptions-item>
        <a-descriptions-item :label="t('skillAlerts.reason')" :span="2">
          <a-space wrap>
            <a-tag v-for="code in selected.alert_codes" :key="code" :color="severityColor(selected.severity)">
              {{ alertLabel(code) }}
            </a-tag>
          </a-space>
        </a-descriptions-item>
      </a-descriptions>
      <template #extra>
        <a-button type="primary" @click="openTrace(selected)">{{ t('skillAlerts.viewTrace') }}</a-button>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

import { listModelSkillAlerts } from '../api'
import { formatBeijingDateTime } from '../utils/format'

const { t } = useI18n()
const router = useRouter()
const loading = ref(false)
const items = ref([])
const summary = ref({ actionable: 0, missing: 0, observations: 0, affected_agents: 0 })
const selected = ref(null)
const drawerOpen = ref(false)
const filters = reactive({ category: 'actionable', days: 7, skill_name: '', model: '', q: '' })
const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showSizeChanger: true,
  showTotal: total => t('skillAlerts.total', { total }),
})

const categoryOptions = computed(() => [
  { label: t('skillAlerts.actionable'), value: 'actionable' },
  { label: t('skillAlerts.missing'), value: 'missing' },
  { label: t('skillAlerts.observations'), value: 'observation' },
  { label: t('skillAlerts.all'), value: 'all' },
])
const columns = computed(() => [
  { title: t('skillAlerts.time'), key: 'time', width: 170 },
  { title: t('skillAlerts.severity'), key: 'severity', width: 80 },
  { title: t('skillAlerts.agent'), key: 'agent', width: 160 },
  { title: t('skillAlerts.skill'), key: 'skill', width: 190 },
  { title: t('skillAlerts.reason'), key: 'reason', width: 260 },
  { title: t('skillAlerts.model'), dataIndex: 'model', width: 140 },
  { title: t('skillAlerts.credential'), key: 'credential', width: 160 },
  { title: t('skillAlerts.requestStatus'), key: 'requestStatus', width: 100 },
  { title: t('skillAlerts.actions'), key: 'actions', width: 170, fixed: 'right' },
])

const severityColor = value => ({ high: 'red', medium: 'orange', info: 'default' }[value] || 'default')
const severityLabel = value => ({
  high: t('skillAlerts.high'),
  medium: t('skillAlerts.medium'),
  info: t('skillAlerts.info'),
}[value] || value || '-')
const trustStateLabel = value => ({
  missing: t('gatewaySkill.missing'),
  declared_trusted: t('gatewaySkill.declaredTrusted'),
  suspicious: t('gatewaySkill.suspicious'),
}[value] || value || '-')
const alertLabel = code => ({
  'gateway.skill_context_missing': t('gatewaySkill.contextMissing'),
  'gateway.skill_unknown': t('gatewaySkill.unknown'),
  'gateway.skill_id_mismatch': t('gatewaySkill.idMismatch'),
  'gateway.skill_name_mismatch': t('gatewaySkill.nameMismatch'),
  'gateway.skill_not_loadable': t('gatewaySkill.notLoadable'),
  'gateway.skill_not_allowed_for_agent': t('gatewaySkill.notAllowed'),
  'gateway.skill_context_unverified': t('gatewaySkill.unverified'),
}[code] || code)

const fetchAlerts = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const response = await listModelSkillAlerts({
      page: pagination.current,
      page_size: pagination.pageSize,
      days: filters.days,
      category: filters.category,
      skill_name: filters.skill_name || undefined,
      model: filters.model || undefined,
      q: filters.q || undefined,
    })
    items.value = response.items || []
    summary.value = response.summary || summary.value
    pagination.total = response.total || 0
  } catch (error) {
    message.error(error.response?.data?.detail || t('skillAlerts.loadFailed'))
  } finally {
    loading.value = false
  }
}

const applyFilters = () => {
  pagination.current = 1
  fetchAlerts()
}
const clearFilterIfEmpty = key => {
  if (!filters[key]) applyFilters()
}
const handleTableChange = pager => {
  pagination.current = pager.current
  pagination.pageSize = pager.pageSize
  fetchAlerts()
}
const openDetails = record => {
  selected.value = record
  drawerOpen.value = true
}
const openTrace = record => {
  if (!record?.request_id) return
  router.push({ path: '/pipeline-trace', query: { request_id: record.request_id } })
}

onMounted(fetchAlerts)
</script>

<style scoped>
.skill-alerts-page {
  min-width: 0;
}

.summary-row {
  margin-top: 8px;
}

.summary-card {
  height: 100%;
  border-left: 3px solid transparent;
}

.summary-card--danger { border-left-color: #cf1322; }
.summary-card--neutral { border-left-color: #8c8c8c; }
.summary-card--observe { border-left-color: #d48806; }
.summary-card--agent { border-left-color: #1677ff; }

.alert-list-card {
  margin-top: 16px;
}

.filter-bar,
.filter-fields {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-bar {
  justify-content: space-between;
  margin-bottom: 16px;
}

.days-select { width: 130px; }
.filter-input { width: 180px; }
.search-input { width: 280px; }

.muted {
  color: rgba(0, 0, 0, 0.45);
  font-size: 12px;
}

.id-text {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 768px) {
  .summary-row :deep(.ant-col) { margin-bottom: 12px; }
  .filter-bar,
  .filter-fields { align-items: stretch; }
  .filter-fields,
  .days-select,
  .filter-input,
  .search-input { width: 100%; }
}
</style>
