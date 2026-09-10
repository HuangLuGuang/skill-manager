<template>
  <section class="trace-page">
    <header class="trace-header">
      <div>
        <h1>{{ t('runtimeTraceExplorer.title') }}</h1>
      </div>
      <div class="trace-header-actions">
      <span class="header-session-count">{{ t('runtimeTraceExplorer.search.sessionsMatched', { count: total }) }}</span>
      <a-button :aria-expanded="searchOpen" aria-controls="trace-query" @click="searchOpen = !searchOpen">
        <template #icon><SearchOutlined /></template>
        {{ t('runtimeTraceExplorer.search.title') }}
      </a-button>
      <a-button :loading="loading || detailLoading" @click="refresh">
        <template #icon><ReloadOutlined /></template>
        {{ t('runtimeTraceExplorer.refresh') }}
      </a-button>
      </div>
    </header>

    <a-alert
      v-if="error"
      class="trace-alert"
      type="error"
      show-icon
      :message="t('runtimeTraceExplorer.loadFailed')"
      :description="error"
    />

    <form v-show="searchOpen" id="trace-query" class="trace-query-ribbon" @submit.prevent="applyTraceSearch">
      <div class="query-controls">
        <a-input
          v-model:value="searchDraft.turn_id"
          @pressEnter.prevent="applyTraceSearch"
          allow-clear
          :maxlength="128"
          :aria-label="t('runtimeTraceExplorer.search.turn')"
          :placeholder="t('runtimeTraceExplorer.search.turnPlaceholder')"
        />
        <a-input
          v-model:value="searchDraft.tool_name"
          @pressEnter.prevent="applyTraceSearch"
          allow-clear
          :maxlength="256"
          :aria-label="t('runtimeTraceExplorer.search.tool')"
          :placeholder="t('runtimeTraceExplorer.search.toolPlaceholder')"
        />
        <a-select
          v-model:value="searchDraft.risk_level"
          @change="applyTraceSearch"
          :aria-label="t('runtimeTraceExplorer.search.risk')"
          :title="t('runtimeTraceExplorer.search.boundary')"
          :options="riskSearchOptions"
        />
        <a-input
          v-model:value="searchDraft.request_id"
          @pressEnter.prevent="applyTraceSearch"
          allow-clear
          :maxlength="128"
          :aria-label="t('runtimeTraceExplorer.search.request')"
          :placeholder="t('runtimeTraceExplorer.search.requestPlaceholder')"
        />
        <label class="error-query-toggle">
          <a-switch v-model:checked="searchDraft.has_error" size="small" @change="applyTraceSearch" />
          <span>{{ t('runtimeTraceExplorer.search.errorsOnly') }}</span>
        </label>
        <a-range-picker
          v-model:value="searchDates"
          class="query-date-range"
          show-time
          format="YYYY-MM-DD HH:mm"
          value-format="YYYY-MM-DDTHH:mm:ss"
          :placeholder="[t('runtimeTraceExplorer.search.createdFrom'), t('runtimeTraceExplorer.search.createdTo')]"
          :title="t('runtimeTraceExplorer.search.beijingTime')"
          @change="applyDateSearch"
        />
        <div class="query-actions">
        <a-button type="primary" html-type="submit" :loading="loading">
          <template #icon><SearchOutlined /></template>
          {{ t('runtimeTraceExplorer.search.apply') }}
        </a-button>
        <a-button :disabled="!isSearchActive && !hasSearchDraft" @click="resetTraceSearch">{{ t('runtimeTraceExplorer.search.reset') }}</a-button>
        </div>
      </div>
      <div v-if="activeSearchEntries.length" class="query-ledger">
        <span class="query-ledger-label">{{ t('runtimeTraceExplorer.search.active') }}</span>
        <template v-if="activeSearchEntries.length">
          <button
            v-for="entry in activeSearchEntries"
            :key="entry.key"
            type="button"
            class="query-token"
            :aria-label="t('runtimeTraceExplorer.search.remove', { field: entry.label })"
            @click="removeTraceSearch(entry.key)"
          >
            <span>{{ entry.label }}</span><code>{{ entry.value }}</code><b aria-hidden="true">×</b>
          </button>
        </template>
        <span v-else>{{ t('runtimeTraceExplorer.search.none') }}</span>
      </div>
    </form>

    <div class="trace-workspace" :class="{ 'detail-visible': detailOpen }">
      <aside class="session-panel">
        <div class="panel-title">
          <div>
            <span>{{ t('runtimeTraceExplorer.sessions.title') }}</span>
            <small>{{ t('runtimeTraceExplorer.sessions.total', { total }) }}</small>
          </div>
          <span class="page-number">{{ page }}</span>
        </div>

        <a-spin :spinning="loading">
          <div v-if="traces.length" class="session-list">
            <button
              v-for="trace in traces"
              :key="trace.trace_id"
              type="button"
              class="session-item"
              :class="{ selected: trace.trace_id === selectedTraceId }"
              @click="selectTrace(trace)"
            >
              <span class="session-leading">
                <span class="session-pulse" />
                <strong>{{ traceTitle(trace) }}</strong>
              </span>
              <span v-if="trace.agent_id" class="session-subtitle">{{ trace.agent_id }}</span>
              <code class="session-id" :title="trace.session_id">{{ shortId(trace.session_id) }}</code>
              <span class="session-badges">
                <span v-if="trace.aggregation" class="trace-badge">{{ t(`runtimeTraceExplorer.aggregation.${trace.aggregation.method}`) }}</span>
                <span class="trace-badge" :class="`completeness-${completenessTone(trace.completeness)}`">
                  {{ completenessLabel(trace.completeness) }}
                </span>
                <span class="trace-badge" :class="`risk-${riskTone(trace.risk_level)}`">
                  {{ riskLevelLabel(trace.risk_level) }}
                </span>
              </span>
              <span class="session-meta">
                <span v-if="trace.aggregation">{{ t('runtimeTraceExplorer.aggregation.count', { count: trace.aggregation.request_count }) }}</span>
                <span v-else>{{ t('runtimeTraceExplorer.sessions.events', { count: trace.event_count || 0 }) }}</span>
                <time>{{ formatDateTime(trace.updated_at || trace.created_at) }}</time>
              </span>
            </button>
          </div>
          <a-empty v-else :description="isSearchActive ? t('runtimeTraceExplorer.search.noResults') : t('runtimeTraceExplorer.sessions.empty')" />
        </a-spin>

        <div v-if="total > pageSize" class="session-pagination">
          <a-button size="small" :disabled="page <= 1 || loading" @click="changePage(page - 1)">
            {{ t('runtimeTraceExplorer.previous') }}
          </a-button>
          <span>{{ t('runtimeTraceExplorer.page', { page, pages: totalPages }) }}</span>
          <a-button size="small" :disabled="page >= totalPages || loading" @click="changePage(page + 1)">
            {{ t('runtimeTraceExplorer.next') }}
          </a-button>
        </div>
      </aside>

      <main class="trace-stage">
        <a-spin :spinning="detailLoading">
          <template v-if="selectedTrace">
            <div class="stage-heading">
              <div class="trace-identity">
                <h2 :title="selectedTrace.trace_id">{{ traceTitle(selectedTrace) }}</h2>
                <span class="trace-subtitle">{{ selectedTraceSubtitle }}</span>
              </div>
              <div class="stage-actions">
                <a-button @click="openExportGate">
                  <template #icon><DownloadOutlined /></template>
                  {{ t('runtimeTraceExplorer.export.open') }}
                </a-button>
                <a-segmented v-model:value="activeView" :options="viewOptions" />
              </div>
            </div>

            <details class="trace-metadata">
              <summary>{{ t('runtimeTraceExplorer.stream.sessionDetails') }}</summary>
            <div class="trace-facts">
              <div>
                <small>{{ t('runtimeTraceExplorer.agent') }}</small>
                <strong>{{ selectedTrace.agent_id || t('runtimeTraceExplorer.agentUnavailable') }}</strong>
              </div>
              <div>
                <small>{{ t('runtimeTraceExplorer.eventCount') }}</small>
                <strong>{{ eventTotal }}</strong>
              </div>
              <div>
                <small>{{ t('runtimeTraceExplorer.status') }}</small>
                <strong>{{ statusLabel(selectedTrace.status) }}</strong>
              </div>
              <div>
                <small>{{ t('runtimeTraceExplorer.lastEvent') }}</small>
                <strong>{{ formatDateTime(selectedTrace.last_event_at || selectedTrace.updated_at) }}</strong>
              </div>
            </div>

            <details v-if="selectedTrace.aggregation" class="gateway-requests">
              <summary>{{ t(`runtimeTraceExplorer.aggregation.${selectedTrace.aggregation.method}`) }} · {{ t('runtimeTraceExplorer.aggregation.count', { count: selectedTrace.aggregation.request_count }) }}</summary>
              <div class="gateway-request-scroll">
                <table>
                  <thead><tr>
                    <th>{{ t('runtimeTraceExplorer.aggregation.request') }}</th>
                    <th>{{ t('runtimeTraceExplorer.status') }}</th>
                    <th>{{ t('runtimeTraceExplorer.aggregation.reason') }}</th>
                    <th>{{ t('runtimeTraceExplorer.aggregation.messages') }}</th>
                    <th>{{ t('runtimeTraceExplorer.aggregation.started') }}</th>
                  </tr></thead>
                  <tbody><tr v-for="item in gatewayRequests" :key="item.request_id">
                    <td><span :title="item.request_id">#{{ item.request_index }} <code>{{ item.request_id }}</code></span></td>
                    <td>{{ t(`runtimeTraceExplorer.aggregation.${item.status}`) }}</td>
                    <td>{{ t(`runtimeTraceExplorer.aggregation.${item.match_reason}`) }}<span v-if="item.matched_message_count" :title="item.matched_request_id"> ({{ item.matched_message_count }})</span></td>
                    <td>{{ item.message_count }}</td>
                    <td>{{ formatDateTime(item.created_at) }}</td>
                  </tr></tbody>
                </table>
              </div>
              <div class="session-pagination">
                <a-button size="small" :disabled="requestPage === 0 || requestsLoading" @click="changeRequestPage(-1)">{{ t('runtimeTraceExplorer.previous') }}</a-button>
                <a-button size="small" :disabled="!requestsHaveMore || requestsLoading" @click="changeRequestPage(1)">{{ t('runtimeTraceExplorer.next') }}</a-button>
              </div>
            </details>

            <details class="secondary-summary">
              <summary>{{ t('runtimeTraceExplorer.secondaryDetails') }}</summary>
            <section class="security-posture" aria-labelledby="trace-security-title">
              <div class="security-heading">
                <div>
                  <span class="trace-kicker">{{ t('runtimeTraceExplorer.securitySummary.eyebrow') }}</span>
                  <h3 id="trace-security-title">{{ t('runtimeTraceExplorer.securitySummary.title') }}</h3>
                </div>
                <div class="security-seals">
                  <span class="trace-badge" :class="`completeness-${completenessTone(securitySummary.completeness)}`">
                    {{ completenessLabel(securitySummary.completeness) }}
                  </span>
                  <span class="trace-badge" :class="`risk-${riskTone(securitySummary.riskLevel)}`">
                    {{ riskLevelLabel(securitySummary.riskLevel) }}
                  </span>
                </div>
              </div>
              <div class="governance-ledger">
                <article class="governance-cell risk-cell">
                  <span>{{ t('runtimeTraceExplorer.securitySummary.risk') }}</span>
                  <strong>{{ securitySummary.riskCodes.length }}</strong>
                  <small>{{ t('runtimeTraceExplorer.securitySummary.riskCodes', { count: securitySummary.riskCodes.length }) }}</small>
                  <div v-if="securitySummary.riskCodes.length" class="risk-code-preview">
                    <code v-for="code in securitySummary.riskCodes.slice(0, 2)" :key="code">{{ agenticRiskLabel(code, t, te) }}</code>
                    <code v-if="securitySummary.riskCodes.length > 2">+{{ securitySummary.riskCodes.length - 2 }}</code>
                  </div>
                </article>
                <article class="governance-cell approval-cell">
                  <span>{{ t('runtimeTraceExplorer.securitySummary.approvals') }}</span>
                  <strong>{{ securitySummary.approvals.pending }}</strong>
                  <small>{{ t('runtimeTraceExplorer.securitySummary.approvalMeta', securitySummary.approvals) }}</small>
                  <span v-if="securitySummary.approvals.denied" class="ledger-alert">
                    {{ t('runtimeTraceExplorer.securitySummary.denied', { count: securitySummary.approvals.denied }) }}
                  </span>
                </article>
                <article class="governance-cell blocked-cell">
                  <span>{{ t('runtimeTraceExplorer.securitySummary.blocked') }}</span>
                  <strong>{{ securitySummary.blocked }}</strong>
                  <small>{{ t('runtimeTraceExplorer.securitySummary.blockedMeta') }}</small>
                </article>
                <article class="governance-cell kill-cell" :class="{ observed: securitySummary.killSwitchObserved || securitySummary.killed }">
                  <span>{{ t('runtimeTraceExplorer.securitySummary.killSwitch') }}</span>
                  <strong>{{ securitySummary.killSwitchObserved ? t('runtimeTraceExplorer.securitySummary.observed') : t('runtimeTraceExplorer.securitySummary.notObserved') }}</strong>
                  <small>{{ t('runtimeTraceExplorer.securitySummary.killed', { count: securitySummary.killed }) }}</small>
                </article>
              </div>
              <p class="security-boundary">{{ t('runtimeTraceExplorer.securitySummary.scope', { loaded: events.length, total: eventTotal }) }}</p>
            </section>

            <section class="performance-panel" aria-labelledby="trace-performance-title">
              <div class="performance-heading">
                <div>
                  <span class="trace-kicker">{{ t('runtimeTraceExplorer.performance.eyebrow') }}</span>
                  <h3 id="trace-performance-title">{{ t('runtimeTraceExplorer.performance.title') }}</h3>
                </div>
                <p>{{ t('runtimeTraceExplorer.performance.scope', { loaded: events.length, total: eventTotal }) }}</p>
              </div>
              <div class="performance-grid">
                <article
                  v-for="metric in performanceMetrics"
                  :key="metric.key"
                  class="signal-card"
                  :style="{ '--signal-color': metric.color }"
                  :title="t(metric.helpKey)"
                >
                  <span class="signal-label"><i />{{ t(`runtimeTraceExplorer.performance.metrics.${metric.key}`) }}</span>
                  <strong :class="{ unavailable: metric.value === null }">{{ metric.display }}</strong>
                  <small>{{ metric.meta }}</small>
                </article>
              </div>
            </section>
            </details>
            </details>

            <TrajectoryStream
              :key="selectedTraceId"
              :rows="trajectoryRows"
              :mode="activeView"
              :selected-id="selectedNode?.id"
              @select="openTrajectoryNode"
              @load-more="loadMoreEvents"
            />

            <div v-if="eventTotal" class="event-pagination" aria-live="polite">
              <div>
                <strong>{{ t('runtimeTraceExplorer.pagination.title') }}</strong>
                <span>{{ t('runtimeTraceExplorer.pagination.progress', { loaded: events.length, total: eventTotal }) }}</span>
              </div>
              <a-button
                v-if="hasMoreEvents"
                size="small"
                :loading="eventsLoadingMore"
                @click="loadMoreEvents"
              >{{ t('runtimeTraceExplorer.pagination.loadMore') }}</a-button>
              <span v-else class="pagination-complete">{{ t('runtimeTraceExplorer.pagination.complete') }}</span>
            </div>
            <p class="privacy-note">{{ t('runtimeTraceExplorer.redactedNotice') }}</p>
          </template>

          <a-empty v-else class="stage-empty" :description="t('runtimeTraceExplorer.selectTrace')" />
        </a-spin>
      </main>
    <aside v-if="detailOpen" class="trace-detail-panel" :aria-label="t('runtimeTraceExplorer.detail.title')">
      <div class="detail-panel-heading">
        <strong>{{ t('runtimeTraceExplorer.detail.title') }}</strong>
        <a-tooltip :title="t('runtimeTraceExplorer.stream.close')"><a-button :aria-label="t('runtimeTraceExplorer.stream.close')" @click="detailOpen = false"><CloseOutlined /></a-button></a-tooltip>
      </div>
      <template v-if="selectedEvent">
        <div class="detail-event-heading">
          <div>
            <span>{{ t('runtimeTraceExplorer.detail.event') }} #{{ selectedEvent.seq }}</span>
            <strong>{{ selectedNode ? nodeLabel(selectedNode) : eventTypeLabel(selectedEvent.type) }}</strong>
            <code>{{ selectedEvent.event_id }}</code>
          </div>
          <span
            v-if="selectedNode ? selectedNode.status : selectedEvent.status"
            class="status-pill"
            :class="`status-${eventStatusTone(selectedNode ? selectedNode.status : selectedEvent.status)}`"
          >{{ eventStatusLabel(selectedNode ? selectedNode.status : selectedEvent.status) }}</span>
        </div>

        <span class="detail-boundary" :title="t('runtimeTraceExplorer.detail.redactedDescription')">
          {{ t('runtimeTraceExplorer.detail.redactedTitle') }}
        </span>

        <section v-if="!selectedNode" class="event-readable-summary">
          <div class="event-readable-heading">
            <strong>{{ eventTypeLabel(selectedEvent.type) }}</strong>
            <span v-if="eventReadableSummary.toolName">{{ eventReadableSummary.toolName }}</span>
            <span v-if="eventReadableSummary.model">{{ eventReadableSummary.model }}</span>
          </div>
          <p>{{ eventSummaryText(selectedEvent) || t('runtimeTraceExplorer.payloadUnavailable') }}</p>
          <a-space v-if="eventReadableSummary.riskCodes.length" wrap>
            <a-tag v-for="code in eventReadableSummary.riskCodes" :key="code">{{ agenticRiskLabel(code, t, te) }}</a-tag>
          </a-space>
        </section>

        <a-tabs v-model:active-key="activeDetailTab" class="detail-tabs">
          <a-tab-pane key="summary" :tab="t('runtimeTraceExplorer.detailTabs.summary')">
            <template v-if="selectedNode">
              <a-tag v-if="selectedNode.observed">{{ t('runtimeTraceExplorer.stream.observed') }}</a-tag>
              <pre class="json-panel readable-content">{{ readableProjection(selectedNode.content) }}</pre>
              <div class="node-evidence">
                <span>{{ t('runtimeTraceExplorer.stream.evidence') }}</span>
                <a-button v-for="event in selectedNode.events" :key="event.event_id" size="small" :type="selectedEvent.event_id === event.event_id ? 'primary' : 'default'" @click="selectEvidence(event)">#{{ event.seq }}</a-button>
              </div>
            </template>
            <details class="technical-details">
              <summary>{{ t('runtimeTraceExplorer.detail.technicalDetails') }}</summary>
            <dl class="detail-grid">
              <div v-for="(value, key) in detailSummary" :key="key">
                <dt>{{ detailFieldLabel(key) }}</dt>
                <dd><code>{{ displayDetailValue(value) }}</code></dd>
              </div>
            </dl>
            </details>
          </a-tab-pane>

          <a-tab-pane key="payload" :tab="t('runtimeTraceExplorer.detailTabs.payload')">
            <div class="projection-heading">
              <strong>{{ t('runtimeTraceExplorer.detail.payloadTitle') }}</strong>
              <span>{{ t('runtimeTraceExplorer.detail.redactedBadge') }}</span>
            </div>
            <pre v-if="selectedEvent.payload !== null && selectedEvent.payload !== undefined" class="json-panel">{{ jsonProjection(selectedEvent.payload) }}</pre>
            <a-empty v-else :description="t('runtimeTraceExplorer.detail.noPayload')" />
          </a-tab-pane>

          <a-tab-pane v-if="selectedNode && ['request', 'tool'].includes(selectedNode.kind)" key="arguments" :tab="t(selectedNode.kind === 'tool' ? 'runtimeTraceExplorer.stream.arguments' : 'runtimeTraceExplorer.stream.options')">
            <pre class="json-panel">{{ readableProjection(nodeArguments) }}</pre>
          </a-tab-pane>

          <a-tab-pane key="result" :tab="t('runtimeTraceExplorer.detailTabs.result')">
            <pre v-if="detailResult !== null" class="json-panel">{{ readableProjection(detailResult) }}</pre>
            <a-empty v-else :description="t('runtimeTraceExplorer.detail.noResult')" />
          </a-tab-pane>

          <a-tab-pane v-if="!selectedNode || ['request', 'tool', 'event'].includes(selectedNode.kind)" key="schema" :tab="t('runtimeTraceExplorer.detailTabs.schema')">
            <pre class="json-panel">{{ jsonProjection(detailSchema) }}</pre>
          </a-tab-pane>

          <a-tab-pane v-if="!selectedNode?.observed" key="timing" :tab="t('runtimeTraceExplorer.detailTabs.timing')">
            <dl class="detail-grid">
              <div v-for="(value, key) in detailTiming" :key="key">
                <dt>{{ detailFieldLabel(key) }}</dt>
                <dd><code>{{ displayDetailValue(value) }}</code></dd>
              </div>
            </dl>
            <p class="detail-footnote">{{ t('runtimeTraceExplorer.detail.timingBoundary') }}</p>
          </a-tab-pane>

          <a-tab-pane key="security" :tab="t('runtimeTraceExplorer.detailTabs.security')">
            <section class="finding-provenance" :aria-label="t('runtimeTraceExplorer.links.title')">
              <div class="provenance-heading">
                <div>
                  <span>{{ t('runtimeTraceExplorer.links.eyebrow') }}</span>
                  <strong>{{ t('runtimeTraceExplorer.links.title') }}</strong>
                </div>
                <a-tag>{{ t('runtimeTraceExplorer.links.count', { count: linkedFindings.length }) }}</a-tag>
              </div>
              <a-spin :spinning="linkedFindingsLoading">
                <a-alert
                  v-if="linkedFindingsError"
                  type="warning"
                  show-icon
                  :message="t('runtimeTraceExplorer.links.loadFailed')"
                  :description="linkedFindingsError"
                />
                <div v-else-if="linkedFindings.length" class="provenance-list">
                  <article v-for="finding in linkedFindings" :key="finding.finding_id" class="provenance-item">
                    <span class="provenance-node" aria-hidden="true" />
                    <div>
                      <span>{{ riskLevelLabel(finding.severity) }} · {{ findingSourceLabel(finding.source) }}</span>
                      <strong>{{ findingTitle(finding) }}</strong>
                      <code>{{ finding.finding_id }}</code>
                    </div>
                    <a-button type="link" size="small" @click="openLinkedFinding(finding)">
                      {{ t('runtimeTraceExplorer.links.openFinding') }}
                    </a-button>
                  </article>
                </div>
                <a-empty v-else :description="t('runtimeTraceExplorer.links.empty')" />
              </a-spin>
              <p :title="t('runtimeTraceExplorer.links.boundaryHelp')">{{ t('runtimeTraceExplorer.links.boundary') }}</p>
            </section>
            <div class="security-code-list">
              <span>{{ t('runtimeTraceExplorer.detail.riskCodes') }}</span>
              <a-space v-if="detailSecurity.risk_codes?.length" wrap>
                <a-tag v-for="code in detailSecurity.risk_codes" :key="code" :color="isAgenticRiskCode(code) ? 'blue' : undefined">{{ agenticRiskLabel(code, t, te) }}</a-tag>
              </a-space>
              <span v-else class="muted-detail">{{ t('runtimeTraceExplorer.detail.noRiskCodes') }}</span>
            </div>
            <pre class="json-panel">{{ jsonProjection(detailSecurity) }}</pre>
            <p class="detail-footnote">{{ t('runtimeTraceExplorer.detail.securityBoundary') }}</p>
          </a-tab-pane>
        </a-tabs>
      </template>
    </aside>
    </div>

    <a-modal
      v-model:open="exportGateOpen"
      class="trace-export-modal"
      width="660px"
      :title="t('runtimeTraceExplorer.export.title')"
      :ok-text="t('runtimeTraceExplorer.export.confirm')"
      :cancel-text="t('runtimeTraceExplorer.export.cancel')"
      :confirm-loading="exporting"
      :ok-button-props="{ disabled: !canSubmitExport }"
      :mask-closable="!exporting"
      @ok="submitTraceExport"
    >
      <div class="export-classification">
        <span>{{ t('runtimeTraceExplorer.export.eyebrow') }}</span>
        <strong>{{ t('runtimeTraceExplorer.export.boundaryTitle') }}</strong>
        <p>{{ t('runtimeTraceExplorer.export.boundary') }}</p>
      </div>

      <a-radio-group v-model:value="exportChoice" class="export-options">
        <a-radio value="redacted_json">
          <span class="export-option-copy">
            <strong>{{ t('runtimeTraceExplorer.export.redactedJson') }}</strong>
            <small>{{ t('runtimeTraceExplorer.export.redactedJsonHelp') }}</small>
          </span>
        </a-radio>
        <a-radio value="redacted_pdf">
          <span class="export-option-copy">
            <strong>{{ t('runtimeTraceExplorer.export.redactedPdf') }}</strong>
            <small>{{ t('runtimeTraceExplorer.export.redactedPdfHelp') }}</small>
          </span>
        </a-radio>
        <a-radio v-if="canRawExport" value="raw_json" class="raw-export-option">
          <span class="export-option-copy">
            <strong>{{ t('runtimeTraceExplorer.export.rawJson') }}</strong>
            <small>{{ t('runtimeTraceExplorer.export.rawJsonHelp') }}</small>
          </span>
        </a-radio>
      </a-radio-group>

      <div v-if="exportChoice === 'raw_json'" class="raw-export-gate">
        <a-alert
          type="warning"
          show-icon
          :message="t('runtimeTraceExplorer.export.rawWarningTitle')"
          :description="t('runtimeTraceExplorer.export.rawWarning')"
        />
        <label>
          <span>{{ t('runtimeTraceExplorer.export.password') }}</span>
          <a-input-password
            v-model:value="rawExportPassword"
            autocomplete="current-password"
            :placeholder="t('runtimeTraceExplorer.export.passwordPlaceholder')"
            @press-enter="submitTraceExport"
          />
        </label>
        <a-checkbox v-model:checked="rawExportAcknowledged">
          {{ t('runtimeTraceExplorer.export.acknowledge') }}
        </a-checkbox>
      </div>
      <a-alert
        v-else-if="!canRawExport"
        type="info"
        show-icon
        :message="t('runtimeTraceExplorer.export.rawUnavailable')"
        :description="t('runtimeTraceExplorer.export.rawUnavailableHelp')"
      />
      <a-alert v-if="exportError" class="export-error" type="error" show-icon :message="t('runtimeTraceExplorer.export.failed')" :description="exportError" />
    </a-modal>
  </section>
