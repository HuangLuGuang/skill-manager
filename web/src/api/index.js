import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export const login = (username, password, captchaId, captchaCode) => {
  const formData = new URLSearchParams()
  formData.append('username', username)
  formData.append('password', password)
  formData.append('captcha_id', captchaId)
  formData.append('captcha_code', captchaCode)
  return api.post('/auth/token', formData)
}

export const getCaptcha = () => api.get('/auth/captcha')
export const getMe = () => api.get('/auth/users/me')
export const changePassword = (oldPassword, newPassword) =>
  api.post('/auth/users/me/password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
export const checkSession = () => api.get('/auth/session-check')

export const getSystemInfo = () => api.get('/system/info')
export const getLogoInfo = () => api.get('/system/logo')

export const listSkills = (params = {}) => api.get('/v1/skills', { params })
export const listSkillsPaged = (params = {}) => api.get('/v1/skills', { params: { ...params, page: params.page || 1, page_size: params.page_size || 10 } })
export const getSkillDetail = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}`)
export const getSkillContent = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/content`)
export const getSkillFiles = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/files`)
export const getSkillFileContent = (skillIdOrName, path) => api.get(`/v1/skills/${skillIdOrName}/file-content`, { params: { path } })
export const downloadSkill = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/download`, { responseType: 'blob' })
export const getSkillScanReport = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/scan-report`)
export const getSkillGovernanceCard = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/governance-card`)
export const refreshSkillGovernanceCard = (skillIdOrName) => api.post(`/v1/skills/${skillIdOrName}/governance-card/refresh`)
export const verifySkillSignature = (skillIdOrName, data = {}) => api.post(`/v1/skills/${skillIdOrName}/verify-signature`, data)
export const listReviewQueue = () => api.get('/v1/review')
export const listReviewQueuePaged = (params = {}) => api.get('/v1/review', { params: { ...params, page: params.page || 1, page_size: params.page_size || 10 } })
export const submitSkillZip = (formData, params = {}) =>
  api.post('/v1/skills/submit-zip', formData, {
    params,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
export const prepareUploadZip = (formData) =>
  api.post('/v1/skills/prepare-upload-zip', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
export const getLocalImportCandidates = () => api.get('/v1/skills/import-candidates')
export const submitLocalSkills = (data) => api.post('/v1/skills/submit-local', data)
export const submitUploadSelected = (data) => api.post('/v1/skills/submit-upload-selected', data)
export const submitSkillUrl = (data) => api.post('/v1/skills/submit-url', data)
export const approveSkill = (skillId, data) => api.post(`/v1/skills/${skillId}/approve`, data)
export const rejectSkill = (skillId, data) => api.post(`/v1/skills/${skillId}/reject`, data)
export const deploySkill = (skillId) => api.post(`/v1/skills/${skillId}/deploy`)
export const retireSkill = (skillId, data) => api.post(`/v1/skills/${skillId}/retire`, data)
export const rescanSkill = (skillId) => api.post(`/v1/skills/${skillId}/rescan`)
export const deleteSkill = (skillId) => api.delete(`/v1/skills/${skillId}`)
export const runtimeCanLoad = (skillName, params = {}) => api.get(`/v1/runtime/can-load/${skillName}`, { params })
export const runtimeCheckTool = (params) => api.get('/v1/runtime/check-tool', { params })
export const getDashboardRiskSourceStats = () => api.get('/v1/dashboard/risk-source-stats')
export const getAudit = (params = {}) => api.get('/v1/audit', { params })
export const getAuditPaged = (params = {}) => api.get('/v1/audit', { params: { ...params, page: params.page || 1, page_size: params.page_size || 10 } })
export const getPolicy = () => api.get('/v1/policy')
export const updatePolicy = (data) => api.put('/v1/policy', data)
export const getLlmConfig = () => api.get('/v1/llm-config')
export const updateLlmConfig = (data) => api.put('/v1/llm-config', data)
export const getSandboxConfig = () => api.get('/v1/sandbox-config')
export const updateSandboxConfig = (data) => api.put('/v1/sandbox-config', data)
export const testSandboxConfig = (data) => api.post('/v1/sandbox-config/test', data)
export const listSandboxImages = () => api.get('/v1/sandbox-images')
export const getAgentManagerSystemStatus = () => api.get('/v1/system/status')
export const listScannerTokens = () => api.get('/v1/scanner/tokens')
export const createScannerToken = (data) => api.post('/v1/scanner/tokens', data)
export const revokeScannerToken = (tokenId) => api.post(`/v1/scanner/tokens/${tokenId}/revoke`)
export const listAccessTokens = (params = {}) => api.get('/v1/access/tokens', { params })
export const createAccessToken = (data) => api.post('/v1/access/tokens', data)
export const updateAccessToken = (tokenId, data) => api.put(`/v1/access/tokens/${tokenId}`, data)
export const revokeAccessToken = (tokenId) => api.post(`/v1/access/tokens/${tokenId}/revoke`)
export const deleteAccessToken = (tokenId) => api.delete(`/v1/access/tokens/${tokenId}`)
export const listMcpServers = () => api.get('/v1/mcp/servers')
export const createMcpServer = (data) => api.post('/v1/mcp/servers', data)
export const updateMcpServer = (serverId, data) => api.put(`/v1/mcp/servers/${serverId}`, data)
export const deleteMcpServer = (serverId) => api.delete(`/v1/mcp/servers/${serverId}`)
export const discoverMcpServer = (serverId) => api.post(`/v1/mcp/servers/${serverId}/discover`)
export const listMcpGateways = () => api.get('/v1/mcp/gateways')
export const createMcpGateway = (data) => api.post('/v1/mcp/gateways', data)
export const updateMcpGateway = (gatewayId, data) => api.put(`/v1/mcp/gateways/${gatewayId}`, data)
export const deleteMcpGateway = (gatewayId) => api.delete(`/v1/mcp/gateways/${gatewayId}`)
export const listMcpAudit = (params = {}) => api.get('/v1/mcp/audit', { params })
export const debugMcpUpstream = (data) => api.post('/v1/mcp/debug/upstream', data)
export const listScannerDownloads = () => api.get('/v1/scanner/downloads')
export const downloadScannerBinary = (platform) =>
  api.get('/v1/scanner/download', {
    params: { platform },
    responseType: 'blob',
  })
export const downloadSkillVerifier = () =>
  api.get('/v1/scanner/skill-verifier/download', {
    responseType: 'blob',
  })

// LLM Gateway
export const listManagedUsers = () => api.get('/v1/users')
export const createManagedUser = (data) => api.post('/v1/users', data)
export const updateManagedUser = (userId, data) => api.put(`/v1/users/${userId}`, data)
export const listGroups = () => api.get('/v1/groups')
export const createGroup = (data) => api.post('/v1/groups', data)
export const updateGroup = (groupId, data) => api.put(`/v1/groups/${groupId}`, data)
export const listAgents = (params = {}) => api.get('/agents', { params })
export const createAgent = (data) => api.post('/agents', data)
export const updateAgent = (agentId, data) => api.put(`/agents/${agentId}`, data)
export const deleteAgent = (agentId) => api.delete(`/agents/${agentId}`)
export const listClients = () => api.get('/v1/clients')
export const getClientDetail = (clientId) => api.get(`/v1/clients/${clientId}`)
export const updateClientPolicy = (clientId, data) => api.put(`/v1/clients/${clientId}/policy`, data)
export const bindClientAgent = (clientId, agentType, data) => api.put(`/v1/clients/${clientId}/agents/${agentType}`, data)
export const createClientTask = (clientId, data) => api.post(`/v1/clients/${clientId}/tasks`, data)
export const cancelClientTask = (clientId, taskId) => api.post(`/v1/clients/${clientId}/tasks/${taskId}/cancel`)
export const retryClientTask = (clientId, taskId) => api.post(`/v1/clients/${clientId}/tasks/${taskId}/retry`)
export const listClientDownloads = () => api.get('/v1/clients/downloads/available')
export const downloadClientBinary = platform => api.get('/v1/clients/downloads/file', { params: { platform }, responseType: 'blob' })
export const listModelProviders = () => api.get('/v1/model-providers')
export const createModelProvider = (data) => api.post('/v1/model-providers', data)
export const updateModelProvider = (providerId, data) => api.put(`/v1/model-providers/${providerId}`, data)
export const deleteModelProvider = (providerId) => api.delete(`/v1/model-providers/${providerId}`)
export const testModelProvider = (providerId) => api.post(`/v1/model-providers/${providerId}/test`)
export const listModelEndpoints = () => api.get('/v1/models')
export const createModelEndpoint = (data) => api.post('/v1/models', data)
export const updateModelEndpoint = (modelId, data) => api.put(`/v1/models/${modelId}`, data)
export const deleteModelEndpoint = (modelId) => api.delete(`/v1/models/${modelId}`)
export const listLlmApiKeys = () => api.get('/v1/llm-api-keys')
export const createLlmApiKey = (data) => api.post('/v1/llm-api-keys', data)
export const updateLlmApiKey = (keyId, data) => api.put(`/v1/llm-api-keys/${keyId}`, data)
export const revokeLlmApiKey = (keyId) => api.post(`/v1/llm-api-keys/${keyId}/revoke`)
export const deleteLlmApiKey = (keyId) => api.delete(`/v1/llm-api-keys/${keyId}`)
export const listPrivacyPolicies = () => api.get('/v1/privacy-policies')
export const savePrivacyPolicy = (data) => api.post('/v1/privacy-policies', data)
export const deletePrivacyPolicy = (policyId) => api.delete(`/v1/privacy-policies/${policyId}`)
export const getPrivacyStats = () => api.get('/v1/privacy/stats')
export const getLlmStatsOverview = (params = {}) => api.get('/v1/llm-stats/overview', { params })
export const getLlmStatsDaily = (params = {}) => api.get('/v1/llm-stats/daily', { params })
export const getLlmStatsByModel = (params = {}) => api.get('/v1/llm-stats/by-model', { params })
export const getLlmStatsByUser = (params = {}) => api.get('/v1/llm-stats/by-user', { params })
export const testPromptGuard = (data) => api.post('/v1/prompt-guard/test', data)
export const listPrivacyTraces = (params = {}) => api.get('/v1/privacy/traces', { params })
export const getPrivacyTrace = (requestId) => api.get(`/v1/privacy/traces/${requestId}`)
export const listPrivacyMappings = (params = {}) => api.get('/v1/privacy/mappings', { params })
export const deletePrivacyMapping = (mappingId) => api.delete(`/v1/privacy/mappings/${mappingId}`)
export const getPrivacyMappings = (conversationId, tenantId) =>
  api.get(`/v1/privacy/conversations/${conversationId}/mappings`, { params: { tenant_id: tenantId } })
export const deletePrivacyMappings = (conversationId, tenantId) =>
  api.delete(`/v1/privacy/conversations/${conversationId}/mappings`, { params: { tenant_id: tenantId } })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.data?.detail) {
      const detail = error.response.data.detail
      if (Array.isArray(detail)) {
        error.response.data.detail = detail.map(e => e.msg).join('; ')
      }
    }
    if (error.response?.status === 401) {
      const detail = error.response.data?.detail
      if (detail === 'session_expired_elsewhere') {
        alert('登录状态已失效，请重新登录')
      }
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export default api
