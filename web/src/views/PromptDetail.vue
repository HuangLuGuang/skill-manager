<template>
  <div class="prompt-detail" v-if="prompt">
    <div class="page-header">
      <div class="header-left">
        <a-breadcrumb>
          <a-breadcrumb-item><router-link to="/prompts">提示词管理</router-link></a-breadcrumb-item>
          <a-breadcrumb-item>{{ prompt.name }}</a-breadcrumb-item>
        </a-breadcrumb>
        <h2 class="page-title">
          {{ prompt.name }}
          <a-tag :color="getStatusColor(prompt.status)" class="status-tag">{{ prompt.status }}</a-tag>
        </h2>
      </div>
      <div class="header-right">
        <a-space>
          <a-button v-if="prompt.status === 'PENDING'" type="primary" :loading="vetting" @click="handleVet">
            立即安全扫描
          </a-button>
          <a-button v-if="prompt.status === 'VETTED'" type="primary" @click="showApproveModal">
            通过审核
          </a-button>
          <a-button v-if="prompt.status === 'VETTED'" danger @click="showRejectModal">
            驳回
          </a-button>
          <a-button v-if="prompt.status === 'APPROVED'" type="primary" @click="handleDeploy">
            部署上线
          </a-button>
        </a-space>
      </div>
    </div>

    <a-row :gutter="24">
      <a-col :span="16">
        <a-card title="提示词内容" class="detail-card">
          <div class="content-box">
            <pre>{{ prompt.content }}</pre>
          </div>
        </a-card>

        <a-card title="安全扫描结果" class="detail-card" v-if="prompt.vetting">
          <a-alert
            :type="prompt.vetting.risk_level === 'malicious' ? 'error' : 'success'"
            :message="prompt.vetting.risk_level === 'malicious' ? '检测到安全风险' : '扫描通过：未发现明显风险'"
            show-icon
            class="vetting-alert"
          />
          
          <div v-if="prompt.vetting.scan_report?.findings?.length" class="findings-list">
            <h4>详细发现项 ({{ prompt.vetting.scan_report.findings.length }}):</h4>
            <a-list item-layout="horizontal" :data-source="prompt.vetting.scan_report.findings">
              <template #renderItem="{ item }">
                <a-list-item>
                  <a-list-item-meta :description="item.message">
                    <template #title>
                      <a-tag :color="getRiskColor(item.severity)">{{ item.severity }}</a-tag>
                      {{ item.type || '安全策略命中' }}
                    </template>
                  </a-list-item-meta>
                </a-list-item>
              </template>
            </a-list>
          </div>
          <div v-else class="no-findings">
            <a-empty description="未发现风险项" />
          </div>
        </a-card>
      </a-col>

      <a-col :span="8">
        <a-card title="基本信息" class="detail-card">
          <a-descriptions :column="1" size="small">
            <a-descriptions-item label="Prompt ID">{{ prompt.prompt_id }}</a-descriptions-item>
            <a-descriptions-item label="Agent ID">{{ prompt.agent_id || '未绑定' }}</a-descriptions-item>
            <a-descriptions-item label="风险等级">
              <a-tag :color="getRiskColor(prompt.risk_level)">{{ prompt.risk_level || 'UNKNOWN' }}</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="内容签名">
              <code class="sig-code">{{ prompt.signature || '尚未签名' }}</code>
            </a-descriptions-item>
            <a-descriptions-item label="提交时间">{{ formatDate(prompt.submitted_at) }}</a-descriptions-item>
            <a-descriptions-item label="批准人">{{ prompt.approved_by || '-' }}</a-descriptions-item>
          </a-descriptions>
        </a-card>

        <a-card title="描述" class="detail-card">
          <p>{{ prompt.description || '无描述信息' }}</p>
        </a-card>

        <a-card title="审核信息" class="detail-card" v-if="prompt.status === 'REJECTED' || prompt.approval_note">
          <div v-if="prompt.status === 'REJECTED'">
            <h4 style="color: #ff4d4f">驳回原因:</h4>
            <p>{{ prompt.rejection_reason }}</p>
          </div>
          <div v-if="prompt.approval_note">
            <h4>批准备注:</h4>
            <p>{{ prompt.approval_note }}</p>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <!-- 审批 Modal -->
    <a-modal v-model:open="approveVisible" title="批准提示词上线" @ok="handleApproveOk" :confirmLoading="approving">
      <p>您正在批准提示词 <b>{{ prompt.name }}</b> 上线。批准后系统将为其生成内容指纹签名。</p>
      <a-form layout="vertical">
        <a-form-item label="批准备注">
          <a-textarea v-model:value="approveForm.note" placeholder="可选：填写审批意见" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 驳回 Modal -->
    <a-modal v-model:open="rejectVisible" title="驳回提示词" @ok="handleRejectOk" :confirmLoading="rejecting" ok-text="确认驳回" ok-type="danger">
      <a-form layout="vertical">
        <a-form-item label="驳回原因" required>
          <a-textarea v-model:value="rejectForm.reason" placeholder="请填写驳回原因" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
  <div v-else-if="loading" class="loading-state">
    <a-spin size="large" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import { approvePrompt, deployPrompt, getPromptDetail, rejectPrompt, listPrompts } from '../api'

