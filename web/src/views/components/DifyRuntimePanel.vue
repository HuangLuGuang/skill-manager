<template>
  <a-space direction="vertical" style="width:100%" size="large">
    <a-alert type="info" show-icon :message="t('difyRuntime.setup')" :description="t('difyRuntime.partial')" />
    <a-alert v-if="error" type="error" :message="error" />
    <a-space wrap>
      <a-select v-model:value="selected" style="min-width:280px" :disabled="saving || !!reviewing" :placeholder="t('difyRuntime.binding')" @change="loadStatus(true)">
        <a-select-option v-for="item in bindings" :key="item.binding_id" :value="item.binding_id">{{ item.app_id }} · {{ item.instance_id }}</a-select-option>
      </a-select>
      <a-button :loading="loading" @click="loadStatus(false)">{{ t('difyRuntime.refresh') }}</a-button>
    </a-space>
    <a-collapse>
      <a-collapse-panel key="new" :header="t('difyRuntime.newBinding')">
        <a-form layout="vertical" @finish="create">
          <a-form-item :label="t('difyRuntime.target')"><a-select v-model:value="form.target_id" :options="targets.map(x => ({ value:x.target_id, label:x.name }))" /></a-form-item>
          <a-form-item :label="t('difyRuntime.agent')"><a-select v-model:value="form.agent_id" :options="agents.map(x => ({ value:x.agent_id, label:x.name }))" /></a-form-item>
          <a-form-item :label="t('difyRuntime.instance')"><a-input v-model:value="form.instance_id" /></a-form-item>
          <a-button html-type="submit" :loading="saving" :disabled="saving">{{ t('difyRuntime.create') }}</a-button>
        </a-form>
      </a-collapse-panel>
    </a-collapse>
    <template v-if="data">
      <a-descriptions bordered :column="1">
        <a-descriptions-item :label="t('difyRuntime.bindingId')">{{ selected }}</a-descriptions-item>
        <a-descriptions-item :label="t('difyRuntime.policyVersion')">{{ data.binding.revision }}</a-descriptions-item>
      </a-descriptions>
      <a-form layout="vertical" @finish="save">
        <a-form-item :label="t('difyRuntime.mode')"><a-select v-model:value="mode">
          <a-select-option v-for="item in ['observe','enforce','disabled']" :key="item" :value="item">{{ t(`difyRuntime.${item}`) }}</a-select-option>
        </a-select></a-form-item>
        <a-form-item :label="t('difyRuntime.policy')" :extra="t('difyRuntime.policyHelp')">
          <a-textarea v-model:value="policy" :rows="12" spellcheck="false" />
        </a-form-item>
        <a-button html-type="submit" type="primary" :loading="saving" :disabled="saving">{{ t('difyRuntime.save') }}</a-button>
      </a-form>
      <h3>{{ t('difyRuntime.processes') }}</h3>
      <a-table size="small" :data-source="data.processes" row-key="process_id" :pagination="false" :scroll="{ x:700 }">
        <a-table-column :title="t('difyRuntime.process')" data-index="process_id" />
        <a-table-column :title="t('difyRuntime.status')"><template #default="{ record }">{{ t(`difyRuntime.${record.healthy ? 'healthy' : 'stale'}`) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.hooks')"><template #default="{ record }">{{ Object.entries(record.hooks).filter(([, value]) => value).map(([key]) => label('hookLabels', key)).join(', ') }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.queued')" data-index="queued_events" />
      </a-table>
      <h3>{{ t('difyRuntime.runs') }}</h3>
      <a-table size="small" :data-source="data.runs" row-key="task_id" :scroll="{ x:700 }">
        <a-table-column :title="t('difyRuntime.run')" data-index="run_id" />
        <a-table-column :title="t('difyRuntime.version')" data-index="graph_digest" />
        <a-table-column :title="t('difyRuntime.trace')"><template #default="{ record }"><router-link :to="{path:'/runtime-traces',query:{trace_id:record.trace_id}}">{{ t('difyRuntime.trace') }}</router-link></template></a-table-column>
      </a-table>
      <h3>{{ t('difyRuntime.calls') }}</h3>
      <a-table size="small" :data-source="data.calls" row-key="action_id" :scroll="{ x:900 }">
        <a-table-column :title="t('difyRuntime.node')" data-index="node_id" />
        <a-table-column :title="t('difyRuntime.type')"><template #default="{ record }">{{ label('nodeLabels', record.node_type) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.status')"><template #default="{ record }">{{ t(`difyRuntime.${record.status}`) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.reason')"><template #default="{ record }">{{ record.reasons.map(reason => label('reasonLabels', reason)).join(', ') }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.approval')"><template #default="{ record }">
          <a-space v-if="record.approval_status === 'pending'" wrap>
            <a-button :loading="reviewing === record.action_id" :disabled="!!reviewing" @click="review(record.action_id,true)">{{ t('difyRuntime.approve') }}</a-button>
            <a-button danger :disabled="!!reviewing" @click="review(record.action_id,false)">{{ t('difyRuntime.reject') }}</a-button>
          </a-space>
          <span v-else>{{ t(`difyRuntime.${record.approval_status}`) }}</span>
        </template></a-table-column>
      </a-table>
    </template>
  </a-space>
