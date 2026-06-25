<template>
  <div>
    <a-page-header title="智能体管理" sub-title="按部门登记智能体，串起模型、Prompt、Skill 与运行时接入">
      <template #extra>
        <a-button @click="flowVisible = true">接入流程</a-button>
      </template>
    </a-page-header>

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
              <span>Prompt：{{ record.prompt_names?.length || 0 }} 个</span>
              <span>Skill：{{ record.skill_names?.length || 0 }} 个</span>
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
        <a-form-item label="默认模型">
          <a-select v-model:value="agentForm.default_model" allow-clear show-search placeholder="选择模型">
            <a-select-option v-for="model in models" :key="model.name" :value="model.name">
              {{ model.display_name || model.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="绑定 Prompt">
          <a-select
            v-model:value="agentForm.prompt_refs"
            mode="multiple"
            show-search
            allow-clear
            option-filter-prop="label"
            placeholder="搜索并选择可用 Prompt"
            :filter-option="filterOption"
          >
            <a-select-option
              v-for="prompt in promptOptions"
              :key="prompt.value"
              :value="prompt.value"
              :label="promptOptionLabel(prompt)"
            >
              {{ promptOptionLabel(prompt) }}
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

    <a-modal v-model:open="flowVisible" title="接入流程" width="920px" :footer="null">
      <a-steps size="small" :current="4" class="agent-flow-steps">
        <a-step title="配置部门" description="维护智能体所属部门或业务团队" />
        <a-step title="登记智能体" description="创建智能体档案并明确负责人" />
        <a-step title="绑定能力" description="关联模型、Prompt 与允许使用的 Skill" />
        <a-step title="签发凭证" description="在凭证管理中创建运行凭证" />
        <a-step title="运行校验" description="接入加载校验和工具调用校验" />
      </a-steps>
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
  listAgents,
  listGroups,
  listManagedUsers,
  listModelEndpoints,
  listPrompts,
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
const prompts = ref([])
const skills = ref([])
const filters = reactive({ department_group_id: null, status: undefined, q: '' })
const agentForm = reactive({
  agent_id: '',
  name: '',
  department_group_id: null,
  owner: '',
  description: '',
  status: 'active',
  default_model: undefined,
  skill_refs: [],
  prompt_refs: [],
})

const columns = [
  { title: '智能体', key: 'agent' },
  { title: '部门', key: 'department', width: 140 },
  { title: '负责人', dataIndex: 'owner', width: 140 },
  { title: '状态', key: 'status', width: 100 },
  { title: '能力绑定', key: 'capabilities', width: 220 },
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
const promptOptions = computed(() => prompts.value.map((prompt, index) => ({
  ...prompt,
  value: uniqueOptionValue(prompt, 'prompt', index),
})))
const statusText = (status) => ({ active: '启用', disabled: '禁用', draft: '草稿' }[status] || status)
const statusColor = (status) => ({ active: 'green', disabled: 'red', draft: 'orange' }[status] || 'default')
const userOptionLabel = (user) => `${user.username}${user.email ? `（${user.email}）` : ''}`
const uniqueOptionValue = (item, type, index) => `${type}:${item.skill_id || item.prompt_id || item.id || index}:${index}`
const skillOptionLabel = (skill) => {
  const statusLabel = skill.status === 'DEPLOYED' ? '已部署' : '已批准'
  const id = skill.skill_id || skill.id
  return `${skill.name}（${statusLabel}${id ? ` · ${id}` : ''}）`
}
const promptOptionLabel = (prompt) => {
  const statusLabel = prompt.status === 'DEPLOYED' ? '已部署' : '已批准'
  const id = prompt.prompt_id || prompt.id
  return `${prompt.name}（${statusLabel}${id ? ` · ${id}` : ''}）`
}
const filterOption = (input, option) =>
  String(option?.label || option?.value || '').toLowerCase().includes(String(input || '').toLowerCase())
const findRefsByNames = (options, names = []) => {
  const used = new Set()
  return names.map((name) => {
    const option = options.find(item => item.name === name && !used.has(item.value))
    if (!option) return null
    used.add(option.value)
    return option.value
  }).filter(Boolean)
}
const namesFromRefs = (options, refs = []) =>
  refs.map(ref => options.find(item => item.value === ref)?.name).filter(Boolean)

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
  const [groupRes, userRes, modelRes, promptRes, skillRes] = await Promise.all([
    listGroups(),
    listManagedUsers(),
    listModelEndpoints(),
    listPrompts({ status: 'APPROVED,DEPLOYED' }),
    listSkills({ status: 'APPROVED,DEPLOYED' }),
  ])
  groups.value = groupRes
  users.value = userRes
  models.value = modelRes
  prompts.value = Array.isArray(promptRes.items) ? promptRes.items : promptRes
  skills.value = Array.isArray(skillRes.items) ? skillRes.items : skillRes
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
    status: record?.status || 'active',
    default_model: record?.default_model || undefined,
    skill_refs: findRefsByNames(skillOptions.value, record?.skill_names || []),
    prompt_refs: findRefsByNames(promptOptions.value, record?.prompt_names || []),
  })
  agentVisible.value = true
}

const saveAgent = async () => {
  if (submitting.value) return
  if (!agentForm.agent_id.trim() || !agentForm.name.trim()) {
    message.warning('请填写 Agent ID 和名称')
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
      status: agentForm.status,
      default_model: agentForm.default_model,
      skill_names: namesFromRefs(skillOptions.value, agentForm.skill_refs),
      prompt_names: namesFromRefs(promptOptions.value, agentForm.prompt_refs),
    }
    let savedAgent
    if (editingAgentId.value) savedAgent = await updateAgent(editingAgentId.value, payload)
    else savedAgent = await createAgent(payload)
    agentVisible.value = false
    await fetchAgents()
    if (!editingAgentId.value) {
      Modal.confirm({
        title: '智能体已创建',
        content: '运行凭证请在“凭证管理”中创建。是否现在去创建 Agent 运行凭证？',
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

.agent-flow-steps {
  padding: 8px 0 12px;
}
</style>
