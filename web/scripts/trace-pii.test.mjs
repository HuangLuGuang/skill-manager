import assert from 'node:assert/strict'
import test from 'node:test'
import { splitTracePii } from '../src/utils/tracePii.js'

test('locates repeated originals and placeholders without changing text', () => {
  const token = '<EMAIL_ADDRESS:em_0123456789>'
  const text = `你好 a+b@example.com ${token}\na+b@example.com <script>alert(1)</script>`
  const parts = splitTracePii(text, [{ token, original_value: 'a+b@example.com' }])
  assert.equal(parts.map(part => part.text).join(''), text)
  assert.deepEqual(parts.filter(part => part.hit >= 0).map(part => part.hit), [0, 1, 2])
  assert.equal(parts.filter(part => part.hit >= 0)[0].text, 'a+b@example.com')
})

test('recognizes placeholders when historical mappings are unavailable', () => {
  const parts = splitTracePii('Contact <CN_MOBILE:mobile_0123456789>')
  assert.equal(parts.filter(part => part.hit >= 0).length, 1)
  assert.equal(splitTracePii('Nothing mapped')[0].hit, -1)
})

test('uses longest overlapping values and treats regex characters literally', () => {
  const text = 'Ann Lee [a.*] Ann'
  const parts = splitTracePii(text, [{ original_value: 'Ann' }, { original_value: 'Ann Lee' }, { original_value: '[a.*]' }])
  assert.deepEqual(parts.filter(part => part.hit >= 0).map(part => part.text), ['Ann Lee', '[a.*]', 'Ann'])
})
