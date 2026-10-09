<template>
  <a-input :id="id" :value="value" inputmode="numeric" :disabled="disabled" @update:value="emit('update:value', $event)">
    <template #suffix>
      <span class="integer-controls">
        <button type="button" :aria-label="t('policySettings.increase')" :disabled="disabled || stepped(step) === value" @click="emit('update:value', stepped(step))">+</button>
        <button type="button" :aria-label="t('policySettings.decrease')" :disabled="disabled || stepped(-step) === value" @click="emit('update:value', stepped(-step))">−</button>
      </span>
    </template>
  </a-input>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { stepInteger } from '../utils/advancedConfig.js'

const props = defineProps({
  id: { type: String, required: true },
  value: { type: [String, Number], default: '' },
  min: { type: Number, required: true },
  max: { type: Number, required: true },
  step: { type: Number, default: 1 },
  disabled: Boolean,
})
const emit = defineEmits(['update:value'])
const { t } = useI18n()
const stepped = delta => stepInteger(props.value, delta, props.min, props.max)
</script>

<style scoped>
.integer-controls { display: flex; flex-direction: column; margin: -4px -10px -4px 4px; }
.integer-controls button { width: 24px; height: 15px; padding: 0; border: 0; border-left: 1px solid #d9d9d9; background: transparent; line-height: 14px; cursor: pointer; }
.integer-controls button + button { border-top: 1px solid #d9d9d9; }
.integer-controls button:disabled { color: #bfbfbf; cursor: not-allowed; }
</style>
