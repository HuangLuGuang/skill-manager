export const FOLDER_LIMITS = { files: 50000, total: 100 * 1024 ** 2, single: 100 * 1024 ** 2 }
export function inspectFolder(files, enforceLimits = true) {
  let total = 0, skipped = 0
  const entries = [], sensitive = [], paths = new Set()
  for (const file of files) {
    const path = file.webkitRelativePath
    const parts = path.split('/')
    if (parts.length < 2 || parts.some(p => !p || p === '.' || p === '..' || p.includes('\\'))) throw new Error('invalidPath')
    if (parts.includes('__MACOSX') || parts.at(-1) === '.DS_Store') { skipped++; continue }
    if (paths.has(path)) throw new Error('invalidPath')
    paths.add(path)
    total += file.size
    if (enforceLimits && (file.size > FOLDER_LIMITS.single || total > FOLDER_LIMITS.total || entries.length >= FOLDER_LIMITS.files)) throw new Error('limit')
    if (/^(\.env(?:\..*)?|id_(rsa|ed25519|ecdsa)|credentials)$/i.test(file.name) || /\.(pem|key|p12|pfx)$/i.test(file.name)) sensitive.push(path)
    entries.push({ path, file })
  }
  if (!entries.length) throw new Error('empty')
  return { entries, sensitive, skipped, total, name: entries[0].path.split('/')[0] }
}

export function folderGroups(entries) {
  const groups = new Map()
  for (const { path, file } of entries) {
    const parts = path.split('/')
    const key = parts.length > 2 ? parts.slice(0, 2).join('/') + '/' : path
    if (!groups.has(key)) groups.set(key, { path: key, size: 0, count: 0 })
    const group = groups.get(key)
    group.size += file.size
    group.count++
  }
  return [...groups.values()].sort((a, b) => b.size - a.size || a.path.localeCompare(b.path))
}
export function selectFolderEntries(entries, keys) {
  const selected = new Set(keys)
  return entries.filter(({path}) => {
    const parts = path.split('/')
    return selected.has(parts.length > 2 ? parts.slice(0, 2).join('/') + '/' : path)
  })
}
