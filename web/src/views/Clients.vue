<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.hx2vnc')" :sub-title="$t('legacy.ud53vr')">
          <template #extra>
            <a-button v-if="hasAccess('clients:update')" @click="globalToolPolicyOpen = true">{{ $t('aidr.hooks.scope.title') }}</a-button>
            <a-button v-if="hasAccess('clients:view') || hasAccess('settings:view')" @click="openClassification('')">{{ $t('clientPolicy.globalSettings') }}</a-button>
            <a-button type="primary" @click="installGuideVisible = true">{{ $t("legacy.18h6c95") }}</a-button>
            <a-button :loading="loading" @click="loadClients">{{ $t("legacy.12qo56a") }}</a-button>
          </template>
        </a-page-header>
      </template>

    <a-row :gutter="[16, 16]" class="summary-row">
      <a-col :xs="12" :lg="6"><a-card><a-statistic :title="$t('legacy.1kv2rkb')" :value="clients.length" /></a-card></a-col>
      <a-col :xs="12" :lg="6"><a-card><a-statistic :title="$t('legacy.hf6go')" :value="onlineCount" /></a-card></a-col>
      <a-col :xs="12" :lg="6"><a-card><a-statistic :title="$t('legacy.1k2vlh1')" :value="agentCount" /></a-card></a-col>
      <a-col :xs="12" :lg="6"><a-card><a-statistic :title="$t('legacy.1iz81li')" :value="issueCount" /></a-card></a-col>
    </a-row>

    <section class="table-card">
      <a-table class="client-inventory-table" table-layout="fixed" :scroll="{ x: 1320 }" :columns="columns" :show-sorter-tooltip="false" :data-source="clients" row-key="client_id" :loading="loading" :pagination="{ pageSize: 10 }">
        <template #headerCell="{ column }">
          <span v-if="column.key === 'agents' || column.key === 'skills'" class="inventory-column-heading">
            {{ column.title }}
            <a-popover :trigger="['hover', 'focus', 'click']" placement="topRight" :overlay-style="{ maxWidth: 'calc(100vw - 32px)' }">
              <template #content>
                <div class="inventory-column-help">
                  <dl>
                    <div v-for="metric in column.key === 'agents' ? ['discovered', 'governable'] : ['records', 'sharedSources']" :key="metric">
                      <dt>{{ $t(`clientGovernance.inventoryColumns.${metric}`) }}</dt>
                      <dd>{{ $t(`clientGovernance.inventoryColumns.${metric}Help`) }}</dd>
                    </div>
                  </dl>
                  <p>{{ $t(`clientGovernance.inventoryColumns.${column.key}Sort`) }}</p>
                </div>
              </template>
              <button type="button" class="inventory-help-trigger" :aria-label="$t('clientGovernance.inventoryColumns.helpLabel', { column: column.title })" @click.stop @keydown.stop><InfoCircleOutlined /></button>
            </a-popover>
          </span>
        </template>
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'client'">
            <a role="button" tabindex="0" @click="openDetail(record)" @keydown.enter.prevent="openDetail(record)" @keydown.space.prevent="openDetail(record)">{{ record.name }}</a>
            <div class="muted">{{ record.hostname }} · {{ record.client_id }}</div>
          </template>
          <template v-else-if="column.key === 'platform'">
            <div>{{ record.os }} / {{ record.arch }}</div>
            <div class="muted">{{ governanceShortLabel(record.governance_mode) }} · Client {{ record.client_version }}</div>
          </template>
          <template v-else-if="column.key === 'agents'">
            <dl class="inventory-counts">
              <div><dt>{{ $t('clientGovernance.inventoryColumns.discovered') }}</dt><dd>{{ actualAgentCount(record) }}</dd></div>
              <div class="inventory-count-secondary"><dt>{{ $t('clientGovernance.inventoryColumns.governable') }}</dt><dd>{{ managedAgentCount(record) }}</dd></div>
            </dl>
          </template>
          <template v-else-if="column.key === 'skills'">
            <dl class="inventory-counts">
              <div><dt>{{ $t('clientGovernance.inventoryColumns.records') }}</dt><dd>{{ skillCount(record) }}</dd></div>
              <div v-if="sharedSkillsCount(record)" class="inventory-count-secondary"><dt>{{ $t('clientGovernance.inventoryColumns.sharedSources') }}</dt><dd>{{ sharedSkillsCount(record) }}</dd></div>
            </dl>
          </template>
          <template v-else-if="column.key === 'credentialOwner'">{{ record.registered_by || '-' }}</template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="isOnline(record) ? 'green' : 'default'">{{ isOnline(record) ? $t('legacy.hf6go') : $t('legacy.1hsp9j3') }}</a-tag>
          </template>
          <template v-else-if="column.key === 'lastSeen'">{{ formatTime(record.last_seen_at) }}</template>
          <template v-else-if="column.key === 'action'">
            <a role="button" tabindex="0" @click="openDetail(record)" @keydown.enter.prevent="openDetail(record)" @keydown.space.prevent="openDetail(record)">{{ $t("legacy.10fbkvl") }}</a>
          </template>
        </template>
      </a-table>
    </section>

    </a-card>

    <a-drawer v-model:open="detailVisible" :title="$t('legacy.95lv9i')" width="min(1280px, 100vw)" :destroy-on-close="true" :body-style="fixedDetailActive ? { padding: '12px 16px', overflow: 'hidden', display: 'flex', flexDirection: 'column' } : {}">
      <a-spin :spinning="detailLoading" :wrapper-class-name="fixedDetailActive ? 'session-audit-layout' : ''">
        <template v-if="detail">
          <div class="detail-head">
            <div>
              <div class="device-title-line">
                <div class="detail-title">{{ detail.name }}</div>
                <a-tag :color="isOnline(detail) ? 'green' : 'default'">{{ $t(isOnline(detail) ? 'agentRuntimeGovernance.detail.online' : 'agentRuntimeGovernance.detail.offline') }}</a-tag>
                <a-popover trigger="click" :title="$t('agentRuntimeGovernance.presentation.deviceInfo')">
                  <template #content>
                    <div class="device-info-content">
                      <div>{{ $t('agentRuntimeGovernance.presentation.deviceId') }}</div>
                      <code>{{ detail.client_id }}</code>
                      <a-button type="link" size="small" @click="copyClientId">{{ $t('clientDetail.copyId') }}</a-button>
                      <div>{{ $t('clientDetail.registeredBy') }}: {{ detail.registered_by || '-' }}</div>
                    </div>
                  </template>
                  <a-button type="text" size="small" :aria-label="$t('agentRuntimeGovernance.presentation.deviceInfo')"><InfoCircleOutlined /></a-button>
                </a-popover>
              </div>
              <div class="device-status-line">
                <span><span v-if="detail.hostname !== detail.name">{{ detail.hostname }} · </span>{{ detail.os }}/{{ detail.arch }}</span>
                <span>{{ $t('agentRuntimeGovernance.detail.lastHeartbeat') }}: {{ formatTime(detail.last_seen_at) }}</span>
                <a-tooltip :title="$t('clientDetail.deviceRefreshHelp')">
                  <a-button type="text" size="small" :loading="deviceRefreshing" :disabled="deviceRefreshing" :aria-label="$t('clientDetail.deviceRefresh')" @click="refreshDeviceStatus"><ReloadOutlined /></a-button>
                </a-tooltip>
              </div>
            </div>
            <div class="detail-config-actions">
              <a-button v-if="hasAccess('clients:view') || hasAccess('settings:view')" @click="openClassification(detail.client_id)"><SettingOutlined />{{ $t('clientPolicy.settings') }}</a-button>
            </div>
          </div>

          <a-tabs v-model:active-key="runtimeTab" :destroy-inactive-tab-pane="true" class="device-runtime-tabs">
            <a-tab-pane key="overview" :tab="$t('agentRuntimeGovernance.detail.overview')"><ClientDeviceOverview ref="overviewPanel" :client="detail" @navigate="navigateDetail" @activity="openAuditActivity" /></a-tab-pane>
            <a-tab-pane key="skills" :tab="$t('agentRuntimeGovernance.detail.skills')">
              <a-radio-group v-model:value="inventoryView" class="inventory-navigation" button-style="solid">
                <a-radio-button value="inventory">{{ $t('clientDetail.inventory') }}</a-radio-button>
                <a-radio-button value="tasks">{{ $t('clientDetail.tasks') }}</a-radio-button>
                <a-radio-button value="history">{{ $t('clientDetail.history') }}</a-radio-button>
                <a-radio-button value="recovery">{{ $t('clientDetail.recovery') }}<span v-if="detail.recovery?.length"> · {{ detail.recovery.length }}</span></a-radio-button>
              </a-radio-group>
              <template v-if="inventoryView === 'inventory'">
              <div class="skill-policy-controls">
                <a-radio-group v-model:value="inventoryType" :aria-label="$t('clientDetail.sourceType')"><a-radio-button value="agents">{{ $t('clientDetail.agents') }} · {{ actualAgentCount(detail) }}</a-radio-button><a-radio-button value="shared">{{ $t('clientDetail.shared') }} · {{ sharedSkillsCount(detail) }}</a-radio-button></a-radio-group>
                <label>
                <span>{{ $t("legacy.1bb65oo") }}</span>
                <a-select :value="currentGovernance" :disabled="!hasAccess('clients:update')" class="governance-select" @change="saveGovernance">
                  <a-select-option value="registry">{{ $t("legacy.12wr3db") }}</a-select-option>
                  <a-select-option value="strict">{{ $t("legacy.1bqmand") }}</a-select-option>
                </a-select>
              </label>
              </div>
          <details><summary>{{ $t('agentRuntimeGovernance.presentation.policyHelp') }}</summary><p>{{ detail.classification?.enabled ? $t('clientGovernance.active') : policyDescription(currentPolicy) }}</p><p>{{ governanceDescription(currentGovernance) }}</p></details>

          <p v-if="inventoryType === 'shared'" class="muted">{{ $t('clientDetail.sharedNote') }}</p>
          <a-table class="local-agents-table" :columns="visibleAgentColumns" :data-source="inventoryAgents" :row-key="row => row.local_agent_id || row.agent_type" size="small" :pagination="{ pageSize: 8, hideOnSinglePage: true }" :expandable="agentTableExpandable" :scroll="{ x: 650 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <a-button v-if="record.managed_agent_id && hasAccess('agents:view') && !isSharedSkillsRecord(record)" type="link" size="small" :title="$t('agentWorkspace.openAgent')" @click="router.push({ path: '/agents', query: { agent: record.managed_agent_id, client: detail.client_id, local: record.local_agent_id } })">{{ agentLabel(record.agent_type, record) }}</a-button><strong v-else>{{ agentLabel(record.agent_type, record) }}</strong>
                <div class="muted">{{ isSharedSkillsRecord(record) ? sharedSkillsDescription(record) : (record.version || $t('legacy.g4nqyc')) }}</div>
                <small v-if="!record.skill_management_supported" class="muted">{{ $t('clientDetail.unsupported') }}</small>
              </template>
              <template v-else-if="column.key === 'model'">
                <div>{{ record.applied_model || record.desired_model || managedAgentDefaultModel(record) || '-' }}</div>
                <a-tag v-if="record.model_config_status && record.model_config_status !== 'not_configured'" :color="modelConfigColor(record.model_config_status)">
                  {{ modelConfigStatusLabel(record.model_config_status) }}
                </a-tag>
                <details v-if="record.model_config_error || record.capabilities?.model_config_state?.verification?.length" class="model-config-evidence">
                  <summary>{{ $t('clientModelConfig.evidence') }}</summary>
                  <p v-if="record.model_config_error" class="muted model-error">{{ modelErrorLabel(record.model_config_error) }}</p>
                  <pre v-if="record.capabilities?.model_config_state?.verification?.length">{{ JSON.stringify(record.capabilities.model_config_state.verification, null, 2) }}</pre>
                </details>
              </template>
              <template v-else-if="column.key === 'skills'">
                <div>{{ $t('localAssets.skills') }} {{ record.skills?.length || 0 }}</div>
                <div v-if="record.asset_inventory" class="muted">{{ $t('localAssets.summary', localAssetCounts(record)) }}</div>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-space wrap size="small">
                  <a-button v-if="hasAccess('clients:execute')" type="link" :disabled="!record.skill_management_supported || (currentGovernance === 'strict' && isSharedSkillsRecord(record))" :title="currentGovernance === 'strict' && isSharedSkillsRecord(record) ? $t('legacy.13rv9dd') : ''" @click="openInstall(record)">{{ $t('legacy.1byrs80') }}</a-button>
                  <a-dropdown v-if="hasAccess('clients:execute') && !isSharedSkillsRecord(record)" :trigger="['click']">
                    <a-button type="link">{{ $t('clientDetail.more') }}</a-button>
                    <template #overlay><a-menu>
                    <a-menu-item key="model" :disabled="!canConfigureModel(record)" :title="modelConfigDisabledReason(record)" @click="openModelConfig(record)">{{ $t('clientModelConfig.action') }}</a-menu-item>
                    <a-menu-item v-if="record.capabilities?.model_config_verification && record.capabilities?.model_config_state?.change_id" key="verify" :disabled="!!modelOperationBusy" @click="runModelOperation(record, 'verify_model_config')">{{ $t('clientModelConfig.verify') }}</a-menu-item>
                    <a-menu-item v-if="record.capabilities?.model_config_state?.change_id" key="restore" :disabled="!!modelOperationBusy || !record.capabilities?.model_config_state?.can_restore" @click="runModelOperation(record, 'restore_model_config')">{{ $t('clientModelConfig.restore') }}</a-menu-item>
                    </a-menu></template>
                  </a-dropdown>
                  <a-spin v-if="modelOperationBusy?.startsWith(record.local_agent_id + ':')" size="small" />

                </a-space>
              </template>
            </template>
            <template #expandedRowRender="{ record: agentRecord }">
              <AgentLocalAssets :inventory="agentRecord.asset_inventory" :skills="agentSkills(agentRecord)" :integrations="!isSharedSkillsRecord(agentRecord)">
                <template #skills>
              <a-table class="agent-skill-table" table-layout="fixed" :columns="skillColumns" :data-source="agentSkills(agentRecord)" :row-key="row => `${row.agent_type}:${row.path}`" size="small" :pagination="false">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'name'">
                    <strong>{{ record.name }}</strong>
                    <div class="muted ellipsis">{{ record.path }}</div>
                  </template>
                  <template v-else-if="column.key === 'status'">
                    <a-tag>{{ $t(`clientGovernance.${record.governance?.certification || 'confirmation_pending'}`) }}</a-tag>
                    <div v-if="record.status === 'external_link'" class="muted">{{ $t('clientGovernance.linkOutsideScope') }}</div>
                    <div v-if="record.governance?.trigger" class="muted">{{ governanceEventValue(record.governance.trigger) }}</div>
                    <div v-if="record.governance?.action" class="muted">{{ governanceEventValue(record.governance.action) }}</div>
                    <ClientSkillScan :skill="record" />
                  </template>
                  <template v-else-if="column.key === 'action'">
                    <ClientSkillActions :client="detail" :agent="agentRecord" :skill="record" @created="skillActionCreated" />
                  </template>
                </template>
              </a-table>
                </template>
              </AgentLocalAssets>
            </template>
          </a-table>
              </template>

          <template v-if="inventoryView === 'recovery'">
          <div class="section-title">{{ $t('clientGovernance.recoveryCopies') }}</div>
          <a-table :columns="recoveryColumns" :data-source="detail.recovery || []" row-key="id" size="small" :pagination="{ pageSize: 6 }" :scroll="{ x: 650 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'action'">
                <ClientSkillActions :client="detail" :agent="recoveryAgent(record)" :skill="record" recovery @created="skillActionCreated" />
              </template>
            </template>
          </a-table>

          </template>
          <template v-if="inventoryView === 'tasks'">
          <div class="section-title">{{ $t("agentRuntimeGovernance.detail.skillTasks") }}</div>
          <a-table :columns="taskColumns" :data-source="skillTasks" row-key="id" size="small" :pagination="{ pageSize: 6 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <strong>{{ taskLabel(record) }}</strong>
                <div v-if="taskTargetLabel(record)" class="muted">{{ taskTargetLabel(record) }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="taskColor(record.status)">{{ taskStatusLabel(record.status, record) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'created'">{{ formatTime(record.created_at) }}</template>
              <template v-else-if="column.key === 'error'">{{ ['policy_superseded', 'policy_ack_required'].includes(record.error) ? $t(`clientGovernance.${record.error}`) : modelErrorLabel(record.error) }}</template>
              <template v-else-if="column.key === 'action'">
                <a-space>
                  <a-button v-if="hasAccess('clients:execute') && (['pending', 'running'].includes(record.status))" type="link" danger :loading="taskOperations.has(record.id)" :disabled="taskOperations.has(record.id) || taskCannotCancel(record)" :title="taskCannotCancel(record) ? $t('clientGovernance.actionAlreadyStarted') : ''" @click="cancelTask(record)">{{ $t("legacy.1589w37") }}</a-button>
                  <a-button v-if="hasAccess('clients:execute') && record.error !== 'policy_superseded' && (['failed', 'cancelled'].includes(record.status))" type="link" :loading="taskOperations.has(record.id)" :disabled="taskOperations.has(record.id)" @click="retryTask(record)">{{ $t("legacy.lswd2v") }}</a-button>
                </a-space>
              </template>
            </template>
          </a-table>
          </template>

          <ClientEventRecords v-if="inventoryView === 'history'" ref="eventRecordsPanel" :client-id="detail.client_id" :client-name="detail.name || detail.hostname" :agent-label="agentLabel" @collection="navigateDetail('collection')" />
            </a-tab-pane>
            <a-tab-pane key="plugins" :tab="$t('agentRuntimeGovernance.tabs.plugins')"><ClientRuntimeGovernance :client-id="detail.client_id" @collection="navigateDetail('collection')" @policy="navigateDetail('control')" @events="openHookEvents" /></a-tab-pane>
            <a-tab-pane key="audit" :tab="$t('agentRuntimeGovernance.tabs.audit')"><ClientBehaviorAudit v-model:view="auditView" :client-id="detail.client_id" :activity-request="activityRequest" @policy="openClassification(detail.client_id)" @plugins="runtimeTab = 'plugins'" /></a-tab-pane>
            <a-tab-pane key="control" :tab="$t('agentRuntimeGovernance.detail.control')">
              <ClientPolicyWorkbench :key="detail.client_id" v-model="controlView" :client-id="detail.client_id" />
            </a-tab-pane>
          </a-tabs>
        </template>
      </a-spin>
    </a-drawer>

    <a-drawer v-model:open="globalToolPolicyOpen" :title="$t('aidr.hooks.scope.title')" width="min(1100px, 100vw)" :destroy-on-close="true">
      <ClientHookPanel v-if="globalToolPolicyOpen" global />
    </a-drawer>
    <a-modal v-model:open="installVisible" :title="$t('legacy.1mz4184')" :ok-text="$t('legacy.zerco7')" @ok="createInstall" :confirm-loading="submitting">
      <a-form layout="vertical">
        <a-form-item :label="$t('legacy.5v4zar')">
          <a-input :value="agentLabel(installForm.agent_type)" disabled />
        </a-form-item>
        <a-form-item label="Skill" required>
          <a-select v-model:value="installForm.skill_id" show-search option-filter-prop="label" :loading="skillsLoading" :placeholder="currentGovernance === 'strict' ? $t('legacy.2a0ve3') : $t('legacy.18oqd51')" :not-found-content="$t('legacy.ohbkin')">
            <a-select-option v-for="skill in installableSkills" :key="skill.skill_id" :value="skill.skill_id" :label="skill.name">
              {{ skill.name }}<span class="skill-option-time">{{ $t("legacy.zemp4d") }} {{ formatTime(skill.submitted_at) }}</span>
            </a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="modelConfigVisible"
      :title="$t('clientModelConfig.title')"
      :ok-text="$t('clientModelConfig.apply')"
      :confirm-loading="modelConfigSubmitting"
      :ok-button-props="{ disabled: modelConfigSubmitting || !modelConfigForm.model }"
      @ok="createModelConfig"
    >
      <a-alert
        type="info"
        show-icon
        class="policy-note"
        :message="$t('clientModelConfig.securityTitle')"
        :description="$t('clientModelConfig.securityDescription')"
      />
      <a-form layout="vertical">
        <a-form-item :label="$t('clientModelConfig.agent')">
          <a-input :value="agentLabel(modelConfigForm.agent_type)" disabled />
        </a-form-item>
        <a-form-item :label="$t('externalModel.source')">
          <a-radio-group v-model:value="modelConfigForm.source" button-style="solid" @change="handleModelSourceChange">
            <a-radio-button value="internal">{{ $t('externalModel.internal') }}</a-radio-button>
            <a-radio-button value="external_gateway" :disabled="!externalSourceAvailable">{{ $t('externalModel.external') }}</a-radio-button>
          </a-radio-group>
          <div v-if="!externalGatewayAllowed" class="muted">{{ $t('externalModel.unavailable') }}</div>
        </a-form-item>
        <template v-if="modelConfigForm.source === 'external_gateway'">
          <a-alert type="info" show-icon class="policy-note" :message="$t('externalModel.prepareHint')" />
          <a-button :loading="externalModelsLoading" :disabled="externalModelsLoading" @click="refreshExternalModels">
            {{ $t(externalCatalog ? 'externalModel.refresh' : 'externalModel.prepare') }}
          </a-button>
          <a-alert v-if="externalModelsLoading" class="model-catalog-state" type="info" show-icon :message="$t('externalModel.preparing')" />
          <a-alert v-else-if="externalModelsError" class="model-catalog-state" type="error" show-icon :message="$t('externalModel.loadFailed')" :description="externalModelsError" />
          <a-alert v-else-if="externalCatalog" class="model-catalog-state" :type="externalModels.length ? 'success' : 'warning'" show-icon :message="$t(externalModels.length ? 'externalModel.ready' : 'externalModel.empty')">
            <template #description>
              <div>{{ $t('externalModel.modelCount', { count: externalModels.length }) }}</div>
              <div v-if="externalCatalog.gateway">{{ $t('externalModel.gateway', { name: externalCatalog.gateway.name }) }}</div>
              <div v-if="externalCatalog.binding?.external_agent_id">{{ $t('externalModel.agent', { id: externalCatalog.binding.external_agent_id }) }}</div>
              <div v-if="externalCatalog.binding?.status">{{ $t('externalModel.bindingStatus', { status: externalCatalog.binding.status }) }}</div>
              <div v-if="externalCatalog.binding?.key_id">{{ $t('externalModel.keyId', { id: externalCatalog.binding.key_id }) }}</div>
            </template>
          </a-alert>
        </template>
        <a-form-item :label="$t('clientModelConfig.model')" required>
          <a-select v-model:value="modelConfigForm.model" show-search option-filter-prop="label" :loading="externalModelsLoading" :disabled="modelConfigForm.source === 'external_gateway' && !externalCatalog" :placeholder="$t(modelConfigForm.source === 'external_gateway' && !externalCatalog ? 'externalModel.selectAfterRefresh' : 'clientModelConfig.modelPlaceholder')">
            <a-select-option v-for="model in modelSelectionOptions" :key="model.name" :value="model.name" :label="modelLabel(model)">
              {{ modelLabel(model) }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-alert v-if="modelConfigTarget?.capabilities?.model_config_contract?.parameter_status === 'version_unverified'" type="warning" :message="$t('clientModelConfig.versionUnverified')" :description="modelConfigTarget.capabilities.model_config_contract.parameter_versions?.join(', ')" />
        <a-form-item v-for="(field, key) in modelParameterFields" :key="key" :label="$t(`clientModelConfig.parameters.${key}`)">
          <a-select v-if="field.enum" v-model:value="modelConfigForm.parameters[key]" allow-clear :placeholder="$t('clientModelConfig.unset')">
            <a-select-option v-for="option in field.enum" :key="option" :value="option">{{ option }}</a-select-option>
          </a-select>
          <a-input-number v-else v-model:value="modelConfigForm.parameters[key]" :min="field.min" :max="field.max" :precision="field.type === 'integer' ? 0 : undefined" :placeholder="$t('clientModelConfig.unset')" style="width: 100%" />
          <div class="muted"><code>{{ field.path }}</code> → <code>{{ field.wire }}</code></div>
        </a-form-item>
        <a-alert type="info" :message="$t('clientModelConfig.effect')" />
        <div v-if="modelConfigForm.source === 'external_gateway'" class="muted model-call-note">{{ $t('externalModel.clientReported') }}</div>
        <pre class="model-config-preview">{{ modelConfigPreview }}</pre>
      </a-form>
    </a-modal>

    <a-modal v-model:open="installGuideVisible" :title="$t('legacy.16nx8w')" :footer="null" width="620">
      <a-steps direction="vertical" size="small" :current="0">
        <a-step :title="$t('legacy.1xejj4z')">
          <template #description>
            <a-space wrap>
              <a-select v-model:value="selectedPlatform" :placeholder="$t('legacy.99euj3')" style="width: 300px">
                <a-select-option v-for="item in downloadPlatforms" :key="item.key" :value="item.key">{{ downloadPlatformLabel(item) }} · {{ item.version }}</a-select-option>
              </a-select>
              <a-button type="primary" :disabled="!selectedPlatform" :loading="clientDownloading" @click="downloadSelectedClient">
                {{ clientDownloading ? $t('legacy.cmznra') : $t('legacy.1osfjit') }}
              </a-button>
            </a-space>
            <div v-if="clientDownloading || clientDownloadDetail" class="client-download-progress">
              <a-spin v-if="clientDownloading" size="small" />
              <span>{{ clientDownloadDetail }}</span>
            </div>
          </template>
        </a-step>
        <a-step :title="$t('legacy.vydiwk')" :description="$t('legacy.1xo5pih')" />
        <a-step :title="$t('legacy.hy1368')" :description="$t('legacy.k9b27o')" />
        <a-step :title="$t('legacy.1jy5crp')" :description="$t('legacy.1dv7bph')" />
      </a-steps>
    </a-modal>
  </div>
    <ClientGovernancePolicy v-model:open="classificationOpen" :client-id="classificationClientId" :initial-tab="classificationTab" @saved="loadClients(); detailVisible && refreshDetail()" />
</template>

<script setup>
import { modelLabel } from '../utils/modelLabels'
import { can as hasAccess } from '../access'
import ClientGovernancePolicy from '../components/ClientGovernancePolicy.vue'
import ClientPolicyWorkbench from '../components/ClientPolicyWorkbench.vue'
import ClientBehaviorAudit from '../components/ClientBehaviorAudit.vue'
import ClientEventRecords from '../components/ClientEventRecords.vue'
import ClientDeviceOverview from '../components/ClientDeviceOverview.vue'
import ClientRuntimeGovernance from '../components/ClientRuntimeGovernance.vue'
import ClientHookPanel from '../components/ClientHookPanel.vue'
import ClientSkillScan from '../components/ClientSkillScan.vue'
import AgentLocalAssets from '../components/AgentLocalAssets.vue'
import { withAssetNameSearch } from '../utils/assetNameSearch'
import ClientSkillActions from '../components/ClientSkillActions.vue'
import {
  getCurrentLocale,
  i18n,
  translateDomain,
  translateLegacy as phrase,
  translateText as text,
} from '../i18n'

import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
const globalToolPolicyOpen = ref(false)
import { message } from 'ant-design-vue'
import { InfoCircleOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons-vue'
import { copyText } from '../utils/clipboard'

import {
  cancelClientTask,
  createClientDownloadTicket,
  createClientTask,
  getClientDetail,
  listAccessTokens,
  listAgents,
  listClients,
  listClientDownloads,
  listModelEndpoints,
  prepareExternalModelCatalog,
  listSkills,
  retryClientTask,
  updateClientPolicy,
} from '../api'
const loading = ref(false)
const classificationOpen = ref(false)
const classificationClientId = ref('')
const classificationTab = ref('integration')
const route = useRoute(), router = useRouter()
const openClassification = (clientId, tab = 'integration') => { classificationClientId.value = clientId; classificationTab.value = tab; classificationOpen.value = true }
watch(() => [route.query.policy, route.query.client], ([value, clientId]) => {
  if (value !== 'audit' || !hasAccess('settings:view')) return
  openClassification(typeof clientId === 'string' ? clientId : '', 'audit')
  const query = { ...route.query }; delete query.policy; delete query.client
  router.replace({ query })
}, { immediate: true })
const detailLoading = ref(false)
const submitting = ref(false)
const eventRecordsPanel = ref(null)
const detailVisible = ref(false)
const runtimeTab = ref('overview')
const inventoryView = ref('inventory'), inventoryType = ref('agents')
const auditView = ref('tools'), controlView = ref('tools')
const activityRequest = ref(null)
const openAuditActivity = request => {
  activityRequest.value = { clientId: detail.value.client_id, ...request }
  auditView.value = request.source === 'logs' ? 'tools' : 'hooks'; runtimeTab.value = 'audit'
}
const openHookEvents = agent => {
  activityRequest.value = { clientId: detail.value.client_id, agent }
  auditView.value = 'hooks'; runtimeTab.value = 'audit'
}
const fixedDetailActive = computed(() => ['audit', 'plugins'].includes(runtimeTab.value))
const navigateDetail = target => {
  auditView.value = target === 'collection' ? 'collection' : target === 'systemEvents' ? 'system' : 'tools'
  if (target === 'skillTasks') inventoryView.value = 'tasks'
  if (target === 'systemControl') controlView.value = 'system'
  runtimeTab.value = ['collection', 'systemEvents'].includes(target) ? 'audit' : target === 'systemControl' ? 'control' : target === 'skillTasks' ? 'skills' : target
}
const skillTasks = computed(() => (detail.value?.tasks || []).filter(task => task.task_type !== 'aidr_plugin_action'))
const installVisible = ref(false)
const modelConfigVisible = ref(false)
const modelConfigSubmitting = ref(false)
const installGuideVisible = ref(false)
const clients = ref([])
const agents = ref([])
const accessTokens = ref([])
const modelEndpoints = ref([])
const skills = ref([])
const skillsLoading = ref(false)
const targetInstalledSkills = ref([])
const detail = ref(null)
const overviewPanel = ref(null)
const taskOperations = reactive(new Set())
let detailSequence = 0
const recoveryColumns = computed(() => [
  { title: i18n.global.t('clientGovernance.skill'), dataIndex: 'skill_name' },
  { title: i18n.global.t('clientGovernance.agent'), dataIndex: 'agent_type' },
  { title: i18n.global.t('clientGovernance.path'), dataIndex: 'original_path', ellipsis: true },
  { title: i18n.global.t('clientGovernance.chooseAction'), key: 'action', width: 220 },
])
const recoveryAgent = record => detail.value?.agents?.find(agent => agent.agent_type === record.agent_type) || { agent_type: record.agent_type }
const skillActionCreated = async ({ clientId, taskId }) => {
  if (detail.value?.client_id !== clientId) return
  await refreshDetail()
  watchTask(taskId, clientId).catch(() => {})
}
const currentPolicy = ref('audit')
const currentGovernance = ref('registry')
const installForm = reactive({ agent_type: '', managed_agent_id: '', skill_id: '' })
const modelConfigForm = reactive({ local_agent_id: '', agent_type: '', managed_agent_id: '', source: 'internal', gateway_id: null, model: '', parameters: {}, expected_revision: undefined })
const modelConfigTarget = ref(null)
const externalCatalog = ref(null)
const externalModels = ref([])
const externalModelsLoading = ref(false)
const externalModelsError = ref('')
const modelOperationBusy = ref('')
const runModelOperation = async (record, operation) => {
  if (modelOperationBusy.value) return
  modelOperationBusy.value = record.local_agent_id + ':' + operation
  const state = record.capabilities?.model_config_state || {}
  try {
    const task = await createClientTask(detail.value.client_id, { task_type: operation, payload: { agent_type: record.agent_type, local_agent_id: record.local_agent_id, change_id: state.change_id, expected_revision: state.revision } })
    await refreshDetail()
    message.success(i18n.global.t('clientModelConfig.taskCreated'))
    watchTask(task.id).catch(() => {})
  } catch (error) { message.error(error.response?.data?.detail || i18n.global.t('clientModelConfig.createFailed')) }
  finally { modelOperationBusy.value = '' }
}

const modelParameterFields = computed(() => modelConfigTarget.value?.capabilities?.model_config_contract?.parameters || {})
const modelConfigPreview = computed(() => JSON.stringify({
  path: modelConfigTarget.value?.capabilities?.model_config_state?.config_path,
  before: { model: modelConfigTarget.value?.capabilities?.model_config_state?.model, parameters: modelConfigTarget.value?.capabilities?.model_config_state?.parameters || {} },
  after: { model: modelConfigForm.model, parameters: { ...(modelConfigTarget.value?.capabilities?.model_config_state?.parameters || {}), ...Object.fromEntries(Object.entries(modelConfigForm.parameters).filter(([, value]) => value != null)) } },
}, null, 2))
const downloadPlatforms = ref([])
const selectedPlatform = ref()
const clientDownloading = ref(false)
const clientDownloadDetail = ref('')
const downloadPlatformLabel = item => text(item.platform_label, {
  'darwin-aarch64': 'macOS Apple Silicon',
  'darwin-x86_64': 'macOS Intel',
  'windows-x86_64': 'Windows 64-bit',
  'linux-x86_64': 'Linux 64-bit',
}[item.platform] || item.platform_label)

const compareClientText = (left, right) => String(left || '').localeCompare(String(right || ''), getCurrentLocale(), { numeric: true, sensitivity: 'base' })
const heartbeatTime = value => {
  if (!value) return 0
  const text = String(value)
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`) || 0
}
const columns = [
  { title: phrase('legacy.tus94r'), key: 'client', sorter: (a, b) => compareClientText(a.name, b.name) },
  { title: phrase('legacy.p0ysv3'), key: 'platform', width: 170, sorter: (a, b) => compareClientText(a.os, b.os) || compareClientText(a.arch, b.arch) },
  { title: 'Agent', key: 'agents', width: 180, sorter: (a, b) => actualAgentCount(a) - actualAgentCount(b) },
  { title: 'Skill', key: 'skills', width: 180, sorter: (a, b) => skillCount(a) - skillCount(b) },
  { title: phrase('legacy.1mk8o97'), key: 'credentialOwner', width: 140, sorter: (a, b) => compareClientText(a.registered_by, b.registered_by) },
  { title: phrase('legacy.1ccx4t4'), key: 'status', width: 100, sorter: (a, b) => Number(isOnline(a)) - Number(isOnline(b)) },
  { title: phrase('legacy.12y43gp'), key: 'lastSeen', width: 200, sorter: (a, b) => heartbeatTime(a.last_seen_at) - heartbeatTime(b.last_seen_at) },
  { title: phrase('legacy.501w24'), key: 'action', width: 100 },
]
const agentColumns = [
  { title: 'Agent', key: 'type' },
  { title: i18n.global.t('clientModelConfig.model'), key: 'model', width: 230 },
  { title: () => i18n.global.t('localAssets.assets'), key: 'skills', width: 155 },
  { title: phrase('legacy.501w24'), key: 'action', width: 170, fixed: 'right' },
]
const visibleAgentColumns = computed(() => agentColumns
  .filter(column => inventoryType.value !== 'shared' || column.key !== 'model')
  .map(column => column.key === 'type' && inventoryType.value === 'shared' ? { ...column, title: i18n.global.t('clientDetail.shared') } : column))
const inventoryAgents = computed(() => (detail.value?.agents || []).filter(agent => isSharedSkillsRecord(agent) === (inventoryType.value === 'shared')))
const skillColumns = [
  withAssetNameSearch({ title: 'Skill', key: 'name' }),
  { title: phrase('legacy.1ccx4t4'), key: 'status', width: 240 },
  { title: phrase('legacy.501w24'), key: 'action', width: 190 },
]
const taskColumns = [
  { title: phrase('legacy.cm180x'), key: 'type', width: 240 },
  { title: phrase('legacy.1ccx4t4'), key: 'status', width: 100 },
  { title: phrase('legacy.miy8ea'), key: 'created', width: 180 },
  { title: phrase('legacy.64sn8k'), key: 'error' },
  { title: phrase('legacy.501w24'), key: 'action', width: 90 },
]

const onlineCount = computed(() => clients.value.filter(isOnline).length)
const isSharedSkillsRecord = record => record?.agent_type === 'global-skills'
const actualAgentCount = record => record.agents?.filter(agent => !isSharedSkillsRecord(agent)).length || 0
const sharedSkillsCount = record => record.agents?.filter(isSharedSkillsRecord).length || 0
const agentCount = computed(() => clients.value.reduce((sum, item) => sum + actualAgentCount(item), 0))
const issueCount = computed(() => clients.value.reduce((sum, item) => sum + (item.issue_count || 0), 0))
const localAssetCounts = record => ({ mcp: (record.asset_inventory?.mcp_servers?.length || 0) + (record.asset_inventory?.plugins || []).reduce((count, plugin) => count + plugin.mcp_servers.length, 0), plugins: record.asset_inventory?.plugins?.length || 0 })
const agentTableExpandable = { rowExpandable: record => !isSharedSkillsRecord(record) || Boolean(record.skills?.length) }
const selectedManagedAgent = computed(() => agents.value.find(agent => agent.agent_id === installForm.managed_agent_id))
const tokenNotExpired = token => {
  if (!token.expires_at) return true
  const raw = String(token.expires_at)
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`
  return new Date(normalized).getTime() > Date.now()
}
const modelRuntimeToken = computed(() => accessTokens.value
  .filter(token => token.token_type === 'agent_runtime'
    && token.bound_agent_id === modelConfigForm.managed_agent_id
    && token.status === 'active'
    && tokenNotExpired(token)
    && (token.scopes || []).includes('model:chat'))
  .sort((left, right) => Number(right.id) - Number(left.id))[0])
const clientIssuanceToken = computed(() => accessTokens.value
  .filter(token => token.token_type === 'client'
    && token.bound_client_id === detail.value?.client_id
    && token.status === 'active'
    && tokenNotExpired(token)
    && token.allow_agent_credential_issuance)
  .sort((left, right) => Number(right.id) - Number(left.id))[0])
const configurableModels = computed(() => {
  const token = modelRuntimeToken.value
  if (!token) {
    const clientToken = clientIssuanceToken.value
    if (!clientToken) return []
    const allowed = new Set(clientToken.allowed_models || [])
    return modelEndpoints.value.filter(model => model.enabled && (!allowed.size || allowed.has(model.name)))
  }
  const allowed = new Set(token.allowed_models || [])
  return modelEndpoints.value.filter(model => model.enabled && (!allowed.size || allowed.has(model.name)))
})
const effectiveModelRouting = computed(() => detail.value?.model_routing || detail.value?.governance?.model_routing || {})
const externalGatewayAllowed = computed(() => Boolean(effectiveModelRouting.value.external_gateway_enabled && effectiveModelRouting.value.external_gateway_id))
const externalSourceAvailable = computed(() => externalGatewayAllowed.value)
const modelSelectionOptions = computed(() => modelConfigForm.source === 'external_gateway' ? externalModels.value : configurableModels.value)
const installableSkills = computed(() => {
  const installedIDs = new Set(targetInstalledSkills.value.map(skill => skill.skill_id).filter(Boolean))
  const installedNames = new Set(targetInstalledSkills.value.map(skill => skill.name).filter(Boolean))
  const available = skills.value.filter(skill => !installedIDs.has(skill.skill_id) && !installedNames.has(skill.name))
  if (currentGovernance.value !== 'strict') return available
  const allowed = new Set(selectedManagedAgent.value?.skill_names || [])
  return available.filter(skill => allowed.has(skill.skill_id) || allowed.has(skill.name))
})

const loadClients = async () => {
  loading.value = true
  try {
    clients.value = await listClients()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.167k0p'))
  } finally {
    loading.value = false
  }
}
const openDetail = async (record) => {
  inventoryView.value = 'inventory'; inventoryType.value = 'agents'
  runtimeTab.value = 'overview'; auditView.value = 'tools'; controlView.value = 'tools'
  const sequence = ++detailSequence
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const result = await getClientDetail(record.client_id)
    if (sequence !== detailSequence) return
    detail.value = result
    currentPolicy.value = detail.value.policy_mode || 'audit'
    currentGovernance.value = detail.value.governance_mode || 'registry'
  } finally {
    if (sequence === detailSequence) detailLoading.value = false
  }
}
const deviceRefreshing = ref(false)
const copyClientId = async () => {
  try {
    await copyText(detail.value.client_id)
    message.success(i18n.global.t('clientDetail.idCopied'))
  } catch {
    message.error(i18n.global.t('clientDetail.copyFailed'))
  }
}
const refreshDeviceStatus = async () => {
  if (deviceRefreshing.value) return
  deviceRefreshing.value = true
  try {
    await refreshDetail(false)
  } catch {
    message.error(i18n.global.t('clientDetail.refreshFailed'))
  } finally {
    deviceRefreshing.value = false
  }
}
const refreshDetail = async (refreshPanels = true) => {
  if (!detail.value?.client_id) return
  const clientId = detail.value.client_id
  const sequence = ++detailSequence
  const result = await getClientDetail(clientId, { event_page: detail.value.event_page || 1 })
  if (sequence !== detailSequence || !detailVisible.value || detail.value?.client_id !== clientId) return
  detail.value = result
  currentPolicy.value = detail.value.policy_mode || 'audit'
  currentGovernance.value = detail.value.governance_mode || 'registry'
  if (refreshPanels) {
    await overviewPanel.value?.refresh()
    await eventRecordsPanel.value?.refresh()
  }
}
const watchTask = async (taskId, clientId = detail.value?.client_id) => {
  for (let attempt = 0; attempt < 15 && detailVisible.value && detail.value?.client_id === clientId; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 2000))
    if (!detailVisible.value || detail.value?.client_id !== clientId) return
    await refreshDetail()
    const status = detail.value.tasks?.find(task => task.id === taskId)?.status
    if (status && !['pending', 'running'].includes(status)) return
  }
}
const saveGovernance = async (governanceMode) => {
  await updateClientPolicy(detail.value.client_id, { governance_mode: governanceMode })
  currentGovernance.value = governanceMode
  detail.value.governance_mode = governanceMode
  await refreshDetail()
  message.success(phrase('legacy.jzjm0b'))
}
const openInstall = async (record) => {
  Object.assign(installForm, { agent_type: record.agent_type, managed_agent_id: record.managed_agent_id, skill_id: '' })
  targetInstalledSkills.value = record.skills || []
  installVisible.value = true
  if (skills.value.length) return
  skillsLoading.value = true
  try {
    const rows = await listSkills({ status: 'APPROVED', page: 1, page_size: 100, sort_by: 'submitted_at', sort_order: 'desc' })
    skills.value = Array.isArray(rows.items) ? rows.items : rows
  } finally {
    skillsLoading.value = false
  }
}
const runtimeTokenFor = record => accessTokens.value
  .filter(token => token.token_type === 'agent_runtime'
    && token.bound_agent_id === record.managed_agent_id
    && token.status === 'active'
    && tokenNotExpired(token)
    && (token.scopes || []).includes('model:chat'))
  .sort((left, right) => Number(right.id) - Number(left.id))[0]
const canConfigureModel = record => Boolean(record.capabilities?.model_config_auto_apply)
  && Boolean((externalGatewayAllowed.value && record.managed_agent_id) || runtimeTokenFor(record) || clientIssuanceToken.value)
const modelConfigDisabledReason = record => {
  if (!record.capabilities?.model_config_auto_apply) return i18n.global.t('clientModelConfig.unsupportedAgent')
  if (externalGatewayAllowed.value) return record.managed_agent_id ? '' : i18n.global.t('clientModelConfig.identityPending')
  if (!record.managed_agent_id && !clientIssuanceToken.value) return i18n.global.t('clientModelConfig.identityPending')
  if (!runtimeTokenFor(record) && !clientIssuanceToken.value) return i18n.global.t('clientModelConfig.credentialRequired')
  return ''
}
const openModelConfig = record => {
  if (!canConfigureModel(record)) {
    message.warning(modelConfigDisabledReason(record))
    return
  }
  modelConfigTarget.value = record
  externalCatalog.value = null
  externalModels.value = []
  externalModelsError.value = ''
  Object.assign(modelConfigForm, {
    local_agent_id: record.local_agent_id || record.agent_type,
    agent_type: record.agent_type,
    managed_agent_id: record.managed_agent_id,
    source: externalGatewayAllowed.value && record.managed_agent_id ? 'external_gateway' : 'internal',
    gateway_id: externalGatewayAllowed.value && record.managed_agent_id ? effectiveModelRouting.value.external_gateway_id : null,
    model: record.desired_model || record.applied_model || managedAgentDefaultModel(record) || '',
    parameters: {},
    expected_revision: record.capabilities?.model_config_state?.revision,
  })
  if (modelConfigForm.source === 'internal' && !configurableModels.value.some(model => model.name === modelConfigForm.model)) {
    modelConfigForm.model = configurableModels.value[0]?.name || ''
  } else if (modelConfigForm.source === 'external_gateway') {
    modelConfigForm.model = ''
  }
  modelConfigVisible.value = true
}
const handleModelSourceChange = () => {
  modelConfigForm.model = ''
  modelConfigForm.gateway_id = modelConfigForm.source === 'external_gateway' ? effectiveModelRouting.value.external_gateway_id : null
  if (modelConfigForm.source === 'internal') modelConfigForm.model = configurableModels.value[0]?.name || ''
}
const refreshExternalModels = async () => {
  if (externalModelsLoading.value || !detail.value?.client_id || !modelConfigTarget.value) return
  externalModelsLoading.value = true
  externalModelsError.value = ''
  try {
    const result = await prepareExternalModelCatalog(detail.value.client_id, {
      local_agent_id: modelConfigForm.local_agent_id,
      agent_type: modelConfigForm.agent_type,
      ...(modelConfigForm.managed_agent_id ? { managed_agent_id: modelConfigForm.managed_agent_id } : {}),
    })
    externalCatalog.value = result
    externalModels.value = (result.models || []).map(model => ({ ...model, name: model.name || model.id }))
    modelConfigForm.gateway_id = result.gateway?.id || effectiveModelRouting.value.external_gateway_id
    if (!externalModels.value.some(model => model.name === modelConfigForm.model)) modelConfigForm.model = externalModels.value[0]?.name || ''
  } catch (error) {
    externalCatalog.value = null
    externalModels.value = []
    modelConfigForm.model = ''
    externalModelsError.value = error.response?.data?.detail || i18n.global.t('externalModel.loadFailed')
  } finally { externalModelsLoading.value = false }
}
const createModelConfig = async () => {
  if (modelConfigSubmitting.value) return
  if (!modelConfigForm.model) {
    message.warning(i18n.global.t('clientModelConfig.selectModel'))
    return
  }
  modelConfigSubmitting.value = true
  try {
    const task = await createClientTask(detail.value.client_id, {
      task_type: 'apply_model_config',
      payload: { ...modelConfigForm },
    })
    modelConfigVisible.value = false
    await refreshDetail()
    message.success(i18n.global.t('clientModelConfig.taskCreated'))
    watchTask(task.id).catch(() => {})
  } catch (error) {
    message.error(error.response?.data?.detail || i18n.global.t('clientModelConfig.createFailed'))
  } finally {
    modelConfigSubmitting.value = false
  }
}
const createInstall = async () => {
  if (!installForm.skill_id) {
    message.warning(phrase('legacy.1xx9z2h'))
    return
  }
  submitting.value = true
  try {
    const task = await createClientTask(detail.value.client_id, {
      task_type: 'install_skill',
      payload: { ...installForm },
    })
    installVisible.value = false
    await refreshDetail()
    message.success(phrase('legacy.1f1g3u'))
    watchTask(task.id).catch(() => {})
  } finally {
    submitting.value = false
  }
}
const cancelTask = async (record) => {
  if (taskOperations.has(record.id)) return
  taskOperations.add(record.id)
  try {
    await cancelClientTask(detail.value.client_id, record.id)
    await refreshDetail()
    message.success(phrase('legacy.1v37glb'))
  } catch (error) { message.error(error.response?.data?.detail || i18n.global.t('clientGovernance.taskFailed')) }
  finally { taskOperations.delete(record.id) }
}
const retryTask = async (record) => {
  if (taskOperations.has(record.id)) return
  taskOperations.add(record.id)
  const clientId = detail.value.client_id
  try {
    const task = await retryClientTask(clientId, record.id)
    await refreshDetail()
    message.success(phrase('legacy.jtnoyu'))
    watchTask(task.id, clientId).catch(() => {})
  } catch (error) { message.error(error.response?.data?.detail || i18n.global.t('clientGovernance.taskFailed')) }
  finally { taskOperations.delete(record.id) }
}
const downloadClient = async ({ key }) => {
  const release = downloadPlatforms.value.find(item => item.key === key)
  if (!release || clientDownloading.value) return
  clientDownloading.value = true
  clientDownloadDetail.value = phrase('legacy.ix9qyw')
  try {
    const ticket = await createClientDownloadTicket(key)
    const link = document.createElement('a')
    link.href = ticket.url
    link.download = ticket.filename || release.filename || `agent-manager-client-${key}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    clientDownloadDetail.value = text(
      `正在下载 ${formatBytes(release.size)}，可在下载列表查看进度`,
      `Downloading ${formatBytes(release.size)}. Track progress in Downloads.`,
    )
    message.success(phrase('legacy.9cimn0'))
  } catch (error) {
    clientDownloadDetail.value = error?.response?.data?.detail || error?.message || phrase('legacy.1dqx4bv')
    message.error(text(
      `下载安装包失败：${clientDownloadDetail.value}`,
      `Installer download failed: ${clientDownloadDetail.value}`,
    ))
  } finally {
    clientDownloading.value = false
  }
}
const downloadSelectedClient = () => downloadClient({ key: selectedPlatform.value })

const managedAgentCount = record => record.agents?.filter(agent => agent.skill_management_supported && !isSharedSkillsRecord(agent)).length || 0
const skillCount = record => record.agents?.reduce((sum, agent) => sum + (agent.skills?.length || 0), 0) || 0
const sharedSkillsDescription = record => {
  const readers = record.capabilities?.shared_skill_readers || []
  return text(
    `${readers.join('、') || phrase('legacy.waagmd')} 可能读取，实际以版本和配置为准`,
    `${readers.join(', ') || phrase('legacy.waagmd')} may read this directory, depending on version and configuration.`,
  )
}
const agentSkills = agent => (agent.skills || []).map(skill => ({ ...skill, agent_type: agent.agent_type }))
const taskSkillName = task => task.payload?.skill_name
  || (detail.value?.agents || []).flatMap(agent => agent.skills || []).find(skill => skill.skill_id === task.payload?.skill_id)?.name
  || skills.value.find(skill => skill.skill_id === task.payload?.skill_id)?.name
  || task.payload?.skill_id
  || ''
const taskTargetLabel = task => task.task_type === 'sync_policy' ? '' : task.task_type === 'apply_model_config'
  ? `${task.payload?.model || '-'} · ${agentLabel(task.payload?.agent_type)}`
  : taskSkillName(task) ? `${taskSkillName(task)} · ${agentLabel(task.payload?.agent_type)}` : ''
const isOnline = record => record.status === 'online'
const formatTime = value => {
  if (!value) return '-'
  const text = String(value)
  const utcValue = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`
  return new Date(utcValue).toLocaleString(getCurrentLocale(), { timeZone: 'Asia/Shanghai', hour12: false })
}
const formatBytes = value => {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
const managedAgentDefaultModel = record => agents.value.find(agent => agent.agent_id === record.managed_agent_id)?.default_model || ''
const modelConfigStatusLabel = value => i18n.global.t(`clientModelConfig.status.${value}`)
const taskCannotCancel = task => task.status === 'running' && ['aidr_plugin_action', 'skill_action', 'remove_skill', 'install_skill', 'repair_skill', 'apply_model_config', 'verify_model_config', 'restore_model_config'].includes(task.task_type)
const modelErrorLabel = value => {
  if (!value) return '-'
  const code = String(value).match(/^model_config\.([a-z_]+)/)?.[1]
  if (!code) {
    const runtimeKey = `agentRuntimeGovernance.codes.${value}`
    return i18n.global.te(runtimeKey) ? `${i18n.global.t(runtimeKey)} (${value})` : i18n.global.t('clientGovernance.errorDetail', { error: String(value) })
  }
  const key = `clientModelConfig.errors.${code}`
  return `${i18n.global.t(i18n.global.te(key) ? key : 'clientModelConfig.errors.fallback')} (${value})`
}
const modelConfigColor = value => ({ pending: 'default', applying: 'blue', applied: 'blue', pending_restart: 'orange', verified: 'green', failed: 'red', cancelled: 'default' }[value] || 'default')
const agentLabel = (value, record = null) => record?.capabilities?.display_name || ({
  'claude-code': 'Claude Code',
  codex: 'Codex',
  gemini: 'Gemini CLI',
  opencode: 'OpenCode',
  openclaw: 'OpenClaw',
  hermes: 'Hermes',
  'trae-cn': 'TRAE CN',
  trae: 'TRAE',
  cursor: 'Cursor',
  'global-skills': phrase('legacy.13u0v7i'),
  codebuddy: 'CodeBuddy',
  workbuddy: 'WorkBuddy',
  teleagent: 'TeleAgent',
}[value] || value)
const policyDescription = mode => ({
  audit: phrase('legacy.mubbv4'),
  repair: phrase('legacy.1rf6q23'),
  block: phrase('legacy.souye8'),
}[mode])
const governanceDescription = mode => i18n.global.t(`clientGovernance.governanceModeDescription.${mode}`)
const governanceShortLabel = mode => ({ registry: phrase('legacy.2kc7ip'), strict: phrase('legacy.y5lawk') }[mode] || phrase('legacy.2kc7ip'))
const governanceEventValue = value => i18n.global.te(`clientGovernance.${value}`) ? i18n.global.t(`clientGovernance.${value}`) : value || '-'
const taskLabel = task => {
  if (task.task_type === 'skill_action') return governanceEventValue(task.payload?.action)
  if (task.task_type === 'rescan' && task.payload?.reason === 'policy_changed') return phrase('legacy.q9utgp')
  return translateDomain('taskType', task.task_type, task.task_type)
}
const taskStatusLabel = (value, task) => task?.task_type === 'sync_policy' && task.error === 'policy_superseded'
  ? i18n.global.t('clientGovernance.superseded') : task?.task_type === 'sync_policy' && value === 'succeeded'
    ? i18n.global.t('clientGovernance.policyApplied') : translateDomain('taskStatus', value, value)
const taskColor = value => ({ pending: 'default', running: 'blue', succeeded: 'green', failed: 'red', cancelled: 'default' }[value] || 'default')

watch(() => [route.query.client, route.query.section], async ([clientId, section]) => {
  if (typeof clientId !== 'string' || !hasAccess('clients:view') || !['overview', 'control', 'audit', 'plugins', 'skills'].includes(section)) return
  try {
    await openDetail({ client_id: clientId })
    if (route.query.client === clientId && detail.value?.client_id === clientId) runtimeTab.value = section
  } catch { message.error(i18n.global.t('agentWorkspace.readFailed')) }
}, { immediate: true })

onMounted(async () => {
  const [agentRows, downloads, tokenRows, models] = await Promise.all([
    listAgents(),
    listClientDownloads(),
    listAccessTokens(),
    listModelEndpoints(),
    loadClients(),
  ])
  agents.value = agentRows || []
  downloadPlatforms.value = downloads.items || []
  accessTokens.value = tokenRows.items || []
  modelEndpoints.value = models || []
})
</script>

<style scoped>
.detail-config-actions { flex-shrink: 0; margin-left: auto; }
.summary-row { margin-top: 8px; }
.table-card {
  margin-top: 16px;
}
.muted {
  color: #7a869a;
  font-size: 12px;
}
.model-error {
  max-width: 160px;
  word-break: break-word;
}
.model-catalog-state { margin-top: 12px; }
.model-call-note { margin: 8px 0; }
.client-inventory-table :deep(td) { overflow-wrap: anywhere; }
.client-inventory-table :deep(th) { white-space: normal; overflow-wrap: normal; word-break: normal; }
.inventory-column-heading { display: inline-flex; align-items: center; gap: 8px; }
.inventory-help-trigger { display: inline-flex; align-items: center; justify-content: center; padding: 3px; border: 0; border-radius: 4px; background: transparent; color: #626b78; font-size: 13px; cursor: help; }
.inventory-help-trigger:hover { color: #245eea; background: #eef4ff; }
.inventory-help-trigger:focus-visible { outline: 2px solid #245eea; outline-offset: 2px; }
.inventory-column-help { width: 300px; max-width: calc(100vw - 64px); font-size: 13px; line-height: 1.65; white-space: normal; overflow-wrap: break-word; }
.inventory-column-help dl { display: grid; gap: 14px; margin: 0; }
.inventory-column-help dt { margin-bottom: 4px; color: #253248; font-weight: 600; }
.inventory-column-help dd { margin: 0; color: #526078; }
.inventory-column-help p { margin: 14px 0 0; padding-top: 10px; border-top: 1px solid #e8edf3; color: #626b78; }
.inventory-counts { display: grid; gap: 6px; margin: 0; }
.inventory-counts > div { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; gap: 12px; }
.inventory-counts dt { overflow-wrap: normal; word-break: normal; }
.inventory-counts dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.inventory-count-secondary { color: #626b78; font-size: 12px; }
.inventory-count-secondary dd { font-weight: 400; }
.client-download-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 470px;
  margin-top: 14px;
}
.client-download-progress span {
  color: #7a869a;
  font-size: 12px;
}
.detail-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.detail-head > :first-child { flex: 1 1 280px; min-width: 0; overflow-wrap: anywhere; }
.session-audit-layout { flex: 1; min-height: 0; }
.session-audit-layout :deep(.ant-spin-container) { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.session-audit-layout .detail-head { flex-shrink: 0; gap: 8px; }
.session-audit-layout .detail-title { font-size: 17px; }
.session-audit-layout .device-status-line { flex-shrink: 0; margin: 4px 0; font-size: 12px; }
.session-audit-layout .device-runtime-tabs { flex: 1; min-height: 0; }
.session-audit-layout .device-runtime-tabs :deep(.ant-tabs-nav) { flex-shrink: 0; margin-bottom: 8px; }
.session-audit-layout .device-runtime-tabs :deep(.ant-tabs-tab) { padding-top: 8px; padding-bottom: 8px; }
.session-audit-layout .device-runtime-tabs :deep(.ant-tabs-content-holder),
.session-audit-layout .device-runtime-tabs :deep(.ant-tabs-content),
.session-audit-layout .device-runtime-tabs :deep(.ant-tabs-tabpane-active) { height: 100%; min-height: 0; }
.agent-skill-table { width: min(984px, calc(100vw - 96px)); max-width: 100%; }
.agent-skill-table :deep(td) { overflow-wrap: anywhere; }
.local-agents-table :deep(.ant-tag) { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.local-agents-table :deep(.ant-space-vertical), .local-agents-table :deep(.ant-space-item) { max-width: 100%; }
.local-agents-table :deep(.ant-btn-link) { max-width: 100%; height: auto; white-space: normal; text-align: left; overflow-wrap: anywhere; }
.skill-policy-controls > label { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; max-width: 100%; }
.inventory-navigation { margin: 12px 0; }
.inventory-navigation { display: flex; flex-wrap: wrap; }
.inventory-navigation :deep(.ant-radio-button-wrapper), .skill-policy-controls :deep(.ant-radio-button-wrapper) { height: auto; white-space: normal; }
.governance-select { width: 270px; max-width: 100%; }
.device-title-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.device-title-line .ant-tag { margin: 0; }
.device-status-line { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; margin: 6px 0 12px; color: #627480; }
.device-info-content { max-width: min(360px, calc(100vw - 64px)); overflow-wrap: anywhere; }
.device-info-content code { user-select: text; }
.detail-panel-heading, .skill-policy-controls { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center; margin: 16px 0; }
.detail-panel-heading p { margin: 0; flex: 1; color: #627480; }
.detail-view-switch { display: flex; flex-wrap: wrap; margin: 16px 0; }
.detail-view-switch :deep(.ant-radio-button-wrapper) { height: auto; white-space: normal; }
.detail-title {
  color: #16324f;
  font-size: 20px;
  font-weight: 650;
}
.policy-controls {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  margin-left: auto;
  max-width: 100%;
  gap: 12px;
}
.policy-controls label > span {
  display: block;
  margin-bottom: 5px;
  color: #7a869a;
  font-size: 12px;
}
.skill-option-time {
  float: right;
  margin-left: 16px;
  color: #7a869a;
  font-size: 12px;
}
.policy-note {
  margin-top: 16px;
}
.section-title {
  border-left: 3px solid #1c6ea4;
  font-weight: 650;
  margin: 24px 0 12px;
  padding-left: 10px;
}
.event-more {
  margin-top: -8px;
  text-align: center;
}
.model-config-preview { max-height: 240px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
.model-config-evidence { min-width: 0; margin-top: 8px; }
.model-config-evidence summary { cursor: pointer; }
.model-config-evidence pre { max-height: 240px; max-width: 480px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; }
.ellipsis {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
