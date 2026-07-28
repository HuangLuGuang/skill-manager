import { execFileSync } from 'node:child_process'

import { parseReleaseVersion } from './release-version.mjs'

const platform = process.argv[2]
const bundles = { mac: 'app,dmg', windows: 'nsis', linux: 'appimage' }[platform]
if (!bundles) throw new Error('usage: build-release <mac|windows|linux>')

const env = { ...process.env }
const { displayVersion } = parseReleaseVersion(env.AGENT_MANAGER_CLIENT_VERSION)
env.AGENT_MANAGER_CLIENT_VERSION = displayVersion
env.TAURI_UPDATER_PUBLIC_KEY ||= env.AGENT_MANAGER_UPDATER_PUBLIC_KEY
env.TAURI_SIGNING_PRIVATE_KEY ||= env.AGENT_MANAGER_UPDATER_PRIVATE_KEY
env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD ||= env.AGENT_MANAGER_UPDATER_PRIVATE_KEY_PASSWORD

if (platform === 'mac') {
  const signingMode = env.AGENT_MANAGER_MACOS_SIGNING_MODE || 'adhoc'
  if (!['adhoc', 'developer-id'].includes(signingMode)) {
    throw new Error(`unsupported AGENT_MANAGER_MACOS_SIGNING_MODE: ${signingMode}`)
  }
  if (signingMode === 'adhoc') {
    for (const name of [
      'APPLE_CERTIFICATE',
      'APPLE_CERTIFICATE_PASSWORD',
      'APPLE_ID',
      'APPLE_PASSWORD',
      'APPLE_TEAM_ID',
      'APPLE_API_ISSUER',
      'APPLE_API_KEY',
      'APPLE_API_KEY_PATH',
    ]) {
      delete env[name]
    }
    env.APPLE_SIGNING_IDENTITY = '-'
  } else {
    const required = ['APPLE_CERTIFICATE', 'APPLE_CERTIFICATE_PASSWORD', 'APPLE_ID', 'APPLE_PASSWORD', 'APPLE_TEAM_ID']
    const missing = required.filter((name) => !env[name])
    if (missing.length) {
      throw new Error(`missing Apple release credentials: ${missing.join(', ')}`)
    }
  }
}

execFileSync(process.execPath, ['scripts/prepare-sidecar.mjs'], { env, stdio: 'inherit' })
execFileSync(process.execPath, ['scripts/prepare-release-config.mjs'], { env, stdio: 'inherit' })
execFileSync(process.execPath, ['node_modules/@tauri-apps/cli/tauri.js', 'build', '--config', 'src-tauri/tauri.release.conf.json', '--bundles', bundles], {
  env: { ...env, AGENT_MANAGER_RELEASE_VERSION: displayVersion },
  stdio: 'inherit',
})
