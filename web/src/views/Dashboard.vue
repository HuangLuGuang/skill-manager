<template>
  <div class="dashboard">
    <header class="dashboard-heading">
      <div><h1>{{ t('dashboard.title') }}</h1><p>{{ t('dashboard.subtitle') }}</p></div>
      <div class="heading-actions">
        <span v-if="data" class="updated">{{ t('dashboard.updated', { time: formatDateTime(data.as_of) }) }}</span>
        <a-button @click="router.push('/docs')"><BookOutlined />{{ t('dashboard.guide') }}</a-button>
        <a-button :loading="loading" :disabled="loading" @click="load(days)"><ReloadOutlined />{{ t('dashboard.refresh') }}</a-button>
      </div>
    </header>
    <a-skeleton v-if="loading && !data" active :paragraph="{ rows: 12 }" :aria-label="t('uiExperience.loading')" />
    <a-result v-else-if="!data && failed" status="warning" :title="t('dashboard.loadFailed')" :sub-title="t('dashboard.retryHint')">
      <template #extra><a-button type="primary" @click="load(days)">{{ t('dashboard.retry') }}</a-button></template>
    </a-result>
    <template v-else-if="data">
      <a-alert v-if="failed" type="warning" show-icon :message="t('dashboard.stale')" class="refresh-warning" />
      <section v-if="assetItems.length" class="asset-strip surface" :aria-label="t('dashboard.assetsLabel')">
        <component :is="pageAllowed(item.path) ? 'button' : 'div'" v-for="item in assetItems" :key="item.key" class="asset" @click="navigate(item.path)">
          <component :is="item.icon" class="asset-icon" /><div><div class="asset-label">{{ t('dashboard.' + item.key) }}</div><strong>{{ item.value }}</strong></div>
        </component>
        <a-tooltip :title="t('dashboard.assetHint')"><button class="info-button asset-help" :aria-label="t('dashboard.assetHint')"><InfoCircleOutlined /></button></a-tooltip>
      </section>
      <a-empty v-else-if="!todoTypes.length && !hasRuntime && !data.trend && !data.activity_sources.length" :description="t('dashboard.noAccess')" />
      <div class="work-grid" :class="{ 'single-column': !hasRuntime || !todoTypes.length }">
        <section v-if="todoTypes.length" class="surface pending-panel" :aria-label="t('dashboard.todos')">
          <div class="panel-heading"><h2>{{ t('dashboard.todos') }} <span class="count">{{ number(totalTodos) }}</span></h2>
            <a-button v-if="pageAllowed(activeQueuePath)" type="primary" @click="navigate(activeQueuePath)">{{ t('dashboard.viewTodos') }}</a-button>
          </div>
          <a-alert v-if="urgentCount" class="urgent-alert" type="warning" show-icon :message="t('dashboard.urgent', { count: number(urgentCount) })" />
          <a-tabs v-model:activeKey="activeTab" class="todo-tabs">
            <a-tab-pane key="all" :tab="t('dashboard.all') + ' ' + number(totalTodos)" />
            <a-tab-pane v-for="type in todoTypes" :key="type" :tab="typeLabel(type) + ' ' + number(data.todos.counts[type])" />
          </a-tabs>
          <a-table :key="activeTab" :columns="todoColumns" :data-source="visibleTodos" row-key="id" size="middle" :scroll="{ x: 590 }"
            :pagination="{ pageSize: 4, size: 'small', hideOnSinglePage: true, showSizeChanger: false }" :locale="{ emptyText: t('dashboard.noTodos') }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <div class="object-cell"><component :is="record.type === 'skill' ? FileTextOutlined : ApiOutlined" class="object-icon" />
                  <div><router-link v-if="pageAllowed(todoPath(record).path)" class="object-name" :to="todoPath(record)">{{ record.name }}</router-link><span v-else class="object-name">{{ record.name }}</span>
                    <div v-if="record.context" class="secondary object-context">{{ record.context }}</div></div>
                </div>
              </template>
              <template v-else-if="column.key === 'type'">{{ typeLabel(record.type) }}</template>
              <template v-else-if="column.key === 'risk'"><a-tag :color="riskColor(record.risk)">{{ riskLabel(record.risk) }}</a-tag></template>
              <template v-else-if="column.key === 'waiting'"><a-tooltip :title="formatDateTime(record.created_at)">{{ waiting(record.created_at) }}</a-tooltip></template>
              <template v-else-if="column.key === 'action'"><a-button v-if="pageAllowed(todoPath(record).path)" type="link" size="small" @click="router.push(todoPath(record))">{{ t('dashboard.view') }}</a-button></template>
            </template>
          </a-table>
          <p class="table-note">{{ t('dashboard.todoScope', { limit: data.todos.limit_per_type }) }}</p>
        </section>
        <section v-if="hasRuntime" class="surface runtime-panel" :aria-label="t('dashboard.runtime')">
          <div class="panel-heading"><h2>{{ t('dashboard.runtime') }}</h2><a-tooltip :title="t('dashboard.utcHint')"><button class="info-button" :aria-label="t('dashboard.utcHint')"><InfoCircleOutlined /></button></a-tooltip></div>
          <component :is="pageAllowed(item.path) ? 'button' : 'div'" v-for="item in runtimeItems" :key="item.key" class="runtime-row" @click="navigate(item.path)">
            <span class="runtime-icon"><component :is="item.icon" /></span>
            <span class="runtime-copy"><span>{{ t('dashboard.' + item.key) }}</span><strong>{{ number(item.value) }}</strong></span><RightOutlined v-if="pageAllowed(item.path)" class="row-arrow" />
          </component>
          <div v-if="data.runtime.aidr" class="aidr-section">
            <div class="aidr-heading"><span class="runtime-icon"><DatabaseOutlined /></span><h3>{{ t('dashboard.aidr') }}</h3><a-tag color="blue">{{ t('dashboard.testing') }}</a-tag></div>
            <div class="aidr-content">
              <div class="aidr-clients"><strong>{{ number(data.runtime.aidr.reporting_clients) }}</strong><span>{{ t('dashboard.reportingClients') }}</span></div>
              <div class="record-summary"><span>{{ t('dashboard.records') }} <a-tooltip :title="t('dashboard.aidrHint')"><button class="info-button" :aria-label="t('dashboard.aidrHint')"><InfoCircleOutlined /></button></a-tooltip></span><strong>{{ number(data.runtime.aidr.records) }}</strong></div>
              <a-button v-if="pageAllowed('/clients')" block @click="navigate('/clients')">{{ t('dashboard.viewEvidence') }}</a-button>
            </div>
          </div>
        </section>
      </div>
      <section v-if="data.activity_sources.length" class="surface activity-panel" :aria-label="t('dashboard.recent')">
        <div class="panel-heading"><h2>{{ t('dashboard.recent') }}</h2><a-tooltip :title="t('dashboard.activityHint')"><button class="info-button" :aria-label="t('dashboard.activityHint')"><InfoCircleOutlined /></button></a-tooltip></div>
        <a-table :columns="activityColumns" :data-source="data.activity" row-key="id" size="small" :scroll="{ x: 640 }"
          :pagination="{ pageSize: 3, size: 'small', hideOnSinglePage: true, showSizeChanger: false }" :locale="{ emptyText: t('dashboard.noActivity') }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'time'"><span class="secondary">{{ formatDateTime(record.created_at) }}</span></template>
            <template v-else-if="column.key === 'event'"><span class="event-cell"><component :is="eventIcon(record)" :class="['event-icon', eventTone(record)]" />{{ eventLabel(record) }}</span></template>
            <template v-else-if="column.key === 'source'"><a-tag>{{ t('dashboard.' + record.source + 'Source') }}</a-tag></template>
            <template v-else-if="column.key === 'name'"><router-link v-if="pageAllowed(activityPath(record).path)" class="object-name" :to="activityPath(record)">{{ record.name || '—' }}</router-link><span v-else>{{ record.name || '—' }}</span></template>
          </template>
        </a-table>
      </section>
      <section v-if="data.trend || data.skills" class="analytics-section" :aria-label="t('dashboard.analytics')">
        <header class="analytics-heading"><h2>{{ t('dashboard.analytics') }}</h2><p>{{ t('dashboard.analyticsHint') }}</p></header>
        <div class="charts-grid" :class="{ 'single-column': !data.trend || !data.skills }">
          <section v-if="data.trend" class="surface chart-panel">
            <div class="panel-heading"><h2>{{ t('dashboard.trend') }}</h2><a-radio-group :value="days" button-style="solid" :disabled="loading" @change="load($event.target.value)">
              <a-radio-button :value="7">{{ t('dashboard.sevenDays') }}</a-radio-button><a-radio-button :value="30">{{ t('dashboard.thirtyDays') }}</a-radio-button>
            </a-radio-group></div>
            <div class="chart-metric"><span class="secondary">{{ t('dashboard.todayRequests') }} <a-tooltip :title="t('dashboard.trendHint')"><button class="info-button" :aria-label="t('dashboard.trendHint')"><InfoCircleOutlined /></button></a-tooltip></span><strong>{{ number(todayRequests) }}</strong></div>
            <div role="img" :aria-label="t('dashboard.trend')"><Chart :options="trendOptions" height="250px" /></div>
            <p v-if="!trendTotal" class="chart-empty-note">{{ t('dashboard.noRequests') }}</p>
            <footer v-if="pageAllowed('/model-gateway/stats')" class="chart-footer"><a-button type="link" @click="navigate('/model-gateway/stats')">{{ t('dashboard.viewModelStats') }}<ArrowRightOutlined /></a-button></footer>
          </section>
          <section v-if="data.skills" class="surface chart-panel risk-panel">
            <div class="panel-heading"><h2>{{ t('dashboard.riskDistribution') }}</h2><span class="secondary">{{ t('dashboard.snapshot') }}</span></div>
            <div v-if="data.skills.total" role="img" :aria-label="t('dashboard.riskDistribution')"><Chart :options="riskOptions" height="275px" /></div>
            <a-empty v-else class="risk-empty" :description="t('dashboard.noSkills')" />
            <ul class="risk-legend"><li v-for="item in riskItems" :key="item.key"><span class="legend-dot" :style="{ background: item.color }" /><span>{{ item.name }}</span><strong>{{ number(item.value) }}</strong></li></ul>
            <footer v-if="pageAllowed('/skills')" class="chart-footer"><a-button type="link" @click="navigate('/skills')">{{ t('dashboard.viewSkills') }}<ArrowRightOutlined /></a-button></footer>
          </section>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ApiOutlined, AppstoreOutlined, ArrowRightOutlined, BookOutlined, CheckCircleFilled, ClockCircleOutlined, CloudServerOutlined, DatabaseOutlined, DesktopOutlined, ExclamationCircleFilled, FileTextOutlined, InfoCircleOutlined, ReloadOutlined, RightOutlined, RobotOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'
