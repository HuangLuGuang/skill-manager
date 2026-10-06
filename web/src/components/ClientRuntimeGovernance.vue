<template>
  <section class="runtime-governance">
    <div class="runtime-heading"><div><h3>{{ t(view === 'collection' ? 'detail.hookCollection' : 'tabs.plugins') }}</h3><p v-if="view === 'collection'">{{ t('detail.collectionNote') }}</p></div><a-button :loading="loading" :disabled="loading || !!busy" @click="load">{{ t(error ? 'retry' : 'refresh') }}</a-button></div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-alert v-if="taskRefreshNeeded" type="info" show-icon :message="t(activeTasks.length ? 'taskWaiting' : 'taskAwaitingReport')" :description="t(refreshPaused ? 'taskRefreshPaused' : 'taskRefreshNote')" />
    <a-space wrap>
      <span>{{ t('reported') }}: {{ stamp(state?.reported_at) }}</span>
      <a-tag v-if="state?.stale" color="orange">{{ t('stale') }}</a-tag>
    </a-space>
    <a-alert v-if="view === 'plugins' && state && !supported" type="warning" show-icon :message="t('unsupported')" />
    <p v-if="view === 'plugins' && state?.target_configured" class="runtime-policy-line">{{ t('targetPolicy') }}: {{ state.target_version }} · {{ t(`accessMode.${state.target?.access_mode || 'unknown'}`) }} · {{ t('receivedPolicy') }}: {{ state.report?.policy_version || t('unknown') }}</p>
    <div v-if="view === 'collection' && state?.channels" class="runtime-hosts">
      <article v-for="name in ['logs', 'hooks', 'system']" :key="name" class="runtime-host">
        <strong>{{ t(`channels.${name}`) }}</strong>
        <p>{{ t('targetPolicy') }}: {{ state.target_configured ? yes(state.channels[name].target_enabled) : t('channelNotConfigured') }} · {{ state.channels[name].target_version }}</p>
        <p v-if="state.channels[name].report">{{ t(`channelStates.${state.channels[name].report.state}`) }} · {{ code(state.channels[name].report.code) }}</p>
        <p v-else>{{ t('channelUnreported') }}</p>
        <a-tag v-if="state.channels[name].report && state.channels[name].stale" color="orange">{{ t('stale') }}</a-tag>
        <template v-if="state.channels[name].report">
          <p>{{ t('channelObserved') }}: {{ stamp(state.channels[name].report.reported_at) }}</p>
          <p>{{ t('receivedPolicy') }}: {{ state.channels[name].report.policy_version || t('unknown') }} · {{ t(state.channels[name].applied ? 'channelApplied' : 'channelUnconfirmed') }}</p>
          <p>{{ t('queued') }}: {{ state.channels[name].report.queued_records ?? t('unknown') }} · {{ t('transport') }}: {{ code(state.channels[name].report.transport_code) }}</p>
          <p>{{ t('channelLastAck') }}: {{ stamp(state.channels[name].report.last_ack_at) }}</p>
          <p v-for="reason in state.channels[name].report.coverage_codes || []" :key="reason">{{ code(reason) }}</p>
        </template>
      </article>
    </div>
    <dl v-else-if="view === 'collection'" class="runtime-summary">
      <div><dt>{{ t('receiver') }}</dt><dd>{{ code(state?.report?.receiver_code) }}</dd></div>
      <div><dt>{{ t('transport') }}</dt><dd>{{ code(state?.report?.transport_code) }}</dd></div>
      <div><dt>{{ t('queued') }}</dt><dd>{{ state?.report?.queued_records ?? t('unknown') }}</dd></div>
      <div><dt>{{ t('automatic') }}</dt><dd>{{ yes(state?.report?.enabled) }}</dd></div>
    </dl>
    <details v-if="view === 'collection'" class="runtime-diagnostics"><summary>{{ t('diagnostics') }}</summary>
    <template v-if="state?.target_configured">
      <p>{{ t('targetPolicy') }}: {{ state.target_version }} · {{ yes(state.target?.enabled) }} · {{ state.target?.hosts?.join(' / ') || t('unknown') }} · {{ t(`accessMode.${state.target?.access_mode || 'unknown'}`) }}</p>
      <p>{{ t('receivedPolicy') }}: {{ state.report?.policy_version || t('unknown') }} · {{ stamp(state.report?.policy_received_at) }}</p>
      <p>{{ t('appliedPolicy') }}: {{ stamp(state.report?.policy_applied_at) }} · {{ code(state.report?.policy_code) }}</p>
      <p>{{ t('checkedPolicy') }}: {{ stamp(state.report?.policy_checked_at) }}</p>
    </template>
    <template v-if="state?.report">
      <dl><dt>{{ t('receiver') }}</dt><dd>{{ code(state.report.receiver_code) }}</dd>
        <dt>{{ t('automatic') }}</dt><dd>{{ yes(state.report.enabled) }}</dd>
        <dt>{{ t('transport') }}</dt><dd>{{ code(state.report.transport_code) }}</dd>
        <dt>{{ t('queued') }}</dt><dd>{{ state.report.queued_records ?? t('unknown') }}</dd>
        <dt>{{ t('lastReport') }}</dt><dd>{{ stamp(state.report.last_report) }}</dd>
        <dt>{{ t('hookSequence') }}</dt><dd>{{ state.report.hook_sequence ?? t('unknown') }}</dd>
        <dt>{{ t('controlRevision') }}</dt><dd>{{ state.report.control_revision || t('unknown') }}</dd>
        <dt>{{ t('redaction') }}</dt><dd>{{ yes(state.report.audit_redaction_enabled) }} · {{ state.report.audit_policy_version || t('unknown') }}</dd>
        <dt>{{ t('appliedTask') }}</dt><dd>{{ state.report.managed_task === '0' ? t('local') : state.report.managed_task }}</dd></dl>
      <dl v-if="state.report.receiver_supervision">
        <dt>{{ t('supervisionObserved') }}</dt><dd>{{ stamp(state.report.receiver_supervision.observed_at) }}</dd>
        <dt>{{ t('retryMode') }}</dt><dd>{{ t(`retryModeValue.${state.report.receiver_supervision.mode}`) }}</dd>
        <dt>{{ t('retryCount') }}</dt><dd>{{ state.report.receiver_supervision.retry_count }}</dd>
        <dt>{{ t('retrySuspended') }}</dt><dd>{{ yes(state.report.receiver_supervision.suspended) }}</dd>
        <dt>{{ t('nextRetryAt') }}</dt><dd>{{ stamp(state.report.receiver_supervision.next_retry_at) }}</dd>
        <dt>{{ t('lastFailure') }}</dt><dd>{{ code(state.report.receiver_supervision.last_failure) }} · {{ stamp(state.report.receiver_supervision.last_failure_at) }}</dd>
      </dl>
    </template>
    </details>
    <template v-if="view === 'collection' && state?.report">
      <a-space v-if="can('clients:execute') && !state.target_configured" wrap>
        <a-button v-for="action in ['enable','disable']" :key="action" :loading="busy === action" :disabled="actionBlocked(action, '')" @click="send(action)">{{ t(receiverAlreadySet(action) ? (action === 'enable' ? 'alreadyEnabled' : 'alreadyDisabled') : action) }}</a-button>
      </a-space>
      <p v-if="receiverTask">{{ t('receiverTask') }} #{{ receiverTask.id }} · {{ t(receiverTask.payload.action) }} · {{ t(receiverTask.status) }}<span v-if="receiverTask.error_code"> · {{ code(receiverTask.error_code) }}</span></p>
    </template>
    <template v-if="view === 'plugins'">
      <a-button @click="$emit('policy')">{{ t('detail.configureAccess') }}</a-button>
      <div class="runtime-hosts"><div v-for="agent in ['claude','codex']" :key="agent" class="runtime-host">
        <strong>{{ agent === 'claude' ? 'Claude Code' : 'Codex' }}</strong>
        <p>{{ t('version') }}: {{ host(agent)?.host_version || t('unknown') }} · {{ t('installed') }}: {{ yes(host(agent)?.installed) }} · {{ t('enabled') }}: {{ yes(host(agent)?.enabled) }}</p>
        <p>{{ t('pluginVersion') }}: {{ host(agent)?.plugin_version || t('unknown') }}</p>
        <p>{{ t('trust') }}: {{ t(host(agent)?.hook_trust || 'unknown') }} · {{ t('observed') }}: {{ stamp(host(agent)?.reported_at) }}</p>
        <p>{{ t('compatibility') }}: {{ t(host(agent)?.version_status || 'unknown') }}</p>
        <p v-if="host(agent)?.version_status !== 'adapter_target'">{{ t('verifiedVersionRequired') }}</p>
        <a-space v-if="can('clients:execute')" wrap>
          <a-button v-for="action in ['install','upgrade','inspect']" :key="action" :loading="busy === action+agent" :disabled="actionBlocked(action,agent)" @click="send(action, agent)">{{ t(action) }}</a-button>
        </a-space>
      </div></div>
    </template>
    <template v-if="view === 'plugins'">
    <p class="runtime-collection-link"><a-button type="link" @click="$emit('collection')">{{ t('detail.collection') }}</a-button></p>
    <details class="runtime-diagnostics"><summary>{{ t('presentation.pluginDiagnostics') }}</summary>
      <p>{{ t('note') }}</p><p>{{ t('trustNote') }}</p>
      <div ref="compatibilityAnchor"><ClientRuntimeCompatibility :state="state" /></div>
      <ClientOnboardingAcceptance :value="state?.onboarding" :loading="loading" :can-inspect="!blocked && can('clients:execute')" @refresh="load" @inspect="agent => send('inspect', agent)" @policy="$emit('policy')" @upgrade="compatibilityAnchor?.scrollIntoView({ block: 'center', behavior: 'smooth' })" />
    </details>
    <details @toggle="pluginReportsOpen = $event.target.open"><summary>{{ t('detail.pluginReports') }}</summary><ClientHookPanel v-if="pluginReportsOpen" :client-id="clientId" view="plugins" /></details>
    <details class="runtime-task-history" :open="state?.tasks?.some(task => ['pending','running','failed'].includes(task.status))"><summary>{{ t('tasks') }}</summary>
    <div v-for="task in state?.tasks || []" :key="task.id" class="runtime-task">
      <p>#{{ task.id }} · {{ t(task.payload.action) }} {{ task.payload.agent }} · {{ task.payload.plugin_version }} · {{ t(task.status) }}</p>
      <p v-if="task.error_code">{{ code(task.error_code) }}</p>
      <p>{{ t('validUntil') }}: {{ stamp(task.payload.expires_at) }}</p>
      <details v-if="task.payload.receipt"><summary>{{ t('receipt') }}</summary>
        <p>{{ t('automatic') }}: {{ yes(task.payload.receipt.enabled) }} · {{ t('receiver') }}: {{ code(task.payload.receipt.receiver_code) }}</p>
        <p v-for="item in task.payload.receipt.hosts" :key="item.agent">{{ item.agent }} · {{ item.host_version }} · {{ t('installed') }}: {{ yes(item.installed) }} · {{ t('enabled') }}: {{ yes(item.enabled) }} · {{ t('trust') }}: {{ t(item.hook_trust) }}</p>
      </details>
      <a-space v-if="can('clients:execute')" wrap>
        <a-button v-if="task.status === 'pending'" :disabled="!!busy || loading" @click="taskAction(task,'cancel')">{{ t('cancel') }}</a-button>
        <a-button v-if="['failed','cancelled'].includes(task.status)" :disabled="!!busy || loading" @click="taskAction(task,'retry')">{{ t('retry') }}</a-button>
      </a-space>
    </div>
    <p v-if="!state?.tasks?.length">{{ t('noTasks') }}</p>
    </details>
    </template>
  </section>
