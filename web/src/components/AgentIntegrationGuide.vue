<template>
  <section class="integration-guide">
    <template v-if="!scenario">
      <div class="scenario-grid">
        <button v-for="item in scenarios" :key="item.id" type="button" class="scenario-card" @click="chooseScenario(item.id)">
          <component :is="item.icon" class="scenario-icon" aria-hidden="true" />
          <strong>{{ t(`agentIntegration.scenarios.${item.id}.title`) }}</strong>
          <span>{{ t(`agentIntegration.scenarios.${item.id}.description`) }}</span>
          <small>{{ t(`agentIntegration.scenarios.${item.id}.path`) }}</small>
        </button>
      </div>
    </template>
    <template v-else>
      <a-button type="link" class="back-link" @click="chooseScenario('')"><ArrowLeftOutlined />{{ t('agentIntegration.back') }}</a-button>
      <h2>{{ t(`agentIntegration.scenarios.${scenario}.title`) }}</h2>
      <p class="muted">{{ t(`agentIntegration.scenarios.${scenario}.description`) }}</p>

      <template v-if="scenario === 'client'">
        <a-alert type="info" show-icon :message="t('agentIntegration.sources.client_discovery')" :description="t('agentIntegration.client.intro')" />
        <div class="client-steps">
          <section v-for="(item, index) in ['connect', 'discover', 'configure', 'verify']" :key="item">
            <h3>{{ index + 1 }}. {{ t(`agentIntegration.client.${item}`) }}</h3>
            <p class="muted">{{ t(`agentIntegration.client.${item}Help`) }}</p>
            <a-button v-if="item === 'discover' && pageAllowed('/agents')" @click="router.push({ path: '/agents', query: { origin: 'client_discovery' } })">{{ t('agentIntegration.client.view') }}</a-button>
            <a-button v-else-if="pageAllowed('/clients')" @click="router.push('/clients')">{{ t('agentIntegration.client.open') }}</a-button>
          </section>
        </div>
        <a-button type="link" @click="router.push('/docs/aidr-client')">{{ t('agentIntegration.client.docs') }}</a-button>
      </template>

      <template v-else>
        <a-card v-if="scenario === 'model' || scenario === 'mcp'" size="small" class="guide-panel" :title="t('agentIntegration.gateway.identity')">
          <a-radio-group v-model:value="caller" class="caller-choices" @change="changeCaller">
            <a-radio value="agent">{{ t('agentIntegration.gateway.agent') }}</a-radio>
            <a-radio value="ordinary">{{ t('agentIntegration.gateway.ordinary') }}</a-radio>
          </a-radio-group>
          <p class="muted">{{ caller === 'agent' ? t('agentIntegration.gateway.agentHelp') : t(`agentIntegration.gateway.${scenario}Help`) }}</p>
        </a-card>

        <template v-if="caller === 'agent'">
          <a-card size="small" class="guide-panel" :title="t('agentIntegration.selectIdentity')">
            <p class="muted">{{ t('agentIntegration.identityHelp') }}</p>
            <div class="identity-picker">
              <a-select v-if="hasAccess('agents:view')" :value="agentId || undefined" :loading="loading" show-search option-filter-prop="label" :placeholder="t('agentIntegration.selectAgent')" @change="selectAgent">
                <a-select-option v-for="item in agents" :key="item.agent_id" :value="item.agent_id" :label="`${item.name} ${item.agent_id}`">{{ item.name }} · {{ item.agent_id }}</a-select-option>
              </a-select>
              <a-button v-if="hasAccess('agents:create') && pageAllowed('/agents')" @click="router.push({ path: '/agents', query: { create: '1', scenario, capabilities: capabilities.join(',') } })">{{ t('agentIntegration.register') }}</a-button>
              <a-button v-if="hasAccess('agents:view')" :loading="loading" :disabled="loading" @click="loadAgents">{{ t('agentIntegration.refresh') }}</a-button>
            </div>
            <a-alert v-if="loadError" class="inline-note" type="error" :message="t('agentIntegration.loadFailed')" />
            <a-alert v-else-if="agentId && !agent && !loading" class="inline-note" type="warning" :message="t('agentIntegration.missingAgent')" />
            <p v-if="!hasAccess('agents:view')" class="muted">{{ t('agentIntegration.noPermission') }}</p>
          </a-card>

          <template v-if="agent">
            <a-card size="small" class="guide-panel">
              <h3>{{ t('agentIntegration.registered') }}</h3>
              <div class="agent-meta"><strong>{{ agent.name }}</strong><code>{{ agent.agent_id }}</code><span>{{ t(isExternal ? 'externalModel.external' : 'externalModel.internal') }}</span><span>{{ t('agentIntegration.model') }}: {{ agent.default_model || t('agentIntegration.unset') }}</span><span>{{ t('agentIntegration.skillCount', { count: agent.skill_names?.length || 0 }) }}</span><span>{{ t('agentMcp.count', { count: agent.allowed_mcp_gateways?.length || 0 }) }}</span></div>
              <a-alert v-if="agent.status !== 'active'" class="inline-note" type="warning" :message="t('agentIntegration.inactive')" />
              <div v-if="agent.origin_type === 'client_discovery'" class="inline-note"><p class="muted">{{ t('agentIntegration.sources.client_discovery') }}</p><a-button v-if="pageAllowed('/clients')" @click="router.push('/clients')">{{ t('agentIntegration.client.open') }}</a-button></div>
              <template v-if="scenario !== 'verifier'">
              <a-divider />
              <h3>{{ t('agentIntegration.capabilities') }}</h3>
              <a-checkbox-group v-model:value="capabilities" class="capabilities" @change="changeCapabilities">
                <a-checkbox v-for="key in capabilityKeys" :key="key" :value="key">{{ t(`agentIntegration.caps.${key}`) }}</a-checkbox>
              </a-checkbox-group>
              <p class="muted help-note">{{ t('agentIntegration.capabilityHelp') }}</p>
              </template>
            </a-card>
            <AgentSkillVerifierGuide v-if="scenario === 'verifier'" :key="agent.agent_id" :agent="agent" @create-credential="openCredential('agent_runtime')" @view-credentials="viewCredentials" />
            <a-card v-else class="guide-panel">
              <div class="guide-layout">
                <nav class="guide-steps" :aria-label="t('agentIntegration.guide')">
                  <button v-for="(key, index) in stepKeys" :key="key" type="button" :class="{ selected: step === index }" :aria-current="step === index ? 'step' : undefined" @click="setStep(index)"><span class="step-number">{{ index + 1 }}</span><span>{{ key === 'mcp' ? t('agentMcp.connect') : t(`agentIntegration.steps.${key}`) }}</span></button>
                </nav>
                <section class="step-content">
                  <template v-if="stepKey === 'credential'">
                    <p class="eyebrow">{{ t('agentIntegration.wherePlatform') }}</p>
                    <h3>{{ t('agentIntegration.steps.credential') }}</h3>
                    <p>{{ t('agentIntegration.credentialHint') }}</p>
                    <a-tag>{{ t(agent.runtime_token_id ? 'agentIntegration.linkedCredential' : 'agentIntegration.noCredential') }}</a-tag>
                    <p class="muted">{{ t('agentIntegration.credentialEvidence') }}</p>
                    <h4>{{ t('agentIntegration.scopes') }}</h4>
                    <pre v-if="suggestedScopes.length">{{ suggestedScopes.join('\n') }}</pre>
                    <a-alert v-else type="info" :message="t('agentIntegration.chooseCapability')" />
                    <a-alert v-if="mcpGrantMissing" class="inline-note" type="warning" :message="t('agentMcp.grantFirst')" />
                    <a-button v-if="mcpGrantMissing && agent.origin_type === 'platform' && hasAccess('agents:update') && pageAllowed('/agents')" @click="router.push({ path: '/agents', query: { edit: agent.agent_id } })">{{ t('agentMcp.editAgent') }}</a-button>
                    <a-space wrap class="guide-actions">
                      <a-button v-if="hasAccess('credentials:create') && pageAllowed('/credentials')" type="primary" :disabled="!capabilities.length || mcpGrantMissing" @click="openCredential('agent_runtime')">{{ t('agentIntegration.createCredential') }}</a-button>
                      <a-button v-if="pageAllowed('/credentials')" @click="viewCredentials">{{ t('agentIntegration.viewCredentials') }}</a-button>
                      <a-button @click="setStep(step + 1)">{{ t('agentMcp.next') }}</a-button>
                    </a-space>
                  </template>
                  <template v-else-if="stepKey === 'model'">
                    <p class="eyebrow">{{ t('agentIntegration.whereRuntime') }}</p>
                    <h3>{{ t('agentIntegration.steps.model') }}</h3>
                    <template v-if="capabilities.includes('model') && agent.default_model">
                      <p>{{ t(isExternal ? 'agentIntegration.modelExternal' : 'agentIntegration.modelInternal') }}</p>
                      <label v-if="!isExternal" class="protocol-picker">{{ t('agentIntegration.protocol') }}<a-select v-model:value="protocol" :options="protocols" /></label>
                      <pre>{{ modelConfig }}</pre>
                      <a-button @click="copyConfig(modelConfig)">{{ t('agentIntegration.copy') }}</a-button>
                      <p class="muted help-note">{{ t('agentIntegration.templateHelp') }}</p>
                    </template>
                    <p v-else class="muted">{{ t(capabilities.includes('model') ? 'agentIntegration.modelEmpty' : 'agentIntegration.modelUnselected') }}</p>
                    <a-space wrap class="guide-actions"><a-button v-if="!agent.default_model && agent.origin_type !== 'client_discovery' && hasAccess('agents:update') && pageAllowed('/agents')" @click="router.push({ path: '/agents', query: { edit: agent.agent_id } })">{{ t('agentIntegration.editAgent') }}</a-button><a-button type="primary" @click="setStep(step + 1)">{{ t('agentMcp.next') }}</a-button></a-space>
                  </template>
                  <template v-else-if="stepKey === 'skill'">
                    <p class="eyebrow">{{ t('agentIntegration.whereLoader') }}</p>
                    <h3>{{ t('agentIntegration.steps.skill') }}</h3>
                    <a-button type="link" @click="router.push({ path: '/runtime', query: { scenario: 'verifier', agent_id: agentId } })">{{ t('skillVerifier.open') }}</a-button>
                    <template v-if="capabilities.includes('skill') && agent.skill_names?.length">
                      <ol><li v-for="key in ['install', 'digest', 'authorize', 'load']" :key="key">{{ t(`agentIntegration.skillSteps.${key}`) }}</li></ol>
                      <pre>{{ skillConfig }}</pre>
                      <p class="muted">{{ t('agentIntegration.skillEvidence') }}</p>
                    </template>
                    <p v-else class="muted">{{ t(capabilities.includes('skill') ? 'agentIntegration.skillEmpty' : 'agentIntegration.skillUnselected') }}</p>
                    <a-space wrap><a-button v-if="capabilities.includes('skill') && !agent.skill_names?.length && agent.origin_type !== 'client_discovery' && hasAccess('agents:update') && pageAllowed('/agents')" @click="router.push({ path: '/agents', query: { edit: agent.agent_id } })">{{ t('agentIntegration.editAgent') }}</a-button><a-button type="primary" @click="setStep(step + 1)">{{ t('agentMcp.next') }}</a-button><a-button @click="router.push('/docs/runtime-integration')">{{ t('agentIntegration.docs') }}</a-button></a-space>
                  </template>
                  <template v-else-if="stepKey === 'mcp'">
                    <p class="eyebrow">{{ t('agentIntegration.whereRuntime') }}</p>
                    <h3>{{ t('agentMcp.connect') }}</h3>
                    <p>{{ t('agentMcp.runtimeHelp') }}</p>
                    <AgentMcpGateways :model-value="agent.allowed_mcp_gateways || []" :editable="false" />
                    <a-alert v-if="mcpGrantMissing" type="warning" :message="t('agentMcp.grantFirst')" />
                    <template v-for="slug in agent.allowed_mcp_gateways || []" :key="slug">
                      <h4>{{ slug }}</h4><pre>{{ mcpConfig(slug) }}</pre>
                      <a-button @click="copyConfig(mcpConfig(slug))">{{ t('agentIntegration.copy') }}</a-button>
                    </template>
                    <p class="muted">{{ t('agentMcp.configHelp') }}</p>
                    <p>{{ t('agentMcp.verifyHelp') }}</p>
                    <a-button type="primary" @click="setStep(step + 1)">{{ t('agentIntegration.nextVerify') }}</a-button>
                  </template>
                  <template v-else>
                    <p class="eyebrow">{{ t('agentIntegration.whereVerify') }}</p>
                    <h3>{{ t('agentIntegration.steps.verify') }}</h3>
                    <p>{{ t('agentIntegration.verifyHelp') }}</p>
                    <a-button v-if="capabilities.includes('mcp') && pageAllowed('/agents')" @click="router.push({ path: '/agents', query: { detail: agent.agent_id, detail_tab: 'mcp' } })">{{ t('agentMcp.viewDetails') }}</a-button>
                    <div v-for="item in verificationLinks" :key="item.key" class="verification-row"><p>{{ t(item.description) }}</p><a-button v-if="item.path && pageAllowed(item.path)" @click="openRecords(item)">{{ t(item.label) }}</a-button></div>
                  </template>
                </section>
              </div>
            </a-card>
            <a-collapse v-if="scenario !== 'verifier' && capabilities.includes('trace')" class="guide-panel">
              <a-collapse-panel v-if="capabilities.includes('trace')" key="trace" :header="t('agentIntegration.traceExtra')"><p>{{ t('agentIntegration.traceExtraHelp') }}</p><a-button @click="router.push('/docs/runtime-trace-guide')">{{ t('agentIntegration.docs') }}</a-button></a-collapse-panel>
            </a-collapse>
          </template>
        </template>

        <a-card v-else class="guide-panel" :title="t('agentIntegration.gateway.connection')">
          <a-button v-if="hasAccess('credentials:create') && pageAllowed('/credentials')" type="primary" @click="openCredential(scenario === 'model' ? 'model_gateway' : 'mcp_gateway')">{{ t('agentIntegration.gateway.create') }}</a-button>
          <p class="muted inline-note">{{ t(`agentIntegration.gateway.${scenario}Boundary`) }}</p>
          <template v-if="scenario === 'model'">
            <label class="protocol-picker">{{ t('agentIntegration.protocol') }}<a-select v-model:value="protocol" :options="protocols" /></label>
            <pre>{{ ordinaryModelConfig }}</pre>
            <a-button @click="copyConfig(ordinaryModelConfig)">{{ t('agentIntegration.copy') }}</a-button>
            <p class="muted help-note">{{ t('agentIntegration.templateHelp') }}</p>
          </template>
          <a-button v-else-if="pageAllowed('/mcp-governance/gateways')" @click="router.push('/mcp-governance/gateways')">{{ t('agentIntegration.gateway.openMcp') }}</a-button>
          <a-divider />
          <a-button v-if="pageAllowed(scenario === 'model' ? '/pipeline-trace' : '/mcp-governance/audit')" @click="router.push(scenario === 'model' ? '/pipeline-trace' : '/mcp-governance/audit')">{{ t(scenario === 'model' ? 'agentIntegration.modelRecords' : 'agentIntegration.mcpRecords') }}</a-button>
        </a-card>
      </template>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeftOutlined, CodeOutlined, DesktopOutlined, ApiOutlined, CloudOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { listAgents } from '../api'
