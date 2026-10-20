<template>
  <div class="policy-page">
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="t('policySettings.title')" :sub-title="t('policySettings.subtitle')" />
      </template>
    <a-alert v-if="loadFailed" type="error" show-icon :message="t('policySettings.loadFailed')">
      <template #action><a-button @click="fetchPolicy" :loading="loading">{{ t('policySettings.reload') }}</a-button></template>
    </a-alert>
    <a-spin :spinning="loading">
      <a-form v-if="loaded" layout="vertical" :model="formState" :disabled="saving || loading || !loaded" @finish="handleSaveAll">
        <a-tabs v-model:activeKey="activeTab">
          <a-tab-pane key="decision" :tab="t('policySettings.admissionTab')">
            <section class="policy-summary" aria-live="polite">
              <div class="section-heading">
                <h2>{{ t('policySettings.summaryTitle') }}</h2>
                <div class="summary-actions">
                  <a-tag :color="dirty ? 'gold' : 'green'">{{ t(dirty ? 'policySettings.draftState' : 'policySettings.savedState') }}</a-tag>
                  <PolicySimulator :policy="simulationPolicy" @update-mode="hasAccess('policy:update') && (formState.judgement_mode = $event)" />
                </div>
              </div>
              <p>{{ policySummary }}</p>
              <div class="field-hint">{{ t('policySettings.effectiveHint') }}</div>
            </section>

            <section class="policy-section">
              <div class="section-heading">
                <h2>{{ t('policySettings.actionsTitle') }}</h2>
                <a-button html-type="button" :disabled="!hasAccess('policy:update') || actionsRecommended || saving || loading || !loaded" @click="useRecommendedActions">{{ t('policySettings.recommendedActions') }}</a-button>
              </div>
              <p class="section-hint">{{ t('policySettings.actionsHint') }}</p>
              <table class="policy-table action-table">
                <thead><tr><th scope="col">{{ t('policySettings.conclusion') }}</th><th scope="col">{{ t('policySettings.action') }}</th></tr></thead>
                <tbody>
                  <tr v-for="risk in policyRisks" :key="risk">
                    <th scope="row"><span class="risk-dot" :class="risk"></span>{{ t('policySettings.risks.' + risk) }}</th>
                    <td>
                      <a-select v-model:value="formState.actions[risk]" :aria-label="t('policySettings.actionFor', { risk: t('policySettings.risks.' + risk) })" :options="actionOptions(risk)" :disabled="saving || loading || !hasAccess('policy:update')" />
                      <div class="field-hint">{{ t('policySettings.actionHints.' + formState.actions[risk]) }}</div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section class="policy-section">
              <div class="section-heading">
                <h2>{{ t('policySettings.rulesTitle') }}</h2>
                <a-tag>{{ t(rulesRecommended ? 'policySettings.recommended' : 'policySettings.customized') }}</a-tag>
              </div>
              <p class="section-hint">{{ t('policySettings.rulesHint') }}</p>
              <div class="classification-overview">
                <div v-for="group in classificationKeys" :id="'risk-class-' + group" :key="group" class="classification-group" :class="{ 'decision-focus': route.query.focus === group }">
                  <h3>{{ t('policySettings.groups.' + group) }}</h3>
                  <p class="field-hint">{{ t('policySettings.groupHints.' + group) }}</p>
                  <div class="classification-tags">
                    <a-tag v-for="item in itemsForGroup(group)" :key="item" :color="focusedCategories.includes(item) ? 'gold' : undefined">{{ t('policySettings.findings.' + item) }}</a-tag>
                    <span v-if="!itemsForGroup(group).length" class="field-hint">{{ t('policySettings.emptyGroup') }}</span>
                  </div>
                </div>
              </div>
              <a-collapse v-model:activeKey="ruleSections" ghost>
                <a-collapse-panel key="rules" :header="t('policySettings.customizeRules')">
                  <div class="reset-rules">
                    <a-button html-type="button" :disabled="rulesRecommended || saving || loading || !loaded" @click="useRecommendedRules">{{ t('policySettings.recommendedRules') }}</a-button>
                    <span class="field-hint">{{ t('policySettings.recommendedRulesHint') }}</span>
                  </div>
                  <a-form-item id="decision-mode" :class="{ 'decision-focus': route.query.focus === 'mode' }">
                    <template #label>
                      {{ t('policySettings.mode') }}
                      <!-- 集中说明所有模式，便于选择前比较判定规则。 -->
                      <a-tooltip :trigger="['hover', 'focus']" :overlay-style="{ maxWidth: 'min(520px, calc(100vw - 32px))' }">
                        <template #title>
                          <ol class="mode-help-content">
                            <li>
                              <strong>{{ t('policySettings.modeHelp.contextualTitle') }}</strong>
                              <ul>
                                <li>{{ t('policySettings.modeHelp.permissive') }}</li>
                                <li>{{ t('policySettings.modeHelp.balanced') }}</li>
                                <li>{{ t('policySettings.modeHelp.strict') }}</li>
                              </ul>
                            </li>
                            <li><strong>{{ t('policySettings.modeHelp.maliciousTitle') }}</strong><p>{{ t('policySettings.modeHelp.malicious') }}</p></li>
                            <li><strong>{{ t('policySettings.modeHelp.aiTitle') }}</strong><p>{{ t('policySettings.modeHelp.ai') }}</p></li>
                          </ol>
                        </template>
                        <button type="button" class="mode-help-button field-help" :aria-label="t('policySettings.modeHelp.label')"><QuestionCircleOutlined /></button>
                      </a-tooltip>
                    </template>
                    <a-select v-model:value="formState.judgement_mode" :get-popup-container="trigger => trigger.parentElement" :aria-label="t('policySettings.mode')" :disabled="saving || loading || !hasAccess('policy:update')">
                      <a-select-option v-for="option in modeOptions" :key="option.value" :value="option.value">
                        <a-tag :color="option.color" style="margin-inline-end: 0; white-space: normal">{{ option.label }}</a-tag>
                      </a-select-option>
                    </a-select>
                  </a-form-item>
                  <table class="policy-table findings-table">
                    <thead><tr><th scope="col">{{ t('policySettings.behavior') }}</th><th scope="col">{{ t('policySettings.classification') }}</th></tr></thead>
                    <tbody>
                      <tr v-for="item in findingKeys" :id="'finding-' + item" :key="item" :class="{ 'finding-focus': focusedCategories.includes(item) }">
                        <th scope="row">{{ t('policySettings.findings.' + item) }}<div class="field-hint">{{ t('policySettings.examples.' + item) }}</div></th>
                        <td><a-select v-model:value="formState.risk_classification[item]" :aria-label="t('policySettings.classificationFor', { behavior: t('policySettings.findings.' + item) })" :options="classificationOptions" :disabled="saving || loading || !hasAccess('policy:update')" /></td>
                      </tr>
                    </tbody>
                  </table>
                </a-collapse-panel>
              </a-collapse>
            </section>

            <a-collapse v-model:activeKey="companySections" class="company-rules">
              <a-collapse-panel key="company" :header="t('policySettings.companyRules')">
                <a-form-item :label="t('policySettings.banned')">
                  <a-select v-model:value="formState.blocked_permissions" mode="tags" :placeholder="t('policySettings.bannedPlaceholder')" :disabled="saving || loading || !hasAccess('policy:update')" />
                  <div class="field-hint">{{ t('policySettings.bannedHint') }}</div>
                </a-form-item>
                <h3>{{ t('policySettings.advisoryTitle') }}</h3>
                <p class="section-hint">{{ t('policySettings.advisoryHint') }}</p>
                <div class="form-grid">
                  <a-form-item :label="t('policySettings.maxTools')">
                    <a-input-number v-model:value="formState.max_allowed_tools" :min="1" :max="100" :disabled="saving || loading || !hasAccess('policy:update')" />
                  </a-form-item>
                  <a-form-item :label="t('policySettings.requireLicense')"><a-switch v-model:checked="formState.require_license" :disabled="saving || loading || !hasAccess('policy:update')" /></a-form-item>
                </div>
                <a-form-item :label="t('policySettings.toolAllowlist')">
                  <a-select v-model:value="formState.allowed_tools_allowlist" mode="tags" :placeholder="t('policySettings.toolsPlaceholder')" :disabled="saving || loading || !hasAccess('policy:update')" />
                </a-form-item>
                <a-form-item :label="t('policySettings.acceptedLicenses')">
                  <a-select v-model:value="formState.accepted_licenses" mode="tags" :placeholder="t('policySettings.licensesPlaceholder')" :disabled="saving || loading || !hasAccess('policy:update')" />
                </a-form-item>
              </a-collapse-panel>
            </a-collapse>
          </a-tab-pane>

          <a-tab-pane key="detection" :tab="t('policySettings.detectionTab')">
            <h2>{{ t('policySettings.detectionTitle') }}</h2>
            <p class="section-hint">{{ t('policySettings.detectionHint') }}</p>
            <section class="capability-section">
              <div class="section-heading">
                <h3>{{ t('policySettings.llmTitle') }}</h3>
                <a-switch v-if="hasAccess('settings:view')" v-model:checked="llmForm.enabled" :aria-label="t('policySettings.llmTitle')" :checked-children="t('policySettings.enabled')" :un-checked-children="t('policySettings.disabled')" :disabled="saving || loading || !hasAccess('settings:update')" />
              </div>
              <p>{{ t('policySettings.llmHint') }}</p>
              <div class="capability-footer">
                <span class="field-hint">{{ !hasAccess('settings:view') ? t('iam.settingsReadRequired') : llmForm.model ? t('policySettings.modelSelected', { model: llmForm.model }) : t('policySettings.modelMissing') }}</span>
                <a-button v-if="hasAccess('settings:view')" html-type="button" @click="openService('llm')">{{ t('policySettings.configure') }}</a-button>
              </div>
            </section>
            <section class="capability-section">
              <div class="section-heading">
                <h3>{{ t('policySettings.sandboxTitle') }}</h3>
                <a-switch v-if="hasAccess('settings:view')" v-model:checked="sandboxForm.enabled" :aria-label="t('policySettings.sandboxTitle')" :checked-children="t('policySettings.enabled')" :un-checked-children="t('policySettings.disabled')" :disabled="saving || loading || !hasAccess('settings:update')" />
              </div>
              <p>{{ t('policySettings.sandboxHint') }}</p>
              <a-form-item :label="t('policySettings.sandboxRequired')">
                <a-select v-model:value="formState.require_sandbox_for_risk" mode="multiple" :options="riskOptions" :placeholder="t('policySettings.selectRisks')" :disabled="saving || loading || !hasAccess('policy:update')" />
                <div class="field-hint">{{ t('policySettings.sandboxRequiredHint') }}</div>
              </a-form-item>
              <div class="capability-footer">
                <span class="field-hint">{{ !hasAccess('settings:view') ? t('iam.settingsReadRequired') : t(sandboxForm.enabled ? 'policySettings.sandboxConfigured' : 'policySettings.sandboxDisabledHint') }}</span>
                <a-button v-if="hasAccess('settings:view')" html-type="button" @click="openService('sandbox')">{{ t('policySettings.configure') }}</a-button>
              </div>
            </section>
          </a-tab-pane>

          <a-tab-pane key="advanced" :tab="t('policySettings.advancedTab')">
            <h2>{{ t('policySettings.advancedTitle') }}</h2>
            <p class="section-hint">{{ t('policySettings.advancedHint') }}</p>
            <a-form-item v-bind="fieldProps('policy.scan_result_reuse_enabled')">
              <template #label><span>{{ t('policySettings.reuseScanResults') }}</span></template>
              <a-switch :aria-label="t('policySettings.reuseScanResults')" :id="'advanced-policy.scan_result_reuse_enabled'" v-model:checked="formState.scan_result_reuse_enabled" :disabled="saving || loading || !hasAccess('policy:update')" />
              <div class="field-hint">{{ t('policySettings.reuseScanResultsHint') }}</div>
            </a-form-item>
            <a-alert v-if="saveFailures.length" type="error" show-icon class="save-errors" :message="t('policySettings.saveFailed')">
              <template #description><ol><li v-for="(line, index) in failureLines(saveFailures)" :key="index">{{ line }}</li></ol></template>
            </a-alert>
            <a-alert v-if="connectionFailures.length" type="error" show-icon class="save-errors" :message="t('policySettings.connectionFailed')">
              <template #description><ol><li v-for="(line, index) in failureLines(connectionFailures)" :key="index">{{ line }}</li></ol></template>
            </a-alert>
            <a-collapse v-model:activeKey="advancedSections">
              <a-collapse-panel v-if="hasAccess('settings:view')" key="llm" :header="t('policySettings.llmConfig')">
                <a-form-item :label="t('policySettings.model')" v-bind="fieldProps('llm.model')">
                  <a-select :id="'advanced-llm.model'" v-model:value="llmForm.model" show-search allow-clear :placeholder="t('policySettings.modelPlaceholder')" :options="llmModelOptions" :disabled="saving || loading || !hasAccess('settings:update')" />
                  <div class="field-hint"><router-link to="/model-gateway/models">{{ t('policySettings.modelHint') }}</router-link></div>
                </a-form-item>
                <div class="form-grid">
                  <a-form-item :label="t('policySettings.timeout')" v-bind="fieldProps('llm.timeout_seconds')"><ConfigIntegerInput :id="'advanced-llm.timeout_seconds'" v-model:value="llmForm.timeout_seconds" :min="5" :max="180" :step="1" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                  <a-form-item :label="t('policySettings.maxFiles')" v-bind="fieldProps('llm.max_files')"><ConfigIntegerInput :id="'advanced-llm.max_files'" v-model:value="llmForm.max_files" :min="1" :max="20" :step="1" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                  <a-form-item :label="t('policySettings.maxManifestChars')" v-bind="fieldProps('llm.max_manifest_chars')"><ConfigIntegerInput :id="'advanced-llm.max_manifest_chars'" v-model:value="llmForm.max_manifest_chars" :min="2000" :max="50000" :step="1000" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                  <a-form-item :label="t('policySettings.maxFileChars')" v-bind="fieldProps('llm.max_file_chars')"><ConfigIntegerInput :id="'advanced-llm.max_file_chars'" v-model:value="llmForm.max_file_chars" :min="500" :max="20000" :step="500" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                </div>
              </a-collapse-panel>
              <a-collapse-panel v-if="hasAccess('settings:view')" key="sandbox" :header="t('policySettings.sandboxConfig')">
                <div class="form-grid">
                  <a-form-item :label="t('policySettings.runtime')" v-bind="fieldProps('sandbox.runtime')">
                    <a-select :id="'advanced-sandbox.runtime'" v-model:value="sandboxForm.runtime" :options="runtimeOptions" :disabled="saving || loading || !hasAccess('settings:update')" />
                  </a-form-item>
                  <a-form-item :label="t('policySettings.timeout')" v-bind="fieldProps('sandbox.timeout_seconds')"><ConfigIntegerInput :id="'advanced-sandbox.timeout_seconds'" v-model:value="sandboxForm.timeout_seconds" :min="1" :max="300" :step="1" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                </div>
                <a-form-item v-if="sandboxForm.runtime === 'docker'" :label="t('policySettings.image')" v-bind="fieldProps('sandbox.image')">
                  <a-select :id="'advanced-sandbox.image'" v-model:value="sandboxForm.image" show-search :placeholder="t('policySettings.imagePlaceholder')" :options="sandboxImageOptions" :loading="imagesLoading" :disabled="saving || loading || !hasAccess('settings:update')" />
                </a-form-item>
                <template v-else>
                  <a-form-item :label="t('policySettings.remoteUrl')" v-bind="fieldProps('sandbox.remote_url')">
                    <div class="connection-controls">
                      <a-input :id="'advanced-sandbox.remote_url'" v-model:value="sandboxForm.remote_url" placeholder="http://sandbox:8194" :disabled="saving || loading || !hasAccess('settings:update')" />
                      <a-button html-type="button" :disabled="!hasAccess('settings:update') || testingSandbox || saving || loading || !loaded" @click="useDefaultSandboxUrl">{{ t('policySettings.defaultUrl') }}</a-button>
                      <a-button html-type="button" :loading="testingSandbox" :disabled="!hasAccess('settings:update') || testingSandbox || saving || loading || !loaded" @click="handleTestSandboxConnection">{{ t('policySettings.testConnection') }}</a-button>
                    </div>
                  </a-form-item>
                  <a-alert v-if="sandboxTestResult" class="sandbox-test-result" show-icon :type="sandboxTestResult.available ? 'success' : 'error'" :message="t(sandboxTestResult.available ? 'policySettings.connectionOk' : 'policySettings.connectionFailed')" :description="sandboxTestDescription" />
                  <a-collapse v-model:activeKey="authSections" ghost>
                    <a-collapse-panel key="auth" :header="t('policySettings.auth')">
                      <a-form-item :label="t('policySettings.apiKey')" v-bind="fieldProps('sandbox.remote_api_key')">
                        <a-input-password :id="'advanced-sandbox.remote_api_key'" v-model:value="sandboxForm.remote_api_key" :placeholder="t('policySettings.apiKeyPlaceholder')" autocomplete="new-password" :disabled="saving || loading || !hasAccess('settings:update')" />
                        <div class="field-hint">{{ t('policySettings.currentKey', { key: sandboxConfig.remote_api_key_configured ? (sandboxConfig.remote_api_key_masked || t('policySettings.configuredKey')) : t('policySettings.notConfigured') }) }}</div>
                      </a-form-item>
                      <a-form-item v-bind="fieldProps('sandbox.clear_remote_api_key')">
                        <div class="inline-clear-key">
                          <a-checkbox :id="'advanced-sandbox.clear_remote_api_key'" v-model:checked="sandboxForm.clear_remote_api_key" :disabled="saving || loading || !hasAccess('settings:update')">{{ t('policySettings.clearKey') }}</a-checkbox>
                          <a-tooltip :title="t('policySettings.fieldHints.sandbox_clear_remote_api_key')"><QuestionCircleOutlined class="field-help" /></a-tooltip>
                        </div>
                      </a-form-item>
                    </a-collapse-panel>
                  </a-collapse>
                </template>
                <a-alert v-if="sandboxForm.runtime === 'remote'" type="info" show-icon class="remote-limits" :message="t('policySettings.remoteLimits')" />
                <div class="form-grid">
                  <a-form-item :label="t('policySettings.network')" v-bind="fieldProps('sandbox.network_mode')"><a-select :id="'advanced-sandbox.network_mode'" v-model:value="sandboxForm.network_mode" :options="networkOptions" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                  <a-form-item v-if="sandboxForm.runtime === 'docker'" :label="t('policySettings.memory')" v-bind="fieldProps('sandbox.memory_limit')"><a-input :id="'advanced-sandbox.memory_limit'" v-model:value="sandboxForm.memory_limit" placeholder="256m" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                  <a-form-item v-if="sandboxForm.runtime === 'docker'" :label="t('policySettings.cpu')" v-bind="fieldProps('sandbox.cpu_limit')"><a-input :id="'advanced-sandbox.cpu_limit'" v-model:value="sandboxForm.cpu_limit" inputmode="decimal" placeholder="1.0" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                  <a-form-item v-if="sandboxForm.runtime === 'docker'" :label="t('policySettings.pids')" v-bind="fieldProps('sandbox.pids_limit')"><ConfigIntegerInput :id="'advanced-sandbox.pids_limit'" v-model:value="sandboxForm.pids_limit" :min="1" :max="1024" :step="1" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
                </div>
                <a-form-item v-if="sandboxForm.runtime === 'docker'" :label="t('policySettings.readOnly')" v-bind="fieldProps('sandbox.read_only_rootfs')"><a-checkbox :id="'advanced-sandbox.read_only_rootfs'" v-model:checked="sandboxForm.read_only_rootfs" :disabled="saving || loading || !hasAccess('settings:update')" /></a-form-item>
              </a-collapse-panel>
            </a-collapse>
          </a-tab-pane>
        </a-tabs>
        <div class="bottom-action-bar">
          <a-button v-if="hasAccess('policy:update') || (hasAccess('settings:view') && hasAccess('settings:update'))" type="primary" html-type="submit" :loading="saving" :disabled="saving || loading || !loaded || !dirty">{{ t('policySettings.save') }}</a-button>
          <a-button html-type="button" :loading="loading" :disabled="saving || loading" @click="reloadPolicy">{{ t('policySettings.reload') }}</a-button>
          <span v-if="loaded" class="field-hint">{{ t(dirty ? 'policySettings.draftState' : 'policySettings.savedState') }}</span>
        </div>
      </a-form>
    </a-spin>
    </a-card>

  </div>
