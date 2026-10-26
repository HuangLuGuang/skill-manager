<template>
  <div ref="chartRef" :style="{ width: '100%', height: height }" :tabindex="navigationLabel ? 0 : undefined" :aria-label="selectionLabel || undefined" @keydown="navigate"></div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  options: { type: Object, required: true },
  height: { type: String, default: '400px' },
  navigationLabel: { type: String, default: '' },
})

const chartRef = ref(null)
const emit = defineEmits(['select'])
let chartInstance = null
let resizeObserver = null
const selectedIndex = ref(0)
const selectionLabel = computed(() => {
  if (!props.navigationLabel) return ''
  const option = props.options, index = selectedIndex.value
  const name = option.xAxis?.data?.[index] ?? option.yAxis?.data?.[index] ?? option.series?.[0]?.data?.[index]?.name ?? ''
  const values = (option.series || []).map(series => {
    const item = series.data?.[index]
    return `${series.name || ''} ${typeof item === 'object' ? item?.value ?? '' : item ?? ''}`.trim()
  }).join(', ')
  return `${props.navigationLabel} ${name}: ${values}`
})
function navigate(event) {
  const count = props.options.series?.[0]?.data?.length || 0
  if (!props.navigationLabel || !count) return
  if (['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
    event.preventDefault()
    if (event.key === 'Enter' || event.key === ' ') emit('select', { dataIndex: selectedIndex.value })
    else {
      selectedIndex.value = (selectedIndex.value + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + count) % count
      chartInstance?.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: selectedIndex.value })
    }
  }
}
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
const chartOptions = options => ({ ...options, ...(props.navigationLabel ? { aria: { enabled: false } } : {}), animation: !motionPreference.matches && options.animation !== false })
const updateMotion = () => chartInstance?.setOption(chartOptions(props.options), { notMerge: true })

const initChart = () => {
  if (!chartRef.value) return
  chartInstance = echarts.init(chartRef.value)
  chartInstance.on('click', params => emit('select', params))
  chartInstance.setOption(chartOptions(props.options), true)
}

watch(
  () => props.options,
  (newVal) => {
    selectedIndex.value = 0
    if (chartInstance && newVal) {
      chartInstance.setOption(chartOptions(newVal), { notMerge: true })
    }
  },
  { deep: true },
)

onMounted(() => {
  motionPreference.addEventListener('change', updateMotion)
  initChart()
  if (chartRef.value) {
    resizeObserver = new ResizeObserver(() => chartInstance?.resize())
    resizeObserver.observe(chartRef.value)
  }
})

onBeforeUnmount(() => {
  motionPreference.removeEventListener('change', updateMotion)
  resizeObserver?.disconnect()
  chartInstance?.dispose()
})
</script>
