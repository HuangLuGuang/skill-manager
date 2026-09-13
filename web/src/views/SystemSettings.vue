<template>
  <div class="system-overview">
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.11x0ooc')" :sub-title="$t('legacy.1572cr1')" />
      </template>

    <BrandingSettings />

    <section class="health-panel">
      <div class="health-main">
        <div>
          <div class="eyebrow">{{ $t("legacy.1fr4rat") }}</div>
          <div class="health-title">{{ $t("legacy.16kfg6f") }}</div>
          <div class="health-summary">
            <a-tag :color="statusColor(overallHealth.status)">{{ overallHealth.text }}</a-tag>
            <span>{{ overallHealth.message }}</span>
          </div>
        </div>
        <div class="group-status-list">
          <div v-for="group in capabilityGroups" :key="group.key" class="group-status-pill">
            <span>{{ group.title }}</span>
            <a-tag :color="statusColor(group.status)">{{ statusText(group.status) }}</a-tag>
          </div>
        </div>
      </div>
      <a-button type="primary" size="small" :loading="loading" @click="fetchStatus">{{ $t("legacy.2fhcc7") }}</a-button>
    </section>

    <section v-for="group in capabilityGroups" :key="group.key" class="capability-section">
      <div class="section-heading">
        <div>
          <div class="section-title">{{ group.title }}</div>
          <div class="section-subtitle">{{ group.description }}</div>
        </div>
        <a-tag :color="statusColor(group.status)">{{ statusText(group.status) }}</a-tag>
      </div>

      <div class="capability-list">
        <div v-for="item in group.items" :key="item.key" class="capability-row">
          <div class="capability-status" :class="`status-${item.status}`" />
          <div class="capability-main">
            <div class="capability-title">{{ item.title }}</div>
            <div class="capability-desc">{{ item.description }}</div>
          </div>
          <div class="meta-list">
            <template v-if="item.meta?.length">
              <div v-for="meta in item.meta" :key="meta.label" class="meta-line">
                <span class="meta-label">{{ meta.label }}：</span>
                <span class="meta-value">{{ meta.value || '-' }}</span>
              </div>
            </template>
            <span v-else class="meta-empty">-</span>
          </div>
          <div class="capability-state">
            <a-tag :color="statusColor(item.status)">{{ item.statusText || statusText(item.status) }}</a-tag>
          </div>
          <div class="capability-action">
            <router-link v-if="item.actionPath && pageAllowed(item.actionPath)" :to="item.actionPath">
              <a-button size="small">{{ item.actionText }}</a-button>
            </router-link>
            <span v-else class="meta-empty">-</span>
          </div>
        </div>
      </div>
    </section>

    <section class="recommendation-panel">
      <div class="section-heading">
        <div>
          <div class="section-title">{{ $t("legacy.g2l9ma") }}</div>
          <div class="section-subtitle">{{ $t("legacy.obze9o") }}</div>
        </div>
      </div>
      <a-empty v-if="!recommendations.length" :description="$t('legacy.11evyev')" />
      <div v-else class="recommendation-list">
        <div v-for="item in recommendations" :key="item.title" class="recommendation-row">
          <div class="recommendation-main">
            <div class="recommendation-title">{{ item.title }}</div>
            <div class="recommendation-desc">{{ item.description }}</div>
          </div>
          <div class="recommendation-action">
            <router-link v-if="item.actionPath && pageAllowed(item.actionPath)" :to="item.actionPath">
              <a-button size="small">{{ item.actionText }}</a-button>
            </router-link>
          </div>
        </div>
      </div>
    </section>

    </a-card>

  </div>
</template>

<script setup>
import { modelLabel } from '../utils/modelLabels'
import BrandingSettings from '../components/BrandingSettings.vue'
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useI18n } from 'vue-i18n'
import { can, pageAllowed } from '../access'

import {
  getAgentManagerSystemStatus,
  getLlmConfig,
  getSandboxConfig,
  listAccessTokens,
  listModelEndpoints,
  listModelProviders,
  listPrivacyPolicies,
} from '../api'

const loading = ref(false)
const { t } = useI18n()
const sourceStatus = ref({})
const managerStatus = ref({})
const llmConfig = ref({})
const sandboxConfig = ref({})
const modelProviders = ref([])
const modelEndpoints = ref([])
const accessTokens = ref([])
const privacyPolicies = ref([])

