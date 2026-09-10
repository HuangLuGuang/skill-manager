import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { parse as parseScript } from '@babel/parser'
import { parse } from '@vue/compiler-sfc'

if (!globalThis.localStorage) {
  Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => null } })
}
if (!globalThis.navigator) {
  Object.defineProperty(globalThis, 'navigator', { value: { language: 'zh-CN' } })
}

const { i18n } = await import('../src/i18n/index.js')
const focusedNamespaces = [
  'agentSecurity',
  'agentSecurityScans',
  'runtimeTraceExplorer',
  'assetLifecycle',
  'scanSchedule',
]
const focusedViews = [
  '../src/views/components/FindingEvidence.vue',
  '../src/views/AgentSecurityScans.vue',
  '../src/views/RuntimeTraceExplorer.vue',
  '../src/views/components/TargetGovernance.vue',
  '../src/views/components/ScanTimingFields.vue',
  '../src/views/components/ScanSchedules.vue',
]
const chinesePattern = /[\u3400-\u9fff]/

const flatten = (value, prefix = '', output = new Map()) => {
  for (const [key, item] of Object.entries(value || {})) {
    const path = prefix ? `${prefix}.${key}` : key
    if (item && typeof item === 'object' && !Array.isArray(item)) flatten(item, path, output)
    else output.set(path, item)
  }
  return output
}

const walk = (node, visitor, ancestors = []) => {
  if (!node || typeof node !== 'object') return
  visitor(node, ancestors)
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'start', 'end', 'extra'].includes(key)) continue
    const next = [...ancestors, { node, key }]
    if (Array.isArray(value)) value.forEach(item => walk(item, visitor, next))
    else if (value && typeof value === 'object' && value.type) walk(value, visitor, next)
  }
}

const callName = node => {
  if (!node || !['CallExpression', 'OptionalCallExpression'].includes(node.type)) return ''
  if (node.callee.type === 'Identifier') return node.callee.name
  return node.callee.property?.name || node.callee.property?.value || ''
}

test('P5-11 keeps all new security namespaces complete in Simplified Chinese and English', () => {
  const zh = i18n.global.getLocaleMessage('zh-CN')
  const en = i18n.global.getLocaleMessage('en-US')
  for (const namespace of focusedNamespaces) {
    const zhMessages = flatten(zh[namespace])
    const enMessages = flatten(en[namespace])
    assert.deepEqual([...zhMessages.keys()].sort(), [...enMessages.keys()].sort(), namespace)
    for (const [key, value] of zhMessages) assert.equal(typeof value, 'string', `${namespace}.${key} zh-CN`)
    for (const [key, value] of enMessages) {
      assert.equal(typeof value, 'string', `${namespace}.${key} en-US`)
      assert.doesNotMatch(value, chinesePattern, `${namespace}.${key} contains Chinese in en-US`)
    }
  }
})

test('P5-11 new pages use semantic keys and never branch on localized display text', async () => {
  for (const file of focusedViews) {
    const source = await readFile(new URL(file, import.meta.url), 'utf8')
    assert.doesNotMatch(source, /legacy\./, file)
    const { descriptor } = parse(source)
    for (const block of [descriptor.script, descriptor.scriptSetup]) {
      if (!block?.content) continue
      const ast = parseScript(block.content, {
        sourceType: 'module',
        plugins: ['topLevelAwait', 'optionalChaining', 'nullishCoalescingOperator'],
      })
      walk(ast, (node, ancestors) => {
        if (node.type === 'StringLiteral' && chinesePattern.test(node.value)) {
          assert.fail(`${file} contains hard-coded Chinese script text: ${node.value}`)
        }
        if (callName(node) !== 't') return
        const usedAsCondition = ancestors.some(({ node: parent, key }) =>
          key === 'test' && ['IfStatement', 'ConditionalExpression', 'WhileStatement', 'DoWhileStatement', 'ForStatement'].includes(parent.type))
        const compared = ancestors.some(({ node: parent }) =>
          parent.type === 'BinaryExpression' && ['==', '===', '!=', '!=='].includes(parent.operator))
        const matched = ancestors.some(({ node: parent }) =>
          parent !== node && ['includes', 'startsWith', 'endsWith', 'match', 'test'].includes(callName(parent)))
        assert.equal(usedAsCondition || compared || matched, false, `${file} branches on translated display text`)
      })
    }
  }
})

test('P5-11 moves the remaining trace and scan labels behind semantic keys', async () => {
  const [trace, scans] = await Promise.all([
    readFile(new URL('../src/views/RuntimeTraceExplorer.vue', import.meta.url), 'utf8'),
    readFile(new URL('../src/views/AgentSecurityScans.vue', import.meta.url), 'utf8'),
  ])
  for (const literal of ['P5 · EVIDENCE QUERY', 'P5 · GOVERNANCE', 'P5 · PERFORMANCE', "'TURN'", "'STEP'"]) {
    assert.doesNotMatch(trace, new RegExp(literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
  const stream = await readFile(new URL('../src/components/TrajectoryStream.vue', import.meta.url), 'utf8')
  assert.match(stream, /runtimeTraceExplorer\.stream\.overview/)
  assert.match(scans, /agentSecurityScans\.targets\.credentialTypes/)
  assert.match(scans, /agentSecurityScans\.targets\.targetTypes/)
  assert.doesNotMatch(scans, />Bearer<|>API Key<|>Basic<|>Custom</)
})
