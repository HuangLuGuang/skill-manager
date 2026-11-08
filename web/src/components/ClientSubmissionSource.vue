<template>
  <span v-if="source?.channel === 'agent_manager_client'" class="submission-source">
    {{ t('deviceAssignment.clientSource', { name: source.device_user || t('deviceAssignment.unassigned') }) }}
    <router-link v-if="source.client_id && can('clients:view')" :to="{ path: '/clients', query: { client: source.client_id, section: 'overview' } }">{{ source.hostname || source.client_id }}</router-link>
    <span v-else-if="source.hostname">{{ source.hostname }}</span>
  </span>
  <span v-else>{{ source?.author || '-' }}</span>
</template>
<script setup>
import { useI18n } from 'vue-i18n'
import { can } from '../access'
defineProps({ source: Object })
const { t } = useI18n()
</script>
<style scoped>
.submission-source { display: inline-flex; flex-wrap: wrap; gap: 4px 8px; overflow-wrap: anywhere; }
</style>
