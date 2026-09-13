<template>
  <section class="assistant-settings">
    <a-card class="page-card settings-content">
      <template #title>
        <a-page-header :title="t('docsAssistantSettings.title')" :sub-title="t('docsAssistantSettings.subtitle')">
          <template #tags>
            <a-tag :color="form.enabled ? 'blue' : 'default'">
              {{ form.enabled ? t('docsAssistantSettings.active') : t('docsAssistantSettings.inactive') }}
            </a-tag>
          </template>
          <template #extra>
            <a-button @click="openDocsPreview">
              <ExportOutlined />
              {{ t('docsAssistantSettings.preview') }}
            </a-button>
          </template>
        </a-page-header>
      </template>

      <a-skeleton v-if="loading" active :paragraph="{ rows: 6 }" />
      <template v-else>
        <div class="enable-row">
          <div>
            <strong>{{ t('docsAssistantSettings.enabled') }}</strong>
            <span>{{ t('docsAssistantSettings.enabledHint') }}</span>
          </div>
          <a-switch v-model:checked="form.enabled" />
        </div>

        <div class="settings-grid">
          <label class="field-block">
            <span class="field-label">{{ t('docsAssistantSettings.model') }}</span>
            <a-select
              v-model:value="form.model"
              allow-clear
              show-search
              option-filter-prop="label"
              :disabled="!form.enabled"
              :placeholder="t('docsAssistantSettings.modelPlaceholder')"
              :options="modelOptions"
            />
            <small>{{ t('docsAssistantSettings.modelHint') }}</small>
            <router-link class="inline-link" to="/model-gateway/models">
              {{ t('docsAssistantSettings.configureModels') }} <ArrowRightOutlined />
            </router-link>
          </label>

          <label class="field-block compact-field">
            <span class="field-label">{{ t('docsAssistantSettings.maxContext') }}</span>
            <a-select v-model:value="form.max_context_sections" :options="contextOptions" />
            <small>{{ t('docsAssistantSettings.maxContextHint') }}</small>
          </label>
        </div>

        <label class="field-block output-token-field">
          <span class="field-label">{{ t('docsAssistantSettings.maxOutputTokens') }}</span>
          <a-input-number v-model:value="form.max_output_tokens" :min="1" :precision="0" style="width: 100%" />
          <small>{{ t('docsAssistantSettings.maxOutputTokensHint') }}</small>
        </label>

        <div class="localized-grid">
          <label class="field-block">
            <span class="field-label">{{ t('docsAssistantSettings.welcomeZh') }}</span>
            <a-textarea v-model:value="form.welcome_zh" :rows="2" :maxlength="300" show-count />
          </label>
          <label class="field-block">
            <span class="field-label">{{ t('docsAssistantSettings.welcomeEn') }}</span>
            <a-textarea v-model:value="form.welcome_en" :rows="2" :maxlength="300" show-count />
          </label>
          <label class="field-block">
            <span class="field-label">{{ t('docsAssistantSettings.instructionZh') }}</span>
            <a-textarea v-model:value="form.instruction_zh" :rows="3" :maxlength="1000" show-count />
          </label>
          <label class="field-block">
            <span class="field-label">{{ t('docsAssistantSettings.instructionEn') }}</span>
            <a-textarea v-model:value="form.instruction_en" :rows="3" :maxlength="1000" show-count />
          </label>
        </div>

        <div class="questions-section">
          <div class="questions-heading">
            <div>
              <strong>{{ t('docsAssistantSettings.commonQuestions') }}</strong>
              <span>{{ t('docsAssistantSettings.commonQuestionsHint') }}</span>
            </div>
            <a-button :disabled="form.common_questions.length >= 8" @click="addQuestion">
              <PlusOutlined /> {{ t('docsAssistantSettings.addQuestion') }}
            </a-button>
          </div>

          <div v-if="form.common_questions.length" class="question-list">
            <div v-for="(question, index) in form.common_questions" :key="question.id" class="question-row">
              <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <a-input v-model:value="question.question_zh" :maxlength="200" :placeholder="t('docsAssistantSettings.questionZh')" />
              <a-input v-model:value="question.question_en" :maxlength="200" :placeholder="t('docsAssistantSettings.questionEn')" />
              <a-button
                type="text"
                danger
                :aria-label="t('docsAssistantSettings.removeQuestion')"
                @click="removeQuestion(index)"
              >
                <DeleteOutlined />
              </a-button>
            </div>
          </div>
        </div>

        <div class="settings-footer">
          <a-button type="primary" :loading="saving" :disabled="saving || loading || !hasAccess('docs:update')" @click="saveSettings">
            <SaveOutlined />
            {{ saving ? t('docsAssistantSettings.saving') : t('docsAssistantSettings.save') }}
          </a-button>
        </div>
      </template>
    </a-card>
  </section>
