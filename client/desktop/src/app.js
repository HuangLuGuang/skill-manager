const invoke = window.__TAURI__.core.invoke
const t = window.clientI18n?.t || (value => value)
const tf = window.clientI18n?.tf || ((strings, ...values) =>
  strings.reduce((result, value, index) => result + value + (values[index] ?? ''), ''))
const runtimeText = window.clientI18n?.translateRuntime || (value => String(value ?? ''))
const connectionErrorText = window.clientI18n?.connectionErrorText || runtimeText
const isEnglish = () => window.clientI18n?.getLocale?.() === 'en-US'
const formatList = values => new Intl.ListFormat(window.clientI18n?.getLocale?.() || 'zh-CN').format(values.filter(Boolean))
const skillCount = count => isEnglish()
  ? `${count} Skill${Number(count) === 1 ? '' : 's'}`
  : `${count} 个 Skill`
const agentCount = count => isEnglish()
  ? `${count} Agent${Number(count) === 1 ? '' : 's'}`
  : `${count} 个 Agent`
const panelTitle = panel => ({
  connect: t('ui.wu8jgp'),
  discover: t('ui.agentManagement.title'),
  models: t('client.models.title'),
  notifications: t('ui.1atia5p'),
  records: t('ui.cn5hhp'),
  settings: t('设置'),
}[panel] || panel)
let inventory = null
let connection = null
const submittingObservedPaths = new Set()
let pendingSkillAction = null
let requestingSkillAction = false
let installCatalog = []
let installVersions = []
let lockedInstallSkill = null
let installAgentContext = ''
let installSearchTimer = null
let lastInventoryAt = ''
let autoRefreshBusy = false
let notificationFilter = 'all'
let customAgentPendingRemoval = null
let builtinAgentSettings = []
let editingBuiltinAgent = null
let selectedModelAgentID = ''
let modelSearch = ''
let pendingItems = []
let pendingDiscardItem = null
let pendingRefreshTimer = null
let pendingRefreshBusy = false
let pendingSubmissionBusy = false
const submittingQuarantineIDs = new Set()
let pendingClientUpdate = null
let clientUpdateInstalling = false
let clientUpdateCheckBusy = false
let lastAutomaticUpdateCheckAt = 0
let clientBuildVersion = 'dev'
const selectedPendingIDs = new Set()
const notificationDeliveryAttempts = new Set()
const operationProgress = new Map()
const CLIENT_UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
const CLIENT_UPDATE_NOTIFIED_KEY = 'agent-manager-client-update-notified'
const CLIENT_SETTINGS_KEY = 'agent-manager-client-settings-v1'
const DEFAULT_CLIENT_SETTINGS = {
  defaultPanel: 'connect',
  systemNotifications: true,
  notificationLevel: 'info',
  autoCheckUpdates: true,
  updateChannel: 'stable',
}
const loadClientSettings = () => {
  try {
    const saved = { ...DEFAULT_CLIENT_SETTINGS, ...JSON.parse(localStorage.getItem(CLIENT_SETTINGS_KEY) || '{}') }
    if (saved.defaultPanel === 'takeover') saved.defaultPanel = 'discover'
    if (saved.defaultPanel === 'status') saved.defaultPanel = 'settings'
    return saved
  } catch {
    return { ...DEFAULT_CLIENT_SETTINGS }
  }
}
let clientSettings = loadClientSettings()
const saveClientSettings = patch => {
  clientSettings = { ...clientSettings, ...patch }
  localStorage.setItem(CLIENT_SETTINGS_KEY, JSON.stringify(clientSettings))
  syncSettingsControls()
}

const syncSettingsControls = () => {
  if (!$('#settings-language')) return
  $('#settings-server').textContent = connection?.server || t('ui.settings.not_connected')
  $('#settings-language').value = window.clientI18n?.getLocale?.() || 'zh-CN'
  $('#settings-default-panel').value = clientSettings.defaultPanel
  $('#settings-system-notifications').checked = clientSettings.systemNotifications
  $('#settings-notification-level').value = clientSettings.notificationLevel
  $('#settings-notification-level').disabled = !clientSettings.systemNotifications
  $('#settings-auto-update').checked = clientSettings.autoCheckUpdates
  $('#settings-update-channel').value = clientSettings.updateChannel
  $('#settings-service-detail').textContent = !connection?.configured
    ? t('请先完成客户端接入。')
    : connection.service_running
      ? t('后台治理服务正在运行，并会在登录系统后自动启动。')
      : connection.service_installed
        ? t('后台治理服务已安装，但当前未运行。')
        : t('ui.background.start_failed')
  $('#settings-update-status').textContent = pendingClientUpdate?.available
    ? tf`发现新版本 ${clientUpdateVersion(pendingClientUpdate)}`
    : tf`当前版本 ${clientBuildVersion} · ${clientSettings.updateChannel === 'preview' ? t('测试通道') : t('正式通道')}`
}

const $ = selector => document.querySelector(selector)
const setBusy = (button, busy) => {
  button.disabled = busy
  button.classList.toggle('is-busy', busy)
  if (busy) {
    button.dataset.original = button.textContent
    button.dataset.busyLabel = button.dataset.busyText || t('ui.1j4vco4')
    button.textContent = button.dataset.busyLabel
  } else if (button.textContent === button.dataset.busyLabel) {
    button.textContent = button.dataset.original
  }
}
const run = async (command, args = []) => invoke('execute_client', { command, args })
const log = value => {
  $('#status-last-operation').textContent = `${t('ui.png61n')}：${new Date().toISOString()} · ${runtimeText(value || t('ui.rxr1o0'))}`
}
const showMessageDialog = (title, detail) => {
  $('#message-dialog-title').textContent = title
  $('#message-dialog-detail').textContent = runtimeText(detail)
  $('#message-dialog').showModal()
}

const formatUpdateBytes = value => {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

const renderClientUpdateProgress = payload => {
  const progress = $('#client-update-progress')
  if (!progress) return
  const stage = payload?.stage || 'preparing'
  const downloaded = Number(payload?.downloaded || 0)
  const total = Number(payload?.total || 0)
  const percentage = total > 0 ? Math.min(100, Math.round((downloaded / total) * 100)) : 0
  const content = {
    preparing: [t('ui.wvy19q'), t('ui.1i0h4nk')],
    downloading: [t('ui.1f0r4xl'), total > 0
      ? tf`已下载 ${formatUpdateBytes(downloaded)} / ${formatUpdateBytes(total)}`
      : tf`已下载 ${formatUpdateBytes(downloaded)}`],
    installing: [t('ui.11861uk'), t('ui.1nkk2ub')],
    restarting: [t('ui.ldl6iz'), t('ui.1yg1pqe')],
  }[stage] || [t('ui.4enimb'), t('ui.123u0aw')]
  progress.hidden = false
  progress.classList.toggle('indeterminate', total <= 0 || stage !== 'downloading')
  progress.querySelector('[data-progress-title]').textContent = content[0]
  progress.querySelector('[data-progress-detail]').textContent = content[1]
  progress.querySelector('[data-progress-elapsed]').textContent = total > 0 && stage === 'downloading' ? `${percentage}%` : t('ui.1h3kna')
  progress.querySelector('[data-progress-bar]').style.width = total > 0 && stage === 'downloading' ? `${percentage}%` : ''
}

if (window.__TAURI__.event?.listen) {
  window.__TAURI__.event
    .listen('client-update-progress', event => renderClientUpdateProgress(event.payload))
    .catch(error => log(tf`更新进度监听失败：${error}`))
}

const startOperationProgress = (selector, { title, detail, current = 0, total = 0 }) => {
  const element = $(selector)
  if (!element) return
  const previous = operationProgress.get(selector)
  if (previous?.timer) clearInterval(previous.timer)
  const startedAt = Date.now()
  const state = {
    startedAt,
    timer: setInterval(() => {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
      element.querySelector('[data-progress-elapsed]').textContent = tf`已用时 ${elapsed} 秒`
    }, 1000),
  }
  operationProgress.set(selector, state)
  element.hidden = false
  element.classList.toggle('indeterminate', total <= 0)
  element.querySelector('[data-progress-title]').textContent = title
  element.querySelector('[data-progress-detail]').textContent = detail
  element.querySelector('[data-progress-elapsed]').textContent = t('ui.i9ne2h')
  element.querySelector('[data-progress-bar]').style.width = total > 0 ? `${Math.round((current / total) * 100)}%` : ''
}

const updateOperationProgress = (selector, { title, detail, current, total }) => {
  const element = $(selector)
  if (!element) return
  if (title) element.querySelector('[data-progress-title]').textContent = title
  if (detail) element.querySelector('[data-progress-detail]').textContent = detail
  if (total > 0) {
    element.classList.remove('indeterminate')
    element.querySelector('[data-progress-bar]').style.width = `${Math.round((current / total) * 100)}%`
  }
}

const stopOperationProgress = selector => {
  const state = operationProgress.get(selector)
  if (state?.timer) clearInterval(state.timer)
  operationProgress.delete(selector)
  const element = $(selector)
  if (element) element.hidden = true
}

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-reveal-path]')
  if (!button || button.disabled) return
  event.preventDefault()
  event.stopPropagation()
  button.disabled = true
  button.setAttribute('aria-busy', 'true')
  try {
    await invoke('reveal_path', { path: button.dataset.revealPath })
  } catch (error) {
    showMessageDialog(t('ui.17y2ac'), String(error))
  } finally {
    button.disabled = false
    button.removeAttribute('aria-busy')
  }
})

const isCustomAgent = agent => Boolean(agent?.capabilities?.custom)
const isSharedSkills = agent => agent?.agent_type === 'global-skills'
const skillSharedReaders = (agent, path) => {
  const capabilities = agent?.capabilities || {}
  const root = String(path || '').replace(/[\\/][^\\/]+$/, '')
  return capabilities.shared_skill_readers_by_path?.[path]
    ?? capabilities.shared_skill_readers_by_root?.[root]
    ?? (capabilities.shared_skills ? capabilities.shared_skill_readers || [] : [])
}

const showPanel = panel => {
  document.querySelectorAll('.nav-item, .panel').forEach(item => item.classList.remove('active'))
  document.querySelector(`.nav-item[data-panel="${panel}"]`)?.classList.add('active')
  $('#notification-trigger').classList.toggle('active', panel === 'notifications')
  $('#settings-trigger').classList.toggle('active', panel === 'settings')
  $(`#${panel}`).classList.add('active')
  $('#panel-title').textContent = panelTitle(panel)
  $('.workspace').scrollTop = 0
  if (panel === 'discover' && connection?.configured) {
    requestAnimationFrame(() => { syncAgentScroll(); revealSelectedAgent() })
    void loadPending().catch(log)
    void loadQuarantine().catch(log)
  }
  if (panel === 'models' && connection) renderModelSwitcher(connection)
  if (panel === 'notifications') refreshConnection()
  if (panel === 'records') void loadRecordHistory()
  if (panel === 'settings') {
    syncSettingsControls()
    void loadBackups().catch(log)
  }
}

document.querySelectorAll('.nav-item').forEach(button => {
  button.addEventListener('click', () => showPanel(button.dataset.panel))
})

const switchOverviewTab = key => {
  document.querySelectorAll('[data-overview-tab]').forEach(button => {
    const selected = button.dataset.overviewTab === key
    button.setAttribute('aria-selected', String(selected))
    button.tabIndex = selected ? 0 : -1
    document.getElementById(button.getAttribute('aria-controls')).hidden = !selected
  })
  $('.overview-tab-content').scrollTop = 0
}
document.querySelectorAll('[data-overview-tab]').forEach(button => {
  button.addEventListener('click', () => switchOverviewTab(button.dataset.overviewTab))
  button.addEventListener('keydown', event => {
    const tabs = [...document.querySelectorAll('[data-overview-tab]')]
    const index = tabs.indexOf(button)
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1
    if (target < 0) return
    event.preventDefault()
    switchOverviewTab(tabs[target].dataset.overviewTab)
    tabs[target].focus()
  })
})

const saveConnection = async ({ button, server, token, name, onSuccess }) => {
  if (button.disabled) return
  setBusy(button, true)
  let saved = false
  let serviceNeedsRestart = false
  try {
    const args = ['--server', server, '--token', token]
    if (name.trim()) args.push('--name', name.trim())
    log(await run('register', args))
    const service = JSON.parse(await run('service-status'))
    if (service.installed) {
      await run('prepare-update')
      serviceNeedsRestart = true
    }
    await run('configure', args)
    saved = true
    await run('reconcile-service')
    serviceNeedsRestart = false
    await refreshConnection()
    onSuccess()
  } catch (error) {
    showMessageDialog(
      saved ? t('ui.6vfjws') : t('ui.1jl22hu'),
      saved
        ? tf`连接配置已经保存，但暂时无法刷新状态。\n${connectionErrorText(error)}`
        : tf`设置尚未保存。\n${connectionErrorText(error)}`,
    )
    log(error)
  } finally {
    if (serviceNeedsRestart) {
      try { await run('reconcile-service') } catch (error) { log(error) }
    }
    setBusy(button, false)
  }
}

$('#connect-form').addEventListener('submit', async event => {
  event.preventDefault()
  await saveConnection({
    button: event.submitter,
    server: $('#server').value,
    token: $('#token').value,
    name: $('#client-name').value,
    onSuccess: () => showPanel('connect'),
  })
})

