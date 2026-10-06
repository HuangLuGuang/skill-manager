<template>
  <section class="enforcement-panel">
    <h3>{{ t(view === 'events' ? 'agentRuntimeGovernance.detail.auditViews.system' : 'aidr.enforcement.title') }}</h3>
    <p>{{ t(view === 'events' ? 'aidr.enforcement.eventsIntro' : 'aidr.enforcement.policyIntro') }}</p>
    <ClientProtectionStatus v-if="view === 'control'" :client-id="clientId" channel="system" />
    <a-alert v-if="error" type="error" :message="t('aidr.enforcement.failed')" :description="error" />
    <div class="controls">
      <a-tag :color="['active', 'collecting'].includes(status.state) ? 'green' : 'orange'">{{ t(`aidr.enforcement.states.${status.state || 'unknown'}`) }}</a-tag>
      <span>{{ t('aidr.enforcement.target') }}: {{ status.target_revision || '0' }}</span>
      <span>{{ t('aidr.enforcement.applied') }}: {{ status.reported_revision || t('aidr.enforcement.unknown') }}</span>
      <a-button :loading="loading" @click="refresh">{{ t('aidr.enforcement.refresh') }}</a-button>
    </div>
    <a-alert v-if="['failed', 'degraded', 'stale'].includes(status.state)" type="warning" show-icon :message="setupNextStep" />
    <details v-if="status.health" class="diagnostics"><summary>{{ t('aidr.enforcement.diagnostics') }}</summary><p>{{ t('aidr.enforcement.diagnostic') }}: <code>{{ status.health.reason_code }}</code></p><p>{{ t('aidr.enforcement.evidence') }}</p></details>
    <a-alert v-if="view === 'events' && !loading && !error && status.state === 'unknown'" type="info" show-icon :message="t('aidr.enforcement.noSystemReport')" :description="t('aidr.enforcement.systemChannelNote')" />
    <a-alert v-if="platformSupport !== 'macos_endpoint_security'" type="warning" show-icon
      :message="t(`aidr.enforcement.setup.platforms.${platformSupport}`)" :description="t('aidr.enforcement.setup.supportBoundary')" />
    <details class="setup-guide">
      <summary>{{ t('aidr.enforcement.setup.title') }}</summary>
      <p>{{ t('aidr.enforcement.setup.onDevice') }}</p><p>{{ t('aidr.enforcement.setup.supportBoundary') }}</p>
      <ol v-if="platformSupport === 'macos_endpoint_security'">
        <li><strong>{{ t('aidr.enforcement.setup.checkTitle') }}</strong><p>{{ t('aidr.enforcement.setup.checkNote') }}</p>
        </li>
        <li><strong>{{ t('aidr.enforcement.setup.installTitle') }}</strong><p>{{ t('aidr.enforcement.setup.installNote') }}</p>
        </li>
        <li><strong>{{ t('aidr.enforcement.setup.authorizeTitle') }}</strong><p>{{ t('aidr.enforcement.setup.authorizeNote') }}</p>
          <p>{{ t('aidr.enforcement.setup.collectionNote') }}</p>
        </li>
        <li><strong>{{ t('aidr.enforcement.setup.verifyTitle') }}</strong><p>{{ setupNextStep }}</p>
          <div class="controls"><a-button :loading="loading" @click="refresh">{{ t('aidr.enforcement.setup.retryStatus') }}</a-button>
            <a-button v-if="view === 'events'" @click="eventKind = 'health'; before = 0; refresh()">{{ t('aidr.enforcement.setup.viewHealth') }}</a-button>
            <a-button v-if="view === 'events'" @click="eventKind = 'process'; before = 0; refresh()">{{ t('aidr.enforcement.setup.viewProcesses') }}</a-button>
          </div>
        </li>
      </ol>
      <p v-else>{{ t('aidr.enforcement.setup.unsupportedNext') }}</p>
    </details>
    <details v-if="view === 'control'" open>
      <summary>{{ t('aidr.enforcement.config') }}</summary>
      <p>{{ t('aidr.enforcement.runtimeHint') }}</p>
      <a-form layout="vertical" :disabled="!canPublish || saving">
        <a-form-item :label="t('aidr.enforcement.roots')" :extra="t('aidr.enforcement.rootsHelp')"><a-textarea v-model:value="roots" :rows="3" :maxlength="32768" :placeholder="t('aidr.enforcement.rootsExample')" /></a-form-item>
        <a-form-item :label="t('aidr.enforcement.lifetime')" :extra="t('aidr.enforcement.lifetimeHelp')"><a-input-number v-model:value="hours" :min="1" :max="720" /></a-form-item>
        <details class="advanced-control"><summary>{{ t('aidr.enforcement.advancedControl') }} · {{ draft.rules.length }}</summary>
        <p>{{ t('aidr.enforcement.controlHelp') }}</p><p>{{ t('aidr.enforcement.publishHint') }}</p>
        <div class="controls">
          <a-form-item :label="t('aidr.enforcement.unknownAction')"><a-select v-model:value="draft.unknown_actor_action" :options="decisionOptions" /></a-form-item>
          <a-form-item :label="t('aidr.enforcement.expiredAction')"><a-select v-model:value="draft.expired_action" :options="decisionOptions" /></a-form-item>
        </div>
        <h4>{{ t('aidr.enforcement.rules') }}</h4>
        <div v-for="(rule, index) in draft.rules" :key="index" class="rule">
          <a-input v-model:value="rule.id" :aria-label="t('aidr.enforcement.rule')" :placeholder="t('aidr.enforcement.rule')" :maxlength="64" />
          <a-input v-model:value="rule.path" :aria-label="t('aidr.enforcement.path')" :placeholder="t('aidr.enforcement.path')" :maxlength="1023" />
          <a-select v-model:value="rule.actor" :aria-label="t('aidr.enforcement.actor')" :options="actorOptions" />
          <a-select v-model:value="rule.decision" :aria-label="t('aidr.enforcement.decision')" :options="decisionOptions" />
          <a-button @click="draft.rules.splice(index, 1)">{{ t('aidr.enforcement.remove') }}</a-button>
        </div>
        <div class="controls">
          <a-button :disabled="draft.rules.length >= 128" @click="draft.rules.push({ id: '', path: '', actor: 'agent', decision: 'deny' })">{{ t('aidr.enforcement.add') }}</a-button>
        </div>
        <AidrRulePreview :client-id="clientId" channel="system" :draft="draft" />
        </details>
        <div class="controls">
          <a-button type="primary" :loading="saving" :disabled="saving || !canPublish" @click="publish(false)">{{ t('aidr.enforcement.publish') }}</a-button>
        </div>
        <details><summary>{{ t('aidr.enforcement.historyActions') }}</summary>
        <div class="controls">
          <a-select v-model:value="historyRevision" :aria-label="t('aidr.enforcement.history')" :placeholder="t('aidr.enforcement.history')" :options="history.map(row => ({ value: row.revision, label: row.revision }))" />
          <a-button :disabled="!historyRevision" @click="loadHistorical">{{ t('aidr.enforcement.restore') }}</a-button>
          <a-popconfirm :title="t('aidr.enforcement.revokeConfirm')" @confirm="publish(true)"><a-button danger :loading="saving" :disabled="saving || !canPublish || !draft.rules.length">{{ t('aidr.enforcement.revoke') }}</a-button></a-popconfirm>
        </div>
        </details>
      </a-form>
    </details>
    <template v-if="view === 'events'">
    <h4>{{ t('aidr.enforcement.events') }}</h4>
    <div class="controls"><a-select v-model:value="eventKind" :aria-label="t('aidr.enforcement.kind')" :options="kindOptions" @change="before = 0; refresh()" /></div>
    <a-table :columns="columns" :data-source="eventRows" row-key="id" size="small" :pagination="false" :scroll="{ x: 980 }">
      <template #bodyCell="{ column, record: row }">
        <template v-if="column.key === 'time'">
          <template v-if="row.repeat_count > 1"><div>{{ time(row.start_time_ns) }}</div><small>{{ t('aidr.enforcement.through') }} {{ time(row.record.time_ns) }} · {{ t('aidr.enforcement.repeated', { count: row.repeat_count }) }}</small></template>
          <template v-else>{{ time(row.record.time_ns) }}</template>
        </template>
        <template v-else-if="column.key === 'activity'">{{ eventActivity(row.record) }}<small v-if="row.record.rule_id">{{ t('aidr.enforcement.rule') }}: {{ row.record.rule_id }}</small></template>
        <template v-else-if="column.key === 'process'">
          <div>{{ ['health', 'policy'].includes(row.record.kind) ? t('aidr.enforcement.executor') : attribution(row.record) }}</div>
          <template v-if="['process', 'authorization', 'response'].includes(row.record.kind)">
            <code>{{ t('aidr.enforcement.pid') }} {{ row.record.process?.pid || '—' }}</code>
            <small v-if="row.record.root?.pid && row.record.root.pid !== row.record.process?.pid">{{ t('aidr.enforcement.rootPid') }} {{ row.record.root.pid }}</small>
          </template>
        </template>
        <template v-else-if="column.key === 'resource'"><code v-if="row.record.path">{{ row.record.path }}</code><span v-else>—</span></template>
        <template v-else-if="column.key === 'outcome'">
          <template v-if="row.record.kind === 'authorization' || row.record.kind === 'response'">{{ t(`aidr.enforcement.results.${row.record.decision}`) }} · {{ t(`aidr.enforcement.results.${row.record.result}`) }}</template>
          <template v-else-if="row.record.kind === 'health'">{{ eventReason(row.record) }}<small v-if="Number(row.record.gaps) > 0">{{ t('aidr.enforcement.gaps', { count: row.record.gaps }) }}</small></template>
          <template v-else-if="row.record.kind === 'policy'">{{ eventReason(row.record) }}</template>
          <template v-else-if="Number(row.record.gaps) > 0">{{ t('aidr.enforcement.gaps', { count: row.record.gaps }) }}</template>
          <span v-else>—</span>
        </template>
        <template v-else-if="column.key === 'action'">
          <a-button size="small" @click="openEvent(row)">{{ t('aidr.enforcement.detail') }}</a-button>
          <template v-if="canTerminate && status.state === 'active' && row.record.kind === 'process'">
            <a-popconfirm v-if="!terminationReason(row)" :title="t('aidr.enforcement.terminateConfirm')" @confirm="terminate(row)"><a-button size="small" danger :loading="terminating" :disabled="terminating">{{ t('aidr.enforcement.terminate') }}</a-button></a-popconfirm>
            <span v-else><a-button size="small" disabled>{{ t('aidr.enforcement.terminate') }}</a-button><small>{{ t(`aidr.enforcement.blocked.${terminationReason(row)}`) }}</small></span>
          </template>
        </template>
      </template>
    </a-table>
    <div class="controls"><a-button :disabled="loading || !before" @click="before = 0; refresh()">{{ t('aidr.enforcement.recent') }}</a-button><a-button :disabled="loading || !events.has_more" @click="before = events.next_before; refresh()">{{ t('aidr.enforcement.earlier') }}</a-button></div>
    </template>
    <details v-if="view === 'control'"><summary>{{ t('aidr.enforcement.commands') }}</summary><div v-for="row in responses" :key="row.id"><code>{{ row.id }}</code> · {{ t(`aidr.enforcement.results.${row.display_state || row.state}`) }} <a-button size="small" @click="selected = row; detailOpen = true">{{ t('aidr.enforcement.detail') }}</a-button></div></details>
    <a-modal v-model:open="detailOpen" :title="t('aidr.enforcement.detail')" :footer="null" width="min(900px, 94vw)"><p>{{ t('aidr.enforcement.evidence') }}</p><pre class="evidence">{{ JSON.stringify(selected, null, 2) }}</pre></a-modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ClientProtectionStatus from './ClientProtectionStatus.vue'
