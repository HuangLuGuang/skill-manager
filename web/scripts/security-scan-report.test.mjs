import assert from 'node:assert/strict'
import test from 'node:test'

import { parseRedteamArtifact, summarizeCaseCoverage, summarizeRedteamRows } from '../src/securityScanReport.js'

test('summarizes the real red-team result as 8 safe and 2 risks', () => {
  const rows = [...Array(8)].map(() => ({ status: 'Safe' })).concat([...Array(2)].map(() => ({ status: 'Jailbreak' })))
  assert.deepEqual(summarizeRedteamRows(rows), { recorded: 10, safe: 8, risk: 2, evaluated: 10, rate: '20%' })
})

test('keeps agent rule coverage scoped to agent detection cases', () => {
  const summary = summarizeCaseCoverage({ task: { scan_kind: 'agent_risk_scan' }, cases: [
    { category: 'agent_detection_skill', status: 'passed' }, { category: 'agent_detection_skill', status: 'failed' },
    { category: 'agent-dialogue-transcript', status: 'passed' },
  ] })
  assert.equal(summary.planned_cases, 2)
  assert.equal(summary.passed_cases, 1)
  assert.equal(summary.failed_cases, 1)
})

test('normalizes legacy agent artifact coverage fields for the report view', () => {
  const summary = summarizeCaseCoverage({
    task: { scan_kind: 'agent_risk_scan' }, cases: [],
    artifacts: [{ artifact_type: 'aig-agent-scan-report', metadata: { coverage: {
      planned_rules: 10, passed_rules: 8, failed_rules: 0, error_rules: 1, blocked_rules: 0, unverified_rules: 1,
    } } }],
  })
  assert.deepEqual(summary, { planned_cases: 10, passed_cases: 8, failed_cases: 0, error_cases: 1, blocked_cases: 0, unverified_cases: 1 })
})

test('uses recorded case count for partial LLM reports', () => {
  const summary = summarizeCaseCoverage({ task: { scan_kind: 'llm_redteam_scan' }, cases: [{ status: 'passed' }, { status: 'failed' }], artifacts: [{ artifact_type: 'aig-llm-redteam-report', metadata: { planned_cases: 10 } }] })
  assert.equal(summary.planned_cases, 2)
  assert.equal(summary.passed_cases, 1)
  assert.equal(summary.failed_cases, 1)
})

test('parses both wrapped and direct artifact results without changing source text', () => {
  const first = { attackMethod: 'Raw', vulnerability: 'JailBench-Tiny', input: '原始 <prompt>', originalInput: '原始输入', output: '响应', status: 'Jailbreak', reason: '理由' }
  const wrapped = parseRedteamArtifact(JSON.stringify({ content: [{ results: [first] }] }))
  const direct = parseRedteamArtifact(JSON.stringify({ results: [first] }))
  assert.equal(wrapped.rows[0].input, first.input)
  assert.equal(wrapped.rows[0].originalInput, first.originalInput)
  assert.equal(wrapped.rows[0].output, first.output)
  assert.equal(direct.rows.length, 1)
  assert.equal(direct.rows[0].reason, first.reason)
})

test('malformed and empty artifacts produce no readable rows', () => {
  assert.deepEqual(parseRedteamArtifact('{broken').rows, [])
  assert.deepEqual(parseRedteamArtifact(JSON.stringify({ content: [{ results: 'bad' }] })).rows, [])
  assert.deepEqual(parseRedteamArtifact(JSON.stringify({ results: [null, 'bad', { status: 'Safe' }] })).rows.map(row => row.status), ['Safe'])
  assert.deepEqual(summarizeRedteamRows([]), { recorded: 0, safe: 0, risk: 0, evaluated: 0, rate: '—' })
})