import Chart from '../components/Chart.vue'
import { getDashboardOverview } from '../api'
import { pageAllowed } from '../access'
import { formatDateTime } from '../utils/format'

const { t, te, locale } = useI18n()
const router = useRouter()
const data = ref(null)
const loading = ref(false)
const failed = ref(false)
const days = ref(7)
const activeTab = ref('all')
let disposed = false
const number = value => new Intl.NumberFormat(locale.value).format(value)
const navigate = path => { if (pageAllowed(path)) router.push(path) }
const assetItems = computed(() => [
  { key: 'agents', icon: RobotOutlined, path: '/agents' },
  { key: 'skills', icon: AppstoreOutlined, path: '/skills' },
  { key: 'mcp', icon: ApiOutlined, path: '/mcp-governance/servers' },
  { key: 'models', icon: CloudServerOutlined, path: '/model-gateway/providers' },
  { key: 'clients', icon: DesktopOutlined, path: '/clients' },
].filter(item => data.value?.assets[item.key] !== undefined).map(item => ({ ...item,
  value: item.key === 'clients' ? number(data.value.assets.clients.online) + ' / ' + number(data.value.assets.clients.total) : number(data.value.assets[item.key]),
})))
const todoTypes = computed(() => Object.keys(data.value?.todos.counts || {}))
const totalTodos = computed(() => Object.values(data.value?.todos.counts || {}).reduce((sum, n) => sum + n, 0))
const visibleTodos = computed(() => (data.value?.todos.items || []).filter(row => activeTab.value === 'all' || row.type === activeTab.value))
const urgentCount = computed(() => visibleTodos.value.filter(row => ['malicious', 'high', 'critical'].includes(row.risk)).length)
const queuePath = type => type === 'skill' ? '/review' : '/mcp-governance/approvals'
const activeQueuePath = computed(() => queuePath(activeTab.value === 'all'
  ? todoTypes.value.find(type => data.value.todos.counts[type] > 0) || todoTypes.value[0] : activeTab.value))
