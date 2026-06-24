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
              <a-form-item label="自动批准最大风险（auto_approve_max_risk）">
                <a-select v-model:value="formState.auto_approve_max_risk">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">低于或等于该风险的 skill 会自动批准并签名；生产环境通常只建议 benign。</div>
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

          <section class="policy-section">
            <div class="section-title">扫描器策略</div>
            <a-row :gutter="16">
              <a-col :xs="24" :lg="12">
                <a-form-item label="扫描策略">
                  <a-select v-model:value="formState.scanner_policy">
                    <a-select-option v-for="item in scannerPolicyOptions" :key="item.value" :value="item.value">
                      {{ item.label }}
                    </a-select-option>
                  </a-select>
                  <div class="field-hint">控制基础 scanner 的敏感程度；balanced 适合日常默认扫描。</div>
                </a-form-item>
              </a-col>
            </a-row>
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
                  <a-input v-model:value="sandboxForm.remote_url" style="width: calc(100% - 150px)" placeholder="http://sandbox:8194" />
                  <a-button html-type="button" @click="useDefaultSandboxUrl">使用默认远程地址</a-button>
                </a-input-group>
                <div class="field-hint">默认推荐 http://sandbox:8194；可以直接编辑为客户环境中的远程 Sandbox 地址。配置文件：{{ sandboxConfig.config_path || '-' }}</div>
              </a-form-item>

              <a-form-item label="远程 API Key">
                <a-input-password
                  v-model:value="sandboxForm.remote_api_key"
                  placeholder="留空则保留现有 key"
                  autocomplete="new-password"
                />
                <div class="field-hint">
                  当前状态：{{ sandboxConfig.remote_api_key_configured ? (sandboxConfig.remote_api_key_masked || '已配置') : '未配置' }}
                </div>
              </a-form-item>

              <a-form-item>
                <a-checkbox v-model:checked="sandboxForm.clear_remote_api_key">清除当前远程 API Key</a-checkbox>
              </a-form-item>
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
const defaultSandboxRemoteUrl = 'http://sandbox:8194'

const riskOptions = [
  { value: 'benign', label: 'benign（安全）' },
  { value: 'suspicious', label: 'suspicious（可疑）' },
  { value: 'malicious', label: 'malicious（恶意）' },
]
const scannerPolicyOptions = [
  { value: 'strict', label: 'strict（更敏感）' },
  { value: 'balanced', label: 'balanced（平衡，推荐）' },
  { value: 'permissive', label: 'permissive（更宽松）' },
]
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
  { step: 4, condition: '不高于自动批准最大风险（auto_approve_max_risk）', result: 'APPROVED', note: '自动批准并签名' },
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
  scanner_policy: 'balanced',
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
  scanner_policy: formState.scanner_policy,
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
  formState.scanner_policy = policy.scanner_policy
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

const useDefaultSandboxUrl = () => {
  sandboxForm.runtime = 'remote'
  sandboxForm.remote_url = defaultSandboxRemoteUrl
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

.policy-section {
  margin-bottom: 16px;
}

.section-title {
  font-weight: 600;
  margin-bottom: 8px;
}
</style>
