<template>
  <div class="skill-detail-page">
    <a-page-header :title="detailPageTitle" :sub-title="text('查看 Skill 详情、审核与审计记录', 'Review Skill details, approval, and audit records')">
      <template #extra>
        <a-button v-if="detail?.status === 'APPROVED'" type="primary" @click="openClientInstall"> {{ $t("legacy.1wbn313") }} </a-button>
        <a-button @click="handleDownloadSkill" :loading="downloadingSkill" :disabled="!detail?.skill_id"> {{ $t("legacy.fye4hw") }} </a-button>
      </template>
    </a-page-header>

    <a-card :title="$t('legacy.17qypnb')" class="basic-info-card" style="margin-top: 16px">
      <a-skeleton :loading="loading" active :paragraph="{ rows: 5 }">
        <a-descriptions :column="{ xs: 1, sm: 2, lg: 3, xxl: 4 }" size="small" bordered>
          <a-descriptions-item label="Skill ID" :span="2">{{ detail?.skill_id || skillId }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.hzx914')">{{ detail?.name || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1ccx4t4')">
            <a-tag :color="statusColor(detail?.status, detail)">{{ statusDisplay(detail?.status, detail) }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.13tzib2')">
            <a-tag v-if="detail?.status === 'PENDING'" color="default">-</a-tag>
            <a-tag v-else-if="detail?.risk_level === 'malicious'" color="red">{{ riskDisplay(detail.risk_level) }}</a-tag>
            <a-tag v-else-if="detail?.risk_level === 'suspicious'" color="orange">{{ riskDisplay(detail.risk_level) }}</a-tag>
            <a-tag v-else-if="detail?.risk_level === 'benign'" color="green">{{ riskDisplay(detail.risk_level) }}</a-tag>
            <a-tag v-else color="default">{{ riskDisplay(detail?.risk_level) }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.41rk3e')">{{ detail?.source?.author || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.2tds9c')">
            <a-space wrap>
              <span>{{ sourceLabel(detail) }}</span>
              <a-tag v-if="detail?.source?.token_name" color="blue">{{ $t("legacy.1tguyk3") }}{{ detail.source.token_name }}</a-tag>
            </a-space>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1tv5qh6')">
            <a-tag :color="detail?.declared_tools_valid ? 'green' : 'red'" :title="$t('legacy.1q4bwse')">
              {{ detail?.declared_tools_valid ? text('合规', 'Compliant') : text('不合规', 'Noncompliant') }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1rjm8hx')" :span="2">
            <span :title="$t('legacy.1108kfy')">
              {{ detail?.allowed_tools?.join(', ') || text('未声明', 'Not Declared') }}
            </span>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1k07gze')" :span="2">
            <a-space wrap>
              <a-tag :color="detail?.scan_reused ? 'green' : 'default'">
                {{ detail?.scan_reused ? text('已复用', 'Reused') : text('未复用', 'Not Reused') }}
              </a-tag>
              <span v-if="detail?.reused_from_skill_id">{{ $t("legacy.j3wbr2") }}{{ detail.reused_from_skill_id }}</span>
            </a-space>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1s59p3z')">{{ detail?.vetting?.sandbox_triggered ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1ftc08b')">
            <a-tag
              :color="detail?.vetting?.sandbox_required_by_policy ? 'orange' : 'default'"
              :title="$t('legacy.1d0deqb')"
            >
              {{ detail?.vetting?.sandbox_required_by_policy ? $t('legacy.btshni') : $t('legacy.9sspjt') }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1g74qkr')">{{ detail?.vetting?.sandbox_runtime || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.7fq7m5')">{{ sandboxDisplayImage }}</a-descriptions-item>
        </a-descriptions>
        <a-alert
          v-if="manualApprovalRequired"
          style="margin-top: 12px"
          type="error"
          show-icon
          :message="vettingFailed ? $t('legacy.11ldhwj') : $t('legacy.gobvd0')"
          :description="manualApprovalSummary"
        />
      </a-skeleton>
    </a-card>

    <a-card class="lifecycle-card" style="margin-top: 12px">
      <div class="lifecycle-row">
        <div class="lifecycle-heading">
          <strong>{{ $t("legacy.1uf97vz") }}</strong>
          <a-tag :color="statusColor(detail?.status, detail)">{{ statusDisplay(detail?.status, detail) }}</a-tag>
        </div>

        <a-steps :current="stepIndex" size="small" class="lifecycle-steps" :responsive="false">
          <a-step :title="$t('legacy.ybr38x')" :description="formatDateTime(detail?.submitted_at)" />
          <a-step :title="$t('legacy.1ws11do')" :description="detail?.approved_by || $t('legacy.a2uv9t')" />
          <a-step :title="$t('legacy.1tmnt86')" :description="formatDateTime(detail?.approved_at)" />
        </a-steps>

        <a-space class="lifecycle-actions" wrap>
            <a-button @click="fetchDetail" :loading="loading">{{ text('刷新', 'Refresh') }}</a-button>
            <a-tooltip :title="signatureVerifyDisabledReason">
              <span>
                <a-button
                  :disabled="!detail?.signature"
                  :loading="verifyingSignature"
                  @click="handleVerifySignature"
                > {{ $t("legacy.y6whtf") }} </a-button>
              </span>
            </a-tooltip>
            <a-button v-if="canApproveSkill" type="primary" @click="openApproveModal">
              {{ manualApprovalRequired ? $t('legacy.8ve3lv') : $t('legacy.1tmnt86') }}
            </a-button>
            <a-button v-if="detail?.status === 'VETTED'" danger @click="openRejectModal">{{ $t("legacy.1qrntx4") }}</a-button>
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

    <a-card :title="$t('legacy.17yj1t4')" style="margin-top: 12px">
      <a-tabs v-model:activeKey="activeTab">
        <a-tab-pane key="vetting" :tab="$t('legacy.1xjnbvp')">
          <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
            <a-space style="margin-bottom: 12px" wrap>
              <a-button type="primary" class="refresh-report-button" @click="fetchScanReport" :loading="loadingScanReport"> {{ $t("legacy.1y2sdbh") }} </a-button>
            </a-space>
            <a-descriptions :column="2" size="small" bordered>
              <a-descriptions-item :label="$t('legacy.13tzib2')">
                <a-tag v-if="detail?.status === 'PENDING'" color="default">
                  -
                </a-tag>
                <a-tag v-else-if="detail?.risk_level === 'malicious'" color="red">
                  {{ riskDisplay(detail.risk_level) }}
                </a-tag>
                <a-tag v-else-if="detail?.risk_level === 'suspicious'" color="orange">
                  {{ riskDisplay(detail.risk_level) }}
                </a-tag>
                <a-tag v-else-if="detail?.risk_level === 'benign'" color="green">
                  {{ riskDisplay(detail.risk_level) }}
                </a-tag>
                <a-tag v-else color="default">{{ riskDisplay(detail?.risk_level) }}</a-tag>
              </a-descriptions-item>
              <a-descriptions-item :label="$t('legacy.l6iuzr')">{{ detail?.vetting?.findings_count ?? 0 }}</a-descriptions-item>
              <a-descriptions-item :label="$t('legacy.13tfl8g')">{{ detail?.vetting?.analyzers_used?.join(', ') || '-' }}</a-descriptions-item>
              <a-descriptions-item :label="$t('legacy.12sj4tc')">{{ detail?.vetting?.scan_duration_seconds ?? 0 }}s</a-descriptions-item>
              <a-descriptions-item :label="$t('legacy.15hd6ok')">{{ detail?.scan_reused ? text('复用历史结果', 'Reused Previous Result') : text('本次执行扫描', 'New Scan') }}</a-descriptions-item>
              <a-descriptions-item :label="$t('legacy.1jezr7l')">{{ detail?.scan_cache_key || '-' }}</a-descriptions-item>
            </a-descriptions>
            <a-card v-if="judgementSummary" size="small" :title="$t('legacy.18h9kx8')" style="margin-top: 12px">
              <a-descriptions bordered size="small" :column="2">
                <a-descriptions-item :label="$t('legacy.1f9s0cj')">{{ judgementSummary.mode }}</a-descriptions-item>
                <a-descriptions-item :label="$t('legacy.1xza6lg')">{{ judgementSummary.strategy }}</a-descriptions-item>
                <a-descriptions-item :label="$t('legacy.1xvouvo')">{{ riskDisplay(judgementSummary.preRisk) }}</a-descriptions-item>
                <a-descriptions-item :label="$t('legacy.5t5taw')">{{ riskDisplay(judgementSummary.finalRisk) }}</a-descriptions-item>
                <a-descriptions-item v-if="judgementSummary.llmRisk" :label="$t('legacy.8qmekw')">{{ riskDisplay(judgementSummary.llmRisk) }}</a-descriptions-item>
                <a-descriptions-item :label="$t('legacy.1y6vbr8')">{{ judgementSummary.blockingCount }}</a-descriptions-item>
                <a-descriptions-item v-if="judgementSummary.reason" :label="$t('legacy.4zn1ks')" :span="2">
                  <div class="markdown-body judgement-reason" v-html="judgementReasonHtml" />
                </a-descriptions-item>
              </a-descriptions>
              <a-list
                v-if="judgementSummary.dismissedFindings.length"
                :data-source="judgementSummary.dismissedFindings"
                size="small"
                style="margin-top: 12px"
              >
                <template #header>{{ $t("legacy.943eoy") }}</template>
                <template #renderItem="{ item }">
                  <a-list-item>{{ item }}</a-list-item>
                </template>
              </a-list>
            </a-card>
            <a-card v-if="decisionRationaleItems.length" size="small" :title="$t('legacy.19ptc9g')" style="margin-top: 12px">
              <a-alert
                v-if="admissionBlocked"
                type="warning"
                show-icon
                :message="$t('legacy.1ymm0nv')"
                :description="$t('legacy.ir5o1o')"
                style="margin-bottom: 12px"
              />
              <a-list :data-source="decisionRationaleItems" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-space wrap>
                      <a-tag :color="item.color">{{ item.source }}</a-tag>
                      <span>{{ item.text }}</span>
                      <a-button type="link" size="small" style="padding: 0" @click="jumpToRationale(item.target)"> {{ $t("legacy.10fbkvl") }} </a-button>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-card>
            <a-divider />
            <a-collapse id="policy-notes-section">
              <a-collapse-panel key="policy-notes" :header="text(`策略说明（${detail?.vetting?.policy_notes?.length || 0}）`, `Policy Notes (${detail?.vetting?.policy_notes?.length || 0})`)">
                <a-list
                  :data-source="detail?.vetting?.policy_notes?.length ? detail.vetting.policy_notes : [$t('legacy.xuf598')]"
                  bordered
                  size="small"
                >
                  <template #renderItem="{ item }">
                    <a-list-item>{{ policyNoteText(item) }}</a-list-item>
                  </template>
                </a-list>
              </a-collapse-panel>
            </a-collapse>
            <a-divider />
            <a-card id="rule-analysis-section" size="small" :title="$t('legacy.1hpgf7r')">
              <template v-if="behavioralAnalysis">
                <a-descriptions :column="2" size="small" bordered>
                  <a-descriptions-item :label="$t('legacy.5p87cu')">
                    {{ localStaticAnalysis?.scanned_file_count ?? behavioralAnalysis.scanned_file_count ?? behavioralScannedFiles.length }}
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
                    <a-tag color="blue">behavioral:local</a-tag>
                    <a-tag v-if="localStaticAnalysis" color="cyan">agent-manager-local</a-tag>
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
            <a-divider />
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
                <a-descriptions :column="2" size="small" bordered>
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
            <a-divider />
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
                    <a-descriptions :column="2" size="small" bordered>
                      <a-descriptions-item :label="$t('legacy.2xyc8z')">{{ sandboxAnalysis.executed ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1sdwzrx')">{{ sandboxAnalysis.runtime || '-' }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1dltjhr')">
                        <a-button
                          v-if="sandboxAnalysis.entrypoint"
                          type="link"
                          style="padding: 0"
                          @click="openFileViewer(sandboxAnalysis.entrypoint)"
                        >
                          {{ sandboxAnalysis.entrypoint }}
                        </a-button>
                        <span v-else>-</span>
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.destq8')">
                        {{ sandboxAnalysis.runtime === 'docker' ? (sandboxAnalysis.image || 'agent-manager-sandbox-runtime:latest') : (sandboxAnalysis.image || '-') }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1abimny')">{{ sandboxAnalysis.probe_strategy || '-' }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.hvs01l')">
                        {{ Array.isArray(sandboxAnalysis.probe_args) && sandboxAnalysis.probe_args.length ? sandboxAnalysis.probe_args.join(' ') : '-' }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1cjrdy2')">{{ sandboxAnalysis.exit_code ?? '-' }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.181sskz')">{{ sandboxAnalysis.timed_out ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.12sj4tc')">{{ sandboxAnalysis.duration_ms ?? '-' }} ms</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1v67ot2')">{{ sandboxAnalysis.network_attempts ?? 0 }}</a-descriptions-item>
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
                      <template #bodyCell="{ column, record }">
                        <template v-if="column.key === 'probe'">
                          <a-space direction="vertical" size="small">
                            <strong>{{ record.probe_name }}</strong>
                            <span class="muted">{{ record.probe_description || '-' }}</span>
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
                          <span v-else>-</span>
                        </template>
                        <template v-else-if="column.key === 'command'">
                          <code class="inline-command">{{ formatSandboxCommand(record) }}</code>
                        </template>
                        <template v-else-if="column.key === 'exit_code'">
                          <a-tag :color="record.exit_code === 0 ? 'green' : 'orange'">{{ record.exit_code ?? '-' }}</a-tag>
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
                    <a-descriptions :column="2" size="small" bordered>
                      <a-descriptions-item :label="$t('legacy.54f4h3')" :span="2">
                        <pre class="command-block">{{ formatSandboxCommand(record) }}</pre>
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.c8d7bb')">{{ record.probe_generated_by || '-' }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1sdwzrx')">{{ record.runtime || sandboxAnalysis.runtime || '-' }}</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.12sj4tc')">{{ record.duration_ms ?? '-' }} ms</a-descriptions-item>
                      <a-descriptions-item :label="$t('legacy.1v67ot2')">{{ record.network_attempts ?? 0 }}</a-descriptions-item>
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
          </a-skeleton>
        </a-tab-pane>

        <a-tab-pane key="llm" :tab="$t('legacy.ka9ulq')">
          <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
            <template v-if="llmAnalysis">
              <a-card id="llm-section" size="small" :title="$t('legacy.1iy14k9')">
                <a-descriptions :column="2" size="small" bordered style="margin-bottom: 12px">
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

        <a-tab-pane key="governance-card" :tab="$t('legacy.11y6y7p')">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button @click="fetchGovernanceCard" :loading="loadingGovernanceCard">{{ $t("legacy.12qo56a") }}</a-button>
            <a-button type="primary" @click="handleRefreshGovernanceCard" :loading="loadingGovernanceCard"> {{ $t("legacy.1oqld67") }} </a-button>
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
          <a-alert
            v-if="governanceCard?.path"
            type="info"
            show-icon
            :message="governanceCard.path"
            style="margin-bottom: 12px"
          />
          <template v-if="governanceCardViewMode === 'preview'">
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
            <a-descriptions-item :label="$t('legacy.s9rtfe')">{{ detail?.signature ? $t('legacy.btshni') : $t('legacy.9sspjt') }}</a-descriptions-item>
            <a-descriptions-item :label="$t('legacy.14ju5sj')">{{ detail?.signature ? `${detail.signature.slice(0, 24)}...` : '-' }}</a-descriptions-item>
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
            v-if="skillContent?.manifest_path"
            type="info"
            show-icon
            :message="skillContent.manifest_path"
            :description="skillContent.encoding
              ? text(`编码：${skillContent.encoding}`, `Encoding: ${skillContent.encoding}`)
              : undefined"
            style="margin-bottom: 12px"
          />

          <template v-if="contentViewMode === 'preview'">
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
            <a-button @click="fetchSkillFiles">{{ $t("legacy.17oz484") }}</a-button>
            <span style="color: #8c8c8c">{{ $t("legacy.1vsm2qk") }} {{ skillFiles.length }} {{ $t("legacy.15u4aw8") }}</span>
          </a-space>
          <a-table
            :data-source="skillFiles"
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

        <a-tab-pane key="audit" :tab="$t('legacy.7wyi9c')">
          <a-table :data-source="auditRows" :columns="auditColumns" rowKey="event_id" :pagination="{ pageSize: 5 }">
            <template #bodyCell="{ column, record }">
              <span v-if="column.key === 'event_type'">{{ auditEventLabel(record.event_type) }}</span>
              <span v-else-if="column.key === 'actor'">{{ record.actor || $t('legacy.p0ysv3') }}</span>
              <span v-else-if="column.key === 'details'">{{ formatAuditDetails(record.details) }}</span>
            </template>
          </a-table>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <a-modal
      v-model:open="approveModalOpen"
      :title="$t('legacy.1xa4yul')"
      :ok-text="$t('legacy.1srvmx8')"
      :cancel-text="$t('legacy.1589w37')"
      :confirm-loading="actionLoading"
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
        <a-form-item :label="$t('legacy.1lakt7z')">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1v900uo')">
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
      @ok="submitReject"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1gs5bzm')">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.1l7e57j')" required>
          <a-textarea v-model:value="rejectReason" :rows="4" :placeholder="$t('legacy.1gqmn09')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="clientInstallOpen"
      :title="$t('legacy.sq6fxa')"
      :ok-text="$t('legacy.1em7bly')"
      :confirm-loading="clientInstallLoading"
      @ok="submitClientInstall"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item :label="$t('legacy.xyrx7l')" required>
          <a-select v-model:value="clientInstallTarget" show-search option-filter-prop="label" :placeholder="$t('legacy.1skpnm2')">
            <a-select-option v-for="target in clientTargets" :key="target.key" :value="target.key" :label="target.label">
              {{ target.label }}
            </a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
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
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { marked } from 'marked'

