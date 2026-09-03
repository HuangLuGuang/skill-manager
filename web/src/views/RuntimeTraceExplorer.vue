<template>
  <section class="trace-page">
    <header class="trace-header">
      <div>
        <div class="eyebrow">{{ t('runtimeTraceExplorer.eyebrow') }}</div>
        <h1>{{ t('runtimeTraceExplorer.title') }}</h1>
        <p>{{ t('runtimeTraceExplorer.subtitle') }}</p>
      </div>
      <a-button :loading="loading || detailLoading" @click="refresh">
        <template #icon><ReloadOutlined /></template>
        {{ t('runtimeTraceExplorer.refresh') }}
      </a-button>
    </header>

    <a-alert
      v-if="error"
      class="trace-alert"
      type="error"
      show-icon
      :message="t('runtimeTraceExplorer.loadFailed')"
      :description="error"
    />

    <form class="trace-query-ribbon" @submit.prevent="applyTraceSearch">
      <div class="query-ribbon-heading">
        <div>
          <span class="trace-kicker">{{ t('runtimeTraceExplorer.search.eyebrow') }}</span>
          <strong>{{ t('runtimeTraceExplorer.search.title') }}</strong>
          <small>{{ t('runtimeTraceExplorer.search.description') }}</small>
        </div>
        <span class="query-result-count">{{ t('runtimeTraceExplorer.search.sessionsMatched', { count: total }) }}</span>
      </div>
      <div class="query-controls">
        <a-input
          v-model:value="searchDraft.turn_id"
          allow-clear
          :maxlength="128"
          :aria-label="t('runtimeTraceExplorer.search.turn')"
          :placeholder="t('runtimeTraceExplorer.search.turnPlaceholder')"
        />
        <a-input
          v-model:value="searchDraft.tool_name"
          allow-clear
          :maxlength="256"
          :aria-label="t('runtimeTraceExplorer.search.tool')"
          :placeholder="t('runtimeTraceExplorer.search.toolPlaceholder')"
        />
        <a-select
          v-model:value="searchDraft.risk_level"
          :aria-label="t('runtimeTraceExplorer.search.risk')"
          :options="riskSearchOptions"
        />
        <a-input
          v-model:value="searchDraft.request_id"
          allow-clear
          :maxlength="128"
          :aria-label="t('runtimeTraceExplorer.search.request')"
          :placeholder="t('runtimeTraceExplorer.search.requestPlaceholder')"
        />
        <label class="error-query-toggle">
          <a-switch v-model:checked="searchDraft.has_error" size="small" />
          <span>{{ t('runtimeTraceExplorer.search.errorsOnly') }}</span>
        </label>
        <a-button type="primary" html-type="submit" :loading="loading">
          <template #icon><SearchOutlined /></template>
          {{ t('runtimeTraceExplorer.search.apply') }}
        </a-button>
        <a-button :disabled="!isSearchActive && !hasSearchDraft" @click="resetTraceSearch">{{ t('runtimeTraceExplorer.search.reset') }}</a-button>
      </div>
      <div class="query-ledger" :class="{ empty: !activeSearchEntries.length }">
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
      <p>{{ isSearchActive ? t('runtimeTraceExplorer.search.filteredBoundary') : t('runtimeTraceExplorer.search.boundary') }}</p>
    </form>

    <div class="trace-workspace">
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
                <strong>{{ trace.session_id }}</strong>
              </span>
              <code>{{ trace.agent_id }}</code>
              <span class="session-badges">
                <span class="trace-badge" :class="`completeness-${completenessTone(trace.completeness)}`">
                  {{ completenessLabel(trace.completeness) }}
                </span>
                <span class="trace-badge" :class="`risk-${riskTone(trace.risk_level)}`">
                  {{ riskLevelLabel(trace.risk_level) }}
                </span>
              </span>
              <span class="session-meta">
                <span>{{ t('runtimeTraceExplorer.sessions.events', { count: trace.event_count || 0 }) }}</span>
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
                <span class="trace-kicker">{{ t('runtimeTraceExplorer.traceLabel') }}</span>
                <h2>{{ selectedTrace.session_id }}</h2>
                <code>{{ selectedTrace.trace_id }}</code>
              </div>
              <div class="stage-actions">
                <a-button @click="openExportGate">
                  <template #icon><DownloadOutlined /></template>
                  {{ t('runtimeTraceExplorer.export.open') }}
                </a-button>
                <a-segmented v-model:value="activeView" :options="viewOptions" />
              </div>
            </div>

            <div class="trace-facts">
              <div>
                <small>{{ t('runtimeTraceExplorer.agent') }}</small>
                <strong>{{ selectedTrace.agent_id }}</strong>
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

            <section v-if="activeView === 'conversation'" class="conversation-view">
              <div class="view-intro">
                <div>
                  <h3>{{ t('runtimeTraceExplorer.conversation.title') }}</h3>
                  <p>{{ t('runtimeTraceExplorer.conversation.description') }}</p>
                </div>
                <span>{{ t('runtimeTraceExplorer.conversation.count', { count: conversationEvents.length }) }}</span>
              </div>

              <div
                v-if="conversationEvents.length"
                class="conversation-stream"
                tabindex="0"
                :aria-label="t('runtimeTraceExplorer.pagination.conversationRegion')"
                @scroll="handleConversationScroll"
              >
                <div aria-hidden="true" :style="{ height: `${conversationWindow.topPadding}px` }" />
                <article
                  v-for="event in conversationWindow.items"
                  :key="event.event_id"
                  class="message-row"
                  :class="[conversationRole(event), { selected: event.event_id === selectedEvent?.event_id }]"
                  role="button"
                  tabindex="0"
                  @click="openEventDetail(event)"
                  @keydown.enter="openEventDetail(event)"
                  @keydown.space.prevent="openEventDetail(event)"
                >
                  <div class="message-meta">
                    <span>{{ conversationRoleLabel(event) }}</span>
                    <code>#{{ event.seq }}</code>
                    <time>{{ formatEventTime(event.event_time) }}</time>
                  </div>
                  <div class="message-bubble">
                    {{ payloadPreview(event.payload, 1200) || t('runtimeTraceExplorer.payloadUnavailable') }}
                  </div>
                </article>
                <div aria-hidden="true" :style="{ height: `${conversationWindow.bottomPadding}px` }" />
              </div>
              <a-empty v-else :description="isEventSearchActive ? t('runtimeTraceExplorer.search.noEventResults') : t('runtimeTraceExplorer.conversation.empty')" />
            </section>

            <section v-else class="timeline-view">
              <div class="view-intro">
                <div>
                  <h3>{{ t('runtimeTraceExplorer.timeline.title') }}</h3>
                  <p>{{ t('runtimeTraceExplorer.timeline.description') }}</p>
                </div>
                <span>{{ t('runtimeTraceExplorer.timeline.serverOrder') }}</span>
              </div>

              <div
                v-if="sortedEvents.length"
                class="rail-scroll"
                tabindex="0"
                :aria-label="t('runtimeTraceExplorer.pagination.traceRegion')"
                @scroll="handleTraceScroll"
              >
                <div class="trace-rail">
                  <div class="rail-header">
                    <span class="seq-heading">{{ t('runtimeTraceExplorer.timeline.sequence') }}</span>
                    <span class="time-heading">{{ t('runtimeTraceExplorer.timeline.time') }}</span>
                    <span v-for="lane in TRACE_LANES" :key="lane" class="lane-heading" :class="`lane-${lane}`">
                      <i />{{ t(`runtimeTraceExplorer.lanes.${lane}`) }}
                    </span>
                  </div>
                  <div class="virtual-spacer" aria-hidden="true" :style="{ height: `${timelineWindow.topPadding}px` }" />
                  <div v-for="turn in traceGroups" :key="turn.key" class="turn-group">
                    <button
                      type="button"
                      class="group-bar turn-bar"
                      :aria-expanded="!collapsedTurns.has(turn.key)"
                      @click="toggleTurn(turn.key)"
                    >
                      <DownOutlined v-if="!collapsedTurns.has(turn.key)" />
                      <RightOutlined v-else />
                      <span class="group-kind">{{ turn.isUnscoped ? t('runtimeTraceExplorer.hierarchy.unscoped') : t('runtimeTraceExplorer.hierarchy.turn') }}</span>
                      <strong>{{ turnLabel(turn) }}</strong>
                      <code>{{ seqRange(turn) }}</code>
                      <span>{{ t('runtimeTraceExplorer.hierarchy.events', { count: turn.eventCount }) }}</span>
                    </button>

                    <template v-if="!collapsedTurns.has(turn.key)">
                      <div v-for="step in turn.steps" :key="step.key" class="step-group">
                        <button
                          type="button"
                          class="group-bar step-bar"
                          :aria-expanded="!collapsedSteps.has(step.key)"
                          @click="toggleStep(step.key)"
                        >
                          <DownOutlined v-if="!collapsedSteps.has(step.key)" />
                          <RightOutlined v-else />
                          <span class="group-kind">{{ step.isUnscoped ? t('runtimeTraceExplorer.hierarchy.direct') : t('runtimeTraceExplorer.hierarchy.step') }}</span>
                          <strong>{{ stepLabel(step) }}</strong>
                          <code>{{ seqRange(step) }}</code>
                          <span>{{ t('runtimeTraceExplorer.hierarchy.events', { count: step.eventCount }) }}</span>
                        </button>

                        <template v-if="!collapsedSteps.has(step.key)">
                          <div v-for="row in step.rows" :key="row.event.event_id" class="event-row">
                            <code class="event-seq">{{ String(row.event.seq).padStart(3, '0') }}</code>
                            <time class="event-time">{{ formatEventTime(row.event.event_time) }}</time>
                            <div v-for="lane in TRACE_LANES" :key="lane" class="lane-cell" :class="`lane-${lane}`">
                              <article
                                v-if="classifyTraceEvent(row.event) === lane"
                                class="event-card"
                                :class="{ 'nested-call': row.depth > 0, selected: row.event.event_id === selectedEvent?.event_id }"
                                :style="callDepthStyle(row.depth)"
                                role="button"
                                tabindex="0"
                                @click="openEventDetail(row.event)"
                                @keydown.enter="openEventDetail(row.event)"
                                @keydown.space.prevent="openEventDetail(row.event)"
                              >
                                <div class="event-card-heading">
                                  <div class="event-title">
                                    <button
                                      v-if="row.isCallHead && row.hasChildren"
                                      type="button"
                                      class="call-toggle"
                                      :aria-expanded="!row.isCollapsed"
                                      :aria-label="callToggleLabel(row)"
                                      @click.stop="toggleCall(row.event.call_id)"
                                    >
                                      <DownOutlined v-if="!row.isCollapsed" />
                                      <RightOutlined v-else />
                                    </button>
                                    <span v-else-if="row.depth > 0" class="call-branch">↳</span>
                                    <strong>{{ row.event.type }}</strong>
                                  </div>
                                  <span
                                    v-if="row.event.status"
                                    class="status-pill"
                                    :class="`status-${eventStatusTone(row.event.status)}`"
                                  >{{ eventStatusLabel(row.event.status) }}</span>
                                </div>
                                <div v-if="row.event.call_id" class="call-meta">
                                  <code>{{ shortId(row.event.call_id) }}</code>
                                  <span v-if="row.event.parent_call_id">
                                    {{ t('runtimeTraceExplorer.hierarchy.parent') }} {{ shortId(row.event.parent_call_id) }}
                                  </span>
                                  <span v-if="row.hasExternalParent">{{ t('runtimeTraceExplorer.hierarchy.externalParent') }}</span>
                                </div>
                                <code v-if="row.event.tool_name">{{ row.event.tool_name }}</code>
                                <p>{{ payloadPreview(row.event.payload) || t('runtimeTraceExplorer.payloadUnavailable') }}</p>
                              </article>
                            </div>
                          </div>
                        </template>
                      </div>
                    </template>
                  </div>
                  <div class="virtual-spacer" aria-hidden="true" :style="{ height: `${timelineWindow.bottomPadding}px` }" />
                </div>
              </div>
              <a-empty v-else :description="isEventSearchActive ? t('runtimeTraceExplorer.search.noEventResults') : t('runtimeTraceExplorer.timeline.empty')" />
            </section>

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
    </div>

    <a-drawer
      v-model:open="detailOpen"
      class="trace-detail-drawer"
      width="min(680px, calc(100vw - 16px))"
      :title="t('runtimeTraceExplorer.detail.title')"
      destroy-on-close
    >
      <template v-if="selectedEvent">
        <div class="detail-event-heading">
          <div>
            <span>{{ t('runtimeTraceExplorer.detail.event') }} #{{ selectedEvent.seq }}</span>
            <strong>{{ selectedEvent.type }}</strong>
            <code>{{ selectedEvent.event_id }}</code>
          </div>
          <span
            v-if="selectedEvent.status"
            class="status-pill"
            :class="`status-${eventStatusTone(selectedEvent.status)}`"
          >{{ eventStatusLabel(selectedEvent.status) }}</span>
        </div>

        <a-alert
          class="detail-boundary"
          type="info"
          show-icon
          :message="t('runtimeTraceExplorer.detail.redactedTitle')"
          :description="t('runtimeTraceExplorer.detail.redactedDescription')"
        />

        <a-tabs v-model:active-key="activeDetailTab" class="detail-tabs">
          <a-tab-pane key="summary" :tab="t('runtimeTraceExplorer.detailTabs.summary')">
            <dl class="detail-grid">
              <div v-for="(value, key) in detailSummary" :key="key">
                <dt>{{ detailFieldLabel(key) }}</dt>
                <dd><code>{{ displayDetailValue(value) }}</code></dd>
              </div>
            </dl>
          </a-tab-pane>

          <a-tab-pane key="payload" :tab="t('runtimeTraceExplorer.detailTabs.payload')">
            <div class="projection-heading">
              <strong>{{ t('runtimeTraceExplorer.detail.payloadTitle') }}</strong>
              <span>{{ t('runtimeTraceExplorer.detail.redactedBadge') }}</span>
            </div>
            <pre v-if="selectedEvent.payload !== null && selectedEvent.payload !== undefined" class="json-panel">{{ jsonProjection(selectedEvent.payload) }}</pre>
            <a-empty v-else :description="t('runtimeTraceExplorer.detail.noPayload')" />
          </a-tab-pane>

          <a-tab-pane key="result" :tab="t('runtimeTraceExplorer.detailTabs.result')">
            <pre v-if="detailResult !== null" class="json-panel">{{ jsonProjection(detailResult) }}</pre>
            <a-empty v-else :description="t('runtimeTraceExplorer.detail.noResult')" />
          </a-tab-pane>

          <a-tab-pane key="schema" :tab="t('runtimeTraceExplorer.detailTabs.schema')">
            <pre class="json-panel">{{ jsonProjection(detailSchema) }}</pre>
          </a-tab-pane>

          <a-tab-pane key="timing" :tab="t('runtimeTraceExplorer.detailTabs.timing')">
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
                      <span>{{ riskLevelLabel(finding.severity) }} · {{ finding.source }}</span>
                      <strong>{{ finding.title }}</strong>
                      <code>{{ finding.finding_id }}</code>
                    </div>
                    <a-button type="link" size="small" @click="openLinkedFinding(finding)">
                      {{ t('runtimeTraceExplorer.links.openFinding') }}
                    </a-button>
                  </article>
                </div>
                <a-empty v-else :description="t('runtimeTraceExplorer.links.empty')" />
              </a-spin>
              <p>{{ t('runtimeTraceExplorer.links.boundary') }}</p>
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
    </a-drawer>

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
import { DownloadOutlined, DownOutlined, ReloadOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  authorizeRawRuntimeTraceExport,
  createRuntimeTraceExport,
  downloadRuntimeTraceExport,
  getMe,
  getRuntimeTrace,
  listRuntimeTraceEvents,
  listRuntimeTraces,
  listSecurityFindingsForTraceEvent,
} from '../api'
import { agenticRiskLabel, isAgenticRiskCode } from '../agenticRiskTaxonomy'
import {
  TRACE_LANES,
  buildCallRows,
  classifyTraceEvent,
  conversationRole,
  eventResultProjection,
  eventSchemaProjection,
  eventSecurityProjection,
  eventStatusTone,
  eventSummaryProjection,
  eventTimingProjection,
  groupTraceEvents,
  payloadPreview,
  runtimeTraceEventSearchParams,
  runtimeTraceSearchParams,
  sortTraceEvents,
  tracePerformanceSummary,
  traceSecuritySummary,
  virtualTraceWindow,
} from '../runtimeTraceView'

