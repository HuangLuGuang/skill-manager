<template>
  <div>
    <a-page-header title="策略配置" sub-title="维护公司策略、允许工具和风险阈值" />

    <a-form layout="vertical" :model="formState" @finish="handleSave">
      <div class="top-action-bar">
        <a-space wrap>
          <a-button type="primary" html-type="submit" :loading="saving">保存策略</a-button>
          <a-button @click="fetchPolicy" :loading="loading">重新加载</a-button>
          <span class="save-hint">修改后需要保存才会对后续提交生效</span>
        </a-space>
      </div>

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

        <a-tab-pane key="analyzers" tab="扫描器与分析器">
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
            <a-col :xs="24" :lg="12">
              <a-form-item label="SkillSpector 超时（秒）">
                <a-input-number v-model:value="formState.skillspector_timeout_seconds" :min="10" :max="600" style="width: 100%" />
                <div class="field-hint">超过该时间会停止 SkillSpector，避免提交任务长时间卡住。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="8">
              <a-form-item label="启用 SkillSpector">
                <a-switch v-model:checked="formState.skillspector_enabled" />
                <div class="field-hint">开启后提交扫描会调用 SkillSpector CLI；系统状态会显示是否启用。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="8">
              <a-form-item label="SkillSpector fail-open">
                <a-switch v-model:checked="formState.skillspector_fail_open" />
                <div class="field-hint">开启后 SkillSpector 失败不会阻断整次扫描。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="8">
              <a-form-item label="SkillSpector LLM">
                <a-switch v-model:checked="formState.skillspector_use_llm" :disabled="!systemLlmReady" />
                <div class="field-hint">{{ skillspectorLlmHint }}</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item label="SkillSpector 阻断阈值">
                <a-select v-model:value="formState.skillspector_min_blocking_severity">
                  <a-select-option v-for="item in severityOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">用于解释 SkillSpector 命中严重度；最终状态仍由审批决策汇总决定。</div>
              </a-form-item>
            </a-col>
          </a-row>
        </a-tab-pane>

        <a-tab-pane key="governance" tab="工具、作者与 License">
          <a-row :gutter="16">
            <a-col :xs="24" :lg="12">
              <a-form-item label="允许声明工具上限">
                <a-input-number v-model:value="formState.max_allowed_tools" :min="1" :max="100" style="width: 100%" />
                <div class="field-hint">限制 SKILL.md allowed-tools 数量，防止 skill 声明过宽权限面。</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item label="必须声明 License">
                <a-switch v-model:checked="formState.require_license" />
                <div class="field-hint">开启后，缺少 license 字段会记录策略违规。</div>
              </a-form-item>
            </a-col>
          </a-row>

          <a-form-item label="禁止权限/工具">
            <a-select v-model:value="formState.blocked_permissions" mode="tags" placeholder="例如 read_credentials、write_memory" />
            <div class="field-hint">命中这里的工具或权限会作为阻断项，优先 REJECTED。</div>
          </a-form-item>

          <a-form-item label="允许工具白名单">
            <a-select v-model:value="formState.allowed_tools_allowlist" mode="tags" placeholder="允许 skill 声明的工具列表" />
            <div class="field-hint">不在白名单里的 allowed-tools 会记录策略违规；按当前实现通常不直接阻断。</div>
          </a-form-item>

          <a-form-item label="可信作者">
            <a-select v-model:value="formState.trusted_authors" mode="tags" placeholder="可信作者，可为空" />
            <div class="field-hint">预留字段；当前主要用于展示和后续策略扩展。</div>
          </a-form-item>

          <a-form-item label="允许 License">
            <a-select v-model:value="formState.accepted_licenses" mode="tags" placeholder="MIT、Apache-2.0、internal 等" />
            <div class="field-hint">当“必须声明 License”开启时，用于判断声明的 license 是否可接受。</div>
          </a-form-item>
        </a-tab-pane>
      </a-tabs>
    </a-form>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import { getLlmConfig, getPolicy, updatePolicy } from '../api'

const loading = ref(false)
const saving = ref(false)
const policyPath = ref('')
const activeTab = ref('decision')
const llmConfig = ref({})

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
  skillspector_enabled: false,
  skillspector_fail_open: true,
  skillspector_timeout_seconds: 120,
  skillspector_min_blocking_severity: 'HIGH',
  skillspector_use_llm: false,
})

const conflictingRiskLevels = computed(() =>
  formState.require_human_review.filter((risk) => formState.auto_reject_risk.includes(risk)),
)
const systemLlmReady = computed(() =>
  Boolean(llmConfig.value.enabled && llmConfig.value.api_key_configured && llmConfig.value.api_base && llmConfig.value.model),
)
const skillspectorLlmHint = computed(() => (
  systemLlmReady.value
    ? `使用系统设置里的大模型配置：${llmConfig.value.provider || '-'} / ${llmConfig.value.model || '-'}`
    : '系统设置里的 LLM 未启用或未配置 API Key，不能启用 SkillSpector LLM。'
))

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
  formState.skillspector_enabled = Boolean(policy.skillspector_enabled)
  formState.skillspector_fail_open = policy.skillspector_fail_open !== false
  formState.skillspector_timeout_seconds = Number(policy.skillspector_timeout_seconds || 120)
  formState.skillspector_min_blocking_severity = policy.skillspector_min_blocking_severity || 'HIGH'
  formState.skillspector_use_llm = Boolean(policy.skillspector_use_llm && systemLlmReady.value)
}

const fetchPolicy = async () => {
  loading.value = true
  try {
    const [policyRes, llmRes] = await Promise.all([getPolicy(), getLlmConfig()])
    llmConfig.value = llmRes || {}
    const res = policyRes
    policyPath.value = res.policy_path || ''
    applyPolicy(res.policy)
  } catch (error) {
    message.error(error.response?.data?.detail || '获取策略失败')
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    if (!systemLlmReady.value) formState.skillspector_use_llm = false
    const payload = {
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
      skillspector_enabled: formState.skillspector_enabled,
      skillspector_fail_open: formState.skillspector_fail_open,
      skillspector_timeout_seconds: Number(formState.skillspector_timeout_seconds || 120),
      skillspector_min_blocking_severity: formState.skillspector_min_blocking_severity,
      skillspector_use_llm: systemLlmReady.value && formState.skillspector_use_llm,
    }
    const res = await updatePolicy(payload)
    policyPath.value = res.policy_path || ''
    applyPolicy(res.policy)
    message.success('策略已保存')
  } catch (error) {
    message.error(error.response?.data?.detail || '保存策略失败')
  } finally {
    saving.value = false
  }
}

onMounted(fetchPolicy)
</script>

<style scoped>
.top-action-bar {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  margin-top: 16px;
  padding: 12px 16px;
  position: sticky;
  top: 0;
  z-index: 10;
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
