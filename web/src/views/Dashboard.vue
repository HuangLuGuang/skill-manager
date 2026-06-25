<template>
  <div>
    <a-page-header title="平台总览" sub-title="查看智能体、Skill、Prompt 与模型网关的治理状态" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :lg="12" :xl="6" v-for="item in moduleCards" :key="item.key">
        <a-card class="module-card" :title="item.title">
          <template #extra>
            <a-button type="link" size="small" @click="$router.push(item.path)">进入</a-button>
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
            <div class="module-flow-title">接入路径</div>
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
      <a-col :xs="24" :xl="15">
        <a-card title="待办中心">
          <a-table
            :data-source="todoRows"
            :columns="todoColumns"
            rowKey="id"
            :pagination="{ pageSize: 8 }"
            :locale="{ emptyText: '当前没有待处理事项' }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <a-tag :color="todoTypeColor(record.type)">{{ record.type }}</a-tag>
              </template>
              <template v-else-if="column.key === 'name'">
                <a @click="$router.push(record.path)">{{ record.name }}</a>
                <div class="muted-text">{{ record.description }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)">{{ statusDisplay(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'risk'">
                <a-tag :color="riskColor(record.risk)">{{ riskDisplay(record.risk) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-button type="link" size="small" @click="$router.push(record.path)">处理</a-button>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="9">
        <a-card title="近期运行事件">
          <a-list :data-source="recentEvents" bordered :locale="{ emptyText: '最近没有高风险或阻断事件' }">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space direction="vertical" size="small">
                  <a-space>
                    <a-tag :color="eventColor(item.event_type)">{{ eventDisplay(item.event_type) }}</a-tag>
                    <strong>{{ item.skill_name || item.skill_id || '运行事件' }}</strong>
                  </a-space>
                  <span class="muted-text">{{ item.actor || 'system' }} · {{ formatDateTime(item.timestamp) }}</span>
                  <span class="muted-text">{{ formatDetails(item.details, 3) }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="8">
        <a-card title="治理状态分布">
          <Chart :options="governanceStatusChartOptions" height="300px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="8">
        <a-card title="风险分布">
          <Chart :options="riskChartOptions" height="300px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="8">
        <a-card title="风险来源发现项">
          <Chart :options="riskSourceChartOptions" height="300px" />
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="14">
        <a-card title="模型网关 Token 与压缩趋势">
          <Chart :options="gatewayTrendChartOptions" height="320px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="10">
        <a-card title="模型调用 Top">
          <Chart :options="gatewayModelChartOptions" height="320px" />
        </a-card>
      </a-col>
    </a-row>

  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import Chart from '../components/Chart.vue'
import {
  getAudit,
  getDashboardRiskSourceStats,
  getLlmStatsByModel,
  getLlmStatsDaily,
  getLlmStatsOverview,
  listAccessTokens,
  listAgents,
  listLlmApiKeys,
  listModelEndpoints,
  listModelProviders,
  listPromptReviewQueue,
  listPrompts,
  listReviewQueue,
  listSkills,
} from '../api'
import { formatDateTime, formatDetails } from '../utils/format'

const skillRows = ref([])
const skillReviewRows = ref([])
const promptRows = ref([])
const promptReviewRows = ref([])
const agentRows = ref([])
const providerRows = ref([])
const modelRows = ref([])
const accessTokenRows = ref([])
const gatewayKeyRows = ref([])
const auditRows = ref([])
const riskSourceRows = ref([])
const gatewayOverview = ref({})
const gatewayDailyRows = ref([])
const gatewayModelRows = ref([])

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

const countByRisk = (rows, risks) => {
  const values = Array.isArray(risks) ? risks : [risks]
  return rows.filter((item) => values.includes(item.risk_level)).length
}

const activeAccessTokens = computed(() =>
  accessTokenRows.value.filter((item) => item.status === 'active'),
)
const activeGatewayKeys = computed(() =>
  gatewayKeyRows.value.filter((item) => item.status === 'active'),
)

const moduleCards = computed(() => [
  {
    key: 'skills',
    title: 'Skill 治理',
    path: '/submit',
    value: skillRows.value.length,
    label: '已提交 Skill',
    flow: ['提交', '扫描', '审核', '可信版本'],
    stats: [
      { label: '待审核', value: skillReviewRows.value.length },
      { label: '可加载', value: countByStatus(skillRows.value, 'APPROVED') },
      { label: '高风险', value: countByRisk(skillRows.value, ['suspicious', 'malicious']) },
      { label: '已拒绝', value: countByStatus(skillRows.value, 'REJECTED') },
    ],
  },
  {
    key: 'prompts',
    title: 'Prompt 治理',
    path: '/prompts',
    value: promptRows.value.length,
    label: '已提交 Prompt',
    flow: ['提交', '检测', '审核', '可授权'],
    stats: [
      { label: '待审核', value: promptReviewRows.value.length },
      { label: '可加载', value: countByStatus(promptRows.value, 'APPROVED') },
      { label: '高风险', value: countByRisk(promptRows.value, ['suspicious', 'malicious']) },
      { label: '已拒绝', value: countByStatus(promptRows.value, 'REJECTED') },
    ],
  },
  {
    key: 'agents',
    title: '智能体管理',
    path: '/agents',
    value: agentRows.value.length,
    label: '已登记智能体',
    flow: ['创建 Agent', '绑定能力', '签发凭证', '接入守卫'],
    stats: [
      { label: '已启用', value: countByStatus(agentRows.value, 'active') },
      { label: '绑定凭证', value: agentRows.value.filter((item) => item.runtime_token_id || item.runtime_token_name).length },
      { label: '绑定 Skill', value: agentRows.value.reduce((sum, item) => sum + (item.skill_names?.length || 0), 0) },
      { label: '绑定 Prompt', value: agentRows.value.reduce((sum, item) => sum + (item.prompt_names?.length || 0), 0) },
    ],
  },
  {
    key: 'gateway',
    title: '模型网关',
    path: '/model-gateway/models',
    value: modelRows.value.length,
    label: '已配置模型',
    flow: ['配置供应商', '添加模型', '绑定组策略', '审计统计'],
    stats: [
      { label: '可用模型', value: modelRows.value.filter((item) => item.enabled).length },
      { label: '供应商', value: providerRows.value.length },
      { label: '接入凭证', value: activeAccessTokens.value.length + activeGatewayKeys.value.length },
      { label: '近 7 天调用', value: gatewayOverview.value.total_requests || 0 },
    ],
  },
])

const todoRows = computed(() => {
  const skillTodos = skillRows.value
    .filter((item) => item.status === 'VETTED')
    .map((item) => ({
      id: `skill-${item.skill_id}`,
      type: 'Skill',
      name: item.name,
      description: '等待人工审核',
      status: item.status,
      risk: item.risk_level,
      time: item.submitted_at,
      path: `/skills/${item.skill_id}`,
    }))
  const promptTodos = promptRows.value
    .filter((item) => item.status === 'VETTED')
    .map((item) => ({
      id: `prompt-${item.prompt_id}`,
      type: 'Prompt',
      name: item.name,
      description: '等待人工审核',
      status: item.status,
      risk: item.risk_level,
      time: item.submitted_at,
      path: `/prompts/${item.prompt_id}`,
    }))
  return [...skillTodos, ...promptTodos]
    .sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0))
    .slice(0, 20)
})

const recentEvents = computed(() =>
  auditRows.value
    .filter((item) => ['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked', 'skill_rejected'].includes(item.event_type))
    .slice(-8)
    .reverse(),
)

const todoColumns = [
  { title: '类型', dataIndex: 'type', key: 'type', width: 100 },
  { title: '对象', dataIndex: 'name', key: 'name' },
  { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
  { title: '风险', dataIndex: 'risk', key: 'risk', width: 100 },
  { title: '时间', dataIndex: 'time', key: 'time', width: 180, customRender: ({ text }) => formatDateTime(text) },
  { title: '操作', key: 'action', width: 80 },
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
    xAxis: { type: 'category', data: statuses.map(statusDisplay), axisTick: { show: false } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: 'Skill',
        type: 'bar',
        data: statuses.map((status) => countByStatus(skillRows.value, status)),
        itemStyle: { color: '#2563eb', borderRadius: [4, 4, 0, 0] },
      },
      {
        name: 'Prompt',
        type: 'bar',
        data: statuses.map((status) => countByStatus(promptRows.value, status)),
        itemStyle: { color: '#16a34a', borderRadius: [4, 4, 0, 0] },
      },
    ],
    grid: { left: 32, right: 16, top: 40, bottom: 24, containLabel: true },
  }
})

