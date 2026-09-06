import test from 'node:test'
import assert from 'node:assert/strict'
import { comparisonCandidates, mergeLlmConfigFromForm, normalizeLlmConfigForForm, selectCompatiblePolicyId } from '../src/securityScanWorkflow.js'

test('LLM form separates dedicated fields without losing advanced config', () => {
  const result = normalizeLlmConfigForForm({ model: 'ollama/qwen', chat_completions_path: '/api/chat', timeout_ms: 15000, headers: { 'x-scope': 'test' }, custom: { keep: true } })
  assert.deepEqual(result, { model: 'ollama/qwen', chat_completions_path: '/api/chat', timeout_ms: 15000, advanced: { headers: { 'x-scope': 'test' }, custom: { keep: true } } })
})

test('multiple compatible policies remain explicitly unselected', () => {
  assert.equal(selectCompatiblePolicyId([]), undefined)
  assert.equal(selectCompatiblePolicyId([{ policy_id: 'one' }, { policy_id: 'two' }]), undefined)
  assert.equal(selectCompatiblePolicyId([{ policy_id: 'one' }]), 'one')
})

test('LLM edits round-trip authentication settings and exact timeout without mutating the source', () => {
  const config = { model: 'qwen3:1.7b', chat_completions_path: '/v1/chat/completions', timeout_ms: 15001, api_protocol: 'openai_chat_completions', credential_header: 'Authorization', credential_prefix: 'Bearer ', headers: { 'X-Scope': 'test' } }
  const fields = normalizeLlmConfigForForm(config)
  const form = { llm_model: fields.model, llm_chat_completions_path: fields.chat_completions_path, llm_timeout_ms: fields.timeout_ms }
  assert.deepEqual(mergeLlmConfigFromForm(fields.advanced, form), config)
  const edited = mergeLlmConfigFromForm(fields.advanced, { ...form, llm_model: ' new-model ', llm_timeout_ms: 1000 })
  assert.equal(edited.model, 'new-model')
  assert.equal(edited.timeout_ms, 1000)
  assert.deepEqual(edited.headers, config.headers)
  assert.equal(config.model, 'qwen3:1.7b')
})

test('comparison candidates ignore report filters but preserve compatibility and order', () => {
  const current = { task_id: 'current', target_id: 'target', scan_kind: 'llm_redteam_scan', status: 'failed', created_at: '2026-01-03T00:00:00Z' }
  const tasks = [current, { task_id: 'older', target_id: 'target', scan_kind: 'llm_redteam_scan', status: 'succeeded', completed_at: '2026-01-01T00:00:00Z' }, { task_id: 'other', target_id: 'other', scan_kind: 'llm_redteam_scan', status: 'succeeded', completed_at: '2026-01-02T00:00:00Z' }]
  assert.deepEqual(comparisonCandidates(tasks, current).map(item => item.task_id), ['older'])
})

test('comparison dates treat naive timestamps as UTC and reject invalid dates', () => {
  const current = { task_id: 'current', target_id: 't', scan_kind: 'k', created_at: '2026-01-03 00:00:00' }
  const tasks = [{ task_id: 'naive', target_id: 't', scan_kind: 'k', status: 'succeeded', completed_at: '2026-01-02 00:00:00' }, { task_id: 'invalid', target_id: 't', scan_kind: 'k', status: 'succeeded', completed_at: 'no-date' }]
  assert.deepEqual(comparisonCandidates(tasks, current).map(item => item.task_id), ['naive'])
  const mixed = [
    { ...tasks[0], task_id: 'later', completed_at: '2026-01-03T00:00:01Z' },
    { ...tasks[0], task_id: 'earlier', completed_at: '2026-01-02T23:59:59Z' },
    { ...tasks[0], task_id: 'wrong-kind', scan_kind: 'other' },
    { ...tasks[0], task_id: 'failed', status: 'failed' },
    ...tasks,
  ]
  assert.deepEqual(comparisonCandidates(mixed, current).map(item => item.task_id), ['earlier', 'naive'])
  assert.deepEqual(comparisonCandidates(mixed, { ...current, created_at: 'invalid' }), [])
})
