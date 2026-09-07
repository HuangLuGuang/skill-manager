<template>
  <section class="trajectory-stream">
    <div class="stream-toolbar">
      <a-input v-model:value="query" allow-clear :placeholder="t('runtimeTraceExplorer.stream.search')" :aria-label="t('runtimeTraceExplorer.stream.search')" @press-enter="matches.length && moveMatch(1)">
        <template #prefix><SearchOutlined /></template>
      </a-input>
      <span class="match-count">{{ matches.length ? `${matchIndex + 1} / ${matches.length}` : '0' }}</span>
      <a-tooltip :title="t('runtimeTraceExplorer.stream.previousMatch')"><a-button :disabled="!matches.length" :aria-label="t('runtimeTraceExplorer.stream.previousMatch')" @click="moveMatch(-1)"><UpOutlined /></a-button></a-tooltip>
      <a-tooltip :title="t('runtimeTraceExplorer.stream.nextMatch')"><a-button :disabled="!matches.length" :aria-label="t('runtimeTraceExplorer.stream.nextMatch')" @click="moveMatch(1)"><DownOutlined /></a-button></a-tooltip>
      <a-tooltip :title="t(collapsed ? 'runtimeTraceExplorer.stream.expand' : 'runtimeTraceExplorer.stream.collapse')"><a-button :aria-label="t(collapsed ? 'runtimeTraceExplorer.stream.expand' : 'runtimeTraceExplorer.stream.collapse')" @click="toggleAll"><ExpandAltOutlined v-if="collapsed" /><ShrinkOutlined v-else /></a-button></a-tooltip>
      <label class="follow-toggle"><a-switch v-model:checked="follow" size="small" @change="follow && jumpLatest()" />{{ t('runtimeTraceExplorer.stream.follow') }}</label>
      <a-tooltip :title="t('runtimeTraceExplorer.stream.latest')"><a-button :aria-label="t('runtimeTraceExplorer.stream.latest')" @click="jumpLatest"><VerticalAlignBottomOutlined /></a-button></a-tooltip>
    </div>
    <div class="stream-overview" :aria-label="t('runtimeTraceExplorer.stream.overview')">
      <div v-for="lane in lanes" :key="lane" class="overview-lane">
        <span>{{ t(`runtimeTraceExplorer.lanes.${lane}`) }}</span>
        <div class="overview-track">
          <button v-for="bucket in overview.filter(item => item.lane === lane)" :key="bucket.index" type="button" :class="`lane-${lane}`"
            :style="{ left: `${bucket.position}%` }" :title="`${rowLabel(bucket.row)} · #${bucket.row.event.seq}`"
            :aria-label="`${rowLabel(bucket.row)} · #${bucket.row.event.seq}`" @click="locate(bucket.row.id)" />
        </div>
      </div>
    </div>
    <div ref="viewport" class="stream-viewport" tabindex="0" :aria-label="t('runtimeTraceExplorer.pagination.traceRegion')" @scroll="onScroll">
      <div :style="{ height: `${start * rowHeight}px` }" aria-hidden="true" />
      <div v-for="row in windowRows" :key="row.id" class="stream-entry" :style="{ height: `${rowHeight}px` }">
      <button v-if="row.kind === 'request'" class="request-toggle" type="button" :aria-expanded="!closedGroups.has(row.group) && !collapsed" :aria-label="`${t(closedGroups.has(row.group) || collapsed ? 'runtimeTraceExplorer.stream.expand' : 'runtimeTraceExplorer.stream.collapse')} · ${rowLabel(row)}`" @click="toggleGroup(row.group)"><RightOutlined v-if="closedGroups.has(row.group) || collapsed" /><DownOutlined v-else /></button>
      <button type="button" class="stream-row" :class="[{ selected: row.id === selectedId, match: row.id === matches[matchIndex]?.id, request: row.kind === 'request', danger: eventStatusTone(row.status) === 'danger' || row.kind === 'error' }, `kind-${row.kind}`]"
        @click="select(row)">
        <span class="role-mark" :class="`lane-${row.lane}`">{{ rowLabel(row) }}</span>
        <span class="row-content">
          <strong v-if="row.kind === 'request'">{{ row.model || row.requestId }}</strong>
          <template v-else><strong v-if="row.toolName">{{ row.toolName }} </strong>{{ row.preview || t('runtimeTraceExplorer.payloadUnavailable') }}</template>
        </span>
        <span v-if="row.observed && row.kind === 'tool'" class="row-observed" :title="t('runtimeTraceExplorer.stream.observed')"><EyeOutlined /></span>
        <span v-if="row.duration != null" class="row-duration">{{ Math.round(row.duration) }} ms</span>
        <code class="row-seq">#{{ row.event.seq }}</code>
      </button>
      </div>
      <div :style="{ height: `${Math.max(0, visibleRows.length - end) * rowHeight}px` }" aria-hidden="true" />
      <a-empty v-if="!visibleRows.length" :description="t('runtimeTraceExplorer.timeline.empty')" />
    </div>
    <div class="stream-footer"><span>{{ t('runtimeTraceExplorer.stream.rows', { count: rows.length }) }}</span><span>{{ t('runtimeTraceExplorer.stream.loadedOnly') }}</span></div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DownOutlined, ExpandAltOutlined, EyeOutlined, RightOutlined, SearchOutlined, ShrinkOutlined, UpOutlined, VerticalAlignBottomOutlined } from '@ant-design/icons-vue'
