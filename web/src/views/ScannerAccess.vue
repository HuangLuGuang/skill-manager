<template>
  <div>
    <a-card :class="{ 'page-card': !embedded }" :bordered="!embedded" :body-style="embedded ? { padding: 0 } : undefined">
      <template v-if="!embedded" #title>
        <a-page-header :title="$t('legacy.7ucd4c')" :sub-title="$t('legacy.wwz7e')" />
      </template>

    <a-row :gutter="[16, 16]">
      <a-col :xs="24" :xl="9">
        <a-card :title="$t('legacy.uqe9vk')">
          <a-space direction="vertical" style="width: 100%" size="middle">
            <a-select v-model:value="selectedPlatform" style="width: 100%" :placeholder="$t('legacy.u8iezs')">
              <a-select-option
                v-for="item in platformOptions"
                :key="item.value"
                :value="item.value"
                :disabled="downloads.length > 0 && !isDownloadAvailable(item.value)"
              >
                {{ item.label }}{{ downloads.length > 0 && !isDownloadAvailable(item.value) ? $t('legacy.h4zed4') : '' }}
              </a-select-option>
            </a-select>
            <a-button type="primary" block :loading="downloading" @click="handleDownload"> {{ $t("legacy.dlhpuk") }} </a-button>
          </a-space>

          <a-divider />
          <a-typography-title :level="5">{{ $t("legacy.yuf4eh") }}</a-typography-title>
          <pre class="code-block">{{ quickStartCommand }}</pre>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="15">
        <a-card :title="$t('legacy.19h1kid')">
          <template #extra>
            <a-space>
              <a-button type="primary" @click="router.push('/credentials')">{{ $t("legacy.ntpgmd") }}</a-button>
            </a-space>
          </template>

          <a-alert
            type="info"
            show-icon
            :message="$t('legacy.aox33a')"
            :description="$t('legacy.g5c5tx')"
            style="margin-bottom: 16px"
          />
          <a-descriptions bordered size="small" :column="1">
            <a-descriptions-item :label="$t('legacy.1acdaj8')">{{ $t("legacy.3k18bg") }}</a-descriptions-item>
            <a-descriptions-item :label="$t('legacy.1tguuvg')">scanner:submit、scanner:read-own-results、scanner:read-own-sessions</a-descriptions-item>
            <a-descriptions-item :label="$t('legacy.basi5o')">
              <a @click="router.push('/runtime')">{{ $t("legacy.mulvsl") }}</a>
            </a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>
    </a-row>

    <a-card :title="t('scannerGuide.title')" style="margin-top: 16px">
      <a-alert type="info" show-icon :message="t('scannerGuide.summary')" :description="t('scannerGuide.priority')" />
      <section v-for="group in parameterGroups" :key="group.id">
        <a-typography-title :level="5">{{ t(`scannerGuide.groups.${group.id}.title`) }}</a-typography-title>
        <p>{{ t(`scannerGuide.groups.${group.id}.help`) }}</p>
        <a-table :data-source="group.rows" :columns="parameterColumns" row-key="id" :pagination="false" :scroll="{ x: 1000 }" size="small">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <div>{{ record.name }}</div>
              <div v-for="form in record.forms" :key="form"><code>{{ form }}</code></div>
            </template>
          </template>
        </a-table>
      </section>
    </a-card>

    <a-card :title="$t('legacy.1ue20m4')" style="margin-top: 16px">
      <a-alert
        type="info"
        show-icon
        :message="$t('legacy.1jdabo8')"
        style="margin-bottom: 16px"
      />
      <a-tabs>
        <a-tab-pane key="basic" :tab="$t('legacy.18pb0yp')">
          <pre class="code-block">{{ basicCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="full" :tab="$t('legacy.uftzek')">
          <pre class="code-block">{{ fullCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="switches" :tab="$t('legacy.moasaw')">
          <pre class="code-block">{{ switchesCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="env" :tab="t('scannerGuide.examples.cliTab')">
          <pre class="code-block">{{ envCommand }}</pre>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    </a-card>

  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  downloadScannerBinary,
  listScannerDownloads,
} from '../api'

defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})

const router = useRouter()
const { t } = useI18n()
const downloads = ref([])
const downloading = ref(false)
const selectedPlatform = ref('darwin-arm64')
const platformOptions = [
  { value: 'darwin-arm64', label: 'macOS Apple Silicon（darwin-arm64）' },
  { value: 'darwin-amd64', label: 'macOS Intel（darwin-amd64）' },
  { value: 'linux-amd64', label: 'Linux x86_64（linux-amd64）' },
  { value: 'linux-arm64', label: 'Linux ARM64（linux-arm64）' },
  { value: 'windows-amd64.exe', label: 'Windows x86_64（windows-amd64.exe）' },
]
const parameterColumns = computed(() => [
  { title: t('scannerGuide.columns.name'), dataIndex: 'name', key: 'name', width: 250 },
  { title: t('scannerGuide.columns.required'), dataIndex: 'required', key: 'required', width: 150 },
  { title: t('scannerGuide.columns.value'), dataIndex: 'value', key: 'value', width: 280 },
  { title: t('scannerGuide.columns.usage'), dataIndex: 'usage', key: 'usage' },
])
// 按配置项合并命令行与环境变量，避免把某种填写方式误标为必填。
const parameterForms = {
  path: ['scan <path>'],
  server: ['--server <URL>', 'SKILL_SCANNER_SERVER'],
  token: ['--token <TOKEN>', 'SKILL_SCANNER_TOKEN'],
  upload: ['--upload'],
  output: ['--output <PATH>'],
  host: ['--host-id <ID>', 'SKILL_SCANNER_HOST_ID'],
  timeout: ['--timeout <DURATION>'],
  behavioral: ['--behavioral'],
  deep: ['--deep-scan'],
  sandbox: ['--sandbox'],
  llm: ['--llm'],
  judgement: ['--judgement-mode <MODE>', 'SKILL_SCANNER_JUDGEMENT_MODE'],
  file: ['--max-file-mb <N>'],
  total: ['--max-total-mb <N>'],
  files: ['--max-files <N>'],
  ignore: ['--ignore <NAMES>'],
}
const parameterGroups = computed(() => [
  { id: 'connection', fields: ['path', 'server', 'token', 'upload', 'output', 'host', 'timeout'] },
  { id: 'analysis', fields: ['behavioral', 'deep', 'sandbox', 'llm', 'judgement'] },
  { id: 'limits', fields: ['file', 'total', 'files', 'ignore'] },
].map(group => ({
  id: group.id,
  rows: group.fields.map(id => ({
    id, forms: parameterForms[id],
    ...Object.fromEntries(['name', 'required', 'value', 'usage'].map(key => [key, t(`scannerGuide.rows.${id}.${key}`)])),
  })),
})))

const serverOrigin = computed(() => window.location.origin)
const quickStartCommand = computed(() => `chmod +x ./skill-scanner
# ${t('scannerGuide.examples.local')}
./skill-scanner scan /path/to/skills --server="" --output skill-scan-report.json

# ${t('scannerGuide.examples.upload')}
export SKILL_SCANNER_SERVER="${serverOrigin.value}"
export SKILL_SCANNER_TOKEN="amat_xxx"
./skill-scanner scan /path/to/skills --behavioral

# ${t('scannerGuide.examples.all')}
./skill-scanner scan /path/to/skills --behavioral --deep-scan --sandbox --llm`)
const basicCommand = computed(() => `# ${t('scannerGuide.examples.local')}
./skill-scanner scan /path/to/skills --server="" --output skill-scan-report.json`)

const fullCommand = computed(() => `export SKILL_SCANNER_SERVER="${serverOrigin.value}"
export SKILL_SCANNER_TOKEN="amat_xxx"
export SKILL_SCANNER_HOST_ID="customer-prod-01"

./skill-scanner scan /path/to/skills --behavioral --deep-scan --sandbox --llm --output skill-scan-report.json`)

const switchesCommand = computed(() => `export SKILL_SCANNER_SERVER="${serverOrigin.value}"
export SKILL_SCANNER_TOKEN="amat_xxx"

# ${t('scannerGuide.examples.rules')}
./skill-scanner scan /path/to/skills --behavioral

# ${t('scannerGuide.examples.deep')}
./skill-scanner scan /path/to/skills --deep-scan

# ${t('scannerGuide.examples.sandbox')}
./skill-scanner scan /path/to/skills --sandbox

# ${t('scannerGuide.examples.llm')}
./skill-scanner scan /path/to/skills --llm

# ${t('scannerGuide.examples.combined')}
./skill-scanner scan /path/to/skills --behavioral --deep-scan --sandbox --llm`)

const envCommand = computed(() => `# ${t('scannerGuide.examples.cli')}
./skill-scanner scan /path/to/skills --server "${serverOrigin.value}" --token "amat_xxx" --output skill-scan-report.json`)

const fetchDownloads = async () => {
  try {
    const data = await listScannerDownloads()
    downloads.value = data.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.5oxkxl'))
  }
}

const isDownloadAvailable = (platform) => {
  const name = `skill-scanner-cli-${platform}`
  return downloads.value.some((item) => item.name === name)
}

const handleDownload = async () => {
  downloading.value = true
  try {
    const downloadKey = `cli-${selectedPlatform.value}`
    if (!isDownloadAvailable(selectedPlatform.value)) {
      message.warning(phrase('legacy.13w5v7q'))
      return
    }
    const blob = await downloadScannerBinary(downloadKey)
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `skill-scanner-${downloadKey}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.nj4ugw'))
  } finally {
    downloading.value = false
  }
}

onMounted(() => {
  fetchDownloads()
})
</script>

<style scoped>
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

.muted,
.hint {
  color: #8c8c8c;
  font-size: 12px;
}
</style>
