<template>
  <div class="dataset-selection">
    <a-button :loading="loading" @click="open = true">
      <template #icon><BookOutlined /></template>
      {{ t('agentSecurityScans.tasks.datasetCatalog.choose') }}
    </a-button>
    <span class="selection-count">{{ t('agentSecurityScans.tasks.datasetCatalog.selected', { count: modelValue.length }) }}</span>
    <div v-if="modelValue.length" class="selected-datasets">
      <a-tag v-for="name in modelValue" :key="name" closable @close.prevent="toggle(name, false)">{{ name }}</a-tag>
    </div>
  </div>

  <a-drawer v-model:open="open" width="min(980px, 100vw)" :title="t('agentSecurityScans.tasks.datasetCatalog.title')" :body-style="{ padding: '20px' }">
    <div class="catalog-toolbar">
      <a-input-search v-model:value="query" allow-clear :placeholder="t('agentSecurityScans.tasks.datasetCatalog.search')" :enter-button="t('agentSecurityScans.tasks.datasetCatalog.searchAction')" @search="applySearch" @change="handleSearchChange" />
      <span class="catalog-total">{{ t('agentSecurityScans.tasks.datasetCatalog.total', { count: filteredDatasets.length }) }}</span>
    </div>
    <a-spin :spinning="loading">
      <div class="dataset-list">
        <article v-for="dataset in pageDatasets" :key="dataset.name" class="dataset-entry" :class="{ 'is-selected': modelValue.includes(dataset.name) }">
          <header class="dataset-heading">
            <a-checkbox :checked="modelValue.includes(dataset.name)" :aria-label="t('agentSecurityScans.tasks.datasetCatalog.selectDataset', { name: dataset.name })" @change="toggle(dataset.name, $event.target.checked)" />
            <h3><button type="button" class="dataset-name" @click="showDetails(dataset.name)">{{ dataset.name }}</button></h3>
            <span v-if="dataset.language" class="dataset-language">{{ dataset.language }}</span>
            <span class="dataset-samples">{{ t('agentSecurityScans.tasks.datasetCatalog.samples', { count: dataset.count.toLocaleString(locale) }) }}</span>
          </header>
          <div class="dataset-recommendation">
            <span>{{ t('agentSecurityScans.tasks.datasetCatalog.recommendation') }}</span>
            <a-rate :value="dataset.recommendation" disabled :aria-label="t('agentSecurityScans.tasks.datasetCatalog.rating', { value: dataset.recommendation })" />
          </div>
          <div v-if="dataset.tags.length" class="dataset-tags">
            <a-tag v-for="tag in dataset.tags" :key="tag">{{ tag }}</a-tag>
          </div>
          <p class="dataset-description">{{ description(dataset) }}</p>
        </article>
        <a-empty v-if="!loading && !filteredDatasets.length" :description="t('agentSecurityScans.tasks.datasetCatalog.empty')" />
      </div>
    </a-spin>
    <div class="catalog-pagination">
      <a-pagination v-model:current="page" :total="filteredDatasets.length" :page-size="pageSize" :show-size-changer="false" :hide-on-single-page="true" />
    </div>
    <template #footer>
      <div class="catalog-footer">
        <span>{{ t('agentSecurityScans.tasks.datasetCatalog.selected', { count: modelValue.length }) }}</span>
        <a-button type="primary" @click="open = false">{{ t('agentSecurityScans.tasks.datasetCatalog.done') }}</a-button>
      </div>
    </template>
  </a-drawer>
  <a-modal v-model:open="detailsOpen" :title="t('agentSecurityScans.tasks.datasetCatalog.details', { name: detailName })" width="min(1100px, calc(100vw - 32px))" :footer="null" :z-index="1100" @cancel="closeDetails">
    <a-alert v-if="detailError" type="error" show-icon :message="detailError" class="detail-error">
      <template #action><a-button size="small" @click="loadDetails(detailPage)">{{ t('agentSecurityScans.tasks.datasetCatalog.retry') }}</a-button></template>
    </a-alert>
    <a-table class="dataset-prompts" :columns="detailColumns" :data-source="detailItems" row-key="index" bordered size="small" :loading="detailLoading" :pagination="false" :scroll="{ y: '60vh' }" :locale="{ emptyText: t('agentSecurityScans.tasks.datasetCatalog.emptyPrompts') }">
      <template #bodyCell="{ column, record }"><span v-if="column.key === 'prompt'" class="prompt-text">{{ record.prompt }}</span></template>
    </a-table>
    <div class="detail-pagination">
      <span>{{ t('agentSecurityScans.tasks.datasetCatalog.samples', { count: detailTotal.toLocaleString(locale) }) }}</span>
      <a-pagination :current="detailPage" :total="detailTotal" :page-size="20" :show-size-changer="false" :show-less-items="true" :disabled="detailLoading" @change="loadDetails" />
    </div>
  </a-modal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { BookOutlined } from '@ant-design/icons-vue'
