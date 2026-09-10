export const FEATURE_AGENT_SECURITY_SCANNING = 'agent_security_scanning'
export const FEATURE_RUNTIME_TRACE = 'runtime_trace'

export const DEFAULT_FEATURE_FLAGS = Object.freeze({
  [FEATURE_AGENT_SECURITY_SCANNING]: false,
  [FEATURE_RUNTIME_TRACE]: false,
})

export const normalizeFeatureFlags = value => ({
  ...DEFAULT_FEATURE_FLAGS,
  ...(value && typeof value === 'object' ? value : {}),
})

export const isFeatureEnabled = (features, feature) => (
  !feature || normalizeFeatureFlags(features)[feature] === true
)

export const filterNavigationByFeatures = (items, features) => items.flatMap((item) => {
  if (!isFeatureEnabled(features, item.feature)) return []
  const next = { ...item }
  if (item.children) {
    next.children = filterNavigationByFeatures(item.children, features)
    if (!next.children.length) return []
  }
  return [next]
})
