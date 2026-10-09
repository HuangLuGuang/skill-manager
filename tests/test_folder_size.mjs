import test from 'node:test'
import assert from 'node:assert/strict'
import { formatFileSize } from '../web/src/utils/fileSize.js'
import { inspectFolder, folderGroups, selectFolderEntries } from '../web/src/utils/folderUpload.js'

const format = (bytes, locale = 'zh-CN') => formatFileSize(bytes, locale, {
  byteUnit: locale === 'zh-CN' ? '字节' : 'B',
  fractionDigits: 2,
})
const file = (path, size) => ({ webkitRelativePath: path, name: path.split('/').at(-1), size })

test('small original sizes remain visible in both languages', () => {
  for (const size of [0, 1, 512, 1023]) {
    assert.equal(format(size), `${size.toLocaleString('zh-CN')} 字节`)
    assert.equal(format(size, 'en-US'), `${size.toLocaleString('en-US')} B`)
  }
  assert.equal(format(2048), '2.00 KB')
  assert.equal(format(2560, 'en-US'), '2.50 KB')
})

test('units switch at each 1024 boundary', () => {
  for (const [power, unit, previous] of [[1, 'KB', '字节'], [2, 'MB', 'KB'], [3, 'GB', 'MB'], [4, 'TB', 'GB']]) {
    const boundary = 1024 ** power
    assert.ok(format(boundary - 1).endsWith(` ${previous}`))
    assert.equal(format(boundary), `1.00 ${unit}`)
    assert.equal(format(boundary + 1), `1.00 ${unit}`)
  }
})

test('nested directory totals and selected original bytes include every file exactly once', () => {
  const report = inspectFolder([
    file('demo/scripts/a.py', 2048),
    file('demo/scripts/deep/b.py', 512),
    file('demo/scripts/empty', 0),
    file('demo/SKILL.md', 512),
  ])
  const rows = folderGroups(report.entries)
  assert.deepEqual(rows, [
    { path: 'demo/scripts/', size: 2560, count: 3 },
    { path: 'demo/SKILL.md', size: 512, count: 1 },
  ])
  assert.equal(report.total, 3072)
  assert.equal(format(report.total), '3.00 KB')
  for (const keys of [rows.map(row => row.path), ['demo/scripts/'], ['demo/SKILL.md'], []]) {
    const rowTotal = rows.filter(row => keys.includes(row.path)).reduce((sum, row) => sum + row.size, 0)
    const fileTotal = selectFolderEntries(report.entries, keys).reduce((sum, entry) => sum + entry.file.size, 0)
    assert.equal(rowTotal, fileTotal)
  }
})

test('existing shared formatter defaults keep their output', () => {
  assert.equal(formatFileSize(512, 'en-US'), '512 B')
  assert.equal(formatFileSize(2560, 'en-US'), '2.5 KB')
  assert.equal(formatFileSize(-1, 'en-US'), '-')
})
