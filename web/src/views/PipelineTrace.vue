<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.1ngfjb6')" :sub-title="$t('legacy.vpytmv')" />
      </template>

    <a-alert
      type="warning"
      show-icon
      :message="$t('legacy.1k6rkb4')"
      :description="$t('legacy.xnr5g4')"
    />

    <a-card :title="$t('legacy.1wwptsv')" style="margin-top: 16px">
      <template #extra>
        <a-button @click="refreshTraces" :loading="loading">{{ $t("legacy.12qo56a") }}</a-button>
      </template>
      <a-table
        class="trace-table"
        :data-source="traces"
        :columns="traceColumns"
        row-key="request_id"
        :loading="loading"
        size="small"
        :pagination="pagination"
        :scroll="{ x: 1280, y: 400 }"
        :customRow="traceRowProps"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'request_id'">
            <a-tooltip :title="record.request_id">
              <a-typography-text code class="request-id-text">{{ record.request_id }}</a-typography-text>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'api_key_username'">
            {{ record.api_key_username || '-' }}
          </template>
          <template v-else-if="column.key === 'api_key_name'">
            {{ record.api_key_name || '-' }}
          </template>
          <template v-else-if="column.key === 'agent'">
            <div>{{ record.agent_name || '-' }}</div>
            <div v-if="record.agent_id" class="muted">{{ record.agent_id }}</div>
          </template>
          <template v-else-if="column.key === 'api_key_group_names'">
            <a-space v-if="normalizeGroupNames(record.api_key_group_names).length" size="small" wrap>
              <a-tag v-for="name in normalizeGroupNames(record.api_key_group_names)" :key="name">{{ name }}</a-tag>
            </a-space>
            <span v-else>-</span>
          </template>
          <template v-else-if="column.key === 'type'">
            <a-tag :color="record.bypass_pii ? 'orange' : 'blue'">{{ record.bypass_pii ? 'Bypass' : 'PII Checked' }}</a-tag>
          </template>
          <template v-else-if="column.key === 'prompt_security'">
            <a-tag :color="promptSecurityColor(record.prompt_security_risk)">
              {{ promptSecurityRiskLabel(record.prompt_security_risk) }}
            </a-tag>
            <div class="muted">{{ promptSecurityActionLabel(record.prompt_security_action) }}</div>
          </template>
        </template>
      </a-table>
    </a-card>

    </a-card>

    <a-drawer
      v-model:open="drawerOpen"
      :title="selectedId || $t('legacy.1ngfjb6')"
      width="960"
      placement="right"
      destroy-on-close
    >
      <template #extra>
        <a-segmented v-model:value="viewMode" :options="[$t('legacy.rljyf2'), 'JSON']" />
      </template>
      <a-spin :spinning="detailLoading">
        <a-descriptions v-if="detail?.stages?.meta" bordered size="small" style="margin-bottom: 16px">
          <a-descriptions-item label="Tenant">{{ detail.stages.meta.tenant_id }}</a-descriptions-item>
          <a-descriptions-item label="Conversation">{{ detail.stages.meta.conversation_id }}</a-descriptions-item>
          <a-descriptions-item label="Model">{{ detail.stages.meta.model }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1in002o')">{{ detail.stages.meta.api_key_username || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.19kaip8')">{{ formatGroupNames(detail.stages.meta.api_key_group_names) }}</a-descriptions-item>
          <a-descriptions-item :label="$t('pipelineTrace.credential')">{{ detail.stages.meta.api_key_name || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="$t('pipelineTrace.credentialType')">{{ detail.stages.meta.credential_type || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="$t('pipelineTrace.agent')">
            {{ detail.stages.meta.agent_name || detail.stages.meta.agent_id || '-' }}
          </a-descriptions-item>
          <a-descriptions-item :label="$t('gatewaySkill.skill')">
            {{ detail.stages.meta.skill_name || '-' }}
            <span v-if="detail.stages.meta.skill_version_id || detail.stages.meta.skill_id" class="muted">
              · {{ detail.stages.meta.skill_version_id || detail.stages.meta.skill_id }}
            </span>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('gatewaySkill.trustState')">
            <a-tag v-if="detail.stages.meta.skill_trust_state" :color="skillTrustColor(detail.stages.meta.skill_trust_state)">
              {{ skillTrustLabel(detail.stages.meta.skill_trust_state) }}
            </a-tag>
            <span v-else>-</span>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('gatewaySkill.alerts')" :span="3">
            <a-space v-if="detail.stages.meta.skill_alert_codes?.length" wrap>
              <a-tag v-for="code in detail.stages.meta.skill_alert_codes" :key="code" :color="skillAlertColor(detail.stages.meta.skill_alert_severity)">
                {{ skillAlertLabel(code) }}
              </a-tag>
            </a-space>
            <span v-else>-</span>
          </a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.csussz')">{{ formatMs(detail.stages.meta.request_duration_ms) }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.j2g9ts')">{{ formatMs(detail.stages.meta.upstream_duration_ms) }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1yz91un')">{{ formatMs(detail.stages.meta.platform_duration_ms) }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.5h548n')">{{ promptSecuritySummary(detail.stages.meta) }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.1dzteri')">{{ formatNumber(originalInputTokens) }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.3xj6sq')">{{ formatNumber(modelInputTokens) }}</a-descriptions-item>
          <a-descriptions-item :label="$t('legacy.k6sqb1')">{{ formatNumber(detail.stages.meta.completion_tokens) }}</a-descriptions-item>
        </a-descriptions>

        <a-alert
          v-if="detail?.stages?.compressed?.enabled && detail.stages.compressed.tokens_saved > 0"
          type="success"
          show-icon
          :message="text(
            `智能压缩：节省 ${detail.stages.compressed.tokens_saved} tokens (${detail.stages.compressed.ratio * 100}%)，耗时 ${detail.stages.compressed.duration_ms}ms`,
            `Smart compression saved ${detail.stages.compressed.tokens_saved} tokens (${detail.stages.compressed.ratio * 100}%) in ${detail.stages.compressed.duration_ms}ms`,
          )"
          style="margin-bottom: 16px"
        />
        <a-alert
          v-if="detail?.stages?.compressed?.enabled && !detail.stages.compressed.tokens_saved"
          type="info"
          show-icon
          :message="$t('legacy.z23rbi')"
          style="margin-bottom: 16px"
        />

        <a-collapse v-model:activeKey="activeStages">
          <a-collapse-panel v-for="stage in stageOrder" :key="stage.key" :header="stage.label">
            <template #extra>
              <a-space @click.stop>
                <a-button size="small" @click="copyStage(stage.key)">{{ $t("legacy.1xbipwq") }}</a-button>
                <a-button v-if="stage.key === 'original'" size="small" danger @click="revealOriginal = !revealOriginal">
                  {{ revealOriginal ? $t('legacy.xkgxvo') : $t('legacy.1juapn3') }}
                </a-button>
              </a-space>
            </template>
            <a-alert
              v-if="stage.key === 'original' && !revealOriginal"
              type="warning"
              show-icon
              :message="$t('legacy.16r4k88')"
            />
            <pre v-else class="trace-block">{{ renderStage(stage.key) }}</pre>
          </a-collapse-panel>
        </a-collapse>
      </a-spin>
    </a-drawer>
  </div>
</template>

<script setup>
import { translateLegacy as phrase, translateText as text } from '../i18n'

import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'

import { getPrivacyTrace, listPrivacyTraces } from '../api'
import { copyText, promptManualCopy } from '../utils/clipboard'
import { formatBeijingDateTime, formatNumber } from '../utils/format'

const { t } = useI18n()
const route = useRoute()
const loading = ref(false)
const detailLoading = ref(false)
const traces = ref([])
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  showTotal: total => text(`共 ${total} 条`, `${total} total`),
})
const detail = ref(null)
const selectedId = ref('')
const drawerOpen = ref(false)
const viewMode = ref(phrase('legacy.rljyf2'))
const revealOriginal = ref(false)
const activeStages = ref(['prompt_security', 'masked', 'compressed', 'masked_response', 'final_response'])
const originalInputTokens = computed(() => {
  const compressed = detail.value?.stages?.compressed
  return compressed?.enabled ? compressed.pre_tokens : detail.value?.stages?.meta?.prompt_tokens
})
const modelInputTokens = computed(() => {
  const compressed = detail.value?.stages?.compressed
  return compressed?.enabled ? compressed.post_tokens : detail.value?.stages?.meta?.prompt_tokens
})
const stageOrder = [
  { key: 'prompt_security', label: phrase('legacy.18kdjir') },
  { key: 'original', label: phrase('legacy.1xtckzh') },
  { key: 'masked', label: phrase('legacy.1wx1lir') },
  { key: 'compressed', label: phrase('legacy.1ez1d3a') },
  { key: 'masked_response', label: phrase('legacy.1azc7gd') },
  { key: 'final_response', label: phrase('legacy.jgj4pf') },
]

