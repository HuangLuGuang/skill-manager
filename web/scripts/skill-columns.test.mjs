import test from 'node:test'
import assert from 'node:assert/strict'
import { analysisCell, readVisibleColumns, defaultSkillColumns } from '../src/utils/skillColumns.js'
test('LLM verdict stays independent of final risk and pending scans hide previous verdicts', () => {
  const record = { risk_level: 'malicious', analysis_results: { llm: { status: 'completed', risk_level: 'benign' } } }
  assert.deepEqual(analysisCell(record, 'llm'), { risk: 'benign' })
  assert.deepEqual(analysisCell({ ...record, scan_pending: true }, 'llm'), { state: 'pending' })
  assert.deepEqual(analysisCell({ analysis_results: { sandbox: { status: 'skipped', risk_level: 'LOW' } } }, 'sandbox'), { state: 'skipped' })
  assert.deepEqual(analysisCell({ analysis_results: { llm: { status: 'failed' } } }, 'llm'), { state: 'failed' })
})
test('all columns are configurable with current columns as defaults', () => {
  assert.deepEqual(readVisibleColumns({ getItem: () => null }, 'key', 'previous'), defaultSkillColumns)
  assert.equal(defaultSkillColumns.includes('skill_id'), false)
  assert.deepEqual(readVisibleColumns({ getItem: () => '["skill_id"]' }, 'key', 'previous'), ['skill_id'])
  assert.deepEqual(readVisibleColumns({ getItem: () => '["sandbox","llm","name"]' }, 'key', 'previous'), ['name', 'llm', 'sandbox'])
  assert.deepEqual(readVisibleColumns({ getItem: () => 'bad JSON' }, 'key', 'previous'), defaultSkillColumns)
})
test('existing optional column choices are retained', () => {
  assert.deepEqual(readVisibleColumns({ getItem: key => key === 'previous' ? '["sandbox"]' : null }, 'key', 'previous'), [...defaultSkillColumns, 'sandbox'])
})
test('empty or obsolete saved column selections restore defaults', () => {
  assert.deepEqual(readVisibleColumns({ getItem: () => '[]' }, 'key', 'previous'), defaultSkillColumns)
  assert.deepEqual(readVisibleColumns({ getItem: () => '["removed-column"]' }, 'key', 'previous'), defaultSkillColumns)
  assert.deepEqual(readVisibleColumns({ getItem: () => '["removed-column","name"]' }, 'key', 'previous'), ['name'])
})
