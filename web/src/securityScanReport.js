const PROMPT_TRANSFORMATION_CODES = {
  RedTeam: 'Raw',
  'Prompt Injection': 'PromptInjection',
  'System Override': 'SystemOverride',
}

export function promptTransformationLabel(value, t, te) {
  if (!value) return '—'
  const code = Object.hasOwn(PROMPT_TRANSFORMATION_CODES, value) ? PROMPT_TRANSFORMATION_CODES[value] : value
  const key = `agentSecurityScans.tasks.techniqueOptions.${code}.label`
  if (!te(key)) return value
  return t(key)
}

export function projectScanCases(detail, reportRows = []) {
  const task = detail?.task
  const finalCases = detail?.cases || []
  const terminal = ['succeeded', 'failed', 'cancelled', 'timed_out', 'blocked'].includes(task?.status)
  const live = task?.scan_kind === 'llm_redteam_scan' && (!terminal || !finalCases.length)
  if (live) return {
    source: 'progress',
    rows: (task.progress?.cases || []).map(item => ({
      ...item, case_id: `progress:${item.case_id}`, title: item.vulnerability,
      request_summary: { prompt: item.prompt, attack_method: item.attack_method },
      response_summary: { response: item.response, evaluator_reason: item.reason },
    })),
  }
  const byExternalId = new Map(reportRows.map(row => [`aig-llm-prompt:${row._index}`, row]))
  return {
    source: 'final',
    rows: finalCases.map(item => {
      const report = byExternalId.get(item.external_case_id)
      if (task?.scan_kind !== 'llm_redteam_scan' || !report) return item
      return { ...item,
        request_summary: { ...item.request_summary, attack_method: item.request_summary?.attack_method || report.attackMethod, prompt: report.input, original_prompt: report.originalInput },
        response_summary: { ...item.response_summary, response: report.output, evaluator_reason: report.reason || item.response_summary?.evaluator_reason },
      }
    }),
  }
}

export function summarizeCaseCoverage({ task, cases = [], artifacts = [] } = {}) {
  const artifactCoverage = artifacts.find(item => item.artifact_type === 'aig-agent-scan-report')?.metadata?.coverage
  if (artifactCoverage) return {
    planned_cases: Number(artifactCoverage.planned_cases ?? artifactCoverage.planned_rules ?? 0),
    passed_cases: Number(artifactCoverage.passed_cases ?? artifactCoverage.passed_rules ?? 0),
    failed_cases: Number(artifactCoverage.failed_cases ?? artifactCoverage.failed_rules ?? 0),
    error_cases: Number(artifactCoverage.error_cases ?? artifactCoverage.error_rules ?? 0),
    blocked_cases: Number(artifactCoverage.blocked_cases ?? artifactCoverage.blocked_rules ?? 0),
    unverified_cases: Number(artifactCoverage.unverified_cases ?? artifactCoverage.unverified_rules ?? 0),
  }
  const sourceCases = task?.scan_kind === 'agent_risk_scan'
    ? cases.filter(item => item.category === 'agent_detection_skill')
    : cases
  const count = status => sourceCases.filter(item => item.status === status).length
  return {
    planned_cases: sourceCases.length,
    passed_cases: count('passed'), failed_cases: count('failed'), error_cases: count('error'),
    blocked_cases: count('blocked'), unverified_cases: count('unverified'),
  }
}

export function parseRedteamArtifact(content) {
  let parsed
  try { parsed = typeof content === 'string' ? JSON.parse(content) : content } catch { return { parsed: null, rows: [] } }
  const reports = Array.isArray(parsed?.content) ? parsed.content : (Array.isArray(parsed?.results) ? [parsed] : [])
  const rows = reports.flatMap(report => Array.isArray(report?.results) ? report.results : []).filter(item => item && typeof item === 'object' && !Array.isArray(item)).map((item, index) => ({
    ...item, _index: index + 1,
    attackMethod: item.attackMethod || item.attack_method,
    vulnerability: item.vulnerability,
    reason: item.reason || item.error,
    input: item.input,
    originalInput: item.originalInput,
    output: item.output,
  }))
  return { parsed, rows }
}

export function summarizeRedteamRows(rows = []) {
  const evaluated = rows.filter(item => item.status === 'Safe' || item.status === 'Jailbreak').length
  const risk = rows.filter(item => item.status === 'Jailbreak').length
  return { recorded: rows.length, safe: rows.filter(item => item.status === 'Safe').length, risk, evaluated, rate: evaluated ? `${Math.round(risk / evaluated * 100)}%` : '—' }
}
