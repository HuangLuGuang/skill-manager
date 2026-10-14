<template>
  <div class="mcp-gateways">
    <a-alert v-if="failed" type="error" show-icon :message="t('agentMcp.loadFailed')" />
    <a-select v-if="editable" :value="modelValue" mode="multiple" allow-clear show-search option-filter-prop="label"
      :loading="loading" :disabled="disabled || loading || failed" :placeholder="t('agentMcp.placeholder')"
      :options="selectOptions" @update:value="emit('update:modelValue', $event)" />
    <p v-if="!loading && !failed && !selected.length" class="muted">{{ t(editable && !selectOptions.length ? 'agentMcp.noOptions' : 'agentMcp.empty') }}</p>
    <div v-for="gateway in selected" :key="gateway.slug" class="gateway-row">
      <div class="gateway-info"><strong>{{ gateway.name }}</strong><code>{{ gateway.slug }}</code><p v-if="gateway.description">{{ gateway.description }}</p>
        <span v-if="gateway.status === 'active'" class="muted">{{ t('agentMcp.toolCount', { count: gateway.tools.length }) }}</span>
        <a-tag v-else color="warning">{{ t('agentMcp.unavailable') }}</a-tag>
        <p v-if="allowedGateways && !allowedGateways.includes(gateway.slug)" class="scope-error">{{ t('agentMcp.outOfScope') }}</p>
      </div>
      <a-space wrap>
        <a-button v-if="gateway.status === 'active'" size="small" @click="preview = gateway">{{ t('agentMcp.tools') }}</a-button>
        <a-button v-if="editable" size="small" :disabled="disabled" @click="emit('update:modelValue', modelValue.filter(name => name !== gateway.slug))">{{ t('agentMcp.remove') }}</a-button>
      </a-space>
    </div>
    <a-space wrap class="gateway-actions">
      <a-button size="small" :loading="loading" :disabled="loading || disabled" @click="load">{{ t('agentMcp.refresh') }}</a-button>
      <a v-if="editable && pageAllowed('/mcp-governance/gateways') && hasAccess('mcp:create')" :href="router.resolve('/mcp-governance/gateways').href" target="_blank" rel="noopener">{{ t('agentMcp.manage') }}</a>
      <span v-else-if="editable && !loading && !selectOptions.length" class="muted">{{ t('agentMcp.contact') }}</span>
    </a-space>
    <a-drawer :open="!!preview" :width="560" :title="preview?.name" @close="preview = null">
      <p>{{ t('agentMcp.toolsHelp') }}</p>
      <a-empty v-if="!preview?.tools.length" :description="t('agentMcp.noTools')" />
      <div v-for="tool in preview?.tools || []" :key="tool.name" class="tool-row">
        <strong>{{ tool.name }}</strong><p>{{ tool.description }}</p><p class="muted">{{ t('agentMcp.source', { name: tool.server_name }) }}</p>
        <a-tag :color="tool.requires_approval ? 'orange' : 'default'">{{ t(tool.requires_approval ? 'agentMcp.approval' : 'agentMcp.noApproval') }}</a-tag>
      </div>
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { listAgentMcpOptions } from '../api'
import { can as hasAccess, pageAllowed } from '../access'

const props = defineProps({ modelValue: { type: Array, default: () => [] }, editable: { type: Boolean, default: true }, disabled: Boolean, allowedGateways: { type: Array, default: undefined } })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n(), router = useRouter()
const options = ref([]), loading = ref(false), failed = ref(false), preview = ref(null)
const selectOptions = computed(() => options.value.filter(item => item.status === 'active' && (!props.allowedGateways || props.allowedGateways.includes(item.slug))).map(item => ({ value: item.slug, label: `${item.name} · ${item.slug}` })))
const selected = computed(() => loading.value || failed.value ? [] : props.modelValue.map(slug => options.value.find(item => item.slug === slug) || { slug, name: slug, status: 'missing', tools: [] }))
const load = async () => {
  if (loading.value) return
  loading.value = true; failed.value = false
  try { options.value = await listAgentMcpOptions() } catch { failed.value = true } finally { loading.value = false }
}
onMounted(load)
</script>

<style scoped>
.mcp-gateways { min-width: 0; }.mcp-gateways > .ant-select { width: 100%; }.muted { color: #626b78; }
.gateway-row { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; border-bottom: 1px solid #edf0f5; padding: 14px 0; }
.gateway-info { flex: 1 1 200px; min-width: 0; overflow-wrap: anywhere; }.gateway-info code { display: block; }.gateway-info p { margin: 5px 0; }
.gateway-actions { margin: 12px 0; }.tool-row { padding: 16px 0; border-bottom: 1px solid #edf0f5; overflow-wrap: anywhere; }
.scope-error { color: #c53030; }
.mcp-gateways :deep(.ant-btn) { height: auto; min-height: 24px; white-space: normal; overflow-wrap: anywhere; }
</style>
