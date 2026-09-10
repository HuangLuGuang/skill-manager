<template>
  <div class="credential-page">
    <a-page-header :title="$t('credentials.pageTitle')" :sub-title="$t('credentials.pageSubtitle')">
      <template #extra>
        <a-button :loading="loading" @click="fetchTokens">{{ $t('credentials.refresh') }}</a-button>
        <a-button type="primary" @click="openCreate()">{{ $t('credentials.createAction') }}</a-button>
      </template>
    </a-page-header>

    <section class="route-map" :aria-label="$t('credentials.routeEyebrow')">
      <div class="route-grid">
        <button
          v-for="scenario in credentialScenarios"
          :key="scenario.id"
          type="button"
          class="route-card"
          @click="startScenario(scenario.id)"
        >
          <span class="route-card__mark">{{ scenario.mark }}</span>
          <span class="route-card__content">
            <strong>{{ scenario.title }}</strong>
            <span class="route-card__description">{{ scenario.description }}</span>
            <span class="route-card__flow">
              <span>{{ scenario.caller }}</span>
              <b aria-hidden="true">→</b>
              <span>{{ scenario.access }}</span>
            </span>
          </span>
        </button>
      </div>
    </section>

    <a-card class="inventory-card" :bordered="false">
      <div class="inventory-head">
        <div>
          <h2>{{ $t('credentials.inventoryTitle') }}</h2>
          <p>{{ $t('credentials.inventoryDescription') }}</p>
        </div>
        <a-space wrap>
          <a-select
            v-model:value="filters.token_type"
            allow-clear
            :placeholder="$t('credentials.allCallers')"
            style="width: 210px"
            @change="fetchTokens"
          >
            <a-select-option v-for="scenario in credentialScenarios" :key="scenario.tokenType" :value="scenario.tokenType">
              {{ scenario.title }}
            </a-select-option>
          </a-select>
          <span class="inventory-count">{{ $t('credentials.recordCount', { count: tokens.length }) }}</span>
        </a-space>
      </div>

      <a-table
        :data-source="tokens"
        :columns="columns"
        row-key="id"
        :loading="loading"
        size="middle"
        :pagination="{ pageSize: 10 }"
        :scroll="{ x: 920 }"
      >
        <template #emptyText>
          <div class="empty-credentials">
            <div class="empty-credentials__mark">KEY</div>
            <strong>{{ $t('credentials.emptyTitle') }}</strong>
            <span>{{ $t('credentials.emptyDescription') }}</span>
            <a-button type="primary" @click="openCreate()">{{ $t('credentials.createFirst') }}</a-button>
          </div>
        </template>

        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'credential'">
            <div class="credential-name">{{ record.name }}</div>
            <code class="credential-prefix">{{ record.token_prefix }}</code>
          </template>
          <template v-else-if="column.key === 'caller'">
            <a-tag :color="typeTagColor(record.token_type)">{{ tokenTypeLabel(record.token_type) }}</a-tag>
            <div class="caller-binding">{{ callerBinding(record) }}</div>
          </template>
          <template v-else-if="column.key === 'access'">
            <a-space wrap size="small">
              <a-tag v-for="item in accessSummary(record)" :key="item.label" :color="item.color">{{ item.label }}</a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'activity'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
            <div class="activity-time">{{ lastActivity(record) }}</div>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-popconfirm v-if="record.status === 'active'" :title="$t('legacy.lsaw9d')" @confirm="handleRevoke(record)">
                <a-button type="link" danger :loading="actionId === record.id">{{ $t('credentials.revoke') }}</a-button>
              </a-popconfirm>
              <a-popconfirm :title="$t('legacy.1dfi7sm')" @confirm="handleDelete(record)">
                <a-button type="link" danger :loading="actionId === record.id">{{ $t('credentials.delete') }}</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>

        <template #expandedRowRender="{ record }">
          <div class="credential-detail-grid">
            <div class="detail-block">
              <span class="detail-label">{{ $t('credentials.permissionDetails') }}</span>
              <a-space wrap size="small">
                <code v-for="scope in record.scopes || []" :key="scope" class="scope-chip">{{ scope }}</code>
              </a-space>
            </div>
            <div class="detail-block">
              <span class="detail-label">{{ $t('credentials.resourceBoundary') }}</span>
              <span>{{ resourceBoundary(record) }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-label">{{ $t('credentials.securityBoundary') }}</span>
              <span>{{ securityBoundary(record) }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-label">{{ $t('credentials.createdAndUsed') }}</span>
              <span>{{ $t('credentials.createdAt') }} {{ formatTime(record.created_at) }}</span>
              <span>{{ $t('credentials.lastUsedAt') }} {{ formatTime(record.last_used_at) }}</span>
            </div>
          </div>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="createVisible"
      :title="$t('credentials.createTitle')"
      width="900px"
      :footer="null"
      :destroy-on-close="true"
    >
      <div class="create-progress" :class="{ 'create-progress--config': createStage === 'config' }">
        <span><b>1</b>{{ $t('credentials.stepCaller') }}</span>
        <i></i>
        <span><b>2</b>{{ $t('credentials.stepBoundary') }}</span>
      </div>

      <div v-if="createStage === 'choose'" class="scenario-picker">
        <div class="scenario-picker__intro">
          <h3>{{ $t('credentials.chooseCallerTitle') }}</h3>
          <p>{{ $t('credentials.chooseCallerDescription') }}</p>
        </div>
        <button
          v-for="scenario in credentialScenarios"
          :key="scenario.id"
          type="button"
          class="scenario-option"
          :style="{ '--route-accent': scenario.color }"
          @click="selectScenario(scenario.id)"
        >
          <span class="scenario-option__mark">{{ scenario.mark }}</span>
          <span>
            <strong>{{ scenario.title }}</strong>
            <small>{{ scenario.description }}</small>
          </span>
          <b aria-hidden="true">→</b>
        </button>
        <div class="modal-actions">
          <a-button @click="createVisible = false">{{ $t('credentials.cancel') }}</a-button>
        </div>
      </div>

      <div v-else>
        <div class="selected-route" :style="{ '--route-accent': selectedScenario.color }">
          <span class="selected-route__mark">{{ selectedScenario.mark }}</span>
          <div>
            <strong>{{ selectedScenario.title }}</strong>
            <span>{{ selectedScenario.description }}</span>
          </div>
          <a-button type="link" @click="createStage = 'choose'">{{ $t('credentials.changeCaller') }}</a-button>
        </div>

        <a-form layout="vertical" :model="form" class="credential-form">
          <section class="form-section">
            <div class="form-section__head">
              <span>{{ $t('credentials.identitySection') }}</span>
              <small>{{ $t('credentials.identitySectionHint') }}</small>
            </div>
            <a-row :gutter="16">
              <a-col :xs="24" :md="12">
                <a-form-item :label="$t('credentials.nameLabel')" required>
                  <a-input v-model:value="form.name" :placeholder="$t('credentials.namePlaceholder')" />
                </a-form-item>
              </a-col>
              <a-col v-if="form.token_type === 'agent_runtime'" :xs="24" :md="12">
                <a-form-item :label="$t('credentials.boundAgent')" required>
                  <a-select
                    v-model:value="form.bound_agent_id"
                    show-search
                    allow-clear
                    option-filter-prop="label"
                    :placeholder="$t('credentials.boundAgentPlaceholder')"
                  >
                    <a-select-option v-for="agent in agents" :key="agent.agent_id" :value="agent.agent_id" :label="`${agent.name} ${agent.agent_id}`">
                      {{ agent.name }}（{{ agent.agent_id }}）
                    </a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
            </a-row>
          </section>

          <section v-if="selectedScenarioId === 'client'" class="form-section client-issuance-section">
            <div class="form-section__head">
              <span>{{ $t('credentials.clientAgentIssuanceSection') }}</span>
              <small>{{ $t('credentials.clientAgentIssuanceHint') }}</small>
            </div>
            <a-checkbox v-model:checked="form.allow_agent_credential_issuance" @change="handleClientIssuanceChange">
              <strong>{{ $t('credentials.allowAgentCredentialIssuance') }}</strong>
            </a-checkbox>
            <p class="field-hint client-issuance-description">{{ $t('credentials.allowAgentCredentialIssuanceDescription') }}</p>
            <a-alert
              type="warning"
              show-icon
              class="client-issuance-permissions"
              :message="$t('credentials.agentCredentialPermissionsTitle')"
              :description="$t('credentials.agentCredentialPermissionsDescription')"
            />
          </section>

          <section v-if="form.token_type === 'agent_runtime'" class="form-section">
            <div class="form-section__head">
              <span>{{ $t('credentials.agentCapabilitySection') }}</span>
              <small>{{ $t('credentials.agentCapabilityHint') }}</small>
            </div>
            <a-radio-group v-model:value="form.agent_preset" class="preset-grid" @change="applyAgentPreset">
              <label v-for="preset in agentPresetOptions" :key="preset.value" class="preset-option" :class="{ 'preset-option--selected': form.agent_preset === preset.value }">
                <a-radio :value="preset.value" />
                <span><strong>{{ preset.title }}</strong><small>{{ preset.description }}</small></span>
              </label>
            </a-radio-group>
          </section>

          <section v-if="supportsModels || supportsMcp" class="form-section">
            <div class="form-section__head">
              <span>{{ $t('credentials.resourceSection') }}</span>
              <small>{{ $t('credentials.resourceSectionHint') }}</small>
            </div>
            <a-row :gutter="16">
              <a-col v-if="supportsModels" :xs="24" :md="supportsMcp ? 12 : 24">
                <a-form-item :label="$t(form.token_type === 'client' ? 'credentials.clientDelegatedModels' : 'credentials.allowedModels')">
                  <a-select v-model:value="form.allowed_models" mode="multiple" allow-clear :placeholder="$t('credentials.allowedModelsPlaceholder')">
                    <a-select-option v-for="model in models" :key="model.name" :value="model.name">{{ model.display_name || model.name }}</a-select-option>
                  </a-select>
                  <div class="field-hint">{{ $t(form.token_type === 'client' ? 'credentials.clientDelegatedModelsHint' : 'credentials.allModelsHint') }}</div>
                </a-form-item>
              </a-col>
              <a-col v-if="supportsMcp" :xs="24" :md="supportsModels ? 12 : 24">
                <a-form-item :label="$t('credentials.allowedGateways')" required>
                  <a-select v-model:value="form.allowed_mcp_gateways" mode="multiple" allow-clear :placeholder="$t('credentials.allowedGatewaysPlaceholder')">
                    <a-select-option v-for="gateway in mcpGateways" :key="gateway.slug" :value="gateway.slug">
                      {{ gateway.name }}（{{ gateway.slug }}）
                    </a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
            </a-row>
          </section>

          <a-collapse v-model:activeKey="advancedSections" ghost class="advanced-collapse">
            <a-collapse-panel key="advanced" :header="$t('credentials.advancedTitle')">
              <p class="advanced-intro">{{ $t('credentials.advancedDescription') }}</p>

              <a-form-item v-if="form.agent_preset === 'custom' || form.token_type !== 'agent_runtime'" :label="$t('credentials.rawPermissions')">
                <a-select v-model:value="form.scopes" mode="multiple" style="width: 100%" @change="handleScopesChange">
                  <a-select-option v-for="scope in availableScopes" :key="scope" :value="scope">{{ scope }}</a-select-option>
                </a-select>
                <div class="field-hint">{{ $t('credentials.rawPermissionsHint') }}</div>
              </a-form-item>

              <template v-if="form.scopes.includes('model:chat')">
                <div class="advanced-subtitle">{{ $t('credentials.modelProtection') }}</div>
                <a-row :gutter="16">
                  <a-col :xs="24" :md="12">
                    <a-form-item :label="$t('credentials.promptGuard')">
                      <a-radio-group v-model:value="form.prompt_guard_mode" button-style="solid">
                        <a-radio-button value="off">{{ $t('credentials.guardOff') }}</a-radio-button>
                        <a-radio-button value="log">{{ $t('credentials.guardLog') }}</a-radio-button>
                        <a-radio-button value="warn">{{ $t('credentials.guardWarn') }}</a-radio-button>
                        <a-radio-button value="block">{{ $t('credentials.guardBlock') }}</a-radio-button>
                      </a-radio-group>
                    </a-form-item>
                  </a-col>
                  <a-col :xs="24" :md="12">
                    <a-form-item>
                      <a-checkbox v-model:checked="form.enable_compression">{{ $t('credentials.enableCompression') }}</a-checkbox>
                      <a-select v-if="form.enable_compression" v-model:value="form.compression_level" style="margin-top: 8px">
                        <a-select-option value="auto">{{ $t('credentials.compressionAuto') }}</a-select-option>
                        <a-select-option value="conservative">{{ $t('credentials.compressionConservative') }}</a-select-option>
                        <a-select-option value="aggressive">{{ $t('credentials.compressionAggressive') }}</a-select-option>
                      </a-select>
                    </a-form-item>
                  </a-col>
                </a-row>
              </template>

              <div class="advanced-subtitle">{{ $t('credentials.capacityAndSource') }}</div>
              <a-row :gutter="16">
                <a-col v-if="form.token_type === 'scanner'" :xs="24" :md="12">
                  <a-form-item :label="$t('credentials.maxUploadMb')">
                    <a-input-number v-model:value="form.max_upload_mb" :min="1" :max="10240" style="width: 100%" />
                  </a-form-item>
                </a-col>
                <a-col v-if="form.token_type === 'scanner'" :xs="24" :md="12">
                  <a-form-item :label="$t('credentials.maxConcurrentJobs')">
                    <a-input-number v-model:value="form.max_concurrent_jobs" :min="1" :max="100" style="width: 100%" />
                  </a-form-item>
                </a-col>
                <template v-else>
                  <a-col :xs="24" :md="12">
                    <a-form-item :label="$t('credentials.maxBodyKb')">
                      <a-input-number v-model:value="form.max_body_kb" :min="1" :max="10240" style="width: 100%" />
                    </a-form-item>
                  </a-col>
                  <a-col :xs="24" :md="12">
                    <a-form-item :label="$t('credentials.maxConcurrentRequests')">
                      <a-input-number v-model:value="form.max_concurrent_requests" :min="1" :max="100" style="width: 100%" />
                    </a-form-item>
                  </a-col>
                </template>
              </a-row>
              <a-form-item :label="$t('credentials.allowedIps')">
                <a-select v-model:value="form.allowed_ips" mode="tags" :placeholder="$t('credentials.allowedIpsPlaceholder')" />
                <div class="field-hint">{{ $t('credentials.allowedIpsHint') }}</div>
              </a-form-item>
            </a-collapse-panel>
          </a-collapse>
        </a-form>

        <div class="creation-summary">
          <span>{{ $t('credentials.willCreate') }}</span>
          <strong>{{ creationSummary }}</strong>
        </div>
        <div class="modal-actions">
          <a-button @click="createVisible = false">{{ $t('credentials.cancel') }}</a-button>
          <a-button type="primary" :loading="creating" @click="handleCreate">{{ $t('credentials.createAndShow') }}</a-button>
        </div>
      </div>
    </a-modal>

    <a-modal v-model:open="createdVisible" :title="$t('credentials.createdTitle')" width="760px" :footer="null">
      <div class="one-time-secret">
        <span class="one-time-secret__mark">!</span>
        <div>
          <strong>{{ $t('credentials.copyNowTitle') }}</strong>
          <p>{{ $t('credentials.copyNowDescription') }}</p>
        </div>
      </div>
      <a-input-group compact>
        <a-input :value="createdToken" readonly class="secret-input" style="width: calc(100% - 112px)" />
        <a-button type="primary" style="width: 112px" @click="copy(createdToken)" :disabled="!createdToken">{{ $t('credentials.copy') }}</a-button>
      </a-input-group>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

import { i18n } from '../i18n'
import { copyText, promptManualCopy } from '../utils/clipboard'
import { formatDateTime } from '../utils/format'
import {
  createAccessToken,
  deleteAccessToken,
  listAccessTokens,
  listAgents,
  listMcpGateways,
  listModelEndpoints,
  revokeAccessToken,
} from '../api'

const route = useRoute()
const router = useRouter()
const t = (key, params) => i18n.global.t(key, params)
const loading = ref(false)
const creating = ref(false)
const createVisible = ref(false)
const createStage = ref('choose')
const selectedScenarioId = ref('agent')
const advancedSections = ref([])
const createdVisible = ref(false)
const createdToken = ref('')
const actionId = ref(null)
const tokens = ref([])
const agents = ref([])
const models = ref([])
const mcpGateways = ref([])
const filters = reactive({ token_type: undefined })
const form = reactive({
  name: '',
  token_type: 'agent_runtime',
  agent_preset: 'verification',
  bound_agent_id: undefined,
  scopes: [],
  allowed_models: [],
  allowed_mcp_gateways: [],
  allowed_ips: [],
  max_body_kb: 1024,
  max_concurrent_requests: 5,
  max_upload_mb: 50,
  max_concurrent_jobs: 2,
  enable_compression: false,
  compression_level: 'auto',
  prompt_guard_mode: 'block',
  prompt_guard_llm_review: false,
  allow_agent_credential_issuance: false,
})

const agentScopePresets = {
  verification: ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool'],
  governance: ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool', 'runtime:govern'],
  governance_model: ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool', 'runtime:govern', 'model:chat'],
  governance_model_mcp: ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool', 'runtime:govern', 'model:chat', 'mcp:connect', 'mcp:list-tools', 'mcp:call-tools'],
}
const typeDefaults = {
  model_gateway: ['model:chat'],
  agent_runtime: [...agentScopePresets.verification],
  scanner: ['scanner:submit', 'scanner:read-own-results', 'scanner:read-own-sessions'],
  client: [
    'client:register',
    'client:heartbeat',
    'client:read-policy',
    'client:read-tasks',
    'client:report-inventory',
    'client:report-events',
    'client:submit-skill',
    'client:download-approved-skill',
  ],
  mcp_gateway: ['mcp:connect', 'mcp:list-tools', 'mcp:call-tools'],
}
const scopeOptionsByType = {
  ...typeDefaults,
  agent_runtime: [...agentScopePresets.governance_model_mcp],
}

const credentialScenarios = computed(() => [
  {
    id: 'agent', tokenType: 'agent_runtime', mark: 'AG', color: '#167c80',
    title: t('credentials.scenarios.agent.title'), description: t('credentials.scenarios.agent.description'),
    caller: t('credentials.scenarios.agent.caller'), access: t('credentials.scenarios.agent.access'),
  },
  {
    id: 'model', tokenType: 'model_gateway', mark: 'AI', color: '#315da8',
    title: t('credentials.scenarios.model.title'), description: t('credentials.scenarios.model.description'),
    caller: t('credentials.scenarios.model.caller'), access: t('credentials.scenarios.model.access'),
  },
  {
    id: 'mcp', tokenType: 'mcp_gateway', mark: 'MC', color: '#7651a8',
    title: t('credentials.scenarios.mcp.title'), description: t('credentials.scenarios.mcp.description'),
    caller: t('credentials.scenarios.mcp.caller'), access: t('credentials.scenarios.mcp.access'),
  },
  {
    id: 'scanner', tokenType: 'scanner', mark: 'SC', color: '#b26b18',
    title: t('credentials.scenarios.scanner.title'), description: t('credentials.scenarios.scanner.description'),
    caller: t('credentials.scenarios.scanner.caller'), access: t('credentials.scenarios.scanner.access'),
  },
  {
    id: 'client', tokenType: 'client', mark: 'CL', color: '#556575',
    title: t('credentials.scenarios.client.title'), description: t('credentials.scenarios.client.description'),
    caller: t('credentials.scenarios.client.caller'), access: t('credentials.scenarios.client.access'),
  },
])
const selectedScenario = computed(() => credentialScenarios.value.find(item => item.id === selectedScenarioId.value) || credentialScenarios.value[0])
const agentPresetOptions = computed(() => [
  { value: 'verification', title: t('credentials.verificationPreset'), description: t('credentials.verificationPresetDescription') },
  { value: 'governance', title: t('credentials.governancePreset'), description: t('credentials.governancePresetDescription') },
  { value: 'governance_model', title: t('credentials.governanceModelPreset'), description: t('credentials.governanceModelPresetDescription') },
  { value: 'governance_model_mcp', title: t('credentials.governanceModelMcpPreset'), description: t('credentials.governanceModelMcpPresetDescription') },
  { value: 'custom', title: t('credentials.customPreset'), description: t('credentials.customPresetDescription') },
])
const availableScopes = computed(() => scopeOptionsByType[form.token_type] || [])
const supportsMcp = computed(() =>
  form.token_type === 'mcp_gateway' || (form.token_type === 'agent_runtime' && form.scopes.some(scope => scope.startsWith('mcp:')))
)
const supportsModels = computed(() =>
  (['model_gateway', 'agent_runtime'].includes(form.token_type) && form.scopes.includes('model:chat'))
  || (form.token_type === 'client' && form.allow_agent_credential_issuance)
)
const columns = computed(() => [
  { title: t('credentials.credentialColumn'), key: 'credential', width: 220 },
  { title: t('credentials.callerColumn'), key: 'caller', width: 220 },
  { title: t('credentials.accessColumn'), key: 'access' },
  { title: t('credentials.activityColumn'), key: 'activity', width: 190 },
  { title: t('credentials.actionColumn'), key: 'action', width: 150, fixed: 'right' },
])
const creationSummary = computed(() => {
  const parts = [selectedScenario.value.title]
  if (form.bound_agent_id) parts.push(t('credentials.summaryBoundAgent', { agent: agentDisplay(form.bound_agent_id) }))
  if (supportsModels.value) parts.push(form.allowed_models.length ? t('credentials.summaryModels', { count: form.allowed_models.length }) : t('credentials.summaryAllModels'))
  if (supportsMcp.value) parts.push(t('credentials.summaryGateways', { count: form.allowed_mcp_gateways.length }))
  return parts.join(' · ')
})

const formatTime = formatDateTime
const sameScopes = (left, right) =>
  left.length === right.length && [...left].sort().every((scope, index) => scope === [...right].sort()[index])
const scenarioByTokenType = value => credentialScenarios.value.find(item => item.tokenType === value)
const tokenTypeLabel = value => scenarioByTokenType(value)?.title || value
const typeTagColor = value => ({ agent_runtime: 'cyan', model_gateway: 'blue', mcp_gateway: 'purple', scanner: 'orange', client: 'default' }[value] || 'default')
const statusLabel = value => ({ active: t('credentials.active'), disabled: t('credentials.disabled'), revoked: t('credentials.revoked') }[value] || value)
const statusColor = value => ({ active: 'green', disabled: 'orange', revoked: 'red' }[value] || 'default')
const agentDisplay = agentId => {
  const agent = agents.value.find(item => item.agent_id === agentId)
  return agent ? `${agent.name}（${agent.agent_id}）` : agentId
}
const callerBinding = record => {
  if (record.bound_agent_id) return agentDisplay(record.bound_agent_id)
  if (record.bound_client_id) return t('credentials.boundClientValue', { client: record.bound_client_id })
  if (record.group_id) return t('credentials.boundGroupValue', { group: record.group_id })
  if (record.user_id) return t('credentials.boundUserValue', { user: record.user_id })
  return t('credentials.noBinding')
}
const accessSummary = record => {
  const scopes = record.scopes || []
  const items = []
  if (scopes.some(scope => scope.startsWith('runtime:'))) items.push({ label: t('credentials.runtimeAccess'), color: 'cyan' })
  if (scopes.includes('model:chat')) {
    items.push({ label: record.allowed_models?.length ? t('credentials.modelCount', { count: record.allowed_models.length }) : t('credentials.allModels'), color: 'blue' })
  }
  if (scopes.some(scope => scope.startsWith('mcp:'))) items.push({ label: t('credentials.gatewayCount', { count: record.allowed_mcp_gateways?.length || 0 }), color: 'purple' })
  if (record.token_type === 'scanner') items.push({ label: t('credentials.scannerAccess'), color: 'orange' })
  if (record.token_type === 'client') items.push({ label: t('credentials.clientAccess'), color: 'default' })
  if (record.token_type === 'client' && record.allow_agent_credential_issuance) {
    items.push({ label: t('credentials.agentCredentialIssuanceAccess'), color: 'geekblue' })
  }
  return items
}
const lastActivity = record => record.last_used_at
  ? t('credentials.lastUsedValue', { time: formatTime(record.last_used_at) })
  : t('credentials.neverUsed')
const resourceBoundary = record => {
  const parts = []
  if (record.allowed_models?.length) parts.push(t('credentials.modelsValue', { value: record.allowed_models.join(', ') }))
  else if ((record.scopes || []).includes('model:chat')) parts.push(t('credentials.allModels'))
  if (record.allowed_mcp_gateways?.length) parts.push(t('credentials.gatewaysValue', { value: record.allowed_mcp_gateways.join(', ') }))
  return parts.join(' · ') || t('credentials.noResourceAllowlist')
}
const securityBoundary = record => {
  const source = record.allowed_ips?.length ? record.allowed_ips.join(', ') : t('credentials.anySourceIp')
  const details = []
  if (record.token_type === 'scanner') {
    details.push(t('credentials.scannerLimitsValue', { upload: record.max_upload_mb, jobs: record.max_concurrent_jobs, source }))
  } else {
    details.push(t('credentials.requestLimitsValue', { body: record.max_body_kb, requests: record.max_concurrent_requests, source }))
  }
  if ((record.scopes || []).includes('model:chat')) {
    details.push(t('credentials.promptGuardValue', { mode: promptGuardLabel(record.prompt_guard_mode) }))
    if (record.enable_compression) details.push(t('credentials.compressionEnabled'))
  }
  return details.join(' · ')
}
const promptGuardLabel = value => ({
  off: t('credentials.guardOff'),
  log: t('credentials.guardLog'),
  warn: t('credentials.guardWarn'),
  block: t('credentials.guardBlock'),
}[value] || value)

const applyAgentPreset = () => {
  const scopes = agentScopePresets[form.agent_preset]
  if (!scopes) {
    advancedSections.value = ['advanced']
    return
  }
  form.scopes = [...scopes]
  handleScopesChange()
}
const handleScopesChange = () => {
  if (form.token_type === 'agent_runtime') {
    const matched = Object.entries(agentScopePresets).find(([, scopes]) => sameScopes(form.scopes, scopes))
    form.agent_preset = matched?.[0] || 'custom'
  }
  if (!form.scopes.includes('model:chat')) {
    form.allowed_models = []
    form.enable_compression = false
    form.compression_level = 'auto'
    if (form.token_type !== 'agent_runtime') form.prompt_guard_mode = 'off'
  }
  if (!form.scopes.some(scope => scope.startsWith('mcp:'))) form.allowed_mcp_gateways = []
}
const handleClientIssuanceChange = () => {
  if (!form.allow_agent_credential_issuance) form.allowed_models = []
}
const resetForm = (tokenType, defaults = {}) => {
  Object.assign(form, {
    name: defaults.name || '',
    token_type: tokenType,
    agent_preset: 'verification',
    bound_agent_id: defaults.bound_agent_id,
    scopes: [...(typeDefaults[tokenType] || [])],
    allowed_models: [],
    allowed_mcp_gateways: [],
    allowed_ips: [],
    max_body_kb: 1024,
    max_concurrent_requests: 5,
    max_upload_mb: 50,
    max_concurrent_jobs: 2,
    enable_compression: false,
    compression_level: 'auto',
    prompt_guard_mode: tokenType === 'agent_runtime' ? 'block' : 'off',
    prompt_guard_llm_review: false,
    allow_agent_credential_issuance: false,
  })
  advancedSections.value = []
}
const openCreate = (defaults = {}) => {
  createVisible.value = true
  if (defaults.token_type) {
    const scenario = scenarioByTokenType(defaults.token_type) || credentialScenarios.value[0]
    selectedScenarioId.value = scenario.id
    resetForm(scenario.tokenType, defaults)
    createStage.value = 'config'
    return
  }
  createStage.value = 'choose'
}
const startScenario = (scenarioId, defaults = {}) => {
  createVisible.value = true
  selectScenario(scenarioId, defaults)
}
const selectScenario = (scenarioId, defaults = {}) => {
  const scenario = credentialScenarios.value.find(item => item.id === scenarioId)
  if (!scenario) return
  selectedScenarioId.value = scenarioId
  resetForm(scenario.tokenType, defaults)
  createStage.value = 'config'
}

const fetchTokens = async () => {
  loading.value = true
  try {
    const data = await listAccessTokens({ token_type: filters.token_type || undefined })
    tokens.value = data.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || t('credentials.loadFailed'))
  } finally {
    loading.value = false
  }
}
const fetchOptions = async () => {
  const [agentRows, modelRows, gatewayRows] = await Promise.all([listAgents(), listModelEndpoints(), listMcpGateways()])
  agents.value = agentRows || []
  models.value = modelRows || []
  mcpGateways.value = gatewayRows || []
}
const openCreateFromQuery = async () => {
  if (route.query.create !== 'agent_runtime') return
  const agentId = String(route.query.agent_id || '')
  const agent = agents.value.find(item => item.agent_id === agentId)
  startScenario('agent', {
    bound_agent_id: agentId || undefined,
    name: agent ? t('credentials.agentCredentialName', { name: agent.name }) : '',
  })
  await router.replace({ name: 'credentials', query: {} })
}
const handleCreate = async () => {
  if (!form.name.trim()) {
    message.warning(t('credentials.nameRequired'))
    return
  }
  if (form.token_type === 'agent_runtime' && !form.bound_agent_id) {
    message.warning(t('credentials.agentRequired'))
    return
  }
  if (supportsMcp.value && !form.allowed_mcp_gateways.length) {
    message.warning(t('credentials.gatewayRequired'))
    return
  }
  form.prompt_guard_llm_review = false
  creating.value = true
  try {
    const payload = { ...form, name: form.name.trim() }
    delete payload.agent_preset
    const data = await createAccessToken(payload)
    createdToken.value = data.token
    createVisible.value = false
    createdVisible.value = true
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || t('credentials.createFailed'))
  } finally {
    creating.value = false
  }
}
const handleRevoke = async record => {
  actionId.value = record.id
  try {
    await revokeAccessToken(record.id)
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || t('credentials.revokeFailed'))
  } finally {
    actionId.value = null
  }
}
const handleDelete = async record => {
  actionId.value = record.id
  try {
    await deleteAccessToken(record.id)
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || t('credentials.deleteFailed'))
  } finally {
    actionId.value = null
  }
}
const copy = async value => {
  const text = value || ''
  try {
    await copyText(text)
    message.success(t('credentials.copied'))
  } catch {
    message.warning(t('clipboard.copyFailed'))
    promptManualCopy(text, t('clipboard.manualCopyPrompt'))
  }
}

