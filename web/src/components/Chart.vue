<template>
  <div ref="chartRef" :style="{ width: '100%', height: height }"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  options: { type: Object, required: true },
  height: { type: String, default: '400px' },
})

const chartRef = ref(null)
let chartInstance = null
let resizeObserver = null

const initChart = () => {
  if (!chartRef.value) return
  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(props.options, true)
}

watch(
  () => props.options,
  (newVal) => {
    if (chartInstance && newVal) {
      chartInstance.setOption(newVal, { notMerge: true })
    }
  },
  { deep: true },
)

onMounted(() => {
  initChart()
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(() => chartInstance?.resize())
    resizeObserver.observe(chartRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chartInstance?.dispose()
})
</script>