</template>

<script setup>
import { advancedConfigErrors, configRequestError } from '../utils/advancedConfig.js'
import ConfigIntegerInput from '../components/ConfigIntegerInput.vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'
import { modelLabel } from '../utils/modelLabels'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { can as hasAccess } from '../access'
import PolicySimulator from '../components/PolicySimulator.vue'
import {
  getLlmConfig, getPolicy, getSandboxConfig, listModelEndpoints, listSandboxImages,
  testSandboxConfig, updateLlmConfig, updatePolicy, updateSandboxConfig,
} from '../api'
import {
  policyRisks, recommendedActions, classificationKeys, defaultRiskClassification,
  policyActions, actionPolicy, allowedActions,
} from '../utils/policySettings'

const { t, locale } = useI18n()
const route = useRoute()
const loading = ref(false)
const loaded = ref(false)
const loadFailed = ref(false)
const saving = ref(false)
const savedState = reactive({ policy: '', llm: '', sandbox: '' })
const persistedPolicy = ref({})
const activeTab = ref('decision')
const ruleSections = ref([])
const companySections = ref([])
const advancedSections = ref([])
const authSections = ref([])
const focusedCategories = computed(() => String(route.query.categories || '').split(',').filter(Boolean))
const sandboxConfig = ref({})
const modelEndpoints = ref([])
const sandboxImages = ref([])
const testingSandbox = ref(false)
const sandboxTestResult = ref(null)
const defaultSandboxRemoteUrl = 'http://sandbox:8194'
const findingKeys = Object.keys(defaultRiskClassification)

