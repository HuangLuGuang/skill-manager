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
const tauriSource = fs.readFileSync(new URL('../src-tauri/src/main.rs', import.meta.url), 'utf8')

test('classification notifications localize reasons and retain Skill names and paths', () => {
  const snippet = appSource.slice(appSource.indexOf('const localizedNotification ='), appSource.indexOf('const renderEventHistory ='))
  const i18n = context.window.clientI18n
  const previous = i18n.getLocale()
  try {
    for (const locale of ['zh-CN', 'en-US']) {
      i18n.setLocale(locale)
      const env = {
        t: i18n.t, runtimeText: i18n.translateRuntime,
        agentLabel: value => value,
        governanceLabelFor: (kind, value) => i18n.t(`ui.agentManagement.${kind}.${value}`),
      }
      vm.runInNewContext(snippet + '\nglobalThis.render = localizedNotification', env)
      const copy = env.render({ event_type: 'skill_governance_action', agent_type: 'codex', skill_name: '用户 Skill',
        details: { trigger: 'malicious', action: 'quarantine', status: 'failed', error_code: 'skill_content_changed', path: '/skills/用户 Skill' } })
      assert.equal(copy.title, locale === 'en-US' ? 'Skill Remediation Result' : 'Skill 处置结果')
      assert.ok(copy.message.includes(locale === 'en-US' ? 'Current content confirmed malicious' : '当前内容已确认恶意'))
      assert.ok(copy.message.includes(locale === 'en-US' ? 'Remediation Failed' : '处置失败'))
      assert.ok(copy.message.includes('/skills/用户 Skill'))
      assert.ok(!copy.message.includes('ui.agentManagement.'))
      assert.ok(!copy.message.includes('skill_content_changed'))
    }
  } finally { i18n.setLocale(previous) }
})

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
  assert.equal(context.window.clientI18n.t('client.models.refresh_failed'), 'Failed to Refresh Models')
  assert.equal(context.window.clientI18n.t('client.models.task_type'), 'Model Configuration')
})

test('does not expose an internal key for generated static bindings', () => {
  for (const binding of context.window.clientStaticI18nBindings) {
    const translated = context.window.clientI18n.t(binding.key)
    assert.equal(translated.startsWith('ui.'), false, binding.key)
  }
})

