import fs from 'node:fs'
import path from 'node:path'

const [platformKey, versionArg, outputDir = 'release-output'] = process.argv.slice(2)
if (!platformKey) throw new Error('platform key is required')
const version = (versionArg || process.env.AGENT_MANAGER_CLIENT_VERSION || '').replace(/^client-v/, '').replace(/^v/, '')
if (!/^\d{2}\.\d{2}\.\d{2}$/.test(version)) throw new Error('version must use YY.MM.DD')

const updaterExtensions = platformKey.startsWith('darwin-')
  ? ['.app.tar.gz']
  : platformKey.startsWith('windows-')
    ? ['.nsis.zip', '.msi.zip']
    : ['.AppImage', '.AppImage.tar.gz']

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

const signaturePath = signatures
  .filter(candidate => {
    const artifact = candidate.slice(0, -4)
    return updaterExtensions.some(extension => artifact.endsWith(extension)) && fs.existsSync(artifact)
  })
  .sort((left, right) => fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs)[0]
if (!signaturePath) throw new Error(`no updater artifact found under ${bundleRoot}`)

const source = signaturePath.slice(0, -4)
const updaterExtension = updaterExtensions.find(extension => source.endsWith(extension))
if (!updaterExtension) throw new Error(`unsupported updater artifact: ${source}`)

const targetDir = path.resolve(outputDir)
fs.mkdirSync(targetDir, { recursive: true })
const filename = `agent-manager-client-${version}-${platformKey}${updaterExtension}`
fs.copyFileSync(source, path.join(targetDir, filename))
const installerExtension = platformKey.startsWith('darwin-') ? '.dmg' : platformKey.startsWith('windows-') ? '.exe' : '.AppImage'
const installers = []
const findInstallers = directory => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) findInstallers(fullPath)
    else if (entry.name.endsWith(installerExtension)) installers.push(fullPath)
  }
}
findInstallers(bundleRoot)
installers.sort((left, right) => fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs)
if (!installers.length) throw new Error(`no ${installerExtension} installer found under ${bundleRoot}`)
const installerFile = `agent-manager-client-${version}-${platformKey}${installerExtension}`
fs.copyFileSync(installers[0], path.join(targetDir, installerFile))
const signature = fs.readFileSync(signaturePath, 'utf8').trim()
fs.writeFileSync(path.join(targetDir, `${platformKey}.json`), JSON.stringify({
  platform: platformKey,
  file: filename,
  installer: installerFile,
  signature,
}, null, 2))
console.log(`release artifacts collected: ${installerFile}, ${filename}`)
