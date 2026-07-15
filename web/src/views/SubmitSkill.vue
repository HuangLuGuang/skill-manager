<template>
  <div>
    <a-page-header title="提交技能" :sub-title="submitModeMeta.subtitle" />

    <a-card style="margin-top: 16px">
      <a-alert
        type="info"
        show-icon
        :message="submitModeMeta.message"
        :description="submitModeMeta.description"
        style="margin-bottom: 16px"
      />

      <a-tabs v-model:activeKey="submitMode">
        <a-tab-pane key="zip" tab="上传 ZIP">
          <a-form layout="vertical" @finish="prepareZipImport">
            <a-form-item label="Skill ZIP 包">
              <a-upload-dragger
                class="zip-dragger"
                accept=".zip,application/zip"
                :show-upload-list="false"
                :before-upload="handleBeforeUpload"
              >
                <p class="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p class="ant-upload-text">点击或拖拽 ZIP 文件到这里，选择后自动解析</p>
                <p class="ant-upload-hint">支持单个 ZIP 上传；如果压缩包里还包含一层 ZIP，系统会自动再解压一层后解析候选技能。</p>
              </a-upload-dragger>
              <div class="field-hint">{{ selectedFile ? `当前文件：${selectedFile.name}` : '尚未选择文件' }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button
                  type="primary"
                  :loading="loadingZipCandidates"
                  :disabled="submitting || loadingZipCandidates || !selectedFile"
                  @click="prepareZipImport"
                >
                  重新解析 ZIP
                </a-button>
                <a-button @click="resetZip" :disabled="submitting || loadingZipCandidates">重置</a-button>
              </a-space>
            </a-form-item>
            <a-form-item v-if="validUploadCandidates.length" label="选择目录">
              <a-select
                v-model:value="selectedUploadDirectories"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingZipCandidates"
                allow-clear
                placeholder="先选择要查看的目录，可多选"
                :options="uploadDirectorySelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">先选目录，再从目录中的 技能列表里多选要导入的项。</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllUploadDirectories" :disabled="!uploadDirectoryOptions.length">全选目录</a-button>
                <a-button size="small" @click="clearUploadDirectories" :disabled="!selectedUploadDirectories.length">全部清除</a-button>
              </a-space>
            </a-form-item>
            <a-form-item v-if="validUploadCandidates.length" label="选择要导入的技能">
              <a-select
                v-model:value="selectedUploadPaths"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingZipCandidates"
                allow-clear
                :placeholder="selectedUploadDirectories.length ? '从所选目录中多选要导入的技能' : '请先选择目录'"
                :options="uploadSkillSelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">本次 ZIP 导入会话：{{ uploadImportRootPath || '-' }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllUploadSkills" :disabled="!filteredUploadCandidates.length">全选当前目录技能</a-button>
                <a-button size="small" @click="clearUploadSkills" :disabled="!selectedUploadPaths.length">全部清除</a-button>
              </a-space>
            </a-form-item>
            <a-alert
              type="info"
              show-icon
              style="margin-bottom: 16px"
              :message="`当前提交人：${currentUsername}`"
              description="当前来源：local（上传 ZIP）"
            />
            <a-form-item>
              <a-space wrap>
                <a-tooltip :title="behavioralTooltip">
                  <span><a-checkbox v-model:checked="formState.useBehavioral">启动规则分析（默认已启动）</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="deepScanTooltip">
                  <span><a-checkbox v-model:checked="formState.useSkillspector" :disabled="!deepScanReadyForSubmit">启动深度扫描</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="sandboxTooltip">
                  <span><a-checkbox v-model:checked="formState.useSandbox" :disabled="!sandboxReadyForSubmit">启动 Sandbox</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="llmTooltip">
                  <span><a-checkbox v-model:checked="formState.useLlm" :disabled="!llmReadyForSubmit">启动 LLM 分析</a-checkbox></span>
                </a-tooltip>
                <a-tooltip title="强制重新扫描，不复用之前的扫描结果">
                  <span><a-checkbox v-model:checked="formState.noCache">禁用缓存</a-checkbox></span>
                </a-tooltip>
              </a-space>
            </a-form-item>
            <a-form-item>
              <a-space>
                <a-button
                  type="primary"
                  ghost
                  :loading="submitting"
                  :disabled="submitting || !uploadImportSessionId || !selectedUploadPaths.length"
                  @click="handleZipSubmit"
                >
                  提交所选技能
                </a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-tab-pane>

        <a-tab-pane v-if="showLocalImport" key="local" tab="本地目录导入">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button
              @click="fetchLocalCandidates"
              :loading="loadingLocalCandidates"
              :disabled="submitting || loadingLocalCandidates"
            >
              扫描导入目录
            </a-button>
            <span style="color: #8c8c8c">根目录：{{ importRootPath || '-' }}</span>
          </a-space>
          <a-form layout="vertical" @finish="handleLocalSubmit">
            <a-form-item v-if="localCandidates.length" label="选择目录">
              <a-select
                v-model:value="selectedLocalDirectories"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingLocalCandidates"
                allow-clear
                placeholder="先选择要查看的目录，可多选"
                :options="localDirectorySelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">先选目录，再从目录中的 技能列表里多选要导入的项。</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllLocalDirectories" :disabled="!localDirectoryOptions.length">全选目录</a-button>
                <a-button size="small" @click="clearLocalDirectories" :disabled="!selectedLocalDirectories.length">全部清除</a-button>
              </a-space>
            </a-form-item>
            <a-form-item label="选择要导入的技能">
              <a-select
                v-model:value="selectedLocalPaths"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingLocalCandidates"
                allow-clear
                :placeholder="selectedLocalDirectories.length ? '从所选目录中多选要导入的技能' : '请先选择目录'"
                :options="localSkillSelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">支持多选，提交后会批量进入后台分析。</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllLocalSkills" :disabled="!filteredLocalCandidates.length">全选当前目录技能</a-button>
                <a-button size="small" @click="clearLocalSkills" :disabled="!selectedLocalPaths.length">全部清除</a-button>
              </a-space>
            </a-form-item>
            <a-alert
              type="info"
              show-icon
              style="margin-bottom: 16px"
              :message="`当前提交人：${currentUsername}`"
              description="当前来源：local（本地目录导入）"
            />
            <a-form-item>
              <a-space wrap>
                <a-tooltip :title="behavioralTooltip">
                  <span><a-checkbox v-model:checked="formState.useBehavioral">启动规则分析（默认已启动）</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="deepScanTooltip">
                  <span><a-checkbox v-model:checked="formState.useSkillspector" :disabled="!deepScanReadyForSubmit">启动深度扫描</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="sandboxTooltip">
                  <span><a-checkbox v-model:checked="formState.useSandbox" :disabled="!sandboxReadyForSubmit">启动 Sandbox</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="llmTooltip">
                  <span><a-checkbox v-model:checked="formState.useLlm" :disabled="!llmReadyForSubmit">启动 LLM 分析</a-checkbox></span>
                </a-tooltip>
                <a-tooltip title="强制重新扫描，不复用之前的扫描结果">
                  <span><a-checkbox v-model:checked="formState.noCache">禁用缓存</a-checkbox></span>
                </a-tooltip>
              </a-space>
            </a-form-item>
            <a-form-item>
              <a-space>
                <a-button
                  type="primary"
                  :loading="submitting"
                  :disabled="submitting || !selectedLocalPaths.length"
                  @click="handleLocalSubmit"
                >
                  导入所选技能
                </a-button>
                <a-button @click="resetLocalImport" :disabled="submitting">清空选择</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-tab-pane>

        <a-tab-pane key="scanner" tab="Skill 扫描器">
          <ScannerAccess embedded />
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <a-card v-if="submitResults.length" title="提交结果" style="margin-top: 16px">
      <a-alert
        v-if="submitResults.some((item) => item.status === 'PENDING')"
        style="margin-bottom: 16px"
        type="info"
        show-icon
        message="后台分析中"
        description="技能已经入库，服务端正在后台执行扫描、LLM、规则分析和 Sandbox。列表页会显示最新状态。"
      />
      <a-table
        :data-source="submitResults"
        :columns="resultColumns"
        row-key="skill_id"
        :pagination="false"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)" :title="statusTitle(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'risk_level'">
            <a-tag v-if="record.status === 'PENDING'" color="default">-</a-tag>
            <a-tag v-else-if="record.risk_level === 'malicious'" color="red" title="恶意">malicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange" title="可疑">suspicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green" title="安全">benign</a-tag>
            <a-tag v-else color="default">-</a-tag>
          </template>
          <template v-else-if="column.key === 'sandbox'">
            <a-space wrap>
              <a-tag v-if="record.sandbox_runtime" color="blue">{{ record.sandbox_runtime }}</a-tag>
              <a-tag v-if="record.sandbox_required_by_policy" color="orange">策略强制</a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-button type="link" style="padding: 0" @click="goToDetail(record.skill_id)">查看详情</a-button>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup>
import { computed, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { InboxOutlined } from '@ant-design/icons-vue'
import ScannerAccess from './ScannerAccess.vue'

import {
  getLocalImportCandidates,
  getSkillDetail,
  getAgentManagerSystemStatus,
  prepareUploadZip,
  submitLocalSkills,
  submitUploadSelected,
} from '../api'

const router = useRouter()
const submitMode = ref('zip')
const showLocalImport = false
const submitting = ref(false)
const loadingSystemStatus = ref(false)
const loadingLocalCandidates = ref(false)
const loadingZipCandidates = ref(false)
const selectedFile = ref(null)
const submitResults = ref([])
const managerStatus = ref({})
const pollingTimer = ref(null)
const importRootPath = ref('')
const localCandidates = ref([])
const selectedLocalDirectories = ref([])
const selectedLocalPaths = ref([])
const uploadImportSessionId = ref('')
const uploadImportRootPath = ref('')
const uploadCandidates = ref([])
const selectedUploadDirectories = ref([])
const selectedUploadPaths = ref([])
const currentUsername = localStorage.getItem('username') || 'admin'

const formState = reactive({
  useBehavioral: true,
  useSkillspector: false,
  useSandbox: false,
  useLlm: false,
  noCache: false,
})

const submitModeMetaMap = {
  zip: {
    subtitle: '上传 ZIP 包并选择要提交的 Skill',
    message: 'ZIP 上传说明',
    description: '拖拽或选择 ZIP 后会自动解析候选 Skill；如果压缩包里包含多个 Skill，可以先选目录再多选提交。提交后先进入 PENDING，后台继续完成规则分析、深度扫描、Sandbox 和 LLM 分析。',
  },
  local: {
    subtitle: '从服务端本地导入目录选择 Skill',
    message: '本地目录导入说明',
    description: '本地目录导入仅用于服务端已配置导入根目录的场景。一般客户侧批量扫描请使用“Skill 扫描器”tab，通过 CLI 扫描本地 skills 目录并上传。',
  },
  scanner: {
    subtitle: '下载 CLI 扫描器，批量扫描本地 skills 目录并上传平台治理',
    message: 'Skill 扫描器说明',
    description: '适合命令行、服务器和 CI 场景。先在“凭证管理”创建 Scanner 接入凭证，再用 CLI 扫描本地 skills 目录；上传后在 Skill 列表查看状态和详情。',
  },
}
const submitModeMeta = computed(() => submitModeMetaMap[submitMode.value] || submitModeMetaMap.zip)

const getCandidateDirectory = (item) => {
  const relativePath = item?.relative_path || ''
  if (!relativePath.includes('/')) return '.'
  return relativePath.split('/').slice(0, -1).join('/')
}

const localDirectoryOptions = computed(() => {
  const counts = new Map()
  for (const item of localCandidates.value) {
    const directory = getCandidateDirectory(item)
    counts.set(directory, (counts.get(directory) || 0) + 1)
  }
  return Array.from(counts.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([directory, count]) => ({
      value: directory,
      label: directory === '.' ? '导入根目录' : directory,
      count,
    }))
})

const localDirectorySelectOptions = computed(() =>
  localDirectoryOptions.value.map((item) => ({
    value: item.value,
    label: `${item.label} (${item.count} 个 skill)`,
  })),
)

const filteredLocalCandidates = computed(() => {
  if (!selectedLocalDirectories.value.length) return []
  return localCandidates.value.filter((item) => selectedLocalDirectories.value.includes(getCandidateDirectory(item)))
})

const localSkillSelectOptions = computed(() =>
  filteredLocalCandidates.value.map((item) => ({
    value: item.path,
    label: item.description
      ? `${item.name} · ${item.relative_path} · ${item.description}`
      : `${item.name} · ${item.relative_path}`,
  })),
)

const getTopLevelDirectory = (item) => {
  const relativePath = item?.relative_path || ''
  const firstSegment = relativePath.split('/').filter(Boolean)[0]
  return firstSegment || '.'
}

const uploadDirectoryOptions = computed(() => {
  const counts = new Map()
  for (const item of validUploadCandidates.value) {
    const directory = getTopLevelDirectory(item)
    counts.set(directory, (counts.get(directory) || 0) + 1)
  }
  return Array.from(counts.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([directory, count]) => ({
      value: directory,
      label: directory === '.' ? '压缩包根目录' : directory,
      count,
    }))
})

const validUploadCandidates = computed(() => uploadCandidates.value.filter((item) => !item.error))
const invalidUploadCandidates = computed(() => uploadCandidates.value.filter((item) => item.error))

const uploadDirectorySelectOptions = computed(() =>
  uploadDirectoryOptions.value.map((item) => ({
    value: item.value,
    label: `${item.label} (${item.count} 个 skill)`,
  })),
)

const filteredUploadCandidates = computed(() => {
  if (!selectedUploadDirectories.value.length) return []
  return validUploadCandidates.value.filter((item) => selectedUploadDirectories.value.includes(getTopLevelDirectory(item)))
})

const uploadSkillSelectOptions = computed(() =>
  filteredUploadCandidates.value.map((item) => ({
    value: item.path,
    label: item.description
      ? `${item.name} · ${item.relative_path} · ${item.description}`
      : `${item.name} · ${item.relative_path}`,
  })),
)

const allUploadDirectoryValues = computed(() => uploadDirectoryOptions.value.map((item) => item.value))
const allFilteredUploadPaths = computed(() => filteredUploadCandidates.value.map((item) => item.path))

const allLocalDirectoryValues = computed(() => localDirectoryOptions.value.map((item) => item.value))
const allFilteredLocalPaths = computed(() => filteredLocalCandidates.value.map((item) => item.path))

const resultColumns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '状态', dataIndex: 'status', key: 'status', width: 120 },
  { title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 120 },
  { title: '发现项', dataIndex: 'findings_count', key: 'findings_count', width: 100 },
  { title: 'Sandbox', key: 'sandbox', width: 180 },
  { title: '说明', dataIndex: 'message', key: 'message' },
  { title: '操作', key: 'action', width: 100 },
]

const llmEnabledInSystem = computed(() => Boolean(managerStatus.value?.llm_enabled))
const llmReadyForSubmit = computed(() => Boolean(managerStatus.value?.llm_enabled && managerStatus.value?.llm_model))
const sandboxEnabledInSystem = computed(() => Boolean(managerStatus.value?.sandbox_enabled))
const sandboxReadyForSubmit = computed(() => Boolean(managerStatus.value?.sandbox_enabled && managerStatus.value?.sandbox_available))
const deepScanReadyForSubmit = computed(() => Boolean(managerStatus.value?.skillspector_available))
const llmTooltip = computed(() => {
  if (loadingSystemStatus.value) return '正在读取系统设置中的 LLM 状态'
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) return '尚未获取系统设置，请稍后重试'
  if (!llmEnabledInSystem.value) return '系统设置里没有启用 LLM 分析，所以这里不能勾选'
  if (!managerStatus.value?.llm_model) return '策略配置里尚未选择模型网关模型，所以这里不能勾选'
  return `启用后会使用策略配置中选择的模型：${managerStatus.value.llm_model}`
})
const behavioralTooltip = '默认已启动。会额外扫描 scripts、references、prompts 等目录中的文本代码文件，检测命令执行、敏感文件访问、动态执行等可疑模式'
const deepScanTooltip = computed(() => {
  if (loadingSystemStatus.value) return '正在读取深度扫描状态'
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) return '尚未获取系统状态，请稍后重试'
  if (!managerStatus.value?.skillspector_available) return '当前运行环境不可用，请先检查服务安装状态'
  if (llmReadyForSubmit.value) return '启用后会执行深度扫描，并自动使用当前 LLM 配置增强分析'
  return '启用后会执行深度扫描；当前未配置 LLM，因此只运行基础深度扫描'
})
const sandboxTooltip = computed(() => {
  if (loadingSystemStatus.value) return '正在读取系统设置中的 Sandbox 状态'
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) return '尚未获取系统设置，请稍后重试'
  if (!sandboxEnabledInSystem.value) return '系统设置里已经关闭 Sandbox，所以这里不能勾选'
  if (!managerStatus.value?.sandbox_available) return 'Sandbox 已启用但当前运行环境不可用，请先检查系统设置'
  return '启用后会尝试在 Docker 沙箱或远程隔离执行服务中执行一个受控 probe，用于观察 skill 运行时行为'
})
const effectiveUseSandbox = () => Boolean(sandboxReadyForSubmit.value && formState.useSandbox)

