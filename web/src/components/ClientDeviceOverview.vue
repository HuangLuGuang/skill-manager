<template>
  <section class="device-overview">
    <div class="overview-cards">
      <button class="overview-card" @click="$emit('navigate', 'skills')">
        <span>{{ t('agentRuntimeGovernance.detail.skills') }}</span><strong>{{ t('agentRuntimeGovernance.detail.inventoryCount', { agents: agentsCount, skills: skillsCount }) }}</strong>
      </button>
      <button class="overview-card" @click="$emit('navigate', 'plugins')">
        <span>{{ t('agentRuntimeGovernance.tabs.plugins') }}</span><strong>{{ installed }}</strong><small>{{ reportTime(runtime?.reported_at) }}</small><small v-if="runtime?.stale">{{ t('agentRuntimeGovernance.stale') }}</small>
      </button>
      <button class="overview-card" @click="$emit('navigate', 'collection')">
        <span>{{ t('agentRuntimeGovernance.detail.collection') }}</span><strong>{{ t('agentRuntimeGovernance.detail.hookChannel') }}: {{ receiverState }}</strong><small>{{ reportTime(runtime?.reported_at) }}</small><small v-if="runtime?.stale">{{ t('agentRuntimeGovernance.stale') }}</small><strong>{{ t('agentRuntimeGovernance.detail.logChannel') }}: {{ logState }}</strong><small>{{ reportTime(logs?.last_seen_at) }}</small>
      </button>
      <button class="overview-card" @click="$emit('navigate', 'control')">
        <span>{{ t('agentRuntimeGovernance.detail.control') }}</span><strong>{{ approvals ? t('agentRuntimeGovernance.detail.pendingSummary', { count: pendingCount }) : t('agentRuntimeGovernance.unknown') }}</strong><small>{{ t('agentRuntimeGovernance.detail.approvalWindow') }}</small>
      </button>
    </div>
    <a-alert v-for="entry in errors" :key="entry" type="error" show-icon :message="t('agentRuntimeGovernance.detail.summaryFailed', { section: t('agentRuntimeGovernance.detail.' + entry) })" :description="t('agentRuntimeGovernance.detail.readFailed')" />
    <a-alert v-if="healthCodes.length" type="warning" show-icon :message="t('aidr.coverageWarning')"><template #description><code v-for="code in healthCodes" :key="code">{{ reasonLabel(code) }} </code></template></a-alert>
    <div class="overview-system"><span>{{ t('agentRuntimeGovernance.detail.systemState') }}</span><strong>{{ system ? t('aidr.enforcement.states.' + (system.state || 'unknown')) : t('agentRuntimeGovernance.unknown') }}</strong><span v-if="system?.last_received_at">{{ reportTime(system.last_received_at) }}</span><a-button type="link" @click="$emit('navigate', 'systemControl')">{{ t('agentRuntimeGovernance.detail.control') }}</a-button></div>
    <h4>{{ t('agentRuntimeGovernance.detail.attentionTasks') }}</h4>
    <p v-if="!attentionTasks.length" class="muted">{{ t('agentRuntimeGovernance.detail.noAttentionTasks') }}</p>
    <div v-for="task in attentionTasks" :key="task.id" class="attention-task"><span>#{{ task.id }} · {{ translateDomain('taskType', task.task_type, task.task_type) }}</span><a-tag>{{ t('agentRuntimeGovernance.' + task.status) }}</a-tag><span v-if="task.error_code || task.error">{{ errorLabel(task.error_code || task.error) }}</span><a-button type="link" @click="$emit('navigate', task.task_type === 'aidr_plugin_action' ? 'plugins' : 'skills')">{{ t('agentRuntimeGovernance.detail.viewTask') }}</a-button></div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { translateDomain } from '../i18n'