const riskChartOptions = computed(() => {
  const rows = [
    { label: '安全', value: countByRisk(skillRows.value, 'benign') + countByRisk(promptRows.value, 'benign') },
    { label: '可疑', value: countByRisk(skillRows.value, 'suspicious') + countByRisk(promptRows.value, 'suspicious') },
    { label: '恶意', value: countByRisk(skillRows.value, 'malicious') + countByRisk(promptRows.value, 'malicious') },
  ]
  return buildBarChart('风险对象', rows, '#d97706')
})

const riskSourceChartOptions = computed(() => {
  const fallback = [
    { key: 'rule', label: '规则分析', count: 0, skills: 0 },
    { key: 'llm', label: '大模型分析', count: 0, skills: 0 },
    { key: 'sandbox', label: 'Sandbox', count: 0, skills: 0 },
    { key: 'skillspector', label: '深度分析', count: 0, skills: 0 },
  ]
  const rows = riskSourceRows.value.length ? riskSourceRows.value.map((item) => ({
    ...item,
    label: item.key === 'skillspector' ? '深度分析' : item.label,
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
          `发现项：${row.count || 0}`,
          `涉及 Skill：${row.skills || 0}`,
          `严重/高/中/低：${row.critical || 0}/${row.high || 0}/${row.medium || 0}/${row.low || 0}`,
        ].join('<br/>')
      },
    },
    xAxis: { type: 'category', data: rows.map((item) => item.label), axisTick: { show: false } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: '发现项',
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
        name: '调用次数',
        type: 'line',
        smooth: true,
        data: rows.map((item) => item.requests || 0),
        itemStyle: { color: '#2563eb' },
        areaStyle: { color: 'rgba(37, 99, 235, 0.12)' },
      },
      {
        name: '节省 Token',
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
    '调用次数',
    rows.map((item) => ({ label: item.model || 'unknown', value: item.requests || 0 })),
    '#7c3aed',
  )
})

