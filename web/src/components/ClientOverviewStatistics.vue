<template>
  <section :aria-busy="loading" class="statistics">
    <div class="toolbar">
      <a-radio-group v-model:value="source" :aria-label="tr('source')" button-style="solid"><a-radio-button value="hooks">Hook</a-radio-button><a-radio-button value="logs">{{ tr('logs') }}</a-radio-button></a-radio-group>
      <a-select v-model:value="agent" :aria-label="tr('agent')" :options="agentOptions" class="select" />
      <a-select v-model:value="hours" :aria-label="tr('range')" :options="rangeOptions" class="select" />
      <a-popover trigger="click" :title="tr('definition')"><template #content><div class="rules"><p>{{ tr('rules') }}</p><p>{{ tr('timeRule') }}</p><p>{{ tr('rankRule') }}</p></div></template><a-button type="text"><InfoCircleOutlined /> {{ tr('definition') }}</a-button></a-popover>
      <span class="updated" v-if="data?.updated_at">{{ tr('updated', { time: time(data.updated_at) }) }}</span>
      <a-button :loading="loading" @click="load"><ReloadOutlined /> {{ tr('refresh') }}</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="tr('failed')"><template #action><a-button @click="load">{{ tr('retry') }}</a-button></template></a-alert>
    <a-alert v-if="data?.state === 'delayed'" type="warning" show-icon :message="tr('delayed')" />
    <div v-if="!data && loading || data?.state === 'preparing'" class="preparing" role="status"><a-spin /><span>{{ data ? tr('preparing') : tr('working') }}</span><a-skeleton active :paragraph="{ rows: 4 }" /></div>
    <div v-else-if="data && !error" :class="{ refreshing: loading }">
      <div class="metrics"><button v-for="(key, i) in metricKeys" :key="key" class="metric" :class="{ failure: key === 'failures' }" @click="openDetails(key)"><span><component :is="icons[i]" /> {{ tr(key) }}</span><strong>{{ data.totals[key].toLocaleString(locale) }}</strong><small>{{ tr(key + 'Hint') }}</small></button></div>
      <div class="charts">
        <section class="panel trend-panel"><header><h4>{{ tr('trend') }}</h4><div class="legend"><span><i />{{ tr('commands') }}</span><span><i class="other" />{{ tr('otherTools') }}</span></div></header>
          <div class="bars" v-if="data.totals.tools"><button v-for="bar in bars" :key="bar.at" :title="`${time(bar.at)} · ${bar.commands + bar.other}`" :aria-label="`${time(bar.at)} · ${bar.commands + bar.other}`" @click="openDetails('', '', bar.at, bar.until)"><span class="other" :style="{ height: `${bar.other / peak * 100}%` }" /><span :style="{ height: `${bar.commands / peak * 100}%` }" /></button></div>
          <a-empty v-else :description="tr('empty')" class="empty" />
          <div class="axis"><span>{{ time(data.since) }}</span><span>{{ time(data.until) }}</span></div><small>{{ tr('trendHint') }}</small>
        </section>
        <section class="panel ranking-panel"><header><h4>{{ tr('breakdown') }}</h4><a-select v-model:value="dimension" :aria-label="tr('dimension')" :options="dimensionOptions" /></header>
          <div v-if="ranks.length" class="rank-list">
          <button v-for="(rank, index) in ranks" :key="rank.name" class="rank" @click="openDetails(dimension, rank.name)"><span class="ordinal">{{ index + 1 }}</span><div><div class="rank-title"><span>{{ rankLabel(rank.name) }}</span><b>{{ rank.count.toLocaleString(locale) }}</b></div><div class="track"><i :style="{ width: `${rank.count / Math.max(...ranks.map(r => r.count), 1) * 100}%` }" /></div></div></button>
          </div>
          <a-empty v-else :description="tr('emptyHint')" class="empty" />
        </section>
      </div>
    </div>
    <a-modal v-model:open="detailVisible" :title="tr('details')" :footer="null" width="850px" @cancel="closeDetails">
      <p class="muted">{{ tr(detailScope.source) }} · {{ productName(detailScope.agent) }} · {{ time(detailScope.since) }} – {{ time(detailScope.until) }}</p>
      <a-alert v-if="detailError" type="error" :message="tr('failed')"><template #action><a-button @click="loadDetails(false)">{{ tr('retry') }}</a-button></template></a-alert>
      <div v-for="row in detailRows" :key="row.key" class="detail-row">
        <header><strong>{{ productName(row.agent) }} · {{ row.session_id || row.tool || tr('unknown') }}</strong><time>{{ time(row.at) }}</time></header>
        <p v-if="!row.session_id">{{ row.failed ? tr('reportedFailure') : tr('recorded') }}<span v-if="row.command"> · {{ row.command === 'other' ? tr('other') : row.command }}</span></p>
        <a-button v-if="row.session_id" type="link" @click="emit('activity', { source: detailScope.source, agent: row.agent, sessionId: row.session_id }); closeDetails()">{{ tr('session') }}</a-button>
        <a-button v-else type="link" :loading="entryLoading === row.key" @click="loadEntry(row)">{{ tr('view') }}</a-button>
        <a-alert v-if="entryErrors[row.key]" type="error" :message="tr('failed')" />
        <AidrTimelineEntry v-if="entries[row.key]" :item="entries[row.key]" :client-id="clientId" />
      </div>
      <a-empty v-if="!detailRows.length && !detailLoading && !detailError" :description="tr('empty')" />
      <a-spin v-if="detailLoading" /><a-button v-if="detailCursor" :loading="detailLoading" @click="loadDetails(true)">{{ tr('more') }}</a-button>
    </a-modal>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CodeOutlined, ToolOutlined, MessageOutlined, ExclamationCircleOutlined, InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { getClientAidrOverview, getClientAidrOverviewDetails, getClientAidrOverviewEntry } from '../api'
