<template>
  <div class="pii-content">
    <div class="pii-navigation">
      <span class="pii-count" role="status">{{ $t('pipelineTrace.piiMatches', { current: current + 1, total }) }}</span>
      <a-space :size="8">
        <a-button size="small" :disabled="!total" @click="locate(-1)">{{ $t('pipelineTrace.previousPii') }}</a-button>
        <a-button size="small" :disabled="!total" @click="locate(1)">{{ $t('pipelineTrace.nextPii') }}</a-button>
      </a-space>
    </div>
    <pre class="trace-block"><template v-for="(part, index) in parts" :key="index"><mark v-if="part.hit >= 0" :ref="element => setMark(part.hit, element)" :class="{ 'active-hit': current === part.hit }">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></pre>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { splitTracePii } from '../utils/tracePii'

const props = defineProps({ text: { type: String, default: '' }, mappings: { type: Array, default: () => [] } })
const parts = computed(() => splitTracePii(props.text, props.mappings))
const total = computed(() => parts.value.filter(part => part.hit >= 0).length)
const current = ref(-1)
const marks = new Map()
const setMark = (index, element) => element ? marks.set(index, element) : marks.delete(index)
watch(parts, () => { current.value = -1 })
const locate = async direction => {
  if (!total.value) return
  current.value = current.value < 0
    ? (direction > 0 ? 0 : total.value - 1)
    : (current.value + direction + total.value) % total.value
  await nextTick()
  marks.get(current.value)?.scrollIntoView({ block: 'center', inline: 'nearest' })
}
</script>

<style scoped>
.pii-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.pii-navigation {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
  min-height: 28px;
}
.pii-count {
  color: #64748b;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.trace-block {
  max-height: 520px;
  overflow: auto;
  padding: 12px;
  margin: 0;
  background: #0f172a;
  color: #e5e7eb;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.55;
}
mark { background: #fde68a; color: #422006; border-radius: 2px; }
mark.active-hit { background: #fb923c; color: #1c1917; outline: 2px solid #fff; }
</style>
