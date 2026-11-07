<template>
  <section class="rule-preview" :aria-label="t('aidr.hooks.test.title')">
    <button v-if="channel === 'hooks'" class="preview-toggle" :aria-expanded="expanded" @click="expanded = !expanded"><span>⌘</span><strong>{{ t('aidr.hooks.test.title') }}</strong><small>{{ t('aidr.hooks.test.analysisOnly') }}</small><span class="toggle-end">{{ t(expanded ? 'aidr.hooks.test.collapse' : 'aidr.hooks.test.expand') }}</span></button>
    <h4 v-else>{{ t('aidr.hooks.test.title') }}</h4>
    <div v-show="channel !== 'hooks' || expanded" class="preview-body">
    <p v-if="channel !== 'hooks'">{{ t('aidr.hooks.test.systemHelp') }}</p>
    <div v-if="channel === 'hooks'" class="preview-kind"><a-radio-group v-model:value="testKind" size="small"><a-radio-button value="command">{{ t('aidr.hooks.test.commandMode') }}</a-radio-button><a-radio-button value="tool">{{ t('aidr.hooks.commands.toolType') }}</a-radio-button></a-radio-group></div>
    <div class="preview-inputs">
      <label v-if="channel === 'hooks'">{{ t('aidr.hooks.agent') }}<select v-model="agent"><option v-for="p in products.filter(p => p.hooks)" :key="p.id" :value="p.id">{{ p.name }}</option></select></label>
      <label v-else>{{ t('aidr.hooks.test.actor') }}<select v-model="actor"><option value="agent">{{ t('aidr.hooks.test.agentActor') }}</option><option value="unknown">{{ t('aidr.hooks.test.unknownActor') }}</option></select></label>
      <label v-if="channel === 'hooks' && testKind === 'command'" class="sample">{{ t('aidr.hooks.test.commandMode') }}<textarea v-model="command" maxlength="32768" rows="2" placeholder="rm -rf ./example" /></label>
      <label v-else class="sample">{{ t(channel === 'hooks' ? 'aidr.hooks.commands.toolType' : 'aidr.hooks.test.path') }}<input v-model="sample" :maxlength="channel === 'hooks' ? 256 : 1023" :placeholder="channel === 'hooks' ? 'Read / Write / Bash' : '/private/tmp/example.txt'" @keydown.enter.prevent="run" /></label>
      <a-button type="primary" ghost :loading="loading" :disabled="loading || !validInput" @click="run">{{ t('aidr.hooks.test.run') }}</a-button>
    </div>
    <div v-if="channel === 'hooks' && testKind === 'command'" class="preview-inputs preview-options">
      <label>{{ t('aidr.hooks.test.shellTool') }}<select v-model="shellTool"><option v-for="tool in shellTools" :key="tool" :value="tool">{{ tool }}</option></select></label>
      <label>{{ t('aidr.hooks.cwd') }}<input v-model="cwd" maxlength="1024" placeholder="/srv/app" /></label>
      <small>{{ t('aidr.hooks.test.shellHelp') }}</small>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="t(`aidr.hooks.test.${error}`)" />
    <div v-if="result" aria-live="polite">
      <a-alert v-if="result.unresolved" type="warning" :message="t('aidr.hooks.commands.unresolved')" show-icon />
      <div class="preview-summary" :class="'result-' + result.decision"><span>{{ t('aidr.hooks.test.result') }}</span><strong>{{ t(`aidr.hooks.${result.decision}`) }}</strong><span>{{ result.used_default ? t(channel === 'hooks' ? 'aidr.hooks.test.default' : 'aidr.hooks.test.unmatchedPath') : t('aidr.hooks.test.winner', { id: result.rule_id }) }}</span></div>
      <details v-if="result.rules.length" class="preview-reasons"><summary>{{ t('aidr.hooks.test.matchDetails') }}</summary><div class="preview-table"><table>
        <thead><tr><th>{{ t('aidr.hooks.ruleId') }}</th><th>{{ t('aidr.hooks.test.match') }}</th><th>{{ t('aidr.hooks.test.reason') }}</th></tr></thead>
        <tbody><tr v-for="rule in result.rules" :key="rule.id" :class="{ matched: rule.matched }"><td><code>{{ rule.id }}</code></td><td>{{ t(rule.matched ? 'aidr.hooks.test.yes' : 'aidr.hooks.test.no') }}</td><td>{{ t(`aidr.hooks.test.reasons.${rule.reason}`) }}</td></tr></tbody>
      </table></div></details>
    </div>
    <p v-if="channel === 'hooks'" class="preview-help">{{ t('aidr.hooks.test.hookHelp') }}</p>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { previewAidrRules, previewGlobalToolPolicy } from '../api'
