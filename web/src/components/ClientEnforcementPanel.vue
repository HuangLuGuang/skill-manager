<template>
  <section class="enforcement-panel" :class="{ 'system-event-view': view === 'events', 'control-view': view !== 'events' }">
    <template v-if="view === 'control'">
      <ClientSystemCollection :client-id="clientId" />
      <details @toggle="advancedOpen = $event.target.open"><summary>{{ t('systemSelection.advancedRules') }}</summary><ClientEnforcementPanel v-if="advancedOpen" :client-id="clientId" view="advanced" /></details>
    </template>
    <template v-if="view === 'advanced'">
    <ClientProtectionStatus :client-id="clientId" channel="system" />
    <p class="control-intro">{{ t('aidr.enforcement.policyIntro') }}</p>
    <a-alert v-if="error" type="error" :message="t('aidr.enforcement.failed')" :description="errorText" />
    <div class="controls">
      <a-tag :color="['active', 'collecting'].includes(status.state) ? 'green' : 'orange'">{{ t(`aidr.enforcement.states.${status.state || 'unknown'}`) }}</a-tag>
      <span>{{ t('aidr.enforcement.target') }}: {{ status.target_revision || '0' }}</span>
      <span>{{ t('aidr.enforcement.applied') }}: {{ status.reported_revision || t('aidr.enforcement.unknown') }}</span>
      <a-button :loading="loading" @click="refresh({ reloadDraft: true })">{{ t('aidr.enforcement.refresh') }}</a-button>
    </div>
    <a-alert v-if="['failed', 'degraded', 'stale'].includes(status.state)" type="warning" show-icon :message="setupNextStep" />
    <details v-if="status.health" class="diagnostics"><summary>{{ t('aidr.enforcement.diagnostics') }}</summary><p>{{ t('aidr.enforcement.diagnostic') }}: <code>{{ status.health.reason_code }}</code></p><p>{{ t('aidr.enforcement.evidence') }}</p></details>
    <a-alert v-if="platformSupport !== 'macos_endpoint_security'" type="warning" show-icon
      :message="t(`aidr.enforcement.setup.platforms.${platformSupport}`)" :description="t('aidr.enforcement.setup.supportBoundary')" />
    <details class="setup-guide">
      <summary>{{ t('aidr.enforcement.setup.title') }}</summary>
      <p>{{ t('aidr.enforcement.setup.onDevice') }}</p><p>{{ t('aidr.enforcement.setup.supportBoundary') }}</p>
      <ol v-if="platformSupport === 'macos_endpoint_security'">
        <li><strong>{{ t('aidr.enforcement.setup.checkTitle') }}</strong><p>{{ t('aidr.enforcement.setup.checkNote') }}</p>
        </li>
        <li><strong>{{ t('aidr.enforcement.setup.installTitle') }}</strong><p>{{ t('aidr.enforcement.setup.installNote') }}</p>
        </li>
        <li><strong>{{ t('aidr.enforcement.setup.authorizeTitle') }}</strong><p>{{ t('aidr.enforcement.setup.authorizeNote') }}</p>
          <p>{{ t('aidr.enforcement.setup.collectionNote') }}</p>
        </li>
        <li><strong>{{ t('aidr.enforcement.setup.verifyTitle') }}</strong><p>{{ setupNextStep }}</p>
          <div class="controls"><a-button :loading="loading" @click="refresh">{{ t('aidr.enforcement.setup.retryStatus') }}</a-button>
          </div>
        </li>
      </ol>
      <p v-else>{{ t('aidr.enforcement.setup.unsupportedNext') }}</p>
    </details>
    </template>
    <details v-if="view === 'advanced'" open>
      <summary>{{ t('aidr.enforcement.config') }}</summary>
      <p>{{ t('aidr.enforcement.runtimeHint') }}</p>
      <a-form layout="vertical" :disabled="!canPublish || saving">
        <a-form-item :label="t('aidr.enforcement.roots')" :extra="t('aidr.enforcement.rootsHelp')"><a-textarea v-model:value="roots" :rows="3" :maxlength="32768" :placeholder="t('aidr.enforcement.rootsExample')" /></a-form-item>
        <a-form-item :label="t('aidr.enforcement.lifetime')" :extra="t('aidr.enforcement.lifetimeHelp')"><a-input-number v-model:value="hours" :min="1" :max="720" /></a-form-item>
        <details class="advanced-control"><summary>{{ t('aidr.enforcement.advancedControl') }} · {{ draft.rules.length }}</summary>
        <p>{{ t('aidr.enforcement.controlHelp') }}</p><p>{{ t('aidr.enforcement.publishHint') }}</p>
        <div class="controls">
          <a-form-item :label="t('aidr.enforcement.unknownAction')"><a-select v-model:value="draft.unknown_actor_action" :options="decisionOptions" /></a-form-item>
          <a-form-item :label="t('aidr.enforcement.expiredAction')"><a-select v-model:value="draft.expired_action" :options="decisionOptions" /></a-form-item>
        </div>
        <h4>{{ t('aidr.enforcement.rules') }}</h4>
        <div v-for="(rule, index) in draft.rules" :key="index" class="rule">
          <a-input v-model:value="rule.id" :aria-label="t('aidr.enforcement.rule')" :placeholder="t('aidr.enforcement.rule')" :maxlength="64" />
          <a-input v-model:value="rule.path" :aria-label="t('aidr.enforcement.path')" :placeholder="t('aidr.enforcement.path')" :maxlength="1023" />
          <a-select v-model:value="rule.actor" :aria-label="t('aidr.enforcement.actor')" :options="actorOptions" />
          <a-select v-model:value="rule.decision" :aria-label="t('aidr.enforcement.decision')" :options="decisionOptions" />
          <a-button @click="draft.rules.splice(index, 1)">{{ t('aidr.enforcement.remove') }}</a-button>
        </div>
        <div class="controls">
          <a-button :disabled="draft.rules.length >= 128" @click="draft.rules.push({ id: '', path: '', actor: 'agent', decision: 'deny' })">{{ t('aidr.enforcement.add') }}</a-button>
        </div>
        <AidrRulePreview :client-id="clientId" channel="system" :draft="draft" />
        </details>
        <div class="controls">
          <a-button type="primary" :loading="saving" :disabled="saving || !canPublish" @click="publish(false)">{{ t('aidr.enforcement.publish') }}</a-button>
        </div>
        <details><summary>{{ t('aidr.enforcement.historyActions') }}</summary>
        <div class="controls">
          <a-select v-model:value="historyRevision" :aria-label="t('aidr.enforcement.history')" :placeholder="t('aidr.enforcement.history')" :options="history.map(row => ({ value: row.revision, label: row.revision }))" />
          <a-button :disabled="!historyRevision" @click="loadHistorical">{{ t('aidr.enforcement.restore') }}</a-button>
          <a-popconfirm :title="t('aidr.enforcement.revokeConfirm')" @confirm="publish(true)"><a-button danger :loading="saving" :disabled="saving || !canPublish || !draft.rules.length">{{ t('aidr.enforcement.revoke') }}</a-button></a-popconfirm>
        </div>
        </details>
      </a-form>
    </details>
    <template v-if="view === 'events'">
      <header class="events-header">
        <div class="events-heading"><h3>{{ tr('title') }}</h3><span class="collection-indicator" :class="{ good: !error && ['active', 'collecting'].includes(status.state) }"><span aria-hidden="true" class="status-dot"></span>{{ error ? tr('statusUnavailable') : t(`aidr.enforcement.states.${status.state || 'unknown'}`) }}</span></div>
        <div class="events-header-actions"><a-button @click="infoOpen = true"><InfoCircleOutlined /> {{ tr('collectionDetails') }}</a-button><a-button :loading="loading && !hasLoaded" :disabled="loading" @click="refresh({ reloadAgents: true })"><ReloadOutlined /> {{ t('aidr.enforcement.refresh') }}</a-button></div>
      </header>
      <a-alert v-if="error" class="events-alert" type="error" show-icon :message="t('aidr.enforcement.failed')" :description="errorText" />
      <div v-else-if="['failed', 'degraded', 'stale', 'stopped'].includes(status.state)" class="events-notice"><InfoCircleOutlined /><span>{{ tr('historyAvailable') }}</span><a-button type="link" size="small" @click="infoOpen = true">{{ tr('checkStatus') }}</a-button></div>
      <div class="events-filters">
        <a-select v-if="!fixedRoot" v-model:value="eventAgent" class="event-agent-filter" :aria-label="tr('agentFilter')" :options="agentOptions" @change="resetEvents"><template #option="{ value, label }"><div class="agent-filter-option"><strong>{{ label }}</strong><small v-if="value">{{ value }}</small></div></template></a-select>
        <nav class="event-categories" :aria-label="t('aidr.enforcement.kind')"><button v-for="category in eventCategories" :key="category.value" :aria-pressed="eventKind === category.value" :class="{ selected: eventKind === category.value }" @click="setEventKind(category.value)"><component :is="category.icon" aria-hidden="true" />{{ tr(category.label) }}</button></nav>
        <a-select class="extra-event-types" :value="extraKind" :aria-label="tr('moreTypes')" :placeholder="tr('moreTypes')" :options="extraKindOptions" @change="setEventKind" />
        <a-input v-model:value="eventSearch" class="event-search" allow-clear :aria-label="tr('search')" :placeholder="tr('search')"><template #prefix><SearchOutlined /></template></a-input>
        <a-checkbox v-model:checked="includeProbes" @change="resetEvents">{{ t('aidr.enforcement.includeProbes') }}</a-checkbox>
      </div>
      <div v-if="eventKind === 'network'" class="network-note"><GlobalOutlined /><span>{{ tr('networkHint') }}</span><a-button type="link" size="small" @click="infoOpen = true">{{ tr('coverage') }}</a-button></div>
      <div ref="eventList" class="system-event-list" role="region" tabindex="0" :aria-label="tr('list')" :aria-busy="loading">
        <div v-if="loading && !events.items" class="event-empty" role="status"><a-spin /><p>{{ tr('loading') }}</p></div>
        <div v-else-if="!visibleEventRows.length" class="event-empty"><SearchOutlined v-if="eventSearch" /><FileTextOutlined v-else /><h4>{{ tr(eventSearch ? 'noMatches' : 'empty') }}</h4><p>{{ tr(eventSearch ? 'searchHint' : 'emptyHint') }}</p><a-button v-if="eventSearch" @click="eventSearch = ''">{{ tr('clearSearch') }}</a-button><a-button v-else @click="emit('collection')">{{ tr('checkCollection') }}</a-button></div>
        <article v-for="row in visibleEventRows" :key="row.id" class="system-event-row">
          <button class="event-open" :aria-label="`${eventActivity(row.record)} · ${time(row.record.time_ns)} · ${tr('open')}`" @click="openEvent(row)">
            <span class="event-type-icon" :class="row.record.kind"><component :is="eventIcon(row.record)" aria-hidden="true" /></span>
            <span class="event-summary"><span class="event-title"><strong>{{ eventActivity(row.record) }}</strong><span v-if="row.record.root_path" class="agent-label">{{ rootLabel(row.record.root_path) }}</span><span v-if="row.record.activity_origin === 'client_probe'" class="probe-label">{{ t('aidr.enforcement.clientProbe') }}</span><span v-if="row.repeat_count > 1" class="repeat-label">{{ t(row.record.kind === 'network' ? 'aidr.enforcement.snapshotCount' : 'aidr.enforcement.repeated', { count: row.repeat_count }) }}</span></span><code v-if="operationText(row.record)" class="event-operation">{{ operationText(row.record) }}</code><span class="event-process"><template v-if="['health', 'policy'].includes(row.record.kind)">{{ t('aidr.enforcement.executor') }}</template><template v-else><span>{{ programLabel(row.record) }}</span><span>PID {{ row.record.process?.pid || '—' }}</span><span>{{ attribution(row.record) }}</span></template><span v-if="row.record.argv_truncated || row.record.paths_truncated">{{ t('aidr.enforcement.contentTruncated') }}</span></span></span>
            <span class="event-trailing"><time :title="time(row.record.time_ns)">{{ shortEventTime(row.record.time_ns) }}</time><span v-if="eventOutcome(row.record)" class="event-outcome" :class="outcomeTone(row.record)">{{ eventOutcome(row.record) }}</span><small v-if="row.repeat_count > 1">{{ tr('since', { time: shortEventTime(row.start_time_ns) }) }}</small></span><RightOutlined class="event-chevron" aria-hidden="true" />
          </button>
          <div v-if="canTerminate && status.state === 'active' && row.record.kind === 'process'" class="event-response"><a-popconfirm v-if="!terminationReason(row)" :title="t('aidr.enforcement.terminateConfirm')" @confirm="terminate(row)"><a-button size="small" danger :loading="terminating" :disabled="terminating">{{ t('aidr.enforcement.terminate') }}</a-button></a-popconfirm><a-tooltip v-else :title="t(`aidr.enforcement.blocked.${terminationReason(row)}`)"><a-button size="small" disabled>{{ t('aidr.enforcement.terminate') }}</a-button></a-tooltip></div>
        </article>
      </div>
      <footer class="events-footer"><span>{{ tr('pageCount', { shown: visibleEventRows.length, total: events.items?.length || 0 }) }}<span v-if="eventSearch"> · {{ tr('pageSearch') }}</span></span><div><a-button size="small" :disabled="loading || !before" @click="changePage(0)">{{ t('aidr.enforcement.recent') }}</a-button><a-button size="small" :disabled="loading || !events.has_more" @click="changePage(events.next_before)">{{ t('aidr.enforcement.earlier') }}</a-button></div></footer>
      <a-modal v-model:open="infoOpen" :title="tr('collectionDetails')" :footer="null" width="min(680px, 94vw)" :body-style="{ maxHeight: '72vh', overflowY: 'auto' }">
        <p>{{ t('aidr.enforcement.eventsIntro') }}</p>
        <dl class="collection-details"><div><dt>{{ tr('status') }}</dt><dd>{{ error ? tr('statusUnavailable') : t(`aidr.enforcement.states.${status.state || 'unknown'}`) }}</dd></div><div><dt>{{ tr('lastReport') }}</dt><dd>{{ status.last_received_at ? new Date(status.last_received_at).toLocaleString(locale) : t('aidr.enforcement.unknown') }}</dd></div><div><dt>{{ t('aidr.enforcement.target') }}</dt><dd>{{ status.target_revision || '0' }}</dd></div><div><dt>{{ t('aidr.enforcement.applied') }}</dt><dd>{{ status.reported_revision || t('aidr.enforcement.unknown') }}</dd></div></dl>
        <a-alert v-if="!['active', 'collecting'].includes(status.state)" type="info" show-icon :message="setupNextStep" />
        <a-alert v-if="status.health && status.health.detail_schema !== 1" type="info" show-icon :message="t('aidr.enforcement.upgradeCollector')" />
        <h4 class="collection-detail-heading">{{ t('aidr.enforcement.coverageTitle', { count: status.configured_roots?.length || 0 }) }}</h4><p>{{ t('aidr.enforcement.coverageHelp') }}</p><code v-for="path in status.configured_roots || []" :key="path" class="coverage-path">{{ path }}</code>
        <h4 class="collection-detail-heading">{{ t('aidr.enforcement.network.title') }}</h4><p>{{ t(`aidr.enforcement.network.health.${networkHealthState}`) }}</p><p>{{ t('aidr.enforcement.network.boundary') }}</p>
        <details class="setup-guide"><summary>{{ t('aidr.enforcement.setup.title') }}</summary><p>{{ t('aidr.enforcement.setup.onDevice') }}</p><p>{{ t('aidr.enforcement.setup.supportBoundary') }}</p><ol v-if="platformSupport === 'macos_endpoint_security'"><li v-for="step in ['check', 'install', 'authorize']" :key="step"><strong>{{ t(`aidr.enforcement.setup.${step}Title`) }}</strong><p>{{ t(`aidr.enforcement.setup.${step}Note`) }}</p></li></ol><p v-else>{{ t('aidr.enforcement.setup.unsupportedNext') }}</p><p>{{ t('aidr.enforcement.setup.collectionNote') }}</p></details>
        <details><summary>{{ t('aidr.enforcement.diagnostics') }}</summary><p>{{ t('aidr.enforcement.evidence') }}</p><pre class="evidence">{{ JSON.stringify(status, null, 2) }}</pre></details>
        <a-button @click="infoOpen = false; emit('collection')">{{ tr('checkCollection') }}</a-button>
      </a-modal>
    </template>
    <details v-if="view === 'advanced'"><summary>{{ t('aidr.enforcement.commands') }}</summary><div v-for="row in responses" :key="row.id"><code>{{ row.id }}</code> · {{ t(`aidr.enforcement.results.${row.display_state || row.state}`) }} <a-button size="small" @click="selected = row; detailOpen = true">{{ t('aidr.enforcement.detail') }}</a-button></div></details>
    <a-modal v-model:open="detailOpen" :title="selected?.record ? eventActivity(selected.record) : t('aidr.enforcement.detail')" :footer="null" width="min(1000px, 94vw)" :body-style="{ maxHeight: '72vh', overflowY: 'auto' }">
      <template v-if="selected?.record">
        <div class="event-detail-heading"><p class="detail-meta">{{ time(selected.record.time_ns) }}<template v-if="selected.record.process?.pid"> · PID {{ selected.record.process.pid }}</template></p><span v-if="eventOutcome(selected.record)" class="event-outcome" :class="outcomeTone(selected.record)">{{ eventOutcome(selected.record) }}</span></div>
        <a-tag v-if="selected.record.activity_origin === 'client_probe'">{{ t('aidr.enforcement.clientProbe') }}</a-tag>
        <template v-if="['process', 'file', 'network', 'authorization', 'response'].includes(selected.record.kind)">
        <template v-if="selected.record.network">
          <details v-if="selected.snapshots?.length > 1"><summary>{{ t('aidr.enforcement.network.observations', { count: selected.snapshots.length }) }}</summary><ol><li v-for="snapshot in selected.snapshots" :key="snapshot.id"><a-button type="link" @click="openEvent(snapshot)">{{ time(snapshot.record.time_ns) }} · {{ t(`aidr.enforcement.network.states.${snapshot.record.network.state}`) }} · #{{ snapshot.record.sequence }}</a-button></li></ol></details>
          <p class="detail-meta">{{ tr('networkHint') }}</p>
          <dl class="network-details"><div><dt>{{ t('aidr.enforcement.network.local') }}</dt><dd>{{ endpoint(selected.record.network.local_ip, selected.record.network.local_port) }}</dd></div><div><dt>{{ t('aidr.enforcement.network.remote') }}</dt><dd>{{ endpoint(selected.record.network.remote_ip, selected.record.network.remote_port) }}</dd></div><div><dt>{{ t('aidr.enforcement.network.protocol') }}</dt><dd>{{ selected.record.network.protocol.toUpperCase() }}</dd></div><div><dt>{{ t('aidr.enforcement.network.state') }}</dt><dd>{{ t(`aidr.enforcement.network.states.${selected.record.network.state}`) }}</dd></div><div><dt>{{ t('aidr.enforcement.network.direction') }}</dt><dd>{{ t('aidr.enforcement.unknown') }}</dd></div></dl>
        </template>
        <template v-if="!selected.record.network">
        <h4>{{ t(selected.record.kind === 'file' ? 'aidr.enforcement.fileChange' : selected.record.kind === 'authorization' ? 'aidr.enforcement.resource' : selected.record.argv?.length ? 'aidr.enforcement.commandLine' : 'aidr.enforcement.executable') }}</h4>
        <pre class="operation-detail">{{ operationText(selected.record) || t('aidr.enforcement.noCommand') }}</pre>
        </template>
        <template v-if="['file', 'network', 'authorization'].includes(selected.record.kind) && selected.record.argv?.length"><h4>{{ t('aidr.enforcement.commandLine') }}</h4><pre class="operation-detail">{{ commandText(selected.record.argv) }}</pre></template>
        <p v-if="selected.record.argv_truncated || selected.record.paths_truncated">{{ t('aidr.enforcement.contentTruncated') }}</p>
        <dl class="collection-details event-attribution"><div><dt>{{ tr('agent') }}</dt><dd>{{ selected.record.root_path ? rootLabel(selected.record.root_path) : t('aidr.enforcement.unknown') }} · {{ attribution(selected.record) }}</dd></div><div v-if="selected.record.executable"><dt>{{ t('aidr.enforcement.executable') }}</dt><dd><code>{{ selected.record.executable }}</code></dd></div><div v-if="selected.record.cwd"><dt>{{ t('aidr.enforcement.cwd') }}</dt><dd><code>{{ selected.record.cwd }}</code></dd></div><div v-if="selected.record.rule_id"><dt>{{ t('aidr.enforcement.rule') }}</dt><dd>{{ selected.record.rule_id }}</dd></div></dl>
        <h4 v-if="exitRecord && selected.record.kind !== 'process'">{{ tr('processExit') }}</h4>
        <p v-if="exitRecord?.exit_code != null">{{ t('aidr.enforcement.exitCode', { code: exitRecord.exit_code }) }}</p>
        <p v-if="exitRecord?.exit_signal != null">{{ t('aidr.enforcement.exitSignal', { signal: exitRecord.exit_signal }) }}</p>
        <p v-if="exitRecord?.duration_ms">{{ t('aidr.enforcement.duration', { seconds: (Number(exitRecord.duration_ms) / 1000).toFixed(2) }) }}</p>
        <details><summary>{{ t('aidr.enforcement.processChain') }}</summary>
          <p v-if="selected.record.root">{{ selected.record.root_path || t('aidr.enforcement.rootPid') }} · PID {{ selected.record.root.pid }}</p>
          <p v-if="selected.record.parent_pid">↳ {{ t('aidr.enforcement.parentPid') }} {{ selected.record.parent_pid }}</p>
          <p>↳ {{ selected.record.executable || selected.record.path }} · PID {{ selected.record.process.pid }}</p>
        </details>
        <a-spin :spinning="contextLoading">
          <a-alert v-if="contextError" type="warning" :message="t('aidr.enforcement.contextFailed')" />
          <template v-if="contextEvents.length">
            <h4>{{ t('aidr.enforcement.processTimeline') }}</h4>
            <p v-if="contextTruncated">{{ t('aidr.enforcement.contextTruncated') }}</p>
            <ol class="process-timeline"><li v-for="item in contextEvents" :key="item.id">
              <span>{{ time(item.record.time_ns) }} · {{ eventActivity(item.record) }}</span>
              <code v-if="['file', 'network'].includes(item.record.kind) || item.record.transition === 'exec'">{{ operationText(item.record) }}</code>
              <span v-if="item.record.exit_code != null">{{ t('aidr.enforcement.exitCode', { code: item.record.exit_code }) }}</span>
              <span v-if="item.record.exit_signal != null">{{ t('aidr.enforcement.exitSignal', { signal: item.record.exit_signal }) }}</span>
            </li></ol>
          </template>
        </a-spin>
        </template>
        <template v-else><p>{{ eventReason(selected.record) }}</p><p>{{ t('aidr.enforcement.applied') }}: {{ selected.record.revision }}</p><p v-if="Number(selected.record.gaps)">{{ t('aidr.enforcement.gaps', { count: selected.record.gaps }) }}</p></template>
      </template>
      <details><summary>{{ t('aidr.enforcement.diagnostics') }}</summary><p>{{ t('aidr.enforcement.evidence') }}</p><pre class="evidence">{{ JSON.stringify(selected, null, 2) }}</pre></details>
    </a-modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CodeOutlined, FileTextOutlined, GlobalOutlined, HeartOutlined, InfoCircleOutlined, ReloadOutlined, RightOutlined, SearchOutlined, SafetyOutlined, SettingOutlined, UnorderedListOutlined } from '@ant-design/icons-vue'
