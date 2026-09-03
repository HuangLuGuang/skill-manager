import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  TRACE_LANES,
  UNSCOPED_STEP,
  UNSCOPED_TURN,
  buildCallRows,
  classifyTraceEvent,
  conversationRole,
  eventResultProjection,
  eventSchemaProjection,
  eventSecurityProjection,
  eventStatusTone,
  eventSummaryProjection,
  eventTimingProjection,
  groupTraceEvents,
  payloadPreview,
  runtimeTraceEventSearchParams,
  runtimeTraceSearchParams,
  sortTraceEvents,
  tracePerformanceSummary,
  traceSecuritySummary,
  virtualTraceWindow,
} from '../src/runtimeTraceView.js'

const read = path => readFile(new URL(path, import.meta.url), 'utf8')

test('P5-02 maps the runtime-trace schema to six stable lanes', () => {
  assert.deepEqual(TRACE_LANES, ['input', 'model', 'tools', 'mcp', 'knowledge', 'policy'])
  const expected = {
    'turn.start': 'input', 'turn.end': 'input', 'step.start': 'input', 'step.end': 'input',
    'message.user': 'input', 'context.injected': 'input',
    'model.request': 'model', 'model.response': 'model', 'model.error': 'model',
    'tool.call': 'tools', 'tool.result': 'tools', 'tool.error': 'tools',
    'mcp.call': 'mcp', 'mcp.result': 'mcp', 'mcp.error': 'mcp',
    'knowledge.retrieval': 'knowledge',
    'policy.decision': 'policy', 'approval.requested': 'policy', 'approval.resolved': 'policy',
    'runtime.blocked': 'policy', 'runtime.killed': 'policy', 'security.finding': 'policy',
  }
  for (const [type, lane] of Object.entries(expected)) {
    assert.equal(classifyTraceEvent({ type }), lane, type)
  }
})

test('conversation projection and payload preview use protocol codes rather than labels', () => {
  assert.equal(conversationRole({ type: 'message.user' }), 'user')
  assert.equal(conversationRole({ type: 'context.injected' }), 'context')
  assert.equal(conversationRole({ type: 'model.response' }), 'assistant')
  assert.equal(conversationRole({ type: 'tool.result' }), null)
  assert.deepEqual(sortTraceEvents([{ seq: 8 }, { seq: 2 }]).map(item => item.seq), [2, 8])
  assert.equal(payloadPreview({ content: 'hello\nworld' }), 'hello world')
  assert.match(payloadPreview({ nested: { secret: '[REDACTED]' } }), /REDACTED/)
})

test('P5-03 groups only explicit Turn and Step ids and keeps unscoped gateway events honest', () => {
  const groups = groupTraceEvents([
    { event_id: 'model-only', seq: 1, type: 'model.request' },
    { event_id: 'turn-start', seq: 2, type: 'turn.start', turn_id: 'turn-1' },
    { event_id: 'step-start', seq: 3, type: 'step.start', turn_id: 'turn-1', step_id: 'step-1' },
    { event_id: 'tool', seq: 4, type: 'tool.call', turn_id: 'turn-1', step_id: 'step-1' },
  ])
  assert.ok(groups[0].key.startsWith(UNSCOPED_TURN))
  assert.equal(groups[0].turnId, null)
  assert.equal(groups[0].steps[0].stepId, null)
  assert.match(groups[0].steps[0].key, new RegExp(UNSCOPED_STEP))
  assert.equal(groups[1].turnId, 'turn-1')
  assert.equal(groups[1].eventCount, 3)
  assert.deepEqual(groups[1].steps.map(step => step.stepId), [null, 'step-1'])
})

test('P5-03 uses contiguous hierarchy segments so group rendering never reorders seq', () => {
  const groups = groupTraceEvents([
    { event_id: 'turn-start', seq: 1, turn_id: 'turn-1', type: 'turn.start' },
    { event_id: 'step-start', seq: 2, turn_id: 'turn-1', step_id: 'step-1', type: 'step.start' },
    { event_id: 'step-end', seq: 3, turn_id: 'turn-1', step_id: 'step-1', type: 'step.end' },
    { event_id: 'turn-end', seq: 4, turn_id: 'turn-1', type: 'turn.end' },
  ])
  const renderedSeq = groups.flatMap(turn => turn.steps.flatMap(step => step.events.map(event => event.seq)))
  assert.deepEqual(renderedSeq, [1, 2, 3, 4])
  assert.deepEqual(groups[0].steps.map(step => step.stepId), [null, 'step-1', null])
})

