import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { docsArticleOrder, docsContent } from '../src/docs/content.js'
import { rankDocsContexts } from '../src/utils/docsSearch.js'

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(webRoot, '..')

const cases = [
  {
    locale: 'zh-CN',
    query: '规则扫描、深度扫描、Sandbox 和 LLM 分析有什么区别？',
    requiredTerms: ['基础 Scanner', '规则分析（默认勾选）', '深度扫描', 'Sandbox', 'LLM 分析'],
  },
  {
    locale: 'en-US',
    query: 'What is the difference between rule analysis, deep scan, Sandbox, and LLM analysis?',
    requiredTerms: ['Base Scanner', 'Rule analysis (selected by default)', 'Deep scan', 'Sandbox', 'LLM analysis'],
  },
]

const governanceCases = [
  {
    locale: 'zh-CN',
    classificationQuery: '阻断项、可疑项、噪声的检测逻辑是什么？',
    policyQuery: 'SKILL 策略配置怎么设置？',
    groupTitle: '能力治理',
    subgroupTitle: 'Skill 治理',
  },
  {
    locale: 'en-US',
    classificationQuery: 'How are blocking suspicious and noise findings classified?',
    policyQuery: 'How do I configure Skill policy settings?',
    groupTitle: 'Capability governance',
    subgroupTitle: 'Skill governance',
  },
]

const scenarioCases = [
  {
    locale: 'zh-CN',
    clientQuery: '如何在一台工作站上按 Agent 和 Skill 目录做模块化治理？',
    modelQuery: '如何验证模型网关先保护隐私再压缩上下文？',
  },
  {
    locale: 'en-US',
    clientQuery: 'How do I govern local Skills by Agent and root on one workstation?',
    modelQuery: 'How do I verify privacy replacement before model context compression?',
  },
]

test('scanning capabilities are present in navigation and article order', () => {
  assert.ok(docsArticleOrder.includes('scan-capabilities'))
  for (const { locale } of cases) {
    const content = docsContent[locale]
    assert.ok(content.articles['scan-capabilities'])
    assert.ok(content.groups.some(group => group.items.some(item => item.slug === 'scan-capabilities')))
  }
})

