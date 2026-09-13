import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
const block = source.slice(source.indexOf('let exportingDiagnostics = false'), source.indexOf("\n$('#overview-sync')"))
function fixture() {
  const elements = new Map()
  const calls = []
  const dialogs = []
  const $ = id => {
    if (!elements.has(id)) elements.set(id, { value: id.endsWith('range') ? '3' : '7', addEventListener(type, handler) { this[type] = handler } })
    return elements.get(id)
  }
  const context = {
    $, t: key => key, tf: (parts, ...values) => parts.map((part, i) => part + (values[i] ?? '')).join(''),
    runtimeText: String, showMessageDialog: (...args) => dialogs.push(args),
    setBusy: (button, busy) => { button.disabled = busy },
    run: (...args) => new Promise((resolve, reject) => calls.push({ args, resolve, reject })),
    invoke: (...args) => new Promise((resolve, reject) => calls.push({ args, resolve, reject })),
  }
  vm.runInNewContext(block + '\nthis.refresh = refreshLogSettings', context)
  return { $, calls, dialogs, context }
}
const settings = days => JSON.stringify({ retention_days: days, used_bytes: 0 })

test('a stale settings read cannot replace the newly selected retention', async () => {
  const f = fixture()
  const initial = f.context.refresh()
  const control = f.$('#settings-log-retention')
  control.value = '14'
  const saving = control.change({ currentTarget: control })
  assert.equal(control.disabled, true)
  f.calls[0].resolve(settings(7))
  await initial
  assert.equal(control.value, '14')
  f.calls[1].resolve(settings(14))
  await new Promise(resolve => setImmediate(resolve))
  f.calls[2].resolve(settings(14))
  await saving
  assert.equal(control.disabled, false)
  assert.equal(control.value, '14')
})

test('export prevents duplicate requests and releases its button after failure', async () => {
  const f = fixture()
  const button = f.$('#settings-export-diagnostics')
  const first = button.click({ currentTarget: button })
  await button.click({ currentTarget: button })
  assert.equal(f.calls.length, 1)
  assert.equal(button.disabled, true)
  f.calls[0].reject(new Error('disk full'))
  await first
  assert.equal(button.disabled, false)
  assert.equal(f.dialogs.length, 1)
  assert.match(f.dialogs[0][1], /disk full/)
})

test('desktop errors aggregate repeats and bound native logging traffic', async () => {
  const listeners = {}
  const records = []
  let flush
  const window = {
    __TAURI__: { core: { invoke: async (_, { record }) => { records.push(record) } } },
    addEventListener: (name, handler) => { listeners[name] = handler },
  }
  const diagnostics = fs.readFileSync(new URL('../src/diagnostics.js', import.meta.url), 'utf8')
  vm.runInNewContext(diagnostics, { window, setInterval: callback => { flush = callback } })
  window.clientDiagnostics.started('26.9.12.1')
  for (let i = 0; i < 100; i++) listeners.error({ message: 'repeated failure' })
  assert.equal(records.length, 2)
  assert.equal(records[1].version, '26.9.12.1')
  flush()
  assert.equal(records[2].count, 99)
  const before = records.length
  for (let i = 0; i < 1000; i++) listeners.unhandledrejection({ reason: `failure ${i}` })
  assert.equal(records.length - before, 20)
  flush()
  assert.equal(records.at(-1).count, 980)
  window.__TAURI__.core.invoke = async () => { throw new Error('logging unavailable') }
  listeners.error({ message: 'must not recurse' })
  await new Promise(resolve => setImmediate(resolve))
})
