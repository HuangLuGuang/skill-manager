<template>
  <section class="event-records" :aria-label="ui('title')">
    <div class="event-toolbar"><div><h3>{{ ui('title') }}</h3><p class="muted">{{ ui('subtitle') }}</p></div><a-button :loading="loading" @click="load">{{ ui('refresh') }}</a-button></div>
    <div class="event-filters">
      <label class="event-search"><span>{{ ui('search') }}</span><a-input-search v-model:value="filters.keyword" :maxlength="200" :placeholder="ui('search')" allow-clear @input="searchLater" @search="filter" /></label>
      <label><span>Agent</span><a-select v-model:value="filters.agent" :options="options(agents, value => agentLabel(value))" @change="filter" /></label>
      <label><span>{{ ui('category') }}</span><a-select v-model:value="filters.category" :options="options(categories, value => ui('category_' + value))" @change="filter" /></label>
      <label><span>{{ ui('handling') }}</span><a-select v-model:value="filters.status" :options="options(states, value => ui('state_' + value))" @change="filter" /></label>
      <label><span>{{ ui('days') }}</span><a-select v-model:value="filters.days" :options="[0,1,7,30].map((value, index) => ({ value, label:ui(['allTime','day','week','month'][index]) }))" @change="filter" /></label>
      <a-button @click="reset">{{ ui('reset') }}</a-button>
    </div>
    <a-alert v-if="error" type="error" :message="ui('loadFailed')" show-icon />
    <a-table :data-source="rows" :columns="columns" row-key="id" :loading="loading" :pagination="pagination" :scroll="{ x:830 }" :locale="{ emptyText:ui('empty') }" :custom-row="rowProps" @change="changePage">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'identity'"><strong>{{ record.skill_name || '—' }}</strong><small>{{ agentLabel(record.agent_type) }}</small></template>
        <template v-else-if="column.key === 'event'"><a-button class="event-title" type="link" @click.stop="selected = record">{{ record.view.title }}</a-button><small>{{ record.view.category }} · {{ record.view.reason }}</small></template>
        <template v-else-if="column.key === 'state'"><span :class="['event-state', record.view.tone]">{{ record.view.state }}</span><small v-if="record.view.retained">{{ ui('retained') }}</small></template>
        <template v-else-if="column.key === 'time'"><time>{{ time(record.view.occurred_at) }}</time><small>{{ record.view.timeLabel }}</small><small v-if="record.view.count">{{ record.view.count }}</small></template>
        <template v-else><RightOutlined aria-hidden="true" /></template>
      </template>
    </a-table>
    <a-drawer :open="!!selected" :title="ui('detail')" :width="600" :destroy-on-close="true" @close="selected = null">
      <article v-if="selected" class="event-record-detail">
        <div class="event-detail-heading"><h2>{{ view.title }}</h2><span :class="['event-state', view.tone]">{{ view.state }}</span></div>
        <p><strong>{{ selected.skill_name || '—' }}</strong> / {{ agentLabel(selected.agent_type) }}<span v-if="clientName"> · {{ clientName }}</span></p>
        <section><h3>{{ ui('what') }}</h3><p v-if="selected.presentation?.category === 'audit'">{{ view.stage }}</p><dl class="event-facts"><div><dt>{{ view.timeLabel }}</dt><dd>{{ time(view.occurred_at) }}</dd></div><div><dt>{{ ui('source') }}</dt><dd>{{ view.category }}</dd></div></dl><p v-if="view.count" class="muted">{{ view.count }}</p></section>
        <section><h3>{{ ui('why') }}</h3><p>{{ view.reason }}</p></section>
        <section><h3>{{ ui('handled') }}</h3><p>{{ view.action }} · {{ view.state }}</p><dl class="event-facts"><div v-if="selected.presentation?.category === 'audit'"><dt>{{ ui('fileAction') }}</dt><dd>{{ ui('unknown') }}</dd></div><div v-if="view.checked_at"><dt>{{ ui('checked') }}</dt><dd>{{ time(view.checked_at) }}</dd></div></dl><p v-if="view.retained">{{ ui('retained') }}</p><p v-if="view.error">{{ ui('error') }}: {{ view.error }}</p></section>
        <section><h3>{{ ui('evidence') }}</h3><a-timeline v-if="view.timeline.length"><a-timeline-item v-for="(node, index) in view.timeline" :key="index"><time>{{ time(node.at) }}</time><strong>{{ phase(node) }}</strong><small>{{ ui('source_' + node.source) }}<template v-if="node.arrival"> · {{ ui('arrival') }}</template></small></a-timeline-item><a-timeline-item v-if="view.checked_at" color="gray"><time>{{ time(view.checked_at) }}</time><strong>{{ ui('checked') }}</strong><small>{{ ui('reason_' + view.current_reason, {}, 'reason_unknown') }}</small></a-timeline-item></a-timeline><p v-else class="muted">{{ ui('noEvidence') }}</p></section>
        <details><summary>{{ ui('technical') }}</summary><dl class="event-technical"><div v-for="field in technical" :key="field.key"><dt>{{ ui(field.key) }}</dt><dd>{{ field.value || ui('unknown') }}</dd></div></dl></details>
        <p v-if="selected.presentation?.category === 'audit'" class="event-boundary muted">{{ ui('boundary') }}</p>
      </article>
      <template #footer><a-space wrap><a-button v-if="selected?.details?.skill_id" @click="openSkill">{{ ui('viewSkill') }}</a-button><a-button v-if="view?.usage_id" type="primary" @click="evidenceId = view.usage_id">{{ ui('viewEvidence') }}</a-button><a-button @click="selected = null">{{ ui('back') }}</a-button></a-space></template>
    </a-drawer>
    <a-drawer :open="!!evidenceId" :width="680" :title="ui('evidence')" destroy-on-close @close="evidenceId = ''"><AidrSkillUseDetail v-if="evidenceId" :client-id="clientId" :usage-id="evidenceId" @close="evidenceId = ''" @collection="$emit('collection')" /></a-drawer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { RightOutlined } from '@ant-design/icons-vue'
