<template>
  <section class="collection-status">
    <header class="collection-heading"><div><h2>{{ tr('title') }}</h2><p>{{ attentionCount ? tr('channelsNeedCheck', { count: attentionCount }) : tr('summary') }}</p></div><a-button :loading="loading && !backgroundRefresh" :disabled="loading" @click="load()"><ReloadOutlined /> {{ tr('refresh') }}</a-button></header>
    <nav class="collection-channels" :aria-label="tr('title')"><button v-for="item in channels" :key="item.id" :class="{ selected: channel === item.id }" :aria-pressed="channel === item.id" @click="changeChannel(item.id)"><component :is="item.icon" /><span><strong>{{ tr(item.id) }}</strong><small>{{ channelSummary(item.id) }}</small></span></button></nav>
    <div ref="scrollArea" class="collection-scroll" @scroll.passive="lastScrollAt = Date.now()" tabindex="0" :aria-label="tr('detail')" :aria-busy="selectedPending">
      <section v-if="issues.length" class="collection-issues" :aria-label="tr('checkHeading')">
        <strong>{{ tr('checkHeading') }}</strong>
        <button v-for="issue in issues" :key="issue.channel" @click="changeChannel(issue.channel, issue.sourceId)">
          <span>{{ tr(issue.channel) }} · {{ label(issue.state) }}</span><RightOutlined />
          <small>{{ tr('updated') }}：{{ stamp(issue.observed) }}</small>
          <p>{{ issue.hint }}</p>
        </button>
      </section>
      <a-alert v-if="errors.length" type="warning" show-icon :message="tr('partialRead')" />
      <div v-if="!selectedReady" class="collection-loading" role="status"><LoadingOutlined spin /><strong>{{ tr('loading') }}</strong><p>{{ tr('loadingHint') }}</p><a-skeleton active :paragraph="{ rows: 4 }" /></div>
      <div v-else-if="selectedPending && !backgroundRefresh" class="collection-refreshing" role="status"><LoadingOutlined spin />{{ tr('refreshing') }}</div>
      <div v-if="selectedReady" class="collection-grid">
        <section ref="sourcePanel" class="source-panel">
          <h3>{{ tr('sources') }}</h3><p class="muted source-hint">{{ tr('sourceHint') }}</p>
          <div class="source-list"><div v-for="group in sourceGroups" :key="group.id" class="source-group"><h4 v-if="group.entries.length > 1" class="source-group-title"><AgentProductLogo :product-id="group.id" />{{ group.name }}</h4><button v-for="row in group.entries" :key="row.id" class="source-row" :class="[{ selected: selectedId === row.id }, tone(row.state)]" :aria-pressed="selectedId === row.id" @click="selectSource(row.id)"><span class="source-icon"><component v-if="channel === 'system'" :is="row.id === 'network' ? ApiOutlined : DesktopOutlined" /><AgentProductLogo v-else :product-id="group.id" /></span><span class="source-name"><strong>{{ group.entries.length > 1 ? entryLabel(row.entry) : group.name }}</strong><small v-if="group.entries.length === 1 && row.entry">{{ entryLabel(row.entry) }}</small></span><span class="source-result"><strong><CheckCircleFilled v-if="row.state === 'received'" /><ExclamationCircleOutlined v-else-if="tone(row.state) === 'warning'" /><ClockCircleOutlined v-else />{{ label(row.state) }}</strong><small>{{ row.arrival ? stamp(row.arrival) : row.observed ? stamp(row.observed) : tr('unknown') }}</small></span><RightOutlined class="chevron" /></button></div></div>
          <a-empty v-if="!rows.length" :description="tr('empty')" />
          <div class="upload-summary"><CloudUploadOutlined /><div><strong>{{ !reportFresh ? label('transport_offline') : currentChannel.report?.last_ack_at ? tr('acknowledged') : tr('noAck') }}</strong><small>{{ reportFresh && currentChannel.report?.queued_records != null ? tr('pending', { count: currentChannel.report.queued_records }) : tr('pendingUnknown') }}</small><small v-if="reportFresh && currentChannel.report?.last_ack_at">{{ stamp(currentChannel.report.last_ack_at) }}</small></div><a-button type="link" @click="openActivity">{{ tr(channel === 'system' ? 'systemActivity' : 'activity') }}<RightOutlined /></a-button></div><p class="small-note">{{ tr('uploadNote') }}</p>
          <details v-if="channel !== 'system' && disabledProducts.length" class="disclosure"><summary>{{ tr('disabled') }} · {{ disabledProducts.length }}</summary><p class="muted">{{ tr('disabledHint') }}</p><div v-for="product in disabledProducts" :key="product.id" class="disabled-product"><span class="disabled-product-name"><span class="disabled-product-logo"><AgentProductLogo :product-id="product.id" /></span>{{ product.name }}</span><small>{{ label('not_requested') }}</small></div><a-button type="link" @click="emit('plugins')">{{ tr('plugins') }}</a-button></details>
          <details class="disclosure"><summary>{{ tr('diagnostics') }}</summary><p class="muted">{{ tr('diagnosticsHint') }}</p><dl><div><dt>{{ tr('updated') }}</dt><dd>{{ stamp(currentChannel.report?.reported_at) }}</dd></div><div><dt>{{ tr('versions') }}</dt><dd>{{ currentChannel.target_version || tr('unknown') }} / {{ currentChannel.report?.policy_version || tr('unknown') }}</dd></div><div><dt>{{ tr('ackTime') }}</dt><dd>{{ stamp(currentChannel.report?.last_ack_at) }}</dd></div></dl><code>{{ currentChannel.report?.code }}</code><code v-if="currentChannel.report?.transport_code">{{ currentChannel.report.transport_code }}</code><code v-for="code in currentChannel.report?.coverage_codes || []" :key="code">{{ code }}</code></details>
        </section>
        <section v-if="selected" ref="inspector" class="source-inspector" :class="tone(selected.state)" aria-live="polite">
          <a-button type="link" class="mobile-back" @click="sourcePanel?.scrollIntoView({ block: 'start' })">{{ tr('back') }}</a-button>
          <header><span class="source-icon"><component v-if="channel === 'system'" :is="selected.id === 'network' ? ApiOutlined : DesktopOutlined" /><AgentProductLogo v-else :product-id="selected.id" /></span><div><h3>{{ selectedGroup?.name }} · {{ label(selected.state) }}</h3><small v-if="selected.entry">{{ entryLabel(selected.entry) }}</small><p>{{ description }}</p></div></header>
          <div class="inspector-body">
            <div v-if="logReasons.length" class="log-reasons"><h4>{{ tr('logReasons') }}</h4><ul><li v-for="reason in logReasons" :key="reason">{{ tr('logReason.' + reason) }}</li></ul></div>
            <template v-if="channel === 'logs'"><template v-for="(item, index) in selected.discovery || []" :key="index"><p v-if="item.progress?.historical_missing" class="small-note">{{ t('clientOverview.historicalMissing', { count: item.progress?.historical_missing }) }} {{ t('clientOverview.historicalBoundary') }}</p><p v-if="item.progress?.unread_missing">{{ t('clientOverview.missingUnread', { count: item.progress?.unread_missing }) }}</p><p v-if="item.progress?.missing_directories">{{ t('clientOverview.missingDirectories', { count: item.progress?.missing_directories }) }}</p></template></template>
            <h4>{{ tr('chain') }}</h4><dl class="evidence-list"><div><dt>{{ tr('updated') }}</dt><dd>{{ stamp(selected.observed) }}</dd></div><div><dt>{{ tr('policyApplied') }}</dt><dd>{{ currentChannel.applied ? tr('policyApplied') : tr('policyPending') }}</dd></div>
              <template v-if="channel === 'logs'"><div><dt>{{ tr('discovery') }}</dt><dd>{{ discoveryLabel }}</dd></div><div><dt>{{ tr('event') }}</dt><dd>{{ selected.arrival ? stamp(selected.arrival) : tr(selected.receiptsReported ? 'noArrival' : 'unknown') }}</dd></div></template>
              <template v-else-if="channel === 'hooks'"><div><dt>{{ tr('installation') }}</dt><dd>{{ connectionLabel('installation', selected.connection?.installation) }}</dd></div><div><dt>{{ tr('authorization') }}</dt><dd>{{ connectionLabel('authorization', selected.connection?.authorization) }}</dd></div><div><dt>{{ tr('event') }}</dt><dd>{{ selected.arrival ? stamp(selected.arrival) : tr('noArrival') }}</dd></div></template>
              <template v-else><div><dt>{{ tr('coverage') }}</dt><dd>{{ tr('systemScope') }}</dd></div><div><dt>{{ tr('versions') }}</dt><dd>{{ system?.target_revision || '—' }} / {{ system?.reported_revision || '—' }}</dd></div></template>
            </dl>
            <p v-if="selected.count != null" class="small-note">{{ tr('receivedCounts', { count: selected.count }) }}</p><p v-if="channel !== 'system'" class="small-note">{{ tr('scopeWindow') }}</p>
            <p v-if="selected.id === 'network'" class="scope-box">{{ t('aidr.enforcement.network.boundary') }}</p>
            <div class="next-action"><h4>{{ tr('next') }}</h4><p>{{ guidance }}</p><div class="desktop-path"><DesktopOutlined /><span>{{ tr(channel === 'system' ? 'desktopSystem' : 'desktop') }}</span></div><div class="action-buttons"><a-button type="primary" @click="guideOpen = true">{{ tr('guide') }}<RightOutlined /></a-button><a-button v-if="can('clients:update')" @click="emit('policy')">{{ tr('policy') }}</a-button><a-button v-if="channel === 'hooks'" @click="emit('plugins')">{{ tr('plugins') }}</a-button></div><a-button type="link" @click="openActivity">{{ tr(channel === 'system' ? 'systemActivity' : 'activity') }}<RightOutlined /></a-button></div>
            <details v-if="channel === 'logs'" class="disclosure"><summary>{{ tr('technical') }}</summary><p>{{ tr('defaultRoots') }}</p><code v-for="root in selected.product?.roots || []" :key="root">~/{{ root }}</code><p class="small-note">{{ tr('rootsNote') }}</p><div v-for="item in selected.discovery" :key="item.source_id || item.agent"><code>{{ item.source_id }}</code><code v-for="code in item.reason_codes || []" :key="code">{{ code }}</code></div></details>
          </div>
        </section>
        <section v-else class="empty-inspector"><InfoCircleOutlined /><h3>{{ label(baseState(channel)) }}</h3><p>{{ tr('checkPolicy') }}</p><a-button v-if="can('clients:update')" @click="emit('policy')">{{ tr('policy') }}</a-button></section>
      </div>
      <footer v-if="selectedReady" class="small-note">{{ tr('receiptNote') }}</footer>
    </div>
    <a-modal v-model:open="guideOpen" :title="tr('guide')" :footer="null" width="min(600px, 94vw)"><p>{{ tr('guideIntro') }}</p><ol class="guide-steps"><li v-for="step in guideSteps" :key="step">{{ step }}</li></ol><p class="muted">{{ tr('noAutoAction') }}</p><a-button @click="guideOpen = false">{{ tr('close') }}</a-button></a-modal>
  </section>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiOutlined, CheckCircleFilled, ClockCircleOutlined, CloudUploadOutlined, DesktopOutlined, ExclamationCircleOutlined, FileTextOutlined, InfoCircleOutlined, LinkOutlined, LoadingOutlined, MessageOutlined, ReloadOutlined, RightOutlined } from '@ant-design/icons-vue'