import ClientSystemCollection from './ClientSystemCollection.vue'
import ClientProtectionStatus from './ClientProtectionStatus.vue'
import AidrRulePreview from './AidrRulePreview.vue'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { getEnforcement, publishEnforcement, terminateEnforcement } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, view: { type: String, default: 'control' }, fixedRoot: { type: String, default: '' } })
const emit = defineEmits(['collection'])
const advancedOpen = ref(false)
const { t, te, locale } = useI18n()
const tr = (key, params = {}) => t(`aidr.enforcement.eventsView.${key}`, params)
const eventSearch = ref(''), infoOpen = ref(false), eventList = ref(null), hasLoaded = ref(false)
const eventAgent = ref(''), agentRoots = ref([]), agentsLoaded = ref(false)
const agentOptions = computed(() => [{ value: '', label: tr('allAgents') }, ...[...new Set([...agentRoots.value, ...(status.value.configured_roots || [])])].map(path => ({ value: path, label: rootLabel(path) }))])
const status = ref({}), events = ref({}), history = ref([]), responses = ref([]), before = ref(0)
const networkHealthState = computed(() => !error.value && ['collecting', 'active', 'degraded'].includes(status.value.state) ? status.value.health?.network_health?.state || 'unreported' : status.value.state === 'stopped' ? 'stopped' : 'unreported')
const eventKind = ref('activity'), includeProbes = ref(false)
const contextEvents = ref([]), contextLoading = ref(false), contextError = ref(false), contextTruncated = ref(false)
let contextRequest = 0
const exitRecord = computed(() => contextEvents.value.findLast(item => item.record.transition === 'exit')?.record || (selected.value?.record?.transition === 'exit' ? selected.value.record : null))
const loading = ref(false), saving = ref(false), terminating = ref(false), error = ref('')
const roots = ref(''), hours = ref(24), draft = ref({ rules: [], unknown_actor_action: 'allow', expired_action: 'allow' })
const historyRevision = ref(), selected = ref(), detailOpen = ref(false)
let baseRevision = '0', baseConfigurationRevision = '0', generation = 0, initialized = false, timer, refreshQueued = false, reloadDraftQueued = false
const requests = new Map()
const platformSupport = computed(() => ['macos_endpoint_security', 'unsupported_platform', 'unreported_platform'].includes(status.value.platform_support) ? status.value.platform_support : 'unreported_platform')
const errorText = computed(() => error.value === 'aidr.enforcement_revision_conflict' ? t('aidr.enforcement.revisionConflict') : t('aidr.enforcement.requestFailure', { code: error.value }))
const canPublish = computed(() => !error.value && !loading.value && status.value.can_edit && can('clients:update'))
const canTerminate = computed(() => status.value.can_edit && can('clients:execute'))
const decisionOptions = computed(() => ['allow', 'deny'].map(value => ({ value, label: t(`aidr.enforcement.${value}`) })))
const actorOptions = computed(() => ['agent', 'all'].map(value => ({ value, label: t(`aidr.enforcement.${value}`) })))
const eventCategories = [{ value: 'activity', label: 'activity', icon: UnorderedListOutlined }, { value: 'process', label: 'process', icon: CodeOutlined }, { value: 'file', label: 'file', icon: FileTextOutlined }, { value: 'network', label: 'network', icon: GlobalOutlined }]
const extraKindOptions = computed(() => [{ value: '', label: t('aidr.enforcement.allKinds') }, ...['authorization', 'policy', 'response', 'health'].map(value => ({ value, label: t(`aidr.enforcement.kinds.${value}`) }))])
const extraKind = computed(() => eventCategories.some(item => item.value === eventKind.value) ? undefined : eventKind.value)
function resetEvents() { before.value = 0; events.value = {}; eventList.value?.scrollTo({ top: 0 }); refresh() }
function setEventKind(value) { if (value !== eventKind.value) { eventKind.value = value; resetEvents() } }
function changePage(value) { before.value = value; events.value = {}; eventList.value?.scrollTo({ top: 0 }); refresh() }
const setupNextStep = computed(() => {
  const reason = status.value.health?.reason_code
  const key = reason === 'aidr_enforcement_es_unavailable' ? 'authorization'
    : ['failed', 'stopped'].includes(status.value.state) ? 'restart'
      : status.value.state === 'degraded' ? 'degraded'
        : status.value.state === 'stale' ? 'stale'
          : ['active', 'collecting'].includes(status.value.state) ? 'reported' : 'unreported'
  return t(`aidr.enforcement.setup.next.${key}`)
})

