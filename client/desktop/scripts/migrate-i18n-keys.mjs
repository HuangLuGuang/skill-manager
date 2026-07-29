import fs from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { parse } = require('../../../web/node_modules/@babel/parser')
const MagicString = require('../../../web/node_modules/magic-string').default

const file = new URL('../src/app.js', import.meta.url)
const dictionaryFile = new URL('../src/i18n.js', import.meta.url)
const source = fs.readFileSync(file, 'utf8')
const dictionary = fs.readFileSync(dictionaryFile, 'utf8')
const ast = parse(source, { sourceType: 'module' })
const output = new MagicString(source)
const missing = new Set()
const semanticCalls = new Set(['includes', 'startsWith', 'endsWith', 'replace', 'match', 'test'])

const hashText = value => {
  let hash = 0x811c9dc5
  for (const character of String(value)) {
    hash ^= character.codePointAt(0)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(36)
}

const calleeName = callee => {
  if (!callee) return ''
  if (callee.type === 'Identifier') return callee.name
  return callee.property?.name || callee.property?.value || ''
}

const hasTranslation = value =>
  dictionary.includes(`${JSON.stringify(value)}:`)
  || dictionary.includes(`'${value.replaceAll("'", "\\'")}':`)

const walk = (node, parent = null, parentKey = '') => {
  if (!node || typeof node !== 'object') return
  if (node.type === 'StringLiteral' && /[\u3400-\u9fff]/.test(node.value)) {
    const inTranslator = parent?.type === 'CallExpression' && calleeName(parent.callee) === 't'
    const propertyKey = parent?.type === 'ObjectProperty' && parentKey === 'key' && !parent.computed
    const semanticUse = parent?.type === 'BinaryExpression'
      || (parent?.type === 'CallExpression' && semanticCalls.has(calleeName(parent.callee)))
    if (!inTranslator && !propertyKey && !semanticUse) {
      if (hasTranslation(node.value)) {
        output.overwrite(node.start, node.end, `t('ui.${hashText(node.value)}')`)
      } else {
        missing.add(node.value)
      }
    } else if (inTranslator) {
      output.overwrite(node.start, node.end, `'ui.${hashText(node.value)}'`)
    }
  }
  if (
    node.type === 'TemplateLiteral'
    && node.quasis.some(item => /[\u3400-\u9fff]/.test(item.value.raw))
    && !(parent?.type === 'TaggedTemplateExpression')
  ) {
    output.appendLeft(node.start, 'tf')
  }
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'start', 'end', 'extra'].includes(key)) continue
    if (Array.isArray(value)) value.forEach(item => walk(item, node, key))
    else if (value && typeof value === 'object' && value.type) walk(value, node, key)
  }
}

walk(ast)
fs.writeFileSync(file, output.toString())
if (missing.size) {
  console.error('Missing desktop translations:')
  ;[...missing].sort().forEach(value => console.error(`- ${value}`))
  process.exitCode = 2
}
