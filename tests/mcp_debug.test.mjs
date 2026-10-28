import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { usesRawArguments, parseRawArguments, createConnectionAttempt, formatDebugDuration, localizeDebugResponse, validConnectionTimeout } from '../web/src/utils/mcpDebug.js'

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

// 执行真实参数初始化及调用逻辑，只验证 Schema 到请求的契约，不挂载 UI。
const parameterFieldsSource = source.slice(source.indexOf('const toolFields ='), source.indexOf('\nconst connectionLabel ='))
const parameterDefaultsSource = source.slice(source.indexOf('const exampleValue ='), source.indexOf('\nwatch(selectedToolName'))
const toolCallSource = source.slice(source.indexOf('const callTool ='), source.indexOf('\nconst copyClientConfig ='))
const makeToolCall = schema => {
  const sent = []
  const warnings = []
  const run = new Function('selectedTool', 'computed', 'request', 'message', 'text', 'phrase', 'usesRawArguments', 'parseRawArguments', `
    const rawArgumentText = { value: '{}' }
    const rawArgumentError = { value: '' }
    const rawArgumentInput = { value: null }
    const calling = { value: false }
    const argumentValues = { value: {} }
    const complexArgumentTexts = { value: {} }
    const callResult = { value: null }
    const pretty = value => JSON.stringify(value, null, 2)
    ${parameterFieldsSource}
    ${parameterDefaultsSource}
    ${toolCallSource}
    return { resetArguments, callTool, argumentValues, complexArgumentTexts, toolFields, rawArgumentText, rawArgumentError }
  `)(
    { value: { name: 'test_tool', inputSchema: schema } },
    getter => ({ get value() { return getter() } }),
    async (method, params) => { sent.push({ method, params }); return { result: {} } },
    { warning: value => warnings.push(value), success: () => {}, error: assert.fail },
    chinese => chinese, key => key, usesRawArguments, parseRawArguments,
  )
  run.resetArguments()
  return { ...run, sent, warnings }
}

for (const value of [true, false, 0, '', null, 'fixed', [], [1, '2'], {}, { nested: [false, null] }]) {
  for (const required of [true, false]) {
    test(`const ${JSON.stringify(value)} survives initialization, reset and submission; required=${required}`, async () => {
      const form = makeToolCall({
        type: 'object',
        properties: { confirm: { const: value, default: 'different', enum: ['different'] } },
        required: required ? ['confirm'] : [],
      })
      assert.deepEqual(form.argumentValues.value.confirm, value)
      assert.equal(form.toolFields.value[0].kind, 'const')
      form.argumentValues.value.confirm = 'changed draft'
      await form.callTool()
      assert.deepEqual(form.sent[0], { method: 'tools/call', params: { name: 'test_tool', arguments: { confirm: value } } })
      assert.deepEqual(form.warnings, [])
      form.resetArguments()
      assert.deepEqual(form.argumentValues.value.confirm, value)
    })
  }
}

test('ordinary arguments retain defaults, required checks and array/JSON conversion', async () => {
  const form = makeToolCall({
    type: 'object',
    properties: {
      confirm: { type: 'boolean', const: true },
      name: { type: 'string' },
      enabled: { type: 'boolean', default: false },
      numbers: { type: 'array', items: { type: 'integer' } },
      config: { type: 'object' },
      optional: { type: 'string' },
    },
    required: ['confirm', 'name', 'numbers', 'config'],
  })
  await form.callTool()
  assert.equal(form.sent.length, 0)
  assert.equal(form.warnings.length, 1)
  form.argumentValues.value.name = 'record'
  form.argumentValues.value.numbers = ['1', '2']
  form.complexArgumentTexts.value.config = '{"key":true}'
  await form.callTool()
  assert.deepEqual(form.sent[0].params.arguments, { confirm: true, name: 'record', enabled: false, numbers: [1, 2], config: { key: true } })
  form.argumentValues.value.numbers = ['invalid']
  await form.callTool()
  assert.equal(form.sent.length, 1)
  assert.equal(form.warnings.length, 2)
})


for (const schema of [
  { oneOf: [{ required: ['name'] }, { required: ['id'] }] },
  { anyOf: [{ properties: { name: { type: 'string' } } }] },
  { allOf: [{ properties: { name: { type: 'string' } } }] },
  { $ref: '#/$defs/input' }, { $dynamicRef: '#input' },
  { type: 'object', additionalProperties: { type: 'string' }, minProperties: 1 },
  { type: 'object', properties: { name: { type: 'string' } }, additionalProperties: true },
  { type: 'object', patternProperties: { '^x': { type: 'string' } } },
  { if: { required: ['kind'] }, then: { required: ['name'] } },
  { dependentSchemas: { kind: { required: ['name'] } } },
  { type: 'object' }, {},
]) {
  test(`root Schema uses raw arguments: ${JSON.stringify(schema)}`, () => {
    assert.equal(usesRawArguments(schema), true)
  })
}

test('ordinary properties and closed empty objects retain the form', () => {
  for (const schema of [
    { properties: { name: { type: 'string' } } },
    { properties: { fixed: { const: null }, config: { type: 'object' } }, additionalProperties: false },
    { type: 'object', additionalProperties: false },
  ]) assert.equal(usesRawArguments(schema), false)
})

for (const input of ['', ' ', '{', '{"name":}', '{"name":"a",}', "{'name':'张三'}"]) {
  test(`invalid JSON is retained and not submitted: ${input}`, async () => {
    const form = makeToolCall({ oneOf: [{ required: ['name'] }] })
    form.rawArgumentText.value = input
    await form.callTool()
    assert.equal(form.sent.length, 0)
    assert.equal(form.rawArgumentText.value, input)
    assert.equal(form.rawArgumentError.value, 'mcpDebug.rawArgumentsInvalidJson')
  })
}
for (const input of ['null', '[]', '[{}]', '"text"', '0', 'true']) {
  test(`reject non-object JSON: ${input}`, () => {
    assert.deepEqual(parseRawArguments(input), { error: 'mcpDebug.rawArgumentsObjectRequired' })
  })
}

test('raw parameters preserve keys, JSON types, empty object and reset state', async () => {
  const form = makeToolCall({ additionalProperties: true })
  for (const input of ['{}', '{"name":"中文","id":1,"enabled":false,"empty":"","none":null,"list":[1,"2"],"nested":{"x":true},"__proto__":{"x":1}}']) {
    form.rawArgumentText.value = input
    await form.callTool()
    assert.deepEqual(form.sent.at(-1).params.arguments, JSON.parse(input))
  }
  form.rawArgumentError.value = 'mcpDebug.rawArgumentsInvalidJson'
  form.resetArguments()
  assert.equal(form.rawArgumentText.value, '{}')
  assert.equal(form.rawArgumentError.value, '')
})
