<template>
  <div>
    <a-page-header :title="detail?.name ? `技能详情：${detail.name}` : `技能详情：${skillId}`" sub-title="查看技能详情、审核、部署与审计记录" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="8">
        <a-card title="基础信息">
          <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
            <a-descriptions :column="1" size="small">
              <a-descriptions-item label="Skill ID">{{ detail?.skill_id || skillId }}</a-descriptions-item>
              <a-descriptions-item label="名称">{{ detail?.name || '-' }}</a-descriptions-item>
              <a-descriptions-item label="状态">
                <a-tag :color="statusColor(detail?.status)">{{ detail?.status || '-' }}</a-tag>
              </a-descriptions-item>
              <a-descriptions-item label="安全判定">
                <a-tag v-if="detail?.status === 'PENDING'" color="default" style="font-size: 16px; padding: 4px 16px;">
                  -
                </a-tag>
                <a-tag v-else-if="detail?.risk_level === 'malicious'" color="red" style="font-size: 16px; padding: 4px 16px;">
                  恶意
                </a-tag>
                <a-tag v-else-if="detail?.risk_level === 'suspicious'" color="orange" style="font-size: 16px; padding: 4px 16px;">
                  可疑
                </a-tag>
                <a-tag v-else color="green" style="font-size: 16px; padding: 4px 16px;">
                  安全
                </a-tag>
              </a-descriptions-item>
              <a-descriptions-item label="路径">{{ detail?.skill_path || '-' }}</a-descriptions-item>
              <a-descriptions-item label="作者">{{ detail?.source?.author || '-' }}</a-descriptions-item>
              <a-descriptions-item label="来源">{{ detail?.source?.origin || '-' }}</a-descriptions-item>
              <a-descriptions-item label="允许工具">{{ detail?.allowed_tools?.join(', ') || 'none' }}</a-descriptions-item>
              <a-descriptions-item label="声明工具有效">{{ detail?.declared_tools_valid ? '是' : '否' }}</a-descriptions-item>
              <a-descriptions-item label="Sandbox 已触发">
                {{ detail?.vetting?.sandbox_triggered ? '是' : '否' }}
              </a-descriptions-item>
              <a-descriptions-item label="Sandbox 由策略强制">
                {{ detail?.vetting?.sandbox_required_by_policy ? '是' : '否' }}
              </a-descriptions-item>
              <a-descriptions-item label="Sandbox 后端">
                {{ detail?.vetting?.sandbox_runtime || '-' }}
              </a-descriptions-item>
              <a-descriptions-item label="Sandbox 镜像">
                {{ sandboxDisplayImage }}
              </a-descriptions-item>
              <a-descriptions-item label="扫描复用">
                <a-space wrap>
                  <a-tag :color="detail?.scan_reused ? 'green' : 'default'">
                    {{ detail?.scan_reused ? '已复用' : '未复用' }}
                  </a-tag>
                  <span v-if="detail?.reused_from_skill_id">来源：{{ detail.reused_from_skill_id }}</span>
                </a-space>
              </a-descriptions-item>
            </a-descriptions>
          </a-skeleton>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="16">
        <a-card title="生命周期与操作">
          <a-space style="margin-bottom: 16px" wrap>
            <a-button @click="fetchDetail" :loading="loading">刷新</a-button>
            <a-button @click="handleVerifySignature" :loading="verifyingSignature">验签</a-button>
            <a-button v-if="detail?.status === 'VETTED'" type="primary" @click="openApproveModal">批准</a-button>
            <a-button v-if="detail?.status === 'VETTED'" danger @click="openRejectModal">拒绝</a-button>
            <a-button v-if="detail?.status === 'APPROVED'" type="primary" :loading="actionLoading && actionType === 'deploy'" @click="handleDeploy">部署</a-button>
            <a-button v-if="detail?.status === 'APPROVED' || detail?.status === 'DEPLOYED'" danger @click="openRetireModal">退役</a-button>
          </a-space>

          <a-steps :current="stepIndex" size="small">
            <a-step title="提交" :description="formatDateTime(detail?.submitted_at)" />
            <a-step title="审核" :description="detail?.approved_by || '待审核'" />
            <a-step title="批准" :description="formatDateTime(detail?.approved_at)" />
            <a-step title="部署" :description="formatDateTime(detail?.deployed_at)" />
          </a-steps>

          <a-alert
            v-if="signatureResult"
            style="margin-top: 16px"
            :type="signatureResult.valid ? 'success' : 'error'"
            show-icon
            :message="signatureResult.valid ? '签名校验通过' : '签名校验失败'"
            :description="signatureResult.reason"
          />
        </a-card>
      </a-col>
    </a-row>

    <a-card title="Vetting / 签名 / 审计" style="margin-top: 16px">
      <a-tabs default-active-key="llm">
        <a-tab-pane key="llm" tab="LLM 分析">
          <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
            <template v-if="llmAnalysis">
              <a-card size="small" title="LLM 深度分析">
                <a-descriptions :column="2" size="small" bordered style="margin-bottom: 12px">
                  <a-descriptions-item label="提供方">{{ llmAnalysis.provider || '-' }}</a-descriptions-item>
                  <a-descriptions-item label="模型">{{ llmAnalysis.model || '-' }}</a-descriptions-item>
                  <a-descriptions-item label="判定">
                    <a-tag v-if="llmAnalysis.risk_level === 'malicious'" color="red" style="font-size: 15px; padding: 2px 12px;">
                      恶意
                    </a-tag>
                    <a-tag v-else-if="llmAnalysis.risk_level === 'suspicious'" color="orange" style="font-size: 15px; padding: 2px 12px;">
                      可疑
                    </a-tag>
                    <a-tag v-else color="green" style="font-size: 15px; padding: 2px 12px;">
                      安全
                    </a-tag>
                  </a-descriptions-item>
                </a-descriptions>

                <!-- 分析说明 -->
                <div v-if="llmAnalysis.report" class="llm-explanation" v-html="llmExplanationHtml" />

                <!-- 攻击链图 -->
                <template v-if="llmAnalysis.risk_level === 'malicious' && llmAnalysis.attack_chain?.length">
                  <a-divider />
                  <div>
                    <h4 style="margin-bottom: 12px;">攻击链分析</h4>
                    <AttackChainGraph :attack-chain="llmAnalysis.attack_chain" />
                  </div>
                </template>
              </a-card>
            </template>
            <template v-else>
              <a-empty description="暂无 LLM 分析结果" />
            </template>
          </a-skeleton>
        </a-tab-pane>
        <a-tab-pane key="vetting" tab="Vetting">
          <a-skeleton :loading="loading" active :paragraph="{ rows: 8 }">
            <a-space style="margin-bottom: 12px" wrap>
              <a-button type="primary" class="refresh-report-button" @click="fetchScanReport" :loading="loadingScanReport">
                刷新报告
              </a-button>
              <span style="color: #8c8c8c">原始扫描 JSON 默认折叠，按需展开查看</span>
            </a-space>
            <a-descriptions :column="2" size="small" bordered>
              <a-descriptions-item label="安全判定">
                <a-tag v-if="detail?.status === 'PENDING'" color="default">
                  -
                </a-tag>
                <a-tag v-else-if="detail?.risk_level === 'malicious'" color="red">
                  恶意
                </a-tag>
                <a-tag v-else-if="detail?.risk_level === 'suspicious'" color="orange">
                  可疑
                </a-tag>
                <a-tag v-else color="green">
                  安全
                </a-tag>
              </a-descriptions-item>
              <a-descriptions-item label="发现项">{{ detail?.vetting?.findings_count ?? 0 }}</a-descriptions-item>
              <a-descriptions-item label="规则分析器">{{ detail?.vetting?.analyzers_used?.join(', ') || '-' }}</a-descriptions-item>
              <a-descriptions-item label="耗时">{{ detail?.vetting?.scan_duration_seconds ?? 0 }}s</a-descriptions-item>
              <a-descriptions-item label="扫描缓存">{{ detail?.scan_reused ? '复用历史结果' : '本次执行扫描' }}</a-descriptions-item>
              <a-descriptions-item label="缓存 Key">{{ detail?.scan_cache_key || '-' }}</a-descriptions-item>
            </a-descriptions>
            <a-divider />
            <a-list
              header="策略说明"
              :data-source="detail?.vetting?.policy_notes?.length ? detail.vetting.policy_notes : ['No policy notes']"
              bordered
              size="small"
            >
              <template #renderItem="{ item }">
                <a-list-item>{{ item }}</a-list-item>
              </template>
            </a-list>
            <a-divider />
            <a-card size="small" title="规则分析结果">
              <template v-if="behavioralAnalysis">
                <a-descriptions :column="2" size="small" bordered>
                  <a-descriptions-item label="扫描文件数">
                    {{ behavioralAnalysis.scanned_file_count ?? behavioralScannedFiles.length }}
                  </a-descriptions-item>
                  <a-descriptions-item label="命中规则数">
                    {{ behavioralFindings.length }}
                  </a-descriptions-item>
                  <a-descriptions-item label="最高严重级别">
                    <a-tag :color="severityColor(behavioralAnalysis.max_severity)">
                      {{ behavioralAnalysis.max_severity || '-' }}
                    </a-tag>
                  </a-descriptions-item>
                  <a-descriptions-item label="规则分析器">
                    <a-tag color="blue">behavioral:local</a-tag>
                  </a-descriptions-item>
                </a-descriptions>
                <a-list
                  style="margin-top: 12px"
                  header="规则命中项"
                  :data-source="behavioralFindings"
                  bordered
                  size="small"
                >
                  <template #renderItem="{ item }">
                    <a-list-item>
                      <div style="width: 100%">
                        <a-space wrap>
                          <a-tag :color="severityColor(item.severity)">{{ item.severity }}</a-tag>
                          <strong>{{ item.title }}</strong>
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
                        <div style="margin-top: 6px">{{ item.message }}</div>
                      </div>
                    </a-list-item>
                  </template>
                </a-list>
                <a-collapse v-if="behavioralScannedFiles.length" style="margin-top: 12px">
                  <a-collapse-panel key="files" header="查看已扫描文件">
                    <a-list :data-source="behavioralScannedFiles" bordered size="small">
                      <template #renderItem="{ item }">
                        <a-list-item>
                          <a-button type="link" style="padding: 0" @click="openFileViewer(item)">{{ item }}</a-button>
                        </a-list-item>
                      </template>
                    </a-list>
                  </a-collapse-panel>
                </a-collapse>
                <a-empty
                  v-else
                  style="margin-top: 12px"
                  description="本次规则分析没有记录到已扫描文件列表。"
                />
              </template>
              <a-empty
                v-else
                description="当前没有可展示的规则分析结果。若本次提交启用了规则分析，但这里仍为空，请刷新报告。"
              />
            </a-card>
            <a-divider />
            <a-card size="small" title="Sandbox 执行结果">
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
                          <a-tag color="default">{{ item.category }}</a-tag>
                          <strong>{{ item.message }}</strong>
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
                      <a-tab-pane key="stdout" tab="stdout">
                        <a-textarea :value="record.stdout || '无输出'" :rows="8" readonly />
                      </a-tab-pane>
                      <a-tab-pane key="stderr" tab="stderr">
                        <a-textarea :value="record.stderr || '无输出'" :rows="8" readonly />
                      </a-tab-pane>
                    </a-tabs>
                  </template>
                </a-table>
                <a-collapse style="margin-top: 12px">
                  <a-collapse-panel key="sandbox-output" header="查看 Sandbox 输出">
                    <a-tabs size="small">
                      <a-tab-pane key="stdout" tab="stdout">
                        <a-textarea :value="sandboxAnalysis.stdout || '无输出'" :rows="8" readonly />
                      </a-tab-pane>
                      <a-tab-pane key="stderr" tab="stderr">
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
            <a-divider />
            <a-collapse>
              <a-collapse-panel key="raw-report" header="查看原始报告 JSON">
                <a-textarea :value="scanReportText" :rows="12" readonly />
              </a-collapse-panel>
            </a-collapse>
          </a-skeleton>
        </a-tab-pane>

        <a-tab-pane key="signature" tab="Signature">
          <a-descriptions :column="1" size="small" bordered>
            <a-descriptions-item label="签名是否存在">{{ detail?.signature ? '是' : '否' }}</a-descriptions-item>
            <a-descriptions-item label="签名预览">{{ detail?.signature ? `${detail.signature.slice(0, 24)}...` : '-' }}</a-descriptions-item>
            <a-descriptions-item label="最近一次校验">{{ signatureResult ? (signatureResult.valid ? '通过' : '失败') : '未校验' }}</a-descriptions-item>
          </a-descriptions>
        </a-tab-pane>

        <a-tab-pane key="content" tab="Skill 内容">
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
              title="Manifest Frontmatter"
              style="margin-bottom: 12px"
            >
              <pre class="frontmatter-box">{{ skillFrontmatter }}</pre>
            </a-card>
            <div class="markdown-body" v-html="skillContentHtml" />
          </template>
          <a-textarea v-else :value="skillContent?.content || '点击“加载 SKILL.md”查看技能内容'" :rows="18" readonly />
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

        <a-tab-pane key="audit" tab="Audit">
          <a-table :data-source="auditRows" :columns="auditColumns" rowKey="event_id" :pagination="{ pageSize: 5 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'details'">
                <span>{{ formatDetails(record.details) }}</span>
              </template>
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

    <a-modal
      v-model:open="retireModalOpen"
      title="退役技能"
      ok-text="确认退役"
      cancel-text="取消"
      :confirm-loading="actionLoading"
      @ok="submitRetire"
    >
      <a-form layout="vertical">
        <a-form-item label="Skill">
          <a-input :value="detail?.name || ''" disabled />
        </a-form-item>
        <a-form-item label="执行人">
          <a-input :value="currentUser()" disabled />
        </a-form-item>
        <a-form-item label="退役原因" required>
          <a-textarea v-model:value="retireReason" :rows="4" placeholder="请输入退役原因" />
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
      <a-textarea :value="viewedFile?.content || '暂无文件内容'" :rows="28" readonly />
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { marked } from 'marked'