</template>

<script setup>
import { CloseOutlined, DownloadOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import TrajectoryStream from '../components/TrajectoryStream.vue'
import { buildTrajectoryRows } from '../trajectoryProjection'

import {
  authorizeRawRuntimeTraceExport,
  createRuntimeTraceExport,
  downloadRuntimeTraceExport,
  getMe,
  getRuntimeTrace,
  listRuntimeTraceRequests,
  listRuntimeTraceEvents,
  listRuntimeTraces,
  listSecurityFindingsForTraceEvent,
} from '../api'
import { agenticRiskLabel, isAgenticRiskCode } from '../agenticRiskTaxonomy'
import {
  eventResultProjection,
  eventSchemaProjection,
  eventSecurityProjection,
  eventStatusTone,
  eventSummaryProjection,
  eventTimingProjection,
  runtimeTraceEventSearchParams,
  runtimeTraceSearchParams,
  sortTraceEvents,
  tracePerformanceSummary,
  traceSecuritySummary,
  traceDisplayIdentity,
  eventDisplaySummary,
  eventSemanticSummary,
} from '../runtimeTraceView'

const { t, te, locale } = useI18n()
dayjs.extend(utc)
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const traces = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const selectedTraceId = ref('')
const selectedTraceDetail = ref(null)
const gatewayRequests = ref([])
const requestPage = ref(0)
const requestsHaveMore = ref(false)
const requestsLoading = ref(false)
let requestPageGeneration = 0
let liveTimer
let liveBusy = false

const refreshGatewayRequests = async () => {
  const traceId = selectedTraceId.value
  const generation = ++requestPageGeneration
  requestsLoading.value = true
  try {
    const result = await listRuntimeTraceRequests(traceId, { after_index: requestPage.value * 100, limit: 100 })
    if (traceId === selectedTraceId.value && generation === requestPageGeneration) {
      gatewayRequests.value = result.items || []
      requestsHaveMore.value = result.has_more === true
    }
  } finally {
    if (generation === requestPageGeneration) requestsLoading.value = false
  }
}
const changeRequestPage = async delta => {
  if (requestsLoading.value) return
  requestPage.value = Math.max(0, requestPage.value + delta)
  try { await refreshGatewayRequests() } catch (e) { error.value = errorMessage(e) }
}

const refreshLiveTrace = async () => {
  if (liveBusy || document.hidden || detailLoading.value || !selectedTrace.value?.aggregation) return
  liveBusy = true
  const traceId = selectedTraceId.value
  const generation = detailRequest
  try {
    const detail = await getRuntimeTrace(traceId)
    if (traceId !== selectedTraceId.value || generation !== detailRequest) return
    selectedTraceDetail.value = detail
    traces.value = traces.value.map(item => item.trace_id === traceId ? detail : item)
    await refreshGatewayRequests()
    if (traceId !== selectedTraceId.value || generation !== detailRequest || hasMoreEvents.value || eventsLoadingMore.value) return
    const result = await listRuntimeTraceEvents(traceId, {
      ...runtimeTraceEventSearchParams(activeSearch.value),
      after_seq: events.value.reduce((seq, item) => Math.max(seq, item.seq), 0), page_size: eventPageSize,
    })
    if (traceId !== selectedTraceId.value || generation !== detailRequest) return
    const known = new Set(events.value.map(item => item.event_id))
    const additions = (result.items || []).filter(item => !known.has(item.event_id))
    if (additions.length) events.value = sortTraceEvents([...events.value, ...additions])
    eventTotal.value = result.total || 0
    hasMoreEvents.value = result.has_more === true
    nextEventCursor.value = result.next_after_seq ?? null
  } catch (e) {
    if (traceId === selectedTraceId.value && generation === detailRequest) error.value = errorMessage(e)
  } finally { liveBusy = false }
}
const events = ref([])
const eventTotal = ref(0)
const eventPageSize = 200
const eventsLoadingMore = ref(false)
const hasMoreEvents = ref(false)
const nextEventCursor = ref(null)
const activeView = ref('trace')
const detailOpen = ref(false)
const selectedEvent = ref(null)
const selectedNodeId = ref(null)
const trajectoryRows = computed(() => buildTrajectoryRows(events.value))
const selectedNode = computed(() => trajectoryRows.value.find(row => row.id === selectedNodeId.value))
const nodeLabel = node => node.kind === 'request' ? t('runtimeTraceExplorer.stream.request', { number: node.number }) : t(`runtimeTraceExplorer.stream.roles.${node.kind}`)
const nodeArguments = computed(() => {
  if (selectedNode.value?.kind !== 'request') return selectedNode.value?.content
  const { messages: _messages, ...options } = selectedNode.value.content || {}
  return options
})
const readableProjection = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2)
const openTrajectoryNode = node => {
  openEventDetail(node.event)
  selectedNodeId.value = node.id
}
const selectEvidence = event => {
  selectedEvent.value = event
  loadLinkedFindings(event)
}
const activeDetailTab = ref('summary')
const linkedFindings = ref([])
const linkedFindingsLoading = ref(false)
const linkedFindingsError = ref('')
const searchDraft = reactive({ turn_id: '', tool_name: '', risk_level: 'all', has_error: false, request_id: '' })
const searchDates = ref(null)
const searchOpen = ref(false)
const activeSearch = ref({})
const currentUser = ref(null)
const exportGateOpen = ref(false)
const exportChoice = ref('redacted_json')
const rawExportPassword = ref('')
const rawExportAcknowledged = ref(false)
const exporting = ref(false)
const exportError = ref('')
let detailRequest = 0
let linkedFindingRequest = 0
let routeSyncRequest = 0
let listRequest = 0

