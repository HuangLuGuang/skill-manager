<template>
  <div>
    <a-page-header title="运行时治理" sub-title="执行加载校验与工具权限校验" />

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="12">
        <a-card title="加载检查">
          <a-form layout="vertical" :model="canLoadForm" @finish="handleCanLoad">
            <a-form-item label="Skill 名称">
              <a-input v-model:value="canLoadForm.skillName" placeholder="如 byd-stock-news" />
            </a-form-item>
            <a-form-item label="Skill 路径">
              <a-input v-model:value="canLoadForm.skillPath" placeholder="/path/to/skill，可选" />
            </a-form-item>
            <a-form-item label="Agent ID">
              <a-input v-model:value="canLoadForm.agentId" placeholder="agent-1，可选" />
            </a-form-item>
            <a-button type="primary" html-type="submit" :loading="checkingCanLoad">检查</a-button>
          </a-form>

          <a-result
            v-if="canLoadResult"
            :status="canLoadResult.allowed ? 'success' : 'error'"
            :title="canLoadResult.allowed ? '允许加载' : '拒绝加载'"
            :sub-title="canLoadResult.reason"
            style="padding-inline: 0"
          >
            <template #extra>
              <a-space wrap>
                <a-tag :color="statusColor(canLoadResult.status)">{{ canLoadResult.status || 'unknown' }}</a-tag>
                <a-tag :color="riskColor(canLoadResult.risk_level)">{{ canLoadResult.risk_level || 'unknown' }}</a-tag>
              </a-space>
            </template>
          </a-result>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="12">
        <a-card title="工具权限检查">
          <a-form layout="vertical" :model="toolForm" @finish="handleCheckTool">
            <a-form-item label="Skill 名称">
              <a-input v-model:value="toolForm.skillName" placeholder="如 byd-stock-news" />
            </a-form-item>
            <a-form-item label="工具名称">
              <a-input v-model:value="toolForm.toolName" placeholder="Read / Bash / WebSearch" />
            </a-form-item>
            <a-form-item label="Agent ID">
              <a-input v-model:value="toolForm.agentId" placeholder="agent-1，可选" />
            </a-form-item>
            <a-button type="primary" html-type="submit" :loading="checkingTool">校验</a-button>
          </a-form>

          <a-result
            v-if="toolResult"
            :status="toolResult.allowed ? 'success' : 'error'"
            :title="toolResult.allowed ? '允许调用工具' : '拒绝调用工具'"
            :sub-title="`${toolResult.skill_name} -> ${toolResult.tool_name}`"
            style="padding-inline: 0"
          />
        </a-card>
      </a-col>
    </a-row>

    <a-row :gutter="[16, 16]" style="margin-top: 16px">
      <a-col :xs="24" :xl="10">
        <a-card title="当前可加载技能">
          <a-space style="margin-bottom: 16px" wrap>
            <a-select v-model:value="skillRiskFilter" style="width: 160px" @change="handleSkillFilterChange">
              <a-select-option value="all">全部风险</a-select-option>
              <a-select-option value="LOW">LOW</a-select-option>
              <a-select-option value="MEDIUM">MEDIUM</a-select-option>
              <a-select-option value="HIGH">HIGH</a-select-option>
              <a-select-option value="EXTREME">EXTREME</a-select-option>
            </a-select>
            <a-input v-model:value="skillKeyword" placeholder="搜索 Skill 名称 / ID" style="width: 220px" allow-clear />
            <a-button type="primary" @click="fetchLoadableSkills" :loading="loadingSkills">查询</a-button>
            <a-button @click="resetSkillFilters" :disabled="loadingSkills">重置</a-button>
          </a-space>

          <div class="table-meta">共 {{ skillTotal }} 条可加载 Skill</div>

          <a-table
            :data-source="loadableSkills"
            :columns="skillColumns"
            rowKey="skill_id"
            :loading="loadingSkills"
            :pagination="skillPagination"
            :locale="{ emptyText: '当前没有可加载 Skill' }"
            @change="handleSkillTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <a @click="$router.push(`/skills/${record.skill_id}`)">{{ record.name }}</a>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
              </template>
              <template v-else-if="column.key === 'risk_level'">
                <a-tag :color="riskColor(record.risk_level)">{{ record.risk_level || '-' }}</a-tag>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>

      <a-col :xs="24" :xl="14">
        <a-card title="最近运行时事件">
          <a-space style="margin-bottom: 16px" wrap>
            <a-select v-model:value="eventFilter" style="width: 220px" @change="handleAuditFilterChange">
              <a-select-option value="all">全部运行时事件</a-select-option>
              <a-select-option v-for="option in runtimeEventOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </a-select-option>
            </a-select>
            <a-input v-model:value="auditKeyword" placeholder="搜索 Skill / Actor" style="width: 220px" allow-clear />
            <a-button type="primary" @click="fetchRuntimeAudit" :loading="loadingAudit">查询</a-button>
            <a-button @click="resetAuditFilters" :disabled="loadingAudit">重置</a-button>
          </a-space>

          <div class="table-meta">共 {{ auditTotal }} 条运行时事件</div>

          <a-table
            :data-source="auditRows"
            :columns="auditColumns"
            rowKey="event_id"
            :loading="loadingAudit"
            :pagination="auditPagination"
            :locale="{ emptyText: '最近没有运行时事件' }"
            @change="handleAuditTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'skill_name'">
                <a v-if="record.skill_id && record.skill_id !== 'unknown'" @click="$router.push(`/skills/${record.skill_id}`)">
                  {{ record.skill_name }}
                </a>
                <span v-else>{{ record.skill_name }}</span>
              </template>
              <template v-else-if="column.key === 'details'">
                <span>{{ formatDetails(record.details) }}</span>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

