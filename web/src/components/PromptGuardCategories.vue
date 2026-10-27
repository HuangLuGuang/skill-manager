<template>
  <div class="guard-workbench">
    <aside class="guard-navigation">
      <a-input-search v-model:value="query" allow-clear :placeholder="w('search')" :aria-label="w('search')" />
      <template v-if="query.trim()">
        <p class="category-hint">{{ w('aiTab') }} · {{ matches.length }}</p>
        <a-empty v-if="!matches.length" :description="w('searchEmpty')" />
        <button v-for="item in matches" :key="item.id" class="search-result" @click="locate(item)">
          <small>{{ categoryName(item.category) }} →</small><strong>{{ checkName(item.id) }}</strong>
          <small v-if="!categoryConfig(item.category).enabled || categoryConfig(item.category).disabled_rules.includes(item.id)">{{ w('disabled') }}</small>
        </button>
      </template>
      <template v-else>
        <template v-if="!semantic">
          <div class="nav-heading">{{ w('native') }}</div><p class="category-hint">{{ w('nativeHint') }}</p>
          <div v-for="item in nativeCatalog" :key="`native:${item.id}`" class="nav-item" :class="{ active: selected === `native:${item.id}` }">
            <button :aria-pressed="selected === `native:${item.id}`" @click="select(`native:${item.id}`)">{{ t(`promptGuard.rsguard.categories.${item.id}`) }}</button>
            <a-switch size="small" :checked="!config.rsguard_disabled_categories.includes(item.id)" :aria-label="t(`promptGuard.rsguard.categories.${item.id}`)" :disabled="disabled || !editable" @change="value => toggleNative(item.id, value)" />
          </div>
        </template>
        <div class="nav-heading"><span>{{ w(semantic ? 'categories' : 'generic') }}</span><a-button v-if="editable" type="link" size="small" :disabled="disabled" @click="openEditor('category')">+ {{ w('addCategory') }}</a-button></div>
        <p class="category-hint">{{ w('scopeHint') }}</p>
        <div v-for="item in categories" :key="item.id" class="nav-item" :class="{ active: selected === item.id, inactive: !categoryConfig(item.id).enabled }">
          <button :aria-pressed="selected === item.id" @click="select(item.id)"><span>{{ categoryName(item.id) }}</span><small>{{ enabledCount(item.id) }}/{{ item.rules.length }} {{ w('countAI') }} · {{ countsFailed ? '—' : textCount(item.id) }} {{ w('countText') }}</small></button>
          <a-switch size="small" :checked="categoryConfig(item.id).enabled" :aria-label="categoryName(item.id)" :disabled="disabled || !editable" @change="value => updateCategory(item.id, { enabled: value })" />
        </div>
      </template>
      <a-alert v-if="countsFailed" type="warning" :message="w('countsFailed')"><template #action><a-button size="small" @click="loadCounts">{{ w('retry') }}</a-button></template></a-alert>
    </aside>
    <section v-if="nativeSelected" class="guard-detail">
      <div class="detail-heading"><h3>{{ t(`promptGuard.rsguard.categories.${nativeSelected}`) }}</h3><a-tag :color="config.rsguard_disabled_categories.includes(nativeSelected) ? 'default' : 'green'">{{ w(config.rsguard_disabled_categories.includes(nativeSelected) ? 'disabled' : 'enabled') }}</a-tag></div>
      <p>{{ w('nativeDetail') }}</p><a-alert type="info" show-icon :message="w('nativeHint')" /><p class="category-hint">{{ w('nativeRisk') }}</p>
    </section>
    <section v-else class="guard-detail" ref="detailElement">
      <div class="detail-heading"><h3>{{ categoryName(selected) }}</h3><a-tag :color="current.enabled ? 'green' : 'default'">{{ w(current.enabled ? 'enabled' : 'disabled') }}</a-tag>
        <a-space v-if="config.custom_categories[selected] && editable" class="category-actions"><a-button size="small" :disabled="disabled" @click="openEditor('category', selected)">{{ w('edit') }}</a-button><a-button danger size="small" :disabled="disabled || countsFailed" @click="remove('category', selected)">{{ w('delete') }}</a-button></a-space>
      </div>
      <p class="category-hint">{{ config.custom_categories[selected]?.description || w(selected === 'operations' ? 'operationsDescription' : selected === 'topics' ? 'topicsDescription' : selected === 'politics' ? 'politicsDescription' : 'genericDescription') }}</p>
      <a-alert v-if="!current.enabled" type="info" show-icon :message="w('offHint')" />
      <a-tabs v-model:active-key="detailTab">
        <a-tab-pane key="ai" :tab="w('aiTab')" force-render>
          <a-alert v-if="!semantic && !config.image_model_id" type="info" :message="w('noImage')" />
          <div v-if="semantic" class="category-model"><span>{{ w('detector') }}</span><strong>{{ current.model_id ? modelLabel(current.model_id) : w('inherit') }}</strong><a-button type="link" size="small" @click="modelExpanded = !modelExpanded">{{ w(modelExpanded ? 'collapse' : 'customize') }}</a-button><a-button v-if="current.model_id && editable" type="link" size="small" :disabled="disabled" @click="updateCategory(selected, { model_id: null }); modelExpanded = false">{{ w('restore') }}</a-button></div>
          <a-select v-if="semantic && modelExpanded" class="category-model-select" :value="current.model_id ?? undefined" :options="modelOptions" :placeholder="w('inherit')" allow-clear show-search option-filter-prop="label" :disabled="disabled || !editable" @change="value => updateCategory(selected, { model_id: value ?? null })" />
          <slot v-if="selected === 'topics'" name="topics" />
          <div class="ai-toolbar"><span class="category-hint">{{ w('customCheckHint') }}</span><a-button v-if="editable" type="primary" size="small" :disabled="disabled" @click="openEditor('check')">+ {{ w('addCheck') }}</a-button></div>
          <a-table size="small" row-key="id" :columns="columns" :data-source="currentChecks" :pagination="false" :scroll="{ x: 760 }" :row-class-name="item => item.id === highlighted ? 'guard-highlight' : ''">
            <template #emptyText>{{ w('noChecks') }}</template>
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'"><strong>{{ checkName(record.id) }}</strong><small v-if="record.custom" class="custom-label">{{ w('custom') }}</small></template>
              <template v-else-if="column.key === 'enabled'"><a-switch size="small" :checked="!current.disabled_rules.includes(record.id)" :aria-label="checkName(record.id)" :disabled="disabled || !editable" @change="value => toggleCheck(record.id, value)" /></template>
              <template v-else-if="column.key === 'risk'"><a-select :value="current.rule_severities[record.id]" :options="severityOptions" :aria-label="`${checkName(record.id)}: ${w('risk')}`" :disabled="disabled || !editable" @change="value => updateCategory(selected, { rule_severities: { ...current.rule_severities, [record.id]: value } })" /></template>
              <template v-else-if="column.key === 'description'"><span class="check-description">{{ checkDescription(record.id) }}</span></template>
              <template v-else><a-space :size="0" wrap><a-button v-if="editable" size="small" type="link" :disabled="disabled" @click="openEditor('check', record.id)">{{ w(record.custom ? 'edit' : 'checkTestAction') }}</a-button><a-button v-if="editable && record.custom" size="small" type="link" danger :disabled="disabled" @click="remove('check', record.id)">{{ w('delete') }}</a-button></a-space></template>
            </template>
          </a-table>
          <p class="category-hint">{{ w('riskHelp') }}</p>
        </a-tab-pane>
        <a-tab-pane key="text" :tab="w('textTab')" force-render>
          <a-tag color="orange">{{ w('immediate') }}</a-tag>
          <a-alert v-if="unsavedCategory" :message="w('newCategoryText')" type="info" show-icon />
          <PromptGuardRules :category="selected" :editable="editable && !unsavedCategory" :disabled="disabled || unsavedCategory" @busy="emit('busy', $event)" @changed="rulesChanged" @dirty="textDirty = $event" />
        </a-tab-pane>
      </a-tabs>
    </section>
    <a-modal :open="editorOpen" :width="720" :title="editorTitle" :mask-closable="false" :closable="!testBusy" :keyboard="!testBusy" @cancel="closeEditor">
      <a-form layout="vertical">
        <p class="category-hint">{{ w('configDraftHint') }}</p>
        <a-form-item :label="w(editorKind === 'category' ? 'categoryName' : 'name')" required><a-input v-model:value="draft.name" :disabled="testBusy || builtinEditor" /></a-form-item>
        <a-form-item v-if="editorKind === 'check'" :label="w('belongsTo')"><a-select v-model:value="draft.category" :options="categoryOptions" :disabled="testBusy || builtinEditor" /></a-form-item>
        <a-form-item :label="w(editorKind === 'category' ? 'description' : 'matchDescription')" required><a-textarea v-model:value="draft.description" :rows="3" :disabled="testBusy || builtinEditor" :placeholder="w(editorKind === 'category' ? 'categoryExample' : 'matchExample')" /></a-form-item>
        <template v-if="editorKind === 'check'"><a-form-item v-if="!builtinEditor" :label="w('allowDescription')"><a-textarea v-model:value="draft.allow" :rows="2" :disabled="testBusy" :placeholder="w('allowExample')" /></a-form-item><a-form-item :label="w('risk')"><a-select v-model:value="draft.risk" :options="severityOptions" :disabled="testBusy || builtinEditor" /></a-form-item></template>
        <a-form-item :label="w('state')"><a-switch v-model:checked="draft.enabled" :disabled="testBusy || builtinEditor" :checked-children="w('enabled')" :un-checked-children="w('disabled')" /></a-form-item>
        <a-alert v-if="editorError" type="error" :message="editorError" show-icon />
        <section v-if="editorKind === 'check'" class="single-check-test">
          <strong>{{ w('checkTestTitle') }}</strong><p class="category-hint">{{ w('checkTestHelp') }}</p>
          <a-form-item :label="w('checkTestModel')"><a-select v-model:value="testModel" :options="modelOptions" show-search option-filter-prop="label" :disabled="testBusy" /></a-form-item>
          <a-form-item :label="t('promptGuard.ruleEditor.testText')"><a-textarea v-model:value="testText" :rows="3" :disabled="testBusy" :placeholder="w('checkTestPlaceholder')" /></a-form-item>
          <a-button :loading="testBusy" :disabled="testBusy || !editable" @click="testCheck">{{ w('checkTestStart') }}</a-button>
          <a-alert v-if="testError" type="error" show-icon :message="testError" class="check-result" />
          <div v-else-if="testResult" class="check-result" aria-live="polite"><a-tag :color="testResult.findings_count ? 'orange' : 'green'">{{ w(testResult.findings_count ? 'checkTestMatch' : 'checkTestPass') }}</a-tag><span>{{ testResult.llm_model }} · {{ testResult.llm_duration_ms }} ms</span><p v-if="!testResult.findings_count">{{ w('checkTestNoMatch') }}</p><dl v-for="(item, index) in testResult.findings" :key="index"><dt>{{ w('checkTestRisk') }}</dt><dd>{{ severityLabel(item.model_severity) }} / {{ severityLabel(item.severity) }}</dd><dt>{{ w('checkTestReason') }}</dt><dd>{{ item.reason }}</dd><dt>{{ t('promptGuard.matchedInput') }}</dt><dd>{{ item.snippet }}</dd></dl></div>
        </section>
      </a-form>
      <template #footer><a-space><a-button :disabled="testBusy" @click="closeEditor">{{ w('close') }}</a-button><a-button v-if="!builtinEditor" type="primary" :disabled="disabled || testBusy" @click="applyEditor">{{ w('applyDraft') }}</a-button></a-space></template>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message, Modal } from 'ant-design-vue'
