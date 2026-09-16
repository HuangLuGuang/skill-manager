import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import test from 'node:test'

test('retains the newest client releases and ignores unrelated entries', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'client-release-prune-'))
  const versions = [
    'client-26.07.28.1',
    'client-26.07.29.1',
    'client-26.07.30.1',
    'client-26.07.31.1',
    'client-26.08.01.1',
    'client-26.08.02.1',
  ]
  for (const version of versions) fs.mkdirSync(path.join(directory, version))
  fs.mkdirSync(path.join(directory, 'client-not-a-version'))
  fs.symlinkSync('client-26.08.02.1', path.join(directory, 'client-latest'))

  execFileSync(
    process.execPath,
    [path.resolve('scripts/prune-client-releases.mjs'), directory, '5'],
    { cwd: path.resolve('.'), encoding: 'utf8' },
  )

  assert.equal(fs.existsSync(path.join(directory, 'client-26.07.28.1')), false)
  assert.equal(fs.existsSync(path.join(directory, 'client-26.07.29.1')), true)
  assert.equal(fs.existsSync(path.join(directory, 'client-26.08.02.1')), true)
  assert.equal(fs.existsSync(path.join(directory, 'client-not-a-version')), true)
  assert.equal(fs.lstatSync(path.join(directory, 'client-latest')).isSymbolicLink(), true)
})
