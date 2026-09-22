<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.hx2vnc')" :sub-title="$t('legacy.ud53vr')">
          <template #extra>
            <a-button v-if="hasAccess('clients:update')" @click="discoveryOpen = true">{{ $t('clientDiscovery.title') }}</a-button>
            <a-button v-if="hasAccess('clients:update')" @click="openClassification('')">{{ $t('clientGovernance.defaults') }}</a-button>
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
      <a-table :columns="columns" :data-source="clients" row-key="client_id" :loading="loading" :pagination="{ pageSize: 10 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'client'">
            <a @click="openDetail(record)">{{ record.name }}</a>
            <div class="muted">{{ record.hostname }} · {{ record.client_id }}</div>
          </template>
          <template v-else-if="column.key === 'platform'">
            <div>{{ record.os }} / {{ record.arch }}</div>
            <div class="muted">{{ governanceShortLabel(record.governance_mode) }} · Client {{ record.client_version }}</div>
          </template>
          <template v-else-if="column.key === 'agents'">
            <span>{{ actualAgentCount(record) }} {{ $t("legacy.d5a1x9") }}</span>
            <span class="muted inline-note">{{ $t("legacy.mhoty8") }}{{ managedAgentCount(record) }}</span>
            <span v-if="sharedSkillsCount(record)" class="muted inline-note">{{ $t("legacy.1mn8gxl") }}{{ sharedSkillsCount(record) }}</span>
          </template>
          <template v-else-if="column.key === 'skills'">{{ skillCount(record) }}</template>
          <template v-else-if="column.key === 'credentialOwner'">{{ record.registered_by || '-' }}</template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="isOnline(record) ? 'green' : 'default'">{{ isOnline(record) ? $t('legacy.hf6go') : $t('legacy.1hsp9j3') }}</a-tag>
          </template>
          <template v-else-if="column.key === 'lastSeen'">{{ formatTime(record.last_seen_at) }}</template>
          <template v-else-if="column.key === 'action'">
            <a @click="openDetail(record)">{{ $t("legacy.10fbkvl") }}</a>
          </template>
        </template>
      </a-table>
    </section>

    </a-card>
    <ClientDiscoveryConfig v-model:open="discoveryOpen" />

    <a-drawer v-model:open="detailVisible" :title="$t('legacy.95lv9i')" width="min(1080px, 100vw)" :destroy-on-close="true">
      <a-spin :spinning="detailLoading">
        <template v-if="detail">
          <div class="detail-head">
            <div>
              <div class="detail-title">{{ detail.name }}</div>
              <div class="muted">{{ detail.hostname }} · {{ detail.os }}/{{ detail.arch }} · {{ detail.client_id }}</div>
              <div class="muted">{{ $t("legacy.4xeakj") }}{{ detail.registered_by || '-' }}</div>
            </div>
            <div class="policy-controls">
              <label>
                <span>{{ $t("legacy.1bb65oo") }}</span>
                <a-select :value="currentGovernance" style="width: 170px" @change="saveGovernance">
                  <a-select-option value="registry">{{ $t("legacy.12wr3db") }}</a-select-option>
                  <a-select-option value="strict">{{ $t("legacy.1bqmand") }}</a-select-option>
                </a-select>
              </label>
              <a-button @click="openClassification(detail.client_id)">{{ $t('clientGovernance.title') }}</a-button>
              <a-button @click="refreshDetail">{{ $t("legacy.2fhcc7") }}</a-button>
            </div>
          </div>

          <a-alert
            type="info"
            show-icon
            class="policy-note"
            :message="detail.classification?.enabled ? $t('clientGovernance.active') : policyDescription(currentPolicy)"
            :description="governanceDescription(currentGovernance)"
          />

          <div class="section-title">{{ $t("legacy.4ig27k") }}</div>
          <a-table class="local-agents-table" :columns="agentColumns" :data-source="detail.agents || []" :row-key="row => row.local_agent_id || row.agent_type" size="small" :pagination="false" :expandable="agentTableExpandable" :scroll="{ x: 760 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <strong>{{ agentLabel(record.agent_type, record) }}</strong>
                <a-tag v-if="isSharedSkillsRecord(record)" color="blue">{{ $t("legacy.y5th5l") }}</a-tag>
                <div class="muted">{{ isSharedSkillsRecord(record) ? sharedSkillsDescription(record) : (record.version || $t('legacy.g4nqyc')) }}</div>
              </template>
              <template v-else-if="column.key === 'capability'">
                <a-tag :color="record.skill_management_supported ? 'green' : 'default'">
                  {{ record.skill_management_supported ? $t('legacy.1uut84r') : $t('legacy.lp0s29') }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'model'">
                <div>{{ record.applied_model || record.desired_model || managedAgentDefaultModel(record) || '-' }}</div>
                <a-tag v-if="record.model_config_status && record.model_config_status !== 'not_configured'" :color="modelConfigColor(record.model_config_status)">
                  {{ modelConfigStatusLabel(record.model_config_status) }}
                </a-tag>
                <div v-if="record.model_config_error" class="muted model-error">{{ modelErrorLabel(record.model_config_error) }}</div>
                <details v-if="record.capabilities?.model_config_state?.verification?.length" class="model-config-evidence">
                  <summary>{{ $t('clientModelConfig.evidence') }}</summary>
                  <pre>{{ JSON.stringify(record.capabilities.model_config_state.verification, null, 2) }}</pre>
                </details>
              </template>
              <template v-else-if="column.key === 'skills'">{{ record.skills?.length || 0 }}</template>
              <template v-else-if="column.key === 'action'">
                <a-space direction="vertical" size="small">
                  <a-button v-if="hasAccess('clients:execute')"
                    type="link"
                    :disabled="!record.skill_management_supported || (currentGovernance === 'strict' && isSharedSkillsRecord(record))"
                    :title="currentGovernance === 'strict' && isSharedSkillsRecord(record) ? $t('legacy.13rv9dd') : ''"
                    @click="openInstall(record)"
                  >{{ $t("legacy.1byrs80") }}</a-button>
                  <a-button v-if="hasAccess('clients:execute')"
                    type="link"
                    :disabled="!canConfigureModel(record)"
                    :title="modelConfigDisabledReason(record)"
                    @click="openModelConfig(record)"
                  >{{ $t('clientModelConfig.action') }}</a-button>
                  <a-button v-if="hasAccess('clients:execute') && record.capabilities?.model_config_verification && record.capabilities?.model_config_state?.change_id" type="link" :loading="modelOperationBusy === record.local_agent_id + ':verify_model_config'" :disabled="!!modelOperationBusy" @click="runModelOperation(record, 'verify_model_config')">{{ $t('clientModelConfig.verify') }}</a-button>
                  <a-button v-if="hasAccess('clients:execute') && record.capabilities?.model_config_state?.change_id" type="link" :loading="modelOperationBusy === record.local_agent_id + ':restore_model_config'" :disabled="!!modelOperationBusy || !record.capabilities?.model_config_state?.can_restore" @click="runModelOperation(record, 'restore_model_config')">{{ $t('clientModelConfig.restore') }}</a-button>

                </a-space>
              </template>
            </template>
            <template #expandedRowRender="{ record: agentRecord }">
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
          </a-table>

          <div class="section-title">{{ $t('clientGovernance.recoveryCopies') }}</div>
          <a-table :columns="recoveryColumns" :data-source="detail.recovery || []" row-key="id" size="small" :pagination="{ pageSize: 6 }" :scroll="{ x: 650 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'action'">
                <ClientSkillActions :client="detail" :agent="recoveryAgent(record)" :skill="record" recovery @created="skillActionCreated" />
              </template>
            </template>
          </a-table>

          <div class="section-title">{{ $t("legacy.uiriue") }}</div>
          <a-table :columns="taskColumns" :data-source="detail.tasks || []" row-key="id" size="small" :pagination="{ pageSize: 6 }">
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

          <div class="section-title">{{ $t("legacy.1hnc5z3") }}</div>
          <a-spin :spinning="eventsLoading">
          <a-timeline v-if="detail.events?.length">
            <a-timeline-item v-for="event in detail.events" :key="event.id" :color="eventColor(event)">
              <strong>{{ eventLabel(event.event_type) }}</strong>
              <span v-if="event.skill_name"> · {{ event.skill_name }}</span>
              <div class="muted">{{ formatTime(event.created_at) }}</div>
              <div v-if="event.details?.trigger" class="muted">{{ governanceEventValue(event.details.trigger) }} · {{ governanceEventValue(event.details.action) }}</div>
              <div v-if="event.observation_count > 1" class="muted">{{ $t('clientGovernance.observations', { count: event.observation_count }) }} · {{ $t('clientGovernance.lastSeen', { time: formatTime(event.last_seen_at) }) }}</div>
            </a-timeline-item>
          </a-timeline>
          <a-empty v-else :description="$t('legacy.1fxykwc')" />
          <a-pagination v-if="detail.events_total" class="event-more" :current="detail.event_page" :page-size="detail.event_page_size" :total="detail.events_total" :show-size-changer="false" :disabled="eventsLoading" @change="changeEventPage" />
          </a-spin>
        </template>
      </a-spin>
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
    <ClientGovernancePolicy v-model:open="classificationOpen" :client-id="classificationClientId" @saved="loadClients(); detailVisible && refreshDetail()" />
</template>

<script setup>
import { modelLabel } from '../utils/modelLabels'
import { can as hasAccess } from '../access'
import ClientGovernancePolicy from '../components/ClientGovernancePolicy.vue'
import ClientSkillScan from '../components/ClientSkillScan.vue'
import ClientSkillActions from '../components/ClientSkillActions.vue'
import {
  getCurrentLocale,
  i18n,
  translateDomain,
  translateLegacy as phrase,
  translateText as text,
} from '../i18n'

import ClientDiscoveryConfig from '../components/ClientDiscoveryConfig.vue'
import { computed, onMounted, reactive, ref } from 'vue'
const discoveryOpen = ref(false)
import { message } from 'ant-design-vue'

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
const openClassification = clientId => { classificationClientId.value = clientId; classificationOpen.value = true }
const detailLoading = ref(false)
const submitting = ref(false)
const eventsLoading = ref(false)
let eventSequence = 0
const detailVisible = ref(false)
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

const columns = [
  { title: phrase('legacy.tus94r'), key: 'client' },
  { title: phrase('legacy.p0ysv3'), key: 'platform', width: 170 },
  { title: 'Agent', key: 'agents', width: 160 },
  { title: 'Skill', key: 'skills', width: 90 },
  { title: phrase('legacy.1mk8o97'), key: 'credentialOwner', width: 120 },
  { title: phrase('legacy.1ccx4t4'), key: 'status', width: 90 },
  { title: phrase('legacy.12y43gp'), key: 'lastSeen', width: 180 },
  { title: phrase('legacy.501w24'), key: 'action', width: 80 },
]
const agentColumns = [
  { title: phrase('legacy.tus94r'), key: 'type' },
  { title: phrase('legacy.uwo0jt'), key: 'capability', width: 150 },
  { title: i18n.global.t('clientModelConfig.model'), key: 'model', width: 160 },
  { title: 'Skill', key: 'skills', width: 70 },
  { title: phrase('legacy.501w24'), key: 'action', width: 150, fixed: 'right' },
]
const skillColumns = [
  { title: 'Skill', key: 'name' },
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
const agentTableExpandable = { rowExpandable: record => Boolean(record.skills?.length) }
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
  const sequence = ++detailSequence
  ++eventSequence
  eventsLoading.value = false
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
const refreshDetail = async () => {
  if (!detail.value?.client_id) return
  const clientId = detail.value.client_id
  const sequence = ++detailSequence
  const eventsRequest = eventSequence
  const result = await getClientDetail(clientId, { event_page: detail.value.event_page || 1 })
  if (sequence !== detailSequence || !detailVisible.value || detail.value?.client_id !== clientId) return
  if (eventsLoading.value || eventsRequest !== eventSequence) {
    Object.assign(result, { events: detail.value.events, events_total: detail.value.events_total, event_page: detail.value.event_page, event_page_size: detail.value.event_page_size })
  }
  detail.value = result
  currentPolicy.value = detail.value.policy_mode || 'audit'
  currentGovernance.value = detail.value.governance_mode || 'registry'
}
const changeEventPage = async page => {
  const clientId = detail.value?.client_id
  if (!clientId || eventsLoading.value) return
  const sequence = ++eventSequence
  eventsLoading.value = true
  try {
    const result = await getClientDetail(clientId, { event_page: page })
    if (sequence !== eventSequence || !detailVisible.value || detail.value?.client_id !== clientId) return
    Object.assign(detail.value, { events: result.events, events_total: result.events_total, event_page: result.event_page, event_page_size: result.event_page_size })
  } catch {
    if (sequence === eventSequence) message.error(i18n.global.t('clientGovernance.eventsLoadFailed'))
  } finally {
    if (sequence === eventSequence) eventsLoading.value = false
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
const taskCannotCancel = task => task.status === 'running' && ['skill_action', 'remove_skill', 'install_skill', 'repair_skill', 'apply_model_config', 'verify_model_config', 'restore_model_config'].includes(task.task_type)
const modelErrorLabel = value => {
  if (!value) return '-'
  const code = String(value).match(/^model_config\.([a-z_]+)/)?.[1]
  if (!code) return value
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
const governanceDescription = mode => t(`clientGovernance.governanceModeDescription.${mode}`)
const governanceShortLabel = mode => ({ registry: phrase('legacy.2kc7ip'), strict: phrase('legacy.y5lawk') }[mode] || phrase('legacy.2kc7ip'))
const eventLabel = value => ['skill_governance_recorded', 'skill_governance_detected', 'skill_governance_action', 'skill_scan_submitted'].includes(value)
  ? i18n.global.t(`clientGovernance.${value}`)
  : translateDomain('auditEvent', value, value)
const governanceEventValue = value => i18n.global.te(`clientGovernance.${value}`) ? i18n.global.t(`clientGovernance.${value}`) : value || '-'
const eventColor = event => event.details?.action === 'record_only' ? 'default' : event.details?.trigger === 'malicious' || event.details?.status === 'failed' || ['skill_blocked', 'skill_quarantined'].includes(event.event_type)
  ? 'red' : ['skill_modified', 'skill_governance_detected'].includes(event.event_type) ? 'orange' : 'green'
const taskLabel = task => {
  if (task.task_type === 'skill_action') return governanceEventValue(task.payload?.action)
  if (task.task_type === 'rescan' && task.payload?.reason === 'policy_changed') return phrase('legacy.q9utgp')
  return translateDomain('taskType', task.task_type, task.task_type)
}
const taskStatusLabel = (value, task) => task?.task_type === 'sync_policy' && task.error === 'policy_superseded'
  ? i18n.global.t('clientGovernance.superseded') : task?.task_type === 'sync_policy' && value === 'succeeded'
    ? i18n.global.t('clientGovernance.policyApplied') : translateDomain('taskStatus', value, value)
const taskColor = value => ({ pending: 'default', running: 'blue', succeeded: 'green', failed: 'red', cancelled: 'default' }[value] || 'default')

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
.inline-note {
  margin-left: 8px;
}
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
.detail-head > :first-child { min-width: 0; overflow-wrap: anywhere; }
.agent-skill-table { width: min(984px, calc(100vw - 96px)); max-width: 100%; }
.agent-skill-table :deep(td) { overflow-wrap: anywhere; }
.local-agents-table :deep(.ant-tag) { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
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