const typeLabel = type => t(type === 'skill' ? 'dashboard.skill' : 'dashboard.mcpApproval')
const todoPath = row => row.type === 'skill'
  ? { path: '/skills/' + encodeURIComponent(row.target_id) }
  : { path: '/mcp-governance/approvals', query: { request_id: row.target_id } }
const todoColumns = computed(() => [
  { title: t('dashboard.object'), key: 'name', width: 200 }, { title: t('dashboard.type'), key: 'type', width: 115 },
  { title: t('dashboard.risk'), key: 'risk', width: 100 }, { title: t('dashboard.waiting'), key: 'waiting', width: 100 },
  { title: t('dashboard.action'), key: 'action', width: 75, fixed: 'right' },
])
const activityColumns = computed(() => [
  { title: t('dashboard.time'), key: 'time', width: 185 }, { title: t('dashboard.source'), key: 'source', width: 90 },
  { title: t('dashboard.event'), key: 'event', width: 230 }, { title: t('dashboard.name'), key: 'name' },
])
const riskColor = risk => ({ benign: 'green', low: 'green', suspicious: 'orange', medium: 'orange', malicious: 'red', high: 'red', critical: 'red' }[risk] || 'default')
const riskLabel = risk => te('domain.risk.' + risk) ? t('domain.risk.' + risk) : t('dashboard.unknown')
const waiting = value => {
  const elapsed = Math.max(0, (Date.parse(data.value.as_of) - Date.parse(value)) / 60000)
  if (!Number.isFinite(elapsed)) return '—'
  if (elapsed < 1) return t('dashboard.justNow')
  if (elapsed < 60) return t('dashboard.minutes', { count: Math.floor(elapsed) })
  if (elapsed < 1440) return t('dashboard.hours', { count: Math.floor(elapsed / 60) })
  return t('dashboard.days', { count: Math.floor(elapsed / 1440) })
}
const runtimeItems = computed(() => [
  { key: 'modelBlocked', field: 'model_blocked_today', icon: SafetyCertificateOutlined, path: '/model-gateway/audit' },
  { key: 'mcpDenied', field: 'mcp_denied_today', icon: ApiOutlined, path: '/mcp-governance/audit' },
].filter(item => data.value?.runtime[item.field] !== undefined).map(item => ({ ...item, value: data.value.runtime[item.field] })))
const hasRuntime = computed(() => runtimeItems.value.length > 0 || Boolean(data.value?.runtime.aidr))
const eventLabel = row => {
  const key = row.source === 'skill' ? 'domain.auditEvent.' + row.event : 'dashboard.' + row.source + 'Events.' + row.event
  return te(key) ? t(key) : row.event
}
const eventTone = row => ['denied', 'error', 'failed', 'timed_out', 'blocked', 'skill_rejected', 'skill_load_blocked', 'tool_blocked', 'skill_tamper_detected'].includes(row.event) ? 'danger'
  : ['success', 'succeeded', 'skill_approved', 'skill_deployed', 'skill_load_allowed', 'skill_signature_verified'].includes(row.event) ? 'success' : 'neutral'