const { t, te, locale } = useI18n()
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
const events = ref([])
const eventTotal = ref(0)
const eventPageSize = 200
const eventsLoadingMore = ref(false)
const hasMoreEvents = ref(false)
const nextEventCursor = ref(null)
const traceScrollTop = ref(0)
const traceViewportHeight = ref(640)
const conversationScrollTop = ref(0)
const conversationViewportHeight = ref(640)
const activeView = ref('trace')
const collapsedTurns = ref(new Set())
const collapsedSteps = ref(new Set())
const collapsedCalls = ref(new Set())
const detailOpen = ref(false)
const selectedEvent = ref(null)
const activeDetailTab = ref('summary')
const linkedFindings = ref([])
const linkedFindingsLoading = ref(false)
const linkedFindingsError = ref('')
const searchDraft = reactive({ turn_id: '', tool_name: '', risk_level: 'all', has_error: false, request_id: '' })
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

const selectedTrace = computed(() => selectedTraceDetail.value
  || traces.value.find(item => item.trace_id === selectedTraceId.value)
  || null)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const isSearchActive = computed(() => Object.keys(activeSearch.value).length > 0)
const hasSearchDraft = computed(() => Object.keys(runtimeTraceSearchParams(searchDraft)).length > 0)
const isEventSearchActive = computed(() => Object.keys(runtimeTraceEventSearchParams(activeSearch.value)).length > 0)
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
].filter(([, , value]) => value).map(([key, labelKey, value]) => ({
  key, value, label: t(`runtimeTraceExplorer.search.${labelKey}`),
})))
const sortedEvents = computed(() => sortTraceEvents(events.value))
const conversationEvents = computed(() => sortedEvents.value.filter(event => conversationRole(event)))
const timelineWindow = computed(() => virtualTraceWindow(
  sortedEvents.value, traceScrollTop.value, traceViewportHeight.value, { rowHeight: 96, overscan: 8 },
))
const conversationWindow = computed(() => virtualTraceWindow(
  conversationEvents.value, conversationScrollTop.value, conversationViewportHeight.value, { rowHeight: 112, overscan: 6 },
))
const traceGroups = computed(() => groupTraceEvents(timelineWindow.value.items).map(turn => ({
  ...turn,
  steps: turn.steps.map(step => ({
    ...step,
    rows: buildCallRows(step.events, collapsedCalls.value, sortedEvents.value),
  })),
})))
const detailSummary = computed(() => eventSummaryProjection(selectedEvent.value || {}))
const detailResult = computed(() => eventResultProjection(selectedEvent.value || {}))
const detailSchema = computed(() => eventSchemaProjection(selectedEvent.value || {}))
const detailTiming = computed(() => eventTimingProjection(selectedEvent.value || {}))
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

