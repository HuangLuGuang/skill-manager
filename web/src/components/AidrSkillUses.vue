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
      <header><strong>{{ item.skill.name || item.certification?.name || t('aidr.skillUse.unknownName') }}</strong><time>{{ time(item.first_at) }}</time></header>
      <div class="skill-badges"><a-tag color="blue">{{ t('aidr.skillUse.' + item.skill.behavior) }}</a-tag><a-tag>{{ phase(item) }}</a-tag><a-tag :color="tone(item.certification?.status)">{{ t('aidr.skillUse.' + (item.certification?.status || 'pending')) }}</a-tag></div>
      <p v-if="item.certification?.reason && item.certification.reason !== item.certification.status">{{ t('aidr.skillUse.' + item.certification.reason) }}</p>
      <details><summary>{{ t('aidr.skillUse.details') }}</summary>
        <dl><dt>{{ t('aidr.skillUse.entry') }}</dt><dd>{{ item.entry }} · {{ item.agent_version || '—' }}</dd><dt>{{ t('aidr.skillUse.version') }}</dt><dd>{{ item.certification?.version_no ?? '—' }}</dd><template v-for="key in ['registered','approved','revoked','content_matches','authorized']" :key="key"><dt>{{ t('aidr.skillUse.check.' + key) }}</dt><dd>{{ t('aidr.skillUse.' + (item.certification?.[key] === true ? 'yes' : item.certification?.[key] === false ? 'no' : 'unknown')) }}</dd></template></dl>
        <dl><dt>{{ t('aidr.skillUse.path') }}</dt><dd>{{ item.skill.path || '—' }}</dd><dt>{{ t('aidr.skillUse.digest') }}</dt><dd><code>{{ item.skill.content_digest || '—' }}</code></dd><dt>{{ t('aidr.skillUse.observedAt') }}</dt><dd>{{ time(item.skill.content_observed_at) }}</dd><dt>{{ t('aidr.skillUse.checkedAt') }}</dt><dd>{{ time(item.certification?.checked_at) }}</dd><dt>{{ t('aidr.skillUse.identity') }}</dt><dd>{{ item.certification?.managed_agent_id || '—' }} / {{ item.certification?.local_agent_id || '—' }}</dd><dt>{{ t('aidr.skillUse.references') }}</dt><dd><span v-for="ref in item.evidence" :key="ref.source + ref.id" class="reference">{{ ref.source === 'hook' ? 'Hook' : 'Agent log' }} #{{ ref.id }} · {{ ref.kind }}</span></dd></dl>
        <p class="muted">{{ t('aidr.skillUse.observation') }}</p>
        <details><summary>{{ t('aidr.skillUse.diagnostics') }}</summary><pre>{{ JSON.stringify(item, null, 2) }}</pre></details>
      </details>
    </article>
    <a-button v-if="hasMore" :loading="loading" :disabled="loading" @click="load(true)">{{ t('aidr.skillUse.more') }}</a-button>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getClientAidrSkillUses } from '../api'
const props = defineProps({ clientId: String, agent: String, sessionId: String })
const { t, locale } = useI18n()
const behavior = ref(''), certification = ref(''), items = ref([]), loading = ref(false), error = ref(false), hasMore = ref(false), cursor = ref('')
let request = 0
const options = (keys, all) => [{value:'', label:t('aidr.skillUse.'+all)}, ...keys.map(value => ({value,label:t('aidr.skillUse.'+value)}))]
const behaviorOptions = computed(() => options(['invocation','file_access'], 'allBehaviors'))
const checkOptions = computed(() => options(['pending','verified','verified_content','unregistered','unapproved','content_changed','revoked','unauthorized'], 'allChecks'))
const tone = status => ['verified','verified_content'].includes(status) ? 'green' : status === 'pending' ? 'default' : 'orange'
const phase = item => t('aidr.skillUse.' + (item.stage === 'host_confirmed' ? item.skill.behavior === 'invocation' ? 'loaded' : 'read' : item.stage))
const time = value => value ? new Date(value).toLocaleString(locale.value) : '—'
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
summary { cursor:pointer; color:#315fbd; } dl { display:grid; grid-template-columns:150px minmax(0,1fr); gap:8px; margin-top:12px; } dd { margin:0; } .reference { display:block; } pre { max-height:260px; overflow:auto; white-space:pre-wrap; }
@media(max-width:700px) { dl { grid-template-columns:1fr; } .skill-filters .ant-select { flex:1; min-width:150px; } }
</style>
