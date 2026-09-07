const text = value => typeof value === 'string' ? value : ''

export function presentFindingEvidence(finding, relatedCase) {
  const evidence = finding?.evidence || {}
  const fields = []
  for (const key of ['attack_method', 'vulnerability', 'endpoint', 'component', 'component_version', 'cve', 'cvss', 'upstream_rule', 'source_skill']) {
    const value = text(evidence[key]) || (key === 'attack_method' ? text(relatedCase?.request_summary?.attack_method) : '')
    if (value) fields.push({ key, value })
  }
  const reason = text(relatedCase?.response_summary?.evaluator_reason) || text(evidence.reason)
  const preview = text(evidence.sanitized_preview)
  const indicators = ['matched_indicators', 'matched_upstream_patterns', 'side_effect_categories']
    .flatMap(key => Array.isArray(evidence[key]) ? evidence[key].filter(item => text(item)) : [])
  const parameters = (Array.isArray(evidence.parameter_signals) ? evidence.parameter_signals : [])
    .map(item => [text(item?.path), text(item?.category)].filter(Boolean).join(' : ')).filter(Boolean)
  const conversation = (Array.isArray(evidence.conversation) ? evidence.conversation : [])
    .map(item => ({ prompt: text(item?.prompt), response: text(item?.response) }))
    .filter(item => item.prompt || item.response)
  const prompt = text(relatedCase?.request_summary?.prompt)
  const response = text(relatedCase?.response_summary?.response)
  if (prompt || response) conversation.unshift({ prompt, response })
  return {
    fields, reason, preview, indicators: [...new Set([...indicators, ...parameters])], conversation,
    suggestion: text(evidence.suggestion),
    hasSpecificEvidence: Boolean(reason || preview || indicators.length || parameters.length || (text(evidence.cve) && text(evidence.component_version))),
  }
}