const fetchSystemStatus = async () => {
  loadingSystemStatus.value = true
  try {
    managerStatus.value = await getAgentManagerSystemStatus()
    if (!llmReadyForSubmit.value) formState.useLlm = false
    if (!sandboxReadyForSubmit.value) formState.useSandbox = false
    if (!deepScanReadyForSubmit.value) formState.useSkillspector = false
  } catch (_error) {
    managerStatus.value = {}
    formState.useLlm = false
    formState.useSandbox = false
    formState.useSkillspector = false
  } finally {
    loadingSystemStatus.value = false
  }
}

const fetchLocalCandidates = async () => {
  if (loadingLocalCandidates.value || submitting.value) return
  loadingLocalCandidates.value = true
  try {
    const data = await getLocalImportCandidates()
    importRootPath.value = data.root_path || ''
    localCandidates.value = data.items || []
    selectedLocalDirectories.value = localDirectoryOptions.value.length === 1 ? [localDirectoryOptions.value[0].value] : []
    selectedLocalPaths.value = localCandidates.value.length === 1 ? [localCandidates.value[0].path] : []
  } catch (error) {
    message.error(error.response?.data?.detail || '扫描导入目录失败')
  } finally {
    loadingLocalCandidates.value = false
  }
}

const handleBeforeUpload = (file) => {
  const isZip = file.type === 'application/zip' || file.name.toLowerCase().endsWith('.zip')
  if (!isZip) {
    message.error('只能上传 ZIP 文件')
    return false
  }
  selectedFile.value = file
  clearZipAnalysis()
  window.setTimeout(() => {
    prepareZipImport()
  }, 0)
  return false
}

