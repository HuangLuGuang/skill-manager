<template>
  <div>
    <a-page-header :title="pageTitle" :sub-title="pageSubtitle" />

    <template v-if="activePage === 'servers'">
        <a-card>
          <template #extra>
            <a-space>
              <a-button :loading="loading" @click="fetchAll">刷新</a-button>
              <a-button type="primary" @click="openServer()">添加 MCP Server</a-button>
            </a-space>
          </template>
          <a-table :data-source="servers" :columns="serverColumns" row-key="id" :loading="loading" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'server'">
                <div class="title">{{ record.name }}</div>
                <div class="muted">{{ record.slug }} · {{ record.endpoint }}</div>
              </template>
              <template v-else-if="column.key === 'health'">
                <a-tag :color="healthColor(record.health_status)">{{ healthLabel(record.health_status) }}</a-tag>
                <div class="muted">{{ formatTime(record.last_checked_at) }}</div>
              </template>
              <template v-else-if="column.key === 'tools'">
                <a-space wrap>
                  <a-tag v-for="tool in record.tools || []" :key="tool.id" :color="tool.enabled ? 'blue' : 'default'">
                    {{ tool.name }}
                  </a-tag>
                  <span v-if="!record.tools?.length" class="muted">尚未发现</span>
                </a-space>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : record.status === 'draft' ? 'orange' : 'default'">
                  {{ statusLabel(record.status) }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" :loading="actionId === `discover-${record.id}`" @click="discover(record)">连接并发现</a-button>
                  <a-button type="link" @click="openServer(record)">编辑</a-button>
                  <a-popconfirm title="确认删除这个 MCP Server？" @confirm="removeServer(record)">
                    <a-button type="link" danger :loading="actionId === `server-${record.id}`">删除</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-card>
    </template>

    <template v-else-if="activePage === 'gateways'">
        <a-card>
          <template #extra>
            <a-space>
              <a-button :loading="loading" @click="fetchAll">刷新</a-button>
              <a-button type="primary" @click="openGateway()">创建虚拟网关</a-button>
            </a-space>
          </template>
          <a-table :data-source="gateways" :columns="gatewayColumns" row-key="id" :loading="loading" size="small">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'gateway'">
                <div class="title">{{ record.name }}</div>
                <div class="muted">/mcp/{{ record.slug }}</div>
              </template>
              <template v-else-if="column.key === 'tools'">
                <a-space wrap>
                  <a-tag v-for="tool in gatewayToolNames(record)" :key="tool">{{ tool }}</a-tag>
                  <span v-if="!gatewayToolNames(record).length" class="muted">未发布 Tool</span>
                </a-space>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : 'default'">{{ statusLabel(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" @click="copy(`${origin}/mcp/${record.slug}`)">复制地址</a-button>
                  <a-button type="link" @click="openGateway(record)">编辑</a-button>
                  <a-popconfirm title="确认删除这个虚拟 MCP 网关？已有凭证将无法使用。" @confirm="removeGateway(record)">
                    <a-button type="link" danger :loading="actionId === `gateway-${record.id}`">删除</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-card>
    </template>

    <template v-else>
        <a-card>
          <template #extra><a-button :loading="loading" @click="fetchAll">刷新</a-button></template>
          <a-table :data-source="auditRows" :columns="auditColumns" row-key="id" :loading="loading" size="small" :pagination="{ pageSize: 20 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'target'">
                <div>{{ record.gateway_slug }} → {{ record.server_slug }}</div>
                <div class="muted">{{ record.tool_name }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'success' ? 'green' : 'red'">{{ record.status }}</a-tag>
              </template>
              <template v-else-if="column.key === 'time'">{{ formatTime(record.created_at) }}</template>
            </template>
          </a-table>
        </a-card>
    </template>

    <a-modal v-model:open="serverVisible" :title="editingServerId ? '编辑 MCP Server' : '添加 MCP Server'" width="760px" :confirm-loading="submitting" @ok="saveServer">
      <a-form layout="vertical" :model="serverForm">
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item label="名称" required><a-input v-model:value="serverForm.name" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item label="唯一标识" required><a-input v-model:value="serverForm.slug" :disabled="Boolean(editingServerId)" placeholder="例如 github" /></a-form-item></a-col>
        </a-row>
        <a-form-item label="Streamable HTTP Endpoint" required>
          <a-input v-model:value="serverForm.endpoint" placeholder="https://mcp.example.com/mcp" />
          <a-space wrap style="margin-top: 8px">
            <a-button :loading="serverTesting" @click="testServerForm">保存前测试连接</a-button>
            <template v-if="serverTestTools">
              <a-tag color="green">连接成功 · {{ serverTestTools.length }} 个 Tool</a-tag>
              <a-tag v-for="name in serverTestTools.slice(0, 8)" :key="name">{{ name }}</a-tag>
              <span v-if="serverTestTools.length > 8" class="muted">还有 {{ serverTestTools.length - 8 }} 个</span>
            </template>
          </a-space>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item label="鉴权 Header"><a-input v-model:value="serverForm.authorization_header" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="editingServerId ? '更新鉴权值（留空保持原值）' : '鉴权值'"><a-input-password v-model:value="serverForm.authorization_value" placeholder="例如 Bearer xxx" /></a-form-item></a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item label="状态"><a-select v-model:value="serverForm.status"><a-select-option value="draft">草稿</a-select-option><a-select-option value="active">启用</a-select-option><a-select-option value="disabled">停用</a-select-option></a-select></a-form-item></a-col>
          <a-col :span="12"><a-form-item label="超时秒数"><a-input-number v-model:value="serverForm.timeout_seconds" :min="1" :max="300" style="width: 100%" /></a-form-item></a-col>
        </a-row>
        <a-form-item label="描述"><a-textarea v-model:value="serverForm.description" :rows="3" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="gatewayVisible" :title="editingGatewayId ? '编辑虚拟 MCP 网关' : '创建虚拟 MCP 网关'" width="820px" :confirm-loading="submitting" @ok="saveGateway">
      <a-form layout="vertical" :model="gatewayForm">
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item label="名称" required><a-input v-model:value="gatewayForm.name" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item label="唯一标识" required><a-input v-model:value="gatewayForm.slug" :disabled="Boolean(editingGatewayId)" placeholder="例如 readonly" /></a-form-item></a-col>
        </a-row>
        <a-form-item label="发布的 Tool" required>
          <a-select v-model:value="gatewayForm.tools" mode="multiple" show-search option-filter-prop="label" placeholder="选择要通过该网关发布的 Tool">
            <a-select-opt-group v-for="server in activeServers" :key="server.id" :label="server.name">
              <a-select-option v-for="tool in enabledTools(server)" :key="toolKey(server.id, tool.name)" :value="toolKey(server.id, tool.name)" :label="`${server.name} ${tool.name}`">
                {{ tool.name }}（对外：{{ tool.exposed_name }}）
              </a-select-option>
            </a-select-opt-group>
          </a-select>
        </a-form-item>
        <a-form-item label="状态"><a-select v-model:value="gatewayForm.status"><a-select-option value="active">启用</a-select-option><a-select-option value="disabled">停用</a-select-option></a-select></a-form-item>
        <a-form-item label="描述"><a-textarea v-model:value="gatewayForm.description" :rows="3" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'

import {
  createMcpGateway,
  createMcpServer,
  debugMcpUpstream,
  deleteMcpGateway,
  deleteMcpServer,
  discoverMcpServer,
  listMcpAudit,
  listMcpGateways,
  listMcpServers,
  updateMcpGateway,
  updateMcpServer,
} from '../api'

const route = useRoute()
const activePage = computed(() => route.meta.mcpTab || 'servers')
const pageTitle = computed(() => ({ servers: 'MCP 服务', gateways: 'MCP 网关', audit: 'MCP 调用审计' }[activePage.value]))
const pageSubtitle = computed(() => ({
  servers: '集中接入远程 Streamable HTTP MCP Server，并发现 Tool 能力',
  gateways: '组合已审核 Tool，通过统一 Endpoint 向任意 MCP Client 发布',
  audit: '查看 MCP Tool 调用、拒绝和上游错误记录',
}[activePage.value]))
const loading = ref(false)
const submitting = ref(false)
const actionId = ref(null)
const servers = ref([])
const gateways = ref([])
const auditRows = ref([])
const serverTesting = ref(false)
const serverTestTools = ref(null)
const serverVisible = ref(false)
const gatewayVisible = ref(false)
const editingServerId = ref(null)
const editingGatewayId = ref(null)
const origin = window.location.origin
const serverForm = reactive({ slug: '', name: '', description: '', endpoint: '', authorization_header: 'Authorization', authorization_value: '', status: 'draft', timeout_seconds: 30 })
const gatewayForm = reactive({ slug: '', name: '', description: '', status: 'active', tools: [] })

const serverColumns = [
  { title: 'MCP Server', key: 'server' },
  { title: '健康状态', key: 'health', width: 150 },
  { title: 'Tool', key: 'tools' },
  { title: '状态', key: 'status', width: 90 },
  { title: '操作', key: 'actions', width: 260 },
]
const gatewayColumns = [
  { title: '虚拟网关', key: 'gateway', width: 260 },
  { title: '发布能力', key: 'tools' },
  { title: '状态', key: 'status', width: 90 },
  { title: '操作', key: 'actions', width: 210 },
]
const auditColumns = [
  { title: '请求 ID', dataIndex: 'request_id', width: 260 },
  { title: '调用目标', key: 'target' },
  { title: 'Token ID', dataIndex: 'token_id', width: 100 },
  { title: '耗时 ms', dataIndex: 'duration_ms', width: 100 },
  { title: '状态', key: 'status', width: 90 },
  { title: '时间', key: 'time', width: 190 },
]

const activeServers = computed(() => servers.value.filter(item => item.status === 'active'))
const enabledTools = server => (server.tools || []).filter(tool => tool.enabled)
const toolKey = (serverId, toolName) => `${serverId}:${toolName}`
const statusLabel = value => ({ active: '启用', disabled: '停用', draft: '草稿' }[value] || value)
const healthLabel = value => ({ healthy: '正常', unhealthy: '异常', unknown: '未检测' }[value] || value)
const healthColor = value => ({ healthy: 'green', unhealthy: 'red', unknown: 'default' }[value] || 'default')
const formatTime = value => value ? new Date(value).toLocaleString() : '-'
const gatewayToolNames = gateway => (gateway.bindings || []).flatMap(binding => binding.allowed_tools.map(name => `${binding.server_slug}__${name}`))

const fetchAll = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const [serverRows, gatewayRows, audits] = await Promise.all([listMcpServers(), listMcpGateways(), listMcpAudit({ limit: 200 })])
    servers.value = serverRows || []
    gateways.value = gatewayRows || []
    auditRows.value = audits || []
  } catch (error) {
    message.error(error.response?.data?.detail || '获取 MCP 配置失败')
  } finally {
    loading.value = false
  }
}

