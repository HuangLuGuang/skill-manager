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
  document: {
    documentElement: {},
    querySelector: () => null,
    querySelectorAll: () => [],
  },
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
const stylesSource = fs.readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')

test('translates core desktop navigation and product name', () => {
  const { t } = context.window.clientI18n
  assert.equal(t('智能体生命周期管理系统'), 'Agent Manager')
  assert.equal(t('客户端接入'), 'Client Access')
  assert.equal(t('客户端概览'), 'Client Overview')
  assert.equal(t('Agent 发现'), 'Agent Discovery')
  assert.equal(t('Skill 治理'), 'Skill Governance')
  assert.equal(t('运行状态'), 'Runtime Status')
  assert.equal(t('执行记录'), 'Activity Records')
  assert.equal(t('ui.75sttk'), 'Quarantined')
  assert.equal(t('ui.8lsmup'), 'The submitted version was not approved and remains disabled. If the platform has an approved version, select it for installation.')
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

test('turns connection failures into friendly messages without JSON payloads', () => {
  const { connectionErrorText, setLocale } = context.window.clientI18n
  setLocale('zh-CN')
  assert.equal(
    connectionErrorText('error: Agent Manager 返回 403 Forbidden: {"detail":"接入凭证无效或已禁用","error_code":"credential.invalid_or_disabled","error_params":{}}'),
    '客户端接入凭证无效或已禁用，请更换有效凭证后重试。',
  )
  assert.equal(
    connectionErrorText('error: Post "http://127.0.0.1:8000/api/v1/clients/register": dial tcp 127.0.0.1:8000: connect: connection refused'),
    '无法连接 Agent Manager。请确认平台地址和端口填写正确，并确认平台服务已启动。',
  )
  setLocale('en-US')
  assert.equal(
    connectionErrorText('error: Agent Manager 返回 403 Forbidden: {"detail":"接入凭证无效或已禁用","error_code":"credential.invalid_or_disabled","error_params":{}}'),
    'The client credential is invalid or disabled. Replace it with an active credential and try again.',
  )
})

test('supports stable desktop message keys', () => {
  assert.equal(context.window.clientI18n.t('ui.png61n'), 'Last operation')
  assert.equal(context.window.clientI18n.t('status.platform_scanning'), 'Platform scan in progress')
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
  assert.match(styles, /\.pending-skill-row\s*\{[^}]*grid-template-columns: 24px minmax\(160px, \.85fr\) minmax\(170px, 1\.15fr\) 206px/)
  assert.match(styles, /html\[lang="en-US"\] \.builtin-agent-settings/)
  assert.match(styles, /@media \(max-width: 1100px\)/)
  assert.match(styles, /@media \(max-width: 1100px\)[\s\S]*\.pending-skill-row\s*\{[^}]*grid-template-columns: 24px minmax\(160px, \.85fr\) minmax\(170px, 1\.15fr\) 206px/)
  assert.match(styles, /\.pending-skill-row > :nth-child\(3\)[^}]*grid-row: auto[^}]*grid-column: auto[^}]*justify-self: stretch/)
  assert.match(styles, /\.pending-skill-row > :nth-child\(4\)[^}]*grid-row: auto[^}]*grid-column: auto[^}]*justify-self: end/)
  assert.match(styles, /\.metric-grid\s*\{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.status-metrics\s*\{\s*grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.status-metrics > :nth-child\(n \+ 3\) \{ grid-column: span 2; \}/)
  assert.match(styles, /\.rail-note > div\s*\{[^}]*display:\s*grid/)
  assert.match(styles, /\.rail-note strong\s*\{[^}]*white-space:\s*nowrap/)
  assert.match(indexHtml, /class="rail-tagline">统一治理智能体配置、能力与运行安全。<\/p>[\s\S]*<nav/)
  assert.doesNotMatch(indexHtml, /class="rail-note"[^>]*>[\s\S]*统一治理智能体配置、能力与运行安全。/)
  assert.match(styles, /\.rail-tagline\s*\{[^}]*font-size:\s*10px/)
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

test('edits an existing connection in a modal without reopening the inline form', () => {
  assert.match(indexHtml, /<dialog id="edit-connection-dialog"/)
  assert.match(indexHtml, /<form id="edit-connection-form"/)
  assert.match(appSource, /\$\('#edit-connection-dialog'\)\.showModal\(\)/)
  assert.match(appSource, /run\('service-status'\)[\s\S]*run\('prepare-update'\)[\s\S]*run\('reconcile-service'\)/)
  assert.equal(appSource.includes("$('#connect-form').hidden = false\n  $('#server').value = connection"), false)
})

test('keeps platform recovery out of Agent discovery', () => {
  assert.doesNotMatch(indexHtml, /id="discover-platform-install-button"/)
  assert.match(indexHtml, /id="open-preview-button"[^>]*>生成接管预览</)
  assert.match(appSource, /previewButton\.disabled = selectedSkillPaths\.size === 0/)
  assert.doesNotMatch(appSource, /previewButton\.dataset\.action/)
})

test('rediscovers local Agents before refreshing governance after an install', () => {
  assert.match(
    appSource,
    /const refreshAfterInstall = async \(\) => \{[\s\S]*await discover\(\)[\s\S]*await refreshConnection\(\)[\s\S]*await preview\(false\)/,
  )
})

test('falls back to exact trusted versions when an older sidecar ignores skill-id', () => {
  assert.match(
    appSource,
    /const exactAvailableSkillForAgent = async[\s\S]*availableSkillsForAgent\(agent, '', skill\.skill_id\)[\s\S]*skillVersionsForAgent\(agent, skill\.skill_id\)/,
  )
  assert.match(
    appSource,
    /Promise\.all\(agents\.map\(agent => exactAvailableSkillForAgent\(agent, skill\)\)\)/,
  )
})

test('reconciles the governance service without restarting an unchanged binary', () => {
  assert.match(
    appSource,
    /const initializeClient = async[\s\S]*run\('reconcile-service'\)/,
  )
  assert.doesNotMatch(appSource, /initializeClient[\s\S]*reconcile-service', \['--force-restart'\]/)
})

test('shows quarantine detection progress without offering duplicate submission', () => {
  assert.match(
    appSource,
    /const loadQuarantine = async[\s\S]*item\.detection_status[\s\S]*pendingStatusLabel\(detection\.status\)[\s\S]*!item\.skill_id/,
  )
  const submitHandler = appSource.match(
    /document\.querySelectorAll\('\[data-submit-quarantine\]'\)[\s\S]*?document\.querySelectorAll\('\[data-install-safe-version\]'/,
  )?.[0]
  assert.ok(submitHandler)
  assert.doesNotMatch(submitHandler, /showPanel\('takeover'\)/)
  assert.match(submitHandler, /await submitPendingIDs\(\[pending\.id\], button\)[\s\S]*await refreshConnection\(\)[\s\S]*await loadQuarantine\(\)/)
  assert.match(appSource, /if \(item\.skill_id\) return t\('status\.platform_scanning'\)/)
  assert.doesNotMatch(appSource, /ui\.10hw1zw/)
  assert.match(appSource, /quarantine-skill-identity[\s\S]*quarantine-status[\s\S]*quarantine-guidance[\s\S]*quarantine-actions/)
  assert.match(stylesSource, /\.quarantine-row\s*\{[^}]*grid-template-columns: minmax\(260px, 1fr\) 100px minmax\(220px, \.65fr\) 210px/)
  assert.match(stylesSource, /\.quarantine-actions\s*\{[^}]*width:\s*210px/)
  assert.doesNotMatch(appSource, /平台正在检测\$\{item\.skill_id/)
})

test('refreshes the visible quarantine list after background status changes', () => {
  assert.match(
    appSource,
    /const refreshChangedInventory = async[\s\S]*const quarantineChanged = local\.quarantined_skills !== connection\.local\?\.quarantined_skills[\s\S]*if \(refreshQuarantine\) await loadQuarantine\(\)/,
  )
})

test('drops detached submissions from the current pending batch count', () => {
  assert.match(
    appSource,
    /const reconcilePendingBatchTracking = \(\) => \{[\s\S]*if \(item && !item\.skill_id\)[\s\S]*pendingBatchTracking\.ids\.delete\(id\)[\s\S]*pendingBatchTracking\.statuses\.delete\(id\)/,
  )
  assert.match(appSource, /const renderPendingBatchStatus = \(\) => \{\s*reconcilePendingBatchTracking\(\)/)
})

test('requires confirmation before discarding one local pending copy', () => {
  assert.match(
    appSource,
    /data-discard-pending[\s\S]*discard-pending-dialog'\)\.showModal\(\)[\s\S]*confirm-discard-pending[\s\S]*run\('discard-pending', \['--id', item\.id, '--confirm'\]\)[\s\S]*await loadPending\(\)[\s\S]*await loadQuarantine\(\)[\s\S]*await refreshConnection\(\)/,
  )
  assert.doesNotMatch(appSource, /确定永久删除这个本地停用副本吗/)
  assert.match(indexHtml, /id="discard-pending-dialog"[\s\S]*平台检测版本和审计记录会保留/)
})

test('renders compact pending rows with inline platform actions', () => {
  assert.match(
    appSource,
    /pending-skill-identity[\s\S]*pending-skill-status[\s\S]*takeover-row-actions pending-inline-actions[\s\S]*item\.platform_installable[\s\S]*从平台安装[\s\S]*data-submit-pending[\s\S]*data-discard-pending/,
  )
  assert.match(appSource, /pendingPlatformVersionFor[\s\S]*exactAvailableSkillForAgent/)
  assert.match(appSource, /enrichPendingPlatformVersions[\s\S]*items = await enrichPendingPlatformVersions/)
  assert.match(appSource, /item\.status === 'APPROVED'[\s\S]*platform_version_id: item\.version_id \|\| ''[\s\S]*platform_installable: Boolean\(item\.skill_id\)/)
  assert.match(appSource, /data-version-id="\$\{escapeHtml\(item\.platform_version_id \|\| ''\)\}"/)
  assert.match(appSource, /const installPlatformSkill = async[\s\S]*if \(versionId\) args\.push\('--version-id', versionId\)/)
  assert.match(stylesSource, /\.pending-inline-actions\s*\{[^}]*display:\s*flex[^}]*width:\s*206px[^}]*justify-content:\s*flex-end/)
  assert.match(stylesSource, /\.pending-inline-actions button\s*\{[^}]*width:\s*100px[^}]*height:\s*34px/)
  assert.doesNotMatch(appSource, /pending-primary-slot|pending-action-placeholder/)
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
