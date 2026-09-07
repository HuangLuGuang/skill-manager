import assert from 'node:assert/strict'
import test from 'node:test'
import { buildTrajectoryRows } from '../src/trajectoryProjection.js'

const user = content => ({ role: 'user', content })
const assistant = content => ({ role: 'assistant', content })
const request = (seq, id, messages) => ({ event_id: `e${seq}`, seq, request_id: id, source: 'model_gateway', type: 'model.request', payload: { request: { messages } } })
const response = (seq, id, message) => ({ event_id: `e${seq}`, seq, request_id: id, source: 'model_gateway', type: 'model.response', status: 'completed', duration_ms: 120, payload: { response: { choices: [{ message }] } } })

test('gateway conversation includes input and emits only the added history, preserving repeated user messages', () => {
  const input = [request(1, 'a', [user('Hello')]), response(2, 'a', assistant('Hi')),
    request(3, 'b', [user('Hello'), assistant('Hi'), user('Hello')]), response(4, 'b', assistant('Again'))]
  const before = structuredClone(input)
  const rows = buildTrajectoryRows(input)
  assert.deepEqual(rows.filter(row => row.kind === 'user' || row.kind === 'assistant').map(row => row.content), ['Hello', 'Hi', 'Hello', 'Again'])
  assert.deepEqual(rows.filter(row => row.kind === 'request').map(row => row.number), [1, 2])
  assert.equal(rows[0].events[1], input[1])
  assert.deepEqual(input, before)
})

test('history tool calls pair with results and retain both evidence events without invented timing', () => {
  const call = { role: 'assistant', content: null, tool_calls: [{ id: 'tool-a', type: 'function', function: { name: 'read_file', arguments: '{"path":"x"}' } }] }
  const rows = buildTrajectoryRows([request(1, 'a', [user('Read x')]), response(2, 'a', call),
    request(3, 'b', [user('Read x'), call, { role: 'tool', tool_call_id: 'tool-a', content: 'File content' }])])
  const tools = rows.filter(row => row.kind === 'tool')
  assert.equal(tools.length, 1)
  assert.equal(tools[0].result, 'File content')
  assert.equal(tools[0].duration, undefined)
  assert.equal(tools[0].observed, true)
  assert.deepEqual(tools[0].events.map(event => event.seq), [2, 3])
})

test('real tool execution pairs by call id and retains measured duration and failure', () => {
  const rows = buildTrajectoryRows([
    { event_id: 'call', seq: 1, type: 'tool.call', call_id: 'a', tool_name: 'bash', payload: { arguments: 'false' } },
    { event_id: 'policy', seq: 2, type: 'policy.decision', payload: { decision: 'allow' } },
    { event_id: 'result', seq: 3, type: 'tool.error', call_id: 'a', status: 'error', duration_ms: 42, payload: { error: 'exit 1' } },
  ])
  assert.equal(rows.length, 2)
  assert.equal(rows[0].duration, 42)
  assert.equal(rows[0].result, 'exit 1')
  assert.equal(rows[0].status, 'error')
  assert.equal(rows[1].lane, 'policy')
})

test('parallel model responses remain paired to their own requests', () => {
  const rows = buildTrajectoryRows([request(1, 'a', [user('A')]), request(2, 'b', [user('B')]),
    response(3, 'b', assistant('B result')), response(4, 'a', assistant('A result'))])
  const requests = rows.filter(row => row.kind === 'request')
  assert.equal(requests[0].events[1].request_id, 'a')
  assert.equal(requests[1].events[1].request_id, 'b')
  assert.deepEqual(rows.filter(row => row.kind === 'user').map(row => row.content), ['A', 'B'])
})

test('compressed and changed histories keep the changed suffix instead of globally deduplicating content', () => {
  const rows = buildTrajectoryRows([request(1, 'a', [user('first')]), response(2, 'a', assistant('answer')),
    request(3, 'b', [{ role: 'system', content: 'summary' }, user('first')])])
  assert.equal(rows.filter(row => row.kind === 'user').length, 2)
  assert.equal(rows.filter(row => row.kind === 'system').length, 1)
})

test('partial pages and unavailable payloads preserve evidence without requiring a request', () => {
  const rows = buildTrajectoryRows([response(9, 'missing', assistant('Loaded response')),
    { event_id: 'missing', seq: 10, type: 'model.request', payload: null },
    { event_id: 'error', seq: 11, type: 'model.error', payload: { error: '[upstream-error]' } }])
  assert.deepEqual(rows.map(row => row.kind), ['assistant', 'request', 'error'])
  assert.equal(rows[0].content, 'Loaded response')
})

test('SDK user events are not duplicated from model request histories', () => {
  const rows = buildTrajectoryRows([{ event_id: 'u', seq: 1, type: 'message.user', payload: { content: 'Hello' } },
    { ...request(2, 'a', [user('Hello')]), source: 'agent_sdk' }])
  assert.equal(rows.filter(row => row.kind === 'user').length, 1)
})