const errorMessage = requestError => requestError.response?.data?.detail || requestError.message || t('runtimeTraceExplorer.loadFailed')

const loadTracePage = async (preserveSelection = true) => {
  loading.value = true
  error.value = ''
  try {
    const result = await listRuntimeTraces({ ...activeSearch.value, page: page.value, page_size: pageSize })
    traces.value = result.items || []
    total.value = result.total || 0
    const next = preserveSelection
      ? traces.value.find(item => item.trace_id === selectedTraceId.value) || traces.value[0]
      : traces.value[0]
    if (next) await selectTrace(next)
    else {
      selectedTraceId.value = ''
      selectedTraceDetail.value = null
      events.value = []
      eventTotal.value = 0
    }
  } catch (requestError) {
    error.value = errorMessage(requestError)
  } finally {
    loading.value = false
  }
}

const selectTrace = async (trace) => {
  if (!trace?.trace_id) return
  selectedTraceId.value = trace.trace_id
  selectedTraceDetail.value = trace
  collapsedTurns.value = new Set()
  collapsedSteps.value = new Set()
  collapsedCalls.value = new Set()
  detailOpen.value = false
  selectedEvent.value = null
  linkedFindings.value = []
  linkedFindingsError.value = ''
  events.value = []
  eventTotal.value = 0
  hasMoreEvents.value = false
  nextEventCursor.value = null
  traceScrollTop.value = 0
  conversationScrollTop.value = 0
  detailLoading.value = true
  error.value = ''
  const requestId = ++detailRequest
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

const updateVirtualViewport = (event, scrollTopRef, viewportRef) => {
  const target = event.currentTarget
  scrollTopRef.value = target.scrollTop
  viewportRef.value = target.clientHeight || 640
  if (target.scrollTop + target.clientHeight >= target.scrollHeight - target.clientHeight) loadMoreEvents()
}
const handleTraceScroll = event => updateVirtualViewport(event, traceScrollTop, traceViewportHeight)
const handleConversationScroll = event => updateVirtualViewport(event, conversationScrollTop, conversationViewportHeight)

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
  Object.assign(searchDraft, { turn_id: '', tool_name: '', risk_level: 'all', has_error: false, request_id: '' })
  activeSearch.value = {}
  page.value = 1
  await router.replace({ name: 'runtime-traces', query: {} })
  await loadTracePage(false)
}
const removeTraceSearch = async key => {
  if (key === 'risk_level') searchDraft.risk_level = 'all'
  else if (key === 'has_error') searchDraft.has_error = false
  else searchDraft[key] = ''
  await applyTraceSearch()
}

