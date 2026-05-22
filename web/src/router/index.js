import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { requiresAuth: true } },
  { path: '/skills', name: 'skills', component: () => import('../views/Skills.vue'), meta: { requiresAuth: true } },
  { path: '/skills/:skillId', name: 'skill-detail', component: () => import('../views/SkillDetail.vue'), meta: { requiresAuth: true } },
  { path: '/prompts', name: 'prompts', component: () => import('../views/Prompts.vue'), meta: { requiresAuth: true } },
  { path: '/prompts/:promptId', name: 'prompt-detail', component: () => import('../views/PromptDetail.vue'), meta: { requiresAuth: true } },
  { path: '/submit', name: 'submit-skill', component: () => import('../views/SubmitSkill.vue'), meta: { requiresAuth: true } },
  { path: '/review', name: 'review-queue', component: () => import('../views/ReviewQueue.vue'), meta: { requiresAuth: true } },
  { path: '/deployments', name: 'deployments', component: () => import('../views/Deployments.vue'), meta: { requiresAuth: true } },
  { path: '/runtime', name: 'runtime', component: () => import('../views/RuntimeGovernance.vue'), meta: { requiresAuth: true } },
  { path: '/audit', name: 'audit', component: () => import('../views/AuditLog.vue'), meta: { requiresAuth: true } },
  { path: '/policy', name: 'policy', component: () => import('../views/PolicySettings.vue'), meta: { requiresAuth: true } },
  { path: '/scanner-access', name: 'scanner-access', component: () => import('../views/ScannerAccess.vue'), meta: { requiresAuth: true } },
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
