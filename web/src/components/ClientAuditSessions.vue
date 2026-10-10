<template>
  <section class="session-audit" :aria-busy="pageLoading">
    <div v-if="pageLoading" class="session-loading-overlay" role="status" aria-live="polite"><a-spin size="large" /><strong>{{ loadingCaption }}</strong><span>{{ t('aidr.sessions.loadingHint') }}</span></div>
    <aside class="session-list">
      <header><h3>{{ t('aidr.sessions.sessions') }}</h3><a-button size="small" :loading="sessionsLoading || turnsLoading || timelineLoading" :disabled="sessionsLoading || turnsLoading || timelineLoading" @click="refresh">{{ t('aidr.sessions.refresh') }}</a-button></header>
      <div class="session-filters">
        <a-select v-if="!fixedAgent" v-model:value="agent" :aria-label="t('aidr.agent')"><a-select-option value="">{{ t('aidr.sessions.allAgents') }}</a-select-option><a-select-option v-for="product in groupProductEntries(products.filter(p => p.collection_visible !== false && (p.logs || p.hooks)))" :key="product.id" :value="product.id">{{ product.name }}</a-select-option></a-select>
        <a-input v-model:value="sessionSearch" :aria-label="t(canRead ? 'aidr.sessions.findQuestion' : 'aidr.sessions.findSession')" :placeholder="t(canRead ? 'aidr.sessions.findQuestion' : 'aidr.sessions.findSession')" :maxlength="256" allow-clear />
      </div>
      <a-alert v-if="sessionsError" type="error" :message="t('aidr.sessions.readFailed')" show-icon><template #action><a-button type="link" :disabled="sessionsLoading" @click="loadSessions(failedSessionAppend, true)">{{ t('aidr.sessions.retry') }}</a-button></template></a-alert>
      <p v-if="!sessionsLoading && !sessionsError && !sessions.items.length" class="muted">{{ t('aidr.sessions.emptySessions') }}</p>
      <select v-if="sessions.items.length" class="mobile-session" :value="selected?.key" :aria-label="t('aidr.sessions.sessions')" @change="selectSession(sessions.items.find(item => item.key === $event.target.value))">
        <option v-for="item in sessions.items" :key="item.key" :value="item.key">{{ sessionTitle(item) }} · {{ shortDate(item.latest_at) }}</option>
      </select>
      <div class="desktop-sessions">
        <button v-for="item in sessions.items" :key="item.key" class="session-choice" type="button" :aria-pressed="selected?.key === item.key" @click="selectSession(item)">
          <span class="session-choice-title"><span>{{ agentName(item.agent) }}</span><code>{{ item.session_id ? '…' + item.session_id.slice(-8) : '#' + item.orphan_id }}</code></span>
          <strong class="session-title">{{ sessionTitle(item) }}</strong>
          <time>{{ t('aidr.sessions.latest') }} · {{ shortDate(item.latest_at) }}</time>
          <span class="session-counts">{{ t('aidr.sessions.counts', { logs: item.log_count, messages: item.message_count || 0, hooks: item.hook_count }) }}</span>
        </button>
      </div>
      <a-button v-if="sessions.has_more" class="more-sessions" :loading="sessionsLoading" :disabled="sessionsLoading" @click="loadSessions(true)">{{ t('aidr.sessions.moreSessions') }}</a-button>
    </aside>
    <main class="session-timeline" :aria-busy="timelineLoading">
      <template v-if="selected">
        <div class="timeline-header">
          <header class="selected-session">
            <h3 :title="sessionTitle(selected)">{{ sessionTitle(selected) }}</h3>
            <span v-if="!sourceCount(selected, 'tools') && sourceCount(selected, 'hooks')" class="session-coverage" :title="t('aidr.sessions.hooksOnlyHelp')">{{ t('aidr.sessions.hooksOnly') }}</span>
            <a-popover :title="t('aidr.sessions.sessionInfo')" :trigger="['click']">
              <template #content><div class="session-info"><code>{{ sessionLabel(selected) }}</code><p>{{ t('aidr.sessions.latest') }} · {{ timestamp(selected.latest_at) }}</p><p>{{ t('aidr.sessions.logHelp') }}</p><p>{{ t('aidr.sessions.hookHelp') }}</p><p v-if="!sourceCount(selected, 'tools') && sourceCount(selected, 'hooks')">{{ t('aidr.sessions.hooksOnlyHelp') }}</p></div></template>
              <button class="session-info-button" type="button" :aria-label="t('aidr.sessions.sessionInfo')"><InfoCircleOutlined /></button>
            </a-popover>
            <span class="session-meta" :title="timestamp(selected.latest_at)">{{ agentName(selected.agent) }} · {{ shortDate(selected.latest_at) }}</span>
          </header>
          <div class="timeline-toolbar">
            <div class="source-tabs" role="group" :aria-label="t('aidr.sessions.activity')">
              <button v-for="value in ['tools', 'hooks']" :key="value" type="button" :aria-pressed="!showSkills && source === value" @click="showSkills = false; source = value">{{ t('aidr.sessions.' + (value === 'tools' ? 'logsTab' : 'hooksTab')) }} <span>{{ sourceCount(countContext(value), value) }}</span></button>
              <button type="button" :aria-pressed="showSkills" @click="showSkills = true">{{ t('aidr.skillUse.title') }}</button>
            </div>
            <div v-if="!showSkills" class="content-mode" role="group" :aria-label="t('aidr.sessions.contentDisplay')"><button v-for="mode in ['rendered', 'source']" :key="mode" type="button" :aria-pressed="contentMode === mode" @click="contentMode = mode">{{ t('aidr.sessions.' + mode) }}</button></div>
            <a-input v-if="!showSkills" v-model:value="search" class="timeline-search" :aria-label="t('aidr.sessions.search')" :placeholder="t('aidr.sessions.searchCompact')" :maxlength="256" allow-clear />
          </div>
        </div>
        <AidrSkillUses v-if="showSkills" :client-id="clientId" :agent="selected.agent" :session-id="selected.session_id" />
        <div v-else class="turn-reading">
          <AidrTurnNavigator :items="sourceTurns" :active="turnKey" :can-read="canRead" :loading="turnsLoading" :error="turnsError" :has-more="turns.has_more" @select="turnKey = $event" @more="loadTurns(turnsFailedAppend || !turnsError)" />
          <div ref="timelinePane" class="timeline-records" tabindex="0" role="region" :aria-label="t('aidr.sessions.timeline')">
            <a-alert v-if="timelineError" type="error" :message="t('aidr.sessions.readFailed')" show-icon><template #action><a-button type="link" :disabled="timelineLoading" @click="loadTimeline(failedAppend)">{{ t('aidr.sessions.retry') }}</a-button></template></a-alert>
            <p v-if="(timelineLoading || turnsLoading) && !timeline.items.length" role="status" class="muted">{{ t('aidr.sessions.loading') }}</p>
            <div :key="timelineIdentity">
            <section v-for="group in timelineGroups" :key="group.key" class="turn-group">
              <header class="question-heading"><strong>{{ group.turn ? turnLabel(group.turn) : t('aidr.sessions.unassignedTurn') }}</strong><time v-if="group.turn">{{ shortDate(group.turn.started_at) }}</time><span v-if="group.turn?.prompt_id" class="muted">{{ t('aidr.detail.prompt') }} · {{ group.turn.prompt_id > 0 ? 'Hook' : t('aidr.sessions.logSource') }}</span></header>
              <div v-if="source === 'hooks' ? hookFields(group.turn).length : group.turn?.log_models?.length" class="turn-context">
                <div v-if="source === 'hooks' && hookFields(group.turn).length" class="turn-context-row">
                  <span class="turn-context-source">{{ t('aidr.sessions.hookMetadata') }}</span>
                  <dl><div v-for="field in hookFields(group.turn)" :key="field.key" :title="field.title"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></div></dl>
                </div>
                <div v-for="report in source === 'tools' ? group.turn?.log_models || [] : []" :key="report.id" class="turn-context-row" :title="logModelTitle(report)">
                  <span class="turn-context-source">{{ t('aidr.sessions.logMetadata') }}</span>
                  <dl><div v-for="field in modelFields.filter(key => report[key])" :key="field"><dt>{{ t('aidr.sessions.' + field) }}</dt><dd>{{ field === 'model' ? modelValue(report[field]) : report[field] }}</dd></div></dl>
                </div>
              </div>
              <div v-if="group.turn?.key !== 'unassigned'" class="question-body">
                <AidrMarkdown :text="questionText(group.turn)" :mode="contentMode" />
                <details v-if="canRead && group.turn?.question?.context_text" class="original-question"><summary>{{ t('aidr.sessions.contextFragment') }}</summary><pre>{{ group.turn.question.context_text }}</pre></details>
                <details v-if="canRead && group.turn?.question?.text !== group.turn?.question?.display_text && group.turn?.question?.text" class="original-question"><summary>{{ t('aidr.sessions.originalQuestion') }}</summary><pre>{{ group.turn.question.text }}</pre></details>
                <p v-for="note in group.turn?.question?.truncations || []" :key="note.part" class="muted">{{ t('aidr.sessions.truncation.' + note.part, note) }}</p>
                <span v-if="group.turn?.question?.truncated && !group.turn.question.truncations?.length" class="muted">{{ t('aidr.detail.partialContent') }}</span>
                <span v-if="group.turn?.question?.redacted" class="muted">{{ t('aidr.detail.redactedContent') }}</span>
                <p v-if="group.turn?.prompt_count > 1" class="muted">{{ t('aidr.sessions.multiplePrompts', { count: group.turn.prompt_count }) }}</p>
              </div>
              <p v-else class="muted">{{ t('aidr.sessions.unassignedTurnHelp') }}</p>
              <AidrTimelineEntry v-for="item in group.items" :key="item.key" :item="item" :client-id="clientId" :content-mode="contentMode" />
            </section>
            </div>
        <div v-if="!turnsLoading && !timelineLoading && !timelineError && !timeline.items.length" class="timeline-empty">
          <h3>{{ t(query ? 'aidr.sessions.noMatches' : turnKey ? 'aidr.sessions.emptyTurn' : source === 'tools' ? 'aidr.sessions.emptyLogs' : 'aidr.sessions.emptyHooks') }}</h3>
          <template v-if="query"><a-button type="link" @click="search = ''">{{ t('aidr.sessions.clearSearch') }}</a-button></template>
          <template v-else-if="turnKey && sourceCount(selected, source)"><p class="muted">{{ t('aidr.sessions.otherTurnsAvailable', { count: sourceCount(selected, source) }) }}</p><a-button type="link" @click="turnKey = ''">{{ t('aidr.sessions.allTurns') }}</a-button></template>
          <template v-else><p class="muted">{{ t('aidr.sessions.emptyHelp') }}</p><a-button type="link" @click="source = source === 'tools' ? 'hooks' : 'tools'">{{ t(source === 'tools' ? 'aidr.sessions.switchHooks' : 'aidr.sessions.switchLogs') }}</a-button><a-button type="link" @click="$emit('collection')">{{ t('aidr.sessions.collection') }}</a-button></template>
        </div>
        <div v-if="timeline.has_more" class="timeline-footer"><a-button :loading="timelineLoading" :disabled="timelineLoading || !!timelineError" @click="loadTimeline(true)">{{ t('aidr.sessions.moreRecords') }}</a-button></div>
        <p v-else-if="timeline.items.length && !timelineError" class="timeline-footer muted">{{ t('aidr.sessions.end') }}</p>
          </div>
        </div>
      </template>
      <div v-else-if="!sessionsLoading" class="timeline-empty"><h3>{{ t('aidr.sessions.emptySessions') }}</h3><p class="muted">{{ t('aidr.sessions.emptySessionHelp') }}</p><a-button type="link" @click="$emit('collection')">{{ t('aidr.sessions.collection') }}</a-button></div>
    </main>
  </section>
