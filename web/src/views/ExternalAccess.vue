<template>
  <a-card class="external-access">
    <a-page-header :title="t('externalAccess.title')" :sub-title="t('externalAccess.subtitle')">
      <template #extra><a-button :loading="loading" @click="refresh(true)">{{ t('externalAccess.refresh') }}</a-button></template>
    </a-page-header>
    <p class="muted">{{ t('externalAccess.timezone') }}</p>
    <a-tabs v-model:activeKey="tab">
      <a-tab-pane key="partners" :tab="t('externalAccess.tabs.partners')">
        <div class="toolbar"><a-button v-if="can('external_access:create')" type="primary" @click="openPartner()">{{ t('externalAccess.createPartner') }}</a-button></div>
        <a-table :data-source="partners" :columns="partnerColumns" row-key="platform_id" :loading="loading" :scroll="{ x: 850 }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'enabled'"><a-tag :color="record.enabled ? 'green' : 'default'">{{ t(`externalAccess.${record.enabled ? 'enabled' : 'disabled'}`) }}</a-tag></template>
            <template v-else-if="column.key === 'departments'"><div v-for="d in record.departments" :key="d.department_id">{{ d.department_id }} → {{ groupName(d.group_id) }}</div></template>
            <template v-else-if="column.key === 'actions'"><a-button v-if="can('external_access:update')" type="link" @click="openPartner(record)">{{ t('externalAccess.edit') }}</a-button></template>
          </template>
        </a-table>
      </a-tab-pane>
      <a-tab-pane v-if="can('credentials:view')" key="tokens" :tab="t('externalAccess.tabs.tokens')">
        <p>{{ t('externalAccess.tokenHelp') }}</p>
        <p class="muted">{{ t('externalAccess.checkHelp') }}</p>
        <div class="toolbar">
          <a-select v-model:value="tokenPartner" allow-clear :placeholder="t('externalAccess.allPartners')" :options="partnerOptions" />
          <a-button v-if="can('credentials:create')" type="primary" @click="openToken()">{{ t('externalAccess.createToken') }}</a-button>
        </div>
        <a-table :data-source="visibleTokens" :columns="tokenColumns" row-key="id" :loading="loading" :scroll="{ x: 1300 }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'"><strong>{{ record.name }}</strong><div class="muted">#{{ record.id }} · {{ record.token_prefix }}</div></template>
            <template v-else-if="column.key === 'platform_id'">{{ partnerName(record.platform_id) }}<div class="muted">{{ record.platform_id }}</div></template>
            <template v-else-if="column.key === 'departments'"><a-tag v-for="id in record.allowed_department_ids" :key="id">{{ id }}</a-tag></template>
            <template v-else-if="column.key === 'scopes'"><div v-for="scope in record.scopes" :key="scope">{{ t(`externalAccess.scopeNames.${scope}`) }}</div></template>
            <template v-else-if="column.key === 'status'"><a-tag :color="tokenStatus(record) === 'active' ? 'green' : 'default'">{{ t(`externalAccess.${tokenStatus(record)}`) }}</a-tag></template>
            <template v-else-if="column.key === 'expires_at'">{{ record.expires_at ? formatTime(record.expires_at) : t('externalAccess.noExpiry') }}</template>
            <template v-else-if="column.key === 'last_used_at'">{{ record.last_used_at ? formatTime(record.last_used_at) : t('externalAccess.neverUsed') }}</template>
            <template v-else-if="column.key === 'actions'">
              <a-space wrap>
                <a-button v-if="can('credentials:update') && record.status !== 'revoked'" type="link" @click="openToken(record)">{{ t('externalAccess.edit') }}</a-button>
                <a-button v-if="can('credentials:update') && record.status !== 'revoked'" type="link" :loading="busyToken === record.id" :disabled="busyToken !== null" @click="changeToken(record)">{{ t(`externalAccess.${record.status === 'active' ? 'disable' : 'enable'}`) }}</a-button>
                <a-popconfirm v-if="can('credentials:update') && record.status !== 'revoked'" :title="t('externalAccess.revokeConfirm')" @confirm="changeToken(record, true)"><a-button type="link" danger :disabled="busyToken !== null">{{ t('externalAccess.revoke') }}</a-button></a-popconfirm>
                <a-button type="link" @click="showTokenRequests(record)">{{ t('externalAccess.requests') }}</a-button>
              </a-space>
            </template>
          </template>
        </a-table>
      </a-tab-pane>
      <a-tab-pane key="profiles" :tab="t('openapiProfiles.title')">
        <OpenapiProfiles v-if="tab === 'profiles'" :partners="partners" />
      </a-tab-pane>
      <a-tab-pane key="callbacks" :tab="t('externalCallbacks.title')">
        <ExternalReceiverConfigs v-if="tab === 'callbacks'" :partners="partners" kind="callback" />
      </a-tab-pane>
      <a-tab-pane key="gateways" :tab="t('externalGateways.title')">
        <ExternalReceiverConfigs v-if="tab === 'gateways'" :partners="partners" kind="gateway" />
      </a-tab-pane>
      <a-tab-pane key="requests" :tab="t('externalAccess.tabs.requests')">
        <a-radio-group v-model:value="recordType" button-style="solid" class="record-type">
          <a-radio-button value="inbound">{{ t('externalDelivery.inbound') }}</a-radio-button>
          <a-radio-button value="outbound">{{ t('externalDelivery.outbound') }}</a-radio-button>
        </a-radio-group>
        <ExternalDeliveries v-if="tab === 'requests' && recordType === 'outbound'" :partners="partners" />
        <template v-else>
        <p class="muted">{{ t('externalAccess.recordsHelp') }}</p>
        <div class="toolbar">
          <a-select v-model:value="filters.platform_id" allow-clear :placeholder="t('externalAccess.allPartners')" :options="partnerOptions" />
          <a-input v-model:value="filters.request_id" :placeholder="t('externalAccess.requestId')" @pressEnter="search" />
          <a-input-number v-model:value="filters.token_id" :min="1" :precision="0" :placeholder="t('externalAccess.tokenId')" />
          <a-input v-model:value="filters.resource_id" :placeholder="t('externalAccess.resourceId')" @pressEnter="search" />
          <a-input v-model:value="filters.business_request_id" :placeholder="t('externalAccess.businessRequestId')" @pressEnter="search" />
          <a-input v-model:value="filters.route" :placeholder="t('externalAccess.route')" @pressEnter="search" />
          <a-select v-model:value="filters.outcome" allow-clear :placeholder="t('externalAccess.allResults')" :options="outcomeOptions" />
          <a-range-picker v-model:value="dates" show-time :placeholder="[t('externalAccess.filterDates.0'), t('externalAccess.filterDates.1')]" class="dates" />
          <a-button type="primary" :loading="recordsLoading" @click="search">{{ t('externalAccess.search') }}</a-button>
          <a-button @click="resetSearch">{{ t('externalAccess.reset') }}</a-button>
        </div>
        <a-table :data-source="records" :columns="requestColumns" row-key="request_id" :loading="recordsLoading" :pagination="pagination" :scroll="{ x: 1350 }" @change="changePage">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'created_at'">{{ formatTime(record.created_at) }}</template>
            <template v-else-if="column.key === 'request_id'"><a class="request-id" @click="selected = record">{{ record.client_request_id || record.request_id }}</a></template>
            <template v-else-if="column.key === 'platform_id'">{{ record.platform_name || record.platform_id || t('externalAccess.unknownPartner') }}<div class="muted">{{ record.token_name }}<span v-if="record.token_id"> · #{{ record.token_id }}</span></div></template>
            <template v-else-if="column.key === 'route'"><code>{{ record.method }}</code> {{ record.route || t('externalAccess.unmatchedRoute') }}</template>
            <template v-else-if="column.key === 'status_code'"><a-tag :color="record.status_code == null ? 'default' : record.status_code < 400 ? 'green' : 'red'">{{ record.status_code ?? t('externalAccess.pending') }}</a-tag><div v-if="record.error_code" class="muted">{{ requestError(record) }}</div></template>
            <template v-else-if="column.key === 'duration_ms'">{{ record.duration_ms == null ? '—' : t('externalAccess.ms', { value: record.duration_ms }) }}</template>
          </template>
        </a-table>
        </template>
      </a-tab-pane>
    </a-tabs>

    <a-modal v-model:open="partnerOpen" :title="t(partnerEditing ? 'externalAccess.edit' : 'externalAccess.createPartner')" :confirm-loading="saving" :ok-button-props="{ disabled: saving }" :cancel-button-props="{ disabled: saving }" :closable="!saving" :mask-closable="false" :ok-text="t('externalAccess.save')" @ok="savePartner">
      <a-form layout="vertical">
        <a-form-item :label="t('externalAccess.platformId')" required :extra="t('externalAccess.platformHint')"><a-input v-model:value="partnerForm.platform_id" :disabled="partnerEditing" :maxlength="64" /></a-form-item>
        <a-form-item :label="t('externalAccess.platformName')" required><a-input v-model:value="partnerForm.name" :maxlength="128" /></a-form-item>
        <a-form-item :label="t('externalAccess.enabled')"><a-switch v-model:checked="partnerForm.enabled" /></a-form-item>
        <a-form-item :label="t('externalAccess.mapping')" :extra="t('externalAccess.mappingHint')">
          <div v-for="(d, index) in partnerForm.departments" :key="index" class="department-row">
            <a-input v-model:value="d.department_id" :maxlength="64" :placeholder="t('externalAccess.departmentId')" />
            <a-select v-model:value="d.group_id" :options="groupOptions" :placeholder="t('externalAccess.group')" />
            <a-button @click="partnerForm.departments.splice(index, 1)">{{ t('externalAccess.remove') }}</a-button>
          </div>
          <a-button @click="partnerForm.departments.push({ department_id: '', group_id: undefined })">{{ t('externalAccess.addDepartment') }}</a-button>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="tokenOpen" :title="t(tokenEditing ? 'externalAccess.edit' : 'externalAccess.createToken')" :confirm-loading="saving" :ok-button-props="{ disabled: saving }" :cancel-button-props="{ disabled: saving }" :closable="!saving" :mask-closable="false" :ok-text="t('externalAccess.save')" @ok="saveToken">
      <a-form layout="vertical">
        <a-form-item :label="t('externalAccess.tokenName')" required><a-input v-model:value="tokenForm.name" :maxlength="128" /></a-form-item>
        <a-form-item :label="t('externalAccess.partners')" required><a-select v-model:value="tokenForm.platform_id" :disabled="!!tokenEditing" :options="enabledPartnerOptions" @change="tokenForm.allowed_department_ids = []" /></a-form-item>
        <a-form-item :label="t('externalAccess.departments')" required><a-select v-model:value="tokenForm.allowed_department_ids" mode="multiple" :options="departmentOptions" /></a-form-item>
        <a-form-item :label="t('externalAccess.scopes')" required :extra="t('externalAccess.scopesHelp')"><a-checkbox-group v-model:value="tokenForm.scopes" class="scope-options"><a-checkbox v-for="scope in options.scopes" :key="scope" :value="scope">{{ t(`externalAccess.scopeNames.${scope}`) }}</a-checkbox></a-checkbox-group></a-form-item>
        <a-form-item :label="t('externalAccess.expiry')" :extra="t('externalAccess.expiryHelp')"><a-date-picker v-model:value="tokenForm.expires_at" show-time style="width: 100%" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal :open="!!plaintext" :title="t('externalAccess.tokenOnce')" :footer="null" :mask-closable="false" @cancel="plaintext = ''">
      <a-alert type="info" show-icon :message="t('externalAccess.tokenOnceHint')" />
      <pre class="token-value">{{ plaintext }}</pre>
      <a-space><a-button type="primary" @click="copyToken">{{ t('externalAccess.copy') }}</a-button><a-button @click="plaintext = ''">{{ t('externalAccess.close') }}</a-button></a-space>
    </a-modal>

    <a-drawer :open="!!selected" :title="t('externalAccess.requestDetail')" width="min(620px, 100vw)" @close="selected = null">
      <a-descriptions v-if="selected" :column="1" bordered size="small">
        <a-descriptions-item v-for="item in detailFields" :key="item.key" :label="t(`externalAccess.${item.label}`)">{{ item.value ?? '—' }}</a-descriptions-item>
        <a-descriptions-item v-if="selected.resource_id" :label="t('externalAccess.resource')"><router-link v-if="resourceLink" :to="resourceLink">{{ selected.resource_id }}</router-link><span v-else>{{ selected.resource_id }}</span></a-descriptions-item>
      </a-descriptions>
    </a-drawer>
  </a-card>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import { can, pageAllowed } from '../access'