onMounted(async () => {
  await Promise.all([fetchTokens(), fetchOptions()])
  await openCreateFromQuery()
})
</script>

<style scoped>
.credential-page {
  --ink: #16324f;
  --muted: #657789;
  --line: #dce5eb;
  --surface: #f5f8fa;
  --trust: #167c80;
}

.route-map {
  margin-top: 12px;
}

.inventory-head h2 {
  margin: 6px 0 8px;
  color: var(--ink);
  font-size: 22px;
  font-weight: 680;
  letter-spacing: -0.02em;
}

.inventory-head p,
.scenario-picker__intro p {
  margin: 0;
  color: var(--muted);
  line-height: 1.65;
}

.route-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.route-card {
  display: flex;
  min-height: 112px;
  padding: 14px 15px;
  color: inherit;
  text-align: left;
  background: #fff;
  border: 1px solid #d9e1e8;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease;
}

.route-card:hover {
  background: #f8fafc;
  border-color: #9babb9;
}

.route-card:focus-visible {
  border-color: #1677ff;
  box-shadow: 0 0 0 2px rgba(22, 119, 255, 0.16);
  outline: none;
}

.route-card__mark,
.scenario-option__mark,
.selected-route__mark {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  width: 34px;
  height: 34px;
  margin-right: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 700;
  border-radius: 6px;
}

