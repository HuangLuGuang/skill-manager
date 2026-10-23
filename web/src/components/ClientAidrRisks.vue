<template>
  <section class="risk-panel">
    <div class="risk-toolbar"><h3>{{ tr('title') }}</h3><a-button :loading="loading" :disabled="loading" @click="refresh">{{ tr('refresh') }}</a-button><a-button v-if="can('settings:view')" :loading="configLoading" :disabled="configLoading" @click="openConfig">{{ tr('configuration') }}</a-button></div>
    <a-alert v-if="error" type="error" show-icon :message="errorText(error)" />
    <div v-if="summary" class="risk-summary">
      <span v-for="value in dispositionStates" :key="value">{{ tr(`disposition.states.${value}`) }} <strong>{{ summary.dispositions?.[value] || 0 }}</strong></span>
      <a-tag color="red">{{ tr('severity.high') }} {{ summary.counts.high || 0 }}</a-tag><a-tag color="orange">{{ tr('severity.medium') }} {{ summary.counts.medium || 0 }}</a-tag>
      <a-tooltip :title="`${tr('checkedAt')}: ${checkedAt}`"><span class="risk-progress">{{ tr(!summary.enabled ? 'detectionDisabled' : caughtUp ? 'caughtUp' : 'pending') }}</span></a-tooltip>
    </div>
    <div class="risk-filters">
      <label>{{ tr('disposition.label') }}<a-select v-model:value="filters.disposition" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in dispositionStates" :key="value" :value="value">{{ tr(`disposition.states.${value}`) }}</a-select-option></a-select></label>
      <label>{{ tr('severityLabel') }}<a-select v-model:value="filters.severity" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in ['high', 'medium']" :key="value" :value="value">{{ tr(`severity.${value}`) }}</a-select-option></a-select></label>
      <label>{{ tr('type') }}<a-select v-model:value="filters.risk_code" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in codes" :key="value" :value="value">{{ tr(`codes.${value}`) }}</a-select-option></a-select></label>
      <label>{{ tr('source') }}<a-select v-model:value="filters.source" @change="filterChanged"><a-select-option value="">{{ tr('all') }}</a-select-option><a-select-option v-for="value in ['hooks', 'logs', 'system']" :key="value" :value="value">{{ tr(`sources.${value}`) }}</a-select-option></a-select></label>
      <label>{{ tr('agentFilter') }}<a-input v-model:value="filters.agent" allow-clear @change="schedule" @pressEnter="filterChanged" /></label>
      <div class="risk-date-range">
        <label class="risk-date">{{ tr('since') }}<input v-model="filters.since" type="datetime-local" step="1" @change="filterChanged" /></label>
        <label class="risk-date">{{ tr('until') }}<input v-model="filters.until" type="datetime-local" step="1" @change="filterChanged" /></label>
      </div>
    </div>
    <a-table :columns="columns" :data-source="items" row-key="id" :loading="loading" :scroll="{ x: 980 }" :pagination="{ current: page, pageSize, total, showSizeChanger: true }" @change="paginate" :locale="{ emptyText: tr(error ? 'readFailed' : caughtUp ? 'empty' : 'pending') }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'time'">{{ stamp(record.occurred_at) }}</template>
        <template v-else-if="column.key === 'risk'"><a-tag :color="record.severity === 'high' ? 'red' : 'orange'">{{ tr(`severity.${record.severity}`) }}</a-tag><strong>{{ tr(`codes.${record.risk_code}`) }}</strong></template>
        <template v-else-if="column.key === 'agent'">{{ record.agent || tr('unknown') }}</template>
        <template v-else-if="column.key === 'source'">{{ tr(`sources.${record.source}`) }}</template>
        <template v-else-if="column.key === 'result'">{{ status(record.result_status) }}<small v-if="record.control_status && record.control_status !== 'unknown'">{{ status(record.control_status) }}</small></template>
        <template v-else-if="column.key === 'disposition'">{{ tr(`disposition.states.${record.disposition}`) }}</template>
        <template v-else-if="column.key === 'actions'"><a-button type="link" @click="showDetail(record.id)">{{ tr('view') }}</a-button></template>
      </template>
    </a-table>
    <a-drawer v-model:open="detailOpen" :title="tr('details')" width="min(820px, 100vw)" @close="closeDetail">
      <a-spin :spinning="detailLoading"><a-alert v-if="detailError" type="error" show-icon :message="errorText(detailError)" />
        <template v-if="detail">
          <h3>{{ tr(`codes.${detail.risk_code}`) }}</h3><p>{{ tr(`reasons.${detail.risk_code}`) }}</p>
          <dl class="risk-meta">
            <dt>{{ tr('severityLabel') }}</dt><dd>{{ tr(`severity.${detail.severity}`) }}</dd>
            <dt>{{ tr('agent') }}</dt><dd>{{ detail.agent || tr('unknown') }} · {{ tr(`attribution.${detail.attribution_status}`) }}</dd>
            <dt>{{ tr('session') }}</dt><dd>{{ detail.session_id || tr('unknown') }}</dd>
            <dt>{{ tr('time') }}</dt><dd>{{ stamp(detail.occurred_at) }} · {{ tr(`timeBasis.${detail.time_basis}`) }}</dd>
            <dt>{{ tr('result') }}</dt><dd>{{ status(detail.result_status) }}</dd>
            <template v-if="detail.control_status && detail.control_status !== 'unknown'"><dt>{{ tr('control') }}</dt><dd>{{ status(detail.control_status) }}<small v-if="detail.control_code">{{ controlReason(detail.control_code) }}</small></dd></template>
          </dl>
          <section class="risk-disposition">
            <h4>{{ tr('disposition.label') }}: {{ tr(`disposition.states.${detail.disposition}`) }}</h4>
            <a-alert v-if="dispositionError" type="error" show-icon :message="errorText(dispositionError)" />
            <a-form v-if="can('clients:update')" :model="dispositionDraft" layout="vertical" @finish="saveDisposition">
              <a-form-item :label="tr('disposition.target')" required><a-select v-model:value="dispositionDraft.status" :aria-label="tr('disposition.target')" :disabled="disposing"><a-select-option v-for="value in dispositionStates" :key="value" :value="value" :disabled="value === detail.disposition">{{ tr(`disposition.states.${value}`) }}</a-select-option></a-select></a-form-item>
              <a-form-item :label="tr('disposition.reason')" required :validate-status="reasonCount > 1000 ? 'error' : undefined" :help="reasonCount > 1000 ? tr('disposition.tooLong', { count: reasonCount - 1000 }) : undefined"><a-textarea v-model:value="dispositionDraft.reason" :aria-label="tr('disposition.reason')" :rows="2" :disabled="disposing" /><small class="reason-count">{{ reasonCount }} / 1000</small></a-form-item>
              <a-space class="disposition-actions" wrap><a-button type="primary" html-type="submit" :loading="disposing" :disabled="!dispositionValid || disposing || detailLoading">{{ tr('disposition.save') }}</a-button><a-button v-if="dispositionError" :disabled="disposing || detailLoading" @click="reloadDisposition">{{ tr('disposition.reload') }}</a-button></a-space>
            </a-form>
            <p v-else>{{ tr('disposition.permission') }}</p>
          </section>
          <a-alert v-for="value in detail.limitations.filter(value => value !== 'result_unverified')" :key="value" type="warning" :message="tr(`limitations.${value}`)" />
          <h4>{{ tr('evidence') }}</h4>
          <a-button v-if="can('clients:read-audit-content') && !evidenceLoaded" :loading="detailLoading" :disabled="detailLoading || disposing" @click="showDetail(detail.id, true)">{{ tr('loadEvidence') }}</a-button><p v-else-if="!can('clients:read-audit-content')">{{ tr('contentPermission') }}</p>
          <article v-for="item in detail.evidence" :key="`${item.source}:${item.record_id}`" class="risk-evidence"><strong>{{ tr(`sources.${item.source}`) }} · #{{ item.record_id }}</strong><p v-if="item.expired">{{ tr('expired') }}</p><p v-else-if="item.changed">{{ tr('evidenceChanged') }}</p>
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
            <a-table size="small" :columns="historyColumns" :data-source="history" row-key="revision" :loading="historyLoading" :scroll="{ x: 650 }" :pagination="{ current: historyPage, pageSize: 10, total: historyTotal, showSizeChanger: false }" @change="value => loadHistory(value.current)">
              <template #bodyCell="{ column, record }"><template v-if="column.key === 'transition'">{{ tr(`disposition.states.${record.previous}`) }} → {{ tr(`disposition.states.${record.status}`) }}</template><template v-else-if="column.key === 'created_at'">{{ stamp(record.created_at) }}</template><template v-else-if="column.key === 'reason'"><span class="disposition-reason">{{ record.reason }}</span></template></template>
            </a-table>
          </section>
        </template>
      </a-spin>
    </a-drawer>
    <a-modal v-model:open="configOpen" :title="tr('configuration')" :footer="null" width="min(720px, 100vw)">
      <p>{{ tr('configHelp') }}</p><a-alert v-if="configError" type="error" show-icon :message="errorText(configError)" />
      <a-form :model="draft" layout="vertical" @finish="saveConfig"><a-form-item :label="tr('enabled')"><a-switch v-model:checked="draft.enabled" :disabled="!canEdit || saving" /></a-form-item><a-form-item :label="tr('sensitivePaths')"><a-textarea v-model:value="draft.sensitive" :rows="4" :disabled="!canEdit || saving" /></a-form-item><a-form-item :label="tr('protectedPaths')"><a-textarea v-model:value="draft.protected" :rows="4" :disabled="!canEdit || saving" /></a-form-item><p>{{ tr('pathHelp') }}</p><a-button v-if="canEdit" type="primary" html-type="submit" :loading="saving" :disabled="saving">{{ tr('save') }}</a-button></a-form>
    </a-modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { can } from '../access'
