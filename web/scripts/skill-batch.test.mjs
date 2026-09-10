import assert from 'node:assert/strict'
import test from 'node:test'
import { canRunSkillAction, runSkillBatch } from '../src/utils/skillBatch.js'
import { skillBatchMessages } from '../src/i18n/skillBatch.js'

test('batch eligibility follows scan and lifecycle status', () => {
  assert.equal(canRunSkillAction('rescan', { status: 'APPROVED', scan_pending: true }), false)
  assert.equal(canRunSkillAction('rescan', { status: 'PENDING' }), false)
  assert.equal(canRunSkillAction('rescan', { status: 'REJECTED' }), true)
  assert.equal(canRunSkillAction('cancel', { status: 'PENDING' }), true)
  assert.equal(canRunSkillAction('cancel', { status: 'APPROVED' }), false)
  assert.equal(canRunSkillAction('cancel', { status: 'APPROVED', scan_pending: true }), true)
  assert.equal(canRunSkillAction('cancel', { status: 'VETTED', scan_pending: true }), true)
  assert.equal(canRunSkillAction('delete', { status: 'APPROVED' }), true)
})

test('mixed batch continues after failure and does not submit ineligible rows', async () => {
  const records = [
    { skill_id: 'pending', status: 'PENDING' },
    { skill_id: 'failed', status: 'REJECTED' },
    { skill_id: 'ok', status: 'APPROVED' },
  ]
  const calls = []
  const result = await runSkillBatch(records, 'rescan', async record => {
    calls.push(record.skill_id)
    if (record.skill_id === 'failed') throw new Error('request failed')
  })
  assert.deepEqual(calls, ['failed', 'ok'])
  assert.deepEqual(result.succeeded, [records[2]])
  assert.equal(result.failed[0].record, records[1])
  assert.deepEqual(result.skipped, [{ record: records[0], reason: 'already_scanning' }])
  assert.equal(result.action, 'rescan')
})

test('cancellation skips completed states and retains their status for the result message', async () => {
  const records = ['APPROVED', 'VETTED', 'REJECTED'].map(status => ({ skill_id: status, status }))
  const result = await runSkillBatch(records, 'cancel', () => assert.fail('No cancellation should be submitted'))
  assert.equal(result.succeeded.length, 0)
  assert.deepEqual(result.skipped.map(item => [item.record.status, item.reason]), records.map(record => [record.status, 'no_pending_scan']))
})

test('server no-op outcomes are skipped using the latest returned status', async () => {
  const result = await runSkillBatch([{ skill_id: 'id', status: 'PENDING', scan_pending: true }], 'cancel', async () => ({ outcome: 'no_pending_scan', status: 'APPROVED', scan_pending: false }))
  assert.equal(result.succeeded.length, 0)
  assert.equal(result.skipped[0].record.status, 'APPROVED')
  assert.equal(result.skipped[0].record.scan_pending, false)
  const rescan = await runSkillBatch([{ skill_id: 'id', status: 'VETTED' }], 'rescan', async () => ({ outcome: 'already_scanning', status: 'VETTED' }))
  assert.equal(rescan.succeeded.length, 0)
  assert.equal(rescan.skipped[0].reason, 'already_scanning')
})

test('batch translations have matching keys and interpolation parameters', () => {
  const zh = skillBatchMessages['zh-CN']
  const en = skillBatchMessages['en-US']
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort())
  for (const key of Object.keys(zh)) {
    assert.deepEqual(zh[key].match(/\{\w+\}/g), en[key].match(/\{\w+\}/g))
  }
})
