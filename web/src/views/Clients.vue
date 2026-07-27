<template>
  <div>
    <a-page-header title="客户端管理" sub-title="统一发现、安装、校验和隔离本地 Agent Skill">
      <template #extra>
        <a-button type="primary" @click="installGuideVisible = true">安装客户端</a-button>
        <a-button :loading="loading" @click="loadClients">刷新</a-button>
      </template>
    </a-page-header>

    <a-row :gutter="[16, 16]" class="summary-row">
      <a-col :xs="12" :lg="6"><a-card><a-statistic title="受管客户端" :value="clients.length" /></a-card></a-col>
      <a-col :xs="12" :lg="6"><a-card><a-statistic title="在线" :value="onlineCount" /></a-card></a-col>
      <a-col :xs="12" :lg="6"><a-card><a-statistic title="已发现 Agent" :value="agentCount" /></a-card></a-col>
      <a-col :xs="12" :lg="6"><a-card><a-statistic title="异常事件" :value="issueCount" /></a-card></a-col>
    </a-row>

    <a-card class="table-card">
      <a-table :columns="columns" :data-source="clients" row-key="client_id" :loading="loading" :pagination="{ pageSize: 10 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'client'">
            <a @click="openDetail(record)">{{ record.name }}</a>
            <div class="muted">{{ record.hostname }} · {{ record.client_id }}</div>
          </template>
          <template v-else-if="column.key === 'platform'">
            <div>{{ record.os }} / {{ record.arch }}</div>
            <div class="muted">{{ governanceShortLabel(record.governance_mode) }} · Client {{ record.client_version }}</div>
          </template>
          <template v-else-if="column.key === 'agents'">
            <span>{{ record.agents?.length || 0 }} 个</span>
            <span class="muted inline-note">支持 Skill：{{ managedAgentCount(record) }}</span>
          </template>
          <template v-else-if="column.key === 'skills'">{{ skillCount(record) }}</template>
          <template v-else-if="column.key === 'credentialOwner'">{{ record.registered_by || '-' }}</template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="isOnline(record) ? 'green' : 'default'">{{ isOnline(record) ? '在线' : '离线' }}</a-tag>
          </template>
          <template v-else-if="column.key === 'lastSeen'">{{ formatTime(record.last_seen_at) }}</template>
          <template v-else-if="column.key === 'action'">
            <a @click="openDetail(record)">查看</a>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-drawer v-model:open="detailVisible" title="客户端详情" width="880" :destroy-on-close="true">
      <a-spin :spinning="detailLoading">
        <template v-if="detail">
          <div class="detail-head">
            <div>
              <div class="detail-title">{{ detail.name }}</div>
              <div class="muted">{{ detail.hostname }} · {{ detail.os }}/{{ detail.arch }} · {{ detail.client_id }}</div>
              <div class="muted">凭据创建人：{{ detail.registered_by || '-' }}</div>
            </div>
            <div class="policy-controls">
              <label>
                <span>治理方式</span>
                <a-select :value="currentGovernance" style="width: 170px" @change="saveGovernance">
                  <a-select-option value="registry">客户端安全治理</a-select-option>
                  <a-select-option value="strict">Agent 强授权</a-select-option>
                </a-select>
              </label>
              <label>
                <span>处置策略</span>
                <a-select :value="currentPolicy" style="width: 150px" @change="savePolicy">
                  <a-select-option value="audit">只审计</a-select-option>
                  <a-select-option value="repair">自动恢复</a-select-option>
                  <a-select-option value="block">隔离阻断</a-select-option>
                </a-select>
              </label>
              <a-button class="detail-refresh" @click="refreshDetail">刷新状态</a-button>
            </div>
          </div>

          <a-alert
            type="info"
            show-icon
            class="policy-note"
            :message="policyDescription(currentPolicy)"
            :description="governanceDescription(currentGovernance)"
          />

          <div class="section-title">本机 Agent</div>
          <a-table :columns="agentColumns" :data-source="detail.agents || []" row-key="agent_type" size="small" :pagination="false" :expandable="agentTableExpandable">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <strong>{{ agentLabel(record.agent_type, record) }}</strong>
                <div class="muted">{{ record.version || '未获取版本' }}</div>
              </template>
              <template v-else-if="column.key === 'capability'">
                <a-tag :color="record.skill_management_supported ? 'green' : 'default'">
                  {{ record.skill_management_supported ? '支持 Skill 管理' : '仅识别客户端' }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'binding'">
                <a-select
                  v-if="currentGovernance === 'strict'"
                  :value="record.managed_agent_id || undefined"
                  allow-clear
                  show-search
                  placeholder="绑定平台智能体"
                  style="width: 220px"
                  :loading="actionKey === `bind:${record.agent_type}`"
                  :disabled="actionKey === `bind:${record.agent_type}`"
                  @change="value => saveBinding(record, value)"
                >
                  <a-select-option v-for="agent in matchingAgents(record.agent_type)" :key="agent.agent_id" :value="agent.agent_id">
                    {{ agent.name }}（{{ agent.agent_id }}）
                  </a-select-option>
                </a-select>
                <span v-else class="muted">无需绑定，按平台 Skill 状态与签名治理</span>
              </template>
              <template v-else-if="column.key === 'skills'">{{ record.skills?.length || 0 }}</template>
              <template v-else-if="column.key === 'action'">
                <a-button
                  type="link"
                  :disabled="!record.skill_management_supported || (currentGovernance === 'strict' && !record.managed_agent_id)"
                  @click="openInstall(record)"
                >下发 Skill</a-button>
              </template>
            </template>
            <template #expandedRowRender="{ record: agentRecord }">
              <a-table class="agent-skill-table" :columns="skillColumns" :data-source="agentSkills(agentRecord)" :row-key="row => `${row.agent_type}:${row.path}`" size="small" :pagination="false">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'name'">
                    <strong>{{ record.name }}</strong>
                    <div class="muted ellipsis">{{ record.path }}</div>
                  </template>
                  <template v-else-if="column.key === 'status'"><a-tag>{{ record.status }}</a-tag></template>
                  <template v-else-if="column.key === 'action'">
                    <a-space>
                      <a-button
                        type="link"
                        :loading="actionKey === `repair:${record.agent_type}:${record.skill_id}`"
                        :disabled="!record.skill_id"
                        @click="repairSkill(record)"
                      >修复</a-button>
                      <a-popconfirm title="确认从该 Agent 移除这个 Skill？" @confirm="removeSkill(record)">
                        <a-button
                          type="link"
                          danger
                          :loading="actionKey === `remove:${record.agent_type}:${record.skill_id || record.name}`"
                        >移除</a-button>
                      </a-popconfirm>
                    </a-space>
                  </template>
                </template>
              </a-table>
            </template>
          </a-table>

          <div class="section-title">最近任务</div>
          <a-table :columns="taskColumns" :data-source="detail.tasks || []" row-key="id" size="small" :pagination="{ pageSize: 6 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <strong>{{ taskLabel(record) }}</strong>
                <div v-if="taskSkillName(record)" class="muted">{{ taskSkillName(record) }} · {{ agentLabel(record.payload?.agent_type) }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="taskColor(record.status)">{{ taskStatusLabel(record.status) }}</a-tag>
              </template>
              <template v-else-if="column.key === 'created'">{{ formatTime(record.created_at) }}</template>
              <template v-else-if="column.key === 'error'">{{ record.error || '-' }}</template>
              <template v-else-if="column.key === 'action'">
                <a-space>
                  <a-button v-if="['pending', 'running'].includes(record.status)" type="link" danger @click="cancelTask(record)">取消</a-button>
                  <a-button v-if="['failed', 'cancelled'].includes(record.status)" type="link" @click="retryTask(record)">重试</a-button>
                </a-space>
              </template>
            </template>
          </a-table>

          <div class="section-title">最近事件</div>
          <a-timeline v-if="detail.events?.length">
            <a-timeline-item v-for="event in detail.events.slice(0, eventVisibleCount)" :key="event.id" :color="eventColor(event.event_type)">
              <strong>{{ eventLabel(event.event_type) }}</strong>
              <span v-if="event.skill_name"> · {{ event.skill_name }}</span>
              <div class="muted">{{ formatTime(event.created_at) }}</div>
            </a-timeline-item>
          </a-timeline>
          <a-empty v-else description="暂无客户端事件" />
          <div v-if="detail.events?.length > eventVisibleCount" class="event-more">
            <a-button type="link" @click="eventVisibleCount += 10">查看更多</a-button>
          </div>
        </template>
      </a-spin>
    </a-drawer>

    <a-modal v-model:open="installVisible" title="下发 Skill 到客户端" ok-text="下发安装" @ok="createInstall" :confirm-loading="submitting">
      <a-form layout="vertical">
        <a-form-item label="目标 Agent">
          <a-input :value="agentLabel(installForm.agent_type)" disabled />
        </a-form-item>
        <a-form-item label="Skill" required>
          <a-select v-model:value="installForm.skill_id" show-search option-filter-prop="label" :loading="skillsLoading" :placeholder="currentGovernance === 'strict' ? '选择该智能体允许使用的 Skill' : '选择已批准的 Skill'" not-found-content="没有其他可安装的 Skill">
            <a-select-option v-for="skill in installableSkills" :key="skill.skill_id" :value="skill.skill_id" :label="skill.name">
              {{ skill.name }}<span class="skill-option-time">提交于 {{ formatTime(skill.submitted_at) }}</span>
            </a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="installGuideVisible" title="安装 Agent Manager Client" :footer="null" width="620">
      <a-steps direction="vertical" size="small" :current="0">
        <a-step title="下载当前系统版本">
          <template #description>
            <a-space wrap>
              <a-select v-model:value="selectedPlatform" placeholder="选择系统与架构" style="width: 300px">
                <a-select-option v-for="item in downloadPlatforms" :key="item.key" :value="item.key">{{ item.platform_label }} · {{ item.version }}</a-select-option>
              </a-select>
              <a-button type="primary" :disabled="!selectedPlatform" :loading="clientDownloading" @click="downloadSelectedClient">
                {{ clientDownloading ? '正在下载' : '下载' }}
              </a-button>
            </a-space>
            <div v-if="clientDownloading || clientDownloadProgress > 0" class="client-download-progress">
              <a-progress :percent="clientDownloadProgress" :status="clientDownloadStatus" />
              <span>{{ clientDownloadDetail }}</span>
            </div>
          </template>
        </a-step>
        <a-step title="创建客户端接入凭证" description="前往“统一凭证中心”，类型选择“客户端接入凭证”，保留默认 client:* 权限。" />
        <a-step title="连接并接管" description="打开桌面客户端，填写平台地址与凭证；发现本机 Agent 后勾选需要治理的 Skill。" />
        <a-step title="启用后台巡检" description="完成接管后启用后台服务，客户端会持续校验签名并上报异常。" />
      </a-steps>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import {
  bindClientAgent,
  cancelClientTask,
  createClientTask,
  downloadClientBinary,
  getClientDetail,
  listAgents,
  listClients,
  listClientDownloads,
  listSkills,
  retryClientTask,
  updateClientPolicy,
} from '../api'

const loading = ref(false)
const detailLoading = ref(false)
const submitting = ref(false)
const actionKey = ref('')
const eventVisibleCount = ref(10)
const detailVisible = ref(false)
const installVisible = ref(false)
const installGuideVisible = ref(false)
const clients = ref([])
const agents = ref([])
const skills = ref([])
const skillsLoading = ref(false)
const targetInstalledSkills = ref([])
const detail = ref(null)
const currentPolicy = ref('audit')
const currentGovernance = ref('registry')
const installForm = reactive({ agent_type: '', managed_agent_id: '', skill_id: '' })
const downloadPlatforms = ref([])
const selectedPlatform = ref()
const clientDownloading = ref(false)
const clientDownloadProgress = ref(0)
const clientDownloadStatus = ref('active')
const clientDownloadDetail = ref('')

const columns = [
  { title: '客户端', key: 'client' },
  { title: '系统', key: 'platform', width: 170 },
  { title: 'Agent', key: 'agents', width: 160 },
  { title: 'Skill', key: 'skills', width: 90 },
  { title: '凭据创建人', key: 'credentialOwner', width: 120 },
  { title: '状态', key: 'status', width: 90 },
  { title: '最后心跳', key: 'lastSeen', width: 180 },
  { title: '操作', key: 'action', width: 80 },
]
const agentColumns = [
  { title: '客户端', key: 'type' },
  { title: '能力', key: 'capability', width: 150 },
  { title: '平台智能体', key: 'binding', width: 250 },
  { title: 'Skill', key: 'skills', width: 70 },
  { title: '操作', key: 'action', width: 100 },
]
const skillColumns = [
  { title: 'Skill', key: 'name' },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 130 },
]
const taskColumns = [
  { title: '任务', key: 'type', width: 240 },
  { title: '状态', key: 'status', width: 100 },
  { title: '创建时间', key: 'created', width: 180 },
  { title: '失败原因', key: 'error' },
  { title: '操作', key: 'action', width: 90 },
]

const onlineCount = computed(() => clients.value.filter(isOnline).length)
const agentCount = computed(() => clients.value.reduce((sum, item) => sum + (item.agents?.length || 0), 0))
const issueCount = computed(() => clients.value.reduce((sum, item) => sum + (item.issue_count || 0), 0))
const agentTableExpandable = { rowExpandable: record => Boolean(record.skills?.length) }
const selectedManagedAgent = computed(() => agents.value.find(agent => agent.agent_id === installForm.managed_agent_id))
const installableSkills = computed(() => {
  const installedIDs = new Set(targetInstalledSkills.value.map(skill => skill.skill_id).filter(Boolean))
  const installedNames = new Set(targetInstalledSkills.value.map(skill => skill.name).filter(Boolean))
  const available = skills.value.filter(skill => !installedIDs.has(skill.skill_id) && !installedNames.has(skill.name))
  if (currentGovernance.value !== 'strict') return available
  const allowed = new Set(selectedManagedAgent.value?.skill_names || [])
  return available.filter(skill => allowed.has(skill.skill_id) || allowed.has(skill.name))
})

const loadClients = async () => {
  loading.value = true
  try {
    clients.value = await listClients()
  } catch (error) {
    message.error(error.response?.data?.detail || '获取客户端列表失败')
  } finally {
    loading.value = false
  }
}
const openDetail = async (record) => {
  eventVisibleCount.value = 10
  detailVisible.value = true
  detailLoading.value = true
  try {
    detail.value = await getClientDetail(record.client_id)
    currentPolicy.value = detail.value.policy_mode || 'audit'
    currentGovernance.value = detail.value.governance_mode || 'registry'
  } finally {
    detailLoading.value = false
  }
}
const refreshDetail = async () => {
  if (!detail.value?.client_id) return
  detail.value = await getClientDetail(detail.value.client_id)
  currentPolicy.value = detail.value.policy_mode || 'audit'
  currentGovernance.value = detail.value.governance_mode || 'registry'
}
const watchTask = async taskId => {
  for (let attempt = 0; attempt < 15 && detailVisible.value; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 2000))
    await refreshDetail()
    const status = detail.value.tasks?.find(task => task.id === taskId)?.status
    if (status && !['pending', 'running'].includes(status)) return
  }
}
const savePolicy = async (mode) => {
  await updateClientPolicy(detail.value.client_id, { mode })
  currentPolicy.value = mode
  detail.value.policy_mode = mode
  await refreshDetail()
  message.success('处置策略已更新，等待客户端同步')
}
const saveGovernance = async (governanceMode) => {
  await updateClientPolicy(detail.value.client_id, { governance_mode: governanceMode })
  currentGovernance.value = governanceMode
  detail.value.governance_mode = governanceMode
  await refreshDetail()
  message.success('治理方式已更新，等待客户端同步')
}
const saveBinding = async (record, managedAgentId) => {
  actionKey.value = `bind:${record.agent_type}`
  try {
    await bindClientAgent(detail.value.client_id, record.agent_type, { managed_agent_id: managedAgentId || null })
    await refreshDetail()
    message.success('Agent 映射已更新')
  } finally {
    actionKey.value = ''
  }
}
const openInstall = async (record) => {
  Object.assign(installForm, { agent_type: record.agent_type, managed_agent_id: record.managed_agent_id, skill_id: '' })
  targetInstalledSkills.value = record.skills || []
  installVisible.value = true
  if (skills.value.length) return
  skillsLoading.value = true
  try {
    const rows = await listSkills({ status: 'APPROVED', page: 1, page_size: 100, sort_by: 'submitted_at', sort_order: 'desc' })
    skills.value = Array.isArray(rows.items) ? rows.items : rows
  } finally {
    skillsLoading.value = false
  }
}
const createInstall = async () => {
  if (!installForm.skill_id) {
    message.warning('请选择 Skill')
    return
  }
  submitting.value = true
  try {
    const task = await createClientTask(detail.value.client_id, {
      task_type: 'install_skill',
      payload: { ...installForm },
    })
    installVisible.value = false
    await refreshDetail()
    message.success('安装任务已下发，等待客户端执行')
    watchTask(task.id).catch(() => {})
  } finally {
    submitting.value = false
  }
}
const removeSkill = async (record) => {
  actionKey.value = `remove:${record.agent_type}:${record.skill_id || record.name}`
  const agent = detail.value.agents.find(item => item.agent_type === record.agent_type)
  try {
    const task = await createClientTask(detail.value.client_id, {
      task_type: 'remove_skill',
      payload: {
        agent_type: record.agent_type,
        managed_agent_id: agent?.managed_agent_id,
        skill_id: record.skill_id || '',
        skill_name: record.name,
      },
    })
    await refreshDetail()
    message.success('移除任务已下发，等待客户端执行')
    watchTask(task.id).catch(() => {})
  } finally {
    actionKey.value = ''
  }
}
const repairSkill = async (record) => {
  const key = `repair:${record.agent_type}:${record.skill_id}`
  actionKey.value = key
  const agent = detail.value.agents.find(item => item.agent_type === record.agent_type)
  try {
    const task = await createClientTask(detail.value.client_id, {
      task_type: 'repair_skill',
      payload: {
        agent_type: record.agent_type,
        managed_agent_id: agent?.managed_agent_id,
        skill_id: record.skill_id,
      },
    })
    await refreshDetail()
    message.success('修复任务已下发，等待客户端执行')
    watchTask(task.id).catch(() => {})
  } finally {
    actionKey.value = ''
  }
}
const cancelTask = async (record) => {
  await cancelClientTask(detail.value.client_id, record.id)
  await refreshDetail()
  message.success('任务已取消')
}
const retryTask = async (record) => {
  await retryClientTask(detail.value.client_id, record.id)
  await refreshDetail()
  message.success('任务已重新进入队列')
}
const downloadErrorDetail = async error => {
  const data = error?.response?.data
  if (data instanceof Blob) {
    try {
      const payload = JSON.parse(await data.text())
      if (payload?.detail) return String(payload.detail)
    } catch {
      // Fall through to the regular network error message.
    }
  }
  return data?.detail || error?.message || '下载失败'
}
const downloadClient = async ({ key }) => {
  const release = downloadPlatforms.value.find(item => item.key === key)
  if (!release || clientDownloading.value) return
  clientDownloading.value = true
  clientDownloadProgress.value = 0
  clientDownloadStatus.value = 'active'
  clientDownloadDetail.value = '正在连接平台'
  try {
    const blob = await downloadClientBinary(key, event => {
      const loaded = Number(event.loaded || 0)
      const total = Number(event.total || release.size || 0)
      clientDownloadProgress.value = total > 0 ? Math.min(99, Math.round((loaded / total) * 100)) : 0
      clientDownloadDetail.value = total > 0
        ? `已接收 ${formatBytes(loaded)} / ${formatBytes(total)}`
        : `已接收 ${formatBytes(loaded)}`
    })
    if (!(blob instanceof Blob) || blob.size <= 0) {
      throw new Error('平台返回的安装包为空')
    }
    if (release.size && blob.size !== release.size) {
      throw new Error(`安装包接收不完整：应为 ${formatBytes(release.size)}，实际为 ${formatBytes(blob.size)}`)
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = release.filename || `agent-manager-client-${key}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60000)
    clientDownloadProgress.value = 100
    clientDownloadStatus.value = 'success'
    clientDownloadDetail.value = `已接收 ${formatBytes(blob.size)}，浏览器正在保存文件`
    message.success('客户端安装包下载完成')
  } catch (error) {
    clientDownloadStatus.value = 'exception'
    clientDownloadDetail.value = await downloadErrorDetail(error)
    message.error(`下载安装包失败：${clientDownloadDetail.value}`)
  } finally {
    clientDownloading.value = false
  }
}
const downloadSelectedClient = () => downloadClient({ key: selectedPlatform.value })

const managedAgentCount = record => record.agents?.filter(agent => agent.skill_management_supported).length || 0
const skillCount = record => record.agents?.reduce((sum, agent) => sum + (agent.skills?.length || 0), 0) || 0
const agentSkills = agent => (agent.skills || []).map(skill => ({ ...skill, agent_type: agent.agent_type }))
const taskSkillName = task => task.payload?.skill_name
  || (detail.value?.agents || []).flatMap(agent => agent.skills || []).find(skill => skill.skill_id === task.payload?.skill_id)?.name
  || skills.value.find(skill => skill.skill_id === task.payload?.skill_id)?.name
  || task.payload?.skill_id
  || ''
const isOnline = record => record.status === 'online'
const formatTime = value => {
  if (!value) return '-'
  const text = String(value)
  const utcValue = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`
  return new Date(utcValue).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
const formatBytes = value => {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
const agentKind = value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '').replace(/^claude$/, 'claudecode').replace(/^geminicli$/, 'gemini')
const matchingAgents = agentType => String(agentType || '').startsWith('custom-')
  ? agents.value
  : agents.value.filter(agent => agentKind(agent.channel) === agentKind(agentType))
const agentLabel = (value, record = null) => record?.capabilities?.display_name || ({
  'claude-code': 'Claude Code',
  codex: 'Codex',
  gemini: 'Gemini CLI',
  opencode: 'OpenCode',
  openclaw: 'OpenClaw',
  hermes: 'Hermes',
  'trae-cn': 'TRAE CN',
  trae: 'TRAE',
  cursor: 'Cursor',
  'global-skills': '通用 Skills',
  codebuddy: 'CodeBuddy',
  workbuddy: 'WorkBuddy',
}[value] || value)
const policyDescription = mode => ({
  audit: '只审计：发现修改后记录事件，不改动本地文件。',
  repair: '自动恢复：先记录异常，再恢复平台批准版本。',
  block: '隔离阻断：把异常内容移入隔离区，并从 Agent 的 Skill 入口移除。',
}[mode])
const governanceDescription = mode => ({
  registry: '客户端安全治理：只要 Skill 已在平台批准且内容签名一致，即可在本机 Agent 使用。',
  strict: 'Agent 强授权：除批准状态和签名外，还要求本机 Agent 绑定平台智能体，并校验允许使用的 Skill。',
}[mode])
const governanceShortLabel = mode => ({ registry: '安全治理', strict: '强授权' }[mode] || '安全治理')
const eventLabel = value => ({
  client_registered: '客户端注册',
  takeover_completed: '治理范围更新',
  unmanaged_skill_found: '发现未受管 Skill',
  unmanaged_skill_verified: '未受管 Skill 已通过平台校验',
  skill_installed: 'Skill 安装完成',
  skill_removed: 'Skill 已移除',
  skill_modified: '发现 Skill 修改',
  skill_repaired: '已恢复批准版本',
  skill_blocked: '已阻断异常 Skill',
  skill_quarantined: 'Skill 已移入隔离区',
  skill_quarantine_restored: 'Skill 已从隔离区恢复',
}[value] || value)
const eventColor = value => ['skill_blocked', 'skill_quarantined'].includes(value) ? 'red' : value === 'skill_modified' ? 'orange' : 'green'
const taskLabel = task => {
  if (task.task_type === 'rescan' && task.payload?.reason === 'policy_changed') return '同步处理策略'
  return ({
    install_skill: '下发 Skill',
    remove_skill: '移除 Skill',
    repair_skill: '修复 Skill',
    rescan: '同步客户端清单',
    sync_policy: '同步处理策略',
  }[task.task_type] || task.task_type)
}
const taskStatusLabel = value => ({ pending: '等待客户端执行', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }[value] || value)
const taskColor = value => ({ pending: 'default', running: 'blue', succeeded: 'green', failed: 'red', cancelled: 'default' }[value] || 'default')

onMounted(async () => {
  const [agentRows, downloads] = await Promise.all([
    listAgents(),
    listClientDownloads(),
    loadClients(),
  ])
  agents.value = agentRows || []
  downloadPlatforms.value = downloads.items || []
})
</script>

<style scoped>
.summary-row,
.table-card {
  margin-top: 16px;
}
.muted {
  color: #7a869a;
  font-size: 12px;
}
.inline-note {
  margin-left: 8px;
}
.client-download-progress {
  max-width: 470px;
  margin-top: 14px;
}
.client-download-progress span {
  display: block;
  margin-top: 3px;
  color: #7a869a;
  font-size: 12px;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.detail-title {
  color: #16324f;
  font-size: 20px;
  font-weight: 650;
}
.policy-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.policy-controls label > span {
  display: block;
  margin-bottom: 5px;
  color: #7a869a;
  font-size: 12px;
}
.detail-refresh {
  align-self: flex-end;
}
.skill-option-time {
  float: right;
  margin-left: 16px;
  color: #7a869a;
  font-size: 12px;
}
.policy-note {
  margin-top: 16px;
}
.section-title {
  border-left: 3px solid #1c6ea4;
  font-weight: 650;
  margin: 24px 0 12px;
  padding-left: 10px;
}
.event-more {
  margin-top: -8px;
  text-align: center;
}
.ellipsis {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
