import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import test from 'node:test'

import { comparePackageVersions, parseReleaseVersion } from './release-version.mjs'

test('converts a four-part display version to a sortable package version', () => {
  assert.deepEqual(parseReleaseVersion('client-v26.07.28.2'), {
    displayVersion: '26.07.28.2',
    packageVersion: '26.7.2802',
    year: 26,
    month: 7,
    day: 28,
    sequence: 2,
  })
})

test('rejects legacy, invalid-date, and zero-sequence release versions', () => {
  assert.throws(() => parseReleaseVersion('client-v26.07.28'), /YY\.MM\.DD\.N/)
  assert.throws(() => parseReleaseVersion('client-v26.02.30.1'), /无效日期/)
  assert.throws(() => parseReleaseVersion('client-v26.07.28.0'), /YY\.MM\.DD\.N/)
})

test('orders same-day and next-day package versions correctly', () => {
  assert.ok(comparePackageVersions('26.7.2802', '26.7.2801') > 0)
  assert.ok(comparePackageVersions('26.7.2901', '26.7.2899') > 0)
  assert.equal(comparePackageVersions('26.7.2802', '26.7.2802'), 0)
})

test('publish guard does not let an older completed workflow replace latest', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'client-release-version-'))
  const candidate = path.join(directory, 'candidate.json')
  const current = path.join(directory, 'current.json')
  fs.writeFileSync(candidate, JSON.stringify({ version: '26.7.2801' }))
  fs.writeFileSync(current, JSON.stringify({ version: '26.7.2802' }))
  const output = execFileSync(
    process.execPath,
    [path.resolve('scripts/should-publish-update.mjs'), candidate, current],
    { cwd: path.resolve('.'), encoding: 'utf8' },
  )
  assert.equal(output.trim(), 'skip')
})
