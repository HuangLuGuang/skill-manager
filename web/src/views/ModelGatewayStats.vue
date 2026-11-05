<template>
  <a-card class="page-card gateway-stats">
    <template #title>
      <a-page-header :title="t('gatewayStats.title')" :sub-title="t('gatewayStats.subtitle')">
      </a-page-header>
    </template>
    <div class="stats-toolbar">
      <a-space wrap>
        <a-range-picker v-model:value="dateRange" class="period-select" size="small" :locale="locale === 'zh-CN' ? zhDateLocale : enDateLocale" :allow-clear="false" :presets="periodPresets" :disabled-date="disabledDate" :placeholder="[t('gatewayStats.startDate'), t('gatewayStats.endDate')]" :aria-label="t('gatewayStats.period')" popup-class-name="gateway-stats-calendar" @change="changePeriod" />
        <a-select v-model:value="model" class="model-select" size="small" show-search allow-clear :placeholder="t('gatewayStats.allModels')" :aria-label="t('gatewayStats.model')" :options="modelOptions" @change="filterChanged" />
      </a-space>
      <a-button size="small" :loading="refreshing" :disabled="loading" @click="load(true)"><ReloadOutlined />{{ t('gatewayStats.refresh') }}</a-button>
    </div>
    <div v-if="hasFilters" class="active-filters">
      <a-tag v-if="selectedDay" closable @close.prevent="setDay()">{{ selectedDay }}</a-tag>
      <a-tag v-if="status" closable @close.prevent="clearStatus">{{ statusText(status) }}</a-tag>
      <a-tag v-if="selectedUser !== undefined" closable @close.prevent="clearUser">{{ selectedUsername || t('gatewayStats.unassigned') }}</a-tag>
      <a-button type="link" size="small" @click="clearFilters">{{ t('gatewayStats.clear') }}</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="errorText(error)" class="stats-error">
      <template #action><a-button size="small" @click="load()">{{ t('gatewayStats.retry') }}</a-button></template>
    </a-alert>
    <a-spin :spinning="loading">
      <a-skeleton v-if="!data && !error" active />
      <div v-if="data && !error">
        <div class="summary-grid">
          <button class="summary-card" @click="showRequests">
            <span class="summary-label">{{ t('gatewayStats.totalRequests') }}</span><strong>{{ number(overview.total_requests) }}</strong>
            <span class="summary-foot">{{ t('gatewayStats.errorRequests') }} <span :class="{ danger: overview.error_requests }">{{ number(overview.error_requests) }}</span> · {{ t('gatewayStats.errorRate') }} {{ percent(overview.error_rate) }}</span>
            <span v-if="overview.blocked_requests" class="summary-foot">{{ t('gatewayStats.blockedRequests') }} {{ number(overview.blocked_requests) }}</span>
          </button>
          <button class="summary-card" @click="metric = 'tokens'">
            <span class="summary-label">{{ t('gatewayStats.totalTokens') }}</span><strong>{{ overview.total_tokens == null ? '—' : compact(overview.total_tokens) }}</strong>
            <span class="summary-foot">{{ t('gatewayStats.input') }} {{ compact(overview.prompt_tokens) }} / {{ t('gatewayStats.output') }} {{ compact(overview.completion_tokens) }}</span>
            <span v-if="overview.usage_requests < overview.total_requests" class="summary-foot">{{ t('gatewayStats.usageCoverage', { known: overview.usage_requests, total: overview.total_requests }) }}</span>
          </button>
          <button class="summary-card" @click="metric = 'latency'">
            <span class="summary-label">{{ t('gatewayStats.avgLatency') }}</span><strong>{{ overview.avg_request_ms == null ? '—' : duration(overview.avg_request_ms) }}</strong>
            <span class="summary-foot">P95 {{ duration(overview.p95_request_ms) }}</span>
          </button>
          <button class="summary-card" @click="metric = 'compression'">
            <span class="summary-label">{{ t('gatewayStats.saved') }}</span><strong>{{ compact(overview.tokens_saved) }}</strong>
            <span class="summary-foot">{{ t('gatewayStats.savingsRate') }} {{ percent(overview.compression_rate) }}</span>
          </button>
        </div>
        <div class="chart-grid">
          <section class="stats-panel">
            <div class="panel-heading"><h2>{{ t('gatewayStats.trend') }}</h2><span class="muted">{{ data.start_date }} — {{ data.end_date }}</span></div>
            <a-tabs v-model:active-key="metric" size="small"><a-tab-pane v-for="key in ['requests', 'tokens', 'latency', 'compression']" :key="key" :tab="t('gatewayStats.' + key)" /></a-tabs>
            <Chart :options="trendOptions" height="260px" :navigation-label="t('gatewayStats.chartNavigation')" @select="selectChartDay" />
            <div class="chart-footer">
              <span class="muted">{{ t('gatewayStats.' + (metric === 'latency' ? 'latencyHint' : metric === 'compression' ? 'compressionHint' : 'chartHint')) }}</span>
            </div>
          </section>
          <section class="stats-panel distribution">
            <h2>{{ t('gatewayStats.distribution') }}</h2>
            <a-empty v-if="!tokenModels.length" :description="t('gatewayStats.' + (overview.usage_requests ? 'zeroTokenUsage' : overview.total_requests ? 'noTokenUsage' : 'empty'))" :image="Empty.PRESENTED_IMAGE_SIMPLE" />
            <div v-for="item in tokenModels" :key="item.model" class="model-row">
              <div class="model-label"><a-button type="link" @click="selectModel(item.model)">{{ item.model }}</a-button><span>{{ compact(item.total_tokens) }}</span></div>
              <a-progress :percent="modelShare(item) * 100" :show-info="false" size="small" />
            </div>
            <div v-if="tokenModels.length" class="distribution-note"><span class="muted">{{ t('gatewayStats.topModel') }}</span><br /><a-button type="link" @click="selectModel(tokenModels[0].model)">{{ tokenModels[0].model }}</a-button> · {{ percent(modelShare(tokenModels[0])) }} {{ t('gatewayStats.share') }}</div>
            <div class="distribution-note"><div>{{ t('gatewayStats.coverage') }} <b>{{ percent(overview.compression_coverage) }}</b></div><span class="muted">{{ t('gatewayStats.compressed') }} {{ number(overview.compression_requests) }} / {{ number(overview.success_requests) }}</span></div>
          </section>
        </div>
        <section class="stats-panel">
          <h2>{{ t('gatewayStats.details') }}</h2>
          <a-tabs :active-key="dimension" size="small" @change="changeDimension"><a-tab-pane v-for="key in ['model', 'user', 'requests']" :key="key" :tab="t('gatewayStats.' + ({ model: 'byModel', user: 'byUser', requests: 'records' }[key]))" /></a-tabs>
          <a-table :columns="columns" :data-source="loadedDimension === dimension ? data.table.items : []" :row-key="rowKey" :pagination="pagination" :locale="{ emptyText: t('gatewayStats.empty') }" :scroll="{ x: dimension === 'user' ? 1250 : 800 }" size="small" @change="tableChanged">
            <template #customFilterDropdown="{ selectedKeys, setSelectedKeys, confirm }">
              <a-menu :selected-keys="selectedKeys.length ? selectedKeys : ['all']" @click="({ key }) => applyStatusFilter(key, setSelectedKeys, confirm)">
                <a-menu-item key="all">{{ t('gatewayStats.allStatus') }}</a-menu-item>
                <a-menu-item v-for="value in ['success', 'error', 'blocked']" :key="value">{{ statusText(value) }}</a-menu-item>
              </a-menu>
            </template>
            <template #bodyCell="{ column, record, text }">
              <template v-if="column.key === 'name'">{{ dimension === 'model' ? record.model : userName(record) }}</template>
              <template v-else-if="column.key === 'created_at'">{{ formatBeijingDateTime(text) }}</template>
              <template v-else-if="column.key === 'status'"><a-badge :status="statusBadge(text)" :text="statusText(text)" /></template>
              <template v-else-if="column.key === 'avg_request_ms'">{{ duration(text) }}</template>
              <template v-else-if="column.key === 'compression_rate'">{{ percent(text) }}</template>
              <template v-else-if="['prompt_tokens', 'completion_tokens', 'total_tokens', 'tokens_saved'].includes(column.key)">{{ compact(text) }}</template>
              <template v-else-if="column.key === 'action'"><a-button type="link" size="small" @click="dimension === 'requests' ? openRequest(record.request_id) : drillDown(record)">{{ t('gatewayStats.' + (dimension === 'requests' ? 'requestDetail' : 'viewRequests')) }}</a-button></template>
              <template v-else><span :class="{ danger: column.key === 'error_requests' && text }">{{ typeof text === 'number' ? number(text) : text }}</span></template>
            </template>
          </a-table>
        </section>
        <div class="updated muted">{{ t('gatewayStats.updated') }} {{ formatBeijingDateTime(data.generated_at) }}</div>
      </div>
    </a-spin>
    <a-drawer v-model:open="detailOpen" :title="t('gatewayStats.requestDetail')" width="min(600px, 100vw)" @close="closeDetail">
      <a-spin :spinning="detailLoading">
        <a-alert v-if="detailError" type="error" show-icon :message="errorText(detailError)"><template #action><a-button size="small" @click="openRequest(requestId)">{{ t('gatewayStats.retry') }}</a-button></template></a-alert>
        <template v-if="detail && !detailError">
          <a-descriptions :column="{ xs: 1, sm: 2 }" size="small" layout="vertical">
            <a-descriptions-item :label="t('gatewayStats.requestId')" :span="2">{{ detail.request_id }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.time')">{{ formatBeijingDateTime(detail.created_at) }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.model')">{{ detail.model }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.user')">{{ userName(detail) }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.status')"><a-badge :status="statusBadge(detail.status)" :text="statusText(detail.status)" /></a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.input')">{{ number(detail.prompt_tokens) }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.output')">{{ number(detail.completion_tokens) }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.latency')">{{ duration(detail.request_duration_ms) }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.upstream')">{{ duration(detail.upstream_duration_ms) }}</a-descriptions-item>
            <a-descriptions-item :label="t('gatewayStats.platform')">{{ duration(detail.platform_duration_ms) }}</a-descriptions-item>
          </a-descriptions>
          <h3>{{ t('gatewayStats.compression') }}</h3>
          <template v-if="detail.compression_recorded"><p>{{ t('gatewayStats.before') }} {{ number(detail.pre_compression_tokens) }} → {{ t('gatewayStats.after') }} {{ number(detail.post_compression_tokens) }}</p><p>{{ t('gatewayStats.saved') }} {{ number(detail.tokens_saved) }} · {{ percent(detail.tokens_saved / detail.pre_compression_tokens) }}</p><p class="muted">{{ t('gatewayStats.compressionHint') }}</p></template>
          <p v-else class="muted">{{ t('gatewayStats.unknownCompression') }}</p>
          <template v-if="detail.error"><h3>{{ t('gatewayStats.originalError') }}</h3><pre class="request-error">{{ detail.error }}</pre></template>
          <p v-if="!detail.usage_recorded" class="muted">{{ t('gatewayStats.failureNoUsage') }}</p>
        </template>
      </a-spin>
    </a-drawer>
  </a-card>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import zhDateLocale from 'ant-design-vue/es/date-picker/locale/zh_CN'