const traceColumns = [
  { title: phrase('legacy.1f90xvr'), dataIndex: 'created_at', width: 135, customRender: ({ text }) => formatBeijingDateTime(text) },
  { title: phrase('legacy.1in002o'), key: 'api_key_username', width: 75 },
  { title: phrase('legacy.19kaip8'), key: 'api_key_group_names', width: 115 },
  { title: t('pipelineTrace.credential'), key: 'api_key_name', width: 105 },
  { title: t('pipelineTrace.agent'), key: 'agent', width: 130 },
  { title: phrase('legacy.1ow6qt'), dataIndex: 'model', width: 110 },
  { title: phrase('legacy.csussz'), dataIndex: 'request_duration_ms', width: 80, customRender: ({ text }) => formatMs(text) },
  { title: phrase('legacy.j2g9ts'), dataIndex: 'upstream_duration_ms', width: 85, customRender: ({ text }) => formatMs(text) },
  { title: phrase('legacy.1yz91un'), dataIndex: 'platform_duration_ms', width: 85, customRender: ({ text }) => formatMs(text) },
  { title: phrase('legacy.5h548n'), key: 'prompt_security', width: 105 },
  { title: phrase('legacy.1qtojr9'), dataIndex: 'prompt_tokens', width: 75, customRender: ({ text }) => formatNumber(text) },
  { title: phrase('legacy.w0yvd4'), dataIndex: 'completion_tokens', width: 75, customRender: ({ text }) => formatNumber(text) },
  { title: phrase('legacy.anh4cj'), key: 'type', width: 90 },
  { title: 'Request ID', key: 'request_id', width: 90 },
]

