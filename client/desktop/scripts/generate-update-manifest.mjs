import fs from 'node:fs'
import path from 'node:path'

import { parseReleaseVersion } from './release-version.mjs'

const [inputDir, version, channel = 'stable'] = process.argv.slice(2)
if (!inputDir || !version || !['stable', 'preview'].includes(channel)) {
  throw new Error('usage: generate-update-manifest <input-dir> <version> [stable|preview]')
}

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

const { displayVersion, packageVersion } = parseReleaseVersion(version)
const manifest = {
  version: packageVersion,
  notes: `AI智能体全生命周期管理平台客户端 ${displayVersion}`,
  pub_date: new Date().toISOString(),
  platforms,
}
const manifestName = channel === 'preview' ? 'preview.json' : 'latest.json'
fs.writeFileSync(path.join(path.resolve(inputDir), manifestName), JSON.stringify(manifest, null, 2))
console.log(`${manifestName} generated for ${Object.keys(platforms).join(', ')}`)