import AidrRulePreview from './AidrRulePreview.vue'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { getEnforcement, publishEnforcement, terminateEnforcement } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, view: { type: String, default: 'control' } })
const { t, te, locale } = useI18n()
const status = ref({}), events = ref({}), history = ref([]), responses = ref([]), before = ref(0)
const eventKind = ref('process')
const loading = ref(false), saving = ref(false), terminating = ref(false), error = ref('')
const roots = ref(''), hours = ref(24), draft = ref({ rules: [], unknown_actor_action: 'allow', expired_action: 'allow' })
const historyRevision = ref(), selected = ref(), detailOpen = ref(false)
let baseRevision = '0', generation = 0, initialized = false, timer, refreshQueued = false
const requests = new Map()
const platformSupport = computed(() => ['macos_endpoint_security', 'unsupported_platform', 'unreported_platform'].includes(status.value.platform_support) ? status.value.platform_support : 'unreported_platform')
const canPublish = computed(() => !error.value && !loading.value && status.value.can_edit && can('clients:update'))
const canTerminate = computed(() => status.value.can_edit && can('clients:execute'))
const decisionOptions = computed(() => ['allow', 'deny'].map(value => ({ value, label: t(`aidr.enforcement.${value}`) })))
const actorOptions = computed(() => ['agent', 'all'].map(value => ({ value, label: t(`aidr.enforcement.${value}`) })))
const kindOptions = computed(() => [{ value: '', label: t('aidr.enforcement.allKinds') }, ...['authorization', 'process', 'policy', 'response', 'health'].map(value => ({ value, label: t(`aidr.enforcement.kinds.${value}`) }))])
const setupNextStep = computed(() => {
  const reason = status.value.health?.reason_code
  const key = reason === 'aidr_enforcement_es_unavailable' ? 'authorization'
    : ['failed', 'stopped'].includes(status.value.state) ? 'restart'
      : status.value.state === 'degraded' ? 'degraded'
        : status.value.state === 'stale' ? 'stale'
          : ['active', 'collecting'].includes(status.value.state) ? 'reported' : 'unreported'
  return t(`aidr.enforcement.setup.next.${key}`)
})

