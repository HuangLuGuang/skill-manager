<template>
  <div>
    <a-page-header title="Token 用量与压缩" sub-title="查看模型调用量、Token 消耗和智能压缩节省效果" />

    <!-- 日期范围 + 模型筛选 -->
    <a-space style="margin-bottom: 16px" wrap>
      <span>统计范围:</span>
      <a-radio-group v-model:value="days" @change="loadAll" button-style="solid" size="small">
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
        @change="loadAll"
        size="small"
      >
        <a-select-option v-for="m in availableModels" :key="m" :value="m">{{ m }}</a-select-option>
      </a-select>
      <a-button size="small" @click="loadAll" :loading="loading">刷新</a-button>
    </a-space>

    <!-- ============================================================ -->
    <!-- 统计卡片 -->
    <!-- ============================================================ -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic title="总请求数" :value="overview.total_requests">
            <template #suffix>
              <span style="font-size: 14px">次</span>
            </template>
          </a-statistic>
          <div class="stat-sub">
            <span style="color: #999">错误: {{ overview.error_requests || 0 }}</span>
          </div>
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic title="Token 用量" :value="formatNumber(overview.total_tokens)">
            <template #suffix>
              <span style="font-size: 14px">tokens</span>
            </template>
          </a-statistic>
          <div class="stat-sub">
            输入 {{ formatNumber(overview.prompt_tokens) }} · 输出 {{ formatNumber(overview.completion_tokens) }}
          </div>
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic title="压缩请求" :value="overview.compression_requests || 0">
            <template #suffix>
              <span style="font-size: 14px">次</span>
            </template>
          </a-statistic>
          <div class="stat-sub">
            占比 {{ overview.total_requests ? Math.round(overview.compression_requests / overview.total_requests * 100) : 0 }}%
          </div>
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic
            title="Token 节省"
            :value="formatNumber(overview.tokens_saved)"
            :value-style="{ color: overview.tokens_saved > 0 ? '#52c41a' : '#999' }"
          >
            <template #suffix>
              <span style="font-size: 14px">tokens</span>
            </template>
          </a-statistic>
          <div class="stat-sub" v-if="overview.avg_compression_ratio">
            平均压缩比 {{ (overview.avg_compression_ratio * 100).toFixed(1) }}% · 平均耗时 {{ overview.avg_compression_ms }}ms
          </div>
        </a-card>
      </a-col>
    </a-row>

    <!-- ============================================================ -->
    <!-- 图表行 1: 每日趋势 -->
    <!-- ============================================================ -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :span="24">
        <a-card title="每日 Token 趋势">
          <Chart :options="dailyChartOptions" height="360px" />
        </a-card>
      </a-col>
    </a-row>

    <!-- ============================================================ -->
    <!-- 图表行 2: 按模型统计 + 压缩前后对比 -->
    <!-- ============================================================ -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :xs="24" :xl="14">
        <a-card title="按模型统计 Token 用量">
          <Chart :options="modelChartOptions" height="380px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="10">
        <a-card title="压缩效果对比">
          <Chart v-if="hasCompressionData" :options="compressionChartOptions" height="380px" />
          <a-empty v-else description="暂无压缩数据，开启压缩的 API Key 产生请求后可查看" style="padding: 60px 0" />
        </a-card>
      </a-col>
    </a-row>

    <!-- ============================================================ -->
    <!-- 表格: 按模型的详细统计 -->
    <!-- ============================================================ -->
    <a-card title="模型用量明细" style="margin-bottom: 16px">
      <a-table
        :data-source="modelStats.models"
        :columns="modelTableColumns"
        row-key="model"
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
import { getLlmStatsOverview, getLlmStatsDaily, getLlmStatsByModel } from '../api'

const days = ref(30)
const selectedModel = ref(null)
const loading = ref(false)
const overview = ref({})
const daily = ref({ series: [] })
const modelStats = ref({ models: [] })
const availableModels = ref([])

const formatNumber = (n) => {
  if (!n && n !== 0) return '-'
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

const buildParams = () => {
  const params = { days: days.value }
  if (selectedModel.value) params.model = selectedModel.value
  return params
}

const loadAll = async () => {
  loading.value = true
  try {
    const params = buildParams()
    const [ov, dy, bm] = await Promise.all([
      getLlmStatsOverview(params),
      getLlmStatsDaily(params),
      getLlmStatsByModel(params),
    ])
    overview.value = ov
    daily.value = dy
    modelStats.value = bm
    // 从 by-model 结果中提取所有模型名作为下拉选项
    if (!selectedModel.value) {
      availableModels.value = (bm.models || []).map(m => m.model)
    }
  } catch (e) {
    message.error('加载统计数据失败')
  } finally {
    loading.value = false
  }
}

const hasCompressionData = computed(() => {
  return modelStats.value.models?.some(m => m.tokens_saved > 0)
})

// ── ECharts: 每日趋势 (折线图) ──────────────────────────────────
const dailyChartOptions = computed(() => {
  const series = daily.value.series || []
  const dates = series.map(s => s.date.substring(5)) // MM-DD
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['输入 Token', '输出 Token', '压缩节省'] },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { rotate: 45, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: formatNumber },
    },
    series: [
      {
        name: '输入 Token',
        type: 'line',
        data: series.map(s => s.prompt_tokens),
        smooth: true,
        lineStyle: { color: '#1890ff' },
        itemStyle: { color: '#1890ff' },
        areaStyle: { color: 'rgba(24,144,255,0.1)' },
      },
      {
        name: '输出 Token',
        type: 'line',
        data: series.map(s => s.completion_tokens),
        smooth: true,
        lineStyle: { color: '#52c41a' },
        itemStyle: { color: '#52c41a' },
        areaStyle: { color: 'rgba(82,196,26,0.08)' },
      },
      {
        name: '压缩节省',
        type: 'bar',
        data: series.map(s => s.tokens_saved),
        itemStyle: { color: 'rgba(114,46,209,0.5)' },
        barGap: '-100%',
        barWidth: '60%',
      },
    ],
  }
})

