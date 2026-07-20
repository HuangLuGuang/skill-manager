<template>
  <div>
    <a-page-header title="智能体管理" sub-title="按部门登记智能体，串起模型、Skill 与运行时接入">
      <template #extra>
        <a-button @click="flowVisible = true">接入流程</a-button>
      </template>
    </a-page-header>

    <a-card class="flow-card">
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="12">
          <div class="flow-section">
            <div class="flow-title">1. 先治理能力</div>
            <a-steps size="small" :current="3" direction="horizontal" class="flow-inline-steps">
              <a-step title="提交" description="Skill" />
              <a-step title="扫描" description="分析风险" />
              <a-step title="审核" description="人工确认" />
              <a-step title="批准" description="可信可用" />
            </a-steps>
          </div>
        </a-col>
        <a-col :xs="24" :lg="12">
          <div class="flow-section">
            <div class="flow-title">2. 再接入 Agent</div>
            <a-steps size="small" :current="4" direction="horizontal" class="flow-inline-steps">
              <a-step title="创建 Agent" description="部门 / 负责人" />
              <a-step title="绑定范围" description="Skill / 模型" />
              <a-step title="签发凭证" description="运行身份" />
              <a-step title="集成守卫" description="加载前校验" />
              <a-step title="审计追踪" description="记录结果" />
            </a-steps>
          </div>
        </a-col>
      </a-row>
      <div class="flow-summary">
        扫描器负责批量接入本地 Skill；Agent 运行时通过 Skill Verifier 或 Runtime API 在加载前向平台校验授权、状态和内容指纹。
      </div>
    </a-card>

    <a-card style="margin-top: 16px">
      <a-row :gutter="[12, 12]">
        <a-col :xs="12" :md="6">
          <a-statistic title="智能体" :value="agents.length" />
        </a-col>
        <a-col :xs="12" :md="6">
          <a-statistic title="启用中" :value="activeCount" />
        </a-col>
        <a-col :xs="12" :md="6">
          <a-statistic title="涉及部门" :value="departmentCount" />
        </a-col>
        <a-col :xs="12" :md="6">
          <a-statistic title="绑定 Skill" :value="skillBindingCount" />
        </a-col>
      </a-row>
    </a-card>

    <a-card style="margin-top: 16px">
      <a-space style="margin-bottom: 16px" wrap>
        <a-select v-model:value="filters.department_group_id" allow-clear placeholder="全部部门" style="width: 180px" @change="fetchAgents">
          <a-select-option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</a-select-option>
        </a-select>
        <a-select v-model:value="filters.status" allow-clear placeholder="全部状态" style="width: 140px" @change="fetchAgents">
          <a-select-option value="active">启用</a-select-option>
          <a-select-option value="disabled">禁用</a-select-option>
          <a-select-option value="draft">草稿</a-select-option>
        </a-select>
        <a-input v-model:value="filters.q" placeholder="搜索智能体 / 负责人" style="width: 240px" allow-clear @pressEnter="fetchAgents" />
        <a-button type="primary" @click="fetchAgents" :loading="loading">查询</a-button>
        <a-button @click="resetFilters" :disabled="loading">重置</a-button>
        <a-button type="primary" @click="openAgent()">新增智能体</a-button>
      </a-space>

      <a-table :data-source="agents" :columns="columns" rowKey="id" :loading="loading" :pagination="{ pageSize: 10 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'agent'">
            <div class="agent-name">{{ record.name }}</div>
            <div class="muted">{{ record.agent_id }}</div>
          </template>
          <template v-else-if="column.key === 'department'">
            <a-tag>{{ record.department_name || '未分配' }}</a-tag>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'capabilities'">
            <a-space direction="vertical" size="small">
              <span>模型：{{ record.default_model || '-' }}</span>
              <span>Skill：{{ record.skill_names?.length || 0 }} 个</span>
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
              <a @click="openAgent(record)">编辑</a>
              <a-popconfirm title="确认删除这个智能体档案？" @confirm="handleDelete(record)">
                <a danger>删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="agentVisible" :title="editingAgentId ? '编辑智能体' : '新增智能体'" width="760px" @ok="saveAgent" :confirm-loading="submitting">
      <a-form layout="vertical" :model="agentForm">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="Agent ID" required>
              <a-input v-model:value="agentForm.agent_id" placeholder="risk-screening-agent" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="名称" required>
              <a-input v-model:value="agentForm.name" placeholder="风险筛查智能体" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="所属部门">
              <a-select v-model:value="agentForm.department_group_id" allow-clear placeholder="选择部门">
                <a-select-option v-for="group in groups" :key="group.id" :value="group.id">{{ group.name }}</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="状态">
              <a-select v-model:value="agentForm.status">
                <a-select-option value="active">启用</a-select-option>
                <a-select-option value="disabled">禁用</a-select-option>
                <a-select-option value="draft">草稿</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="负责人">
              <a-select
                v-model:value="agentForm.owner"
                show-search
                allow-clear
                option-filter-prop="label"
                placeholder="选择平台用户"
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
        <a-form-item label="客户端类型" required>
          <a-select v-model:value="agentForm.channel" placeholder="选择该智能体运行在哪类客户端">
            <a-select-option v-for="option in clientTypeOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </a-select-option>
          </a-select>
          <div class="field-hint">仅用于终端自动发现和映射，不代表接入方式。</div>
        </a-form-item>
        <a-form-item label="默认模型">
          <a-select v-model:value="agentForm.default_model" allow-clear show-search placeholder="选择模型">
            <a-select-option v-for="model in models" :key="model.name" :value="model.name">
              {{ model.display_name || model.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="允许 Skills">
          <a-select
            v-model:value="agentForm.skill_refs"
            mode="multiple"
            show-search
            allow-clear
            placeholder="搜索并选择可用 Skill"
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
          <div class="field-hint">只显示已批准或已部署的 Skill。</div>
        </a-form-item>
        <a-alert
          type="info"
          show-icon
          message="运行凭证请在“凭证管理”中创建。"
          style="margin-bottom: 16px"
        />
        <a-form-item label="描述">
          <a-textarea v-model:value="agentForm.description" :rows="3" placeholder="说明该智能体的业务职责和使用边界" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="flowVisible" title="Agent 接入流程" width="980px" :footer="null">
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="12">
          <a-card size="small" title="能力治理入库">
            <a-steps size="small" direction="vertical" :current="3">
              <a-step title="提交 Skill" description="手动提交，或用扫描器批量接入本地 Skill。" />
              <a-step title="平台扫描分析" description="执行静态扫描、Sandbox 信号、深度分析和 LLM 辅助研判。" />
              <a-step title="人工审核" description="查看判断依据，确认通过或拒绝。" />
              <a-step title="批准为可信版本" description="批准后记录内容指纹，后续运行时可校验是否被篡改。" />
            </a-steps>
          </a-card>
        </a-col>
        <a-col :xs="24" :lg="12">
          <a-card size="small" title="Agent 接入运行">
            <a-steps size="small" direction="vertical" :current="4">
              <a-step title="创建 Agent" description="登记部门、负责人和业务用途。" />
              <a-step title="绑定能力范围" description="约束可用 Skill 和默认模型。" />
              <a-step title="签发运行凭证" description="凭证绑定 Agent，作为外部运行身份。" />
              <a-step title="集成 Agent Skill Verifier" description="Agent 加载 Skill 前向平台校验状态、内容指纹和授权。" />
              <a-step title="审计追踪" description="记录哪个 Agent 通过哪个凭证使用了哪个 Skill。" />
            </a-steps>
          </a-card>
        </a-col>
      </a-row>
      <a-alert
        type="info"
        show-icon
        class="flow-note"
        message="推荐路径"
        description="能力治理 → 智能体管理 → 凭证管理 → 接入与运行 → 审计追踪。扫描器负责把本地 Skill 批量接入平台；Agent Skill Verifier 负责运行时加载前完整性校验。"
      />
      <a-card size="small" title="模型网关接入" class="flow-gateway-card">
        <a-steps size="small" :current="4">
          <a-step title="配置供应商" description="维护上游模型地址和密钥" />
          <a-step title="添加模型" description="对外暴露可选模型列表" />
          <a-step title="绑定组策略" description="按用户组应用隐私策略" />
          <a-step title="签发凭证" description="模型调用或 Agent 凭证勾选 model:chat" />
          <a-step title="修改模型配置" description="将 Agent/SDK 的大模型 API 地址改为平台网关地址，使用已签发凭证调用" />
        </a-steps>
      </a-card>
      <a-space class="flow-actions" wrap>
        <a-button @click="router.push('/submit')">提交 Skill</a-button>
        <a-button @click="router.push('/agents')">创建 Agent</a-button>
        <a-button @click="router.push('/credentials')">签发凭证</a-button>
        <a-button @click="router.push('/model-gateway/models')">配置模型网关</a-button>
        <a-button type="primary" @click="router.push('/runtime')">查看接入与运行</a-button>
      </a-space>
    </a-modal>
  </div>
</template>

<script setup>
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
  { value: 'Custom', label: '自定义 Agent' },
]

const columns = [
  { title: '智能体', key: 'agent' },
  { title: '部门', key: 'department', width: 140 },
  { title: '负责人', dataIndex: 'owner', width: 140 },
  { title: '状态', key: 'status', width: 100 },
  { title: '能力绑定', key: 'capabilities', width: 220 },
  { title: '接入状态', key: 'access', width: 190 },
  { title: '操作', key: 'actions', width: 120 },
]

const activeCount = computed(() => agents.value.filter(item => item.status === 'active').length)
const departmentCount = computed(() => new Set(agents.value.map(item => item.department_group_id).filter(Boolean)).size)
const skillBindingCount = computed(() => agents.value.reduce((sum, item) => sum + (item.skill_names?.length || 0), 0))
const activeUsers = computed(() => users.value.filter(item => item.is_active !== false))
const skillOptions = computed(() => skills.value.map((skill, index) => ({
  ...skill,
  value: uniqueOptionValue(skill, 'skill', index),
})))
const statusText = (status) => ({ active: '启用', disabled: '禁用', draft: '草稿' }[status] || status)
const statusColor = (status) => ({ active: 'green', disabled: 'red', draft: 'orange' }[status] || 'default')
const userOptionLabel = (user) => `${user.username}${user.email ? `（${user.email}）` : ''}`
const uniqueOptionValue = (item, type, index) => `${type}:${item.skill_id || item.id || index}:${index}`
const skillOptionLabel = (skill) => {
  const statusLabel = skill.status === 'DEPLOYED' ? '已部署' : '已批准'
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
    return { color: 'default', text: '未签发凭证', hint: '到凭证管理创建运行凭证' }
  }
  if (token.status !== 'active') {
    return { color: 'orange', text: '凭证不可用', hint: statusText(token.status) }
  }
  const event = latestRuntimeEventByAgent.value.get(record.agent_id)
  if (!event) {
    return { color: 'blue', text: '已签发凭证', hint: '等待运行时校验' }
  }
  if (['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked'].includes(event.event_type)) {
    return { color: 'red', text: '最近被阻断', hint: event.skill_name || event.event_type }
  }
  return { color: 'green', text: '最近校验成功', hint: event.skill_name || event.event_type }
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
    message.error(error.response?.data?.detail || '获取智能体列表失败')
  } finally {
    loading.value = false
  }
}

const loadOptions = async () => {
  const [groupRes, userRes, modelRes, skillRes, tokenRes, auditRes] = await Promise.all([
    listGroups(),
    listManagedUsers(),
    listModelEndpoints(),
    listSkills({ status: 'APPROVED,DEPLOYED' }),
    listAccessTokens({ token_type: 'agent_runtime' }),
    getAudit({ since_hours: 168, limit: 300 }),
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
    message.warning('请填写 Agent ID、名称并选择客户端类型')
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
        title: '智能体已创建',
        content: '下一步到“凭证管理”创建 Agent 运行凭证。',
        okText: '去创建凭证',
        cancelText: '稍后再说',
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
    message.error(error.response?.data?.detail || '保存智能体失败')
  } finally {
    submitting.value = false
  }
}

const handleDelete = async (record) => {
  await deleteAgent(record.id)
  message.success('智能体档案已删除')
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
