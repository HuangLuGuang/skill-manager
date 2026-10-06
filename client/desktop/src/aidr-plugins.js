(() => {
  const invoke = window.__TAURI__?.core?.invoke
  if (!invoke) return
  const $ = id => document.getElementById(id)
  const t = key => window.clientI18n.t(`ui.aidrDesktop.${key}`)
  let polling = false
  let statusRevision = 0, statusError = ''
  let busy = false, error = '', snapshot = {}, hosts = {}, collection = {}, collectionError = ''
  let systemPrerequisites = null, systemError = ''
  let collectionCheckedAt = 0
  let renderedSnapshot = ''
  const renderedHosts = new Map()
  const codeText = code => {
    const key = `ui.aidrDesktop.code.${code}`
    const translated = window.clientI18n.t(key)
    if (translated !== key) return translated
    const systemKey = `ui.systemCollection.code.${code}`
    const systemText = window.clientI18n.t(systemKey)
    return systemText === systemKey ? `${t('error')} (${code})` : systemText
  }
  const valueText = value => value === true ? t('yes') : value === false ? t('no') : t('unknown')
  const add = (list, label, value) => {
    const group = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd')
    dt.textContent = label; dd.textContent = value; group.append(dt, dd); list.append(group)
  }
  const render = () => {
    const channelStale = Object.fromEntries(['logs', 'hooks', 'system'].map(kind => {
      const stamp = Date.parse(collection.channels?.[kind]?.reported_at)
      return [kind, !Number.isFinite(stamp) || Date.now() - stamp > 30000 || stamp > Date.now() + 5000]
    }))
    const signature = JSON.stringify([busy, error, statusError, snapshot, hosts, collection, collectionError, channelStale, systemPrerequisites, systemError, window.clientI18n.getLocale()])
    if (renderedSnapshot === signature) return
    renderedSnapshot = signature
    const managed = snapshot.policy?.target?.access_mode === 'managed'
    const configured = !!snapshot.code && !['aidr_desktop_not_configured', 'aidr_desktop_config_unreadable'].includes(snapshot.code)
    const platformManaged = snapshot.managed_task && snapshot.managed_task !== '0'
    $('aidr-connection-needed').hidden = configured
    $('aidr-receiver-controls').hidden = !configured
    $('aidr-authorization-note').hidden = !managed
    document.querySelectorAll('[data-aidr-action="authorize"]').forEach(button => { button.hidden = !managed || !snapshot.policy?.target?.hosts?.includes(button.dataset.aidrAgent) })
    document.querySelectorAll('[data-aidr-action="remove-managed"]').forEach(button => { button.hidden = hosts[button.dataset.aidrAgent]?.managed_installed !== true })
    $('aidr-managed-note').hidden = !snapshot.managed_task || snapshot.managed_task === '0'
    const auditGap = snapshot.receiver_diagnostic?.audit_gap
    const gapError = snapshot.receiver_diagnostic?.audit_gap_code
    $('aidr-plugin-error').hidden = !error && !statusError && !auditGap && !gapError
    $('aidr-plugin-error').textContent = [
      ...[error, statusError, gapError].filter(Boolean).map(codeText),
      ...(auditGap ? [codeText(auditGap.code), codeText(auditGap.cause), `${t('audit_gap_at')}: ${new Date(auditGap.observed_at).toLocaleString(window.clientI18n.getLocale())}`] : [])
    ].join(' · ')
    document.querySelectorAll('[data-aidr-action]').forEach(button => {
      const action = button.dataset.aidrAction
      const plugin = hosts[button.dataset.aidrAgent]?.plugin
      if (action === 'retry') button.title = t('retry_scope')
      if (action === 'upgrade') button.hidden = plugin?.installed !== true
      if (action === 'enable') button.hidden = snapshot.enabled === true
      if (action === 'disable') button.hidden = snapshot.enabled !== true
      button.disabled = busy || !configured || (action === 'retry-logs' && (collectionError !== '' || collection.channels?.logs?.state !== 'failed')) || (platformManaged && ['connect','upgrade','enable','disable'].includes(action)) || (['connect','upgrade'].includes(action) && plugin?.version_status !== 'adapter_target')
      if (['connect', 'upgrade'].includes(action)) button.title = !configured ? codeText('aidr_desktop_not_configured') : platformManaged ? t('managed_note') : plugin?.version_status !== 'adapter_target' ? t(plugin?.version_status ? 'unsupported' : 'unchecked') : ''
    })
    const channelList = $('aidr-collection-channels'); channelList.replaceChildren()
    for (const kind of ['logs', 'hooks', 'system']) {
      const card = document.createElement('section'), title = document.createElement('h3'), fields = document.createElement('dl')
      card.className = 'governance-host'; fields.className = 'detail-list'; title.textContent = t(`channel_${kind}`)
      const report = collectionError ? null : collection.channels?.[kind]
      const policy = collection.runtime_policy
      const target = policy?.target
      const desired = target ? !!target.enabled && (target.channels ? !!target.channels[kind] : kind === 'hooks') : null
      add(fields, t('channel_target'), desired == null ? t('channel_unconfigured') : valueText(desired))
      add(fields, t('policy_received'), policy?.version || t('unknown'))
      const stamp = report?.reported_at ? Date.parse(report.reported_at) : NaN
      const stale = channelStale[kind]
      let health = desired == null ? 'policy_unknown' : desired === false ? 'not_requested' : !report ? 'unreported' : report.policy_version !== policy.version ? 'awaiting_application' : stale ? 'stale' : report.enabled !== true ? 'awaiting_application' : report.state
      if (desired === false && report && !stale && (report.enabled === true || ['running', 'starting', 'waiting_authorization'].includes(report.state))) {
        health = report.policy_version === policy.version ? 'disable_not_applied' : 'awaiting_stop'
      }
      add(fields, t('channel_actual'), collectionError ? t('unknown') : kind === 'logs' ? codeText(`aidr_channel_${health}`) : !report ? t('unknown') : stale ? t('channel_historical') : t(`channel_state_${report.state}`))
      if (kind === 'logs') {
        add(fields, t('channel_reported_state'), !report || stale ? t('channel_historical') : t(`channel_state_${report.state}`))
        add(fields, t('channel_policy_health_note'), t('channel_policy_health_help'))
      }
      add(fields, t('last_report'), Number.isFinite(stamp) ? new Date(stamp).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
      if (report) {
        add(fields, t('policy_applied_version'), report.policy_version || t('unknown'))
        add(fields, t('channel_reason'), codeText(report.code))
        add(fields, t('transport'), report.transport_code ? codeText(report.transport_code) : t('unknown'))
        add(fields, t('queued'), report.queued_records == null ? t('unknown') : String(report.queued_records))
        add(fields, t('latest_ack'), report.last_ack_at ? new Date(report.last_ack_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
      } else add(fields, t('channel_reason'), collectionError ? codeText(collectionError) : t('channel_unreported'))
      card.append(title, fields); channelList.append(card)
    }
    const prerequisiteList = $('aidr-system-prerequisites'); prerequisiteList.replaceChildren()
    $('aidr-system-check-error').hidden = !systemError
    $('aidr-system-check-error').textContent = systemError ? codeText(systemError) : ''
    if (systemPrerequisites) {
      add(prerequisiteList, t('channel_reason'), codeText(systemPrerequisites.code))
      add(prerequisiteList, t('system_checked_at'), new Date(systemPrerequisites.checked_at).toLocaleString(window.clientI18n.getLocale()))
      add(prerequisiteList, t('system_es_authorization'), t('unknown'))
      add(prerequisiteList, t('system_es_subscription'), t('unknown'))
      for (const component of systemPrerequisites.components || []) {
        add(prerequisiteList, t('system_component'), component.path || t('unknown'))
        add(prerequisiteList, t('channel_reason'), codeText(component.code))
        add(prerequisiteList, t('system_exists'), valueText(component.exists))
        add(prerequisiteList, t('system_path_trust'), valueText(component.trusted_path))
        add(prerequisiteList, t('system_signature'), valueText(component.valid_product_signature))
        if (component.es_entitlement != null) add(prerequisiteList, t('system_entitlement'), valueText(component.es_entitlement))
        if (component.supports_collection_only != null) add(prerequisiteList, t('system_collection_support'), valueText(component.supports_collection_only))
      }
    } else add(prerequisiteList, t('channel_reason'), t('system_not_checked'))
    const diagnostic = snapshot.receiver_diagnostic
    const telemetry = snapshot.telemetry || {}
    const summary = $('aidr-runtime-summary'); summary.replaceChildren()
    add(summary, t('receiver'), statusError ? t('unknown') : codeText(snapshot.code || 'aidr_desktop_not_configured'))
    add(summary, t('transport'), statusError ? t('unknown') : telemetry.runtime_code ? codeText(telemetry.runtime_code) : t('unknown'))
    add(summary, t('queued'), statusError || !telemetry.state ? t('unknown') : String(telemetry.state.queued_records))
    add(summary, t('latest_ack'), telemetry.state?.last_event_ack_at ? new Date(telemetry.state.last_event_ack_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
    const state = $('aidr-receiver-state'); state.replaceChildren()
    add(state, t('receiver'), codeText(snapshot.code || 'aidr_desktop_not_configured'))
    if (diagnostic) {
      add(state, t('ownership'), t(`ownership_${diagnostic.ownership || 'unavailable'}`))
      add(state, t('diagnostic_code'), codeText(diagnostic.code))
      add(state, t('owner_pid'), diagnostic.pid ? String(diagnostic.pid) : t('unknown'))
      if (Number.isInteger(diagnostic.pid) && diagnostic.pid > 0) add(state, t('owner_check'), `ps -p ${diagnostic.pid} -o pid=,uid=,lstart=,comm=`)
      add(state, t('owner_uid'), diagnostic.pid ? String(diagnostic.uid) : t('unknown'))
      add(state, t('owner_started'), diagnostic.process_started_at || t('unknown'))
      add(state, t('owner_executable'), diagnostic.executable || t('unknown'))
      add(state, t('socket_path'), diagnostic.socket || t('unknown'))
      add(state, t('expected_queue'), diagnostic.queue || t('unknown'))
      add(state, t('queue_path'), diagnostic.receiver?.queue || t('unknown'))
      add(state, t('expected_destination'), diagnostic.expected_server || t('unknown'))
      add(state, t('actual_destination'), diagnostic.receiver?.server || t('unknown'))
      add(state, t('owner_queued'), diagnostic.state?.queued_records == null ? t('unknown') : String(diagnostic.state.queued_records))
      add(state, t('owner_ack'), diagnostic.state?.last_event_ack_at || t('unknown'))
      add(state, t('recovery'), t(diagnostic.ownership === 'owned' ? 'recovery_owned' : diagnostic.ownership === 'external_verified' ? 'recovery_external' : 'recovery_unverified'))
    }
    add(state, t('automatic'), valueText(snapshot.enabled))
    add(state, t('managed_task'), snapshot.managed_task && snapshot.managed_task !== '0' ? snapshot.managed_task : t('unknown'))
    add(state, t('attempts'), String(snapshot.attempts || 0))
    add(state, t('retry_count'), String(snapshot.retry_count || 0))
    add(state, t('retry_mode'), t(`retry_mode_${snapshot.retry_mode || 'fixed'}`))
    add(state, t('retry_suspended'), valueText(snapshot.retry_suspended))
    add(state, t('next_retry'), snapshot.next_retry_seconds == null ? t('unknown') : String(snapshot.next_retry_seconds))
    add(state, t('last_failure'), snapshot.last_failure ? codeText(snapshot.last_failure) : t('unknown'))
    add(state, t('last_failure_at'), snapshot.last_failure_at_ms == null ? t('unknown') : new Date(snapshot.last_failure_at_ms).toLocaleString(window.clientI18n.getLocale()))
    if (snapshot.policy) {
      add(state, t('policy_received'), `${snapshot.policy.version} · ${snapshot.policy.received_at ? new Date(snapshot.policy.received_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown')}`)
      add(state, t('policy_applied'), snapshot.policy.applied_at ? new Date(snapshot.policy.applied_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
      add(state, t('policy_code'), codeText(snapshot.policy.code))
    }
    add(state, t('transport'), telemetry.runtime_code ? codeText(telemetry.runtime_code) : t('unknown'))
    add(state, t('upload'), telemetry.upload_code ? codeText(telemetry.upload_code) : telemetry.state ? t('no_upload_error') : t('unknown'))
    add(state, t('queued'), telemetry.state ? String(telemetry.state.queued_records) : t('unknown'))
    add(state, t('last_report'), telemetry.last_report ? new Date(telemetry.last_report).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
    add(state, t('last_event_ack'), telemetry.state?.last_event_ack_at ? new Date(telemetry.state.last_event_ack_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
    add(state, t('hook_sequence'), telemetry.state?.last_sequence ?? t('unknown'))
    add(state, t('control'), telemetry.state?.control_mode ? t(`mode.${telemetry.state.control_mode}`) : t('unknown'))
    add(state, t('audit_policy'), telemetry.state?.policy?.version || t('unknown'))
    add(state, t('audit_enabled'), valueText(telemetry.state?.policy?.enabled))
    const scope = telemetry.state?.policy?.capture
    add(state, t('content_scope'), scope ? ['prompt', 'model_response', 'tool_output', 'file_body', 'command_body'].filter(kind => scope[kind]).map(kind => t(`content_${kind}`)).join(' · ') || t('content_none') : t('content_unsupported'))
    const lifecycle = telemetry.state?.policy?.lifecycle
    add(state, t('collection'), lifecycle ? t(lifecycle.enabled ? 'collection_enabled' : 'collection_disabled') : t('collection_unsupported'))
    add(state, t('retention'), lifecycle ? String(lifecycle.retention_days) : t('unknown'))
    if (lifecycle) add(state, t('suppressed'), telemetry.state?.audit_suppressed_recent == null ? t('unknown') : String(telemetry.state.audit_suppressed_recent))
    add(state, t('control_revision'), telemetry.state?.control_revision || t('unknown'))
    for (const agent of ['claude', 'codex']) {
      const signature = JSON.stringify([hosts[agent], window.clientI18n.getLocale()])
      if (renderedHosts.get(agent) === signature) continue
      renderedHosts.set(agent, signature)
      const section = $(`aidr-host-${agent}-status`), title = document.createElement('h3'), fields = document.createElement('dl')
      section.replaceChildren()
      fields.className = 'detail-list'; title.textContent = agent === 'claude' ? 'Claude Code' : 'Codex'; section.append(title, fields)
      const data = hosts[agent]
      if (data?.error) add(fields, t('source'), codeText(data.error))
      else if (data) {
        const plugin = data.plugin || {}
        add(fields, t('version'), plugin.host_version || t('unknown'))
        add(fields, t('compatibility'), plugin.version_status === 'adapter_target' ? t('supported') : plugin.version_status === 'unverified' ? t('unsupported') : t('unknown'))
        add(fields, t('installed'), valueText(plugin.installed)); add(fields, t('enabled'), valueText(plugin.enabled))
        add(fields, t('trust'), data.hook_trust === 'managed' ? t('managed_trust') : data.hook_trust === 'trusted' ? t('trusted') : data.hook_trust === 'needs_review' ? t('needs_review') : t('trust_unknown'))
        add(fields, t('checked_at'), plugin.reported_at ? new Date(plugin.reported_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
        const details = document.createElement('details'), heading = document.createElement('summary'), evidence = document.createElement('dl')
        details.className = 'governance-host-details'; evidence.className = 'detail-list'; heading.textContent = t('host_details')
        add(evidence, t('path'), data.host?.binary || t('unknown'))
        add(evidence, t('source'), codeText(plugin.source_code || 'aidr_plugin_source_unreadable'))
        details.append(heading, evidence); section.append(details)
      } else add(fields, t('source'), t('unchecked'))
    }
  }
  const poll = async (afterAction = false) => {
    if (polling || (busy && !afterAction)) return
    polling = true
    const revision = ++statusRevision
    try {
      const nextSnapshot = await invoke('aidr_receiver_status')
      if (revision !== statusRevision) return
      snapshot = nextSnapshot
      statusError = ''
      if (Date.now() - collectionCheckedAt >= 5000) {
        collectionCheckedAt = Date.now()
        try {
          const nextCollection = await invoke('aidr_collection_status')
          if (revision !== statusRevision) return
          collection = nextCollection; collectionError = ''
        }
        catch (cause) {
          if (revision !== statusRevision) return
          collectionError = String(cause); collection = {}
        }
      }
      render()
    }
    catch { if (revision === statusRevision) { statusError = 'aidr_desktop_status_failed'; render() } }
    finally { if (revision === statusRevision) polling = false }
  }
  const act = async (action, agent = '') => {
    if (busy) return
    if (['connect', 'upgrade'].includes(action) && hosts[agent]?.plugin?.version_status !== 'adapter_target') return
    statusRevision++; polling = false
    busy = true; error = ''; if (action === 'system-check') { systemError = ''; systemPrerequisites = null }; render()
    try {
      if (action === 'inspect') {
        for (const host of ['claude', 'codex']) {
          try { hosts[host] = await invoke('aidr_plugin_action', {action, agent: host}) }
          catch (cause) { hosts[host] = {error: String(cause)} }
        }
      } else {
        const result = await invoke('aidr_plugin_action', {action, agent})
        if (action === 'system-check') {
          if (result.version !== 1 || !Array.isArray(result.components)) throw 'aidr_system_prerequisites_invalid'
          systemPrerequisites = result
        }
        else if (agent) hosts[agent] = result
      }
      collectionCheckedAt = 0
      await poll(true)
    } catch (cause) { if (action === 'system-check') systemError = String(cause); else error = String(cause) }
    finally { busy = false; render() }
  }
  document.querySelectorAll('[data-aidr-action]').forEach(button => button.addEventListener('click', () => { void act(button.dataset.aidrAction, button.dataset.aidrAgent || '') }))
  $('aidr-open-connection').addEventListener('click', () => document.querySelector('.nav-item[data-panel="connect"]')?.click())
  window.addEventListener('agent-manager-client-locale-change', render)
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void poll() })
  setInterval(() => { if (!document.hidden && $('runtime-governance')?.classList.contains('active') && !$('aidr-plugin-settings')?.hidden) void poll() }, 2000)
  window.aidrGovernance = {refresh: () => act('inspect')}
  void poll()
})()
