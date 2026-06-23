<template>
  <div>
    <a-page-header title="Skills 扫描器" sub-title="下载客户侧 Go Scanner / Agent Skill Guard，并说明扫描与运行时校验方式" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="9">
        <a-card title="下载 Skills 扫描器">
          <a-alert
            type="info"
            show-icon
            message="下载的是预编译 Go 单二进制"
            description="CLI 用于命令行和 CI；GUI 是原生桌面窗口，支持系统目录选择、设置页配置 Server/Token、实时刷新扫描结果并跳转服务端详情。"
            style="margin-bottom: 16px"
          />
          <a-space direction="vertical" style="width: 100%" size="middle">
            <a-radio-group v-model:value="selectedEdition" button-style="solid" style="width: 100%">
              <a-radio-button value="cli">CLI 命令行版</a-radio-button>
              <a-radio-button value="gui">GUI 图形版</a-radio-button>
            </a-radio-group>
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
              下载 {{ selectedEdition === 'gui' ? 'GUI 图形版' : 'CLI 命令行版' }}
            </a-button>
          </a-space>

          <a-divider />
          <a-typography-title :level="5">服务端构建发布示例</a-typography-title>
          <pre class="code-block">cd scanner
./scripts/package.sh

# 指定版本号目录：
./scripts/package.sh v0.1.0