test('P5-03 preserves server sequence while deriving collapsible parent-call depth', () => {
  const events = [
    { event_id: 'parent', seq: 2, type: 'tool.call', call_id: 'call-parent' },
    { event_id: 'middle', seq: 3, type: 'policy.decision' },
    { event_id: 'child', seq: 4, type: 'mcp.call', call_id: 'call-child', parent_call_id: 'call-parent' },
    { event_id: 'child-result', seq: 5, type: 'mcp.result', call_id: 'call-child', parent_call_id: 'call-parent' },
    { event_id: 'parent-result', seq: 6, type: 'tool.result', call_id: 'call-parent' },
  ]
  const rows = buildCallRows(events)
  assert.deepEqual(rows.map(row => row.event.seq), [2, 3, 4, 5, 6])
  assert.equal(rows.find(row => row.event.event_id === 'parent').hasChildren, true)
  assert.equal(rows.find(row => row.event.event_id === 'child').depth, 1)
  assert.equal(rows.find(row => row.event.event_id === 'child-result').isCallHead, false)
  assert.deepEqual(buildCallRows(events, new Set(['call-parent'])).map(row => row.event.seq), [2, 3, 6])
})

test('P5-03 keeps parent-child expansion connected across Step groups', () => {
  const events = [
    { event_id: 'parent', seq: 1, turn_id: 'turn-1', step_id: 'step-1', type: 'tool.call', call_id: 'parent' },
    { event_id: 'child', seq: 2, turn_id: 'turn-1', step_id: 'step-2', type: 'mcp.call', call_id: 'child', parent_call_id: 'parent' },
  ]
  const childRows = buildCallRows([events[1]], new Set(), events)
  assert.equal(childRows[0].depth, 1)
  assert.equal(childRows[0].hasExternalParent, true)
  assert.deepEqual(buildCallRows([events[1]], new Set(['parent']), events), [])
})

test('P5-03 status tones are based on stable status codes', () => {
  assert.equal(eventStatusTone('completed'), 'success')
  assert.equal(eventStatusTone('running'), 'active')
  assert.equal(eventStatusTone('blocked'), 'danger')
  assert.equal(eventStatusTone('deny'), 'danger')
  assert.equal(eventStatusTone('provider_specific'), 'neutral')
})

test('P5-04 derives six detail projections without requesting raw payloads', () => {
  const event = {
    schema_version: 'runtime-trace@1', event_id: 'event-9', seq: 9, type: 'mcp.result', source: 'mcp_gateway',
    status: 'completed', turn_id: 'turn-1', step_id: 'step-2', request_id: 'request-1', call_id: 'child',
    parent_call_id: 'parent', event_time: '2026-08-29T00:00:01Z', received_at: '2026-08-29T00:00:02Z',
    duration_ms: 34, risk_codes: ['ASI_TOOL_ABUSE'], payload_ref: 'payload-redacted',
    payload: {
      result: { ok: true, secret: '[REDACTED]' },
      metadata: { input_schema: { type: 'object' }, schema_hash: 'sha256:test' },
      security: { reviewed: true },
    },
  }
  assert.equal(eventSummaryProjection(event).payload, undefined)
  assert.deepEqual(eventResultProjection(event), event.payload.result)
  assert.equal(eventSchemaProjection(event).event_schema_version, 'runtime-trace@1')
  assert.deepEqual(eventSchemaProjection(event).discovered_schema_fields['metadata.input_schema'], { type: 'object' })
  assert.equal(eventSchemaProjection(event).discovered_schema_fields['metadata.schema_hash'], 'sha256:test')
  assert.deepEqual(eventTimingProjection(event), {
    event_time: event.event_time, received_at: event.received_at, duration_ms: 34,
    request_duration_ms: null, upstream_duration_ms: null, platform_duration_ms: null, ttft_ms: null,
    prompt_tokens: null, completion_tokens: null, total_tokens: null,
  })
  assert.deepEqual(eventSecurityProjection(event).risk_codes, ['ASI_TOOL_ABUSE'])
  assert.equal(eventSecurityProjection(event).projection, 'redacted')
})

