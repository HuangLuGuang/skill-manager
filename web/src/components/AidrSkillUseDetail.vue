<template>
  <aside class="skill-detail" :aria-label="ui('details')" :aria-busy="loading">
    <header><h3>{{ selected ? name(selected) : ui('details') }}</h3><a-button type="text" :aria-label="ui('close')" @click="$emit('close')"><CloseOutlined /></a-button></header>
    <a-alert v-if="error" type="error" :message="tr('error')" show-icon><template #action><a-button @click="load">{{ ui('retry') }}</a-button></template></a-alert>
    <a-spin v-if="loading && !selected" />
    <template v-if="selected">
      <p class="muted">{{ tr(selected.skill.behavior) }} · {{ time(selected.first_at) }} · {{ entryName }}</p>
      <div class="state-pair"><div><span>{{ ui('outcome') }}</span><a-tag :color="outcomeTone(selected.stage)">{{ phase(selected) }}</a-tag></div><div><span>{{ ui('certification') }}</span><a-tag :color="tone(selected.certification?.status)">{{ tr(selected.certification?.status || 'pending') }}</a-tag></div></div>
      <p class="skill-path"><span class="muted">{{ tr('path') }}</span> {{ selected.skill.path || tr('source_unknown') }}</p>
      <p v-if="selected.certification?.reason" class="muted">{{ reason(selected.certification.reason) }}</p>
      <section class="detail-section"><h4>{{ ui('timeline') }}</h4>
        <a-timeline>
          <a-timeline-item v-for="node in timeline" :key="node.key" :color="node.color">
            <time>{{ node.at ? time(node.at) : ui('arrivalAt', { time:time(node.receivedAt) }) }}</time><strong>{{ node.title }}</strong>
            <template v-if="node.kind === 'evidence'"><p class="muted">{{ ui(node.ref.source === 'hook' ? 'sourceHook' : 'sourceLog') }} · {{ node.ref.tool || selected.tool }}<template v-if="node.ref.turn_id"> · {{ ui('turn', { id:node.ref.turn_id }) }}</template></p><a-button type="link" size="small" :disabled="node.ref.available === false" @click="openEvidence(node.ref)">{{ node.ref.available === false ? ui('evidenceExpired') : ui('viewEvidence') }}</a-button></template>
            <template v-else-if="node.kind === 'observation'"><p v-if="node.observation.skill.content_status === 'reused'" class="muted">{{ tr('contentState.reused') }}</p><p class="digest">{{ node.observation.skill.content_digest || reason('content_' + node.observation.skill.content_reason) }}</p><p v-if="node.observation.resolved_path" class="skill-path">{{ ui('resolvedPath') }} {{ node.observation.resolved_path }}</p></template>
            <p v-else class="muted">{{ reason(node.check.reason) }}</p>
          </a-timeline-item>
        </a-timeline>
        <p v-if="['attempted', 'unknown'].includes(selected.stage)" class="muted">{{ ui('missingResult') }}</p>
        <a-button v-if="selected.checks_more" :loading="historyLoading" :disabled="historyLoading" @click="loadHistory">{{ ui('moreHistory') }}</a-button><p class="muted">{{ ui('historyBoundary') }}</p>
      </section>
      <section v-if="pending" class="detail-section pending-steps"><h4>{{ ui('pendingSteps') }}</h4>
        <ol><li><strong>{{ ui('inspectEvidence') }}</strong><p>{{ ui('inspectHelp') }}</p><a-button type="link" size="small" @click="$emit('collection')">{{ ui('collection') }}</a-button></li>
          <li v-if="needsContent"><strong>{{ ui('recollect') }}</strong><p>{{ ui('recollectHelp') }}</p><a-tooltip :title="unavailable"><a-button type="primary" :loading="submitting" :disabled="submitting || !!unavailable || taskActive" @click="recollect">{{ ui('requestObservation') }}</a-button></a-tooltip><p v-if="unavailable" class="muted">{{ unavailable }}</p></li>
          <li v-else><strong>{{ ui('resolveReason') }}</strong><p>{{ reason(selected.certification?.reason) }}</p><p>{{ ui('resolveHelp') }}</p></li>
          <li><strong>{{ ui('reviewResult') }}</strong><p>{{ ui('reviewHelp') }}</p></li>
        </ol><a-alert v-if="submitError" type="error" :message="submitError" show-icon />
      </section>
      <details class="detail-section"><summary>{{ ui('currentCheck') }}</summary><dl class="check-facts"><template v-for="field in checkFields" :key="field"><dt>{{ tr('check.' + field) }}</dt><dd>{{ selected.certification?.[field] == null ? tr('unknown') : tr(selected.certification[field] ? 'yes' : 'no') }}</dd></template><template v-if="selected.certification?.local_agent_id"><dt>{{ tr('localInstance') }}</dt><dd>{{ selected.certification.local_agent_id }}</dd></template><template v-if="selected.certification?.managed_agent_id"><dt>{{ tr('managedAgent') }}</dt><dd>{{ selected.certification.managed_agent_id }}</dd></template><dt>{{ tr('hostVersion') }}</dt><dd>{{ selected.agent_version || '—' }}</dd><dt>{{ tr('version') }}</dt><dd>{{ selected.certification?.version_no ?? '—' }}</dd><dt>{{ tr('checkedAt') }}</dt><dd>{{ time(selected.certification?.checked_at) }}</dd></dl></details>
      <section v-if="selected.tasks?.length" class="detail-section"><h4>{{ ui('requests') }}</h4><p v-for="task in selected.tasks" :key="task.id"><time>{{ time(task.created_at) }}</time> · {{ ui('taskStatus.' + task.status) }}<span v-if="task.error_code"> · {{ taskError(task.error_code) }}</span><span v-if="task.status === 'succeeded'"> · {{ ui('receiptOnly') }}</span></p></section>
      <footer><a-button :loading="loading" :disabled="loading" @click="load">{{ ui('refreshPlatform') }}</a-button><p class="muted">{{ ui('refreshHelp') }}</p></footer><p class="observation-note"><InfoCircleOutlined /> {{ tr('observation') }}</p>
    </template>
    <a-drawer v-model:open="evidenceOpen" :title="ui('viewEvidence')" width="min(720px, 100vw)" :destroy-on-close="true">
      <a-spin v-if="evidenceLoading" /><a-alert v-if="evidenceError" type="error" :message="ui('evidenceUnavailable')" show-icon />
      <template v-if="evidenceData"><dl class="check-facts"><dt>{{ tr('tool') }}</dt><dd>{{ evidenceData.event.tool || '—' }}</dd><dt>{{ ui('call') }}</dt><dd>{{ evidenceData.event.native_call_id || '—' }}</dd><dt>{{ ui('turnLabel') }}</dt><dd>{{ evidenceData.event.turn_id || '—' }}</dd><dt>{{ ui('nativeEvent') }}</dt><dd>{{ evidenceData.event.hook_event || evidenceData.event.kind }}</dd><template v-if="evidenceData.event.skill_use?.path"><dt>{{ tr('path') }}</dt><dd>{{ evidenceData.event.skill_use.path }}</dd></template></dl><p v-if="!evidenceData.event.contents?.length && !evidenceData.event.behavior?.contents?.length && !evidenceData.event.message?.contents?.length" class="muted">{{ ui('noFragments') }}</p><AidrAuditContent :key="evidenceData.source + evidenceData.record_id" :client-id="clientId" :source="evidenceData.source" :record-id="evidenceData.record_id" :evidence="evidenceData.event" /></template>
    </a-drawer>
  </aside>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { CloseOutlined, InfoCircleOutlined } from '@ant-design/icons-vue'
