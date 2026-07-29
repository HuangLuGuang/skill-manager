const RELEASE_VERSION_RE = /^(?:client-v|v)?(\d{2})\.(\d{2})\.(\d{2})\.([1-9]\d?)$/
const PACKAGE_VERSION_RE = /^(\d+)\.(\d+)\.(\d+)$/

export function parseReleaseVersion(value) {
  const match = String(value || '').trim().match(RELEASE_VERSION_RE)
  if (!match) {
    throw new Error('客户端版本必须使用 YY.MM.DD.N，例如 client-v26.07.28.1')
  }
  const [, yearText, monthText, dayText, sequenceText] = match
  const year = Number(yearText)
  const month = Number(monthText)
  const day = Number(dayText)
  const sequence = Number(sequenceText)
  const date = new Date(Date.UTC(2000 + year, month - 1, day))
  if (
    date.getUTCFullYear() !== 2000 + year
    || date.getUTCMonth() !== month - 1
    || date.getUTCDate() !== day
  ) {
    throw new Error(`客户端版本包含无效日期：${yearText}.${monthText}.${dayText}`)
  }
  return {
    displayVersion: `${yearText}.${monthText}.${dayText}.${sequence}`,
    packageVersion: `${year}.${month}.${day * 100 + sequence}`,
    year,
    month,
    day,
    sequence,
  }
}

export function parsePackageVersion(value) {
  const match = String(value || '').trim().match(PACKAGE_VERSION_RE)
  if (!match) throw new Error(`无效的客户端内部版本：${value || '-'}`)
  return match.slice(1).map(Number)
}

export function comparePackageVersions(left, right) {
  const leftParts = parsePackageVersion(left)
  const rightParts = parsePackageVersion(right)
  for (let index = 0; index < 3; index += 1) {
    if (leftParts[index] !== rightParts[index]) return leftParts[index] - rightParts[index]
  }
  return 0
}
