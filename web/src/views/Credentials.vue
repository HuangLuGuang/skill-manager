<template>
  <div>
    <a-page-header :title="$t('legacy.97xff4')" :sub-title="$t('legacy.zt36j')" />

    <a-card style="margin-top: 16px">
      <template #extra>
        <a-space>
          <a-select v-model:value="filters.token_type" allow-clear :placeholder="$t('legacy.zao217')" style="width: 180px" @change="fetchTokens">
            <a-select-option value="model_gateway">{{ $t("legacy.9ooix4") }}</a-select-option>
            <a-select-option value="agent_runtime">{{ $t("legacy.1l0be8o") }}</a-select-option>
            <a-select-option value="scanner">{{ $t("legacy.kgw7m7") }}</a-select-option>
            <a-select-option value="client">{{ $t("legacy.11044ab") }}</a-select-option>
            <a-select-option value="mcp_gateway">{{ $t("legacy.1gb7s5r") }}</a-select-option>
          </a-select>
          <a-button @click="fetchTokens" :loading="loading">{{ $t("legacy.12qo56a") }}</a-button>
          <a-button type="primary" @click="openCreate">{{ $t("legacy.xm5sv6") }}</a-button>
        </a-space>
      </template>

      <a-alert
        type="info"
        show-icon
        :message="$t('legacy.1d30bzi')"
        :description="$t('legacy.58jku8')"
        style="margin-bottom: 16px"
      />

      <a-table :data-source="tokens" :columns="columns" row-key="id" :loading="loading" size="small" :pagination="{ pageSize: 10 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'type'">
            <a-tag color="blue">{{ tokenTypeLabel(record.token_type) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'binding'">
            <div>{{ record.bound_agent_id || record.bound_client_id || '-' }}</div>
            <div class="muted" v-if="record.group_id">Group ID: {{ record.group_id }}</div>
            <div class="muted" v-if="record.allowed_mcp_gateways?.length">{{ record.allowed_mcp_gateways.join(', ') }}</div>
          </template>
          <template v-else-if="column.key === 'scopes'">
            <a-space wrap>
              <a-tag v-for="scope in record.scopes || []" :key="scope">{{ scope }}</a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'models'">
            <a-space wrap>
              <a-tag v-for="model in record.allowed_models || []" :key="model">{{ model }}</a-tag>
              <span v-if="!record.allowed_models?.length" class="muted">{{ $t("legacy.heq3bi") }}</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'promptGuard'">
            <a-tag :color="promptGuardColor(record.prompt_guard_mode)">
              {{ promptGuardLabel(record.prompt_guard_mode) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'time'">
            <div>{{ $t("legacy.1rmdoq6") }}{{ formatTime(record.created_at) }}</div>
            <div class="muted">{{ $t("legacy.vgf6kt") }}{{ formatTime(record.last_used_at) }}</div>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-popconfirm v-if="record.status === 'active'" :title="$t('legacy.lsaw9d')" @confirm="handleRevoke(record)">
                <a-button type="link" danger :loading="actionId === record.id">{{ $t("legacy.1xammsn") }}</a-button>
              </a-popconfirm>
              <a-popconfirm :title="$t('legacy.1dfi7sm')" @confirm="handleDelete(record)">
                <a-button type="link" danger :loading="actionId === record.id">{{ $t("legacy.1t2vi4h") }}</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="createVisible" :title="$t('legacy.xm5sv6')" width="760px" @ok="handleCreate" :confirm-loading="creating">
      <a-form layout="vertical" :model="form">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.1sfhit2')" required>
              <a-input v-model:value="form.name" :placeholder="$t('legacy.1fkez83')" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.1ik4ln5')" required>
              <a-select v-model:value="form.token_type" @change="applyTypeDefaults">
                <a-select-option value="model_gateway">{{ $t("legacy.9ooix4") }}</a-select-option>
                <a-select-option value="agent_runtime">{{ $t("legacy.1l0be8o") }}</a-select-option>
                <a-select-option value="scanner">{{ $t("legacy.kgw7m7") }}</a-select-option>
                <a-select-option value="client">{{ $t("legacy.11044ab") }}</a-select-option>
                <a-select-option value="mcp_gateway">{{ $t("legacy.1gb7s5r") }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item v-if="form.token_type === 'agent_runtime'" :label="$t('legacy.hues6c')" required>
          <a-select v-model:value="form.bound_agent_id" show-search allow-clear option-filter-prop="label" :placeholder="$t('legacy.bn0dh2')">
            <a-select-option v-for="agent in agents" :key="agent.agent_id" :value="agent.agent_id" :label="`${agent.name} ${agent.agent_id}`">
              {{ agent.name }}（{{ agent.agent_id }}）
            </a-select-option>
          </a-select>
          <div class="hint">{{ $t("legacy.1tsx8y7") }}</div>
        </a-form-item>

        <a-form-item v-if="form.token_type === 'mcp_gateway'" :label="$t('legacy.107vn25')" required>
          <a-select v-model:value="form.allowed_mcp_gateways" mode="multiple" allow-clear :placeholder="$t('legacy.e82puc')">
            <a-select-option v-for="gateway in mcpGateways" :key="gateway.slug" :value="gateway.slug">
              {{ gateway.name }}（{{ gateway.slug }}）
            </a-select-option>
          </a-select>
          <div class="hint">{{ $t("legacy.mdhqps") }}</div>
        </a-form-item>

        <a-form-item :label="$t('legacy.13dp9dd')">
          <a-select v-model:value="form.scopes" mode="multiple" style="width: 100%">
            <a-select-opt-group :label="$t('legacy.15en1a5')">
              <a-select-option value="model:chat">model:chat</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Agent Runtime">
              <a-select-option value="runtime:verify-signature">runtime:verify-signature</a-select-option>
              <a-select-option value="runtime:can-load">runtime:can-load</a-select-option>
              <a-select-option value="runtime:check-tool">runtime:check-tool</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Scanner">
              <a-select-option value="scanner:submit">scanner:submit</a-select-option>
              <a-select-option value="scanner:read-own-results">scanner:read-own-results</a-select-option>
              <a-select-option value="scanner:read-own-sessions">scanner:read-own-sessions</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Agent Manager Client">
              <a-select-option value="client:register">client:register</a-select-option>
              <a-select-option value="client:heartbeat">client:heartbeat</a-select-option>
              <a-select-option value="client:read-policy">client:read-policy</a-select-option>
              <a-select-option value="client:read-tasks">client:read-tasks</a-select-option>
              <a-select-option value="client:report-inventory">client:report-inventory</a-select-option>
              <a-select-option value="client:report-events">client:report-events</a-select-option>
              <a-select-option value="client:submit-skill">client:submit-skill</a-select-option>
              <a-select-option value="client:download-approved-skill">client:download-approved-skill</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group :label="$t('legacy.1gcagoh')">
              <a-select-option value="mcp:connect">mcp:connect</a-select-option>
              <a-select-option value="mcp:list-tools">mcp:list-tools</a-select-option>
              <a-select-option value="mcp:call-tools">mcp:call-tools</a-select-option>
            </a-select-opt-group>
          </a-select>
          <div class="hint">{{ $t("legacy.141vff0") }}</div>
        </a-form-item>

        <a-form-item :label="$t('legacy.1o3mles')">
          <a-select v-model:value="form.allowed_models" mode="multiple" allow-clear :placeholder="$t('legacy.ws9xsw')">
            <a-select-option v-for="model in models" :key="model.name" :value="model.name">{{ model.display_name || model.name }}</a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item v-if="form.scopes.includes('model:chat')">
          <a-checkbox v-model:checked="form.enable_compression">{{ $t("legacy.msnsa5") }}</a-checkbox>
          <div class="hint">{{ $t("legacy.1xtgz2i") }}</div>
        </a-form-item>
        <a-form-item v-if="form.scopes.includes('model:chat') && form.enable_compression" :label="$t('legacy.1xs6jxf')">
          <a-radio-group v-model:value="form.compression_level">
            <a-radio value="auto">{{ $t("legacy.1cezww5") }}</a-radio>
            <a-radio value="conservative">{{ $t("legacy.pwi37k") }}</a-radio>
            <a-radio value="aggressive">{{ $t("legacy.11adc24") }}</a-radio>
          </a-radio-group>
        </a-form-item>

        <a-form-item v-if="form.scopes.includes('model:chat')" :label="$t('legacy.5h548n')">
          <a-radio-group v-model:value="form.prompt_guard_mode">
            <a-radio value="off">{{ $t("legacy.g0fanx") }}</a-radio>
            <a-radio value="log">{{ $t("legacy.4drpun") }}</a-radio>
            <a-radio value="warn">{{ $t("legacy.gjwe4z") }}</a-radio>
            <a-radio value="block">{{ $t("legacy.enaw4e") }}</a-radio>
          </a-radio-group>
          <div class="hint">{{ $t("legacy.ug60p") }}</div>
        </a-form-item>
        <a-form-item v-if="form.scopes.includes('model:chat') && form.prompt_guard_mode !== 'off'" :label="$t('legacy.otccp4')">
          <div class="hint">{{ $t("legacy.16x9kox") }}</div>
        </a-form-item>

        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.1wuxzav')">
              <a-input-number v-model:value="form.max_body_kb" :min="1" :max="10240" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.xiepuo')">
              <a-input-number v-model:value="form.max_concurrent_requests" :min="1" :max="100" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.1on4ot5')">
              <a-input-number v-model:value="form.max_upload_mb" :min="1" :max="10240" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item :label="$t('legacy.1smg0jr')">
              <a-input-number v-model:value="form.max_concurrent_jobs" :min="1" :max="100" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item :label="$t('legacy.gos0c3')">
          <a-select v-model:value="form.allowed_ips" mode="tags" :placeholder="$t('legacy.1xc63zs')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="createdVisible" :title="$t('legacy.erv7dq')" width="760px" :footer="null">
      <a-alert type="warning" show-icon :message="$t('legacy.369wfb')" style="margin-bottom: 16px" />
      <a-input-group compact>
        <a-input :value="createdToken" readonly style="width: calc(100% - 96px)" />
        <a-button type="primary" @click="copy(createdToken)" :disabled="!createdToken">{{ $t("legacy.1xbipwq") }}</a-button>
      </a-input-group>
    </a-modal>
  </div>
</template>

<script setup>
import { translateLegacy as phrase, translateText as text } from '../i18n'

import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
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
const loading = ref(false)
const creating = ref(false)
const createVisible = ref(false)
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
})

const typeDefaults = {
  model_gateway: ['model:chat'],
  agent_runtime: ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool', 'runtime:govern', 'runtime:memory'],
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
const columns = [
  { title: phrase('legacy.hzx914'), dataIndex: 'name' },
  { title: phrase('legacy.anh4cj'), key: 'type', width: 140 },
  { title: phrase('legacy.z7wyiw'), dataIndex: 'token_prefix', width: 130 },
  { title: phrase('legacy.575kfk'), key: 'binding', width: 180 },
  { title: phrase('legacy.lpjrwm'), key: 'scopes' },
  { title: phrase('legacy.1ow6qt'), key: 'models', width: 180 },
  { title: phrase('legacy.5h548n'), key: 'promptGuard', width: 130 },
  { title: phrase('legacy.1ccx4t4'), key: 'status', width: 100 },
  { title: phrase('legacy.1f90xvr'), key: 'time', width: 240 },
  { title: phrase('legacy.501w24'), key: 'action', width: 130 },
]

const tokenTypeLabel = (value) => ({
  model_gateway: phrase('legacy.9zs4ni'),
  agent_runtime: phrase('legacy.9wky3i'),
  scanner: phrase('legacy.17bs4x'),
  client: phrase('legacy.1u7rfgt'),
  mcp_gateway: phrase('legacy.1gcagoh'),
}[value] || value)
const statusLabel = (value) => ({ active: phrase('legacy.5pm2ma'), disabled: phrase('legacy.1dcdrxo'), revoked: phrase('legacy.1ouf8s7') }[value] || value)
const statusColor = (value) => ({ active: 'green', disabled: 'orange', revoked: 'red' }[value] || 'default')
const promptGuardLabel = (value) => ({ off: phrase('legacy.g0fanx'), log: phrase('legacy.4drpun'), warn: phrase('legacy.gjwe4z'), block: phrase('legacy.enaw4e') }[value] || phrase('legacy.g0fanx'))
const promptGuardColor = (value) => ({ off: 'default', log: 'blue', warn: 'orange', block: 'red' }[value] || 'default')
const formatTime = formatDateTime

const applyTypeDefaults = () => {
  form.scopes = [...(typeDefaults[form.token_type] || [])]
  form.prompt_guard_mode = form.token_type === 'agent_runtime' ? 'block' : 'off'
  if (form.token_type !== 'agent_runtime') form.bound_agent_id = undefined
  if (form.token_type !== 'mcp_gateway') form.allowed_mcp_gateways = []
}

const fetchTokens = async () => {
  loading.value = true
  try {
    const data = await listAccessTokens({ token_type: filters.token_type || undefined })
    tokens.value = data.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.13t7csk'))
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

const openCreate = (defaults = {}) => {
  Object.assign(form, {
    name: defaults.name || '',
    token_type: defaults.token_type || 'agent_runtime',
    bound_agent_id: defaults.bound_agent_id,
    scopes: [...typeDefaults.agent_runtime],
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
  })
  applyTypeDefaults()
  form.bound_agent_id = defaults.bound_agent_id
  if (defaults.name) form.name = defaults.name
  createVisible.value = true
}

const openCreateFromQuery = async () => {
  if (route.query.create !== 'agent_runtime') return
  const agentId = String(route.query.agent_id || '')
  const agent = agents.value.find(item => item.agent_id === agentId)
  openCreate({
    token_type: 'agent_runtime',
    bound_agent_id: agentId || undefined,
    name: agent ? text(`${agent.name}运行凭证`, `${agent.name} Runtime Credential`) : '',
  })
  await router.replace({ name: 'credentials', query: {} })
}

const handleCreate = async () => {
  if (!form.name.trim()) {
    message.warning(phrase('legacy.1slkaeh'))
    return
  }
  if (form.token_type === 'agent_runtime' && !form.bound_agent_id) {
    message.warning(phrase('legacy.1mafkvb'))
    return
  }
  if (form.token_type === 'mcp_gateway' && !form.allowed_mcp_gateways.length) {
    message.warning(phrase('legacy.68wepu'))
    return
  }
  if (form.token_type !== 'agent_runtime' && !form.scopes.includes('model:chat')) {
    form.prompt_guard_mode = 'off'
  }
  form.prompt_guard_llm_review = false
  creating.value = true
  try {
    const data = await createAccessToken({ ...form, name: form.name.trim() })
    createdToken.value = data.token
    createVisible.value = false
    createdVisible.value = true
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.96w1us'))
  } finally {
    creating.value = false
  }
}

const handleRevoke = async (record) => {
  actionId.value = record.id
  try {
    await revokeAccessToken(record.id)
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.rwom3n'))
  } finally {
    actionId.value = null
  }
}

const handleDelete = async (record) => {
  actionId.value = record.id
  try {
    await deleteAccessToken(record.id)
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1nny9ul'))
  } finally {
    actionId.value = null
  }
}

const copy = async (value) => {
  await navigator.clipboard.writeText(value || '')
  message.success(phrase('legacy.alyyje'))
}

onMounted(async () => {
  await Promise.all([fetchTokens(), fetchOptions()])
  await openCreateFromQuery()
})
</script>

<style scoped>
.muted,
.hint {
  color: #8c8c8c;
  font-size: 12px;
}

.hint {
  margin-top: 6px;
}
</style>
