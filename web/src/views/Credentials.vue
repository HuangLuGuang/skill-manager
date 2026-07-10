<template>
  <div>
    <a-page-header title="统一凭证中心" sub-title="统一签发模型调用、Agent 运行时和 Scanner 接入凭证" />

    <a-card style="margin-top: 16px">
      <template #extra>
        <a-space>
          <a-select v-model:value="filters.token_type" allow-clear placeholder="全部类型" style="width: 180px" @change="fetchTokens">
            <a-select-option value="model_gateway">模型调用凭证</a-select-option>
            <a-select-option value="agent_runtime">Agent 运行凭证</a-select-option>
            <a-select-option value="scanner">Scanner 接入凭证</a-select-option>
          </a-select>
          <a-button @click="fetchTokens" :loading="loading">刷新</a-button>
          <a-button type="primary" @click="openCreate">创建凭证</a-button>
        </a-space>
      </template>

      <a-alert
        type="info"
        show-icon
        message="凭证明文只展示一次"
        description="服务端只保存 hash。模型网关调用、Agent 运行时校验和 Scanner 批量提交都在这里创建凭证。"
        style="margin-bottom: 16px"
      />

      <a-table :data-source="tokens" :columns="columns" row-key="id" :loading="loading" size="small" :pagination="{ pageSize: 10 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'type'">
            <a-tag color="blue">{{ tokenTypeLabel(record.token_type) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'binding'">
            <div>{{ record.bound_agent_id || '-' }}</div>
            <div class="muted" v-if="record.group_id">Group ID: {{ record.group_id }}</div>
          </template>
          <template v-else-if="column.key === 'scopes'">
            <a-space wrap>
              <a-tag v-for="scope in record.scopes || []" :key="scope">{{ scope }}</a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'models'">
            <a-space wrap>
              <a-tag v-for="model in record.allowed_models || []" :key="model">{{ model }}</a-tag>
              <span v-if="!record.allowed_models?.length" class="muted">按类型默认</span>
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
            <div>创建：{{ formatTime(record.created_at) }}</div>
            <div class="muted">最近使用：{{ formatTime(record.last_used_at) }}</div>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-popconfirm v-if="record.status === 'active'" title="确认吊销这个凭证？" @confirm="handleRevoke(record)">
                <a-button type="link" danger :loading="actionId === record.id">吊销</a-button>
              </a-popconfirm>
              <a-popconfirm title="确认删除这个凭证记录？" @confirm="handleDelete(record)">
                <a-button type="link" danger :loading="actionId === record.id">删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="createVisible" title="创建凭证" width="760px" @ok="handleCreate" :confirm-loading="creating">
      <a-form layout="vertical" :model="form">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="凭证名称" required>
              <a-input v-model:value="form.name" placeholder="例如：风控智能体运行凭证" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="凭证类型" required>
              <a-select v-model:value="form.token_type" @change="applyTypeDefaults">
                <a-select-option value="model_gateway">模型调用凭证</a-select-option>
                <a-select-option value="agent_runtime">Agent 运行凭证</a-select-option>
                <a-select-option value="scanner">Scanner 接入凭证</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item v-if="form.token_type === 'agent_runtime'" label="绑定智能体" required>
          <a-select v-model:value="form.bound_agent_id" show-search allow-clear option-filter-prop="label" placeholder="选择 Agent">
            <a-select-option v-for="agent in agents" :key="agent.agent_id" :value="agent.agent_id" :label="`${agent.name} ${agent.agent_id}`">
              {{ agent.name }}（{{ agent.agent_id }}）
            </a-select-option>
          </a-select>
          <div class="hint">Agent 运行凭证用于识别调用方；如果列表为空，请先到“智能体管理”创建智能体。</div>
        </a-form-item>

        <a-form-item label="权限范围">
          <a-select v-model:value="form.scopes" mode="multiple" style="width: 100%">
            <a-select-opt-group label="模型网关">
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
          </a-select>
          <div class="hint">Agent 运行凭证默认不含 model:chat；只有显式勾选后才能调用模型网关。</div>
        </a-form-item>

        <a-form-item label="允许模型">
          <a-select v-model:value="form.allowed_models" mode="multiple" allow-clear placeholder="留空表示按类型默认或 Agent 默认模型">
            <a-select-option v-for="model in models" :key="model.name" :value="model.name">{{ model.display_name || model.name }}</a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item v-if="form.scopes.includes('model:chat')">
          <a-checkbox v-model:checked="form.enable_compression">开启智能压缩</a-checkbox>
          <div class="hint">压缩工具输出、日志、代码等内容后再发送给 LLM。</div>
        </a-form-item>
        <a-form-item v-if="form.scopes.includes('model:chat') && form.enable_compression" label="压缩级别">
          <a-radio-group v-model:value="form.compression_level">
            <a-radio value="auto">均衡</a-radio>
            <a-radio value="conservative">保守</a-radio>
            <a-radio value="aggressive">激进</a-radio>
          </a-radio-group>
        </a-form-item>

        <a-form-item v-if="form.scopes.includes('model:chat')" label="Prompt 防护">
          <a-radio-group v-model:value="form.prompt_guard_mode">
            <a-radio value="off">关闭</a-radio>
            <a-radio value="log">仅记录</a-radio>
            <a-radio value="warn">告警放行</a-radio>
            <a-radio value="block">高风险阻断</a-radio>
          </a-radio-group>
          <div class="hint">在模型网关运行时检测提示词注入、系统提示词泄露和凭据外传等风险。</div>
        </a-form-item>
        <a-form-item v-if="form.scopes.includes('model:chat') && form.prompt_guard_mode !== 'off'" label="AI 复核">
          <div class="hint">暂未启用在线大模型复核。当前 Prompt 防护使用轻量规则检测，避免增加模型网关主链路延迟。</div>
        </a-form-item>

        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="最大请求体 KB">
              <a-input-number v-model:value="form.max_body_kb" :min="1" :max="10240" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="最大并发请求数">
              <a-input-number v-model:value="form.max_concurrent_requests" :min="1" :max="100" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="最大上传 MB">
              <a-input-number v-model:value="form.max_upload_mb" :min="1" :max="10240" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="最大并发任务数">
              <a-input-number v-model:value="form.max_concurrent_jobs" :min="1" :max="100" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="允许来源 IP / CIDR">
          <a-select v-model:value="form.allowed_ips" mode="tags" placeholder="留空表示不限制，例如 10.0.0.0/24" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="createdVisible" title="凭证已创建" width="760px" :footer="null">
      <a-alert type="warning" show-icon message="请立即保存明文凭证，关闭后无法再次查看。" style="margin-bottom: 16px" />
      <a-input-group compact>
        <a-input :value="createdToken" readonly style="width: calc(100% - 96px)" />
        <a-button type="primary" @click="copy(createdToken)" :disabled="!createdToken">复制</a-button>
      </a-input-group>
    </a-modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

import {
  createAccessToken,
  deleteAccessToken,
  listAccessTokens,
  listAgents,
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
const filters = reactive({ token_type: undefined })
const form = reactive({
  name: '',
  token_type: 'agent_runtime',
  bound_agent_id: undefined,
  scopes: [],
  allowed_models: [],
  allowed_ips: [],
  max_body_kb: 1024,
  max_concurrent_requests: 5,
  max_upload_mb: 50,
  max_concurrent_jobs: 2,
  enable_compression: false,
  compression_level: 'auto',
  prompt_guard_mode: 'off',
  prompt_guard_llm_review: false,
})

const typeDefaults = {
  model_gateway: ['model:chat'],
  agent_runtime: ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool'],
  scanner: ['scanner:submit', 'scanner:read-own-results', 'scanner:read-own-sessions'],
}
const columns = [
  { title: '名称', dataIndex: 'name' },
  { title: '类型', key: 'type', width: 140 },
  { title: '前缀', dataIndex: 'token_prefix', width: 130 },
  { title: '绑定对象', key: 'binding', width: 180 },
  { title: '权限', key: 'scopes' },
  { title: '模型', key: 'models', width: 180 },
  { title: 'Prompt 防护', key: 'promptGuard', width: 130 },
  { title: '状态', key: 'status', width: 100 },
  { title: '时间', key: 'time', width: 240 },
  { title: '操作', key: 'action', width: 130 },
]

const tokenTypeLabel = (value) => ({
  model_gateway: '模型调用',
  agent_runtime: 'Agent 运行',
  scanner: 'Scanner 接入',
}[value] || value)
const statusLabel = (value) => ({ active: '启用', disabled: '禁用', revoked: '已吊销' }[value] || value)
const statusColor = (value) => ({ active: 'green', disabled: 'orange', revoked: 'red' }[value] || 'default')
const promptGuardLabel = (value) => ({ off: '关闭', log: '仅记录', warn: '告警放行', block: '高风险阻断' }[value] || '关闭')
const promptGuardColor = (value) => ({ off: 'default', log: 'blue', warn: 'orange', block: 'red' }[value] || 'default')
const formatTime = (value) => value ? new Date(value).toLocaleString() : '-'

const applyTypeDefaults = () => {
  form.scopes = [...(typeDefaults[form.token_type] || [])]
  if (form.token_type !== 'agent_runtime') form.bound_agent_id = undefined
}

const fetchTokens = async () => {
  loading.value = true
  try {
    const data = await listAccessTokens({ token_type: filters.token_type || undefined })
    tokens.value = data.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || '获取凭证失败')
  } finally {
    loading.value = false
  }
}

const fetchOptions = async () => {
  const [agentRows, modelRows] = await Promise.all([listAgents(), listModelEndpoints()])
  agents.value = agentRows || []
  models.value = modelRows || []
}

const openCreate = (defaults = {}) => {
  Object.assign(form, {
    name: defaults.name || '',
    token_type: defaults.token_type || 'agent_runtime',
    bound_agent_id: defaults.bound_agent_id,
    scopes: [...typeDefaults.agent_runtime],
    allowed_models: [],
    allowed_ips: [],
    max_body_kb: 1024,
    max_concurrent_requests: 5,
    max_upload_mb: 50,
    max_concurrent_jobs: 2,
    enable_compression: false,
    compression_level: 'auto',
    prompt_guard_mode: 'off',
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
    name: agent ? `${agent.name}运行凭证` : '',
  })
  await router.replace({ name: 'credentials', query: {} })
}

const handleCreate = async () => {
  if (!form.name.trim()) {
    message.warning('请填写凭证名称')
    return
  }
  if (form.token_type === 'agent_runtime' && !form.bound_agent_id) {
    message.warning('请选择绑定智能体')
    return
  }
  if (!form.scopes.includes('model:chat')) {
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
    message.error(error.response?.data?.detail || '创建凭证失败')
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
    message.error(error.response?.data?.detail || '吊销凭证失败')
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
    message.error(error.response?.data?.detail || '删除凭证失败')
  } finally {
    actionId.value = null
  }
}

const copy = async (value) => {
  await navigator.clipboard.writeText(value || '')
  message.success('已复制')
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
