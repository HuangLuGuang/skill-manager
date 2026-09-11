<template>
  <div class="policy-simulator-trigger">
    <a-tooltip :title="t('policySimulation.entryHint')">
      <a-button html-type="button" @click="opened = true">{{ t('policySimulation.open') }}</a-button>
    </a-tooltip>
    <a-modal v-model:open="opened" class="policy-simulator" :title="t('policySimulation.title')" width="min(1120px, calc(100vw - 32px))" centered :body-style="{ maxHeight: 'calc(100dvh - 180px)', overflowY: 'auto', paddingRight: '4px' }">
      <template #footer>
        <a-button html-type="button" @click="opened = false">{{ t('policySimulation.close') }}</a-button>
      </template>
      <p class="sim-context">{{ t('policySimulation.entryHint') }}</p>
      <p class="sim-intro">{{ t('policySimulation.subtitle') }}</p>
      <p class="sim-hint">{{ t('policySimulation.scope') }}</p>
      <div class="sim-examples">
        <span>{{ t('policySimulation.examples') }}</span>
        <a-button html-type="button" size="small" @click="loadExample('dynamic_execution')">{{ t('policySimulation.contextualExample') }}</a-button>
        <a-button html-type="button" size="small" @click="loadExample('data_exfiltration')">{{ t('policySimulation.blockingExample') }}</a-button>
      </div>
      <p class="sim-hint">{{ t('policySimulation.exampleHint') }}</p>
      <div class="sim-layout">
        <section class="sim-inputs">
          <h3>{{ t('policySimulation.inputs') }}</h3>
          <div v-for="source in toolSources" :key="source" class="sim-analyzer" :data-source="source">
            <div class="sim-analyzer-heading">
              <h4>{{ sourceLabel(source) }}</h4>
              <a-select v-model:value="inputs[source].status" :aria-label="t('policySimulation.statusFor', { source: sourceLabel(source) })" :options="statusOptions" />
            </div>
            <template v-if="inputs[source].status === 'completed'">
              <div v-for="(finding, index) in inputs[source].findings" :key="index" class="sim-finding">
                <label class="sim-field">
                  <span>{{ t('policySimulation.findingType') }}</span>
                  <a-select v-model:value="finding.kind" :aria-label="t('policySimulation.findingFor', { source: sourceLabel(source), index: index + 1 })" :options="findingOptions" />
                </label>
                <label class="sim-field">
                  <span>{{ t('policySimulation.findingSeverity') }}</span>
                  <a-select v-model:value="finding.severity" :aria-label="t('policySimulation.severityFor', { source: sourceLabel(source), index: index + 1 })" :options="severityOptions" />
                </label>
                <a-button html-type="button" type="text" :aria-label="t('policySimulation.removeFor', { source: sourceLabel(source), index: index + 1 })" @click="inputs[source].findings.splice(index, 1)">{{ t('policySimulation.remove') }}</a-button>
              </div>
              <p v-if="!inputs[source].findings.length" class="sim-hint">{{ t('policySimulation.empty') }}</p>
              <a-button html-type="button" size="small" :disabled="inputs[source].findings.length >= 10" @click="inputs[source].findings.push({ kind: 'network', severity: 'MEDIUM' })">{{ t('policySimulation.add') }}</a-button>
            </template>
            <p v-else class="sim-hint">{{ t('policySimulation.inactive') }}</p>
          </div>
          <div class="sim-analyzer" data-source="llm">
            <div class="sim-analyzer-heading">
              <h4>{{ sourceLabel('llm') }}</h4>
              <a-select v-model:value="inputs.llm.status" :aria-label="t('policySimulation.statusFor', { source: sourceLabel('llm') })" :options="statusOptions" />
            </div>
            <label v-if="inputs.llm.status === 'completed'" class="sim-field">
              <span>{{ t('policySimulation.llmRisk') }}</span>
              <a-select v-model:value="inputs.llm.risk" :aria-label="t('policySimulation.llmRisk')" :options="riskOptions" />
            </label>
            <p v-else class="sim-hint">{{ t('policySimulation.inactive') }}</p>
          </div>
          <label v-if="policy.blocked_permissions.length" class="sim-field sim-permissions">
            <span>{{ t('policySimulation.permissions') }}</span>
            <a-select v-model:value="inputs.declared_permissions" mode="multiple" :aria-label="t('policySimulation.permissions')" :placeholder="t('policySimulation.permissionsPlaceholder')" :options="permissionOptions" />
            <span class="sim-hint">{{ t('policySimulation.permissionsHint') }}</span>
          </label>
        </section>
        <section ref="outputElement" class="sim-output" :aria-busy="pending" :style="{ minHeight: pending ? pendingHeight + 'px' : undefined }">
          <h3>{{ t('policySimulation.results') }}</h3>
          <label class="sim-field sim-mode">
            <span>{{ t('policySimulation.draftMode') }}</span>
            <a-select :value="policy.judgement_mode" :get-popup-container="trigger => trigger.parentElement" :aria-label="t('policySimulation.draftMode')" @update:value="$emit('update-mode', $event)">
              <a-select-option v-for="option in modeOptions" :key="option.value" :value="option.value">
                <a-tag :color="option.color" style="margin-inline-end: 0; white-space: normal">{{ option.label }}</a-tag>
              </a-select-option>
            </a-select>
            <span class="sim-hint">{{ t('policySimulation.modeHint') }}</span>
          </label>
          <p v-if="pending" role="status" class="sim-pending">{{ t('policySimulation.calculating') }}</p>
          <a-alert v-else-if="failed" type="error" show-icon :message="t('policySimulation.error')">
            <template #action><a-button html-type="button" @click="scheduleCalculation">{{ t('policySimulation.retry') }}</a-button></template>
          </a-alert>
          <template v-else-if="result">
            <a-alert v-if="result.coverage !== 'complete'" class="sim-coverage" :type="result.coverage === 'none' ? 'warning' : 'info'" show-icon :message="t('policySimulation.' + result.coverage)" />
            <div class="sim-verdicts" aria-live="polite">
              <div class="sim-verdict" :class="result.final_risk">
                <span>{{ t('policySimulation.finalRisk') }}</span>
                <strong data-testid="simulation-risk">{{ riskLabel(result.final_risk) }}</strong>
              </div>
              <div class="sim-verdict" :class="result.admission_status">
                <span>{{ t('policySimulation.admission') }}</span>
                <strong data-testid="simulation-action">{{ actionLabel(result.admission_status) }}</strong>
              </div>
            </div>
            <h4 class="sim-path-title">{{ t('policySimulation.path') }}</h4>
            <ol class="sim-path">
              <li>
                <h4>{{ t('policySimulation.classificationStep') }}</h4>
                <p>{{ t('policySimulation.counts', result.counts) }}</p>
                <ul v-if="result.findings.length" class="sim-classifications">
                  <li v-for="finding in result.findings" :key="finding.id">
                    <span>{{ sourceLabel(finding.source) }} · {{ t('policySettings.findings.' + finding.kind) }} · {{ t('policySimulation.severity.' + finding.severity) }}</span>
                    <span class="sim-classification" :class="finding.classification">→ {{ t('policySettings.groups.' + finding.classification) }}</span>
                  </li>
                </ul>
                <p v-else class="sim-hint">{{ t('policySimulation.noFindings') }}</p>
              </li>
              <li>
                <h4>{{ t('policySimulation.toolStep') }}</h4>
                <p>{{ t('policySimulation.toolConclusion', { mode: t('policySettings.modes.' + result.judgement_mode), risk: riskLabel(result.tool_risk) }) }}</p>
                <p class="sim-hint">{{ t('policySimulation.toolReasons.' + result.tool_reason) }}</p>
                <p v-if="result.tool_reason === 'risk'" class="sim-hint">{{ t('policySettings.modeHints.' + result.judgement_mode) }}</p>
              </li>
              <li>
                <h4>{{ t('policySimulation.llmStep') }}</h4>
                <p v-if="result.llm_risk">{{ t('policySimulation.llmConclusion', { risk: riskLabel(result.llm_risk) }) }}</p>
                <p class="sim-hint">{{ t('policySimulation.llmReasons.' + result.llm_reason) }}</p>
              </li>
              <li>
                <h4>{{ t('policySimulation.admissionStep') }}</h4>
                <p>{{ result.admission_reason === 'blocked_permission' ? t('policySimulation.permissionReason') : t('policySimulation.actionReason', { risk: riskLabel(result.final_risk), action: actionLabel(result.admission_status) }) }}</p>
              </li>
            </ol>
            <p class="sim-sandbox-note">{{ t(result.sandbox_required ? 'policySimulation.sandboxRequired' : 'policySimulation.sandboxOptional', { risk: riskLabel(result.interim_risk) }) }}</p>
            <a-alert v-if="result.sandbox_required && result.analyzer_states.sandbox !== 'completed'" type="warning" show-icon :message="t('policySimulation.sandboxMissing')" />
          </template>
        </section>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { simulatePolicy } from '../api'
