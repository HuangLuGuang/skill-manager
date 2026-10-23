<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="pageTitle" :sub-title="pageSubtitle">
          <template #extra>
            <a-button :loading="loading" @click="fetchAll">{{ text('刷新', 'Refresh') }}</a-button>
            <a-button v-if="activePage === 'servers' && hasAccess('mcp:create')" type="primary" @click="openServer()">{{ $t("legacy.1enmtj9") }}</a-button>
            <a-button v-if="activePage === 'gateways' && hasAccess('mcp:create')" type="primary" @click="openGateway()">{{ $t("legacy.1cl5f6n") }}</a-button>
          </template>
        </a-page-header>
      </template>

    <template v-if="activePage === 'servers'">
        <section>

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
                    <a-button v-if="hasAccess('mcp:update')" type="link" size="small" @click="openToolPolicy(tool)">{{ tool.name }}</a-button>
                    <span> · {{ $t(`mcpSecurity.accessModes.${tool.access_mode || 'unknown'}`) }}</span>
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
                  <a-button v-if="hasAccess('mcp:execute')" type="link" :loading="actionId === `discover-${record.id}`" @click="discover(record)">{{ $t("legacy.vtu19j") }}</a-button>
                  <a-button v-if="hasAccess('mcp:update')" type="link" @click="openServer(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  <a-popconfirm v-if="hasAccess('mcp:delete')" :title="$t('legacy.1ggc2d8')" @confirm="removeServer(record)">
                    <a-button type="link" danger :loading="actionId === `server-${record.id}`">{{ $t("legacy.1t2vi4h") }}</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </section>
    </template>

    <template v-else-if="activePage === 'gateways'">
        <section>

          <a-table :data-source="gateways" :columns="gatewayColumns" row-key="id" :loading="loading" size="small" :scroll="{ x: 980 }">
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
              <template v-else-if="column.key === 'boundary'">
                <a-tag :color="record.environment === 'production' ? 'red' : 'blue'">{{ $t(`mcpSecurity.environments.${record.environment || 'test'}`) }}</a-tag>
                <div class="muted">{{ $t(`mcpSecurity.executionModes.${record.execution_mode || 'active_safe'}`) }}</div>
                <div v-if="record.environment === 'production'" class="muted">{{ $t('mcpSecurity.denylistCount', { value: record.production_tool_denylist?.length || 0 }) }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : 'default'">{{ statusLabel(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-space>
                  <a-button type="link" @click="copy(`${origin}/mcp/${record.slug}`)">{{ $t("legacy.1vnyd7u") }}</a-button>
                  <a-button v-if="hasAccess('mcp:update')" type="link" @click="openGateway(record)">{{ $t("legacy.qreyeg") }}</a-button>
                  <a-popconfirm v-if="hasAccess('mcp:delete')" :title="$t('legacy.j29c29')" @confirm="removeGateway(record)">
                    <a-button type="link" danger :loading="actionId === `gateway-${record.id}`">{{ $t("legacy.1t2vi4h") }}</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </section>
    </template>

    <template v-else>
        <section>

          <!-- 使用默认条数，让表格保留用户选择的每页数量。 -->
          <a-table :data-source="auditRows" :columns="auditColumns" row-key="id" :loading="loading" size="small" :pagination="{ defaultPageSize: 20 }">
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
        </section>
    </template>

    </a-card>

    <a-modal v-model:open="serverVisible" :title="editingServerId ? $t('legacy.irabzr') : $t('legacy.1enmtj9')" width="760px" :confirm-loading="submitting" :ok-button-props="{ disabled: submitting || serverTesting }" @ok="saveServer">
      <a-form layout="vertical" :model="serverForm">
        <a-row :gutter="16">
          <a-col :xs="24" :md="12"><a-form-item :validate-status="serverError('name') ? 'error' : undefined" :help="serverError('name')" required><template #label><span>{{ $t('mcpServerForm.fields.name') }}</span><a-tooltip :title="$t('mcpServerForm.help.name')"><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpServerForm.help.name')" style="margin-left: 6px" /></a-tooltip></template><a-input v-model:value="serverForm.name" @update:value="touchServerField('name')" /></a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item :validate-status="serverError('slug') ? 'error' : undefined" :help="serverError('slug')" required><template #label><span>{{ $t('mcpServerForm.fields.slug') }}</span><a-tooltip :title="$t('mcpServerForm.help.slug')"><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpServerForm.help.slug')" style="margin-left: 6px" /></a-tooltip></template><a-input v-model:value="serverForm.slug" @update:value="touchServerField('slug')" :disabled="Boolean(editingServerId)" :placeholder="$t('legacy.a0rp53')" /></a-form-item></a-col>
        </a-row>
        <a-form-item :validate-status="serverError('endpoint') ? 'error' : undefined" :help="serverError('endpoint')" required><template #label><span>{{ $t('mcpServerForm.fields.endpoint') }}</span><a-tooltip :title="endpointHelp"><QuestionCircleOutlined tabindex="0" :aria-label="endpointHelp" style="margin-left: 6px" /></a-tooltip></template>
          <a-input v-model:value="serverForm.endpoint" @update:value="touchServerField('endpoint')" placeholder="https://mcp.example.com/mcp" />
          <a-space wrap style="margin-top: 8px">
            <a-button :loading="serverTesting" :disabled="serverTesting || submitting" @click="testServerForm">{{ $t("legacy.17pa11i") }}</a-button>
            <template v-if="serverTestTools">
              <a-tag color="green">{{ $t("legacy.13x3opo") }} {{ serverTestTools.length }} {{ $t("legacy.18nntpt") }}</a-tag>
              <a-tag v-for="name in serverTestTools.slice(0, 8)" :key="name">{{ name }}</a-tag>
              <span v-if="serverTestTools.length > 8" class="muted">{{ $t("legacy.1lfcp9m") }} {{ serverTestTools.length - 8 }} {{ $t("legacy.d5a1x9") }}</span>
            </template>
          </a-space>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12"><a-form-item :validate-status="serverError('authorization_header') ? 'error' : undefined" :help="serverError('authorization_header')" required><template #label><span>{{ $t('mcpServerForm.fields.authorization_header') }}</span><a-tooltip :title="$t('mcpServerForm.help.authorization_header')"><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpServerForm.help.authorization_header')" style="margin-left: 6px" /></a-tooltip></template><a-input v-model:value="serverForm.authorization_header" @update:value="touchServerField('authorization_header')" /></a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item :validate-status="serverError('authorization_value') ? 'error' : undefined" :help="serverError('authorization_value')"><template #label><span>{{ editingServerId ? $t('mcpServerForm.editValue') : $t('mcpServerForm.fields.authorization_value') }}</span><a-tooltip :title="$t('mcpServerForm.help.authorization_value')"><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpServerForm.help.authorization_value')" style="margin-left: 6px" /></a-tooltip></template><a-input-password v-model:value="serverForm.authorization_value" @update:value="touchServerField('authorization_value')" :placeholder="$t('legacy.1479ky1')" /></a-form-item></a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12"><a-form-item :validate-status="serverError('status') ? 'error' : undefined" :help="serverError('status')"><template #label><span>{{ $t('mcpServerForm.fields.status') }}</span></template><a-select v-model:value="serverForm.status" @update:value="touchServerField('status')"><a-select-option value="draft">{{ $t("legacy.oc54qp") }}</a-select-option><a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option><a-select-option value="disabled">{{ $t("legacy.6q9o5l") }}</a-select-option></a-select></a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item :validate-status="serverError('timeout_seconds') ? 'error' : undefined" :help="serverError('timeout_seconds')" required><template #label><span>{{ $t('mcpServerForm.fields.timeout_seconds') }}</span><a-tooltip :title="$t('mcpServerForm.help.timeout_seconds')"><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpServerForm.help.timeout_seconds')" style="margin-left: 6px" /></a-tooltip></template><a-input-number :value="serverForm.timeout_seconds" :min="1" :max="300" :step="1" :formatter="() => String(serverForm.timeout_seconds ?? '')" @input="setServerNumber('timeout_seconds', $event)" @step="(_, info) => stepServerNumber('timeout_seconds', info.type === 'up' ? 1 : -1)" style="width: 100%" /></a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item :validate-status="serverError('max_response_kb') ? 'error' : undefined" :help="serverError('max_response_kb')" required><template #label><span>{{ $t('mcpServerForm.fields.max_response_kb') }}</span><a-tooltip :title="$t('mcpServerForm.help.max_response_kb')"><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpServerForm.help.max_response_kb')" style="margin-left: 6px" /></a-tooltip></template><a-input-number :value="serverForm.max_response_kb" :min="1" :max="10240" :step="1" :formatter="() => String(serverForm.max_response_kb ?? '')" @input="setServerNumber('max_response_kb', $event)" @step="(_, info) => stepServerNumber('max_response_kb', info.type === 'up' ? 1 : -1)" style="width: 100%" /></a-form-item></a-col>
        </a-row>
        <a-form-item :validate-status="serverError('description') ? 'error' : undefined" :help="serverError('description')"><template #label><span>{{ $t('mcpServerForm.fields.description') }}</span><a-tooltip :title="$t('mcpServerForm.help.description')"><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpServerForm.help.description')" style="margin-left: 6px" /></a-tooltip></template><a-textarea v-model:value="serverForm.description" @update:value="touchServerField('description')" :rows="3" /></a-form-item>
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
        <a-form-item :label="$t('mcpSecurity.accessMode')" :extra="$t('mcpSecurity.accessModeHelp')">
          <a-select v-model:value="toolPolicyForm.access_mode">
            <a-select-option v-for="mode in ['unknown', 'read', 'write', 'destructive']" :key="mode" :value="mode">{{ $t(`mcpSecurity.accessModes.${mode}`) }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :span="12"><a-form-item :label="$t('mcpSecurity.callsPerMinute')"><a-input-number v-model:value="toolPolicyForm.rate_limit_per_minute" :min="1" :max="10000" style="width: 100%" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item :label="$t('mcpSecurity.maximumConcurrency')"><a-input-number v-model:value="toolPolicyForm.max_concurrent" :min="1" :max="100" style="width: 100%" /></a-form-item></a-col>
        </a-row>
        <a-form-item :label="$t('mcpSecurity.preExecutionApproval')"><a-switch v-model:checked="toolPolicyForm.requires_approval" :disabled="toolPolicyForm.risk_level === 'high' || toolPolicyForm.access_mode === 'destructive'" /></a-form-item>
        <a-alert v-if="toolPolicyForm.risk_level === 'high' || toolPolicyForm.access_mode === 'destructive'" type="warning" show-icon :message="toolPolicyForm.access_mode === 'destructive' ? $t('mcpSecurity.destructiveApprovalHint') : $t('mcpSecurity.highRiskHint')" />
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
        <a-row :gutter="16">
          <a-col :xs="24" :md="12"><a-form-item required>
            <template #label><span>{{ $t('mcpSecurity.environment') }}</span><a-tooltip><template #title><div style="white-space: pre-line">{{ $t('mcpSecurity.environmentHelp') }}</div></template><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpSecurity.environmentHelp')" style="margin-left: 6px" /></a-tooltip></template>
            <a-select v-model:value="gatewayForm.environment" @change="handleGatewayEnvironmentChange"><a-select-option v-for="value in ['sandbox', 'test', 'staging', 'production']" :key="value" :value="value">{{ $t(`mcpSecurity.environments.${value}`) }}</a-select-option></a-select>
          </a-form-item></a-col>
          <a-col :xs="24" :md="12"><a-form-item required>
            <template #label><span>{{ $t('mcpSecurity.executionMode') }}</span><a-tooltip><template #title><div style="white-space: pre-line">{{ $t('mcpSecurity.executionModeHelp') }}</div></template><QuestionCircleOutlined tabindex="0" :aria-label="$t('mcpSecurity.executionModeHelp')" style="margin-left: 6px" /></a-tooltip></template>
            <a-select v-model:value="gatewayForm.execution_mode"><a-select-option v-for="value in ['passive', 'read_only', 'active_safe', 'active_full']" :key="value" :value="value" :disabled="gatewayForm.environment === 'production' && value === 'active_full'">{{ $t(`mcpSecurity.executionModes.${value}`) }}</a-select-option></a-select>
          </a-form-item></a-col>
        </a-row>
        <a-alert class="policy-alert" type="info" show-icon :message="$t('mcpSecurity.executionBoundaryHelp')" />
        <a-form-item v-if="gatewayForm.environment === 'production'" :label="$t('mcpSecurity.productionDenylist')" :extra="$t('mcpSecurity.productionDenylistHelp')">
          <a-select v-model:value="gatewayForm.production_tool_denylist" mode="multiple" show-search option-filter-prop="label">
            <a-select-option v-for="tool in selectedGatewayToolOptions" :key="tool.exposed_name" :value="tool.exposed_name" :label="`${tool.name} ${tool.exposed_name}`">{{ tool.name }} · {{ tool.exposed_name }} · {{ $t(`mcpSecurity.accessModes.${tool.access_mode || 'unknown'}`) }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="$t('legacy.1ccx4t4')"><a-select v-model:value="gatewayForm.status"><a-select-option value="active">{{ $t("legacy.5pm2ma") }}</a-select-option><a-select-option value="disabled">{{ $t("legacy.6q9o5l") }}</a-select-option></a-select></a-form-item>
        <a-form-item :label="$t('legacy.1kxyax6')"><a-textarea v-model:value="gatewayForm.description" :rows="3" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { can as hasAccess } from '../access'
import { translateLegacy as phrase } from '../i18n'

import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'
import { mcpServerErrors, serverFields, testFields, serverPayload } from '../utils/mcpServerForm'
import { formatMcpFieldError } from '../i18n/mcpServerForm'
import { stepInteger } from '../utils/advancedConfig'

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
  getMcpServerOptions,
  updateMcpGateway,
  updateMcpServer,
  updateMcpToolPolicy,
} from '../api'
import { useLocaleText } from '../i18n/useLocaleText'
import { copyText, promptManualCopy } from '../utils/clipboard'
import { formatDateTime } from '../utils/format'

const route = useRoute()
const { t, locale } = useI18n()
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
const initialServerValues = ref({})
const checkedServerFields = ref([])
const serverAllowHttp = ref(null)
const endpointHelp = computed(() => serverAllowHttp.value === null
  ? t('mcpServerForm.help.endpointLoading')
  : t('mcpServerForm.help.endpoint', { protocols: serverAllowHttp.value ? 'HTTP/HTTPS' : 'HTTPS' }))
// 首次用户输入才启用即时错误，初始化回填不触发必填提示。
const touchServerField = field => {
  if (!checkedServerFields.value.includes(field)) checkedServerFields.value.push(field)
}
const remoteServerErrors = ref({})
const remoteServerValues = ref({})
const serverIssues = computed(() => mcpServerErrors(serverForm, { allowHttp: serverAllowHttp.value }))
const serverError = field => {
  const issue = checkedServerFields.value.includes(field) && serverIssues.value[field]
    || (remoteServerValues.value[field] === serverForm[field] && remoteServerErrors.value[field])
  return issue ? formatMcpFieldError(issue, locale.value) : ''
}
const validateServerForm = fields => {
  checkedServerFields.value = [...new Set([...checkedServerFields.value, ...fields])]
  return !fields.some(field => serverIssues.value[field])
}
const captureServerErrors = error => {
  const issues = error.response?.data?.error_code === 'mcp.server.invalid_fields'
    ? error.response.data.error_params?.errors || [] : []
  remoteServerErrors.value = Object.fromEntries(issues.map(issue => [issue.field, issue]))
  remoteServerValues.value = { ...serverForm }
}
// 保留原数字框箭头样式；formatter显示原始草稿，避免失焦时自动夹取。
const setServerNumber = (field, value) => {
  serverForm[field] = value
  touchServerField(field)
}
const stepServerNumber = (field, delta) => {
  touchServerField(field)
  serverForm[field] = stepInteger(serverForm[field], delta, 1, field === 'timeout_seconds' ? 300 : 10240)
}
const gatewayForm = reactive({ slug: '', name: '', description: '', environment: 'test', execution_mode: 'active_safe', production_tool_denylist: [], status: 'active', tools: [] })
const toolPolicyForm = reactive({ id: null, access_mode: 'unknown', risk_level: 'low', rate_limit_per_minute: 60, max_concurrent: 5, requires_approval: false })

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
  { title: t('mcpSecurity.executionBoundary'), key: 'boundary', width: 180 },
  { title: text('状态', 'Status'), key: 'status', width: 90 },
  { title: text('操作', 'Actions'), key: 'actions', width: 210 },
])
const auditColumns = computed(() => [
  { title: text('请求 ID', 'Request ID'), dataIndex: 'request_id', width: 260 },
  { title: text('调用目标', 'Call Target'), key: 'target' },
  { title: 'Token ID', dataIndex: 'token_id', width: 100 },
  { title: text('耗时 ms', 'Duration (ms)'), dataIndex: 'duration_ms', width: 100 },
  { title: text('状态', 'Status'), key: 'status', width: 90 },
  { title: text('时间', 'Time'), key: 'time', width: 190 },
])

