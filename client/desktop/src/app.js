const invoke = window.__TAURI__.core.invoke
const titles = {
  connect: '客户端接入',
  discover: 'Agent 发现',
  takeover: '接管预览',
  status: '运行状态',
  notifications: '安全通知',
  records: '执行记录',
}
let inventory = null
let connection = null
let selectedSkillPaths = new Set()
let takeoverReady = false
let installCatalog = []
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
let pendingRefreshTimer = null
let pendingRefreshBusy = false
let pendingSubmissionBusy = false
let pendingBatchTracking = null
let pendingClientUpdate = null
let clientUpdateInstalling = false
const selectedPendingIDs = new Set()
const notificationDeliveryAttempts = new Set()
const operationProgress = new Map()

const $ = selector => document.querySelector(selector)
const setBusy = (button, busy) => {
  button.disabled = busy
  button.classList.toggle('is-busy', busy)
  if (busy) {
    button.dataset.original = button.textContent
    button.dataset.busyLabel = button.dataset.busyText || '处理中...'
    button.textContent = button.dataset.busyLabel
  } else if (button.textContent === button.dataset.busyLabel) {
    button.textContent = button.dataset.original
  }
}
const run = async (command, args = []) => invoke('execute_client', { command, args })
const log = value => {
  $('#status-last-operation').textContent = `最近操作：${new Date().toLocaleTimeString()} · ${value || '操作完成'}`
}
const showMessageDialog = (title, detail) => {
  $('#message-dialog-title').textContent = title
  $('#message-dialog-detail').textContent = detail
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
    preparing: ['准备更新', '正在暂停后台服务并检查本地状态'],
    downloading: ['下载更新', total > 0
      ? `已下载 ${formatUpdateBytes(downloaded)} / ${formatUpdateBytes(total)}`
      : `已下载 ${formatUpdateBytes(downloaded)}`],
    installing: ['校验并安装', '更新包已下载，正在校验签名并安装'],
    restarting: ['重启客户端', '前台即将重启，启动后会自动更新后台服务'],
  }[stage] || ['处理更新', '正在处理客户端更新']
  progress.hidden = false
  progress.classList.toggle('indeterminate', total <= 0 || stage !== 'downloading')
  progress.querySelector('[data-progress-title]').textContent = content[0]
  progress.querySelector('[data-progress-detail]').textContent = content[1]
  progress.querySelector('[data-progress-elapsed]').textContent = total > 0 && stage === 'downloading' ? `${percentage}%` : '处理中'
  progress.querySelector('[data-progress-bar]').style.width = total > 0 && stage === 'downloading' ? `${percentage}%` : ''
}

if (window.__TAURI__.event?.listen) {
  window.__TAURI__.event
    .listen('client-update-progress', event => renderClientUpdateProgress(event.payload))
    .catch(error => log(`更新进度监听失败：${error}`))
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
      element.querySelector('[data-progress-elapsed]').textContent = `已用时 ${elapsed} 秒`
    }, 1000),
  }
  operationProgress.set(selector, state)
  element.hidden = false
  element.classList.toggle('indeterminate', total <= 0)
  element.querySelector('[data-progress-title]').textContent = title
  element.querySelector('[data-progress-detail]').textContent = detail
  element.querySelector('[data-progress-elapsed]').textContent = '已用时 0 秒'
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
    showMessageDialog('打开文件夹失败', String(error))
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
  $(`#${panel}`).classList.add('active')
  $('#panel-title').textContent = titles[panel]
  $('.workspace').scrollTop = 0
  if (panel === 'status') loadStatusPage()
  if (panel === 'notifications') refreshConnection()
  if (panel === 'records') refreshConnection()
}

