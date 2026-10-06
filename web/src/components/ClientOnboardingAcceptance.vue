<template>
  <section class="onboarding-acceptance">
    <div class="acceptance-heading"><h4>{{ t('agentRuntimeGovernance.onboarding.title') }}</h4><a-button :loading="loading" :disabled="loading" @click="$emit('refresh')">{{ t('agentRuntimeGovernance.refresh') }}</a-button></div>
    <p>{{ t('agentRuntimeGovernance.onboarding.note') }}</p>
    <a-alert v-if="value?.target_enabled === false" type="info" show-icon :message="t('agentRuntimeGovernance.onboarding.notRequested')" />
    <a-alert v-else-if="value?.target_enabled == null" type="info" show-icon :message="t('agentRuntimeGovernance.onboarding.unknownTarget')" />
    <p v-if="value?.audit_enabled === false">{{ t('agentRuntimeGovernance.onboarding.auditPaused') }}</p>
    <a-radio-group v-if="value?.hosts?.length" :value="current?.agent" @update:value="selectedAgent = $event" button-style="solid"><a-radio-button v-for="item in value.hosts" :key="item.agent" :value="item.agent">{{ item.agent === 'claude' ? 'Claude Code' : 'Codex' }}</a-radio-button></a-radio-group>
    <template v-if="current">
      <div v-if="current.next_step" class="acceptance-next">
        <strong>{{ t('agentRuntimeGovernance.onboarding.next') }}: {{ t('agentRuntimeGovernance.onboarding.steps.' + current.next_step.key) }}</strong>
        <p>{{ t('agentRuntimeGovernance.onboarding.actions.' + current.next_step.next_action) }}</p>
        <a-button v-if="current.next_step.next_action === 'upgrade_client'" @click="$emit('upgrade')">{{ t('agentRuntimeGovernance.onboarding.openUpgrade') }}</a-button>
        <a-button v-else-if="current.next_step.next_action === 'configure_policy'" @click="$emit('policy')">{{ t('agentRuntimeGovernance.detail.configureAccess') }}</a-button>
        <a-button v-else :disabled="!canInspect || loading" @click="$emit('inspect', current.agent)">{{ t('agentRuntimeGovernance.onboarding.inspect') }}</a-button>
      </div>
      <p v-if="!current.next_step && value.target_enabled === true">{{ t('agentRuntimeGovernance.onboarding.availableEvidenceComplete') }}</p>
      <ol class="acceptance-steps">
        <li v-for="item in current.steps" :key="item.key">
          <div class="acceptance-step-heading"><strong>{{ t('agentRuntimeGovernance.onboarding.steps.' + item.key) }}</strong><a-tag :color="item.status === 'confirmed' ? 'green' : item.status === 'reported' ? 'blue' : item.status === 'attention' ? 'orange' : 'default'">{{ t('agentRuntimeGovernance.onboarding.statuses.' + item.status) }}</a-tag></div>
          <p v-if="item.key === 'host_loading' && item.evidence.hook_event_observed_at">{{ t('agentRuntimeGovernance.onboarding.hookObserved') }}</p>
          <details v-if="Object.keys(item.evidence).length"><summary>{{ t('agentRuntimeGovernance.onboarding.evidence') }} · {{ item.evidence.at ? stamp(item.evidence.at) : t('agentRuntimeGovernance.unknown') }}</summary><p>{{ t('agentRuntimeGovernance.onboarding.evidenceTypes.' + item.evidence.type) }}</p><pre>{{ JSON.stringify(item.evidence, null, 2) }}</pre></details>
        </li>
      </ol>
    </template>
    <p v-else>{{ t('agentRuntimeGovernance.unknown') }}</p>
    <details v-if="value"><summary>{{ t('agentRuntimeGovernance.onboarding.scope') }}</summary><p>{{ t('agentRuntimeGovernance.onboarding.window') }}: {{ stamp(value.evidence_after) }} · {{ t('agentRuntimeGovernance.onboarding.checked') }}: {{ stamp(value.checked_at) }}</p><p>{{ t('agentRuntimeGovernance.onboarding.windowNote') }}</p><p v-if="value.truncated_events">{{ t('agentRuntimeGovernance.onboarding.truncated') }}</p></details>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
const props = defineProps({ value: { type: Object, default: null }, loading: Boolean, canInspect: Boolean })
defineEmits(['refresh', 'inspect', 'policy', 'upgrade'])
const { t, locale } = useI18n()
const selectedAgent = ref('')
const current = computed(() => props.value?.hosts?.find(item => item.agent === selectedAgent.value) || props.value?.hosts?.[0])
const stamp = value => value ? new Date(value).toLocaleString(locale.value) : t('agentRuntimeGovernance.unknown')
</script>

<style scoped>
.onboarding-acceptance { border: 1px solid #dce4e8; border-radius: 10px; padding: 16px; margin: 16px 0; overflow-wrap: anywhere; }
.acceptance-heading, .acceptance-step-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
h4 { margin: 0; } .acceptance-next { background: #f5f7f9; border-radius: 8px; padding: 14px; margin: 14px 0; } .acceptance-next p { margin: 8px 0; line-height: 1.6; }
.acceptance-steps { padding-left: 24px; } li { padding: 10px 0; border-bottom: 1px solid #e5ebee; } summary { cursor: pointer; color: #627480; font-size: 12px; margin-top: 6px; } pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; } .ant-btn { height: auto; min-height: 32px; white-space: normal; }
</style>
