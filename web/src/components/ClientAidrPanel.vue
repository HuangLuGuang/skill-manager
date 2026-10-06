<template>
  <section class="aidr-panel">
    <div class="aidr-heading"><h3>{{ t(view === 'collection' ? 'agentRuntimeGovernance.detail.logCollection' : 'agentRuntimeGovernance.detail.tools') }}</h3><a-button :loading="loading" :disabled="loading" @click="refresh">{{ t('aidr.refresh') }}</a-button></div>
    <p v-if="view === 'operations'" class="aidr-muted">{{ t('aidr.logSource') }}</p>
    <a-alert v-if="error" type="error" :message="error" :description="t('agentRuntimeGovernance.detail.readFailed')" show-icon />
    <a-alert v-if="view === 'operations' && state && channelHealth.state !== 'running'" :type="channelHealth.severity || 'info'" show-icon :message="stateLabel">
      <template v-if="channelHealth.state === 'not_configured' && can('clients:update')" #action><a-button type="link" @click="$emit('policy')">{{ t('aidr.logSetup.action') }}</a-button></template>
    </a-alert>
    <a-alert v-if="healthCodes.length" type="warning" :message="t('aidr.coverageWarning')" show-icon><template #description><code v-for="code in healthCodes" :key="code"> {{ reasonLabel(code) }}</code></template></a-alert>
    <details class="aidr-diagnostics"><summary>{{ t('agentRuntimeGovernance.presentation.auditDiagnostics') }}<span v-if="operations.coverage_gap_sources"> · {{ t('agentRuntimeGovernance.presentation.historicalGaps', { count: operations.coverage_gap_sources }) }}</span></summary>
      <p>{{ t('aidr.logEvidence') }}</p>
      <p v-if="view === 'operations'">{{ channelPolicyNote }}</p>
      <p v-if="channelHealth.state === 'not_configured'">{{ t('aidr.logSetup.help') }}</p>
      <p v-if="operations.coverage_gap_sources">{{ t('aidr.historicalCoverage') }}</p>
      <template v-if="view === 'operations'"><p>{{ t('aidr.autoFilters') }}</p><p>{{ t('aidr.recentNote') }}</p></template>
      <a-button v-if="view === 'collection' && channelHealth.state === 'not_configured' && can('clients:update')" type="link" @click="$emit('policy')">{{ t('aidr.logSetup.action') }}</a-button>
    </details>
    <template v-if="state">
      <template v-if="view === 'collection'">
      <div class="aidr-summary"><a-tag :color="channelHealth.severity === 'warning' ? 'orange' : 'default'">{{ stateLabel }}</a-tag><span>{{ t('aidr.lastSeen') }}: {{ timestamp(state.last_seen_at) }}</span></div>
      <p class="aidr-muted">{{ channelPolicyNote }}</p>
      <p>{{ t('aidr.channelObservation') }}: {{ state.log_channel?.report ? t('agentRuntimeGovernance.channelStates.' + state.log_channel.report.state) : t('aidr.unknown') }} <span v-if="state.log_channel?.stale">· {{ t('aidr.snapshotNote') }}</span></p>
      <p v-if="state.health?.audit_policy">{{ t('aidr.redactionSettings.applied') }}: {{ t(state.health.audit_policy.policy.enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') }} / {{ state.health.audit_policy.policy.version }} · {{ timestamp(state.health.audit_policy.refreshed_at) }} <span v-if="state.health.audit_policy.code !== 'aidr_policy_applied'">{{ t('aidr.redactionSettings.cached') }}</span></p>
      <p v-else>{{ t('aidr.redactionSettings.unsupported') }}</p>
      <p>{{ t('aidr.content.appliedScope') }}: {{ scopeLabel(state.health?.audit_policy?.policy?.capture) }}</p>
      <p>{{ t('aidr.lifecycle.actual') }}: {{ lifecycleLabel(state.health?.audit_policy?.policy?.lifecycle) }}</p>
      <p><router-link v-if="can('settings:view') && pageAllowed('/clients')" :to="{ path: '/clients', query: { policy: 'audit', client: clientId } }">{{ t('aidr.policyNavigation.openDevice') }}</router-link></p>
      <details class="aidr-diagnostics"><summary>{{ t('aidr.collectionDiagnostics') }}</summary>
      <p>{{ t('aidr.redactionSettings.target') }}: {{ state.audit_redaction ? t(state.audit_redaction.enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') + ' / ' + state.audit_redaction.version : t('aidr.redactionSettings.unknown') }}</p>
      <p v-if="state.retention">{{ t('aidr.lifecycle.expired', state.retention) }}</p>
      <div v-for="item in state.health?.discovery || []" :key="`progress:${item.agent}`" class="aidr-summary"><strong>{{ item.agent }} · {{ t('aidr.discovery') }}: {{ statusLabel(item.status) }}</strong><span v-if="item.progress">{{ t('aidr.knownSources') }}: {{ item.progress.known_sources }} · {{ t('aidr.pendingSources') }}: {{ item.progress.pending_sources }} · {{ t('aidr.pendingDirectories') }}: {{ item.progress.pending_directories }} · {{ t('aidr.scannedEntries') }}: {{ item.progress.scanned_entries }}</span></div>
      <p class="aidr-muted">{{ t('aidr.healthSeparation') }}</p>
      <div class="aidr-summary"><strong>{{ t('aidr.parserSupport') }}</strong><span v-if="!(state.capabilities || []).length">{{ t('aidr.unknown') }}</span><a-tag v-for="cap in state.capabilities || []" :key="`health:${cap.agent}:${cap.version}`">{{ cap.agent }} {{ cap.version }} · {{ cap.parser_status ? statusLabel(cap.parser_status) : t('aidr.unknown') }} · {{ cap.parser_version || t('aidr.unknown') }}</a-tag></div>
      <p>{{ t('aidr.parserReportNote') }} {{ timestamp(state.last_seen_at) }}</p>
      </details>
      <details v-if="canUpdate"><summary>{{ t('aidr.configure') }}</summary><p class="aidr-muted">{{ t('aidr.setup') }}</p><a-button :loading="saving" :disabled="saving || !!error" @click="save">{{ state.enabled ? t('aidr.disable') : t('aidr.enable') }}</a-button></details>
      </template>
      <template v-if="view === 'operations'">
      <form class="aidr-filters" @submit.prevent="applyFilters">
        <label>{{ t('aidr.agent') }}<a-select v-model:value="draft.agent" :aria-label="t('aidr.agent')"><a-select-option value="">{{ t('aidr.all') }}</a-select-option><a-select-option value="claude">Claude</a-select-option><a-select-option value="codex">Codex</a-select-option></a-select></label>
        <label>{{ t('aidr.session') }}<a-input v-model:value="draft.session" :aria-label="t('aidr.session')" :placeholder="t('aidr.exactMatch')" :maxlength="256" /></label>
        <label>{{ t('aidr.tool') }}<a-input v-model:value="draft.tool" :aria-label="t('aidr.tool')" :placeholder="t('aidr.exactMatch')" :maxlength="256" /></label>
        <label>{{ t('aidr.outcome') }}<a-select v-model:value="draft.result" :aria-label="t('aidr.outcome')"><a-select-option value="">{{ t('aidr.all') }}</a-select-option><a-select-option v-for="value in resultStatuses" :key="value" :value="value">{{ t(`aidr.results.${value}`) }}</a-select-option></a-select></label>
        <label>{{ t('aidr.since') }}<input v-model="draft.since" type="datetime-local" :aria-label="t('aidr.since')" /></label>
        <label>{{ t('aidr.until') }}<input v-model="draft.until" type="datetime-local" :aria-label="t('aidr.until')" /></label>
        <a-button @click="resetFilters">{{ t('aidr.clear') }}</a-button>
      </form>
      <a-table :columns="columns" :data-source="operations.items" row-key="operation_key" :pagination="false" :scroll="{ x: 880 }" size="small" :locale="{ emptyText: t('aidr.emptyOperations') }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'observed'">{{ timestamp(record.latest_at) }}</template>
          <template v-else-if="column.key === 'agent'"><strong>{{ record.agent }}</strong><div class="aidr-muted aidr-id">{{ record.session_id || t('aidr.unknown') }}</div></template>
          <template v-else-if="column.key === 'operation'"><strong>{{ summary(record) }}</strong><div class="aidr-muted">{{ record.tool || t('aidr.unknown') }}</div><div v-for="(action, index) in actions(record)" :key="index" class="aidr-preview"><code v-if="action.command">{{ action.command }}</code><span v-else-if="record.call?.behavior?.category === 'wrapper'">{{ t(`aidr.categories.${action.category}`) }}</span></div><a-tag v-if="!record.call?.behavior">{{ t('aidr.insufficient') }}</a-tag></template>
          <template v-else-if="column.key === 'target'"><div v-for="(target, index) in targets(record)" :key="index" class="aidr-id">{{ target.value }}</div><span v-if="!targets(record).length">{{ t('aidr.notProvided') }}</span></template>
          <template v-else-if="column.key === 'outcome'"><a-tag :color="record.status === 'reported_error' ? 'orange' : 'default'">{{ t(`aidr.results.${record.status}`) }}</a-tag><div v-if="record.result?.behavior?.exit_code != null && record.status !== 'reported_success'">{{ t('aidr.exitCode') }}: {{ record.result.behavior.exit_code }}</div></template>
          <template v-else-if="column.key === 'details'"><a-button type="link" @click="showDetail(record)">{{ t('aidr.details') }}</a-button></template>
        </template>
      </a-table>
      <div v-if="cursor || operations.has_more" class="aidr-actions"><a-button :disabled="loading || !cursor" @click="page('')">{{ t('aidr.first') }}</a-button><a-button :disabled="loading || !operations.has_more" @click="page(operations.next_cursor)">{{ t('aidr.next') }}</a-button></div>
      <i18n-t v-if="!loading && !error && !operations.items.length" keypath="agentRuntimeGovernance.detail.noLogOperations" tag="p" class="aidr-muted">
        <template #hooks><a-button type="link" @click="$emit('hooks')">{{ t('agentRuntimeGovernance.detail.auditViews.hooks') }}</a-button></template>
      </i18n-t>
      </template>
      <details v-if="view === 'collection'" class="aidr-diagnostics" @toggle="toggleSources"><summary>{{ t('aidr.diagnostics') }}</summary>
        <p>{{ t('aidr.snapshotNote') }}</p><p>{{ t('aidr.queued') }}: {{ state.health?.queued_records ?? '—' }} · {{ t('aidr.retained') }}: {{ state.health?.logical_events ?? '—' }} · {{ t('aidr.expired') }}: {{ state.health?.evicted_event_payloads ?? '—' }}</p><p>{{ t('aidr.historyNote') }}</p>
        <h4>{{ t('aidr.sourceCapabilityReport') }}</h4><a-tag v-for="cap in state.capabilities || []" :key="`${cap.agent}:${cap.version}`">{{ cap.agent }} {{ cap.version }} · {{ statusLabel(cap.status) }}</a-tag>
        <h4>{{ t('aidr.discovery') }}</h4><div v-for="item in state.health?.discovery || []" :key="item.agent">{{ item.agent }} · {{ statusLabel(item.status) }} <code v-for="code in item.reason_codes" :key="code">{{ reasonLabel(code) }}</code></div>
        <h4>{{ t('aidr.sources') }}</h4><p v-if="!sources.items.length">{{ t('aidr.emptySources') }}</p>
        <div v-for="item in sources.items" :key="item.id" class="aidr-source"><strong>{{ statusLabel(item.coverage.status) }}</strong><code>{{ item.source_id }}</code><div>{{ t('aidr.revision') }} {{ item.revision }}</div><code v-for="reason in item.coverage.reason_codes" :key="reason">{{ reasonLabel(reason) }}</code><details><summary>{{ t('aidr.projectionJSON') }}</summary><pre>{{ JSON.stringify(item, null, 2) }}</pre></details></div>
        <div class="aidr-actions"><a-button :disabled="loading || sourceAfter === '0'" @click="pageSources('0')">{{ t('aidr.first') }}</a-button><a-button :disabled="loading || !sources.has_more" @click="pageSources(sources.next_after)">{{ t('aidr.next') }}</a-button></div>
      </details>
    </template>
    <a-modal v-model:open="detailOpen" :title="t('aidr.detailTitle')" :footer="null" width="min(960px, 94vw)">
      <article v-if="detail" class="audit-detail">
        <header class="audit-detail-header"><h3>{{ detail.tool || summary(detail) }}</h3><a-tag>{{ t('aidr.results.' + detail.status) }}</a-tag></header>
        <p class="aidr-muted">{{ detail.agent }} · {{ t('aidr.detail.logSource') }} · {{ timestamp(detail.call?.observed_at || detail.result?.observed_at) }}</p>
        <p v-if="detail.result?.behavior?.exit_code != null && detail.status !== 'reported_success'">{{ t('aidr.exitCode') }}: <strong>{{ detail.result.behavior.exit_code }}</strong></p>
        <a-alert v-if="detail.call && !detail.call.behavior" type="info" :message="t('aidr.legacyNote')" />
        <a-alert v-if="detail.history_expired" type="info" :message="t('aidr.lifecycle.historyExpired')" />
        <AidrAuditActions :actions="actions(detail)" :tool="detail.tool" :body-omitted="detail.call?.behavior?.body_omitted" :body-captured="detail.call?.behavior?.contents?.some(item => item.kind === 'command_body')" />
        <p v-if="detail.call?.behavior?.category === 'wrapper'" class="aidr-muted">{{ t('aidr.detail.wrapper') }}</p>
        <p v-if="detail.call?.behavior?.truncated || detail.result?.behavior?.truncated || detail.evidence_truncated" class="aidr-muted">{{ t('aidr.truncated') }}</p>
        <template v-if="detailOpen"><AidrAuditContent v-for="event in [detail.call, detail.result].filter(Boolean)" :key="event.logical_event_id" :client-id="clientId" source="log" :record-id="event.logical_event_id" :evidence="event" /></template>
        <details v-if="detail.hook_evidence?.items?.length" class="aidr-diagnostics">
          <summary>{{ t('aidr.detail.relatedHooks') }} · {{ detail.hook_evidence.items.length }}</summary>
          <p>{{ t('aidr.correlation.codes.' + detail.hook_evidence.code) }}</p>
          <p class="aidr-muted">{{ t('aidr.detail.relatedNote') }}</p>
          <div v-for="item in detail.hook_evidence.items" :key="item.id" class="aidr-source">
            <strong>{{ item.hook_event }}</strong> · {{ timestamp(item.received_at) }}
            <p v-if="['PostToolUse', 'PostToolUseFailure'].includes(item.hook_event)">{{ t('aidr.hooks.events.results.' + item.status) }}<span v-if="item.exit_code != null"> · {{ t('aidr.exitCode') }}: {{ item.exit_code }}</span></p>
            <p>{{ t('aidr.detail.recordId') }}: {{ item.id }}</p>
          </div>
        </details>
        <details class="aidr-diagnostics">
          <summary>{{ t('aidr.detail.recordInfo') }}</summary>
          <p>{{ t('aidr.session') }}: <code>{{ detail.session_id }}</code></p>
          <p v-if="detail.call?.turn_id || detail.result?.turn_id">{{ t('aidr.turn') }}: <code>{{ detail.call?.turn_id || detail.result?.turn_id }}</code></p>
          <p v-if="detail.call?.native_call_id || detail.result?.native_call_id">{{ t('aidr.call') }}: <code>{{ detail.call?.native_call_id || detail.result?.native_call_id }}</code></p>
          <p v-if="detail.log_elapsed_ms != null">{{ t('aidr.logElapsed') }}: {{ detail.log_elapsed_ms }} ms</p>
          <p v-if="detail.result?.behavior?.result_basis?.length">{{ t('aidr.resultBasis') }}: {{ detail.result.behavior.result_basis.map(value => t('aidr.bases.' + value)).join(' · ') }}</p>
          <div v-for="event in [detail.call, detail.result].filter(Boolean)" :key="event.logical_event_id" class="aidr-source">
            <h4>{{ event.kind === 'tool_call' ? t('aidr.started') : t('aidr.ended') }} · {{ timestamp(event.observed_at) }}</h4>
            <p v-if="event.behavior?.policy">{{ t('aidr.redactionSettings.event') }}: {{ event.behavior.policy.version }} · {{ t(event.behavior.policy.enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') }}</p>
            <p>{{ t('aidr.sourceIdentity') }}: <code>{{ event.source_id }}</code></p>
            <p>{{ t('aidr.sourcePosition') }}: {{ event.record_offset }} / {{ event.block }}</p>
          </div>
          <p v-for="reason in uncertainties(detail)" :key="reason">{{ t('aidr.uncertainties.' + reason) }}</p>
        </details>
      </article>
    </a-modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Translation as I18nT, useI18n } from 'vue-i18n'
import { can, pageAllowed } from '../access'
import AidrAuditContent from './AidrAuditContent.vue'
import AidrAuditActions from './AidrAuditActions.vue'
import { configureClientAidr, getClientAidrOperations, getClientAidrSources, getClientAidrStatus } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, view: { type: String, default: 'operations' } })
defineEmits(['hooks', 'policy'])
const { t, locale } = useI18n()
const scopeLabel = scope => scope ? ['prompt', 'model_response', 'tool_output', 'file_body', 'command_body'].filter(kind => scope[kind]).map(kind => t('aidr.content.kinds.' + kind)).join(' · ') || t('aidr.content.none') : t('aidr.redactionSettings.unknown')
const lifecycleLabel = value => value ? t(value.enabled ? 'aidr.lifecycle.enabled' : 'aidr.lifecycle.disabled') + ' · ' + t('aidr.lifecycle.days', { days: value.retention_days }) : t('aidr.lifecycle.legacy')
const loading = ref(false), saving = ref(false), error = ref(''), state = ref(null)
const emptyFilters = () => ({ agent: '', session: '', tool: '', result: '', since: '', until: '' })
const draft = ref(emptyFilters()), filters = ref(emptyFilters()), cursor = ref(''), sourceAfter = ref('0')
const operations = ref({ items: [], has_more: false }), sources = ref({ items: [], has_more: false })
const detailOpen = ref(false), detail = ref(null)
const resultStatuses = ['reported_success', 'reported_complete', 'reported_error', 'reported_cancelled', 'unknown', 'missing_result', 'missing_call', 'conflicting_evidence']
const canUpdate = computed(() => can('clients:update'))
let sequence = 0, filterRevision = 0, refreshQueued = false, filterTimer
const sourcesOpen = ref(false)
const channelHealth = computed(() => state.value?.log_channel?.health || { state: 'policy_unknown', severity: 'info' })
const stateLabel = computed(() => t('aidr.channelHealth.' + channelHealth.value.state))
const channelPolicyNote = computed(() => t('aidr.channelPolicyNote', { targetVersion: state.value?.log_channel?.target_version || t('aidr.unknown'), observedVersion: state.value?.log_channel?.report?.policy_version || t('aidr.unknown'), time: timestamp(state.value?.last_seen_at) }))
const healthCodes = computed(() => state.value?.log_channel?.target_enabled !== true || !state.value?.online || state.value?.log_channel?.report?.policy_version !== state.value?.log_channel?.target_version ? [] : [...new Set([...['intake_code', 'upload_code', 'recovery_code', 'capacity_warning'].map(key => state.value?.health?.[key]).filter(Boolean), ...(state.value?.health?.discovery || []).flatMap(item => item.reason_codes || [])])])
const reasonKeys = { aidr_audit_collection_disabled: 'collectionDisabled', aidr_log_discovery_budget: 'budget', aidr_log_discovery_pending: 'pending', aidr_log_discovery_capacity: 'capacity', aidr_log_schema_unsupported: 'format', aidr_log_record_too_large: 'large', aidr_log_version_unverified: 'version', aidr_upload_reporting_paused: 'reportingPaused', aidr_upload_auth_rejected: 'credentialRejected', aidr_log_call_capacity: 'callCapacity', aidr_log_call_conflict: 'callConflict', aidr_log_call_unresolved: 'callUnresolved', aidr_log_optional_record_skipped: 'optionalSkipped', aidr_log_context_invalidated: 'contextInvalidated', aidr_log_timestamp_future: 'timestampFuture', aidr_audit_history_retention: 'historyRetired', aidr_store_capacity_warning: 'capacityWarning', aidr_store_capacity: 'storeCapacity' }
const reasonLabel = code => reasonKeys[code] ? `${t('aidr.diagnosticReasons.' + reasonKeys[code])} (${code})` : code
const statusKeys = { complete: 'aidr.complete', partial: 'aidr.partial', unavailable: 'aidr.unavailable', available: 'aidr.available', unverified: 'aidr.unverified' }
const statusLabel = value => t(statusKeys[value] || 'aidr.unknown')
const columns = computed(() => ['observed', 'agent', 'operation', 'target', 'outcome', 'details'].map(key => ({ key, title: t(`aidr.${key}`), width: key === 'operation' ? 290 : key === 'details' ? 90 : 160 })))
const actions = row => row.call?.behavior?.actions || []
const targets = row => actions(row).flatMap(action => action.targets || [])
const summary = row => t(`aidr.categories.${row.call?.behavior?.category || 'unknown'}`)
const uncertainties = row => [...new Set([...(row.call?.behavior?.uncertainty || []), ...(row.result?.behavior?.uncertainty || [])])]
function timestamp(value) {
  if (!value) return '—'
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }).format(date)
}
function showDetail(value) { detail.value = value; detailOpen.value = true }
async function refresh() {
  if (loading.value) { refreshQueued = true; return }
  const current = ++sequence, id = props.clientId, revision = filterRevision
  loading.value = true; error.value = ''
  try {
    const [status, rows, coverage] = await Promise.all([getClientAidrStatus(id), props.view === 'operations' ? getClientAidrOperations(id, { ...filters.value, cursor: cursor.value, limit: 20 }) : Promise.resolve(operations.value), sourcesOpen.value ? getClientAidrSources(id, { after: sourceAfter.value, limit: 20 }) : Promise.resolve(sources.value)])
    if (current !== sequence || revision !== filterRevision) return
    state.value = status; operations.value = rows; sources.value = coverage
    if (detailOpen.value && detail.value) { const updated = rows.items.find(row => row.operation_key === detail.value.operation_key); if (updated) detail.value = updated }
  } catch (err) { if (current === sequence && revision === filterRevision) { error.value = t('aidr.loadingError') + (err.apiErrorCode ? ` (${err.apiErrorCode})` : '') } }
  finally { if (current === sequence) { loading.value = false; if (refreshQueued) { refreshQueued = false; refresh() } } }
}
async function save() {
  if (saving.value || error.value || !state.value || props.view !== 'collection' || !canUpdate.value) return
  const id = props.clientId
  saving.value = true
  try { await configureClientAidr(id, { enabled: !state.value?.enabled }); if (props.clientId === id) await refresh() }
  catch (err) { if (props.clientId === id) error.value = err.response?.data?.detail || t('aidr.saveError') }
  finally { saving.value = false }
}
function applyFilters() {
  clearTimeout(filterTimer)
  const next = { ...draft.value }
  for (const key of ['since', 'until']) {
    if (!next[key]) continue
    const date = new Date(next[key])
    if (Number.isNaN(date.valueOf())) return
    next[key] = date.toISOString()
  }
  filters.value = next; filterRevision++; cursor.value = ''; refresh()
}
function resetFilters() { draft.value = emptyFilters() }
function page(value) { cursor.value = value; refresh() }
function toggleSources(event) { sourcesOpen.value = event.target.open; if (sourcesOpen.value) refresh() }
function pageSources(value) { sourceAfter.value = value; refresh() }
watch(() => [draft.value.agent, draft.value.result, draft.value.since, draft.value.until, draft.value.session, draft.value.tool], (value, previous) => {
  clearTimeout(filterTimer)
  if (props.view !== 'operations') return
  if (value.slice(0, 4).some((item, index) => item !== previous[index])) applyFilters()
  else filterTimer = setTimeout(applyFilters, 250)
})
watch(() => props.clientId, () => { sequence++; refreshQueued = false; clearTimeout(filterTimer); loading.value = false; state.value = null; cursor.value = ''; sourceAfter.value = '0'; draft.value = emptyFilters(); filters.value = emptyFilters(); operations.value = { items: [] }; sources.value = { items: [] }; detailOpen.value = false; sourcesOpen.value = false; refresh() }, { immediate: true })
const timer = setInterval(() => { if (!document.hidden && !saving.value) refresh() }, 10000)
onBeforeUnmount(() => { sequence++; clearInterval(timer); clearTimeout(filterTimer) })
</script>

<style scoped>
.audit-detail { overflow-wrap: anywhere; }
.audit-detail-header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
.audit-detail-header h3 { margin: 0; font-size: 20px; }

.aidr-panel { margin: 12px 0 24px; }
.aidr-heading, .aidr-summary, .aidr-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.aidr-heading { justify-content: space-between; } .aidr-heading h3 { margin: 0; }
.aidr-muted { color: #627480; font-size: 13px; overflow-wrap: anywhere; }
.aidr-summary, .aidr-actions, details { margin: 12px 0; }
summary { cursor: pointer; }
.aidr-diagnostics { border-top: 1px solid #e5ebee; border-bottom: 1px solid #e5ebee; padding: 14px 0; }
.aidr-diagnostics > summary { color: #526873; font-weight: 500; }
.aidr-filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin: 18px 0; }
.aidr-filters label { display: flex; flex-direction: column; gap: 4px; width: 180px; }
.aidr-filters input { max-width: 100%; min-height: 30px; border: 1px solid #d9d9d9; border-radius: 6px; }
.aidr-id, code { overflow-wrap: anywhere; word-break: break-word; }
.aidr-preview { max-height: 5em; overflow: auto; white-space: pre-wrap; margin: 6px 0; }
.aidr-source { padding: 12px 0; border-bottom: 1px solid #edf0f2; overflow-wrap: anywhere; }
.aidr-source code { display: inline-block; max-width: 100%; margin: 4px 0; }
pre { max-height: 45vh; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.aidr-panel :deep(.ant-tag) { white-space: normal; }
@media (max-width: 600px) { .aidr-panel { padding: 12px; } .aidr-filters label { width: 100%; } }
</style>