import { eventStatusTone } from '../runtimeTraceView'

const props = defineProps({ rows: { type: Array, default: () => [] }, mode: String, selectedId: String })
const emit = defineEmits(['select', 'load-more'])
const { t, te } = useI18n()
const viewport = ref(null)
const query = ref('')
const collapsed = ref(false)
const closedGroups = ref(new Set())
const toggleAll = () => { closedGroups.value = new Set(); collapsed.value = !collapsed.value }
const follow = ref(false)
const scrollTop = ref(0)
const height = ref(600)
const matchIndex = ref(0)
const rowHeight = computed(() => props.mode === 'conversation' ? 88 : 40)
const requestGroups = computed(() => new Set(props.rows.filter(row => row.kind === 'request' && row.group).map(row => row.group)))
const visibleRows = computed(() => props.rows.filter(row => row.kind === 'request' || row.kind === 'error' || row.lane === 'policy'
  || !(closedGroups.value.has(row.group) || (collapsed.value && requestGroups.value.has(row.group)))))
const toggleGroup = group => {
  const next = new Set(collapsed.value ? requestGroups.value : closedGroups.value)
  collapsed.value = false
  if (next.has(group)) next.delete(group)
  else next.add(group)
  closedGroups.value = next
}
const start = computed(() => Math.max(0, Math.min(visibleRows.value.length, Math.floor(scrollTop.value / rowHeight.value) - 8)))
const end = computed(() => Math.min(visibleRows.value.length, start.value + Math.ceil(height.value / rowHeight.value) + 16))
const windowRows = computed(() => visibleRows.value.slice(start.value, end.value))
const rowLabel = row => {
  if (row.kind === 'request') return t('runtimeTraceExplorer.stream.request', { number: row.number })
  const key = `runtimeTraceExplorer.stream.roles.${row.kind}`
  if (row.kind === 'event') {
    const eventKey = `runtimeTraceExplorer.eventTypes.${row.event.type.replaceAll('.', '_')}`
    return te(eventKey) ? t(eventKey) : row.event.type
  }
  return te(key) ? t(key) : row.event.type
}
const searchIndex = computed(() => props.rows.map(row => ({ row, text: [rowLabel(row), row.toolName, row.requestId, row.model,
  ...(row.kind === 'request' ? [] : [row.content, row.result]),
].map(value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value)).join(' ').toLocaleLowerCase() })))
const matches = computed(() => query.value.trim() ? searchIndex.value.filter(item => item.text.includes(query.value.trim().toLocaleLowerCase())).map(item => item.row) : [])
const lanes = computed(() => [...new Set(props.rows.map(row => row.lane))])
const overview = computed(() => {
  const buckets = new Map()
  props.rows.forEach((row, index) => {
    const position = Math.floor(index / Math.max(1, props.rows.length - 1) * 99)
    buckets.set(`${row.lane}:${position}`, { row, index, lane: row.lane, position })
  })
  return [...buckets.values()]
})
const select = row => emit('select', row)
const locate = async id => {
  collapsed.value = false
  closedGroups.value = new Set()
  follow.value = false
  await nextTick()
  const index = visibleRows.value.findIndex(row => row.id === id)
  if (index < 0) return
  viewport.value.scrollTop = index * rowHeight.value
  scrollTop.value = viewport.value.scrollTop
  select(visibleRows.value[index])
}
const moveMatch = delta => {
  matchIndex.value = (matchIndex.value + delta + matches.value.length) % matches.value.length
  locate(matches.value[matchIndex.value].id)
}
const jumpLatest = async () => {
  await nextTick()
  if (viewport.value) {
    viewport.value.scrollTop = viewport.value.scrollHeight
    scrollTop.value = viewport.value.scrollTop
  }
  emit('load-more')
}
const onScroll = event => {
  const element = event.currentTarget
  scrollTop.value = element.scrollTop
  height.value = element.clientHeight
  if (element.scrollTop + element.clientHeight < element.scrollHeight - 100) follow.value = false
  if (element.scrollTop + element.clientHeight >= element.scrollHeight - 100) emit('load-more')
}
watch(query, () => { matchIndex.value = 0; if (matches.value.length) locate(matches.value[0].id) })
watch(() => props.rows.length, () => { if (follow.value) jumpLatest() })
watch([collapsed, closedGroups, () => props.mode], () => { scrollTop.value = 0; if (viewport.value) viewport.value.scrollTop = 0 })
</script>

