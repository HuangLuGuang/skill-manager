export const decisionReason = report => {
  const r = report?.risk_reconciliation
  if (!r) return 'missing'
  if (r.llm_downgrade_blocked) return report.risk_classification?.blocking_count > 0 ? 'blocked' : 'strict'
  if (r.llm_downgraded) return 'lowered'
  return r.llm_risk_level ? 'raised' : 'toolsOnly'
}
export const decisionConfigChanged = (snapshot, policy) => {
  if (!snapshot || !policy) return null
  const keys = new Set([...Object.keys(snapshot.risk_classification || {}), ...Object.keys(policy.risk_classification || {})])
  return snapshot.judgement_mode !== policy.judgement_mode || [...keys].some(key => snapshot.risk_classification?.[key] !== policy.risk_classification?.[key])
}
export const analysisState = (report, key) => {
  const status = report?.analyzer_timings?.[key]?.status
  return ['completed', 'failed', 'skipped', 'disabled', 'pending'].includes(status) ? status : 'unrecorded'
}
