import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import dayjs from '../web/node_modules/dayjs/dayjs.min.js'

const source = readFileSync(new URL('../web/src/views/McpApprovals.vue', import.meta.url), 'utf8')
// 直接验证页面传给列表接口的时间参数，不挂载 UI 组件。
const fields = source.match(/^      created_(?:from|to):.*$/gm)
assert.equal(fields?.length, 2)
const serializeRange = new Function('timeRange', `return ({${fields.join('\n')}})`)

for (const [startMs, endMs] of [[626, 968], [0, 0], [999, 1]]) {
  test(`request boundaries match displayed seconds: ${startMs}/${endMs}`, () => {
    const range = [
      dayjs('2026-10-23T00:00:00').millisecond(startMs),
      dayjs('2026-10-23T23:00:00').millisecond(endMs),
    ]
    assert.deepEqual(serializeRange(range), {
      created_from: '2026-10-23T00:00:00+08:00',
      created_to: '2026-10-23T23:00:00+08:00',
    })
  })
}

test('same visible second has identical inclusive boundaries', () => {
  const range = [
    dayjs('2026-10-23T00:00:00.999'), dayjs('2026-10-23T00:00:00.001'),
  ]
  const result = serializeRange(range)
  assert.equal(result.created_from, '2026-10-23T00:00:00+08:00')
  assert.equal(result.created_to, result.created_from)
})

test('cleared and incomplete ranges omit missing boundaries', () => {
  assert.deepEqual(serializeRange([]), { created_from: undefined, created_to: undefined })
  assert.deepEqual(serializeRange([dayjs('2026-10-23T00:00:00.626')]), {
    created_from: '2026-10-23T00:00:00+08:00', created_to: undefined,
  })
})