<style scoped>
.trajectory-stream { min-width: 0; border-top: 1px solid #e4e7eb; }
.stream-toolbar { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; padding: 10px 0; }
.stream-toolbar > .ant-input-affix-wrapper { width: 200px; flex: 1; min-width: 120px; }
.stream-toolbar > .ant-btn { width: 30px; padding: 0; flex-shrink: 0; }
.match-count, .follow-toggle, .stream-footer { font-size: 11px; color: #69717c; }
.follow-toggle { display: flex; align-items: center; gap: 6px; margin-inline: 4px; }
.match-count { min-width: 36px; text-align: center; }
.stream-overview { padding: 6px 0 10px; border-bottom: 1px solid #e4e7eb; }
.overview-lane { display: flex; align-items: center; height: 15px; gap: 8px; }
.overview-lane > span { font-size: 10px; width: 64px; color: #69717c; }
.overview-track { position: relative; flex: 1; height: 10px; background: #f5f6f8; }
.overview-track button { position: absolute; width: 1%; min-width: 3px; height: 10px; border: 0; cursor: pointer; padding: 0; background: var(--lane-ink); opacity: .6; }
.stream-viewport { height: min(62vh, 720px); min-height: 300px; overflow: auto; overscroll-behavior: contain; }
.stream-entry { position: relative; }
.request-toggle { position: absolute; left: 2px; top: 50%; transform: translateY(-50%); width: 22px; height: 26px; padding: 0; border: 0; background: transparent; z-index: 1; color: #69717c; cursor: pointer; font-size: 10px; }
.stream-row { width: 100%; height: 100%; display: flex; align-items: center; gap: 10px; padding: 0 8px 0 27px; text-align: left; border: 0; border-bottom: 1px solid #eef0f3; background: #fff; color: #303640; cursor: pointer; font: inherit; font-size: 12px; }
.stream-row:hover { background: #f6f8fa; }
.stream-row.selected { background: #eaf3ff; box-shadow: inset 3px 0 #3478c5; }
.stream-row.match { outline: 1px solid #dba740; outline-offset: -1px; }
.stream-row.request { background: #f7f8fa; }
.stream-row.request.selected { background: #eaf3ff; }
.stream-row.danger { color: #b53642; }
.role-mark { color: var(--lane-ink); background: var(--lane-bg); font-size: 10px; padding: 3px 5px; border-radius: 3px; width: 70px; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lane-input { --lane-ink: #357b69; --lane-bg: #edf6f0; }
.lane-model { --lane-ink: #346fba; --lane-bg: #edf3fc; }
.lane-tools, .lane-mcp { --lane-ink: #986a2e; --lane-bg: #fbf3e8; }
.lane-policy { --lane-ink: #ac455b; --lane-bg: #fbeff2; }
.lane-knowledge { --lane-ink: #7960a3; --lane-bg: #f3eff9; }
.row-content { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.7; }
.stream-entry[style*="88px"] .row-content { white-space: pre-wrap; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; max-height: 63px; }
.row-content strong { font-weight: 600; }
.row-duration, .row-seq, .row-observed { color: #7c8491; font-size: 10px; flex-shrink: 0; }
.row-seq { width: 35px; text-align: right; }
.stream-footer { display: flex; justify-content: space-between; gap: 10px; padding: 8px 0; flex-wrap: wrap; }
button:focus-visible { outline: 2px solid #3478c5; outline-offset: -2px; }
@media (max-width: 600px) { .row-duration, .row-seq { display: none; } .stream-row { gap: 6px; padding-right: 3px; } .role-mark { width: 62px; } }
</style>
