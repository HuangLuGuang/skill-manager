<template>
  <article class="timeline-entry" :class="{ failed, lifecycle: !isTool, message: !!item.message, finalReply: item.message?.message.phase === 'final' }">
    <time :datetime="item.at">{{ timestamp(item.at) }}</time>
    <div class="entry-body">
      <div class="entry-card">
        <header><strong>{{ title }}</strong><span v-if="status" class="entry-status" :class="{ success }">{{ status }}</span></header>
        <div v-if="blocked" class="control-decision">
          <span>{{ controlReason }}</span>
          <span v-if="control.rule_id">{{ t(control.rule_id === 'default' ? 'aidr.sessions.controlDefault' : 'aidr.sessions.controlRule') }}<code v-if="control.rule_id !== 'default'"> {{ control.rule_id }}</code></span>
        </div>
        <p v-if="event.skill_use" class="skill-evidence"><a-tag color="blue">{{ t('aidr.skillUse.' + event.skill_use.behavior) }}</a-tag>{{ event.skill_use.name || event.skill_use.path }}</p>
        <p v-if="!isTool && !item.message" class="event-code">{{ event.hook_event }}</p>
        <AidrAuditContent v-if="item.message" :content-mode="contentMode" :show-heading="false" :client-id="clientId" source="log" :record-id="item.message.logical_event_id" :evidence="item.message" />
        <AidrAuditContent v-for="record in promptRecords" :key="record.id" :content-mode="contentMode" :client-id="clientId" source="hook" :record-id="record.id" :evidence="record.record.event" />
        <code v-if="preview && !expanded" class="entry-preview">{{ preview }}</code>
        <p v-if="allActions.length > 1" class="muted">{{ t('aidr.sessions.moreActions', { count: allActions.length - 1 }) }}</p>
        <p v-if="exitCode != null && exitCode !== 0 && !showLogExitCode" class="exit-code">{{ item.operation ? t('aidr.commandExitCode', { code: exitCode }) : `${t('aidr.exitCode')}: ${exitCode}` }}</p>
        <p v-if="item.operation?.log_elapsed_ms != null" class="muted">{{ t('aidr.sessions.elapsed') }}: {{ item.operation.log_elapsed_ms }} ms</p>
        <p v-if="records.length > 1" class="muted">{{ pairedStages ? t('aidr.sessions.pairedStages') : t('aidr.sessions.paired', { count: records.length }) }}</p>
        <p v-if="item.association === 'cross_turn_native_identity_matched'" class="muted">{{ t('aidr.hooks.events.relatedCodes.cross_turn_native_identity_matched') }}</p>
        <p v-if="item.execution_evidence" class="muted">{{ t('aidr.sessions.endHookMissing') }} · {{ t('aidr.sessions.executionSources.' + (item.execution_evidence.source === 'codex.item_completed' ? 'codex' : 'log')) }} · {{ t('aidr.detail.recordId') }}: {{ item.execution_evidence.record_id }}<span v-if="item.execution_evidence.relation === 'inferred'"> · {{ t('aidr.sessions.executionInferred') }}</span></p>
        <p v-if="Number.isInteger(item.execution_evidence?.exit_code)" class="muted">{{ t('aidr.commandExitCode', { code: item.execution_evidence.exit_code }) }}</p>
        <p v-if="resultOnly" class="muted">{{ t('aidr.sessions.resultOnly') }}</p>
        <details v-if="!item.message" :open="expanded" @toggle="expanded = $event.target.open">
          <summary>{{ t('aidr.sessions.details') }}</summary>
          <div v-if="expanded" class="entry-detail">
            <p v-if="!isTool">{{ t('aidr.hooks.events.meanings.' + (meanings[event.hook_event] || 'other')) }}</p>
            <AidrAuditActions :actions="allActions" :tool="event.tool || item.operation?.tool" :body-omitted="event.behavior?.body_omitted" :body-captured="commandCaptured" />
            <p v-if="event.behavior?.truncated || result?.behavior?.truncated" class="muted">{{ t('aidr.sessions.truncated') }}</p>
            <template v-if="item.operation">
              <AidrAuditContent v-for="part in [item.operation.call, item.operation.result].filter(Boolean)" :key="part.logical_event_id" :content-mode="contentMode" :client-id="clientId" source="log" :record-id="part.logical_event_id" :evidence="part" />
            </template>
            <section v-for="record in records" :key="record.id" class="hook-part">
              <strong>{{ record.record.event.hook_event }}</strong>
              <p v-if="record.record.event.turn_id" class="muted">{{ t('aidr.turn') }}: <code>{{ record.record.event.turn_id }}</code></p>
              <p class="muted">{{ t('aidr.sessions.received') }}: {{ timestamp(record.record.received_at) }}</p>
              <template v-if="record.record.event.context">
                <p v-if="record.record.event.context.model">{{ t('aidr.sessions.model') }}: <code>{{ record.record.event.context.model }}</code></p>
                <p v-if="record.record.event.context.cwd">{{ t(record.record.event.context.cwd_source === 'agent_log' ? 'aidr.sessions.cwdFromLog' : 'aidr.sessions.cwd') }}: <code>{{ record.record.event.context.cwd }}</code></p>
                <p v-for="root in record.record.event.context.workspace_roots || []" :key="root">{{ t('aidr.sessions.workspace_roots') }}: <code>{{ root }}</code></p>
                <p v-if="record.record.event.context.redacted || record.record.event.context.truncated" class="muted">{{ t('aidr.sessions.hostContextProcessed') }}</p>
              </template>
              <AidrAuditContent v-if="record.record.event.kind !== 'turn.submit'" :content-mode="contentMode" :client-id="clientId" source="hook" :record-id="record.id" :evidence="record.record.event" />
            </section>
            <details class="record-info"><summary>{{ t('aidr.sessions.recordInfo') }}</summary>
              <p v-if="event.turn_id">{{ t('aidr.turn') }}: <code>{{ event.turn_id }}</code></p>
              <p v-if="event.native_call_id">{{ t('aidr.call') }}: <code>{{ event.native_call_id }}</code></p>
              <p v-if="event.native_agent_id">{{ t('aidr.detail.subagent') }}: <code>{{ event.native_agent_id }}</code></p>
              <p v-for="record in records" :key="record.id">{{ record.record.event.hook_event }} · {{ t('aidr.detail.recordId') }}: {{ record.id }}</p>
              <p v-if="item.operation">{{ t('aidr.detail.recordId') }}: {{ item.operation.id }}</p>
              <p v-if="item.operation?.association === 'native_call_same_source_instance'">{{ t('aidr.sessions.recoveredAssociation') }}</p>
              <p v-if="result?.behavior?.result_basis?.length">{{ t('aidr.resultBasis') }}: {{ result.behavior.result_basis.map(value => t('aidr.bases.' + value)).join(' · ') }}</p>
            </details>
          </div>
        </details>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AidrAuditActions from './AidrAuditActions.vue'
