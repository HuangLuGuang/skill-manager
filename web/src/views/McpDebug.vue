<template>
  <div>
    <a-page-header title="MCP 调试" sub-title="保存前直连测试 MCP 服务，或验证平台 MCP 网关的凭证与 Tool 调用" />

    <a-alert
      type="info"
      show-icon
      message="调试配置不会保存"
      description="临时鉴权值只保存在页面内存中；平台网关调用会经过真实权限校验并写入调用审计。"
      style="margin: 16px 0"
    />

    <a-card title="连接配置">
      <a-radio-group v-model:value="targetMode" button-style="solid" @change="resetConnection">
        <a-radio-button value="service">直连 MCP 服务</a-radio-button>
        <a-radio-button value="gateway">平台 MCP 网关</a-radio-button>
      </a-radio-group>

      <a-form v-if="targetMode === 'service'" layout="vertical" style="margin-top: 16px">
        <a-row :gutter="16">
          <a-col :xs="24" :lg="8">
            <a-form-item label="已有服务（可选）">
              <a-select v-model:value="serverId" allow-clear placeholder="不选择则测试临时 Endpoint" @change="loadServer">
                <a-select-option v-for="server in servers" :key="server.id" :value="server.id">
                  {{ server.name }}（{{ server.slug }}）
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :lg="16">
            <a-form-item label="Streamable HTTP Endpoint" required>
              <a-input v-model:value="serviceEndpoint" placeholder="https://mcp.example.com/mcp" @change="resetConnection" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :lg="7">
            <a-form-item label="鉴权 Header"><a-input v-model:value="authorizationHeader" /></a-form-item>
          </a-col>
          <a-col :xs="24" :lg="11">
            <a-form-item label="鉴权值">
              <a-input-password v-model:value="authorizationValue" autocomplete="off" placeholder="例如 Bearer xxx" />
              <div class="muted">{{ serviceSecretHint }}</div>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :lg="6">
            <a-form-item label="超时秒数"><a-input-number v-model:value="timeoutSeconds" :min="1" :max="300" style="width: 100%" /></a-form-item>
          </a-col>
        </a-row>
      </a-form>

      <a-form v-else layout="vertical" style="margin-top: 16px">
        <a-row :gutter="16">
          <a-col :xs="24" :lg="9">
            <a-form-item label="平台网关" required>
              <a-select v-model:value="gatewaySlug" placeholder="选择已启用的网关" @change="loadGateway">
                <a-select-option v-for="gateway in activeGateways" :key="gateway.slug" :value="gateway.slug">
                  {{ gateway.name }}（{{ gateway.slug }}）
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :lg="15">
            <a-form-item label="MCP 网关凭证" required>
              <a-input-password v-model:value="gatewayToken" autocomplete="off" placeholder="粘贴 amat_..." @change="resetConnection" @pressEnter="connect" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-input v-model:value="gatewayEndpoint" placeholder="http://localhost:8001/mcp/test" @change="resetConnection">
          <template #addonBefore>Endpoint</template>
        </a-input>
      </a-form>

      <a-space wrap style="margin-top: 16px">
        <a-button v-if="!connected" type="primary" :loading="connecting" @click="connect">连接并列出 Tool</a-button>
        <a-button v-else danger @click="resetConnection">断开连接</a-button>
        <a-button v-if="connected" :loading="pinging" @click="ping">Ping</a-button>
        <a-button @click="copyClientConfig">复制客户端配置</a-button>
        <a-tag :color="connected ? 'green' : 'default'">{{ connectionLabel }}</a-tag>
      </a-space>
    </a-card>

    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :xs="24" :xl="10">
        <a-card title="Tools" :loading="connecting">
          <template #extra><span class="muted">{{ tools.length }} 个</span></template>
          <a-empty v-if="!tools.length" description="连接后显示可调用的 Tool" />
          <a-list v-else :data-source="tools" size="small" class="tool-list">
            <template #renderItem="{ item }">
              <a-list-item :class="{ selected: selectedToolName === item.name }" @click="selectedToolName = item.name">
                <a-list-item-meta :title="item.name" :description="item.description || '无描述'" />
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="14">
        <a-card title="Tool 调用">
          <a-empty v-if="!selectedTool" description="请选择一个 Tool" />
          <template v-else>
            <div class="tool-title">{{ selectedTool.name }}</div>
            <div class="muted">{{ selectedTool.description || '无描述' }}</div>
            <a-form layout="vertical" style="margin-top: 16px">
              <a-empty v-if="!toolFields.length" description="该 Tool 不需要参数" />
              <a-form-item v-for="field in toolFields" :key="field.name" :required="field.required">
                <template #label>
                  <a-space size="small">
                    <span>{{ field.schema.title || field.name }}</span>
                    <a-tag v-if="!field.required">可选</a-tag>
                  </a-space>
                </template>
                <a-select
                  v-if="field.kind === 'enum'"
                  v-model:value="argumentValues[field.name]"
                  allow-clear
                  :placeholder="field.schema.description || `请选择 ${field.name}`"
                >
                  <a-select-option v-for="option in field.schema.enum" :key="String(option)" :value="option">{{ option }}</a-select-option>
                </a-select>
                <a-select
                  v-else-if="field.kind === 'boolean'"
                  v-model:value="argumentValues[field.name]"
                  allow-clear
                  :placeholder="field.schema.description || `请选择 ${field.name}`"
                >
                  <a-select-option :value="true">true</a-select-option>
                  <a-select-option :value="false">false</a-select-option>
                </a-select>
                <a-input-number
                  v-else-if="field.kind === 'number'"
                  v-model:value="argumentValues[field.name]"
                  :min="field.schema.minimum"
                  :max="field.schema.maximum"
                  :step="field.schema.type === 'integer' ? 1 : undefined"
                  :placeholder="field.schema.description || field.name"
                  style="width: 100%"
                />
                <a-select
                  v-else-if="field.kind === 'array'"
                  v-model:value="argumentValues[field.name]"
                  mode="tags"
                  :placeholder="field.schema.description || '输入后按回车添加'"
                />
                <a-textarea
                  v-else-if="field.kind === 'complex'"
                  v-model:value="complexArgumentTexts[field.name]"
                  :rows="5"
                  class="code-input"
                  :placeholder="field.schema.description || `${field.name} 为复杂类型，请填写该字段的 JSON`"
                />
                <a-input
                  v-else
                  v-model:value="argumentValues[field.name]"
                  :placeholder="field.schema.description || `请输入 ${field.name}`"
                />
                <div v-if="field.schema.description" class="field-description">{{ field.schema.description }}</div>
              </a-form-item>
              <a-space>
                <a-button type="primary" :loading="calling" @click="callTool">调用 Tool</a-button>
                <a-button @click="resetArguments">重置参数</a-button>
              </a-space>
            </a-form>
            <a-collapse style="margin-top: 16px">
              <a-collapse-panel key="schema" header="Input Schema"><pre>{{ pretty(selectedTool.inputSchema || {}) }}</pre></a-collapse-panel>
              <a-collapse-panel v-if="callResult" key="result" header="最近调用结果"><pre>{{ pretty(callResult) }}</pre></a-collapse-panel>
            </a-collapse>
          </template>
        </a-card>
      </a-col>
    </a-row>

    <a-card title="请求历史" style="margin-top: 16px">
      <template #extra><a-button type="link" :disabled="!history.length" @click="history = []">清空</a-button></template>
      <a-empty v-if="!history.length" description="尚无调试请求" />
      <a-collapse v-else>
        <a-collapse-panel v-for="item in history" :key="item.key">
          <template #header>
            <a-space><a-tag :color="item.ok ? 'green' : 'red'">{{ item.ok ? '成功' : '失败' }}</a-tag><span>{{ item.method }}</span><span class="muted">{{ item.duration }} ms · {{ item.time }}</span></a-space>
          </template>
          <a-row :gutter="16">
            <a-col :xs="24" :lg="12"><div class="json-title">Request</div><pre>{{ pretty(item.request) }}</pre></a-col>
            <a-col :xs="24" :lg="12"><div class="json-title">Response</div><pre>{{ pretty(item.response) }}</pre></a-col>
          </a-row>
        </a-collapse-panel>
      </a-collapse>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'