import products from '../aidr-products.json'
import { can } from '../access'
import { getClientAidrSkillUse, getClientAidrSkillEvidence, requestClientSkillObservation } from '../api'
import { useSkillAuditLabels } from '../utils/skillAudit'
import AidrAuditContent from './AidrAuditContent.vue'
const props = defineProps({ clientId:String, usageId:String })
const emit = defineEmits(['close', 'collection', 'updated'])
const { tr, ui, name, time, phase, tone, outcomeTone, reason, taskError } = useSkillAuditLabels()
const selected = ref(null), loading = ref(false), error = ref(false), historyLoading = ref(false), submitting = ref(false), submitError = ref('')
const evidenceOpen = ref(false), evidenceLoading = ref(false), evidenceError = ref(false), evidenceData = ref(null)
let request = 0, evidenceRequest = 0, timer, requestId = '', disposed = false
const checkFields = ['registered','approved','revoked','content_matches','authorized']
const entryName = computed(() => products.find(p => p.id === (selected.value?.entry || selected.value?.agent))?.name || selected.value?.entry || selected.value?.agent)
const timeline = computed(() => {
  const value = selected.value
  if (!value) return []
  const nodes = (value.evidence || []).map(ref => ({ key:ref.source + ref.id, kind:'evidence', ref, at:ref.at, receivedAt:ref.received_at, title:phase({ stage:ref.stage, skill:value.skill }), color:['denied','failed'].includes(ref.stage) ? 'red' : 'blue' }))
  const observations = new Map()
  if (value.skill.content_digest) observations.set('original', { skill:value.skill, observed_at:value.skill.content_observed_at })
  for (const check of value.checks || []) {
    nodes.push({ key:'check' + check.id, kind:'check', check:check.check, at:check.check.checked_at, title:ui('recordedCheck') + ' · ' + tr(check.check.status), color:tone(check.check.status) === 'green' ? 'green' : 'gray' })
    if (check.observation?.task_id) observations.set(check.observation.task_id, check.observation)
  }
  if (value.latest_observation) observations.set(value.latest_observation.task_id, value.latest_observation)
  for (const [key, observation] of observations) nodes.push({ key:'observation' + key, kind:'observation', observation, at:observation.observed_at, title:ui(key === 'original' ? 'originalObservation' : 'newObservation'), color:'blue' })
  return nodes.sort((a,b) => Date.parse(a.at || a.receivedAt || 0) - Date.parse(b.at || b.receivedAt || 0))
})
const pending = computed(() => ['pending','verified_content'].includes(selected.value?.certification?.status))
const needsContent = computed(() => ['content_digest_missing','content_source_missing','content_source_unreadable','content_source_symlink','content_source_changed','content_file_limit','content_file_size_limit','content_total_size_limit','content_entry_limit','content_check_cancelled'].includes(selected.value?.certification?.reason))
const taskActive = computed(() => selected.value?.tasks?.some(task => ['pending','running'].includes(task.status)))
const unavailable = computed(() => !can('clients:update') ? ui('permission') : selected.value?.observe_unavailable ? reason(selected.value.observe_unavailable) : '')
async function load() {
  const id = ++request; clearTimeout(timer); loading.value = true; error.value = false
  try {
    const data = await getClientAidrSkillUse(props.clientId, props.usageId)
    if (id !== request || disposed) return
    selected.value = data; emit('updated', data)
    if (data.tasks.some(task => ['pending','running'].includes(task.status))) timer = setTimeout(load, 3000)
  } catch { if (id === request && !disposed) error.value = true }
  finally { if (id === request && !disposed) loading.value = false }
}
async function loadHistory() {
  if (historyLoading.value || !selected.value?.checks_more) return
  const id = request; historyLoading.value = true
  try { const data = await getClientAidrSkillUse(props.clientId, props.usageId, { before:selected.value.checks_cursor }); if (id === request && !disposed) selected.value = { ...selected.value, checks:[...selected.value.checks, ...data.checks], checks_more:data.checks_more, checks_cursor:data.checks_cursor } }
  catch { if (id === request && !disposed) error.value = true } finally { historyLoading.value = false }
}
async function recollect() {
  if (submitting.value || unavailable.value || taskActive.value) return
  submitting.value = true; submitError.value = ''; requestId ||= crypto.randomUUID()
  try { await requestClientSkillObservation(props.clientId, props.usageId, requestId); if (disposed) return; requestId = ''; await load() }
  catch (error) { if (!disposed) { submitError.value = reason(error.response?.data?.error_code?.replace(/^aidr\.skill_/, '') || 'observation_failed'); await load() } }
  finally { if (!disposed) submitting.value = false }
}
async function openEvidence(ref) {
  const id = ++evidenceRequest; evidenceOpen.value = true; evidenceLoading.value = true; evidenceError.value = false; evidenceData.value = null
  try { const data = await getClientAidrSkillEvidence(props.clientId, props.usageId, { source:ref.source, record_id:ref.id }); if (id === evidenceRequest && !disposed) evidenceData.value = data }
  catch { if (id === evidenceRequest && !disposed) evidenceError.value = true } finally { if (id === evidenceRequest && !disposed) evidenceLoading.value = false }
}
watch(evidenceOpen, open => { if (!open) { evidenceRequest++; evidenceData.value = null } })
onBeforeUnmount(() => { disposed = true; request++; evidenceRequest++; clearTimeout(timer) })
load()
defineExpose({ refresh:load })
</script>
<style scoped>
.skill-detail { padding:20px 22px; overflow:auto; background:#fff; } header { display:flex; align-items:center; justify-content:space-between; gap:12px; } h3 { font-size:20px; margin:0; overflow-wrap:anywhere; } h4 { margin:0 0 18px; font-size:16px; } p { margin:8px 0; }.muted,time { color:#68798c; font-size:12px; } time { font-variant-numeric:tabular-nums; }.state-pair { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin:20px 0; }.state-pair > div { display:flex; flex-direction:column; align-items:flex-start; gap:8px; }.state-pair > div + div { border-left:1px solid #e5e9ef; padding-left:18px; }.state-pair :deep(.ant-tag) { white-space:normal; }.skill-path,.digest { overflow-wrap:anywhere; font-size:12px; }.skill-path .muted { margin-right:8px; }.detail-section { border-top:1px solid #e5e9ef; padding-top:20px; margin-top:20px; }.detail-section :deep(.ant-timeline-item-content) { overflow-wrap:anywhere; }.detail-section time { display:block; margin-bottom:5px; }.check-facts { display:grid; grid-template-columns:minmax(95px,1fr) minmax(0,1.3fr); gap:9px 14px; font-size:13px; } dt { color:#68798c; } dd { margin:0; overflow-wrap:anywhere; }.pending-steps ol { padding-left:24px; }.pending-steps li { padding:0 0 18px 6px; }.pending-steps li::marker { color:#315fbd; font-weight:600; }.pending-steps p { font-size:12px; color:#68798c; } footer { display:flex; align-items:center; gap:12px; border-top:1px solid #e5e9ef; padding-top:16px; flex-wrap:wrap; margin-top:18px; }.observation-note { padding:10px; background:#f0f5ff; color:#68798c; font-size:12px; }.skill-detail :deep(.ant-btn) { white-space:normal; height:auto; min-height:30px; }
@media(max-width:600px) { .skill-detail { padding:12px; } }
</style>
