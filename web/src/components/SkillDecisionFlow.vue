<template>
  <section class="decision-flow" aria-labelledby="decision-title">
    <header class="decision-header">
      <div><h2 id="decision-title">{{ t('decisionFlow.title') }}</h2><p>{{ t('decisionFlow.subtitle') }}</p></div>
      <span class="scan-time">{{ report.timestamp || '' }}</span>
    </header>
    <div v-if="reconciliation" class="decision-grid">
      <div class="signal-column">
        <h3>{{ t('decisionFlow.signals') }}</h3>
        <button v-for="node in nodes" :key="node.target" class="signal" :class="node.state" @click="$emit('navigate', node.target)">
          <span class="signal-heading"><strong>{{ t(`decisionFlow.${node.label}`) }}</strong><span class="state-dot">{{ t(`decisionFlow.${node.state}`) }}</span></span>
          <span class="signal-summary">{{ node.summary }}</span>
          <span class="node-link">{{ t(`decisionFlow.${node.link}`) }} <span aria-hidden="true">→</span></span>
        </button>
      </div>
      <div class="policy-column">
        <h3>{{ t('decisionFlow.policy') }}</h3>
        <div class="policy-node">
          <span class="eyebrow">{{ t('decisionFlow.tool') }}</span><strong class="tool-risk">{{ risk(reconciliation.pre_llm_risk_level) }}</strong>
          <div class="policy-divider"></div>
          <h4>{{ t(blocking.length ? 'decisionFlow.configured' : 'decisionFlow.classified') }}</h4>
          <div class="category-tags"><span v-for="key in categories" :key="key">{{ te(`decisionFlow.${key}`) ? t(`decisionFlow.${key}`) : key }}</span></div>
          <p class="decision-reason">{{ t(`decisionFlow.${reason}`, { count: classification.blocking_count || 0 }) }}</p>
          <p class="mode">{{ t('decisionFlow.mode') }} <b>{{ reconciliation.judgement_mode || t('decisionFlow.unknown') }}</b></p>
          <div class="policy-links">
            <a :href="configLink('blocking')" target="_blank" rel="noopener">{{ t('decisionFlow.config') }} ↗</a>
            <a :href="configLink('mode')" target="_blank" rel="noopener">{{ t('decisionFlow.modeConfig') }} ↗</a>
          </div>
        </div>
      </div>
      <div class="final-column">
        <h3>{{ t('decisionFlow.final') }}</h3>
        <div class="final-node" :class="reconciliation.final_risk_level">
          <span class="verdict-mark" aria-hidden="true">{{ reconciliation.final_risk_level === 'benign' ? '✓' : '!' }}</span>
          <strong>{{ risk(reconciliation.final_risk_level) }}</strong>
          <p>{{ t('decisionFlow.riskNote') }}</p>
          <button v-if="blocking.length" class="evidence-button" @click="expanded = !expanded" :aria-expanded="expanded">{{ t('decisionFlow.evidence') }} · {{ blocking.length }} {{ expanded ? '−' : '+' }}</button>
        </div>
      </div>
    </div>
    <p v-else>{{ t('decisionFlow.missing') }}</p>
    <div v-if="expanded" class="evidence-panel">
      <div v-for="(item, index) in blocking" :key="index" class="evidence-row">
        <b>{{ item.rule_id || item.rule || '—' }}</b>
        <button @click="$emit('navigate', findingTarget(item))">{{ item.file_path || item.file || '—' }}{{ item.line_number || item.line ? `:${item.line_number || item.line}` : '' }}</button>
        <code>{{ item.evidence || item.snippet || item.title || '—' }}</code>
        <span>{{ t('decisionFlow.retained') }}</span>
      </div>
      <div v-if="report.llm_analysis?.downgrade_reason" class="llm-opinion"><strong>{{ t('decisionFlow.llmOpinion') }}</strong><p>{{ report.llm_analysis.downgrade_reason }}</p></div>
    </div>
    <footer :class="{ changed: changed === true }">{{ t(`decisionFlow.${!reconciliation?.policy_snapshot ? 'historical' : policyFailed ? 'configUnavailable' : changed ? 'changed' : 'snapshot'}`) }}</footer>
  </section>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { getPolicy } from '../api'