import { getClientRuntimeGovernance, getClientAidrStatus, getEnforcement, listHookApprovals } from '../api'
const props = defineProps({ client: { type: Object, required: true } })
defineEmits(['navigate'])
const { t, te, locale } = useI18n()
const runtime = ref(null), logs = ref(null), system = ref(null), approvals = ref(null), errors = ref([]), loading = ref(false)
let generation = 0
const agentsCount = computed(() => (props.client.agents || []).filter(agent => agent.agent_type !== 'global-skills').length)
const skillsCount = computed(() => (props.client.agents || []).reduce((total, agent) => total + (agent.skills || []).length, 0))
const installed = computed(() => runtime.value?.report?.hosts?.length ? t('agentRuntimeGovernance.detail.installedCount', { count: runtime.value.report.hosts.filter(host => host.installed === true).length, total: runtime.value.report.hosts.length }) : t('agentRuntimeGovernance.unknown'))
const receiverState = computed(() => {
  if (runtime.value?.stale) return t('agentRuntimeGovernance.unknown')
  const code = runtime.value?.report?.receiver_code
  return code && te('agentRuntimeGovernance.codes.' + code) ? t('agentRuntimeGovernance.codes.' + code) : t('agentRuntimeGovernance.unknown')
})
const logState = computed(() => t('aidr.channelHealth.' + (logs.value?.log_channel?.health?.state || 'policy_unknown')))
const pendingCount = computed(() => approvals.value?.items.filter(row => row.state === 'pending').length ?? 0)
const healthCodes = computed(() => logs.value?.log_channel?.target_enabled !== true || !logs.value?.online || logs.value?.log_channel?.report?.policy_version !== logs.value?.log_channel?.target_version ? [] : [...new Set((logs.value?.health?.discovery || []).flatMap(entry => entry.reason_codes || []))])
const attentionTasks = computed(() => (props.client.tasks || []).filter(task => ['pending', 'running', 'failed'].includes(task.status)).slice(0, 5))
const reasonKeys = { aidr_audit_collection_disabled: 'collectionDisabled', aidr_log_discovery_budget: 'budget', aidr_log_discovery_pending: 'pending', aidr_log_discovery_capacity: 'capacity', aidr_log_schema_unsupported: 'format', aidr_log_record_too_large: 'large', aidr_log_version_unverified: 'version', aidr_upload_reporting_paused: 'reportingPaused', aidr_upload_auth_rejected: 'credentialRejected', aidr_log_call_capacity: 'callCapacity', aidr_log_call_conflict: 'callConflict', aidr_log_call_unresolved: 'callUnresolved', aidr_log_optional_record_skipped: 'optionalSkipped', aidr_log_context_invalidated: 'contextInvalidated', aidr_log_timestamp_future: 'timestampFuture', aidr_audit_history_retention: 'historyRetired', aidr_store_capacity_warning: 'capacityWarning', aidr_store_capacity: 'storeCapacity' }
const reasonLabel = code => reasonKeys[code] ? `${t('aidr.diagnosticReasons.' + reasonKeys[code])} (${code})` : t('clientGovernance.errorDetail', { error: code })
const errorLabel = code => te('agentRuntimeGovernance.codes.' + code) ? `${t('agentRuntimeGovernance.codes.' + code)} (${code})` : t('clientGovernance.errorDetail', { error: code })
const reportTime = value => {
  if (!value) return t('agentRuntimeGovernance.detail.notReported')
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(String(value)) ? value : `${value}Z`
  return t('agentRuntimeGovernance.detail.reportAt', { time: new Date(normalized).toLocaleString(locale.value) })
}
async function load() {
  if (loading.value) return
  loading.value = true
  const epoch = generation, id = props.client.client_id
  const resources = [['plugins', runtime, () => getClientRuntimeGovernance(id)], ['collection', logs, () => getClientAidrStatus(id)], ['systemState', system, () => getEnforcement(id, 'status')], ['control', approvals, () => listHookApprovals(id, { limit: 50 })]]
  const results = await Promise.allSettled(resources.map(([, , request]) => request()))
  if (epoch !== generation) return
  errors.value = []
  results.forEach((result, index) => { const [name, target] = resources[index]; if (result.status === 'fulfilled') target.value = result.value; else { target.value = null; errors.value.push(name) } })
  loading.value = false
}
onMounted(load)
defineExpose({ refresh: load })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.overview-system, .attention-task { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.overview-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
.overview-card { text-align: left; background: #f8fafb; border: 1px solid #dce4e8; border-radius: 10px; padding: 16px; cursor: pointer; font: inherit; color: inherit; overflow-wrap: anywhere; }
.overview-card:hover, .overview-card:focus-visible { border-color: #d7644c; outline: 2px solid #f9e2db; }
.overview-card span, .overview-card strong, .overview-card small { display: block; }.overview-card strong { margin: 8px 0; }
.overview-card span, .overview-card small, .muted { color: #627480; }.device-overview :deep(.ant-alert) { margin: 12px 0; }
code { overflow-wrap: anywhere; }.overview-system { border-block: 1px solid #e5ebee; padding: 12px 0; }
@media (max-width: 480px) { .overview-cards { grid-template-columns: minmax(0, 1fr); } }
</style>
