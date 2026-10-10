import { marked, Renderer } from 'marked'

const allowedTags = new Set([
  'A', 'BLOCKQUOTE', 'BR', 'CODE', 'DEL', 'EM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'HR', 'LI', 'OL', 'P', 'PRE', 'STRONG', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL',
])
const removedTags = new Set(['IFRAME', 'OBJECT', 'SCRIPT', 'STYLE', 'SVG', 'MATH', 'FORM'])

const safeHref = value => {
  const href = String(value || '').trim()
  if (!href) return null
  if (href.startsWith('#') || href.startsWith('/docs')) return href
  try {
    const url = new URL(href, window.location.origin)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null
  } catch {
    return null
  }
}

const sanitizeElement = element => {
  if (removedTags.has(element.tagName)) {
    element.remove()
    return
  }
  if (!allowedTags.has(element.tagName)) {
    element.replaceWith(...element.childNodes)
    return
  }

  const href = element.tagName === 'A' ? safeHref(element.getAttribute('href')) : null
  const title = element.tagName === 'A' ? element.getAttribute('title') : null
  const languageClass = element.tagName === 'CODE'
    ? [...element.classList].find(name => /^language-[a-z0-9_+-]+$/i.test(name))
    : null
  for (const attribute of [...element.attributes]) element.removeAttribute(attribute.name)

  if (element.tagName === 'A' && href) {
    element.setAttribute('href', href)
    if (title) element.setAttribute('title', title.slice(0, 200))
    element.setAttribute('target', '_blank')
    element.setAttribute('rel', 'noopener noreferrer')
  } else if (element.tagName === 'A') {
    element.replaceWith(...element.childNodes)
  }
  if (languageClass) element.classList.add(languageClass)
}

export const renderSafeMarkdown = (value, { literalHtml = false } = {}) => {
  const renderer = literalHtml ? new Renderer() : undefined
  if (renderer) {
    const escape = value => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    renderer.html = token => escape(token.text)
    renderer.image = token => escape(token.raw)
  }
  const rawHtml = marked.parse(String(value || ''), { breaks: true, gfm: true, ...(renderer ? { renderer } : {}) })
  const documentValue = new DOMParser().parseFromString(`<body>${rawHtml}</body>`, 'text/html')
  for (const element of [...documentValue.body.querySelectorAll('*')]) sanitizeElement(element)
  return documentValue.body.innerHTML
}