import AgentMcpGateways from './AgentMcpGateways.vue'
import AgentSkillVerifierGuide from './AgentSkillVerifierGuide.vue'
import { can as hasAccess, pageAllowed } from '../access'
import { copyText, promptManualCopy } from '../utils/clipboard'
import { integrationCapabilities, integrationScopes, parseIntegrationCapabilities, runtimeApiOrigin } from '../utils/agentIntegration'

const props = defineProps({ traceEnabled: Boolean })
const { t } = useI18n()
const route = useRoute(), router = useRouter()
const scenarios = [{ id: 'custom', icon: CodeOutlined }, { id: 'client', icon: DesktopOutlined }, { id: 'verifier', icon: CodeOutlined }, { id: 'model', icon: CloudOutlined }, { id: 'mcp', icon: ApiOutlined }]
const scenario = computed(() => scenarios.some(item => item.id === route.query.scenario) ? route.query.scenario : '')
const agentId = computed(() => typeof route.query.agent_id === 'string' ? route.query.agent_id : '')
const agents = ref([]), loading = ref(false), loadError = ref(false)
const agent = computed(() => agents.value.find(item => item.agent_id === agentId.value))
const isExternal = computed(() => agent.value?.default_model_source === 'external_gateway')
const caller = ref('agent'), step = ref(0), capabilities = ref([]), protocol = ref('chat')
const capabilityKeys = Object.keys(integrationCapabilities)
const stepKeys = computed(() => ['credential', ...['model', 'skill', 'mcp'].filter(key => capabilities.value.includes(key)), 'verify'])
const stepKey = computed(() => stepKeys.value[step.value])
const mcpGrantMissing = computed(() => capabilities.value.includes('mcp') && !agent.value?.allowed_mcp_gateways?.length)
const mcpConfig = slug => `URL: ${runtimeApiOrigin()}/mcp/${encodeURIComponent(slug)}\nTransport: Streamable HTTP\nAuthorization: Bearer <AGENT_RUNTIME_TOKEN>`
const protocols = [{ value: 'chat', label: 'Chat Completions' }, { value: 'responses', label: 'Responses' }, { value: 'messages', label: 'Anthropic Messages' }]
const suggestedScopes = computed(() => integrationScopes(capabilities.value))
const endpoint = computed(() => ({ chat: '/v1/chat/completions', responses: '/v1/responses', messages: '/v1/messages' }[protocol.value]))
const modelConfig = computed(() => isExternal.value
  ? `GET ${runtimeApiOrigin()}/api/v1/runtime/external-model/credential\nAuthorization: Bearer <AGENT_RUNTIME_TOKEN>`
  : `Base URL: ${runtimeApiOrigin()}${protocol.value === 'messages' ? '' : '/v1'}\nAPI Key: <AGENT_RUNTIME_TOKEN>\nModel: ${agent.value?.default_model || '<MODEL_NAME>'}\nRequest URL: ${runtimeApiOrigin()}${endpoint.value}`)
