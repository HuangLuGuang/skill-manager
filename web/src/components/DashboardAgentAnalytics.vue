<template>
  <section class="agent-analytics">
    <a-tabs v-model:activeKey="tab">
      <a-tab-pane v-for="key in ['assets', 'behavior', 'risk']" :key="key" :tab="tr(key)" />
    </a-tabs>
    <div v-if="tab === 'assets'" class="chart-grid">
      <section class="chart-card"><h2>{{ tr('platformAssets') }}</h2><Chart :options="assetChart" height="270px" :navigation-label="tr('drill')" @select="openAsset" /></section>
      <section v-if="overview.reported_assets" class="chart-card"><h2>{{ tr('reportedAssets') }} <a-tooltip :title="tr('reportedScope')"><InfoCircleOutlined tabindex="0" :aria-label="tr('scope')" /></a-tooltip></h2><Chart :options="reportedChart" height="270px" :navigation-label="tr('drill')" @select="openReported" /></section>
      <section v-if="overview.assets.clients" class="chart-card"><h2>{{ tr('connectivity') }}</h2><Chart :options="clientChart" height="270px" :navigation-label="tr('drill')" @select="openClients" /></section>
      <section v-if="overview.agent_products" class="chart-card"><h2>{{ tr('products') }} <a-tooltip :title="tr('productScope')"><InfoCircleOutlined tabindex="0" :aria-label="tr('scope')" /></a-tooltip></h2><Chart v-if="productRows.length" :options="productChart" height="270px" :navigation-label="tr('drill')" @select="openProduct" /><a-empty v-else :description="tr('empty')" /></section>
    </div>
    <template v-else>
      <template v-if="can('clients:view')">
        <div class="analytics-toolbar">
          <a-select v-model:value="current.client" :aria-label="tr('client')" :options="clientOptions" show-search option-filter-prop="label" @change="scopeChanged" />
          <a-select v-model:value="current.source" :aria-label="tr('source')" :options="sourceOptions" @change="scopeChanged" />
          <a-radio-group v-model:value="current.days" button-style="solid" @change="scopeChanged"><a-radio-button :value="7">{{ t('dashboard.sevenDays') }}</a-radio-button><a-radio-button :value="30">{{ t('dashboard.thirtyDays') }}</a-radio-button></a-radio-group>
          <a-button :loading="current.loading" :disabled="current.loading" @click="refresh">{{ t('dashboard.refresh') }}</a-button>
          <a-tooltip :title="tr(tab === 'risk' ? 'riskScope' : 'behaviorScope')"><InfoCircleOutlined tabindex="0" :aria-label="tr('scope')" /></a-tooltip>
        </div>
        <a-alert v-if="current.error" type="error" show-icon :message="t(current.data ? 'dashboard.stale' : 'dashboard.loadFailed')" />
        <a-skeleton v-if="current.loading && !current.data" active />
        <template v-if="current.data">
          <a-alert v-if="current.data.state !== 'ready'" class="state-note" type="info" show-icon :message="tr(current.data.state)" />
          <div class="metric-strip">
            <component :is="metric.filters ? 'button' : 'div'" v-for="metric in metrics" :key="metric.key" class="metric" @click="metric.filters && drill(metric.filters)"><span>{{ tr(metric.key) }}</span><strong>{{ number(metric.value) }}</strong><ArrowRightOutlined v-if="metric.filters" /></component>
          </div>
          <div class="chart-grid">
            <section v-for="chart in charts" :key="chart.key" class="chart-card">
              <h2>{{ tr(chart.key) }}<a-radio-group v-if="['tools', 'commandTop'].includes(chart.key)" v-model:value="rankMode" size="small" class="rank-mode"><a-radio-button value="commands">{{ tr('commandRank') }}</a-radio-button><a-radio-button value="tools">{{ tr('toolRank') }}</a-radio-button></a-radio-group><span v-if="chart.stock" class="scope-label">{{ t('dashboard.snapshot') }}</span></h2>
              <Chart v-if="chart.rows.some(row => row.value)" :options="chart.options" height="250px" :navigation-label="tr('drill')" @select="chart.select" />
              <a-empty v-else :description="tr('empty')" class="chart-empty" />
            </section>
            <div class="existing-chart"><slot :name="tab" /></div>
          </div>
          <a-modal v-if="current.selection" :open="true" :title="tr('details')" :footer="null" width="min(1200px, calc(100vw - 32px))" centered :body-style="{ maxHeight: '72vh', overflow: 'auto' }" @cancel="closeDetails">
            <div class="detail-heading"><span class="scope-label">{{ selectionText }}</span><a-button size="small" @click="drill({})">{{ tr('clear') }}</a-button></div><p v-if="current.selection.program" class="scope-label">{{ tr('commandDetailScope') }}</p>
            <a-alert v-if="current.listError" type="error" show-icon :message="t('dashboard.loadFailed')" />
            <a-table size="small" :columns="columns" :data-source="current.items" row-key="id" :loading="current.listLoading" :scroll="{ x: 950 }" :pagination="{ current: current.page, pageSize: current.pageSize, total: current.total, showSizeChanger: true, showTotal: total => tr('count', { count: total }) }" @change="paginate">
              <template #customFilterDropdown="{ column }">
                <div class="filter-menu">
                  <a-select v-if="column.key === 'client_id'" :value="current.selection.client_id || ''" :options="clientOptions" show-search option-filter-prop="label" @change="filter('client_id', $event)" />
                  <template v-else-if="column.key === 'risk_code'">
                    <label>{{ t('aidrRisk.severityLabel') }}</label><a-select :value="current.selection.severity || ''" :options="severityOptions" @change="filter('severity', $event)" />
                    <label>{{ t('aidrRisk.type') }}</label><a-select :value="current.selection.risk_code || ''" :options="riskOptions" @change="filter('risk_code', $event)" />
                  </template>
                  <a-select v-else-if="column.key === 'disposition'" :value="current.selection.disposition || ''" :options="dispositionOptions" @change="filter('disposition', $event, true)" />
                  <a-input v-else :value="current.selection[column.key] || ''" allow-clear :placeholder="tr(column.key)" @input="textFilter(column.key, $event.target.value)" @pressEnter="flushFilter" />
                </div>
              </template>
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'time'">{{ formatDateTime(tab === 'behavior' ? new Date(record.at * 1000).toISOString() : record.detected_at) }}</template>
                <template v-else-if="column.key === 'client_id'"><router-link :to="clientPath(record.client_id)">{{ clientName(record.client_id) }}</router-link></template>
                <template v-else-if="column.key === 'agent'">{{ record.agent || t('dashboard.unknown') }}</template>
                <template v-else-if="column.key === 'commands'">{{ Object.entries(record.commands || {}).map(([name, count]) => `${name} × ${count}`).join(', ') || '—' }}</template>
                <template v-else-if="column.key === 'source'">{{ sourceLabel(record.source) }}</template>
                <template v-else-if="column.key === 'risk_code'"><a-tag :color="record.severity === 'high' ? 'red' : 'orange'">{{ t('aidrRisk.severity.' + record.severity) }}</a-tag>{{ riskLabel(record.risk_code) }}</template>
                <template v-else-if="column.key === 'disposition'">{{ dispositionLabel(record.disposition) }}</template>
                <template v-else-if="column.key === 'action'"><a-button type="link" size="small" @click="showRecord(record)">{{ t('dashboard.view') }}</a-button></template>
              </template>
            </a-table>
          </a-modal>
        </template>
      </template>
      <a-empty v-else :description="t('dashboard.noAccess')" />
      <div v-if="!can('clients:view') || !current.data" class="existing-chart"><slot :name="tab" /></div>
    </template>
    <a-modal :footer="null" centered v-model:open="clientDrawer" :title="tr(clientOnline ? 'online' : 'offline')" width="min(720px, 100vw)">
      <a-alert v-if="states.behavior.error" type="error" :message="t('dashboard.loadFailed')" />
      <a-table size="small" :loading="states.behavior.loading" :data-source="visibleClients" row-key="id" :columns="[{ key: 'name', title: tr('client') }]" :pagination="{ pageSize: 10 }"><template #bodyCell="{ record }"><router-link :to="clientPath(record.id)">{{ record.name }} · {{ record.id }}</router-link></template></a-table>
    </a-modal>
    <a-modal :footer="null" :z-index="1100" centered v-model:open="entryOpen" :title="tr('details')" width="min(820px, 100vw)" @cancel="entryGeneration++">
      <a-spin :spinning="entryLoading"><a-alert v-if="entryError" type="error" :message="t('dashboard.loadFailed')" /><AidrTimelineEntry v-if="entry" :item="entry" :client-id="entryClient" :expanded="true" /></a-spin>
    </a-modal>
    <a-modal :open="instanceOpen" :title="tr('instances') + ' · ' + selectedProduct" :footer="null" centered width="min(1100px, calc(100vw - 32px))" :body-style="{ maxHeight: '72vh', overflow: 'auto' }" @cancel="closeInstances">
      <a-alert v-if="instanceError" type="error" show-icon :message="t('dashboard.loadFailed')"><template #action><a-button size="small" @click="loadInstances">{{ t('dashboard.retry') }}</a-button></template></a-alert>
      <a-table size="small" :loading="instanceLoading" :columns="instanceColumns" :data-source="instanceItems" row-key="id" :scroll="{ x: 950 }" :pagination="{ current: instancePage, pageSize: instancePageSize, total: instanceTotal, showSizeChanger: true, showTotal: total => tr('count', { count: total }) }" @change="instancePaginate">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'client'"><router-link :to="clientPath(record.client_id)">{{ record.client_name }} · {{ record.client_id }}</router-link></template>
          <template v-else-if="column.key === 'product'">{{ productName(record.product) }}</template>
          <template v-else-if="column.key === 'last_scanned_at'">{{ formatDateTime(record.last_scanned_at) }}</template>
        </template>
      </a-table>
    </a-modal>
    <slot name="footer" :tab="tab" />
    <ClientAidrRisks v-if="riskClient" :key="riskClient" ref="riskDetail" :client-id="riskClient" detail-only @changed="refresh" />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ArrowRightOutlined, InfoCircleOutlined } from '@ant-design/icons-vue'