.route-card__mark {
  color: #405468;
  background: #eef2f5;
  border: 1px solid #d9e1e8;
}

.scenario-option__mark,
.selected-route__mark {
  color: #fff;
  background: var(--route-accent);
}

.route-card__content {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.route-card__content strong {
  color: var(--ink);
  font-size: 14px;
  font-weight: 650;
}

.route-card__description {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.route-card__flow {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: auto;
  padding-top: 10px;
  color: #4d6174;
  font-size: 11px;
}

.route-card__flow b {
  color: #1677ff;
}

.inventory-card {
  margin-top: 18px;
  border: 1px solid var(--line);
  border-radius: 14px;
}

.inventory-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.inventory-head h2 {
  margin-top: 0;
}

.inventory-count {
  color: var(--muted);
  font-size: 12px;
}

.credential-name {
  color: var(--ink);
  font-weight: 650;
}

.credential-prefix,
.scope-chip {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.credential-prefix {
  display: inline-block;
  margin-top: 5px;
  color: #607284;
  font-size: 12px;
}

.caller-binding,
.activity-time {
  margin-top: 6px;
  color: var(--muted);
  font-size: 12px;
}

.credential-detail-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr 0.9fr;
  gap: 18px;
  padding: 16px 20px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
}

.detail-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  color: #42576b;
  font-size: 12px;
  line-height: 1.6;
}

.detail-label {
  color: var(--ink);
  font-weight: 650;
}

.scope-chip {
  padding: 2px 7px;
  color: #35516b;
  font-size: 11px;
  background: #fff;
  border: 1px solid #d4e0e7;
  border-radius: 4px;
}

.empty-credentials {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 38px;
  color: var(--muted);
}

.empty-credentials__mark {
  display: grid;
  place-items: center;
  width: 54px;
  height: 40px;
  color: var(--trust);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 700;
  border: 2px solid var(--trust);
  border-radius: 7px;
}

.empty-credentials strong {
  color: var(--ink);
  font-size: 16px;
}

.create-progress {
  display: grid;
  grid-template-columns: max-content 1fr max-content;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
  color: #8695a3;
  font-size: 12px;
}

.create-progress span {
  display: flex;
  align-items: center;
  gap: 7px;
}

.create-progress b {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  color: #fff;
  background: var(--trust);
  border-radius: 50%;
}

.create-progress i {
  height: 1px;
  background: var(--line);
}

.create-progress:not(.create-progress--config) span:last-child b {
  color: #7d8d9c;
  background: #e8eef2;
}

.scenario-picker__intro h3 {
  margin-bottom: 4px;
  color: var(--ink);
}

.scenario-picker {
  display: grid;
  gap: 10px;
}

.scenario-option {
  display: grid;
  grid-template-columns: 42px 1fr auto;
  align-items: center;
  padding: 14px 16px;
  text-align: left;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 9px;
  cursor: pointer;
}

.scenario-option:hover,
.scenario-option:focus-visible {
  border-color: var(--route-accent);
  outline: none;
}

.scenario-option strong,
.scenario-option small {
  display: block;
}

.scenario-option strong {
  color: var(--ink);
}

.scenario-option small {
  margin-top: 3px;
  color: var(--muted);
}

.scenario-option > b {
  color: var(--route-accent);
  font-size: 18px;
}

.selected-route {
  display: flex;
  align-items: center;
  padding: 13px 15px;
  background: #f5f9fa;
  border-left: 3px solid var(--route-accent);
  border-radius: 8px;
}

.selected-route > div {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.selected-route strong {
  color: var(--ink);
}

.selected-route span {
  color: var(--muted);
  font-size: 12px;
}

.credential-form {
  max-height: min(62vh, 680px);
  margin-top: 16px;
  padding-right: 4px;
  overflow-y: auto;
}

.form-section {
  padding: 17px 18px 3px;
  margin-bottom: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.client-issuance-description {
  margin: 8px 0 10px 24px;
  line-height: 1.6;
}

.client-issuance-permissions {
  margin: 0 0 14px 24px;
}

.form-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.form-section__head > span {
  color: var(--ink);
  font-weight: 680;
}

.form-section__head small,
.field-hint,
.advanced-intro {
  color: var(--muted);
  font-size: 12px;
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
  width: 100%;
  padding-bottom: 16px;
}

.preset-option {
  display: flex;
  gap: 6px;
  padding: 12px;
  cursor: pointer;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.preset-option--selected {
  background: rgba(22, 124, 128, 0.05);
  border-color: var(--trust);
}

.preset-option span,
.preset-option strong,
.preset-option small {
  display: block;
}

.preset-option strong {
  color: var(--ink);
  font-size: 13px;
}

.preset-option small {
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
}

.advanced-collapse {
  margin: 4px 0 10px;
  background: #f8fafb;
  border: 1px dashed #cbd8e0;
  border-radius: 9px;
}

.advanced-intro {
  margin-top: 0;
}

.advanced-subtitle {
  margin: 14px 0 10px;
  color: var(--ink);
  font-size: 12px;
  font-weight: 680;
  letter-spacing: 0.03em;
}

.creation-summary {
  display: flex;
  gap: 8px;
  padding: 11px 14px;
  margin-top: 12px;
  color: var(--muted);
  font-size: 12px;
  background: #f5f8fa;
  border-radius: 7px;
}

.creation-summary strong {
  color: var(--ink);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
}

.one-time-secret {
  display: flex;
  gap: 13px;
  padding: 16px;
  margin-bottom: 16px;
  background: #fff8e8;
  border: 1px solid #eed39a;
  border-radius: 9px;
}

.one-time-secret__mark {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 28px;
  height: 28px;
  color: #fff;
  font-weight: 800;
  background: #b26b18;
  border-radius: 50%;
}

.one-time-secret strong {
  color: #69400f;
}

.one-time-secret p {
  margin: 4px 0 0;
  color: #7d5b2d;
}

.secret-input :deep(input) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

@media (max-width: 1500px) {
  .route-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .route-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .credential-detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .route-grid {
    grid-template-columns: 1fr;
  }

  .inventory-head,
  .form-section__head {
    align-items: stretch;
    flex-direction: column;
  }

  .credential-detail-grid,
  .preset-grid {
    grid-template-columns: 1fr;
  }

  .credential-form {
    max-height: 58vh;
  }
}

@media (prefers-reduced-motion: reduce) {
  .route-card {
    transition: none;
  }
}
</style>