test('P5-05 summarizes only measured token and latency signals', () => {
  const summary = tracePerformanceSummary([
    {
      type: 'model.response', duration_ms: 140,
      payload: {
        usage: { prompt_tokens: 12, completion_tokens: 8, total_tokens: 20 },
        performance: { request_duration_ms: 140, upstream_duration_ms: 110, platform_duration_ms: 30, ttft_ms: 45 },
      },
    },
    {
      type: 'model.response', duration_ms: 200,
      payload: {
        usage: { prompt_tokens: 20, completion_tokens: 10, total_tokens: 30 },
        performance: { request_duration_ms: 200, upstream_duration_ms: 160, platform_duration_ms: 40 },
      },
    },
    { type: 'mcp.result', duration_ms: 50, payload: { result: { ok: true } } },
    { type: 'tool.error', duration_ms: 70, payload: { error: '[REDACTED]' } },
    { type: 'model.response', duration_ms: 90, payload: {} },
  ])
  assert.deepEqual(summary.tokens, { value: 50, prompt: 32, completion: 18, samples: 2 })
  assert.deepEqual(summary.ttft, { value: 45, samples: 1 })
  assert.deepEqual(summary.model, { value: 135, samples: 2 })
  assert.deepEqual(summary.platform, { value: 35, samples: 2 })
  assert.deepEqual(summary.tool, { value: 60, samples: 2 })
  assert.equal(tracePerformanceSummary([{ type: 'model.response', duration_ms: 90, payload: {} }]).model.value, null)
})

test('P5-06 summarizes governance signals from stable codes without reading labels', () => {
  const summary = traceSecuritySummary([
    { seq: 1, type: 'approval.requested', status: 'pending', payload: { approval_request_id: 'apr-1', message: 'localized text may change' } },
    { seq: 2, type: 'approval.requested', status: 'pending', payload: { approval_request_id: 'apr-2' } },
    { seq: 3, type: 'approval.resolved', status: 'approved', payload: { approval_request_id: 'apr-1' } },
    { seq: 4, type: 'approval.resolved', status: 'rejected', payload: { approval_request_id: 'apr-3' } },
    { seq: 5, type: 'runtime.blocked', status: 'blocked', risk_codes: ['policy.high_risk'] },
    { seq: 6, type: 'runtime.blocked', status: 'kill_switch_active', risk_codes: ['runtime.kill_switch_active'] },
    { seq: 7, type: 'runtime.killed', status: 'killed' },
  ], {
    completeness: 'gateway_partial', risk_level: 'high', risk_codes: ['trace.high_risk'],
  })
  assert.equal(summary.completeness, 'gateway_partial')
  assert.equal(summary.riskLevel, 'high')
  assert.deepEqual(summary.riskCodes, ['trace.high_risk', 'policy.high_risk', 'runtime.kill_switch_active'])
  assert.deepEqual(summary.approvals, { requested: 2, resolved: 2, pending: 1, approved: 1, denied: 1 })
  assert.equal(summary.blocked, 2)
  assert.equal(summary.killed, 1)
  assert.equal(summary.killSwitchObserved, true)

  const labelOnly = traceSecuritySummary([{ type: 'model.response', status: 'completed', payload: { message: '等待审批 kill switch blocked' } }])
  assert.equal(labelOnly.approvals.pending, 0)
  assert.equal(labelOnly.blocked, 0)
  assert.equal(labelOnly.killSwitchObserved, false)
})

