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
export const getSkillScanReport = (skillIdOrName) => api.get(`/v1/skills/${skillIdOrName}/scan-report`)
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
export const prepareRemoteImport = (data) => api.post('/v1/skills/prepare-remote-import', data)
export const submitRemoteSelected = (data) => api.post('/v1/skills/submit-remote-selected', data)
export const submitUploadSelected = (data) => api.post('/v1/skills/submit-upload-selected', data)
export const submitSkillUrl = (data) => api.post('/v1/skills/submit-url', data)
export const submitClawHubSkill = (data) => api.post('/v1/skills/submit-clawhub', data)
export const approveSkill = (skillId, data) => api.post(`/v1/skills/${skillId}/approve`, data)
export const rejectSkill = (skillId, data) => api.post(`/v1/skills/${skillId}/reject`, data)
export const deploySkill = (skillId) => api.post(`/v1/skills/${skillId}/deploy`)
export const retireSkill = (skillId, data) => api.post(`/v1/skills/${skillId}/retire`, data)
export const runtimeCanLoad = (skillName, params = {}) => api.get(`/v1/runtime/can-load/${skillName}`, { params })
export const runtimeCheckTool = (params) => api.get('/v1/runtime/check-tool', { params })
export const getAudit = (params = {}) => api.get('/v1/audit', { params })
export const getAuditPaged = (params = {}) => api.get('/v1/audit', { params: { ...params, page: params.page || 1, page_size: params.page_size || 10 } })
export const getPolicy = () => api.get('/v1/policy')
export const updatePolicy = (data) => api.put('/v1/policy', data)
export const getLlmConfig = () => api.get('/v1/llm-config')
export const updateLlmConfig = (data) => api.put('/v1/llm-config', data)
export const getSandboxConfig = () => api.get('/v1/sandbox-config')
export const updateSandboxConfig = (data) => api.put('/v1/sandbox-config', data)
export const getSkillManagerSystemStatus = () => api.get('/v1/system/status')

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
    if (error.response?.status === 401) {
      const detail = error.response.data?.detail
      if (detail === 'session_expired_elsewhere') {
        alert('您的账号已在其他地方登录，当前会话已失效')
      }
      localStorage.removeItem('token')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export default api
