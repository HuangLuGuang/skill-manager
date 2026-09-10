<template>
  <div>
    <div class="schedule-toolbar"><h2>{{ t('scanSchedule.title') }}</h2><a-button :loading="loading" :disabled="loading" @click="load">{{ t('assetLifecycle.refresh') }}</a-button></div>
    <p>{{ t('scanSchedule.note') }}</p>
    <a-alert v-if="error" type="error" :message="error" />
    <a-table :columns="columns" :data-source="rows" row-key="schedule_id" :loading="loading" :scroll="{ x: 1300 }" :locale="{ emptyText: t('scanSchedule.empty') }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'target'">{{ targets.find(x => x.target_id === record.target_id)?.name || record.target_id }}</template>
        <template v-else-if="column.key === 'timing'"><span>{{ t(`scanSchedule.${record.timing.kind}`) }}</span><small>{{ record.timing.kind === 'interval' ? record.timing.interval_minutes : record.timing.kind === 'cron' ? record.timing.cron : record.timing.time }} · {{ record.timing.timezone }}</small></template>
        <template v-else-if="column.key === 'enabled'"><a-tag :color="record.enabled ? 'green' : 'default'">{{ t(`scanSchedule.${record.enabled ? 'enabled' : 'paused'}`) }}</a-tag></template>
        <template v-else-if="column.key === 'next'">{{ date(record.next_run_at) }}</template>
        <template v-else-if="column.key === 'last'"><a v-if="record.last_run" @click="record.last_run.task_id ? openReport(record.last_run.task_id) : showRuns(record)">{{ state(record.last_run.status) }}</a><span v-else>—</span></template>
        <template v-else-if="column.key === 'actions'"><a-space wrap>
          <a-button size="small" @click="showRuns(record)">{{ t('scanSchedule.history') }}</a-button>
          <template v-if="canAdmin"><a-button size="small" :disabled="!!busy" @click="$emit('edit', record)">{{ t('assetLifecycle.edit') }}</a-button><a-button size="small" :loading="busy === record.schedule_id" :disabled="!!busy" @click="run(record)">{{ t('scanSchedule.run') }}</a-button><a-button size="small" :disabled="!!busy" @click="toggle(record)">{{ t(record.enabled ? 'scanSchedule.pause' : 'scanSchedule.resume') }}</a-button>
          <a-popconfirm :title="t('scanSchedule.deleteConfirm')" @confirm="remove(record)"><a-button size="small" danger :disabled="!!busy">{{ t('scanSchedule.delete') }}</a-button></a-popconfirm></template>
        </a-space></template>
      </template>
    </a-table>
    <a-drawer v-model:open="historyOpen" :title="selected?.name" @after-open-change="afterHistoryChange" width="min(900px, 100vw)">
      <p>{{ t('scanSchedule.runNote') }}</p>
      <a-table :columns="runColumns" :data-source="runs" row-key="run_id" :scroll="{ x: 720 }">
        <template #bodyCell="{ column, record }"><template v-if="column.key === 'status'">{{ state(record.status) }}</template><template v-else-if="column.key === 'created_at'">{{ date(record.created_at) }}</template><template v-else-if="column.key === 'error_code'">{{ explain(record.error_code) }}</template><template v-else-if="column.key === 'task_id'"><a v-if="record.task_id" @click="openReport(record.task_id)">{{ record.task_id }}</a></template></template>
      </a-table>
    </a-drawer>
  </div>
</template>
<script setup>
import { createRequestId } from '../../utils/requestId'
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { listScanSchedules, listScanScheduleRuns, updateScanSchedule, deleteScanSchedule, triggerScanSchedule } from '../../api'
import { localizeApiError } from '../../i18n/errors'
const props = defineProps({ targets: { type: Array, default: () => [] }, canAdmin: Boolean })
const emit = defineEmits(['edit', 'task', 'count'])
const { t, te, locale } = useI18n()
const rows = ref([]), loading = ref(false), error = ref(''), busy = ref(''), selected = ref(null), runs = ref([]), historyOpen = ref(false)
const date = v => v ? new Date(v).toLocaleString(locale.value) : '—'
const state = v => te(`scanSchedule.states.${v}`) ? t(`scanSchedule.states.${v}`) : v
const explain = code => code ? localizeApiError({ code }, locale.value) : '—'
const columns = computed(() => [['name', 'scanSchedule.name', 190], ['target', 'agentSecurityScans.tasks.target', 160], ['timing', 'scanSchedule.frequency', 170], ['enabled', 'agentSecurityScans.status', 100], ['next', 'scanSchedule.next', 180], ['last', 'scanSchedule.last', 150], ['actions', 'assetLifecycle.actions', 350]].map(([key, label, width]) => ({ key, dataIndex: key, title: t(label), width })))
const runColumns = computed(() => [['created_at', 'assetLifecycle.assessedAt', 190], ['status', 'agentSecurityScans.status', 140], ['error_code', 'assetLifecycle.error', 240], ['task_id', 'agentSecurityScans.detail.task', 240]].map(([key, label, width]) => ({ key, dataIndex: key, title: t(label), width })))
const fail = e => { error.value = e.response?.data?.detail || t('assetLifecycle.failed'); message.error(error.value) }
async function load() { if (loading.value) return; loading.value = true; try { rows.value = await listScanSchedules(); emit('count', rows.value.length); error.value = '' } catch(e) { fail(e) } finally { loading.value = false } }
async function showRuns(row) { selected.value = row; historyOpen.value = true; try { runs.value = await listScanScheduleRuns(row.schedule_id) } catch(e) { fail(e) } }
async function mutate(row, action) { if (busy.value) return; busy.value = row.schedule_id; try { await action(); await load(); if(historyOpen.value) await showRuns(row) } catch(e) { fail(e) } finally { busy.value = '' } }
let pendingReport = null
function openReport(taskId) {
  if (historyOpen.value) { pendingReport = taskId; historyOpen.value = false }
  else emit('task', taskId)
}
function afterHistoryChange(open) {
  if (!open && pendingReport) { const taskId = pendingReport; pendingReport = null; emit('task', taskId) }
}
const runKeys = new Map()
async function run(row) { return mutate(row, async () => { if (!runKeys.has(row.schedule_id)) runKeys.set(row.schedule_id, createRequestId()); await triggerScanSchedule(row.schedule_id, runKeys.get(row.schedule_id)); runKeys.delete(row.schedule_id); message.success(t('scanSchedule.requested')); await showRuns(row) }) }
const toggle = row => mutate(row, () => updateScanSchedule(row.schedule_id, { name: row.name, version: row.version, timing: row.timing, enabled: !row.enabled }))
const remove = row => mutate(row, async () => { await deleteScanSchedule(row.schedule_id); historyOpen.value = false })
let timer
onMounted(() => { load(); timer = setInterval(async () => { await load(); if (historyOpen.value && selected.value) await showRuns(selected.value) }, 10000) })
onUnmounted(() => clearInterval(timer))
defineExpose({ load, open: async id => { await load(); const row = rows.value.find(x => x.schedule_id === id); if (row) await showRuns(row) } })
</script>
<style scoped>
.schedule-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; } small { display: block; color: #667085; overflow-wrap: anywhere; }
</style>
