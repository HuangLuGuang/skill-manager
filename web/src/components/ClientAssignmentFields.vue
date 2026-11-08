<template>
  <a-form-item name="device_user" :label="t('deviceAssignment.user')" :tooltip="t(allowCustomUser ? 'deviceAssignment.chooseOrEnterHelp' : userOptions ? 'deviceAssignment.selectUserHelp' : 'deviceAssignment.userHelp')" :rules="userOptions && !allowCustomUser ? [{ required: true, message: t('deviceAssignment.userRequired') }, ...rules(128)] : rules(128)">
    <a-auto-complete v-if="allowCustomUser" v-model:value="model.device_user" :options="userOptions || []" :filter-option="filterUser" allow-clear :placeholder="t('deviceAssignment.chooseOrEnter')" />
    <a-select v-else-if="userOptions" v-model:value="model.device_user" :options="userOptions" show-search option-filter-prop="label" :loading="usersLoading" :disabled="usersLoading" :placeholder="t('deviceAssignment.selectUser')" />
    <a-input v-else v-model:value="model.device_user" />
  </a-form-item>
  <a-form-item name="assignment_note" :label="t('deviceAssignment.note')" :tooltip="t('deviceAssignment.noteHelp')" :rules="rules(1000)">
    <a-textarea v-model:value="model.assignment_note" :auto-size="{ minRows: 2, maxRows: 4 }" />
  </a-form-item>
</template>
<script setup>
import { useI18n } from 'vue-i18n'
defineProps({ model: { type: Object, required: true }, userOptions: { type: Array, default: null }, usersLoading: Boolean, allowCustomUser: Boolean })
const { t } = useI18n()
const filterUser = (input, option) => option.value.toLocaleLowerCase().includes(input.toLocaleLowerCase())
const rules = limit => [{ validator: (_, value) => {
  const count = Array.from(value || '').length
  return count > limit ? Promise.reject(t('deviceAssignment.tooLong', { limit, count })) : Promise.resolve()
} }]
</script>