</template>

<script setup>
import { modelLabel } from '../utils/modelLabels'
import { can as hasAccess } from '../access'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { onBeforeRouteLeave } from 'vue-router'
import {
  ArrowRightOutlined,
  DeleteOutlined,
  ExportOutlined,
  PlusOutlined,
  SaveOutlined,
} from '@ant-design/icons-vue'

import { getDocsAssistantConfig, listModelEndpoints, updateDocsAssistantConfig } from '../api'

const { t } = useI18n()
const loading = ref(true)
const saving = ref(false)
const dirty = ref(false)
const savedSnapshot = ref('')
const models = ref([])
const form = reactive({
  enabled: false,
  model: undefined,
  welcome_zh: '',
  welcome_en: '',
  instruction_zh: '',
  instruction_en: '',
  max_context_sections: 4,
  max_output_tokens: 12800,
  common_questions: [],
})

const modelOptions = computed(() => models.value
  .filter(item => item.enabled !== false)
  .map(item => {
    return {
      value: item.name,
      label: modelLabel(item),
    }
  }))
const contextOptions = [2, 3, 4, 5, 6].map(value => ({ value, label: String(value) }))

const errorText = (error, fallback) => error?.response?.data?.detail || fallback
const buildSettingsPayload = () => ({
  enabled: Boolean(form.enabled),
  model: form.model || null,
  welcome_zh: form.welcome_zh,
  welcome_en: form.welcome_en,
  instruction_zh: form.instruction_zh,
  instruction_en: form.instruction_en,
  max_context_sections: Number(form.max_context_sections || 4),
  max_output_tokens: Number(form.max_output_tokens ?? 12800),
  common_questions: form.common_questions.map(item => ({
    ...item,
    question_zh: item.question_zh,
    question_en: item.question_en,
  })),
})

const markSaved = () => {
  savedSnapshot.value = JSON.stringify(buildSettingsPayload())
  dirty.value = false
}

const assignConfig = config => {
  Object.assign(form, {
    enabled: Boolean(config.enabled),
    model: config.model || undefined,
    welcome_zh: config.welcome_zh || '',
    welcome_en: config.welcome_en || '',
    instruction_zh: config.instruction_zh || '',
    instruction_en: config.instruction_en || '',
    max_context_sections: config.max_context_sections || 4,
    max_output_tokens: config.max_output_tokens ?? 12800,
    common_questions: (config.common_questions || []).map(item => ({ ...item })),
  })
}

const loadSettings = async () => {
  loading.value = true
  try {
    const [config, modelRows] = await Promise.all([
      getDocsAssistantConfig(),
      hasAccess('models:view') ? listModelEndpoints() : [],
    ])
    assignConfig(config)
    markSaved()
    models.value = Array.isArray(modelRows) ? modelRows : []
  } catch (error) {
    message.error(errorText(error, t('docsAssistantSettings.loadFailed')))
  } finally {
    loading.value = false
  }
}