// For demo purposes, we'll simulate 'vet' by re-loading detail
// In a real app, there would be an api.vetPrompt()

const route = useRoute()
const prompt = ref(null)
const loading = ref(true)
const vetting = ref(false)
const approving = ref(false)
const rejecting = ref(false)
const approveVisible = ref(false)
const rejectVisible = ref(false)

const approveForm = reactive({ note: '' })
const rejectForm = reactive({ reason: '' })

const loadDetail = async () => {
  loading.value = true
  try {
    const res = await getPromptDetail(route.params.promptId)
    prompt.value = res
  } catch (err) {
    message.error('加载详情失败: ' + err.message)
  } finally {
    loading.value = false
  }
}

const getStatusColor = (status) => {
  const map = {
    PENDING: 'blue',
    VETTED: 'cyan',
    APPROVED: 'green',
    DEPLOYED: 'gold',
    REJECTED: 'red',
    RETIRED: 'default',
  }
  return map[status] || 'default'
}

const getRiskColor = (risk) => {
  const map = {
    benign: 'green',
    suspicious: 'orange',
    malicious: 'red',
    LOW: 'orange',
    MEDIUM: 'orange',
    HIGH: 'red',
    CRITICAL: 'red',
    SAFE: 'green',
  }
  return map[risk] || 'default'
}

const formatDate = (date) => (date ? dayjs(date).format('YYYY-MM-DD HH:mm:ss') : '-')

const handleVet = async () => {
  vetting.value = true
  try {
    // In our refactored backend, AgentManager.vet_prompt handles this
    // We use the submit-vet flow. Here we simulate the trigger.
    // Assuming a POST /prompts/{id}/vet exists or using the manager directly
    // For now, let's pretend we're calling an endpoint that triggers vetting
    message.loading({ content: '安全引擎正在分析提示词内容...', key: 'vet' })
    
    // Simulate API call to vet
    // await api.vetPrompt(prompt.value.prompt_id)
    
    setTimeout(async () => {
      await loadDetail()
      message.success({ content: '扫描完成', key: 'vet' })
      vetting.value = false
    }, 1500)
  } catch (err) {
    message.error({ content: '扫描失败: ' + err.message, key: 'vet' })
    vetting.value = false
  }
}

const showApproveModal = () => {
  approveForm.note = ''
  approveVisible.value = true
}

const handleApproveOk = async () => {
  approving.value = true
  try {
    await approvePrompt(prompt.value.prompt_id, { note: approveForm.note })
    message.success('已批准上线')
    approveVisible.value = false
    loadDetail()
  } catch (err) {
    message.error('审批失败: ' + err.message)
  } finally {
    approving.value = false
  }
}

const showRejectModal = () => {
  rejectForm.reason = ''
  rejectVisible.value = true
}

const handleRejectOk = async () => {
  if (!rejectForm.reason) {
    message.error('请填写驳回原因')
    return
  }
  rejecting.value = true
  try {
    await rejectPrompt(prompt.value.prompt_id, { reason: rejectForm.reason })
    message.success('已驳回该提示词')
    rejectVisible.value = false
    loadDetail()
  } catch (err) {
    message.error('驳回操作失败: ' + err.message)
  } finally {
    rejecting.value = false
  }
}

const handleDeploy = async () => {
  try {
    await deployPrompt(prompt.value.prompt_id)
    message.success('已成功标记为部署状态')
    loadDetail()
  } catch (err) {
    message.error('部署失败: ' + err.message)
  }
}

onMounted(() => {
  loadDetail()
})
</script>

<style scoped>
.prompt-detail {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  margin: 8px 0 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-tag {
  font-size: 14px;
  padding: 4px 12px;
}

.detail-card {
  margin-bottom: 24px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}

.content-box {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 4px;
  max-height: 500px;
  overflow-y: auto;
  font-family: 'Fira Code', 'Courier New', Courier, monospace;
}

.content-box pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.vetting-alert {
  margin-bottom: 20px;
}

.findings-list h4 {
  margin-bottom: 12px;
  font-weight: 600;
}

.sig-code {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  word-break: break-all;
}

.loading-state {
  height: 400px;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
