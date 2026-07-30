<template>
  <div>
    <a-page-header :title="$t('legacy.v71tm')" :sub-title="submitModeMeta.subtitle" />

    <a-card style="margin-top: 16px">
      <a-alert
        type="info"
        show-icon
        :message="submitModeMeta.message"
        :description="submitModeMeta.description"
        style="margin-bottom: 16px"
      />

      <a-tabs v-model:activeKey="submitMode">
        <a-tab-pane key="zip" :tab="$t('legacy.17o43lg')">
          <a-form layout="vertical" @finish="prepareZipImport">
            <a-form-item :label="$t('legacy.1vavpyy')">
              <a-upload-dragger
                class="zip-dragger"
                accept=".zip,application/zip"
                :show-upload-list="false"
                :before-upload="handleBeforeUpload"
              >
                <p class="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p class="ant-upload-text">{{ $t("legacy.xz9kog") }}</p>
                <p class="ant-upload-hint">{{ $t("legacy.1em9qzx") }}</p>
              </a-upload-dragger>
              <div class="field-hint">{{ selectedFile ? text(`当前文件：${selectedFile.name}`, `Current file: ${selectedFile.name}`) : text('尚未选择文件', 'No file selected') }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button
                  type="primary"
                  :loading="loadingZipCandidates"
                  :disabled="submitting || loadingZipCandidates || !selectedFile"
                  @click="prepareZipImport"
                > {{ $t("legacy.1skr69s") }} </a-button>
                <a-button @click="resetZip" :disabled="submitting || loadingZipCandidates">{{ text('重置', 'Reset') }}</a-button>
              </a-space>
            </a-form-item>
            <a-form-item v-if="validUploadCandidates.length" :label="$t('legacy.1xftwp6')">
              <a-select
                v-model:value="selectedUploadDirectories"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingZipCandidates"
                allow-clear
                :placeholder="$t('legacy.1nya4ux')"
                :options="uploadDirectorySelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">{{ $t("legacy.10xsbdc") }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllUploadDirectories" :disabled="!uploadDirectoryOptions.length">{{ $t("legacy.cpa1l7") }}</a-button>
                <a-button size="small" @click="clearUploadDirectories" :disabled="!selectedUploadDirectories.length">{{ $t("legacy.1w6ww0k") }}</a-button>
              </a-space>
            </a-form-item>
            <a-form-item v-if="validUploadCandidates.length" :label="$t('legacy.b8ssec')">
              <a-select
                v-model:value="selectedUploadPaths"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingZipCandidates"
                allow-clear
                :placeholder="selectedUploadDirectories.length ? $t('legacy.y3xbs4') : $t('legacy.1ca98rx')"
                :options="uploadSkillSelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">{{ $t("legacy.sqr6fl") }}{{ uploadImportRootPath || '-' }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllUploadSkills" :disabled="!filteredUploadCandidates.length">{{ $t("legacy.qz14l8") }}</a-button>
                <a-button size="small" @click="clearUploadSkills" :disabled="!selectedUploadPaths.length">{{ $t("legacy.1w6ww0k") }}</a-button>
              </a-space>
            </a-form-item>
            <a-alert
              type="info"
              show-icon
              style="margin-bottom: 16px"
              :message="currentSubmitterMessage"
              :description="$t('legacy.cpri8l')"
            />
            <a-form-item>
              <a-space wrap>
                <a-tooltip :title="behavioralTooltip">
                  <span><a-checkbox v-model:checked="formState.useBehavioral">{{ $t("legacy.zloh25") }}</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="deepScanTooltip">
                  <span><a-checkbox v-model:checked="formState.useSkillspector" :disabled="!deepScanReadyForSubmit">{{ $t("legacy.1w3zw0n") }}</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="sandboxTooltip">
                  <span><a-checkbox v-model:checked="formState.useSandbox" :disabled="!sandboxReadyForSubmit">{{ $t("legacy.9un8hd") }}</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="llmTooltip">
                  <span><a-checkbox v-model:checked="formState.useLlm" :disabled="!llmReadyForSubmit">{{ $t("legacy.7szg5p") }}</a-checkbox></span>
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
                > {{ $t("legacy.dlkvph") }} </a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-tab-pane>

        <a-tab-pane v-if="showLocalImport" key="local" :tab="$t('legacy.1iew9t7')">
          <a-space style="margin-bottom: 12px" wrap>
            <a-button
              @click="fetchLocalCandidates"
              :loading="loadingLocalCandidates"
              :disabled="submitting || loadingLocalCandidates"
            > {{ $t("legacy.9vrw3l") }} </a-button>
            <span style="color: #8c8c8c">{{ $t("legacy.1x5s5wh") }}{{ importRootPath || '-' }}</span>
          </a-space>
          <a-form layout="vertical" @finish="handleLocalSubmit">
            <a-form-item v-if="localCandidates.length" :label="$t('legacy.1xftwp6')">
              <a-select
                v-model:value="selectedLocalDirectories"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingLocalCandidates"
                allow-clear
                :placeholder="$t('legacy.1nya4ux')"
                :options="localDirectorySelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">{{ $t("legacy.10xsbdc") }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllLocalDirectories" :disabled="!localDirectoryOptions.length">{{ $t("legacy.cpa1l7") }}</a-button>
                <a-button size="small" @click="clearLocalDirectories" :disabled="!selectedLocalDirectories.length">{{ $t("legacy.1w6ww0k") }}</a-button>
              </a-space>
            </a-form-item>
            <a-form-item :label="$t('legacy.b8ssec')">
              <a-select
                v-model:value="selectedLocalPaths"
                class="remote-import-select"
                mode="multiple"
                :loading="loadingLocalCandidates"
                allow-clear
                :placeholder="selectedLocalDirectories.length ? $t('legacy.y3xbs4') : $t('legacy.1ca98rx')"
                :options="localSkillSelectOptions"
                option-filter-prop="label"
                option-label-prop="label"
              />
              <div class="field-hint">{{ $t("legacy.yix7k2") }}</div>
              <a-space style="margin-top: 8px" wrap>
                <a-button size="small" @click="selectAllLocalSkills" :disabled="!filteredLocalCandidates.length">{{ $t("legacy.qz14l8") }}</a-button>
                <a-button size="small" @click="clearLocalSkills" :disabled="!selectedLocalPaths.length">{{ $t("legacy.1w6ww0k") }}</a-button>
              </a-space>
            </a-form-item>
            <a-alert
              type="info"
              show-icon
              style="margin-bottom: 16px"
              :message="currentSubmitterMessage"
              :description="$t('legacy.u2f68')"
            />
            <a-form-item>
              <a-space wrap>
                <a-tooltip :title="behavioralTooltip">
                  <span><a-checkbox v-model:checked="formState.useBehavioral">{{ $t("legacy.zloh25") }}</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="deepScanTooltip">
                  <span><a-checkbox v-model:checked="formState.useSkillspector" :disabled="!deepScanReadyForSubmit">{{ $t("legacy.1w3zw0n") }}</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="sandboxTooltip">
                  <span><a-checkbox v-model:checked="formState.useSandbox" :disabled="!sandboxReadyForSubmit">{{ $t("legacy.9un8hd") }}</a-checkbox></span>
                </a-tooltip>
                <a-tooltip :title="llmTooltip">
                  <span><a-checkbox v-model:checked="formState.useLlm" :disabled="!llmReadyForSubmit">{{ $t("legacy.7szg5p") }}</a-checkbox></span>
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
                > {{ $t("legacy.1vqj5mu") }} </a-button>
                <a-button @click="resetLocalImport" :disabled="submitting">{{ $t("legacy.s0t0zo") }}</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-tab-pane>

        <a-tab-pane key="scanner" :tab="$t('legacy.7ucd4c')">
          <ScannerAccess embedded />
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <a-card v-if="submitResults.length" :title="$t('legacy.1prneem')" style="margin-top: 16px">
      <a-alert
        v-if="submitResults.some((item) => item.status === 'PENDING')"
        style="margin-bottom: 16px"
        type="info"
        show-icon
        :message="$t('legacy.h472o0')"
        :description="$t('legacy.1mofivi')"
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
            <a-tag v-else-if="record.risk_level === 'malicious'" color="red" :title="$t('legacy.m36raq')">malicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'suspicious'" color="orange" :title="$t('legacy.1x3ukv1')">suspicious</a-tag>
            <a-tag v-else-if="record.risk_level === 'benign'" color="green" :title="$t('legacy.1apxo2s')">benign</a-tag>
            <a-tag v-else color="default">-</a-tag>
          </template>
          <template v-else-if="column.key === 'sandbox'">
            <a-space wrap>
              <a-tag v-if="record.sandbox_runtime" color="blue">{{ record.sandbox_runtime }}</a-tag>
              <a-tag v-if="record.sandbox_required_by_policy" color="orange">{{ $t("legacy.pf5db8") }}</a-tag>
            </a-space>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-button type="link" style="padding: 0" @click="goToDetail(record.skill_id)">{{ $t("legacy.ox3r68") }}</a-button>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { InboxOutlined } from '@ant-design/icons-vue'
import ScannerAccess from './ScannerAccess.vue'
import { useLocaleText } from '../i18n/useLocaleText'

import {
  getLocalImportCandidates,
  getSkillDetail,
  getAgentManagerSystemStatus,
  prepareUploadZip,
  submitLocalSkills,
  submitUploadSelected,
} from '../api'

const router = useRouter()
const { text } = useLocaleText()
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
const currentSubmitterMessage = computed(() => `${text('当前提交人', 'Current submitter')}: ${currentUsername}`)

const formState = reactive({
  useBehavioral: true,
  useSkillspector: false,
  useSandbox: false,
  useLlm: false,
})

const submitModeMetaMap = {
  zip: {
    subtitle: phrase('legacy.1vom54d'),
    message: phrase('legacy.18pplhk'),
    description: phrase('legacy.1nupcv7'),
  },
  local: {
    subtitle: phrase('legacy.5fwpqd'),
    message: phrase('legacy.1rpk3eh'),
    description: phrase('legacy.1nduc3h'),
  },
  scanner: {
    subtitle: phrase('legacy.k7sk7w'),
    message: phrase('legacy.g1i2b6'),
    description: phrase('legacy.17fev6g'),
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
      label: directory === '.' ? phrase('legacy.812gtc') : directory,
      count,
    }))
})

const localDirectorySelectOptions = computed(() =>
  localDirectoryOptions.value.map((item) => ({
    value: item.value,
    label: text(`${item.label} (${item.count} 个 Skill)`, `${item.label} (${item.count} Skills)`),
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
      label: directory === '.' ? phrase('legacy.1ebf5re') : directory,
      count,
    }))
})

