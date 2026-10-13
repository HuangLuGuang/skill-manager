<template>
  <section class="verifier-guide">
    <a-alert type="info" show-icon :message="t('skillVerifier.boundaryTitle')" :description="t('skillVerifier.boundary')" />
    <a-card class="panel" :title="t('skillVerifier.prepareTitle')">
      <p>{{ t('skillVerifier.prepare') }}</p>
      <a-alert v-if="!agent.skill_names?.length" type="warning" :message="t('skillVerifier.noSkills')" />
      <a-space wrap>
        <a-button v-if="agent.origin_type === 'client_discovery' && pageAllowed('/clients')" @click="router.push('/clients')">{{ t('agentIntegration.client.open') }}</a-button>
        <a-button v-else-if="hasAccess('agents:update') && pageAllowed('/agents')" @click="router.push({ path: '/agents', query: { edit: agent.agent_id, scenario: 'verifier', capabilities: 'skill' } })">{{ t('agentIntegration.editAgent') }}</a-button>
      </a-space>
    </a-card>
    <a-card class="panel" :title="t('skillVerifier.credentialTitle')">
      <p>{{ t('skillVerifier.credential') }}</p>
      <a-space wrap><a-tag v-for="scope in verifierScopes" :key="scope">{{ scope }}</a-tag></a-space>
      <p class="muted">{{ t('agentIntegration.credentialEvidence') }}</p>
      <a-space wrap>
        <a-button v-if="hasAccess('credentials:create') && pageAllowed('/credentials')" type="primary" :disabled="agent.status !== 'active'" @click="$emit('create-credential')">{{ t('agentIntegration.createCredential') }}</a-button>
        <a-button v-if="pageAllowed('/credentials')" @click="$emit('view-credentials')">{{ t('agentIntegration.viewCredentials') }}</a-button>
      </a-space>
    </a-card>
    <a-card class="panel" :title="t('skillVerifier.installTitle')">
      <p>{{ t('skillVerifier.install') }}</p>
      <a-button v-if="hasAccess('credentials:view')" type="primary" :loading="downloading" :disabled="downloading" @click="download">{{ t('skillVerifier.download') }}</a-button>
      <p v-else class="muted">{{ t('skillVerifier.downloadPermission') }}</p>
      <label class="field"><span>{{ t('skillVerifier.host') }}</span><a-select v-model:value="host" :options="hostOptions" /></label>
      <label v-if="host === 'other'" class="field"><span>{{ t('skillVerifier.installDirectory') }}</span><a-input v-model:value="customDirectory" placeholder="/absolute/path/to/skills" /></label>
      <p class="muted">{{ t('skillVerifier.directoryHelp') }}</p>
      <pre>{{ installCommand }}</pre>
      <a-button @click="copy(installCommand)">{{ t('skillVerifier.copyCommand') }}</a-button>
    </a-card>
    <a-card class="panel" :title="t('skillVerifier.configureTitle')">
      <p>{{ t('skillVerifier.configure') }}</p>
      <pre>{{ environmentCommand }}</pre>
      <a-button @click="copy(environmentCommand)">{{ t('skillVerifier.copyCommand') }}</a-button>
      <a-alert class="note" type="warning" show-icon :message="t('skillVerifier.environmentTitle')" :description="t('skillVerifier.environment')" />
    </a-card>
    <a-card class="panel" :title="t('skillVerifier.verifyTitle')">
      <p>{{ t('skillVerifier.verify') }}</p>
      <label class="field"><span>{{ t('skillVerifier.skillPath') }}</span><a-input v-model:value="skillPath" placeholder="/absolute/path/to/third-party-skill" /></label>
      <p class="muted">{{ t('skillVerifier.pathHelp') }}</p>
      <pre>{{ verifyCommand }}</pre>
      <a-button @click="copy(verifyCommand)">{{ t('skillVerifier.copyCommand') }}</a-button>
      <ol><li>{{ t('skillVerifier.success') }}</li><li>{{ t('skillVerifier.audit') }}</li><li>{{ t('skillVerifier.invoke') }}</li></ol>
      <a-space wrap>
        <a-button v-if="hasAccess('skills:view')" @click="router.push({ path: '/runtime', query: { scenario: 'verifier', agent_id: agent.agent_id, tab: 'records', q: agent.agent_id } })">{{ t('agentIntegration.skillRecords') }}</a-button>
        <a-button @click="router.push('/docs/runtime-integration#skill-verifier')">{{ t('agentIntegration.docs') }}</a-button>
      </a-space>
      <a-collapse class="note">
        <a-collapse-panel key="troubleshoot" :header="t('skillVerifier.troubleshootTitle')"><ul><li v-for="key in ['auth', 'approval', 'digest', 'network']" :key="key">{{ t(`skillVerifier.failures.${key}`) }}</li></ul></a-collapse-panel>
        <a-collapse-panel key="submit" :header="t('skillVerifier.submitTitle')"><p>{{ t('skillVerifier.submit') }}</p><a-button v-if="pageAllowed('/scanner-access')" @click="router.push('/scanner-access')">{{ t('skillVerifier.scanner') }}</a-button></a-collapse-panel>
      </a-collapse>
    </a-card>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { downloadSkillVerifier } from '../api'