const policyLabel = value => ({ audit: t('ui.1n7b1v3'), repair: t('ui.1fftepa'), block: t('ui.1lg89ho') }[value] || value || '-')
const governanceLabel = value => ({ registry: t('ui.12wr3db'), strict: t('ui.1bqmand') }[value] || value || t('ui.12wr3db'))
const formatTime = value => {
  if (!value) return '-'
  const text = String(value)
  const normalized = /^\d{4}-\d{2}-\d{2}T/.test(text) && !/(Z|[+-]\d{2}:?\d{2})$/.test(text) ? `${text}Z` : text
  return new Date(normalized).toLocaleString(window.clientI18n?.getLocale?.() || 'zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
const setProgress = (id, state) => {
  const element = $(`#${id}`)
  element.classList.remove('done', 'current')
  if (state) element.classList.add(state)
}
const renderDisconnected = () => {
  $('#connection-intro').hidden = false
  $('#credential-tip').hidden = false
  $('#connected-overview').hidden = true
  $('#connect-form').hidden = false
  $('#token').required = true
  $('#token').value = ''
  $('#token').placeholder = 'amat_...'
  $('#connect-submit').textContent = t('ui.nonmak')
  $('#connection-state').textContent = t('ui.1gwretz')
  $('#connection-state').classList.remove('online')
  $('#notification-trigger').hidden = true
  $('#model-permission-note').textContent = t('client.models.connect_first')
  $('#model-agent-tabs').innerHTML = ''
  $('#model-current').innerHTML = ''
  $('#model-catalog').classList.add('empty')
  $('#model-catalog').textContent = t('client.models.connect_to_load')
  $('#panel-title').textContent = t('ui.wu8jgp')
  syncSettingsControls()
}
const editConnection = () => {
  $('#edit-server').value = connection?.server || ''
  $('#edit-client-name').value = connection?.name || connection?.platform?.name || ''
  $('#edit-token').value = ''
  $('#edit-connection-dialog').showModal()
  $('#edit-server').focus()
}

$('#edit-connection-form').addEventListener('submit', async event => {
  event.preventDefault()
  await saveConnection({
    button: event.submitter,
    server: $('#edit-server').value,
    token: $('#edit-token').value,
    name: $('#edit-client-name').value,
    onSuccess: () => $('#edit-connection-dialog').close(),
  })
})

$('#cancel-edit-connection').addEventListener('click', () => {
  $('#edit-token').value = ''
  $('#edit-connection-dialog').close()
})

const renderBuiltinAgentSettings = () => {
  const element = $('#builtin-agent-settings')
  element.innerHTML = builtinAgentSettings.length
    ? builtinAgentSettings.map(item => {
      const readers = item.shared_skill_readers || []
      return tf`
      <button class="builtin-agent-row${item.shared_skills ? ' shared' : ''}" type="button" data-edit-agent-paths="${escapeHtml(item.agent_type)}">
        <span class="builtin-agent-name"><strong>${escapeHtml(agentLabel(item.agent_type))}</strong>${item.shared_skills ? t('ui.qn1hdp') : ''}${item.customized ? t('ui.xtw2wn') : ''}</span>
        <span class="builtin-agent-roots">${item.current_roots.map(root => `<code title="${escapeHtml(root)}">${escapeHtml(root)}</code>`).join('')}</span>
        ${item.shared_skills ? tf`<span class="builtin-agent-hint">可能由 ${escapeHtml(formatList(readers) || t('ui.waagmd'))} 读取，实际以版本和配置为准</span>` : ''}
        <span class="builtin-agent-edit">修改目录</span>
      </button>`
    }).join('')
    : t('ui.11mm43w')
  document.querySelectorAll('[data-edit-agent-paths]').forEach(button => button.addEventListener('click', () => {
    editingBuiltinAgent = builtinAgentSettings.find(item => item.agent_type === button.dataset.editAgentPaths) || null
    if (!editingBuiltinAgent) return
    $('#agent-paths-title').textContent = tf`修改 ${agentLabel(editingBuiltinAgent.agent_type)} 扫描目录`
    $('#agent-paths-input').value = editingBuiltinAgent.current_roots.join('\n')
    $('#agent-paths-default').textContent = tf`默认目录：${editingBuiltinAgent.default_roots.join('；')}`
    $('#reset-agent-paths').disabled = !editingBuiltinAgent.customized
    $('#agent-paths-dialog').showModal()
  }))
}

const loadBuiltinAgentSettings = async (force = false) => {
  if (builtinAgentSettings.length && !force) return
  builtinAgentSettings = JSON.parse(await run('agent-settings'))
  renderBuiltinAgentSettings()
}

const renderConnected = data => {
  const platform = data.platform || {}
  const agents = data.inventory?.agents || []
  const localAgents = agents.filter(agent => !isSharedSkills(agent))
  const platformAgents = platform.agents || []
  const platformByType = Object.fromEntries(platformAgents.map(agent => [agent.agent_type, agent]))
  const governableTargets = agents.filter(agent => agent.skill_management_supported)
  const supported = localAgents.filter(agent => agent.skill_management_supported)
  const bound = supported.filter(agent => platformByType[agent.agent_type]?.managed_agent_id)
  const strict = platform.governance_mode === 'strict'
  const managedSkills = platformAgents.reduce((count, agent) => count + (agent.skills || []).filter(skill => skill.skill_id).length, 0)
  const todos = []
  const local = data.local || {}
  const inventorySynced = Boolean(local.sync?.inventory?.last_success_at)
  const patrolActive = Boolean(data.service_running)
  const connectionError = !data.connected
  if (connectionError) {
    todos.push({ title: t('ui.1i3u5zy'), detail: runtimeText(data.error || t('ui.14ahndy')), action: t('ui.xhhfbd'), actionType: 'refresh', error: true })
  }
  if (data.connected && governableTargets.length === 0) {
    todos.push({ title: t('ui.1uwxfnn'), detail: t('ui.1syv6zk'), action: t('ui.ooab5x'), panel: 'discover' })
  }
  if (data.connected && strict && supported.length > bound.length) {
    todos.push({ title: tf`${supported.length - bound.length} 个 Agent 尚未绑定`, detail: t('ui.tq4rjs'), action: t('ui.67hphv'), panel: 'discover' })
  }
  if (data.configured && !data.service_running) {
    todos.push({
      title: data.service_installed ? t('ui.cewtrw') : t('ui.ur9dh5'),
      detail: runtimeText(data.service_detail || t('ui.17kvfer')),
      action: t('ui.background.retry'), actionType: 'install-service', error: data.service_installed,
    })
  }
  const attentionCopies = recoveryItems.filter(item => item.status !== 'backed_up' && item.status !== 'restored')
  if (attentionCopies.length) {
    todos.push({ title: t('ui.overview.attention_copies').replace('{count}', attentionCopies.length), detail: t('ui.overview.attention_hint'), action: t('ui.overview.view_copies'), panel: 'discover', view: 'recovery' })
  }
  if ((local.queued_events || 0) > 0) {
    todos.push({ title: tf`${local.queued_events} 条审计事件待补报`, detail: t('ui.1smkxvk'), action: t('ui.1hbudir'), actionType: 'refresh' })
  }

  $('#connection-intro').hidden = true
  $('#credential-tip').hidden = true
  $('#connect-form').hidden = true
  $('#token').value = ''
  $('#connected-overview').hidden = false
  $('#connection-state').textContent = data.connected ? t('ui.id9tin') : t('ui.19towct')
  $('#connection-state').classList.toggle('online', data.connected)
  $('#notification-trigger').hidden = false
  const activePanel = document.querySelector('.panel.active')?.id || 'connect'
  $('#panel-title').textContent = panelTitle(activePanel)
  $('#overview-badge').className = `overview-badge${connectionError ? ' error' : ''}`
  $('#overview-badge').textContent = connectionError ? t('ui.19towct') : t('ui.id9tin')
  $('#overview-title').textContent = platform.name || data.name || data.inventory?.hostname || t('ui.13nfgz7')
  const lastSync = t('ui.overview.synced').replace('{time}', formatTime(local.sync?.inventory?.last_success_at || platform.last_seen_at))
  $('#overview-subtitle').textContent = connectionError ? runtimeText(data.error || t('ui.cvy3o')) : lastSync
  $('#overview-service').textContent = t(patrolActive ? 'ui.overview.running' : 'ui.overview.stopped')
  $('#overview-service').classList.toggle('error', !patrolActive)
  const appliedPolicy = local.classification
  const currentPolicyText = appliedPolicy?.enabled
    ? t('ui.overview.policy_managed')
    : platform.classification?.enabled
      ? t('ui.overview.policy_pending')
      : policyLabel(platform.policy_mode)
  $('#overview-policy').textContent = currentPolicyText
  const policyGroups = [
    ['unverified', ['unverified', 'unverified_content_changed']],
    ['trusted', ['trusted_content_changed']],
    ['results', ['malicious', 'trusted_scan_rejected', 'unverified_scan_rejected']],
  ]
  $('#overview-policy-rules').innerHTML = appliedPolicy?.enabled ? policyGroups.map(([group, triggers]) => {
    const rows = triggers.filter(trigger => Object.hasOwn(appliedPolicy.rules || {}, trigger)).map(trigger => `<div class="policy-rule-row"><dt>${escapeHtml(governanceLabelFor('trigger', trigger))}</dt><dd><span class="policy-action policy-action-${['record', 'record_only', 'submit_scan', 'quarantine', 'uninstall', 'restore_trusted'].includes(appliedPolicy.rules[trigger]) ? appliedPolicy.rules[trigger] : 'unknown'}">${escapeHtml(governanceLabelFor('action', appliedPolicy.rules[trigger]))}</span></dd></div>`).join('')
    return rows ? `<section class="policy-rule-group policy-rule-group-${group}"><h3>${escapeHtml(t(`ui.overview.policy_group.${group}`))}</h3><dl class="detail-list">${rows}</dl></section>` : ''
  }).join('') : ''
  $('#overview-last-sync').textContent = lastSync
  $('#overview-sync').textContent = connectionError ? t('ui.xhhfbd') : t('ui.2fhcc7')

  $('#metric-agents').textContent = localAgents.length
  $('#metric-bound').textContent = strict ? `${bound.length} / ${supported.length}` : supported.length
  $('#metric-bound-label').textContent = strict ? t('ui.1idv0ac') : t('ui.16k09ve')
  $('#metric-skills').textContent = local.managed_skills ?? managedSkills
  $('#metric-todos').textContent = todos.length
  $('#metric-todos').hidden = todos.length === 0
  $('#overview-todo-summary').textContent = todos.length ? t('ui.overview.todo_hint').replace('{count}', todos.length) : ''
  $('#overview-all-clear').hidden = todos.length !== 0
  $('#progress-summary').textContent = data.connected
    ? t('ui.agentManagement.automatic')
    : t('ui.agentManagement.offline')
  setProgress('step-connect', data.connected ? 'done' : 'current')
  setProgress('step-discover', governableTargets.length ? 'done' : data.connected ? 'current' : '')
  $('#step-bind span').textContent = t('ui.agentManagement.inventory_sync')
  setProgress('step-bind', inventorySynced ? 'done' : 'current')
  $('#step-service span').textContent = t('ui.background.title')
  setProgress('step-service', patrolActive ? 'done' : 'current')
  $('#detail-service').textContent = patrolActive ? t('ui.yp0d17') : t('ui.background.start_failed')
  $('#detail-governance').textContent = governanceLabel(platform.governance_mode)
  $('#detail-last-seen').textContent = formatTime(local.sync?.inventory?.last_success_at || platform.last_seen_at)
  $('#detail-token-status').textContent = data.connected ? tf`有效 · ${data.token_hint}` : tf`需检查 · ${data.token_hint}`
  $('#detail-queued-events').textContent = local.queued_events || 0
  $('#detail-local-scan').textContent = formatTime(local.last_inventory_at)
  $('#detail-name').textContent = platform.name || data.name || data.inventory?.hostname || '-'
  $('#detail-client-id').textContent = platform.client_id || data.inventory?.client_id || '-'
  $('#detail-system').textContent = `${platform.os || data.inventory?.os || '-'} · ${platform.arch || data.inventory?.arch || '-'}`
  $('#detail-version').textContent = platform.client_version || data.inventory?.client_version || '-'
  $('#detail-server').textContent = data.server
  const capabilities = platform.detection_capabilities || {}
  renderCapability('#capability-rules', capabilities.rules)
  renderCapability('#capability-deep-scan', capabilities.deep_scan)
  renderCapability('#capability-sandbox', capabilities.sandbox)
  renderCapability('#capability-llm', capabilities.llm)
  renderStatus(data)
  renderModelSwitcher(data)

  $('#todo-section').hidden = false
  $('#todo-list').innerHTML = todos.map((todo, index) => `
      <div class="todo-item${todo.error ? ' error' : ''}">
        <img class="overview-todo-icon" src="./assets/icons/${todo.error ? 'circle-alert' : 'search'}.svg" alt="" />
        <div><strong>${escapeHtml(todo.title)}</strong><span>${escapeHtml(todo.detail)}</span></div>
        <button class="${index === 0 ? 'primary' : ''} overview-todo-action" data-todo-index="${index}"><img src="./assets/icons/${todo.view === 'recovery' ? 'archive' : (todo.actionType === 'refresh' ? 'refresh-cw' : 'chevron-right')}.svg" alt="" />${escapeHtml(todo.action)}</button>
      </div>`).join('')
  document.querySelectorAll('[data-todo-index]').forEach(button => {
    button.addEventListener('click', async () => {
      const todo = todos[Number(button.dataset.todoIndex)]
      if (todo.panel) {
        if (todo.view === 'recovery') {
          if (button.disabled) return
          setBusy(button, true)
          try {
            await loadPending()
            await loadQuarantine()
            $('#recovery-status-filter').value = ''
            const candidates = recoveryItems.filter(item => item.status !== 'backed_up' && item.status !== 'restored')
            const target = inventory?.agents?.find(agent => installedAgent(agent) && candidates.some(item => item.agent_type === agent.agent_type))
            if (target) switchAgent(agentKey(target))
          } catch (error) {
            showMessageDialog(t('ui.agentTabs.recovery'), runtimeText(error))
            return
          } finally { setBusy(button, false) }
        }
        showPanel(todo.panel)
        if (todo.view) switchAgentView(todo.view)
        return
      }
      if (todo.actionType === 'refresh') return refreshConnection()
      if (todo.actionType === 'install-service') {
        setBusy(button, true)
        try { log(await run('reconcile-service')); await refreshConnection() } catch (error) { log(error) } finally { setBusy(button, false) }
      }
    })
  })
  syncSettingsControls()
}

const modelAgentKind = value => {
  const normalized = String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
  return { claude: 'claudecode', claudecode: 'claudecode' }[normalized] || normalized
}

const localModelAgents = data => (data?.inventory?.agents || []).filter(agent =>
  ['claude-code', 'codex', 'hermes'].includes(agent.agent_type)
  && agent.capabilities?.model_config_auto_apply,
)

const platformAgentForLocal = (data, agent) => {
  const platformAgents = data?.platform?.agents || []
  return platformAgents.find(item => item.local_agent_id === agent.local_agent_id)
    || platformAgents.find(item => item.agent_type === agent.agent_type)
}

const modelConfigState = agent => agent?.capabilities?.model_config_state || {}

const renderModelSwitcher = data => {
  const agents = localModelAgents(data)
  const permission = data?.platform?.model_configuration || {}
  if (!selectedModelAgentID || !agents.some(agent => agent.local_agent_id === selectedModelAgentID)) {
    selectedModelAgentID = agents[0]?.local_agent_id || ''
  }
  const selected = agents.find(agent => agent.local_agent_id === selectedModelAgentID)
  const models = permission.models || []
  $('#model-permission-note').className = `model-permission-note${permission.can_configure_models ? '' : ' disabled'}`
  $('#model-permission-note').textContent = permission.can_configure_models
    ? tf`当前凭证可配置 ${models.length} 个网关模型；首次切换会自动建立运行身份并创建独立凭证。`
    : t('client.models.issuance_disabled')
  $('#model-agent-tabs').innerHTML = agents.map(agent => `
    <button type="button" role="tab" aria-selected="${agent.local_agent_id === selectedModelAgentID}" class="${agent.local_agent_id === selectedModelAgentID ? 'active' : ''}" data-model-agent="${escapeHtml(agent.local_agent_id)}">
      ${agentLogo(agent)}<span class="model-agent-copy"><strong>${escapeHtml(agentLabel(agent.agent_type))}</strong>
      <span>${escapeHtml(modelConfigState(agent).model || t('client.models.not_configured'))}</span></span>
    </button>`).join('')
  document.querySelectorAll('[data-model-agent]').forEach(button => button.addEventListener('click', () => {
    selectedModelAgentID = button.dataset.modelAgent
    renderModelSwitcher(connection)
  }))
  if (!selected) {
    $('#model-current').innerHTML = tf`<div><strong>未发现支持的 Agent</strong><span>当前仅支持自动配置 Claude Code、Codex 和 Hermes。安装后重新发现即可显示。</span></div>`
    $('#model-catalog').classList.add('empty')
    $('#model-catalog').textContent = t('client.models.no_local_agent')
    $('#model-result-count').textContent = tf`${models.length} 个模型`
    return
  }
  const state = modelConfigState(selected)
  const platformAgent = platformAgentForLocal(data, selected)
  $('#model-current').innerHTML = `
    <div class="model-current-main">
      <span>${escapeHtml(t('client.models.current_config'))}</span>
      <strong>${escapeHtml(state.model || t('client.models.no_model'))}</strong>
      ${state.error ? `<em>${escapeHtml(runtimeText(state.error))}</em>` : ''}
    </div>
    <dl>
      <div><dt>${escapeHtml(t('client.models.gateway_url'))}</dt><dd><code>${escapeHtml(state.gateway_url || '-')}</code></dd></div>
      <div><dt>${escapeHtml(t('client.models.config_file'))}</dt><dd><code>${escapeHtml(state.config_path || '-')}</code></dd></div>
      <div><dt>${escapeHtml(t('client.models.runtime_identity'))}</dt><dd>${escapeHtml(platformAgent?.managed_agent_id ? t('client.models.identity_ready') : t('client.models.identity_auto_create'))}</dd></div>
    </dl>`
  const query = modelSearch.trim().toLowerCase()
  const visible = models.filter(model => !query || [model.name, model.display_name, model.provider_name].some(value => String(value || '').toLowerCase().includes(query)))
  $('#model-result-count').textContent = tf`${visible.length} 个模型`
  $('#model-catalog').classList.toggle('empty', visible.length === 0)
  $('#model-catalog').innerHTML = visible.length ? visible.map(model => {
    const current = state.model === model.name
    return `<div class="model-row${current ? ' current' : ''}">
      <div class="model-row-name"><strong>${escapeHtml(model.display_name || model.name)}</strong><code>${escapeHtml(model.name)}</code></div>
      <span class="model-provider">${escapeHtml(model.provider_name || '-')}</span>
      <span class="model-limits">${model.context_window ? escapeHtml(tf`上下文 ${model.context_window}`) : ''}${model.max_output_tokens ? escapeHtml(tf` · 输出 ${model.max_output_tokens}`) : ''}</span>
      <button type="button" class="${current ? '' : 'primary'}" data-switch-model="${escapeHtml(model.name)}" ${current || modelSwitchBusy || !permission.can_configure_models ? 'disabled' : ''}>${escapeHtml(current ? t('client.models.current') : t('client.models.switch'))}</button>
    </div>`
  }).join('') : t('client.models.no_matches')
  document.querySelectorAll('[data-switch-model]').forEach(button => button.addEventListener('click', () => beginModelSwitch(selected, button.dataset.switchModel, button)))
}

let modelSwitchBusy = false
const executeModelSwitch = async (agent, model, button, managedAgentID = '') => {
  if (modelSwitchBusy) return
  modelSwitchBusy = true
  document.querySelectorAll('[data-switch-model]').forEach(item => { item.disabled = true })
  const args = ['--agent-type', agent.agent_type, '--model', model]
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  setBusy(button, true)
  try {
    log(await run('switch-model', args))
    await refreshConnection()
    showMessageDialog(t('client.models.switch_complete'), tf`${agentLabel(agent.agent_type)} 已切换为 ${model}，页面显示的是重新读取后的实际配置。`)
  } catch (error) {
    showMessageDialog(t('client.models.switch_failed'), runtimeText(error))
    log(error)
  } finally {
    modelSwitchBusy = false
    setBusy(button, false)
    if (connection) renderModelSwitcher(connection)
  }
}

const beginModelSwitch = (agent, model, button) => {
  return executeModelSwitch(agent, model, button)
}

$('#model-search').addEventListener('input', event => {
  modelSearch = event.target.value
  if (connection) renderModelSwitcher(connection)
})

$('#refresh-models').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('inventory')
    await refreshConnection()
  } catch (error) {
    showMessageDialog(t('client.models.refresh_failed'), runtimeText(error))
  } finally {
    setBusy(button, false)
  }
})

const renderStatus = data => {
  const local = data?.local || {}
  const running = Boolean(data?.service_running)
  const findings = local.patrol_findings || []
  const issues = (local.quarantined_skills || 0) + (local.queued_events || 0) + findings.length
  $('#status-service-badge').className = `overview-badge${running ? '' : ' warning'}`
  $('#status-service-badge').textContent = running ? t('ui.yp0d17') : t('ui.ir5jv')
  $('#status-service-title').textContent = t('ui.background.title')
  $('#status-service-description').textContent = running
    ? t('ui.background.description')
    : runtimeText(data.service_detail || t('ui.background.start_failed'))
  $('#install-service').hidden = running
  $('#install-service').textContent = t('ui.background.retry')
  $('#run-once').disabled = !data?.configured
  $('#status-last-scan').textContent = formatTime(local.last_full_scan_at)
  $('#status-next-scan').textContent = running ? formatTime(local.next_full_scan_at) : '-'
  $('#status-managed-count').textContent = local.managed_skills || 0
  $('#status-quarantine-count').textContent = local.quarantined_skills || 0
  $('#status-queued-count').textContent = local.queued_events || 0
  $('#status-attention').className = `status-attention${issues ? ' warning' : ' ok'}`
  $('#status-attention-text').textContent = findings.length
    ? tf`最近巡检发现 ${findings.length} 个异常：${formatList(findings.map(item => item.skill_name))}。`
    : issues
    ? tf`需要处理：${local.quarantined_skills || 0} 个隔离项、${local.queued_events || 0} 条待补报事件。`
    : t('ui.19y0h48')
  renderNotifications(local)
}

