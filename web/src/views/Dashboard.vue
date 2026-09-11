<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.1jy0sj1')" :sub-title="$t('legacy.1urpidh')">
          <template #extra>
            <a-button type="primary" @click="guideVisible = true">{{ $t("legacy.u03t1e") }}</a-button>
          </template>
        </a-page-header>
      </template>

    <a-row :gutter="[16, 16]">
      <a-col :xs="24" :xl="8" v-for="item in moduleCards" :key="item.key">
        <a-card class="module-card" :title="item.title">
          <template #extra>
            <a-button v-if="pageAllowed(item.path)" type="link" size="small" @click="$router.push(item.path)">{{ $t("legacy.58gz2l") }}</a-button>
          </template>
          <div class="module-primary">
            <span class="module-value">{{ item.value }}</span>
            <span class="module-label">{{ item.label }}</span>
          </div>
          <a-row :gutter="[8, 8]" class="module-substats">
            <a-col :span="12" v-for="stat in item.stats" :key="stat.label">
              <div class="substat">
                <div class="substat-value">{{ stat.value }}</div>
                <div class="substat-label">{{ stat.label }}</div>
              </div>
            </a-col>
          </a-row>
          <div class="module-flow">
            <div class="module-flow-title">{{ $t("legacy.1f4me9o") }}</div>
            <div class="module-flow-steps">
              <span v-for="(step, index) in item.flow" :key="step" class="flow-step">
                {{ step }}<span v-if="index < item.flow.length - 1" class="flow-arrow">→</span>
              </span>
            </div>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="16">
        <a-card :title="$t('legacy.jsrb0i')">
          <a-table
            :data-source="todoRows"
            :columns="todoColumns"
            rowKey="id"
            :pagination="{ pageSize: 8 }"
            :locale="{ emptyText: $t('legacy.ar9qc8') }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <a-tag :color="todoTypeColor(record.type)">{{ record.type }}</a-tag>
              </template>
              <template v-else-if="column.key === 'name'">
                <a v-if="pageAllowed(record.path)" @click="$router.push(record.path)">{{ record.name }}</a><span v-else>{{ record.name }}</span>
                <div class="muted-text">{{ record.description }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)">{{ statusDisplay(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'risk'">
                <a-tag :color="riskColor(record.risk)">{{ riskDisplay(record.risk) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-button v-if="pageAllowed(record.path)" type="link" size="small" @click="$router.push(record.path)">{{ $t("legacy.1p3h5cf") }}</a-button>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>

      <a-col v-if="can('skills:view')" :xs="24" :xl="8">
        <a-card :title="$t('legacy.19kwidw')" class="recent-events-card">
          <a-list class="recent-events-list" :data-source="pagedRecentEvents" bordered :locale="{ emptyText: $t('legacy.1mta22k') }">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space direction="vertical" size="small">
                  <a-space>
                    <a-tag :color="eventColor(item.event_type)">{{ eventDisplay(item.event_type) }}</a-tag>
                    <strong>{{ item.skill_name || item.skill_id || $t('legacy.1rbdzwg') }}</strong>
                  </a-space>
                  <span class="muted-text">{{ item.actor || 'system' }} · {{ formatDateTime(item.timestamp) }}</span>
                  <span class="muted-text">{{ formatDetails(item.details, 3) }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
          <a-pagination
            v-model:current="recentEventsPage"
            class="recent-events-pagination"
            :total="recentEvents.length"
            :page-size="recentEventsPageSize"
            :show-size-changer="false"
            :show-less-items="true"
          />
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="8">
        <a-card :title="$t('legacy.1kyn3wu')">
          <Chart :options="governanceStatusChartOptions" height="300px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="8">
        <a-card :title="$t('legacy.1blmte3')">
          <Chart :options="riskChartOptions" height="300px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="8">
        <a-card :title="$t('legacy.1pp4tl3')">
          <Chart :options="riskSourceChartOptions" height="300px" />
        </a-card>
      </a-col>
    </a-row>

    <a-row v-if="can('privacy_audit:view')" :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="14">
        <a-card :title="$t('legacy.zoebks')">
          <Chart :options="gatewayTrendChartOptions" height="320px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="10">
        <a-card :title="$t('legacy.dc6gel')">
          <Chart :options="gatewayModelChartOptions" height="320px" />
        </a-card>
      </a-col>
    </a-row>

    </a-card>

    <a-modal v-model:open="guideVisible" :title="$t('legacy.8y18tl')" width="980px" :footer="null">
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="12">
          <a-card size="small" :title="$t('legacy.xlet5m')">
            <a-steps size="small" direction="vertical" :current="3">
              <a-step :title="$t('legacy.17yp2z2')" :description="$t('legacy.15814ra')" />
              <a-step :title="$t('legacy.b3qxcp')" :description="$t('legacy.1tj0nfa')" />
              <a-step :title="$t('legacy.mxm4hl')" :description="$t('legacy.tby29q')" />
              <a-step :title="$t('legacy.ubr5hi')" :description="$t('legacy.16w5dv8')" />
            </a-steps>
            <a-space class="guide-actions" wrap>
              <a-button v-if="pageAllowed('/submit')" @click="$router.push('/submit')">{{ $t("legacy.knj41c") }}</a-button>
              <a-button v-if="pageAllowed('/skills')" @click="$router.push('/skills')">{{ $t("legacy.zg4apj") }}</a-button>
            </a-space>
          </a-card>
        </a-col>
        <a-col :xs="24" :lg="12">
          <a-card size="small" :title="$t('legacy.ypga3u')">
            <a-steps size="small" direction="vertical" :current="4">
              <a-step :title="$t('legacy.15vaur7')" :description="$t('legacy.19o7rej')" />
              <a-step :title="$t('legacy.1sye9u7')" :description="$t('legacy.1oytr3a')" />
              <a-step :title="$t('legacy.1odwfha')" :description="$t('legacy.e0nfzo')" />
              <a-step :title="$t('legacy.1y6ts4k')" :description="$t('legacy.c6ttxt')" />
              <a-step :title="$t('legacy.13omz3w')" :description="$t('legacy.y0e5jz')" />
            </a-steps>
            <a-space class="guide-actions" wrap>
              <a-button v-if="pageAllowed('/agents')" @click="$router.push('/agents')">{{ $t("legacy.1dq96hb") }}</a-button>
              <a-button v-if="pageAllowed('/credentials')" @click="$router.push('/credentials')">{{ $t("legacy.xm5sv6") }}</a-button>
              <a-button type="primary" v-if="pageAllowed('/runtime')" @click="$router.push('/runtime')">{{ $t("legacy.ppwp4v") }}</a-button>
            </a-space>
          </a-card>
        </a-col>
      </a-row>
    </a-modal>

  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { can, pageAllowed } from '../access'

import Chart from '../components/Chart.vue'
import {
  getAudit,
  getDashboardRiskSourceStats,
  getLlmStatsByModel,
  getLlmStatsDaily,
  getPrivacyStats,
  listAgents,
  listModelEndpoints,
  listModelProviders,
} from '../api'
import { useLocaleText } from '../i18n/useLocaleText'
import { formatDateTime, formatDetails } from '../utils/format'

const { text } = useLocaleText()
const skillSummary = ref({ total: 0, status_counts: {}, risk_counts: {}, todos: [] })
const agentRows = ref([])
const providerRows = ref([])
const modelRows = ref([])
const auditRows = ref([])
const recentEventsPage = ref(1)
const recentEventsPageSize = 5
const riskSourceRows = ref([])
const privacyStats = ref({})
const gatewayDailyRows = ref([])
const gatewayModelRows = ref([])
const guideVisible = ref(false)

const safeRequest = async (request, fallback) => {
  try {
    return await request()
  } catch {
    return fallback
  }
}

const toArray = (value, key = 'items') => {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.[key])) return value[key]
  return []
}

const countByStatus = (rows, statuses) => {
  const values = Array.isArray(statuses) ? statuses : [statuses]
  return rows.filter((item) => values.includes(item.status)).length
}

const skillStatusCount = (statuses) =>
  (Array.isArray(statuses) ? statuses : [statuses])
    .reduce((sum, status) => sum + (skillSummary.value.status_counts?.[status] || 0), 0)

const skillRiskCount = (risks) =>
  (Array.isArray(risks) ? risks : [risks])
    .reduce((sum, risk) => sum + (skillSummary.value.risk_counts?.[risk] || 0), 0)

const moduleCards = computed(() => [
  {
    key: 'skills',
    title: phrase('legacy.1meon5z'),
    path: '/submit',
    value: skillSummary.value.total,
    label: phrase('legacy.36m4ao'),
    flow: [phrase('legacy.ybr38x'), phrase('legacy.1myljr3'), phrase('legacy.1ws11do'), phrase('legacy.jhvfft')],
    stats: [
      { label: phrase('legacy.a2uv9t'), value: skillStatusCount('VETTED') },
      { label: phrase('legacy.f2p4bp'), value: skillStatusCount(['APPROVED', 'DEPLOYED']) },
      { label: phrase('legacy.197bn2e'), value: skillRiskCount(['suspicious', 'malicious']) },
      { label: phrase('legacy.16h1qdk'), value: skillStatusCount('REJECTED') },
    ],
  },
  {
    key: 'agents',
    title: phrase('legacy.5chjsa'),
    path: '/agents',
    value: agentRows.value.length,
    label: phrase('legacy.g72beo'),
    flow: [phrase('legacy.61qni9'), phrase('legacy.rvmkwi'), phrase('legacy.qiw836'), phrase('legacy.1xi4mpm')],
    stats: [
      { label: phrase('legacy.1w2s4cy'), value: countByStatus(agentRows.value, 'active') },
      { label: phrase('legacy.17bfydg'), value: agentRows.value.filter((item) => item.runtime_token_id || item.runtime_token_name).length },
      { label: phrase('legacy.1nwtm7'), value: agentRows.value.reduce((sum, item) => sum + (item.skill_names?.length || 0), 0) },
      { label: phrase('legacy.9tnz09'), value: agentRows.value.filter((item) => item.default_model).length },
    ],
  },
  {
    key: 'gateway',
    title: phrase('legacy.mfpzot'),
    path: '/model-gateway/providers',
    value: modelRows.value.length,
    label: phrase('legacy.1aglluu'),
    flow: [phrase('legacy.15teb0h'), phrase('legacy.17lmhaa'), phrase('legacy.qiw836'), phrase('legacy.5h548n')],
    stats: [
      { label: phrase('legacy.103n846'), value: modelRows.value.filter((item) => item.enabled).length },
      { label: phrase('legacy.1x7qpl0'), value: providerRows.value.length },
      { label: phrase('legacy.tcjr24'), value: can('privacy_audit:view') ? privacyStats.value.prompt_guard_events || 0 : '—' },
      { label: phrase('legacy.1fsazit'), value: can('privacy_audit:view') ? privacyStats.value.prompt_guard_blocked || 0 : '—' },
    ],
  },
].filter(item => item.key === 'skills' || (item.key === 'agents' ? can('agents:view') : can('models:view') && can('providers:view'))))

const todoRows = computed(() => {
  const skillTodos = skillSummary.value.todos
    .map((item) => ({
      id: `skill-${item.skill_id}`,
      type: 'Skill',
      name: item.name,
      description: phrase('legacy.1rgqqjv'),
      status: item.status,
      risk: item.risk_level,
      time: item.submitted_at,
      path: `/skills/${item.skill_id}`,
    }))
  return skillTodos
    .sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0))
    .slice(0, 20)
})