test('scanning overview covers every selectable analyzer in both languages', () => {
  for (const { locale, requiredTerms } of cases) {
    const overview = docsContent[locale].articles['scan-capabilities'].sections
      .find(section => section.id === 'capability-overview')
    const serialized = JSON.stringify(overview)
    for (const term of requiredTerms) assert.match(serialized, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'))
  }
})

test('Ask AI ranks the scanning overview first for analyzer comparison questions', () => {
  for (const { locale, query } of cases) {
    const [first] = rankDocsContexts({ content: docsContent[locale], query })
    assert.equal(first.slug, 'scan-capabilities')
    assert.equal(first.section_title, docsContent[locale].articles['scan-capabilities'].sections[0].title)
  }
})

test('Skill detection logic diagram follows the implemented reconciliation stages', () => {
  for (const { locale } of cases) {
    const section = docsContent[locale].articles['scan-capabilities'].sections
      .find(item => item.id === 'detection-logic')
    assert.ok(section)
    assert.equal(section.diagram, 'skill-scan-logic')
    const serialized = JSON.stringify(section).toLocaleLowerCase()
    const requiredTerms = locale === 'zh-CN'
      ? ['分析器', '策略', 'sandbox', '发现项归类', 'llm', '准入']
      : ['analyzer', 'policy', 'sandbox', 'classification', 'llm', 'admission']
    for (const term of requiredTerms) assert.match(serialized, new RegExp(term, 'i'))
  }
})

test('Skill docs follow the console capability-governance grouping and order', () => {
  const expectedSlugs = ['skill-governance', 'scanner-access', 'scan-capabilities', 'risk-classification', 'skill-policy']
  for (const { locale, groupTitle, subgroupTitle } of governanceCases) {
    const group = docsContent[locale].groups.find(item => item.title === groupTitle)
    assert.ok(group)
    const skillItems = group.items.filter(item => item.subgroup === subgroupTitle)
    assert.deepEqual(skillItems.map(item => item.slug), expectedSlugs)
    assert.equal(group.items.at(-1).slug, 'mcp-governance')
  }
  for (const slug of expectedSlugs) assert.ok(docsArticleOrder.includes(slug))
})

test('Agent docs follow the console agent-management grouping and order', () => {
  const expected = {
    'zh-CN': { title: '智能体管理', slugs: ['agent-management', 'client-management', 'credential-management', 'runtime-integration', 'hook-integration', 'audit-trail'] },
    'en-US': { title: 'Agent management', slugs: ['agent-management', 'client-management', 'credential-management', 'runtime-integration', 'hook-integration', 'audit-trail'] },
  }
  for (const [locale, { title, slugs }] of Object.entries(expected)) {
    const group = docsContent[locale].groups.find(item => item.title === title)
    assert.ok(group)
    assert.deepEqual(group.items.map(item => item.slug), slugs)
  }
})

test('Ask AI finds risk classification and Skill policy guidance in both languages', () => {
  for (const { locale, classificationQuery, policyQuery } of governanceCases) {
    const [classification] = rankDocsContexts({ content: docsContent[locale], query: classificationQuery })
    const [policy] = rankDocsContexts({ content: docsContent[locale], query: policyQuery })
    assert.equal(classification.slug, 'risk-classification')
    assert.equal(policy.slug, 'skill-policy')
  }
})

test('Ask AI finds Scanner, Credential Center, and Audit trail guidance', () => {
  const questions = {
    'zh-CN': [
      ['如何批量扫描服务器上的 Skill？', 'scanner-access'],
      ['不同类型的接入凭证怎么创建和限制权限？', 'credential-management'],
      ['如何查询 Skill 被阻断的审计事件？', 'audit-trail'],
    ],
    'en-US': [
      ['How do I batch scan Skills on a server?', 'scanner-access'],
      ['How do I create access credentials with least privilege?', 'credential-management'],
      ['How do I find an audit event for a blocked Skill?', 'audit-trail'],
    ],
  }
  for (const [locale, entries] of Object.entries(questions)) {
    for (const [query, expectedSlug] of entries) {
      const [first] = rankDocsContexts({ content: docsContent[locale], query })
      assert.equal(first.slug, expectedSlug, `${locale}: ${query}`)
    }
  }
})

test('Ask AI finds the dedicated Hook integration guide', () => {
  const questions = {
    'zh-CN': 'Claude Code、Codex 和 OpenClaw 的 Hook 怎么配置和验证？',
    'en-US': 'How do I configure and validate Hooks for Claude Code Codex and OpenClaw?',
  }
  for (const [locale, query] of Object.entries(questions)) {
    const [first] = rankDocsContexts({ content: docsContent[locale], query })
    assert.equal(first.slug, 'hook-integration')
  }
})

test('Hook guide includes official Claude Code, TraeCode, and Codex references', () => {
  const expectedUrls = [
    'https://code.claude.com/docs/en/hooks-guide',
    'https://code.claude.com/docs/en/hooks',
    'https://code.claude.com/docs/en/permissions',
    'https://docs.trae.cn/ide_automate-actions-with-hooks',
    'https://docs.trae.cn/ide_hook-configuration-reference',
    'https://docs.trae.cn/ide_changelog',
    'https://learn.chatgpt.com/docs/hooks',
    'https://learn.chatgpt.com/docs/config-file/config-reference',
  ]

  for (const [locale, content] of Object.entries(docsContent)) {
    const references = content.articles['hook-integration'].sections.flatMap(section => section.references || [])
    const urls = new Set(references.map(reference => reference.url))
    for (const url of expectedUrls) assert.ok(urls.has(url), `${locale}: missing official reference ${url}`)
  }
})

test('system architecture covers every major runtime domain and ranks for Ask AI', () => {
  const cases = {
    'zh-CN': '系统总体架构是什么，模型网关、MCP网关、客户端和Skill是什么关系？',
    'en-US': 'What is the system architecture across Skills Clients Model Gateway and MCP Gateway?',
  }
  for (const [locale, query] of Object.entries(cases)) {
    const section = docsContent[locale].articles[''].sections.find(item => item.id === 'system-architecture')
    assert.ok(section)
    assert.equal(section.diagram, 'architecture')
    const serialized = JSON.stringify(section).toLocaleLowerCase()
    const requiredTerms = locale === 'zh-CN'
      ? ['skill', '客户端', '模型', 'mcp', 'sandbox', '审计']
      : ['skill', 'client', 'model', 'mcp', 'sandbox', 'audit']
    for (const term of requiredTerms) assert.match(serialized, new RegExp(term, 'i'))
    const [first] = rankDocsContexts({ content: docsContent[locale], query })
    assert.equal(first.slug, '')
    assert.equal(first.section_title, section.title)
  }
})

test('scenario guides stay in one ungrouped list and rank for Ask AI', () => {
  for (const { locale, clientQuery, modelQuery } of scenarioCases) {
    const group = docsContent[locale].groups.find(item => item.items.some(entry => entry.slug === 'case-client-modular-governance'))
    assert.ok(group)
    const scenarioItems = group.items
    assert.deepEqual(scenarioItems.slice(-2).map(item => item.slug), [
      'case-client-modular-governance',
      'case-model-privacy-compression',
    ])
    assert.ok(scenarioItems.every(item => !item.subgroup))

    const [clientContext] = rankDocsContexts({ content: docsContent[locale], query: clientQuery })
    const [modelContext] = rankDocsContexts({ content: docsContent[locale], query: modelQuery })
    assert.equal(clientContext.slug, 'case-client-modular-governance')
    assert.equal(modelContext.slug, 'case-model-privacy-compression')
  }
})

test('documentation navigation, tables, links, and screenshots stay internally valid', () => {
  const routerSource = fs.readFileSync(path.join(webRoot, 'src/router/index.js'), 'utf8')
  const routePaths = new Set([...routerSource.matchAll(/path:\s*['"]([^'"]+)['"]/g)].map(match => match[1]))

  const visit = (value, callback) => {
    if (Array.isArray(value)) return value.forEach(item => visit(item, callback))
    if (!value || typeof value !== 'object') return
    callback(value)
    Object.values(value).forEach(item => visit(item, callback))
  }

  for (const [locale, content] of Object.entries(docsContent)) {
    const navigationSlugs = content.groups.flatMap(group => group.items.map(item => item.slug))
    assert.deepEqual(new Set(navigationSlugs), new Set(docsArticleOrder), `${locale}: navigation and article order differ`)
    assert.equal(navigationSlugs.length, new Set(navigationSlugs).size, `${locale}: duplicate navigation slug`)

    for (const [slug, article] of Object.entries(content.articles)) {
      const sectionIds = (article.sections || []).map(section => section.id)
      assert.equal(sectionIds.length, new Set(sectionIds).size, `${locale}/${slug}: duplicate section id`)

      visit(article, node => {
        if (node.table) {
          for (const row of node.table.rows) {
            assert.equal(row.length, node.table.columns.length, `${locale}/${slug}: table column mismatch`)
          }
        }
        if (node.references) {
          for (const reference of node.references) {
            assert.ok(reference.label, `${locale}/${slug}: reference label is required`)
            assert.match(reference.url, /^https:\/\//, `${locale}/${slug}: reference must use HTTPS`)
          }
        }
        if (node.image?.name) {
          const screenshot = path.join(webRoot, 'public/docs/screenshots', locale, `${node.image.name}.png`)
          assert.ok(fs.existsSync(screenshot), `${locale}/${slug}: missing screenshot ${node.image.name}`)
        }
        if (typeof node.path === 'string' && node.path.startsWith('/docs/')) {
          const targetSlug = node.path.slice('/docs/'.length).split('#')[0]
          assert.ok(content.articles[targetSlug], `${locale}/${slug}: missing docs target ${node.path}`)
        } else if (typeof node.path === 'string' && node.path.startsWith('/examples/')) {
          const download = path.join(webRoot, 'public', node.path.replace(/^\//, ''))
          assert.ok(fs.existsSync(download), `${locale}/${slug}: missing download ${node.path}`)
        } else if (typeof node.path === 'string' && node.path.startsWith('/')) {
          assert.ok(routePaths.has(node.path), `${locale}/${slug}: missing app route ${node.path}`)
        }
      })
    }
  }
})

test('repository Markdown docs do not contain machine-specific or broken local links', () => {
  const docsRoot = path.join(repoRoot, 'docs')
  const markdownFiles = []
  const walk = directory => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const entryPath = path.join(directory, entry.name)
      if (entry.isDirectory()) walk(entryPath)
      else if (entry.name.endsWith('.md')) markdownFiles.push(entryPath)
    }
  }
  walk(docsRoot)

  for (const file of markdownFiles) {
    const source = fs.readFileSync(file, 'utf8')
    assert.doesNotMatch(source, /\/Users\/huangluguang\//, `${path.relative(repoRoot, file)}: machine-specific path`)
    for (const match of source.matchAll(/\]\(([^)]+)\)/g)) {
      const target = match[1].trim().replace(/^<|>$/g, '')
      if (!target || /^(?:https?:|mailto:|#)/i.test(target)) continue
      const localTarget = target.split('#')[0].split('?')[0]
      assert.ok(!path.isAbsolute(localTarget), `${path.relative(repoRoot, file)}: absolute local link ${target}`)
      const resolved = path.resolve(path.dirname(file), localTarget)
      assert.ok(fs.existsSync(resolved), `${path.relative(repoRoot, file)}: broken local link ${target}`)
    }
  }
})
