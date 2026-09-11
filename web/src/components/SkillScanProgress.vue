<template>
  <a-popover
    :trigger="['hover', 'focus', 'click']"
    placement="top"
    :align="{ offset: [activeAnchorOffset, -12] }"
    :title="t('skillColumns.steps.label')"
    overlay-class-name="scan-progress-popover"
    transition-name="scan-progress-reveal"
    :mouse-enter-delay="0.12"
    :mouse-leave-delay="0.1"
  >
    <template #content>
      <ol class="step-details">
        <li v-for="step in steps" :key="step.key" :class="step.status">
          <span><component :is="step.icon" aria-hidden="true" /> {{ t(`skillColumns.steps.${step.key}`) }}</span>
          <span class="detail-state">{{ t(`skillColumns.stepStates.${step.status}`) }}</span>
        </li>
      </ol>
    </template>
    <button type="button" class="skill-scan-progress" :aria-label="`${t('skillColumns.steps.label')}: ${summary}`">
      <span class="scan-steps" role="list">
        <span v-for="step in steps" :key="step.key" role="listitem" :class="['scan-step', step.status]" :aria-label="`${t(`skillColumns.steps.${step.key}`)}: ${t(`skillColumns.stepStates.${step.status}`)}`">
          <span class="step-icon" aria-hidden="true">
            <CheckOutlined v-if="step.status === 'completed'" />
            <LoadingOutlined v-else-if="step.status === 'running'" spin />
            <CloseOutlined v-else-if="step.status === 'failed'" />
            <MinusOutlined v-else-if="['disabled', 'skipped'].includes(step.status)" />
            <component :is="step.icon" v-else />
          </span>
        </span>
      </span>
      <span class="stage-label">{{ summary }}<DownOutlined class="detail-caret" aria-hidden="true" /></span>
    </button>
  </a-popover>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckOutlined, ClockCircleOutlined, DownOutlined, CloseOutlined, CodeSandboxOutlined, ExperimentOutlined, FileSearchOutlined, LoadingOutlined, MinusOutlined, RobotOutlined, SafetyCertificateOutlined, SolutionOutlined } from '@ant-design/icons-vue'

const props = defineProps({
  stage: { type: String, default: null },
  analyzers: { type: Object, default: () => ({}) },
})
const { t } = useI18n()
const summary = computed(() => {
  const active = steps.value.filter(step => step.status === 'running' && ['scanner', 'skillspector', 'sandbox', 'llm'].includes(step.key))
  return active.length ? active.map(step => t(`skillColumns.steps.${step.key}`)).join(' · ') : t(`skillColumns.progress.${stageKey.value}`)
})
const stageKeys = ['queued', 'preparing', 'analyzers', 'sandbox', 'llm', 'finalizing']
const stageKey = computed(() => !props.stage ? 'queued' : stageKeys.includes(props.stage) ? props.stage : 'running')
const states = ['pending', 'running', 'completed', 'failed', 'disabled', 'skipped']
const analyzerState = key => states.includes(props.analyzers[key]) ? props.analyzers[key] : 'pending'
const steps = computed(() => {
  const current = stageKeys.indexOf(stageKey.value)
  return [
    { key: 'queued', icon: ClockCircleOutlined, status: current === 0 ? 'running' : current > 0 ? 'completed' : 'pending' },
    { key: 'preparing', icon: FileSearchOutlined, status: current === 1 ? 'running' : current > 1 ? 'completed' : 'pending' },
    { key: 'scanner', icon: SafetyCertificateOutlined, status: analyzerState('scanner') },
    { key: 'skillspector', icon: ExperimentOutlined, status: analyzerState('skillspector') },
    { key: 'sandbox', icon: CodeSandboxOutlined, status: analyzerState('sandbox') },
    { key: 'llm', icon: RobotOutlined, status: analyzerState('llm') },
    { key: 'finalizing', icon: SolutionOutlined, status: stageKey.value === 'finalizing' ? 'running' : 'pending' },
  ]
})
const activeAnchorOffset = computed(() => {
  const index = steps.value.findIndex(step => step.status === 'running')
  return index < 0 ? 0 : index * 27 + 11 - 188 / 2
})
</script>

<style scoped>
.skill-scan-progress { display: block; width: 188px; max-width: 100%; padding: 0; border: 0; background: transparent; text-align: left; cursor: pointer; font: inherit; }
.skill-scan-progress:focus-visible { outline: 2px solid #1677ff; outline-offset: 4px; border-radius: 4px; }
.scan-steps { display: flex; align-items: center; gap: 5px; }
.scan-step { position: relative; color: #8c8c8c; }
.scan-step:not(:last-child)::after { content: ''; position: absolute; width: 5px; height: 1px; top: 11px; left: 22px; background: #d9d9d9; }
.step-icon { display: flex; align-items: center; justify-content: center; box-sizing: border-box; width: 22px; height: 22px; border: 1px solid #d9d9d9; border-radius: 50%; background: #fafafa; font-size: 12px; }
.completed .step-icon { color: #389e0d; border-color: #b7eb8f; background: #f6ffed; }
.running .step-icon { color: #1677ff; border-color: #91caff; background: #e6f4ff; }
.failed .step-icon { color: #cf1322; border-color: #ffa39e; background: #fff1f0; }
.stage-label { display: block; margin-top: 4px; color: #1677ff; font-size: 12px; line-height: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-caret { margin-left: 6px; font-size: 9px; color: #8c8c8c; }
.step-details { width: 240px; max-width: calc(100vw - 64px); padding: 0; margin: 0; list-style: none; }
.step-details li { display: flex; align-items: baseline; justify-content: space-between; gap: 20px; padding: 5px 0; }
.detail-state { color: #8c8c8c; white-space: nowrap; }
.running .detail-state { color: #1677ff; }
.completed .detail-state { color: #389e0d; }
.failed .detail-state { color: #cf1322; }
@media (prefers-reduced-motion: reduce) { .step-icon :deep(.anticon-spin) { animation: none; } }
</style>

<style>
.scan-progress-popover.scan-progress-reveal-enter { opacity: 0; }
.scan-progress-popover.scan-progress-reveal-enter-active {
  animation: scan-progress-in 220ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
.scan-progress-popover.scan-progress-reveal-leave-active {
  animation: scan-progress-out 130ms cubic-bezier(0.4, 0, 1, 1) both;
  pointer-events: none;
}
@keyframes scan-progress-in {
  from { opacity: 0; transform: translateY(6px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes scan-progress-out {
  from { opacity: 1; transform: translateY(0) scale(1); }
  to { opacity: 0; transform: translateY(3px) scale(0.985); }
}
@media (prefers-reduced-motion: reduce) {
  .scan-progress-popover.scan-progress-reveal-enter-active,
  .scan-progress-popover.scan-progress-reveal-leave-active {
    animation-name: scan-progress-fade;
    animation-duration: 80ms;
  }
  .scan-progress-popover.scan-progress-reveal-leave-active { animation-direction: reverse; }
  @keyframes scan-progress-fade { from { opacity: 0; } to { opacity: 1; } }
}
</style>