const openServer = record => {
  editingServerId.value = record?.id || null
  Object.assign(serverForm, {
    slug: record?.slug || '', name: record?.name || '', description: record?.description || '', endpoint: record?.endpoint || '',
    authorization_header: record?.authorization_header || 'Authorization', authorization_value: '', status: record?.status || 'draft', timeout_seconds: record?.timeout_seconds || 30,
  })
  serverTestTools.value = null
  serverVisible.value = true
}

const testServerForm = async () => {
  if (serverTesting.value) return
  if (!serverForm.endpoint.trim()) return message.warning('请填写 Endpoint')
  serverTesting.value = true
  serverTestTools.value = null
  try {
    const payload = {
      server_id: editingServerId.value || undefined,
      endpoint: serverForm.endpoint.trim(),
      authorization_header: serverForm.authorization_header || 'Authorization',
      authorization_value: serverForm.authorization_value || undefined,
      timeout_seconds: serverForm.timeout_seconds,
      method: 'tools/list',
      params: {},
    }
    const result = await debugMcpUpstream(payload)
    if (result.response?.error) throw new Error(result.response.error.message)
    serverTestTools.value = (result.response?.result?.tools || []).map(tool => tool.name)
    message.success('MCP 服务连接成功')
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || 'MCP 服务连接失败')
  } finally {
    serverTesting.value = false
  }
}

