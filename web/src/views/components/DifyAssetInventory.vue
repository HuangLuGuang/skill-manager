<template>
  <a-spin :spinning="loading">
    <a-alert
      class="inventory-boundary"
      type="info"
      show-icon
      :message="t('agentSecurityScans.inventory.boundaryTitle')"
      :description="t('agentSecurityScans.inventory.boundary')"
    />
    <a-alert v-if="error" class="inventory-boundary" type="error" show-icon :message="error" />
    <template v-if="inventory">
      <header class="profile-header">
        <div>
          <span>{{ t('agentSecurityScans.inventory.profileEyebrow') }}</span>
          <h3>{{ fieldValue('name') }}</h3>
          <p>{{ fieldValue('description') }}</p>
        </div>
        <div class="profile-status">
          <a-tag :color="verificationColor(profileField('verification_status')?.value)">
            {{ verificationLabel(profileField('verification_status')?.value) }}
          </a-tag>
          <small>{{ t('agentSecurityScans.inventory.collectedAt') }} {{ formatDateTime(inventory.collected_at) }}</small>
        </div>
      </header>

      <section class="intent-overview" :aria-label="t('agentSecurityScans.inventory.intentSummary')">
        <div class="intent-source-strip">
          <div class="intent-entry">
            <span>{{ t('agentSecurityScans.inventory.verifiedIntent') }}</span>
            <strong>{{ displayField(profileField('verified_intent')) }}</strong>
            <small>{{ fieldStatusLabel(profileField('verified_intent')?.status) }} · {{ sourceLabel(profileField('verified_intent')?.source) }}</small>
          </div>
          <div class="intent-entry">
            <span>{{ t('agentSecurityScans.inventory.declaredIntentDisplay') }}</span>
            <strong>{{ displayField(profileField('declared_intent')) }}</strong>
            <small>{{ fieldStatusLabel(profileField('declared_intent')?.status) }} · {{ sourceLabel(profileField('declared_intent')?.source) }}</small>
          </div>
        </div>
        <div class="intent-entry intent-entry--inferred">
          <span>{{ t('agentSecurityScans.inventory.inferredIntent') }}</span>
          <strong>{{ displayField(profileField('inferred_intent')) }}</strong>
          <small>
            {{ fieldStatusLabel(profileField('inferred_intent')?.status) }}
            <template v-if="profileField('inferred_intent')?.confidence !== undefined">
              · {{ t('agentSecurityScans.inventory.intentConfidence', { value: Math.round(profileField('inferred_intent').confidence * 100) }) }}
            </template>
          </small>
          <small v-if="profileField('inferred_intent')?.model">
            {{ profileField('inferred_intent').provider || t('agentSecurityScans.inventory.unknownProvider') }} · {{ profileField('inferred_intent').model }} · {{ profileField('inferred_intent').rule_version }}
          </small>
          <ul v-if="profileField('inferred_intent')?.evidence_summary?.length">
            <li v-for="item in profileField('inferred_intent').evidence_summary" :key="item">{{ item }}</li>
          </ul>
          <small v-if="profileField('inferred_intent')?.error_code" class="intent-error">
            {{ intentErrorLabel(profileField('inferred_intent').error_code) }}
          </small>
          <small v-if="profileField('inferred_intent')?.diagnostic_code" class="intent-error">
            {{ t('agentSecurityScans.inventory.intentDiagnostic') }}: {{ intentDiagnosticLabel(profileField('inferred_intent').diagnostic_code) }}
          </small>
        </div>
      </section>
      <a-alert
        v-if="profileField('intent_alignment')?.value === 'potential_mismatch'"
        class="inventory-boundary intent-mismatch"
        type="warning"
        show-icon
        :message="t('agentSecurityScans.inventory.intentMismatch')"
      />

      <section class="coverage-strip" :aria-label="t('agentSecurityScans.inventory.coverage')">
        <div v-for="source in coverageSources" :key="source">
          <span>{{ t(`agentSecurityScans.inventory.coverageSources.${source}`) }}</span>
          <a-tag :color="coverageColor(inventory.coverage[source])">{{ coverageLabel(inventory.coverage[source]) }}</a-tag>
        </div>
      </section>

      <a-descriptions class="profile-fields" bordered size="small" :column="{ xs: 1, sm: 1, md: 2 }">
        <a-descriptions-item v-for="key in profileKeys" :key="key" :label="t(`agentSecurityScans.inventory.profileFields.${key}`)">
          <div class="profile-value">
            <span :title="displayField(profileField(key))">{{ displayField(profileField(key)) }}</span>
            <div>
              <a-tag :color="fieldStatusColor(profileField(key)?.status)">{{ fieldStatusLabel(profileField(key)?.status) }}</a-tag>
              <small>{{ sourceLabel(profileField(key)?.source) }}</small>
            </div>
            <small v-if="profileField(key)?.missing_reason" class="missing-reason">
              {{ missingReasonLabel(profileField(key).missing_reason) }}
            </small>
          </div>
        </a-descriptions-item>
      </a-descriptions>

      <section class="inventory-summary">
        <div v-for="type in assetTypes" :key="type">
          <span>{{ assetTypeLabel(type) }}</span>
          <strong>{{ countType(type) }}</strong>
        </div>
      </section>

      <div class="inventory-toolbar">
        <a-select v-model:value="filters.asset_type" allow-clear :placeholder="t('agentSecurityScans.inventory.filters.type')">
          <a-select-option v-for="type in assetTypes" :key="type" :value="type">{{ assetTypeLabel(type) }}</a-select-option>
        </a-select>
        <a-select v-model:value="filters.source_type" allow-clear :placeholder="t('agentSecurityScans.inventory.filters.source')">
          <a-select-option v-for="source in itemSources" :key="source" :value="source">{{ sourceLabel(source) }}</a-select-option>
        </a-select>
        <a-input v-model:value="filters.node_id" allow-clear :placeholder="t('agentSecurityScans.inventory.filters.node')" />
        <a-select v-model:value="filters.verification_status" allow-clear :placeholder="t('agentSecurityScans.inventory.filters.verification')">
          <a-select-option v-for="status in verificationStatuses" :key="status" :value="status">{{ verificationLabel(status) }}</a-select-option>
        </a-select>
        <a-button :loading="comparing" @click="loadComparison">{{ t('agentSecurityScans.inventory.comparePrevious') }}</a-button>
      </div>

      <a-alert
        v-if="comparison"
        class="inventory-boundary"
        :type="comparison.status === 'completed' ? 'success' : 'warning'"
        show-icon
        :message="comparison.status === 'completed' ? t('agentSecurityScans.inventory.comparisonReady') : t('agentSecurityScans.inventory.noBaseline')"
        :description="comparison.status === 'completed' ? t('agentSecurityScans.inventory.comparisonSummary', comparison.summary) : undefined"
      />
      <div v-if="comparison?.status === 'completed'" class="diff-groups">
        <div v-for="kind in ['added', 'removed', 'changed']" :key="kind">
          <strong>{{ t(`agentSecurityScans.inventory.diff.${kind}`) }}</strong>
          <code v-for="assetId in comparison[kind]" :key="assetId">{{ assetId }}</code>
          <small v-if="!comparison[kind]?.length">{{ t('agentSecurityScans.inventory.none') }}</small>
        </div>
      </div>

      <a-table
        :columns="columns"
        :data-source="inventory.items"
        row-key="item_id"
        size="small"
        table-layout="fixed"
        :scroll="{ x: 1000 }"
        :pagination="{ pageSize: 20, showSizeChanger: true }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'asset'">
            <div class="asset-identity"><strong :title="record.name">{{ record.name }}</strong><code :title="record.asset_id">{{ record.asset_id }}</code></div>
          </template>
          <template v-else-if="column.key === 'type'">{{ assetTypeLabel(record.asset_type) }}</template>
          <template v-else-if="column.key === 'configuration'">
            <div class="configuration-summary">
              <span v-for="item in keyConfiguration(record)" :key="item">{{ item }}</span>
            </div>
          </template>
          <template v-else-if="column.key === 'verification_summary'">
            <div class="verification-summary" :class="{ 'verification-summary--attention': verificationNeedsAttention(record) }">
              <strong>{{ verificationSummaryLabel(record) }}</strong>
              <div>
                <a-tag v-for="source in record.sources" :key="`${source.source_type}:${source.source_identifier}`">{{ sourceLabel(source.source_type) }}</a-tag>
              </div>
            </div>
          </template>
          <template v-else-if="column.key === 'details'">
            <a-button type="link" size="small" @click="openAssetDetails(record)">{{ t('agentSecurityScans.inventory.viewDetails') }}</a-button>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-button v-if="record.asset_type === 'prompt' && record.sensitive_content_available && canAdmin" type="link" size="small" @click="confirmPrompt(record)">{{ t('agentSecurityScans.inventory.viewPrompt') }}</a-button>
            <span v-else class="muted">—</span>
          </template>
        </template>
      </a-table>
    </template>
    <a-empty v-else-if="!loading && !error" :description="t('agentSecurityScans.inventory.unavailable')" />
  </a-spin>

  <a-modal v-model:open="promptOpen" :title="t('agentSecurityScans.inventory.promptTitle')" width="760px" :footer="null">
    <a-alert class="inventory-boundary" type="warning" show-icon :message="t('agentSecurityScans.inventory.promptAuditWarning')" />
    <a-spin :spinning="promptLoading"><pre class="prompt-block">{{ promptContent }}</pre></a-spin>
  </a-modal>
  <a-drawer v-model:open="assetDetailsOpen" :title="t('agentSecurityScans.inventory.assetDetailsTitle')" width="min(720px, 94vw)">
    <pre class="details-block">{{ prettyJson(assetDetailPayload(selectedAsset)) }}</pre>
  </a-drawer>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { useI18n } from 'vue-i18n'