const eventIcon = row => ({ danger: ExclamationCircleFilled, success: CheckCircleFilled, neutral: ClockCircleOutlined }[eventTone(row)])
const activityPath = row => row.source === 'scan'
  ? { path: '/agent-security/scans', query: { stage: 'tasks', task_id: row.target_id } }
  : { path: row.source === 'mcp' ? '/mcp-governance/audit' : '/audit' }
const todayRequests = computed(() => data.value?.trend?.series.at(-1)?.requests || 0)
const trendTotal = computed(() => data.value?.trend?.series.reduce((sum, row) => sum + row.requests, 0) || 0)
const trendOptions = computed(() => ({
  aria: { enabled: true }, tooltip: { trigger: 'axis', renderMode: 'richText' },
  grid: { left: 12, right: 18, top: 35, bottom: 12, containLabel: true },
  xAxis: { type: 'category', boundaryGap: false, data: data.value.trend.series.map(row => row.date.slice(5).replace('-', '/')),
    axisTick: { show: false }, axisLine: { lineStyle: { color: '#e5eaf1' } }, axisLabel: { color: '#667085', hideOverlap: true } },
  yAxis: { type: 'value', name: t('dashboard.requests'), minInterval: 1, nameTextStyle: { color: '#667085', align: 'left' },
    splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { color: '#667085' } },
  series: [{ name: t('dashboard.requests'), type: 'line', data: data.value.trend.series.map(row => row.requests),
    symbol: 'circle', symbolSize: 6, showSymbol: days.value === 7, itemStyle: { color: '#2563eb' },
    lineStyle: { width: 2 }, areaStyle: { color: 'rgba(37,99,235,0.08)' } }],
}))
const riskItems = computed(() => {
  const summary = data.value?.skills
  if (!summary) return []
  const items = [
    { key: 'benign', color: '#16b65c' }, { key: 'suspicious', color: '#faad14' }, { key: 'malicious', color: '#ef4444' },
  ].map(item => ({ ...item, name: riskLabel(item.key), value: summary.risk_counts[item.key] || 0 }))
  const unknown = Math.max(0, summary.total - items.reduce((sum, row) => sum + row.value, 0))
  if (unknown) items.push({ key: 'unknown', name: t('dashboard.unknown'), value: unknown, color: '#94a3b8' })
  return items
})
const riskOptions = computed(() => ({
  aria: { enabled: true }, tooltip: { trigger: 'item', renderMode: 'richText' },
  title: [{ text: number(data.value.skills.total), left: 'center', top: '40%', textStyle: { fontSize: 30, fontWeight: 600, color: '#17223b' } },
    { text: t('dashboard.skillTotal'), left: 'center', top: '54%', textStyle: { fontSize: 14, fontWeight: 400, color: '#667085' } }],
  series: [{ type: 'pie', radius: ['60%', '79%'], center: ['50%', '50%'], label: { show: false },
    data: riskItems.value.map(row => ({ name: row.name, value: row.value, itemStyle: { color: row.color, borderWidth: 2, borderColor: '#fff' } })) }],
}))
async function load(requestedDays) {
  if (loading.value) return
  loading.value = true
  failed.value = false
  try {
    const result = await getDashboardOverview({ days: requestedDays })
    if (disposed) return
    data.value = result
    days.value = requestedDays
    if (activeTab.value !== 'all' && !(activeTab.value in result.todos.counts)) activeTab.value = 'all'
  } catch {
    if (!disposed) failed.value = true
  } finally {
    if (!disposed) loading.value = false
  }
}
onMounted(() => load(days.value))
onBeforeUnmount(() => { disposed = true })
</script>

