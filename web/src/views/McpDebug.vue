<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.1o166ch')" :sub-title="$t('legacy.1p8eh88')" />
      </template>

    <a-alert
      type="info"
      show-icon
      :message="$t('legacy.wr9plc')"
      :description="$t('legacy.17lol69')"
      style="margin: 16px 0"
    />

    <a-card :title="$t('legacy.1qcyuf')">
      <a-radio-group v-model:value="targetMode" button-style="solid" @change="resetConnection">
        <a-radio-button value="service">{{ $t("legacy.r4nafb") }}</a-radio-button>
        <a-radio-button value="gateway">{{ $t("legacy.1akoixy") }}</a-radio-button>
      </a-radio-group>

      <a-form v-if="targetMode === 'service'" layout="vertical" style="margin-top: 16px">
        <a-row :gutter="16">
          <a-col :xs="24" :lg="8">
            <a-form-item :label="$t('legacy.swalzt')">
              <a-select v-model:value="serverId" allow-clear :placeholder="$t('legacy.xbjfm4')" @change="loadServer">
                <a-select-option v-for="server in servers" :key="server.id" :value="server.id">
                  {{ server.name }}（{{ server.slug }}）
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :lg="16">
            <a-form-item label="Streamable HTTP Endpoint" required :validate-status="endpointError ? 'error' : undefined" :help="endpointError ? t(endpointError) : undefined">
              <a-input ref="endpointInput" v-model:value="serviceEndpoint" aria-label="Streamable HTTP Endpoint" :aria-invalid="!!endpointError" placeholder="https://mcp.example.com/mcp" @change="endpointError = ''; resetConnection()" @pressEnter="connect" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :lg="7">
            <a-form-item :label="$t('legacy.17s488l')"><a-input v-model:value="authorizationHeader" /></a-form-item>
          </a-col>
          <a-col :xs="24" :lg="11">
            <a-form-item :label="$t('legacy.1iwkwic')">
              <a-input-password v-model:value="authorizationValue" autocomplete="off" :placeholder="$t('legacy.1479ky1')" />
              <div class="muted">{{ serviceSecretHint }}</div>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :lg="6">
            <a-form-item :label="$t('legacy.tabbi8')"><a-input-number v-model:value="timeoutSeconds" :min="1" :max="300" style="width: 100%" /></a-form-item>
          </a-col>
        </a-row>
      </a-form>

      <a-form v-else layout="vertical" style="margin-top: 16px">
        <a-row :gutter="16">
          <a-col :xs="24" :lg="9">
            <a-form-item :label="$t('legacy.1hqgzoi')" required>
              <a-select v-model:value="gatewaySlug" :placeholder="$t('legacy.1iqszp0')" @change="loadGateway">
                <a-select-option v-for="gateway in activeGateways" :key="gateway.slug" :value="gateway.slug">
                  {{ gateway.name }}（{{ gateway.slug }}）
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :lg="15">
            <a-form-item required :validate-status="gatewayTokenError ? 'error' : undefined" :help="gatewayTokenError ? t(gatewayTokenError) : undefined">
              <template #label><span>{{ t('mcpDebug.gatewayCredential') }}</span><a-tooltip :title="t('mcpDebug.gatewayCredentialHelp')"><QuestionCircleOutlined tabindex="0" :aria-label="t('mcpDebug.gatewayCredentialHelp')" style="margin-left: 6px" /></a-tooltip></template>
              <a-input-password ref="gatewayTokenInput" v-model:value="gatewayToken" autocomplete="off" :placeholder="$t('legacy.1hbgqpx')" @update:value="gatewayTokenChecked = true" @change="resetConnection" @pressEnter="connect" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-input v-model:value="gatewayEndpoint" placeholder="http://localhost:8001/mcp/test" @change="resetConnection">
          <template #addonBefore>Endpoint</template>
        </a-input>
        <a-form-item style="margin-top: 16px" :validate-status="gatewayTimeoutError ? 'error' : undefined" :help="gatewayTimeoutError ? t('mcpDebug.connectionTimeoutInvalid') : undefined">
          <template #label><span>{{ t('mcpDebug.connectionTimeoutLabel') }}</span><a-tooltip :title="t('mcpDebug.connectionTimeoutHelp')"><QuestionCircleOutlined tabindex="0" :aria-label="t('mcpDebug.connectionTimeoutHelp')" style="margin-left: 6px" /></a-tooltip></template>
          <a-input-number ref="gatewayTimeoutInput" v-model:value="gatewayTimeoutSeconds" :step="1" :aria-label="t('mcpDebug.connectionTimeoutLabel')" :aria-invalid="gatewayTimeoutError" @update:value="gatewayTimeoutChecked = true; resetConnection()" />
        </a-form-item>
      </a-form>

      <a-space wrap style="margin-top: 16px">
        <a-button v-if="!connected" type="primary" :loading="connecting" :disabled="connecting" @click="connect">{{ $t("legacy.bt1d8b") }}</a-button>
        <a-button v-else danger @click="resetConnection">{{ $t("legacy.2kwd2d") }}</a-button>
        <a-button v-if="connected" :loading="pinging" @click="ping">Ping</a-button>
        <a-button @click="copyClientConfig">{{ $t("legacy.135fagt") }}</a-button>
        <a-tag :color="connected ? 'green' : 'default'">{{ connectionLabel }}</a-tag>
      </a-space>
    </a-card>

    <a-row :gutter="16" style="margin-top: 16px">
      <a-col :xs="24" :xl="10">
        <a-card title="Tools" :loading="connecting">
          <template #extra><span class="muted">{{ t('uiExperience.toolCount', { count: tools.length }) }}</span></template>
          <a-empty v-if="!tools.length" :description="$t('legacy.1qrt9zy')" />
          <a-list v-else :data-source="tools" size="small" class="tool-list">
            <template #renderItem="{ item }">
              <a-list-item :class="{ selected: selectedToolName === item.name }" @click="selectedToolName = item.name">
                <a-list-item-meta :title="item.name" :description="item.description || $t('legacy.1qkgodc')" />
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="14">
        <a-card :title="$t('legacy.1nwtalq')">
          <a-empty v-if="!selectedTool" :description="$t('legacy.pymhbs')" />
          <template v-else>
            <div class="tool-title">{{ selectedTool.name }}</div>
            <div class="muted">{{ selectedTool.description || $t('legacy.1qkgodc') }}</div>
            <a-form layout="vertical" style="margin-top: 16px">
              <a-empty v-if="!toolFields.length" :description="$t('legacy.1en7knw')" />
              <a-form-item v-for="field in toolFields" :key="field.name" :required="field.required">
                <template #label>
                  <a-space size="small">
                    <span>{{ field.schema.title || field.name }}</span>
                    <a-tag v-if="!field.required">{{ $t("legacy.zflkxh") }}</a-tag>
                  </a-space>
                </template>
                <a-select
                  v-if="field.kind === 'enum'"
                  v-model:value="argumentValues[field.name]"
                  allow-clear
                  :placeholder="field.schema.description || text(`请选择 ${field.name}`, `Select ${field.name}`)"
                >
                  <a-select-option v-for="option in field.schema.enum" :key="String(option)" :value="option">{{ option }}</a-select-option>
                </a-select>
                <a-select
                  v-else-if="field.kind === 'boolean'"
                  v-model:value="argumentValues[field.name]"
                  allow-clear
                  :placeholder="field.schema.description || text(`请选择 ${field.name}`, `Select ${field.name}`)"
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
                  :placeholder="field.schema.description || $t('legacy.r7tjvz')"
                />
                <a-textarea
                  v-else-if="field.kind === 'complex'"
                  v-model:value="complexArgumentTexts[field.name]"
                  :rows="5"
                  class="code-input"
                  :placeholder="field.schema.description || text(
                    `${field.name} 为复杂类型，请填写该字段的 JSON`,
                    `${field.name} is a complex value. Enter JSON for this field.`,
                  )"
                />
                <a-input
                  v-else
                  v-model:value="argumentValues[field.name]"
                  :placeholder="field.schema.description || text(`请输入 ${field.name}`, `Enter ${field.name}`)"
                />
                <div v-if="field.schema.description" class="field-description">{{ field.schema.description }}</div>
              </a-form-item>
              <a-space>
                <a-button type="primary" :loading="calling" @click="callTool">{{ $t("legacy.1tke9d0") }}</a-button>
                <a-button @click="resetArguments">{{ $t("legacy.c8hbyo") }}</a-button>
              </a-space>
            </a-form>
            <a-collapse style="margin-top: 16px">
              <a-collapse-panel key="schema" :header="t('mcpDebug.inputSchema')"><pre>{{ pretty(selectedTool.inputSchema || {}) }}</pre></a-collapse-panel>
              <a-collapse-panel v-if="callResult" key="result" :header="$t('legacy.uqgcyu')"><pre>{{ pretty(callResult) }}</pre></a-collapse-panel>
            </a-collapse>
          </template>
        </a-card>
      </a-col>
    </a-row>

    <a-card :title="$t('legacy.1nw1cic')" style="margin-top: 16px">
      <template #extra><a-button type="link" :disabled="!history.length" @click="history = []">{{ $t("legacy.9mbwb2") }}</a-button></template>
      <a-empty v-if="!history.length" :description="$t('legacy.1xg7io2')" />
      <a-collapse v-else>
        <a-collapse-panel v-for="item in history" :key="item.key">
          <template #header>
            <a-space wrap><a-tag :color="item.ok ? 'green' : 'red'">{{ item.ok ? $t('legacy.1rraohc') : $t('legacy.12db3qz') }}</a-tag><span>{{ item.method }}</span><span class="muted">{{ formatDebugDuration(item.duration, t) }} · {{ item.time }}</span></a-space>
          </template>
          <a-row :gutter="16">
            <a-col :xs="24" :lg="12"><div class="json-title">Request</div><pre>{{ pretty(item.request) }}</pre></a-col>
            <a-col :xs="24" :lg="12"><div class="json-title">Response</div><pre>{{ pretty(localizeDebugResponse(item.response, t)) }}</pre></a-col>
          </a-row>
        </a-collapse-panel>
      </a-collapse>
    </a-card>
    </a-card>

  </div>