test('P5-02 page is feature-protected, bilingual, and reads only redacted projections', async () => {
  const [view, router, navigation, api, i18n] = await Promise.all([
    read('../src/views/RuntimeTraceExplorer.vue'),
    read('../src/router/index.js'),
    read('../src/navigation.js'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
  ])
  assert.match(router, /path: '\/runtime-traces'/)
  assert.match(router, /feature: 'runtime_trace'/)
  assert.match(navigation, /key: '\/runtime-traces'/)
  assert.match(view, /activeView === 'conversation'/)
  assert.match(view, /value: 'trace'/)
  assert.match(view, /traceGroups/)
  assert.match(view, /toggleTurn/)
  assert.match(view, /toggleStep/)
  assert.match(view, /toggleCall/)
  assert.match(view, /eventStatusTone/)
  for (const tab of ['summary', 'payload', 'result', 'schema', 'timing', 'security']) {
    assert.match(view, new RegExp(`detailTabs\\.${tab}`))
  }
  assert.match(view, /openEventDetail/)
  assert.match(view, /tracePerformanceSummary/)
  assert.match(view, /performanceMetrics/)
  assert.match(view, /traceSecuritySummary/)
  assert.match(view, /securitySummary/)
  assert.match(view, /completenessLabel\(trace\.completeness\)/)
  assert.match(view, /riskLevelLabel\(trace\.risk_level\)/)
  for (const lane of TRACE_LANES) assert.match(i18n, new RegExp(`${lane}:`))
  assert.match(api, /\/v1\/runtime-traces'/)
  assert.match(api, /\/events`/)
  assert.doesNotMatch(view, /raw-payload|\/exports/)
  assert.doesNotMatch(view, /legacy\./)
})

test('P5-07 opens only explicit event-to-finding links and supports exact deep links', async () => {
  const [view, api, i18n] = await Promise.all([
    read('../src/views/RuntimeTraceExplorer.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
  ])
  assert.match(api, /listSecurityFindingsForTraceEvent/)
  assert.match(api, /findings\/links/)
  assert.match(view, /listSecurityFindingsForTraceEvent\(traceId, event\.event_id\)/)
  assert.match(view, /route\.query\.trace_id/)
  assert.match(view, /route\.query\.event_id/)
  assert.match(view, /event_id: eventId, page: 1, page_size: 1/)
  assert.match(view, /name: 'agent-security-scans'/)
  assert.match(view, /finding_id: finding\.finding_id/)
  assert.match(i18n, /不会按标题、风险等级或证据文本推测/)
  assert.match(i18n, /never used to infer a link/)
})

test('P5-08 normalizes stable trace and event search fields without display-text matching', () => {
  const filters = {
    turn_id: '  turn-7  ', tool_name: ' search ', request_id: ' req-9 ',
    risk_level: 'high', has_error: true,
  }
  assert.deepEqual(runtimeTraceSearchParams(filters), {
    turn_id: 'turn-7', tool_name: 'search', request_id: 'req-9', risk_level: 'high', has_error: true,
  })
  assert.deepEqual(runtimeTraceEventSearchParams(filters), {
    turn_id: 'turn-7', tool_name: 'search', request_id: 'req-9', errors_only: true,
  })
  assert.deepEqual(runtimeTraceSearchParams({ risk_level: 'all', has_error: false }), {})
})

test('P5-08 exposes the five-field evidence search ribbon and server-side filters', async () => {
  const [view, backend, i18n] = await Promise.all([
    read('../src/views/RuntimeTraceExplorer.vue'),
    read('../../backend/routers/runtime_traces.py'),
    read('../src/i18n/index.js'),
  ])
  for (const field of ['turn_id', 'tool_name', 'risk_level', 'has_error', 'request_id']) {
    assert.match(view, new RegExp(field))
  }
  assert.match(view, /runtimeTraceSearchParams/)
  assert.match(view, /runtimeTraceEventSearchParams/)
  assert.match(view, /applyTraceSearch/)
  assert.match(view, /resetTraceSearch/)
  assert.match(backend, /turn_id: str \| None = Query/)
  assert.match(backend, /has_error: bool = False/)
  assert.match(backend, /errors_only: bool = False/)
  assert.match(backend, /RuntimeTraceEvent\.type\.like\("%\.error"\)/)
  assert.match(i18n, /稳定协议字段/)
  assert.match(i18n, /stable protocol fields/)
})

test('P5-09 virtualizes a 10k-event trace without materializing every event row', () => {
  const events = Array.from({ length: 10_000 }, (_, index) => ({
    event_id: `event-${index + 1}`, seq: index + 1, type: 'tool.result',
  }))
  const first = virtualTraceWindow(events, 0, 640, { rowHeight: 96, overscan: 8 })
  assert.equal(first.start, 0)
  assert.ok(first.items.length < 32)
  assert.ok(first.bottomPadding > 900_000)

  const middle = virtualTraceWindow(events, 480_000, 640, { rowHeight: 96, overscan: 8 })
  assert.ok(middle.start > 4_900)
  assert.ok(middle.items.length < 32)
  assert.equal(middle.items[0].seq, middle.start + 1)
})

test('P5-09 page uses cursor-based lazy loading and visible-window rendering', async () => {
  const [view, backend, i18n] = await Promise.all([
    read('../src/views/RuntimeTraceExplorer.vue'),
    read('../../backend/routers/runtime_traces.py'),
    read('../src/i18n/index.js'),
  ])
  assert.match(backend, /after_seq: int \| None = Query/)
  assert.match(backend, /next_after_seq/)
  assert.match(backend, /limit\(page_size \+ 1\)/)
  assert.match(view, /loadMoreEvents/)
  assert.match(view, /virtualTraceWindow/)
  assert.match(view, /nextEventCursor/)
  assert.match(view, /@scroll="handleTraceScroll"/)
  assert.match(i18n, /按需加载/)
  assert.match(i18n, /loaded on demand/)
})

test('P5-10 exposes redacted JSON/PDF export and password-bound raw authorization', async () => {
  const [view, api, backend, schemas, i18n] = await Promise.all([
    read('../src/views/RuntimeTraceExplorer.vue'),
    read('../src/api/index.js'),
    read('../../backend/routers/runtime_traces.py'),
    read('../../backend/runtime_trace_schemas.py'),
    read('../src/i18n/index.js'),
  ])
  assert.match(view, /redacted_json/)
  assert.match(view, /redacted_pdf/)
  assert.match(view, /raw_json/)
  assert.match(view, /rawExportPassword/)
  assert.match(view, /rawExportAcknowledged/)
  assert.match(view, /canRawExport/)
  assert.match(api, /authorizeRawRuntimeTraceExport/)
  assert.match(api, /createRuntimeTraceExport/)
  assert.match(api, /downloadRuntimeTraceExport/)
  assert.match(api, /responseType: 'blob'/)
  assert.match(backend, /RAW_EXPORT_AUTHORIZATION_TTL_MINUTES = 5/)
  assert.match(backend, /_consume_raw_export_authorization/)
  assert.match(backend, /runtime_trace\.raw_export_authorized/)
  assert.match(schemas, /Literal\["json", "pdf"\]/)
  assert.match(i18n, /高敏数据出库/)
  assert.match(i18n, /Sensitive data export/)
  assert.doesNotMatch(view, /raw-payload/)
})

test('P5-12 wraps long trace identities and keeps narrow layouts responsive', async () => {
  const view = await read('../src/views/RuntimeTraceExplorer.vue')
  assert.match(view, /\.trace-identity h2 \{[^}]*overflow-wrap: anywhere;/)
  assert.match(view, /@media \(max-width: 680px\)/)
  assert.match(view, /\.query-controls \{ grid-template-columns: 1fr; \}/)
  assert.match(view, /\.trace-facts strong \{ white-space: normal; overflow-wrap: anywhere; \}/)
  assert.match(view, /\.performance-grid \{ grid-template-columns: 1fr 1fr; \}/)
})

test('P6-07 localizes ASI codes and preserves each event mapping snapshot', async () => {
  const [view, projection, i18n] = await Promise.all([
    read('../src/views/RuntimeTraceExplorer.vue'),
    read('../src/runtimeTraceView.js'),
    read('../src/i18n/index.js'),
  ])

  assert.match(view, /agenticRiskLabel, isAgenticRiskCode/)
  assert.match(view, /agenticRiskLabel\(code, t, te\)/)
  assert.match(projection, /\['risk_mapping', event\.risk_mapping\]/)
  assert.match(i18n, /智能体行为劫持/)
  assert.match(i18n, /Agent Behaviour Hijack/)
})
