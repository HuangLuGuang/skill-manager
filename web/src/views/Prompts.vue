<template>
  <div class="prompts-view">
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title">提示词管理 (Prompt Registry)</h2>
        <p class="page-desc">对 AI Agent 的系统提示词进行版本化管理、安全审计与生命周期治理。</p>
      </div>
      <div class="header-right">
        <a-button type="primary" @click="submitVisible = true">
          <template #icon><PlusOutlined /></template>
          提交新提示词
        </a-button>
      </div>
    </div>

    <a-card class="filter-card">
      <a-form layout="inline">
        <a-form-item label="提示词名称">
          <a-input v-model:value="filters.name" placeholder="模糊搜索" allow-clear @pressEnter="handleSearch" />
        </a-form-item>
        <a-form-item label="状态">
          <a-select v-model:value="filters.status" placeholder="全部" style="width: 120px" allow-clear @change="handleSearch">
            <a-select-option value="PENDING">待定 (PENDING)</a-select-option>
            <a-select-option value="VETTED">已扫描 (VETTED)</a-select-option>
            <a-select-option value="APPROVED">已批准 (APPROVED)</a-select-option>
            <a-select-option value="DEPLOYED">已部署 (DEPLOYED)</a-select-option>
            <a-select-option value="REJECTED">已驳回 (REJECTED)</a-select-option>
            <a-select-option value="RETIRED">已停用 (RETIRED)</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="Agent ID">
          <a-input v-model:value="filters.agent_id" placeholder="所属 Agent" allow-clear @pressEnter="handleSearch" />
        </a-form-item>
        <a-form-item>
          <a-button type="primary" @click="handleSearch">查询</a-button>
          <a-button style="margin-left: 8px" @click="resetFilters">重置</a-button>
        </a-form-item>
      </a-form>
    </a-card>

    <a-table
      :columns="columns"
      :data-source="prompts"
      :loading="loading"
      :pagination="pagination"
      @change="handleTableChange"
      row-key="prompt_id"
      class="prompts-table"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'">
          <router-link :to="`/prompts/${record.prompt_id}`" class="prompt-name-link">
            {{ record.name }}
          </router-link>
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag :color="getStatusColor(record.status)">
            {{ record.status }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'risk_level'">
          <a-tag :color="getRiskColor(record.risk_level)">
            {{ record.risk_level || 'UNKNOWN' }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'submitted_at'">
          {{ formatDate(record.submitted_at) }}
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space>
            <a @click="$router.push(`/prompts/${record.prompt_id}`)">详情</a>
            <a-divider type="vertical" />
            <a-dropdown>
              <a class="ant-dropdown-link" @click.prevent>
                操作 <DownOutlined />
              </a>
              <template #overlay>
                <a-menu>
                  <a-menu-item v-if="record.status === 'PENDING'" @click="handleVet(record)">安全扫描</a-menu-item>
                  <a-menu-item v-if="record.status === 'VETTED'" @click="showApproveModalDirect(record)">通过审核</a-menu-item>
                  <a-menu-item v-if="record.status === 'VETTED'" @click="showRejectModalDirect(record)" danger>驳回</a-menu-item>
                  <a-menu-item v-if="record.status === 'APPROVED'" @click="handleDeploy(record)">立即部署</a-menu-item>
                  <a-menu-item v-if="['APPROVED', 'DEPLOYED'].includes(record.status)" @click="showRetireModal(record)" danger>停用提示词</a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </a-space>
        </template>
      </template>
    </a-table>

    <!-- 提交提示词 Modal -->
    <a-modal v-model:open="submitVisible" title="提交新提示词" @ok="handleSubmitOk" :confirmLoading="submitting" width="700px">
      <a-form :model="submitForm" layout="vertical">
        <a-form-item label="提示词名称" required>
          <a-input v-model:value="submitForm.name" placeholder="例如: customer-service-v1" />
        </a-form-item>
        <a-form-item label="所属 Agent ID">
          <a-input v-model:value="submitForm.agent_id" placeholder="可选，该提示词所属的 Agent" />
        </a-form-item>
        <a-form-item label="提示词内容 (Content)" required>
          <a-textarea v-model:value="submitForm.content" :rows="10" placeholder="请输入完整系统提示词..." />
        </a-form-item>
        <a-form-item label="描述 (Description)">
          <a-textarea v-model:value="submitForm.description" :rows="2" placeholder="简要说明此提示词的用途" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 停用提示词 Modal -->
    <a-modal v-model:open="retireVisible" title="确认停用提示词" @ok="handleRetireOk" :confirmLoading="retiring" ok-text="确认停用" ok-type="danger">
      <p>您确定要停用提示词 <b>{{ currentRecord?.name }}</b> 吗？停用后 Agent 将无法加载此内容。</p>
      <a-form layout="vertical">
        <a-form-item label="停用原因" required>
          <a-input v-model:value="retireForm.reason" placeholder="请输入停用原因" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 审批 Modal -->
    <a-modal v-model:open="approveVisible" title="批准提示词上线" @ok="handleApproveOk" :confirmLoading="approving">
      <p>您正在批准提示词 <b>{{ currentRecord?.name }}</b> 上线。批准后系统会记录内容指纹，用于后续完整性校验。</p>
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
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { DownOutlined, PlusOutlined } from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { approvePrompt, deployPrompt, listPrompts, rejectPrompt, retirePrompt, submitPrompt } from '../api'

const loading = ref(false)
const submitting = ref(false)
const retiring = ref(false)
const approving = ref(false)
const rejecting = ref(false)
const submitVisible = ref(false)
const retireVisible = ref(false)
const approveVisible = ref(false)
const rejectVisible = ref(false)
const prompts = ref([])
const currentRecord = ref(null)

const filters = reactive({
  name: '',
  status: undefined,
  agent_id: '',
})

const pagination = reactive({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
})

const submitForm = reactive({
  name: '',
  agent_id: '',
  content: '',
  description: '',
})

const retireForm = reactive({
  reason: '',
})

const approveForm = reactive({
  note: '',
})

const rejectForm = reactive({
  reason: '',
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: 'Agent ID', dataIndex: 'agent_id', key: 'agent_id' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '风险等级', dataIndex: 'risk_level', key: 'risk_level' },
  { title: '提交时间', dataIndex: 'submitted_at', key: 'submitted_at' },
  { title: '操作', key: 'action', fixed: 'right', width: 160 },
]

const loadPrompts = async () => {
  loading.value = true
  try {
    const params = {
      ...filters,
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    const res = await listPrompts(params)
    prompts.value = res.items || res
    pagination.total = res.total || prompts.value.length
  } catch (err) {
    message.error('加载提示词列表失败: ' + err.message)
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  pagination.current = 1
  loadPrompts()
}

const resetFilters = () => {
  Object.keys(filters).forEach(k => filters[k] = undefined)
  filters.name = ''
  filters.agent_id = ''
  handleSearch()
}

const handleTableChange = (pag) => {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  loadPrompts()
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
    LOW: 'green',
    MEDIUM: 'orange',
    HIGH: 'red',
    EXTREME: 'purple',
  }
  return map[risk] || 'default'
}

const formatDate = (date) => (date ? dayjs(date).format('YYYY-MM-DD HH:mm') : '-')

const handleSubmitOk = async () => {
  if (!submitForm.name || !submitForm.content) {
    message.error('请填写提示词名称和内容')
    return
  }
  submitting.value = true
  try {
    await submitPrompt(submitForm)
    message.success('提示词已提交，进入待扫描状态')
    submitVisible.value = false
    Object.keys(submitForm).forEach(k => submitForm[k] = '')
    loadPrompts()
  } catch (err) {
    message.error('提交失败: ' + err.message)
  } finally {
    submitting.value = false
  }
}

const handleVet = (record) => {
  // Navigation to detail page to perform vet
  message.info('正在跳转至详情页进行安全扫描...')
  // In a real app, you might have a direct API call here
  // For simplicity, we navigate
}

const handleDeploy = async (record) => {
  try {
    await deployPrompt(record.prompt_id)
    message.success('提示词已部署')
    loadPrompts()
  } catch (err) {
    message.error('部署失败: ' + err.message)
  }
}

const showApproveModalDirect = (record) => {
  currentRecord.value = record
  approveForm.note = ''
  approveVisible.value = true
}

const handleApproveOk = async () => {
  approving.value = true
  try {
    await approvePrompt(currentRecord.value.prompt_id, { note: approveForm.note })
    message.success('已批准上线')
    approveVisible.value = false
    loadPrompts()
  } catch (err) {
    message.error('审批失败: ' + err.message)
  } finally {
    approving.value = false
  }
}

const showRejectModalDirect = (record) => {
  currentRecord.value = record
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
    await rejectPrompt(currentRecord.value.prompt_id, { reason: rejectForm.reason })
    message.success('已驳回该提示词')
    rejectVisible.value = false
    loadPrompts()
  } catch (err) {
    message.error('驳回操作失败: ' + err.message)
  } finally {
    rejecting.value = false
  }
}

const showRetireModal = (record) => {
  currentRecord.value = record
  retireForm.reason = ''
  retireVisible.value = true
}

const handleRetireOk = async () => {
  if (!retireForm.reason) {
    message.error('请填写停用原因')
    return
  }
  retiring.value = true
  try {
    await retirePrompt(currentRecord.value.prompt_id, { reason: retireForm.reason })
    message.success('提示词已停用')
    retireVisible.value = false
    loadPrompts()
  } catch (err) {
    message.error('操作失败: ' + err.message)
  } finally {
    retiring.value = false
  }
}

onMounted(() => {
  loadPrompts()
})
</script>

<style scoped>
.prompts-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  margin-bottom: 4px;
  color: #16324f;
}

.page-desc {
  color: #5a7188;
  margin-bottom: 0;
}

.filter-card {
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(10px);
  border: 1px solid #d9e6f2;
}

.prompts-table {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.prompt-name-link {
  font-weight: 500;
  color: #1890ff;
}

.prompt-name-link:hover {
  text-decoration: underline;
}
</style>
