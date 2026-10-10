<template>
  <section class="device-overview" :aria-busy="loading">
    <div class="inventory">
      <button @click="emit('navigate', 'skills')"><AppstoreOutlined /><strong>{{ t('agentRuntimeGovernance.detail.inventoryCount', { agents: agentsCount, skills: skillsCount }) }}</strong><RightOutlined /></button>
      <button @click="emit('navigate', 'plugins')"><ApiOutlined /><strong>{{ installed }}</strong><RightOutlined /></button>
      <button @click="emit('navigate', 'control')"><SafetyCertificateOutlined /><strong>{{ approvals ? t('clientDetail.pending', { count: pendingCount }) : tr('unknown') }}</strong><a-tooltip :title="t('agentRuntimeGovernance.detail.approvalWindow')"><InfoCircleOutlined /></a-tooltip></button>
    </div>
    <ClientOverviewStatistics ref="statistics" :client-id="client.client_id" @activity="emit('activity', $event)" />
    <div class="health">
      <button @click="emit('navigate', 'collection')"><ApiOutlined /><div><b>Hook</b><span>{{ receiverState }}</span><small>{{ reportTime(runtime?.reported_at) }}</small></div><RightOutlined /></button>
      <button @click="emit('navigate', 'collection')"><FileTextOutlined /><div><b>{{ tr('logs') }}</b><span>{{ logState }}</span><small>{{ reportTime(logs?.last_seen_at) }}</small></div><RightOutlined /></button>
      <button @click="emit('navigate', 'systemEvents')"><DesktopOutlined /><div><b>{{ t('clientDetail.system') }}</b><span>{{ system?.state === 'collecting' ? t('clientDetail.collectionOnly') : system ? t('aidr.enforcement.states.' + (system.state || 'unknown')) : tr('unknown') }}</span><small>{{ reportTime(system?.last_received_at) }}</small></div><RightOutlined /></button>
    </div>
    <div class="section-heading"><h3>{{ tr('attention') }} <a-badge v-if="sourceIssues.length + tasks.length" :count="sourceIssues.length + tasks.length" :number-style="{ backgroundColor: '#a96b20' }" /></h3><div><a-button type="link" @click="sourcesVisible = true">{{ tr('historicalSources') }}</a-button><a-button type="link" @click="openHistory">{{ tr('history') }}</a-button><a-button :loading="loading" @click="load">{{ tr('refresh') }}</a-button></div></div>
    <a-alert v-for="entry in errors" :key="entry" type="warning" show-icon :message="entry === 'tasks' ? tr('taskReadFailed') : t('agentRuntimeGovernance.detail.summaryFailed', { section: t('agentRuntimeGovernance.detail.' + entry) })" />
    <div v-if="loading && !settled" class="loading"><a-skeleton active :paragraph="{ rows: 2 }" /></div>
    <p v-else-if="!sourceIssues.length && !tasks.length" class="quiet"><CheckCircleOutlined v-if="!uncertain" /><InfoCircleOutlined v-else /> {{ tr(uncertain ? 'incomplete' : 'healthy') }}</p>
    <div v-for="entry in sourceIssues" :key="entry.agent" class="issue"><ExclamationCircleOutlined /><div><strong>{{ entry.name }}</strong><p>{{ entry.labels.join(' · ') }}</p></div><a-button @click="emit('navigate', 'collection')">{{ tr('inspect') }}</a-button></div>
    <details v-for="task in tasks" :key="task.id" class="task"><summary><strong>{{ taskTitle(task) }}</strong><a-tag :color="taskColor(task)">{{ taskStatus(task) }}</a-tag><span>{{ taskTarget(task) }} · {{ taskTime(task.created_at) }}</span></summary><p v-if="task.error_code">{{ errorLabel(task.error_code) }} <code>{{ task.error_code }}</code></p><p>#{{ task.id }}<span v-if="task.payload?.policy_version"> · {{ t('agentRuntimeGovernance.taskSummary.policy', { version: task.payload.policy_version }) }}</span></p><p v-if="task.payload?.target">{{ targetChannels(task.payload.target) }}</p></details>
    <p v-if="taskData?.attention_truncated" class="muted">{{ tr('taskMore') }}</p>
    <a-modal v-model:open="sourcesVisible" :title="tr('historicalSources')" :footer="null" width="680px">
      <p class="muted">{{ reportTime(logs?.last_seen_at) }}</p><p v-if="!discovery.length">{{ tr('unknown') }}</p>
      <div v-for="(entry, index) in discovery" :key="index" class="source-detail"><h4>{{ productName(entry.agent) }}</h4><p v-if="entry.historical_missing">{{ tr('historicalMissing', { count: entry.historical_missing }) }}</p><p v-if="entry.historical_missing" class="muted">{{ tr('historicalBoundary') }}</p><p v-for="label in sourceLabels(entry)" :key="label">{{ label }}</p><p v-if="!entry.historical_missing && !sourceLabels(entry).length">{{ tr('noSourceIssues') }}</p></div>
      <a-button @click="sourcesVisible = false; emit('navigate', 'collection')">{{ t('clientDetail.checkCollection') }}</a-button>
    </a-modal>
    <a-modal v-model:open="historyVisible" :title="tr('history')" :footer="null" width="850px"><p class="muted">{{ tr('taskScope') }}</p><a-alert v-if="historyError" type="error" :message="tr('taskReadFailed')"><template #action><a-button @click="loadHistory(false)">{{ tr('retry') }}</a-button></template></a-alert>
      <details v-for="task in history" :key="task.id" class="task"><summary><strong>{{ taskTitle(task) }}</strong><a-tag :color="taskColor(task)">{{ taskStatus(task) }}</a-tag><span>{{ taskTarget(task) }} · {{ taskTime(task.created_at) }}</span></summary><p>#{{ task.id }}<span v-if="task.payload?.policy_version"> · {{ t('agentRuntimeGovernance.taskSummary.policy', { version: task.payload.policy_version }) }}</span></p><p v-if="task.error_code">{{ errorLabel(task.error_code) }} <code>{{ task.error_code }}</code></p><p v-if="task.payload?.target">{{ targetChannels(task.payload.target) }}</p><p v-if="task.finished_at">{{ t('agentRuntimeGovernance.taskSummary.finished', { time: taskTime(task.finished_at) }) }}</p></details>
      <a-empty v-if="!history.length && !historyLoading && !historyError" :description="tr('empty')" /><a-spin v-if="historyLoading" /><a-button v-if="historyCursor" :loading="historyLoading" @click="loadHistory(true)">{{ tr('more') }}</a-button>
    </a-modal>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AppstoreOutlined, ApiOutlined, SafetyCertificateOutlined, InfoCircleOutlined, RightOutlined, FileTextOutlined, DesktopOutlined, ExclamationCircleOutlined, CheckCircleOutlined } from '@ant-design/icons-vue'
