import { docsArticleOrder, docsContent } from '../docs/content.js'

const HOME_KEY = '__home__'
const articleKey = slug => slug || HOME_KEY
const textValue = value => value && typeof value === 'object'
  ? String(value.label || value.value || '')
  : String(value ?? '')

const normalizeResource = resource => resource ? {
  label: String(resource.label || ''),
  value: String(resource.path || resource.hint || ''),
} : undefined

const normalizeSection = section => ({
  id: String(section.id || ''),
  title: String(section.title || ''),
  paragraphs: (section.paragraphs || []).map(String),
  bullets: (section.bullets || []).map(String),
  flow: (section.flow || []).map(item => ({ label: String(item.label || ''), value: String(item.value || '') })),
  diagram: section.diagram || undefined,
  steps: (section.steps || []).map(step => ({
    title: String(step.title || ''),
    body: String(step.body || ''),
    code: step.code ? String(step.code) : undefined,
    expected: step.expected ? String(step.expected) : undefined,
  })),
  table: section.table ? {
    columns: section.table.columns.map(String),
    rows: section.table.rows.map(row => row.map(textValue)),
  } : undefined,
  code: section.code ? String(section.code) : undefined,
  callout: section.callout ? {
    type: section.callout.type === 'warning' ? 'warning' : 'note',
    title: String(section.callout.title || ''),
    body: String(section.callout.body || ''),
  } : undefined,
  references: (section.references || []).map(reference => ({
    label: String(reference.label || ''),
    url: String(reference.url || ''),
  })),
  image: section.image ? {
    name: String(section.image.name || ''),
    alt: String(section.image.alt || ''),
    caption: String(section.image.caption || ''),
  } : undefined,
  link: normalizeResource(section.link),
  download: normalizeResource(section.download),
})

export function buildDocsPdfExportPayload({ locale, selectedArticleKeys }) {
  const content = docsContent[locale]
  const selected = new Set(selectedArticleKeys)
  const groupBySlug = new Map(content.groups.flatMap(group => group.items.map(item => [articleKey(item.slug), group.title])))
  const articles = docsArticleOrder
    .filter(slug => selected.has(articleKey(slug)))
    .map(slug => {
      const article = content.articles[slug]
      return {
        slug,
        group_title: groupBySlug.get(articleKey(slug)),
        eyebrow: String(article.eyebrow || ''),
        title: String(article.title || ''),
        summary: String(article.summary || ''),
        scenario: (article.scenario?.items || []).map(item => ({
          label: String(item.label || ''),
          value: String(item.value || ''),
        })),
        roles: (article.roles || []).map(role => ({
          label: String(role.title || ''),
          value: String(role.text || ''),
        })),
        sections: (article.sections || []).map(normalizeSection),
      }
    })
  return { locale, articles }
}

export const docsPdfFilename = (locale, date = new Date()) => {
  const stamp = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('')
  return locale === 'en-US'
    ? `Agent-Manager-help-documentation-${stamp}.pdf`
    : `Agent-Manager-帮助文档-${stamp}.pdf`
}
