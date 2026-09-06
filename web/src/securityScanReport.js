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