const renderNotifications = local => {
  const items = local.notifications || []
  const unread = Number(local.unread_notifications || 0)
  const critical = items.filter(item => item.severity === 'critical').length
  $('#notification-total').textContent = items.length
  $('#notification-unread').textContent = unread
  $('#notification-critical').textContent = critical
  $('#notification-nav-badge').hidden = unread === 0
  $('#notification-nav-badge').textContent = unread > 99 ? '99+' : unread
  const filtered = items.filter(item => {
    if (notificationFilter === 'unread') return !item.read_at
    if (notificationFilter === 'critical') return item.severity === 'critical'
    return true
  })
  const element = $('#notification-list')
  element.classList.toggle('empty', filtered.length === 0)
  element.innerHTML = filtered.length ? filtered.map(item => {
    const action = notificationAction(item.event_type)
    const copy = localizedNotification(item)
    return `
    <button class="notification-item ${escapeHtml(item.severity)}${item.read_at ? '' : ' unread'}" data-notification-id="${item.id}" data-notification-agent="${escapeHtml(item.agent_type || '')}" data-notification-panel="${action.panel}">
      <i aria-hidden="true"></i>
      <div class="notification-content">
        <div><strong>${escapeHtml(copy.title)}</strong><span class="severity-label">${notificationSeverity(item.severity)}</span>${item.read_at ? '' : `<span>${t('ui.1grkwxe')}</span>`}</div>
        <p>${escapeHtml(copy.message)}</p>
        <small>${escapeHtml(agentLabel(item.agent_type))} · ${escapeHtml(item.skill_name)} · ${escapeHtml(formatTime(item.created_at))}</small>
      </div>
      <span class="notification-action">${action.label} →</span>
    </button>`
  }).join('') : `<div class="empty">${t('ui.bfts9h')}</div>`
  document.querySelectorAll('[data-notification-id]').forEach(button => button.addEventListener('click', async () => {
    const panel = button.dataset.notificationPanel
    showPanel(panel)
    if (panel === 'discover') {
      const agent = inventory?.agents?.find(item => item.agent_type === button.dataset.notificationAgent && installedAgent(item))
      if (agent) switchAgent(agentKey(agent))
      switchAgentView('local')
    }
    try {
      await run('read-notifications', ['--id', button.dataset.notificationId])
      await refreshLocalNotifications()
    } catch (error) {
      showMessageDialog(t('ui.ydow7a'), String(error))
    }
  }))
  deliverDesktopNotification(items.find(item => !item.delivered_at))
}

const refreshLocalNotifications = async () => {
  const local = JSON.parse(await run('local-status'))
  if (connection) connection.local = local
  renderNotifications(local)
  return local
}

const deliverDesktopNotification = async item => {
  if (!item || notificationDeliveryAttempts.has(item.id)) return
  notificationDeliveryAttempts.add(item.id)
  try {
    const severityRank = { info: 0, warning: 1, critical: 2 }
    const threshold = severityRank[clientSettings.notificationLevel] ?? 0
    const severity = severityRank[item.severity] ?? 0
    if (!clientSettings.systemNotifications || severity < threshold) {
      await run('deliver-notification', ['--id', String(item.id)])
      return
    }
    const copy = localizedNotification(item)
    await invoke('show_system_notification', { title: copy.title, body: copy.message })
    await run('deliver-notification', ['--id', String(item.id)])
    $('#system-notification-state').hidden = true
  } catch (error) {
    notificationDeliveryAttempts.delete(item.id)
    $('#system-notification-state').classList.remove('success')
    $('#system-notification-state').hidden = false
    $('#system-notification-state').textContent = runtimeText(error)
  }
}

const notificationSeverity = severity => t(
  ({ critical: t('ui.s9cfpz'), warning: t('ui.1uwa1ih'), info: t('ui.1ltzzrr') }[severity] || t('ui.1hx7jj')),
)
const notificationAction = eventType => ({
  skill_governance_detected: { panel: 'discover', label: t('ui.agentManagement.title') },
  skill_governance_action: { panel: 'discover', label: t('ui.agentManagement.title') },
  skill_quarantined: { panel: 'discover', label: t('ui.fdodj6') },
  unmanaged_skill_found: { panel: 'discover', label: t('ui.hrqy3h') },
  skill_modified: { panel: 'discover', label: t('ui.g9imto') },
  skill_repaired: { panel: 'records', label: t('ui.13q7xte') },
  skill_auto_installed: { panel: 'records', label: t('ui.13q7xte') },
  skill_auto_install_failed: { panel: 'discover', label: t('ui.hrqy3h') },
  connection_changed_governance_paused: { panel: 'connect', label: t('ui.ox3r68') },
  connection_changed_state_reset: { panel: 'connect', label: t('ui.ox3r68') },
}[eventType] || { panel: 'records', label: t('ui.ox3r68') })

const recordState = { kind: 'events', page: 1, pageSize: 10, total: 0, sequence: 0 }
let recordSearchTimer
const recordOptions = (id, values, label) => {
  const control = $(id), selected = control.value
  control.innerHTML = `<option value="">${escapeHtml(t('ui.records.all'))}</option>` + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(label(value))}</option>`).join('')
  control.value = values.includes(selected) ? selected : ''
}
const loadRecordHistory = async () => {
  recordOptions('#records-status', ['pending', 'running', 'succeeded', 'failed', 'cancelled'], taskStatusLabel)
  const sequence = ++recordState.sequence
  const filters = { kind: recordState.kind, page: String(recordState.page), page_size: String(recordState.pageSize),
    keyword: $('#records-keyword').value, agent: $('#records-agent').value, record_type: $('#records-type').value,
    status: recordState.kind === 'tasks' ? $('#records-status').value : '', days: $('#records-days').value }
  $('#records-feedback').textContent = t('ui.records.loading')
  $('#records-prev').disabled = $('#records-next').disabled = true
  $('#records').setAttribute('aria-busy', 'true')
  $('#event-history-list').innerHTML = $('#task-history-list').innerHTML = ''
  try {
    const result = await invoke('get_client_history', { filters })
    if (sequence !== recordState.sequence) return
    recordState.page = result.page
    recordState.total = result.total
    recordOptions('#records-agent', result.agents, agentLabel)
    recordOptions('#records-type', result.types, value => recordState.kind === 'events' ? eventTypeLabel(value) : taskTypeLabel({ task_type: value, payload: {} }))
    const rows = result.items
    if (recordState.kind === 'events') renderEventHistory(rows)
    else renderTaskHistory(rows)
    $('#records-feedback').textContent = ''
    $('#records-total').textContent = `${t('ui.records.total')}: ${result.total}`
    const pages = Math.max(1, Math.ceil(result.total / recordState.pageSize))
    $('#records-page').textContent = `${result.page} / ${pages}`
    $('#records-prev').disabled = result.page <= 1
    $('#records-next').disabled = result.page >= pages
  } catch (error) {
    if (sequence !== recordState.sequence) return
    $('#records-feedback').textContent = t('ui.records.load_error')
    $('#records-total').textContent = $('#records-page').textContent = ''
  } finally {
    if (sequence === recordState.sequence) $('#records').setAttribute('aria-busy', 'false')
  }
}
const filterRecords = () => { recordState.page = 1; void loadRecordHistory() }
recordOptions('#records-agent', [], agentLabel)
recordOptions('#records-type', [], value => eventTypeLabel(value))
$('#records-keyword').addEventListener('input', () => { clearTimeout(recordSearchTimer); recordState.sequence++; recordSearchTimer = setTimeout(filterRecords, 300) })
for (const id of ['records-agent', 'records-type', 'records-status', 'records-days']) $(`#${id}`).addEventListener('change', filterRecords)
$('#records-page-size').addEventListener('change', event => { recordState.pageSize = Number(event.target.value); filterRecords() })
$('#records-prev').addEventListener('click', () => { recordState.page--; void loadRecordHistory() })
$('#records-next').addEventListener('click', () => { recordState.page++; void loadRecordHistory() })
$('#records-reset').addEventListener('click', () => {
  clearTimeout(recordSearchTimer)
  for (const id of ['records-keyword', 'records-agent', 'records-type', 'records-status']) $(`#${id}`).value = ''
  $('#records-days').value = '0'
  filterRecords()
})
document.querySelectorAll('[data-record-kind]').forEach(button => button.addEventListener('click', () => {
  recordState.kind = button.dataset.recordKind
  document.querySelectorAll('[data-record-kind]').forEach(tab => tab.setAttribute('aria-selected', String(tab === button)))
  $('#event-records').hidden = recordState.kind !== 'events'
  $('#task-records').hidden = recordState.kind !== 'tasks'
  $('#records-status-filter').hidden = recordState.kind !== 'tasks'
  $('#records-type').value = ''
  filterRecords()
}))

const localizedNotification = item => {
  if (['skill_governance_detected', 'skill_governance_action'].includes(item.event_type)) {
    const details = item.details || {}
    return {
      title: t(item.event_type === 'skill_governance_detected' ? 'ui.agentManagement.notification_detected' : 'ui.agentManagement.notification_action'),
      message: [agentLabel(item.agent_type), item.skill_name,
        details.trigger && governanceLabelFor('trigger', details.trigger),
        details.action && governanceLabelFor('action', details.action),
        details.status && governanceLabelFor('actionStatus', details.status),
        details.error_code && runtimeText(details.error_code), details.path,
      ].filter(Boolean).join(' · '),
    }
  }
  if (item.event_type === 'connection_changed_state_reset') return {
    title: t('ui.agentManagement.connection_reset_title'), message: t('ui.agentManagement.connection_reset_description'),
  }
  const english = window.clientI18n?.getLocale?.() === 'en-US'
  const agent = agentLabel(item.agent_type)
  const target = english
    ? `${agent} Skill ${item.skill_name}`
    : tf`${agent} 的 Skill ${item.skill_name}`
  const copies = {
    skill_repaired: {
      zh: [t('ui.f8b7hj'), tf`${target} 发生内容变化，已恢复为平台批准版本。`],
      en: ['Skill Automatically Restored', `${target} changed and was restored to the platform-approved version.`],
    },
    skill_quarantined: {
      zh: [t('ui.n2ip1x'), tf`${target} 未通过完整性或准入校验，已移出 Agent 目录。`],
      en: ['Skill Quarantined', `${target} failed integrity or admission checks and was removed from the Agent directory.`],
    },
    skill_modified: {
      zh: [t('ui.18hkev'), tf`${target} 与平台批准版本不一致，请查看运行状态。`],
      en: ['Skill Content Changed', `${target} differs from the platform-approved version. Review Agent Management.`],
    },
    unmanaged_skill_found: {
      zh: [t('ui.gawr4f'), tf`${target} 尚未纳入平台治理。`],
      en: ['Unmanaged Skill Found', `${target} is not yet governed by the platform.`],
    },
    skill_auto_installed: {
      zh: [t('ui.cfjni5'), tf`${target} 已通过平台审批并自动安装可信版本。`],
      en: ['Skill Automatically Enabled', `${target} passed platform approval and the trusted version was installed automatically.`],
    },
    skill_auto_install_failed: {
      zh: [t('ui.1kb5hmk'), tf`${target} 已通过平台审批，但自动安装失败；客户端将稍后重试，也可以在待处理区手动安装。`],
      en: ['Skill Automatic Installation Failed', `${target} passed platform approval, but automatic installation failed. The client will retry later, or you can install it manually from Pending Skills.`],
    },
    connection_changed_governance_paused: {
      zh: ['平台连接已变更', '为避免使用旧平台策略处置本地 Skill，持续治理已自动暂停。请确认新平台配置和治理范围后再恢复。'],
      en: ['Platform Connection Changed', 'Continuous governance was paused to prevent the previous platform policy from changing local Skills. Confirm the new platform configuration and governance scope before resuming.'],
    },
  }
  const copy = copies[item.event_type]
  if (!copy) return { title: runtimeText(item.title), message: runtimeText(item.message) }
  const [title, message] = english ? copy.en : copy.zh
  return { title, message }
}

const renderEventHistory = events => {
  const element = $('#event-history-list')
  element.classList.toggle('empty', !events.length)
  element.innerHTML = events.length ? events.map(event => `<div class="takeover-row task-history-row">
    <div><strong>${escapeHtml(eventTypeLabel(event.event_type))}</strong><p>${escapeHtml(event.skill_name || eventDetail(event.event_type))}</p></div>
    <span>${escapeHtml(event.agent_type ? agentLabel(event.agent_type) : t('ui.13nfgz7'))}</span>
    <strong class="task-status-${event.details?.action === 'record_only' ? 'completed' : event.details?.trigger === 'malicious' || event.details?.status === 'failed' ? 'failed' : event.details?.trigger ? 'warning' : eventStatus(event.event_type)}">${escapeHtml(event.details?.trigger ? governanceLabelFor('trigger', event.details.trigger) : eventResultLabel(event.event_type))}</strong>
    <span>${escapeHtml(formatTime(event.last_seen_at || event.created_at))}${event.observation_count > 1 ? `<small>${escapeHtml(t('ui.agentManagement.observations'))}: ${event.observation_count}</small>` : ''}</span>
  </div>`).join('') : t('ui.records.empty')
}

const renderTaskHistory = tasks => {
  const element = $('#task-history-list')
  element.classList.toggle('empty', !tasks.length)
  element.innerHTML = tasks.length ? tasks.map(task => {
    const payload = task.payload || {}
    const policySync = task.task_type === 'sync_policy' || (task.task_type === 'rescan' && payload.reason === 'policy_changed')
    const target = payload.target_version
      ? t('ui.overview.classified_policy')
      : policySync ? tf`处置：${policyLabel(payload.mode)} · 治理：${governanceLabel(payload.governance_mode)}`
      : payload.skill_name || payload.skill_id || (task.task_type === 'rescan' ? t('ui.1agolmk') : '-')
    return `<div class="takeover-row task-history-row">
      <div><strong>${escapeHtml(taskTypeLabel(task))}</strong><p>${escapeHtml(target)}</p></div>
      <span>${escapeHtml(payload.agent_type ? agentLabel(payload.agent_type) : t('ui.13nfgz7'))}</span>
      <strong class="task-status-${escapeHtml(task.status)}">${escapeHtml(task.task_type === 'sync_policy' && task.error === 'policy_superseded' ? t('ui.policyTask.superseded') : task.task_type === 'sync_policy' && task.status === 'succeeded' ? t('ui.policyTask.applied') : taskStatusLabel(task.status))}</strong>
      <span class="${task.error ? 'task-history-error' : ''}">${escapeHtml(formatTime(task.finished_at || task.started_at || task.updated_at || task.created_at))}${task.error ? `<details class="record-error"><summary>${escapeHtml(t('ui.records.error_details'))}</summary><p>${escapeHtml(['policy_superseded', 'policy_ack_required'].includes(task.error) ? t(`ui.policyTask.${task.error}`) : runtimeText(task.error))}</p></details>` : ''}</span>
    </div>`
  }).join('') : t('ui.records.empty')
}
async function refreshConnection() {
  try {
    connection = await invoke('get_connection_status')
    if (!connection.configured) return renderDisconnected()
    inventory = connection.inventory
    lastInventoryAt = connection.local?.last_inventory_at || lastInventoryAt
    renderConnected(connection)
    renderInventory()
    await loadBuiltinAgentSettings().catch(error => {
      $('#builtin-agent-settings').innerHTML = tf`<div class="inline-error"><strong>读取扫描目录失败</strong><span>${escapeHtml(error)}</span></div>`
    })
    await loadPending().catch(error => log(error))
    checkClientUpdateAutomatically()
  } catch (error) {
    renderDisconnected()
    log(error)
  }
}

const refreshChangedInventory = async () => {
  if (document.hidden || autoRefreshBusy || !connection?.configured) return
  autoRefreshBusy = true
  try {
    const local = JSON.parse(await run('local-status'))
    const changedAt = local.last_inventory_at || ''
    const policyChanged = JSON.stringify(local.classification) !== JSON.stringify(connection.local?.classification)
    const taskChanged = local.tasks?.[0]?.updated_at !== connection.local?.tasks?.[0]?.updated_at
    const notificationChanged = local.notifications?.[0]?.id !== connection.local?.notifications?.[0]?.id || local.unread_notifications !== connection.local?.unread_notifications
    const quarantineChanged = local.quarantined_skills !== connection.local?.quarantined_skills || local.pending_skills !== connection.local?.pending_skills
    const refreshQuarantine = $('#discover').classList.contains('active') || $('#connect').classList.contains('active')
    if ((!changedAt || changedAt === lastInventoryAt) && !policyChanged && !taskChanged && !notificationChanged && !quarantineChanged) return
    if (changedAt === lastInventoryAt) {
      connection.local = local
      if (policyChanged) renderConnected(connection)
      else renderStatus(connection)
      if (refreshQuarantine) await loadPending()
      return
    }
    const refreshManagement = $('#discover').classList.contains('active')
    await refreshConnection()
    if (refreshManagement) await loadPending()
    if (refreshQuarantine) await loadPending()
  } catch (_) {
    // The normal connection refresh remains responsible for surfacing errors.
  } finally {
    autoRefreshBusy = false
  }
}

document.querySelectorAll('[data-notification-filter]').forEach(button => {
  button.addEventListener('click', () => {
    notificationFilter = button.dataset.notificationFilter
    document.querySelectorAll('[data-notification-filter]').forEach(item => item.classList.toggle('active', item === button))
    renderNotifications(connection?.local || {})
  })
})

$('#refresh-notifications').addEventListener('click', refreshConnection)
$('#notification-trigger').addEventListener('click', () => showPanel('notifications'))
$('#test-system-notification').addEventListener('click', async () => {
  if (!clientSettings.systemNotifications) {
    showMessageDialog(t('系统通知已关闭'), t('请在设置中开启系统通知后再测试。'))
    return
  }
  try {
    await invoke('show_system_notification', {
      title: window.clientI18n?.getLocale?.() === 'en-US' ? 'Agent Manager Client' : t('ui.7jdhon'),
      body: t('ui.1rj8d7t'),
    })
    $('#system-notification-state').hidden = false
    $('#system-notification-state').classList.add('success')
    $('#system-notification-state').textContent = t('ui.jswm83')
  } catch (error) {
    $('#system-notification-state').classList.remove('success')
    $('#system-notification-state').hidden = false
    $('#system-notification-state').textContent = runtimeText(error)
  }
})
$('#mark-notifications-read').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('read-notifications')
    const local = await refreshLocalNotifications()
    if (Number(local.unread_notifications || 0) !== 0) throw new Error(t('ui.1hudnlq'))
    $('#system-notification-state').hidden = false
    $('#system-notification-state').classList.add('success')
    $('#system-notification-state').textContent = t('ui.15h7kok')
  } catch (error) {
    showMessageDialog(t('ui.ydow7a'), String(error))
  } finally {
    setBusy(button, false)
  }
})
$('#clear-notifications').addEventListener('click', () => $('#clear-notifications-dialog').showModal())
$('#cancel-clear-notifications').addEventListener('click', () => $('#clear-notifications-dialog').close())
$('#confirm-clear-notifications').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('clear-notifications')
    const local = await refreshLocalNotifications()
    if ((local.notifications || []).length !== 0) throw new Error(t('ui.1mk1djv'))
    $('#clear-notifications-dialog').close()
    $('#system-notification-state').hidden = false
    $('#system-notification-state').classList.add('success')
    $('#system-notification-state').textContent = t('ui.rlm9bx')
    log(t('ui.wff6ih'))
  } catch (error) {
    showMessageDialog(t('ui.1osubs6'), String(error))
  } finally {
    setBusy(button, false)
  }
})

