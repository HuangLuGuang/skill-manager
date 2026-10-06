<template>
  <section class="runtime-compatibility">
    <h4>{{ t('agentRuntimeGovernance.compatibilityGuide.title') }}</h4>
    <p>{{ t('agentRuntimeGovernance.compatibilityGuide.version') }}: {{ state?.client_version || t('agentRuntimeGovernance.unknown') }} · {{ t('agentRuntimeGovernance.compatibilityGuide.protocol') }}: {{ state?.compatibility?.protocol ?? t('agentRuntimeGovernance.unknown') }}</p>
    <a-alert :type="['legacy', 'partial'].includes(state?.compatibility?.state) ? 'warning' : 'info'" show-icon :message="t('agentRuntimeGovernance.compatibilityGuide.states.' + (state?.compatibility?.state || 'unknown'))" :description="t('agentRuntimeGovernance.compatibilityGuide.evidenceNote')" />
    <dl>
      <div v-for="kind in ['task_control', 'runtime_policy', 'channel_policy']" :key="kind"><dt>{{ t('agentRuntimeGovernance.compatibilityGuide.capabilities.' + kind) }}</dt><dd>{{ t(state?.compatibility?.current?.[kind] === true ? 'agentRuntimeGovernance.yes' : state?.compatibility?.current?.[kind] === false ? 'agentRuntimeGovernance.no' : 'agentRuntimeGovernance.unknown') }}</dd></div>
    </dl>
    <details :open="!state?.compatibility || state.compatibility.state !== 'reported_current'">
      <summary>{{ t('agentRuntimeGovernance.compatibilityGuide.upgradeTitle') }}</summary>
      <ol><li v-for="step in ['openSettings', 'checkUpdate', 'restart', 'newSession', 'refresh']" :key="step">{{ t('agentRuntimeGovernance.compatibilityGuide.steps.' + step) }}</li></ol>
      <p>{{ t('agentRuntimeGovernance.compatibilityGuide.packageFallback') }}</p>
    </details>
  </section>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
defineProps({ state: { type: Object, default: null } })
const { t } = useI18n()
</script>

<style scoped>
.runtime-compatibility { border: 1px solid #dce4e8; border-radius: 10px; padding: 16px; margin: 16px 0; overflow-wrap: anywhere; }
h4 { margin: 0 0 12px; }
dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; } dl > div { min-width: 0; } dd { margin: 6px 0 0; font-weight: 600; }
summary { cursor: pointer; } li { margin: 8px 0; line-height: 1.6; }
@media (max-width: 760px) { dl { grid-template-columns: minmax(0, 1fr); } }
</style>
