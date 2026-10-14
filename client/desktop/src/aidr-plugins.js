(() => {
  const invoke = window.__TAURI__?.core?.invoke
  if (!invoke) return
  const $ = id => document.getElementById(id)
  const t = key => window.clientI18n.t(`ui.aidrDesktop.${key}`)
  const products = window.aidrProducts || []
  const hookProducts = products.filter(product => product.hooks)
  const qoderEntries = new Set(['qoder-cli', 'qoder-hooks', 'qoder-ide', 'qoder-work'])
  let qoderCard = null
  for (const product of hookProducts.filter(product => !product.managed)) {
    const card = document.createElement('section'), status = document.createElement('div'), actions = document.createElement('div')
    card.className = 'governance-host'; status.id = `aidr-host-${product.id}-status`; actions.className = 'governance-host-actions'
    for (const action of ['connect', 'disconnect']) {
      const button = document.createElement('button'); button.type = 'button'; button.className = action === 'connect' ? 'primary' : ''; button.dataset.aidrAction = action; button.dataset.aidrAgent = product.id; button.dataset.productAction = action; actions.append(button)
    }
    card.append(status, actions)
    if (qoderEntries.has(product.id)) {
      if (!qoderCard) {
        qoderCard = document.createElement('section'); qoderCard.className = 'governance-host'
        const title = document.createElement('strong'); title.textContent = 'Qoder'; qoderCard.append(title)
        $('aidr-host-status').append(qoderCard)
      }
      card.className = 'governance-product-entry'; qoderCard.append(card)
    } else $('aidr-host-status').append(card)
  }
  const catalogView = document.createElement('details'), catalogTitle = document.createElement('summary'), catalogNote = document.createElement('p'), catalogRows = document.createElement('div')
  catalogView.className = 'governance-product-catalog'
  catalogView.append(catalogTitle, catalogNote, catalogRows); $('aidr-host-status').after(catalogView)
  window.aidrWorkbench.init()
  let catalogLocale = ''
  const renderCatalog = () => {
    if (catalogLocale === window.clientI18n.getLocale()) return
    catalogLocale = window.clientI18n.getLocale()
    catalogTitle.textContent = t('catalog_title'); catalogNote.textContent = t('catalog_note'); catalogRows.replaceChildren()
    let qoderCatalog = null
    for (const product of products.filter(item => item.collection_visible !== false)) {
      const row = document.createElement('section'), title = document.createElement('strong'), info = document.createElement('p'), source = document.createElement('p')
      const entryLabel = t(`entry_${product.entry.replaceAll('-', '_')}`)
      title.textContent = qoderEntries.has(product.id) ? entryLabel : `${product.name} · ${entryLabel}`
      info.textContent = `${product.os.join(' / ') || t('unknown')} · ${t('catalog_samples')}: ${product.sample_versions.join(' / ') || t('unknown')} · ${product.logs || product.hooks ? t('adapter_implemented') : t('catalog_unavailable')}`
      source.textContent = `${t('channel_logs')}: ${product.logs || t('catalog_unavailable')} ${product.log_os.join('/')} ${product.roots.map(root => `~/${root}`).join(' / ')} · Hook: ${product.hooks || t('catalog_unavailable')} ${product.hook_os.join('/')}`
      row.append(title, info, source)
      if (qoderEntries.has(product.id)) {
        if (!qoderCatalog) {
          qoderCatalog = document.createElement('section')
          const title = document.createElement('h3'); title.textContent = 'Qoder'; qoderCatalog.append(title)
          catalogRows.append(qoderCatalog)
        }
        qoderCatalog.append(row)
      } else catalogRows.append(row)
    }
  }
  let polling = false
  let statusRevision = 0, statusError = ''
  let busy = false, error = '', snapshot = {}, hosts = {}, collection = {}, collectionError = ''
  let pendingAction = '', pendingAgent = ''
  let systemPrerequisites = null, systemError = ''
  let collectionCheckedAt = 0
  const bridgeRechecks = new Map()
  let renderedSnapshot = ''
  const renderedHosts = new Map()
  const enrollmentActionState = agent => {
    const state = window.aidrWorkbench.productState(agent, { snapshot, hosts, collection, collectionError })
    const product = products.find(item => item.id === agent)
    if (!state.current || state.installed !== true || (product?.hook_setup?.host_enablement !== false && state.plugin?.enabled === false)) return ''
    if (state.enabled) return 'enabled'
    const target = snapshot.policy?.target
    if (!collectionError && target?.enabled && target.channels?.hooks !== false && target.access_mode === 'ordinary' && target.allow_user_enrollment === true && collection.user_hook_hosts?.includes(agent)) return 'pending'
    return ''
  }
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
    renderCatalog()
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
    const target = snapshot.policy?.target
    const selfEnrollment = target?.allow_user_enrollment === true && target?.access_mode === 'ordinary'
    const localInstallation = (target?.installation === 'manual' || selfEnrollment) && target?.access_mode === 'ordinary'
    $('aidr-connection-needed').hidden = configured
    $('aidr-receiver-controls').hidden = !configured
    $('aidr-authorization-note').hidden = !managed
    document.querySelectorAll('[data-aidr-action="authorize"]').forEach(button => { button.hidden = !managed || !snapshot.policy?.target?.hosts?.includes(button.dataset.aidrAgent) })
    document.querySelectorAll('[data-aidr-action="remove-managed"]').forEach(button => { button.hidden = hosts[button.dataset.aidrAgent]?.managed_installed !== true })
    $('aidr-managed-note').hidden = !snapshot.managed_task || snapshot.managed_task === '0'
    $('aidr-managed-note').textContent = t(selfEnrollment ? 'self_enrollment_note' : localInstallation ? 'manual_installation_note' : 'managed_note')
    const auditGap = snapshot.receiver_diagnostic?.audit_gap
    const gapError = snapshot.receiver_diagnostic?.audit_gap_code
    $('aidr-plugin-error').hidden = !error && !statusError && !gapError
    $('aidr-plugin-error').textContent = [error, statusError, gapError].filter(Boolean).map(codeText).join(' · ')
    $('aidr-audit-history').hidden = !auditGap
    if (auditGap) {
      const product = products.find(item => item.id === auditGap.agent)
      const name = product?.name || t('unknown')
      const at = new Date(auditGap.observed_at).toLocaleString(window.clientI18n.getLocale())
      $('aidr-audit-history-summary').textContent = `${t('audit_history_title')} · ${name} · ${at}`
      $('aidr-audit-history-explanation').textContent = t('audit_history_explanation')
      const fields = $('aidr-audit-history-fields'); fields.replaceChildren()
      add(fields, t('audit_history_product'), name)
      add(fields, t('audit_gap_at'), at)
      const causeKey = `ui.aidrDesktop.code.${auditGap.cause}`
      const causeText = window.clientI18n.t(causeKey)
      add(fields, t('audit_history_reason'), causeText === causeKey ? t('audit_history_reason_unknown') : causeText)
      add(fields, t('audit_history_impact'), t('audit_history_impact_note'))
      add(fields, t('audit_history_technical'), `${auditGap.hook} · ${auditGap.cause}`)
    }
    document.querySelectorAll('[data-aidr-action]').forEach(button => {
      const action = button.dataset.aidrAction
      const enrollment = action === 'connect' ? enrollmentActionState(button.dataset.aidrAgent) : ''
      button.setAttribute('aria-busy', String(busy && action === pendingAction && (button.dataset.aidrAgent || '') === pendingAgent))
      if (button.dataset.productAction) button.textContent = t(`product_${action}`)
      const product = products.find(item => item.id === button.dataset.aidrAgent)
      const paired = !!product?.enrollment_log_source
      if (action === 'connect') button.textContent = t(enrollment === 'enabled' ? paired ? 'paired_connected' : 'product_connected' : enrollment === 'pending' ? 'product_pending' : paired ? 'paired_connect' : 'product_connect')
      if (action === 'disconnect' && paired) button.textContent = t('paired_disconnect')
      if (action === 'disconnect') button.hidden = hosts[button.dataset.aidrAgent]?.plugin?.installed !== true || managed
      const plugin = hosts[button.dataset.aidrAgent]?.plugin
      if (action === 'retry') { button.title = t('retry_scope'); button.hidden = !snapshot.retry_suspended }
      if (action === 'upgrade') button.hidden = plugin?.installed !== true
      if (action === 'enable') button.hidden = snapshot.enabled === true
      if (action === 'disable') button.hidden = snapshot.enabled !== true
      const enrollmentBlocked = action === 'connect' && (!target || target.allow_user_enrollment == null || !target.enabled || target.channels?.hooks === false || (!selfEnrollment && !target.hosts?.includes(button.dataset.aidrAgent)))
      const logsBlocked = action === 'connect' && paired && (target?.channels?.logs !== true || (!selfEnrollment && !target?.log_sources?.includes(product.enrollment_log_source)))
      const policyBlocked = logsBlocked || enrollmentBlocked || platformManaged && (['enable', 'disable'].includes(action) || (!localInstallation && ['connect', 'upgrade', 'disconnect'].includes(action)))
      button.disabled = busy || !!enrollment || !configured || (action === 'retry-logs' && (collectionError !== '' || collection.channels?.logs?.state !== 'failed')) || policyBlocked || (['connect','upgrade'].includes(action) && !['interface_compatible', 'adapter_available'].includes(plugin?.version_status))
      if (['connect', 'upgrade', 'disconnect'].includes(action)) button.title = !configured ? codeText('aidr_desktop_not_configured') : logsBlocked ? codeText('aidr_enrollment_logs_blocked') : policyBlocked ? t('managed_note') : action === 'disconnect' ? t(paired ? 'paired_remove_scope' : 'remove_scope') : !['interface_compatible', 'adapter_available'].includes(plugin?.version_status) ? t(plugin?.version_status ? 'unsupported' : 'unchecked') : ''
      if (enrollment && !policyBlocked) button.title = t(enrollment === 'enabled' ? paired ? 'paired_waiting_event' : 'enrollment_waiting_event' : 'enrollment_pending')
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
    const retryPolicy = snapshot.policy?.target?.retry
    const exhausted = snapshot.retry_suspended && snapshot.retry_mode === 'fixed' && Number.isInteger(retryPolicy?.retries) && snapshot.attempts > retryPolicy.retries
    const receiverText = snapshot.retry_suspended
      ? `${exhausted ? t('retry_exhausted').replace('{count}', String(retryPolicy.retries)) : t('retry_required')} · ${codeText(snapshot.code || 'aidr_desktop_not_configured')}`
      : codeText(snapshot.code || 'aidr_desktop_not_configured')
    const summary = $('aidr-runtime-summary'); summary.replaceChildren()
    summary.parentElement.dataset.health = statusError || snapshot.retry_suspended ? 'attention' : ['aidr_desktop_running', 'aidr_desktop_shared_receiver'].includes(snapshot.code) ? 'running' : 'unknown'
    add(summary, t('receiver'), statusError ? t('unknown') : receiverText)
    add(summary, t('transport'), statusError ? t('unknown') : telemetry.runtime_code ? codeText(telemetry.runtime_code) : t('unknown'))
    add(summary, t('queued'), statusError || !telemetry.state ? t('unknown') : String(telemetry.state.queued_records))
    add(summary, t('latest_ack'), telemetry.state?.last_event_ack_at ? new Date(telemetry.state.last_event_ack_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
    const state = $('aidr-receiver-state'); state.replaceChildren()
    add(state, t('receiver'), receiverText)
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
    add(state, t('upload'), telemetry.upload_code ? codeText(telemetry.upload_code) : telemetry.state && !telemetry.shared_observation ? t('no_upload_error') : t('unknown'))
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
    for (const agent of hookProducts.map(product => product.id)) {
      const signature = JSON.stringify([hosts[agent], snapshot.policy, snapshot.enabled, collection.user_hook_hosts, window.clientI18n.getLocale()])
      if (renderedHosts.get(agent) === signature) continue
      renderedHosts.set(agent, signature)
      const section = $(`aidr-host-${agent}-status`), title = document.createElement('h3'), fields = document.createElement('dl')
      section.replaceChildren()
      const product = products.find(product => product.id === agent)
      fields.className = 'detail-list'; title.textContent = qoderEntries.has(agent) ? t(`entry_${product.entry.replaceAll('-', '_')}`) : product?.name || agent; section.append(title, fields)
      const data = hosts[agent]
      if (data?.error) add(fields, t('source'), codeText(data.error))
      else if (data) {
        const plugin = data.plugin || {}
        add(fields, t('version'), plugin.host_version || t('unknown'))
        add(fields, t('compatibility'), plugin.version_status === 'interface_compatible' ? t('interface_compatible') : plugin.version_status === 'adapter_available' ? t('adapter_implemented') : plugin.version_status === 'unverified' ? t('unsupported') : t('unknown'))
        const requested = collection.user_hook_hosts?.includes(agent)
        const selected = target?.hosts?.includes(agent)
        const enrollmentState = !target?.enabled || target?.channels?.hooks === false || (requested && !selfEnrollment && !selected) ? 'enrollment_blocked' : requested && !selected ? 'enrollment_pending' : selected && snapshot.enabled ? 'enrollment_waiting_event' : 'enrollment_not_enabled'
        add(fields, t('enrollment_status'), t(enrollmentState))
        add(fields, t('installed'), valueText(plugin.installed))
        if (product.hook_setup?.host_enablement !== false) add(fields, t('enabled'), valueText(plugin.enabled))
        if (product.hook_setup?.host_authorization !== false) add(fields, t('trust'), data.hook_trust === 'managed' ? t('managed_trust') : data.hook_trust === 'trusted' ? t('trusted') : data.hook_trust === 'needs_review' ? t('needs_review') : t('trust_unknown'))
        add(fields, t('checked_at'), plugin.reported_at ? new Date(plugin.reported_at).toLocaleString(window.clientI18n.getLocale()) : t('unknown'))
        const details = document.createElement('details'), heading = document.createElement('summary'), evidence = document.createElement('dl')
        details.className = 'governance-host-details'; evidence.className = 'detail-list'; heading.textContent = t('host_details')
        add(evidence, t('path'), data.host?.binary || t('unknown'))
        add(evidence, t('source'), codeText(plugin.source_code || 'aidr_plugin_source_unreadable'))
        details.append(heading, evidence); section.append(details)
      } else add(fields, t('source'), t('unchecked'))
    }
    window.aidrWorkbench.render({ snapshot, hosts, collection, collectionError })
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
      const enrollmentPending = hookProducts.some(product => enrollmentActionState(product.id) === 'pending')
      if (Date.now() - collectionCheckedAt >= (enrollmentPending ? 1000 : 5000)) {
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
      for (const [agent, deadline] of bridgeRechecks) {
        if (Date.now() > deadline || hosts[agent]?.plugin?.receiver_code !== 'aidr_teleagent_bridge_unavailable') { bridgeRechecks.delete(agent); continue }
        try {
          const host = await invoke('aidr_plugin_action', { action: 'inspect', agent })
          if (revision !== statusRevision) return
          hosts[agent] = { ...host, enrollment_sync_code: hosts[agent]?.enrollment_sync_code }
        } catch { /* Keep the last observed state until the next startup check. */ }
      }
      render()
    }
    catch { if (revision === statusRevision) { statusError = 'aidr_desktop_status_failed'; render() } }
    finally { if (revision === statusRevision) polling = false }
  }
  const act = async (action, agent = '') => {
    if (busy) return
    if (action === 'connect' && enrollmentActionState(agent)) return
    if (['connect', 'upgrade'].includes(action) && !['interface_compatible', 'adapter_available'].includes(hosts[agent]?.plugin?.version_status)) return
    statusRevision++; polling = false
    busy = true; pendingAction = action; pendingAgent = agent; error = ''; if (action === 'system-check') { systemError = ''; systemPrerequisites = null }; render()
    try {
      if (action === 'inspect') {
        for (const host of hookProducts.map(product => product.id)) {
          try { hosts[host] = await invoke('aidr_plugin_action', {action, agent: host}) }
          catch (cause) { hosts[host] = {error: String(cause)} }
        }
      } else {
        const result = await invoke('aidr_plugin_action', {action: action === 'connect' ? 'enroll' : action, agent})
        if (action === 'system-check') {
          if (result.version !== 1 || !Array.isArray(result.components)) throw 'aidr_system_prerequisites_invalid'
          systemPrerequisites = result
        }
        else if (agent) {
          hosts[agent] = result
          bridgeRechecks.delete(agent)
          if (action === 'connect' && result.plugin?.receiver_code === 'aidr_teleagent_bridge_unavailable') bridgeRechecks.set(agent, Date.now() + 30000)
        }
      }
      collectionCheckedAt = 0
      await poll(true)
    } catch (cause) { if (action === 'system-check') systemError = String(cause); else error = String(cause) }
    finally { busy = false; pendingAction = ''; pendingAgent = ''; render() }
  }
  document.querySelectorAll('[data-aidr-action]').forEach(button => button.addEventListener('click', () => { void act(button.dataset.aidrAction, button.dataset.aidrAgent || '') }))
  $('aidr-open-connection').addEventListener('click', () => document.querySelector('.nav-item[data-panel="connect"]')?.click())
  window.addEventListener('agent-manager-client-locale-change', render)
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void poll() })
  setInterval(() => { if (!document.hidden && $('runtime-governance')?.classList.contains('active') && !$('aidr-plugin-settings')?.hidden) void poll() }, 2000)
  window.aidrGovernance = {refresh: () => act('inspect')}
  void poll()
})()
