<template>
  <section class="decision-flow" aria-labelledby="decision-title">
    <header class="decision-header">
      <div><h2 id="decision-title" tabindex="-1">{{ t('decisionFlow.title') }}</h2><p>{{ t('decisionFlow.subtitle') }}</p></div>
      <span v-if="report.timestamp" class="scan-time">{{ formatDateTime(report.timestamp) }}</span>
    </header>
    <div class="decision-context" :class="{ changed: changed === true }">{{ t('decisionFlow.' + contextMessage) }}</div>
    <div class="decision-layout">
      <section class="signal-column">
        <h3>{{ t('decisionFlow.signals') }}</h3>
        <button v-for="node in nodes" :key="node.target" type="button" class="signal" :class="node.state" @click="$emit('navigate', node.target)">
          <span class="signal-heading"><strong>{{ t('decisionFlow.' + node.label) }}</strong><span class="state-label">{{ t('decisionFlow.' + node.state) }}</span></span>
          <span class="signal-summary">{{ node.summary }}</span>
          <span class="node-link">{{ t('decisionFlow.' + node.link) }} <span aria-hidden="true">→</span></span>
        </button>
        <p class="muted signal-note">{{ t('decisionFlow.signalHint') }}</p>
      </section>
      <section class="decision-output">
        <h3>{{ t('decisionFlow.outcome') }}</h3>
        <div class="decision-verdicts">
          <div class="decision-verdict" :class="decision.finalRisk">
            <span>{{ t('decisionFlow.final') }}</span>
            <strong data-testid="detail-decision-risk">{{ risk(decision.finalRisk) }}</strong>
          </div>
          <div class="decision-verdict" :class="status">
            <span>{{ t('decisionFlow.admission') }}</span>
            <strong data-testid="detail-decision-status">{{ statusLabel }}</strong>
          </div>
        </div>
        <aside v-if="llmDisagreement" class="llm-disagreement" :aria-label="t('decisionFlow.llmDisagreementTitle')">
          <strong>{{ t(llmDisagreement === 'unrecorded' ? 'decisionFlow.llmDisagreementTitle' : 'decisionFlow.llmDowngradeNotAdopted') }}</strong>
          <p class="llm-risk-comparison">{{ t('decisionFlow.llmRiskComparison', { tool: risk(decision.toolRisk), llm: risk(decision.llmRisk), final: risk(decision.finalRisk) }) }}</p>
          <p>{{ t(`decisionFlow.llmNotAdopted_${llmDisagreement}`, { count: displayCounts.blocking }) }}</p>
          <div class="llm-disagreement-actions">
            <button v-if="llmDisagreement === 'blocked' && retainedFindings.length" type="button" class="text-link" @click="showRetainedFindings">{{ t('decisionFlow.viewRetainedFindings') }} →</button>
            <button type="button" class="text-link" @click="$emit('navigate', 'llm')">{{ t('decisionFlow.viewOriginalLlm') }} →</button>
          </div>
        </aside>
        <p class="decision-mode">{{ t('decisionFlow.mode') }} <b>{{ modeLabel }}</b></p>
        <h4 class="path-heading">{{ t('decisionFlow.basis') }}</h4>
        <ol class="decision-path">
          <li>
            <h4>{{ t('decisionFlow.classificationStep') }}</h4>
            <p>{{ t('decisionFlow.counts', displayCounts) }}</p>
            <p v-if="!decision.findings" class="muted">{{ t('decisionFlow.classificationMissing') }}</p>
            <p v-else-if="!decision.findings.length" class="muted">{{ t('decisionFlow.noFindings') }}</p>
            <details v-else ref="findingDetails" class="finding-details">
              <summary>{{ t('decisionFlow.evidence', { count: decision.findings.length }) }}</summary>
              <a-tabs v-model:activeKey="evidenceSource" class="evidence-tabs" size="small" destroy-inactive-tab-pane @change="evidencePage = 1">
                <a-tab-pane v-for="source in evidenceSources" :key="source.key" :tab="`${t('decisionFlow.' + source.label)} (${source.items.length})`">
                  <ul v-if="filteredEvidence.length" class="classified-findings" aria-live="polite">
                    <li v-for="(item, index) in pagedEvidence" :key="`${evidenceSource}-${evidencePage}-${index}`" tabindex="-1">
                      <div class="finding-evidence">
                        <div class="finding-heading">{{ sourceLabel(item) }} · {{ findingLabel(item) }} · {{ severity(item.severity) }}</div>
                        <button type="button" class="text-link finding-location" @click="$emit('navigate', findingTarget(item))">
                          {{ item.file_path || item.file || t('decisionFlow.results') }}{{ item.line_number || item.line ? `:${item.line_number || item.line}` : '' }} →
                        </button>
                        <pre v-if="evidenceText(item)">{{ evidenceText(item) }}</pre>
                      </div>
                      <div class="finding-decision">
                        <span class="finding-decision-source">{{ findingDecisionSource(item) }}</span>
                        <strong class="finding-class" :class="item.classification">{{ classificationLabel(item.classification) }}</strong>
                        <p>{{ findingImpact(item) }}</p>
                      </div>
                    </li>
                  </ul>
                  <p v-else class="muted evidence-empty">{{ t('decisionFlow.noSourceEvidence') }}</p>
                  <div v-if="filteredEvidence.length" class="evidence-pagination">
                    <span class="muted">{{ t('decisionFlow.evidenceRange', { start: (evidencePage - 1) * evidencePageSize + 1, end: Math.min(evidencePage * evidencePageSize, filteredEvidence.length), total: filteredEvidence.length }) }}</span>
                    <a-pagination
                      v-if="filteredEvidence.length > evidencePageSize"
                      v-model:current="evidencePage"
                      :page-size="evidencePageSize"
                      :total="filteredEvidence.length"
                      :show-size-changer="false"
                      :aria-label="t('decisionFlow.evidencePagination')"
                      size="small"
                      simple
                    />
                  </div>
                </a-tab-pane>
              </a-tabs>
            </details>
            <a class="config-link" :href="configLink('classification')" target="_blank" rel="noopener">{{ t('decisionFlow.config') }} ↗</a>
          </li>
          <li>
            <h4>{{ t('decisionFlow.toolStep') }}</h4>
            <p>{{ t('decisionFlow.toolConclusion', { risk: risk(decision.toolRisk) }) }}</p>
            <p class="muted">{{ t('decisionFlow.' + toolReason) }}</p>
            <a class="config-link" :href="configLink('mode')" target="_blank" rel="noopener">{{ t('decisionFlow.modeConfig') }} ↗</a>
          </li>
          <li>
            <h4>{{ t('decisionFlow.llmStep') }}</h4>
            <p v-if="decision.llmRisk">{{ t('decisionFlow.llmConclusion', { risk: risk(decision.llmRisk) }) }}</p>
            <p class="muted">{{ t('decisionFlow.' + reason, { count: displayCounts.blocking }) }}</p>
            <details v-if="llmOpinion || dismissedFindings.length" class="llm-opinion">
              <summary>{{ t('decisionFlow.llmOpinion') }}</summary>
              <p v-if="llmOpinion">{{ llmOpinion }}</p>
              <template v-if="dismissedFindings.length">
                <h5>{{ t('decisionFlow.dismissedFindings') }}</h5>
                <ul class="dismissed-findings">
                  <li v-for="(finding, index) in dismissedFindings" :key="index">{{ finding }}</li>
                </ul>
              </template>
            </details>
          </li>
          <li>
            <h4>{{ t('decisionFlow.admissionStep') }}</h4>
            <p>{{ t('decisionFlow.statusConclusion', { status: statusLabel }) }}</p>
            <p class="muted">{{ t('decisionFlow.statusHint') }}</p>
          </li>
          <li v-if="policyNotices.length" class="policy-notices">
            <h4>{{ t('decisionFlow.policyNoticesTitle') }}</h4>
            <p class="muted">{{ t('decisionFlow.policyNoticesHint') }}</p>
            <ul>
              <li v-for="(notice, index) in policyNotices" :key="index">{{ policyNoticeText(notice) }}</li>
            </ul>
          </li>
        </ol>
      </section>
    </div>
    <a-alert v-if="toolDeclarationNotices.length" class="declaration-notices" type="warning" show-icon :message="t('decisionFlow.declarationNoticesTitle')">
      <template #description>
        <p v-for="(notice, index) in toolDeclarationNotices" :key="index">{{ policyNoticeText(notice) }}</p>
      </template>
    </a-alert>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { getPolicy } from '../api'