</template>
<script setup>
import { onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { listDifyRuntimeBindings, createDifyRuntimeBinding, updateDifyRuntimeBinding, getDifyRuntimeStatus, reviewDifyRuntimeCall, listSecurityTargets, listAgents } from '../../api'
const { t, te } = useI18n()
function label(group, value) {
  const key = `difyRuntime.${group}.${value}`
  return te(key) ? t(key) : value
}
const bindings=ref([]), targets=ref([]), agents=ref([]), selected=ref(), data=ref(), mode=ref('observe'), policy=ref('')
const loading=ref(false), saving=ref(false), reviewing=ref(''), error=ref('')
const form=reactive({ target_id:undefined, agent_id:undefined, instance_id:'' })
let generation=0
function failed(e) { error.value=e.response?.data?.detail || e.message }
async function loadStatus(reset) {
  if (!selected.value) return
  const ticket=++generation
  loading.value=true
  try {
    const response=await getDifyRuntimeStatus(selected.value)
    if (ticket !== generation) return
    data.value=response.data
    if (reset) { mode.value=data.value.binding.mode; policy.value=JSON.stringify(data.value.binding.policy,null,2) }
  } catch(e) { if(ticket===generation) failed(e) }
  finally { if(ticket===generation) loading.value=false }
}
async function create() {
  if(saving.value) return
  if(!form.target_id || !form.agent_id || !form.instance_id.trim()) return message.warning(t('difyRuntime.required'))
  saving.value=true; error.value=''
  try {
    const response=await createDifyRuntimeBinding(form)
    bindings.value=(await listDifyRuntimeBindings()).data.items
    selected.value=response.data.binding_id
    await loadStatus(true)
  } catch(e) { failed(e) } finally { saving.value=false }
}
async function save() {
  if(saving.value) return
  let parsed
  try { parsed=JSON.parse(policy.value) } catch { return message.error(t('difyRuntime.invalid')) }
  saving.value=true; error.value=''
  try {
    await updateDifyRuntimeBinding(selected.value,{ revision:data.value.binding.revision,mode:mode.value,policy:parsed })
    await loadStatus(false); message.success(t('difyRuntime.saved'))
  } catch(e) { failed(e) } finally { saving.value=false }
}
async function review(id, approve) {
  if(reviewing.value) return
  reviewing.value=id
  try { await reviewDifyRuntimeCall(id,approve); await loadStatus(false) }
  catch(e) { failed(e) } finally { reviewing.value='' }
}
onMounted(async () => {
  try {
    const [b,tg,ag]=await Promise.all([listDifyRuntimeBindings(),listSecurityTargets(),listAgents()])
    bindings.value=b.data.items
    targets.value=(tg.data.items || tg.data).filter(x=>x.connector_type==='dify')
    agents.value=ag.data.items || ag.data
    if(bindings.value.length) { selected.value=bindings.value[0].binding_id; await loadStatus(true) }
  } catch(e) { failed(e) }
})
onBeforeUnmount(()=>{ generation++ })
</script>
