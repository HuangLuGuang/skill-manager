<template>
  <section class="agent-workspace" :class="{ 'audit-workspace': tab === 'audit' }">
    <div class="workspace-breadcrumb"><a-button type="link" @click="emit('back')"><ArrowLeftOutlined />{{ tr('back') }}</a-button><span>/</span><span>{{ t('agentAssets.source.client') }}</span><span>/</span><span>{{ asset.name }}</span></div>
    <header class="workspace-heading"><div class="identity"><span class="product-logo"><AgentProductLogo :product-id="productId" /></span><div><h1>{{ displayName }} <a-tag :color="attention ? 'orange' : 'default'">{{ tr(attention ? 'attention' : 'unconfirmed') }}</a-tag></h1><p>{{ t('agentAssets.source.client') }} · {{ instance?.os }} / {{ instance?.arch }} · {{ tr('reported', { time: stamp(runtime?.reported_at || instance?.client_last_seen_at) }) }}</p></div></div><a-button :loading="loading" :disabled="loading" @click="refresh"><ReloadOutlined />{{ tr('refresh') }}</a-button></header>
    <a-empty v-if="!instance" :description="tr('noSelection')" />
    <template v-else>
      <div class="workspace-scope"><span>{{ tr('client') }}</span><strong>{{ instance.client_name }}</strong><a-tag :color="client?.status === 'online' ? 'green' : 'default'">{{ t(`agentAssets.filters.${client?.status || instance.client_status || 'offline'}`) }}</a-tag><label for="workspace-instance">{{ tr('installation') }}</label><a-select id="workspace-instance" v-model:value="instanceKey" :options="instanceOptions" :aria-label="tr('installation')" /><a-button v-if="can('clients:view')" class="client-link" type="link" @click="openClient('overview')">{{ tr('clientLink') }}<RightOutlined /></a-button></div>
      <a-alert v-if="!can('clients:view')" type="info" show-icon :message="tr('noPermission')" />
      <a-alert v-else-if="errors.length" type="warning" show-icon :message="tr(missing ? 'missingInstance' : 'readFailed')"><template #action><a-button :loading="loading" :disabled="loading" @click="refresh">{{ tr('refresh') }}</a-button></template></a-alert>
      <nav class="workspace-tabs" :aria-label="tr('title')"><button v-for="item in tabs" :key="item" type="button" :aria-current="tab === item ? 'page' : undefined" :class="{ selected: tab === item }" @click="selectTab(item)">{{ tr(item) }}</button></nav>
      <div class="workspace-body" :class="{ 'audit-body': tab === 'audit' }" tabindex="0" role="region" :aria-label="tr(tab)">
      <a-skeleton v-if="loading && !loaded" active :paragraph="{ rows: 7 }" />
      <template v-else-if="tab === 'overview'">
        <div v-if="attention" class="workspace-notice"><div><strong>{{ tr('attention') }}</strong><p>{{ attentionSummary }}</p></div><a-button :disabled="!can('clients:view')" @click="diagnostic = true">{{ tr('diagnose') }}</a-button></div>
        <div class="workspace-stats"><div><span>{{ tr('recentSessions') }}</span><strong>{{ sessions ? `${sessions.items.length}${sessions.has_more ? '+' : ''}` : '—' }}</strong><small>{{ tr('sessions') }}</small></div><div><span>{{ tr('localSkills') }}</span><strong>{{ agent ? agent.skills?.length ?? '—' : '—' }}</strong><small>{{ tr('scopeInstance') }}</small></div><div><span>{{ tr('configuredModel') }}</span><strong>{{ configuredModel }}</strong><small>{{ tr('modelHint') }}</small></div><div><span>{{ tr('effectivePolicy') }}</span><strong>{{ policyMode }}</strong><small>{{ policySource }}</small></div></div>
        <div class="workspace-columns"><div><section class="workspace-panel"><header><div><h2>{{ tr('sources') }}</h2><small>{{ tr('sourceHint') }}</small></div><a-button type="link" :disabled="!can('clients:view')" @click="diagnostic = true">{{ tr('view') }}</a-button></header><div class="panel-body"><div v-for="row in channels" :key="row.id" class="health-row"><div><strong>{{ tr(row.id) }}</strong><p>{{ row.id === 'system' || row.id === 'receiver' ? tr('sharedScope') : tr('latestArrival', { time: stamp(row.arrival) }) }}</p></div><a-tag :color="row.warning ? 'orange' : row.state === 'received' ? 'green' : 'default'">{{ stateLabel(row.state) }}</a-tag></div></div></section><section class="workspace-panel"><header><h2>{{ tr('installation') }}</h2><a-button type="link" @click="evidence = true">{{ tr('evidence') }}</a-button></header><dl class="workspace-meta"><dt>{{ tr('version') }}</dt><dd>{{ agent?.version || instance.agent_version || tr('unknown') }}</dd><dt>{{ tr('path') }}</dt><dd>{{ agent?.install_path || instance.install_path || tr('unknown') }}</dd><dt>{{ tr('skillsPath') }}</dt><dd>{{ agent?.skills_path || instance.skills_path || tr('unknown') }}</dd></dl></section></div><div><section class="workspace-panel"><header><h2>{{ tr('recent') }}</h2><a-button type="link" @click="selectTab('audit')">{{ tr('viewAll') }}</a-button></header><div class="panel-body"><a-empty v-if="!sessions?.items.length" :description="tr(errors.includes('sessions') ? 'readFailed' : 'empty')" /><button v-for="item in sessions?.items || []" :key="item.session_id || item.orphan_id" class="session-preview" @click="openSession(item)"><span class="activity-dot" /><span><strong>{{ item.question_preview || item.session_id || '#' + item.orphan_id }}</strong><small>{{ stamp(item.latest_at) }}</small></span><RightOutlined /></button></div></section><section class="workspace-panel"><header><h2>{{ tr('client') }}</h2></header><div class="panel-body"><p class="muted">{{ tr('clientSummary') }}</p><a-button type="link" @click="openClient('overview')">{{ tr('clientLink') }}<RightOutlined /></a-button></div></section></div></div>
      </template>
      <template v-else-if="tab === 'capabilities'">
        <p class="scope-note">{{ tr('scopeInstance') }}</p>
        <section class="workspace-panel"><header><h2>{{ tr('localSkills') }}</h2></header><a-alert v-if="!agent?.skills_path && !agent?.capabilities?.skill_roots?.length" type="info" :message="tr('skillsUnavailable')" /><a-table :columns="skillColumns" :data-source="agent?.skills || []" row-key="path" :pagination="{ pageSize: 10, hideOnSinglePage: true }" :scroll="{ x: 760 }" size="middle"><template #bodyCell="{ column, record }"><template v-if="column.key === 'name'"><strong>{{ record.name }}</strong><small class="path-text">{{ record.path }}</small></template><template v-else-if="column.key === 'certification'"><a-tag :color="isCertified(record) ? 'green' : 'orange'">{{ tr(isCertified(record) ? 'certified' : 'uncertified') }}</a-tag></template><template v-else-if="column.key === 'actions'"><div class="skill-action-row"><a-button type="link" @click="selectedSkill = record">{{ tr('view') }}</a-button><ClientSkillActions v-if="client && agent" :client="client" :agent="agent" :skill="record" @created="taskCreated" /></div></template></template></a-table></section>
        <section v-if="client?.recovery?.length" class="workspace-panel"><header><h2>{{ tr('recovery') }}</h2></header><a-table :columns="recoveryColumns" :data-source="client.recovery" row-key="id" :pagination="{ pageSize: 5, hideOnSinglePage: true }" :scroll="{ x: 650 }"><template #bodyCell="{ column, record }"><template v-if="column.key === 'actions'"><ClientSkillActions :client="client" :agent="agent" :skill="record" recovery @created="taskCreated" /></template></template></a-table></section>
        <section class="workspace-panel"><header><h2>{{ tr('configuredModel') }}</h2></header><div class="panel-body"><dl class="workspace-meta inline"><dt>{{ tr('configuredModel') }}</dt><dd><strong>{{ configuredModel }}</strong></dd><dt>{{ tr('modelSource') }}</dt><dd>{{ modelSource }}</dd><dt>{{ tr('modelTaskState') }}</dt><dd>{{ agent?.model_config_status === 'not_configured' ? tr('modelNotManaged') : translated('agentAssets.drawer.modelStatuses', agent?.model_config_status) }}</dd></dl><p class="muted">{{ tr('modelHint') }}</p><AgentModelConfiguration v-if="client && agent" :key="instanceKey" :client="client" :agent="agent" :pending="modelPending" @created="taskCreated" /></div></section>
        <section class="workspace-panel"><header><h2>{{ tr('plugins') }}</h2><a-button @click="pluginsOpen = true">{{ tr('view') }}</a-button></header><div class="panel-body"><ClientHookConnection v-if="connection" :value="connection" /><p v-else class="muted">{{ tr('unknown') }}</p></div></section>
      </template>
      <template v-else-if="tab === 'audit'">
        <a-radio-group v-model:value="auditTab" button-style="solid" class="workspace-segments"><a-radio-button value="sessions">{{ tr('sessions') }}</a-radio-button><a-radio-button value="system">{{ tr('system') }}</a-radio-button></a-radio-group>
        <p class="scope-note">{{ tr(auditTab === 'sessions' ? 'scopeProduct' : 'scopeSystem') }}</p>
        <div v-if="auditTab === 'sessions'" class="workspace-audit"><ClientAuditSessions :key="instance.client_id + productId" v-model:source="auditSource" :client-id="instance.client_id" :fixed-agent="productId" :activity-request="activityRequest" @collection="diagnostic = true" /></div>
        <div v-else-if="agent?.install_path" class="workspace-system"><ClientEnforcementPanel :key="instanceKey" :client-id="instance.client_id" view="events" :fixed-root="agent.install_path" @collection="diagnostic = true" /></div><a-empty v-else :description="tr('systemNoPath')" />
      </template>
      <template v-else-if="tab === 'policy'">
        <p class="scope-note">{{ tr('scopeProduct') }}</p><section class="workspace-panel"><header><h2>{{ tr('effectivePolicy') }}</h2><a-button v-if="can('clients:view')" @click="openClient('control')">{{ tr('managePolicy') }}</a-button></header><div class="panel-body"><dl class="workspace-meta inline"><dt>{{ tr('policySource') }}</dt><dd>{{ policySource }}</dd><dt>{{ tr('policyVersion') }}</dt><dd>{{ policy?.revision || tr('unknown') }}</dd><dt>{{ tr('policyMode') }}</dt><dd>{{ policyMode }}</dd><dt>{{ t('aidr.hooks.defaultAction') }}</dt><dd>{{ translated('aidr.hooks', policy?.policy?.default_action) }}</dd><dt>{{ tr('actualMode') }}</dt><dd>{{ observedMode }} · {{ tr('sharedScope') }}</dd><dt>{{ tr('actualPolicy') }}</dt><dd>{{ currentHookReport?.control_revision || tr('unknown') }}</dd></dl><p class="muted">{{ tr('policyBoundary') }}</p><details><summary>{{ tr('relatedRules') }}</summary><a-table :data-source="rules" :columns="ruleColumns" row-key="id" :pagination="false"><template #bodyCell="{ column, record }"><template v-if="column.key === 'rule'"><strong>{{ record.id }}</strong><pre>{{ record.command ? JSON.stringify(record.command, null, 2) : record.tool }}</pre></template><template v-else-if="column.key === 'decision'">{{ translated('aidr.hooks', record.decision) }}</template></template></a-table></details></div></section>
        <section class="workspace-panel approvals-panel"><header><h2>{{ tr('approvals') }}</h2></header><div class="panel-body"><ClientHookPanel :key="instance.client_id + productId" :client-id="instance.client_id" :fixed-agent="productId" view="control" control-section="approvals" /></div></section>
      </template>
      <template v-else-if="tab === 'history'">
        <p class="scope-note">{{ tr('taskHint') }}</p><a-alert v-if="pollPaused" type="info" :message="tr('refreshPaused')" /><section class="workspace-panel"><a-table :columns="taskColumns" :data-source="tasks" row-key="id" :pagination="false" :scroll="{ x: 850 }"><template #bodyCell="{ column, record }"><template v-if="column.key === 'task'"><strong>{{ taskName(record) }}</strong><small class="path-text">#{{ record.id }} · {{ tr(record.payload?.local_agent_id ? 'instanceScope' : 'productScope') }}</small></template><template v-else-if="column.key === 'time'">{{ stamp(record.created_at) }}</template><template v-else-if="column.key === 'status'"><a-tag :color="record.status === 'succeeded' ? 'green' : record.status === 'failed' ? 'red' : 'default'">{{ translated('agentRuntimeGovernance', record.status) }}</a-tag></template><template v-else-if="column.key === 'completed'">{{ stamp(record.finished_at) }}</template><template v-else-if="column.key === 'actions'"><a-space wrap><a-button type="link" @click="selectedTask = record">{{ tr('view') }}</a-button><a-button v-if="can('clients:execute') && record.status === 'pending'" :disabled="!!taskBusy" :loading="taskBusy === String(record.id)" @click="taskOperation(record, 'cancel')">{{ tr('cancel') }}</a-button><a-button v-if="can('clients:execute') && ['failed', 'cancelled'].includes(record.status)" :disabled="!!taskBusy" :loading="taskBusy === String(record.id)" @click="taskOperation(record, 'retry')">{{ tr('retry') }}</a-button></a-space></template></template></a-table><footer class="task-pagination"><a-button :disabled="loading || tasksLoading" @click="refresh">{{ tr('latest') }}</a-button><a-button :disabled="!nextBefore || tasksLoading || loading" :loading="tasksLoading" @click="loadMoreTasks">{{ tr('more') }}</a-button></footer></section>
      </template>
      </div>
    </template>
    <a-modal v-model:open="evidence" :title="tr('evidence')" :footer="null"><p>{{ tr('evidenceHint') }}</p><dl class="workspace-meta inline"><dt>{{ tr('localId') }}</dt><dd>{{ instance?.local_agent_id }}</dd><dt>{{ tr('path') }}</dt><dd>{{ agent?.install_path || instance?.install_path }}</dd><dt>{{ tr('scanAt') }}</dt><dd>{{ stamp(instance?.last_scanned_at) }}</dd></dl><details><summary>{{ tr('raw') }}</summary><pre>{{ JSON.stringify(instance, null, 2) }}</pre></details></a-modal>
    <a-modal :open="Boolean(selectedSkill)" :title="tr('signature')" :footer="null" @cancel="selectedSkill = null"><h3>{{ selectedSkill?.name }}</h3><p class="path-text">{{ selectedSkill?.path }}</p><dl class="workspace-meta inline"><dt>{{ tr('certification') }}</dt><dd>{{ tr(isCertified(selectedSkill) ? 'certified' : 'uncertified') }}</dd><dt>{{ tr('contentDigest') }}</dt><dd class="path-text">{{ selectedSkill?.signature || tr('unknown') }}</dd></dl><details><summary>{{ tr('raw') }}</summary><pre>{{ JSON.stringify(selectedSkill, null, 2) }}</pre></details></a-modal>
    <a-modal :open="Boolean(selectedTask)" :title="tr('taskDetails')" :footer="null" @cancel="selectedTask = null"><h3>{{ selectedTask && taskName(selectedTask) }}</h3><dl class="workspace-meta inline"><dt>{{ tr('taskScope') }}</dt><dd>{{ selectedTask?.payload?.local_agent_id || selectedTask?.payload?.agent }}</dd><dt>{{ tr('status') }}</dt><dd>{{ translated('agentRuntimeGovernance', selectedTask?.status) }}</dd><dt>{{ tr('time') }}</dt><dd>{{ stamp(selectedTask?.created_at) }}</dd><dt>{{ tr('completed') }}</dt><dd>{{ stamp(selectedTask?.finished_at) }}</dd></dl><a-alert v-if="selectedTask?.error" type="error" :message="tr('taskError')" :description="selectedTask.error" /><details><summary>{{ tr('raw') }}</summary><pre>{{ JSON.stringify(selectedTask, null, 2) }}</pre></details></a-modal>
    <a-drawer v-model:open="diagnostic" :title="tr('diagnostic')" :body-style="{ display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }" width="min(1120px, 100vw)" :destroy-on-close="true"><template v-if="instance && can('clients:view')"><a-alert type="info" show-icon :message="tr('scopeProduct')" :description="tr('localRetry')" /><div class="diagnostic-content"><ClientCollectionStatus :key="instanceKey" :client-id="instance.client_id" :fixed-agent="productId" :initial-channel="diagnosticChannel" @policy="openClient('control')" @plugins="diagnostic = false; pluginsOpen = true" @activity="showActivity" /></div></template></a-drawer>
    <a-drawer v-model:open="pluginsOpen" :title="tr('plugins')" width="min(1000px, 100vw)" :destroy-on-close="true"><template v-if="instance && can('clients:view')"><p>{{ tr('scopeProduct') }}</p><ClientRuntimeGovernance v-if="catalogProduct?.hooks" :key="instanceKey" :client-id="instance.client_id" :fixed-agent="productId" @policy="openClient('control')" @collection="pluginsOpen = false; diagnostic = true" @events="pluginsOpen = false; showActivity('hooks')" /><a-empty v-else :description="tr('unsupported')" /></template></a-drawer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined, ReloadOutlined, RightOutlined } from '@ant-design/icons-vue'