const saveServer = async () => {
  if (submitting.value) return
  if (!serverForm.name.trim() || !serverForm.slug.trim() || !serverForm.endpoint.trim()) return message.warning('请填写名称、标识和 Endpoint')
  submitting.value = true
  try {
    const payload = { ...serverForm, name: serverForm.name.trim(), slug: serverForm.slug.trim(), endpoint: serverForm.endpoint.trim() }
    if (editingServerId.value && !payload.authorization_value) delete payload.authorization_value
    if (editingServerId.value) await updateMcpServer(editingServerId.value, payload)
    else await createMcpServer(payload)
    serverVisible.value = false
    await fetchAll()
    message.success('MCP Server 已保存')
  } catch (error) {
    message.error(error.response?.data?.detail || '保存失败')
  } finally {
    submitting.value = false
  }
}

const discover = async record => {
  if (actionId.value) return
  actionId.value = `discover-${record.id}`
  try {
    await discoverMcpServer(record.id)
    await fetchAll()
    message.success('连接成功，Tool 已更新')
  } catch (error) {
    message.error(error.response?.data?.detail || '连接发现失败')
  } finally {
    actionId.value = null
  }
}

const removeServer = async record => {
  if (actionId.value) return
  actionId.value = `server-${record.id}`
  try { await deleteMcpServer(record.id); await fetchAll(); message.success('已删除') }
  catch (error) { message.error(error.response?.data?.detail || '删除失败') }
  finally { actionId.value = null }
}

