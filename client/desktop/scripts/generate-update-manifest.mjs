import fs from 'node:fs'
import path from 'node:path'

const [inputDir, version] = process.argv.slice(2)
if (!inputDir || !version) throw new Error('usage: generate-update-manifest <input-dir> <version>')

const platforms = {}
const walk = directory => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name)
    if (entry.isDirectory()) walk(fullPath)
    else if (entry.name.endsWith('.json') && entry.name !== 'latest.json') {
      const value = JSON.parse(fs.readFileSync(fullPath, 'utf8'))
      if (value.platform && value.file && value.signature) {
        platforms[value.platform] = { file: value.file, signature: value.signature }
      }
    }
  }
}
walk(path.resolve(inputDir))
if (!Object.keys(platforms).length) throw new Error('no platform updater metadata found')

const manifest = {
  version: version.replace(/^client-v/, '').replace(/^v/, ''),
  notes: `Agent Manager Client ${version}`,
  pub_date: new Date().toISOString(),
  platforms,
}
fs.writeFileSync(path.join(path.resolve(inputDir), 'latest.json'), JSON.stringify(manifest, null, 2))
console.log(`latest.json generated for ${Object.keys(platforms).join(', ')}`)