const loadSource = async (key, permission, request, fallback) => {
  if (!can(permission)) {
    sourceStatus.value[key] = 'restricted'
    return fallback
  }
  try {
    const result = await request()
    sourceStatus.value[key] = 'ready'
    return result
  } catch (error) {
    sourceStatus.value[key] = 'unavailable'
    return fallback
  }
}

const capabilitySources = {
  api: ['manager'], signing: ['manager'], sandbox: ['manager', 'sandbox'],
  llm: ['manager', 'llm'], 'deep-analysis': ['manager'],
  models: ['providers', 'models'], credentials: ['tokens'], privacy: ['policies'],
  'runtime-token': ['tokens'], 'runtime-check': ['manager'], scanner: ['tokens'],
}
const withSourceStatus = item => {
  const states = (capabilitySources[item.key] || []).map(key => sourceStatus.value[key])
  if (states.some(status => status !== 'ready')) {
    const statusText = t(states.includes('restricted') ? 'iam.dataRestricted' : 'iam.dataUnavailable')
    return { ...item, status: 'unknown', meta: [], statusText, description: statusText }
  }
  return item
}

const toArray = (value) => {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.items)) return value.items
  return []
}

const statusText = (status) => ({
  ok: phrase('legacy.tt5vxa'),
  warning: phrase('legacy.1v15qsb'),
  error: phrase('legacy.1uz4mvb'),
  disabled: phrase('legacy.1tylsuy'),
  unknown: phrase('legacy.1w2inwf'),
}[status] || phrase('legacy.1w2inwf'))

const statusColor = (status) => ({
  ok: 'green',
  warning: 'orange',
  error: 'red',
  disabled: 'default',
  unknown: 'default',
}[status] || 'default')

const groupStatus = (items) => {
  const statuses = items.map((item) => item.status)
  if (statuses.includes('error')) return 'error'
  if (statuses.includes('warning')) return 'warning'
  if (statuses.every((status) => status === 'disabled')) return 'disabled'
  if (statuses.includes('unknown')) return 'unknown'
  return 'ok'
}

const activeModels = computed(() => modelEndpoints.value.filter((item) => item.enabled !== false))
const activeAccessTokens = computed(() => accessTokens.value.filter((item) => item.status === 'active'))
const agentRuntimeTokens = computed(() =>
  activeAccessTokens.value.filter((item) => item.token_type === 'agent_runtime'),
)
const scannerTokens = computed(() =>
  activeAccessTokens.value.filter((item) => item.token_type === 'scanner'),
)
const gatewayTokens = computed(() =>
  activeAccessTokens.value.filter((item) => item.token_type === 'model_gateway'),
)
const boundAgentTokenCount = computed(() =>
  new Set(agentRuntimeTokens.value.map((item) => item.bound_agent_id).filter(Boolean)).size,
)

const sandboxEnabled = computed(() => managerStatus.value.sandbox_enabled ?? sandboxConfig.value.enabled ?? false)
const sandboxRuntime = computed(() => managerStatus.value.sandbox_runtime || sandboxConfig.value.runtime || 'remote')
const sandboxTargetValue = computed(() => {
  if (managerStatus.value.sandbox_target) return managerStatus.value.sandbox_target
  if (sandboxRuntime.value === 'remote') return sandboxConfig.value.remote_url || 'http://sandbox:8194'
  return sandboxConfig.value.image || '-'
})
const sandboxItemStatus = computed(() => {
  if (!sandboxEnabled.value) return 'disabled'
  return managerStatus.value.sandbox_available ? 'ok' : 'error'
})
const llmItemStatus = computed(() => {
  if (!managerStatus.value.llm_enabled) return 'disabled'
  return managerStatus.value.llm_model ? 'ok' : 'warning'
})
const llmSource = computed(() =>
  (managerStatus.value.llm_provider || llmConfig.value.provider) === 'model-gateway'
    ? phrase('legacy.15en1a5')
    : (managerStatus.value.llm_provider || llmConfig.value.provider || '-'),
)

const coreItems = computed(() => [
  {
    key: 'api',
    title: phrase('legacy.tesmjn'),
    status: 'ok',
    statusText: phrase('legacy.1dd5rmv'),
    description: phrase('legacy.ua02qd'),
  },
  {
    key: 'signing',
    title: phrase('legacy.f8hw35'),
    status: managerStatus.value.signing_key_configured ? 'ok' : 'warning',
    statusText: managerStatus.value.signing_key_configured ? phrase('legacy.oe97li') : phrase('legacy.i0qje'),
    description: managerStatus.value.signing_key_configured
      ? phrase('legacy.ufoev8')
      : phrase('legacy.hibd5j'),
    actionText: phrase('legacy.1ydn1ts'),
    actionPath: '/policy',
  },
  {
    key: 'audit',
    title: phrase('legacy.179jrgz'),
    status: 'ok',
    statusText: phrase('legacy.18ety4i'),
    description: phrase('legacy.i26te7'),
    actionText: phrase('legacy.c63dvn'),
    actionPath: '/audit',
  },
])

