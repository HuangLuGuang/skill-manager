<template>
  <section class="skill-uses" :aria-busy="loading">
    <div class="skill-filters">
      <a-select v-model:value="behavior" :aria-label="t('aidr.skillUse.allBehaviors')" :options="behaviorOptions" />
      <a-select v-model:value="certification" :aria-label="t('aidr.skillUse.allChecks')" :options="checkOptions" />
      <a-button :loading="loading" :disabled="loading" @click="load()">{{ t('aidr.skillUse.refresh') }}</a-button>
    </div>
    <p class="muted">{{ t('aidr.skillUse.help') }}</p>
    <a-alert v-if="error" type="error" show-icon :message="t('aidr.skillUse.error')" />
    <a-spin v-if="loading && !items.length" />
    <a-empty v-else-if="!items.length && !error" :description="t('aidr.skillUse.empty')" />
    <article v-for="item in items" :key="item.id" class="skill-card">
      <header><strong>{{ item.skill.name || item.certification?.name || (item.skill.path ? t('aidr.skillUse.fileRecord') : t('aidr.skillUse.unknownName')) }}</strong><time>{{ time(item.first_at) }}</time></header>
      <div class="skill-origin">
        <span v-if="item.entry || item.agent"><span class="meta-label">{{ t('aidr.skillUse.entry') }}</span>{{ entryName(item) }}<template v-if="item.agent_version"> · {{ item.agent_version }}</template></span>
        <span v-for="source in sources(item)" :key="source.source">{{ t('aidr.skillUse.source.' + source.source, { count: source.count }) }}</span>
        <span v-if="item.tool"><span class="meta-label">{{ t('aidr.skillUse.tool') }}</span>{{ item.tool }}</span>
      </div>
      <p v-if="item.skill.path" class="skill-path"><span class="meta-label">{{ t('aidr.skillUse.path') }}</span>{{ item.skill.path }}</p>
      <div class="skill-badges"><a-tag color="blue">{{ t('aidr.skillUse.' + item.skill.behavior) }}</a-tag><a-tag>{{ phase(item) }}</a-tag><a-tag :color="tone(item.certification?.status)">{{ t('aidr.skillUse.' + (item.certification?.status || 'pending')) }}</a-tag></div>
      <p v-if="item.certification?.reason && item.certification.reason !== item.certification.status">{{ t('aidr.skillUse.' + item.certification.reason) }}</p>
      <dl v-if="item.certification?.version_no != null || item.certification?.managed_agent_id || item.certification?.local_agent_id || item.skill.content_digest" class="skill-facts">
        <template v-if="item.certification?.version_no != null"><dt>{{ t('aidr.skillUse.version') }}</dt><dd>{{ item.certification.version_no }}</dd></template>
        <template v-if="item.certification?.managed_agent_id"><dt>{{ t('aidr.skillUse.managedAgent') }}</dt><dd>{{ item.certification.managed_agent_id }}</dd></template>
        <template v-if="item.certification?.local_agent_id"><dt>{{ t('aidr.skillUse.localInstance') }}</dt><dd>{{ item.certification.local_agent_id }}</dd></template>
        <template v-if="item.skill.content_digest"><dt>{{ t('aidr.skillUse.digest') }}<a-tooltip :title="t('aidr.skillUse.observation')"><button class="digest-info" :aria-label="t('aidr.skillUse.observation')"><InfoCircleOutlined /></button></a-tooltip></dt><dd><code>{{ item.skill.content_digest }}</code><span v-if="item.skill.content_observed_at" class="observed-at">{{ t('aidr.skillUse.observedAt') }} · {{ time(item.skill.content_observed_at) }}</span></dd></template>
      </dl>
      <p v-if="['computed', 'reused'].includes(item.skill.content_status)" class="muted">{{ t('aidr.skillUse.contentState.' + item.skill.content_status) }}</p>
      <p v-if="item.certification?.checked_at" class="muted">{{ t('aidr.skillUse.checkedAt') }} · {{ time(item.certification.checked_at) }}</p>
    </article>
    <a-button v-if="hasMore" :loading="loading" :disabled="loading" @click="load(true)">{{ t('aidr.skillUse.more') }}</a-button>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { InfoCircleOutlined } from '@ant-design/icons-vue'