const fetchTraces = async (page = pagination.value.current, pageSize = pagination.value.pageSize) => {
  loading.value = true
  try {
    const res = await listPrivacyTraces({ page, page_size: pageSize })
    traces.value = res.traces || []
    pagination.value = {
      ...pagination.value,
      current: res.page || page,
      pageSize: res.page_size || pageSize,
      total: res.total || 0,
    }
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1s0pk7m'))
  } finally {
    loading.value = false
  }
}

const refreshTraces = () => {
  fetchTraces()
}

const handleTableChange = (pager) => {
  fetchTraces(pager.current || 1, pager.pageSize || 10)
}

const selectTrace = async (record) => {
  selectedId.value = record.request_id
  drawerOpen.value = true
  revealOriginal.value = false
  detailLoading.value = true
  try {
    detail.value = await getPrivacyTrace(record.request_id)
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.zzt7t8'))
  } finally {
    detailLoading.value = false
  }
}

const traceRowProps = (record) => ({
  onClick: () => selectTrace(record),
  style: { cursor: 'pointer' },
})

const normalizeGroupNames = (value) => Array.isArray(value) ? value.filter(Boolean) : []

const formatGroupNames = (value) => {
  const names = normalizeGroupNames(value)
  return names.length ? names.join(', ') : '-'
}
const formatMs = (value) => value || value === 0 ? `${Number(value).toFixed(1)} ms` : '-'
const promptSecurityRiskLabel = (value) => ({ none: phrase('legacy.41lnsu'), LOW: phrase('legacy.qy3yng'), MEDIUM: phrase('legacy.pakbe9'), HIGH: phrase('legacy.197bn2e') }[value] || phrase('legacy.41lnsu'))
const promptSecurityActionLabel = (value) => ({ off: phrase('legacy.g0fanx'), log: phrase('legacy.4drpun'), pass: phrase('legacy.j666m6'), record: phrase('legacy.cdnjf2'), warn: phrase('legacy.gjwe4z'), block: phrase('legacy.14byf2d') }[value] || phrase('legacy.g0fanx'))
const promptSecurityColor = (value) => ({ LOW: 'blue', MEDIUM: 'orange', HIGH: 'red' }[value] || 'default')
const promptSecuritySummary = (meta = {}) =>
  `${promptSecurityRiskLabel(meta.prompt_security_risk)} / ${promptSecurityActionLabel(meta.prompt_security_action)}`