const formState = reactive({
  scan_result_reuse_enabled: true,
  actions: { ...recommendedActions },
  require_sandbox_for_risk: [],
  blocked_permissions: [],
  allowed_tools_allowlist: [],
  max_allowed_tools: 20,
  require_license: false,
  accepted_licenses: [],
  judgement_mode: 'balanced',
  risk_classification: { ...defaultRiskClassification },
})
const llmForm = reactive({
  enabled: false, model: '', timeout_seconds: 30,
  max_files: 6, max_file_chars: 3000, max_manifest_chars: 12000,
})
const sandboxForm = reactive({
  enabled: false, runtime: 'remote', image: 'agent-manager-sandbox-runtime:latest',
  timeout_seconds: 15, network_mode: 'none', memory_limit: '256m', cpu_limit: '1.0',
  pids_limit: 64, read_only_rootfs: true, remote_url: defaultSandboxRemoteUrl,
  remote_api_key: '', clear_remote_api_key: false,
})
const riskOptions = computed(() => policyRisks.map(value => ({ value, label: t('policySettings.risks.' + value) })))
const modeOptions = computed(() => ['permissive', 'balanced', 'strict'].map(value => ({ value, label: t('policySettings.modes.' + value), color: { permissive: 'green', balanced: 'blue', strict: 'volcano' }[value] })))
const classificationOptions = computed(() => classificationKeys.map(value => ({ value, label: t('policySettings.groups.' + value) })))
const runtimeOptions = computed(() => ['remote', 'docker'].map(value => ({ value, label: t('policySettings.' + value) })))
const networkOptions = computed(() => [
  { value: 'none', label: t('policySettings.noNetwork') },
  { value: 'bridge', label: t('policySettings.bridgeNetwork') },
])
const actionOptions = risk => allowedActions(risk).map(value => ({ value, label: t('policySettings.actions.' + value) }))
const itemsForGroup = group => findingKeys.filter(key => formState.risk_classification[key] === group)
const policySummary = computed(() => t('policySettings.summary', Object.fromEntries(
  policyRisks.map(risk => [risk, t('policySettings.actions.' + formState.actions[risk])]),
)))
const actionsRecommended = computed(() => policyRisks.every(risk => formState.actions[risk] === recommendedActions[risk]))
const rulesRecommended = computed(() => formState.judgement_mode === 'balanced'
  && findingKeys.every(key => formState.risk_classification[key] === defaultRiskClassification[key]))