import { formatDateTime } from '../utils/format'
import { localizeApiError } from '../i18n/errors'
import { getClientAidrRisks, getClientAidrRiskSummary, getClientAidrRisk, getClientAidrRiskConfiguration, saveClientAidrRiskConfiguration, getClientAidrRiskDispositions, setClientAidrRiskDisposition } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, initialAgent: { type: String, default: '' } })
const { t, te, locale } = useI18n(), tr = (key, values) => t(`aidrRisk.${key}`, values || {})
const codes = ['destructive_command', 'download_to_shell', 'sensitive_path_read', 'protected_path_change', 'tool_policy_denied', 'system_access_denied']
const dispositionStates = ['open', 'accepted', 'false_positive', 'resolved']
const dispositionDraft = ref({ status: undefined, reason: '' }), disposing = ref(false), dispositionError = ref(null)
const history = ref([]), historyPage = ref(1), historyTotal = ref(0), historyLoading = ref(false), historyError = ref(null)
let historyGeneration = 0
const reasonCount = computed(() => Array.from(dispositionDraft.value.reason).length)
const dispositionValid = computed(() => dispositionStates.includes(dispositionDraft.value.status) && dispositionDraft.value.status !== detail.value?.disposition && dispositionDraft.value.reason.trim() && reasonCount.value <= 1000)
const historyColumns = computed(() => ['created_at', 'actor', 'transition', 'reason'].map(key => ({ key, dataIndex: key, title: tr(`disposition.${key}`) })))
const items = ref([]), total = ref(0), page = ref(1), pageSize = ref(20), summary = ref(null), loading = ref(false), error = ref(null)
const filters = ref({ severity: '', risk_code: '', source: '', agent: '', since: '', until: '', disposition: '' })
const detailOpen = ref(false), detail = ref(null), detailLoading = ref(false), detailError = ref(null), evidenceLoaded = ref(false)
const configOpen = ref(false), configLoading = ref(false), configError = ref(null), saving = ref(false), revision = ref(0), draft = ref({ enabled: true, sensitive: '', protected: '' })
let generation = 0, detailGeneration = 0, configGeneration = 0, timer
const serverCanEdit = ref(false)
const canEdit = computed(() => serverCanEdit.value && can('clients:update') && can('settings:update'))
const caughtUp = computed(() => !!summary.value?.progress?.every(item => item.caught_up && item.fresh))
const stamp = value => value ? formatDateTime(value) : tr('unknown')
const checkedAt = computed(() => stamp(summary.value?.progress?.map(item => item.checked_at).filter(Boolean).sort()[0]))
const status = value => te(`aidrRisk.statuses.${value}`) ? tr(`statuses.${value}`) : tr('unknown')
const controlReason = code => { const key = [`aidrRisk.controlReasons.${code}`, `aidr.hooks.runtime.${code}`, `aidr.enforcement.reasons.${code}`].find(value => te(value)); return key ? t(key) : tr('technicalReason', { code }) }
const errorText = value => localizeApiError({ code: value?.apiErrorCode, params: value?.apiErrorParams, message: value?.response?.data?.detail || tr('readFailed') }, locale.value)
const columns = computed(() => [['time', 'time'], ['risk', 'type'], ['agent', 'agent'], ['source', 'source'], ['result', 'result'], ['disposition', 'disposition.label'], ['actions', 'details']].map(([key, title]) => ({ key, title: tr(title) })))
function clearTimer() { clearTimeout(timer); timer = null }
async function refresh() {
  if (timer) page.value = 1
  clearTimer(); const epoch = ++generation; loading.value = true; error.value = null
  try { const params = { ...filters.value, since: filters.value.since ? new Date(filters.value.since).toISOString() : undefined, until: filters.value.until ? new Date(filters.value.until).toISOString() : undefined, page: page.value, page_size: pageSize.value }; const [list, stats] = await Promise.all([getClientAidrRisks(props.clientId, params), getClientAidrRiskSummary(props.clientId)]); if (epoch !== generation) return; items.value = list.items; total.value = list.total; summary.value = stats }
  catch (cause) { if (epoch === generation) { error.value = cause; items.value = []; total.value = 0; summary.value = null } }
  finally { if (epoch === generation) loading.value = false }
}
function filterChanged() { page.value = 1; refresh() }
function schedule() { clearTimer(); generation++; loading.value = false; timer = setTimeout(filterChanged, 300) }
function paginate(value) { page.value = timer ? 1 : value.current; pageSize.value = value.pageSize; refresh() }
function closeDetail() { detailGeneration++; historyGeneration++; detail.value = null; detailLoading.value = false; disposing.value = false; history.value = []; historyTotal.value = 0 }
async function showDetail(id, evidence = false) {
  const epoch = ++detailGeneration; detailOpen.value = true; detailLoading.value = true; detailError.value = null
  if (!evidence) { detail.value = null; evidenceLoaded.value = false; dispositionDraft.value = { status: undefined, reason: '' }; dispositionError.value = null; history.value = []; historyTotal.value = 0; historyGeneration++ }
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
  try { const value = await getClientAidrRisk(props.clientId, detail.value.id); if (epoch === detailGeneration) { detail.value = { ...value, evidence: detail.value.evidence }; loadHistory(1) } }
  catch (cause) { if (epoch === detailGeneration) dispositionError.value = cause }
  finally { if (epoch === detailGeneration) detailLoading.value = false }
}
async function saveDisposition() {
  if (disposing.value || detailLoading.value || !dispositionValid.value || !can('clients:update')) return
  const epoch = detailGeneration; disposing.value = true; dispositionError.value = null
  try { const value = await setClientAidrRiskDisposition(props.clientId, detail.value.id, { ...dispositionDraft.value, expected_revision: detail.value.disposition_revision }); if (epoch === detailGeneration) { detail.value = { ...detail.value, ...value }; dispositionDraft.value = { status: undefined, reason: '' }; loadHistory(1); refresh() } }
  catch (cause) { if (epoch === detailGeneration) dispositionError.value = cause }
  finally { if (epoch === detailGeneration) disposing.value = false }
}
async function openConfig() {
  const epoch = ++configGeneration; configLoading.value = true; configError.value = null
  try { const value = await getClientAidrRiskConfiguration(props.clientId); if (epoch !== configGeneration) return; serverCanEdit.value = value.can_edit; revision.value = value.revision; draft.value = { enabled: value.enabled, sensitive: value.sensitive_paths.join('\n'), protected: value.protected_paths.join('\n') }; configOpen.value = true }
  catch (cause) { if (epoch === configGeneration) error.value = cause }
  finally { if (epoch === configGeneration) configLoading.value = false }
}
async function saveConfig() {
  if (saving.value || !canEdit.value) return
  const epoch = configGeneration; saving.value = true; configError.value = null
  const lines = value => value.split('\n').filter(line => line !== '')
  try { const value = await saveClientAidrRiskConfiguration(props.clientId, { expected_revision: revision.value, enabled: draft.value.enabled, sensitive_paths: lines(draft.value.sensitive), protected_paths: lines(draft.value.protected) }); if (epoch === configGeneration) { revision.value = value.revision; configOpen.value = false; refresh() } }
  catch (cause) { if (epoch === configGeneration) configError.value = cause }
  finally { if (epoch === configGeneration) saving.value = false }
}
watch(() => [props.clientId, props.initialAgent], () => { clearTimer(); filters.value = { severity: '', risk_code: '', source: '', agent: props.initialAgent, since: '', until: '', disposition: '' }; closeDetail(); detailOpen.value = false; configGeneration++; configOpen.value = false; saving.value = false; configLoading.value = false; page.value = 1; items.value = []; summary.value = null; refresh() }, { immediate: true })
onBeforeUnmount(() => { clearTimer(); generation++; detailGeneration++; configGeneration++; historyGeneration++ })
</script>

