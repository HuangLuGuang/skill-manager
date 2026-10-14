<template>
      <article v-if="record" class="event-record-detail">
        <div class="event-detail-heading"><h2>{{ view.title }}</h2><span :class="['event-state', view.tone]">{{ view.state }}</span></div>
        <p><strong>{{ record.skill_name || '—' }}</strong> / {{ agentLabel(record.agent_type) }}<span v-if="clientName"> · {{ clientName }}</span></p>
        <section><h3>{{ ui('what') }}</h3><p v-if="record.presentation?.category === 'audit'">{{ view.stage }}</p><dl class="event-facts"><div><dt>{{ view.timeLabel }}</dt><dd>{{ time(view.occurred_at) }}</dd></div><div><dt>{{ ui('source') }}</dt><dd>{{ view.category }}</dd></div><div v-if="record.presentation?.category === 'audit'"><dt>{{ t('auditTrail.certification') }}</dt><dd>{{ ui('condition_' + record.presentation.condition, {}, 'condition_unknown') }}</dd></div></dl><p v-if="view.count" class="muted">{{ view.count }}</p></section>
        <section><h3>{{ ui('why') }}</h3><p>{{ view.reason }}</p></section>
        <section><h3>{{ ui('handled') }}</h3><p>{{ view.state }}<template v-if="!['recorded', 'succeeded', 'failed'].includes(record.presentation?.state)"> · {{ view.action }}</template></p><dl class="event-facts"><div v-if="record.presentation?.category === 'audit'"><dt>{{ ui('fileAction') }}</dt><dd>{{ ui('unknown') }}</dd></div><div v-if="view.checked_at"><dt>{{ ui('checked') }}</dt><dd>{{ time(view.checked_at) }}</dd></div></dl><p v-if="view.retained">{{ ui('retained') }}</p><p v-if="view.error">{{ ui('error') }}: {{ view.error }}</p></section>
        <section><h3>{{ ui('evidence') }}</h3><a-timeline v-if="view.timeline.length"><a-timeline-item v-for="(node, index) in view.timeline" :key="index"><time>{{ time(node.at) }}</time><strong>{{ phase(node) }}</strong><small>{{ ui('source_' + node.source) }}<template v-if="node.arrival"> · {{ ui('arrival') }}</template></small></a-timeline-item><a-timeline-item v-if="view.checked_at" color="gray"><time>{{ time(view.checked_at) }}</time><strong>{{ ui('checked') }}</strong><small>{{ ui('reason_' + view.current_reason, {}, 'reason_unknown') }}</small></a-timeline-item></a-timeline><p v-else class="muted">{{ ui('noEvidence') }}</p></section>
        <details><summary>{{ ui('technical') }}</summary><dl class="event-technical"><div v-for="field in technical" :key="field.key"><dt>{{ ui(field.key) }}</dt><dd>{{ field.value || ui('unknown') }}</dd></div></dl></details>
        <p v-if="record.presentation?.category === 'audit'" class="event-boundary muted">{{ ui('boundary') }}</p>
      </article>
      <footer v-if="showBack || view?.usage_id || (record?.details?.skill_id && can('skills:view'))"><a-space wrap><a-button v-if="record?.details?.skill_id && can('skills:view')" @click="openSkill">{{ ui('viewSkill') }}</a-button><a-button v-if="view?.usage_id" type="primary" @click="evidenceId = view.usage_id">{{ ui('viewEvidence') }}</a-button><a-button v-if="showBack" @click="$emit('close')">{{ ui('back') }}</a-button></a-space></footer>

    <a-drawer :open="!!evidenceId" :width="680" :styles="{ wrapper: { maxWidth: '100vw' } }" :title="ui('evidence')" destroy-on-close @close="evidenceId = ''"><AidrSkillUseDetail v-if="evidenceId" :client-id="clientId" :usage-id="evidenceId" @collection="$emit('collection')" @close="evidenceId = ''" /></a-drawer>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { can } from '../access'
import AidrSkillUseDetail from './AidrSkillUseDetail.vue'
import '../../../client/desktop/src/event-records.js'
const props = defineProps({ record:Object, clientId:String, clientName:String, agentLabel:{ type:Function, required:true }, showBack:{ type:Boolean, default:true } })
defineEmits(['close', 'collection'])
const { t, te, locale } = useI18n(), router = useRouter()
const ui = (key, args = {}, fallback = 'unknown') => t('clientEvents.' + (te('clientEvents.' + key) ? key : fallback), args)
const view = computed(() => globalThis.clientEventRecords.describe(props.record, ui))
const evidenceId = ref('')
const time = value => value ? new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(String(value)) ? value : value + 'Z').toLocaleString(locale.value, { hour12:false, timeZone:'Asia/Shanghai' }) : '—'
const technical = computed(() => [{ key:'path', value:view.value.path }, { key:'session', value:view.value.session_id }, { key:'native', value:view.value.native_call_id }, { key:'code', value:props.record.event_type }, { key:'created', value:time(props.record.created_at) }])
const phase = node => ui('stage_' + (node.stage === 'host_confirmed' ? view.value.behavior === 'invocation' ? 'loaded' : 'read' : node.stage), {}, 'stage_unknown')
function openSkill() { router.push('/skills/' + encodeURIComponent(props.record.details.skill_id)) }
watch(() => props.record.id, () => { evidenceId.value = '' })
</script>
<style scoped>
footer { display:flex; justify-content:flex-end; padding:16px 0; border-top:1px solid #e8edf2; }
.muted, small, dt { color:#697586; } small { display:block; font-size:12px; line-height:1.6; margin-top:5px; }
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
