import { execFileSync } from 'node:child_process'

const platform = process.argv[2]
const bundles = { mac: 'app,dmg', windows: 'nsis', linux: 'appimage' }[platform]
if (!bundles) throw new Error('usage: build-release <mac|windows|linux>')

const env = { ...process.env }
const displayVersion = (env.AGENT_MANAGER_CLIENT_VERSION || '').replace(/^client-v/, '').replace(/^v/, '')
env.AGENT_MANAGER_CLIENT_VERSION = displayVersion
env.TAURI_UPDATER_PUBLIC_KEY ||= env.AGENT_MANAGER_UPDATER_PUBLIC_KEY
env.TAURI_SIGNING_PRIVATE_KEY ||= env.AGENT_MANAGER_UPDATER_PRIVATE_KEY
env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD ||= env.AGENT_MANAGER_UPDATER_PRIVATE_KEY_PASSWORD
execFileSync('npm', ['run', 'prepare'], { env, stdio: 'inherit' })
execFileSync('node', ['scripts/prepare-release-config.mjs'], { env, stdio: 'inherit' })
execFileSync('npx', ['tauri', 'build', '--config', 'src-tauri/tauri.release.conf.json', '--bundles', bundles], {
  env: { ...env, AGENT_MANAGER_RELEASE_VERSION: displayVersion },
  stdio: 'inherit',
})
