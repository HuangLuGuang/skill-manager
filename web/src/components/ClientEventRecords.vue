<template>
  <section class="event-records" :aria-label="ui('title')">
    <div class="event-filters">
      <label class="event-search"><span>{{ ui('search') }}</span><a-input-search v-model:value="filters.keyword" :maxlength="200" :placeholder="ui('search')" allow-clear @input="searchLater" @search="filter" /></label>
      <label><span>Agent</span><a-select v-model:value="filters.agent" :options="options(agents, value => agentLabel(value))" @change="filter" /></label>
      <label><span>{{ ui('category') }}</span><a-select v-model:value="filters.category" :options="options(categories, value => ui('category_' + value))" @change="filter" /></label>
      <label><span>{{ ui('handling') }}</span><a-select v-model:value="filters.status" :options="options(states, value => ui('state_' + value))" @change="filter" /></label>
      <label><span>{{ ui('days') }}</span><a-select v-model:value="filters.days" :options="[0,1,7,30].map((value, index) => ({ value, label:ui(['allTime','day','week','month'][index]) }))" @change="filter" /></label>
      <a-button @click="reset">{{ ui('reset') }}</a-button>
      <a-button :loading="loading" @click="load">{{ ui('refresh') }}</a-button>
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
      <ClientEventDetail v-if="selected" :record="selected" :client-id="clientId" :client-name="clientName" :agent-label="agentLabel" @close="selected = null" @collection="$emit('collection')" />
    </a-drawer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RightOutlined } from '@ant-design/icons-vue'
import { getClientEventRecords } from '../api'
import ClientEventDetail from './ClientEventDetail.vue'
import '../../../client/desktop/src/event-records.js'
const props = defineProps({ clientId:String, clientName:String, agentLabel:{ type:Function, required:true } })
defineEmits(['collection'])
const { t, te, locale } = useI18n()
const ui = (key, args = {}, fallback = 'unknown') => t('clientEvents.' + (te('clientEvents.' + key) ? key : fallback), args)
const describe = event => globalThis.clientEventRecords.describe(event, ui)
const agentLabel = value => props.agentLabel(value)
const time = value => value ? new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(String(value)) ? value : value + 'Z').toLocaleString(locale.value, { hour12:false, timeZone:'Asia/Shanghai' }) : '—'
const filters = reactive({ keyword:'', agent:'', category:'', status:'', days:0 })
const items = ref([]), agents = ref([]), categories = ref([]), states = ref([]), total = ref(0), page = ref(1), pageSize = ref(10)
const loading = ref(false), error = ref(false), selected = ref(null)
let request = 0, timer, disposed = false
const rows = computed(() => items.value.map(event => ({ ...event, view:describe(event) })))
const columns = computed(() => [{ key:'identity', title:'Skill / Agent', width:190 }, { key:'event', title:ui('event'), width:290 }, { key:'state', title:ui('handling'), width:150 }, { key:'time', title:ui('time'), width:180 }, { key:'open', width:30 }])
const pagination = computed(() => ({ current:page.value, pageSize:pageSize.value, total:total.value, showSizeChanger:true, pageSizeOptions:['10','20','50'] }))
const options = (values, label) => [{ value:'', label:ui('all') }, ...values.map(value => ({ value, label:label(value) }))]
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
watch(() => props.clientId, () => { selected.value = null; reset() }, { immediate:true })
onBeforeUnmount(() => { disposed = true; request++; clearTimeout(timer) })
defineExpose({ refresh:load })
</script>

<style scoped>
.muted, small, dt { color:#697586; } small { display:block; font-size:12px; line-height:1.6; margin-top:5px; }
.event-filters { display:flex; align-items:flex-end; flex-wrap:wrap; gap:12px; margin-bottom:20px; }
.event-filters label { display:flex; flex-direction:column; gap:6px; flex:1 1 155px; min-width:0; }
.event-filters .event-search { flex:2 1 240px; } .event-filters .ant-select { width:100%; }
.event-title { padding:0; height:auto; white-space:normal; text-align:left; font-weight:600; line-height:1.6; }
.event-records :deep(td) { vertical-align:top; overflow-wrap:anywhere; cursor:pointer; }
.event-state { display:inline-block; padding:3px 9px; border:1px solid; border-radius:4px; font-size:12px; line-height:1.6; }
.neutral { color:#596774; background:#f6f8fa; border-color:#cbd3dc; } .warning { color:#ad5418; background:#fff8ed; border-color:#efc18f; }
.danger { color:#b7333b; background:#fff1f2; border-color:#f0a9ae; } .success { color:#257664; background:#f0faf6; border-color:#91c9b7; } .info { color:#246ac6; background:#f0f6ff; border-color:#a9c9f4; }
</style>