import { compareSecurityTaskInventory, getSecurityInventoryPromptContent, getSecurityTaskInventory } from '../../api'
import { formatDateTime } from '../../utils/format'

const props = defineProps({ taskId: { type: String, required: true }, canAdmin: { type: Boolean, default: false } })
const { t, te } = useI18n()
const inventory = ref(null)
const error = ref('')
const loading = ref(false)
const comparing = ref(false)
const comparison = ref(null)
const promptOpen = ref(false)
const promptLoading = ref(false)
const promptContent = ref('')
const assetDetailsOpen = ref(false)
const selectedAsset = ref(null)
const filters = reactive({ asset_type: undefined, source_type: undefined, node_id: '', verification_status: undefined })
let inventoryRequestSequence = 0
let nodeFilterTimer
const coverageSources = computed(() => [
  'dsl', 'dify_console_api', 'dify_knowledge_api', 'mcp_tools_list', 'runtime_trace',
  ...(Object.hasOwn(inventory.value?.coverage || {}, 'intent_inference') ? ['intent_inference'] : []),
])
const assetTypes = ['node', 'prompt', 'mcp', 'tool', 'knowledge']
const verificationStatuses = ['verified', 'declared', 'inferred', 'partially_verified', 'unverified', 'unavailable']
const profileKeys = ['name', 'description', 'mode', 'created_at', 'updated_at', 'author', 'tags', 'app_id', 'workspace_id', 'workflow_id', 'workflow_version', 'dsl_version', 'published_status', 'environment', 'dify_base_url', 'owner', 'owner_group', 'last_collected_at', 'data_source', 'verification_status']
const columns = computed(() => [
  { title: t('agentSecurityScans.inventory.asset'), key: 'asset', width: 220 },
  { title: t('agentSecurityScans.inventory.type'), key: 'type', width: 90 },
  { title: t('agentSecurityScans.inventory.keyConfiguration'), key: 'configuration', width: 230 },
  { title: t('agentSecurityScans.inventory.verificationSummary'), key: 'verification_summary', width: 300 },
  { title: t('agentSecurityScans.inventory.details'), key: 'details', width: 90, fixed: 'right' },
  { title: t('agentSecurityScans.actions'), key: 'actions', width: 96, fixed: 'right' },
])
const itemSources = computed(() => [...new Set((inventory.value?.items || []).flatMap(item => item.sources.map(source => source.source_type)))])
const profileField = key => inventory.value?.agent_profile?.[key]
const fieldValue = key => displayField(profileField(key))
const displayField = field => {
  if (!field || field.value === null || field.value === undefined || field.value === '') return t('agentSecurityScans.inventory.notCollected')
  return Array.isArray(field.value) ? field.value.join(', ') : String(field.value)
}
const prettyJson = value => JSON.stringify(value ?? {}, null, 2)
const fieldStatusLabel = value => t(`agentSecurityScans.inventory.fieldStatuses.${value || 'unavailable'}`, value)
const verificationLabel = value => t(`agentSecurityScans.inventory.verificationStatuses.${value || 'unverified'}`, value)
const sourceLabel = value => value ? t(`agentSecurityScans.inventory.sourcesMap.${value}`, value) : t('agentSecurityScans.inventory.unknownSource')
const missingReasonLabel = value => te(`agentSecurityScans.inventory.missingReasons.${value}`) ? t(`agentSecurityScans.inventory.missingReasons.${value}`) : value
const intentErrorLabel = value => te(`agentSecurityScans.inventory.intentErrors.${value}`) ? t(`agentSecurityScans.inventory.intentErrors.${value}`) : value
const intentDiagnosticLabel = value => te(`agentSecurityScans.inventory.intentDiagnostics.${value}`) ? t(`agentSecurityScans.inventory.intentDiagnostics.${value}`) : value
const coverageLabel = value => t(`agentSecurityScans.inventory.coverageStatuses.${value || 'unavailable'}`, value)
const assetTypeLabel = value => t(`agentSecurityScans.inventory.assetTypes.${value}`, value)
const summaryKeyByAssetType = { node: 'nodes', prompt: 'prompts', mcp: 'mcp', tool: 'tools', knowledge: 'knowledge_bases' }
const countType = type => {
  const summaryValue = inventory.value?.summary?.[summaryKeyByAssetType[type]]
  if (Number.isInteger(summaryValue) && summaryValue >= 0) return summaryValue
  return (inventory.value?.items || []).filter(item => item.asset_type === type).length
}
const fieldStatusColor = value => ({ verified: 'green', declared: 'blue', inferred: 'gold', unverified: 'default', unavailable: 'default' }[value] || 'default')
const verificationColor = value => ({ verified: 'green', declared: 'blue', inferred: 'gold', partially_verified: 'orange', unverified: 'default', unavailable: 'default' }[value] || 'default')
const coverageColor = value => ({ completed: 'green', partial: 'orange', unavailable: 'default', error: 'red' }[value] || 'default')
const errorText = failure => failure.response?.data?.detail || failure.message || t('agentSecurityScans.operationFailed')
const keyConfiguration = record => {
  const details = record.details || {}
  const entries = [
    details.node_id && `${t('agentSecurityScans.inventory.configKeys.node')}: ${details.node_id}`,
    details.node_type && `${t('agentSecurityScans.inventory.configKeys.nodeType')}: ${details.node_type}`,
    details.role && `${t('agentSecurityScans.inventory.configKeys.role')}: ${details.role}`,
    details.provider_id && `${t('agentSecurityScans.inventory.configKeys.provider')}: ${details.provider_id}`,
    details.tool_name && `${t('agentSecurityScans.inventory.configKeys.tool')}: ${details.tool_name}`,
    details.resolved_dataset_id && `${t('agentSecurityScans.inventory.configKeys.dataset')}: ${details.resolved_dataset_id}`,
    details.capabilities?.length && `${t('agentSecurityScans.inventory.configKeys.capabilities')}: ${details.capabilities.join(', ')}`,
  ].filter(Boolean)
  return entries.length ? entries.slice(0, 3) : [t('agentSecurityScans.inventory.noKeyConfiguration')]
}
const sourceTypes = record => new Set((record.sources || []).map(item => item.source_type))
const verificationSummaryKey = record => {
  const sources = sourceTypes(record)
  const mapping = record.details?.mcp_mapping_status
  const datasetMapping = record.details?.dataset_reference_status
  if (datasetMapping === 'unmapped') return 'datasetReferenceUnmapped'
  if (datasetMapping === 'ambiguous') return 'datasetReferenceAmbiguous'
  if (datasetMapping === 'unavailable') return 'sourceUnavailable'
  if (sources.has('dify_console_draft_workflow')) return 'draftWorkflowMapped'
  if (mapping === 'unverified' || mapping === 'configured_tool_not_discovered') return 'mcpMappingUnverified'
  if (record.configured && !record.discovered) return 'configuredNotDiscovered'
  if (!record.configured && record.discovered && sources.has('runtime_trace')) return 'runtimeDiscoveredNotConfigured'
  if (record.verification_status === 'unavailable') return 'sourceUnavailable'
  if (record.verification_status === 'partially_verified') return 'partiallyVerified'
  if (record.verification_status === 'unverified') return 'insufficientEvidence'
  if (sources.has('mcp_tools_list')) return 'mcpToolsConfirmed'
  if (sources.has('dify_console_api')) return 'consoleConfirmed'
  if (sources.has('runtime_trace')) return 'runtimeConfirmed'
  if (sources.has('dsl')) return record.executed ? 'dslAndRuntimeConfirmed' : 'dslConfirmedNoExecutionEvidence'
  return 'evidenceConfirmed'
}
const knowledgeVerificationKeys = new Set(['draftWorkflowMapped', 'datasetReferenceUnmapped', 'datasetReferenceAmbiguous'])
const verificationSummaryLabel = record => {
  const key = verificationSummaryKey(record)
  return t(`agentSecurityScans.inventory.${knowledgeVerificationKeys.has(key) ? 'knowledgeVerificationSummaries' : 'verificationSummaries'}.${key}`)
}
const verificationNeedsAttention = record => ['mcpMappingUnverified', 'configuredNotDiscovered', 'runtimeDiscoveredNotConfigured', 'sourceUnavailable', 'partiallyVerified', 'insufficientEvidence', 'draftWorkflowMapped'].includes(verificationSummaryKey(record))
const assetDetailPayload = record => record ? ({
  configured: record.configured,
  discovered: record.discovered,
  executed: record.executed,
  verification_status: record.verification_status,
  sources: record.sources || [],
  details: record.details || {},
}) : {}
const openAssetDetails = record => { selectedAsset.value = record; assetDetailsOpen.value = true }