const selectedTrace = computed(() => selectedTraceDetail.value
  || traces.value.find(item => item.trace_id === selectedTraceId.value)
  || null)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const isSearchActive = computed(() => Object.keys(activeSearch.value).length > 0)
const hasSearchDraft = computed(() => Object.keys(runtimeTraceSearchParams(searchDraft)).length > 0)
const canRawExport = computed(() => ['admin', 'super_admin', 'privacy_auditor'].includes(currentUser.value?.role))
const canSubmitExport = computed(() => Boolean(
  selectedTraceId.value
  && !exporting.value
  && (exportChoice.value !== 'raw_json' || (canRawExport.value && rawExportPassword.value && rawExportAcknowledged.value)),
))
const riskSearchOptions = computed(() => [
  { value: 'all', label: t('runtimeTraceExplorer.search.allRisks') },
  ...['critical', 'high', 'medium', 'low', 'info'].map(value => ({ value, label: riskLevelLabel(value) })),
])
const activeSearchEntries = computed(() => [
  ['turn_id', 'turn', activeSearch.value.turn_id],
  ['tool_name', 'tool', activeSearch.value.tool_name],
  ['risk_level', 'risk', activeSearch.value.risk_level ? riskLevelLabel(activeSearch.value.risk_level) : null],
  ['has_error', 'error', activeSearch.value.has_error ? t('runtimeTraceExplorer.search.errorValue') : null],
  ['request_id', 'request', activeSearch.value.request_id],
  ['created_from', 'createdFrom', activeSearch.value.created_from ? formatDateTime(activeSearch.value.created_from) : null],
  ['created_to', 'createdTo', activeSearch.value.created_to ? formatDateTime(activeSearch.value.created_to) : null],
].filter(([, , value]) => value).map(([key, labelKey, value]) => ({
  key, value, label: t(`runtimeTraceExplorer.search.${labelKey}`),
})))
const sortedEvents = computed(() => sortTraceEvents(events.value))
const detailSummary = computed(() => eventSummaryProjection(selectedEvent.value || {}))
const eventReadableSummary = computed(() => eventDisplaySummary(selectedEvent.value || {}))
const detailResult = computed(() => selectedNode.value?.result ?? eventResultProjection(selectedEvent.value || {}))
const detailSchema = computed(() => eventSchemaProjection(selectedEvent.value || {}))
const detailTiming = computed(() => eventTimingProjection(selectedNode.value?.events.at(-1) || selectedEvent.value || {}))
const detailSecurity = computed(() => eventSecurityProjection(selectedEvent.value || {}))
const performanceSummary = computed(() => tracePerformanceSummary(sortedEvents.value))
const securitySummary = computed(() => traceSecuritySummary(sortedEvents.value, selectedTrace.value || {}))
const performanceMetrics = computed(() => {
  const summary = performanceSummary.value
  const averageMeta = metric => metric.value === null
    ? t('runtimeTraceExplorer.performance.notCollected')
    : t('runtimeTraceExplorer.performance.averageSamples', { count: metric.samples })
  return [
    {
      key: 'tokens', color: '#3156a3', value: summary.tokens.value,
      display: summary.tokens.value === null ? t('runtimeTraceExplorer.performance.unavailable') : formatInteger(summary.tokens.value),
      meta: summary.tokens.value === null
        ? t('runtimeTraceExplorer.performance.notCollected')
        : t('runtimeTraceExplorer.performance.tokenSplit', { prompt: formatInteger(summary.tokens.prompt), completion: formatInteger(summary.tokens.completion) }),
      helpKey: 'runtimeTraceExplorer.performance.help.tokens',
    },
    {
      key: 'ttft', color: '#7857b8', value: summary.ttft.value,
      display: formatDurationMetric(summary.ttft.value), meta: summary.ttft.value === null ? t('runtimeTraceExplorer.performance.streamingOnly') : averageMeta(summary.ttft),
      helpKey: 'runtimeTraceExplorer.performance.help.ttft',
    },
    {
      key: 'model', color: '#a95f21', value: summary.model.value,
      display: formatDurationMetric(summary.model.value), meta: averageMeta(summary.model),
      helpKey: 'runtimeTraceExplorer.performance.help.model',
    },
    {
      key: 'platform', color: '#268578', value: summary.platform.value,
      display: formatDurationMetric(summary.platform.value), meta: averageMeta(summary.platform),
      helpKey: 'runtimeTraceExplorer.performance.help.platform',
    },
    {
      key: 'tool', color: '#9a486f', value: summary.tool.value,
      display: formatDurationMetric(summary.tool.value), meta: averageMeta(summary.tool),
      helpKey: 'runtimeTraceExplorer.performance.help.tool',
    },
  ]
})
const viewOptions = computed(() => [
  { label: t('runtimeTraceExplorer.views.conversation'), value: 'conversation' },
  { label: t('runtimeTraceExplorer.views.trace'), value: 'trace' },
])

