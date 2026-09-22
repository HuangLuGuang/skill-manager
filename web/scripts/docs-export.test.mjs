import assert from 'node:assert/strict'
import test from 'node:test'

import { BlobReader, TextWriter, ZipReader } from '@zip.js/zip.js'

import { capabilityCatalog, capabilityModules } from '../src/docs/capabilityCatalog.js'
import { docsArticleOrder, docsContent } from '../src/docs/content.js'
import { buildCapabilityWorkbookBlob } from '../src/utils/capabilityWorkbook.js'
import { buildDocsPdfExportPayload, docsPdfFilename } from '../src/utils/docsPdfExport.js'

test('capability catalog is bilingual, complete, and points to current help articles', () => {
  const zh = capabilityCatalog['zh-CN']
  const en = capabilityCatalog['en-US']
  assert.equal(zh.length, en.length)
  assert.ok(zh.length >= 50)
  assert.deepEqual(zh.map(item => item.id), en.map(item => item.id))
  assert.deepEqual(new Set(zh.map(item => item.module)), new Set(capabilityModules.map(item => item.id)))
  for (const locale of ['zh-CN', 'en-US']) {
    for (const entry of capabilityCatalog[locale]) {
      for (const field of ['id', 'module', 'submodule', 'name', 'description', 'scenario', 'entry', 'boundary', 'docs']) {
        assert.ok(String(entry[field] || '').trim(), `${locale}/${entry.id}: missing ${field}`)
      }
      assert.ok(docsContent[locale].articles[entry.docs], `${locale}/${entry.id}: missing help article ${entry.docs}`)
    }
  }
  assert.doesNotMatch(JSON.stringify(en), /[\u3400-\u9fff]/)
})

test('PDF export source covers every current help article in both languages', () => {
  for (const locale of ['zh-CN', 'en-US']) {
    const navigationSlugs = docsContent[locale].groups.flatMap(group => group.items.map(item => item.slug))
    assert.deepEqual(navigationSlugs, docsArticleOrder)
    assert.equal(navigationSlugs.length, 34)
    const payload = buildDocsPdfExportPayload({
      locale,
      selectedArticleKeys: navigationSlugs.map(slug => slug || '__home__'),
    })
    assert.equal(payload.articles.length, 34)
    assert.deepEqual(payload.articles.map(article => article.slug), docsArticleOrder)
    assert.ok(payload.articles.every(article => article.group_title && article.title && article.sections.length))
  }
  assert.match(docsPdfFilename('zh-CN', new Date(2026, 8, 22)), /帮助文档-20260922\.pdf$/)
  assert.match(docsPdfFilename('en-US', new Date(2026, 8, 22)), /help-documentation-20260922\.pdf$/)
})

test('capability workbook is a valid two-sheet XLSX package with filters and selected rows only', async () => {
  const selected = capabilityCatalog['en-US'].filter(item => ['scanner', 'mcp'].includes(item.module))
  const blob = await buildCapabilityWorkbookBlob({
    items: selected,
    locale: 'en-US',
    generatedAt: new Date('2026-09-22T08:00:00Z'),
  })
  assert.equal(blob.type, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
  assert.ok(blob.size > 5_000)

  const reader = new ZipReader(new BlobReader(blob))
  const entries = await reader.getEntries()
  const names = new Set(entries.map(entry => entry.filename))
  for (const name of ['[Content_Types].xml', 'xl/workbook.xml', 'xl/styles.xml', 'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml']) {
    assert.ok(names.has(name), `missing ${name}`)
  }
  const detailEntry = entries.find(entry => entry.filename === 'xl/worksheets/sheet2.xml')
  const detail = await detailEntry.getData(new TextWriter())
  await reader.close()

  assert.match(detail, /<autoFilter ref="A3:I\d+"\/>/)
  assert.match(detail, /Endpoint Skill scanning/)
  assert.match(detail, /MCP governance/)
  assert.doesNotMatch(detail, /Model access and privacy governance/)
  assert.equal((detail.match(/<row /g) || []).length, selected.length + 2)
})
