const flattenDocsText = value => {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(flattenDocsText).filter(Boolean).join(' ')
  if (value && typeof value === 'object') return Object.values(value).map(flattenDocsText).filter(Boolean).join(' ')
  return ''
}

const docsQueryTokens = query => {
  const normalized = String(query || '').toLocaleLowerCase().trim()
  const stopWords = new Set(['a', 'an', 'and', 'are', 'can', 'do', 'does', 'for', 'how', 'i', 'in', 'is', 'my', 'of', 'on', 'or', 'should', 'the', 'to', 'what', 'with'])
  const words = (normalized.match(/[a-z0-9][a-z0-9_-]+/g) || []).filter(word => !stopWords.has(word))
  const chinese = normalized.match(/[\u3400-\u9fff]+/g) || []
  const grams = chinese.flatMap(group => {
    if (group.length <= 2) return [group]
    return Array.from({ length: group.length - 1 }, (_, index) => group.slice(index, index + 2))
  })
  return [...new Set([...words, ...grams].filter(token => token.length > 1))]
}

export const rankDocsContexts = ({ content, query, currentSlug = '' }) => {
  const tokens = docsQueryTokens(query)
  const candidates = []
  for (const [slug, article] of Object.entries(content?.articles || {})) {
    for (const section of article.sections || []) {
      const sectionContent = flattenDocsText({
        article_summary: article.summary,
        paragraphs: section.paragraphs,
        bullets: section.bullets,
        steps: section.steps,
        table: section.table,
        callout: section.callout,
        code: section.code,
      }).replace(/\s+/g, ' ').trim()
      if (!sectionContent) continue
      const titleText = `${article.title} ${section.title}`.toLocaleLowerCase()
      const bodyText = sectionContent.toLocaleLowerCase()
      let score = slug === currentSlug ? 1.5 : 0
      for (const token of tokens) {
        if (titleText.includes(token)) score += 5 + Math.min(token.length, 5)
        if (bodyText.includes(token)) score += 1 + Math.min(token.length / 2, 3)
      }
      candidates.push({
        slug,
        article_title: article.title,
        section_title: section.title,
        content: sectionContent.slice(0, 4000),
        score,
      })
    }
  }
  return candidates.sort((left, right) => right.score - left.score)
}