const governanceLabelFor = (kind, value) => {
  const key = `ui.agentManagement.${kind}.${value}`
  const translated = t(key)
  return translated === key ? value || '-' : translated
}

const scanProgressText = item => {
  const progress = item?.progress
  if (item?.status !== 'PENDING' || !progress || progress.version_id !== (item.version_id || item.skill_id)) return ''
  const stage = ['queued', 'preparing', 'analyzers', 'sandbox', 'llm', 'finalizing'].includes(progress.stage) ? progress.stage : 'running'
  const parts = [t(`ui.agentManagement.scanStage.${stage}`)]
  for (const analyzer of ['scanner', 'skillspector', 'sandbox', 'llm']) {
    const state = progress.analyzers?.[analyzer]
    if (['pending', 'running', 'completed', 'failed', 'disabled', 'skipped'].includes(state)) {
      parts.push(`${t(`ui.agentManagement.analyzer.${analyzer}`)}: ${t(`ui.agentManagement.analyzerState.${state}`)}`)
    }
  }
  return parts.join(' · ')
}

const renderSkillObservation = skill => {
  const observation = skill.governance?.signature === skill.signature ? skill.governance : null
  const certification = skill.status === 'broken_link' ? 'missing_files' : skill.status === 'unscannable' ? 'unscannable' : observation?.certification || 'confirmation_pending'
  const pending = observation?.pending_id ? pendingItems.find(item => item.id === observation.pending_id) : null
  const policy = connection?.local?.classification || connection?.platform?.classification
  const trigger = observation?.trigger
  const source = policy?.sources?.[trigger]
  const facts = [
    governanceLabelFor('certification', certification),
    observation?.malicious ? t('ui.agentManagement.trigger.malicious') : '',
  ].filter(Boolean)
  const details = [
    trigger ? governanceLabelFor('trigger', trigger) : '',
    observation?.action ? `${t('ui.agentManagement.policy')}: ${governanceLabelFor('action', observation.action)}` : '',
    source ? governanceLabelFor('source', source) : '',
    observation?.action_status ? governanceLabelFor('actionStatus', observation.action_status) : '',
    pending ? `${t('ui.agentManagement.scan')}: ${scanProgressText(pending) || pendingStatusLabel(pending.status)}` : '',
    pending?.progress?.updated_at ? `${t('ui.agentManagement.scan_updated')}: ${formatTime(pending.progress.updated_at)}` : '',
    observation?.last_seen_at ? `${t('ui.agentManagement.last_seen')}: ${formatTime(observation.last_seen_at)}` : '',
    `${t('ui.agentManagement.inventory_sync')}: ${formatTime(connection?.local?.sync?.inventory?.last_success_at)}`,
    skill.status === 'external_link' ? t('ui.agentManagement.link_outside_scope') : skill.error || observation?.error_code || connection?.local?.sync?.inventory?.error || '',
  ].filter(Boolean)
  return `<div class="skill-observation ${observation?.malicious || skill.error ? 'warning' : ''}"><span data-ui-icon="${observation?.malicious || certification === 'missing_files' ? 'circle-alert' : certification === 'certified' ? 'circle-check' : certification === 'changed' ? 'triangle-alert' : certification === 'unverified' ? 'circle-alert' : 'clock-3'}" class="skill-status ${escapeHtml(certification)} ${observation?.malicious ? 'malicious' : ''}">${escapeHtml(facts.join(' · '))}</span></div><details class="skill-facts"><summary>${escapeHtml(t('ui.agentManagement.details'))}</summary><button class="path-link" type="button" title="${escapeHtml(skill.path)}" data-reveal-path="${escapeHtml(skill.path)}">${escapeHtml(skill.path)}</button>${details.map(detail => `<small>${escapeHtml(detail)}</small>`).join('')}</details>`
}

document.addEventListener('click', event => {
  const trigger = event.target.closest('.skill-more > summary')
  if (trigger) {
    event.preventDefault()
    const selected = trigger.parentElement
    selected.open = !selected.open
    document.querySelectorAll('.skill-more[open]').forEach(menu => { if (menu !== selected) menu.open = false })
    if (selected.open) positionSkillMenu(selected)
    return
  }
  document.querySelectorAll('.skill-more[open]').forEach(menu => {
    if (!menu.contains(event.target) || event.target.closest('button')) menu.open = false
  })
})
const positionSkillMenu = menu => {
  const popup = menu.querySelector('.skill-more-menu')
  const anchor = menu.querySelector('summary').getBoundingClientRect()
  const margin = 12
  popup.style.position = 'fixed'
  popup.style.right = 'auto'
  popup.style.maxHeight = `${window.innerHeight - margin * 2}px`
  const box = popup.getBoundingClientRect()
  popup.style.left = `${Math.max(margin, Math.min(anchor.right - box.width, window.innerWidth - box.width - margin))}px`
  const top = anchor.bottom + 6 + box.height > window.innerHeight - margin ? anchor.top - box.height - 6 : anchor.bottom + 6
  popup.style.top = `${Math.max(margin, top)}px`
}
document.addEventListener('toggle', event => {
  const menu = event.target
  if (!menu.matches?.('.skill-more') || !menu.open) return
  document.querySelectorAll('.skill-more[open]').forEach(other => { if (other !== menu) other.open = false })
  positionSkillMenu(menu)
}, true)
const closeSkillMenus = () => document.querySelectorAll('.skill-more[open]').forEach(menu => { menu.open = false })
window.addEventListener('resize', closeSkillMenus)
document.addEventListener('scroll', event => {
  if (!event.target.closest?.('.skill-more-menu')) closeSkillMenus()
}, true)
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return
  const menu = event.target.closest?.('.skill-more[open]')
  if (menu) { menu.open = false; menu.querySelector('summary').focus() }
})

const installedAgent = agent => Boolean(agent.install_path || isCustomAgent(agent) || isSharedSkills(agent))
let selectedAgentID = localStorage.getItem('agent-manager-selected-agent') || ''
let agentSkillPage = 1
let recoveryItems = []
let scanHistoryItems = []
const agentKey = agent => agent.local_agent_id || agent.agent_type
const selectedAgent = () => inventory?.agents?.find(agent => agentKey(agent) === selectedAgentID && installedAgent(agent))
const scopeIncludes = item => Boolean(selectedAgent()) && item.agent_type === selectedAgent().agent_type
const scopedPendingItems = () => pendingItems.filter(item => recoveryItems.some(copy => copy.pending_copy_id === item.id && recoveryVisible(copy)))
const skillCertification = skill => {
  const value = skill.governance?.signature === skill.signature ? skill.governance : null
  if (value?.malicious) return 'malicious'
  return value?.certification === 'certified' ? 'trusted' : value?.certification === 'changed' ? 'changed' : value?.certification === 'unverified' ? 'unverified' : 'confirmation_pending'
}
const filteredAgentSkills = agent => (agent?.skills || []).filter(skill => {
  const query = $('#agent-skill-search').value.trim().toLowerCase()
  const status = $('#agent-skill-status').value
  return (!query || skill.name.toLowerCase().includes(query)) && (!status || skillCertification(skill) === status)
})
const switchAgent = id => {
  selectedAgentID = id
  localStorage.setItem('agent-manager-selected-agent', id)
  agentSkillPage = 1
  selectedPendingIDs.clear()
  renderInventory()
}
const syncAgentHistory = () => {
  const agent = selectedAgent()
  $('#agent-pending-count').textContent = scanHistoryItems.filter(item => item.agent_type === agent?.agent_type).length
  $('#agent-recovery-count').textContent = recoveryItems.filter(item => item.agent_type === agent?.agent_type).length
  document.querySelectorAll('[data-pending-agent]').forEach(group => {
    group.hidden = !scopeIncludes({agent_type: group.dataset.pendingAgent})
    group.querySelectorAll('[data-select-pending]').forEach(input => {
      if (group.hidden) selectedPendingIDs.delete(input.dataset.selectPending)
      input.checked = selectedPendingIDs.has(input.dataset.selectPending)
    })
  })
  document.querySelectorAll('[data-recovery-agent]').forEach(row => { row.hidden = !recoveryItems.some(item => item.id === row.dataset.recoveryId && recoveryVisible(item)) })
  document.querySelectorAll('[data-select-pending]').forEach(input => { input.checked = selectedPendingIDs.has(input.dataset.selectPending) })
  const hasPending = scanHistoryItems.some(scopeIncludes)
  $('#pending-list').hidden = !hasPending
  $('#agent-pending-empty').hidden = hasPending
  const hasRecovery = recoveryItems.some(recoveryVisible)
  $('#quarantine-list').hidden = !hasRecovery
  $('#agent-recovery-empty').hidden = hasRecovery
  $('#agent-recovery-empty').textContent = t('ui.recovery.filter_empty')
  syncPendingBatchControls()
}
const agentLogoFile = agent => ({
  'claude-code': 'claude-color', codex: 'openai', gemini: 'gemini-color', opencode: 'opencode',
  hermes: 'hermesagent', openclaw: 'openclaw-color', 'trae-cn': 'trae', trae: 'trae', cursor: 'cursor',
  codebuddy: 'codebuddy-color', workbuddy: 'workbuddy', 'global-skills': 'users',
}[agent.agent_type] || 'bot')
const agentLogo = (agent, large = false) => `<img class="agent-logo${large ? ' large' : ''}" src="./assets/icons/${agentLogoFile(agent)}.${agentLogoFile(agent) === 'workbuddy' ? 'png' : 'svg'}" alt="" aria-hidden="true" draggable="false" />`
const agentScrollBehavior = () => matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
const syncAgentScroll = () => {
  const strip = $('#agent-tabs')
  const overflow = strip.scrollWidth > strip.clientWidth + 2
  $('#agent-scroll-left').hidden = $('#agent-scroll-right').hidden = !overflow
  $('#agent-scroll-left').disabled = strip.scrollLeft <= 1
  $('#agent-scroll-right').disabled = strip.scrollLeft >= strip.scrollWidth - strip.clientWidth - 1
}
const revealSelectedAgent = () => {
  const strip = $('#agent-tabs')
  const button = strip.querySelector('[aria-selected=true]')
  if (!button || !strip.clientWidth) return
  const bounds = strip.getBoundingClientRect()
  const target = button.getBoundingClientRect()
  const delta = target.left < bounds.left ? target.left - bounds.left : target.right > bounds.right ? target.right - bounds.right : 0
  if (delta) strip.scrollBy({left: delta, behavior: agentScrollBehavior()})
}
let renderedAgentSelection = ''
let renderedAgentMarkup = ''
const renderAgentNavigation = agents => {
  if (!agents.some(agent => agentKey(agent) === selectedAgentID)) selectedAgentID = agentKey(agents.find(agent => !isSharedSkills(agent)) || agents[0] || {}) || ''
  const selected = selectedAgent()
  const ordered = [...agents.filter(agent => !isSharedSkills(agent)), ...agents.filter(isSharedSkills)]
  const strip = $('#agent-tabs')
  const markup = ordered.map(agent => `<button type="button" role="tab" aria-selected="${agentKey(agent) === selectedAgentID}" tabindex="${agentKey(agent) === selectedAgentID ? 0 : -1}" data-agent-tab="${escapeHtml(agentKey(agent))}" class="${isSharedSkills(agent) ? 'shared-agent-tab' : ''}">${agentLogo(agent)}<span>${escapeHtml(agentLabel(agent.agent_type))}</span><small>${agent.skills?.length || 0}</small></button>`).join('')
  if (renderedAgentMarkup !== markup) {
    renderedAgentMarkup = markup
    const scroll = strip.scrollLeft
    strip.innerHTML = markup
    strip.scrollLeft = scroll
  }
  $('#agent-context').innerHTML = selected ? `${agentLogo(selected)}<div class="agent-context-copy" title="${escapeHtml(selected.skills_path || '')}"><strong>${escapeHtml(agentLabel(selected.agent_type))}</strong></div>${selected.skills_path && selected.capabilities?.path_available !== false && selected.capabilities?.skills_directory_exists !== false ? `<button type="button" class="agent-folder-button" data-ui-icon="folder-open" data-reveal-path="${escapeHtml(selected.skills_path)}" aria-label="${escapeHtml(t('ui.agentTabs.directory'))}" title="${escapeHtml(t('ui.agentTabs.directory'))}: ${escapeHtml(selected.skills_path)}"></button>` : ''}` : `<p>${escapeHtml(t('ui.agentTabs.no_agents'))}</p>`
  $('#agent-local-count').textContent = selected?.skills?.length || 0
  const changed = renderedAgentSelection !== selectedAgentID
  renderedAgentSelection = selectedAgentID
  requestAnimationFrame(() => { syncAgentScroll(); if (changed) revealSelectedAgent() })
  syncAgentHistory()
}
let agentDrag = null
let suppressAgentClickUntil = 0
$('#agent-tabs').addEventListener('click', event => {
  if (performance.now() < suppressAgentClickUntil) { event.preventDefault(); return }
  const button = event.target.closest('[data-agent-tab]')
  if (button) switchAgent(button.dataset.agentTab)
})
$('#agent-tabs').addEventListener('wheel', event => {
  if (event.ctrlKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
  const strip = event.currentTarget
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? strip.clientWidth : 1)
  const next = Math.max(0, Math.min(strip.scrollWidth - strip.clientWidth, strip.scrollLeft + delta))
  if (Math.abs(next - strip.scrollLeft) > 0.5) { event.preventDefault(); strip.scrollLeft = next }
}, {passive: false})
$('#agent-tabs').addEventListener('pointerdown', event => {
  if (event.pointerType !== 'mouse' || event.button !== 0) return
  agentDrag = {id: event.pointerId, x: event.clientX, scroll: event.currentTarget.scrollLeft, moved: false}
})
$('#agent-tabs').addEventListener('pointermove', event => {
  if (!agentDrag || agentDrag.id !== event.pointerId) return
  const delta = event.clientX - agentDrag.x
  if (!agentDrag.moved && Math.abs(delta) < 6) return
  agentDrag.moved = true
  event.currentTarget.setPointerCapture(event.pointerId)
  event.currentTarget.classList.add('dragging')
  event.currentTarget.scrollLeft = agentDrag.scroll - delta
  event.preventDefault()
})
const finishAgentDrag = event => {
  if (!agentDrag || agentDrag.id !== event.pointerId) return
  if (agentDrag.moved) suppressAgentClickUntil = performance.now() + 250
  agentDrag = null
  $('#agent-tabs').classList.remove('dragging')
  if ($('#agent-tabs').hasPointerCapture(event.pointerId)) $('#agent-tabs').releasePointerCapture(event.pointerId)
}
window.addEventListener('pointerup', finishAgentDrag)
window.addEventListener('pointercancel', finishAgentDrag)
$('#agent-tabs').addEventListener('scroll', syncAgentScroll, {passive: true})
for (const direction of ['left', 'right']) $(`#agent-scroll-${direction}`).addEventListener('click', () => {
  $('#agent-tabs').scrollBy({left: (direction === 'left' ? -1 : 1) * $('#agent-tabs').clientWidth * 0.7, behavior: agentScrollBehavior()})
})
new ResizeObserver(syncAgentScroll).observe($('#agent-tabs'))
$('#agent-tabs').addEventListener('keydown', event => {
  const buttons = [...$('#agent-tabs').querySelectorAll('[role=tab]')]
  const index = buttons.indexOf(document.activeElement)
  if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
  const id = buttons[next].dataset.agentTab
  switchAgent(id)
  Array.from($('#agent-tabs').querySelectorAll('button')).find(button => button.dataset.agentTab === id)?.focus()
})
const switchAgentView = view => {
  for (const kind of ['local', 'pending', 'recovery']) $(`#agent-${kind}-panel`).hidden = kind !== view
  document.querySelectorAll('[data-agent-view]').forEach(button => {
    button.setAttribute('aria-selected', String(button.dataset.agentView === view))
    button.tabIndex = button.dataset.agentView === view ? 0 : -1
  })
  syncAgentHistory()
}
document.querySelectorAll('[data-agent-view]').forEach(button => button.addEventListener('click', () => switchAgentView(button.dataset.agentView)))
$('.agent-content-tabs').addEventListener('keydown', event => {
  const buttons = Array.from(document.querySelectorAll('[data-agent-view]'))
  const index = buttons.indexOf(document.activeElement)
  if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
  switchAgentView(buttons[next].dataset.agentView)
  buttons[next].focus()
})
for (const id of ['#agent-skill-search', '#agent-skill-status', '#agent-skill-page-size']) $(id).addEventListener(id.includes('search') ? 'input' : 'change', () => { agentSkillPage = 1; renderInventory() })
$('#agent-skill-prev').addEventListener('click', () => { agentSkillPage--; renderInventory() })
$('#agent-skill-next').addEventListener('click', () => { agentSkillPage++; renderInventory() })


const confirmCertifiedRescan = () => new Promise(resolve => {
  const dialog = $('#rescan-confirm-dialog')
  if (dialog.open) return resolve(false)
  dialog.returnValue = ''
  dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true })
  dialog.showModal()
})

