export const validateServiceEndpoint = value => {
  if (!value.trim()) return 'uiExperience.endpointRequired'
  try {
    const url = new URL(value.trim())
    if (url.protocol === 'http:' || url.protocol === 'https:') return ''
  } catch {}
  return 'uiExperience.endpointInvalid'
}