</template>

<script setup>
import { getCurrentLocale, translateLegacy as phrase, translateText as text } from '../i18n'
import { localizeApiError } from '../i18n/errors'

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'

import { debugMcpUpstream, listMcpGateways, listMcpServers } from '../api'
import { copyText, promptManualCopy } from '../utils/clipboard'
import { validateServiceEndpoint } from '../utils/serviceEndpoint'
import { createConnectionAttempt, formatDebugDuration, localizeDebugResponse, validConnectionTimeout } from '../utils/mcpDebug'

const { t } = useI18n()
const targetMode = ref('service')
const servers = ref([])
const gateways = ref([])
const serverId = ref()
const serviceEndpoint = ref('')
const endpointInput = ref(null)
const endpointError = ref('')
const authorizationHeader = ref('Authorization')
const authorizationValue = ref('')
const timeoutSeconds = ref(30)
const gatewaySlug = ref()
const gatewayToken = ref('')
const gatewayTokenInput = ref(null)
const gatewayTokenChecked = ref(false)
// 在构造HTTP Header前校验原始凭证，保留非法草稿且不回显敏感值。
const gatewayTokenError = computed(() => {
  if (!gatewayTokenChecked.value) return ''
  if (!gatewayToken.value) return 'mcpDebug.gatewayCredentialRequired'
  return /^[\x21-\x7e]+$/u.test(gatewayToken.value) ? '' : 'mcpDebug.gatewayCredentialInvalid'
})
const gatewayEndpoint = ref('')
const gatewayTimeoutSeconds = ref(30)
const gatewayTimeoutInput = ref(null)
const gatewayTimeoutChecked = ref(false)
const gatewayTimeoutError = computed(() => gatewayTimeoutChecked.value && !validConnectionTimeout(gatewayTimeoutSeconds.value))
let connectionAttempt = null
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
const connectionLabel = computed(() => connected.value
  ? text(
    `已连接${protocolVersion.value ? ` · ${protocolVersion.value}` : ''}`,
    `Connected${protocolVersion.value ? ` · ${protocolVersion.value}` : ''}`,
  )
  : phrase('legacy.1x8ir3o'))
