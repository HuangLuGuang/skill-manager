<template>
  <div>
    <a-page-header title="策略配置" sub-title="维护公司策略、允许工具和风险阈值" />

    <a-form layout="vertical" :model="formState" @finish="handleSaveAll">
      <a-alert
        v-if="conflictingRiskLevels.length"
        style="margin-top: 12px"
        type="error"
        show-icon
        message="策略存在冲突"
        :description="`这些风险同时配置了人工审核和自动拒绝：${conflictingRiskLevels.join('、')}。实际会自动拒绝，不会进入审核队列。`"
      />

      <a-tabs v-model:activeKey="activeTab" style="margin-top: 16px">
        <a-tab-pane key="decision" tab="审批决策">
          <section class="policy-section">
            <div class="section-title">判定顺序</div>
            <a-table
              size="small"
              row-key="step"
              :columns="decisionColumns"
              :data-source="decisionRows"
              :pagination="false"
            />
          </section>

          <a-row :gutter="16">
            <a-col :xs="24" :lg="12">
              <a-form-item label="判定模式（judgement_mode）">
                <a-select v-model:value="formState.judgement_mode">
                  <a-select-option v-for="item in judgementModeOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">{{ currentJudgementModeDescription }}</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item label="自动批准最大风险（auto_approve_max_risk）">
                <a-select v-model:value="formState.auto_approve_max_risk">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">低于或等于该风险的 skill 会自动批准为可信版本；生产环境通常只建议 benign。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item label="需要人工审核（require_human_review）">
                <a-select v-model:value="formState.require_human_review" mode="multiple" placeholder="进入审核队列的风险">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">命中后状态变为 VETTED，并出现在审核队列。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item label="自动拒绝风险（auto_reject_risk）">
                <a-select v-model:value="formState.auto_reject_risk" mode="multiple" placeholder="直接拒绝的风险">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">命中后状态直接变为 REJECTED，不进入审核队列。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item label="强制 Sandbox 风险等级">
                <a-select v-model:value="formState.require_sandbox_for_risk" mode="multiple" placeholder="必须执行 Sandbox 的风险">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">命中这些风险时，即使提交时没勾选 Sandbox，后台也会尝试执行 Sandbox probe。</div>
              </a-form-item>
            </a-col>
          </a-row>

          <section class="policy-section">
            <div class="section-title">风险项目归类</div>
            <a-row :gutter="[16, 16]">
              <a-col v-for="group in riskClassificationGroups" :key="group.key" :xs="24" :lg="8">
                <div class="risk-class-card">
                  <div class="risk-class-header">
                    <span>{{ group.label }}</span>
                    <a-tag :color="group.color">{{ group.tag }}</a-tag>
                  </div>
                  <div class="risk-class-description">{{ group.description }}</div>
                  <a-select
                    :value="formState.risk_classification_groups[group.key]"
                    class="risk-class-select"
                    mode="multiple"
                    option-label-prop="label"
                    placeholder="选择风险项"
                    @change="value => handleRiskGroupChange(group.key, value)"
                  >
                    <template #tagRender="{ value }">
                      <a-tag class="risk-class-tag">{{ riskItemLabel(value) }}</a-tag>
                    </template>
                    <a-select-option v-for="item in riskItems" :key="item.key" :value="item.key" :label="item.label">
                      <div class="risk-option">
                        <div class="risk-option-title">{{ item.label }}</div>
                        <div class="risk-option-description">{{ item.description }}</div>
                      </div>
                    </a-select-option>
                  </a-select>
                </div>
              </a-col>
            </a-row>
          </section>
        </a-tab-pane>

        <a-tab-pane key="admission" tab="准入规则">
          <section class="policy-section">
            <div class="section-title">工具权限</div>
            <a-row :gutter="16">
              <a-col :xs="24" :lg="12">
                <a-form-item label="允许声明工具上限">
                  <a-input-number v-model:value="formState.max_allowed_tools" :min="1" :max="100" style="width: 100%" />
                  <div class="field-hint">限制 SKILL.md allowed-tools 数量，防止 skill 声明过宽权限面。</div>
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item label="禁止权限/工具">
              <a-select v-model:value="formState.blocked_permissions" mode="tags" placeholder="例如 read_credentials、write_memory" />
              <div class="field-hint">命中这里的工具或权限会作为阻断项，优先 REJECTED。</div>
            </a-form-item>

            <a-form-item label="允许工具白名单">
              <a-select v-model:value="formState.allowed_tools_allowlist" mode="tags" placeholder="允许 skill 声明的工具列表" />
              <div class="field-hint">不在白名单里的 allowed-tools 会记录策略违规；低风险策略拒绝可由管理员人工例外批准。</div>
            </a-form-item>
          </section>

          <section class="policy-section">
            <div class="section-title">作者与 License</div>
            <a-row :gutter="16">
              <a-col :xs="24" :lg="12">
                <a-form-item label="必须声明 License">
                  <a-switch v-model:checked="formState.require_license" />
                  <div class="field-hint">开启后，缺少 license 字段会记录策略违规。</div>
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item label="可信作者">
              <a-select v-model:value="formState.trusted_authors" mode="tags" placeholder="可信作者，可为空" />
              <div class="field-hint">预留字段；当前主要用于展示和后续策略扩展。</div>
            </a-form-item>

            <a-form-item label="允许 License">
              <a-select v-model:value="formState.accepted_licenses" mode="tags" placeholder="MIT、Apache-2.0、internal 等" />
              <div class="field-hint">当“必须声明 License”开启时，用于判断声明的 license 是否可接受。</div>
            </a-form-item>
          </section>

        </a-tab-pane>

        <a-tab-pane key="llm" tab="LLM 配置">
          <a-card title="LLM 分析配置" size="small">
            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item label="启用 LLM 分析">
                  <a-switch
                    v-model:checked="llmForm.enabled"
                    checked-children="启用"
                    un-checked-children="关闭"
                  />
                  <div class="field-hint">这里控制提交扫描时是否允许使用 LLM 分析。</div>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="16">
                <a-form-item label="模型">
                  <a-select
                    v-model:value="llmForm.model"
                    show-search
                    allow-clear
                    placeholder="选择模型网关中的模型"
                    :options="llmModelOptions"
                  />
                  <div class="field-hint">选项来自模型网关的模型列表；供应商地址和上游 API Key 在模型网关中维护。</div>
                </a-form-item>
              </a-col>
            </a-row>

            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item label="超时时间（秒）">
                  <a-input-number v-model:value="llmForm.timeout_seconds" :min="5" :max="180" style="width: 100%" />
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="分析文件数上限">
                  <a-input-number v-model:value="llmForm.max_files" :min="1" :max="20" style="width: 100%" />
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="SKILL.md 截断字符数">
                  <a-input-number v-model:value="llmForm.max_manifest_chars" :min="2000" :max="50000" :step="1000" style="width: 100%" />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item label="单文件截断字符数">
              <a-input-number v-model:value="llmForm.max_file_chars" :min="500" :max="20000" :step="500" style="width: 100%" />
            </a-form-item>
          </a-card>
        </a-tab-pane>

        <a-tab-pane key="sandbox" tab="Sandbox 配置">
          <a-card title="Sandbox 运行配置" size="small">
            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item label="启用 Sandbox">
                  <a-switch
                    v-model:checked="sandboxForm.enabled"
                    checked-children="启用"
                    un-checked-children="关闭"
                  />
                  <div class="field-hint">风险等级强制执行仍由审批决策页控制，修改后通过底部按钮统一保存。</div>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="后端类型">
                  <a-select v-model:value="sandboxForm.runtime">
                    <a-select-option value="remote">remote（推荐）</a-select-option>
                    <a-select-option value="docker">docker</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="超时时间（秒）">
                  <a-input-number v-model:value="sandboxForm.timeout_seconds" :min="1" :max="300" style="width: 100%" />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item v-if="sandboxForm.runtime === 'docker'" label="镜像">
              <a-select
                v-model:value="sandboxForm.image"
                show-search
                placeholder="选择本机 sandbox 镜像"
                :options="sandboxImageOptions"
                :loading="loading"
              />
              <div class="field-hint">只显示本机 Docker 镜像名包含 sandbox 的镜像。</div>
            </a-form-item>

            <template v-else>
              <a-form-item label="远程 Sandbox URL">
                <a-input-group compact>
                  <a-input v-model:value="sandboxForm.remote_url" style="width: calc(100% - 238px)" placeholder="http://sandbox:8194" />
                  <a-button html-type="button" @click="useDefaultSandboxUrl">使用默认远程地址</a-button>
                  <a-button html-type="button" :loading="testingSandbox" @click="handleTestSandboxConnection">测试连接</a-button>
                </a-input-group>
                <div class="field-hint">默认推荐 http://sandbox:8194；可以直接编辑为客户环境中的远程 Sandbox 地址。配置文件：{{ sandboxConfig.config_path || '-' }}</div>
              </a-form-item>

              <a-alert
                v-if="sandboxTestResult"
                class="sandbox-test-result"
                show-icon
                :type="sandboxTestResult.available ? 'success' : 'error'"
                :message="sandboxTestResult.available ? 'Sandbox 连接可用' : 'Sandbox 连接不可用'"
                :description="sandboxTestDescription"
              />

              <a-collapse ghost size="small" class="sandbox-auth-collapse">
                <a-collapse-panel key="auth" header="远程访问凭证（可选）">
                  <a-form-item label="服务 Token">
                    <a-input-password
                      v-model:value="sandboxForm.remote_api_key"
                      placeholder="仅在远程 Sandbox 服务要求鉴权时填写"
                      autocomplete="new-password"
                    />
                    <div class="field-hint">
                      这是 Sandbox 服务自身的访问 Token，不是模型网关凭据；本地演示或未开启鉴权的远程服务可留空。当前状态：{{ sandboxConfig.remote_api_key_configured ? (sandboxConfig.remote_api_key_masked || '已配置') : '未配置' }}
                    </div>
                  </a-form-item>

                  <a-form-item>
                    <a-checkbox v-model:checked="sandboxForm.clear_remote_api_key">清除当前 Sandbox 服务 Token</a-checkbox>
                  </a-form-item>
                </a-collapse-panel>
              </a-collapse>
            </template>

            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item label="网络模式">
                  <a-select v-model:value="sandboxForm.network_mode">
                    <a-select-option value="none">none</a-select-option>
                    <a-select-option value="bridge">bridge</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="内存限制">
                  <a-input v-model:value="sandboxForm.memory_limit" placeholder="256m" />
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="CPU 限制">
                  <a-input v-model:value="sandboxForm.cpu_limit" placeholder="1.0" />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item label="进程数限制">
              <a-input-number v-model:value="sandboxForm.pids_limit" :min="1" :max="1024" style="width: 100%" />
            </a-form-item>

            <a-form-item>
              <a-checkbox v-model:checked="sandboxForm.read_only_rootfs">启用只读根文件系统</a-checkbox>
            </a-form-item>
          </a-card>
        </a-tab-pane>
      </a-tabs>

      <div class="bottom-action-bar">
        <a-space wrap>
          <a-button type="primary" html-type="submit" :loading="saving">保存配置</a-button>
          <a-button html-type="button" @click="fetchPolicy" :loading="loading" :disabled="saving">重新加载</a-button>
        </a-space>
      </div>
    </a-form>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { onBeforeRouteLeave } from 'vue-router'

