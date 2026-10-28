import assert from 'node:assert/strict'
import test from 'node:test'
import { isPendingDebugApproval, maskDebugRequest } from '../web/src/utils/mcpDebug.js'

test('history masks nested credentials without changing sent values or JSON types', () => {
  const request = { jsonrpc: '2.0', id: 12, method: 'tools/call', params: { name: 'echo', arguments: {
    text: '原文', enabled: false, count: 0, empty: null, nested: [{ 'API-Key': 'secret', text: 'keep' }],
    access_token: 'token', credential: 'credential', password: 'password', private_key: 'key',
  } } }
  const before = structuredClone(request)
  const display = maskDebugRequest(request)
  assert.deepEqual(request, before)
  assert.equal(display.id, request.id)
  assert.deepEqual(display.params.arguments, {
    text: '原文', enabled: false, count: 0, empty: null, nested: [{ 'API-Key': '******', text: 'keep' }],
    access_token: '******', credential: '******', password: '******', private_key: '******',
  })
})


test('pending approval requires the structured pending Tool call response', () => {
  const response = { jsonrpc: '2.0', id: 3, error: { code: -32002, data: {
    approval_required: true, status: 'pending',
  } } }
  const before = structuredClone(response)
  assert.equal(isPendingDebugApproval('tools/call', response), true)
  assert.equal(isPendingDebugApproval('tools/list', response), false)
  for (const status of ['approved', 'rejected', 'expired', 'used', undefined]) {
    assert.equal(isPendingDebugApproval('tools/call', { error: { data: { approval_required: true, status } } }), false)
  }
  for (const approval_required of [false, 'true', undefined]) {
    assert.equal(isPendingDebugApproval('tools/call', { error: { data: { approval_required, status: 'pending' } } }), false)
  }
  for (const other of [null, {}, { result: {} }, { error: { message: 'MCP Tool 调用等待管理员审批' } }, { error_code: 'mcp.debug.network_failed' }]) {
    assert.equal(isPendingDebugApproval('tools/call', other), false)
  }
  assert.deepEqual(response, before)
})
