import test from 'node:test'
import assert from 'node:assert/strict'
import { createUploadProgressReader } from '../src/utils/uploadProgress.js'

test('partial chunks and repeated download events emit progress once', () => {
  const events = []
  const reader = createUploadProgressReader(event => events.push(event))
  const progress = JSON.stringify({ type: 'progress', stage: 'identifying', completed: 1, total: 3 }) + '\n'
  reader.feed(progress.slice(0, 12))
  reader.feed(progress)
  reader.feed(progress)
  assert.equal(events.length, 1)
  const result = { count: 3, items: [] }
  assert.deepEqual(reader.finish(progress + JSON.stringify({ type: 'result', data: result }) + '\n'), result)
})

test('failed and truncated responses cannot be mistaken for completion', () => {
  for (const text of ['{"type":"error","error_code":"upload.parse_failed"}\n', '{"type":"result"']) {
    assert.throws(() => createUploadProgressReader().finish(text), error => error.apiErrorCode === 'upload.parse_failed')
  }
})