</template>

<script setup>
import ClientHookPanel from './ClientHookPanel.vue'
import ClientRuntimeCompatibility from './ClientRuntimeCompatibility.vue'
import ClientOnboardingAcceptance from './ClientOnboardingAcceptance.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { can } from '../access'
import { getClientRuntimeGovernance, createClientTask, cancelClientTask, retryClientTask } from '../api'
const props = defineProps({clientId: {type: String, required: true}, view: {type: String, default: 'plugins'}})
defineEmits(['collection', 'policy'])
const pluginReportsOpen = ref(false), compatibilityAnchor = ref(null)
let generation = 0
let refreshTimer, pollUntil = 0
const {t: translate, te, locale} = useI18n()
const t = key => translate(`agentRuntimeGovernance.${key}`)
const state = ref(null), loading = ref(false), busy = ref(''), error = ref('')
const refreshPaused = ref(false)
let pendingRequest = null
const supported = computed(() => state.value?.supports_tasks === true)
const activeTasks = computed(() => (state.value?.tasks || []).filter(task => ['pending','running'].includes(task.status)))
const receiverTask = computed(() => state.value?.tasks?.find(task => ['enable','disable'].includes(task.payload.action)))
const receiverAwaitingReport = computed(() => {
  const task = receiverTask.value, applied = state.value?.report?.managed_task
  return task?.status === 'succeeded' && (!/^[0-9]+$/.test(String(applied)) || BigInt(applied) < BigInt(task.id))
})
const taskRefreshNeeded = computed(() => activeTasks.value.length > 0 || receiverAwaitingReport.value || ['aidr_desktop_starting', 'aidr_desktop_health_rechecking'].includes(state.value?.report?.receiver_code))
const blocked = computed(() => !supported.value || !!busy.value || loading.value || !!error.value || taskRefreshNeeded.value)
const stamp = value => value ? new Date(value).toLocaleString(locale.value) : t('unknown')
const yes = value => t(value === true ? 'yes' : value === false ? 'no' : 'unknown')
const code = value => value && te(`agentRuntimeGovernance.codes.${value}`) ? t(`codes.${value}`) : value ? `${t('statusCode')}: ${value}` : t('unknown')
const host = agent => state.value?.report?.hosts?.find(item => item.agent === agent)
const receiverAlreadySet = action => !state.value?.stale && ((action === 'enable' && state.value?.report?.enabled === true && state.value.report.receiver_code === 'aidr_desktop_running') || (action === 'disable' && state.value?.report?.enabled === false && state.value.report.receiver_code === 'aidr_desktop_stopped'))
const actionBlocked = (action, agent) => blocked.value || receiverAlreadySet(action) || (['install','upgrade'].includes(action) && host(agent)?.version_status !== 'adapter_target')
const failure = cause => {
  const value = cause.response?.data?.error_code
  return value && te(`agentRuntimeGovernance.codes.${value}`) ? code(value) : value ? `${t('requestFailed')} ${code(value)}` : t('requestFailed')
}
function scheduleTaskRefresh() {
  clearTimeout(refreshTimer)
  if (!taskRefreshNeeded.value) { pollUntil = 0; refreshPaused.value = false; return }
  if (!pollUntil) pollUntil = Date.now() + 120000
  if (Date.now() >= pollUntil) { refreshPaused.value = true; return }
  refreshTimer = setTimeout(() => {
    if (document.hidden) scheduleTaskRefresh()
    else load(true)
  }, 5000)
}
async function load(automatic = false) {
  if (loading.value) return
  if (automatic !== true) { pollUntil = 0; refreshPaused.value = false }
  const epoch = generation
  loading.value = true; error.value = ''
  try { const result = await getClientRuntimeGovernance(props.clientId); if (epoch === generation) state.value = result }
  catch (cause) { if (epoch === generation) error.value = failure(cause) }
  finally { if (epoch === generation) { loading.value = false; scheduleTaskRefresh() } }
}
async function send(action, agent = '') {
  if (actionBlocked(action,agent)) return
  const epoch = generation, id = props.clientId
  busy.value = action+agent; error.value = ''
  try {
    if (!pendingRequest || pendingRequest.action !== action || pendingRequest.agent !== agent) pendingRequest = {request_id: crypto.randomUUID(), action, agent, plugin_version: state.value.report.plugin_version}
    await createClientTask(id, {task_type: 'aidr_plugin_action', payload: pendingRequest})
    if (epoch !== generation) return
    pendingRequest = null
    await load()
  } catch (cause) { if (epoch === generation) error.value = failure(cause) }
  finally { if (epoch === generation) busy.value = '' }
}
async function taskAction(task, action) {
  if (busy.value || loading.value) return
  const epoch = generation, id = props.clientId
  busy.value = action+task.id; error.value = ''
  try { await (action === 'cancel' ? cancelClientTask : retryClientTask)(id,task.id); if (epoch === generation) await load() }
  catch (cause) { if (epoch === generation) error.value = failure(cause) }
  finally { if (epoch === generation) busy.value = '' }
}
watch(() => props.clientId, () => {
  generation++; clearTimeout(refreshTimer); pollUntil = 0; refreshPaused.value = false
  state.value = null; loading.value = false; busy.value = ''; pendingRequest = null; error.value = ''
  load()
}, { immediate: true })
onBeforeUnmount(() => { generation++; clearTimeout(refreshTimer) })
</script>