import { formatBeijingDateTime as formatTime } from '../utils/format'
import { copyText } from '../utils/clipboard'
import ExternalDeliveries from '../components/ExternalDeliveries.vue'
import OpenapiProfiles from '../components/OpenapiProfiles.vue'
import ExternalReceiverConfigs from '../components/ExternalReceiverConfigs.vue'
import { externalAccessOptions, listExternalPlatforms, createExternalPlatform, updateExternalPlatform, listExternalRequests,
  listAccessTokens, createAccessToken, updateAccessToken, revokeAccessToken } from '../api'

const { t, te } = useI18n()
const route = useRoute()
const router = useRouter()
const tab = ref(route.query.request_id ? 'requests' : route.query.tab || 'partners')
const recordType = ref('inbound')
const partners = ref([]), tokens = ref([]), records = ref([]), options = ref({ groups: [], scopes: [] })
const loading = ref(false), recordsLoading = ref(false), saving = ref(false), busyToken = ref(null)
const partnerOpen = ref(false), tokenOpen = ref(false), partnerEditing = ref(false), tokenEditing = ref(null), plaintext = ref(''), selected = ref(null)
const partnerForm = reactive({ platform_id: '', name: '', enabled: true, departments: [] })
const tokenForm = reactive({ name: '', platform_id: undefined, allowed_department_ids: [], scopes: [], expires_at: null })
const tokenPartner = ref(undefined), dates = ref(null)
const filters = reactive({ platform_id: undefined, request_id: route.query.request_id || '', token_id: undefined, resource_id: '', business_request_id: '', route: '', outcome: undefined })
const pagination = reactive({ current: 1, pageSize: 20, total: 0, showSizeChanger: true })
let recordSequence = 0
const groupName = id => options.value.groups.find(g => g.id === id)?.name || String(id)
const partnerName = id => partners.value.find(p => p.platform_id === id)?.name || id
const partnerOptions = computed(() => partners.value.map(p => ({ value: p.platform_id, label: `${p.name} (${p.platform_id})` })))
const enabledPartnerOptions = computed(() => partnerOptions.value.filter(o => partners.value.find(p => p.platform_id === o.value)?.enabled || o.value === tokenForm.platform_id))
const groupOptions = computed(() => options.value.groups.map(g => ({ value: g.id, label: g.name })))
const departmentOptions = computed(() => (partners.value.find(p => p.platform_id === tokenForm.platform_id)?.departments || []).map(d => ({ value: d.department_id, label: `${d.department_id} · ${groupName(d.group_id)}` })))
const visibleTokens = computed(() => tokens.value.filter(row => !tokenPartner.value || row.platform_id === tokenPartner.value))
const outcomeOptions = computed(() => [['success', 'success'], ['failed', 'failedRequest'], ['pending', 'pending']].map(([value, key]) => ({ value, label: t(`externalAccess.${key}`) })))
const columns = specs => specs.map(([key, label, width]) => ({ key, dataIndex: key, title: t(`externalAccess.${label || key}`), width }))
const partnerColumns = computed(() => columns([['platform_id', 'platformId', 180], ['name', 'platformName', 200], ['departments', 'mapping', 260], ['enabled', 'status', 120], ['actions', 'actions', 100]]))
const tokenColumns = computed(() => columns([['name', 'tokenName', 160], ['platform_id', 'partners', 180], ['departments', 'departments', 160], ['scopes', 'scopes', 220], ['status', 'status', 110], ['expires_at', 'expiry', 175], ['last_used_at', 'lastUsed', 175], ['actions', 'actions', 210]]))
const requestColumns = computed(() => columns([['created_at', 'createdAt', 175], ['request_id', 'requestId', 290], ['platform_id', 'partners', 180], ['route', 'route', 300], ['status_code', 'httpStatus', 180], ['duration_ms', 'duration', 110], ['source_ip', 'sourceIp', 150]]))
const parseDate = value => dayjs(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
const dateFilter = value => value ? `${value.format('YYYY-MM-DDTHH:mm:ss.SSS')}+08:00` : undefined
const tokenStatus = row => row.status === 'active' && row.expires_at && parseDate(row.expires_at).isBefore(dayjs()) ? 'expired' : row.status
const fail = error => message.error(error?.response?.data?.detail || t('externalAccess.failed'))
const requestError = row => te(`externalAccess.skillErrors.${row.error_code}`) ? t(`externalAccess.skillErrors.${row.error_code}`) : te(`externalAccess.requestErrors['${row.error_code}']`) ? t(`externalAccess.requestErrors['${row.error_code}']`) : t('externalAccess.failedRequest')
const detailFields = computed(() => {
  const r = selected.value || {}
  return [['request_id', 'requestId'], ['platform_name', 'platformName'], ['platform_id', 'platformId'], ['token_id', 'tokenId'], ['token_name', 'tokenName'], ['token_prefix', 'prefix'], ['department_id', 'departmentId'], ['method', 'method'], ['route', 'route'], ['source_ip', 'sourceIp'], ['status_code', 'httpStatus'], ['error_code', 'errorCode']].map(([key, label]) => ({ key, label, value: r[key] })).concat([
    { key: 'client_request_id', label: 'clientRequestId', value: r.client_request_id },
    { key: 'created_at', label: 'createdAt', value: formatTime(r.created_at) },
    { key: 'duration_ms', label: 'duration', value: r.duration_ms == null ? null : t('externalAccess.ms', { value: r.duration_ms }) },
    { key: 'error_reason', label: 'errorReason', value: r.error_code ? requestError(r) : null },
    { key: 'business_request_id', label: 'businessRequestId', value: r.business_request_id },
  ])
})
const resourceLink = computed(() => {
  const r = selected.value
  if (!r) return null
  if (r.resource_type === 'agent' && pageAllowed('/agents')) return { path: '/agents', query: { q: r.resource_id } }
  if (r.resource_type === 'skill' && pageAllowed('/skills')) return `/skills/${encodeURIComponent(r.resource_id)}`
  if (r.resource_type === 'evaluation' && pageAllowed('/agent-security/scans')) return { path: '/agent-security/scans', query: { task_id: r.resource_id } }
  return null
})

const sharedPending = new Map()
const sharedLoaded = new Set()
let refreshSequence = 0
function loadShared(force) {
  const resources = [['partners', listExternalPlatforms]]
  if (['partners', 'tokens'].includes(tab.value)) resources.push(['options', externalAccessOptions])
  return Promise.all(resources.map(([key, request]) => {
    if (sharedPending.has(key)) return sharedPending.get(key)
    if (sharedLoaded.has(key) && !force) return Promise.resolve()
    const pending = request().then(result => {
      if (key === 'partners') partners.value = result.items
      else options.value = result
      sharedLoaded.add(key)
    }).finally(() => { sharedPending.delete(key) })
    sharedPending.set(key, pending)
    return pending
  }))
}
async function refresh(force = false) {
  const sequence = ++refreshSequence
  const currentTab = tab.value
  loading.value = true
  try {
    await Promise.all([
      loadShared(force),
      currentTab === 'tokens' && can('credentials:view') ? listAccessTokens({ token_type: 'openapi' }).then(result => {
        if (sequence === refreshSequence) tokens.value = result.items
      }) : null,
      currentTab === 'requests' && recordType.value === 'inbound' ? loadRecords() : null,
    ])
  } catch (error) { if (sequence === refreshSequence) fail(error) }
  finally { if (sequence === refreshSequence) loading.value = false }
}
async function loadRecords() {
  const sequence = ++recordSequence
  recordsLoading.value = true
  try {
    const result = await listExternalRequests({ ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v != null && v !== '')),
      started_at: dateFilter(dates.value?.[0]), ended_at: dateFilter(dates.value?.[1]), page: pagination.current, page_size: pagination.pageSize })
    if (sequence !== recordSequence) return
    records.value = result.items; pagination.total = result.total
  } catch (error) { if (sequence === recordSequence) fail(error) } finally { if (sequence === recordSequence) recordsLoading.value = false }
}
function search() { pagination.current = 1; loadRecords() }
function resetSearch() { resetFilters(); search() }
function changePage(page) { pagination.current = page.current; pagination.pageSize = page.pageSize; loadRecords() }
function showTokenRequests(row) { recordType.value = 'inbound'; resetFilters(); filters.token_id = row.id; pagination.current = 1; tab.value = 'requests' }
function resetFilters() { Object.assign(filters, { platform_id: undefined, request_id: '', token_id: undefined, resource_id: '', business_request_id: '', route: '', outcome: undefined }); dates.value = null }
function openPartner(row) {
  partnerEditing.value = !!row
  Object.assign(partnerForm, row ? { ...row, departments: row.departments.map(d => ({ ...d })) } : { platform_id: '', name: '', enabled: true, departments: [] })
  partnerOpen.value = true
}
async function savePartner() {
  if (saving.value) return
  if (!partnerForm.name.trim() || !partnerForm.platform_id || partnerForm.departments.some(d => !d.department_id || !d.group_id)) return message.error(t('externalAccess.required'))
  if (![partnerForm.platform_id, ...partnerForm.departments.map(d => d.department_id)].every(v => /^[A-Za-z0-9_.-]+$/.test(v))) return message.error(t('externalAccess.invalidCode'))
  if (new Set(partnerForm.departments.map(d => d.department_id)).size !== partnerForm.departments.length) return message.error(t('externalAccess.duplicateDepartment'))
  saving.value = true
  try {
    const body = { name: partnerForm.name.trim(), enabled: partnerForm.enabled, departments: partnerForm.departments.map(d => ({ ...d })) }
    if (partnerEditing.value) await updateExternalPlatform(partnerForm.platform_id, body)
    else await createExternalPlatform({ ...body, platform_id: partnerForm.platform_id })
    partnerOpen.value = false; message.success(t('externalAccess.saved')); await refresh(true)
  } catch (error) { fail(error) } finally { saving.value = false }
}
function openToken(row) {
  tokenEditing.value = row?.id || null
  Object.assign(tokenForm, row ? { name: row.name, platform_id: row.platform_id, allowed_department_ids: [...row.allowed_department_ids], scopes: [...row.scopes], expires_at: row.expires_at ? dayjs(parseDate(row.expires_at).tz('Asia/Shanghai').format('YYYY-MM-DDTHH:mm:ss')) : null } : { name: '', platform_id: tokenPartner.value, allowed_department_ids: [], scopes: [], expires_at: null })
  tokenOpen.value = true
}
async function saveToken() {
  if (saving.value) return
  if (!tokenForm.name.trim() || !tokenForm.platform_id) return message.error(t('externalAccess.required'))
  if (!tokenForm.allowed_department_ids.length) return message.error(t('externalAccess.selectDepartments'))
  if (!tokenForm.scopes.length) return message.error(t('externalAccess.selectScopes'))
  saving.value = true
  try {
    const body = { name: tokenForm.name.trim(), allowed_department_ids: [...tokenForm.allowed_department_ids], scopes: [...tokenForm.scopes], expires_at: dateFilter(tokenForm.expires_at) || null }
    if (tokenEditing.value) await updateAccessToken(tokenEditing.value, body)
    else plaintext.value = (await createAccessToken({ ...body, token_type: 'openapi', platform_id: tokenForm.platform_id })).token
    tokenOpen.value = false; await refresh()
  } catch (error) { fail(error) } finally { saving.value = false }
}
async function changeToken(row, revoke = false) {
  if (busyToken.value !== null) return
  busyToken.value = row.id
  try { if (revoke) await revokeAccessToken(row.id); else await updateAccessToken(row.id, { status: row.status === 'active' ? 'disabled' : 'active' }); await refresh() }
  catch (error) { fail(error) } finally { busyToken.value = null }
}
async function copyToken() { try { await copyText(plaintext.value); message.success(t('externalAccess.copied')) } catch { message.error(t('externalAccess.copyFailed')) } }
watch(() => route.query.edit_token, value => { if (value) tab.value = 'tokens' }, { immediate: true })
watch([() => route.query.edit_token, tokens, loading], () => {
  if (!route.query.edit_token || loading.value || !can('credentials:update')) return
  const row = tokens.value.find(item => String(item.id) === route.query.edit_token)
  if (!row || row.status === 'revoked') return
  openToken(row)
  const query = { ...route.query }; delete query.edit_token
  void router.replace({ query })
})
watch(() => route.query.request_id, value => { if (value) {
  const alreadyInbound = tab.value === 'requests' && recordType.value === 'inbound'
  recordType.value = 'inbound'; resetFilters(); filters.request_id = String(value); pagination.current = 1; tab.value = 'requests'
  if (alreadyInbound) search()
} })
watch([tab, recordType], () => { recordSequence++; recordsLoading.value = false; refresh() }, { immediate: true })
onBeforeUnmount(() => { refreshSequence++; recordSequence++; plaintext.value = '' })
</script>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.record-type { margin: 8px 0 16px; }
.toolbar > .ant-select, .toolbar > .ant-input, .toolbar > .ant-input-number { width: 220px; }
.toolbar .dates { width: 410px; }
.muted { color: #6b7280; font-size: 12px; overflow-wrap: anywhere; }
.request-id { overflow-wrap: anywhere; }
.department-row { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.department-row > .ant-input, .department-row > .ant-select { flex: 1; min-width: 150px; }
.scope-options { display: flex; flex-direction: column; gap: 10px; }
.token-value { margin: 18px 0; padding: 12px; background: #f5f6f8; white-space: pre-wrap; overflow-wrap: anywhere; user-select: all; }
:deep(.ant-descriptions-item-content) { overflow-wrap: anywhere; }
@media (max-width: 600px) { .toolbar > .ant-select, .toolbar > .ant-input, .toolbar > .ant-input-number, .toolbar .dates { width: 100%; } }
</style>