import {
  getLlmConfig,
  getPolicy,
  getSandboxConfig,
  listModelEndpoints,
  listSandboxImages,
  testSandboxConfig,
  updateLlmConfig,
  updatePolicy,
  updateSandboxConfig,
} from '../api'

const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const savedSnapshot = ref('')
const policyPath = ref('')
const activeTab = ref('decision')
const llmConfig = ref({})
const sandboxConfig = ref({})
const modelEndpoints = ref([])
const sandboxImages = ref([])
const testingSandbox = ref(false)
const sandboxTestResult = ref(null)
const defaultSandboxRemoteUrl = 'http://sandbox:8194'

const riskOptions = [
  { value: 'benign', label: 'benign（安全）' },
  { value: 'suspicious', label: 'suspicious（可疑）' },
  { value: 'malicious', label: 'malicious（恶意）' },
]
const judgementModeOptions = [
  { value: 'strict', label: '严格模式：优先降低漏报风险', description: '对潜在危险行为采取保守判定，适合生产环境、敏感数据场景和外部来源 Skill 准入。' },
  { value: 'balanced', label: '平衡模式（推荐）：兼顾安全与可操作性', description: '明确恶意自动阻断，可疑行为进入审核，低置信噪声不直接影响最终结论。' },
  { value: 'permissive', label: '宽松模式：优先减少误报和噪声', description: '仅对明确恶意或策略禁止项阻断，其他风险以提示和人工复核为主。' },
]
const riskClassificationGroups = [
  { key: 'blocking', label: '阻断项', tag: '阻断', color: 'red', description: '确认命中后会按恶意风险处理，阻止 LLM 降级，通常直接进入拒绝或强制人工处理。' },
  { key: 'risk', label: '可疑项', tag: '审核', color: 'orange', description: '作为有效风险信号参与综合判定，通常进入审核；在平衡或宽松模式下可结合上下文降级。' },
  { key: 'noise', label: '噪声', tag: '记录', color: 'default', description: '只作为诊断信息记录，不直接影响最终风险结论，适合环境问题和低价值信号。' },
]
const riskItems = [
  { key: 'data_exfiltration', label: '数据外传', description: '检测到向外部发送数据、采集环境变量、读取敏感信息后可能外传的行为。' },
  { key: 'supply_chain', label: '供应链风险', description: '检测到下载后执行、远程脚本安装、混淆载荷或不可信依赖引入。' },
  { key: 'prompt_injection', label: '提示词注入', description: '检测到忽略上级指令、泄露系统提示词、隐藏指令等面向 Agent 的攻击。' },
  { key: 'tool_misuse', label: '工具滥用', description: '检测到工具投毒、绕过平台校验、诱导 Agent 使用高风险工具等行为。' },
  { key: 'network', label: '网络访问', description: '检测到代码或运行时尝试访问网络，需结合业务场景判断是否必要。' },
  { key: 'credential_access', label: '凭据访问', description: '检测到读取密钥、凭据文件、Token、SSH 配置等敏感凭据相关行为。' },
  { key: 'dynamic_execution', label: '动态执行', description: '检测到 eval、exec、os.system、shell=True 等动态代码或命令执行能力。' },
  { key: 'excessive_permissions', label: '权限过宽', description: '检测到 allowed-tools 过宽、通配权限或不符合最小权限原则的声明。' },
  { key: 'documented_external_api', label: '文档型 API 示例', description: 'SKILL.md 或说明文档中列出的固定 API endpoint、curl 示例。通常只记录为噪声，不代表真实数据外传。' },
  { key: 'dependency', label: '依赖/环境问题', description: '检测到依赖缺失、模块不可导入等环境问题，通常不代表 Skill 本身恶意。' },
  { key: 'runtime', label: '运行时失败', description: '检测到非零退出、超时或运行环境异常，主要用于辅助排查。' },
]
const riskItemLabel = (value) => riskItems.find(item => item.key === value)?.label || value
const defaultRiskClassification = {
  data_exfiltration: 'blocking',
  supply_chain: 'blocking',
  prompt_injection: 'risk',
  tool_misuse: 'risk',
  network: 'risk',
  credential_access: 'risk',
  dynamic_execution: 'risk',
  excessive_permissions: 'risk',
  documented_external_api: 'noise',
  dependency: 'noise',
  runtime: 'noise',
}
const severityOptions = [
  { value: 'MEDIUM', label: 'MEDIUM（中）' },
  { value: 'HIGH', label: 'HIGH（高）' },
  { value: 'CRITICAL', label: 'CRITICAL（严重）' },
]
const decisionColumns = [
  { title: '顺序', dataIndex: 'step', width: 80 },
  { title: '条件', dataIndex: 'condition' },
  { title: '结果', dataIndex: 'result', width: 140 },
  { title: '说明', dataIndex: 'note' },
]
const decisionRows = [
  { step: 1, condition: '命中禁止权限/工具', result: 'REJECTED', note: '最高优先级，直接拒绝' },
  { step: 2, condition: '命中自动拒绝风险（auto_reject_risk）', result: 'REJECTED', note: '不会进入审核队列' },
  { step: 3, condition: '命中需要人工审核（require_human_review）', result: 'VETTED', note: '进入审核队列，等待人工处理' },
  { step: 4, condition: '不高于自动批准最大风险（auto_approve_max_risk）', result: 'APPROVED', note: '自动批准为可信版本' },
]