const recentEvents = computed(() =>
  auditRows.value
    .filter((item) => ['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked', 'skill_rejected'].includes(item.event_type))
    .reverse(),
)
const pagedRecentEvents = computed(() =>
  recentEvents.value.slice(
    (recentEventsPage.value - 1) * recentEventsPageSize,
    recentEventsPage.value * recentEventsPageSize,
  ),
)

const todoColumns = [
  { title: phrase('legacy.anh4cj'), dataIndex: 'type', key: 'type', width: 100 },
  { title: phrase('legacy.1hptjin'), dataIndex: 'name', key: 'name' },
  { title: phrase('legacy.1ccx4t4'), dataIndex: 'status', key: 'status', width: 110 },
  { title: phrase('legacy.1qgsa3s'), dataIndex: 'risk', key: 'risk', width: 100 },
  { title: phrase('legacy.1f90xvr'), dataIndex: 'time', key: 'time', width: 180, customRender: ({ text }) => formatDateTime(text) },
  { title: phrase('legacy.501w24'), key: 'action', width: 80 },
]

const buildBarChart = (title, items, color) => ({
  tooltip: { trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: items.map((item) => item.label),
    axisTick: { show: false },
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      name: title,
      type: 'bar',
      data: items.map((item) => item.value),
      itemStyle: { color, borderRadius: [6, 6, 0, 0] },
      label: { show: true, position: 'top' },
    },
  ],
  grid: { left: 32, right: 16, top: 28, bottom: 24, containLabel: true },
})

