import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { getBranding } from './api'

export const branding = reactive({ system_name_zh: '', system_name_en: '', company_name: '', logo_url: '/logo.png', has_custom_logo: false })
export function applyBranding(data) {
  Object.assign(branding, data, { logo_url: `${data.logo_url || '/logo.png'}?v=${Date.now()}` })
}
export async function loadBranding() { applyBranding(await getBranding()) }
export function useBranding() {
  const { t, locale } = useI18n()
  return {
    systemName: computed(() => branding[locale.value === 'en-US' ? 'system_name_en' : 'system_name_zh'] || t('app.name')),
    companyName: computed(() => branding.company_name),
    logoUrl: computed(() => branding.logo_url),
  }
}
