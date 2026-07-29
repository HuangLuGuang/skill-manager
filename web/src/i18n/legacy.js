import { enPhrases } from './phrases.js'

const hashText = (value) => {
  let hash = 0x811c9dc5
  for (const character of String(value)) {
    hash ^= character.codePointAt(0)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(36)
}

export const legacyKey = source => `legacy.${hashText(source)}`

export const legacyMessages = Object.entries(enPhrases).reduce(
  (messages, [source, english]) => {
    const key = hashText(source)
    if (messages['zh-CN'][key] && messages['zh-CN'][key] !== source) {
      throw new Error(`Legacy i18n key collision for ${source}`)
    }
    messages['zh-CN'][key] = source
    messages['en-US'][key] = english
    return messages
  },
  { 'zh-CN': {}, 'en-US': {} },
)
