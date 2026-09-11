<template>
  <div>
    <a-page-header :title="$t('legacy.5chjsa')" :sub-title="$t('legacy.8y4kug')">
      <template #extra>
        <a-button @click="flowVisible = true">{{ $t("legacy.udb4df") }}</a-button>
      </template>
    </a-page-header>

    <a-card class="flow-card">
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="12">
          <div class="flow-section">
            <div class="flow-title">{{ $t("legacy.7t2cwb") }}</div>
            <a-steps size="small" :current="3" direction="horizontal" class="flow-inline-steps">
              <a-step :title="$t('legacy.ybr38x')" description="Skill" />
              <a-step :title="$t('legacy.1myljr3')" :description="$t('legacy.15rx88y')" />
              <a-step :title="$t('legacy.1ws11do')" :description="$t('legacy.1whlgcy')" />
              <a-step :title="$t('legacy.1tmnt86')" :description="$t('legacy.1oxl3ey')" />
            </a-steps>
          </div>
        </a-col>
        <a-col :xs="24" :lg="12">
          <div class="flow-section">
            <div class="flow-title">{{ $t("legacy.7aets9") }}</div>
            <a-steps size="small" :current="4" direction="horizontal" class="flow-inline-steps">
              <a-step :title="$t('legacy.61qni9')" :description="$t('legacy.2gpy3c')" />
              <a-step :title="$t('legacy.vlky39')" :description="$t('legacy.1sbtgxh')" />
              <a-step :title="$t('legacy.qiw836')" :description="$t('legacy.ma87zl')" />
              <a-step :title="$t('legacy.17adtee')" :description="$t('legacy.s467ck')" />
              <a-step :title="$t('legacy.13omz3w')" :description="$t('legacy.1d0sbdt')" />
            </a-steps>
          </div>
        </a-col>
      </a-row>
      <div class="flow-summary"> {{ $t("legacy.qhnqxy") }} </div>
    </a-card>

    <a-card style="margin-top: 16px">
      <a-row :gutter="[12, 12]">
        <a-col :xs="12" :md="6">
          <a-statistic :title="$t('legacy.1auoal5')" :value="agents.length" />
        </a-col>
        <a-col :xs="12" :md="6">
          <a-statistic :title="$t('legacy.o58hfh')" :value="activeCount" />
        </a-col>
        <a-col :xs="12" :md="6">
          <a-statistic :title="$t('legacy.19hhbpm')" :value="departmentCount" />
        </a-col>
        <a-col :xs="12" :md="6">
          <a-statistic :title="$t('legacy.1nwtm7')" :value="skillBindingCount" />
        </a-col>
      </a-row>
    </a-card>

    <a-card style="margin-top: 16px">
      <a-space style="margin-bottom: 16px" wrap>
        <a-select v-model:value="filters.department_group_id" allow-clear :placeholder="$t('legacy.1qbe72t')" style="width: 180px" @change="fetchAgents">
          <a-select-option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</a-select-option>
        </a-select>
        <a-select v-model:value="filters.status" allow-clear :placeholder="$t('legacy.igzce8')" style="width: 140px" @change="fetchAgents">
          <a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option>
          <a-select-option value="disabled">{{ $t("legacy.1dcdrxo") }}</a-select-option>
          <a-select-option value="draft">{{ $t("legacy.oc54qp") }}</a-select-option>
        </a-select>
        <a-input v-model:value="filters.q" :placeholder="$t('legacy.1kyry2m')" style="width: 240px" allow-clear @pressEnter="fetchAgents" />
        <a-button type="primary" @click="fetchAgents" :loading="loading">{{ $t("legacy.16mfmhy") }}</a-button>
        <a-button @click="resetFilters" :disabled="loading">{{ $t("legacy.1wq9feq") }}</a-button>
        <a-button v-if="hasAccess('agents:create')" type="primary" @click="openAgent()">{{ $t("legacy.1krdxw3") }}</a-button>
      </a-space>

      <a-table :data-source="agents" :columns="columns" rowKey="id" :loading="loading" :pagination="{ pageSize: 10 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'agent'">
            <div class="agent-name">{{ record.name }}</div>
            <div class="muted">{{ record.agent_id }}</div>
          </template>
          <template v-else-if="column.key === 'department'">
            <a-tag>{{ record.department_name || $t('legacy.1bgs62s') }}</a-tag>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'capabilities'">
            <a-space direction="vertical" size="small">
              <span>{{ $t("legacy.1nqvdwt") }}{{ record.default_model || '-' }}</span>
              <span>Skill：{{ record.skill_names?.length || 0 }} {{ $t("legacy.d5a1x9") }}</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'access'">
            <a-space direction="vertical" size="small">
              <a-tag :color="agentAccessStatus(record).color">{{ agentAccessStatus(record).text }}</a-tag>
              <span class="muted">{{ agentAccessStatus(record).hint }}</span>
            </a-space>
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a v-if="hasAccess('agents:update')" @click="openAgent(record)">{{ $t("legacy.qreyeg") }}</a>
              <a-popconfirm v-if="hasAccess('agents:delete')" :title="$t('legacy.17y5gsa')" @confirm="handleDelete(record)">
                <a danger>{{ $t("legacy.1t2vi4h") }}</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="agentVisible" :title="editingAgentId ? $t('legacy.1k1efeu') : $t('legacy.1krdxw3')" width="760px" @ok="saveAgent" :confirm-loading="submitting">
      <a-form layout="vertical" :model="agentForm">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="Agent ID" required>
              <a-input v-model:value="agentForm.agent_id" placeholder="risk-screening-agent" />
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
        <a-form-item :label="$t('legacy.vf8e1d')" required>
          <a-select v-model:value="agentForm.channel" :placeholder="$t('legacy.rz3jld')">
            <a-select-option v-for="option in clientTypeOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </a-select-option>
          </a-select>
          <div class="field-hint">{{ $t("legacy.t60ukl") }}</div>
        </a-form-item>
        <a-form-item :label="$t('legacy.9tnz09')">
          <a-select v-model:value="agentForm.default_model" allow-clear show-search :placeholder="$t('legacy.13jl62z')">
            <a-select-option v-for="model in models" :key="model.name" :value="model.name">
              {{ model.display_name || model.name }}
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
import { can as hasAccess } from '../access'
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'

