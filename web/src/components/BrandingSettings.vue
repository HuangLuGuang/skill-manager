<template>
  <a-card :title="t('branding.title')" class="branding-settings" :loading="loading">
    <a-alert v-if="loadFailed" type="error" :message="t('branding.loadFailed')" show-icon />
    <template v-else>
      <div class="branding-preview"><img :src="logoUrl" alt="Logo" /><div><strong>{{ systemName }}</strong><p>{{ companyName }}</p></div></div>
      <a-form layout="vertical" :model="form" @finish="save">
        <div class="branding-fields">
          <a-form-item :label="t('branding.nameZh')" name="system_name_zh" :rules="[{ required: true, whitespace: true, message: t('branding.required') }]"><a-input v-model:value="form.system_name_zh" :maxlength="80" :disabled="busy || !editable" /></a-form-item>
          <a-form-item :label="t('branding.nameEn')" name="system_name_en" :rules="[{ required: true, whitespace: true, message: t('branding.required') }]"><a-input v-model:value="form.system_name_en" :maxlength="80" :disabled="busy || !editable" /></a-form-item>
          <a-form-item :label="t('branding.company')" name="company_name"><a-input v-model:value="form.company_name" :maxlength="120" :disabled="busy || !editable" /></a-form-item>
        </div>
        <a-space v-if="editable" wrap>
          <a-button type="primary" html-type="submit" :loading="busy" :disabled="busy">{{ t('branding.save') }}</a-button>
          <a-upload :show-upload-list="false" :before-upload="upload" accept="image/png,image/jpeg,image/gif,image/webp" :disabled="busy"><a-button :disabled="busy">{{ t('branding.upload') }}</a-button></a-upload>
          <a-button :disabled="busy || !branding.has_custom_logo" @click="restore">{{ t('branding.restore') }}</a-button>
        </a-space>
        <p class="branding-hint">{{ t('branding.hint') }}</p>
      </a-form>
    </template>
  </a-card>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { getBranding, saveBranding, uploadBrandLogo, resetBrandLogo } from '../api'
import { branding, applyBranding, loadBranding, useBranding } from '../branding'
const { t } = useI18n()
const { logoUrl, systemName, companyName } = useBranding()
const editable = computed(() => can('settings:update'))
const form = reactive({ system_name_zh: '', system_name_en: '', company_name: '' })
const loading = ref(true), loadFailed = ref(false), busy = ref(false)
const report = error => message.error(typeof error.response?.data?.detail === 'string' ? error.response.data.detail : t('branding.failed'))
onMounted(async () => {
  try { const data = await getBranding(); Object.keys(form).forEach(key => { form[key] = data[key] }); applyBranding(data) }
  catch { loadFailed.value = true } finally { loading.value = false }
})
async function save() {
  if (busy.value || !editable.value) return
  busy.value = true
  try { applyBranding(await saveBranding({ ...form })); message.success(t('branding.saved')) }
  catch (error) { report(error) } finally { busy.value = false }
}
async function upload(file) {
  if (busy.value || !editable.value) return false
  if (file.size > 5 * 1024 * 1024) { message.error(t('branding.tooLarge')); return false }
  busy.value = true
  try { const data = new FormData(); data.append('file', file); await uploadBrandLogo(data); await loadBranding(); message.success(t('branding.saved')) }
  catch (error) { report(error) } finally { busy.value = false }
  return false
}
async function restore() {
  if (busy.value || !editable.value) return
  busy.value = true
  try { await resetBrandLogo(); await loadBranding(); message.success(t('branding.saved')) }
  catch (error) { report(error) } finally { busy.value = false }
}
</script>
<style scoped>
.branding-settings { margin: 20px 0; }
.branding-preview { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; overflow-wrap: anywhere; }
.branding-preview img { max-width: min(160px, 40%); max-height: 56px; object-fit: contain; }
.branding-preview > div { min-width: 0; }
.branding-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 16px; }
.branding-hint { color: #64748b; margin-top: 12px; }
</style>