import Chart from './Chart.vue'
import ClientAidrRisks from './ClientAidrRisks.vue'
import AidrTimelineEntry from './AidrTimelineEntry.vue'
import { can, pageAllowed } from '../access'
import { getDashboardAgentAnalytics, getDashboardAgentInstances, getClientAidrOverviewEntry } from '../api'
import { formatDateTime } from '../utils/format'

const props = defineProps({ overview: { type: Object, required: true } })
const { t, te, locale } = useI18n(), router = useRouter()
const tr = (key, params) => t('dashboard.agentAnalytics.' + key, params || {})
const tab = ref('assets'), rankMode = ref('commands')
const states = reactive(Object.fromEntries(['behavior', 'risk'].map(kind => [kind, { days: 7, source: kind === 'behavior' ? 'hooks' : '', client: '', data: null, loading: false, error: false, generation: 0, selection: null, items: [], total: 0, page: 1, pageSize: 10, sortBy: 'time', sortOrder: 'descend', listLoading: false, listError: false, listGeneration: 0 }])))
const current = computed(() => states[tab.value])
const number = value => new Intl.NumberFormat(locale.value).format(value || 0)
const sourceLabel = value => t('aidrRisk.sources.' + value)
const riskLabel = value => te('aidrRisk.codes.' + value) ? t('aidrRisk.codes.' + value) : value
const dispositionLabel = value => t('aidrRisk.disposition.states.' + value)
const clients = computed(() => current.value?.data?.clients || states.behavior.data?.clients || states.risk.data?.clients || [])
const clientName = id => clients.value.find(row => row.id === id)?.name || id
const clientPath = id => ({ path: '/clients', query: { client: id, section: 'overview' } })
const options = (values, label) => [{ value: '', label: t('dashboard.all') }, ...values.map(value => ({ value, label: label(value) }))]
const clientOptions = computed(() => [{ value: '', label: tr('allClients') }, ...clients.value.map(row => ({ value: row.id, label: `${row.name} · ${row.id}` }))])
const sourceOptions = computed(() => tab.value === 'behavior' ? ['hooks', 'logs'].map(value => ({ value, label: sourceLabel(value) })) : options(['hooks', 'logs', 'system'], sourceLabel))
const severityOptions = computed(() => options(['high', 'medium'], value => t('aidrRisk.severity.' + value)))
const riskOptions = computed(() => options(current.value?.data?.risk_codes || [], riskLabel))
const dispositionOptions = computed(() => options(['open', 'accepted', 'false_positive', 'resolved'], dispositionLabel))
const palette = ['#4679df', '#80a8f2', '#e6a23c', '#df6667', '#7a85af']
const pie = rows => ({ color: palette, tooltip: { trigger: 'item', confine: true }, legend: { bottom: 0, type: 'scroll' }, series: [{ type: 'pie', radius: ['48%', '70%'], center: ['50%', '43%'], label: { show: false }, data: rows.map(row => ({ name: row.name, value: row.value, ...(row.color ? { itemStyle: { color: row.color } } : {}) })) }] })
const bars = rows => ({ color: palette, tooltip: { trigger: 'axis', confine: true }, grid: { left: 12, right: 24, top: 20, bottom: 12, containLabel: true }, xAxis: { type: 'value', minInterval: 1 }, yAxis: { type: 'category', inverse: true, data: rows.map(row => row.name), axisLabel: { width: 180, overflow: 'truncate' } }, series: [{ type: 'bar', barMaxWidth: 20, itemStyle: { borderRadius: [0, 4, 4, 0] }, data: rows.map(row => row.value) }] })
const line = rows => ({ color: palette, tooltip: { trigger: 'axis', confine: true }, grid: { left: 12, right: 24, top: 20, bottom: 12, containLabel: true }, xAxis: { type: 'category', data: rows.map(row => row.date.slice(5)), boundaryGap: false }, yAxis: { type: 'value', minInterval: 1 }, series: [{ type: 'line', showSymbol: true, symbolSize: 7, areaStyle: { opacity: 0.07 }, data: rows.map(row => row.value) }] })
const assetPaths = { agents: '/agents', skills: '/skills', mcp: '/mcp-governance/servers', models: '/model-gateway/providers', clients: '/clients' }
const assets = computed(() => Object.entries(props.overview.assets).map(([key, value]) => ({ key, name: key === 'clients' ? tr('client') : t('dashboard.' + key), value: key === 'clients' ? value.total : value })))
const assetChart = computed(() => bars(assets.value))
const reportedItems = computed(() => Object.entries(props.overview.reported_assets || {}).map(([key, value]) => ({ key, name: tr('reported.' + key), value })))
const reportedChart = computed(() => bars(reportedItems.value))
const productName = key => props.overview.agent_products?.find(row => row.key === key)?.name || key || tr('unknownProduct')
const productRows = computed(() => {
  const rows = (props.overview.agent_products || []).map(row => ({ ...row, name: productName(row.key), products: [row.key] }))
  return rows.length > 8 ? [...rows.slice(0, 8), { name: tr('otherProducts'), value: rows.slice(8).reduce((sum, row) => sum + row.value, 0), products: rows.slice(8).map(row => row.key) }] : rows
})
const productChart = computed(() => bars(productRows.value))
const instanceOpen = ref(false), instanceLoading = ref(false), instanceError = ref(false), instanceItems = ref([]), instanceTotal = ref(0), instancePage = ref(1), instancePageSize = ref(10), selectedProduct = ref('')
let instanceProducts = [], instanceGeneration = 0
const instanceColumns = computed(() => [
  { key: 'client', title: tr('client'), width: 210 },
  ...['product', 'local_agent_id', 'agent_version', 'install_path', 'last_scanned_at'].map(key => ({ key, dataIndex: key, title: tr(key), width: key === 'install_path' ? 260 : 170 })),
])
function openProduct(event) { const row = productRows.value[event.dataIndex]; if (!row) return; instanceProducts = row.products; selectedProduct.value = row.name; instancePage.value = 1; instanceItems.value = []; instanceTotal.value = 0; instanceOpen.value = true; loadInstances() }
function closeInstances() { instanceOpen.value = false; instanceGeneration++ }
function instancePaginate(pagination) { instancePage.value = pagination.pageSize === instancePageSize.value ? pagination.current : 1; instancePageSize.value = pagination.pageSize; loadInstances() }
async function loadInstances() {
  const epoch = ++instanceGeneration; instanceLoading.value = true; instanceError.value = false
  try { const data = await getDashboardAgentInstances({ products: instanceProducts, page: instancePage.value, page_size: instancePageSize.value }); if (!disposed && epoch === instanceGeneration) { instanceItems.value = data.items; instanceTotal.value = data.total; instancePage.value = data.page } }
  catch { if (!disposed && epoch === instanceGeneration) { instanceError.value = true; instanceItems.value = []; instanceTotal.value = 0 } }
  finally { if (!disposed && epoch === instanceGeneration) instanceLoading.value = false }
}
function openReported() { if (pageAllowed('/agents')) router.push({ path: '/agents', query: { origin: 'client_discovery' } }); else if (pageAllowed('/clients')) router.push('/clients') }
const clientChart = computed(() => pie([{ name: tr('online'), value: props.overview.assets.clients?.online || 0 }, { name: tr('offline'), value: (props.overview.assets.clients?.total || 0) - (props.overview.assets.clients?.online || 0) }]))
function openAsset(event) { const path = assetPaths[assets.value[event.dataIndex]?.key]; if (path && pageAllowed(path)) router.push(path === '/agents' ? { path, query: { origin: 'platform' } } : path) }
const clientDrawer = ref(false), clientOnline = ref(true)
const visibleClients = computed(() => (states.behavior.data?.clients || []).filter(row => row.online === clientOnline.value))
async function openClients(event) { clientOnline.value = event.dataIndex === 0; clientDrawer.value = true; await load('behavior') }
const metrics = computed(() => { const d = current.value?.data; if (!d) return []; return tab.value === 'behavior' ? [
  { key: 'calls', value: d.total, filters: {} }, { key: 'activeAgents', value: d.active_agents, filters: null }, { key: 'failures', value: d.failures, filters: { category: 'failures' } },
] : [{ key: 'open', value: d.total, filters: {} }, { key: 'high', value: d.high, filters: { severity: 'high' } }, { key: 'new', value: d.new, filters: { scope: 'period' } }] })
const charts = computed(() => {
  const d = current.value?.data; if (!d) return []
  const chart = (key, rows, type, select, stock = false) => ({ key, rows, options: type(rows), select: event => { const row = rows[event.dataIndex]; if (row) select(row) }, stock })
  const trend = chart(tab.value === 'behavior' ? 'activityTrend' : 'riskTrend', d.trend, line, row => { const since = Date.parse(row.date + 'T00:00:00Z') / 1000; drill({ scope: 'period', since: Math.max(since, d.since), until: Math.min(since + 86400, d.until) }) })
  if (tab.value === 'behavior') return [trend, chart('composition', d.categories.map(row => ({ ...row, name: tr(row.key) })), pie, row => drill({ category: row.key })), rankMode.value === 'commands' ? chart('commandTop', d.commands.map(row => ({ ...row, name: row.key })), bars, row => drill({ program: row.key })) : chart('tools', d.tools.map(row => ({ ...row, name: row.key || t('dashboard.unknown') })), bars, row => drill({ tool: row.key }))]
  return [trend,
    chart('severity', d.severities.map(row => ({ ...row, name: t('aidrRisk.severity.' + row.key), color: row.key === 'high' ? '#df6667' : '#e6a23c' })), pie, row => drill({ severity: row.key }), true),
    chart('riskTypes', d.types.map(row => ({ ...row, name: riskLabel(row.key) })), bars, row => drill({ risk_code: row.key }), true),
    chart('riskAgents', d.agents.map(row => ({ ...row, name: `${clientName(row.client_id)} / ${row.agent || t('dashboard.unknown')}` })), bars, row => drill({ client_id: row.client_id, agent: row.agent, unknown_agent: !row.agent }), true),
    chart('dispositions', d.dispositions.map(row => ({ ...row, name: dispositionLabel(row.key), color: ({ open: '#e6a23c', accepted: '#4679df', false_positive: '#94a3b8', resolved: '#52a58c' })[row.key] })), pie, row => drill({ scope: 'period', disposition: row.key })),
  ]
})
let timer, disposed = false
async function load(kind) {
  if (!can('clients:view')) return
  const s = states[kind], epoch = ++s.generation; s.loading = true; s.error = false
  try { const data = await getDashboardAgentAnalytics({ kind, days: s.days, source: s.source, client_id: s.client }); if (!disposed && epoch === s.generation) s.data = data }
  catch { if (!disposed && epoch === s.generation) s.error = true }
  finally { if (!disposed && epoch === s.generation) s.loading = false }
}
async function refresh() { if (timer && current.value) current.value.page = 1; clearTimeout(timer); timer = null; const kind = tab.value; if (!states[kind]) return; await load(kind); if (states[kind].selection) await loadList(kind) }
function scopeChanged() { clearTimeout(timer); timer = null; const s = current.value; s.listGeneration++; s.selection = null; s.data = null; s.items = []; s.page = 1; load(tab.value) }
function drill(filters) { clearTimeout(timer); timer = null; const s = current.value; s.selection = { scope: 'current', since: s.data.since, until: s.data.until, ...filters }; s.page = 1; loadList(tab.value) }
function closeDetails() { clearTimeout(timer); timer = null; current.value.listGeneration++; current.value.selection = null; current.value.listLoading = false }
async function loadList(kind) {
  const s = states[kind], epoch = ++s.listGeneration; s.listLoading = true; s.listError = false
  try { const data = await getDashboardAgentAnalytics({ kind, source: s.source, days: s.days, ...s.selection, client_id: s.selection.client_id || s.client, details: true, page: s.page, page_size: s.pageSize, sort_by: s.sortBy, sort_order: s.sortOrder === 'ascend' ? 'asc' : 'desc' }); if (!disposed && epoch === s.listGeneration) { s.items = data.items; s.total = data.total; s.page = data.page } }
  catch { if (!disposed && epoch === s.listGeneration) { s.listError = true; s.items = []; s.total = 0 } }
  finally { if (!disposed && epoch === s.listGeneration) s.listLoading = false }
}
function filter(key, value, period = false) { clearTimeout(timer); timer = null; const s = current.value; s.selection[key] = value; if (key === 'agent') s.selection.unknown_agent = false; if (period) s.selection.scope = 'period'; s.page = 1; loadList(tab.value) }
function textFilter(key, value) { if (!value) { filter(key, ''); return } clearTimeout(timer); const kind = tab.value; states[kind].selection[key] = value; states[kind].selection.unknown_agent = false; states[kind].listGeneration++; timer = setTimeout(() => { timer = null; states[kind].page = 1; loadList(kind) }, 300) }
function flushFilter() { clearTimeout(timer); timer = null; current.value.page = 1; loadList(tab.value) }
function paginate(pagination, _filters, sorter, extra) { const pending = !!timer; clearTimeout(timer); timer = null; if (extra.action === 'sort') { current.value.sortBy = sorter.columnKey === 'risk_code' ? 'severity' : sorter.columnKey; current.value.sortOrder = sorter.order } current.value.page = pending || extra.action === 'sort' ? 1 : pagination.current; current.value.pageSize = pagination.pageSize; loadList(tab.value) }
const columns = computed(() => (tab.value === 'behavior' ? ['time', 'client_id', 'agent', 'source', 'tool', 'commands', 'action'] : ['time', 'client_id', 'agent', 'source', 'risk_code', 'disposition', 'action']).map(key => ({ key, dataIndex: key, title: tr(key === 'commands' ? 'commandPrograms' : key), width: key === 'time' ? 180 : key === 'risk_code' ? 240 : 140, ...(['time', 'client_id', 'agent', 'tool', 'risk_code'].includes(key) ? { sorter: true, sortDirections: ['ascend', 'descend', 'ascend'], sortOrder: current.value?.sortBy === (key === 'risk_code' ? 'severity' : key) ? current.value.sortOrder : null } : {}), customFilterDropdown: ['client_id', 'agent', 'tool', 'risk_code', 'disposition'].includes(key) && !(key === 'client_id' && current.value.client), filtered: !!current.value?.selection?.[key] || (key === 'risk_code' && !!current.value?.selection?.severity) || (key === 'agent' && !!current.value?.selection?.unknown_agent) })))
const selectionText = computed(() => { const s = current.value?.selection; if (!s) return ''; return [tab.value === 'risk' && s.scope === 'current' ? tr('open') : `${new Date(s.since * 1000).toISOString().slice(0, 10)} – ${new Date((s.until - 1) * 1000).toISOString().slice(0, 10)} UTC`, s.program, s.category && tr(s.category), s.severity && t('aidrRisk.severity.' + s.severity), s.risk_code && riskLabel(s.risk_code), s.disposition && dispositionLabel(s.disposition), s.unknown_agent ? t('dashboard.unknown') : s.agent, s.tool, (s.client_id || current.value.client) && clientName(s.client_id || current.value.client)].filter(Boolean).join(' · ') })
const riskClient = ref(''), riskDetail = ref(null), entryOpen = ref(false), entry = ref(null), entryClient = ref(''), entryLoading = ref(false), entryError = ref(false)
let entryGeneration = 0
async function showRecord(row) {
  if (tab.value === 'risk') { riskClient.value = row.client_id; await nextTick(); riskDetail.value?.showDetail(row.id); return }
  const epoch = ++entryGeneration; entryClient.value = row.client_id; entryOpen.value = true; entryLoading.value = true; entryError.value = false; entry.value = null
  try { const data = await getClientAidrOverviewEntry(row.client_id, { source: row.source, record_id: row.record_id }); if (!disposed && epoch === entryGeneration) { entry.value = data; entryError.value = !data } }
  catch { if (!disposed && epoch === entryGeneration) entryError.value = true }
  finally { if (!disposed && epoch === entryGeneration) entryLoading.value = false }
}
watch(tab, (kind, previous) => { if (timer && states[previous]) { clearTimeout(timer); timer = null; states[previous].page = 1; loadList(previous) } if (states[kind] && !states[kind].data) load(kind) })
watch(() => props.overview.as_of, () => { for (const kind of ['behavior', 'risk']) if (states[kind].data) { load(kind); if (states[kind].selection) loadList(kind) } })
onBeforeUnmount(() => { disposed = true; clearTimeout(timer); entryGeneration++ })
</script>

