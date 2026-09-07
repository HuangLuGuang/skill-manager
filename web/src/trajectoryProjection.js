import { classifyTraceEvent, eventSemanticSummary, payloadPreview, sortTraceEvents } from './runtimeTraceView.js'

const stableValue = value => {
  if (Array.isArray(value)) return value.map(stableValue)
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, stableValue(value[key])]))
  return value
}
const messageKey = message => JSON.stringify(stableValue({
  role: message.role, content: message.content ?? '', name: message.name,
  tool_call_id: message.tool_call_id, tool_calls: message.tool_calls,
  function_call: message.function_call,
}))
const responseMessages = event => {
  const response = event?.payload?.response
  if (Array.isArray(response?.choices)) return response.choices.map(choice => choice.message).filter(Boolean)
  if (response?.role) return [response]
  if (typeof response?.content === 'string') return [{ role: 'assistant', content: response.content }]
  return []
}

// Rows reference the original redacted events; inferred messages never become audit events.
export const buildTrajectoryRows = (events = []) => {
  const ordered = sortTraceEvents(events)
  const rows = []
  const requests = new Map()
  const requestRows = new Map()
  const tools = new Map()
  const messageTools = new Map()
  let previousHistory = []
  let latestRequest = null
  let requestNumber = 0
  const makeRow = (event, suffix, kind, content, extra = {}) => ({
    id: `${event.event_id}:${suffix}`, event, events: [event], kind,
    lane: classifyTraceEvent(event), content, preview: kind === 'request' ? (event.payload?.model || '') : payloadPreview(content, 400),
    requestId: event.request_id || null, group: event.request_id || event.turn_id || null,
    status: event.status, ...extra,
  })
  const addMessage = (event, message, index, observed) => {
    const role = message.role || 'context'
    if (role === 'tool' && message.tool_call_id) {
      const tool = messageTools.get(message.tool_call_id)
      if (tool && tool.result === undefined) {
        tool.result = message.content
        tool.preview = `${payloadPreview(tool.content)} → ${payloadPreview(message.content)}`
        if (!tool.events.includes(event)) tool.events.push(event)
        return
      }
    }
    if (message.content || !message.tool_calls?.length) rows.push(makeRow(event, `message-${index}`, role, message.content ?? message, {
      lane: role === 'user' || role === 'system' || role === 'developer' ? 'input' : role === 'tool' ? 'tools' : 'model',
      observed, status: null, toolName: message.name, message,
    }))
    for (const [callIndex, call] of (message.tool_calls || []).entries()) {
      const row = makeRow(event, `message-${index}-tool-${callIndex}`, 'tool', call.function?.arguments ?? call, {
        lane: 'tools', toolName: call.function?.name, callId: call.id, observed: true, status: null,
      })
      rows.push(row)
      if (call.id) messageTools.set(call.id, row)
    }
  }
  for (const event of ordered) {
    if (event.type === 'model.request') {
      latestRequest = event
      requestNumber += 1
      const row = makeRow(event, 'request', 'request', event.payload?.request, {
        number: requestNumber, model: event.payload?.model || event.payload?.request?.model,
      })
      rows.push(row)
      if (event.request_id) {
        requests.set(event.request_id, event)
        requestRows.set(event.request_id, row)
      }
      const history = event.payload?.request?.messages
      if (event.source === 'model_gateway' && Array.isArray(history)) {
        const keys = history.map(messageKey)
        let shared = 0
        while (shared < keys.length && shared < previousHistory.length && keys[shared] === previousHistory[shared]) shared += 1
        if (shared < previousHistory.length) messageTools.clear()
        history.slice(shared).forEach((message, index) => addMessage(event, message, shared + index, true))
        previousHistory = keys
      }
      continue
    }
    if (event.type === 'model.response' || event.type === 'model.error') {
      const requestRow = requestRows.get(event.request_id)
      if (requestRow) {
        requestRow.events.push(event)
        requestRow.result = event.payload?.response ?? event.payload?.error
        requestRow.status = event.status
        requestRow.duration = event.duration_ms
      }
      const messages = responseMessages(event)
      if (event.type === 'model.response' && messages.length) {
        messages.forEach((message, index) => addMessage(event, message, index, false))
        const request = requests.get(event.request_id)
        const history = request?.payload?.request?.messages
        if (event.source === 'model_gateway' && Array.isArray(history) && request === latestRequest) {
          previousHistory.push(...messages.map(messageKey))
        }
      } else rows.push(makeRow(event, 'response', event.type === 'model.error' ? 'error' : 'assistant', event.payload?.response ?? event.payload?.error ?? eventSemanticSummary(event)))
      continue
    }
    if (/^(tool|mcp)\.(call|result|error)$/.test(event.type)) {
      const key = `${event.type.split('.')[0]}:${event.call_id}`
      const existing = event.call_id ? tools.get(key) : null
      if (!event.type.endsWith('.call') && existing && existing.result === undefined) {
        existing.result = event.payload?.result ?? event.payload?.error ?? event.payload
        existing.events.push(event)
        existing.status = event.status
        existing.duration = event.duration_ms
        existing.preview = `${payloadPreview(existing.content)} → ${payloadPreview(existing.result)}`
      } else {
        const row = makeRow(event, 'tool', 'tool', event.payload?.arguments ?? event.payload?.args ?? event.payload, {
          toolName: event.tool_name, callId: event.call_id, duration: event.duration_ms,
        })
        rows.push(row)
        if (event.call_id && event.type.endsWith('.call')) tools.set(key, row)
      }
      continue
    }
    rows.push(makeRow(event, 'event', event.type === 'message.user' ? 'user' : event.type === 'context.injected' ? 'context' : 'event',
      event.payload?.content ?? eventSemanticSummary(event), { toolName: event.tool_name, duration: event.duration_ms }))
  }
  return rows
}
