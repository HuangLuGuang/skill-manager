<template>
  <div class="hook-connection">
    <a-tag v-if="value?.requested === false">{{ t('agentRuntimeGovernance.connection.notRequested') }}</a-tag>
    <a-tag v-if="value?.stale" color="orange">{{ t('agentRuntimeGovernance.stale') }}</a-tag>
    <dl>
      <div><dt>{{ t('agentRuntimeGovernance.connection.installation') }}</dt><dd>{{ status('installation', value?.installation) }}</dd></div>
      <div><dt>{{ t('agentRuntimeGovernance.connection.enabled') }}</dt><dd>{{ t(`agentRuntimeGovernance.connection.${value?.enabled === true ? 'enabledYes' : value?.enabled === false ? 'enabledNo' : 'unknown'}`) }}</dd></div>
      <div><dt>{{ t('agentRuntimeGovernance.connection.authorization') }}</dt><dd>{{ status('authorization', value?.authorization) }}</dd></div>
      <div><dt>{{ t('agentRuntimeGovernance.receiver') }}</dt><dd>{{ t(`agentRuntimeGovernance.channelStates.${value?.receiver || 'unknown'}`) }}</dd></div>
      <div><dt>{{ t('agentRuntimeGovernance.connection.arrival') }}</dt><dd>{{ value?.event_received_at ? new Date(value.event_received_at).toLocaleString(locale) : t('agentRuntimeGovernance.connection.noRecentEvent') }}</dd></div>
    </dl>
    <p v-if="value?.authorization === 'review_required'">{{ t('agentRuntimeGovernance.connection.reviewHint') }}</p>
    <p v-if="['admin_required','cancelled','failed','interrupted'].includes(value?.authorization)">{{ t('agentRuntimeGovernance.connection.adminHint') }}</p>
    <p v-if="value?.installation === 'host_missing'">{{ t('agentRuntimeGovernance.connection.hostHint') }}</p>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
defineProps({ value: { type: Object, default: null } })
const { t, te, locale } = useI18n()
const status = (kind, value) => {
  const key = `agentRuntimeGovernance.connection.${kind}States.${value || 'unknown'}`
  return te(key) ? t(key) : t('agentRuntimeGovernance.connection.unknown')
}
</script>

<style scoped>
dl { margin: 12px 0; display: grid; gap: 8px; }
dl > div { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 16px; }
dt { color: #627480; } dd { margin: 0; overflow-wrap: anywhere; }
p { color: #627480; line-height: 1.6; }
</style>
