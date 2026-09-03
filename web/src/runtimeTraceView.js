export const TRACE_LANES = Object.freeze([
  'input',
  'model',
  'tools',
  'mcp',
  'knowledge',
  'policy',
])

const cleanSearchValue = value => typeof value === 'string' && value.trim() ? value.trim() : undefined

export const runtimeTraceSearchParams = (filters = {}) => ({
  ...(cleanSearchValue(filters.turn_id) ? { turn_id: cleanSearchValue(filters.turn_id) } : {}),
  ...(cleanSearchValue(filters.tool_name) ? { tool_name: cleanSearchValue(filters.tool_name) } : {}),
  ...(cleanSearchValue(filters.request_id) ? { request_id: cleanSearchValue(filters.request_id) } : {}),
  ...(cleanSearchValue(filters.risk_level) && filters.risk_level !== 'all'
    ? { risk_level: cleanSearchValue(filters.risk_level) }
    : {}),
  ...(filters.has_error === true ? { has_error: true } : {}),
})

export const runtimeTraceEventSearchParams = (filters = {}) => {
  const params = runtimeTraceSearchParams(filters)
  const { risk_level: _riskLevel, has_error: hasError, ...eventParams } = params
  return { ...eventParams, ...(hasError ? { errors_only: true } : {}) }
}

const PREFIX_LANES = Object.freeze({
  model: 'model',
  tool: 'tools',
  mcp: 'mcp',
  knowledge: 'knowledge',
  policy: 'policy',
  approval: 'policy',
  runtime: 'policy',
  security: 'policy',
})

export const classifyTraceEvent = (event = {}) => {
  const type = typeof event.type === 'string' ? event.type : ''
  if (type === 'message.user' || type === 'context.injected') return 'input'
  return PREFIX_LANES[type.split('.')[0]] || 'input'
}

export const conversationRole = (event = {}) => {
  if (event.type === 'message.user') return 'user'
  if (event.type === 'context.injected') return 'context'
  if (event.type === 'model.response') return 'assistant'
  if (event.type === 'model.error') return 'error'
  return null
}

export const sortTraceEvents = events => [...(Array.isArray(events) ? events : [])]
  .sort((left, right) => Number(left.seq || 0) - Number(right.seq || 0))

export const virtualTraceWindow = (events, scrollTop = 0, viewportHeight = 640, options = {}) => {
  const ordered = sortTraceEvents(events)
  const rowHeight = Math.max(1, Number(options.rowHeight) || 96)
  const overscan = Math.max(0, Number(options.overscan) || 8)
  const safeTop = Math.max(0, Number(scrollTop) || 0)
  const safeViewport = Math.max(rowHeight, Number(viewportHeight) || 640)
  const start = Math.max(0, Math.floor(safeTop / rowHeight) - overscan)
  const end = Math.min(ordered.length, Math.ceil((safeTop + safeViewport) / rowHeight) + overscan)
  return {
    items: ordered.slice(start, end),
    start,
    end,
    topPadding: start * rowHeight,
    bottomPadding: Math.max(0, (ordered.length - end) * rowHeight),
  }
}

export const UNSCOPED_TURN = '__unscoped_turn__'
export const UNSCOPED_STEP = '__unscoped_step__'

const groupedRange = events => ({
  startSeq: Number(events[0]?.seq || 0),
  endSeq: Number(events.at(-1)?.seq || 0),
  eventCount: events.length,
})

export const groupTraceEvents = (events) => {
  const turns = []
  const turnOccurrences = new Map()
  for (const event of sortTraceEvents(events)) {
    const turnBase = event.turn_id || UNSCOPED_TURN
    let turn = turns.at(-1)
    if (!turn || turn.base !== turnBase) {
      const occurrence = (turnOccurrences.get(turnBase) || 0) + 1
      turnOccurrences.set(turnBase, occurrence)
      turn = {
        key: `${turnBase}:${occurrence}`,
        base: turnBase,
        turnId: event.turn_id || null,
        isUnscoped: !event.turn_id,
        events: [],
        steps: [],
        stepOccurrences: new Map(),
      }
      turns.push(turn)
    }
    turn.events.push(event)
    const stepBase = event.step_id || UNSCOPED_STEP
    let step = turn.steps.at(-1)
    if (!step || step.base !== stepBase) {
      const occurrence = (turn.stepOccurrences.get(stepBase) || 0) + 1
      turn.stepOccurrences.set(stepBase, occurrence)
      step = {
        key: `${turn.key}:${stepBase}:${occurrence}`,
        base: stepBase,
        stepId: event.step_id || null,
        isUnscoped: !event.step_id,
        events: [],
      }
      turn.steps.push(step)
    }
    step.events.push(event)
  }

  return turns.map(turn => ({
    ...groupedRange(turn.events),
    key: turn.key,
    turnId: turn.turnId,
    isUnscoped: turn.isUnscoped,
    steps: turn.steps.map(step => ({
      ...step,
      ...groupedRange(step.events),
    })),
  }))
}

