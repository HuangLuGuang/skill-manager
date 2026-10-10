import assert from 'node:assert/strict'
import test from 'node:test'
import { skillDetailMessages } from '../web/src/i18n/skillDetail.js'
import { formatLlmFailureReason, llmFailureReason } from '../web/src/utils/decisionFlow.js'

const report = status => ({ analyzer_timings: { llm: { status } } })
const notes = ['unrelated note', '[LLM] analysis skipped: HTTP 401: invalid API key']
test('failed analysis preserves the recorded reason and reports missing reasons', () => {
  assert.equal(llmFailureReason(report('failed'), notes), 'HTTP 401: invalid API key')
  assert.equal(llmFailureReason(report('failed')), '')
  assert.equal(llmFailureReason(report('failed'), [null, '[LLM] success']), '')
})
test('legacy reports recover errors only when no explicit state or result exists', () => {
  assert.equal(llmFailureReason({}, notes), 'HTTP 401: invalid API key')
  assert.equal(llmFailureReason({ llm_analysis: { report: 'done' } }, notes), null)
  assert.equal(llmFailureReason(null), null)
})
test('successful and disabled states do not reuse old error notes', () => {
  for (const status of ['completed', 'disabled', 'skipped', 'pending', 'unavailable']) {
    assert.equal(llmFailureReason(report(status), notes), null)
  }
})
test('multiple recorded reasons retain newlines and original text', () => {
  assert.equal(llmFailureReason(report('failed'), ['[LLM] analysis skipped: <error>\n详情', '[LLM] analysis skipped: timeout']), '<error>\n详情\ntimeout')
})


test('saved gateway errors translate only the platform prefix in both languages', () => {
  const raw = '502: 上游模型接口失败: 401 Authentication Fails (governor)'
  const en = key => skillDetailMessages['en-US'][key.split('.')[1]]
  const zh = key => skillDetailMessages['zh-CN'][key.split('.')[1]]
  assert.equal(formatLlmFailureReason(raw, en), '502: Upstream model request failed: 401 Authentication Fails (governor)')
  assert.equal(formatLlmFailureReason(raw, zh), raw)
  assert.equal(formatLlmFailureReason('上游模型接口失败: 401 原始中文', en), 'Upstream model request failed: 401 原始中文')
  assert.equal(formatLlmFailureReason('401 response: 上游模型接口失败: raw', en), '401 response: 上游模型接口失败: raw')
  assert.equal(formatLlmFailureReason('timeout', en), 'timeout')
  assert.equal(formatLlmFailureReason(null, en), null)
  assert.equal(formatLlmFailureReason('', en), '')
  assert.equal(formatLlmFailureReason(raw + '\n' + raw, en), Array(2).fill('502: Upstream model request failed: 401 Authentication Fails (governor)').join('\n'))
})
