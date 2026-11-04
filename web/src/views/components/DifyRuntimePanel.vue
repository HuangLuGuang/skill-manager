<template>
  <section class="dify-workspace">
    <div class="workspace-breadcrumb"><a-button type="link" @click="$emit('back')">← {{ t('difyRuntime.back') }}</a-button><span>/</span><span>Dify</span></div>
    <header class="workspace-heading">
      <div class="identity"><span class="product-logo"><DeploymentUnitOutlined /></span><div><h1>{{ asset.name }}</h1><span class="muted">Dify · {{ agentId }}</span></div></div>
      <a-space wrap><a-button v-if="hasAccess('agents:update')" @click="$emit('edit')">{{ t('agentAssets.edit') }}</a-button><a-button :loading="loading" @click="loadStatus(false)">{{ t('difyRuntime.refresh') }}</a-button></a-space>
    </header>
    <a-tabs v-model:activeKey="tab" class="workspace-tabs">
      <a-tab-pane key="overview" :tab="t('difyRuntime.overview')" />
      <a-tab-pane v-if="hasAccess('runtime:view') && hasAccess('traces:view')" key="audit" :tab="t('difyRuntime.audit')" />
      <a-tab-pane v-if="hasAccess('runtime:view')" key="skills" :tab="t('difyRuntime.skills.title')" />
      <a-tab-pane v-if="hasAccess('runtime:view')" key="policy" :tab="t('difyRuntime.controls')" />
      <a-tab-pane v-if="hasAccess('runtime:view')" key="connection" :tab="t('difyRuntime.connection')" />
    </a-tabs>
    <div class="workspace-body" :class="{ 'audit-body': tab === 'audit' }">
    <a-alert v-if="!hasAccess('runtime:view')" type="info" :message="t('difyRuntime.noRuntimeAccess')" />
    <a-skeleton v-if="loading && !data" active />
    <a-alert v-if="error" type="error" :message="error" />
    <template v-if="data">
      <template v-if="tab === 'overview'">
        <p class="muted">{{ t('difyRuntime.overviewScope') }}</p>
        <div class="overview-stats">
          <a-statistic :title="t('difyRuntime.succeeded')" :value="data.runs.filter(r=>r.status==='succeeded').length" />
          <a-statistic :title="t('difyRuntime.failed')" :value="data.runs.filter(r=>r.status==='failed').length" />
          <a-statistic :title="t('difyRuntime.blockedCalls')" :value="data.calls.filter(c=>c.status==='blocked').length" />
          <a-statistic :title="t('difyRuntime.pending')" :value="data.calls.filter(c=>c.approval_status==='pending').length" />
          <a-statistic :title="t('difyRuntime.onlineProcesses')" :value="data.processes.filter(p=>p.healthy).length" />
        </div>
        <p v-if="data.runs.length" class="muted">{{ t('difyRuntime.latestRun') }} · {{ formatBeijingDateTime(data.runs[0].created_at) }}</p>
        <DifyOverviewCharts :runs="data.runs" :calls="data.calls" />
      </template>
      <template v-if="tab === 'overview' || tab === 'connection'">
      <a-descriptions class="identity-panel" size="small" :column="{ xs:1, sm:1, md:2 }">
        <a-descriptions-item :label="t('difyRuntime.bindingId')">{{ selected }}</a-descriptions-item>
        <a-descriptions-item v-for="field in ['instance_id','workspace_id','app_id']" :key="field" :label="t(`difyRuntime.${field}`)">{{ data.binding[field] }}</a-descriptions-item>
        <a-descriptions-item :label="t('difyRuntime.credentialOwner')">{{ data.binding.owner_group_id != null ? t('difyRuntime.groupOwner', { id: data.binding.owner_group_id }) : t('difyRuntime.userOwner', { id: data.binding.owner_user_id }) }}</a-descriptions-item>
        <a-descriptions-item :label="t('difyRuntime.status')">{{ t(`difyRuntime.${!data.processes.length ? 'awaitingConnection' : data.processes.some(p => p.healthy) ? 'healthy' : 'stale'}`) }}</a-descriptions-item>
        <a-descriptions-item :label="t('difyRuntime.policyVersion')">{{ data.binding.revision }}</a-descriptions-item>
        <a-descriptions-item v-if="tab === 'overview'" :label="t('difyRuntime.mode')">{{ t(`difyRuntime.${data.binding.mode}`) }}</a-descriptions-item>
        <a-descriptions-item v-if="tab === 'overview'" :label="t('difyRuntime.rules')">{{ data.binding.policy.rules.length }}</a-descriptions-item>
        <a-descriptions-item v-if="tab === 'overview'" :label="t('difyRuntime.defaultDecision')">{{ t(`difyRuntime.${data.binding.policy.default}`) }}</a-descriptions-item>
      </a-descriptions>
      <p v-if="tab === 'overview'" class="muted">{{ t('difyRuntime.partial') }}</p>
      <a-button v-if="tab === 'overview' && hasAccess('traces:view')" @click="tab = 'audit'">{{ t('difyRuntime.audit') }} · {{ data.runs.length }}</a-button>
      </template>
      <DifyBehaviorAudit v-if="tab === 'audit' && hasAccess('traces:view')" :runs="data.runs" :calls="data.calls" :reviewing="reviewing" :refresh-key="auditRefresh" @review="review" />
      <DifySkills v-if="tab === 'skills'" :binding-id="selected" :refresh-key="auditRefresh" />
      <template v-if="tab === 'connection'">
      <a-alert type="info" show-icon :message="t('difyRuntime.setup')" />
      <a-space wrap>
        <router-link v-if="hasAccess('credentials:view')" to="/credentials">{{ t('difyRuntime.credentials') }}</router-link>
        <a-button @click="downloadConfig">{{ t('difyRuntime.downloadConfig') }}</a-button>
      </a-space>
      <a-collapse>
        <a-collapse-panel key="install" :header="t('difyRuntime.install')">
          <p>{{ t('difyRuntime.installHelp') }}</p>
          <pre class="install-command">python3 integrations/dify-runtime/install.py --compose /srv/dify/docker/docker-compose.yaml --project dify --config /secure/config.json --credentials /secure/credentials.json --output /srv/dify/agent-manager-adapter</pre>
          <p>{{ t('difyRuntime.credentialsFile') }}</p>
          <pre class="install-command">{{ JSON.stringify({ [selected]: t('difyRuntime.tokenPlaceholder') }, null, 2) }}</pre>
        </a-collapse-panel>
      </a-collapse>
      <h3>{{ t('difyRuntime.processes') }}</h3>
      <a-table size="small" :data-source="data.processes" row-key="process_id" :pagination="false" :scroll="{ x:700 }">
        <a-table-column :title="t('difyRuntime.process')" data-index="process_id" />
        <a-table-column :title="t('difyRuntime.status')"><template #default="{ record }">{{ t(`difyRuntime.${record.healthy ? 'healthy' : 'stale'}`) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.hooks')"><template #default="{ record }">{{ Object.entries(record.hooks).filter(([, value]) => value).map(([key]) => label('hookLabels', key)).join(', ') }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.queued')" data-index="queued_events" />
      </a-table>
      </template>
      <template v-if="tab === 'policy'">
      <DifyPolicyForm v-model="policy" v-model:mode="mode" :disabled="!hasAccess('runtime:update') || saving" :saving="saving" :graphs="[...new Set(data.runs.map(run => run.graph_digest))]" @save="save" />
      <h3>{{ t('difyRuntime.pending') }}</h3>
      <a-table size="small" :data-source="data.calls.filter(call => call.approval_status === 'pending')" row-key="action_id" :scroll="{ x:900 }">
        <a-table-column :title="t('difyRuntime.node')" data-index="node_id" />
        <a-table-column :title="t('difyRuntime.type')"><template #default="{ record }">{{ label('nodeLabels', record.node_type) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.status')"><template #default="{ record }">{{ t(`difyRuntime.${record.status}`) }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.reason')"><template #default="{ record }">{{ record.reasons.map(reason => label('reasonLabels', reason)).join(', ') }}</template></a-table-column>
        <a-table-column :title="t('difyRuntime.approval')"><template #default="{ record }">
          <a-space v-if="record.approval_status === 'pending' && hasAccess('runtime:execute')" wrap>
            <a-button :loading="reviewing === record.action_id" :disabled="!!reviewing" @click="review(record.action_id,true)">{{ t('difyRuntime.approve') }}</a-button>
            <a-button danger :disabled="!!reviewing" @click="review(record.action_id,false)">{{ t('difyRuntime.reject') }}</a-button>
          </a-space>
          <span v-else>{{ t(`difyRuntime.${record.approval_status}`) }}</span>
        </template></a-table-column>
      </a-table>
      </template>
    </template>
    </div>
  </section>
