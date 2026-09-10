import test from 'node:test'
import assert from 'node:assert/strict'
import { baseCompile } from '@intlify/message-compiler'
import { policyActions, actionPolicy, allowedActions, recommendedActions } from '../src/utils/policySettings.js'
import { policySettingsMessages } from '../src/i18n/policySettings.js'
import { policySimulationMessages } from '../src/i18n/policySimulation.js'

test('overlapping legacy decisions display the effective rejection and save one action', () => {
  const actions = policyActions({
    auto_reject_risk: ['EXTREME'], require_human_review: ['HIGH', 'MEDIUM'],
  })
  assert.deepEqual(actions, recommendedActions)
  assert.deepEqual(actionPolicy(actions), {
    auto_approve_risk: ['benign'],
    auto_reject_risk: ['malicious'], require_human_review: ['suspicious'],
  })
})

test('omitted and empty risk lists retain the backend default outcomes', () => {
  assert.deepEqual(policyActions({}), recommendedActions)
  assert.deepEqual(policyActions({ auto_reject_risk: [], require_human_review: [] }), recommendedActions)
})

test('malicious risk can require review when automatic rejection is not configured', () => {
  const actions = policyActions({ auto_reject_risk: [], require_human_review: ['malicious', 'benign'] })
  assert.deepEqual(actions, { benign: 'VETTED', suspicious: 'VETTED', malicious: 'VETTED' })
  assert.deepEqual(policyActions(actionPolicy(actions)), actions)
})

test('existing risk aliases, case and whitespace follow the server policy', () => {
  const actions = policyActions({ auto_reject_risk: [' medium ', ' BeNiGn '], require_human_review: ['CRITICAL'] })
  assert.deepEqual(actions, { benign: 'REJECTED', suspicious: 'REJECTED', malicious: 'VETTED' })
})

test('every offered action combination round-trips without changing its outcome', () => {
  for (const benign of allowedActions('benign')) {
    for (const suspicious of allowedActions('suspicious')) {
      for (const malicious of allowedActions('malicious')) {
        const actions = { benign, suspicious, malicious }
        assert.deepEqual(policyActions(actionPolicy(actions)), actions)
      }
    }
  }
  assert.ok(allowedActions('suspicious').includes('APPROVED'))
  assert.ok(!allowedActions('malicious').includes('APPROVED'))
})

test('suspicious automatic approval persists separately from the Prompt threshold', () => {
  const actions = { ...recommendedActions, suspicious: 'APPROVED' }
  const policy = { auto_approve_max_risk: 'benign', ...actionPolicy(actions) }
  assert.deepEqual(policy.auto_approve_risk, ['benign', 'suspicious'])
  assert.deepEqual(policyActions(policy), actions)
})

test('explicit review and rejection take precedence over overlapping approval entries', () => {
  const policy = { auto_approve_risk: ['suspicious'], require_human_review: ['suspicious'], auto_reject_risk: [] }
  assert.equal(policyActions(policy).suspicious, 'VETTED')
  assert.equal(policyActions({ ...policy, auto_reject_risk: ['suspicious'] }).suspicious, 'REJECTED')
})

const flatten = (value, prefix = '') => Object.entries(value).flatMap(([key, item]) => (
  typeof item === 'string' ? [[prefix + key, item]] : flatten(item, prefix + key + '.')
))
test('all policy messages have matching locales, valid syntax and matching placeholders', () => {
  const zh = Object.fromEntries(flatten({ settings: policySettingsMessages['zh-CN'], simulation: policySimulationMessages['zh-CN'] }))
  const en = Object.fromEntries(flatten({ settings: policySettingsMessages['en-US'], simulation: policySimulationMessages['en-US'] }))
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort())
  const params = message => [...message.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort()
  for (const [key, value] of Object.entries(zh)) {
    assert.deepEqual(params(value), params(en[key]), key)
    for (const message of [value, en[key]]) baseCompile(message, { onError: error => { throw error } })
  }
})
