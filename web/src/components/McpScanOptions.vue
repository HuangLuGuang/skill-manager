<template>
  <a-alert type="info" show-icon :message="t('mcpScan.boundary')" style="margin-bottom: 16px" />
  <a-form-item :label="t('mcpScan.mode')">
    <a-select :value="modelValue.mcp_mode" @change="mode => set({ mcp_mode: mode })">
      <a-select-option v-for="mode in modes" :key="mode" :value="mode">{{ t(`mcpScan.${mode}`) }}</a-select-option>
    </a-select>
  </a-form-item>
  <template v-if="modelValue.mcp_mode === 'source'">
    <a-form-item :label="t('mcpScan.snapshot')" required>
      <McpSourceInput v-if="canImport" :model-value="modelValue.mcp_source_id || target?.config?.source_id" @update:model-value="id => set({ mcp_source_id: id })" />
      <a-typography-text v-else style="overflow-wrap: anywhere">{{ modelValue.mcp_source_id || target?.config?.source_id || t('mcpScan.adminSourceRequired') }}</a-typography-text>
    </a-form-item>
    <a-form-item :label="t('mcpScan.depth')"><a-select :value="modelValue.mcp_depth" @change="value => set({ mcp_depth: value })"><a-select-option v-for="depth in ['quick', 'full']" :key="depth" :value="depth">{{ t(`mcpScan.${depth}`) }}</a-select-option></a-select></a-form-item>
  </template>
  <template v-if="['dynamic', 'redteam'].includes(modelValue.mcp_mode)">
    <a-alert v-if="error" type="error" :message="t('mcpScan.toolsUnavailable')" />
    <a-form-item :label="t('mcpScan.tools')" required>
      <a-select mode="multiple" :value="modelValue.mcp_tools" :loading="loading" :disabled="loading" @change="value => set({ mcp_tools: value })">
        <a-select-option v-for="tool in tools" :key="tool.name" :value="tool.name">{{ tool.name }} · {{ t(`mcpSecurity.accessModes.${tool.access_mode || 'unknown'}`) }} · {{ t(`agentSecurityScans.severities.${tool.risk_level || 'low'}`) }}</a-select-option>
      </a-select>
    </a-form-item>
    <a-form-item :label="t('mcpScan.callLimit')"><a-input-number :value="modelValue.mcp_call_limit" :min="1" :max="200" @change="value => set({ mcp_call_limit: value })" /></a-form-item>
    <a-form-item :label="t('mcpScan.route')" :extra="t('mcpScan.routeHelp')"><a-select :value="modelValue.mcp_route" @change="value => set({ mcp_route: value })"><a-select-option v-for="route in ['gateway', 'server']" :key="route" :value="route">{{ t(`mcpScan.${route}`) }}</a-select-option></a-select></a-form-item>
  </template>
  <a-form-item v-if="modelValue.mcp_mode === 'redteam'" :label="t('mcpScan.strategy')"><a-select :value="modelValue.mcp_strategy" @change="value => set({ mcp_strategy: value })"><a-select-option value="crescendo">Crescendo</a-select-option><a-select-option value="tap">TAP</a-select-option></a-select></a-form-item>
  <template v-if="modelValue.mcp_mode !== 'metadata'">
    <a-form-item v-for="role in roles" :key="role.field" :label="t(role.label)">
      <a-select :value="modelValue[role.field]" allow-clear show-search :placeholder="t('mcpScan.sameModel')" @change="value => set({ [role.field]: value })">
        <a-select-option v-for="model in models" :key="model.name" :value="model.name">{{ modelLabel(model) }}</a-select-option>
      </a-select>
    </a-form-item>
  </template>
</template>
<script setup>
import { modelLabel } from '../utils/modelLabels'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMcpScanTools } from '../api'
import McpSourceInput from './McpSourceInput.vue'
const props = defineProps({ modelValue: { type: Object, required: true }, target: Object, models: { type: Array, default: () => [] }, canImport: Boolean })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const tools = ref([])
const loading = ref(false)
const error = ref(false)
const modes = computed(() => props.target?.connector_type === 'mcp_source' ? ['source'] : ['metadata', 'source', 'dynamic', 'redteam'])
const roles = computed(() => [{ field: 'analysis_model', label: 'mcpScan.analysisModel' }, ...(props.modelValue.mcp_mode === 'redteam' ? [{ field: 'attack_model', label: 'mcpScan.attackModel' }] : [])])
const set = patch => emit('update:modelValue', { ...props.modelValue, ...patch })
watch(() => props.target?.target_id, async id => {
  tools.value = []
  if (!id) return
  if (props.target?.connector_type === 'mcp_source') set({ mcp_mode: 'source' })
  loading.value = true
  error.value = false
  try { const result = await getMcpScanTools(id); if (id === props.target?.target_id) tools.value = result.tools }
  catch { if (id === props.target?.target_id) error.value = true }
  finally { if (id === props.target?.target_id) loading.value = false }
}, { immediate: true })
</script>
