import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { requiresAuth: true } },
  { path: '/agents', name: 'agents', component: () => import('../views/Agents.vue'), meta: { requiresAuth: true } },
  { path: '/clients', name: 'clients', component: () => import('../views/Clients.vue'), meta: { requiresAuth: true } },
  { path: '/credentials', name: 'credentials', component: () => import('../views/Credentials.vue'), meta: { requiresAuth: true } },
  { path: '/mcp-governance/servers', name: 'mcp-servers', component: () => import('../views/McpGateway.vue'), meta: { requiresAuth: true, mcpTab: 'servers' } },
  { path: '/mcp-governance/gateways', name: 'mcp-gateways', component: () => import('../views/McpGateway.vue'), meta: { requiresAuth: true, mcpTab: 'gateways' } },
  { path: '/mcp-governance/approvals', name: 'mcp-approvals', component: () => import('../views/McpApprovals.vue'), meta: { requiresAuth: true } },
  { path: '/mcp-governance/debug', name: 'mcp-debug', component: () => import('../views/McpDebug.vue'), meta: { requiresAuth: true } },
  { path: '/mcp-governance/audit', name: 'mcp-audit', component: () => import('../views/McpGateway.vue'), meta: { requiresAuth: true, mcpTab: 'audit' } },
  { path: '/skills', name: 'skills', component: () => import('../views/Skills.vue'), meta: { requiresAuth: true } },
  { path: '/skills/:skillId', name: 'skill-detail', component: () => import('../views/SkillDetail.vue'), meta: { requiresAuth: true } },
  { path: '/prompts', redirect: '/model-gateway/policies' },
  { path: '/prompts/:promptId', redirect: '/model-gateway/policies' },
  { path: '/submit', name: 'submit-skill', component: () => import('../views/SubmitSkill.vue'), meta: { requiresAuth: true } },
  { path: '/review', name: 'review-queue', component: () => import('../views/ReviewQueue.vue'), meta: { requiresAuth: true } },
  { path: '/runtime', name: 'runtime', component: () => import('../views/RuntimeGovernance.vue'), meta: { requiresAuth: true } },
  { path: '/audit', name: 'audit', component: () => import('../views/AuditLog.vue'), meta: { requiresAuth: true } },
  { path: '/policy', name: 'policy', component: () => import('../views/PolicySettings.vue'), meta: { requiresAuth: true } },
  { path: '/users-groups', name: 'users-groups', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'users-groups' } },
  { path: '/scanner-access', name: 'scanner-access', component: () => import('../views/ScannerAccess.vue'), meta: { requiresAuth: true } },
  { path: '/model-gateway', redirect: '/model-gateway/providers' },
  { path: '/model-gateway/providers', name: 'model-gateway-providers', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'providers' } },
  { path: '/model-gateway/models', name: 'model-gateway-models', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'models' } },
  { path: '/model-gateway/keys', name: 'model-gateway-keys', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'keys' } },
  { path: '/model-gateway/groups', redirect: '/model-gateway/policy-bindings' },
  { path: '/model-gateway/policy-bindings', name: 'model-gateway-policy-bindings', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'policy-bindings' } },
  { path: '/model-gateway/policies', name: 'model-gateway-policies', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'policies' } },
  { path: '/model-gateway/prompt-guard', name: 'model-gateway-prompt-guard', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'prompt-guard' } },
  { path: '/model-gateway/audit', name: 'model-gateway-audit', component: () => import('../views/ModelGateway.vue'), meta: { requiresAuth: true, gatewayTab: 'audit' } },
  { path: '/model-gateway/stats', name: 'model-gateway-stats', component: () => import('../views/ModelGatewayStats.vue'), meta: { requiresAuth: true } },
  { path: '/model-gateway/user-stats', name: 'model-gateway-user-stats', component: () => import('../views/UserTokenStats.vue'), meta: { requiresAuth: true } },
  { path: '/pipeline-trace', name: 'pipeline-trace', component: () => import('../views/PipelineTrace.vue'), meta: { requiresAuth: true } },
  { path: '/settings', name: 'settings', component: () => import('../views/SystemSettings.vue'), meta: { requiresAuth: true } },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFound.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (!to.meta.requiresAuth) {
    next()
    return
  }
  if (!token) {
    next('/login')
    return
  }
  next()
})

export default router
