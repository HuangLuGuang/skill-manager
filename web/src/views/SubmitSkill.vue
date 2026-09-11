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
        <a-tab-pane key="zip" :tab="t('skillUpload.folder.tab')">
          <a-alert v-if="oversizedZip" type="warning" show-icon :message="t('skillUpload.localTooLarge', { size: formatZipSize(oversizedZip.size) })" style="margin-bottom: 16px">
            <template #description>
              <p>{{ t('skillUpload.cleanupHint') }}</p>
              <p v-if="zipSizeError">{{ t('skillUpload.sizeAnalysisFailed') }}</p>
              <template v-else-if="zipSizeReport">
                <a-table :data-source="zipSizeReport.folders" :columns="zipSizeColumns" row-key="path" :pagination="false" size="small" :scroll="{ x: 620 }">
                  <template #bodyCell="{ column, record }">
                    <span v-if="column.key === 'path'" style="overflow-wrap: anywhere">{{ record.path === '.' ? t('skillUpload.rootFiles') : record.path }}</span>
                    <span v-else-if="column.key === 'compressed'">{{ formatZipSize(record.compressed) }}</span>
                    <span v-else-if="column.key === 'original'">{{ formatZipSize(record.original) }}</span>
                  </template>
                </a-table>
              </template>
            </template>
          </a-alert>
          <a-alert v-if="skippedZipSymlinks.length" type="warning" show-icon :message="t('skillUpload.skippedLinks')" style="margin-bottom: 16px">
            <template #description>
              <div style="max-height: 180px; overflow: auto; overflow-wrap: anywhere">
                <div v-for="path in skippedZipSymlinks" :key="path">{{ path }}</div>
              </div>
            </template>
          </a-alert>
          <a-form layout="vertical" @finish="prepareZipImport">
            <a-form-item :label="t('skillUpload.folder.source')">
              <a-radio-group v-model:value="uploadSource" button-style="solid" :disabled="folderBusy || loadingZipCandidates || submitting || analyzingZipSize" style="margin-bottom: 16px" @change="resetZip">
                <a-radio-button value="zip">{{ t('skillUpload.folder.zipMode') }}</a-radio-button>
                <a-radio-button value="folder">{{ t('skillUpload.folder.folderMode') }}</a-radio-button>
              </a-radio-group>
              <input ref="folderInput" type="file" webkitdirectory multiple hidden @change="handleFolderSelection" />
              <a-alert v-if="uploadSource === 'folder'" type="info" show-icon :message="t('skillUpload.folder.performanceHint')" style="margin-bottom: 12px" />
              <a-space v-if="uploadSource === 'folder'" wrap style="display: flex; margin-bottom: 12px">
                <a-button :disabled="folderBusy || loadingZipCandidates || submitting || analyzingZipSize" @click="folderInput.click()">{{ t('skillUpload.folder.choose') }}</a-button>
                <a-button v-if="folderBusy" @click="cancelFolder">{{ t('skillUpload.folder.cancel') }}</a-button>
              </a-space>
              <a-upload-dragger
                v-if="uploadSource === 'zip'"
                class="zip-dragger"
                :disabled="loadingZipCandidates || submitting || analyzingZipSize || folderBusy"
                accept=".zip,application/zip"
                :show-upload-list="false"
                :before-upload="handleBeforeUpload"
              >
                <p class="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p class="ant-upload-text">{{ $t("legacy.xz9kog") }}</p>
                <p class="ant-upload-hint">{{ $t("legacy.1em9qzx") }}</p>
                <p class="ant-upload-hint">{{ t('skillUpload.zipSizeHint') }}</p>
              </a-upload-dragger>
              <div class="field-hint">{{ selectedFile ? text(`当前文件：${selectedFile.name}`, `Current file: ${selectedFile.name}`) : text('尚未选择文件', 'No file selected') }}</div>
              <div v-if="zipProgress" class="zip-progress" role="status" aria-live="polite">
                <a-space wrap>
                  <a-spin v-if="zipProgress.percent === null" size="small" />
                  <span>{{ t(`skillUpload.progress.${zipProgress.stage}`) }}</span>
                  <span v-if="zipProgress.total > 0 && zipProgress.stage !== 'uploading'">{{ zipProgress.completed }} / {{ zipProgress.total }}</span>
                </a-space>
                <a-progress v-if="zipProgress.percent !== null" :percent="zipProgress.percent" :status="zipProgress.percent === 100 ? 'normal' : 'active'" size="small" />
              </div>
              <a-space style="margin-top: 8px" wrap>
                <a-button
                  type="primary"
                  :loading="loadingZipCandidates"
                  :disabled="folderBusy || submitting || loadingZipCandidates || !selectedFile"
                  @click="prepareZipImport"
                > {{ $t("legacy.1skr69s") }} </a-button>
                <a-button @click="resetZip" :disabled="folderBusy || submitting || loadingZipCandidates || analyzingZipSize">{{ text('重置', 'Reset') }}</a-button>
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
            <div class="submission-controls">
              <SkillScanOptions v-model="submissionScanOptions" :status="managerStatus" :loading="loadingSystemStatus" :disabled="submitting" />
              <a-space wrap>
                <a-button
                  type="primary"
                  ghost
                  :loading="submitting"
                  :disabled="submitting || !uploadImportSessionId || !selectedUploadPaths.length"
                  @click="handleZipSubmit"
                > {{ $t("legacy.dlkvph") }} </a-button>
                <a-button @click="uploadJobsOpen = true; refreshUploadJobs()">{{ t('skillUpload.jobs.title') }}</a-button>
              </a-space>
            </div>
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
              <SkillScanOptions v-model="submissionScanOptions" :status="managerStatus" :loading="loadingSystemStatus" :disabled="submitting" />
            </a-form-item>
            <a-form-item>
              <a-space wrap>
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

    <a-modal v-model:open="folderReviewOpen" :title="t('skillUpload.folder.review')" :width="800" :ok-text="t('skillUpload.folder.continue')" :cancel-text="t('skillUpload.folder.cancel')" :ok-button-props="{ disabled: !folderSelectedKeys.length || folderSelectedSize > FOLDER_LIMITS.total }" @ok="confirmFolderSelection" @cancel="cancelFolder">
      <a-alert v-if="folderSelectedSize > FOLDER_LIMITS.total" type="warning" show-icon :message="t('skillUpload.folder.largeSelection')" style="margin-bottom: 12px" />
      <p>{{ t('skillUpload.folder.selectedSize', { size: formatZipSize(folderSelectedSize) }) }}</p>
      <a-table :data-source="folderRows" :columns="folderColumns" row-key="path" :pagination="{ pageSize: 8 }" :scroll="{ x: 600 }" :row-selection="{ selectedRowKeys: folderSelectedKeys, onChange: keys => folderSelectedKeys = keys }" size="small">
        <template #bodyCell="{ column, record }">
          <span v-if="column.key === 'size'">{{ formatZipSize(record.size) }}</span>
          <a-button v-else-if="column.key === 'remove'" type="link" @click="removeFolderRow(record.path)">{{ t('skillUpload.folder.remove') }}</a-button>
        </template>
      </a-table>
    </a-modal>

    <a-modal v-model:open="uploadJobsOpen" :footer="null" :width="1100" :title="t('skillUpload.jobs.title')" style="max-width: calc(100vw - 32px)" :body-style="{ maxHeight: '70vh', overflowY: 'auto' }">
      <a-alert v-if="uploadJobsError" type="warning" :message="t('skillUpload.jobs.loadFailed')" show-icon />
      <a-table :data-source="uploadJobs" :columns="uploadJobColumns" row-key="job_id" :pagination="{ pageSize: 5 }" :scroll="{ x: 950 }" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'created_at'">{{ record.created_at ? new Date(record.created_at * 1000).toLocaleString(locale) : '—' }}</template>
          <template v-else-if="column.key === 'filename'">{{ record.filename || '—' }}</template>
          <template v-else-if="column.key === 'status'">{{ t(`skillUpload.jobs.status.${record.status}`) }}</template>
          <template v-else-if="column.key === 'progress'">{{ record.completed }} / {{ record.total }}</template>
          <template v-else-if="column.key === 'action'"><a-button size="small" @click="showUploadJob(record)">{{ t('skillUpload.jobs.viewResults') }}</a-button></template>
        </template>
      </a-table>
    </a-modal>

    <a-modal v-model:open="uploadResultsOpen" :title="t('skillUpload.jobs.resultTitle')" :footer="null" :width="1100" style="max-width: calc(100vw - 32px)" :body-style="{ maxHeight: '70vh', overflowY: 'auto' }">
      <a-button v-if="selectedUploadJobId" style="margin-bottom: 16px" @click="uploadResultsOpen = false; uploadJobsOpen = true; stopPolling()">{{ t('skillUpload.jobs.backToRecords') }}</a-button>
      <p v-if="selectedUploadJob">{{ t(`skillUpload.jobs.status.${selectedUploadJob.status}`) }} · {{ selectedUploadJob.completed }} / {{ selectedUploadJob.total }}</p>
      <a-alert v-for="error in selectedUploadJobErrors" :key="error.path" type="error" show-icon style="margin-top: 8px" :message="t('skillUpload.jobs.itemFailed')" :description="error.path" />
      <a-empty v-if="!submitResults.length && !selectedUploadJobErrors.length" :description="t('skillUpload.jobs.noResults')" />
      <a-alert
        v-if="submitResults.some((item) => item.status === 'PENDING')"
        style="margin-bottom: 16px"
        type="info"
        show-icon
        :message="$t('legacy.h472o0')"
        :description="$t('legacy.1mofivi')"
      />
      <a-table v-if="submitResults.length"
        :data-source="submitResults"
        :columns="resultColumns"
        row-key="skill_id"
        :pagination="{ pageSize: 20 }"
        :scroll="{ x: 1000 }"
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
          <template v-else-if="column.key === 'message' && record.scan_state">{{ t(`skillUpload.scanState.${record.scan_state}`) }}</template>
          <template v-else-if="column.key === 'action'">
            <a-button type="link" style="padding: 0" @click="goToDetail(record.skill_id)">{{ $t("legacy.ox3r68") }}</a-button>
          </template>
        </template>
      </a-table>
    </a-modal>
  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { FOLDER_LIMITS, inspectFolder, folderGroups, selectFolderEntries } from '../utils/folderUpload'
