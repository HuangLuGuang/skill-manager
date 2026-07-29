<template>
  <div>
    <a-page-header :title="$t('legacy.1p5yvwf')" :sub-title="$t('legacy.1r9oqv3')" />

    <a-form layout="vertical" :model="formState" @finish="handleSaveAll">
      <a-alert
        v-if="conflictingRiskLevels.length"
        style="margin-top: 12px"
        type="error"
        show-icon
        :message="$t('legacy.1s2pf8p')"
        :description="text(
          `这些风险同时配置了人工审核和自动拒绝：${conflictingRiskLevels.join('、')}。实际会自动拒绝，不会进入审核队列。`,
          `These risks are configured for both manual review and automatic rejection: ${conflictingRiskLevels.join(', ')}. Automatic rejection takes precedence.`,
        )"
      />

      <a-tabs v-model:activeKey="activeTab" style="margin-top: 16px">
        <a-tab-pane key="decision" :tab="$t('legacy.15tr9ja')">
          <section class="policy-section">
            <div class="section-title">{{ $t("legacy.1qnr6kk") }}</div>
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
              <a-form-item :label="$t('legacy.d9qpsd')">
                <a-select v-model:value="formState.judgement_mode">
                  <a-select-option v-for="item in judgementModeOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">{{ currentJudgementModeDescription }}</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item :label="$t('legacy.1drrjfl')">
                <a-select v-model:value="formState.auto_approve_max_risk">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">{{ $t("legacy.1j17s9m") }}</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item :label="$t('legacy.mvffxz')">
                <a-select v-model:value="formState.require_human_review" mode="multiple" :placeholder="$t('legacy.38b653')">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">{{ $t("legacy.1geckvv") }}</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item :label="$t('legacy.1jphvct')">
                <a-select v-model:value="formState.auto_reject_risk" mode="multiple" :placeholder="$t('legacy.7g5oj8')">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">{{ $t("legacy.1r0krhb") }}</div>
              </a-form-item>
            </a-col>
            <a-col :xs="24" :lg="12">
              <a-form-item :label="$t('legacy.1y5kmg7')">
                <a-select v-model:value="formState.require_sandbox_for_risk" mode="multiple" :placeholder="$t('legacy.m3ilow')">
                  <a-select-option v-for="item in riskOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </a-select-option>
                </a-select>
                <div class="field-hint">{{ $t("legacy.12psofi") }}</div>
              </a-form-item>
            </a-col>
          </a-row>

          <section class="policy-section">
            <div class="section-title">{{ $t("legacy.1e7mnak") }}</div>
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
                    :placeholder="$t('legacy.u81p8d')"
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

        <a-tab-pane key="admission" :tab="$t('legacy.1wsaxvv')">
          <section class="policy-section">
            <div class="section-title">{{ $t("legacy.kicus6") }}</div>
            <a-row :gutter="16">
              <a-col :xs="24" :lg="12">
                <a-form-item :label="$t('legacy.4u3gt4')">
                  <a-input-number v-model:value="formState.max_allowed_tools" :min="1" :max="100" style="width: 100%" />
                  <div class="field-hint">{{ $t("legacy.1u4pday") }}</div>
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item :label="$t('legacy.1hcaau6')">
              <a-select v-model:value="formState.blocked_permissions" mode="tags" :placeholder="$t('legacy.god0gn')" />
              <div class="field-hint">{{ $t("legacy.kfzse8") }}</div>
            </a-form-item>

            <a-form-item :label="$t('legacy.o8tpn9')">
              <a-select v-model:value="formState.allowed_tools_allowlist" mode="tags" :placeholder="$t('legacy.unjnyg')" />
              <div class="field-hint">{{ $t("legacy.r3uboi") }}</div>
            </a-form-item>
          </section>

          <section class="policy-section">
            <div class="section-title">{{ $t("legacy.pcy7z3") }}</div>
            <a-row :gutter="16">
              <a-col :xs="24" :lg="12">
                <a-form-item :label="$t('legacy.rwq8ic')">
                  <a-switch v-model:checked="formState.require_license" />
                  <div class="field-hint">{{ $t("legacy.1fpyfpp") }}</div>
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item :label="$t('legacy.1h5j6c2')">
              <a-select v-model:value="formState.trusted_authors" mode="tags" :placeholder="$t('legacy.1heopsf')" />
              <div class="field-hint">{{ $t("legacy.9ukjba") }}</div>
            </a-form-item>

            <a-form-item :label="$t('legacy.1lpbftr')">
              <a-select v-model:value="formState.accepted_licenses" mode="tags" :placeholder="$t('legacy.12c0o98')" />
              <div class="field-hint">{{ $t("legacy.1xaakez") }}</div>
            </a-form-item>
          </section>

        </a-tab-pane>

        <a-tab-pane key="llm" :tab="$t('legacy.kxtxcz')">
          <a-card :title="$t('legacy.hnbm6t')" size="small">
            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.z86tql')">
                  <a-switch
                    v-model:checked="llmForm.enabled"
                    :checked-children="$t('legacy.5pm2ma')"
                    :un-checked-children="$t('legacy.g0fanx')"
                  />
                  <div class="field-hint">{{ $t("legacy.u1h4vv") }}</div>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="16">
                <a-form-item :label="$t('legacy.1ow6qt')">
                  <a-select
                    v-model:value="llmForm.model"
                    show-search
                    allow-clear
                    :placeholder="$t('legacy.he8ama')"
                    :options="llmModelOptions"
                  />
                  <div class="field-hint">{{ $t("legacy.1irg3nj") }}</div>
                </a-form-item>
              </a-col>
            </a-row>

            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.wa5fzx')">
                  <a-input-number v-model:value="llmForm.timeout_seconds" :min="5" :max="180" style="width: 100%" />
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.3a4t3c')">
                  <a-input-number v-model:value="llmForm.max_files" :min="1" :max="20" style="width: 100%" />
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.1i9i4qp')">
                  <a-input-number v-model:value="llmForm.max_manifest_chars" :min="2000" :max="50000" :step="1000" style="width: 100%" />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item :label="$t('legacy.73z6en')">
              <a-input-number v-model:value="llmForm.max_file_chars" :min="500" :max="20000" :step="500" style="width: 100%" />
            </a-form-item>
          </a-card>
        </a-tab-pane>

        <a-tab-pane key="sandbox" :tab="$t('legacy.1d9ypbb')">
          <a-card :title="$t('legacy.1ikjgw3')" size="small">
            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.u45dd')">
                  <a-switch
                    v-model:checked="sandboxForm.enabled"
                    :checked-children="$t('legacy.5pm2ma')"
                    :un-checked-children="$t('legacy.g0fanx')"
                  />
                  <div class="field-hint">{{ $t("legacy.jvxouw") }}</div>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.1734qnc')">
                  <a-select v-model:value="sandboxForm.runtime">
                    <a-select-option value="remote">{{ $t("legacy.xvarvc") }}</a-select-option>
                    <a-select-option value="docker">docker</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.wa5fzx')">
                  <a-input-number v-model:value="sandboxForm.timeout_seconds" :min="1" :max="300" style="width: 100%" />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item v-if="sandboxForm.runtime === 'docker'" :label="$t('legacy.mjv24c')">
              <a-select
                v-model:value="sandboxForm.image"
                show-search
                :placeholder="$t('legacy.19xos27')"
                :options="sandboxImageOptions"
                :loading="loading"
              />
              <div class="field-hint">{{ $t("legacy.1jxy29r") }}</div>
            </a-form-item>

            <template v-else>
              <a-form-item :label="$t('legacy.18j6yg6')">
                <a-input-group compact>
                  <a-input v-model:value="sandboxForm.remote_url" style="width: calc(100% - 238px)" placeholder="http://sandbox:8194" />
                  <a-button html-type="button" @click="useDefaultSandboxUrl">{{ $t("legacy.1nf2ljj") }}</a-button>
                  <a-button html-type="button" :loading="testingSandbox" @click="handleTestSandboxConnection">{{ $t("legacy.1fmxsdg") }}</a-button>
                </a-input-group>
                <div class="field-hint">{{ $t("legacy.bkm8wx") }}{{ sandboxConfig.config_path || '-' }}</div>
              </a-form-item>

              <a-alert
                v-if="sandboxTestResult"
                class="sandbox-test-result"
                show-icon
                :type="sandboxTestResult.available ? 'success' : 'error'"
                :message="sandboxTestResult.available ? $t('legacy.9duapa') : $t('legacy.1scu0xv')"
                :description="sandboxTestDescription"
              />

              <a-collapse ghost size="small" class="sandbox-auth-collapse">
                <a-collapse-panel key="auth" :header="$t('legacy.1ikhg58')">
                  <a-form-item :label="$t('legacy.16kcq9i')">
                    <a-input-password
                      v-model:value="sandboxForm.remote_api_key"
                      :placeholder="$t('legacy.1io07l0')"
                      autocomplete="new-password"
                    />
                    <div class="field-hint"> {{ $t("legacy.110i633") }}{{ sandboxConfig.remote_api_key_configured ? (sandboxConfig.remote_api_key_masked || $t('legacy.1pxgbde')) : $t('legacy.n1gs62') }}
                    </div>
                  </a-form-item>

                  <a-form-item>
                    <a-checkbox v-model:checked="sandboxForm.clear_remote_api_key">{{ $t("legacy.1wsjgu") }}</a-checkbox>
                  </a-form-item>
                </a-collapse-panel>
              </a-collapse>
            </template>

            <a-row :gutter="16">
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.iiso9g')">
                  <a-select v-model:value="sandboxForm.network_mode">
                    <a-select-option value="none">none</a-select-option>
                    <a-select-option value="bridge">bridge</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.1hksixm')">
                  <a-input v-model:value="sandboxForm.memory_limit" placeholder="256m" />
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item :label="$t('legacy.1gzg08l')">
                  <a-input v-model:value="sandboxForm.cpu_limit" placeholder="1.0" />
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item :label="$t('legacy.7ykb07')">
              <a-input-number v-model:value="sandboxForm.pids_limit" :min="1" :max="1024" style="width: 100%" />
            </a-form-item>

            <a-form-item>
              <a-checkbox v-model:checked="sandboxForm.read_only_rootfs">{{ $t("legacy.1emuxvv") }}</a-checkbox>
            </a-form-item>
          </a-card>
        </a-tab-pane>
      </a-tabs>

      <div class="bottom-action-bar">
        <a-space wrap>
          <a-button type="primary" html-type="submit" :loading="saving">{{ $t("legacy.6zgubv") }}</a-button>
          <a-button html-type="button" @click="fetchPolicy" :loading="loading" :disabled="saving">{{ $t("legacy.1ghz5wv") }}</a-button>
        </a-space>
      </div>
    </a-form>
  </div>
