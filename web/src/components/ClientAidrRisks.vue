<template>
  <section class="risk-panel">
    <p v-if="detectionTime && filters.detected_since">{{ t('riskOverview.detectionFilter', { start: stamp(filters.detected_since), end: stamp(filters.detected_before) }) }}</p>
    <a-alert v-if="error" type="error" show-icon :message="errorText(error)" />
    <a-table size="small" :columns="columns" :data-source="items" row-key="id" :loading="loading" :scroll="{ x: 980 }" :pagination="{ current: page, pageSize, total, showTotal: value => t('riskOverview.total', { count: value }), showSizeChanger: true }" @change="paginate" :locale="{ emptyText: tr(error ? 'readFailed' : 'empty') }">
      <template #headerCell="{ column }">
        <div v-if="column.key === 'actions'" class="risk-header-actions">
          <span>{{ column.title }}</span>
          <a-tooltip v-if="hasFilters" :title="tr('clearFilters')"><a-button type="text" size="small" :aria-label="tr('clearFilters')" @click.stop="clearFilters"><ClearOutlined /></a-button></a-tooltip>
          <a-tooltip :title="tr('refresh')"><a-button type="text" size="small" :aria-label="tr('refresh')" :loading="loading" :disabled="loading" @click.stop="refresh"><template #icon><ReloadOutlined /></template></a-button></a-tooltip>
        </div>
      </template>
      <template #customFilterDropdown="{ column }">
        <div class="risk-filter-dropdown">
      <label v-if="column.key === 'disposition'">{{ tr('disposition.label') }}<a-select v-model:value="filters.disposition" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in dispositionStates" :key="value" :value="value">{{ tr(`disposition.states.${value}`) }}</a-select-option></a-select></label>
      <label v-if="column.key === 'risk'">{{ tr('severityLabel') }}<a-select v-model:value="filters.severity" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in ['high', 'medium']" :key="value" :value="value">{{ tr(`severity.${value}`) }}</a-select-option></a-select></label>
      <label v-if="column.key === 'risk'">{{ tr('type') }}<a-select v-model:value="filters.risk_code" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in codes" :key="value" :value="value">{{ tr(`codes.${value}`) }}</a-select-option></a-select></label>
      <label v-if="column.key === 'source'">{{ tr('source') }}<a-select v-model:value="filters.source" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in ['hooks', 'logs', 'system']" :key="value" :value="value">{{ tr(`sources.${value}`) }}</a-select-option></a-select></label>
      <label v-if="column.key === 'agent'">{{ tr('agentFilter') }}<a-select v-model:value="filters.agent" show-search option-filter-prop="label" :options="agentOptions" @change="filters.unknown_agent = false; filterChanged()" /></label>
      <div v-if="column.key === 'time'" class="risk-date-range">
        <label>{{ tr('dateRange') }}<a-range-picker popup-class-name="risk-date-popup" v-model:value="timeRange" format="YYYY-MM-DD" :placeholder="[tr('since'), tr('until')]" @change="dateChanged" /></label>
        <small v-if="rangeError" class="field-error" role="alert">{{ rangeError }}</small>
      </div>
        </div>
      </template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'time'">{{ stamp(detectionTime ? record.detected_at : record.occurred_at) }}</template>
        <template v-else-if="column.key === 'risk'"><a-tag :color="record.severity === 'high' ? 'red' : 'orange'">{{ tr(`severity.${record.severity}`) }}</a-tag><strong>{{ tr(`codes.${record.risk_code}`) }}</strong></template>
        <template v-else-if="column.key === 'agent'">{{ record.agent || tr('unknown') }}</template>
        <template v-else-if="column.key === 'source'">{{ tr(`sources.${record.source}`) }}</template>
        <template v-else-if="column.key === 'disposition'">{{ tr(`disposition.states.${record.disposition}`) }}</template>
        <template v-else-if="column.key === 'actions'"><a-button type="link" @click="showDetail(record.id)">{{ tr('view') }}</a-button></template>
      </template>
    </a-table>
    <a-drawer v-model:open="detailOpen" :title="tr('details')" width="min(820px, 100vw)" @close="closeDetail">
      <a-spin :spinning="detailLoading"><a-alert v-if="detailError" type="error" show-icon :message="errorText(detailError)" />
        <template v-if="detail">
          <h3>{{ tr(`codes.${detail.risk_code}`) }}</h3>
          <section class="detection-trace">
            <h4>{{ tr('commandRules.trace') }}</h4>
            <AidrDetectionMatches v-if="detail.detection_matches?.length" :matches="detail.detection_matches" />
            <p v-else>{{ tr('commandRules.noTrace') }}</p>
            <small v-if="detail.detection_matches?.length && !evidenceLoaded">{{ tr('commandRules.traceHelp') }}</small>
          </section>
          <dl class="risk-meta">
            <dt>{{ tr('severityLabel') }}</dt><dd>{{ tr(`severity.${detail.severity}`) }}</dd>
            <template v-if="detail.detection_source"><dt>{{ tr('settings.ruleSource') }}</dt><dd>{{ tr(detail.detection_source === 'inherit' ? 'settings.globalRules' : 'settings.clientRules') }}</dd></template>
            <dt>{{ tr('agent') }}</dt><dd>{{ products.find(product => product.id === detail.agent)?.name || detail.agent || tr('unknown') }}</dd>
            <dt>{{ tr('session') }}</dt><dd>{{ detail.session_id || tr('unknown') }}</dd>
            <dt>{{ tr('time') }}</dt><dd>{{ stamp(detail.occurred_at) }}</dd>
            <dt>{{ tr('result') }}</dt><dd>{{ executionResult }}</dd>
            <template v-if="detail.control_status && detail.control_status !== 'unknown'"><dt>{{ tr('control') }}</dt><dd>{{ status(detail.control_status) }}<small v-if="controlReason(detail.control_code)">{{ controlReason(detail.control_code) }}</small></dd></template>
          </dl>
          <section class="risk-disposition">
            <h4>{{ tr('disposition.label') }}: {{ tr(`disposition.states.${detail.disposition}`) }}</h4>
            <a-alert v-if="dispositionError" type="error" show-icon :message="errorText(dispositionError)" />
            <a-button v-if="can('clients:update') && !dispositionEditing" @click="dispositionEditing = true">{{ tr('disposition.edit') }}</a-button>
            <a-form v-if="can('clients:update') && dispositionEditing" :model="dispositionDraft" layout="vertical" @finish="saveDisposition">
              <a-form-item :label="tr('disposition.target')" required><a-select v-model:value="dispositionDraft.status" :aria-label="tr('disposition.target')" :disabled="disposing"><a-select-option v-for="value in dispositionStates" :key="value" :value="value" :disabled="value === detail.disposition">{{ tr(`disposition.states.${value}`) }}</a-select-option></a-select></a-form-item>
              <a-form-item :label="tr('disposition.reason')" required :validate-status="reasonCount > 1000 ? 'error' : undefined" :help="reasonCount > 1000 ? tr('disposition.tooLong', { count: reasonCount - 1000 }) : undefined"><a-textarea v-model:value="dispositionDraft.reason" :aria-label="tr('disposition.reason')" :rows="2" :disabled="disposing" /><small class="reason-count">{{ reasonCount }} / 1000</small></a-form-item>
              <a-space class="disposition-actions" wrap><a-button type="primary" html-type="submit" :loading="disposing" :disabled="!dispositionValid || disposing || detailLoading">{{ tr('disposition.save') }}</a-button><a-button :disabled="disposing" @click="dispositionEditing = false">{{ tr('disposition.cancel') }}</a-button><a-button v-if="dispositionError" :disabled="disposing || detailLoading" @click="reloadDisposition">{{ tr('disposition.reload') }}</a-button></a-space>
            </a-form>
            <p v-if="!can('clients:update')">{{ tr('disposition.permission') }}</p>
          </section>
          <a-alert v-for="value in detail.limitations.filter(value => value !== 'result_unverified')" :key="value" type="warning" :message="tr(`limitations.${value}`)" />
          <h4>{{ tr('evidence') }}</h4><p v-if="!evidenceLoaded">{{ tr('evidenceCount', { count: detail.evidence.length }) }}</p>
          <a-button v-if="can('clients:read-audit-content') && !evidenceLoaded" :loading="detailLoading" :disabled="detailLoading || disposing" @click="showDetail(detail.id, true)">{{ tr('loadEvidence') }}</a-button><p v-else-if="!can('clients:read-audit-content')">{{ tr('contentPermission') }}</p>
          <article v-for="item in evidenceLoaded ? detail.evidence : []" :key="`${item.source}:${item.record_id}`" class="risk-evidence"><strong>{{ tr(`sources.${item.source}`) }} · #{{ item.record_id }}</strong><p v-if="item.expired">{{ tr('expired') }}</p><p v-else-if="item.changed">{{ tr('evidenceChanged') }}</p>
            <template v-if="item.event">
              <dl class="risk-meta"><dt>{{ tr('tool') }}</dt><dd>{{ item.event.tool || item.event.executable || tr('unknown') }}</dd><dt>{{ tr('result') }}</dt><dd>{{ status(item.event.status) }}<span v-if="item.event.exit_code != null"> · {{ tr('exitCode') }}: {{ item.event.exit_code }}</span></dd></dl>
              <template v-for="(action, index) in item.event.actions" :key="index"><pre v-if="action.command">{{ action.command }}</pre><p v-if="action.cwd">{{ tr('cwd') }}: <code>{{ action.cwd }}</code></p><p v-for="(target, i) in action.targets" :key="i">{{ tr('target') }}: <code>{{ target.value }}</code></p></template>
              <pre v-if="item.event.argv?.length">{{ item.event.argv.join('\n') }}</pre><p v-if="item.event.path">{{ tr('target') }}: <code>{{ item.event.path }}</code></p><p v-if="item.event.destination_path">{{ tr('destination') }}: <code>{{ item.event.destination_path }}</code></p>
            </template>
          </article>
          <section class="risk-history">
            <h4>{{ tr('disposition.history') }}</h4>
            <a-alert v-if="historyError" type="error" :message="errorText(historyError)" />
            <a-button v-if="historyError" @click="loadHistory()">{{ tr('refresh') }}</a-button>
            <p v-if="!historyLoading && !historyError && historyTotal === 0">{{ tr('noHistory') }}</p>
            <a-table v-else size="small" :columns="historyColumns" :data-source="history" row-key="revision" :loading="historyLoading" :scroll="{ x: 650 }" :pagination="{ current: historyPage, pageSize: 10, total: historyTotal, showSizeChanger: false }" @change="value => loadHistory(value.current)">
              <template #bodyCell="{ column, record }"><template v-if="column.key === 'transition'">{{ tr(`disposition.states.${record.previous}`) }} → {{ tr(`disposition.states.${record.status}`) }}</template><template v-else-if="column.key === 'created_at'">{{ stamp(record.created_at) }}</template><template v-else-if="column.key === 'reason'"><span class="disposition-reason">{{ record.reason }}</span></template></template>
            </a-table>
          </section>
        </template>
      </a-spin>
    </a-drawer>

  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ClearOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import products from '../aidr-products.json'
