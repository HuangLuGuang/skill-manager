(() => {
  const invoke = window.__TAURI__?.core?.invoke
  if (!invoke) return
  const $ = id => document.getElementById(`system-collection-${id}`)
  const t = key => window.clientI18n.t(`ui.systemCollection.${key}`)
  const designText = key => window.clientI18n.t(`ui.governanceDesign.${key}`)
  let status = { state: 'stopped' }, busy = '', error = '', polling = false, renderedEvents = ''
  const targetEl = id => document.getElementById(`system-targets-${id}`)
  const tt = (key, values = {}) => window.clientI18n.t(`ui.systemTargets.${key}`).replace(/\{(\w+)\}/g, (match, name) => values[name] ?? match)
  let targets = null, targetBusy = false, targetError = '', selection = new Set(), dirty = false, discoveryRequest = null, renderedTargets = ''
  const names = { codex: 'Codex', claude: 'Claude Code', workbuddy: 'WorkBuddy' }
  const productName = product => names[product] || tt('custom')
  const isActive = () => ['collecting', 'starting', 'draining', 'degraded'].includes(status.state)
  const allowed = item => targets?.enabled && targets?.configured && item.availability === 'available' && targets.requirements.products.includes(item.product)
  const selectedItems = () => (targets?.items || []).filter(item => selection.has(item.id))
  const validSelection = () => {
    const items = selectedItems()
    return targets && items.length > 0 && items.every(allowed) && (targets.requirements.selection_mode !== 'platform' || targets.requirements.products.every(product => items.some(item => item.product === product)))
  }
  function renderTargets() {
    const active = isActive(), list = targetEl('list')
    targetEl('discover').disabled = targetBusy || !!busy
    targetEl('add').disabled = targetBusy || !!busy || !targetEl('custom').value.trim()
    targetEl('apply').hidden = !active
    targetEl('apply').disabled = targetBusy || !!busy || !dirty || !validSelection()
    targetEl('apply').setAttribute('aria-busy', String(busy === 'apply'))
    const available = (targets?.items || []).filter(item => item.availability === 'available')
    targetEl('description').textContent = targetBusy ? tt('discovering') : tt('found', { products: new Set(available.map(item => item.product)).size, count: available.length })
    targetEl('policy').hidden = !targets || (!!targets.enabled && targets.configured)
    targetEl('policy').textContent = tt(targets?.configured ? 'disabled' : 'notConfigured')
    targetEl('scope').textContent = targets?.configured ? tt(targets.requirements.selection_mode === 'platform' ? 'required' : 'allowed', { products: targets.requirements.products.map(productName).join(window.clientI18n.getLocale() === 'zh-CN' ? '、' : ', ') || '—' }) : ''
    targetEl('error').hidden = !targetError
    targetEl('error').textContent = targetError ? codeText(targetError) : ''
    const items = selectedItems()
    targetEl('count').textContent = tt('selected', { products: new Set(items.map(item => item.product)).size, entries: items.length })
    targetEl('next').textContent = tt(active ? 'applyHint' : 'startHint')
    const signature = JSON.stringify([targets, [...selection], targetBusy, busy, window.clientI18n.getLocale()])
    if (signature === renderedTargets) return
    renderedTargets = signature
    const focused = list.contains(document.activeElement) ? document.activeElement.dataset.id : null
    const expanded = new Set([...list.querySelectorAll('details[open]')].map(item => item.dataset.id))
    list.replaceChildren()
    if (targets && !targets.items.length && !targetBusy) { const empty = document.createElement('p'); empty.className = 'system-target-empty'; empty.textContent = tt('empty'); list.append(empty) }
    const groups = new Map()
    for (const item of targets?.items || []) {
      if (!groups.has(item.product)) {
        const group = document.createElement('section'), heading = document.createElement('h3')
        group.className = 'system-target-group'
        if (names[item.product]) { const icon = document.createElement('img'); icon.src = `assets/icons/${item.product === 'claude' ? 'claude-color.svg' : item.product + '.png'}`; icon.alt = ''; icon.width = 28; icon.height = 28; heading.append(icon) }
        heading.append(document.createTextNode(productName(item.product))); group.append(heading); list.append(group); groups.set(item.product, group)
      }
      const row = document.createElement('div'); row.className = 'system-target-row'
      const label = document.createElement('label'), input = document.createElement('input')
      input.type = 'checkbox'; input.checked = selection.has(item.id); input.disabled = targetBusy || !!busy || !allowed(item)
      input.dataset.id = item.id
      input.addEventListener('change', () => { input.checked ? selection.add(item.id) : selection.delete(item.id); dirty = true; render() })
      label.append(input)
      const title = document.createElement('span'), name = document.createElement('strong'), entry = document.createElement('small')
      const app = item.path.split('/').find(part => part.endsWith('.app'))?.slice(0, -4)
      const entryName = tt(item.availability === 'not_native' ? 'nonNativeEntry' : `entry.${item.entry}`)
      name.textContent = app ? `${app} · ${entryName}` : entryName
      input.setAttribute('aria-label', `${productName(item.product)} · ${name.textContent}`)
      entry.textContent = item.availability === 'not_native' ? tt('nonNativeHint') : item.path
      entry.className = 'system-target-location'
      title.append(name, entry); label.append(title)
      const availability = document.createElement('span'); availability.className = 'system-target-availability'; availability.dataset.state = item.availability
      availability.textContent = tt(`availability.${item.availability}`)
      const details = document.createElement('details'), summary = document.createElement('summary'), path = document.createElement('code')
      details.dataset.id = item.id; details.open = expanded.has(item.id); summary.textContent = tt('detail'); path.textContent = item.path; details.append(summary, path)
      if (item.product === 'workbuddy') { const note = document.createElement('p'); note.textContent = tt('workbuddyHint'); details.append(note) }
      row.append(label, availability, details); groups.get(item.product).append(row)
      if (focused === item.id) input.focus()
    }
  }
  async function loadTargets(action = 'targets', custom = '') {
    if (targetBusy || busy) return false
    targetBusy = true; targetError = ''; render()
    try {
      const next = await invoke('aidr_system_targets', { action, custom: custom || null })
      if (targets && targets.binding !== next.binding) { dirty = false; selection = new Set(); discoveryRequest = null }
      targets = next
      if (!dirty) selection = new Set(next.selected_ids)
      selection = new Set([...selection].filter(id => next.items.some(item => item.id === id)))
      if (next.requirements.selection_mode === 'platform') {
        for (const product of next.requirements.products) {
          const candidates = next.items.filter(item => item.product === product && allowed(item))
          if (candidates.length === 1 && !selection.has(candidates[0].id)) { selection.add(candidates[0].id); dirty = true }
        }
      }
      if (action !== 'targets') discoveryRequest = next.discovery_request
      return true
    } catch (e) { targetError = String(e); return false }
    finally { targetBusy = false; render() }
  }
  async function applyTargets(start) {
    if (busy || targetBusy || !validSelection()) return
    const version = targets.version, binding = targets.binding, selected = [...selection]
    // Fresh discovery and binary identity checks precede each signed selection.
    dirty = true
    if (!await loadTargets('discover')) return
    if (targets.binding !== binding || targets.version !== version || selected.some(id => !targets.items.some(item => item.id === id)) || !validSelection()) {
      targetError = 'aidr.system_candidate_changed'; render(); return
    }
    busy = start ? 'start' : 'apply'; error = ''; render()
    try {
      targets = await invoke('aidr_system_targets', { action: 'select', selection: { binding: targets.binding, expected_version: targets.version, expected_revision: targets.revision, ids: selected } })
      selection = new Set(targets.selected_ids); dirty = false
      if (start) status = await invoke('aidr_system_action', { action: 'start' })
    } catch (e) { error = String(e) }
    finally { busy = ''; await refresh() }
  }
  const codeText = code => {
    if (!code) return ''
    const key = `ui.systemCollection.code.${code}`
    const text = window.clientI18n.t(key)
    return text === key ? `${t('failure')} (${code})` : text
  }
  const date = value => value ? new Date(value).toLocaleString(window.clientI18n.getLocale()) : '—'
  const commandText = argv => argv.map(arg => /^[a-zA-Z0-9_./:=+-]+$/.test(arg) ? arg : "'" + arg.replaceAll("'", "'\\''") + "'").join(' ')
  const row = (list, label, value) => {
    const div = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd')
    dt.textContent = label; dd.textContent = value; div.append(dt, dd); list.append(div)
  }
  function render() {
    const active = ['collecting', 'starting', 'draining', 'degraded'].includes(status.state)
    $('state').textContent = t(`state.${busy === 'start' ? 'authorizing' : busy === 'stop' ? 'draining' : status.state}`)
    $('start').disabled = !!busy || targetBusy || active || !validSelection()
    $('stop').disabled = !!busy || !active
    $('start').hidden = active
    $('stop').hidden = !active
    $('state').dataset.state = busy || status.state
    renderTargets()
    for (const name of ['start', 'stop', 'settings', 'reveal']) $(name).setAttribute('aria-busy', String(busy === name))
    $('development').hidden = !status.development
    const failure = error || status.code
    $('error').hidden = !failure
    $('error').textContent = codeText(failure)
    if (failure === 'aidr_enforcement_fda_required') $('permissions').open = true
    const summary = $('summary'); summary.replaceChildren()
    row(summary, t('device'), status.device || '—')
    row(summary, t('server'), status.server || '—')
    row(summary, t('configuredMode'), t(`mode.${status.target_mode || 'unknown'}`))
    row(summary, t('effectiveMode'), t(`mode.${status.state === 'collecting' ? status.mode || 'unknown' : 'unknown'}`))
    row(summary, t('subscription'), date(status.health_at))
    const networkState = ['collecting', 'degraded'].includes(status.state) && Math.abs(Date.now() - Date.parse(status.health_at)) < 10000 ? status.network_health?.state || 'unreported' : status.state === 'stopped' ? 'stopped' : 'unreported'
    row(summary, t('network.title'), t(`network.health.${networkState}`))
    row(summary, t('upload'), status.upload_code ? codeText(status.upload_code) : date(status.uploaded_at))
    row(summary, t('pending'), status.pending_uploads == null ? t('unknown') : String(status.pending_uploads))
    row(summary, t('count'), String(status.event_count || 0))
    const overview = $('overview'); overview.replaceChildren()
    row(overview, t('effectiveMode'), t(`mode.${status.state === 'collecting' ? status.mode || 'unknown' : 'unknown'}`))
    row(overview, designText('processFiles'), t(`state.${status.state}`))
    row(overview, t('network.title'), t(`network.health.${networkState}`))
    row(overview, t('pending'), status.pending_uploads == null ? t('unknown') : String(status.pending_uploads))
    row(overview, t('upload'), status.upload_code ? codeText(status.upload_code) : date(status.uploaded_at))
    const scope = document.createElement('p'); scope.className = 'governance-scope-note'; scope.textContent = designText('systemScope'); overview.append(scope)
    const eventSignature = JSON.stringify([status.recent, window.clientI18n.getLocale()])
    if (eventSignature === renderedEvents) return
    renderedEvents = eventSignature
    const events = $('events')
    const expanded = new Set([...events.querySelectorAll('details[open]')].map(el => el.dataset.event))
    events.replaceChildren()
    if (!status.recent?.length) { const p = document.createElement('p'); p.textContent = t('empty'); events.append(p) }
    for (const record of status.recent || []) {
      const item = document.createElement('div'); item.className = 'runtime-evidence-item'
      const heading = document.createElement('strong'), detail = document.createElement('p')
      const time = document.createElement('time')
      time.className = 'governance-event-time'
      time.dateTime = new Date(Number(BigInt(record.time_ns) / 1000000n)).toISOString()
      time.textContent = date(time.dateTime)
      heading.textContent = `${t(record.network ? 'network.title' : record.kind === 'file' ? `file.${record.operation}` : `transition.${record.transition}`)} · PID ${record.process.pid}`
      detail.textContent = record.argv?.length && record.kind !== 'file' ? commandText(record.argv) : record.destination_path ? `${record.path} → ${record.destination_path}` : record.path || '—'
      if (record.network) {
        const n = record.network, endpoint = (ip, port) => `${ip.includes(':') ? `[${ip}]` : ip}:${port}`
        detail.textContent = `${record.executable || '—'}\n${endpoint(n.local_ip, n.local_port)} ↔ ${endpoint(n.remote_ip, n.remote_port)} · ${n.protocol.toUpperCase()}\n${t(`network.states.${n.state}`)}`
      }
      detail.style.whiteSpace = 'pre-wrap'
      if (record.exit_code != null) heading.textContent += ` · ${t('exitCode')}: ${record.exit_code}`
      if (record.exit_signal != null) heading.textContent += ` · ${t('exitSignal')}: ${record.exit_signal}`
      if (record.argv_truncated || record.paths_truncated) detail.textContent += `\n${t('truncated')}`
      if (record.activity_origin === 'client_probe') detail.textContent += `\n${t('clientProbe')}`
      const attribution = document.createElement('p')
      const relation = ['direct', 'inherited'].includes(record.relation) ? record.relation : 'unknown'
      attribution.textContent = `${t(`relation.${relation}`)}${record.root?.pid && record.root.pid !== '0' ? ` · ${t('rootProcess')} ${record.root.pid}` : ''}`
      const diagnostics = document.createElement('details'), title = document.createElement('summary'), fields = document.createElement('dl')
      diagnostics.dataset.event = `${record.monitor_id}:${record.sequence}`
      diagnostics.open = expanded.has(diagnostics.dataset.event)
      title.textContent = t('eventDiagnostics')
      row(fields, t('processIdentity'), `${record.process.pid} / ${record.process.pidversion} / ${record.process.start_us}`)
      if (record.cwd) row(fields, t('cwd'), record.cwd)
      row(fields, t('monitor'), record.monitor_id)
      row(fields, t('sequence'), record.sequence)
      diagnostics.append(title, fields)
      const content = document.createElement('div'); content.className = 'governance-event-content'
      content.append(heading, detail, attribution, diagnostics)
      item.append(time, content); events.append(item)
    }
  }
  async function refresh() {
    if (polling) return
    polling = true
    try { status = await invoke('aidr_system_action', { action: 'status' }) }
    catch (e) { status = { ...status, state: 'unknown' }; error = String(e) }
    finally { polling = false; render() }
  }
  async function action(name) {
    if (busy) return
    busy = name; error = ''; render()
    try {
      const result = await invoke('aidr_system_action', { action: name })
      if (result.state) status = result
    } catch (e) { error = String(e) }
    finally { busy = ''; await refresh() }
  }
  for (const name of ['stop', 'settings', 'reveal']) $(name).addEventListener('click', () => void action(name))
  $('start').addEventListener('click', () => void applyTargets(true))
  targetEl('apply').addEventListener('click', () => void applyTargets(false))
  targetEl('discover').addEventListener('click', () => void loadTargets('discover'))
  targetEl('custom').addEventListener('input', () => { targetEl('add').disabled = targetBusy || !!busy || !targetEl('custom').value.trim() })
  targetEl('add').addEventListener('click', () => void loadTargets('add-program', targetEl('custom').value.trim()))
  window.aidrSystemCollection = { refresh: async () => { await refresh(); if (!targets) await loadTargets('discover') } }
  setInterval(async () => {
    if (targetBusy || busy) return
    if (await loadTargets() && targets.discovery_request !== discoveryRequest) await loadTargets('discover')
  }, 30000)
  window.addEventListener('agent-manager-client-locale-change', render)
  setInterval(() => { if (!$('state').closest('[role="tabpanel"]').hidden && document.getElementById('runtime-governance').classList.contains('active')) void refresh() }, 2000)
  render()
})()