import { defaultRiskClassification, policyRisks } from '../utils/policySettings'

const props = defineProps({ policy: { type: Object, required: true } })
defineEmits(['update-mode'])
const { t } = useI18n()
const opened = ref(false)
const toolSources = ['rules', 'deep', 'sandbox']
const sourceLabel = source => t('policySimulation.sources.' + source)
const riskLabel = risk => t('policySettings.risks.' + risk)
const actionLabel = action => t('policySettings.actions.' + action)
const options = (values, prefix) => values.map(value => ({ value, label: t(prefix + value) }))
const statusOptions = computed(() => options(['completed', 'disabled', 'skipped', 'unavailable', 'failed'], 'policySimulation.statuses.'))
const findingOptions = computed(() => options(Object.keys(defaultRiskClassification), 'policySettings.findings.'))
const severityOptions = computed(() => options(['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'], 'policySimulation.severity.'))
const riskOptions = computed(() => options(policyRisks, 'policySettings.risks.'))
const modeOptions = computed(() => options(['permissive', 'balanced', 'strict'], 'policySettings.modes.').map(option => ({ ...option, color: { permissive: 'green', balanced: 'blue', strict: 'volcano' }[option.value] })))
const permissionOptions = computed(() => props.policy.blocked_permissions.map(value => ({ value, label: value })))
const example = kind => ({
  rules: { status: 'completed', findings: [{ kind, severity: kind === 'data_exfiltration' ? 'HIGH' : 'MEDIUM' }] },
  deep: { status: 'completed', findings: [] },
  sandbox: { status: 'completed', findings: [] },
  llm: { status: 'completed', risk: 'benign' },
  declared_permissions: [],
})
const inputs = reactive(example('dynamic_execution'))
const loadExample = kind => Object.assign(inputs, example(kind))
const result = ref(null)
const outputElement = ref(null)
const pendingHeight = ref(0)
const pending = ref(false)
const failed = ref(false)
let timer
let generation = 0
let controller

