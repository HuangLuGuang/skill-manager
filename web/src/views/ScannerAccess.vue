<template>
  <div>
    <a-page-header v-if="!embedded" :title="$t('legacy.7ucd4c')" :sub-title="$t('legacy.wwz7e')" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
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

    <a-card :title="$t('legacy.eskstn')" style="margin-top: 16px">
      <a-table :data-source="parameterRows" :columns="parameterColumns" row-key="name" :pagination="false" size="small" />
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
        <a-tab-pane key="env" :tab="$t('legacy.2dp295')">
          <pre class="code-block">{{ envCommand }}</pre>
        </a-tab-pane>
      </a-tabs>
    </a-card>

  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useRouter } from 'vue-router'

import {
  downloadScannerBinary,
  listScannerDownloads,
} from '../api'
import { useLocaleText } from '../i18n/useLocaleText'

defineProps({
  embedded: {
    type: Boolean,
    default: false,
  },
})

const router = useRouter()
const { text } = useLocaleText()
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
  { title: text('参数', 'Parameter'), dataIndex: 'name', key: 'name', width: 180 },
  { title: text('是否必填', 'Required'), dataIndex: 'required', key: 'required', width: 100 },
  { title: text('作用', 'Purpose'), dataIndex: 'usage', key: 'usage' },
  { title: text('示例', 'Example'), dataIndex: 'example', key: 'example', width: 260 },
])

const parameterRows = computed(() => [
  { name: 'scan <path>', required: text('是', 'Yes'), usage: text('客户本地 skills 根目录。scanner 会递归查找包含 SKILL.md 的目录。', 'Local skills root. The scanner recursively discovers directories containing SKILL.md.'), example: './skill-scanner scan /opt/openclaw/skills' },
  { name: 'SKILL_SCANNER_SERVER', required: text('上传时必填', 'Required for upload'), usage: text('Agent Manager 管理台地址。设置后会启用上传；也可以用 --server 传入。', 'Agent Manager URL. Setting it enables uploads; --server can also be used.'), example: 'http://127.0.0.1:8001' },
  { name: 'SKILL_SCANNER_TOKEN', required: text('上传时必填', 'Required for upload'), usage: text('凭证管理中创建的 Scanner 接入凭证，需要包含 scanner:submit。', 'Scanner credential created in Credential Center with scanner:submit scope.'), example: 'amat_xxx' },
  { name: '--server', required: text('否', 'No'), usage: text('命令行方式指定平台地址，会覆盖环境变量。', 'Set the platform URL from the command line, overriding the environment variable.'), example: '--server https://agent-manager.example.com' },
  { name: '--token', required: text('否', 'No'), usage: text('命令行方式指定接入凭证，会覆盖环境变量。', 'Set the credential from the command line, overriding the environment variable.'), example: '--token amat_xxx' },
  { name: '--output', required: text('否', 'No'), usage: text('本地 JSON 报告输出路径。报告里有 skill_id、fingerprint、本地预检结果和上传状态。', 'Local JSON report path containing skill_id, fingerprint, precheck results, and upload status.'), example: '--output report.json' },
  { name: '--host-id', required: text('否', 'No'), usage: text('客户主机或环境标识，便于后台区分来源。也可以用 SKILL_SCANNER_HOST_ID。', 'Host or environment identifier used to distinguish sources. SKILL_SCANNER_HOST_ID is also supported.'), example: '--host-id customer-a-prod-01' },
  { name: '--behavioral', required: text('否', 'No'), usage: text('请求服务端启用规则分析，扫描 scripts、references 等文件中的可疑行为。', 'Enable server-side rule analysis for suspicious behavior in scripts, references, and related files.'), example: '--behavioral' },
  { name: '--deep-scan', required: text('否', 'No'), usage: text('请求服务端启用深度扫描。服务端配置了模型网关模型时，会同时启用深度扫描中的 LLM 能力。', 'Enable deep analysis. If a gateway model is configured, its LLM capability is also used.'), example: '--deep-scan' },
  { name: '--sandbox', required: text('否', 'No'), usage: text('请求服务端启用 Sandbox probe，观察受控运行时行为。', 'Enable the Sandbox probe to observe controlled runtime behavior.'), example: '--sandbox' },
  { name: '--llm', required: text('否', 'No'), usage: text('请求服务端启用 LLM 分析。服务端会使用策略配置中选择的模型网关模型。', 'Enable LLM analysis using the gateway model selected in Policy Settings.'), example: '--llm' },
  { name: '--no-cache', required: text('否', 'No'), usage: text('禁用服务端缓存，强制重新扫描和分析。', 'Disable server-side cache and force a new scan and analysis.'), example: '--no-cache' },
  { name: '--max-file-mb', required: text('否', 'No'), usage: text('本地打包前限制单文件大小。', 'Limit individual file size before packaging.'), example: '--max-file-mb 20' },
  { name: '--max-total-mb', required: text('否', 'No'), usage: text('本地打包前限制单个 skill 总大小。', 'Limit total size of one skill before packaging.'), example: '--max-total-mb 50' },
  { name: '--max-files', required: text('否', 'No'), usage: text('本地打包前限制单个 skill 文件数量。', 'Limit the number of files in one skill before packaging.'), example: '--max-files 2000' },
  { name: '--ignore', required: text('否', 'No'), usage: text('逗号分隔的忽略目录，避免扫描依赖目录和构建目录。', 'Comma-separated directories to ignore, such as dependencies and build output.'), example: '--ignore .git,node_modules,.venv,dist' },
])

