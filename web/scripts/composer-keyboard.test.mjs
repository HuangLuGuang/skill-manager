import assert from 'node:assert/strict'
import test from 'node:test'

import { shouldSubmitComposerOnEnter } from '../src/utils/composerKeyboard.js'

const enterEvent = overrides => ({
  key: 'Enter',
  shiftKey: false,
  ctrlKey: false,
  altKey: false,
  metaKey: false,
  isComposing: false,
  keyCode: 13,
  ...overrides,
})

test('plain Enter submits the composer', () => {
  assert.equal(shouldSubmitComposerOnEnter(enterEvent()), true)
})

test('IME confirmation Enter does not submit the composer', () => {
  assert.equal(shouldSubmitComposerOnEnter(enterEvent({ isComposing: true })), false)
  assert.equal(shouldSubmitComposerOnEnter(enterEvent(), true), false)
  assert.equal(shouldSubmitComposerOnEnter(enterEvent({ keyCode: 229 })), false)
})

test('modified Enter and non-Enter keys do not submit the composer', () => {
  assert.equal(shouldSubmitComposerOnEnter(enterEvent({ shiftKey: true })), false)
  assert.equal(shouldSubmitComposerOnEnter(enterEvent({ ctrlKey: true })), false)
  assert.equal(shouldSubmitComposerOnEnter(enterEvent({ key: 'a', keyCode: 65 })), false)
})