import AidrDetectionMatches from './AidrDetectionMatches.vue'
import { useI18n } from 'vue-i18n'
import { can } from '../access'
import { formatDateTime } from '../utils/format'
import { localizeApiError } from '../i18n/errors'
import { getClientAidrRisks, getClientAidrRiskSummary, getClientAidrRisk, getClientAidrRiskDispositions, setClientAidrRiskDisposition } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, initialAgent: { type: String, default: '' }, fixedAgent: { type: String, default: '' }, initialFilters: { type: Object, default: null } })
const emit = defineEmits(['changed', 'filters-cleared'])
const detectionTime = computed(() => props.initialFilters !== null)
const { t, te, locale } = useI18n(), tr = (key, values) => t(`aidrRisk.${key}`, values || {})
const codes = ['destructive_command', 'download_to_shell', 'sensitive_path_read', 'protected_path_change', 'tool_policy_denied', 'system_access_denied', 'filesystem_format', 'device_write', 'protected_permissions', 'custom_command', 'custom_tool']
const dispositionStates = ['open', 'accepted', 'false_positive', 'resolved']
const dispositionEditing = ref(false)
const dispositionDraft = ref({ status: undefined, reason: '' }), disposing = ref(false), dispositionError = ref(null)
const history = ref([]), historyPage = ref(1), historyTotal = ref(0), historyLoading = ref(false), historyError = ref(null)
let historyGeneration = 0
const reasonCount = computed(() => Array.from(dispositionDraft.value.reason).length)
const dispositionValid = computed(() => dispositionStates.includes(dispositionDraft.value.status) && dispositionDraft.value.status !== detail.value?.disposition && dispositionDraft.value.reason.trim() && reasonCount.value <= 1000)
const historyColumns = computed(() => ['created_at', 'actor', 'transition', 'reason'].map(key => ({ key, dataIndex: key, title: tr(`disposition.${key}`) })))
const items = ref([]), total = ref(0), page = ref(1), pageSize = ref(10), summary = ref(null), loading = ref(false), error = ref(null)
const timeRange = ref(null), rangeError = ref('')
const sortState = ref({ key: 'time', order: 'descend' })
const sortFields = { time: 'occurred_at', risk: 'severity', agent: 'agent' }
const agentOptions = computed(() => [{ value: '', label: tr('all') }, ...[...new Set([...(summary.value?.agents || []), props.initialAgent].filter(Boolean))].sort().map(value => ({ value, label: value }))])
const filters = ref({ severity: '', risk_code: '', source: '', agent: '', since: '', until: '', disposition: '' })
const hasFilters = computed(() => Object.values(filters.value).some(Boolean))
const activeFilters = computed(() => ({ time: !!(filters.value.since || filters.value.detected_since), risk: !!(filters.value.severity || filters.value.risk_code), agent: !!(filters.value.agent || filters.value.unknown_agent), source: !!filters.value.source, disposition: !!filters.value.disposition }))
const detailOpen = ref(false), detail = ref(null), detailLoading = ref(false), detailError = ref(null), evidenceLoaded = ref(false)
let generation = 0, detailGeneration = 0
const stamp = value => value ? formatDateTime(value) : tr('unknown')
const status = value => te(`aidrRisk.statuses.${value}`) ? tr(`statuses.${value}`) : tr('unknown')
const controlReason = code => { const key = [`aidrRisk.controlReasons.${code}`, `aidr.hooks.runtime.${code}`, `aidr.enforcement.reasons.${code}`].find(value => te(value)); return key ? t(key) : '' }
const executionResult = computed(() => {
  const value = detail.value
  if (value.result_status && !['unknown', 'missing_result'].includes(value.result_status)) return status(value.result_status)
  if (value.result_reasons?.includes('result_fields_conflict')) return status('conflicting_evidence')
  const missingFeedback = ['hooks', 'logs'].includes(value.source) && value.result_feedback === false && !value.evidence?.some(item => item.expired || item.changed)
  return tr(missingFeedback ? 'feedbackNotCaptured' : 'resultNotCaptured')
})
const errorText = value => localizeApiError({ code: value?.apiErrorCode, params: value?.apiErrorParams, message: value?.response?.data?.detail || tr('readFailed') }, locale.value)
const columns = computed(() => [['time', 'time'], ['risk', 'type'], ['agent', 'agent'], ['source', 'source'], ['disposition', 'disposition.label'], ['actions', 'details']].map(([key, title]) => ({ key, title: key === 'time' && detectionTime.value ? t('riskOverview.detected') : tr(title), ...(key !== 'actions' && !(key === 'agent' && props.fixedAgent) ? { customFilterDropdown: true, filtered: activeFilters.value[key] } : {}), ...(sortFields[key] ? { sorter: true, sortDirections: ['ascend', 'descend', 'ascend'], sortOrder: sortState.value.key === key ? sortState.value.order : null } : {}) })))
async function refresh() {
  const epoch = ++generation; loading.value = true; error.value = null
  try { const params = { ...filters.value, ...(props.fixedAgent ? { agent_type: props.fixedAgent, agent: '', unknown_agent: false } : {}), detected_since: filters.value.detected_since || undefined, detected_before: filters.value.detected_before || undefined, since: filters.value.since ? new Date(filters.value.since).toISOString() : undefined, until: filters.value.until ? new Date(filters.value.until).toISOString() : undefined, sort_by: detectionTime.value && sortState.value.key === 'time' ? 'detected_at' : sortFields[sortState.value.key], sort_order: sortState.value.order === 'ascend' ? 'asc' : 'desc', page: page.value, page_size: pageSize.value }; const [list, stats] = await Promise.all([getClientAidrRisks(props.clientId, params), getClientAidrRiskSummary(props.clientId)]); if (epoch !== generation) return; items.value = list.items; total.value = list.total; summary.value = stats }
  catch (cause) { if (epoch === generation) { error.value = cause; items.value = []; total.value = 0; summary.value = null } }
  finally { if (epoch === generation) loading.value = false }
}
function clearFilters() { emit('filters-cleared'); timeRange.value = null; rangeError.value = ''; filters.value = { severity: '', risk_code: '', source: '', agent: '', since: '', until: '', disposition: '' }; filterChanged() }
function filterChanged() { page.value = 1; refresh() }
function dateChanged(value) {
  rangeError.value = ''
  if (value && (!value[0]?.isValid() || !value[1]?.isValid() || value[0].valueOf() > value[1].valueOf())) { rangeError.value = tr('invalidRange'); return }
  filters.value.since = value?.[0]?.startOf('day').toISOString() || ''
  filters.value.until = value?.[1]?.endOf('day').toISOString() || ''
  if (detectionTime.value) { filters.value.detected_since = filters.value.since; filters.value.detected_before = value?.[1]?.add(1, 'day').startOf('day').toISOString() || ''; filters.value.since = ''; filters.value.until = '' }
  filterChanged()
}
function paginate(value, _filters, sorter, extra) {
  pageSize.value = value.pageSize
  if (extra.action === 'sort') { sortState.value = { key: sorter.columnKey, order: sorter.order }; page.value = 1 }
  else page.value = value.current
  refresh()
}
function closeDetail() { detailGeneration++; historyGeneration++; detail.value = null; detailLoading.value = false; disposing.value = false; history.value = []; historyTotal.value = 0 }
async function showDetail(id, evidence = false) {
  const epoch = ++detailGeneration; detailOpen.value = true; detailLoading.value = true; detailError.value = null
  if (!evidence) { dispositionEditing.value = false; detail.value = null; evidenceLoaded.value = false; dispositionDraft.value = { status: undefined, reason: '' }; dispositionError.value = null; history.value = []; historyTotal.value = 0; historyGeneration++ }
  try { const value = await getClientAidrRisk(props.clientId, id, { include_evidence: evidence }); if (epoch === detailGeneration) { detail.value = value; evidenceLoaded.value = evidence } }
  catch (cause) { if (epoch === detailGeneration) detailError.value = cause }
  finally { if (epoch === detailGeneration) { detailLoading.value = false; if (detail.value && !evidence) loadHistory(1) } }
}
async function loadHistory(page = historyPage.value) {
  if (!detail.value) return
  const epoch = ++historyGeneration; historyPage.value = page; historyLoading.value = true; historyError.value = null
  try { const value = await getClientAidrRiskDispositions(props.clientId, detail.value.id, { page, page_size: 10 }); if (epoch === historyGeneration) { history.value = value.items; historyTotal.value = value.total } }
  catch (cause) { if (epoch === historyGeneration) historyError.value = cause }
  finally { if (epoch === historyGeneration) historyLoading.value = false }
}
async function reloadDisposition() {
  if (!detail.value || detailLoading.value || disposing.value) return
  const epoch = detailGeneration; detailLoading.value = true; dispositionError.value = null
  try { const value = await getClientAidrRisk(props.clientId, detail.value.id); if (epoch === detailGeneration) { detail.value = { ...value, evidence: detail.value.evidence, detection_matches: evidenceLoaded.value ? detail.value.detection_matches : value.detection_matches }; loadHistory(1) } }
  catch (cause) { if (epoch === detailGeneration) dispositionError.value = cause }
  finally { if (epoch === detailGeneration) detailLoading.value = false }
}
async function saveDisposition() {
  if (disposing.value || detailLoading.value || !dispositionValid.value || !can('clients:update')) return
  const epoch = detailGeneration; disposing.value = true; dispositionError.value = null
  try { const value = await setClientAidrRiskDisposition(props.clientId, detail.value.id, { ...dispositionDraft.value, expected_revision: detail.value.disposition_revision }); if (epoch === detailGeneration) { detail.value = { ...detail.value, ...value }; dispositionEditing.value = false; dispositionDraft.value = { status: undefined, reason: '' }; loadHistory(1); refresh(); emit('changed') } }
  catch (cause) { if (epoch === detailGeneration) dispositionError.value = cause }
  finally { if (epoch === detailGeneration) disposing.value = false }
}
watch(() => [props.clientId, props.initialAgent, props.fixedAgent, props.initialFilters], () => { timeRange.value = null; rangeError.value = ''; sortState.value = { key: 'time', order: 'descend' }; filters.value = { severity: '', risk_code: '', source: '', agent: props.initialAgent, since: '', until: '', disposition: '', ...props.initialFilters }; closeDetail(); detailOpen.value = false; page.value = 1; items.value = []; summary.value = null; refresh() }, { immediate: true })
onBeforeUnmount(() => { generation++; detailGeneration++; historyGeneration++ })
defineExpose({ showDetail })
</script>