import {
  approveSkill,
  createClientTask,
  downloadSkill,
  getAudit,
  getSkillContent,
  getSkillDetail,
  getSkillFileContent,
  getSkillFiles,
  getSkillGovernanceCard,
  getSkillScanReport,
  listClients,
  refreshSkillGovernanceCard,
  rejectSkill,
  verifySkillSignature,
} from '../api'
import { formatDateTime } from '../utils/format'
import { translateDomain } from '../i18n'
import { useLocaleText } from '../i18n/useLocaleText'
import AttackChainGraph from '../components/AttackChainGraph.vue'

const { isEnglish, phrase, text } = useLocaleText()
const route = useRoute()
const skillId = computed(() => route.params.skillId)
const detailPageTitle = computed(() => {
  const name = detail.value?.name || skillId.value
  return text(`Skill 详情：${name}`, `Skill Details: ${name}`)
})
const activeTab = ref(route.query.tab || 'vetting')
const loading = ref(false)
const loadingScanReport = ref(false)
const loadingContent = ref(false)
const loadingGovernanceCard = ref(false)
const verifyingSignature = ref(false)
const downloadingSkill = ref(false)
const actionLoading = ref(false)
const actionType = ref('')
const detail = ref(null)
const auditRows = ref([])
const scanReport = ref(null)
const governanceCard = ref(null)
const skillContent = ref(null)
const skillFiles = ref([])
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
const clientInstallOpen = ref(false)
const clientInstallLoading = ref(false)
const clientInstallTarget = ref('')
const managedClients = ref([])
const clientTargets = computed(() => managedClients.value.flatMap(client =>
  (client.agents || [])
    .filter(agent => agent.skill_management_supported && (client.governance_mode !== 'strict' || agent.managed_agent_id))
    .map(agent => ({
      key: `${client.client_id}\x00${agent.agent_type}`,
      label: `${client.name} / ${agent.agent_type}`,
      clientId: client.client_id,
      agentType: agent.agent_type,
      managedAgentId: agent.managed_agent_id,
    })),
))