<style scoped>
.dashboard { color: #17223b; min-width: 0; }
.dashboard-heading, .heading-actions, .panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.dashboard-heading { margin-bottom: 22px; }
h1, h2, h3, p { margin: 0; }
h1 { font-size: 28px; font-weight: 650; line-height: 1.4; letter-spacing: -.5px; }
h2 { font-size: 18px; font-weight: 600; line-height: 1.5; }
h3 { font-size: 14px; font-weight: 500; }
.dashboard-heading p, .analytics-heading p { color: #667085; margin-top: 5px; }
.heading-actions { gap: 10px; justify-content: flex-end; }
.updated { font-size: 12px; color: #667085; }
.surface { background: #fff; border: 1px solid #e6eaf0; border-radius: 9px; min-width: 0; }
.asset-strip { display: flex; flex-wrap: wrap; position: relative; padding: 24px 20px; margin-bottom: 18px; }
.asset { flex: 1 1 150px; display: flex; align-items: center; gap: 16px; text-align: start; padding: 8px 20px; background: transparent; border: 0; border-inline-end: 1px solid #eef1f5; color: inherit; font: inherit; min-width: 0; }
.asset:last-of-type { border-inline-end: 0; }
button.asset, button.runtime-row { cursor: pointer; }
button.asset:hover, button.runtime-row:hover { background: #f8faff; }
.asset-icon { font-size: 30px; color: #2563eb; flex-shrink: 0; }
.asset-label { color: #667085; font-size: 14px; margin-bottom: 5px; }
.asset strong { font-size: 28px; font-weight: 650; line-height: 1.2; font-variant-numeric: tabular-nums; white-space: nowrap; }
.asset-help { position: absolute; right: 8px; top: 6px; }
.info-button { border: 0; background: transparent; padding: 2px; color: #78869f; line-height: 1; cursor: help; font-size: 13px; }
.work-grid { display: grid; grid-template-columns: minmax(0, 1.9fr) minmax(290px, 1fr); gap: 18px; align-items: stretch; margin-bottom: 18px; }
.pending-panel, .runtime-panel, .activity-panel, .chart-panel { padding: 22px; }
.panel-heading { margin-bottom: 18px; gap: 12px; }
.panel-heading h2 { display: flex; align-items: center; gap: 12px; }
.count { color: #2563eb; font-size: 24px; font-variant-numeric: tabular-nums; }
.urgent-alert { margin-bottom: 10px; border: 0; }
.todo-tabs :deep(.ant-tabs-nav) { margin-bottom: 12px; }
.todo-tabs :deep(.ant-tabs-content-holder) { display: none; }
.todo-tabs :deep(.ant-tabs-tab) { padding-block: 14px; }
.dashboard :deep(.ant-table-thead > tr > th) { color: #475467; font-weight: 500; background: #f7f8fb; }
.dashboard :deep(.ant-table-cell) { overflow-wrap: anywhere; }
.dashboard :deep(.ant-tag) { margin-inline-end: 0; white-space: normal; }
.object-cell { display: flex; gap: 12px; align-items: center; }
.object-icon { color: #2563eb; font-size: 23px; flex-shrink: 0; }
.object-name { font-weight: 500; color: #17223b; overflow-wrap: anywhere; }
a.object-name:hover { color: #2563eb; }
.secondary, .table-note { color: #667085; font-size: 12px; }
.object-context { margin-top: 4px; word-break: break-word; }
.table-note { margin-top: 14px; line-height: 1.7; }
.runtime-row { width: 100%; text-align: start; font: inherit; color: inherit; background: transparent; border: 0; border-top: 1px solid #eef1f5; padding: 22px 0; display: flex; align-items: center; gap: 14px; }
.runtime-icon { width: 48px; height: 48px; border-radius: 50%; background: #f3f7ff; color: #2563eb; display: inline-flex; align-items: center; justify-content: center; font-size: 25px; flex-shrink: 0; }
.runtime-copy { flex: 1; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.runtime-copy strong, .aidr-clients strong { font-size: 28px; font-weight: 600; line-height: 1.3; font-variant-numeric: tabular-nums; }
.row-arrow { font-size: 12px; color: #72809a; }
.aidr-section { padding-top: 20px; border-top: 1px solid #eef1f5; }
.aidr-heading { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.aidr-heading .ant-tag { font-size: 11px; }
.aidr-content { margin-left: 62px; }
.aidr-clients { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; font-size: 13px; }
.record-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-radius: 6px; background: #f7f8fb; padding: 10px; font-size: 12px; margin-bottom: 12px; }
.record-summary strong { font-size: 16px; }
.aidr-content > .ant-btn { color: #2563eb; border-color: #b7cdfb; height: auto; min-height: 32px; white-space: normal; }
.event-cell { display: flex; gap: 10px; align-items: center; }
.event-icon { font-size: 16px; flex-shrink: 0; }
.success { color: #16a34a; }.danger { color: #e5484d; }.neutral { color: #d99000; }
.activity-panel { margin-bottom: 26px; }
.analytics-heading { margin-bottom: 16px; }
.analytics-heading h2 { font-size: 23px; }
.analytics-heading p { font-size: 13px; }
.charts-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr); gap: 18px; }
.chart-panel { display: flex; flex-direction: column; }
.chart-panel .panel-heading { align-items: flex-start; }
.chart-metric { display: flex; flex-direction: column; gap: 2px; margin-bottom: 8px; }
.chart-metric strong { font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums; }
.chart-footer { display: flex; justify-content: flex-end; border-top: 1px solid #eef1f5; padding-top: 10px; margin-top: auto; }
.chart-empty-note { font-size: 12px; color: #667085; text-align: center; margin-bottom: 12px; }
.risk-legend { padding: 0; margin: 8px 0 24px; display: flex; justify-content: center; flex-wrap: wrap; gap: 12px 18px; list-style: none; }
.risk-legend li { display: flex; align-items: center; gap: 7px; font-size: 13px; }
.risk-legend strong { font-weight: 500; }
.legend-dot { height: 9px; width: 9px; border-radius: 50%; flex-shrink: 0; }
.risk-empty { margin-block: auto; padding-block: 60px; }
.work-grid.single-column, .charts-grid.single-column { grid-template-columns: minmax(0, 1fr); }
.refresh-warning { margin-bottom: 16px; }
.dashboard button:focus-visible, .dashboard a:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
@media (max-width: 1200px) { .asset { padding-inline: 12px; gap: 10px; flex-basis: 130px; }.asset strong { font-size: 24px; }.asset-icon { font-size: 26px; }.work-grid { grid-template-columns: minmax(0, 1.65fr) minmax(260px, 1fr); }.pending-panel, .runtime-panel, .activity-panel, .chart-panel { padding: 18px; }.aidr-content { margin-left: 0; margin-top: 12px; } }
@media (max-width: 1000px) { .work-grid, .charts-grid { grid-template-columns: minmax(0, 1fr); }.asset { flex-basis: 180px; }.asset-strip { gap: 14px 0; }.updated { flex-basis: 100%; }.heading-actions { justify-content: flex-start; }.runtime-row { padding-block: 16px; }.aidr-content { margin-left: 62px; } }
@media (max-width: 600px) { h1 { font-size: 24px; }.dashboard-heading { gap: 12px; }.asset-strip { padding: 16px 8px; }.asset { flex-basis: 45%; padding: 8px; }.asset:nth-child(even) { border-inline-end: 0; }.asset-label { font-size: 12px; }.asset strong { font-size: 23px; }.asset-icon { font-size: 24px; }.pending-panel, .runtime-panel, .activity-panel, .chart-panel { padding: 16px; }.panel-heading h2 { font-size: 17px; }.aidr-content { margin-left: 0; }.dashboard-heading p { font-size: 14px; }.chart-panel :deep(.ant-radio-button-wrapper) { padding-inline: 12px; }.risk-legend { gap: 10px; } }
</style>
