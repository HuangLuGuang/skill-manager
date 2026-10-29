<template>
  <section>
    <p class="discovery-help">{{ $t('clientDiscovery.description') }}</p>
    <p class="discovery-help">{{ $t(clientId ? 'clientDiscovery.overrideHelp' : 'clientDiscovery.globalHelp') }}</p>
    <a-alert v-if="error" :message="error" type="error" show-icon class="notice" />
    <a-spin :spinning="loading">
      <div class="discovery-toolbar">
        <a-input v-model:value="search" allow-clear class="agent-search" :placeholder="$t('clientDiscovery.search')" :aria-label="$t('clientDiscovery.search')" />
        <a-button v-if="clientId" :disabled="fieldsDisabled" @click="resetAll">{{ $t('clientDiscovery.resetAll') }}</a-button>
      </div>
      <div class="definitions">
        <a-empty v-if="!loading && !error && !filteredAgents.length" :description="$t('clientDiscovery.noMatches')" />
        <section v-for="{ agent, index } in filteredAgents" :key="index" class="definition">
          <div class="heading">
            <strong>{{ agent.name || $t('clientDiscovery.newAgent') }}</strong>
            <a-button v-if="agent.isNew || (clientId && !globalAgents.some(item => item.agent_type === agent.agent_type))" type="link" :disabled="fieldsDisabled" @click="agents.splice(index, 1)">{{ $t('clientDiscovery.remove') }}</a-button>
            <a-switch v-model:checked="agent.enabled" :disabled="agentDisabled(agent)" :aria-label="$t('clientDiscovery.enabled')" />
          </div>
          <a-checkbox v-if="clientId && !agent.isNew && globalAgents.some(item => item.agent_type === agent.agent_type)" :checked="!agent.override" :disabled="fieldsDisabled" @change="event => setInheritance(index, event.target.checked)">{{ $t('clientDiscovery.inherit') }}</a-checkbox>
          <a-tag v-else-if="clientId">{{ $t('clientDiscovery.clientOnly') }}</a-tag>
          <div class="fields">
            <label>{{ $t('clientDiscovery.name') }}<a-input v-model:value="agent.name" :disabled="agentDisabled(agent)" :maxlength="80" /></label>
            <label>{{ $t('clientDiscovery.identifier') }}<a-input v-model:value="agent.agent_type" :disabled="agentDisabled(agent) || !agent.isNew" :maxlength="64" /></label>
            <label>{{ $t('clientDiscovery.systems') }}<a-select v-model:value="agent.systems" mode="multiple" :disabled="agentDisabled(agent)" :options="systems" /></label>
          </div>
          <label class="roots">{{ $t('clientDiscovery.roots') }}<a-textarea v-model:value="agent.rootsText" :disabled="agentDisabled(agent)" :auto-size="{ minRows: 1, maxRows: 4 }" :placeholder="$t('clientDiscovery.rootsHelp')" /></label>
          <div v-if="!agent.rootsText.trim()" class="hint">{{ $t('clientDiscovery.missingPath') }}</div>
        </section>
      </div>
      <a-button :disabled="fieldsDisabled || agents.length >= 100" @click="add">{{ $t('clientDiscovery.add') }}</a-button>
    </a-spin>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { getClientDiscoveryConfig, updateClientDiscoveryConfig } from '../api'
import { can } from '../access'
const props = defineProps({ clientId: { type: String, default: '' } })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const agents = ref([])
const globalAgents = ref([])
const search = ref('')
const filteredAgents = computed(() => {
  const query = search.value.trim().toLowerCase()
  return agents.value.map((agent, index) => ({ agent, index }))
    .filter(({ agent }) => !query || agent.name.toLowerCase().includes(query) || agent.agent_type.toLowerCase().includes(query))
})
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const busy = computed(() => loading.value || saving.value)
const fieldsDisabled = computed(() => busy.value || !!error.value || !can('clients:update'))
const canSave = computed(() => !fieldsDisabled.value)
const agentDisabled = agent => fieldsDisabled.value || (!!props.clientId && !agent.override)
defineExpose({ busy, canSave, save })
let version = ''
let sequence = 0
const systems = [{ value: 'darwin', label: 'macOS' }, { value: 'windows', label: 'Windows' }, { value: 'linux', label: 'Linux' }]
function populate(data) {
  version = data.edit_version || data.version
  globalAgents.value = data.global_agents || data.agents
  agents.value = data.agents.map(agent => ({ ...agent, systems: [...agent.systems], rootsText: agent.skill_roots.join('\n'), override: (data.overrides || []).some(item => item.agent_type === agent.agent_type) }))
}
watch(() => props.clientId, async clientId => {
  const request = ++sequence
  search.value = ''
  loading.value = true
  error.value = ''
  agents.value = []
  try {
    const data = await getClientDiscoveryConfig(clientId)
    if (request !== sequence) return
    populate(data)
  } catch {
    if (request === sequence) error.value = t('clientDiscovery.loadFailed')
  } finally {
    if (request === sequence) loading.value = false
  }
}, { immediate: true })
function setInheritance(index, inherit) {
  if (!inherit) { agents.value[index].override = true; return }
  const original = globalAgents.value.find(item => item.agent_type === agents.value[index].agent_type)
  agents.value[index] = { ...original, systems: [...original.systems], rootsText: original.skill_roots.join('\n'), override: false }
}
function resetAll() {
  search.value = ''
  agents.value = globalAgents.value.map(agent => ({ ...agent, systems: [...agent.systems], rootsText: agent.skill_roots.join('\n'), override: false }))
}
function add() { search.value = ''; agents.value.push({ agent_type: '', name: '', enabled: false, systems: ['darwin', 'windows', 'linux'], rootsText: '', isNew: true, override: true }) }
async function save() {
  if (!canSave.value) return
  const types = agents.value.map(agent => agent.agent_type.trim())
  if (new Set(types).size !== types.length) { message.error(t('clientDiscovery.invalid')); return }
  const definitions = agents.value.filter(agent => !props.clientId || agent.override).map(({ agent_type, name, enabled, systems, rootsText }) => ({ agent_type: agent_type.trim(), name: name.trim(), enabled, systems, skill_roots: rootsText.split('\n').map(value => value.trim()).filter(Boolean) }))
  if (definitions.some(a => !a.name || !/^[a-z][a-z0-9-]{0,63}$/.test(a.agent_type) || !a.systems.length || (a.enabled && !a.skill_roots.length)) || new Set(definitions.map(a => a.agent_type)).size !== definitions.length) {
    message.error(t('clientDiscovery.invalid'))
    return
  }
  saving.value = true
  try {
    const data = await updateClientDiscoveryConfig({ expected_version: version, agents: definitions }, props.clientId)
    populate(data)
    message.success(t('clientDiscovery.saved'))
    emit('saved')
  } catch (failure) {
    message.error(t(failure.response?.status === 409 ? 'clientDiscovery.conflict' : 'clientDiscovery.saveFailed'))
  } finally { saving.value = false }
}
</script>

<style scoped>
.discovery-help { margin: 0 0 8px; color: #64748b; font-size: 12px; }
.notice { margin-bottom: 8px; }
.discovery-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
.agent-search { flex: 1 1 240px; min-width: 0; }
.definitions { margin-bottom: 8px; }
.definition { border-top: 1px solid #e5e7eb; padding: 16px 0; }
.heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.heading strong { overflow-wrap: anywhere; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.fields label, .roots { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.roots { margin-top: 12px; }
.hint { color: #64748b; margin-top: 6px; }
@media (max-width: 600px) { .fields { grid-template-columns: 1fr; } }
</style>