const openGateway = record => {
  editingGatewayId.value = record?.id || null
  Object.assign(gatewayForm, {
    slug: record?.slug || '', name: record?.name || '', description: record?.description || '', status: record?.status || 'active',
    tools: (record?.bindings || []).flatMap(binding => binding.allowed_tools.map(name => toolKey(binding.server_id, name))),
  })
  gatewayVisible.value = true
}

const gatewayBindings = () => {
  const grouped = new Map()
  gatewayForm.tools.forEach(value => {
    const separator = value.indexOf(':')
    const serverId = Number(value.slice(0, separator))
    const name = value.slice(separator + 1)
    if (!grouped.has(serverId)) grouped.set(serverId, [])
    grouped.get(serverId).push(name)
  })
  return [...grouped.entries()].map(([server_id, allowed_tools]) => ({ server_id, allowed_tools }))
}

const saveGateway = async () => {
  if (submitting.value) return
  if (!gatewayForm.name.trim() || !gatewayForm.slug.trim()) return message.warning('请填写名称和标识')
  if (!gatewayForm.tools.length) return message.warning('请至少发布一个 Tool')
  submitting.value = true
  try {
    const payload = { slug: gatewayForm.slug.trim(), name: gatewayForm.name.trim(), description: gatewayForm.description, status: gatewayForm.status, bindings: gatewayBindings() }
    if (editingGatewayId.value) await updateMcpGateway(editingGatewayId.value, payload)
    else await createMcpGateway(payload)
    gatewayVisible.value = false
    await fetchAll()
    message.success('虚拟 MCP 网关已保存')
  } catch (error) {
    message.error(error.response?.data?.detail || '保存失败')
  } finally {
    submitting.value = false
  }
}

const removeGateway = async record => {
  if (actionId.value) return
  actionId.value = `gateway-${record.id}`
  try { await deleteMcpGateway(record.id); await fetchAll(); message.success('已删除') }
  catch (error) { message.error(error.response?.data?.detail || '删除失败') }
  finally { actionId.value = null }
}

const copy = async value => { await navigator.clipboard.writeText(value); message.success('地址已复制') }
onMounted(fetchAll)
</script>

<style scoped>
.title { font-weight: 600; }
.muted { color: #8c8c8c; font-size: 12px; word-break: break-all; }
</style>
