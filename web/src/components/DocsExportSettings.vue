<template>
  <a-card class="export-card">
    <template #title>
      <div class="card-heading">
        <span class="card-icon"><ExportOutlined /></span>
        <div>
          <strong>{{ t('docsExport.title') }}</strong>
          <span>{{ t('docsExport.subtitle') }}</span>
        </div>
      </div>
    </template>

    <a-tabs v-model:active-key="activeFormat">
      <a-tab-pane key="pdf" :tab="t('docsExport.pdfTab')">
        <div class="export-toolbar">
          <label>
            <span>{{ t('docsExport.language') }}</span>
            <a-select v-model:value="pdfLocale" :options="languageOptions" :disabled="pdfExporting" />
          </label>
          <label>
            <span>{{ t('docsExport.scopePreset') }}</span>
            <a-select v-model:value="pdfPreset" :options="pdfPresetOptions" :disabled="pdfExporting" @change="applyPdfPreset" />
          </label>
          <div class="selection-count">{{ t('docsExport.articleCount', { count: selectedArticleCount }) }}</div>
        </div>

        <div class="module-grid">
          <div v-for="(group, index) in pdfGroups" :key="group.title" class="module-block">
            <a-checkbox
              :checked="pdfModuleState(index).checked"
              :indeterminate="pdfModuleState(index).indeterminate"
              :disabled="pdfExporting"
              @change="event => togglePdfModule(index, event.target.checked)"
            >
              <strong>{{ group.title }}</strong>
              <small>{{ t('docsExport.articleCount', { count: group.items.length }) }}</small>
            </a-checkbox>
            <a-checkbox-group v-model:value="selectedPdfArticles" :disabled="pdfExporting" @change="markPdfCustom">
              <a-checkbox v-for="entry in group.items" :key="pdfKey(entry.slug)" :value="pdfKey(entry.slug)">
                {{ entry.title }}
              </a-checkbox>
            </a-checkbox-group>
          </div>
        </div>

        <div class="export-action">
          <div>
            <strong>{{ t('docsExport.pdfActionTitle') }}</strong>
            <span>{{ t('docsExport.pdfActionHint') }}</span>
          </div>
          <a-button type="primary" :loading="pdfExporting" :disabled="!selectedArticleCount || pdfExporting" @click="exportPdf">
            <FilePdfOutlined /> {{ t('docsExport.exportPdf') }}
          </a-button>
        </div>
        <div v-if="pdfProgress" class="pdf-progress" role="status" aria-live="polite">
          <a-steps size="small" :current="pdfProgressStep" :status="pdfProgress.stage === 'failed' ? 'error' : pdfProgress.stage === 'complete' ? 'finish' : 'process'"
            :items="pdfProgressSteps" />
          <div class="pdf-progress-overall">
            <span>{{ t('docsExport.progress.overallStages', { completed: pdfProgressStep, total: pdfStageOrder.length }) }}</span>
            <a-progress :percent="pdfProgressStep / pdfStageOrder.length * 100" :show-info="false"
              role="progressbar" :aria-label="t('docsExport.progress.overallLabel')"
              :aria-valuenow="pdfProgressStep" :aria-valuemin="0" :aria-valuemax="pdfStageOrder.length"
              :aria-valuetext="t('docsExport.progress.overallStages', { completed: pdfProgressStep, total: pdfStageOrder.length })"
              :status="pdfProgress.stage === 'failed' ? 'exception' : pdfProgress.stage === 'complete' ? 'success' : pdfExporting ? 'active' : 'normal'" />
          </div>
          <div v-if="pdfProgress.pass || pdfProgress.total_passes" class="pdf-progress-stats">
            <div>
              <span>{{ t('docsExport.progress.roundsLabel') }}</span>
              <strong>{{ pdfProgress.total_passes
                ? t('docsExport.progress.roundsTotal', { count: pdfProgress.total_passes })
                : t('docsExport.progress.roundsPending', { count: pdfProgress.pass, completed: pdfProgress.pass - 1 }) }}</strong>
            </div>
            <div>
              <span>{{ t('docsExport.progress.pagesLabel') }}</span>
              <strong>{{ pdfProgress.total_pages
                ? t('docsExport.progress.pagesTotal', { count: pdfProgress.total_pages })
                : pdfProgress.estimated_pages
                  ? t('docsExport.progress.pagesEstimate', { count: pdfProgress.estimated_pages })
                  : t('docsExport.progress.pagesPending') }}</strong>
            </div>
          </div>
          <div class="pdf-progress-detail">
            <span>{{ pdfProgressText }}</span>
            <span>{{ t('docsExport.progress.elapsed', { seconds: pdfElapsed }) }}</span>
            <a-button v-if="pdfExporting" size="small" @click="pdfController?.abort()">{{ t('docsExport.progress.cancel') }}</a-button>
          </div>
          <p v-if="pdfProgress.stage === 'layout'" class="pdf-progress-hint">{{ t('docsExport.progress.layoutHint') }}</p>
        </div>
      </a-tab-pane>

      <a-tab-pane key="xlsx" :tab="t('docsExport.excelTab')">
        <div class="export-toolbar">
          <label>
            <span>{{ t('docsExport.language') }}</span>
            <a-select v-model:value="excelLocale" :options="languageOptions" />
          </label>
          <label>
            <span>{{ t('docsExport.scopePreset') }}</span>
            <a-select v-model:value="excelPreset" :options="excelPresetOptions" @change="applyExcelPreset" />
          </label>
          <div class="selection-count">{{ t('docsExport.featureCount', { count: selectedFeatureCount }) }}</div>
        </div>

        <div class="capability-grid">
          <div v-for="module in capabilityModules" :key="module.id" class="capability-block">
            <a-checkbox
              :checked="excelModuleState(module.id).checked"
              :indeterminate="excelModuleState(module.id).indeterminate"
              @change="event => toggleExcelModule(module.id, event.target.checked)"
            >
              <strong>{{ excelLocale === 'en-US' ? module.en : module.zh }}</strong>
              <small>{{ t('docsExport.featureCount', { count: featureCount(module.id) }) }}</small>
            </a-checkbox>
            <a-checkbox-group v-model:value="selectedExcelGroups" @change="markExcelCustom">
              <a-checkbox v-for="group in excelModuleGroups(module.id)" :key="group.key" :value="group.key">
                {{ group.label }} <small>{{ group.count }}</small>
              </a-checkbox>
            </a-checkbox-group>
          </div>
        </div>

        <div class="export-action">
          <div>
            <strong>{{ t('docsExport.excelActionTitle') }}</strong>
            <span>{{ t('docsExport.excelActionHint') }}</span>
          </div>
          <a-button type="primary" :loading="excelExporting" :disabled="!selectedFeatureCount || excelExporting" @click="exportExcel">
            <FileExcelOutlined /> {{ t('docsExport.exportExcel') }}
          </a-button>
        </div>
      </a-tab-pane>
    </a-tabs>
  </a-card>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { ExportOutlined, FileExcelOutlined, FilePdfOutlined } from '@ant-design/icons-vue'

