import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, copyFileSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const details = execFileSync('rustc', ['-vV'], { encoding: 'utf8' })
const target = details.match(/^host:\s+(.+)$/m)?.[1]
if (!target) throw new Error('Unable to detect Rust host target')

const [arch, vendor, os] = target.split('-')
const goos = os === 'windows' ? 'windows' : os === 'darwin' || vendor === 'apple' ? 'darwin' : 'linux'
const goarch = arch === 'aarch64' ? 'arm64' : arch === 'x86_64' ? 'amd64' : arch
const suffix = goos === 'windows' ? '.exe' : ''
const output = resolve(root, 'client/desktop/src-tauri/bin', `agent-manager-client-${target}${suffix}`)
const version = (process.env.AGENT_MANAGER_CLIENT_VERSION || 'dev').replace(/^client-v/, '').replace(/^v/, '')
const linkerFlags = [`-X skill-manager/scanner/internal/managedclient.Version=${version}`]
if (version === 'dev') linkerFlags.push('-X main.systemDevelopment=true')
const systemResources = resolve(root, 'client/desktop/src-tauri/resources/aidr-system')
mkdirSync(systemResources, { recursive: true })
writeFileSync(resolve(systemResources, 'mode.json'), JSON.stringify({ development: version === 'dev', platform: goos }))
if (goos === 'darwin') {
  const nativeBuild = resolve(tmpdir(), `agent-manager-es-${target}`)
  execFileSync('make', [`BUILD=${nativeBuild}`, `${nativeBuild}/aidr-enforcer`], { cwd: resolve(root, 'client/macos-enforcer'), stdio: 'inherit' })
  const native = resolve(systemResources, 'aidr-enforcer')
  copyFileSync(resolve(nativeBuild, 'aidr-enforcer'), native)
  if (version !== 'dev' && process.env.AGENT_MANAGER_MACOS_SIGNING_MODE === 'developer-id') {
    if (!process.env.APPLE_SIGNING_IDENTITY || process.env.APPLE_SIGNING_IDENTITY === '-') throw new Error('System collection release requires an installed Developer ID signing identity and Apple ES entitlement')
    execFileSync('codesign', ['--force', '--options', 'runtime', '--timestamp', '--sign', process.env.APPLE_SIGNING_IDENTITY,
      '--entitlements', resolve(root, 'experiments/macos-es-poc/entitlements.plist'), native], { stdio: 'inherit' })
  }
  linkerFlags.push(`-X main.systemNativeDigest=${createHash('sha256').update(readFileSync(native)).digest('hex')}`)
}
if (goos === 'windows') linkerFlags.unshift('-H=windowsgui')
mkdirSync(dirname(output), { recursive: true })
const bundled = {}
for (const agent of ['claude', 'codex']) {
  for (const relative of [`.${agent}-plugin/plugin.json`, 'hooks/hooks.json', 'scripts/bridge.sh']) {
    const targetFile = resolve(root, 'client/desktop/src-tauri/resources/aidr-plugins', `aidr-${agent}`, relative)
    mkdirSync(dirname(targetFile), { recursive: true })
    const sourceFile = resolve(root, 'client/aidr-plugins', `aidr-${agent}`, relative)
    copyFileSync(sourceFile, targetFile)
    bundled[`aidr-${agent}/${relative}`] = readFileSync(sourceFile, 'utf8')
  }
}
const sortedBundle = Object.fromEntries(Object.entries(bundled).sort(([a], [b]) => a.localeCompare(b, 'en')))
writeFileSync(resolve(root, 'scanner/internal/aidr/hooks/bundle.json'), JSON.stringify(sortedBundle, null, 2) + '\n')
execFileSync('go', ['build', '-ldflags', linkerFlags.join(' '), '-o', output, './cmd/agent-manager-client'], {
  cwd: resolve(root, 'scanner'),
  env: {
    ...process.env,
    CGO_ENABLED: '0',
    GOCACHE: process.env.GOCACHE || resolve(tmpdir(), 'agent-manager-client-go-cache'),
    GOOS: goos,
    GOARCH: goarch,
  },
  stdio: 'inherit',
})
console.log(`prepared Agent Manager Client ${version} sidecar for ${target}`)