const auditColumns = computed(() => [
  { title: text('时间', 'Time'), dataIndex: 'timestamp', key: 'timestamp', width: 180, customRender: ({ text: value }) => formatDateTime(value) },
  { title: text('事件', 'Event'), dataIndex: 'event_type', key: 'event_type', width: 180 },
  { title: text('操作人', 'Operator'), dataIndex: 'actor', key: 'actor', width: 120 },
  { title: text('详情', 'Details'), dataIndex: 'details', key: 'details' },
])

const auditEventLabels = {
  skill_submitted: phrase('legacy.1ctggg0'),
  skill_processing_completed: phrase('legacy.4q96e1'),
  skill_queued_for_review: phrase('legacy.13g0wa9'),
  skill_vetted: phrase('legacy.14mw4ld'),
  skill_approved: phrase('legacy.1irm9dn'),
  skill_rejected: phrase('legacy.v95xbp'),
  skill_deployed: phrase('legacy.10iljsa'),
  skill_retired: phrase('legacy.xrktp3'),
  skill_signature_verified: phrase('legacy.niy9wk'),
  skill_tamper_detected: phrase('legacy.1r553w'),
  skill_load_allowed: phrase('legacy.13u1sex'),
  skill_load_blocked: phrase('legacy.1yqcn2t'),
  tool_invoked: phrase('legacy.13iq9ke'),
  tool_blocked: phrase('legacy.1hed6yi'),
}