const serviceSecretHint = computed(() => {
  if (!selectedServer.value) return phrase('legacy.1k1jpui')
  return serviceEndpoint.value === selectedServer.value.endpoint
    ? phrase('legacy.vizdqe')
    : phrase('legacy.1jwdrvc')
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
  // 配置变化后取消旧连接，避免旧结果覆盖当前目标。
  connectionAttempt?.cancel()
  connectionAttempt = null
  connecting.value = false
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

const gatewayRequest = async (method, params = {}, notification = false, attempt) => {
  const requestId = notification ? undefined : ++requestSequence
  const payload = { jsonrpc: '2.0', ...(requestId === undefined ? {} : { id: requestId }), method, params }
  const started = performance.now()
  let responseData
  let ok = false
  try {
    const response = await fetch(gatewayEndpoint.value.trim(), {
      signal: attempt?.signal,
      method: 'POST',
      headers: {
        Authorization: `Bearer ${gatewayToken.value.trim()}`,
        Accept: 'application/json, text/event-stream',
        'Content-Type': 'application/json',
        'MCP-Protocol-Version': protocolVersion.value || '2025-11-25',
        'Accept-Language': getCurrentLocale(),
      },
      body: JSON.stringify(payload),
    })
    const text = await response.text()
    responseData = text ? JSON.parse(text) : null
    if (!response.ok) throw new Error(responseData?.detail || `HTTP ${response.status}`)
    if (responseData?.error) {
      const { message, data } = responseData.error
      // 按稳定编码显示当前语言，历史中的原始响应保持不变。
      throw new Error(localizeApiError({
        code: data?.error_code, params: data?.error_params, message,
      }, getCurrentLocale()))
    }
    ok = true
    return responseData
  } catch (error) {
    const reason = error?.message || String(error)
    // 浏览器错误采用统一响应字段，原始异常与本次超时保存在参数中。
    if (attempt?.signal.aborted && attempt.signal.reason === 'timeout') {
      responseData = { error_code: 'mcp.debug.connection_timeout', error_params: { reason, timeout_seconds: attempt.seconds } }
    } else if (error instanceof TypeError) {
      responseData = { error_code: 'mcp.debug.network_failed', error_params: { reason } }
    } else {
      responseData ||= { error: reason }
      throw error
    }
    throw new Error(localizeDebugResponse(responseData, t).detail)
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
  if (targetMode.value === 'service') {
    endpointError.value = validateServiceEndpoint(serviceEndpoint.value)
    if (endpointError.value) {
      endpointInput.value?.focus()
      return
    }
  }
  if (targetMode.value === 'gateway') {
    gatewayTokenChecked.value = true
    if (gatewayTokenError.value) {
      gatewayTokenInput.value?.focus()
      return
    }
    gatewayTimeoutChecked.value = true
    if (gatewayTimeoutError.value) {
      gatewayTimeoutInput.value?.focus()
      return
    }
    if (!gatewaySlug.value || !gatewayEndpoint.value.trim()) return message.warning(phrase('legacy.1wfq6rv'))
  }
  resetConnection()
  const isGateway = targetMode.value === 'gateway'
  // 初始化、通知与发现共用一次预算，Tool 调用保持独立。
  const attempt = createConnectionAttempt(isGateway ? gatewayTimeoutSeconds.value : undefined)
  connectionAttempt = attempt
  connecting.value = true
  try {
    if (isGateway) {
      const initialized = await gatewayRequest('initialize', {
        protocolVersion: '2025-11-25',
        capabilities: {},
        clientInfo: { name: 'agent-manager-debugger', version: '0.1.0' },
      }, false, attempt)
      attempt.signal.throwIfAborted()
      protocolVersion.value = initialized?.result?.protocolVersion || '2025-11-25'
      await gatewayRequest('notifications/initialized', {}, true, attempt)
      attempt.signal.throwIfAborted()
    }
    const listed = isGateway
      ? await gatewayRequest('tools/list', {}, false, attempt)
      : await serviceRequest('tools/list')
    if (connectionAttempt !== attempt) return
    attempt.signal.throwIfAborted()
    tools.value = listed?.result?.tools || []
    selectedToolName.value = tools.value[0]?.name
    connected.value = true
    message.success(text(
      `连接成功，发现 ${tools.value.length} 个 Tool`,
      `Connected. Discovered ${tools.value.length} Tools.`,
    ))
  } catch (error) {
    if (connectionAttempt === attempt) {
      message.error(error.response?.data?.detail || error.message || phrase('legacy.1pcchg2'))
    }
  } finally {
    attempt.dispose()
    if (connectionAttempt === attempt) {
      connectionAttempt = null
      connecting.value = false
    }
  }
}

const ping = async () => {
  if (pinging.value) return
  pinging.value = true
  try { await request('ping'); message.success(phrase('legacy.16a3m56')) }
  catch (error) { message.error(error.response?.data?.detail || error.message || phrase('legacy.z5zf9t')) }
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
        if (field.required) {
          throw new Error(text(
            `请填写必填参数：${field.schema.title || field.name}`,
            `Enter the required argument: ${field.schema.title || field.name}`,
          ))
        }
        continue
      }
      if (field.kind === 'complex') value = JSON.parse(value)
      if (field.kind === 'array') {
        const itemType = field.schema.items?.type
        value = value.map(item => itemType === 'string' ? item : Number(item))
        if (itemType !== 'string' && value.some(Number.isNaN)) {
          throw new Error(text(
            `${field.name} 包含无效数字`,
            `${field.name} contains an invalid number`,
          ))
        }
      }
      args[field.name] = value
    }
  } catch (error) {
    return message.warning(error instanceof SyntaxError ? phrase('legacy.uw6e11') : error.message)
  }
  calling.value = true
  try {
    callResult.value = await request('tools/call', { name: selectedTool.value.name, arguments: args })
    message.success(phrase('legacy.bjv336'))
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || phrase('legacy.1jj1f5k'))
  } finally {
    calling.value = false
  }
}

