<template>
  <div v-if="scan" class="client-skill-scan">
    <span>{{ label('scanStatus', scan.status) }}</span>
    <template v-if="currentProgress">
      <div v-if="currentProgress.stage">{{ label('scanStage', currentProgress.stage) }}</div>
      <div v-for="(state, analyzer) in currentProgress.analyzers" :key="analyzer">
        {{ label('scanAnalyzer', analyzer) }}: {{ label('scanAnalyzerState', state) }}
      </div>
      <small v-if="currentProgress.updated_at">{{ t('clientGovernance.scanUpdated') }}: {{ currentProgress.updated_at }}</small>
    </template>
    <router-link v-if="versionId && can('skills:read')" :to="`/skills/${encodeURIComponent(versionId)}`">{{ t('clientGovernance.scanReport') }}</router-link>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { can } from '../access'
const props = defineProps({ skill: { type: Object, required: true } })
const { t, te } = useI18n()
const scan = computed(() => props.skill.governance?.signature === props.skill.signature ? props.skill.governance?.scan : null)
const versionId = computed(() => scan.value?.version_id || scan.value?.skill_id)
const currentProgress = computed(() => scan.value?.status === 'PENDING' && versionId.value && scan.value.progress?.version_id === versionId.value ? scan.value.progress : null)
function label(section, value) {
  const key = `clientGovernance.${section}.${value}`
  return te(key) ? t(key) : value
}
</script>

<style scoped>
.client-skill-scan { display: grid; gap: 3px; margin-top: 6px; overflow-wrap: anywhere; }
</style>
