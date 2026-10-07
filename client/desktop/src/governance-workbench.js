(() => {
  const $ = id => document.getElementById(id)
  const t = key => window.clientI18n.t(`ui.governanceDesign.${key}`)
  const hostText = key => window.clientI18n.t(`ui.aidrDesktop.${key}`)
  const node = (tag, className = '', text = '') => {
    const element = document.createElement(tag)
    element.className = className; element.textContent = text
    return element
  }
  const icons = { claude: 'claude-color.svg', codex: 'codex.png', workbuddy: 'workbuddy.png', qoder: 'qoder.png', cursor: 'cursor.svg', opencode: 'opencode.svg' }
  const groupId = id => id.startsWith('qoder-') ? 'qoder' : id
  const logo = id => {
    const img = node('img', 'governance-product-logo')
    img.src = `./assets/icons/${icons[groupId(id)] || 'bot.svg'}`; img.alt = ''
    return img
  }
  const groups = []
  for (const product of window.aidrProducts || []) {
    if (!product.logs && !product.hooks && groupId(product.id) !== 'qoder') continue
    const id = groupId(product.id)
    let group = groups.find(item => item.id === id)
    if (!group) { group = { id, name: id === 'qoder' ? 'Qoder' : product.name, entries: [] }; groups.push(group) }
    group.entries.push(product)
  }
  let selected = groups[0]?.entries[0]?.id, latest = {}, selectedSignature = ''
  const buttons = new Map(), actionGroups = new Map(), hostCards = new Map()
  function init() {
    $('aidr-runtime-summary').parentElement.append(document.querySelector('[data-aidr-action="retry"]'))
    for (const group of groups) {
      const button = node('button', 'governance-product-option'), text = node('span'), name = node('strong', '', group.name), state = node('small')
      button.type = 'button'; button.append(logo(group.id), text); text.append(name, state)
      button.addEventListener('click', () => select(group.entries[0].id))
      buttons.set(group.id, { button, state }); $('aidr-product-navigation').append(button)
    }
    const hostDetails = node('details', 'governance-diagnostics'), summary = node('summary')
    summary.dataset.i18n = 'ui.governanceDesign.versions'
    summary.textContent = t('versions'); hostDetails.append(summary)
    $('aidr-host-status').before(hostDetails); hostDetails.append($('aidr-host-status'))
    for (const product of (window.aidrProducts || []).filter(item => item.hooks)) {
      const section = $(`aidr-host-${product.id}-status`), card = section.parentElement
      const actions = card.querySelector('.governance-host-actions')
      hostCards.set(product.id, card); actionGroups.set(product.id, actions)
    }
    $('aidr-product-navigation').setAttribute('aria-label', t('products'))
  }
  function select(id) {
    selected = id; selectedSignature = ''; render(latest)
    $('aidr-product-inspector').scrollTop = 0
  }
  function states(product, data) {
    const target = data.snapshot?.policy?.target, host = data.hosts?.[product.id], plugin = host?.plugin
    const policy = data.collection?.runtime_policy
    const logTarget = policy?.target
    const logSources = logTarget?.log_sources ?? ['claude', 'codex']
    const logs = !product.logs ? 'unsupported' : !logTarget || data.collectionError ? 'unknown'
      : logTarget.enabled && logTarget.channels?.logs && logSources.includes(product.id) ? 'inPolicy' : 'notEnabled'
    const stamp = Date.parse(plugin?.reported_at)
    const current = Number.isFinite(stamp) && Date.now() - stamp < 480000 && stamp <= Date.now() + 5000
    const installed = current ? plugin?.installed : null
    const trusted = current && ['managed', 'trusted'].includes(host?.hook_trust)
    const enabled = target?.enabled && target.channels?.hooks !== false && target.hosts?.includes(product.id) && data.snapshot?.enabled
    const requested = data.collection?.user_hook_hosts?.includes(product.id)
    const hooks = !product.hooks ? 'unsupported' : !host ? 'unchecked' : host.error || !current ? 'unknown'
      : installed == null ? 'unknown' : !installed ? 'notInstalled' : host.hook_trust === 'needs_review' ? 'needsAuth'
      : !enabled ? requested ? 'pendingPolicy' : 'notEnabled' : plugin.enabled === false ? 'hostDisabled' : 'configured'
    return { logs, hooks, installed, trusted, enabled, current, host, plugin }
  }
  function render(data) {
    latest = data
    $('aidr-product-navigation').setAttribute('aria-label', t('products'))
    $('aidr-host-status').parentElement.querySelector('summary').textContent = t('versions')
    const product = (window.aidrProducts || []).find(item => item.id === selected)
    if (!product) return
    const group = groups.find(item => item.id === groupId(selected))
    for (const item of groups) {
      const entry = item.id === group.id ? product : item.entries[0]
      const state = states(entry, data), ui = buttons.get(item.id)
      ui.button.setAttribute('aria-pressed', String(item.id === group.id))
      ui.state.textContent = item.entries.length > 1 ? t('multipleEntries') : `Hook · ${t(state.hooks)}`
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
    const signature = JSON.stringify([selected, state, report?.state, fresh, data.collectionError, window.clientI18n.getLocale()])
    if (signature === selectedSignature) return
    selectedSignature = signature
    const heading = $('aidr-product-heading'); heading.replaceChildren()
    const titles = node('div'), name = node('h2', '', group.name), entry = node('p', '', hostText(`entry_${product.entry.replaceAll('-', '_')}`))
    titles.append(name, entry); heading.append(logo(group.id), titles)
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
    channels.replaceChildren()
    for (const kind of ['logs', 'hooks']) {
      const card = node('section', 'governance-channel-card'), title = node('h3', '', t(kind)), status = node('strong', `governance-channel-state state-${state[kind]}`, t(state[kind]))
      card.append(title, status)
      if (kind === 'logs') {
        card.append(node('p', '', t(product.logs ? 'logScope' : 'logUnsupported')))
        if (product.logs) {
          card.append(node('p', 'governance-channel-meta', `${t('sharedLogChannel')} · ${fresh ? hostText(`channel_state_${report.state}`) : t('unknown')}`))
        }
      } else {
        if (product.hooks) card.append(node('p', 'governance-channel-meta', t(product.hooks === 'native-plugin' ? 'nativeName' : 'hookName')))
        card.append(node('p', '', t(state.hooks === 'needsAuth' ? 'authHint' : product.hooks ? 'hookHint' : 'hookUnsupported')))
        if (actionGroups.has(selected)) card.append(actionGroups.get(selected))
      }
      channels.append(card)
    }
    $('aidr-host-status').parentElement.hidden = !product.hooks
    const progress = $('aidr-product-progress'); progress.replaceChildren(); progress.hidden = !product.hooks
    if (product.hooks) {
      progress.append(node('h3', '', t('progress')))
      const list = node('ol', 'governance-steps')
      for (const [label, confirmed] of [['installed', state.installed === true], ['authorized', state.trusted], ['policyEnabled', state.enabled === true], ['delivery', false]]) {
        const item = node('li', confirmed ? 'confirmed' : '')
        item.append(node('span', '', t(label)), node('small', '', t(confirmed ? 'confirmed' : label === 'delivery' ? 'checkPlatform' : 'unconfirmed')))
        list.append(item)
      }
      progress.append(list)
    }
  }
  window.aidrWorkbench = { init, render }
})()
