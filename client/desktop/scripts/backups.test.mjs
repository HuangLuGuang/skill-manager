import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
const block = source.slice(source.indexOf('let backupPreview = null'), source.indexOf('\nconst mergeRecoveryCopies'))
function fixture() {
  const elements = new Map(), calls = []
  const $ = id => {
    if (!elements.has(id)) elements.set(id, { value: 'backup-a', addEventListener(type, fn) { this[type] = fn } })
    return elements.get(id)
  }
  const context = { $, connection: { platform: { manual_skill_actions_allowed: true } },
    t: String, escapeHtml: String, connectionErrorText: String, log() {}, showMessageDialog() {},
    window: { confirm: () => true }, crypto: { randomUUID: () => 'request' },
    setBusy: (button, busy) => { button.disabled = busy },
    run: (...args) => new Promise((resolve, reject) => calls.push({ args, resolve, reject })) }
  vm.runInNewContext(block + '\nthis.preview = previewBackup', context)
  return { $, calls, context }
}
const items = signature => JSON.stringify([{ SkillName: 'sample', AgentType: 'codex', Target: '/skills/sample', Signature: signature, TargetSignature: 'current' }])
test('late backup preview cannot overwrite a newer selection', async () => {
  const f = fixture()
  const first = f.context.preview()
  f.$('#backup-select').value = 'backup-b'
  const second = f.context.preview()
  f.calls[1].resolve(items('b')); await second
  const html = f.$('#backup-preview').innerHTML
  f.calls[0].reject(new Error('old failure')); await first
  assert.equal(f.$('#backup-preview').innerHTML, html)
  assert.equal(f.$('#restore-backup').disabled, false)
})
test('changed content requires review again and does not request restoration', async () => {
  const f = fixture()
  const preview = f.context.preview(); f.calls[0].resolve(items('a')); await preview
  const button = f.$('#restore-backup')
  const submit = button.click({ currentTarget: button })
  await button.click({ currentTarget: button })
  assert.equal(f.calls.length, 2)
  f.calls[1].resolve(items('b'))
  await new Promise(resolve => setImmediate(resolve))
  f.calls[2].resolve(items('b')); await submit
  assert.ok(f.calls.every(call => call.args[0] === 'backups'))
  assert.equal(f.$('#backup-feedback').textContent, 'ui.backups.changed')
  assert.equal(button.disabled, false)
})