const eventRows = computed(() => {
  const grouped = [], sockets = new Map()
  for (const item of events.value.items || []) {
    const record = item.record || {}
    if (record.network) {
      const key = `${record.boot_id}:${record.monitor_id}:${record.process.pid}:${record.process.pidversion}:${record.process.start_us}:${record.network.observation_id}`
      const existing = sockets.get(key)
      if (existing) { existing.snapshots.push(item); existing.repeat_count += 1; existing.start_time_ns = record.time_ns; continue }
      const row = { ...item, snapshots: [item], repeat_count: 1, start_time_ns: record.time_ns }
      sockets.set(key, row); grouped.push(row); continue
    }
    const previous = grouped[grouped.length - 1]
    const sameHealth = record.kind === 'health' && previous?.record?.kind === 'health'
      && ['monitor_id', 'boot_id', 'revision', 'reason_code', 'gaps'].every(key => record[key] === previous.record[key])
      && record.network_health?.state === previous.record.network_health?.state
      && record.network_health?.source === previous.record.network_health?.source
      && JSON.stringify(record.process) === JSON.stringify(previous.record.process)
      && JSON.stringify(record.root) === JSON.stringify(previous.record.root)
    if (sameHealth) {
      previous.repeat_count += 1
      previous.start_time_ns = record.time_ns
    } else grouped.push({ ...item, repeat_count: 1, start_time_ns: record.time_ns })
  }
  return grouped
})
const visibleEventRows = computed(() => {
  const query = eventSearch.value.trim().toLowerCase()
  return query ? eventRows.value.filter(({ record }) => [eventActivity(record), operationText(record), eventOutcome(record), record.executable, record.root_path, record.root_path && rootLabel(record.root_path), record.process?.pid, record.cwd, record.rule_id].some(value => String(value ?? '').toLowerCase().includes(query))) : eventRows.value
})
const eventDateFormatter = computed(() => new Intl.DateTimeFormat(locale.value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))
function shortEventTime(ns) { return eventDateFormatter.value.format(new Date(Number(BigInt(ns) / 1000000n))) }
function eventIcon(record) { return ({ process: CodeOutlined, file: FileTextOutlined, network: GlobalOutlined, health: HeartOutlined, policy: SettingOutlined, authorization: SafetyOutlined, response: SafetyOutlined })[record.kind] || InfoCircleOutlined }
function eventOutcome(record) {
  if (record.exit_code != null) return t('aidr.enforcement.exitCode', { code: record.exit_code })
  if (record.exit_signal != null) return t('aidr.enforcement.exitSignal', { signal: record.exit_signal })
  if (record.network) return t(`aidr.enforcement.network.states.${record.network.state}`)
  if (record.kind === 'file') return t('aidr.enforcement.fileObserved')
  if (['authorization', 'response'].includes(record.kind)) return `${t(`aidr.enforcement.results.${record.decision}`)} · ${t(`aidr.enforcement.results.${record.result}`)}`
  if (Number(record.gaps) > 0) return t('aidr.enforcement.gaps', { count: record.gaps })
  return ''
}
function outcomeTone(record) {
  if (record.decision === 'deny' || record.result === 'failed' || (record.exit_code != null && Number(record.exit_code) !== 0) || record.exit_signal != null || Number(record.gaps) > 0) return 'attention'
  return record.exit_code != null && Number(record.exit_code) === 0 ? 'success' : ''
}
function time(ns) { return new Date(Number(BigInt(ns) / 1000000n)).toLocaleString(locale.value) }
function eventActivity(record) {
  const reason = `aidr.enforcement.reasons.${record.reason_code}`
  if (te(reason)) return t(reason)
  const transition = `aidr.enforcement.transitions.${record.transition}`
  if (record.transition && te(transition)) return t(transition)
  return t(`aidr.enforcement.kinds.${record.kind}`)
}
function eventReason(record) {
  const key = `aidr.enforcement.reasons.${record.reason_code}`
  return te(key) ? t(key) : t('aidr.enforcement.technicalReason', { code: record.reason_code })
}
function attribution(record) { return t(`aidr.enforcement.attribution.${record.relation || 'unknown'}`) }
function basename(path) { return (path || '').split('/').pop() }
function programLabel(record) {
  const path = record.executable || record.path || ''
  return path.includes('/claude/versions/') ? 'claude' : basename(path) || t('aidr.enforcement.unknown')
}
function rootLabel(path) {
  const appName = path.match(/(?:^|\/)([^/]+)\.app\/Contents\//)?.[1]
  if (appName) return appName === 'Claude' ? 'Claude Code' : appName
  if (basename(path) === 'claude' || path.includes('/claude/versions/')) return 'Claude Code'
  if (basename(path) === 'codex') return 'Codex'
  return basename(path)
}
function commandText(argv) { return argv.map(arg => /^[a-zA-Z0-9_./:=+-]+$/.test(arg) ? arg : "'" + arg.replaceAll("'", "'\\''") + "'").join(' ') }
function endpoint(ip, port) { return `${ip.includes(':') ? `[${ip}]` : ip}:${port}` }
function operationText(record) {
  if (record.network) return `${endpoint(record.network.remote_ip, record.network.remote_port)} · ${record.network.protocol.toUpperCase()}`
  if (['file', 'authorization'].includes(record.kind)) return record.destination_path ? `${record.path} → ${record.destination_path}` : record.path
  if (record.argv?.length) return commandText(record.argv)
  return record.path || record.executable
}
async function openEvent(row) {
  selected.value = { id: row.id, record: row.record, snapshots: row.snapshots, repeated_records: row.repeat_count,
    time_range: row.repeat_count > 1 ? { from_ns: row.start_time_ns, to_ns: row.record.time_ns } : null }
  detailOpen.value = true
  const request = ++contextRequest, g = generation
  contextEvents.value = []; contextError.value = false; contextTruncated.value = false; contextLoading.value = false
  if (!['process', 'file', 'network', 'authorization', 'response'].includes(row.record.kind)) return
  contextLoading.value = true
  try {
    const result = await getEnforcement(props.clientId, `records/${row.id}/context`)
    if (g === generation && request === contextRequest) { contextEvents.value = result.items; contextTruncated.value = result.truncated }
  } catch { if (g === generation && request === contextRequest) contextError.value = true }
  finally { if (g === generation && request === contextRequest) contextLoading.value = false }
}
function loadDraft(policy) {
  roots.value = (policy?.agent_executables || []).join('\n')
  const lifetime = Number(policy?.expires_at) - Number(policy?.issued_at)
  if (Number.isFinite(lifetime) && lifetime >= 60) hours.value = Math.min(720, Math.max(1, lifetime / 3600))
  draft.value = { rules: JSON.parse(JSON.stringify(policy?.rules || [])), unknown_actor_action: policy?.unknown_actor_action || 'allow', expired_action: policy?.expired_action || 'allow' }
}
function loadHistorical() { const row = history.value.find(item => item.revision === historyRevision.value); if (row) loadDraft(row.policy) }
function failure(err) { error.value = err.response?.data?.error_code || err.response?.data?.detail?.error_code || 'aidr_enforcement_request_failed' }
async function refresh(options = {}) {
  if (props.view === 'control') return
  if (loading.value) { refreshQueued = true; reloadDraftQueued ||= !!options.reloadDraft; return }
  const g = generation, id = props.clientId
  loading.value = true
  try {
    const queryKind = eventKind.value, queryBefore = before.value, queryProbes = includeProbes.value, queryAgent = eventAgent.value
    const resources = props.view === 'events' ? ['status', 'records'] : ['status', 'policy', 'history', 'responses']
    if (props.view === 'events' && !props.fixedRoot && (!agentsLoaded.value || options.reloadAgents)) resources.push('record-agents')
    const data = Object.fromEntries(await Promise.all(resources.map(async resource => [resource, await getEnforcement(id, resource, resource === 'records' ? { before: queryBefore, kind: queryKind, include_probes: queryProbes, root_path: props.fixedRoot ? undefined : queryAgent, installation_path: props.fixedRoot || undefined } : undefined)])))
    if (g !== generation) return
    status.value = data.status
    if (props.view === 'events') {
      if (data['record-agents']) { agentRoots.value = data['record-agents'].items.map(item => item.root_path); agentsLoaded.value = true }
      if (queryKind === eventKind.value && queryBefore === before.value && queryProbes === includeProbes.value && queryAgent === eventAgent.value) events.value = data.records
    } else {
      history.value = data.history.items; responses.value = data.responses.items
      if (!initialized || options.reloadDraft) { loadDraft(data.policy.policy); baseRevision = data.policy.revision; baseConfigurationRevision = data.policy.configuration_revision; initialized = true }
    }
    error.value = ''
    hasLoaded.value = true
  } catch (err) { if (g === generation) failure(err) }
  finally { if (g === generation) { loading.value = false; if (refreshQueued) { const reloadDraft = reloadDraftQueued; refreshQueued = false; reloadDraftQueued = false; refresh({ reloadDraft }) } } }
}
async function publish(revoke) {
  if (saving.value || !canPublish.value) return
  const id = props.clientId, g = generation
  saving.value = true
  try {
    const body = { ...draft.value, rules: revoke ? [] : draft.value.rules, agent_executables: roots.value.split('\n').map(s => s.trim()).filter(Boolean), expected_revision: baseRevision, expected_configuration_revision: baseConfigurationRevision, lifetime_seconds: Math.round(hours.value * 3600) }
    const result = await publishEnforcement(id, body)
    if (g !== generation) return
    baseRevision = result.revision; baseConfigurationRevision = result.configuration_revision; loadDraft(result.policy); message.success(t('aidr.enforcement.saved')); await refresh()
  } catch (err) { if (g === generation) failure(err) }
  finally { if (g === generation) saving.value = false }
}
function terminationReason(row) {
  const reportedAt = Date.parse(status.value.last_received_at)
  if (error.value || !Number.isFinite(reportedAt) || Math.abs(Date.now() - reportedAt) >= 10000) return 'enforcement_executor_inactive'
  if (status.value.state === 'collecting') return 'enforcement_control_not_enabled'
  if (status.value.state !== 'active') return 'enforcement_executor_inactive'
  if (row.record.boot_id !== status.value.health?.boot_id || row.record.monitor_id !== status.value.health?.monitor_id) return 'enforcement_monitor_changed'
  return row.can_terminate === true ? '' : row.termination_reason || 'enforcement_target_unverified'
}
async function terminate(row) {
  if (terminating.value || !canTerminate.value || terminationReason(row)) return
  const record = row.record
  const id = props.clientId, g = generation, key = JSON.stringify([record.boot_id, record.monitor_id, record.process])
  if (!requests.has(key)) requests.set(key, crypto.randomUUID())
  terminating.value = true
  try {
    await terminateEnforcement(id, { request_id: requests.get(key), boot_id: record.boot_id, monitor_id: record.monitor_id, process: record.process })
    if (g === generation) { message.success(t('aidr.enforcement.sent')); await refresh() }
  } catch (err) { if (g === generation) failure(err) }
  finally { if (g === generation) terminating.value = false }
}
watch(() => [props.clientId, props.fixedRoot], () => {
  eventAgent.value = props.fixedRoot; agentRoots.value = []; agentsLoaded.value = false
  generation++; refreshQueued = false; reloadDraftQueued = false; initialized = false; loading.value = false; saving.value = false; terminating.value = false; before.value = 0; status.value = {}; events.value = {}; responses.value = []; history.value = []; requests.clear(); detailOpen.value = false; infoOpen.value = false; hasLoaded.value = false; eventSearch.value = ''
  clearInterval(timer); refresh(); timer = setInterval(() => { if (!document.hidden) refresh() }, 5000)
}, { immediate: true })
onBeforeUnmount(() => { generation++; clearInterval(timer) })
</script>

<style scoped>
.network-details { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.network-details dd { margin: 4px 0; overflow-wrap: anywhere; }
.enforcement-panel { margin: 12px 0; padding: 16px; border: 1px solid #d9d9d9; border-radius: 8px; }
.enforcement-panel.control-view { margin: 0; padding: 0; border: 0; min-width: 0; }
.control-intro { margin: 8px 0; color: #596579; font-size: 13px; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 12px 0; }
.controls .ant-select { min-width: 150px; }
.setup-guide li { margin: 14px 0; padding-right: 8px; }
.command { display: flex; align-items: flex-start; gap: 10px; margin: 8px 0; }
.command code { flex: 1; min-width: 0; padding: 10px; background: #f5f7f9; }
.command .ant-btn { flex-shrink: 0; height: auto; white-space: normal; }
.rule { display: grid; grid-template-columns: 130px minmax(180px, 1fr) 200px 100px auto; gap: 8px; margin: 8px 0; }
.coverage-path { display: block; margin: 6px 0; }
.operation-detail { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 280px; overflow: auto; background: #f5f7fa; padding: 12px; border-radius: 6px; }
.detail-meta { color: #64748b; }
.process-timeline { padding-left: 20px; max-height: 340px; overflow: auto; }
.process-timeline li { padding: 8px 0; border-bottom: 1px solid #edf0f5; }
.process-timeline code { display: block; margin-top: 4px; }
code, .evidence { overflow-wrap: anywhere; white-space: pre-wrap; word-break: break-word; }
.evidence { max-height: 65vh; overflow: auto; }
summary { cursor: pointer; margin: 12px 0; }
.system-event-view { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; overflow: hidden; padding: 0; border-color: #e4e8ef; background: #fff; }
.events-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 14px 16px; flex-shrink: 0; }
.events-heading { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; min-width: 0; }
.events-heading h3 { margin: 0; color: #172b45; font-size: 16px; font-weight: 650; }
.collection-indicator { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #64748b; }
.status-dot { width: 6px; height: 6px; background: currentColor; border-radius: 50%; flex-shrink: 0; }
.collection-indicator.good { color: #247a58; }
.events-header-actions { display: flex; gap: 8px; }
.events-header-actions .ant-btn { font-size: 12px; }
.events-alert { margin: 0 16px 12px; flex-shrink: 0; }
.events-notice, .network-note { display: flex; align-items: center; gap: 8px; padding: 6px 16px; font-size: 12px; flex-shrink: 0; }
.events-notice { color: #8b5d19; background: #fff9ed; }
.network-note { color: #526579; background: #f5f8fc; }
.events-notice > span, .network-note > span { min-width: 0; }
.events-notice .ant-btn, .network-note .ant-btn { white-space: normal; height: auto; margin-left: auto; flex-shrink: 0; }
.events-filters { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 0 16px 12px; border-bottom: 1px solid #e4e8ef; flex-shrink: 0; }
.event-categories { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.event-categories button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 1px solid transparent; background: transparent; border-radius: 6px; padding: 6px 10px; color: #526579; font: inherit; font-size: 13px; cursor: pointer; }
.event-categories button:hover { background: #f3f6fb; }
.event-categories button.selected { color: #245edb; background: #edf3ff; border-color: #d9e5ff; font-weight: 600; }
.extra-event-types { width: 150px; }
.event-agent-filter { width: 165px; }
.agent-filter-option { max-width: 420px; }
.agent-filter-option strong { font-weight: 500; }
.agent-filter-option small { display: block; overflow-wrap: anywhere; white-space: normal; color: #718096; font-size: 11px; }
.event-search { flex: 1; min-width: 200px; }
.event-search :deep(.ant-input-prefix) { color: #718096; }
.events-filters .ant-checkbox-wrapper { font-size: 12px; color: #526579; }
.system-event-list { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.system-event-row { border-bottom: 1px solid #edf0f5; }
.event-open { width: 100%; display: grid; grid-template-columns: 32px minmax(0, 1fr) minmax(130px, 190px) 12px; align-items: start; gap: 12px; padding: 16px; background: transparent; border: 0; text-align: left; color: #25364b; cursor: pointer; font: inherit; }
.event-open:hover { background: #f7f9fd; }
.event-type-icon { width: 32px; height: 32px; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; color: #4d6586; background: #f0f4fa; font-size: 16px; }
.event-type-icon.network { color: #297575; background: #edf7f6; }
.event-type-icon.file { color: #896527; background: #fbf5e9; }
.event-summary { display: flex; min-width: 0; flex-direction: column; gap: 6px; }
.event-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
.event-title strong { font-weight: 650; }
.agent-label, .probe-label, .repeat-label { font-size: 11px; font-weight: 400; border-radius: 4px; padding: 1px 6px; color: #526579; background: #f1f4f8; }
.event-operation { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 12px; line-height: 1.65; color: #293c55; }
.event-process { display: flex; gap: 10px; flex-wrap: wrap; color: #718096; font-size: 11px; overflow-wrap: anywhere; }
.event-trailing { display: flex; align-items: flex-end; gap: 8px; flex-direction: column; font-size: 11px; color: #64748b; text-align: right; font-variant-numeric: tabular-nums; }
.event-trailing time { white-space: nowrap; }
.event-outcome { display: inline-block; font-size: 11px; line-height: 1.5; padding: 2px 7px; border-radius: 4px; background: #f1f4f8; color: #526579; }
.event-outcome.success { background: #edf7f1; color: #267250; }
.event-outcome.attention { background: #fff4e6; color: #946017; }
.event-chevron { align-self: center; font-size: 10px; color: #94a3b8; }
.event-response { display: flex; justify-content: flex-end; padding: 0 16px 10px; }
.events-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 10px 16px; color: #718096; font-size: 12px; border-top: 1px solid #e4e8ef; flex-shrink: 0; }
.events-footer > div { display: flex; gap: 8px; }
.event-empty { min-height: 180px; padding: 32px 16px; text-align: center; color: #718096; }
.event-empty > .anticon { font-size: 26px; margin-bottom: 12px; color: #94a3b8; }
.event-empty h4 { margin: 0 0 8px; color: #334155; }
.event-empty p { font-size: 13px; }
.event-categories button:focus-visible, .event-open:focus-visible, .system-event-list:focus-visible { outline: 2px solid #2563eb; outline-offset: -2px; }
.collection-details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 20px; margin: 20px 0; }
.collection-details dt { color: #718096; font-size: 12px; }
.collection-details dd { margin: 4px 0 0; color: #26384e; overflow-wrap: anywhere; }
.collection-detail-heading { margin: 22px 0 8px; font-weight: 600; }
.event-detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 16px; }
.event-detail-heading p { margin: 0; font-size: 12px; }
.event-attribution { padding: 14px; background: #f8fafc; border-radius: 6px; }
@media (max-width: 800px) {
  .events-header { gap: 8px; padding: 12px; }
  .events-filters { padding: 0 12px 10px; gap: 8px; }
  .event-open { padding: 12px; gap: 8px; grid-template-columns: 28px minmax(0, 1fr) 120px 10px; }
  .event-type-icon { width: 28px; height: 28px; font-size: 14px; }
  .event-search { flex-basis: 60%; }
}
@media (max-width: 520px) {
  .events-heading { gap: 5px; }
  .events-header-actions { margin-left: auto; }
  .event-categories { flex: 1 0 100%; justify-content: space-between; }
  .event-categories button { padding: 5px 7px; }
  .event-categories .anticon { display: none; }
  .extra-event-types { width: 130px; }
  .event-search { min-width: 140px; flex-basis: 140px; }
  .event-open { grid-template-columns: 26px minmax(0, 1fr) 10px; }
  .event-trailing { grid-column: 2; flex-direction: row; align-items: center; justify-content: space-between; flex-wrap: wrap; text-align: left; }
  .event-chevron { grid-column: 3; grid-row: 1 / 3; }
  .events-footer { padding: 8px 12px; font-size: 11px; }
  .collection-details { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 800px) { .rule { grid-template-columns: 1fr; } }
</style>
