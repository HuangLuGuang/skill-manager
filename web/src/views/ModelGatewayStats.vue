<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.igys3')" :sub-title="$t('legacy.b7xc44')" />
      </template>

    <!-- 日期范围 + 模型筛选 -->
    <a-space style="margin-bottom: 16px" wrap>
      <span>{{ $t("legacy.11zetu8") }}</span>
      <a-radio-group v-model:value="days" @change="loadAll" button-style="solid" size="small">
        <a-radio-button :value="7">{{ $t("legacy.1a30idy") }}</a-radio-button>
        <a-radio-button :value="14">{{ $t("legacy.1ff0wce") }}</a-radio-button>
        <a-radio-button :value="30">{{ $t("legacy.98mce4") }}</a-radio-button>
        <a-radio-button :value="90">{{ $t("legacy.180r88y") }}</a-radio-button>
      </a-radio-group>
      <a-select
        v-model:value="selectedModel"
        style="width: 200px"
        :placeholder="$t('legacy.1b657i5')"
        allow-clear
        @change="loadAll"
        size="small"
      >
        <a-select-option v-for="m in availableModels" :key="m" :value="m">{{ m }}</a-select-option>
      </a-select>
      <a-button size="small" @click="loadAll" :loading="loading">{{ $t("legacy.12qo56a") }}</a-button>
    </a-space>

    <!-- ============================================================ -->
    <!-- 统计卡片 -->
    <!-- ============================================================ -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic :title="$t('legacy.1j9ugd')" :value="overview.total_requests">
            <template #suffix>
              <span style="font-size: 14px">{{ $t("legacy.a5jtgs") }}</span>
            </template>
          </a-statistic>
          <div class="stat-sub">
            <span style="color: #999">{{ $t("legacy.1iftgzl") }} {{ overview.error_requests || 0 }}</span>
          </div>
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic :title="$t('legacy.p9j46n')" :value="formatNumber(overview.total_tokens)">
            <template #suffix>
              <span style="font-size: 14px">tokens</span>
            </template>
          </a-statistic>
          <div class="stat-sub"> {{ $t("legacy.1qtojr9") }} {{ formatNumber(overview.prompt_tokens) }} {{ $t("legacy.1d0qg9n") }} {{ formatNumber(overview.completion_tokens) }}
          </div>
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic :title="$t('legacy.1f2hy0o')" :value="overview.compression_requests || 0">
            <template #suffix>
              <span style="font-size: 14px">{{ $t("legacy.a5jtgs") }}</span>
            </template>
          </a-statistic>
          <div class="stat-sub"> {{ $t("legacy.wu2yr5") }} {{ overview.total_requests ? Math.round(overview.compression_requests / overview.total_requests * 100) : 0 }}%
          </div>
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :lg="6">
        <a-card>
          <a-statistic :title="$t('legacy.1a64tsc')" :value="overview.avg_request_ms || 0" :precision="1">
            <template #suffix>
              <span style="font-size: 14px">ms</span>
            </template>
          </a-statistic>
          <div class="stat-sub"> {{ $t("legacy.1ow6qt") }} {{ overview.avg_upstream_ms || 0 }}{{ $t("legacy.1lz6xcf") }} {{ overview.avg_platform_ms || 0 }}ms
          </div>
        </a-card>
      </a-col>
    </a-row>
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :span="24">
        <a-card>
          <a-statistic
            :title="$t('legacy.49c9bb')"
            :value="formatNumber(overview.tokens_saved)"
            :value-style="{ color: overview.tokens_saved > 0 ? '#52c41a' : '#999' }"
          >
            <template #suffix>
              <span style="font-size: 14px">tokens</span>
            </template>
          </a-statistic>
          <div class="stat-sub" v-if="overview.avg_compression_ratio"> {{ $t("legacy.140axhd") }} {{ (overview.avg_compression_ratio * 100).toFixed(1) }}{{ $t("legacy.hwg8zc") }} {{ overview.avg_compression_ms }}ms
          </div>
        </a-card>
      </a-col>
    </a-row>

    <!-- ============================================================ -->
    <!-- 图表行 1: 每日趋势 -->
    <!-- ============================================================ -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :span="24">
        <a-card :title="$t('legacy.2thvkq')">
          <Chart :options="dailyChartOptions" height="360px" />
        </a-card>
      </a-col>
    </a-row>

    <!-- ============================================================ -->
    <!-- 图表行 2: 按模型统计 + 压缩前后对比 -->
    <!-- ============================================================ -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :xs="24" :xl="14">
        <a-card :title="$t('legacy.falrie')">
          <Chart :options="modelChartOptions" height="380px" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="10">
        <a-card :title="$t('legacy.10mfxp4')">
          <Chart v-if="hasCompressionData" :options="compressionChartOptions" height="380px" />
          <a-empty v-else :description="$t('legacy.1232jyr')" style="padding: 60px 0" />
        </a-card>
      </a-col>
    </a-row>

    <!-- ============================================================ -->
    <!-- 表格: 按模型的详细统计 -->
    <!-- ============================================================ -->
    <a-card :title="$t('legacy.1pe8458')" style="margin-bottom: 16px">
      <a-table
        :data-source="modelStats.models"
        :columns="modelTableColumns"
        row-key="model"
        :loading="loading"
        :pagination="false"
        size="small"
        :locale="{ emptyText: $t('legacy.6tzr61') }"
      />
    </a-card>
    </a-card>

  </div>