<style scoped>
.risk-panel { overflow: auto; min-height: 0; padding-bottom: 16px; }
.risk-disposition .ant-form { margin-top: 16px; }
.risk-disposition { padding: 20px 0; border-block: 1px solid #eee; margin: 20px 0; }
.risk-history { margin-top: 24px; }.risk-history h4 { margin-bottom: 12px; }.reason-count { text-align: right; margin-top: 4px; }.disposition-actions { margin-top: 4px; }
.disposition-reason { white-space: pre-wrap; overflow-wrap: anywhere; }
.risk-header-actions { display: flex; align-items: center; gap: 4px; white-space: nowrap; }
.risk-header-actions > span { margin-right: 4px; }
.risk-filter-dropdown { padding: 12px; width: min(320px, calc(100vw - 32px)); display: flex; flex-direction: column; gap: 12px; }
.risk-filter-dropdown label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.risk-date-range :deep(.ant-picker) { width: 100%; }
.field-error { color: #cf1322; margin-top: 4px; }

small { display: block; color: #667085; white-space: normal; overflow-wrap: anywhere; }
.risk-meta { display: grid; grid-template-columns: minmax(100px, 150px) minmax(0, 1fr); gap: 8px 12px; }.risk-meta dt { color: #667085; }.risk-meta dd { margin: 0; overflow-wrap: anywhere; }
.risk-evidence { border-top: 1px solid #e5e7eb; padding: 12px 0; } pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 280px; overflow: auto; padding: 12px; background: #f6f8fa; } code { overflow-wrap: anywhere; } .ant-alert { margin-bottom: 12px; }
@media (max-width: 540px) { .risk-date-range :deep(.ant-picker-range) { flex-wrap: wrap; gap: 8px; }.risk-date-range :deep(.ant-picker-input) { flex: 1 0 100%; }.risk-date-range :deep(.ant-picker-range-separator) { display: none; }.risk-meta { grid-template-columns: 1fr; gap: 4px; }.risk-meta dd { margin-bottom: 10px; } }
</style>

<style>
@media (max-width: 540px) {
  .risk-date-popup { left: 8px !important; }
  .risk-date-popup .ant-picker-panels { flex-direction: column; }
  .risk-date-popup .ant-picker-panel-container { max-height: 55vh; overflow-y: auto; margin-left: 0 !important; }
}
</style>
