import test from 'node:test'
import assert from 'node:assert/strict'
import { inspectFolder, folderGroups, selectFolderEntries } from '../src/utils/folderUpload.js'
const file = (path, size=1) => ({webkitRelativePath:path,name:path.split('/').at(-1),size})
test('keeps SVG and dependencies; skips only system metadata and flags credentials',()=>{
 const r=inspectFolder([file('demo/SKILL.md'),file('demo/a.svg'),file('demo/node_modules/a.js'),file('demo/.env'),file('demo/__MACOSX/a'),file('demo/.DS_Store')])
 assert.equal(r.entries.length,4); assert.equal(r.skipped,2); assert.deepEqual(r.sensitive,['demo/.env'])
})
test('rejects traversal, duplicate paths and oversized files',()=>{
 for(const files of [[file('demo/../a')],[file('demo/a'),file('demo/a')],[file('demo/a',101*1024**2)]]) assert.throws(()=>inspectFolder(files))
})

test('groups deep files into disjoint subfolders sorted by size and keeps selection exact', () => {
 const files = [file('demo/small/a.svg', 2), file('demo/large/deep/b.svg', 8), file('demo/large/c.svg', 4), file('demo/SKILL.md', 1)]
 const report = inspectFolder(files)
 const rows = folderGroups(report.entries)
 assert.deepEqual(rows.map(row => row.size), [12, 2, 1])
 assert.equal(rows[0].count, 2)
 assert.deepEqual(selectFolderEntries(report.entries, ['demo/small/', 'demo/SKILL.md']).map(entry => entry.path), ['demo/small/a.svg', 'demo/SKILL.md'])
})
test('can inspect oversized folders before enforcing limits on the selected subset', () => {
 const files = [file('demo/large/a', 150 * 1024 ** 2), file('demo/SKILL.md', 1)]
 const report = inspectFolder(files, false)
 assert.equal(folderGroups(report.entries)[0].path, 'demo/large/')
 const selected = selectFolderEntries(report.entries, ['demo/SKILL.md'])
 assert.equal(inspectFolder(selected.map(entry => entry.file)).total, 1)
})

test('accepts exactly 100 MiB original bytes and rejects one byte over across files', () => {
 const limit = 100 * 1024 ** 2
 assert.equal(inspectFolder([file('demo/a', limit - 1), file('demo/b', 1)]).total, limit)
 assert.throws(() => inspectFolder([file('demo/a', limit - 1), file('demo/b', 2)]), /limit/)
})