export const buildCallRows = (events, collapsedCallIds = [], relationshipEvents = events) => {
  const ordered = sortTraceEvents(events)
  const relationshipOrdered = sortTraceEvents(relationshipEvents)
  const parentByCall = new Map()
  const childrenByCall = new Map()
  const firstSeqByCall = new Map()
  const localCallIds = new Set(ordered.map(event => event.call_id).filter(Boolean))

  for (const event of relationshipOrdered) {
    if (!event.call_id) continue
    if (!firstSeqByCall.has(event.call_id)) firstSeqByCall.set(event.call_id, Number(event.seq || 0))
    if (event.parent_call_id && event.parent_call_id !== event.call_id && !parentByCall.has(event.call_id)) {
      parentByCall.set(event.call_id, event.parent_call_id)
      if (!childrenByCall.has(event.parent_call_id)) childrenByCall.set(event.parent_call_id, new Set())
      childrenByCall.get(event.parent_call_id).add(event.call_id)
    }
  }

  const collapsed = collapsedCallIds instanceof Set ? collapsedCallIds : new Set(collapsedCallIds)
  return ordered.flatMap((event) => {
    const ancestors = []
    const visited = new Set(event.call_id ? [event.call_id] : [])
    let parentCallId = event.call_id ? parentByCall.get(event.call_id) : null
    while (parentCallId && !visited.has(parentCallId)) {
      ancestors.unshift(parentCallId)
      visited.add(parentCallId)
      parentCallId = parentByCall.get(parentCallId)
    }
    if (ancestors.some(callId => collapsed.has(callId))) return []
    return [{
      event,
      depth: ancestors.length,
      ancestorCallIds: ancestors,
      isCallHead: Boolean(event.call_id) && firstSeqByCall.get(event.call_id) === Number(event.seq || 0),
      hasChildren: Boolean(event.call_id && childrenByCall.get(event.call_id)?.size),
      isCollapsed: Boolean(event.call_id && collapsed.has(event.call_id)),
      hasExternalParent: Boolean(event.parent_call_id && !localCallIds.has(event.parent_call_id)),
    }]
  })
}

const SUCCESS_STATUSES = new Set(['allow', 'allowed', 'approved', 'authorized', 'completed', 'passed', 'resolved', 'succeeded', 'used'])
const ERROR_STATUSES = new Set(['blocked', 'cancelled', 'denied', 'deny', 'error', 'failed', 'killed', 'kill_switch_active', 'rejected', 'timed_out'])
const ACTIVE_STATUSES = new Set(['active', 'executing', 'observed', 'pending', 'requested', 'running', 'submitted'])

export const eventStatusTone = (status) => {
  const value = typeof status === 'string' ? status.toLowerCase() : ''
  if (SUCCESS_STATUSES.has(value)) return 'success'
  if (ERROR_STATUSES.has(value)) return 'danger'
  if (ACTIVE_STATUSES.has(value)) return 'active'
  return 'neutral'
}

const compactObject = entries => Object.fromEntries(entries.filter(([, value]) => value !== null && value !== undefined && value !== ''))

export const eventSummaryProjection = (event = {}) => compactObject([
  ['event_id', event.event_id],
  ['seq', event.seq],
  ['type', event.type],
  ['source', event.source],
  ['status', event.status],
  ['tool_name', event.tool_name],
  ['schema_version', event.schema_version],
  ['turn_id', event.turn_id],
  ['step_id', event.step_id],
  ['request_id', event.request_id],
  ['call_id', event.call_id],
  ['parent_call_id', event.parent_call_id],
  ['payload_ref', event.payload_ref],
])

