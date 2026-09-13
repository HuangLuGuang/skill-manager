<template>
  <div class="skill-actions">
    <a-select :value="null" :placeholder="t('clientGovernance.chooseAction')" :disabled="Boolean(disabledReason) || busy" :title="disabledReason" @change="prepare">
      <a-select-option v-for="action in actions" :key="action" :value="action" :disabled="action === 'restore_trusted' && !skill.governance?.trusted_version_id">
        {{ t(action === 'restore_trusted' && !skill.governance?.trusted_version_id ? 'clientGovernance.noTrustedVersion' : `clientGovernance.${action}`) }}
      </a-select-option>
    </a-select>
    <small v-if="disabledReason">{{ disabledReason }}</small>
    <a-modal :open="Boolean(request)" :title="request ? t(`clientGovernance.${request.action}`) : ''" :confirm-loading="busy" :ok-button-props="{ disabled: busy || Boolean(disabledReason) }" :cancel-button-props="{ disabled: busy }" :closable="!busy" :mask-closable="!busy" :keyboard="!busy" :ok-text="t('clientGovernance.createTask')" @ok="submit" @cancel="request = null">
      <p>{{ t(request?.action === 'restore_backup' ? 'clientGovernance.backupConfirmation' : recovery ? 'clientGovernance.recoveryConfirmation' : request?.action === 'submit_scan' ? 'clientGovernance.scanConfirmation' : 'clientGovernance.fileConfirmation') }}</p>
      <p><strong>{{ client.name }} · {{ agent.agent_type }}</strong></p>
      <code>{{ path }}</code>
      <a-alert v-if="sharedReaders.length" type="warning" show-icon :message="t('clientGovernance.sharedImpact', { agents: sharedReaders.join(', ') })" />
      <a-alert v-if="disabledReason" type="warning" :message="disabledReason" />
      <a-alert v-if="errorMessage" type="error" :message="errorMessage" />
    </a-modal>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { createClientTask } from '../api'
const props = defineProps({ client: { type: Object, required: true }, agent: { type: Object, required: true }, skill: { type: Object, required: true }, recovery: Boolean })
const emit = defineEmits(['created'])
const { t } = useI18n()
const request = ref(null), busy = ref(false), errorMessage = ref('')
const path = computed(() => props.recovery ? props.skill.original_path : props.skill.path)
const sharedReaders = computed(() => {
  const capabilities = props.agent.capabilities || {}
  const root = String(path.value || '').replace(/[\\/][^\\/]+$/, '')
  return capabilities.shared_skill_readers_by_path?.[path.value]
    ?? capabilities.shared_skill_readers_by_root?.[root]
    ?? (capabilities.shared_skills ? capabilities.shared_skill_readers || [] : [])
})
watch(() => [props.client.client_id, path.value], () => { request.value = null; errorMessage.value = '' })
const certified = computed(() => Boolean(props.skill.signature) && props.skill.governance?.signature === props.skill.signature && props.skill.governance?.certification === 'certified')
const actions = computed(() => props.recovery ? [props.skill.status === 'backed_up' ? 'restore_backup' : 'restore_quarantine'] : ['submit_scan', ...(certified.value ? [] : ['quarantine']), 'uninstall', 'restore_trusted'])
const disabledReason = computed(() => {
  if (!can('clients:execute')) return t('clientGovernance.noActionPermission')
  if (!props.client.classification?.supported) return t('clientGovernance.upgrade')
  if (!props.agent.skill_management_supported || !props.agent.skills_path || props.agent.capabilities?.path_available === false) return t('clientGovernance.targetUnavailable')
  if (!props.skill.signature || props.skill.error || props.skill.error_code) return t('clientGovernance.contentUnavailable')
  if ((props.client.tasks || []).some(task => task.task_type === 'skill_action' && task.payload?.path === path.value && ['pending', 'running'].includes(task.status))) return t('clientGovernance.actionPending')
  return ''
})
function prepare(action) {
  if (busy.value || disabledReason.value || !actions.value.includes(action)) return
  errorMessage.value = ''
  request.value = {
    request_id: crypto.randomUUID(), action, agent_type: props.agent.agent_type, local_agent_id: props.agent.local_agent_id,
    path: path.value, expected_signature: props.skill.signature,
    ...(props.recovery ? { quarantine_id: props.skill.id } : {}),
    ...(action === 'restore_backup' ? { expected_target_signature: (props.agent.skills || []).find(skill => skill.path === path.value)?.signature || null } : {}),
    ...(action === 'restore_trusted' ? { version_id: props.skill.governance.trusted_version_id } : {}),
  }
}
async function submit() {
  if (busy.value || disabledReason.value || !request.value) return
  busy.value = true
  const clientId = props.client.client_id
  try {
    const task = await createClientTask(clientId, { task_type: 'skill_action', payload: { ...request.value } })
    request.value = null
    message.success(t('clientGovernance.taskCreated'))
    emit('created', { clientId, taskId: task.id })
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || t('clientGovernance.taskFailed')
  } finally { busy.value = false }
}
</script>

<style scoped>
.skill-actions { min-width: 170px; max-width: 250px; }
.skill-actions .ant-select { width: 100%; }
small { display: block; color: #777; overflow-wrap: anywhere; margin-top: 4px; }
code { display: block; white-space: pre-wrap; overflow-wrap: anywhere; margin-bottom: 16px; }
.ant-alert + .ant-alert { margin-top: 12px; }
</style>