const traceTitle = trace => {
  const identity = traceDisplayIdentity(trace)
  const key = `runtimeTraceExplorer.traceKinds.${identity.category}`
  return te(key) ? t(key, { id: identity.shortId }) : `${identity.category} · ${identity.shortId}`
}
const eventSummaryText = (event, maxLength = 220) => {
  const payload = event?.payload
  const hasSummary = [payload?.summary, payload?.title].some(value => typeof value === 'string' && value.trim())
  if (event?.type === 'security.finding' && !hasSummary && (payload?.finding_code || payload?.code) === 'llm_redteam.jailbreak_signal') {
    return t('agentSecurityScans.detail.findingTitles.jailbreakSignal')
  }
  return eventSemanticSummary(event, maxLength)
}
const selectedTraceSubtitle = computed(() => {
  if (selectedTrace.value?.agent_id) return selectedTrace.value.agent_id
  const model = sortedEvents.value.map(event => eventDisplaySummary(event).model).find(Boolean)
  return model || t('runtimeTraceExplorer.agentUnavailable')
})
const eventTypeLabel = value => {
  const key = `runtimeTraceExplorer.eventTypes.${String(value || '').replaceAll('.', '_')}`
  return te(key) ? t(key) : value || t('runtimeTraceExplorer.detail.unknownEvent')
}
const findingSourceLabel = value => ['ai-infra-guard', 'ai-infra-guard-mcp'].includes(value) ? t('runtimeTraceExplorer.links.scannerSource') : value
const findingTitle = finding => {
  if ((finding.finding_code || finding.code) === 'llm_redteam.jailbreak_signal') return t('agentSecurityScans.detail.findingTitles.jailbreakSignal')
  return finding.title
}

