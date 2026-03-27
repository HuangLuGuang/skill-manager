<template>
  <div>
    <a-page-header title="提交 Skill" sub-title="上传 skill ZIP 并触发 vetting" />

    <a-card style="margin-top: 16px">
      <a-alert
        type="info"
        show-icon
        message="提交说明"
        description="ZIP 包根目录应包含 SKILL.md。提交动作会走受登录保护的 /api/v1/skills/submit-zip 接口。若勾选“启用 LLM 分析”，请先在“系统设置”里配置 DeepSeek 接口和 API Key。"
        style="margin-bottom: 16px"
      />

      <a-form layout="vertical" :model="formState" @finish="handleSubmit">
        <a-form-item label="Skill ZIP 包">
          <a-upload
            accept=".zip,application/zip"
            :show-upload-list="false"
            :before-upload="handleBeforeUpload"
          >
            <a-button>选择 ZIP 文件</a-button>
          </a-upload>
          <div class="field-hint">{{ selectedFile ? selectedFile.name : '尚未选择文件' }}</div>
        </a-form-item>
        <a-form-item label="作者" name="author">
          <a-input v-model:value="formState.author" placeholder="作者 / 提交方" />
        </a-form-item>
        <a-form-item label="来源" name="origin">
          <a-select v-model:value="formState.origin">
            <a-select-option value="local">local</a-select-option>
            <a-select-option value="github">github</a-select-option>
            <a-select-option value="clawhub">clawhub</a-select-option>
            <a-select-option value="internal">internal</a-select-option>
            <a-select-option value="unknown">unknown</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-tooltip :title="behavioralTooltip">
              <span>
                <a-checkbox v-model:checked="formState.useBehavioral">启用行为分析</a-checkbox>
              </span>
            </a-tooltip>
            <a-tooltip :title="llmTooltip">
              <span>
                <a-checkbox v-model:checked="formState.useLlm" :disabled="!llmReadyForSubmit">启用 LLM 分析</a-checkbox>
              </span>
            </a-tooltip>
          </a-space>
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" html-type="submit" :loading="submitting">提交</a-button>
            <a-button @click="resetForm" :disabled="submitting">重置</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </a-card>

    <a-card v-if="submitResult" title="提交结果" style="margin-top: 16px">
      <a-descriptions :column="2" size="small" bordered>
        <a-descriptions-item label="Skill ID">{{ submitResult.skill_id }}</a-descriptions-item>
        <a-descriptions-item label="名称">{{ submitResult.name }}</a-descriptions-item>
        <a-descriptions-item label="状态">
          <a-tag :color="statusColor(submitResult.status)">{{ submitResult.status }}</a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="风险">
          <a-tag :color="riskColor(submitResult.risk_level)">{{ submitResult.risk_level || '-' }}</a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="发现项">{{ submitResult.findings_count }}</a-descriptions-item>
        <a-descriptions-item label="结果说明">{{ submitResult.message }}</a-descriptions-item>
      </a-descriptions>

      <a-space style="margin-top: 16px">
        <a-button type="primary" @click="goToDetail">查看详情</a-button>
        <a-button @click="$router.push('/skills')">返回列表</a-button>
      </a-space>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'

import { getSkillManagerSystemStatus, submitSkillZip } from '../api'

const router = useRouter()
const submitting = ref(false)
const loadingSystemStatus = ref(false)
const selectedFile = ref(null)
const submitResult = ref(null)
const managerStatus = ref({})

const formState = reactive({
  author: localStorage.getItem('username') || 'admin',
  origin: 'local',
  useBehavioral: false,
  useLlm: false,
})

const llmEnabledInSystem = computed(() => Boolean(managerStatus.value?.llm_enabled))
const llmReadyForSubmit = computed(
  () => Boolean(managerStatus.value?.llm_enabled && managerStatus.value?.llm_api_key_configured),
)
const llmTooltip = computed(() => {
  if (loadingSystemStatus.value) return '正在读取系统设置中的 LLM 状态'
  if (!managerStatus.value || Object.keys(managerStatus.value).length === 0) {
    return '尚未获取系统设置，请稍后重试'
  }
  if (!llmEnabledInSystem.value) {
    return '系统设置里没有启用 LLM 分析，所以这里不能勾选'
  }
  if (!managerStatus.value?.llm_api_key_configured) {
    return '系统设置里尚未配置 LLM API Key，所以这里不能勾选'
  }
  return '启用后会调用系统设置里的 DeepSeek 配置，对技能做补充分析'
})
const behavioralTooltip =
  '启用后会额外扫描 scripts、references、prompts 等目录中的文本代码文件，检测命令执行、敏感文件访问、动态执行等可疑模式'

const fetchSystemStatus = async () => {
  loadingSystemStatus.value = true
  try {
    managerStatus.value = await getSkillManagerSystemStatus()
    if (!llmReadyForSubmit.value) {
      formState.useLlm = false
    }
  } catch (_error) {
    managerStatus.value = {}
    formState.useLlm = false
  } finally {
    loadingSystemStatus.value = false
  }
}

const handleBeforeUpload = (file) => {
  const isZip = file.type === 'application/zip' || file.name.toLowerCase().endsWith('.zip')
  if (!isZip) {
    message.error('只能上传 ZIP 文件')
    return false
  }
  selectedFile.value = file
  return false
}

const resetForm = () => {
  selectedFile.value = null
  submitResult.value = null
  formState.author = localStorage.getItem('username') || 'admin'
  formState.origin = 'local'
  formState.useBehavioral = false
  formState.useLlm = false
}

const handleSubmit = async () => {
  if (!selectedFile.value) {
    message.warning('请先选择 skill ZIP 文件')
    return
  }

  const formData = new FormData()
  formData.append('file', selectedFile.value)

  submitting.value = true
  try {
    const result = await submitSkillZip(formData, {
      author: formState.author || undefined,
      origin: formState.origin,
      use_behavioral: formState.useBehavioral,
      use_llm: formState.useLlm,
    })
    submitResult.value = result
    message.success('提交成功')
  } catch (error) {
    message.error(error.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

const goToDetail = () => {
  if (!submitResult.value?.skill_id) return
  router.push(`/skills/${submitResult.value.skill_id}`)
}

const statusColor = (value) =>
  ({
    VETTED: 'orange',
    APPROVED: 'green',
    DEPLOYED: 'blue',
    REJECTED: 'red',
    RETIRED: 'default',
  }[value] || 'default')

const riskColor = (value) =>
  ({
    SAFE: 'green',
    LOW: 'green',
    MEDIUM: 'orange',
    HIGH: 'red',
    EXTREME: 'magenta',
  }[value] || 'default')

onMounted(fetchSystemStatus)
</script>

<style scoped>
.field-hint {
  margin-top: 8px;
  color: #8c8c8c;
  font-size: 12px;
}
</style>