import products from '../aidr-products.json'
import { getClientAidrSkillUses } from '../api'
const props = defineProps({ clientId: String, agent: String, sessionId: String })
const { t, locale } = useI18n()
const behavior = ref(''), certification = ref(''), items = ref([]), loading = ref(false), error = ref(false), hasMore = ref(false), cursor = ref('')
let request = 0
const options = (keys, all) => [{value:'', label:t('aidr.skillUse.'+all)}, ...keys.map(value => ({value,label:t('aidr.skillUse.'+value)}))]
const behaviorOptions = computed(() => options(['invocation','file_access'], 'allBehaviors'))
const checkOptions = computed(() => options(['pending','verified','verified_content','unregistered','unapproved','content_changed','revoked','unauthorized'], 'allChecks'))
const tone = status => ['verified','verified_content'].includes(status) ? 'green' : status === 'pending' ? 'default' : 'orange'
const phase = item => t('aidr.skillUse.' + (item.stage === 'host_confirmed' ? item.skill.behavior === 'invocation' ? 'loaded' : 'read' : item.stage === 'unknown' ? 'outcomeUnconfirmed' : item.stage))
const time = value => value ? new Date(value).toLocaleString(locale.value) : '—'
const entryName = item => {
  const id = item.entry || item.agent
  const product = products.find(entry => entry.id === id)
  if (!product) return id
  return product.id.startsWith('qoder-') ? `Qoder · ${t('agentRuntimeGovernance.catalog.entries.' + product.entry)}` : product.name
}
const sources = item => ['log', 'hook'].map(source => ({ source, count: (item.evidence || []).filter(ref => ref.source === source).length })).filter(source => source.count)
async function load(append = false) {
  if (append && loading.value) return
  const id = ++request
  loading.value = true; error.value = false
  if (!append) { items.value = []; cursor.value = ''; hasMore.value = false }
  try {
    const result = await getClientAidrSkillUses(props.clientId, { agent:props.agent, session_id:props.sessionId, behavior:behavior.value, certification:certification.value, after:append ? cursor.value : 0 })
    if (id !== request) return
    items.value = append ? [...items.value, ...result.items] : result.items
    cursor.value = result.next_cursor; hasMore.value = result.has_more
  } catch { if (id === request) error.value = true }
  finally { if (id === request) loading.value = false }
}
watch(() => [props.clientId, props.agent, props.sessionId, behavior.value, certification.value], () => load(), { immediate:true })
onBeforeUnmount(() => request++)
</script>
<style scoped>
.skill-uses { overflow:auto; min-height:0; padding:12px 14px; overscroll-behavior:contain; }
.skill-filters { display:flex; flex-wrap:wrap; gap:8px; }.skill-filters .ant-select { min-width:190px; max-width:100%; }
.skill-card { border:1px solid #e2e7ed; border-radius:10px; padding:14px; margin:12px 0; overflow-wrap:anywhere; }
header { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; } time,.muted { color:#68798c; font-size:12px; } .skill-badges { display:flex; flex-wrap:wrap; gap:4px; margin:10px 0; }
dl { display:grid; grid-template-columns:150px minmax(0,1fr); gap:8px; margin:12px 0; } dd { margin:0; min-width:0; }
.skill-origin { display:flex; flex-wrap:wrap; gap:6px 18px; margin-top:8px; color:#68798c; font-size:12px; }
.meta-label { color:#68798c; margin-right:8px; }.skill-path { margin:12px 0; font-size:13px; }.skill-facts { font-size:12px; }.skill-facts dt { color:#68798c; }.observed-at { display:block; color:#68798c; margin-top:4px; }
.digest-info { border:0; padding:0 4px; background:none; color:#68798c; cursor:help; }.digest-info:focus-visible { outline:2px solid #315fbd; outline-offset:2px; }
@media(max-width:700px) { dl { grid-template-columns:1fr; } .skill-filters .ant-select { flex:1; min-width:150px; } }
</style>
