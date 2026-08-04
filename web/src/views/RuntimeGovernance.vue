<template>
  <div>
    <a-page-header :title="$t('legacy.ppwp4v')" :sub-title="$t('legacy.1n3dozp')" />

    <a-card :title="$t('legacy.1b4zqhb')" style="margin-top: 16px">
      <template #extra>
        <a-button type="primary" :loading="guardDownloading" @click="handleSkillGuardDownload">{{ $t("legacy.ayz2ay") }}</a-button>
      </template>
      <a-alert
        type="info"
        show-icon
        :message="$t('legacy.8z0qky')"
        :description="$t('legacy.17ymjuz')"
        style="margin-bottom: 16px"
      />
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">{{ $t("legacy.bgbtdd") }}</div>
            <p class="hint">{{ $t("legacy.tj8mcw") }}</p>
            <a-space wrap>
              <a-tag v-for="scope in skillGuardScopes" :key="scope" color="blue">{{ scope }}</a-tag>
            </a-space>
          </div>
        </a-col>
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">{{ $t("legacy.1qkyade") }}</div>
            <p class="hint">{{ $t("legacy.45l7xs") }}</p>
            <a-tabs size="small">
              <a-tab-pane key="codex" tab="Codex">
                <pre class="code-block compact">{{ codexGuardInstallCommand }}</pre>
              </a-tab-pane>
              <a-tab-pane key="claude" tab="Claude Code">
                <pre class="code-block compact">{{ claudeGuardInstallCommand }}</pre>
              </a-tab-pane>
            </a-tabs>
          </div>
        </a-col>
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">{{ $t("legacy.vzsacv") }}</div>
            <p class="hint">{{ $t("legacy.887oam") }}</p>
            <pre class="code-block compact">{{ guardUsageCommand }}</pre>
          </div>
        </a-col>
      </a-row>
    </a-card>

    <a-card :title="$t('runtimeGovernance.title')" style="margin-top: 16px">
      <template #extra>
        <a-button :loading="governanceLoading" @click="fetchGovernanceData">{{ $t("legacy.16mfmhy") }}</a-button>
      </template>
      <a-alert type="info" show-icon :message="$t('runtimeGovernance.subtitle')" style="margin-bottom: 16px" />
      <a-tabs>
        <a-tab-pane key="tasks" :tab="$t('runtimeGovernance.tasks')">
          <a-alert
            v-if="replayResult"
            type="success"
            closable
            :message="$t('runtimeGovernance.replayResult')"
            :description="`${$t('runtimeGovernance.changedActions')}: ${replayResult.changed_count}`"
            style="margin-bottom: 12px"
            @close="replayResult = null"
          />
          <a-table :data-source="runtimeTasks" :columns="runtimeTaskColumns" row-key="task_id" :pagination="{ pageSize: 8 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : record.status === 'killed' ? 'red' : 'default'">{{ record.status }}</a-tag>
              </template>
              <template v-else-if="column.key === 'usage'">
                {{ record.usage?.steps || 0 }}/{{ record.policy?.max_steps || '-' }} · {{ record.usage?.data_bytes || 0 }} B
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button size="small" @click="handleTaskDetail(record)">{{ $t("runtimeGovernance.details") }}</a-button>
                  <a-button size="small" @click="handleReplay(record)">{{ $t("runtimeGovernance.replay") }}</a-button>
                  <a-popconfirm :title="$t('runtimeGovernance.killConfirm')" @confirm="handleKillTask(record)">
                    <a-button size="small" danger :disabled="record.status !== 'active'">{{ $t("runtimeGovernance.kill") }}</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="switches" :tab="$t('runtimeGovernance.killSwitches')">
          <a-space wrap style="margin-bottom: 16px">
            <a-select v-model:value="killSwitchForm.scope_type" style="width: 140px">
              <a-select-option value="global">{{ $t("runtimeGovernance.global") }}</a-select-option>
              <a-select-option value="tenant">{{ $t("runtimeGovernance.tenant") }}</a-select-option>
              <a-select-option value="user">{{ $t("runtimeGovernance.user") }}</a-select-option>
              <a-select-option value="agent">{{ $t("runtimeGovernance.agent") }}</a-select-option>
              <a-select-option value="tool">{{ $t("runtimeGovernance.tool") }}</a-select-option>
            </a-select>
            <a-input v-model:value="killSwitchForm.scope_id" :placeholder="$t('runtimeGovernance.scopeId')" style="width: 200px" />
            <a-input v-model:value="killSwitchForm.reason" :placeholder="$t('runtimeGovernance.reason')" style="width: 280px" />
            <a-button type="primary" danger @click="handleCreateKillSwitch">{{ $t("runtimeGovernance.activate") }}</a-button>
          </a-space>
          <a-table :data-source="killSwitches" :pagination="false" row-key="id">
            <a-table-column key="scope" :title="$t('runtimeGovernance.scope')">
              <template #default="{ record }">{{ record.scope_type }}:{{ record.scope_id }}</template>
            </a-table-column>
            <a-table-column data-index="reason" key="reason" :title="$t('runtimeGovernance.reason')" />
            <a-table-column key="active" :title="$t('runtimeGovernance.status')">
              <template #default="{ record }"><a-tag :color="record.active ? 'red' : 'default'">{{ record.active ? 'active' : 'released' }}</a-tag></template>
            </a-table-column>
            <a-table-column key="actions" :title="$t('runtimeGovernance.actions')">
              <template #default="{ record }"><a-button size="small" :disabled="!record.active" @click="handleReleaseKillSwitch(record)">{{ $t("runtimeGovernance.release") }}</a-button></template>
            </a-table-column>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="memory" :tab="$t('runtimeGovernance.memories')">
          <a-table :data-source="runtimeMemories" row-key="memory_id" :pagination="{ pageSize: 8 }">
            <a-table-column data-index="source_type" key="source" :title="$t('runtimeGovernance.source')" />
            <a-table-column data-index="content" key="content" :title="$t('runtimeGovernance.content')" ellipsis />
            <a-table-column key="trust" :title="$t('runtimeGovernance.trust')">
              <template #default="{ record }"><a-tag :color="memoryTrustColor(record.trust_status)">{{ $t(`runtimeGovernance.${record.trust_status}`) }}</a-tag></template>
            </a-table-column>
            <a-table-column key="actions" :title="$t('runtimeGovernance.actions')">
              <template #default="{ record }">
                <a-space>
                  <a-button size="small" type="primary" :disabled="record.trust_status === 'trusted'" @click="handleReviewMemory(record, 'trusted')">{{ $t("runtimeGovernance.approve") }}</a-button>
                  <a-button size="small" danger :disabled="record.trust_status === 'quarantined'" @click="handleReviewMemory(record, 'quarantined')">{{ $t("runtimeGovernance.quarantine") }}</a-button>
                </a-space>
              </template>
            </a-table-column>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="policies" :tab="$t('runtimeGovernance.policies')">
          <a-select v-model:value="selectedPolicyAgent" :placeholder="$t('runtimeGovernance.selectAgent')" style="width: 320px; margin-bottom: 16px" @change="loadSelectedPolicy">
            <a-select-option v-for="agent in managedAgents" :key="agent.agent_id" :value="agent.agent_id">{{ agent.name }} ({{ agent.agent_id }})</a-select-option>
          </a-select>
          <a-form v-if="selectedPolicyAgent" layout="vertical">
            <a-row :gutter="16">
              <a-col v-for="field in policyFields" :key="field.key" :xs="24" :md="8">
                <a-form-item :label="$t(field.label)"><a-input-number v-model:value="runtimePolicy[field.key]" :min="field.min" :max="field.max" style="width: 100%" /></a-form-item>
              </a-col>
            </a-row>
            <a-button type="primary" @click="handleSavePolicy">{{ $t("runtimeGovernance.save") }}</a-button>
          </a-form>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <a-drawer v-model:open="taskDetailVisible" :title="$t('runtimeGovernance.details')" width="760">
      <a-descriptions v-if="taskDetail" bordered :column="2" size="small" style="margin-bottom: 16px">
        <a-descriptions-item :label="$t('runtimeGovernance.taskId')">{{ taskDetail.task_id }}</a-descriptions-item>
        <a-descriptions-item :label="$t('runtimeGovernance.agent')">{{ taskDetail.agent_id }}</a-descriptions-item>
        <a-descriptions-item :label="$t('runtimeGovernance.goal')" :span="2">{{ taskDetail.original_goal }}</a-descriptions-item>
      </a-descriptions>
      <a-table v-if="taskDetail" :data-source="taskDetail.actions || []" row-key="action_id" :pagination="false" size="small">
        <a-table-column data-index="action_type" key="action" :title="$t('runtimeGovernance.actions')" />
        <a-table-column data-index="target" key="target" :title="$t('runtimeGovernance.actualTarget')" ellipsis />
        <a-table-column key="effects" :title="$t('runtimeGovernance.expectedEffects')">
          <template #default="{ record }">{{ (record.expected_side_effects || []).join(', ') || '-' }}</template>
        </a-table-column>
        <a-table-column key="approval" :title="$t('runtimeGovernance.approvalContext')">
          <template #default="{ record }">{{ record.approval_context?.approved_by || '-' }}</template>
        </a-table-column>
      </a-table>
    </a-drawer>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24">
        <a-card :title="$t('legacy.wz9nkl')">
          <a-space style="margin-bottom: 16px" wrap>
            <a-select v-model:value="eventFilter" style="width: 220px" @change="handleAuditFilterChange">
              <a-select-option value="all">{{ $t("legacy.1jb5dqs") }}</a-select-option>
              <a-select-option v-for="option in runtimeEventOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </a-select-option>
            </a-select>
            <a-input v-model:value="auditKeyword" :placeholder="$t('legacy.5yag5')" style="width: 240px" allow-clear />
            <a-button type="primary" @click="fetchRuntimeAudit" :loading="loadingAudit">{{ $t("legacy.16mfmhy") }}</a-button>
            <a-button @click="resetAuditFilters" :disabled="loadingAudit">{{ $t("legacy.1wq9feq") }}</a-button>
          </a-space>

          <div class="table-meta">{{ $t("legacy.1vsm2qk") }} {{ auditTotal }} {{ $t("legacy.1tz183z") }}</div>

          <a-table
            :data-source="auditRows"
            :columns="auditColumns"
            rowKey="event_id"
            :loading="loadingAudit"
            :pagination="auditPagination"
            :locale="{ emptyText: $t('legacy.1qzv31n') }"
            @change="handleAuditTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'skill_name'">
                <a v-if="record.skill_id && record.skill_id !== 'unknown'" @click="$router.push(`/skills/${record.skill_id}`)">
                  {{ record.skill_name }}
                </a>
                <span v-else>{{ record.skill_name }}</span>
              </template>
              <template v-else-if="column.key === 'event_type'">
                <a-tag :color="runtimeEventColor(record.event_type)">{{ runtimeEventLabel(record.event_type) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'agent_id'">
                <span>{{ auditAgent(record) }}</span>
              </template>
              <template v-else-if="column.key === 'client_ip'">
                <span>{{ auditIp(record) }}</span>
              </template>
              <template v-else-if="column.key === 'actor'">
                <span>{{ auditActor(record) }}</span>
              </template>
              <template v-else-if="column.key === 'details'">
                <span>{{ formatRuntimeDetails(record.details) }}</span>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { i18n, translateLegacy as phrase, translateText as text } from '../i18n'

import { onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import {
  createRuntimeKillSwitch,
  downloadSkillVerifier,
  getAuditPaged,
  getRuntimePolicy,
  getRuntimeTask,
  killRuntimeTask,
  listAgents,
  listRuntimeKillSwitches,
  listRuntimeMemories,
  listRuntimeTasks,
  releaseRuntimeKillSwitch,
  replayRuntimeTask,
  reviewRuntimeMemory,
  updateRuntimePolicy,
} from '../api'
import { formatDateTime } from '../utils/format'

const loadingAudit = ref(false)
const guardDownloading = ref(false)
const governanceLoading = ref(false)
const runtimeTasks = ref([])
const killSwitches = ref([])
const runtimeMemories = ref([])
const managedAgents = ref([])
const replayResult = ref(null)
const taskDetailVisible = ref(false)
const taskDetail = ref(null)
const selectedPolicyAgent = ref(undefined)
const killSwitchForm = ref({ scope_type: 'global', scope_id: '*', reason: '' })
const runtimePolicy = ref({})
const i18nLabel = key => i18n.global.t(key)

const runtimeTaskColumns = [
  { title: phrase('legacy.1f90xvr'), dataIndex: 'created_at', key: 'created_at', width: 180, customRender: ({ text }) => formatDateTime(text) },
  { title: i18nLabel('runtimeGovernance.taskId'), dataIndex: 'task_id', key: 'task_id', ellipsis: true },
  { title: i18nLabel('runtimeGovernance.agent'), dataIndex: 'agent_id', key: 'agent_id', width: 150 },
  { title: i18nLabel('runtimeGovernance.goal'), dataIndex: 'original_goal', key: 'goal', ellipsis: true },
  { title: i18nLabel('runtimeGovernance.status'), dataIndex: 'status', key: 'status', width: 110 },
  { title: i18nLabel('runtimeGovernance.usage'), key: 'usage', width: 170 },
  { title: i18nLabel('runtimeGovernance.actions'), key: 'actions', width: 280 },
]

const policyFields = [
  { key: 'max_steps', label: 'runtimeGovernance.maxSteps', min: 1, max: 10000 },
  { key: 'max_retries', label: 'runtimeGovernance.maxRetries', min: 0, max: 100 },
  { key: 'max_delegation_depth', label: 'runtimeGovernance.delegationDepth', min: 0, max: 32 },
  { key: 'max_cost_microunits', label: 'runtimeGovernance.maxCost', min: 0 },
  { key: 'max_data_bytes', label: 'runtimeGovernance.maxData', min: 0 },
  { key: 'max_duration_seconds', label: 'runtimeGovernance.maxDuration', min: 1, max: 604800 },
  { key: 'circuit_failure_threshold', label: 'runtimeGovernance.failureThreshold', min: 1, max: 1000 },
  { key: 'circuit_cooldown_seconds', label: 'runtimeGovernance.cooldown', min: 1, max: 86400 },
  { key: 'goal_drift_threshold', label: 'runtimeGovernance.driftThreshold', min: 0, max: 1 },
]

const auditRows = ref([])
const auditTotal = ref(0)
const eventFilter = ref('all')
const auditKeyword = ref('')
const auditSortState = ref({ field: 'timestamp', order: 'descend' })
const skillGuardScopes = ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool']
const runtimeApiOrigin = (() => {
  const { protocol, hostname, port } = window.location
  if ((hostname === 'localhost' || hostname === '127.0.0.1') && (port === '5173' || port === '5174')) {
    return `${protocol}//${hostname}:8001`
  }
  return window.location.origin
})()
const codexGuardInstallCommand = `mkdir -p ~/.codex/skills
unzip agent-manager-skill-verifier.zip -d ~/.codex/skills/

export AGENT_MANAGER_VERIFIER_BASE_URL="${runtimeApiOrigin}"
export AGENT_MANAGER_VERIFIER_TOKEN="amat_xxx"
export AGENT_ID="<agent-id>"`
const claudeGuardInstallCommand = `mkdir -p ~/.claude/skills
unzip agent-manager-skill-verifier.zip -d ~/.claude/skills/

export AGENT_MANAGER_VERIFIER_BASE_URL="${runtimeApiOrigin}"
export AGENT_MANAGER_VERIFIER_TOKEN="amat_xxx"
export AGENT_ID="<agent-id>"`
const guardUsageCommand = `python <skills-dir>/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py verify \\
  --path /path/to/skill`
const auditPagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['10', '20', '50'],
  showTotal: total => text(`共 ${total} 条`, `${total} total`),
})

const auditColumns = [
  { title: phrase('legacy.1f90xvr'), dataIndex: 'timestamp', key: 'timestamp', width: 220, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: phrase('legacy.q8rrsk'), dataIndex: 'event_type', key: 'event_type', width: 170, sorter: true },
  { title: 'Skill', dataIndex: 'skill_name', key: 'skill_name', width: 180, sorter: true },
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id', width: 160 },
  { title: phrase('legacy.d22rf5'), dataIndex: 'client_ip', key: 'client_ip', width: 140 },
  { title: phrase('legacy.19fsh85'), dataIndex: 'actor', key: 'actor', width: 170, sorter: true },
  { title: phrase('legacy.xc5h04'), dataIndex: 'details', key: 'details' },
]

const runtimeEventOptions = [
  { value: 'skill_signature_verified', label: phrase('legacy.niy9wk') },
  { value: 'skill_load_allowed', label: phrase('legacy.1b6ll1m') },
  { value: 'skill_load_blocked', label: phrase('legacy.qn8i26') },
  { value: 'skill_tamper_detected', label: phrase('legacy.1327pp') },
  { value: 'tool_invoked', label: phrase('legacy.1dc2waf') },
  { value: 'tool_blocked', label: phrase('legacy.b0w6ir') },
]
const runtimeEventTypes = runtimeEventOptions.map((item) => item.value)
const runtimeEventLabelMap = Object.fromEntries(runtimeEventOptions.map((item) => [item.value, item.label]))

const handleSkillGuardDownload = async () => {
  guardDownloading.value = true
  try {
    const blob = await downloadSkillVerifier()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'agent-manager-skill-verifier.zip'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.upa1zl'))
  } finally {
    guardDownloading.value = false
  }
}

const fetchRuntimeAudit = async () => {
  loadingAudit.value = true
  try {
    const res = await getAuditPaged({
      since_hours: 168,
      event_type: eventFilter.value === 'all' ? undefined : eventFilter.value,
      event_types: eventFilter.value === 'all' ? runtimeEventTypes.join(',') : undefined,
      q: auditKeyword.value.trim() || undefined,
      page: auditPagination.value.current,
      page_size: auditPagination.value.pageSize,
      sort_order: auditSortState.value.order === 'ascend' ? 'asc' : 'desc',
      limit: 1000,
    })
    auditRows.value = Array.isArray(res.items) ? res.items : []
    auditTotal.value = Number(res.total || 0)
    auditPagination.value = {
      ...auditPagination.value,
      total: auditTotal.value,
      current: Number(res.page || auditPagination.value.current),
      pageSize: Number(res.page_size || auditPagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.p00w7t'))
    auditRows.value = []
    auditTotal.value = 0
  } finally {
    loadingAudit.value = false
  }
}

const handleAuditTableChange = (pager, _filters, sorter) => {
  auditPagination.value = {
    ...auditPagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    auditSortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchRuntimeAudit()
}

const handleAuditFilterChange = () => {
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const resetAuditFilters = () => {
  eventFilter.value = 'all'
  auditKeyword.value = ''
  auditSortState.value = { field: 'timestamp', order: 'descend' }
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const runtimeEventLabel = (value) => runtimeEventLabelMap[value] || value || '-'
const runtimeEventColor = (value) => {
  if (['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked'].includes(value)) return 'red'
  if (['skill_load_allowed', 'skill_signature_verified', 'tool_invoked'].includes(value)) return 'green'
  return 'blue'
}
const auditDetails = (record) => (record?.details && typeof record.details === 'object' ? record.details : {})
const auditAgent = (record) => record.agent_id || auditDetails(record).agent_id || record.actor || '-'
const auditIp = (record) => record.client_ip || auditDetails(record).client_ip || '-'
const auditActor = (record) => {
  const details = auditDetails(record)
  if (details.token_name) return details.token_name
  if (details.token_prefix) return details.token_prefix
  return record.actor || '-'
}
const formatRuntimeDetails = (details = {}) => {
  const labels = {
    status: phrase('legacy.1ccx4t4'),
    reason: phrase('legacy.jsgjbe'),
    tool: phrase('legacy.185ciet'),
    allowed: phrase('legacy.q9h21m'),
    verification_mode: phrase('legacy.1x88724'),
  }
  const hidden = new Set([
    'agent_id',
    'client_ip',
    'token_id',
    'token_name',
    'token_type',
    'token_prefix',
    'bound_agent_id',
    'user_id',
    'group_id',
  ])
  return Object.entries(details || {})
    .filter(([key, value]) => !hidden.has(key) && value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${labels[key] || key}: ${value === true ? phrase('legacy.11bz44c') : value === false ? phrase('legacy.1qrntx4') : value}`)
    .join('；') || '-'
}

const fetchGovernanceData = async () => {
  governanceLoading.value = true
  try {
    const [tasks, switches, memories, agents] = await Promise.all([
      listRuntimeTasks({ limit: 100 }),
      listRuntimeKillSwitches(),
      listRuntimeMemories({ limit: 100 }),
      listAgents(),
    ])
    runtimeTasks.value = Array.isArray(tasks) ? tasks : []
    killSwitches.value = Array.isArray(switches) ? switches : []
    runtimeMemories.value = Array.isArray(memories) ? memories : []
    managedAgents.value = Array.isArray(agents) ? agents : []
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.loadFailed'))
  } finally {
    governanceLoading.value = false
  }
}

const handleKillTask = async (record) => {
  try {
    await killRuntimeTask(record.task_id, 'admin kill switch')
    message.success(i18nLabel('runtimeGovernance.actionSucceeded'))
    await fetchGovernanceData()
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.operationFailed'))
  }
}

const handleReplay = async (record) => {
  try {
    replayResult.value = await replayRuntimeTask(record.task_id)
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.operationFailed'))
  }
}

const handleTaskDetail = async (record) => {
  try {
    taskDetail.value = await getRuntimeTask(record.task_id)
    taskDetailVisible.value = true
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.operationFailed'))
  }
}

const handleCreateKillSwitch = async () => {
  if (!killSwitchForm.value.reason.trim()) {
    message.warning(i18nLabel('runtimeGovernance.reason'))
    return
  }
  try {
    await createRuntimeKillSwitch({
      ...killSwitchForm.value,
      scope_id: killSwitchForm.value.scope_type === 'global' ? '*' : killSwitchForm.value.scope_id,
    })
    killSwitchForm.value.reason = ''
    message.success(i18nLabel('runtimeGovernance.actionSucceeded'))
    await fetchGovernanceData()
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.operationFailed'))
  }
}

const handleReleaseKillSwitch = async (record) => {
  try {
    await releaseRuntimeKillSwitch(record.id)
    message.success(i18nLabel('runtimeGovernance.actionSucceeded'))
    await fetchGovernanceData()
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.operationFailed'))
  }
}

const memoryTrustColor = (status) => ({ trusted: 'green', untrusted: 'orange', quarantined: 'red' }[status] || 'default')

const handleReviewMemory = async (record, trustStatus) => {
  try {
    await reviewRuntimeMemory(record.memory_id, { trust_status: trustStatus })
    message.success(i18nLabel('runtimeGovernance.actionSucceeded'))
    await fetchGovernanceData()
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.operationFailed'))
  }
}

const loadSelectedPolicy = async () => {
  if (!selectedPolicyAgent.value) return
  try {
    runtimePolicy.value = await getRuntimePolicy(selectedPolicyAgent.value)
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.loadFailed'))
  }
}

const handleSavePolicy = async () => {
  try {
    const payload = Object.fromEntries(policyFields.map(field => [field.key, runtimePolicy.value[field.key]]))
    runtimePolicy.value = await updateRuntimePolicy(selectedPolicyAgent.value, payload)
    message.success(i18nLabel('runtimeGovernance.actionSucceeded'))
  } catch (error) {
    message.error(error.response?.data?.detail || i18nLabel('runtimeGovernance.operationFailed'))
  }
}

onMounted(() => {
  fetchRuntimeAudit()
  fetchGovernanceData()
})
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}

.code-block {
  margin: 0;
  padding: 12px;
  overflow: auto;
  background: #0f172a;
  color: #dbeafe;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
}

.code-block.compact {
  max-height: 220px;
}

.guard-panel {
  min-height: 100%;
  padding: 12px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  background: #fafafa;
}

.guard-panel-title {
  margin-bottom: 8px;
  color: #262626;
  font-weight: 600;
}

.hint {
  color: #8c8c8c;
  font-size: 12px;
}
</style>
