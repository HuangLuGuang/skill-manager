import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

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

const tauriCli = 'node_modules/@tauri-apps/cli/tauri.js'
const releaseEnv = { ...env, AGENT_MANAGER_RELEASE_VERSION: displayVersion }

const removeDmgArtifacts = directory => {
  if (!fs.existsSync(directory)) return
  for (const entry of fs.readdirSync(directory)) {
    if (entry.endsWith('.dmg')) {
      fs.rmSync(path.join(directory, entry), { force: true })
    }
  }
}

execFileSync(process.execPath, ['scripts/prepare-sidecar.mjs'], { env, stdio: 'inherit' })
execFileSync(process.execPath, ['scripts/prepare-release-config.mjs'], { env, stdio: 'inherit' })

const buildArgs = [tauriCli, 'build', '--config', 'src-tauri/tauri.release.conf.json', '--bundles', bundles]
if (platform === 'mac') {
  buildArgs.push('--ci', '--verbose')
}

try {
  execFileSync(process.execPath, buildArgs, {
    env: releaseEnv,
    stdio: 'inherit',
  })
} catch (error) {
  if (platform !== 'mac') throw error

  const bundleRoot = path.resolve('src-tauri/target/release/bundle')
  const macosBundleDir = path.join(bundleRoot, 'macos')
  const hasApp = fs.existsSync(macosBundleDir)
    && fs.readdirSync(macosBundleDir).some(name => name.endsWith('.app'))
  if (!hasApp) throw error

  console.warn('DMG 首次生成失败，应用构建已完成；清理临时镜像后重试 DMG。')
  removeDmgArtifacts(path.join(bundleRoot, 'dmg'))
  removeDmgArtifacts(macosBundleDir)
  execFileSync('sleep', ['3'], { stdio: 'inherit' })
  execFileSync(process.execPath, [
    tauriCli,
    'bundle',
    '--config',
    'src-tauri/tauri.release.conf.json',
    '--bundles',
    'dmg',
    '--ci',
    '--verbose',
  ], {
    env: releaseEnv,
    stdio: 'inherit',
  })
}
