<template>
  <section class="policy-workbench">
    <header class="workbench-heading">
      <div><h3>{{ t('clientPolicy.title') }}</h3><p>{{ t('clientPolicy.description') }}</p></div>
      <div class="settings-actions">
        <a-button v-if="can('clients:view')" @click="emit('configure', 'integration')"><SettingOutlined />{{ t('clientPolicy.configure') }}</a-button>
        <a-button v-if="can('settings:view')" @click="emit('configure', 'audit')"><FileProtectOutlined />{{ t('clientPolicy.content') }}</a-button>
      </div>
    </header>
    <nav class="policy-navigation" :aria-label="t('clientPolicy.navigation')">
      <button v-for="item in sections" :key="item.key" type="button" :aria-pressed="modelValue === item.key" @click="emit('update:modelValue', item.key)">
        <component :is="item.icon" class="nav-icon" aria-hidden="true" />
        <span><strong>{{ t(`clientPolicy.${item.key}`) }}</strong><small>{{ t(`clientPolicy.${item.key}Hint`) }}</small></span>
        <RightOutlined class="nav-arrow" aria-hidden="true" />
      </button>
    </nav>
    <div class="policy-content">
      <ClientHookPanel v-show="modelValue !== 'system'" :client-id="clientId" view="control" :control-section="modelValue === 'approvals' ? 'approvals' : 'rules'" />
      <ClientEnforcementPanel v-if="systemVisited" v-show="modelValue === 'system'" :client-id="clientId" view="control" />
    </div>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { SettingOutlined, FileProtectOutlined, SafetyOutlined, CheckSquareOutlined, DesktopOutlined, RightOutlined } from '@ant-design/icons-vue'
import { can } from '../access'
import ClientHookPanel from './ClientHookPanel.vue'
import ClientEnforcementPanel from './ClientEnforcementPanel.vue'
const props = defineProps({ clientId: { type: String, required: true }, modelValue: { type: String, default: 'tools' } })
const emit = defineEmits(['update:modelValue', 'configure'])
const { t } = useI18n()
const sections = [{ key: 'tools', icon: SafetyOutlined }, { key: 'approvals', icon: CheckSquareOutlined }, { key: 'system', icon: DesktopOutlined }]
const systemVisited = ref(false)
watch(() => props.modelValue, value => { if (value === 'system') systemVisited.value = true }, { immediate: true })
</script>

<style scoped>
.policy-workbench { --policy-ink: #23354d; --policy-muted: #66768c; --policy-line: #e4eaf2; color: var(--policy-ink); }
.workbench-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 8px 0 20px; }
.workbench-heading h3 { margin: 0; font-size: 18px; font-weight: 650; letter-spacing: -.3px; }
.workbench-heading p { margin: 5px 0 0; color: var(--policy-muted); font-size: 13px; }
.settings-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.policy-navigation { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
.policy-navigation button { display: flex; align-items: center; gap: 12px; min-width: 0; padding: 16px; border: 1px solid var(--policy-line); border-radius: 10px; background: #fff; text-align: start; color: var(--policy-ink); cursor: pointer; font: inherit; }
.policy-navigation button:hover { border-color: #9bb6f6; background: #fafcff; }
.policy-navigation button[aria-pressed=true] { border-color: #3265df; background: #f3f7ff; box-shadow: inset 0 3px #3265df; }
.policy-navigation button:focus-visible { outline: 2px solid #3265df; outline-offset: 3px; }
.policy-navigation strong, .policy-navigation small { display: block; }
.policy-navigation strong { font-size: 14px; font-weight: 600; }
.policy-navigation small { margin-top: 4px; font-size: 12px; line-height: 1.5; color: var(--policy-muted); }
.nav-icon { font-size: 20px; color: #66809f; }
[aria-pressed=true] .nav-icon { color: #3265df; }
.nav-arrow { margin-left: auto; font-size: 10px; color: #8090a7; }
.policy-content { border-top: 1px solid var(--policy-line); padding-top: 20px; min-width: 0; }
@media (max-width: 800px) {
  .workbench-heading { align-items: flex-start; flex-direction: column; }
  .policy-navigation { gap: 8px; }
  .policy-navigation button { padding: 12px 10px; gap: 8px; align-items: flex-start; }
  .nav-arrow { display: none; }
}
@media (max-width: 520px) {
  .policy-navigation { grid-template-columns: 1fr; }
  .policy-navigation button[aria-pressed=true] { box-shadow: inset 3px 0 #3265df; }
  .settings-actions :deep(.ant-btn) { height: auto; min-height: 32px; white-space: normal; }
}
</style>
