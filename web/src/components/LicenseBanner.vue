<template><a-alert v-if="failed || status && status.state !== 'valid'" class="license-banner" type="warning" show-icon :message="failed ? t('license.unavailable') : t('license.banner',{state:t(`license.states.${status.state}`)})"><template #description>{{ t('license.expiry') }} <router-link v-if="can('license:view')" to="/license">{{ t('license.manage') }}</router-link></template></a-alert></template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getLicenseStatus } from '../api'
import { can } from '../access'
const { t } = useI18n(), status = ref(null), failed = ref(false)
let timer, loading = false, active = true
async function load() { if(loading)return;loading=true;try {const value=await getLicenseStatus();if(active){status.value=value;failed.value=false}}catch{if(active)failed.value=true}finally{loading=false} }
onMounted(()=>{load();timer=setInterval(load,60000);window.addEventListener('license-changed',load)})
onUnmounted(()=>{active=false;clearInterval(timer);window.removeEventListener('license-changed',load)})
</script>
<style scoped>.license-banner { margin-bottom:18px; } a { margin-left:8px; }</style>
