import assert from 'node:assert/strict'
import test from 'node:test'
import { reviewTextLength, REVIEW_TEXT_LIMIT } from '../web/src/utils/reviewText.js'

test('review text counts Unicode characters, spaces and newlines without truncation', () => {
  assert.equal(REVIEW_TEXT_LIMIT, 1000)
  for (const char of ['中', 'a', '😀', ' ', '\n']) {
    assert.equal(reviewTextLength(char.repeat(999)), 999)
    assert.equal(reviewTextLength(char.repeat(1000)), 1000)
    assert.equal(reviewTextLength(char.repeat(1001)), 1001)
  }
  assert.equal(reviewTextLength(''), 0)
})


test('character counts match the limit calculation for mixed input', () => {
  assert.equal(reviewTextLength(''), 0)
  assert.equal(reviewTextLength('中a😀 \n'), 5)
  for (const count of [999, 1000, 1005]) {
    const value = '😀'.repeat(count)
    assert.equal(reviewTextLength(value), count)
  }
  assert.equal(reviewTextLength('a'.repeat(1005)) - REVIEW_TEXT_LIMIT, 5)
})
