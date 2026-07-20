import fs from 'node:fs'
import path from 'node:path'

const publicKey = (process.env.TAURI_UPDATER_PUBLIC_KEY || '').trim()
if (!publicKey) {
  throw new Error('TAURI_UPDATER_PUBLIC_KEY is required for a release build')
}

const output = path.resolve('src-tauri/tauri.release.conf.json')
fs.writeFileSync(output, JSON.stringify({
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
