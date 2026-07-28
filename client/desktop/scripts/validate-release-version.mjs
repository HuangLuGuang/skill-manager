import { parseReleaseVersion } from './release-version.mjs'

const { displayVersion, packageVersion } = parseReleaseVersion(process.argv[2])
console.log(`客户端显示版本 ${displayVersion}，内部更新版本 ${packageVersion}`)