<style scoped>
.runtime-governance { margin: 12px 0 24px; overflow-wrap: anywhere; }
.runtime-heading { display: flex; justify-content: space-between; align-items: start; gap: 16px; margin-bottom: 12px; }
.runtime-heading h3 { margin: 0 0 6px; }
.runtime-heading p { color: #627480; margin: 0; }
.runtime-heading .ant-btn { flex-shrink: 0; }
.runtime-policy-line { margin: 14px 0; color: #526873; }
dl { display: grid; grid-template-columns: minmax(100px, 180px) minmax(0, 1fr); gap: 8px; } dd { margin: 0; }
.runtime-summary { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }
.runtime-summary > div { min-width: 0; border: 1px solid #dce4e8; border-radius: 10px; background: #f8fafb; padding: 14px; }
.runtime-summary dt { color: #627480; font-size: 12px; margin-bottom: 8px; }
.runtime-summary dd { font-weight: 600; font-size: 14px; }
.runtime-hosts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 18px 0; }
.runtime-host { border: 1px solid #dce4e8; padding: 18px; border-radius: 10px; min-width: 0; }
.runtime-host > strong { display: block; font-size: 17px; margin-bottom: 12px; }
.runtime-host p { line-height: 1.6; color: #526873; }
.runtime-host .ant-btn { height: auto; min-height: 32px; white-space: normal; }
.runtime-diagnostics, .runtime-task-history { border-top: 1px solid #e5ebee; padding: 14px 0; }
summary { cursor: pointer; color: #526873; font-weight: 500; }
.runtime-task { border-bottom: 1px solid #eee; padding: 14px 0; }
@media (max-width: 760px) { .runtime-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } .runtime-hosts { grid-template-columns: minmax(0, 1fr); } }
</style>