const scheduleCalculation = () => {
  clearTimeout(timer)
  controller?.abort()
  const current = ++generation
  pendingHeight.value = outputElement.value?.getBoundingClientRect().height || 0
  result.value = null
  failed.value = false
  pending.value = opened.value
  if (!pending.value) return
  const body = JSON.parse(JSON.stringify({ policy: props.policy, ...inputs }))
  timer = setTimeout(async () => {
    controller = new AbortController()
    try {
      const response = await simulatePolicy(body, controller.signal)
      if (current === generation) result.value = response
    } catch {
      if (current === generation) failed.value = true
    } finally {
      if (current === generation) pending.value = false
    }
  }, 350)
}
watch(() => props.policy.blocked_permissions, permissions => {
  inputs.declared_permissions = inputs.declared_permissions.filter(value => permissions.includes(value))
}, { deep: true })
watch([inputs, () => props.policy, opened], scheduleCalculation, { deep: true, flush: 'sync' })
onBeforeUnmount(() => { ++generation; clearTimeout(timer); controller?.abort() })
</script>

<style scoped>
.sim-context { color: #2459ad; background: #f0f5fc; padding: 10px 12px; border-radius: 6px; font-size: 13px; }
:global(.policy-simulator .ant-select-single), :global(.policy-simulator .ant-select-single .ant-select-selector) { height: auto; min-height: 32px; }
:global(.policy-simulator .ant-select-selection-item) { white-space: normal; overflow-wrap: anywhere; }
:global(.policy-simulator .ant-btn) { height: auto; min-height: 32px; white-space: normal; }
.sim-intro { color: #1f2937; font-weight: 500; }
.sim-hint { color: #637083; font-size: 13px; line-height: 1.65; margin: 6px 0; overflow-wrap: anywhere; }
.sim-examples { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.sim-examples > span { font-size: 13px; color: #637083; }
.sim-examples :deep(.ant-btn) { height: auto; white-space: normal; text-align: left; }
.sim-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 24px; margin-top: 20px; }
.sim-layout h3 { font-size: 16px; color: #1f2937; margin: 0 0 16px; }
.sim-layout h4 { font-size: 14px; color: #1f2937; margin: 0; }
.sim-analyzer { background: #fff; padding: 14px; border: 1px solid #e5e9ef; border-radius: 8px; margin-bottom: 12px; }
.sim-analyzer-heading { display: grid; grid-template-columns: minmax(0, 1fr) 145px; align-items: center; gap: 12px; margin-bottom: 12px; }
.sim-analyzer-heading h4 { overflow-wrap: anywhere; }
.sim-finding { display: grid; grid-template-columns: minmax(0, 1fr) 112px auto; align-items: start; gap: 6px; margin-bottom: 10px; }
.sim-finding > .ant-btn { margin-top: 26px; }
.sim-finding > .sim-field { min-width: 0; }
.sim-finding .sim-field > span { color: #637083; font-size: 12px; }
.sim-field > .ant-select { width: 100%; min-width: 0; }
.sim-field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.sim-permissions { margin-top: 18px; }
.sim-output { min-width: 0; background: #fff; border: 1px solid #e5e9ef; border-radius: 8px; padding: 18px; align-self: start; }
.sim-mode { position: relative; padding-bottom: 12px; margin-bottom: 16px; border-bottom: 1px solid #e5e9ef; }
.sim-pending { color: #637083; padding: 24px 0; }
.sim-coverage { margin-bottom: 14px; }
.sim-verdicts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.sim-verdict { border: 1px solid #e5e9ef; border-radius: 7px; padding: 12px; background: #f6f8fb; }
.sim-verdict span { display: block; color: #637083; font-size: 12px; margin-bottom: 8px; }
.sim-verdict strong { font-size: 19px; line-height: 1.4; overflow-wrap: anywhere; }
.sim-verdict.benign, .sim-verdict.APPROVED { color: #23744b; background: #f1faf5; }
.sim-verdict.suspicious, .sim-verdict.VETTED { color: #a65d0a; background: #fff9ef; }
.sim-verdict.malicious, .sim-verdict.REJECTED { color: #b13232; background: #fff4f3; }
.sim-layout .sim-path-title { margin: 22px 0 16px; }
.sim-path { list-style: none; counter-reset: stage; padding: 0; margin: 0; }
.sim-path > li { counter-increment: stage; position: relative; margin-left: 11px; padding: 0 0 18px 26px; border-left: 1px solid #d6e2f2; }
.sim-path > li:last-child { border-color: transparent; padding-bottom: 0; }
.sim-path > li::before { content: counter(stage); position: absolute; left: -12px; top: -1px; width: 23px; height: 23px; border-radius: 50%; background: #eaf1fb; color: #2459ad; text-align: center; line-height: 23px; font-size: 12px; font-weight: 600; }
.sim-path p { margin: 7px 0 0; font-size: 13px; line-height: 1.65; }
.sim-classifications { list-style: none; margin: 8px 0; padding: 0; }
.sim-classifications li { padding: 7px 9px; border-radius: 4px; margin-bottom: 5px; background: #f6f8fb; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.sim-classification { display: block; color: #637083; }
.sim-classification.blocking { color: #b13232; }
.sim-classification.risk { color: #a65d0a; }
.sim-sandbox-note { padding: 12px 0 0; border-top: 1px solid #e5e9ef; margin-top: 18px; font-size: 12px; color: #637083; line-height: 1.65; }
@media (max-width: 1100px) { .sim-layout { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 480px) {
  .sim-output, .sim-analyzer { padding: 12px; }
  .sim-finding { grid-template-columns: minmax(0, 1fr) 84px; }
  .sim-finding > .sim-field:first-child { grid-column: 1 / -1; }
  .sim-verdicts { grid-template-columns: minmax(0, 1fr); }
  .sim-analyzer-heading { gap: 6px; grid-template-columns: minmax(0, 1fr) 128px; }
}
</style>