const formState = reactive({
  auto_approve_max_risk: 'benign',
  require_human_review: ['suspicious'],
  auto_reject_risk: ['malicious'],
  require_sandbox_for_risk: ['suspicious', 'malicious'],
  blocked_permissions: [],
  trusted_authors: [],
  allowed_tools_allowlist: [],
  max_allowed_tools: 20,
  require_license: false,
  accepted_licenses: [],
  judgement_mode: 'balanced',
  risk_classification_groups: {
    blocking: [],
    risk: [],
    noise: [],
  },
})
const llmForm = reactive({
  enabled: false,
  model: 'deepseek-chat',
  timeout_seconds: 30,
  max_files: 6,
  max_file_chars: 3000,
  max_manifest_chars: 12000,
})
const sandboxForm = reactive({
  enabled: false,
  runtime: 'remote',
  image: 'agent-manager-sandbox-runtime:latest',
  timeout_seconds: 15,
  network_mode: 'none',
  memory_limit: '256m',
  cpu_limit: '1.0',
  pids_limit: 64,
  read_only_rootfs: true,
  remote_url: defaultSandboxRemoteUrl,
  remote_api_key: '',
  clear_remote_api_key: false,
})

const conflictingRiskLevels = computed(() =>
  formState.require_human_review.filter((risk) => formState.auto_reject_risk.includes(risk)),
)
const currentJudgementModeDescription = computed(() =>
  judgementModeOptions.find((item) => item.value === formState.judgement_mode)?.description || '',
)
const systemLlmReady = computed(() =>
  Boolean(llmForm.enabled && llmForm.model),
)
const llmModelOptions = computed(() => {
  const values = new Set(modelEndpoints.value.map((item) => item.name).filter(Boolean))
  if (llmForm.model) values.add(llmForm.model)
  return [...values].map((value) => {
    const endpoint = modelEndpoints.value.find((item) => item.name === value)
    const label = endpoint?.display_name ? `${endpoint.display_name} (${value})` : value
    return { value, label }
  })
})
const sandboxImageOptions = computed(() => {
  const values = new Set(sandboxImages.value)
  if (sandboxForm.image) values.add(sandboxForm.image)
  return [...values].map((value) => ({ value, label: value }))
})
const sandboxTestDescription = computed(() => {
  if (!sandboxTestResult.value) return ''
  const parts = [sandboxTestResult.value.message].filter(Boolean)
  if (sandboxTestResult.value.target) parts.push(`目标：${sandboxTestResult.value.target}`)
  if (sandboxTestResult.value.duration_ms != null) parts.push(`耗时：${sandboxTestResult.value.duration_ms} ms`)
  return parts.join('；')
})

