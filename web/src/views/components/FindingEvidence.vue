<template>
  <div class="finding-evidence">
    <dl v-if="presentation.fields.length" class="evidence-fields">
      <template v-for="field in presentation.fields" :key="field.key">
        <dt>{{ t(`agentSecurityScans.evidence.fields.${field.key}`) }}</dt><dd>{{ field.key === 'attack_method' ? promptTransformationLabel(field.value, t, te) : field.value }}</dd>
      </template>
    </dl>
    <p v-if="!presentation.hasSpecificEvidence" class="muted">{{ t('agentSecurityScans.evidence.missing') }}</p>
    <div v-if="presentation.reason"><h4>{{ t('agentSecurityScans.detail.caseReason') }}</h4><p class="source-text">{{ presentation.reason }}</p></div>
    <div v-if="presentation.indicators.length || presentation.preview">
      <h4>{{ t('agentSecurityScans.evidence.trigger') }}</h4>
      <ul v-if="presentation.indicators.length"><li v-for="indicator in presentation.indicators" :key="indicator">{{ indicator }}</li></ul>
      <p v-if="presentation.preview" class="source-text">{{ presentation.preview }}</p>
    </div>
    <div v-if="presentation.conversation.length">
      <h4>{{ t('agentSecurityScans.evidence.context') }}</h4>
      <div class="conversation-evidence">
      <dl v-for="(turn, index) in presentation.conversation" :key="index" class="evidence-fields">
        <template v-if="turn.prompt"><dt>{{ t('agentSecurityScans.detail.casePrompt') }}</dt><dd class="source-text">{{ turn.prompt }}</dd></template>
        <template v-if="turn.response"><dt>{{ t('agentSecurityScans.detail.caseResponse') }}</dt><dd class="source-text">{{ turn.response }}</dd></template>
      </dl>
      </div>
    </div>
    <div v-if="presentation.suggestion"><h4>{{ t('agentSecurityScans.evidence.suggestion') }}</h4><p class="source-text">{{ presentation.suggestion }}</p></div>
    <a-space wrap>
      <a-button v-if="traceability.caseId && finding.task_id" type="link" @click="$emit('open-case', finding)">{{ t('agentSecurityScans.evidence.openCase') }}</a-button>
      <a-button v-if="traceability.traceId && traceability.eventId" type="link" @click="$emit('open-trace', finding)">{{ t('agentSecurityScans.findings.openTrace') }}</a-button>
    </a-space>
    <details class="technical-evidence">
      <summary>{{ t('agentSecurityScans.evidence.technical') }}</summary>
      <dl class="evidence-fields">
        <dt>{{ t('agentSecurityScans.findings.mappingVersion') }}</dt><dd>{{ finding.risk_mapping?.mapping_version || t('agentSecurityScans.findings.legacyUnmapped') }}</dd>
        <dt>{{ t('agentSecurityScans.detail.decisionCriteriaVersion') }}</dt><dd>{{ traceability.decisionCriteriaVersion || t('agentSecurityScans.detail.legacyUnversioned') }}</dd>
        <dt>{{ t('agentSecurityScans.findings.evidenceSha256') }}</dt><dd>{{ traceability.evidenceSha256 || '—' }}</dd>
      </dl>
      <a-tooltip :title="t('agentSecurityScans.evidence.copy')"><a-button :aria-label="t('agentSecurityScans.evidence.copy')" @click="copyEvidence"><CopyOutlined /></a-button></a-tooltip>
      <pre>{{ rawEvidence }}</pre>
    </details>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { CopyOutlined } from '@ant-design/icons-vue'
import { presentFindingEvidence } from '../../securityFindingEvidence'
import { promptTransformationLabel } from '../../securityScanReport'
import { normalizeFindingTraceability } from '../../securityFindingTraceability'
import { copyText } from '../../utils/clipboard'

const props = defineProps({ finding: { type: Object, required: true }, relatedCase: { type: Object, default: null } })
defineEmits(['open-case', 'open-trace'])
const { t, te } = useI18n()
const presentation = computed(() => presentFindingEvidence(props.finding, props.relatedCase))
const traceability = computed(() => normalizeFindingTraceability(props.finding))
const rawEvidence = computed(() => JSON.stringify(props.finding.evidence ?? {}, null, 2))
const copyEvidence = async () => {
  try { await copyText(rawEvidence.value); message.success(t('agentSecurityScans.evidence.copied')) }
  catch { message.error(t('agentSecurityScans.evidence.copyFailed')) }
}
</script>

<style scoped>
.finding-evidence { min-width: 0; overflow-wrap: anywhere; }
.finding-evidence h4 { margin: 12px 0 6px; font-size: 14px; }
.evidence-fields { display: grid; grid-template-columns: minmax(100px, 150px) minmax(0, 1fr); gap: 8px 12px; margin: 12px 0; }
.evidence-fields dt, .muted { color: #666; }
.evidence-fields dd { min-width: 0; margin: 0; }
.source-text, pre { white-space: pre-wrap; overflow-wrap: anywhere; }
.conversation-evidence { max-height: 360px; overflow: auto; }
.technical-evidence { margin-top: 12px; }
.technical-evidence summary { cursor: pointer; color: #666; }
pre { max-height: 360px; overflow: auto; padding: 12px; background: #f5f5f5; font-size: 12px; }
@media (max-width: 640px) { .evidence-fields { grid-template-columns: minmax(0, 1fr); gap: 4px; }.evidence-fields dd { margin-bottom: 8px; } }
</style>