const useRecommendedActions = () => { formState.actions = { ...recommendedActions } }
const useRecommendedRules = () => {
  formState.judgement_mode = 'balanced'
  Object.assign(formState.risk_classification, defaultRiskClassification)
}
const openService = service => {
  activeTab.value = 'advanced'
  advancedSections.value = [service]
}
const focusDecisionConfig = async () => {
  const tab = route.query.tab
  if (tab === 'llm' || tab === 'sandbox') {
    openService(tab)
    return
  }
  if (tab === 'admission') {
    activeTab.value = 'decision'
    companySections.value = ['company']
    return
  }
  if (['detection', 'advanced'].includes(tab)) {
    activeTab.value = tab
    return
  }
  if (tab !== 'decision') return
  activeTab.value = 'decision'
  if (route.query.focus === 'mode' || focusedCategories.value.length) ruleSections.value = ['rules']
  await nextTick()
  const id = route.query.focus === 'mode' ? 'decision-mode'
    : classificationKeys.includes(route.query.focus) ? 'risk-class-' + route.query.focus : null
  if (id) document.getElementById(id)?.scrollIntoView({ block: 'center' })
}
watch(() => route.query, focusDecisionConfig)

const llmModelOptions = computed(() => {
  const values = new Set(modelEndpoints.value.map(item => item.name).filter(Boolean))
  if (llmForm.model) values.add(llmForm.model)
  return [...values].map(value => {
    const endpoint = modelEndpoints.value.find(item => item.name === value)
    return { value, label: endpoint ? modelLabel(endpoint) : value }
  })
})
const sandboxImageOptions = computed(() => {
  const values = new Set(sandboxImages.value)
  if (sandboxForm.image) values.add(sandboxForm.image)
  return [...values].map(value => ({ value, label: value }))
})
const sandboxTestDescription = computed(() => {
  const result = sandboxTestResult.value
  if (!result) return ''
  const parts = []
  if (result.target) parts.push(t('policySettings.connectionTarget', { target: result.target }))
  if (result.duration_ms != null) parts.push(t('policySettings.connectionDuration', { duration: result.duration_ms }))
  return parts.join(' · ')
})
watch(sandboxForm, () => { sandboxTestResult.value = null }, { deep: true })