import { debugMcpUpstream, listMcpGateways, listMcpServers } from '../api'

const targetMode = ref('service')
const servers = ref([])
const gateways = ref([])
const serverId = ref()
const serviceEndpoint = ref('')
const authorizationHeader = ref('Authorization')
const authorizationValue = ref('')
const timeoutSeconds = ref(30)
const gatewaySlug = ref()
const gatewayToken = ref('')
const gatewayEndpoint = ref('')
const connected = ref(false)
const connecting = ref(false)
const pinging = ref(false)
const calling = ref(false)
const protocolVersion = ref('')
const tools = ref([])
const selectedToolName = ref()
const argumentValues = ref({})
const complexArgumentTexts = ref({})
const callResult = ref(null)
const history = ref([])
let requestSequence = 0
let historySequence = 0

const selectedServer = computed(() => servers.value.find(item => item.id === serverId.value))
const activeGateways = computed(() => gateways.value.filter(item => item.status === 'active'))
const selectedTool = computed(() => tools.value.find(item => item.name === selectedToolName.value))
const toolFields = computed(() => {
  const schema = selectedTool.value?.inputSchema || {}
  const required = new Set(schema.required || [])
  return Object.entries(schema.properties || {}).map(([name, fieldSchema]) => {
    let kind = 'string'
    if (Array.isArray(fieldSchema.enum)) kind = 'enum'
    else if (fieldSchema.type === 'boolean') kind = 'boolean'
    else if (fieldSchema.type === 'number' || fieldSchema.type === 'integer') kind = 'number'
    else if (fieldSchema.type === 'array' && ['string', 'number', 'integer'].includes(fieldSchema.items?.type)) kind = 'array'
    else if (fieldSchema.type === 'object' || fieldSchema.type === 'array' || fieldSchema.oneOf || fieldSchema.anyOf) kind = 'complex'
    return { name, schema: fieldSchema, required: required.has(name), kind }
  })
})
const connectionLabel = computed(() => connected.value ? `已连接${protocolVersion.value ? ` · ${protocolVersion.value}` : ''}` : '未连接')
const serviceSecretHint = computed(() => {
  if (!selectedServer.value) return '临时鉴权值不会保存。'
  return serviceEndpoint.value === selectedServer.value.endpoint
    ? '留空将使用该服务已保存的鉴权值。'
    : 'Endpoint 已变化，留空不会发送原服务的鉴权值。'
})
const pretty = value => JSON.stringify(value, null, 2)