const errorMessage = requestError => requestError.response?.data?.detail || requestError.message || t('runtimeTraceExplorer.loadFailed')

const loadTracePage = async (preserveSelection = true) => {
  const requestId = ++listRequest
  loading.value = true
  error.value = ''
  try {
    const result = await listRuntimeTraces({ ...activeSearch.value, page: page.value, page_size: pageSize })
    if (requestId !== listRequest) return
    traces.value = result.items || []
    total.value = result.total || 0
    const selectedOnPage = traces.value.find(item => item.trace_id === selectedTraceId.value)
    const next = preserveSelection && selectedTraceId.value
      ? (selectedOnPage || { trace_id: selectedTraceId.value, session_id: selectedTrace.value?.session_id, agent_id: selectedTrace.value?.agent_id })
      : traces.value[0]
    if (next) await selectTrace(next)
    else {
      detailRequest += 1
      linkedFindingRequest += 1
      detailLoading.value = false
      linkedFindingsLoading.value = false
      selectedTraceId.value = ''
      selectedTraceDetail.value = null
      events.value = []
      eventTotal.value = 0
      selectedEvent.value = null
      detailOpen.value = false
    }
  } catch (requestError) {
    if (requestId === listRequest) error.value = errorMessage(requestError)
  } finally {
    if (requestId === listRequest) loading.value = false
  }
}

const selectTrace = async (trace) => {
  if (!trace?.trace_id) return
  selectedTraceId.value = trace.trace_id
  selectedTraceDetail.value = trace
  requestPage.value = 0
  gatewayRequests.value = []
  requestsHaveMore.value = false
  requestPageGeneration += 1
  detailOpen.value = false
  selectedEvent.value = null
  linkedFindings.value = []
  linkedFindingsError.value = ''
  events.value = []
  eventTotal.value = 0
  hasMoreEvents.value = false
  nextEventCursor.value = null
  detailLoading.value = true
  error.value = ''
  const requestId = ++detailRequest
  linkedFindingRequest += 1
  try {
    const [detail, eventResult] = await Promise.all([
      getRuntimeTrace(trace.trace_id),
      listRuntimeTraceEvents(trace.trace_id, {
        ...runtimeTraceEventSearchParams(activeSearch.value), page: 1, page_size: eventPageSize,
      }),
    ])
    if (requestId !== detailRequest) return
    selectedTraceDetail.value = detail
    events.value = eventResult.items || []
    eventTotal.value = eventResult.total || 0
    hasMoreEvents.value = eventResult.has_more === true
    nextEventCursor.value = eventResult.next_after_seq ?? null
    if (detail.aggregation) await refreshGatewayRequests()
  } catch (requestError) {
    if (requestId === detailRequest) error.value = errorMessage(requestError)
  } finally {
    if (requestId === detailRequest) detailLoading.value = false
  }
}

const loadMoreEvents = async () => {
  if (eventsLoadingMore.value || !hasMoreEvents.value || nextEventCursor.value === null || !selectedTraceId.value) return
  const traceId = selectedTraceId.value
  const requestId = detailRequest
  eventsLoadingMore.value = true
  error.value = ''
  try {
    const result = await listRuntimeTraceEvents(traceId, {
      ...runtimeTraceEventSearchParams(activeSearch.value),
      after_seq: nextEventCursor.value,
      page_size: eventPageSize,
    })
    if (selectedTraceId.value !== traceId || detailRequest !== requestId) return
    const known = new Set(events.value.map(event => event.event_id))
    const additions = (result.items || []).filter(event => !known.has(event.event_id))
    events.value = sortTraceEvents([...events.value, ...additions])
    eventTotal.value = result.total || 0
    hasMoreEvents.value = result.has_more === true
    nextEventCursor.value = result.next_after_seq ?? null
  } catch (requestError) {
    if (selectedTraceId.value === traceId && detailRequest === requestId) error.value = errorMessage(requestError)
  } finally {
    eventsLoadingMore.value = false
  }
}


const refresh = () => loadTracePage(true)
const changePage = (value) => {
  page.value = value
  loadTracePage(false)
}
const searchRouteQuery = () => Object.fromEntries(Object.entries(activeSearch.value).map(([key, value]) => [key, String(value)]))
const applyTraceSearch = async () => {
  activeSearch.value = runtimeTraceSearchParams(searchDraft)
  page.value = 1
  await router.replace({ name: 'runtime-traces', query: searchRouteQuery() })
  await loadTracePage(false)
}
const resetTraceSearch = async () => {
  searchDates.value = null
  searchDraft.created_from = ''
  searchDraft.created_to = ''
  Object.assign(searchDraft, { turn_id: '', tool_name: '', risk_level: 'all', has_error: false, request_id: '' })
  activeSearch.value = {}
  page.value = 1
  await router.replace({ name: 'runtime-traces', query: {} })
  await loadTracePage(false)
}
const removeTraceSearch = async key => {
  if (key === 'created_from' || key === 'created_to') {
    searchDates.value = null
    searchDraft.created_from = ''
    searchDraft.created_to = ''
  }
  if (key === 'risk_level') searchDraft.risk_level = 'all'
  else if (key === 'has_error') searchDraft.has_error = false
  else searchDraft[key] = ''
  await applyTraceSearch()
}