import { translateDomain } from '../i18n'
import { formatDateTime } from '../utils/format'
import { analysisState, decisionConfigChanged, decisionReason, findingTarget, llmRiskDisagreement, recordedDecision } from '../utils/decisionFlow'
const props = defineProps({ report: { type: Object, required: true }, status: { type: String, default: '' } })
defineEmits(['navigate'])
const { t, te } = useI18n()
const router = useRouter()
const policy = ref(null)
const policyFailed = ref(false)
onMounted(async () => { try { policy.value = (await getPolicy()).policy } catch { policyFailed.value = true } })
const reconciliation = computed(() => props.report.risk_reconciliation)
const decision = computed(() => recordedDecision(props.report))
// 准入提示使用本次扫描参数，与规则发现项分别展示。
const declarationRules = ['tool_not_in_allowlist', 'max_allowed_tools']
const policyNotices = computed(() => (props.report.policy_warnings || []).filter(notice => !declarationRules.includes(notice.rule)))
const toolDeclarationNotices = computed(() => (props.report.policy_warnings || []).filter(notice => declarationRules.includes(notice.rule)))
const policyNoticeText = notice => {
  if (notice.rule === 'max_allowed_tools' && notice.params?.count != null && notice.params?.limit != null) {
    return t('decisionFlow.toolCountExceeded', { count: notice.params.count, limit: notice.params.limit })
  }
  if (notice.rule === 'tool_not_in_allowlist' && typeof notice.params?.tool === 'string') {
    const allowed = notice.params.allowed_tools_allowlist
    return t('decisionFlow.toolNotInAllowlist', {
      tool: notice.params.tool,
      allowed: Array.isArray(allowed) ? allowed.join(', ') || t('decisionFlow.noAllowedTools') : t('decisionFlow.unrecorded'),
    })
  }
  if (notice.rule === 'require_license') return t('decisionFlow.policyNoticeRequireLicense')
  if (notice.rule === 'unaccepted_license') return t('decisionFlow.policyNoticeUnacceptedLicense', {
    license: notice.params.license,
    accepted: notice.params.accepted_licenses.join(', '),
  })
  return notice.message
}
const llmDisagreement = computed(() => llmRiskDisagreement(props.report))
const findingDetails = ref(null)
const retainedFindings = computed(() => (decision.value.findings || []).filter(item => item.classification === 'blocking'))
const evidenceSource = ref('rule')
const evidencePage = ref(1)
const evidencePageSize = 5
const evidenceSources = computed(() => [
  { key: 'rule', label: 'rule' },
  { key: 'skillspector', label: 'deep' },
  { key: 'sandbox', label: 'sandbox' },
].map(source => ({ ...source, items: (decision.value.findings || []).filter(item => findingTarget(item) === source.key) })))
const filteredEvidence = computed(() => evidenceSources.value.find(source => source.key === evidenceSource.value)?.items || [])
const pagedEvidence = computed(() => filteredEvidence.value.slice((evidencePage.value - 1) * evidencePageSize, evidencePage.value * evidencePageSize))
const showRetainedFindings = async () => {
  const first = retainedFindings.value[0]
  if (!first || !findingDetails.value) return
  const source = evidenceSources.value.find(source => source.key === findingTarget(first))
  if (!source) return
  evidenceSource.value = source.key
  findingDetails.value.open = true
  await nextTick()
  evidencePage.value = Math.floor(source.items.indexOf(first) / evidencePageSize) + 1
  await nextTick()
  const row = findingDetails.value.querySelector('.finding-class.blocking')?.closest('li')
  row?.focus({ preventScroll: true })
  row?.scrollIntoView({ block: 'center' })
}
watch(() => props.report, () => {
  evidenceSource.value = evidenceSources.value.find(source => source.items.length)?.key || 'rule'
  evidencePage.value = 1
}, { immediate: true })
const categories = computed(() => [...new Set((decision.value.findings || []).map(item => item.classification_key).filter(Boolean))])
const reason = computed(() => decisionReason(props.report))
const changed = computed(() => decisionConfigChanged(reconciliation.value?.policy_snapshot, policy.value))
const contextMessage = computed(() => !reconciliation.value?.policy_snapshot ? 'historical' : policyFailed.value ? 'configUnavailable' : !policy.value ? 'configLoading' : changed.value ? 'changed' : 'snapshot')
const risk = value => value && te('policySettings.risks.' + value) ? t('policySettings.risks.' + value) : value || t('decisionFlow.unrecorded')
const severity = value => value && te('policySimulation.severity.' + String(value).toUpperCase()) ? t('policySimulation.severity.' + String(value).toUpperCase()) : value || t('decisionFlow.unrecorded')
const statusLabel = computed(() => translateDomain('skillStatus', props.status, t('decisionFlow.unrecorded')))
const modeLabel = computed(() => decision.value.mode && te('policySettings.modes.' + decision.value.mode) ? t('policySettings.modes.' + decision.value.mode) : decision.value.mode || t('decisionFlow.unrecorded'))
const displayCounts = computed(() => Object.fromEntries(Object.entries(decision.value.counts).map(([key, count]) => [key, count ?? '—'])))
const classificationLabel = value => value && te('policySettings.groups.' + value) ? t('policySettings.groups.' + value) : value || t('decisionFlow.unrecorded')
const findingLabel = item => item.classification_key && te('policySettings.findings.' + item.classification_key) ? t('policySettings.findings.' + item.classification_key) : item.rule_id || item.rule || item.category || t('decisionFlow.unrecorded')
const findingDecisionSource = item => {
  const mapping = reconciliation.value?.policy_snapshot?.risk_classification
  return item.classification_key && item.classification && mapping?.[item.classification_key] === item.classification
    ? t('decisionFlow.findingPolicyResult', { finding: findingLabel(item) })
    : t('decisionFlow.findingRecordedResult')
}
const findingImpact = item => item.classification && te(`policySettings.groupHints.${item.classification}`)
  ? t(`policySettings.groupHints.${item.classification}`)
  : t('decisionFlow.findingImpactMissing')
