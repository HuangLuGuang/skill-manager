<template>
  <section v-if="visible" class="audit-content">
    <div v-if="showHeading || failed" class="audit-content-heading"><h4 v-if="showHeading">{{ t(titleKey) }}</h4><a-button v-if="failed && allowed" :loading="busy" :disabled="busy" @click="load">{{ t('aidr.content.retry') }}</a-button></div>
    <p v-if="promptNotCollected" class="audit-content-note">{{ t('aidr.policyNavigation.promptNotCollected') }} <router-link v-if="can('settings:view') && pageAllowed('/clients')" :to="{ path: '/clients', query: { policy: 'audit', client: clientId } }">{{ t('aidr.policyNavigation.openDevice') }}</router-link></p>
    <p v-else-if="!descriptors.length" class="audit-content-note">{{ t('aidr.content.statuses.' + contentStatus) }}</p>
    <template v-if="descriptors.length">
      <p v-if="!allowed">{{ t('aidr.content.permission') }}</p>
      <p v-if="busy" class="audit-content-note" role="status">{{ t('aidr.sessions.loading') }}</p>
      <a-alert v-if="failed" type="error" :message="t(errorCode === 'aidr.content_expired' ? 'aidr.lifecycle.historyExpired' : 'aidr.content.failed')" show-icon />
      <div v-for="(item, index) in contents || []" :key="index" class="audit-content-fragment">
        <p v-if="contents.length > 1 || item.redacted || item.truncated"><strong>{{ fragmentLabel(item, index) }}</strong><span v-if="item.redacted"> · {{ t('aidr.detail.redactedContent') }}</span><span v-if="item.truncated"> · {{ t('aidr.detail.partialContent') }}</span></p>
        <AidrMarkdown v-if="['prompt', 'model_response'].includes(item.kind) && !item.source_field?.endsWith('.context')" :text="item.text" :mode="contentMode" />
        <pre v-else>{{ item.text }}</pre>
        <p v-if="item.truncated" class="audit-content-note">{{ t('aidr.content.truncationSize', { source: item.source_bytes, stored: storedBytes(item.text), fragment: appliedCapture?.max_fragment_bytes ?? 1024, event: appliedCapture?.max_event_bytes ?? 2048 }) }}</p>
      </div>
    </template>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { can, pageAllowed } from '../access'
import { getClientAidrContent } from '../api'
import AidrMarkdown from './AidrMarkdown.vue'
const props = defineProps({ contentMode: { type: String, default: 'source' }, showHeading: { type: Boolean, default: true }, clientId: { type: String, required: true }, source: { type: String, required: true }, recordId: { type: [String, Number], required: true }, evidence: { type: Object, required: true } })
const { t } = useI18n()
const busy = ref(false), contents = ref(null), failed = ref(false), errorCode = ref('')
let generation = 0
const allowed = computed(() => can('clients:read-audit-content'))
const descriptors = computed(() => [...(props.evidence.message?.contents || []), ...(props.evidence.contents || []), ...(props.evidence.behavior?.contents || [])])
const appliedCapture = computed(() => props.evidence.message?.policy?.capture || props.evidence.behavior?.policy?.capture || props.evidence.policy?.capture)
const contentStatus = computed(() => props.evidence.message?.content_status || props.evidence.behavior?.content_status || props.evidence.content_status || 'unknown')
const promptNotCollected = computed(() => props.evidence.kind === 'turn.submit' && contentStatus.value === 'not_requested' && props.evidence.policy?.capture?.prompt === false)
const isPrompt = computed(() => ['turn.submit', 'user_message'].includes(props.evidence.kind))
const isResult = computed(() => ['tool_result', 'tool.post', 'tool.failure', 'assistant_message'].includes(props.evidence.kind))
const titleKey = computed(() => isPrompt.value ? 'aidr.detail.prompt' : isResult.value ? 'aidr.detail.output' : 'aidr.detail.input')
const visible = computed(() => {
  if (descriptors.value.length || isPrompt.value || props.evidence.kind === 'assistant_message') return true
  const scope = props.evidence.behavior?.policy?.capture
  const kind = ['Read', 'read_file'].includes(props.evidence.tool) ? 'file_body' : 'tool_output'
  return isResult.value && !!scope?.[kind]
})
function fragmentLabel(item, index) {
  const field = item.source_field || ''
  if (item.kind === 'prompt' && field.endsWith('.request')) return t('aidr.sessions.requestFragment')
  if (item.kind === 'prompt' && field.endsWith('.context')) return t('aidr.sessions.contextFragment')
  const key = field.endsWith('old_string') ? 'aidr.detail.beforeEdit' : field.endsWith('new_string') ? 'aidr.detail.afterEdit' : 'aidr.content.kinds.' + item.kind
  return t(key) + (contents.value?.length > 1 ? ` ${index + 1}` : '')
}
function storedBytes(text) { return new TextEncoder().encode(text).length }
function clear() { generation++; contents.value = null; busy.value = false; failed.value = false; errorCode.value = '' }
async function load() {
  if (busy.value || !allowed.value) return
  const request = ++generation
  busy.value = true; failed.value = false; contents.value = null
  try {
    const result = await getClientAidrContent(props.clientId, props.source, String(props.recordId))
    if (request === generation && allowed.value) contents.value = result.contents
  } catch (error) {
    if (request === generation) { failed.value = true; errorCode.value = error.response?.data?.error_code || 'aidr.content_request_failed' }
  } finally { if (request === generation) busy.value = false }
}
watch(() => JSON.stringify([props.clientId, props.source, props.recordId, allowed.value, descriptors.value]), () => {
  clear()
  if (allowed.value && descriptors.value.length) load()
}, { immediate: true })
onBeforeUnmount(clear)
</script>
<style scoped>
.audit-content { margin: 16px 0; overflow-wrap: anywhere; }
.audit-content pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 35vh; overflow: auto; }
.audit-content-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 8px; }
.audit-content-heading h4 { margin: 0; }
.audit-content-note { color: #667085; }
.audit-content pre { background: #f6f8fa; padding: 12px 14px; border-radius: 6px; }
.audit-content-fragment p { margin-bottom: 6px; }
</style>
