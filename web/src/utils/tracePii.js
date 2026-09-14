const placeholderPattern = /<[A-Z][A-Z0-9_]*:[a-z]+_[0-9a-f]{10}>/g

export function splitTracePii(text, mappings = []) {
  const terms = new Set(text.match(placeholderPattern) || [])
  for (const mapping of mappings) {
    for (const value of [mapping.token, mapping.original_value]) {
      if (typeof value === 'string' && value.length) terms.add(value)
    }
  }
  if (!terms.size) return [{ text, hit: -1 }]
  const pattern = new RegExp([...terms].sort((a, b) => b.length - a.length)
    .map(value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g')
  const parts = []
  let offset = 0
  let hit = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > offset) parts.push({ text: text.slice(offset, match.index), hit: -1 })
    parts.push({ text: match[0], hit: hit++ })
    offset = match.index + match[0].length
  }
  if (offset < text.length) parts.push({ text: text.slice(offset), hit: -1 })
  return parts
}
