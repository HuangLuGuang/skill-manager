import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { parse as parseScript, parseExpression } from '@babel/parser'
import { baseParse, NodeTypes } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'
import MagicString from 'magic-string'

import { legacyKey } from '../src/i18n/legacy.js'
import { enPhrases } from '../src/i18n/phrases.js'

const srcDir = fileURLToPath(new URL('../src/', import.meta.url))
const files = []
const hasChinese = value => /[\u3400-\u9fff]/.test(value || '')
const skipCalls = new Set(['text', 'phrase', 't', '$t', 'translateLegacy'])
const semanticCalls = new Set(['includes', 'startsWith', 'endsWith', 'replace', 'match', 'test'])
const missingTranslations = new Set()

const collectVueFiles = directory => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) collectVueFiles(fullPath)
    else if (entry.isFile() && entry.name.endsWith('.vue')) files.push(fullPath)
  }
}

const walk = (node, visitor, parent = null, parentKey = '') => {
  if (!node || typeof node !== 'object') return
  visitor(node, parent, parentKey)
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'start', 'end', 'extra'].includes(key)) continue
    if (Array.isArray(value)) value.forEach(item => walk(item, visitor, node, key))
    else if (value && typeof value === 'object' && value.type) walk(value, visitor, node, key)
  }
}

const calleeName = callee => {
  if (!callee) return ''
  if (callee.type === 'Identifier') return callee.name
  if (callee.type === 'MemberExpression' || callee.type === 'OptionalMemberExpression') {
    return callee.property?.name || callee.property?.value || ''
  }
  return ''
}

const shouldTranslate = (node, parent, parentKey) => {
  if (node.type !== 'StringLiteral' || !hasChinese(node.value)) return false
  if (!enPhrases[node.value]) {
    missingTranslations.add(node.value)
    return false
  }
  if (!parent) return true
  if (
    (parent.type === 'ObjectProperty' || parent.type === 'ObjectMethod')
    && parentKey === 'key'
    && !parent.computed
  ) return false
  if (['ImportDeclaration', 'ExportNamedDeclaration', 'Directive', 'BinaryExpression'].includes(parent.type)) return false
  if (parent.type === 'CallExpression' || parent.type === 'OptionalCallExpression') {
    const name = calleeName(parent.callee)
    if (skipCalls.has(name) || semanticCalls.has(name)) return false
  }
  return true
}

const collectExpressionReplacements = (expression, baseOffset, wrapper) => {
  const replacements = []
  let ast
  try {
    ast = parseExpression(expression, { plugins: ['optionalChaining', 'nullishCoalescingOperator'] })
  } catch {
    return replacements
  }
  walk(ast, (node, parent, parentKey) => {
    if (!shouldTranslate(node, parent, parentKey)) return
    replacements.push({
      start: baseOffset + node.start,
      end: baseOffset + node.end,
      value: `${wrapper}('${legacyKey(node.value)}')`,
    })
  })
  return replacements
}

collectVueFiles(srcDir)

for (const file of files) {
  const source = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(source)
  const replacements = []
  let scriptChanged = false

  if (descriptor.template) {
    const template = descriptor.template
    const ast = baseParse(template.content)
    const visit = node => {
      if (node.type === NodeTypes.INTERPOLATION && node.content?.content) {
        replacements.push(...collectExpressionReplacements(
          node.content.content,
          template.loc.start.offset + node.content.loc.start.offset,
          '$t',
        ))
      }
      if (node.type === NodeTypes.DIRECTIVE && node.exp?.content) {
        replacements.push(...collectExpressionReplacements(
          node.exp.content,
          template.loc.start.offset + node.exp.loc.start.offset,
          '$t',
        ))
      }
      for (const child of node.children || []) visit(child)
      if (node.type === NodeTypes.ELEMENT) {
        for (const prop of node.props || []) visit(prop)
      }
    }
    visit(ast)
  }

  if (descriptor.scriptSetup?.content) {
    const script = descriptor.scriptSetup
    let ast
    try {
      ast = parseScript(script.content, {
        sourceType: 'module',
        plugins: ['topLevelAwait', 'optionalChaining', 'nullishCoalescingOperator'],
      })
    } catch (error) {
      throw new Error(`Could not parse ${file}: ${error.message}`)
    }
    walk(ast, (node, parent, parentKey) => {
      if (!shouldTranslate(node, parent, parentKey)) return
      replacements.push({
        start: script.loc.start.offset + node.start,
        end: script.loc.start.offset + node.end,
        value: `phrase('${legacyKey(node.value)}')`,
      })
      scriptChanged = true
    })
  }

  if (!replacements.length) continue
  const output = new MagicString(source)
  for (const replacement of replacements.sort((a, b) => b.start - a.start)) {
    output.overwrite(replacement.start, replacement.end, replacement.value)
  }

  if (scriptChanged && descriptor.scriptSetup && !/\bphrase\b/.test(descriptor.scriptSetup.content)) {
    const relativeImport = file === path.join(srcDir, 'App.vue') ? './i18n' : '../i18n'
    output.appendLeft(
      descriptor.scriptSetup.loc.start.offset,
      `\nimport { translateLegacy as phrase } from '${relativeImport}'\n`,
    )
  }

  fs.writeFileSync(file, output.toString())
  console.log(`${path.relative(srcDir, file)}: migrated ${replacements.length} expressions`)
}

if (missingTranslations.size) {
  console.error('\nMissing expression translations:')
  for (const value of [...missingTranslations].sort()) console.error(`- ${value}`)
  process.exitCode = 2
}
