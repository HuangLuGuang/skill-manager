<template>
  <div>
    <a-page-header title="扫描器接入" sub-title="下载客户侧 Go Scanner，管理 Token，并说明扫描结果查看方式" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="9">
        <a-card title="下载扫描器">
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
        <a-card title="接入 Token">
          <template #extra>
            <a-space>
              <a-button @click="fetchTokens" :loading="loading">刷新</a-button>
              <a-button type="primary" @click="openCreateModal">创建 Token</a-button>
            </a-space>
          </template>

          <a-alert
            type="warning"
            show-icon
            message="Token 只展示一次"
            description="服务端只保存 hash。可按用途选择 scanner 或 runtime 权限；创建后请立即复制，泄露后只能吊销并重建。"
            style="margin-bottom: 16px"
          />

          <a-table
            :data-source="tokens"
            :columns="columns"
            row-key="id"
            :loading="loading"
            :pagination="{ pageSize: 10 }"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <a-tag :color="record.status === 'active' ? 'green' : 'default'">
                  {{ record.status === 'active' ? '启用' : '已吊销' }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'scopes'">
                <a-space wrap>
                  <a-tag v-for="scope in record.scopes || []" :key="scope" color="blue">{{ scope }}</a-tag>
                </a-space>
              </template>
              <template v-else-if="column.key === 'limits'">
                {{ record.max_upload_mb || 0 }} MB / {{ record.max_concurrent_jobs || 0 }} 并发
              </template>
              <template v-else-if="column.key === 'time'">
                <div>创建：{{ formatTime(record.created_at) }}</div>
                <div class="muted">最近使用：{{ formatTime(record.last_used_at) }}</div>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-popconfirm
                  v-if="record.status === 'active'"
                  title="确认吊销这个接入 Token？"
                  ok-text="吊销"
                  cancel-text="取消"
                  @confirm="handleRevoke(record)"
                >
                  <a-button type="link" danger :loading="revokingId === record.id">吊销</a-button>
                </a-popconfirm>
                <span v-else class="muted">不可用</span>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>
    </a-row>

    <a-card title="参数怎么用" style="margin-top: 16px">
      <a-table :data-source="parameterRows" :columns="parameterColumns" row-key="name" :pagination="false" size="small" />
    </a-card>

    <a-card title="扫描结果在哪里看" style="margin-top: 16px">
      <a-steps :current="3" direction="vertical">
        <a-step title="客户本地 JSON 报告" description="scanner 执行结束后会在 --output 指定路径写入 JSON 报告，里面包含发现的 skill、fingerprint、本地轻量预检发现项、上传状态和服务端 skill_id。" />
        <a-step title="技能列表" description="上传成功后，管理台「技能列表」会出现对应记录，初始状态通常是 PENDING，后台完成扫描后会变成 APPROVED、VETTED 或 REJECTED。" />
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

    <a-modal v-model:open="createVisible" title="创建接入 Token" width="760px" @ok="handleCreate" :confirm-loading="creating">
      <a-form layout="vertical" :model="createForm">
        <a-form-item label="名称" required>
          <a-input v-model:value="createForm.name" placeholder="例如：客户A-生产环境扫描器" />
          <div class="hint">用于后台识别这个 token 属于哪个客户、环境或主机组。</div>
        </a-form-item>
        <a-row :gutter="16">
          <a-col :xs="24" :md="12">
            <a-form-item label="最大上传大小（MB）">
              <a-input-number v-model:value="createForm.max_upload_mb" :min="1" :max="500" style="width: 100%" />
              <div class="hint">限制单个 skill ZIP 上传大小，防止客户误扫大目录。</div>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="12">
            <a-form-item label="最大并发任务数">
              <a-input-number v-model:value="createForm.max_concurrent_jobs" :min="1" :max="20" style="width: 100%" />
              <div class="hint">预留给后续批量 session 调度使用。</div>
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="允许来源 IP / CIDR">
          <a-select v-model:value="createForm.allowed_ips" mode="tags" placeholder="留空表示不限制，例如 10.0.0.0/24" />
          <div class="hint">可填具体 IP 或 CIDR。配置后，只有这些来源能使用 token。</div>
        </a-form-item>
        <a-form-item label="权限范围">
          <a-space style="margin-bottom: 8px" wrap>
            <a-button size="small" @click="setScannerScopes">扫描器默认</a-button>
            <a-button size="small" @click="setRuntimeScopes">Runtime 默认</a-button>
            <a-button size="small" @click="setAllScopes">全部权限</a-button>
          </a-space>
          <a-select v-model:value="createForm.scopes" mode="multiple" style="width: 100%">
            <a-select-opt-group label="Scanner 扫描器权限">
              <a-select-option value="scanner:submit">scanner:submit</a-select-option>
              <a-select-option value="scanner:read-own-results">scanner:read-own-results</a-select-option>
              <a-select-option value="scanner:read-own-sessions">scanner:read-own-sessions</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Runtime Agent 加载校验权限">
              <a-select-option value="runtime:verify-signature">runtime:verify-signature</a-select-option>
              <a-select-option value="runtime:can-load">runtime:can-load</a-select-option>
              <a-select-option value="runtime:check-tool">runtime:check-tool</a-select-option>
            </a-select-opt-group>
          </a-select>
          <div class="hint">Scanner 用于提交扫描；Runtime 用于外部 Agent 加载前验签、can-load 和工具调用校验。不要授权审批、部署、策略修改或用户管理权限。</div>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="tokenVisible" title="接入 Token 已创建" width="820px" :footer="null">
      <a-alert
        type="warning"
        show-icon
        message="请立即保存 Token"
        description="这是唯一一次展示明文 Token。关闭弹窗后，系统无法再次查看，只能吊销后重建。"
        style="margin-bottom: 16px"
      />
      <a-input-group compact>
        <a-input :value="createdToken" readonly style="width: calc(100% - 96px)" />
        <a-button type="primary" @click="copyText(createdToken)">复制</a-button>
      </a-input-group>
      <a-divider />
      <a-typography-title :level="5">客户侧运行命令</a-typography-title>
      <pre class="code-block">{{ createdCommand }}</pre>
      <a-typography-title :level="5" style="margin-top: 12px">Agent Runtime 使用</a-typography-title>
      <pre class="code-block">{{ createdRuntimeCommand }}</pre>
      <a-space style="margin-top: 12px">
        <a-button type="primary" @click="copyText(createdCommand)">复制命令</a-button>
        <a-button @click="tokenVisible = false">关闭</a-button>
      </a-space>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import {
  createScannerToken,
  downloadScannerBinary,
  listScannerDownloads,
  listScannerTokens,
  revokeScannerToken,
} from '../api'

const loading = ref(false)
const creating = ref(false)
const createVisible = ref(false)
const tokenVisible = ref(false)
const revokingId = ref('')
const tokens = ref([])
const createdToken = ref('')
const downloads = ref([])
const downloading = ref(false)
const selectedEdition = ref('cli')
const selectedPlatform = ref('darwin-arm64')
const platformOptions = [
  { value: 'darwin-arm64', label: 'macOS Apple Silicon（darwin-arm64）' },
  { value: 'darwin-amd64', label: 'macOS Intel（darwin-amd64）' },
  { value: 'linux-amd64', label: 'Linux x86_64（linux-amd64）' },
  { value: 'linux-arm64', label: 'Linux ARM64（linux-arm64）' },
  { value: 'windows-amd64.exe', label: 'Windows x86_64（windows-amd64.exe）' },
]
const scannerScopes = ['scanner:submit', 'scanner:read-own-results', 'scanner:read-own-sessions']
const runtimeScopes = ['runtime:verify-signature', 'runtime:can-load', 'runtime:check-tool']
const createForm = reactive({
  name: '',
  scopes: [...scannerScopes],
  allowed_ips: [],
  max_upload_mb: 50,
  max_concurrent_jobs: 2,
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '前缀', dataIndex: 'token_prefix', key: 'token_prefix', width: 160 },
  { title: '状态', key: 'status', width: 90 },
  { title: '权限', key: 'scopes' },
  { title: '限制', key: 'limits', width: 140 },
  { title: '时间', key: 'time', width: 240 },
  { title: '操作', key: 'action', width: 90 },
]

const parameterColumns = [
  { title: '参数', dataIndex: 'name', key: 'name', width: 180 },
  { title: '是否必填', dataIndex: 'required', key: 'required', width: 100 },
  { title: '作用', dataIndex: 'usage', key: 'usage' },
  { title: '示例', dataIndex: 'example', key: 'example', width: 260 },
]

const parameterRows = [
  { name: 'scan <path>', required: '是', usage: '客户本地 skills 根目录。scanner 会递归查找包含 SKILL.md 的目录。', example: './skill-scanner scan /opt/openclaw/skills' },
  { name: '--server', required: '上传时必填', usage: 'Skill Manager 管理台地址。设置后会启用上传。', example: '--server https://skill-manager.example.com' },
  { name: '--token', required: '上传时必填', usage: '本页创建的接入 Token，需要包含 scanner:submit。也可以用 SKILL_MANAGER_TOKEN 环境变量。', example: '--token smsc_live_xxx' },
  { name: '--output', required: '否', usage: '本地 JSON 报告输出路径。报告里有 skill_id、fingerprint、本地预检结果和上传状态。', example: '--output report.json' },
  { name: '--host-id', required: '否', usage: '客户主机或环境标识，便于后台区分来源。也可以用 SKILL_SCANNER_HOST_ID。', example: '--host-id customer-a-prod-01' },
  { name: '--behavioral', required: '否', usage: '请求服务端启用规则分析，扫描 scripts、references 等文件中的可疑行为。', example: '--behavioral' },
  { name: '--sandbox', required: '否', usage: '请求服务端启用 Sandbox probe，观察受控运行时行为。', example: '--sandbox' },
  { name: '--llm', required: '否', usage: '请求服务端启用 LLM 分析。需要系统设置里已配置 LLM。', example: '--llm' },
  { name: '--max-file-mb', required: '否', usage: '本地打包前限制单文件大小。', example: '--max-file-mb 20' },
  { name: '--max-total-mb', required: '否', usage: '本地打包前限制单个 skill 总大小。', example: '--max-total-mb 50' },
  { name: '--max-files', required: '否', usage: '本地打包前限制单个 skill 文件数量。', example: '--max-files 2000' },
  { name: '--ignore', required: '否', usage: '逗号分隔的忽略目录，避免扫描依赖目录和构建目录。', example: '--ignore .git,node_modules,.venv,dist' },
]

const serverOrigin = computed(() => window.location.origin)
const runtimeApiOrigin = computed(() => {
  const { protocol, hostname, port } = window.location
  if ((hostname === 'localhost' || hostname === '127.0.0.1') && (port === '5173' || port === '5174')) {
    return `${protocol}//${hostname}:8000`
  }
  return serverOrigin.value
})
const basicCommand = computed(() => `./skill-scanner scan /path/to/customer/skills \\
  --server ${serverOrigin.value} \\
  --token smsc_live_xxx \\
  --output report.json`)

const fullCommand = computed(() => `./skill-scanner scan /path/to/customer/skills \\
  --server ${serverOrigin.value} \\
  --token smsc_live_xxx \\
  --host-id customer-prod-01 \\
  --behavioral \\
  --sandbox \\
  --llm \\
  --output report.json`)

const envCommand = computed(() => `export SKILL_MANAGER_TOKEN="smsc_live_xxx"
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

const createdCommand = computed(() => `./skill-scanner scan /path/to/customer/skills \\
  --server ${serverOrigin.value} \\
  --token ${createdToken.value || 'smsc_live_xxx'} \\
  --host-id customer-prod-01 \\
  --behavioral \\
  --sandbox \\
  --output report.json`)

const createdRuntimeCommand = computed(() => `# 本地开发时这里要填后端 API 地址，不要填前端 Vite 端口 5173/5174。
export SKILL_MANAGER_BASE_URL="${runtimeApiOrigin.value}"
export SKILL_MANAGER_API_TOKEN="${createdToken.value || 'smsc_live_xxx'}"
export SKILL_MANAGER_SIGNING_KEY="和服务器 .env 中保持一致"

uv run python git_workflow_demo.py --all`)

const formatTime = (value) => {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

const fetchTokens = async () => {
  loading.value = true
  try {
    const data = await listScannerTokens()
    tokens.value = data.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || '获取接入 Token 失败')
  } finally {
    loading.value = false
  }
}

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

const openCreateModal = () => {
  createForm.name = ''
  createForm.scopes = [...scannerScopes]
  createForm.allowed_ips = []
  createForm.max_upload_mb = 50
  createForm.max_concurrent_jobs = 2
  createVisible.value = true
}

const setScannerScopes = () => {
  createForm.scopes = [...scannerScopes]
}

const setRuntimeScopes = () => {
  createForm.scopes = [...runtimeScopes]
}

const setAllScopes = () => {
  createForm.scopes = [...scannerScopes, ...runtimeScopes]
}

const handleCreate = async () => {
  if (!createForm.name.trim()) {
    message.warning('请填写 Token 名称')
    return
  }
  creating.value = true
  try {
    const data = await createScannerToken({
      name: createForm.name.trim(),
      scopes: createForm.scopes,
      allowed_ips: createForm.allowed_ips,
      max_upload_mb: Number(createForm.max_upload_mb || 50),
      max_concurrent_jobs: Number(createForm.max_concurrent_jobs || 2),
      created_by: localStorage.getItem('username') || 'admin',
    })
    createdToken.value = data.token
    createVisible.value = false
    tokenVisible.value = true
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || '创建接入 Token 失败')
  } finally {
    creating.value = false
  }
}

const handleRevoke = async (record) => {
  revokingId.value = record.id
  try {
    await revokeScannerToken(record.id)
    message.success('接入 Token 已吊销')
    await fetchTokens()
  } catch (error) {
    message.error(error.response?.data?.detail || '吊销接入 Token 失败')
  } finally {
    revokingId.value = ''
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
  fetchTokens()
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

.muted,
.hint {
  color: #8c8c8c;
  font-size: 12px;
}
</style>
