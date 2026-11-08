export const optionalAnalysisColumns = ['rule', 'skillspector', 'sandbox']
export const defaultSkillColumns = ['name', 'version', 'trustedVersion', 'status', 'risk', 'llm', 'approved_by', 'updated_at', 'actions']
export const readVisibleColumns = (storage, key, previousKey) => {
  try {
    const saved = storage.getItem(key)
    if (saved !== null) {
      const value = JSON.parse(saved)
      const columns = Array.isArray(value) ? [...defaultSkillColumns, 'skill_id', 'submitterSource', ...optionalAnalysisColumns].filter(item => value.includes(item)) : []
      // 旧版可保存空列设置，读取时恢复默认以保留可读业务列。
      return columns.length ? columns : [...defaultSkillColumns]
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
  // 已执行但缺少风险值时仍展示执行状态，避免误显示为未记录。
  if (key === 'sandbox' && result.executed === true && !result.risk_level) return { state: 'executed' }
  return result.risk_level ? { risk: result.risk_level } : { state: 'unrecorded' }
}
