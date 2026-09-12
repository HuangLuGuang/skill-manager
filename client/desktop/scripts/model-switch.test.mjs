import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
const implementation = source.slice(source.indexOf('let modelSwitchBusy = false'), source.indexOf('const beginModelSwitch'))

test('model switch blocks overlapping requests and releases controls after failure', async () => {
  let rejectRequest
  let calls = 0
  let rendered = 0
  const buttons = [{ disabled: false }, { disabled: false }]
  const context = vm.createContext({
    document: { querySelectorAll: () => buttons },
    run: () => { calls++; return new Promise((_, reject) => { rejectRequest = reject }) },
    setBusy: () => {}, log: () => {}, refreshConnection: async () => {},
    showMessageDialog: () => {}, runtimeText: String, t: value => value,
    connection: {}, renderModelSwitcher: () => { rendered++ },
  })
  vm.runInContext(implementation + '\nglobalThis.switchModel = executeModelSwitch', context)
  const first = context.switchModel({ agent_type: 'codex' }, 'a', buttons[0])
  await context.switchModel({ agent_type: 'codex' }, 'b', buttons[1])
  assert.equal(calls, 1)
  assert.ok(buttons.every(item => item.disabled))
  rejectRequest(new Error('fixture failure'))
  await first
  assert.equal(rendered, 1)
  const retry = context.switchModel({ agent_type: 'codex' }, 'b', buttons[1])
  assert.equal(calls, 2)
  rejectRequest(new Error('fixture failure'))
  await retry
})