import { getAuditPaged, listSkillsPaged, runtimeCanLoad, runtimeCheckTool } from '../api'
import { formatDateTime, formatDetails } from '../utils/format'

const checkingCanLoad = ref(false)
const checkingTool = ref(false)
const loadingSkills = ref(false)
const loadingAudit = ref(false)

const canLoadResult = ref(null)
const toolResult = ref(null)
const loadableSkills = ref([])
const auditRows = ref([])
const skillTotal = ref(0)
const auditTotal = ref(0)
const eventFilter = ref('all')
const skillRiskFilter = ref('all')
const skillKeyword = ref('')
const auditKeyword = ref('')
const skillSortState = ref({ field: 'name', order: 'ascend' })
const auditSortState = ref({ field: 'timestamp', order: 'descend' })
const skillPagination = ref({
  current: 1,
  pageSize: 6,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['6', '12', '24'],
  showTotal: (total) => `共 ${total} 条`,
})
const auditPagination = ref({
  current: 1,
  pageSize: 6,
  total: 0,
  showSizeChanger: true,
  pageSizeOptions: ['6', '12', '24'],
  showTotal: (total) => `共 ${total} 条`,
})

const canLoadForm = reactive({
  skillName: '',
  skillPath: '',
  agentId: '',
})

const toolForm = reactive({
  skillName: '',
  toolName: '',
  agentId: '',
})

const skillColumns = [
  { title: '技能名称', dataIndex: 'name', key: 'name', sorter: true },
  { title: '状态', dataIndex: 'status', key: 'status', width: 120, sorter: true },
  { title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 120, sorter: true },
]

const auditColumns = [
  { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 220, sorter: true, customRender: ({ text }) => formatDateTime(text) },
  { title: '事件', dataIndex: 'event_type', key: 'event_type', width: 190, sorter: true },
  { title: 'Skill', dataIndex: 'skill_name', key: 'skill_name', width: 180, sorter: true },
  { title: 'Actor', dataIndex: 'actor', key: 'actor', width: 140, sorter: true },
  { title: 'Details', dataIndex: 'details', key: 'details' },
]

const runtimeEventOptions = [
  { value: 'skill_signature_verified', label: 'skill_signature_verified' },
  { value: 'skill_load_allowed', label: 'skill_load_allowed' },
  { value: 'skill_load_blocked', label: 'skill_load_blocked' },
  { value: 'skill_tamper_detected', label: 'skill_tamper_detected' },
  { value: 'tool_invoked', label: 'tool_invoked' },
  { value: 'tool_blocked', label: 'tool_blocked' },
]
const runtimeEventTypes = runtimeEventOptions.map((item) => item.value)

const handleCanLoad = async () => {
  if (!canLoadForm.skillName.trim()) {
    message.warning('请先输入 Skill 名称')
    return
  }
  checkingCanLoad.value = true
  try {
    canLoadResult.value = await runtimeCanLoad(canLoadForm.skillName.trim(), {
      skill_path: canLoadForm.skillPath.trim() || undefined,
      agent_id: canLoadForm.agentId.trim() || undefined,
    })
    fetchRuntimeAudit()
  } catch (error) {
    message.error(error.response?.data?.detail || '加载检查失败')
  } finally {
    checkingCanLoad.value = false
  }
}

