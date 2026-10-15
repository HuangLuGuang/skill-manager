<template>
  <div class="license-page">
    <header><div><h1>{{ t('license.title') }}</h1><p>{{ t('license.intro') }}</p></div><a-button :loading="loading" @click="load">{{ t('license.refresh') }}</a-button></header>
    <a-alert v-if="loadError" type="error" show-icon :message="t('license.unavailable')" />
    <a-alert type="info" show-icon :message="t('license.expiry')" />
    <a-spin :spinning="loading">
      <a-card v-if="status" :title="t('license.current')">
        <a-descriptions bordered :column="{ xs: 1, sm: 1, md: 2 }">
          <a-descriptions-item :label="t('license.state')"><a-tag :color="status.state === 'valid' ? 'green' : 'orange'">{{ t(`license.states.${status.state}`) }}</a-tag></a-descriptions-item>
          <a-descriptions-item :label="t('license.deployment')"><code>{{ status.deployment_id }}</code></a-descriptions-item>
          <a-descriptions-item :label="t('license.customerName')">{{ status.current?.customer_name || status.customer_name || '—' }}</a-descriptions-item>
          <a-descriptions-item :label="t('license.customerId')">{{ status.customer_id || '—' }}</a-descriptions-item>
          <a-descriptions-item :label="t('license.start')">{{ date(status.current?.not_before) }}</a-descriptions-item>
          <a-descriptions-item :label="t('license.end')">{{ date(status.current?.expires_at) }}</a-descriptions-item>
          <a-descriptions-item :label="t('license.clients')">{{ status.client_limit == null ? `${status.registered_clients} / ${t('license.noLimit')}` : t('license.quota', {used: status.registered_clients, limit: status.client_limit}) }}</a-descriptions-item>
          <a-descriptions-item :label="t('license.revision')">{{ status.current?.revision || '—' }}</a-descriptions-item>
        </a-descriptions>
        <p class="hint">{{ t('license.timezone') }} {{ t('license.seatsHelp') }}</p>
        <a-alert v-if="status.over_limit" type="warning" show-icon :message="t('license.overLimit')" />
        <div class="module-list"><div v-for="feature in features" :key="feature"><span>{{ t(`license.feature.${feature}`) }}</span><a-tag :color="status.current?.features.includes(feature) ? 'blue' : undefined">{{ t(status.current?.features.includes(feature) ? 'license.enabled' : 'license.disabled') }}</a-tag></div></div>
      </a-card>
      <div v-if="can('license:update')" class="forms">
        <a-card :title="t('license.request')"><p class="hint">{{ t('license.requestHelp') }}</p><a-form :model="{ customerId, customerName }" layout="vertical" @finish="exportRequest">
          <a-form-item :label="t('license.customerId')" html-for="license-customer-id"><a-input id="license-customer-id" v-model:value="customerId" :disabled="!!status?.highest_revision" /></a-form-item>
          <a-form-item :label="t('license.customerName')" html-for="license-customer-name"><a-input id="license-customer-name" v-model:value="customerName" /></a-form-item>
          <a-alert v-if="requestError" type="error" :message="t('license.requestRequired')" />
          <a-button html-type="submit" :loading="requesting" :disabled="requesting">{{ t('license.request') }}</a-button>
        </a-form></a-card>
        <a-card :title="t('license.importTitle')"><p class="hint">{{ t('license.importHelp') }}</p>
          <div class="file-label"><input ref="fileInput" type="file" hidden accept=".license,.json,application/json" :disabled="importing" @change="chooseFile" /><a-button :disabled="importing" @click="fileInput.click()">{{ t('license.choose') }}</a-button></div>
          <p v-if="fileName" class="filename">{{ fileName }}</p>
          <a-alert v-if="fileError" type="error" :message="t(`license.${fileError}`)" />
          <a-alert v-if="importFailure" type="error" show-icon :message="localizeApiError(importFailure, locale)" />
          <a-button type="primary" :loading="importing" :disabled="importing || !fileContent" @click="importFile">{{ t('license.import') }}</a-button>
        </a-card>
      </div>
      <a-card v-if="status?.pending.length" :title="t('license.pending')"><p class="hint">{{ t('license.pendingHelp') }}</p><div v-for="item in status.pending" :key="item.license_id" class="pending"><strong>{{ t('license.revision') }} {{ item.revision }}</strong><span>{{ date(item.not_before) }} → {{ date(item.expires_at) }}</span><span>{{ t('license.quota', {used: status.registered_clients, limit:item.limits.clients}) }}</span></div></a-card>
      <a-card :title="t('license.history')"><a-table :data-source="status?.history || []" :columns="columns" row-key="license_id" :scroll="{ x: 1050 }" :pagination="{ pageSize: 10 }"><template #bodyCell="{column, record}"><span v-if="column.key === 'validity'">{{ date(record.not_before) }} → {{ date(record.expires_at) }}</span><span v-else-if="column.key === 'imported_at'">{{ date(record.imported_at * 1000) }}</span></template></a-table></a-card>
    </a-spin>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { getLicenseStatus, exportLicenseRequest, importLicense } from '../api'
