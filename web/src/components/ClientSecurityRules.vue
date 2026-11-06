<template>
  <section class="security-rules">
    <a-spin v-if="loading && !view" />
    <a-alert v-if="error" type="error" show-icon :message="errorText(error)">
      <template #action><a-popconfirm :title="tr('reloadHelp')" @confirm="load"><a-button size="small" :disabled="busy">{{ tr('reload') }}</a-button></a-popconfirm></template>
    </a-alert>
    <template v-if="view">
      <SecurityRuleExecution :execution="view.execution" :refreshing="refreshingExecution" @configure="emit('configure')" @refresh="refreshExecution" />
      <p v-if="baseline && baseline !== JSON.stringify(snapshot())" role="status" class="draft-notice">{{ tr('unsavedDraft') }}</p>
      <a-form layout="vertical" class="settings-grid">
        <a-form-item v-if="clientId" :label="tr('source')">
          <a-select :value="source" :aria-label="tr('source')" :options="sourceOptions" :disabled="busy || !editable" @change="changeSource" />
        </a-form-item>
        <a-form-item :label="tr('detectionEnabled')">
          <a-select v-if="clientId" v-model:value="enabledMode" :aria-label="tr('detectionEnabled')" :options="enabledOptions" :disabled="busy || !editable" />
          <a-switch v-else v-model:checked="enabled" :aria-label="tr('detectionEnabled')" :disabled="busy || !editable" />
        </a-form-item>
        <a-form-item :label="tr('defaultAction')"><a-select v-model:value="defaultAction" :aria-label="tr('defaultAction')" :options="actionOptions.filter(x => x.value !== 'none')" :disabled="busy || !editable || source === 'inherit' || source === 'mixed' && view.control.inherit" /></a-form-item>
        <a-form-item :label="t('aidr.hooks.wait.label')" :tooltip="t('aidr.hooks.wait.detail')" :validate-status="waitInvalid ? 'error' : ''" :help="waitInvalid ? t('aidr.hooks.wait.invalid') : t('aidr.hooks.wait.help')">
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
              <template v-if="column.key === 'name'"><strong>{{ ruleName(record) }}</strong><small v-if="record.kind !== 'builtin'">{{ conditionText(record) }}</small><a-button v-if="record.path_set" type="link" class="path-link" @click="tab = 'paths'">{{ pathName(paths.find(p => p.id === record.path_set)) }}</a-button></template>
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
    <a-modal v-model:open="ruleOpen" :z-index="1020" :style="{ top: '24px' }" :body-style="{ maxHeight: 'calc(100dvh - 220px)', overflowY: 'auto' }" :title="tr(editingId ? 'editRule' : 'addRule')" width="min(760px, 100vw)" :mask-closable="false">
      <a-form v-if="draft" ref="ruleForm" name="security-rule" :model="draft" layout="vertical" class="rule-form" @finish="applyRule">
        <a-form-item v-if="!editingId" :label="tr('startExample')"><a-select :value="selectedExample" :aria-label="tr('startExample')" allow-clear :placeholder="tr('chooseExample')" :options="securityRuleExamples.map(item => ({ value: item.id, label: tr('examples.' + item.id) + ' · ' + (item.command || tr('examplesHelp.' + item.id)) }))" @change="selectExample" /></a-form-item>
        <p v-if="selectedExample" class="muted">{{ tr('examplesHelp.' + selectedExample) }}</p>
        <a-form-item name="name" :label="tr('name')" v-bind="fieldError('name')" :required="draft.kind !== 'builtin'"><a-input v-model:value="draft.name" :aria-label="tr('name')" :placeholder="draft.kind === 'builtin' ? t(`aidrRisk.codes.${draft.code}`) : ''" :maxlength="100" /></a-form-item>
        <div class="form-grid">
          <a-form-item :label="tr('condition')"><a-select :value="matchKind" :aria-label="tr('condition')" :options="['command','keywords','networks','tool','builtin'].map(value => ({ value, label: tr(value) }))" @change="changeKind" /></a-form-item>
          <a-form-item name="agent" :label="tr('agent')" v-bind="fieldError('agent')"><a-select :value="Array.isArray(draft.agent) ? draft.agent : [draft.agent]" mode="multiple" :aria-label="tr('agent')" :options="agentOptions" @change="changeAgents" /></a-form-item>
        </div>
        <a-form-item v-if="draft.kind === 'builtin'" :label="tr('template')"><a-select v-model:value="draft.code" :aria-label="tr('template')" :options="builtinCodes.map(value => ({ value, label: t(`aidrRisk.codes.${value}`) }))" /></a-form-item>
        <a-form-item v-if="draft.kind === 'tool'" name="tool" :label="tr('toolName')" :tooltip="tr('toolHelp')" v-bind="fieldError('tool')"><a-input v-model:value="draft.tool" :aria-label="tr('toolName')" placeholder="Bash / Read" /></a-form-item>
        <a-form-item v-if="matchKind === 'command'" name="executable" :label="tr('executable')" :help="ruleErrors.executable ? tr(ruleErrors.executable) : tr('executableHelp')" :validate-status="ruleErrors.executable ? 'error' : ''" required><a-input v-model:value="draft.condition.executable" :aria-label="tr('executable')" placeholder="rm" /></a-form-item>
        <template v-if="matchKind === 'keywords'">
          <a-form-item name="keywords" :label="tr('keywordTerms')" :tooltip="tr('keywordDetail')" :help="ruleErrors.keywords ? tr(ruleErrors.keywords) : tr('keywordHelp')" :validate-status="ruleErrors.keywords ? 'error' : ''" required><a-textarea v-model:value="keywordText" :aria-label="tr('keywordTerms')" :rows="3" placeholder="test.txt" /></a-form-item>
          <div class="form-grid"><a-form-item :label="tr('keywordMode')"><a-select v-model:value="draft.condition.keywords.mode" :aria-label="tr('keywordMode')" :options="['any','all'].map(value => ({ value, label: tr('keywordModes.' + value) }))" /></a-form-item><a-form-item :label="tr('ignoreCase')"><a-switch v-model:checked="draft.condition.keywords.ignore_case" :aria-label="tr('ignoreCase')" /></a-form-item></div>
        </template>
        <a-form-item v-if="matchKind === 'networks'" name="networks" :label="tr('subnets')" :tooltip="tr('networkDetail')" :help="ruleErrors.networks ? tr(ruleErrors.networks) : tr('networkHelp')" :validate-status="ruleErrors.networks ? 'error' : ''" required><a-textarea v-model:value="networkText" :aria-label="tr('subnets')" :rows="3" placeholder="10.10.71.0/24&#10;2001:db8::/32" /></a-form-item>
        <div class="form-grid">
          <a-form-item name="action" :label="tr('action')" :help="ruleErrors.action ? tr(ruleErrors.action) : actionLimit ? tr(actionLimit) : unsupportedApprovalAgents.length ? tr('approvalUnavailable', { agents: unsupportedApprovalAgents.join(', ') }) : undefined" :validate-status="ruleErrors.action ? 'error' : ''"><a-select v-model:value="draft.action" :aria-label="tr('action')" :options="actionOptions.map(x => ({ ...x, disabled: x.value !== 'none' && !!actionLimit || x.value === 'ask' && unsupportedApprovalAgents.length > 0 }))" /></a-form-item>
          <a-form-item name="severity" :label="tr('record')" v-bind="fieldError('severity')"><a-select :value="draft.severity || 'off'" :aria-label="tr('record')" :options="severityOptions" @change="value => draft.severity = value === 'off' ? null : value" /></a-form-item>
        </div>
        <SecurityRuleExecution v-if="draft.action !== 'none'" :execution="view.execution" compact /><p v-if="draft.action !== 'none' && ['keywords', 'networks'].includes(matchKind)" class="muted">{{ tr(matchKind === 'keywords' ? 'keywordClientRequirement' : 'networkClientRequirement') }}</p>
        <a-collapse v-model:active-key="advanced" ghost><a-collapse-panel key="conditions" :header="tr('advanced') + (advancedCount ? ' · ' + advancedCount : '')">
          <a-form-item v-if="draft.kind === 'command'" name="tool" :label="tr('toolRestriction')" :tooltip="tr('toolRestrictionHelp')" v-bind="fieldError('tool')"><a-input v-model:value="draft.tool" :aria-label="tr('toolRestriction')" /></a-form-item>
          <div v-if="matchKind === 'command'" class="form-grid"><a-form-item v-for="key in ['args_all','args_any','pipe_to']" :key="key" :name="key" :label="t(`aidrRisk.commandRules.conditions.${key}`)" :help="ruleErrors[key] ? tr(ruleErrors[key]) : tr('onePerLine')" :validate-status="ruleErrors[key] ? 'error' : ''"><a-textarea v-model:value="argumentText[key]" :aria-label="t(`aidrRisk.commandRules.conditions.${key}`)" :auto-size="{ minRows: 2, maxRows: 4 }" /></a-form-item></div>
          <a-form-item v-if="needsPath" name="path_set" :label="tr('pathReference')" :tooltip="tr('pathReferenceHelp')" v-bind="fieldError('path_set')"><a-select v-model:value="draft.path_set" :aria-label="tr('pathReference')" allow-clear :options="paths.map(p => ({ value: p.id, label: pathName(p) }))" /></a-form-item>
          <a-form-item name="platforms" :label="tr('platforms')" :help="ruleErrors.platforms ? tr(ruleErrors.platforms) : tr('platformHelp')" :validate-status="ruleErrors.platforms ? 'error' : ''"><a-select v-model:value="draft.platforms" :aria-label="tr('platforms')" mode="multiple" :options="platformOptions" /></a-form-item>
        </a-collapse-panel></a-collapse>
        <p class="rule-summary" role="status">{{ draftSummary }}</p>
        <details class="draft-test"><summary>{{ tr('testCurrent') }}</summary><p class="muted">{{ tr('testHelp') }}</p><a-textarea v-model:value="draftTestCommand" :aria-label="tr('commandText')" :rows="2" /><a-button :loading="draftTesting" :disabled="draftTesting || !draftTestCommand.trim()" @click="testDraft">{{ tr('test') }}</a-button><a-alert v-if="draftTestError" type="error" :message="errorText(draftTestError)" /><p v-if="draftTestResult" role="status">{{ tr('record') }}: {{ t('aidrRisk.commandRules.results.' + draftTestResult.risk.status) }} · {{ tr('execution.ruleDecision') }}: {{ actionName(draftTestResult.control.decision) }}</p><SecurityRuleExecution v-if="draftTestResult" :execution="draftTestResult.execution" compact /><p v-for="hit in draftTestResult?.control.keyword_matches || []" :key="hit.rule_id">{{ tr('matchedKeywords') }}: {{ hit.terms.join(', ') }}</p><template v-for="hit in draftTestResult?.control.network_matches || []" :key="hit.rule_id"><p v-for="address in hit.addresses" :key="address.ip + address.subnet">{{ tr('matchedIP') }}: {{ address.ip }} → {{ address.subnet }}</p></template><template v-if="exampleDefinition?.command"><p>{{ tr('matchExample') }}: <code>{{ exampleDefinition.command }}</code></p><p>{{ tr('missExample') }}: <code>{{ exampleDefinition.miss }}</code></p></template></details>
        <a-form-item :label="tr('state')"><a-switch v-model:checked="draft.enabled" :aria-label="tr('state')" /></a-form-item>
      </a-form>
      <template #footer><div class="rule-footer"><span v-if="Object.keys(ruleErrors).length" role="alert" class="field-error">{{ tr('errorCount', { count: Object.keys(ruleErrors).length }) }} <a-button type="link" @click="focusRuleError">{{ tr('locateError') }}</a-button></span><a-space><a-button @click="ruleOpen = false">{{ tr('cancel') }}</a-button><a-button type="primary" :disabled="locked" @click="applyRule">{{ tr('saveDraft') }}</a-button></a-space></div></template>
    </a-modal>
    <a-modal v-model:open="pathOpen" :z-index="1020" :style="{ top: '24px' }" :body-style="{ maxHeight: 'calc(100dvh - 220px)', overflowY: 'auto' }" :title="tr('pathSet')" width="min(660px, 100vw)" :mask-closable="false">
      <a-form :model="pathDraft" layout="vertical" @finish="applyPath">
        <a-form-item :label="tr('name')" :validate-status="pathError && !pathDraft.name.trim() ? 'error' : ''" :help="pathError && !pathDraft.name.trim() ? tr('nameRequired') : undefined" required><a-input id="security-path-name" v-model:value="pathDraft.name" :aria-label="tr('name')" :maxlength="100" /></a-form-item>
        <a-form-item :label="tr('builtinPaths')"><a-select v-model:value="pathDraft.builtin_ids" :aria-label="tr('builtinPaths')" mode="multiple" :options="catalog.map(p => ({ value: p.id, label: t(`aidrRisk.settings.builtins.${p.id}`) }))" /></a-form-item>
        <p class="muted">{{ tr('browseBuiltins', { count: catalog.length }) }}</p>
        <a-collapse ghost class="builtin-path-browser">
              <a-collapse-panel v-for="item in catalog" :key="item.id" :header="t(`aidrRisk.settings.builtins.${item.id}`)">
                <template #extra><a-tag v-if="pathDraft.builtin_ids?.includes(item.id)" color="blue">{{ tr('selected') }}</a-tag></template>
                <div v-for="spec in item.paths" :key="spec.os + spec.path" class="path-spec"><span>{{ platformOptions.find(p => p.value === spec.os)?.label }}</span><code>{{ spec.path }}</code><small>{{ t(spec.directory ? 'aidrRisk.settings.descendants' : 'aidrRisk.settings.exact') }}</small></div>
              </a-collapse-panel>
        </a-collapse>
        <a-form-item :label="tr('customPaths')" :tooltip="tr('pathHelp')"><a-textarea v-model:value="pathText" :aria-label="tr('customPaths')" :rows="6" /></a-form-item>
      </a-form>
      <template #footer><div class="rule-footer"><span v-if="pathError && !pathDraft.name.trim()" class="field-error" role="alert">{{ tr('nameRequired') }}</span><a-space><a-button @click="pathOpen = false">{{ tr('cancel') }}</a-button><a-button type="primary" :disabled="locked" @click="applyPath">{{ tr('saveDraft') }}</a-button></a-space></div></template>
    </a-modal>
    <a-modal v-model:open="testOpen" :z-index="1020" :style="{ top: '24px' }" :body-style="{ maxHeight: 'calc(100dvh - 132px)', overflowY: 'auto' }" :title="tr('test')" :footer="null" width="min(760px, 100vw)">
      <p class="muted">{{ tr('testHelp') }}</p>
      <a-form :model="testInput" layout="vertical" @finish="test">
        <div class="form-grid"><a-form-item :label="tr('agent')"><a-select v-model:value="testInput.agent" :aria-label="tr('agent')" :options="agentOptions.filter(x => x.value !== '*')" /></a-form-item><a-form-item :label="tr('toolName')"><a-input v-model:value="testInput.tool" :aria-label="tr('toolName')" /></a-form-item><a-form-item :label="tr('platforms')"><a-select v-model:value="testInput.platform" :aria-label="tr('platforms')" :options="platformOptions" /></a-form-item><a-form-item :label="tr('cwd')"><a-input v-model:value="testInput.cwd" :aria-label="tr('cwd')" /></a-form-item></div>
        <a-form-item :label="tr('commandText')"><a-textarea v-model:value="testInput.command" :aria-label="tr('commandText')" :rows="3" /></a-form-item>
        <a-button html-type="submit" :loading="testing" :disabled="testing || !testInput.tool.trim()">{{ tr('test') }}</a-button>
      </a-form>
      <a-alert v-if="testError" type="error" :message="errorText(testError)" />
      <template v-if="testResult"><a-divider /><strong>{{ tr('record') }}</strong><p>{{ t(`aidrRisk.commandRules.results.${testResult.risk.status}`) }}</p><AidrDetectionMatches :matches="testResult.risk.matches" /><a-divider /><strong>{{ tr('execution.ruleDecision') }}: {{ actionName(testResult.control.decision) }}</strong><p v-if="testResult.control.used_default">{{ tr('usedDefault') }}</p><p v-else>{{ rules.filter(r => testResult.control.security_rule_ids?.includes(r.id)).map(ruleName).join(' · ') }}</p><SecurityRuleExecution :execution="testResult.execution" compact /></template>
    </a-modal>
  </section>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import { getSecurityRules, saveSecurityRules, previewSecurityRules } from '../api'
