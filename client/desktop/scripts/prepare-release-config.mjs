import fs from 'node:fs'
import path from 'node:path'

const publicKey = (process.env.TAURI_UPDATER_PUBLIC_KEY || '').trim()
const displayVersion = (process.env.AGENT_MANAGER_CLIENT_VERSION || '').replace(/^client-v/, '').replace(/^v/, '')
if (!publicKey) {
  throw new Error('TAURI_UPDATER_PUBLIC_KEY is required for a release build')
}
if (!/^\d{2}\.\d{2}\.\d{2}$/.test(displayVersion)) {
  throw new Error('AGENT_MANAGER_CLIENT_VERSION must use YY.MM.DD, for example 26.03.15')
}
const packageVersion = displayVersion.split('.').map(Number).join('.')

const output = path.resolve('src-tauri/tauri.release.conf.json')
fs.writeFileSync(output, JSON.stringify({
  version: packageVersion,
  bundle: {
    createUpdaterArtifacts: true,
  },
  plugins: {
    updater: {
      pubkey: publicKey,
      dangerousInsecureTransportProtocol: true,
    },
  },
}, null, 2))
console.log(`release config written: ${output}`)