const governanceStatusChartOptions = computed(() => {
  const statuses = ['VETTED', 'APPROVED', 'REJECTED']
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0 },
    xAxis: { type: 'category', data: statuses.map(statusDisplay), axisTick: { show: false }, axisLabel: { interval: 0 } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: 'Skill',
        type: 'bar',
        data: statuses.map(skillStatusCount),
        itemStyle: { color: '#2563eb', borderRadius: [4, 4, 0, 0] },
      },
    ],
    grid: { left: 32, right: 16, top: 40, bottom: 24, containLabel: true },
  }
})

const riskChartOptions = computed(() => {
  const rows = [
    { label: text('安全', 'Safe'), value: skillRiskCount('benign') },
    { label: text('可疑', 'Suspicious'), value: skillRiskCount('suspicious') },
    { label: text('恶意', 'Malicious'), value: skillRiskCount('malicious') },
  ]
  return buildBarChart(text('风险对象', 'Risk Objects'), rows, '#d97706')
})

const riskSourceChartOptions = computed(() => {
  const fallback = [
    { key: 'rule', label: text('规则分析', 'Rule Analysis'), count: 0, skills: 0 },
    { key: 'llm', label: text('大模型分析', 'LLM Analysis'), count: 0, skills: 0 },
    { key: 'sandbox', label: 'Sandbox', count: 0, skills: 0 },
    { key: 'skillspector', label: text('深度分析', 'Deep Analysis'), count: 0, skills: 0 },
  ]
  const rows = riskSourceRows.value.length ? riskSourceRows.value.map((item) => ({
    ...item,
    label: ({
      rule: text('规则分析', 'Rule Analysis'),
      llm: text('大模型分析', 'LLM Analysis'),
      sandbox: 'Sandbox',
      skillspector: text('深度分析', 'Deep Analysis'),
    }[item.key] || item.label),
  })) : fallback
  const colors = {
    rule: '#2563eb',
    llm: '#16a34a',
    sandbox: '#ea580c',
    skillspector: '#0891b2',
  }
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const row = rows[params?.[0]?.dataIndex] || {}
        return [
          `<strong>${row.label}</strong>`,
          `${text('发现项', 'Findings')}: ${row.count || 0}`,
          `${text('涉及 Skill', 'Affected Skills')}: ${row.skills || 0}`,
          `${text('严重/高/中/低', 'Critical/High/Medium/Low')}: ${row.critical || 0}/${row.high || 0}/${row.medium || 0}/${row.low || 0}`,
        ].join('<br/>')
      },
    },
    xAxis: { type: 'category', data: rows.map((item) => item.label), axisTick: { show: false }, axisLabel: { interval: 0 } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: text('发现项', 'Findings'),
        type: 'bar',
        data: rows.map((item) => ({
          value: item.count || 0,
          itemStyle: { color: colors[item.key] || '#64748b', borderRadius: [6, 6, 0, 0] },
        })),
        label: { show: true, position: 'top' },
      },
    ],
    grid: { left: 32, right: 16, top: 28, bottom: 24, containLabel: true },
  }
})