const showTakeoverError = error => {
  takeoverReady = false
  syncApplyState()
  $('#takeover-summary').hidden = true
  $('#takeover-result-note').hidden = true
  $('#takeover-actions').hidden = true
  $('#takeover-list').classList.remove('empty')
  $('#takeover-list').innerHTML = `<div class="inline-error"><strong>暂时无法生成预览</strong><span>${escapeHtml(error)}</span><button class="icon-button icon-back" data-back-to-discover>返回选择 Skill</button></div>`
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
      $('#takeover-list').textContent = '正在加载受管 Agent 和 Skill...'
    }
    takeoverLoading = true
    startOperationProgress('#takeover-progress', {
      title: '正在生成接管预览',
      detail: `正在读取 ${selectedSkillPaths.size} 个已选 Skill，并核对平台状态与内容签名。`,
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

$('#connect-form').addEventListener('submit', async event => {
  event.preventDefault()
  const button = event.submitter
  setBusy(button, true)
  try {
    const args = ['--server', $('#server').value, '--token', $('#token').value]
    if ($('#client-name').value.trim()) args.push('--name', $('#client-name').value.trim())
    await run('configure', args)
    log(await run('register'))
    await refreshConnection()
    showPanel('connect')
  } catch (error) {
    log(error)
  } finally {
    setBusy(button, false)
  }
})

const policyLabel = value => ({ audit: '只审计', repair: '自动恢复', block: '隔离阻断' }[value] || value || '-')
const governanceLabel = value => ({ registry: '客户端安全治理', strict: 'Agent 强授权' }[value] || value || '客户端安全治理')
const formatTime = value => {
  if (!value) return '-'
  const text = String(value)
  const normalized = /^\d{4}-\d{2}-\d{2}T/.test(text) && !/(Z|[+-]\d{2}:?\d{2})$/.test(text) ? `${text}Z` : text
  return new Date(normalized).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
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
  $('#cancel-edit').hidden = true
  $('#connect-submit').textContent = '接入平台'
  $('#connection-state').textContent = '未接入'
  $('#connection-state').classList.remove('online')
  $('#notification-trigger').hidden = true
  $('#panel-title').textContent = '客户端接入'
}
const editConnection = () => {
  $('#connect-form').hidden = false
  $('#server').value = connection?.server || ''
  $('#client-name').value = connection?.name || connection?.platform?.name || ''
  $('#token').value = ''
  $('#token').required = false
  $('#token').placeholder = '留空表示继续使用现有凭证'
  $('#connect-submit').textContent = '测试并保存'
  $('#cancel-edit').hidden = false
  $('#server').focus()
}

const renderBuiltinAgentSettings = () => {
  const element = $('#builtin-agent-settings')
  element.innerHTML = builtinAgentSettings.length
    ? builtinAgentSettings.map(item => `
      <button class="builtin-agent-row" type="button" data-edit-agent-paths="${escapeHtml(item.agent_type)}">
        <span class="builtin-agent-name"><strong>${escapeHtml(agentLabel(item.agent_type))}</strong>${item.customized ? '<em>已自定义</em>' : ''}</span>
        <span class="builtin-agent-roots">${item.current_roots.map(root => `<code title="${escapeHtml(root)}">${escapeHtml(root)}</code>`).join('')}</span>
        <span class="builtin-agent-edit">修改目录</span>
      </button>`).join('')
    : '<div class="empty compact">暂无内置 Agent 配置</div>'
  document.querySelectorAll('[data-edit-agent-paths]').forEach(button => button.addEventListener('click', () => {
    editingBuiltinAgent = builtinAgentSettings.find(item => item.agent_type === button.dataset.editAgentPaths) || null
    if (!editingBuiltinAgent) return
    $('#agent-paths-title').textContent = `修改 ${agentLabel(editingBuiltinAgent.agent_type)} 扫描目录`
    $('#agent-paths-input').value = editingBuiltinAgent.current_roots.join('\n')
    $('#agent-paths-default').textContent = `默认目录：${editingBuiltinAgent.default_roots.join('；')}`
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
  const platformAgents = platform.agents || []
  const platformByType = Object.fromEntries(platformAgents.map(agent => [agent.agent_type, agent]))
  const supported = agents.filter(agent => agent.skill_management_supported)
  const bound = supported.filter(agent => platformByType[agent.agent_type]?.managed_agent_id)
  const strict = platform.governance_mode === 'strict'
  const managedSkills = platformAgents.reduce((count, agent) => count + (agent.skills || []).filter(skill => skill.skill_id).length, 0)
  const todos = []
  const local = data.local || {}
  const hasTakeover = (local.managed_skills || 0) + (local.pending_skills || 0) > 0
  const governanceEnabled = Boolean(local.governance_enabled)
  const agentsReady = supported.length > 0 && (!strict || bound.length === supported.length)
  const scopeConfirmed = agentsReady && hasTakeover
  const patrolActive = scopeConfirmed && data.service_running && governanceEnabled
  const takeoverTitle = hasTakeover ? 'Skill 治理' : '接管预览'
  titles.takeover = takeoverTitle
  $('#takeover-nav-label').textContent = takeoverTitle
  $('#takeover-heading').textContent = takeoverTitle
  $('#takeover-description').textContent = hasTakeover
    ? '查看当前受管 Skill，并识别新出现或需要处理的本地 Skill。刷新不会重复接管。'
    : '安全治理模式只校验平台批准状态与内容签名；Agent 强授权模式还会校验智能体允许范围。'
  $('#takeover-state-badge').hidden = !hasTakeover
  $('#takeover-state-badge').className = `takeover-state-badge${governanceEnabled ? '' : ' paused'}`
  $('#takeover-state-badge').textContent = governanceEnabled ? '接管中' : '治理已暂停'
  const connectionError = !data.connected
  if (connectionError) {
    todos.push({ title: '平台接入异常', detail: data.error || '无法验证当前接入状态', action: '重试接入', actionType: 'refresh', error: true })
  }
  if (data.connected && supported.length === 0) {
    todos.push({ title: '尚未发现可管理的 Agent', detail: '重新发现本机已安装的 Agent。', action: '发现 Agent', panel: 'discover' })
  }
  if (data.connected && strict && supported.length > bound.length) {
    todos.push({ title: `${supported.length - bound.length} 个 Agent 尚未绑定`, detail: '绑定平台智能体后才能统一安装和校验 Skill。', action: '前往绑定', panel: 'discover' })
  }
  if (data.connected && hasTakeover && !data.service_running) {
    todos.push({
      title: data.service_installed ? '后台巡检未运行' : '后台巡检尚未启用',
      detail: data.service_detail || '关闭桌面应用后将无法持续同步和校验 Skill。',
      action: '启用巡检', actionType: 'install-service', error: data.service_installed,
    })
  }
  if (data.connected && data.service_running && local.managed_skills > 0 && !local.governance_enabled) {
    todos.push({ title: '持续治理已暂停', detail: '平台任务仍会同步，但不会巡检或自动处置本地 Skill。', action: '查看状态', panel: 'status' })
  }
  if ((local.quarantined_skills || 0) > 0) {
    todos.push({ title: `${local.quarantined_skills} 个 Skill 已隔离`, detail: '可在运行状态中查看原因，并从平台选择批准版本重新安装。', action: '查看隔离区', panel: 'status', error: true })
  }
  if ((local.pending_skills || 0) > 0) {
    todos.push({ title: `${local.pending_skills} 个 Skill 已停用待检测`, detail: '内容仍安全保留，可直接提交平台检测。', action: '前往处理', panel: 'takeover' })
  }
  if ((local.queued_events || 0) > 0) {
    todos.push({ title: `${local.queued_events} 条审计事件待补报`, detail: '平台恢复连接后会自动补报。', action: '刷新连接', actionType: 'refresh' })
  }

  $('#connection-intro').hidden = true
  $('#credential-tip').hidden = true
  $('#connect-form').hidden = true
  $('#token').value = ''
  $('#connected-overview').hidden = false
  $('#connection-state').textContent = data.connected ? '已接入' : '接入异常'
  $('#connection-state').classList.toggle('online', data.connected)
  $('#notification-trigger').hidden = false
  const activePanel = document.querySelector('.panel.active')?.id || 'connect'
  $('#panel-title').textContent = titles[activePanel]
  $('#overview-badge').className = `overview-badge${connectionError ? ' error' : ''}`
  $('#overview-badge').textContent = connectionError ? '接入异常' : '已接入'
  $('#overview-title').textContent = connectionError ? '暂时无法连接 Agent Manager' : '客户端已接入 Agent Manager'
  $('#overview-subtitle').textContent = connectionError
    ? `${data.error || '平台暂时不可达'}。现有 Skill 不受影响。`
    : `${platform.name || data.name || data.inventory?.hostname || '当前客户端'}已接入 ${data.server}`
  $('#overview-sync').textContent = connectionError ? '重试接入' : '刷新状态'

  $('#metric-agents').textContent = agents.length
  $('#metric-bound').textContent = strict ? `${bound.length} / ${supported.length}` : `${supported.length} / ${supported.length}`
  $('#metric-bound-label').textContent = strict ? '已绑定智能体' : '可治理 Agent'
  $('#metric-skills').textContent = local.managed_skills ?? managedSkills
  $('#metric-todos').textContent = todos.length
  $('#progress-summary').textContent = !data.connected
    ? '恢复平台接入后才能继续同步。'
    : supported.length === 0
      ? '客户端已接入，请发现本机 Agent。'
      : strict && bound.length < supported.length
        ? `已发现 ${agents.length} 个 Agent，还有 ${supported.length - bound.length} 个需要绑定。`
        : !hasTakeover
          ? 'Agent 已发现，请确认需要治理的 Skill 范围。'
          : !data.service_running
            ? '治理范围已确认，请启用后台巡检。'
            : !governanceEnabled
              ? '持续治理已暂停，恢复后将继续巡检。'
              : `${supported.length} 个 Agent 正在持续治理。`
  setProgress('step-connect', data.connected ? 'done' : 'current')
  setProgress('step-discover', agents.length ? 'done' : data.connected ? 'current' : '')
  $('#step-bind span').textContent = strict ? '绑定并确认范围' : '确认治理范围'
  setProgress('step-bind', scopeConfirmed ? 'done' : agents.length ? 'current' : '')
  $('#step-service span').textContent = data.service_running && !governanceEnabled && hasTakeover ? '后台巡检已暂停' : '后台巡检'
  setProgress('step-service', patrolActive ? 'done' : scopeConfirmed ? 'current' : '')

  $('#detail-service').textContent = data.service_running
    ? governanceEnabled && hasTakeover ? '运行中' : hasTakeover ? '运行中 · 巡检已暂停' : '运行中 · 尚未接管'
    : data.service_installed ? '已安装但未运行' : '未安装'
  $('#detail-policy').textContent = policyLabel(platform.policy_mode)
  $('#detail-governance').textContent = governanceLabel(platform.governance_mode)
  $('#detail-last-seen').textContent = formatTime(platform.last_seen_at)
  $('#detail-token-status').textContent = data.connected ? `有效 · ${data.token_hint}` : `需检查 · ${data.token_hint}`
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
}

const renderStatus = data => {
  const local = data?.local || {}
  const running = Boolean(data?.service_running)
  const installed = Boolean(data?.service_installed)
  const governanceEnabled = Boolean(local.governance_enabled)
  const findings = local.patrol_findings || []
  const issues = (local.quarantined_skills || 0) + (local.queued_events || 0) + findings.length
  $('#status-service-badge').className = `overview-badge${running ? '' : ' warning'}`
  $('#status-service-badge').textContent = running ? governanceEnabled ? '治理中' : '服务运行中' : installed ? '运行异常' : '未启用'
  $('#status-service-title').textContent = running ? governanceEnabled ? '持续治理运行中' : '持续治理已暂停' : installed ? '后台服务未运行' : '后台服务尚未启用'
  $('#status-service-description').textContent = running
    ? governanceEnabled
      ? '后台服务持续同步平台任务，并定时巡检受管 Skill；也可以立即执行一次完整巡检。'
      : '后台服务仍会同步平台任务，但不会巡检、告警、隔离或自动修复本地 Skill。'
    : installed ? data.service_detail || '请重新启用后台服务。' : '启用后将同步平台任务，并可持续治理受管 Skill。'
  $('#install-service').hidden = running
  $('#install-service').textContent = installed ? '重新启用后台服务' : '启用后台服务'
  $('#uninstall-service').hidden = !installed
  $('#toggle-governance').hidden = !local.managed_skills
  $('#toggle-governance').textContent = governanceEnabled ? '暂停持续治理' : '恢复持续治理'
  $('#toggle-governance').className = `takeover-toggle icon-button ${governanceEnabled ? 'pause icon-pause' : 'resume icon-resume'}`
  $('#toggle-takeover').hidden = !local.managed_skills
  $('#toggle-takeover').textContent = governanceEnabled ? '暂停接管' : '恢复接管'
  $('#toggle-takeover').className = `takeover-toggle icon-button ${governanceEnabled ? 'pause icon-pause' : 'resume icon-resume'}`
  $('#run-once').disabled = !governanceEnabled
  $('#run-once').title = governanceEnabled ? '' : '恢复持续治理后才能执行巡检'
  $('#status-last-scan').textContent = formatTime(local.last_full_scan_at)
  $('#status-next-scan').textContent = governanceEnabled && running ? formatTime(local.next_full_scan_at) : '-'
  $('#status-managed-count').textContent = local.managed_skills || 0
  $('#status-quarantine-count').textContent = local.quarantined_skills || 0
  $('#status-queued-count').textContent = local.queued_events || 0
  $('#status-attention').className = `status-attention${issues ? ' warning' : ' ok'}`
  $('#status-attention-text').textContent = findings.length
    ? `最近巡检发现 ${findings.length} 个异常：${findings.map(item => item.skill_name).join('、')}。`
    : issues
    ? `需要处理：${local.quarantined_skills || 0} 个隔离项、${local.queued_events || 0} 条待补报事件。`
    : '当前没有需要处理的本地事项。'
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
    return `
    <button class="notification-item ${escapeHtml(item.severity)}${item.read_at ? '' : ' unread'}" data-notification-id="${item.id}" data-notification-panel="${action.panel}">
      <i aria-hidden="true"></i>
      <div class="notification-content">
        <div><strong>${escapeHtml(item.title)}</strong><span class="severity-label">${notificationSeverity(item.severity)}</span>${item.read_at ? '' : '<span>未读</span>'}</div>
        <p>${escapeHtml(item.message)}</p>
        <small>${escapeHtml(agentLabel(item.agent_type))} · ${escapeHtml(item.skill_name)} · ${escapeHtml(formatTime(item.created_at))}</small>
      </div>
      <span class="notification-action">${action.label} →</span>
    </button>`
  }).join('') : '<div class="empty">当前筛选下暂无通知</div>'
  document.querySelectorAll('[data-notification-id]').forEach(button => button.addEventListener('click', async () => {
    const panel = button.dataset.notificationPanel
    showPanel(panel)
    try {
      await run('read-notifications', ['--id', button.dataset.notificationId])
      await refreshLocalNotifications()
    } catch (error) {
      showMessageDialog('操作失败', String(error))
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
    await invoke('show_system_notification', { title: item.title, body: item.message })
    await run('deliver-notification', ['--id', String(item.id)])
    $('#system-notification-state').hidden = true
  } catch (error) {
    $('#system-notification-state').classList.remove('success')
    $('#system-notification-state').hidden = false
    $('#system-notification-state').textContent = String(error)
  }
}

const notificationSeverity = severity => ({ critical: '严重', warning: '警告', info: '已处置' }[severity] || '提示')
const notificationAction = eventType => ({
  skill_quarantined: { panel: 'status', label: '查看隔离区' },
  unmanaged_skill_found: { panel: 'takeover', label: '前往治理' },
  skill_modified: { panel: 'status', label: '查看状态' },
  skill_repaired: { panel: 'records', label: '查看记录' },
}[eventType] || { panel: 'records', label: '查看详情' })

const renderEventHistory = events => {
  const element = $('#event-history-list')
  element.classList.toggle('empty', !events.length)
  element.innerHTML = events.length ? events.map(event => `<div class="takeover-row task-history-row">
    <div><strong>${escapeHtml(eventTypeLabel(event.event_type))}</strong><p>${escapeHtml(event.skill_name || eventDetail(event.event_type))}</p></div>
    <span>${escapeHtml(event.agent_type ? agentLabel(event.agent_type) : '当前客户端')}</span>
    <strong class="task-status-${eventStatus(event.event_type)}">${escapeHtml(eventResultLabel(event.event_type))}</strong>
    <span>${escapeHtml(formatTime(event.created_at))}</span>
  </div>`).join('') : '<div class="empty">暂无巡检与处置记录</div>'
}

const renderTaskHistory = tasks => {
  const element = $('#task-history-list')
  element.classList.toggle('empty', !tasks.length)
  element.innerHTML = tasks.length ? tasks.map(task => {
    const payload = task.payload || {}
    const policySync = task.task_type === 'sync_policy' || (task.task_type === 'rescan' && payload.reason === 'policy_changed')
    const target = policySync
      ? `处置：${policyLabel(payload.mode)} · 治理：${governanceLabel(payload.governance_mode)}`
      : payload.skill_name || payload.skill_id || (task.task_type === 'rescan' ? '全部 Skill' : '-')
    return `<div class="takeover-row task-history-row">
      <div><strong>${escapeHtml(taskTypeLabel(task))}</strong><p>${escapeHtml(target)}</p></div>
      <span>${escapeHtml(payload.agent_type ? agentLabel(payload.agent_type) : '当前客户端')}</span>
      <strong class="task-status-${escapeHtml(task.status)}">${escapeHtml(taskStatusLabel(task.status))}</strong>
      <span class="${task.error ? 'task-history-error' : ''}">${escapeHtml(`${formatTime(task.finished_at || task.started_at || task.updated_at || task.created_at)}${task.error ? ` · ${task.error}` : ''}`)}</span>
    </div>`
  }).join('') : '<div class="empty">暂无平台任务记录</div>'
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
      $('#builtin-agent-settings').innerHTML = `<div class="inline-error"><strong>读取扫描目录失败</strong><span>${escapeHtml(error)}</span></div>`
    })
    await loadPending().catch(error => log(error))
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
    if ((!changedAt || changedAt === lastInventoryAt) && !taskChanged && !notificationChanged) return
    if (changedAt === lastInventoryAt) {
      connection.local = local
      renderStatus(connection)
      return
    }
    const refreshTakeover = $('#takeover').classList.contains('active')
    await refreshConnection()
    if (refreshTakeover) await preview(false)
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
  try {
    await invoke('show_system_notification', { title: '瑞数智能体安全治理客户端', body: '系统通知已开启，安全事件将及时提醒。' })
    $('#system-notification-state').hidden = false
    $('#system-notification-state').classList.add('success')
    $('#system-notification-state').textContent = '系统通知已发送。应用位于前台时，macOS 可能只将其收录到通知中心。'
  } catch (error) {
    $('#system-notification-state').classList.remove('success')
    $('#system-notification-state').hidden = false
    $('#system-notification-state').textContent = String(error)
  }
})
$('#mark-notifications-read').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('read-notifications')
    const local = await refreshLocalNotifications()
    if (Number(local.unread_notifications || 0) !== 0) throw new Error('本地通知状态未更新，请重试')
    $('#system-notification-state').hidden = false
    $('#system-notification-state').classList.add('success')
    $('#system-notification-state').textContent = '全部通知已标记为已读。'
  } catch (error) {
    showMessageDialog('操作失败', String(error))
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
    if ((local.notifications || []).length !== 0) throw new Error('本地通知仍未清空，请重试')
    $('#clear-notifications-dialog').close()
    $('#system-notification-state').hidden = false
    $('#system-notification-state').classList.add('success')
    $('#system-notification-state').textContent = '本机通知已清除。隔离记录和平台审计未受影响。'
    log('本机通知已清除')
  } catch (error) {
    showMessageDialog('清除失败', String(error))
  } finally {
    setBusy(button, false)
  }
})