import { listPromptGuardRules, testPromptGuardCheck } from '../api'
import PromptGuardRules from './PromptGuardRules.vue'
import { createRequestId } from '../utils/requestId'
const props = defineProps({ modelValue: { type: Object, required: true }, catalog: { type: Array, required: true }, nativeCatalog: { type: Array, default: () => [] }, savedCustomCategories: { type: Object, default: () => ({}) }, modelOptions: { type: Array, default: () => [] }, editable: Boolean, disabled: Boolean, semantic: { type: Boolean, default: true } })
const emit = defineEmits(['update:modelValue', 'busy', 'changed', 'dirty'])
const { t, te } = useI18n()
const w = (key, params) => t(`promptGuard.workbench.${key}`, params)
const config = computed(() => props.modelValue)
const selected = ref('injection'), detailTab = ref('ai'), query = ref(''), highlighted = ref(''), modelExpanded = ref(false), detailElement = ref(null)
const textRules = ref([]), countsFailed = ref(false), textDirty = ref(false)
const nativeSelected = computed(() => selected.value.startsWith('native:') ? selected.value.slice(7) : '')
const categories = computed(() => [...props.catalog.filter(item => !item.custom).map(item => ({ ...item, rules: [...item.rules, ...Object.entries(config.value.custom_checks).filter(([, r]) => r.category === item.id).map(([id]) => id)] })), ...Object.entries(config.value.custom_categories).map(([id, item]) => ({ ...item, id, custom: true, rules: Object.entries(config.value.custom_checks).filter(([, r]) => r.category === id).map(([key]) => key) }))])
const checks = computed(() => categories.value.flatMap(category => category.rules.map(id => ({ id, category: category.id, custom: Boolean(config.value.custom_checks[id]) }))))
const categoryName = id => config.value.custom_categories[id]?.name || t(`promptGuard.categories.${id}`)
const checkName = id => config.value.custom_checks[id]?.name || t(`promptGuard.rules.${id}`)
const checkDescription = id => { const item = config.value.custom_checks[id]; return item ? [item.description, item.allow].filter(Boolean).join('\n') : t(`promptGuard.checkDescriptions.${id}`) }
const categoryConfig = id => config.value.categories[id] || { enabled: !config.value.custom_categories[id], model_id: null, disabled_rules: [], rule_severities: {} }
const current = computed(() => categoryConfig(selected.value))
const currentChecks = computed(() => checks.value.filter(item => item.category === selected.value))
const unsavedCategory = computed(() => Boolean(config.value.custom_categories[selected.value]) && !props.savedCustomCategories[selected.value])
const categoryOptions = computed(() => categories.value.map(item => ({ value: item.id, label: categoryName(item.id) })))
const matches = computed(() => checks.value.filter(item => [categoryName(item.category), checkName(item.id), checkDescription(item.id)].join(' ').toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
const enabledCount = id => checks.value.filter(item => item.category === id && !categoryConfig(id).disabled_rules.includes(item.id)).length
const textCount = id => textRules.value.filter(item => item.category === id).length
const modelLabel = id => props.modelOptions.find(item => item.value === id)?.label || String(id)
const severityLabel = value => value === 'AI' ? w('aiRisk') : t(`promptGuard.ruleEditor.severityValues.${value}`)
const severityOptions = computed(() => ['HIGH', 'MEDIUM', 'LOW', 'AI'].map(value => ({ value, label: severityLabel(value) })))
const columns = computed(() => [{ key: 'name', title: w('name'), width: 170 }, { key: 'enabled', title: w('state'), width: 70 }, { key: 'risk', title: w('risk'), width: 155 }, { key: 'description', title: w('description') }, { key: 'actions', title: w('actions'), width: 105 }])
const updateCategory = (id, patch) => emit('update:modelValue', { ...config.value, categories: { ...config.value.categories, [id]: { ...categoryConfig(id), ...patch } } })
const toggleCheck = (id, enabled) => updateCategory(selected.value, { disabled_rules: enabled ? current.value.disabled_rules.filter(item => item !== id) : [...current.value.disabled_rules, id] })
const toggleNative = (id, enabled) => emit('update:modelValue', { ...config.value, rsguard_disabled_categories: enabled ? config.value.rsguard_disabled_categories.filter(item => item !== id) : [...config.value.rsguard_disabled_categories, id] })
const select = id => { selected.value = id; highlighted.value = ''; modelExpanded.value = false }
const locate = async item => { select(item.category); detailTab.value = 'ai'; highlighted.value = item.id; await nextTick(); detailElement.value?.querySelector(`[data-row-key="${item.id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
watch(() => props.semantic, value => { if (value && nativeSelected.value) select('injection') })
const loadCounts = async () => { try { textRules.value = await listPromptGuardRules(); countsFailed.value = false } catch { countsFailed.value = true } }
const rulesChanged = () => { loadCounts(); emit('changed') }
onMounted(loadCounts)
const editorOpen = ref(false), editorKind = ref('check'), editorId = ref(''), editorError = ref(''), editorSnapshot = ref('')
const draft = reactive({ name: '', description: '', allow: '', category: '', risk: 'MEDIUM', enabled: false })
const builtinEditor = computed(() => editorKind.value === 'check' && Boolean(editorId.value) && !editorId.value.startsWith('custom_check_'))
const editorTitle = computed(() => w(builtinEditor.value ? 'checkTestTitle' : editorKind.value === 'category' ? editorId.value ? 'editCategory' : 'addCategory' : editorId.value ? 'editCheck' : 'addCheck'))
const editorDirty = computed(() => editorOpen.value && !builtinEditor.value && JSON.stringify(draft) !== editorSnapshot.value)
watch(() => textDirty.value || editorDirty.value, value => emit('dirty', value))
const testModel = ref(null), testText = ref(''), testBusy = ref(false), testError = ref(''), testResult = ref(null)
let testSequence = 0
watch(() => [JSON.stringify(draft), testModel.value, testText.value], () => { testSequence++; testResult.value = null; testError.value = '' })
const openEditor = (kind, id = '') => {
  if (props.disabled) return
  editorKind.value = kind; editorId.value = id; editorError.value = ''; testError.value = ''; testResult.value = null; testText.value = ''
  const item = kind === 'category' ? config.value.custom_categories[id] : config.value.custom_checks[id]
  const category = kind === 'category' ? id : checks.value.find(r => r.id === id)?.category || selected.value
  Object.assign(draft, { name: id ? kind === 'category' ? categoryName(id) : checkName(id) : '', description: item?.description || (id && kind === 'check' ? checkDescription(id) : ''), allow: item?.allow || '', category, risk: categoryConfig(category).rule_severities[id] || 'MEDIUM', enabled: id ? kind === 'category' ? categoryConfig(id).enabled : !categoryConfig(category).disabled_rules.includes(id) : false })
  testModel.value = props.semantic ? categoryConfig(category).model_id || config.value.model_id : config.value.image_model_id
  if (!props.modelOptions.some(item => item.value === testModel.value)) testModel.value = null
  editorSnapshot.value = JSON.stringify(draft); editorOpen.value = true
}
const closeEditor = () => { if (testBusy.value) return; if (editorDirty.value && !window.confirm(w('leaveEditor'))) { editorOpen.value = true; return } editorOpen.value = false; testSequence++ }
const validateDraft = () => {
  editorError.value = ''
  if (!draft.name.trim() || !draft.description.trim()) editorError.value = w('configRequired')
  else if ([...draft.name].length > 80 || [...draft.description].length > 2000 || [...draft.allow].length > 2000) editorError.value = w('configLength')
  else if (!editorId.value && Object.keys(editorKind.value === 'category' ? config.value.custom_categories : config.value.custom_checks).length >= (editorKind.value === 'category' ? 30 : 100)) editorError.value = w('itemLimit')
  else if (!builtinEditor.value && (editorKind.value === 'category' ? categories.value.some(item => item.id !== editorId.value && categoryName(item.id).toLocaleLowerCase() === draft.name.trim().toLocaleLowerCase()) : checks.value.some(item => item.id !== editorId.value && item.category === draft.category && checkName(item.id).toLocaleLowerCase() === draft.name.trim().toLocaleLowerCase()))) editorError.value = w('configDuplicate')
  return !editorError.value
}
const draftConfig = () => {
  const next = JSON.parse(JSON.stringify(config.value)), id = editorId.value || `custom_${editorKind.value === 'category' ? 'category' : 'check'}_${createRequestId().replaceAll('-', '')}`
  if (builtinEditor.value) return { next, id }
  if (editorKind.value === 'category') { next.custom_categories[id] = { name: draft.name.trim(), description: draft.description }; next.categories[id] = { ...categoryConfig(id), enabled: draft.enabled } }
  else {
    const oldCategory = next.custom_checks[id]?.category
    if (oldCategory && oldCategory !== draft.category) { const old = next.categories[oldCategory]; if (old) { old.disabled_rules = old.disabled_rules.filter(key => key !== id); delete old.rule_severities[id] } }
    next.custom_checks[id] = { name: draft.name.trim(), description: draft.description, allow: draft.allow, category: draft.category }
    const settings = next.categories[draft.category] || { enabled: true, model_id: null, disabled_rules: [], rule_severities: {} }
    settings.disabled_rules = settings.disabled_rules.filter(key => key !== id); if (!draft.enabled) settings.disabled_rules.push(id)
    settings.rule_severities[id] = draft.risk; next.categories[draft.category] = settings
  }
  return { next, id }
}
const applyEditor = () => { if (props.disabled || testBusy.value || !validateDraft()) return; const { next, id } = draftConfig(); emit('update:modelValue', next); editorSnapshot.value = JSON.stringify(draft); editorOpen.value = false; query.value = ''; if (editorKind.value === 'category') { select(id); detailTab.value = 'ai' } else locate({ id, category: draft.category }) }
const remove = (kind, id) => {
  if (props.disabled) return
  if (kind === 'category' && (countsFailed.value || textCount(id))) { message.warning(w('categoryHasText')); return }
  Modal.confirm({ title: w('deleteTitle'), content: w(kind === 'category' ? 'deleteCategoryHelp' : 'deleteCheckHelp'), okText: w('delete'), okType: 'danger', cancelText: w('cancel'), onOk: () => {
    if (props.disabled) return
    const next = JSON.parse(JSON.stringify(config.value)), ids = kind === 'category' ? checks.value.filter(item => item.category === id).map(item => item.id) : [id]
    for (const key of ids) { const category = next.custom_checks[key]?.category; delete next.custom_checks[key]; if (next.categories[category]) { next.categories[category].disabled_rules = next.categories[category].disabled_rules.filter(rule => rule !== key); delete next.categories[category].rule_severities[key] } }
    if (kind === 'category') { delete next.custom_categories[id]; delete next.categories[id]; select('injection') }
    emit('update:modelValue', next)
  } })
}
const errorLabel = data => { const code = String(data?.error_code || '').split('.').pop(); return te(`promptGuard.workbench.${code}`) ? w(code) : te(`promptGuard.errors.${code}`) ? t(`promptGuard.errors.${code}`) : typeof data?.detail === 'string' ? data.detail : w('checkTestFailed') }
const testCheck = async () => {
  if (testBusy.value || !props.editable || !validateDraft()) return
  if (!testText.value.trim() || [...testText.value].length > 20000) { testError.value = t('promptGuard.errors.rule_test_text'); return }
  if (!testModel.value) { testError.value = w('checkTestNoModel'); return }
  const { next, id } = draftConfig(), sequence = ++testSequence
  testBusy.value = true; emit('busy', true); testError.value = ''; testResult.value = null
  try {
    const result = await testPromptGuardCheck({ config: next, rule_id: id, model_id: testModel.value, text: testText.value })
    if (sequence !== testSequence) return
    if (result.llm_status !== 'completed') testError.value = errorLabel({ error_code: result.llm_error_code })
    else testResult.value = result
  } catch (error) { if (sequence === testSequence) testError.value = errorLabel(error.response?.data) }
  finally { testBusy.value = false; emit('busy', false) }
}
onUnmounted(() => { testSequence++; emit('dirty', false) })
</script>

<style scoped>
.guard-workbench{display:grid;grid-template-columns:280px minmax(0,1fr);gap:20px;margin:18px 0;align-items:start}.guard-navigation{border:1px solid #e4e9f1;border-radius:8px;padding:12px;max-height:75vh;overflow:auto;position:sticky;top:12px}.nav-heading{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px;color:#65738a;margin:16px 4px 8px}.nav-heading .ant-btn{font-size:12px;padding:0}.nav-item{display:flex;align-items:center;gap:8px;padding-right:8px;border-radius:6px;margin:3px 0}.nav-item>button:not(.ant-switch),.search-result{background:none;border:0;text-align:left;cursor:pointer;color:inherit;font:inherit;padding:10px;min-width:0;overflow-wrap:anywhere}.nav-item>button:not(.ant-switch){flex:1}.nav-item small,.search-result small{display:block;font-size:11px;color:#7c899e;margin-top:4px}.nav-item.active{background:#edf3ff;color:#245de0;box-shadow:inset 3px 0 #2864e8}.nav-item.inactive>button:not(.ant-switch){color:#8b94a5}.nav-item:hover,.search-result:hover{background:#f1f5fc}.search-result{display:block;width:100%;border-radius:6px}.search-result strong{display:block;font-size:13px}.guard-detail{min-width:0;border:1px solid #e4e9f1;border-radius:8px;padding:20px}.detail-heading{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.detail-heading h3{font-size:19px;margin:0}.category-actions{margin-left:auto}.category-hint{font-size:12px;color:#758298;line-height:1.6;margin:8px 0 12px}.category-model{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;font-size:12px}.category-model>span{color:#7b879b}.category-model strong{font-weight:500}.category-model-select{width:100%;max-width:440px;margin-bottom:16px}.ai-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:8px}.ai-toolbar>.ant-btn{flex-shrink:0}.guard-detail :deep(.ant-table-cell){font-size:12px}.guard-detail :deep(.ant-table-cell .ant-select){width:140px}.guard-detail :deep(.guard-highlight>td){background:#fff8dd!important}.custom-label{display:block;font-size:10px;color:#7c8aa0}.check-description{white-space:pre-wrap;overflow-wrap:anywhere}.single-check-test{background:#f6f9ff;padding:16px;border:1px solid #dfe7f5;border-radius:8px;margin-top:20px}.check-result{margin-top:14px;font-size:12px}.check-result dl{display:grid;grid-template-columns:140px minmax(0,1fr);gap:8px}.check-result dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.check-result dt{color:#7b879c}@media(max-width:900px){.guard-workbench{grid-template-columns:1fr}.guard-navigation{position:static;max-height:280px}.guard-detail{padding:14px}.ai-toolbar{flex-wrap:wrap}.check-result dl{grid-template-columns:1fr}}
</style>
