<template>
  <div>
    <a-card class="page-card">
      <template #title>
        <a-page-header :title="$t('legacy.7h965d')" :sub-title="$t('legacy.o7xf8c')" />
      </template>

    <!-- 筛选 -->
    <a-space style="margin-bottom: 16px" wrap>
      <span>{{ $t("legacy.11zetu8") }}</span>
      <a-radio-group v-model:value="days" @change="loadData" button-style="solid" size="small">
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
        @change="loadData"
        size="small"
      >
        <a-select-option v-for="m in availableModels" :key="m" :value="m">{{ m }}</a-select-option>
      </a-select>
      <a-select
        v-model:value="topLimit"
        style="width: 120px"
        @change="loadData"
        size="small"
      >
        <a-select-option :value="10">Top 10</a-select-option>
        <a-select-option :value="20">Top 20</a-select-option>
      </a-select>
      <a-button size="small" @click="loadData" :loading="loading">{{ $t("legacy.12qo56a") }}</a-button>
    </a-space>

    <!-- 柱状图: 按用户 Token 用量 + 压缩节省 -->
    <a-row :gutter="[16, 16]" style="margin-bottom: 16px">
      <a-col :xs="24" :xl="16">
        <a-card :title="$t('legacy.1xb8pkw')">
          <Chart v-if="userStats.users?.length" :options="userBarOptions" height="380px" />
          <a-empty v-else :description="$t('legacy.6tzr61')" style="padding: 80px 0" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="8">
        <a-card :title="$t('legacy.yjyj07')">
          <Chart v-if="hasCompression" :options="savedBarOptions" height="380px" />
          <a-empty v-else :description="$t('legacy.1irf4nt')" style="padding: 80px 0" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 明细表 -->
    <a-card :title="$t('legacy.fx8afj')">
      <a-table
        :data-source="userStats.users"
        :columns="columns"
        row-key="user_id"
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
import { getLlmStatsByUser, getLlmStatsByModel } from '../api'
import { formatCompactNumber as formatNumber } from '../utils/format'

const days = ref(30)
const selectedModel = ref(null)
const topLimit = ref(10)
const loading = ref(false)
const userStats = ref({ users: [] })
const availableModels = ref([])

const hasCompression = computed(() =>
  userStats.value.users?.some(u => u.tokens_saved > 0)
)

const loadData = async () => {
  loading.value = true
  try {
    const params = { days: days.value, limit: topLimit.value }
    if (selectedModel.value) params.model = selectedModel.value
    const data = await getLlmStatsByUser(params)
    userStats.value = data
    if (!selectedModel.value) {
      const bm = await getLlmStatsByModel({ days: days.value })
      availableModels.value = (bm.models || []).map(m => m.model)
    }
  } catch (e) {
    message.error(phrase('legacy.156uaxi'))
  } finally {
    loading.value = false
  }
}

const userBarOptions = computed(() => {
  const users = userStats.value.users || []
  const names = users.map(u => u.username)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: [phrase('legacy.6okv1w'), phrase('legacy.k6sqb1')] },
    grid: { left: 60, right: 10, top: 30, bottom: 100 },
    xAxis: { type: 'category', data: names, axisLabel: { rotate: 45, fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: formatNumber } },
    series: [
      { name: phrase('legacy.6okv1w'), type: 'bar', stack: 'tokens', data: users.map(u => u.prompt_tokens), itemStyle: { color: '#1890ff' } },
      { name: phrase('legacy.k6sqb1'), type: 'bar', stack: 'tokens', data: users.map(u => u.completion_tokens), itemStyle: { color: '#52c41a' } },
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
        return text(
          `${u.username}<br/>节省: ${formatNumber(u.tokens_saved)} (${pct}%)`,
          `${u.username}<br/>Saved: ${formatNumber(u.tokens_saved)} (${pct}%)`,
        )
      },
    },
    grid: { left: 60, right: 10, top: 30, bottom: 100 },
    xAxis: { type: 'category', data: names, axisLabel: { rotate: 45, fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: formatNumber } },
    series: [{
      name: phrase('legacy.147iclc'), type: 'bar',
      data: users.map(u => u.tokens_saved),
      itemStyle: { color: '#722ed1' },
      label: { show: true, position: 'top', formatter: (p) => formatNumber(p.value), fontSize: 10 },
    }],
  }
})

const columns = [
  { title: phrase('legacy.1in002o'), dataIndex: 'username', width: 140 },
  { title: phrase('legacy.fq51j8'), dataIndex: 'requests', width: 80, align: 'right', customRender: ({ text }) => formatNumber(text) },
  { title: phrase('legacy.6okv1w'), dataIndex: 'prompt_tokens', width: 120, align: 'right', sorter: (a, b) => a.prompt_tokens - b.prompt_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: phrase('legacy.k6sqb1'), dataIndex: 'completion_tokens', width: 120, align: 'right', sorter: (a, b) => a.completion_tokens - b.completion_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: phrase('legacy.s8fw9n'), dataIndex: 'total_tokens', width: 120, align: 'right', sorter: (a, b) => a.total_tokens - b.total_tokens, customRender: ({ text }) => formatNumber(text) },
  { title: phrase('legacy.147iclc'), dataIndex: 'tokens_saved', width: 120, align: 'right', customRender: ({ text, record }) => {
    if (!text) return '-'
    const pct = record.prompt_tokens ? Math.round(text / record.prompt_tokens * 100) : 0
    return `${formatNumber(text)} (${pct}%)`
  } },
]

onMounted(() => loadData())
</script>
