import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DEFAULT_FEATURE_FLAGS,
  FEATURE_AGENT_SECURITY_SCANNING,
  FEATURE_RUNTIME_TRACE,
  filterNavigationByFeatures,
  normalizeFeatureFlags,
} from '../src/features.js'
import { navigationItems } from '../src/navigation.js'

const flattenKeys = (items) => items.flatMap(item => [item.key, ...flattenKeys(item.children || [])])

test('agent security UI fails closed only before capabilities are loaded', () => {
  assert.deepEqual(normalizeFeatureFlags(), DEFAULT_FEATURE_FLAGS)
  const keys = flattenKeys(filterNavigationByFeatures(navigationItems, normalizeFeatureFlags()))
  assert.ok(!keys.includes('agent-security-vnext'))
  assert.ok(!keys.includes('/agent-security/scans'))
  assert.ok(!keys.includes('/agent-security/baseline'))
  assert.ok(!keys.includes('/runtime-traces'))
  assert.ok(!keys.includes('/runtime-traces/baseline'))
})

test('each enabled feature reveals only its own menu', () => {
  const scanKeys = flattenKeys(filterNavigationByFeatures(navigationItems, {
    [FEATURE_AGENT_SECURITY_SCANNING]: true,
  }))
  assert.ok(scanKeys.includes('agent-security-vnext'))
  assert.ok(scanKeys.includes('/agent-security/scans'))
  assert.ok(scanKeys.includes('/agent-security/baseline'))
  assert.ok(!scanKeys.includes('/runtime-traces/baseline'))
  assert.ok(!scanKeys.includes('/runtime-traces'))

  const traceKeys = flattenKeys(filterNavigationByFeatures(navigationItems, {
    [FEATURE_RUNTIME_TRACE]: true,
  }))
  assert.ok(traceKeys.includes('agent-security-vnext'))
  assert.ok(!traceKeys.includes('/agent-security/scans'))
  assert.ok(!traceKeys.includes('/agent-security/baseline'))
  assert.ok(traceKeys.includes('/runtime-traces/baseline'))
  assert.ok(traceKeys.includes('/runtime-traces'))
})

test('truthy strings do not accidentally enable a feature', () => {
  const keys = flattenKeys(filterNavigationByFeatures(navigationItems, {
    [FEATURE_AGENT_SECURITY_SCANNING]: 'true',
    [FEATURE_RUNTIME_TRACE]: 1,
  }))
  assert.ok(!keys.includes('agent-security-vnext'))
})
