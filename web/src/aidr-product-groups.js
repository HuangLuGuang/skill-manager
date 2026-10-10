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

export const selectedProductGroups = entries => [...new Set(entries.map(productGroupId))]

// Keep existing entry choices; a newly selected product starts with one entry.
export function expandProductSelection(selected, current, groups, eligible = () => true) {
  const selectedIds = new Set(selected)
  const result = current.filter(id => selectedIds.has(productGroupId(id)))
  for (const id of selected) {
    if (result.some(entry => productGroupId(entry) === id)) continue
    const entry = groups.find(group => group.id === id)?.entries.find(eligible)
    if (entry) result.push(entry.id)
  }
  return [...new Set(result)]
}