const analysisItems = computed(() => [
  {
    key: 'sandbox',
    title: 'Sandbox',
    status: sandboxItemStatus.value,
    statusText: sandboxEnabled.value
      ? (managerStatus.value.sandbox_available ? phrase('legacy.18ety4i') : phrase('legacy.vub0qv'))
      : phrase('legacy.1tylsuy'),
    description: managerStatus.value.sandbox_status_message || phrase('legacy.1pluc6n'),
    meta: [
      { label: phrase('legacy.m51d96'), value: sandboxRuntime.value },
      { label: phrase('legacy.1xibtz6'), value: sandboxTargetValue.value },
    ],
    actionText: phrase('legacy.1mrz32b'),
    actionPath: '/policy',
  },
  {
    key: 'llm',
    title: phrase('legacy.ka9ulq'),
    status: llmItemStatus.value,
    statusText: managerStatus.value.llm_enabled ? phrase('legacy.1w2s4cy') : phrase('legacy.1tylsuy'),
    description: managerStatus.value.llm_enabled
      ? phrase('legacy.1f6jve4')
      : phrase('legacy.50t2b9'),
    meta: [
      { label: phrase('legacy.1ow6qt'), value: modelLabel(modelEndpoints.value.find(model => model.name === (managerStatus.value.llm_model || llmConfig.value.model))) || managerStatus.value.llm_model || llmConfig.value.model || '-' },
      { label: phrase('legacy.2tds9c'), value: llmSource.value },
    ],
    actionText: phrase('legacy.13jl62z'),
    actionPath: '/policy',
  },
  {
    key: 'deep-analysis',
    title: phrase('legacy.e67rtk'),
    status: managerStatus.value.skillspector_available ? 'ok' : 'warning',
    statusText: managerStatus.value.skillspector_available ? phrase('legacy.18ety4i') : phrase('legacy.buf4kb'),
    description: phrase('legacy.1ov25l9'),
    actionText: phrase('legacy.knj41c'),
    actionPath: '/submit',
  },
])

const gatewayItems = computed(() => [
  {
    key: 'models',
    title: phrase('legacy.1berpj2'),
    status: activeModels.value.length > 0 ? 'ok' : 'error',
    statusText: activeModels.value.length > 0 ? phrase('legacy.ir2zun') : phrase('legacy.19yuxkw'),
    description: phrase('legacy.1e4t529'),
    meta: [
      { label: phrase('legacy.1x7qpl0'), value: `${modelProviders.value.length}` },
      { label: phrase('legacy.103n846'), value: `${activeModels.value.length}` },
    ],
    actionText: phrase('legacy.h6olrl'),
    actionPath: '/model-gateway/providers',
  },
  {
    key: 'credentials',
    title: phrase('legacy.9ooix4'),
    status: activeAccessTokens.value.length > 0 ? 'ok' : 'warning',
    statusText: activeAccessTokens.value.length > 0 ? phrase('legacy.18ety4i') : phrase('legacy.7mgyvl'),
    description: phrase('legacy.1rh3475'),
    meta: [
      { label: phrase('legacy.jv7f4r'), value: `${gatewayTokens.value.length}` },
      { label: phrase('legacy.pfgf5p'), value: `${agentRuntimeTokens.value.filter(item => item.scopes?.includes('model:chat')).length}` },
    ],
    actionText: phrase('legacy.y9va7n'),
    actionPath: '/credentials',
  },
  {
    key: 'privacy',
    title: phrase('legacy.jt33j7'),
    status: privacyPolicies.value.length > 0 ? 'ok' : 'warning',
    statusText: privacyPolicies.value.length > 0 ? phrase('legacy.1pxgbde') : phrase('legacy.1v15qsb'),
    description: phrase('legacy.wa8e0d'),
    meta: [
      { label: phrase('legacy.17licqk'), value: `${privacyPolicies.value.length}` },
    ],
    actionText: phrase('legacy.1mv69vw'),
    actionPath: '/model-gateway/policies',
  },
  {
    key: 'prompt-guard',
    title: phrase('legacy.1yae1mb'),
    status: 'ok',
    statusText: phrase('legacy.18ety4i'),
    description: phrase('legacy.u2frm5'),
    actionText: phrase('legacy.12hgt5u'),
    actionPath: '/model-gateway/prompt-guard',
  },
])

