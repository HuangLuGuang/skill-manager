<template>
  <section v-if="loading || total || failed" class="client-submissions">
    <h3>{{ t('deviceAssignment.history') }}</h3>
    <div v-if="failed">{{ t('deviceAssignment.loadFailed') }} <a-button @click="load">{{ t('deviceAssignment.retry') }}</a-button></div>
    <a-table v-else :data-source="rows" :columns="columns" :loading="loading" row-key="event_id" size="small" table-layout="fixed" :scroll="{ x: 620 }"
      :pagination="{ current: page, pageSize: 10, total, showSizeChanger: false }" @change="changePage">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'source'"><ClientSubmissionSource :source="record.details" /></template>
        <template v-else-if="column.key === 'time'">{{ formatDateTime(record.timestamp) }}</template>
      </template>
    </a-table>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getClientSubmissions } from '../api'
import { formatDateTime } from '../utils/format'
import ClientSubmissionSource from './ClientSubmissionSource.vue'
const props = defineProps({ versionId: String })
const { t } = useI18n()
const rows = ref([]), total = ref(0), page = ref(1), loading = ref(false), failed = ref(false)
let generation = 0
const columns = computed(() => [
  { title: t('deviceAssignment.source'), key: 'source' },
  { title: t('deviceAssignment.credential'), dataIndex: ['details', 'token_name'] },
  { title: t('deviceAssignment.time'), key: 'time', width: 190 },
])
async function load() {
  const request = ++generation
  if (!props.versionId) { loading.value = false; failed.value = false; return }
  loading.value = true
  failed.value = false
  try {
    const data = await getClientSubmissions(props.versionId, { page: page.value })
    if (request !== generation) return
    rows.value = data.items
    total.value = data.total
  } catch { if (request === generation) failed.value = true }
  finally { if (request === generation) loading.value = false }
}
function changePage(pagination) { page.value = pagination.current; void load() }
watch(() => props.versionId, () => { page.value = 1; rows.value = []; total.value = 0; void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.client-submissions { margin-top: 16px; min-width: 0; }
.client-submissions :deep(td) { overflow-wrap: anywhere; }
h3 { font-size: 14px; }
</style>
