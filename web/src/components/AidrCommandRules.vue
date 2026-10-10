<template>
  <section class="command-editor">
    <details class="preset-library" :open="!rules.length">
    <summary>{{ t('aidr.hooks.commands.common') }}<span>{{ t('aidr.hooks.commands.commonHelp') }}</span></summary>
    <div class="presets">
      <button v-for="preset in presets" :key="preset.id" type="button" :disabled="disabled || rules.length >= 128" @click="edit(preset)">
        <span class="preset-icon" :class="preset.id"><component :is="preset.icon" /></span><span class="preset-copy"><strong>{{ t(`aidr.hooks.commands.presets.${preset.id}`) }}</strong><code>{{ preset.example }}</code></span><small>＋ {{ t('aidr.hooks.commands.configure') }}</small>
      </button>
    </div>
    </details>
    <div class="editor-heading current-heading"><h3>{{ t('aidr.hooks.commands.current') }} <span class="rule-count">{{ rules.length }}</span></h3><a-button type="primary" ghost :disabled="disabled || rules.length >= 128" @click="edit()">＋ {{ t('aidr.hooks.commands.custom') }}</a-button></div>
    <div class="rule-table"><table><thead><tr><th>{{ t('aidr.hooks.commands.condition') }}</th><th>{{ t('aidr.hooks.agent') }}</th><th>{{ t('aidr.hooks.commands.disposition') }}</th><th>{{ t('aidr.hooks.commands.actions') }}</th></tr></thead>
      <tbody><tr v-for="(rule, index) in rules" :key="rule.id + index"><td><strong>{{ rule.id }}</strong><small> · {{ t(rule.command ? 'aidr.hooks.commands.commandType' : 'aidr.hooks.commands.toolType') }}</small><code>{{ describe(rule) }}</code><p v-if="!rule.command" class="native-hint">{{ t('aidr.hooks.commands.nativeHint') }}</p></td><td><select :aria-label="rule.id + ' · ' + t('aidr.hooks.agent')" :value="rule.agent" :disabled="disabled" @change="update(index, 'agent', $event.target.value)"><option value="*">{{ t('aidr.hooks.commands.allAgents') }}</option><option v-for="p in products.filter(p => p.hooks)" :key="p.id" :value="p.id">{{ p.name }}</option></select></td><td><select :class="'decision-' + rule.decision" :aria-label="rule.id + ' · ' + t('aidr.hooks.commands.disposition')" :value="rule.decision" :disabled="disabled" @change="update(index, 'decision', $event.target.value)"><option v-for="d in ['allow', 'ask', 'deny']" :key="d" :value="d" :disabled="d === 'ask' && rule.agent !== '*' && !products.find(p => p.id === rule.agent)?.approval">{{ t('aidr.hooks.' + d) }}</option></select></td><td class="row-actions"><a-button type="link" :disabled="disabled" @click="edit(rule, index)">{{ t('aidr.hooks.commands.edit') }}</a-button><a-button type="text" danger :disabled="disabled" @click="remove(index)">{{ t('aidr.hooks.remove') }}</a-button></td></tr></tbody>
    </table><a-empty v-if="!rules.length" :description="t('aidr.hooks.commands.empty')" /></div>
    <a-modal v-model:open="open" :title="t('aidr.hooks.commands.custom')" :footer="null" :width="700" :body-style="{ maxHeight: '70vh', overflow: 'auto' }">
      <form class="rule-form" @submit.prevent="apply">
        <label>{{ t('aidr.hooks.ruleId') }}<a-input v-model:value="editing.id" required maxlength="64" pattern="[A-Za-z0-9_-]+" /></label>
        <div class="pair"><label>{{ t('aidr.hooks.commands.type') }}<select v-model="kind"><option value="command">{{ t('aidr.hooks.commands.commandType') }}</option><option value="tool">{{ t('aidr.hooks.commands.toolType') }}</option></select></label><label>{{ t('aidr.hooks.agent') }}<select v-model="editing.agent" @change="normalize"><option value="*">{{ t('aidr.hooks.commands.allAgents') }}</option><option v-for="p in products.filter(p => p.hooks)" :key="p.id" :value="p.id">{{ p.name }}</option></select></label></div>
        <template v-if="kind === 'command'">
          <label>{{ t('aidr.hooks.commands.executable') }}<a-input v-model:value="condition.executable" placeholder="rm" required maxlength="128" pattern="[A-Za-z0-9_./+\-]+" /></label>
          <div class="pair"><label>{{ t('aidr.hooks.commands.argsAll') }}<a-textarea v-model:value="argsAll" :rows="2" placeholder="reset&#10;--hard" /></label><label>{{ t('aidr.hooks.commands.argsAny') }}<a-textarea v-model:value="argsAny" :rows="2" placeholder="-r&#10;--recursive" /></label></div>
          <label>{{ t('aidr.hooks.commands.path') }}<a-input v-model:value="condition.path_prefix" placeholder="/srv/data" maxlength="512" /></label>
          <label>{{ t('aidr.hooks.commands.pipe') }}<a-input v-model:value="pipeTo" placeholder="sh, bash" /></label>
          <details class="help"><summary>{{ t('aidr.hooks.commands.scope') }}</summary><p>{{ t('aidr.hooks.commands.boundary') }}</p></details>
        </template>
        <label v-else>{{ t('aidr.hooks.tool') }}<a-input v-model:value="editing.tool" placeholder="Bash" required maxlength="256" /></label>
        <label>{{ t('aidr.hooks.decision') }}<select v-model="editing.decision"><option v-for="d in ['deny','ask','allow']" :key="d" :value="d" :disabled="d === 'ask' && editing.agent !== '*' && !products.find(p => p.id === editing.agent)?.approval">{{ t(`aidr.hooks.${d}`) }}</option></select></label>
        <a-alert v-if="error" type="error" :message="error" />
        <div class="dialog-actions"><a-button @click="open = false">{{ t('aidr.hooks.cancel') }}</a-button><a-button type="primary" html-type="submit" :disabled="disabled">{{ t('aidr.hooks.commands.addDraft') }}</a-button></div>
      </form>
    </a-modal>
  </section>
