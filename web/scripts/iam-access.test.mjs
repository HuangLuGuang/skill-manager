import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import dayjs from 'dayjs'
import { reactive, ref, computed, watch, nextTick, effectScope } from 'vue'
import { baseCompile } from '@intlify/message-compiler'
import { parse } from '@vue/compiler-sfc'
import { parse as parseScript } from '@babel/parser'
import { iamMessages } from '../src/i18n/iam.js'

const source = await readFile(new URL('../src/access.js', import.meta.url), 'utf8')
function accessHarness() {
  const requests = []
  let token = 'first-account'
  const iamAccess = () => new Promise((resolve, reject) => requests.push({ resolve, reject }))
  const localStorage = { getItem: () => token }
  const script = source.replace(/^import .*$/gm, '').replace(/^export /gm, '')
  const access = new Function('reactive', 'iamAccess', 'localStorage', `${script}\nreturn { accessState, refreshAccess, clearAccess, can, pageAllowed, navigationParents }`)(reactive, iamAccess, localStorage)
  return { ...access, requests, setToken: value => { token = value } }
}

test('a logged-out account cannot restore permissions from a late request', async () => {
  const h = accessHarness()
  const old = h.refreshAccess()
  h.setToken(null)
  h.clearAccess()
  h.requests[0].resolve({ permissions: ['users:delete'] })
  await old
  assert.equal(h.accessState.loaded, false)
  assert.equal(h.can('users:delete'), false)
})

test('switching accounts starts a new request and ignores the old response', async () => {
  const h = accessHarness()
  const first = h.refreshAccess()
  h.setToken('second-account')
  const second = h.refreshAccess()
  assert.equal(h.requests.length, 2)
  h.requests[1].resolve({ permissions: ['skills:view'] })
  await second
  h.requests[0].resolve({ permissions: ['users:delete'] })
  await first
  assert.equal(h.can('skills:view'), true)
  assert.equal(h.can('users:delete'), false)
})

test('concurrent refreshes share a request and failures allow retry', async () => {
  const h = accessHarness()
  const first = h.refreshAccess()
  const second = h.refreshAccess()
  assert.equal(h.requests.length, 1)
  h.requests[0].reject(new Error('offline'))
  assert.deepEqual((await Promise.allSettled([first, second])).map(r => r.status), ['rejected', 'rejected'])
  const retry = h.refreshAccess()
  h.requests[1].resolve({ permissions: ['users:view'] })
  await retry
  assert.equal(h.can('users:view'), true)
})

test('routes and nested menu selection follow the current grants', () => {
  const h = accessHarness()
  Object.assign(h.accessState, {
    permissions: ['skills:view', 'audit:login'],
    page_permissions: { '/skills': 'skills:view', '/users': 'users:view' },
    menus: [{ name: 'governance', children: [{ name: 'skills', path: '/skills' }] }],
  })
  assert.equal(h.pageAllowed('/skills/version-123'), true)
  assert.equal(h.pageAllowed('/users'), false)
  assert.equal(h.pageAllowed('/system-audit'), true)
  assert.deepEqual(h.navigationParents('/skills/version-123'), ['governance'])
})

const flatten = (value, prefix = '') => Object.entries(value).flatMap(([key, item]) => typeof item === 'string' ? [[prefix + key, item]] : flatten(item, `${prefix}${key}.`))
test('IAM messages have matching Chinese and English keys and placeholders', () => {
  const zh = Object.fromEntries(flatten(iamMessages['zh-CN']))
  const en = Object.fromEntries(flatten(iamMessages['en-US']))
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort())
  for (const [key, value] of Object.entries(zh)) {
    const params = text => [...text.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort()
    assert.deepEqual(params(value), params(en[key]), key)
    for (const text of [value, en[key]]) baseCompile(text, { onError: error => { throw error } })
  }
})

