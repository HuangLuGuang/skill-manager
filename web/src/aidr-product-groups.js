// Presentation groups only; adapter IDs remain the policy and event identities.
const qoderEntries = new Set(['qoder-cli', 'qoder-hooks', 'qoder-ide', 'qoder-work'])
export const productGroupId = id => qoderEntries.has(id) ? 'qoder' : id

export function groupProductEntries(entries) {
  const groups = new Map()
  for (const entry of entries) {
    const id = productGroupId(entry.id)
    if (!groups.has(id)) groups.set(id, { id, name: id === 'qoder' ? 'Qoder' : entry.name, entries: [] })
    groups.get(id).entries.push(entry)
  }
  return [...groups.values()]
}
