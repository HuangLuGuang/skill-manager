<template>
  <div>
    <a-page-header title="接入与运行" sub-title="指导 Agent 接入运行时守卫，并执行加载校验与工具权限校验" />

    <a-card title="Agent Skill Verifier 接入" style="margin-top: 16px">
      <template #extra>
        <a-button type="primary" :loading="guardDownloading" @click="handleSkillGuardDownload">下载 Skill Verifier</a-button>
      </template>
      <a-alert
        type="info"
        show-icon
        message="Agent Skill Verifier 是 Agent 侧验证门禁"
        description="它安装在 Agent 的 skills 目录中。Agent 加载第三方 Skill 前，先向平台校验 Skill 状态、内容指纹、Agent 授权范围和运行凭证，未通过则阻止加载并写入审计。"
        style="margin-bottom: 16px"
      />
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">1. 签发运行凭证</div>
            <p class="hint">在“凭证管理”创建 Agent 运行凭证，绑定目标 Agent，并授予提交扫描与运行时校验权限。</p>
            <a-space wrap>
              <a-tag v-for="scope in skillGuardScopes" :key="scope" color="blue">{{ scope }}</a-tag>
            </a-space>
          </div>
        </a-col>
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">2. 安装到 Agent</div>
            <p class="hint">下载 zip 后解压到 Agent 的 skills 目录。安装完成后重启 Agent 或刷新 skill 列表。</p>
            <a-tabs size="small">
              <a-tab-pane key="codex" tab="Codex">
                <pre class="code-block compact">{{ codexGuardInstallCommand }}</pre>
              </a-tab-pane>
              <a-tab-pane key="claude" tab="Claude Code">
                <pre class="code-block compact">{{ claudeGuardInstallCommand }}</pre>
              </a-tab-pane>
            </a-tabs>
          </div>
        </a-col>
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">3. 加载前校验</div>
            <p class="hint">Agent 使用 Skill 前执行校验。平台会检查是否已批准、内容指纹是否匹配、当前 Agent 是否被授权。</p>
            <pre class="code-block compact">{{ guardUsageCommand }}</pre>
          </div>
        </a-col>
      </a-row>
    </a-card>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="12">
        <a-card title="加载检查">
          <a-form layout="vertical" :model="canLoadForm" @finish="handleCanLoad">
            <a-form-item label="技能名称">
              <a-input v-model:value="canLoadForm.skillName" placeholder="如 byd-stock-news" />
            </a-form-item>
            <a-form-item label="技能路径">
              <a-input v-model:value="canLoadForm.skillPath" placeholder="/path/to/skill，可选" />
            </a-form-item>
            <a-form-item label="Agent ID">
              <a-input v-model:value="canLoadForm.agentId" placeholder="agent-1，可选" />
            </a-form-item>
            <a-button type="primary" html-type="submit" :loading="checkingCanLoad">检查</a-button>
          </a-form>

          <a-result
            v-if="canLoadResult"
            :status="canLoadResult.allowed ? 'success' : 'error'"
            :title="canLoadResult.allowed ? '允许加载' : '拒绝加载'"
            :sub-title="canLoadResult.reason"
            style="padding-inline: 0"
          >
            <template #extra>
              <a-space wrap>
                <a-tag :color="statusColor(canLoadResult.status)" :title="statusTitle(canLoadResult.status)">{{ canLoadResult.status || 'unknown' }}</a-tag>
                <a-tag :color="riskColor(canLoadResult.risk_level)" :title="riskTitle(canLoadResult.risk_level)">
                  {{ canLoadResult.risk_level || 'unknown' }}
                </a-tag>
              </a-space>
            </template>
          </a-result>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="12">
        <a-card title="工具权限检查">
          <a-form layout="vertical" :model="toolForm" @finish="handleCheckTool">
            <a-form-item label="技能名称">
              <a-input v-model:value="toolForm.skillName" placeholder="如 byd-stock-news" />
            </a-form-item>
            <a-form-item label="工具名称">
              <a-input v-model:value="toolForm.toolName" placeholder="Read / Bash / WebSearch" />
            </a-form-item>
            <a-form-item label="Agent ID">
              <a-input v-model:value="toolForm.agentId" placeholder="agent-1，可选" />
            </a-form-item>
            <a-button type="primary" html-type="submit" :loading="checkingTool">校验</a-button>
          </a-form>

          <a-result
            v-if="toolResult"
            :status="toolResult.allowed ? 'success' : 'error'"
            :title="toolResult.allowed ? '允许调用工具' : '拒绝调用工具'"
            :sub-title="`${toolResult.skill_name} -> ${toolResult.tool_name}`"
            style="padding-inline: 0"
          />
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="10">
        <a-card title="当前可加载技能">
          <a-space style="margin-bottom: 16px" wrap>
            <a-select v-model:value="skillRiskFilter" style="width: 160px" @change="handleSkillFilterChange">
              <a-select-option value="all">全部风险</a-select-option>
              <a-select-option value="benign">benign</a-select-option>
              <a-select-option value="suspicious">suspicious</a-select-option>
              <a-select-option value="malicious">malicious</a-select-option>
            </a-select>
            <a-input v-model:value="skillKeyword" placeholder="搜索 技能名称 / ID" style="width: 220px" allow-clear />
            <a-button type="primary" @click="fetchLoadableSkills" :loading="loadingSkills">查询</a-button>
            <a-button @click="resetSkillFilters" :disabled="loadingSkills">重置</a-button>
          </a-space>

          <div class="table-meta">共 {{ skillTotal }} 条可加载技能</div>

          <a-table
            :data-source="loadableSkills"
            :columns="skillColumns"
            rowKey="skill_id"
            :loading="loadingSkills"
            :pagination="skillPagination"
            :locale="{ emptyText: '当前没有可加载技能' }"
            @change="handleSkillTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.name }}</a>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)" :title="statusTitle(record.status)">{{ record.status }}</a-tag>
              </template>
              <template v-else-if="column.key === 'risk_level'">
                <a-tag v-if="record.risk_level === 'malicious'" color="red" title="恶意">malicious</a-tag>
                <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange" title="可疑">suspicious</a-tag>
                <a-tag v-else-if="record.risk_level === 'benign'" color="green" title="安全">benign</a-tag>
                <a-tag v-else color="default">-</a-tag>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="14">
        <a-card title="最近运行时事件">
          <a-space style="margin-bottom: 16px" wrap>
            <a-select v-model:value="eventFilter" style="width: 220px" @change="handleAuditFilterChange">
              <a-select-option value="all">全部运行时事件</a-select-option>
              <a-select-option v-for="option in runtimeEventOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </a-select-option>
            </a-select>
            <a-input v-model:value="auditKeyword" placeholder="搜索 Skill / Agent / IP / 凭证" style="width: 240px" allow-clear />
            <a-button type="primary" @click="fetchRuntimeAudit" :loading="loadingAudit">查询</a-button>
            <a-button @click="resetAuditFilters" :disabled="loadingAudit">重置</a-button>
          </a-space>

          <div class="table-meta">共 {{ auditTotal }} 条运行时事件</div>

          <a-table
            :data-source="auditRows"
            :columns="auditColumns"
            rowKey="event_id"
            :loading="loadingAudit"
            :pagination="auditPagination"
            :locale="{ emptyText: '最近没有运行时事件' }"
            @change="handleAuditTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'skill_name'">
                <a v-if="record.skill_id && record.skill_id !== 'unknown'" @click="$router.push(`/skills/${record.skill_id}`)">
                  {{ record.skill_name }}
                </a>
                <span v-else>{{ record.skill_name }}</span>
              </template>
              <template v-else-if="column.key === 'event_type'">
                <a-tag :color="runtimeEventColor(record.event_type)">{{ runtimeEventLabel(record.event_type) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'agent_id'">
                <span>{{ auditAgent(record) }}</span>
              </template>
              <template v-else-if="column.key === 'client_ip'">
                <span>{{ auditIp(record) }}</span>
              </template>
              <template v-else-if="column.key === 'actor'">
                <span>{{ auditActor(record) }}</span>
              </template>
              <template v-else-if="column.key === 'details'">
                <span>{{ formatRuntimeDetails(record.details) }}</span>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import { downloadSkillVerifier, getAuditPaged, listSkillsPaged, runtimeCanLoad, runtimeCheckTool } from '../api'
import { formatDateTime } from '../utils/format'

const checkingCanLoad = ref(false)
const checkingTool = ref(false)
const loadingSkills = ref(false)
const loadingAudit = ref(false)
const guardDownloading = ref(false)

const canLoadResult = ref(null)
const toolResult = ref(null)
const loadableSkills = ref([])
const auditRows = ref([])
const skillTotal = ref(0)
const auditTotal = ref(0)
const eventFilter = ref('all')
const skillRiskFilter = ref('all')
const skillKeyword = ref('')
const auditKeyword = ref('')
const skillSortState = ref({ field: 'name', order: 'ascend' })
const auditSortState = ref({ field: 'timestamp', order: 'descend' })
const skillGuardScopes = ['scanner:submit', 'scanner:read-own-results', 'scanner:read-own-sessions', 'runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool']
const runtimeApiOrigin = (() => {
  const { protocol, hostname, port } = window.location
  if ((hostname === 'localhost' || hostname === '127.0.0.1') && (port === '5173' || port === '5174')) {
    return `${protocol}//${hostname}:8001`
  }
  return window.location.origin
})()
const codexGuardInstallCommand = `mkdir -p ~/.codex/skills
unzip agent-manager-skill-verifier.zip -d ~/.codex/skills/

export AGENT_MANAGER_BASE_URL="${runtimeApiOrigin}"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_ID="<agent-id>"`
const claudeGuardInstallCommand = `mkdir -p ~/.claude/skills
unzip agent-manager-skill-verifier.zip -d ~/.claude/skills/

export AGENT_MANAGER_BASE_URL="${runtimeApiOrigin}"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_ID="<agent-id>"`
const guardUsageCommand = `python <skills-dir>/agent-manager-skill-verifier/scripts/agent_manager_skill_guard.py verify \\
  --path /path/to/skill`
const skillPagination = ref({
  current: 1,
  pageSize: 6,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['6', '12', '24'],
  showTotal: (total) => `共 ${total} 条`,
})
const auditPagination = ref({
  current: 1,
  pageSize: 6,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['6', '12', '24'],
  showTotal: (total) => `共 ${total} 条`,
})

const canLoadForm = reactive({
  skillName: '',
  skillPath: '',
  agentId: '',
})

const toolForm = reactive({
  skillName: '',
  toolName: '',
  agentId: '',
})

const skillColumns = [
  { title: '技能名称', dataIndex: 'name', key: 'name', sorter: true },
  { title: '状态', dataIndex: 'status', key: 'status', width: 120, sorter: true },
  { title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 120, sorter: true },
]

const auditColumns = [
  { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 220, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: '事件', dataIndex: 'event_type', key: 'event_type', width: 170, sorter: true },
  { title: 'Skill', dataIndex: 'skill_name', key: 'skill_name', width: 180, sorter: true },
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id', width: 160 },
  { title: '来源 IP', dataIndex: 'client_ip', key: 'client_ip', width: 140 },
  { title: '凭证/Actor', dataIndex: 'actor', key: 'actor', width: 170, sorter: true },
  { title: '详情', dataIndex: 'details', key: 'details' },
]

const runtimeEventOptions = [
  { value: 'skill_signature_verified', label: '完整性校验通过' },
  { value: 'skill_load_allowed', label: '允许加载 Skill' },
  { value: 'skill_load_blocked', label: '阻止加载 Skill' },
  { value: 'skill_tamper_detected', label: '发现内容不一致' },
  { value: 'tool_invoked', label: '允许工具调用' },
  { value: 'tool_blocked', label: '阻止工具调用' },
]
const runtimeEventTypes = runtimeEventOptions.map((item) => item.value)
const runtimeEventLabelMap = Object.fromEntries(runtimeEventOptions.map((item) => [item.value, item.label]))

const handleCanLoad = async () => {
  if (!canLoadForm.skillName.trim()) {
    message.warning('请先输入 技能名称')
    return
  }
  checkingCanLoad.value = true
  try {
    canLoadResult.value = await runtimeCanLoad(canLoadForm.skillName.trim(), {
      skill_path: canLoadForm.skillPath.trim() || undefined,
      agent_id: canLoadForm.agentId.trim() || undefined,
    })
    fetchRuntimeAudit()
  } catch (error) {
    message.error(error.response?.data?.detail || '加载检查失败')
  } finally {
    checkingCanLoad.value = false
  }
}

const handleCheckTool = async () => {
  if (!toolForm.skillName.trim() || !toolForm.toolName.trim()) {
    message.warning('请先输入 技能名称和工具名称')
    return
  }
  checkingTool.value = true
  try {
    toolResult.value = await runtimeCheckTool({
      skill_name: toolForm.skillName.trim(),
      tool_name: toolForm.toolName.trim(),
      agent_id: toolForm.agentId.trim() || undefined,
    })
    fetchRuntimeAudit()
  } catch (error) {
    message.error(error.response?.data?.detail || '工具校验失败')
  } finally {
    checkingTool.value = false
  }
}

const handleSkillGuardDownload = async () => {
  guardDownloading.value = true
  try {
    const blob = await downloadSkillVerifier()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'agent-manager-skill-verifier.zip'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    message.error(error.response?.data?.detail || '下载 Agent Skill Verifier 失败')
  } finally {
    guardDownloading.value = false
  }
}

const fetchLoadableSkills = async () => {
  loadingSkills.value = true
  try {
    const res = await listSkillsPaged({
      loadable_only: true,
      risk_level: skillRiskFilter.value === 'all' ? undefined : skillRiskFilter.value,
      q: skillKeyword.value.trim() || undefined,
      page: skillPagination.value.current,
      page_size: skillPagination.value.pageSize,
      sort_by: skillSortState.value.field,
      sort_order: skillSortState.value.order === 'ascend' ? 'asc' : 'desc',
    })
    loadableSkills.value = Array.isArray(res.items) ? res.items : []
    skillTotal.value = Number(res.total || 0)
    skillPagination.value = {
      ...skillPagination.value,
      total: skillTotal.value,
      current: Number(res.page || skillPagination.value.current),
      pageSize: Number(res.page_size || skillPagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || '获取可加载技能失败')
    loadableSkills.value = []
    skillTotal.value = 0
  } finally {
    loadingSkills.value = false
  }
}

const fetchRuntimeAudit = async () => {
  loadingAudit.value = true
  try {
    const res = await getAuditPaged({
      since_hours: 168,
      event_type: eventFilter.value === 'all' ? undefined : eventFilter.value,
      event_types: eventFilter.value === 'all' ? runtimeEventTypes.join(',') : undefined,
      q: auditKeyword.value.trim() || undefined,
      page: auditPagination.value.current,
      page_size: auditPagination.value.pageSize,
      sort_order: auditSortState.value.order === 'ascend' ? 'asc' : 'desc',
      limit: 1000,
    })
    auditRows.value = Array.isArray(res.items) ? res.items : []
    auditTotal.value = Number(res.total || 0)
    auditPagination.value = {
      ...auditPagination.value,
      total: auditTotal.value,
      current: Number(res.page || auditPagination.value.current),
      pageSize: Number(res.page_size || auditPagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || '获取运行时事件失败')
    auditRows.value = []
    auditTotal.value = 0
  } finally {
    loadingAudit.value = false
  }
}

const handleSkillTableChange = (pager, _filters, sorter) => {
  skillPagination.value = {
    ...skillPagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    skillSortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchLoadableSkills()
}

const handleAuditTableChange = (pager, _filters, sorter) => {
  auditPagination.value = {
    ...auditPagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    auditSortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchRuntimeAudit()
}

const handleSkillFilterChange = () => {
  skillPagination.value = {
    ...skillPagination.value,
    current: 1,
  }
  fetchLoadableSkills()
}

const handleAuditFilterChange = () => {
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const resetSkillFilters = () => {
  skillRiskFilter.value = 'all'
  skillKeyword.value = ''
  skillSortState.value = { field: 'name', order: 'ascend' }
  skillPagination.value = {
    ...skillPagination.value,
    current: 1,
  }
  fetchLoadableSkills()
}

const resetAuditFilters = () => {
  eventFilter.value = 'all'
  auditKeyword.value = ''
  auditSortState.value = { field: 'timestamp', order: 'descend' }
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const statusColor = (value) =>
  ({
    PENDING: 'gold',
    VETTED: 'orange',
    APPROVED: 'green',
    DEPLOYED: 'blue',
    REJECTED: 'red',
    RETIRED: 'default',
  }[value] || 'default')

const statusTitle = (value) =>
  ({
    PENDING: '分析中',
    VETTED: '待审核',
    APPROVED: '已批准',
    DEPLOYED: '已部署',
    REJECTED: '已拒绝',
    RETIRED: '已退役',
  }[value] || '未知')

const riskColor = (value) =>
  ({
    benign: 'green',
    suspicious: 'orange',
    malicious: 'red',
  }[value] || 'default')

const riskTitle = (value) =>
  ({
    benign: '安全',
    suspicious: '可疑',
    malicious: '恶意',
  }[value] || '未知')

const runtimeEventLabel = (value) => runtimeEventLabelMap[value] || value || '-'
const runtimeEventColor = (value) => {
  if (['skill_load_blocked', 'skill_tamper_detected', 'tool_blocked'].includes(value)) return 'red'
  if (['skill_load_allowed', 'skill_signature_verified', 'tool_invoked'].includes(value)) return 'green'
  return 'blue'
}
const auditDetails = (record) => (record?.details && typeof record.details === 'object' ? record.details : {})
const auditAgent = (record) => record.agent_id || auditDetails(record).agent_id || record.actor || '-'
const auditIp = (record) => record.client_ip || auditDetails(record).client_ip || '-'
const auditActor = (record) => {
  const details = auditDetails(record)
  if (details.token_name) return details.token_name
  if (details.token_prefix) return details.token_prefix
  return record.actor || '-'
}
const formatRuntimeDetails = (details = {}) => {
  const labels = {
    status: '状态',
    reason: '原因',
    tool: '工具',
    allowed: '结果',
    verification_mode: '校验方式',
  }
  const hidden = new Set([
    'agent_id',
    'client_ip',
    'token_id',
    'token_name',
    'token_type',
    'token_prefix',
    'bound_agent_id',
    'user_id',
    'group_id',
  ])
  return Object.entries(details || {})
    .filter(([key, value]) => !hidden.has(key) && value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${labels[key] || key}: ${value === true ? '允许' : value === false ? '拒绝' : value}`)
    .join('；') || '-'
}

onMounted(() => {
  fetchLoadableSkills()
  fetchRuntimeAudit()
})
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}

.code-block {
  margin: 0;
  padding: 12px;
  overflow: auto;
  background: #0f172a;
  color: #dbeafe;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
}

.code-block.compact {
  max-height: 220px;
}

.guard-panel {
  min-height: 100%;
  padding: 12px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  background: #fafafa;
}

.guard-panel-title {
  margin-bottom: 8px;
  color: #262626;
  font-weight: 600;
}

.hint {
  color: #8c8c8c;
  font-size: 12px;
}
</style>
