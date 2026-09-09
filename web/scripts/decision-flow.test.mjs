import test from 'node:test'
import assert from 'node:assert/strict'
import { decisionReason, decisionConfigChanged, analysisState } from '../src/utils/decisionFlow.js'
import { decisionFlowMessages } from '../src/i18n/decisionFlow.js'
test('blocking and strict-mode refusals explain different decisions', () => {
  const report = { risk_reconciliation: { llm_downgrade_blocked: true }, risk_classification: { blocking_count: 3 } }
  assert.equal(decisionReason(report), 'blocked')
  report.risk_classification.blocking_count = 0
  assert.equal(decisionReason(report), 'strict')
  assert.equal(decisionReason({ risk_reconciliation: { llm_downgraded: true } }), 'lowered')
  assert.equal(decisionReason({}), 'missing')
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
})
