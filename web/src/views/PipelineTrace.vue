<template>
  <div>
    <a-page-header title="隐私链路追踪" sub-title="查看模型请求的脱敏、智能压缩、响应和还原过程" />

    <a-alert
      type="warning"
      show-icon
      message="链路详情包含原始隐私数据"
      description="仅管理员和隐私审计人员应查看此页面。打开原始内容前请确认业务授权。"
      style="margin-top: 16px"
    />

    <a-card title="最近请求" style="margin-top: 16px">
      <template #extra>
        <a-button @click="refreshTraces" :loading="loading">刷新</a-button>
      </template>
      <a-table
        class="trace-table"
        :data-source="traces"
        :columns="traceColumns"
        row-key="request_id"
        :loading="loading"
        size="small"
        :pagination="pagination"
        :scroll="{ x: 1120, y: 400 }"
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

    <a-drawer
      v-model:open="drawerOpen"
      :title="selectedId || '隐私链路追踪'"
      width="960"
      placement="right"
      destroy-on-close
    >
      <template #extra>
        <a-segmented v-model:value="viewMode" :options="['文本', 'JSON']" />
      </template>
      <a-spin :spinning="detailLoading">
        <a-descriptions v-if="detail?.stages?.meta" bordered size="small" style="margin-bottom: 16px">
          <a-descriptions-item label="Tenant">{{ detail.stages.meta.tenant_id }}</a-descriptions-item>
          <a-descriptions-item label="Conversation">{{ detail.stages.meta.conversation_id }}</a-descriptions-item>
          <a-descriptions-item label="Model">{{ detail.stages.meta.model }}</a-descriptions-item>
          <a-descriptions-item label="用户">{{ detail.stages.meta.api_key_username || '-' }}</a-descriptions-item>
          <a-descriptions-item label="用户组">{{ formatGroupNames(detail.stages.meta.api_key_group_names) }}</a-descriptions-item>
          <a-descriptions-item label="API key">{{ detail.stages.meta.api_key_name || '-' }}</a-descriptions-item>
          <a-descriptions-item label="总耗时">{{ formatMs(detail.stages.meta.request_duration_ms) }}</a-descriptions-item>
          <a-descriptions-item label="模型耗时">{{ formatMs(detail.stages.meta.upstream_duration_ms) }}</a-descriptions-item>
          <a-descriptions-item label="平台耗时">{{ formatMs(detail.stages.meta.platform_duration_ms) }}</a-descriptions-item>
          <a-descriptions-item label="Prompt 防护">{{ promptSecuritySummary(detail.stages.meta) }}</a-descriptions-item>
          <a-descriptions-item label="原始输入 Token">{{ formatNumber(originalInputTokens) }}</a-descriptions-item>
          <a-descriptions-item label="发给模型输入 Token">{{ formatNumber(modelInputTokens) }}</a-descriptions-item>
          <a-descriptions-item label="输出 Token">{{ formatNumber(detail.stages.meta.completion_tokens) }}</a-descriptions-item>
        </a-descriptions>

        <a-alert
          v-if="detail?.stages?.compressed?.enabled && detail.stages.compressed.tokens_saved > 0"
          type="success"
          show-icon
          :message="`智能压缩: 节省 ${detail.stages.compressed.tokens_saved} tokens (${detail.stages.compressed.ratio * 100}%), 耗时 ${detail.stages.compressed.duration_ms}ms`"
          style="margin-bottom: 16px"
        />
        <a-alert
          v-if="detail?.stages?.compressed?.enabled && !detail.stages.compressed.tokens_saved"
          type="info"
          show-icon
          message="智能压缩已开启，但本请求无额外压缩空间（内容已足够精简）"
          style="margin-bottom: 16px"
        />

        <a-collapse v-model:activeKey="activeStages">
          <a-collapse-panel v-for="stage in stageOrder" :key="stage.key" :header="stage.label">
            <template #extra>
              <a-space @click.stop>
                <a-button size="small" @click="copyStage(stage.key)">复制</a-button>
                <a-button v-if="stage.key === 'original'" size="small" danger @click="revealOriginal = !revealOriginal">
                  {{ revealOriginal ? '隐藏原始内容' : '确认查看' }}
                </a-button>
              </a-space>
            </template>
            <a-alert
              v-if="stage.key === 'original' && !revealOriginal"
              type="warning"
              show-icon
              message="原始请求可能包含 PII，点击“确认查看”后展示。"
            />
            <pre v-else class="trace-block">{{ renderStage(stage.key) }}</pre>
          </a-collapse-panel>
        </a-collapse>
      </a-spin>
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import { getPrivacyTrace, listPrivacyTraces } from '../api'
import { formatBeijingDateTime } from '../utils/format'

