<template>
  <Transition name="assistant-rail">
    <aside v-if="open" class="assistant-panel" :aria-label="t('docsAssistant.title')" @keydown.esc="$emit('close')">
      <header class="assistant-header">
        <div class="assistant-identity">
          <span class="assistant-mark"><RobotOutlined /></span>
          <div>
            <strong>{{ t('docsAssistant.title') }}</strong>
            <span><i />{{ t('docsAssistant.grounded') }}</span>
          </div>
        </div>
        <div class="assistant-header-actions">
          <button type="button" :aria-label="t('docsAssistant.newConversation')" @click="clearConversation">
            <DeleteOutlined />
          </button>
          <button type="button" :aria-label="t('docsAssistant.close')" @click="$emit('close')">
            <CloseOutlined />
          </button>
        </div>
      </header>

      <div ref="conversationScroller" class="assistant-conversation">
        <section v-if="!messages.length" class="assistant-welcome">
          <div class="welcome-orbit" aria-hidden="true">
            <span><RobotOutlined /></span>
          </div>
          <h2>{{ welcomeMessage }}</h2>
          <p>{{ t('docsAssistant.commonQuestionsHint') }}</p>

          <div v-if="questions.length" class="suggestion-block">
            <div class="suggestion-label"><BulbOutlined /> {{ t('docsAssistant.commonQuestions') }}</div>
            <button
              v-for="question in questions"
              :key="question.id"
              type="button"
              class="suggestion-card"
              @click="submitQuestion(question.label)"
            >
              <span>{{ question.label }}</span>
              <ArrowUpOutlined />
            </button>
          </div>
        </section>

        <div v-else class="message-list">
          <article v-for="(item, index) in messages" :key="`${item.role}-${index}`" :class="['chat-message', item.role]">
            <div class="message-role">
              <span v-if="item.role === 'assistant'"><RobotOutlined /></span>
              <span v-else><UserOutlined /></span>
              {{ item.role === 'assistant' ? t('docsAssistant.assistantLabel') : t('docsAssistant.userLabel') }}
            </div>
            <div
              v-if="item.role === 'assistant' && !item.error"
              class="message-bubble markdown-answer"
              v-html="renderSafeMarkdown(item.content)"
            />
            <div v-else class="message-bubble">{{ item.content }}</div>
            <div v-if="item.error" class="message-error-action">
              <button type="button" @click="submitQuestion(item.question, true)">
                <ReloadOutlined /> {{ t('docsAssistant.retry') }}
              </button>
            </div>
            <div v-if="item.related?.length" class="related-docs">
              <div class="related-title"><LinkOutlined /> {{ t('docsAssistant.relatedDocs') }}</div>
              <button
                v-for="related in item.related"
                :key="related.slug"
                type="button"
                @click="$emit('navigate', related.slug)"
              >
                <span><strong>{{ related.title }}</strong><small>{{ related.section }}</small></span>
                <ArrowRightOutlined />
              </button>
            </div>
          </article>

          <article v-if="asking" class="chat-message assistant pending">
            <div class="message-role"><span><RobotOutlined /></span>{{ t('docsAssistant.assistantLabel') }}</div>
            <div class="thinking-bubble">
              <span class="thinking-dots"><i /><i /><i /></span>
              {{ t('docsAssistant.thinking') }}
            </div>
          </article>
        </div>
      </div>

      <footer class="assistant-composer">
        <div class="composer-shell">
          <textarea
            ref="inputElement"
            v-model="questionInput"
            rows="2"
            :placeholder="t('docsAssistant.inputPlaceholder')"
            :disabled="asking"
            @compositionstart="composing = true"
            @compositionend="composing = false"
            @keydown="handleComposerKeydown"
          />
          <button
            type="button"
            :disabled="asking || !questionInput.trim()"
            :aria-label="t('docsAssistant.send')"
            @click="submitQuestion(questionInput)"
          >
            <SendOutlined />
          </button>
        </div>
        <p>{{ t('docsAssistant.disclaimer') }}</p>
      </footer>
    </aside>
  </Transition>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowRightOutlined,
  ArrowUpOutlined,
  BulbOutlined,
  CloseOutlined,
  DeleteOutlined,
  LinkOutlined,
  ReloadOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'