const riskClassificationFromGroups = () => {
  const result = {}
  for (const group of riskClassificationGroups) {
    for (const key of formState.risk_classification_groups[group.key] || []) {
      result[key] = group.key
    }
  }
  return result
}

const applyRiskClassification = (mapping = {}) => {
  const merged = { ...defaultRiskClassification, ...(mapping || {}) }
  for (const group of riskClassificationGroups) formState.risk_classification_groups[group.key] = []
  for (const item of riskItems) {
    const group = merged[item.key]
    if (formState.risk_classification_groups[group]) {
      formState.risk_classification_groups[group].push(item.key)
    }
  }
}

const normalizeRiskValues = (values) => (values || []).map(item => (
  typeof item === 'object' && item !== null ? item.value : item
)).filter(value => typeof value === 'string')

const handleRiskGroupChange = (targetGroup, values) => {
  const previous = new Set(formState.risk_classification_groups[targetGroup] || [])
  const selected = new Set(normalizeRiskValues(values))
  for (const item of riskItems) {
    if (previous.has(item.key) && !selected.has(item.key)) selected.add(item.key)
  }
  for (const group of riskClassificationGroups) {
    if (group.key === targetGroup) {
      formState.risk_classification_groups[group.key] = [...selected]
    } else {
      formState.risk_classification_groups[group.key] = formState.risk_classification_groups[group.key].filter(key => !selected.has(key))
    }
  }
}

