<template>
  <article v-for="(hit, index) in matches" :key="`${hit.id}:${index}`" class="match">
    <strong>{{ hit.name || (te(`aidrRisk.settings.builtins.${hit.id}`) ? tr(`settings.builtins.${hit.id}`) : hit.id.startsWith('path_') ? tr('settings.customPaths') : tr(`codes.${hit.risk_code}`)) }}</strong>
    <a-tag :color="hit.severity === 'high' ? 'red' : 'orange'">{{ tr(`severity.${hit.severity}`) }}</a-tag>
    <dl v-if="hit.condition">
<template v-if="hit.condition.networks"><dt>{{ t('securityRules.subnets') }}</dt><dd>{{ hit.condition.networks.subnets.join('\n') }}</dd></template>
      <template v-if="hit.condition.keywords"><dt>{{ t('securityRules.keywordTerms') }}</dt><dd>{{ hit.condition.keywords.terms.join('\n') }}</dd><dt>{{ t('securityRules.keywordMode') }}</dt><dd>{{ t('securityRules.keywordModes.' + hit.condition.keywords.mode) }} · {{ t('securityRules.ignoreCase') }}: {{ t(hit.condition.keywords.ignore_case ? 'securityRules.enabled' : 'securityRules.disabled') }}</dd></template>
      <template v-for="key in ['agent', 'tool', 'executable', 'args_all', 'args_any', 'path_prefix', 'pipe_to', 'paths']" :key="key">
        <template v-if="hit.condition[key]?.length"><dt>{{ tr(`commandRules.conditions.${key}`) }}</dt><dd>{{ Array.isArray(hit.condition[key]) ? hit.condition[key].join('\n') : hit.condition[key] }}</dd></template>
      </template>
      <template v-if="hit.targets?.length"><dt>{{ tr('target') }}</dt><dd>{{ hit.targets.join('\n') }}</dd></template>
    </dl>
  </article>
</template>
<script setup>
import { useI18n } from 'vue-i18n'
defineProps({ matches: { type: Array, required: true } })
const { t, te } = useI18n(), tr = key => t(`aidrRisk.${key}`)
</script>
<style scoped>
.match { padding: 12px 0; border-bottom: 1px solid #eee; overflow-wrap: anywhere; }.ant-tag { margin-left: 8px; } dl { display: grid; grid-template-columns: minmax(90px, 130px) minmax(0, 1fr); gap: 6px 12px; margin: 8px 0 0; } dt { color: #667085; } dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 540px) { dl { grid-template-columns: 1fr; } }
</style>