import AidrAuditContent from './AidrAuditContent.vue'
const props = defineProps({ contentMode: { type: String, default: 'source' }, item: { type: Object, required: true }, clientId: { type: String, required: true } })
const { t, locale } = useI18n()
const expanded = defineModel('expanded', { type: Boolean, default: false })
const records = computed(() => props.item.records || [])
const pairedStages = computed(() => records.value.length === 2 && records.value.filter(r => r.record.event.kind === 'tool.pre').length === 1 && records.value.filter(r => ['tool.post', 'tool.failure'].includes(r.record.event.kind)).length === 1)
const promptRecords = computed(() => records.value.filter(record => record.record.event.kind === 'turn.submit'))
const event = computed(() => props.item.message || props.item.operation?.call || props.item.operation?.result || records.value.find(r => r.record.event.kind === 'tool.pre')?.record.event || records.value[0]?.record.event || {})
const result = computed(() => props.item.operation?.result || records.value.find(r => ['tool.post', 'tool.failure'].includes(r.record.event.kind))?.record.event)
const isTool = computed(() => !!props.item.operation || ['tool.pre', 'tool.post', 'tool.failure'].includes(event.value.kind))
const resultOnly = computed(() => !props.item.operation && !!result.value && !records.value.some(r => r.record.event.kind === 'tool.pre'))
const allActions = computed(() => event.value.behavior?.actions || [])
const commandCaptured = computed(() => event.value.behavior?.contents?.some(item => item.kind === 'command_body'))
const preview = computed(() => {
  const commands = event.value.behavior?.contents?.filter(item => item.kind === 'command_body') || []
  if (commands.length) return t(commands.every(item => item.command_summary) ? 'aidr.commandParsing.summaryPreview' : 'aidr.content.commandPreview')
  return allActions.value[0]?.targets?.[0]?.value || ''
})
const exitCode = computed(() => result.value?.behavior?.exit_code)
const control = computed(() => event.value.control_decision)
const blocked = computed(() => control.value?.decision === 'deny')
const controlReason = computed(() => {
  const key = { aidr_hook_rule_deny: 'rule', aidr_hook_policy_missing: 'policyMissing', aidr_hook_approval_unsupported: 'approvalUnsupported', aidr_hook_audit_disabled_requires_evidence: 'evidenceRequired' }[control.value?.code]
  return key ? t('aidr.sessions.controlReasons.' + key) : control.value?.code
})
const showLogExitCode = computed(() => Number.isInteger(exitCode.value) && ['reported_success', 'reported_error'].includes(props.item.operation?.status))
const failed = computed(() => blocked.value || props.item.execution_evidence?.status === 'failed' || props.item.operation?.status === 'reported_error' || result.value?.behavior?.status === 'reported_error' || result.value?.kind === 'tool.failure' || event.value.kind === 'permission.denied')
const success = computed(() => !blocked.value && (props.item.operation ? props.item.operation.status === 'reported_success' : result.value?.behavior?.status === 'reported_success'))
const meanings = { SessionStart: 'sessionStart', SessionEnd: 'sessionEnd', UserPromptSubmit: 'promptSubmit', PreToolUse: 'preTool', PostToolUse: 'postTool', PostToolUseFailure: 'toolFailure', PermissionRequest: 'permissionRequest', PermissionDenied: 'permissionDenied', Stop: 'stop', Interrupt: 'interrupt', Notification: 'notification', SubagentStart: 'subagentStart', SubagentStop: 'subagentStop', PreCompact: 'preCompact', PostCompact: 'postCompact', TaskCompleted: 'taskCompleted', TeammateIdle: 'teammateIdle' }
const title = computed(() => props.item.message ? t('aidr.sessions.messages.' + (props.item.message.message.role === 'user' ? 'input' : props.item.message.message.phase)) : isTool.value ? props.item.operation?.tool || event.value.tool || t(props.item.operation?.status === 'missing_call' ? 'aidr.sessions.toolReturn' : 'aidr.unknown') : t('aidr.sessions.events.' + (meanings[event.value.hook_event] || 'other')))
const status = computed(() => {
  if (blocked.value) return t('aidr.sessions.controlBlocked')
  if (showLogExitCode.value) return t('aidr.commandExitCode', { code: exitCode.value })
  if (props.item.operation) return t(props.item.operation.status === 'unknown' ? 'aidr.sessions.unknownResult' : 'aidr.results.' + props.item.operation.status)
  if (!isTool.value) return ''
  if (!result.value && props.item.execution_evidence) return t('aidr.sessions.executionStates.' + props.item.execution_evidence.status)
  if (!result.value) return t('aidr.sessions.pendingResult')
  const key = { reported_success: 'hookSuccess', reported_error: 'hookFailure', reported_complete: 'hookComplete', reported_cancelled: 'hookCancelled' }[result.value.behavior?.status]
  if (result.value.kind === 'tool.failure') return t('aidr.sessions.hookFailure')
  return key ? t('aidr.sessions.' + key) : ''
})
function timestamp(value) {
  if (!value) return '—'
  const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`)
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(locale.value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date)
}
</script>

<style scoped>
.timeline-entry { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 15px; }
time { color: #667085; font-size: 12px; padding-top: 12px; font-variant-numeric: tabular-nums; }
.entry-body { position: relative; border-left: 1px solid #e4e8ef; padding: 0 0 18px 18px; min-width: 0; }
.entry-body::before { content: ''; position: absolute; width: 7px; height: 7px; border-radius: 50%; background: #8b96a6; left: -4px; top: 17px; box-shadow: 0 0 0 4px white; }
.timeline-entry:last-child .entry-body { border-left-color: transparent; }
.entry-card { border: 1px solid #e4e8ef; border-radius: 7px; padding: 12px 14px; overflow-wrap: anywhere; }
.message .entry-card { background: #f8fafc; padding: 10px 12px; }
.message .entry-body { padding-bottom: 12px; }
.message header { line-height: 20px; }
.message header > strong { font-size: 13px; color: #475467; }
.message :deep(.audit-content) { margin: 6px 0 0; }
.message :deep(.audit-content-fragment + .audit-content-fragment) { margin-top: 8px; }
.message :deep(.audit-content-note:last-child) { margin-bottom: 0; }
.finalReply .entry-card { border-left: 3px solid #245fe5; background: #f3f7ff; padding-left: 12px; }
.finalReply header > strong { color: #245fe5; }
.lifecycle:not(.message) .entry-card { border: 0; padding: 10px 0; }
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.entry-status { color: #667085; margin-left: auto; font-size: 12px; }
.entry-status.success { color: #237a47; }
.failed .entry-card { background: #fff8f7; border-color: #f2d3d0; }
.failed .entry-body::before { background: #c63b3b; }
.failed .entry-status, .exit-code { color: #b93636; }
.control-decision { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 8px; color: #b93636; font-size: 12px; }
.entry-preview { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; white-space: pre-wrap; margin: 9px 0; }
.muted, .event-code { color: #667085; font-size: 12px; margin: 6px 0; }
summary { cursor: pointer; color: #245fe5; font-size: 13px; margin-top: 8px; width: fit-content; }
.entry-detail { border-top: 1px solid #e4e8ef; margin-top: 12px; padding-top: 8px; }
.hook-part + .hook-part { margin-top: 16px; }
.record-info summary { color: #667085; }
.record-info p { margin-top: 8px; }
@media(max-width: 560px) { .timeline-entry { grid-template-columns: 1fr; gap: 3px; } time { padding: 0 0 0 19px; } .entry-status { margin-left: 0; } }
</style>