import { can } from '../access'
import { formatDateTime } from '../utils/format'
import products from '../aidr-products.json'
import { getAgentWorkspace, getClientRuntimeGovernance, getClientAidrStatus, getClientAidrSessions, getHookPolicy, cancelClientTask, retryClientTask } from '../api'
import AgentProductLogo from './AgentProductLogo.vue'
import AgentModelConfiguration from './AgentModelConfiguration.vue'
import ClientSkillActions from './ClientSkillActions.vue'
import ClientAuditSessions from './ClientAuditSessions.vue'
import ClientEnforcementPanel from './ClientEnforcementPanel.vue'
import ClientHookPanel from './ClientHookPanel.vue'
import ClientHookConnection from './ClientHookConnection.vue'
import ClientRuntimeGovernance from './ClientRuntimeGovernance.vue'
import ClientCollectionStatus from './ClientCollectionStatus.vue'
const props = defineProps({ asset: { type: Object, required: true }, initialClient: String, initialLocalId: String })
const emit = defineEmits(['back'])
const { t, te } = useI18n(), router = useRouter(), tr = (key, values) => t(`agentWorkspace.${key}`, values || {})
const keyOf = item => JSON.stringify([item.client_id, item.local_agent_id])
const instanceKey = ref(''), tab = ref('overview'), client = ref(null), runtime = ref(null), logs = ref(null), sessions = ref(null), policy = ref(null), errors = ref([]), missing = ref(false), loaded = ref(false), loading = ref(false)
const diagnostic = ref(false), pluginsOpen = ref(false), evidence = ref(false), selectedSkill = ref(null), selectedTask = ref(null), auditTab = ref('sessions'), auditSource = ref('tools'), activityRequest = ref(null)
const tasks = ref([]), nextBefore = ref(null), tasksLoading = ref(false), taskBusy = ref(''), pollPaused = ref(false), now = ref(Date.now())
let generation = 0, pollTimer, pollUntil = 0, taskRequest = 0
const instance = computed(() => props.asset.instances?.find(item => keyOf(item) === instanceKey.value))
const instanceOptions = computed(() => (props.asset.instances || []).map(item => ({ value: keyOf(item), label: `${item.local_agent_id} · ${item.install_path || tr('unknown')}` })))
const productId = computed(() => instance.value?.agent_type || props.asset.channel || '')
const catalogProduct = computed(() => products.find(item => item.id === productId.value))
const displayName = computed(() => catalogProduct.value?.name || props.asset.name)
const agent = computed(() => client.value?.agents?.find(item => item.local_agent_id === instance.value?.local_agent_id))
const tabs = computed(() => can('clients:view') ? ['overview', 'capabilities', 'audit', 'policy', 'history'] : ['overview'])
const stamp = value => value ? formatDateTime(value) : tr('unknown')
const parsed = value => value ? Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z') : NaN
const fresh = (value, seconds = 30) => Number.isFinite(parsed(value)) && now.value - parsed(value) >= -5000 && now.value - parsed(value) <= seconds * 1000
const connection = computed(() => runtime.value?.hook_connections?.find(item => item.agent === productId.value))
const warningStates = new Set(['stale', 'failed', 'stopped', 'source_partial', 'source_unavailable', 'permission_denied', 'source_missing', 'partial', 'transport_offline', 'product_upgrade_required', 'read_failed', 'disable_not_applied', 'host_missing', 'not_installed', 'review_required', 'admin_required', 'cancelled', 'interrupted', 'disabled'])
const translated = (namespace, value) => value && te(`${namespace}.${value}`) ? t(`${namespace}.${value}`) : value || tr('unknown')
const stateLabel = state => te(`collectionStatus.states.${state}`) ? t(`collectionStatus.states.${state}`) : tr('unknown')
const channels = computed(() => ['hooks', 'logs', 'system', 'receiver'].map(id => {
  const data = id === 'logs' ? logs.value?.log_channel || runtime.value?.channels?.logs : runtime.value?.channels?.[id]
  let state = !runtime.value || errors.value.includes('runtime') || (id === 'logs' && errors.value.includes('logs')) ? 'unreported' : data?.health?.state || 'unreported'
  let arrival = null
  if (id === 'receiver') state = fresh(runtime.value?.reported_at) && !runtime.value?.stale ? (runtime.value.report?.receiver_code === 'aidr_desktop_running' ? 'running' : runtime.value.report?.receiver_code === 'aidr_desktop_stopped' ? 'stopped' : 'unknown') : 'stale'
  else {
    if (state === 'running' && (!fresh(data.report?.reported_at) || runtime.value?.stale)) state = 'stale'
    if (['logs', 'hooks'].includes(id)) {
      const selected = id === 'logs' ? runtime.value?.target?.log_sources : runtime.value?.target?.hosts
      if (data?.target_enabled === false || (Array.isArray(selected) && !selected.includes(productId.value))) state = 'not_requested'
      if (id === 'hooks') arrival = connection.value?.event_received_at
      else arrival = (logs.value?.product_receipts || []).filter(item => item.agent === productId.value).map(item => item.last_received_at).sort().at(-1)
      if (state === 'running') {
        if (id === 'logs') {
          const discovery = (logs.value?.health?.discovery || []).filter(item => item.agent === productId.value)
          if (!fresh(logs.value?.last_seen_at, 90)) state = 'transport_offline'
          else if (discovery.some(item => item.reason_codes?.includes('aidr_log_permission_denied'))) state = 'permission_denied'
          else if (discovery.some(item => item.status === 'unavailable')) state = 'source_unavailable'
          else if (discovery.some(item => item.status === 'partial')) state = 'source_partial'
          else state = fresh(arrival, 900) ? 'received' : discovery.length ? 'waiting' : 'unreported'
        } else if (connection.value?.stale || !fresh(connection.value?.observed_at, 480)) state = fresh(arrival, 900) ? 'received' : 'unreported'
        else if (['host_missing', 'not_installed'].includes(connection.value?.installation)) state = connection.value.installation
        else if (['review_required', 'admin_required', 'cancelled', 'failed', 'interrupted'].includes(connection.value?.authorization)) state = connection.value.authorization
        else if (connection.value?.enabled === false) state = 'disabled'
        else state = fresh(arrival, 900) ? 'received' : 'waiting'
      }
    }
  }
  return { id, state, arrival, warning: warningStates.has(state) }
}))
const attention = computed(() => channels.value.some(item => item.warning))
const attentionSummary = computed(() => channels.value.filter(item => item.warning).map(item => `${tr(item.id)}：${stateLabel(item.state)}`).join(' · '))
const diagnosticChannel = computed(() => { const id = channels.value.find(item => item.warning)?.id; return id === 'receiver' ? 'hooks' : id || 'logs' })
const modelState = computed(() => agent.value?.capabilities?.model_config_state || instance.value?.capabilities?.model_config_state || {})
const configuredModel = computed(() => modelState.value.model || tr('modelNoReport'))
const modelSource = computed(() => modelState.value.gateway_name || modelState.value.gateway_source || tr('unknown'))
const policySource = computed(() => !policy.value ? tr('unknown') : tr(policy.value.inherit ? 'globalPolicy' : 'clientPolicy'))
const policyMode = computed(() => runtime.value?.target_configured ? runtime.value.target?.modes?.hooks === 'audit' ? t('aidr.hooks.runtime.audit') : runtime.value.target?.modes?.hooks === 'intercept' ? tr('intercept') : tr('unknown') : tr('unknown'))
const currentHookReport = computed(() => { const report = policy.value?.runtime?.items?.[0]; return report?.code === 'aidr_hook_runtime_recent' && now.value - Number(report.received_at) * 1000 <= 90000 ? report : null })
const observedMode = computed(() => currentHookReport.value ? translated('aidr.hooks.runtime', currentHookReport.value.control_mode) : tr('unknown'))
const rules = computed(() => (policy.value?.policy?.rules || []).filter(rule => rule.agent === '*' || rule.agent === productId.value))
const isCertified = skill => Boolean(skill?.signature && skill.governance?.signature === skill.signature && skill.governance?.certification === 'certified')
const skillColumns = computed(() => ['name', 'certification', 'actions'].map(key => ({ key, title: tr(key) })))
const recoveryColumns = computed(() => [{ key: 'path', dataIndex: 'original_path', title: tr('originalPath') }, { key: 'actions', title: tr('actions') }])
const taskColumns = computed(() => ['time', 'task', 'status', 'completed', 'actions'].map(key => ({ key, title: tr(key) })))
const ruleColumns = computed(() => ['rule', 'decision'].map(key => ({ key, title: tr(key) })))
const modelPending = computed(() => tasks.value.some(item => ['apply_model_config', 'verify_model_config', 'restore_model_config'].includes(item.task_type) && ['pending', 'running'].includes(item.status)))
function taskName(task) {
  if (task.task_type === 'aidr_plugin_action') return translated('agentRuntimeGovernance', task.payload?.action)
  if (task.task_type === 'skill_action') return translated('clientGovernance', task.payload?.action)
  const key = { apply_model_config: 'modelChange', verify_model_config: 'modelVerify', restore_model_config: 'modelRestore' }[task.task_type]
  return key ? tr(key) : task.task_type
}
function openClient(section) { if (can('clients:view')) router.push({ path: '/clients', query: { client: instance.value.client_id, section } }) }
function selectTab(value) { if (value === 'audit') activityRequest.value = null; tab.value = value }
function showActivity(source, session = null) { activityRequest.value = session; diagnostic.value = false; auditTab.value = source === 'system' ? 'system' : 'sessions'; auditSource.value = source === 'hooks' ? 'hooks' : 'tools'; tab.value = 'audit' }
function openSession(item) { showActivity('tools', { clientId: instance.value.client_id, agent: productId.value, sessionId: item.session_id }) }
function schedule() {
  clearTimeout(pollTimer)
  if (!tasks.value.some(item => ['pending', 'running'].includes(item.status))) { pollUntil = 0; pollPaused.value = false; return }
  if (!pollUntil) pollUntil = Date.now() + 120000
  if (Date.now() >= pollUntil) { pollPaused.value = true; return }
  pollTimer = setTimeout(() => document.hidden ? schedule() : refresh(true), 5000)
}
async function refresh(automatic = false) {
  if (loading.value || !instance.value || !can('clients:view')) { if (!can('clients:view')) loaded.value = true; return }
  if (automatic !== true) { pollUntil = 0; pollPaused.value = false }
  const epoch = generation, id = instance.value.client_id, local = instance.value.local_agent_id, product = productId.value
  loading.value = true; errors.value = automatic === true ? errors.value.filter(key => !['client', 'runtime'].includes(key)) : []; missing.value = false; taskRequest++; tasksLoading.value = false
  const requests = [
    ['client', () => getAgentWorkspace(id, { local_agent_id: local }), result => { client.value = result; tasks.value = result.tasks || []; nextBefore.value = result.tasks_next_before }],
    ['runtime', () => getClientRuntimeGovernance(id), result => { runtime.value = result }],
    ['logs', () => getClientAidrStatus(id, { include_retention: false }), result => { logs.value = result }],
    ['sessions', () => getClientAidrSessions(id, { agent: product, limit: 5, include_questions: can('clients:read-audit-content') }), result => { sessions.value = result }],
    ['policy', () => getHookPolicy(id), result => { policy.value = result }],
  ]
  await Promise.allSettled((automatic === true ? requests.filter(([key]) => ['client', 'runtime'].includes(key)) : requests).map(async ([key, request, accept]) => {
    try { const result = await request(); if (epoch === generation) accept(result) }
    catch (cause) { if (epoch === generation) { errors.value.push(key); if (key === 'client') { client.value = null; tasks.value = []; nextBefore.value = null; missing.value = cause.response?.status === 404 } if (key === 'runtime') runtime.value = null; if (key === 'policy') policy.value = null; if (key === 'logs') logs.value = null; if (key === 'sessions') sessions.value = null } }
  }))
  if (epoch === generation) { loading.value = false; loaded.value = true; schedule() }
}
async function loadMoreTasks() {
  if (tasksLoading.value || !nextBefore.value || loading.value) return
  const epoch = generation, request = ++taskRequest; tasksLoading.value = true
  try { const result = await getAgentWorkspace(instance.value.client_id, { local_agent_id: instance.value.local_agent_id, before: nextBefore.value }); if (epoch === generation && request === taskRequest) { const ids = new Set(tasks.value.map(task => task.id)); tasks.value.push(...result.tasks.filter(task => !ids.has(task.id))); nextBefore.value = result.tasks_next_before } }
  catch { if (epoch === generation) message.error(tr('readFailed')) }
  finally { if (epoch === generation && request === taskRequest) tasksLoading.value = false }
}
function taskCreated(result) { if (result.clientId !== instance.value?.client_id) return; tab.value = 'history'; refresh() }
async function taskOperation(task, action) {
  if (taskBusy.value || !can('clients:execute')) return
  const epoch = generation, id = instance.value.client_id; taskBusy.value = String(task.id)
  try { await (action === 'cancel' ? cancelClientTask : retryClientTask)(id, task.id); if (epoch === generation) await refresh() }
  catch (cause) { if (epoch === generation) message.error(typeof cause.response?.data?.detail === 'string' ? cause.response.data.detail : tr('failed')) }
  finally { if (epoch === generation) taskBusy.value = '' }
}
watch(() => props.asset.asset_key, () => { instanceKey.value = keyOf(props.asset.instances?.find(item => item.client_id === props.initialClient && item.local_agent_id === props.initialLocalId) || props.asset.instances?.[0] || {}); tab.value = 'overview' }, { immediate: true })
watch(instanceKey, () => {
  generation++; clearTimeout(pollTimer); pollUntil = 0; taskRequest++; loaded.value = false; loading.value = false; tasksLoading.value = false; taskBusy.value = ''; pollPaused.value = false
  client.value = null; runtime.value = null; logs.value = null; sessions.value = null; policy.value = null; tasks.value = []; nextBefore.value = null; errors.value = []; missing.value = false
  diagnostic.value = false; pluginsOpen.value = false; evidence.value = false; selectedSkill.value = null; selectedTask.value = null; activityRequest.value = null; refresh()
}, { immediate: true })
const clock = setInterval(() => { now.value = Date.now() }, 15000)
onBeforeUnmount(() => { generation++; taskRequest++; clearInterval(clock); clearTimeout(pollTimer) })
</script>