test('covers static Chinese desktop UI text', () => {
  const { t } = context.window.clientI18n
  const staticKeys = new Map(context.window.clientStaticI18nBindings.map(binding => [binding.source, binding.key]))
  const translate = value => t(staticKeys.get(value) || value)
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

  const missing = [...values].filter(value => /[\u3400-\u9fff]/.test(value) && translate(value) === value)
  const residualChinese = [...values].filter(
    value => /[\u3400-\u9fff]/.test(value) && /[\u3400-\u9fff]/.test(translate(value)),
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
  assert.match(styles, /\.pending-skill-row\s*\{[^}]*grid-template-columns: 24px minmax\(160px, \.85fr\) minmax\(170px, 1\.15fr\) max-content/)
  assert.match(styles, /html\[lang="en-US"\] \.builtin-agent-settings/)
  assert.match(styles, /@media \(max-width: 1100px\)/)
  assert.match(styles, /@media \(max-width: 1000px\)[\s\S]*#discover \.pending-skill-row > :nth-child\(4\)[^}]*grid-column: 2 \/ -1[^}]*grid-row: 2/)
  assert.match(styles, /\.pending-skill-row > :nth-child\(3\)[^}]*grid-row: auto[^}]*grid-column: auto[^}]*justify-self: stretch/)
  assert.match(styles, /\.pending-skill-row > :nth-child\(4\)[^}]*grid-row: auto[^}]*grid-column: auto[^}]*justify-self: end/)
  assert.match(styles, /\.metric-grid\s*\{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.status-metrics\s*\{\s*grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/)
  assert.match(styles, /\.status-metrics > :nth-child\(n \+ 3\) \{ grid-column: span 2; \}/)
  assert.match(styles, /\.task-history-columns > :nth-child\(2\),[\s\S]*\.task-history-row > :nth-child\(3\)[^{]*\{[^}]*text-align: center/)
  assert.match(styles, /\.task-history-columns > :nth-child\(4\),[\s\S]*\.task-history-row > :nth-child\(4\)[^{]*\{[^}]*text-align: right/)
  assert.match(styles, /\.takeover-column-head\.task-history-columns,\s*\.takeover-list \.takeover-row\.task-history-row\s*\{[^}]*grid-template-columns: minmax\(220px, 1fr\) 120px 90px 160px[^}]*gap: 14px[^}]*padding-left: 16px/)
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

test('switches gateway models from live local Agent configuration without exposing credentials', () => {
  assert.match(indexHtml, /data-panel="models"/)
  assert.match(indexHtml, /id="model-agent-tabs"/)
  assert.doesNotMatch(indexHtml, /id="model-binding-dialog"/)
  assert.match(appSource, /model_config_state/)
  assert.match(appSource, /model_configuration/)
  assert.match(appSource, /run\('switch-model', args\)/)
  assert.match(appSource, /return executeModelSwitch\(agent, model, button\)/)
  assert.doesNotMatch(appSource, /缺少可关联的 Agent/)
  assert.doesNotMatch(appSource, /switch-model[^\n]*--token/)
  assert.match(tauriSource, /"switch-model"/)
  assert.doesNotMatch(appSource, /t\('刷新模型失败'\)|t\('模型配置'\)/)
})

test('edits an existing connection in a modal without reopening the inline form', () => {
  assert.match(indexHtml, /<dialog id="edit-connection-dialog"/)
  assert.match(indexHtml, /<form id="edit-connection-form"/)
  assert.match(appSource, /\$\('#edit-connection-dialog'\)\.showModal\(\)/)
  assert.match(appSource, /run\('service-status'\)[\s\S]*run\('prepare-update'\)[\s\S]*run\('reconcile-service'\)/)
  assert.equal(appSource.includes("$('#connect-form').hidden = false\n  $('#server').value = connection"), false)
})

test('groups Skills and recovery in Agent Management', () => {
  const management = indexHtml.split('<section id="discover"')[1].split('<section id="models"')[0]
  for (const id of ['agent-list', 'platform-install-button', 'pending-list', 'quarantine-list']) {
    assert.ok(management.includes(`id="${id}"`), id)
  }
  assert.equal(context.window.clientI18n.t('ui.agentManagement.title'), 'Agent Management')
  const settings = indexHtml.split('<section id="settings"')[1]
  for (const id of ['backup-select', 'refresh-backups', 'restore-backup']) {
    assert.ok(settings.includes(`id="${id}"`), id)
  }
})

test('rediscovers local Agents before refreshing governance after an install', () => {
  assert.match(
    appSource,
    /const refreshAfterInstall = async \(\) => \{[\s\S]*await discover\(\)[\s\S]*await refreshConnection\(\)[\s\S]*await loadPending\(\)/,
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
  assert.match(appSource, /quarantine-skill-identity[\s\S]*history-details[\s\S]*quarantineDetectionGuidance[\s\S]*quarantine-status[\s\S]*quarantine-actions/)
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

test('pending copies remain actionable in recovery while submitted scans use independent history', () => {
  assert.match(appSource, /data-discard-copy[\s\S]*discard-pending-dialog'\)\.showModal\(\)/)
  assert.match(appSource, /confirm-discard-pending[\s\S]*run\('discard-pending', \['--id', item\.id, '--confirm'\]\)/)
  assert.match(appSource, /scanHistoryItems = JSON.parse\(await run\(refresh \? 'refresh-scan-history' : 'scan-history'\)\)/)
  assert.match(appSource, /const copies = pendingItems.filter\(item => item.reason !== 'observed_scan'/)
  assert.match(appSource, /pending_copy_id \? \{id: copy.pending_copy_id\}/)
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
