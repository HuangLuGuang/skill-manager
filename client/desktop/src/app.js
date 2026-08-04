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
let currentTakeoverTitle = t('ui.1aqrn47')
const panelTitle = panel => ({
  connect: t('ui.wu8jgp'),
  discover: t('ui.zg9dnv'),
  takeover: currentTakeoverTitle,
  status: t('ui.1ihgm6s'),
  notifications: t('ui.1atia5p'),
  records: t('ui.cn5hhp'),
  settings: t('设置'),
}[panel] || panel)
let inventory = null
let connection = null
let selectedSkillPaths = new Set()
let takeoverReady = false
let installCatalog = []
let installVersions = []
let lockedInstallSkill = null
let installSearchTimer = null
let lastInventoryAt = ''
let takeoverLoadedAt = ''
let previewSelectionKey = ''
let takeoverLoading = false
let autoRefreshBusy = false
let notificationFilter = 'all'
let customAgentPendingRemoval = null
let builtinAgentSettings = []
let editingBuiltinAgent = null
let pendingItems = []
let pendingDiscardItem = null
let pendingRefreshTimer = null
let pendingRefreshBusy = false
let pendingSubmissionBusy = false
let pendingBatchTracking = null
const pendingPlatformVersionCache = new Map()
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
    return { ...DEFAULT_CLIENT_SETTINGS, ...JSON.parse(localStorage.getItem(CLIENT_SETTINGS_KEY) || '{}') }
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
  $('#settings-language').value = window.clientI18n?.getLocale?.() || 'zh-CN'
  $('#settings-default-panel').value = clientSettings.defaultPanel
  $('#settings-system-notifications').checked = clientSettings.systemNotifications
  $('#settings-notification-level').value = clientSettings.notificationLevel
  $('#settings-notification-level').disabled = !clientSettings.systemNotifications
  $('#settings-auto-update').checked = clientSettings.autoCheckUpdates
  $('#settings-update-channel').value = clientSettings.updateChannel
  $('#settings-background-service').checked = Boolean(connection?.service_installed)
  $('#settings-background-service').disabled = !connection?.configured
  $('#settings-service-detail').textContent = !connection?.configured
    ? t('请先完成客户端接入。')
    : connection.service_running
      ? t('后台治理服务正在运行，并会在登录系统后自动启动。')
      : connection.service_installed
        ? t('后台治理服务已安装，但当前未运行。')
        : t('后台治理服务未安装，不会在登录系统后自动启动。')
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
  $('#status-last-operation').textContent = `${t('ui.png61n')}：${new Date().toLocaleTimeString(window.clientI18n?.getLocale?.() || 'zh-CN')} · ${runtimeText(value || t('ui.rxr1o0'))}`
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
  if (!button) return
  event.preventDefault()
  event.stopPropagation()
  setBusy(button, true)
  try {
    await invoke('reveal_path', { path: button.dataset.revealPath })
  } catch (error) {
    showMessageDialog(t('ui.17y2ac'), String(error))
  } finally {
    setBusy(button, false)
  }
})

const isCustomAgent = agent => Boolean(agent?.capabilities?.custom)
const isSharedSkills = agent => Boolean(agent?.capabilities?.shared_skills)

const showPanel = panel => {
  document.querySelectorAll('.nav-item, .panel').forEach(item => item.classList.remove('active'))
  document.querySelector(`.nav-item[data-panel="${panel}"]`)?.classList.add('active')
  $('#notification-trigger').classList.toggle('active', panel === 'notifications')
  $('#settings-trigger').classList.toggle('active', panel === 'settings')
  $(`#${panel}`).classList.add('active')
  $('#panel-title').textContent = panelTitle(panel)
  $('.workspace').scrollTop = 0
  if (panel === 'status') loadStatusPage()
  if (panel === 'notifications') refreshConnection()
  if (panel === 'records') refreshConnection()
  if (panel === 'settings') syncSettingsControls()
}

const showTakeoverError = error => {
  takeoverReady = false
  syncApplyState()
  $('#takeover-summary').hidden = true
  $('#takeover-result-note').hidden = true
  $('#takeover-actions').hidden = true
  $('#takeover-list').classList.remove('empty')
  $('#takeover-list').innerHTML = tf`<div class="inline-error"><strong>暂时无法生成预览</strong><span>${escapeHtml(runtimeText(error))}</span><button class="icon-button icon-back" data-back-to-discover>返回选择 Skill</button></div>`
  $('[data-back-to-discover]')?.addEventListener('click', () => showPanel('discover'))
  log(error)
}

document.querySelectorAll('.nav-item').forEach(button => {
  button.addEventListener('click', async () => {
    const panel = button.dataset.panel
    showPanel(panel)
    if (panel !== 'takeover' || !connection?.configured) return
    const inventoryKey = lastInventoryAt || 'current'
    if (takeoverLoadedAt === inventoryKey || takeoverLoading) return
    if (!takeoverLoadedAt) {
      $('#takeover-list').classList.add('empty')
      $('#takeover-list').textContent = t('ui.1pzntjl')
    }
    takeoverLoading = true
    startOperationProgress('#takeover-progress', {
      title: t('ui.7707sb'),
      detail: tf`正在读取 ${selectedSkillPaths.size} 个已选 Skill，并核对平台状态与内容签名。`,
    })
    try {
      await preview(false)
      updateSelectionSummary()
    } catch (error) {
      showTakeoverError(error)
    } finally {
      takeoverLoading = false
      stopOperationProgress('#takeover-progress')
    }
  })
})