</template>
<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { DeploymentUnitOutlined } from '@ant-design/icons-vue'
import { listDifyRuntimeBindings, updateDifyRuntimeBinding, getDifyRuntimeStatus, reviewDifyRuntimeCall } from '../../api'
import { can as hasAccess } from '../../access'
import DifyBehaviorAudit from './DifyBehaviorAudit.vue'
import DifyPolicyForm from './DifyPolicyForm.vue'
import DifyOverviewCharts from './DifyOverviewCharts.vue'
import DifySkills from './DifySkills.vue'
import { formatBeijingDateTime } from '../../utils/format'
const props = defineProps({ agentId: { type: String, required: true }, asset: { type: Object, required: true } })
defineEmits(['back', 'edit'])
const tab = ref('overview'), auditRefresh = ref(0)
const { t, te } = useI18n()
function label(group, value) {
  const key = `difyRuntime.${group}.${value}`
  return te(key) ? t(key) : value
}
const selected=ref(), data=ref(), mode=ref('observe'), policy=ref({default:'allow',rules:[],approved_graphs:[],approval_seconds:120,max_actions:500})
const loading=ref(false), saving=ref(false), reviewing=ref(''), error=ref('')
let generation=0
function failed(e) { error.value=e.response?.data?.detail || e.message }
async function loadStatus(reset) {
  if (!hasAccess('runtime:view')) return
  const ticket=++generation
  loading.value=true
  error.value=''
  try {
    if (!selected.value) {
      const b=await listDifyRuntimeBindings({ agent_id: props.agentId })
      if (ticket !== generation) return
      selected.value=b.items[0]?.binding_id
      if (!selected.value) return
      reset=true
    }
    const response=await getDifyRuntimeStatus(selected.value)
    if (ticket !== generation) return
    data.value=response
    auditRefresh.value++
    if (reset) { mode.value=response.binding.mode; policy.value={default:'allow',rules:[],approved_graphs:[],approval_seconds:120,max_actions:500,...structuredClone(response.binding.policy)} }
  } catch(e) { if(ticket===generation) failed(e) }
  finally { if(ticket===generation) loading.value=false }
}
function downloadConfig() {
  const { binding_id, workspace_id, app_id } = data.value.binding
  const value = { server_url: window.location.origin, applications: [{ binding_id, workspace_id, app_id, mode: data.value.binding.mode }] }
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url; link.download = 'config.json'; link.click()
  URL.revokeObjectURL(url)
}
async function save() {
  if(saving.value || !hasAccess('runtime:update')) return
  const parsed=policy.value
  if (!parsed.rules.every(rule => rule.rule_id?.trim()) || new Set(parsed.rules.map(rule => rule.rule_id)).size !== parsed.rules.length) return message.error(t('difyRuntime.ruleNameError'))
  saving.value=true; error.value=''
  try {
    await updateDifyRuntimeBinding(selected.value,{ revision:data.value.binding.revision,mode:mode.value,policy:parsed })
    await loadStatus(false); message.success(t('difyRuntime.saved'))
  } catch(e) { failed(e) } finally { saving.value=false }
}
async function review(id, approve) {
  if(reviewing.value || !hasAccess('runtime:execute')) return
  reviewing.value=id
  try { await reviewDifyRuntimeCall(id,approve); await loadStatus(false) }
  catch(e) { failed(e) } finally { reviewing.value='' }
}
onMounted(() => loadStatus(true))
onBeforeUnmount(()=>{ generation++ })
</script>
<style scoped>
.dify-workspace { display:flex; flex-direction:column; box-sizing:border-box; color:#263750; max-width:1440px; margin:auto; padding:6px 4px 0; height:100%; overflow:hidden; min-width:0; }
.workspace-breadcrumb,.workspace-heading,.workspace-tabs { flex-shrink:0; }
.workspace-body { flex:1; min-height:0; overflow:auto; overscroll-behavior:contain; padding-bottom:16px; }
.audit-body { display:flex; flex-direction:column; overflow:hidden; }
.workspace-breadcrumb { display:flex; gap:12px; align-items:center; font-size:12px; color:#8995a6; margin-bottom:10px; }
.workspace-breadcrumb .ant-btn { padding:0; font-size:12px; }
.identity { display:flex; align-items:center; gap:16px; min-width:0; }
.product-logo { display:grid; place-items:center; width:56px; height:56px; flex-shrink:0; background:white; border:1px solid #e5eaf1; border-radius:12px; color:#275fe4; font-size:26px; }
.identity-panel { background:white; border:1px solid #e5eaf1; border-radius:10px; padding:20px 22px 4px; margin:8px 0 16px; }
.overview-stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:20px; padding:20px; border:1px solid #e5eaf1; border-radius:10px; background:white; margin-bottom:16px; }
.workspace-tabs :deep(.ant-tabs-tab) { padding:14px 0; }
.workspace-tabs :deep(.ant-tabs-nav) { margin:6px 0 16px; }
.dify-workspace > .ant-form { background:white; border:1px solid #e5eaf1; border-radius:10px; padding:20px 22px; }
.workspace-heading { display:flex; justify-content:space-between; align-items:center; gap:16px; }
.workspace-heading h1 { margin:0 0 6px; font-size:26px; font-weight:650; letter-spacing:-.5px; overflow-wrap:anywhere; }
.muted { color:#7b8799; font-size:12px; line-height:1.7; }
.dify-workspace > .ant-alert, .dify-workspace > .ant-space, .dify-workspace > .ant-collapse { margin-bottom:16px; }
.dify-workspace :deep(.ant-descriptions-item-content) { overflow-wrap:anywhere; }
@media(max-width:600px) { .dify-workspace { padding:8px; } .workspace-heading { align-items:flex-start; } }
.install-command { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
