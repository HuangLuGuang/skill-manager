<template>
  <section class="guard-categories">
    <a-row :gutter="16">
      <a-col :xs="24" :md="8">
        <a-form-item :label="t(semantic ? 'promptGuard.categorySettings.category' : 'promptGuard.rsguard.textCategory')">
          <a-select v-model:value="selected" :options="categoryOptions" :disabled="disabled" />
        </a-form-item>
      </a-col>
      <a-col :xs="24" :md="4">
        <a-form-item :label="t('promptGuard.categorySettings.enabled')">
          <a-switch :checked="current.enabled" :disabled="disabled || !editable" @change="value => update({ enabled: value })" />
        </a-form-item>
      </a-col>
      <a-col v-if="semantic" :xs="24" :md="12">
        <a-form-item :label="t('promptGuard.categorySettings.model')">
          <a-select :value="current.model_id ?? undefined" :options="modelOptions" :placeholder="t('promptGuard.categorySettings.inherit')" allow-clear show-search option-filter-prop="label" :disabled="disabled || !editable || !current.enabled" @change="value => update({ model_id: value ?? null })" />
        </a-form-item>
      </a-col>
    </a-row>
    <p class="category-hint">{{ t(semantic ? 'promptGuard.categorySettings.help' : 'promptGuard.rsguard.textHelp') }}</p>
    <a-alert v-if="!current.enabled" type="info" show-icon :message="t('promptGuard.categorySettings.disabledHint')" />
    <strong v-if="semantic">{{ t('promptGuard.categorySettings.aiRules') }}</strong>
    <div v-if="semantic" class="semantic-rules">
      <div v-for="rule in selectedDefinition?.rules || []" :key="rule" class="semantic-rule">
        <a-checkbox :checked="!current.disabled_rules.includes(rule)" :disabled="disabled || !editable || !current.enabled" @change="event => toggleRule(rule, event.target.checked)">
          {{ t(`promptGuard.rules.${rule}`) }}
        </a-checkbox>
        <a-select :value="current.rule_severities?.[rule]" :placeholder="t('promptGuard.categorySettings.modelSeverity')" :aria-label="`${t(`promptGuard.rules.${rule}`)}: ${t('promptGuard.categorySettings.severity')}`" :options="severityOptions" :disabled="disabled || !editable || !current.enabled || current.disabled_rules.includes(rule)" @change="value => update({ rule_severities: { ...current.rule_severities, [rule]: value } })" />
      </div>
    </div>
    <p v-if="semantic" class="category-hint">{{ t('promptGuard.categorySettings.severityHelp') }}</p>
    <PromptGuardRules :category="selected" :editable="editable" :disabled="disabled" @busy="emit('busy', $event)" @changed="emit('changed')" @dirty="emit('dirty', $event)" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import PromptGuardRules from './PromptGuardRules.vue'
const props = defineProps({ modelValue: { type: Object, required: true }, catalog: { type: Array, required: true }, modelOptions: Array, editable: Boolean, disabled: Boolean, semantic: { type: Boolean, default: true } })
const emit = defineEmits(['update:modelValue', 'busy', 'changed', 'dirty'])
const { t } = useI18n()
const selected = ref('injection')
const severityOptions = computed(() => ['HIGH', 'MEDIUM', 'LOW', 'AI'].map(value => ({ value, label: value === 'AI' ? t('promptGuard.categorySettings.modelSeverity') : t(`promptGuard.ruleEditor.severityValues.${value}`) })))
const categoryOptions = computed(() => props.catalog.map(item => ({ value: item.id, label: t(`promptGuard.categories.${item.id}`) })))
const selectedDefinition = computed(() => props.catalog.find(item => item.id === selected.value))
const current = computed(() => props.modelValue[selected.value] || { enabled: true, model_id: null, disabled_rules: [] })
const update = patch => emit('update:modelValue', { ...props.modelValue, [selected.value]: { ...current.value, ...patch } })
const toggleRule = (rule, enabled) => update({ disabled_rules: enabled ? current.value.disabled_rules.filter(item => item !== rule) : [...current.value.disabled_rules, rule] })
</script>

<style scoped>
.guard-categories { margin: 16px 0; }
.category-hint { color: #64748b; margin-bottom: 12px; }
.semantic-rules { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 12px 24px; margin: 12px 0; }
.semantic-rule { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.semantic-rule .ant-select { width: 200px; flex-shrink: 0; }
@media (max-width: 480px) {
  .semantic-rule { align-items: stretch; flex-direction: column; }
  .semantic-rule .ant-select { width: 100%; }
}
.semantic-rules :deep(.ant-checkbox-wrapper) { margin-inline-start: 0; }
</style>