const columns = computed(() => ['time', 'activity', 'process', 'resource', 'outcome', 'action'].map(key => ({ key, title: t(`aidr.enforcement.${key === 'action' ? 'detail' : key}`), width: { time: 160, activity: 165, process: 190, resource: 300, outcome: 190, action: 110 }[key] })))
const eventRows = computed(() => {
  const grouped = []
  for (const item of events.value.items || []) {
    const record = item.record || {}
    const previous = grouped[grouped.length - 1]
    const sameHealth = record.kind === 'health' && previous?.record?.kind === 'health'
      && ['monitor_id', 'boot_id', 'revision', 'reason_code', 'gaps'].every(key => record[key] === previous.record[key])
      && JSON.stringify(record.process) === JSON.stringify(previous.record.process)
      && JSON.stringify(record.root) === JSON.stringify(previous.record.root)
    if (sameHealth) {
      previous.repeat_count += 1
      previous.start_time_ns = record.time_ns
    } else grouped.push({ ...item, repeat_count: 1, start_time_ns: record.time_ns })
  }
  return grouped
})
function time(ns) { return new Date(Number(BigInt(ns) / 1000000n)).toLocaleString(locale.value) }
function eventActivity(record) {
  const reason = `aidr.enforcement.reasons.${record.reason_code}`
  if (te(reason)) return t(reason)
  const transition = `aidr.enforcement.transitions.${record.transition}`
  if (record.transition && te(transition)) return t(transition)
  return t(`aidr.enforcement.kinds.${record.kind}`)
}
function eventReason(record) {
  const key = `aidr.enforcement.reasons.${record.reason_code}`
  return te(key) ? t(key) : t('aidr.enforcement.technicalReason', { code: record.reason_code })
}
function attribution(record) { return t(`aidr.enforcement.attribution.${record.relation || 'unknown'}`) }
function openEvent(row) {
  selected.value = { record: row.record, repeated_records: row.repeat_count,
    time_range: row.repeat_count > 1 ? { from_ns: row.start_time_ns, to_ns: row.record.time_ns } : null }
  detailOpen.value = true
}
function loadDraft(policy) {
  roots.value = (policy?.agent_executables || []).join('\n')
  const lifetime = Number(policy?.expires_at) - Number(policy?.issued_at)
  if (Number.isFinite(lifetime) && lifetime >= 60) hours.value = Math.min(720, Math.max(1, lifetime / 3600))
  draft.value = { rules: JSON.parse(JSON.stringify(policy?.rules || [])), unknown_actor_action: policy?.unknown_actor_action || 'allow', expired_action: policy?.expired_action || 'allow' }
}
function loadHistorical() { const row = history.value.find(item => item.revision === historyRevision.value); if (row) { loadDraft(row.policy); baseRevision = status.value.target_revision } }
function failure(err) { error.value = err.response?.data?.error_code || err.response?.data?.detail?.error_code || 'aidr_enforcement_request_failed' }
async function refresh() {
  if (loading.value) { refreshQueued = true; return }
  const g = generation, id = props.clientId
  loading.value = true
  try {
    const queryKind = eventKind.value, queryBefore = before.value
    const resources = props.view === 'events' ? ['status', 'records'] : ['status', 'policy', 'history', 'responses']
    const data = Object.fromEntries(await Promise.all(resources.map(async resource => [resource, await getEnforcement(id, resource, resource === 'records' ? { before: queryBefore, kind: queryKind } : undefined)])))
    if (g !== generation) return
    status.value = data.status
    if (props.view === 'events') {
      if (queryKind === eventKind.value && queryBefore === before.value) events.value = data.records
    } else {
      history.value = data.history.items; responses.value = data.responses.items
      if (!initialized) { loadDraft(data.policy.policy); baseRevision = data.policy.revision; initialized = true }
    }
    error.value = ''
  } catch (err) { if (g === generation) failure(err) }
  finally { if (g === generation) { loading.value = false; if (refreshQueued) { refreshQueued = false; refresh() } } }
}
async function publish(revoke) {
  if (saving.value || !canPublish.value) return
  const id = props.clientId, g = generation
  saving.value = true
  try {
    const body = { ...draft.value, rules: revoke ? [] : draft.value.rules, agent_executables: roots.value.split('\n').map(s => s.trim()).filter(Boolean), expected_revision: baseRevision, lifetime_seconds: Math.round(hours.value * 3600) }
    const result = await publishEnforcement(id, body)
    if (g !== generation) return
    baseRevision = result.revision; loadDraft(result.policy); message.success(t('aidr.enforcement.saved')); await refresh()
  } catch (err) { if (g === generation) failure(err) }
  finally { if (g === generation) saving.value = false }
}
function terminationReason(row) {
  const reportedAt = Date.parse(status.value.last_received_at)
  if (error.value || !Number.isFinite(reportedAt) || Math.abs(Date.now() - reportedAt) >= 10000) return 'enforcement_executor_inactive'
  if (status.value.state === 'collecting') return 'enforcement_control_not_enabled'
  if (status.value.state !== 'active') return 'enforcement_executor_inactive'
  if (row.record.boot_id !== status.value.health?.boot_id || row.record.monitor_id !== status.value.health?.monitor_id) return 'enforcement_monitor_changed'
  return row.can_terminate === true ? '' : row.termination_reason || 'enforcement_target_unverified'
}
async function terminate(row) {
  if (terminating.value || !canTerminate.value || terminationReason(row)) return
  const record = row.record
  const id = props.clientId, g = generation, key = JSON.stringify([record.boot_id, record.monitor_id, record.process])
  if (!requests.has(key)) requests.set(key, crypto.randomUUID())
  terminating.value = true
  try {
    await terminateEnforcement(id, { request_id: requests.get(key), boot_id: record.boot_id, monitor_id: record.monitor_id, process: record.process })
    if (g === generation) { message.success(t('aidr.enforcement.sent')); await refresh() }
  } catch (err) { if (g === generation) failure(err) }
  finally { if (g === generation) terminating.value = false }
}
watch(() => props.clientId, () => {
  generation++; refreshQueued = false; initialized = false; loading.value = false; saving.value = false; terminating.value = false; before.value = 0; status.value = {}; events.value = {}; responses.value = []; history.value = []; requests.clear(); detailOpen.value = false
  clearInterval(timer); refresh(); timer = setInterval(() => { if (!document.hidden) refresh() }, 5000)
}, { immediate: true })
onBeforeUnmount(() => { generation++; clearInterval(timer) })
</script>