const exampleValue = schema => {
  if (Object.prototype.hasOwnProperty.call(schema || {}, 'default')) return schema.default
  if (schema?.type === 'boolean') return false
  if (schema?.type === 'integer' || schema?.type === 'number') return 0
  if (schema?.type === 'array') return []
  if (schema?.type === 'object') return {}
  return ''
}
const resetArguments = () => {
  const values = {}
  const complex = {}
  toolFields.value.forEach(field => {
    const hasDefault = Object.prototype.hasOwnProperty.call(field.schema, 'default')
    if (!hasDefault && !field.required) return
    const value = exampleValue(field.schema)
    if (field.kind === 'complex') complex[field.name] = pretty(value)
    else values[field.name] = value
  })
  argumentValues.value = values
  complexArgumentTexts.value = complex
  callResult.value = null
}
watch(selectedToolName, resetArguments)

const resetConnection = () => {
  connected.value = false
  protocolVersion.value = ''
  tools.value = []
  selectedToolName.value = undefined
  callResult.value = null
}

const loadServer = () => {
  if (selectedServer.value) {
    serviceEndpoint.value = selectedServer.value.endpoint
    authorizationHeader.value = selectedServer.value.authorization_header || 'Authorization'
    timeoutSeconds.value = selectedServer.value.timeout_seconds || 30
  }
  authorizationValue.value = ''
  resetConnection()
}

const loadGateway = () => {
  gatewayEndpoint.value = gatewaySlug.value ? `${window.location.origin}/mcp/${gatewaySlug.value}` : ''
  resetConnection()
}

const serviceRequest = async (method, params) => {
  const request = {
    server_id: serverId.value,
    endpoint: serviceEndpoint.value.trim(),
    authorization_header: authorizationHeader.value.trim() || 'Authorization',
    ...(authorizationValue.value ? { authorization_value: authorizationValue.value } : {}),
    timeout_seconds: timeoutSeconds.value,
    method,
    params,
  }
  const started = performance.now()
  let response
  let ok = false
  try {
    const result = await debugMcpUpstream(request)
    response = result.response
    if (response?.error) throw new Error(response.error.message)
    ok = true
    return response
  } catch (error) {
    response ||= error.response?.data || { error: error.message }
    throw error
  } finally {
    addHistory(method, { endpoint: request.endpoint, params }, response, ok, Math.round(performance.now() - started))
  }
}