const ordinaryModelConfig = computed(() => `Base URL: ${runtimeApiOrigin()}${protocol.value === 'messages' ? '' : '/v1'}\nAPI Key: <MODEL_CREDENTIAL>\nModel: <ALLOWED_MODEL>\nRequest URL: ${runtimeApiOrigin()}${endpoint.value}`)
const skillConfig = computed(() => `POST /api/v1/access/runtime/verify-skill-signature\nContent-Type: application/json\n{\n  "skill_name": "<skill_name>",\n  "local_signature": "<LOCAL_CONTENT_DIGEST>"\n}\n\nGET /api/v1/access/runtime/can-load/<skill_name>\nGET /api/v1/access/runtime/check-tool?skill_name=<skill_name>&tool_name=<tool_name>\n\nAuthorization: Bearer <AGENT_RUNTIME_TOKEN>\nX-Agent-ID: ${agentId.value}`)
const verificationLinks = computed(() => [
  { key: 'model', description: isExternal.value ? 'agentIntegration.verifyExternalModel' : 'agentIntegration.verifyModel', label: 'agentIntegration.modelRecords', path: isExternal.value ? null : '/pipeline-trace' },
  { key: 'skill', description: 'agentIntegration.verifySkill', label: 'agentIntegration.skillRecords', path: '/runtime' },
  { key: 'mcp', description: 'agentIntegration.verifyMcp', label: 'agentIntegration.mcpRecords', path: '/mcp-governance/audit' },
  { key: 'trace', description: 'agentIntegration.verifyTrace', label: 'agentIntegration.traceRecords', path: props.traceEnabled ? '/runtime-traces' : null },
].filter(item => capabilities.value.includes(item.key)))

