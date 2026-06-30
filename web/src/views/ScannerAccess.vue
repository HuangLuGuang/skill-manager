<template>
  <div>
    <a-page-header v-if="!embedded" title="Skill 扫描器" sub-title="下载客户侧 Go Scanner，并说明本地 Skill 批量接入方式" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="9">
        <a-card title="下载 Skill 扫描器 CLI">
          <a-space direction="vertical" style="width: 100%" size="middle">
            <a-select v-model:value="selectedPlatform" style="width: 100%" placeholder="选择下载平台">
              <a-select-option
                v-for="item in platformOptions"
                :key="item.value"
                :value="item.value"
                :disabled="downloads.length > 0 && !isDownloadAvailable(item.value)"
              >
                {{ item.label }}{{ downloads.length > 0 && !isDownloadAvailable(item.value) ? '（暂未构建）' : '' }}
              </a-select-option>
            </a-select>
            <a-button type="primary" block :loading="downloading" @click="handleDownload">
              下载 CLI 命令行版
            </a-button>
          </a-space>

          <a-divider />
          <a-typography-title :level="5">使用示例</a-typography-title>
          <pre class="code-block">chmod +x ./skill-scanner
./skill-scanner scan /path/to/skills --output skill-scan-report.json

# 上传到平台：
export SKILL_SCANNER_SERVER="{{ serverOrigin }}"
export SKILL_SCANNER_TOKEN="amat_xxx"
./skill-scanner scan /path/to/skills --behavioral

