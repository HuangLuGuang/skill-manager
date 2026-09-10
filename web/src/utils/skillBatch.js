export const canRunSkillAction = (action, record) => {
  if (action === 'rescan') return !record.scan_pending && record.status !== 'PENDING'
  if (action === 'cancel') return Boolean(record.scan_pending) || record.status === 'PENDING'
  return action === 'delete'
}

export const runSkillBatch = async (records, action, execute) => {
  const result = { action, succeeded: [], failed: [], skipped: [] }
  for (const record of records) {
    if (!canRunSkillAction(action, record)) {
      result.skipped.push({ record, reason: action === 'rescan' ? 'already_scanning' : 'no_pending_scan' })
      continue
    }
    try {
      const response = await execute(record)
      if (response?.outcome === 'no_pending_scan' || response?.outcome === 'already_scanning') {
        result.skipped.push({ record: { ...record, ...response }, reason: response.outcome })
        continue
      }
      result.succeeded.push(record)
    } catch (error) {
      result.failed.push({ record, error })
    }
  }
  return result
}
