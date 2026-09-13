<template>
  <a-modal :open="open" :title="$t('clientDiscovery.title')" :width="960" :confirm-loading="saving" :ok-button-props="{ disabled: loading || !!error }" :ok-text="$t('clientDiscovery.save')" :cancel-text="$t('clientDiscovery.close')" :closable="!saving" :mask-closable="false" @cancel="close" @ok="save">
    <a-alert :message="$t('clientDiscovery.description')" type="info" show-icon class="notice" />
    <a-alert v-if="error" :message="error" type="error" show-icon class="notice" />
    <a-spin :spinning="loading">
      <a-input v-model:value="search" allow-clear class="agent-search" :placeholder="$t('clientDiscovery.search')" :aria-label="$t('clientDiscovery.search')" />
      <div class="definitions">
        <a-empty v-if="!loading && !error && !filteredAgents.length" :description="$t('clientDiscovery.noMatches')" />
        <section v-for="{ agent, index } in filteredAgents" :key="index" class="definition">
          <div class="heading">
            <strong>{{ agent.name || $t('clientDiscovery.newAgent') }}</strong>
            <a-button v-if="agent.isNew" type="link" :disabled="saving" @click="agents.splice(index, 1)">{{ $t('clientDiscovery.remove') }}</a-button>
            <a-switch v-model:checked="agent.enabled" :disabled="saving" :aria-label="$t('clientDiscovery.enabled')" />
          </div>
          <div class="fields">
            <label>{{ $t('clientDiscovery.name') }}<a-input v-model:value="agent.name" :disabled="saving" :maxlength="80" /></label>
            <label>{{ $t('clientDiscovery.identifier') }}<a-input v-model:value="agent.agent_type" :disabled="saving || !agent.isNew" :maxlength="64" /></label>
            <label>{{ $t('clientDiscovery.systems') }}<a-select v-model:value="agent.systems" mode="multiple" :disabled="saving" :options="systems" /></label>
          </div>
          <label class="roots">{{ $t('clientDiscovery.roots') }}<a-textarea v-model:value="agent.rootsText" :disabled="saving" :auto-size="{ minRows: 1, maxRows: 4 }" :placeholder="$t('clientDiscovery.rootsHelp')" /></label>
          <div v-if="!agent.rootsText.trim()" class="hint">{{ $t('clientDiscovery.missingPath') }}</div>
        </section>
      </div>
      <a-button :disabled="loading || saving || !!error || agents.length >= 100" @click="add">{{ $t('clientDiscovery.add') }}</a-button>
    </a-spin>
  </a-modal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { getClientDiscoveryConfig, updateClientDiscoveryConfig } from '../api'
const props = defineProps({ open: Boolean })
const emit = defineEmits(['update:open'])
const { t } = useI18n()
const agents = ref([])
const search = ref('')
const filteredAgents = computed(() => {
  const query = search.value.trim().toLowerCase()
  return agents.value.map((agent, index) => ({ agent, index }))
    .filter(({ agent }) => !query || agent.name.toLowerCase().includes(query) || agent.agent_type.toLowerCase().includes(query))
})
const loading = ref(false)
const saving = ref(false)
const error = ref('')
let version = ''
let sequence = 0
const systems = [{ value: 'darwin', label: 'macOS' }, { value: 'windows', label: 'Windows' }, { value: 'linux', label: 'Linux' }]
watch(() => props.open, async open => {
  const request = ++sequence
  if (!open) return
  search.value = ''
  loading.value = true
  error.value = ''
  agents.value = []
  try {
    const data = await getClientDiscoveryConfig()
    if (request !== sequence) return
    version = data.version
    agents.value = data.agents.map(agent => ({ ...agent, rootsText: agent.skill_roots.join('\n') }))
  } catch {
    if (request === sequence) error.value = t('clientDiscovery.loadFailed')
  } finally {
    if (request === sequence) loading.value = false
  }
})
function close() { if (!saving.value) emit('update:open', false) }
function add() { search.value = ''; agents.value.push({ agent_type: '', name: '', enabled: false, systems: ['darwin', 'windows', 'linux'], rootsText: '', isNew: true }) }
async function save() {
  if (saving.value || loading.value || error.value) return
  const definitions = agents.value.map(({ agent_type, name, enabled, systems, rootsText }) => ({ agent_type: agent_type.trim(), name: name.trim(), enabled, systems, skill_roots: rootsText.split('\n').map(value => value.trim()).filter(Boolean) }))
  if (definitions.some(a => !a.name || !/^[a-z][a-z0-9-]{0,63}$/.test(a.agent_type) || !a.systems.length || (a.enabled && !a.skill_roots.length)) || new Set(definitions.map(a => a.agent_type)).size !== definitions.length) {
    message.error(t('clientDiscovery.invalid'))
    return
  }
  saving.value = true
  try {
    await updateClientDiscoveryConfig({ expected_version: version, agents: definitions })
    message.success(t('clientDiscovery.saved'))
    emit('update:open', false)
  } catch (failure) {
    message.error(t(failure.response?.status === 409 ? 'clientDiscovery.conflict' : 'clientDiscovery.saveFailed'))
  } finally { saving.value = false }
}
</script>

<style scoped>
.notice { margin-bottom: 16px; }
.agent-search { margin-bottom: 16px; }
.definitions { max-height: 58vh; overflow-y: auto; padding-right: 8px; margin-bottom: 16px; }
.definition { border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.fields { display: grid; grid-template-columns: 1fr 1fr 1.4fr; gap: 12px; }
label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.roots { margin-top: 12px; }
.hint { color: #64748b; margin-top: 6px; }
@media (max-width: 680px) { .fields { grid-template-columns: 1fr; } }
</style>
