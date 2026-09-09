export const rescanCapabilities = status => ({
  use_behavioral: true,
  use_skillspector: Boolean(status?.skillspector_available),
  use_sandbox: Boolean(status?.sandbox_enabled && status?.sandbox_available),
  use_llm: Boolean(status?.llm_enabled && status?.llm_model),
})

export const rescanOptions = (mode, selected, status) => {
  if (mode === 'previous') return { use_behavioral: true }
  const available = rescanCapabilities(status)
  return {
    ...Object.fromEntries(Object.keys(available).map(key => [key, Boolean(selected[key] && available[key])])),
    use_behavioral: true,
  }
}
