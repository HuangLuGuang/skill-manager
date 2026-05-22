<template>
  <div>
    <a-page-header title="总览" sub-title="Agent Manager 核心指标与待处理事项" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :sm="12" :lg="6" v-for="item in metrics" :key="item.label">
        <a-card>
          <a-statistic :title="item.label" :value="item.value" />
          <div class="metric-note">{{ item.note }}</div>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="8">
        <a-card title="状态分布">
          <Chart :options="statusChartOptions" height="300px" />
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
        <a-card title="最近待处理技能">
          <a-table :data-source="pendingRows" :columns="pendingColumns" rowKey="skill_id" :pagination="{ pageSize: 5 }" :locale="{ emptyText: '当前没有待处理技能' }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.name }}</a>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
              </template>
              <template v-else-if="column.key === 'risk'">
                <a-tag :color="riskColor(record.risk_level)">{{ record.risk_level || '-' }}</a-tag>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="10">
        <a-card title="最近阻断事件">
          <a-list :data-source="blockedEvents" bordered :locale="{ emptyText: '最近没有阻断事件' }">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space direction="vertical" size="small">
                  <strong>{{ item.event_type }}</strong>
                  <span>{{ item.skill_name || item.skill_id }}</span>
                  <span class="muted-text">{{ item.actor || 'system' }} · {{ formatDateTime(item.timestamp) }}</span>
                  <span class="muted-text">{{ formatDetails(item.details, 3) }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import Chart from '../components/Chart.vue'
import { getAudit, getDashboardRiskSourceStats, listReviewQueue, listSkills } from '../api'
import { formatDateTime, formatDetails } from '../utils/format'

const skillRows = ref([])
const reviewRows = ref([])
const auditRows = ref([])
const riskSourceRows = ref([])

const metrics = computed(() => {
  const deployments = skillRows.value.filter((item) => ['APPROVED', 'DEPLOYED'].includes(item.status)).length
  const blocked = auditRows.value.filter((item) =>
    ['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked'].includes(item.event_type),
  ).length

  return [
    { label: '技能总数', value: skillRows.value.length, note: '当前 registry 中的技能总数' },
    { label: '待审核', value: reviewRows.value.length, note: '待审核技能 数量' },
    { label: '可部署/已部署', value: deployments, note: 'APPROVED + DEPLOYED 状态聚合' },
    { label: '阻断事件', value: blocked, note: '最近 7 天被拦截的运行时事件' },
  ]
})

const pendingRows = computed(() =>
  skillRows.value
    .filter((item) => ['VETTED', 'APPROVED'].includes(item.status))
    .slice(0, 8),
)

const blockedEvents = computed(() =>
  auditRows.value
    .filter((item) => ['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked'].includes(item.event_type))
    .slice(-8)
    .reverse(),
)

const pendingColumns = [
  { title: '技能名称', dataIndex: 'name', key: 'name' },
  { title: 'Status', dataIndex: 'status', key: 'status', width: 120 },
  { title: 'Risk', dataIndex: 'risk_level', key: 'risk', width: 120 },
  { title: 'Submitted At', dataIndex: 'submitted_at', key: 'submitted_at', width: 220, customRender: ({ text }) => formatDateTime(text) },
]

const buildBarChart = (title, items, color) => ({
  tooltip: { trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: items.map((item) => item.label),
    axisTick: { show: false },
  },
  yAxis: { type: 'value' },
  series: [
    {
      name: title,
      type: 'bar',
      data: items.map((item) => item.value),
      itemStyle: { color, borderRadius: [6, 6, 0, 0] },
    },
  ],
  grid: { left: 32, right: 16, top: 24, bottom: 24, containLabel: true },
})

const riskSourceChartOptions = computed(() => {
  const fallback = [
    { key: 'rule', label: '规则分析', count: 0, skills: 0 },
    { key: 'llm', label: '大模型分析', count: 0, skills: 0 },
    { key: 'sandbox', label: 'Sandbox', count: 0, skills: 0 },
  ]
  const rows = riskSourceRows.value.length ? riskSourceRows.value : fallback
  const colors = {
    rule: '#2563eb',
    llm: '#16a34a',
    sandbox: '#ea580c',
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
          `涉及技能：${row.skills || 0}`,
          `严重/高/中/低：${row.critical || 0}/${row.high || 0}/${row.medium || 0}/${row.low || 0}`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: rows.map((item) => item.label),
      axisTick: { show: false },
    },
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
    grid: { left: 32, right: 16, top: 24, bottom: 24, containLabel: true },
  }
})

const statusChartOptions = computed(() => {
  const counts = ['VETTED', 'APPROVED', 'DEPLOYED', 'REJECTED', 'RETIRED'].map((label) => ({
    label,
    value: skillRows.value.filter((item) => item.status === label).length,
  }))
  return buildBarChart('Status', counts, '#1c6ea4')
})

const riskChartOptions = computed(() => {
  const counts = ['LOW', 'MEDIUM', 'HIGH', 'EXTREME'].map((label) => ({
    label,
    value: skillRows.value.filter((item) => item.risk_level === label).length,
  }))
  return buildBarChart('Risk', counts, '#d97706')
})

const fetchDashboard = async () => {
  try {
    const [skills, review, audit, riskSourceStats] = await Promise.all([
      listSkills(),
      listReviewQueue(),
      getAudit({ since_hours: 168, limit: 300 }),
      getDashboardRiskSourceStats(),
    ])
    skillRows.value = Array.isArray(skills) ? skills : []
    reviewRows.value = Array.isArray(review) ? review : []
    auditRows.value = Array.isArray(audit) ? audit : []
    riskSourceRows.value = Array.isArray(riskSourceStats?.items) ? riskSourceStats.items : []
  } catch (error) {
    message.error(error.response?.data?.detail || '获取 Dashboard 数据失败')
  }
}

const statusColor = (value) =>
  ({
    VETTED: 'orange',
    APPROVED: 'green',
    DEPLOYED: 'blue',
    REJECTED: 'red',
    RETIRED: 'default',
  }[value] || 'default')

const riskColor = (value) =>
  ({
    SAFE: 'green',
    LOW: 'green',
    MEDIUM: 'orange',
    HIGH: 'red',
    EXTREME: 'magenta',
  }[value] || 'default')

onMounted(fetchDashboard)
</script>

<style scoped>
.metric-note {
  margin-top: 8px;
  color: #6b7280;
  font-size: 12px;
}

.muted-text {
  color: #6b7280;
  font-size: 12px;
}
</style>