import { can as hasAccess, pageAllowed } from '../access'
import { copyText, promptManualCopy } from '../utils/clipboard'
import { runtimeApiOrigin, verifierScopes } from '../utils/agentIntegration'

const props = defineProps({ agent: { type: Object, required: true } })
defineEmits(['create-credential', 'view-credentials'])
const { t, locale } = useI18n(), router = useRouter()
const host = ref('codex'), customDirectory = ref(''), skillPath = ref(''), downloading = ref(false)
const quote = value => `'${String(value).replaceAll("'", "'\\''")}'`
const hostOptions = computed(() => [{ value: 'codex', label: 'Codex' }, { value: 'claude', label: 'Claude Code' }, { value: 'other', label: t('skillVerifier.otherHost') }])
const directory = computed(() => host.value === 'other' ? quote(customDirectory.value || '/absolute/path/to/skills') : `"$HOME/.${host.value === 'codex' ? 'codex' : 'claude'}/skills"`)
const script = computed(() => `${directory.value}/agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py`)
const installCommand = computed(() => `python3 --version\nmkdir -p ${directory.value}\nunzip agent-manager-skill-verifier.zip -d ${directory.value}`)
const environmentCommand = computed(() => `export AGENT_MANAGER_VERIFIER_BASE_URL=${quote(runtimeApiOrigin())}\nexport AGENT_MANAGER_AGENT_RUNTIME_TOKEN='<AGENT_RUNTIME_TOKEN>'\nexport AGENT_ID=${quote(props.agent.agent_id)}\nexport AGENT_MANAGER_VERIFIER_LANG=${quote(locale.value)}`)
const verifyCommand = computed(() => `python3 ${script.value} verify \\\n  --path ${quote(skillPath.value || '/absolute/path/to/third-party-skill')}`)
const copy = async value => {
  try { await copyText(value); message.success(t('skillVerifier.copied')) } catch { message.warning(t('clipboard.copyFailed')); promptManualCopy(value, t('clipboard.manualCopyPrompt')) }
}
const download = async () => {
  if (downloading.value) return
  downloading.value = true
  try {
    const blob = await downloadSkillVerifier()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'agent-manager-skill-verifier.zip'
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch { message.error(t('skillVerifier.downloadFailed')) } finally { downloading.value = false }
}
</script>

<style scoped>
.verifier-guide { min-width: 0; }
.panel, .note { margin-top: 16px; }
.muted { color: #626b78; }
.field { display: flex; flex-direction: column; gap: 8px; margin: 16px 0 8px; }
.field :deep(.ant-select) { max-width: 400px; }
pre { padding: 16px; white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f6f8; border: 1px solid #e4e8ef; border-radius: 6px; font-size: 12px; }
li { margin: 10px 0; overflow-wrap: anywhere; }
@media (max-width: 600px) { .panel :deep(.ant-card-body) { padding: 16px; }.panel :deep(.ant-card-head-title) { white-space: normal; padding: 12px 0; } }
</style>
