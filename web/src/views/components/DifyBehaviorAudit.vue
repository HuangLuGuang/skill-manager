<template>
  <p class="muted">{{ t('difyRuntime.auditScope') }}</p>
  <a-empty v-if="!runs.length" :description="t('difyRuntime.noRuns')" />
  <div v-else class="audit-layout">
    <aside class="run-list" :aria-label="t('difyRuntime.runs')">
      <header class="list-heading">{{ t('difyRuntime.runs') }}<span>{{ runs.length }}</span></header>
      <button v-for="run in runs" :key="run.task_id" type="button" class="run-item" :class="{ selected: selectedId === run.task_id }" :aria-pressed="selectedId === run.task_id" @click="selectedId = run.task_id">
        <span>{{ formatDateTime(run.created_at) }}</span>
        <a-tag :color="run.status === 'succeeded' ? 'green' : run.status === 'failed' ? 'red' : 'blue'">{{ label(run.status) }}</a-tag>
        <small :title="run.run_id">{{ run.run_id }}</small>
      </button>
    </aside>
    <section v-if="selectedRun" class="run-detail" :aria-label="t('difyRuntime.audit')">
      <header class="detail-heading"><div><h2>{{ t('difyRuntime.runs') }}</h2><span>{{ formatDateTime(selectedRun.created_at) }}</span></div><a-tag :color="selectedRun.status === 'succeeded' ? 'green' : 'red'">{{ label(selectedRun.status) }}</a-tag></header>
      <details class="run-identifiers"><summary>{{ t('difyRuntime.run') }} · {{ selectedRun.run_id }}</summary>
      <a-descriptions size="small" :column="1" class="run-meta">
        <a-descriptions-item :label="t('difyRuntime.run')">{{ selectedRun.run_id }}</a-descriptions-item>
        <a-descriptions-item :label="t('difyRuntime.workflow')">{{ selectedRun.workflow_id }}</a-descriptions-item>
        <a-descriptions-item :label="t('difyRuntime.version')">{{ selectedRun.graph_digest }}</a-descriptions-item>
        <a-descriptions-item :label="t('difyRuntime.status')">{{ label(selectedRun.status) }}</a-descriptions-item>
      </a-descriptions>
      </details>
      <h3>{{ t('difyRuntime.executionTimeline') }}</h3>
      <p class="muted">{{ t('difyRuntime.contentHelp') }}</p>
      <a-alert v-if="error" type="error" :message="error"><template #action><a-button @click="loadEvents(false)">{{ t('difyRuntime.refresh') }}</a-button></template></a-alert>
      <a-spin :spinning="loading">
        <a-empty v-if="!loading && !error && !events.length" :description="t('difyRuntime.noEvents')" />
        <ol class="events">
          <li v-for="step in steps" :key="step.id">
            <header class="step-heading"><strong>{{ step.models.find(model => model.input?.model)?.input.model || step.title }}</strong><span>{{ nodeLabel(step.type) }}</span><time>{{ formatDateTime(step.time) }}</time><a-tag :color="['failed','blocked'].includes(step.status) ? 'red' : step.status === 'succeeded' ? 'green' : 'blue'">{{ label(step.status) }}</a-tag></header>
            <a-alert v-for="reason in step.errors" :key="reason" type="error" :message="t('difyRuntime.executionError')" show-icon><template #description><pre class="failure-text">{{ failureText(reason) }}</pre></template></a-alert>
            <a-alert v-if="step.truncated" type="warning" :message="t('difyRuntime.contentTruncated')" />
            <section v-for="(input,index) in step.userInputs" :key="`user-${index}`"><h4>{{ t('difyRuntime.userInput') }}</h4><DifyExecutionContent :value="input" /></section>
            <details v-if="step.execution.length || step.inputs.length" open><summary>{{ t('difyRuntime.executionDetails') }}</summary><DifyExecutionContent v-for="(value,index) in [...step.execution,...step.inputs]" :key="index" :value="value" /></details>
            <section v-for="model in step.models" :key="model.id" class="model-call">
              <h4>{{ t('difyRuntime.modelInput') }}</h4><DifyExecutionContent v-if="model.input" :value="model.input" />
              <h4 v-if="model.outputs.length">{{ t('difyRuntime.modelOutput') }}</h4><DifyExecutionContent v-if="model.outputs.length" :value="modelOutput(model)" />
              <a-tag v-if="!model.complete">{{ t('difyRuntime.incomplete') }}</a-tag>
            </section>
            <section v-for="(output,index) in step.outputs" :key="`out-${index}`"><h4>{{ t(step.type === 'workflow' || step.type === 'answer' || step.type === 'end' ? 'difyRuntime.finalReply' : 'difyRuntime.outputs') }}</h4><DifyExecutionContent :value="output" /></section>
            <p v-if="!step.hasContent && step.status !== 'started'" class="muted">{{ t('difyRuntime.noContent') }}</p>
          </li>
        </ol>
      </a-spin>
      <a-button v-if="hasMore" :loading="loading" :disabled="loading" @click="loadEvents(true)">{{ t('difyRuntime.moreEvents') }}</a-button>
      <h3>{{ t('difyRuntime.calls') }}</h3>
      <a-table size="small" :data-source="runCalls" row-key="action_id" :scroll="{ x:650 }" :pagination="{ pageSize:10, hideOnSinglePage:true }">
        <a-table-column :title="t('difyRuntime.node')" data-index="node_id" />
        <a-table-column :title="t('difyRuntime.type')"><template #default="{ record }">{{ nodeLabel(record.node_type) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.callTarget')"><template #default="{ record }">{{ [record.method, record.host || record.tool || record.datasets?.join(', ')].filter(Boolean).join(' ') || '—' }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.status')"><template #default="{ record }">{{ label(record.status) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.reason')"><template #default="{ record }">{{ record.reasons.map(reason => localized('reasonLabels', reason)).join(', ') }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.approval')"><template #default="{ record }">
          <a-space v-if="record.approval_status === 'pending' && hasAccess('runtime:execute')" wrap>
            <a-button :loading="reviewing === record.action_id" :disabled="!!reviewing" @click="$emit('review', record.action_id, true)">{{ t('difyRuntime.approve') }}</a-button>
            <a-button :disabled="!!reviewing" @click="$emit('review', record.action_id, false)">{{ t('difyRuntime.reject') }}</a-button>
          </a-space>
          <span v-else>{{ label(record.approval_status) }}</span>
        </template></a-table-column>
      </a-table>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import DifyExecutionContent from './DifyExecutionContent.vue'