const activeServers = computed(() => servers.value.filter(item => item.status === 'active'))
const enabledTools = server => (server.tools || []).filter(tool => tool.enabled)
const selectedGatewayToolOptions = computed(() => gatewayForm.tools.map(value => {
  const separator = value.indexOf(':')
  const server = servers.value.find(item => item.id === Number(value.slice(0, separator)))
  return server?.tools?.find(tool => tool.name === value.slice(separator + 1))
}).filter(Boolean))
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
const formatTime = formatDateTime
const gatewayToolNames = gateway => (gateway.bindings || []).flatMap(binding => binding.allowed_tools.map(name => `${binding.server_slug}__${name}`))

let listSequence = 0
const fetchAll = async () => {
  const sequence = ++listSequence
  const page = activePage.value
  loading.value = true
  try {
    const rows = await (page === 'servers' ? listMcpServers() : page === 'gateways' ? listMcpGateways() : listMcpAudit({ limit: 200 }))
    if (sequence !== listSequence) return
    if (page === 'servers') servers.value = rows || []
    else if (page === 'gateways') gateways.value = rows || []
    else auditRows.value = rows || []
  } catch (error) {
    if (sequence !== listSequence) return
    message.error(error.response?.data?.detail || phrase('legacy.1qi24x1'))
  } finally {
    if (sequence === listSequence) loading.value = false
  }
}

