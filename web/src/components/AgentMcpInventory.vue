<template>
  <div class="mcp-inventory">
    <p class="muted">{{ t('localAssets.originHelp') }}</p>
    <a-table :columns="columns" :data-source="items" :row-key="row => row.row_key || row.id" size="small" :pagination="{ pageSize: 8, hideOnSinglePage: true }" :scroll="{ x: 620 }" :locale="{ emptyText: t('localAssets.empty') }">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'"><strong>{{ record.name }}</strong><div class="muted">{{ record.plugin_name || t('localAssets.standalone') }}</div></template>
        <template v-else-if="column.key === 'connection'">
          <a-tag>{{ ['unknown', 'registered'].includes(record.transport) ? t(`localAssets.${record.transport}`) : record.transport }}</a-tag>
          <div class="asset-path">{{ record.endpoint_origin || record.executable || record.server_reference || '—' }}</div>
          <div v-if="record.argument_count" class="muted">{{ t('localAssets.args', { count: record.argument_count }) }}</div>
          <details v-if="record.credential_keys?.length"><summary>{{ t('localAssets.credentialKeys') }}</summary><div class="asset-path">{{ record.credential_keys.join(', ') }}</div></details>
        </template>
        <template v-else-if="column.key === 'enabled'"><a-tag>{{ t(record.enabled === true ? 'localAssets.yes' : record.enabled === false ? 'localAssets.no' : 'localAssets.unknown') }}</a-tag></template>
        <template v-else-if="column.key === 'source'"><div class="asset-path">{{ scopeText(record.scope) }}</div><div class="asset-path muted">{{ record.source_path }}</div></template>
      </template>
    </a-table>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { withAssetNameSearch } from '../utils/assetNameSearch'
defineProps({ items: { type: Array, default: () => [] } })
const { t } = useI18n()
const scopeText = value => ['user', 'managed', 'project', 'local'].includes(value) ? t(`localAssets.${value}`) : value
const columns = computed(() => [
  withAssetNameSearch({ title: t('localAssets.name'), key: 'name', width: 150 }),
  { title: t('localAssets.endpoint'), key: 'connection', width: 200 },
  { title: t('localAssets.enabled'), key: 'enabled', width: 120 },
  { title: t('localAssets.source'), key: 'source' },
])
</script>

<style scoped>
.mcp-inventory { min-width: 0; }
.asset-path { overflow-wrap: anywhere; white-space: normal; }
.muted { color: #6b7280; font-size: 12px; }
summary { cursor: pointer; white-space: normal; }
</style>