const loadAgents = async () => {
  if (!hasAccess('agents:view') || loading.value) return
  loading.value = true
  loadError.value = false
  try { agents.value = await listAgents() } catch { agents.value = []; loadError.value = true } finally { loading.value = false }
}
const syncContext = () => {
  caller.value = route.query.caller === 'ordinary' && ['model', 'mcp'].includes(scenario.value) ? 'ordinary' : 'agent'
  if (scenario.value === 'verifier') { capabilities.value = ['skill']; step.value = 0; return }
  const index = Number(route.query.step || 0)
  capabilities.value = typeof route.query.capabilities === 'string' ? parseIntegrationCapabilities(route.query.capabilities) : [
    ...(agent.value?.skill_names?.length ? ['skill'] : []),
    ...(agent.value?.default_model || scenario.value === 'model' ? ['model'] : []),
    ...(agent.value?.allowed_mcp_gateways?.length || scenario.value === 'mcp' ? ['mcp'] : []),
  ]
  step.value = Number.isInteger(index) && index >= 0 && index < stepKeys.value.length ? index : 0
}
watch(() => [route.query, agent.value], syncContext, { immediate: true })
const chooseScenario = value => router.push({ path: '/runtime', query: value ? { scenario: value } : {} })
const selectAgent = id => router.push({ path: '/runtime', query: { scenario: scenario.value, agent_id: id, step: '0' } })
const changeCaller = () => router.replace({ query: { ...route.query, caller: caller.value } })
const changeCapabilities = () => router.replace({ query: { ...route.query, capabilities: capabilities.value.join(','), step: '0' } })
const setStep = index => { step.value = index; router.replace({ query: { ...route.query, step: String(index) } }) }
const credentialQuery = () => ({ from: 'runtime', scenario: scenario.value, ...(agentId.value && caller.value === 'agent' ? { agent_id: agentId.value, capabilities: capabilities.value.join(',') } : { caller: 'ordinary' }) })
const openCredential = type => router.push({ path: '/credentials', query: { ...credentialQuery(), create: type } })
const viewCredentials = () => router.push({ path: '/credentials', query: credentialQuery() })
const openRecords = item => router.push(item.key === 'skill' ? { path: '/runtime', query: { ...route.query, tab: 'records', q: agentId.value } } : item.path)
const copyConfig = async value => {
  try { await copyText(value); message.success(t('agentIntegration.copied')) } catch { message.warning(t('clipboard.copyFailed')); promptManualCopy(value, t('clipboard.manualCopyPrompt')) }
}
onMounted(loadAgents)
</script>