const buildPayload = () => ({
  ...persistedPolicy.value,
  scan_result_reuse_enabled: formState.scan_result_reuse_enabled,
  ...actionPolicy(formState.actions),
  require_sandbox_for_risk: formState.require_sandbox_for_risk,
  blocked_permissions: formState.blocked_permissions,
  allowed_tools_allowlist: formState.allowed_tools_allowlist,
  max_allowed_tools: Number(formState.max_allowed_tools),
  require_license: formState.require_license,
  accepted_licenses: formState.accepted_licenses,
  scanner_policy: formState.judgement_mode,
  judgement_mode: formState.judgement_mode,
  risk_classification: { ...formState.risk_classification },
})

const simulationPolicy = computed(() => ({
  judgement_mode: formState.judgement_mode,
  risk_classification: { ...formState.risk_classification },
  ...actionPolicy(formState.actions),
  require_sandbox_for_risk: [...formState.require_sandbox_for_risk],
  blocked_permissions: [...formState.blocked_permissions],
}))

const buildLlmPayload = () => ({
  enabled: llmForm.enabled,
  provider: 'model-gateway',
  api_base: '',
  model: llmForm.model || '',
  timeout_seconds: Number(llmForm.timeout_seconds),
  max_files: Number(llmForm.max_files),
  max_file_chars: Number(llmForm.max_file_chars),
  max_manifest_chars: Number(llmForm.max_manifest_chars),
  api_key: null,
  clear_api_key: true,
})

