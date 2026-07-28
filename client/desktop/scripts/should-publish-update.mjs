import fs from 'node:fs'

import { comparePackageVersions } from './release-version.mjs'

const [candidatePath, currentPath] = process.argv.slice(2)
if (!candidatePath || !currentPath) {
  throw new Error('usage: should-publish-update <candidate-latest.json> <current-latest.json>')
}

const readVersion = path => {
  const value = JSON.parse(fs.readFileSync(path, 'utf8'))
  if (!value.version) throw new Error(`${path} 缺少 version`)
  return String(value.version)
}

const candidateVersion = readVersion(candidatePath)
if (!fs.existsSync(currentPath)) {
  console.log('publish')
} else {
  const currentVersion = readVersion(currentPath)
  if (comparePackageVersions(candidateVersion, currentVersion) >= 0) {
    console.log('publish')
  } else {
    console.log('skip')
    console.error(`保留当前最新版 ${currentVersion}，不使用较旧构建 ${candidateVersion} 覆盖`)
  }
}
