import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { parse as parseScript } from '@babel/parser'
import { baseParse, NodeTypes } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'

import { domainMessages } from '../src/i18n/domain.js'
import { localizeApiError } from '../src/i18n/errors.js'
import { legacyKey, legacyMessages } from '../src/i18n/legacy.js'
import { enPhrases } from '../src/i18n/phrases.js'
import { pseudoLocalize } from '../src/i18n/pseudo.js'

const chinesePattern = /[\u3400-\u9fff]/
const srcDir = fileURLToPath(new URL('../src/', import.meta.url))
const files = []
const failures = []
const validLegacyKeys = new Set(Object.keys(legacyMessages['zh-CN']).map(key => `legacy.${key}`))

const collectVueFiles = directory => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) collectVueFiles(fullPath)
    else if (entry.isFile() && entry.name.endsWith('.vue')) files.push(fullPath)
  }
}

const walk = (node, visitor, ancestors = []) => {
  if (!node || typeof node !== 'object') return
  visitor(node, ancestors)
  const next = [...ancestors, node]
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'start', 'end', 'extra'].includes(key)) continue
    if (Array.isArray(value)) value.forEach(item => walk(item, visitor, next))
    else if (value && typeof value === 'object' && value.type) walk(value, visitor, next)
  }
}

const callName = node => {
  if (!node || !['CallExpression', 'OptionalCallExpression'].includes(node.type)) return ''
  if (node.callee.type === 'Identifier') return node.callee.name
  return node.callee.property?.name || node.callee.property?.value || ''
}

const isLocalized = ancestors =>
  ancestors.some(node => ['text', 'phrase', 't', '$t', 'translateLegacy'].includes(callName(node)))

const checkKey = (value, file) => {
  if (!String(value).startsWith('legacy.')) return
  if (!validLegacyKeys.has(value)) failures.push(`${file}: unknown legacy key ${value}`)
}

const checkExpressionAst = (ast, file) => {
  walk(ast, (node, ancestors) => {
    if (node.type === 'StringLiteral') {
      checkKey(node.value, file)
      if (chinesePattern.test(node.value) && !isLocalized(ancestors)) {
        const semanticUse = ancestors.some(parent =>
          parent.type === 'BinaryExpression'
          || ['includes', 'startsWith', 'endsWith', 'replace', 'match', 'test'].includes(callName(parent)))
        if (!semanticUse) failures.push(`${file}: unlocalized script text ${node.value}`)
      }
    }
    if (node.type === 'TemplateLiteral') {
      const raw = node.quasis.map(item => item.value.raw).join('')
      if (chinesePattern.test(raw) && !isLocalized(ancestors)) {
        failures.push(`${file}: unlocalized template literal ${raw}`)
      }
    }
  })
}

const visitTemplate = (node, file, skipped = false) => {
  if (!node) return
  if (node.type === NodeTypes.ELEMENT) {
    skipped = skipped || ['pre', 'code', 'textarea'].includes(node.tag)
    skipped = skipped || node.props?.some(prop =>
      prop.type === NodeTypes.ATTRIBUTE && prop.name === 'data-no-i18n')
    for (const prop of node.props || []) {
      if (prop.type === NodeTypes.ATTRIBUTE && prop.value && chinesePattern.test(prop.value.content) && !skipped) {
        failures.push(`${file}: static Chinese attribute ${prop.value.content}`)
      }
      if (prop.type === NodeTypes.DIRECTIVE && prop.exp?.content) {
        for (const match of prop.exp.content.matchAll(/['"](legacy\.[a-z0-9]+)['"]/g)) checkKey(match[1], file)
      }
    }
  }
  if (node.type === NodeTypes.TEXT && chinesePattern.test(node.content) && !skipped) {
    failures.push(`${file}: static Chinese template text ${node.content.trim()}`)
  }
  if (node.type === NodeTypes.INTERPOLATION) {
    for (const match of node.content.content.matchAll(/['"](legacy\.[a-z0-9]+)['"]/g)) checkKey(match[1], file)
  }
  for (const child of node.children || []) visitTemplate(child, file, skipped)
}

collectVueFiles(srcDir)
for (const file of files) {
  const relative = path.relative(srcDir, file)
  const { descriptor } = parse(fs.readFileSync(file, 'utf8'))
  if (descriptor.template) visitTemplate(baseParse(descriptor.template.content), relative)
  for (const script of [descriptor.script, descriptor.scriptSetup]) {
    if (!script?.content) continue
    checkExpressionAst(
      parseScript(script.content, {
        sourceType: 'module',
        plugins: ['topLevelAwait', 'optionalChaining', 'nullishCoalescingOperator'],
      }),
      relative,
    )
  }
}

assert.equal(legacyKey('刷新'), 'legacy.12qo56a')
assert.equal(legacyMessages['en-US'][legacyKey('刷新').split('.')[1]], 'Refresh')
assert.deepEqual(Object.keys(domainMessages['zh-CN']).sort(), Object.keys(domainMessages['en-US']).sort())
for (const category of Object.keys(domainMessages['zh-CN'])) {
  assert.deepEqual(
    Object.keys(domainMessages['zh-CN'][category]).sort(),
    Object.keys(domainMessages['en-US'][category]).sort(),
  )
}
assert.ok(pseudoLocalize('Agent Manager').length > 'Agent Manager'.length)
assert.ok(!pseudoLocalize('Agent Manager').includes('Agent Manager'))
assert.equal(
  localizeApiError({ code: 'auth.invalid_credentials' }, 'en-US'),
  'Incorrect username or password',
)

const i18nRuntime = fs.readFileSync(new URL('../src/i18n/index.js', import.meta.url), 'utf8')
assert.ok(!i18nRuntime.includes('MutationObserver'))
assert.ok(!i18nRuntime.includes('createTreeWalker'))

for (const [source, english] of Object.entries(enPhrases)) {
  if (chinesePattern.test(english)) failures.push(`English translation contains Chinese: ${source} -> ${english}`)
}

if (failures.length) {
  console.error('V3 i18n gate failed:')
  failures.slice(0, 200).forEach(failure => console.error(`- ${failure}`))
  if (failures.length > 200) console.error(`... ${failures.length - 200} more`)
  process.exitCode = 1
} else {
  console.log(`V3 i18n gate passed: ${files.length} Vue files, ${validLegacyKeys.size} legacy keys`)
}