const buildPayload = () => ({
  auto_approve_max_risk: formState.auto_approve_max_risk,
  require_human_review: formState.require_human_review,
  auto_reject_risk: formState.auto_reject_risk,
  require_sandbox_for_risk: formState.require_sandbox_for_risk,
  blocked_permissions: formState.blocked_permissions,
  trusted_authors: formState.trusted_authors,
  allowed_tools_allowlist: formState.allowed_tools_allowlist,
  max_allowed_tools: Number(formState.max_allowed_tools || 0),
  require_license: formState.require_license,
  accepted_licenses: formState.accepted_licenses,
  scanner_policy: formState.judgement_mode,
  judgement_mode: formState.judgement_mode,
  risk_classification: riskClassificationFromGroups(),
})

const buildLlmPayload = () => ({
  enabled: llmForm.enabled,
  provider: 'model-gateway',
  api_base: '',
  model: llmForm.model,
  timeout_seconds: Number(llmForm.timeout_seconds || 30),
  max_files: Number(llmForm.max_files || 6),
  max_file_chars: Number(llmForm.max_file_chars || 3000),
  max_manifest_chars: Number(llmForm.max_manifest_chars || 12000),
  api_key: null,
  clear_api_key: true,
})

const buildSandboxPayload = () => ({
  enabled: sandboxForm.enabled,
  runtime: sandboxForm.runtime,
  image: sandboxForm.image,
  timeout_seconds: Number(sandboxForm.timeout_seconds || 15),
  network_mode: sandboxForm.network_mode,
  memory_limit: sandboxForm.memory_limit,
  cpu_limit: sandboxForm.cpu_limit,
  pids_limit: Number(sandboxForm.pids_limit || 64),
  read_only_rootfs: sandboxForm.read_only_rootfs,
  remote_url: sandboxForm.remote_url || null,
  remote_api_key: sandboxForm.remote_api_key || null,
  clear_remote_api_key: sandboxForm.clear_remote_api_key,
})