const validUploadCandidates = computed(() => uploadCandidates.value.filter((item) => !item.error))
const invalidUploadCandidates = computed(() => uploadCandidates.value.filter((item) => item.error))

const uploadDirectorySelectOptions = computed(() =>
  uploadDirectoryOptions.value.map((item) => ({
    value: item.value,
    label: text(`${item.label} (${item.count} 个 Skill)`, `${item.label} (${item.count} Skills)`),
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
  { title: phrase('legacy.hzx914'), dataIndex: 'name', key: 'name' },
  { title: phrase('legacy.1ccx4t4'), dataIndex: 'status', key: 'status', width: 120 },
  { title: phrase('legacy.1qgsa3s'), dataIndex: 'risk_level', key: 'risk_level', width: 120 },
  { title: phrase('legacy.l6iuzr'), dataIndex: 'findings_count', key: 'findings_count', width: 100 },
  { title: 'Sandbox', key: 'sandbox', width: 180 },
  { title: phrase('legacy.1mi4vdj'), dataIndex: 'message', key: 'message' },
  { title: phrase('legacy.501w24'), key: 'action', width: 100 },
]

const llmEnabledInSystem = computed(() => Boolean(managerStatus.value?.llm_enabled))
const llmReadyForSubmit = computed(() => Boolean(managerStatus.value?.llm_enabled && managerStatus.value?.llm_model))
const sandboxEnabledInSystem = computed(() => Boolean(managerStatus.value?.sandbox_enabled))
const sandboxReadyForSubmit = computed(() => Boolean(managerStatus.value?.sandbox_enabled && managerStatus.value?.sandbox_available))
const deepScanReadyForSubmit = computed(() => Boolean(managerStatus.value?.skillspector_available))
const llmTooltip = computed(() => {
  if (loadingSystemStatus.value) return phrase('legacy.11gyk58')
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) return phrase('legacy.eh7hm2')
  if (!llmEnabledInSystem.value) return phrase('legacy.15tlipg')
  if (!managerStatus.value?.llm_model) return phrase('legacy.z86ri4')
  return text(
    `启用后会使用策略配置中选择的模型：${managerStatus.value.llm_model}`,
    `Uses the model selected in Policy Settings: ${managerStatus.value.llm_model}`,
  )
})
const behavioralTooltip = phrase('legacy.er61t5')
const deepScanTooltip = computed(() => {
  if (loadingSystemStatus.value) return phrase('legacy.ytd7gn')
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) return phrase('legacy.s8dbz7')
  if (!managerStatus.value?.skillspector_available) return phrase('legacy.nxt8hi')
  if (llmReadyForSubmit.value) return phrase('legacy.87644d')
  return phrase('legacy.lxs8i8')
})
const sandboxTooltip = computed(() => {
  if (loadingSystemStatus.value) return phrase('legacy.1lc1opo')
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) return phrase('legacy.eh7hm2')
  if (!sandboxEnabledInSystem.value) return phrase('legacy.18scr9y')
  if (!managerStatus.value?.sandbox_available) return phrase('legacy.clcfa1')
  return phrase('legacy.1dj13ib')
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
    message.error(error.response?.data?.detail || phrase('legacy.q9ds1b'))
  } finally {
    loadingLocalCandidates.value = false
  }
}