let serverOptionsPending = false
const openServer = async record => {
  if (serverOptionsPending) return
  editingServerId.value = record?.id || null
  Object.assign(serverForm, {
    slug: record?.slug || '', name: record?.name || '', description: record?.description || '', endpoint: record?.endpoint || '',
    authorization_header: record?.authorization_header || 'Authorization', authorization_value: '', status: record?.status || 'draft', timeout_seconds: record?.timeout_seconds || 30,
    max_response_kb: record?.max_response_kb || 1024,
  })
  initialServerValues.value = { ...serverForm }
  serverTestTools.value = null
  checkedServerFields.value = []
  remoteServerErrors.value = {}
  remoteServerValues.value = {}
  serverVisible.value = true
  serverAllowHttp.value = null
  serverOptionsPending = true
  try { serverAllowHttp.value = (await getMcpServerOptions()).allow_http }
  catch (error) { message.error(error.response?.data?.detail || phrase('legacy.1qi24x1')) }
  finally { serverOptionsPending = false }
}

const testServerForm = async () => {
  if (serverTesting.value || submitting.value) return
  if (!validateServerForm(testFields)) return
  serverTesting.value = true
  serverTestTools.value = null
  try {
    const payload = {
      server_id: editingServerId.value || undefined,
      endpoint: serverForm.endpoint.trim(),
      authorization_header: serverForm.authorization_header || 'Authorization',
      authorization_value: serverForm.authorization_value || undefined,
      timeout_seconds: Number(serverForm.timeout_seconds),
      method: 'tools/list',
      params: {},
    }
    const result = await debugMcpUpstream(payload)
    if (result.response?.error) throw new Error(result.response.error.message)
    serverTestTools.value = (result.response?.result?.tools || []).map(tool => tool.name)
    message.success(phrase('legacy.1e1auoj'))
  } catch (error) {
    captureServerErrors(error)
    message.error(error.response?.data?.detail || error.message || phrase('legacy.6c3q70'))
  } finally {
    serverTesting.value = false
  }
}

