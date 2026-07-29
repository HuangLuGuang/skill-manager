import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(import.meta.url)
const { parse } = require('@babel/parser')
const storage = new Map([['agent-manager-client-locale', 'en-US']])
const context = {
  CustomEvent: class CustomEvent {},
  document: {},
  localStorage: {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
  },
  navigator: { language: 'en-US' },
  window: {
    addEventListener: () => {},
    dispatchEvent: () => {},
  },
}

vm.runInNewContext(
  fs.readFileSync(new URL('../src/static-i18n-bindings.js', import.meta.url), 'utf8'),
  context,
)
vm.runInNewContext(
  fs.readFileSync(new URL('../src/i18n.js', import.meta.url), 'utf8'),
  context,
)
const appSource = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
const indexHtml = fs.readFileSync(new URL('../src/index.html', import.meta.url), 'utf8')

test('translates core desktop navigation and product name', () => {
  const { t } = context.window.clientI18n
  assert.equal(t('智能体生命周期管理系统'), 'Agent Manager')
  assert.equal(t('客户端接入'), 'Client Access')
  assert.equal(t('Agent 发现'), 'Agent Discovery')
  assert.equal(t('Skill 治理'), 'Skill Governance')
  assert.equal(t('运行状态'), 'Runtime Status')
  assert.equal(t('执行记录'), 'Activity Records')
})

test('keeps code-like values unchanged', () => {
  assert.equal(context.window.clientI18n.t('client:submit-skill'), 'client:submit-skill')
  assert.equal(context.window.clientI18n.t('/Users/me/.codex/skills'), '/Users/me/.codex/skills')
})

test('localizes runtime errors while preserving technical details', () => {
  const { translateRuntime } = context.window.clientI18n
  assert.equal(
    translateRuntime('无法连接 Agent Manager: error sending request for url'),
    'Unable to connect to Agent Manager: error sending request for url',
  )
  assert.equal(
    translateRuntime('无法读取后台服务状态: exit status 1'),
    'Unable to read the background service status: exit status 1',
  )
})

test('supports stable desktop message keys', () => {
  assert.equal(context.window.clientI18n.t('ui.png61n'), 'Last operation')
})

test('does not expose an internal key for generated static bindings', () => {
  for (const binding of context.window.clientStaticI18nBindings) {
    const translated = context.window.clientI18n.t(binding.key)
    assert.equal(translated.startsWith('ui.'), false, binding.key)
  }
})

