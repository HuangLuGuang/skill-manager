import fs from 'node:fs'
import path from 'node:path'

const [platformKey, outputDir = 'release-output'] = process.argv.slice(2)
if (!platformKey) throw new Error('platform key is required')

const bundleRoot = path.resolve('src-tauri/target/release/bundle')
const signatures = []
const walk = directory => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) walk(fullPath)
    else if (entry.name.endsWith('.sig')) signatures.push(fullPath)
  }
}
walk(bundleRoot)

const signaturePath = signatures.find(candidate => fs.existsSync(candidate.slice(0, -4)))
if (!signaturePath) throw new Error(`no updater artifact found under ${bundleRoot}`)

const source = signaturePath.slice(0, -4)
const match = path.basename(source).match(/(\.app\.tar\.gz|\.AppImage\.tar\.gz|\.nsis\.zip|\.msi\.zip)$/)
if (!match) throw new Error(`unsupported updater artifact: ${source}`)

const targetDir = path.resolve(outputDir)
fs.mkdirSync(targetDir, { recursive: true })
const filename = `agent-manager-client-${platformKey}${match[1]}`
fs.copyFileSync(source, path.join(targetDir, filename))
const signature = fs.readFileSync(signaturePath, 'utf8').trim()
fs.writeFileSync(path.join(targetDir, `${platformKey}.json`), JSON.stringify({
  platform: platformKey,
  file: filename,
  signature,
}, null, 2))
console.log(`updater artifact collected: ${filename}`)
