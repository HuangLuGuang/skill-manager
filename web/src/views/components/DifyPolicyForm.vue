<template>
  <a-form layout="vertical" :model="model" :disabled="disabled" @finish="$emit('save')">
    <div class="policy-grid">
      <a-form-item :label="t('difyRuntime.mode')"><a-select :value="mode" @update:value="$emit('update:mode', $event)" :options="options(['observe','enforce','disabled'])" /></a-form-item>
      <a-form-item :label="t('difyRuntime.defaultDecision')"><a-select v-model:value="model.default" :options="options(['allow','deny'])" /></a-form-item>
      <a-form-item name="approval_seconds" :rules="[{required:true,type:'integer',min:10,max:300,message:t('difyRuntime.numberRange',{min:10,max:300})}]" :label="t('difyRuntime.approvalSeconds')"><a-input-number v-model:value="model.approval_seconds" :step="1" /></a-form-item>
      <a-form-item name="max_actions" :rules="[{required:true,type:'integer',min:1,max:10000,message:t('difyRuntime.numberRange',{min:1,max:10000})}]" :label="t('difyRuntime.maxActions')"><a-input-number v-model:value="model.max_actions" :step="1" /></a-form-item>
    </div>
    <a-form-item :label="t('difyRuntime.approvedGraphs')" :extra="t('difyRuntime.graphHelp')"><a-select v-model:value="model.approved_graphs" mode="multiple" :options="[...new Set([...graphs,...model.approved_graphs])].map(value => ({ value, label:value }))" /></a-form-item>
    <div class="rules-heading"><h3>{{ t('difyRuntime.rules') }}</h3><a-button :disabled="disabled || model.rules.length >= 100" @click="add">{{ t('difyRuntime.addRule') }}</a-button></div>
    <p class="muted">{{ t('difyRuntime.rulesHelp') }}</p>
    <section v-for="(rule,index) in model.rules" :key="index" class="rule">
      <header><strong>{{ t('difyRuntime.ruleNumber', { number:index+1 }) }}</strong><a-space><a-button :disabled="disabled || index === 0" @click="move(index,-1)">{{ t('difyRuntime.up') }}</a-button><a-button :disabled="disabled || index === model.rules.length-1" @click="move(index,1)">{{ t('difyRuntime.down') }}</a-button><a-button danger :disabled="disabled" @click="model.rules.splice(index,1)">{{ t('difyRuntime.remove') }}</a-button></a-space></header>
      <div class="policy-grid">
        <a-form-item :name="['rules',index,'rule_id']" :rules="[{required:true,whitespace:true,message:t('difyRuntime.ruleNameError')}]" :label="t('difyRuntime.ruleName')"><a-input v-model:value="rule.rule_id" :maxlength="64" /></a-form-item>
        <a-form-item :label="t('difyRuntime.type')"><a-select v-model:value="rule.node_type" :options="nodeOptions" /></a-form-item>
        <a-form-item :label="t('difyRuntime.decision')"><a-select v-model:value="rule.effect" :options="options(['allow','deny','approval'])" /></a-form-item>
        <a-form-item :label="t('difyRuntime.fields.host')"><a-input v-model:value="rule.host" :maxlength="253" :placeholder="t('difyRuntime.any')" /></a-form-item>
        <a-form-item :label="t('difyRuntime.fields.tool')"><a-input v-model:value="rule.tool" :maxlength="256" :placeholder="t('difyRuntime.any')" /></a-form-item>
        <a-form-item :label="t('difyRuntime.fields.method')"><a-select v-model:value="rule.method" :options="[{value:'',label:t('difyRuntime.any')}, ...['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'].map(value => ({value,label:value}))]" /></a-form-item>
      </div>
      <a-collapse ghost><a-collapse-panel key="more" :header="t('difyRuntime.moreConditions')"><div class="policy-grid">
        <a-form-item v-for="field in ['node_id','dataset','code_digest']" :key="field" :label="t(`difyRuntime.conditionLabels.${field}`)"><a-input v-model:value="rule[field]" :placeholder="t('difyRuntime.any')" /></a-form-item>
        <a-form-item :label="t('difyRuntime.afterNode')"><a-select v-model:value="rule.after_node_type" :options="nodeOptions" /></a-form-item>
      </div></a-collapse-panel></a-collapse>
    </section>
    <a-button type="primary" html-type="submit" :loading="saving" :disabled="disabled">{{ t('difyRuntime.save') }}</a-button>
  </a-form>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
const model=defineModel({type:Object,required:true})
defineProps({mode:String,disabled:Boolean,saving:Boolean,graphs:{type:Array,default:()=>[]}})
defineEmits(['update:mode','save'])
const {t}=useI18n()
const options=values=>values.map(value=>({value,label:t(`difyRuntime.${value}`)}))
const nodeOptions=computed(()=>[{value:'',label:t('difyRuntime.any')},...['http-request','code','tool','knowledge-retrieval','llm','agent','skill','shell'].map(value=>({value,label:t(`difyRuntime.nodeLabels.${value}`)}))])
function add(){ model.value.rules.push({rule_id:'',node_type:'',effect:'deny',host:'',method:'',tool:'',node_id:'',dataset:'',code_digest:'',after_node_type:''}) }
function move(index,offset){ const [rule]=model.value.rules.splice(index,1);model.value.rules.splice(index+offset,0,rule) }
</script>
<style scoped>
.policy-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 20px}.rules-heading,.rule header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.rule{border:1px solid #e5eaf1;border-radius:8px;padding:16px;margin:16px 0;background:#fff}.rule header{margin-bottom:16px}.muted{font-size:12px;color:#7b8799}.ant-input-number{width:100%}@media(max-width:760px){.policy-grid{grid-template-columns:1fr}}
</style>
