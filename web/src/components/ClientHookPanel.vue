<template>
  <section ref="panelElement" class="hook-panel" :class="{ 'control-view': view === 'control' }">
    <ClientProtectionStatus v-if="view === 'control' && !global && !fixedAgent" :client-id="clientId" channel="hooks" />
    <h3 v-if="view === 'events'">{{ t('aidr.hooks.events.title') }}</h3>
    <details v-if="view === 'events'" class="hook-context"><summary>{{ t('aidr.hooks.evidenceBoundary') }}</summary><p>{{ t('aidr.hooks.evidenceNote') }}</p><p>{{ t('aidr.hooks.events.note') }}</p><p>{{ t('aidr.hooks.scrollHint') }}</p></details>
    <a-alert v-if="actionError" type="error" show-icon :message="actionError" />
    <template v-if="['plugins','runtime'].includes(view)">
      <a-button :loading="policyLoading" :disabled="policyLoading" @click="loadPolicy">{{ t(policyError ? 'aidr.hooks.retry' : 'aidr.hooks.refresh') }}</a-button>
      <a-alert v-if="policyError" type="error" :message="policyError" show-icon />
      <template v-if="policy">
        <details v-if="view === 'plugins'" class="hook-analysis" open>
          <summary>{{ t('aidr.hooks.plugins.title') }}</summary>
          <p>{{ t('aidr.hooks.plugins.note') }}</p>
          <p v-if="!policy.plugins?.items?.length">{{ t('aidr.hooks.plugins.unknown') }}</p>
          <p v-if="policy.plugins?.truncated">{{ t('aidr.hooks.plugins.truncated') }}</p>
          <div v-for="item in policy.plugins?.items || []" :key="item.report.stream_id + item.report.status.scope_digest" class="hook-drift-entry">
            <strong>{{ item.report.status.agent }} · {{ item.report.status.host_version || t('aidr.hooks.unknown') }}</strong>
            <p>{{ t('aidr.hooks.plugins.' + item.report.status.version_status) }}</p>
            <p>{{ t('aidr.hooks.plugins.' + item.report.status.source_code) }}</p>
            <p>{{ t(item.report.status.source_kind === 'unknown' ? 'aidr.hooks.plugins.sourceUnknown' : 'aidr.hooks.plugins.' + item.report.status.source_kind) }} · {{ t('aidr.hooks.plugins.' + item.report.status.files_code) }}</p>
            <p>{{ t('aidr.hooks.receivedAt') }}: {{ stamp(item.received_at) }} · {{ t(item.stale ? 'aidr.hooks.plugins.stale' : 'aidr.hooks.plugins.recent') }}</p>
            <p>{{ t('aidr.hooks.plugins.change') }}: {{ t('aidr.hooks.plugins.' + item.change.code) }} · {{ item.change.received_at ? stamp(item.change.received_at) : t('aidr.hooks.unknown') }}</p>
            <p v-for="field in item.change.fields" :key="field">{{ t('aidr.hooks.plugins.' + field) }}</p>
          </div>
        </details>
        <details v-if="view === 'runtime'" class="hook-analysis" open>
          <summary>{{ t('aidr.hooks.runtime.title') }}</summary>
          <p>{{ t('aidr.hooks.runtime.note') }}</p>
          <p v-if="!policy.runtime?.items?.length">{{ t('aidr.hooks.runtime.unknown') }}</p>
          <p v-if="policy.runtime">{{ t('aidr.hooks.updated') }}: {{ stamp(policy.runtime.checked_at) }}</p>
          <p v-if="policy.runtime?.truncated">{{ t('aidr.hooks.runtime.truncated') }}</p>
          <div v-for="entry in policy.runtime?.items || []" :key="entry.stream_id + entry.receiver_instance" class="hook-drift-entry">
            <p>{{ t('aidr.hooks.receiver') }}: <code>{{ entry.receiver_instance }}</code></p>
            <p>{{ t('aidr.hooks.runtime.' + entry.control_mode) }} · {{ t('aidr.hooks.runtime.' + entry.control_code) }}</p>
            <p>{{ t('aidr.hooks.revision') }}: {{ entry.control_revision || t('aidr.hooks.unknown') }} · {{ t(entry.matches_published_revision ? 'aidr.hooks.runtime.matches' : 'aidr.hooks.runtime.differs') }}</p>
            <p>{{ t('aidr.hooks.receivedAt') }}: {{ stamp(entry.received_at) }} · {{ t('aidr.hooks.runtime.' + entry.code) }}</p>
            <p>{{ t('aidr.hooks.runtime.queued') }}: {{ entry.queued_records }}</p>
            <p>{{ t('aidr.hooks.runtimeUpload.state') }}: {{ t('aidr.hooks.runtimeUpload.codes.' + (entry.upload_code == null ? 'unknown' : entry.upload_code || 'noFailure')) }}</p>
            <p>{{ t('aidr.hooks.runtimeUpload.next') }}: {{ entry.next_upload_at ? new Date(entry.next_upload_at).toLocaleString(locale) : t('aidr.hooks.unknown') }}</p>
            <p>{{ t('aidr.hooks.runtimeUpload.ack') }}: {{ entry.last_event_ack_at ? new Date(entry.last_event_ack_at).toLocaleString(locale) : t('aidr.hooks.unknown') }}</p>
            <p>{{ t('aidr.redactionSettings.applied') }}: {{ entry.audit_policy?.version || t('aidr.unknown') }} · {{ t('aidr.content.appliedScope') }}: {{ scopeLabel(entry.audit_policy?.capture) }}</p>
            <p>{{ t('aidr.lifecycle.actual') }}: {{ lifecycleLabel(entry.audit_policy?.lifecycle) }}</p>
            <p v-if="entry.audit_suppressed_recent != null">{{ t('aidr.lifecycle.suppressed', { count: entry.audit_suppressed_recent }) }}</p>
          </div>
        </details>
      </template>
    </template>
    <template v-if="view === 'control'">
    <div class="control-note-row">
      <p v-if="!fixedAgent" class="control-mode-note">{{ t(global ? 'aidr.hooks.scope.globalHelp' : `aidr.hooks.${controlReportKey}`) }}</p>
      <a-button v-if="controlTab === 'rules'" type="text" size="small" :loading="policyLoading" :disabled="policyLoading || saving" @click="loadPolicy">{{ t(policyError ? 'aidr.hooks.retry' : 'aidr.hooks.refresh') }}</a-button>
    </div>
    <div v-if="!global && !controlSection" class="control-tabs" role="group" :aria-label="t('aidr.hooks.title')"><button :aria-pressed="controlTab === 'rules'" @click="controlTab = 'rules'">{{ t('aidr.hooks.commands.title') }}</button><button :aria-pressed="controlTab === 'approvals'" @click="controlTab = 'approvals'">{{ t('aidr.hooks.approvals') }} <span>{{ page.items.length }}</span></button></div>
    <div v-if="controlTab === 'approvals'">
    <div class="hook-heading hook-list-heading"><h4>{{ t('aidr.hooks.approvals') }} <span class="hook-count">{{ t('aidr.hooks.visibleRecords', { count: page.items.length }) }}</span></h4><a-button :loading="listLoading" :disabled="listLoading || deciding" @click="loadList()">{{ t(listError ? 'aidr.hooks.retry' : 'aidr.hooks.refresh') }}</a-button></div>
    <a-alert v-if="listError" type="error" show-icon :message="listError" />
    <p>{{ t('aidr.hooks.lastSync') }}: {{ lastSynced ? new Date(lastSynced).toLocaleString(locale) : t('aidr.hooks.unknown') }}</p>
    <a-alert v-if="latestAvailable" type="info" show-icon :message="t('aidr.hooks.latestAvailable')">
      <template #description><a-button :disabled="listLoading || deciding" @click="loadList(null)">{{ t('aidr.hooks.showLatest') }}</a-button></template>
    </a-alert>
    <a-table class="hook-table" table-layout="fixed" :columns="columns" :data-source="page.items" row-key="id" :pagination="false" :scroll="{ x: 820, y: 'min(52vh, 440px)' }" size="small" :locale="{ emptyText: t(listError ? 'aidr.hooks.listUnavailable' : 'aidr.hooks.empty') }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'created'"><span class="hook-date">{{ datePart(record.created_at) }}<small>{{ timePart(record.created_at) }}</small></span></template>
        <template v-else-if="column.key === 'agent'">{{ record.scope.agent }}<div><a-tooltip :title="record.scope.tool" :trigger="['hover', 'focus']"><code class="hook-id" tabindex="0" :aria-label="record.scope.tool">{{ shortId(record.scope.tool) }}</code></a-tooltip></div></template>
        <template v-else-if="column.key === 'session'"><a-tooltip :title="record.scope.session_id" :trigger="['hover', 'focus']"><code class="hook-id" tabindex="0" :aria-label="record.scope.session_id">{{ shortId(record.scope.session_id) }}</code></a-tooltip><div><a-tooltip :title="record.scope.native_call_id" :trigger="['hover', 'focus']"><code class="hook-id" tabindex="0" :aria-label="record.scope.native_call_id">{{ shortId(record.scope.native_call_id) }}</code></a-tooltip></div></template>
        <template v-else-if="column.key === 'state'"><a-tag :color="stateColor(record.state)">{{ stateLabel(record.state) }}</a-tag></template>
        <template v-else-if="column.key === 'expires'"><span class="hook-date">{{ datePart(record.expires_at) }}<small>{{ timePart(record.expires_at) }}</small></span></template>
        <template v-else><a-button type="link" @click="openDetail(record.id)">{{ t('aidr.hooks.details') }}</a-button></template>
      </template>
    </a-table>
    <p v-if="!listError && !page.items.length">{{ t('aidr.hooks.approvalEmptyHelp') }}</p>
    <div v-if="cursor || page.has_more" class="hook-heading"><a-button :disabled="listLoading || deciding || !cursor" @click="loadList(null)">{{ t('aidr.hooks.first') }}</a-button><a-button :disabled="listLoading || deciding || !page.has_more" @click="loadList({ before: page.next_before, before_id: page.next_before_id })">{{ t('aidr.hooks.next') }}</a-button></div>
    </div>
    <section v-if="controlTab === 'rules'" class="control-rules">
      <a-alert v-if="policyError" type="error" :message="policyError" show-icon />
      <template v-if="policy">
        <div class="scope-choice" v-if="!global">
          <label :title="!policy.global_policy ? t('aidr.hooks.scope.unconfigured') : ''"><a-switch v-model:checked="inherit" :disabled="!canEdit || saving || policyLoading || !!policyError || (!inherit && !policy.global_policy)" @change="changeInheritance" /> {{ t('aidr.hooks.scope.inherit') }}</label>
          <span>{{ t('aidr.hooks.scope.' + policy.distribution) }}</span>
          <small>{{ t('aidr.hooks.scope.localHelp') }}</small>
        </div>
        <p v-else>{{ t('aidr.hooks.scope.impact', policy.impact || {}) }}</p>
        <p v-if="!canEdit">{{ t('aidr.hooks.readonly') }}</p>
        <AidrCommandRules v-model:rules="draft.rules" :products="products" :disabled="(!global && inherit) || !canEdit || saving || policyLoading || !!policyError" />
        <fieldset class="default-rule" :disabled="(!global && inherit) || !canEdit || saving || policyLoading || !!policyError">
          <label>{{ t('aidr.hooks.defaultAction') }}<select v-model="draft.default_action"><option v-for="d in decisions" :key="d" :value="d">{{ t(`aidr.hooks.${d}`) }}</option></select></label>
          <span :class="{ 'default-danger': draft.default_action === 'deny' }">{{ t('aidr.hooks.commands.fallback.' + draft.default_action) }}</span>
        </fieldset>
        <AidrRulePreview :client-id="clientId" :global="global" channel="hooks" :draft="draft" />
        <footer class="policy-footer"><span role="status">{{ t(saved ? 'aidr.hooks.published' : dirty ? 'aidr.hooks.commands.unsaved' : 'aidr.hooks.commands.noChanges') }}</span><a-button type="primary" :disabled="!canEdit || saving || policyLoading || !!policyError || !dirty" @click="reviewOpen = true">{{ t('aidr.hooks.commands.review') }}</a-button></footer>
      </template>
    </section>
    <a-modal v-model:open="reviewOpen" :title="t('aidr.hooks.commands.review')" :closable="!saving" :mask-closable="!saving" :keyboard="!saving" :confirm-loading="saving" :ok-text="t(global ? 'aidr.hooks.globalPublish' : 'aidr.hooks.publish')" :cancel-text="t('aidr.hooks.cancel')" :cancel-button-props="{ disabled: saving }" :ok-button-props="{ disabled: !dirty || !canEdit || !!policyError }" @ok="publish">
      <p>{{ t('aidr.hooks.commands.reviewHelp') }}</p>
      <p v-if="global">{{ t('aidr.hooks.scope.impact', policy?.impact || {}) }}</p>
      <p v-else>{{ t(inherit ? 'aidr.hooks.scope.inherit' : 'aidr.hooks.scope.local') }}</p>
      <ul class="publish-review"><li v-for="rule in draft.rules" :key="rule.id"><div><strong>{{ rule.id }}</strong><code>{{ rule.command ? [rule.command.executable, ...(rule.command.args_all || []), rule.command.args_any?.length ? '(' + rule.command.args_any.join(' / ') + ')' : '', rule.command.path_prefix, rule.command.pipe_to?.length ? '| ' + rule.command.pipe_to.join(' / ') : ''].filter(Boolean).join(' ') : rule.tool }}</code><small>{{ t(rule.command ? 'aidr.hooks.commands.commandType' : 'aidr.hooks.commands.toolType') }}</small></div><span>{{ rule.agent === '*' ? t('aidr.hooks.commands.allAgents') : products.find(p => p.id === rule.agent)?.name || rule.agent }}</span><a-tag>{{ t('aidr.hooks.' + rule.decision) }}</a-tag></li></ul>
      <p><strong>{{ t('aidr.hooks.defaultAction') }}: {{ t('aidr.hooks.' + draft.default_action) }}</strong></p><p>{{ t('aidr.hooks.commands.fallback.' + draft.default_action) }}</p>
      <a-alert v-if="actionError" type="error" show-icon :message="actionError" />
    </a-modal>
    </template>
    <template v-if="view === 'events'">
    <form class="hook-filters" @submit.prevent="applyEventFilters">
      <div class="hook-filter-main">
        <label>{{ t('aidr.hooks.agent') }}<select v-model="eventFilters.agent"><option value="">{{ t('aidr.hooks.events.all') }}</option><option v-for="product in products.filter(p => p.hooks)" :key="product.id" :value="product.id">{{ product.name }}</option></select></label>
        <label>{{ t('aidr.hooks.events.eventFilter') }}<a-auto-complete v-model:value="eventFilters.hook_event" :options="hookEventOptions" :filter-option="matchHookEvent" :aria-label="t('aidr.hooks.events.eventFilter')" :placeholder="t('aidr.hooks.events.all')" :maxlength="32" allow-clear @select="selectHookEvent" /></label>
        <label>{{ t('aidr.hooks.events.search') }}<a-input v-model:value="eventFilters.keyword" :aria-label="t('aidr.hooks.events.search')" :placeholder="t('aidr.hooks.events.searchPlaceholder')" :title="t('aidr.hooks.events.keyword')" :maxlength="256" allow-clear /></label>
      </div>
      <div class="hook-filter-actions">
        <span class="hook-muted">{{ t('aidr.hooks.events.autoFilter') }}</span>
        <div><a-button type="link" :aria-expanded="advancedFiltersOpen" @click="advancedFiltersOpen = !advancedFiltersOpen">{{ t(advancedFiltersOpen ? 'aidr.hooks.events.lessFilters' : 'aidr.hooks.events.moreFilters') }}<span v-if="advancedFilterCount"> ({{ advancedFilterCount }})</span></a-button><a-button type="text" :disabled="!hasEventFilters" @click="clearEventFilters">{{ t('aidr.hooks.events.clear') }}</a-button></div>
      </div>
      <div v-if="advancedFiltersOpen" class="hook-filter-advanced">
        <label v-for="field in advancedFilterFields" :key="field">{{ t('aidr.hooks.events.filters.' + field) }}<a-input v-model:value="eventFilters[field]" :aria-label="t('aidr.hooks.events.filters.' + field)" :maxlength="field === 'event_id' ? 32 : 256" allow-clear /></label>
      </div>
    </form>
    <div class="hook-heading hook-pagination"><a-button :loading="eventQueryBusy" :disabled="eventQueryBusy" @click="loadEvents(eventHistory[eventIndex], 'refresh')">{{ t(eventsError ? 'aidr.hooks.retry' : 'aidr.hooks.refresh') }}</a-button><a-button :disabled="eventQueryBusy" @click="loadEvents()">{{ t('aidr.hooks.events.latest') }}</a-button><a-button :disabled="eventQueryBusy || eventIndex === 0" @click="loadEvents(eventHistory[eventIndex - 1], 'newer')">{{ t('aidr.hooks.events.newer') }}</a-button><a-button :disabled="eventQueryBusy || !!eventsError || !eventsPage.has_more" @click="loadEvents({ before: eventsPage.next_before, snapshot_id: eventsPage.snapshot_id }, 'older')">{{ t('aidr.hooks.events.older') }}</a-button><span class="hook-muted">{{ t('aidr.hooks.events.batch', { number: eventIndex + 1 }) }}</span></div>
    <a-alert v-if="eventsError" type="error" show-icon :message="eventsError" />
    <a-table class="hook-table hook-event-table" table-layout="fixed" :columns="eventColumns" :data-source="eventsPage.items" :loading="eventQueryBusy" row-key="id" :pagination="false" :scroll="{ x: 1200, y: 'min(56vh, 500px)' }" size="small" :locale="{ emptyText: t(eventsError ? 'aidr.hooks.events.unavailable' : 'aidr.hooks.events.empty') }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'received'"><span class="hook-date">{{ datePart(record.record.received_at, true) }}<small>{{ timePart(record.record.received_at, true) }}</small></span></template>
        <template v-else-if="column.key === 'agent'">{{ record.record.event.agent }}</template>
        <template v-else-if="column.key === 'relation'">{{ t('aidr.hooks.events.roles.' + eventRole(record.record.event)) }}<div v-if="eventRole(record.record.event) === 'result'">{{ hookResult(record.record.event.behavior?.status) }}<template v-if="record.record.event.behavior?.exit_code != null && record.record.event.behavior?.status !== 'reported_success'"> · {{ t('aidr.hooks.events.exitCode') }} {{ record.record.event.behavior.exit_code }}</template></div></template>
        <template v-else-if="column.key === 'event'"><code>{{ record.record.event.hook_event }}</code><div>{{ record.record.event.tool }}</div></template>
        <template v-else-if="column.key === 'activity'"><p class="hook-line-clamp">{{ eventMeaning(record.record.event) }}</p><a-tooltip v-if="record.record.event.behavior?.actions?.[0]?.command" :title="record.record.event.behavior.actions[0].command"><code class="hook-line-clamp">{{ record.record.event.behavior.actions[0].command }}</code></a-tooltip><small v-if="record.record.event.behavior?.actions?.length" class="hook-muted">{{ t('aidr.hooks.events.actionsInDetail', { count: record.record.event.behavior.actions.length }) }}</small></template>
        <template v-else-if="column.key === 'session'"><a-tooltip :title="record.record.event.session_id" :trigger="['hover', 'focus']"><code class="hook-id" tabindex="0" :aria-label="record.record.event.session_id">{{ shortId(record.record.event.session_id) }}</code></a-tooltip><div v-if="record.record.event.native_call_id"><a-tooltip :title="record.record.event.native_call_id" :trigger="['hover', 'focus']"><code class="hook-id" tabindex="0" :aria-label="record.record.event.native_call_id">{{ shortId(record.record.event.native_call_id) }}</code></a-tooltip></div></template>
        <template v-else><a-button type="link" @click="openEventDetail(record)">{{ t('aidr.hooks.details') }}</a-button></template>
      </template>
    </a-table>
    </template>
    <a-modal v-model:open="eventDetailOpen" :title="t('aidr.hooks.events.detail')" :footer="null" width="min(900px, 94vw)" :destroy-on-close="true">
      <article v-if="eventDetail" class="audit-detail">
        <header class="audit-detail-header">
          <h3>{{ hookEvent.tool || hookEvent.hook_event }}</h3>
          <a-tag v-if="hookEvent.tool">{{ hookEvent.hook_event }}</a-tag>
          <a-tag v-if="eventRole(hookEvent) === 'result'">{{ hookResult(hookEvent.behavior?.status) }}</a-tag>
        </header>
        <p class="hook-muted">{{ hookEvent.agent }} · Hook · {{ new Date(eventDetail.record.received_at).toLocaleString(locale) }}</p>
        <p>{{ eventMeaning(hookEvent) }}</p>
        <p v-if="!hookEvent.tool">{{ t('aidr.hooks.session') }}: <code>{{ hookEvent.session_id }}</code></p>
        <p v-if="hookEvent.native_agent_id">{{ t('aidr.detail.subagent') }}: <code>{{ hookEvent.native_agent_id }}</code></p>
        <p v-if="eventRole(hookEvent) === 'result' && hookEvent.behavior?.exit_code != null && hookEvent.behavior?.status !== 'reported_success'">{{ t('aidr.hooks.events.exitCode') }}: <strong>{{ hookEvent.behavior.exit_code }}</strong></p>
        <AidrAuditActions :actions="hookEvent.behavior?.actions || []" :tool="hookEvent.tool" :body-omitted="hookEvent.behavior?.body_omitted" :body-captured="hookEvent.behavior?.contents?.some(item => item.kind === 'command_body')" />
        <p v-if="hookEvent.behavior?.truncated" class="hook-muted">{{ t('aidr.truncated') }}</p>
        <AidrAuditContent v-if="eventDetailOpen" :client-id="clientId" source="hook" :record-id="eventDetail.id" :evidence="hookEvent" />
        <details v-if="canRelateHook" class="hook-context">
          <summary>{{ t('aidr.detail.relatedHooks') }}<span v-if="relatedOthers.length"> · {{ relatedOthers.length }}</span></summary>
          <p v-if="relatedLoading">{{ t('aidr.detail.loadingRelated') }}</p>
          <a-alert v-if="relatedError" type="error" show-icon :message="relatedError"><template #action><a-button :loading="relatedLoading" :disabled="relatedLoading" @click="loadRelated(eventDetail)">{{ t('aidr.hooks.retry') }}</a-button></template></a-alert>
          <p v-if="related && related.code !== 'native_identity_matched'">{{ t('aidr.hooks.events.relatedCodes.' + related.code) }}</p>
          <p v-if="related?.relation === 'matched'">{{ t('aidr.detail.relatedNote') }}</p>
          <p v-if="related?.execution_evidence">
            {{ t('aidr.sessions.endHookMissing') }} · {{ t('aidr.sessions.executionStates.' + related.execution_evidence.status) }} ·
            {{ t('aidr.sessions.executionSources.' + (related.execution_evidence.source === 'codex.item_completed' ? 'codex' : 'log')) }} ·
            {{ t('aidr.detail.recordId') }}: {{ related.execution_evidence.record_id }}
            <span v-if="Number.isInteger(related.execution_evidence.exit_code)"> · {{ t('aidr.commandExitCode', { code: related.execution_evidence.exit_code }) }}</span>
            <span v-if="related.execution_evidence.relation === 'inferred'"> · {{ t('aidr.sessions.executionInferred') }}</span>
          </p>
          <div v-for="item in relatedOthers" :key="item.id" class="hook-drift-entry">
            <strong>{{ item.record.event.hook_event }}</strong> · {{ new Date(item.record.received_at).toLocaleString(locale) }}
            <p v-if="eventRole(item.record.event) === 'result'">{{ hookResult(item.record.event.behavior?.status) }}<template v-if="item.record.event.behavior?.exit_code != null"> · {{ t('aidr.hooks.events.exitCode') }} {{ item.record.event.behavior.exit_code }}</template></p>
            <a-button type="link" @click="openEventDetail(item)">{{ t('aidr.hooks.details') }}</a-button>
          </div>
        </details>
        <details class="hook-context">
          <summary>{{ t('aidr.detail.recordInfo') }}</summary>
          <dl class="audit-record-fields">
            <template v-if="hookEvent.tool"><dt>{{ t('aidr.hooks.session') }}</dt><dd><code>{{ hookEvent.session_id }}</code></dd></template>
            <template v-if="hookEvent.turn_id"><dt>{{ t('aidr.hooks.turn') }}</dt><dd><code>{{ hookEvent.turn_id }}</code></dd></template>
            <template v-if="hookEvent.native_call_id"><dt>{{ t('aidr.hooks.call') }}</dt><dd><code>{{ hookEvent.native_call_id }}</code></dd></template>
            <dt>{{ t('aidr.detail.recordId') }}</dt><dd><code>{{ eventDetail.id }}</code></dd>
            <template v-if="hookEvent.policy"><dt>{{ t('aidr.redactionSettings.event') }}</dt><dd>{{ hookEvent.policy.version }} · {{ t(hookEvent.policy.enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') }}</dd></template>
            <template v-if="eventRole(hookEvent) === 'result' && hookEvent.behavior?.result_basis?.length"><dt>{{ t('aidr.resultBasis') }}</dt><dd>{{ hookEvent.behavior.result_basis.map(value => t('aidr.bases.' + value)).join(' · ') }}</dd></template>
          </dl>
          <p v-for="reason in hookEvent.behavior?.uncertainty || []" :key="reason">{{ t('aidr.uncertainties.' + reason) }}</p>
        </details>
      </article>
    </a-modal>
    <a-modal v-model:open="detailOpen" :title="t('aidr.hooks.detailTitle')" :footer="null" :width="900" :destroy-on-close="true">
      <a-alert v-if="actionError" type="error" :message="actionError" show-icon />
      <a-alert v-if="detailError" type="error" :message="detailError" show-icon />
      <a-button :loading="detailLoading" :disabled="detailLoading || deciding" @click="openDetail(detailId)">{{ t('aidr.hooks.retry') }}</a-button>
      <template v-if="detail && !detailError">
        <p>{{ t('aidr.hooks.evidenceNote') }}</p>
        <p>{{ t('aidr.hooks.state') }}: {{ stateLabel(detail.approval.state) }} · {{ t('aidr.hooks.recordedState') }}: {{ stateLabel(detail.approval.recorded_state) }}</p>
        <p>{{ t('aidr.hooks.expires') }}: {{ stamp(detail.approval.expires_at) }}</p>
        <a-alert type="info" :message="t('aidr.hooks.clientReport')" show-icon>
          <template #description>
            <template v-if="detail.client_report"><p>{{ t(detail.client_report.record.state === 'consumed' ? 'aidr.hooks.clientConsumed' : 'aidr.hooks.clientDenied') }} · <code>{{ detail.client_report.record.code }}</code></p><p>{{ t('aidr.hooks.reportedAt') }}: {{ stamp(detail.client_report.record.reported_at) }} · {{ t('aidr.hooks.receivedAt') }}: {{ stamp(detail.client_report.received_at) }}</p></template>
            <p v-else>{{ t('aidr.hooks.noClientReport') }}</p>
          </template>
        </a-alert>
        <dl class="hook-evidence"><template v-for="[label, key] in scopeFields" :key="key"><dt>{{ t(`aidr.hooks.${label}`) }}</dt><dd><code>{{ detail.approval.scope[key] || t('aidr.hooks.unknown') }}</code></dd></template></dl>
        <a-alert v-if="!detail.evidence" type="warning" :message="t('aidr.hooks.noEvidence')" />
        <p v-if="detail.evidence_code === 'aidr_audit_history_retention'">{{ t('aidr.lifecycle.historyExpired') }}</p>
        <div v-for="(action, index) in detail.evidence?.event?.behavior?.actions || []" :key="index" class="hook-evidence">
          <p v-if="action.command">{{ t('aidr.hooks.command') }}<pre>{{ action.command }}</pre></p><p v-if="action.cwd">{{ t('aidr.hooks.cwd') }}: <code>{{ action.cwd }}</code></p>
          <p v-for="(target, i) in action.targets || []" :key="i">{{ t('aidr.hooks.targets') }}: <code>{{ target.value }}</code></p>
        </div>
        <AidrAuditContent v-if="detail.evidence?.event && detail.evidence_record_id" :client-id="clientId" source="hook" :record-id="detail.evidence_record_id" :evidence="detail.evidence.event" />
        <p v-if="!actionAllowed">{{ t('aidr.hooks.unavailable') }}</p>
        <div class="hook-heading">
          <a-popconfirm v-for="action in availableActions" :key="action.value" :title="t('aidr.hooks.confirmDecision')" :ok-text="t('aidr.hooks.confirm')" :cancel-text="t('aidr.hooks.cancel')" :disabled="!actionAllowed || deciding" @confirm="decide(action.value)"><a-button :danger="action.value !== 'allow'" :loading="deciding" :disabled="!actionAllowed || deciding">{{ t(`aidr.hooks.${action.label}`) }}</a-button></a-popconfirm>
        </div>
      </template>
      <a-button @click="detailOpen = false">{{ t('aidr.hooks.close') }}</a-button>
    </a-modal>
  </section>
</template>

<script setup>
import products from '../aidr-products.json'
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import AidrAuditContent from './AidrAuditContent.vue'
import AidrAuditActions from './AidrAuditActions.vue'
import ClientProtectionStatus from './ClientProtectionStatus.vue'
import AidrRulePreview from './AidrRulePreview.vue'
import AidrCommandRules from './AidrCommandRules.vue'
import { useI18n } from 'vue-i18n'
import { can } from '../access'
import { getHookPolicy, saveHookPolicy, getGlobalToolPolicy, saveGlobalToolPolicy, listHookApprovals, getHookApproval, decideHookApproval, listHookEvents, getHookEventRelations } from '../api'
const props = defineProps({ clientId: { type: String, default: '' }, global: Boolean, view: { type: String, default: 'control' }, controlSection: { type: String, default: '' }, fixedAgent: { type: String, default: '' } })
const { t, locale } = useI18n()
const scopeLabel = scope => scope ? ['prompt', 'model_response', 'tool_output', 'file_body', 'command_body'].filter(kind => scope[kind]).map(kind => t('aidr.content.kinds.' + kind)).join(' · ') || t('aidr.content.none') : t('aidr.redactionSettings.unknown')
const lifecycleLabel = value => value ? t(value.enabled ? 'aidr.lifecycle.enabled' : 'aidr.lifecycle.disabled') + ' · ' + t('aidr.lifecycle.days', { days: value.retention_days }) : t('aidr.lifecycle.legacy')
const policy = ref(null), draft = ref({ default_action: 'deny', rules: [] })
const reviewOpen = ref(false), baseline = ref('')
const inherit = ref(false), baselineInherit = ref(false)
let localDraft = null
const dirty = computed(() => !!policy.value && ((props.global && !policy.value.policy) || inherit.value !== baselineInherit.value || JSON.stringify(draft.value) !== baseline.value))
function applyPolicy(data) {
  localDraft = null
  policy.value = data
  inherit.value = !props.global && !!data.inherit
  const selected = inherit.value ? data.global_policy : data.policy
  draft.value = { default_action: selected?.default_action || 'allow', rules: structuredClone(selected?.rules || []) }
  baseline.value = JSON.stringify(draft.value); baselineInherit.value = inherit.value
}
function changeInheritance() {
  if (inherit.value) {
    localDraft = JSON.parse(JSON.stringify(draft.value))
    const selected = policy.value?.global_policy
    draft.value = { default_action: selected?.default_action || 'allow', rules: structuredClone(selected?.rules || []) }
  } else if (localDraft) {
    draft.value = localDraft
    localDraft = null
  }
}
const controlTab = ref('rules')
watch(() => props.controlSection, section => { if (section) controlTab.value = section }, { immediate: true })
const controlReportKey = computed(() => {
  const report = policy.value?.runtime?.items?.[0]
  if (!report || report.code !== 'aidr_hook_runtime_recent' || now.value - Number(report.received_at) * 1000 > 90000) return 'controlUnknown'
  return report.control_mode === 'plugin_pre_tool' ? 'controlEnabled' : report.control_mode === 'audit' ? 'controlAudit' : 'controlUnknown'
})
const policyLoading = ref(false), listLoading = ref(false), saving = ref(false), deciding = ref(false), saved = ref(false)
const policyError = ref(''), listError = ref(''), actionError = ref(''), detailError = ref('')
watch(draft, () => { saved.value = false }, { deep: true })
const page = ref({ items: [], has_more: false }), cursor = ref(null)
const eventsPage = ref({ items: [], has_more: false }), eventsLoading = ref(false), eventsError = ref('')
const eventHistory = ref([{}]), eventIndex = ref(0)
const emptyEventFilters = () => ({ agent: '', hook_event: '', session_id: '', tool: '', native_call_id: '', event_id: '', keyword: '' })
const eventFilters = ref(emptyEventFilters()), appliedEventFilters = ref({})
const advancedFilterFields = ['tool', 'session_id', 'native_call_id', 'event_id']
const advancedFiltersOpen = ref(false), eventsPending = ref(false)
const advancedFilterCount = computed(() => advancedFilterFields.filter(field => eventFilters.value[field]).length)
const hasEventFilters = computed(() => Object.values(eventFilters.value).some(Boolean))
const eventQueryBusy = computed(() => eventsLoading.value || eventsPending.value)
let eventFilterTimer, resettingEventFilters = false
let eventsGeneration = 0, relatedGeneration = 0
const related = ref(null), relatedError = ref(''), relatedLoading = ref(false)
const hookResult = status => t('aidr.hooks.events.results.' + (['reported_complete', 'reported_error', 'reported_success', 'reported_cancelled', 'missing_result', 'missing_call', 'conflicting_evidence'].includes(status) ? status : 'unknown'))
const eventRole = event => event.kind === 'tool.pre' ? 'call' : ['tool.post', 'tool.failure'].includes(event.kind) ? 'result' : 'lifecycle'
const eventDetail = ref(null), eventDetailOpen = ref(false)
const hookEvent = computed(() => eventDetail.value?.record.event || {})
const canRelateHook = computed(() => ['tool.pre', 'tool.post', 'tool.failure'].includes(hookEvent.value.kind) && !!hookEvent.value.native_call_id)
const relatedOthers = computed(() => (related.value?.items || []).filter(item => item.id !== eventDetail.value?.id))
const eventColumns = computed(() => ['received', 'agent', 'event', 'relation', 'activity', 'session', 'details'].map(key => ({ key, title: t(['received', 'event', 'activity', 'relation'].includes(key) ? `aidr.hooks.events.${key}` : `aidr.hooks.${key}`), width: { received: 145, agent: 85, event: 160, relation: 160, activity: 280, session: 220, details: 90 }[key], fixed: key === 'received' ? 'left' : key === 'details' ? 'right' : undefined })))
const eventMeaningKeys = { SessionStart: 'sessionStart', SessionEnd: 'sessionEnd', UserPromptSubmit: 'promptSubmit', PreToolUse: 'preTool', PostToolUse: 'postTool', PostToolUseFailure: 'toolFailure', PermissionRequest: 'permissionRequest', PermissionDenied: 'permissionDenied', Stop: 'stop', Interrupt: 'interrupt', Notification: 'notification', SubagentStart: 'subagentStart', SubagentStop: 'subagentStop', PreCompact: 'preCompact', PostCompact: 'postCompact', TaskCompleted: 'taskCompleted', TeammateIdle: 'teammateIdle' }
const eventMeaning = event => t('aidr.hooks.events.meanings.' + (eventMeaningKeys[event.hook_event] || 'other'))
const hookEventOptions = Object.keys(eventMeaningKeys).map(value => ({ value }))
const matchHookEvent = (input, option) => option.value.toLowerCase().includes(input.toLowerCase())
function selectHookEvent(value) { eventFilters.value.hook_event = value; applyEventFilters() }
const detailOpen = ref(false), detailLoading = ref(false), detailId = ref(''), detail = ref(null), now = ref(Date.now())
const decisions = ['allow', 'deny', 'ask']
const states = ['pending', 'approved', 'denied', 'revoked', 'expired']
const stateLabel = value => t(`aidr.hooks.${states.includes(value) ? value : 'unknown'}`)
const canEdit = computed(() => !!policy.value?.can_edit && can('clients:update'))
const actionAllowed = computed(() => !!policy.value?.can_edit && can('clients:execute') && !!detail.value?.evidence && !detail.value?.client_report && !detailLoading.value && !detailError.value && ['pending', 'approved'].includes(detail.value?.approval.state) && Number(detail.value?.approval.expires_at) * 1000 > now.value)
const availableActions = computed(() => detail.value?.approval.state === 'approved' ? [{ value: 'revoke', label: 'revoke' }] : [{ value: 'allow', label: 'approve' }, { value: 'deny', label: 'reject' }])
const columns = computed(() => ['created', 'agent', 'session', 'state', 'expires', 'details'].map(key => ({ key, title: t(`aidr.hooks.${key}`), width: { created: 135, agent: 95, session: 215, state: 150, expires: 135, details: 90 }[key], fixed: key === 'created' ? 'left' : key === 'details' ? 'right' : undefined })))
const scopeFields = [['agent', 'agent'], ['tool', 'tool'], ['session', 'session_id'], ['turn', 'turn_id'], ['call', 'native_call_id'], ['user', 'user_scope'], ['receiver', 'receiver_instance'], ['inputDigest', 'input_digest'], ['attempt', 'attempt_nonce'], ['revision', 'policy_revision'], ['execution', 'execution_point']]
const shortId = value => !value ? t('aidr.hooks.unknown') : value.length > 28 ? `${value.slice(0, 15)}…${value.slice(-9)}` : value
const stateColor = state => ({ pending: 'gold', approved: 'green', denied: 'red', revoked: 'orange', expired: 'default' }[state] || 'default')
const tableDate = (value, iso) => value ? new Date(iso ? value : Number(value) * 1000) : null
const datePart = (value, iso = false) => tableDate(value, iso)?.toLocaleDateString(locale.value) || t('aidr.hooks.unknown')
const timePart = (value, iso = false) => tableDate(value, iso)?.toLocaleTimeString(locale.value, { hour12: false }) || ''
const stamp = value => value ? new Date(Number(value) * 1000).toLocaleString(locale.value) : t('aidr.hooks.unknown')
const failure = (error, key) => error.apiErrorCode?.endsWith('hook_command_upgrade_required') ? t('aidr.hooks.commands.upgrade') : `${t(`aidr.hooks.${key}`)}${error.apiErrorCode ? ` (${error.apiErrorCode})` : ''}`
let generation = 0, detailGeneration = 0, listGeneration = 0
const panelElement = ref(null), panelVisible = ref(false), documentVisible = ref(!document.hidden), componentActive = ref(true)
const lastSynced = ref(0), latestAvailable = ref(false)
let latestHead = '', visibilityObserver, syncTimer
const canSync = computed(() => props.view === 'control' && panelVisible.value && documentVisible.value && componentActive.value)
const headId = data => data.items?.[0]?.id || ''
const invalidateList = () => { listGeneration++; listLoading.value = false }
const syncApprovals = () => {
  if (props.global) return
  if (canSync.value && !listLoading.value && !deciding.value) void loadList(cursor.value, true)
}
const visibilityChanged = () => { documentVisible.value = !document.hidden }
watch(canSync, visible => {
  clearInterval(syncTimer)
  invalidateList()
  if (visible) {
    now.value = Date.now()
    if (!policy.value && !policyLoading.value) void loadPolicy()
    syncApprovals()
    syncTimer = setInterval(syncApprovals, 4000)
  }
})
onMounted(() => {
  document.addEventListener('visibilitychange', visibilityChanged)
  visibilityObserver = new IntersectionObserver(entries => { panelVisible.value = entries.some(entry => entry.isIntersecting) })
  visibilityObserver.observe(panelElement.value)
})
onActivated(() => { componentActive.value = true })
onDeactivated(() => { componentActive.value = false })
const requestIds = new Map()
const timer = setInterval(() => { if (canSync.value) now.value = Date.now() }, 1000)
async function loadPolicy() {
  if (policyLoading.value || saving.value) return
  const epoch = generation
  policyLoading.value = true; policyError.value = ''; saved.value = false
  try {
    const data = await (props.global ? getGlobalToolPolicy() : getHookPolicy(props.clientId))
    if (epoch !== generation) return
    applyPolicy(data)
  } catch (error) { if (epoch === generation) policyError.value = failure(error, 'policyError') }
  finally { if (epoch === generation) policyLoading.value = false }
}
async function loadList(next = cursor.value, automatic = false) {
  if (listLoading.value || (automatic && (!canSync.value || deciding.value))) return
  const epoch = generation, request = ++listGeneration
  const current = () => epoch === generation && request === listGeneration
  listLoading.value = true
  if (!automatic) listError.value = ''
  try {
    const data = await listHookApprovals(props.clientId, { ...(automatic ? {} : next || {}), ...(props.fixedAgent ? { agent: props.fixedAgent } : {}) })
    if (!current()) return
    lastSynced.value = Date.now(); listError.value = ''
    if (automatic && next) {
      if (headId(data) !== latestHead) latestAvailable.value = true
    } else {
      page.value = data; cursor.value = next
      if (!next) { latestHead = headId(data); latestAvailable.value = false }
    }
  } catch (error) { if (current()) listError.value = failure(error, 'listError') }
  finally { if (current()) listLoading.value = false }
}
function applyEventFilters() {
  clearTimeout(eventFilterTimer); eventsPending.value = false
  appliedEventFilters.value = Object.fromEntries(Object.entries(eventFilters.value).filter(([, value]) => typeof value === 'string' && value !== ''))
  eventsGeneration++; eventsLoading.value = false
  eventsPage.value = { items: [], has_more: false }; eventHistory.value = [{}]; eventIndex.value = 0
  void loadEvents()
}
function clearEventFilters() {
  resettingEventFilters = true; eventFilters.value = emptyEventFilters(); resettingEventFilters = false
  applyEventFilters()
}
watch(() => ({ ...eventFilters.value }), (value, previous) => {
  if (resettingEventFilters || props.view !== 'events') return
  clearTimeout(eventFilterTimer)
  eventsGeneration++; eventsLoading.value = false; eventsPending.value = true; eventsError.value = ''
  if (value.agent !== previous.agent || !Object.values(value).some(Boolean)) applyEventFilters()
  else eventFilterTimer = setTimeout(applyEventFilters, 250)
}, { flush: 'sync' })
async function loadEvents(next = {}, navigation = 'reset') {
  if (eventQueryBusy.value) return
  const epoch = generation, request = ++eventsGeneration
  const current = () => epoch === generation && request === eventsGeneration
  eventsLoading.value = true; eventsError.value = ''
  try {
    const data = await listHookEvents(props.clientId, { ...appliedEventFilters.value, ...next, limit: 100 })
    if (!current()) return
    eventsPage.value = data
    const position = { ...next, snapshot_id: data.snapshot_id }
    if (navigation === 'reset') { eventHistory.value = [position]; eventIndex.value = 0 }
    else if (navigation === 'older') { eventHistory.value = [...eventHistory.value.slice(0, eventIndex.value + 1), position]; eventIndex.value++ }
    else if (navigation === 'newer') eventIndex.value--
  } catch (error) { if (current()) eventsError.value = failure(error, 'events.error') }
  finally { if (current()) eventsLoading.value = false }
}
async function loadRelated(record) {
  const epoch = generation, request = ++relatedGeneration
  const current = () => epoch === generation && request === relatedGeneration && eventDetailOpen.value && eventDetail.value?.id === record.id
  related.value = null; relatedError.value = ''; relatedLoading.value = true
  try { const data = await getHookEventRelations(props.clientId, record.id); if (current()) related.value = data }
  catch (error) { if (current()) relatedError.value = failure(error, 'events.relatedError') }
  finally { if (current()) relatedLoading.value = false }
}
function openEventDetail(record) {
  relatedGeneration++; related.value = null; relatedError.value = ''; relatedLoading.value = false
  eventDetail.value = record; eventDetailOpen.value = true
  if (canRelateHook.value) void loadRelated(record)
}
watch(eventDetailOpen, open => { if (!open) { relatedGeneration++; relatedLoading.value = false; related.value = null; relatedError.value = '' } })

async function publish() {
  if (saving.value || policyLoading.value || !dirty.value || !canEdit.value || policyError.value) return
  const rules = draft.value.rules
  if (rules.some(r => !/^[A-Za-z0-9_-]{1,64}$/.test(r.id) || r.id === 'default' || !r.tool || /\s/.test(r.tool)) || new Set(rules.map(r => r.id)).size !== rules.length) { actionError.value = t('aidr.hooks.invalid'); return }
  const epoch = generation
  saving.value = true; actionError.value = ''; saved.value = false
  try {
    const body = { ...draft.value, expected_revision: policy.value.revision }
    const data = await (props.global ? saveGlobalToolPolicy(body) : saveHookPolicy(props.clientId, { ...body, inherit: inherit.value, expected_global_revision: policy.value.global_revision, expected_scope_revision: policy.value.scope_revision }))
    if (epoch === generation) { applyPolicy(data); saved.value = true; reviewOpen.value = false }
  } catch (error) { if (epoch === generation) actionError.value = failure(error, 'actionError') }
  finally { if (epoch === generation) saving.value = false }
}
async function openDetail(id) {
  const epoch = generation, request = ++detailGeneration
  detailOpen.value = true; detailId.value = id; detailLoading.value = true; detailError.value = ''; actionError.value = ''; detail.value = null
  try { const data = await getHookApproval(props.clientId, id); if (epoch === generation && request === detailGeneration) detail.value = data }
  catch (error) { if (epoch === generation && request === detailGeneration) detailError.value = failure(error, 'detailError') }
  finally { if (epoch === generation && request === detailGeneration) detailLoading.value = false }
}
async function decide(action) {
  if (deciding.value || !actionAllowed.value) return
  const epoch = generation, request = detailGeneration, row = detail.value.approval
  const stillViewing = () => epoch === generation && request === detailGeneration && detailOpen.value && detailId.value === row.id
  const key = `${row.id}:${row.revision}:${action}`
  if (!requestIds.has(key)) requestIds.set(key, crypto.randomUUID().replaceAll('-', ''))
  invalidateList()
  deciding.value = true; actionError.value = ''
  try {
    await decideHookApproval(props.clientId, row.id, { request_id: requestIds.get(key), expected_revision: row.revision, decision: action })
    if (epoch === generation) {
      requestIds.delete(key)
      const refreshDetail = stillViewing() ? openDetail(row.id) : Promise.resolve()
      await Promise.all([refreshDetail, loadList()])
    }
  } catch (error) { if (stillViewing()) actionError.value = failure(error, 'actionError') }
  finally { if (epoch === generation) deciding.value = false }
}
watch(detailOpen, open => {
  if (!open) {
    detailGeneration++
    detail.value = null; detailId.value = ''; detailLoading.value = false; detailError.value = ''; actionError.value = ''
  }
})
watch(() => [props.clientId, props.view, props.fixedAgent], () => {
  clearTimeout(eventFilterTimer); eventsPending.value = false; resettingEventFilters = true; advancedFiltersOpen.value = false
  generation++; detailGeneration++; invalidateList(); requestIds.clear()
  lastSynced.value = 0; latestAvailable.value = false; latestHead = ''
  policy.value = null; page.value = { items: [], has_more: false }; cursor.value = null
  reviewOpen.value = false; baseline.value = ''
  eventsGeneration++; relatedGeneration++; relatedLoading.value = false; related.value = null; relatedError.value = ''
  eventsPage.value = { items: [], has_more: false }; eventHistory.value = [{}]; eventIndex.value = 0; eventFilters.value = emptyEventFilters(); appliedEventFilters.value = {}; eventsError.value = ''; eventsLoading.value = false
  resettingEventFilters = false
  eventDetailOpen.value = false; eventDetail.value = null
  detailOpen.value = false; detail.value = null; detailId.value = ''; detailLoading.value = false; detailError.value = ''; actionError.value = ''; policyError.value = ''; listError.value = ''
  policyLoading.value = false; listLoading.value = false; saving.value = false; deciding.value = false
  if (props.view === 'events') loadEvents()
  else if (props.view !== 'control') loadPolicy()
  else if (canSync.value) { loadPolicy(); syncApprovals() }
}, { immediate: true })
onBeforeUnmount(() => {
  generation++; detailGeneration++; eventsGeneration++; relatedGeneration++; invalidateList()
  clearInterval(timer); clearInterval(syncTimer); clearTimeout(eventFilterTimer)
  visibilityObserver?.disconnect()
  document.removeEventListener('visibilitychange', visibilityChanged)
})
</script>

<style scoped>
.scope-choice { display:flex; align-items:center; flex-wrap:wrap; gap:10px 16px; padding:12px; margin-bottom:16px; border-radius:8px; background:#f4f7fb; }
.scope-choice label { display:flex; align-items:center; gap:8px; font-weight:600; }.scope-choice small{width:100%;color:#738098}
.audit-detail { overflow-wrap: anywhere; }
.audit-detail-header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
.audit-detail-header h3 { margin: 0; font-size: 20px; }
.audit-record-fields { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px 16px; margin: 14px 0; }
.audit-record-fields dt { color: #667085; }
.audit-record-fields dd { margin: 0; }
@media (max-width: 560px) { .audit-record-fields { grid-template-columns: 1fr; gap: 4px; } .audit-record-fields dd { margin-bottom: 8px; } }

.hook-panel { min-width: 0; width: 100%; box-sizing: border-box; margin: 16px 0; padding: 16px; border: 1px solid #d9d9d9; border-radius: 8px; }
.hook-panel details { margin: 16px 0; }
.hook-panel.control-view { margin: 0; padding: 0; border: 0; }
.control-mode-note { margin: 8px 0 16px; color: #68768b; font-size: 13px; }
.scope-choice > label { flex-direction: row; align-items: center; margin: 0; }
.control-tabs { display:flex; gap:24px; border-bottom:1px solid #e4eaf2; }
.control-tabs button { border:0; background:transparent; padding:12px 0; font:inherit; cursor:pointer; color:#637189; border-bottom:3px solid transparent; }
.control-tabs button[aria-pressed=true] { color:#2860ed; border-bottom-color:#2860ed; font-weight:600; }
.control-tabs span { background:#f0f3f8; border-radius:4px; padding:2px 6px; font-size:12px; }
.control-note-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.control-note-row .control-mode-note { margin: 0; flex: 1; min-width: 200px; }
.control-rules .default-rule { display:flex; flex-wrap:wrap; align-items:center; gap:12px 20px; margin:16px 0; padding:12px 16px; background:#f3f7ff; border-radius:8px; }
.control-rules .default-rule label { display:flex; flex-direction:row; align-items:center; gap:16px; margin:0; font-weight:600; }
.default-rule span { font-size:13px; color:#68768b; }.default-rule .default-danger { color:#ba343e; }
.policy-footer { position:sticky; bottom:0; z-index:2; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; padding:14px 0; background:white; border-top:1px solid #e4eaf2; }
.policy-footer > span { font-size:13px; color:#68768b; }
.publish-review { list-style:none; padding:0; max-height:45vh; overflow:auto; }.publish-review li { display:flex; flex-wrap:wrap; gap:10px; justify-content:space-between; padding:12px 0; border-bottom:1px solid #e4eaf2; }.publish-review code { overflow-wrap:anywhere; }
.publish-review li>div{flex:1 1 200px;min-width:0}.publish-review code{display:block;font-size:12px;margin:5px 0}.publish-review small{color:#7a879e}.publish-review :deep(.ant-tag){align-self:flex-start}
.control-view .hook-context { margin: 8px 0; }
.control-intro { margin: 8px 0; color: #596579; font-size: 13px; }
.hook-heading, .hook-rule { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin: 12px 0; }
fieldset { border: 0; padding: 12px 0; }
fieldset label { display: inline-flex; flex-direction: column; gap: 6px; margin: 0 12px 12px 0; max-width: 100%; }
fieldset input, fieldset select { padding: 6px 8px; border: 1px solid #d9d9d9; border-radius: 6px; max-width: 100%; }
.hook-rule label { flex: 1; min-width: 120px; }
label { display: inline-flex; flex-direction: column; gap: 6px; margin: 8px 12px 8px 0; max-width: 100%; }
input, select { padding: 6px; max-width: 100%; }
code, dd { overflow-wrap: anywhere; word-break: break-word; }
dd { margin: 0 0 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 320px; overflow: auto; }
.hook-analysis { margin: 12px 0; overflow-wrap: anywhere; }
.hook-drift-entry { border-top: 1px solid #ddd; padding: 10px 0; }
.hook-panel h3 { font-size: 18px; margin: 0 0 12px; }
.hook-list-heading { justify-content: space-between; }
.hook-list-heading h4 { margin: 0; font-size: 16px; }
.hook-count { color: #627480; font-size: 12px; font-weight: 400; margin-left: 8px; }
.hook-muted, .hook-date small { color: #627480; font-size: 12px; }
.hook-context { padding: 8px 12px; background: #f5f7fa; border-radius: 6px; }
.hook-context summary { cursor: pointer; }
.hook-context p { margin: 8px 0 0; }
.hook-filters { margin: 12px 0; }
.hook-filter-main { display: grid; grid-template-columns: 100px minmax(140px, 1fr) minmax(180px, 1.4fr); gap: 12px; align-items: end; }
.hook-filter-actions { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.hook-filter-actions > div { display: flex; flex-wrap: wrap; margin-left: auto; }
.hook-filter-advanced { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 12px 0; border-top: 1px solid #edf0f2; }
.hook-filters label { display: flex; margin: 0; min-width: 0; font-size: 12px; }
.hook-filters select { width: 100%; height: 32px; box-sizing: border-box; border: 1px solid #d9d9d9; border-radius: 6px; background: #fff; }
.hook-filters select:focus-visible { outline: 2px solid #1c6ea4; outline-offset: 2px; }
.hook-filters :deep(.ant-select), .hook-filters :deep(.ant-input-affix-wrapper) { width: 100%; min-width: 0; }
.hook-table { min-width: 0; width: 100%; }
.hook-table :deep(.ant-table-cell) { vertical-align: top; overflow-wrap: anywhere; }
.hook-table :deep(.ant-tag) { max-width: 100%; white-space: normal; margin: 0; }
.hook-table :deep(.ant-table-body) { overscroll-behavior: contain; }
.hook-table :deep(.ant-table-cell-fix-right) { text-align: center; }
.hook-table :deep(.ant-table-cell-fix-right .ant-btn) { white-space: nowrap; padding-inline: 6px; height: 32px; }
.hook-id { display: inline-block; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: top; font-size: 12px; }
.hook-id:focus-visible { outline: 2px solid #1c6ea4; outline-offset: 2px; border-radius: 2px; }
.hook-date { display: block; white-space: nowrap; font-size: 12px; }
.hook-date small { display: block; }
.hook-line-clamp { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; margin: 0 0 4px; }
.hook-pagination { margin: 10px 0; }
@media (max-width: 540px) {
  .hook-panel { padding: 10px; margin: 12px 0; }
  .hook-filter-main { grid-template-columns: 90px minmax(0, 1fr); }
  .hook-filter-main label:last-child { grid-column: 1 / -1; }
  .hook-filter-advanced { grid-template-columns: minmax(0, 1fr); }
  .hook-panel :deep(.ant-btn) { height: auto; min-height: 32px; white-space: normal; }
}
</style>
