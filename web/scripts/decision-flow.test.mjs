import test from 'node:test'
import assert from 'node:assert/strict'
import { decisionReason, decisionConfigChanged, analysisState, recordedDecision, findingTarget, llmRiskDisagreement } from '../src/utils/decisionFlow.js'
import { baseCompile } from '@intlify/message-compiler'
import { decisionFlowMessages } from '../src/i18n/decisionFlow.js'
test('blocking and strict-mode refusals explain different decisions', () => {
  const report = { risk_reconciliation: { llm_downgrade_blocked: true }, risk_classification: { blocking_count: 3 } }
  assert.equal(decisionReason(report), 'blocked')
  report.risk_classification.blocking_count = 0
  report.risk_reconciliation.judgement_mode = 'strict'
  assert.equal(decisionReason(report), 'strict')
  assert.equal(decisionReason({ risk_reconciliation: { llm_downgraded: true } }), 'lowered')
  assert.equal(decisionReason({}), 'missing')
  assert.equal(decisionReason({ risk_reconciliation: { llm_downgrade_blocked: true } }), 'reconciled')
  assert.equal(decisionReason({ risk_reconciliation: { llm_downgrade_blocked: true }, risk_classification: { items: [{ classification: 'blocking' }] } }), 'blocked')
})
test('historical reports have unknown config comparison and changed classifications are detected', () => {
  const policy = { judgement_mode: 'balanced', risk_classification: { network: 'risk' } }
  assert.equal(decisionConfigChanged(null, policy), null)
  assert.equal(decisionConfigChanged(policy, policy), false)
  assert.equal(decisionConfigChanged(policy, { ...policy, risk_classification: { network: 'blocking' } }), true)
})
test('skipped or failed analysis is never presented as successful', () => {
  assert.equal(analysisState({ analyzer_timings: { sandbox: { status: 'skipped' } } }, 'sandbox'), 'skipped')
  assert.equal(analysisState({ analyzer_timings: { llm: { status: 'failed' } } }, 'llm'), 'failed')
  assert.equal(analysisState({}, 'llm'), 'unrecorded')
})
test('decision translations have matching keys', () => {
  assert.deepEqual(Object.keys(decisionFlowMessages['zh-CN']).sort(), Object.keys(decisionFlowMessages['en-US']).sort())
  for (const [key, zh] of Object.entries(decisionFlowMessages['zh-CN'])) {
    const en = decisionFlowMessages['en-US'][key]
    const parameters = value => [...value.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort()
    assert.deepEqual(parameters(zh), parameters(en), key)
    for (const value of [zh, en]) baseCompile(value, { onError: error => { throw error } })
  }
})

test('agreement and raised risk have different explanations', () => {
  const r = { pre_llm_risk_level: 'suspicious', llm_risk_level: 'suspicious', final_risk_level: 'suspicious' }
  assert.equal(decisionReason({ risk_reconciliation: r }), 'unchanged')
  assert.equal(decisionReason({ risk_reconciliation: { ...r, llm_risk_level: 'malicious', final_risk_level: 'malicious' } }), 'raised')
  assert.equal(decisionReason({ risk_reconciliation: { llm_risk_level: 'benign' } }), 'reconciled')
})

test('historical gaps remain unknown while recorded zero findings stay zero', () => {
  const missing = recordedDecision({})
  assert.equal(missing.finalRisk, null)
  assert.equal(missing.toolRisk, null)
  assert.equal(missing.findings, null)
  assert.deepEqual(missing.counts, { blocking: null, risk: null, noise: null })
  const recorded = recordedDecision({ risk_level: 'suspicious', risk_classification: { items: [] } })
  assert.equal(recorded.finalRisk, 'suspicious')
  assert.deepEqual(recorded.counts, { blocking: 0, risk: 0, noise: 0 })
})

test('recorded reconciliation stays authoritative, including an absent usable LLM conclusion', () => {
  const result = recordedDecision({
    risk_level: 'benign', llm_analysis: { risk_level: 'benign' },
    risk_reconciliation: { final_risk_level: 'malicious', pre_llm_risk_level: 'malicious', llm_risk_level: null, judgement_mode: 'strict' },
    risk_classification: { items: [{ classification: 'blocking' }, { classification: 'noise' }] },
  })
  assert.equal(result.finalRisk, 'malicious')
  assert.equal(result.llmRisk, null)
  assert.equal(result.mode, 'strict')
  assert.deepEqual(result.counts, { blocking: 1, risk: 0, noise: 1 })
})

test('evidence keeps analyzer navigation and unavailable status', () => {
  assert.equal(findingTarget({ source: 'sandbox' }), 'sandbox')
  assert.equal(findingTarget({ analyzer: 'skillspector:cli' }), 'skillspector')
  assert.equal(findingTarget({ source: 'behavioral' }), 'rule')
  assert.equal(findingTarget({ source: 'llm' }), 'llm')
  assert.equal(analysisState({ analyzer_timings: { sandbox: { status: 'unavailable' } } }, 'sandbox'), 'unavailable')
})

test('a lower LLM assessment explains recorded policy refusals and historical gaps', () => {
  const report = {
    risk_classification: { items: [{ classification: 'blocking' }] },
    risk_reconciliation: { pre_llm_risk_level: 'malicious', llm_risk_level: 'benign', final_risk_level: 'malicious', llm_downgrade_blocked: true, judgement_mode: 'balanced' },
  }
  assert.equal(llmRiskDisagreement(report), 'blocked')
  const strict = { ...report, risk_classification: { items: [] }, risk_reconciliation: { ...report.risk_reconciliation, judgement_mode: 'strict' } }
  assert.equal(llmRiskDisagreement(strict), 'strict')
  assert.equal(llmRiskDisagreement({ risk_level: 'malicious', llm_analysis: { risk_level: 'benign' } }), 'unrecorded')
  assert.equal(llmRiskDisagreement({ ...strict, risk_reconciliation: { ...strict.risk_reconciliation, llm_downgrade_blocked: undefined } }), 'unrecorded')
})

test('accepted, agreeing, absent, and higher LLM conclusions do not show a refused downgrade', () => {
  for (const [llm, final] of [['benign', 'benign'], ['malicious', 'malicious'], ['malicious', 'suspicious'], [null, 'malicious'], ['unknown', 'malicious'], ['benign', null]]) {
    assert.equal(llmRiskDisagreement({ risk_reconciliation: { pre_llm_risk_level: 'malicious', llm_risk_level: llm, final_risk_level: final, llm_downgrade_blocked: true } }), null)
  }
})
