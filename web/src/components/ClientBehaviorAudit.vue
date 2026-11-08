<template>
  <section class="behavior-audit">
    <a-radio-group v-model:value="section" class="audit-views" option-type="button" button-style="solid" :options="options" />
    <ClientAuditSessions v-if="['tools', 'hooks'].includes(view)" v-model:source="view" :client-id="clientId" :activity-request="activityRequest" @collection="emit('collection', $event)" />
    <div v-else-if="view === 'system'" class="system-events-scroll">
      <ClientEnforcementPanel :client-id="clientId" view="events" @collection="emit('collection', { channel: 'system' })" />
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ClientEnforcementPanel from './ClientEnforcementPanel.vue'
import ClientAuditSessions from './ClientAuditSessions.vue'
defineProps({ clientId: { type: String, required: true }, activityRequest: Object })
const emit = defineEmits(['collection'])
const { t } = useI18n()
const view = defineModel('view', { type: String, default: 'tools' })
const section = computed({ get: () => ['tools', 'hooks'].includes(view.value) ? 'sessions' : view.value, set: value => { view.value = value === 'sessions' ? 'tools' : value } })
const options = computed(() => ['sessions', 'system'].map(value => ({ value, label: t(value === 'sessions' ? 'aidr.sessions.activity' : `agentRuntimeGovernance.detail.auditViews.${value}`) })))
</script>

<style scoped>
.behavior-audit { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.audit-views { display: flex; flex-wrap: wrap; flex-shrink: 0; margin: 0 0 8px; }
.audit-views :deep(.ant-radio-button-wrapper) { height: auto; white-space: normal; }
.system-events-scroll { display: flex; flex: 1; min-height: 0; overflow: hidden; }
.system-events-scroll :deep(.enforcement-panel) { margin: 0; }
</style>
