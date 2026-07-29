import { createI18n } from 'vue-i18n'

import { domainKey, domainMessages } from './domain.js'
import { legacyKey, legacyMessages } from './legacy.js'

export const LOCALE_STORAGE_KEY = 'agent-manager-locale'
export const SUPPORTED_LOCALES = ['zh-CN', 'en-US']

const detectLocale = () => {
  const saved = localStorage.getItem(LOCALE_STORAGE_KEY)
  if (SUPPORTED_LOCALES.includes(saved)) return saved
  return navigator.language?.toLowerCase().startsWith('en') ? 'en-US' : 'zh-CN'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': {
      app: {
        name: '智能体生命周期管理系统',
        subtitle: 'AI 智能体全生命周期管理平台',
      },
      language: {
        label: '语言',
        chinese: '简体中文',
        english: 'English',
      },
      domain: domainMessages['zh-CN'],
      legacy: legacyMessages['zh-CN'],
    },
    'en-US': {
      app: {
        name: 'Agent Manager',
        subtitle: 'AI agent lifecycle governance platform',
      },
      language: {
        label: 'Language',
        chinese: '简体中文',
        english: 'English',
      },
      domain: domainMessages['en-US'],
      legacy: legacyMessages['en-US'],
    },
  },
})

export const setLocale = (locale) => {
  const next = SUPPORTED_LOCALES.includes(locale) ? locale : 'zh-CN'
  i18n.global.locale.value = next
  localStorage.setItem(LOCALE_STORAGE_KEY, next)
  document.documentElement.lang = next
  document.title = i18n.global.t('app.name')
  window.dispatchEvent(new CustomEvent('agent-manager-locale-change', { detail: next }))
}

export const getCurrentLocale = () => i18n.global.locale.value
export const translateLegacy = source =>
  i18n.global.t(String(source).startsWith('legacy.') ? source : legacyKey(source))
export const translateText = (chinese, english) =>
  getCurrentLocale() === 'en-US' ? english : chinese
export const translateDomain = (category, value, fallback = value) => {
  const key = domainKey(category, value)
  return i18n.global.te(key) ? i18n.global.t(key) : fallback
}