test('covers static Chinese desktop UI text', () => {
  const { t } = context.window.clientI18n
  const values = new Set()
  const html = fs.readFileSync(new URL('../src/index.html', import.meta.url), 'utf8')
  for (const match of html.matchAll(/>([^<>]+)</g)) values.add(match[1].trim())
  for (const match of html.matchAll(/(?:placeholder|title|aria-label|alt)="([^"]+)"/g)) values.add(match[1].trim())

  const source = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
  const patterns = [
    /'((?:\\.|[^'\\\r\n])*)'/g,
    /"((?:\\.|[^"\\\r\n])*)"/g,
    /`((?:\\.|[^`\\])*)`/g,
  ]
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      let value = match[1].trim()
      if (value.includes('<')) value = value.replace(/<[^>]*>/g, '').trim()
      if (
        value
        && !value.includes('${')
        && !value.includes('\n')
        && !value.includes('\\u')
        && !value.includes('(?')
        && !value.includes('</')
      ) {
        values.add(value)
      }
    }
  }

  const missing = [...values].filter(value => /[\u3400-\u9fff]/.test(value) && t(value) === value)
  const residualChinese = [...values].filter(
    value => /[\u3400-\u9fff]/.test(value) && /[\u3400-\u9fff]/.test(t(value)),
  )
  assert.deepEqual(missing, [])
  assert.deepEqual(residualChinese, [])
})

test('uses explicit static bindings and localizes system notifications', () => {
  const runtime = fs.readFileSync(new URL('../src/i18n.js', import.meta.url), 'utf8')
  const app = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
  assert.equal(runtime.includes('MutationObserver'), false)
  assert.equal(runtime.includes('createTreeWalker'), false)
  assert.equal(runtime.includes('localizeDocument'), false)
  assert.match(runtime, /clientStaticI18nBindings/)
  assert.match(app, /const localizedNotification = item =>/)
  assert.match(app, /show_system_notification'[\s\S]*copy\.title[\s\S]*copy\.message/)
  assert.match(app, /if \(builtinAgentSettings\.length\) renderBuiltinAgentSettings\(\)/)
})

test('keeps governance columns aligned across supported window widths', () => {
  const styles = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
  assert.match(styles, /\.agent-summary\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\) 250px 104px/)
  assert.match(styles, /@media \(min-width: 1000px\) and \(max-width: 1100px\)/)
  assert.match(styles, /\.pending-skill-row\s*\{[^}]*grid-template-columns: 24px minmax\(180px, 1fr\)/)
  assert.match(styles, /html\[lang="en-US"\] \.builtin-agent-settings/)
  assert.match(styles, /@media \(max-width: 1100px\)/)
  assert.match(styles, /\.pending-skill-row[\s\S]*grid-template-columns: 24px minmax\(0, 1fr\)/)
  assert.match(styles, /\.metric-grid\s*\{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.status-metrics\s*\{\s*grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.status-metrics > :nth-child\(n \+ 3\) \{ grid-column: span 2; \}/)
})

test('persists functional client settings without a sound preference', () => {
  assert.match(appSource, /agent-manager-client-settings-v1/)
  assert.match(appSource, /clientSettings\.autoCheckUpdates/)
  assert.match(appSource, /channel: clientSettings\.updateChannel/)
  assert.match(appSource, /systemNotifications/)
  assert.doesNotMatch(indexHtml, /提示音|notification-sound/)
})

test('keeps language selection inside client settings', () => {
  assert.doesNotMatch(indexHtml, /id="locale-switch"/)
  assert.match(indexHtml, /id="settings-language"/)
  assert.match(appSource, /\$\('#settings-language'\)\.value = window\.clientI18n/)
})

test('bundles localized macOS application names', () => {
  const tauriConfig = JSON.parse(fs.readFileSync(new URL('../src-tauri/tauri.conf.json', import.meta.url), 'utf8'))
  assert.equal(
    tauriConfig.bundle.resources['infoplist/en.lproj/InfoPlist.strings'],
    'en.lproj/InfoPlist.strings',
  )
  assert.match(
    fs.readFileSync(new URL('../src-tauri/infoplist/en.lproj/InfoPlist.strings', import.meta.url), 'utf8'),
    /CFBundleDisplayName = "Agent Manager Client"/,
  )
  assert.match(
    fs.readFileSync(new URL('../src-tauri/infoplist/zh-Hans.lproj/InfoPlist.strings', import.meta.url), 'utf8'),
    /CFBundleDisplayName = "智能体生命周期管理系统客户端"/,
  )
})

test('localizes every dynamic desktop template fragment', () => {
  const app = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
  const ast = parse(app, { sourceType: 'module' })
  const failures = []
  const walk = node => {
    if (!node || typeof node !== 'object') return
    if (node.type === 'TaggedTemplateExpression' && node.tag?.name === 'tf') {
      for (const quasi of node.quasi.quasis) {
        const source = quasi.value.cooked || quasi.value.raw
        const translated = context.window.clientI18n.translateFragment(source)
        if (/[\u3400-\u9fff]/.test(translated)) failures.push(`${source} -> ${translated}`)
      }
    }
    for (const [key, value] of Object.entries(node)) {
      if (['loc', 'start', 'end', 'extra'].includes(key)) continue
      if (Array.isArray(value)) value.forEach(walk)
      else if (value && typeof value === 'object' && value.type) walk(value)
    }
  }
  walk(ast)
  assert.deepEqual(failures, [])
})