const serverOrigin = computed(() => window.location.origin)
const quickStartCommand = computed(() => `chmod +x ./skill-scanner
./skill-scanner scan /path/to/skills --output skill-scan-report.json

# ${text('上传到平台', 'Upload to Agent Manager')}:
export SKILL_SCANNER_SERVER="${serverOrigin.value}"
export SKILL_SCANNER_TOKEN="amat_xxx"
./skill-scanner scan /path/to/skills --behavioral

# ${text('启用全部分析能力', 'Enable all analysis capabilities')}:
./skill-scanner scan /path/to/skills --behavioral --deep-scan --sandbox --llm --no-cache`)
const basicCommand = computed(() => `# ${text('只做本地发现和轻量预检，不上传', 'Local discovery and lightweight precheck only; do not upload')}
./skill-scanner scan /path/to/customer/skills \\
  --output skill-scan-report.json`)

const fullCommand = computed(() => `export SKILL_SCANNER_SERVER="${serverOrigin.value}"
export SKILL_SCANNER_TOKEN="amat_xxx"
export SKILL_SCANNER_HOST_ID="customer-prod-01"

./skill-scanner scan /path/to/customer/skills \\
  --behavioral \\
  --deep-scan \\
  --sandbox \\
  --llm \\
  --no-cache \\
  --output skill-scan-report.json`)

const switchesCommand = computed(() => `# ${text('启动规则分析', 'Enable rule analysis')}
./skill-scanner scan /path/to/customer/skills --behavioral

# ${text('启动深度扫描', 'Enable deep analysis')}
./skill-scanner scan /path/to/customer/skills --deep-scan

# ${text('启动 Sandbox', 'Enable Sandbox')}
./skill-scanner scan /path/to/customer/skills --sandbox

# ${text('启动 LLM 分析', 'Enable LLM analysis')}
./skill-scanner scan /path/to/customer/skills --llm

# ${text('禁用缓存，强制重新扫描', 'Disable cache and force a new scan')}
./skill-scanner scan /path/to/customer/skills --no-cache

# ${text('组合使用', 'Combined example')}
./skill-scanner scan /path/to/customer/skills \\
  --behavioral \\
  --deep-scan \\
  --sandbox \\
  --llm \\
  --no-cache \\
  --output skill-scan-report.json`)

const envCommand = computed(() => `# ${text('本地调试示例，后端端口按你的 dev_server 配置填写', 'Local debugging example; use the port configured for dev_server')}
export SKILL_SCANNER_SERVER="http://127.0.0.1:8001"
export SKILL_SCANNER_TOKEN="amat_xxx"
export SKILL_SCANNER_HOST_ID="customer-prod-01"

./skill-scanner scan /Users/huangluguang/Downloads/skills-main \\
  --behavioral \\
  --deep-scan \\
  --sandbox \\
  --llm \\
  --no-cache \\
  --output skill-scan-report.json`)

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
