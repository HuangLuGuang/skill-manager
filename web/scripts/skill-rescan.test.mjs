import assert from 'node:assert/strict'
import test from 'node:test'
import { rescanCapabilities, rescanOptions } from '../src/utils/skillRescan.js'

const ready = { skillspector_available: true, sandbox_enabled: true, sandbox_available: true, llm_enabled: true, llm_model: 'model' }

test('previous mode enables mandatory rule analysis and inherits optional analysis settings', () => {
  assert.deepEqual(rescanOptions('previous', { use_llm: true }, ready), { use_behavioral: true })
})
test('custom mode sends explicit false values to turn off previous options', () => {
  assert.deepEqual(rescanOptions('custom', { use_skillspector: true }, ready), {
    use_behavioral: true, use_skillspector: true, use_sandbox: false, use_llm: false,
  })
})
test('enabled gateway model can be selected for LLM analysis', () => {
  const status = { ...ready, llm_api_key_configured: false }
  assert.equal(rescanCapabilities(status).use_llm, true)
  assert.equal(rescanOptions('custom', { use_llm: true }, status).use_llm, true)
})
test('LLM analysis requires an enabled configuration and a selected model', () => {
  assert.equal(rescanCapabilities({ ...ready, llm_enabled: false }).use_llm, false)
  assert.equal(rescanCapabilities({ ...ready, llm_model: '' }).use_llm, false)
})
test('unavailable scanning capabilities cannot be selected', () => {
  assert.deepEqual(rescanOptions('custom', { use_llm: true, use_sandbox: true, use_skillspector: true }, null), {
    use_behavioral: true, use_skillspector: false, use_sandbox: false, use_llm: false,
  })
})
