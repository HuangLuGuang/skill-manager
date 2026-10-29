<template>
  <section class="system-selection" :aria-busy="loading">
    <header><a-tag>{{ t(`clientGovernance.runtime.mode_${state.mode || 'audit'}`) }}</a-tag><a-button :loading="loading" :disabled="loading || saving" @click="load(true)"><ReloadOutlined />{{ tr('reload') }}</a-button></header>
    <p class="runtime-state"><a-badge :status="['active', 'collecting'].includes(status.state) ? 'success' : 'default'" />{{ t(`aidr.enforcement.states.${status.state || 'unknown'}`) }}<span v-if="status.last_received_at">{{ tr('lastReport', { time: time(status.last_received_at) }) }}</span></p>
    <a-alert v-if="error" type="error" show-icon :message="tr('failed')" :description="errorText" />
    <a-alert v-if="status.platform_support && status.platform_support !== 'macos_endpoint_security'" type="info" show-icon :message="t(`aidr.enforcement.setup.platforms.${status.platform_support}`)" />
    <section class="requirements">
      <p v-if="loaded && !state.configured && state.configured_roots?.length" class="field-note">{{ tr('adoptionHint') }}</p>
      <a-form layout="horizontal" :disabled="!editable || saving || loading" :label-col="{ flex: '180px' }" :wrapper-col="{ flex: 'auto' }">
        <a-form-item :label="tr('enabled')"><a-switch v-model:checked="draft.enabled" /></a-form-item>
        <a-form-item :label="tr('owner')"><a-radio-group v-model:value="draft.requirements.selection_mode" button-style="solid"><a-radio-button value="client">{{ tr('clientSelect') }}</a-radio-button><a-radio-button value="platform">{{ tr('platformSelect') }}</a-radio-button></a-radio-group><p class="field-note">{{ tr(draft.requirements.selection_mode === 'client' ? 'clientHint' : 'platformHint') }}</p></a-form-item>
        <a-form-item :label="tr('products')"><a-checkbox-group v-model:value="draft.requirements.products"><a-space wrap><a-checkbox v-for="product in products" :key="product.id" :value="product.id">{{ product.name }}</a-checkbox></a-space></a-checkbox-group></a-form-item>
      </a-form>
    </section>
    <section class="discovery">
      <header><div><h4>{{ tr('discovery') }}</h4><span class="muted">{{ state.reported_at ? tr('updated', { time: time(state.reported_at) }) : tr('notReported') }}</span></div><a-button type="link" :loading="discovering" :disabled="!editable || discovering || saving" @click="rediscover"><ReloadOutlined />{{ tr('rediscover') }}</a-button></header>
      <p v-if="pendingDiscovery" class="field-note" role="status">{{ tr('discoveryPending') }}</p>
      <a-table :data-source="state.items || []" :columns="columns" :pagination="false" row-key="id" :scroll="{ x: 580 }" size="middle">
        <template #emptyText>{{ tr('empty') }}</template>
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'product'"><span class="product-label"><span class="product-icon"><AgentProductLogo :product-id="record.product" /></span><strong>{{ productName(record.product) }}</strong></span></template>
          <template v-else-if="column.key === 'entry'">{{ tr(`entry.${record.entry}`) }}</template>
          <template v-else-if="column.key === 'availability'"><a-badge :status="record.availability === 'available' ? 'success' : 'warning'" :text="tr(`availability.${record.availability}`)" /></template>
          <template v-else-if="column.key === 'detail'"><a-button type="link" size="small" @click="selected = record">{{ tr('detail') }}<RightOutlined /></a-button></template>
        </template>
      </a-table>
    </section>
    <footer><p>{{ tr('saveHint') }}</p><a-button type="primary" :loading="saving" :disabled="!editable || saving || loading || !loaded || (draft.enabled && !draft.requirements.products.length)" @click="save">{{ tr('save') }}</a-button></footer>
    <details class="diagnostics"><summary>{{ tr('diagnostics') }}</summary><p>{{ t('aidr.enforcement.target') }}: {{ status.target_revision || '0' }} · {{ t('aidr.enforcement.applied') }}: {{ status.reported_revision || '—' }}</p><p v-for="path in state.configured_roots || []" :key="path"><code>{{ path }}</code></p><p v-if="status.health?.reason_code"><code>{{ status.health.reason_code }}</code></p></details>
    <a-drawer :open="!!selected" :title="selected ? productName(selected.product) : ''" width="min(520px, 94vw)" @close="selected = null">
      <template v-if="selected"><a-descriptions :column="1" layout="vertical"><a-descriptions-item :label="tr('path')"><code class="program-path">{{ selected.path }}</code></a-descriptions-item><a-descriptions-item :label="tr('source')">{{ tr(`sourceType.${selected.source}`) }}</a-descriptions-item><a-descriptions-item :label="tr('availabilityLabel')">{{ tr(`availability.${selected.availability}`) }}</a-descriptions-item><a-descriptions-item :label="tr('configuration')">{{ tr(state.configured_roots?.includes(selected.path) ? 'signed' : 'unselected') }}</a-descriptions-item></a-descriptions></template>
    </a-drawer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { ReloadOutlined, RightOutlined } from '@ant-design/icons-vue'
