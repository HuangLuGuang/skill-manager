<template>
  <section class="behavior-audit" :class="{ 'session-view': section === 'sessions' }">
    <a-radio-group v-model:value="section" class="audit-views" option-type="button" button-style="solid" :options="options" />
    <ClientAuditSessions v-if="['tools', 'hooks'].includes(view)" v-model:source="view" :client-id="clientId" @collection="view = 'collection'" />
    <ClientEnforcementPanel v-else-if="view === 'system'" :client-id="clientId" view="events" />
    <template v-else>
      <p class="collection-note">{{ t('agentRuntimeGovernance.detail.channelsNote') }}</p>
      <ClientRuntimeGovernance :client-id="clientId" view="collection" />
      <details @toggle="receiverReportsOpen = $event.target.open">
        <summary>{{ t('agentRuntimeGovernance.detail.receiverReports') }}</summary>
        <ClientHookPanel v-if="receiverReportsOpen" :client-id="clientId" view="runtime" />
      </details>
      <ClientAidrPanel :client-id="clientId" view="collection" @policy="$emit('policy')" />
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ClientAidrPanel from './ClientAidrPanel.vue'
import ClientHookPanel from './ClientHookPanel.vue'
import ClientEnforcementPanel from './ClientEnforcementPanel.vue'
import ClientRuntimeGovernance from './ClientRuntimeGovernance.vue'
import ClientAuditSessions from './ClientAuditSessions.vue'
defineProps({ clientId: { type: String, required: true } })
defineEmits(['policy'])
const { t } = useI18n()
const view = defineModel('view', { type: String, default: 'tools' })
const section = computed({ get: () => ['tools', 'hooks'].includes(view.value) ? 'sessions' : view.value, set: value => { view.value = value === 'sessions' ? 'tools' : value } })
const receiverReportsOpen = ref(false)
const options = computed(() => ['sessions', 'system', 'collection'].map(value => ({ value, label: t(value === 'sessions' ? 'aidr.sessions.activity' : `agentRuntimeGovernance.detail.auditViews.${value}`) })))
</script>

<style scoped>
.audit-views { display: flex; flex-wrap: wrap; margin: 16px 0; }
.session-view { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.session-view .audit-views { flex-shrink: 0; margin: 0 0 8px; }
.audit-views :deep(.ant-radio-button-wrapper) { height: auto; white-space: normal; }
.collection-note { color: #627480; }
summary { cursor: pointer; color: #526873; padding: 12px 0; }
</style>