</template>

<script setup>
import { translateLegacy as phrase, translateText as text } from '../i18n'

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
  { value: 'benign', label: phrase('legacy.1tgumc') },
  { value: 'suspicious', label: phrase('legacy.iqwiq5') },
  { value: 'malicious', label: phrase('legacy.1fe99zj') },
]
const judgementModeOptions = [
  { value: 'strict', label: phrase('legacy.1twbn24'), description: phrase('legacy.x3x4mz') },
  { value: 'balanced', label: phrase('legacy.11ev62m'), description: phrase('legacy.krtp51') },
  { value: 'permissive', label: phrase('legacy.umwxgy'), description: phrase('legacy.1izj7l6') },
]
const riskClassificationGroups = [
  { key: 'blocking', label: phrase('legacy.1y6vbr8'), tag: phrase('legacy.1fsazit'), color: 'red', description: phrase('legacy.nkd29f') },
  { key: 'risk', label: phrase('legacy.xgpxf0'), tag: phrase('legacy.1ws11do'), color: 'orange', description: phrase('legacy.4e9acf') },
  { key: 'noise', label: phrase('legacy.m4z27r'), tag: phrase('legacy.cdnjf2'), color: 'default', description: phrase('legacy.1cu0ih4') },
]
const riskItems = [
  { key: 'data_exfiltration', label: phrase('legacy.13wlkrx'), description: phrase('legacy.1xngwd2') },
  { key: 'supply_chain', label: phrase('legacy.33dhvx'), description: phrase('legacy.1hmp9b5') },
  { key: 'prompt_injection', label: phrase('legacy.v4iti5'), description: phrase('legacy.1frd2ou') },
  { key: 'tool_misuse', label: phrase('legacy.1bpfkaw'), description: phrase('legacy.1cubpru') },
  { key: 'network', label: phrase('legacy.1xh2061'), description: phrase('legacy.rg4o7j') },
  { key: 'credential_access', label: phrase('legacy.1jxzdyj'), description: phrase('legacy.10lmwts') },
  { key: 'dynamic_execution', label: phrase('legacy.qath61'), description: phrase('legacy.uts9ww') },
  { key: 'excessive_permissions', label: phrase('legacy.1rc1tey'), description: phrase('legacy.jtwckm') },
  { key: 'documented_external_api', label: phrase('legacy.1iv6edf'), description: phrase('legacy.13g1cqe') },
  { key: 'dependency', label: phrase('legacy.19x9ebb'), description: phrase('legacy.edxa12') },
  { key: 'runtime', label: phrase('legacy.q3x1o3'), description: phrase('legacy.11w6vv5') },
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
  { value: 'MEDIUM', label: phrase('legacy.1y10pck') },
  { value: 'HIGH', label: phrase('legacy.1c4si50') },
  { value: 'CRITICAL', label: phrase('legacy.bj99il') },
]
const decisionColumns = [
  { title: phrase('legacy.bpa6iu'), dataIndex: 'step', width: 80 },
  { title: phrase('legacy.1haswfi'), dataIndex: 'condition' },
  { title: phrase('legacy.q9h21m'), dataIndex: 'result', width: 140 },
  { title: phrase('legacy.1mi4vdj'), dataIndex: 'note' },
]
const decisionRows = [
  { step: 1, condition: phrase('legacy.ys2uvw'), result: 'REJECTED', note: phrase('legacy.ciz2no') },
  { step: 2, condition: phrase('legacy.1t40ibb'), result: 'REJECTED', note: phrase('legacy.hbmb3h') },
  { step: 3, condition: phrase('legacy.1ag3fwd'), result: 'VETTED', note: phrase('legacy.1cpvcnr') },
  { step: 4, condition: phrase('legacy.17x0rvg'), result: 'APPROVED', note: phrase('legacy.d8mg2e') },
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
  if (sandboxTestResult.value.target) {
    parts.push(text(`目标：${sandboxTestResult.value.target}`, `Target: ${sandboxTestResult.value.target}`))
  }
  if (sandboxTestResult.value.duration_ms != null) {
    parts.push(text(
      `耗时：${sandboxTestResult.value.duration_ms} ms`,
      `Duration: ${sandboxTestResult.value.duration_ms} ms`,
    ))
  }
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
    message.error(error.response?.data?.detail || phrase('legacy.1dmx50b'))
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
    message.success(phrase('legacy.1ypovr1'))
  } catch (error) {
    message.error(extractErrorMsg(error, phrase('legacy.jikq9d')))
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
      message.success(result.message || phrase('legacy.9duapa'))
    } else {
      message.error(result?.message || phrase('legacy.1scu0xv'))
    }
  } catch (error) {
    message.error(extractErrorMsg(error, phrase('legacy.z38xwd')))
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
  return window.confirm(phrase('legacy.8h4k7h'))
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