const handleBeforeUpload = (file) => {
  const isZip = file.type === 'application/zip' || file.name.toLowerCase().endsWith('.zip')
  if (!isZip) {
    message.error(phrase('legacy.1ndzlv6'))
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
            message: detail.status === 'PENDING' ? phrase('legacy.1u7g8m0') : phrase('legacy.1nf87mp'),
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
    message.warning(phrase('legacy.18gvsoj'))
    return
  }
  if (!uploadImportSessionId.value) {
    message.warning(phrase('legacy.1uzgrft'))
    return
  }
  if (!selectedUploadDirectories.value.length) {
    message.warning(phrase('legacy.11n4k6p'))
    return
  }
  if (!selectedUploadPaths.value.length) {
    message.warning(phrase('legacy.3oinlv'))
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
    })
    submitResults.value = result.results || []
    clearSubmittedZipSelection()
    message.success(text(
      `已提交 ${submitResults.value.length} 个 Skill`,
      `Submitted ${submitResults.value.length} Skills`,
    ))
    startPolling()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.1kuial'))
  } finally {
    submitting.value = false
  }
}

const prepareZipImport = async () => {
  if (loadingZipCandidates.value || submitting.value) return
  if (!selectedFile.value) {
    message.warning(phrase('legacy.18gvsoj'))
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
        title: phrase('legacy.xowbev'),
        content: h('div', invalidUploadCandidates.value.map((item) => {
          const directory = item.relative_path && item.relative_path !== '.'
            ? text(`${item.relative_path} 目录`, `${item.relative_path} directory`)
            : phrase('legacy.1ebf5re')
          return h(
            'div',
            { style: 'margin-bottom: 8px' },
            text(`${directory}解析失败，${item.error}`, `${directory} could not be parsed: ${item.error}`),
          )
        })),
        okText: phrase('legacy.15plsd9'),
      })
    }
    if (!validUploadCandidates.value.length) {
      message.warning(phrase('legacy.1mik2yg'))
      return
    }
    message.success(text(
      `ZIP 解析完成，识别到 ${validUploadCandidates.value.length} 个可导入 Skill`,
      `ZIP parsing completed. Found ${validUploadCandidates.value.length} importable Skills.`,
    ))
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.6o53hh'))
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
    message.warning(phrase('legacy.11n4k6p'))
    return
  }
  if (!selectedLocalPaths.value.length) {
    message.warning(phrase('legacy.1iw7jj5'))
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
    })
    submitResults.value = result.results || []
    clearSubmittedLocalSelection()
    message.success(text(
      `已提交 ${submitResults.value.length} 个 Skill`,
      `Submitted ${submitResults.value.length} Skills`,
    ))
    startPolling()
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.14eyvbl'))
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
  PENDING: phrase('legacy.viveky'),
  VETTED: phrase('legacy.a2uv9t'),
  APPROVED: phrase('legacy.10hmnl2'),
  DEPLOYED: phrase('legacy.1t00jqn'),
  REJECTED: phrase('legacy.16h1qdk'),
  RETIRED: phrase('legacy.1vdmo1u'),
}[value] || phrase('legacy.1lpnuh4'))

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
