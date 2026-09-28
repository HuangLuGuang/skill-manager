import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

test('Windows release binaries do not allocate console windows', () => {
  const desktopMain = fs.readFileSync(path.join(root, 'src-tauri/src/main.rs'), 'utf8')
  assert.match(
    desktopMain,
    /^#!\[cfg_attr\(\s*all\(target_os = "windows", not\(debug_assertions\)\),\s*windows_subsystem = "windows"\s*\)\]/,
  )

  const sidecarBuild = fs.readFileSync(path.join(root, 'scripts/prepare-sidecar.mjs'), 'utf8')
  assert.match(sidecarBuild, /if \(goos === 'windows'\) linkerFlags\.unshift\('-H=windowsgui'\)/)
})
