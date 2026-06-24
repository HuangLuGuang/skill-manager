<template>
  <div>
    <a-page-header title="提交技能" sub-title="支持 ZIP 上传、远程压缩包/GitHub 仓库导入和 ClawHub 导入" />

    <a-card style="margin-top: 16px">
      <a-alert
        type="info"
        show-icon
        message="提交说明"
        description="你可以上传 ZIP，或填写 ZIP 下载地址 / GitHub 仓库地址先下载候选技能，再多选提交。ZIP 选择或拖拽后会自动解析；来源会根据导入方式自动填充，提交后会先进入 PENDING，再由后台继续完成扫描、LLM、规则分析和 Sandbox。"
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
            <a-form-item v-if="uploadCandidates.length" label="选择目录">
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
            <a-form-item v-if="uploadCandidates.length" label="选择要导入的技能">
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

        <a-tab-pane key="url" tab="网络下载导入">
          <a-form layout="vertical" @finish="handleRemoteFormFinish">
            <a-form-item label="下载地址">
              <a-input v-model:value="downloadUrl" class="remote-import-input" allow-clear placeholder="https://example.com/skill.zip 或 https://github.com/org/repo" />
              <div class="field-hint">支持直接填 ZIP 下载地址，也支持 GitHub 仓库地址；如果压缩包里包含多个 skill，会先解析候选目录供你多选。</div>
            </a-form-item>
            <a-form-item v-if="remoteCandidates.length" label="选择目录">
              <a-select
                v-model:value="selectedRemoteDirectories"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingRemoteCandidates"
                allow-clear
                placeholder="先选择要查看的目录，可多选"
                :options="remoteDirectorySelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">先选目录，再从目录中的 技能列表里多选要导入的项。</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllRemoteDirectories" :disabled="!remoteDirectoryOptions.length">全选目录</a-button>
                <a-button size="small" @click="clearRemoteDirectories" :disabled="!selectedRemoteDirectories.length">全部清除</a-button>
              </a-space>
            </a-form-item>
            <a-form-item v-if="remoteCandidates.length" label="选择要导入的技能">
              <a-select
                v-model:value="selectedRemotePaths"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingRemoteCandidates"
                allow-clear
                :placeholder="selectedRemoteDirectories.length ? '从所选目录中多选要导入的技能' : '请先选择目录'"
                :options="remoteSkillSelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">本次远程导入会话：{{ remoteImportRootPath || '-' }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllRemoteSkills" :disabled="!filteredRemoteCandidates.length">全选当前目录技能</a-button>
                <a-button size="small" @click="clearRemoteSkills" :disabled="!selectedRemotePaths.length">全部清除</a-button>
              </a-space>
            </a-form-item>
            <a-alert
              type="info"
              show-icon
              style="margin-bottom: 16px"
              :message="`当前提交人：${currentUsername}`"
              :description="`当前来源：${inferRemoteOrigin(downloadUrl.trim())}`"
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
                  v-if="!remoteImportSessionId"
                  type="primary"
                  :loading="loadingRemoteCandidates"
                  :disabled="submitting || loadingRemoteCandidates || !downloadUrl.trim()"
                  @click="prepareUrlImport"
                >
                  下载
                </a-button>
                <a-button
                  type="primary"
                  ghost
                  :loading="submitting"
                  :disabled="submitting || !remoteImportSessionId || !selectedRemotePaths.length"
                  @click="handleUrlSubmit"
                >
                  提交所选技能
                </a-button>
                <a-popconfirm
                  v-if="remoteImportSessionId"
                  title="重新下载会清空当前已解析的候选技能和选择，确认继续？"
                  ok-text="重新下载"
                  cancel-text="取消"
                  @confirm="prepareUrlImport"
                >
                  <a-button :loading="loadingRemoteCandidates" :disabled="submitting || loadingRemoteCandidates || !downloadUrl.trim()">
                    重新下载
                  </a-button>
                </a-popconfirm>
                <a-button @click="resetRemoteImport" :disabled="submitting || loadingRemoteCandidates">清空</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-tab-pane>

        <a-tab-pane key="clawhub" tab="ClawHub 导入">
          <a-form layout="vertical" @finish="handleClawHubSubmit">
            <a-form-item label="ClawHub 地址">
              <a-input v-model:value="clawhubUrl" placeholder="ClawHub 详情页地址或 ZIP 下载地址" />
            </a-form-item>
            <a-form-item label="访问 Token（可选）">
              <a-input-password v-model:value="clawhubToken" placeholder="如果 ClawHub 需要认证，可填写 token" autocomplete="new-password" />
              <div class="field-hint">当前版本会优先尝试直接下载；如果返回的是页面，会尝试从页面里解析 ZIP 链接。</div>
            </a-form-item>
            <a-alert
              type="info"
              show-icon
              style="margin-bottom: 16px"
              :message="`当前提交人：${currentUsername}`"
              description="当前来源：clawhub"
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
                  :disabled="submitting || !clawhubUrl.trim()"
                  @click="handleClawHubSubmit"
                >
                  从 ClawHub 导入
                </a-button>
                <a-button @click="resetClawHub" :disabled="submitting">清空</a-button>
              </a-space>
            </a-form-item>
          </a-form>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { InboxOutlined } from '@ant-design/icons-vue'

import {
  getLocalImportCandidates,
  getSkillDetail,
  getAgentManagerSystemStatus,
  prepareUploadZip,
  prepareRemoteImport,
  submitLocalSkills,
  submitClawHubSkill,
  submitRemoteSelected,
  submitUploadSelected,
} from '../api'

const router = useRouter()
const submitMode = ref('zip')
const showLocalImport = false
const submitting = ref(false)
const loadingSystemStatus = ref(false)
const loadingLocalCandidates = ref(false)
const loadingRemoteCandidates = ref(false)
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
const downloadUrl = ref('')
const remoteImportSessionId = ref('')
const remoteImportRootPath = ref('')
const remoteCandidates = ref([])
const selectedRemoteDirectories = ref([])
const selectedRemotePaths = ref([])
const clawhubUrl = ref('')
const clawhubToken = ref('')
const currentUsername = localStorage.getItem('username') || 'admin'

const formState = reactive({
  useBehavioral: true,
  useSkillspector: false,
  useSandbox: false,
  useLlm: false,
  noCache: false,
})

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
  for (const item of uploadCandidates.value) {
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

const uploadDirectorySelectOptions = computed(() =>
  uploadDirectoryOptions.value.map((item) => ({
    value: item.value,
    label: `${item.label} (${item.count} 个 skill)`,
  })),
)

const filteredUploadCandidates = computed(() => {
  if (!selectedUploadDirectories.value.length) return []
  return uploadCandidates.value.filter((item) => selectedUploadDirectories.value.includes(getTopLevelDirectory(item)))
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

const getRemoteCandidateDirectory = (item) => {
  return getCandidateDirectory(item)
}

const remoteDirectoryOptions = computed(() => {
  const counts = new Map()
  for (const item of remoteCandidates.value) {
    const directory = getRemoteCandidateDirectory(item)
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

const remoteDirectorySelectOptions = computed(() =>
  remoteDirectoryOptions.value.map((item) => ({
    value: item.value,
    label: `${item.label} (${item.count} 个 skill)`,
  })),
)

const filteredRemoteCandidates = computed(() => {
  if (!selectedRemoteDirectories.value.length) return []
  return remoteCandidates.value.filter((item) => selectedRemoteDirectories.value.includes(getRemoteCandidateDirectory(item)))
})

const remoteSkillSelectOptions = computed(() =>
  filteredRemoteCandidates.value.map((item) => ({
    value: item.path,
    label: item.description
      ? `${item.name} · ${item.relative_path} · ${item.description}`
      : `${item.name} · ${item.relative_path}`,
  })),
)

const allRemoteDirectoryValues = computed(() => remoteDirectoryOptions.value.map((item) => item.value))
const allFilteredRemotePaths = computed(() => filteredRemoteCandidates.value.map((item) => item.path))

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
const llmReadyForSubmit = computed(() => Boolean(managerStatus.value?.llm_enabled && managerStatus.value?.llm_api_key_configured))
const sandboxEnabledInSystem = computed(() => Boolean(managerStatus.value?.sandbox_enabled))
const sandboxReadyForSubmit = computed(() => Boolean(managerStatus.value?.sandbox_enabled && managerStatus.value?.sandbox_available))
const deepScanReadyForSubmit = computed(() => Boolean(managerStatus.value?.skillspector_available))
const llmTooltip = computed(() => {
  if (loadingSystemStatus.value) return '正在读取系统设置中的 LLM 状态'
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) return '尚未获取系统设置，请稍后重试'
  if (!llmEnabledInSystem.value) return '系统设置里没有启用 LLM 分析，所以这里不能勾选'
  if (!managerStatus.value?.llm_api_key_configured) return '系统设置里尚未配置直连 LLM API Key，所以这里不能勾选'
  return '启用后会调用系统设置里的 OpenAI-compatible 配置；服务端也可配置模型网关隐私代理'
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

const inferRemoteOrigin = (url) => (url && url.includes('github.com') ? 'github' : 'unknown')

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
            message: detail.status === 'PENDING' ? '已提交，后台分析中。请在技能注册表查看状态变化。' : '后台分析已完成。',
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
  resetRemoteImport()
  resetClawHub()
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
    selectedUploadPaths.value = uploadCandidates.value.length === 1 ? [uploadCandidates.value[0].path] : []
    if (!uploadCandidates.value.length) {
      message.warning('ZIP 解析完成，但没有识别到可导入的 skill 目录')
      return
    }
    message.success(`ZIP 解析完成，识别到 ${uploadCandidates.value.length} 个可导入 skill`)
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

const resetRemoteImport = () => {
  downloadUrl.value = ''
  remoteImportSessionId.value = ''
  remoteImportRootPath.value = ''
  remoteCandidates.value = []
  selectedRemoteDirectories.value = []
  selectedRemotePaths.value = []
}

const clearSubmittedRemoteSelection = () => {
  remoteImportSessionId.value = ''
  remoteImportRootPath.value = ''
  remoteCandidates.value = []
  selectedRemoteDirectories.value = []
  selectedRemotePaths.value = []
}

const selectAllRemoteDirectories = () => {
  selectedRemoteDirectories.value = [...allRemoteDirectoryValues.value]
}

const clearRemoteDirectories = () => {
  selectedRemoteDirectories.value = []
}

const selectAllRemoteSkills = () => {
  selectedRemotePaths.value = [...allFilteredRemotePaths.value]
}

const clearRemoteSkills = () => {
  selectedRemotePaths.value = []
}

const prepareUrlImport = async () => {
  if (loadingRemoteCandidates.value || submitting.value) return
  if (!downloadUrl.value.trim()) {
    message.warning('请输入 ZIP 下载地址或 GitHub 仓库地址')
    return
  }
  loadingRemoteCandidates.value = true
  try {
    const result = await prepareRemoteImport({
      url: downloadUrl.value.trim(),
      author: currentUsername,
      origin: inferRemoteOrigin(downloadUrl.value.trim()),
    })
    remoteImportSessionId.value = result.session_id
    remoteImportRootPath.value = result.root_path
    remoteCandidates.value = result.items || []
    selectedRemoteDirectories.value = []
    selectedRemotePaths.value = []
    if (!remoteCandidates.value.length) {
      message.warning('下载完成，但没有识别到可导入的 skill 目录')
      return
    }
    if (remoteDirectoryOptions.value.length === 1) {
      selectedRemoteDirectories.value = [remoteDirectoryOptions.value[0].value]
    }
    if (remoteCandidates.value.length === 1) {
      selectedRemotePaths.value = [remoteCandidates.value[0].path]
    }
    message.success(`下载完成，识别到 ${remoteCandidates.value.length} 个可导入 skill`)
  } catch (error) {
    message.error(error.response?.data?.detail || '远程下载失败')
  } finally {
    loadingRemoteCandidates.value = false
  }
}

const handleRemoteFormFinish = () => {
  if (!remoteImportSessionId.value) {
    prepareUrlImport()
  }
}

const handleUrlSubmit = async () => {
  if (submitting.value) return
  if (!remoteImportSessionId.value) {
    message.warning('请先下载远程压缩包')
    return
  }
  if (!selectedRemoteDirectories.value.length) {
    message.warning('请先选择要导入的目录')
    return
  }
  if (!selectedRemotePaths.value.length) {
    message.warning('请先选择要导入的技能 目录')
    return
  }
  submitting.value = true
  try {
    const result = await submitRemoteSelected({
      session_id: remoteImportSessionId.value,
      paths: selectedRemotePaths.value,
      author: currentUsername,
      origin: inferRemoteOrigin(downloadUrl.value.trim()),
      use_behavioral: formState.useBehavioral,
      use_skillspector: formState.useSkillspector,
      use_sandbox: effectiveUseSandbox(),
      use_llm: formState.useLlm,
      no_cache: formState.noCache,
    })
    submitResults.value = result.results || []
    clearSubmittedRemoteSelection()
    message.success(`已提交 ${submitResults.value.length} 个 skills`)
    startPolling()
  } catch (error) {
    message.error(error.response?.data?.detail || '远程导入失败')
  } finally {
    submitting.value = false
  }
}

const resetClawHub = () => {
  clawhubUrl.value = ''
  clawhubToken.value = ''
}

watch(downloadUrl, (_newValue, oldValue) => {
  if (!oldValue) return
  remoteImportSessionId.value = ''
  remoteImportRootPath.value = ''
  remoteCandidates.value = []
  selectedRemoteDirectories.value = []
  selectedRemotePaths.value = []
})

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

watch(selectedRemoteDirectories, (directories) => {
  if (!directories.length) {
    selectedRemotePaths.value = []
    return
  }
  const allowed = new Set(filteredRemoteCandidates.value.map((item) => item.path))
  selectedRemotePaths.value = selectedRemotePaths.value.filter((path) => allowed.has(path))
})

const handleClawHubSubmit = async () => {
  if (submitting.value) return
  if (!clawhubUrl.value.trim()) {
    message.warning('请输入 ClawHub 地址')
    return
  }
  submitting.value = true
  try {
    const result = await submitClawHubSkill({
      url: clawhubUrl.value.trim(),
      token: clawhubToken.value.trim() || null,
      author: currentUsername,
      use_behavioral: formState.useBehavioral,
      use_skillspector: formState.useSkillspector,
      use_sandbox: effectiveUseSandbox(),
      use_llm: formState.useLlm,
      no_cache: formState.noCache,
    })
    submitResults.value = [result]
    message.success('ClawHub 导入成功')
    startPolling()
  } catch (error) {
    message.error(error.response?.data?.detail || 'ClawHub 导入失败')
  } finally {
    submitting.value = false
  }
}

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