<style scoped>
.enforcement-panel { margin: 24px 0; padding: 18px; border: 1px solid #d9d9d9; border-radius: 8px; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 12px 0; }
.controls .ant-select { min-width: 150px; }
.setup-guide li { margin: 14px 0; padding-right: 8px; }
.command { display: flex; align-items: flex-start; gap: 10px; margin: 8px 0; }
.command code { flex: 1; min-width: 0; padding: 10px; background: #f5f7f9; }
.command .ant-btn { flex-shrink: 0; height: auto; white-space: normal; }
.rule { display: grid; grid-template-columns: 130px minmax(180px, 1fr) 200px 100px auto; gap: 8px; margin: 8px 0; }
.enforcement-panel :deep(.ant-table-cell) { vertical-align: top; }
.enforcement-panel :deep(.ant-table-cell small) { display: block; margin-top: 3px; color: #718096; white-space: normal; }
.enforcement-panel :deep(.ant-table-cell code) { overflow-wrap: anywhere; white-space: normal; }
code, .evidence { overflow-wrap: anywhere; white-space: pre-wrap; word-break: break-word; }
.evidence { max-height: 65vh; overflow: auto; }
summary { cursor: pointer; margin: 12px 0; }
@media (max-width: 800px) { .rule { grid-template-columns: 1fr; } }
</style>