const integrationItems = computed(() => [
  {
    key: 'runtime-token',
    title: phrase('legacy.140y10e'),
    status: boundAgentTokenCount.value > 0 ? 'ok' : 'warning',
    statusText: boundAgentTokenCount.value > 0 ? phrase('legacy.1ghmee8') : phrase('legacy.7mgyvl'),
    description: phrase('legacy.14n23nw'),
    meta: [
      { label: phrase('legacy.1abb4z'), value: `${boundAgentTokenCount.value}` },
    ],
    actionText: phrase('legacy.y9va7n'),
    actionPath: '/credentials',
  },
  {
    key: 'runtime-check',
    title: phrase('legacy.kulwtc'),
    status: managerStatus.value.hooks_available ? 'ok' : 'warning',
    statusText: managerStatus.value.hooks_available ? phrase('legacy.18ety4i') : phrase('legacy.1g1lnce'),
    description: phrase('legacy.1gnnji7'),
    actionText: phrase('legacy.tp1mzf'),
    actionPath: '/runtime',
  },
  {
    key: 'scanner',
    title: phrase('legacy.17bs4x'),
    status: scannerTokens.value.length > 0 ? 'ok' : 'warning',
    statusText: scannerTokens.value.length > 0 ? phrase('legacy.18ety4i') : phrase('legacy.1v15qsb'),
    description: phrase('legacy.vot61v'),
    meta: [
      { label: phrase('legacy.12rtpxx'), value: `${scannerTokens.value.length}` },
    ],
    actionText: phrase('legacy.192ppzd'),
    actionPath: '/scanner-access',
  },
  {
    key: 'runtime-audit',
    title: phrase('legacy.udt5mo'),
    status: 'ok',
    statusText: phrase('legacy.18ety4i'),
    description: phrase('legacy.1k1twim'),
    actionText: phrase('legacy.c63dvn'),
    actionPath: '/audit',
  },
])

const capabilityGroups = computed(() => {
  const groups = [
    {
      key: 'core',
      title: phrase('legacy.is6646'),
      description: phrase('legacy.9afyo3'),
      items: coreItems.value,
    },
    {
      key: 'analysis',
      title: phrase('legacy.mbjhkh'),
      description: phrase('legacy.j1wmye'),
      items: analysisItems.value,
    },
    {
      key: 'gateway',
      title: phrase('legacy.15en1a5'),
      description: phrase('legacy.i6u5ex'),
      items: gatewayItems.value,
    },
    {
      key: 'integration',
      title: phrase('legacy.1p5vv10'),
      description: phrase('legacy.19ndc48'),
      items: integrationItems.value,
    },
  ]
  return groups.map((group) => {
    const items = group.items.map(withSourceStatus)
    return { ...group, items, status: groupStatus(items) }
  })
})

const overallHealth = computed(() => {
  const statuses = capabilityGroups.value.map((group) => group.status)
  if (statuses.includes('error')) {
    return { status: 'error', text: phrase('legacy.1yaobox'), message: phrase('legacy.1xk31no') }
  }
  if (statuses.includes('warning')) {
    return { status: 'warning', text: phrase('legacy.1bd07kw'), message: phrase('legacy.d3obsd') }
  }
  if (statuses.includes('unknown')) {
    return { status: 'unknown', text: phrase('legacy.1w2inwf'), message: phrase('legacy.hlvlfi') }
  }
  return { status: 'ok', text: phrase('legacy.tt5vxa'), message: phrase('legacy.1nzlxij') }
})

const recommendations = computed(() =>
  capabilityGroups.value
    .flatMap((group) => group.items.map((item) => ({ ...item, groupTitle: group.title })))
    .filter((item) => ['error', 'warning'].includes(item.status))
    .map((item) => ({
      title: `${item.groupTitle}：${item.title} ${item.statusText || statusText(item.status)}`,
      description: item.description,
      actionPath: item.actionPath,
      actionText: item.actionText || phrase('legacy.azmapg'),
    })),
)

