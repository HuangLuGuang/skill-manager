<template>
  <div :class="{ 'agent-workspace-page': workspaceAsset }">
    <AgentDiscoveredWorkspace v-if="workspaceAsset" :key="workspaceAsset.asset_key" :asset="workspaceAsset" :initial-client="route.query.client" :initial-local-id="route.query.local" @back="closeWorkspace" />
    <a-card v-else class="page-card agent-list-card">
      <template #title>
        <a-page-header :title="$t('legacy.5chjsa')" :sub-title="$t('agentAssets.subtitle')">
          <template #extra>
            <a-button v-if="pageAllowed('/runtime')" @click="router.push('/runtime')">{{ $t('agentIntegration.choose') }}</a-button>
            <a-button v-if="hasAccess('agents:create')" type="primary" @click="openAgent()">{{ $t('agentIntegration.register') }}</a-button>
          </template>
        </a-page-header>
      </template>

      <a-card class="asset-stats">
        <a-row :gutter="[12, 12]">
        <a-col :xs="12" :md="8">
            <a-statistic :title="$t('agentAssets.stats.total')" :value="assetStats.total" />
        </a-col>
        <a-col :xs="12" :md="8">
            <a-statistic :title="$t('agentAssets.stats.platform')" :value="assetStats.platform" />
        </a-col>
        <a-col :xs="24" :md="8">
            <a-statistic :title="$t('agentAssets.stats.discovered')" :value="assetStats.client_discovery" />
        </a-col>
      </a-row>
      </a-card>

      <a-card class="asset-list-card" :body-style="{ padding: 0 }">
        <a-tabs v-model:activeKey="filters.origin" class="asset-tabs" @change="handleOriginChange">
          <a-tab-pane key="all" :tab="tabLabel('all', assetStats.total)" />
          <a-tab-pane key="platform" :tab="tabLabel('platform', assetStats.platform)" />
          <a-tab-pane key="client_discovery" :tab="tabLabel('discovered', assetStats.client_discovery)" />
        </a-tabs>
        <a-alert class="source-help" type="info" show-icon :message="$t(`agentIntegration.sources.${filters.origin}`)" />
        <div class="asset-toolbar">
          <a-select v-if="filters.origin !== 'client_discovery'" v-model:value="filters.department_group_id" allow-clear :placeholder="$t('legacy.1qbe72t')" class="department-filter" @change="fetchAgentAssets">
            <a-select-option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</a-select-option>
          </a-select>
          <a-select v-model:value="filters.status" allow-clear :placeholder="$t('legacy.igzce8')" class="status-filter" @change="fetchAgentAssets">
            <a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option>
            <a-select-option value="disabled">{{ $t("legacy.1dcdrxo") }}</a-select-option>
            <a-select-option value="draft">{{ $t("legacy.oc54qp") }}</a-select-option>
            <a-select-option value="online">{{ $t('agentAssets.filters.online') }}</a-select-option>
            <a-select-option value="offline">{{ $t('agentAssets.filters.offline') }}</a-select-option>
            <a-select-option value="not_detected">{{ $t('agentAssets.filters.not_detected') }}</a-select-option>
          </a-select>
          <a-input v-model:value="filters.q" :placeholder="$t('agentAssets.filters.search')" class="asset-search" allow-clear @pressEnter="fetchAgentAssets" />
          <a-button type="primary" @click="fetchAgentAssets" :loading="loading">{{ $t("legacy.16mfmhy") }}</a-button>
          <a-button @click="resetFilters" :disabled="loading">{{ $t("legacy.1wq9feq") }}</a-button>
        </div>

        <a-table class="agent-asset-table" :data-source="agents" :columns="columns" :show-sorter-tooltip="false" :scroll="{ x: 1480 }" rowKey="asset_key" :loading="loading" :pagination="{ pageSize: 10, showSizeChanger: true }">
          <template #headerCell="{ column }">
            <span v-if="column.sortHelp" class="asset-sort-heading">
              {{ column.title }}
              <a-popover :trigger="['hover', 'focus', 'click']" placement="topRight" :overlay-style="{ maxWidth: 'calc(100vw - 32px)' }">
                <template #content><div class="asset-sort-help"><strong>{{ $t('agentAssets.sorting.basis') }}</strong><p>{{ $t(column.sortHelp) }}</p><p>{{ $t('agentAssets.sorting.cycle') }}</p></div></template>
                <button class="asset-sort-info" type="button" :aria-label="$t('agentAssets.sorting.helpLabel', { column: column.title })" @click.stop @keydown.stop><InfoCircleOutlined /></button>
              </a-popover>
            </span>
          </template>
          <template #emptyText>
            <div class="source-empty">
              <p>{{ $t(sourceEmptyKey) }}</p>
              <a-button v-if="sourceEmptyKey === 'agentIntegration.emptyPlatform' && hasAccess('agents:create')" type="primary" @click="openAgent()">{{ $t('agentIntegration.register') }}</a-button>
              <a-button v-if="sourceEmptyKey === 'agentIntegration.emptyClient' && pageAllowed('/clients')" type="primary" @click="router.push('/clients')">{{ $t('agentIntegration.client.open') }}</a-button>
            </div>
          </template>
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'agent'">
              <div class="agent-cell">
                <div class="agent-mark" :class="{ client: record.origin_type === 'client_discovery' }"><AgentProductLogo v-if="record.origin_type === 'client_discovery'" :product-id="record.instances?.[0]?.agent_type || record.channel || ''" /><template v-else>{{ agentInitials(record) }}</template></div>
                <div>
                  <div class="agent-name">{{ record.name }}</div>
                  <div v-if="record.origin_type === 'platform'" class="muted">{{ record.agent_id }}</div>
                </div>
              </div>
            </template>
            <template v-else-if="column.key === 'source'">
              <a-tag :color="record.origin_type === 'platform' ? 'purple' : 'cyan'">{{ sourceText(record) }}</a-tag>
            </template>
            <template v-else-if="column.key === 'owner'">
              <div>{{ record.origin_type === 'client_discovery' ? ownerDepartmentText(record) : (record.department_name || $t('legacy.1bgs62s')) }}</div>
              <div class="muted">{{ record.owner ? $t('agentAssets.owner', { name: record.owner }) : '-' }}</div>
            </template>
            <template v-else-if="column.key === 'location'">
              <template v-if="record.instances?.length">
                <div>{{ record.instances[0].client_name }}</div>
                <div class="muted">{{ instanceLocation(record) }}</div>
              </template>
              <template v-else>
                <div>{{ $t('agentAssets.locationUnknown') }}</div>
              </template>
            </template>
            <template v-else-if="column.key === 'assets'">
              <div>{{ assetModelText(record) }}</div>
              <div class="muted">{{ record.origin_type === 'platform' ? $t('agentAssets.assignedSkillSummary', { count: record.skill_names?.length || 0 }) : record.client_status === 'not_detected' ? $t('agentAssets.inventoryUnavailable') : $t('agentAssets.discoveredSkillSummary', { count: record.discovered_skill_count || 0 }) }}</div>
              <div v-if="record.instances?.some(instance => instance.asset_inventory)" class="muted">{{ $t('localAssets.summary', { mcp: record.discovered_mcp_count, plugins: record.discovered_plugin_count }) }}</div>
              <div v-if="record.plugin_skill_count" class="muted">{{ $t('localAssets.pluginSkills', { count: record.plugin_skill_count }) }}</div>
            </template>
            <template v-else-if="column.key === 'status'">
              <a-space direction="vertical" size="small">
                <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
                <a-tag v-if="record.client_status === 'not_detected'">{{ clientStatusText(record.client_status) }}</a-tag>
                <span v-if="record.instance_count" class="muted">{{ $t('agentAssets.onlineInstances', { online: record.online_instance_count, total: record.instance_count }) }}</span>
              </a-space>
            </template>
            <template v-else-if="column.key === 'lastSeen'">{{ record.last_seen_at || record.updated_at ? formatDateTime(record.last_seen_at || record.updated_at) : '-' }}</template>
            <template v-else-if="column.key === 'actions'">
              <a-space wrap>
                <a @click="openAsset(record)">{{ $t('agentAssets.detail') }}</a>
                <a v-if="record.origin_type === 'platform' && pageAllowed('/runtime')" @click="openGuide(record)">{{ $t('agentIntegration.guide') }}</a>
                <a v-if="record.origin_type === 'platform' && hasAccess('agents:update')" @click="openAgent(record)">{{ $t('agentAssets.edit') }}</a>
                <a-popconfirm v-if="record.origin_type === 'platform' && hasAccess('agents:delete')" :title="$t('legacy.17y5gsa')" @confirm="handleDelete(record)">
                  <a danger>{{ $t("legacy.1t2vi4h") }}</a>
                </a-popconfirm>
              </a-space>
            </template>
          </template>
        </a-table>
      </a-card>
    </a-card>

    <a-drawer v-model:open="assetVisible" :width="760" :title="selectedAsset?.name || $t('agentAssets.detail')">
      <template #extra>
        <a-space wrap>
          <a-button v-if="selectedAsset?.origin_type === 'platform' && pageAllowed('/runtime')" @click="openGuide(selectedAsset)">{{ $t('agentIntegration.guide') }}</a-button>
          <a-button v-if="selectedAsset?.origin_type === 'platform' && hasAccess('agents:update')" type="primary" @click="editSelectedAsset">{{ $t('agentAssets.edit') }}</a-button>
        </a-space>
      </template>
      <template v-if="selectedAsset">
        <div class="drawer-tags">
          <a-tag :color="selectedAsset.origin_type === 'platform' ? 'purple' : 'cyan'">{{ sourceText(selectedAsset) }}</a-tag>
          <span class="muted">{{ selectedAsset.agent_id }}</span>
        </div>
        <template v-if="selectedAsset.origin_type === 'platform'">
          <a-row :gutter="[10, 10]" class="drawer-summary">
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.agentStatus') }}</span><strong>{{ statusText(selectedAsset.status) }}</strong></div></a-col>
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.assignedSkillCount') }}</span><strong>{{ selectedAsset.skill_names?.length || 0 }}</strong></div></a-col>
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.defaultModel') }}</span><strong>{{ selectedAsset.default_model || $t('agentAssets.drawer.notConfigured') }}</strong></div></a-col>
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.runtimeCredential') }}</span><strong>{{ selectedAsset.runtime_token_id ? $t('agentIntegration.linkedCredential') : $t('agentAssets.drawer.notConfigured') }}</strong></div></a-col>
          </a-row>
          <a-tabs v-model:activeKey="assetDetailTab">
            <a-tab-pane key="overview" :tab="$t('agentAssets.drawer.platformOverview')">
              <section class="detail-section">
                <a-alert type="info" :message="$t('agentAssets.drawer.platformHint')" />
              </section>
              <section class="detail-section">
                <h3>{{ $t('agentAssets.drawer.basic') }}</h3>
                <a-descriptions bordered size="small" :column="2">
                  <a-descriptions-item :label="$t('agentAssets.drawer.platformId')">{{ selectedAsset.agent_id }}</a-descriptions-item>
                  <a-descriptions-item :label="$t('agentAssets.drawer.department')">{{ selectedAsset.department_name || '-' }}</a-descriptions-item>
                  <a-descriptions-item :label="$t('agentAssets.drawer.owner')">{{ selectedAsset.owner || '-' }}</a-descriptions-item>
                  <a-descriptions-item :label="$t('agentAssets.drawer.createdAt')">{{ selectedAsset.created_at ? formatDateTime(selectedAsset.created_at) : '-' }}</a-descriptions-item>
                  <a-descriptions-item :label="$t('agentAssets.drawer.updatedAt')">{{ selectedAsset.updated_at ? formatDateTime(selectedAsset.updated_at) : '-' }}</a-descriptions-item>
                  <a-descriptions-item :label="$t('agentAssets.drawer.description')" :span="2">{{ selectedAsset.description || '-' }}</a-descriptions-item>
                </a-descriptions>
              </section>
            </a-tab-pane>
            <a-tab-pane key="skills" :tab="`${$t('agentAssets.drawer.assignedSkills')} (${platformSkills.length})`">
              <a-empty v-if="!platformSkills.length" :description="$t('agentAssets.drawer.noAssignedSkills')" />
              <a-list v-else bordered :data-source="platformSkills">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta :title="item.name" :description="item.id" />
                    <a-tag :color="item.status === 'DEPLOYED' ? 'blue' : 'green'">{{ skillStatusText(item.status) }}</a-tag>
                  </a-list-item>
                </template>
              </a-list>
            </a-tab-pane>
            <a-tab-pane key="mcp" :tab="$t('agentMcp.count', { count: selectedAsset.allowed_mcp_gateways?.length || 0 })">
              <AgentMcpAccess :key="selectedAsset.agent_id" :agent-pk="selectedAsset.managed_agent_pk" />
            </a-tab-pane>
            <a-tab-pane v-if="selectedAsset.instances?.length" key="local-assets" :tab="$t('localAssets.instances')">
              <section v-for="instance in selectedAsset.instances" :key="`${instance.client_id}:${instance.local_agent_id}`" class="detail-section">
                <h3>{{ instance.client_name }} · {{ instance.local_agent_id }}</h3>
                <AgentLocalAssets :inventory="instance.asset_inventory" :skills="instance.skills" />
              </section>
            </a-tab-pane>
            <a-tab-pane key="model" :tab="$t('agentAssets.drawer.modelAccess')">
              <a-descriptions bordered size="small" :column="2">
                <a-descriptions-item :label="$t('agentAssets.drawer.defaultModel')">{{ selectedAsset.default_model || $t('agentAssets.drawer.notConfigured') }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.gatewaySource')">{{ gatewaySourceText(selectedAsset) }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.runtimeCredential')" :span="2">{{ selectedAsset.runtime_token_id ? `${$t('agentIntegration.linkedCredential')} · ${selectedAsset.runtime_token_name || selectedAsset.runtime_token_id}` : $t('agentAssets.drawer.notConfigured') }}</a-descriptions-item>
              </a-descriptions>
            </a-tab-pane>
          </a-tabs>
        </template>

      </template>
    </a-drawer>

    <a-modal v-model:open="agentVisible" wrap-class-name="agent-registration-modal" :title="editingAgentId && !createdDraft ? $t('legacy.1k1efeu') : $t('agentIntegration.registerTitle')" width="760px" :mask-closable="!createdDraft && !submitting && !preparingExternal" :closable="!submitting && !preparingExternal" :keyboard="!submitting && !preparingExternal" :cancel-button-props="{ disabled: submitting || preparingExternal }" :ok-button-props="{ disabled: submitting || preparingExternal }" :ok-text="pageAllowed('/runtime') ? $t('agentIntegration.saveAndGuide') : undefined" @ok="saveAgent" @cancel="cancelAgentModal" :confirm-loading="submitting">
      <a-alert type="info" show-icon :message="$t('agentIntegration.form.intro')" />
      <a-button v-if="pageAllowed('/runtime')" type="link" class="local-guide-link" @click="openClientGuide">{{ $t('agentIntegration.form.local') }}</a-button>
      <a-form layout="vertical" :model="agentForm" :disabled="submitting || preparingExternal">
        <h3>{{ $t('agentIntegration.form.basic') }}</h3>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="Agent ID" required :extra="$t('agentIntegration.form.idHelp')">
              <a-input v-model:value="agentForm.agent_id" placeholder="risk-screening-agent" :disabled="editingOriginType === 'client_discovery'" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.hzx914')" required>
              <a-input v-model:value="agentForm.name" :placeholder="$t('legacy.qu7pc2')" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.1sjdnv')">
              <a-select v-model:value="agentForm.department_group_id" allow-clear :placeholder="$t('legacy.18m3h1b')">
                <a-select-option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.1ccx4t4')" :extra="$t('agentIntegration.form.statusHelp')">
              <a-select v-model:value="agentForm.status">
                <a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option>
                <a-select-option value="disabled">{{ $t("legacy.1dcdrxo") }}</a-select-option>
                <a-select-option value="draft">{{ $t("legacy.oc54qp") }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.17eokaf')">
              <a-select
                v-model:value="agentForm.owner"
                show-search
                allow-clear
                option-filter-prop="label"
                :placeholder="$t('legacy.vopx5l')"
              >
                <a-select-option
                  v-for="user in activeUsers"
                  :key="user.id"
                  :value="user.username"
                  :label="userOptionLabel(user)"
                >
                  {{ userOptionLabel(user) }}
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>
        <a-divider />
        <h3>{{ $t('agentIntegration.form.model') }}</h3>
        <p class="field-hint">{{ $t('agentIntegration.form.modelHelp') }}</p>
        <a-form-item :label="$t('externalModel.source')">
          <a-radio-group v-model:value="agentForm.default_model_source" button-style="solid" @change="handleModelSourceChange">
            <a-radio-button value="internal">{{ $t('externalModel.internal') }}</a-radio-button>
            <a-radio-button v-if="hasAccess('external_gateways:view')" value="external_gateway">{{ $t('externalModel.external') }}</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <template v-if="agentForm.default_model_source === 'external_gateway'">
          <a-form-item :label="$t('externalModel.gatewaySelect')" required>
            <a-select v-model:value="agentForm.external_gateway_id" :disabled="preparingExternal || createdDraft" @change="handleGatewayChange">
              <a-select-option v-for="gateway in externalGateways" :key="gateway.id" :value="gateway.id">{{ gateway.name }}</a-select-option>
            </a-select>
          </a-form-item>
          <a-alert type="info" show-icon :message="$t('externalModel.platformPrepareHint')" style="margin-bottom: 12px" />
          <a-button :loading="preparingExternal" :disabled="!agentForm.external_gateway_id || submitting" @click="prepareExternalModels">
            {{ $t(externalModels.length ? 'externalModel.refresh' : 'externalModel.prepare') }}
          </a-button>
          <div v-if="externalCatalogInfo" class="field-hint external-ready">
            {{ $t('externalModel.modelCount', { count: externalModels.length }) }} · {{ $t('externalModel.agent', { id: externalCatalogInfo.external_agent_id }) }} · {{ $t('externalModel.keyId', { id: externalCatalogInfo.key_id }) }}
          </div>
        </template>
        <a-form-item :label="$t('legacy.9tnz09')" :required="agentForm.default_model_source === 'external_gateway'">
          <a-select v-model:value="agentForm.default_model" allow-clear show-search :disabled="agentForm.default_model_source === 'external_gateway' && !externalModels.length" :placeholder="$t(agentForm.default_model_source === 'external_gateway' && !externalModels.length ? 'externalModel.selectAfterRefresh' : 'legacy.13jl62z')">
            <a-select-option v-for="model in selectableModels" :key="model.name || model.id" :value="model.name || model.id">
              {{ modelLabel(model) }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-divider />
        <h3>{{ $t('agentIntegration.form.skills') }}</h3>
        <a-form-item :label="$t('legacy.zdumf2')">
          <a-select
            v-model:value="agentForm.skill_refs"
            mode="multiple"
            show-search
            allow-clear
            :placeholder="$t('legacy.140f3cr')"
            option-filter-prop="label"
            :filter-option="filterOption"
          >
            <a-select-option
              v-for="skill in skillOptions"
              :key="skill.value"
              :value="skill.value"
              :label="skillOptionLabel(skill)"
            >
              {{ skillOptionLabel(skill) }}
            </a-select-option>
          </a-select>
          <div class="field-hint">{{ $t('agentIntegration.form.skillHelp') }}</div>
        </a-form-item>
        <h3>{{ $t('agentMcp.optional') }}</h3>
        <p class="field-hint">{{ $t('agentMcp.intro') }}</p>
        <a-form-item :label="$t('agentMcp.gateways')">
          <AgentMcpGateways v-model="agentForm.allowed_mcp_gateways" :disabled="submitting || preparingExternal" />
          <p class="field-hint">{{ $t('agentMcp.scope') }}</p>
        </a-form-item>
        <a-form-item :label="$t('legacy.1kxyax6')">
          <a-textarea v-model:value="agentForm.description" :rows="3" :placeholder="$t('legacy.1zcrx6')" />
        </a-form-item>
      </a-form>
    </a-modal>


  </div>
</template>

<script setup>
import { modelLabel } from '../utils/modelLabels'
import { formatDateTime } from '../utils/format'
import { can as hasAccess, pageAllowed } from '../access'
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, reactive, ref, watch } from 'vue'
import AgentDiscoveredWorkspace from '../components/AgentDiscoveredWorkspace.vue'
import AgentProductLogo from '../components/AgentProductLogo.vue'
import AgentMcpGateways from '../components/AgentMcpGateways.vue'
import AgentMcpAccess from '../components/AgentMcpAccess.vue'
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { InfoCircleOutlined } from '@ant-design/icons-vue'
import AgentLocalAssets from '../components/AgentLocalAssets.vue'

import {
  createAgent,
  deleteAgent,
  listAgentAssets,
  listGroups,
  listManagedUsers,
  listExternalAiGateways,
  listModelEndpoints,
  listSkills,
  prepareAgentExternalModelCatalog,
  updateAgent,
} from '../api'

const router = useRouter(), route = useRoute()
const workspaceAsset = ref(null)
const closeWorkspace = () => { workspaceAsset.value = null; const query = { ...route.query }; delete query.agent; delete query.client; delete query.local; router.replace({ query }) }

const { t, locale } = useI18n()
const loading = ref(false)
const assetsLoadFailed = ref(false)
const submitting = ref(false)
const agentVisible = ref(false)
const assetVisible = ref(false)
const selectedAsset = ref(null)
const assetDetailTab = ref('overview')
const editingAgentId = ref(null)
const editingOriginType = ref('platform')
const createdDraft = ref(false)
const agents = ref([])
watch(() => [route.query.agent, agents.value], ([id, items]) => { workspaceAsset.value = items.find(item => item.origin_type === 'client_discovery' && item.agent_id === id) || null })
const assetStats = reactive({ total: 0, platform: 0, client_discovery: 0 })
const groups = ref([])
const users = ref([])
const models = ref([])
const externalGateways = ref([])
const externalModels = ref([])
const externalCatalogInfo = ref(null)
const preparingExternal = ref(false)
const skills = ref([])
const filters = reactive({ origin: ['platform', 'client_discovery'].includes(route.query.origin) ? route.query.origin : 'all', department_group_id: null, status: undefined, q: '' })
const sourceEmptyKey = computed(() => {
  if (assetsLoadFailed.value) return 'agentAssets.loadFailed'
  if (filters.q || filters.status || filters.department_group_id) return 'agentAssets.empty'
  if (filters.origin === 'platform' && !assetStats.platform) return 'agentIntegration.emptyPlatform'
  if (filters.origin === 'client_discovery' && !assetStats.client_discovery) return 'agentIntegration.emptyClient'
  return 'agentAssets.empty'
})
const openGuide = record => { assetVisible.value = false; router.push({ path: '/runtime', query: { scenario: 'custom', agent_id: record.agent_id } }) }
const openClientGuide = async () => {
  if (submitting.value || preparingExternal.value) return
  if (await cancelAgentModal() === false) return
  agentVisible.value = false
  router.push({ path: '/runtime', query: { scenario: 'client' } })
}
const agentForm = reactive({
  agent_id: '',
  name: '',
  department_group_id: null,
  owner: '',
  description: '',
  status: 'active',
  default_model: undefined,
  default_model_source: 'internal',
  external_gateway_id: undefined,
  skill_refs: [],
  allowed_mcp_gateways: [],
  prompt_names: [],
})
const compareAssetText = (a, b) => String(a || '').localeCompare(String(b || ''), locale.value, { numeric: true, sensitivity: 'base' })
const assetSkillCount = record => record.origin_type === 'platform' ? record.skill_names?.length || 0 : record.client_status === 'not_detected' ? -1 : record.discovered_skill_count || 0
const assetTimestamp = record => {
  const value = record.last_seen_at || record.updated_at
  if (!value) return 0
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`) || 0
}
const assetStatusRank = record => ({ draft: 0, active: 1, disabled: 2 }[record.status] ?? 3)
const assetDepartment = record => record.origin_type === 'client_discovery' ? ownerDepartmentText(record) : record.department_name || ''
const columns = computed(() => [
  { title: t('agentAssets.columns.agent'), key: 'agent', width: 210, sorter: (a, b) => compareAssetText(a.name, b.name) },
  { title: t('agentAssets.columns.source'), key: 'source', width: 170, sorter: (a, b) => Number(a.origin_type !== 'platform') - Number(b.origin_type !== 'platform') },
  { title: t('agentAssets.columns.owner'), key: 'owner', width: 180, sorter: (a, b) => compareAssetText(assetDepartment(a), assetDepartment(b)) || compareAssetText(a.owner, b.owner) },
  { title: t('agentAssets.columns.location'), key: 'location', width: 220, sorter: (a, b) => compareAssetText(a.instances?.[0]?.client_name, b.instances?.[0]?.client_name) },
  { title: t('agentAssets.columns.assets'), key: 'assets', width: 220, sorter: (a, b) => assetSkillCount(a) - assetSkillCount(b), sortHelp: 'agentAssets.sorting.assets' },
  { title: t('agentAssets.columns.status'), key: 'status', width: 180, sorter: (a, b) => assetStatusRank(a) - assetStatusRank(b), sortHelp: 'agentAssets.sorting.status' },
  { title: t('agentAssets.columns.lastSeen'), key: 'lastSeen', width: 190, sorter: (a, b) => assetTimestamp(a) - assetTimestamp(b) },
  { title: t('agentAssets.columns.actions'), key: 'actions', width: 110, fixed: 'right' },
])
const activeUsers = computed(() => users.value.filter(item => item.is_active !== false))
const skillOptions = computed(() => skills.value.map((skill, index) => ({
  ...skill,
  value: uniqueOptionValue(skill, 'skill', index),
})))
const selectableModels = computed(() => agentForm.default_model_source === 'external_gateway' ? externalModels.value : models.value)
const platformSkills = computed(() => (selectedAsset.value?.skill_names || []).map((reference, index) => {
  const matched = skills.value.find(item => item.skill_id === reference || item.id === reference || item.name === reference)
  return {
    key: matched?.skill_id || matched?.id || `${reference}:${index}`,
    id: matched?.skill_id || matched?.id || reference,
    name: matched?.name || reference,
    status: matched?.status || 'ASSIGNED',
  }
}))
const statusText = (status) => ({ active: phrase('legacy.5pm2ma'), disabled: phrase('legacy.1dcdrxo'), draft: phrase('legacy.oc54qp') }[status] || status)
const statusColor = (status) => ({ active: 'green', disabled: 'red', draft: 'orange' }[status] || 'default')
const tabLabel = (key, count) => `${t(`agentAssets.tabs.${key}`)} ${count}`
const sourceText = record => t(record.origin_type === 'platform' ? 'agentAssets.source.platform' : 'agentAssets.source.client')
const clientStatusText = status => status ? t(`agentAssets.filters.${status}`) : '-'
const ownerDepartmentText = record => {
  if (record.department_name) return record.department_name
  const owner = users.value.find(item => item.username === record.owner)
  const names = (owner?.group_ids || [])
    .map(groupId => groups.value.find(group => group.id === groupId)?.name)
    .filter(Boolean)
  return names.length ? names.join(' / ') : t('agentAssets.ownerDepartmentMissing')
}
const skillStatusText = status => ({ APPROVED: phrase('legacy.10hmnl2'), DEPLOYED: phrase('legacy.1t00jqn'), ASSIGNED: t('agentAssets.drawer.assigned') }[status] || status)
const agentInitials = record => String(record.channel || record.name || 'A').split(/\s+/).map(item => item[0]).join('').slice(0, 2).toUpperCase()
const instanceLocation = record => {
  const instance = record.instances?.[0]
  if (!instance) return t('agentAssets.locationUnknown')
  const base = `${instance.os} ${instance.arch} · ${clientStatusText(instance.client_status)}`
  return record.instance_count > 1 ? `${base} · ${t('agentAssets.moreInstances', { count: record.instance_count })}` : base
}
const reportedModelState = record => record?.instances?.[0]?.capabilities?.model_config_state || {}
const currentModelText = record => {
  if (record?.origin_type === 'platform') return record.default_model || t('agentIntegration.unset')
  const instance = record?.instances?.[0]
  return reportedModelState(record).model || instance?.applied_model || instance?.desired_model || record?.default_model || t('agentAssets.modelUnknown')
}
const isReportedExternalGateway = record => {
  const state = reportedModelState(record)
  const source = String(state.gateway_source || '').toLowerCase()
  const credentialSource = String(state.credential_source || '').toLowerCase()
  return ['external', 'external_gateway'].includes(source) || credentialSource === 'external_gateway'
}
const reportedGatewayName = record => reportedModelState(record).gateway_name || record?.external_gateway_name || ''
const assetModelText = record => {
  const model = currentModelText(record)
  const gateway = record?.origin_type === 'client_discovery' && isReportedExternalGateway(record) ? reportedGatewayName(record) : ''
  return gateway ? `${model} · ${gateway}` : model
}
const gatewaySourceText = record => {
  if (record.origin_type === 'client_discovery') {
    if (isReportedExternalGateway(record)) {
      const gateway = reportedGatewayName(record)
      return `${t('agentAssets.drawer.externalGateway')}${gateway ? ` · ${gateway}` : ''}`
    }
    const state = reportedModelState(record)
    const source = String(state.gateway_source || '').toLowerCase()
    const credentialSource = String(state.credential_source || '').toLowerCase()
    if (source === 'internal' || credentialSource === 'agent_runtime') return t('agentAssets.drawer.builtInGateway')
    if (record.default_model_source === 'external_gateway') return `${t('agentAssets.drawer.externalGateway')}${record.external_gateway_name ? ` · ${record.external_gateway_name}` : ''}`
    return t('agentAssets.drawer.localConfig')
  }
  if (record.default_model_source === 'external_gateway') return `${t('agentAssets.drawer.externalGateway')}${record.external_gateway_name ? ` · ${record.external_gateway_name}` : ''}`
  if (record.default_model) return t('agentAssets.drawer.builtInGateway')
  return t('agentAssets.drawer.localConfig')
}
const userOptionLabel = (user) => `${user.username}${user.email ? `（${user.email}）` : ''}`
const uniqueOptionValue = (item, type, index) => `${type}:${item.skill_id || item.id || index}:${index}`
const skillOptionLabel = (skill) => {
  const statusLabel = skill.status === 'DEPLOYED' ? phrase('legacy.1t00jqn') : phrase('legacy.10hmnl2')
  const id = skill.skill_id || skill.id
  return `${skill.name}（${statusLabel}${id ? ` · ${id}` : ''}）`
}
const filterOption = (input, option) =>
  String(option?.label || option?.value || '').toLowerCase().includes(String(input || '').toLowerCase())
const findRefsByNames = (options, names = []) => {
  const used = new Set()
  return names.map((name) => {
    const option = options.find(item => (item.skill_id === name || item.name === name) && !used.has(item.value))
    if (!option) return null
    used.add(option.value)
    return option.value
  }).filter(Boolean)
}
const skillIdsFromRefs = (options, refs = []) =>
  refs.map(ref => {
    const item = options.find(option => option.value === ref)
    return item?.skill_id || item?.id || item?.name
  }).filter(Boolean)
const fetchAgentAssets = async () => {
  loading.value = true
  assetsLoadFailed.value = false
  try {
    const result = await listAgentAssets({
      origin: filters.origin === 'all' ? undefined : filters.origin,
      department_group_id: filters.department_group_id || undefined,
      status: filters.status || undefined,
      q: filters.q?.trim() || undefined,
    })
    agents.value = result.items || []
    Object.assign(assetStats, result.stats || { total: 0, platform: 0, client_discovery: 0 })
  } catch (error) {
    assetsLoadFailed.value = true
    message.error(error.response?.data?.detail || t('agentAssets.loadFailed'))
  } finally {
    loading.value = false
  }
}

const handleOriginChange = async (origin) => {
  if (origin === 'client_discovery') filters.department_group_id = null
  await router.replace({ query: { ...route.query, origin } })
  await fetchAgentAssets()
}

watch(() => route.query.origin, origin => {
  const next = ['platform', 'client_discovery'].includes(origin) ? origin : 'all'
  if (filters.origin === next) return
  filters.origin = next
  if (next === 'client_discovery') filters.department_group_id = null
  fetchAgentAssets()
})

const loadOptions = async () => {
  const [groupRes, userRes, modelRes, skillRes] = await Promise.all([
    hasAccess('groups:view') ? listGroups() : [],
    hasAccess('users:view') ? listManagedUsers() : [],
    hasAccess('models:view') ? listModelEndpoints() : [],
    hasAccess('skills:view') ? listSkills({ status: 'APPROVED,DEPLOYED' }) : [],
  ])
  groups.value = groupRes
  users.value = userRes
  models.value = modelRes
  skills.value = Array.isArray(skillRes.items) ? skillRes.items : skillRes
}

const loadExternalGateways = async () => {
  if (!hasAccess('external_gateways:view')) {
    externalGateways.value = []
    return
  }
  externalGateways.value = (await listExternalAiGateways() || []).filter(item => item.enabled)
}

const resetFilters = async () => {
  Object.assign(filters, { origin: 'all', department_group_id: null, status: undefined, q: '' })
  const query = { ...route.query }; delete query.origin
  await router.replace({ query })
  await fetchAgentAssets()
}

const openAsset = (record) => {
  if (record.origin_type === 'client_discovery') { workspaceAsset.value = record; router.push({ query: { ...route.query, agent: record.agent_id } }); return }
  selectedAsset.value = record
  assetDetailTab.value = 'overview'
  assetVisible.value = true
}

const editSelectedAsset = () => {
  const record = selectedAsset.value
  assetVisible.value = false
  if (record) openAgent(record)
}

const openAgent = (record = null) => {
  editingAgentId.value = record?.managed_agent_pk || record?.id || null
  editingOriginType.value = record?.origin_type || 'platform'
  createdDraft.value = false
  externalModels.value = []
  externalCatalogInfo.value = null
  Object.assign(agentForm, {
    agent_id: record?.agent_id || '',
    name: record?.name || '',
    department_group_id: record?.department_group_id || null,
    owner: record?.owner || '',
    description: record?.description || '',
    status: record?.status || 'active',
    default_model: record?.default_model || undefined,
    default_model_source: record?.default_model_source || 'internal',
    external_gateway_id: record?.external_gateway_id || undefined,
    skill_refs: findRefsByNames(skillOptions.value, record?.skill_names || []),
    allowed_mcp_gateways: [...(record?.allowed_mcp_gateways || [])],
    prompt_names: record?.prompt_names || [],
  })
  agentVisible.value = true
}

const baseAgentPayload = (status = agentForm.status) => ({
  agent_id: agentForm.agent_id.trim(),
  name: agentForm.name.trim(),
  department_group_id: agentForm.department_group_id,
  owner: agentForm.owner,
  description: agentForm.description,
  status,
  default_model: agentForm.default_model || null,
  default_model_source: agentForm.default_model_source,
  external_gateway_id: agentForm.default_model_source === 'external_gateway' ? agentForm.external_gateway_id : null,
  skill_names: skillIdsFromRefs(skillOptions.value, agentForm.skill_refs),
  allowed_mcp_gateways: [...agentForm.allowed_mcp_gateways],
  prompt_names: agentForm.prompt_names || [],
})

const validateAgentIdentity = () => {
  if (!agentForm.agent_id.trim() || !agentForm.name.trim()) {
    message.warning(t('agentAssets.identityRequired'))
    return false
  }
  return true
}

const handleModelSourceChange = () => {
  agentForm.default_model = undefined
  externalModels.value = []
  externalCatalogInfo.value = null
  if (agentForm.default_model_source === 'internal') agentForm.external_gateway_id = undefined
}

const handleGatewayChange = () => {
  agentForm.default_model = undefined
  externalModels.value = []
  externalCatalogInfo.value = null
}

const prepareExternalModels = async () => {
  if (preparingExternal.value || submitting.value || !validateAgentIdentity()) return
  if (!agentForm.external_gateway_id) return message.warning(t('externalModel.gatewayRequired'))
  preparingExternal.value = true
  try {
    if (!editingAgentId.value) {
      const draft = await createAgent({ ...baseAgentPayload('draft'), default_model: null })
      editingAgentId.value = draft.id
      createdDraft.value = true
    }
    const result = await prepareAgentExternalModelCatalog(editingAgentId.value, { gateway_id: agentForm.external_gateway_id })
    externalModels.value = (result.models || []).map(item => ({ ...item, name: item.id }))
    externalCatalogInfo.value = result
    if (!externalModels.value.some(item => item.id === agentForm.default_model)) agentForm.default_model = undefined
    message.success(t('externalModel.ready'))
  } catch (error) {
    message.error(error.response?.data?.detail || t('externalModel.loadFailed'))
  } finally {
    preparingExternal.value = false
  }
}

const cancelAgentModal = async () => {
  if (submitting.value || preparingExternal.value) return false
  if (!createdDraft.value || !editingAgentId.value) return
  try {
    await deleteAgent(editingAgentId.value)
    createdDraft.value = false
    editingAgentId.value = null
  } catch (error) {
    agentVisible.value = true
    message.error(error.response?.data?.detail || t('externalModel.draftCleanupFailed'))
    return false
  }
}

const saveAgent = async () => {
  if (submitting.value || preparingExternal.value) return
  if (!validateAgentIdentity()) return
  if (agentForm.default_model_source === 'external_gateway') {
    if (!agentForm.external_gateway_id) return message.warning(t('externalModel.gatewayRequired'))
    if (!externalModels.value.length) return message.warning(t('externalModel.selectAfterRefresh'))
    if (!agentForm.default_model) return message.warning(t('externalModel.modelRequired'))
  }
  submitting.value = true
  try {
    const payload = baseAgentPayload()
    let savedAgent
    if (editingAgentId.value) savedAgent = await updateAgent(editingAgentId.value, payload)
    else savedAgent = await createAgent(payload)
    createdDraft.value = false
    agentVisible.value = false
    await fetchAgentAssets()
    if (pageAllowed('/runtime')) {
      const scenario = ['custom', 'model', 'mcp', 'verifier'].includes(route.query.scenario) ? route.query.scenario : 'custom'
      const query = { scenario, agent_id: savedAgent.agent_id }
      if (typeof route.query.capabilities === 'string' && route.query.capabilities) {
        query.capabilities = [...new Set([...route.query.capabilities.split(','), ...(savedAgent.allowed_mcp_gateways?.length ? ['mcp'] : [])])].join(',')
      }
      router.push({ path: '/runtime', query })
    }

  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1b0loi0'))
  } finally {
    submitting.value = false
  }
}

const handleDelete = async (record) => {
  await deleteAgent(record.managed_agent_pk || record.id)
  message.success(phrase('legacy.1s2wkng'))
  await fetchAgentAssets()
}

onMounted(async () => {
  await Promise.all([loadOptions(), loadExternalGateways(), fetchAgentAssets()])
  if (typeof route.query.detail === 'string') {
    const record = agents.value.find(item => item.agent_id === route.query.detail && item.origin_type === 'platform')
    if (record) { openAsset(record); assetDetailTab.value = route.query.detail_tab === 'mcp' ? 'mcp' : 'overview' }
  }
  if (route.query.create === '1' && hasAccess('agents:create')) {
    openAgent()
    const query = { ...route.query }; delete query.create
    await router.replace({ query })
  } else if (typeof route.query.edit === 'string' && hasAccess('agents:update')) {
    const record = agents.value.find(item => item.agent_id === route.query.edit && item.origin_type === 'platform')
    if (record) openAgent(record)
    const query = { ...route.query }; delete query.edit
    await router.replace({ query })
  }
})
</script>

<style scoped>
.agent-asset-table :deep(th) { white-space: normal; word-break: normal; }
.asset-sort-heading { display: inline-flex; align-items: center; gap: 6px; }
.asset-sort-info { display: inline-flex; align-items: center; justify-content: center; padding: 3px; border: 0; border-radius: 4px; background: transparent; color: #626b78; cursor: help; }
.asset-sort-info:hover { color: #245eea; background: #eef4ff; }
.asset-sort-info:focus-visible { outline: 2px solid #245eea; outline-offset: 2px; }
.asset-sort-help { width: 300px; max-width: calc(100vw - 64px); font-size: 13px; line-height: 1.65; white-space: normal; color: #526078; }
.asset-sort-help strong { color: #253248; }
.asset-sort-help p { margin: 6px 0 0; }
.asset-sort-help p:last-child { border-top: 1px solid #e8edf3; margin-top: 12px; padding-top: 10px; }
.agent-list-card :deep(.ant-page-header-heading) { flex-wrap: wrap; gap: 12px; }
:global(.agent-registration-modal .ant-modal-footer) { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
:global(.agent-registration-modal .ant-modal-footer .ant-btn) { margin-inline-start: 0; height: auto; min-height: 32px; white-space: normal; }

.source-help { margin: 16px 18px 0; }
.source-empty { padding: 20px; }
.local-guide-link { height: auto; white-space: normal; margin: 8px 0 16px; padding-left: 0; }

.agent-workspace-page { height: 100%; min-height: 0; overflow: hidden; }
.agent-name {
  font-weight: 600;
}

.muted {
  color: #7a869a;
  font-size: 12px;
}

.asset-stats,
.asset-list-card {
  margin-top: 16px;
}

.asset-tabs {
  padding: 0 18px;
}

.asset-tabs :deep(.ant-tabs-content-holder) {
  display: none;
}

.asset-tabs :deep(.ant-tabs-nav) {
  margin-bottom: 0;
}

.asset-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  border-bottom: 1px solid #f0f0f0;
}

.department-filter {
  width: 180px;
}

.status-filter {
  width: 150px;
}

.asset-search {
  width: min(320px, 32vw);
}

.agent-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.agent-mark {
  display: grid;
  flex: 0 0 36px;
  width: 36px;
  height: 36px;
  place-items: center;
  color: #315a9d;
  background: #edf3fd;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
}

.agent-mark.client {
  padding: 6px;
  color: #137b73;
  background: #eaf8f5;
}

.drawer-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 16px;
}

.drawer-summary {
  margin-bottom: 12px;
}

.summary-card {
  min-height: 74px;
  padding: 11px 12px;
  background: #fafbfc;
  border: 1px solid #e6eaf0;
  border-radius: 8px;
}

.summary-card span,
.summary-card strong {
  display: block;
}

.summary-card span {
  color: #7a869a;
  font-size: 12px;
}

.summary-card strong {
  margin-top: 6px;
  overflow-wrap: anywhere;
}

.detail-section {
  margin-bottom: 22px;
}

.detail-section h3 {
  margin-bottom: 10px;
  font-size: 14px;
}

.external-ready {
  margin-top: 8px;
}

@media (max-width: 900px) {
  .asset-toolbar {
    align-items: stretch;
    flex-wrap: wrap;
  }

  .department-filter,
  .status-filter,
  .asset-search {
    width: 100%;
  }
}
</style>