import { exportDocsPdf } from '../api'
import { capabilityCatalog, capabilityModules } from '../docs/capabilityCatalog'
import { docsContent } from '../docs/content'
import { buildCapabilityWorkbookBlob, capabilityWorkbookFilename, downloadBlob } from '../utils/capabilityWorkbook'
import { buildDocsPdfExportPayload, docsPdfFilename } from '../utils/docsPdfExport'

const HOME_KEY = '__home__'
const { t, locale } = useI18n()
const activeFormat = ref('pdf')
const pdfLocale = ref(locale.value)
const excelLocale = ref(locale.value)
const pdfPreset = ref('all')
const excelPreset = ref('all')
const pdfExporting = ref(false)
const pdfSource = shallowRef({ docsContent })
const pdfProgress = ref(null)
const pdfElapsed = ref(0)
let pdfController
let pdfTimer
const pdfStageOrder = ['refreshing', 'preparing', 'layout', 'downloading']
const pdfProgressSteps = computed(() => pdfStageOrder.map(stage => ({ title: t(`docsExport.progress.${stage}`) })))
const pdfProgressStep = computed(() => {
  if (pdfProgress.value?.stage === 'complete') return 4
  const stage = ['failed', 'cancelled'].includes(pdfProgress.value?.stage) ? pdfProgress.value.previousStage : pdfProgress.value?.stage
  return Math.max(0, pdfStageOrder.indexOf(stage === 'queued' ? 'preparing' : stage))
})
const pdfProgressText = computed(() => {
  const progress = pdfProgress.value
  const key = progress.stage === 'layout'
    ? progress.estimated_pages && progress.page <= progress.estimated_pages ? 'layoutEstimated' : 'layoutPages'
    : progress.stage === 'downloading' && progress.total_bytes ? 'downloadingFile'
    : progress.stage === 'preparing' ? 'articles' : progress.stage
  return t(`docsExport.progress.${key}`, {
    ...progress,
    percent: progress.total_bytes ? Math.floor(progress.completed_bytes / progress.total_bytes * 100) : 0,
  })
})
const excelExporting = ref(false)
const pdfKey = slug => slug || HOME_KEY
const pdfSlug = key => key === HOME_KEY ? '' : key

