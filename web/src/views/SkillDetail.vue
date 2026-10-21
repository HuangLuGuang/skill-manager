<template>
  <div class="skill-detail-page">
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="detailPageTitle" :sub-title="text('查看 Skill 详情、审核与审计记录', 'Review Skill details, approval, and audit records')">
          <template #extra>
            <a-button v-if="hasAccess('clients:execute') && (detail?.status === 'APPROVED')" type="primary" @click="openClientInstall"> {{ $t("legacy.1wbn313") }} </a-button>
            <a-button
              @click="handleExportScanReport"
              :loading="exportingScanReport"
              :disabled="!detail?.vetting || detail?.status === 'PENDING'"
            >
              {{ $t('scanReportExport.button') }}
            </a-button>
            <a-button @click="handleDownloadSkill" :loading="downloadingSkill" :disabled="!detail?.skill_id"> {{ $t("legacy.fye4hw") }} </a-button>
          </template>
        </a-page-header>
      </template>

    <a-card :title="$t('legacy.17qypnb')" class="basic-info-card">
      <template #extra>
        <a-space wrap class="basic-scan-options">
          <a-tooltip :title="$t(`skillBatch.optionsSource_${detail?.scan_options_source || 'unknown'}`)">
            <span class="scan-options-label">{{ $t('skillBatch.scanOptionsLabel') }}</span>
          </a-tooltip>
          <a-checkbox :checked="Boolean(detail?.scan_options?.use_skillspector)" :indeterminate="!detail?.scan_options" disabled>{{ $t('skillBatch.deepScan') }}</a-checkbox>
          <a-checkbox :checked="Boolean(detail?.scan_options?.use_sandbox)" :indeterminate="!detail?.scan_options" disabled>{{ $t('skillBatch.sandbox') }}</a-checkbox>
          <a-checkbox :checked="Boolean(detail?.scan_options?.use_llm)" :indeterminate="!detail?.scan_options" disabled>{{ $t('skillBatch.llm') }}</a-checkbox>
          <span v-if="detail?.scan_options_source === 'report'" class="scan-options-label">{{ $t('skillBatch.fromReport') }}</span>
        </a-space>
      </template>
      <a-skeleton :loading="loading" active :paragraph="{ rows: 5 }">
        <dl class="basic-summary">
          <div class="basic-field version-field">
            <dt>{{ $t('skillVersions.currentVersion') }}</dt>
            <dd>
              <div class="current-version-rail">
                <div class="current-version-badges">
                  <strong class="current-version-number">v{{ detail?.version_no || '-' }}</strong>
                  <a-tag v-if="currentVersionRecord?.latest" color="blue">{{ $t('skillVersions.latest') }}</a-tag>
                  <a-tag v-if="currentVersionRecord?.latest_trusted" color="green">{{ $t('skillVersions.latestTrusted') }}</a-tag>
                </div>
                <a-select
                  class="current-version-select"
                  :value="detail?.version_id"
                  :placeholder="$t('skillVersions.switchVersion')"
                  :aria-label="$t('skillVersions.switchVersion')"
                  :loading="loadingVersions"
                  @change="switchVersion"
                >
                  <a-select-option v-for="item in skillVersions" :key="item.version_id" :value="item.version_id">
                    v{{ item.version_no }} · {{ summaryStatus(item) }}
                    {{ item.latest_trusted ? ` · ${$t('skillVersions.latestTrusted')}` : '' }}
                  </a-select-option>
                </a-select>
              </div>
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('legacy.1ccx4t4') }}</dt>
            <dd>
              <a-tag :color="statusColor(detail?.status, detail)" :title="statusDisplay(detail?.status, detail)" class="summary-tag">
                <span class="status-dot" aria-hidden="true"></span>{{ summaryStatus(detail) }}
              </a-tag>
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('legacy.13tzib2') }}</dt>
            <dd>
              <div class="summary-risk">
                <a-tag :color="detail?.status === 'PENDING' ? 'default' : riskColor(detail?.risk_level)" class="summary-tag" :title="detail?.status === 'PENDING' ? undefined : riskDisplay(detail?.risk_level)">
                  <SafetyOutlined v-if="detail?.status !== 'PENDING' && detail?.risk_level === 'benign'" />
                  <WarningOutlined v-else-if="detail?.status !== 'PENDING' && detail?.risk_level === 'malicious'" />
                  <ExclamationCircleOutlined v-else-if="detail?.status !== 'PENDING' && detail?.risk_level === 'suspicious'" />
                  {{ summaryRisk }}
                </a-tag>
                <a href="#decision-title" class="decision-jump" @click.prevent="openDecisionTrace">{{ $t('decisionFlow.viewTrace') }} <span aria-hidden="true">→</span></a>
              </div>
            </dd>
          </div>
        </dl>
        <dl class="basic-metadata">
          <div class="basic-field">
            <dt>{{ $t('legacy.hzx914') }}</dt>
            <dd>
              {{ detail?.name || '-' }}
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('skillDetail.submitter') }}</dt>
            <dd>
              {{ detail?.source?.author || '-' }}
            </dd>
          </div>
          <div class="basic-field metadata-wide skill-identifier">
            <dt>Skill ID</dt>
            <dd>
              {{ detail?.skill_id || skillId }}
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('legacy.2tds9c') }}</dt>
            <dd>
              <a-space wrap>
                <span>{{ sourceLabel(detail) }}</span>
                <a-tag v-if="detail?.source?.token_name" color="blue" class="source-credential">{{ $t("legacy.1tguyk3") }}{{ detail.source.token_name }}</a-tag>
              </a-space>
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('skillDetail.declaredTools') }}</dt>
            <dd>
              <span :title="$t('legacy.1108kfy')">
                {{ detail?.allowed_tools?.join(', ') || $t('skillDetail.notDeclared') }}
              </span>
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('skillDetail.toolCheck') }}</dt>
            <dd>
              <a-tag :color="toolDeclarationWarning ? 'orange' : detail?.declared_tools_valid === true ? 'green' : detail?.declared_tools_valid === false ? 'red' : 'default'" :title="$t('skillDetail.toolCheckHint')" class="summary-tag">
                <ExclamationCircleOutlined v-if="toolDeclarationWarning || detail?.declared_tools_valid === false" />
                <CheckCircleOutlined v-else-if="detail?.declared_tools_valid === true" />
                {{ toolDeclarationWarning ? $t('skillDetail.toolDeclarationNotice') : detail?.declared_tools_valid === true ? $t('skillDetail.compliant') : detail?.declared_tools_valid === false ? $t('skillDetail.noncompliant') : $t('decisionFlow.unrecorded') }}
              </a-tag>
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('decisionFlow.resultReuse') }}</dt>
            <dd>
              <a-space wrap>
                <a-tag :color="detail?.scan_reused ? 'green' : 'default'">
                  {{ $t(detail?.scan_reused === true ? 'decisionFlow.reusedResult' : detail?.scan_reused === false ? 'skillDetail.notReused' : 'decisionFlow.unrecorded') }}
                </a-tag>
                <span v-if="detail?.reused_from_skill_id">{{ $t('skillDetail.reusedFrom', { id: detail.reused_from_skill_id }) }}</span>
              </a-space>
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('skillDetail.sandboxStatus') }}</dt>
            <dd>
              {{ $t(`decisionFlow.${sandboxExecutionState}`) }}
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('skillDetail.sandboxPolicy') }}</dt>
            <dd>
              <a-tag :color="detail?.vetting?.sandbox_required_by_policy === true ? 'orange' : 'default'">
                {{ $t(detail?.vetting?.sandbox_required_by_policy === true ? 'skillDetail.required' : detail?.vetting?.sandbox_required_by_policy === false ? 'skillDetail.notRequired' : 'decisionFlow.unrecorded') }}
              </a-tag>
            </dd>
          </div>
          <div class="basic-field">
            <dt>{{ $t('skillDetail.sandboxRuntime') }}</dt>
            <dd>
              <SandboxDebugHelp field="runtime" :value="sandboxRuntime" />
            </dd>
          </div>
          <div class="basic-field sandbox-target-field">
            <dt>{{ sandboxTargetLabel }}</dt>
            <dd>
              {{ sandboxTarget }}
            </dd>
          </div>
        </dl>
      </a-skeleton>
    </a-card>

    <a-card class="lifecycle-card" style="margin-top: 12px">
      <div class="lifecycle-row">
        <div class="lifecycle-heading">
          <strong>{{ $t("legacy.1uf97vz") }}</strong>
          <a-tag :color="statusColor(detail?.status, detail)" :title="detail?.status">{{ summaryStatus(detail) }}</a-tag>
        </div>

        <a-steps :current="stepIndex" size="small" class="lifecycle-steps" :responsive="false">
          <a-step :title="$t('legacy.ybr38x')" :description="formatDateTime(detail?.submitted_at)" />
          <a-step :title="$t('legacy.1ws11do')" :description="approvalActor" />
          <a-step :title="$t('legacy.1tmnt86')" :description="formatDateTime(detail?.approved_at)" />
        </a-steps>

        <a-space class="lifecycle-actions" wrap>
            <a-button @click="fetchDetail" :loading="loading">{{ text('刷新', 'Refresh') }}</a-button>
            <a-tooltip :title="signatureVerifyDisabledReason">
              <span>
                <a-button v-if="hasAccess('skills:sign')"
                  :disabled="!detail?.signature"
                  :loading="verifyingSignature"
                  @click="handleVerifySignature"
                > {{ $t("legacy.y6whtf") }} </a-button>
              </span>
            </a-tooltip>
            <a-button v-if="hasAccess('skills:approve') && (canApproveSkill)" type="primary" @click="openApproveModal">
              {{ manualApprovalRequired ? $t('legacy.8ve3lv') : $t('legacy.1tmnt86') }}
            </a-button>
            <a-button v-if="hasAccess('skills:reject') && (detail?.status === 'VETTED')" danger @click="openRejectModal">{{ $t("legacy.1qrntx4") }}</a-button>
        </a-space>
      </div>
      <a-alert
        v-if="signatureResult"
        style="margin-top: 12px"
        :type="signatureResult.valid ? 'success' : 'error'"
        show-icon
        :message="signatureResult.valid ? $t('legacy.niy9wk') : $t('legacy.169xltl')"
        :description="signatureResultReason"
      />
    </a-card>

    <a-card :title="$t('decisionFlow.reportTitle')" style="margin-top: 12px">
      <template #extra>
        <a-button type="primary" class="refresh-report-button" @click="fetchScanReport" :loading="loadingScanReport"> {{ $t("legacy.1y2sdbh") }} </a-button>
      </template>
      <a-tabs v-model:activeKey="activeTab">
        <a-tab-pane key="decision" :tab="$t('decisionFlow.title')">
          <div id="skill-decision-panel" tabindex="-1">
            <a-skeleton v-if="decisionLoading" class="decision-loading" active :paragraph="{ rows: 12 }" />
            <template v-else>
              <a-alert v-if="scanReportError" class="report-load-error" type="error" show-icon :message="$t('skillDetail.reportLoadFailed')">
                <template #action>
                  <a-button size="small" :loading="loadingScanReport" @click="fetchScanReport">{{ $t('skillDetail.retryReport') }}</a-button>
                </template>
              </a-alert>
              <SkillDecisionFlow v-if="scanReport" :report="scanReport" :status="isCancelled(detail) ? 'CANCELLED' : detail?.status" style="margin: 0" @navigate="jumpToRationale" />
              <a-empty v-else-if="!scanReportError" :description="$t('decisionFlow.missing')" />
              <template v-if="scanReport || !scanReportError">
                <a-alert
                  v-if="manualApprovalRequired"
                  style="margin-top: 12px"
                  type="error"
                  show-icon
                  :message="vettingFailed ? $t('legacy.11ldhwj') : $t('legacy.gobvd0')"
                  :description="manualApprovalSummary"
                />
                <a-alert
                  v-if="detail?.status === 'REJECTED' && detail?.rejection_reason && !vettingFailed"
                  class="rejection-reason"
                  style="margin-top: 12px"
                  type="error"
                  show-icon
                  :message="$t('decisionFlow.rejectionReason')"
                  :description="detail.rejection_reason"
                />
              </template>
            </template>
          </div>
        </a-tab-pane>
        <a-tab-pane key="vetting" :tab="$t('decisionFlow.scanResults')">
          <a-tabs v-model:activeKey="analysisTab" class="analysis-result-tabs" type="card">
            <a-tab-pane key="rule" :tab="$t('decisionFlow.ruleScan')">
                <a-card id="rule-analysis-section" size="small" :title="$t('legacy.1hpgf7r')">
                  <template v-if="behavioralAnalysis || localStaticAnalysis || ruleAnalyzerNames.length || ruleAnalysisFindings.length">
                    <a-descriptions :column="{ xs: 1, sm: 2 }" size="small" bordered>
                      <a-descriptions-item :label="$t('legacy.5p87cu')">
                        {{ localStaticAnalysis?.scanned_file_count ?? behavioralAnalysis?.scanned_file_count ?? (behavioralAnalysis ? behavioralScannedFiles.length : '-') }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.7yxhns')">
                        {{ ruleAnalysisFindings.length }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.syac4h')">
                        <a-tag :color="severityColor(ruleAnalysisMaxSeverity)">
                          {{ ruleAnalysisMaxSeverity || '-' }}
                        </a-tag>
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.13tfl8g')">
                        <a-space v-if="ruleAnalyzerNames.length" wrap :size="[0, 8]">
                          <a-tag v-for="name in ruleAnalyzerNames" :key="name" :color="name === 'agent-manager-local' ? 'cyan' : 'blue'">{{ name }}</a-tag>
                        </a-space>
                        <span v-else>{{ $t('decisionFlow.unrecorded') }}</span>
                      </a-descriptions-item>
                    </a-descriptions>
                    <a-collapse
                      style="margin-top: 12px"
                      :default-active-key="ruleAnalysisFindings.length ? nonEmptyRuleClassificationKeys : []"
                    >
                      <a-collapse-panel
                        v-for="group in groupedRuleAnalysisFindings"
                        :key="group.key"
                        :header="`${group.label}（${group.items.length}）`"
                      >
                        <div v-for="section in group.sections" :key="section.key" class="finding-section">
                          <div class="finding-section-title">{{ section.label }}（{{ section.items.length }}）</div>
                          <a-list :data-source="section.items" bordered size="small">
                            <template #renderItem="{ item }">
                              <a-list-item>
                                <div style="width: 100%">
                                  <a-space wrap>
                                    <a-tag :color="severityColor(item.severity)">{{ item.severity }}</a-tag>
                                    <strong>{{ findingTitle(item) }}</strong>
                                    <a-button
                                      v-if="item.file"
                                      type="link"
                                      size="small"
                                      style="padding: 0"
                                      @click="openFileViewer(item.file)"
                                    >
                                      {{ item.file }}
                                    </a-button>
                                    <a-tag v-if="item.rule" color="default">{{ item.rule }}</a-tag>
                                    <a-tag v-if="findingPolicyLabel(item)" color="cyan">{{ text('策略项', 'Policy Category') }}: {{ findingPolicyLabel(item) }}</a-tag>
                                    <a-tag v-if="item.aggregate_count > 1" color="blue">{{ text(`命中 ${item.aggregate_count} 处`, `${item.aggregate_count} matches`) }}</a-tag>
                                  </a-space>
                                  <div v-if="item.aggregate_lines?.length" class="muted" style="margin-top: 4px">
                                    {{ text('行号', 'Lines') }}: {{ formatAggregateLines(item.aggregate_lines) }}
                                  </div>
                                  <div style="margin-top: 6px">{{ ruleFindingExplanation(item) }}</div>
                                </div>
                              </a-list-item>
                            </template>
                          </a-list>
                        </div>
                      </a-collapse-panel>
                      <a-collapse-panel key="files" :header="text(`已扫描文件（${behavioralScannedFiles.length}）`, `Scanned Files (${behavioralScannedFiles.length})`)">
                        <a-list v-if="behavioralScannedFiles.length" :data-source="behavioralScannedFiles" bordered size="small">
                          <template #renderItem="{ item }">
                            <a-list-item>
                              <a-button type="link" style="padding: 0" @click="openFileViewer(item)">{{ item }}</a-button>
                            </a-list-item>
                          </template>
                        </a-list>
                        <a-empty v-else :image-style="{ height: '36px' }" :description="$t('legacy.by9c6r')" />
                      </a-collapse-panel>
                    </a-collapse>
                  </template>
                  <a-empty
                    v-else
                    :description="$t('legacy.bffpo6')"
                  />
                </a-card>
            </a-tab-pane>
            <a-tab-pane key="skillspector" :tab="$t('decisionFlow.deep')">
                <a-card id="skillspector-section" size="small" :title="$t('legacy.1fvbrzz')">
                  <template v-if="skillspectorAnalysis">
                    <a-alert
                      v-if="skillspectorAnalysis.error"
                      type="warning"
                      show-icon
                      :message="$t('legacy.fe5e82')"
                      :description="deepScanText(skillspectorAnalysis.error)"
                      style="margin-bottom: 12px"
                    />
                    <a-descriptions :column="{ xs: 1, sm: 2 }" size="small" bordered>
                      <a-descriptions-item :label="$t('legacy.1ecjgmg')">
                        <a-tag :color="skillspectorAnalysis.available ? 'green' : 'default'">
                          {{ skillspectorAnalysis.available ? $t('legacy.18ety4i') : $t('legacy.buf4kb') }}
                        </a-tag>
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.15n4i96')">{{ skillspectorAnalysis.risk_score ?? '-' }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1mlpede')">
                        <a-tag :color="severityColor(skillspectorEffectiveSeverity)">
                          {{ severityDisplay(skillspectorEffectiveSeverity) }}
                        </a-tag>
                      </a-descriptions-item>
                      <a-descriptions-item v-if="skillspectorRawSeverity && skillspectorRawSeverity !== skillspectorEffectiveSeverity" :label="$t('legacy.tofxxa')">
                        {{ severityDisplay(skillspectorRawSeverity) }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1qgeq0p')">{{ recommendationDisplay(skillspectorAnalysis.risk_recommendation) }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.l6iuzr')">{{ skillspectorFindings.length }}</a-descriptions-item>
                      <a-descriptions-item v-if="skillspectorAnalysis.suppressed_findings_count" :label="$t('legacy.lglj70')">
                        {{ skillspectorAnalysis.suppressed_findings_count }}
                      </a-descriptions-item>
                    </a-descriptions>
                    <a-collapse v-if="skillspectorAnalysis.suppressed_findings_count" style="margin-top: 12px">
                      <a-collapse-panel key="suppressed" :header="$t('skillDetail.suppressed.title', { count: skillspectorAnalysis.suppressed_findings_count })">
                        <a-alert
                          v-if="skillspectorSuppressedFindings.length !== skillspectorAnalysis.suppressed_findings_count"
                          type="info"
                          show-icon
                          :message="$t('skillDetail.suppressed.missing')"
                          style="margin-bottom: 12px"
                        />
                        <!-- 噪声明细沿用发现项布局，行号独立显示，便于核对过滤位置。 -->
                        <a-list v-if="skillspectorSuppressedFindings.length" :data-source="skillspectorSuppressedFindings" :pagination="{ pageSize: 5, size: 'small', hideOnSinglePage: true }" bordered size="small">
                          <template #renderItem="{ item }">
                            <a-list-item>
                              <div style="width: 100%; overflow-wrap: anywhere">
                                <a-space wrap>
                                  <a-tag :color="severityColor(item.severity)">{{ severityDisplay(item.severity) }}</a-tag>
                                  <a-tag>{{ item.rule_id || '-' }}</a-tag>
                                  <strong>{{ findingTitle(item) }}</strong>
                                  <a-button v-if="item.file" type="link" size="small" style="padding: 0; white-space: normal; height: auto; text-align: left" @click="openFileViewer(item.file)">{{ item.file }}</a-button>
                                </a-space>
                                <!-- PDF 二进制解码行号无法用于文件定位，仅在明细展示时隐藏。 -->
                                <div v-if="item.line != null && !/\.pdf$/i.test(item.file || '')" class="muted" style="margin-top: 4px">{{ $t('skillDetail.suppressed.lines') }}: {{ item.line }}</div>
                                <!-- 原因编码缺少对应译文时统一显示未知，兼容报告字段缺失和版本差异。 -->
                                <div style="margin-top: 6px">{{ $t('skillDetail.suppressed.reason') }}: {{ $te(`skillDetail.suppressed.reasons.${item.suppression_reason}`) ? $t(`skillDetail.suppressed.reasons.${item.suppression_reason}`) : $t('skillDetail.suppressed.unknown') }}</div>
                              </div>
                            </a-list-item>
                          </template>
                        </a-list>
                      </a-collapse-panel>
                    </a-collapse>
                    <a-collapse v-if="skillspectorFindings.length" v-model:activeKey="skillspectorFindingsActiveKey" style="margin-top: 12px">
                      <a-collapse-panel
                        v-for="group in groupedSkillspectorFindings"
                        :key="`skillspector-${group.key}`"
                        :header="`${group.label}（${group.items.length}）`"
                      >
                        <div v-for="section in group.sections" :key="section.key" class="finding-section">
                          <div class="finding-section-title">{{ section.label }}（{{ section.items.length }}）</div>
                          <a-list :data-source="section.items" bordered size="small">
                            <template #renderItem="{ item }">
                              <a-list-item>
                                <div style="width: 100%">
                                  <a-space wrap>
                                    <a-tag :color="severityColor(item.severity)">{{ item.severity || '-' }}</a-tag>
                                    <a-tag color="default">{{ item.rule || item.rule_id || '-' }}</a-tag>
                                    <strong>{{ findingTitle(item) }}</strong>
                                    <a-button
                                      v-if="item.file"
                                      type="link"
                                      size="small"
                                      style="padding: 0"
                                      @click="openFileViewer(item.file)"
                                    >
                                      {{ item.file }}{{ item.line || item.start_line ? `:${item.line || item.start_line}` : '' }}
                                    </a-button>
                                    <a-tag v-if="findingPolicyLabel(item)" color="cyan">{{ text('策略项', 'Policy Category') }}: {{ findingPolicyLabel(item) }}</a-tag>
                                    <a-tag v-if="item.aggregate_count > 1" color="blue">{{ text(`命中 ${item.aggregate_count} 处`, `${item.aggregate_count} matches`) }}</a-tag>
                                  </a-space>
                                  <div v-if="item.aggregate_lines?.length" class="muted" style="margin-top: 4px">
                                    {{ text('行号', 'Lines') }}: {{ formatAggregateLines(item.aggregate_lines) }}
                                  </div>
                                  <div v-if="item.message || item.explanation" style="margin-top: 6px">
                                    {{ deepScanText(bilingualText(item.message || item.explanation)) }}
                                  </div>
                                  <div v-if="item.remediation" style="margin-top: 6px; color: #8c8c8c">
                                    {{ text('建议', 'Recommendation') }}: {{ deepScanText(bilingualText(item.remediation)) }}
                                  </div>
                                </div>
                              </a-list-item>
                            </template>
                          </a-list>
                        </div>
                      </a-collapse-panel>
                    </a-collapse>
                  </template>
                  <a-empty v-else :description="$t('legacy.pip45f')" />
                </a-card>
            </a-tab-pane>
            <a-tab-pane key="sandbox" :tab="$t('decisionFlow.sandbox')">
                <a-card id="sandbox-section" size="small" :title="$t('legacy.256glc')">
                  <template v-if="sandboxAnalysis">
                    <a-alert
                      :type="sandboxRiskAlertType"
                      show-icon
                      :message="text(`风险等级：${sandboxDisplayRiskLevel} / 最高严重级别：${sandboxDisplayMaxSeverity}`, `Risk Level: ${sandboxDisplayRiskLevel} / Maximum Severity: ${sandboxDisplayMaxSeverity}`)"
                      :description="sandboxDisplaySummary"
                    />
                    <a-list
                      v-if="sandboxSignals.length"
                      style="margin-top: 12px"
                      :header="$t('legacy.yq0ehw')"
                      :data-source="sandboxSignals"
                      bordered
                      size="small"
                    >
                      <template #renderItem="{ item }">
                        <a-list-item>
                          <div style="width: 100%">
                            <a-space wrap>
                              <a-tag :color="severityColor(item.severity)">{{ item.severity }}</a-tag>
                              <a-tag color="default">{{ bilingualText(item.category) }}</a-tag>
                              <strong>{{ bilingualText(item.message) }}</strong>
                            </a-space>
                            <div v-if="item.evidence" class="evidence-box">
                              <div class="evidence-title">{{ $t("legacy.1kyo8cx") }}</div>
                              <div
                                v-for="line in sandboxEvidenceLines(item.evidence)"
                                :key="line"
                                class="evidence-line"
                              >
                                {{ line }}
                              </div>
                            </div>
                          </div>
                        </a-list-item>
                      </template>
                    </a-list>
                    <a-empty
                      v-else
                      style="margin-top: 12px"
                      :description="$t('legacy.166yan')"
                    />
                    <a-collapse style="margin-top: 12px">
                      <a-collapse-panel key="sandbox-debug" :header="$t('legacy.enkq9u')">
                        <a-descriptions :column="{ xs: 1, sm: 2 }" size="small" bordered>
                          <a-descriptions-item :label="$t('legacy.2xyc8z')">{{ sandboxAnalysis.executed ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-descriptions-item>
                          <a-descriptions-item><template #label><SandboxDebugHelp field="runtime" :value="sandboxRuntime" label>{{ $t('skillDetail.sandboxRuntime') }}</SandboxDebugHelp></template><SandboxDebugHelp field="runtime" :value="sandboxRuntime" /></a-descriptions-item>
                          <a-descriptions-item><template #label><SandboxDebugHelp field="entrypoint" :value="sandboxAnalysis.entrypoint" label>{{ $t('legacy.1dltjhr') }}</SandboxDebugHelp></template>
                            <a-button
                              v-if="sandboxAnalysis.entrypoint"
                              type="link"
                              style="padding: 0"
                              @click="openFileViewer(sandboxAnalysis.entrypoint)"
                            >
                              {{ sandboxAnalysis.entrypoint }}
                            </a-button>
                            <SandboxDebugHelp v-else field="entrypoint" />
                          </a-descriptions-item>
                          <a-descriptions-item><template #label><SandboxDebugHelp field="target" :value="sandboxTarget" label>{{ sandboxTargetLabel }}</SandboxDebugHelp></template>
                            <SandboxDebugHelp field="target" :value="sandboxTarget" />
                          </a-descriptions-item>
                          <a-descriptions-item>
                            <template #label><SandboxDebugHelp field="strategy" label>{{ $t('legacy.1abimny') }}</SandboxDebugHelp></template>
                            <SandboxDebugHelp field="strategy" :value="sandboxAnalysis.probe_strategy || '-'" /></a-descriptions-item>
                          <a-descriptions-item>
                            <template #label><SandboxDebugHelp field="args" :value="sandboxAnalysis.probe_args" label>{{ $t('legacy.hvs01l') }}</SandboxDebugHelp></template>

                            <SandboxDebugHelp field="args" :value="Array.isArray(sandboxAnalysis.probe_args) && sandboxAnalysis.probe_args.length ? sandboxAnalysis.probe_args.join(' ') : '-'" />
                          </a-descriptions-item>
                          <a-descriptions-item>
                            <template #label><SandboxDebugHelp field="exit" label>{{ $t('legacy.1cjrdy2') }}</SandboxDebugHelp></template>
                            <SandboxDebugHelp field="exit" :value="sandboxAnalysis.exit_code ?? '-'" /></a-descriptions-item>
                          <a-descriptions-item :label="$t('legacy.181sskz')">{{ sandboxAnalysis.timed_out ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-descriptions-item>
                          <a-descriptions-item><template #label><SandboxDebugHelp field="duration" :value="sandboxAnalysis.duration_ms" label>{{ $t('legacy.12sj4tc') }}</SandboxDebugHelp></template><SandboxDebugHelp field="duration" :value="sandboxAnalysis.duration_ms ?? '-'" /> ms</a-descriptions-item>
                          <a-descriptions-item :label="$t('legacy.1v67ot2')">{{ $t('skillDetail.networkAttempts', { count: sandboxAnalysis.network_attempts ?? 0 }) }}</a-descriptions-item>
                          <a-descriptions-item :label="$t('skillDetail.sandboxErrorOutput')" :span="2">
                            <!-- 保留 stderr 原文，方便查看执行异常；未记录时留空。 -->
                            <pre v-if="sandboxAnalysis.stderr" class="sandbox-error-output">{{ sandboxAnalysis.stderr }}</pre>
                          </a-descriptions-item>
                          <a-descriptions-item v-if="sandboxAnalysis.reason" :label="$t('legacy.1mi4vdj')" :span="2">
                            {{ platformResultText(sandboxAnalysis.reason) }}
                          </a-descriptions-item>
                          <a-descriptions-item v-if="sandboxAnalysis.recommendation" :label="$t('legacy.1qgeq0p')" :span="2">
                            {{ platformResultText(sandboxAnalysis.recommendation) }}
                          </a-descriptions-item>
                        </a-descriptions>
                        <a-list
                          v-if="sandboxDiagnosticSignals.length"
                          style="margin-top: 12px"
                          :header="$t('legacy.1jz86ze')"
                          :data-source="sandboxDiagnosticSignals"
                          bordered
                          size="small"
                        >
                          <template #renderItem="{ item }">
                            <a-list-item>
                              <div style="width: 100%">
                                <a-space wrap>
                                  <a-tag :color="severityColor(item.severity)">{{ item.severity || 'INFO' }}</a-tag>
                                  <a-tag color="default">{{ bilingualText(item.category) }}</a-tag>
                                  <strong>{{ bilingualText(item.message) }}</strong>
                                </a-space>
                                <div v-if="item.evidence" class="evidence-box">
                                  <div class="evidence-title">{{ $t("legacy.1kyo8cx") }}</div>
                                  <div
                                    v-for="line in sandboxEvidenceLines(item.evidence)"
                                    :key="line"
                                    class="evidence-line"
                                  >
                                    {{ line }}
                                  </div>
                                </div>
                              </div>
                            </a-list-item>
                          </template>
                        </a-list>
                        <a-table
                          v-if="sandboxProbeResults.length"
                          style="margin-top: 12px"
                          :data-source="sandboxProbeResults"
                          :columns="sandboxProbeColumns"
                          row-key="key"
                          size="small"
                          bordered
                          :pagination="false"
                        >
                          <template #title> {{ $t("legacy.yq0ehw") }} </template>
                          <template #headerCell="{ column }">
                            <SandboxDebugHelp v-if="sandboxHeaderHelp(column.key)" :field="sandboxHeaderHelp(column.key)" label>{{ column.title }}</SandboxDebugHelp>
                            <span v-else-if="column.key">{{ column.title }}</span>
                          </template>
                          <template #bodyCell="{ column, record }">
                            <template v-if="column.key === 'probe'">
                              <a-space direction="vertical" size="small">
                                <strong><SandboxDebugHelp field="probe" :value="record.probe_name" /></strong>
                                <span class="muted"><SandboxDebugHelp field="description" :value="record.probe_description || '-'" /></span>
                              </a-space>
                            </template>
                            <template v-else-if="column.key === 'entrypoint'">
                              <a-button
                                v-if="record.probe_entrypoint"
                                type="link"
                                style="padding: 0"
                                @click="openFileViewer(record.probe_entrypoint)"
                              >
                                {{ record.probe_entrypoint }}
                              </a-button>
                              <SandboxDebugHelp v-else field="entrypoint" />
                            </template>
                            <template v-else-if="column.key === 'command'">
                              <code class="inline-command"><SandboxDebugHelp field="command" :value="formatSandboxCommand(record)" /></code>
                            </template>
                            <template v-else-if="column.key === 'exit_code'">
                              <a-tag :color="record.exit_code === 0 ? 'green' : 'orange'"><SandboxDebugHelp field="exit" :value="record.exit_code ?? '-'" /></a-tag>
                            </template>
                            <template v-else-if="column.key === 'duration_ms'">
                              <SandboxDebugHelp field="duration" :value="record.duration_ms" /> ms
                            </template>
                            <template v-else-if="column.key === 'timeout'">
                              <a-tag :color="record.timed_out ? 'red' : 'green'">{{ record.timed_out ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-tag>
                            </template>
                            <template v-else-if="column.key === 'result'">
                              <a-tag :color="sandboxProbeResultTag(record).color">
                                {{ sandboxProbeResultTag(record).text }}
                              </a-tag>
                            </template>
                          </template>
                          <template #expandedRowRender="{ record }">
                        <a-descriptions :column="{ xs: 1, sm: 2 }" size="small" bordered>
                          <a-descriptions-item :span="2"><template #label><SandboxDebugHelp field="command" :value="formatSandboxCommand(record)" label>{{ $t('legacy.54f4h3') }}</SandboxDebugHelp></template>
                            <pre class="command-block"><SandboxDebugHelp field="command" :value="formatSandboxCommand(record)" /></pre>
                          </a-descriptions-item>
                          <a-descriptions-item>
                            <template #label><SandboxDebugHelp field="source" label>{{ $t('legacy.c8d7bb') }}</SandboxDebugHelp></template>
                            <SandboxDebugHelp field="source" :value="record.probe_generated_by || '-'" /></a-descriptions-item>
                          <a-descriptions-item><template #label><SandboxDebugHelp field="runtime" :value="record.runtime || sandboxAnalysis.runtime" label>{{ $t('legacy.1sdwzrx') }}</SandboxDebugHelp></template><SandboxDebugHelp field="runtime" :value="record.runtime || sandboxAnalysis.runtime || '-'" /></a-descriptions-item>
                          <a-descriptions-item><template #label><SandboxDebugHelp field="duration" :value="record.duration_ms" label>{{ $t('legacy.12sj4tc') }}</SandboxDebugHelp></template><SandboxDebugHelp field="duration" :value="record.duration_ms ?? '-'" /> ms</a-descriptions-item>
                          <a-descriptions-item :label="$t('legacy.1v67ot2')">{{ $t('skillDetail.networkAttempts', { count: record.network_attempts ?? 0 }) }}</a-descriptions-item>
                          <a-descriptions-item :label="$t('skillDetail.sandboxErrorOutput')" :span="2">
                            <!-- 每条 Probe 展示自身 stderr，方便核对该次执行异常。 -->
                            <pre v-if="record.stderr" class="sandbox-error-output">{{ record.stderr }}</pre>
                          </a-descriptions-item>
                          <a-descriptions-item :label="$t('legacy.1suldox')" :span="2">
                            {{ sandboxProbeResultText(record) }}
                          </a-descriptions-item>
                        </a-descriptions>
                        <a-alert
                          v-if="isSandboxProbeInputMissing(record)"
                          style="margin-top: 12px"
                          type="info"
                          show-icon
                          :message="$t('legacy.1c0iwtv')"
                          :description="$t('legacy.708edr')"
                        />
                        <a-alert
                          v-else-if="record.exit_code != null && record.exit_code !== 0"
                          style="margin-top: 12px"
                          type="info"
                          show-icon
                          :message="$t('legacy.im1knm')"
                          :description="$t('legacy.dfsc95')"
                        />
                          </template>
                        </a-table>
                      </a-collapse-panel>
                    </a-collapse>
                  </template>
                  <a-empty
                    v-else
                    :description="$t('legacy.13s2o01')"
                  />
                </a-card>
            </a-tab-pane>
            <a-tab-pane key="llm" :tab="$t('decisionFlow.llmAnalysis')">
                <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
                  <a-alert v-if="llmDisabled" type="info" show-icon :message="$t('skillDetail.llmDisabled')" :description="$t('skillDetail.llmDisabledReason')" />
                  <a-alert v-else-if="llmFailure !== null" type="error" show-icon :message="$t('skillDetail.llmFailed')">
                    <template #description><div style="white-space: pre-wrap; overflow-wrap: anywhere">{{ llmFailure || $t('skillDetail.llmFailureUnavailable') }}</div></template>
                  </a-alert>
                  <template v-else-if="llmAnalysis">
                    <a-card id="llm-section" size="small" :title="$t('legacy.1iy14k9')">
                      <a-descriptions :column="{ xs: 1, sm: 2 }" size="small" bordered style="margin-bottom: 12px">
                        <a-descriptions-item :label="$t('legacy.1l721lr')">{{ llmAnalysis.provider || '-' }}</a-descriptions-item>
                        <a-descriptions-item :label="$t('legacy.1ow6qt')">{{ llmAnalysis.model || '-' }}</a-descriptions-item>
                        <a-descriptions-item :label="$t('legacy.c68fez')">
                          <a-tag v-if="llmAnalysis.risk_level === 'malicious'" color="red">{{ riskDisplay(llmAnalysis.risk_level) }}</a-tag>
                          <a-tag v-else-if="llmAnalysis.risk_level === 'suspicious'" color="orange">{{ riskDisplay(llmAnalysis.risk_level) }}</a-tag>
                          <a-tag v-else-if="llmAnalysis.risk_level === 'benign'" color="green">{{ riskDisplay(llmAnalysis.risk_level) }}</a-tag>
                          <a-tag v-else color="default">{{ riskDisplay(llmAnalysis.risk_level) }}</a-tag>
                        </a-descriptions-item>
                      </a-descriptions>
                      <div v-if="llmAnalysis.report" class="llm-explanation" v-html="llmExplanationHtml" />
                      <template v-if="llmAnalysis.risk_level === 'malicious' && llmAnalysis.attack_chain?.length">
                        <a-divider />
                        <div>
                          <h4 style="margin-bottom: 12px">{{ $t("legacy.bayp6x") }}</h4>
                          <AttackChainGraph :attack-chain="llmAnalysis.attack_chain" />
                        </div>
                      </template>
                    </a-card>
                  </template>
                  <a-empty v-else :description="$t('legacy.mbiky1')" />
                </a-skeleton>
            </a-tab-pane>
          </a-tabs>
          <a-collapse class="scan-execution-info" style="margin-top: 16px">
            <a-collapse-panel key="execution" :header="$t('decisionFlow.executionInfo')">
              <a-descriptions :column="{ xs: 1, sm: 1, md: 1, lg: 1, xl: 2, xxl: 2 }" size="small" bordered>
                <a-descriptions-item :label="$t('decisionFlow.findingCount')">{{ detail?.vetting?.findings_count ?? $t('decisionFlow.unrecorded') }}</a-descriptions-item>
                <a-descriptions-item :label="$t('decisionFlow.duration')">{{ scanDurationDisplay }}</a-descriptions-item>
                <a-descriptions-item :label="$t('decisionFlow.analyzers')">{{ analyzerNames.join(', ') || $t('decisionFlow.unrecorded') }}</a-descriptions-item>
                <a-descriptions-item :label="$t('decisionFlow.resultReuse')">{{ $t(detail?.scan_reused === true ? 'decisionFlow.reusedResult' : detail?.scan_reused === false ? 'decisionFlow.newScan' : 'decisionFlow.unrecorded') }}</a-descriptions-item>
                <a-descriptions-item :label="$t('decisionFlow.cacheKey')">{{ detail?.scan_cache_key || $t('decisionFlow.unrecorded') }}</a-descriptions-item>
              </a-descriptions>
            </a-collapse-panel>
          </a-collapse>
        </a-tab-pane>

        <a-tab-pane key="governance-card" :tab="$t('legacy.11y6y7p')">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button @click="fetchGovernanceCard" :loading="loadingGovernanceCard">{{ $t("legacy.12qo56a") }}</a-button>
            <a-button v-if="hasAccess('skills:update')" type="primary" @click="handleRefreshGovernanceCard" :loading="loadingGovernanceCard"> {{ $t("legacy.1oqld67") }} </a-button>
            <a-radio-group v-model:value="governanceCardViewMode" button-style="solid">
              <a-radio-button value="preview">{{ $t("legacy.k2jp4x") }}</a-radio-button>
              <a-radio-button value="raw">{{ $t("legacy.9lvlaj") }}</a-radio-button>
            </a-radio-group>
            <span style="color: #8c8c8c">
              {{ governanceCard?.generated_at
                ? text(
                  `生成时间：${formatDateTime(governanceCard.generated_at)}`,
                  `Generated: ${formatDateTime(governanceCard.generated_at)}`,
                )
                : $t('legacy.1gshff6') }}
            </span>
          </a-space>
          <a-skeleton v-if="loadingGovernanceCard && !governanceCard" active />
          <template v-else-if="governanceCardViewMode === 'preview'">
            <div class="markdown-body governance-card-preview" v-html="governanceCardHtml" />
          </template>
          <template v-else>
            <div class="code-preview">
              <div v-for="line in governanceCardLines" :key="line.no" class="code-line">
                <span class="line-no">{{ line.no }}</span>
                <span class="line-text">{{ line.text || ' ' }}</span>
              </div>
            </div>
          </template>
        </a-tab-pane>

        <a-tab-pane key="signature" :tab="$t('legacy.y6whtf')">
          <a-descriptions :column="1" size="small" bordered>
            <!-- 内容指纹在导入时生成，展示使用当前版本的指纹字段。 -->
            <a-descriptions-item :label="$t('skillDetail.fingerprintExists')">{{ detail?.content_fingerprint ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-descriptions-item>
            <a-descriptions-item :label="$t('skillDetail.fingerprintPreview')">{{ detail?.content_fingerprint ? `${detail.content_fingerprint.slice(0, 24)}...` : '-' }}</a-descriptions-item>
            <a-descriptions-item :label="$t('legacy.1a9csig')">{{ signatureResult ? (signatureResult.valid ? $t('legacy.j666m6') : $t('legacy.12db3qz')) : $t('legacy.39zt54') }}</a-descriptions-item>
          </a-descriptions>
        </a-tab-pane>

        <a-tab-pane key="content" :tab="$t('legacy.76rr28')">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button @click="fetchSkillContent" :loading="loadingContent">{{ $t("legacy.1hagldm") }}</a-button>
            <a-radio-group v-model:value="contentViewMode" button-style="solid">
              <a-radio-button value="preview">{{ $t("legacy.k2jp4x") }}</a-radio-button>
              <a-radio-button value="raw">{{ $t("legacy.9lvlaj") }}</a-radio-button>
            </a-radio-group>
          </a-space>

          <a-alert
            v-if="skillContent?.encoding"
            type="info"
            show-icon
            :message="text(`编码：${skillContent.encoding}`, `Encoding: ${skillContent.encoding}`)"
            style="margin-bottom: 12px"
          />

          <a-skeleton v-if="loadingContent && !skillContent" active />
          <template v-else-if="contentViewMode === 'preview'">
            <a-card
              v-if="skillFrontmatter"
              size="small"
              :title="$t('legacy.168y9p7')"
              style="margin-bottom: 12px"
            >
              <pre class="frontmatter-box">{{ skillFrontmatter }}</pre>
            </a-card>
            <div class="markdown-body" v-html="skillContentHtml" />
          </template>
          <div v-else class="code-preview">
            <div v-for="line in skillContentLines" :key="line.no" class="code-line">
              <span class="line-no">{{ line.no }}</span>
              <span class="line-text">{{ line.text || ' ' }}</span>
            </div>
          </div>
        </a-tab-pane>

        <a-tab-pane key="files" :tab="$t('legacy.gpyzjr')">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button @click="fetchSkillFiles" :loading="loadingFiles">{{ $t("legacy.17oz484") }}</a-button>
            <span style="color: #8c8c8c">{{ $t("legacy.1vsm2qk") }} {{ skillFiles.length }} {{ $t("legacy.15u4aw8") }}</span>
          </a-space>
          <a-table
            :data-source="skillFiles"
            :loading="loadingFiles"
            :columns="fileColumns"
            rowKey="path"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'path'">
                <a-button type="link" style="padding: 0" @click="openFileViewer(record.path)">{{ record.path }}</a-button>
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="versions" :tab="$t('skillVersions.versions')">
          <a-alert
            type="info"
            show-icon
            :message="$t('skillVersions.trustedOnlyHint')"
            style="margin-bottom: 12px"
          />
          <a-table
            :data-source="skillVersions"
            :columns="versionColumns"
            rowKey="version_id"
            :loading="loadingVersions"
            :pagination="false"
            :scroll="{ x: 1410 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'version'">
                <a-space wrap>
                  <strong>v{{ record.version_no }}</strong>
                  <a-tag v-if="record.latest" color="blue">{{ $t('skillVersions.latest') }}</a-tag>
                  <a-tag v-if="record.latest_trusted" color="green">{{ $t('skillVersions.latestTrusted') }}</a-tag>
                  <a-tag v-if="record.rescanned" color="purple">{{ $t('skillVersions.rescanned') }}</a-tag>
                </a-space>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status, record)">{{ statusDisplay(record.status, record) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'risk'">
                <div class="version-risk-chain">
                  <div class="version-risk-stage">
                    <small>{{ $t('skillVersions.staticAssessment') }}</small>
                    <a-tag :color="riskColor(versionRiskChain(record).static_risk_level)">
                      {{ riskDisplay(versionRiskChain(record).static_risk_level) }}
                    </a-tag>
                  </div>
                  <span class="version-risk-arrow" aria-hidden="true">→</span>
                  <div class="version-risk-stage">
                    <small>{{ $t('skillVersions.llmReview') }}</small>
                    <a-tooltip :title="versionRiskChain(record).llm_note || versionRiskChain(record).downgrade_reason || ''">
                      <a-tag :color="llmStageColor(versionRiskChain(record))">
                        {{ llmStageLabel(versionRiskChain(record)) }}
                      </a-tag>
                    </a-tooltip>
                  </div>
                  <span class="version-risk-arrow" aria-hidden="true">→</span>
                  <div class="version-risk-stage">
                    <small>{{ $t('skillVersions.finalAssessment') }}</small>
                    <a-tag :color="riskColor(versionRiskChain(record).final_risk_level)">
                      {{ riskDisplay(versionRiskChain(record).final_risk_level) }}
                    </a-tag>
                  </div>
                </div>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button size="small" @click="downloadVersion(record)">{{ $t('skillVersions.download') }}</a-button>
                  <a-button size="small" @click="openScanRuns(record)">{{ $t('skillVersions.scanRuns') }}</a-button>
                  <a-button v-if="hasAccess('skills:scan')"
                    size="small"
                    :loading="rescanningVersionId === record.version_id"
                    :disabled="record.scan_pending"
                    @click="rescanVersion(record)"
                  >
                    {{ record.scan_pending ? $t('skillVersions.scanning') : $t('skillVersions.rescan') }}
                  </a-button>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="diff" :tab="$t('skillVersions.diff')">
          <div class="version-diff-toolbar">
            <a-space wrap>
              <span>{{ $t('skillVersions.baseVersion') }}</span>
              <a-select v-model:value="diffBaseVersion" style="width: 190px">
                <a-select-option v-for="item in skillVersions" :key="item.version_id" :value="item.version_id">
                  v{{ item.version_no }}{{ item.source_version ? ` · ${item.source_version}` : '' }}
                </a-select-option>
              </a-select>
              <a-tooltip :title="$t('skillVersions.swapVersions')">
                <a-button
                  class="version-diff-swap"
                  shape="circle"
                  :aria-label="$t('skillVersions.swapVersions')"
                  :disabled="!diffBaseVersion || !diffTargetVersion"
                  @click="swapDiffVersions"
                >
                  <template #icon><SwapOutlined /></template>
                </a-button>
              </a-tooltip>
              <span>{{ $t('skillVersions.targetVersion') }}</span>
              <a-select v-model:value="diffTargetVersion" style="width: 190px">
                <a-select-option v-for="item in skillVersions" :key="item.version_id" :value="item.version_id">
                  v{{ item.version_no }}{{ item.source_version ? ` · ${item.source_version}` : '' }}
                </a-select-option>
              </a-select>
            </a-space>
            <a-radio-group v-model:value="diffViewMode" button-style="solid">
              <a-radio-button value="side-by-side">{{ $t('skillVersions.sideBySide') }}</a-radio-button>
              <a-radio-button value="inline">{{ $t('skillVersions.inline') }}</a-radio-button>
            </a-radio-group>
          </div>
          <a-alert v-if="versionDiffError" type="error" show-icon :message="$t('skillVersions.diffLoadFailed')">
            <template #action><a-button size="small" @click="fetchVersionDiff">{{ $t('skillDetail.retryDiff') }}</a-button></template>
          </a-alert>
          <a-empty v-else-if="!versionDiffItems.length && !loadingVersionDiff && !loadingVersions" :description="$t('skillVersions.noChanges')" />
          <a-spin v-else :spinning="loadingVersionDiff || loadingVersions">
            <a-skeleton v-if="!versionDiffItems.length" active :paragraph="{ rows: 4 }" />
            <div v-if="selectedVersionDiffItem" class="version-diff-file">
              <div class="version-diff-file-toolbar">
                <a-space wrap>
                  <span>{{ $t('skillVersions.file') }}</span>
                  <a-select
                    v-model:value="selectedDiffPath"
                    show-search
                    option-filter-prop="label"
                    class="version-diff-file-select"
                    :placeholder="$t('skillVersions.selectFile')"
                  >
                    <a-select-option
                      v-for="item in versionDiffItems"
                      :key="item.path"
                      :value="item.path"
                      :label="item.path"
                    >
                      {{ item.path }}
                    </a-select-option>
                  </a-select>
                </a-space>
                <a-space>
                  <a-tag>{{ diffFileStatus(selectedVersionDiffItem.status) }}</a-tag>
                  <a-tag color="green">+{{ selectedVersionDiffItem.additions }}</a-tag>
                  <a-tag color="red">-{{ selectedVersionDiffItem.deletions }}</a-tag>
                </a-space>
              </div>
              <div v-if="diffViewMode === 'side-by-side'" class="version-diff-scroll">
                <div class="version-diff-grid version-diff-grid--header">
                  <div>{{ $t('skillVersions.before') }}</div>
                  <div>{{ $t('skillVersions.after') }}</div>
                </div>
                <div
                  v-for="row in selectedVersionDiffItem.diffRows"
                  :key="row.key"
                  class="version-diff-grid version-diff-row"
                  :class="{ 'version-diff-row--hunk': row.kind === 'hunk' }"
                >
                  <template v-if="row.kind === 'hunk'">
                    <div class="version-diff-hunk">{{ row.text }}</div>
                  </template>
                  <template v-else>
                    <div class="version-diff-line" :class="`version-diff-line--${row.left?.kind || 'empty'}`">
                      <span class="version-diff-line-no">{{ row.left?.lineNo || '' }}</span>
                      <span class="version-diff-marker">{{ row.left?.marker || '' }}</span>
                      <span class="version-diff-text">{{ row.left?.text || ' ' }}</span>
                    </div>
                    <div class="version-diff-line" :class="`version-diff-line--${row.right?.kind || 'empty'}`">
                      <span class="version-diff-line-no">{{ row.right?.lineNo || '' }}</span>
                      <span class="version-diff-marker">{{ row.right?.marker || '' }}</span>
                      <span class="version-diff-text">{{ row.right?.text || ' ' }}</span>
                    </div>
                  </template>
                </div>
              </div>
              <div v-else class="version-diff-scroll version-diff-scroll--inline">
                <div
                  v-for="row in selectedVersionDiffItem.inlineRows"
                  :key="row.key"
                  class="version-diff-line version-diff-line--inline"
                  :class="`version-diff-line--${row.kind}`"
                >
                  <span class="version-diff-line-no">{{ row.oldLineNo || '' }}</span>
                  <span class="version-diff-line-no">{{ row.newLineNo || '' }}</span>
                  <span class="version-diff-marker">{{ row.marker }}</span>
                  <span class="version-diff-text">{{ row.text || ' ' }}</span>
                </div>
              </div>
            </div>
          </a-spin>
        </a-tab-pane>

        <a-tab-pane key="audit" :tab="$t('legacy.7wyi9c')">
          <a-table :loading="loadingAudit" :data-source="auditRows" :columns="auditColumns" rowKey="event_id" :pagination="{ pageSize: 5 }">
            <template #bodyCell="{ column, record }">
              <span v-if="column.key === 'event_type'">{{ auditEventLabel(record.event_type) }}</span>
              <span v-else-if="column.key === 'actor'">{{ record.actor || $t('legacy.p0ysv3') }}</span>
              <span v-else-if="column.key === 'details'">{{ formatAuditDetails(record.details) }}</span>
            </template>
          </a-table>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    </a-card>

    <a-modal
      v-model:open="approveModalOpen"
      :title="$t('legacy.1xa4yul')"
      :ok-text="$t('legacy.1srvmx8')"
      :cancel-text="$t('legacy.1589w37')"
      :confirm-loading="actionLoading"
      :ok-button-props="{ disabled: actionLoading || !approvalVersionId || approveTooLong }"
      @ok="submitApprove"
    >
      <a-form layout="vertical">
        <a-alert
          v-if="manualApprovalRequired"
          type="warning"
          show-icon
          :message="$t('legacy.1y2twlp')"
          :description="vettingFailed ? $t('legacy.17wodku') : $t('legacy.afqt0u')"
          style="margin-bottom: 12px"
        />
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('skillVersions.version')">
          <a-input :value="approvalVersionLabel" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1lakt7z')">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1v900uo')" :tooltip="$t('skillDetail.reviewTextHelp', { max: REVIEW_TEXT_LIMIT })" :validate-status="approveTooLong ? 'error' : undefined" :help="$t(approveTooLong ? 'skillDetail.reviewTextCountOver' : 'skillDetail.reviewTextCount', { count: approveTextLength, max: REVIEW_TEXT_LIMIT, excess: approveTextLength - REVIEW_TEXT_LIMIT })">
          <a-textarea v-model:value="approveNote" :rows="4" :placeholder="$t('legacy.y7iiel')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="rejectModalOpen"
      :title="$t('legacy.sgs3in')"
      :ok-text="$t('legacy.iwk43y')"
      :cancel-text="$t('legacy.1589w37')"
      :confirm-loading="actionLoading"
      :ok-button-props="{ disabled: actionLoading || rejectTooLong }"
      @ok="submitReject"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1gs5bzm')">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1l7e57j')" :tooltip="$t('skillDetail.reviewTextHelp', { max: REVIEW_TEXT_LIMIT })" :validate-status="rejectTooLong ? 'error' : undefined" :help="$t(rejectTooLong ? 'skillDetail.reviewTextCountOver' : 'skillDetail.reviewTextCount', { count: rejectTextLength, max: REVIEW_TEXT_LIMIT, excess: rejectTextLength - REVIEW_TEXT_LIMIT })" required>
          <a-textarea v-model:value="rejectReason" :rows="4" :placeholder="$t('legacy.1gqmn09')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="clientInstallOpen"
      :title="$t('legacy.sq6fxa')"
      :ok-text="$t('legacy.1em7bly')"
      :confirm-loading="clientInstallLoading"
      :ok-button-props="{ disabled: clientInstallLoading || !clientInstallTarget }"
      @ok="submitClientInstall"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('skillDetail.installClient')" required>
          <a-select
            v-model:value="clientInstallClient"
            show-search
            option-filter-prop="label"
            :loading="clientInstallLoading"
            :disabled="clientInstallLoading"
            :placeholder="$t('skillDetail.selectInstallClient')"
            @change="clientInstallTarget = undefined"
          >
            <a-select-option v-for="client in managedClients" :key="client.client_id" :value="client.client_id" :label="client.name || client.client_id">
              {{ client.name || client.client_id }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('skillDetail.installAgent')" required>
          <a-select
            v-model:value="clientInstallTarget"
            show-search
            option-filter-prop="label"
            :disabled="!clientInstallClient || clientInstallLoading"
            :placeholder="$t(clientInstallClient ? 'skillDetail.selectInstallAgent' : 'skillDetail.selectClientFirst')"
            :not-found-content="$t('skillDetail.noInstallAgents')"
          >
            <a-select-option v-for="target in clientTargets" :key="target.key" :value="target.key" :label="target.label">
              {{ target.label }}
            </a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="scanRunsOpen"
      :title="$t('skillVersions.scanRuns')"
      :footer="null"
      width="900px"
    >
      <a-table
        :data-source="scanRuns"
        :columns="scanRunColumns"
        rowKey="scan_run_id"
        :loading="loadingScanRuns"
        :pagination="false"
        size="small"
      />
    </a-modal>

    <a-drawer
      v-model:open="fileViewerOpen"
      :title="viewerTitle"
      width="720"
      destroyOnClose
    >
      <a-space style="margin-bottom: 12px" wrap>
        <a-button @click="refreshViewedFile" :loading="loadingFileViewer" :disabled="!viewingFilePath">{{ $t("legacy.rgtjkr") }}</a-button>
        <span style="color: #8c8c8c">{{ viewedFile?.path || viewingFilePath || '-' }}</span>
        <a-tag v-if="viewedFile?.encoding">{{ $t("legacy.11zpbd2") }}{{ viewedFile.encoding }}</a-tag>
      </a-space>
      <div class="code-preview drawer-code-preview">
        <div v-for="line in viewedFileLines" :key="line.no" class="code-line">
          <span class="line-no">{{ line.no }}</span>
          <span class="line-text">{{ line.text || ' ' }}</span>
        </div>
      </div>
    </a-drawer>
  </div>
</template>

<script setup>
import { REVIEW_TEXT_LIMIT, reviewTextLength } from '../utils/reviewText'

import { can as hasAccess } from '../access'
import SkillDecisionFlow from '../components/SkillDecisionFlow.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { CheckCircleOutlined, ExclamationCircleOutlined, SafetyOutlined, SwapOutlined, WarningOutlined } from '@ant-design/icons-vue'
import { marked } from 'marked'

import {
  approveSkill,
  createClientTask,
  downloadSkill,
  exportSkillScanReportPdf,
  getAudit,
  getSkillContent,
  getSkillDetail,
  getSkillFileContent,
  getSkillFiles,
  getSkillGovernanceCard,
  getSkillScanReport,
  getSkillVersionDiff,
  getSkillVersionScanRuns,
  getSkillVersions,
  listClients,
  refreshSkillGovernanceCard,
  rejectSkill,
  rescanSkill,
  verifySkillSignature,
} from '../api'
import { formatDateTime } from '../utils/format'
import { parseUnifiedDiff } from '../utils/diff'
import { analysisState, formatLlmFailureReason, llmFailureReason } from '../utils/decisionFlow'
import { translateDomain } from '../i18n'
import { legacyKey, legacyMessages } from '../i18n/legacy'
import { useLocaleText } from '../i18n/useLocaleText'
import AttackChainGraph from '../components/AttackChainGraph.vue'
import SandboxDebugHelp from '../components/SandboxDebugHelp.vue'

const { isEnglish, phrase, text, t } = useLocaleText()
const route = useRoute()
const router = useRouter()
const skillId = computed(() => route.params.skillId)
const detailPageTitle = computed(() => {
  const name = detail.value?.name || skillId.value
  return text(`Skill 详情：${name}`, `Skill Details: ${name}`)
})
const activeTab = ref(route.query.tab === 'llm' ? 'vetting' : route.query.tab || 'decision')
const summaryStatus = entry => translateDomain('skillStatus', isCancelled(entry) ? 'CANCELLED' : entry?.status, t('decisionFlow.unrecorded'))
const summaryRisk = computed(() => detail.value?.status === 'PENDING'
  ? t('decisionFlow.pending')
  : ['benign', 'suspicious', 'malicious'].includes(detail.value?.risk_level)
    ? t('policySettings.risks.' + detail.value.risk_level)
    : riskDisplay(detail.value?.risk_level))
const openDecisionTrace = async () => {
  activeTab.value = 'decision'
  await nextTick()
  const heading = document.getElementById('decision-title') || document.getElementById('skill-decision-panel')
  heading?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
  heading?.focus({ preventScroll: true })
}
const scanDurationDisplay = computed(() => {
  const seconds = detail.value?.vetting?.scan_duration_seconds
  return Number.isFinite(seconds)
    ? t('decisionFlow.durationValue', { seconds: new Intl.NumberFormat(isEnglish.value ? 'en-US' : 'zh-CN', { maximumFractionDigits: 2 }).format(seconds) })
    : t('decisionFlow.unrecorded')
})
const analysisTab = ref(route.query.tab === 'llm' ? 'llm' : 'rule')
const loading = ref(false)
const loadingScanReport = ref(false)
const scanReportError = ref(false)
const decisionLoading = computed(() => !scanReport.value && (loading.value || loadingScanReport.value))
let scanReportRequestId = 0
const loadingContent = ref(false)
const loadingFiles = ref(false)
const loadingAudit = ref(false)
const loadingVersions = ref(false)
const loadingVersionDiff = ref(false)
const versionDiffError = ref(false)
let detailRequestId = 0
let diffRequestId = 0
let loadedDiffKey = ''
let pendingDiffKey = ''
const loadingScanRuns = ref(false)
const loadingGovernanceCard = ref(false)
const verifyingSignature = ref(false)
const downloadingSkill = ref(false)
const exportingScanReport = ref(false)
const actionLoading = ref(false)
const actionType = ref('')
const detail = ref(null)
const auditRows = ref([])
const scanReport = ref(null)
const governanceCard = ref(null)
const skillContent = ref(null)
const skillFiles = ref([])
const skillVersions = ref([])
const versionDiffItems = ref([])
const scanRuns = ref([])
const scanRunsOpen = ref(false)
const diffBaseVersion = ref('')
const diffTargetVersion = ref('')
const diffViewMode = ref('side-by-side')
const selectedDiffPath = ref('')
const rescanningVersionId = ref('')
const signatureResult = ref(null)
const fileViewerOpen = ref(false)
const loadingFileViewer = ref(false)
const viewingFilePath = ref('')
const viewedFile = ref(null)
const contentViewMode = ref('preview')
const governanceCardViewMode = ref('preview')
const skillspectorFindingsActiveKey = ref([])
const approveModalOpen = ref(false)
const rejectModalOpen = ref(false)
const approveNote = ref('')
const rejectReason = ref('')
const approveTextLength = computed(() => reviewTextLength(approveNote.value))
const rejectTextLength = computed(() => reviewTextLength(rejectReason.value))
const approveTooLong = computed(() => approveTextLength.value > REVIEW_TEXT_LIMIT)
const rejectTooLong = computed(() => rejectTextLength.value > REVIEW_TEXT_LIMIT)
const clientInstallOpen = ref(false)
const clientInstallLoading = ref(false)
const clientInstallClient = ref()
const clientInstallTarget = ref()
const clientInstallVersion = ref('')
const managedClients = ref([])
const clientTargets = computed(() => managedClients.value.filter(client => client.client_id === clientInstallClient.value).flatMap(client =>
  (client.agents || [])
    .filter(agent => agent.skills_path?.trim()
      && agent.capabilities?.path_available !== false
      && agent.skill_management_supported
      && (client.governance_mode !== 'strict' || agent.managed_agent_id))
    .map(agent => ({
      key: `${client.client_id}\x00${agent.agent_type}`,
      label: agent.agent_type,
      clientId: client.client_id,
      agentType: agent.agent_type,
      managedAgentId: agent.managed_agent_id,
    })),
))
const trustedSkillVersions = computed(() =>
  skillVersions.value.filter(item => ['APPROVED', 'DEPLOYED'].includes(item.status)),
)
const currentVersionRecord = computed(() =>
  skillVersions.value.find(item => item.version_id === detail.value?.version_id) || null,
)
const currentVersionId = computed(() => detail.value?.version_id || skillId.value)
const approvalVersionId = computed(() => detail.value?.version_id || '')
const approvalVersionLabel = computed(() => {
  const record = currentVersionRecord.value || detail.value
  if (!record) return ''
  return [
    record.version_no != null ? `v${record.version_no}` : '',
    record.source_version || '',
    approvalVersionId.value,
  ].filter(Boolean).join(' · ')
})

const versionRiskChain = record => record?.risk_chain || {
  static_risk_level: record?.risk_level,
  llm_status: 'not_run',
  llm_risk_level: null,
  final_risk_level: record?.risk_level,
}

const llmStageLabel = chain => {
  if (chain.llm_status === 'completed') return chain.llm_risk_level ? riskDisplay(chain.llm_risk_level) : t('skillVersions.llmCompleted')
  if (chain.llm_status === 'disabled') return t('skillColumns.stepStates.disabled')
  if (chain.llm_status === 'skipped') return t('skillVersions.llmSkipped')
  if (chain.llm_status === 'failed') return t('skillVersions.llmFailed')
  return t('skillVersions.llmNotRun')
}

const llmStageColor = chain => {
  if (chain.llm_status === 'completed') return riskColor(chain.llm_risk_level)
  if (chain.llm_status === 'skipped') return 'orange'
  if (chain.llm_status === 'failed') return 'red'
  return 'default'
}

const switchVersion = async versionId => {
  if (!versionId || versionId === detail.value?.version_id) return
  await router.push({
    name: 'skill-detail',
    params: { skillId: versionId },
    query: route.query,
  })
}

const selectedVersionDiffItem = computed(() => {
  const item = versionDiffItems.value.find(row => row.path === selectedDiffPath.value)
    || versionDiffItems.value[0]
  if (!item) return null
  const parsed = parseUnifiedDiff(item.diff)
  return {
    ...item,
    diffRows: parsed.sideRows,
    inlineRows: parsed.inlineRows,
  }
})

const diffFileStatus = status => ({
  added: t('skillVersions.fileAdded'),
  deleted: t('skillVersions.fileDeleted'),
  changed: t('skillVersions.fileChanged'),
}[status] || status)

const auditColumns = computed(() => [
  { title: text('时间', 'Time'), dataIndex: 'timestamp', key: 'timestamp', width: 180, customRender: ({ text: value }) => formatDateTime(value) },
  { title: text('事件', 'Event'), dataIndex: 'event_type', key: 'event_type', width: 180 },
  { title: text('操作人', 'Operator'), dataIndex: 'actor', key: 'actor', width: 120 },
  { title: text('详情', 'Details'), dataIndex: 'details', key: 'details' },
])

const fileColumns = computed(() => [
  { title: text('路径', 'Path'), dataIndex: 'path', key: 'path' },
  { title: text('大小', 'Size'), dataIndex: 'size_bytes', key: 'size_bytes', width: 140, customRender: ({ text: value }) => formatFileSize(value) },
  { title: text('修改时间', 'Modified At'), dataIndex: 'modified_at', key: 'modified_at', width: 220, customRender: ({ text: value }) => formatDateTime(value) },
])
const versionColumns = computed(() => [
  { title: t('skillVersions.version'), key: 'version', width: 240 },
  { title: t('skillVersions.sourceVersion'), dataIndex: 'source_version', key: 'sourceVersion', width: 130 },
  { title: t('skillVersions.status'), dataIndex: 'status', key: 'status', width: 130 },
  { title: t('skillVersions.risk'), key: 'risk', width: 390 },
  { title: t('skillVersions.submittedAt'), dataIndex: 'submitted_at', key: 'submittedAt', width: 190, customRender: ({ text: value }) => formatDateTime(value) },
  { title: t('skillVersions.scannedAt'), dataIndex: 'last_scanned_at', key: 'scannedAt', width: 190, customRender: ({ text: value }) => formatDateTime(value) },
  { title: t('skillVersions.actions'), key: 'actions', width: 330 },
])
const scanRunColumns = computed(() => [
  { title: t('skillVersions.runStatus'), dataIndex: 'status', key: 'status', width: 120 },
  { title: t('skillVersions.startedAt'), dataIndex: 'started_at', key: 'startedAt', width: 190, customRender: ({ text: value }) => formatDateTime(value) },
  { title: t('skillVersions.finishedAt'), dataIndex: 'finished_at', key: 'finishedAt', width: 190, customRender: ({ text: value }) => formatDateTime(value) },
  { title: t('skillVersions.forced'), dataIndex: 'forced', key: 'forced', width: 90, customRender: ({ text: value }) => value ? t('skillVersions.yes') : t('skillVersions.no') },
  { title: t('skillVersions.reusedFrom'), dataIndex: 'reused_from_scan_run_id', key: 'reusedFrom' },
])

const initializeVersionDiff = () => {
  if (!skillVersions.value.length) {
    diffBaseVersion.value = ''
    diffTargetVersion.value = ''
    versionDiffItems.value = []
    return
  }
  diffTargetVersion.value = skillVersions.value[0].version_id
  diffBaseVersion.value = skillVersions.value[Math.min(1, skillVersions.value.length - 1)].version_id
}

const loadDetailResource = async (request, apply, busy, errorMessage) => {
  const requestId = detailRequestId
  busy.value = true
  try {
    const result = await request()
    if (requestId === detailRequestId) apply(result)
  } catch (error) {
    if (requestId === detailRequestId && errorMessage) message.error(error.response?.data?.detail || errorMessage)
  } finally {
    if (requestId === detailRequestId) busy.value = false
  }
}

const fetchVersions = async () => {
  if (!detail.value?.skill_id) return
  return loadDetailResource(
    () => getSkillVersions(detail.value.skill_id),
    result => { skillVersions.value = result?.items || []; initializeVersionDiff() },
    loadingVersions, t('skillVersions.loadFailed'),
  )
}

const fetchVersionDiff = async () => {
  if (activeTab.value !== 'diff' || !detail.value?.skill_id || !diffBaseVersion.value || !diffTargetVersion.value) return
  const family = detail.value.skill_id
  const base = diffBaseVersion.value
  const target = diffTargetVersion.value
  const key = JSON.stringify([family, base, target])
  if (key === loadedDiffKey || key === pendingDiffKey) return
  const requestId = ++diffRequestId
  versionDiffItems.value = []
  selectedDiffPath.value = ''
  versionDiffError.value = false
  pendingDiffKey = ''
  loadedDiffKey = ''
  if (base === target) {
    loadingVersionDiff.value = false
    loadedDiffKey = key
    return
  }
  pendingDiffKey = key
  loadingVersionDiff.value = true
  try {
    const result = await getSkillVersionDiff(family, { base, target })
    if (requestId !== diffRequestId) return
    const items = result?.items || []
    versionDiffItems.value = items
    selectedDiffPath.value = items[0]?.path || ''
    loadedDiffKey = key
  } catch (error) {
    if (requestId !== diffRequestId) return
    versionDiffError.value = true
  } finally {
    if (requestId === diffRequestId) {
      pendingDiffKey = ''
      loadingVersionDiff.value = false
    }
  }
}

const swapDiffVersions = () => {
  const previousBase = diffBaseVersion.value
  diffBaseVersion.value = diffTargetVersion.value
  diffTargetVersion.value = previousBase
}

const downloadVersion = async (record) => {
  downloadingSkill.value = true
  try {
    const blob = await downloadSkill(detail.value.skill_id, { version: record.version_id })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${detail.value.name}-v${record.version_no}.zip`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    message.error(error.response?.data?.detail || t('skillVersions.downloadFailed'))
  } finally {
    downloadingSkill.value = false
  }
}

const rescanVersion = async (record) => {
  rescanningVersionId.value = record.version_id
  try {
    const result = await rescanSkill(record.version_id)
    message.success(result?.message || t('skillVersions.rescanSubmitted'))
    await fetchVersions()
  } catch (error) {
    message.error(error.response?.data?.detail || t('skillVersions.rescanFailed'))
  } finally {
    rescanningVersionId.value = ''
  }
}

const openScanRuns = async (record) => {
  scanRunsOpen.value = true
  loadingScanRuns.value = true
  scanRuns.value = []
  try {
    const result = await getSkillVersionScanRuns(detail.value.skill_id, record.version_id)
    scanRuns.value = result?.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || t('skillVersions.scanRunsLoadFailed'))
  } finally {
    loadingScanRuns.value = false
  }
}

const sandboxHeaderHelp = (key) => {
  if (key === 'probe') return 'probe'
  if (key === 'exit_code') return 'exit'
  if (key === 'entrypoint' && sandboxProbeResults.value.some(record => !record.probe_entrypoint)) return 'entrypoint'
  if (key === 'command' && sandboxProbeResults.value.some(record => formatSandboxCommand(record) === '-')) return 'command'
  if (key === 'duration_ms' && sandboxProbeResults.value.some(record => record.duration_ms == null)) return 'duration'
  return ''
}

const sandboxProbeColumns = computed(() => [
  { title: 'Probe', key: 'probe', width: 220 },
  { title: text('入口', 'Entrypoint'), key: 'entrypoint', width: 260 },
  { title: text('执行命令', 'Command'), key: 'command' },
  { title: text('退出码', 'Exit Code'), key: 'exit_code', width: 90 },
  { title: text('超时', 'Timed Out'), key: 'timeout', width: 80 },
  { title: text('结果', 'Result'), key: 'result', width: 100 },
  { title: text('耗时', 'Duration'), dataIndex: 'duration_ms', key: 'duration_ms', width: 100, customRender: ({ text: value }) => `${value ?? '-'} ms` },
])

const fetchDetail = async () => {
  const requestId = ++detailRequestId
  ++scanReportRequestId
  scanReportError.value = false
  loadedTabs.clear()
  ++diffRequestId
  loadedDiffKey = ''
  pendingDiffKey = ''
  detail.value = null
  scanReport.value = null
  skillContent.value = null
  skillFiles.value = []
  governanceCard.value = null
  auditRows.value = []
  skillVersions.value = []
  versionDiffItems.value = []
  selectedDiffPath.value = ''
  diffBaseVersion.value = ''
  diffTargetVersion.value = ''
  versionDiffError.value = false
  loadingVersionDiff.value = false
  for (const busy of [loadingScanReport, loadingContent, loadingFiles, loadingGovernanceCard, loadingAudit, loadingVersions]) busy.value = false
  loading.value = true
  try {
    const data = await getSkillDetail(skillId.value)
    if (requestId !== detailRequestId) return
    detail.value = data
    signatureResult.value = null
    loading.value = false
    await Promise.allSettled([
      fetchScanReport(),
      loadDetailResource(() => getSkillVersions(data.skill_id),
        result => { skillVersions.value = result?.items || []; initializeVersionDiff() }, loadingVersions),
    ])
  } catch (error) {
    if (requestId === detailRequestId) message.error(error.response?.data?.detail || phrase('legacy.qrrlus'))
  } finally {
    if (requestId === detailRequestId) loading.value = false
  }
}

const openClientInstall = async () => {
  if (clientInstallLoading.value) return
  clientInstallClient.value = undefined
  clientInstallTarget.value = undefined
  managedClients.value = []
  clientInstallVersion.value = trustedSkillVersions.value.find(item => item.latest_trusted)?.version_id
    || trustedSkillVersions.value[0]?.version_id
    || ''
  clientInstallOpen.value = true
  clientInstallLoading.value = true
  try {
    managedClients.value = await listClients()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.167k0p'))
  } finally {
    clientInstallLoading.value = false
  }
}

const submitClientInstall = async () => {
  if (clientInstallLoading.value) return
  const target = clientTargets.value.find(item => item.key === clientInstallTarget.value)
  if (!target) {
    message.warning(phrase('legacy.9itypw'))
    return
  }
  clientInstallLoading.value = true
  try {
    await createClientTask(target.clientId, {
      task_type: 'install_skill',
      payload: {
        agent_type: target.agentType,
        managed_agent_id: target.managedAgentId,
        skill_id: detail.value.skill_id,
        version_id: clientInstallVersion.value,
      },
    })
    clientInstallOpen.value = false
    message.success(phrase('legacy.zqfh0e'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1kcqrgw'))
  } finally {
    clientInstallLoading.value = false
  }
}

// 报告及准入提示共用加载结果，只接收当前记录的最新请求。
const fetchScanReport = async () => {
  if (!detail.value) return
  const requestId = ++scanReportRequestId
  const detailId = detailRequestId
  loadingScanReport.value = true
  scanReportError.value = false
  try {
    const result = await getSkillScanReport(currentVersionId.value)
    if (requestId === scanReportRequestId && detailId === detailRequestId) {
      scanReport.value = result?.scan_report || null
    }
  } catch {
    if (requestId === scanReportRequestId && detailId === detailRequestId) scanReportError.value = true
  } finally {
    if (requestId === scanReportRequestId && detailId === detailRequestId) loadingScanReport.value = false
  }
}

const fetchSkillContent = async () => {
  if (!detail.value || loadingContent.value) return
  return loadDetailResource(() => getSkillContent(currentVersionId.value),
    result => { skillContent.value = result || null; loadedTabs.add('content') }, loadingContent, phrase('legacy.1iff97n'))
}

const fetchSkillFiles = async () => {
  if (!detail.value || loadingFiles.value) return
  return loadDetailResource(() => getSkillFiles(currentVersionId.value),
    result => { skillFiles.value = result?.files || []; loadedTabs.add('files') }, loadingFiles, phrase('legacy.1rirokg'))
}

const fetchGovernanceCard = async () => {
  if (!detail.value || loadingGovernanceCard.value) return
  return loadDetailResource(() => getSkillGovernanceCard(currentVersionId.value),
    result => { governanceCard.value = result || null; loadedTabs.add('governance-card') }, loadingGovernanceCard, phrase('legacy.82xq4f'))
}

const loadedTabs = new Set()
watch(() => [activeTab.value, detail.value?.version_id, detail.value?.skill_id], () => {
  if (!detail.value || loadedTabs.has(activeTab.value)) return
  if (activeTab.value === 'content') void fetchSkillContent()
  else if (activeTab.value === 'files') void fetchSkillFiles()
  else if (activeTab.value === 'governance-card') void fetchGovernanceCard()
  else if (activeTab.value === 'audit' && !loadingAudit.value) {
    void loadDetailResource(() => getAudit({ skill_id: currentVersionId.value, since_hours: 720, limit: 50 }),
      result => { auditRows.value = Array.isArray(result) ? result : []; loadedTabs.add('audit') }, loadingAudit, phrase('legacy.qrrlus'))
  }
})

const handleRefreshGovernanceCard = async () => {
  if (!detail.value) return
  loadingGovernanceCard.value = true
  try {
    governanceCard.value = await refreshSkillGovernanceCard(currentVersionId.value)
    await fetchScanReport()
    message.success(phrase('legacy.1su23nl'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.7lzo4d'))
  } finally {
    loadingGovernanceCard.value = false
  }
}

const handleDownloadSkill = async () => {
  if (!detail.value?.skill_id) return
  downloadingSkill.value = true
  try {
    const blob = await downloadSkill(currentVersionId.value)
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    const safeName = String(detail.value.name || detail.value.skill_id || 'skill').replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '') || 'skill'
    link.href = url
    link.download = `${safeName}.zip`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    message.success(phrase('legacy.kguwcl'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1rt1fc6'))
  } finally {
    downloadingSkill.value = false
  }
}

const handleExportScanReport = async () => {
  if (!detail.value?.vetting || detail.value?.status === 'PENDING') return
  exportingScanReport.value = true
  try {
    const blob = await exportSkillScanReportPdf(
      currentVersionId.value,
      isEnglish.value ? 'en-US' : 'zh-CN',
    )
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    const safeName = String(detail.value.name || detail.value.skill_id || 'skill')
      .replace(/[^A-Za-z0-9_.-]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'skill'
    link.href = url
    link.download = `${safeName}-v${detail.value.version_no || 1}-${t('scanReportExport.fileSuffix')}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    message.success(t('scanReportExport.success'))
  } catch (error) {
    message.error(error.response?.data?.detail || t('scanReportExport.failed'))
  } finally {
    exportingScanReport.value = false
  }
}

const openFileViewer = async (path) => {
  if (!detail.value || !path) return
  viewingFilePath.value = path
  fileViewerOpen.value = true
  loadingFileViewer.value = true
  try {
    viewedFile.value = await getSkillFileContent(currentVersionId.value, path)
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.u64zz9'))
  } finally {
    loadingFileViewer.value = false
  }
}

const refreshViewedFile = async () => {
  if (!viewingFilePath.value) return
  await openFileViewer(viewingFilePath.value)
}

const handleVerifySignature = async () => {
  if (!detail.value) return
  if (!detail.value.signature) {
    message.warning(signatureVerifyDisabledReason.value)
    return
  }
  verifyingSignature.value = true
  try {
    signatureResult.value = await verifySkillSignature(currentVersionId.value)
    if (signatureResult.value.valid) {
      message.success(phrase('legacy.niy9wk'))
    } else {
      message.error(text(
        `完整性校验失败：${signatureResultReason.value}`,
        `Integrity verification failed: ${signatureResultReason.value}`,
      ))
    }
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.169xltl'))
  } finally {
    verifyingSignature.value = false
  }
}

const currentUser = () => localStorage.getItem('username') || 'admin'

const openApproveModal = () => {
  approveNote.value = ''
  approveModalOpen.value = true
}

const openRejectModal = () => {
  rejectReason.value = ''
  rejectModalOpen.value = true
}

const submitApprove = async () => {
  if (actionLoading.value || !approvalVersionId.value || approveTooLong.value) return
  actionLoading.value = true
  actionType.value = 'approve'
  try {
    await approveSkill(approvalVersionId.value, { approver: currentUser(), note: approveNote.value.trim() || null })
    message.success(phrase('legacy.10hmnl2'))
    approveModalOpen.value = false
    fetchDetail()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.xx2z1c'))
  } finally {
    actionLoading.value = false
    actionType.value = ''
  }
}

const submitReject = async () => {
  if (actionLoading.value || !detail.value || rejectTooLong.value) return
  if (!rejectReason.value.trim()) {
    message.warning(phrase('legacy.erwuhg'))
    return
  }
  actionLoading.value = true
  actionType.value = 'reject'
  try {
    await rejectSkill(currentVersionId.value, { reviewer: currentUser(), reason: rejectReason.value.trim() })
    message.success(phrase('legacy.16h1qdk'))
    rejectModalOpen.value = false
    fetchDetail()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.36obuy'))
  } finally {
    actionLoading.value = false
    actionType.value = ''
  }
}

const stepIndex = computed(() => {
  if (!detail.value) return 0
  const status = detail.value.status
  if (['APPROVED', 'DEPLOYED'].includes(status) && detail.value.approved_at) return 2
  if (status === 'VETTED') return 1
  return 0
})

const llmAnalysis = computed(() => {
  const analysis = scanReport.value?.llm_analysis
  if (!analysis) return null
  return {
    ...analysis,
    risk_level: analysis.risk_level || 'benign',
  }
})
// 仅按本次报告的关闭原因展示说明，不使用当前系统开关推断历史结果。
const llmDisabled = computed(() => analysisState(scanReport.value, 'llm') === 'disabled'
  && scanReport.value?.analyzer_timings?.llm?.reason === 'llm_analysis_disabled')
const llmFailure = computed(() => {
  const timing = scanReport.value?.analyzer_timings?.llm
  if (timing?.status === 'failed' && timing.reason === 'llm_analysis_timeout') {
    return t('skillDetail.llmAnalysisTimedOut', { seconds: timing.timeout_seconds })
  }
  const raw = formatLlmFailureReason(llmFailureReason(scanReport.value, policyNotes.value), t)
  if (timing?.status === 'failed' && timing.reason === 'llm_provider_timeout') {
    return [t('skillDetail.llmProviderTimedOut'), raw].filter(Boolean).join('\n')
  }
  return raw
})
const llmExplanationHtml = computed(() => {
  const text = llmAnalysis.value?.report || ''
  if (!text) return phrase('legacy.xsay8c')
  return marked.parse(text)
})
const riskClassification = computed(() => scanReport.value?.risk_classification || null)
const findingClassificationGroups = computed(() => ['blocking', 'risk', 'noise'].map(key => ({
  key,
  label: t(`policySettings.groups.${key}`),
})))
const findingTypeLabels = {
  data_exfiltration: phrase('legacy.13wlkrx'),
  supply_chain: phrase('legacy.33dhvx'),
  prompt_injection: phrase('legacy.v4iti5'),
  tool_misuse: phrase('legacy.1bpfkaw'),
  network: phrase('legacy.1xh2061'),
  credential_access: phrase('legacy.1jxzdyj'),
  dynamic_execution: phrase('legacy.qath61'),
  excessive_permissions: phrase('legacy.1rc1tey'),
  documented_external_api: phrase('legacy.1iv6edf'),
  dependency: phrase('legacy.19x9ebb'),
  runtime: phrase('legacy.q3x1o3'),
  other: phrase('legacy.dcd4ul'),
}
const findingTypeLabelsEn = {
  data_exfiltration: 'Data Exfiltration',
  supply_chain: 'Supply Chain Risk',
  prompt_injection: 'Prompt Injection',
  tool_misuse: 'Tool Misuse',
  network: 'Network Access',
  credential_access: 'Credential Access',
  dynamic_execution: 'Dynamic Execution',
  excessive_permissions: 'Excessive Permissions',
  documented_external_api: 'Documented API Example',
  dependency: 'Dependency / Environment Issue',
  runtime: 'Runtime Failure',
  other: 'Other',
}
const findingTypeLabel = (key) => (isEnglish.value ? findingTypeLabelsEn[key] : findingTypeLabels[key]) || key
const findingSignature = (finding) => {
  const item = normalizeRuleFinding(finding)
  return [item.rule, item.category, item.title, item.file]
    .map(value => String(value || '').toLowerCase()).join('|')
}
const classifiedFindingMap = computed(() => {
  const map = new Map()
  const items = riskClassification.value?.items
  if (!Array.isArray(items)) return map
  for (const item of items) {
    if (!item?.classification) continue
    map.set(findingSignature(item), item)
  }
  return map
})
const classifiedFindingOf = (item) => classifiedFindingMap.value.get(findingSignature(item)) || (item?.classification ? item : null)
const fallbackFindingClassification = (item) => {
  const severity = severityRank(item?.severity)
  const category = String(item?.category || '').toLowerCase()
  const rule = String(item?.rule || item?.rule_id || '').toUpperCase()
  if (category.includes('data exfiltration') || category.includes('data_exfiltration')) return 'blocking'
  if (rule.includes('DEPENDENCY') || ['dependency', 'runtime'].includes(category)) return 'noise'
  return severity >= severityRank('MEDIUM') ? 'risk' : 'noise'
}
const findingClassificationOf = (item) =>
  classifiedFindingOf(item)?.classification || fallbackFindingClassification(item)
const findingTypeOf = (item) => {
  const classified = classifiedFindingOf(item)
  if (classified?.classification_key) return classified.classification_key
  if (item?.classification_key) return item.classification_key
  return legacyFindingType(item)
}
const aggregateFindingKey = (item) => [
  findingClassificationOf(item),
  findingTypeOf(item),
  item?.rule || item?.rule_id || '',
  item?.category || '',
  item?.title || '',
  item?.message || item?.finding || '',
  item?.file || item?.file_path || '',
].map(value => String(value || '').trim().toLowerCase()).join('|')
const aggregateFindings = (items) => {
  const map = new Map()
  for (const item of items) {
    const key = aggregateFindingKey(item)
    const line = item?.line || item?.start_line || item?.line_number
    const current = map.get(key)
    if (current) {
      current.aggregate_count += 1
      if (line) current.aggregate_lines.push(line)
      continue
    }
    map.set(key, {
      ...item,
      aggregate_count: 1,
      aggregate_lines: line ? [line] : [],
    })
  }
  return [...map.values()]
}
const legacyFindingType = (item) => {
  const rule = String(item?.rule || item?.rule_id || '').toLowerCase()
  const category = String(item?.category || '').toLowerCase()
  if (legacyDocumentedExternalApi(item)) return 'documented_external_api'
  if (rule.includes('dependency') || category === 'dependency') return 'dependency'
  if (category === 'runtime') return 'runtime'
  if (rule === 'e1' || rule === 'e2' || rule === 'e3' || category.includes('data exfiltration')) return 'data_exfiltration'
  if (category.includes('credential') || rule === 'credential_file_access') return 'credential_access'
  if (category.includes('prompt')) return 'prompt_injection'
  if (category.includes('network')) return 'network'
  return 'other'
}
const legacyDocumentedExternalApi = (item) => {
  const rule = String(item?.rule || item?.rule_id || '').toLowerCase()
  const file = String(item?.file || item?.file_path || '').toLowerCase().split('/').pop()
  const text = [
    item?.message,
    item?.finding,
    item?.code_snippet,
    item?.explanation,
  ].map(value => String(value || '').toLowerCase()).join(' ')
  return rule === 'e1'
    && ['skill.md', 'skill-card.md'].includes(file)
    && (text.includes('http://') || text.includes('https://'))
    && ['curl ', 'api ', 'endpoint', phrase('legacy.llpdyd'), phrase('legacy.19vzoc9')].some(token => text.includes(token))
}
const groupFindingSections = (items) => {
  const sections = []
  for (const item of items) {
    const key = findingTypeOf(item)
    let section = sections.find(entry => entry.key === key)
    if (!section) {
      section = { key, label: findingTypeLabel(key), items: [] }
      sections.push(section)
    }
    section.items.push(item)
  }
  return sections
}
const groupFindingsByClassification = (items) =>
  findingClassificationGroups.value.map(group => ({
    ...group,
    items: aggregateFindings(items.filter(item => findingClassificationOf(item) === group.key)),
  })).filter(group => group.items.length).map(group => ({
    ...group,
    sections: groupFindingSections(group.items),
  }))
const behavioralAnalysis = computed(() => scanReport.value?.behavioral_analysis || null)
const behavioralFindings = computed(() => behavioralAnalysis.value?.findings || [])
const behavioralScannedFiles = computed(() => behavioralAnalysis.value?.scanned_files || [])
const localStaticAnalysis = computed(() => scanReport.value?.local_static_analysis || null)
// 按本次记录展示规则分析器，兼容仅保存本地分析结果的旧报告。
const ruleAnalyzerNames = computed(() => {
  const recorded = scanReport.value?.analyzers_used || detail.value?.vetting?.analyzers_used || []
  const names = recorded.filter(name => ['static_analyzer', 'bytecode', 'pipeline', 'behavioral:local', 'agent-manager-local', 'basic'].includes(name))
  if (!recorded.length) {
    if (behavioralAnalysis.value) names.push('behavioral:local')
    if (localStaticAnalysis.value) names.push('agent-manager-local')
  }
  return [...new Set(names)]
})
const normalizeRuleFinding = (item) => ({
  ...item,
  title: item.title || item.rule_id || item.rule || phrase('legacy.10qlo3g'),
  message: item.message || item.description || item.remediation || '',
  file: item.file || item.file_path || '',
  line: item.line || item.line_number || item.start_line || null,
  rule: item.rule || item.rule_id || '',
})
const isRuleFinding = (item) => {
  const source = String(item.source || item.analyzer || '').toLowerCase()
  return !['sandbox', 'llm', 'skillspector'].some((name) => source.includes(name))
}
const topLevelRuleFindings = computed(() => {
  const findings = Array.isArray(scanReport.value?.findings) ? scanReport.value.findings : []
  return findings.filter(isRuleFinding).map(normalizeRuleFinding)
})
const ruleAnalysisFindings = computed(() => {
  // 合并基础与本地规则，去掉顶层报告包含的同一发现项副本。
  const findings = [
    ...topLevelRuleFindings.value,
    ...behavioralFindings.value.map(normalizeRuleFinding),
    ...(localStaticAnalysis.value?.findings || []).map(normalizeRuleFinding),
  ]
  const seen = new Set()
  return findings.filter(item => {
    const key = JSON.stringify([
      item.source || item.analyzer || '', item.rule, item.file, item.line,
      item.severity, item.title, item.message, item.category, item.code_snippet, item.snippet, item.evidence,
    ])
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const groupedRuleAnalysisFindings = computed(() => groupFindingsByClassification(ruleAnalysisFindings.value))
const nonEmptyRuleClassificationKeys = computed(() => groupedRuleAnalysisFindings.value.map(group => group.key))
const maxSeverity = (...values) => {
  let current = 'SAFE'
  for (const value of values) {
    if (severityRank(value) > severityRank(current)) current = value
  }
  return current
}
const ruleAnalysisMaxSeverity = computed(() =>
  maxSeverity(
    scanReport.value?.max_severity,
    behavioralAnalysis.value?.max_severity,
    localStaticAnalysis.value?.max_severity,
    ...ruleAnalysisFindings.value.map(item => item.severity),
  ),
)
const policyNotes = computed(() => detail.value?.vetting?.policy_notes || [])
const parsePolicyBlock = (note) => {
  const noteText = String(note || '')
  const match = noteText.match(/^\[BLOCK\]\s+([^:]+):\s*(.+)$/)
  if (!match) return null
  const [, code, message] = match
  const countMatch = message.match(/^Skill declares (\d+) tools; policy allows at most (\d+)$/)
  if (code === 'max_allowed_tools' && countMatch) {
    return { code, text: t('decisionFlow.toolCountExceeded', { count: countMatch[1], limit: countMatch[2] }) }
  }
  const permissionMatch = message.match(/^Tool\/permission ['"](.+)['"] is explicitly blocked by policy$/)
  if (code === 'blocked_permission' && permissionMatch) {
    const blocked = scanReport.value?.risk_reconciliation?.policy_snapshot?.blocked_permissions
    return {
      code,
      text: t('skillDetail.blockedPermission', {
        permission: permissionMatch[1],
        blocked: Array.isArray(blocked) ? blocked.join(', ') : t('decisionFlow.unrecorded'),
      }),
    }
  }
  const toolMatch = message.match(/Tool '([^']+)' is not in the company allowlist/i)
  if (code === 'tool_not_in_allowlist' && toolMatch) {
    return {
      code,
      text: t('skillDetail.recordedToolBlock', { tool: toolMatch[1] }),
    }
  }
  return {
    code,
    text: `${code}：${message}`,
  }
}
const policyBlockItems = computed(() =>
  policyNotes.value
    .map(parsePolicyBlock)
    .filter(Boolean),
)
// 仅非阻断的工具声明告警显示黄色；真实禁止权限仍按本次记录显示失败。
const toolDeclarationWarning = computed(() =>
  !policyBlockItems.value.some(item => ['blocked_permission', 'max_allowed_tools'].includes(item.code))
  && ((scanReport.value?.policy_warnings || []).some(item => ['tool_not_in_allowlist', 'max_allowed_tools'].includes(item.rule))
    || policyNotes.value.some(note => /^\[WARN\] (tool_not_in_allowlist|max_allowed_tools):/.test(String(note)))),
)
const admissionBlocked = computed(() =>
  detail.value?.status === 'REJECTED' && policyBlockItems.value.length > 0,
)
const vettingFailed = computed(() =>
  detail.value?.status === 'REJECTED' && Boolean(scanReport.value?.vetting_failed || detail.value?.rejection_reason?.startsWith('后台分析失败')),
)
const manualApprovalRequired = computed(() => admissionBlocked.value || vettingFailed.value)
const canApproveSkill = computed(() => {
  if (detail.value?.status === 'VETTED') return true
  if (vettingFailed.value) return true
  if (!admissionBlocked.value) return false
  return ['benign', 'suspicious'].includes(detail.value?.risk_level)
})
const admissionBlockedSummary = computed(() => {
  if (!admissionBlocked.value) return ''
  return policyBlockItems.value.map((item) => item.text).join('；')
})
const manualApprovalSummary = computed(() => {
  if (vettingFailed.value) {
    const reason = scanReport.value?.vetting_error || detail.value?.rejection_reason || phrase('legacy.1m4f5ms')
    return text(
      `后台分析失败：${reason}。可人工确认 Skill 内容后例外批准。`,
      `Background analysis failed: ${reason}. The Skill may be approved as an exception after manual review.`,
    )
  }
  return admissionBlockedSummary.value
})
const skillspectorAnalysis = computed(() => scanReport.value?.skillspector_analysis || null)
const skillspectorSuppressedFindings = computed(() => skillspectorAnalysis.value?.suppressed_findings || [])
const skillspectorFindings = computed(() => {
  const findings = skillspectorAnalysis.value?.findings
  if (Array.isArray(findings)) return findings
  return []
})
const groupedSkillspectorFindings = computed(() => groupFindingsByClassification(skillspectorFindings.value))
const nonEmptySkillspectorClassificationKeys = computed(() =>
  groupedSkillspectorFindings.value.map(group => `skillspector-${group.key}`),
)
const skillspectorEffectiveSeverity = computed(() =>
  skillspectorAnalysis.value?.effective_risk_severity
  || skillspectorAnalysis.value?.risk_severity
  || skillspectorAnalysis.value?.max_severity
  || '',
)
const skillspectorRawSeverity = computed(() => skillspectorAnalysis.value?.raw_risk_severity || '')
const hasHighRiskSkillspectorFinding = computed(() =>
  skillspectorFindings.value.some((item) => severityRank(item.severity) >= severityRank('HIGH')),
)
const governanceCardHtml = computed(() => {
  const content = governanceCard.value?.content || ''
  if (!content) return phrase('legacy.ppdayt')
  return marked.parse(content)
})
const numberedLines = (text) => String(text || '').split('\n').map((line, index) => ({
  no: index + 1,
  text: line,
}))
const governanceCardLines = computed(() => numberedLines(governanceCard.value?.content || phrase('legacy.nnioji')))
const sandboxAnalysis = computed(() => scanReport.value?.sandbox_analysis || null)
const sandboxDiagnosticCategories = new Set(['dependency', 'probe_input', 'runtime', 'execution', 'credentials'])
const sandboxAllSignals = computed(() => sandboxAnalysis.value?.signals || sandboxAnalysis.value?.suspicious_events || [])
const isSandboxDiagnosticSignal = (item) => sandboxDiagnosticCategories.has(String(item?.category || '').toLowerCase())
const sandboxSignals = computed(() => sandboxAllSignals.value.filter((item) => !isSandboxDiagnosticSignal(item)))
const sandboxDiagnosticSignals = computed(() => sandboxAllSignals.value.filter((item) => isSandboxDiagnosticSignal(item)))
const sandboxDisplayRiskLevel = computed(() => {
  if (!sandboxSignals.value.length && sandboxDiagnosticSignals.value.length) return 'LOW'
  return sandboxAnalysis.value?.risk_level || 'LOW'
})
const sandboxDisplayMaxSeverity = computed(() => {
  if (!sandboxSignals.value.length && sandboxDiagnosticSignals.value.length) return 'SAFE'
  return sandboxAnalysis.value?.max_severity || 'SAFE'
})
const sandboxDisplaySummary = computed(() => {
  if (!sandboxAnalysis.value) return ''
  if (!sandboxSignals.value.length && sandboxDiagnosticSignals.value.length) {
    return text(
      'Sandbox 未提取到明确运行时风险信号；仅发现执行环境或 Probe 诊断信息，可在调试信息中查看。',
      'Sandbox found no explicit runtime risk signals. Only environment or Probe diagnostics were recorded; review the debugging details.',
    )
  }
  return sandboxAnalysis.value.summary
    ? platformResultText(sandboxAnalysis.value.summary)
    : text('Sandbox 未发现明确风险信号。', 'Sandbox found no explicit risk signals.')
})
const missingProbeInputPattern = /(cannot open\s+[^:\n]+:\s+No such file|No such file or directory)/i
const isSandboxProbeInputMissing = (record) => {
  const text = [record?.stdout, record?.stderr, record?.reason, record?.summary]
    .map((item) => String(item || ''))
    .join('\n')
  return missingProbeInputPattern.test(text)
}
const sandboxProbeResultTag = (record) => {
  if (isSandboxProbeInputMissing(record)) return { text: text('输入缺失', 'Input Missing'), color: 'orange' }
  if (record?.timed_out) return { text: text('超时', 'Timed Out'), color: 'red' }
  if (record?.exit_code === 0) return { text: text('已执行', 'Executed'), color: 'green' }
  if (record?.exit_code != null) return { text: text('诊断', 'Diagnostic'), color: 'default' }
  return { text: text('未执行', 'Not Executed'), color: 'default' }
}
const sandboxProbeResults = computed(() => {
  const results = sandboxAnalysis.value?.probe_results
  if (Array.isArray(results) && results.length) {
    return results.map((item, index) => ({
      key: `${item.probe_name || 'probe'}-${index}`,
      ...item,
      probe_name: item.probe_name || `probe-${index + 1}`,
      probe_entrypoint: item.probe_entrypoint || item.entrypoint || sandboxAnalysis.value?.entrypoint || '',
      probe_args: Array.isArray(item.probe_args) ? item.probe_args : [],
    }))
  }
  if (!sandboxAnalysis.value) return []
  return [{
    key: 'representative',
    probe_name: 'representative',
    probe_description: sandboxAnalysis.value.reason || text('代表性 Sandbox 执行结果', 'Representative Sandbox Result'),
    probe_entrypoint: sandboxAnalysis.value.entrypoint || '',
    probe_args: Array.isArray(sandboxAnalysis.value.probe_args) ? sandboxAnalysis.value.probe_args : [],
    probe_generated_by: 'summary',
    runtime: sandboxAnalysis.value.runtime,
    stdout: sandboxAnalysis.value.stdout,
    stderr: sandboxAnalysis.value.stderr,
    exit_code: sandboxAnalysis.value.exit_code,
    timed_out: sandboxAnalysis.value.timed_out,
    duration_ms: sandboxAnalysis.value.duration_ms,
    network_attempts: sandboxAnalysis.value.network_attempts,
    reason: sandboxAnalysis.value.reason,
    summary: sandboxAnalysis.value.summary,
    recommendation: sandboxAnalysis.value.recommendation,
    max_severity: sandboxAnalysis.value.max_severity,
    risk_level: sandboxAnalysis.value.risk_level,
  }]
})
const sandboxRiskAlertType = computed(() => {
  const risk = (sandboxDisplayRiskLevel.value || '').toUpperCase()
  if (risk === 'EXTREME' || risk === 'HIGH') return 'error'
  if (risk === 'MEDIUM') return 'warning'
  return 'success'
})
const deepScanText = (value) =>
  String(value || '')
    .replace(/SkillSpector/gi, isEnglish.value ? 'Deep Analysis' : phrase('legacy.l2wtjk'))
    .replace(/skillspector/gi, isEnglish.value ? 'Deep Analysis' : phrase('legacy.l2wtjk'))
    .replace(/\bCLI\b/g, isEnglish.value ? 'service' : phrase('legacy.2yn6uz'))
const severityRank = (value) =>
  ({
    SAFE: 0,
    INFO: 1,
    LOW: 2,
    MEDIUM: 3,
    HIGH: 4,
    CRITICAL: 5,
    EXTREME: 5,
  }[String(value || 'LOW').toUpperCase()] ?? 2)
const jumpToRationale = async (target) => {
  activeTab.value = 'vetting'
  analysisTab.value = target
  await nextTick()
  const id = {
    rule: 'rule-analysis-section',
    skillspector: 'skillspector-section',
    sandbox: 'sandbox-section',
    llm: 'llm-section',
  }[target]
  if (id) document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const sandboxRuntime = computed(() => sandboxAnalysis.value?.runtime || detail.value?.vetting?.sandbox_runtime)
// 已有报告的分析器名称按该次报告记录的运行方式展示。
const analyzerNames = computed(() => (detail.value?.vetting?.analyzers_used || []).map(name =>
  name.startsWith('sandbox:') && ['remote', 'docker'].includes(sandboxRuntime.value)
    ? `sandbox:${sandboxRuntime.value}` : name,
))
const sandboxTargetLabel = computed(() => t(sandboxRuntime.value === 'remote'
  ? 'skillDetail.sandboxService' : sandboxRuntime.value === 'docker' ? 'skillDetail.sandboxImage' : 'skillDetail.sandboxTarget'))
const sandboxTarget = computed(() => {
  // 无可执行脚本时不会调用远程服务，按报告原因显示实际调用状态。
  if (sandboxRuntime.value === 'remote' && sandboxAnalysis.value?.reason_code === 'no_executable_script') {
    return t('skillDetail.sandboxNotCalled')
  }
  return sandboxAnalysis.value?.image || t('decisionFlow.unrecorded')
})
const sandboxExecutionState = computed(() => {
  const recorded = analysisState(scanReport.value, 'sandbox')
  if (recorded !== 'unrecorded') return recorded
  if (sandboxAnalysis.value?.available === false) return 'unavailable'
  if (sandboxAnalysis.value?.executed === true) return 'completed'
  if (sandboxAnalysis.value?.executed === false) return 'skipped'
  return 'unrecorded'
})
const approvalActor = computed(() => {
  const actor = detail.value?.approved_by
  if (actor === 'auto-policy') return t('skillDetail.autoApproval')
  if (actor === 'auto-policy-cache') return t('skillDetail.cachedAutoApproval')
  return actor || t(detail.value?.status === 'VETTED' ? 'skillDetail.pendingReview' : 'decisionFlow.unrecorded')
})

const signatureReasonLabels = {
  'No signature stored for this skill': phrase('legacy.1eyejfi'),
  'No skill path available for verification': phrase('legacy.1syl1es'),
  'signature valid': phrase('legacy.7htsrw'),
  'signature mismatch': phrase('legacy.11kbaiv'),
}
const signatureVerifyDisabledReason = computed(() => (
  detail.value?.signature
    ? ''
    : phrase('legacy.jyd49r')
))
const signatureResultReason = computed(() => {
  const reason = signatureResult.value?.reason
  return signatureReasonLabels[reason] || reason || '-'
})

const formatSandboxCommand = (record) => {
  const entrypoint = record?.probe_entrypoint || record?.entrypoint || ''
  const args = Array.isArray(record?.probe_args) ? record.probe_args : []
  if (!entrypoint) return args.length ? args.join(' ') : '-'
  const prefix = entrypoint.endsWith('.py')
    ? 'python'
    : entrypoint.endsWith('.js')
      ? 'node'
      : entrypoint.endsWith('.sh')
        ? 'sh'
        : ''
  return [prefix, entrypoint, ...args].filter(Boolean).join(' ')
}

const sandboxEvidenceLines = (evidence) => {
  const text = String(evidence || '').trim()
  if (!text) return []
  return text
    .replace(/；/g, '\n')
    .split('\n')
    .map((line) => platformResultText(line.trim()))
    .filter(Boolean)
}

const sandboxProbeResultText = (record) => {
  if (isSandboxProbeInputMissing(record)) {
    return text(
      'Probe 引用了不存在的示例输入文件，当前结果主要反映测试参数不完整，不应单独作为安全风险判断。',
      'The Probe referenced a missing sample input file. This result mainly indicates incomplete test parameters and should not be treated as a security risk on its own.',
    )
  }
  const parts = [
    record?.summary,
    record?.reason,
    record?.recommendation,
  ].filter((item) => String(item || '').trim())
  if (parts.length) return parts.join(text('；', '; '))
  if (record?.timed_out) return text('执行超时，建议检查 probe 参数或执行环境限制。', 'Execution timed out. Check Probe parameters and runtime limits.')
  if (record?.exit_code != null && record.exit_code !== 0) return text('脚本以非零退出码结束，建议结合规则扫描和风险信号判断。', 'The script exited with a non-zero code. Review it together with rule findings and runtime signals.')
  if (record?.exit_code === 0) return text('脚本执行完成，未从输出中提取到明确风险信号。', 'Execution completed and no explicit risk signals were extracted from the output.')
  return text('未记录额外执行说明。', 'No additional execution details were recorded.')
}

const parsedSkillContent = computed(() => {
  const content = skillContent.value?.content || ''
  if (!content.startsWith('---')) {
    return { frontmatter: '', body: content }
  }
  const lines = content.split('\n')
  const closingIndex = lines.findIndex((line, index) => index > 0 && line.trim() === '---')
  if (closingIndex === -1) {
    return { frontmatter: '', body: content }
  }
  return {
    frontmatter: lines.slice(1, closingIndex).join('\n').trim(),
    body: lines.slice(closingIndex + 1).join('\n').trim(),
  }
})

const skillFrontmatter = computed(() => parsedSkillContent.value.frontmatter)
const viewerTitle = computed(() => (viewingFilePath.value
  ? text(`文件内容：${viewingFilePath.value}`, `File Contents: ${viewingFilePath.value}`)
  : phrase('legacy.4264pu')))
const skillContentHtml = computed(() => {
  const body = parsedSkillContent.value.body
  if (!body) return phrase('legacy.1k82gzg')
  return marked.parse(body)
})
const skillContentLines = computed(() => numberedLines(skillContent.value?.content || phrase('legacy.1gvzf2u')))
const viewedFileLines = computed(() => numberedLines(viewedFile.value?.content || phrase('legacy.osyxq4')))

const cancelledReason = phrase('legacy.1fphrle')
const isCancelled = (entry) => entry?.status === 'REJECTED' && entry?.rejection_reason === cancelledReason

const severityLabels = {
  SAFE: phrase('legacy.1apxo2s'),
  INFO: phrase('legacy.1hx7jj'),
  LOW: phrase('legacy.1kffmxd'),
  MEDIUM: phrase('legacy.b7cu2g'),
  HIGH: phrase('legacy.pk6gtj'),
  CRITICAL: phrase('legacy.s9cfpz'),
  EXTREME: phrase('legacy.163y7r0'),
}

const recommendationLabels = {
  SAFE: phrase('legacy.1k3oaj4'),
  CAUTION: phrase('legacy.lsnmcp'),
  REVIEW: phrase('legacy.1mmbxob'),
  DO_NOT_INSTALL: phrase('legacy.qijv1l'),
}

const termTranslations = {
  'LOW_ANALYZABILITY': phrase('legacy.xucvo9'),
  'Moderate analyzability score': phrase('legacy.18k1139'),
  'External Transmission': phrase('legacy.13wlkrx'),
  'Data Exfiltration': phrase('legacy.13wlkrx'),
  'Prompt Injection': phrase('legacy.v4iti5'),
  'Instruction Override': phrase('legacy.16xag79'),
  'System Prompt Leakage': phrase('legacy.1y1bb3m'),
  'System Prompt Disclosure': phrase('legacy.1hfhk23'),
  'Tool Poisoning': phrase('legacy.5o0i46'),
  'Hidden Instructions': phrase('legacy.kl77lf'),
  'Supply Chain': phrase('legacy.33dhvx'),
  'External Script Fetching': phrase('legacy.txwthx'),
  'Obfuscated Code': phrase('legacy.l4itaw'),
  'Wildcard Permission': phrase('legacy.1dknhaj'),
  'Network Access': phrase('legacy.1xh2061'),
  'File System Access': phrase('legacy.ys72kz'),
  'Sensitive File Access': phrase('legacy.eq1zzb'),
  'Command Execution': phrase('legacy.1u3dwq7'),
  'Code Execution': phrase('legacy.1082dwy'),
  'Dynamic Code Execution': phrase('legacy.1ihewot'),
  'Credential Access': phrase('legacy.1jxzdyj'),
  'Privilege Escalation': phrase('legacy.zl59z3'),
  Persistence: phrase('legacy.4xb5jb'),
  'Encoded Payload': phrase('legacy.11ji0hk'),
  'Undeclared network usage': phrase('legacy.cgxrx3'),
  'Potential description-behavior mismatch': phrase('legacy.1opd4vl'),
  'Skill does not specify a license': phrase('legacy.iod8ba'),
  'Outbound network request primitives that can transmit data externally': phrase('legacy.1lylg3v'),
  'MCP Least Privilege': phrase('legacy.1vp57ev'),
  'Data Flow': phrase('legacy.gv0kra'),
  'Env Variable Harvesting': phrase('legacy.vc0w9b'),
  'Access token': phrase('legacy.14ku9c0'),
}

const ruleExplanations = {
  TOOL_ABUSE_UNDECLARED_NETWORK: phrase('legacy.b3uz3h'),
  SOCIAL_ENG_MISLEADING_DESC: phrase('legacy.193vv54'),
  MANIFEST_MISSING_LICENSE: phrase('legacy.16m8g6s'),
  DATA_EXFIL_NETWORK_REQUESTS: phrase('legacy.11m0x07'),
  E1: phrase('legacy.11f7w0r'),
  LP3: phrase('legacy.rlvl9x'),
  TT3: phrase('legacy.1fbijdh'),
  E2: phrase('legacy.wwube7'),
  PE3: phrase('legacy.1liu94r'),
}

const sentenceTranslations = [
  {
    pattern: /^Only\s+(\d+)%\s+of skill content could be analyzed\.\s+(\d+)\s+of\s+(\d+)\s+files?\s+(?:is|are)\s+opaque to the scanner\.\s+Some content could not be verified as safe\.?$/i,
    render: ([, percent, opaque, total]) => text(
      `仅有 ${percent}% 的 Skill 内容可被分析。${total} 个文件中有 ${opaque} 个对扫描器不可解析，因此部分内容无法确认安全。`,
      `Only ${percent}% of the Skill content could be analyzed. ${opaque} of ${total} files are opaque to the scanner, so some content could not be verified as safe.`,
    ),
  },
  {
    pattern: /^Code or instructions reference external transmission\.\s*文件:\s*(.+)$/i,
    render: ([, file]) => text(
      `代码或指令引用了可能向外部发送数据的调用。文件：${file}`,
      `Code or instructions reference a call that may send data externally. File: ${file}`,
    ),
  },
  {
    pattern: /^Code accesses environment variables that may contain secrets\.\s*文件:\s*(.+)$/i,
    render: ([, file]) => text(
      `代码读取环境变量，可能接触密钥或敏感配置。文件：${file}`,
      `Code reads environment variables and may access secrets or sensitive configuration. File: ${file}`,
    ),
  },
  {
    pattern: /^Skill content asks the agent to ignore higher-priority instructions\.\s*文件:\s*(.+)$/i,
    render: ([, file]) => text(
      `Skill 内容要求忽略上级或系统指令。文件：${file}`,
      `The Skill instructs the Agent to ignore higher-priority or system instructions. File: ${file}`,
    ),
  },
  {
    pattern: /^Tainted flow:\s+'([^']+)'\s+from\s+(.+?)\s+→\s+(.+)$/i,
    render: ([, variable, source, sink]) => text(
      `污点数据流：变量 ${variable} 从 ${source} 流向 ${sink}。需要确认敏感数据是否被发送到网络出口。`,
      `Tainted data flow: ${variable} flows from ${source} to ${sink}. Confirm whether sensitive data is sent to a network sink.`,
    ),
  },
  {
    pattern: /^Credentials or environment variables flow to a network sink\. This is a high-confidence indicator of credential exfiltration\.?$/i,
    render: () => phrase('legacy.jafom'),
  },
  {
    pattern: /^Without declared permissions the skill's intent is opaque and cannot be validated\.?$/i,
    render: () => phrase('legacy.1cuujuu'),
  },
  {
    pattern: /^Code accesses environment variables that may contain secrets \(API keys, tokens\)\. This is a common pattern for credential theft\.?$/i,
    render: () => phrase('legacy.1f5of6n'),
  },
  {
    pattern: /^Code accesses credential files \(SSH keys, AWS credentials, etc\.\)\. This could indicate credential theft attempts\.?$/i,
    render: () => phrase('legacy.11s002q'),
  },
  {
    pattern: /^Data is being sent to an external URL\. This could be legitimate telemetry or data exfiltration\. Manual review is recommended\.?$/i,
    render: () => phrase('legacy.1xr4o1d'),
  },
  {
    pattern: /^Add a 'permissions' field to SKILL\.md listing the capabilities this skill requires\.?$/i,
    render: () => phrase('legacy.u0lbjs'),
  },
  {
    pattern: /^Never send credentials or environment variables over the network\. Use secure credential stores and avoid transmitting secrets in request bodies or URLs\.?$/i,
    render: () => phrase('legacy.129f5y5'),
  },
  {
    pattern: /^Avoid reading sensitive env vars \(API keys, tokens\) unless strictly required\. Use secrets managers or secure config\. Never log or transmit credentials\.?$/i,
    render: () => phrase('legacy.ae0ijt'),
  },
  {
    pattern: /^Remove references to credential paths\. Use environment variables or secrets managers\. For docs, use placeholder paths \(e\.g\., \/path\/to\/config\)\. Never load \.env or token files in production code paths\.?$/i,
    render: () => phrase('legacy.mkthze'),
  },
]

const statusTitle = (value) => translateDomain('skillStatus', value, phrase('legacy.1lpnuh4'))
const statusDisplay = (value, entry) => {
  if (isCancelled(entry)) return text('Cancelled（已取消）', 'CANCELLED')
  if (isEnglish.value) return value || '-'
  return value ? `${value}（${statusTitle(value)}）` : '-'
}
const severityDisplay = (value) => {
  const displayValue = String(value || '').toUpperCase()
  if (isEnglish.value) return displayValue || '-'
  return displayValue
    ? `${displayValue}（${translateDomain('risk', displayValue.toLowerCase(), severityLabels[displayValue] || phrase('legacy.1lpnuh4'))}）`
    : '-'
}
const recommendationDisplay = (value) => {
  const displayValue = String(value || '').toUpperCase()
  if (isEnglish.value) return displayValue || '-'
  return displayValue ? `${displayValue}（${recommendationLabels[displayValue] || phrase('legacy.1lpnuh4')}）` : '-'
}
const riskDisplay = (value) => {
  const displayValue = String(value || 'unknown')
  if (isEnglish.value) return displayValue
  const zh = {
    benign: phrase('legacy.1apxo2s'),
    suspicious: phrase('legacy.1x3ukv1'),
    malicious: phrase('legacy.m36raq'),
    unknown: phrase('legacy.1lpnuh4'),
  }[displayValue.toLowerCase()] || phrase('legacy.1lpnuh4')
  return `${displayValue}（${zh}）`
}
const bilingualText = (value) => {
  const displayValue = String(value || '').trim()
  if (!displayValue) return '-'
  if (isEnglish.value) return platformResultText(displayValue)
  if (termTranslations[displayValue]) return `${displayValue}（${termTranslations[displayValue]}）`
  for (const item of sentenceTranslations) {
    const match = displayValue.match(item.pattern)
    if (match) return item.render(match)
  }
  return displayValue
}
const platformResultText = (value) => {
  const displayValue = String(value || '').trim()
  if (!displayValue || !isEnglish.value) return displayValue
  // 仅使用已有英文译文，动态说明缺少翻译时继续按原文展示。
  const translationKey = legacyKey(displayValue)
  if (Object.hasOwn(legacyMessages['en-US'], translationKey.split('.')[1])) return t(translationKey)
  return displayValue
    .replace(/^规则：/, 'Rule: ')
    .replace(/^命中片段：/, 'Matched excerpt: ')
    .replace(/^判断依据：/, 'Rationale: ')
    .replace(/^建议：/, 'Recommendation: ')
    .replace(/^代码读取环境变量，可能接触密钥或敏感配置。\s*文件:\s*/i, 'Code reads environment variables and may access secrets or sensitive configuration. File: ')
    .replace(/^权限声明包含通配或过宽权限。\s*文件:\s*/i, 'The permission declaration contains wildcard or overly broad permissions. File: ')
}
const ruleFindingExplanation = (item) => {
  if (findingTypeOf(item) === 'documented_external_api') {
    return t('skillDetail.documentedApiExplanation')
  }
  const rule = item?.rule || item?.rule_id || ''
  if (ruleExplanations[rule] && !isEnglish.value) return ruleExplanations[rule]
  return bilingualText(item?.message || item?.description || item?.remediation || '')
}
const findingPolicyLabel = (item) => findingTypeLabel(findingTypeOf(item))
const formatAggregateLines = (lines) => {
  const unique = [...new Set(lines)].slice(0, 8)
  const suffix = lines.length > unique.length
    ? text(` 等 ${lines.length} 处`, ` and ${lines.length - unique.length} more`)
    : ''
  return `${unique.join(text('、', ', '))}${suffix}`
}
const findingTitle = (item) => {
  if (findingTypeOf(item) === 'documented_external_api') return text('文档型 API 示例', 'Documented API Example')
  return bilingualText(item?.title || item?.pattern || item?.message || '-')
}
const originLabel = (value) => ({
  local: phrase('legacy.zgeech'),
  github: 'GitHub',
  clawhub: 'ClawHub',
  internal: phrase('legacy.cr1wqg'),
  unknown: phrase('legacy.1lpnuh4'),
}[value] || value || '-')
const sourceChannelLabel = (value) => ({
  external_api: t('externalAccess.sources.external_api'),
  scanner: phrase('legacy.7ucd4c'),
  agent_manager_client: 'Agent Manager Client',
  upload_zip: phrase('legacy.17o43lg'),
  local_import: phrase('legacy.1iew9t7'),
  remote_download: phrase('legacy.1kroevr'),
  github: phrase('legacy.1uy421t'),
  clawhub: phrase('legacy.1ck2qj4'),
  direct_submit: phrase('legacy.1g1oqdi'),
}[value] || '')
const sourceLabelFromPath = (value) => {
  const text = String(value || '')
  if (text.includes('scanner_uploaded_skills')) return phrase('legacy.7ucd4c')
  if (text.includes('uploaded_skills') || text.includes('upload_import_sessions')) return phrase('legacy.17o43lg')
  if (text.includes('downloaded_skills') || text.includes('remote_import_sessions')) return phrase('legacy.1kroevr')
  if (text.includes('clawhub_skills')) return phrase('legacy.1ck2qj4')
  return ''
}
const sourceLabel = (entry) => {
  const source = entry?.source
  if (!source) return '-'
  const channel = sourceChannelLabel(source.channel)
  if (channel) return channel
  const pathLabel = sourceLabelFromPath(entry?.skill_path)
  if (pathLabel) return pathLabel
  return originLabel(source.origin)
}
// 审计编码只翻译一次，避免将已翻译文案再次转换为 legacy 编号。
const auditEventLabel = (value) => translateDomain('auditEvent', value, value || '-')

const formatAuditValue = (key, value) => {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'boolean') return translateDomain('auditValue', String(value))
  if (key === 'status') return translateDomain('skillStatus', value, String(value))
  if (key === 'risk_level' || key === 'pre_llm_risk_level') {
    return translateDomain('risk', String(value).toLowerCase(), String(value))
  }
  if (key === 'max_severity') {
    return translateDomain('risk', String(value).toLowerCase(), String(value))
  }
  if (Array.isArray(value)) return value.length ? value.join(text('、', ', ')) : text('无', 'None')
  if (typeof value === 'object') return JSON.stringify(value)
  // 路径及其他原始值保持原文，不作为翻译键。
  return String(value)
}

const formatAuditDetails = (details, limit = 6) => {
  if (!details || typeof details !== 'object') return '-'
  const entries = Object.entries(details).slice(0, limit)
  if (!entries.length) return '-'
  return entries
    .map(([key, value]) => `${translateDomain('auditDetail', key, key)}${text('：', ': ')}${formatAuditValue(key, value)}`)
    .join(text('；', '; '))
}

const statusColor = (value, entry) => {
  if (isCancelled(entry)) return 'default'
  return ({
    PENDING: 'gold',
    VETTED: 'orange',
    APPROVED: 'green',
    DEPLOYED: 'blue',
    REJECTED: 'red',
    RETIRED: 'default',
  }[value] || 'default')
}

const riskColor = (value) =>
  ({
    SAFE: 'green',
    BENIGN: 'green',
    LOW: 'green',
    SUSPICIOUS: 'orange',
    MEDIUM: 'orange',
    MALICIOUS: 'red',
    HIGH: 'red',
    EXTREME: 'magenta',
  }[(value || '').toUpperCase()] || 'default')

const severityColor = (value) =>
  ({
    SAFE: 'green',
    INFO: 'blue',
    LOW: 'green',
    MEDIUM: 'orange',
    HIGH: 'red',
    CRITICAL: 'magenta',
    EXTREME: 'magenta',
  }[(value || '').toUpperCase()] || 'default')

const formatFileSize = (value) => {
  let size = Number(value || 0)
  const units = ['B', 'KB', 'MB', 'GB']
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(size >= 100 || index === 0 ? 0 : 2)} ${units[index]}`
}

onMounted(() => {
  fetchDetail()
})

watch(
  () => route.params.skillId,
  () => {
    fetchDetail()
  },
)

watch(
  () => [activeTab.value, detail.value?.skill_id, diffBaseVersion.value, diffTargetVersion.value],
  () => { fetchVersionDiff() },
)

watch(
  () => route.query.tab,
  (value) => {
    activeTab.value = value === 'llm' ? 'vetting' : value || 'decision'
    if (value === 'llm') analysisTab.value = 'llm'
  },
)

watch(
  () => [skillspectorFindings.value.length, groupedSkillspectorFindings.value.length],
  () => {
    skillspectorFindingsActiveKey.value = nonEmptySkillspectorClassificationKeys.value
  },
  { immediate: true },
)
</script>

<style scoped>
/* LLM 分析报告 Markdown 样式 - 使用 :deep() 穿透 scoped */
.llm-explanation {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.7;
  color: #24292f;
  word-wrap: break-word;
}

/* 标题样式 */
.llm-explanation :deep(h1),
.llm-explanation :deep(h2),
.llm-explanation :deep(h3),
.llm-explanation :deep(h4) {
  font-weight: 600;
  margin-top: 20px;
  margin-bottom: 12px;
  padding-bottom: 0.3em;
  border-bottom: 1px solid #d0d7de;
}

.llm-explanation :deep(h1) { font-size: 24px; }
.llm-explanation :deep(h2) { font-size: 20px; }
.llm-explanation :deep(h3) { font-size: 16px; }

/* 段落样式 */
.llm-explanation :deep(p) {
  margin-top: 0;
  margin-bottom: 12px;
}

/* 列表样式 */
.llm-explanation :deep(ul),
.llm-explanation :deep(ol) {
  padding-left: 2em;
  margin-top: 0;
  margin-bottom: 12px;
}

.llm-explanation :deep(li) {
  margin-top: 0.25em;
}

/* 代码块样式（修复黑框问题）- 使用 !important 强制覆盖默认样式 */
.llm-explanation :deep(pre) {
  background-color: #f6f8fa !important;
  border-radius: 6px;
  padding: 16px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.45;
  border: 1px solid #d0d7de;
  margin: 12px 0;
  color: #24292f !important;
}

.llm-explanation :deep(code) {
  background-color: rgba(175, 184, 193, 0.2) !important;
  border-radius: 3px;
  font-size: 85%;
  padding: 0.2em 0.4em;
  font-family: monospace;
  color: #24292f !important;
}

.llm-explanation :deep(pre code) {
  background-color: transparent !important;
  padding: 0;
}

/* 引用样式 */
.llm-explanation blockquote {
  padding: 0 1em;
  color: #57606a;
  border-left: 0.25em solid #d0d7de;
  margin: 0 0 12px 0;
}

/* 表格样式 */
.llm-explanation table {
  border-spacing: 0;
  border-collapse: collapse;
  margin-bottom: 12px;
  width: 100%;
}

.llm-explanation table th,
.llm-explanation table td {
  padding: 6px 13px;
  border: 1px solid #d0d7de;
}

.llm-explanation table th {
  font-weight: 600;
  background-color: #f6f8fa;
}

.llm-explanation table tr:nth-child(2n) {
  background-color: #f6f8fa;
}

/* 链接样式 */
.llm-explanation a {
  color: #0969da;
  text-decoration: none;
}

.llm-explanation a:hover {
  text-decoration: underline;
}

/* 内联命令样式 */
.inline-command {
  background-color: #f6f8fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 85%;
  font-family: monospace;
}

/* 命令块样式 */
.command-block {
  background-color: #f6f8fa;
  padding: 12px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 85%;
  overflow-x: auto;
}

/* Frontmatter 样式 */
.frontmatter-box {
  background-color: #f6f8fa;
  padding: 12px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 通用 Markdown 样式 */
.markdown-body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.7;
  color: #24292f;
  word-wrap: break-word;
}

.markdown-body pre {
  background-color: #f6f8fa;
  border-radius: 6px;
  padding: 16px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.45;
  border: 1px solid #d0d7de;
  margin: 12px 0;
}

.markdown-body code {
  background-color: rgba(175, 184, 193, 0.2);
  border-radius: 3px;
  font-size: 85%;
  padding: 0.2em 0.4em;
  font-family: monospace;
}

.markdown-body pre code {
  background-color: transparent;
  padding: 0;
}

</style>

<style scoped>
.basic-info-card :deep(.ant-card-body),
.lifecycle-card :deep(.ant-card-body) {
  padding: 16px;
}

.skill-detail-page {
  max-width: 100%;
  overflow-x: hidden;
}

.skill-detail-page :deep(.ant-card),
.skill-detail-page :deep(.ant-card-body),
.skill-detail-page :deep(.ant-tabs),
.skill-detail-page :deep(.ant-tabs-content),
.skill-detail-page :deep(.ant-tabs-tabpane),
.skill-detail-page :deep(.ant-descriptions),
.skill-detail-page :deep(.ant-table-wrapper) {
  min-width: 0;
  max-width: 100%;
}

.basic-info-card { container-type: inline-size; }
.basic-summary {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(100px, 0.6fr) minmax(0, 1.3fr);
  gap: 16px 28px;
  margin: 0;
  padding-bottom: 16px;
  border-bottom: 1px solid #edf0f3;
}
.basic-metadata {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px 24px;
  margin: 16px 0 0;
}
.basic-field { min-width: 0; }
.basic-field dt { margin-bottom: 5px; color: #6b7280; font-size: 12px; line-height: 18px; }
.basic-field dd { margin: 0; color: #1f2937; font-size: 14px; line-height: 24px; overflow-wrap: anywhere; }
.basic-summary dd { min-height: 32px; display: flex; align-items: center; }
.basic-metadata .basic-field { display: flex; align-items: baseline; gap: 10px; }
.basic-metadata dt { flex: 0 0 auto; max-width: 48%; margin: 0; }
.basic-metadata dd { min-width: 0; }
.basic-metadata .sandbox-target-field { flex-wrap: wrap; gap: 0 10px; }
.sandbox-target-field dd { flex: 1 1 170px; }
.metadata-wide { grid-column: span 2; }
.skill-identifier dd { font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 12px; }
.basic-metadata :deep(.ant-tag) { margin: 0; white-space: normal; }

@container (max-width: 1000px) {
  .basic-summary { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  .version-field { grid-column: 1 / -1; }
  .basic-metadata { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (max-width: 480px) {
  .basic-summary, .basic-metadata { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .metadata-wide { grid-column: auto; }
  .basic-metadata .basic-field { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 12px; align-items: baseline; }
  .basic-metadata dt { max-width: none; }
}

.basic-info-card :deep(.ant-card-head-wrapper) {
  flex-wrap: wrap;
  gap: 12px;
}
.basic-info-card :deep(.ant-card-extra) {
  max-width: 100%;
}
.basic-scan-options :deep(.ant-checkbox-disabled + span) {
  color: rgba(0, 0, 0, 0.65);
}
.scan-options-label {
  color: #6b7280;
  font-size: 12px;
}

.basic-info-card :deep(.ant-space),
.basic-info-card :deep(.ant-space-item) { min-width: 0; max-width: 100%; }
.source-credential { white-space: normal; overflow-wrap: anywhere; }

.decision-loading { min-height: 620px; padding: 20px; }
.report-load-error { margin-bottom: 12px; }
.scan-execution-info :deep(.ant-descriptions-item-content),
.rejection-reason { overflow-wrap: anywhere; white-space: pre-wrap; }
.scan-execution-info :deep(.ant-descriptions-item-label) { width: 128px; }

.current-version-rail {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  align-items: center;
  width: 100%;
}

.current-version-badges {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  flex: 0 0 auto;
  max-width: 100%;
}
.current-version-badges :deep(.ant-tag) { margin: 0; white-space: nowrap; }
.summary-tag { display: inline-flex; align-items: center; gap: 6px; margin: 0; white-space: nowrap; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.summary-risk { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; }
.decision-jump { font-size: 12px; white-space: nowrap; }
.decision-jump:focus-visible { outline: 2px solid #1677ff; outline-offset: 3px; border-radius: 2px; }

.current-version-number {
  color: #1d4ed8;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 15px;
  white-space: nowrap;
  line-height: 24px;
}

.current-version-select {
  flex: 1 1 220px;
  min-width: 0;
  max-width: 320px;
}

.version-risk-chain {
  display: flex;
  gap: 6px;
  align-items: center;
  min-width: 350px;
}

.version-risk-stage {
  display: grid;
  gap: 3px;
  min-width: 84px;
}

.version-risk-stage small {
  color: #64748b;
  font-size: 11px;
  line-height: 1;
}

.version-risk-stage :deep(.ant-tag) {
  width: fit-content;
  margin-inline-end: 0;
}

.version-risk-arrow {
  color: #94a3b8;
  font-size: 12px;
}

.path-value {
  color: #475569;
  overflow-wrap: anywhere;
}

.lifecycle-row {
  display: flex;
  gap: 16px;
  align-items: center;
  width: 100%;
}

.lifecycle-heading {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
  align-items: center;
  white-space: nowrap;
}

.lifecycle-heading strong {
  font-size: 15px;
}

.lifecycle-steps {
  flex: 1 1 620px;
  min-width: 0;
}

.lifecycle-actions {
  flex: 0 0 auto;
  justify-content: flex-end;
}

@media (max-width: 1100px) {
  .lifecycle-row {
    flex-wrap: wrap;
  }

  .lifecycle-steps {
    order: 3;
    width: 100%;
    min-width: 0;
  }

  .lifecycle-actions {
    margin-left: auto;
  }
}

@media (max-width: 640px) {
  .basic-info-card :deep(.ant-card-head-wrapper) { padding: 12px 0; }
  .current-version-rail {
    align-items: flex-start;
    flex-direction: column;
  }

  .current-version-select {
    flex: auto;
    width: 100%;
    max-width: none;
  }

  .lifecycle-steps {
    overflow-x: auto;
  }
}

.markdown-body {
  padding: 16px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  background: #fff;
  line-height: 1.7;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  color: #16324f;
  margin-top: 1.2em;
}

.markdown-body :deep(code) {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 4px;
}

.markdown-body :deep(pre) {
  background: #0f172a;
  color: #e5e7eb;
  padding: 12px;
  border-radius: 8px;
  overflow: auto;
}

.llm-explanation {
  padding: 16px;
  background: #f7f9fc;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  line-height: 1.8;
  font-size: 14px;
  color: #333;
}

.llm-explanation :deep(h2),
.llm-explanation :deep(h3),
.llm-explanation :deep(h4) {
  margin-top: 16px;
  margin-bottom: 8px;
}

.llm-explanation :deep(p) {
  margin-bottom: 8px;
}

.llm-explanation :deep(ul),
.llm-explanation :deep(ol) {
  padding-left: 20px;
  margin-bottom: 8px;
}

.llm-explanation :deep(code) {
  background: #e8e8e8;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}

.llm-explanation :deep(pre) {
  background: #0f172a;
  color: #e5e7eb;
  padding: 12px;
  border-radius: 8px;
  overflow: auto;
}

.frontmatter-box {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  background: #f7f9fc;
  color: #16324f;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.refresh-report-button {
  box-shadow: 0 8px 20px rgba(22, 50, 79, 0.16);
}

.inline-command {
  display: inline-block;
  max-width: 520px;
  padding: 2px 6px;
  overflow: hidden;
  color: #16324f;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
  background: #f5f7fa;
  border-radius: 4px;
}

.command-block {
  margin: 0;
  padding: 10px;
  overflow: auto;
  color: #dbeafe;
  white-space: pre-wrap;
  word-break: break-word;
  background: #0f172a;
  border-radius: 8px;
}

.sandbox-error-output {
  margin: 0;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.evidence-box {
  margin-top: 8px;
  padding: 8px 10px;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.evidence-title {
  margin-bottom: 4px;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.evidence-line {
  font-family: monospace;
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.finding-section {
  margin-bottom: 12px;
}

.finding-section:last-child {
  margin-bottom: 0;
}

.finding-section-title {
  margin-bottom: 8px;
  color: #595959;
  font-weight: 600;
}

.governance-card-preview {
  max-width: 100%;
  overflow-x: auto;
  word-break: break-word;
}

.code-preview {
  width: 100%;
  max-width: 100%;
  max-height: 620px;
  overflow: auto;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fbfdff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
}

.drawer-code-preview {
  max-height: calc(100vh - 150px);
}

.code-line {
  display: flex;
  width: max-content;
  min-width: 100%;
}

.line-no {
  flex: 0 0 56px;
  padding: 0 10px;
  color: #8c8c8c;
  text-align: right;
  user-select: none;
  background: #f3f6fa;
  border-right: 1px solid #e5e7eb;
}

.line-text {
  flex: 0 0 auto;
  padding: 0 12px;
  white-space: pre;
}

.version-diff-toolbar,
.version-diff-file-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.version-diff-toolbar {
  margin-bottom: 12px;
}

.version-diff-swap {
  color: #2563eb;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.version-diff-swap:hover,
.version-diff-swap:focus-visible {
  color: #1d4ed8;
  border-color: #60a5fa;
  background: #dbeafe;
}

.version-diff-file {
  overflow: hidden;
  border: 1px solid #d8e0ea;
  border-radius: 8px;
  background: #fff;
}

.version-diff-file-toolbar {
  min-height: 48px;
  padding: 8px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #d8e0ea;
}

.version-diff-file-select {
  width: min(460px, 52vw);
}

.version-diff-grid {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr);
}

.version-diff-scroll {
  max-height: 560px;
  overflow: auto;
  color: #334155;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 12px;
  line-height: 20px;
  background: #fff;
}

.version-diff-grid--header {
  position: sticky;
  top: 0;
  z-index: 2;
  min-width: 840px;
  color: #475569;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 12px;
  font-weight: 600;
  line-height: 34px;
  background: #f8fafc;
  border-bottom: 1px solid #cbd5e1;
}

.version-diff-grid--header > div {
  padding: 0 12px;
}

.version-diff-grid--header > div + div,
.version-diff-row > .version-diff-line + .version-diff-line {
  border-left: 1px solid #cbd5e1;
}

.version-diff-row {
  min-width: 840px;
}

.version-diff-row--hunk {
  display: block;
}

.version-diff-hunk {
  box-sizing: border-box;
  width: 100%;
  min-width: 840px;
  padding: 2px 12px;
  color: #1d4ed8;
  background: #eff6ff;
  border-top: 1px solid #dbeafe;
  border-bottom: 1px solid #dbeafe;
}

.version-diff-line {
  display: grid;
  grid-template-columns: 52px 22px max-content;
  min-width: 0;
  white-space: pre;
}

.version-diff-line--inline {
  grid-template-columns: 52px 52px 22px max-content;
  width: max-content;
  min-width: 100%;
}

.version-diff-line-no {
  padding: 0 8px;
  color: #94a3b8;
  text-align: right;
  user-select: none;
  background: rgb(248 250 252 / 82%);
  border-right: 1px solid rgb(203 213 225 / 72%);
}

.version-diff-marker {
  color: #64748b;
  text-align: center;
  user-select: none;
}

.version-diff-text {
  padding-right: 16px;
}

.version-diff-line--removed {
  color: #7f1d1d;
  background: #fee2e2;
}

.version-diff-line--removed .version-diff-line-no {
  color: #b91c1c;
  background: #fecaca;
}

.version-diff-line--removed .version-diff-marker {
  color: #b91c1c;
  font-weight: 700;
}

.version-diff-line--added {
  color: #14532d;
  background: #dcfce7;
}

.version-diff-line--added .version-diff-line-no {
  color: #15803d;
  background: #bbf7d0;
}

.version-diff-line--added .version-diff-marker {
  color: #15803d;
  font-weight: 700;
}

.version-diff-line--empty {
  background:
    repeating-linear-gradient(
      -45deg,
      #f8fafc,
      #f8fafc 4px,
      #f1f5f9 4px,
      #f1f5f9 8px
    );
}

.version-diff-scroll--inline .version-diff-line--hunk {
  display: grid;
  grid-template-columns: 52px 52px 22px max-content;
  width: max-content;
  min-width: 100%;
  color: #1d4ed8;
  background: #eff6ff;
  border-top: 1px solid #dbeafe;
  border-bottom: 1px solid #dbeafe;
}

@media (max-width: 900px) {
  .version-diff-toolbar,
  .version-diff-file-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .version-diff-file-select {
    width: min(560px, 72vw);
  }

  .version-diff-scroll {
    max-height: 480px;
  }
}
</style>