import {
  approveSkill,
  deploySkill,
  getAudit,
  getSkillContent,
  getSkillDetail,
  getSkillFileContent,
  getSkillFiles,
  getSkillScanReport,
  rejectSkill,
  retireSkill,
  verifySkillSignature,
} from '../api'
import { formatDateTime, formatDetails } from '../utils/format'
import AttackChainGraph from '../components/AttackChainGraph.vue'

const route = useRoute()
const skillId = computed(() => route.params.skillId)
const loading = ref(false)
const loadingScanReport = ref(false)
const loadingContent = ref(false)
const verifyingSignature = ref(false)
const actionLoading = ref(false)
const actionType = ref('')
const detail = ref(null)
const auditRows = ref([])
const scanReport = ref(null)
const skillContent = ref(null)
const skillFiles = ref([])
const signatureResult = ref(null)
const fileViewerOpen = ref(false)
const loadingFileViewer = ref(false)
const viewingFilePath = ref('')
const viewedFile = ref(null)
const contentViewMode = ref('preview')
const approveModalOpen = ref(false)
const rejectModalOpen = ref(false)
const retireModalOpen = ref(false)
const approveNote = ref('')
const rejectReason = ref('')
const retireReason = ref('')

const auditColumns = [
  { title: 'Time', dataIndex: 'timestamp', key: 'timestamp', width: 220, customRender: ({ text }) => formatDateTime(text) },
  { title: 'Event', dataIndex: 'event_type', key: 'event_type', width: 180 },
  { title: 'Actor', dataIndex: 'actor', key: 'actor', width: 140 },
  { title: 'Details', dataIndex: 'details', key: 'details' },
]

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
    const [auditResult, reportResult, contentResult, filesResult] = await Promise.allSettled([
      getAudit({ skill_id: data.skill_id, since_hours: 720, limit: 50 }),
      getSkillScanReport(data.skill_id),
      getSkillContent(data.skill_id),
      getSkillFiles(data.skill_id),
    ])
    auditRows.value = auditResult.status === 'fulfilled' && Array.isArray(auditResult.value)
      ? auditResult.value
      : []
    scanReport.value = reportResult.status === 'fulfilled'
      ? (reportResult.value?.scan_report || null)
      : null
    skillContent.value = contentResult.status === 'fulfilled' ? (contentResult.value || null) : null
    skillFiles.value = filesResult.status === 'fulfilled' ? (filesResult.value?.files || []) : []
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
  verifyingSignature.value = true
  try {
    signatureResult.value = await verifySkillSignature(detail.value.skill_id)
    message.success(signatureResult.value.valid ? '签名校验通过' : '签名校验失败')
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

const openRetireModal = () => {
  retireReason.value = ''
  retireModalOpen.value = true
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

const handleDeploy = async () => {
  if (!detail.value) return
  actionLoading.value = true
  actionType.value = 'deploy'
  try {
    await deploySkill(detail.value.skill_id)
    message.success('已部署')
    fetchDetail()
  } catch (error) {
    message.error(error.response?.data?.detail || '部署失败')
  } finally {
    actionLoading.value = false
    actionType.value = ''
  }
}

const submitRetire = async () => {
  if (!detail.value) return
  if (!retireReason.value.trim()) {
    message.warning('请输入退役原因')
    return
  }
  actionLoading.value = true
  actionType.value = 'retire'
  try {
    await retireSkill(detail.value.skill_id, { actor: currentUser(), reason: retireReason.value.trim() })
    message.success('已退役')
    retireModalOpen.value = false
    fetchDetail()
  } catch (error) {
    message.error(error.response?.data?.detail || '退役失败')
  } finally {
    actionLoading.value = false
    actionType.value = ''
  }
}

const scanReportText = computed(() =>
  scanReport.value ? JSON.stringify(scanReport.value, null, 2) : '暂无扫描报告',
)

const stepIndex = computed(() => {
  if (!detail.value) return 0
  const status = detail.value.status
  if (status === 'DEPLOYED' && detail.value.deployed_at) return 3
  if (status === 'APPROVED' && detail.value.approved_at) return 2
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
const sandboxDisplayImage = computed(() => {
  if (sandboxAnalysis.value?.image) return sandboxAnalysis.value.image
  if (detail.value?.vetting?.sandbox_runtime === 'docker') return 'agent-manager-sandbox-runtime:latest'
  return '-'
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
</style>