import { translateDomain } from '../i18n'
import products from '../aidr-products.json'
import ClientOverviewStatistics from './ClientOverviewStatistics.vue'
import { getClientRuntimeGovernance, getClientAidrStatus, getEnforcement, listHookApprovals, getClientAidrOverviewTasks } from '../api'
const props = defineProps({ client: { type: Object, required: true } }), emit = defineEmits(['navigate', 'activity'])
const { t, te, locale } = useI18n(), tr = (key, params) => t('clientOverview.' + key, params)
const runtime = ref(null), logs = ref(null), system = ref(null), approvals = ref(null), taskData = ref(null), errors = ref([]), loading = ref(false), settled = ref(false), statistics = ref(null)
let generation = 0
const agentsCount = computed(() => (props.client.agents || []).filter(agent => agent.agent_type !== 'global-skills').length)
const skillsCount = computed(() => (props.client.agents || []).reduce((total, agent) => total + (agent.skills || []).length, 0))
const installed = computed(() => runtime.value?.report?.hosts?.length && !runtime.value.stale ? t('clientDetail.installed', { count: runtime.value.report.hosts.filter(host => host.installed === true).length }) : tr('unknown'))
const receiverState = computed(() => { const code = runtime.value?.report?.receiver_code; return !runtime.value?.stale && code && te('agentRuntimeGovernance.codes.' + code) ? t('agentRuntimeGovernance.codes.' + code) : tr('unknown') })
const logState = computed(() => t('aidr.channelHealth.' + (logs.value?.log_channel?.health?.state || 'policy_unknown')))
const pendingCount = computed(() => approvals.value?.items?.filter(row => row.state === 'pending').length ?? 0)
const discovery = computed(() => (logs.value?.health?.discovery || []).map(entry => ({ ...entry, ...(entry.progress || {}) })))
const productName = id => products.find(p => p.id === id)?.name || id || tr('unknown')
function sourceLabels(entry) {
  const labels = []
  if (entry.unread_missing) labels.push(tr('missingUnread', { count: entry.unread_missing }))
  if (entry.missing_directories) labels.push(tr('missingDirectories', { count: entry.missing_directories }))
  const reasons = { aidr_log_permission_denied: 'permission', aidr_log_discovery_capacity: 'capacity', aidr_log_discovery_depth: 'depth', aidr_log_io_error: 'readError', aidr_log_symlink: 'symlink', aidr_log_source_outside_root: 'outsideRoot', aidr_log_invalid_json: 'format', aidr_log_schema_unsupported: 'format' }
  for (const code of entry.reason_codes || []) {
    if (code === 'aidr_log_source_missing') { if (!entry.historical_missing && !entry.unread_missing && !entry.missing_directories) labels.push(tr('missingUnknown')) }
    else if (['aidr_log_discovery_pending', 'aidr_log_discovery_budget'].includes(code)) labels.push(t('collectionStatus.states.source_scanning'))
    else labels.push(reasons[code] && te('collectionStatus.logReason.' + reasons[code]) ? t('collectionStatus.logReason.' + reasons[code]) : t('clientDetail.logUnknown'))
  }
  return [...new Set(labels)]
}
const logSourceIssues = computed(() => {
  if (!logs.value?.online || logs.value?.log_channel?.target_enabled !== true || logs.value?.log_channel?.report?.policy_version !== logs.value?.log_channel?.target_version) return []
  const groups = new Map()
  for (const entry of discovery.value) { const labels = sourceLabels({ ...entry, reason_codes: (entry.reason_codes || []).filter(code => !['aidr_log_discovery_pending', 'aidr_log_discovery_budget'].includes(code)) }); if (!labels.length) continue; const group = groups.get(entry.agent) || { agent: entry.agent, name: productName(entry.agent), labels: [] }; group.labels = [...new Set([...group.labels, ...labels])]; groups.set(entry.agent, group) }
  return [...groups.values()]
})
const sourceIssues = computed(() => [...logSourceIssues.value, ...['hooks', 'logs', 'system'].flatMap(channel => { const state = channel === 'logs' ? logs.value?.log_channel : runtime.value?.channels?.[channel]; return state?.health?.severity === 'warning' ? [{ agent: 'channel-' + channel, name: channel === 'hooks' ? 'Hook' : channel === 'logs' ? tr('logs') : t('clientDetail.system'), labels: [tr('channelAttention')] }] : [] })])
const tasks = computed(() => taskData.value?.attention || [])
const uncertain = computed(() => errors.value.length || runtime.value?.stale || !runtime.value?.report || !logs.value || !system.value || ['policy_unknown', 'unreported', 'stale', 'awaiting_application'].includes(logs.value?.log_channel?.health?.state) || system.value?.state === 'unknown')
const superseded = task => (task.error_code || task.error) === 'aidr_desktop_task_superseded' || (task.error_code || task.error) === 'policy_superseded'
const taskStatus = task => superseded(task) ? t('agentRuntimeGovernance.taskSummary.superseded') : t('agentRuntimeGovernance.' + task.status)
const taskColor = task => superseded(task) ? 'default' : ({ succeeded: 'green', failed: 'red', running: 'blue' }[task.status] || 'default')
const taskTitle = task => {
  const action = task.payload?.action
  if (task.task_type === 'aidr_plugin_action') return t('agentRuntimeGovernance.taskSummary.' + (['install', 'upgrade', 'inspect', 'enable', 'disable', 'reconcile'].includes(action) ? action : 'generic'))
  if (task.task_type === 'skill_action' && action && te('clientGovernance.' + action)) return t('clientGovernance.' + action)
  return translateDomain('taskType', task.task_type, task.task_type)
}
const taskTarget = task => {
  const payload = task.payload || {}
  if (task.task_type !== 'aidr_plugin_action') return payload.skill_name || payload.agent_type || t('agentRuntimeGovernance.taskSummary.device')
  const hosts = payload.agent ? [payload.agent] : payload.target?.hosts || []
  return hosts.length ? hosts.map(id => products.find(product => product.id === id)?.name || id).join(' / ') : t('agentRuntimeGovernance.taskSummary.device')
}
const targetChannels = target => ['logs', 'hooks', 'system'].map(channel => `${t('agentRuntimeGovernance.taskSummary.' + channel)}: ${t('agentRuntimeGovernance.taskSummary.' + (target.enabled === false || target.channels?.[channel] === false ? 'off' : target.channels?.[channel] === true ? 'on' : 'unknown'))}`).join(' · ')
const taskTime = value => value ? new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(String(value)) ? value : `${value}Z`).toLocaleString(locale.value) : t('agentRuntimeGovernance.unknown')
const errorLabel = code => te('agentRuntimeGovernance.codes.' + code) ? t('agentRuntimeGovernance.codes.' + code) : t('agentRuntimeGovernance.taskSummary.details')
const reportTime = value => {
  if (!value) return t('agentRuntimeGovernance.detail.notReported')
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(String(value)) ? value : `${value}Z`
  return t('agentRuntimeGovernance.detail.reportAt', { time: new Date(normalized).toLocaleString(locale.value) })
}

