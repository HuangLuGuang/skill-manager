<template>
  <a-select
    :value="modelValue"
    :options="options"
    show-search
    option-filter-prop="label"
    style="width: 100%"
    @update:value="$emit('update:modelValue', $event)"
  />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ modelValue: String })
defineEmits(['update:modelValue'])

const commonZones = ['Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Singapore', 'Asia/Tokyo', 'UTC', 'Europe/London', 'America/New_York', 'America/Los_Angeles']
const supportedZones = Intl.supportedValuesOf('timeZone')
const options = computed(() => [...new Set([...commonZones, ...supportedZones, props.modelValue].filter(Boolean))]
  .map(value => ({ value, label: value })))
</script>
