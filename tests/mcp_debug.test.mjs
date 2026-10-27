import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createConnectionAttempt, formatDebugDuration, localizeDebugResponse, validConnectionTimeout } from '../web/src/utils/mcpDebug.js'

for (const value of [1, 30, 300]) {
  test(`accept connection timeout ${value}`, () => assert.equal(validConnectionTimeout(value), true))
}
for (const value of [null, undefined, '', '30', 0, 301, -1, 1.5, NaN, Infinity]) {
  test(`reject connection timeout ${String(value)}`, () => assert.equal(validConnectionTimeout(value), false))
}
for (const [value, unit, displayed] of [[0, 'Milliseconds', 0], [999, 'Milliseconds', 999], [1000, 'Seconds', 1], [3327, 'Seconds', 3.33], [59999, 'Seconds', 60], [60000, 'Minutes', 1], [75009, 'Minutes', 1.25]]) {
  test(`format ${value} milliseconds`, () => {
    const translate = (key, params) => ({ key, params })
    assert.deepEqual(formatDebugDuration(value, translate), { key: `mcpDebug.duration${unit}`, params: { value: displayed } })
  })
}

// 只执行真实请求函数验证取消与错误协议，不挂载或测试 UI 组件。
const source = readFileSync(new URL('../web/src/views/McpDebug.vue', import.meta.url), 'utf8')
const requestSource = source.slice(source.indexOf('const gatewayRequest ='), source.indexOf('\nconst addHistory ='))
const makeRequest = fetch => {
  const history = []
  const request = new Function('fetch', 'gatewayEndpoint', 'gatewayToken', 'protocolVersion', 'getCurrentLocale', 'localizeApiError', 'addHistory', 't', 'localizeDebugResponse', `let requestSequence = 0; ${requestSource}; return gatewayRequest`)(
    fetch, { value: 'http://test.invalid/mcp/test' }, { value: 'test-only-placeholder' }, { value: '' }, () => 'en-US', error => error.message,
    (...args) => history.push(args), (key, params) => `${key}:${params?.seconds ?? ''}`, localizeDebugResponse,
  )
  return { request, history }
}
const delayedResponse = (signal, delay) => new Promise((resolve, reject) => {
  signal.throwIfAborted()
  const cancel = () => { clearTimeout(timer); reject(signal.reason) }
  const timer = setTimeout(() => {
    signal.removeEventListener('abort', cancel)
    resolve({ ok: true, text: async () => '{"result":{}}' })
  }, delay)
  signal.addEventListener('abort', cancel, { once: true })
})

test('one budget covers initialize, notification and discovery', async context => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  const attempt = createConnectionAttempt(0.07)
  const { request, history } = makeRequest((url, options) => delayedResponse(options.signal, 30))
  try {
    const initialized = request('initialize', {}, false, attempt)
    context.mock.timers.tick(30)
    await initialized
    const notified = request('notifications/initialized', {}, true, attempt)
    context.mock.timers.tick(30)
    await notified
    const listed = request('tools/list', {}, false, attempt)
    context.mock.timers.tick(10)
    await assert.rejects(listed, /mcpDebug.connectionTimeout/)
    assert.equal(attempt.signal.reason, 'timeout')
    assert.deepEqual(history[2][2], { error_code: 'mcp.debug.connection_timeout', error_params: { reason: 'timeout', timeout_seconds: 0.07 } })
    assert.deepEqual(history.map(item => item[3]), [true, true, false])
    assert.equal(history[1][1].id, undefined)
    assert.ok(!JSON.stringify(history).includes('test-only-placeholder'))
  } finally { attempt.dispose() }
})

test('budget cancels a response whose body never finishes', async () => {
  const attempt = createConnectionAttempt(0.02)
  const { request } = makeRequest(async (url, options) => ({ ok: true, text: () => delayedResponse(options.signal, 1000) }))
  try { await assert.rejects(request('initialize', {}, false, attempt), /mcpDebug.connectionTimeout/) }
  finally { attempt.dispose() }
})

test('network failure has a localized message and original history evidence', async () => {
  const { request, history } = makeRequest(async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(request('initialize'), /mcpDebug.networkFailed/)
  assert.deepEqual(history[0][2], { error_code: 'mcp.debug.network_failed', error_params: { reason: 'Failed to fetch' } })
})

test('server errors preserve raw response and business error message', async () => {
  const response = { error: { message: 'upstream evidence', data: { error_code: 'mcp.upstream_timeout', error_params: { timeout_seconds: 90 } } } }
  const { request, history } = makeRequest(async () => ({ ok: true, text: async () => JSON.stringify(response) }))
  await assert.rejects(request('tools/call'), /upstream evidence/)
  assert.deepEqual(history[0][2], response)
})

test('HTTP error reason remains readable', async () => {
  const { request } = makeRequest(async () => ({ ok: false, status: 403, text: async () => '{"detail":"Permission denied"}' }))
  await assert.rejects(request('initialize'), /Permission denied/)
})

test('cancellation aborts pending requests and releases its timer', async () => {
  const attempt = createConnectionAttempt(0.02)
  const { request } = makeRequest((url, options) => delayedResponse(options.signal, 1000))
  const pending = request('initialize', {}, false, attempt)
  attempt.cancel()
  await assert.rejects(pending, reason => reason === 'cancelled')
  await new Promise(resolve => setTimeout(resolve, 30))
  assert.equal(attempt.signal.reason, 'cancelled')
})

test('completed connections release timers', async () => {
  const attempt = createConnectionAttempt(0.01)
  attempt.dispose()
  await new Promise(resolve => setTimeout(resolve, 20))
  assert.equal(attempt.signal.aborted, false)
})

test('Tool calls remain independent of the connection budget', async () => {
  const { request } = makeRequest(async (url, options) => {
    assert.equal(options.signal, undefined)
    return { ok: true, text: async () => '{"result":{"content":[]}}' }
  })
  assert.deepEqual(await request('tools/call'), { result: { content: [] } })
})

test('browser responses expose localized detail, code and original parameters', () => {
  const response = { error_code: 'mcp.debug.connection_timeout', error_params: { reason: 'timeout', timeout_seconds: 30 } }
  const original = structuredClone(response)
  for (const locale of ['zh-CN', 'en-US']) {
    const translated = localizeDebugResponse(response, (key, params) => `${locale}:${key}:${params.seconds}`)
    assert.deepEqual(translated, { detail: `${locale}:mcpDebug.connectionTimeout:30`, ...original })
    assert.deepEqual(response, original)
  }
})

test('server and successful responses retain their original fields', () => {
  for (const response of [null, { result: {} }, { error_code: 'constructor', detail: 'original' }, { detail: 'original', error_code: 'credential.invalid_or_disabled', error_params: {} }]) {
    assert.equal(localizeDebugResponse(response, () => assert.fail('unexpected translation')), response)
  }
})
