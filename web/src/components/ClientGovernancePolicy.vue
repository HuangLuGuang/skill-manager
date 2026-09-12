<template>
  <a-modal :open="open" :title="t(clientId ? 'clientGovernance.title' : 'clientGovernance.defaults')" width="820px" :footer="null" @cancel="emit('update:open', false)">
    <a-spin :spinning="loading">
      <template v-if="policy">
        <a-alert v-if="!impact" type="info" show-icon :message="t('clientGovernance.description')" />
        <a-alert v-if="!editable" type="warning" :message="t(policy.supported ? 'clientGovernance.readonly' : 'clientGovernance.upgrade')" />
        <a-alert v-if="!impact && clientId && policy.advanced_supported === false" type="warning" show-icon :message="t('clientGovernance.capabilityAvailable')" />
        <a-form v-if="!impact" layout="vertical" class="policy-form">
          <section v-for="group in groups" :key="group.key" class="policy-group">
            <header class="group-heading">
              <h3>{{ t(`clientGovernance.groups.${group.key}.title`) }}</h3>
              <p>{{ t(`clientGovernance.groups.${group.key}.description`) }}</p>
            </header>
            <div class="group-rules">
              <div v-for="trigger in group.triggers" :key="trigger" :ref="element => ruleFields[trigger] = element" class="rule-field" :data-rule="trigger" :class="{ 'priority-rule': trigger === 'malicious' }">
                <a-form-item>
                  <template #label>
                    {{ t(`clientGovernance.${trigger}`) }}
                    <span v-if="trigger === 'malicious'" class="priority-label">{{ t('clientGovernance.priority') }}</span>
                  </template>
                  <a-select :value="rules[trigger] || ''" :disabled="!editable || busy" @change="value => setRule(trigger, value)">
                    <a-select-option v-if="clientId" value="">{{ t('clientGovernance.inherit') }}</a-select-option>
                    <a-select-option v-for="action in choices[trigger]" :key="action" :value="action">{{ t(`clientGovernance.${action}`) }}</a-select-option>
                  </a-select>
                  <div class="effective">{{ t('clientGovernance.effective', { action: t(`clientGovernance.${policy.rules[trigger]}`) }) }}</div>
                  <button v-if="draftAction(trigger) === 'submit_scan'" type="button" class="scan-followup" @click="focusRule(rejectionRule(trigger))">
                    {{ t('clientGovernance.scanFollowup', { action: t(`clientGovernance.${draftAction(rejectionRule(trigger))}`) }) }}
                    <span>{{ t('clientGovernance.configureFollowup') }} →</span>
                  </button>
                </a-form-item>
              </div>
            </div>
          </section>
        </a-form>
        <template v-else>
          <p>{{ t('clientGovernance.candidates', { clients: impact.client_count, count: impact.candidate_count }) }}</p>
          <a-alert v-if="impact.excluded_clients?.length" type="warning" show-icon :message="t('clientGovernance.excludedTitle', { count: impact.excluded_clients.length })" class="excluded-clients">
            <template #description>
              <ul>
                <li v-for="client in impact.excluded_clients" :key="client.client_id">
                  <strong>{{ client.client_name || client.client_id }}</strong> — {{ t(`clientGovernance.exclusion.${client.reason}`) }}
                </li>
              </ul>
              <p>{{ t('clientGovernance.excludedNext') }}</p>
            </template>
          </a-alert>
          <a-alert v-if="impact.incompatible_clients?.length" type="warning" show-icon :message="t('clientGovernance.capabilityTitle')" class="excluded-clients">
            <template #description>
              <p>{{ t('clientGovernance.capabilityHint') }}</p>
              <ul><li v-for="client in impact.incompatible_clients" :key="client.client_id">{{ client.client_name || client.client_id }} · {{ client.rules.map(rule => t(`clientGovernance.${rule}`)).join(' / ') }}</li></ul>
            </template>
          </a-alert>
          <a-alert v-if="impact.contains_uninstall" type="warning" show-icon :message="t('clientGovernance.uninstallWarning')" />
          <details v-if="impact.items?.some(item => item.effect === 'recheck')" class="recheck-help">
            <summary>{{ t('clientGovernance.recheckCompact', { count: impact.items.filter(item => item.effect === 'recheck').length }) }} <span>{{ t('clientGovernance.howToHandle') }}</span></summary>
            <div class="recheck-instructions">
              <p>{{ t('clientGovernance.recheckSteps') }}</p>
              <p v-if="impact.items?.some(item => ['broken_link', 'unscannable', 'external_link'].includes(item.recheck_reason))">{{ t('clientGovernance.recheckBlocked') }}</p>
              <p>{{ t('clientGovernance.recheckSave') }}</p>
            </div>
          </details>
          <p class="effective">{{ t('clientGovernance.expandHint') }}</p>
          <a-table class="impact-tree" :data-source="impactTree" :columns="columns" row-key="key" :expanded-row-keys="expandedKeys" @expandedRowsChange="keys => expandedKeys = keys" :pagination="{ pageSize: 8, hideOnSinglePage: true }" :locale="{ emptyText: t('clientGovernance.empty') }" size="small" table-layout="fixed">
            <template #bodyCell="{ column, record }">
              <template v-if="column.dataIndex === 'name'">
                <span class="impact-name">{{ record.name }}</span>
                <div v-if="record.path" class="impact-path">{{ record.path }}</div>
                <div v-if="record.path" class="impact-effect" :class="{ changed: record.effect === 'changed' }">
                  <details v-if="record.effect === 'recheck'" class="skill-reason">
                    <summary>{{ t(`clientGovernance.reasonShort.${record.recheck_reason || 'missing_observation'}`) }} <span>{{ t('clientGovernance.howToHandle') }}</span></summary>
                    <p>{{ t(`clientGovernance.recheckReason.${record.recheck_reason || 'missing_observation'}`) }}</p>
                  </details>
                  <template v-else>
                    <span>{{ record.trigger ? t(`clientGovernance.${record.trigger}`) : t('clientGovernance.noTrigger') }}</span>
                    <div>{{ t('clientGovernance.currentAction') }}: {{ t(`clientGovernance.${record.current_action}`) }} → {{ t('clientGovernance.proposedAction') }}: {{ t(`clientGovernance.${record.proposed_action}`) }}</div>
                    <span v-if="record.client_override">{{ t('clientGovernance.overrideUnaffected') }}</span>
                    <span v-else-if="record.effect === 'unchanged'">{{ t('clientGovernance.unchanged') }}</span>
                  </template>
                </div>
                <div v-else class="impact-summary">{{ summaryText(record) }}</div>
              </template>
            </template>
          </a-table>
        </template>
        <div class="actions">
          <a-button v-if="impact" :disabled="busy" @click="impact = null">{{ t('clientGovernance.back') }}</a-button>
          <a-button :disabled="busy" @click="emit('update:open', false)">{{ t('clientGovernance.cancel') }}</a-button>
          <a-button type="primary" :loading="busy" :disabled="!editable || busy || !!impact?.incompatible_clients?.length" @click="impact ? save() : preview()">{{ t(impact ? 'clientGovernance.confirm' : 'clientGovernance.preview') }}</a-button>
        </div>
      </template>
    </a-spin>
  </a-modal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { can } from '../access'