const skillTrustLabel = value => ({
  missing: t('gatewaySkill.missing'),
  declared_trusted: t('gatewaySkill.declaredTrusted'),
  suspicious: t('gatewaySkill.suspicious'),
}[value] || value)
const skillTrustColor = value => ({ missing: 'default', declared_trusted: 'orange', suspicious: 'red' }[value] || 'default')
const skillAlertColor = value => ({ info: 'default', medium: 'orange', high: 'red' }[value] || 'default')
const skillAlertLabel = code => ({
  'gateway.skill_context_missing': t('gatewaySkill.contextMissing'),
  'gateway.skill_unknown': t('gatewaySkill.unknown'),
  'gateway.skill_id_mismatch': t('gatewaySkill.idMismatch'),
  'gateway.skill_name_mismatch': t('gatewaySkill.nameMismatch'),
  'gateway.skill_not_loadable': t('gatewaySkill.notLoadable'),
  'gateway.skill_not_allowed_for_agent': t('gatewaySkill.notAllowed'),
  'gateway.skill_context_unverified': t('gatewaySkill.unverified'),
}[code] || code)

const renderContentPart = (part) => {
  if (part === null || part === undefined) return ''
  if (typeof part === 'string') return part
  if (Array.isArray(part)) return part.map(renderContentPart).filter(Boolean).join('\n')
  if (typeof part !== 'object') return String(part)

  if (part.type === 'text' && typeof part.text === 'string') return part.text
  if (typeof part.content === 'string') return part.content
  if (typeof part.text === 'string') return part.text
  if (part.type) return `[${part.type}] ${JSON.stringify(part)}`
  return JSON.stringify(part, null, 2)
}

const renderMessages = (messages = []) => messages.map((msg, index) => {
  const tag = msg.system ? 'SYSTEM INJECTED' : String(msg.role || '').toUpperCase()
  return `#${index + 1} ${tag}\n${renderContentPart(msg.content)}`
}).join('\n\n')

const renderChoices = (choices = []) => choices.map((choice) => `#${choice.index ?? 0}\n${renderContentPart(choice.content)}`).join('\n\n')

const renderPromptSecurity = (data = {}) => {
  if (!data.enabled) return phrase('legacy.63mr26')
  const lines = [
    text(`检测模式：${promptSecurityActionLabel(data.mode)}`, `Detection mode: ${promptSecurityActionLabel(data.mode)}`),
    text(`风险等级：${promptSecurityRiskLabel(data.risk_level)}`, `Risk level: ${promptSecurityRiskLabel(data.risk_level)}`),
    text(`处理动作：${promptSecurityActionLabel(data.action)}`, `Action: ${promptSecurityActionLabel(data.action)}`),
    text(`命中数量：${data.findings_count || 0}`, `Findings: ${data.findings_count || 0}`),
  ]
  for (const item of data.findings || []) {
    lines.push(`\n- ${item.reason || item.rule}（${promptSecurityRiskLabel(item.severity)}）`)
    if (item.snippet) {
      lines.push(text(`  命中片段：${item.snippet}`, `  Matched snippet: ${item.snippet}`))
    }
  }
  return lines.join('\n')
}

const renderStage = (stage) => {
  const data = detail.value?.stages?.[stage] || {}
  if (viewMode.value === 'JSON') return JSON.stringify(data, null, 2)
  if (stage === 'prompt_security') return renderPromptSecurity(data)
  if (data.messages) return renderMessages(data.messages)
  if (data.choices) return renderChoices(data.choices)
  return JSON.stringify(data, null, 2)
}

const copyStage = async (stage) => {
  const text = renderStage(stage)
  try {
    await copyText(text)
    message.success(phrase('legacy.alyyje'))
  } catch {
    message.warning(t('clipboard.copyFailed'))
    promptManualCopy(text, t('clipboard.manualCopyPrompt'))
  }
}

onMounted(async () => {
  await fetchTraces()
  const requestId = Array.isArray(route.query.request_id) ? route.query.request_id[0] : route.query.request_id
  if (requestId) await selectTrace({ request_id: String(requestId) })
})
</script>

<style scoped>
.trace-block {
  max-height: 520px;
  overflow: auto;
  padding: 12px;
  margin: 0;
  background: #0f172a;
  color: #e5e7eb;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.55;
}

.request-id-text {
  display: inline-block;
  max-width: 70px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  white-space: nowrap;
}

.trace-table :deep(.ant-table-body) {
  min-height: 400px;
}
</style>