const sourceLabel = item => t('decisionFlow.' + ({ skillspector: 'deep' }[findingTarget(item)] || findingTarget(item)))
const evidenceText = item => item.evidence || item.snippet || item.code_snippet || item.title || item.message || ''
const llmOpinion = computed(() => reconciliation.value?.downgrade_reason || props.report.llm_analysis?.downgrade_reason || '')
const dismissedFindings = computed(() => Array.isArray(reconciliation.value?.dismissed_findings) ? reconciliation.value.dismissed_findings : [])
const toolReason = computed(() => ({ blocking: 'toolBlocking', risk: 'toolContextual', noise: 'toolNotice' }[reconciliation.value?.pre_llm_reason] || 'toolMissing'))
const configLink = focus => router.resolve({ path: '/policy', query: { tab: 'decision', focus: focus === 'classification' ? undefined : focus, categories: categories.value.join(',') } }).href
const nodes = computed(() => {
  const r = props.report
  const sourceSummary = target => {
    if (!decision.value.findings) return t('decisionFlow.classificationMissing')
    const items = decision.value.findings.filter(item => findingTarget(item) === target)
    return t('decisionFlow.counts', Object.fromEntries(['blocking', 'risk', 'noise'].map(key => [key, items.filter(item => item.classification === key).length])))
  }
  return [
    { label: 'rule', target: 'rule', key: 'scanner', summary: sourceSummary('rule'), link: 'results' },
    { label: 'deep', target: 'skillspector', key: 'skillspector', summary: sourceSummary('skillspector'), link: 'results' },
    { label: 'sandbox', target: 'sandbox', key: 'sandbox', summary: sourceSummary('sandbox'), link: 'details' },
    { label: 'llm', target: 'llm', key: 'llm', summary: risk(decision.value.llmRisk), link: 'report' },
  ].map(node => {
    const state = analysisState(r, node.key)
    const summary = state === 'completed' ? node.summary
      : state === 'skipped' && node.target === 'sandbox' && r.sandbox_analysis?.reason_code === 'no_executable_script' ? t('decisionFlow.noScript')
        : t('decisionFlow.' + (['failed', 'unavailable'].includes(state) ? 'failedHint' : state === 'skipped' ? 'skippedHint' : state))
    return { ...node, state, summary }
  })
})
</script>