import {
  createAgent,
  deleteAgent,
  getAudit,
  listAccessTokens,
  listAgents,
  listGroups,
  listManagedUsers,
  listModelEndpoints,
  listSkills,
  updateAgent,
} from '../api'

const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const agentVisible = ref(false)
const flowVisible = ref(false)
const editingAgentId = ref(null)
const agents = ref([])
const groups = ref([])
const users = ref([])
const models = ref([])
const skills = ref([])
const accessTokens = ref([])
const auditRows = ref([])
const filters = reactive({ department_group_id: null, status: undefined, q: '' })
const agentForm = reactive({
  agent_id: '',
  name: '',
  department_group_id: null,
  owner: '',
  description: '',
  channel: undefined,
  status: 'active',
  default_model: undefined,
  skill_refs: [],
  prompt_names: [],
})
const clientTypeOptions = [
  { value: 'Claude Code', label: 'Claude Code' },
  { value: 'Codex', label: 'Codex' },
  { value: 'Gemini CLI', label: 'Gemini CLI' },
  { value: 'OpenCode', label: 'OpenCode' },
  { value: 'OpenClaw', label: 'OpenClaw' },
  { value: 'Hermes', label: 'Hermes' },
  { value: 'TRAE CN', label: 'TRAE CN' },
  { value: 'TRAE', label: 'TRAE' },
  { value: 'Cursor', label: 'Cursor' },
  { value: 'Global Skills', label: phrase('legacy.13u0v7i') },
  { value: 'CodeBuddy', label: 'CodeBuddy' },
  { value: 'WorkBuddy', label: 'WorkBuddy' },
  { value: 'Custom', label: phrase('legacy.rgimjp') },
]

const columns = [
  { title: phrase('legacy.1auoal5'), key: 'agent' },
  { title: phrase('legacy.104oyzx'), key: 'department', width: 140 },
  { title: phrase('legacy.17eokaf'), dataIndex: 'owner', width: 140 },
  { title: phrase('legacy.1ccx4t4'), key: 'status', width: 100 },
  { title: phrase('legacy.15fyal2'), key: 'capabilities', width: 220 },
  { title: phrase('legacy.1phk7cu'), key: 'access', width: 190 },
  { title: phrase('legacy.501w24'), key: 'actions', width: 120 },
]