import { useI18n } from 'vue-i18n'
import { listRuntimeTraceEvents } from '../../api'
import { can as hasAccess } from '../../access'
import { formatBeijingDateTime as formatDateTime } from '../../utils/format'
const props = defineProps({ runs: { type:Array, required:true }, calls: { type:Array, required:true }, reviewing:String, refreshKey:Number })
defineEmits(['review'])
const { t, te } = useI18n()
const selectedId = ref(''), events = ref([]), loading = ref(false), error = ref(''), hasMore = ref(false), cursor = ref(null)
let generation = 0
const selectedRun = computed(() => props.runs.find(run => run.task_id === selectedId.value))
const runCalls = computed(() => props.calls.filter(call => call.task_id === selectedId.value))
function localized(group, value) { const key=`difyRuntime.${group}.${group === 'eventLabels' ? value?.replaceAll('.', '_') : value}`; return te(key) ? t(key) : value || '—' }
function label(value) { const key=`difyRuntime.${value}`; return te(key) ? t(key) : value || '—' }
function nodeLabel(value) { return localized('nodeLabels', value) }
function failureText(value) {
  return String(value).replace(/dify_runtime\.skill_not_approved: ([^\n]+) \(([^()\n]+)\)/g, (_, name, reason) =>
    `${name}: ${t('difyRuntime.skillAdmission.reasons.unapproved_blocked')} ${localized('skillAdmission.checks', reason)}`)
}
function content(event, field) {
  const encoded=event.payload?.content?.[field]?.join('') ?? event.payload?.[field]
  const entities={amp:'&',lt:'<',gt:'>',quot:'"','#x27':"'",'#39':"'"}
  const text=event.payload?.content?.[field] ? encoded : encoded?.replace(/&(amp|lt|gt|quot|#x27|#39);/g,(_,key)=>entities[key])
  if (!text || ['{}','[]','null'].includes(text)) return null
  try { return JSON.parse(text) } catch { return text }
}
const steps=computed(()=>{
  const groups=new Map()
  const ordered=[...events.value].sort((a,b)=>Date.parse(a.event_time)-Date.parse(b.event_time) || a.seq-b.seq)
  for(const event of ordered){
    const p=event.payload || {}, sourceId=event.step_id || p.node_id || event.event_id
    const id=event.type==='turn.end' ? `final:${sourceId}` : sourceId
    if(!groups.has(id)) groups.set(id,{id,title:p.node_title || p.node_id || id,type:p.node_type,time:event.event_time,status:'started',inputs:[],outputs:[],execution:[],userInputs:[],errors:[],models:[],truncated:false,hasContent:false})
    const step=groups.get(id)
    if(p.node_title) step.title=p.node_title
    if(p.node_type) step.type=p.node_type
    if(event.type==='turn.end') step.title=t('difyRuntime.finalReply')
    if(['step.end','turn.end'].includes(event.type)) step.status=event.status
    step.truncated ||= !!p.truncated
    const error=content(event,'error')
    if(error && !step.errors.includes(error)) step.errors.push(error)
    if(event.type.startsWith('model.')){
      const id=event.request_id || event.event_id
      let model=step.models.find(item=>item.id===id)
      if(!model){model={id,input:null,outputs:[],complete:false};step.models.push(model)}
      if(event.type==='model.request') model.input=content(event,'inputs')
      const output=content(event,'outputs')
      if(output) model.outputs.push(output)
      if(event.status==='succeeded') model.complete=true
    } else {
      for(const field of ['inputs','outputs','execution']){
        const value=content(event,field)
        if(value) step[event.type==='message.user' && field==='inputs' ? 'userInputs' : field].push(value)
      }
    }
    step.hasContent=!!(step.inputs.length || step.outputs.length || step.execution.length || step.userInputs.length || step.models.length || step.errors.length)
  }
  const result=[...groups.values()]
  for(const step of result){
    if(step.type==='start' && step.userInputs.length){step.inputs=[];step.outputs=[]}
  }
  return result.filter(step=>step.type!=='workflow' || !result.some(other=>['end','answer'].includes(other.type) && JSON.stringify(other.outputs)===JSON.stringify(step.outputs) && step.outputs.length))
})
function modelOutput(model){
  if(model.outputs.length===1 && !('index' in model.outputs[0])) {
    const value=model.outputs[0]
    return {content:value.message?.content ?? value,...(value.message?.tool_calls?.length ? {tool_calls:value.message.tool_calls} : {}),...(value.reasoning_content ? {reasoning_content:value.reasoning_content} : {}),...(value.usage ? {usage:value.usage} : {})}
  }
  const messages=model.outputs.map(item=>item.message).filter(Boolean)
  const text=messages.map(item=>typeof item.content==='string' ? item.content : JSON.stringify(item.content ?? '')).join('')
  const tools=messages.flatMap(item=>item.tool_calls || [])
  const last=model.outputs.at(-1)
  return {content:text,...(tools.length ? {tool_calls:tools} : {}),...(last?.usage ? {usage:last.usage} : {})}
}
async function loadEvents(append) {
  if (append && loading.value) return
  const run=selectedRun.value
  const ticket=++generation
  error.value=''; loading.value=true
  if (!append) { events.value=[]; cursor.value=null; hasMore.value=false }
  if (!run) { loading.value=false; return }
  try {
    do {
    const response=await listRuntimeTraceEvents(run.trace_id, { page_size:1000, ...(cursor.value != null ? { after_seq:cursor.value } : {}) })
    if (ticket !== generation) return
    events.value=[...events.value, ...response.items]
    cursor.value=response.next_after_seq; hasMore.value=response.has_more
    } while(hasMore.value)
  } catch(e) { if(ticket === generation) error.value=e.response?.data?.detail || e.message }
  finally { if(ticket === generation) loading.value=false }
}
watch(() => props.runs, runs => { if (!runs.some(run => run.task_id === selectedId.value)) selectedId.value=runs[0]?.task_id || '' }, { immediate:true })
watch([selectedId, () => props.refreshKey], () => loadEvents(false), { immediate:true })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.muted { color:#7b8799; font-size:12px; line-height:1.7; margin:0 0 12px; }
.step-heading{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:12px 0}.step-heading>span{color:#64748b;font-size:12px}.failure-text{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;margin:0}.events h4{margin:16px 0 6px;font-size:13px}.model-call{border-top:1px solid #eff2f6;margin-top:12px}
.audit-layout { display:grid; grid-template-columns:280px minmax(0,1fr); gap:18px; min-width:0; flex:1; min-height:0; overflow:hidden; }
.list-heading { display:flex; justify-content:space-between; padding:16px; border-bottom:1px solid #e5eaf1; font-weight:600; background:white; position:sticky; top:0; z-index:1; }
.list-heading span { font-weight:400; color:#7b8799; }
.detail-heading { display:flex; justify-content:space-between; align-items:center; padding:18px 22px; border-bottom:1px solid #e5eaf1; }
.detail-heading h2 { font-size:16px; margin:0 0 5px; }
.detail-heading span { font-size:12px; color:#7b8799; }
.run-meta { padding:16px 22px 0; }
.execution-content { margin:12px 0; } .execution-content h4 { margin:0 0 8px; font-size:13px; } .execution-content pre { background:#f8fafc; border:1px solid #e5eaf1; padding:12px; border-radius:6px; white-space:pre-wrap; overflow-wrap:anywhere; max-height:360px; overflow:auto; font-size:12px; }
.run-identifiers > summary { padding:12px 22px; color:#7b8799; font-size:12px; border-bottom:1px solid #eff2f6; }
.run-detail h3 { font-size:14px; font-weight:600; padding:16px 22px 10px; margin:0; }
.run-detail > .ant-table-wrapper { padding:0 22px; }
.run-list { min-height:0; overflow:auto; overscroll-behavior:contain; border:1px solid #e5eaf1; border-radius:8px; }
.run-item { display:block; width:100%; text-align:left; padding:14px; border:0; border-bottom:1px solid #e5eaf1; background:white; color:inherit; cursor:pointer; }
.run-item:hover,.run-item.selected { background:#eff6ff; }
.run-item.selected { box-shadow:inset 3px 0 #1677ff; }
.run-item small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:8px; color:#7b8799; font-size:11px; }
.run-item > span:first-child { font-size:12px; }
.run-item .ant-tag { margin-left:6px; white-space:normal; }
.run-detail { min-width:0; min-height:0; background:white; border:1px solid #e5eaf1; border-radius:10px; overflow:auto; overscroll-behavior:contain; }
.run-detail > .muted { padding:0 22px; }
.run-detail :deep(.ant-descriptions-item-content) { overflow-wrap:anywhere; }
.events { padding:0 22px 20px 36px; list-style:none; }
.events li { border-left:1px solid #dce3ec; padding:4px 0 12px 20px; position:relative; }
.events li::before { content:''; position:absolute; left:-4px; top:18px; width:7px; height:7px; border-radius:50%; background:#8aa9e8; box-shadow:0 0 0 4px white; }
summary { cursor:pointer; overflow-wrap:anywhere; padding:10px 0; font-size:13px; }
summary > * { margin-right:12px; }
time { color:#64748b; font-size:12px; }
dl { display:grid; grid-template-columns:150px minmax(0,1fr); gap:8px 16px; background:#f8fafc; padding:14px; margin:12px 0 0; }
dt { color:#64748b; } dd { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; }
@media(max-width:760px) { .audit-layout { grid-template-columns:minmax(0,1fr); grid-template-rows:minmax(100px,25%) minmax(0,1fr); } dl { grid-template-columns:1fr; gap:4px; } dd { margin-bottom:8px; } }
</style>