</template>
<script setup>
import { ref } from 'vue'
import { DeleteOutlined, BranchesOutlined, CodeOutlined } from '@ant-design/icons-vue'
import { useI18n } from 'vue-i18n'
const props = defineProps({ rules: { type: Array, required: true }, products: { type: Array, required: true }, disabled: Boolean })
const emit = defineEmits(['update:rules'])
const { t } = useI18n()
const open = ref(false), editing = ref({}), condition = ref({}), kind = ref('command'), argsAll = ref(''), argsAny = ref(''), pipeTo = ref(''), error = ref('')
let editingIndex = -1
const presets = [
  { id: 'recursive_delete', icon: DeleteOutlined, example: 'rm -r / -R / --recursive', command: { executable: 'rm', args_any: ['-r', '-R', '--recursive'] } },
  { id: 'git_discard', icon: BranchesOutlined, example: 'git reset --hard', command: { executable: 'git', args_all: ['reset', '--hard'] } },
  { id: 'remote_script', icon: CodeOutlined, example: 'curl … | sh / bash', command: { executable: 'curl', pipe_to: ['sh', 'bash'] } },
]
function edit(rule, index = -1) {
  editingIndex = index
  const { icon, example, ...source } = rule || {}
  editing.value = { id: '', agent: '*', tool: '*', decision: 'deny', ...JSON.parse(JSON.stringify(source)) }
  if (index < 0 && props.rules.some(r => r.id === editing.value.id)) editing.value.id += '_' + (props.rules.length + 1)
  kind.value = !rule || rule.command ? 'command' : 'tool'
  condition.value = { executable: '', args_all: [], args_any: [], path_prefix: '', pipe_to: [], ...editing.value.command }
  argsAll.value = condition.value.args_all.join('\n'); argsAny.value = condition.value.args_any.join('\n'); pipeTo.value = condition.value.pipe_to.join(', ')
  error.value = ''; open.value = true
}
function normalize() { if (editing.value.decision === 'ask' && editing.value.agent !== '*' && !props.products.find(p => p.id === editing.value.agent)?.approval) editing.value.decision = 'deny' }
const lines = text => text.split('\n').map(x => x.trim()).filter(Boolean)
function apply() {
  if (props.disabled) return
  const rule = { id: editing.value.id.trim(), agent: editing.value.agent, tool: kind.value === 'command' ? '*' : editing.value.tool.trim(), decision: editing.value.decision }
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(rule.id) || rule.id === 'default' || props.rules.some((r, i) => i !== editingIndex && r.id === rule.id) || !rule.tool || /\s/.test(rule.tool)) { error.value = t('aidr.hooks.invalid'); return }
  if (kind.value === 'command') {
    rule.command = { executable: condition.value.executable.trim(), args_all: lines(argsAll.value), args_any: lines(argsAny.value), path_prefix: condition.value.path_prefix.trim(), pipe_to: pipeTo.value.split(',').map(x => x.trim()).filter(Boolean) }
    if (!/^[A-Za-z0-9_./+-]{1,128}$/.test(rule.command.executable) || (rule.command.path_prefix && !rule.command.path_prefix.startsWith('/')) || rule.command.args_all.length > 16 || rule.command.args_any.length > 16 || rule.command.pipe_to.length > 8) { error.value = t('aidr.hooks.invalid'); return }
  }
  const next = props.rules.slice(); if (editingIndex < 0) next.push(rule); else next[editingIndex] = rule
  emit('update:rules', next); open.value = false
}
function remove(index) { emit('update:rules', props.rules.filter((_, i) => i !== index)) }
function update(index, key, value) {
  if (props.disabled) return
  const next = props.rules.map((rule, i) => i === index ? { ...rule, [key]: value } : rule)
  if (next[index].decision === 'ask' && next[index].agent !== '*' && !props.products.find(p => p.id === next[index].agent)?.approval) next[index].decision = 'deny'
  emit('update:rules', next)
}
function describe(rule) { const c = rule.command; return c ? [c.executable, ...(c.args_all || []), c.args_any?.length ? `(${c.args_any.join(' / ')})` : '', c.path_prefix || '', c.pipe_to?.length ? `| ${c.pipe_to.join(' / ')}` : ''].filter(Boolean).join(' ') : rule.tool }
</script>
<style scoped>
.preset-library { border-bottom: 1px solid #e4eaf2; padding: 10px 0; }
.preset-library summary { cursor: pointer; color: #405671; font-size: 13px; font-weight: 600; }
.preset-library summary span { margin-left: 12px; color: #77869a; font-size: 12px; font-weight: 400; }
.editor-heading,.dialog-actions{display:flex;justify-content:space-between;align-items:center;gap:12px}.editor-heading h3{margin:0}.presets{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:18px 0}.presets button{text-align:start;display:flex;flex-direction:column;gap:8px;padding:16px;border:1px solid #dbe3ee;background:#f8faff;border-radius:10px;color:#253753;cursor:pointer}.presets button:hover{border-color:#3168ef}.presets span{font:12px monospace;overflow-wrap:anywhere}.presets small{color:#2563eb}.rule-table{overflow:auto;margin-bottom:16px}table{width:100%;border-collapse:collapse}th,td{padding:12px;border-bottom:1px solid #e6ebf2;text-align:start}td code{display:block;max-width:440px;overflow-wrap:anywhere;color:#65758e;margin-top:4px}.rule-form{display:grid;gap:16px}.rule-form label{display:grid;gap:6px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}select{min-height:34px;border:1px solid #d9e0ea;border-radius:6px;background:white;padding:4px 10px;max-width:100%}.help{font-size:13px;color:#66758d;margin:0}.dialog-actions{justify-content:flex-end;position:sticky;bottom:0;padding:12px 0;background:white}button:disabled{opacity:.55;cursor:default}@media(max-width:680px){.presets,.pair{grid-template-columns:1fr}.editor-heading{align-items:flex-start;flex-wrap:wrap}}
.editor-heading p{margin:5px 0 0;font-size:13px;color:#7a879e}.editor-heading h3{font-size:16px}.current-heading{margin:24px 0 12px}.rule-count{font-size:12px;background:#f0f3f8;padding:2px 7px;border-radius:4px;color:#7a879e}.presets{margin:14px 0}.presets button{background:white;display:flex;flex-direction:row;align-items:center;padding:16px;gap:12px;min-width:0}.presets .preset-icon{display:flex;align-items:center;justify-content:center;flex:0 0 40px;height:40px;border-radius:50%;font-size:20px}.recursive_delete{background:#fff0f2;color:#d94459}.git_discard{background:#fff2e9;color:#ca7927}.remote_script{background:#f2edff;color:#7951d4}.presets .preset-copy{display:flex;flex-direction:column;gap:6px;flex:1;min-width:0;font:inherit}.preset-copy strong{font-size:14px}.preset-copy code{font-size:12px;color:#7a879e;overflow-wrap:anywhere}.presets small{flex:0 0 auto;font-size:12px}.rule-table{border:1px solid #e4eaf2;border-radius:8px;margin:0}table{table-layout:fixed}th{background:#f7f9fc;font-size:12px;color:#637189}th:first-child{width:43%}th:last-child{width:140px}td{font-size:13px;vertical-align:middle}td small{color:#7a879e;font-size:11px}td code{font-size:12px}td select{width:100%;font-size:13px}tr:last-child td{border-bottom:0}.native-hint{margin:5px 0 0;font-size:12px;color:#876a35}.decision-deny{color:#bd3543}.decision-ask{color:#ad690f}.decision-allow{color:#24855b}.row-actions{white-space:nowrap}.row-actions :deep(.ant-btn){padding-inline:7px;font-size:13px}.presets button:focus-visible{outline:2px solid #2860ed;outline-offset:2px}@media(max-width:1100px){.presets button{flex-wrap:wrap}.presets small{margin-left:52px}}@media(max-width:680px){.rule-table table,.rule-table tbody,.rule-table tr,.rule-table td{display:block;width:100%}.rule-table thead{display:none}.rule-table td{padding:8px 12px;border:0}.rule-table tr{padding:8px 0;border-bottom:1px solid #e4eaf2}.rule-table tr:last-child{border:0}.row-actions{text-align:end}.presets small{margin-left:0}.presets button{flex-wrap:nowrap}.rule-table td:first-child{padding-bottom:12px}}
</style>