import { getClientGovernance, previewClientGovernance, saveClientGovernance } from '../api'
const props = defineProps({ open: Boolean, clientId: { type: String, default: '' } })
const emit = defineEmits(['update:open', 'saved'])
const { t } = useI18n()
const policy = ref(null), rules = ref({}), impact = ref(null), loading = ref(false), busy = ref(false)
const expandedKeys = ref([])
const impactTree = computed(() => {
  const clients = new Map()
  for (const client of impact.value?.clients || []) {
    clients.set(client.client_id, { key: JSON.stringify(['client', client.client_id]), name: client.client_name || client.client_id, agent_count: 0, skill_count: 0, agents: new Map() })
  }
  for (const item of impact.value?.items || []) {
    if (!clients.has(item.client_id)) clients.set(item.client_id, { key: JSON.stringify(['client', item.client_id]), name: item.client_name || item.client_id, agent_count: 0, skill_count: 0, agents: new Map() })
    const client = clients.get(item.client_id)
    if (!client.agents.has(item.agent_type)) client.agents.set(item.agent_type, { key: JSON.stringify(['agent', item.client_id, item.agent_type]), name: item.agent_type, skill_count: 0, children: [] })
    const agent = client.agents.get(item.agent_type)
    agent.children.push({ ...item, key: JSON.stringify(['skill', item.client_id, item.agent_type, item.path]), name: item.skill_name })
    agent.skill_count += 1
    client.skill_count += 1
  }
  return [...clients.values()].map(({ agents, ...client }) => ({ ...client, agent_count: [...agents.keys()].filter(type => type !== 'global-skills').length, ...(agents.size ? { children: [...agents.values()] } : {}) }))
})
const summaryText = record => {
  const skills = (record.children || []).flatMap(child => child.children || [child])
  const counts = {}
  for (const skill of skills) {
    const key = skill.effect === 'changed' ? skill.proposed_action : skill.effect === 'unchanged' ? 'unchanged' : 'recheck'
    counts[key] = (counts[key] || 0) + 1
  }
  return Object.entries(counts).map(([key, count]) => `${t(`clientGovernance.${key}`)} ${count}`).join(' · ')
}
let loadSequence = 0
const editable = computed(() => can('clients:update') && policy.value?.supported && (props.clientId || policy.value?.editable))
const choices = {
  unverified: ['record_only', 'record', 'submit_scan', 'quarantine'], malicious: ['record_only', 'record', 'quarantine', 'uninstall'],
  trusted_content_changed: ['record_only', 'record', 'submit_scan', 'quarantine', 'restore_trusted'], unverified_content_changed: ['record_only', 'record', 'submit_scan', 'quarantine'],
  trusted_scan_rejected: ['record_only', 'record', 'quarantine', 'restore_trusted'],
  unverified_scan_rejected: ['record_only', 'record', 'quarantine'],
}
const groups = [
  { key: 'unverified', triggers: ['unverified', 'unverified_content_changed'] },
  { key: 'certified', triggers: ['trusted_content_changed'] },
  { key: 'results', triggers: ['malicious', 'trusted_scan_rejected', 'unverified_scan_rejected'] },
]
const ruleFields = ref({})
const draftAction = trigger => rules.value[trigger] || policy.value.defaults?.[trigger] || policy.value.rules[trigger]
const rejectionRule = trigger => trigger === 'trusted_content_changed' ? 'trusted_scan_rejected' : 'unverified_scan_rejected'
const focusRule = trigger => {
  const element = ruleFields.value[trigger]
  element?.scrollIntoView({ block: 'center', behavior: 'auto' })
  element?.querySelector('input')?.focus({ preventScroll: true })
}
const columns = computed(() => [
  { title: t('clientGovernance.client'), dataIndex: 'name' },
  { title: t('clientGovernance.agentCount'), dataIndex: 'agent_count', width: 110, align: 'right' },
  { title: t('clientGovernance.skillCount'), dataIndex: 'skill_count', width: 110, align: 'right' },
])
const setRule = (trigger, action) => { impact.value = null; if (action) rules.value[trigger] = action; else delete rules.value[trigger] }
async function load() {
  const sequence = ++loadSequence
  busy.value = false; impact.value = null; policy.value = null
  if (!props.open) return
  loading.value = true
  const clientId = props.clientId
  try {
    const result = await getClientGovernance(clientId)
    if (sequence !== loadSequence) return
    policy.value = result
    rules.value = { ...(clientId ? result.overrides : result.rules) }
  } catch (error) { if (sequence === loadSequence) message.error(error.response?.data?.detail || t('clientGovernance.failed')) }
  finally { if (sequence === loadSequence) loading.value = false }
}
watch(() => [props.open, props.clientId], load, { immediate: true })
const payload = () => ({ rules: { ...rules.value }, expected_version: policy.value.version })
const current = (sequence, clientId) => sequence === loadSequence && props.open && clientId === props.clientId
async function handleError(error) {
  const code = error.apiErrorCode || error.response?.data?.error_code
  if (code === 'client.policy_changed') {
    message.warning(t('clientGovernance.policyChanged'))
    await load()
  } else {
    impact.value = null
    message.error(code === 'client.policy_preview_required' ? t('clientGovernance.previewChanged') : error.response?.data?.detail || t('clientGovernance.failed'))
  }
}
async function preview() {
  if (busy.value || loading.value || !props.open || !editable.value) return
  const sequence = loadSequence, clientId = props.clientId, request = payload()
  busy.value = true
  try {
    const result = await previewClientGovernance(clientId, request)
    if (current(sequence, clientId)) { expandedKeys.value = []; impact.value = { ...result, request } }
  }
  catch (error) { if (current(sequence, clientId)) await handleError(error) }
  finally { if (current(sequence, clientId)) busy.value = false }
}
async function save() {
  if (busy.value || loading.value || !props.open || !editable.value || !impact.value || impact.value.incompatible_clients?.length) return
  const sequence = loadSequence, clientId = props.clientId
  const request = { ...impact.value.request, preview_id: impact.value.preview_id }
  busy.value = true
  try {
    await saveClientGovernance(clientId, request)
    if (!current(sequence, clientId)) return
    message.success(t('clientGovernance.saved')); emit('saved'); emit('update:open', false)
  } catch (error) { if (current(sequence, clientId)) await handleError(error) }
  finally { if (current(sequence, clientId)) busy.value = false }
}
</script>