const renderInventory = () => {
  if (!inventory?.agents) return
  const visibleAgents = inventory.agents.filter(installedAgent)
  renderAgentNavigation(visibleAgents)
  const currentAgent = selectedAgent()
  const filteredSkills = filteredAgentSkills(currentAgent)
  const pageSize = Number($('#agent-skill-page-size').value)
  const pages = Math.max(1, Math.ceil(filteredSkills.length / pageSize))
  agentSkillPage = Math.max(1, Math.min(agentSkillPage, pages))
  const pageSkills = filteredSkills.slice((agentSkillPage - 1) * pageSize, agentSkillPage * pageSize)
  $('#agent-skill-empty').hidden = filteredSkills.length > 0
  $('#agent-skill-total').textContent = skillCount(filteredSkills.length)
  $('#agent-skill-page').textContent = `${agentSkillPage} / ${pages}`
  $('#agent-skill-prev').disabled = agentSkillPage <= 1
  $('#agent-skill-next').disabled = agentSkillPage >= pages
  const bindings = Object.fromEntries((connection?.platform?.agents || []).map(agent => [agent.agent_type, agent.managed_agent_id || '']))
  const strict = connection?.platform?.governance_mode === 'strict'
  const availableAgents = connection?.platform?.available_managed_agents || []
  $('#agent-list').classList.remove('empty')
  $('#agent-list').innerHTML = currentAgent
    ? [currentAgent].map(agent => {
      const binding = bindings[agent.agent_type] || ''
      const shared = isSharedSkills(agent)
      const readers = agent.capabilities?.shared_skill_readers || []
      const requiresBinding = agent.skill_management_supported && strict && !shared
      return `
        <article class="agent-card${shared ? ' shared-skills-card' : ''}" data-agent-card="${escapeHtml(agentKey(agent))}">
          ${shared ? tf`<div class="shared-skills-note"><strong>这是共用目录，不计入 Agent 数量</strong><span>${escapeHtml(formatList(readers) || t('ui.waagmd'))} 可能读取其中的 Skill，实际以各 Agent 的版本和配置为准；共用目录仅执行状态与内容完整性治理，无法据此识别具体调用方。</span></div>` : ''}
          ${requiresBinding || isCustomAgent(agent)
            ? `<div class="agent-settings">${requiresBinding ? `<span>${escapeHtml(t('ui.agentManagement.binding'))}: ${escapeHtml(availableAgents.find(item => item.agent_id === binding)?.name || binding || t('ui.agentManagement.binding_required'))}</span>` : ''}${isCustomAgent(agent) ? tf`<button class="custom-agent-remove icon-button icon-remove" type="button" title="只取消本地登记，不删除 Skill 文件" data-remove-custom-agent="${escapeHtml(agent.agent_type)}" data-custom-agent-name="${escapeHtml(agent.display_name)}">取消登记</button>` : ''}</div>`
            : ''}
          ${agent.skill_management_supported ? `<div class="skill-inventory">${pageSkills.length ? pageSkills.map(skill => tf`
            <div class="skill-row">
              <div class="skill-row-main">
                <span>
                  <button class="skill-name-button" type="button" data-ui-icon="file-text" data-toggle-skill-details aria-expanded="false"><strong>${escapeHtml(skill.name)}</strong></button>
                  ${renderSkillObservation(skill)}
                </span>
              </div>
              <div class="skill-row-actions">
                ${skill.status === 'broken_link' ? `<button class="skill-scan-button" data-ui-icon="download" type="button" data-reinstall-missing="${escapeHtml(agent.agent_type)}" data-skill-name="${escapeHtml(skill.name)}" data-skill-id="${escapeHtml(skill.skill_id || '')}" ${!connection?.connected ? 'disabled' : ''}>${escapeHtml(t('ui.agentManagement.reinstall_missing'))}</button>` : `                <button class="skill-scan-button" data-ui-icon="shield-check" type="button" data-submit-observed="${escapeHtml(skill.path)}" data-agent-type="${escapeHtml(agent.agent_type)}" data-signature="${escapeHtml(skill.signature || '')}" ${skill.error || !skill.signature || !connection?.connected || submittingObservedPaths.has(skill.path) ? 'disabled' : ''}>${escapeHtml(t(submittingObservedPaths.has(skill.path) ? 'ui.agentManagement.submitting' : 'ui.agentManagement.action.submit_scan'))}</button>
                <details class="skill-more"><summary data-ui-icon="ellipsis" aria-label="${escapeHtml(t('ui.agentManagement.more'))}" title="${escapeHtml(t('ui.agentManagement.more'))}"></summary><div class="skill-more-menu">${renderSkillActions(agent, skill)}${skill.skill_id && !skill.error ? tf`<button type="button" data-ui-icon="download" data-install-other="${escapeHtml(skill.skill_id)}" data-skill-name="${escapeHtml(skill.name)}" data-source-agent="${escapeHtml(agent.agent_type)}">安装到其他 Agent</button>` : ''}</div></details>`}

              </div>
            </div>`).join('') : ''}</div>` : ''}
        </article>`
    }).join('')
    : t('ui.1o0lsp0')
  document.querySelectorAll('[data-toggle-skill-details]').forEach(button => button.addEventListener('click', () => {
    const details = button.closest('.skill-row').querySelector('.skill-facts')
    details.open = !details.open
    button.setAttribute('aria-expanded', String(details.open))
  }))
  document.querySelectorAll('[data-reinstall-missing]').forEach(button => button.addEventListener('click', () => openInstallDialog(null, button.dataset.skillName, button.dataset.reinstallMissing, { name: button.dataset.skillName, skill_id: button.dataset.skillId })))
  document.querySelectorAll('[data-install-other]').forEach(button => button.addEventListener('click', () => {
    button.closest('details').open = false
    openInstallDialog({ skill_id: button.dataset.installOther, name: button.dataset.skillName, source_agent_type: button.dataset.sourceAgent })
  }))
  document.querySelectorAll('.skill-more').forEach(menu => {
    menu.addEventListener('toggle', () => {
      if (menu.open) document.querySelectorAll('.skill-more[open]').forEach(other => { if (other !== menu) other.open = false })
    })
    menu.addEventListener('keydown', event => { if (event.key === 'Escape') { menu.open = false; menu.querySelector('summary').focus() } })
  })
  document.querySelectorAll('[data-skill-action]').forEach(select => select.addEventListener('click', () => {
    if (select.disabled || requestingSkillAction) return
    const agent = inventory.agents.find(item => item.agent_type === select.dataset.agentType)
    const skill = agent?.skills.find(item => item.path === select.dataset.skillAction)
    if (!skill) return
    pendingSkillAction = { requestID: crypto.randomUUID(), action: select.dataset.action, agentType: agent.agent_type,
      path: skill.path, signature: skill.signature, versionID: skill.governance?.trusted_version_id || '' }
    select.closest('details').open = false
    $('#skill-action-title').textContent = governanceLabelFor('action', pendingSkillAction.action)
    $('#skill-action-description').textContent = t('ui.agentManagement.action_confirm')
    $('#skill-action-path').textContent = skill.path
    const readers = skillSharedReaders(agent, skill.path)
    $('#skill-action-impact').textContent = readers.length
      ? `${t('ui.agentManagement.shared_impact')}: ${formatList(readers)}`
      : `${t('ui.agentManagement.binding')}: ${agentLabel(agent.agent_type)}`
    $('#skill-action-dialog').dataset.action = pendingSkillAction.action
    $('#skill-action-dialog').showModal()
  }))
  document.querySelectorAll('[data-submit-observed]').forEach(button => button.addEventListener('click', async () => {
    const path = button.dataset.submitObserved
    if (submittingObservedPaths.has(path)) return
    const skill = inventory?.agents?.find(agent => agent.agent_type === button.dataset.agentType)?.skills?.find(item => item.path === path)
    submittingObservedPaths.add(path)
    try {
      if (skill?.signature && skill.signature === button.dataset.signature && skill.governance?.signature === skill.signature && skill.governance?.certification === 'certified') {
        if (!await confirmCertifiedRescan()) return
      }
      setBusy(button, true)
      await run('submit-observed', ['--agent-type', button.dataset.agentType, '--skill', path, '--expected-signature', button.dataset.signature])
      await discover()
      await loadPending(true)
      showMessageDialog(t('ui.agentManagement.submitted'), t('ui.agentManagement.snapshot_description'))
    } catch (error) {
      showMessageDialog(t('ui.agentManagement.submit_failed'), runtimeText(error))
    } finally {
      submittingObservedPaths.delete(path)
      renderInventory()
    }
  }))
  document.querySelectorAll('[data-remove-custom-agent]').forEach(button => button.addEventListener('click', async () => {
    customAgentPendingRemoval = {
      agentType: button.dataset.removeCustomAgent,
      name: button.dataset.customAgentName,
    }
    $('#remove-custom-agent-name').textContent = customAgentPendingRemoval.name
    $('#remove-custom-agent-dialog').showModal()
  }))
}

const renderSkillActions = (agent, skill) => {
  const allowed = Boolean(connection?.platform?.manual_skill_actions_allowed)
  const pending = (connection?.platform?.tasks || []).some(task => task.task_type === 'skill_action' && task.payload?.path === skill.path && ['pending', 'running'].includes(task.status))
  const disabled = !allowed || !connection?.connected || Boolean(skill.error) || !skill.signature || pending
  const title = !allowed ? t('ui.agentManagement.action_permission_required') : pending ? t('ui.agentManagement.action_pending') : ''
  const certified = Boolean(skill.signature) && skill.governance?.signature === skill.signature && skill.governance?.certification === 'certified'
  const actions = [...(certified ? [] : ['quarantine']), 'uninstall', ...(skill.governance?.trusted_version_id ? ['restore_trusted'] : [])]
  return `${title ? `<small class="skill-menu-hint">${escapeHtml(title)}</small>` : ''}${actions.map(action => `<button type="button" data-ui-icon="${({quarantine: 'archive', uninstall: 'trash-2', restore_trusted: 'rotate-ccw'})[action]}" data-skill-action="${escapeHtml(skill.path)}" data-agent-type="${escapeHtml(agent.agent_type)}" data-action="${action}" ${disabled ? 'disabled' : ''}>${escapeHtml(t(`ui.agentManagement.action.${action}`))}</button>`).join('')}`
}

$('#confirm-skill-action').addEventListener('click', async event => {
  if (!pendingSkillAction || requestingSkillAction) return
  requestingSkillAction = true
  const button = event.currentTarget
  const action = pendingSkillAction
  setBusy(button, true)
  try {
    const args = ['--action', action.action, '--request-id', action.requestID, '--agent-type', action.agentType,
      '--skill', action.path, '--expected-signature', action.signature]
    if (action.action === 'restore_trusted' && action.versionID) args.push('--version-id', action.versionID)
    if (['restore_quarantine', 'restore_backup'].includes(action.action)) args.push('--id', action.quarantineID)
    if (action.action === 'restore_backup' && action.targetSignature) args.push('--expected-target-signature', action.targetSignature)
    const task = JSON.parse(await run('request-skill-action', args))
    $('#skill-action-dialog').close()
    await refreshConnection()
    showMessageDialog(t('ui.agentManagement.action_queued'), `${t('ui.agentManagement.task_id')}: ${task.id}`)
  } catch (error) {
    $('#skill-action-dialog').close()
    showMessageDialog(t('ui.agentManagement.action_failed'), connectionErrorText(error))
  } finally {
    requestingSkillAction = false
    setBusy(button, false)
  }
})

$('#cancel-remove-custom-agent').addEventListener('click', () => {
  customAgentPendingRemoval = null
  $('#remove-custom-agent-dialog').close()
})

$('#cancel-agent-paths').addEventListener('click', () => {
  editingBuiltinAgent = null
  $('#agent-paths-dialog').close()
})

$('#select-agent-path').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const path = await invoke('select_skill_directory')
    if (path) {
      const input = $('#agent-paths-input')
      input.value = path
      input.setCustomValidity('')
      input.focus()
    }
  } catch (error) {
    $('#agent-paths-dialog').close()
    showMessageDialog(t('ui.xcqz4c'), String(error))
  } finally {
    setBusy(button, false)
  }
})

$('#save-agent-paths').addEventListener('click', async event => {
  if (!editingBuiltinAgent) return
  const input = $('#agent-paths-input')
  const roots = input.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean)
  input.setCustomValidity(roots.length ? '' : t('ui.1znl4f'))
  if (!input.reportValidity()) return
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const args = ['--agent-type', editingBuiltinAgent.agent_type]
    roots.forEach(root => args.push('--skill-root', root))
    await run('set-agent-roots', args)
    editingBuiltinAgent = null
    $('#agent-paths-dialog').close()
    await loadBuiltinAgentSettings(true)
    await discover()
    showMessageDialog(t('ui.a9933o'), t('ui.14mjvkv'))
  } catch (error) {
    showMessageDialog(t('ui.kwr7cx'), String(error))
  } finally {
    setBusy(button, false)
  }
})

$('#reset-agent-paths').addEventListener('click', async event => {
  if (!editingBuiltinAgent) return
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('reset-agent-roots', ['--agent-type', editingBuiltinAgent.agent_type])
    editingBuiltinAgent = null
    $('#agent-paths-dialog').close()
    await loadBuiltinAgentSettings(true)
    await discover()
    showMessageDialog(t('ui.h1u4jd'), t('ui.1eqvozo'))
  } catch (error) {
    showMessageDialog(t('ui.1viosk7'), String(error))
  } finally {
    setBusy(button, false)
  }
})

$('#confirm-remove-custom-agent').addEventListener('click', async event => {
  if (!customAgentPendingRemoval) return
  const button = event.currentTarget
  const item = customAgentPendingRemoval
  setBusy(button, true)
  try {
    await run('remove-custom-agent', ['--agent-type', item.agentType])
    customAgentPendingRemoval = null
    $('#remove-custom-agent-dialog').close()
    await discover()
    showMessageDialog(t('ui.1y3ykai'), tf`已取消“${item.name}”的本地登记，原 Skill 目录和文件没有被删除。`)
  } catch (error) {
    showMessageDialog(t('ui.1ykwh3e'), String(error))
  } finally {
    setBusy(button, false)
  }
})

const discover = async () => {
  const output = await run('inventory')
  inventory = JSON.parse(output)
  renderInventory()
  const agents = inventory.agents.filter(agent => !isSharedSkills(agent))
  const supported = agents.filter(agent => agent.skill_management_supported).length
  const shared = inventory.agents.filter(isSharedSkills).length
  log(tf`发现 ${agents.length} 个 Agent，其中 ${supported} 个支持 Skill 管理${shared ? tf`；另发现 ${shared} 个共用 Skills 目录` : ''}`)
}

$('#discover-button').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  $('#agent-list').classList.add('empty')
  $('#agent-list').textContent = t('ui.1jhrms5')
  try {
    await discover()
  } catch (error) {
    $('#agent-list').innerHTML = tf`<div class="empty discovery-error">发现失败：${escapeHtml(error)}</div>`
    log(error)
  } finally {
    setBusy(button, false)
  }
})

$('#add-custom-agent-button').addEventListener('click', () => {
  if (!connection?.configured) return showMessageDialog(t('ui.172wjyr'), t('ui.1ea9uve'))
  $('#custom-agent-form').reset()
  $('#custom-agent-dialog').showModal()
  $('#custom-agent-name').focus()
})
$('#cancel-custom-agent').addEventListener('click', () => $('#custom-agent-dialog').close())
$('#select-custom-agent-path').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const path = await invoke('select_skill_directory')
    if (path) $('#custom-agent-path').value = path
  } catch (error) {
    showMessageDialog(t('ui.xcqz4c'), String(error))
  } finally {
    setBusy(button, false)
  }
})
$('#custom-agent-form').addEventListener('submit', async event => {
  event.preventDefault()
  const button = event.submitter || $('#custom-agent-form button[type="submit"]')
  setBusy(button, true)
  try {
    await run('add-custom-agent', ['--name', $('#custom-agent-name').value.trim(), '--skills-path', $('#custom-agent-path').value.trim()])
    $('#custom-agent-dialog').close()
    await discover()
    showMessageDialog(t('ui.is6ir0'), t('ui.1byen3i'))
  } catch (error) {
    showMessageDialog(t('ui.24x3uq'), String(error))
  } finally {
    setBusy(button, false)
  }
})

const groupTakeoverItems = items => {
  const groups = new Map()
  items.forEach(item => {
    if (!groups.has(item.agent_type)) groups.set(item.agent_type, [])
    groups.get(item.agent_type).push(item)
  })
  return [...groups].map(([agentType, groupItems]) => ({ agentType, items: groupItems }))
}

const pendingStatusTerminal = status => ['APPROVED', 'REJECTED', 'CANCELLED', 'unavailable'].includes(status)
const pendingNeedsRefresh = item => Boolean(item.skill_id) && !pendingStatusTerminal(item.status)
const pendingCanSubmit = item => !item.skill_id

const syncPendingBatchControls = () => {
  const eligible = scopedPendingItems().filter(pendingCanSubmit)
  for (const id of [...selectedPendingIDs]) {
    if (!eligible.some(item => item.id === id)) selectedPendingIDs.delete(id)
  }
  const selectAll = $('#pending-select-all')
  const submitSelected = $('#submit-selected-pending')
  const refreshPending = $('#refresh-pending')
  const selectedCount = eligible.filter(item => selectedPendingIDs.has(item.id)).length
  $('#pending-select-all-wrap').hidden = eligible.length === 0
  submitSelected.hidden = eligible.length === 0
  submitSelected.disabled = selectedCount === 0 || pendingSubmissionBusy
  if (!pendingSubmissionBusy) submitSelected.textContent = tf`提交所选 ${selectedCount}`
  selectAll.disabled = pendingSubmissionBusy
  refreshPending.disabled = pendingSubmissionBusy || pendingRefreshBusy
  document.querySelectorAll('[data-select-pending]').forEach(input => { input.disabled = pendingSubmissionBusy })
  selectAll.checked = eligible.length > 0 && selectedCount === eligible.length
  selectAll.indeterminate = selectedCount > 0 && selectedCount < eligible.length
}

const schedulePendingRefresh = items => {
  if (pendingRefreshTimer) clearTimeout(pendingRefreshTimer)
  pendingRefreshTimer = null
  if (!items.some(pendingNeedsRefresh)) return
  const activeAnalysis = items.some(item => pendingNeedsRefresh(item) && !['VETTED', 'APPROVED'].includes(item.status))
  pendingRefreshTimer = setTimeout(async () => {
    if (document.hidden || pendingRefreshBusy || pendingSubmissionBusy) {
      schedulePendingRefresh(scanHistoryItems)
      return
    }
    try {
      await loadPending(true, { silent: true })
    } catch (error) {
      log(tf`刷新检测状态失败：${error}`)
      schedulePendingRefresh(scanHistoryItems)
    }
  }, activeAnalysis ? 3000 : 10000)
}

