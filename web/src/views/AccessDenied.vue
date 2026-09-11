<template><a-result status="403" :title="t('iam.noAccess')"><template #extra><a-button v-if="accessState.default_path !== '/access-denied'" type="primary" @click="$router.push(accessState.default_path)">{{ t('iam.back') }}</a-button></template></a-result></template>
<script setup>
import { useI18n } from 'vue-i18n'
import { accessState } from '../access'
const { t } = useI18n()
</script>
