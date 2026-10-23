(() => {
  const isCertified = skill => Boolean(skill?.signature) && skill.governance?.signature === skill.signature && skill.governance?.certification === 'certified'
  const isScanActive = scan => ['submitted', 'PENDING', 'VETTED'].includes(scan?.status)
  const completedInBackground = (result, skill, scan, startedAt) => result?.status === 'failed'
    && result.error === 'skill_action_busy'
    && Boolean(result.item.signature) && skill?.signature === result.item.signature
    && skill?.path === result.item.path && skill.governance?.signature === result.item.signature
    && Boolean(scan?.skill_id) && Date.parse(scan.submitted_at) >= startedAt

  // Serial execution limits upload pressure and preserves per-item results.
  const execute = async (items, operation, progress = () => {}) => {
    const results = []
    for (const item of items) {
      let result
      try {
        const value = await operation(item)
        result = { item, status: value?.skipped ? 'skipped' : 'succeeded', reason: value?.skipped || (value?.already_submitted ? 'already_submitted' : '') }
      } catch (error) {
        result = { item, status: 'failed', error: String(error) }
      }
      results.push(result)
      progress(result, results.length)
    }
    return results
  }
  globalThis.clientSkillBatch = { isCertified, isScanActive, execute, completedInBackground }
})()
