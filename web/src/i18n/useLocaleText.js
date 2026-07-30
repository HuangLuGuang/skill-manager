import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { legacyKey } from './legacy.js'

export const useLocaleText = () => {
  const { locale, t } = useI18n()
  const isEnglish = computed(() => locale.value === 'en-US')
  const text = (zh, en) => (isEnglish.value ? en : zh)
  const phrase = value => t(String(value).startsWith('legacy.') ? value : legacyKey(value))

  return { locale, isEnglish, text, phrase, t }
}
