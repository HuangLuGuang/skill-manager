<template>
  <section class="risk-overview" :aria-busy="loading">

    <a-alert v-if="error" type="error" show-icon :message="tr('failed')"><template #action><a-button @click="load">{{ tr('retry') }}</a-button></template></a-alert>
    <a-skeleton v-else-if="!data && loading" active />
    <template v-else-if="data">
      <a-alert v-if="data.score.state !== 'ready'" type="warning" show-icon :message="tr(data.score.state)" />
      <div class="metrics">
        <button @click="scoreOpen = true"><span>{{ tr('score') }} <InfoCircleOutlined /></span><strong>{{ data.score.value ?? '—' }}</strong><small>{{ data.score.value == null ? tr('unavailable') : tr('outOf', { level: tr(data.score.value >= 60 ? 'highLevel' : data.score.value >= 30 ? 'medium' : 'low') }) }}</small></button>
        <button @click="open({ disposition: 'open' }, tr('open'))"><span>{{ tr('open') }}</span><strong>{{ data.open }}</strong><small>{{ tr('stock') }}</small></button>
        <button @click="open({ disposition: 'open', severity: 'high' }, tr('high'))"><span>{{ tr('high') }}</span><strong class="high">{{ data.high_open }}</strong><small>{{ tr('stock') }}</small></button>
        <button @click="open({ detected_since: data.since, detected_before: data.before }, tr('new'))"><span>{{ tr('new') }}</span><strong>{{ data.total }}</strong><small>{{ tr('detected') }}</small></button>
      </div>
      <div class="charts" :class="{ scoped: fixedAgent }">
        <section v-for="key in chartKeys" :key="key" class="panel">
          <header><h4>{{ tr(key) }}</h4><span v-if="key === 'types'">{{ tr('total', { count: data.total }) }}</span></header>
          <p v-if="key === 'dispositions'" class="muted">{{ tr('stateScope') }}</p>
          <Chart v-if="data.total" :options="options[key]" :navigation-label="t('overviewTabs.chartKeyboard', { name: tr(key) })" :height="['agents','types'].includes(key) ? `${Math.max(220, data[key].length * 34 + 65)}px` : '220px'" @select="value => chartClick(key, value.dataIndex)" />
          <a-empty v-else :description="tr('empty')" />
          <div v-if="key === 'dispositions' && data.total" class="disposition-legend"><button v-for="(row,index) in chartRows(key)" :key="row.key" @click="chartClick(key,index)"><span><i :style="{ background: dispositionColors[index] }" />{{ rowLabel(key,row) }}</span><b>{{ row.count }} <small>{{ Math.round(row.count / data.total * 100) }}%</small></b></button></div>
        </section>
      </div>
      <footer v-if="!fixedAgent">{{ tr('retained') }}</footer>
    </template>
    <a-modal v-model:open="scoreOpen" :title="tr('scoreHelp')" :footer="null" width="620px">
      <template v-if="data"><p>{{ tr('basis') }}</p><div class="formula"><p>{{ tr('formula') }}</p><p>{{ tr('weights') }}</p><strong>{{ tr('contribution', data.score) }}</strong></div><p>{{ tr('thresholds') }}</p><p>{{ tr('rule') }}</p><p class="muted">{{ fixedAgent ? t('agentWorkspace.scoreCalibration') : tr('calibration') }}</p><a-button type="link" @click="scoreOpen=false;open({ disposition:'open' },tr('open'))">{{ tr('contributionLink') }}</a-button></template>
    </a-modal>
    <a-modal v-model:open="detailsOpen" :title="detailTitle" :footer="null" width="1100px" @cancel="load">
      <ClientAidrRisks v-if="detailsOpen" :client-id="clientId" :initial-filters="detailFilters" :fixed-agent="fixedAgent" @changed="load" />
    </a-modal>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { InfoCircleOutlined } from '@ant-design/icons-vue'
