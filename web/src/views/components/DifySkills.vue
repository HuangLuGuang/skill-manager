<template>
  <p class="scope">{{ t('difyRuntime.skills.help') }}</p>
  <a-alert v-if="error" type="error" :message="error"><template #action><a-button @click="load">{{ t('difyRuntime.refresh') }}</a-button></template></a-alert>
  <a-table size="small" :loading="loading" :data-source="items" :row-key="row => `${row.dify_agent_id}:${row.archive_hash}`" :scroll="{x:900}" :pagination="{current:page,pageSize,total,showSizeChanger:true}" @change="changePage">
    <a-table-column :title="t('difyRuntime.skills.name')" data-index="name" />
    <a-table-column :title="t('difyRuntime.skills.agent')" data-index="dify_agent_id" :ellipsis="true" />
    <a-table-column :title="t('difyRuntime.skills.status')"><template #default="{record}"><a-tag :color="['APPROVED','DEPLOYED'].includes(record.status) ? 'green' : record.status === 'REJECTED' ? 'red' : 'orange'">{{ t(`difyRuntime.skills.states.${record.status}`) }}</a-tag></template></a-table-column>
    <a-table-column :title="t('difyRuntime.skills.risk')"><template #default="{record}">{{ record.risk_level ? t(`difyRuntime.skills.risks.${record.risk_level}`) : '—' }}</template></a-table-column>
    <a-table-column :title="t('difyRuntime.skills.content')"><template #default="{record}"><a-tooltip :title="record.archive_hash"><code>{{ record.archive_hash.slice(0,12) }}</code></a-tooltip></template></a-table-column>
    <a-table-column :title="t('difyRuntime.skills.seen')"><template #default="{record}">{{ formatBeijingDateTime(record.seen_at) }}</template></a-table-column>
    <a-table-column :title="t('difyRuntime.skills.report')"><template #default="{record}"><router-link v-if="hasAccess('skills:view')" :to="`/skills/${record.version_id}`">{{ t('difyRuntime.skills.viewReport') }}</router-link><span v-else>—</span></template></a-table-column>
  </a-table>
</template>
<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
import {useI18n} from 'vue-i18n'
import {listDifyRuntimeSkills} from '../../api'
import {can as hasAccess} from '../../access'
import {formatBeijingDateTime} from '../../utils/format'
const props=defineProps({bindingId:{type:String,required:true},refreshKey:Number})
const {t}=useI18n(),items=ref([]),loading=ref(false),error=ref('')
const page=ref(1),pageSize=ref(10),total=ref(0)
let generation=0
async function load(){
  const ticket=++generation
  loading.value=true;error.value=''
  try{const result=await listDifyRuntimeSkills(props.bindingId,{page:page.value,page_size:pageSize.value});if(ticket===generation){items.value=result.items;total.value=result.total}}
  catch(e){if(ticket===generation)error.value=e.response?.data?.detail || e.message}
  finally{if(ticket===generation)loading.value=false}
}
function changePage(pagination){page.value=pagination.current;pageSize.value=pagination.pageSize;load()}
watch(()=>props.bindingId,()=>{page.value=1;items.value=[];load()},{immediate:true})
watch(()=>props.refreshKey,load)
onBeforeUnmount(()=>generation++)
</script>
<style scoped>.scope{font-size:12px;color:#64748b;margin:0 0 16px}</style>