const gatewayRequest = async (method, params = {}, notification = false) => {
  const requestId = notification ? undefined : ++requestSequence
  const payload = { jsonrpc: '2.0', ...(requestId === undefined ? {} : { id: requestId }), method, params }
  const started = performance.now()
  let responseData
  let ok = false
  try {
    const response = await fetch(gatewayEndpoint.value.trim(), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${gatewayToken.value.trim()}`,
        Accept: 'application/json, text/event-stream',
        'Content-Type': 'application/json',
        'MCP-Protocol-Version': protocolVersion.value || '2025-11-25',
      },
      body: JSON.stringify(payload),
    })
    const text = await response.text()
    responseData = text ? JSON.parse(text) : null
    if (!response.ok) throw new Error(responseData?.detail || `HTTP ${response.status}`)
    if (responseData?.error) throw new Error(responseData.error.message)
    ok = true
    return responseData
  } catch (error) {
    responseData ||= { error: error.message }
    throw error
  } finally {
    addHistory(method, payload, responseData, ok, Math.round(performance.now() - started))
  }
}

const addHistory = (method, request, response, ok, duration) => history.value.unshift({
  key: ++historySequence,
  method,
  request,
  response,
  ok,
  duration,
  time: new Date().toLocaleTimeString(),
})

const request = (method, params = {}, notification = false) => targetMode.value === 'service'
  ? serviceRequest(method, params)
  : gatewayRequest(method, params, notification)

const connect = async () => {
  if (connecting.value) return
  if (targetMode.value === 'service' && !serviceEndpoint.value.trim()) return message.warning('请填写 MCP Endpoint')
  if (targetMode.value === 'gateway' && (!gatewaySlug.value || !gatewayEndpoint.value.trim() || !gatewayToken.value.trim())) return message.warning('请选择网关，并填写 Endpoint 和 MCP 网关凭证')
  connecting.value = true
  resetConnection()
  try {
    if (targetMode.value === 'gateway') {
      const initialized = await gatewayRequest('initialize', {
        protocolVersion: '2025-11-25',
        capabilities: {},
        clientInfo: { name: 'agent-manager-debugger', version: '0.1.0' },
      })
      protocolVersion.value = initialized?.result?.protocolVersion || '2025-11-25'
      await gatewayRequest('notifications/initialized', {}, true)
    }
    const listed = await request('tools/list')
    tools.value = listed?.result?.tools || []
    selectedToolName.value = tools.value[0]?.name
    connected.value = true
    message.success(`连接成功，发现 ${tools.value.length} 个 Tool`)
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || 'MCP 连接失败')
  } finally {
    connecting.value = false
  }
}

const ping = async () => {
  if (pinging.value) return
  pinging.value = true
  try { await request('ping'); message.success('Ping 成功') }
  catch (error) { message.error(error.response?.data?.detail || error.message || 'Ping 失败') }
  finally { pinging.value = false }
}

const callTool = async () => {
  if (calling.value || !selectedTool.value) return
  const args = {}
  try {
    for (const field of toolFields.value) {
      let value = field.kind === 'complex' ? complexArgumentTexts.value[field.name] : argumentValues.value[field.name]
      const empty = value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)
      if (empty) {
        if (field.required) throw new Error(`请填写必填参数：${field.schema.title || field.name}`)
        continue
      }
      if (field.kind === 'complex') value = JSON.parse(value)
      if (field.kind === 'array') {
        const itemType = field.schema.items?.type
        value = value.map(item => itemType === 'string' ? item : Number(item))
        if (itemType !== 'string' && value.some(Number.isNaN)) throw new Error(`${field.name} 包含无效数字`)
      }
      args[field.name] = value
    }
  } catch (error) {
    return message.warning(error instanceof SyntaxError ? '复杂参数不是有效 JSON' : error.message)
  }
  calling.value = true
  try {
    callResult.value = await request('tools/call', { name: selectedTool.value.name, arguments: args })
    message.success('Tool 调用完成')
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || 'Tool 调用失败')
  } finally {
    calling.value = false
  }
}

const copyClientConfig = async () => {
  const name = targetMode.value === 'service' ? (selectedServer.value?.slug || 'mcp-server') : gatewaySlug.value
  const url = targetMode.value === 'service' ? serviceEndpoint.value.trim() : gatewayEndpoint.value
  if (!name || !url) return message.warning('请先填写连接配置')
  const config = { mcpServers: { [name]: { type: 'streamable-http', url } } }
  if (targetMode.value === 'gateway') config.mcpServers[name].headers = { Authorization: 'Bearer amat_xxx' }
  else if (authorizationValue.value || selectedServer.value) config.mcpServers[name].headers = { [authorizationHeader.value || 'Authorization']: '<secret>' }
  await navigator.clipboard.writeText(pretty(config))
  message.success('客户端配置已复制，密钥使用占位符')
}

onMounted(async () => {
  try {
    const [serverRows, gatewayRows] = await Promise.all([listMcpServers(), listMcpGateways()])
    servers.value = serverRows || []
    gateways.value = gatewayRows || []
    gatewaySlug.value = activeGateways.value[0]?.slug
    loadGateway()
  } catch (error) {
    message.error(error.response?.data?.detail || '获取 MCP 配置失败')
  }
})
</script>

<style scoped>
.tool-list :deep(.ant-list-item) { cursor: pointer; padding: 12px; border-radius: 6px; }
.tool-list :deep(.ant-list-item:hover), .tool-list :deep(.ant-list-item.selected) { background: #f0f5ff; }
.tool-title { font-size: 16px; font-weight: 600; }
.muted { color: #8c8c8c; }
.code-input { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.field-description { margin-top: 4px; color: #8c8c8c; font-size: 12px; }
.json-title { margin-bottom: 8px; font-weight: 600; }
pre { max-height: 420px; margin: 0; padding: 12px; overflow: auto; background: #f7f8fa; border-radius: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