const loadPending = async (refresh = false, { silent = false } = {}) => {
  if (refresh && pendingRefreshBusy) return pendingItems
  if (refresh) pendingRefreshBusy = true
  let items
  try {
    items = JSON.parse(await run(refresh ? 'refresh-pending' : 'pending'))
  } finally {
    if (refresh) pendingRefreshBusy = false
  }
  pendingItems = items
  for (const id of [...selectedPendingIDs]) {
    if (!items.some(item => item.id === id && pendingCanSubmit(item))) selectedPendingIDs.delete(id)
  }
  scanHistoryItems = JSON.parse(await run(refresh ? 'refresh-scan-history' : 'scan-history'))
  $('#pending-list').classList.toggle('empty', !scanHistoryItems.length)
  $('#pending-list').innerHTML = groupTakeoverItems(scanHistoryItems).map(group => `<div data-pending-agent="${escapeHtml(group.agentType)}">
    <div class="history-columns recovery-columns"><span>Skill</span><span>${escapeHtml(t('ui.agentHistory.status'))}</span><span>${escapeHtml(t('ui.agentHistory.submitted_at'))}</span></div>
    ${group.items.map(item => `<div class="takeover-row quarantine-row">
      <details class="history-details"><summary data-ui-icon="file-text">${escapeHtml(item.skill_name)}</summary><div class="history-facts"><small>${escapeHtml(item.original_path || item.pending_path)}</small><small>${escapeHtml(t('ui.agentHistory.version'))}: ${escapeHtml(item.version_id || item.skill_id)}</small></div></details>
      <div class="pending-skill-status"><span class="result-status ${escapeHtml(pendingStatusClass(item.status))}"><i></i>${escapeHtml(pendingStatusLabel(item.status))}</span>${scanProgressText(item) ? `<small>${escapeHtml(scanProgressText(item))}</small>` : ''}</div>
      <span class="history-submitted-at">${escapeHtml(formatTime(item.submitted_at || item.created_at))}</span>
    </div>`).join('')}
  </div>`).join('')
  await loadQuarantine()
  syncPendingBatchControls()
  schedulePendingRefresh(scanHistoryItems)
  renderInventory()
  if (refresh && !silent) log(tf`待处理区共有 ${skillCount(items.length)}`)
  return items
}

$('#cancel-discard-pending').addEventListener('click', () => {
  $('#discard-pending-dialog').close()
  pendingDiscardItem = null
})

$('#confirm-discard-pending').addEventListener('click', async event => {
  const item = pendingDiscardItem
  if (!item) return
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('discard-pending', ['--id', item.id, '--confirm'])
    selectedPendingIDs.delete(item.id)
    pendingDiscardItem = null
    $('#discard-pending-dialog').close()
    await loadPending()
    await loadQuarantine()
    await refreshConnection()
    showMessageDialog(t('删除完成'), t('本地停用副本已删除，平台检测和审计记录仍然保留。'))
  } catch (error) {
    showMessageDialog(t('删除失败'), String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})

const submitPendingIDs = async (ids, button) => {
  if (pendingSubmissionBusy || !ids.length) return
  pendingSubmissionBusy = true
  const submitted = []
  const failures = []
  try {
    setBusy(button, true)
    syncPendingBatchControls()
    let currentItems = JSON.parse(await run('pending'))
    for (let index = 0; index < ids.length; index += 1) {
      const id = ids[index]
      button.textContent = ids.length > 1 ? tf`正在提交 ${index + 1}/${ids.length}` : t('ui.agentManagement.submitting')
      const current = currentItems.find(item => item.id === id)
      if (!current || current.skill_id) continue
      try {
        const result = JSON.parse(await run('submit-pending', ['--id', id]))
        submitted.push(result.name || current.skill_name || result.skill_id)
        selectedPendingIDs.delete(id)
        currentItems = JSON.parse(await run('pending'))
      } catch (error) {
        failures.push({ name: current.skill_name || id, detail: String(error) })
        if (String(error).includes('client:submit-skill') || String(error).includes('scanner:submit')) break
      }
    }
    await loadPending()
    if (submitted.length) {
      log(tf`已提交平台检测：${formatList(submitted)}`)
    }
    if (failures.length) {
      const permissionDenied = failures.some(item => item.detail.includes('client:submit-skill') || item.detail.includes('scanner:submit'))
      const detail = permissionDenied
        ? t('ui.agentManagement.submit_permission_required')
        : failures.map(item => `${item.name}：${item.detail}`).join('\n')
      showMessageDialog(t('ui.agentManagement.submit_failed'), detail)
      log(detail)
    }
  } catch (error) {
    const detail = String(error)
    showMessageDialog(t('ui.agentManagement.submit_failed'), detail)
    log(detail)
  } finally {
    pendingSubmissionBusy = false
    ids.forEach(id => selectedPendingIDs.delete(id))
    document.querySelectorAll('[data-select-pending]').forEach(input => {
      input.checked = selectedPendingIDs.has(input.dataset.selectPending)
    })
    button.textContent = button.dataset.busyLabel
    setBusy(button, false)
    syncPendingBatchControls()
  }
}

$('#pending-select-all').addEventListener('change', event => {
  const checked = event.currentTarget.checked
  scopedPendingItems().filter(pendingCanSubmit).forEach(item => {
    if (checked) selectedPendingIDs.add(item.id)
    else selectedPendingIDs.delete(item.id)
  })
  document.querySelectorAll('[data-select-pending]').forEach(input => { input.checked = selectedPendingIDs.has(input.dataset.selectPending) })
  syncPendingBatchControls()
})

$('#submit-selected-pending').addEventListener('click', event => {
  const checkedIDs = [...document.querySelectorAll('[data-select-pending]:checked')]
    .map(input => input.dataset.selectPending)
    .filter(Boolean)
  selectedPendingIDs.clear()
  checkedIDs.forEach(id => selectedPendingIDs.add(id))
  submitPendingIDs(checkedIDs, event.currentTarget)
})

$('#refresh-pending').addEventListener('click', async event => {
  if (pendingSubmissionBusy) {
    showMessageDialog(t('ui.1p52cco'), t('ui.15zzqwz'))
    return
  }
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await loadPending(true)
  } catch (error) {
    showMessageDialog(t('ui.mjir9s'), String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})

const runStatusCommand = async (button, command, success) => {
  setBusy(button, true)
  try {
    const previousFullScan = connection?.local?.last_full_scan_at || ''
    await run(command)
    if (command === 'run-once') await waitForFullScan(previousFullScan)
    await refreshConnection()
    const findings = connection?.local?.patrol_findings || []
    log(command === 'run-once'
      ? findings.length ? tf`巡检完成，发现 ${findings.length} 个异常：${formatList(findings.map(item => item.skill_name))}` : t('ui.77zeux')
      : success)
  } catch (error) {
    showMessageDialog(t('ui.ydow7a'), String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
}
const waitForFullScan = async previous => {
  for (let attempt = 0; attempt < 45; attempt += 1) {
    const status = JSON.parse(await run('local-status'))
    if (status.last_full_scan_at && status.last_full_scan_at !== previous) return
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  throw new Error(t('ui.1nvd3qf'))
}
$('#run-once').addEventListener('click', event => runStatusCommand(event.currentTarget, 'run-once', t('ui.1fhr44u')))
$('#install-service').addEventListener('click', event => runStatusCommand(event.currentTarget, 'reconcile-service', t('ui.1wl6i9a')))
$('#refresh-records').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try { await loadRecordHistory() } finally { setBusy(button, false) }
})

$('#settings-trigger').addEventListener('click', () => { showPanel('settings'); void refreshLogSettings() })
$('#settings-language').addEventListener('change', event => {
  window.clientI18n?.setLocale(event.currentTarget.value)
})
$('#settings-default-panel').addEventListener('change', event => {
  saveClientSettings({ defaultPanel: event.currentTarget.value })
})
$('#settings-system-notifications').addEventListener('change', event => {
  saveClientSettings({ systemNotifications: event.currentTarget.checked })
})
$('#settings-notification-level').addEventListener('change', event => {
  saveClientSettings({ notificationLevel: event.currentTarget.value })
})
$('#settings-auto-update').addEventListener('change', event => {
  saveClientSettings({ autoCheckUpdates: event.currentTarget.checked })
  if (event.currentTarget.checked) void checkClientUpdateAutomatically()
})
$('#settings-update-channel').addEventListener('change', event => {
  saveClientSettings({ updateChannel: event.currentTarget.value })
  pendingClientUpdate = null
  lastAutomaticUpdateCheckAt = 0
  void checkClientUpdate({ interactive: true })
})
$('#settings-check-update').addEventListener('click', async event => {
  if (pendingClientUpdate?.available) {
    openClientUpdateDialog(pendingClientUpdate)
    return
  }
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await checkClientUpdate({ interactive: true })
  } finally {
    setBusy(button, false)
  }
})
$('#settings-open-logs').addEventListener('click', async () => {
  try {
    await invoke('open_client_location', { kind: 'logs' })
  } catch (error) {
    showMessageDialog(t('打开日志目录失败'), String(error))
  }
})
$('#settings-open-data').addEventListener('click', async () => {
  try {
    await invoke('open_client_location', { kind: 'data' })
  } catch (error) {
    showMessageDialog(t('打开数据目录失败'), String(error))
  }
})
let exportingDiagnostics = false
let savingLogSettings = false
let logSettingsRequest = 0
function renderLogSettings(settings) {
  $('#settings-log-retention').value = String(settings.retention_days)
  $('#settings-log-usage').textContent = `${t('ui.diagnostics.usage')}: ${(Number(settings.used_bytes || 0) / 1024 / 1024).toFixed(1)} MB · ${t('ui.diagnostics.limit')}`
  const previous = Number($('#settings-log-range').value) || 3
  $('#settings-log-range').innerHTML = [1, 3, 7, 14, 30].filter(days => days <= settings.retention_days).map(days => `<option value="${days}">${days}</option>`).join('')
  $('#settings-log-range').value = String(Math.min(previous, settings.retention_days))
}
async function refreshLogSettings() {
  if (savingLogSettings) return
  const request = ++logSettingsRequest
  try {
    const settings = JSON.parse(await run('log-settings'))
    if (request === logSettingsRequest && !savingLogSettings) renderLogSettings(settings)
  } catch (error) {
    if (request === logSettingsRequest && !savingLogSettings) $('#settings-log-usage').textContent = runtimeText(error)
  }
}
$('#settings-log-retention').addEventListener('change', async event => {
  if (savingLogSettings) return
  savingLogSettings = true
  ++logSettingsRequest
  const control = event.currentTarget
  control.disabled = true
  try { renderLogSettings(JSON.parse(await run('log-settings', ['--days', control.value]))) }
  catch (error) { showMessageDialog(t('ui.diagnostics.failed'), runtimeText(error)) }
  finally { savingLogSettings = false; control.disabled = false; await refreshLogSettings() }
})
$('#settings-export-diagnostics').addEventListener('click', async event => {
  if (exportingDiagnostics) return
  exportingDiagnostics = true
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const path = await invoke('export_diagnostics', { days: Number($('#settings-log-range').value) || 3 })
    showMessageDialog(t('诊断报告已导出'), tf`文件已保存到 ${path}`)
    await refreshLogSettings()
  } catch (error) {
    showMessageDialog(t('导出诊断报告失败'), String(error))
  } finally {
    exportingDiagnostics = false
    setBusy(button, false)
  }
})

$('#overview-sync').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try { await refreshConnection() } finally { setBusy(button, false) }
})
$('#edit-connection').addEventListener('click', editConnection)
document.querySelectorAll('[data-target-panel]').forEach(button => {
  button.addEventListener('click', () => showPanel(button.dataset.targetPanel))
})

const clientUpdateVersion = result => result?.display_version || result?.version || ''

const renderClientUpdateAvailability = result => {
  const button = $('#settings-check-update')
  const available = Boolean(result?.available)
  const version = clientUpdateVersion(result)
  pendingClientUpdate = available ? result : null
  button.classList.toggle('update-available', available)
  button.classList.toggle('icon-check', !available)
  button.classList.toggle('icon-install', available)
  button.textContent = available ? tf`可更新 ${version}` : t('ui.re5xvw')
  button.title = available ? tf`发现客户端新版本 ${version}，点击查看并更新` : t('ui.1wcdr2e')
  if ($('#settings-update-status')) {
    $('#settings-update-status').textContent = available
      ? tf`发现新版本 ${version}`
      : t('已是当前通道的最新版本。')
  }
}

const openClientUpdateDialog = result => {
  const version = clientUpdateVersion(result)
  $('#update-dialog-title').textContent = tf`发现新版本 ${version}`
  $('#update-dialog-notes').textContent = result.notes || t('ui.1osi4fc')
  $('#client-update-progress').hidden = true
  $('#cancel-client-update').disabled = false
  $('#confirm-client-update').disabled = false
  $('#update-dialog').showModal()
}

const notifyClientUpdate = async result => {
  const version = clientUpdateVersion(result)
  if (!version || localStorage.getItem(CLIENT_UPDATE_NOTIFIED_KEY) === version) return
  await invoke('show_system_notification', {
    title: tf`客户端新版本 ${version}`,
    body: t('ui.en65u1'),
  })
  localStorage.setItem(CLIENT_UPDATE_NOTIFIED_KEY, version)
}

const checkClientUpdate = async ({ interactive = false, notify = false } = {}) => {
  if (clientUpdateCheckBusy) {
    if (interactive) showMessageDialog(t('ui.t1go01'), t('ui.147j41'))
    return
  }
  clientUpdateCheckBusy = true
  lastAutomaticUpdateCheckAt = Date.now()
  try {
    const result = await invoke('check_client_update', { install: false, channel: clientSettings.updateChannel })
    if (!result.available) {
      renderClientUpdateAvailability(null)
      if (interactive) {
        const developmentBuild = result.supported === false
        const title = developmentBuild ? t('ui.1bbpt32') : t('ui.16i7quy')
        const detail = result.notes || t('ui.141nh2n')
        showMessageDialog(title, detail)
        log(developmentBuild ? t('ui.1n2cpzt') : t('ui.16cvhj6'))
      }
      return
    }
    renderClientUpdateAvailability(result)
    if (notify) {
      try {
        await notifyClientUpdate(result)
      } catch (error) {
        log(tf`新版本通知发送失败：${error}`)
      }
    }
    if (interactive) openClientUpdateDialog(result)
  } catch (error) {
    if ($('#settings-update-status')) $('#settings-update-status').textContent = runtimeText(error)
    if (interactive) {
      showMessageDialog(t('ui.1be4nr0'), String(error))
      log(error)
    }
  } finally {
    clientUpdateCheckBusy = false
  }
}

const checkClientUpdateAutomatically = () => {
  if (!clientSettings.autoCheckUpdates || !connection?.connected || Date.now() - lastAutomaticUpdateCheckAt < CLIENT_UPDATE_CHECK_INTERVAL_MS) return
  void checkClientUpdate({ notify: true })
}

$('#cancel-client-update').addEventListener('click', () => {
  if (clientUpdateInstalling) return
  $('#update-dialog').close()
  if (pendingClientUpdate?.version) log(tf`发现新版本 ${clientUpdateVersion(pendingClientUpdate)}，已选择稍后更新`)
})
$('#update-dialog').addEventListener('cancel', event => {
  if (clientUpdateInstalling) event.preventDefault()
})

$('#confirm-client-update').addEventListener('click', async event => {
  if (clientUpdateInstalling || !pendingClientUpdate) return
  const button = event.currentTarget
  clientUpdateInstalling = true
  $('#cancel-client-update').disabled = true
  setBusy(button, true)
  renderClientUpdateProgress({ stage: 'preparing' })
  try {
    const result = await invoke('check_client_update', { install: true, channel: clientSettings.updateChannel })
    if (!result.available) {
      $('#update-dialog').close()
      showMessageDialog(t('ui.zdzohd'), t('ui.drdmvz'))
    }
  } catch (error) {
    $('#update-dialog').close()
    showMessageDialog(t('ui.10lkv9z'), String(error))
    log(error)
  } finally {
    clientUpdateInstalling = false
    $('#cancel-client-update').disabled = false
    setBusy(button, false)
  }
})

let backupPreview = null
let backupPreviewSequence = 0
const previewBackup = async () => {
  const sequence = ++backupPreviewSequence
  const name = $('#backup-select').value
  backupPreview = null
  $('#restore-backup').disabled = true
  $('#backup-preview').textContent = t(name ? 'ui.backups.loading' : 'ui.backups.empty')
  if (!name) return
  try {
    const items = JSON.parse(await run('backups', ['--backup', name])) || []
    if (sequence !== backupPreviewSequence) return
    backupPreview = { name, items }
    $('#backup-preview').innerHTML = items.length ? items.map(item => `<div class="backup-skill"><div><strong>${escapeHtml(item.SkillName)}</strong><small>${escapeHtml(item.AgentType)}</small><code>${escapeHtml(item.Target)}</code></div><span class="backup-impact">${t(item.Signature === item.TargetSignature ? 'ui.backups.same' : item.TargetSignature ? 'ui.backups.replace' : 'ui.backups.create')}</span></div>`).join('') : escapeHtml(t('ui.backups.empty'))
    $('#backup-feedback').textContent = t(connection?.platform?.manual_skill_actions_allowed ? 'ui.backups.policy' : 'ui.agentManagement.action_permission_required')
    $('#restore-backup').disabled = !items.length || !connection?.platform?.manual_skill_actions_allowed || backupRestoreBusy
  } catch (error) {
    if (sequence === backupPreviewSequence) $('#backup-preview').textContent = connectionErrorText(String(error))
  }
}
$('#backup-select').addEventListener('change', () => { void previewBackup() })
$('#backup-task-records').addEventListener('click', () => { showPanel('records'); $('#records-tasks-tab').click() })
const loadBackups = async () => {
  const selected = $('#backup-select').value
  const backups = JSON.parse(await run('backups'))
  $('#backup-select').innerHTML = backups.length
    ? backups.map(item => `<option value="${escapeHtml(item.name)}">${escapeHtml(formatTime(item.created_at))} · ${escapeHtml(item.name)}</option>`).join('')
    : t('ui.2jmxw8')
  if (backups.some(item => item.name === selected)) $('#backup-select').value = selected
  await previewBackup()
  return backups
}
$('#refresh-backups').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const backups = await loadBackups()
    log(tf`找到 ${backups.length} 个可恢复备份`)
  } catch (error) {
    showMessageDialog(t('ui.z05bdy'), String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})
