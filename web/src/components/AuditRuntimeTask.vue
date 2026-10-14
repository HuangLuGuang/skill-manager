<template>
  <a-alert v-if="error" type="error" :message="ui('failure')" show-icon><template #action><a-button @click="load">{{ t('auditLog.retry') }}</a-button></template></a-alert>
  <a-spin :spinning="loading">
    <template v-if="task">
      <h3>{{ task.task_id }}</h3>
      <a-descriptions :column="1" size="small" bordered>
        <a-descriptions-item :label="t('auditTrail.agent')">{{ task.agent_id }}</a-descriptions-item>
        <a-descriptions-item :label="ui('status')">{{ state(task.status) }}</a-descriptions-item>
        <a-descriptions-item :label="ui('created')">{{ time(task.created_at) }}</a-descriptions-item>
        <a-descriptions-item :label="ui('completed')">{{ time(task.completed_at) }}</a-descriptions-item>
        <a-descriptions-item :label="ui('steps')">{{ task.usage?.steps }}</a-descriptions-item>
        <a-descriptions-item :label="ui('retries')">{{ task.usage?.retries }}</a-descriptions-item>
        <a-descriptions-item v-if="task.stop_reason" :label="ui('reason')">{{ reason(task.stop_reason) }}</a-descriptions-item>
      </a-descriptions>
      <h4>{{ ui('actions') }}</h4>
      <a-empty v-if="!task.actions?.length" :description="ui('empty')" />
      <article v-for="action in task.actions" :key="action.action_id" class="runtime-action">
        <strong>{{ action.action_type }}</strong><small>{{ action.action_id }}</small>
        <dl><dt>{{ ui('target') }}</dt><dd>{{ action.target }}</dd><dt>{{ ui('decision') }}</dt><dd>{{ state(action.decision) }}</dd><dt>{{ ui('outcome') }}</dt><dd>{{ state(action.status) }}</dd><template v-if="action.decision_reasons?.length"><dt>{{ t('auditTrail.fields.decision_reasons') }}</dt><dd>{{ action.decision_reasons.map(reason).join(' · ') }}</dd></template></dl>
      </article>
      <p class="muted">{{ ui('boundary') }}</p>
    </template>
  </a-spin>
</template>
<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { getRuntimeTask } from '../api'
const props = defineProps({ taskId:String })
const { t, te, locale } = useI18n()
const ui = key => t('auditTrail.task.' + key)
const state = value => te('auditTrail.task.states.' + value) ? ui('states.' + value) : ui('states.unknown')
const reason = value => te('auditTrail.reasons.' + value) ? t('auditTrail.reasons.' + value) : value
const time = value => value ? new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + 'Z').toLocaleString(locale.value, { hour12:false, timeZone:'Asia/Shanghai' }) : '—'
const task = ref(null), error = ref(false), loading = ref(false)
let request = 0
async function load() {
  const id = ++request; loading.value = true; error.value = false; task.value = null
  try { const data = await getRuntimeTask(props.taskId); if (id === request) task.value = data }
  catch { if (id === request) error.value = true }
  finally { if (id === request) loading.value = false }
}
watch(() => props.taskId, load, { immediate:true })
onBeforeUnmount(() => { request++ })
</script>
<style scoped>
h3, dd, strong, small { overflow-wrap:anywhere; } h4 { margin-top:24px; } small { display:block; color:#697586; } .runtime-action { padding:16px 0; border-bottom:1px solid #e8edf2; } dl { display:grid; grid-template-columns:120px minmax(0,1fr); gap:10px; } dt,.muted { color:#697586; } dd { margin:0; }
</style>
