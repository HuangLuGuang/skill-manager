<template>
  <div class="source-attribution">
    <a-tag :color="source === 'external_api' ? 'blue' : 'default'">{{ t(`externalAccess.sources.${knownSource}`) }}</a-tag>
    <div v-if="record.source_platform_id">{{ record.source_platform_name || record.source_platform_id }}<span v-if="record.source_platform_name"> ({{ record.source_platform_id }})</span></div>
    <div v-if="externalId">{{ t(task ? 'externalAccess.externalTaskId' : 'externalAccess.externalAgentId') }}: {{ externalId }}</div>
    <div v-if="details && record.source_token_id">{{ t('externalAccess.sourceToken') }}: #{{ record.source_token_id }}</div>
    <div v-if="details && record.business_request_id">{{ t('externalAccess.businessRequestId') }}: {{ record.business_request_id }}</div>
    <router-link v-if="record.source_request_id && pageAllowed('/external-access')" :to="{ path: '/external-access', query: { request_id: record.source_request_id } }">{{ t('externalAccess.viewRequest') }}</router-link>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { pageAllowed } from '../access'
const props = defineProps({ record: { type: Object, required: true }, task: Boolean, details: Boolean })
const { t } = useI18n()
const source = computed(() => props.task ? props.record.trigger_source : props.record.registration_source)
const knownSource = computed(() => ['console', 'external_api', 'client_discovery', 'scheduled', 'asset_change', 'asset_sync'].includes(source.value) ? source.value : 'unknown')
const externalId = computed(() => props.task ? props.record.external_task_id : props.record.external_agent_id)
</script>
<style scoped>
.source-attribution { font-size: 12px; overflow-wrap: anywhere; line-height: 1.6; }
</style>
