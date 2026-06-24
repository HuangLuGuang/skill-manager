<template>
  <div class="skill-detail-page">
    <a-page-header :title="detail?.name ? `技能详情：${detail.name}` : `技能详情：${skillId}`" sub-title="查看技能详情、审核与审计记录" />

    <a-card title="基础信息" class="basic-info-card" style="margin-top: 16px">
      <a-skeleton :loading="loading" active :paragraph="{ rows: 5 }">
        <a-descriptions :column="{ xs: 1, sm: 2, lg: 3, xxl: 4 }" size="small" bordered>
          <a-descriptions-item label="Skill ID" :span="2">{{ detail?.skill_id || skillId }}</a-descriptions-item>
          <a-descriptions-item label="名称">{{ detail?.name || '-' }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="statusColor(detail?.status)">{{ statusDisplay(detail?.status) }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="安全判定">
            <a-tag v-if="detail?.status === 'PENDING'" color="default">-</a-tag>
            <a-tag v-else-if="detail?.risk_level === 'malicious'" color="red">{{ riskDisplay(detail.risk_level) }}</a-tag>
            <a-tag v-else-if="detail?.risk_level === 'suspicious'" color="orange">{{ riskDisplay(detail.risk_level) }}</a-tag>
            <a-tag v-else-if="detail?.risk_level === 'benign'" color="green">{{ riskDisplay(detail.risk_level) }}</a-tag>
            <a-tag v-else color="default">{{ riskDisplay(detail?.risk_level) }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="作者">{{ detail?.source?.author || '-' }}</a-descriptions-item>
          <a-descriptions-item label="来源">{{ originLabel(detail?.source?.origin) }}</a-descriptions-item>
          <a-descriptions-item label="工具声明是否合规">
            <a-tag :color="detail?.declared_tools_valid ? 'green' : 'red'" title="按策略页的允许工具白名单和禁止权限/工具校验">
              {{ detail?.declared_tools_valid ? '合规' : '不合规' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="SKILL.md 声明工具" :span="2">
            <span title="来自 SKILL.md 的 allowed-tools 字段，表示 skill 声明可能需要使用的工具权限">
              {{ detail?.allowed_tools?.join(', ') || '未声明' }}
            </span>
          </a-descriptions-item>
          <a-descriptions-item label="扫描复用" :span="2">
            <a-space wrap>
              <a-tag :color="detail?.scan_reused ? 'green' : 'default'">
                {{ detail?.scan_reused ? '已复用' : '未复用' }}
              </a-tag>
              <span v-if="detail?.reused_from_skill_id">来源：{{ detail.reused_from_skill_id }}</span>
            </a-space>
          </a-descriptions-item>
          <a-descriptions-item label="Sandbox 已触发">{{ detail?.vetting?.sandbox_triggered ? '是' : '否' }}</a-descriptions-item>
          <a-descriptions-item label="策略强制 Sandbox">
            <a-tag
              :color="detail?.vetting?.sandbox_required_by_policy ? 'orange' : 'default'"
              title="表示这次 Sandbox 不是用户手动勾选触发的，而是因为风险等级命中了策略页里的“强制 Sandbox 风险等级”，系统自动要求执行"
            >
              {{ detail?.vetting?.sandbox_required_by_policy ? '是' : '否' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="Sandbox 后端">{{ detail?.vetting?.sandbox_runtime || '-' }}</a-descriptions-item>
          <a-descriptions-item label="Sandbox 镜像">{{ sandboxDisplayImage }}</a-descriptions-item>
          <a-descriptions-item label="技能路径" :span="4">
            <span class="path-value">{{ detail?.skill_path || '-' }}</span>
          </a-descriptions-item>
        </a-descriptions>
        <a-alert
          v-if="admissionBlocked"
          style="margin-top: 12px"
          type="error"
          show-icon
          message="准入策略拒绝"
          :description="admissionBlockedSummary"
        />
      </a-skeleton>
    </a-card>

    <a-card class="lifecycle-card" style="margin-top: 12px">
      <div class="lifecycle-row">
        <div class="lifecycle-heading">
          <strong>生命周期与操作</strong>
          <a-tag :color="statusColor(detail?.status)">{{ statusDisplay(detail?.status) }}</a-tag>
        </div>

        <a-steps :current="stepIndex" size="small" class="lifecycle-steps" :responsive="false">
          <a-step title="提交" :description="formatDateTime(detail?.submitted_at)" />
          <a-step title="审核" :description="detail?.approved_by || '待审核'" />
          <a-step title="批准" :description="formatDateTime(detail?.approved_at)" />
        </a-steps>

        <a-space class="lifecycle-actions" wrap>
            <a-button @click="fetchDetail" :loading="loading">刷新</a-button>
            <a-tooltip :title="signatureVerifyDisabledReason">
              <span>
                <a-button
                  :disabled="!detail?.signature"
                  :loading="verifyingSignature"
                  @click="handleVerifySignature"
                >
                  验签
                </a-button>
              </span>
            </a-tooltip>
            <a-button v-if="canApproveSkill" type="primary" @click="openApproveModal">
              {{ admissionBlocked ? '例外批准' : '批准' }}
            </a-button>
            <a-button v-if="detail?.status === 'VETTED'" danger @click="openRejectModal">拒绝</a-button>
        </a-space>
      </div>
      <a-alert
        v-if="signatureResult"
        style="margin-top: 12px"
        :type="signatureResult.valid ? 'success' : 'error'"
        show-icon
        :message="signatureResult.valid ? '签名校验通过' : '签名校验失败'"
        :description="signatureResultReason"
      />
    </a-card>

    <a-card title="安全检测与治理" style="margin-top: 12px">
      <a-tabs v-model:activeKey="activeTab">
        <a-tab-pane key="vetting" tab="安全检测">
          <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
            <a-space style="margin-bottom: 12px" wrap>
              <a-button type="primary" class="refresh-report-button" @click="fetchScanReport" :loading="loadingScanReport">
                刷新报告
              </a-button>
            </a-space>
            <a-descriptions :column="2" size="small" bordered>
              <a-descriptions-item label="安全判定">
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
              <a-descriptions-item label="发现项">{{ detail?.vetting?.findings_count ?? 0 }}</a-descriptions-item>
              <a-descriptions-item label="规则分析器">{{ detail?.vetting?.analyzers_used?.join(', ') || '-' }}</a-descriptions-item>
              <a-descriptions-item label="耗时">{{ detail?.vetting?.scan_duration_seconds ?? 0 }}s</a-descriptions-item>
              <a-descriptions-item label="扫描缓存">{{ detail?.scan_reused ? '复用历史结果' : '本次执行扫描' }}</a-descriptions-item>
              <a-descriptions-item label="缓存 Key">{{ detail?.scan_cache_key || '-' }}</a-descriptions-item>
            </a-descriptions>
            <a-card v-if="decisionRationaleItems.length" size="small" title="最终判定依据" style="margin-top: 12px">
              <a-alert
                v-if="admissionBlocked"
                type="warning"
                show-icon
                message="安全研判与准入结果是两条线"
                description="安全判定用于说明内容风险；准入结果还会校验工具白名单、权限边界、许可证等策略。即使安全判定为安全，策略违规仍会导致拒绝。"
                style="margin-bottom: 12px"
              />
              <a-list :data-source="decisionRationaleItems" size="small">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-space wrap>
                      <a-tag :color="item.color">{{ item.source }}</a-tag>
                      <span>{{ item.text }}</span>
                      <a-button type="link" size="small" style="padding: 0" @click="jumpToRationale(item.target)">
                        查看
                      </a-button>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-card>
            <a-divider />
            <a-collapse id="policy-notes-section">
              <a-collapse-panel key="policy-notes" :header="`策略说明（${detail?.vetting?.policy_notes?.length || 0}）`">
                <a-list
                  :data-source="detail?.vetting?.policy_notes?.length ? detail.vetting.policy_notes : ['暂无策略说明']"
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
            <a-card id="rule-analysis-section" size="small" title="规则分析结果">
              <template v-if="behavioralAnalysis">
                <a-descriptions :column="2" size="small" bordered>
                  <a-descriptions-item label="扫描文件数">
                    {{ localStaticAnalysis?.scanned_file_count ?? behavioralAnalysis.scanned_file_count ?? behavioralScannedFiles.length }}
                  </a-descriptions-item>
                  <a-descriptions-item label="命中规则数">
                    {{ ruleAnalysisFindings.length }}
                  </a-descriptions-item>
                  <a-descriptions-item label="最高严重级别">
                    <a-tag :color="severityColor(localStaticAnalysis?.max_severity || behavioralAnalysis.max_severity)">
                      {{ localStaticAnalysis?.max_severity || behavioralAnalysis.max_severity || '-' }}
                    </a-tag>
                  </a-descriptions-item>
                  <a-descriptions-item label="规则分析器">
                    <a-tag color="blue">behavioral:local</a-tag>
                    <a-tag v-if="localStaticAnalysis" color="cyan">agent-manager-local</a-tag>
                  </a-descriptions-item>
                </a-descriptions>
                <a-collapse
                  style="margin-top: 12px"
                  :default-active-key="ruleAnalysisFindings.length ? ['findings'] : []"
                >
                  <a-collapse-panel key="findings" :header="`规则命中项（${ruleAnalysisFindings.length}）`">
                    <a-list
                      v-if="ruleAnalysisFindings.length"
                      :data-source="ruleAnalysisFindings"
                      bordered
                      size="small"
                    >
                      <template #renderItem="{ item }">
                        <a-list-item>
                          <div style="width: 100%">
                            <a-space wrap>
                              <a-tag :color="severityColor(item.severity)">{{ item.severity }}</a-tag>
                              <strong>{{ bilingualText(item.title) }}</strong>
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
                            </a-space>
                            <div style="margin-top: 6px">{{ bilingualText(item.message) }}</div>
                          </div>
                        </a-list-item>
                      </template>
                    </a-list>
                    <a-empty v-else :image-style="{ height: '36px' }" description="本次规则分析没有命中项" />
                  </a-collapse-panel>
                  <a-collapse-panel key="files" :header="`已扫描文件（${behavioralScannedFiles.length}）`">
                    <a-list v-if="behavioralScannedFiles.length" :data-source="behavioralScannedFiles" bordered size="small">
                      <template #renderItem="{ item }">
                        <a-list-item>
                          <a-button type="link" style="padding: 0" @click="openFileViewer(item)">{{ item }}</a-button>
                        </a-list-item>
                      </template>
                    </a-list>
                    <a-empty v-else :image-style="{ height: '36px' }" description="没有已扫描文件记录" />
                  </a-collapse-panel>
                </a-collapse>
              </template>
              <a-empty
                v-else
                description="当前没有可展示的规则分析结果。若本次提交启用了规则分析，但这里仍为空，请刷新报告。"
              />
            </a-card>
            <a-divider />
            <a-card id="skillspector-section" size="small" title="深度扫描结果">
              <template v-if="skillspectorAnalysis">
                <a-alert
                  v-if="skillspectorAnalysis.error"
                  type="warning"
                  show-icon
                  message="深度扫描未完成"
                  :description="deepScanText(skillspectorAnalysis.error)"
                  style="margin-bottom: 12px"
                />
                <a-descriptions :column="2" size="small" bordered>
                  <a-descriptions-item label="扫描器状态">
                    <a-tag :color="skillspectorAnalysis.available ? 'green' : 'default'">
                      {{ skillspectorAnalysis.available ? '可用' : '未安装' }}
                    </a-tag>
                  </a-descriptions-item>
                  <a-descriptions-item label="风险分">{{ skillspectorAnalysis.risk_score ?? '-' }}</a-descriptions-item>
                  <a-descriptions-item label="风险级别">
                    <a-tag :color="severityColor(skillspectorEffectiveSeverity)">
                      {{ severityDisplay(skillspectorEffectiveSeverity) }}
                    </a-tag>
                  </a-descriptions-item>
                  <a-descriptions-item v-if="skillspectorRawSeverity && skillspectorRawSeverity !== skillspectorEffectiveSeverity" label="原始风险">
                    {{ severityDisplay(skillspectorRawSeverity) }}
                  </a-descriptions-item>
                  <a-descriptions-item label="建议">{{ recommendationDisplay(skillspectorAnalysis.risk_recommendation) }}</a-descriptions-item>
                  <a-descriptions-item label="发现项">{{ skillspectorFindings.length }}</a-descriptions-item>
                  <a-descriptions-item v-if="skillspectorAnalysis.suppressed_findings_count" label="已过滤噪声">
                    {{ skillspectorAnalysis.suppressed_findings_count }}
                  </a-descriptions-item>
                </a-descriptions>
                <a-collapse v-if="skillspectorFindings.length" v-model:activeKey="skillspectorFindingsActiveKey" style="margin-top: 12px">
                  <a-collapse-panel key="skillspector-findings" :header="`深度扫描命中项（${skillspectorFindings.length}）`">
                    <a-list
                      :data-source="skillspectorFindings"
                      bordered
                      size="small"
                    >
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
                            </a-space>
                            <div v-if="item.message || item.explanation" style="margin-top: 6px">
                              {{ deepScanText(bilingualText(item.message || item.explanation)) }}
                            </div>
                            <div v-if="item.remediation" style="margin-top: 6px; color: #8c8c8c">
                              建议：{{ deepScanText(item.remediation) }}
                            </div>
                          </div>
                        </a-list-item>
                      </template>
                    </a-list>
                  </a-collapse-panel>
                </a-collapse>
              </template>
              <a-empty v-else description="本次扫描未启用深度扫描或没有报告。" />
            </a-card>
            <a-divider />
            <a-card id="sandbox-section" size="small" title="Sandbox 执行结果">
              <template v-if="sandboxAnalysis">
                <a-alert
                  style="margin-bottom: 12px"
                  type="info"
                  show-icon
                  message="当前实际执行环境"
                  :description="sandboxAnalysis.runtime === 'docker' ? `后端：docker，镜像：${sandboxAnalysis.image || 'agent-manager-sandbox-runtime:latest'}` : `后端：${sandboxAnalysis.runtime || '-'}，执行服务：${sandboxAnalysis.image || '-'}`"
                />
                <a-alert
                  :type="sandboxRiskAlertType"
                  show-icon
                  :message="`风险等级：${sandboxAnalysis.risk_level || 'LOW'} / 最高严重级别：${sandboxAnalysis.max_severity || 'SAFE'}`"
                  :description="sandboxAnalysis.summary || 'Sandbox 未发现明确风险信号。'"
                />
                <a-descriptions :column="2" size="small" bordered>
                  <a-descriptions-item label="风险等级">
                    <a-tag :color="riskColor(sandboxAnalysis.risk_level)">{{ sandboxAnalysis.risk_level || '-' }}</a-tag>
                  </a-descriptions-item>
                  <a-descriptions-item label="最高严重级别">
                    <a-tag :color="severityColor(sandboxAnalysis.max_severity)">{{ sandboxAnalysis.max_severity || '-' }}</a-tag>
                  </a-descriptions-item>
                  <a-descriptions-item label="是否执行">
                    {{ sandboxAnalysis.executed ? '是' : '否' }}
                  </a-descriptions-item>
                  <a-descriptions-item label="运行时">
                    {{ sandboxAnalysis.runtime || '-' }}
                  </a-descriptions-item>
                  <a-descriptions-item label="入口脚本">
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
                  <a-descriptions-item label="镜像">
                    {{ sandboxAnalysis.image || '-' }}
                  </a-descriptions-item>
                  <a-descriptions-item label="Probe 策略">
                    {{ sandboxAnalysis.probe_strategy || '-' }}
                  </a-descriptions-item>
                  <a-descriptions-item label="Probe 参数">
                    {{ Array.isArray(sandboxAnalysis.probe_args) && sandboxAnalysis.probe_args.length ? sandboxAnalysis.probe_args.join(' ') : '-' }}
                  </a-descriptions-item>
                  <a-descriptions-item label="退出码">
                    {{ sandboxAnalysis.exit_code ?? '-' }}
                  </a-descriptions-item>
                  <a-descriptions-item label="是否超时">
                    {{ sandboxAnalysis.timed_out ? '是' : '否' }}
                  </a-descriptions-item>
                  <a-descriptions-item label="耗时">
                    {{ sandboxAnalysis.duration_ms ?? '-' }} ms
                  </a-descriptions-item>
                  <a-descriptions-item label="网络尝试">
                    {{ sandboxAnalysis.network_attempts ?? 0 }}
                  </a-descriptions-item>
                </a-descriptions>
                <a-alert
                  v-if="sandboxAnalysis.recommendation"
                  style="margin-top: 12px"
                  type="warning"
                  show-icon
                  message="建议动作"
                  :description="sandboxAnalysis.recommendation"
                />
                <a-alert
                  v-if="sandboxAnalysis.reason"
                  style="margin-top: 12px"
                  type="info"
                  show-icon
                  message="Sandbox 说明"
                  :description="sandboxAnalysis.reason"
                />
                <a-list
                  v-if="sandboxSignals.length"
                  style="margin-top: 12px"
                  header="Sandbox 风险信号"
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
                        <div v-if="item.evidence" style="margin-top: 6px; color: #8c8c8c">
                          {{ item.evidence }}
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
                  <template #title>
                    Sandbox 执行明细
                  </template>
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
                      <a-tag :color="record.timed_out ? 'red' : 'green'">{{ record.timed_out ? '是' : '否' }}</a-tag>
                    </template>
                  </template>
                  <template #expandedRowRender="{ record }">
                    <a-descriptions :column="2" size="small" bordered>
                      <a-descriptions-item label="执行命令" :span="2">
                        <pre class="command-block">{{ formatSandboxCommand(record) }}</pre>
                      </a-descriptions-item>
                      <a-descriptions-item label="生成来源">{{ record.probe_generated_by || '-' }}</a-descriptions-item>
                      <a-descriptions-item label="运行时">{{ record.runtime || sandboxAnalysis.runtime || '-' }}</a-descriptions-item>
                      <a-descriptions-item label="耗时">{{ record.duration_ms ?? '-' }} ms</a-descriptions-item>
                      <a-descriptions-item label="网络尝试">{{ record.network_attempts ?? 0 }}</a-descriptions-item>
                    </a-descriptions>
                    <a-tabs size="small" style="margin-top: 12px">
                      <a-tab-pane key="stdout" tab="标准输出">
                        <a-textarea :value="record.stdout || '无输出'" :rows="8" readonly />
                      </a-tab-pane>
                      <a-tab-pane key="stderr" tab="标准错误">
                        <a-textarea :value="record.stderr || '无输出'" :rows="8" readonly />
                      </a-tab-pane>
                    </a-tabs>
                  </template>
                </a-table>
                <a-collapse style="margin-top: 12px">
                  <a-collapse-panel key="sandbox-output" header="查看 Sandbox 输出">
                    <a-tabs size="small">
                      <a-tab-pane key="stdout" tab="标准输出">
                        <a-textarea :value="sandboxAnalysis.stdout || '无输出'" :rows="8" readonly />
                      </a-tab-pane>
                      <a-tab-pane key="stderr" tab="标准错误">
                        <a-textarea :value="sandboxAnalysis.stderr || '无输出'" :rows="8" readonly />
                      </a-tab-pane>
                    </a-tabs>
                  </a-collapse-panel>
                </a-collapse>
              </template>
              <a-empty
                v-else
                description="当前没有可展示的 Sandbox 执行结果。若本次提交启用了 Sandbox，请刷新报告。"
              />
            </a-card>
          </a-skeleton>
        </a-tab-pane>

        <a-tab-pane key="llm" tab="LLM 分析">
          <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
            <template v-if="llmAnalysis">
              <a-card id="llm-section" size="small" title="LLM 深度分析">
                <a-descriptions :column="2" size="small" bordered style="margin-bottom: 12px">
                  <a-descriptions-item label="提供方">{{ llmAnalysis.provider || '-' }}</a-descriptions-item>
                  <a-descriptions-item label="模型">{{ llmAnalysis.model || '-' }}</a-descriptions-item>
                  <a-descriptions-item label="判定">
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
                    <h4 style="margin-bottom: 12px">攻击链分析</h4>
                    <AttackChainGraph :attack-chain="llmAnalysis.attack_chain" />
                  </div>
                </template>
              </a-card>
            </template>
            <a-empty v-else description="暂无 LLM 分析结果" />
          </a-skeleton>
        </a-tab-pane>

        <a-tab-pane key="governance-card" tab="Governance Card（治理卡片）">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button @click="fetchGovernanceCard" :loading="loadingGovernanceCard">刷新</a-button>
            <a-button type="primary" @click="handleRefreshGovernanceCard" :loading="loadingGovernanceCard">
              重新生成
            </a-button>
            <a-radio-group v-model:value="governanceCardViewMode" button-style="solid">
              <a-radio-button value="preview">预览</a-radio-button>
              <a-radio-button value="raw">原文</a-radio-button>
            </a-radio-group>
            <span style="color: #8c8c8c">
              {{ governanceCard?.generated_at ? `生成时间：${formatDateTime(governanceCard.generated_at)}` : '暂无生成时间' }}
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

        <a-tab-pane key="signature" tab="签名验证">
          <a-descriptions :column="1" size="small" bordered>
            <a-descriptions-item label="签名是否存在">{{ detail?.signature ? '是' : '否' }}</a-descriptions-item>
            <a-descriptions-item label="签名预览">{{ detail?.signature ? `${detail.signature.slice(0, 24)}...` : '-' }}</a-descriptions-item>
            <a-descriptions-item label="最近一次校验">{{ signatureResult ? (signatureResult.valid ? '通过' : '失败') : '未校验' }}</a-descriptions-item>
          </a-descriptions>
        </a-tab-pane>

        <a-tab-pane key="content" tab="技能内容">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button @click="fetchSkillContent" :loading="loadingContent">刷新 SKILL.md</a-button>
            <a-radio-group v-model:value="contentViewMode" button-style="solid">
              <a-radio-button value="preview">预览</a-radio-button>
              <a-radio-button value="raw">原文</a-radio-button>
            </a-radio-group>
          </a-space>

          <a-alert
            v-if="skillContent?.manifest_path"
            type="info"
            show-icon
            :message="skillContent.manifest_path"
            style="margin-bottom: 12px"
          />

          <template v-if="contentViewMode === 'preview'">
            <a-card
              v-if="skillFrontmatter"
              size="small"
              title="Manifest 元数据"
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

        <a-tab-pane key="files" tab="文件列表">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button @click="fetchSkillFiles">刷新文件列表</a-button>
            <span style="color: #8c8c8c">共 {{ skillFiles.length }} 个文件</span>
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

        <a-tab-pane key="audit" tab="审计记录">
          <a-table :data-source="auditRows" :columns="auditColumns" rowKey="event_id" :pagination="{ pageSize: 5 }">
            <template #bodyCell="{ column, record }">
              <span v-if="column.key === 'event_type'">{{ auditEventLabel(record.event_type) }}</span>
              <span v-else-if="column.key === 'actor'">{{ record.actor || '系统' }}</span>
              <span v-else-if="column.key === 'details'">{{ formatAuditDetails(record.details) }}</span>
            </template>
          </a-table>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <a-modal
      v-model:open="approveModalOpen"
      title="批准技能"
      ok-text="确认批准"
      cancel-text="取消"
      :confirm-loading="actionLoading"
      @ok="submitApprove"
    >
      <a-form layout="vertical">
        <a-alert
          v-if="admissionBlocked"
          type="warning"
          show-icon
          message="这是一次人工例外批准"
          description="该 Skill 的安全研判为低风险，但准入策略曾因工具/权限/许可证阻断。批准后会签名并进入可绑定状态，请在备注中说明例外依据。"
          style="margin-bottom: 12px"
        />
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item label="审批人">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item label="审批备注">
          <a-textarea v-model:value="approveNote" :rows="4" placeholder="可留空" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="rejectModalOpen"
      title="拒绝技能"
      ok-text="确认拒绝"
      cancel-text="取消"
      :confirm-loading="actionLoading"
      @ok="submitReject"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item label="审核人">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item label="拒绝原因" required>
          <a-textarea v-model:value="rejectReason" :rows="4" placeholder="请输入原因" />
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
        <a-button @click="refreshViewedFile" :loading="loadingFileViewer" :disabled="!viewingFilePath">刷新文件</a-button>
        <span style="color: #8c8c8c">{{ viewedFile?.absolute_path || viewingFilePath || '-' }}</span>
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
  getAudit,
  getSkillContent,
  getSkillDetail,
  getSkillFileContent,
  getSkillFiles,
  getSkillGovernanceCard,
  getSkillScanReport,
  refreshSkillGovernanceCard,
  rejectSkill,
  verifySkillSignature,
} from '../api'
import { formatDateTime } from '../utils/format'
import AttackChainGraph from '../components/AttackChainGraph.vue'

const route = useRoute()
const skillId = computed(() => route.params.skillId)
const activeTab = ref(route.query.tab || 'vetting')
const loading = ref(false)
const loadingScanReport = ref(false)
const loadingContent = ref(false)
const loadingGovernanceCard = ref(false)
const verifyingSignature = ref(false)
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

const auditColumns = [
  { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 180, customRender: ({ text }) => formatDateTime(text) },
  { title: '事件', dataIndex: 'event_type', key: 'event_type', width: 180 },
  { title: '操作人', dataIndex: 'actor', key: 'actor', width: 120 },
  { title: '详情', dataIndex: 'details', key: 'details' },
]

const auditEventLabels = {
  skill_submitted: '技能已提交',
  skill_processing_completed: '后台分析完成',
  skill_queued_for_review: '已进入人工审核',
  skill_vetted: '安全检测完成',
  skill_approved: '技能已批准',
  skill_rejected: '技能已拒绝',
  skill_deployed: '技能已部署',
  skill_retired: '技能已退役',
  skill_signature_verified: '签名校验通过',
  skill_tamper_detected: '检测到内容篡改',
  skill_load_allowed: '允许运行时加载',
  skill_load_blocked: '阻止运行时加载',
  tool_invoked: '工具已调用',
  tool_blocked: '工具调用被阻止',
}

const auditDetailLabels = {
  skill_path: '技能路径',
  status: '状态',
  risk_level: '风险等级',
  pre_llm_risk_level: 'LLM 分析前风险',
  max_severity: '最高严重级别',
  violations: '策略违规',
  verification_mode: '校验方式',
  reason: '原因',
  note: '备注',
}

const fileColumns = [
  { title: '路径', dataIndex: 'path', key: 'path' },
  { title: '大小', dataIndex: 'size_bytes', key: 'size_bytes', width: 140, customRender: ({ text }) => formatFileSize(text) },
  { title: '修改时间', dataIndex: 'modified_at', key: 'modified_at', width: 220, customRender: ({ text }) => formatDateTime(text) },
]

const sandboxProbeColumns = [
  { title: 'Probe', key: 'probe', width: 220 },
  { title: '入口', key: 'entrypoint', width: 260 },
  { title: '执行命令', key: 'command' },
  { title: '退出码', key: 'exit_code', width: 90 },
  { title: '超时', key: 'timeout', width: 80 },
  { title: '耗时', dataIndex: 'duration_ms', key: 'duration_ms', width: 100, customRender: ({ text }) => `${text ?? '-'} ms` },
]

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
    message.error(error.response?.data?.detail || '获取技能详情失败')
  } finally {
    loading.value = false
  }
}

const fetchScanReport = async () => {
  if (!detail.value) return
  loadingScanReport.value = true
  try {
    const data = await getSkillScanReport(detail.value.skill_id)
    scanReport.value = data.scan_report || {}
  } catch (error) {
    message.error(error.response?.data?.detail || '获取扫描报告失败')
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
    message.error(error.response?.data?.detail || '获取技能内容失败')
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
    message.error(error.response?.data?.detail || '获取文件列表失败')
  }
}

const fetchGovernanceCard = async () => {
  if (!detail.value) return
  loadingGovernanceCard.value = true
  try {
    governanceCard.value = await getSkillGovernanceCard(detail.value.skill_id)
  } catch (error) {
    message.error(error.response?.data?.detail || '获取治理卡片失败')
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
    message.success('治理卡片已刷新')
  } catch (error) {
    message.error(error.response?.data?.detail || '刷新治理卡片失败')
  } finally {
    loadingGovernanceCard.value = false
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
    message.error(error.response?.data?.detail || '获取文件内容失败')
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
      message.success('签名校验通过')
    } else {
      message.error(`签名校验失败：${signatureResultReason.value}`)
    }
  } catch (error) {
    message.error(error.response?.data?.detail || '签名校验失败')
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
    message.success('已批准')
    approveModalOpen.value = false
    fetchDetail()
  } catch (error) {
    message.error(error.response?.data?.detail || '批准失败')
  } finally {
    actionLoading.value = false
    actionType.value = ''
  }
}

const submitReject = async () => {
  if (!detail.value) return
  if (!rejectReason.value.trim()) {
    message.warning('请输入拒绝原因')
    return
  }
  actionLoading.value = true
  actionType.value = 'reject'
  try {
    await rejectSkill(detail.value.skill_id, { reviewer: currentUser(), reason: rejectReason.value.trim() })
    message.success('已拒绝')
    rejectModalOpen.value = false
    fetchDetail()
  } catch (error) {
    message.error(error.response?.data?.detail || '拒绝失败')
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
  if (!text) return '<p>暂无分析说明</p>'
  return marked.parse(text)
})
const behavioralAnalysis = computed(() => scanReport.value?.behavioral_analysis || null)
const behavioralFindings = computed(() => behavioralAnalysis.value?.findings || [])
const behavioralScannedFiles = computed(() => behavioralAnalysis.value?.scanned_files || [])
const localStaticAnalysis = computed(() => scanReport.value?.local_static_analysis || null)
const normalizeRuleFinding = (item) => ({
  ...item,
  title: item.title || item.rule_id || item.rule || '规则命中',
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
      source: '准入策略',
      color: 'red',
      target: 'policy',
      text: `工具声明不在白名单：${toolMatch[1]}。安全研判可以是安全，但该工具权限未被公司策略允许，因此准入被拒绝。`,
    }
  }
  return {
    code,
    source: '准入策略',
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
const canApproveSkill = computed(() => {
  if (detail.value?.status === 'VETTED') return true
  if (!admissionBlocked.value) return false
  return ['benign', 'suspicious'].includes(detail.value?.risk_level)
})
const admissionBlockedSummary = computed(() => {
  if (!admissionBlocked.value) return ''
  const risk = detail.value?.risk_level ? riskDisplay(detail.value.risk_level) : '未知'
  const reasons = policyBlockItems.value.map((item) => item.text).join('；')
  return `安全判定：${risk}。最终状态为已拒绝，是因为准入策略未通过：${reasons}`
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
      text: finalRisk === 'malicious' ? 'LLM 判定为恶意，详情见 LLM 分析。' : 'LLM 判定为可疑，详情见 LLM 分析。',
    })
  }

  if (!items.length && detail.value?.vetting?.policy_notes?.length) {
    items.push({
      source: '策略',
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
      source: '人工审核',
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
  if (!content) return '<p>暂无治理卡片</p>'
  return marked.parse(content)
})
const numberedLines = (text) => String(text || '').split('\n').map((line, index) => ({
  no: index + 1,
  text: line,
}))
const governanceCardLines = computed(() => numberedLines(governanceCard.value?.content || '暂无治理卡片'))
const sandboxAnalysis = computed(() => scanReport.value?.sandbox_analysis || null)
const sandboxSignals = computed(() => sandboxAnalysis.value?.signals || sandboxAnalysis.value?.suspicious_events || [])
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
    probe_description: sandboxAnalysis.value.reason || '代表性 Sandbox 执行结果',
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
  }]
})
const sandboxRiskAlertType = computed(() => {
  const risk = (sandboxAnalysis.value?.risk_level || '').toUpperCase()
  if (risk === 'EXTREME' || risk === 'HIGH') return 'error'
  if (risk === 'MEDIUM') return 'warning'
  return 'success'
})
const rationaleSource = (source) => {
  const text = String(source || '').toLowerCase()
  if (text.includes('sandbox')) return { label: 'Sandbox', color: 'orange', target: 'sandbox' }
  if (text.includes('skillspector')) return { label: '深度扫描', color: 'cyan', target: 'skillspector' }
  if (text.includes('llm')) return { label: 'LLM', color: 'purple', target: 'llm' }
  return { label: '规则', color: 'blue', target: 'rule' }
}
const deepScanText = (value) =>
  String(value || '')
    .replace(/SkillSpector/gi, '深度扫描')
    .replace(/skillspector/gi, '深度扫描')
    .replace(/\bCLI\b/g, '服务')
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
  const title = finding?.title || finding?.message || finding?.rule || finding?.rule_id || '命中风险规则'
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
  'No signature stored for this skill': '当前技能未存储签名。只有已批准并完成签名的技能才能验签。',
  'No skill path available for verification': '没有可用于验签的技能路径。',
  'signature valid': '签名有效，技能内容未发生变化。',
  'signature mismatch': '签名不匹配，技能内容可能已发生变化。',
}
const signatureVerifyDisabledReason = computed(() => (
  detail.value?.signature
    ? ''
    : '当前技能没有签名。被拒绝、待分析或待审核的技能不会生成签名。'
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
const viewerTitle = computed(() => (viewingFilePath.value ? `文件内容：${viewingFilePath.value}` : '文件内容'))
const skillContentHtml = computed(() => {
  const body = parsedSkillContent.value.body
  if (!body) return '<p>该 SKILL.md 只有 manifest，没有额外正文内容。</p>'
  return marked.parse(body)
})
const skillContentLines = computed(() => numberedLines(skillContent.value?.content || '点击“加载 SKILL.md”查看技能内容'))
const viewedFileLines = computed(() => numberedLines(viewedFile.value?.content || '暂无文件内容'))

const statusLabels = {
  PENDING: '分析中',
  VETTED: '待审核',
  APPROVED: '已批准',
  DEPLOYED: '已部署',
  REJECTED: '已拒绝',
  RETIRED: '已退役',
}

const severityLabels = {
  SAFE: '安全',
  INFO: '提示',
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
  CRITICAL: '严重',
  EXTREME: '极高',
}

const recommendationLabels = {
  SAFE: '可安装',
  CAUTION: '谨慎安装',
  REVIEW: '需要审核',
  DO_NOT_INSTALL: '不要安装',
}

const termTranslations = {
  'LOW_ANALYZABILITY': '可分析性不足',
  'Moderate analyzability score': '中等可分析性评分',
  'External Transmission': '外部传输',
  'Data Exfiltration': '数据外传',
  'Prompt Injection': '提示词注入',
  'Instruction Override': '覆盖上级指令',
  'System Prompt Leakage': '系统提示词泄露',
  'System Prompt Disclosure': '披露系统提示词',
  'Tool Poisoning': '工具投毒',
  'Hidden Instructions': '隐藏指令',
  'Supply Chain': '供应链风险',
  'External Script Fetching': '下载外部脚本',
  'Obfuscated Code': '混淆代码',
  'Wildcard Permission': '通配权限',
  'Network Access': '网络访问',
  'File System Access': '文件系统访问',
  'Sensitive File Access': '敏感文件访问',
  'Command Execution': '命令执行',
  'Code Execution': '代码执行',
  'Dynamic Code Execution': '动态代码执行',
  'Credential Access': '凭据访问',
  'Privilege Escalation': '权限提升',
  Persistence: '持久化',
  'Encoded Payload': '编码载荷',
}

const sentenceTranslations = [
  {
    pattern: /^Only\s+(\d+)%\s+of skill content could be analyzed\.\s+(\d+)\s+of\s+(\d+)\s+files?\s+(?:is|are)\s+opaque to the scanner\.\s+Some content could not be verified as safe\.?$/i,
    render: ([, percent, opaque, total]) =>
      `仅有 ${percent}% 的 Skill 内容可被分析。${total} 个文件中有 ${opaque} 个对扫描器不可解析，因此部分内容无法确认安全。`,
  },
  {
    pattern: /^Code or instructions reference external transmission\.\s*文件:\s*(.+)$/i,
    render: ([, file]) => `代码或指令引用了可能向外部发送数据的调用。文件: ${file}`,
  },
  {
    pattern: /^Code accesses environment variables that may contain secrets\.\s*文件:\s*(.+)$/i,
    render: ([, file]) => `代码读取环境变量，可能接触密钥或敏感配置。文件: ${file}`,
  },
  {
    pattern: /^Skill content asks the agent to ignore higher-priority instructions\.\s*文件:\s*(.+)$/i,
    render: ([, file]) => `Skill 内容要求忽略上级或系统指令。文件: ${file}`,
  },
]

const statusTitle = (value) => statusLabels[value] || '未知'
const statusDisplay = (value) => (value ? `${value}（${statusTitle(value)}）` : '-')
const severityDisplay = (value) => {
  const text = String(value || '').toUpperCase()
  return text ? `${text}（${severityLabels[text] || '未知'}）` : '-'
}
const recommendationDisplay = (value) => {
  const text = String(value || '').toUpperCase()
  return text ? `${text}（${recommendationLabels[text] || '未知'}）` : '-'
}
const riskDisplay = (value) => {
  const text = String(value || 'unknown')
  const zh = {
    benign: '安全',
    suspicious: '可疑',
    malicious: '恶意',
    unknown: '未知',
  }[text.toLowerCase()] || '未知'
  return `${text}（${zh}）`
}
const bilingualText = (value) => {
  const text = String(value || '').trim()
  if (!text) return '-'
  if (termTranslations[text]) return `${text}（${termTranslations[text]}）`
  for (const item of sentenceTranslations) {
    const match = text.match(item.pattern)
    if (match) return item.render(match)
  }
  return text
}
const findingTitle = (item) => bilingualText(item?.title || item?.pattern || item?.message || '-')
const originLabel = (value) => ({
  local: '本地',
  github: 'GitHub',
  clawhub: 'ClawHub',
  internal: '内部',
  unknown: '未知',
}[value] || value || '-')
const auditEventLabel = (value) => auditEventLabels[value] || value || '-'

const formatAuditValue = (key, value) => {
  if (value === null || value === undefined || value === '') return '-'
  if (key === 'status') return statusDisplay(String(value))
  if (key === 'risk_level' || key === 'pre_llm_risk_level') {
    return riskDisplay(value)
  }
  if (key === 'max_severity') {
    return severityLabels[String(value).toUpperCase()] || String(value)
  }
  if (Array.isArray(value)) return value.length ? value.join('、') : '无'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const formatAuditDetails = (details, limit = 6) => {
  if (!details || typeof details !== 'object') return '-'
  const entries = Object.entries(details).slice(0, limit)
  if (!entries.length) return '-'
  return entries
    .map(([key, value]) => `${auditDetailLabels[key] || key}：${formatAuditValue(key, value)}`)
    .join('；')
}

const statusColor = (value) =>
  ({
    PENDING: 'gold',
    VETTED: 'orange',
    APPROVED: 'green',
    DEPLOYED: 'blue',
    REJECTED: 'red',
    RETIRED: 'default',
  }[value] || 'default')

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
  () => [skillspectorFindings.value.length, hasHighRiskSkillspectorFinding.value],
  () => {
    skillspectorFindingsActiveKey.value = hasHighRiskSkillspectorFinding.value ? ['skillspector-findings'] : []
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