let backupRestoreBusy = false
let backupRestoreRequest = null
$('#restore-backup').addEventListener('click', async event => {
  if (backupRestoreBusy) return
  const backup = $('#backup-select').value
  const preview = backupPreview
  if (!preview || preview.name !== backup || !preview.items.length) return
  if (!backup) return log(t('ui.1npxley'))
  if (!connection?.platform?.manual_skill_actions_allowed) return showMessageDialog(t('ui.agentManagement.restore_backup_title'), t('ui.agentManagement.action_permission_required'))
  if (!window.confirm(t('ui.agentManagement.restore_backup_confirm'))) return
  if (backupRestoreRequest?.backup !== backup) backupRestoreRequest = { backup, id: crypto.randomUUID() }
  backupRestoreBusy = true
  const button = event.currentTarget
  setBusy(button, true)
  $('#backup-select').disabled = true
  $('#refresh-backups').disabled = true
  try {
    const current = JSON.parse(await run('backups', ['--backup', backup])) || []
    if (JSON.stringify(current) !== JSON.stringify(preview.items)) {
      await previewBackup()
      $('#backup-feedback').textContent = t('ui.backups.changed')
      return
    }
    const result = JSON.parse(await run('restore', ['--backup', backup, '--request-id', backupRestoreRequest.id, '--confirm']))
    const summary = `${t('ui.agentManagement.restore_backup_queued')}: ${result.tasks.length}`
    log(summary)
    $('#backup-feedback').textContent = summary
    if (result.errors.length) {
      await refreshConnection()
      await loadQuarantine()
      showMessageDialog(t('ui.agentManagement.restore_backup_title'), `${summary}\n${result.errors.map(connectionErrorText).join('\n')}\n\n${t('ui.agentManagement.restore_backup_partial')}`)
    } else {
      backupRestoreRequest = null
      showMessageDialog(t('ui.agentManagement.restore_backup_title'), summary)
    }
    await refreshLocalNotifications()
  } catch (error) {
    showMessageDialog(t('ui.6y1l8i'), String(error))
    log(error)
  } finally {
    backupRestoreBusy = false
    setBusy(button, false)
    $('#backup-select').disabled = false
    $('#refresh-backups').disabled = false
    button.disabled = !backupPreview?.items.length || !connection?.platform?.manual_skill_actions_allowed
  }
})

const mergeRecoveryCopies = (quarantined, pending) => {
  const result = []
  const paths = new Set()
  for (const copy of quarantined) {
    if (copy.quarantine_path && paths.has(copy.quarantine_path)) continue
    const linked = pending.find(item => item.id === copy.pending_id || item.pending_path === copy.quarantine_path)
    result.push(linked?.skill_id ? {...copy, skill_id: linked.skill_id, version_id: linked.version_id, detection_status: linked.status} : copy)
    if (copy.quarantine_path) paths.add(copy.quarantine_path)
  }
  for (const item of pending) {
    if (item.reason === 'observed_scan' || item.reason === 'quarantine_rescan' || paths.has(item.pending_path) || quarantined.some(copy => copy.pending_id === item.id)) continue
    result.push({...item, id: `pending:${item.id}`, pending_copy_id: item.id, quarantine_path: item.pending_path, detection_status: item.skill_id ? item.status : '', status: 'pending_copy'})
    if (item.pending_path) paths.add(item.pending_path)
  }
  return result
}
const recoveryStage = item => {
  if (item.status === 'backed_up') return 'backup'
  if (!item.skill_id) return 'unsubmitted'
  if (item.detection_status === 'APPROVED') return 'approved'
  if (item.detection_status === 'REJECTED') return 'rejected'
  if (item.detection_status === 'VETTED') return 'review'
  if (['CANCELLED', 'unavailable', 'FAILED', 'ERROR'].includes(item.detection_status)) return 'interrupted'
  return 'scanning'
}
const recoveryVisible = item => scopeIncludes(item) && (!$('#recovery-status-filter').value || recoveryStage(item) === $('#recovery-status-filter').value)
$('#recovery-status-filter').addEventListener('change', () => {
  selectedPendingIDs.clear()
  syncAgentHistory()
})
const loadQuarantine = async () => {
  pendingItems = JSON.parse(await run('pending'))
  const quarantined = JSON.parse(await run('quarantine'))
  const items = mergeRecoveryCopies(quarantined, pendingItems)
  recoveryItems = items
  $('#quarantine-list').classList.toggle('empty', !items.length)
  $('#quarantine-list').innerHTML = items.length ? `<div class="history-columns recovery-columns"><span>Skill</span><span>${escapeHtml(t('ui.agentHistory.status'))}</span><span>${escapeHtml(t('ui.agentTabs.actions'))}</span></div>` + items.map(item => {
    const pending = (connection?.platform?.tasks || []).some(task => task.task_type === 'skill_action' && task.payload?.path === item.original_path && ['pending', 'running'].includes(task.status))
    const recoveryReason = !connection?.platform?.manual_skill_actions_allowed ? t('ui.agentManagement.action_permission_required')
      : !connection?.connected ? t('ui.agentManagement.actionStatus.waiting')
      : !item.signature || item.error_code ? t('ui.agentManagement.recovery_unavailable')
      : pending ? t('ui.agentManagement.action_pending') : ''
    const detection = item.detection_status
      ? { ...item, status: item.detection_status }
      : null
    return tf`
    <div class="takeover-row quarantine-row" data-recovery-agent="${escapeHtml(item.agent_type)}" data-recovery-id="${escapeHtml(item.id)}">
      <div class="quarantine-skill-identity">${item.pending_copy_id && !item.skill_id ? `<input type="checkbox" class="pending-copy-select" data-select-pending="${escapeHtml(item.pending_copy_id)}" aria-label="${escapeHtml(item.skill_name)}" ${selectedPendingIDs.has(item.pending_copy_id) ? 'checked' : ''} />` : ''}<details class="history-details"><summary data-ui-icon="file-text">${escapeHtml(item.skill_name)}</summary><div class="history-facts"><button class="path-link" type="button" title="隔离目录：${escapeHtml(item.quarantine_path)}" data-reveal-path="${escapeHtml(item.quarantine_path)}">所属 Agent：${escapeHtml(agentLabel(item.agent_type))} · ${escapeHtml(item.original_path || item.pending_path)}</button><small>${escapeHtml(detection ? quarantineDetectionGuidance(detection) : reasonLabel(item.reason))}</small>${item.skill_id ? `<small>${escapeHtml(quarantineNextLabel(item.detection_status))}</small>` : ''}</div></details></div>
      ${detection
        ? `<strong class="quarantine-status result-status ${escapeHtml(pendingStatusClass(detection.status))}"><i></i>${escapeHtml(pendingStatusLabel(detection.status))}</strong>`
        : `<strong class="quarantine-status result-status status-review" data-ui-icon="archive">${escapeHtml(t(item.pending_copy_id ? 'ui.agentHistory.pending_copy' : item.status === 'backed_up' ? 'ui.agentHistory.backed_up' : 'ui.agentHistory.quarantined'))}</strong>`}
      <div class="takeover-row-actions quarantine-actions">
        ${item.status === 'backed_up' ? `<button type="button" class="icon-button" data-ui-icon="rotate-ccw" data-restore-quarantine="${escapeHtml(item.id)}" title="${escapeHtml(recoveryReason)}" ${recoveryReason ? 'disabled' : ''}>${escapeHtml(t('ui.agentManagement.restore_short'))}</button>` : ''}
        ${!item.skill_id
          ? `<button class="primary icon-button icon-submit ${submittingQuarantineIDs.has(item.id) ? 'is-busy' : ''}" data-submit-quarantine="${escapeHtml(item.id)}" data-busy-text="${escapeHtml(t('ui.agentManagement.submitting'))}" ${submittingQuarantineIDs.has(item.id) ? 'disabled aria-busy="true"' : ''}>${escapeHtml(t(submittingQuarantineIDs.has(item.id) ? 'ui.agentManagement.submitting' : 'ui.agentManagement.scan_short'))}</button>`
          : ''}
        <details class="skill-more"><summary data-ui-icon="ellipsis" aria-label="${escapeHtml(t('ui.agentManagement.more'))}"></summary><div class="skill-more-menu">
        ${recoveryReason ? `<small class="skill-menu-hint">${escapeHtml(recoveryReason)}</small>` : ''}
        ${item.pending_copy_id ? `<button type="button" data-ui-icon="trash-2" data-discard-copy="${escapeHtml(item.pending_copy_id)}">${escapeHtml(t('ui.agentHistory.delete_copy'))}</button>` : ''}
        <button class="icon-button icon-install" data-install-safe-version="${escapeHtml(item.skill_name)}">选择批准版本</button>
        </div></details>
      </div>
    </div>`
  }).join('') : t('ui.w1aoqw')
  document.querySelectorAll('[data-select-pending]').forEach(input => input.addEventListener('change', () => {
    if (input.checked) selectedPendingIDs.add(input.dataset.selectPending)
    else selectedPendingIDs.delete(input.dataset.selectPending)
    syncPendingBatchControls()
  }))
  document.querySelectorAll('[data-discard-copy]').forEach(button => button.addEventListener('click', () => {
    const item = pendingItems.find(item => item.id === button.dataset.discardCopy)
    if (!item) return
    pendingDiscardItem = item
    $('#discard-pending-name').textContent = item.skill_name
    $('#discard-pending-agent').textContent = agentLabel(item.agent_type)
    $('#discard-pending-path').textContent = item.pending_path
    $('#discard-pending-dialog').showModal()
  }))
  document.querySelectorAll('[data-restore-quarantine]').forEach(button => button.addEventListener('click', () => {
    if (requestingSkillAction) return
    const item = items.find(value => value.id === button.dataset.restoreQuarantine)
    if (!item?.signature || item.status !== 'backed_up') return
    const restoringBackup = item.status === 'backed_up'
    const current = inventory?.agents?.flatMap(agent => agent.skills || []).find(skill => skill.path === item.original_path)
    pendingSkillAction = { requestID: crypto.randomUUID(), action: restoringBackup ? 'restore_backup' : 'restore_quarantine', agentType: item.agent_type,
      path: item.original_path, signature: item.signature, quarantineID: item.id, targetSignature: current?.signature }
    $('#skill-action-title').textContent = governanceLabelFor('action', pendingSkillAction.action)
    $('#skill-action-description').textContent = t(restoringBackup ? 'ui.agentManagement.restore_backup_confirm' : 'ui.agentManagement.recovery_confirm')
    $('#skill-action-path').textContent = item.original_path
    const agent = inventory?.agents?.find(value => value.agent_type === item.agent_type)
    const readers = skillSharedReaders(agent, item.original_path)
    $('#skill-action-impact').textContent = readers.length
      ? `${t('ui.agentManagement.shared_impact')}: ${formatList(readers)}`
      : `${t('ui.agentManagement.binding')}: ${agentLabel(item.agent_type)}`
    $('#skill-action-dialog').dataset.action = pendingSkillAction.action
    $('#skill-action-dialog').showModal()
  }))
  document.querySelectorAll('[data-submit-quarantine]').forEach(button => button.addEventListener('click', async () => {
    if (pendingSubmissionBusy || submittingQuarantineIDs.size) return
    const quarantineID = button.dataset.submitQuarantine
    submittingQuarantineIDs.add(quarantineID)
    setBusy(button, true)
    try {
      const copy = items.find(item => item.id === button.dataset.submitQuarantine)
      const pending = copy?.pending_copy_id ? {id: copy.pending_copy_id} : JSON.parse(await run('queue-quarantine', ['--id', button.dataset.submitQuarantine]))
      await submitPendingIDs([pending.id], button)
      await refreshConnection()
      await loadQuarantine()
    } catch (error) {
      showMessageDialog(t('ui.agentManagement.submit_failed'), String(error))
      log(error)
    } finally {
      submittingQuarantineIDs.delete(quarantineID)
      setBusy(button, false)
      await loadQuarantine().catch(log)
    }
  }))
  document.querySelectorAll('[data-install-safe-version]').forEach(button => button.addEventListener('click', () => {
    openInstallDialog(null, button.dataset.installSafeVersion)
  }))
  syncAgentHistory()
  if (connection?.configured) renderConnected(connection)
  return items
}

$('#refresh-quarantine').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const items = await loadQuarantine()
    log(tf`隔离区共有 ${items.filter(item => item.status === 'quarantined').length} 个待处理 Skill`)
  } catch (error) {
    showMessageDialog(t('ui.vowndr'), String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})

function agentLabel(value) {
  const customName = inventory?.agents?.find(agent => agent.agent_type === value)?.display_name
  if (customName) return customName
  return {
    'claude-code': 'Claude Code',
    codex: 'Codex',
    gemini: 'Gemini CLI',
    opencode: 'OpenCode',
    openclaw: 'OpenClaw',
    hermes: 'Hermes',
    'trae-cn': 'TRAE CN',
    trae: 'TRAE',
    cursor: 'Cursor',
    'global-skills': t('ui.13u0v7i'),
    codebuddy: 'CodeBuddy',
    workbuddy: 'WorkBuddy',
  }[value] || value
}

function taskTypeLabel(task) {
  const value = task?.task_type || task
  if (value === 'skill_action') return governanceLabelFor('action', task.payload?.action)
  if (value === 'rescan' && task?.payload?.reason === 'policy_changed') return t('ui.q9utgp')
  return { install_skill: t('ui.14fftle'), remove_skill: t('ui.s2pmon'), repair_skill: t('ui.14oueep'), apply_model_config: t('client.models.task_type'), rescan: t('ui.1rnx8gk'), sync_policy: t('ui.q9utgp') }[value] || value || tf`平台任务`
}

function taskStatusLabel(value) {
  return { pending: t('ui.1yesuc2'), running: t('ui.6svkbt'), succeeded: t('ui.19j4h'), failed: t('ui.12db3qz'), cancelled: t('ui.1d8x36r') }[value] || value || '-'
}

function eventTypeLabel(value) {
  return {
    agent_credential_issued: t('ui.activity.credential_issued'),
    local_agent_binding_updated: t('ui.activity.binding_updated'),
    managed_agent_auto_created: t('ui.activity.agent_created'),
    skill_governance_recorded: t('ui.agentManagement.recorded'), skill_governance_detected: t('ui.agentManagement.alert'), skill_governance_action: t('ui.agentManagement.remediation'), skill_scan_submitted: t('ui.agentManagement.submitted'),
    client_registered: t('ui.444a0v'), takeover_completed: t('ui.1nk4zrj'), unmanaged_skill_found: t('ui.gawr4f'),
    unmanaged_skill_verified: t('ui.11fi048'), skill_installed: t('ui.14fftle'), skill_removed: t('ui.s2pmon'),
    skill_modified: t('ui.grb2re'), skill_repaired: t('ui.1dswesb'), skill_blocked: t('ui.ly2ow4'),
    skill_quarantined: t('ui.1bc6akl'), skill_quarantine_restored: t('ui.1swl6k'),
  }[value] || value || t('ui.1l0wfyp')
}

function eventDetail(value) {
  return { skill_repaired: t('ui.1nedkoa'), skill_modified: t('ui.111odxs'), skill_blocked: t('ui.l5pb9v'), skill_quarantined: t('ui.1ena7pa') }[value] || '-'
}

const eventStatus = value => value === 'skill_modified' ? 'running' : ['skill_blocked', 'skill_quarantined'].includes(value) ? 'failed' : 'succeeded'
const eventResultLabel = value => value === 'skill_modified' ? t('ui.4bymt0') : ['skill_blocked', 'skill_quarantined'].includes(value) ? t('ui.1ltzzrr') : t('ui.19j4h')

function agentKind(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '').replace(/^claude$/, 'claudecode').replace(/^geminicli$/, 'gemini')
}

function reasonLabel(value) {
  return {
    allowed: t('ui.9nqwss'),
    skill_not_found: t('ui.1cgsepv'),
    skill_not_approved: t('ui.vtlruf'),
    signature_mismatch: t('ui.1bxv65w'),
    managed_agent_not_found: t('ui.15k9sn2'),
    agent_not_authorized: t('ui.1djc1z3'),
    local_agent_not_found: t('ui.2oan4k'),
    unmanaged_skill: t('ui.1o9b1mg'),
    already_managed: t('ui.r1tok9'),
    not_compared: t('ui.1psmu0h'),
    legacy_pending: t('ui.1lrslxp'),
    quarantine_rescan: t('ui.agentManagement.quarantine_rescan'),
  }[value] || value || '-'
}

function pendingStatusLabel(value) {
  return {
    unavailable: t('ui.agentHistory.unavailable'),
    pending: t('ui.pctz4h'),
    submitted: t('ui.xr2jgj'),
    PENDING: t('ui.xr2jgj'),
    VETTED: t('ui.ja05aw'),
    APPROVED: t('ui.1e2kk7j'),
    REJECTED: t('ui.1a4ymwt'),
    CANCELLED: t('ui.1iiq2qc'),
  }[value] || value || t('ui.pctz4h')
}

function pendingStatusClass(value) {
  return {
    submitted: 'status-processing',
    PENDING: 'status-processing',
    VETTED: 'status-review',
    APPROVED: 'status-approved',
    REJECTED: 'status-rejected',
    CANCELLED: 'status-cancelled',
  }[value] || 'status-pending'
}

function pendingGroupSummary(items) {
  const actionable = items.filter(pendingCanSubmit).length
  const review = items.filter(item => item.status === 'VETTED').length
  return [
    skillCount(items.length),
    actionable ? tf`待检测 ${actionable}` : '',
    review ? tf`待审核 ${review}` : '',
  ].filter(Boolean).join(' · ')
}

function pendingStatusGuidance(item) {
  if (item.status === 'APPROVED' && item.auto_install_error) return `${t('ui.agentHistory.install_failed')}: ${runtimeText(item.auto_install_error)}`
  if (item.status === 'APPROVED') return t('ui.lq6pi3')
  if (item.status === 'REJECTED') return t('ui.1m5rgkv')
  if (item.status === 'CANCELLED') return t('ui.z61ghp')
  if (item.status === 'VETTED') return t('ui.14chebx')
  if (item.skill_id) return t('status.platform_scanning')
  return reasonLabel(item.reason)
}

function pendingNextLabel(status) {
  if (status === 'REJECTED') return t('ui.18gje6f')
  if (status === 'CANCELLED') return t('ui.18gje6f')
  if (status === 'VETTED') return t('ui.17tazct')
  return t('ui.12iu3xi')
}

function quarantineDetectionGuidance(item) {
  if (item.status === 'REJECTED') return t('ui.8lsmup')
  return pendingStatusGuidance(item)
}

function quarantineNextLabel(status) {
  if (status === 'REJECTED' || status === 'CANCELLED') return t('ui.114uhtn')
  return pendingNextLabel(status)
}

