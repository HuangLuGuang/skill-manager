<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.5chjsa')" :sub-title="$t('agentAssets.subtitle')">
          <template #extra>
            <a-button @click="flowVisible = true">{{ $t("legacy.udb4df") }}</a-button>
            <a-button v-if="hasAccess('agents:create')" type="primary" @click="openAgent()">{{ $t("legacy.1krdxw3") }}</a-button>
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
          </a-select>
          <a-input v-model:value="filters.q" :placeholder="$t('agentAssets.filters.search')" class="asset-search" allow-clear @pressEnter="fetchAgentAssets" />
          <a-button type="primary" @click="fetchAgentAssets" :loading="loading">{{ $t("legacy.16mfmhy") }}</a-button>
          <a-button @click="resetFilters" :disabled="loading">{{ $t("legacy.1wq9feq") }}</a-button>
        </div>

        <a-table :data-source="agents" :columns="columns" :scroll="{ x: 1180 }" rowKey="asset_key" :loading="loading" :pagination="{ pageSize: 10, showSizeChanger: true }">
          <template #emptyText>{{ $t('agentAssets.empty') }}</template>
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'agent'">
              <div class="agent-cell">
                <div class="agent-mark" :class="{ client: record.origin_type === 'client_discovery' }">{{ agentInitials(record) }}</div>
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
                <div>{{ $t('agentAssets.platformRuntime') }}</div>
              </template>
            </template>
            <template v-else-if="column.key === 'assets'">
              <div>{{ assetModelText(record) }}</div>
              <div class="muted">{{ record.origin_type === 'platform' ? $t('agentAssets.assignedSkillSummary', { count: record.skill_names?.length || 0 }) : $t('agentAssets.discoveredSkillSummary', { count: record.discovered_skill_count || 0 }) }}</div>
            </template>
            <template v-else-if="column.key === 'status'">
              <a-space direction="vertical" size="small">
                <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
                <span v-if="record.instance_count" class="muted">{{ $t('agentAssets.onlineInstances', { online: record.online_instance_count, total: record.instance_count }) }}</span>
              </a-space>
            </template>
            <template v-else-if="column.key === 'lastSeen'">{{ record.last_seen_at || record.updated_at ? formatDateTime(record.last_seen_at || record.updated_at) : '-' }}</template>
            <template v-else-if="column.key === 'actions'">
              <a-space wrap>
                <a @click="openAsset(record)">{{ $t('agentAssets.detail') }}</a>
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
        <a-space>
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
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.runtimeCredential') }}</span><strong>{{ selectedAsset.runtime_token_id ? $t('agentAssets.drawer.configured') : $t('agentAssets.drawer.notConfigured') }}</strong></div></a-col>
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
            <a-tab-pane key="model" :tab="$t('agentAssets.drawer.modelAccess')">
              <a-descriptions bordered size="small" :column="2">
                <a-descriptions-item :label="$t('agentAssets.drawer.defaultModel')">{{ selectedAsset.default_model || $t('agentAssets.drawer.notConfigured') }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.gatewaySource')">{{ gatewaySourceText(selectedAsset) }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.runtimeCredential')" :span="2">{{ selectedAsset.runtime_token_id ? `${$t('agentAssets.drawer.configured')} · ${selectedAsset.runtime_token_name || selectedAsset.runtime_token_id}` : $t('agentAssets.drawer.notConfigured') }}</a-descriptions-item>
              </a-descriptions>
            </a-tab-pane>
          </a-tabs>
        </template>

        <template v-else>
          <a-row :gutter="[10, 10]" class="drawer-summary">
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.clientStatus') }}</span><strong>{{ clientStatusText(selectedAsset.client_status) }}</strong></div></a-col>
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.skillCount') }}</span><strong>{{ selectedAsset.discovered_skill_count }}</strong></div></a-col>
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.currentModel') }}</span><strong>{{ currentModelText(selectedAsset) }}</strong></div></a-col>
            <a-col :xs="12" :md="6"><div class="summary-card"><span>{{ $t('agentAssets.drawer.lastScan') }}</span><strong>{{ latestScanAt ? formatDateTime(latestScanAt) : '-' }}</strong></div></a-col>
          </a-row>

          <a-tabs v-model:activeKey="assetDetailTab">
          <a-tab-pane key="overview" :tab="$t('agentAssets.drawer.overview')">
            <section class="detail-section">
              <h3>{{ $t('agentAssets.drawer.identity') }}</h3>
              <a-alert type="info" :message="assetIdentityHint" />
            </section>
            <section class="detail-section">
              <h3>{{ $t('agentAssets.drawer.basic') }}</h3>
              <a-descriptions bordered size="small" :column="2">
                <a-descriptions-item :label="$t('agentAssets.drawer.platformId')">{{ selectedAsset.agent_id }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.localId')">{{ primaryInstance?.local_agent_id || '-' }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.typeVersion')">{{ primaryInstance ? `${primaryInstance.agent_type} / ${primaryInstance.agent_version || '-'}` : selectedAsset.channel || '-' }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.discoverySource')">{{ selectedAsset.origin_type === 'client_discovery' ? $t('agentAssets.drawer.clientReport') : $t('agentAssets.source.platform') }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.client')">{{ primaryInstance?.client_name || '-' }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.environment')">{{ primaryInstance ? `${primaryInstance.os} / ${primaryInstance.arch}` : '-' }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.installPath')">{{ primaryInstance?.install_path || '-' }}</a-descriptions-item>
                <a-descriptions-item :label="$t('agentAssets.drawer.skillsPath')">{{ primaryInstance?.skills_path || '-' }}</a-descriptions-item>
              </a-descriptions>
            </section>
          </a-tab-pane>
          <a-tab-pane key="skills" :tab="`${$t('agentAssets.drawer.skills')} (${detailSkills.length})`">
            <a-table :data-source="detailSkills" :columns="skillColumns" row-key="key" size="small" :pagination="false">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'localStatus'"><a-tag>{{ $t('agentAssets.drawer.localInstalled') }}</a-tag></template>
                <template v-else-if="column.key === 'certification'"><a-tag :color="record.signature ? 'green' : 'orange'">{{ record.signature ? record.status : $t('legacy.1rfhupd') }}</a-tag></template>
                <template v-else-if="column.key === 'verifiedAt'">{{ record.verified_at ? formatDateTime(record.verified_at) : '-' }}</template>
              </template>
            </a-table>
          </a-tab-pane>
          <a-tab-pane key="model" :tab="$t('agentAssets.drawer.model')">
            <a-descriptions bordered size="small" :column="2">
              <a-descriptions-item :label="$t('agentAssets.drawer.modelStatus')">{{ modelConfigStatusText(primaryInstance?.model_config_status) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('agentAssets.drawer.currentModel')">{{ currentModelText(selectedAsset) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('agentAssets.drawer.gatewaySource')">{{ gatewaySourceText(selectedAsset) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('agentAssets.drawer.autoApply')">{{ primaryInstance?.capabilities?.model_config_auto_apply ? $t('agentAssets.drawer.supported') : $t('agentAssets.drawer.unsupported') }}</a-descriptions-item>
              <a-descriptions-item :label="$t('agentAssets.drawer.credentialSource')">{{ credentialSourceText(selectedAsset) }}</a-descriptions-item>
            </a-descriptions>
          </a-tab-pane>
          <a-tab-pane key="evidence" :tab="$t('agentAssets.drawer.evidence')">
            <h3>{{ $t('agentAssets.drawer.evidenceTitle') }}</h3>
            <a-timeline>
              <a-timeline-item v-for="instance in selectedAsset.instances" :key="`${instance.client_id}:${instance.local_agent_id}:scan`">
                <div>{{ $t('agentAssets.drawer.scannedAt') }}</div>
                <div class="muted">{{ instance.client_name }} · {{ formatDateTime(instance.last_scanned_at) }}</div>
              </a-timeline-item>
              <a-timeline-item v-if="selectedAsset.origin_type === 'client_discovery'">
                <div>{{ $t('agentAssets.drawer.discoveredAt') }}</div>
                <div class="muted">{{ selectedAsset.created_at ? formatDateTime(selectedAsset.created_at) : '-' }}</div>
              </a-timeline-item>
            </a-timeline>
          </a-tab-pane>
          </a-tabs>
        </template>
      </template>
    </a-drawer>

    <a-modal v-model:open="agentVisible" :title="editingAgentId && !createdDraft ? $t('legacy.1k1efeu') : $t('legacy.1krdxw3')" width="760px" :mask-closable="!createdDraft" @ok="saveAgent" @cancel="cancelAgentModal" :confirm-loading="submitting">
      <a-form layout="vertical" :model="agentForm">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="Agent ID" required>
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
            <a-form-item :label="$t('legacy.1ccx4t4')">
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
          <div class="field-hint">{{ $t("legacy.1ienetp") }}</div>
        </a-form-item>
        <a-alert
          type="info"
          show-icon
          :message="$t('legacy.ybzs30')"
          style="margin-bottom: 16px"
        />
        <a-form-item :label="$t('legacy.1kxyax6')">
          <a-textarea v-model:value="agentForm.description" :rows="3" :placeholder="$t('legacy.1zcrx6')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="flowVisible" :title="$t('legacy.10eib88')" width="980px" :footer="null">
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="12">
          <a-card size="small" :title="$t('legacy.1laqeus')">
            <a-steps size="small" direction="vertical" :current="3">
              <a-step :title="$t('legacy.knj41c')" :description="$t('legacy.1ecffk1')" />
              <a-step :title="$t('legacy.5zetdq')" :description="$t('legacy.ggcbgt')" />
              <a-step :title="$t('legacy.mxm4hl')" :description="$t('legacy.wfusa5')" />
              <a-step :title="$t('legacy.hkysa4')" :description="$t('legacy.3hftou')" />
            </a-steps>
          </a-card>
        </a-col>
        <a-col :xs="24" :lg="12">
          <a-card size="small" :title="$t('legacy.1fz7t0k')">
            <a-steps size="small" direction="vertical" :current="4">
              <a-step :title="$t('legacy.61qni9')" :description="$t('legacy.16rumca')" />
              <a-step :title="$t('legacy.1hfbt5h')" :description="$t('legacy.ybnv0i')" />
              <a-step :title="$t('legacy.1odwfha')" :description="$t('legacy.1giz277')" />
              <a-step :title="$t('legacy.1a7xapv')" :description="$t('legacy.1noips3')" />
              <a-step :title="$t('legacy.13omz3w')" :description="$t('legacy.1vl9n7k')" />
            </a-steps>
          </a-card>
        </a-col>
      </a-row>
      <a-alert
        type="info"
        show-icon
        class="flow-note"
        :message="$t('legacy.2lwr8u')"
        :description="$t('legacy.1lk2300')"
      />
      <a-card size="small" :title="$t('legacy.3ct5nb')" class="flow-gateway-card">
        <a-steps size="small" :current="4">
          <a-step :title="$t('legacy.15teb0h')" :description="$t('legacy.1bobpp0')" />
          <a-step :title="$t('legacy.17lmhaa')" :description="$t('legacy.1yydulr')" />
          <a-step :title="$t('legacy.ua7bgb')" :description="$t('legacy.19qufvh')" />
          <a-step :title="$t('legacy.qiw836')" :description="$t('legacy.1vcdl0n')" />
          <a-step :title="$t('legacy.46x8kr')" :description="$t('legacy.lw1t0f')" />
        </a-steps>
      </a-card>
      <a-space class="flow-actions" wrap>
        <a-button @click="router.push('/submit')">{{ $t("legacy.knj41c") }}</a-button>
        <a-button @click="router.push('/agents')">{{ $t("legacy.61qni9") }}</a-button>
        <a-button @click="router.push('/credentials')">{{ $t("legacy.qiw836") }}</a-button>
        <a-button @click="router.push('/model-gateway/models')">{{ $t("legacy.1jabg1u") }}</a-button>
        <a-button type="primary" @click="router.push('/runtime')">{{ $t("legacy.t46zf7") }}</a-button>
      </a-space>
    </a-modal>
  </div>
</template>

<script setup>
import { modelLabel } from '../utils/modelLabels'
import { formatDateTime } from '../utils/format'
import { can as hasAccess } from '../access'
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'

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

const router = useRouter()
const { t, te } = useI18n()
const loading = ref(false)
const submitting = ref(false)
const agentVisible = ref(false)
const flowVisible = ref(false)
const assetVisible = ref(false)
const selectedAsset = ref(null)
const assetDetailTab = ref('overview')
const editingAgentId = ref(null)
const editingOriginType = ref('platform')
const createdDraft = ref(false)
const agents = ref([])
const assetStats = reactive({ total: 0, platform: 0, client_discovery: 0 })
const groups = ref([])
const users = ref([])
const models = ref([])
const externalGateways = ref([])
const externalModels = ref([])
const externalCatalogInfo = ref(null)
const preparingExternal = ref(false)
const skills = ref([])
const filters = reactive({ origin: 'all', department_group_id: null, status: undefined, q: '' })
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
  prompt_names: [],
})
const columns = computed(() => [
  { title: t('agentAssets.columns.agent'), key: 'agent', width: 210 },
  { title: t('agentAssets.columns.source'), key: 'source', width: 170 },
  { title: t('agentAssets.columns.owner'), key: 'owner', width: 160 },
  { title: t('agentAssets.columns.location'), key: 'location', width: 220 },
  { title: t('agentAssets.columns.assets'), key: 'assets', width: 220 },
  { title: t('agentAssets.columns.status'), key: 'status', width: 180 },
  { title: t('agentAssets.columns.lastSeen'), key: 'lastSeen', width: 170 },
  { title: t('agentAssets.columns.actions'), key: 'actions', width: 110, fixed: 'right' },
])
const skillColumns = computed(() => [
  { title: t('agentAssets.drawer.skill'), dataIndex: 'name', key: 'skill' },
  { title: t('agentAssets.drawer.localStatus'), key: 'localStatus', width: 120 },
  { title: t('agentAssets.drawer.certification'), key: 'certification', width: 140 },
  { title: t('agentAssets.drawer.lastVerified'), key: 'verifiedAt', width: 180 },
])
const activeUsers = computed(() => users.value.filter(item => item.is_active !== false))
const skillOptions = computed(() => skills.value.map((skill, index) => ({
  ...skill,
  value: uniqueOptionValue(skill, 'skill', index),
})))
const selectableModels = computed(() => agentForm.default_model_source === 'external_gateway' ? externalModels.value : models.value)
const primaryInstance = computed(() => selectedAsset.value?.instances?.[0] || null)
const platformSkills = computed(() => (selectedAsset.value?.skill_names || []).map((reference, index) => {
  const matched = skills.value.find(item => item.skill_id === reference || item.id === reference || item.name === reference)
  return {
    key: matched?.skill_id || matched?.id || `${reference}:${index}`,
    id: matched?.skill_id || matched?.id || reference,
    name: matched?.name || reference,
    status: matched?.status || 'ASSIGNED',
  }
}))
const latestScanAt = computed(() => {
  const values = (selectedAsset.value?.instances || []).map(item => item.last_scanned_at).filter(Boolean)
  return values.sort().at(-1) || null
})
const detailSkills = computed(() => (selectedAsset.value?.instances || []).flatMap(instance =>
  (instance.skills || []).map((skill, index) => ({
    ...skill,
    key: `${instance.client_id}:${instance.local_agent_id}:${skill.path || skill.name}:${index}`,
    client_name: instance.client_name,
  }))))
const assetIdentityHint = computed(() => {
  if (!selectedAsset.value) return ''
  return t(selectedAsset.value.origin_type === 'client_discovery' ? 'agentAssets.drawer.managedClientHint' : 'agentAssets.drawer.platformHint')
})
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
const modelConfigStatusText = status => {
  if (!status) return t('agentAssets.drawer.notConfigured')
  const key = `agentAssets.drawer.modelStatuses.${status}`
  return te(key) ? t(key) : status
}
const agentInitials = record => String(record.channel || record.name || 'A').split(/\s+/).map(item => item[0]).join('').slice(0, 2).toUpperCase()
const instanceLocation = record => {
  const instance = record.instances?.[0]
  if (!instance) return t('agentAssets.locationUnknown')
  const base = `${instance.os} ${instance.arch} · ${clientStatusText(instance.client_status)}`
  return record.instance_count > 1 ? `${base} · ${t('agentAssets.moreInstances', { count: record.instance_count })}` : base
}
const reportedModelState = record => record?.instances?.[0]?.capabilities?.model_config_state || {}
const currentModelText = record => {
  if (record?.origin_type === 'platform') return record.default_model || t('agentAssets.modelUnknown')
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
const credentialSourceText = record => {
  const source = String(reportedModelState(record).credential_source || '').toLowerCase()
  if (source === 'external_gateway') return t('agentAssets.drawer.externalApiKey')
  if (source === 'agent_runtime') return t('agentAssets.drawer.runtimeCredential')
  return t('agentAssets.drawer.credentialUnknown')
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
    message.error(error.response?.data?.detail || t('agentAssets.loadFailed'))
  } finally {
    loading.value = false
  }
}

const handleOriginChange = async (origin) => {
  if (origin === 'client_discovery') filters.department_group_id = null
  await fetchAgentAssets()
}

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
  await fetchAgentAssets()
}

const openAsset = (record) => {
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
  if (preparingExternal.value || !validateAgentIdentity()) return
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
  if (!createdDraft.value || !editingAgentId.value) return
  try {
    await deleteAgent(editingAgentId.value)
    createdDraft.value = false
    editingAgentId.value = null
  } catch (error) {
    message.error(error.response?.data?.detail || t('externalModel.draftCleanupFailed'))
  }
}

const saveAgent = async () => {
  if (submitting.value) return
  if (!validateAgentIdentity()) return
  if (agentForm.default_model_source === 'external_gateway') {
    if (!agentForm.external_gateway_id) return message.warning(t('externalModel.gatewayRequired'))
    if (!externalModels.value.length) return message.warning(t('externalModel.selectAfterRefresh'))
    if (!agentForm.default_model) return message.warning(t('externalModel.modelRequired'))
  }
  submitting.value = true
  try {
    const payload = baseAgentPayload()
    const wasNew = !editingAgentId.value || createdDraft.value
    let savedAgent
    if (editingAgentId.value) savedAgent = await updateAgent(editingAgentId.value, payload)
    else savedAgent = await createAgent(payload)
    createdDraft.value = false
    agentVisible.value = false
    await fetchAgentAssets()
    if (wasNew) {
      Modal.confirm({
        title: phrase('legacy.x1jtt8'),
        content: phrase('legacy.cpvopf'),
        okText: phrase('legacy.1xo7ne1'),
        cancelText: phrase('legacy.4uzegb'),
        onOk: () => router.push({
          name: 'credentials',
          query: {
            create: 'agent_runtime',
            agent_id: savedAgent.agent_id,
          },
        }),
      })
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
})
</script>

<style scoped>
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

.flow-card {
  margin-top: 8px;
}

.flow-section {
  min-height: 118px;
}

.flow-title {
  font-weight: 600;
  margin-bottom: 12px;
}

.flow-inline-steps :deep(.ant-steps-item-description) {
  max-width: 120px;
}

.flow-summary {
  color: #5f6b7a;
  font-size: 13px;
  margin-top: 14px;
}

.flow-note {
  margin-top: 16px;
}

.flow-gateway-card {
  margin-top: 16px;
}

.flow-actions {
  margin-top: 16px;
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