import { analysisState, decisionConfigChanged, decisionReason } from '../utils/decisionFlow'
const props = defineProps({ report: { type: Object, required: true } })
defineEmits(['navigate'])
const { t, te } = useI18n()
const router = useRouter()
const policy = ref(null)
const policyFailed = ref(false)
const expanded = ref(false)
onMounted(async () => { try { policy.value = (await getPolicy()).policy } catch { policyFailed.value = true } })
const reconciliation = computed(() => props.report.risk_reconciliation)
const classification = computed(() => props.report.risk_classification || {})
const blocking = computed(() => (classification.value.items || []).filter(item => item.classification === 'blocking'))
const categories = computed(() => [...new Set(blocking.value.map(item => item.classification_key).filter(Boolean))])
const reason = computed(() => decisionReason(props.report))
const findingTarget = item => {
  const source = String(item.source || item.analyzer || '').toLowerCase()
  return source.includes('sandbox') ? 'sandbox' : source.includes('skillspector') ? 'skillspector' : 'rule'
}
const changed = computed(() => decisionConfigChanged(reconciliation.value?.policy_snapshot, policy.value))
const risk = value => te(`decisionFlow.${value}`) ? t(`decisionFlow.${value}`) : value || t('decisionFlow.unknown')
const configLink = focus => router.resolve({ path: '/policy', query: { tab: 'decision', focus, categories: categories.value.join(',') } }).href
const nodes = computed(() => {
  const r = props.report
  const ruleItems = (classification.value.items || []).filter(item => !/sandbox|skillspector/.test(String(item.source || item.analyzer || '').toLowerCase()))
  const counts = Object.fromEntries(['blocking', 'risk', 'noise'].map(key => [key, ruleItems.filter(item => item.classification === key).length]))
  return [
    { label: 'rule', target: 'rule', key: 'scanner', summary: t('decisionFlow.counts', counts), link: 'results' },
    { label: 'deep', target: 'skillspector', key: 'skillspector', summary: r.skillspector_analysis?.risk_severity || r.skillspector_analysis?.max_severity || r.skillspector_analysis?.risk_level || '—', link: 'results' },
    { label: 'sandbox', target: 'sandbox', key: 'sandbox', summary: r.sandbox_analysis?.reason_code === 'no_executable_script' ? t('decisionFlow.noScript') : r.sandbox_analysis?.risk_level ? risk(r.sandbox_analysis.risk_level.toLowerCase()) : t('decisionFlow.skippedHint'), link: 'details' },
    { label: 'llm', target: 'llm', key: 'llm', summary: risk(reconciliation.value?.llm_risk_level), link: 'report' },
  ].map(node => {
    const state = analysisState(r, node.key)
    return { ...node, state, summary: state === 'failed' ? t('decisionFlow.failedHint') : ['disabled', 'unrecorded', 'pending'].includes(state) ? t(`decisionFlow.${state}`) : node.summary }
  })
})
</script>
<style scoped>
.decision-flow { --ink:#24344d; --muted:#69788d; --line:#dce5ef; margin-top:16px; border:1px solid var(--line); border-radius:14px; background:#fff; color:var(--ink); overflow:hidden; }
.decision-header { display:flex; justify-content:space-between; gap:16px; padding:22px 26px; border-bottom:1px solid #edf1f6; align-items:center; }
h2 { font-size:19px; font-weight:650; margin:0 0 5px; letter-spacing:.02em; }
.decision-header p { color:var(--muted); margin:0; font-size:13px; }.scan-time { font:11px ui-monospace,monospace; color:var(--muted); overflow-wrap:anywhere; }
.decision-grid { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(0,1.1fr) minmax(0,.8fr); gap:38px; padding:24px 26px; background:#f8fafd; }
h3 { margin:0 0 14px; font-size:12px; font-weight:600; color:var(--muted); letter-spacing:.06em; }
.signal { display:flex; flex-direction:column; width:100%; text-align:left; border:1px solid var(--line); border-radius:9px; background:#fff; padding:13px 15px; margin-bottom:10px; cursor:pointer; gap:7px; color:var(--ink); transition:border-color .15s; }.signal:hover { border-color:#547ba7; }.signal-heading { display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; }.state-dot { font-size:11px; color:#547365; }.failed .state-dot { color:#bf463f; }.skipped .state-dot,.unrecorded .state-dot { color:var(--muted); }.signal-summary { font-size:12px; overflow-wrap:anywhere; }.node-link { color:#386caa; font-size:12px; }.policy-column,.final-column { position:relative; }.policy-column::before,.final-column::before { content:'→'; position:absolute; left:-29px; top:49%; color:#8297b0; font-size:23px; }
.policy-node { background:#fffdf7; border:1px solid #e9d9ae; border-top:3px solid #c49a46; border-radius:10px; padding:22px; }.eyebrow { font-size:12px; color:var(--muted); display:block; }.tool-risk { display:block; margin-top:8px; font-size:17px; }.policy-divider { height:1px; background:#ede2c9; margin:18px 0; }h4 { font-size:16px; line-height:1.6; margin:0 0 12px; }.category-tags { display:flex; flex-wrap:wrap; gap:6px; }.category-tags span { background:#f4ead5; color:#805b24; padding:3px 9px; font-size:12px; border-radius:4px; }.decision-reason { margin:16px 0; line-height:1.8; font-size:14px; }.mode { font-size:12px; color:var(--muted); }.mode b { display:block; color:var(--ink); font-family:ui-monospace,monospace; margin-top:5px; }.policy-links { display:flex; flex-direction:column; gap:12px; font-size:12px; margin-top:22px; }
.final-node { border:1px solid var(--line); border-radius:10px; padding:26px 20px; text-align:center; background:white; }.final-node.malicious { background:#fff6f5; border-color:#eacac7; }.final-node.benign { background:#f3faf6; border-color:#c7dfcf; }.verdict-mark { display:flex; align-items:center; justify-content:center; margin:0 auto 18px; width:42px; height:42px; border:1px solid currentColor; border-radius:50%; font-size:24px; }.malicious .verdict-mark { color:#b64b43; }.benign .verdict-mark { color:#3c8560; }.final-node strong { display:block; font-size:20px; overflow-wrap:anywhere; }.final-node p { font-size:12px; color:var(--muted); line-height:1.8; margin:16px 0; }.evidence-button { background:#fff; border:1px solid #dccbc8; border-radius:6px; padding:8px 12px; cursor:pointer; color:inherit; max-width:100%; }
footer { padding:13px 26px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); line-height:1.7; }footer.changed { color:#8e601a; background:#fffbe9; }.evidence-panel { padding:8px 26px 20px; }.evidence-row { display:grid; grid-template-columns:60px 1fr 1fr auto; gap:12px; padding:14px 0; border-bottom:1px solid var(--line); align-items:center; font-size:12px; }.evidence-row button { text-align:left; background:none; border:0; color:#386caa; cursor:pointer; }.evidence-row code { overflow-wrap:anywhere; white-space:pre-wrap; }.evidence-row span { color:#a24c44; }.llm-opinion { padding:16px; background:#f5f8fc; margin-top:16px; border-radius:8px; font-size:13px; }.llm-opinion p { margin:8px 0 0; line-height:1.8; white-space:pre-wrap; }
button:focus-visible,a:focus-visible { outline:2px solid #386caa; outline-offset:3px; }
@media(max-width:1000px) { .decision-grid { gap:26px; padding:20px; }.policy-node { padding:16px; }.policy-column::before,.final-column::before { left:-22px; font-size:18px; } }
@media(max-width:760px) { .decision-header { align-items:flex-start; flex-direction:column; padding:18px; }.decision-grid { grid-template-columns:1fr; gap:30px; padding:18px; }.policy-column::before,.final-column::before { content:'↓'; top:-28px; left:50%; }.evidence-row { grid-template-columns:1fr 1fr; }.evidence-panel { padding:8px 18px 18px; }footer { padding:12px 18px; } }
@media(prefers-reduced-motion:reduce) { .signal { transition:none; } }
</style>