const payloadObject = event => event?.payload && typeof event.payload === 'object' ? event.payload : null

export const eventResultProjection = (event = {}) => {
  const payload = payloadObject(event)
  if (!payload) return null
  if (event.type === 'model.response') return payload.response ?? payload.result ?? null
  if (event.type === 'model.error') return payload.error ?? null
  if (event.type?.endsWith('.result')) return payload.result ?? payload.response ?? payload
  if (event.type?.endsWith('.error')) return payload.error ?? payload
  if (event.type === 'policy.decision') {
    const projection = compactObject([['decision', payload.decision], ['reasons', payload.reasons]])
    return Object.keys(projection).length ? projection : null
  }
  if (event.type === 'approval.resolved') {
    const projection = compactObject([['decision', payload.decision], ['message', payload.message], ['approval_request_id', payload.approval_request_id]])
    return Object.keys(projection).length ? projection : null
  }
  if (event.type === 'runtime.blocked' || event.type === 'runtime.killed') {
    const projection = compactObject([['reason', payload.reason], ['reasons', payload.reasons], ['message', payload.message]])
    return Object.keys(projection).length ? projection : null
  }
  for (const key of ['result', 'response', 'error', 'output', 'decision']) {
    if (payload[key] !== undefined) return payload[key]
  }
  return null
}

export const eventSchemaProjection = (event = {}) => {
  const schemas = {}
  const visit = (value, path = [], depth = 0) => {
    if (depth > 8 || value === null || value === undefined || Object.keys(schemas).length >= 100) return
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, [...path, `[${index}]`], depth + 1))
      return
    }
    if (typeof value !== 'object') return
    for (const [key, child] of Object.entries(value)) {
      const childPath = [...path, key]
      if (key.toLowerCase().includes('schema')) schemas[childPath.join('.').replaceAll('.[', '[')] = child
      visit(child, childPath, depth + 1)
    }
  }
  visit(event.payload)
  return {
    event_schema_version: event.schema_version || null,
    discovered_schema_fields: schemas,
  }
}

export const eventTimingProjection = (event = {}) => ({
  event_time: event.event_time || null,
  received_at: event.received_at || null,
  duration_ms: event.duration_ms ?? null,
  request_duration_ms: payloadObject(event)?.performance?.request_duration_ms ?? null,
  upstream_duration_ms: payloadObject(event)?.performance?.upstream_duration_ms ?? null,
  platform_duration_ms: payloadObject(event)?.performance?.platform_duration_ms ?? null,
  ttft_ms: payloadObject(event)?.performance?.ttft_ms ?? null,
  prompt_tokens: payloadObject(event)?.usage?.prompt_tokens ?? null,
  completion_tokens: payloadObject(event)?.usage?.completion_tokens ?? null,
  total_tokens: payloadObject(event)?.usage?.total_tokens ?? null,
})

const finiteMetric = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
const averageMetric = (values) => {
  const samples = values.map(finiteMetric).filter(value => value !== null)
  return { value: samples.length ? samples.reduce((sum, value) => sum + value, 0) / samples.length : null, samples: samples.length }
}

export const tracePerformanceSummary = (events = []) => {
  let promptTokens = 0
  let completionTokens = 0
  let totalTokens = 0
  let tokenSamples = 0
  const ttftValues = []
  const modelValues = []
  const platformValues = []
  const toolValues = []

  for (const event of events) {
    const payload = payloadObject(event)
    const usage = payload?.usage && typeof payload.usage === 'object' ? payload.usage : null
    const performance = payload?.performance && typeof payload.performance === 'object' ? payload.performance : null
    if (event.type === 'model.response' && usage) {
      const prompt = finiteMetric(usage.prompt_tokens)
      const completion = finiteMetric(usage.completion_tokens)
      const total = finiteMetric(usage.total_tokens)
      if (prompt !== null || completion !== null || total !== null) {
        promptTokens += prompt || 0
        completionTokens += completion || 0
        totalTokens += total ?? (prompt || 0) + (completion || 0)
        tokenSamples += 1
      }
    }
    if (event.type === 'model.response' || event.type === 'model.error') {
      ttftValues.push(performance?.ttft_ms)
      modelValues.push(performance?.upstream_duration_ms)
      platformValues.push(performance?.platform_duration_ms)
    }
    if (/^(tool|mcp)\.(result|error)$/.test(event.type || '')) toolValues.push(event.duration_ms)
  }

  return {
    tokens: {
      value: tokenSamples ? totalTokens : null,
      prompt: tokenSamples ? promptTokens : null,
      completion: tokenSamples ? completionTokens : null,
      samples: tokenSamples,
    },
    ttft: averageMetric(ttftValues),
    model: averageMetric(modelValues),
    platform: averageMetric(platformValues),
    tool: averageMetric(toolValues),
  }
}