async function viewFunction(view, name, context) {
  const file = await readFile(new URL(`../src/views/${view}.vue`, import.meta.url), 'utf8')
  const script = parse(file).descriptor.scriptSetup.content
  const body = parseScript(script, { sourceType: 'module' }).program.body
  const declarations = body.flatMap(node => node.declarations || [])
  const node = declarations.find(item => item.id.name === name)?.init || body.find(item => item.type === 'FunctionDeclaration' && item.id.name === name)
  assert.ok(node, `${view}.${name}`)
  return new Function(...Object.keys(context), `return (${script.slice(node.start, node.end)})`)(...Object.values(context))
}

test('system overview distinguishes restricted and unavailable sources from empty configuration', async () => {
  const sourceStatus = { value: {} }
  const load = await viewFunction('SystemSettings', 'loadSource', { sourceStatus, can: code => code === 'settings:view' })
  let requested = false
  const fallback = await load('models', 'models:view', () => { requested = true }, [])
  assert.deepEqual(fallback, [])
  assert.equal(requested, false)
  assert.equal(sourceStatus.value.models, 'restricted')
  await load('manager', 'settings:view', async () => { throw new Error('offline') }, {})
  assert.equal(sourceStatus.value.manager, 'unavailable')
  const present = await viewFunction('SystemSettings', 'withSourceStatus', {
    sourceStatus, capabilitySources: { models: ['models'], api: ['manager'] }, t: key => key,
  })
  const models = present({ key: 'models', status: 'error', meta: [{ value: '0' }] })
  assert.equal(models.status, 'unknown')
  assert.deepEqual(models.meta, [])
  assert.equal(models.statusText, 'iam.dataRestricted')
  assert.equal(present({ key: 'api', status: 'ok' }).statusText, 'iam.dataUnavailable')
  await load('manager', 'settings:view', async () => ({ running: true }), {})
  assert.equal(present({ key: 'api', status: 'ok' }).status, 'ok')
})

test('a slow account response cannot replace a newly selected menu page', async () => {
  const pending = []
  const context = {
    kind: { value: 'users' }, loadState: { version: 0 }, loading: {}, rows: {}, options: {},
    filters: {}, pager: { current: 1, pageSize: 20 },
    iamList: kind => new Promise(resolve => pending.push({ kind, resolve })),
    loadOptions: async () => {}, error: error => { throw error },
  }
  const load = await viewFunction('IdentityManagement', 'load', context)
  const accounts = load()
  context.kind.value = 'menus'
  const menus = load()
  pending[1].resolve([{ name: 'menu' }])
  await menus
  pending[0].resolve({ items: [{ username: 'old-account' }], total: 99 })
  await accounts
  assert.deepEqual(context.rows.value, [{ name: 'menu' }])
  assert.equal(context.pager.total, 0)
  assert.equal(context.loading.value, false)
})

test('personal password submission prevents duplicates and keeps failed edits open', async () => {
  let rejectRequest, count = 0
  const errors = []
  const context = {
    passwordSaving: { value: false }, passwordVisible: { value: true },
    passwordForm: { oldPassword: 'OldPassword!', newPassword: 'NewPassword!', confirmPassword: 'NewPassword!' },
    changePassword: () => { count += 1; return new Promise((_, reject) => { rejectRequest = reject }) },
    message: { error: error => errors.push(error), success: () => { throw new Error('Unexpected success') } },
    handleLogout: () => { throw new Error('Unexpected logout') }, phrase: key => key, t: key => key,
  }
  const submit = await viewFunction('../App', 'handlePasswordOk', context)
  const first = submit()
  await submit()
  assert.equal(count, 1)
  rejectRequest({ response: { data: { detail: 'Current password is incorrect' } } })
  await first
  assert.equal(context.passwordSaving.value, false)
  assert.equal(context.passwordVisible.value, true)
  assert.deepEqual(errors, ['Current password is incorrect'])
})

