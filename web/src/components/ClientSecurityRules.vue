<template>
  <section class="security-rules">
    <a-spin v-if="loading && !view" />
    <a-alert v-if="error" type="error" show-icon :message="errorText(error)">
      <template #action><a-popconfirm :title="tr('reloadHelp')" @confirm="load"><a-button size="small" :disabled="busy">{{ tr('reload') }}</a-button></a-popconfirm></template>
    </a-alert>
    <template v-if="view">
      <a-form layout="vertical" class="settings-grid">
        <a-form-item v-if="clientId" :label="tr('source')">
          <a-select :value="source" :aria-label="tr('source')" :options="sourceOptions" :disabled="busy || !editable" @change="changeSource" />
        </a-form-item>
        <a-form-item :label="tr('detectionEnabled')">
          <a-select v-if="clientId" v-model:value="enabledMode" :aria-label="tr('detectionEnabled')" :options="enabledOptions" :disabled="busy || !editable" />
          <a-switch v-else v-model:checked="enabled" :aria-label="tr('detectionEnabled')" :disabled="busy || !editable" />
        </a-form-item>
        <a-form-item :label="tr('defaultAction')"><a-select v-model:value="defaultAction" :aria-label="tr('defaultAction')" :options="actionOptions.filter(x => x.value !== 'none')" :disabled="busy || !editable || source === 'inherit' || source === 'mixed' && view.control.inherit" /></a-form-item>
        <a-form-item :label="t('aidr.hooks.wait.label')" :validate-status="waitInvalid ? 'error' : ''" :help="waitInvalid ? t('aidr.hooks.wait.invalid') : t('aidr.hooks.wait.help')">
          <a-input-number v-model:value="approvalWait" :step="1" :aria-label="t('aidr.hooks.wait.label')" :disabled="busy || !editable || source === 'inherit' || source === 'mixed' && view.control.inherit" />
        </a-form-item>
      </a-form>
      <a-button v-if="clientId && source !== 'custom'" type="link" @click="emit('global')">{{ tr('viewGlobal') }}</a-button>
      <a-tabs v-model:active-key="tab">
        <a-tab-pane key="rules" :tab="tr('rules')">
          <div class="toolbar">
            <a-input-search v-model:value="search" :placeholder="tr('search')" :aria-label="tr('search')" allow-clear @search="flushSearch" />
            <a-select v-model:value="filter" :aria-label="tr('filter')" :options="['all','withAction','riskOnly'].map(value => ({ value, label: tr(value) }))" />
            <a-button type="primary" :disabled="locked || source === 'mixed'" @click="editRule()">{{ tr('addRule') }}</a-button>
            <a-button :disabled="busy || !view.detection" @click="openTest">{{ tr('test') }}</a-button>
          </div>
          <a-table :data-source="rows" :columns="columns" row-key="id" size="small" :pagination="false" :scroll="{ x: 700 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'"><strong>{{ ruleName(record) }}</strong><small>{{ conditionText(record) }}</small><a-button v-if="record.path_set" type="link" class="path-link" @click="tab = 'paths'">{{ pathName(paths.find(p => p.id === record.path_set)) }}</a-button></template>
              <template v-else-if="column.key === 'severity'"><a-tag v-if="record.severity" :color="record.severity === 'high' ? 'red' : 'orange'">{{ t(`aidrRisk.severity.${record.severity}`) }}</a-tag><span v-else>{{ tr('off') }}</span></template>
              <template v-else-if="column.key === 'action'">{{ actionName(record.action) }}</template>
              <template v-else-if="column.key === 'source'">{{ tr(record.source) }}</template>
              <template v-else-if="column.key === 'enabled'"><a-switch size="small" v-model:checked="record.enabled" :disabled="rowLocked(record)" :aria-label="ruleName(record)" /></template>
              <template v-else-if="column.key === 'actions'"><a-space :size="0"><a-button type="link" :disabled="rowLocked(record)" @click="editRule(record)">{{ tr('edit') }}</a-button><a-popconfirm :title="tr('removeTitle')" @confirm="rules = rules.filter(r => r.id !== record.id)"><a-button type="link" danger :disabled="rowLocked(record)">{{ tr('remove') }}</a-button></a-popconfirm></a-space></template>
            </template>
          </a-table>
        </a-tab-pane>
        <a-tab-pane key="paths" :tab="tr('paths')">
          <a-button type="primary" :disabled="locked || source === 'mixed'" @click="editPath()">{{ tr('addPath') }}</a-button>
          <section v-for="group in paths" :key="group.id" class="path-group">
            <header><strong>{{ pathName(group) }}</strong><a-space :size="0"><a-button type="link" :disabled="rowLocked(group)" @click="editPath(group)">{{ tr('edit') }}</a-button><a-popconfirm :title="tr('removePathTitle')" @confirm="paths = paths.filter(p => p.id !== group.id)"><a-button type="link" danger :disabled="rowLocked(group) || references(group.id).length > 0">{{ tr('remove') }}</a-button></a-popconfirm></a-space></header>
            <small v-if="!group.paths.length && !group.builtin_ids.length">{{ tr('emptyPaths') }}</small>
            <code v-for="path in group.paths" :key="path">{{ path }}</code>
            <details v-for="item in catalog.filter(item => group.builtin_ids.includes(item.id))" :key="item.id"><summary>{{ t(`aidrRisk.settings.builtins.${item.id}`) }}</summary><div v-for="spec in item.paths" :key="spec.os + spec.path" class="path-spec"><span>{{ spec.os }}</span><code>{{ spec.path }}</code><small>{{ t(spec.directory ? 'aidrRisk.settings.descendants' : 'aidrRisk.settings.exact') }}</small></div></details>
            <small>{{ tr('references') }}: {{ references(group.id).map(ruleName).join(' · ') || tr('unused') }}</small>
          </section>
          <a-empty v-if="!paths.length" />
        </a-tab-pane>
      </a-tabs>
    </template>
    <a-modal v-model:open="ruleOpen" :z-index="1020" :style="{ top: '24px' }" :body-style="{ maxHeight: 'calc(100dvh - 132px)', overflowY: 'auto' }" :title="tr(editingId ? 'editRule' : 'addRule')" :footer="null" width="min(760px, 100vw)" :mask-closable="false">
      <a-form v-if="draft" :model="draft" layout="vertical" class="rule-form" @finish="applyRule">
        <a-alert v-if="draftError" type="error" :message="tr(draftError)" />
        <a-form-item :label="tr('name')"><a-input v-model:value="draft.name" :aria-label="tr('name')" :placeholder="draft.kind === 'builtin' ? t(`aidrRisk.codes.${draft.code}`) : ''" :maxlength="100" /></a-form-item>
        <div class="form-grid">
          <a-form-item :label="tr('condition')"><a-select v-model:value="draft.kind" :aria-label="tr('condition')" :options="['command','tool','builtin'].map(value => ({ value, label: tr(value) }))" @change="changeKind" /></a-form-item>
          <a-form-item :label="tr('agent')"><a-select :value="Array.isArray(draft.agent) ? draft.agent : [draft.agent]" mode="multiple" :aria-label="tr('agent')" :options="agentOptions" @change="changeAgents" /></a-form-item>
        </div>
        <a-form-item v-if="draft.kind === 'builtin'" :label="tr('template')"><a-select v-model:value="draft.code" :aria-label="tr('template')" :options="builtinCodes.map(value => ({ value, label: t(`aidrRisk.codes.${value}`) }))" /></a-form-item>
        <a-form-item v-else :label="tr('toolName')" :tooltip="tr('toolHelp')"><a-input v-model:value="draft.tool" :aria-label="tr('toolName')" /></a-form-item>
        <template v-if="draft.kind === 'command'">
          <a-form-item :label="tr('executable')"><a-input v-model:value="draft.condition.executable" :aria-label="tr('executable')" placeholder="rm / Remove-Item" /></a-form-item>
          <div class="form-grid"><a-form-item v-for="key in ['args_all','args_any','pipe_to']" :key="key" :label="t(`aidrRisk.commandRules.conditions.${key}`)" :tooltip="tr('onePerLine')"><a-textarea v-model:value="argumentText[key]" :aria-label="t(`aidrRisk.commandRules.conditions.${key}`)" :auto-size="{ minRows: 2, maxRows: 4 }" /></a-form-item></div>
        </template>
        <a-form-item v-if="needsPath" :label="tr('pathReference')" :tooltip="tr('pathReferenceHelp')"><a-select v-model:value="draft.path_set" :aria-label="tr('pathReference')" allow-clear :options="paths.map(p => ({ value: p.id, label: pathName(p) }))" /></a-form-item>
        <a-form-item :label="tr('platforms')" :tooltip="tr('platformHelp')"><a-select v-model:value="draft.platforms" :aria-label="tr('platforms')" mode="multiple" :options="platformOptions" /></a-form-item>
        <div class="form-grid">
          <a-form-item :label="tr('record')"><a-select :value="draft.severity || 'off'" :aria-label="tr('record')" :options="severityOptions" @change="value => draft.severity = value === 'off' ? null : value" /></a-form-item>
          <a-form-item :label="tr('action')" :help="actionLimit ? tr(actionLimit) : unsupportedApprovalAgents.length ? tr('approvalUnavailable', { agents: unsupportedApprovalAgents.join(', ') }) : undefined"><a-select v-model:value="draft.action" :aria-label="tr('action')" :options="actionOptions.map(x => ({ ...x, disabled: x.value !== 'none' && !!actionLimit || x.value === 'ask' && unsupportedApprovalAgents.length > 0 }))" /></a-form-item>
        </div>
        <a-form-item :label="tr('state')"><a-switch v-model:checked="draft.enabled" :aria-label="tr('state')" /></a-form-item>
        <div class="dialog-footer"><a-button @click="ruleOpen = false">{{ tr('cancel') }}</a-button><a-button type="primary" html-type="submit">{{ tr('saveDraft') }}</a-button></div>
      </a-form>
    </a-modal>
    <a-modal v-model:open="pathOpen" :z-index="1020" :style="{ top: '24px' }" :body-style="{ maxHeight: 'calc(100dvh - 132px)', overflowY: 'auto' }" :title="tr('pathSet')" :footer="null" width="min(660px, 100vw)" :mask-closable="false">
      <a-form :model="pathDraft" layout="vertical" @finish="applyPath">
        <a-alert v-if="pathError" type="error" :message="tr(pathError)" />
        <a-form-item :label="tr('name')"><a-input v-model:value="pathDraft.name" :aria-label="tr('name')" :maxlength="100" /></a-form-item>
        <a-form-item :label="tr('builtinPaths')"><a-select v-model:value="pathDraft.builtin_ids" :aria-label="tr('builtinPaths')" mode="multiple" :options="catalog.map(p => ({ value: p.id, label: t(`aidrRisk.settings.builtins.${p.id}`) }))" /></a-form-item>
        <p class="muted">{{ tr('browseBuiltins', { count: catalog.length }) }}</p>
        <a-collapse ghost class="builtin-path-browser">
              <a-collapse-panel v-for="item in catalog" :key="item.id" :header="t(`aidrRisk.settings.builtins.${item.id}`)">
                <template #extra><a-tag v-if="pathDraft.builtin_ids?.includes(item.id)" color="blue">{{ tr('selected') }}</a-tag></template>
                <div v-for="spec in item.paths" :key="spec.os + spec.path" class="path-spec"><span>{{ platformOptions.find(p => p.value === spec.os)?.label }}</span><code>{{ spec.path }}</code><small>{{ t(spec.directory ? 'aidrRisk.settings.descendants' : 'aidrRisk.settings.exact') }}</small></div>
              </a-collapse-panel>
        </a-collapse>
        <a-form-item :label="tr('customPaths')" :tooltip="tr('pathHelp')"><a-textarea v-model:value="pathText" :aria-label="tr('customPaths')" :rows="6" /></a-form-item>
        <div class="dialog-footer"><a-button @click="pathOpen = false">{{ tr('cancel') }}</a-button><a-button type="primary" html-type="submit">{{ tr('saveDraft') }}</a-button></div>
      </a-form>
    </a-modal>
    <a-modal v-model:open="testOpen" :z-index="1020" :style="{ top: '24px' }" :body-style="{ maxHeight: 'calc(100dvh - 132px)', overflowY: 'auto' }" :title="tr('test')" :footer="null" width="min(760px, 100vw)">
      <p class="muted">{{ tr('testHelp') }}</p>
      <a-form :model="testInput" layout="vertical" @finish="test">
        <div class="form-grid"><a-form-item :label="tr('agent')"><a-select v-model:value="testInput.agent" :aria-label="tr('agent')" :options="agentOptions.filter(x => x.value !== '*')" /></a-form-item><a-form-item :label="tr('toolName')"><a-input v-model:value="testInput.tool" :aria-label="tr('toolName')" /></a-form-item><a-form-item :label="tr('platforms')"><a-select v-model:value="testInput.platform" :aria-label="tr('platforms')" :options="platformOptions" /></a-form-item><a-form-item :label="tr('cwd')"><a-input v-model:value="testInput.cwd" :aria-label="tr('cwd')" /></a-form-item></div>
        <a-form-item :label="tr('commandText')"><a-textarea v-model:value="testInput.command" :aria-label="tr('commandText')" :rows="3" /></a-form-item>
        <a-button html-type="submit" :loading="testing" :disabled="testing || !testInput.tool.trim()">{{ tr('test') }}</a-button>
      </a-form>
      <a-alert v-if="testError" type="error" :message="errorText(testError)" />
      <template v-if="testResult"><a-divider /><strong>{{ tr('record') }}</strong><p>{{ t(`aidrRisk.commandRules.results.${testResult.risk.status}`) }}</p><AidrDetectionMatches :matches="testResult.risk.matches" /><a-divider /><strong>{{ tr('action') }}: {{ actionName(testResult.control.decision) }}</strong><p v-if="testResult.control.used_default">{{ tr('usedDefault') }}</p><p v-else>{{ rules.filter(r => testResult.control.security_rule_ids?.includes(r.id)).map(ruleName).join(' · ') }}</p></template>
    </a-modal>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { getSecurityRules, saveSecurityRules, previewSecurityRules } from '../api'
