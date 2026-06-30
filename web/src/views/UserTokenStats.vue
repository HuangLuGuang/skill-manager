<template>
  <div>
    <a-page-header title="用户 Token 分析" sub-title="按用户查看模型调用、Token 消耗和压缩节省" />

    <!-- 筛选 -->
    <a-space style="margin-bottom: 16px" wrap>
      <span>统计范围:</span>
      <a-radio-group v-model:value="days" @change="loadData" button-style="solid" size="small">
        <a-radio-button :value="7">近 7 天</a-radio-button>
        <a-radio-button :value="14">近 14 天</a-radio-button>
        <a-radio-button :value="30">近 30 天</a-radio-button>
        <a-radio-button :value="90">近 90 天</a-radio-button>
      </a-radio-group>
      <a-select
        v-model:value="selectedModel"
        style="width: 200px"
        placeholder="全部模型"
        allow-clear
        @change="loadData"
        size="small"
      >
        <a-select-option v-for="m in availableModels" :key="m" :value="m">{{ m }}</a-select-option>
      </a-select>
      <a-button size="small" @click="loadData" :loading="loading">刷新</a-button>
    </a-space>

    <!-- 柱状图: 按用户 Token 用量 + 压缩节省 -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :xs="24" :xl="16">
        <a-card title="各用户 Token 用量（堆叠柱状图）">
          <Chart v-if="userStats.users?.length" :options="userBarOptions" height="380px" />
          <a-empty v-else description="暂无数据" style="padding: 80px 0" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="8">
        <a-card title="各用户压缩节省">
          <Chart v-if="hasCompression" :options="savedBarOptions" height="380px" />
          <a-empty v-else description="暂无压缩数据" style="padding: 80px 0" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 明细表 -->
    <a-card title="用户 Token 明细">
      <a-table
        :data-source="userStats.users"
        :columns="columns"
        row-key="user_id"
        :loading="loading"
        :pagination="false"
        size="small"
        :locale="{ emptyText: '暂无数据' }"
      />
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import Chart from '../components/Chart.vue'
import { getLlmStatsByUser, getLlmStatsByModel } from '../api'

const days = ref(30)
const selectedModel = ref(null)
const loading = ref(false)
const userStats = ref({ users: [] })
const availableModels = ref([])

const formatNumber = (n) => {
  if (!n && n !== 0) return '-'
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

const hasCompression = computed(() =>
  userStats.value.users?.some(u => u.tokens_saved > 0)
)

const loadData = async () => {
  loading.value = true
  try {
    const params = { days: days.value }
    if (selectedModel.value) params.model = selectedModel.value
    const data = await getLlmStatsByUser(params)
    userStats.value = data
    if (!selectedModel.value) {
      const bm = await getLlmStatsByModel({ days: days.value })
      availableModels.value = (bm.models || []).map(m => m.model)
    }
  } catch (e) {
    message.error('加载统计数据失败')
  } finally {
    loading.value = false
  }
}

const userBarOptions = computed(() => {
  const users = userStats.value.users || []
  const names = users.map(u => u.username)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['输入 Token', '输出 Token'] },
    grid: { left: 60, right: 10, top: 30, bottom: 100 },
    xAxis: { type: 'category', data: names, axisLabel: { rotate: 45, fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: formatNumber } },
    series: [
      { name: '输入 Token', type: 'bar', stack: 'tokens', data: users.map(u => u.prompt_tokens), itemStyle: { color: '#1890ff' } },
      { name: '输出 Token', type: 'bar', stack: 'tokens', data: users.map(u => u.completion_tokens), itemStyle: { color: '#52c41a' } },
    ],
  }
})

const savedBarOptions = computed(() => {
  const users = (userStats.value.users || []).filter(u => u.tokens_saved > 0)
  const names = users.map(u => u.username)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (p) => {
        const u = users[p[0].dataIndex]
        const pct = u.prompt_tokens ? Math.round(u.tokens_saved / u.prompt_tokens * 100) : 0
        return `${u.username}<br/>节省: ${formatNumber(u.tokens_saved)} (${pct}%)`
      },
    },
    grid: { left: 60, right: 10, top: 30, bottom: 100 },
    xAxis: { type: 'category', data: names, axisLabel: { rotate: 45, fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: formatNumber } },
    series: [{
      name: '压缩节省', type: 'bar',
      data: users.map(u => u.tokens_saved),
      itemStyle: { color: '#722ed1' },
      label: { show: true, position: 'top', formatter: (p) => formatNumber(p.value), fontSize: 10 },
    }],
  }
})

const columns = [
  { title: '用户', dataIndex: 'username', width: 140 },
  { title: '请求数', dataIndex: 'requests', width: 80, align: 'right', customRender: ({ text }) => formatNumber(text) },
  { title: '输入 Token', dataIndex: 'prompt_tokens', width: 120, align: 'right', sorter: (a, b) => a.prompt_tokens - b.prompt_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: '输出 Token', dataIndex: 'completion_tokens', width: 120, align: 'right', sorter: (a, b) => a.completion_tokens - b.completion_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: '总 Token', dataIndex: 'total_tokens', width: 120, align: 'right', sorter: (a, b) => a.total_tokens - b.total_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: '压缩节省', dataIndex: 'tokens_saved', width: 120, align: 'right', customRender: ({ text, record }) => {
    if (!text) return '-'
    const pct = record.prompt_tokens ? Math.round(text / record.prompt_tokens * 100) : 0
    return `${formatNumber(text)} (${pct}%)`
  } },
]

onMounted(() => loadData())
</script>