import enDateLocale from 'ant-design-vue/es/date-picker/locale/en_US'
import { Empty } from 'ant-design-vue'
import { localizeApiError } from '../i18n/errors'
import { ReloadOutlined } from '@ant-design/icons-vue'
import Chart from '../components/Chart.vue'
import { getLlmStatsDashboard, getLlmStatsRequest } from '../api'
import { formatBeijingDateTime, formatCompactNumber } from '../utils/format'

const route = useRoute()
const { t, locale } = useI18n()
const beijingToday = () => dayjs().tz('Asia/Shanghai').startOf('day')
const dateRange = ref([beijingToday().subtract(6, 'day'), beijingToday()])
const periodPresets = computed(() => [7, 14, 30, 90].map(count => ({ label: t('gatewayStats.days', { count }), value: [beijingToday().subtract(count - 1, 'day'), beijingToday()] })))
const disabledDate = value => value.format('YYYY-MM-DD') < beijingToday().subtract(364, 'day').format('YYYY-MM-DD') || value.format('YYYY-MM-DD') > beijingToday().format('YYYY-MM-DD')
const model = ref(), status = ref(), selectedDay = ref(), selectedUser = ref(), selectedUsername = ref('')
const metric = ref('requests'), dimension = ref(route.query.dimension === 'user' ? 'user' : 'model'), page = ref(1), pageSize = ref(10), sort = ref('total_tokens'), descending = ref(true)
const loadedDimension = ref('model')
const data = ref(null), loading = ref(false), refreshing = ref(false), error = ref('')
const detailOpen = ref(false), detailLoading = ref(false), detailError = ref(''), detail = ref(null), requestId = ref('')
let generation = 0, detailGeneration = 0
const errorText = code => {
  if (code.startsWith('gatewayStats.')) return t(code)
  const message = localizeApiError({ code }, locale.value)
  return message === code ? t('gatewayStats.loadFailed') : message
}
const number = value => value == null ? t('gatewayStats.noUsage') : new Intl.NumberFormat(locale.value).format(value)
const compact = value => value == null ? t('gatewayStats.noUsage') : formatCompactNumber(value)
const percent = value => value == null ? '—' : new Intl.NumberFormat(locale.value, { style: 'percent', maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(value)
const duration = value => value == null ? t('gatewayStats.noUsage') : (value / 1000).toLocaleString(locale.value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' s'
const statusText = value => ['success', 'error', 'blocked'].includes(value) ? t('gatewayStats.' + value) : value
const statusBadge = value => ({ success: 'success', error: 'error', blocked: 'warning' }[value] || 'default')
const userName = record => record.username || (record.user_id ? 'user-' + record.user_id : t('gatewayStats.unassigned'))
const overview = computed(() => data.value?.overview || {})
const modelOptions = computed(() => [...new Set([...(data.value?.model_options || []), ...(model.value ? [model.value] : [])])].map(value => ({ label: value, value })))
const tokenModels = computed(() => (data.value?.models || []).filter(item => item.total_tokens > 0))
const modelShare = item => overview.value.total_tokens ? item.total_tokens / overview.value.total_tokens : 0
const hasFilters = computed(() => model.value || status.value || selectedDay.value || selectedUser.value !== undefined)

async function load(manual = false) {
  const current = ++generation
  loading.value = true
  refreshing.value = manual
  error.value = ''
  try {
    const result = await getLlmStatsDashboard({ start_date: dateRange.value[0].format('YYYY-MM-DD'), end_date: dateRange.value[1].format('YYYY-MM-DD'), model: model.value, status: status.value, day: selectedDay.value, user_id: selectedUser.value, dimension: dimension.value, page: page.value, page_size: pageSize.value, sort: sort.value, descending: descending.value })
    if (current !== generation) return
    data.value = result
    loadedDimension.value = dimension.value
    const lastPage = Math.max(1, Math.ceil(result.table.total / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; return load(manual) }
  } catch (e) {
    if (current === generation) error.value = e?.apiErrorCode || 'gatewayStats.loadFailed'
  } finally {
    if (current === generation) { loading.value = false; refreshing.value = false }
  }
}
function filterChanged() { page.value = 1; load() }
function changePeriod(value) { if (!value?.[0] || !value?.[1]) return; selectedDay.value = undefined; filterChanged() }
function setDay(value) { selectedDay.value = value || undefined; filterChanged() }
function selectChartDay({ dataIndex }) { const day = data.value?.series[dataIndex]?.date; if (day) setDay(selectedDay.value === day ? undefined : day) }
function selectModel(value) { model.value = model.value === value ? undefined : value; filterChanged() }
function clearStatus() { status.value = undefined; filterChanged() }
function clearUser() { selectedUser.value = undefined; selectedUsername.value = ''; filterChanged() }
function clearFilters() { model.value = undefined; status.value = undefined; selectedDay.value = undefined; selectedUser.value = undefined; selectedUsername.value = ''; filterChanged() }
function changeDimension(value) { dimension.value = value; sort.value = value === 'requests' ? 'created_at' : 'total_tokens'; descending.value = true; filterChanged() }
watch(() => route.query.dimension, value => { if (value === 'user') changeDimension('user') })
function showRequests() { metric.value = 'requests'; changeDimension('requests') }
function drillDown(record) {
  if (dimension.value === 'model') model.value = record.model
  else { selectedUser.value = record.user_id; selectedUsername.value = userName(record) }
  changeDimension('requests')
}
function tableChanged(pagination, filters, sorter, extra) {
  pageSize.value = pagination.pageSize
  page.value = extra.action === 'paginate' ? pagination.current : 1
  if (extra.action === 'filter') status.value = filters.status?.[0] || undefined
  if (extra.action === 'sort' && sorter.columnKey) { sort.value = sorter.columnKey; descending.value = sorter.order !== 'ascend' }
  load()
}
function applyStatusFilter(value, setSelectedKeys, confirm) {
  setSelectedKeys(value === 'all' ? [] : [value])
  confirm({ closeDropdown: true })
}
const rowKey = row => dimension.value === 'requests' ? row.request_id : dimension.value === 'model' ? row.model : row.user_id
const pagination = computed(() => ({ current: page.value, pageSize: pageSize.value, total: data.value?.table.total || 0, showSizeChanger: true, pageSizeOptions: ['10', '20', '50', '100'], showTotal: total => t('gatewayStats.total', { total }) }))
const sortable = (key, title, width = 110) => ({ key, dataIndex: key, title, width, align: 'right', sorter: true, sortDirections: ['ascend', 'descend', 'ascend'], sortOrder: sort.value === key ? descending.value ? 'descend' : 'ascend' : null })
const columns = computed(() => dimension.value === 'requests' ? [
  { ...sortable('created_at', t('gatewayStats.time'), 175), align: 'left' },
  { key: 'model', dataIndex: 'model', title: t('gatewayStats.model'), width: 160 },
  { key: 'status', dataIndex: 'status', title: t('gatewayStats.status'), width: 110, customFilterDropdown: true, filters: ['success', 'error', 'blocked'].map(value => ({ text: statusText(value), value })), filterMultiple: false, filteredValue: status.value ? [status.value] : [] },
  sortable('total_tokens', 'Token'), { ...sortable('avg_request_ms', t('gatewayStats.latency')), dataIndex: 'request_duration_ms' },
  { key: 'action', width: 130 },
] : [
  { key: 'name', title: t('gatewayStats.' + (dimension.value === 'model' ? 'model' : 'user')), width: 170 },
  sortable('total_requests', t('gatewayStats.count'), 90), sortable('error_requests', t('gatewayStats.errorRequests'), 80),
  ...(dimension.value === 'user' ? [sortable('prompt_tokens', t('gatewayStats.inputTokens'), 125), sortable('completion_tokens', t('gatewayStats.outputTokens'), 125)] : []),
  sortable('total_tokens', 'Token'), sortable('avg_request_ms', t('gatewayStats.avgLatency')),
  sortable('tokens_saved', t('gatewayStats.saved'), 135),
  ...(dimension.value === 'user' ? [sortable('compression_rate', t('gatewayStats.savingsRate'), 135)] : []),
  { key: 'action', width: 130 },
])
const trendOptions = computed(() => {
  const series = data.value?.series || []
  const fields = {
    requests: [['success_requests', 'success', '#1677ff'], ['error_requests', 'error', '#cf333e'], ['blocked_requests', 'blocked', '#d48806']],
    tokens: [['prompt_tokens', 'input', '#1677ff'], ['completion_tokens', 'output', '#7953bf']],
    latency: [['avg_request_ms', 'avgLatency', '#1677ff'], ['p95_request_ms', 'p95', '#7953bf']],
    compression: [['pre_compression_tokens', 'before', '#7953bf'], ['post_compression_tokens', 'after', '#1677ff']],
  }[metric.value]
  return {
    tooltip: { trigger: 'axis', renderMode: 'richText', valueFormatter: value => value == null ? t('gatewayStats.noUsage') : metric.value === 'latency' ? duration(value * 1000) : number(value) },
    legend: { top: 0, type: 'scroll', textStyle: { color: '#687080' } },
    grid: { left: 60, right: 12, top: 60, bottom: 30 },
    xAxis: { type: 'category', data: series.map(item => item.date), axisLabel: { formatter: value => value.slice(5).replace('-', '/'), hideOverlap: true } },
    yAxis: { type: 'value', name: metric.value === 'latency' ? 's' : metric.value === 'requests' ? t('gatewayStats.count') : 'Token', axisLabel: { formatter: value => formatCompactNumber(value) } },
    series: fields.filter(([key]) => key !== 'blocked_requests' || series.some(item => item.blocked_requests > 0)).map(([key, label, color]) => ({ name: t('gatewayStats.' + label), type: 'bar', itemStyle: { color }, barMaxWidth: 22, data: series.map(item => ({ value: item[key] == null ? null : metric.value === 'latency' ? item[key] / 1000 : item[key], itemStyle: { opacity: selectedDay.value && item.date !== selectedDay.value ? 0.3 : 1 } })) })),
  }
})
async function openRequest(id) {
  const current = ++detailGeneration
  requestId.value = id; detailOpen.value = true; detailLoading.value = true; detail.value = null; detailError.value = ''
  try { const result = await getLlmStatsRequest(id); if (current === detailGeneration) detail.value = result }
  catch (e) { if (current === detailGeneration) detailError.value = e?.apiErrorCode || 'gatewayStats.detailFailed' }
  finally { if (current === detailGeneration) detailLoading.value = false }
}
function closeDetail() { ++detailGeneration; detail.value = null; detailLoading.value = false }
onMounted(() => load())
onBeforeUnmount(() => { ++generation; ++detailGeneration })
</script>

<style scoped>
.stats-toolbar,.panel-heading,.model-label,.chart-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.stats-toolbar{margin-bottom:16px}.period-select{width:270px;max-width:100%}.model-select{width:210px;max-width:100%}.active-filters{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:12px}.stats-error{margin-bottom:16px}
.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:16px}
.summary-card{display:flex;flex-direction:column;align-items:flex-start;gap:5px;padding:16px;border:1px solid #e8ebef;border-radius:6px;background:#fff;color:#1f2329;text-align:left;font:inherit;cursor:pointer;min-width:0}
.summary-card:hover{border-color:#1677ff}.summary-card:focus-visible{outline:2px solid #1677ff;outline-offset:3px}.summary-label,.summary-foot,.muted{color:#687080;font-size:12px}.summary-card strong{font-size:26px;font-weight:600;line-height:1.4;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.summary-foot{overflow-wrap:anywhere}.danger{color:#cf333e}
.chart-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(220px,1fr);gap:16px;margin-bottom:16px}.stats-panel{border:1px solid #e8ebef;border-radius:6px;padding:16px;min-width:0;background:#fff}.stats-panel h2{font-size:14px;font-weight:600;margin:0}.panel-heading .muted{font-variant-numeric:tabular-nums}.chart-footer{justify-content:flex-start;align-items:flex-start}.model-row{margin-top:18px}.model-label{font-size:12px;flex-wrap:nowrap}.model-label .ant-btn{padding:0;height:auto;white-space:normal;text-align:left;overflow-wrap:anywhere}.model-label span{white-space:nowrap}.distribution-note{border-top:1px solid #e8ebef;padding-top:12px;margin-top:16px;font-size:12px}.distribution-note .ant-btn{padding:0;height:auto;white-space:normal;text-align:left;overflow-wrap:anywhere}.distribution-note b{font-weight:500}.updated{text-align:right;margin-top:12px}.request-error{background:#f5f6f8;padding:12px;border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:280px;overflow:auto}.gateway-stats :deep(.ant-table-cell){overflow-wrap:anywhere}
@media(max-width:1050px){.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.chart-grid{grid-template-columns:minmax(0,1fr)}}
@media(max-width:575px){.summary-card,.stats-panel{padding:12px}.summary-card strong{font-size:23px}.summary-grid{gap:10px}.model-select{width:180px}.updated{text-align:left}.panel-heading{align-items:flex-start}.gateway-stats :deep(.ant-page-header-heading){flex-wrap:wrap}.gateway-stats :deep(.ant-page-header-heading-sub-title){white-space:normal}.gateway-stats :deep(.ant-table-pagination){flex-wrap:wrap}}
</style>

<style>
@media(max-width:600px){
  .gateway-stats-calendar .ant-picker-panel-container{max-width:calc(100vw - 16px);max-height:75vh;overflow:auto}
  .gateway-stats-calendar .ant-picker-panel-layout,.gateway-stats-calendar .ant-picker-panel-container .ant-picker-panels{flex-direction:column}
  .gateway-stats-calendar .ant-picker-panel-layout .ant-picker-presets{min-width:0;max-width:none;width:100%;min-height:0;border-right:0;border-bottom:1px solid #f0f0f0}
  .gateway-stats-calendar .ant-picker-panel-layout .ant-picker-presets ul{display:flex;flex-wrap:wrap;gap:4px;height:auto}
  .gateway-stats-calendar .ant-picker-presets li{margin:0;white-space:nowrap}
}
</style>
