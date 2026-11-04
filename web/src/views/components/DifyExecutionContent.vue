<template>
  <div class="execution-fields">
    <template v-for="(item,key) in fields" :key="key">
      <section v-if="key === 'skill_admission'" class="skill-admission">
        <a-descriptions size="small" :column="1">
          <a-descriptions-item :label="t('difyRuntime.skillAdmission.name')">{{ item.name }}</a-descriptions-item>
          <a-descriptions-item :label="t('difyRuntime.skillAdmission.certification')"><a-tag :color="item.certified ? 'green' : 'orange'">{{ t(`difyRuntime.skillAdmission.${item.certified ? 'certified' : 'uncertified'}`) }}</a-tag>{{ admissionLabel('states', item.status) }}</a-descriptions-item>
          <a-descriptions-item :label="t('difyRuntime.skillAdmission.decision')"><a-tag :color="item.allowed ? 'blue' : 'red'">{{ t(`difyRuntime.skillAdmission.${item.allowed ? 'allowed' : 'blocked'}`) }}</a-tag></a-descriptions-item>
          <a-descriptions-item :label="t('difyRuntime.skillAdmission.reason')">{{ admissionLabel('reasons', item.reason) }}</a-descriptions-item>
          <a-descriptions-item v-if="!item.certified" :label="t('difyRuntime.skillAdmission.checkReason')">{{ admissionLabel('checks', item.check_reason) }}</a-descriptions-item>
        </a-descriptions>
      </section>
      <section v-else-if="key === 'prompt_messages' && Array.isArray(item)" class="messages">
        <article v-for="(message,index) in item" :key="index"><strong>{{ message.role }}</strong><pre>{{ display(message.content) }}</pre></article>
      </section>
      <section v-else><span v-if="key !== 'text'" class="field-name">{{ key }}</span><pre>{{ display(item) }}</pre></section>
    </template>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
const { t, te } = useI18n()
const admissionLabel=(group,value)=>{const key=`difyRuntime.skillAdmission.${group}.${value}`;return te(key) ? t(key) : value || '—'}
const props=defineProps({ value:{required:true} })
const fields=computed(()=>{
  const value=props.value && typeof props.value === 'object' && !Array.isArray(props.value) ? props.value : {text:props.value}
  return Object.fromEntries(Object.entries(value).filter(([,item])=>item !== null && item !== undefined && !(typeof item==='object' && !Object.keys(item).length)))
})
const display=value=>typeof value === 'string' ? value : JSON.stringify(value,null,2)
</script>
<style scoped>
.execution-fields{min-width:0}.execution-fields section{margin:8px 0}.field-name,.messages strong{font-size:12px;color:#64748b}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:440px;overflow:auto;padding:12px;background:#f8fafc;border:1px solid #e5eaf1;border-radius:6px;font-size:12px;margin:4px 0 12px}
</style>