const buildSandboxPayload = () => {
  const payload = {
  enabled: sandboxForm.enabled,
  runtime: sandboxForm.runtime,
  image: sandboxForm.image,
  timeout_seconds: Number(sandboxForm.timeout_seconds),
  network_mode: sandboxForm.network_mode,
  memory_limit: sandboxForm.memory_limit,
  cpu_limit: sandboxForm.cpu_limit,
  pids_limit: Number(sandboxForm.pids_limit),
  read_only_rootfs: sandboxForm.read_only_rootfs,
  remote_url: sandboxForm.remote_url || null,
  remote_api_key: sandboxForm.remote_api_key || null,
  clear_remote_api_key: sandboxForm.clear_remote_api_key,
  }
  const inactive = sandboxForm.runtime === 'docker'
    ? ['remote_url', 'remote_api_key', 'clear_remote_api_key']
    : ['image', 'memory_limit', 'cpu_limit', 'pids_limit', 'read_only_rootfs']
  for (const field of inactive) delete payload[field]
  return payload
}


const buildSnapshotPayload = () => ({
  policy: buildPayload(), llm: { ...llmForm }, sandbox: { ...sandboxForm },
})
const dirty = computed(() => loaded.value && Object.entries(buildSnapshotPayload()).some(
  ([key, payload]) => JSON.stringify(payload) !== savedState[key],
))
const markSaved = () => {
  for (const [key, payload] of Object.entries(buildSnapshotPayload())) savedState[key] = JSON.stringify(payload)
}
const applyPolicy = policy => {
  persistedPolicy.value = { ...policy }
  formState.scan_result_reuse_enabled = policy.scan_result_reuse_enabled !== false
  formState.actions = policyActions(policy)
  formState.require_sandbox_for_risk = [...(policy.require_sandbox_for_risk || [])]
  formState.blocked_permissions = [...(policy.blocked_permissions || [])]
  formState.allowed_tools_allowlist = [...(policy.allowed_tools_allowlist || [])]
  formState.max_allowed_tools = policy.max_allowed_tools
  formState.require_license = Boolean(policy.require_license)
  formState.accepted_licenses = [...(policy.accepted_licenses || [])]
  formState.judgement_mode = policy.judgement_mode || 'balanced'
  formState.risk_classification = {
    ...defaultRiskClassification, ...(policy.risk_classification || policy.risk_classification_overrides || {}),
  }
}
const applyLlmConfig = (llm) => {
  llmForm.enabled = llm?.enabled ?? false
  llmForm.model = llm?.model || ''
  llmForm.timeout_seconds = llm?.timeout_seconds ?? 30
  llmForm.max_files = llm?.max_files ?? 6
  llmForm.max_file_chars = llm?.max_file_chars ?? 3000
  llmForm.max_manifest_chars = llm?.max_manifest_chars ?? 12000
}

const applySandboxConfig = (sandbox) => {
  sandboxConfig.value = sandbox || {}
  sandboxForm.enabled = sandbox?.enabled ?? false
  sandboxForm.runtime = sandbox?.runtime ?? 'remote'
  sandboxForm.image = sandbox?.image ?? 'agent-manager-sandbox-runtime:latest'
  sandboxForm.timeout_seconds = sandbox?.timeout_seconds ?? 15
  sandboxForm.network_mode = sandbox?.network_mode ?? 'none'
  sandboxForm.memory_limit = sandbox?.memory_limit ?? '256m'
  sandboxForm.cpu_limit = sandbox?.cpu_limit ?? '1.0'
  sandboxForm.pids_limit = sandbox?.pids_limit ?? 64
  sandboxForm.read_only_rootfs = sandbox?.read_only_rootfs ?? true
  sandboxForm.remote_url = sandbox?.remote_url ?? defaultSandboxRemoteUrl
  sandboxForm.remote_api_key = ''
  sandboxForm.clear_remote_api_key = false
}


const imagesLoading = ref(false)
let imagesLoaded = false
const loadSandboxImages = async (force = false) => {
  if (!loaded.value || sandboxForm.runtime !== 'docker' || !hasAccess('settings:view') || imagesLoading.value) return
  if (imagesLoaded && !force) return
  imagesLoading.value = true
  try { sandboxImages.value = (await listSandboxImages()).images || []; imagesLoaded = true }
  catch { message.error(t('policySettings.loadFailed')) }
  finally { imagesLoading.value = false }
}
watch(() => sandboxForm.runtime, () => loadSandboxImages())