<style scoped>
.decision-flow { --ink: #1f2937; --muted: #637083; --line: #e5e9ef; border: 1px solid var(--line); border-radius: 8px; background: #f6f8fb; color: var(--ink); overflow: hidden; }
.decision-header { display: flex; justify-content: space-between; gap: 16px; padding: 20px 22px 12px; align-items: center; }
.decision-header h2 { font-size: 17px; font-weight: 600; margin: 0 0 5px; }
.decision-header p { color: var(--muted); margin: 0; font-size: 13px; }
.scan-time { font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
.decision-context { margin: 0 22px; padding: 10px 12px; border-radius: 6px; color: #2459ad; background: #eaf1fb; font-size: 12px; line-height: 1.7; }
.decision-context.changed { color: #996515; background: #fff5df; }
.decision-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; padding: 22px; }
.signal-column { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.signal-column h3, .signal-note { grid-column: 1 / -1; }
.decision-layout h3 { font-size: 16px; margin: 0 0 16px; color: var(--ink); }
.signal-column h3 { margin-bottom: 0; }
.signal { display: flex; flex-direction: column; width: 100%; text-align: left; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 14px; cursor: pointer; gap: 10px; color: var(--ink); }
.signal:hover { border-color: #2459ad; }
.signal-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.signal-heading strong { font-size: 14px; font-weight: 600; }
.state-label { font-size: 12px; color: var(--muted); }
.completed .state-label { color: #23744b; }
.failed .state-label, .unavailable .state-label { color: #b13232; }
.signal-summary { font-size: 13px; overflow-wrap: anywhere; }
.node-link, .config-link { color: #2459ad; font-size: 12px; }
.signal-note { margin: 0; }
.node-link { margin-top: auto; }
.muted { color: var(--muted); font-size: 13px; line-height: 1.7; }
.decision-output { min-width: 0; border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 18px; align-self: start; }
.decision-verdicts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.decision-verdict { border: 1px solid var(--line); border-radius: 7px; padding: 12px; background: #f6f8fb; }
.decision-verdict > span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 8px; }
.decision-verdict strong { font-size: 19px; line-height: 1.4; overflow-wrap: anywhere; }
.decision-verdict.benign, .decision-verdict.APPROVED, .decision-verdict.DEPLOYED { color: #23744b; background: #f1faf5; }
.decision-verdict.suspicious, .decision-verdict.VETTED { color: #a65d0a; background: #fff9ef; }
.decision-verdict.malicious, .decision-verdict.REJECTED { color: #b13232; background: #fff4f3; }
.llm-disagreement { margin-top: 12px; padding: 14px 16px; border: 1px solid #efd6a7; border-radius: 7px; background: #fffbf2; font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.llm-disagreement > strong { color: #8a5313; font-size: 14px; }
.llm-disagreement p { margin: 6px 0 0; }
.llm-risk-comparison { font-weight: 500; }
.llm-disagreement-actions { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-top: 10px; }
.classified-findings > li:focus { outline: 2px solid #2459ad; outline-offset: 2px; }
.decision-mode { display: flex; flex-wrap: wrap; gap: 6px 12px; color: var(--muted); font-size: 13px; margin: 16px 0; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.decision-mode b { color: var(--ink); font-weight: 500; }
.decision-output h4 { font-size: 14px; margin: 0; color: var(--ink); }
.decision-output .path-heading { margin-bottom: 16px; }
.decision-path { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; list-style: none; counter-reset: stage; padding: 0; margin: 0; }
.decision-path > li { min-width: 0; counter-increment: stage; position: relative; padding: 16px 16px 16px 48px; border: 1px solid var(--line); border-radius: 6px; }
.declaration-notices { margin-top: 16px; overflow-wrap: anywhere; }
.declaration-notices p { margin: 0; white-space: pre-wrap; }
.declaration-notices p + p { margin-top: 6px; }
.policy-notices { grid-column: 1 / -1; }
.policy-notices ul { margin: 7px 0 0; padding-left: 20px; font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.decision-path > li:has(details[open]) { grid-column: 1 / -1; }
.decision-path:has(details[open]) > li:last-child { grid-column: 1 / -1; }
.decision-path > li::before { content: counter(stage); position: absolute; left: 14px; top: 15px; width: 23px; height: 23px; border-radius: 50%; background: #eaf1fb; color: #2459ad; text-align: center; line-height: 23px; font-size: 12px; font-weight: 600; }
.decision-path p { margin: 7px 0 0; font-size: 13px; line-height: 1.7; }
.config-link { display: inline-block; margin-top: 8px; }
summary { cursor: pointer; color: #2459ad; font-size: 12px; line-height: 1.6; }
.finding-details, .llm-opinion { margin-top: 10px; }
.finding-details { container-type: inline-size; }
.evidence-tabs { margin-top: 12px; min-width: 0; }
.evidence-tabs :deep(.ant-tabs-nav) { margin-bottom: 0; }
.evidence-tabs :deep(.ant-tabs-tab) { font-size: 12px; }
.evidence-pagination { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px 16px; margin-top: 12px; }
.evidence-empty { padding: 12px 0; }
.classified-findings { list-style: none; margin: 8px 0 0; padding: 0; }
.classified-findings li { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr); gap: 24px; background: #f6f8fb; padding: 14px 16px; margin-bottom: 8px; border-radius: 5px; font-size: 12px; overflow-wrap: anywhere; }
.finding-evidence, .finding-decision { min-width: 0; }
.finding-decision { padding-left: 20px; border-left: 1px solid var(--line); }
.finding-decision-source { color: var(--muted); font-size: 12px; line-height: 1.7; }
.finding-decision p { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.finding-heading { line-height: 1.7; }
.finding-class { display: block; margin-top: 5px; color: var(--muted); font-size: 14px; font-weight: 600; line-height: 1.6; }
.finding-class.blocking { color: #b13232; }
.finding-class.risk { color: #a65d0a; }
.text-link { background: none; border: 0; padding: 0; color: #2459ad; text-align: left; cursor: pointer; }
.finding-location { margin-top: 7px; overflow-wrap: anywhere; max-width: 100%; }
.classified-findings pre { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; font-family: ui-monospace, monospace; }
@container (max-width: 640px) {
  .classified-findings li { grid-template-columns: minmax(0, 1fr); gap: 12px; padding: 12px; }
  .finding-decision { padding: 10px 0 0; border-left: 0; border-top: 1px solid var(--line); }
}
.llm-opinion p { padding: 10px; background: #f6f8fb; border-radius: 5px; white-space: pre-wrap; overflow-wrap: anywhere; }
.llm-opinion h5 { font-size: 13px; margin: 12px 0 8px; }
.dismissed-findings { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.7; }
.dismissed-findings li { margin-top: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid #2459ad; outline-offset: 3px; }
@media (max-width: 1200px) { .signal-column { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 800px) { .decision-path { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 480px) { .decision-header { flex-direction: column; align-items: flex-start; padding: 16px 12px 12px; } .decision-context { margin: 0 12px; } .decision-layout { padding: 16px 12px; gap: 18px; } .signal-column, .decision-verdicts { grid-template-columns: minmax(0, 1fr); } .decision-output { padding: 12px; } }
</style>