import { getClientAidrStatus, getClientRuntimeGovernance, getEnforcement } from '../api'
import { can } from '../access'
import products from '../aidr-products.json'
import AgentProductLogo from './AgentProductLogo.vue'
import { groupProductEntries, productGroupId } from '../aidr-product-groups'
const props = defineProps({ clientId: { type: String, required: true }, fixedAgent: { type: String, default: '' }, initialChannel: { type: String, default: 'logs' } })
const emit = defineEmits(['policy', 'plugins', 'activity'])
const { t, te, tm, locale } = useI18n()
const tr = (key, params) => t('collectionStatus.' + key, params || {})
const channel = ref(props.initialChannel), selectedId = ref(''), runtime = ref(null), logs = ref(null), system = ref(null), errors = ref([]), loading = ref(false), guideOpen = ref(false)
const backgroundRefresh = ref(false)
const settled = ref({ runtime: false, logs: false, system: false })
const pending = ref({ runtime: false, logs: false, system: false })
const selectedReady = computed(() => settled.value.runtime && (channel.value === 'hooks' || settled.value[channel.value]))
const selectedPending = computed(() => pending.value.runtime || (channel.value !== 'hooks' && pending.value[channel.value]))
const inspector = ref(null), sourcePanel = ref(null), scrollArea = ref(null)
const channels = [{ id: 'logs', icon: MessageOutlined }, { id: 'hooks', icon: LinkOutlined }, { id: 'system', icon: FileTextOutlined }]
let generation = 0, lastScrollAt = 0
const clock = ref(Date.now())
// Read-only refresh runs only while this panel is visible.
const clockTimer = setInterval(() => {
 if (document.hidden || !scrollArea.value?.offsetParent || Date.now() - lastScrollAt <= 2000) return
 clock.value = Date.now()
 load(true)
}, 5000)
const parsed = value => value ? Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z') : NaN
const fresh = (value, seconds = 30) => Number.isFinite(parsed(value)) && clock.value - parsed(value) <= seconds * 1000 && clock.value - parsed(value) >= -5000
const stamp = value => Number.isFinite(parsed(value)) ? new Date(parsed(value)).toLocaleString(locale.value) : tr('unknown')
const channelData = id => id === 'logs' ? logs.value?.log_channel || runtime.value?.channels?.logs || {} : runtime.value?.channels?.[id] || {}
const currentChannel = computed(() => channelData(channel.value))
const reportFresh = computed(() => !errors.value.includes('runtime') && !errors.value.includes(channel.value) && fresh(currentChannel.value.report?.reported_at))
const label = value => te('collectionStatus.states.' + value) ? tr('states.' + value) : tr('states.unknown')
const warningStates = new Set(['stale','unreported','unknown','failed','stopped','disabled','unsupported','source_partial','source_missing','source_unavailable','permission_denied','not_installed','review_required','admin_required','cancelled','interrupted','host_missing','partial','transport_offline','read_failed','disable_not_applied','mode_upgrade_required','product_upgrade_required'])
const tone = state => state === 'received' ? 'good' : warningStates.has(state) ? 'warning' : 'neutral'
function baseState(id) {
 if (errors.value.includes(id) || errors.value.includes('runtime')) return 'read_failed'
 const data = channelData(id), state = data.health?.state || 'unreported'
 if (data.target_enabled === false) return state
 if (state !== 'running') return state
 if (!fresh(data.report?.reported_at)) return 'stale'
 if (id === 'logs' && !fresh(logs.value?.last_seen_at, 90)) return 'transport_offline'
 return 'running'
}
const requested = id => id === 'logs' ? runtime.value?.target?.log_sources || ['claude', 'codex'] : runtime.value?.target?.hosts || []
function productRows(id) {
 const data = channelData(id), base = baseState(id)
 if (!runtime.value || data.target_enabled === false) return []
 return products.filter(p => p[id] && (!props.fixedAgent || p.id === props.fixedAgent) && requested(id).includes(p.id)).map(product => {
  let state = base
  const discovery = (logs.value?.health?.discovery || []).filter(d => d.agent === product.id)
  const receipts = (logs.value?.product_receipts || []).filter(r => r.agent === product.id && fresh(r.last_received_at, 900))
  const connection = runtime.value?.hook_connections?.find(c => c.agent === product.id)
  const arrival = id === 'logs' ? receipts.map(r => r.last_received_at).sort().at(-1) : fresh(connection?.event_received_at, 900) ? connection.event_received_at : null
  if (base === 'running' && id === 'logs') {
   if (discovery.some(d => d.reason_codes?.includes('aidr_log_permission_denied'))) state = 'permission_denied'
   else if (discovery.some(d => d.status === 'unavailable')) state = 'source_unavailable'
   else if (discovery.some(d => d.status === 'partial')) {
    const reasons = discovery.flatMap(d => d.reason_codes || [])
    state = reasons.includes('aidr_log_source_missing') ? 'source_missing'
      : reasons.length && reasons.every(code => ['aidr_log_discovery_pending', 'aidr_log_discovery_budget'].includes(code)) ? 'source_scanning' : 'source_partial'
   }
   else state = arrival ? 'received' : discovery.length ? 'waiting' : 'unreported'
  }
  if (base === 'running' && id === 'hooks') {
   if (connection?.stale || !fresh(connection?.observed_at, 480)) state = arrival ? 'received' : 'unreported'
   else if (['host_missing', 'not_installed'].includes(connection?.installation)) state = connection.installation
   else if (['review_required','admin_required','cancelled','failed','interrupted'].includes(connection?.authorization)) state = connection.authorization
   else if (connection?.enabled === false) state = 'disabled'
   else state = arrival ? 'received' : 'waiting'
  }
  return { id: product.id, name: product.name, entry: product.entry, product, state, arrival, discovery, connection, receiptsReported: id === 'hooks' || Array.isArray(logs.value?.product_receipts), count: id === 'logs' && Array.isArray(logs.value?.product_receipts) ? receipts.reduce((sum,r) => sum+r.count, 0) : null, observed: id === 'logs' ? logs.value?.last_seen_at : connection?.observed_at }
 })
}
function systemRows() {
 const base = baseState('system')
 if (currentChannel.value.target_enabled === false) return []
 return ['process','network'].map(id => {
  let state = base
  if (base === 'running') {
   if (!system.value) state = 'unreported'
   else if (['stopped','failed'].includes(system.value.state)) state = system.value.state
   else if (!fresh(system.value.last_received_at, 10) || system.value.state === 'stale') state = 'stale'
   else if (['collecting','active','degraded'].includes(system.value.state)) {
    const network = system.value.health?.network_health
    state = id === 'network' ? network?.state || 'unreported' : system.value.state === 'degraded' ? 'partial' : 'observing'
    if (id === 'network' && state === 'sampled' && (!Number.isFinite(Number(network.sampled_at_ns)) || clock.value - Number(network.sampled_at_ns) / 1e6 > 10000)) state = 'stale'
   }
   else state = 'unreported'
  }
  return { id, name: tr(id), state, observed: system.value?.last_received_at }
 })
}
const rows = computed(() => channel.value === 'system' ? systemRows() : productRows(channel.value))
const entryLabel = entry => t(`agentRuntimeGovernance.catalog.entries.${entry}`)
const inactiveEntries = computed(() => runtime.value?.target_configured && currentChannel.value.target_enabled != null ? products.filter(p => (!props.fixedAgent || p.id === props.fixedAgent) && p.collection_visible !== false && p[channel.value] && (currentChannel.value.target_enabled === false || !requested(channel.value).includes(p.id))) : [])
const sourceGroups = computed(() => groupProductEntries(rows.value).map(group => ({
 ...group,
 entries: [...group.entries, ...inactiveEntries.value.filter(p => productGroupId(p.id) === group.id).map(product => ({ ...product, product, state: 'not_requested' }))],
})))
const selectableRows = computed(() => sourceGroups.value.flatMap(group => group.entries))
const selected = computed(() => selectableRows.value.find(row => row.id === selectedId.value) || selectableRows.value[0])
const selectedGroup = computed(() => sourceGroups.value.find(group => group.entries.some(row => row.id === selected.value?.id)))
watch(selectableRows, value => { if (!value.some(row => row.id === selectedId.value)) selectedId.value = value[0]?.id || '' })
const disabledProducts = computed(() => groupProductEntries(inactiveEntries.value).filter(group => !sourceGroups.value.some(active => active.id === group.id)))
const issues = computed(() => channels.flatMap(({ id }) => {
 if (!settled.value.runtime || (id !== 'hooks' && !settled.value[id])) return []
 const candidates = id === 'system' ? systemRows() : productRows(id)
 const problem = candidates.find(row => warningStates.has(row.state))
 const state = problem?.state || baseState(id)
 if (!warningStates.has(state)) return []
 return [{ channel: id, sourceId: problem?.id || '', state, observed: channelData(id).report?.reported_at,
  hint: state === 'stale' ? tr(id === 'system' ? 'systemStaleNote' : 'staleNote') : ['unknown', 'unreported', 'read_failed'].includes(state) ? tr('reportProblem') : state === 'transport_offline' ? tr('checkUpload') : tr(id === 'logs' ? 'logProblem' : id === 'hooks' ? 'hookProblem' : 'checkSystem') }]
}))
const attentionCount = computed(() => issues.value.length)
const discoveryLabel = computed(() => selected.value?.discovery?.length ? selected.value.discovery.map(d => d.status === 'partial' ? label(['source_missing', 'source_scanning'].includes(selected.value.state) ? selected.value.state : 'source_partial') : t('aidr.' + (d.status === 'complete' ? 'complete' : 'unavailable'))).join(' · ') : tr('unknown'))
const logReasonKinds = {
 aidr_log_source_missing: 'missing', aidr_log_permission_denied: 'permission',
 aidr_log_discovery_pending: 'scanning', aidr_log_discovery_budget: 'scanning',
 aidr_log_discovery_capacity: 'capacity', aidr_log_discovery_depth: 'depth',
 aidr_log_io_error: 'readError', aidr_log_symlink: 'symlink', aidr_log_source_outside_root: 'outsideRoot',
 aidr_log_invalid_json: 'format', aidr_log_schema_unsupported: 'format',
}
const logReasons = computed(() => channel.value === 'logs' && ['source_partial', 'source_missing', 'source_scanning', 'source_unavailable', 'permission_denied'].includes(selected.value?.state)
 ? [...new Set((selected.value.discovery || []).flatMap(d => d.reason_codes || []).map(code => logReasonKinds[code] || 'other'))] : [])