const buildSnapshotPayload = () => ({
  policy: buildPayload(),
  llm: buildLlmPayload(),
  sandbox: buildSandboxPayload(),
})

const markSaved = () => {
  savedSnapshot.value = JSON.stringify(buildSnapshotPayload())
  dirty.value = false
}

const applyPolicy = (policy) => {
  formState.auto_approve_max_risk = policy.auto_approve_max_risk
  formState.require_human_review = [...(policy.require_human_review || [])]
  formState.auto_reject_risk = [...(policy.auto_reject_risk || [])]
  formState.require_sandbox_for_risk = [...(policy.require_sandbox_for_risk || [])]
  formState.blocked_permissions = [...(policy.blocked_permissions || [])]
  formState.trusted_authors = [...(policy.trusted_authors || [])]
  formState.allowed_tools_allowlist = [...(policy.allowed_tools_allowlist || [])]
  formState.max_allowed_tools = policy.max_allowed_tools
  formState.require_license = Boolean(policy.require_license)
  formState.accepted_licenses = [...(policy.accepted_licenses || [])]
  formState.judgement_mode = policy.judgement_mode || 'balanced'
  applyRiskClassification(policy.risk_classification || policy.risk_classification_overrides || {})
  markSaved()
}

const applyLlmConfig = (llm) => {
  llmConfig.value = llm || {}
  llmForm.enabled = llm?.enabled ?? false
  llmForm.model = llm?.model || modelEndpoints.value[0]?.name || 'deepseek-chat'
  llmForm.timeout_seconds = llm?.timeout_seconds ?? 30
  llmForm.max_files = llm?.max_files ?? 6
  llmForm.max_file_chars = llm?.max_file_chars ?? 3000
  llmForm.max_manifest_chars = llm?.max_manifest_chars ?? 12000
}

const applySandboxConfig = (sandbox) => {
  sandboxConfig.value = sandbox || {}
  sandboxForm.enabled = sandbox?.enabled ?? false
  sandboxForm.runtime = sandbox?.runtime || 'remote'
  sandboxForm.image = sandbox?.image || 'agent-manager-sandbox-runtime:latest'
  sandboxForm.timeout_seconds = sandbox?.timeout_seconds ?? 15
  sandboxForm.network_mode = sandbox?.network_mode || 'none'
  sandboxForm.memory_limit = sandbox?.memory_limit || '256m'
  sandboxForm.cpu_limit = sandbox?.cpu_limit || '1.0'
  sandboxForm.pids_limit = sandbox?.pids_limit ?? 64
  sandboxForm.read_only_rootfs = sandbox?.read_only_rootfs ?? true
  sandboxForm.remote_url = sandbox?.remote_url || defaultSandboxRemoteUrl
  sandboxForm.remote_api_key = ''
  sandboxForm.clear_remote_api_key = false
}