const sourcesVisible = ref(false), historyVisible = ref(false), history = ref([]), historyCursor = ref(null), historyLoading = ref(false), historyError = ref(false)
function openHistory() { historyVisible.value = true; loadHistory(false) }
async function loadHistory(append) { if (historyLoading.value) return; const epoch = generation; historyLoading.value = true; historyError.value = false; try { const result = await getClientAidrOverviewTasks(props.client.client_id, append ? { before: historyCursor.value } : {}); if (epoch !== generation) return; history.value = append ? [...history.value, ...result.history] : result.history; historyCursor.value = result.next_cursor } catch { if (epoch === generation) historyError.value = true } finally { if (epoch === generation) historyLoading.value = false } }
async function load() {
  if (loading.value) return
  loading.value = true
  const epoch = generation, id = props.client.client_id
  const resources = [['plugins', runtime, () => getClientRuntimeGovernance(id)], ['collection', logs, () => getClientAidrStatus(id, { include_retention: false })], ['systemState', system, () => getEnforcement(id, 'status')], ['control', approvals, () => listHookApprovals(id, { limit: 50 })], ['tasks', taskData, () => getClientAidrOverviewTasks(id)]]
  const results = await Promise.allSettled(resources.map(([, , request]) => request()))
  if (epoch !== generation) return
  errors.value = []
  results.forEach((result, index) => { const [name, target] = resources[index]; if (result.status === 'fulfilled') target.value = result.value; else { target.value = null; errors.value.push(name) } })
  loading.value = false; settled.value = true
}
watch(() => props.client.client_id, () => { generation++; loading.value = false; settled.value = false; sourcesVisible.value = false; historyVisible.value = false; historyLoading.value = false; runtime.value = logs.value = system.value = approvals.value = taskData.value = null; load() }, { immediate: true })
defineExpose({ refresh: () => { load(); statistics.value?.refresh() } })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.device-overview{padding:12px 0}.inventory{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:22px}.inventory button{display:flex;align-items:center;gap:10px;background:#f7f9fc;border:1px solid #e3e9f1;border-radius:7px;padding:11px 16px;cursor:pointer;color:#42546b}.inventory strong{font-weight:500}.section-heading{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin:22px 0 8px}.section-heading h3{margin:0;font-size:16px}.muted{color:#78889d;font-size:12px}.health{margin-top:18px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid #e3e9f1;border-radius:10px}.health button{display:flex;align-items:center;gap:12px;padding:17px;background:none;border:0;border-right:1px solid #e3e9f1;text-align:left;cursor:pointer;color:#42546b;min-width:0}.health button:last-child{border:0}.health button>div{flex:1;min-width:0}.health span,.health small,.health b{display:block;overflow-wrap:anywhere}.health b{font-size:14px;color:#25354b}.health span{font-size:13px;margin:5px 0}.health small{color:#78889d;font-size:11px}.quiet{display:flex;align-items:center;gap:9px;background:#f8fafb;border-radius:7px;padding:15px;color:#627480}.issue{display:flex;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid #e3e9f1}.issue>div{flex:1}.issue p{margin:4px 0;color:#78889d}.issue>.anticon{color:#a96b20}.task{border-top:1px solid #e3e9f1;padding:14px 0;overflow-wrap:anywhere}.task summary{cursor:pointer;line-height:2}.task summary>*{margin-right:10px}.task summary>span:not(.ant-tag){color:#78889d;font-size:12px}.task p{margin:8px 0}.source-detail{border-top:1px solid #e3e9f1;padding:14px 0}.source-detail h4{margin:0 0 8px}.device-overview :deep(.ant-alert){margin:10px 0}button:hover{background:#f5f8ff}button:focus-visible{outline:2px solid #285ff5;outline-offset:2px}@media(max-width:850px){.health{grid-template-columns:1fr}.health button{border-right:0;border-bottom:1px solid #e3e9f1}.inventory{gap:8px}.inventory button{padding:9px 11px}}
</style>
