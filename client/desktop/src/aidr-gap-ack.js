(() => {
  const key = diagnostic => `agent-manager-aidr-gap-ack:${JSON.stringify([diagnostic?.device || '', diagnostic?.queue || ''])}`
  const identity = diagnostic => {
    const gap = diagnostic?.audit_gap
    return gap?.observed_at ? JSON.stringify([gap.observed_at, gap.agent, gap.hook, gap.cause, gap.code]) : null
  }
  globalThis.clientAidrGapAck = {
    isAcknowledged(storage, diagnostic) {
      const value = identity(diagnostic)
      if (!value) return false
      try { return storage.getItem(key(diagnostic)) === value } catch { return false }
    },
    acknowledge(storage, diagnostic) {
      const value = identity(diagnostic)
      if (!value) return false
      storage.setItem(key(diagnostic), value)
      return true
    },
  }
})()