import { can } from '../access'
import AgentProductLogo from './AgentProductLogo.vue'
import { getEnforcement, saveSystemCollection, rediscoverSystemCollection } from '../api'
const props = defineProps({ clientId: { type: String, required: true } })
const { t, te, locale } = useI18n()
const tr = (key, values) => t(`systemSelection.${key}`, values || {})
const state = ref({}), status = ref({}), loading = ref(false), saving = ref(false), discovering = ref(false), loaded = ref(false), error = ref(''), selected = ref(null)
const draft = ref({ enabled: false, requirements: { selection_mode: 'client', products: ['codex', 'claude', 'workbuddy'] } })
let generation = 0, timer, baseVersion = '', requestedReport
const products = computed(() => [{ id: 'codex', name: 'Codex' }, { id: 'claude', name: 'Claude Code' }, { id: 'workbuddy', name: 'WorkBuddy' }, { id: 'custom', name: tr('custom') }])
const productName = id => products.value.find(p => p.id === id)?.name || id
const editable = computed(() => can('clients:update') && status.value.can_edit === true)
const columns = computed(() => [{ key: 'product', title: 'Agent' }, { key: 'entry', title: tr('installation') }, { key: 'availability', title: tr('availabilityLabel') }, { key: 'detail', title: '', width: 110 }])
const pendingDiscovery = computed(() => requestedReport !== undefined && state.value.reported_at === requestedReport)
const errorText = computed(() => te(`systemSelection.errors.${error.value.replaceAll('.', '_')}`) ? tr(`errors.${error.value.replaceAll('.', '_')}`) : tr('errorCode', { code: error.value }))
const time = value => new Date(value).toLocaleString(locale.value)
const failure = e => { error.value = e.response?.data?.error_code || 'request_failed' }
function applyDraft() { draft.value = { enabled: state.value.enabled, requirements: state.value.configured ? { ...state.value.requirements, products: [...state.value.requirements.products] } : { selection_mode: 'client', products: ['codex', 'claude', 'workbuddy'] } }; baseVersion = state.value.version }
async function load(reset = false) {
  if (loading.value || saving.value) return
  const g = generation; loading.value = true
  try {
    const [next, runtime] = await Promise.all([getEnforcement(props.clientId, 'collection'), getEnforcement(props.clientId, 'status')])
    if (g !== generation) return
    state.value = next; status.value = runtime
    if (!loaded.value || reset) applyDraft()
    loaded.value = true; error.value = ''
  } catch (e) { if (g === generation) failure(e) }
  finally { if (g === generation) loading.value = false }
}
async function save() {
  if (saving.value || !editable.value || !loaded.value) return
  const g = generation; saving.value = true; error.value = ''
  try {
    const next = await saveSystemCollection(props.clientId, { ...draft.value, expected_version: baseVersion })
    if (g === generation) { state.value = next; applyDraft(); message.success(tr('saved')) }
  } catch (e) { if (g === generation) failure(e) }
  finally { if (g === generation) saving.value = false }
}
async function rediscover() {
  if (discovering.value || !editable.value) return
  const g = generation, previousReport = state.value.reported_at; discovering.value = true
  try { const next = await rediscoverSystemCollection(props.clientId); if (g === generation) { requestedReport = previousReport; state.value = next } }
  catch (e) { if (g === generation) failure(e) }
  finally { if (g === generation) discovering.value = false }
}
watch(() => props.clientId, () => { generation++; loaded.value = false; loading.value = false; saving.value = false; discovering.value = false; state.value = {}; status.value = {}; selected.value = null; requestedReport = undefined; load() }, { immediate: true })
timer = setInterval(() => { if (!document.hidden) load() }, 10000)
onBeforeUnmount(() => { generation++; clearInterval(timer) })
</script>

<style scoped>
.system-selection { color: #25364b; min-width: 0; }
.product-label { display: flex; align-items: center; gap: 10px; }.product-icon { width: 24px; height: 24px; flex-shrink: 0; }
header, header > div, footer { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
header { justify-content: space-between; }
h4 { font-size: 15px; margin: 0; }
.runtime-state { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 12px 0 24px; color: #64748b; }
.runtime-state span:last-child { font-size: 12px; }
.requirements, .discovery { border: 1px solid #e4eaf2; border-radius: 8px; padding: 20px; margin: 18px 0; }
.requirements :deep(.ant-form-item:last-child) { margin-bottom: 0; }
.field-note { color: #718096; font-size: 12px; margin: 8px 0 0; }
.discovery { padding: 16px 16px 6px; }.discovery header { margin-bottom: 14px; }.muted { font-size: 12px; color: #718096; }
footer { justify-content: flex-end; }footer p { color: #718096; font-size: 12px; margin: 0; }
.diagnostics { margin-top: 24px; color: #718096; font-size: 12px; }.diagnostics summary { cursor: pointer; }.diagnostics code, .program-path { overflow-wrap: anywhere; }
.system-selection :deep(.ant-alert) { margin-bottom: 14px; }
@media(max-width: 650px) { .requirements, .discovery { padding: 14px; }.requirements :deep(.ant-form-item-row) { display: block; }.requirements :deep(.ant-form-item-label) { text-align: left; } footer { align-items: stretch; flex-direction: column; } .requirements :deep(.ant-radio-button-wrapper) { height: auto; white-space: normal; } }
</style>