test('audit tab changes ignore stale rows and omit hidden login filters', async () => {
  const pending = []
  const context = {
    kind: { value: 'operation' }, kinds: { value: ['operation', 'login'] }, loadState: { version: 0 },
    loading: {}, loadError: {}, rows: {}, dates: { value: [] }, pager: { current: 1, pageSize: 20 },
    filters: { module: 'roles', action: 'grant', actor: 'admin' },
    dateFilter: value => value,
    iamList: (path, query) => new Promise(resolve => pending.push({ path, query, resolve })),
    message: { error: error => { throw error } }, t: key => key,
  }
  const load = await viewFunction('SystemAudit', 'load', context)
  const operations = load()
  context.kind.value = 'login'
  const login = load()
  assert.equal(pending[1].query.module, undefined)
  assert.equal(pending[1].query.action, undefined)
  assert.equal(pending[1].query.actor, 'admin')
  pending[0].resolve({ items: [{ action: 'grant' }], total: 3 })
  await operations
  assert.equal(context.loading.value, true)
  pending[1].resolve({ items: [{ action: 'login' }], total: 1 })
  await login
  assert.deepEqual(context.rows.value, [{ action: 'login' }])
  assert.equal(context.pager.total, 1)
})

test('audit date filters interpret the selected clock time in Beijing across browser timezones', async () => {
  const original = process.env.TZ
  const dateFilter = await viewFunction('SystemAudit', 'dateFilter', {})
  try {
    for (const zone of ['America/Los_Angeles', 'Asia/Shanghai', 'UTC']) {
      process.env.TZ = zone
      const parameter = dateFilter(dayjs('2026-09-11T00:30:00'))
      assert.equal(new Date(parameter).toISOString(), '2026-09-10T16:30:00.000Z', zone)
    }
    assert.equal(dateFilter(undefined), undefined)
  } finally {
    if (original === undefined) delete process.env.TZ
    else process.env.TZ = original
  }
})

test('clearing account sorting restores creation-time order', async () => {
  const pager = { current: 2, pageSize: 20, sort: 'last_login_at', order: 'asc' }
  let calls = 0
  const change = await viewFunction('IdentityManagement', 'tableChange', { pager, load: () => { calls++ } })
  change({ current: 1, pageSize: 20 }, {}, { field: 'last_login_at', order: undefined })
  assert.equal(pager.sort, 'created_at')
  assert.equal(pager.order, 'desc')
  assert.equal(calls, 1)
})

test('failed audit filters clear old results and expose a retryable error', async () => {
  const state = {
    kind: { value: 'operation' }, kinds: { value: ['operation'] }, loadState: { version: 0 },
    loading: {}, loadError: {}, rows: { value: [{ target: 'previous-filter' }] },
    dates: { value: [] }, pager: { current: 1, pageSize: 20, total: 1 }, filters: {},
    dateFilter: value => value, t: key => key,
    iamList: async () => { throw { response: { data: { detail: 'Invalid time range' } } } },
  }
  await (await viewFunction('SystemAudit', 'load', state))()
  assert.deepEqual(state.rows.value, [])
  assert.equal(state.pager.total, 0)
  assert.equal(state.loadError.value, 'Invalid time range')
  assert.equal(state.loading.value, false)
  state.iamList = async () => ({ items: [{ target: 'current-filter' }], total: 1 })
  await (await viewFunction('SystemAudit', 'load', state))()
  assert.equal(state.loadError.value, '')
  assert.equal(state.rows.value[0].target, 'current-filter')
})

