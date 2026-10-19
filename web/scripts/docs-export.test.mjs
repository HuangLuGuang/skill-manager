import assert from 'node:assert/strict'
import test from 'node:test'

import { BlobReader, TextWriter, ZipReader } from '@zip.js/zip.js'

import { capabilityCatalog, capabilityModules } from '../src/docs/capabilityCatalog.js'
import { docsArticleOrder, docsContent } from '../src/docs/content.js'
import { integrationChoiceSections } from '../src/docs/integration-choice.js'
import { buildCapabilityWorkbookBlob } from '../src/utils/capabilityWorkbook.js'
import { buildDocsPdfExportPayload, docsPdfFilename } from '../src/utils/docsPdfExport.js'
import { createDocsPdfProgressReader } from '../src/utils/docsPdfProgress.js'

test('PDF export uses the refreshed source including newly published articles', () => {
  const source = structuredClone({ docsContent, docsArticleOrder })
  const content = source.docsContent['en-US']
  content.articles['quick-start'].title = 'Updated quick start'
  content.articles['new-guide'] = { title: 'New guide', sections: [{ id: 'new', title: 'New section', paragraphs: ['Latest text'] }] }
  content.groups[0].items.push({ slug: 'new-guide', title: 'New guide' })
  source.docsArticleOrder.push('new-guide')
  const payload = buildDocsPdfExportPayload({ locale: 'en-US', selectedArticleKeys: ['quick-start', 'new-guide'], source })
  assert.deepEqual(payload.articles.map(article => article.title), ['Updated quick start', 'New guide'])
  assert.deepEqual(payload.articles[1].sections[0].paragraphs, ['Latest text'])
})

test('PDF progress reader handles split events, heartbeats, and binary chunks', async () => {
  const progress = []
  const reader = createDocsPdfProgressReader(event => progress.push(event))
  const data = new Uint8Array([37, 80, 68, 70, 0, 255])
  const text = [
    JSON.stringify({ type: 'progress', stage: 'layout', pass: 2, page: 5 }),
    '', JSON.stringify({ type: 'chunk', data: Buffer.from(data).toString('base64') }),
    JSON.stringify({ type: 'complete' }), '',
  ].join('\n')
  reader.feed(text.slice(0, 20))
  reader.feed(text.slice(0, 80))
  const blob = reader.finish(text)
  assert.equal(progress.length, 1)
  assert.equal(progress[0].page, 5)
  assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), data)
})

test('PDF progress reader rejects failed and interrupted exports', () => {
  const reader = createDocsPdfProgressReader()
  assert.throws(() => reader.finish('{"type":"error","error_code":"docs_export.generation_failed"}\n'), /generation_failed/)
  assert.throws(() => createDocsPdfProgressReader().finish('{"type":"chunk","data":"JVBERg=="}\n'), /incomplete/)
})

test('PDF download progress counts decoded bytes and preserves final page totals', async () => {
  const progress = []
  const reader = createDocsPdfProgressReader(event => progress.push(event))
  const data = [
    { type: 'progress', stage: 'downloading', total_passes: 3, total_pages: 174, total_bytes: 6, completed_bytes: 0 },
    { type: 'chunk', data: Buffer.from([37, 80, 68, 70]).toString('base64') },
    { type: 'chunk', data: Buffer.from([0, 255]).toString('base64') },
    { type: 'complete' },
  ].map(event => JSON.stringify(event)).join('\n') + '\n'
  reader.feed(data.slice(0, data.lastIndexOf('\n', data.length - 2)))
  const blob = reader.finish(data)
  assert.deepEqual(progress.map(event => event.completed_bytes), [0, 4, 6])
  assert.ok(progress.every(event => event.total_passes === 3 && event.total_pages === 174))
  assert.equal(blob.size, 6)
})

test('integration flowchart links resolve in both languages and retain routes in PDF export', () => {
  const pathsByLocale = []
  for (const locale of ['zh-CN', 'en-US']) {
    const section = integrationChoiceSections[locale]
    const decision = section.decision
    const links = [...decision.routes.flatMap(route => route.links), ...decision.additional, decision.identity]
    pathsByLocale.push(links.map(link => link.path))
    for (const link of links) {
      const [slug, anchor] = link.path.replace('/docs/', '').split('#')
      const target = docsContent[locale].articles[slug]
      assert.ok(target, `${locale}: missing ${link.path}`)
      if (anchor) assert.ok(target.sections.some(item => item.id === anchor), `${locale}: missing anchor ${link.path}`)
    }
    const payload = buildDocsPdfExportPayload({ locale, selectedArticleKeys: ['scenario-selection'] })
    const exported = payload.articles[0].sections.find(item => item.id === section.id)
    assert.equal(exported.diagram, 'integration-choice')
    assert.equal(exported.table.rows.length, decision.routes.reduce((count, route) => count + route.links.length, 0) + decision.additional.length)
    for (const route of decision.routes) assert.ok(exported.table.rows.some(row => row.includes(route.condition)))
  }
  assert.deepEqual(...pathsByLocale)
})

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
    assert.ok(navigationSlugs.length > 0)
    const payload = buildDocsPdfExportPayload({
      locale,
      selectedArticleKeys: navigationSlugs.map(slug => slug || '__home__'),
    })
    assert.equal(payload.articles.length, navigationSlugs.length)
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
