import assert from 'node:assert/strict'
import test from 'node:test'
import { presentFindingEvidence } from '../src/securityFindingEvidence.js'

test('findings show their recorded transformation or the explicitly linked case method', () => {
  const relatedCase = { request_summary: { attack_method: 'Roleplay' } }
  assert.deepEqual(presentFindingEvidence({ evidence: { attack_method: 'Raw' } }, relatedCase).fields, [{ key: 'attack_method', value: 'Raw' }])
  assert.deepEqual(presentFindingEvidence({ evidence: {} }, relatedCase).fields, [{ key: 'attack_method', value: 'Roleplay' }])
  assert.deepEqual(presentFindingEvidence({ evidence: {} }).fields, [])
})

test('hashes, titles and generic descriptions do not become trigger evidence', () => {
  const result = presentFindingEvidence({ title: 'Risk', description: 'Risk detected', evidence: { prompt_sha256: 'abc', vulnerability: 'dataset', engine_commit: '123' } })
  assert.equal(result.hasSpecificEvidence, false)
  assert.equal(result.reason, '')
  assert.deepEqual(result.fields, [{ key: 'vulnerability', value: 'dataset' }])
})

test('linked case reasons and recorded conversation remain verbatim', () => {
  const result = presentFindingEvidence({ evidence: { conversation: [{ prompt: '<input>', response: '原始响应' }], suggestion: 'Review' } }, { response_summary: { evaluator_reason: 'Recorded reason' } })
  assert.equal(result.reason, 'Recorded reason')
  assert.equal(result.hasSpecificEvidence, true)
  assert.deepEqual(result.conversation, [{ prompt: '<input>', response: '原始响应' }])
  assert.equal(presentFindingEvidence({ evidence: { conversation: [{ prompt: 'context' }] } }).hasSpecificEvidence, false)
})

test('MCP indicators and CVE version evidence are presented from recorded fields', () => {
  const mcp = presentFindingEvidence({ evidence: { matched_indicators: ['ignore instructions'], parameter_signals: [{ path: '$.url', category: 'external_destination' }] } })
  assert.deepEqual(mcp.indicators, ['ignore instructions', '$.url : external_destination'])
  assert.equal(mcp.hasSpecificEvidence, true)
  const infra = presentFindingEvidence({ evidence: { cve: 'CVE-example', component_version: '1.0' } })
  assert.equal(infra.hasSpecificEvidence, true)
  assert.equal(presentFindingEvidence({ evidence: { parameter_signals: [null], conversation: [null] } }).hasSpecificEvidence, false)
})
