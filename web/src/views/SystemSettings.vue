<template>
  <div class="system-overview">
    <a-page-header title="系统总览" sub-title="检查治理、运行、模型网关与接入能力是否可用" />

    <section class="health-panel">
      <div class="health-main">
        <div>
          <div class="eyebrow">平台能力体检</div>
          <div class="health-title">系统健康度</div>
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
      <a-button type="primary" size="small" :loading="loading" @click="fetchStatus">刷新状态</a-button>
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
            <router-link v-if="item.actionPath" :to="item.actionPath">
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
          <div class="section-title">配置建议</div>
          <div class="section-subtitle">只展示会影响系统能力闭环的配置项。</div>
        </div>
      </div>
      <a-empty v-if="!recommendations.length" description="当前系统能力配置完整，可以支持 Skill 治理、模型调用和 Agent 接入。" />
      <div v-else class="recommendation-list">
        <div v-for="item in recommendations" :key="item.title" class="recommendation-row">
          <div class="recommendation-main">
            <div class="recommendation-title">{{ item.title }}</div>
            <div class="recommendation-desc">{{ item.description }}</div>
          </div>
          <div class="recommendation-action">
            <router-link v-if="item.actionPath" :to="item.actionPath">
              <a-button size="small">{{ item.actionText }}</a-button>
            </router-link>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

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
const managerStatus = ref({})
const llmConfig = ref({})
const sandboxConfig = ref({})
const modelProviders = ref([])
const modelEndpoints = ref([])
const accessTokens = ref([])
const privacyPolicies = ref([])

const safeRequest = async (request, fallback) => {
  try {
    return await request()
  } catch (error) {
    return fallback
  }
}

const toArray = (value) => {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.items)) return value.items
  return []
}

const statusText = (status) => ({
  ok: '正常',
  warning: '待配置',
  error: '异常',
  disabled: '未启用',
  unknown: '待检查',
}[status] || '待检查')

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
    ? '模型网关'
    : (managerStatus.value.llm_provider || llmConfig.value.provider || '-'),
)

const coreItems = computed(() => [
  {
    key: 'api',
    title: '后台 API',
    status: 'ok',
    statusText: '可访问',
    description: '管理台已能读取系统状态接口。',
  },
  {
    key: 'signing',
    title: '内容完整性校验',
    status: managerStatus.value.signing_key_configured ? 'ok' : 'warning',
    statusText: managerStatus.value.signing_key_configured ? '生产密钥' : '开发模式',
    description: managerStatus.value.signing_key_configured
      ? '已配置正式完整性校验密钥，适合生产运行时校验。'
      : '当前使用开发模式，生产环境建议配置正式完整性校验密钥。',
    actionText: '查看策略',
    actionPath: '/policy',
  },
  {
    key: 'audit',
    title: '审计日志',
    status: 'ok',
    statusText: '可用',
    description: '审核、凭证、运行校验和网关调用具备统一审计入口。',
    actionText: '查看审计',
    actionPath: '/audit',
  },
])

const analysisItems = computed(() => [
  {
    key: 'sandbox',
    title: 'Sandbox',
    status: sandboxItemStatus.value,
    statusText: sandboxEnabled.value
      ? (managerStatus.value.sandbox_available ? '可用' : '不可用')
      : '未启用',
    description: managerStatus.value.sandbox_status_message || '用于受控执行 probe，辅助判断运行时行为。',
    meta: [
      { label: '后端', value: sandboxRuntime.value },
      { label: '目标', value: sandboxTargetValue.value },
    ],
    actionText: '去测试连接',
    actionPath: '/policy',
  },
  {
    key: 'llm',
    title: 'LLM 分析',
    status: llmItemStatus.value,
    statusText: managerStatus.value.llm_enabled ? '已启用' : '未启用',
    description: managerStatus.value.llm_enabled
      ? '深度研判使用模型网关中选择的模型。'
      : '未启用时只使用基础扫描和规则策略。',
    meta: [
      { label: '模型', value: managerStatus.value.llm_model || llmConfig.value.model || '-' },
      { label: '来源', value: llmSource.value },
    ],
    actionText: '选择模型',
    actionPath: '/policy',
  },
  {
    key: 'deep-analysis',
    title: '深度分析',
    status: managerStatus.value.skillspector_available ? 'ok' : 'warning',
    statusText: managerStatus.value.skillspector_available ? '可用' : '未安装',
    description: '提交时勾选深度分析后，会增加更细的静态与行为信号。',
    actionText: '提交 Skill',
    actionPath: '/submit',
  },
])

const gatewayItems = computed(() => [
  {
    key: 'models',
    title: '模型管理',
    status: activeModels.value.length > 0 ? 'ok' : 'error',
    statusText: activeModels.value.length > 0 ? '有可用模型' : '无可用模型',
    description: '平台内部 LLM 分析和 Agent 调用都应从模型网关选择模型。',
    meta: [
      { label: '供应商', value: `${modelProviders.value.length}` },
      { label: '可用模型', value: `${activeModels.value.length}` },
    ],
    actionText: '去模型管理',
    actionPath: '/model-gateway/models',
  },
  {
    key: 'credentials',
    title: '模型调用凭证',
    status: activeAccessTokens.value.length > 0 ? 'ok' : 'warning',
    statusText: activeAccessTokens.value.length > 0 ? '可用' : '待签发',
    description: '模型网关调用需要有效的模型调用凭证或带 model:chat 的 Agent 凭证。',
    meta: [
      { label: '模型凭证', value: `${gatewayTokens.value.length}` },
      { label: '可调用模型的运行凭证', value: `${agentRuntimeTokens.value.filter(item => item.scopes?.includes('model:chat')).length}` },
    ],
    actionText: '去凭证管理',
    actionPath: '/credentials',
  },
  {
    key: 'privacy',
    title: '隐私策略',
    status: privacyPolicies.value.length > 0 ? 'ok' : 'warning',
    statusText: privacyPolicies.value.length > 0 ? '已配置' : '待配置',
    description: '控制脱敏、路由和审计策略，支撑模型网关合规调用。',
    meta: [
      { label: '策略数', value: `${privacyPolicies.value.length}` },
    ],
    actionText: '去隐私策略',
    actionPath: '/model-gateway/policies',
  },
  {
    key: 'prompt-guard',
    title: 'Prompt 防护测试',
    status: 'ok',
    statusText: '可用',
    description: '可在不调用上游模型的情况下测试提示词注入、凭据外传等规则。',
    actionText: '去测试',
    actionPath: '/model-gateway/prompt-guard',
  },
])