import { localizeApiError } from '../i18n/errors'
import products from '../aidr-products.json'
import AidrDetectionMatches from './AidrDetectionMatches.vue'
const props = defineProps({ clientId: { type: String, default: '' } })
const emit = defineEmits(['saved', 'global'])
const { t, locale } = useI18n(), tr = (key, params) => t(`securityRules.${key}`, params || {})
const clone = value => JSON.parse(JSON.stringify(value))
const view = ref(null), rules = ref([]), paths = ref([]), source = ref('custom'), enabled = ref(true), enabledMode = ref('inherit'), defaultAction = ref('allow'), approvalWait = ref(180)
const waitInvalid = computed(() => !Number.isInteger(approvalWait.value) || approvalWait.value < 30 || approvalWait.value > 300)
const loading = ref(false), saving = ref(false), error = ref(null), baseline = ref(''), tab = ref('rules'), search = ref(''), query = ref(''), filter = ref('all')
const ruleOpen = ref(false), draft = ref(null), draftError = ref(''), editingId = ref(''), argumentText = ref({})
const pathOpen = ref(false), pathDraft = ref({}), pathText = ref(''), pathError = ref('')
const testOpen = ref(false), testing = ref(false), testError = ref(null), testResult = ref(null), testInput = ref({ agent: 'claude', tool: 'Bash', platform: 'linux', cwd: '', command: '' })
let generation = 0, timer, customDraft
const busy = computed(() => loading.value || saving.value)
const editable = computed(() => !!view.value?.detection?.can_edit && !!view.value?.control.can_edit)
const locked = computed(() => busy.value || !editable.value || source.value === 'inherit')
const rowLocked = row => locked.value || source.value === 'mixed' && row.source !== 'client'
const catalog = computed(() => view.value?.detection?.catalog || [])
const builtinCodes = ['sensitive_path_read', 'protected_path_change', 'destructive_command', 'download_to_shell', 'filesystem_format', 'device_write', 'protected_permissions', 'tool_policy_denied', 'system_access_denied']
const actionName = value => value === 'none' ? tr('none') : t(`aidr.hooks.${value}`)
const actionOptions = computed(() => ['none','allow','ask','deny'].map(value => ({ value, label: actionName(value) })))
const severityOptions = computed(() => [{ value: 'off', label: tr('off') }, ...['medium','high'].map(value => ({ value, label: t(`aidrRisk.severity.${value}`) }))])
const platformOptions = [{ value: 'linux', label: 'Linux' }, { value: 'darwin', label: 'macOS' }, { value: 'windows', label: 'Windows' }]
const agentOptions = computed(() => [{ value: '*', label: tr('allAgents') }, ...products.filter(p => p.hooks).map(p => ({ value: p.id, label: p.name }))])
const sourceOptions = computed(() => ['inherit','custom', ...(view.value && (view.value.detection?.rules_mode === 'inherit') !== view.value.control.inherit ? ['mixed'] : [])].map(value => ({ value, label: tr(value) })))
const enabledOptions = computed(() => ['inherit','enabled','disabled'].map(value => ({ value, label: tr(value) })))
const riskEnabled = computed(() => props.clientId ? enabledMode.value === 'inherit' ? view.value?.detection?.global_config.enabled : enabledMode.value === 'enabled' : enabled.value)
const ruleName = row => row.name || (row.kind === 'builtin' ? t(`aidrRisk.codes.${row.code}`) : row.id)
const pathName = row => !row ? '' : ['sensitive','protected'].includes(row.name) && row.id === `detection:${row.name}` ? tr(row.name) : row.name
const references = id => rules.value.filter(row => row.path_set === id)
const conditionText = row => row.kind === 'command' ? [row.condition.executable, ...row.condition.args_all, row.condition.args_any?.join(' / ')].filter(Boolean).join(' ') : row.kind === 'tool' ? `${(Array.isArray(row.agent) ? row.agent : [row.agent]).map(agent => agentOptions.value.find(p => p.value === agent)?.label || agent).join(', ')} · ${row.tool}` : tr('builtin')
const rows = computed(() => rules.value.filter(row => (!query.value || `${ruleName(row)} ${conditionText(row)}`.toLowerCase().includes(query.value.toLowerCase())) && (filter.value === 'all' || (filter.value === 'withAction' ? row.action !== 'none' : row.action === 'none' && row.severity))))
const columns = computed(() => [
  { title: tr('rule'), key: 'name', width: 260, sorter: (a,b) => ruleName(a).localeCompare(ruleName(b)), defaultSortOrder: 'ascend', sortDirections: ['ascend','descend','ascend'] },
  { title: tr('record'), key: 'severity', width: 100, sorter: (a,b) => ({ high: 2, medium: 1 }[a.severity] || 0) - ({ high: 2, medium: 1 }[b.severity] || 0), sortDirections: ['ascend','descend','ascend'] },
  ...[['action',100],['source',90],['enabled',70],['actions',120]].map(([key,width]) => ({ title: tr(key === 'enabled' ? 'state' : key), key, width })),
].map(column => ({ ...column, customCell: () => ({ 'data-label': column.title }) })))
function flushSearch() { clearTimeout(timer); query.value = search.value }
watch(search, value => { clearTimeout(timer); if (!value) flushSearch(); else timer = setTimeout(flushSearch, 300) })
const emptyCondition = () => ({ executable: '', args_all: [], args_any: [], pipe_to: [], path_prefix: '' })
function editRule(row) {
  editingId.value = row?.id || ''; draft.value = clone(row || { id: `security_${crypto.randomUUID().replaceAll('-','')}`, name: '', kind: 'command', code: '', enabled: true, severity: 'medium', action: 'none', agent: '*', tool: '*', platforms: ['linux','darwin','windows'], condition: emptyCondition(), path_set: null, control_id: '', source: props.clientId ? 'client' : 'global' })
  argumentText.value = Object.fromEntries(['args_all','args_any','pipe_to'].map(key => [key, (draft.value.condition?.[key] || []).join('\n')]))
  draftError.value = ''; ruleOpen.value = true
}
function changeKind() { draft.value.condition = draft.value.kind === 'command' ? emptyCondition() : null; draft.value.code = draft.value.kind === 'builtin' ? 'destructive_command' : ''; draft.value.path_set = null }
const needsPath = computed(() => draft.value?.kind === 'command' || draft.value?.kind === 'builtin' && ['sensitive_path_read','protected_path_change','destructive_command','protected_permissions'].includes(draft.value.code))
watch(needsPath, value => { if (!value && draft.value) draft.value.path_set = null })
function changeAgents(values) {
  const previous = Array.isArray(draft.value.agent) ? draft.value.agent : [draft.value.agent]
  const selected = values.includes('*') ? previous.includes('*') && values.length > 1 ? values.filter(x => x !== '*') : ['*'] : values
  draft.value.agent = selected.length === 1 ? selected[0] : selected
}
const unsupportedApprovalAgents = computed(() => {
  const agents = Array.isArray(draft.value?.agent) ? draft.value.agent : [draft.value?.agent]
  return products.filter(p => agents.includes(p.id) && !p.approval).map(p => p.name)
})
const actionLimit = computed(() => {
  if (!draft.value) return ''
  if (draft.value.kind === 'builtin') return 'actionBuiltin'
  if (draft.value.platforms.length !== 3) return 'actionSystems'
  if (draft.value.kind !== 'command') return ''
  const group = paths.value.find(p => p.id === draft.value.path_set)
  if (group && (group.builtin_ids.length || group.paths.length !== 1)) return 'actionPaths'
  if (group && !group.paths[0].startsWith('/')) return 'actionWindowsPath'
  if (draft.value.condition?.executable && !/^[A-Za-z0-9_./+-]+$/.test(draft.value.condition.executable)) return 'actionCommand'
  return ''
})
function applyRule() {
  if (locked.value) return
  const row = clone(draft.value)
  if ((!row.name.trim() && row.kind !== 'builtin') || !row.platforms.length || !row.tool.trim() || row.kind === 'command' && !row.condition.executable.trim()) { draftError.value = 'required'; return }
  if (actionLimit.value && row.action !== 'none') { draftError.value = actionLimit.value; return }
  if (row.action === 'ask' && unsupportedApprovalAgents.value.length) { draftError.value = 'approvalSelection'; return }
  if (Array.isArray(row.agent) && !row.agent.length) { draftError.value = 'agentRequired'; return }
  if (row.kind === 'command') {
    const group = paths.value.find(p => p.id === row.path_set)
    if (group?.builtin_ids.length) { draftError.value = 'commandPathSupport'; return }
    for (const key of ['args_all','args_any','pipe_to']) row.condition[key] = argumentText.value[key].split('\n').filter(Boolean)
  }
  row.path_set ||= null
  rules.value = editingId.value ? rules.value.map(r => r.id === editingId.value ? row : r) : [...rules.value, row]
  ruleOpen.value = false
}
function editPath(row) { pathDraft.value = clone(row || { id: `paths_${crypto.randomUUID().replaceAll('-','')}`, name: '', paths: [], builtin_ids: [], source: props.clientId ? 'client' : 'global' }); pathText.value = pathDraft.value.paths.join('\n'); pathError.value = ''; pathOpen.value = true }
function applyPath() { if (locked.value) return; if (!pathDraft.value.name.trim()) { pathError.value = 'required'; return }; const row = { ...clone(pathDraft.value), paths: pathText.value.split('\n').filter(Boolean) }; paths.value = paths.value.some(p => p.id === row.id) ? paths.value.map(p => p.id === row.id ? row : p) : [...paths.value, row]; pathOpen.value = false }
const document = () => ({ rules: clone(rules.value), path_sets: clone(paths.value) })
function snapshot() { return { document: document(), source: source.value, enabled: enabled.value, enabled_mode: enabledMode.value, default_action: defaultAction.value, approval_wait_seconds: approvalWait.value } }
function accept(value) {
  view.value = clone(value); rules.value = clone(value.rules); paths.value = clone(value.path_sets); enabled.value = value.detection?.enabled ?? true; enabledMode.value = value.detection?.enabled_mode || 'inherit'
  source.value = !props.clientId ? 'custom' : (value.detection?.rules_mode === 'inherit') === value.control.inherit ? value.control.inherit ? 'inherit' : 'custom' : 'mixed'
  defaultAction.value = (props.clientId && value.control.inherit ? value.control.global_policy : value.control.policy)?.default_action || 'allow'
  approvalWait.value = (props.clientId && value.control.inherit ? value.control.global_policy : value.control.policy)?.approval_wait_seconds ?? 180
  baseline.value = JSON.stringify(snapshot()); customDraft = null
}
async function changeSource(value) {
  if (busy.value) return
  if (value === 'custom') { if (customDraft) { rules.value = customDraft.rules; paths.value = customDraft.path_sets; defaultAction.value = customDraft.default_action; approvalWait.value = customDraft.approval_wait_seconds }; rules.value.forEach(r => r.source = 'client'); paths.value.forEach(p => p.source = 'client'); source.value = value; return }
  if (value === 'mixed') { rules.value = clone(view.value.rules); paths.value = clone(view.value.path_sets); approvalWait.value = (view.value.control.inherit ? view.value.control.global_policy : view.value.control.policy)?.approval_wait_seconds ?? 180; source.value = value; return }
  const epoch = generation; customDraft = { ...document(), default_action: defaultAction.value, approval_wait_seconds: approvalWait.value }; loading.value = true; error.value = null
  try { const global = await getSecurityRules(''); if (epoch !== generation) return; rules.value = global.rules; paths.value = global.path_sets; defaultAction.value = global.control.policy?.default_action || 'allow'; approvalWait.value = global.control.policy?.approval_wait_seconds ?? 180; source.value = value }
  catch (cause) { if (epoch === generation) error.value = cause }
  finally { if (epoch === generation) loading.value = false }
}
const needsWaitUpgrade = computed(() => source.value === 'custom' && view.value?.control.policy?.approval_wait_seconds == null)
const canSave = computed(() => !!view.value && editable.value && !busy.value && !waitInvalid.value && (needsWaitUpgrade.value || baseline.value !== JSON.stringify(snapshot())))
const errorText = value => localizeApiError({ code: value?.apiErrorCode, params: value?.apiErrorParams, message: value?.response?.data?.detail || t('aidrRisk.readFailed') }, locale.value)
async function load() { const epoch = ++generation; loading.value = true; error.value = null; try { const result = await getSecurityRules(props.clientId); if (epoch === generation) accept(result) } catch (cause) { if (epoch === generation) error.value = cause } finally { if (epoch === generation) loading.value = false } }
async function save() {
  if (!canSave.value) return
  const epoch = generation, d = view.value.detection, c = view.value.control
  saving.value = true; error.value = null
  try { const result = await saveSecurityRules(props.clientId, { ...snapshot(), expected: { risk: d.revision, risk_global: d.global_revision ?? null, control: c.revision, control_global: c.global_revision ?? null, scope: c.scope_revision ?? null } }); if (epoch === generation) { accept(result); emit('saved'); message.success(tr('saved')) } }
  catch (cause) { if (epoch === generation) error.value = cause }
  finally { if (epoch === generation) saving.value = false }
}
function openTest() { testResult.value = null; testError.value = null; testOpen.value = true }
async function test() {
  if (testing.value) return
  const epoch = generation, payload = { document: document(), ...testInput.value, enabled: !!riskEnabled.value, default_action: defaultAction.value }; testing.value = true; testError.value = null; testResult.value = null
  try { const result = await previewSecurityRules(props.clientId, payload); if (epoch === generation && JSON.stringify(payload) === JSON.stringify({ document: document(), ...testInput.value, enabled: !!riskEnabled.value, default_action: defaultAction.value })) testResult.value = result }
  catch (cause) { if (epoch === generation) testError.value = cause }
  finally { if (epoch === generation) testing.value = false }
}
watch([testInput, rules, paths, defaultAction, riskEnabled], () => { testResult.value = null }, { deep: true })
watch(() => props.clientId, () => { generation++; view.value = null; saving.value = false; ruleOpen.value = pathOpen.value = testOpen.value = false; load() }, { immediate: true })
onBeforeUnmount(() => { generation++; clearTimeout(timer) })
defineExpose({ save, busy, editable, canSave })
</script>
<style scoped>
.settings-grid :deep(.ant-form-item) { margin-bottom:12px; }
.settings-grid,.form-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px; }.settings-grid { grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); }
.toolbar { display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px; }.toolbar .ant-input-search { width:230px;max-width:100%; }.toolbar .ant-select { min-width:160px; }
.security-rules small,.muted { color:#667085;font-size:12px; }.security-rules small { display:block; }.security-rules strong,.security-rules code,.rule-form { overflow-wrap:anywhere; }
.rule-form .ant-form-item { margin-bottom:16px;min-width:0; }
.rule-form :deep(.ant-form-item-control) { min-width:0; }
.rule-form :deep(.ant-form-item-explain) { overflow-wrap:anywhere;white-space:normal; }
.builtin-path-browser { margin:-8px 0 16px; }.builtin-path-browser code { overflow-wrap:anywhere;white-space:pre-wrap; }.builtin-path-browser .path-spec { padding:6px 0; }.builtin-path-browser small { color:#667085; }
.path-link { display:block;padding:0;height:auto;font-size:12px; }.path-group { padding:16px 0;border-bottom:1px solid #eee; }.path-group header,.dialog-footer { display:flex;align-items:center;gap:12px;justify-content:space-between; }.dialog-footer { justify-content:flex-end;position:sticky;bottom:0;background:white;padding:12px 0 0;z-index:1; }.path-group code { display:block;white-space:pre-wrap; }.path-group details { margin:8px 0; }.path-spec { display:flex;gap:8px;flex-wrap:wrap; }summary { cursor:pointer; }.ant-alert { margin-bottom:16px; }
@media(max-width:600px) {
  .settings-grid,.form-grid { grid-template-columns:1fr; }.toolbar .ant-input-search { width:100%; }.dialog-footer { flex-wrap:wrap; }
  .security-rules :deep(.ant-table-content) { overflow-x:visible !important; }.security-rules :deep(.ant-table table) { width:100% !important;min-width:0 !important; }
  .security-rules :deep(.ant-table colgroup),.security-rules :deep(.ant-table-thead) { display:none; }.security-rules :deep(.ant-table-tbody),.security-rules :deep(.ant-table-row) { display:block; }
  .security-rules :deep(.ant-table-row) { padding:10px 0;border-bottom:1px solid #eee; }.security-rules :deep(.ant-table-cell) { display:flex;width:100%;gap:8px;padding:5px 0 !important;border:0;flex-wrap:wrap; }
  .security-rules :deep(.ant-table-cell::before) { content:attr(data-label);color:#667085;flex:0 0 100px;font-size:12px; }.security-rules :deep(.ant-table-cell:first-child) { display:block; }.security-rules :deep(.ant-table-cell:first-child::before) { display:none; }
}
</style>