const fetchDashboard = async () => {
  try {
    const [
      skills,
      skillReview,
      prompts,
      promptReview,
      agents,
      providers,
      models,
      accessTokens,
      gatewayKeys,
      audit,
      riskSourceStats,
      llmOverview,
      llmDaily,
      llmByModel,
    ] = await Promise.all([
      safeRequest(() => listSkills(), []),
      safeRequest(() => listReviewQueue(), []),
      safeRequest(() => listPrompts(), []),
      safeRequest(() => listPromptReviewQueue(), []),
      safeRequest(() => listAgents(), []),
      safeRequest(() => listModelProviders(), []),
      safeRequest(() => listModelEndpoints(), []),
      safeRequest(() => listAccessTokens(), { items: [] }),
      safeRequest(() => listLlmApiKeys(), []),
      safeRequest(() => getAudit({ since_hours: 168, limit: 300 }), []),
      safeRequest(() => getDashboardRiskSourceStats(), { items: [] }),
      safeRequest(() => getLlmStatsOverview({ days: 7 }), {}),
      safeRequest(() => getLlmStatsDaily({ days: 7 }), { series: [] }),
      safeRequest(() => getLlmStatsByModel({ days: 7 }), { models: [] }),
    ])

    skillRows.value = toArray(skills)
    skillReviewRows.value = toArray(skillReview)
    promptRows.value = toArray(prompts)
    promptReviewRows.value = toArray(promptReview)
    agentRows.value = toArray(agents)
    providerRows.value = toArray(providers)
    modelRows.value = toArray(models)
    accessTokenRows.value = toArray(accessTokens)
    gatewayKeyRows.value = toArray(gatewayKeys)
    auditRows.value = toArray(audit)
    riskSourceRows.value = toArray(riskSourceStats)
    gatewayOverview.value = llmOverview || {}
    gatewayDailyRows.value = toArray(llmDaily, 'series')
    gatewayModelRows.value = toArray(llmByModel, 'models')
  } catch (error) {
    message.error(error.response?.data?.detail || '获取平台总览数据失败')
  }
}

const todoTypeColor = (value) =>
  ({
    Skill: 'blue',
    Prompt: 'green',
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
    PENDING: '分析中',
    VETTED: '待审核',
    APPROVED: '已批准',
    DEPLOYED: '已启用',
    REJECTED: '已拒绝',
    active: '已启用',
    inactive: '未启用',
    revoked: '已吊销',
  }[value] || value || '-')

const riskColor = (value) =>
  ({
    benign: 'green',
    suspicious: 'orange',
    malicious: 'red',
  }[value] || 'default')

const riskDisplay = (value) =>
  ({
    benign: '安全',
    suspicious: '可疑',
    malicious: '恶意',
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
    skill_load_blocked: '加载阻断',
    skill_tamper_detected: '篡改阻断',
    tool_blocked: '工具阻断',
    skill_rejected: '审核拒绝',
  }[value] || value)

onMounted(fetchDashboard)
</script>

<style scoped>
.module-card {
  height: 100%;
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
  white-space: nowrap;
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

.muted-text {
  color: #6b7280;
  font-size: 12px;
}

</style>
