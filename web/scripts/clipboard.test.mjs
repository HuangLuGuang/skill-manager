import assert from 'node:assert/strict'
import test from 'node:test'

import { ClipboardCopyError, copyText, promptManualCopy } from '../src/utils/clipboard.js'

const createDocument = ({ copied = true, throws = false } = {}) => {
  const calls = []
  const previousFocus = { focus: () => calls.push('restore-focus') }
  const textarea = {
    style: {},
    setAttribute: (name, value) => calls.push(['attribute', name, value]),
    focus: () => calls.push('focus'),
    select: () => calls.push('select'),
    setSelectionRange: (start, end) => calls.push(['range', start, end]),
    remove: () => calls.push('remove'),
  }
  const document = {
    activeElement: previousFocus,
    body: { appendChild: element => calls.push(['append', element]) },
    createElement: tag => {
      calls.push(['create', tag])
      return textarea
    },
    execCommand: command => {
      calls.push(['command', command])
      if (throws) throw new Error('copy denied')
      return copied
    },
  }
  return { calls, document, textarea }
}

test('uses the asynchronous Clipboard API when it is available', async () => {
  const writes = []
  const method = await copyText('secret', {
    navigator: { clipboard: { writeText: async text => writes.push(text) } },
    document: createDocument().document,
  })

  assert.equal(method, 'clipboard')
  assert.deepEqual(writes, ['secret'])
})

test('falls back to a selected textarea when Clipboard API is unavailable', async () => {
  const { calls, document, textarea } = createDocument()
  const method = await copyText('client config', { navigator: {}, document })

  assert.equal(method, 'selection')
  assert.equal(textarea.value, 'client config')
  assert.ok(calls.some(call => Array.isArray(call) && call[0] === 'command' && call[1] === 'copy'))
  assert.deepEqual(calls.slice(-2), ['remove', 'restore-focus'])
})

test('falls back when the asynchronous Clipboard API rejects the write', async () => {
  const { document } = createDocument()
  const method = await copyText('trace', {
    navigator: { clipboard: { writeText: async () => { throw new Error('not allowed') } } },
    document,
  })

  assert.equal(method, 'selection')
})

test('throws a typed error when neither copy method succeeds', async () => {
  const { calls, document } = createDocument({ copied: false })

  await assert.rejects(
    copyText('value', { navigator: {}, document }),
    error => error instanceof ClipboardCopyError,
  )
  assert.deepEqual(calls.slice(-2), ['remove', 'restore-focus'])
})

test('opens a manual copy prompt with the original text', () => {
  const prompts = []
  const shown = promptManualCopy('amat_xxx', 'Copy manually', {
    prompt: (instruction, value) => prompts.push({ instruction, value }),
  })

  assert.equal(shown, true)
  assert.deepEqual(prompts, [{ instruction: 'Copy manually', value: 'amat_xxx' }])
})
