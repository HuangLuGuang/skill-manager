import test from 'node:test'
import assert from 'node:assert/strict'
import { advancedConfigErrors, configRequestError, integerLimits, stepInteger } from '../web/src/utils/advancedConfig.js'

test('step buttons respect ranges and original steps without replacing invalid drafts', () => {
  assert.equal(stepInteger('30', 1, 5, 180), '31')
  assert.equal(stepInteger('12000', 1000, 2000, 50000), '13000')
  assert.equal(stepInteger('3000', -500, 500, 20000), '2500')
  for (const value of ['abc', '', '-1', '30.6', '1e2', '181']) {
    assert.equal(stepInteger(value, 1, 5, 180), value)
  }
  assert.equal(stepInteger(180, 1, 5, 180), 180)
  assert.equal(stepInteger('5', -1, 5, 180), '5')
})

test('request failures render in the selected language and retain unknown server detail', () => {
  assert.equal(configRequestError({}, 'zh-CN'), '请求失败，请重试。')
  assert.equal(configRequestError({}, 'en-US'), 'Request failed. Please retry.')
  const failure = { code: 'server.internal_error', message: '服务器内部错误' }
  assert.equal(configRequestError(failure, 'en-US'), 'Internal server error')
  assert.equal(configRequestError(failure, 'zh-CN'), '服务器内部错误')
  assert.equal(configRequestError({ code: 'new.code', message: 'Upstream detail' }, 'zh-CN'), 'Upstream detail')
})

const llm = { enabled: true, model: 'test-model', timeout_seconds: 30, max_files: 6, max_manifest_chars: 12000, max_file_chars: 3000 }
const sandbox = { enabled: true, runtime: 'docker', image: 'agent-manager-sandbox-runtime:latest', timeout_seconds: 15, pids_limit: 64, memory_limit: '256m', cpu_limit: '1.0', network_mode: 'none', read_only_rootfs: true, clear_remote_api_key: false }

test('integer boundaries reject malformed drafts without mutation', () => {
  for (const [group, limits] of Object.entries(integerLimits)) {
    for (const [field, [min, max]] of Object.entries(limits)) {
      for (const value of [min, max, String(min), String(max)]) {
        assert.equal(advancedConfigErrors(group, { ...(group === 'llm' ? llm : sandbox), [field]: value })[field], undefined)
      }
      for (const value of [min - 1, max + 1, '', null, true, '1e2', 'abc', 1.5, 'NaN', 'Infinity']) {
        const draft = { ...(group === 'llm' ? llm : sandbox), [field]: value }
        const before = JSON.stringify(draft)
        assert.equal(advancedConfigErrors(group, draft)[field].code, 'config.integer', `${group}.${field}: ${value}`)
        assert.equal(JSON.stringify(draft), before)
      }
    }
  }
})

test('CPU and memory validate syntax and resource boundaries', () => {
  for (const cpu_limit of ['0.01', '0.5', '2.50', '64']) assert.equal(advancedConfigErrors('sandbox', { ...sandbox, cpu_limit }).cpu_limit, undefined)
  for (const cpu_limit of ['', 'abc', '0', '-1', 'NaN', 'Infinity', '1e2', '64.01', '0.001']) assert.equal(advancedConfigErrors('sandbox', { ...sandbox, cpu_limit }).cpu_limit.code, 'config.cpu')
  for (const memory_limit of ['6m', '256m', '1g', '64G', '6291456b']) assert.equal(advancedConfigErrors('sandbox', { ...sandbox, memory_limit }).memory_limit, undefined)
  for (const memory_limit of ['', 'invalid', '0m', '-1m', '1.5g', '5m', '65g']) assert.equal(advancedConfigErrors('sandbox', { ...sandbox, memory_limit }).memory_limit.code, 'config.memory')
})

test('runtime-specific values and model requirement follow the active mode', () => {
  assert.deepEqual(advancedConfigErrors('sandbox', { ...sandbox, remote_url: 'bad', remote_api_key: 'a b' }), {})
  const remote = { ...sandbox, runtime: 'remote', remote_url: 'http://localhost:8194', remote_api_key: '', memory_limit: 'bad', cpu_limit: 'bad', pids_limit: '' }
  assert.deepEqual(advancedConfigErrors('sandbox', remote), {})
  assert.equal(advancedConfigErrors('sandbox', { ...remote, remote_url: '' }).remote_url.code, 'sandbox.url_required')
  for (const remote_api_key of ['a b', 'a\nb', 'x'.repeat(4097)]) assert.equal(advancedConfigErrors('sandbox', { ...remote, remote_api_key }).remote_api_key.code, 'config.key')
  assert.equal(advancedConfigErrors('sandbox', { ...remote, remote_api_key: 'new', clear_remote_api_key: true }).remote_api_key.code, 'config.key_conflict')
  assert.equal(advancedConfigErrors('llm', { ...llm, model: '' }).model.code, 'config.required')
  assert.deepEqual(advancedConfigErrors('llm', { ...llm, enabled: false, model: '' }), {})
})
