<template>
  <a-tabs v-model:active-key="activeTab" class="agent-overview">
    <template #rightExtra><slot name="period" /></template>
    <a-tab-pane key="assets" :tab="t('overviewTabs.assets')">
      <p class="muted">{{ tr('snapshotScope') }}</p>
      <div class="metrics">
        <button v-for="row in assets" :key="row.key" @click="openAsset(row.key)"><span>{{ row.label }}</span><strong>{{ row.count ?? '—' }}</strong><small>{{ row.count == null ? t('localAssets.unreported') : t('overviewTabs.snapshot') }}</small></button>
        <button @click="emit('configure')"><span>{{ tr('configuredModel') }}</span><strong class="model">{{ agent?.capabilities?.model_config_state?.model || tr('modelNoReport') }}</strong><small>{{ t('overviewTabs.snapshot') }}</small></button>
      </div>
      <div class="charts">
        <section class="panel"><h4>{{ tr('assetDistribution') }}</h4><Chart v-if="assets.some(row => row.count > 0)" :options="assetChart" height="240px" :navigation-label="t('overviewTabs.chartKeyboard',{name:tr('assetDistribution')})" @select="value => openAsset(assets[value.dataIndex].key)" /><a-empty v-else :description="tr('empty')" /></section>
        <section class="panel"><div class="panel-heading"><h4>{{ tr('installation') }}</h4><a-button type="link" @click="emit('evidence')">{{ tr('evidence') }}</a-button></div><dl><template v-for="row in metadata" :key="row.key"><dt>{{ tr(row.key) }}</dt><dd>{{ row.value || tr('unknown') }}</dd></template></dl></section>
      </div>
    </a-tab-pane>
    <a-tab-pane key="activity" :tab="t('overviewTabs.activity')"><p class="muted">{{ tr('riskScope',{product:name}) }}</p><ClientOverviewStatistics :client-id="clientId" :fixed-agent="product" :period="period" @activity="emit('activity',$event)" /></a-tab-pane>
    <a-tab-pane key="risks" :tab="t('overviewTabs.risks')"><p class="muted">{{ tr('riskScope',{product:name}) }}</p><ClientRiskOverview :client-id="clientId" :fixed-agent="product" :period="period" navigate @risks="emit('risks',$event)" /></a-tab-pane>
  </a-tabs>
  <a-modal v-model:open="assetOpen" :title="t('localAssets.title')" :footer="null" width="950px"><AgentLocalAssets :key="assetTab" :initial-tab="assetTab" :inventory="agent?.asset_inventory" :skills="agent?.skills || []" /></a-modal>
</template>
<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Chart from './Chart.vue'
import AgentLocalAssets from './AgentLocalAssets.vue'
import ClientOverviewStatistics from './ClientOverviewStatistics.vue'
import ClientRiskOverview from './ClientRiskOverview.vue'
const props = defineProps({clientId:String, product:String, name:String, agent:Object, period:Object})
const emit = defineEmits(['activity','risks','configure','evidence'])
const {t} = useI18n(), tr = (key,params) => t('agentWorkspace.'+key,params)
const activeTab = ref('assets'), assetOpen = ref(false), assetTab = ref('skills')
const inventory = computed(() => props.agent?.asset_inventory)
const assets = computed(() => [
  {key:'skills',label:t('localAssets.skills'),count:props.agent ? props.agent.skills?.length ?? 0 : null},
  {key:'mcp',label:t('localAssets.mcp'),count:inventory.value && (inventory.value.mcp_supported || inventory.value.plugins?.some(p=>p.mcp_servers?.length)) ? (inventory.value.mcp_servers?.length || 0)+(inventory.value.plugins || []).reduce((n,p)=>n+(p.mcp_servers?.length || 0),0) : null},
  {key:'plugins',label:t('localAssets.plugins'),count:inventory.value?.plugin_supported ? inventory.value.plugins?.length || 0 : null},
])
const metadata = computed(() => ['localId','version','path','skillsPath'].map((key,i)=>({key,value:props.agent?.[['local_agent_id','version','install_path','skills_path'][i]]})))
const assetChart = computed(() => ({tooltip:{trigger:'axis',renderMode:'richText',confine:true},grid:{left:8,right:35,top:20,bottom:20,containLabel:true},xAxis:{type:'value',minInterval:1},yAxis:{type:'category',inverse:true,data:assets.value.map(r=>r.label)},series:[{type:'bar',barWidth:24,itemStyle:{color:'#759bcf'},label:{show:true,position:'right'},data:assets.value.map(r=>r.count)}]}))
function openAsset(key) {assetTab.value=key;assetOpen.value=true}
</script>
<style scoped>
.panel-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.panel-heading h4{margin:0}.muted,small,dt{color:#78889d;font-size:12px}.muted{margin:0 0 12px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}.metrics button{padding:12px;text-align:left;border:1px solid #edf0f4;background:white;border-radius:6px;cursor:pointer;color:inherit;min-width:0}.metrics strong{display:block;font-size:30px;line-height:1.8;overflow-wrap:anywhere}.metrics .model{font-size:18px;min-height:54px;display:flex;align-items:center}.metrics small{display:block}.charts{display:grid;grid-template-columns:1.2fr 1fr;gap:12px}.panel{min-width:0;padding:14px;border:1px solid #edf0f4;border-radius:6px}h4{margin:0 0 12px}dl{display:grid;grid-template-columns:100px minmax(0,1fr);gap:16px 12px;margin:20px 0}dd{margin:0;overflow-wrap:anywhere}button:focus-visible{outline:2px solid #1677ff}@media(max-width:900px){.charts{grid-template-columns:1fr}}@media(max-width:540px){.metrics{grid-template-columns:1fr 1fr}dl{grid-template-columns:80px minmax(0,1fr)}}
.agent-overview :deep(.ant-tabs-nav-wrap){min-width:0}.agent-overview :deep(.ant-tabs-nav){gap:8px}@media(max-width:760px){.agent-overview :deep(.ant-tabs-nav){flex-wrap:wrap}.agent-overview :deep(.ant-tabs-extra-content){width:100%;padding-bottom:8px}}
</style>
