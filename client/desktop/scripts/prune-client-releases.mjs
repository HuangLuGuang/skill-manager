import fs from 'node:fs'
import path from 'node:path'

import { comparePackageVersions, parseReleaseVersion } from './release-version.mjs'

const [releaseRoot, keepText = '5'] = process.argv.slice(2)
const keep = Number(keepText)
if (!releaseRoot || !Number.isInteger(keep) || keep < 1) {
  throw new Error('usage: prune-client-releases <release-root> [keep-count]')
}

const releases = fs.readdirSync(releaseRoot, { withFileTypes: true })
  .filter(entry => entry.isDirectory() && /^client-\d{2}\.\d{2}\.\d{2}\.[1-9]\d?$/.test(entry.name))
  .map(entry => {
    const name = entry.name
    const version = name.slice('client-'.length)
    const parsed = parseReleaseVersion(`client-v${version}`)
    return { name, version: parsed.packageVersion }
  })
  .sort((left, right) => comparePackageVersions(right.version, left.version) || right.name.localeCompare(left.name))

for (const release of releases.slice(keep)) {
  fs.rmSync(path.join(releaseRoot, release.name), { recursive: true, force: true })
  console.log(`Removed old client release ${release.name}`)
}

console.log(`Retained ${Math.min(keep, releases.length)} client releases`)