# GUI 版本使用 Fyne 原生桌面窗口，Linux/Windows GUI 建议在目标平台或 CI runner 上构建：
BUILD_LINUX_GUI=1 ./scripts/package.sh v0.1.0-linux
BUILD_WINDOWS_CLI=1 BUILD_WINDOWS_GUI=1 ./scripts/package.sh v0.1.0-windows</pre>
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
            description="创建时类型选择“Scanner 接入凭证”，权限至少包含 scanner:submit；如需 Agent Skill Guard 同时运行校验，再增加 runtime:verify-signature、runtime:can-load、runtime:check-tool。"
            style="margin-bottom: 16px"
          />
          <a-descriptions bordered size="small" :column="1">
            <a-descriptions-item label="创建入口">智能体治理 / 凭证管理</a-descriptions-item>
            <a-descriptions-item label="Scanner 权限">scanner:submit、scanner:read-own-results、scanner:read-own-sessions</a-descriptions-item>
            <a-descriptions-item label="Runtime 权限">runtime:verify-signature、runtime:can-load、runtime:check-tool</a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>
    </a-row>

    <a-card title="Agent Skill Guard 接入" style="margin-top: 16px">
      <template #extra>
        <a-button type="primary" :loading="guardDownloading" @click="handleSkillGuardDownload">下载 Skill Guard</a-button>
      </template>
      <a-alert
        type="info"
        show-icon
        message="给 Codex、Claude Code 等 Agent 使用的通用 skill"
        description="它不依赖 hook：安装到 Agent 的 skills 目录后，Agent 在安装、加载或调用第三方 skill 前，按说明先提交扫描，再做签名和审批状态校验。未批准、未签名、验签失败或状态不可加载都会阻断使用。"
        style="margin-bottom: 16px"
      />
      <a-row :gutter="[16, 16]">
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">1. 创建凭证</div>
            <p class="hint">请在“凭证管理”创建 Scanner 接入凭证，并至少包含下面这些 scope，既能提交扫描，也能在运行时验签。</p>
            <a-space wrap>
              <a-tag v-for="scope in skillGuardScopes" :key="scope" color="blue">{{ scope }}</a-tag>
            </a-space>
          </div>
        </a-col>
        <a-col :xs="24" :lg="8">
          <div class="guard-panel">
            <div class="guard-panel-title">2. 安装到 Agent</div>
            <p class="hint">下载 zip 后解压到对应平台的 skills 目录。安装完成后重启 Agent 或刷新 skill 列表。</p>
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
            <div class="guard-panel-title">3. 提交与验签</div>
            <p class="hint">首次发现第三方 skill 先 submit；管理员批准并签名后，使用前执行 verify。</p>
            <pre class="code-block compact">{{ guardUsageCommand }}</pre>
          </div>
        </a-col>
      </a-row>
    </a-card>

    <a-card title="参数怎么用" style="margin-top: 16px">
      <a-table :data-source="parameterRows" :columns="parameterColumns" row-key="name" :pagination="false" size="small" />
    </a-card>

    <a-card title="扫描结果在哪里看" style="margin-top: 16px">
      <a-steps :current="3" direction="vertical">
        <a-step title="客户本地 JSON 报告" description="scanner 执行结束后会在 --output 指定路径写入 JSON 报告，里面包含发现的 skill、fingerprint、本地轻量预检发现项、上传状态和服务端 skill_id。" />
        <a-step title="技能注册表" description="上传成功后，管理台「技能注册表」会出现对应记录，初始状态通常是 PENDING，后台完成扫描后会变成 APPROVED、VETTED 或 REJECTED。" />
        <a-step title="技能详情" description="点击技能详情可以查看 SKILL.md、文件列表、原始报告、规则分析、Sandbox 结果和 LLM 分析结果。" />
        <a-step title="审计日志" description="Token 创建、吊销、使用，以及 scanner 提交记录会写入审计，后续可以在审计日志或 scanner_audit.jsonl 中追踪。" />
      </a-steps>
    </a-card>

    <a-card title="客户侧运行示例" style="margin-top: 16px">
      <a-tabs>
        <a-tab-pane key="basic" tab="基础扫描">
          <pre class="code-block">{{ basicCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="full" tab="启用行为 / Sandbox / LLM">
          <pre class="code-block">{{ fullCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="env" tab="使用环境变量">
          <pre class="code-block">{{ envCommand }}</pre>
        </a-tab-pane>
        <a-tab-pane key="gui" tab="GUI 图形版">
          <pre class="code-block">{{ guiCommand }}</pre>
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
  downloadSkillGuard,
  listScannerDownloads,
} from '../api'

const router = useRouter()
const downloads = ref([])
const downloading = ref(false)
const guardDownloading = ref(false)
const selectedEdition = ref('cli')
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
  { name: '--server', required: '上传时必填', usage: 'Agent Manager 管理台地址。设置后会启用上传。', example: '--server https://agent-manager.example.com' },
  { name: '--token', required: '上传时必填', usage: '凭证管理中创建的 Scanner 接入凭证，需要包含 scanner:submit。也可以用 AGENT_MANAGER_TOKEN 环境变量。', example: '--token amat_xxx' },
  { name: '--output', required: '否', usage: '本地 JSON 报告输出路径。报告里有 skill_id、fingerprint、本地预检结果和上传状态。', example: '--output report.json' },
  { name: '--host-id', required: '否', usage: '客户主机或环境标识，便于后台区分来源。也可以用 SKILL_SCANNER_HOST_ID。', example: '--host-id customer-a-prod-01' },
  { name: '--behavioral', required: '否', usage: '请求服务端启用规则分析，扫描 scripts、references 等文件中的可疑行为。', example: '--behavioral' },
  { name: '--sandbox', required: '否', usage: '请求服务端启用 Sandbox probe，观察受控运行时行为。', example: '--sandbox' },
  { name: '--llm', required: '否', usage: '请求服务端启用 LLM 分析。需要系统设置直连 LLM 可用，或服务端已配置模型网关隐私代理。', example: '--llm' },
  { name: '--max-file-mb', required: '否', usage: '本地打包前限制单文件大小。', example: '--max-file-mb 20' },
  { name: '--max-total-mb', required: '否', usage: '本地打包前限制单个 skill 总大小。', example: '--max-total-mb 50' },
  { name: '--max-files', required: '否', usage: '本地打包前限制单个 skill 文件数量。', example: '--max-files 2000' },
  { name: '--ignore', required: '否', usage: '逗号分隔的忽略目录，避免扫描依赖目录和构建目录。', example: '--ignore .git,node_modules,.venv,dist' },
]

const serverOrigin = computed(() => window.location.origin)
const runtimeApiOrigin = computed(() => {
  const { protocol, hostname, port } = window.location
  if ((hostname === 'localhost' || hostname === '127.0.0.1') && (port === '5173' || port === '5174')) {
    return `${protocol}//${hostname}:8001`
  }
  return serverOrigin.value
})
const basicCommand = computed(() => `./skill-scanner scan /path/to/customer/skills \\
  --server ${serverOrigin.value} \\
  --token amat_xxx \\
  --output report.json`)

const fullCommand = computed(() => `./skill-scanner scan /path/to/customer/skills \\
  --server ${serverOrigin.value} \\
  --token amat_xxx \\
  --host-id customer-prod-01 \\
  --behavioral \\
  --sandbox \\
  --llm \\
  --output report.json`)

const envCommand = computed(() => `export AGENT_MANAGER_TOKEN="amat_xxx"
export SKILL_SCANNER_HOST_ID="customer-prod-01"
./skill-scanner scan /path/to/customer/skills \\
  --server ${serverOrigin.value} \\
  --behavioral \\
  --sandbox \\
  --output report.json`)

const guiCommand = computed(() => `chmod +x ./skill-scanner-gui-darwin-arm64
./skill-scanner-gui-darwin-arm64

# GUI 是原生桌面窗口，不启动本地 Web 服务。
# Server、Token、Host ID、输出报告在 GUI 的「设置」页配置。`)

const codexGuardInstallCommand = computed(() => `mkdir -p ~/.codex/skills
unzip agent-manager-skill-guard.zip -d ~/.codex/skills/

export AGENT_MANAGER_BASE_URL="${runtimeApiOrigin.value}"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_MANAGER_SIGNING_KEY="和服务器 .env 中保持一致"`)

const claudeGuardInstallCommand = computed(() => `mkdir -p ~/.claude/skills
unzip agent-manager-skill-guard.zip -d ~/.claude/skills/

export AGENT_MANAGER_BASE_URL="${runtimeApiOrigin.value}"
export AGENT_MANAGER_API_TOKEN="amat_xxx"
export AGENT_MANAGER_SIGNING_KEY="和服务器 .env 中保持一致"`)

const guardUsageCommand = computed(() => `python <skills-dir>/agent-manager-skill-guard/scripts/agent_manager_skill_guard.py submit --path /path/to/third-party-skill --behavioral
python <skills-dir>/agent-manager-skill-guard/scripts/agent_manager_skill_guard.py status --skill-id <skill-id>
python <skills-dir>/agent-manager-skill-guard/scripts/agent_manager_skill_guard.py verify --name <skill-name> --path /path/to/third-party-skill`)

const fetchDownloads = async () => {
  try {
    const data = await listScannerDownloads()
    downloads.value = data.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || '获取下载列表失败')
  }
}

const isDownloadAvailable = (platform) => {
  const name = `skill-scanner-${selectedEdition.value}-${platform}`
  return downloads.value.some((item) => item.name === name)
}

const handleDownload = async () => {
  downloading.value = true
  try {
    const downloadKey = `${selectedEdition.value}-${selectedPlatform.value}`
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

const handleSkillGuardDownload = async () => {
  guardDownloading.value = true
  try {
    const blob = await downloadSkillGuard()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'agent-manager-skill-guard.zip'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    message.error(error.response?.data?.detail || '下载 Agent Skill Guard 失败')
  } finally {
    guardDownloading.value = false
  }
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制')
  } catch {
    message.error('复制失败，请手动复制')
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

.muted,
.hint {
  color: #8c8c8c;
  font-size: 12px;
}
</style>
