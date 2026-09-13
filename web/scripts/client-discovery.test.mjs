import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import axios from 'axios'

const apiSource = fs.readFileSync(new URL('../src/api/index.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '')
  .replace(/export default api;?/g, '')
  .replace(/export const /g, 'const ')
const componentSource = fs.readFileSync(new URL('../src/components/ClientDiscoveryConfig.vue', import.meta.url), 'utf8')
  .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
const catalog = { version: 'catalog-1', agents: [{ agent_type: 'qoder', name: 'Qoder', enabled: true, systems: ['darwin'], skill_roots: ['~/.qoder/skills'] }] }
function fixture(fail = false) {
  const requests = []
  // Run the production API interceptors against an Axios HTTP adapter fixture.
  const apiContext = vm.createContext({ axios, localStorage: { getItem: () => null }, getCurrentLocale: () => 'en-US' })
  vm.runInContext(apiSource + '\nglobalThis.bridge = {api, getClientDiscoveryConfig, updateClientDiscoveryConfig}', apiContext)
  apiContext.bridge.api.defaults.adapter = async config => {
    requests.push(config)
    if (fail) throw new Error('network unavailable')
    return { data: catalog, status: 200, statusText: 'OK', headers: {}, config }
  }
  let openChanged
  const emitted = []
  const context = vm.createContext({
    ...apiContext.bridge,
    ref: value => ({ value }), computed: getter => ({ get value() { return getter() } }), watch: (_source, callback) => { openChanged = callback },
    defineProps: () => ({ open: false }), defineEmits: () => (...args) => emitted.push(args),
    useI18n: () => ({ t: key => key }), message: { error() {}, success() {} },
  })
  vm.runInContext(componentSource + '\nglobalThis.form = {agents, loading, error, save, search, filteredAgents, add}', context)
  return { form: context.form, open: () => openChanged(true), requests, emitted }
}

test('discovery dialog loads the production API payload and saves the loaded version', async () => {
  const { form, open, requests, emitted } = fixture()
  await open()
  assert.equal(form.error.value, '')
  assert.equal(form.loading.value, false)
  assert.equal(form.agents.value[0].rootsText, '~/.qoder/skills')
  await form.save()
  assert.equal(requests[0].url, '/v1/clients/discovery-config')
  assert.equal(requests[1].method, 'put')
  assert.deepEqual(JSON.parse(requests[1].data), { expected_version: catalog.version, agents: catalog.agents })
  assert.deepEqual(emitted, [['update:open', false]])
})

test('failed discovery request shows an error and prevents saving empty configuration', async () => {
  const { form, open, requests } = fixture(true)
  await open()
  assert.equal(form.error.value, 'clientDiscovery.loadFailed')
  assert.equal(form.loading.value, false)
  await form.save()
  assert.equal(requests.length, 1)
})

test('search filters by name and identifier while saving all edited Agents', async () => {
  const { form, open, requests } = fixture()
  await open()
  form.agents.value.push({ agent_type: 'qoder-cn', name: '中文名称', enabled: true, systems: ['darwin'], rootsText: '.qoder-c/skills' })
  form.search.value = ' QODER-CN '
  assert.equal(form.filteredAgents.value.length, 1)
  assert.equal(form.filteredAgents.value[0].index, 1)
  form.filteredAgents.value[0].agent.rootsText = '.qoder-cn/skills'
  form.search.value = '中文'
  assert.equal(form.filteredAgents.value.length, 1)
  form.search.value = 'missing'
  assert.equal(form.filteredAgents.value.length, 0)
  await form.save()
  const saved = JSON.parse(requests[1].data).agents
  assert.equal(saved.length, 2)
  assert.equal(saved[1].skill_roots[0], '.qoder-cn/skills')
  form.add()
  assert.equal(form.search.value, '')
  assert.equal(form.filteredAgents.value.length, 3)
  form.search.value = 'old search'
  await open()
  assert.equal(form.search.value, '')
})
