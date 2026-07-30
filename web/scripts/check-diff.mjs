import assert from 'node:assert/strict'

import { parseUnifiedDiff } from '../src/utils/diff.js'

const parsed = parseUnifiedDiff(`--- v1/SKILL.md
+++ v2/SKILL.md
@@ -1,4 +1,4 @@
 unchanged
-old one
-old two
+new one
 tail
`)

const changedRows = parsed.sideRows.filter(row => row.kind === 'change')
assert.equal(changedRows.length, 2)
assert.deepEqual(
  changedRows.map(row => [row.left?.text || null, row.right?.text || null]),
  [
    ['old one', 'new one'],
    ['old two', null],
  ],
)
assert.deepEqual(
  parsed.inlineRows.filter(row => ['removed', 'added'].includes(row.kind)).map(row => row.kind),
  ['removed', 'removed', 'added'],
)
assert.deepEqual(
  parsed.inlineRows.filter(row => ['removed', 'added'].includes(row.kind)).map(row => row.text),
  ['old one', 'old two', 'new one'],
)

console.log('Diff rendering checks passed')