const copyClientConfig = async () => {
  const name = targetMode.value === 'service' ? (selectedServer.value?.slug || 'mcp-server') : gatewaySlug.value
  const url = targetMode.value === 'service' ? serviceEndpoint.value.trim() : gatewayEndpoint.value
  if (!name || !url) return message.warning(phrase('legacy.13u3i1k'))
  const config = { mcpServers: { [name]: { type: 'streamable-http', url } } }
  if (targetMode.value === 'gateway') config.mcpServers[name].headers = { Authorization: 'Bearer amat_xxx' }
  else if (authorizationValue.value || selectedServer.value) config.mcpServers[name].headers = { [authorizationHeader.value || 'Authorization']: '<secret>' }
  const configText = pretty(config)
  try {
    await copyText(configText)
    message.success(phrase('legacy.ihss14'))
  } catch {
    message.warning(t('clipboard.copyFailed'))
    promptManualCopy(configText, t('clipboard.manualCopyPrompt'))
  }
}

onUnmounted(resetConnection)

onMounted(async () => {
  try {
    const [serverRows, gatewayRows] = await Promise.all([listMcpServers(), listMcpGateways()])
    servers.value = serverRows || []
    gateways.value = gatewayRows || []
    gatewaySlug.value = activeGateways.value[0]?.slug
    loadGateway()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1qi24x1'))
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