const saveConnection = async ({ button, server, token, name, onSuccess }) => {
  setBusy(button, true)
  let saved = false
  try {
    const args = ['--server', server, '--token', token]
    if (name.trim()) args.push('--name', name.trim())
    log(await run('register', args))
    await run('configure', args)
    saved = true
    const service = JSON.parse(await run('service-status'))
    if (service.installed) {
      await run('prepare-update')
      await run('reconcile-service')
    }
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
  const sharedTargets = agents.filter(isSharedSkills)
  const platformAgents = platform.agents || []
  const platformByType = Object.fromEntries(platformAgents.map(agent => [agent.agent_type, agent]))
  const governableTargets = agents.filter(agent => agent.skill_management_supported)
  const supported = localAgents.filter(agent => agent.skill_management_supported)
  const bound = supported.filter(agent => platformByType[agent.agent_type]?.managed_agent_id)
  const strict = platform.governance_mode === 'strict'
  const managedSkills = platformAgents.reduce((count, agent) => count + (agent.skills || []).filter(skill => skill.skill_id).length, 0)
  const todos = []
  const local = data.local || {}
  const hasTakeover = (local.managed_skills || 0) + (local.pending_skills || 0) > 0
  const governanceEnabled = Boolean(local.governance_enabled)
  const agentsReady = governableTargets.length > 0 && (!strict || bound.length === supported.length)
  const scopeConfirmed = agentsReady && hasTakeover
  const patrolActive = scopeConfirmed && data.service_running && governanceEnabled
  const takeoverTitle = hasTakeover ? t('ui.1meon5z') : t('ui.1aqrn47')
  currentTakeoverTitle = takeoverTitle
  $('#takeover-nav-label').textContent = takeoverTitle
  $('#takeover-heading').textContent = takeoverTitle
  $('#takeover-description').textContent = hasTakeover
    ? t('ui.1xrvaa9')
    : t('ui.6igw3y')
  $('#takeover-state-badge').hidden = !hasTakeover
  $('#takeover-state-badge').className = `takeover-state-badge${governanceEnabled ? '' : ' paused'}`
  $('#takeover-state-badge').textContent = governanceEnabled ? t('ui.wxg0be') : t('ui.18d9dw')
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
  if (data.connected && hasTakeover && !data.service_running) {
    todos.push({
      title: data.service_installed ? t('ui.cewtrw') : t('ui.ur9dh5'),
      detail: runtimeText(data.service_detail || t('ui.17kvfer')),
      action: t('ui.1ox0viz'), actionType: 'install-service', error: data.service_installed,
    })
  }
  if (data.connected && data.service_running && local.managed_skills > 0 && !local.governance_enabled) {
    todos.push({ title: t('ui.1pm2mwm'), detail: t('ui.bj45l'), action: t('ui.g9imto'), panel: 'status' })
  }
  if ((local.quarantined_skills || 0) > 0) {
    todos.push({ title: tf`${skillCount(local.quarantined_skills)} 已隔离`, detail: t('ui.1jypd9c'), action: t('ui.fdodj6'), panel: 'status', error: true })
  }
  if ((local.pending_skills || 0) > 0) {
    todos.push({ title: tf`${skillCount(local.pending_skills)} 已停用待检测`, detail: t('ui.3rlwg5'), action: t('ui.11srxfq'), panel: 'takeover' })
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
  $('#overview-title').textContent = connectionError ? t('ui.gqjsy5') : t('ui.7t7yhn')
  $('#overview-subtitle').textContent = connectionError
    ? tf`${runtimeText(data.error || t('ui.cvy3o'))}。现有 Skill 不受影响。`
    : isEnglish()
      ? `${platform.name || data.name || data.inventory?.hostname || t('ui.13nfgz7')} · Connected to ${data.server}`
      : `${platform.name || data.name || data.inventory?.hostname || t('ui.13nfgz7')}已接入 ${data.server}`
  $('#overview-sync').textContent = connectionError ? t('ui.xhhfbd') : t('ui.2fhcc7')

  $('#metric-agents').textContent = localAgents.length
  $('#metric-bound').textContent = strict ? `${bound.length} / ${supported.length}` : `${supported.length} / ${supported.length}`
  $('#metric-bound-label').textContent = strict ? t('ui.1idv0ac') : t('ui.16k09ve')
  $('#metric-skills').textContent = local.managed_skills ?? managedSkills
  $('#metric-todos').textContent = todos.length
  $('#progress-summary').textContent = !data.connected
    ? t('ui.1e2g05i')
    : governableTargets.length === 0
      ? t('ui.w7oyqs')
      : strict && bound.length < supported.length
        ? tf`已发现 ${localAgents.length} 个 Agent，还有 ${supported.length - bound.length} 个需要绑定。`
        : !hasTakeover
          ? isEnglish()
            ? `${agentCount(localAgents.length)}${sharedTargets.length ? ' and shared Skills directories' : ''} discovered. Confirm the governance scope.`
            : tf`${localAgents.length} 个 Agent${sharedTargets.length ? t('ui.ysb7y1') : ''}已发现，请确认治理范围。`
          : !data.service_running
            ? t('ui.es4v92')
            : !governanceEnabled
              ? t('ui.1evu320')
              : isEnglish()
                ? `${agentCount(supported.length)}${sharedTargets.length ? ' and shared Skills directories' : ''} are under continuous governance.`
                : tf`${supported.length} 个 Agent${sharedTargets.length ? t('ui.tamedf') : ''}正在持续治理。`
  setProgress('step-connect', data.connected ? 'done' : 'current')
  setProgress('step-discover', governableTargets.length ? 'done' : data.connected ? 'current' : '')
  $('#step-bind span').textContent = strict ? t('ui.1jfg101') : t('ui.1220ih')
  setProgress('step-bind', scopeConfirmed ? 'done' : governableTargets.length ? 'current' : '')
  $('#step-service span').textContent = data.service_running && !governanceEnabled && hasTakeover ? t('ui.15hy02m') : t('ui.6tdt5u')
  setProgress('step-service', patrolActive ? 'done' : scopeConfirmed ? 'current' : '')

  $('#detail-service').textContent = data.service_running
    ? governanceEnabled && hasTakeover ? t('ui.1bywqik') : hasTakeover ? t('ui.uymdom') : t('ui.17y0wdd')
    : data.service_installed ? t('ui.wfa2b') : t('ui.buf4kb')
  $('#detail-policy').textContent = policyLabel(platform.policy_mode)
  $('#detail-governance').textContent = governanceLabel(platform.governance_mode)
  $('#detail-last-seen').textContent = formatTime(platform.last_seen_at)
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

  $('#todo-section').hidden = todos.length === 0
  $('#todo-list').innerHTML = todos.map((todo, index) => `
      <div class="todo-item${todo.error ? ' error' : ''}">
        <div><strong>${escapeHtml(todo.title)}</strong><span>${escapeHtml(todo.detail)}</span></div>
        <button class="icon-button icon-next" data-todo-index="${index}">${escapeHtml(todo.action)}</button>
      </div>`).join('')
  document.querySelectorAll('[data-todo-index]').forEach(button => {
    button.addEventListener('click', async () => {
      const todo = todos[Number(button.dataset.todoIndex)]
      if (todo.panel) return showPanel(todo.panel)
      if (todo.actionType === 'refresh') return refreshConnection()
      if (todo.actionType === 'install-service') {
        setBusy(button, true)
        try { log(await run('install-service')); await refreshConnection() } catch (error) { log(error) } finally { setBusy(button, false) }
      }
    })
  })
  syncSettingsControls()
}

const renderStatus = data => {
  const local = data?.local || {}
  const running = Boolean(data?.service_running)
  const installed = Boolean(data?.service_installed)
  const governanceEnabled = Boolean(local.governance_enabled)
  const findings = local.patrol_findings || []
  const issues = (local.quarantined_skills || 0) + (local.queued_events || 0) + findings.length
  $('#status-service-badge').className = `overview-badge${running ? '' : ' warning'}`
  $('#status-service-badge').textContent = running ? governanceEnabled ? t('ui.yp0d17') : t('ui.ihbpsu') : installed ? t('ui.ir5jv') : t('ui.1tylsuy')
  $('#status-service-title').textContent = running ? governanceEnabled ? t('ui.7cyhwh') : t('ui.1pm2mwm') : installed ? t('ui.1t069n1') : t('ui.1tsoz5i')
  $('#status-service-description').textContent = running
    ? governanceEnabled
      ? t('ui.1ur37ia')
      : t('ui.8prxjn')
    : installed ? runtimeText(data.service_detail || t('ui.lkjgbu')) : t('ui.c1pwr3')
  $('#install-service').hidden = running
  $('#install-service').textContent = installed ? t('ui.at9scf') : t('ui.r8dnq')
  $('#uninstall-service').hidden = !installed
  $('#toggle-governance').hidden = !local.managed_skills
  $('#toggle-governance').textContent = governanceEnabled ? t('ui.16zn63k') : t('ui.ebl6p3')
  $('#toggle-governance').className = `takeover-toggle icon-button ${governanceEnabled ? 'pause icon-pause' : 'resume icon-resume'}`
  $('#toggle-takeover').hidden = !local.managed_skills
  $('#toggle-takeover').textContent = governanceEnabled ? t('ui.1cm4u1t') : t('ui.m2imlu')
  $('#toggle-takeover').className = `takeover-toggle icon-button ${governanceEnabled ? 'pause icon-pause' : 'resume icon-resume'}`
  $('#run-once').disabled = !governanceEnabled
  $('#run-once').title = governanceEnabled ? '' : t('ui.9qicf')
  $('#status-last-scan').textContent = formatTime(local.last_full_scan_at)
  $('#status-next-scan').textContent = governanceEnabled && running ? formatTime(local.next_full_scan_at) : '-'
  $('#status-managed-count').textContent = local.managed_skills || 0
  $('#status-quarantine-count').textContent = local.quarantined_skills || 0
  $('#status-queued-count').textContent = local.queued_events || 0
  $('#status-attention').className = `status-attention${issues ? ' warning' : ' ok'}`
  $('#status-attention-text').textContent = findings.length
    ? tf`最近巡检发现 ${findings.length} 个异常：${formatList(findings.map(item => item.skill_name))}。`
    : issues
    ? tf`需要处理：${local.quarantined_skills || 0} 个隔离项、${local.queued_events || 0} 条待补报事件。`
    : t('ui.19y0h48')
  const localTasks = local.tasks || []
  const localTasksByID = new Map(localTasks.map(task => [task.id, task]))
  const tasks = data?.platform?.tasks?.length
    ? data.platform.tasks.map(task => {
      const executed = localTasksByID.get(task.id)
      return executed ? { ...task, status: executed.status, error: executed.error, updated_at: executed.updated_at } : task
    })
    : localTasks
  renderTaskHistory(tasks)
  renderEventHistory(data?.platform?.events || [])
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
    <button class="notification-item ${escapeHtml(item.severity)}${item.read_at ? '' : ' unread'}" data-notification-id="${item.id}" data-notification-panel="${action.panel}">
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
    $('#system-notification-state').classList.remove('success')
    $('#system-notification-state').hidden = false
    $('#system-notification-state').textContent = runtimeText(error)
  }
}

const notificationSeverity = severity => t(
  ({ critical: t('ui.s9cfpz'), warning: t('ui.1uwa1ih'), info: t('ui.1ltzzrr') }[severity] || t('ui.1hx7jj')),
)
const notificationAction = eventType => ({
  skill_quarantined: { panel: 'status', label: t('ui.fdodj6') },
  unmanaged_skill_found: { panel: 'takeover', label: t('ui.hrqy3h') },
  skill_modified: { panel: 'status', label: t('ui.g9imto') },
  skill_repaired: { panel: 'records', label: t('ui.13q7xte') },
  skill_auto_installed: { panel: 'records', label: t('ui.13q7xte') },
  skill_auto_install_failed: { panel: 'takeover', label: t('ui.hrqy3h') },
  connection_changed_governance_paused: { panel: 'connect', label: t('ui.ox3r68') },
}[eventType] || { panel: 'records', label: t('ui.ox3r68') })

const localizedNotification = item => {
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
      en: ['Skill Content Changed', `${target} differs from the platform-approved version. Review Runtime Status.`],
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
    <strong class="task-status-${eventStatus(event.event_type)}">${escapeHtml(eventResultLabel(event.event_type))}</strong>
    <span>${escapeHtml(formatTime(event.created_at))}</span>
  </div>`).join('') : t('ui.1tbkycy')
}

const renderTaskHistory = tasks => {
  const element = $('#task-history-list')
  element.classList.toggle('empty', !tasks.length)
  element.innerHTML = tasks.length ? tasks.map(task => {
    const payload = task.payload || {}
    const policySync = task.task_type === 'sync_policy' || (task.task_type === 'rescan' && payload.reason === 'policy_changed')
    const target = policySync
      ? tf`处置：${policyLabel(payload.mode)} · 治理：${governanceLabel(payload.governance_mode)}`
      : payload.skill_name || payload.skill_id || (task.task_type === 'rescan' ? t('ui.1agolmk') : '-')
    return `<div class="takeover-row task-history-row">
      <div><strong>${escapeHtml(taskTypeLabel(task))}</strong><p>${escapeHtml(target)}</p></div>
      <span>${escapeHtml(payload.agent_type ? agentLabel(payload.agent_type) : t('ui.13nfgz7'))}</span>
      <strong class="task-status-${escapeHtml(task.status)}">${escapeHtml(taskStatusLabel(task.status))}</strong>
      <span class="${task.error ? 'task-history-error' : ''}">${escapeHtml(`${formatTime(task.finished_at || task.started_at || task.updated_at || task.created_at)}${task.error ? ` · ${runtimeText(task.error)}` : ''}`)}</span>
    </div>`
  }).join('') : t('ui.2jt1e6')
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
    const taskChanged = local.tasks?.[0]?.updated_at !== connection.local?.tasks?.[0]?.updated_at
    const notificationChanged = local.notifications?.[0]?.id !== connection.local?.notifications?.[0]?.id || local.unread_notifications !== connection.local?.unread_notifications
    const quarantineChanged = local.quarantined_skills !== connection.local?.quarantined_skills
    const refreshQuarantine = $('#status').classList.contains('active')
    if ((!changedAt || changedAt === lastInventoryAt) && !taskChanged && !notificationChanged && !quarantineChanged) return
    if (changedAt === lastInventoryAt) {
      connection.local = local
      renderStatus(connection)
      if (refreshQuarantine) await loadQuarantine()
      return
    }
    const refreshTakeover = $('#takeover').classList.contains('active')
    await refreshConnection()
    if (refreshTakeover) await preview(false)
    if (refreshQuarantine) await loadQuarantine()
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

const renderInventory = () => {
  if (!inventory?.agents) return
  const bindings = Object.fromEntries((connection?.platform?.agents || []).map(agent => [agent.agent_type, agent.managed_agent_id || '']))
  const strict = connection?.platform?.governance_mode === 'strict'
  const availableAgents = connection?.platform?.available_managed_agents || []
  selectedSkillPaths = new Set(inventory.agents.flatMap(agent => agent.skills || []).filter(skill => !skill.error).map(skill => skill.path))
  takeoverReady = false
  $('#takeover-ack').checked = false
  syncApplyState()
  $('#agent-list').classList.remove('empty')
  $('#agent-list').innerHTML = inventory.agents.length
    ? inventory.agents.map(agent => {
      const compatible = isCustomAgent(agent)
        ? availableAgents
        : availableAgents.filter(item => agentKind(item.channel) === agentKind(agent.agent_type))
      const binding = bindings[agent.agent_type] || ''
      const shared = isSharedSkills(agent)
      const readers = agent.capabilities?.shared_skill_readers || []
      const requiresBinding = agent.skill_management_supported && strict && !shared
      return `
        <details class="agent-card${shared ? ' shared-skills-card' : ''}">
          <summary class="agent-summary">
            <div class="agent-name"><span class="entity-badge">${shared ? t('ui.6m4yak') : 'Agent'}</span><div><strong>${escapeHtml(agentLabel(agent.agent_type))}</strong><small title="${escapeHtml(agent.skills_path || t('ui.1d2upau'))}">${escapeHtml(agent.skills_path || t('ui.1d2upau'))}</small></div></div>
            <div class="capability ${agent.skill_management_supported ? 'supported' : ''}">
              ${agent.skill_management_supported
                ? tf`${skillCount(agent.skills.length)}${shared ? t('ui.1x0ngfg') : ''}${agent.skills.filter(skill => skill.error).length ? tf` · ${agent.skills.filter(skill => skill.error).length} 个待校验` : ''}`
                : t('ui.9694e6')}
            </div>
            <span class="fold-label">${agent.skill_management_supported ? t('ui.172hsfg') : t('ui.1gnqr2m')}</span>
          </summary>
          ${shared ? tf`<div class="shared-skills-note"><strong>这是共用目录，不计入 Agent 数量</strong><span>${escapeHtml(formatList(readers) || t('ui.waagmd'))} 可能读取其中的 Skill，实际以各 Agent 的版本和配置为准；共用目录仅执行状态与内容完整性治理，无法据此识别具体调用方。</span></div>` : ''}
          ${requiresBinding || isCustomAgent(agent)
            ? `<div class="agent-settings">${requiresBinding ? tf`<label class="mapping">平台智能体<select data-agent="${escapeHtml(agent.agent_type)}"><option value="">请选择</option>${compatible.map(item => `<option value="${escapeHtml(item.agent_id)}" ${item.agent_id === binding ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}</select></label>` : ''}${isCustomAgent(agent) ? tf`<button class="custom-agent-remove icon-button icon-remove" type="button" title="只取消本地登记，不删除 Skill 文件" data-remove-custom-agent="${escapeHtml(agent.agent_type)}" data-custom-agent-name="${escapeHtml(agent.display_name)}">取消登记</button>` : ''}</div>`
            : ''}
          ${agent.skill_management_supported ? `<div class="skill-inventory">${agent.skills.length ? agent.skills.map(skill => tf`
            <div class="skill-row">
              <div class="skill-row-main">
                <input type="checkbox" aria-label="选择 ${escapeHtml(skill.name)}" data-skill-path="${escapeHtml(skill.path)}" ${skill.error ? 'disabled' : 'checked'} />
                <span>
                  <strong>${escapeHtml(skill.name)}</strong>
                  <button class="path-link" type="button" title="${escapeHtml(skill.path)}" data-reveal-path="${escapeHtml(skill.path)}">${escapeHtml(skill.path)}</button>
                </span>
              </div>
              <div class="skill-row-actions">
                <em class="${skill.error ? 'warning' : 'ok'}">${skill.error ? t('ui.titry') : skill.skill_id ? t('ui.wd1ghx') : t('ui.zbxgqi')}</em>
                ${skill.skill_id && !skill.error ? tf`<button class="icon-button icon-install" type="button" data-install-other="${escapeHtml(skill.skill_id)}" data-skill-name="${escapeHtml(skill.name)}" data-source-agent="${escapeHtml(agent.agent_type)}">安装到其他 Agent</button>` : ''}
              </div>
            </div>`).join('') : t('ui.1nq630h')}</div>` : ''}
        </details>`
    }).join('')
    : t('ui.1o0lsp0')
  document.querySelectorAll('[data-skill-path]').forEach(input => input.addEventListener('change', () => {
    if (input.checked) selectedSkillPaths.add(input.dataset.skillPath)
    else selectedSkillPaths.delete(input.dataset.skillPath)
    updateSelectionSummary()
  }))
  document.querySelectorAll('[data-install-other]').forEach(button => button.addEventListener('click', () => {
    openInstallDialog({ skill_id: button.dataset.installOther, name: button.dataset.skillName, source_agent_type: button.dataset.sourceAgent })
  }))
  document.querySelectorAll('[data-remove-custom-agent]').forEach(button => button.addEventListener('click', async () => {
    customAgentPendingRemoval = {
      agentType: button.dataset.removeCustomAgent,
      name: button.dataset.customAgentName,
    }
    $('#remove-custom-agent-name').textContent = customAgentPendingRemoval.name
    $('#remove-custom-agent-dialog').showModal()
  }))
  updateSelectionSummary()
}

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

const updateSelectionSummary = () => {
  $('#discover-next').hidden = !inventory?.agents?.some(agent => agent.skill_management_supported)
  const previewButton = $('#open-preview-button')
  const discoveredSkills = [...document.querySelectorAll('[data-skill-path]')]
  const unavailableCount = discoveredSkills.filter(input => input.disabled).length
  const selectableCount = discoveredSkills.length - unavailableCount
  previewButton.disabled = selectedSkillPaths.size === 0
  $('#selection-heading').textContent = t('ui.1tcut2')
  $('#selection-guidance').innerHTML = selectableCount === 0
    ? unavailableCount
      ? tf`发现 ${unavailableCount} 个不可用 Skill。请展开 Agent 查看原因；平台恢复和安装请前往 Skill 治理。`
      : t('ui.mzo6ro')
    : tf`已选择 <b id="selected-skill-count">${selectedSkillPaths.size}</b> ${skillCount(selectedSkillPaths.size).replace(/^\d+\s*/, '')}，生成预览后可查看哪些继续启用、哪些需要处理。`
  const currentKey = JSON.stringify([lastInventoryAt, [...selectedSkillPaths].sort()])
  previewButton.textContent = selectableCount === 0
    ? t('ui.78yft3')
    : !previewSelectionKey
      ? t('ui.mxuy7s')
      : previewSelectionKey === currentKey
        ? t('ui.14bf9qb')
        : t('ui.443oyz')
  previewButton.title = selectableCount === 0
    ? t('ui.10c2cz2')
    : selectedSkillPaths.size === 0
      ? t('ui.k57bdv')
      : previewButton.textContent
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

const mappingArgs = () => [...document.querySelectorAll('[data-agent]')]
  .filter(input => input.value.trim())
  .flatMap(input => ['--agent', `${input.dataset.agent}=${input.value.trim()}`])

const preview = async (confirm, showNoChange = false) => {
  if (!document.querySelector('[data-skill-path]')) await discover()
  const args = mappingArgs()
  const selectedAgentSkills = (inventory?.agents || [])
    .filter(agent => !isSharedSkills(agent))
    .some(agent => (agent.skills || []).some(skill => selectedSkillPaths.has(skill.path)))
  if (connection?.platform?.governance_mode === 'strict' && selectedAgentSkills && !args.length) {
    throw new Error(t('ui.1pu7ifd'))
  }
  const selected = [...selectedSkillPaths]
  if (!selected.length) {
    $('#manage-count').textContent = '0'
    $('#pending-count').textContent = '0'
    $('#takeover-summary').hidden = true
    $('#takeover-result-note').hidden = !showNoChange
    $('#takeover-result-note').textContent = t('ui.scaie8')
    $('#takeover-list').classList.add('empty')
    $('#takeover-list').textContent = t('ui.1prcba7')
    takeoverReady = false
    $('#takeover-actions').hidden = true
    takeoverLoadedAt = lastInventoryAt || 'current'
    await loadPending()
    return ''
  }
  selected.forEach(path => args.push('--skill', path))
  if (confirm) args.push('--confirm')
  const output = await run('takeover', args)
  if (confirm) {
    return output
  }
  const plan = JSON.parse(output)
  const manage = plan.items.filter(item => item.action === 'manage').length
  const managed = plan.items.filter(item => item.action === 'managed').length
  const pending = plan.items.filter(item => item.action === 'pending').length
  const hasChanges = manage > 0 || pending > 0
  $('#takeover-summary').hidden = !hasChanges
  $('#takeover-result-note').hidden = !hasChanges && !showNoChange
  $('#takeover-result-note').textContent = !hasChanges
    ? t('ui.1qtolsc')
    : managed
      ? tf`已接管 ${skillCount(managed)}；仅新增或状态异常的 Skill 需要处理。`
      : t('ui.19jaci3')
  $('#manage-count').textContent = manage
  $('#pending-count').textContent = pending
  $('#takeover-feedback').hidden = true
  $('#takeover-list').classList.remove('empty')
  $('#takeover-list').innerHTML = plan.items.length
    ? groupTakeoverItems(plan.items).map(group => {
      const enabled = group.items.filter(item => item.action === 'manage').length
      const existing = group.items.filter(item => item.action === 'managed').length
      const pendingItems = group.items.filter(item => item.action === 'pending').length
      return tf`<details class="takeover-agent">
        <summary class="takeover-agent-summary">
          <div class="takeover-agent-name"><span class="entity-badge">Agent</span><strong>${escapeHtml(agentLabel(group.agentType))}</strong></div>
          <span>${skillCount(group.items.length)}${existing ? tf` · ${existing} 个已接管` : ''}${enabled ? tf` · ${enabled} 个待接管` : ''}${pendingItems ? tf` · ${pendingItems} 个停用` : ''}</span>
          <em>展开 / 收起</em>
        </summary>
        <div class="takeover-agent-items">
          <div class="takeover-column-head"><span>Skill</span><span>接管后状态</span><span>判断依据</span><span>操作</span></div>
          ${group.items.map(item => `
          <div class="takeover-row">
            <div><strong>${escapeHtml(item.name)}</strong><button class="path-link" type="button" title="${escapeHtml(item.source)}" data-reveal-path="${escapeHtml(item.source)}">${escapeHtml(item.source)}</button></div>
            <span class="result-status status-${item.action}"><i></i>${item.action === 'managed' ? t('ui.yxyw4j') : item.action === 'manage' ? t('ui.zbxgqi') : t('ui.6q9o5l')}</span>
            <span>${escapeHtml(reasonLabel(item.reason))}</span>
            ${['manage', 'managed'].includes(item.action) && item.skill_id ? tf`<button class="icon-button icon-install" type="button" data-install-preview="${escapeHtml(item.skill_id)}" data-skill-name="${escapeHtml(item.name)}" data-source-agent="${escapeHtml(item.agent_type)}">安装到其他 Agent</button>` : '<span>-</span>'}
          </div>`).join('')}
        </div>
      </details>`
    }).join('')
    : t('ui.n4bxkk')
  takeoverReady = plan.items.some(item => item.action !== 'managed')
  document.querySelectorAll('[data-install-preview]').forEach(button => button.addEventListener('click', () => {
    openInstallDialog({ skill_id: button.dataset.installPreview, name: button.dataset.skillName, source_agent_type: button.dataset.sourceAgent })
  }))
  $('#takeover-ack').checked = false
  $('#takeover-actions').hidden = !takeoverReady
  takeoverLoadedAt = lastInventoryAt || 'current'
  previewSelectionKey = JSON.stringify([lastInventoryAt, [...selectedSkillPaths].sort()])
  syncApplyState()
  await loadPending()
}

const groupTakeoverItems = items => {
  const groups = new Map()
  items.forEach(item => {
    if (!groups.has(item.agent_type)) groups.set(item.agent_type, [])
    groups.get(item.agent_type).push(item)
  })
  return [...groups].map(([agentType, groupItems]) => ({ agentType, items: groupItems }))
}

const syncApplyState = () => {
  $('#apply-button').disabled = !takeoverReady || !$('#takeover-ack').checked
}

const showTakeoverFeedback = (type, title, detail) => {
  const element = $('#takeover-feedback')
  element.hidden = false
  element.className = `takeover-feedback ${type}`
  element.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span>`
}

const generateAndOpenPreview = async (button, force = false) => {
  if (takeoverLoading) return
  const currentKey = JSON.stringify([lastInventoryAt, [...selectedSkillPaths].sort()])
  if (!force && previewSelectionKey === currentKey) return showPanel('takeover')
  takeoverLoading = true
  showPanel('takeover')
  startOperationProgress('#takeover-progress', {
    title: t('ui.7707sb'),
    detail: tf`正在读取 ${selectedSkillPaths.size} 个已选 Skill，并核对平台状态与内容签名。`,
  })
  setBusy(button, true)
  try {
    await preview(false, true)
  } catch (error) {
    showTakeoverError(error)
  } finally {
    takeoverLoading = false
    stopOperationProgress('#takeover-progress')
    setBusy(button, false)
    updateSelectionSummary()
  }
}

$('#preview-button').addEventListener('click', async event => {
  await generateAndOpenPreview(event.currentTarget, true)
})
$('#open-preview-button').addEventListener('click', async event => {
  return generateAndOpenPreview(event.currentTarget)
})
$('#takeover-ack').addEventListener('change', syncApplyState)
$('#apply-button').addEventListener('click', async event => {
  if (!takeoverReady) return showTakeoverError(t('ui.mupilr'))
  const button = event.currentTarget
  const managedCount = Number($('#manage-count').textContent) || 0
  const pendingCount = Number($('#pending-count').textContent) || 0
  showTakeoverFeedback('processing', t('ui.1wihumr'), t('ui.jksjyl'))
  startOperationProgress('#takeover-progress', {
    title: t('ui.1wihumr'),
    detail: tf`正在备份并处理 ${skillCount(managedCount + pendingCount)}，请不要关闭客户端。`,
  })
  $('#takeover-feedback').scrollIntoView({ behavior: 'smooth', block: 'center' })
  setBusy(button, true)
  try {
    await preview(true)
    takeoverReady = false
    $('#takeover-summary').hidden = true
    $('#takeover-result-note').hidden = true
    $('#takeover-ack').checked = false
    $('#takeover-actions').hidden = true
    log(tf`接管完成：纳入管理 ${managedCount} 个，停用 ${pendingCount} 个`)
    await refreshConnection()
    const detail = tf`已纳入管理 ${managedCount} 个，可继续使用；已停用 ${pendingCount} 个，已移入下方待处理区。客户端将持续巡检，接管前内容已备份。`
    $('#takeover-result-note').textContent = t('ui.teyp42')
    showTakeoverFeedback('success', t('ui.1nqsn'), detail)
    showMessageDialog(t('ui.1nqsn'), detail)
  } catch (error) {
    showTakeoverFeedback('error', t('ui.x6xsih'), error)
    log(error)
  } finally {
    stopOperationProgress('#takeover-progress')
    setBusy(button, false)
    syncApplyState()
  }
})

const pendingStatusTerminal = status => ['APPROVED', 'REJECTED', 'CANCELLED'].includes(status)
const pendingNeedsRefresh = item => Boolean(item.skill_id) && !pendingStatusTerminal(item.status)
const pendingCanSubmit = item => !item.skill_id

const renderPendingBatchStatus = () => {
  if (!pendingBatchTracking) return
  const element = $('#pending-batch-status')
  const counts = { detecting: 0, review: 0, approved: 0, rejected: 0, cancelled: 0 }
  pendingBatchTracking.ids.forEach(id => {
    const item = pendingItems.find(candidate => candidate.id === id)
    if (item) pendingBatchTracking.statuses.set(id, item.status)
    const status = item?.status || pendingBatchTracking.statuses.get(id) || 'submitted'
    if (status === 'VETTED') counts.review += 1
    else if (status === 'APPROVED') counts.approved += 1
    else if (status === 'REJECTED') counts.rejected += 1
    else if (status === 'CANCELLED') counts.cancelled += 1
    else counts.detecting += 1
  })
  const total = pendingBatchTracking.ids.size
  const resolved = total - counts.detecting
  const finished = counts.detecting === 0 && counts.review === 0
  element.hidden = false
  element.className = `takeover-feedback ${finished ? counts.rejected || counts.cancelled ? 'error' : 'success' : 'processing'}`
  const title = counts.detecting
    ? tf`本批检测进度：已出结果 ${resolved}/${total}`
    : counts.review
      ? tf`自动检测已完成：${counts.review} 个待审核`
      : t('ui.1iebqkf')
  element.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml([
    tf`检测中 ${counts.detecting}`,
    tf`待审核 ${counts.review}`,
    tf`已批准 ${counts.approved}`,
    tf`未通过 ${counts.rejected}`,
    counts.cancelled ? tf`已取消 ${counts.cancelled}` : '',
  ].filter(Boolean).join(' · '))}</span>`
}

const pendingBatchIsActive = () => {
  if (!pendingBatchTracking) return false
  return [...pendingBatchTracking.ids].some(id => {
    const item = pendingItems.find(candidate => candidate.id === id)
    const status = item?.status || pendingBatchTracking.statuses.get(id) || 'submitted'
    return !pendingStatusTerminal(status)
  })
}

const syncPendingBatchControls = () => {
  const eligible = pendingItems.filter(pendingCanSubmit)
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
  const activeAnalysis = items.some(item => pendingNeedsRefresh(item) && item.status !== 'VETTED')
  pendingRefreshTimer = setTimeout(async () => {
    if (document.hidden || pendingRefreshBusy || pendingSubmissionBusy) {
      schedulePendingRefresh(pendingItems)
      return
    }
    try {
      await loadPending(true, { silent: true })
    } catch (error) {
      log(tf`刷新检测状态失败：${error}`)
      schedulePendingRefresh(pendingItems)
    }
  }, activeAnalysis ? 3000 : 10000)
}

const pendingPlatformVersionFor = async (item, force = false) => {
  if (!connection?.connected || !item.skill_id || item.status === 'APPROVED') return null
  const agent = (inventory?.agents || []).find(candidate => candidate.agent_type === item.agent_type && candidate.skill_management_supported)
  if (!agent) return null
  const cacheKey = `${item.agent_type}:${managedAgentIDFor(item.agent_type)}:${item.skill_id}`
  const cached = pendingPlatformVersionCache.get(cacheKey)
  if (!force && cached && cached.expiresAt > Date.now()) return cached.value
  const result = await exactAvailableSkillForAgent(agent, { skill_id: item.skill_id, name: item.skill_name })
  const trusted = result.items.find(candidate => candidate.skill_id === item.skill_id && candidate.version_id)
    || result.items.find(candidate => candidate.version_id)
    || null
  const value = trusted ? {
    skill_id: trusted.skill_id || item.skill_id,
    version_id: trusted.version_id,
    version_no: trusted.version_no || 0,
  } : null
  pendingPlatformVersionCache.set(cacheKey, { value, expiresAt: Date.now() + 10000 })
  return value
}

const enrichPendingPlatformVersions = async (items, force = false) => Promise.all(items.map(async item => {
  if (item.status === 'APPROVED') {
    return {
      ...item,
      platform_skill_id: item.skill_id,
      platform_version_id: item.version_id || '',
      platform_installable: Boolean(item.skill_id),
    }
  }
  try {
    const trusted = await pendingPlatformVersionFor(item, force)
    return trusted ? {
      ...item,
      platform_skill_id: trusted.skill_id,
      platform_version_id: trusted.version_id,
      platform_version_no: trusted.version_no,
      platform_installable: true,
    } : item
  } catch (error) {
    log(tf`平台可信版本读取失败：${item.skill_name} · ${runtimeText(error)}`)
    return item
  }
}))

const pendingPlatformInstallTitle = item => item.platform_version_no
  ? tf`安装平台可信版本 v${item.platform_version_no}`
  : t('从平台安装 Skill')

const loadPending = async (refresh = false, { silent = false } = {}) => {
  if (refresh && pendingRefreshBusy) return pendingItems
  if (refresh) pendingRefreshBusy = true
  let items
  try {
    items = JSON.parse(await run(refresh ? 'refresh-pending' : 'pending'))
  } finally {
    if (refresh) pendingRefreshBusy = false
  }
  items = await enrichPendingPlatformVersions(items, refresh && !silent)
  pendingItems = items
  renderPendingBatchStatus()
  for (const id of [...selectedPendingIDs]) {
    if (!items.some(item => item.id === id && pendingCanSubmit(item))) selectedPendingIDs.delete(id)
  }
  $('#pending-list').classList.toggle('empty', !items.length)
  $('#pending-list').innerHTML = items.length
    ? groupTakeoverItems(items.map(item => ({ ...item, agent_type: item.agent_type }))).map(group => tf`
      <details class="takeover-agent" open>
        <summary class="takeover-agent-summary">
          <div class="takeover-agent-name"><span class="entity-badge">Agent</span><strong>${escapeHtml(agentLabel(group.agentType))}</strong></div>
          <span>${escapeHtml(pendingGroupSummary(group.items))}</span>
          <em>展开 / 收起</em>
        </summary>
        <div class="takeover-agent-items">
          ${group.items.map(item => `
            <div class="takeover-row pending-skill-row">
              ${pendingCanSubmit(item)
                ? tf`<label class="pending-skill-select" title="选择 ${escapeHtml(item.skill_name)}"><input type="checkbox" data-select-pending="${escapeHtml(item.id)}"${selectedPendingIDs.has(item.id) ? ' checked' : ''} /></label>`
                : '<span class="pending-select-placeholder"></span>'}
              <div class="pending-skill-identity">
                <strong>${escapeHtml(item.skill_name)}</strong>
                <button class="path-link" type="button" title="${escapeHtml(item.pending_path)}" data-reveal-path="${escapeHtml(item.pending_path)}">${escapeHtml(item.pending_path)}</button>
              </div>
              <div class="pending-skill-status">
                <span class="result-status ${escapeHtml(pendingStatusClass(item.status))}"><i></i>${escapeHtml(pendingStatusLabel(item.status))}</span>
                <small>${escapeHtml(pendingStatusGuidance(item))}</small>
              </div>
              <div class="takeover-row-actions pending-inline-actions">
                ${item.platform_installable
                  ? tf`<button class="action-success icon-button icon-install" data-install-approved="${escapeHtml(item.id)}" data-agent-type="${escapeHtml(item.agent_type)}" data-skill-id="${escapeHtml(item.platform_skill_id || item.skill_id)}" data-version-id="${escapeHtml(item.platform_version_id || '')}" title="${escapeHtml(pendingPlatformInstallTitle(item))}">从平台安装</button>`
                  : pendingCanSubmit(item)
                  ? tf`<button class="primary icon-button icon-submit" data-submit-pending="${escapeHtml(item.id)}">提交平台检测</button>`
                  : ''}
                ${tf`<button class="pending-discard-button icon-button icon-remove" data-discard-pending="${escapeHtml(item.id)}" title="删除本地副本">删除副本</button>`}
              </div>
            </div>`).join('')}
        </div>
      </details>`).join('')
    : t('ui.iyva04')
  document.querySelectorAll('[data-select-pending]').forEach(input => input.addEventListener('change', () => {
    if (input.checked) selectedPendingIDs.add(input.dataset.selectPending)
    else selectedPendingIDs.delete(input.dataset.selectPending)
    syncPendingBatchControls()
  }))
  document.querySelectorAll('[data-submit-pending]').forEach(button => button.addEventListener('click', async () => {
    await submitPendingIDs([button.dataset.submitPending], button)
  }))
  document.querySelectorAll('[data-discard-pending]').forEach(button => button.addEventListener('click', async () => {
    const item = pendingItems.find(candidate => candidate.id === button.dataset.discardPending)
    if (!item) return
    pendingDiscardItem = item
    $('#discard-pending-name').textContent = item.skill_name
    $('#discard-pending-agent').textContent = tf`所属 Agent：${agentLabel(item.agent_type)}`
    $('#discard-pending-path').textContent = item.pending_path
    $('#discard-pending-dialog').showModal()
  }))
  document.querySelectorAll('[data-install-approved]').forEach(button => button.addEventListener('click', async () => {
    setBusy(button, true)
    try {
      await installPlatformSkill(button.dataset.agentType, button.dataset.skillId, button.dataset.installApproved, button.dataset.versionId)
      await refreshAfterInstall()
      showMessageDialog(t('ui.1br1zwn'), t('ui.stci1f'))
    } catch (error) {
      showMessageDialog(t('ui.v4sbw9'), String(error))
      log(error)
    } finally {
      setBusy(button, false)
    }
  }))
  syncPendingBatchControls()
  schedulePendingRefresh(items)
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
  const submittedIDs = []
  const failures = []
  try {
    setBusy(button, true)
    syncPendingBatchControls()
    const queuedNames = ids
      .map(id => pendingItems.find(item => item.id === id)?.skill_name)
      .filter(Boolean)
    startOperationProgress('#pending-progress', {
      title: tf`正在提交平台检测 0/${ids.length}`,
      detail: queuedNames.length ? tf`本次共 ${ids.length} 个：${formatList(queuedNames)}` : t('ui.1fn4bpx'),
      current: 0,
      total: ids.length,
    })
    let currentItems = JSON.parse(await run('pending'))
    for (let index = 0; index < ids.length; index += 1) {
      const id = ids[index]
      button.textContent = ids.length > 1 ? tf`正在提交 ${index + 1}/${ids.length}` : t('ui.q83krs')
      const current = currentItems.find(item => item.id === id)
      if (!current || current.skill_id) continue
      updateOperationProgress('#pending-progress', {
        title: tf`正在提交平台检测 ${index + 1}/${ids.length}`,
        detail: tf`当前：${current.skill_name || id}`,
        current: index,
        total: ids.length,
      })
      try {
        const result = JSON.parse(await run('submit-pending', ['--id', id]))
        submitted.push(result.name || current.skill_name || result.skill_id)
        submittedIDs.push(current.id)
        selectedPendingIDs.delete(id)
        currentItems = JSON.parse(await run('pending'))
      } catch (error) {
        failures.push({ name: current.skill_name || id, detail: String(error) })
        if (String(error).includes('client:submit-skill') || String(error).includes('scanner:submit')) break
      }
      updateOperationProgress('#pending-progress', {
        title: tf`正在提交平台检测 ${index + 1}/${ids.length}`,
        detail: tf`已完成 ${index + 1} 个，成功 ${submitted.length} 个，失败 ${failures.length} 个。`,
        current: index + 1,
        total: ids.length,
      })
    }
    if (submittedIDs.length) {
      const tracking = pendingBatchIsActive()
        ? pendingBatchTracking
        : { ids: new Set(), statuses: new Map() }
      submittedIDs.forEach(id => {
        tracking.ids.add(id)
        tracking.statuses.set(id, 'submitted')
      })
      pendingBatchTracking = tracking
    }
    await loadPending()
    if (submitted.length) {
      renderPendingBatchStatus()
      log(tf`已提交平台检测：${formatList(submitted)}`)
    }
    if (failures.length) {
      const permissionDenied = failures.some(item => item.detail.includes('client:submit-skill') || item.detail.includes('scanner:submit'))
      const detail = permissionDenied
        ? t('ui.1vj1hpi')
        : failures.map(item => `${item.name}：${item.detail}`).join('\n')
      showMessageDialog(permissionDenied ? t('ui.am251f') : t('ui.6y7is'), detail)
      showTakeoverFeedback('error', t('ui.1wps06y'), detail)
      log(detail)
    }
  } catch (error) {
    const detail = String(error)
    showMessageDialog(t('ui.182zhbv'), detail)
    showTakeoverFeedback('error', t('ui.182zhbv'), detail)
    log(detail)
  } finally {
    stopOperationProgress('#pending-progress')
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
  pendingItems.filter(pendingCanSubmit).forEach(item => {
    if (checked) selectedPendingIDs.add(item.id)
    else selectedPendingIDs.delete(item.id)
  })
  document.querySelectorAll('[data-select-pending]').forEach(input => { input.checked = checked })
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
const toggleGovernance = button => {
  const enabled = Boolean(connection?.local?.governance_enabled)
  runStatusCommand(button, enabled ? 'pause-governance' : 'resume-governance', enabled ? t('ui.1pm2mwm') : t('ui.1m8sjuh'))
}
$('#toggle-governance').addEventListener('click', event => toggleGovernance(event.currentTarget))
$('#toggle-takeover').addEventListener('click', event => toggleGovernance(event.currentTarget))
$('#install-service').addEventListener('click', event => runStatusCommand(event.currentTarget, 'install-service', t('ui.1wl6i9a')))
$('#uninstall-service').addEventListener('click', () => $('#stop-service-dialog').showModal())
$('#confirm-stop-service').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('uninstall-service')
    await refreshConnection()
    $('#stop-service-dialog').close()
    showMessageDialog(t('ui.duph87'), t('ui.176m8tu'))
    log(t('ui.duph87'))
  } catch (error) {
    $('#stop-service-dialog').close()
    showMessageDialog(t('ui.lu1yd5'), String(error))
    log(error)
  } finally {
    setBusy(button, false)
    syncSettingsControls()
  }
})
$('#stop-service-dialog').addEventListener('close', syncSettingsControls)
$('#refresh-records').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try { await refreshConnection() } finally { setBusy(button, false) }
})

