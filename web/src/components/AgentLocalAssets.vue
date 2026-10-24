<template>
  <section class="local-assets">
      <a-tabs v-model:active-key="activeTab">
        <a-tab-pane key="skills" :tab="`${t('localAssets.skills')} (${skills.length})`">
          <slot name="skills">
            <a-table :columns="skillColumns" :data-source="skills" row-key="path" size="small" :pagination="{ pageSize: 8, hideOnSinglePage: true }" :scroll="{ x: 480 }" :locale="{ emptyText: t('localAssets.empty') }">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'name'"><strong>{{ record.name }}</strong></template>
                <template v-else-if="column.key === 'path'"><div class="asset-path">{{ record.path }}</div></template>
              </template>
            </a-table>
          </slot>
        </a-tab-pane>
        <a-tab-pane v-if="integrations" key="plugins" :tab="assetTabLabel('plugins', inventory?.plugins.length)">
          <a-alert v-if="!inventory" type="info" show-icon :message="t('localAssets.unreported')" />
          <a-alert v-else-if="!inventory.plugin_supported" type="info" :message="t('localAssets.unsupported')" />
          <a-table v-else :columns="columns" :data-source="inventory.plugins" row-key="id" size="small" :pagination="{ pageSize: 8, hideOnSinglePage: true }" :scroll="{ x: 640 }" :locale="{ emptyText: t('localAssets.empty') }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'"><strong>{{ record.name }}</strong><div class="muted">{{ record.version || '—' }} · {{ record.format === 'unknown' ? t('localAssets.unknown') : record.format }}</div></template>
              <template v-else-if="column.key === 'state'"><a-tag>{{ t(`localAssets.${record.state === 'local' ? 'localFiles' : record.state}`) }}</a-tag><div>{{ t(record.enabled === true ? 'localAssets.yes' : record.enabled === false ? 'localAssets.no' : 'localAssets.unknown') }}</div></template>
              <template v-else-if="column.key === 'components'"><div>{{ t('localAssets.skills') }} {{ record.skills.length }}</div><div>{{ t('localAssets.mcp') }} {{ record.mcp_servers.length }}</div></template>
              <template v-else-if="column.key === 'path'"><div class="asset-path">{{ record.path || '—' }}</div><div class="asset-path muted">{{ scopeText(record.scope) }}</div></template>
            </template>
            <template #expandedRowRender="{ record }">
              <p class="asset-path muted">{{ t('localAssets.source') }} · {{ record.source_path }}</p>
              <h4>{{ t('localAssets.skills') }} ({{ record.skills.length }})</h4>
              <a-empty v-if="!record.skills.length" :description="t('localAssets.empty')" :image="simpleImage" />
              <ul v-else class="bundled-skills"><li v-for="skill in record.skills" :key="skill.path"><strong>{{ skill.name }}</strong><div class="asset-path muted">{{ skill.path }}</div></li></ul>
              <h4>{{ t('localAssets.mcp') }} ({{ record.mcp_servers.length }})</h4>
              <AgentMcpInventory :items="record.mcp_servers.map(item => ({ ...item, plugin_name: record.name }))" />
            </template>
          </a-table>
        </a-tab-pane>
        <a-tab-pane v-if="integrations" key="mcp" :tab="assetTabLabel('mcp', mcps.length)">
          <a-alert v-if="!inventory" type="info" show-icon :message="t('localAssets.unreported')" />
          <a-alert v-else-if="!inventory.mcp_supported && !mcps.length" type="info" :message="t('localAssets.unsupported')" />
          <AgentMcpInventory v-else :items="mcps" />
        </a-tab-pane>
      </a-tabs>
    <template v-if="inventory && activeTab !== 'skills'">
      <p class="muted">{{ t('localAssets.boundary') }}</p>
      <p class="muted">{{ t('localAssets.observedAt') }} · {{ formatDateTime(inventory.observed_at) }}</p>
      <a-alert v-if="inventory.issues?.length" type="warning" show-icon :message="t('localAssets.partial')">
        <template #description><ul class="issues"><li v-for="(issue, index) in inventory.issues" :key="index">{{ t(`localAssets.${issue.code}`) }} · {{ issue.path }}</li></ul></template>
      </a-alert>
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Empty } from 'ant-design-vue'
import { formatDateTime } from '../utils/format'
import AgentMcpInventory from './AgentMcpInventory.vue'
import { withAssetNameSearch } from '../utils/assetNameSearch'
const props = defineProps({
  initialTab: { type: String, default: 'skills' },
  inventory: { type: Object, default: null },
  skills: { type: Array, default: () => [] },
  integrations: { type: Boolean, default: true },
})
const activeTab = ref(props.initialTab)
const { t } = useI18n(), simpleImage = Empty.PRESENTED_IMAGE_SIMPLE
const assetTabLabel = (key, count) => t(`localAssets.${key}`) + (props.inventory ? ` (${count})` : '')
const skillColumns = computed(() => [
  withAssetNameSearch({ title: t('localAssets.name'), key: 'name', width: 180 }),
  { title: t('localAssets.path'), key: 'path' },
])
const scopeText = value => ['user', 'managed', 'project', 'local'].includes(value) ? t(`localAssets.${value}`) : value
const mcps = computed(() => [
  ...(props.inventory?.mcp_servers || []),
  ...(props.inventory?.plugins || []).flatMap(plugin => plugin.mcp_servers.map(item => ({ ...item, row_key: `${plugin.id}:${item.id}`, plugin_name: plugin.name }))),
])
const columns = computed(() => [
  withAssetNameSearch({ title: t('localAssets.name'), key: 'name', width: 160 }),
  { title: t('localAssets.state'), key: 'state', width: 140 },
  { title: t('localAssets.components'), key: 'components', width: 120 },
  { title: t('localAssets.path'), key: 'path' },
])
</script>

<style scoped>
.local-assets { min-width: 0; margin: 12px 0; }
/* Asset tabs provide their own inset; reset Ant Design's nested-table margins. */
.local-assets :deep(.ant-table-wrapper .ant-table) { margin: 0 !important; }
.asset-path, .issues { overflow-wrap: anywhere; white-space: normal; }
.issues { max-height: 180px; overflow: auto; padding-left: 18px; }
.muted { color: #6b7280; font-size: 12px; }
.bundled-skills { padding-left: 20px; }
.bundled-skills li { margin-bottom: 10px; }
</style>