const connectionLabel = (kind, value) => { const key = `agentRuntimeGovernance.connection.${kind}States.${value || 'unknown'}`; return te(key) ? t(key) : tr('unknown') }
const guidance = computed(() => {
 const state = selected.value?.state
 if (channel.value === 'logs' && state === 'source_scanning') return tr('checkLogScanning')
 if (channel.value === 'logs' && state === 'source_missing') return tr('checkLogMissing')
 if (['awaiting_application','not_requested','not_configured','policy_unknown','mode_pending','disable_not_applied'].includes(state)) return tr('checkPolicy')
 if (state === 'transport_offline' || currentChannel.value.report?.transport_code?.includes('failed')) return tr('checkUpload')
 if (['stale','unreported','unknown','read_failed'].includes(state)) return tr('checkReport')
 return tr(channel.value === 'logs' ? 'checkLog' : channel.value === 'hooks' ? 'checkHook' : 'checkSystem')
})
const description = computed(() => selected.value?.state === 'stale' ? tr(channel.value === 'system' ? 'systemStaleNote' : 'staleNote') : selected.value?.state === 'source_scanning' ? tr('logScanning') : tone(selected.value?.state) === 'warning' ? tr(channel.value === 'logs' ? 'logProblem' : channel.value === 'hooks' ? 'hookProblem' : 'checkSystem') : tr('receiptNote'))
const guideSteps = computed(() => tm('collectionStatus.' + (channel.value === 'system' ? 'systemSteps' : 'guideSteps')))
function channelSummary(id) {
 if (!settled.value.runtime || (id !== 'hooks' && !settled.value[id])) return tr('loading')
 const state = baseState(id)
 return state === 'running' ? tr(id === 'logs' ? 'logHint' : id === 'hooks' ? 'hookHint' : 'systemHint') : label(state)
}
function changeChannel(id, sourceId = '') { channel.value = id; selectedId.value = sourceId; if (scrollArea.value) scrollArea.value.scrollTop = 0 }
async function selectSource(id) { selectedId.value = id; await nextTick(); if (window.matchMedia('(max-width:700px)').matches) inspector.value?.scrollIntoView({ block: 'start' }) }
function openActivity() { emit('activity', channel.value === 'system' ? 'system' : channel.value === 'hooks' ? 'hooks' : 'tools') }
async function load(background = false) {
 if (loading.value || !props.clientId) return
 const epoch = ++generation, id = props.clientId
 backgroundRefresh.value = background
 loading.value = true
 pending.value = { runtime: true, logs: true, system: true }
 const requests = [
  ['runtime', runtime, () => getClientRuntimeGovernance(id)],
  ['logs', logs, () => getClientAidrStatus(id, { include_retention: false })],
  ['system', system, () => getEnforcement(id, 'status')],
 ]
 await Promise.allSettled(requests.map(async ([key, target, request]) => {
  try {
   const result = await request()
   if (epoch !== generation) return
   target.value = result
   errors.value = errors.value.filter(value => value !== key)
  } catch {
   if (epoch !== generation) return
   target.value = null
   if (!errors.value.includes(key)) errors.value.push(key)
  } finally {
   if (epoch === generation) {
    pending.value[key] = false
    settled.value[key] = true
    clock.value = Date.now()
   }
  }
 }))
 if (epoch !== generation) return
 loading.value = false
}
watch(() => props.clientId, () => {
 generation++; loading.value = false; runtime.value = logs.value = system.value = null; selectedId.value = ''; errors.value = []
 settled.value = { runtime: false, logs: false, system: false }
 pending.value = { runtime: false, logs: false, system: false }
 load()
}, { immediate: true })
onBeforeUnmount(() => { generation++; clearInterval(clockTimer) })
</script>
<style scoped>
.collection-issues { padding:14px 16px; margin-bottom:16px; border:1px solid #edcf90; border-radius:7px; background:#fffaf0; }
.collection-issues>strong { display:block; margin-bottom:8px; }
.collection-issues button { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:6px 12px; width:100%; text-align:left; border:0; border-top:1px solid #f0e4ce; background:none; padding:12px 0; color:#795a28; cursor:pointer; }
.collection-issues small,.collection-issues p { grid-column:1 / -1; margin:0; font-size:12px; line-height:1.7; }
.collection-loading { padding: 28px; border: 1px solid #dfe6ef; border-radius: 7px; background: #fff; }
.collection-loading > .anticon { color: #2860e8; margin-right: 10px; font-size: 20px; }
.collection-loading > p { color: #718198; margin: 10px 0 24px; }
.collection-refreshing { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; color: #245ddb; font-size: 13px; }
.log-reasons { margin-bottom: 16px; }
.log-reasons ul { margin: 8px 0 0; padding-left: 20px; }
.log-reasons li { margin: 6px 0; line-height: 1.6; overflow-wrap: anywhere; }
.source-group { display: grid; gap: 6px; }
.source-group-title { display: flex; align-items: center; gap: 8px; margin: 8px 0 2px; }
.source-group-title :deep(.agent-product-logo) { width: 24px; height: 24px; }
.source-inspector header small { color: #718198; }
.source-icon:has(.agent-product-logo) { padding: 3px; background: white; }
.disabled-product-name { display: flex; align-items: center; gap: 8px; }
.disabled-product-logo { display: inline-flex; width: 22px; height: 22px; flex-shrink: 0; }
.collection-scroll{overflow-anchor:none}
.collection-status{display:flex;flex-direction:column;flex:1;min-height:0;color:#23334c}.collection-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex:none;margin:12px 0 16px}.collection-heading h2{font-size:22px;margin:0 0 5px}.collection-heading p{margin:0;color:#718198;font-size:13px}.collection-channels{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid #dde5f0;border-radius:7px;overflow:hidden;flex:none}.collection-channels button{background:#fff;border:0;border-right:1px solid #dde5f0;padding:16px;display:flex;align-items:center;gap:13px;text-align:left;cursor:pointer;color:inherit;border-bottom:3px solid transparent;min-width:0}.collection-channels button:last-child{border-right:0}.collection-channels button.selected{background:#f5f8ff;border-bottom-color:#2860e8;color:#245ddb}.collection-channels button>.anticon{font-size:25px}.collection-channels strong{font-size:15px}.collection-channels small{display:block;color:#718198;margin-top:6px;font-size:12px}.collection-scroll{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;margin-top:16px;padding-bottom:16px;scrollbar-gutter:stable}.collection-grid{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,1fr);gap:16px;align-items:start}.source-panel,.source-inspector,.empty-inspector{border:1px solid #dfe6ef;border-radius:7px;min-width:0}.source-panel{padding:20px 16px 3px}.source-panel h3{margin:0;font-size:19px}.muted,.source-hint{color:#718198;font-size:12px;line-height:1.7}.source-hint{margin:8px 0 15px}.source-list{display:flex;flex-direction:column;gap:9px}.source-row{display:flex;align-items:center;gap:12px;border:1px solid #e0e7f0;border-radius:6px;padding:13px 12px;min-height:80px;background:#fff;width:100%;text-align:left;color:inherit;cursor:pointer}.source-row.selected{background:#f5f8ff;border-color:#a9c2f5}.source-row.warning.selected{background:#fffbf1;border-color:#edcf90}.source-icon{display:flex;align-items:center;justify-content:center;background:#f0f4fa;color:#6883ac;border-radius:7px;width:34px;height:34px;flex:none;font-size:22px}.source-name{flex:1;min-width:0}.source-name strong{font-size:15px;display:block;overflow-wrap:anywhere}.source-name small{display:block;margin-top:7px;color:#8592a7;font-size:11px}.source-result{text-align:right;max-width:46%}.source-result strong{font-weight:500;display:flex;gap:6px;align-items:center;font-size:12px}.source-result small{display:block;color:#8794a7;font-size:10px;margin-top:8px}.good .source-result strong{color:#278441}.warning .source-result strong{color:#aa7418}.chevron{font-size:10px;color:#8b9bb2}.upload-summary{display:flex;align-items:center;gap:12px;background:#f5f8fd;border-radius:5px;padding:16px 12px;margin-top:15px}.upload-summary>.anticon{font-size:28px;color:#7190bf}.upload-summary>div{flex:1;min-width:0}.upload-summary strong{display:block;font-size:13px}.upload-summary small{display:block;color:#7e8fa8;margin-top:6px;font-size:11px}.upload-summary :deep(.ant-btn){height:auto;white-space:normal;max-width:130px;font-size:12px;padding:0}.small-note{font-size:11px;color:#7c8ca3;line-height:1.7;margin:9px 0}.disclosure{border-top:1px solid #e2e8f0;margin-top:15px;padding:15px 0}.disclosure summary{cursor:pointer;font-size:13px;color:#536881}.disclosure p{margin:12px 0 7px}.disabled-product{display:flex;justify-content:space-between;gap:12px;padding:8px 0;font-size:13px}.disabled-product small{color:#8391a6}dl{margin:12px 0}dl>div{display:flex;justify-content:space-between;gap:15px;padding:7px 0;font-size:12px}dt{color:#7c8ca2}dd{margin:0;text-align:right;overflow-wrap:anywhere}.source-inspector{overflow:hidden}.source-inspector.warning{border-color:#edcf90}.source-inspector>header{display:flex;align-items:flex-start;gap:12px;background:#f5f8fd;padding:20px 18px;border-bottom:1px solid #e1e8f2}.source-inspector.warning>header{background:#fff9ed;border-color:#f3e5c7}.source-inspector h3{font-size:16px;margin:0;line-height:1.7}.source-inspector header p{margin:7px 0 0;font-size:12px;color:#7f8da2;line-height:1.75}.inspector-body{padding:18px}.inspector-body h4{font-size:14px;margin:0 0 12px}.evidence-list>div{padding:11px 0;border-bottom:1px solid #f0f3f8}.scope-box,.desktop-path{background:#f5f8fd;border-radius:5px;padding:13px;line-height:1.8;font-size:12px;color:#6c819f}.desktop-path{display:flex;align-items:flex-start;gap:9px;color:#2e476c}.desktop-path>.anticon{font-size:20px;margin-top:2px}.next-action{margin-top:20px;border-top:1px solid #e2e8f0;padding-top:17px}.next-action>p{font-size:13px;line-height:1.8;color:#6f8098}.action-buttons{display:flex;flex-wrap:wrap;gap:9px;margin:14px 0 6px}.action-buttons :deep(.ant-btn){height:auto;white-space:normal;padding:7px 12px;font-size:12px}.next-action>:deep(.ant-btn-link){padding-left:0;font-size:12px}.disclosure code{display:block;overflow-wrap:anywhere;margin:8px 0;font-size:11px;color:#6d7e96}.empty-inspector{padding:25px;color:#718198;line-height:1.8}.empty-inspector h3{margin-top:15px}.mobile-back{display:none}.guide-steps{padding-left:22px}.guide-steps li{margin:18px 0;line-height:1.8}.collection-scroll>.ant-alert{margin-bottom:12px}button:focus-visible,summary:focus-visible{outline:2px solid #87aafa;outline-offset:2px}
@media(max-width:1050px){.source-row{gap:8px;padding:10px}.source-name strong{font-size:13px}.source-result strong{font-size:11px}.source-icon{width:28px;height:28px;font-size:19px}.collection-channels button{padding:12px;gap:9px}.collection-channels strong{font-size:13px}.collection-channels small{font-size:11px}.upload-summary{flex-wrap:wrap}.upload-summary :deep(.ant-btn){margin-left:40px;max-width:none}}
@media(max-width:700px){.collection-grid{grid-template-columns:1fr}.collection-heading{margin:8px 0 12px}.collection-heading h2{font-size:19px}.collection-heading p{font-size:11px}.collection-channels button{padding:10px 8px;gap:6px;align-items:flex-start}.collection-channels button>.anticon{font-size:18px}.collection-channels small{font-size:10px}.collection-channels strong{font-size:12px}.collection-scroll{margin-top:12px}.mobile-back{display:block;margin:10px}.source-result{max-width:47%}.source-result small{font-size:10px}.source-result strong{font-size:12px}.source-name strong{font-size:14px}.source-panel{padding:16px 12px 2px}.source-inspector>header,.inspector-body{padding:16px}.upload-summary{flex-wrap:nowrap}.upload-summary :deep(.ant-btn){margin-left:0;max-width:90px}}
</style>
