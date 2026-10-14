export const integrationCapabilities = {
  skill: ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool'],
  model: ['model:chat'],
  mcp: ['mcp:connect', 'mcp:list-tools', 'mcp:call-tools'],
  trace: ['runtime:trace'],
}

export const parseIntegrationCapabilities = value =>
  typeof value === 'string' ? [...new Set(value.split(',').filter(key => Object.hasOwn(integrationCapabilities, key)))] : []

export const verifierScopes = ['runtime:verify-signature', 'runtime:can-load']

export const integrationScopes = (capabilities, scenario) => scenario === 'verifier'
  ? [...verifierScopes]
  : [...new Set(capabilities.flatMap(key => integrationCapabilities[key] || []))]

export const runtimeApiOrigin = () => {
  const { protocol, hostname, port, origin } = window.location
  if (['localhost', '127.0.0.1'].includes(hostname) && ['5173', '5174'].includes(port)) {
    return `${protocol}//${hostname}:8001`
  }
  return origin
}
