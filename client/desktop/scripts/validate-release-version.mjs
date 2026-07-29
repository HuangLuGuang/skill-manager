import { parseReleaseVersion } from './release-version.mjs'

const releaseVersion = process.argv[2] || process.env.GITHUB_REF_NAME
if (!releaseVersion) {
  throw new Error('缺少客户端版本，请传入版本参数或设置 GITHUB_REF_NAME')
}

const { displayVersion, packageVersion } = parseReleaseVersion(releaseVersion)
console.log(`客户端显示版本 ${displayVersion}，内部更新版本 ${packageVersion}`)