const managedAgentIDFor = agentType => (connection?.platform?.agents || []).find(item => item.agent_type === agentType)?.managed_agent_id || ''

const installPlatformSkill = async (agentType, skillId, pendingId = '', versionId = '') => {
  const args = ['--agent-type', agentType, '--skill-id', skillId]
  const managedAgentID = managedAgentIDFor(agentType)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  if (pendingId) args.push('--id', pendingId)
  if (versionId) args.push('--version-id', versionId)
  await run('install-skill', args)
  log(tf`已安装 Skill ${skillId} 到 ${agentLabel(agentType)}`)
}

const refreshAfterInstall = async () => {
  // Rediscover before rendering the installed Skill in its Agent group.
  await discover()
  await refreshConnection()
  await loadPending()
}

const availableSkillsForAgent = async (agent, query = '', skillId = '') => {
  const agentType = agent.agent_type
  const args = ['--agent-type', agentType]
  const managedAgentID = managedAgentIDFor(agentType)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  if (query) args.push('--query', query)
  if (skillId) args.push('--skill-id', skillId)
  try {
    return { agent, items: JSON.parse(await run('available-skills', args)), error: '' }
  } catch (error) {
    const rawError = String(error ?? '')
    return {
      agent,
      items: [],
      error: runtimeText(error),
      unauthorized: /\b403\b/.test(rawError),
    }
  }
}

const skillVersionsForAgent = async (agent, skillId) => {
  const args = ['--skill-id', skillId, '--agent-type', agent.agent_type]
  const managedAgentID = managedAgentIDFor(agent.agent_type)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  return JSON.parse(await run('skill-versions', args))
}

const exactAvailableSkillForAgent = async (agent, skill) => {
  const result = await availableSkillsForAgent(agent, '', skill.skill_id)
  if (result.items.some(item => item.skill_id === skill.skill_id)) return result
  if (result.error) return result
  // Older sidecars accept --skill-id but silently omit it from the request and
  // return the paginated catalog. Fall back to the existing exact versions
  // endpoint so catalog pagination never decides target authorization.
  try {
    const versions = await skillVersionsForAgent(agent, skill.skill_id)
    const trusted = (versions.items || []).find(item => item.version_id === versions.default_version_id) || versions.items?.[0]
    return {
      agent,
      items: trusted ? [{ ...skill, skill_id: versions.skill_id || skill.skill_id, ...trusted }] : [],
      versions,
      error: '',
    }
  } catch (error) {
    const rawError = String(error ?? '')
    return {
      agent,
      items: [],
      error: runtimeText(error),
      unauthorized: /\b403\b/.test(rawError),
    }
  }
}

const loadInstallCatalog = async (agents, query = '', skill = null) => {
  if (skill?.skill_id) {
    return Promise.all(agents.map(agent => exactAvailableSkillForAgent(agent, skill)))
  }
  if (connection?.platform?.governance_mode !== 'strict') {
    const result = await availableSkillsForAgent(agents[0], query)
    return agents.map(agent => ({ ...result, agent }))
  }
  return Promise.all(agents.map(agent => availableSkillsForAgent(agent, query)))
}

const selectedInstallSkill = () => {
  const skillId = $('#install-platform-skill').value
  return lockedInstallSkill || installCatalog.flatMap(item => item.items).find(item => item.skill_id === skillId)
}

const installSubmitter = item => item?.submitted_by || t('ui.13nfgz7')
const installVersion = item => item?.version_no ? `v${item.version_no}` : 'v-'
const installSubmittedAt = item => item?.submitted_at ? formatTime(item.submitted_at) : '-'

const installCatalogSourceFor = skill => {
  const candidates = installCatalog.filter(item => item.items.some(candidate => candidate.skill_id === skill.skill_id))
  return candidates.find(item => item.agent.agent_type === lockedInstallSkill?.source_agent_type) || candidates[0]
}

const installCatalogError = () => installCatalog.find(item => item.error)?.error || ''

const installSkills = () => {
  const skills = new Map()
  installCatalog.flatMap(item => item.items).forEach(item => skills.set(item.skill_id, item))
  if (lockedInstallSkill) skills.set(lockedInstallSkill.skill_id, lockedInstallSkill)
  return [...skills.values()]
}

const loadInstallSkillVersions = async () => {
  const skill = selectedInstallSkill()
  const select = $('#install-platform-version')
  installVersions = []
  select.disabled = true
  $('#confirm-install-skill').disabled = true
  select.innerHTML = `<option value="">${skill ? '正在读取可信版本...' : t('请先选择 Skill')}</option>`
  if (!skill) return
  const source = installCatalogSourceFor(skill)
  if (!source) {
    select.innerHTML = `<option value="">${escapeHtml(installCatalogError() || t('ui.1roebpj'))}</option>`
    return
  }
  const args = ['--skill-id', skill.skill_id, '--agent-type', source.agent.agent_type]
  const managedAgentID = managedAgentIDFor(source.agent.agent_type)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  try {
    const response = source.versions || JSON.parse(await run('skill-versions', args))
    if (selectedInstallSkill()?.skill_id !== skill.skill_id) return
    installVersions = response.items || []
    select.innerHTML = installVersions.length
      ? installVersions.map(item => `<option value="${escapeHtml(item.version_id)}">${escapeHtml(installVersion(item))}${item.source_version ? ` · ${escapeHtml(item.source_version)}` : ''}${item.latest_trusted ? ` · ${t('ui.install.latest_trusted')}` : ''} · ${escapeHtml(tf`提交人：${installSubmitter(item)}`)} · ${escapeHtml(tf`提交时间：${installSubmittedAt(item)}`)}</option>`).join('')
      : '<option value="">暂无可信版本</option>'
    select.value = response.default_version_id || installVersions[0]?.version_id || ''
    select.disabled = !installVersions.length
    await loadInstallSkillPreview()
    updateInstallTargetCount()
  } catch (error) {
    select.innerHTML = `<option value="">${escapeHtml(runtimeText(error))}</option>`
  }
}

const loadInstallSkillPreview = async () => {
  const skill = selectedInstallSkill()
  if (!skill) {
    $('#install-skill-preview').innerHTML = t('ui.1ilu5f6')
    return
  }
  const source = installCatalogSourceFor(skill)
  if (!source) {
    $('#install-skill-preview').innerHTML = tf`<strong>${escapeHtml(skill.name)}</strong><span>${escapeHtml(installCatalogError() || t('ui.1roebpj'))}</span>`
    return
  }
  const args = ['--skill-id', skill.skill_id, '--agent-type', source.agent.agent_type]
  const versionID = $('#install-platform-version').value
  if (versionID) args.push('--version-id', versionID)
  const managedAgentID = managedAgentIDFor(source.agent.agent_type)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  $('#install-skill-preview').innerHTML = tf`<strong>${escapeHtml(skill.name)}</strong><span>正在读取说明...</span>`
  try {
    const item = JSON.parse(await run('skill-preview', args))
    if (selectedInstallSkill()?.skill_id !== skill.skill_id) return
    $('#install-skill-preview').innerHTML = tf`<strong>${escapeHtml(item.name)} · ${escapeHtml(installVersion(item))}</strong><span>${escapeHtml(item.description || t('ui.4wmnyk'))}</span><small>状态：已批准${item.risk_level ? tf` · 风险等级：${escapeHtml(item.risk_level)}` : ''} · 提交人：${escapeHtml(installSubmitter(item))} · 提交时间：${escapeHtml(installSubmittedAt(item))}</small>`
  } catch (error) {
    $('#install-skill-preview').innerHTML = tf`<strong>${escapeHtml(skill.name)}</strong><span>说明读取失败：${escapeHtml(error)}</span>`
  }
}

const renderInstallSkillOptions = () => {
  if (lockedInstallSkill) return
  const query = $('#install-skill-search').value.trim().toLowerCase()
  const current = $('#install-platform-skill').value
  const skills = installSkills().filter(item => !query || item.name.toLowerCase().includes(query))
  $('#install-platform-skill').innerHTML = `<option value="">${skills.length ? t('ui.cnlubu') : t('ui.5jkgiy')}</option>${skills.map(item => `<option value="${escapeHtml(item.skill_id)}">${escapeHtml(item.name)} · ${escapeHtml(installVersion(item))} · ${escapeHtml(tf`提交人：${installSubmitter(item)}`)} · ${escapeHtml(tf`提交时间：${installSubmittedAt(item)}`)}</option>`).join('')}`
  if (skills.some(item => item.skill_id === current)) $('#install-platform-skill').value = current
  renderInstallTargets()
  loadInstallSkillVersions()
}

const updateInstallTargetCount = () => {
  const selected = $('#install-agent-targets').querySelectorAll('[data-install-target]:checked').length
  $('#confirm-install-skill').disabled = platformInstallBusy || !selected || !$('#install-platform-version').value || $('#install-platform-version').disabled
  $('#install-target-count').textContent = t('ui.installTargets.count').replace('{selected}', selected).replace('{total}', installCatalog.length)
}
$('#install-agent-targets').addEventListener('change', updateInstallTargetCount)

const renderInstallTargets = () => {
  const skill = selectedInstallSkill()
  if (!skill) {
    $('#install-agent-targets').innerHTML = t('ui.icgn8')
    updateInstallTargetCount()
    return
  }
  $('#install-agent-targets').innerHTML = installCatalog.map(({ agent, items, error, unauthorized }) => {
    const sourceAgent = lockedInstallSkill?.source_agent_type === agent.agent_type
    const installed = sourceAgent || (agent.skills || []).some(item => item.skill_id === skill.skill_id)
    const conflict = !installed && (agent.skills || []).some(item => item.name === skill.name && item.status !== 'broken_link')
    const available = items.some(item => item.skill_id === skill.skill_id)
    const disabled = installed || conflict || !available
    const status = sourceAgent ? t('ui.yzzvd8') : installed ? t('ui.hdlzwj') : conflict ? t('ui.1bmno87') : available ? t('ui.1k3oaj4') : unauthorized ? t('ui.1rrz078') : t('ui.vub0qv')
    const kind = conflict ? 'conflict' : available && !installed ? 'available' : ''
    return `<label class="install-agent-target ${kind}" title="${escapeHtml(error)}">
      <span><input type="checkbox" data-install-target value="${escapeHtml(agent.agent_type)}" ${disabled ? 'disabled' : agent.agent_type === installAgentContext ? 'checked' : ''} />${escapeHtml(agentLabel(agent.agent_type))}</span>
      <em>${status}</em>
    </label>`
  }).join('') || t('ui.1m6fhil')
  updateInstallTargetCount()
}

const openInstallDialog = async (skill, initialQuery = '', targetAgentType = '', reinstallSkill = null) => {
  const agents = (inventory?.agents || []).filter(item => installedAgent(item) && item.skill_management_supported && item.skills_path?.trim() && item.capabilities?.path_available !== false && (!targetAgentType || item.agent_type === targetAgentType))
  if (!agents.length) return showMessageDialog(t('ui.1rloj41'), t('ui.k8dvfk'))
  lockedInstallSkill = skill || null
  installAgentContext = targetAgentType
  installCatalog = []
  $('#install-target-count').textContent = ''
  installVersions = []
  $('#install-skill-search').value = initialQuery
  $('#install-skill-search-label').hidden = Boolean(skill || reinstallSkill)
  $('#install-skill-title').textContent = reinstallSkill ? t('ui.agentManagement.reinstall_title').replace('{name}', reinstallSkill.name) : skill ? tf`安装 ${skill.name} 到其他 Agent` : t('ui.c0s9l')
  $('#install-platform-skill').disabled = true
  $('#install-platform-skill').innerHTML = `<option value="">${skill ? escapeHtml(skill.name) : t('ui.12x34mh')}</option>`
  $('#install-platform-version').disabled = true
  $('#install-platform-version').innerHTML = `<option value="">${t('请先选择 Skill')}</option>`
  $('#install-agent-targets').innerHTML = t('ui.hola4k')
  $('#install-skill-dialog').showModal()
  try {
    installCatalog = await loadInstallCatalog(agents, initialQuery, skill)
    if (reinstallSkill) {
      const matches = installSkills().filter(item => reinstallSkill.skill_id ? item.skill_id === reinstallSkill.skill_id : item.name === reinstallSkill.name)
      if (matches.length !== 1) {
        $('#install-skill-dialog').close()
        return showMessageDialog(t('ui.agentManagement.reinstall_missing'), t(matches.length ? 'ui.agentManagement.reinstall_ambiguous' : 'ui.agentManagement.reinstall_unavailable').replace('{name}', reinstallSkill.name))
      }
      skill = matches[0]
      lockedInstallSkill = skill
    }
    if (skill) {
      $('#install-platform-skill').innerHTML = `<option value="${escapeHtml(skill.skill_id)}">${escapeHtml(skill.name)}</option>`
      $('#install-platform-skill').value = skill.skill_id
      $('#install-platform-skill').disabled = true
      renderInstallTargets()
      loadInstallSkillVersions()
    } else {
      $('#install-platform-skill').disabled = false
      renderInstallSkillOptions()
    }
  } catch (error) {
    $('#install-skill-dialog').close()
    showMessageDialog(t('ui.w3jfjg'), String(error))
  }
}

$('#platform-install-button').addEventListener('click', () => openInstallDialog())
$('#install-skill-search').addEventListener('input', () => {
  clearTimeout(installSearchTimer)
  installSearchTimer = setTimeout(async () => {
    const query = $('#install-skill-search').value.trim()
    const agents = (inventory?.agents || []).filter(item => installedAgent(item) && item.skill_management_supported)
    $('#install-platform-skill').disabled = true
    $('#install-platform-skill').innerHTML = t('ui.gii72j')
    try {
      const result = await loadInstallCatalog(agents, query)
      if ($('#install-skill-search').value.trim() !== query) return
      installCatalog = result
      $('#install-platform-skill').disabled = false
      renderInstallSkillOptions()
    } catch (error) {
      $('#install-platform-skill').innerHTML = t('ui.1knpwiu')
      showMessageDialog(t('ui.11vz1mg'), String(error))
    }
  }, 300)
})
$('#install-platform-skill').addEventListener('change', () => {
  renderInstallTargets()
  loadInstallSkillVersions()
})
$('#install-platform-version').addEventListener('change', () => { updateInstallTargetCount(); loadInstallSkillPreview() })
$('#cancel-install-skill').addEventListener('click', () => {
  lockedInstallSkill = null
  $('#install-skill-dialog').close()
})
let platformInstallBusy = false
$('#confirm-install-skill').addEventListener('click', async event => {
  if (platformInstallBusy) return
  const skill = selectedInstallSkill()
  if (!skill) return showMessageDialog(t('ui.1xx9z2h'), t('ui.5bo4oh'))
  const targets = [...document.querySelectorAll('[data-install-target]:checked')].map(item => item.value)
  if (!targets.length) return showMessageDialog(t('ui.1titnia'), t('ui.1ybbgmr'))
  const versionId = $('#install-platform-version').value
  if (!versionId) return showMessageDialog('请选择可信版本', '恢复或安装必须绑定一个可信版本。')
  platformInstallBusy = true
  const button = event.currentTarget
  setBusy(button, true)
  const succeeded = []
  const failed = []
  try {
    for (const agentType of targets) {
      try {
        await installPlatformSkill(agentType, skill.skill_id, '', versionId)
        succeeded.push(agentLabel(agentType))
      } catch (error) {
        failed.push(`${agentLabel(agentType)}：${runtimeText(error)}`)
      }
    }
    await refreshAfterInstall()
    lockedInstallSkill = null
    $('#install-skill-dialog').close()
    showMessageDialog(!succeeded.length ? t('ui.v4sbw9') : failed.length ? t('ui.i22ked') : t('ui.1br1zwn'), [
      succeeded.length ? tf`${skill.name} 已安装到：${formatList(succeeded)}。` : '',
      failed.length ? tf`未安装：\n${failed.join('\n')}` : t('ui.o11sy8'),
    ].filter(Boolean).join('\n'))
  } catch (error) {
    showMessageDialog(t('ui.12x45mj'), tf`安装命令已经执行，但页面状态刷新失败：${runtimeText(error)}`)
    log(error)
  } finally {
    platformInstallBusy = false
    setBusy(button, false)
  }
})

function renderCapability(selector, capability) {
  const element = $(selector)
  const enabled = Boolean(capability?.enabled)
  element.className = enabled ? 'available' : 'unavailable'
  element.textContent = enabled ? tf`已启用${capability.detail ? ` · ${runtimeText(capability.detail)}` : ''}` : t('ui.n1gs62')
}

function escapeHtml(value) {
  const node = document.createElement('span')
  node.textContent = String(value ?? '')
  return node.innerHTML
}

invoke('get_build_version').then(version => {
  clientBuildVersion = version
  window.clientDiagnostics?.started(version)
  $('#client-build-version').textContent = tf`版本 ${version}`
  syncSettingsControls()
})
const initializeClient = async () => {
  try {
    const result = JSON.parse(await run('reconcile-service'))
    if (result.restarted) log(t('ui.1gpi43u'))
  } catch (error) {
    log(tf`后台服务自检失败：${error}`)
  }
  await refreshConnection()
  if (connection?.configured && document.querySelector('.panel.active')?.id === 'connect' && document.querySelector(`#${clientSettings.defaultPanel}`)) {
    showPanel(clientSettings.defaultPanel)
  }
}
initializeClient()
setInterval(refreshChangedInventory, 3000)
setInterval(checkClientUpdateAutomatically, CLIENT_UPDATE_CHECK_INTERVAL_MS)
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    refreshChangedInventory()
    checkClientUpdateAutomatically()
  }
})
window.addEventListener('agent-manager-client-locale-change', async () => {
  const activePanel = document.querySelector('.panel.active')?.id || 'connect'
  if (activePanel === 'records') void loadRecordHistory()
  $('#panel-title').textContent = panelTitle(activePanel)
  if (inventory) renderInventory()
  if (builtinAgentSettings.length) renderBuiltinAgentSettings()
  if (pendingItems.length) {
    await loadPending()
  }
  if (connection) {
    renderConnected(connection)
    renderStatus(connection)
  } else {
    renderDisconnected()
  }
  if ($('#quarantine-list').children.length) await loadQuarantine()
  if ($('#install-skill-dialog')?.open) {
    renderInstallSkillOptions()
    renderInstallTargets()
  }
  syncSettingsControls()
})
