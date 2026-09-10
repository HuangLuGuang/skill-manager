export const decisionReason = report => {
  const r = report?.risk_reconciliation
  if (!r) return 'missing'
  if (r.llm_downgrade_blocked) {
    if (recordedDecision(report).counts.blocking > 0) return 'blocked'
    return r.judgement_mode === 'strict' ? 'strict' : 'reconciled'
  }
  if (r.llm_downgraded) return 'lowered'
  if (!r.llm_risk_level) return 'toolsOnly'
  if (r.llm_risk_level === r.pre_llm_risk_level && r.final_risk_level === r.pre_llm_risk_level) return 'unchanged'
  const risks = ['benign', 'suspicious', 'malicious']
  const before = risks.indexOf(r.pre_llm_risk_level)
  const after = risks.indexOf(r.final_risk_level)
  return before >= 0 && after > before ? 'raised' : 'reconciled'
}
export const decisionConfigChanged = (snapshot, policy) => {
  if (!snapshot || !policy) return null
  const keys = new Set([...Object.keys(snapshot.risk_classification || {}), ...Object.keys(policy.risk_classification || {})])
  return snapshot.judgement_mode !== policy.judgement_mode || [...keys].some(key => snapshot.risk_classification?.[key] !== policy.risk_classification?.[key])
}
export const analysisState = (report, key) => {
  const status = report?.analyzer_timings?.[key]?.status
  return ['completed', 'failed', 'skipped', 'disabled', 'unavailable', 'pending'].includes(status) ? status : 'unrecorded'
}

export const findingTarget = item => {
  const source = String(item.source || item.analyzer || '').toLowerCase()
  return source.includes('sandbox') ? 'sandbox' : source.includes('skillspector') ? 'skillspector' : source.includes('llm') ? 'llm' : 'rule'
}

export const llmRiskDisagreement = report => {
  const decision = recordedDecision(report)
  const risks = ['benign', 'suspicious', 'malicious']
  const llm = risks.indexOf(decision.llmRisk)
  const final = risks.indexOf(decision.finalRisk)
  if (llm < 0 || final <= llm) return null
  const reason = report?.risk_reconciliation?.llm_downgrade_blocked === true ? decisionReason(report) : null
  return ['blocked', 'strict'].includes(reason) ? reason : 'unrecorded'
}

export const recordedDecision = report => {
  const reconciliation = report?.risk_reconciliation
  const classification = report?.risk_classification
  const items = Array.isArray(classification?.items) ? classification.items : null
  return {
    finalRisk: reconciliation?.final_risk_level || report?.risk_level || null,
    toolRisk: reconciliation?.pre_llm_risk_level || report?.pre_llm_risk_level || null,
    llmRisk: reconciliation ? reconciliation.llm_risk_level ?? null : report?.llm_analysis?.risk_level ?? null,
    mode: reconciliation?.judgement_mode || report?.judgement_mode || null,
    findings: items,
    counts: Object.fromEntries(['blocking', 'risk', 'noise'].map(key => [key,
      classification?.[key + '_count'] ?? (items ? items.filter(item => item.classification === key).length : null),
    ])),
  }
}