<style scoped>
.agent-analytics { margin: 20px 0; min-width: 0; }
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.chart-card,.detail-card { padding: 20px; background: #fff; border: 1px solid #e8edf3; border-radius: 10px; min-width: 0; }
h2 { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 15px; font-weight: 600; margin: 0 0 14px; }
.rank-mode { margin-left: auto; }
.scope-label { color: #788397; font-size: 12px; font-weight: 400; margin-left: 10px; }
.analytics-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.analytics-toolbar .ant-select { min-width: 160px; max-width: 300px; }
.metric-strip { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); background: #fff; border: 1px solid #e8edf3; border-radius: 10px; margin: 16px 0; }
.metric-strip .metric { background: none; border: 0; padding: 18px 22px; text-align: left; color: #667085; display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.metric-strip .metric + .metric { border-left: 1px solid #edf0f5; }
.metric-strip strong { grid-row: 2; font-size: 28px; color: #1f2937; font-variant-numeric: tabular-nums; }
.metric-strip .anticon { grid-column: 2; grid-row: 2; align-self: center; color: #4679df; }
.metric-strip button { cursor: pointer; }
.metric-strip button:hover { background: #f7faff; }
.chart-empty { min-height: 250px; display: flex; flex-direction: column; justify-content: center; }
.detail-card { margin-top: 16px; scroll-margin-top: 20px; }.existing-chart { min-width: 0; }.existing-chart :deep(.chart-panel) { height: 100%; box-sizing: border-box; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.detail-heading h2 { margin: 0; }.filter-menu { padding: 12px; display: grid; gap: 10px; min-width: 240px; max-width: 360px; }.filter-menu .ant-select { width: 100%; }
.state-note { margin-bottom: 12px; }
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; }.metric-strip .metric { padding: 12px; }.metric-strip strong { font-size: 24px; } }
@media (max-width: 520px) { .metric-strip { grid-template-columns: 1fr; }.metric-strip .metric + .metric { border-left: 0; border-top: 1px solid #edf0f5; }.analytics-toolbar > * { max-width: 100%; }.chart-card,.detail-card { padding: 12px; } }
</style>
