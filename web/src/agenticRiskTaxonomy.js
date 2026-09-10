const ASI_CODE = /^ASI(?:0[1-9]|10)$/

export const isAgenticRiskCode = code => ASI_CODE.test(String(code || '').toUpperCase())

export const agenticRiskLabel = (code, t, te) => {
  const normalized = String(code || '').toUpperCase()
  if (!isAgenticRiskCode(normalized)) return String(code || '')
  const key = `agenticRiskTaxonomy.categories.${normalized}`
  return te(key) ? `${normalized} · ${t(key)}` : normalized
}
