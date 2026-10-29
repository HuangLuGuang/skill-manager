<template>
  <section class="device-overview" :aria-busy="loading">
    <a-alert v-if="rangeError" type="error" :message="ot('rangeError')" />
    <a-alert v-for="entry in errors" :key="entry" type="warning" show-icon :message="entry === 'tasks' ? tr('taskReadFailed') : t('agentRuntimeGovernance.detail.summaryFailed', { section: t('agentRuntimeGovernance.detail.' + entry) })" />
    <a-tabs v-model:active-key="activeTab" class="overview-tabs">
    <template #rightExtra>
      <div class="period-controls"><a-select v-model:value="range" :aria-label="tr('range')" :options="[{value:7,label:tr('week')},{value:30,label:tr('month')},{value:'custom',label:ot('custom')}]" @change="setPeriod" />
        <a-range-picker v-if="range === 'custom'" popup-class-name="overview-date-popup" @keydown.esc.stop v-model:value="dates" :allow-clear="false" :disabled-date="date => date.isAfter(dayjs(), 'day')" @change="setPeriod" />
        <span v-else class="muted">{{ periodLabel }}</span><a-button :loading="loading" @click="refresh">{{ tr('refresh') }}</a-button>
      </div>
    </template>
    <a-tab-pane key="assets" :tab="ot('assets')" force-render>
    <section>
      <div class="asset-charts">
        <section class="asset-panel">
          <p class="muted">{{ ot('snapshot') }}</p>
          <div class="asset-metrics">
            <button @click="emit('navigate','skills')"><span>{{ ot('agents') }}</span><strong>{{ agentsCount }}</strong></button>
            <a-tooltip :title="ot('skillScope')" :trigger="['hover', 'focus']"><button :aria-label="`${ot('skills')} · ${ot('skillScope')}`" @click="openAssets()"><span>{{ ot('skills') }}</span><strong>{{ skillsCount }}</strong></button></a-tooltip>
            <button @click="emit('navigate','plugins')"><span>{{ ot('plugins') }}</span><strong>{{ installedCount ?? '—' }}</strong><small v-if="installedCount == null">{{ tr('unknown') }}</small></button>
          </div>
          <h4>{{ ot('skillDistribution') }}</h4><Chart v-if="skillGroups.length" :options="skillOptions" :height="`${Math.max(240,skillGroups.length*34+50)}px`" :navigation-label="ot('chartKeyboard',{name:ot('skillDistribution')})" @select="value => openAssets(skillGroups[value.dataIndex]?.key)" /><a-empty v-else :description="tr('empty')" />
        </section>
        <section class="asset-panel">
          <p class="muted">{{ ot('taskScope') }}</p>
          <div class="asset-metrics task-metric"><button @click="openHistory()"><span>{{ ot('tasks') }}</span><strong>{{ taskData ? taskTotal : '—' }}</strong></button></div>
          <h4>{{ ot('taskDistribution') }}</h4><Chart v-if="taskTotal" :options="taskOptions" height="230px" :navigation-label="ot('chartKeyboard',{name:ot('taskDistribution')})" @select="value => openHistory(taskStates[value.dataIndex])" /><a-empty v-else :description="tr(taskData ? 'empty' : 'unknown')" /><div v-if="taskTotal" class="task-legend"><button v-for="(status,index) in taskStates" :key="status" @click="openHistory(status)"><i :style="{background:taskColors[index]}" />{{ t('agentRuntimeGovernance.'+status) }}<b>{{ taskData.counts[status] || 0 }}</b></button></div>
        </section>
      </div>
      <div class="asset-footer"><a-button type="link" @click="emit('navigate','skills')">{{ ot('viewAssets') }}</a-button><a-button v-if="taskData" type="link" @click="openHistory('failed')">{{ ot('failedTasks',{count:taskData?.counts?.failed || 0}) }}</a-button></div>
    </section>
    </a-tab-pane>
    <a-tab-pane key="activity" :tab="ot('activity')" force-render>
    <section>
    <ClientOverviewStatistics ref="statistics" :client-id="client.client_id" :period="period" @activity="emit('activity', $event)" />
    <div class="health">
      <button @click="emit('navigate', 'collection')"><ApiOutlined /><div><b>Hook</b><span>{{ receiverState }}</span><small>{{ reportTime(runtime?.reported_at) }}</small></div><RightOutlined /></button>
      <button @click="emit('navigate', 'collection')"><FileTextOutlined /><div><b>{{ tr('logs') }}</b><span>{{ logState }}</span><small>{{ reportTime(logs?.last_seen_at) }}</small></div><RightOutlined /></button>
      <button @click="emit('navigate', 'systemEvents')"><DesktopOutlined /><div><b>{{ t('clientDetail.system') }}</b><span>{{ system?.state === 'collecting' ? t('clientDetail.collectionOnly') : system ? t('aidr.enforcement.states.' + (system.state || 'unknown')) : tr('unknown') }}</span><small>{{ reportTime(system?.last_received_at) }}</small></div><RightOutlined /></button>
    </div>
    <div class="section-heading"><h3>{{ tr('attention') }} <a-badge v-if="sourceIssues.length" :count="sourceIssues.length" /></h3><a-button type="link" @click="sourcesVisible = true">{{ tr('historicalSources') }}</a-button></div>
    <p v-if="!sourceIssues.length && settled" class="quiet"><InfoCircleOutlined /> {{ tr(uncertain ? 'incomplete' : 'healthy') }}</p>
    <div v-for="entry in sourceIssues" :key="entry.agent" class="issue"><ExclamationCircleOutlined /><div><strong>{{ entry.name }}</strong><p>{{ entry.labels.join(' · ') }}</p></div><a-button @click="emit('navigate', 'collection')">{{ tr('inspect') }}</a-button></div>
    </section>
    </a-tab-pane>
    <a-tab-pane key="risks" :tab="ot('risks')" force-render><ClientRiskOverview ref="risks" :client-id="client.client_id" :period="period" /></a-tab-pane>
    </a-tabs>
    <a-modal v-model:open="assetsVisible" :title="ot('skills')" :footer="null" width="900px"><p class="muted">{{ ot('skillScope') }}</p><a-table :key="assetProduct" :columns="assetColumns" :data-source="assetRows" row-key="key" :pagination="{defaultPageSize:10,showSizeChanger:true}" :scroll="{x:600}"><template #bodyCell="{column,record}"><span v-if="column.key === 'product'">{{ productName(record.product) }}</span></template></a-table></a-modal>
    <a-modal v-model:open="sourcesVisible" :title="tr('historicalSources')" :footer="null" width="680px">
      <p class="muted">{{ reportTime(logs?.last_seen_at) }}</p><p v-if="!discovery.length">{{ tr('unknown') }}</p>
      <div v-for="(entry, index) in discovery" :key="index" class="source-detail"><h4>{{ productName(entry.agent) }}</h4><p v-if="entry.historical_missing">{{ tr('historicalMissing', { count: entry.historical_missing }) }}</p><p v-if="entry.historical_missing" class="muted">{{ tr('historicalBoundary') }}</p><p v-for="label in sourceLabels(entry)" :key="label">{{ label }}</p><p v-if="!entry.historical_missing && !sourceLabels(entry).length">{{ tr('noSourceIssues') }}</p></div>
      <a-button @click="sourcesVisible = false; emit('navigate', 'collection')">{{ t('clientDetail.checkCollection') }}</a-button>
    </a-modal>
    <a-modal v-model:open="historyVisible" :title="tr('history')" :footer="null" width="850px"><p class="muted">{{ ot('taskScope') }} · {{ periodLabel }}<span v-if="historyStatus"> · {{ t('agentRuntimeGovernance.'+historyStatus) }}</span></p><a-alert v-if="historyError" type="error" :message="tr('taskReadFailed')"><template #action><a-button @click="loadHistory(false)">{{ tr('retry') }}</a-button></template></a-alert>
      <details v-for="task in history" :key="task.id" class="task"><summary><strong>{{ taskTitle(task) }}</strong><a-tag :color="taskColor(task)">{{ taskStatus(task) }}</a-tag><span>{{ taskTarget(task) }} · {{ taskTime(task.created_at) }}</span></summary><p>#{{ task.id }}<span v-if="task.payload?.policy_version"> · {{ t('agentRuntimeGovernance.taskSummary.policy', { version: task.payload.policy_version }) }}</span></p><p v-if="task.error_code">{{ errorLabel(task.error_code) }} <code>{{ task.error_code }}</code></p><p v-if="task.payload?.target">{{ targetChannels(task.payload.target) }}</p><p v-if="task.finished_at">{{ t('agentRuntimeGovernance.taskSummary.finished', { time: taskTime(task.finished_at) }) }}</p></details>
      <a-empty v-if="!history.length && !historyLoading && !historyError" :description="tr('empty')" /><a-spin v-if="historyLoading" /><a-button v-if="historyCursor" :loading="historyLoading" @click="loadHistory(true)">{{ tr('more') }}</a-button>
    </a-modal>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiOutlined, InfoCircleOutlined, RightOutlined, FileTextOutlined, DesktopOutlined, ExclamationCircleOutlined } from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import Chart from './Chart.vue'
