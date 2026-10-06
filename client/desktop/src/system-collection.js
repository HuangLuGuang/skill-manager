(() => {
  const invoke = window.__TAURI__?.core?.invoke
  if (!invoke) return
  const $ = id => document.getElementById(`system-collection-${id}`)
  const t = key => window.clientI18n.t(`ui.systemCollection.${key}`)
  let status = { state: 'stopped' }, busy = '', error = '', polling = false, renderedEvents = ''
  const codeText = code => {
    if (!code) return ''
    const key = `ui.systemCollection.code.${code}`
    const text = window.clientI18n.t(key)
    return text === key ? `${t('failure')} (${code})` : text
  }
  const date = value => value ? new Date(value).toLocaleString(window.clientI18n.getLocale()) : '—'
  const row = (list, label, value) => {
    const div = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd')
    dt.textContent = label; dd.textContent = value; div.append(dt, dd); list.append(div)
  }
  function render() {
    const active = ['collecting', 'starting', 'draining', 'degraded'].includes(status.state)
    $('state').textContent = t(`state.${busy === 'start' ? 'authorizing' : busy === 'stop' ? 'draining' : status.state}`)
    $('start').disabled = !!busy || active
    $('stop').disabled = !!busy || !active
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
    row(summary, t('upload'), status.upload_code ? codeText(status.upload_code) : date(status.uploaded_at))
    row(summary, t('pending'), status.pending_uploads == null ? t('unknown') : String(status.pending_uploads))
    row(summary, t('count'), String(status.event_count || 0))
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
      heading.textContent = `${t(`transition.${record.transition}`)} · PID ${record.process.pid}`
      detail.textContent = `${record.path || '—'} · ${date(new Date(Number(BigInt(record.time_ns) / 1000000n)).toISOString())}`
      const attribution = document.createElement('p')
      const relation = ['direct', 'inherited'].includes(record.relation) ? record.relation : 'unknown'
      attribution.textContent = `${t(`relation.${relation}`)}${record.root?.pid && record.root.pid !== '0' ? ` · ${t('rootProcess')} ${record.root.pid}` : ''}`
      const diagnostics = document.createElement('details'), title = document.createElement('summary'), fields = document.createElement('dl')
      diagnostics.dataset.event = `${record.monitor_id}:${record.sequence}`
      diagnostics.open = expanded.has(diagnostics.dataset.event)
      title.textContent = t('eventDiagnostics')
      row(fields, t('processIdentity'), `${record.process.pid} / ${record.process.pidversion} / ${record.process.start_us}`)
      row(fields, t('monitor'), record.monitor_id)
      row(fields, t('sequence'), record.sequence)
      const raw = document.createElement('pre'); raw.textContent = JSON.stringify(record, null, 2)
      diagnostics.append(title, fields, raw)
      item.append(heading, detail, attribution, diagnostics); events.append(item)
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
  for (const name of ['start', 'stop', 'settings', 'reveal']) $(name).addEventListener('click', () => void action(name))
  window.aidrSystemCollection = { refresh }
  window.addEventListener('agent-manager-client-locale-change', render)
  setInterval(() => { if (!$('state').closest('[role="tabpanel"]').hidden && document.getElementById('runtime-governance').classList.contains('active')) void refresh() }, 2000)
  render()
})()
