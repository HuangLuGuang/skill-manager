<template>
  <div>
    <a-page-header title="系统设置" sub-title="查看系统状态、数据目录与基础环境信息" />

    <a-card class="status-overview-card" title="系统状态总览" style="margin-top: 16px">
      <template #extra>
        <a-button type="primary" size="small" @click="fetchStatus" :loading="loading">刷新状态</a-button>
      </template>

      <div class="status-section">
        <div class="section-title">基础环境</div>
        <a-descriptions bordered size="small" :column="{ xs: 1, md: 2, xl: 3 }">
          <a-descriptions-item label="数据目录" :span="2">
            <span class="path-text">{{ systemInfo.data_dir || '-' }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="目录大小">{{ formatSize(systemInfo.data_dir_size || 0) }}</a-descriptions-item>
          <a-descriptions-item label="CPU">{{ formatCpu(systemInfo.cpu) }}</a-descriptions-item>
          <a-descriptions-item label="内存">{{ formatPercent(systemInfo.memory?.percent) }}</a-descriptions-item>
          <a-descriptions-item label="Logo 地址">
            <span class="path-text">{{ logoInfo.logo_url || '-' }}</span>
          </a-descriptions-item>
        </a-descriptions>
      </div>

      <div class="status-section">
        <div class="section-title">治理服务</div>
        <a-descriptions bordered size="small" :column="{ xs: 1, md: 2, xl: 3 }">
          <a-descriptions-item label="服务">{{ managerStatus.service || '-' }}</a-descriptions-item>
          <a-descriptions-item label="注册条目">{{ managerStatus.registry_entries ?? '-' }}</a-descriptions-item>
          <a-descriptions-item label="审核队列">{{ managerStatus.review_queue ?? '-' }}</a-descriptions-item>
          <a-descriptions-item label="签名密钥">
            <a-tag :color="managerStatus.signing_key_configured ? 'green' : 'orange'">
              {{ managerStatus.signing_key_configured ? '已配置' : '开发模式' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="运行时 Hooks">
            <a-tag :color="managerStatus.hooks_available ? 'blue' : 'default'">
              {{ managerStatus.hooks_available ? '可用' : '缺失' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="当前扫描模式">
            <a-tag :color="scanModeColor(managerStatus.scan_mode)">
              {{ managerStatus.scan_mode || '-' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="注册表目录" :span="2">
            <span class="path-text">{{ managerStatus.data_dir || '-' }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="策略文件">
            <span class="path-text">{{ managerStatus.policy_path || '-' }}</span>
          </a-descriptions-item>
        </a-descriptions>
      </div>

      <div class="status-section">
        <div class="section-title">分析与运行能力</div>
        <a-descriptions bordered size="small" :column="{ xs: 1, md: 2, xl: 3 }">
          <a-descriptions-item label="扫描器">
            <a-tag :color="managerStatus.scanner_available ? 'green' : 'default'">
              {{ managerStatus.scanner_available ? '可用' : '未安装' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="SkillSpector">
            <a-space wrap>
              <a-tag :color="skillspectorStatusColor">
                {{ skillspectorStatusText }}
              </a-tag>
              <span class="muted">{{ managerStatus.skillspector_version || '-' }}</span>
            </a-space>
          </a-descriptions-item>
          <a-descriptions-item label="Sandbox">
            <a-tag :color="sandboxStatusColor">{{ sandboxStatusText }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="Sandbox 后端">{{ managerStatus.sandbox_runtime || sandboxConfig.runtime || '-' }}</a-descriptions-item>
          <a-descriptions-item label="Sandbox 镜像">
            <span class="path-text">{{ sandboxConfig.image || '-' }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="LLM 分析">
            <a-tag :color="managerStatus.llm_enabled ? 'blue' : 'default'">
              {{ managerStatus.llm_enabled ? '已启用' : '未启用' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="LLM 提供方">{{ managerStatus.llm_provider || '-' }}</a-descriptions-item>
          <a-descriptions-item label="LLM 模型">{{ managerStatus.llm_model || '-' }}</a-descriptions-item>
          <a-descriptions-item label="LLM API Key">
            <a-tag :color="managerStatus.llm_api_key_configured ? 'green' : 'orange'">
              {{ managerStatus.llm_api_key_configured ? '已配置' : '未配置' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="LLM 接口" :span="3">
            <span class="path-text">{{ managerStatus.llm_api_base || '-' }}</span>
          </a-descriptions-item>
        </a-descriptions>
      </div>
    </a-card>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="12">
        <a-card title="LLM 配置">
          <a-form layout="vertical" :model="llmForm" @finish="saveLlmConfig">
            <a-form-item>
              <a-switch
                v-model:checked="llmForm.enabled"
                checked-children="启用"
                un-checked-children="关闭"
                :loading="savingLlm"
                @change="handleToggleLlmEnabled"
              />
              <div class="hint">这里切换会直接保存，下面的“保存 LLM 配置”主要用于其他字段。</div>
            </a-form-item>
            <a-form-item label="提供方">
              <a-select v-model:value="llmForm.provider">
                <a-select-option value="openai-compatible">openai-compatible</a-select-option>
                <a-select-option value="deepseek">deepseek</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="API Base URL">
              <a-input v-model:value="llmForm.api_base" placeholder="https://api.deepseek.com" />
              <div class="hint">配置文件：{{ llmConfig.config_path || '-' }}</div>
            </a-form-item>
            <a-form-item label="模型">
              <a-input v-model:value="llmForm.model" placeholder="deepseek-chat" />
            </a-form-item>
            <a-form-item label="超时时间（秒）">
              <a-input-number v-model:value="llmForm.timeout_seconds" :min="5" :max="180" style="width: 100%" />
            </a-form-item>
            <a-form-item label="分析文件数上限">
              <a-input-number v-model:value="llmForm.max_files" :min="1" :max="20" style="width: 100%" />
            </a-form-item>
            <a-form-item label="单文件截断字符数">
              <a-input-number v-model:value="llmForm.max_file_chars" :min="500" :max="20000" :step="500" style="width: 100%" />
            </a-form-item>
            <a-form-item label="SKILL.md 截断字符数">
              <a-input-number v-model:value="llmForm.max_manifest_chars" :min="2000" :max="50000" :step="1000" style="width: 100%" />
            </a-form-item>
            <a-form-item label="API Key">
              <a-input-password
                v-model:value="llmForm.api_key"
                placeholder="留空则保留现有 key"
                autocomplete="new-password"
              />
              <div class="hint">
                当前状态：{{ llmConfig.api_key_configured ? (llmConfig.api_key_masked || '已配置') : '未配置' }}
              </div>
            </a-form-item>
            <a-form-item>
              <a-checkbox v-model:checked="llmForm.clear_api_key">清除当前 API Key</a-checkbox>
            </a-form-item>
            <a-form-item>
              <a-space wrap>
                <a-button type="primary" html-type="submit" :loading="savingLlm">保存 LLM 配置</a-button>
                <a-button @click="fetchStatus" :disabled="savingLlm">重新加载</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="12">
        <a-card title="Sandbox 配置">
          <a-form layout="vertical" :model="sandboxForm" @finish="saveSandboxConfig">
            <a-form-item>
              <a-switch
                v-model:checked="sandboxForm.enabled"
                checked-children="启用"
                un-checked-children="关闭"
                :loading="savingSandbox"
                @change="handleToggleSandboxEnabled"
              />
              <div class="hint">切换后会立即保存；高风险 skill 的强制执行仍由策略页决定。</div>
            </a-form-item>
            <a-form-item label="后端类型">
              <a-select v-model:value="sandboxForm.runtime">
                <a-select-option value="docker">docker</a-select-option>
                <a-select-option value="remote">remote</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item v-if="sandboxForm.runtime === 'docker'" label="镜像">
              <a-select
                v-model:value="sandboxForm.image"
                show-search
                placeholder="选择本机 sandbox 镜像"
                :options="sandboxImageOptions"
                :loading="loading"
              />
              <div class="hint">只显示本机 Docker 镜像名包含 sandbox 的镜像。</div>
            </a-form-item>
            <template v-else>
              <a-form-item label="远程 Sandbox URL">
                <a-input v-model:value="sandboxForm.remote_url" placeholder="http://sandbox:8194" />
                <div class="hint">配置文件：{{ sandboxConfig.config_path || '-' }}</div>
              </a-form-item>
              <a-form-item label="远程 API Key">
                <a-input-password
                  v-model:value="sandboxForm.remote_api_key"
                  placeholder="留空则保留现有 key"
                  autocomplete="new-password"
                />
                <div class="hint">
                  当前状态：{{ sandboxConfig.remote_api_key_configured ? (sandboxConfig.remote_api_key_masked || '已配置') : '未配置' }}
                </div>
              </a-form-item>
              <a-form-item>
                <a-checkbox v-model:checked="sandboxForm.clear_remote_api_key">清除当前远程 API Key</a-checkbox>
              </a-form-item>
            </template>
            <a-form-item label="超时时间（秒）">
              <a-input-number v-model:value="sandboxForm.timeout_seconds" :min="1" :max="300" style="width: 100%" />
            </a-form-item>
            <a-form-item label="网络模式">
              <a-select v-model:value="sandboxForm.network_mode">
                <a-select-option value="none">none</a-select-option>
                <a-select-option value="bridge">bridge</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="内存限制">
              <a-input v-model:value="sandboxForm.memory_limit" placeholder="256m" />
            </a-form-item>
            <a-form-item label="CPU 限制">
              <a-input v-model:value="sandboxForm.cpu_limit" placeholder="1.0" />
            </a-form-item>
            <a-form-item label="进程数限制">
              <a-input-number v-model:value="sandboxForm.pids_limit" :min="1" :max="1024" style="width: 100%" />
            </a-form-item>
            <a-form-item>
              <a-checkbox v-model:checked="sandboxForm.read_only_rootfs">启用只读根文件系统</a-checkbox>
            </a-form-item>
            <a-form-item>
              <a-space wrap>
                <a-button type="primary" html-type="submit" :loading="savingSandbox">保存 Sandbox 配置</a-button>
                <a-button @click="fetchStatus" :disabled="savingSandbox">重新加载</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="12">
        <a-card title="操作">
          <a-space wrap>
            <a-button type="primary" @click="fetchStatus" :loading="loading">刷新状态</a-button>
            <a-button @click="$router.push('/policy')">打开策略配置</a-button>
            <a-button @click="$router.push('/audit')">查看审计日志</a-button>
          </a-space>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="12">
        <a-card title="当前说明">
          <a-list size="small" bordered :data-source="items">
            <template #renderItem="{ item }">
              <a-list-item>{{ item }}</a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import {
  getLlmConfig,
  getLogoInfo,
  getSandboxConfig,
  getAgentManagerSystemStatus,
  getSystemInfo,
  listSandboxImages,
  updateLlmConfig,
  updateSandboxConfig,
} from '../api'

const loading = ref(false)
const savingLlm = ref(false)
const savingSandbox = ref(false)
const systemInfo = ref({})
const logoInfo = ref({})
const managerStatus = ref({})
const llmConfig = ref({})
const sandboxConfig = ref({})
const sandboxImages = ref([])
const llmForm = reactive({
  enabled: false,
  provider: 'deepseek',
  api_base: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  timeout_seconds: 30,
  max_files: 6,
  max_file_chars: 3000,
  max_manifest_chars: 12000,
  api_key: '',
  clear_api_key: false,
})
const sandboxForm = reactive({
  enabled: false,
  runtime: 'docker',
  image: 'agent-manager-sandbox-runtime:latest',
  timeout_seconds: 15,
  network_mode: 'none',
  memory_limit: '256m',
  cpu_limit: '1.0',
  pids_limit: 64,
  read_only_rootfs: true,
  remote_url: '',
  remote_api_key: '',
  clear_remote_api_key: false,
})
const items = [
  'Starter backend 继续负责账号、登录、菜单和系统管理。',
  'Agent Manager API 负责智能体技能生命周期、审计和运行时治理。',
  '启用 LLM 分析后，提交技能时勾选“启用 LLM 分析”才会调用 OpenAI-compatible 接口；服务端也可以优先走模型网关隐私代理。',
  '当前页面已经同时汇总两侧状态，便于你判断环境是否完整。',
  'Sandbox 可以走本机 Docker，也可以走独立隔离执行服务；当前后端类型会显示在状态区。',
]

const formatSize = (size) => {
  let value = Number(size || 0)
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(2)} ${units[unitIndex]}`
}

const formatPercent = (value) => (value == null ? '-' : `${Number(value).toFixed(1)}%`)
const formatCpu = (cpu) => (cpu ? `${formatPercent(cpu.percent)} / ${cpu.count} cores` : '-')
const sandboxEnabled = computed(() => managerStatus.value.sandbox_enabled ?? sandboxConfig.value.enabled ?? false)
const sandboxStatusText = computed(() => {
  if (!sandboxEnabled.value) return '已关闭'
  return managerStatus.value.sandbox_available ? '可用' : '不可用'
})
const sandboxStatusColor = computed(() => {
  if (!sandboxEnabled.value) return 'default'
  return managerStatus.value.sandbox_available ? 'green' : 'red'
})
const skillspectorStatusText = computed(() => {
  if (!managerStatus.value.skillspector_enabled) return '未启用'
  return managerStatus.value.skillspector_available ? '可用' : '未安装'
})
const skillspectorStatusColor = computed(() => {
  if (!managerStatus.value.skillspector_enabled) return 'default'
  return managerStatus.value.skillspector_available ? 'green' : 'orange'
})
const scanModeColor = (value) =>
  ({
    'scanner + llm': 'green',
    'scanner only': 'blue',
    'llm only': 'orange',
    'manifest only': 'default',
  }[value] || 'default')
const sandboxImageOptions = computed(() => {
  const values = new Set(sandboxImages.value)
  if (sandboxForm.image) values.add(sandboxForm.image)
  return [...values].map((value) => ({ value, label: value }))
})

const fetchStatus = async () => {
  loading.value = true
  try {
    const [sys, logo, manager, llm, sandbox, images] = await Promise.all([
      getSystemInfo(),
      getLogoInfo(),
      getAgentManagerSystemStatus(),
      getLlmConfig(),
      getSandboxConfig(),
      listSandboxImages(),
    ])
    systemInfo.value = sys || {}
    logoInfo.value = logo || {}
    managerStatus.value = manager || {}
    llmConfig.value = llm || {}
    sandboxConfig.value = sandbox || {}
    sandboxImages.value = images?.images || []
    llmForm.enabled = llm?.enabled ?? false
    llmForm.provider = llm?.provider || 'deepseek'
    llmForm.api_base = llm?.api_base || 'https://api.deepseek.com'
    llmForm.model = llm?.model || 'deepseek-chat'
    llmForm.timeout_seconds = llm?.timeout_seconds ?? 30
    llmForm.max_files = llm?.max_files ?? 6
    llmForm.max_file_chars = llm?.max_file_chars ?? 3000
    llmForm.max_manifest_chars = llm?.max_manifest_chars ?? 12000
    llmForm.api_key = ''
    llmForm.clear_api_key = false
    sandboxForm.enabled = sandbox?.enabled ?? false
    sandboxForm.runtime = sandbox?.runtime || 'docker'
    sandboxForm.image = sandbox?.image || 'agent-manager-sandbox-runtime:latest'
    sandboxForm.timeout_seconds = sandbox?.timeout_seconds ?? 15
    sandboxForm.network_mode = sandbox?.network_mode || 'none'
    sandboxForm.memory_limit = sandbox?.memory_limit || '256m'
    sandboxForm.cpu_limit = sandbox?.cpu_limit || '1.0'
    sandboxForm.pids_limit = sandbox?.pids_limit ?? 64
    sandboxForm.read_only_rootfs = sandbox?.read_only_rootfs ?? true
    sandboxForm.remote_url = sandbox?.remote_url || ''
    sandboxForm.remote_api_key = ''
    sandboxForm.clear_remote_api_key = false
  } catch (error) {
    message.error(extractErrorMsg(error, '获取系统状态失败'))
  } finally {
    loading.value = false
  }
}

const buildLlmPayload = () => ({
  enabled: llmForm.enabled,
  provider: llmForm.provider,
  api_base: llmForm.api_base,
  model: llmForm.model,
  timeout_seconds: Number(llmForm.timeout_seconds || 30),
  max_files: Number(llmForm.max_files || 6),
  max_file_chars: Number(llmForm.max_file_chars || 3000),
  max_manifest_chars: Number(llmForm.max_manifest_chars || 12000),
  api_key: llmForm.api_key || null,
  clear_api_key: llmForm.clear_api_key,
})

const extractErrorMsg = (error, fallback) => {
  const detail = error.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(e => e.msg).join('; ')
  return fallback
}

const saveLlmConfig = async (successText) => {
  savingLlm.value = true
  try {
    const result = await updateLlmConfig(buildLlmPayload())
    llmConfig.value = result || {}
    message.success(typeof successText === 'string' ? successText : '修改成功')
    await fetchStatus()
  } catch (error) {
    message.error(extractErrorMsg(error, '保存 LLM 配置失败'))
  } finally {
    savingLlm.value = false
  }
}

const handleToggleLlmEnabled = async () => {
  await saveLlmConfig(llmForm.enabled ? 'LLM 已启用' : 'LLM 已禁用')
}

const buildSandboxPayload = () => ({
  enabled: sandboxForm.enabled,
  runtime: sandboxForm.runtime,
  image: sandboxForm.image,
  timeout_seconds: Number(sandboxForm.timeout_seconds || 15),
  network_mode: sandboxForm.network_mode,
  memory_limit: sandboxForm.memory_limit,
  cpu_limit: sandboxForm.cpu_limit,
  pids_limit: Number(sandboxForm.pids_limit || 64),
  read_only_rootfs: sandboxForm.read_only_rootfs,
  remote_url: sandboxForm.remote_url || null,
  remote_api_key: sandboxForm.remote_api_key || null,
  clear_remote_api_key: sandboxForm.clear_remote_api_key,
})

const saveSandboxConfig = async () => {
  savingSandbox.value = true
  try {
    const result = await updateSandboxConfig(buildSandboxPayload())
    sandboxConfig.value = result || {}
    message.success('Sandbox 配置已保存')
    await fetchStatus()
  } catch (error) {
    message.error(extractErrorMsg(error, '保存 Sandbox 配置失败'))
    await fetchStatus()
  } finally {
    savingSandbox.value = false
  }
}

const handleToggleSandboxEnabled = async () => {
  savingSandbox.value = true
  try {
    const result = await updateSandboxConfig(buildSandboxPayload())
    sandboxConfig.value = result || {}
    message.success(sandboxForm.enabled ? 'Sandbox 已启用' : 'Sandbox 已关闭')
    await fetchStatus()
  } catch (error) {
    message.error(extractErrorMsg(error, '切换 Sandbox 状态失败'))
    await fetchStatus()
  } finally {
    savingSandbox.value = false
  }
}

onMounted(fetchStatus)
</script>

<style scoped>
.status-overview-card :deep(.ant-card-body) {
  padding: 16px;
}

.status-section + .status-section {
  margin-top: 16px;
}

.section-title {
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
  color: #16324f;
}

.status-overview-card :deep(.ant-descriptions-item-label) {
  width: 132px;
  color: #475569;
  white-space: nowrap;
  background: #f8fafc;
}

.status-overview-card :deep(.ant-descriptions-item-content) {
  min-width: 0;
  color: #1f2937;
  overflow-wrap: anywhere;
}

.path-text {
  color: #475569;
  overflow-wrap: anywhere;
}

.muted {
  color: #64748b;
}

.hint {
  margin-top: 8px;
  color: #8c8c8c;
  font-size: 12px;
}
</style>