const APPROVAL_DENIED_STATUSES = new Set(['denied', 'deny', 'rejected'])

const approvalEventId = (event) => {
  const payload = payloadObject(event)
  return payload?.approval_request_id || payload?.approval_id || null
}

export const traceSecuritySummary = (events = [], trace = {}) => {
  const riskCodes = new Set(Array.isArray(trace.risk_codes) ? trace.risk_codes.filter(Boolean) : [])
  const pendingApprovals = new Set()
  let unlinkedPendingApprovals = 0
  let approvalRequested = 0
  let approvalResolved = 0
  let approvalApproved = 0
  let approvalDenied = 0
  let blocked = 0
  let killed = 0
  let killSwitchObserved = false

  for (const event of sortTraceEvents(events)) {
    for (const code of Array.isArray(event.risk_codes) ? event.risk_codes : []) {
      if (code) riskCodes.add(code)
    }
    const status = typeof event.status === 'string' ? event.status.toLowerCase() : ''
    if (event.type === 'approval.requested') {
      approvalRequested += 1
      const approvalId = approvalEventId(event)
      if (approvalId) pendingApprovals.add(approvalId)
      else if (status === 'pending' || status === 'requested') unlinkedPendingApprovals += 1
    }
    if (event.type === 'approval.resolved') {
      approvalResolved += 1
      const approvalId = approvalEventId(event)
      if (approvalId) pendingApprovals.delete(approvalId)
      if (status === 'approved' || status === 'authorized' || status === 'used') approvalApproved += 1
      if (APPROVAL_DENIED_STATUSES.has(status)) approvalDenied += 1
    }
    if (event.type === 'runtime.blocked') blocked += 1
    if (event.type === 'runtime.killed') killed += 1
    if (
      status === 'kill_switch_active'
      || (Array.isArray(event.risk_codes) && event.risk_codes.includes('runtime.kill_switch_active'))
    ) killSwitchObserved = true
  }

  return {
    completeness: trace.completeness || 'unknown',
    riskLevel: trace.risk_level || 'info',
    riskCodes: [...riskCodes],
    approvals: {
      requested: approvalRequested,
      resolved: approvalResolved,
      pending: pendingApprovals.size + unlinkedPendingApprovals,
      approved: approvalApproved,
      denied: approvalDenied,
    },
    blocked,
    killed,
    killSwitchObserved,
  }
}

export const eventSecurityProjection = (event = {}) => {
  const payload = payloadObject(event)
  const security = compactObject([
    ['projection', 'redacted'],
    ['status', event.status],
    ['risk_codes', Array.isArray(event.risk_codes) ? event.risk_codes : []],
    ['risk_mapping', event.risk_mapping],
    ['prompt_security', payload?.prompt_security],
    ['security', payload?.security],
    ['finding', event.type === 'security.finding' ? payload : null],
  ])
  return security
}

const preferredPayloadValue = (payload) => {
  if (payload === null || payload === undefined) return ''
  if (typeof payload === 'string') return payload
  if (typeof payload !== 'object') return String(payload)
  if (Array.isArray(payload)) {
    return payload.map(preferredPayloadValue).filter(Boolean).join('\n')
  }
  for (const key of ['content', 'text', 'message', 'response', 'result', 'summary']) {
    if (payload[key] !== undefined) {
      const value = preferredPayloadValue(payload[key])
      if (value) return value
    }
  }
  return ''
}

export const payloadPreview = (payload, maxLength = 240) => {
  if (payload === null || payload === undefined) return ''
  const preferred = preferredPayloadValue(payload)
  let text = preferred
  if (!text) {
    try {
      text = JSON.stringify(payload)
    } catch {
      text = String(payload)
    }
  }
  const normalized = text.replace(/\s+/g, ' ').trim()
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}…` : normalized
}
