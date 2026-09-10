<template>
  <div class="timing-grid">
    <a-form-item :label="t('scanSchedule.frequency')"><a-select :value="modelValue.kind" :options="kinds" @update:value="set('kind', $event)" /></a-form-item>
    <a-form-item :label="t('scanSchedule.timezone')"><TimezoneSelect :model-value="modelValue.timezone" @update:model-value="set('timezone', $event)" /></a-form-item>
    <a-form-item v-if="modelValue.kind === 'interval'" :label="t('scanSchedule.minutes')"><a-input-number :value="modelValue.interval_minutes" :min="5" :max="525600" @update:value="set('interval_minutes', $event)" /></a-form-item>
    <a-form-item v-else-if="modelValue.kind === 'cron'" :label="t('scanSchedule.cron')"><a-input :value="modelValue.cron" @update:value="set('cron', $event)" /></a-form-item>
    <a-form-item v-else :label="t('scanSchedule.time')"><a-input type="time" :value="modelValue.time" @update:value="set('time', $event)" /></a-form-item>
    <a-form-item v-if="modelValue.kind === 'weekly'" :label="t('scanSchedule.weekday')"><a-select :value="modelValue.weekday" :options="days" @update:value="set('weekday', $event)" /></a-form-item>
  </div>
  <a-alert v-if="error" type="error" :message="error" />
  <div class="timing-preview"><strong>{{ t('scanSchedule.preview') }}</strong><span v-for="time in times" :key="time">{{ new Date(time).toLocaleString(locale, { timeZone: modelValue.timezone }) }} ({{ modelValue.timezone }})</span></div>
</template>
<script setup>
import { computed, ref, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { previewScanTiming } from '../../api'
import TimezoneSelect from './TimezoneSelect.vue'
const props = defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue', 'valid'])
const { t, locale } = useI18n()
const times = ref([]), error = ref('')
const kinds = computed(() => ['interval', 'daily', 'weekly', 'cron'].map(value => ({ value, label: t(`scanSchedule.${value}`) })))
const days = computed(() => Array.from({ length: 7 }, (_, value) => ({ value, label: t(`scanSchedule.weekdays.${value}`) })))
const set = (key, value) => emit('update:modelValue', { ...props.modelValue, [key]: value })
let timer, generation = 0
watch(() => props.modelValue, value => { clearTimeout(timer); const id = ++generation; times.value = []; emit('valid', false); timer = setTimeout(async () => { try { const data = await previewScanTiming(value); if (id !== generation) return; times.value = data.times; error.value = ''; emit('valid', true) } catch (e) { if (id === generation) error.value = e.response?.data?.detail || t('scanSchedule.invalid') } }, 300) }, { deep: true, immediate: true })
onUnmounted(() => { generation++; clearTimeout(timer) })
</script>
<style scoped>
.timing-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }.timing-grid :deep(.ant-input-number) { width: 100%; }.timing-preview { display: grid; gap: 6px; margin-bottom: 16px; color: #667085; overflow-wrap: anywhere; } @media(max-width: 600px) { .timing-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