const formatDateTime = (value) => value
  ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : '—'
const formatEventTime = (value) => value
  ? new Intl.DateTimeFormat(locale.value, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value))
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
const conversationRoleLabel = event => t(`runtimeTraceExplorer.roles.${conversationRole(event)}`)
const turnLabel = turn => turn.isUnscoped ? t('runtimeTraceExplorer.hierarchy.unscopedEvents') : turn.turnId
const stepLabel = step => step.isUnscoped ? t('runtimeTraceExplorer.hierarchy.directEvents') : step.stepId
const seqRange = group => group.startSeq === group.endSeq ? `#${group.startSeq}` : `#${group.startSeq}–${group.endSeq}`
const shortId = value => value?.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
const callDepthStyle = depth => ({ '--call-indent': `${Math.min(Number(depth || 0), 5) * 18}px` })
const eventStatusLabel = (value) => {
  const key = `runtimeTraceExplorer.statuses.${value || 'unknown'}`
  return te(key) ? t(key) : value
}
const callToggleLabel = row => t(
  row.isCollapsed ? 'runtimeTraceExplorer.hierarchy.expandCall' : 'runtimeTraceExplorer.hierarchy.collapseCall',
  { callId: shortId(row.event.call_id) },
)

const toggleSetValue = (holder, key) => {
  const next = new Set(holder.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  holder.value = next
}
const toggleTurn = key => toggleSetValue(collapsedTurns, key)
const toggleStep = key => toggleSetValue(collapsedSteps, key)
const toggleCall = key => toggleSetValue(collapsedCalls, key)
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
  const traceId = queryValue(route.query.trace_id)
  const eventId = queryValue(route.query.event_id)
  if (!traceId || !eventId) return
  if (selectedTraceId.value !== traceId) await selectTrace({ trace_id: traceId })
  let event = events.value.find(item => item.event_id === eventId)
  if (!event) {
    try {
      const result = await listRuntimeTraceEvents(traceId, { event_id: eventId, page: 1, page_size: 1 })
      event = result.items?.[0]
    } catch (requestError) {
      error.value = errorMessage(requestError)
    }
  }
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
  Object.assign(searchDraft, {
    turn_id: queryValue(route.query.turn_id) || '',
    tool_name: queryValue(route.query.tool_name) || '',
    risk_level: queryValue(route.query.risk_level) || 'all',
    has_error: queryValue(route.query.has_error) === 'true',
    request_id: queryValue(route.query.request_id) || '',
  })
  activeSearch.value = runtimeTraceSearchParams(searchDraft)
  const [profileResult] = await Promise.allSettled([getMe(), loadTracePage(false)])
  if (profileResult.status === 'fulfilled') currentUser.value = profileResult.value
  await openEventFromRoute()
})
watch(() => [route.query.trace_id, route.query.event_id], openEventFromRoute)
</script>

