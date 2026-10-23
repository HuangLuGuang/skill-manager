(() => {
  const mt = key => t(`ui.manualModel.${key}`)
  const h = escapeHtml
  let state = null
  const dialog = document.createElement('dialog')
  dialog.className = 'manual-model-dialog'
  dialog.setAttribute('aria-labelledby', 'manual-model-title')
  document.body.append(dialog)
  const target = () => ({ local_agent_id: state.agent.local_agent_id, agent_type: state.agent.agent_type })
  const call = (operation, payload = target()) => invoke('manual_model_action', { operation, payload })
  const allowed = () => Boolean(connection?.platform?.model_configuration?.can_export_manual_credentials)
  const gatewayURL = () => {
    if (source() === 'external_gateway' && !state.options?.gateway_url) return ''
    const base = (state.options?.gateway_url || connection?.server || '').replace(/\/+$/, '')
    return state.protocol === 'anthropic' ? base.replace(/\/v1$/, '') : /\/v1$/.test(base) ? base : `${base}/v1`
  }
  const source = () => state.options?.source || (connection?.platform?.model_configuration?.model_routing?.external_gateway_enabled ? 'external_gateway' : 'internal')
  const errorText = error => {
    const raw = String(error)
    const code = raw.match(/"error_code"\s*:\s*"([\w.]+)"/)?.[1] || raw.match(/manual_model_\w+/)?.[0]
    const translated = t(`ui.manualModel.error.${code}`)
    return code && translated !== `ui.manualModel.error.${code}` ? translated : mt('requestFailed')
  }
  const run = async action => {
    if (!state || state.busy) return
    const current = state
    current.busy = true
    current.error = ''
    current.notice = ''
    render()
    try { await action() } catch (error) { if (state === current) {
      current.error = errorText(error)
      if (String(error).includes('manual_model_copy_expired')) current.copyAvailable = false
    } }
    finally { if (state === current) { current.busy = false; render() } }
  }
  const load = async () => {
    await refreshConnection()
    if (!allowed()) { state.options = null; state.handoff = null; return }
    state.options = await call('options')
    if (state.options.handoff) {
      state.handoff = state.options.handoff
      state.payload = Object.fromEntries(['local_agent_id', 'agent_type', 'request_id', 'model', 'source', 'protocol'].map(key => [key, state.handoff[key]]))
      state.model = state.options.models.some(item => item.name === state.handoff.model) ? state.handoff.model : (state.options.models[0]?.name || '')
      state.copyAvailable = false
      if (state.protocol === state.handoff.protocol && state.model === state.handoff.model) {
        const result = await call('issue', state.payload)
        state.copyAvailable = result.copy_available
      }
    } else {
      state.handoff = null
      state.copyAvailable = false
      state.saved = false
      if (!state.options.models.some(item => item.name === state.model)) state.model = state.options.models[0]?.name || ''
    }
  }
  const close = () => {
    if (state?.busy) return
    state = null
    dialog.close()
    void call('clear', {}).catch(() => {})
  }
  dialog.addEventListener('cancel', event => { event.preventDefault(); close() })
  const checkbox = (id, key, checked) => `<label class="manual-model-check"><input id="${id}" type="checkbox" ${checked ? 'checked' : ''}>${h(mt(key))}</label>`
  const row = (label, value, copy) => `<div class="manual-model-row"><dt>${h(label)}</dt><dd><span>${h(value)}</span>${copy ? `<button type="button" class="icon-button icon-copy" data-manual-copy="${h(value)}" aria-label="${h(mt('copy'))}">${h(mt('copy'))}</button>` : ''}</dd></div>`
  function render() {
    if (!state) return
    const s = state
    const models = s.options?.models || []
    let body
    if (s.step === 1) {
      body = `<h3>${h(mt('findSettings'))}</h3><p>${h(mt('findHelp'))}</p><p class="manual-model-note">${h(mt('pathUnknown'))}</p>
        <h4>${h(mt('requirements'))}</h4><ul><li>${h(mt('addressSupport'))}</li><li>${h(mt('keySupport'))}</li><li>${h(mt('protocolSupport'))}</li></ul>
        <label>${h(mt('protocol'))}<select id="manual-protocol"><option value="">${h(mt('selectProtocol'))}</option>${[['openai', 'OpenAI Chat Completions'], ['responses', 'OpenAI Responses'], ['anthropic', 'Anthropic Messages']].map(([v, name]) => `<option value="${v}" ${s.protocol === v ? 'selected' : ''}>${name}</option>`).join('')}</select></label>
        ${checkbox('manual-compatible', 'compatible', s.compatible)}<p>${h(mt('unsupportedHelp'))}</p>`
    } else if (s.step === 2) {
      body = `<h3>${h(mt('step2'))}</h3><p>${h(mt('fillHelp'))}</p><dl class="manual-model-fields">
        ${row(mt('protocol'), { openai: 'OpenAI Chat Completions', responses: 'OpenAI Responses', anthropic: 'Anthropic Messages' }[s.protocol])}
        ${row('Base URL', gatewayURL() || '—', Boolean(gatewayURL()))}</dl>
        <label>${h(mt('model'))}<select id="manual-model" ${s.copyAvailable || s.busy ? 'disabled' : ''}>${models.length ? models.map(model => `<option value="${h(model.name)}" ${model.name === s.model ? 'selected' : ''}>${h(model.display_name || model.name)} · ${h(model.name)}</option>`).join('') : `<option value="">${h(mt('noModels'))}</option>`}</select></label>
        <dl>${row(mt('modelName'), s.model || '—', Boolean(s.model))}</dl>
        <h4>${h(mt('credential'))} <span class="manual-model-badge">${h(mt(!allowed() ? 'denied' : s.handoff ? 'received' : 'permitted'))}</span></h4>`
      if (!allowed()) {
        body += `<div class="manual-model-note">${h(mt('permissionHelp'))}</div><button id="manual-reload" type="button">${h(mt('recheck'))}</button>`
      } else if (!s.options) {
        body += `<button id="manual-reload" type="button">${h(mt('loadModels'))}</button>`
      } else if (!s.handoff) {
        body += `<p>${h(mt('issueHelp'))}</p><button id="manual-issue" class="primary" type="button" ${!s.model ? 'disabled' : ''}>${h(mt(s.busy ? 'requesting' : 'issue'))}</button>`
      } else {
        body += `<p>${h(mt('boundTo'))} ${h(s.agent.name || agentLabel(s.agent.agent_type))}</p>
          ${s.copyAvailable ? `<div class="manual-model-secret"><span aria-label="${h(mt('masked'))}">••••••••••••••••</span><button id="manual-copy-key" class="primary" type="button">${h(mt('copyCredential'))}</button></div><p>${h(mt('copyHelp'))}</p>` : `<p class="manual-model-note">${h(mt('copyExpired'))}</p>${s.confirmReplace ? `<p class="manual-model-note">${h(mt(source() === 'internal' ? 'replaceConfirm' : 'externalReissueConfirm'))}</p><button id="manual-replace-confirm" type="button" class="primary">${h(mt('confirmReplace'))}</button> <button id="manual-replace-cancel" type="button">${h(mt('cancel'))}</button>` : `<button id="manual-replace" type="button">${h(mt('replace'))}</button>`}`}
          ${s.handoff.expires_at ? `<p>${h(mt('expires'))} ${h(formatTime(s.handoff.expires_at))}</p>` : ''}
          ${checkbox('manual-saved', 'saved', s.saved)}`
      }
      if (source() === 'external_gateway') body += `<p class="manual-model-footnote">${h(mt('externalScope'))}</p>`
    } else {
      body = `<h3>${h(mt('verifyTitle'))}</h3><ol><li><strong>${h(mt('restart'))}</strong><p>${h(mt('restartHelp'))}</p></li><li><strong>${h(mt('test'))}</strong><p>${h(mt('testHelp'))}</p></li></ol>
        <dl>${row(mt('testMessage'), mt('testPrompt'), true)}</dl><h4>${h(mt('evidence'))}</h4><p>${h(mt('evidenceHelp'))}</p>
        <dl class="manual-model-fields">${row(mt('configSaved'), mt('userConfirmed'))}${row(mt('callStatus'), mt('unverified'))}</dl>
        <p class="manual-model-note">${h(mt('completionHelp'))}</p><h4>${h(mt('failure'))}</h4><p>${h(mt('failureHelp'))}</p>`
    }
    const nextDisabled = s.busy || (s.step === 1 && (!s.compatible || !s.protocol)) || (s.step === 2 && (!s.handoff || !s.saved))
    dialog.innerHTML = `<header><div><h2 id="manual-model-title">${h(mt('title'))}</h2><span>${h(s.agent.name || agentLabel(s.agent.agent_type))}</span></div><button type="button" id="manual-close" class="icon-button icon-close" aria-label="${h(mt('close'))}" ${s.busy ? 'disabled' : ''}>${h(mt('close'))}</button></header>
      <ol class="manual-model-steps">${[1, 2, 3].map(step => `<li ${s.step === step ? 'aria-current="step"' : ''} class="${s.step === step ? 'active' : ''}"><b>${step}</b><span>${h(mt(`step${step}`))}</span></li>`).join('')}</ol>
      <div class="manual-model-body">${body}<p class="manual-model-error" role="alert">${h(s.error || '')}</p><p role="status">${h(s.notice || '')}</p></div>
      <footer><button id="manual-back" ${s.busy ? 'disabled' : ''}>${h(mt(s.step === 1 ? 'cancel' : 'back'))}</button><button id="manual-next" class="primary" ${nextDisabled ? 'disabled' : ''}>${h(mt(s.step === 3 ? 'finish' : s.step === 2 ? 'savedNext' : 'foundNext'))}</button></footer>`
    if (s.busy) dialog.querySelectorAll('button, input, select').forEach(node => { node.disabled = true })
    dialog.querySelector('#manual-close').onclick = close
    dialog.querySelector('#manual-back').onclick = () => { if (s.step === 1) close(); else { s.step--; s.notice = ''; s.error = ''; render() } }
    dialog.querySelector('#manual-next').onclick = () => {
      if (nextDisabled) return
      if (s.step === 3) { close(); return }
      s.step++
      s.notice = ''
      s.error = ''
      render()
      if (s.step === 2) void run(load)
    }
    const bind = (id, event, fn) => { const node = dialog.querySelector(`#${id}`); if (node) node[event] = fn }
    bind('manual-protocol', 'onchange', event => { s.protocol = event.target.value; s.handoff = null; s.saved = false; render() })
    bind('manual-compatible', 'onchange', event => { s.compatible = event.target.checked; render() })
    bind('manual-model', 'onchange', event => { s.model = event.target.value; s.requestId = null; s.saved = false; render() })
    bind('manual-saved', 'onchange', event => { s.saved = event.target.checked; render() })
    bind('manual-reload', 'onclick', () => run(load))
    const issue = async replace => {
      if (!s.requestId || (replace && s.replaceRequestId !== s.handoff.request_id)) s.requestId = crypto.randomUUID()
      s.replaceRequestId = replace ? s.handoff.request_id : null
      s.payload = { ...target(), request_id: s.requestId, model: s.model, protocol: s.protocol, source: source(), ...(replace ? { replace_request_id: s.handoff.request_id } : {}) }
      const result = await call('issue', s.payload)
      s.handoff = result
      s.copyAvailable = result.copy_available
      s.saved = false
      s.confirmReplace = false
    }
    bind('manual-issue', 'onclick', () => run(() => issue(false)))
    bind('manual-replace', 'onclick', () => { s.confirmReplace = true; render() })
    bind('manual-replace-cancel', 'onclick', () => { s.confirmReplace = false; render() })
    bind('manual-replace-confirm', 'onclick', () => run(() => issue(true)))
    bind('manual-copy-key', 'onclick', () => run(async () => {
      // Begin the clipboard write during the click; WebKit requires a live user gesture.
      let authorizationError
      const content = call('copy', s.payload).then(result => {
        try { return new Blob([result.token], { type: 'text/plain' }) }
        finally { result.token = '' }
      }).catch(error => { authorizationError = error; throw error })
      try {
        // WebKit can finish write() before the promised payload rejects; await both outcomes.
        await Promise.all([navigator.clipboard.write([new ClipboardItem({ 'text/plain': content })]), content])
        s.notice = mt('copiedCredential')
      } catch {
        await content.catch(() => {})
        if (authorizationError) throw authorizationError
        s.error = mt('copyFailed')
      }
    }))
    dialog.querySelectorAll('[data-manual-copy]').forEach(button => { button.onclick = () => run(async () => {
      try { await navigator.clipboard.writeText(button.dataset.manualCopy); s.notice = mt('copied') }
      catch { s.error = mt('copyFailed') }
    }) })
  }
  window.manualModelGuide = { open(agent) {
    state = { agent, step: 1, protocol: '', compatible: false, model: '', options: null, handoff: null, busy: false, saved: false }
    render()
    dialog.showModal()
  } }
  window.addEventListener('agent-manager-client-locale-change', render)
})()