import products from '../aidr-products.json'
const props = defineProps({ clientId: { type: String, default: '' }, global: Boolean, channel: { type: String, required: true }, draft: { type: Object, required: true } })
const { t } = useI18n()
const agent = ref('claude'), actor = ref('agent'), sample = ref('')
const command = ref(''), cwd = ref('')
const expanded = ref(false), testKind = ref('command'), shellTool = ref('Bash')
const shellTools = ['Bash', 'PowerShell', 'exec', 'exec_command', 'shell', 'run_terminal_cmd', 'run_shell_command', 'mcp__qw-builtin__mcp_workspace_bash']
const validInput = computed(() => props.channel === 'hooks' && testKind.value === 'command' ? !!command.value.trim() : !!sample.value.trim())
const result = ref(null), error = ref(''), loading = ref(false)
let generation = 0
watch(() => [props.clientId, props.channel, props.draft, agent.value, actor.value, sample.value, command.value, cwd.value, testKind.value, shellTool.value], () => { generation++; result.value = null; error.value = '' }, { deep: true, flush: 'sync' })
onBeforeUnmount(() => { generation++ })
async function run() {
  if (loading.value || !validInput.value) return
  const runId = ++generation
  loading.value = true; result.value = null; error.value = ''
  const policy = props.channel === 'hooks'
    ? { ...props.draft, expected_revision: '0' }
    : { ...props.draft, expected_revision: '0', agent_executables: [], lifetime_seconds: 60 }
  const body = props.channel === 'hooks' ? { policy, agent: agent.value, tool: testKind.value === 'command' ? shellTool.value : sample.value.trim(), command: testKind.value === 'command' ? command.value : '', cwd: testKind.value === 'command' ? cwd.value : '' } : { policy, actor: actor.value, path: sample.value.trim() }
  try {
    const data = await (props.global ? previewGlobalToolPolicy(body) : previewAidrRules(props.clientId, props.channel, body))
    if (runId === generation) result.value = data
  } catch (err) {
    if (runId === generation) error.value = err.response?.status === 422 ? 'invalid' : 'failed'
  } finally { loading.value = false }
}
</script>

<style scoped>
.rule-preview { margin: 16px 0; padding: 16px; border: 1px solid #e4eaf2; border-radius: 8px; background: white; }
.preview-toggle { width:100%; display:flex; align-items:center; flex-wrap:wrap; gap:10px; border:0; padding:0; background:transparent; text-align:start; cursor:pointer; font:inherit; color:#253753; }.preview-toggle > span:first-child { color:#2860ed; }.preview-toggle small,.toggle-end { color:#7a879e; font-size:12px; }.toggle-end{margin-left:auto}.preview-kind{margin-top:16px}
.preview-options { font-size:12px; }.preview-options small{color:#7a879e; max-width:340px}.preview-options input,.preview-options select{min-height:32px}.preview-help{font-size:12px;margin:12px 0 0}.preview-summary{padding:12px 14px;border-radius:6px;background:#f3f7ff}.preview-summary strong{font-size:16px}.result-allow strong{color:#24855b}.result-deny strong{color:#c13745}.result-ask strong{color:#ad690f}.preview-reasons{font-size:12px;color:#637189}.preview-reasons summary{cursor:pointer}
h4 { margin: 0 0 8px; } p { color: #596579; }
.preview-inputs, .preview-summary { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin: 12px 0; }
.preview-inputs > label { display: flex; flex-direction: column; gap: 6px; } .sample { flex: 1; min-width: min(220px, 100%); }
input, select, textarea { width: 100%; min-height: 32px; padding: 4px 8px; border: 1px solid #b8c4d4; border-radius: 6px; background: white; color: #172b4d; }
input,select,textarea{box-sizing:border-box}textarea{font-family:monospace;resize:vertical}button:focus-visible,summary:focus-visible{outline:2px solid #2860ed;outline-offset:3px}@media(max-width:600px){.preview-inputs>label{width:100%}.preview-toggle small{display:none}}
.preview-table { overflow: auto; max-height: 320px; } table { width: 100%; border-collapse: collapse; } th, td { padding: 8px; text-align: left; border-bottom: 1px solid #d9e2ee; overflow-wrap: anywhere; } .matched { background: #edf5ff; }
</style>