import { can } from '../access'
import { localizeApiError } from '../i18n/errors'
const { t, locale } = useI18n()
const features = ['skill_governance', 'security_scanning', 'aidr', 'mcp_gateway', 'model_gateway']
const status = ref(null), loading = ref(false), loadError = ref(false)
const customerId = ref(''), customerName = ref(''), requesting = ref(false), requestError = ref(false)
const fileName = ref(''), fileContent = ref(''), importing = ref(false), fileError = ref('')
const fileInput = ref(null)
const importFailure = ref(null)
function apiFailure(error) {
  return { code: error.apiErrorCode, params: error.apiErrorParams, message: error.response?.data?.detail || error.message }
}
let fileRevision = 0
const columns = computed(() => ['revision', 'license_id', 'validity', 'imported_at', 'imported_by', 'key_id'].map((key, i) => ({key, dataIndex:key, title:t(`license.${['revision','licenseId','validity','importedAt','actor','key'][i]}`)})))
function date(value) { return value == null ? '—' : new Intl.DateTimeFormat(locale.value, {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(value)) }
async function load() { if (loading.value) return; loading.value = true; loadError.value = false; try { status.value = await getLicenseStatus(); if (!customerId.value) customerId.value = status.value.customer_id; if (!customerName.value) customerName.value = status.value.customer_name } catch { loadError.value = true } finally { loading.value = false } }
function download(blob, name) { const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
async function exportRequest() {
  if (requesting.value) return
  requestError.value = !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(customerId.value) || !customerName.value.trim() || [...customerName.value].length > 200 || /[\u0000-\u001f]/.test(customerName.value)
  if (requestError.value) return
  requesting.value = true
  try { const result = await exportLicenseRequest({customer_id:customerId.value, customer_name:customerName.value}); download(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}),'customer-request.json'); message.success(t('license.requested')); await load() } catch(error) { message.error(localizeApiError(apiFailure(error), locale.value)) } finally { requesting.value = false }
}
async function chooseFile(event) { const revision = ++fileRevision; importFailure.value=null; fileError.value=''; fileContent.value=''; const file = event.target.files[0]; fileName.value=file?.name || ''; if (!file) return; if (file.size > 65536 || !/\.(license|json)$/i.test(file.name)) {fileError.value='fileInvalid';return} try {const content=await file.text(); JSON.parse(content);if(revision === fileRevision) fileContent.value=content} catch {if(revision === fileRevision)fileError.value='fileInvalid'} }
async function importFile() {
  if (importing.value) return
  if (!fileContent.value) { fileError.value='fileRequired'; return }
  importing.value=true
  importFailure.value=null
  try {
    await importLicense(fileContent.value)
    message.success(t('license.imported'))
    await load()
    window.dispatchEvent(new Event('license-changed'))
  } catch (error) {
    importFailure.value=apiFailure(error)
  } finally {
    importing.value=false
  }
}
onMounted(load)
</script>
<style scoped>
.license-page { max-width: 1400px; margin: auto; } header { display:flex; justify-content:space-between; gap:16px; margin-bottom:20px; } h1 { margin:0 0 6px; } header p,.hint { color:#64748b; } .license-page :deep(.ant-card),.license-page > .ant-alert { margin-bottom:20px; } .forms { display:grid; grid-template-columns:1fr 1fr; gap:20px; } .forms .ant-card { min-width:0; } .module-list { display:flex; flex-wrap:wrap; gap:16px 24px; margin-top:20px; } .module-list > div { display:flex; align-items:center; gap:10px; } .file-label { display:block; margin:20px 0; } input[type=file] { display:block; width:100%; margin-top:10px; } .filename,code { overflow-wrap:anywhere; } .pending { display:flex; gap:20px; flex-wrap:wrap; padding:12px 0; } .hint { margin:12px 0 18px; } .ant-alert { margin-bottom:16px; } @media(max-width:760px) { .forms { grid-template-columns:1fr; gap:0; } header { flex-wrap:wrap; } .license-page :deep(.ant-card-body) { padding:16px; } }
</style>