import { useI18n } from 'vue-i18n'
import { getSecurityRedteamDataset } from '../../api'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  datasets: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t, locale } = useI18n()
const open = ref(false)
const query = ref('')
const search = ref('')
const page = ref(1)
const pageSize = 3
const description = dataset => locale.value === 'zh-CN' ? dataset.description_zh || dataset.description : dataset.description || dataset.description_zh
const filteredDatasets = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase()
  return props.datasets.filter(dataset => [dataset.name, dataset.description, dataset.description_zh, ...dataset.tags].join(' ').toLocaleLowerCase().includes(needle))
})
const pageDatasets = computed(() => filteredDatasets.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const applySearch = () => { search.value = query.value; page.value = 1 }
const handleSearchChange = () => { if (!query.value) applySearch() }
const toggle = (name, selected) => emit('update:modelValue', selected ? [...new Set([...props.modelValue, name])] : props.modelValue.filter(value => value !== name))
const detailsOpen = ref(false)
const detailName = ref('')
const detailPage = ref(1)
const detailTotal = ref(0)
const detailItems = ref([])
const detailLoading = ref(false)
const detailError = ref('')
let detailRequest = 0
const detailColumns = computed(() => [
  { title: '#', key: 'index', dataIndex: 'index', width: 64 },
  { title: t('agentSecurityScans.tasks.datasetCatalog.prompt'), key: 'prompt', dataIndex: 'prompt' },
])
const loadDetails = async (nextPage = 1) => {
  const request = ++detailRequest
  detailLoading.value = true
  detailError.value = ''
  detailItems.value = []
  detailPage.value = nextPage
  try {
    const result = await getSecurityRedteamDataset(detailName.value, { page: nextPage, page_size: 20 })
    if (request !== detailRequest) return
    detailItems.value = result.items
    detailTotal.value = result.total
  } catch (error) {
    if (request === detailRequest) detailError.value = error.response?.data?.detail || t('agentSecurityScans.tasks.datasetCatalog.loadFailed')
  } finally { if (request === detailRequest) detailLoading.value = false }
}
const showDetails = name => {
  detailName.value = name
  detailTotal.value = 0
  detailsOpen.value = true
  loadDetails(1)
}
const closeDetails = () => { detailRequest += 1; detailLoading.value = false }
watch(() => props.datasets, () => { page.value = 1 })
</script>

<style scoped>
.dataset-selection { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.selection-count, .catalog-total { color: #697180; font-size: 13px; }
.selected-datasets { display: flex; flex-wrap: wrap; gap: 6px; width: 100%; }
.selected-datasets :deep(.ant-tag) { margin: 0; max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.catalog-toolbar { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.catalog-total { flex-shrink: 0; }
.dataset-list { display: grid; gap: 16px; }
.dataset-entry { min-width: 0; padding: 22px; border: 1px solid #dce2eb; border-radius: 8px; background: #fff; }
.dataset-entry.is-selected { border-color: #1677ff; box-shadow: inset 3px 0 #1677ff; }
.dataset-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px 14px; }
.dataset-heading h3 { min-width: 0; margin: 0; font-size: 20px; line-height: 1.4; font-weight: 650; color: #17202e; overflow-wrap: anywhere; }
.dataset-language { padding: 3px 10px; border-radius: 6px; background: #202124; color: #fff; font-size: 13px; font-weight: 600; }
.dataset-samples { color: #697180; font-size: 14px; margin-left: auto; }
.dataset-recommendation { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; color: #a96b00; font-size: 13px; }
.dataset-recommendation :deep(.ant-rate) { color: #e6a817; font-size: 19px; }
.dataset-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
.dataset-tags :deep(.ant-tag) { margin: 0; color: #515b6a; background: #f7f8fa; border-color: #e0e4ea; }
.dataset-description { margin: 16px 0; color: #3d4756; font-size: 14px; line-height: 1.75; overflow-wrap: anywhere; white-space: pre-wrap; }
.dataset-name { padding: 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; overflow-wrap: anywhere; }
.dataset-name:hover { color: #1677ff; text-decoration: underline; }
.dataset-name:focus-visible { outline: 2px solid #1677ff; outline-offset: 4px; }
.prompt-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; }
.dataset-prompts :deep(table) { table-layout: fixed; }
.detail-pagination { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
.detail-error { margin-bottom: 12px; }
.catalog-pagination { display: flex; justify-content: center; margin: 24px 0 4px; }
.catalog-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
@media (max-width: 600px) {
  .catalog-toolbar { align-items: stretch; flex-direction: column; gap: 8px; }
  .dataset-entry { padding: 16px; }
  .dataset-heading { gap: 8px; }
  .dataset-heading h3 { font-size: 17px; flex-basis: calc(100% - 28px); }
  .dataset-samples { margin-left: 0; }
  .dataset-description { font-size: 13px; }
}
</style>