</template>

<script setup>
import AidrSkillUses from './AidrSkillUses.vue'
import products from '../aidr-products.json'
import { groupProductEntries } from '../aidr-product-groups'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { InfoCircleOutlined } from '@ant-design/icons-vue'
import { getClientAidrSessions, getClientAidrSessionTimeline, getClientAidrSessionTurns } from '../api'
import { can } from '../access'
import AidrTimelineEntry from './AidrTimelineEntry.vue'
import AidrMarkdown from './AidrMarkdown.vue'
import AidrTurnNavigator from './AidrTurnNavigator.vue'
const modelFields = ['model', 'provider', 'reasoning_effort', 'reasoning_summary']
function modelValue(value) { return value?.toLowerCase() === 'auto' ? 'Auto' : value }
function logModelTitle(report) {
  return [...modelFields.filter(key => report[key]).map(key => `${t('aidr.sessions.' + key)}: ${key === 'model' ? modelValue(report[key]) : report[key]}`), `${report.source} · ${timestamp(report.at)} #${report.id}`].join('\n')
}
function hookFields(turn) {
  const context = turn?.hook_context || { model: turn?.hook_models || [] }
  return ['model', 'cwd', 'workspace_roots'].flatMap(key => {
    const native = context[key] || []
    const session = key !== 'model' && !native.length && turns.value.host_context?.[key]
    const reports = session ? [session] : native
    if (!reports.length) return []
    const label = t('aidr.sessions.' + key)
    return [{ key, label: session ? t('aidr.sessions.sessionContextLabel', { field: label }) : label,
      value: [...new Set(reports.flatMap(report => [].concat(report.value)).map(value => key === 'model' ? modelValue(value) : value))].join(' / '),
      title: reports.map(report => `${timestamp(report.at)} · ${report.hook_event} #${report.id}`).join('\n') }]
  })
}
const props = defineProps({ clientId: { type: String, required: true }, activityRequest: Object, fixedAgent: { type: String, default: '' } })
defineEmits(['collection'])
const source = defineModel('source', { type: String, default: 'tools' })
const contentMode = ref('rendered')
const { t, locale } = useI18n()
const empty = () => ({ items: [], has_more: false, next_cursor: '' })
const sessions = ref(empty()), timeline = ref(empty()), selected = ref(null)
const timelinePane = ref(null)
const showSkills = ref(false)
const turns = ref(empty()), turnKey = ref('')
const turnsLoading = ref(false), turnsError = ref(false), turnsFailedAppend = ref(false)
const canRead = computed(() => can('clients:read-audit-content'))
const turnContext = computed(() => JSON.stringify([props.clientId, selected.value?.key, canRead.value]))
const resolvedTurnContext = ref('')
const turnsReady = computed(() => resolvedTurnContext.value === turnContext.value)
const sourceTurns = computed(() => turns.value.items.filter(turn => sourceCount(turn, source.value)))
const activeTurn = computed(() => turns.value.items.find(item => item.key === turnKey.value))
const countContext = value => activeTurn.value && sourceCount(activeTurn.value, value) ? activeTurn.value : selected.value
const turnLabel = turn => turn.key === 'unassigned' ? t('aidr.sessions.unassignedTurn') : sourceTurns.value.some(item => item.key === turn.key) ? t('aidr.sessions.round', { n: sourceTurns.value.filter(item => item.key !== 'unassigned').findIndex(item => item.key === turn.key) + 1 }) : t('aidr.sessions.turnId', { id: turn.key.slice(5, 13) })
const questionText = turn => !canRead.value ? t('aidr.sessions.questionRestricted') : turn?.question?.display_text || t('aidr.sessions.questionMissing')
const timelineGroups = computed(() => {
  const groups = []
  for (const item of timeline.value.items) {
    let group = groups.at(-1)
    if (!group || group.turn.key !== item.turn_key) {
      group = { key: item.key, turn: turns.value.items.find(turn => turn.key === item.turn_key) || { key: item.turn_key }, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  if (!groups.length && turnKey.value && activeTurn.value) groups.push({ key: activeTurn.value.key, turn: activeTurn.value, items: [] })
  return groups
})
const sessionsLoading = ref(false), timelineLoading = ref(false), sessionsError = ref(false), timelineError = ref(false)
const sessionSearch = ref(''), sessionQuery = ref(''), agent = ref(''), search = ref(''), query = ref('')
const failedAppend = ref(false)
const failedSessionAppend = ref(false)
const pageLoading = computed(() => (sessionsLoading.value && !failedSessionAppend.value) || turnsLoading.value || (timelineLoading.value && !failedAppend.value))
const loadingCaption = computed(() => t(sessionsLoading.value ? 'aidr.sessions.loadingSessions' : turnsLoading.value ? 'aidr.sessions.loadingTurns' : 'aidr.sessions.loadingTimeline'))
let sessionRequest = 0, timelineRequest = 0, turnRequest = 0, sessionTimer, searchTimer
const timelineIdentity = computed(() => JSON.stringify([props.clientId, selected.value?.key, source.value, query.value, turnKey.value, turnsReady.value]))
const agentName = value => products.find(p => p.id === value)?.name || value
const sessionLabel = item => item.session_id || t('aidr.sessions.unassigned', { id: item.orphan_id })
const sessionTitle = item => (canRead.value && item.question_preview) || (item.session_id ? `${agentName(item.agent)} · ${shortDate(item.latest_at)} · …${item.session_id.slice(-8)}` : sessionLabel(item))
function timestamp(value) { return value ? new Date(value).toLocaleString(locale.value) : '—' }
const shortDateFormatter = computed(() => new Intl.DateTimeFormat(locale.value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }))
function shortDate(value) { return value ? shortDateFormatter.value.format(new Date(value)) : '—' }
function sourceCount(item, value) { return value === 'tools' ? (item?.log_count || 0) + (item?.message_count || 0) : item?.hook_count || 0 }
function selectSession(value, keepSource = false) {
  if (!value || value.key === selected.value?.key) return
  clearTimeout(searchTimer); search.value = ''; query.value = ''
  const other = source.value === 'tools' ? 'hooks' : 'tools'
  if (!keepSource && !sourceCount(value, source.value) && sourceCount(value, other)) source.value = other
  selected.value = value
}
async function loadTurns(append = false) {
  if (!selected.value || (append && turnsLoading.value)) return
  const request = ++turnRequest, item = selected.value, context = turnContext.value
  turnsLoading.value = true; turnsError.value = false; turnsFailedAppend.value = append
  try {
    const result = await getClientAidrSessionTurns(props.clientId, { agent: item.agent, session_id: item.session_id, orphan_id: item.orphan_id, cursor: append ? turns.value.next_cursor : '', include_questions: canRead.value })
    if (request !== turnRequest) return
    const firstLoad = !turns.value.items.length
    turns.value = { ...result, items: append ? [...turns.value.items, ...result.items] : result.items }
    if (firstLoad) {
      // A partial turn page cannot identify the latest turn in the session.
      const candidates = result.items.filter(turn => turn.key !== 'unassigned' && sourceCount(turn, source.value))
      turnKey.value = result.has_more ? '' : candidates.reduce((latest, turn) => !latest || turn.latest_at > latest.latest_at ? turn : latest, null)?.key || ''
    } else if (turnKey.value && !turns.value.items.some(turn => turn.key === turnKey.value)) turnKey.value = ''
  } catch { if (request === turnRequest) turnsError.value = true }
  finally { if (request === turnRequest) { turnsLoading.value = false; resolvedTurnContext.value = context } }
}
async function loadSessions(append = false, preserve = false) {
  if (append && sessionsLoading.value) return
  const request = ++sessionRequest, clientId = props.clientId
  sessionsLoading.value = true; sessionsError.value = false; failedSessionAppend.value = append
  if (!append && !preserve) { sessions.value = empty(); selected.value = null }
  try {
    const result = await getClientAidrSessions(clientId, { agent: agent.value, keyword: sessionQuery.value, cursor: append ? sessions.value.next_cursor : '', limit: 20, include_questions: canRead.value })
    if (request !== sessionRequest) return
    sessions.value = { ...result, items: append ? [...sessions.value.items, ...result.items] : result.items }
    const current = sessions.value.items.find(item => item.key === selected.value?.key)
    if (current) selected.value = current
    else if (result.items.length) selectSession(result.items[0], props.activityRequest?.clientId === clientId)
    else selected.value = null
  } catch { if (request === sessionRequest) sessionsError.value = true }
  finally { if (request === sessionRequest) sessionsLoading.value = false }
}
async function loadTimeline(append = false) {
  if (!selected.value || !turnsReady.value || (append && timelineLoading.value)) return
  const request = ++timelineRequest, selectedSession = selected.value
  timelineLoading.value = true; timelineError.value = false; failedAppend.value = append
  if (!append) timeline.value = empty()
  try {
    const result = await getClientAidrSessionTimeline(props.clientId, {
      source: source.value === 'tools' ? 'logs' : 'hooks', agent: selectedSession.agent, session_id: selectedSession.session_id,
      orphan_id: selectedSession.orphan_id, keyword: query.value, order: 'oldest', turn_key: turnKey.value,
      cursor: append ? timeline.value.next_cursor : '', limit: 30,
    })
    if (request !== timelineRequest) return
    timeline.value = { ...result, items: append ? [...timeline.value.items, ...result.items] : result.items }
  } catch { if (request === timelineRequest) timelineError.value = true }
  finally { if (request === timelineRequest) timelineLoading.value = false }
}
function refresh() {
  if (sessionsLoading.value || timelineLoading.value || turnsLoading.value) return
  resolvedTurnContext.value = ''
  loadSessions(false, true)
  loadTurns()
}
watch(source, () => {
  if (turnKey.value && !sourceTurns.value.some(turn => turn.key === turnKey.value)) turnKey.value = ''
}, { flush: 'sync' })
watch(timelineIdentity, () => { timelinePane.value?.scrollTo({ top: 0 }); timelineRequest++; timelineLoading.value = false; timeline.value = empty(); timelineError.value = false; if (selected.value) loadTimeline() })
watch(turnContext, () => { turnRequest++; resolvedTurnContext.value = ''; turns.value = empty(); turnsLoading.value = false; turnsError.value = false; turnKey.value = ''; if (selected.value) loadTurns() })
watch(canRead, () => { sessions.value = empty(); selected.value = null; loadSessions() })
watch([sessionQuery, agent], () => loadSessions())
watch(sessionSearch, value => { clearTimeout(sessionTimer); sessionTimer = setTimeout(() => { sessionQuery.value = value.trim() }, 250) })
watch(search, value => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { query.value = value.trim() }, 250) })
watch([() => props.clientId, () => props.activityRequest, () => props.fixedAgent], () => {
  sessionRequest++; timelineRequest++; clearTimeout(sessionTimer); clearTimeout(searchTimer)
  sessions.value = empty(); timeline.value = empty(); selected.value = null
  sessionsLoading.value = false; timelineLoading.value = false; sessionsError.value = false; timelineError.value = false
  const requestedAgent = props.fixedAgent || (props.activityRequest?.clientId === props.clientId ? props.activityRequest.agent : '')
  const requestedSession = props.activityRequest?.clientId === props.clientId ? props.activityRequest.sessionId || '' : ''
  const filterChanged = sessionQuery.value !== requestedSession || agent.value !== requestedAgent
  sessionSearch.value = requestedSession; sessionQuery.value = requestedSession; agent.value = requestedAgent; search.value = ''; query.value = ''; showSkills.value = false
  if (!filterChanged) loadSessions()
}, { immediate: true })
onBeforeUnmount(() => { sessionRequest++; timelineRequest++; turnRequest++; clearTimeout(sessionTimer); clearTimeout(searchTimer) })
</script>