const loadInventory = async () => {
  const requestSequence = ++inventoryRequestSequence
  loading.value = true
  error.value = ''
  try {
    const result = await getSecurityTaskInventory(props.taskId, {
      asset_type: filters.asset_type,
      source_type: filters.source_type,
      node_id: filters.node_id.trim() || undefined,
      verification_status: filters.verification_status,
    })
    if (requestSequence === inventoryRequestSequence) inventory.value = result
  } catch (failure) {
    if (requestSequence === inventoryRequestSequence) {
      inventory.value = null
      error.value = errorText(failure)
    }
  } finally {
    if (requestSequence === inventoryRequestSequence) loading.value = false
  }
}
const loadComparison = async () => {
  comparing.value = true
  try { comparison.value = await compareSecurityTaskInventory(props.taskId) }
  catch (failure) { message.error(errorText(failure)) }
  finally { comparing.value = false }
}
const confirmPrompt = record => Modal.confirm({
  title: t('agentSecurityScans.inventory.promptConfirmTitle'),
  content: t('agentSecurityScans.inventory.promptConfirm'),
  okText: t('agentSecurityScans.inventory.confirmView'),
  cancelText: t('agentSecurityScans.inventory.cancel'),
  onOk: async () => {
    promptOpen.value = true
    promptLoading.value = true
    promptContent.value = ''
    try { promptContent.value = (await getSecurityInventoryPromptContent(props.taskId, record.item_id)).content }
    catch (failure) { promptContent.value = errorText(failure) }
    finally { promptLoading.value = false }
  },
})