<style scoped>
.integration-guide { min-width: 0; }
.scenario-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.scenario-card { display: flex; flex-direction: column; gap: 9px; text-align: left; padding: 22px; border: 1px solid #e4e8ef; border-radius: 8px; background: #fff; color: #202630; cursor: pointer; font: inherit; }
.scenario-card:hover { border-color: #1d4ed8; background: #f8faff; }
.scenario-card:focus-visible, .guide-steps button:focus-visible { outline: 2px solid #1d4ed8; outline-offset: 3px; }
.scenario-card strong { font-size: 16px; }.scenario-card span, .muted { color: #626b78; }
.scenario-card small { color: #1d4ed8; margin-top: auto; font-size: 13px; }.scenario-icon { align-self: flex-start; font-size: 20px; color: #1d4ed8; margin-bottom: 5px; }
.back-link { padding-left: 0; margin-bottom: 12px; }.guide-panel { margin-bottom: 18px; }
.identity-picker, .agent-meta, .caller-choices { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.identity-picker > .ant-select { flex: 1 1 260px; min-width: 0; }.agent-meta { color: #626b78; overflow-wrap: anywhere; }
.capabilities { display: flex; flex-wrap: wrap; gap: 12px; }.capabilities :deep(.ant-checkbox-wrapper) { margin: 0; }
.guide-layout { display: grid; grid-template-columns: 190px minmax(0, 1fr); gap: 24px; }.guide-steps { display: flex; flex-direction: column; gap: 8px; }
.guide-steps button { display: flex; align-items: flex-start; gap: 10px; text-align: left; padding: 12px; border: 0; border-radius: 6px; background: transparent; color: #626b78; cursor: pointer; font: inherit; }
.guide-steps button.selected { background: #eff5ff; color: #1d4ed8; }.step-number { display: grid; place-items: center; border: 1px solid #dce2ec; border-radius: 50%; flex: 0 0 26px; height: 26px; background: #fff; }
.step-content { min-width: 0; }.eyebrow { color: #1d4ed8; font-size: 12px; }.guide-actions { margin-top: 16px; }.help-note { margin: 10px 0 0; font-size: 13px; }.inline-note { margin-top: 14px; }
pre { padding: 16px; white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f6f8; border: 1px solid #e4e8ef; border-radius: 6px; font-size: 12px; }
.protocol-picker { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 14px 0; }.protocol-picker .ant-select { min-width: 0; width: 220px; max-width: 100%; }
.verification-row, .client-steps section { padding: 16px 0; border-bottom: 1px solid #edf0f5; }.verification-row:last-child, .client-steps section:last-child { border-bottom: 0; }
.client-steps { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }.verification-row p { color: #626b78; }
.integration-guide :deep(.ant-btn) { height: auto; min-height: 32px; white-space: normal; overflow-wrap: anywhere; }
@media (max-width: 900px) { .guide-layout { grid-template-columns: 1fr; }.guide-steps { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .scenario-grid, .client-steps { grid-template-columns: 1fr; }.scenario-card { padding: 18px; }.guide-panel :deep(.ant-card-body) { padding: 16px; }.identity-picker > .ant-select { flex-basis: 100%; }.guide-steps button { padding: 9px 5px; font-size: 13px; } }
</style>
