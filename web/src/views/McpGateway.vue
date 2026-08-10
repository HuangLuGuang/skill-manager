<template>
  <div>
    <a-page-header :title="pageTitle" :sub-title="pageSubtitle" />

    <template v-if="activePage === 'servers'">
        <a-card>
          <template #extra>
            <a-space>
              <a-button :loading="loading" @click="fetchAll">{{ text('刷新', 'Refresh') }}</a-button>
              <a-button type="primary" @click="openServer()">{{ $t("legacy.1enmtj9") }}</a-button>
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
                  <a-tag v-for="tool in record.tools || []" :key="tool.id" :color="tool.risk_level === 'high' ? 'red' : tool.risk_level === 'medium' ? 'orange' : tool.enabled ? 'blue' : 'default'">
                    <a-button type="link" size="small" @click="openToolPolicy(tool)">{{ tool.name }}</a-button>
                    <span v-if="tool.requires_approval"> · {{ $t('mcpSecurity.approvalRequired') }}</span>
                  </a-tag>
                  <span v-if="!record.tools?.length" class="muted">{{ $t("legacy.1cqmmbo") }}</span>
                </a-space>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : record.status === 'draft' ? 'orange' : 'default'">
                  {{ statusLabel(record.status) }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" :loading="actionId === `discover-${record.id}`" @click="discover(record)">{{ $t("legacy.vtu19j") }}</a-button>
                  <a-button type="link" @click="openServer(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  <a-popconfirm :title="$t('legacy.1ggc2d8')" @confirm="removeServer(record)">
                    <a-button type="link" danger :loading="actionId === `server-${record.id}`">{{ $t("legacy.1t2vi4h") }}</a-button>
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
              <a-button :loading="loading" @click="fetchAll">{{ text('刷新', 'Refresh') }}</a-button>
              <a-button type="primary" @click="openGateway()">{{ $t("legacy.1cl5f6n") }}</a-button>
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
                  <span v-if="!gatewayToolNames(record).length" class="muted">{{ $t("legacy.1bmfz89") }}</span>
                </a-space>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : 'default'">{{ statusLabel(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" @click="copy(`${origin}/mcp/${record.slug}`)">{{ $t("legacy.1vnyd7u") }}</a-button>
                  <a-button type="link" @click="openGateway(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  <a-popconfirm :title="$t('legacy.j29c29')" @confirm="removeGateway(record)">
                    <a-button type="link" danger :loading="actionId === `gateway-${record.id}`">{{ $t("legacy.1t2vi4h") }}</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-card>
    </template>

    <template v-else>
        <a-card>
          <template #extra><a-button :loading="loading" @click="fetchAll">{{ text('刷新', 'Refresh') }}</a-button></template>
          <a-table :data-source="auditRows" :columns="auditColumns" row-key="id" :loading="loading" size="small" :pagination="{ pageSize: 20 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'target'">
                <div>{{ record.gateway_slug }} → {{ record.server_slug }}</div>
                <div class="muted">{{ record.tool_name }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'success' ? 'green' : 'red'">{{ record.status }}</a-tag>
              </template>
              <template v-else-if="column.key === 'skill'">
                <div>{{ record.skill_name || '-' }}</div>
                <div v-if="record.skill_version_id || record.skill_id" class="muted">{{ record.skill_version_id || record.skill_id }}</div>
              </template>
              <template v-else-if="column.key === 'skillTrust'">
                <template v-if="record.skill_trust_state">
                  <a-tag :color="skillTrustColor(record.skill_trust_state)">{{ skillTrustLabel(record.skill_trust_state) }}</a-tag>
                  <div v-if="record.skill_alert_codes?.length" class="muted">{{ skillAlertLabel(record.skill_alert_codes[0]) }}</div>
                </template>
                <span v-else>-</span>
              </template>
              <template v-else-if="column.key === 'time'">{{ formatTime(record.created_at) }}</template>
            </template>
          </a-table>
        </a-card>
    </template>

    <a-modal v-model:open="serverVisible" :title="editingServerId ? $t('legacy.irabzr') : $t('legacy.1enmtj9')" width="760px" :confirm-loading="submitting" @ok="saveServer">
      <a-form layout="vertical" :model="serverForm">
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="$t('legacy.hzx914')" required><a-input v-model:value="serverForm.name" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="$t('legacy.10w0qab')" required><a-input v-model:value="serverForm.slug" :disabled="Boolean(editingServerId)" :placeholder="$t('legacy.a0rp53')" /></a-form-item></a-col>
        </a-row>
        <a-form-item label="Streamable HTTP Endpoint" required>
          <a-input v-model:value="serverForm.endpoint" placeholder="https://mcp.example.com/mcp" />
          <a-space wrap style="margin-top: 8px">
            <a-button :loading="serverTesting" @click="testServerForm">{{ $t("legacy.17pa11i") }}</a-button>
            <template v-if="serverTestTools">
              <a-tag color="green">{{ $t("legacy.13x3opo") }} {{ serverTestTools.length }} {{ $t("legacy.18nntpt") }}</a-tag>
              <a-tag v-for="name in serverTestTools.slice(0, 8)" :key="name">{{ name }}</a-tag>
              <span v-if="serverTestTools.length > 8" class="muted">{{ $t("legacy.1lfcp9m") }} {{ serverTestTools.length - 8 }} {{ $t("legacy.d5a1x9") }}</span>
            </template>
          </a-space>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="$t('legacy.17s488l')"><a-input v-model:value="serverForm.authorization_header" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="editingServerId ? $t('legacy.d6ubyh') : $t('legacy.1iwkwic')"><a-input-password v-model:value="serverForm.authorization_value" :placeholder="$t('legacy.1479ky1')" /></a-form-item></a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="$t('legacy.1ccx4t4')"><a-select v-model:value="serverForm.status"><a-select-option value="draft">{{ $t("legacy.oc54qp") }}</a-select-option><a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option><a-select-option value="disabled">{{ $t("legacy.6q9o5l") }}</a-select-option></a-select></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="$t('legacy.tabbi8')"><a-input-number v-model:value="serverForm.timeout_seconds" :min="1" :max="300" style="width: 100%" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="$t('mcpSecurity.maximumResponseKb')"><a-input-number v-model:value="serverForm.max_response_kb" :min="1" :max="10240" style="width: 100%" /></a-form-item></a-col>
        </a-row>
        <a-form-item :label="$t('legacy.1kxyax6')"><a-textarea v-model:value="serverForm.description" :rows="3" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="toolPolicyVisible" :title="$t('mcpSecurity.title')" :confirm-loading="submitting" @ok="saveToolPolicy">
      <a-form layout="vertical" :model="toolPolicyForm">
        <a-form-item :label="$t('mcpSecurity.riskLevel')">
          <a-select v-model:value="toolPolicyForm.risk_level">
            <a-select-option value="low">{{ $t('mcpSecurity.low') }}</a-select-option>
            <a-select-option value="medium">{{ $t('mcpSecurity.medium') }}</a-select-option>
            <a-select-option value="high">{{ $t('mcpSecurity.high') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="$t('mcpSecurity.callsPerMinute')"><a-input-number v-model:value="toolPolicyForm.rate_limit_per_minute" :min="1" :max="10000" style="width: 100%" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="$t('mcpSecurity.maximumConcurrency')"><a-input-number v-model:value="toolPolicyForm.max_concurrent" :min="1" :max="100" style="width: 100%" /></a-form-item></a-col>
        </a-row>
        <a-form-item :label="$t('mcpSecurity.preExecutionApproval')"><a-switch v-model:checked="toolPolicyForm.requires_approval" :disabled="toolPolicyForm.risk_level === 'high'" /></a-form-item>
        <a-alert v-if="toolPolicyForm.risk_level === 'high'" type="warning" show-icon :message="$t('mcpSecurity.highRiskHint')" />
      </a-form>
    </a-modal>

    <a-modal v-model:open="gatewayVisible" :title="editingGatewayId ? $t('legacy.cwb4lh') : $t('legacy.1tnkzbx')" width="820px" :confirm-loading="submitting" @ok="saveGateway">
      <a-form layout="vertical" :model="gatewayForm">
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="$t('legacy.hzx914')" required><a-input v-model:value="gatewayForm.name" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="$t('legacy.10w0qab')" required><a-input v-model:value="gatewayForm.slug" :disabled="Boolean(editingGatewayId)" :placeholder="$t('legacy.dcntg6')" /></a-form-item></a-col>
        </a-row>
        <a-form-item :label="$t('legacy.1fxfunn')" required>
          <a-select v-model:value="gatewayForm.tools" mode="multiple" show-search option-filter-prop="label" :placeholder="$t('legacy.8qb692')">
            <a-select-opt-group v-for="server in activeServers" :key="server.id" :label="server.name">
              <a-select-option v-for="tool in enabledTools(server)" :key="toolKey(server.id, tool.name)" :value="toolKey(server.id, tool.name)" :label="`${server.name} ${tool.name}`">
                {{ tool.name }}{{ $t("legacy.1qdqea2") }}{{ tool.exposed_name }}）
              </a-select-option>
            </a-select-opt-group>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('legacy.1ccx4t4')"><a-select v-model:value="gatewayForm.status"><a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option><a-select-option value="disabled">{{ $t("legacy.6q9o5l") }}</a-select-option></a-select></a-form-item>
        <a-form-item :label="$t('legacy.1kxyax6')"><a-textarea v-model:value="gatewayForm.description" :rows="3" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
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
  updateMcpToolPolicy,
} from '../api'
import { useLocaleText } from '../i18n/useLocaleText'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const { t } = useI18n()
const { text } = useLocaleText()
const activePage = computed(() => route.meta.mcpTab || 'servers')
const pageTitle = computed(() => ({ servers: phrase('legacy.lnloo7'), gateways: phrase('legacy.1gcagoh'), audit: phrase('legacy.2pfrfc') }[activePage.value]))
const pageSubtitle = computed(() => ({
  servers: phrase('legacy.pi6v2j'),
  gateways: phrase('legacy.3q6zr7'),
  audit: phrase('legacy.1h856pr'),
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
const toolPolicyVisible = ref(false)
const editingServerId = ref(null)
const editingGatewayId = ref(null)
const origin = window.location.origin
const serverForm = reactive({ slug: '', name: '', description: '', endpoint: '', authorization_header: 'Authorization', authorization_value: '', status: 'draft', timeout_seconds: 30, max_response_kb: 1024 })
const gatewayForm = reactive({ slug: '', name: '', description: '', status: 'active', tools: [] })
const toolPolicyForm = reactive({ id: null, risk_level: 'low', rate_limit_per_minute: 60, max_concurrent: 5, requires_approval: false })

const serverColumns = computed(() => [
  { title: 'MCP Server', key: 'server' },
  { title: text('健康状态', 'Health'), key: 'health', width: 150 },
  { title: 'Tool', key: 'tools' },
  { title: text('状态', 'Status'), key: 'status', width: 90 },
  { title: text('操作', 'Actions'), key: 'actions', width: 260 },
])
const gatewayColumns = computed(() => [
  { title: text('虚拟网关', 'Virtual Gateway'), key: 'gateway', width: 260 },
  { title: text('发布能力', 'Published Capabilities'), key: 'tools' },
  { title: text('状态', 'Status'), key: 'status', width: 90 },
  { title: text('操作', 'Actions'), key: 'actions', width: 210 },
])
const auditColumns = computed(() => [
  { title: text('请求 ID', 'Request ID'), dataIndex: 'request_id', width: 260 },
  { title: text('调用目标', 'Call Target'), key: 'target' },
  { title: t('gatewaySkill.skill'), key: 'skill', width: 160 },
  { title: t('gatewaySkill.trustState'), key: 'skillTrust', width: 170 },
  { title: 'Token ID', dataIndex: 'token_id', width: 100 },
  { title: text('耗时 ms', 'Duration (ms)'), dataIndex: 'duration_ms', width: 100 },
  { title: text('状态', 'Status'), key: 'status', width: 90 },
  { title: text('时间', 'Time'), key: 'time', width: 190 },
])

const activeServers = computed(() => servers.value.filter(item => item.status === 'active'))
const enabledTools = server => (server.tools || []).filter(tool => tool.enabled)
const toolKey = (serverId, toolName) => `${serverId}:${toolName}`
const statusLabel = value => ({
  active: text('启用', 'Enabled'),
  disabled: text('停用', 'Disabled'),
  draft: text('草稿', 'Draft'),
}[value] || value)
const healthLabel = value => ({
  healthy: text('正常', 'Healthy'),
  unhealthy: text('异常', 'Unhealthy'),
  unknown: text('未检测', 'Not Checked'),
}[value] || value)
const healthColor = value => ({ healthy: 'green', unhealthy: 'red', unknown: 'default' }[value] || 'default')
const skillTrustLabel = value => ({
  missing: t('gatewaySkill.missing'),
  declared_trusted: t('gatewaySkill.declaredTrusted'),
  suspicious: t('gatewaySkill.suspicious'),
}[value] || value)
const skillTrustColor = value => ({ missing: 'default', declared_trusted: 'orange', suspicious: 'red' }[value] || 'default')
const skillAlertLabel = code => ({
  'gateway.skill_context_missing': t('gatewaySkill.contextMissing'),
  'gateway.skill_unknown': t('gatewaySkill.unknown'),
  'gateway.skill_id_mismatch': t('gatewaySkill.idMismatch'),
  'gateway.skill_name_mismatch': t('gatewaySkill.nameMismatch'),
  'gateway.skill_not_loadable': t('gatewaySkill.notLoadable'),
  'gateway.skill_not_allowed_for_agent': t('gatewaySkill.notAllowed'),
  'gateway.skill_context_unverified': t('gatewaySkill.unverified'),
}[code] || code)
const formatTime = formatDateTime
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
    message.error(error.response?.data?.detail || phrase('legacy.1qi24x1'))
  } finally {
    loading.value = false
  }
}

const openServer = record => {
  editingServerId.value = record?.id || null
  Object.assign(serverForm, {
    slug: record?.slug || '', name: record?.name || '', description: record?.description || '', endpoint: record?.endpoint || '',
    authorization_header: record?.authorization_header || 'Authorization', authorization_value: '', status: record?.status || 'draft', timeout_seconds: record?.timeout_seconds || 30,
    max_response_kb: record?.max_response_kb || 1024,
  })
  serverTestTools.value = null
  serverVisible.value = true
}

const testServerForm = async () => {
  if (serverTesting.value) return
  if (!serverForm.endpoint.trim()) return message.warning(phrase('legacy.1jvoy6r'))
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
    message.success(phrase('legacy.1e1auoj'))
  } catch (error) {
    message.error(error.response?.data?.detail || error.message || phrase('legacy.6c3q70'))
  } finally {
    serverTesting.value = false
  }
}

const saveServer = async () => {
  if (submitting.value) return
  if (!serverForm.name.trim() || !serverForm.slug.trim() || !serverForm.endpoint.trim()) return message.warning(phrase('legacy.g0i7ay'))
  submitting.value = true
  try {
    const payload = { ...serverForm, name: serverForm.name.trim(), slug: serverForm.slug.trim(), endpoint: serverForm.endpoint.trim() }
    if (editingServerId.value && !payload.authorization_value) delete payload.authorization_value
    if (editingServerId.value) await updateMcpServer(editingServerId.value, payload)
    else await createMcpServer(payload)
    serverVisible.value = false
    await fetchAll()
    message.success(phrase('legacy.wf80o5'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1q9u8le'))
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
    message.success(phrase('legacy.1r5dof'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.8ufi7f'))
  } finally {
    actionId.value = null
  }
}

const openToolPolicy = tool => {
  Object.assign(toolPolicyForm, {
    id: tool.id,
    risk_level: tool.risk_level || 'low',
    rate_limit_per_minute: tool.rate_limit_per_minute || 60,
    max_concurrent: tool.max_concurrent || 5,
    requires_approval: Boolean(tool.requires_approval),
  })
  toolPolicyVisible.value = true
}

const saveToolPolicy = async () => {
  if (submitting.value || !toolPolicyForm.id) return
  submitting.value = true
  try {
    await updateMcpToolPolicy(toolPolicyForm.id, {
      risk_level: toolPolicyForm.risk_level,
      rate_limit_per_minute: toolPolicyForm.rate_limit_per_minute,
      max_concurrent: toolPolicyForm.max_concurrent,
      requires_approval: toolPolicyForm.risk_level === 'high' || toolPolicyForm.requires_approval,
    })
    toolPolicyVisible.value = false
    await fetchAll()
    message.success(t('mcpSecurity.updated'))
  } catch (error) {
    message.error(error.response?.data?.detail || t('mcpSecurity.updateFailed'))
  } finally {
    submitting.value = false
  }
}

const removeServer = async record => {
  if (actionId.value) return
  actionId.value = `server-${record.id}`
  try { await deleteMcpServer(record.id); await fetchAll(); message.success(phrase('legacy.1gyqcpd')) }
  catch (error) { message.error(error.response?.data?.detail || phrase('legacy.1ijrr73')) }
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
  if (!gatewayForm.name.trim() || !gatewayForm.slug.trim()) return message.warning(phrase('legacy.9ktg78'))
  if (!gatewayForm.tools.length) return message.warning(phrase('legacy.1m1vd36'))
  submitting.value = true
  try {
    const payload = { slug: gatewayForm.slug.trim(), name: gatewayForm.name.trim(), description: gatewayForm.description, status: gatewayForm.status, bindings: gatewayBindings() }
    if (editingGatewayId.value) await updateMcpGateway(editingGatewayId.value, payload)
    else await createMcpGateway(payload)
    gatewayVisible.value = false
    await fetchAll()
    message.success(phrase('legacy.1tvic29'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1q9u8le'))
  } finally {
    submitting.value = false
  }
}

const removeGateway = async record => {
  if (actionId.value) return
  actionId.value = `gateway-${record.id}`
  try { await deleteMcpGateway(record.id); await fetchAll(); message.success(phrase('legacy.1gyqcpd')) }
  catch (error) { message.error(error.response?.data?.detail || phrase('legacy.1ijrr73')) }
  finally { actionId.value = null }
}

const copy = async value => { await navigator.clipboard.writeText(value); message.success(phrase('legacy.11bea7m')) }
onMounted(fetchAll)
</script>

<style scoped>
.title { font-weight: 600; }
.muted { color: #8c8c8c; font-size: 12px; word-break: break-all; }
</style>
