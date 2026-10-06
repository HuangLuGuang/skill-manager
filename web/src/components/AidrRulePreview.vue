<template>
  <section class="rule-preview" :aria-label="t('aidr.hooks.test.title')">
    <h4>{{ t('aidr.hooks.test.title') }}</h4>
    <p>{{ t(channel === 'hooks' ? 'aidr.hooks.test.hookHelp' : 'aidr.hooks.test.systemHelp') }}</p>
    <div class="preview-inputs" @keydown.enter.prevent="run">
      <label v-if="channel === 'hooks'">{{ t('aidr.hooks.agent') }}<select v-model="agent"><option value="claude">Claude Code</option><option value="codex">Codex</option></select></label>
      <label v-else>{{ t('aidr.hooks.test.actor') }}<select v-model="actor"><option value="agent">{{ t('aidr.hooks.test.agentActor') }}</option><option value="unknown">{{ t('aidr.hooks.test.unknownActor') }}</option></select></label>
      <label class="sample">{{ t(channel === 'hooks' ? 'aidr.hooks.test.tool' : 'aidr.hooks.test.path') }}<input v-model="sample" :maxlength="channel === 'hooks' ? 256 : 1023" :placeholder="channel === 'hooks' ? 'Bash' : '/private/tmp/example.txt'" /></label>
      <a-button :loading="loading" :disabled="loading || !sample.trim()" @click="run">{{ t('aidr.hooks.test.run') }}</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="t(`aidr.hooks.test.${error}`)" />
    <div v-if="result" aria-live="polite">
      <div class="preview-summary"><strong>{{ t('aidr.hooks.test.result') }}: {{ t(`aidr.hooks.${result.decision}`) }}</strong><span>{{ result.used_default ? t(channel === 'hooks' ? 'aidr.hooks.test.default' : 'aidr.hooks.test.unmatchedPath') : t('aidr.hooks.test.winner', { id: result.rule_id }) }}</span></div>
      <div class="preview-table"><table v-if="result.rules.length">
        <thead><tr><th>{{ t('aidr.hooks.ruleId') }}</th><th>{{ t('aidr.hooks.test.match') }}</th><th>{{ t('aidr.hooks.decision') }}</th><th>{{ t('aidr.hooks.test.reason') }}</th></tr></thead>
        <tbody><tr v-for="rule in result.rules" :key="rule.id" :class="{ matched: rule.matched }"><td><code>{{ rule.id }}</code></td><td>{{ t(rule.matched ? 'aidr.hooks.test.yes' : 'aidr.hooks.test.no') }}</td><td>{{ t(`aidr.hooks.${rule.decision}`) }}</td><td>{{ t(`aidr.hooks.test.reasons.${rule.reason}`) }}</td></tr></tbody>
      </table></div>
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { previewAidrRules } from '../api'
const props = defineProps({ clientId: { type: String, required: true }, channel: { type: String, required: true }, draft: { type: Object, required: true } })
const { t } = useI18n()
const agent = ref('claude'), actor = ref('agent'), sample = ref('')
const result = ref(null), error = ref(''), loading = ref(false)
let generation = 0
watch(() => [props.clientId, props.channel, props.draft, agent.value, actor.value, sample.value], () => { generation++; result.value = null; error.value = '' }, { deep: true, flush: 'sync' })
onBeforeUnmount(() => { generation++ })
async function run() {
  if (loading.value || !sample.value.trim()) return
  const runId = ++generation
  loading.value = true; result.value = null; error.value = ''
  const policy = props.channel === 'hooks'
    ? { ...props.draft, expected_revision: '0' }
    : { ...props.draft, expected_revision: '0', agent_executables: [], lifetime_seconds: 60 }
  const body = props.channel === 'hooks' ? { policy, agent: agent.value, tool: sample.value.trim() } : { policy, actor: actor.value, path: sample.value.trim() }
  try {
    const data = await previewAidrRules(props.clientId, props.channel, body)
    if (runId === generation) result.value = data
  } catch (err) {
    if (runId === generation) error.value = err.response?.status === 422 ? 'invalid' : 'failed'
  } finally { loading.value = false }
}
</script>

<style scoped>
.rule-preview { margin: 16px 0; padding: 16px; border: 1px solid #d9e2ee; border-radius: 8px; background: #f8fafc; }
h4 { margin: 0 0 8px; } p { color: #596579; }
.preview-inputs, .preview-summary { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin: 12px 0; }
label { display: flex; flex-direction: column; gap: 6px; } .sample { flex: 1; min-width: min(220px, 100%); }
input, select { width: 100%; min-height: 32px; padding: 4px 8px; border: 1px solid #b8c4d4; border-radius: 6px; background: white; color: #172b4d; }
.preview-table { overflow: auto; max-height: 320px; } table { width: 100%; border-collapse: collapse; } th, td { padding: 8px; text-align: left; border-bottom: 1px solid #d9e2ee; overflow-wrap: anywhere; } .matched { background: #edf5ff; }
</style>
