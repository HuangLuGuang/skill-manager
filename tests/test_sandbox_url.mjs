import test from 'node:test'
import assert from 'node:assert/strict'
import { sandboxUrlError } from '../web/src/utils/sandboxUrl.js'

test('accepts local hosts, IPs, paths and the exact length boundary', () => {
  for (const value of ['http://127.0.0.1:8194', 'http://sandbox:8194', 'https://example.com/base', 'http://[::1]:8194', 'http://localhost:8194/', 'http://a/' + 'x'.repeat(2039)]) {
    assert.equal(sandboxUrlError(value), null, value)
  }
})

test('rejects malformed, unsupported and non-base addresses', () => {
  for (const value of ['example.com', 'ftp://example.com', 'http://', 'http:///path', 'http://127.0.0.1:8194http://127.0.0.1:8194', 'http://localhost:65536', 'http://localhost:0', 'http://host/with space', 'http://host/?q=1', 'http://host/#section', 'http://host\\path']) {
    assert.equal(sandboxUrlError(value), 'url_invalid', value)
  }
})

test('rejects overlong and required empty URLs, permits empty Docker address', () => {
  assert.equal(sandboxUrlError('http://a/' + 'x'.repeat(2040)), 'url_too_long')
  assert.equal(sandboxUrlError(null), 'url_required')
  assert.equal(sandboxUrlError('', 'docker'), null)
})

test('Docker ignores retained remote configuration; remote mode validates it again', () => {
  for (const value of [null, "", "invalid", "http://a/" + "x".repeat(2040)]) {
    assert.equal(sandboxUrlError(value, "docker"), null)
    assert.notEqual(sandboxUrlError(value, "remote"), null)
  }
})