import Chart from './Chart.vue'
import ClientAidrRisks from './ClientAidrRisks.vue'
import products from '../aidr-products.json'
import { getClientAidrRiskOverview } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, period: { type: Object, required: true }, fixedAgent: { type: String, default: '' }, navigate: Boolean })
const { t, locale } = useI18n(), tr = (key, values) => t('riskOverview.' + key, values)
const data = ref(null), loading = ref(false), error = ref(false), scoreOpen = ref(false), detailsOpen = ref(false), detailTitle = ref(''), detailFilters = ref({})
const emit = defineEmits(['risks'])
const chartKeys = computed(() => props.fixedAgent ? ['trend','types','dispositions'] : ['trend','types','agents','dispositions'])
const colors = ['#d96b6b','#e6b35e'], states = ['open','resolved','accepted','false_positive']
const dispositionColors = ['#e6b35e','#7eac91','#759bcf','#afb8c4']
let generation = 0
async function load() {
  const id = ++generation; loading.value = true; error.value = false
  try { const result = await getClientAidrRiskOverview(props.clientId, { ...props.period, agent: props.fixedAgent, offset_minutes: -new Date().getTimezoneOffset() }); if (id === generation) data.value = result }
  catch { if (id === generation) error.value = true }
  finally { if (id === generation) loading.value = false }
}
function open(filters, title) { if (props.navigate) { emit('risks', filters); return }; detailFilters.value = filters; detailTitle.value = title; detailsOpen.value = true }
function chartRows(key) { return key === 'dispositions' ? states.map(key => ({ key, count: data.value.dispositions.find(r => r.key === key)?.count || 0 })) : data.value[key] }
function rowLabel(key, row) {
  if (key === 'trend') return row.day
  if (key === 'types') return t('aidrRisk.codes.' + row.key)
  if (key === 'dispositions') return t('aidrRisk.disposition.states.' + row.key)
  return products.find(p => p.id === row.key)?.name || row.key || t('aidrRisk.unknown')
}
function chartClick(key, index) {
  const row = chartRows(key)[index]; if (!row) return
  const filters = { detected_since: data.value.since, detected_before: data.value.before }
  if (key === 'trend') { filters.detected_since = row.since; filters.detected_before = row.before }
  if (key === 'types') filters.risk_code = row.key
  if (key === 'agents') { if (row.key) filters.agent = row.key; else filters.unknown_agent = true }
  if (key === 'dispositions') filters.disposition = row.key
  open(filters, `${tr(key)} · ${rowLabel(key,row)}`)
}
const options = computed(() => {
  if (!data.value) return {}
  const high = t('aidrRisk.severity.high'), medium = t('aidrRisk.severity.medium')
  const common = { color: colors, tooltip: { trigger: 'axis', renderMode: 'richText', confine: true }, aria: { enabled: true, label: { description: tr('scope') } }, grid: { left: 8, right: 34, top: 26, bottom: 18, containLabel: true } }
  const numeric = { type:'value', minInterval:1, name:tr('unit'), nameLocation:'end', splitLine:{ lineStyle:{ color:'#edf0f4' } } }
  const result = {}
  result.trend = { ...common, legend:{ data:[high,medium], top:0 }, xAxis:{ type:'category', data:data.value.trend.map(r=>r.day.slice(5)) }, yAxis:numeric,
    series:['high','medium'].map((key,i)=>({ name:[high,medium][i], type:'bar', stack:'risk', barMaxWidth:32, data:data.value.trend.map(r=>r[key]) })) }
  for (const key of ['types','agents']) {
    const rows = chartRows(key)
    result[key] = { ...common, xAxis:{ ...numeric, name:'' }, yAxis:{ type:'category', inverse:true, data:rows.map(r=>rowLabel(key,r)), axisLabel:{ width:125, overflow:'truncate' } },
      series:key === 'types' ? [{ type:'bar', barWidth:22, itemStyle:{ color:'#759bcf' }, label:{ show:true, position:'right' }, data:rows.map(r=>r.count) }] : ['high','medium'].map((field,i)=>({ name:[high,medium][i], type:'bar', stack:'risk', barWidth:22, label:{ show:i===1, position:'right', formatter:p=>rows[p.dataIndex].high+rows[p.dataIndex].medium }, data:rows.map(r=>r[field]) })) }
    if (key === 'agents') result[key].legend = { data:[high,medium], top:0 }
  }
  result.dispositions = { color:dispositionColors, aria:{ enabled:true, label:{ description:tr('stateScope') } }, tooltip:{ trigger:'item', renderMode:'richText', confine:true },
    title:{ text:String(data.value.total), subtext:tr('unit'), left:'center', top:'32%', textStyle:{ fontSize:27 } },
    series:[{ type:'pie', radius:['48%','68%'], center:['50%','43%'], label:{ show:false }, data:chartRows('dispositions').map(r=>({ name:rowLabel('dispositions',r), value:r.count })) }] }
  return result
})
watch([() => props.clientId, () => props.fixedAgent, () => props.period], () => { data.value = null; detailsOpen.value = false; scoreOpen.value = false; load() }, { immediate:true })
watch(locale, () => { if (detailsOpen.value) detailTitle.value = tr('details') })
onBeforeUnmount(() => { generation++ })
defineExpose({ refresh:load })
</script>
<style scoped>
.disposition-legend{display:grid;grid-template-columns:1fr 1fr;gap:8px 16px}.disposition-legend button{display:flex;justify-content:space-between;align-items:center;gap:10px;background:none;border:0;padding:4px 0;text-align:left;cursor:pointer;color:inherit}.disposition-legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px}.disposition-legend small{color:#78889d;font-weight:400;margin-left:5px}.disposition-legend b{white-space:nowrap}.risk-overview{min-width:0}header,.scope{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}h3,h4{margin:0}h3{font-size:16px}h4{font-size:14px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin:12px 0}.metrics button{background:none;border:0;border-left:1px solid #edf0f4;text-align:left;padding:0 18px;color:inherit;cursor:pointer}.metrics button:first-child{border:0;padding-left:0}.metrics button>span,.metrics small{display:block;color:#78889d}.metrics strong{display:block;font-size:32px;line-height:1.6;font-variant-numeric:tabular-nums}.metrics .high{color:#cf4141}.scope{margin-bottom:16px;color:#78889d}.scope .ant-select{min-width:160px}.charts{display:grid;grid-template-columns:1.2fr 1fr;gap:12px}.charts.scoped .panel:first-child{grid-column:1/-1}.panel{min-width:0;border:1px solid #edf0f4;border-radius:6px;padding:14px}.muted,footer,header>span{color:#78889d;font-size:12px}.muted{margin:8px 0}footer{margin-top:16px}.formula{padding:14px;background:#f7f9fc;border-radius:6px}.ant-alert{margin-top:14px}button:focus-visible{outline:2px solid #1677ff;outline-offset:3px}@media(max-width:900px){.charts{grid-template-columns:1fr}}@media(max-width:540px){.disposition-legend{grid-template-columns:1fr}.risk-overview{padding:0}.metrics{grid-template-columns:1fr 1fr;gap:18px}.metrics button{padding:0 12px}.metrics button:nth-child(3){padding-left:0;border-left:0}.metrics span{font-size:12px}.metrics strong{font-size:28px}}
</style>