# 全部分析能力：
./skill-scanner scan /path/to/skills --behavioral --deep-scan --sandbox --llm --no-cache</pre>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="15">
        <a-card title="接入凭证">
          <template #extra>
            <a-space>
              <a-button type="primary" @click="router.push('/credentials')">前往凭证管理</a-button>
            </a-space>
          </template>

          <a-alert
            type="info"
            show-icon
            message="Scanner 接入凭证统一在“凭证管理”中创建"
            description="创建时类型选择“Scanner 接入凭证”，权限至少包含 scanner:submit。Agent Skill Verifier 属于 Agent 运行时接入，请到“智能体管理 / 接入与运行”查看。"
            style="margin-bottom: 16px"
          />
          <a-descriptions bordered size="small" :column="1">
            <a-descriptions-item label="创建入口">智能体管理 / 凭证管理</a-descriptions-item>
            <a-descriptions-item label="Scanner 权限">scanner:submit、scanner:read-own-results、scanner:read-own-sessions</a-descriptions-item>
            <a-descriptions-item label="运行时守卫">
              <a @click="router.push('/runtime')">前往“接入与运行”查看 Agent Skill Verifier 接入说明</a>
            </a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>
    </a-row>

    <a-card title="参数怎么用" style="margin-top: 16px">
      <a-table :data-source="parameterRows" :columns="parameterColumns" row-key="name" :pagination="false" size="small" />
    </a-card>

    <a-card title="客户侧运行示例" style="margin-top: 16px">
      <a-alert
        type="info"
        show-icon
        message="上传完成后，请在 Skill 列表查看扫描状态和详情。"
        style="margin-bottom: 16px"
      />
      <a-tabs>
        <a-tab-pane key="basic" tab="基础扫描">
          <pre class="code-block">{{ basicCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="full" tab="启用行为 / Sandbox / LLM">
          <pre class="code-block">{{ fullCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="switches" tab="能力开关">
          <pre class="code-block">{{ switchesCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="env" tab="本地调试">
          <pre class="code-block">{{ envCommand }}</pre>
        </a-tab-pane>
      </a-tabs>
    </a-card>

  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useRouter } from 'vue-router'

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
const parameterColumns = [
  { title: '参数', dataIndex: 'name', key: 'name', width: 180 },
  { title: '是否必填', dataIndex: 'required', key: 'required', width: 100 },
  { title: '作用', dataIndex: 'usage', key: 'usage' },
  { title: '示例', dataIndex: 'example', key: 'example', width: 260 },
]

const parameterRows = [
  { name: 'scan <path>', required: '是', usage: '客户本地 skills 根目录。scanner 会递归查找包含 SKILL.md 的目录。', example: './skill-scanner scan /opt/openclaw/skills' },
  { name: 'SKILL_SCANNER_SERVER', required: '上传时必填', usage: 'Agent Manager 管理台地址。设置后会启用上传；也可以用 --server 传入。', example: 'http://127.0.0.1:8001' },
  { name: 'SKILL_SCANNER_TOKEN', required: '上传时必填', usage: '凭证管理中创建的 Scanner 接入凭证，需要包含 scanner:submit。', example: 'amat_xxx' },
  { name: '--server', required: '否', usage: '命令行方式指定平台地址，会覆盖环境变量。', example: '--server https://agent-manager.example.com' },
  { name: '--token', required: '否', usage: '命令行方式指定接入凭证，会覆盖环境变量。', example: '--token amat_xxx' },
  { name: '--output', required: '否', usage: '本地 JSON 报告输出路径。报告里有 skill_id、fingerprint、本地预检结果和上传状态。', example: '--output report.json' },
  { name: '--host-id', required: '否', usage: '客户主机或环境标识，便于后台区分来源。也可以用 SKILL_SCANNER_HOST_ID。', example: '--host-id customer-a-prod-01' },
  { name: '--behavioral', required: '否', usage: '请求服务端启用规则分析，扫描 scripts、references 等文件中的可疑行为。', example: '--behavioral' },
  { name: '--deep-scan', required: '否', usage: '请求服务端启用深度扫描。服务端配置了模型网关模型时，会同时启用深度扫描中的 LLM 能力。', example: '--deep-scan' },
  { name: '--sandbox', required: '否', usage: '请求服务端启用 Sandbox probe，观察受控运行时行为。', example: '--sandbox' },
  { name: '--llm', required: '否', usage: '请求服务端启用 LLM 分析。服务端会使用策略配置中选择的模型网关模型。', example: '--llm' },
  { name: '--no-cache', required: '否', usage: '禁用服务端缓存，强制重新扫描和分析。', example: '--no-cache' },
  { name: '--max-file-mb', required: '否', usage: '本地打包前限制单文件大小。', example: '--max-file-mb 20' },
  { name: '--max-total-mb', required: '否', usage: '本地打包前限制单个 skill 总大小。', example: '--max-total-mb 50' },
  { name: '--max-files', required: '否', usage: '本地打包前限制单个 skill 文件数量。', example: '--max-files 2000' },
  { name: '--ignore', required: '否', usage: '逗号分隔的忽略目录，避免扫描依赖目录和构建目录。', example: '--ignore .git,node_modules,.venv,dist' },
]

const serverOrigin = computed(() => window.location.origin)
const basicCommand = computed(() => `# 只做本地发现和轻量预检，不上传
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

const switchesCommand = computed(() => `# 启动规则分析
./skill-scanner scan /path/to/customer/skills --behavioral

# 启动深度扫描
./skill-scanner scan /path/to/customer/skills --deep-scan

# 启动 Sandbox
./skill-scanner scan /path/to/customer/skills --sandbox

# 启动 LLM 分析
./skill-scanner scan /path/to/customer/skills --llm

# 禁用缓存，强制重新扫描
./skill-scanner scan /path/to/customer/skills --no-cache

# 组合使用
./skill-scanner scan /path/to/customer/skills \\
  --behavioral \\
  --deep-scan \\
  --sandbox \\
  --llm \\
  --no-cache \\
  --output skill-scan-report.json`)

const envCommand = computed(() => `# 本地调试示例，后端端口按你的 dev_server 配置填写
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
    message.error(error.response?.data?.detail || '获取下载列表失败')
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
      message.warning('该版本暂未构建，请先在服务端生成对应 release 文件')
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
    message.error(error.response?.data?.detail || '下载失败，请确认 scanner/releases 下已有对应平台二进制')
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