</template>

<script setup>
import { translateLegacy as phrase, translateText as text } from '../i18n'

import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import Chart from '../components/Chart.vue'
import { getLlmStatsOverview, getLlmStatsDaily, getLlmStatsByModel } from '../api'
import { formatCompactNumber as formatNumber } from '../utils/format'

const days = ref(30)
const selectedModel = ref(null)
const loading = ref(false)
const overview = ref({})
const daily = ref({ series: [] })
const modelStats = ref({ models: [] })
const availableModels = ref([])

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
    message.error(phrase('legacy.156uaxi'))
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
    legend: { data: [phrase('legacy.6okv1w'), phrase('legacy.k6sqb1'), phrase('legacy.147iclc')] },
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
        name: phrase('legacy.6okv1w'),
        type: 'line',
        data: series.map(s => s.prompt_tokens),
        smooth: true,
        lineStyle: { color: '#1890ff' },
        itemStyle: { color: '#1890ff' },
        areaStyle: { color: 'rgba(24,144,255,0.1)' },
      },
      {
        name: phrase('legacy.k6sqb1'),
        type: 'line',
        data: series.map(s => s.completion_tokens),
        smooth: true,
        lineStyle: { color: '#52c41a' },
        itemStyle: { color: '#52c41a' },
        areaStyle: { color: 'rgba(82,196,26,0.08)' },
      },
      {
        name: phrase('legacy.147iclc'),
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
    legend: { data: [phrase('legacy.6okv1w'), phrase('legacy.k6sqb1')] },
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
        name: phrase('legacy.6okv1w'),
        type: 'bar',
        stack: 'tokens',
        data: models.map(m => m.prompt_tokens),
        itemStyle: { color: '#1890ff' },
        emphasis: { focus: 'series' },
      },
      {
        name: phrase('legacy.k6sqb1'),
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
        return text(
          `${m.model}<br/>压缩前: ${formatNumber(m.prompt_tokens)}<br/>压缩后: ${formatNumber(m.prompt_tokens - m.tokens_saved)}<br/>节省: ${formatNumber(m.tokens_saved)} (${m.prompt_tokens ? Math.round(m.tokens_saved / m.prompt_tokens * 100) : 0}%)`,
          `${m.model}<br/>Before: ${formatNumber(m.prompt_tokens)}<br/>After: ${formatNumber(m.prompt_tokens - m.tokens_saved)}<br/>Saved: ${formatNumber(m.tokens_saved)} (${m.prompt_tokens ? Math.round(m.tokens_saved / m.prompt_tokens * 100) : 0}%)`,
        )
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
        name: phrase('legacy.1mnhwqd'),
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
        name: phrase('legacy.147iclc'),
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
  { title: phrase('legacy.1ow6qt'), dataIndex: 'model', width: 200 },
  {
    title: phrase('legacy.fq51j8'), dataIndex: 'requests', width: 90, align: 'right',
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: phrase('legacy.6okv1w'), dataIndex: 'prompt_tokens', width: 120, align: 'right', sorter: (a, b) => a.prompt_tokens - b.prompt_tokens,
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: phrase('legacy.k6sqb1'), dataIndex: 'completion_tokens', width: 120, align: 'right', sorter: (a, b) => a.completion_tokens - b.completion_tokens,
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: phrase('legacy.s8fw9n'), dataIndex: 'total_tokens', width: 120, align: 'right', sorter: (a, b) => a.total_tokens - b.total_tokens,
    customRender: ({ text }) => formatNumber(text),
  },
  {
    title: phrase('legacy.147iclc'), dataIndex: 'tokens_saved', width: 120, align: 'right',
    customRender: ({ text, record }) => {
      if (!text) return '-'
      const pct = record.prompt_tokens ? Math.round(text / record.prompt_tokens * 100) : 0
      return `${formatNumber(text)} (${pct}%)`
    },
  },
  {
    title: phrase('legacy.1hzv0va'), dataIndex: 'avg_request_ms', width: 110, align: 'right',
    customRender: ({ text }) => `${text || 0} ms`,
  },
  {
    title: phrase('legacy.j2g9ts'), dataIndex: 'avg_upstream_ms', width: 110, align: 'right',
    customRender: ({ text }) => `${text || 0} ms`,
  },
  {
    title: phrase('legacy.1yz91un'), dataIndex: 'avg_platform_ms', width: 110, align: 'right',
    customRender: ({ text }) => `${text || 0} ms`,
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