import { computed, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { InboxOutlined } from '@ant-design/icons-vue'
import ScannerAccess from './ScannerAccess.vue'
import SkillScanOptions from '../components/SkillScanOptions.vue'
import { rescanCapabilities } from '../utils/skillRescan'
import { analyzeZipSize, formatZipSize, isZipTooLarge, removeMacOSMetadata } from '../utils/zipSize'
import { useLocaleText } from '../i18n/useLocaleText'

import {
  getLocalImportCandidates,
  getSkillDetail,
  getAgentManagerSystemStatus,
  prepareUploadZip,
  confirmUploadZip,
  submitLocalSkills,
  submitUploadSelected,
  getUploadImportJobs,
} from '../api'

const router = useRouter()
const { t, locale } = useI18n()
const { text } = useLocaleText()
const submitMode = ref('zip')
const showLocalImport = false
const submitting = ref(false)
const loadingSystemStatus = ref(false)
const loadingLocalCandidates = ref(false)
const loadingZipCandidates = ref(false)
const selectedFile = ref(null)
const submitResults = ref([])
const uploadJobs = ref([])
const uploadJobsOpen = ref(false)
const uploadJobsError = ref(false)
const selectedUploadJobId = ref('')
const uploadResultsOpen = ref(false)
const selectedUploadJob = computed(() => uploadJobs.value.find(job => job.job_id === selectedUploadJobId.value))
const selectedUploadJobErrors = computed(() => selectedUploadJob.value?.errors || [])
const uploadJobColumns = computed(() => [
  { title: t('skillUpload.jobs.id'), dataIndex: 'job_id', key: 'job_id', ellipsis: true },
  { title: t('skillUpload.jobs.filename'), key: 'filename', width: 240, ellipsis: true },
  { title: t('skillUpload.jobs.createdAt'), key: 'created_at', width: 190 },
  { title: t('skillUpload.jobs.state'), key: 'status', width: 160 },
  { title: t('skillUpload.jobs.progress'), key: 'progress', width: 120 },
  { title: t('skillUpload.jobs.results'), key: 'action', width: 130 },
])
let uploadJobsTimer = null
let uploadJobsInFlight = false
let uploadJobsDisposed = false
const showUploadJob = job => {
  uploadJobsOpen.value = false
  uploadResultsOpen.value = true
  selectedUploadJobId.value = job.job_id
  submitResults.value = job.results || []
  startPolling()
}
const refreshUploadJobs = async () => {
  if (uploadJobsInFlight || uploadJobsDisposed) return
  uploadJobsInFlight = true
  try {
    const response = await getUploadImportJobs()
    if (uploadJobsDisposed) return
    uploadJobs.value = response.items || []
    uploadJobsError.value = false
    const job = uploadJobs.value.find(item => item.job_id === selectedUploadJobId.value)
    if (job && uploadResultsOpen.value) {
      submitResults.value = job.results || []
      if (!pollingTimer.value) startPolling()
    }
  } catch {
    if (!uploadJobsDisposed) uploadJobsError.value = true
  } finally {
    uploadJobsInFlight = false
  }
}
const managerStatus = ref({})
const pollingTimer = ref(null)
const pollingInFlight = ref(false)
const importRootPath = ref('')
const localCandidates = ref([])
const selectedLocalDirectories = ref([])
const selectedLocalPaths = ref([])
const uploadImportSessionId = ref('')
const uploadImportRootPath = ref('')
const uploadCandidates = ref([])
const skippedZipSymlinks = ref([])
const oversizedZip = ref(null)
const analyzingZipSize = ref(false)
const zipProgress = ref(null)
const updateZipProgress = ({ stage, completed, total }) => {
  zipProgress.value = { stage, completed, total, percent: total > 0 ? Math.min(100, Math.floor(completed / total * 100)) : null }
}
const uploadZipWithProgress = async (formData, params = {}) => {
  zipProgress.value = { stage: 'uploading', percent: 0 }
  let uploadComplete = false
  try {
    return await prepareUploadZip(formData, params, ({ loaded, total }) => {
      if (uploadComplete) return
      if (total && loaded >= total) {
        uploadComplete = true
        zipProgress.value = { stage: 'server', percent: null }
      } else updateZipProgress({ stage: 'uploading', completed: loaded, total })
    }, progress => {
      uploadComplete = true
      updateZipProgress(progress)
    })
  } finally {
    uploadComplete = true
  }
}
const zipSizeReport = ref(null)
const zipSizeError = ref(false)
const zipSizeColumns = computed(() => [
  { title: t('skillUpload.folderColumn'), key: 'path', dataIndex: 'path', width: 260 },
  { title: t('skillUpload.compressedColumn'), key: 'compressed', width: 180 },
  { title: t('skillUpload.originalColumn'), key: 'original', width: 180 },
])
const selectedUploadDirectories = ref([])
const selectedUploadPaths = ref([])
const currentUsername = localStorage.getItem('username') || 'admin'
const currentSubmitterMessage = computed(() => `${text('当前提交人', 'Current submitter')}: ${currentUsername}`)

const formState = reactive({
  useSkillspector: false,
  useSandbox: false,
  useLlm: false,
})

const submitModeMetaMap = computed(() => ({
  zip: {
    subtitle: t('skillUpload.intro.subtitle'),
    message: t('skillUpload.intro.title'),
    description: t('skillUpload.intro.description'),
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
}))
const submitModeMeta = computed(() => submitModeMetaMap.value[submitMode.value] || submitModeMetaMap.value.zip)

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

const submissionScanOptions = computed({
  get: () => ({
    use_behavioral: true, use_skillspector: formState.useSkillspector,
    use_sandbox: formState.useSandbox, use_llm: formState.useLlm,
  }),
  set: options => {
    formState.useSkillspector = options.use_skillspector
    formState.useSandbox = options.use_sandbox
    formState.useLlm = options.use_llm
  },
})
const scanCapabilities = computed(() => rescanCapabilities(managerStatus.value))
const llmReadyForSubmit = computed(() => scanCapabilities.value.use_llm)
const sandboxReadyForSubmit = computed(() => scanCapabilities.value.use_sandbox)
const deepScanReadyForSubmit = computed(() => scanCapabilities.value.use_skillspector)
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

const uploadSource = ref('zip')
const folderInput = ref(null)
const folderBusy = ref(false)
const folderReviewOpen = ref(false)
const folderRows = ref([])
const folderSelectedKeys = ref([])
let folderEntries = []
const folderSelectedSize = computed(() => folderRows.value.filter(row => folderSelectedKeys.value.includes(row.path)).reduce((sum, row) => sum + row.size, 0))
const folderColumns = computed(() => [
  { title: t('skillUpload.folder.path'), dataIndex: 'path', key: 'path' },
  { title: t('skillUpload.folder.size'), key: 'size', width: 120 },
  { title: t('skillUpload.folder.count'), dataIndex: 'count', width: 90 },
  { title: t('skillUpload.folder.action'), key: 'remove', width: 90 },
])
const removeFolderRow = path => {
  folderRows.value = folderRows.value.filter(row => row.path !== path)
  folderSelectedKeys.value = folderSelectedKeys.value.filter(key => key !== path)
  folderEntries = selectFolderEntries(folderEntries, folderRows.value.map(row => row.path))
}
const confirmFolderSelection = () => {
  if (folderSelectedSize.value > FOLDER_LIMITS.total) return
  const entries = selectFolderEntries(folderEntries, folderSelectedKeys.value)
  if (!entries.length) return
  folderReviewOpen.value = false
  reviewFolderFiles(entries.map(entry => entry.file))
}
let folderWorker = null
let folderRun = 0
let folderConfirmation = null
const cancelFolder = () => {
  folderReviewOpen.value = false
  folderEntries = []
  folderRun++
  folderWorker?.terminate()
  folderWorker = null
  folderConfirmation?.destroy()
  folderConfirmation = null
  folderBusy.value = false
  zipProgress.value = null
}
const handleFolderSelection = async event => {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length || folderBusy.value || loadingZipCandidates.value || submitting.value || analyzingZipSize.value) return
  try {
    const report = inspectFolder(files, false)
    folderEntries = report.entries
    folderRows.value = folderGroups(report.entries)
    folderSelectedKeys.value = folderRows.value.map(row => row.path)
    folderBusy.value = true
    folderReviewOpen.value = true
  } catch (error) {
    message.error(t(`skillUpload.folder.${error.message === 'empty' ? 'empty' : 'invalidPath'}`))
  }
}
const reviewFolderFiles = files => {
  folderBusy.value = true
  const run = ++folderRun
  try {
    const report = inspectFolder(files)
    const confirmation = {
      title: t('skillUpload.folder.review'),
      content: h('div', [
        h('p', t('skillUpload.folder.summary', { name: report.name, count: report.entries.length, size: formatZipSize(report.total), skipped: report.skipped })),
        ...(report.sensitive.length ? [h('p', t('skillUpload.folder.sensitive')), h('div', { style: 'max-height: 180px; overflow: auto; overflow-wrap: anywhere' }, report.sensitive.map(path => h('div', path)))] : []),
      ]),
      okText: t('skillUpload.folder.continue'), cancelText: t('skillUpload.folder.cancel'),
      onCancel: cancelFolder,
      onOk: () => {
        if (run !== folderRun) return
        folderConfirmation = null
        clearZipAnalysis()
        selectedFile.value = null
        zipProgress.value = { stage: 'packing', percent: 0, completed: 0, total: report.entries.length }
        const worker = new Worker(new URL('../utils/folderUpload.worker.js', import.meta.url), { type: 'module' })
        folderWorker = worker
        const fail = () => { if (run === folderRun) { cancelFolder(); message.error(t('skillUpload.folder.failed')) } }
        worker.onerror = fail
        worker.onmessage = ({ data }) => {
          if (run !== folderRun) return
          if (data.type === 'progress') zipProgress.value = { ...data, stage: 'packing' }
          else if (data.type === 'result') {
            worker.terminate()
            folderWorker = null
            folderBusy.value = false
            zipProgress.value = null
            if (data.blob.size > 100 * 1024 * 1024) {
              message.warning(t('skillUpload.folder.packedTooLarge'))
              folderBusy.value = true
              folderReviewOpen.value = true
              return
            }
            folderEntries = []
            void handleBeforeUpload(new File([data.blob], `${report.name}.zip`, { type: 'application/zip' }))
          } else fail()
        }
        worker.postMessage(report.entries)
      },
    }
    if (report.sensitive.length) folderConfirmation = Modal.confirm(confirmation)
    else confirmation.onOk()
  } catch (error) {
    folderReviewOpen.value = true
    message.error(t(`skillUpload.folder.${['limit', 'invalidPath', 'empty'].includes(error.message) ? error.message : 'failed'}`))
  }
}

const handleBeforeUpload = async (file) => {
  if (folderBusy.value || analyzingZipSize.value || loadingZipCandidates.value || submitting.value) return false
  const isZip = file.type === 'application/zip' || file.name.toLowerCase().endsWith('.zip')
  if (!isZip) {
    message.error(phrase('legacy.1ndzlv6'))
    return false
  }
  oversizedZip.value = null
  zipSizeReport.value = null
  zipSizeError.value = false
  skippedZipSymlinks.value = []
  selectedFile.value = null
  clearZipAnalysis()
  analyzingZipSize.value = true
  try {
    const cleanedFile = await removeMacOSMetadata(file, updateZipProgress)
    if (isZipTooLarge(cleanedFile)) {
      oversizedZip.value = { name: cleanedFile.name, size: cleanedFile.size }
      zipSizeReport.value = await analyzeZipSize(cleanedFile, updateZipProgress)
      return false
    }
    selectedFile.value = cleanedFile
  } catch {
    if (oversizedZip.value) zipSizeError.value = true
    else message.error(t('skillUpload.zipPreparationFailed'))
    return false
  } finally {
    analyzingZipSize.value = false
    zipProgress.value = null
  }
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

const refreshPendingResults = async () => {
  if (pollingInFlight.value) return
  if (!uploadResultsOpen.value || !submitResults.value.some((item) => item.status === 'PENDING')) {
    stopPolling()
    return
  }
  pollingInFlight.value = true
  const jobId = selectedUploadJobId.value
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
    if (!uploadResultsOpen.value || selectedUploadJobId.value !== jobId) return
    submitResults.value = updated
    if (!updated.some((item) => item.status === 'PENDING')) stopPolling()
  } catch (_error) {
    // ignore transient polling errors
  } finally {
    pollingInFlight.value = false
  }
}

const startPolling = () => {
  stopPolling()
  if (selectedUploadJobId.value) return
  if (!submitResults.value.some((item) => item.status === 'PENDING')) return
  void refreshPendingResults()
  pollingTimer.value = setInterval(refreshPendingResults, 1000)
}

const clearZipAnalysis = () => {
  uploadImportSessionId.value = ''
  uploadImportRootPath.value = ''
  uploadCandidates.value = []
  selectedUploadDirectories.value = []
  selectedUploadPaths.value = []
}

const resetZip = () => {
  oversizedZip.value = null
  zipSizeReport.value = null
  zipSizeError.value = false
  selectedFile.value = null
  skippedZipSymlinks.value = []
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
      use_behavioral: true,
      use_skillspector: formState.useSkillspector,
      use_sandbox: effectiveUseSandbox(),
      use_llm: formState.useLlm,
    })
    uploadJobs.value = [result, ...uploadJobs.value.filter(job => job.job_id !== result.job_id)]
    selectedUploadJobId.value = ''
    submitResults.value = []
    stopPolling()
    clearSubmittedZipSelection()
    message.success(t('skillUpload.jobs.accepted'))
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
  if (isZipTooLarge(selectedFile.value)) {
    message.error(t('skillUpload.localTooLarge', { size: formatZipSize(selectedFile.value.size) }))
    return
  }
  const formData = new FormData()
  formData.append('file', selectedFile.value)
  clearZipAnalysis()
  skippedZipSymlinks.value = []
  loadingZipCandidates.value = true
  try {
    let result = await uploadZipWithProgress(formData)
    if (result.requires_symlink_confirmation) {
      zipProgress.value = { stage: 'confirmation', percent: null }
      const confirmed = await new Promise((resolve) => Modal.confirm({
        title: t('skillUpload.symlinkTitle'),
        content: h('div', [
          h('p', t('skillUpload.symlinkWarning')),
          h('div', { style: 'max-height: 240px; overflow: auto; overflow-wrap: anywhere' },
            result.skipped_symlinks.map((path) => h('div', path))),
        ]),
        okText: t('skillUpload.skipAndContinue'),
        cancelText: t('skillUpload.cancelUpload'),
        onOk: () => { resolve(true) },
        onCancel: () => { resolve(false) },
      }))
      zipProgress.value = { stage: 'server', percent: null }
      result = await confirmUploadZip(result.session_id, confirmed, updateZipProgress)
      if (!confirmed) return
    }
    skippedZipSymlinks.value = result.skipped_symlinks || []
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
    message.error(error.apiErrorCode === 'upload.parse_failed' ? t('skillUpload.parseFailed') : error.response?.status === 413
      ? t('skillUpload.zipTooLarge')
      : error.response?.data?.detail || phrase('legacy.6o53hh'))
  } finally {
    loadingZipCandidates.value = false
    zipProgress.value = null
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
      use_behavioral: true,
      use_skillspector: formState.useSkillspector,
      use_sandbox: effectiveUseSandbox(),
      use_llm: formState.useLlm,
    })
    selectedUploadJobId.value = ''
    uploadResultsOpen.value = true
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
  void refreshUploadJobs()
  uploadJobsTimer = setInterval(refreshUploadJobs, 2000)
  await fetchSystemStatus()
  await fetchLocalCandidates()
})

onBeforeUnmount(() => {
  cancelFolder()
  uploadJobsDisposed = true
  clearInterval(uploadJobsTimer)
  stopPolling()
})
</script>

<style scoped>
.submission-controls {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 15px;
}

.zip-progress {
  margin-top: 12px;
  max-width: 560px;
}

.zip-progress :deep(.ant-progress-bg) {
  transition: none;
}

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

.remote-import-select :deep(.ant-select-clear) {
  margin-top: 0;
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
