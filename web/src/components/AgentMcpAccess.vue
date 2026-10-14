<template>
  <section class="mcp-access">
    <p>{{ t('agentMcp.scope') }}</p>
    <a-button :loading="loading" :disabled="loading" @click="load">{{ t('agentIntegration.refresh') }}</a-button>
    <a-alert v-if="failed" type="error" show-icon :message="t('agentMcp.detailsFailed')" />
    <a-spin :spinning="loading">
      <template v-if="data && !failed">
        <AgentMcpGateways :model-value="data.gateways.map(item => item.slug)" :editable="false" />
        <div v-for="gateway in data.gateways" :key="gateway.slug" class="credential-row">
          <strong>{{ gateway.name }}</strong>
          <a-tag :color="gateway.credential_configured ? 'blue' : 'orange'">{{ t(gateway.credential_configured ? 'agentMcp.credentialConfigured' : 'agentMcp.credentialPending') }}</a-tag>
        </div>
        <p class="muted">{{ t('agentMcp.coverageHelp') }}</p>
        <h3>{{ t('agentMcp.recentCalls') }}</h3>
        <p class="muted">{{ t('agentMcp.evidenceHelp') }}</p>
        <a-table size="small" :columns="columns" :data-source="data.recent_calls" row-key="request_id" :pagination="false" :scroll="{ x: 580 }">
          <template #emptyText>{{ t('agentMcp.noCalls') }}</template>
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'time'">{{ formatDateTime(record.created_at) }}</template>
            <template v-else-if="column.key === 'status'">{{ te(`agentMcp.statuses.${record.status}`) ? t(`agentMcp.statuses.${record.status}`) : record.status }}</template>
          </template>
        </a-table>
      </template>
    </a-spin>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAgentMcpAccess } from '../api'
import { formatDateTime } from '../utils/format'
import AgentMcpGateways from './AgentMcpGateways.vue'
const props = defineProps({ agentPk: { type: Number, required: true } })
const { t, te } = useI18n()
const data = ref(null), loading = ref(false), failed = ref(false)
let requestVersion = 0
const columns = computed(() => [
  { title: t('agentMcp.time'), key: 'time', width: 165 },
  { title: t('agentMcp.gateway'), dataIndex: 'gateway_slug', width: 140 },
  { title: t('agentMcp.tool'), dataIndex: 'tool_name', width: 165 },
  { title: t('agentMcp.result'), key: 'status', width: 110 },
])
const load = async () => {
  const version = ++requestVersion
  loading.value = true; failed.value = false; data.value = null
  try { const result = await getAgentMcpAccess(props.agentPk); if (version === requestVersion) data.value = result }
  catch { if (version === requestVersion) failed.value = true }
  finally { if (version === requestVersion) loading.value = false }
}
watch(() => props.agentPk, load, { immediate: true })
</script>
<style scoped>
.mcp-access { min-width: 0; }.credential-row { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; overflow-wrap: anywhere; }.muted { color: #626b78; }
.mcp-access :deep(td) { overflow-wrap: anywhere; }
</style>