const languageOptions = computed(() => [
  { value: 'zh-CN', label: t('language.chinese') },
  { value: 'en-US', label: t('language.english') },
])
const pdfPresetOptions = computed(() => [
  { value: 'all', label: t('docsExport.presets.allDocs') },
  { value: 'usage', label: t('docsExport.presets.usage') },
  { value: 'admin', label: t('docsExport.presets.admin') },
  { value: 'custom', label: t('docsExport.presets.custom') },
])
const excelPresetOptions = computed(() => [
  { value: 'all', label: t('docsExport.presets.allFeatures') },
  { value: 'governance', label: t('docsExport.presets.governance') },
  { value: 'operations', label: t('docsExport.presets.operations') },
  { value: 'custom', label: t('docsExport.presets.custom') },
])

const pdfGroups = computed(() => pdfSource.value.docsContent[pdfLocale.value].groups)
const allPdfKeys = computed(() => pdfGroups.value.flatMap(group => group.items.map(entry => pdfKey(entry.slug))))
const selectedPdfArticles = ref(docsContent[locale.value].groups.flatMap(group => group.items.map(entry => pdfKey(entry.slug))))
const excelSubmodules = (localeValue, moduleId) => [...new Set(capabilityCatalog[localeValue]
  .filter(entry => entry.module === moduleId)
  .map(entry => entry.submodule))]
const excelGroupKey = (entry, localeValue) => `${entry.module}:${excelSubmodules(localeValue, entry.module).indexOf(entry.submodule)}`
const allExcelGroupKeys = localeValue => [...new Set(capabilityCatalog[localeValue]
  .map(entry => excelGroupKey(entry, localeValue)))]
const selectedExcelGroups = ref(allExcelGroupKeys(locale.value))

const selectedArticleCount = computed(() => selectedPdfArticles.value.length)
const selectedFeatures = computed(() => capabilityCatalog[excelLocale.value]
  .filter(entry => selectedExcelGroups.value.includes(excelGroupKey(entry, excelLocale.value))))
const selectedFeatureCount = computed(() => selectedFeatures.value.length)

const pdfModuleKeys = index => pdfGroups.value[index].items.map(entry => pdfKey(entry.slug))
const pdfModuleState = index => {
  const keys = pdfModuleKeys(index)
  const count = keys.filter(key => selectedPdfArticles.value.includes(key)).length
  return { checked: count === keys.length, indeterminate: count > 0 && count < keys.length }
}
const togglePdfModule = (index, checked) => {
  const keys = pdfModuleKeys(index)
  const next = new Set(selectedPdfArticles.value)
  keys.forEach(key => checked ? next.add(key) : next.delete(key))
  selectedPdfArticles.value = [...next]
  pdfPreset.value = 'custom'
}
const markPdfCustom = () => { pdfPreset.value = 'custom' }

const applyPdfPreset = preset => {
  if (preset === 'all') {
    selectedPdfArticles.value = [...allPdfKeys.value]
    return
  }
  if (preset === 'usage') {
    const excluded = new Set(['system-management', 'docker-deployment', 'performance-benchmark', 'docker-operations'])
    selectedPdfArticles.value = allPdfKeys.value.filter(key => !excluded.has(pdfSlug(key)))
    return
  }
  if (preset === 'admin') {
    const included = new Set(['', 'quick-start', 'system-management', 'docker-deployment', 'performance-benchmark', 'docker-operations', 'faq'])
    selectedPdfArticles.value = allPdfKeys.value.filter(key => included.has(pdfSlug(key)))
  }
}