import { getClientEventRecords } from '../api'
import AidrSkillUseDetail from './AidrSkillUseDetail.vue'
import '../../../client/desktop/src/event-records.js'
const props = defineProps({ clientId:String, clientName:String, agentLabel:{ type:Function, required:true } })
defineEmits(['collection'])
const { t, te, locale } = useI18n(), router = useRouter()
const ui = (key, args = {}, fallback = 'unknown') => t('clientEvents.' + (te('clientEvents.' + key) ? key : fallback), args)
const describe = event => globalThis.clientEventRecords.describe(event, ui)
const agentLabel = value => props.agentLabel(value)
const time = value => value ? new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(String(value)) ? value : value + 'Z').toLocaleString(locale.value, { hour12:false, timeZone:'Asia/Shanghai' }) : '—'
const filters = reactive({ keyword:'', agent:'', category:'', status:'', days:0 })
const items = ref([]), agents = ref([]), categories = ref([]), states = ref([]), total = ref(0), page = ref(1), pageSize = ref(10)
const loading = ref(false), error = ref(false), selected = ref(null), evidenceId = ref('')
let request = 0, timer, disposed = false
const rows = computed(() => items.value.map(event => ({ ...event, view:describe(event) })))
const view = computed(() => selected.value ? describe(selected.value) : null)
const columns = computed(() => [{ key:'identity', title:'Skill / Agent', width:190 }, { key:'event', title:ui('event'), width:290 }, { key:'state', title:ui('handling'), width:150 }, { key:'time', title:ui('time'), width:180 }, { key:'open', width:30 }])
const pagination = computed(() => ({ current:page.value, pageSize:pageSize.value, total:total.value, showSizeChanger:true, pageSizeOptions:['10','20','50'] }))
const technical = computed(() => [{ key:'path', value:view.value?.path }, { key:'session', value:view.value?.session_id }, { key:'native', value:view.value?.native_call_id }, { key:'code', value:selected.value?.event_type }, { key:'created', value:time(selected.value?.created_at) }])
const options = (values, label) => [{ value:'', label:ui('all') }, ...values.map(value => ({ value, label:label(value) }))]
const phase = node => ui('stage_' + (node.stage === 'host_confirmed' ? view.value.behavior === 'invocation' ? 'loaded' : 'read' : node.stage), {}, 'stage_unknown')
const rowProps = row => ({ onClick:() => { selected.value = row } })
async function load() {
  clearTimeout(timer)
  const id = ++request
  loading.value = true; error.value = false; items.value = []
  try {
    const data = await getClientEventRecords(props.clientId, { ...filters, page:page.value, page_size:pageSize.value })
    if (disposed || id !== request) return
    items.value = data.items; total.value = data.total; page.value = data.page
    agents.value = data.agents; categories.value = data.categories; states.value = data.states
  } catch { if (!disposed && id === request) { error.value = true; total.value = 0 } }
  finally { if (!disposed && id === request) loading.value = false }
}
function filter() { page.value = 1; void load() }
function searchLater() { clearTimeout(timer); request++; timer = setTimeout(filter, 300) }
function reset() { Object.assign(filters, { keyword:'', agent:'', category:'', status:'', days:0 }); filter() }
function changePage(value) { page.value = value.pageSize === pageSize.value ? value.current : 1; pageSize.value = value.pageSize; void load() }
function openSkill() { router.push('/skills/' + encodeURIComponent(selected.value.details.skill_id)) }
watch(() => props.clientId, () => { selected.value = null; evidenceId.value = ''; reset() }, { immediate:true })
onBeforeUnmount(() => { disposed = true; request++; clearTimeout(timer) })
defineExpose({ refresh:load })
</script>

