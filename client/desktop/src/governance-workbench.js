(() => {
  const $ = id => document.getElementById(id)
  const t = key => window.clientI18n.t(`ui.governanceDesign.${key}`)
  const hostText = key => window.clientI18n.t(`ui.aidrDesktop.${key}`)
  const node = (tag, className = '', text = '') => {
    const element = document.createElement(tag)
    element.className = className; element.textContent = text
    return element
  }
  const icons = { claude: 'claude-color.svg', codex: 'codex.png', workbuddy: 'workbuddy.png', codebuddy: 'codebuddy-color.svg', teleagent: 'teleagent.png', doubaowork: 'doubaowork.png', qwenwork: 'qwenwork.png', zcode: 'zcode.png', qoder: 'qoder.png', cursor: 'cursor.svg', opencode: 'opencode.svg', openclaw: 'openclaw-color.svg', trae: 'trae.svg', 'trae-cn': 'trae.svg', traework: 'trae.svg' }
  const groupId = id => id.startsWith('qoder-') ? 'qoder' : id
  const logo = id => {
    const img = node('img', 'governance-product-logo')
    img.src = `./assets/icons/${icons[groupId(id)] || 'bot.svg'}`; img.alt = ''
    return img
  }
  const groups = []
  const products = window.aidrProducts || []
  const linkedLogEntries = new Set(products.map(product => product.log_entry).filter(Boolean))
  for (const product of products) {
    if (product.collection_visible === false || (!product.logs && !product.hooks) || linkedLogEntries.has(product.id)) continue
    const id = groupId(product.id)
    let group = groups.find(item => item.id === id)
    if (!group) { group = { id, name: id === 'qoder' ? 'Qoder' : product.name, entries: [] }; groups.push(group) }
    group.entries.push(product)
  }
  let selected = groups[0]?.entries[0]?.id, latest = {}, selectedSignature = ''
  let showAll = false
  const buttons = new Map(), actionGroups = new Map(), hostCards = new Map()
  function init() {
    $('aidr-runtime-summary').parentElement.append(document.querySelector('[data-aidr-action="retry"]'))
    const diagnostics = node('details', 'governance-diagnostics'), diagnosticsTitle = node('summary', '', t('compactDiagnostics'))
    diagnostics.id = 'aidr-compact-diagnostics'; diagnosticsTitle.dataset.i18n = 'ui.governanceDesign.compactDiagnostics'
    diagnostics.append(diagnosticsTitle)
    $('aidr-product-inspector').append(diagnostics)
    for (const item of [...$('aidr-product-inspector').children]) {
      if (item.matches('details, #aidr-managed-note') && item !== diagnostics) diagnostics.append(item)
    }
    $('aidr-product-inspector').append($('aidr-audit-history'))
    const catalogToggle = node('button', 'governance-catalog-toggle', t('showProducts'))
    catalogToggle.type = 'button'; catalogToggle.id = 'aidr-product-toggle'
    catalogToggle.addEventListener('click', () => { showAll = !showAll; render(latest) })
    $('aidr-product-navigation').after(catalogToggle)
    const empty = node('p', 'governance-empty', t('noLocalProducts'))
    empty.id = 'aidr-product-empty'; empty.dataset.i18n = 'ui.governanceDesign.noLocalProducts'
    $('aidr-product-navigation').after(empty)
    for (const group of groups) {
      const button = node('button', 'governance-product-option'), text = node('span'), name = node('strong', '', group.name), state = node('small')
      button.type = 'button'; button.append(logo(group.id), text); text.append(name, state)
      button.addEventListener('click', () => select(group.entries[0].id))
      buttons.set(group.id, { button, state }); $('aidr-product-navigation').append(button)
    }
    const hostDetails = node('details', 'governance-diagnostics'), summary = node('summary')
    summary.dataset.i18n = 'ui.governanceDesign.versions'
    summary.textContent = t('versions'); hostDetails.append(summary)
    diagnostics.prepend(hostDetails); hostDetails.append($('aidr-host-status'))
    for (const product of (window.aidrProducts || []).filter(item => item.hooks)) {
      const section = $(`aidr-host-${product.id}-status`), card = section.parentElement
      const actions = card.querySelector('.governance-host-actions')
      const more = node('details', 'governance-more-actions'), label = node('summary', '', t('moreActions'))
      label.dataset.i18n = 'ui.governanceDesign.moreActions'; more.append(label)
      for (const button of actions.querySelectorAll('[data-aidr-action="disconnect"], [data-aidr-action="remove-managed"]')) more.append(button)
      actions.append(more)
      hostCards.set(product.id, card); actionGroups.set(product.id, actions)
    }
    $('aidr-product-navigation').setAttribute('aria-label', t('products'))
  }
  function select(id) {
    selected = id; selectedSignature = ''; render(latest)
    $('aidr-product-inspector').scrollTop = 0
  }
  function states(product, data) {
    const logProduct = products.find(entry => entry.id === product.log_entry) || product
    const target = data.snapshot?.policy?.target, host = data.hosts?.[product.id], plugin = host?.plugin
    const policy = data.collection?.runtime_policy
    const logTarget = policy?.target
    const logSources = logTarget?.log_sources ?? ['claude', 'codex']
    const logs = !logProduct.logs ? 'unsupported' : !logTarget || data.collectionError ? 'unknown'
      : logTarget.enabled && logTarget.channels?.logs && logSources.includes(logProduct.id) ? 'inPolicy' : 'notEnabled'
    const stamp = Date.parse(plugin?.reported_at)
    const current = Number.isFinite(stamp) && Date.now() - stamp < 480000 && stamp <= Date.now() + 5000
    const installed = current ? plugin?.installed : null
    const trusted = current && ['managed', 'trusted'].includes(host?.hook_trust)
    const enabled = target?.enabled && target.channels?.hooks !== false && target.hosts?.includes(product.id) && data.snapshot?.enabled
    const requested = data.collection?.user_hook_hosts?.includes(product.id)
    const hooks = !product.hooks ? 'unsupported' : !host ? 'unchecked' : host.error || !current ? 'unknown'
      : plugin?.source_code === 'aidr_teleagent_configuration_changed' ? 'configurationChanged' : installed == null ? 'unknown' : !installed ? 'notInstalled' : product.hook_setup?.host_authorization !== false && host.hook_trust === 'needs_review' ? 'needsAuth'
      : plugin.receiver_code === 'aidr_teleagent_bridge_unavailable' ? 'bridgeUnavailable' : !enabled ? requested ? 'pendingPolicy' : 'notEnabled' : product.hook_setup?.host_enablement !== false && plugin.enabled === false ? 'hostDisabled' : 'configured'
    return { logs, hooks, installed, trusted, enabled, current, host, plugin, logProduct }
  }
  function render(data) {
    latest = data
    $('aidr-product-navigation').setAttribute('aria-label', t('products'))
    $('aidr-host-status').parentElement.querySelector('summary').textContent = t('versions')
    const target = data.snapshot?.policy?.target
    const visibleGroups = groups.filter(group => showAll || group.entries.some(entry => {
      const host = data.hosts?.[entry.id]
      return target?.hosts?.includes(entry.id)
        || data.collection?.runtime_policy?.target?.log_sources?.includes(entry.log_entry || entry.id)
        || (host?.plugin && host.plugin.source_code !== 'aidr_desktop_host_missing')
    }))
    $('aidr-product-toggle').textContent = t(showAll ? 'localProducts' : 'showProducts')
    $('aidr-product-toggle').setAttribute('aria-expanded', String(showAll))
    $('aidr-product-empty').hidden = visibleGroups.length > 0
    for (const group of groups) buttons.get(group.id).button.hidden = !visibleGroups.includes(group)
    if (!visibleGroups.some(group => group.entries.some(entry => entry.id === selected))) selected = visibleGroups[0]?.entries[0]?.id
    $('aidr-product-heading').hidden = !selected; $('aidr-product-channels').hidden = !selected
    const product = products.find(item => item.id === selected)
    if (!product) {
      selectedSignature = ''
      $('aidr-host-status').parentElement.hidden = true
      for (const card of hostCards.values()) card.hidden = true
      for (const actions of actionGroups.values()) actions.hidden = true
      return
    }
    const group = groups.find(item => item.id === groupId(selected))
    for (const item of groups) {
      const entry = item.id === group.id ? product : item.entries[0]
      const state = states(entry, data), ui = buttons.get(item.id)
      ui.button.setAttribute('aria-pressed', String(item.id === group.id))
      ui.state.textContent = item.entries.length > 1 ? t('multipleEntries') : t(entry.hooks ? state.hooks : state.logs)
    }
    for (const [id, card] of hostCards) {
      card.hidden = id !== selected
      if (groupId(id) === 'qoder') card.parentElement.hidden = group.id !== 'qoder'
    }
    for (const [id, actions] of actionGroups) actions.hidden = id !== selected
    const state = states(product, data)
    const report = data.collection?.channels?.logs
    const stamp = Date.parse(report?.reported_at)
    const fresh = !data.collectionError && Number.isFinite(stamp) && Date.now() - stamp < 30000 && stamp <= Date.now() + 5000
    const automatic = target?.enabled && target?.installation === 'automatic' && target.hosts?.includes(product.id)
    const managed = target?.access_mode === 'managed'
    const signature = JSON.stringify([selected, state, automatic, managed, target, report?.state, fresh, data.collectionError, window.clientI18n.getLocale()])
    if (signature === selectedSignature) return
    selectedSignature = signature
    const heading = $('aidr-product-heading'); heading.replaceChildren()
    const titles = node('div'), name = node('h2', '', group.name), entry = node('p', '', hostText(`entry_${product.entry.replaceAll('-', '_')}`))
    titles.append(name, entry); heading.append(logo(group.id), titles)
    heading.append(node('span', 'governance-management-badge', t(!target ? 'managementUnknown' : !target.enabled ? 'platformControlled' : managed ? 'managedAccess' : automatic ? 'platformAutomatic' : target.allow_user_enrollment || target.installation === 'manual' ? 'localAccess' : 'platformControlled')))
    if (group.entries.length > 1) {
      const selectEntry = node('select'); selectEntry.setAttribute('aria-label', t('entry'))
      for (const item of group.entries) {
        const option = node('option', '', hostText(`entry_${item.entry.replaceAll('-', '_')}`))
        option.value = item.id; option.selected = item.id === selected; selectEntry.append(option)
      }
      selectEntry.addEventListener('change', () => select(selectEntry.value)); heading.append(selectEntry)
    }
    const channels = $('aidr-product-channels')
    // Keep the existing action nodes and their in-flight state/listeners.
    for (const actions of actionGroups.values()) $('aidr-host-status').append(actions)
    $('aidr-compact-diagnostics').append($('aidr-authorization-note'))
    channels.replaceChildren()
    for (const kind of ['logs', 'hooks']) {
      const card = node('section', 'governance-channel-card'), title = node('h3', '', t(kind === 'hooks' && product.hooks === 'native-review-http' ? 'nativeReview' : kind)), status = node('strong', `governance-channel-state state-${state[kind]}`, t(state[kind]))
      card.append(title, status)
      if (kind === 'logs') {
        if (state.logs === 'unknown') card.append(node('p', '', t('checkStatusHint')))
      } else {
        if (state.hooks === 'needsAuth') card.append(node('p', '', t('authHint')))
        else if (state.hooks === 'hostDisabled') card.append(node('p', '', t('hostEnableHint')))
        else if (['unchecked', 'unknown'].includes(state.hooks)) card.append(node('p', '', t('checkStatusHint')))
        else if (automatic && state.hooks === 'notInstalled') card.append(node('p', '', t('automaticHint')))
        else if (state.hooks === 'notEnabled') card.append(node('p', '', t('policyDisabledHint')))
        if (state.hooks === 'pendingPolicy') {
          const syncCode = state.host?.enrollment_sync_code
          const message = ['aidr_enrollment_sync_retrying', 'aidr_enrollment_submitted'].includes(syncCode) ? `code.${syncCode}` : 'enrollment_pending'
          card.append(node('p', 'governance-enrollment-progress', hostText(message)))
        }
        if (actionGroups.has(selected)) card.append(actionGroups.get(selected))
        const authorization = $('aidr-authorization-note')
        authorization.hidden = !managed || !target?.hosts?.includes(selected) || (state.host?.managed_installed === true && data.snapshot?.enabled === true)
        if (!authorization.hidden) card.append(authorization)
      }
      channels.append(card)
    }
    $('aidr-host-status').parentElement.hidden = !product.hooks
  }
  window.aidrWorkbench = { init, render, productState: (id, data) => states(window.aidrProducts.find(product => product.id === id), data) }
})()