const fetchPolicy = async () => {
  if (loading.value || saving.value) return
  loading.value = true
  loadFailed.value = false
  try {
    const [policyRes, llmRes, sandboxRes, modelRes] = await Promise.all([
      getPolicy(),
      hasAccess('settings:view') ? getLlmConfig() : null,
      hasAccess('settings:view') ? getSandboxConfig() : null,
      hasAccess('models:view') ? listModelEndpoints() : [],
    ])
    modelEndpoints.value = Array.isArray(modelRes) ? modelRes : []
    applyLlmConfig(llmRes)
    applySandboxConfig(sandboxRes)
    applyPolicy(policyRes.policy)
    markSaved()
    saveFailures.value = []
    connectionFailures.value = []
    for (const key of Object.keys(serverFieldErrors)) delete serverFieldErrors[key]
    loaded.value = true
    void loadSandboxImages(true)
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}
const reloadPolicy = () => {
  if (dirty.value && !window.confirm(t('policySettings.leaveConfirm'))) return
  return fetchPolicy()
}
const serverFieldErrors = reactive({})
const saveFailures = ref([])
const connectionFailures = ref([])
const forms = { llm: llmForm, sandbox: sandboxForm, policy: formState }
const localErrors = computed(() => Object.fromEntries(Object.entries(forms).flatMap(([group, form]) =>
  Object.entries(advancedConfigErrors(group, form)).map(([field, error]) => [`${group}.${field}`, error]),
)))
const groupLabel = group => t(`policySettings.${{ llm: 'llmConfig', sandbox: 'sandboxConfig', policy: 'admissionTab' }[group]}`)
const errorMessage = error => error.code.startsWith('sandbox.url_')
  ? t(`policySettings.sandboxUrlErrors.${error.code.slice(8)}`)
  : t(`policySettings.validation.${error.code.replace('config.', '')}`, error.params)
const fieldProps = key => {
  const [group, field] = key.split('.')
  const error = localErrors.value[key] || serverFieldErrors[key]
    || connectionFailures.value.find(failure => failure.group === group)?.errors?.find(item => item.field === field)
  return {
    tooltip: group === 'policy' ? undefined : t(`policySettings.fieldHints.${key.replace('.', '_')}`),
    validateStatus: error ? 'error' : undefined,
    help: error ? errorMessage(error) : undefined,
    htmlFor: group === 'policy' ? null : `advanced-${key}`,
  }
}
const failureLines = failures => failures.flatMap(failure => {
  const prefix = groupLabel(failure.group)
  return failure.errors?.length
    ? failure.errors.map(error => `${prefix}: ${t(`policySettings.fieldNames.${error.field}`)}: ${errorMessage(error)}`)
    : [`${prefix}: ${configRequestError(failure, locale.value)}`]
})
for (const [group, form] of Object.entries(forms)) {
  watch(() => ({ ...form }), (current, previous) => {
    for (const field of Object.keys(current)) {
      if (current[field] !== previous[field]) delete serverFieldErrors[`${group}.${field}`]
    }
  })
}
const validateGroups = async (groups, source = 'save') => {
  const keys = Object.keys(localErrors.value).filter(key => groups.includes(key.split('.')[0]))
  if (!keys.length) return true
  const failures = source === 'test' ? connectionFailures : saveFailures
  failures.value = groups.map(group => ({ group, errors: keys.filter(key => key.startsWith(`${group}.`)).map(key => ({ field: key.split('.')[1], ...localErrors.value[key] })) })).filter(failure => failure.errors.length)
  activeTab.value = 'advanced'
  advancedSections.value = [...new Set(keys.map(key => key.split('.')[0]).filter(group => group !== 'policy'))]
  if (keys.some(key => key === 'sandbox.remote_api_key' || key === 'sandbox.clear_remote_api_key')) authSections.value = ['auth']
  message.error(t(source === 'test' ? 'policySettings.testFixFields' : 'policySettings.fixFields'))
  await nextTick()
  document.getElementById(`advanced-${keys[0]}`)?.focus()
  return false
}
const recordFailure = (group, error, source = 'save') => {
  const body = error.response?.data || {}
  const errors = body.error_params?.errors?.filter(item => item.field && item.code) || []
  if (source === 'save') for (const item of errors) serverFieldErrors[`${group}.${item.field}`] = item
  return { group, errors, code: body.error_code, params: body.error_params, message: body.detail || '' }
}
const handleSaveAll = async () => {
  if (saving.value || loading.value || !loaded.value || !dirty.value) return
  const jobs = [
    { key: 'policy', build: buildPayload, update: updatePolicy, apply: result => applyPolicy(result.policy) },
    { key: 'llm', build: buildLlmPayload, update: updateLlmConfig, apply: applyLlmConfig },
    { key: 'sandbox', build: buildSandboxPayload, update: updateSandboxConfig, apply: applySandboxConfig },
  ].filter(job => hasAccess(job.key === 'policy' ? 'policy:update' : 'settings:update')
    && (job.key === 'policy' || hasAccess('settings:view'))
    && JSON.stringify(buildSnapshotPayload()[job.key]) !== savedState[job.key])
  if (!await validateGroups(jobs.map(job => job.key))) return
  saving.value = true
  saveFailures.value = []
  try {
    const results = await Promise.allSettled(jobs.map(async job => {
      const result = await job.update(job.build())
      job.apply(result)
      savedState[job.key] = JSON.stringify(buildSnapshotPayload()[job.key])
      for (const key of Object.keys(serverFieldErrors)) if (key.startsWith(`${job.key}.`)) delete serverFieldErrors[key]
    }))
    saveFailures.value = results.flatMap((result, index) => result.status === 'rejected' ? [recordFailure(jobs[index].key, result.reason)] : [])
    if (saveFailures.value.length) {
      activeTab.value = 'advanced'
      advancedSections.value = saveFailures.value.map(failure => failure.group)
      message.error(t('policySettings.saveFailed'))
    } else message.success(t('policySettings.saved'))
  } finally {
    saving.value = false
  }
}
const handleTestSandboxConnection = async () => {
  if (!hasAccess('settings:update') || testingSandbox.value || saving.value || loading.value || !loaded.value) return
  sandboxTestResult.value = null
  if (!await validateGroups(['sandbox'], 'test')) return
  testingSandbox.value = true
  const payload = { ...buildSandboxPayload(), enabled: true, runtime: 'remote' }
  try {
    const result = await testSandboxConfig(payload)
    if (JSON.stringify(payload) === JSON.stringify({ ...buildSandboxPayload(), enabled: true, runtime: 'remote' })) {
      sandboxTestResult.value = result
      connectionFailures.value = []
    }
  } catch (error) {
    connectionFailures.value = [recordFailure('sandbox', error, 'test')]
    message.error(t('policySettings.connectionFailed'))
  } finally {
    testingSandbox.value = false
  }
}
const useDefaultSandboxUrl = () => {
  sandboxForm.runtime = 'remote'
  sandboxForm.remote_url = defaultSandboxRemoteUrl
}
const handleBeforeUnload = event => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeRouteLeave(() => !dirty.value || window.confirm(t('policySettings.leaveConfirm')))
onMounted(async () => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  await fetchPolicy()
  await focusDecisionConfig()
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>

<style scoped>
.policy-page {
  --policy-ink: #1f2937;
  --policy-muted: #637083;
  --policy-border: #e5e9ef;
  --policy-surface: #f6f8fb;
  --policy-accent: #2459ad;
  color: var(--policy-ink);
  width: 100%;
}
.save-errors, .remote-limits { margin-bottom: 16px; }
.inline-clear-key { display: flex; align-items: center; gap: 6px; }
.field-help { color: #8c8c8c; }
.mode-help-button { margin-inline-start: 6px; padding: 0; border: 0; background: transparent; font: inherit; line-height: 1; cursor: help; }
.mode-help-button:focus-visible { outline: 2px solid var(--policy-accent); outline-offset: 3px; }
.mode-help-content { margin: 0; padding-inline-start: 20px; line-height: 1.65; overflow-wrap: anywhere; }
.mode-help-content > li + li { margin-top: 10px; }
.mode-help-content ul { padding-inline-start: 18px; margin-top: 4px; }
.mode-help-content p { margin: 4px 0 0; }
.save-errors ol { margin: 0; padding-left: 20px; overflow-wrap: anywhere; }
.policy-page h2 { font-size: 17px; font-weight: 600; line-height: 1.5; margin: 0; }
.policy-page h3 { font-size: 14px; font-weight: 600; line-height: 1.5; margin: 0; }
.policy-page p { line-height: 1.65; margin: 8px 0 12px; }
.policy-page :deep(.ant-spin-nested-loading) { min-height: 160px; }
.policy-page :deep(.ant-form-item-label > label) { height: auto; white-space: normal; }
.policy-page :deep(.ant-select), .policy-page :deep(.ant-input-number) { width: 100%; min-width: 0; }
.policy-page :deep(.ant-select-selection-item) { white-space: normal; overflow-wrap: anywhere; }
.policy-page :deep(.ant-select-single .ant-select-selector) { min-height: 32px; height: auto; }
.policy-page :deep(.ant-btn) { height: auto; min-height: 32px; white-space: normal; }
.section-heading, .capability-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.section-heading .ant-tag { margin: 0; }
.summary-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.policy-summary { background: var(--policy-surface); border-left: 3px solid var(--policy-accent); padding: 18px 20px; margin-bottom: 24px; }
.policy-summary p { margin-bottom: 6px; }
.policy-section { margin-bottom: 24px; }
.section-hint, .field-hint { color: var(--policy-muted); font-size: 13px; font-weight: 400; line-height: 1.6; overflow-wrap: anywhere; }
.field-hint { margin-top: 5px; }
.policy-table { width: 100%; table-layout: fixed; border-collapse: collapse; }
.policy-table th, .policy-table td { text-align: left; padding: 14px 16px; border-bottom: 1px solid var(--policy-border); vertical-align: middle; overflow-wrap: anywhere; }
.policy-table thead th { background: var(--policy-surface); color: var(--policy-muted); font-size: 12px; font-weight: 500; padding-top: 9px; padding-bottom: 9px; }
.policy-table th:first-child { width: 44%; }
.policy-table tbody th { font-weight: 500; }
.risk-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 10px; }
.risk-dot.benign { background: #30845d; }
.risk-dot.suspicious { background: #b97511; }
.risk-dot.malicious { background: #c74545; }
.classification-overview { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--policy-border); border-radius: 6px; }
.classification-group { padding: 16px; min-width: 0; }
.classification-group + .classification-group { border-left: 1px solid var(--policy-border); }
.classification-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.classification-tags .ant-tag { margin: 0; max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.reset-rules { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.decision-focus { outline: 2px solid #c49a46; outline-offset: 3px; border-radius: 6px; scroll-margin-top: 90px; }
.finding-focus { background: #fff8e8; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 20px; }
.form-grid > * { min-width: 0; }
.capability-section { border: 1px solid var(--policy-border); border-radius: 6px; padding: 20px; margin-top: 20px; }
.connection-controls { display: flex; flex-wrap: wrap; gap: 8px; }
.connection-controls > .ant-input { flex: 1 1 280px; min-width: 0; }
.sandbox-test-result { margin-bottom: 16px; overflow-wrap: anywhere; }
.bottom-action-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; background: #fff; border-top: 1px solid var(--policy-border); margin-top: 24px; padding: 16px 0; }
@media (max-width: 760px) {
  .classification-overview, .form-grid { grid-template-columns: 1fr; }
  .classification-group + .classification-group { border-left: 0; border-top: 1px solid var(--policy-border); }
  .policy-summary, .capability-section { padding: 16px; }
  .policy-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .policy-table, .policy-table tbody, .policy-table tr, .policy-table th, .policy-table td { display: block; width: 100%; }
  .policy-table th:first-child { width: 100%; padding: 12px 0 4px; border: 0; }
  .policy-table td { padding: 6px 0 14px; }
  .policy-page :deep(.ant-collapse-content-box) { padding: 12px; }
}
</style>
