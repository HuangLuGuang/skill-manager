import { test } from 'node:test'
import assert from 'node:assert/strict'
import { invalidIpEntries } from '../web/src/utils/credentialIps.js'

test('valid IPv4, IPv6, CIDR boundaries and runtime-compatible host bits', () => {
  const valid = ['127.0.0.1', '10.10.71.35', '::1', '2001:db8::1', '::ffff:192.0.2.1', '10.0.0.0/0', '10.0.0.1/32', '10.0.0.1/24', '::/0', '2001:db8::1/128', ' 10.10.71.35 ']
  assert.deepEqual(invalidIpEntries(valid), [])
  assert.deepEqual(invalidIpEntries([]), [])
})

test('invalid entries retain their original positions and values', () => {
  const invalid = ['test', 'ddd', '256.1.1.1', '1.2.3', '01.2.3.4', '10.0.0.1/33', '10.0.0.1/-1', '2001:db8::/129', '2001:::1', 'gggg::1', '10.0.0.1/abc', '', '::1%eth0', '<script>']
  for (const value of invalid) assert.deepEqual(invalidIpEntries(['127.0.0.1', value]), [{ index: 2, value }])
  assert.deepEqual(invalidIpEntries(['test', '::1', 'ddd']), [{ index: 1, value: 'test' }, { index: 3, value: 'ddd' }])
})
