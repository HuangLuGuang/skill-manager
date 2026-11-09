<template>
  <section>
    <div class="diagnostic-toolbar">
      <a-input v-model:value="filters.keyword" allow-clear :placeholder="t('clientDiagnostics.search')" :aria-label="t('clientDiagnostics.search')" @change="later" @press-enter="filter" />
      <a-space wrap>
        <a-checkbox v-model:checked="unresolved" @change="filter">{{ t('clientSummary.unresolvedOnly') }}</a-checkbox>
        <a-button :loading="loading" @click="refresh">{{ t('clientDiagnostics.refresh') }}</a-button>
        <a-button v-if="filtered" @click="reset">{{ t('clientDiagnostics.reset') }}</a-button>
        <a-button v-if="hasAccess('clients:diagnostics-export')" :loading="downloading" :disabled="loading || pending || !rows.length || downloading" @click="download">{{ t('clientDiagnostics.download') }}</a-button>
      </a-space>
    </div>
    <a-alert v-if="error" :message="t('clientDiagnostics.failed')" type="error" show-icon />
    <a-table :columns="columns" :data-source="rows" row-key="id" size="small" :loading="loading" :pagination="pagination" :scroll="{ x: 900 }" @change="paginate">
      <template #customFilterDropdown="{ column }">
        <div class="diagnostic-filter">
          <a-select v-if="column.key === 'level'" v-model:value="filters.level" :options="levels" :aria-label="t('clientDiagnostics.level')" @change="filter" />
          <a-range-picker v-else-if="column.key === 'time'" v-model:value="dates" show-time format="YYYY-MM-DD HH:mm:ss" :placeholder="[t('clientDiagnostics.start'), t('clientDiagnostics.end')]" @change="filter" />
          <a-input v-else v-model:value="filters[column.key]" allow-clear :placeholder="t('clientDiagnostics.exact')" :aria-label="t(`clientDiagnostics.${column.key}`)" @change="later" @press-enter="filter" />
        </div>
      </template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'time'">{{ formatTime(record.time) }}</template>
        <template v-else-if="column.key === 'event'"><a-tag v-if="record.event === 'sync_recovered'" color="success">{{ t('clientDiagnostics.recovered') }}</a-tag><template v-else>{{ record.event }}</template><div v-if="record.aggregation">{{ t('clientDiagnostics.repeated', { count: record.aggregation.repeated_count }) }}</div></template>
        <template v-else-if="column.key === 'open'"><a-button type="link" size="small" @click="selected = record">{{ t('clientDiagnostics.raw') }}</a-button></template>
      </template>
    </a-table>
    <a-modal :open="!!selected" :title="t('clientDiagnostics.raw')" :footer="null" width="800px" @cancel="selected = null"><pre class="diagnostic-original">{{ selected ? JSON.stringify(selected, null, 2) : '' }}</pre></a-modal>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can as hasAccess } from '../access'
import { getClientDiagnosticLogs, downloadClientDiagnosticLogs } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, initialUnresolved: Boolean })
const unresolved = ref(props.initialUnresolved)
const { t, locale } = useI18n()
const filters = reactive({ keyword: '', level: '', module: '', version: '' }), dates = ref(null)
const rows = ref([]), total = ref(0), page = ref(1), pageSize = ref(10), loading = ref(false), error = ref(false), selected = ref(null), downloading = ref(false), pending = ref(false)
const sortOrder = ref('descend')
let request = 0, timer, disposed = false, displayedParams = null
const filtered = computed(() => unresolved.value || Object.values(filters).some(Boolean) || dates.value)
const columns = computed(() => [
  ...['time', 'level', 'module', 'event', 'version'].map(key => ({ key, dataIndex: key, title: t(`clientDiagnostics.${key}`), width: key === 'time' ? 190 : 130, ellipsis: key !== 'time', sorter: key === 'time', sortOrder: key === 'time' ? sortOrder.value : undefined, sortDirections: ['descend', 'ascend', 'descend'], customFilterDropdown: key !== 'event', filteredValue: key === 'time' ? (dates.value ? ['range'] : null) : filters[key] ? [filters[key]] : null })),
  { key: 'open', width: 130 },
])
const levels = computed(() => [{ value: '', label: t('clientDiagnostics.all') }, ...['DEBUG', 'INFO', 'WARN', 'ERROR'].map(value => ({ value, label: value }))])
const pagination = computed(() => ({ current: page.value, pageSize: pageSize.value, total: total.value, showSizeChanger: true }))
const formatTime = value => new Date(value).toLocaleString(locale.value, { hour12: false })
const params = () => ({ ...filters, unresolved: unresolved.value, page: page.value, page_size: pageSize.value, sort_order: sortOrder.value === 'ascend' ? 'asc' : 'desc', start: dates.value?.[0]?.toISOString(), end: dates.value?.[1]?.toISOString() })
async function load() {
  clearTimeout(timer); pending.value = false
  const current = ++request, query = params()
  loading.value = true; error.value = false
  try {
    const data = await getClientDiagnosticLogs(props.clientId, query)
    if (disposed || current !== request) return
    rows.value = data.items; total.value = data.total; displayedParams = query
  } catch { if (!disposed && current === request) { error.value = true; rows.value = []; total.value = 0 } }
  finally { if (!disposed && current === request) loading.value = false }
}
function filter() { page.value = 1; load() }
function later() { clearTimeout(timer); pending.value = true; request++; timer = setTimeout(filter, 300) }
function refresh() { if (pending.value) page.value = 1; load() }
function reset() { Object.keys(filters).forEach(key => { filters[key] = '' }); unresolved.value = false; dates.value = null; filter() }
function paginate(value, _, sorter, extra) { page.value = pending.value || extra.action === 'sort' ? 1 : value.current; pageSize.value = value.pageSize; sortOrder.value = sorter.order || 'descend'; load() }
async function download() {
  if (downloading.value || loading.value || pending.value || !displayedParams) return
  downloading.value = true
  try {
    const data = await downloadClientDiagnosticLogs(props.clientId, displayedParams)
    if (disposed) return
    const url = URL.createObjectURL(data), link = document.createElement('a')
    link.href = url; link.download = 'client-runtime-logs.jsonl'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch { if (!disposed) message.error(t('clientDiagnostics.downloadFailed')) }
  finally { downloading.value = false }
}
watch(() => props.clientId, () => { selected.value = null; filter() }, { immediate: true })
onBeforeUnmount(() => { disposed = true; request++; clearTimeout(timer) })
</script>
<style scoped>
.diagnostic-toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center; }
.diagnostic-toolbar > .ant-input-affix-wrapper { max-width: 320px; }
.diagnostic-filter { padding: 8px; max-width: calc(100vw - 40px); }
.diagnostic-filter .ant-select { min-width: 180px; }
.diagnostic-filter .ant-picker { width: 440px; max-width: 100%; }
.diagnostic-original { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 65vh; overflow: auto; }
</style>