import { localizeApiError } from '../i18n/errors'
import products from '../aidr-products.json'
import AidrDetectionMatches from './AidrDetectionMatches.vue'
import securityRuleExamples from '../utils/securityRuleExamples.json'
import SecurityRuleExecution from './SecurityRuleExecution.vue'
import { validCommandSubnet } from '../utils/commandSubnet'
const props = defineProps({ clientId: { type: String, default: '' }, active: { type: Boolean, default: true } })
const emit = defineEmits(['saved', 'global', 'configure'])
const { t, locale } = useI18n(), tr = (key, params) => t(`securityRules.${key}`, params || {})
const clone = value => JSON.parse(JSON.stringify(value))
const view = ref(null), rules = ref([]), paths = ref([]), source = ref('custom'), enabled = ref(true), enabledMode = ref('inherit'), defaultAction = ref('allow'), approvalWait = ref(180)
const waitInvalid = computed(() => !Number.isInteger(approvalWait.value) || approvalWait.value < 30 || approvalWait.value > 300)
const loading = ref(false), saving = ref(false), error = ref(null), baseline = ref(''), tab = ref('rules'), search = ref(''), query = ref(''), filter = ref('all')
const refreshingExecution = ref(false)
const ruleOpen = ref(false), draft = ref(null), editingId = ref(''), argumentText = ref({})
const ruleForm = ref(), submitted = ref(false), advanced = ref([]), selectedExample = ref(), keywordText = ref(''), networkText = ref('')
const draftTestCommand = ref(''), draftTesting = ref(false), draftTestResult = ref(null), draftTestError = ref(null)
let initialRuleDraft = ''
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
const conditionText = row => row.condition?.networks ? tr('networkCondition', { subnets: row.condition.networks.subnets.join(', ') }) : row.condition?.keywords ? tr('keywordCondition', { mode: tr('keywordModes.' + row.condition.keywords.mode), terms: row.condition.keywords.terms.join(', ') }) : row.kind === 'command' ? [row.condition.executable, ...(row.condition.args_all || []), row.condition.args_any?.join(' / ')].filter(Boolean).join(' ') : row.kind === 'tool' ? `${(Array.isArray(row.agent) ? row.agent : [row.agent]).map(agent => agentOptions.value.find(p => p.value === agent)?.label || agent).join(', ')} · ${row.tool}` : t(`aidrRisk.codes.${row.code}`)
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
  keywordText.value = (draft.value.condition?.keywords?.terms || []).join('\n')
  networkText.value = (draft.value.condition?.networks?.subnets || []).join('\n')
  submitted.value = false; advanced.value = []; selectedExample.value = undefined; draftTestResult.value = null; draftTestError.value = null; draftTestCommand.value = ''
  ruleOpen.value = true; initialRuleDraft = ruleDraftIdentity()
}
const matchKind = computed(() => draft.value?.condition?.networks ? 'networks' : draft.value?.condition?.keywords ? 'keywords' : draft.value?.kind)
function changeKind(value) {
  draft.value.kind = ['keywords','networks'].includes(value) ? 'command' : value
  draft.value.condition = draft.value.kind === 'command' ? emptyCondition() : null
  if (value === 'networks') draft.value.condition.networks = { subnets: [] }
  if (value === 'keywords') draft.value.condition.keywords = { terms: [], mode: 'any', ignore_case: false }
  argumentText.value = { args_all: '', args_any: '', pipe_to: '' }; keywordText.value = ''; networkText.value = ''
  draft.value.code = value === 'builtin' ? 'destructive_command' : ''; draft.value.path_set = null
}
const needsPath = computed(() => matchKind.value === 'command' || draft.value?.kind === 'builtin' && ['sensitive_path_read','protected_path_change','destructive_command','protected_permissions'].includes(draft.value.code))
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
const lines = value => value.split('\n').filter(value => value.length > 0)
const byteLength = value => new TextEncoder().encode(value).length
function currentRule() {
  const row = clone(draft.value)
  if (row.kind === 'command') {
    if (row.condition.networks) row.condition.networks.subnets = lines(networkText.value)
    else if (row.condition.keywords) row.condition.keywords.terms = lines(keywordText.value)
    else for (const key of ['args_all','args_any','pipe_to']) row.condition[key] = lines(argumentText.value[key] || '')
  }
  row.path_set ||= null
  return row
}
function validateRule() {
  if (!draft.value) return {}
  const row = currentRule(), errors = {}
  if (!row.name.trim() && row.kind !== 'builtin') errors.name = 'nameRequired'
  if (Array.isArray(row.agent) && !row.agent.length) errors.agent = 'agentRequired'
  if (!row.tool.trim() || /\s/.test(row.tool) || row.tool.length > 256) errors.tool = 'toolInvalid'
  if (!row.platforms.length) errors.platforms = 'platformRequired'
  if (matchKind.value === 'command') {
    if (!row.condition.executable.trim()) errors.executable = 'commandRequired'
    else if (byteLength(row.condition.executable) > 128 || !/^[A-Za-z0-9_./+\-]+$/.test(row.condition.executable) && !/^[A-Za-z]:\\/.test(row.condition.executable)) errors.executable = 'commandInvalid'
    for (const key of ['args_all','args_any','pipe_to']) {
      if (row.condition[key].length > (key === 'pipe_to' ? 8 : 16) || row.condition[key].some(value => byteLength(value) > (key === 'pipe_to' ? 128 : 256) || /[\x00-\x1f]/.test(value) || key === 'pipe_to' && !/^[A-Za-z0-9_.+\-]+$/.test(value))) errors[key] = 'argumentsInvalid'
    }
  }
  if (matchKind.value === 'keywords' && (!row.condition.keywords.terms.length || row.condition.keywords.terms.length > 16 || row.condition.keywords.terms.some(value => !value.trim() || byteLength(value) > 256 || /[\x00-\x1f]/.test(value)))) errors.keywords = 'keywordsInvalid'
  if (matchKind.value === 'networks' && (!row.condition.networks.subnets.length || row.condition.networks.subnets.length > 16 || row.condition.networks.subnets.some(value => !validCommandSubnet(value)))) errors.networks = 'networksInvalid'
  if (actionLimit.value && row.action !== 'none') errors.action = actionLimit.value
  if (row.action === 'ask' && unsupportedApprovalAgents.value.length) errors.action = 'approvalSelection'
  if (row.action === 'none' && !row.severity) errors.severity = 'effectRequired'
  if (row.kind === 'command' && paths.value.find(p => p.id === row.path_set)?.builtin_ids.length) errors.path_set = 'commandPathSupport'
  if (selectedExample.value === 'sensitiveRead' && !row.path_set) errors.path_set = 'pathRequired'
  return errors
}
const ruleErrors = computed(() => submitted.value ? validateRule() : {})
const fieldError = key => ({ validateStatus: ruleErrors.value[key] ? 'error' : '', help: ruleErrors.value[key] ? tr(ruleErrors.value[key]) : undefined })
async function focusRuleError() {
  const key = Object.keys(ruleErrors.value)[0]
  if (['tool','platforms','args_all','args_any','pipe_to','path_set'].includes(key)) advanced.value = ['conditions']
  await nextTick()
  ruleForm.value?.scrollToField(key, { behavior: 'smooth', block: 'center' })
  window.document.getElementById(`security-rule_${key}`)?.focus({ preventScroll: true })
}
function ruleDraftIdentity() { return JSON.stringify([draft.value, argumentText.value, keywordText.value, networkText.value]) }
const exampleDefinition = computed(() => securityRuleExamples.find(item => item.id === selectedExample.value))
function selectExample(value) {
  if (!value) { selectedExample.value = undefined; return }
  const fill = () => {
    const item = securityRuleExamples.find(item => item.id === value)
    changeKind(item.networks ? 'networks' : item.keywords ? 'keywords' : item.kind || 'command')
    Object.assign(draft.value, { name: tr('examples.' + value), agent: '*', tool: item.kind === 'tool' ? '' : '*', platforms: ['linux','darwin','windows'], severity: 'medium', action: item.action, enabled: true })
    if (draft.value.condition) Object.assign(draft.value.condition, item.networks ? { networks: clone(item.networks) } : item.keywords ? { keywords: clone(item.keywords) } : { executable: item.executable })
    if (item.code) draft.value.code = item.code
    if (value === 'sensitiveRead') draft.value.path_set = paths.value.find(p => p.id === 'detection:sensitive')?.id || null
    keywordText.value = (item.keywords?.terms || []).join('\n')
    networkText.value = (item.networks?.subnets || []).join('\n')
    argumentText.value = { args_all: (item.args_all || []).join('\n'), args_any: '', pipe_to: '' }
    selectedExample.value = value; draftTestCommand.value = item.command || ''; draftTestResult.value = null; submitted.value = false
    advanced.value = item.args_all?.length || value === 'sensitiveRead' ? ['conditions'] : []
    initialRuleDraft = ruleDraftIdentity()
  }
  if (ruleDraftIdentity() !== initialRuleDraft) Modal.confirm({ zIndex: 1030, title: tr('replaceExample'), content: tr('replaceExampleHelp'), okText: tr('replace'), cancelText: tr('cancel'), onOk: fill })
  else fill()
}
const advancedCount = computed(() => draft.value ? (draft.value.tool !== '*' ? 1 : 0) + (draft.value.path_set ? 1 : 0) + (draft.value.platforms.length !== 3 ? 1 : 0) + Object.values(argumentText.value).filter(value => value?.length).length : 0)
const draftSummary = computed(() => {
  if (!draft.value) return ''
  const row = currentRule(), agents = (Array.isArray(row.agent) ? row.agent : [row.agent]).map(id => agentOptions.value.find(item => item.value === id)?.label || id).join(', ')
  return tr('ruleSummary', { agents, condition: conditionText(row), action: actionName(row.action), record: row.severity ? t('aidrRisk.severity.' + row.severity) : tr('off') })
})
function applyRule() {
  if (locked.value) return
  submitted.value = true
  if (Object.keys(ruleErrors.value).length) { void focusRuleError(); return }
  const row = currentRule()
  rules.value = editingId.value ? rules.value.map(r => r.id === editingId.value ? row : r) : [...rules.value, row]
  ruleOpen.value = false
  message.success(tr('draftAdded'))
}
async function testDraft() {
  if (draftTesting.value) return
  submitted.value = true
  if (Object.keys(ruleErrors.value).length) { await focusRuleError(); return }
  const row = currentRule(), identity = ruleDraftIdentity(), command = draftTestCommand.value, epoch = generation
  const agent = (Array.isArray(row.agent) ? row.agent[0] : row.agent) === '*' ? 'claude' : Array.isArray(row.agent) ? row.agent[0] : row.agent
  draftTesting.value = true; draftTestError.value = null; draftTestResult.value = null
  try {
    const result = await previewSecurityRules(props.clientId, { document: { rules: [row], path_sets: clone(paths.value) }, command, cwd: '', platform: row.platforms[0], agent, tool: row.tool === '*' ? 'Bash' : row.tool, enabled: !!riskEnabled.value, default_action: defaultAction.value })
    if (epoch === generation && ruleOpen.value && identity === ruleDraftIdentity() && command === draftTestCommand.value) draftTestResult.value = result
  } catch (cause) { if (epoch === generation && ruleOpen.value && identity === ruleDraftIdentity() && command === draftTestCommand.value) draftTestError.value = cause }
  finally { draftTesting.value = false }
}
watch([draft, argumentText, keywordText, networkText, draftTestCommand], () => { draftTestResult.value = null; draftTestError.value = null }, { deep: true })
function editPath(row) { pathDraft.value = clone(row || { id: `paths_${crypto.randomUUID().replaceAll('-','')}`, name: '', paths: [], builtin_ids: [], source: props.clientId ? 'client' : 'global' }); pathText.value = pathDraft.value.paths.join('\n'); pathError.value = ''; pathOpen.value = true }
async function applyPath() { if (locked.value) return; if (!pathDraft.value.name.trim()) { pathError.value = 'nameRequired'; await nextTick(); const input = window.document.getElementById('security-path-name'); input?.scrollIntoView({ block: 'center' }); input?.focus({ preventScroll: true }); return }; const row = { ...clone(pathDraft.value), paths: pathText.value.split('\n').filter(Boolean) }; paths.value = paths.value.some(p => p.id === row.id) ? paths.value.map(p => p.id === row.id ? row : p) : [...paths.value, row]; pathOpen.value = false; message.success(tr('draftAdded')) }
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
async function load() { const epoch = ++generation; refreshingExecution.value = false; loading.value = true; error.value = null; try { const result = await getSecurityRules(props.clientId); if (epoch === generation) accept(result) } catch (cause) { if (epoch === generation) error.value = cause } finally { if (epoch === generation) loading.value = false } }
async function refreshExecution() {
  if (refreshingExecution.value || !view.value) return
  const epoch = generation
  const currentView = view.value
  refreshingExecution.value = true
  try {
    const result = await getSecurityRules(props.clientId)
    if (epoch === generation && view.value === currentView) view.value.execution = result.execution
  } catch {
    if (epoch === generation && view.value === currentView) view.value.execution = null
  } finally { if (epoch === generation) refreshingExecution.value = false }
}
async function save() {
  if (!canSave.value) return
  const epoch = generation, d = view.value.detection, c = view.value.control
  saving.value = true; error.value = null
  try { const result = await saveSecurityRules(props.clientId, { ...snapshot(), expected: { risk: d.revision, risk_global: d.global_revision ?? null, control: c.revision, control_global: c.global_revision ?? null, scope: c.scope_revision ?? null } }); if (epoch === generation) { accept(result); emit('saved'); message.info(tr('execution.saved', { effect: tr('execution.states.' + (result.execution?.state || 'unknown')) })) } }
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
watch(() => props.clientId, () => { generation++; view.value = null; saving.value = false; refreshingExecution.value = false; ruleOpen.value = pathOpen.value = testOpen.value = false; load() }, { immediate: true })
watch(() => props.active, value => { if (value) void refreshExecution() })
onBeforeUnmount(() => { generation++; clearTimeout(timer) })
defineExpose({ save, busy, editable, canSave })
</script>
<style scoped>
.settings-grid :deep(.ant-form-item) { margin-bottom:12px; }
.settings-grid,.form-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px; }
.settings-grid { grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }
.settings-grid :deep(.ant-input-number) { width:100%; }
.toolbar { display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px; }.toolbar .ant-input-search { width:230px;max-width:100%; }.toolbar .ant-select { min-width:160px; }
.security-rules small,.muted { color:#667085;font-size:12px; }.security-rules small { display:block; }.security-rules strong,.security-rules code,.rule-form { overflow-wrap:anywhere; }
.rule-form .ant-form-item { margin-bottom:16px;min-width:0; }
.rule-form :deep(.ant-form-item-control) { min-width:0; }
.rule-form :deep(.ant-form-item-explain) { overflow-wrap:anywhere;white-space:normal; }
.rule-footer { display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap; }
.rule-footer :deep(.ant-space) { margin-inline-start:auto; }
.field-error { color:#c93636;overflow-wrap:anywhere;text-align:start; }
.rule-summary { background:#f4f7fb;padding:10px 12px;border-radius:6px;white-space:pre-wrap; }
.draft-notice { color:#80551c;font-size:13px; }
.draft-test { margin:12px 0; }.draft-test :deep(.ant-btn) { margin-top:8px; }
.builtin-path-browser { margin:-8px 0 16px; }.builtin-path-browser code { overflow-wrap:anywhere;white-space:pre-wrap; }.builtin-path-browser .path-spec { padding:6px 0; }.builtin-path-browser small { color:#667085; }
.path-link { display:block;padding:0;height:auto;font-size:12px; }.path-group { padding:16px 0;border-bottom:1px solid #eee; }.path-group header,.dialog-footer { display:flex;align-items:center;gap:12px;justify-content:space-between; }.dialog-footer { justify-content:flex-end;position:sticky;bottom:0;background:white;padding:12px 0 0;z-index:1; }.path-group code { display:block;white-space:pre-wrap; }.path-group details { margin:8px 0; }.path-spec { display:flex;gap:8px;flex-wrap:wrap; }summary { cursor:pointer; }.ant-alert { margin-bottom:16px; }
@media(max-width:600px) {
  .security-rules { padding-inline-end:16px; }
  .settings-grid,.form-grid { grid-template-columns:1fr; }.toolbar .ant-input-search { width:100%; }.dialog-footer { flex-wrap:wrap; }
  .security-rules :deep(.ant-table-content) { overflow-x:visible !important; }.security-rules :deep(.ant-table table) { width:100% !important;min-width:0 !important; }
  .security-rules :deep(.ant-table colgroup),.security-rules :deep(.ant-table-thead) { display:none; }.security-rules :deep(.ant-table-tbody),.security-rules :deep(.ant-table-row) { display:block; }
  .security-rules :deep(.ant-table-row) { padding:10px 0;border-bottom:1px solid #eee; }.security-rules :deep(.ant-table-cell) { display:flex;width:100%;gap:8px;padding:5px 0 !important;border:0;flex-wrap:wrap; }
  .security-rules :deep(.ant-table-cell::before) { content:attr(data-label);color:#667085;flex:0 0 100px;font-size:12px; }.security-rules :deep(.ant-table-cell:first-child) { display:block; }.security-rules :deep(.ant-table-cell:first-child::before) { display:none; }
}
</style>
