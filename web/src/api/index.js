import axios from 'axios'
import { getCurrentLocale } from '../i18n'
import { getApiErrorCode, localizeApiError } from '../i18n/errors'

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
export const updateMyLocale = (locale) => api.put('/auth/users/me/locale', { locale })
export const changePassword = (oldPassword, newPassword) =>
  api.post('/auth/users/me/password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
export const checkSession = () => api.get('/auth/session-check')

export const getSystemInfo = () => api.get('/system/info')
export const getSystemCapabilities = () => api.get('/system/capabilities')
export const getLogoInfo = () => api.get('/system/logo')
export const listRuntimeTraces = (params = {}) => api.get('/v1/runtime-traces', { params })
export const getRuntimeTrace = traceId => api.get(`/v1/runtime-traces/${traceId}`)
export const listRuntimeTraceRequests = (traceId, params) => api.get(`/v1/runtime-traces/${traceId}/requests`, { params })
export const listRuntimeTraceEvents = (traceId, params = {}) =>
  api.get(`/v1/runtime-traces/${traceId}/events`, { params })
export const authorizeRawRuntimeTraceExport = (traceId, data) =>
  api.post(`/v1/runtime-traces/${traceId}/exports/raw-authorization`, data)
export const createRuntimeTraceExport = (traceId, data) =>
  api.post(`/v1/runtime-traces/${traceId}/exports`, data)
export const downloadRuntimeTraceExport = exportId =>
  api.get(`/v1/runtime-traces/exports/${exportId}/download`, { responseType: 'blob' })
export const listSecurityTargets = () => api.get('/v1/agent-security/targets')
export const getSecurityRedteamOptions = () => api.get('/v1/agent-security/redteam-options')
export const getSecurityRedteamDataset = (name, params = {}) => api.get(`/v1/agent-security/redteam-datasets/${encodeURIComponent(name)}`, { params })
export const createSecurityTarget = data => api.post('/v1/agent-security/targets', data)
export const testSecurityTargetConnectivity = data => api.post('/v1/agent-security/targets/test-connectivity', data)
export const updateSecurityTarget = (targetId, data) => api.patch(`/v1/agent-security/targets/${targetId}`, data)
export const getDifyMcpBindingOptions = targetId =>
  api.get(`/v1/agent-security/targets/${targetId}/dify-mcp-binding-options`)
export const setSecurityTargetCredential = (targetId, data) =>
  api.post(`/v1/agent-security/targets/${targetId}/credentials`, data)
export const updateSecurityTargetCredentialStatus = (credentialId, status) =>
  api.patch(`/v1/agent-security/credentials/${credentialId}/status`, { status })
export const listSecurityPolicies = () => api.get('/v1/agent-security/policies')
export const createSecurityPolicy = data => api.post('/v1/agent-security/policies', data)
export const updateSecurityPolicy = (policyId, data) =>
  api.patch(`/v1/agent-security/policies/${policyId}`, data)
export const listSecurityScanApprovals = (params = {}) => api.get('/v1/agent-security/scan-approvals', { params })
export const createSecurityScanApproval = data => api.post('/v1/agent-security/scan-approvals', data)
export const listSecurityTasks = (params = {}) => api.get('/v1/agent-security/tasks', { params })
export const previewSecurityTask = data => api.post('/v1/agent-security/tasks/preview', data)
export const createSecurityTask = data => api.post('/v1/agent-security/tasks', data)
export const getSecurityTask = taskId => api.get(`/v1/agent-security/tasks/${taskId}`)
export const getSecurityTaskInventory = (taskId, params = {}) =>
  api.get(`/v1/agent-security/tasks/${taskId}/inventory`, { params })
export const compareSecurityTaskInventory = (taskId, baselineTaskId = null) =>
  api.get(`/v1/agent-security/tasks/${taskId}/inventory/compare`, {
    params: baselineTaskId ? { baseline_task_id: baselineTaskId } : {},
  })
export const getSecurityInventoryPromptContent = (taskId, itemId) =>
  api.get(`/v1/agent-security/tasks/${taskId}/inventory/items/${itemId}/content`, {
    params: { confirm: true },
  })
export const cancelSecurityTask = taskId => api.post(`/v1/agent-security/tasks/${taskId}/cancel`)
export const activateSecurityTaskKillSwitch = (taskId, data) =>
  api.post(`/v1/agent-security/tasks/${taskId}/kill-switch`, data)
export const compareSecurityTasks = (taskId, baselineTaskId) =>
  api.get(`/v1/agent-security/tasks/${taskId}/compare/${baselineTaskId}`)
export const listSecurityTaskFindings = taskId => api.get(`/v1/agent-security/tasks/${taskId}/findings`)
export const listSecurityFindings = params => api.get('/v1/agent-security/findings', { params })
export const getSecurityFinding = findingId => api.get(`/v1/agent-security/findings/${findingId}`)
export const listSecurityFindingsForTraceEvent = (traceId, eventId) =>
  api.get('/v1/agent-security/findings/links', { params: { trace_id: traceId, event_id: eventId } })
export const updateSecurityFinding = (findingId, data) =>
  api.patch(`/v1/agent-security/findings/${findingId}`, data)
export const getSecurityArtifactContent = (taskId, artifactId) =>
  api.get(`/v1/agent-security/tasks/${taskId}/artifacts/${artifactId}/content`)
export const exportSecurityScanReportPdf = (taskId, language = 'zh-CN') =>
  api.get(`/v1/agent-security/tasks/${taskId}/scan-report.pdf`, { params: { language }, responseType: 'blob' })
export const getDocsAssistantConfig = () => api.get('/config/docs-assistant')
export const updateDocsAssistantConfig = (data) => api.post('/config/docs-assistant', data)
export const askDocsAssistant = (data) => api.post('/config/docs-assistant/ask', data)

export const listSkills = (params = {}) => api.get('/v1/skills', { params })
export const listSkillsPaged = (params = {}) => api.get('/v1/skills', { params: { ...params, page: params.page || 1, page_size: params.page_size || 10 } })
export const getSkillDetail = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}`)
export const getSkillContent = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/content`)
export const getSkillFiles = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/files`)
export const getSkillFileContent = (skillIdOrName, path) => api.get(`/v1/skills/${skillIdOrName}/file-content`, { params: { path } })
export const downloadSkill = (skillIdOrName, params = {}) => api.get(`/v1/skills/${skillIdOrName}/download`, { params, responseType: 'blob' })
export const getSkillScanReport = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/scan-report`)
export const exportSkillScanReportPdf = (skillIdOrName, language = 'zh-CN') =>
  api.get(`/v1/skills/${skillIdOrName}/scan-report.pdf`, {
    params: { language },
    responseType: 'blob',
  })