const stopPolling = () => {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

const startPolling = () => {
  stopPolling()
  if (!submitResults.value.some((item) => item.status === 'PENDING')) return
  pollingTimer.value = setInterval(async () => {
    try {
      const updated = await Promise.all(
        submitResults.value.map(async (item) => {
          if (item.status !== 'PENDING') return item
          const detail = await getSkillDetail(item.skill_id)
          return {
            ...item,
            name: detail.name,
            status: detail.status,
            risk_level: detail.risk_level,
            findings_count: detail.vetting?.findings_count || 0,
            sandbox_triggered: Boolean(detail.vetting?.sandbox_triggered),
            sandbox_required_by_policy: Boolean(detail.vetting?.sandbox_required_by_policy),
            sandbox_runtime: detail.vetting?.sandbox_runtime || null,
            message: detail.status === 'PENDING' ? '已提交，后台分析中。请在 Skill 列表查看状态变化。' : '后台分析已完成。',
          }
        }),
      )
      submitResults.value = updated
      if (!updated.some((item) => item.status === 'PENDING')) stopPolling()
    } catch (_error) {
      // ignore transient polling errors
    }
  }, 3000)
}

const clearZipAnalysis = () => {
  uploadImportSessionId.value = ''
  uploadImportRootPath.value = ''
  uploadCandidates.value = []
  selectedUploadDirectories.value = []
  selectedUploadPaths.value = []
}

const resetZip = () => {
  selectedFile.value = null
  clearZipAnalysis()
}

const clearSubmittedZipSelection = () => {
  selectedFile.value = null
  clearZipAnalysis()
}

const resetAll = () => {
  stopPolling()
  selectedFile.value = null
  submitResults.value = []
  resetLocalImport()
}

const resetLocalImport = () => {
  selectedLocalDirectories.value = []
  selectedLocalPaths.value = []
}

const clearSubmittedLocalSelection = () => {
  selectedLocalDirectories.value = []
  selectedLocalPaths.value = []
}

const selectAllLocalDirectories = () => {
  selectedLocalDirectories.value = [...allLocalDirectoryValues.value]
}

const clearLocalDirectories = () => {
  selectedLocalDirectories.value = []
}

const selectAllLocalSkills = () => {
  selectedLocalPaths.value = [...allFilteredLocalPaths.value]
}

const clearLocalSkills = () => {
  selectedLocalPaths.value = []
}

const handleZipSubmit = async () => {
  if (submitting.value) return
  if (!selectedFile.value) {
    message.warning('请先选择 skill ZIP 文件')
    return
  }
  if (!uploadImportSessionId.value) {
    message.warning('请先解析 ZIP 包')
    return
  }
  if (!selectedUploadDirectories.value.length) {
    message.warning('请先选择要导入的目录')
    return
  }
  if (!selectedUploadPaths.value.length) {
    message.warning('请先选择要导入的技能')
    return
  }
  submitting.value = true
  try {
    const result = await submitUploadSelected({
      session_id: uploadImportSessionId.value,
      paths: selectedUploadPaths.value,
      author: currentUsername,
      origin: 'local',
      use_behavioral: formState.useBehavioral,
      use_skillspector: formState.useSkillspector,
      use_sandbox: effectiveUseSandbox(),
      use_llm: formState.useLlm,
      no_cache: formState.noCache,
    })
    submitResults.value = result.results || []
    clearSubmittedZipSelection()
    message.success(`已提交 ${submitResults.value.length} 个 skills`)
    startPolling()
  } catch (error) {
    message.error(error.response?.data?.detail || 'ZIP 导入失败')
  } finally {
    submitting.value = false
  }
}

const prepareZipImport = async () => {
  if (loadingZipCandidates.value || submitting.value) return
  if (!selectedFile.value) {
    message.warning('请先选择 skill ZIP 文件')
    return
  }
  const formData = new FormData()
  formData.append('file', selectedFile.value)
  clearZipAnalysis()
  loadingZipCandidates.value = true
  try {
    const result = await prepareUploadZip(formData)
    uploadImportSessionId.value = result.session_id
    uploadImportRootPath.value = result.root_path
    uploadCandidates.value = result.items || []
    selectedUploadDirectories.value = uploadDirectoryOptions.value.length === 1 ? [uploadDirectoryOptions.value[0].value] : []
    selectedUploadPaths.value = validUploadCandidates.value.length === 1 ? [validUploadCandidates.value[0].path] : []
    if (invalidUploadCandidates.value.length) {
      Modal.warning({
        title: '部分 Skill 解析失败，已跳过',
        content: h('div', invalidUploadCandidates.value.map((item) => {
          const directory = item.relative_path && item.relative_path !== '.' ? `${item.relative_path} 目录` : '压缩包根目录'
          return h('div', { style: 'margin-bottom: 8px' }, `${directory}解析失败，${item.error}`)
        })),
        okText: '知道了',
      })
    }
    if (!validUploadCandidates.value.length) {
      message.warning('ZIP 解析完成，但没有识别到可导入的 skill 目录')
      return
    }
    message.success(`ZIP 解析完成，识别到 ${validUploadCandidates.value.length} 个可导入 Skill`)
  } catch (error) {
    message.error(error.response?.data?.detail || 'ZIP 解析失败')
  } finally {
    loadingZipCandidates.value = false
  }
}

const selectAllUploadDirectories = () => {
  selectedUploadDirectories.value = [...allUploadDirectoryValues.value]
}

const clearUploadDirectories = () => {
  selectedUploadDirectories.value = []
}

const selectAllUploadSkills = () => {
  selectedUploadPaths.value = [...allFilteredUploadPaths.value]
}

const clearUploadSkills = () => {
  selectedUploadPaths.value = []
}

const handleLocalSubmit = async () => {
  if (submitting.value) return
  if (!selectedLocalDirectories.value.length) {
    message.warning('请先选择要导入的目录')
    return
  }
  if (!selectedLocalPaths.value.length) {
    message.warning('请先多选要导入的技能s')
    return
  }
  submitting.value = true
  try {
    const result = await submitLocalSkills({
      paths: selectedLocalPaths.value,
      author: currentUsername,
      origin: 'local',
      use_behavioral: formState.useBehavioral,
      use_skillspector: formState.useSkillspector,
      use_sandbox: effectiveUseSandbox(),
      use_llm: formState.useLlm,
      no_cache: formState.noCache,
    })
    submitResults.value = result.results || []
    clearSubmittedLocalSelection()
    message.success(`已提交 ${submitResults.value.length} 个 skills`)
    startPolling()
  } catch (error) {
    message.error(error.response?.data?.detail || '本地目录导入失败')
  } finally {
    submitting.value = false
  }
}

watch(selectedLocalDirectories, (directories) => {
  if (!directories.length) {
    selectedLocalPaths.value = []
    return
  }
  const allowed = new Set(filteredLocalCandidates.value.map((item) => item.path))
  selectedLocalPaths.value = selectedLocalPaths.value.filter((path) => allowed.has(path))
})

watch(selectedUploadDirectories, (directories) => {
  if (!directories.length) {
    selectedUploadPaths.value = []
    return
  }
  const allowed = new Set(filteredUploadCandidates.value.map((item) => item.path))
  selectedUploadPaths.value = selectedUploadPaths.value.filter((path) => allowed.has(path))
})

const goToDetail = (skillId) => {
  if (!skillId) return
  router.push(`/skills/${skillId}`)
}

const statusColor = (value) => ({
  PENDING: 'gold',
  VETTED: 'orange',
  APPROVED: 'green',
  DEPLOYED: 'blue',
  REJECTED: 'red',
  RETIRED: 'default',
}[value] || 'default')

const statusTitle = (value) => ({
  PENDING: '分析中',
  VETTED: '待审核',
  APPROVED: '已批准',
  DEPLOYED: '已部署',
  REJECTED: '已拒绝',
  RETIRED: '已退役',
}[value] || '未知')

const riskColor = (value) => ({
  benign: 'green',
  suspicious: 'orange',
  malicious: 'red',
}[value] || 'default')

onMounted(async () => {
  await fetchSystemStatus()
  await fetchLocalCandidates()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.field-hint {
  margin-top: 8px;
  color: #8c8c8c;
  font-size: 12px;
}

.zip-dragger {
  background: #fafcff;
}

.remote-import-input :deep(.ant-input-affix-wrapper .ant-input-clear-icon),
.remote-import-select :deep(.ant-select-clear) {
  top: 50%;
  inset-inline-end: 11px;
  transform: translateY(-50%);
}

.remote-import-select :deep(.ant-select-selector) {
  align-items: center;
}

.remote-import-select :deep(.ant-select-selection-overflow) {
  align-items: center;
}

.remote-import-select :deep(.ant-select-selection-item) {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
}

.remote-import-select :deep(.ant-select-selection-item-content) {
  display: inline-flex;
  align-items: center;
  line-height: 1.2;
}

.remote-import-select :deep(.ant-select-selection-item-remove) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-inline-start: 6px;
  line-height: 1;
}

.remote-import-select :deep(.ant-select-selection-search) {
  display: inline-flex;
  align-items: center;
}
</style>
