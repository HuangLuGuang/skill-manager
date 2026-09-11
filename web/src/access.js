import { reactive } from 'vue'
import { iamAccess } from './api'

export const accessState = reactive({ loaded: false, permissions: [], menus: [], default_path: '/access-denied', page_permissions: {} })
let pending
let generation = 0
export const can = code => accessState.permissions.includes(code)
export async function refreshAccess() {
  if (!localStorage.getItem('token')) {
    clearAccess()
    return accessState
  }
  const token = localStorage.getItem('token')
  if (!pending || pending.token !== token) {
    const version = ++generation
    const promise = iamAccess().then(data => {
      if (version === generation && token === localStorage.getItem('token')) Object.assign(accessState, data, { loaded: true })
      return accessState
    }).finally(() => { if (pending?.version === version) pending = null })
    pending = { token, version, promise }
  }
  return pending.promise
}
export function clearAccess() {
  generation += 1
  pending = null
  Object.assign(accessState, { loaded: false, permissions: [], menus: [], default_path: '/access-denied', page_permissions: {} })
}
export function pageAllowed(path) {
  if (['/access-denied', '/login', '/docs'].includes(path) || path.startsWith('/docs/')) return true
  if (path.startsWith('/skills/')) path = '/skills'
  if (path === '/system-audit') return ['login', 'operation', 'security'].some(kind => can(`audit:${kind}`))
  const code = accessState.page_permissions[path]
  return Boolean(code && can(code))
}
export function navigationEntries(items = accessState.menus) {
  return items.map(item => ({
    ...item, key: item.path || item.name,
    children: item.children?.length ? navigationEntries(item.children) : undefined,
  }))
}
export function navigationParents(path, items = accessState.menus, parents = []) {
  if (path.startsWith('/skills/')) path = '/skills'
  for (const item of items) {
    if (item.path === path) return parents
    const nested = navigationParents(path, item.children || [], [...parents, item.path || item.name])
    if (nested.length) return nested
  }
  return []
}