<style scoped>
.trace-page {
  max-width: 1560px;
  margin: 0 auto;
  color: #172033;
}

.trace-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
}

.eyebrow,
.trace-kicker {
  color: #3156a3;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
}

.trace-header h1 {
  margin: 4px 0 6px;
  font-size: clamp(25px, 3vw, 34px);
  line-height: 1.15;
}

.trace-header p,
.view-intro p {
  margin: 0;
  color: #667085;
}

.trace-alert { margin-bottom: 16px; }

.trace-query-ribbon {
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid #d7dfeb;
  border-left: 4px solid #3156a3;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(36, 59, 101, .055);
}
.query-ribbon-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 13px 16px 10px; background: linear-gradient(100deg, #f3f7ff, #fff 60%); }
.query-ribbon-heading > div { display: grid; gap: 2px; }
.query-ribbon-heading strong { color: #24344f; font-size: 15px; }
.query-ribbon-heading small { color: #738096; font-size: 11px; }
.query-result-count { padding: 4px 9px; border: 1px solid #c9d5e9; border-radius: 999px; color: #31568f; background: #f7faff; font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }
.query-controls { display: grid; grid-template-columns: minmax(130px, .9fr) minmax(130px, .9fr) minmax(130px, .7fr) minmax(160px, 1.15fr) auto auto auto; align-items: center; gap: 8px; padding: 11px 14px; border-top: 1px solid #e5eaf2; border-bottom: 1px solid #e5eaf2; }
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
  display: grid;
  grid-template-columns: 292px minmax(0, 1fr);
  min-height: 690px;
  overflow: hidden;
  border: 1px solid #dfe4ed;
  border-radius: 18px;
  background: #f7f8fb;
  box-shadow: 0 14px 40px rgba(20, 36, 65, .08);
}

.session-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-right: 1px solid #dfe4ed;
  background: #f1f4f8;
}

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

.session-list { padding: 8px; }
.session-item {
  display: grid;
  width: 100%;
  gap: 7px;
  padding: 13px 12px;
  border: 1px solid transparent;
  border-radius: 12px;
  color: inherit;
  text-align: left;
  background: transparent;
  cursor: pointer;
  transition: background .18s ease, border-color .18s ease, transform .18s ease;
}

.session-item:hover { background: rgba(255, 255, 255, .7); transform: translateY(-1px); }
.session-item.selected { border-color: #bcccf0; background: #fff; box-shadow: 0 5px 18px rgba(35, 65, 120, .08); }
.session-leading { display: flex; align-items: center; gap: 8px; min-width: 0; }
.session-leading strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-pulse { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: #3e68c2; box-shadow: 0 0 0 4px #e1e9fb; }
.session-item code { overflow: hidden; color: #68758b; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.session-badges { display: flex; flex-wrap: wrap; gap: 5px; }
.session-meta { display: flex; justify-content: space-between; gap: 8px; color: #8a93a2; font-size: 11px; }
.session-pagination { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; padding: 12px; border-top: 1px solid #dfe4ed; color: #667085; font-size: 11px; }

.trace-stage { min-width: 0; padding: 24px; background: #fff; }
.stage-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.stage-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 9px; }
.trace-identity { min-width: 0; }
.trace-identity h2 { margin: 4px 0 2px; font-size: 22px; overflow-wrap: anywhere; }
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

.conversation-view,
.timeline-view { min-height: 460px; }
.view-intro { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
.view-intro h3 { margin: 0 0 4px; font-size: 16px; }
.view-intro > span { color: #7b8496; font-size: 12px; white-space: nowrap; }

.conversation-stream { display: grid; max-height: 680px; gap: 15px; overflow-y: auto; padding: 8px 8px 28px 2px; }
.conversation-stream:focus-visible,
.rail-scroll:focus-visible { outline: 2px solid #4c74ca; outline-offset: 3px; }
.message-row { display: grid; max-width: 78%; gap: 5px; cursor: pointer; }
.message-row.user { justify-self: end; }
.message-row.assistant,
.message-row.context,
.message-row.error { justify-self: start; }
.message-meta { display: flex; align-items: center; gap: 9px; padding: 0 4px; color: #7b8496; font-size: 11px; }
.message-row.user .message-meta { justify-content: flex-end; }
.message-meta span { font-weight: 700; color: #4c5a70; }
.message-bubble { padding: 13px 15px; border: 1px solid #dde4ee; border-radius: 4px 14px 14px; background: #f7f9fc; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.message-row.user .message-bubble { border-color: #345bb0; border-radius: 14px 4px 14px 14px; background: #345bb0; color: #fff; }
.message-row.context .message-bubble { border-color: #abdcd2; background: #f0faf7; }
.message-row.error .message-bubble { border-color: #efc0c0; background: #fff4f4; }
.message-row:hover .message-bubble,
.message-row.selected .message-bubble { box-shadow: 0 0 0 2px rgba(49, 86, 163, .22), 0 8px 22px rgba(23, 32, 51, .08); }
.message-row:focus-visible { outline: 2px solid #4c74ca; outline-offset: 4px; border-radius: 8px; }

.rail-scroll { max-height: 680px; overflow: auto; border: 1px solid #e2e6ee; border-radius: 13px; background: #fbfcfe; }
.trace-rail { min-width: 1240px; }
.virtual-spacer { width: 100%; pointer-events: none; }
.rail-header,
.event-row {
  display: grid;
  grid-template-columns: 58px 96px repeat(6, minmax(150px, 1fr));
}
.rail-header { position: sticky; top: 0; z-index: 2; border-bottom: 1px solid #dfe4ed; background: #f1f4f8; }
.rail-header > span { display: flex; min-height: 46px; align-items: center; padding: 0 10px; border-right: 1px solid #dfe4ed; color: #596579; font-size: 11px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.lane-heading i { width: 7px; height: 7px; margin-right: 7px; border-radius: 50%; background: currentColor; }
.turn-group + .turn-group { border-top: 1px solid #ccd5e3; }
.group-bar {
  display: grid;
  width: 100%;
  min-width: 1240px;
  grid-template-columns: 18px 92px minmax(180px, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  border: 0;
  color: #42506a;
  text-align: left;
  cursor: pointer;
}
.group-bar:focus-visible,
.call-toggle:focus-visible { outline: 2px solid #4c74ca; outline-offset: -2px; }
.turn-bar { padding: 11px 15px; background: #e8edf5; }
.step-bar { padding: 8px 18px 8px 36px; border-top: 1px solid #e1e6ef; background: #f5f7fa; }
.group-bar:hover { filter: brightness(.985); }
.group-bar svg { font-size: 11px; }
.group-kind { color: #68758b; font: 800 10px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .08em; }
.group-bar strong { overflow: hidden; color: #24344f; font: 700 12px ui-monospace, SFMono-Regular, Menlo, monospace; text-overflow: ellipsis; white-space: nowrap; }
.group-bar code,
.group-bar > span:last-child { color: #7a8598; font-size: 10px; }
.event-row { min-height: 74px; border-bottom: 1px solid #edf0f5; }
.event-row:last-child { border-bottom: 0; }
.event-seq,
.event-time { display: flex; align-items: flex-start; justify-content: center; padding: 17px 6px; color: #7b8496; font-size: 11px; }
.lane-cell { position: relative; min-width: 0; padding: 8px; border-left: 1px solid #edf0f5; }
.lane-cell::before { position: absolute; top: 0; bottom: 0; left: 18px; width: 1px; background: #dbe1ea; content: ''; }
.event-card { position: relative; z-index: 1; width: calc(100% - var(--call-indent, 0px)); min-width: 0; margin-left: var(--call-indent, 0px); padding: 10px 11px; border: 1px solid currentColor; border-radius: 9px; background: #fff; box-shadow: 0 3px 10px rgba(23, 32, 51, .06); cursor: pointer; transition: box-shadow .16s ease, transform .16s ease; }
.event-card:hover,
.event-card.selected { box-shadow: 0 0 0 2px currentColor, 0 8px 20px rgba(23, 32, 51, .12); transform: translateY(-1px); }
.event-card:focus-visible { outline: 2px solid #172033; outline-offset: 2px; }
.event-card.nested-call::before { position: absolute; top: 50%; left: -13px; width: 10px; border-top: 1px solid #aeb8c8; content: ''; }
.event-card-heading { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.event-title { display: flex; min-width: 0; align-items: center; gap: 5px; }
.event-title strong { overflow: hidden; font: 700 11px ui-monospace, SFMono-Regular, Menlo, monospace; text-overflow: ellipsis; white-space: nowrap; }
.call-toggle { display: grid; width: 18px; height: 18px; flex: 0 0 auto; place-items: center; padding: 0; border: 1px solid currentColor; border-radius: 5px; color: inherit; background: rgba(255, 255, 255, .8); cursor: pointer; }
.call-toggle svg { font-size: 9px; }
.call-branch { color: #7f8aa0; font-size: 12px; }
.status-pill { flex: 0 0 auto; padding: 2px 6px; border: 1px solid transparent; border-radius: 999px; font-size: 9px; font-weight: 750; text-transform: none; }
.status-success { border-color: #9ad6b7; color: #217a4a; background: #effaf4; }
.status-active { border-color: #a9c4ea; color: #315f9d; background: #f0f6ff; }
.status-danger { border-color: #e6acb1; color: #a43c47; background: #fff2f3; }
.status-neutral { border-color: #ccd3de; color: #667085; background: #f5f6f8; }
.call-meta { display: flex; min-width: 0; align-items: center; gap: 6px; margin-top: 6px; color: #7b8496; font-size: 9px; }
.call-meta code { overflow: hidden; color: inherit; text-overflow: ellipsis; white-space: nowrap; }
.call-meta span { white-space: nowrap; }
.event-card > code { display: block; margin-top: 5px; overflow: hidden; color: inherit; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.event-card p { margin: 6px 0 0; overflow: hidden; color: #657086; font-size: 11px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.lane-input { color: #3f64b4; }
.lane-model { color: #6f52b5; }
.lane-tools { color: #b56a22; }
.lane-mcp { color: #ce7724; }
.lane-knowledge { color: #268578; }
.lane-policy { color: #9a486f; }
.lane-input .event-card { background: #f5f8ff; }
.lane-model .event-card { background: #faf7ff; }
.lane-tools .event-card,
.lane-mcp .event-card { background: #fff9f2; }
.lane-knowledge .event-card { background: #f2fbf8; }
.lane-policy .event-card { background: #fff6fa; }

.detail-event-heading { display: grid; gap: 5px; padding-bottom: 14px; }
.detail-event-heading > div { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.detail-event-heading > div > span:first-child { color: #3156a3; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.detail-event-heading strong { font: 750 16px ui-monospace, SFMono-Regular, Menlo, monospace; }
.detail-event-heading > code { overflow: hidden; color: #7b8496; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.detail-boundary { margin-bottom: 8px; }
.detail-tabs { margin-top: 6px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 0; }
.detail-grid > div { min-width: 0; padding: 12px 13px; border: 1px solid #e1e6ee; border-radius: 10px; background: #f8fafc; }
.detail-grid dt { margin-bottom: 5px; color: #7b8496; font-size: 11px; }
.detail-grid dd { margin: 0; overflow: hidden; color: #26364f; text-overflow: ellipsis; white-space: nowrap; }
.detail-grid code { font-size: 12px; }
.projection-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.projection-heading span { padding: 3px 8px; border-radius: 999px; color: #315f9d; background: #edf4ff; font-size: 10px; font-weight: 700; }
.json-panel { max-height: calc(100vh - 290px); margin: 0; overflow: auto; padding: 15px; border: 1px solid #dfe4ed; border-radius: 11px; color: #dce7ff; background: #172033; font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
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
  .trace-workspace { grid-template-columns: 1fr; }
  .session-panel { max-height: 330px; border-right: 0; border-bottom: 1px solid #dfe4ed; }
  .session-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .governance-ledger { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .performance-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 680px) {
  .trace-header,
  .stage-heading,
  .view-intro { align-items: stretch; flex-direction: column; }
  .stage-actions { align-items: stretch; flex-direction: column-reverse; }
  .stage-actions :deep(.ant-btn) { width: 100%; }
  .trace-stage { padding: 16px; }
  .query-ribbon-heading { align-items: flex-start; flex-direction: column; }
  .query-controls { grid-template-columns: 1fr; }
  .query-controls :deep(.ant-btn) { width: 100%; }
  .query-ledger { align-items: flex-start; flex-direction: column; padding-left: 30px; }
  .query-token { max-width: 100%; }
  .session-list { grid-template-columns: 1fr; }
  .trace-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .trace-facts strong { white-space: normal; overflow-wrap: anywhere; }
  .security-heading { align-items: flex-start; flex-direction: column; }
  .security-seals { justify-content: flex-start; }
  .governance-ledger { grid-template-columns: 1fr; }
  .performance-heading { align-items: flex-start; flex-direction: column; }
  .performance-heading p { text-align: left; }
  .performance-grid { grid-template-columns: 1fr 1fr; }
  .message-row { max-width: 94%; }
  .detail-grid { grid-template-columns: 1fr; }
  .event-pagination { align-items: stretch; flex-direction: column; }
  .event-pagination :deep(.ant-btn) { width: 100%; }
}
</style>