const auditDetailLabels = {
  skill_path: phrase('legacy.1lv21p9'),
  status: phrase('legacy.1ccx4t4'),
  risk_level: phrase('legacy.hm077g'),
  pre_llm_risk_level: phrase('legacy.s1hoes'),
  max_severity: phrase('legacy.syac4h'),
  violations: phrase('legacy.1mfo0dp'),
  verification_mode: phrase('legacy.1x88724'),
  reason: phrase('legacy.jsgjbe'),
  note: phrase('legacy.b5m1l6'),
}

const fileColumns = computed(() => [
  { title: text('路径', 'Path'), dataIndex: 'path', key: 'path' },
  { title: text('大小', 'Size'), dataIndex: 'size_bytes', key: 'size_bytes', width: 140, customRender: ({ text: value }) => formatFileSize(value) },
  { title: text('修改时间', 'Modified At'), dataIndex: 'modified_at', key: 'modified_at', width: 220, customRender: ({ text: value }) => formatDateTime(value) },
])

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
  loading.value = true
  try {
    const data = await getSkillDetail(skillId.value)
    detail.value = data
    signatureResult.value = null
    const [auditResult, reportResult, contentResult, filesResult, cardResult] = await Promise.allSettled([
      getAudit({ skill_id: data.skill_id, since_hours: 720, limit: 50 }),
      getSkillScanReport(data.skill_id),
      getSkillContent(data.skill_id),
      getSkillFiles(data.skill_id),
      getSkillGovernanceCard(data.skill_id),
    ])
    auditRows.value = auditResult.status === 'fulfilled' && Array.isArray(auditResult.value)
      ? auditResult.value
      : []
    scanReport.value = reportResult.status === 'fulfilled'
      ? (reportResult.value?.scan_report || null)
      : null
    skillContent.value = contentResult.status === 'fulfilled' ? (contentResult.value || null) : null
    skillFiles.value = filesResult.status === 'fulfilled' ? (filesResult.value?.files || []) : []
    governanceCard.value = cardResult.status === 'fulfilled' ? (cardResult.value || null) : null
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.qrrlus'))
  } finally {
    loading.value = false
  }
}