import products from '../aidr-products.json'
import { groupProductEntries } from '../aidr-product-groups'
import AidrTimelineEntry from './AidrTimelineEntry.vue'
const props = defineProps({ clientId: { type: String, required: true } }), emit = defineEmits(['activity'])
const { t, locale } = useI18n(), tr = (key, params) => t('clientOverview.' + key, params)
const source = ref('hooks'), agent = ref(''), hours = ref(24), dimension = ref('commands')
const data = ref(null), error = ref(false), loading = ref(false)
const icons = [CodeOutlined, ToolOutlined, MessageOutlined, ExclamationCircleOutlined], metricKeys = ['commands', 'tools', 'sessions', 'failures']
const agentOptions = computed(() => [{ value: '', label: tr('allAgents') }, ...groupProductEntries(products.filter(p => p.collection_visible !== false && p[source.value])).map(p => ({ value: p.id, label: p.name }))])
const rangeOptions = computed(() => [24, 168, 720].map((value, i) => ({ value, label: tr(['day', 'week', 'month'][i]) })))
const dimensionOptions = computed(() => ['commands', 'agents', 'tools'].map((value, i) => ({ value, label: tr(['commandRank', 'agentRank', 'toolRank'][i]) })))
const productName = id => !id ? tr('allAgents') : id === 'qoder' ? 'Qoder' : products.find(p => p.id === id)?.name || id
const rankLabel = value => dimension.value === 'agents' ? productName(value) : value === 'other' ? tr('other') : value
const ranks = computed(() => data.value?.rankings[dimension.value] || [])
const bars = computed(() => { const result = [], rows = data.value?.trend || []; const step = Math.max(1, Math.ceil(rows.length / 48)); for (let i = 0; i < rows.length; i += step) { const group = rows.slice(i, i + step); result.push({ at: group[0].at, until: Math.min(group.at(-1).at + 3600, data.value.until), commands: group.reduce((n, r) => n + r.commands, 0), other: group.reduce((n, r) => n + r.other, 0) }) } return result })
const peak = computed(() => Math.max(...bars.value.map(b => b.commands + b.other), 1))
const time = value => value ? new Date(value * 1000).toLocaleString(locale.value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : tr('unknown')
let sequence = 0, timer
async function load() { const request = ++sequence; clearTimeout(timer); loading.value = true; error.value = false; try { const result = await getClientAidrOverview(props.clientId, { source: source.value, agent: agent.value, hours: hours.value }); if (request !== sequence) return; data.value = result; if (result.state === 'preparing') timer = setTimeout(load, 5000) } catch { if (request === sequence) error.value = true } finally { if (request === sequence) loading.value = false } }
const detailVisible = ref(false), detailScope = ref({}), detailRows = ref([]), detailCursor = ref(''), detailError = ref(false), detailLoading = ref(false)
const entries = ref({}), entryErrors = ref({}), entryLoading = ref(''); let detailSequence = 0
function closeDetails() { detailVisible.value = false; detailSequence++; detailLoading.value = false; entryLoading.value = '' }
function openDetails(selectedDimension, value = '', since = data.value.since, until = data.value.until) { detailSequence++; detailScope.value = { source: data.value.source, agent: data.value.agent, since, until, dimension: selectedDimension, value }; detailRows.value = []; entries.value = {}; entryErrors.value = {}; detailCursor.value = ''; detailVisible.value = true; detailLoading.value = false; loadDetails(false) }
async function loadDetails(append) { if (detailLoading.value) return; const request = ++detailSequence; detailLoading.value = true; detailError.value = false; try { const result = await getClientAidrOverviewDetails(props.clientId, { ...detailScope.value, cursor: append ? detailCursor.value : '' }); if (request !== detailSequence) return; detailRows.value = append ? [...detailRows.value, ...result.items] : result.items; detailCursor.value = result.next_cursor } catch { if (request === detailSequence) detailError.value = true } finally { if (request === detailSequence) detailLoading.value = false } }
async function loadEntry(row) { if (entryLoading.value || entries.value[row.key]) return; const request = detailSequence; entryLoading.value = row.key; entryErrors.value[row.key] = false; try { const result = await getClientAidrOverviewEntry(props.clientId, { source: detailScope.value.source, record_id: row.record_id }); if (request === detailSequence) entries.value[row.key] = result } catch { if (request === detailSequence) entryErrors.value[row.key] = true } finally { if (request === detailSequence) entryLoading.value = '' } }
watch(source, () => { if (!agentOptions.value.some(option => option.value === agent.value)) agent.value = '' })
watch([() => props.clientId, source, agent, hours], () => { data.value = null; closeDetails(); load() }, { immediate: true })
onBeforeUnmount(() => { sequence++; detailSequence++; clearTimeout(timer) })
defineExpose({ refresh: load })
</script>
<style scoped>
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:18px}.select{min-width:150px}.updated{margin-left:auto;font-size:12px;color:#78889d}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid #e3e9f1;border-radius:10px;overflow:hidden;margin-bottom:18px}.metric{padding:18px 20px;background:white;border:0;border-right:1px solid #e3e9f1;text-align:left;cursor:pointer;color:#233348}.metric:last-child{border:0}.metric:hover{background:#f8faff}.metric>span{display:flex;gap:9px;align-items:center;color:#63748b}.metric .anticon{color:#285ff5;background:#edf2ff;padding:7px;border-radius:6px}.metric strong{display:block;font-size:30px;margin:8px 0;font-variant-numeric:tabular-nums}.metric small,.panel small,.muted,.axis{color:#78889d;font-size:12px}.failure strong{color:#9e6644}.charts{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(0,1fr);gap:18px}.panel{display:flex;flex-direction:column;min-height:clamp(360px,43vh,460px);border:1px solid #e3e9f1;border-radius:10px;padding:18px;min-width:0}header{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}h4{margin:0;font-size:15px}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:#78889d}.legend i{display:inline-block;width:8px;height:8px;background:#285ff5;margin-right:5px}.legend .other,.bars .other{background:#b8cdfd}.bars{flex:1;min-height:230px;display:flex;align-items:end;gap:4px;padding:15px 0 0;margin-top:15px;background:repeating-linear-gradient(to top,transparent 0,transparent 46px,#edf1f6 47px,#edf1f6 48px)}.bars button{display:flex;flex:1;flex-direction:column;justify-content:end;height:100%;padding:0;background:none;border:0;min-width:2px;cursor:pointer}.bars button span{display:block;background:#285ff5}.bars button:hover{filter:brightness(.8)}.axis{display:flex;justify-content:space-between;margin:9px 0}.rank-list{display:grid;grid-auto-rows:minmax(48px,1fr);flex:1;margin-top:12px}.rank{display:flex;gap:12px;align-items:center;width:100%;background:none;border:0;padding:12px 0;cursor:pointer;color:#233348}.rank>div{flex:1;min-width:0}.rank-title{display:flex;justify-content:space-between;gap:12px;font-size:13px;text-align:left}.rank-title span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ordinal{font-size:12px;color:#78889d}.track{height:5px;background:#f0f3f8;border-radius:5px;margin-top:6px}.track i{display:block;background:#779df8;height:100%;border-radius:5px}.rules{max-width:min(520px,80vw);line-height:1.8}.preparing{padding:24px;border:1px solid #e3e9f1;border-radius:10px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}.refreshing{opacity:.55;pointer-events:none}.detail-row{border-top:1px solid #e3e9f1;padding:15px 0;overflow-wrap:anywhere}.detail-row time{color:#78889d;font-size:12px}.detail-row p{margin:6px 0}.panel .empty{display:flex;flex:1;flex-direction:column;justify-content:center;min-height:160px}.ranking-panel :deep(.ant-select){min-width:150px;max-width:100%}button:focus-visible{outline:2px solid #285ff5;outline-offset:2px}@media(max-width:1000px){.charts{grid-template-columns:1fr}.panel{min-height:0}.bars{flex:none;height:230px}.rank-list{flex:none}.metrics{grid-template-columns:1fr 1fr}.metric:nth-child(2){border-right:0}.metric:nth-child(-n+2){border-bottom:1px solid #e3e9f1}}@media(max-width:520px){.metric{padding:13px}.metric>span{font-size:12px}.metric strong{font-size:26px}.updated{margin-left:0}.select{min-width:135px}.panel{padding:14px}}
</style>