const renderInventory = () => {
  if (!inventory?.agents) return
  const bindings = Object.fromEntries((connection?.platform?.agents || []).map(agent => [agent.agent_type, agent.managed_agent_id || '']))
  const supported = inventory.agents.filter(agent => agent.skill_management_supported).length
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
      return `
        <details class="agent-card">
          <summary class="agent-summary">
            <div class="agent-name"><span class="entity-badge">${isSharedSkills(agent) ? '共享' : 'Agent'}</span><div><strong>${escapeHtml(agentLabel(agent.agent_type))}</strong><small title="${escapeHtml(agent.skills_path || 'Skill 目录尚未创建')}">${escapeHtml(agent.skills_path || 'Skill 目录尚未创建')}</small></div></div>
            <div class="capability ${agent.skill_management_supported ? 'supported' : ''}">
              ${agent.skill_management_supported
                ? `${agent.skills.length} 个 Skill${agent.skills.filter(skill => skill.error).length ? ` · ${agent.skills.filter(skill => skill.error).length} 个待校验` : ''}`
                : '仅识别客户端，不执行 Skill 接管'}
            </div>
            <span class="fold-label">${agent.skill_management_supported ? '展开 / 收起' : '无可管理 Skill'}</span>
          </summary>
          ${(agent.skill_management_supported && strict) || isCustomAgent(agent)
            ? `<div class="agent-settings">${agent.skill_management_supported && strict ? `<label class="mapping">平台智能体<select data-agent="${escapeHtml(agent.agent_type)}"><option value="">请选择</option>${compatible.map(item => `<option value="${escapeHtml(item.agent_id)}" ${item.agent_id === binding ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}</select></label>` : ''}${isCustomAgent(agent) ? `<button class="custom-agent-remove icon-button icon-remove" type="button" title="只取消本地登记，不删除 Skill 文件" data-remove-custom-agent="${escapeHtml(agent.agent_type)}" data-custom-agent-name="${escapeHtml(agent.display_name)}">取消登记</button>` : ''}</div>`
            : ''}
          ${agent.skill_management_supported ? `<div class="skill-inventory">${agent.skills.length ? agent.skills.map(skill => `
            <div class="skill-row">
              <div class="skill-row-main">
                <input type="checkbox" aria-label="选择 ${escapeHtml(skill.name)}" data-skill-path="${escapeHtml(skill.path)}" ${skill.error ? 'disabled' : 'checked'} />
                <span>
                  <strong>${escapeHtml(skill.name)}</strong>
                  <button class="path-link" type="button" title="${escapeHtml(skill.path)}" data-reveal-path="${escapeHtml(skill.path)}">${escapeHtml(skill.path)}</button>
                </span>
              </div>
              <div class="skill-row-actions">
                <em class="${skill.error ? 'warning' : 'ok'}">${skill.error ? '待处理' : skill.skill_id ? '已受管' : '待接管'}</em>
                ${skill.skill_id && !skill.error ? `<button class="icon-button icon-install" type="button" data-install-other="${escapeHtml(skill.skill_id)}" data-skill-name="${escapeHtml(skill.name)}" data-source-agent="${escapeHtml(agent.agent_type)}">安装到其他 Agent</button>` : ''}
              </div>
            </div>`).join('') : '<div class="empty compact">未发现 Skill</div>'}</div>` : ''}
        </details>`
    }).join('')
    : '<div class="empty">未发现支持的 Agent</div>'
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
    showMessageDialog('选择目录失败', String(error))
  } finally {
    setBusy(button, false)
  }
})

$('#save-agent-paths').addEventListener('click', async event => {
  if (!editingBuiltinAgent) return
  const input = $('#agent-paths-input')
  const roots = input.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean)
  input.setCustomValidity(roots.length ? '' : '至少保留一个 Skill 扫描目录')
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
    showMessageDialog('扫描目录已更新', '新的目录已保存并完成一次 Agent 重新发现。')
  } catch (error) {
    showMessageDialog('保存扫描目录失败', String(error))
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
    showMessageDialog('已恢复默认目录', '该 Agent 已恢复使用内置的默认 Skill 扫描目录。')
  } catch (error) {
    showMessageDialog('恢复默认目录失败', String(error))
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
    showMessageDialog('登记已取消', `已取消“${item.name}”的本地登记，原 Skill 目录和文件没有被删除。`)
  } catch (error) {
    showMessageDialog('取消登记失败', String(error))
  } finally {
    setBusy(button, false)
  }
})

const discover = async () => {
  const output = await run('inventory')
  inventory = JSON.parse(output)
  renderInventory()
  const supported = inventory.agents.filter(agent => agent.skill_management_supported).length
  log(`发现 ${inventory.agents.length} 个 Agent，其中 ${supported} 个支持 Skill 管理`)
}

const updateSelectionSummary = () => {
  $('#discover-next').hidden = !inventory?.agents?.some(agent => agent.skill_management_supported)
  const previewButton = $('#open-preview-button')
  const discoveredSkills = [...document.querySelectorAll('[data-skill-path]')]
  const unavailableCount = discoveredSkills.filter(input => input.disabled).length
  const selectableCount = discoveredSkills.length - unavailableCount
  const recoveryNeeded = selectableCount === 0 && unavailableCount > 0
  previewButton.dataset.action = recoveryNeeded ? 'restore' : 'preview'
  previewButton.disabled = !recoveryNeeded && selectedSkillPaths.size === 0
  $('#selection-heading').textContent = recoveryNeeded ? '需要恢复 Skill' : '下一步：确认接管范围'
  $('#selection-guidance').innerHTML = selectableCount === 0
    ? unavailableCount
      ? `发现 ${unavailableCount} 个不可用 Skill。请展开 Agent 查看原因，或从平台重新安装可信版本。`
      : '当前没有发现可接管的 Skill。'
    : `已选择 <b id="selected-skill-count">${selectedSkillPaths.size}</b> 个 Skill，生成预览后可查看哪些继续启用、哪些需要处理。`
  const currentKey = JSON.stringify([lastInventoryAt, [...selectedSkillPaths].sort()])
  previewButton.textContent = recoveryNeeded
    ? '从平台恢复 Skill'
    : selectableCount === 0
      ? '暂无可接管 Skill'
    : !previewSelectionKey
      ? '生成接管预览'
      : previewSelectionKey === currentKey
        ? '查看接管预览'
        : '更新接管预览'
  previewButton.title = recoveryNeeded
    ? '从平台选择已批准的 Skill，重新安装到本机 Agent'
    : selectableCount === 0
      ? '当前没有发现可接管的 Skill'
    : selectedSkillPaths.size === 0
      ? '请先选择至少一个 Skill'
      : previewButton.textContent
}

$('#discover-button').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  $('#agent-list').classList.add('empty')
  $('#agent-list').textContent = '正在发现本机 Agent 和 Skill...'
  try {
    await discover()
  } catch (error) {
    $('#agent-list').innerHTML = `<div class="empty discovery-error">发现失败：${escapeHtml(error)}</div>`
    log(error)
  } finally {
    setBusy(button, false)
  }
})

$('#add-custom-agent-button').addEventListener('click', () => {
  if (!connection?.configured) return showMessageDialog('请先接入平台', '接入 Agent Manager 后才能添加自定义 Agent。')
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
    showMessageDialog('选择目录失败', String(error))
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
    showMessageDialog('自定义 Agent 已添加', '已读取该目录中的 Skill。接下来可选择 Skill 并生成接管预览。')
  } catch (error) {
    showMessageDialog('添加自定义 Agent 失败', String(error))
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
  if (connection?.platform?.governance_mode === 'strict' && !args.length) {
    throw new Error('Agent 强授权模式下，请至少绑定一个平台智能体')
  }
  const selected = [...selectedSkillPaths]
  if (!selected.length) {
    $('#manage-count').textContent = '0'
    $('#pending-count').textContent = '0'
    $('#takeover-summary').hidden = true
    $('#takeover-result-note').hidden = !showNoChange
    $('#takeover-result-note').textContent = '预览结果：当前没有选择需要接管的 Skill。'
    $('#takeover-list').classList.add('empty')
    $('#takeover-list').textContent = '当前没有新选择的 Skill，已停用项仍保留在下方待处理区'
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
    ? '预览结果：没有需要新增接管或停用的 Skill。'
    : managed
      ? `已接管 ${managed} 个 Skill；仅新增或状态异常的 Skill 需要处理。`
      : '以下为确认接管后的状态预览，展开 Agent 可查看每个 Skill 的判断依据。'
  $('#manage-count').textContent = manage
  $('#pending-count').textContent = pending
  $('#takeover-feedback').hidden = true
  $('#takeover-list').classList.remove('empty')
  $('#takeover-list').innerHTML = plan.items.length
    ? groupTakeoverItems(plan.items).map(group => {
      const enabled = group.items.filter(item => item.action === 'manage').length
      const existing = group.items.filter(item => item.action === 'managed').length
      const pendingItems = group.items.filter(item => item.action === 'pending').length
      return `<details class="takeover-agent">
        <summary class="takeover-agent-summary">
          <div class="takeover-agent-name"><span class="entity-badge">Agent</span><strong>${escapeHtml(agentLabel(group.agentType))}</strong></div>
          <span>${group.items.length} 个 Skill${existing ? ` · ${existing} 个已接管` : ''}${enabled ? ` · ${enabled} 个待接管` : ''}${pendingItems ? ` · ${pendingItems} 个停用` : ''}</span>
          <em>展开 / 收起</em>
        </summary>
        <div class="takeover-agent-items">
          <div class="takeover-column-head"><span>Skill</span><span>接管后状态</span><span>判断依据</span><span>操作</span></div>
          ${group.items.map(item => `
          <div class="takeover-row">
            <div><strong>${escapeHtml(item.name)}</strong><button class="path-link" type="button" title="${escapeHtml(item.source)}" data-reveal-path="${escapeHtml(item.source)}">${escapeHtml(item.source)}</button></div>
            <span class="result-status status-${item.action}"><i></i>${item.action === 'managed' ? '已接管' : item.action === 'manage' ? '待接管' : '停用'}</span>
            <span>${escapeHtml(reasonLabel(item.reason))}</span>
            ${['manage', 'managed'].includes(item.action) && item.skill_id ? `<button class="icon-button icon-install" type="button" data-install-preview="${escapeHtml(item.skill_id)}" data-skill-name="${escapeHtml(item.name)}" data-source-agent="${escapeHtml(item.agent_type)}">安装到其他 Agent</button>` : '<span>-</span>'}
          </div>`).join('')}
        </div>
      </details>`
    }).join('')
    : '<div class="empty">没有需要接管的 Skill</div>'
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
    title: '正在生成接管预览',
    detail: `正在读取 ${selectedSkillPaths.size} 个已选 Skill，并核对平台状态与内容签名。`,
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
  if (event.currentTarget.dataset.action === 'restore') return openInstallDialog()
  return generateAndOpenPreview(event.currentTarget)
})
$('#takeover-ack').addEventListener('change', syncApplyState)
$('#apply-button').addEventListener('click', async event => {
  if (!takeoverReady) return showTakeoverError('请先生成接管预览')
  const button = event.currentTarget
  const managedCount = Number($('#manage-count').textContent) || 0
  const pendingCount = Number($('#pending-count').textContent) || 0
  showTakeoverFeedback('processing', '正在执行接管', '正在备份现有目录并应用预览中的处理结果，请稍候。')
  startOperationProgress('#takeover-progress', {
    title: '正在执行接管',
    detail: `正在备份并处理 ${managedCount + pendingCount} 个 Skill，请不要关闭客户端。`,
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
    log(`接管完成：纳入管理 ${managedCount} 个，停用 ${pendingCount} 个`)
    await refreshConnection()
    const detail = `已纳入管理 ${managedCount} 个，可继续使用；已停用 ${pendingCount} 个，已移入下方待处理区。客户端将持续巡检，接管前内容已备份。`
    $('#takeover-result-note').textContent = '以下为接管后的当前状态；停用的 Skill 已无法被 Agent 加载。'
    showTakeoverFeedback('success', '接管完成', detail)
    showMessageDialog('接管完成', detail)
  } catch (error) {
    showTakeoverFeedback('error', '接管失败', error)
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
  const tracked = pendingItems.filter(item => pendingBatchTracking.ids.has(item.id))
  const counts = { detecting: pendingBatchTracking.ids.size - tracked.length, review: 0, approved: 0, rejected: 0, cancelled: 0 }
  tracked.forEach(item => {
    if (item.status === 'VETTED') counts.review += 1
    else if (item.status === 'APPROVED') counts.approved += 1
    else if (item.status === 'REJECTED') counts.rejected += 1
    else if (item.status === 'CANCELLED') counts.cancelled += 1
    else counts.detecting += 1
  })
  const total = pendingBatchTracking.ids.size
  const resolved = total - counts.detecting
  const finished = counts.detecting === 0 && counts.review === 0
  element.hidden = false
  element.className = `takeover-feedback ${finished ? counts.rejected || counts.cancelled ? 'error' : 'success' : 'processing'}`
  const title = counts.detecting
    ? `本批检测进度：已出结果 ${resolved}/${total}`
    : counts.review
      ? `自动检测已完成：${counts.review} 个待审核`
      : '本批检测已完成'
  element.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml([
    `检测中 ${counts.detecting}`,
    `待审核 ${counts.review}`,
    `已批准 ${counts.approved}`,
    `未通过 ${counts.rejected}`,
    counts.cancelled ? `已取消 ${counts.cancelled}` : '',
  ].filter(Boolean).join(' · '))}</span>`
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
  if (!pendingSubmissionBusy) submitSelected.textContent = `提交所选 ${selectedCount}`
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
      log(`刷新检测状态失败：${error}`)
      schedulePendingRefresh(pendingItems)
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
  renderPendingBatchStatus()
  for (const id of [...selectedPendingIDs]) {
    if (!items.some(item => item.id === id && pendingCanSubmit(item))) selectedPendingIDs.delete(id)
  }
  $('#pending-list').classList.toggle('empty', !items.length)
  $('#pending-list').innerHTML = items.length
    ? groupTakeoverItems(items.map(item => ({ ...item, agent_type: item.agent_type }))).map(group => `
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
                ? `<label class="pending-skill-select" title="选择 ${escapeHtml(item.skill_name)}"><input type="checkbox" data-select-pending="${escapeHtml(item.id)}"${selectedPendingIDs.has(item.id) ? ' checked' : ''} /></label>`
                : '<span class="pending-select-placeholder"></span>'}
              <div><strong>${escapeHtml(item.skill_name)}</strong><button class="path-link" type="button" title="${escapeHtml(item.pending_path)}" data-reveal-path="${escapeHtml(item.pending_path)}">${escapeHtml(item.pending_path)}</button></div>
              <div class="pending-status-block">
                <span class="result-status ${escapeHtml(pendingStatusClass(item.status))}"><i></i>${escapeHtml(pendingStatusLabel(item.status))}</span>
                <small>${escapeHtml(pendingStatusGuidance(item))}</small>
              </div>
              <div class="takeover-row-actions">
                ${item.status === 'APPROVED'
                  ? `<button class="action-success icon-button icon-install" data-install-approved="${escapeHtml(item.id)}" data-agent-type="${escapeHtml(item.agent_type)}" data-skill-id="${escapeHtml(item.skill_id)}">立即安装</button>`
                  : item.skill_id
                  ? `<span class="pending-next">${escapeHtml(pendingNextLabel(item.status))}</span>`
                  : `<button class="primary icon-button icon-submit" data-submit-pending="${escapeHtml(item.id)}">提交平台检测</button>`}
              </div>
            </div>`).join('')}
        </div>
      </details>`).join('')
    : '<div class="empty">当前没有停用待处理的 Skill</div>'
  document.querySelectorAll('[data-select-pending]').forEach(input => input.addEventListener('change', () => {
    if (input.checked) selectedPendingIDs.add(input.dataset.selectPending)
    else selectedPendingIDs.delete(input.dataset.selectPending)
    syncPendingBatchControls()
  }))
  document.querySelectorAll('[data-submit-pending]').forEach(button => button.addEventListener('click', async () => {
    await submitPendingIDs([button.dataset.submitPending], button)
  }))
  document.querySelectorAll('[data-install-approved]').forEach(button => button.addEventListener('click', async () => {
    setBusy(button, true)
    try {
      await installPlatformSkill(button.dataset.agentType, button.dataset.skillId, button.dataset.installApproved)
      await refreshAfterInstall()
      showMessageDialog('安装完成', 'Skill 已安装到目标 Agent。多个 Agent 安装同一 Skill 时会共用平台内容目录。')
    } catch (error) {
      showMessageDialog('安装失败', String(error))
      log(error)
    } finally {
      setBusy(button, false)
    }
  }))
  syncPendingBatchControls()
  schedulePendingRefresh(items)
  if (refresh && !silent) log(`待处理区共有 ${items.length} 个 Skill`)
  return items
}

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
      title: `正在提交平台检测 0/${ids.length}`,
      detail: queuedNames.length ? `本次共 ${ids.length} 个：${queuedNames.join('、')}` : '正在读取待处理 Skill...',
      current: 0,
      total: ids.length,
    })
    let currentItems = JSON.parse(await run('pending'))
    for (let index = 0; index < ids.length; index += 1) {
      const id = ids[index]
      button.textContent = ids.length > 1 ? `正在提交 ${index + 1}/${ids.length}` : '正在提交...'
      const current = currentItems.find(item => item.id === id)
      if (!current || current.skill_id) continue
      updateOperationProgress('#pending-progress', {
        title: `正在提交平台检测 ${index + 1}/${ids.length}`,
        detail: `当前：${current.skill_name || id}`,
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
        title: `正在提交平台检测 ${index + 1}/${ids.length}`,
        detail: `已完成 ${index + 1} 个，成功 ${submitted.length} 个，失败 ${failures.length} 个。`,
        current: index + 1,
        total: ids.length,
      })
    }
    if (submittedIDs.length) {
      pendingBatchTracking = { ids: new Set(submittedIDs) }
    }
    await loadPending()
    if (submitted.length) {
      renderPendingBatchStatus()
      log(`已提交平台检测：${submitted.join('、')}`)
    }
    if (failures.length) {
      const permissionDenied = failures.some(item => item.detail.includes('client:submit-skill') || item.detail.includes('scanner:submit'))
      const detail = permissionDenied
        ? '当前客户端凭证没有提交 Skill 的权限。请前往 Agent Manager 的“凭证管理”，编辑当前客户端凭证并勾选 client:submit-skill。'
        : failures.map(item => `${item.name}：${item.detail}`).join('\n')
      showMessageDialog(permissionDenied ? '缺少提交权限' : '部分 Skill 提交失败', detail)
      showTakeoverFeedback('error', '提交检测未全部完成', detail)
      log(detail)
    }
  } catch (error) {
    const detail = String(error)
    showMessageDialog('批量提交失败', detail)
    showTakeoverFeedback('error', '批量提交失败', detail)
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
    showMessageDialog('正在提交平台检测', '批量提交完成后会自动刷新待处理状态，无需重复操作。')
    return
  }
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await loadPending(true)
  } catch (error) {
    showMessageDialog('刷新检测状态失败', String(error))
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
      ? findings.length ? `巡检完成，发现 ${findings.length} 个异常：${findings.map(item => item.skill_name).join('、')}` : '巡检完成，未发现异常'
      : success)
  } catch (error) {
    showMessageDialog('操作失败', String(error))
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
  throw new Error('完整巡检尚未在 45 秒内完成，请查看后台服务状态或稍后重试')
}
$('#run-once').addEventListener('click', event => runStatusCommand(event.currentTarget, 'run-once', '巡检已完成'))
const toggleGovernance = button => {
  const enabled = Boolean(connection?.local?.governance_enabled)
  runStatusCommand(button, enabled ? 'pause-governance' : 'resume-governance', enabled ? '持续治理已暂停' : '持续治理已恢复')
}
$('#toggle-governance').addEventListener('click', event => toggleGovernance(event.currentTarget))
$('#toggle-takeover').addEventListener('click', event => toggleGovernance(event.currentTarget))
$('#install-service').addEventListener('click', event => runStatusCommand(event.currentTarget, 'install-service', '后台服务已启用'))
$('#uninstall-service').addEventListener('click', () => $('#stop-service-dialog').showModal())
$('#confirm-stop-service').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('uninstall-service')
    await refreshConnection()
    $('#stop-service-dialog').close()
    showMessageDialog('后台服务已停止', '现在可以安全备份或移动 ~/.agent-manager。重新启用后台服务后，客户端会继续同步任务和巡检 Skill。')
    log('后台服务已停止')
  } catch (error) {
    $('#stop-service-dialog').close()
    showMessageDialog('停止后台服务失败', String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})
$('#refresh-records').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try { await refreshConnection() } finally { setBusy(button, false) }
})

$('#overview-sync').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try { await refreshConnection() } finally { setBusy(button, false) }
})
$('#edit-connection').addEventListener('click', editConnection)
$('#cancel-edit').addEventListener('click', () => {
  $('#connect-form').hidden = true
  $('#token').value = ''
})
document.querySelectorAll('[data-target-panel]').forEach(button => {
  button.addEventListener('click', () => showPanel(button.dataset.targetPanel))
})

$('#check-update').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const result = await invoke('check_client_update', { install: false })
    if (!result.available) return log('当前已是最新版本')
    pendingClientUpdate = result
    $('#update-dialog-title').textContent = `发现新版本 ${result.version}`
    $('#update-dialog-notes').textContent = result.notes || '更新将先暂停后台服务，安装完成后自动重启前台并恢复后台巡检。'
    $('#client-update-progress').hidden = true
    $('#cancel-client-update').disabled = false
    $('#confirm-client-update').disabled = false
    $('#update-dialog').showModal()
  } catch (error) {
    log(error)
  } finally {
    setBusy(button, false)
  }
})

$('#cancel-client-update').addEventListener('click', () => {
  if (clientUpdateInstalling) return
  $('#update-dialog').close()
  if (pendingClientUpdate?.version) log(`发现新版本 ${pendingClientUpdate.version}，已选择稍后更新`)
  pendingClientUpdate = null
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
    const result = await invoke('check_client_update', { install: true })
    if (!result.available) {
      $('#update-dialog').close()
      showMessageDialog('无需更新', '当前已经是最新版本。')
    }
  } catch (error) {
    $('#update-dialog').close()
    showMessageDialog('更新失败', String(error))
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
    : '<option value="">暂无备份</option>'
  return backups
}
$('#refresh-backups').addEventListener('click', async event => {
  const button = event.currentTarget
  setBusy(button, true)
  try {
    const backups = await loadBackups()
    log(`找到 ${backups.length} 个可恢复备份`)
  } catch (error) {
    showMessageDialog('读取备份失败', String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})
$('#restore-backup').addEventListener('click', async event => {
  const backup = $('#backup-select').value
  if (!backup) return log('请选择要恢复的备份')
  if (!window.confirm(`确认恢复备份 ${backup}？当前同名 Skill 会先备份。`)) return
  const button = event.currentTarget
  setBusy(button, true)
  try {
    await run('restore', ['--backup', backup, '--confirm'])
    log(`备份 ${backup} 已恢复`)
    showMessageDialog('备份恢复完成', '对应 Agent 的同名 Skill 已恢复。建议立即执行一次同步与巡检。')
  } catch (error) {
    showMessageDialog('恢复备份失败', String(error))
    log(error)
  } finally {
    setBusy(button, false)
  }
})

const loadQuarantine = async () => {
  const items = JSON.parse(await run('quarantine'))
  $('#quarantine-list').classList.toggle('empty', !items.length)
  $('#quarantine-list').innerHTML = items.length ? items.map(item => `
    <div class="takeover-row quarantine-row">
      <div><strong>${escapeHtml(item.skill_name)}</strong><button class="path-link" type="button" title="隔离目录：${escapeHtml(item.quarantine_path)}" data-reveal-path="${escapeHtml(item.quarantine_path)}">所属 Agent：${escapeHtml(agentLabel(item.agent_type))} · ${escapeHtml(item.original_path)}</button></div>
      <strong class="action-pending">已隔离</strong>
      <span>${escapeHtml(reasonLabel(item.reason))}</span>
      <button class="icon-button icon-install" data-install-safe-version="${escapeHtml(item.skill_name)}">选择批准版本</button>
    </div>`).join('') : '<div class="empty">当前没有隔离的 Skill</div>'
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
    log(`隔离区共有 ${items.filter(item => item.status === 'quarantined').length} 个待处理 Skill`)
  } catch (error) {
    showMessageDialog('读取隔离区失败', String(error))
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
    'global-skills': '通用 Skills',
    codebuddy: 'CodeBuddy',
    workbuddy: 'WorkBuddy',
  }[value] || value
}

function taskTypeLabel(task) {
  const value = task?.task_type || task
  if (value === 'rescan' && task?.payload?.reason === 'policy_changed') return '同步处理策略'
  return { install_skill: '安装 Skill', remove_skill: '移除 Skill', repair_skill: '修复 Skill', rescan: '同步客户端清单', sync_policy: '同步处理策略' }[value] || value || `平台任务`
}

function taskStatusLabel(value) {
  return { pending: '等待客户端执行', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }[value] || value || '-'
}

function eventTypeLabel(value) {
  return {
    client_registered: '客户端注册', takeover_completed: '治理范围更新', unmanaged_skill_found: '发现未受管 Skill',
    unmanaged_skill_verified: 'Skill 校验通过', skill_installed: '安装 Skill', skill_removed: '移除 Skill',
    skill_modified: '发现 Skill 修改', skill_repaired: '自动恢复 Skill', skill_blocked: '阻断 Skill',
    skill_quarantined: '隔离 Skill', skill_quarantine_restored: '恢复隔离 Skill',
  }[value] || value || '安全事件'
}

function eventDetail(value) {
  return { skill_repaired: '已恢复为平台批准版本', skill_modified: '检测到本地内容变化', skill_blocked: '已阻止异常内容继续使用', skill_quarantined: '已移入隔离区' }[value] || '-'
}

const eventStatus = value => value === 'skill_modified' ? 'running' : ['skill_blocked', 'skill_quarantined'].includes(value) ? 'failed' : 'succeeded'
const eventResultLabel = value => value === 'skill_modified' ? '已发现' : ['skill_blocked', 'skill_quarantined'].includes(value) ? '已处置' : '已完成'

function agentKind(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '').replace(/^claude$/, 'claudecode').replace(/^geminicli$/, 'gemini')
}

function reasonLabel(value) {
  return {
    allowed: '已批准且内容一致',
    skill_not_found: '平台未登记该 Skill',
    skill_not_approved: 'Skill 尚未审批通过',
    signature_mismatch: '本地内容与平台签名不一致',
    managed_agent_not_found: '未绑定可用的平台智能体',
    agent_not_authorized: '该智能体未获准使用此 Skill',
    local_agent_not_found: '未找到该 Agent 的本地登记信息',
    unmanaged_skill: '未纳入 Agent Manager 治理',
    already_managed: '已完成接管，无需重复处理',
    not_compared: '尚未完成平台比对',
    legacy_pending: '接管后已停用，等待提交平台检测',
  }[value] || value || '-'
}

function pendingStatusLabel(value) {
  return {
    pending: '待检测',
    submitted: '检测中',
    PENDING: '检测中',
    VETTED: '待人工审核',
    APPROVED: '检测通过',
    REJECTED: '检测未通过',
    CANCELLED: '检测已取消',
  }[value] || value || '待检测'
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
    `${items.length} 个 Skill`,
    actionable ? `待检测 ${actionable}` : '',
    review ? `待审核 ${review}` : '',
  ].filter(Boolean).join(' · ')
}

function pendingStatusGuidance(item) {
  if (item.status === 'APPROVED') return '平台已批准，可在客户端管理中下发安装'
  if (item.status === 'REJECTED') return '平台未通过，继续保持停用；请到 Skill 详情查看判断依据'
  if (item.status === 'CANCELLED') return '平台检测已取消，继续保持停用'
  if (item.status === 'VETTED') return '自动检测已完成，等待平台人工审核'
  if (item.skill_id) return `平台正在检测${item.skill_id ? ` · ${item.skill_id}` : ''}`
  return reasonLabel(item.reason)
}

function pendingNextLabel(status) {
  if (status === 'REJECTED') return '保持停用'
  if (status === 'CANCELLED') return '保持停用'
  if (status === 'VETTED') return '等待审批'
  return '等待检测'
}

const managedAgentIDFor = agentType => (connection?.platform?.agents || []).find(item => item.agent_type === agentType)?.managed_agent_id || ''

const installPlatformSkill = async (agentType, skillId, pendingId = '') => {
  const args = ['--agent-type', agentType, '--skill-id', skillId]
  const managedAgentID = managedAgentIDFor(agentType)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  if (pendingId) args.push('--id', pendingId)
  await run('install-skill', args)
  log(`已安装 Skill ${skillId} 到 ${agentLabel(agentType)}`)
}

const refreshAfterInstall = async () => {
  await refreshConnection()
  if ($('#takeover').classList.contains('active')) await preview(false)
}

const availableSkillsForAgent = async (agent, query = '') => {
  const agentType = agent.agent_type
  const args = ['--agent-type', agentType]
  const managedAgentID = managedAgentIDFor(agentType)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  if (query) args.push('--query', query)
  try {
    return { agent, items: JSON.parse(await run('available-skills', args)), error: '' }
  } catch (error) {
    return { agent, items: [], error: String(error) }
  }
}

const loadInstallCatalog = async (agents, query = '') => {
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

const installSkills = () => {
  const skills = new Map()
  installCatalog.flatMap(item => item.items).forEach(item => skills.set(item.skill_id, item))
  if (lockedInstallSkill) skills.set(lockedInstallSkill.skill_id, lockedInstallSkill)
  return [...skills.values()]
}

const loadInstallSkillPreview = async () => {
  const skill = selectedInstallSkill()
  if (!skill) {
    $('#install-skill-preview').innerHTML = '<span>选择 Skill 后可查看说明</span>'
    return
  }
  const source = installCatalog.find(item => item.items.some(candidate => candidate.skill_id === skill.skill_id))
  if (!source) {
    $('#install-skill-preview').innerHTML = `<strong>${escapeHtml(skill.name)}</strong><span>当前客户端无权读取该 Skill 的详情</span>`
    return
  }
  const args = ['--skill-id', skill.skill_id, '--agent-type', source.agent.agent_type]
  const managedAgentID = managedAgentIDFor(source.agent.agent_type)
  if (managedAgentID) args.push('--managed-agent-id', managedAgentID)
  $('#install-skill-preview').innerHTML = `<strong>${escapeHtml(skill.name)}</strong><span>正在读取说明...</span>`
  try {
    const item = JSON.parse(await run('skill-preview', args))
    if (selectedInstallSkill()?.skill_id !== skill.skill_id) return
    $('#install-skill-preview').innerHTML = `<strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.description || '该 Skill 未提供说明')}</span><small>状态：已批准${item.risk_level ? ` · 风险等级：${escapeHtml(item.risk_level)}` : ''}${item.submitted_at ? ` · 提交时间：${escapeHtml(formatTime(item.submitted_at))}` : ''}</small>`
  } catch (error) {
    $('#install-skill-preview').innerHTML = `<strong>${escapeHtml(skill.name)}</strong><span>说明读取失败：${escapeHtml(error)}</span>`
  }
}

const renderInstallSkillOptions = () => {
  if (lockedInstallSkill) return
  const query = $('#install-skill-search').value.trim().toLowerCase()
  const current = $('#install-platform-skill').value
  const skills = installSkills().filter(item => !query || item.name.toLowerCase().includes(query))
  $('#install-platform-skill').innerHTML = `<option value="">${skills.length ? '请选择已批准的 Skill' : '没有匹配的 Skill'}</option>${skills.map(item => `<option value="${escapeHtml(item.skill_id)}">${escapeHtml(item.name)}${item.submitted_at ? ` · 提交于 ${escapeHtml(formatTime(item.submitted_at))}` : ''}</option>`).join('')}`
  if (skills.some(item => item.skill_id === current)) $('#install-platform-skill').value = current
  renderInstallTargets()
  loadInstallSkillPreview()
}

const renderInstallTargets = () => {
  const skill = selectedInstallSkill()
  if (!skill) {
    $('#install-agent-targets').innerHTML = '<span>请先选择 Skill</span>'
    return
  }
  $('#install-agent-targets').innerHTML = installCatalog.map(({ agent, items, error }) => {
    const sourceAgent = lockedInstallSkill?.source_agent_type === agent.agent_type
    const installed = sourceAgent || (agent.skills || []).some(item => item.skill_id === skill.skill_id)
    const conflict = !installed && (agent.skills || []).some(item => item.name === skill.name && item.status !== 'broken_link')
    const available = items.some(item => item.skill_id === skill.skill_id)
    const disabled = installed || conflict || !available
    const status = sourceAgent ? '当前所在 Agent' : installed ? '已安装' : conflict ? '存在同名 Skill' : available ? '可安装' : error ? '不可用' : '未授权'
    const kind = conflict ? 'conflict' : available && !installed ? 'available' : ''
    return `<label class="install-agent-target ${kind}" title="${escapeHtml(error)}">
      <span><input type="checkbox" data-install-target value="${escapeHtml(agent.agent_type)}" ${disabled ? 'disabled' : ''} />${escapeHtml(agentLabel(agent.agent_type))}</span>
      <em>${status}</em>
    </label>`
  }).join('') || '<span>没有支持 Skill 管理的 Agent</span>'
}

const openInstallDialog = async (skill, initialQuery = '') => {
  const agents = (inventory?.agents || []).filter(item => item.skill_management_supported)
  if (!agents.length) return showMessageDialog('没有可安装目标', '请先发现支持 Skill 管理的 Agent。')
  lockedInstallSkill = skill || null
  installCatalog = []
  $('#install-skill-search').value = initialQuery
  $('#install-skill-search-label').hidden = Boolean(skill)
  $('#install-skill-title').textContent = skill ? `安装 ${skill.name} 到其他 Agent` : '从平台安装 Skill'
  $('#install-platform-skill').disabled = true
  $('#install-platform-skill').innerHTML = `<option value="">${skill ? escapeHtml(skill.name) : '正在读取平台 Skill...'}</option>`
  $('#install-agent-targets').innerHTML = '<span>正在检查可安装的 Agent...</span>'
  $('#install-skill-dialog').showModal()
  try {
    installCatalog = await loadInstallCatalog(agents, initialQuery)
    if (skill) {
      $('#install-platform-skill').innerHTML = `<option value="${escapeHtml(skill.skill_id)}">${escapeHtml(skill.name)}</option>`
      $('#install-platform-skill').value = skill.skill_id
      $('#install-platform-skill').disabled = true
      renderInstallTargets()
      loadInstallSkillPreview()
    } else {
      $('#install-platform-skill').disabled = false
      renderInstallSkillOptions()
    }
  } catch (error) {
    $('#install-skill-dialog').close()
    showMessageDialog('读取平台 Skill 失败', String(error))
  }
}

$('#platform-install-button').addEventListener('click', () => openInstallDialog())
$('#install-skill-search').addEventListener('input', () => {
  clearTimeout(installSearchTimer)
  installSearchTimer = setTimeout(async () => {
    const query = $('#install-skill-search').value.trim()
    const agents = (inventory?.agents || []).filter(item => item.skill_management_supported)
    $('#install-platform-skill').disabled = true
    $('#install-platform-skill').innerHTML = '<option>正在搜索平台 Skill...</option>'
    try {
      const result = await loadInstallCatalog(agents, query)
      if ($('#install-skill-search').value.trim() !== query) return
      installCatalog = result
      $('#install-platform-skill').disabled = false
      renderInstallSkillOptions()
    } catch (error) {
      $('#install-platform-skill').innerHTML = '<option>搜索失败</option>'
      showMessageDialog('搜索 Skill 失败', String(error))
    }
  }, 300)
})
$('#install-platform-skill').addEventListener('change', () => {
  renderInstallTargets()
  loadInstallSkillPreview()
})
$('#cancel-install-skill').addEventListener('click', () => {
  lockedInstallSkill = null
  $('#install-skill-dialog').close()
})
$('#confirm-install-skill').addEventListener('click', async event => {
  const skill = selectedInstallSkill()
  if (!skill) return showMessageDialog('请选择 Skill', '请先选择需要安装的平台 Skill。')
  const targets = [...document.querySelectorAll('[data-install-target]:checked')].map(item => item.value)
  if (!targets.length) return showMessageDialog('请选择目标 Agent', '至少选择一个需要安装该 Skill 的 Agent。')
  const button = event.currentTarget
  setBusy(button, true)
  const succeeded = []
  const failed = []
  try {
    for (const agentType of targets) {
      try {
        await installPlatformSkill(agentType, skill.skill_id)
        succeeded.push(agentLabel(agentType))
      } catch (error) {
        failed.push(`${agentLabel(agentType)}：${String(error)}`)
      }
    }
    await refreshAfterInstall()
    lockedInstallSkill = null
    $('#install-skill-dialog').close()
    showMessageDialog(!succeeded.length ? '安装失败' : failed.length ? '部分安装完成' : '安装完成', [
      succeeded.length ? `${skill.name} 已安装到：${succeeded.join('、')}。` : '',
      failed.length ? `未安装：\n${failed.join('\n')}` : '多个 Agent 共用同一份受管内容。',
    ].filter(Boolean).join('\n'))
  } catch (error) {
    showMessageDialog('安装状态刷新失败', `安装命令已经执行，但页面状态刷新失败：${String(error)}`)
    log(error)
  } finally {
    setBusy(button, false)
  }
})

function renderCapability(selector, capability) {
  const element = $(selector)
  const enabled = Boolean(capability?.enabled)
  element.className = enabled ? 'available' : 'unavailable'
  element.textContent = enabled ? `已启用${capability.detail ? ` · ${capability.detail}` : ''}` : '未配置'
}

function escapeHtml(value) {
  const node = document.createElement('span')
  node.textContent = String(value ?? '')
  return node.innerHTML
}

invoke('get_build_version').then(version => { $('#client-build-version').textContent = `版本 ${version}` })
const initializeClient = async () => {
  try {
    const result = JSON.parse(await run('reconcile-service'))
    if (result.restarted) log('检测到客户端后台程序已更新，后台服务已自动重启')
  } catch (error) {
    log(`后台服务自检失败：${error}`)
  }
  await refreshConnection()
}
initializeClient()
setInterval(refreshChangedInventory, 3000)
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshChangedInventory()
})
