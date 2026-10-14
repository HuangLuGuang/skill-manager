<template>
  <div class="asset-name-search" @keydown.stop>
    <label :for="inputId">{{ t('localAssets.searchName') }}</label>
    <a-input :id="inputId" ref="input" :value="selectedKeys[0] || ''" :placeholder="t('localAssets.searchPlaceholder')" allow-clear @update:value="update" @pressEnter="apply(true)" />
    <p>{{ t('localAssets.searchHint') }}</p>
    <div class="search-actions"><a-button size="small" @click="reset">{{ t('localAssets.clearSearch') }}</a-button><a-button size="small" type="primary" @click="apply(true)">{{ t('localAssets.search') }}</a-button></div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
const props = defineProps({
  selectedKeys: { type: Array, default: () => [] },
  setSelectedKeys: { type: Function, required: true },
  confirm: { type: Function, required: true },
  clearFilters: { type: Function, required: true },
  visible: Boolean,
})
const { t } = useI18n()
const input = ref(null), inputId = useId()
let timer
const apply = (closeDropdown = false) => {
  clearTimeout(timer)
  props.confirm({ closeDropdown })
}
const update = value => {
  props.setSelectedKeys(value ? [value] : [])
  clearTimeout(timer)
  timer = setTimeout(() => apply(), 300)
}
const reset = () => {
  clearTimeout(timer)
  props.clearFilters({ confirm: true, closeDropdown: false })
  input.value?.focus()
}
watch(() => props.visible, async visible => {
  clearTimeout(timer)
  if (visible) { await nextTick(); input.value?.focus() }
}, { immediate: true })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.asset-name-search { width: 260px; max-width: calc(100vw - 32px); padding: 16px; box-sizing: border-box; }
label { display: block; margin-bottom: 8px; font-weight: 600; }
p { margin: 8px 0 14px; color: #626b78; font-size: 12px; line-height: 1.6; white-space: normal; }
.search-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.search-actions :deep(.ant-btn) { height: auto; min-height: 24px; white-space: normal; }
</style>