test('audit filters debounce typing, apply selections immediately, and reject stale responses', async context => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  const file = await readFile(new URL('../src/views/SystemAudit.vue', import.meta.url), 'utf8')
  const script = parse(file).descriptor.scriptSetup.content.replace(/^import .*$/gm, '')
  const requests = []
  const route = reactive({ query: { tab: 'operation' }, hash: '' })
  const scope = effectScope()
  let dispose
  const deps = { computed, ref, reactive, watch, nextTick, onMounted: () => {}, onUnmounted: fn => { dispose = fn },
    useRoute: () => route, useRouter: () => ({ replace: value => { Object.assign(route, value) } }),
    can: () => true, useI18n: () => ({ t: key => key, te: () => false, tm: () => ({}) }),
    iamList: (path, query) => new Promise(resolve => requests.push({ path, query, resolve })),
    message: { error: assert.fail }, formatDateTime: String,
  }
  const h = scope.run(() => new Function(...Object.keys(deps), `${script}\nreturn { filters, kind, pager, rows, reset }`)(...Object.values(deps)))
  try {
    assert.equal(h.kind.value, 'operation')
    h.pager.current = 3
    h.filters.q = 'old'
    await nextTick()
    context.mock.timers.tick(300)
    assert.equal(requests.length, 1)
    assert.equal(requests[0].query.page, 1)
    h.filters.q = 'new'
    await nextTick()
    requests[0].resolve({ items: [{ target: 'old' }], total: 1 })
    await nextTick()
    assert.deepEqual(h.rows.value, [])
    context.mock.timers.tick(299)
    assert.equal(requests.length, 1)
    context.mock.timers.tick(1)
    assert.equal(requests[1].query.q, 'new')
    h.filters.outcome = 'failed'
    await nextTick()
    assert.equal(requests[2].query.outcome, 'failed')
    h.reset()
    await nextTick()
    assert.equal(requests[3].query.q, '')
    assert.equal(requests[3].query.outcome, undefined)
    context.mock.timers.tick(300)
    assert.equal(requests.length, 4)
    h.kind.value = 'security'
    await nextTick()
    assert.equal(route.query.tab, 'security')
    assert.equal(requests[4].path, 'audit/security')
  } finally { dispose(); scope.stop() }
})

test('agents-only reader loads without requesting unrelated account or credential data', async () => {
  const forbidden = () => { throw new Error('Unrelated API requested') }
  const context = {
    hasAccess: code => code === 'agents:view',
    listGroups: forbidden, listManagedUsers: forbidden, listModelEndpoints: forbidden,
    listSkills: forbidden,
    groups: ref([]), users: ref([]), models: ref([]), skills: ref([]),
  }
  await (await viewFunction('Agents', 'loadOptions', context))()
  for (const name of ['groups', 'users', 'models', 'skills']) assert.deepEqual(context[name].value, [])
})

test('scan reader loads tasks without requesting target or schedule management data', async () => {
  const forbidden = () => { throw new Error('Unrelated API requested') }
  const context = {
    hasAccess: code => code === 'scans:view',
    listSecurityTargets: forbidden, listScanSchedules: forbidden,
    listSecurityPolicies: async () => [], listSecurityScanApprovals: async () => [],
    listSecurityTasks: async () => [{ task_id: 'visible-task' }],
    targets: {}, policies: {}, tasks: {}, scanApprovals: {}, scheduleCount: {},
  }
  await (await viewFunction('AgentSecurityScans', 'loadCoreData', context))()
  assert.deepEqual(context.tasks.value, [{ task_id: 'visible-task' }])
  assert.equal(context.scheduleCount.value, 0)
})

test('policy-only editor saves the changed policy without submitting service settings', async () => {
  const saved = []
  const context = {
    hasAccess: code => code === 'policy:update',
    saving: { value: false }, loading: { value: false }, loaded: { value: true }, dirty: { value: true },
    llmForm: { enabled: true, model: '' }, savedState: { policy: '{}', llm: '{}', sandbox: '{}' },
    buildSnapshotPayload: () => ({ policy: { review: true }, llm: {}, sandbox: {} }),
    validateGroups: async groups => { assert.deepEqual(groups, ['policy']); return true },
    serverFieldErrors: {}, saveFailures: { value: [] },
    buildPayload: () => ({ review: true }), buildLlmPayload: () => ({ enabled: false }), buildSandboxPayload: () => ({ enabled: false }),
    updatePolicy: async body => { saved.push(body); return { policy: body } },
    updateLlmConfig: () => { throw new Error('Unrelated settings write') },
    updateSandboxConfig: () => { throw new Error('Unrelated settings write') },
    applyPolicy: () => {}, applyLlmConfig: () => {}, applySandboxConfig: () => {},
    openService: () => { throw new Error('Unrelated settings validation') },
    t: key => key, message: { success: () => {}, error: () => { throw new Error('Save failed') } },
  }
  await (await viewFunction('PolicySettings', 'handleSaveAll', context))()
  assert.deepEqual(saved, [{ review: true }])
  assert.equal(context.savedState.llm, '{}')
  assert.equal(context.saving.value, false)
})