const fetchStatus = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const [
      manager,
      llm,
      sandbox,
      providers,
      models,
      tokens,
      policies,
    ] = await Promise.all([
      loadSource('manager', 'settings:view', () => getAgentManagerSystemStatus(), {}),
      loadSource('llm', 'settings:view', () => getLlmConfig(), {}),
      loadSource('sandbox', 'settings:view', () => getSandboxConfig(), {}),
      loadSource('providers', 'providers:view', () => listModelProviders(), []),
      loadSource('models', 'models:view', () => listModelEndpoints(), []),
      loadSource('tokens', 'credentials:view', () => listAccessTokens({ page_size: 200 }), { items: [] }),
      loadSource('policies', 'privacy:view', () => listPrivacyPolicies(), []),
    ])
    managerStatus.value = manager || {}
    llmConfig.value = llm || {}
    sandboxConfig.value = sandbox || {}
    modelProviders.value = toArray(providers)
    modelEndpoints.value = toArray(models)
    accessTokens.value = toArray(tokens)
    privacyPolicies.value = toArray(policies)
  } catch (error) {
    message.error(extractErrorMsg(error, phrase('legacy.q92czh')))
  } finally {
    loading.value = false
  }
}

const extractErrorMsg = (error, fallback) => {
  const detail = error.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(e => e.msg).join('; ')
  return fallback
}

onMounted(fetchStatus)
</script>

<style scoped>
.system-overview {
  padding-bottom: 24px;
}

.health-panel {
  display: flex;
  gap: 20px;
  align-items: flex-start;
  justify-content: space-between;
  margin-top: 16px;
  padding: 18px 20px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.health-main {
  display: flex;
  gap: 20px;
  align-items: flex-start;
  justify-content: space-between;
  width: 100%;
}

.eyebrow {
  margin-bottom: 4px;
  color: #64748b;
  font-size: 12px;
}

.health-title {
  margin-bottom: 6px;
  color: #16324f;
  font-size: 20px;
  font-weight: 600;
}

.health-summary {
  display: flex;
  gap: 8px;
  align-items: center;
  color: #475569;
}

.group-status-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.group-status-pill {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 5px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  color: #475569;
  background: #f8fafc;
  font-size: 12px;
}

.capability-section {
  margin-top: 18px;
  padding: 16px 18px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-title {
  color: #16324f;
  font-size: 16px;
  font-weight: 600;
}

.section-subtitle {
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
}

.capability-list {
  border-top: 1px solid #f1f5f9;
}

.capability-row {
  display: grid;
  grid-template-columns: 10px minmax(260px, 1fr) minmax(220px, 0.8fr) 96px 116px;
  gap: 14px;
  align-items: center;
  min-height: 76px;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.capability-row:last-child {
  border-bottom: 0;
}

.capability-status {
  width: 8px;
  height: 34px;
  border-radius: 999px;
  background: #d1d5db;
}

.status-ok {
  background: #22c55e;
}

.status-warning {
  background: #f59e0b;
}

.status-error {
  background: #ef4444;
}

.status-disabled,
.status-unknown {
  background: #cbd5e1;
}

.capability-main {
  min-width: 0;
}

.capability-title {
  color: #1f2937;
  font-weight: 600;
}

.capability-desc {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.meta-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  min-width: 0;
}

.meta-line {
  display: flex;
  gap: 6px;
  color: #475569;
  font-size: 12px;
  line-height: 1.4;
}

.meta-label {
  flex: none;
  color: #8c8c8c;
}

.meta-value {
  min-width: 0;
  overflow-wrap: anywhere;
}

.meta-empty {
  color: #c0c4cc;
  font-size: 12px;
}

.capability-state {
  text-align: left;
}

.capability-action {
  text-align: right;
  white-space: nowrap;
}

.recommendation-panel {
  margin-top: 18px;
  padding: 16px 18px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.recommendation-list {
  border-top: 1px solid #f1f5f9;
}

.recommendation-row {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.recommendation-row:last-child {
  border-bottom: 0;
}

.recommendation-title {
  color: #1f2937;
  font-weight: 600;
}

.recommendation-desc {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

@media (max-width: 768px) {
  .health-panel,
  .health-main {
    align-items: flex-start;
    flex-direction: column;
  }

  .group-status-list {
    justify-content: flex-start;
  }

  .capability-row {
    grid-template-columns: 10px minmax(0, 1fr);
  }

  .meta-list,
  .capability-state,
  .capability-action {
    grid-column: 2;
    text-align: left;
  }

  .recommendation-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