<style scoped>
.session-loading-overlay { position: absolute; inset: 0; z-index: 3; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; background: rgba(255, 255, 255, .91); pointer-events: none; padding: 20px; text-align: center; }
.session-loading-overlay strong { color: #334155; font-size: 15px; font-weight: 500; }
.session-loading-overlay > span { color: #718096; font-size: 12px; }
@media (prefers-reduced-motion: reduce) { .session-loading-overlay :deep(.ant-spin-dot), .session-loading-overlay :deep(.ant-spin-dot-item) { animation: none; } }
.session-audit { position: relative; display: grid; grid-template-columns: 210px minmax(0, 1fr); border: 1px solid #e4e8ef; border-radius: 8px; background: white; flex: 1; min-height: 0; overflow: hidden; }
.session-list { display: flex; flex-direction: column; padding: 10px 8px; border-right: 1px solid #e4e8ef; min-width: 0; min-height: 0; overflow: hidden; }
.session-list > * { flex-shrink: 0; }
.session-list header, .selected-session { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.session-list header { padding: 0 4px 8px; }
h3 { margin: 0; font-size: 16px; }
.session-filters { display: flex; flex-direction: column; gap: 6px; margin: 0 4px 8px; }
.session-choice { display: block; width: 100%; text-align: left; padding: 9px; border: 1px solid transparent; border-radius: 6px; background: transparent; cursor: pointer; margin-bottom: 4px; }
.session-choice[aria-pressed=true] { background: #eef4ff; border-color: #245fe5; }
.session-choice:hover { background: #f3f6fc; }
.session-choice-title { display: flex; justify-content: space-between; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.session-choice time { color: #667085; font-size: 12px; }
.session-choice code { display: block; color: #667085; font-size: 12px; overflow-wrap: anywhere; }
.session-title { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; margin: 6px 0; }
.selected-session { flex-wrap: nowrap; gap: 6px; }
.selected-session h3 { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; min-width: 0; font-size: 14px; }
.session-meta { margin-left: auto; flex-shrink: 0; font-size: 12px; color: #667085; font-variant-numeric: tabular-nums; }
.timeline-header { flex-shrink: 0; padding: 10px 14px 0; border-bottom: 1px solid #e4e8ef; }
.timeline-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.session-info-button { display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; width: 28px; height: 28px; padding: 0; border: 0; background: none; color: #667085; cursor: pointer; border-radius: 4px; }
.session-info-button:hover { background: #eef4ff; color: #245fe5; }
button:focus-visible, .timeline-records:focus-visible { outline: 2px solid #245fe5; outline-offset: -2px; }
.session-info { max-width: min(380px, 75vw); overflow-wrap: anywhere; font-size: 13px; }
.session-info p { margin: 4px 0; }
.session-coverage { flex-shrink: 0; border-radius: 4px; padding: 2px 6px; background: #f2f4f7; color: #667085; font-size: 11px; line-height: 18px; cursor: default; }
.timeline-search { width: 210px; min-width: 150px; max-width: 100%; margin-left: auto; margin-bottom: 5px; }
.content-mode { display: flex; flex-shrink: 0; gap: 2px; margin: 0 8px 5px auto; padding: 2px; border: 1px solid #e4e8ef; border-radius: 5px; }
.content-mode button { border: 0; border-radius: 3px; padding: 3px 7px; background: none; color: #667085; font-size: 12px; cursor: pointer; }
.content-mode button[aria-pressed="true"] { background: #eef4ff; color: #245fe5; }
.turn-reading { display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 8px; flex: 1; min-height: 0; overflow: hidden; padding: 10px 0 0 8px; }
.timeline-records { min-width: 0; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 0 14px 12px 0; }
.question-heading { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; font-size: 13px; }
.question-heading time { color: #667085; }
.turn-context { display: grid; gap: 6px; margin: -2px 0 12px; font-size: 12px; }
.turn-context-row { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.turn-context-source { color: #475467; font-weight: 600; flex: 0 0 68px; }
.turn-context dl { display: flex; flex-wrap: wrap; gap: 4px 16px; min-width: 0; margin: 0; }
.turn-context dl > div { display: flex; gap: 6px; min-width: 0; max-width: 100%; }
.turn-context dt { color: #667085; flex-shrink: 0; }
.turn-context dd { margin: 0; color: #344054; overflow-wrap: anywhere; min-width: 0; }
.question-body { background: #eef4ff; border-left: 3px solid #245fe5; padding: 9px 12px; margin-bottom: 14px; border-radius: 5px; overflow-wrap: anywhere; }
.question-body p { white-space: pre-wrap; margin: 0; }
.original-question { margin-top: 8px; font-size: 12px; }
.original-question pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; }
.question-body .muted { display: inline-block; margin: 6px 10px 0 0; }
.turn-group + .turn-group { border-top: 1px solid #e4e8ef; padding-top: 24px; margin-top: 24px; }
.session-counts { display: block; margin-top: 8px; color: #667085; font-size: 12px; }
.session-list > .desktop-sessions { flex: 1 1 auto; min-height: 80px; overflow-y: auto; overscroll-behavior: contain; }
.session-timeline { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; }
.muted { color: #667085; font-size: 13px; }
summary { cursor: pointer; width: fit-content; }
.source-tabs { display: flex; gap: 16px; flex-shrink: 0; }
.source-tabs button { padding: 8px 0 9px; border: 0; border-bottom: 2px solid transparent; background: none; cursor: pointer; color: #667085; font-size: 13px; }
.source-tabs button[aria-pressed=true] { color: #245fe5; border-bottom-color: #245fe5; font-weight: 600; }
.source-tabs span { background: #f3f5f8; padding: 1px 6px; border-radius: 4px; font-size: 12px; margin-left: 5px; }
select { border: 1px solid #d9d9d9; border-radius: 6px; background: white; padding: 6px 10px; color: #344054; }
.timeline-footer { text-align: center; margin-top: 16px; }
.timeline-empty { text-align: center; padding: 24px 12px; }
.timeline-empty p { margin-top: 12px; }
.mobile-session { display: none; }
.more-sessions { margin: 10px 8px; max-width: calc(100% - 16px); height: auto; white-space: normal; }
@media(max-width: 900px) {
  .session-audit { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
  .session-list { border-right: 0; border-bottom: 1px solid #e4e8ef; padding: 6px 10px; }
  .session-list header { padding-bottom: 4px; }
  .desktop-sessions { display: none; }
  .mobile-session { display: block; width: 100%; max-width: 100%; }
  .session-filters { flex-direction: row; margin: 0 0 4px; }
  .session-filters > * { min-width: 0; }
  .session-filters > :first-child { width: 130px; flex-shrink: 0; }
  .turn-reading { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); padding: 6px 10px 0; gap: 4px; }
  .timeline-records { padding-right: 4px; }
  .more-sessions { margin: 4px 0 0; }
}
@media(max-width: 560px) {
  .timeline-header { padding: 6px 10px 0; }
  .session-meta { display: none; }
  .timeline-search { width: 100%; margin: 0 0 6px; }
  .timeline-toolbar { gap: 4px; margin-top: 2px; }
  .source-tabs { gap: 12px; }
}
@media(pointer: coarse) { button, select, summary { min-height: 44px; } select { font-size: 16px; } }
</style>
