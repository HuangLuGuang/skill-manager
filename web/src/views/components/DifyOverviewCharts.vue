<template>
  <div class="overview-charts">
    <section class="chart-panel trend">
      <header><div><h3>{{ t('difyRuntime.charts.trend') }}</h3><p>{{ t('difyRuntime.charts.trendScope') }}</p></div></header>
      <Chart v-if="runs.length" :options="trendOptions" height="260px" :navigation-label="t('difyRuntime.charts.trend')" />
      <a-empty v-else :description="t('difyRuntime.noRuns')" />
    </section>
    <section class="chart-panel">
      <header><h3>{{ t('difyRuntime.charts.results') }}</h3><span>{{ t('difyRuntime.charts.runCount', { count:runs.length }) }}</span></header>
      <Chart v-if="runs.length" :options="resultOptions" height="280px" :navigation-label="t('difyRuntime.charts.results')" />
      <a-empty v-else :description="t('difyRuntime.noRuns')" />
    </section>
    <section class="chart-panel">
      <header><h3>{{ t('difyRuntime.charts.calls') }}</h3><span>{{ t('difyRuntime.charts.callCount', { count:calls.length }) }}</span></header>
      <Chart v-if="calls.length" :options="callOptions" height="280px" :navigation-label="t('difyRuntime.charts.calls')" />
      <a-empty v-else :description="t('difyRuntime.charts.noCalls')" />
    </section>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import Chart from '../../components/Chart.vue'
dayjs.extend(utc)
const props=defineProps({ runs:{type:Array,required:true}, calls:{type:Array,required:true} })
const {t,te}=useI18n()
const colors=['#34b38a','#ed7378','#6495ed']
const resultKeys=['succeeded','failed','other']
const resultKey=status=>['succeeded','failed'].includes(status) ? status : 'other'
const label=key=>key==='other' ? t('difyRuntime.charts.other') : t(`difyRuntime.${key}`)
const tooltip={trigger:'axis',renderMode:'richText',confine:true}
const axis={type:'value',minInterval:1,splitLine:{lineStyle:{color:'#edf1f6'}},axisLabel:{color:'#7b8799'}}
const trendOptions=computed(()=>{
  // Read the current day on every data refresh, using the same UTC+8 boundary as audit timestamps.
  const days=Array.from({length:7},(_,i)=>dayjs.utc().utcOffset(480).subtract(6-i,'day').format('YYYY-MM-DD'))
  const counts=Object.fromEntries(days.map(day=>[day,{succeeded:0,failed:0,other:0}]))
  for(const run of props.runs){
    if(!run.created_at) continue
    const day=dayjs.utc(run.created_at).utcOffset(480).format('YYYY-MM-DD')
    if(counts[day]) counts[day][resultKey(run.status)]++
  }
  return {color:colors,tooltip,legend:{bottom:0,icon:'circle'},grid:{left:38,right:16,top:20,bottom:62,containLabel:true},xAxis:{type:'category',data:days,axisLabel:{formatter:value=>value.slice(5),color:'#7b8799'},axisTick:{show:false}},yAxis:axis,
    series:resultKeys.map(key=>({name:label(key),type:'bar',stack:'runs',barMaxWidth:36,data:days.map(day=>counts[day][key])}))}
})
const resultOptions=computed(()=>({color:colors,tooltip:{trigger:'item',renderMode:'richText',confine:true},legend:{bottom:0,icon:'circle'},series:[{name:t('difyRuntime.charts.results'),type:'pie',radius:['46%','66%'],center:['50%','43%'],avoidLabelOverlap:true,label:{show:false},emphasis:{label:{show:true,formatter:'{b}\n{c} ({d}%)',fontSize:13}},data:resultKeys.map((key,index)=>({name:label(key),itemStyle:{color:colors[index]},value:props.runs.filter(run=>resultKey(run.status)===key).length})).filter(item=>item.value)}]}))
const callOptions=computed(()=>{
  const counts=new Map()
  for(const call of props.calls){const key=call.node_type || 'unknown';counts.set(key,(counts.get(key)||0)+1)}
  const rows=[...counts].sort((a,b)=>b[1]-a[1])
  const nodeLabel=key=>te(`difyRuntime.nodeLabels.${key}`) ? t(`difyRuntime.nodeLabels.${key}`) : key==='unknown' ? t('difyRuntime.charts.unknown') : key
  return {color:['#6495ed'],tooltip,grid:{left:12,right:40,top:12,bottom:20,containLabel:true},xAxis:axis,yAxis:{type:'category',inverse:true,data:rows.map(([key])=>nodeLabel(key)),axisTick:{show:false},axisLine:{show:false},axisLabel:{color:'#64748b',width:110,overflow:'truncate'}},series:[{name:t('difyRuntime.charts.calls'),type:'bar',barMaxWidth:24,label:{show:true,position:'right',color:'#64748b'},itemStyle:{borderRadius:[0,4,4,0]},data:rows.map(([,count])=>count)}]}
})
</script>
<style scoped>
.overview-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:16px 0}.chart-panel{min-width:0;background:#fff;border:1px solid #e5eaf1;border-radius:10px;padding:18px 20px}.trend{grid-column:1/-1}header{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;margin-bottom:8px}h3{font-size:14px;font-weight:600;margin:0}p,header>span{font-size:12px;color:#7b8799;margin:6px 0 0}.ant-empty{margin:54px 0}@media(max-width:760px){.overview-charts{grid-template-columns:minmax(0,1fr)}.chart-panel{padding:16px 12px}}
</style>