const featureCount = moduleId => capabilityCatalog[excelLocale.value].filter(item => item.module === moduleId).length
const excelModuleGroups = moduleId => {
  const items = capabilityCatalog[excelLocale.value].filter(item => item.module === moduleId)
  return excelSubmodules(excelLocale.value, moduleId).map((label, index) => ({
    label,
    key: `${moduleId}:${index}`,
    count: items.filter(item => item.submodule === label).length,
  }))
}
const excelModuleState = moduleId => {
  const keys = excelModuleGroups(moduleId).map(group => group.key)
  const count = keys.filter(key => selectedExcelGroups.value.includes(key)).length
  return { checked: count === keys.length, indeterminate: count > 0 && count < keys.length }
}
const toggleExcelModule = (moduleId, checked) => {
  const keys = excelModuleGroups(moduleId).map(group => group.key)
  const next = new Set(selectedExcelGroups.value)
  keys.forEach(key => checked ? next.add(key) : next.delete(key))
  selectedExcelGroups.value = allExcelGroupKeys(excelLocale.value).filter(key => next.has(key))
  excelPreset.value = 'custom'
}
const markExcelCustom = () => { excelPreset.value = 'custom' }
const applyExcelPreset = preset => {
  const modules = preset === 'all'
    ? capabilityModules.map(module => module.id)
    : preset === 'governance'
      ? ['skill', 'agent', 'client', 'scanner', 'security', 'mcp', 'model']
      : preset === 'operations' ? ['system', 'operations'] : []
  if (modules.length) selectedExcelGroups.value = allExcelGroupKeys(excelLocale.value).filter(key => modules.some(module => key.startsWith(`${module}:`)))
}

const exportPdf = async () => {
  if (pdfExporting.value || !selectedArticleCount.value) return
  pdfExporting.value = true
  pdfController = new AbortController()
  pdfProgress.value = { stage: 'refreshing' }
  pdfElapsed.value = 0
  const startedAt = Date.now()
  pdfTimer = setInterval(() => { pdfElapsed.value = Math.floor((Date.now() - startedAt) / 1000) }, 1000)
  try {
    const now = new Date()
    const exportLocale = pdfLocale.value
    const latest = await fetch('/docs/content.json', { cache: 'no-store', signal: pdfController.signal })
    if (!latest.ok) throw new Error('docs_export.content_unavailable')
    pdfSource.value = await latest.json()
    if (pdfPreset.value === 'custom') {
      selectedPdfArticles.value = selectedPdfArticles.value.filter(key => allPdfKeys.value.includes(key))
    } else {
      applyPdfPreset(pdfPreset.value)
    }
    const payload = buildDocsPdfExportPayload({
      locale: exportLocale,
      selectedArticleKeys: selectedPdfArticles.value,
      source: pdfSource.value,
    })
    const blob = await exportDocsPdf(payload, progress => { pdfProgress.value = { ...pdfProgress.value, ...progress } }, pdfController.signal)
    downloadBlob(blob, docsPdfFilename(exportLocale, now))
    pdfProgress.value = { ...pdfProgress.value, stage: 'complete' }
    message.success(t('docsExport.pdfSuccess'))
  } catch (error) {
    if (pdfController.signal.aborted) {
      pdfProgress.value = { ...pdfProgress.value, stage: 'cancelled', previousStage: pdfProgress.value.stage }
      return
    }
    console.error('Help documentation PDF export failed', error)
    const previousStage = pdfProgress.value.stage
    pdfProgress.value = { ...pdfProgress.value, stage: 'failed', previousStage }
    message.error(t('docsExport.pdfFailed'))
  } finally {
    clearInterval(pdfTimer)
    pdfExporting.value = false
  }
}

onBeforeUnmount(() => {
  pdfController?.abort()
  clearInterval(pdfTimer)
})

const exportExcel = async () => {
  if (excelExporting.value || !selectedFeatureCount.value) return
  excelExporting.value = true
  try {
    const now = new Date()
    const blob = await buildCapabilityWorkbookBlob({ items: selectedFeatures.value, locale: excelLocale.value, generatedAt: now })
    downloadBlob(blob, capabilityWorkbookFilename(excelLocale.value, now))
    message.success(t('docsExport.excelSuccess'))
  } catch (error) {
    console.error('Capability workbook export failed', error)
    message.error(t('docsExport.excelFailed'))
  } finally {
    excelExporting.value = false
  }
}