import { askDocsAssistant } from '../api'
import { shouldSubmitComposerOnEnter } from '../utils/composerKeyboard'
import { rankDocsContexts } from '../utils/docsSearch'
import { renderSafeMarkdown } from '../utils/markdown'

const props = defineProps({
  open: { type: Boolean, required: true },
  config: { type: Object, required: true },
  content: { type: Object, required: true },
  locale: { type: String, required: true },
  currentSlug: { type: String, default: '' },
})
defineEmits(['close', 'navigate'])

const { t } = useI18n()
const questionInput = ref('')
const messages = ref([])
const asking = ref(false)
const composing = ref(false)
const conversationScroller = ref(null)
const inputElement = ref(null)

const welcomeMessage = computed(() => props.locale === 'en-US' ? props.config.welcome_en : props.config.welcome_zh)
const questions = computed(() => (props.config.common_questions || []).map(item => ({
  id: item.id,
  label: props.locale === 'en-US' ? item.question_en : item.question_zh,
})).filter(item => item.label))

const buildRelated = contexts => {
  const seen = new Set()
  return contexts.filter(item => {
    if (seen.has(item.slug)) return false
    seen.add(item.slug)
    return true
  }).slice(0, 3).map(item => ({
    slug: item.slug,
    title: item.article_title,
    section: item.section_title,
  }))
}

const scrollToBottom = async () => {
  await nextTick()
  conversationScroller.value?.scrollTo({ top: conversationScroller.value.scrollHeight, behavior: 'smooth' })
}

const handleComposerKeydown = event => {
  if (!shouldSubmitComposerOnEnter(event, composing.value)) return
  event.preventDefault()
  submitQuestion(questionInput.value)
}

const submitQuestion = async (rawQuestion, retry = false) => {
  const question = String(rawQuestion || '').trim()
  if (!question || asking.value) return
  if (!retry) messages.value.push({ role: 'user', content: question })
  questionInput.value = ''
  asking.value = true
  await scrollToBottom()

  const limit = Math.min(Math.max(props.config.max_context_sections || 4, 2), 6)
  const contexts = rankDocsContexts({
    content: props.content,
    query: question,
    currentSlug: props.currentSlug,
  }).slice(0, limit)
  const history = messages.value
    .filter(item => !item.error)
    .slice(retry ? -7 : -7, -1)
    .slice(-6)
    .map(item => ({ role: item.role, content: item.content.slice(0, 2000) }))
  try {
    const result = await askDocsAssistant({
      question,
      locale: props.locale,
      contexts,
      history,
    })
    messages.value.push({
      role: 'assistant',
      content: result.answer,
      related: buildRelated(contexts),
    })
  } catch (error) {
    messages.value.push({
      role: 'assistant',
      content: error?.response?.data?.detail || t('docsAssistant.requestFailed'),
      error: true,
      question,
    })
  } finally {
    asking.value = false
    await scrollToBottom()
    inputElement.value?.focus()
  }
}

const clearConversation = () => {
  messages.value = []
  questionInput.value = ''
  nextTick(() => inputElement.value?.focus())
}

watch(() => props.open, value => {
  if (value) nextTick(() => inputElement.value?.focus())
})
</script>

<style scoped>
.assistant-panel {
  position: fixed;
  z-index: 35;
  top: 68px;
  right: 0;
  bottom: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  width: min(430px, 100vw);
  color: #132d45;
  background: #fff;
  border-left: 1px solid #d9e3ee;
  box-shadow: -18px 0 50px rgba(11, 31, 51, 0.14);
}

