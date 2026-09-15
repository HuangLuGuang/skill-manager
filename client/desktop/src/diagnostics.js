(() => {
  let version = 'unknown'
  const errors = new Map()
  const send = record => {
    try {
      Promise.resolve(window.__TAURI__.core.invoke('record_desktop_diagnostic', {
        record: { ...record, version },
      })).catch(() => {})
    } catch { /* Logging must not recursively create unhandled errors. */ }
  }
  const flush = () => {
    for (const record of errors.values()) {
      if (record.count > 0) send(record)
    }
    errors.clear()
  }
  const report = (event, value) => {
    const message = String(value?.stack || value?.message || value || 'Unknown desktop error').slice(0, 4000)
    const key = `${event}:${message}`
    const previous = errors.get(key)
    if (previous) {
      previous.count++
      return
    }
    // Bound both the aggregation memory and native subprocess traffic.
    if (errors.size >= 20) {
      const overflow = errors.get('overflow') || { event: 'script_error', message: 'Additional desktop errors suppressed', first_at: new Date().toISOString(), count: 0 }
      overflow.count++
      errors.set('overflow', overflow)
      return
    }
    const record = { event, message, count: 1, first_at: new Date().toISOString() }
    send(record)
    errors.set(key, { ...record, count: 0 })
  }
  window.addEventListener('error', event => report('script_error', event.error || event.message))
  window.addEventListener('unhandledrejection', event => report('unhandled_rejection', event.reason))
  window.addEventListener('pagehide', flush)
  setInterval(flush, 60000)
  window.clientDiagnostics = {
    started(value) {
      version = String(value)
      send({ event: 'started', message: '', count: 1, first_at: new Date().toISOString() })
    },
    localState(event, fields = {}) {
      send({ event: String(event), ...fields, message: '', count: 1, first_at: new Date().toISOString() })
    },
  }
})()