export const getSkillVersions = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/versions`)
export const getSkillVersionDiff = (skillIdOrName, params = {}) => api.get(`/v1/skills/${skillIdOrName}/diff`, { params })
export const getSkillVersionScanRuns = (skillIdOrName, versionId) =>
  api.get(`/v1/skills/${skillIdOrName}/versions/${versionId}/scan-runs`)
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
export const updateMcpToolPolicy = (toolId, data) => api.put(`/v1/mcp/tools/${toolId}/policy`, data)
export const createMcpToolApproval = (data) => api.post('/v1/mcp/approvals', data)
export const listMcpApprovalRequests = (params = {}) => api.get('/v1/mcp/approval-requests', { params })
export const getMcpApprovalRequest = (requestId, revealArguments = false) =>
  api.get(`/v1/mcp/approval-requests/${requestId}`, { params: { reveal_arguments: revealArguments } })
export const getMcpApprovalRequestStats = () => api.get('/v1/mcp/approval-requests/stats')
export const approveMcpApprovalRequest = (requestId, data) =>
  api.post(`/v1/mcp/approval-requests/${requestId}/approve`, data)
export const rejectMcpApprovalRequest = (requestId, data) =>
  api.post(`/v1/mcp/approval-requests/${requestId}/reject`, data)
export const listMcpGateways = () => api.get('/v1/mcp/gateways')
export const createMcpGateway = (data) => api.post('/v1/mcp/gateways', data)
export const updateMcpGateway = (gatewayId, data) => api.put(`/v1/mcp/gateways/${gatewayId}`, data)
export const deleteMcpGateway = (gatewayId) => api.delete(`/v1/mcp/gateways/${gatewayId}`)
export const listMcpAudit = (params = {}) => api.get('/v1/mcp/audit', { params })
export const listSecurityAudit = (params = {}) => api.get('/v1/security-audit/events', { params })
export const verifySecurityAudit = () => api.get('/v1/security-audit/verify')
export const listRuntimeTasks = (params = {}) => api.get('/v1/runtime-governance/tasks', { params })
export const getRuntimeTask = (taskId) => api.get(`/v1/runtime-governance/tasks/${taskId}`)
export const killRuntimeTask = (taskId, reason) => api.post(`/v1/runtime-governance/tasks/${taskId}/kill`, null, { params: { reason } })
export const replayRuntimeTask = (taskId) => api.post(`/v1/runtime-governance/replay/${taskId}`)
export const getRuntimePolicy = (agentId) => api.get(`/v1/runtime-governance/policies/${agentId}`)
export const updateRuntimePolicy = (agentId, data) => api.put(`/v1/runtime-governance/policies/${agentId}`, data)
export const listRuntimeKillSwitches = () => api.get('/v1/runtime-governance/kill-switches')
export const createRuntimeKillSwitch = (data) => api.post('/v1/runtime-governance/kill-switches', data)
export const releaseRuntimeKillSwitch = (switchId) => api.delete(`/v1/runtime-governance/kill-switches/${switchId}`)
export const listRuntimeMemories = (params = {}) => api.get('/v1/runtime-governance/memories', { params })
export const reviewRuntimeMemory = (memoryId, data) => api.post(`/v1/runtime-governance/memories/${memoryId}/review`, data)
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
export const createClientDownloadTicket = platform => api.post('/v1/clients/downloads/ticket', null, { params: { platform } })
export const listModelProviders = () => api.get('/v1/model-providers')
export const createModelProvider = (data) => api.post('/v1/model-providers', data)
export const updateModelProvider = (providerId, data) => api.put(`/v1/model-providers/${providerId}`, data)
export const deleteModelProvider = (providerId) => api.delete(`/v1/model-providers/${providerId}`)
export const testModelProvider = (providerId, data) => api.post(`/v1/model-providers/${providerId}/test`, data)
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
export const listModelSkillAlerts = (params = {}) => api.get('/v1/model-gateway/skill-alerts', { params })
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
  config.headers['Accept-Language'] = getCurrentLocale()
  return config
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.data?.error_code) {
      error.apiErrorCode = error.response.data.error_code
      error.apiErrorParams = error.response.data.error_params || {}
      error.response.data.detail = localizeApiError(
        {
          code: error.apiErrorCode,
          message: error.response.data.detail,
          params: error.apiErrorParams,
        },
        getCurrentLocale(),
      )
    }
    if (error.response?.data?.detail) {
      const detail = error.response.data.detail
      if (Array.isArray(detail)) {
        error.response.data.detail = detail.map(e => e.msg).join('; ')
      } else if (typeof detail === 'object') {
        error.apiErrorCode = getApiErrorCode(detail)
        error.apiErrorParams = detail.params || {}
        error.response.data.error = detail
        error.response.data.detail = localizeApiError(detail, getCurrentLocale())
      }
    }
    if (error.response?.status === 401) {
      if (error.apiErrorCode === 'auth.session_expired_elsewhere') {
        alert(error.response.data.detail)
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