const saveServer = async () => {
  if (submitting.value || serverTesting.value) return
  // 先按原始草稿校验变更字段，避免数值转换掩盖非法输入。
  const fields = editingServerId.value
    ? serverFields.filter(field => serverForm[field] !== initialServerValues.value[field]) : serverFields
  if (!validateServerForm(fields)) return
  const current = serverPayload(serverForm)
  submitting.value = true
  try {
    const payload = Object.fromEntries(fields.map(field => [field, current[field]]))
    if (editingServerId.value && !payload.authorization_value) delete payload.authorization_value
    if (editingServerId.value) await updateMcpServer(editingServerId.value, payload)
    else await createMcpServer(payload)
    serverVisible.value = false
    await fetchAll()
    message.success(phrase('legacy.wf80o5'))
  } catch (error) {
    captureServerErrors(error)
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
    message.success(phrase('legacy.1r5dof'))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.8ufi7f'))
  } finally {
    // 发现失败也会更新服务端健康状态，完成后统一刷新。
    await fetchAll()
    actionId.value = null
  }
}

const openToolPolicy = tool => {
  Object.assign(toolPolicyForm, {
    id: tool.id,
    access_mode: tool.access_mode || 'unknown',
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
      access_mode: toolPolicyForm.access_mode,
      risk_level: toolPolicyForm.risk_level,
      rate_limit_per_minute: toolPolicyForm.rate_limit_per_minute,
      max_concurrent: toolPolicyForm.max_concurrent,
      requires_approval: toolPolicyForm.risk_level === 'high' || toolPolicyForm.access_mode === 'destructive' || toolPolicyForm.requires_approval,
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

let gatewayOptionsPending = false
const openGateway = async record => {
  if (gatewayOptionsPending) return
  gatewayOptionsPending = true
  try { servers.value = await listMcpServers() || [] }
  catch (error) { message.error(error.response?.data?.detail || phrase('legacy.1qi24x1')); return }
  finally { gatewayOptionsPending = false }
  if (activePage.value !== 'gateways') return
  editingGatewayId.value = record?.id || null
  Object.assign(gatewayForm, {
    slug: record?.slug || '', name: record?.name || '', description: record?.description || '', environment: record?.environment || 'test', execution_mode: record?.execution_mode || 'active_safe', production_tool_denylist: [...(record?.production_tool_denylist || [])], status: record?.status || 'active',
    tools: (record?.bindings || []).flatMap(binding => binding.allowed_tools.map(name => toolKey(binding.server_id, name))),
  })
  gatewayVisible.value = true
}
const handleGatewayEnvironmentChange = environment => { if (environment === 'production' && gatewayForm.execution_mode === 'active_full') gatewayForm.execution_mode = 'active_safe' }

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
    const payload = { slug: gatewayForm.slug.trim(), name: gatewayForm.name.trim(), description: gatewayForm.description, environment: gatewayForm.environment, execution_mode: gatewayForm.execution_mode, production_tool_denylist: [...gatewayForm.production_tool_denylist], status: gatewayForm.status, bindings: gatewayBindings() }
    if (editingGatewayId.value) await updateMcpGateway(editingGatewayId.value, payload)
    else await createMcpGateway(payload)
    gatewayVisible.value = false
    await fetchAll()
    message.success(phrase('legacy.1tvic29'))
  } catch (error) {
    captureServerErrors(error)
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

const copy = async value => {
  try {
    await copyText(value)
    message.success(phrase('legacy.11bea7m'))
  } catch {
    message.warning(t('clipboard.copyFailed'))
    promptManualCopy(value, t('clipboard.manualCopyPrompt'))
  }
}
watch(activePage, () => {
  serverVisible.value = false
  gatewayVisible.value = false
  toolPolicyVisible.value = false
  fetchAll()
}, { immediate: true })
onUnmounted(() => { listSequence++ })
watch(() => [...gatewayForm.tools], () => {
  const selected = new Set(selectedGatewayToolOptions.value.map(tool => tool.exposed_name))
  gatewayForm.production_tool_denylist = gatewayForm.production_tool_denylist.filter(name => selected.has(name))
})
</script>

<style scoped>
.title { font-weight: 600; }
.muted { color: #8c8c8c; font-size: 12px; word-break: break-all; }
.policy-alert { margin-bottom: 16px; }
</style>