<style scoped>
.risk-panel { overflow: auto; min-height: 0; padding-bottom: 16px; }
.risk-disposition { padding: 20px 0; border-block: 1px solid #eee; margin: 20px 0; }
.risk-history { margin-top: 24px; }.risk-history h4 { margin-bottom: 12px; }.reason-count { text-align: right; margin-top: 4px; }.disposition-actions { margin-top: 4px; }
.risk-progress { margin-left: auto; color: #667085; font-size: 12px; }.risk-summary .ant-tag { margin: 0; }.disposition-reason { white-space: pre-wrap; overflow-wrap: anywhere; }
.risk-toolbar, .risk-summary, .risk-filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 14px; }
.risk-toolbar h3 { margin: 0; margin-right: auto; }
.risk-filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); align-items: end; }
.risk-filters label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.risk-date-range { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; grid-column: span 2; }
.risk-date input { box-sizing: border-box; width: 100%; height: 32px; padding: 4px 11px; border: 1px solid #d9d9d9; border-radius: 6px; }
small { display: block; color: #667085; white-space: normal; overflow-wrap: anywhere; }
.risk-meta { display: grid; grid-template-columns: minmax(100px, 150px) minmax(0, 1fr); gap: 8px 12px; }.risk-meta dt { color: #667085; }.risk-meta dd { margin: 0; overflow-wrap: anywhere; }
.risk-evidence { border-top: 1px solid #e5e7eb; padding: 12px 0; } pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 280px; overflow: auto; padding: 12px; background: #f6f8fa; } code { overflow-wrap: anywhere; } .ant-alert { margin-bottom: 12px; }
@media (max-width: 540px) { .risk-filters { grid-template-columns: 1fr; }.risk-date-range { grid-column: span 1; grid-template-columns: 1fr; }.risk-progress { margin-left: 0; }.risk-meta { grid-template-columns: 1fr; gap: 4px; }.risk-meta dd { margin-bottom: 10px; } }
</style>
