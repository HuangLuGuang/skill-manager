export const optionalAnalysisColumns = ['rule', 'skillspector', 'sandbox']
export const defaultSkillColumns = ['name', 'version', 'trustedVersion', 'status', 'risk', 'llm', 'approved_by', 'updated_at', 'actions']
export const readVisibleColumns = (storage, key, previousKey) => {
  try {
    const saved = storage.getItem(key)
    if (saved !== null) {
      const value = JSON.parse(saved)
      return Array.isArray(value) ? [...defaultSkillColumns, 'skill_id', ...optionalAnalysisColumns].filter(item => value.includes(item)) : [...defaultSkillColumns]
    }
    const previous = JSON.parse(storage.getItem(previousKey) || '[]')
    return [...defaultSkillColumns, ...(Array.isArray(previous) ? optionalAnalysisColumns.filter(item => previous.includes(item)) : [])]
  } catch { return [...defaultSkillColumns] }
}
export const analysisCell = (record, key) => {
  if (record.scan_pending || record.status === 'PENDING') return { state: 'pending' }
  const result = record.analysis_results?.[key]
  if (!result) return { state: 'unrecorded' }
  if (result.status !== 'completed') return { state: ['failed', 'skipped', 'disabled', 'pending'].includes(result.status) ? result.status : 'unrecorded' }
  if (key === 'rule') return { count: result.findings_count ?? 0 }
  return result.risk_level ? { risk: result.risk_level } : { state: 'unrecorded' }
}
