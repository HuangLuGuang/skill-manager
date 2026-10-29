<template>
  <a-card :title="embedded ? undefined : t(section === 'skill' ? 'clientPolicy.usageAudit' : 'aidr.redactionSettings.title')" :loading="loading" class="aidr-redaction-settings" :class="{ embedded }" :bordered="!embedded">
    <template v-if="!embedded" #extra><a-tag color="blue">{{ t(clientId ? (inherit ? 'aidr.policyNavigation.inherited' : 'aidr.policyNavigation.clientScope') : 'aidr.policyNavigation.global') }}</a-tag></template>
    <a-alert v-if="failed" type="error" :message="t('aidr.redactionSettings.loadFailed')" show-icon>
      <template #action><a-button :disabled="loading || busy" @click="load">{{ t('aidr.redactionSettings.retry') }}</a-button></template>
    </a-alert>
    <template v-else-if="summary">
      <a-space wrap>
        <a-tag>{{ t(policy.lifecycle?.enabled ? 'aidr.lifecycle.enabled' : 'aidr.lifecycle.disabled') }}</a-tag>
        <a-tag>{{ t(policy.enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') }}</a-tag>
      </a-space>
      <p>{{ t('aidr.policyNavigation.scope') }}</p>
      <router-link v-if="pageAllowed('/clients') && can('settings:view')" :to="{ path: '/clients', query: { policy: 'audit' } }">
        <a-button>{{ t('aidr.policyNavigation.open') }}</a-button>
      </router-link>
    </template>
    <template v-else>
      <p v-if="section === 'skill'" class="setting-help">{{ t('clientPolicy.usageHelp') }}</p>
      <p v-else class="setting-help">{{ t('aidr.contentSettings.applies') }}</p>
      <template v-if="clientId">
        <div class="inherit-control"><a-switch :checked="inherit" :disabled="busy || !editable" :aria-label="t(section === 'skill' ? 'clientPolicy.inheritUsage' : 'clientPolicy.inheritContent')" @change="setInheritance" /><span>{{ t(section === 'skill' ? 'clientPolicy.inheritUsage' : 'clientPolicy.inheritContent') }}</span></div>
      </template>
      <a-alert v-if="saveFailed" type="error" :message="t('aidr.redactionSettings.saveFailed')" show-icon>
        <template #action><a-button :disabled="loading || busy" @click="load">{{ t('aidr.redactionSettings.retry') }}</a-button></template>
      </a-alert>
      <section v-if="section === 'content'" class="other-policy"><h4>{{ t('aidr.policyNavigation.redaction') }}</h4>
      <div class="setting-switch-row"><a-switch v-model:checked="enabled" :disabled="fieldsDisabled" :aria-label="t('aidr.policyNavigation.redaction')" /><span>{{ t(enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') }}</span></div>
      <p class="setting-help">{{ t('aidr.contentSettings.redaction') }}</p>
      </section>
      <SkillAuditPolicyFields v-if="section === 'skill'" v-model="skillAudit" :disabled="fieldsDisabled" />
      <div v-if="section === 'skill'" class="delivery-state">
        <strong>{{ t('aidr.skillUse.policy.delivery') }}</strong>
        <p>{{ t('aidr.skillUse.policy.deliveryHelp') }}</p>
        <template v-if="clientId && policy.skill_audit_runtime?.skill_audit">
          <p>{{ t('aidr.skillUse.policy.reported', { time: policy.skill_audit_runtime.reported_at || '—' }) }}</p>
          <p>{{ t(sameSkillAudit(policy.skill_audit_runtime.skill_audit, policy.skill_audit) ? 'aidr.skillUse.policy.reportMatches' : 'aidr.skillUse.policy.reportDiffers') }}</p>
        </template>
        <p v-else-if="clientId">{{ t('aidr.skillUse.policy.noReport') }}</p>
      </div>
      <section v-if="section === 'content'" class="other-policy"><h4>{{ t('aidr.content.scopeTitle') }}</h4>
      <div class="setting-switch-row"><a-switch v-model:checked="lifecycle.enabled" :disabled="fieldsDisabled" :aria-label="t('aidr.lifecycle.collection')" /><span>{{ t(lifecycle.enabled ? 'aidr.lifecycle.enabled' : 'aidr.lifecycle.disabled') }}</span></div>
      <p class="setting-help">{{ t('aidr.contentSettings.collection') }} <a-tooltip :title="t('aidr.lifecycle.collectionHelp')"><a-button type="text" size="small" :aria-label="t('aidr.lifecycle.collection')"><QuestionCircleOutlined /></a-button></a-tooltip></p>
      <div class="capture-options"><a-checkbox v-for="kind in scopeKinds" :key="kind" v-model:checked="capture[kind]" :disabled="fieldsDisabled">{{ t('aidr.content.kinds.' + kind) }}</a-checkbox></div>
      <p class="setting-help">{{ t('aidr.contentSettings.scope') }} <a-tooltip :title="t('aidr.content.support')"><a-button type="text" size="small" :aria-label="t('aidr.content.scopeTitle')"><QuestionCircleOutlined /></a-button></a-tooltip></p>
      <div class="content-limits">
        <label><span>{{ t('aidr.content.fragmentLimit') }}</span><a-input-number v-model:value="capture.max_fragment_bytes" :min="256" :max="32768" :precision="0" :disabled="fieldsDisabled" :aria-label="t('aidr.content.fragmentLimit')" /></label>
        <label><span>{{ t('aidr.content.eventLimit') }}</span><a-input-number v-model:value="capture.max_event_bytes" :min="256" :max="32768" :precision="0" :disabled="fieldsDisabled" :aria-label="t('aidr.content.eventLimit')" /></label>
      </div>
      <p v-if="!validLimits" class="limit-error" role="alert">{{ t('aidr.content.invalidLimits') }}</p>
      <p class="setting-help">{{ t('aidr.contentSettings.limits') }}</p>
      <div class="content-limits"><label for="aidr-retention-days"><span>{{ t('aidr.lifecycle.retention') }}</span><a-input-number id="aidr-retention-days" v-model:value="lifecycle.retention_days" :min="1" :max="365" :precision="0" :disabled="fieldsDisabled" /></label></div>
      <p class="setting-help">{{ t('aidr.contentSettings.retention') }}</p>
      </section>
      <a-button v-if="editable && !externalActions" type="primary" :loading="busy" :disabled="!canReview" @click="review">{{ t(section === 'skill' ? 'clientPolicy.saveUsage' : 'aidr.redactionSettings.save') }}</a-button>
    </template>
    <a-modal :z-index="1020" :width="720" wrap-class-name="aidr-policy-review" v-model:open="reviewOpen" :title="t('aidr.redactionSettings.reviewTitle')" :ok-text="t('aidr.redactionSettings.confirmSave')" :cancel-text="t('aidr.redactionSettings.cancelReview')" :confirm-loading="busy" :ok-button-props="{ disabled: busy || !editable || (requiresAcknowledgement && !acknowledged) }" :cancel-button-props="{ disabled: busy }" :closable="!busy" :mask-closable="!busy" :keyboard="!busy" @ok="save" @cancel="cancelReview">
      <template v-if="reviewTarget">
        <p v-if="section === 'content'">{{ t('aidr.policyReview.comparison') }}</p>
        <p v-if="clientId" class="setting-help">{{ t(reviewTarget.inherit ? 'aidr.policyNavigation.inherited' : 'aidr.policyNavigation.clientScope') }}</p>
        <SkillAuditPolicyReview v-if="section === 'skill'" :current="policy.skill_audit" :target="reviewTarget.skill_audit" />
        <a-descriptions v-if="section === 'content'" :column="1" size="small">
          <a-descriptions-item :label="t('aidr.policyNavigation.redaction')">{{ t(policy.enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') }} → {{ t(reviewTarget.enabled ? 'aidr.redactionSettings.on' : 'aidr.redactionSettings.off') }}</a-descriptions-item>
          <a-descriptions-item :label="t('aidr.lifecycle.collection')">{{ t((policy.lifecycle?.enabled ?? true) ? 'aidr.lifecycle.enabled' : 'aidr.lifecycle.disabled') }} → {{ t(reviewTarget.lifecycle.enabled ? 'aidr.lifecycle.enabled' : 'aidr.lifecycle.disabled') }}</a-descriptions-item>
          <a-descriptions-item v-for="kind in scopeKinds" :key="kind" :label="t('aidr.content.kinds.' + kind)">{{ t((policy.capture?.[kind] ?? false) ? 'aidr.redactionSettings.collect' : 'aidr.redactionSettings.doNotCollect') }} → {{ t(reviewTarget.capture[kind] ? 'aidr.redactionSettings.collect' : 'aidr.redactionSettings.doNotCollect') }}</a-descriptions-item>
          <a-descriptions-item :label="t('aidr.lifecycle.retention')">{{ policy.lifecycle?.retention_days ?? 7 }} → {{ reviewTarget.lifecycle.retention_days }}</a-descriptions-item>
          <a-descriptions-item v-for="(fallback, key) in limitDefaults" :key="key" :label="t(key === 'max_fragment_bytes' ? 'aidr.content.fragmentLimit' : 'aidr.content.eventLimit')">{{ policy.capture?.[key] ?? fallback }} → {{ reviewTarget.capture[key] }}</a-descriptions-item>
        </a-descriptions>
        <p v-if="section === 'content'" class="setting-help">{{ t('aidr.policyReview.contentEffect') }}</p>
        <a-alert v-if="requiresAcknowledgement" type="warning" show-icon :message="t('aidr.policyReview.risk')" />
        <a-checkbox v-if="requiresAcknowledgement" v-model:checked="acknowledged" :disabled="busy" style="margin-top: 12px">{{ t('aidr.policyReview.acknowledge') }}</a-checkbox>
      </template>
    </a-modal>
  </a-card>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'
import { can, pageAllowed } from '../access'
import { getAidrRedaction, saveAidrRedaction, getClientAuditPolicy, saveClientAuditPolicy } from '../api'
import SkillAuditPolicyFields from './SkillAuditPolicyFields.vue'
import SkillAuditPolicyReview from './SkillAuditPolicyReview.vue'
import { normalizeSkillAudit, validSkillAudit, sameSkillAudit } from '../skill-audit-policy'
const { t } = useI18n()
const props = defineProps({ summary: Boolean, embedded: Boolean, externalActions: Boolean, section: { type: String, default: 'content' }, clientId: { type: String, default: '' } })
const emit = defineEmits(['saved'])
const policyInheritance = value => (props.section === 'skill' ? value.skill_audit_inherit ?? value.inherit : value.inherit) ?? true
const inherit = ref(true)
const editable = computed(() => can('settings:update') && (!props.clientId || can('clients:update')) && policy.value.can_edit === true)
const policy = ref({ enabled: true, version: '1' }), enabled = ref(true)
const fieldsDisabled = computed(() => busy.value || !editable.value || (!!props.clientId && inherit.value))
const scopeKinds = ['prompt', 'model_response', 'tool_output', 'file_body', 'command_body']
const limitDefaults = { max_fragment_bytes: 1024, max_event_bytes: 2048 }
const capture = ref({ prompt: false, model_response: false, tool_output: false, file_body: false })
const skillAudit = ref(normalizeSkillAudit())
const lifecycle = ref({ enabled: true, retention_days: 7 })
const validRetention = computed(() => Number.isInteger(lifecycle.value.retention_days) && lifecycle.value.retention_days >= 1 && lifecycle.value.retention_days <= 365)
const validLimits = computed(() => Object.keys(limitDefaults).every(key => Number.isInteger(capture.value[key]) && capture.value[key] >= 256 && capture.value[key] <= 32768) && capture.value.max_fragment_bytes <= capture.value.max_event_bytes)
const changed = computed(() => props.section === 'skill'
  ? validSkillAudit(skillAudit.value) && ((props.clientId && inherit.value !== policyInheritance(policy.value)) || !sameSkillAudit(skillAudit.value, policy.value.skill_audit))
  : validLimits.value && validRetention.value && ((props.clientId && inherit.value !== policyInheritance(policy.value)) || enabled.value !== policy.value.enabled || scopeKinds.some(kind => capture.value[kind] !== (policy.value.capture?.[kind] ?? false)) || Object.entries(limitDefaults).some(([key, fallback]) => capture.value[key] !== (policy.value.capture?.[key] ?? fallback)) || lifecycle.value.enabled !== (policy.value.lifecycle?.enabled ?? true) || lifecycle.value.retention_days !== (policy.value.lifecycle?.retention_days ?? 7)))
const loading = ref(false), failed = ref(false), saveFailed = ref(false), busy = ref(false)
const reviewOpen = ref(false), reviewTarget = ref(null), acknowledged = ref(false)
const canReview = computed(() => !busy.value && !loading.value && !failed.value && !reviewOpen.value && editable.value && changed.value)
defineExpose({ editable, canReview, busy, reviewOpen, review })
const requiresAcknowledgement = computed(() => props.section === 'content' && reviewTarget.value && (
  (policy.value.enabled && !reviewTarget.value.enabled) ||
  scopeKinds.some(kind => reviewTarget.value.capture[kind] && !(policy.value.capture?.[kind] ?? false)) ||
  Object.entries(limitDefaults).some(([key, fallback]) => reviewTarget.value.capture[key] > (policy.value.capture?.[key] ?? fallback)) ||
  reviewTarget.value.lifecycle.retention_days < (policy.value.lifecycle?.retention_days ?? 7)
))
let mounted = true
onMounted(load)
onBeforeUnmount(() => { mounted = false; reviewOpen.value = false; reviewTarget.value = null })
async function load() {
  if (loading.value || busy.value) return
  loading.value = true
  try {
    const value = await (props.clientId ? getClientAuditPolicy(props.clientId) : getAidrRedaction())
    if (!mounted) return
    applyPolicy(value)
    failed.value = false
    saveFailed.value = false
  } catch { if (mounted) failed.value = true }
  finally { if (mounted) loading.value = false }
}
function applyDraft(value) {
  skillAudit.value = normalizeSkillAudit(value.skill_audit)
  enabled.value = value.enabled
  capture.value = Object.fromEntries(scopeKinds.map(kind => [kind, value.capture?.[kind] ?? false]))
  for (const [key, fallback] of Object.entries(limitDefaults)) capture.value[key] = value.capture?.[key] ?? fallback
  lifecycle.value = { enabled: value.lifecycle?.enabled ?? true, retention_days: value.lifecycle?.retention_days ?? 7 }
}
function applyPolicy(value) {
  policy.value = { ...value, can_edit: value.can_edit ?? policy.value.can_edit }
  inherit.value = policyInheritance(value)
  applyDraft(value)
}
function setInheritance(value) {
  inherit.value = value
  if (value) applyDraft(policy.value.global_policy)
}
async function review() {
  if (!canReview.value) return
  busy.value = true
  try {
    const latest = await (props.clientId ? getClientAuditPolicy(props.clientId) : getAidrRedaction())
    if (!mounted) return
    const ownValues = value => JSON.stringify(props.section === 'skill' ? [normalizeSkillAudit(value.skill_audit), policyInheritance(value)] : [value.enabled, value.capture, value.lifecycle, policyInheritance(value)])
    if (ownValues(latest) !== ownValues(policy.value)) { message.warning(t('clientPolicy.auditConflict')); return }
    policy.value = latest
    const draft = props.clientId && inherit.value ? latest.global_policy : { skill_audit: normalizeSkillAudit(skillAudit.value), enabled: enabled.value, capture: { ...capture.value }, lifecycle: { ...lifecycle.value } }
    reviewTarget.value = { section: props.section, skill_audit: props.section === 'skill' ? draft.skill_audit : latest.skill_audit, enabled: props.section === 'content' ? draft.enabled : latest.enabled, capture: props.section === 'content' ? draft.capture : latest.capture, lifecycle: props.section === 'content' ? draft.lifecycle : latest.lifecycle, version: latest.version, ...(props.clientId ? { inherit: inherit.value, global_version: latest.global_policy.version } : {}) }
  acknowledged.value = false
  reviewOpen.value = true
  } catch { message.error(t('aidr.redactionSettings.loadFailed')) }
  finally { if (mounted) busy.value = false }
}
function cancelReview() {
  if (busy.value) return
  reviewOpen.value = false
  reviewTarget.value = null
  acknowledged.value = false
}
async function save() {
  if (busy.value || loading.value || failed.value || !editable.value || !reviewOpen.value || !reviewTarget.value || (requiresAcknowledgement.value && !acknowledged.value)) return
  busy.value = true
  saveFailed.value = false
  try {
    const value = await (props.clientId ? saveClientAuditPolicy(props.clientId, reviewTarget.value) : saveAidrRedaction(reviewTarget.value))
    if (!mounted) return
    applyPolicy(value)
    reviewOpen.value = false
    reviewTarget.value = null
    message.success(t('aidr.redactionSettings.saved'))
    emit('saved')
  }
  catch { if (mounted) { saveFailed.value = true; reviewOpen.value = false; reviewTarget.value = null } }
  finally { if (mounted) busy.value = false }
}
</script>
<style scoped>
.aidr-redaction-settings { margin: 20px 0; overflow-wrap: anywhere; }
.aidr-redaction-settings.embedded { margin: 0; border: 0; border-radius: 0; box-shadow: none; background: transparent; }
.embedded :deep(.ant-card-body) { padding: 0; }
.inherit-control, .setting-switch-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.inherit-control { margin: 16px 0; }
.ant-checkbox-wrapper { margin-top: 12px; }
.content-limits { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; margin: 16px 0; }
.content-limits label { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.content-limits .ant-input-number { width: 100%; }
.limit-error { color: #b42318; }
.other-policy { padding: 16px 0; } .other-policy + .other-policy { border-top: 1px solid #e2e8f0; } .other-policy h4 { font-weight: 600; margin: 0 0 12px; }
.setting-help { color: #64748b; font-size: 12px; margin: 8px 0 12px; }
.capture-options { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 16px;margin:12px 0; }.capture-options .ant-checkbox-wrapper { margin:0; }
@media(max-width:600px) { .capture-options, .content-limits { grid-template-columns:1fr; } }
.delivery-state { background: #f8fafc; border-radius: 8px; padding: 12px 14px; margin: 16px 0; font-size: 12px; } .delivery-state p { margin: 8px 0 0; color: #64748b; }
:global(.aidr-policy-review .ant-modal) { top: 24px; padding-bottom: 24px; }
:global(.aidr-policy-review .ant-modal-body) { max-height: calc(100dvh - 180px); overflow-y: auto; overflow-wrap: anywhere; }
</style>