.assistant-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 74px; padding: 14px 18px; border-bottom: 1px solid #e1e8f0; }
.assistant-identity { display: flex; align-items: center; gap: 11px; }
.assistant-mark { position: relative; display: grid; width: 38px; height: 38px; place-items: center; color: #fff; background: linear-gradient(145deg, #1e5eb8, #347de3); border-radius: 11px; box-shadow: 0 8px 20px rgba(37, 99, 235, 0.22); font-size: 18px; }
.assistant-mark::after { position: absolute; top: -2px; right: -2px; width: 9px; height: 9px; background: #2bc48a; border: 2px solid #fff; border-radius: 50%; content: ''; }
.assistant-identity > div { display: flex; flex-direction: column; gap: 4px; }
.assistant-identity strong { font-size: 15px; }
.assistant-identity span:not(.assistant-mark) { display: flex; align-items: center; gap: 6px; color: #718297; font-size: 11px; }
.assistant-identity i { width: 5px; height: 5px; background: #2bb985; border-radius: 50%; }
.assistant-header-actions { display: flex; gap: 5px; }
.assistant-header-actions button { display: grid; width: 32px; height: 32px; place-items: center; color: #607489; background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.assistant-header-actions button:hover { color: #174f91; background: #edf4fc; }

.assistant-conversation { overflow-y: auto; background: linear-gradient(180deg, #f8fbfe 0, #fff 160px); }
.assistant-welcome { padding: 38px 24px 30px; }
.welcome-orbit { position: relative; display: grid; width: 74px; height: 74px; margin: 2px auto 22px; place-items: center; border: 1px solid #cfe0f4; border-radius: 24px; transform: rotate(10deg); }
.welcome-orbit::before { position: absolute; inset: 8px; background: #eaf3ff; border-radius: 18px; content: ''; }
.welcome-orbit span { z-index: 1; display: grid; width: 44px; height: 44px; place-items: center; color: #1d5eb3; background: #fff; border-radius: 14px; box-shadow: 0 8px 25px rgba(34, 86, 147, 0.13); font-size: 21px; transform: rotate(-10deg); }
.assistant-welcome h2 { max-width: 340px; margin: 0 auto; color: #102b44; font-size: 20px; font-weight: 690; line-height: 1.45; text-align: center; }
.assistant-welcome > p { margin: 10px auto 28px; color: #6e8195; font-size: 13px; line-height: 1.6; text-align: center; }
.suggestion-label { display: flex; align-items: center; gap: 7px; margin: 0 2px 10px; color: #567087; font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.suggestion-card { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 14px; width: 100%; min-height: 58px; margin-top: 9px; padding: 13px 15px; color: #243d54; text-align: left; background: rgba(255, 255, 255, .9); border: 1px solid #dce6f0; border-radius: 11px; cursor: pointer; transition: 160ms ease; }
.suggestion-card:hover { color: #174f91; border-color: #9ebce2; box-shadow: 0 8px 22px rgba(23, 68, 113, .08); transform: translateY(-1px); }
.suggestion-card .anticon { color: #3d71ae; transform: rotate(45deg); }

.message-list { display: grid; gap: 24px; padding: 24px 20px 30px; }
.message-role { display: flex; align-items: center; gap: 7px; margin-bottom: 7px; color: #6d8092; font-size: 11px; font-weight: 650; }
.message-role span { display: grid; width: 22px; height: 22px; place-items: center; color: #285d94; background: #e9f2fb; border-radius: 7px; }
.chat-message.user .message-role { justify-content: flex-end; }
.chat-message.user .message-role span { color: #fff; background: #39566f; }
.message-bubble { padding: 13px 15px; color: #2c4358; white-space: pre-wrap; background: #f1f6fb; border: 1px solid #e0e9f2; border-radius: 4px 13px 13px; font-size: 13px; line-height: 1.75; overflow-wrap: anywhere; }
.markdown-answer { white-space: normal; }
.markdown-answer :deep(> :first-child) { margin-top: 0; }
.markdown-answer :deep(> :last-child) { margin-bottom: 0; }
.markdown-answer :deep(p) { margin: 0 0 10px; }
.markdown-answer :deep(h1),
.markdown-answer :deep(h2),
.markdown-answer :deep(h3),
.markdown-answer :deep(h4) { margin: 17px 0 8px; color: #17324c; font-weight: 700; line-height: 1.35; }
.markdown-answer :deep(h1) { font-size: 18px; }
.markdown-answer :deep(h2) { font-size: 16px; }
.markdown-answer :deep(h3),
.markdown-answer :deep(h4) { font-size: 14px; }
.markdown-answer :deep(ul),
.markdown-answer :deep(ol) { display: grid; gap: 5px; margin: 8px 0 12px; padding-left: 21px; }
.markdown-answer :deep(li::marker) { color: #2b6fba; }
.markdown-answer :deep(blockquote) { margin: 10px 0; padding: 8px 11px; color: #516b82; background: #e7f0f9; border-left: 3px solid #5c91c9; }
.markdown-answer :deep(blockquote p) { margin: 0; }
.markdown-answer :deep(code) { padding: 2px 5px; color: #9b2f4e; background: #e8edf3; border-radius: 4px; font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }
.markdown-answer :deep(pre) { margin: 10px 0; padding: 12px; overflow-x: auto; color: #dce9f5; background: #102b44; border: 1px solid #294963; border-radius: 8px; }
.markdown-answer :deep(pre code) { padding: 0; color: inherit; background: transparent; font-size: 11px; line-height: 1.65; }
.markdown-answer :deep(a) { color: #1d64ad; font-weight: 650; text-decoration: underline; text-decoration-color: #9cbce0; text-underline-offset: 3px; }
.markdown-answer :deep(hr) { margin: 14px 0; border: 0; border-top: 1px solid #d5e0ea; }
.markdown-answer :deep(table) { width: 100%; margin: 10px 0; border-collapse: collapse; font-size: 11px; }
.markdown-answer :deep(th),
.markdown-answer :deep(td) { padding: 7px 8px; text-align: left; border: 1px solid #cfdae5; }
.markdown-answer :deep(th) { color: #29465f; background: #e8eff6; }
.chat-message.user .message-bubble { margin-left: 50px; color: #fff; background: #183d60; border-color: #183d60; border-radius: 13px 4px 13px 13px; }
.related-docs { display: grid; gap: 7px; margin-top: 11px; }
.related-title { display: flex; align-items: center; gap: 6px; color: #678096; font-size: 11px; font-weight: 650; }
.related-docs button { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 12px; padding: 10px 11px; color: #24425d; text-align: left; background: #fff; border: 1px solid #dce6ef; border-radius: 9px; cursor: pointer; }
.related-docs button:hover { color: #1c5ca4; border-color: #a9c4e3; }
.related-docs button > span { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.related-docs strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.related-docs small { color: #7c8d9d; font-size: 10px; }
.message-error-action { margin-top: 8px; }
.message-error-action button { padding: 5px 9px; color: #b45309; background: #fff7ed; border: 1px solid #fed7aa; border-radius: 7px; cursor: pointer; font-size: 11px; }
.thinking-bubble { display: flex; align-items: center; gap: 10px; padding: 13px 15px; color: #657b8f; background: #f1f6fb; border: 1px solid #e0e9f2; border-radius: 4px 13px 13px; font-size: 12px; }
.thinking-dots { display: flex; gap: 3px; }
.thinking-dots i { width: 5px; height: 5px; background: #3475bd; border-radius: 50%; animation: thinking 1.1s infinite ease-in-out; }
.thinking-dots i:nth-child(2) { animation-delay: .14s; }
.thinking-dots i:nth-child(3) { animation-delay: .28s; }

.assistant-composer { padding: 13px 16px 14px; background: #fff; border-top: 1px solid #e1e8f0; }
.composer-shell { display: grid; grid-template-columns: 1fr 38px; gap: 8px; align-items: end; padding: 9px 9px 9px 13px; background: #f8fafc; border: 1px solid #cfdbe7; border-radius: 13px; transition: 160ms ease; }
.composer-shell:focus-within { background: #fff; border-color: #74a3db; box-shadow: 0 0 0 3px rgba(45, 108, 223, .1); }
.composer-shell textarea { min-height: 44px; max-height: 130px; padding: 4px 0; resize: none; color: #17324c; background: transparent; border: 0; outline: 0; font: inherit; font-size: 13px; line-height: 1.55; }
.composer-shell button { display: grid; width: 38px; height: 38px; place-items: center; color: #fff; background: #2468bd; border: 0; border-radius: 10px; cursor: pointer; }
.composer-shell button:disabled { color: #9baaba; background: #e3e9ef; cursor: not-allowed; }
.assistant-composer > p { margin: 8px 5px 0; color: #8a98a6; font-size: 9px; line-height: 1.45; text-align: center; }

.assistant-rail-enter-active,
.assistant-rail-leave-active { transition: transform 220ms ease, opacity 180ms ease; }
.assistant-rail-enter-from,
.assistant-rail-leave-to { opacity: 0; transform: translateX(100%); }
@keyframes thinking { 0%, 70%, 100% { opacity: .35; transform: translateY(0); } 35% { opacity: 1; transform: translateY(-3px); } }

button:focus-visible,
textarea:focus-visible { outline: 3px solid rgba(37, 99, 235, .25); outline-offset: 2px; }

@media (max-width: 600px) {
  .assistant-panel { top: 0; width: 100vw; }
  .assistant-welcome { padding-right: 18px; padding-left: 18px; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
</style>
