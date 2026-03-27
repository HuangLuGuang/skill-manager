<template>
  <div>
    <a-page-header title="系统设置" sub-title="查看系统状态、数据目录与基础环境信息" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :span="24">
        <a-card title="系统状态">
          <a-row :gutter="[24, 16]">
            <a-col :xs="24" :xl="12">
              <div class="section-title">后台基础服务状态</div>
              <a-descriptions :column="1" size="small">
                <a-descriptions-item label="数据目录">{{ systemInfo.data_dir || '-' }}</a-descriptions-item>
                <a-descriptions-item label="目录大小">{{ formatSize(systemInfo.data_dir_size || 0) }}</a-descriptions-item>
                <a-descriptions-item label="Logo 地址">{{ logoInfo.logo_url || '-' }}</a-descriptions-item>
                <a-descriptions-item label="CPU">{{ formatCpu(systemInfo.cpu) }}</a-descriptions-item>
                <a-descriptions-item label="内存">{{ formatPercent(systemInfo.memory?.percent) }}</a-descriptions-item>
              </a-descriptions>
            </a-col>

            <a-col :xs="24" :xl="12">
              <div class="section-title">治理服务状态</div>
              <a-descriptions :column="1" size="small">
                <a-descriptions-item label="服务">{{ managerStatus.service || '-' }}</a-descriptions-item>
                <a-descriptions-item label="注册表目录">{{ managerStatus.data_dir || '-' }}</a-descriptions-item>
                <a-descriptions-item label="策略文件">{{ managerStatus.policy_path || '-' }}</a-descriptions-item>
                <a-descriptions-item label="注册条目">{{ managerStatus.registry_entries ?? '-' }}</a-descriptions-item>
                <a-descriptions-item label="审核队列">{{ managerStatus.review_queue ?? '-' }}</a-descriptions-item>
                <a-descriptions-item label="签名密钥">
                  <a-tag :color="managerStatus.signing_key_configured ? 'green' : 'orange'">
                    {{ managerStatus.signing_key_configured ? '已配置' : '开发模式' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="扫描器">
                  <a-tag :color="managerStatus.scanner_available ? 'green' : 'default'">
                    {{ managerStatus.scanner_available ? '可用' : '未安装' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="当前扫描模式">
                  <a-tag :color="scanModeColor(managerStatus.scan_mode)">
                    {{ managerStatus.scan_mode || '-' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="运行时 Hooks">
                  <a-tag :color="managerStatus.hooks_available ? 'blue' : 'default'">
                    {{ managerStatus.hooks_available ? '可用' : '缺失' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="LLM 分析">
                  <a-tag :color="managerStatus.llm_enabled ? 'blue' : 'default'">
                    {{ managerStatus.llm_enabled ? '已启用' : '未启用' }}
                  </a-tag>
                </a-descriptions-item>
                <a-descriptions-item label="LLM 提供方">{{ managerStatus.llm_provider || '-' }}</a-descriptions-item>
                <a-descriptions-item label="LLM 接口">{{ managerStatus.llm_api_base || '-' }}</a-descriptions-item>
                <a-descriptions-item label="LLM 模型">{{ managerStatus.llm_model || '-' }}</a-descriptions-item>
                <a-descriptions-item label="LLM API Key">
                  <a-tag :color="managerStatus.llm_api_key_configured ? 'green' : 'orange'">
                    {{ managerStatus.llm_api_key_configured ? '已配置' : '未配置' }}
                  </a-tag>
                </a-descriptions-item>
              </a-descriptions>
            </a-col>
          </a-row>
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :span="24">
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
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import { getLlmConfig, getLogoInfo, getSkillManagerSystemStatus, getSystemInfo, updateLlmConfig } from '../api'

const loading = ref(false)
const savingLlm = ref(false)
const systemInfo = ref({})
const logoInfo = ref({})
const managerStatus = ref({})
const llmConfig = ref({})
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
const items = [
  'Starter backend 继续负责账号、登录、菜单和系统管理。',
  'Skill Manager API 负责 skill 生命周期、审计和运行时治理。',
  '启用 LLM 分析后，提交 Skill 时勾选“启用 LLM 分析”才会调用 DeepSeek 接口。',
  '当前页面已经同时汇总两侧状态，便于你判断环境是否完整。',
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
    const [sys, logo, manager, llm] = await Promise.all([
      getSystemInfo(),
      getLogoInfo(),
      getSkillManagerSystemStatus(),
      getLlmConfig(),
    ])
    systemInfo.value = sys || {}
    logoInfo.value = logo || {}
    managerStatus.value = manager || {}
    llmConfig.value = llm || {}
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
  } catch (error) {
    message.error(error.response?.data?.detail || '获取系统状态失败')
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

const saveLlmConfig = async (successText = 'LLM 配置已保存') => {
  savingLlm.value = true
  try {
    const result = await updateLlmConfig(buildLlmPayload())
    llmConfig.value = result || {}
    message.success(successText)
    await fetchStatus()
  } catch (error) {
    message.error(error.response?.data?.detail || '保存 LLM 配置失败')
  } finally {
    savingLlm.value = false
  }
}

const handleToggleLlmEnabled = async () => {
  await saveLlmConfig(llmForm.enabled ? 'LLM 已启用' : 'LLM 已禁用')
}

onMounted(fetchStatus)
</script>

<style scoped>
.section-title {
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
  color: #1f1f1f;
}

.hint {
  margin-top: 8px;
  color: #8c8c8c;
  font-size: 12px;
}
</style>