watch(excelLocale, localeValue => {
  const validKeys = new Set(allExcelGroupKeys(localeValue))
  selectedExcelGroups.value = selectedExcelGroups.value.filter(key => validKeys.has(key))
})
</script>

<style scoped>
.export-card { margin-bottom: 18px; }
.pdf-progress { margin-top: 18px; padding: 16px; background: #f8fafc; border: 1px solid #e3eaf2; border-radius: 10px; }
.pdf-progress-detail { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 12px; color: #526579; overflow-wrap: anywhere; }
.pdf-progress-stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.pdf-progress-stats > div { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.pdf-progress-stats span, .pdf-progress-hint { color: #718196; font-size: 12px; }
.pdf-progress-stats strong { color: #29445d; overflow-wrap: anywhere; }
.pdf-progress-hint { margin: 8px 0 0; line-height: 1.5; }
.pdf-progress-overall { margin-top: 16px; color: #526579; font-size: 12px; }
@media (prefers-reduced-motion: reduce) { .pdf-progress :deep(.ant-progress-bg::before) { animation: none; } }
.card-heading { display: flex; align-items: center; gap: 12px; }
.card-heading > div { display: flex; min-width: 0; flex-direction: column; gap: 3px; white-space: normal; }
.card-heading strong { color: #1e3852; font-size: 15px; }
.card-heading span:not(.card-icon) { color: #718196; font-size: 12px; font-weight: 400; }
.card-icon { display: grid; width: 34px; height: 34px; place-items: center; color: #1f5ea8; background: #edf5ff; border-radius: 9px; }
.export-toolbar { display: grid; grid-template-columns: 180px 220px minmax(180px, 1fr); align-items: end; gap: 14px; margin-bottom: 18px; }
.export-toolbar label { display: flex; flex-direction: column; gap: 7px; color: #526579; font-size: 12px; }
.selection-count { justify-self: end; padding-bottom: 8px; color: #365a7b; font-size: 12px; font-weight: 650; }
.module-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.module-block { min-width: 0; padding: 14px; background: #f8fafc; border: 1px solid #e3eaf2; border-radius: 10px; }
.module-block > :deep(.ant-checkbox-wrapper) { display: flex; align-items: center; }
.module-block strong, .capability-grid strong { color: #253f58; }
.module-block small, .capability-grid small { margin-left: 7px; color: #7a8999; }
.module-block :deep(.ant-checkbox-group) { display: grid; grid-template-columns: minmax(0, 1fr); gap: 7px; margin: 11px 0 0 25px; }
.module-block :deep(.ant-checkbox-wrapper) { align-items: flex-start; color: #526579; font-size: 12px; line-height: 1.45; white-space: normal; overflow-wrap: anywhere; }
.capability-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.capability-block { min-width: 0; padding: 13px; background: #f8fafc; border: 1px solid #e3eaf2; border-radius: 9px; }
.capability-block > :deep(.ant-checkbox-wrapper) { align-items: flex-start; }
.capability-block :deep(.ant-checkbox-group) { display: grid; gap: 6px; margin: 10px 0 0 25px; }
.capability-block :deep(.ant-checkbox-group .ant-checkbox-wrapper) { align-items: flex-start; color: #526579; font-size: 12px; line-height: 1.45; }
.export-action { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 20px; padding-top: 17px; border-top: 1px solid #e8edf3; }
.export-action > div { display: flex; flex-direction: column; gap: 4px; }
.export-action strong { color: #29445d; }
.export-action span { color: #718196; font-size: 12px; line-height: 1.5; }
@media (max-width: 920px) {
  .module-grid, .capability-grid { grid-template-columns: 1fr; }
  .export-toolbar { grid-template-columns: 1fr 1fr; }
  .selection-count { grid-column: 1 / -1; justify-self: start; }
}
@media (max-width: 620px) {
  .export-toolbar { grid-template-columns: 1fr; }
  .selection-count { grid-column: 1; }
  .export-action { align-items: stretch; flex-direction: column; }
}
</style>