<style scoped>
.policy-form { margin-top: 16px; display: grid; gap: 16px; max-height: 62vh; overflow-y: auto; padding: 2px 6px 2px 2px; }
.policy-group { border: 1px solid #e6eaf0; border-radius: 8px; padding: 16px; }
.group-heading { margin-bottom: 14px; }
.group-heading h3 { margin: 0; font-size: 15px; font-weight: 600; }
.group-heading p { margin: 4px 0 0; color: #777; font-size: 12px; line-height: 1.5; }
.group-rules { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 24px; }
.rule-field { min-width: 0; scroll-margin: 20px; }
.priority-rule { grid-column: 1 / -1; }
.priority-label { margin-left: 8px; color: #ad5925; background: #fff7e8; border-radius: 4px; padding: 0 6px; font-size: 12px; white-space: nowrap; }
.policy-form :deep(.ant-form-item) { margin-bottom: 0; min-width: 0; }
.policy-form :deep(.ant-form-item-label > label) { height: auto; flex-wrap: wrap; }
.scan-followup { display: block; width: 100%; margin-top: 8px; padding: 8px 10px; border: 0; border-radius: 4px; background: #f5f8ff; color: #4c6075; text-align: start; font: inherit; font-size: 12px; line-height: 1.5; cursor: pointer; overflow-wrap: anywhere; }
.scan-followup span { color: #1677ff; margin-left: 6px; }
.scan-followup:focus-visible { outline: 2px solid #1677ff; outline-offset: 2px; }
@media (max-width: 600px) { .group-rules { grid-template-columns: minmax(0, 1fr); } }
.recheck-help { margin-top: 12px; padding: 10px 12px; border-radius: 6px; background: #f5f7fa; color: #596975; }
.recheck-help summary, .skill-reason summary { cursor: pointer; font-size: 12px; line-height: 1.6; }
.recheck-help summary span, .skill-reason summary span { margin-left: 8px; color: #1677ff; }
.recheck-instructions { padding-top: 6px; }
.skill-reason p { margin: 6px 0 0; }
.recheck-help p { margin: 6px 0 0; line-height: 1.6; }
.impact-name, .impact-path { overflow-wrap: anywhere; }
.impact-path { margin: 4px 0 0 54px; color: #697986; font-size: 12px; line-height: 1.5; }
.impact-effect { margin: 6px 0 0 54px; font-size: 12px; line-height: 1.6; color: #687681; overflow-wrap: anywhere; }
.impact-effect.changed { color: #ad5925; background: #fff8ed; padding: 6px 8px; border-radius: 4px; }
.impact-summary { margin-top: 4px; color: #687681; font-size: 12px; overflow-wrap: anywhere; }
.impact-tree :deep(.ant-table-cell) { vertical-align: top; }
.excluded-clients { margin-bottom: 16px; overflow-wrap: anywhere; }
.excluded-clients ul { padding-left: 18px; margin: 8px 0; }
.excluded-clients p { margin-bottom: 0; }
.effective { color: #777; margin-top: 6px; overflow-wrap: anywhere; }
.actions { margin-top: 20px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
</style>