import { translateDomain } from '../i18n'
import products from '../aidr-products.json'
import ClientOverviewStatistics from './ClientOverviewStatistics.vue'
import ClientRiskOverview from './ClientRiskOverview.vue'
import { getClientRuntimeGovernance, getClientAidrStatus, getEnforcement, getClientAidrOverviewTasks } from '../api'
const props = defineProps({ client: { type: Object, required: true } }), emit = defineEmits(['navigate', 'activity'])
const { t, te, locale } = useI18n(), tr = (key, params) => t('clientOverview.' + key, params)
const runtime = ref(null), logs = ref(null), system = ref(null), taskData = ref(null), errors = ref([]), loading = ref(false), settled = ref(false), statistics = ref(null)
let generation = 0
const risks = ref(null)
const ot = (key, params) => t('overviewTabs.' + key, params)
const activeTab = ref('assets'), range = ref(7), dates = ref([]), rangeError = ref(false)
const period = ref({ since: dayjs().startOf('day').subtract(6,'day').unix(), until: dayjs().unix() })
const periodLabel = computed(() => `${dayjs.unix(period.value.since).format('YYYY-MM-DD')} – ${dayjs.unix(period.value.until - 1).format('YYYY-MM-DD')}`)
function setPeriod() {
  if (range.value === 'custom' && dates.value.length !== 2) dates.value = [dayjs.unix(period.value.since), dayjs.unix(period.value.until - 1)]
  const start = range.value === 'custom' ? dates.value[0].startOf('day') : dayjs().startOf('day').subtract(range.value - 1,'day')
  const end = range.value === 'custom' ? dates.value[1].add(1,'day').startOf('day') : dayjs()
  const until = Math.min(end.unix(), dayjs().unix())
  rangeError.value = until <= start.unix() || until - start.unix() > 720 * 3600
  if (!rangeError.value) period.value = { since:start.unix(), until }
}
function refresh() { setPeriod() }
const installedCount = computed(() => Array.isArray(runtime.value?.report?.hosts) && !runtime.value.stale ? runtime.value.report.hosts.filter(host => host.installed === true).length : null)
const taskStates = ['succeeded','running','pending','failed','cancelled'], taskColors = ['#7eac91','#759bcf','#afb8c4','#d96b6b','#bba2cc']
const taskTotal = computed(() => Object.values(taskData.value?.counts || {}).reduce((sum,n) => sum+n,0))
const skillGroups = computed(() => {
  const groups = new Map()
  for (const agent of props.client.agents || []) groups.set(agent.agent_type, (groups.get(agent.agent_type) || 0) + (agent.skills || []).length)
  return [...groups].filter(([,count]) => count).map(([key,count]) => ({key,count})).sort((a,b) => b.count-a.count)
})
const skillOptions = computed(() => ({ tooltip:{trigger:'axis',renderMode:'richText',confine:true}, grid:{left:8,right:32,top:12,bottom:12,containLabel:true}, xAxis:{type:'value',minInterval:1}, yAxis:{type:'category',inverse:true,data:skillGroups.value.map(r=>productName(r.key)),axisLabel:{width:125,overflow:'truncate'}}, series:[{type:'bar',barWidth:22,itemStyle:{color:'#759bcf'},label:{show:true,position:'right'},data:skillGroups.value.map(r=>r.count)}] }))
const taskOptions = computed(() => ({ color:taskColors, tooltip:{trigger:'item',renderMode:'richText',confine:true}, title:{text:String(taskTotal.value),left:'center',top:'42%'}, series:[{type:'pie',radius:['52%','73%'],label:{show:false},data:taskStates.map(key=>({name:t('agentRuntimeGovernance.'+key),value:taskData.value?.counts?.[key] || 0}))}] }))
const assetsVisible = ref(false), assetProduct = ref('')
function openAssets(product = '') { assetProduct.value = product; assetsVisible.value = true }
const assetRows = computed(() => (props.client.agents || []).flatMap((agent,i) => (!assetProduct.value || agent.agent_type === assetProduct.value) ? (agent.skills || []).map((skill,j) => ({key:`${i}-${j}`, product:agent.agent_type,name:skill.name,path:skill.path})) : []))
const assetColumns = computed(() => [{key:'product',title:ot('agent'),dataIndex:'product',sorter:(a,b)=>productName(a.product).localeCompare(productName(b.product))},{key:'name',title:'Skill',dataIndex:'name',sorter:(a,b)=>(a.name || '').localeCompare(b.name || '')},{key:'path',title:ot('path'),dataIndex:'path',sorter:(a,b)=>(a.path || '').localeCompare(b.path || '')}])
const agentsCount = computed(() => (props.client.agents || []).filter(agent => agent.agent_type !== 'global-skills').length)
const skillsCount = computed(() => (props.client.agents || []).reduce((total, agent) => total + (agent.skills || []).length, 0))
const receiverState = computed(() => { const code = runtime.value?.report?.receiver_code; return !runtime.value?.stale && code && te('agentRuntimeGovernance.codes.' + code) ? t('agentRuntimeGovernance.codes.' + code) : tr('unknown') })
const logState = computed(() => t('aidr.channelHealth.' + (logs.value?.log_channel?.health?.state || 'policy_unknown')))
const discovery = computed(() => (logs.value?.health?.discovery || []).map(entry => ({ ...entry, ...(entry.progress || {}) })))
const productName = id => id === 'global-skills' ? ot('shared') : products.find(p => p.id === id)?.name || id || tr('unknown')
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
const historyStatus = ref('')
let historySequence = 0
function openHistory(status = '') { historyStatus.value = status; history.value = []; historyCursor.value = null; historyVisible.value = true; loadHistory(false) }
async function loadHistory(append) { if (append && historyLoading.value) return; const request = ++historySequence, epoch = generation; historyLoading.value = true; historyError.value = false; try { const result = await getClientAidrOverviewTasks(props.client.client_id, { ...period.value, status: historyStatus.value, ...(append ? { before: historyCursor.value } : {}) }); if (epoch !== generation || request !== historySequence) return; history.value = append ? [...history.value, ...result.history] : result.history; historyCursor.value = result.next_cursor } catch { if (epoch === generation && request === historySequence) historyError.value = true } finally { if (epoch === generation && request === historySequence) historyLoading.value = false } }
async function load() {
  if (loading.value) return
  loading.value = true
  const epoch = generation, id = props.client.client_id
  const resources = [['plugins', runtime, () => getClientRuntimeGovernance(id)], ['collection', logs, () => getClientAidrStatus(id, { include_retention: false })], ['systemState', system, () => getEnforcement(id, 'status')], ['tasks', taskData, () => getClientAidrOverviewTasks(id, period.value)]]
  const results = await Promise.allSettled(resources.map(([, , request]) => request()))
  if (epoch !== generation) return
  errors.value = []
  results.forEach((result, index) => { const [name, target] = resources[index]; if (result.status === 'fulfilled') target.value = result.value; else { target.value = null; errors.value.push(name) } })
  loading.value = false; settled.value = true
}
watch([() => props.client.client_id, period], () => { generation++; loading.value = false; settled.value = false; sourcesVisible.value = false; assetsVisible.value = false; historyVisible.value = false; historyLoading.value = false; runtime.value = logs.value = system.value = taskData.value = null; load() }, { immediate: true })
defineExpose({ refresh })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.overview-tabs :deep(.ant-tabs-nav){margin-bottom:12px;flex-wrap:wrap;gap:8px}.overview-tabs > :deep(.ant-tabs-nav) .ant-tabs-tab{padding-top:8px;padding-bottom:8px}.overview-tabs :deep(.ant-tabs-extra-content){max-width:100%}.period-controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.period-controls>.ant-select{min-width:145px}.asset-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:12px 0}.asset-metrics.task-metric{grid-template-columns:1fr}.asset-metrics button{min-width:0;overflow-wrap:anywhere;background:#fff;border:1px solid #e3e9f1;border-radius:8px;text-align:left;padding:12px 16px;cursor:pointer;color:#25354b}.asset-metrics span,.asset-metrics small{display:block;color:#63748b}.asset-metrics strong{display:block;font-size:30px;margin:4px 0}.asset-charts{display:grid;grid-template-columns:1.3fr 1fr;gap:12px}.asset-panel{border:1px solid #e3e9f1;border-radius:8px;padding:16px;min-width:0}.asset-panel h4{font-size:14px;margin:0 0 8px}.asset-footer{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:10px}.task-legend{display:grid;grid-template-columns:1fr 1fr;gap:8px}.task-legend button{display:flex;align-items:center;gap:8px;background:none;border:0;cursor:pointer;color:inherit;padding:5px 0}.task-legend b{margin-left:auto}.task-legend i{width:8px;height:8px;border-radius:2px}.asset-panel :deep(.ant-empty){margin:64px 0}@media(max-width:800px){.asset-charts{grid-template-columns:1fr}.asset-metrics{grid-template-columns:1fr}.overview-tabs :deep(.ant-tabs-extra-content){width:100%}.period-controls{width:100%}.period-controls>.ant-picker{width:100%;min-width:0}.period-controls>.muted{font-size:11px}.asset-metrics button{padding:12px}}

.device-overview{padding:0;min-width:0}.section-heading{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin:22px 0 8px}.section-heading h3{margin:0;font-size:16px}.muted{color:#78889d;font-size:12px}.health{margin-top:18px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid #e3e9f1;border-radius:10px}.health button{display:flex;align-items:center;gap:12px;padding:17px;background:none;border:0;border-right:1px solid #e3e9f1;text-align:left;cursor:pointer;color:#42546b;min-width:0}.health button:last-child{border:0}.health button>div{flex:1;min-width:0}.health span,.health small,.health b{display:block;overflow-wrap:anywhere}.health b{font-size:14px;color:#25354b}.health span{font-size:13px;margin:5px 0}.health small{color:#78889d;font-size:11px}.quiet{display:flex;align-items:center;gap:9px;background:#f8fafb;border-radius:7px;padding:15px;color:#627480}.issue{display:flex;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid #e3e9f1}.issue>div{flex:1}.issue p{margin:4px 0;color:#78889d}.issue>.anticon{color:#a96b20}.task{border-top:1px solid #e3e9f1;padding:14px 0;overflow-wrap:anywhere}.task summary{cursor:pointer;line-height:2}.task summary>*{margin-right:10px}.task summary>span:not(.ant-tag){color:#78889d;font-size:12px}.task p{margin:8px 0}.source-detail{border-top:1px solid #e3e9f1;padding:14px 0}.source-detail h4{margin:0 0 8px}.device-overview :deep(.ant-alert){margin:10px 0}button:hover{background:#f5f8ff}button:focus-visible{outline:2px solid #285ff5;outline-offset:2px}@media(max-width:850px){.health{grid-template-columns:1fr}.health button{border-right:0;border-bottom:1px solid #e3e9f1}}
</style>
<style>
@media (max-width: 600px) {
  .overview-date-popup { left: 8px !important; }
  .overview-date-popup .ant-picker-panels { flex-direction: column; }
  .overview-date-popup .ant-picker-panel-container { max-height: 55vh; overflow-y: auto; margin-left: 0 !important; }
}
</style>