const gatewayTrendChartOptions = computed(() => {
  const rows = gatewayDailyRows.value
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    xAxis: { type: 'category', data: rows.map((item) => item.date), axisTick: { show: false } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: text('调用次数', 'Requests'),
        type: 'line',
        smooth: true,
        data: rows.map((item) => item.requests || 0),
        itemStyle: { color: '#2563eb' },
        areaStyle: { color: 'rgba(37, 99, 235, 0.12)' },
      },
      {
        name: text('节省 Token', 'Tokens Saved'),
        type: 'line',
        smooth: true,
        data: rows.map((item) => item.tokens_saved || 0),
        itemStyle: { color: '#16a34a' },
      },
    ],
    grid: { left: 40, right: 20, top: 44, bottom: 28, containLabel: true },
  }
})

const gatewayModelChartOptions = computed(() => {
  const rows = gatewayModelRows.value.slice(0, 8)
  return buildBarChart(
    text('调用次数', 'Requests'),
    rows.map((item) => ({ label: item.model || 'unknown', value: item.requests || 0 })),
    '#7c3aed',
  )
})

const fetchDashboard = async () => {
  try {
    const [
      agents,
      providers,
      models,
      audit,
      riskSourceStats,
      gatewayPrivacy,
      llmDaily,
      llmByModel,
    ] = await Promise.all([
      can('agents:view') ? safeRequest(() => listAgents(), []) : null,
      can('providers:view') ? safeRequest(() => listModelProviders(), []) : null,
      can('models:view') ? safeRequest(() => listModelEndpoints(), []) : null,
      can('skills:view') ? safeRequest(() => getAudit({ since_hours: 168, limit: 300 }), []) : null,
      safeRequest(() => getDashboardRiskSourceStats(), { items: [] }),
      can('privacy_audit:view') ? safeRequest(() => getPrivacyStats(), {}) : null,
      can('privacy_audit:view') ? safeRequest(() => getLlmStatsDaily({ days: 7 }), { series: [] }) : null,
      can('privacy_audit:view') ? safeRequest(() => getLlmStatsByModel({ days: 7 }), { models: [] }) : null,
    ])

    agentRows.value = toArray(agents)
    providerRows.value = toArray(providers)
    modelRows.value = toArray(models)
    auditRows.value = toArray(audit)
    riskSourceRows.value = toArray(riskSourceStats)
    skillSummary.value = riskSourceStats?.skill_summary || skillSummary.value
    privacyStats.value = gatewayPrivacy || {}
    gatewayDailyRows.value = toArray(llmDaily, 'series')
    gatewayModelRows.value = toArray(llmByModel, 'models')
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.uut6dg'))
  }
}