const integrationItems = computed(() => [
  {
    key: 'runtime-token',
    title: '运行凭证签发',
    status: boundAgentTokenCount.value > 0 ? 'ok' : 'warning',
    statusText: boundAgentTokenCount.value > 0 ? '已签发' : '待签发',
    description: '凭证绑定 Agent 后，才能识别调用方并执行运行时校验。',
    meta: [
      { label: '绑定 Agent', value: `${boundAgentTokenCount.value}` },
    ],
    actionText: '去凭证管理',
    actionPath: '/credentials',
  },
  {
    key: 'runtime-check',
    title: 'Runtime 校验接口',
    status: managerStatus.value.hooks_available ? 'ok' : 'warning',
    statusText: managerStatus.value.hooks_available ? '可用' : '待接入',
    description: 'Agent 加载 Skill 前可校验注册状态、审批状态和内容完整性。',
    actionText: '查看接入',
    actionPath: '/runtime',
  },
  {
    key: 'scanner',
    title: 'Scanner 接入',
    status: scannerTokens.value.length > 0 ? 'ok' : 'warning',
    statusText: scannerTokens.value.length > 0 ? '可用' : '待配置',
    description: '客户侧扫描器通过 Scanner 接入凭证提交 Skill。',
    meta: [
      { label: 'Scanner 凭证', value: `${scannerTokens.value.length}` },
    ],
    actionText: '查看接入说明',
    actionPath: '/scanner-access',
  },
  {
    key: 'runtime-audit',
    title: '运行审计链路',
    status: 'ok',
    statusText: '可用',
    description: '调用方、Agent、模型、Skill 和审核动作可以进入审计链路。',
    actionText: '查看审计',
    actionPath: '/audit',
  },
])

const capabilityGroups = computed(() => {
  const groups = [
    {
      key: 'core',
      title: '核心服务',
      description: '检查后台 API、完整性校验和审计基础能力。',
      items: coreItems.value,
    },
    {
      key: 'analysis',
      title: '扫描分析',
      description: '检查 Sandbox、LLM 和深度分析是否可用于 Skill 检测。',
      items: analysisItems.value,
    },
    {
      key: 'gateway',
      title: '模型网关',
      description: '检查模型、调用凭证、隐私策略和 Prompt 防护测试是否可用。',
      items: gatewayItems.value,
    },
    {
      key: 'integration',
      title: '接入链路',
      description: '检查运行凭证、Runtime 校验、Scanner 和审计链路是否具备接入条件。',
      items: integrationItems.value,
    },
  ]
  return groups.map((group) => ({
    ...group,
    status: groupStatus(group.items),
  }))
})

const overallHealth = computed(() => {
  const statuses = capabilityGroups.value.map((group) => group.status)
  if (statuses.includes('error')) {
    return { status: 'error', text: '部分异常', message: '存在会影响运行或模型调用的能力异常。' }
  }
  if (statuses.includes('warning')) {
    return { status: 'warning', text: '待完善', message: '核心能力可用，但仍有配置建议需要处理。' }
  }
  if (statuses.includes('unknown')) {
    return { status: 'unknown', text: '待检查', message: '部分能力状态暂时无法读取。' }
  }
  return { status: 'ok', text: '正常', message: '治理、运行、模型网关和接入能力配置完整。' }
})

const recommendations = computed(() =>
  capabilityGroups.value
    .flatMap((group) => group.items.map((item) => ({ ...item, groupTitle: group.title })))
    .filter((item) => ['error', 'warning'].includes(item.status))
    .map((item) => ({
      title: `${item.groupTitle}：${item.title} ${item.statusText || statusText(item.status)}`,
      description: item.description,
      actionPath: item.actionPath,
      actionText: item.actionText || '去处理',
    })),
)

const fetchStatus = async () => {
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
      safeRequest(() => getAgentManagerSystemStatus(), {}),
      safeRequest(() => getLlmConfig(), {}),
      safeRequest(() => getSandboxConfig(), {}),
      safeRequest(() => listModelProviders(), []),
      safeRequest(() => listModelEndpoints(), []),
      safeRequest(() => listAccessTokens({ page_size: 200 }), { items: [] }),
      safeRequest(() => listPrivacyPolicies(), []),
    ])
    managerStatus.value = manager || {}
    llmConfig.value = llm || {}
    sandboxConfig.value = sandbox || {}
    modelProviders.value = toArray(providers)
    modelEndpoints.value = toArray(models)
    accessTokens.value = toArray(tokens)
    privacyPolicies.value = toArray(policies)
  } catch (error) {
    message.error(extractErrorMsg(error, '获取系统能力状态失败'))
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
