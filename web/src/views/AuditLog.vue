<template>
  <div :class="['audit-page', { 'with-detail': selected }]">
    <header class="audit-heading"><div><h1>{{ t('auditLog.title') }}</h1><p>{{ ui('subtitle') }}</p></div><a-button :loading="loading || optionsLoading" @click="refresh"><ReloadOutlined />{{ ui('refresh') }}</a-button></header>
    <section class="audit-controls">
      <a-input v-model:value="keyword" allow-clear :maxlength="200" :placeholder="ui('search')" :aria-label="ui('search')" @press-enter="filter"><template #prefix><SearchOutlined /></template></a-input>
      <div class="audit-filters">
        <label>{{ ui('agent') }}<a-select v-model:value="filters.agent" :loading="optionsLoading" show-search option-filter-prop="label" :options="agentOptions" @change="filter" /></label>
        <label>{{ ui('client') }}<a-select v-model:value="filters.client_id" :loading="optionsLoading" show-search option-filter-prop="label" :options="clientOptions" @change="filter" /></label>
        <label>{{ ui('category') }}<a-select class="wrap-select" v-model:value="filters.category" :options="categoryOptions" @change="filter" /></label>
        <label>{{ ui('result') }}<a-select class="wrap-select" v-model:value="filters.result" :options="resultOptions" @change="filter" /></label>
        <label>{{ t('auditLog.timeRange') }}<a-select v-model:value="filters.days" :options="timeOptions" @change="filter" /></label>
        <a-button @click="reset">{{ t('auditLog.reset') }}</a-button>
      </div>
    </section>
    <p class="audit-scope">{{ ui('scope') }}</p>
    <a-alert v-if="optionsError" class="audit-error" type="error" show-icon :message="ui('optionsLoadFailed')"><template #action><a-button :loading="optionsLoading" @click="loadOptions">{{ t('auditLog.retry') }}</a-button></template></a-alert>
    <a-alert v-if="error" class="audit-error" type="error" show-icon :message="t('auditLog.loadFailedHelp')"><template #action><a-button @click="load">{{ t('auditLog.retry') }}</a-button></template></a-alert>
    <div :class="['audit-workspace', { 'has-detail': selected }]">
      <section class="audit-list" :aria-label="t('auditLog.title')">
        <a-table :data-source="rows" :columns="columns" row-key="key" :loading="loading" :pagination="pagination" :scroll="{ x: 740 }" :row-class-name="record => selected?.key === record.key ? 'audit-selected' : ''" :custom-row="record => ({ onClick: () => select(record) })" :locale="{ emptyText: error ? t('auditLog.emptyAfterError') : t('auditLog.empty') }" @change="tableChange">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'identity'"><strong>{{ record.agent_name || record.agent_id || ui('unlinkedAgent') }}</strong><small v-if="record.local_agent">{{ ui('localAgent') }} · {{ record.local_agent }}</small><small>{{ record.client_name || record.client_id || ui('unlinkedClient') }}</small></template>
            <template v-else-if="column.key === 'event'"><button class="event-link" :aria-expanded="selected?.key === record.key" @click.stop="select(record)">{{ title(record) }}</button><small>{{ record.object_name || record.object_id || '—' }}</small><span class="category-label">{{ ui('categories.' + record.category) }}</span></template>
            <template v-else-if="column.key === 'result'"><a-tag :color="tone(record)">{{ resultLabel(record) }}</a-tag><small v-if="clientView(record)?.retained">{{ t('clientEvents.retained') }}</small></template>
            <template v-else-if="column.key === 'timestamp'"><time>{{ time(record.timestamp) }}</time><small>{{ ui('time.' + record.time_kind) }}</small><small v-if="clientView(record)?.count">{{ clientView(record).count }}</small></template>
          </template>
        </a-table>
      </section>
      <aside v-if="selected" ref="detailPanel" class="audit-detail" :aria-label="ui('detail')">
        <header class="detail-header"><span>{{ ui('detail') }}</span><a-button type="text" :aria-label="ui('close')" @click="close"><CloseOutlined /></a-button></header>
        <div class="detail-body">
          <ClientEventDetail v-if="selected.client_event && selected.category === 'capability'" :key="selected.key" :record="selected.client_event" :client-id="selected.client_id" :client-name="selected.client_name" :agent-label="agentLabel" :show-back="false" @close="close" @collection="refresh" />
          <template v-else>
            <div class="detail-title"><h2>{{ title(selected) }}</h2><a-tag :color="tone(selected)">{{ resultLabel(selected) }}</a-tag></div>
            <p class="muted">{{ time(selected.timestamp) }} · {{ ui('time.' + selected.time_kind) }}</p>
            <section><h3>{{ ui('what') }}</h3><p><span class="muted">{{ ui(['task','security'].includes(selected.source) ? 'fields.task_id' : 'object') }} · </span>{{ selected.object_name || selected.object_id || '—' }}</p><div v-if="selected.event_type === 'runtime_action_authorized'" class="decision-pair"><div><small>{{ ui('platformDecision') }}</small><strong>{{ resultLabel(selected) }}</strong></div><div><small>{{ ui('execution') }}</small><strong>{{ ui('unknown') }}</strong></div></div><p v-if="boundary" class="context-note">{{ boundary }}</p></section>
          </template>
          <section><h3>{{ ui('objects') }}</h3><dl class="facts"><div><dt>{{ ui('platformAgent') }}</dt><dd>{{ selected.agent_name || selected.agent_id || ui('unlinkedAgent') }}<small v-if="selected.agent_name">{{ selected.agent_id }}</small></dd></div><div v-if="selected.local_agent"><dt>{{ ui('localAgent') }}</dt><dd>{{ selected.local_agent }}</dd></div><div><dt>{{ ui('client') }}</dt><dd>{{ selected.client_name || selected.client_id || ui('unlinkedClient') }}<small v-if="selected.client_name">{{ selected.client_id }}</small></dd></div><div v-if="selected.actor"><dt>{{ ui('actor') }}</dt><dd>{{ selected.actor }}</dd></div></dl></section>
          <section v-if="detailFields.length"><h3>{{ ui('sourceFacts') }}</h3><dl class="facts"><div v-for="field in detailFields" :key="field.key"><dt>{{ ui('fields.' + field.key) }}</dt><dd>{{ fieldValue(field.key, field.value) }}</dd></div></dl></section>
          <section><h3>{{ ui('evidence') }}</h3><dl class="facts"><div><dt>{{ ui('source') }}</dt><dd>{{ ui('sources.' + selected.source) }}</dd></div><div><dt>{{ ui('eventCode') }}</dt><dd class="mono">{{ selected.event_type }}</dd></div><div><dt>{{ ui('sourceKey') }}</dt><dd class="mono">{{ selected.source_id }}</dd></div></dl></section>
        </div>
        <footer><a-space wrap><a-button v-if="selected.source === 'security' && can('runtime:view')" type="primary" @click="taskId = selected.object_id">{{ ui('viewTask') }}</a-button><a-button v-if="selected.can_view_agent" @click="openAgent">{{ ui('viewAgent') }}</a-button><a-button v-if="selected.can_view_client" @click="router.push({ path:'/clients', query:{ client:selected.client_id, section:'audit' } })">{{ ui('viewClient') }}</a-button><a-button v-if="selected.skill_id" @click="router.push('/skills/' + encodeURIComponent(selected.skill_id))">{{ ui('viewSkill') }}</a-button><a-button @click="close">{{ ui('back') }}</a-button></a-space></footer>
      </aside>
    </div>
    <a-drawer :open="!!taskId" :title="ui('task.title')" :width="680" :styles="{ wrapper:{ maxWidth:'100vw' } }" destroy-on-close @close="taskId = ''"><AuditRuntimeTask v-if="taskId" :task-id="taskId" /></a-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { CloseOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { getAgentAuditTrail, getAgentAuditTrailOptions } from '../api'
import { translateDomain } from '../i18n'
import { can } from '../access'
import ClientEventDetail from '../components/ClientEventDetail.vue'
import AuditRuntimeTask from '../components/AuditRuntimeTask.vue'
import '../../../client/desktop/src/event-records.js'

const { t, te, locale } = useI18n(), router = useRouter()
const ui = (key, args = {}) => t('auditTrail.' + key, args)
const eventUi = (key, args = {}, fallback = 'unknown') => t('clientEvents.' + (te('clientEvents.' + key) ? key : fallback), args)
const rows = ref([]), selected = ref(null), loading = ref(false), error = ref(false), keyword = ref(''), taskId = ref(''), detailPanel = ref(null)
const options = ref({ agents:[], clients:[], categories:[], results:[] })
const optionsLoading = ref(false), optionsError = ref(false)
const filters = reactive({ agent:'', client_id:'', category:'', result:'', days:7 })
const current = ref(1), pageSize = ref(10), total = ref(0), order = ref('desc')
let request = 0, optionsRequest = 0, searchTimer
const pagination = computed(() => ({ current:current.value, pageSize:pageSize.value, total:total.value, showSizeChanger:true, pageSizeOptions:['10','20','50'], showTotal:value => t('auditLog.paginationTotal', { total:value }) }))
const all = () => ({ value:'', label:ui('all') })
const agentOptions = computed(() => [all(), ...options.value.agents.map(v => ({ value:v.value, label:v.kind === 'local' ? ui('localOption', { name:v.name }) : v.name }))])
const clientOptions = computed(() => [all(), ...options.value.clients.map(v => ({ value:v.value, label:v.name }))])
const categoryOptions = computed(() => [all(), ...options.value.categories.map(v => ({ value:v, label:ui('categories.' + v) }))])
const resultOptions = computed(() => [all(), ...options.value.results.map(v => ({ value:v, label:ui('results.' + v) }))])
const timeOptions = computed(() => [{ value:1, label:t('auditLog.last24Hours') }, { value:7, label:t('auditLog.last7Days') }, { value:30, label:t('auditLog.last30Days') }, { value:0, label:ui('allTime') }])
const columns = computed(() => [{ title:ui('identity'), key:'identity', width:180 }, { title:ui('eventObject'), key:'event', width:230 }, { title:ui('result'), key:'result', width:155 }, { title:t('auditLog.time'), key:'timestamp', width:175, sorter:true, sortOrder:order.value === 'asc' ? 'ascend' : 'descend' }])
const agentLabel = value => value || ui('unknown')
const clientView = record => record?.client_event ? globalThis.clientEventRecords.describe(record.client_event, eventUi) : null
function title(record) {
  if (record.source === 'task') return translateDomain('taskType', record.event_type, ui('events.client_task'))
  const client = clientView(record)
  if (client && record.client_event.presentation?.title !== 'unknown_event') return client.title
  if (record.source === 'management') return ui('events.management', { module:t('iam.modules.' + record.module), action:te('iam.operations.' + record.event_type) ? t('iam.operations.' + record.event_type) : record.event_type })
  if (te('auditTrail.events.' + record.title)) return ui('events.' + record.title)
  return translateDomain('auditEvent', record.event_type, ui('events.unknown'))
}
const resultLabel = record => record.source === 'task' ? translateDomain('taskStatus', record.result === 'success' ? 'succeeded' : record.result, ui('results.' + record.result)) : (record.category === 'capability' ? clientView(record)?.state : '') || ui('results.' + record.result)
const tone = record => ({ deny:'red', failed:'red', alert_active:'orange', success:'green', allow:'blue', pending:'gold', require_approval:'gold', running:'processing' })[record.result] || 'default'
const time = value => value ? new Date(value).toLocaleString(locale.value, { hour12:false, timeZone:'Asia/Shanghai' }) : '—'
const boundary = computed(() => selected.value?.event_type === 'runtime_action_authorized' ? ui('authorizationBoundary') : selected.value?.source === 'task' ? ui('taskBoundary') : ['management','operation'].includes(selected.value?.source) ? ui('managementBoundary') : '')
const detailFields = computed(() => Object.entries(selected.value?.details || {}).filter(([key,value]) => te('auditTrail.fields.' + key) && value !== '' && value != null && (!selected.value.client_event || !['path','session_id','native_call_id','source','skill_id'].includes(key))).map(([key,value]) => ({ key,value })))
function fieldValue(key, value) {
  if (typeof value === 'boolean') return ui(value ? 'yes' : 'no')
  if (key === 'decision_reasons') return (Array.isArray(value) ? value : [value]).map(code => te('auditTrail.reasons.' + code) ? ui('reasons.' + code) : code).join(' · ') || '—'
  if (Array.isArray(value)) return value.join(' · ') || '—'
  if (key === 'decision' && te('auditTrail.results.' + value)) return ui('results.' + value)
  if (key === 'task_type') return translateDomain('taskType', value, value)
  if (key === 'error_code' && te('aidr.skillUse.review.taskErrors.' + value)) return t('aidr.skillUse.review.taskErrors.' + value)
  if (key === 'risk_level') return translateDomain('risk', value, value)
  if (key === 'status') return translateDomain('skillStatus', value, translateDomain('taskStatus', value, value))
  return value
}
async function select(record) { selected.value = record; taskId.value = ''; await nextTick(); if (window.innerWidth < 1280) detailPanel.value?.scrollIntoView({ block:'start', behavior:'smooth' }) }
function close() { selected.value = null; taskId.value = '' }
function openAgent() { router.push({ path:'/agents', query: selected.value.agent_origin === 'client_discovery' ? { agent:selected.value.agent_id } : { detail:selected.value.agent_id } }) }
async function load() {
  const id = ++request; loading.value = true; error.value = false
  try {
    const data = await getAgentAuditTrail({ ...filters, q:keyword.value.trim(), page:current.value, page_size:pageSize.value, order:order.value })
    if (id !== request) return
    total.value = data.total
    if (current.value > 1 && (current.value - 1) * pageSize.value >= data.total) { current.value = Math.max(1, Math.ceil(data.total / pageSize.value)); return load() }
    rows.value = data.items
    if (selected.value) selected.value = rows.value.find(row => row.key === selected.value.key) || null
  } catch { if (id === request) { error.value = true; rows.value = []; total.value = 0; close() } }
  finally { if (id === request) loading.value = false }
}
async function loadOptions() {
  if (optionsLoading.value) return
  const id = ++optionsRequest; optionsLoading.value = true; optionsError.value = false
  try {
    const data = await getAgentAuditTrailOptions()
    if (id === optionsRequest) options.value = data
  } catch { if (id === optionsRequest) optionsError.value = true }
  finally { if (id === optionsRequest) optionsLoading.value = false }
}
function filter() { clearTimeout(searchTimer); searchTimer = undefined; current.value = 1; close(); load() }
function refresh() { clearTimeout(searchTimer); if (searchTimer) current.value = 1; searchTimer = undefined; load(); loadOptions() }
function reset() { keyword.value = ''; Object.assign(filters, { agent:'', client_id:'', category:'', result:'', days:7 }); filter() }
function tableChange(pager, _, sorter) { current.value = searchTimer ? 1 : pager.current; clearTimeout(searchTimer); searchTimer = undefined; pageSize.value = pager.pageSize; order.value = sorter.order === 'ascend' ? 'asc' : 'desc'; close(); load() }
watch(keyword, () => { clearTimeout(searchTimer); request++; searchTimer = setTimeout(filter, 300) }, { flush:'sync' })
onMounted(() => { load(); loadOptions() })
onBeforeUnmount(() => { clearTimeout(searchTimer); request++; optionsRequest++ })
</script>

<style scoped>
.audit-page { color:#26364a; min-width:0; }
.audit-page.with-detail { display:grid; grid-template-columns:minmax(0, 1.55fr) minmax(420px, 1fr); column-gap:20px; align-items:start; }
.with-detail > .audit-heading, .with-detail > .audit-controls, .with-detail > .audit-scope, .with-detail > .audit-error { grid-column:1; }
.audit-heading { display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:22px; }
h1 { font-size:28px; font-weight:650; margin:0 0 6px; } .audit-heading p { margin:0; color:#718096; }
.audit-controls { padding:0; }
.audit-filters { display:flex; align-items:flex-end; flex-wrap:wrap; gap:12px; margin-top:16px; }
.audit-filters label { display:flex; flex:1 1 110px; min-width:0; flex-direction:column; gap:6px; color:#627084; font-size:12px; }
.audit-filters :deep(.ant-select) { width:100%; } .audit-scope { color:#718096; font-size:12px; margin:14px 0; } .audit-error { margin-bottom:16px; }
.audit-filters :deep(.wrap-select.ant-select-single .ant-select-selector) { height:auto; min-height:32px; }
.audit-filters :deep(.wrap-select.ant-select-single .ant-select-selection-item) { white-space:normal; line-height:1.45; padding-top:6px; padding-bottom:6px; }
.audit-workspace { display:grid; gap:20px; align-items:start; min-width:0; }
.audit-workspace.has-detail { display:contents; }
.has-detail .audit-list { grid-column:1; }
.has-detail .audit-detail { grid-column:2; grid-row:1 / span 5; }
.audit-list { min-width:0; background:white; border:1px solid #e4e9ef; border-radius:8px; overflow:hidden; }
.audit-list :deep(td) { vertical-align:top; overflow-wrap:anywhere; cursor:pointer; padding:12px; }
.audit-list :deep(.ant-table-tbody > tr > td) { padding:10px 12px; }
.audit-list :deep(.ant-table-thead > tr > th) { background:#f8fafc; color:#68788c; font-size:12px; }
.audit-list :deep(.audit-selected > td) { background:#edf4ff !important; } .audit-list :deep(.audit-selected > td:first-child) { box-shadow:inset 3px 0 #3376d5; }
.audit-list :deep(.ant-pagination) { padding:0 16px; flex-wrap:wrap; } .audit-list strong { font-size:14px; }
small { display:block; margin-top:5px; color:#718096; line-height:1.6; font-size:12px; } time { font-size:12px; font-variant-numeric:tabular-nums; }
.event-link { background:none; border:0; padding:0; color:#263c59; text-align:left; font:inherit; font-size:14px; font-weight:600; cursor:pointer; }
.event-link:hover { color:#246dc6; } .event-link:focus-visible { outline:2px solid #246dc6; outline-offset:4px; }
.category-label { display:inline-block; margin-top:4px; color:#6a7b8e; background:#f4f6f8; padding:2px 6px; font-size:11px; border-radius:3px; }
.audit-page :deep(.ant-tag) { white-space:normal; margin:0; } .audit-detail { min-width:0; position:sticky; top:20px; max-height:calc(100vh - 112px); display:flex; flex-direction:column; background:white; border:1px solid #dce4ee; border-radius:8px; box-shadow:0 4px 18px #21365208; }
.detail-header { display:flex; justify-content:space-between; align-items:center; padding:12px 22px; border-bottom:1px solid #e8edf2; color:#64758a; font-size:13px; }
.detail-body { padding:24px; overflow:auto; overflow-wrap:anywhere; } .detail-title { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
h2 { font-size:22px; margin:0; } h3 { font-size:13px; color:#586c84; margin:0 0 14px; } .muted { color:#718096; font-size:12px; }
.detail-body > section { border-top:1px solid #e8edf2; padding:22px 0; } .facts { margin:0; display:grid; gap:14px; } .facts > div { display:grid; grid-template-columns:115px minmax(0, 1fr); gap:14px; }
dt { color:#748297; font-size:12px; } dd { margin:0; font-size:13px; white-space:pre-wrap; } .mono { font-family:ui-monospace, monospace; }
.decision-pair { display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:16px; background:#f7f9fc; border:1px solid #e7edf5; border-radius:6px; } .decision-pair strong { display:block; margin-top:6px; }
.context-note { font-size:12px; line-height:1.8; color:#62748b; margin:14px 0 0; } footer { padding:16px 22px; border-top:1px solid #e8edf2; }
@media(max-width:1279px) { .audit-page.with-detail { display:block; } .with-detail > .audit-controls, .with-detail > .audit-scope { display:none; } .has-detail .audit-list { display:none; } .audit-detail { position:static; max-height:none; } }
@media(max-width:600px) { h1 { font-size:24px; } .audit-heading { align-items:flex-start; } .audit-controls { padding:14px; } .audit-filters label { flex-basis:calc(50% - 12px); } .detail-body { padding:18px; } .detail-title { flex-wrap:wrap; } .facts > div { grid-template-columns:minmax(80px, 30%) minmax(0,1fr); } .decision-pair { grid-template-columns:1fr; } }
</style>