$('#settings-trigger').addEventListener('click', () => showPanel('settings'))
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
$('#settings-background-service').addEventListener('change', async event => {
  const input = event.currentTarget
  if (!input.checked) {
    input.checked = true
    $('#stop-service-dialog').showModal()
    return
  }
  input.disabled = true
  try {
    await run('install-service')
    await refreshConnection()
    showMessageDialog(t('后台服务已启用'), t('客户端将在登录系统后自动启动后台治理服务。'))
  } catch (error) {
    showMessageDialog(t('启用后台服务失败'), String(error))
  } finally {
    syncSettingsControls()
  }
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
$('#settings-export-diagnostics').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const local = connection?.local || {}
    const platform = connection?.platform || {}
    const report = {
      generated_at: new Date().toISOString(),
      client_version: clientBuildVersion,
      locale: window.clientI18n?.getLocale?.() || 'zh-CN',
      settings: clientSettings,
      connection: {
        configured: Boolean(connection?.configured),
        connected: Boolean(connection?.connected),
        server: connection?.server || '',
        client_id: platform.client_id || connection?.inventory?.client_id || '',
        client_name: platform.name || connection?.name || '',
        service_installed: Boolean(connection?.service_installed),
        service_running: Boolean(connection?.service_running),
      },
      runtime: {
        governance_enabled: Boolean(local.governance_enabled),
        managed_skills: Number(local.managed_skills || 0),
        quarantined_skills: Number(local.quarantined_skills || 0),
        queued_events: Number(local.queued_events || 0),
        last_inventory_at: local.last_inventory_at || null,
        last_full_scan_at: local.last_full_scan_at || null,
      },
    }
    const path = await invoke('export_diagnostics', { content: JSON.stringify(report, null, 2) })
    showMessageDialog(t('诊断报告已导出'), tf`文件已保存到 ${path}`)
  } catch (error) {
    showMessageDialog(t('导出诊断报告失败'), String(error))
  } finally {
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

const loadBackups = async () => {
  const backups = JSON.parse(await run('backups'))
  $('#backup-select').innerHTML = backups.length
    ? backups.map(item => `<option value="${escapeHtml(item.name)}">${escapeHtml(formatTime(item.created_at))}</option>`).join('')
    : t('ui.2jmxw8')
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
$('#restore-backup').addEventListener('click', async event => {
  const backup = $('#backup-select').value
  if (!backup) return log(t('ui.1npxley'))
  if (!window.confirm(tf`确认恢复备份 ${backup}？当前同名 Skill 会先备份。`)) return
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('restore', ['--backup', backup, '--confirm'])
    log(tf`备份 ${backup} 已恢复`)
    showMessageDialog(t('ui.1q20nls'), t('ui.e38z9k'))
  } catch (error) {
    showMessageDialog(t('ui.6y1l8i'), String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})

const loadQuarantine = async () => {
  const items = JSON.parse(await run('quarantine'))
  $('#quarantine-list').classList.toggle('empty', !items.length)
  $('#quarantine-list').innerHTML = items.length ? items.map(item => {
    const detection = item.detection_status
      ? { ...item, status: item.detection_status }
      : null
    return tf`
    <div class="takeover-row quarantine-row">
      <div class="quarantine-skill-identity"><strong>${escapeHtml(item.skill_name)}</strong><button class="path-link" type="button" title="隔离目录：${escapeHtml(item.quarantine_path)}" data-reveal-path="${escapeHtml(item.quarantine_path)}">所属 Agent：${escapeHtml(agentLabel(item.agent_type))} · ${escapeHtml(item.original_path)}</button></div>
      ${detection
        ? `<strong class="quarantine-status result-status ${escapeHtml(pendingStatusClass(detection.status))}"><i></i>${escapeHtml(pendingStatusLabel(detection.status))}</strong>`
        : `<strong class="quarantine-status action-pending">${escapeHtml(t('ui.75sttk'))}</strong>`}
      <span class="quarantine-guidance">${escapeHtml(detection ? quarantineDetectionGuidance(detection) : reasonLabel(item.reason))}</span>
      <div class="takeover-row-actions quarantine-actions">
        ${!item.skill_id
          ? `<button class="primary icon-button icon-submit" data-submit-quarantine="${escapeHtml(item.id)}">提交当前版本检测</button>`
          : `<span class="pending-next">${escapeHtml(quarantineNextLabel(item.detection_status))}</span>`}
        <button class="icon-button icon-install" data-install-safe-version="${escapeHtml(item.skill_name)}">选择批准版本</button>
      </div>
    </div>`
  }).join('') : t('ui.w1aoqw')
  document.querySelectorAll('[data-submit-quarantine]').forEach(button => button.addEventListener('click', async () => {
    setBusy(button, true)
    try {
      const pending = JSON.parse(await run('queue-quarantine', ['--id', button.dataset.submitQuarantine]))
      await loadPending()
      await submitPendingIDs([pending.id], button)
      await refreshConnection()
      await loadQuarantine()
    } catch (error) {
      showMessageDialog(t('ui.1wvf48w'), String(error))
      log(error)
    } finally {
      setBusy(button, false)
    }
  }))
  document.querySelectorAll('[data-install-safe-version]').forEach(button => button.addEventListener('click', () => {
    openInstallDialog(null, button.dataset.installSafeVersion)
  }))
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

const loadStatusPage = async () => {
  if (connection) renderStatus(connection)
  await Promise.all([
    loadBackups().catch(error => log(error)),
    loadQuarantine().catch(error => log(error)),
  ])
}

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
  if (value === 'rescan' && task?.payload?.reason === 'policy_changed') return t('ui.q9utgp')
  return { install_skill: t('ui.14fftle'), remove_skill: t('ui.s2pmon'), repair_skill: t('ui.14oueep'), rescan: t('ui.1rnx8gk'), sync_policy: t('ui.q9utgp') }[value] || value || tf`平台任务`
}

function taskStatusLabel(value) {
  return { pending: t('ui.1yesuc2'), running: t('ui.6svkbt'), succeeded: t('ui.19j4h'), failed: t('ui.12db3qz'), cancelled: t('ui.1d8x36r') }[value] || value || '-'
}

function eventTypeLabel(value) {
  return {
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
    quarantine_rescan: t('ui.18kgpq0'),
  }[value] || value || '-'
}

function pendingStatusLabel(value) {
  return {
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
  // install-skill updates the filesystem and installation registry, but the
  // cached inventory still describes the state before installation. Discover
  // first so the governance preview can immediately render the installed
  // Skill under its Agent instead of showing an empty selection.
  await discover()
  await refreshConnection()
  if ($('#takeover').classList.contains('active')) await preview(false)
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
const installSubmittedAt = item => item?.submitted_at ? formatTime(item.submitted_at) : t('ui.13nfgz7')

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
      ? installVersions.map(item => `<option value="${escapeHtml(item.version_id)}">${escapeHtml(installVersion(item))}${item.source_version ? ` · ${escapeHtml(item.source_version)}` : ''}${item.latest_trusted ? ' · 最新可信' : ''} · ${escapeHtml(tf`提交人：${installSubmitter(item)}`)} · ${escapeHtml(tf`提交时间：${installSubmittedAt(item)}`)}</option>`).join('')
      : '<option value="">暂无可信版本</option>'
    select.value = response.default_version_id || installVersions[0]?.version_id || ''
    select.disabled = !installVersions.length
    await loadInstallSkillPreview()
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

const renderInstallTargets = () => {
  const skill = selectedInstallSkill()
  if (!skill) {
    $('#install-agent-targets').innerHTML = t('ui.icgn8')
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
      <span><input type="checkbox" data-install-target value="${escapeHtml(agent.agent_type)}" ${disabled ? 'disabled' : ''} />${escapeHtml(agentLabel(agent.agent_type))}</span>
      <em>${status}</em>
    </label>`
  }).join('') || t('ui.1m6fhil')
}

const openInstallDialog = async (skill, initialQuery = '') => {
  const agents = (inventory?.agents || []).filter(item => item.skill_management_supported)
  if (!agents.length) return showMessageDialog(t('ui.1rloj41'), t('ui.k8dvfk'))
  lockedInstallSkill = skill || null
  installCatalog = []
  installVersions = []
  $('#install-skill-search').value = initialQuery
  $('#install-skill-search-label').hidden = Boolean(skill)
  $('#install-skill-title').textContent = skill ? tf`安装 ${skill.name} 到其他 Agent` : t('ui.c0s9l')
  $('#install-platform-skill').disabled = true
  $('#install-platform-skill').innerHTML = `<option value="">${skill ? escapeHtml(skill.name) : t('ui.12x34mh')}</option>`
  $('#install-platform-version').disabled = true
  $('#install-platform-version').innerHTML = `<option value="">${t('请先选择 Skill')}</option>`
  $('#install-agent-targets').innerHTML = t('ui.hola4k')
  $('#install-skill-dialog').showModal()
  try {
    installCatalog = await loadInstallCatalog(agents, initialQuery, skill)
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
    const agents = (inventory?.agents || []).filter(item => item.skill_management_supported)
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
$('#install-platform-version').addEventListener('change', loadInstallSkillPreview)
$('#cancel-install-skill').addEventListener('click', () => {
  lockedInstallSkill = null
  $('#install-skill-dialog').close()
})
$('#confirm-install-skill').addEventListener('click', async event => {
  const skill = selectedInstallSkill()
  if (!skill) return showMessageDialog(t('ui.1xx9z2h'), t('ui.5bo4oh'))
  const targets = [...document.querySelectorAll('[data-install-target]:checked')].map(item => item.value)
  if (!targets.length) return showMessageDialog(t('ui.1titnia'), t('ui.1ybbgmr'))
  const versionId = $('#install-platform-version').value
  if (!versionId) return showMessageDialog('请选择可信版本', '恢复或安装必须绑定一个可信版本。')
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
  if (connection?.configured && document.querySelector(`#${clientSettings.defaultPanel}`)) {
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
  $('#panel-title').textContent = panelTitle(activePanel)
  if (inventory) renderInventory()
  if (builtinAgentSettings.length) renderBuiltinAgentSettings()
  if (selectedSkillPaths.size && $('#takeover-list').children.length) {
    await preview(false, true)
  } else if (pendingItems.length) {
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
