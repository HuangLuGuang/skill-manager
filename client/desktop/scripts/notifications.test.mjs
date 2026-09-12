import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
const delivery = source.slice(source.indexOf('const deliverDesktopNotification ='), source.indexOf('const notificationSeverity ='))

function harness(settings, send) {
  const acknowledged = []
  const state = { hidden: true, classList: { remove() {} } }
  const context = {
    notificationDeliveryAttempts: new Set(), clientSettings: settings,
    localizedNotification: () => ({ title: 'title', message: 'body' }),
    invoke: send, run: async (_command, args) => acknowledged.push(args[1]),
    $: () => state, runtimeText: String,
  }
  vm.runInNewContext(delivery + '\nglobalThis.deliver = deliverDesktopNotification', context)
  return { ...context, acknowledged, state }
}

test('temporary system notification failure remains pending and can retry', async () => {
  let calls = 0
  const h = harness({ systemNotifications: true, notificationLevel: 'info' }, async () => {
    if (++calls === 1) throw new Error('temporarily unavailable')
  })
  const item = { id: 7, severity: 'warning' }
  await h.deliver(item)
  assert.deepEqual(h.acknowledged, [])
  assert.equal(h.state.hidden, false)
  await h.deliver(item)
  assert.deepEqual(h.acknowledged, ['7'])
  assert.equal(h.state.hidden, true)
  await h.deliver(item)
  assert.equal(calls, 2)
})

test('notification preferences suppress OS delivery while acknowledging local entries', async () => {
  for (const settings of [
    { systemNotifications: false, notificationLevel: 'info' },
    { systemNotifications: true, notificationLevel: 'critical' },
  ]) {
    const h = harness(settings, () => { throw new Error('OS delivery should be suppressed') })
    await h.deliver({ id: 8, severity: 'warning' })
    assert.deepEqual(h.acknowledged, ['8'])
  }
})

test('concurrent notification refreshes share one delivery attempt', async () => {
  let finish, calls = 0
  const h = harness({ systemNotifications: true }, () => {
    calls++
    return new Promise(resolve => { finish = resolve })
  })
  const item = { id: 9, severity: 'critical' }
  const pending = h.deliver(item)
  await h.deliver(item)
  assert.equal(calls, 1)
  finish()
  await pending
  assert.deepEqual(h.acknowledged, ['9'])
})
