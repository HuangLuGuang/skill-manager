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

// 验证跳转查询参数的协调逻辑，不挂载 UI。
test('approval route fills visible search and clearing it removes URL condition', () => {
  const state = {
    route: { query: { request_id: 'approval-A', keep: 'yes' } },
    activeTab: { value: 'pending' },
    statistic: { value: 'pending' },
    filters: { q: 'old', gateway_slug: 'old', tool_name: 'old', token_name: 'old', timeRange: [1, 2] },
  }
  const queries = [], details = [], routes = []
  const block = source.slice(source.indexOf('const syncRequestedQuery ='), source.indexOf('watch(() => route.query.request_id'))
  const api = new Function(...Object.keys(state), 'router', 'applyFilters', 'openDetails', `${block}; return { openRequestedDetails, syncRequestedQuery }`)(
    ...Object.values(state), { replace: next => routes.push(next) },
    () => queries.push({ id: state.filters.q, tab: state.activeTab.value }),
    record => details.push(record.request_id),
  )
  api.openRequestedDetails()
  assert.deepEqual(queries, [{ id: 'approval-A', tab: 'all' }])
  assert.deepEqual(details, ['approval-A'])
  assert.equal(state.statistic.value, undefined)
  assert.deepEqual(state.filters, { q: 'approval-A', gateway_slug: undefined, tool_name: '', token_name: '', timeRange: [] })
  state.route.query.request_id = 'approval-B'
  api.openRequestedDetails()
  assert.equal(queries.at(-1).id, 'approval-B')
  assert.equal(details.at(-1), 'approval-B')
  state.filters.q = ''
  api.syncRequestedQuery()
  assert.deepEqual(routes.at(-1), { query: { keep: 'yes' } })
})