const openClientInstall = async () => {
  clientInstallTarget.value = ''
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

const fetchScanReport = async () => {
  if (!detail.value) return
  loadingScanReport.value = true
  try {
    const data = await getSkillScanReport(detail.value.skill_id)
    scanReport.value = data.scan_report || {}
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.g9q48r'))
  } finally {
    loadingScanReport.value = false
  }
}

const fetchSkillContent = async () => {
  if (!detail.value) return
  loadingContent.value = true
  try {
    skillContent.value = await getSkillContent(detail.value.skill_id)
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1iff97n'))
  } finally {
    loadingContent.value = false
  }
}

const fetchSkillFiles = async () => {
  if (!detail.value) return
  try {
    const data = await getSkillFiles(detail.value.skill_id)
    skillFiles.value = data?.files || []
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1rirokg'))
  }
}

const fetchGovernanceCard = async () => {
  if (!detail.value) return
  loadingGovernanceCard.value = true
  try {
    governanceCard.value = await getSkillGovernanceCard(detail.value.skill_id)
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.82xq4f'))
  } finally {
    loadingGovernanceCard.value = false
  }
}

const handleRefreshGovernanceCard = async () => {
  if (!detail.value) return
  loadingGovernanceCard.value = true
  try {
    governanceCard.value = await refreshSkillGovernanceCard(detail.value.skill_id)
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
    const blob = await downloadSkill(detail.value.skill_id)
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

const openFileViewer = async (path) => {
  if (!detail.value || !path) return
  viewingFilePath.value = path
  fileViewerOpen.value = true
  loadingFileViewer.value = true
  try {
    viewedFile.value = await getSkillFileContent(detail.value.skill_id, path)
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
    signatureResult.value = await verifySkillSignature(detail.value.skill_id)
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
  if (!detail.value) return
  actionLoading.value = true
  actionType.value = 'approve'
  try {
    await approveSkill(detail.value.skill_id, { approver: currentUser(), note: approveNote.value.trim() || null })
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
  if (!detail.value) return
  if (!rejectReason.value.trim()) {
    message.warning(phrase('legacy.erwuhg'))
    return
  }
  actionLoading.value = true
  actionType.value = 'reject'
  try {
    await rejectSkill(detail.value.skill_id, { reviewer: currentUser(), reason: rejectReason.value.trim() })
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
const llmExplanationHtml = computed(() => {
  const text = llmAnalysis.value?.report || ''
  if (!text) return phrase('legacy.xsay8c')
  return marked.parse(text)
})
const riskReconciliation = computed(() => scanReport.value?.risk_reconciliation || null)
const riskClassification = computed(() => scanReport.value?.risk_classification || null)
const findingClassificationGroups = computed(() => [
  { key: 'blocking', label: text('阻断项', 'Blocking') },
  { key: 'risk', label: text('可疑项', 'Suspicious') },
  { key: 'noise', label: text('噪声', 'Noise') },
])
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
const findingSignature = (item) => [
  item?.rule || item?.rule_id || '',
  item?.category || '',
  item?.title || item?.message || '',
  item?.file || item?.file_path || '',
].map(value => String(value || '').toLowerCase()).join('|')
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
const classifiedFindingOf = (item) => classifiedFindingMap.value.get(findingSignature(item))
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
const judgementSummary = computed(() => {
  const rec = riskReconciliation.value
  if (!rec) return null
  return {
    mode: judgementModeText(rec.judgement_mode || scanReport.value?.judgement_mode),
    strategy: rec.llm_downgraded ? phrase('legacy.1y0u2y2') : (rec.llm_downgrade_blocked ? phrase('legacy.bn5sxy') : phrase('legacy.9sok78')),
    preRisk: rec.pre_llm_risk_level,
    finalRisk: rec.final_risk_level || detail.value?.risk_level,
    llmRisk: rec.llm_risk_level,
    blockingCount: riskClassification.value?.blocking_count || 0,
    reason: rec.downgrade_reason || '',
    dismissedFindings: Array.isArray(rec.dismissed_findings) ? rec.dismissed_findings : [],
  }
})
const judgementReasonHtml = computed(() => marked.parse(judgementSummary.value?.reason || ''))
const judgementModeText = (mode) => ({
  strict: phrase('legacy.zhhsio'),
  balanced: phrase('legacy.118ugth'),
  permissive: phrase('legacy.xjfgxu'),
}[mode] || phrase('legacy.118ugth'))
const behavioralAnalysis = computed(() => scanReport.value?.behavioral_analysis || null)
const behavioralFindings = computed(() => behavioralAnalysis.value?.findings || [])
const behavioralScannedFiles = computed(() => behavioralAnalysis.value?.scanned_files || [])
const localStaticAnalysis = computed(() => scanReport.value?.local_static_analysis || null)
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
  const nested = [
    ...behavioralFindings.value,
    ...(localStaticAnalysis.value?.findings || []),
  ].map(normalizeRuleFinding)
  return nested.length ? nested : topLevelRuleFindings.value
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
  const text = String(note || '')
  const match = text.match(/^\[BLOCK\]\s+([^:]+):\s*(.+)$/)
  if (!match) return null
  const [, code, message] = match
  const toolMatch = message.match(/Tool '([^']+)' is not in the company allowlist/i)
  if (code === 'tool_not_in_allowlist' && toolMatch) {
    return {
      code,
      source: phrase('legacy.1lz1myh'),
      color: 'red',
      target: 'policy',
      text: text(
        `工具声明不在白名单：${toolMatch[1]}。安全研判可以是安全，但该工具权限未被公司策略允许，因此准入被拒绝。`,
        `The declared tool is not allowlisted: ${toolMatch[1]}. The security assessment may be safe, but admission was rejected because company policy does not allow this permission.`,
      ),
    }
  }
  return {
    code,
    source: phrase('legacy.1lz1myh'),
    color: 'red',
    target: 'policy',
    text: `${code}：${message}`,
  }
}
const policyBlockItems = computed(() =>
  policyNotes.value
    .map(parsePolicyBlock)
    .filter(Boolean),
)
const policyNoteText = (note) => {
  const parsed = parsePolicyBlock(note)
  return parsed ? parsed.text : deepScanText(note)
}
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
  const risk = detail.value?.risk_level ? riskDisplay(detail.value.risk_level) : phrase('legacy.1lpnuh4')
  const reasons = policyBlockItems.value.map((item) => item.text).join('；')
  return text(
    `安全判定：${risk}。最终状态为已拒绝，是因为准入策略未通过：${reasons}`,
    `Security assessment: ${risk}. The final status is Rejected because admission policy failed: ${reasons}`,
  )
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
const riskRationaleItems = computed(() => {
  const finalRisk = detail.value?.risk_level
  if (!['suspicious', 'malicious'].includes(finalRisk)) return []
  const findings = Array.isArray(scanReport.value?.findings) ? scanReport.value.findings : []
  const items = findings
    .filter((item) => findingSupportsRisk(item, finalRisk))
    .sort((a, b) => severityRank(b.severity) - severityRank(a.severity))
    .map((item) => {
      const source = rationaleSource(item.source)
      return {
        source: source.label,
        color: source.color,
        target: source.target,
        text: rationaleText(item),
      }
    })

  const llmRisk = llmAnalysis.value?.risk_level
  if (llmRisk === finalRisk) {
    items.push({
      source: 'LLM',
      color: 'purple',
      target: 'llm',
      text: finalRisk === 'malicious' ? phrase('legacy.hf8tnk') : phrase('legacy.sze5d3'),
    })
  }

  if (!items.length && detail.value?.vetting?.policy_notes?.length) {
    items.push({
      source: phrase('legacy.1xza6lg'),
      color: 'blue',
      target: 'policy',
      text: detail.value.vetting.policy_notes[0],
    })
  }
  const seen = new Set()
  return items.filter((item) => {
    const key = `${item.source}:${item.text}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 3)
})
const decisionRationaleItems = computed(() => {
  const items = [...policyBlockItems.value, ...riskRationaleItems.value]
  if (!items.length && detail.value?.status === 'REJECTED' && detail.value?.rejection_reason) {
    items.push({
      source: phrase('legacy.mxm4hl'),
      color: 'red',
      target: 'policy',
      text: detail.value.rejection_reason,
    })
  }
  const seen = new Set()
  return items.filter((item) => {
    const key = `${item.source}:${item.text}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 5)
})
const skillspectorAnalysis = computed(() => scanReport.value?.skillspector_analysis || null)
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
const rationaleSource = (source) => {
  const text = String(source || '').toLowerCase()
  if (text.includes('sandbox')) return { label: 'Sandbox', color: 'orange', target: 'sandbox' }
  if (text.includes('skillspector')) return { label: isEnglish.value ? 'Deep Analysis' : phrase('legacy.l2wtjk'), color: 'cyan', target: 'skillspector' }
  if (text.includes('llm')) return { label: 'LLM', color: 'purple', target: 'llm' }
  return { label: isEnglish.value ? 'Rules' : phrase('legacy.16w14qm'), color: 'blue', target: 'rule' }
}
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
const findingSupportsRisk = (finding, finalRisk) => {
  const rank = severityRank(finding?.severity)
  if (finalRisk === 'malicious') return rank >= 4
  if (finalRisk === 'suspicious') return rank >= 2 && rank <= 3
  return false
}
const rationaleText = (finding) => {
  const severity = String(finding?.severity || '').toUpperCase()
  const title = finding?.title || finding?.message || finding?.rule || finding?.rule_id || phrase('legacy.1j1qm51')
  const text = bilingualText(title)
  return severity ? `${severity}：${text}` : text
}
const jumpToRationale = async (target) => {
  if (target === 'llm') activeTab.value = 'llm'
  else activeTab.value = 'vetting'
  await nextTick()
  const id = {
    rule: 'rule-analysis-section',
    skillspector: 'skillspector-section',
    sandbox: 'sandbox-section',
    llm: 'llm-section',
    policy: 'policy-notes-section',
  }[target]
  if (id) document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const sandboxDisplayImage = computed(() => {
  if (sandboxAnalysis.value?.image) return sandboxAnalysis.value.image
  if (detail.value?.vetting?.sandbox_runtime === 'docker') return 'agent-manager-sandbox-runtime:latest'
  return '-'
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
  const translated = phrase(displayValue)
  if (translated !== displayValue) return translated
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
    return text(
      '文档中声明的固定 API endpoint 或 curl 示例，按策略记录为噪声；不等同于读取用户数据、凭据或文件后进行数据外传。',
      'A fixed API endpoint or curl example declared in documentation is classified as noise. It does not by itself indicate exfiltration of user data, credentials, or files.',
    )
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
const auditEventLabel = (value) => phrase(auditEventLabels[value] || value || '-')

const formatAuditValue = (key, value) => {
  if (value === null || value === undefined || value === '') return '-'
  if (key === 'status') return statusDisplay(String(value))
  if (key === 'risk_level' || key === 'pre_llm_risk_level') {
    return riskDisplay(value)
  }
  if (key === 'max_severity') {
    return isEnglish.value ? String(value).toUpperCase() : (severityLabels[String(value).toUpperCase()] || String(value))
  }
  if (Array.isArray(value)) return value.length ? value.join(text('、', ', ')) : text('无', 'None')
  if (typeof value === 'object') return JSON.stringify(value)
  return phrase(String(value))
}

const formatAuditDetails = (details, limit = 6) => {
  if (!details || typeof details !== 'object') return '-'
  const entries = Object.entries(details).slice(0, limit)
  if (!entries.length) return '-'
  return entries
    .map(([key, value]) => `${phrase(auditDetailLabels[key] || key)}${text('：', ': ')}${formatAuditValue(key, value)}`)
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
    LOW: 'green',
    MEDIUM: 'orange',
    HIGH: 'red',
    EXTREME: 'magenta',
  }[value] || 'default')

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
  () => route.query.tab,
  (value) => {
    activeTab.value = value || 'vetting'
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

.judgement-reason :deep(p:last-child) {
  margin-bottom: 0;
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

.basic-info-card :deep(.ant-descriptions-item-label) {
  width: 124px;
  white-space: nowrap;
}

.basic-info-card :deep(.ant-descriptions-item-content) {
  min-width: 0;
  overflow-wrap: anywhere;
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
</style>
