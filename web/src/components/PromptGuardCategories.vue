<template>
  <section class="guard-categories">
    <a-row :gutter="16">
      <a-col :xs="24" :md="8">
        <a-form-item :label="t('promptGuard.categorySettings.category')">
          <a-select v-model:value="selected" :options="categoryOptions" :disabled="disabled" />
        </a-form-item>
      </a-col>
      <a-col :xs="24" :md="4">
        <a-form-item :label="t('promptGuard.categorySettings.enabled')">
          <a-switch :checked="current.enabled" :disabled="disabled || !editable" @change="value => update({ enabled: value })" />
        </a-form-item>
      </a-col>
      <a-col :xs="24" :md="12">
        <a-form-item :label="t('promptGuard.categorySettings.model')">
          <a-select :value="current.model_id ?? undefined" :options="modelOptions" :placeholder="t('promptGuard.categorySettings.inherit')" allow-clear show-search option-filter-prop="label" :disabled="disabled || !editable || !current.enabled" @change="value => update({ model_id: value ?? null })" />
        </a-form-item>
      </a-col>
    </a-row>
    <p class="category-hint">{{ t('promptGuard.categorySettings.help') }}</p>
    <a-alert v-if="!current.enabled" type="info" show-icon :message="t('promptGuard.categorySettings.disabledHint')" />
    <strong>{{ t('promptGuard.categorySettings.aiRules') }}</strong>
    <div class="semantic-rules">
      <a-checkbox v-for="rule in selectedDefinition?.rules || []" :key="rule" :checked="!current.disabled_rules.includes(rule)" :disabled="disabled || !editable || !current.enabled" @change="event => toggleRule(rule, event.target.checked)">
        {{ t(`promptGuard.rules.${rule}`) }}
      </a-checkbox>
    </div>
    <PromptGuardRules :category="selected" :editable="editable" :disabled="disabled" @busy="emit('busy', $event)" @changed="emit('changed')" @dirty="emit('dirty', $event)" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import PromptGuardRules from './PromptGuardRules.vue'
const props = defineProps({ modelValue: { type: Object, required: true }, catalog: { type: Array, required: true }, modelOptions: Array, editable: Boolean, disabled: Boolean })
const emit = defineEmits(['update:modelValue', 'busy', 'changed', 'dirty'])
const { t } = useI18n()
const selected = ref('injection')
const categoryOptions = computed(() => props.catalog.map(item => ({ value: item.id, label: t(`promptGuard.categories.${item.id}`) })))
const selectedDefinition = computed(() => props.catalog.find(item => item.id === selected.value))
const current = computed(() => props.modelValue[selected.value] || { enabled: true, model_id: null, disabled_rules: [] })
const update = patch => emit('update:modelValue', { ...props.modelValue, [selected.value]: { ...current.value, ...patch } })
const toggleRule = (rule, enabled) => update({ disabled_rules: enabled ? current.value.disabled_rules.filter(item => item !== rule) : [...current.value.disabled_rules, rule] })
</script>

<style scoped>
.guard-categories { margin: 16px 0; }
.category-hint { color: #64748b; margin-bottom: 12px; }
.semantic-rules { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 12px 0 20px; }
.semantic-rules :deep(.ant-checkbox-wrapper) { margin-inline-start: 0; }
</style>
