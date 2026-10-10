<template>
  <details class="product-capabilities">
    <summary>{{ t('catalog.title') }}</summary>
    <p>{{ t('catalog.note') }}</p>
    <div class="product-table"><table>
      <thead><tr><th>{{ t('catalog.product') }}</th><th>{{ t('catalog.entry') }}</th><th>{{ t('catalog.logs') }}</th><th>Hook</th><th>{{ t('catalog.control') }}</th><th>{{ t('catalog.samples') }}</th></tr></thead>
      <tbody v-for="group in groups" :key="group.id"><tr v-for="(p, index) in group.entries" :key="p.id">
        <td v-if="index === 0" :rowspan="group.entries.length" class="product-name"><AgentProductLogo :product-id="group.id" />{{ group.name }}</td>
        <td>{{ t(`catalog.entries.${p.entry}`) }}<small>{{ p.os.join(' / ') || t('unknown') }}</small></td>
        <td>{{ p.logs || t('catalog.notImplemented') }}<small v-if="p.logs">{{ p.log_os.join(' / ') }}</small><small v-for="root in p.roots" :key="root">~/{{ root }}</small></td>
        <td>{{ p.hooks ? t('catalog.implemented') : t('catalog.notImplemented') }}<small v-if="p.hooks">{{ p.hook_os.join(' / ') }}</small><small v-if="p.hooks">{{ Object.keys(p.hook_events).length }} {{ t('catalog.events') }}</small></td>
        <td>{{ p.block ? t('catalog.block') : '—' }}<small v-if="p.approval">{{ t('catalog.approval') }}</small></td>
        <td>{{ p.sample_versions.join(' / ') || '—' }}<small>{{ translate('aidr.skillUse.' + (p.skill_usage?.invocation ? 'invocationAdapter' : p.skill_usage?.file_access ? 'fileAdapter' : 'unverifiedAdapter')) }}</small></td>
      </tr></tbody>
    </table></div>
  </details>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import products from '../aidr-products.json'
import { groupProductEntries } from '../aidr-product-groups'
import AgentProductLogo from './AgentProductLogo.vue'
const props = defineProps({ productIds: { type: Array, default: null } })
const groups = computed(() => groupProductEntries(products.filter(p => p.collection_visible !== false && (!props.productIds || props.productIds.includes(p.id)))))
const { t: translate } = useI18n()
const t = key => translate(`agentRuntimeGovernance.${key}`)
</script>
<style scoped>
.product-capabilities { margin: 12px 0; }
.product-capabilities summary { cursor: pointer; }
.product-capabilities p { color: #64748b; margin: 8px 0; }
.product-table { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }
th, td { padding: 8px; border-bottom: 1px solid #e2e8f0; vertical-align: top; min-width: 92px; overflow-wrap: anywhere; }
small { display: block; color: #64748b; margin-top: 4px; }
.product-name { font-weight: 600; }
.product-name :deep(.agent-product-logo) { width: 24px; height: 24px; margin-bottom: 8px; }
tbody + tbody { border-top: 1px solid #cbd5e1; }
</style>