const loading = ref(false)
const detailLoading = ref(false)
const traces = ref([])
const pagination = ref({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  showTotal: (total) => `共 ${total} 条`,
})
const detail = ref(null)
const selectedId = ref('')
const drawerOpen = ref(false)
const viewMode = ref('文本')
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
  { key: 'prompt_security', label: '0. Prompt 防护' },
  { key: 'original', label: '1. 原始请求（含 PII）' },
  { key: 'masked', label: '2. 发送给 LLM（已替换）' },
  { key: 'compressed', label: '3. 智能压缩后（发送上游）' },
  { key: 'masked_response', label: '4. LLM 返回（含占位符）' },
  { key: 'final_response', label: '5. 最终响应（已还原）' },
]

const traceColumns = [
  { title: '时间', dataIndex: 'created_at', width: 135, customRender: ({ text }) => formatBeijingDateTime(text) },
  { title: '用户', key: 'api_key_username', width: 75 },
  { title: '用户组', key: 'api_key_group_names', width: 115 },
  { title: 'API Key', key: 'api_key_name', width: 105 },
  { title: '模型', dataIndex: 'model', width: 110 },
  { title: '总耗时', dataIndex: 'request_duration_ms', width: 80, customRender: ({ text }) => formatMs(text) },
  { title: '模型耗时', dataIndex: 'upstream_duration_ms', width: 85, customRender: ({ text }) => formatMs(text) },
  { title: '平台耗时', dataIndex: 'platform_duration_ms', width: 85, customRender: ({ text }) => formatMs(text) },
  { title: 'Prompt 防护', key: 'prompt_security', width: 105 },
  { title: '输入', dataIndex: 'prompt_tokens', width: 75, customRender: ({ text }) => formatNumber(text) },
  { title: '输出', dataIndex: 'completion_tokens', width: 75, customRender: ({ text }) => formatNumber(text) },
  { title: '类型', key: 'type', width: 90 },
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
    message.error(error.response?.data?.detail || '获取链路列表失败')
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
    message.error(error.response?.data?.detail || '获取链路详情失败')
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
const formatNumber = (value) => value || value === 0 ? Number(value).toLocaleString() : '-'
const promptSecurityRiskLabel = (value) => ({ none: '无风险', LOW: '低风险', MEDIUM: '中风险', HIGH: '高风险' }[value] || '无风险')
const promptSecurityActionLabel = (value) => ({ off: '关闭', log: '仅记录', pass: '通过', record: '记录', warn: '告警放行', block: '已阻断' }[value] || '关闭')
const promptSecurityColor = (value) => ({ LOW: 'blue', MEDIUM: 'orange', HIGH: 'red' }[value] || 'default')
const promptSecuritySummary = (meta = {}) =>
  `${promptSecurityRiskLabel(meta.prompt_security_risk)} / ${promptSecurityActionLabel(meta.prompt_security_action)}`

const renderMessages = (messages = []) => messages.map((msg, index) => {
  const tag = msg.system ? 'SYSTEM INJECTED' : String(msg.role || '').toUpperCase()
  return `#${index + 1} ${tag}\n${msg.content || ''}`
}).join('\n\n')

const renderChoices = (choices = []) => choices.map((choice) => `#${choice.index ?? 0}\n${choice.content || ''}`).join('\n\n')

const renderPromptSecurity = (data = {}) => {
  if (!data.enabled) return 'Prompt 防护未开启'
  const lines = [
    `检测模式：${promptSecurityActionLabel(data.mode)}`,
    `风险等级：${promptSecurityRiskLabel(data.risk_level)}`,
    `处理动作：${promptSecurityActionLabel(data.action)}`,
    `命中数量：${data.findings_count || 0}`,
  ]
  for (const item of data.findings || []) {
    lines.push(`\n- ${item.reason || item.rule}（${promptSecurityRiskLabel(item.severity)}）`)
    if (item.snippet) lines.push(`  命中片段：${item.snippet}`)
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
  await navigator.clipboard.writeText(renderStage(stage))
  message.success('已复制')
}

onMounted(fetchTraces)
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