const activeCount = computed(() => agents.value.filter(item => item.status === 'active').length)
const departmentCount = computed(() => new Set(agents.value.map(item => item.department_group_id).filter(Boolean)).size)
const skillBindingCount = computed(() => agents.value.reduce((sum, item) => sum + (item.skill_names?.length || 0), 0))
const activeUsers = computed(() => users.value.filter(item => item.is_active !== false))
const skillOptions = computed(() => skills.value.map((skill, index) => ({
  ...skill,
  value: uniqueOptionValue(skill, 'skill', index),
})))
const statusText = (status) => ({ active: phrase('legacy.5pm2ma'), disabled: phrase('legacy.1dcdrxo'), draft: phrase('legacy.oc54qp') }[status] || status)
const statusColor = (status) => ({ active: 'green', disabled: 'red', draft: 'orange' }[status] || 'default')
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
const auditDetails = (record) => {
  if (!record?.details) return {}
  if (typeof record.details === 'object') return record.details
  try {
    return JSON.parse(record.details)
  } catch {
    return {}
  }
}
const tokenByAgent = computed(() => {
  const map = new Map()
  accessTokens.value
    .filter(item => item.token_type === 'agent_runtime' && item.bound_agent_id)
    .forEach(item => {
      const current = map.get(item.bound_agent_id)
      if (!current || item.status === 'active') map.set(item.bound_agent_id, item)
    })
  return map
})
const latestRuntimeEventByAgent = computed(() => {
  const map = new Map()
  auditRows.value.forEach((item) => {
    const details = auditDetails(item)
    const agentId = item.agent_id || details.agent_id || details.bound_agent_id
    if (!agentId || map.has(agentId)) return
    map.set(agentId, item)
  })
  return map
})
const agentAccessStatus = (record) => {
  const token = tokenByAgent.value.get(record.agent_id)
  if (!token) {
    return { color: 'default', text: phrase('legacy.1w9cudm'), hint: phrase('legacy.1rfhupd') }
  }
  if (token.status !== 'active') {
    return { color: 'orange', text: phrase('legacy.88vhrh'), hint: statusText(token.status) }
  }
  const event = latestRuntimeEventByAgent.value.get(record.agent_id)
  if (!event) {
    return { color: 'blue', text: phrase('legacy.lo94w2'), hint: phrase('legacy.1e7tzwm') }
  }
  if (['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked'].includes(event.event_type)) {
    return { color: 'red', text: phrase('legacy.5hx75b'), hint: event.skill_name || event.event_type }
  }
  return { color: 'green', text: phrase('legacy.118ohr2'), hint: event.skill_name || event.event_type }
}
const fetchAgents = async () => {
  loading.value = true
  try {
    agents.value = await listAgents({
      department_group_id: filters.department_group_id || undefined,
      status: filters.status || undefined,
      q: filters.q?.trim() || undefined,
    })
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.nb6eev'))
  } finally {
    loading.value = false
  }
}

const loadOptions = async () => {
  const [groupRes, userRes, modelRes, skillRes, tokenRes, auditRes] = await Promise.all([
    hasAccess('groups:view') ? listGroups() : [],
    hasAccess('users:view') ? listManagedUsers() : [],
    hasAccess('models:view') ? listModelEndpoints() : [],
    hasAccess('skills:view') ? listSkills({ status: 'APPROVED,DEPLOYED' }) : [],
    hasAccess('credentials:view') ? listAccessTokens({ token_type: 'agent_runtime' }) : { items: [] },
    hasAccess('skills:view') ? getAudit({ since_hours: 168, limit: 300 }) : [],
  ])
  groups.value = groupRes
  users.value = userRes
  models.value = modelRes
  skills.value = Array.isArray(skillRes.items) ? skillRes.items : skillRes
  accessTokens.value = tokenRes.items || []
  auditRows.value = Array.isArray(auditRes) ? auditRes : []
}

const resetFilters = async () => {
  Object.assign(filters, { department_group_id: null, status: undefined, q: '' })
  await fetchAgents()
}

const openAgent = (record = null) => {
  editingAgentId.value = record?.id || null
  Object.assign(agentForm, {
    agent_id: record?.agent_id || '',
    name: record?.name || '',
    department_group_id: record?.department_group_id || null,
    owner: record?.owner || '',
    description: record?.description || '',
    channel: record?.channel || undefined,
    status: record?.status || 'active',
    default_model: record?.default_model || undefined,
    skill_refs: findRefsByNames(skillOptions.value, record?.skill_names || []),
    prompt_names: record?.prompt_names || [],
  })
  agentVisible.value = true
}

const saveAgent = async () => {
  if (submitting.value) return
  if (!agentForm.agent_id.trim() || !agentForm.name.trim() || !agentForm.channel) {
    message.warning(phrase('legacy.1jpsp3w'))
    return
  }
  submitting.value = true
  try {
    const payload = {
      agent_id: agentForm.agent_id.trim(),
      name: agentForm.name.trim(),
      department_group_id: agentForm.department_group_id,
      owner: agentForm.owner,
      description: agentForm.description,
      channel: agentForm.channel,
      status: agentForm.status,
      default_model: agentForm.default_model,
      skill_names: skillIdsFromRefs(skillOptions.value, agentForm.skill_refs),
      prompt_names: agentForm.prompt_names || [],
    }
    let savedAgent
    if (editingAgentId.value) savedAgent = await updateAgent(editingAgentId.value, payload)
    else savedAgent = await createAgent(payload)
    agentVisible.value = false
    await fetchAgents()
    if (!editingAgentId.value) {
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
  await deleteAgent(record.id)
  message.success(phrase('legacy.1s2wkng'))
  await fetchAgents()
}

onMounted(async () => {
  await Promise.all([loadOptions(), fetchAgents()])
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

.flow-card {
  margin-top: 16px;
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
</style>
