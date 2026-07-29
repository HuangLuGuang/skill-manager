import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { baseParse, NodeTypes } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'

import { legacyKey } from '../src/i18n/legacy.js'
import { enPhrases } from '../src/i18n/phrases.js'

const srcDir = fileURLToPath(new URL('../src/', import.meta.url))
const files = []

const collectVueFiles = directory => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) collectVueFiles(fullPath)
    else if (entry.isFile() && entry.name.endsWith('.vue')) files.push(fullPath)
  }
}

const hasChinese = value => /[\u3400-\u9fff]/.test(value || '')

collectVueFiles(srcDir)

for (const file of files) {
  const source = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(source)
  if (!descriptor.template) continue

  const template = descriptor.template
  const ast = baseParse(template.content)
  const replacements = []

  const visit = (node, skip = false) => {
    const nextSkip = skip || (
      node.type === NodeTypes.ELEMENT
      && ['pre', 'code', 'textarea'].includes(node.tag)
    ) || (
      node.type === NodeTypes.ELEMENT
      && node.props?.some(prop => prop.type === NodeTypes.ATTRIBUTE && prop.name === 'data-no-i18n')
    )

    if (node.type === NodeTypes.TEXT && !nextSkip) {
      const raw = node.content
      const text = raw.trim()
      if (text && hasChinese(text)) {
        if (!enPhrases[text]) throw new Error(`Missing English phrase in ${file}: ${text}`)
        const leading = raw.match(/^\s*/)?.[0] || ''
        const trailing = raw.match(/\s*$/)?.[0] || ''
        replacements.push({
          start: template.loc.start.offset + node.loc.start.offset,
          end: template.loc.start.offset + node.loc.end.offset,
          value: `${leading}{{ $t(${JSON.stringify(legacyKey(text))}) }}${trailing}`,
        })
      }
    }

    if (node.type === NodeTypes.ELEMENT && !nextSkip) {
      for (const prop of node.props || []) {
        if (prop.type !== NodeTypes.ATTRIBUTE || !prop.value || !hasChinese(prop.value.content)) continue
        const text = prop.value.content.trim()
        if (!enPhrases[text]) throw new Error(`Missing English attribute phrase in ${file}: ${text}`)
        replacements.push({
          start: template.loc.start.offset + prop.loc.start.offset,
          end: template.loc.start.offset + prop.loc.end.offset,
          value: `:${prop.name}="$t('${legacyKey(text)}')"`,
        })
      }
    }

    for (const child of node.children || []) visit(child, nextSkip)
  }

  visit(ast)
  if (!replacements.length) continue
  replacements.sort((a, b) => b.start - a.start)
  let output = source
  for (const replacement of replacements) {
    output = output.slice(0, replacement.start) + replacement.value + output.slice(replacement.end)
  }
  fs.writeFileSync(file, output)
  console.log(`${path.relative(srcDir, file)}: migrated ${replacements.length} template phrases`)
}