// ── ECharts: 按模型统计 (堆叠柱状图) ───────────────────────────
const modelChartOptions = computed(() => {
  const models = modelStats.value.models || []
  const names = models.map(m => m.model.length > 20 ? m.model.substring(0, 20) + '...' : m.model)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['输入 Token', '输出 Token'] },
    grid: { left: 10, right: 10, top: 30, bottom: 100 },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { rotate: 45, fontSize: 10, interval: 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: formatNumber },
    },
    series: [
      {
        name: '输入 Token',
        type: 'bar',
        stack: 'tokens',
        data: models.map(m => m.prompt_tokens),
        itemStyle: { color: '#1890ff' },
        emphasis: { focus: 'series' },
      },
      {
        name: '输出 Token',
        type: 'bar',
        stack: 'tokens',
        data: models.map(m => m.completion_tokens),
        itemStyle: { color: '#52c41a' },
        emphasis: { focus: 'series' },
      },
    ],
  }
})

// ── ECharts: 压缩效果对比 (瀑布图风格) ─────────────────────────
const compressionChartOptions = computed(() => {
  const models = (modelStats.value.models || []).filter(m => m.tokens_saved > 0)
  const names = models.map(m => m.model.length > 16 ? m.model.substring(0, 16) + '...' : m.model)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const m = models[params[0].dataIndex]
        return `${m.model}<br/>压缩前: ${formatNumber(m.prompt_tokens)}<br/>压缩后: ${formatNumber(m.prompt_tokens - m.tokens_saved)}<br/>节省: ${formatNumber(m.tokens_saved)} (${m.prompt_tokens ? Math.round(m.tokens_saved / m.prompt_tokens * 100) : 0}%)`
      },
    },
    grid: { left: 10, right: 10, top: 30, bottom: 100 },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { rotate: 45, fontSize: 10, interval: 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: formatNumber },
    },
    series: [
      {
        name: '压缩后',
        type: 'bar',
        stack: 'compression',
        data: models.map(m => Math.max(0, m.prompt_tokens - m.tokens_saved)),
        itemStyle: { color: '#52c41a' },
        label: {
          show: true,
          position: 'inside',
          formatter: (p) => formatNumber(p.value),
          fontSize: 10,
        },
      },
      {
        name: '压缩节省',
        type: 'bar',
        stack: 'compression',
        data: models.map(m => m.tokens_saved),
        itemStyle: { color: 'rgba(114,46,209,0.65)' },
        label: {
          show: true,
          position: 'inside',
          formatter: (p) => {
            const m = models[p.dataIndex]
            const pct = m.prompt_tokens ? Math.round(m.tokens_saved / m.prompt_tokens * 100) : 0
            return pct + '%'
          },
          fontSize: 10,
        },
      },
    ],
  }
})

// ── 明细表格列 ──────────────────────────────────────────────────
const modelTableColumns = [
  { title: '模型', dataIndex: 'model', width: 200 },
  {
    title: '请求数', dataIndex: 'requests', width: 90, align: 'right',
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: '输入 Token', dataIndex: 'prompt_tokens', width: 120, align: 'right', sorter: (a, b) => a.prompt_tokens - b.prompt_tokens,
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: '输出 Token', dataIndex: 'completion_tokens', width: 120, align: 'right', sorter: (a, b) => a.completion_tokens - b.completion_tokens,
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: '总 Token', dataIndex: 'total_tokens', width: 120, align: 'right', sorter: (a, b) => a.total_tokens - b.total_tokens,
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: '压缩节省', dataIndex: 'tokens_saved', width: 120, align: 'right',
    customRender: ({ text, record }) => {
      if (!text) return '-'
      const pct = record.prompt_tokens ? Math.round(text / record.prompt_tokens * 100) : 0
      return `${formatNumber(text)} (${pct}%)`
    },
  },
]

onMounted(() => loadAll())
</script>

<style scoped>
.stat-sub {
  margin-top: 8px;
  font-size: 13px;
  color: #888;
}
</style>