watch(() => props.taskId, () => {
  comparison.value = null
  loadInventory()
}, { immediate: true })
watch(
  () => [filters.asset_type, filters.source_type, filters.verification_status],
  loadInventory,
)
watch(() => filters.node_id, value => {
  clearTimeout(nodeFilterTimer)
  nodeFilterTimer = setTimeout(loadInventory, value.trim() ? 300 : 0)
})
onBeforeUnmount(() => clearTimeout(nodeFilterTimer))
</script>

<style scoped>
.inventory-boundary { margin-bottom: 14px; }
.profile-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 18px; color: #f7fbff; background: #17324f; border-left: 4px solid #24a37f; }
.profile-header span { color: #8fd6c3; font-size: 11px; font-weight: 700; text-transform: uppercase; }
.profile-header h3 { margin: 4px 0; color: #fff; font-size: 22px; letter-spacing: 0; }
.profile-header p { max-width: 620px; margin: 0; color: #c8d6e6; overflow-wrap: anywhere; }
.profile-status { display: grid; flex: 0 0 auto; justify-items: end; gap: 8px; }
.profile-status small { color: #b6c8db; }
.intent-overview { display: grid; grid-template-columns: minmax(0, 1fr); border: 1px solid #dbe4ee; border-top: 0; background: #fff; }
.intent-source-strip { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); min-width: 0; }
.intent-entry { display: grid; align-content: start; min-width: 0; gap: 6px; padding: 14px; border-right: 1px solid #e5ebf2; }
.intent-entry:last-child { border-right: 0; }
.intent-entry > span { color: #66788e; font-size: 11px; font-weight: 700; }
.intent-entry strong { overflow-wrap: anywhere; }
.intent-entry small { color: #77899e; overflow-wrap: anywhere; }
.intent-entry ul { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 28px; margin: 4px 0 0; padding-left: 18px; color: #52677f; font-size: 12px; }
.intent-entry li { min-width: 0; overflow-wrap: anywhere; }
.intent-entry--inferred { padding: 16px 18px 18px; border-top: 2px solid #d99b22; background: #fffdf8; }
.intent-error { color: #b42318 !important; }
.intent-mismatch { margin-top: 12px; }
.coverage-strip, .inventory-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); border: 1px solid #dbe4ee; border-top: 0; }
.coverage-strip > div, .inventory-summary > div { display: grid; min-width: 0; gap: 6px; padding: 11px 12px; border-right: 1px solid #e5ebf2; }
.coverage-strip > div:last-child, .inventory-summary > div:last-child { border-right: 0; }
.coverage-strip span, .inventory-summary span { color: #66788e; font-size: 11px; overflow-wrap: anywhere; }
.profile-fields { margin-top: 16px; }
.profile-value { display: grid; min-width: 0; gap: 6px; }
.profile-value > span { overflow-wrap: anywhere; }
.profile-value > div { display: flex; align-items: center; gap: 5px; }
.profile-value small { color: #77899e; }
.missing-reason { color: #a56a16 !important; }
.inventory-summary { margin: 16px 0; border-top: 1px solid #dbe4ee; }
.inventory-summary strong { color: #17324f; font: 700 19px/1.1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.inventory-toolbar { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)) auto; gap: 8px; margin-bottom: 14px; }
.asset-identity { display: grid; min-width: 0; gap: 3px; }
.asset-identity strong, .asset-identity code { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-identity code { color: #63778f; font-size: 11px; }
.configuration-summary { display: grid; min-width: 0; gap: 4px; color: #52677f; font-size: 12px; }
.configuration-summary span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.verification-summary { display: grid; min-width: 0; gap: 6px; padding-left: 8px; border-left: 3px solid #57a98e; }
.verification-summary--attention { border-left-color: #d99b22; }
.verification-summary strong { color: #334a62; font-size: 12px; overflow-wrap: anywhere; }
.verification-summary > div { display: flex; flex-wrap: wrap; gap: 4px; }
.verification-summary :deep(.ant-tag) { margin: 0; font-size: 10px; }
.fact-grid { display: flex; flex-wrap: wrap; gap: 5px; }
.fact-grid span { padding: 2px 6px; color: #8795a7; font-size: 11px; background: #f0f2f5; border-radius: 3px; }
.fact-grid span.on { color: #116149; background: #dff4ed; }
.details-block, .prompt-block { max-width: min(620px, 70vw); max-height: 55vh; margin: 0; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.prompt-block { padding: 14px; color: #dbe9f7; background: #16283c; }
.diff-groups { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
.diff-groups > div { display: grid; align-content: start; gap: 5px; min-width: 0; padding: 10px; background: #f7f9fc; border: 1px solid #e2e8f0; }
.diff-groups code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted { color: #93a1b3; }
@media (max-width: 900px) { .intent-entry ul { grid-template-columns: 1fr; }.coverage-strip, .inventory-summary { grid-template-columns: 1fr 1fr; }.inventory-toolbar { grid-template-columns: 1fr 1fr; }.diff-groups { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .profile-header { flex-direction: column; }.profile-status { justify-items: start; }.intent-source-strip { grid-template-columns: 1fr; }.intent-source-strip .intent-entry { border-right: 0; border-bottom: 1px solid #e5ebf2; }.coverage-strip, .inventory-summary, .inventory-toolbar { grid-template-columns: 1fr; } }
</style>
