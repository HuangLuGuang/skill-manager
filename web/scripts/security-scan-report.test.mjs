import assert from 'node:assert/strict'
import test from 'node:test'

import { parseRedteamArtifact, projectScanCases, promptTransformationLabel, summarizeCaseCoverage, summarizeRedteamRows } from '../src/securityScanReport.js'

test('prompt transformations display localized labels', () => {
  const key = 'agentSecurityScans.tasks.techniqueOptions.Raw.label'
  for (const label of ['原始问题', 'Original prompt']) {
    assert.equal(promptTransformationLabel('Raw', () => label, value => value === key), label)
    assert.equal(promptTransformationLabel('RedTeam', () => label, value => value === key), label)
  }
  assert.equal(promptTransformationLabel('CustomMethod', () => '', () => false), 'CustomMethod')
  assert.equal(promptTransformationLabel('', () => 'Raw', () => true), '—')
})

test('upstream display names resolve to configured transformation translations', () => {
  const labels = {
    'agentSecurityScans.tasks.techniqueOptions.PromptInjection.label': '指令干扰',
    'agentSecurityScans.tasks.techniqueOptions.SystemOverride.label': '伪装高权限指令',
  }
  const t = key => labels[key]
  const te = key => Object.hasOwn(labels, key)
  assert.equal(promptTransformationLabel('Prompt Injection', t, te), '指令干扰')
  assert.equal(promptTransformationLabel('System Override', t, te), '伪装高权限指令')
})

test('live and final case projections preserve the recorded transformation', () => {
  const detail = { task: { scan_kind: 'llm_redteam_scan', status: 'running', progress: { cases: [{ case_id: '1', attack_method: 'Roleplay' }] } }, cases: [] }
  assert.equal(projectScanCases(detail).rows[0].request_summary.attack_method, 'Roleplay')
  detail.task.status = 'succeeded'
  detail.cases = [{ case_id: 'final', external_case_id: 'aig-llm-prompt:1', request_summary: { attack_method: 'Raw' } }]
  const reports = [{ _index: 1, attackMethod: 'Roleplay' }]
  assert.equal(projectScanCases(detail, reports).rows[0].request_summary.attack_method, 'Raw')
  delete detail.cases[0].request_summary.attack_method
  assert.equal(projectScanCases(detail, reports).rows[0].request_summary.attack_method, 'Roleplay')
})

test('running LLM tasks show progress records and completed tasks select final cases', () => {
  const detail = { task: { scan_kind: 'llm_redteam_scan', status: 'running', progress: { cases: [{ case_id: '1', status: 'running', prompt: 'input', response: 'output' }] } }, cases: [{ case_id: 'final', external_case_id: 'aig-llm-prompt:1', status: 'passed' }] }
  const live = projectScanCases(detail)
  assert.equal(live.source, 'progress')
  assert.equal(live.rows.length, 1)
  assert.equal(live.rows[0].request_summary.prompt, 'input')
  assert.equal(live.rows[0].response_summary.response, 'output')
  detail.task.status = 'succeeded'
  assert.deepEqual(projectScanCases(detail).rows, detail.cases)
})

test('terminal tasks retain process records only when final cases are unavailable', () => {
  for (const status of ['failed', 'cancelled', 'timed_out', 'blocked']) {
    const detail = { task: { scan_kind: 'llm_redteam_scan', status, progress: { cases: [{ case_id: '1', status: 'error' }] } }, cases: [] }
    assert.equal(projectScanCases(detail).rows.length, 1)
    detail.cases = [{ case_id: 'final', status: 'error' }]
    assert.equal(projectScanCases(detail).source, 'final')
  }
  assert.deepEqual(projectScanCases({ task: { scan_kind: 'mcp_risk_scan' }, cases: [{ case_id: 'mcp' }] }).rows, [{ case_id: 'mcp' }])
})

test('final report bodies match external IDs rather than database case order', () => {
  const detail = { task: { scan_kind: 'llm_redteam_scan', status: 'succeeded' }, cases: [
    { case_id: 'second', external_case_id: 'aig-llm-prompt:2', response_summary: { evaluator_reason: 'short' } },
    { case_id: 'first', external_case_id: 'aig-llm-prompt:1' },
  ] }
  const rows = parseRedteamArtifact({ results: [{ input: 'one', output: 'response one' }, { input: 'two', output: 'response two', reason: 'full reason' }] }).rows
  const result = projectScanCases(detail, rows).rows
  assert.equal(result[0].request_summary.prompt, 'two')
  assert.equal(result[0].response_summary.evaluator_reason, 'full reason')
  assert.equal(result[1].response_summary.response, 'response one')
  assert.equal(detail.cases[0].response_summary.evaluator_reason, 'short')
})

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