const addQuestion = () => {
  if (form.common_questions.length >= 8) return
  const suffix = `${Date.now()}-${form.common_questions.length}`
  form.common_questions.push({ id: `question-${suffix}`, question_zh: '', question_en: '' })
}
const removeQuestion = index => form.common_questions.splice(index, 1)
const openDocsPreview = () => window.open('/docs', '_blank', 'noopener,noreferrer')

const validate = () => {
  if (form.enabled && !form.model) {
    message.warning(t('docsAssistantSettings.modelRequired'))
    return false
  }
  if (form.common_questions.some(item => !item.question_zh.trim() || !item.question_en.trim())) {
    message.warning(t('docsAssistantSettings.questionRequired'))
    return false
  }
  return true
}

const saveSettings = async () => {
  if (saving.value || loading.value || !hasAccess('docs:update')) return
  if (!validate()) return
  saving.value = true
  try {
    const payload = {
      ...buildSettingsPayload(),
      common_questions: form.common_questions.map(item => ({
        ...item,
        question_zh: item.question_zh.trim(),
        question_en: item.question_en.trim(),
      })),
    }
    await updateDocsAssistantConfig(payload)
    assignConfig(payload)
    markSaved()
    message.success(t('docsAssistantSettings.saved'))
  } catch (error) {
    message.error(errorText(error, t('docsAssistantSettings.saveFailed')))
  } finally {
    saving.value = false
  }
}

const handleBeforeUnload = event => {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

watch(form, () => {
  dirty.value = Boolean(savedSnapshot.value && JSON.stringify(buildSettingsPayload()) !== savedSnapshot.value)
}, { deep: true })

onBeforeRouteLeave(() => {
  if (!dirty.value) return true
  return window.confirm(t('docsAssistantSettings.unsavedChanges'))
})

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  loadSettings()
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>

<style scoped>
.assistant-settings {
  position: relative;
  margin-top: 18px;
}


.enable-row,
.questions-heading,
.settings-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }

.enable-row {
  margin: 20px 0;
  padding: 15px 16px;
  background: #f7faff;
  border: 1px solid #dfe9f5;
  border-radius: 9px;
}
.enable-row > div,
.questions-heading > div { display: flex; flex-direction: column; gap: 4px; }
.enable-row strong,
.questions-heading strong { color: #1e3852; }
.enable-row span,
.questions-heading span { color: #718196; font-size: 12px; line-height: 1.5; }

.settings-grid { display: grid; grid-template-columns: minmax(300px, 1fr) 180px; gap: 18px; }
.localized-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 20px; }
.field-block { display: flex; min-width: 0; flex-direction: column; gap: 8px; }
.output-token-field { margin-top: 20px; }
.field-label { color: #314a62; font-size: 13px; font-weight: 630; }
.field-block small { color: #7b8a9a; font-size: 11px; line-height: 1.55; }
.inline-link { display: inline-flex; align-items: center; gap: 4px; width: fit-content; color: #2663b8; font-size: 12px; }
.compact-field { align-self: start; }

.questions-section { margin-top: 24px; padding-top: 20px; border-top: 1px solid #e8edf3; }
.question-list { display: grid; gap: 9px; margin-top: 14px; }
.question-row { display: grid; grid-template-columns: 32px 1fr 1fr 34px; gap: 10px; align-items: center; }
.question-index { color: #7990a7; font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }
.settings-footer { justify-content: flex-end; margin-top: 22px; padding-top: 18px; border-top: 1px solid #e8edf3; }

@media (max-width: 900px) {
  .settings-grid,
  .localized-grid { grid-template-columns: 1fr; }
  .question-row { grid-template-columns: 28px 1fr 34px; }
  .question-row :deep(.ant-input:nth-of-type(2)) { grid-column: 2; }
}

@media (max-width: 560px) {
  .questions-heading { align-items: flex-start; flex-direction: column; }
}
</style>
