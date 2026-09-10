export const policyRisks = ['benign', 'suspicious', 'malicious']
export const recommendedActions = { benign: 'APPROVED', suspicious: 'VETTED', malicious: 'REJECTED' }
export const classificationKeys = ['blocking', 'risk', 'noise']
export const defaultRiskClassification = {
  data_exfiltration: 'blocking', supply_chain: 'blocking',
  prompt_injection: 'risk', tool_misuse: 'risk', network: 'risk',
  credential_access: 'risk', dynamic_execution: 'risk', excessive_permissions: 'risk',
  documented_external_api: 'noise', dependency: 'noise', runtime: 'noise',
}

// Existing YAML policies may use scanner severity names. Match CompanyPolicy.decide.
const severityRisks = {
  SAFE: 'benign', INFO: 'benign', LOW: 'benign', MEDIUM: 'suspicious',
  HIGH: 'malicious', CRITICAL: 'malicious', EXTREME: 'malicious',
}
const normalizedRisks = values => new Set((Array.isArray(values) ? values : []).map(value => {
  const text = String(value).trim()
  return policyRisks.includes(text.toLowerCase()) ? text.toLowerCase() : severityRisks[text.toUpperCase()]
}).filter(Boolean))

export function policyActions(policy) {
  const rejected = normalizedRisks(policy.auto_reject_risk ?? ['malicious'])
  const reviewed = normalizedRisks(policy.require_human_review ?? ['suspicious'])
  const approved = normalizedRisks(policy.auto_approve_risk ?? ['benign'])
  return Object.fromEntries(policyRisks.map(risk => [risk,
    rejected.has(risk) ? 'REJECTED' : reviewed.has(risk) ? 'VETTED'
      : allowedActions(risk).includes('APPROVED') && approved.has(risk) ? 'APPROVED' : recommendedActions[risk],
  ]))
}

export function actionPolicy(actions) {
  return {
    auto_approve_risk: policyRisks.filter(risk => actions[risk] === 'APPROVED'),
    require_human_review: policyRisks.filter(risk => actions[risk] === 'VETTED'),
    auto_reject_risk: policyRisks.filter(risk => actions[risk] === 'REJECTED'),
  }
}

export const allowedActions = risk => ['benign', 'suspicious'].includes(risk)
  ? ['APPROVED', 'VETTED', 'REJECTED']
  : ['VETTED', 'REJECTED']