const fetchPolicy = async () => {
  loading.value = true
  try {
    const [policyRes, llmRes, sandboxRes, modelRes, imageRes] = await Promise.all([
      getPolicy(),
      getLlmConfig(),
      getSandboxConfig(),
      listModelEndpoints(),
      listSandboxImages(),
    ])
    modelEndpoints.value = Array.isArray(modelRes) ? modelRes : []
    sandboxImages.value = imageRes?.images || []
    applyLlmConfig(llmRes)
    applySandboxConfig(sandboxRes)
    const res = policyRes
    policyPath.value = res.policy_path || ''
    applyPolicy(res.policy)
  } catch (error) {
    message.error(error.response?.data?.detail || '获取策略失败')
  } finally {
    loading.value = false
  }
}

const extractErrorMsg = (error, fallback) => {
  const detail = error.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(e => e.msg).join('; ')
  return fallback
}

const handleSaveAll = async () => {
  saving.value = true
  try {
    const [llmRes, sandboxRes, policyRes] = await Promise.all([
      updateLlmConfig(buildLlmPayload()),
      updateSandboxConfig(buildSandboxPayload()),
      updatePolicy(buildPayload()),
    ])
    applyLlmConfig(llmRes)
    applySandboxConfig(sandboxRes)
    policyPath.value = policyRes.policy_path || ''
    applyPolicy(policyRes.policy)
    message.success('配置已保存')
  } catch (error) {
    message.error(extractErrorMsg(error, '保存配置失败'))
  } finally {
    saving.value = false
  }
}

const handleTestSandboxConnection = async () => {
  testingSandbox.value = true
  sandboxTestResult.value = null
  try {
    const result = await testSandboxConfig({
      ...buildSandboxPayload(),
      enabled: true,
      runtime: 'remote',
    })
    sandboxTestResult.value = result || {}
    if (result?.available) {
      message.success(result.message || 'Sandbox 连接可用')
    } else {
      message.error(result?.message || 'Sandbox 连接不可用')
    }
  } catch (error) {
    message.error(extractErrorMsg(error, '测试 Sandbox 连接失败'))
  } finally {
    testingSandbox.value = false
  }
}

const useDefaultSandboxUrl = () => {
  sandboxForm.runtime = 'remote'
  sandboxForm.remote_url = defaultSandboxRemoteUrl
  sandboxTestResult.value = null
}

const handleBeforeUnload = (event) => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

watch([formState, llmForm, sandboxForm], () => {
  dirty.value = Boolean(savedSnapshot.value && JSON.stringify(buildSnapshotPayload()) !== savedSnapshot.value)
}, { deep: true })

onBeforeRouteLeave(() => {
  if (!dirty.value) return true
  return window.confirm('策略配置有未保存修改，确定离开吗？')
})

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  fetchPolicy()
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>

<style scoped>
.bottom-action-bar {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  margin-top: 20px;
  padding: 12px 16px;
}

.save-hint,
.field-hint {
  color: #8c8c8c;
  font-size: 12px;
  line-height: 1.5;
}

.field-hint {
  margin-top: 6px;
}

.sandbox-test-result {
  margin: -4px 0 16px;
}

.sandbox-auth-collapse {
  margin: -4px 0 16px;
}

.policy-section {
  margin-bottom: 16px;
}

.section-title {
  font-weight: 600;
  margin-bottom: 8px;
}

.risk-class-card {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 12px;
  min-height: 188px;
  background: #fff;
}

.risk-class-header {
  align-items: center;
  display: flex;
  font-weight: 600;
  justify-content: space-between;
  margin-bottom: 8px;
}

.risk-class-description {
  color: #8c8c8c;
  font-size: 12px;
  line-height: 1.5;
  min-height: 54px;
  margin-bottom: 10px;
}

.risk-class-select {
  width: 100%;
}

.risk-class-tag {
  margin: 2px 4px 2px 0;
}

.risk-option {
  line-height: 1.35;
  padding: 4px 0;
  white-space: normal;
}

.risk-option-title {
  color: #262626;
  font-weight: 500;
}

.risk-option-description {
  color: #8c8c8c;
  font-size: 12px;
  margin-top: 2px;
}
</style>
