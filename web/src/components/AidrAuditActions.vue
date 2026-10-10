<template>
  <section v-if="actions.length" class="audit-actions">
    <h4>{{ t('aidr.detail.request') }}</h4>
    <p v-if="bodyOmitted && !bodyCaptured" class="audit-muted">{{ t('aidr.redactionSettings.body') }}</p>
    <div v-for="(action, index) in actions" :key="index" class="audit-action">
      <strong v-if="actions.length > 1 || action.tool !== tool">{{ action.tool }}</strong>
      <pre v-if="action.command && !bodyCaptured">{{ action.command }}</pre>
      <p v-if="action.cwd">{{ t('aidr.cwd') }}: <code>{{ action.cwd }}</code></p>
      <p v-for="(target, targetIndex) in action.targets || []" :key="targetIndex">{{ t('aidr.targetKinds.' + target.kind) }}: <code>{{ target.value }}</code></p>
      <p v-if="!action.command && !action.cwd && !action.targets?.length" class="audit-muted">{{ t('aidr.detail.noArguments') }}</p>
    </div>
  </section>
</template>
<script setup>
import { useI18n } from 'vue-i18n'
defineProps({ actions: { type: Array, default: () => [] }, tool: { type: String, default: '' }, bodyOmitted: Boolean, bodyCaptured: Boolean })
const { t } = useI18n()
</script>
<style scoped>
.audit-actions { margin: 20px 0; }
.audit-action + .audit-action { border-top: 1px solid #f0f0f0; padding-top: 12px; }
.audit-action p { margin: 8px 0; overflow-wrap: anywhere; }
.audit-action pre { padding: 12px 14px; border-radius: 6px; background: #f6f8fa; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 32vh; overflow: auto; }
.audit-muted { color: #667085; }
</style>