const todoTypeColor = (value) =>
  ({
    Skill: 'blue',
    智能体: 'purple',
    模型网关: 'cyan',
    凭证: 'orange',
  }[value] || 'default')

const statusColor = (value) =>
  ({
    PENDING: 'gold',
    VETTED: 'orange',
    APPROVED: 'green',
    DEPLOYED: 'blue',
    REJECTED: 'red',
    active: 'green',
    inactive: 'default',
    revoked: 'red',
    未接入: 'orange',
    未启用: 'default',
  }[value] || 'default')

const statusDisplay = (value) =>
  ({
    PENDING: text('分析中', 'Analyzing'),
    VETTED: text('待审核', 'Pending Review'),
    APPROVED: text('已批准', 'Approved'),
    DEPLOYED: text('已启用', 'Enabled'),
    REJECTED: text('已拒绝', 'Rejected'),
    active: text('已启用', 'Enabled'),
    inactive: text('未启用', 'Disabled'),
    revoked: text('已吊销', 'Revoked'),
  }[value] || value || '-')

const riskColor = (value) =>
  ({
    benign: 'green',
    suspicious: 'orange',
    malicious: 'red',
  }[value] || 'default')

const riskDisplay = (value) =>
  ({
    benign: text('安全', 'Safe'),
    suspicious: text('可疑', 'Suspicious'),
    malicious: text('恶意', 'Malicious'),
  }[value] || '-')

const eventColor = (value) =>
  ({
    skill_load_blocked: 'red',
    skill_tamper_detected: 'red',
    tool_blocked: 'orange',
    skill_rejected: 'volcano',
  }[value] || 'default')

const eventDisplay = (value) =>
  ({
    skill_load_blocked: phrase('legacy.fxy726'),
    skill_tamper_detected: phrase('legacy.v734gz'),
    tool_blocked: phrase('legacy.uehlgl'),
    skill_rejected: phrase('legacy.qwkmdx'),
  }[value] || value)

onMounted(fetchDashboard)
</script>

<style scoped>
.recent-events-card {
  display: flex;
  flex-direction: column;
  max-height: 70vh;
}

.recent-events-card :deep(.ant-card-head) {
  flex-shrink: 0;
}

.recent-events-card :deep(.ant-card-body) {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.recent-events-list {
  min-height: 0;
  overflow-y: auto;
  overflow-wrap: anywhere;
}

.recent-events-pagination {
  flex-shrink: 0;
  margin-top: auto;
  padding-top: 16px;
  text-align: right;
}

@media (min-width: 1200px) {
  .recent-events-card {
    position: absolute;
    inset: 0 8px;
    max-height: none;
  }
}

.module-card {
  height: 100%;
}
.module-card :deep(.ant-card-head-title) {
  white-space: normal;
  overflow-wrap: anywhere;
}

.module-primary {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 14px;
}

.module-value {
  color: #111827;
  font-size: 32px;
  font-weight: 650;
  line-height: 1;
}

.module-label {
  color: #6b7280;
  font-size: 13px;
}

.module-substats {
  border-top: 1px solid #eef2f7;
  padding-top: 12px;
}

.module-flow {
  border-top: 1px solid #eef2f7;
  margin-top: 12px;
  padding-top: 10px;
}

.module-flow-title {
  color: #6b7280;
  font-size: 12px;
  margin-bottom: 6px;
}

.module-flow-steps {
  color: #374151;
  font-size: 12px;
  line-height: 1.8;
}

.flow-step {
  display: inline-block;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.flow-arrow {
  color: #9ca3af;
  margin: 0 5px;
}

.substat {
  background: #f8fafc;
  border-radius: 6px;
  padding: 8px 10px;
}

.substat-value {
  color: #111827;
  font-size: 18px;
  font-weight: 600;
}

.substat-label {
  color: #6b7280;
  font-size: 12px;
  margin-top: 2px;
}

.guide-actions {
  margin-top: 16px;
}

.muted-text {
  color: #6b7280;
  font-size: 12px;
}

</style>