<style scoped>
.agent-workspace { --workspace-line:#e5eaf1; --workspace-muted:#7b8799; color:#263750; max-width:1440px; margin:auto; padding:6px 4px 0; height:100%; display:flex; flex-direction:column; min-height:0; overflow:hidden; }.workspace-breadcrumb { display:flex; gap:12px; align-items:center; font-size:12px; color:#8995a6; margin-bottom:20px; }.workspace-breadcrumb .ant-btn { padding:0; font-size:12px; }.workspace-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:20px; }.identity { display:flex; align-items:center; gap:16px; }.product-logo { width:56px; height:56px; padding:10px; background:white; border:1px solid var(--workspace-line); border-radius:12px; flex-shrink:0; }.workspace-heading>.ant-btn { flex-shrink:0; }.workspace-heading h1 { font-size:26px; margin:0 0 6px; font-weight:650; letter-spacing:-.5px; }.workspace-heading h1 .ant-tag { vertical-align:middle; margin-left:10px; font-size:11px; font-weight:400; }.workspace-heading p { color:var(--workspace-muted); margin:0; font-size:12px; }.workspace-scope { display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:13px 17px; border:1px solid var(--workspace-line); border-radius:9px; background:white; font-size:12px; }.workspace-scope>span,.workspace-scope>label { color:var(--workspace-muted); }.workspace-scope .ant-select { width:330px; max-width:100%; }.workspace-scope .client-link { margin-left:auto; }.workspace-tabs { display:flex; gap:28px; border-bottom:1px solid #dce3ec; margin:12px 0 22px; overflow:auto; }.workspace-tabs button { padding:14px 0; font:inherit; white-space:nowrap; border:0; border-bottom:2px solid transparent; color:#788499; background:none; cursor:pointer; }.workspace-tabs .selected { color:#275fe4; font-weight:600; border-bottom-color:#275fe4; }.workspace-tabs button:focus-visible,.session-preview:focus-visible { outline:2px solid #275fe4; outline-offset:-2px; }.workspace-notice { display:flex; justify-content:space-between; align-items:center; gap:20px; padding:15px 18px; margin-bottom:20px; border:1px solid #f4e5c9; border-radius:8px; background:#fff9ee; color:#8d682f; }.workspace-notice p { font-size:12px; margin:5px 0 0; }.workspace-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); padding:20px 0; background:white; border:1px solid var(--workspace-line); border-radius:10px; margin-bottom:22px; }.workspace-stats>div { padding:0 22px; border-right:1px solid var(--workspace-line); min-width:0; }.workspace-stats>div:last-child { border:0; }.workspace-stats span,.workspace-stats small { display:block; font-size:12px; color:var(--workspace-muted); }.workspace-stats strong { display:block; font-size:20px; margin:10px 0 6px; overflow-wrap:anywhere; }.workspace-stats small { font-size:11px; line-height:1.6; }.workspace-columns { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:20px; }.workspace-panel { min-width:0; background:white; border:1px solid var(--workspace-line); border-radius:10px; margin-bottom:20px; overflow:hidden; }.workspace-panel>header { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:18px 22px 14px; }.workspace-panel h2 { font-size:16px; font-weight:600; margin:0; }.workspace-panel header small { color:var(--workspace-muted); display:block; margin-top:5px; font-size:12px; }.panel-body { padding:0 22px 20px; }.health-row { display:flex; align-items:center; justify-content:space-between; gap:15px; padding:15px 0; border-bottom:1px solid #eff2f6; }.health-row:last-child { border:0; }.health-row strong { font-weight:500; }.health-row p { margin:5px 0 0; font-size:12px; color:var(--workspace-muted); }.workspace-meta { display:grid; grid-template-columns:110px minmax(0,1fr); gap:14px; padding:0 22px 20px; font-size:12px; margin:0; }.workspace-meta.inline { padding:0; margin:12px 0 18px; }.workspace-meta dt { color:var(--workspace-muted); }.workspace-meta dd { margin:0; overflow-wrap:anywhere; }.session-preview { display:flex; align-items:center; gap:14px; width:100%; border:0; background:none; text-align:left; cursor:pointer; font:inherit; color:inherit; padding:15px 0; }.session-preview>span:nth-child(2) { flex:1; min-width:0; }.session-preview strong { font-size:13px; font-weight:500; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.session-preview small { display:block; color:var(--workspace-muted); font-size:11px; margin-top:7px; }.activity-dot { width:7px; height:7px; background:#8aa9e8; border-radius:50%; flex-shrink:0; box-shadow:0 0 0 4px #f2f6ff; }.session-preview .anticon { font-size:10px; color:#91a0b5; }.muted,.scope-note { color:var(--workspace-muted); font-size:12px; line-height:1.7; }.scope-note { margin:0 0 16px; }.workspace-segments { margin-bottom:15px; }.workspace-audit { display:flex; flex-direction:column; flex:1; min-height:0; overflow:hidden; }.workspace-system { display:flex; flex:1; min-height:0; overflow:hidden; }.workspace-system :deep(.enforcement-panel) { margin:0; }.skill-action-row { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }.path-text { display:block; font-size:12px; overflow-wrap:anywhere; color:var(--workspace-muted); margin-top:5px; }.task-pagination { display:flex; justify-content:flex-end; gap:10px; padding:15px 20px; }.diagnostic-content { display:flex; flex:1; min-height:0; margin-top:18px; overflow:hidden; }.approvals-panel :deep(.hook-table .ant-table-body) { max-height:none!important; }.workspace-panel :deep(.ant-table-cell) { vertical-align:top; }pre { background:#f7f9fc; padding:13px; border-radius:6px; font-size:12px; white-space:pre-wrap; overflow-wrap:anywhere; }summary { cursor:pointer; color:#56749c; }details { margin-top:16px; }.agent-workspace>.ant-alert { margin-top:14px; }.workspace-panel :deep(.ant-btn),.workspace-heading>.ant-btn { height:auto; min-height:32px; white-space:normal; }
@media(max-width:1100px){.workspace-scope .ant-select{width:260px}.workspace-stats>div{padding:0 16px}.workspace-stats strong{font-size:18px}.workspace-tabs{gap:22px}}
@media(max-width:760px){.workspace-columns{grid-template-columns:1fr;gap:0}.workspace-stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:22px 0}.workspace-stats>div:nth-child(2){border:0}.workspace-heading{align-items:flex-start}.workspace-heading h1{font-size:23px}.workspace-scope .ant-select{flex:1;min-width:200px}.workspace-breadcrumb{flex-wrap:wrap}.workspace-tabs{gap:20px}.workspace-meta{grid-template-columns:95px minmax(0,1fr)}}
@media(max-width:480px){.workspace-heading{flex-wrap:wrap}.workspace-tabs button{font-size:13px}.workspace-panel>header,.panel-body{padding-left:15px;padding-right:15px}.workspace-scope .ant-select{width:100%;flex:auto}.workspace-notice{align-items:flex-start}.workspace-heading h1 .ant-tag{margin-left:0}.workspace-heading p{line-height:1.7}.workspace-meta{padding-left:15px;padding-right:15px}.workspace-tabs{gap:18px}}
.agent-workspace > :not(.workspace-body) { flex-shrink:0; }
.workspace-body { flex:1; min-height:0; overflow-y:auto; scrollbar-gutter:stable; padding-bottom:16px; }
.workspace-body.audit-body { display:flex; flex-direction:column; overflow:hidden; padding-bottom:0; }
.audit-body > :not(.workspace-audit):not(.workspace-system) { flex-shrink:0; }
.audit-workspace .workspace-breadcrumb { margin-bottom:10px; }
.audit-workspace .workspace-heading { margin-bottom:12px; }
.audit-workspace .product-logo { width:44px; height:44px; padding:8px; }
.audit-workspace .workspace-heading h1 { font-size:22px; }
.audit-workspace .workspace-scope { padding:8px 12px; }
.audit-workspace .workspace-tabs { margin:6px 0 12px; }
.audit-workspace .workspace-tabs button { padding:10px 0; }
.audit-workspace .workspace-segments { margin-bottom:8px; }
.audit-workspace .scope-note { margin-bottom:10px; }
.workspace-audit :deep(.audit-content pre), .workspace-audit :deep(.skill-uses pre), .workspace-audit :deep(.original-question pre) { max-height:none; overflow:visible; white-space:pre-wrap; overflow-wrap:anywhere; }
@media (max-width:900px) {
  .workspace-body.audit-body { display:block; overflow-y:auto; overscroll-behavior-y:contain; }
  .workspace-audit, .workspace-system { display:block; overflow:visible; }
  .workspace-audit :deep(.session-audit) { display:flex; flex-direction:column; overflow:visible; }
  .workspace-audit :deep(.session-timeline),
  .workspace-audit :deep(.turn-reading),
  .workspace-audit :deep(.timeline-records),
  .workspace-audit :deep(.skill-uses),
  .workspace-system :deep(.system-event-view),
  .workspace-system :deep(.system-event-list) { flex:none; overflow:visible; }
}
</style>