const handleCheckTool = async () => {
  if (!toolForm.skillName.trim() || !toolForm.toolName.trim()) {
    message.warning('请先输入 Skill 名称和工具名称')
    return
  }
  checkingTool.value = true
  try {
    toolResult.value = await runtimeCheckTool({
      skill_name: toolForm.skillName.trim(),
      tool_name: toolForm.toolName.trim(),
      agent_id: toolForm.agentId.trim() || undefined,
    })
    fetchRuntimeAudit()
  } catch (error) {
    message.error(error.response?.data?.detail || '工具校验失败')
  } finally {
    checkingTool.value = false
  }
}

const fetchLoadableSkills = async () => {
  loadingSkills.value = true
  try {
    const res = await listSkillsPaged({
      loadable_only: true,
      risk_level: skillRiskFilter.value === 'all' ? undefined : skillRiskFilter.value,
      q: skillKeyword.value.trim() || undefined,
      page: skillPagination.value.current,
      page_size: skillPagination.value.pageSize,
      sort_by: skillSortState.value.field,
      sort_order: skillSortState.value.order === 'ascend' ? 'asc' : 'desc',
    })
    loadableSkills.value = Array.isArray(res.items) ? res.items : []
    skillTotal.value = Number(res.total || 0)
    skillPagination.value = {
      ...skillPagination.value,
      total: skillTotal.value,
      current: Number(res.page || skillPagination.value.current),
      pageSize: Number(res.page_size || skillPagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || '获取可加载技能失败')
    loadableSkills.value = []
    skillTotal.value = 0
  } finally {
    loadingSkills.value = false
  }
}

const fetchRuntimeAudit = async () => {
  loadingAudit.value = true
  try {
    const res = await getAuditPaged({
      since_hours: 168,
      event_type: eventFilter.value === 'all' ? undefined : eventFilter.value,
      event_types: eventFilter.value === 'all' ? runtimeEventTypes.join(',') : undefined,
      q: auditKeyword.value.trim() || undefined,
      page: auditPagination.value.current,
      page_size: auditPagination.value.pageSize,
      sort_order: auditSortState.value.order === 'ascend' ? 'asc' : 'desc',
      limit: 1000,
    })
    auditRows.value = Array.isArray(res.items) ? res.items : []
    auditTotal.value = Number(res.total || 0)
    auditPagination.value = {
      ...auditPagination.value,
      total: auditTotal.value,
      current: Number(res.page || auditPagination.value.current),
      pageSize: Number(res.page_size || auditPagination.value.pageSize),
    }
  } catch (error) {
    message.error(error.response?.data?.detail || '获取运行时事件失败')
    auditRows.value = []
    auditTotal.value = 0
  } finally {
    loadingAudit.value = false
  }
}

const handleSkillTableChange = (pager, _filters, sorter) => {
  skillPagination.value = {
    ...skillPagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    skillSortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchLoadableSkills()
}

const handleAuditTableChange = (pager, _filters, sorter) => {
  auditPagination.value = {
    ...auditPagination.value,
    current: pager.current,
    pageSize: pager.pageSize,
  }
  if (sorter?.field) {
    auditSortState.value = {
      field: sorter.field,
      order: sorter.order || 'ascend',
    }
  }
  fetchRuntimeAudit()
}

const handleSkillFilterChange = () => {
  skillPagination.value = {
    ...skillPagination.value,
    current: 1,
  }
  fetchLoadableSkills()
}

const handleAuditFilterChange = () => {
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const resetSkillFilters = () => {
  skillRiskFilter.value = 'all'
  skillKeyword.value = ''
  skillSortState.value = { field: 'name', order: 'ascend' }
  skillPagination.value = {
    ...skillPagination.value,
    current: 1,
  }
  fetchLoadableSkills()
}

const resetAuditFilters = () => {
  eventFilter.value = 'all'
  auditKeyword.value = ''
  auditSortState.value = { field: 'timestamp', order: 'descend' }
  auditPagination.value = {
    ...auditPagination.value,
    current: 1,
  }
  fetchRuntimeAudit()
}

const statusColor = (value) =>
  ({
    APPROVED: 'green',
    DEPLOYED: 'blue',
  }[value] || 'default')

const riskColor = (value) =>
  ({
    SAFE: 'green',
    LOW: 'green',
    MEDIUM: 'orange',
    HIGH: 'red',
    EXTREME: 'magenta',
  }[value] || 'default')

onMounted(() => {
  fetchLoadableSkills()
  fetchRuntimeAudit()
})
</script>

<style scoped>
.table-meta {
  margin-bottom: 12px;
  color: #6b7280;
  font-size: 12px;
}
</style>
