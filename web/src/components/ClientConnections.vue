<template>
  <section class="connections">
    <template v-if="!selected">
      <a-button v-if="groupFilter" class="policy-link" type="link" @click="groupFilter = ''"><ArrowLeftOutlined />{{ t('clientConnections.allAgents') }}</a-button>
      <ClientCollectionStatus :client-id="clientId" :fixed-agent="groupFilter" :discovered-agents="discoveredAgents" view="overview" @open="open" />
    </template>
    <template v-else>
      <header class="connections-heading">
        <a-button type="link" @click="selected = null"><ArrowLeftOutlined />{{ t('clientConnections.allAgents') }}</a-button>
        <strong>{{ product?.name || t('collectionStatus.system') }}</strong>
        <span v-if="product">{{ t('agentRuntimeGovernance.catalog.entries.' + product.entry) }}</span>
        <a-button v-if="product" :loading="refreshing" :disabled="refreshing" @click="refresh"><ReloadOutlined />{{ t('collectionStatus.refresh') }}</a-button>
        <a-button type="link" @click="activity(selected.channel === 'system' ? 'system' : section === 'logs' ? 'tools' : 'hooks')">{{ t('clientConnections.audit') }}</a-button>
      </header>
      <div class="connection-content">
        <ClientCollectionStatus v-if="product" ref="collection" :key="product.id" :client-id="clientId" :fixed-agent="product.id" view="detail" :offline="offline" @open="showDetails" @policy="emit('policy')" />
        <ClientCollectionStatus v-else ref="collection" :client-id="clientId" initial-channel="system" @policy="emit('policy')" @activity="activity" />
        <div v-if="product?.hooks" class="mode-row"><strong>{{ t('clientConnections.protection') }}</strong><SecurityRuleExecution :execution="execution" compact /><a-button type="link" @click="emit('policy')">{{ t('clientConnections.change') }}</a-button></div>
      </div>
      <a-modal v-model:open="detailsOpen" :title="`${product?.name || ''} · ${t(section === 'setup' ? 'clientConnections.setup' : section === 'logs' ? 'clientConnections.columns.logs' : 'clientConnections.operations')}`" width="min(780px, 96vw)" destroy-on-close @after-close="refresh">
        <template #footer><a-button @click="detailsOpen = false">{{ t('clientConnections.backToStatus') }}</a-button></template>
        <div class="connection-dialog">
          <ClientRuntimeGovernance v-if="section === 'setup' && product?.hooks" :client-id="clientId" :fixed-agent="product.id" compact @collection="detailsOpen = false" @policy="detailsOpen = false; emit('policy')" @events="detailsOpen = false; activity('hooks')" />
          <ClientCollectionStatus v-else :key="section" :client-id="clientId" :fixed-agent="product?.id || ''" :initial-channel="section" :offline="offline" embedded @plugins="detailsOpen = false" @policy="detailsOpen = false; emit('policy')" @activity="value => { detailsOpen = false; activity(value) }" />
        </div>
      </a-modal>
    </template>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import ClientCollectionStatus from './ClientCollectionStatus.vue'
import ClientRuntimeGovernance from './ClientRuntimeGovernance.vue'
import SecurityRuleExecution from './SecurityRuleExecution.vue'
import products from '../aidr-products.json'
import { productGroupId } from '../aidr-product-groups'
import { getSecurityRules } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, request: Object, offline: Boolean, discoveredAgents: { type: Array, default: () => [] } })
const emit = defineEmits(['policy', 'activity', 'refresh'])
const { t } = useI18n()
const selected = ref(null), section = ref('setup'), execution = ref(null), groupFilter = ref('')
const collection = ref(null), detailsOpen = ref(false), refreshing = ref(false)
let generation = 0
const product = computed(() => products.find(p => p.id === selected.value?.agent))
function showDetails(request) { section.value = request.channel; detailsOpen.value = true }
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  emit('refresh')
  try { await Promise.allSettled([loadExecution(), collection.value?.refresh()]) }
  finally { refreshing.value = false }
}
function open(value) {
  const request = value || {}
  detailsOpen.value = false
  const p = products.find(p => p.id === request.agent)
  groupFilter.value = !p && products.some(p => productGroupId(p.id) === request.agent) ? request.agent : ''
  selected.value = request.channel === 'system' ? { channel: 'system' } : p ? { ...request, agent: p.id } : null
  section.value = request.channel === 'system' ? 'system' : request.channel === 'logs' && p?.logs ? 'logs' : p?.hooks ? 'setup' : 'logs'
}
function activity(source) { emit('activity', { source, agent: product.value ? productGroupId(product.value.id) : '' }) }
async function loadExecution() {
  const epoch = ++generation
  execution.value = null
  try { const data = await getSecurityRules(props.clientId); if (epoch === generation) execution.value = data.execution }
  catch { /* The shared status renders an unconfirmed mode until a report is available. */ }
}
watch(() => [props.clientId, props.request], () => { open(props.request); loadExecution() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.connections{display:flex;flex-direction:column;height:100%;min-height:0}
.connections-heading{display:flex;align-items:center;gap:8px 16px;flex-wrap:wrap;flex-shrink:0;margin-bottom:8px}
.connections-heading>span{color:#66768c}.connections-heading :deep(.ant-btn){height:auto;white-space:normal}
.connection-content{flex:1;min-height:0;overflow:auto}.connection-content :deep(.collection-compact){flex:none;overflow:visible}
.connections-heading>.ant-btn:nth-last-child(2){margin-left:auto}
.connection-dialog{max-height:65vh;overflow:auto}.connection-dialog>*{min-height:0}.connection-dialog :deep(.collection-scroll){overflow:visible}
.mode-row{display:grid;grid-template-columns:140px minmax(180px,420px) auto;justify-content:start;gap:12px 20px;align-items:center;padding:18px 4px}.mode-row>strong{font-size:14px;font-weight:500}.mode-row :deep(.rule-execution){border:0;background:transparent;padding:0;margin:0}.mode-row :deep(.execution-content){flex-basis:auto}
.policy-link{align-self:flex-start;height:auto;white-space:normal}
@media(max-width:600px){.mode-row{grid-template-columns:minmax(0,1fr) auto;gap:8px}.mode-row>.rule-execution{grid-column:1;grid-row:2}.mode-row>.ant-btn{grid-column:2;grid-row:1 / 3}.connections-heading>.ant-btn:nth-last-child(2){margin-left:0}}
</style>
