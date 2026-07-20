import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
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
mkdirSync(dirname(output), { recursive: true })
execFileSync('go', ['build', '-ldflags', `-X skill-manager/scanner/internal/managedclient.Version=${version}`, '-o', output, './cmd/agent-manager-client'], {
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
