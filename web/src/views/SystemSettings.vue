<template>
  <div>
    <a-page-header title="系统总览" sub-title="查看系统状态、数据目录与基础环境信息" />

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
          <a-descriptions-item label="深度扫描">
            <a-space wrap>
              <a-tag :color="skillspectorStatusColor">
                {{ skillspectorStatusText }}
              </a-tag>
            </a-space>
          </a-descriptions-item>
          <a-descriptions-item label="Sandbox">
            <a-tag :color="sandboxStatusColor">{{ sandboxStatusText }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="Sandbox 后端">{{ managerStatus.sandbox_runtime || sandboxConfig.runtime || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="sandboxTargetLabel">
            <span class="path-text">{{ sandboxTargetValue }}</span>
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

  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'

import {
  getLlmConfig,
  getLogoInfo,
  getSandboxConfig,
  getAgentManagerSystemStatus,
  getSystemInfo,
} from '../api'

const loading = ref(false)
const systemInfo = ref({})
const logoInfo = ref({})
const managerStatus = ref({})
const llmConfig = ref({})
const sandboxConfig = ref({})

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
const sandboxRuntime = computed(() => managerStatus.value.sandbox_runtime || sandboxConfig.value.runtime || '')
const sandboxTargetLabel = computed(() => sandboxRuntime.value === 'remote' ? 'Sandbox 服务' : 'Sandbox 镜像')
const sandboxTargetValue = computed(() =>
  sandboxRuntime.value === 'remote'
    ? (sandboxConfig.value.remote_url || 'http://sandbox:8194')
    : (sandboxConfig.value.image || '-'),
)
const skillspectorStatusText = computed(() => {
  return managerStatus.value.skillspector_available ? '可用' : '未安装'
})
const skillspectorStatusColor = computed(() => {
  return managerStatus.value.skillspector_available ? 'green' : 'orange'
})
const scanModeColor = (value) =>
  ({
    'scanner + llm': 'green',
    'scanner only': 'blue',
    'llm only': 'orange',
    'manifest only': 'default',
  }[value] || 'default')
const fetchStatus = async () => {
  loading.value = true
  try {
    const [sys, logo, manager, llm, sandbox] = await Promise.all([
      getSystemInfo(),
      getLogoInfo(),
      getAgentManagerSystemStatus(),
      getLlmConfig(),
      getSandboxConfig(),
    ])
    systemInfo.value = sys || {}
    logoInfo.value = logo || {}
    managerStatus.value = manager || {}
    llmConfig.value = llm || {}
    sandboxConfig.value = sandbox || {}
  } catch (error) {
    message.error(extractErrorMsg(error, '获取系统状态失败'))
  } finally {
    loading.value = false
  }
}

const extractErrorMsg = (error, fallback) => {
  const detail = error.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(e => e.msg).join('; ')
  return fallback
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
