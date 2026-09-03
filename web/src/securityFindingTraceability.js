const TRACEABILITY_PARTS = ['case', 'event', 'evidence', 'decision_criteria']

export const normalizeFindingTraceability = finding => {
  const supplied = finding?.traceability || {}
  const values = {
    case: supplied.case_id || finding?.case_id || null,
    event: supplied.trace_id && supplied.event_id
      ? { traceId: supplied.trace_id, eventId: supplied.event_id }
      : finding?.trace_id && finding?.event_id
        ? { traceId: finding.trace_id, eventId: finding.event_id }
        : null,
    evidence: supplied.evidence_sha256 || null,
    decision_criteria: supplied.decision_criteria_version || finding?.decision_criteria_version || null,
  }
  const missing = TRACEABILITY_PARTS.filter(part => !values[part])
  return {
    status: missing.length ? 'incomplete' : 'complete',
    caseId: values.case,
    traceId: values.event?.traceId || null,
    eventId: values.event?.eventId || null,
    evidenceSha256: values.evidence,
    decisionCriteriaVersion: values.decision_criteria,
    missing,
  }
}