<style scoped>
.event-toolbar { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:16px; }
.event-toolbar h3 { margin:0 0 4px; } .event-toolbar p { margin:0; }
.muted, small, dt { color:#697586; } small { display:block; font-size:12px; line-height:1.6; margin-top:5px; }
.event-filters { display:flex; align-items:flex-end; flex-wrap:wrap; gap:12px; margin-bottom:20px; }
.event-filters label { display:flex; flex-direction:column; gap:6px; flex:1 1 155px; min-width:0; }
.event-filters .event-search { flex:2 1 240px; } .event-filters .ant-select { width:100%; }
.event-title { padding:0; height:auto; white-space:normal; text-align:left; font-weight:600; line-height:1.6; }
.event-records :deep(td) { vertical-align:top; overflow-wrap:anywhere; cursor:pointer; }
.event-state { display:inline-block; padding:3px 9px; border:1px solid; border-radius:4px; font-size:12px; line-height:1.6; }
.neutral { color:#596774; background:#f6f8fa; border-color:#cbd3dc; } .warning { color:#ad5418; background:#fff8ed; border-color:#efc18f; }
.danger { color:#b7333b; background:#fff1f2; border-color:#f0a9ae; } .success { color:#257664; background:#f0faf6; border-color:#91c9b7; } .info { color:#246ac6; background:#f0f6ff; border-color:#a9c9f4; }
.event-detail-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; } h2 { font-size:21px; margin:0; }
.event-detail-heading .event-state { flex-shrink:0; max-width:42%; }
.event-record-detail { overflow-wrap:anywhere; } .event-record-detail section { padding:19px 0; border-top:1px solid #e8edf2; } h3 { font-size:14px; color:#4c5b6b; margin:0 0 10px; }
.event-facts { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin:12px 0 0; } dt { font-size:12px; margin-bottom:5px; } dd { margin:0; }
.event-record-detail :deep(.ant-timeline) { margin-top:20px; } .event-record-detail time { margin-right:12px; font-size:12px; color:#697586; }
.event-record-detail summary { cursor:pointer; color:#4c5b6b; padding:14px 0; border-top:1px solid #e8edf2; } .event-technical div { margin:12px 0; } .event-boundary { font-size:12px; margin-top:20px; }
@media(max-width:600px) { .event-facts { grid-template-columns:1fr; } .event-detail-heading { flex-wrap:wrap; } }
</style>