const applyDateSearch = () => {
  searchDraft.created_from = searchDates.value?.[0] ? `${searchDates.value[0]}+08:00` : ''
  searchDraft.created_to = searchDates.value?.[1] ? `${searchDates.value[1]}+08:00` : ''
  return applyTraceSearch()
}
const formatDateTime = (value) => value
  ? new Intl.DateTimeFormat(locale.value, { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`))
  : '—'
const formatInteger = value => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }).format(value || 0)
const formatDurationMetric = (value) => {
  if (value === null || value === undefined) return t('runtimeTraceExplorer.performance.unavailable')
  if (value >= 1000) return `${new Intl.NumberFormat(locale.value, { maximumFractionDigits: 2 }).format(value / 1000)} s`
  return `${new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(value)} ms`
}
const statusLabel = value => t(`runtimeTraceExplorer.statuses.${value || 'unknown'}`)
const completenessLabel = (value) => {
  const key = `runtimeTraceExplorer.completeness.${value || 'unknown'}`
  return te(key) ? t(key) : value
}
const completenessTone = value => value === 'full' ? 'full' : value === 'unknown' ? 'unknown' : 'partial'
const riskLevelLabel = (value) => {
  const key = `runtimeTraceExplorer.riskLevels.${value || 'info'}`
  return te(key) ? t(key) : value
}
const riskTone = value => ['critical', 'high', 'medium', 'low'].includes(value) ? value : 'info'
const shortId = value => value?.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
const eventStatusLabel = (value) => {
  const key = `runtimeTraceExplorer.statuses.${value || 'unknown'}`
  return te(key) ? t(key) : value
}
const loadLinkedFindings = async (event) => {
  const traceId = event?.trace_id || selectedTraceId.value
  if (!traceId || !event?.event_id) return
  const requestId = ++linkedFindingRequest
  linkedFindingsLoading.value = true
  linkedFindingsError.value = ''
  linkedFindings.value = []
  try {
    const result = await listSecurityFindingsForTraceEvent(traceId, event.event_id)
    if (requestId === linkedFindingRequest) linkedFindings.value = Array.isArray(result) ? result : []
  } catch (requestError) {
    if (requestId === linkedFindingRequest) linkedFindingsError.value = errorMessage(requestError)
  } finally {
    if (requestId === linkedFindingRequest) linkedFindingsLoading.value = false
  }
}
const openEventDetail = (event, tab = 'summary') => {
  selectedNodeId.value = null
  selectedEvent.value = event
  activeDetailTab.value = tab
  detailOpen.value = true
  loadLinkedFindings(event)
}
const openLinkedFinding = finding => router.push({
  name: 'agent-security-scans',
  query: { stage: 'findings', task_id: finding.task_id, finding_id: finding.finding_id },
})
const queryValue = value => Array.isArray(value) ? value[0] : value
const openEventFromRoute = async () => {
  const syncRequest = ++routeSyncRequest
  if (route.name !== 'runtime-traces') return
  const traceId = queryValue(route.query.trace_id)
  const eventId = queryValue(route.query.event_id)
  if (!traceId) return
  if (selectedTraceId.value !== traceId) await selectTrace({ trace_id: traceId })
  if (syncRequest !== routeSyncRequest || route.name !== 'runtime-traces') return
  if (!eventId) return
  let event = events.value.find(item => item.event_id === eventId)
  if (!event) {
    try {
      const result = await listRuntimeTraceEvents(traceId, { event_id: eventId, page: 1, page_size: 1 })
      event = result.items?.[0]
    } catch (requestError) {
      if (syncRequest === routeSyncRequest && route.name === 'runtime-traces' && selectedTraceId.value === traceId) error.value = errorMessage(requestError)
    }
  }
  if (syncRequest !== routeSyncRequest || route.name !== 'runtime-traces' || selectedTraceId.value !== traceId) return
  if (event) openEventDetail(event, 'security')
}
const detailFieldLabel = (key) => {
  const messageKey = `runtimeTraceExplorer.detailFields.${key}`
  return te(messageKey) ? t(messageKey) : key
}
const displayDetailValue = value => value === null || value === undefined || value === '' ? '—' : String(value)
const jsonProjection = value => JSON.stringify(value, null, 2)

const openExportGate = () => {
  exportChoice.value = 'redacted_json'
  rawExportPassword.value = ''
  rawExportAcknowledged.value = false
  exportError.value = ''
  exportGateOpen.value = true
}
const saveExportBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
const submitTraceExport = async () => {
  if (!canSubmitExport.value) return
  exporting.value = true
  exportError.value = ''
  try {
    const isRaw = exportChoice.value === 'raw_json'
    const format = exportChoice.value === 'redacted_pdf' ? 'pdf' : 'json'
    let rawAuthorizationToken
    if (isRaw) {
      const authorization = await authorizeRawRuntimeTraceExport(selectedTraceId.value, {
        password: rawExportPassword.value,
        acknowledge_sensitive_content: true,
      })
      rawAuthorizationToken = authorization.authorization_token
    }
    const result = await createRuntimeTraceExport(selectedTraceId.value, {
      redaction_level: isRaw ? 'raw' : 'redacted',
      format,
      language: locale.value,
      acknowledge_sensitive_content: isRaw,
      ...(rawAuthorizationToken ? { raw_authorization_token: rawAuthorizationToken } : {}),
    })
    const blob = await downloadRuntimeTraceExport(result.export_id)
    const sessionName = String(selectedTrace.value?.session_id || selectedTraceId.value).replace(/[^a-zA-Z0-9_-]+/g, '-').slice(0, 80)
    saveExportBlob(blob, `${sessionName}-${isRaw ? 'raw' : 'redacted'}.${format}`)
    exportGateOpen.value = false
    rawExportPassword.value = ''
    rawExportAcknowledged.value = false
    message.success(t('runtimeTraceExplorer.export.success'))
  } catch (requestError) {
    exportError.value = errorMessage(requestError)
  } finally {
    exporting.value = false
  }
}

onMounted(async () => {
  liveTimer = window.setInterval(refreshLiveTrace, 3000)
  Object.assign(searchDraft, {
    turn_id: queryValue(route.query.turn_id) || '',
    tool_name: queryValue(route.query.tool_name) || '',
    risk_level: queryValue(route.query.risk_level) || 'all',
    has_error: queryValue(route.query.has_error) === 'true',
    request_id: queryValue(route.query.request_id) || '',
    created_from: queryValue(route.query.created_from) || '',
    created_to: queryValue(route.query.created_to) || '',
  })
  activeSearch.value = runtimeTraceSearchParams(searchDraft)
  if (searchDraft.created_from && searchDraft.created_to) {
    searchDates.value = [searchDraft.created_from, searchDraft.created_to]
      .map(value => dayjs(value).utcOffset(480).format('YYYY-MM-DDTHH:mm:ss'))
  }
  searchOpen.value = isSearchActive.value
  const [profileResult] = await Promise.allSettled([getMe(), loadTracePage(false)])
  if (profileResult.status === 'fulfilled') currentUser.value = profileResult.value
  await openEventFromRoute()
})
watch(() => [route.name, route.query.trace_id, route.query.event_id], openEventFromRoute)
onBeforeUnmount(() => {
  window.clearInterval(liveTimer)
  detailRequest += 1
  requestPageGeneration += 1
})
</script>

<style scoped>
.gateway-requests { margin: 16px 0; border-block: 1px solid #e5e7eb; padding: 12px 0; }
.gateway-requests summary { cursor: pointer; font-weight: 600; }
.gateway-request-scroll { overflow-x: auto; max-height: 320px; margin-top: 12px; }
.gateway-requests table { width: 100%; min-width: 680px; border-collapse: collapse; font-size: 12px; }
.gateway-requests th, .gateway-requests td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #e5e7eb; }
.gateway-requests th { position: sticky; top: 0; background: #f9fafb; }
.gateway-requests td:first-child { max-width: 190px; }
.gateway-requests td:first-child span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gateway-requests code { font-size: 11px; }
.trace-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  width: 100%;
  min-width: 0;
  color: #172033;
}

.trace-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px 20px;
  min-height: 32px;
  margin-bottom: 12px;
}
.trace-header-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.header-session-count { margin-right: 4px; color: #667085; font-size: 12px; }

.eyebrow,
.trace-kicker {
  color: #3156a3;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
}

.trace-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  line-height: 32px;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.trace-header p,
.view-intro p {
  margin: 0;
  color: #667085;
}

.trace-alert { margin-bottom: 16px; flex-shrink: 0; max-height: 25%; overflow: auto; }

.trace-query-ribbon {
  flex-shrink: 0;
  max-height: 35%;
  margin-bottom: 12px;
  overflow: auto;
  overscroll-behavior: contain;
  border: 1px solid #d7dfeb;
  border-radius: 4px;
  background: #fff;
}
.query-controls { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); align-items: center; gap: 8px; padding: 11px 14px; border-top: 1px solid #e5eaf2; border-bottom: 1px solid #e5eaf2; }
.query-controls > * { min-width: 0; }
.query-date-range { grid-column: span 2; width: 100%; }
.query-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.error-query-toggle { display: flex; min-height: 32px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid #d9d9d9; border-radius: 6px; color: #4f5d72; background: #fafbfc; font-size: 12px; white-space: nowrap; cursor: pointer; }
.query-ledger { position: relative; display: flex; min-height: 42px; align-items: center; flex-wrap: wrap; gap: 7px; padding: 8px 14px 8px 28px; color: #788397; background: #fbfcfe; font-size: 11px; }
.query-ledger::before { position: absolute; top: 0; bottom: 0; left: 18px; border-left: 1px dashed #9aaccc; content: ''; }
.query-ledger-label { color: #4c6080; font-size: 10px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.query-token { display: inline-flex; min-width: 0; align-items: center; gap: 6px; padding: 4px 7px; border: 1px solid #bfcce1; border-radius: 6px; color: #2e4f87; background: #f2f6fd; cursor: pointer; }
.query-token span { color: #6a7890; font-size: 9px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.query-token code { max-width: 210px; overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.query-token b { color: #71819c; font-size: 13px; line-height: 1; }
.query-token:hover { border-color: #7895c6; background: #eaf1fc; }
.query-token:focus-visible { outline: 2px solid #3156a3; outline-offset: 2px; }
.trace-query-ribbon > p { margin: 0; padding: 8px 14px; border-top: 1px solid #e8ecf3; color: #7d8798; font-size: 10px; line-height: 1.5; }

.trace-workspace {
  flex: 1;
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  grid-template-columns: 210px minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
  border: 1px solid #dfe4ed;
  border-radius: 4px;
  background: #fff;
}
.trace-workspace.detail-visible { grid-template-columns: 210px minmax(0, 1fr) minmax(300px, 36%); }
.trace-metadata { margin-bottom: 12px; font-size: 12px; flex-shrink: 0; max-height: 35%; overflow: auto; overscroll-behavior: contain; }
.trace-metadata > summary { cursor: pointer; color: #69717c; padding: 6px 0; }
.trace-detail-panel { min-width: 0; min-height: 0; padding: 14px; border-left: 1px solid #dfe4ed; background: #fff; overflow: auto; overscroll-behavior: contain; }
.detail-panel-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 16px; font-size: 13px; }
.detail-panel-heading .ant-btn { width: 28px; height: 28px; padding: 0; }
.node-evidence { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 12px 0; font-size: 12px; }
.detail-event-heading code { overflow-wrap: anywhere; font-size: 10px; color: #7b8496; }

.session-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-right: 1px solid #dfe4ed;
  background: #fafbfc;
  min-height: 0;
  overflow: hidden;
}
.session-panel > :deep(.ant-spin-nested-loading),
.session-panel :deep(.ant-spin-container) { display: flex; flex-direction: column; min-height: 0; flex: 1; overflow: hidden; }

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 19px 18px 14px;
  border-bottom: 1px solid #dfe4ed;
}

.panel-title > div { display: grid; gap: 2px; }
.panel-title span { font-weight: 750; }
.panel-title small { color: #7b8496; }
.page-number {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid #cbd4e2;
  border-radius: 9px;
  background: #fff;
  color: #4b5870;
  font: 600 12px ui-monospace, SFMono-Regular, Menlo, monospace;
}

.session-list { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 8px; }
.session-item {
  display: grid;
  width: 100%;
  gap: 7px;
  padding: 13px 12px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: inherit;
  text-align: left;
  background: transparent;
  cursor: pointer;
  transition: background .18s ease, border-color .18s ease;
}

.session-item:hover { background: #f0f3f7; }
.session-item.selected { border-color: #cbd9eb; background: #edf3fa; }
.session-leading { display: flex; align-items: center; gap: 8px; min-width: 0; }
.session-leading strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-pulse { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: #3e68c2; box-shadow: 0 0 0 4px #e1e9fb; }
.session-item code { overflow: hidden; color: #68758b; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.session-badges { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 5px; }
.session-meta { display: flex; justify-content: space-between; gap: 8px; color: #8a93a2; font-size: 11px; }
.session-pagination { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; padding: 12px; border-top: 1px solid #dfe4ed; color: #667085; font-size: 11px; }

.trace-stage { min-width: 0; min-height: 0; padding: 14px; background: #fff; overflow: auto; overscroll-behavior: contain; }
.trace-stage > :deep(.ant-spin-nested-loading),
.trace-stage > :deep(.ant-spin-nested-loading > .ant-spin-container) { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.trace-stage :deep(.trajectory-stream) { flex: 1; min-height: 320px; }
.stage-heading, .event-pagination, .privacy-note { flex-shrink: 0; }
.stage-heading { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 8px; }
.stage-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 9px; }
.trace-identity { min-width: 0; }
.trace-identity h2 { margin: 0 0 2px; font-size: 18px; overflow-wrap: anywhere; }
.detail-visible .trace-identity { flex-basis: 100%; }
.trace-subtitle { display: block; color: #68758b; font-size: 11px; }
.trace-identity code { display: block; overflow: hidden; color: #7b8496; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }

.trace-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 20px 0;
  overflow: hidden;
  border: 1px solid #e5e8ef;
  border-radius: 12px;
  background: #e5e8ef;
}

.trace-facts > div { display: grid; gap: 5px; min-width: 0; padding: 13px 15px; background: #fafbfc; }
.trace-facts small { color: #7b8496; }
.trace-facts strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.session-subtitle { overflow: hidden; color: #68758b; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.secondary-summary { margin: 0 0 18px; border: 1px solid #d9dee8; border-radius: 12px; background: #fff; }
.secondary-summary > summary { padding: 11px 15px; color: #4c5a70; cursor: pointer; font-size: 12px; font-weight: 750; }
.secondary-summary[open] > summary { border-bottom: 1px solid #e3e7ee; }
.secondary-summary .security-posture,
.secondary-summary .performance-panel { margin: 0; border: 0; border-radius: 0; box-shadow: none; }

.trace-badge {
  display: inline-flex;
  min-height: 21px;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid #cbd4e2;
  border-radius: 999px;
  color: #596579;
  background: #f6f8fb;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .025em;
  line-height: 1.2;
}
.completeness-full { border-color: #8bcdb0; color: #24744b; background: #eefaf4; }
.completeness-partial { border-color: #e6c98d; color: #8a5c12; background: #fff9e9; }
.completeness-unknown { color: #68758b; background: #f3f5f8; }
.risk-critical,
.risk-high { border-color: #e6a4aa; color: #a13a45; background: #fff1f2; }
.risk-medium { border-color: #e9c071; color: #875612; background: #fff7e6; }
.risk-low { border-color: #a5c8df; color: #296381; background: #edf7fc; }
.risk-info { border-color: #c7d0dc; color: #657086; background: #f3f5f8; }

.security-posture {
  margin: 0 0 18px;
  overflow: hidden;
  overflow-wrap: anywhere;
  border: 1px solid #d9dee8;
  border-left: 4px solid #9a486f;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 7px 22px rgba(75, 35, 62, .055);
}
.security-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; padding: 14px 16px 11px; background: linear-gradient(105deg, #fff8fb 0%, #fff 58%); }
.security-heading h3 { margin: 3px 0 0; font-size: 15px; }
.security-seals { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.governance-ledger { display: grid; grid-template-columns: 1.15fr 1.2fr .8fr 1.15fr; border-top: 1px solid #e3e7ee; border-bottom: 1px solid #e3e7ee; background: #e3e7ee; gap: 1px; }
.governance-cell { position: relative; display: grid; min-width: 0; align-content: start; gap: 4px; padding: 13px 14px 14px; background: #fff; }
.governance-cell > span:first-child { color: #6d7789; font-size: 10px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
.governance-cell > strong { color: #25344d; font: 780 21px ui-monospace, SFMono-Regular, Menlo, monospace; }
.governance-cell > small { min-height: 31px; color: #7a8598; font-size: 10px; line-height: 1.5; }
.risk-code-preview { display: flex; min-width: 0; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
.risk-code-preview code { max-width: 100%; overflow: hidden; padding: 2px 5px; border-radius: 4px; color: #804261; background: #faedf3; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.ledger-alert { width: fit-content; padding: 2px 6px; border-radius: 5px; color: #9b3643; background: #fff0f1; font-size: 9px; font-weight: 750; }
.kill-cell > strong { font-size: 14px; }
.kill-cell.observed { background: #fff4f5; box-shadow: inset 0 3px #bb3e4d; }
.kill-cell.observed > strong { color: #a73543; }
.security-boundary { margin: 0; padding: 9px 16px 10px; color: #7a8598; background: #fafbfc; font-size: 10px; line-height: 1.5; }

.performance-panel {
  margin: 0 0 24px;
  overflow: hidden;
  border: 1px solid #dfe4ed;
  border-radius: 14px;
  background: #f8fafc;
}
.performance-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; padding: 15px 17px 12px; border-bottom: 1px solid #e2e7ef; }
.performance-heading h3 { margin: 3px 0 0; font-size: 15px; }
.performance-heading p { max-width: 540px; margin: 0; color: #7b8496; font-size: 11px; text-align: right; }
.performance-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); background: #e3e8f0; gap: 1px; }
.signal-card { position: relative; display: grid; min-width: 0; gap: 5px; padding: 13px 14px 14px; background: #fff; }
.signal-card::before { position: absolute; top: 0; right: 0; left: 0; height: 2px; background: var(--signal-color); content: ''; }
.signal-label { display: flex; align-items: center; gap: 7px; color: #657086; font-size: 10px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.signal-label i { width: 6px; height: 6px; border-radius: 2px; background: var(--signal-color); }
.signal-card strong { overflow: hidden; color: #1e2e49; font: 750 clamp(17px, 2vw, 22px) ui-monospace, SFMono-Regular, Menlo, monospace; text-overflow: ellipsis; white-space: nowrap; }
.signal-card strong.unavailable { color: #a0a8b5; font-size: 15px; }
.signal-card small { overflow: hidden; color: #8a93a2; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }

.status-pill { display: inline-flex; width: fit-content; flex: 0 0 auto; padding: 2px 6px; border: 1px solid transparent; border-radius: 999px; font-size: 9px; font-weight: 750; text-transform: none; }
.status-success { border-color: #9ad6b7; color: #217a4a; background: #effaf4; }
.status-active { border-color: #a9c4ea; color: #315f9d; background: #f0f6ff; }
.status-danger { border-color: #e6acb1; color: #a43c47; background: #fff2f3; }
.status-neutral { border-color: #ccd3de; color: #667085; background: #f5f6f8; }

.detail-event-heading { display: grid; gap: 5px; padding-bottom: 14px; }
.detail-event-heading > div { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.detail-event-heading > div > span:first-child { color: #3156a3; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.detail-event-heading strong { font: 750 16px ui-monospace, SFMono-Regular, Menlo, monospace; }
.detail-event-heading > code { overflow: hidden; color: #7b8496; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.detail-boundary { display: inline-block; margin-bottom: 10px; color: #7b8496; font-size: 10px; cursor: help; }
.event-readable-summary { margin-bottom: 14px; padding-block: 10px; border-bottom: 1px solid #dfe5ef; }
.event-readable-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.event-readable-heading strong { color: #26364f; font-size: 14px; }
.event-readable-heading span { color: #68758b; font-size: 11px; }
.event-readable-summary p { margin: 7px 0 0; color: #34425a; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.technical-details { margin-top: 2px; }
.technical-details > summary { margin-bottom: 10px; color: #68758b; cursor: pointer; font-size: 11px; font-weight: 700; }
.detail-tabs { margin-top: 6px; }
.detail-grid { display: grid; grid-template-columns: 1fr; gap: 0; margin: 0; }
.detail-grid > div { min-width: 0; padding: 8px 0; border-bottom: 1px solid #e1e6ee; }
.detail-grid dt { margin-bottom: 5px; color: #7b8496; font-size: 11px; }
.detail-grid dd { margin: 0; color: #26364f; overflow-wrap: anywhere; }
.detail-grid code { font-size: 12px; }
.projection-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.projection-heading span { padding: 3px 8px; border-radius: 999px; color: #315f9d; background: #edf4ff; font-size: 10px; font-weight: 700; }
.json-panel { max-height: calc(100vh - 290px); margin: 0; overflow: auto; padding: 12px; border: 1px solid #e4e7eb; border-radius: 4px; color: #303640; background: #fafbfc; font: 12px/1.7 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.readable-content { font-family: inherit; background: #fff; border: 0; padding: 0; }
.security-code-list { display: grid; gap: 8px; margin-bottom: 12px; }
.security-code-list > span:first-child { color: #596579; font-size: 11px; font-weight: 750; text-transform: uppercase; }
.finding-provenance { margin-bottom: 16px; overflow: hidden; border: 1px solid #dfe5ef; border-radius: 12px; background: #fbfcfe; }
.finding-provenance > p { margin: 0; padding: 9px 14px; border-top: 1px solid #e7ebf2; color: #768196; font-size: 11px; line-height: 1.5; }
.provenance-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-bottom: 1px solid #e7ebf2; background: linear-gradient(110deg, #f5f8ff, #fff); }
.provenance-heading > div { display: grid; gap: 2px; }
.provenance-heading span { color: #4568a9; font-size: 10px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.provenance-heading strong { color: #27364f; font-size: 14px; }
.provenance-list { position: relative; display: grid; padding: 8px 12px 8px 30px; }
.provenance-list::before { position: absolute; top: 0; bottom: 0; left: 19px; border-left: 1px dashed #9eb0ce; content: ''; }
.provenance-item { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 10px 4px; border-bottom: 1px solid #edf0f5; }
.provenance-item:last-child { border-bottom: 0; }
.provenance-node { position: absolute; left: -17px; width: 9px; height: 9px; border: 2px solid #fff; border-radius: 50%; background: #315fae; box-shadow: 0 0 0 1px #9eb0ce; }
.provenance-item > div { display: grid; min-width: 0; gap: 2px; }
.provenance-item span { color: #748097; font-size: 10px; }
.provenance-item strong { overflow: hidden; color: #27364f; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.provenance-item code { overflow: hidden; color: #778399; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.muted-detail,
.detail-footnote { color: #7b8496; font-size: 11px; }
.detail-footnote { margin: 12px 2px 0; line-height: 1.6; }

.privacy-note { margin: 14px 2px 0; color: #8a93a2; font-size: 11px; }
.event-pagination { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 16px; padding: 11px 13px; border: 1px solid #dfe4ed; border-radius: 11px; background: #f8fafc; }
.event-pagination > div { display: grid; gap: 2px; }
.event-pagination strong { color: #34425a; font-size: 12px; }
.event-pagination span { color: #7b8496; font-size: 11px; }
.pagination-complete { color: #28724d !important; font-weight: 700; }

.export-classification { margin-bottom: 16px; padding: 14px 16px; border: 1px solid #cfd8e8; border-left: 4px solid #3156a3; border-radius: 10px; background: #f6f8fc; }
.export-classification > span { color: #3156a3; font: 800 9px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .12em; }
.export-classification > strong { display: block; margin-top: 4px; color: #26364f; font-size: 14px; }
.export-classification > p { margin: 5px 0 0; color: #68758b; font-size: 11px; line-height: 1.6; }
.export-options { display: grid; gap: 8px; width: 100%; }
.export-options :deep(.ant-radio-wrapper) { display: flex; min-height: 64px; align-items: flex-start; margin: 0; padding: 11px 13px; border: 1px solid #dce2eb; border-radius: 10px; background: #fff; transition: border-color .16s ease, box-shadow .16s ease; }
.export-options :deep(.ant-radio-wrapper:hover),
.export-options :deep(.ant-radio-wrapper-checked) { border-color: #87a2d5; box-shadow: 0 0 0 2px rgba(49, 86, 163, .09); }
.export-options :deep(.ant-radio) { margin-top: 2px; }
.export-option-copy { display: grid; gap: 3px; padding-left: 4px; }
.export-option-copy strong { color: #2c3b54; font-size: 13px; }
.export-option-copy small { color: #738096; font-size: 10.5px; line-height: 1.5; }
.export-options :deep(.raw-export-option) { border-color: #ead1b2; background: #fffaf3; }
.export-options :deep(.raw-export-option.ant-radio-wrapper-checked) { border-color: #c68638; box-shadow: 0 0 0 2px rgba(177, 104, 27, .1); }
.raw-export-gate { display: grid; gap: 13px; margin-top: 14px; padding-top: 14px; border-top: 1px solid #e2e6ed; }
.raw-export-gate label { display: grid; gap: 6px; color: #4c5a70; font-size: 11px; font-weight: 700; }
.export-error { margin-top: 14px; }
.stage-empty { margin-top: 170px; }

@media (max-width: 1100px) {
  .query-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .error-query-toggle { justify-content: center; }
  .trace-workspace, .trace-workspace.detail-visible { grid-template-columns: 1fr; grid-template-rows: minmax(0, 200px) minmax(0, 1fr); }
  .trace-detail-panel { position: fixed; inset: 56px 0 0 auto; width: min(440px, 100%); max-height: none; z-index: 100; box-shadow: -8px 0 24px #17203318; }
  .session-panel { border-right: 0; border-bottom: 1px solid #dfe4ed; }
  .session-list { display: grid; align-content: start; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .governance-ledger { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .performance-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 680px) {
  .trace-header-actions { gap: 6px; }
  .header-session-count { margin-right: 0; font-size: 11px; }
  .trace-header,
  .stage-heading,
  .view-intro { align-items: stretch; flex-direction: column; }
  .stage-actions { align-items: stretch; flex-direction: column-reverse; }
  .stage-actions :deep(.ant-btn) { width: 100%; }
  .trace-stage { padding: 16px; }
  .trace-header p,
  .conversation-view .view-intro p { display: none; }
  .query-controls { grid-template-columns: 1fr; }
  .query-date-range { grid-column: span 1; }
  .query-controls :deep(.ant-btn) { width: 100%; }
  .query-ledger { align-items: flex-start; flex-direction: column; padding-left: 30px; }
  .query-token { max-width: 100%; }
  .session-list { grid-template-columns: 1fr; }
  .session-id { display: none; }
  .trace-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .trace-facts strong { white-space: normal; overflow-wrap: anywhere; }
  .security-heading { align-items: flex-start; flex-direction: column; }
  .security-seals { justify-content: flex-start; }
  .governance-ledger { grid-template-columns: 1fr; }
  .performance-heading { align-items: flex-start; flex-direction: column; }
  .performance-heading p { text-align: left; }
  .performance-grid { grid-template-columns: 1fr 1fr; }
  .detail-grid { grid-template-columns: 1fr; }
  .event-pagination { align-items: stretch; flex-direction: column; }
  .event-pagination :deep(.ant-btn) { width: 100%; }
}
</style>
