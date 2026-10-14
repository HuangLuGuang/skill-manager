<template>
  <section class="skill-uses" :class="{ 'has-detail': selectedId }" :aria-busy="loading">
    <div class="skill-list">
      <header><h3>{{ tr('title') }}</h3><a-button :loading="loading" :disabled="loading" @click="refresh">{{ ui('refreshPlatform') }}</a-button></header>
      <p class="muted">{{ ui('separateStates') }}</p>
      <div class="skill-filters">
        <a-input v-model:value="search" :placeholder="ui('search')" :aria-label="ui('search')" :maxlength="256" allow-clear @press-enter="searchNow" />
        <a-select v-model:value="behavior" :aria-label="tr('allBehaviors')" :options="behaviorOptions" />
        <a-select v-model:value="result" :aria-label="ui('allResults')" :options="resultOptions" />
        <a-select v-model:value="certification" :aria-label="tr('allChecks')" :options="checkOptions" />
        <a-select v-model:value="order" :aria-label="ui('order')" :options="orderOptions" />
        <a-input v-model:value="turnSearch" :placeholder="ui('turnSearch')" :aria-label="ui('turnSearch')" :maxlength="256" allow-clear @press-enter="searchNow" />
      </div>
      <p v-if="loading && items.length" class="muted" role="status">{{ ui('refreshing') }}</p>
      <a-alert v-if="error" type="error" show-icon :message="tr('error')"><template #action><a-button @click="load(failedAppend)">{{ ui('retry') }}</a-button></template></a-alert>
      <a-spin v-if="loading && !items.length" />
      <a-empty v-else-if="!items.length && !error" :description="hasMore ? ui('batchEmpty') : tr('empty')" />
      <div v-if="items.length" class="skill-table-scroll"><table class="skill-table">
        <thead><tr><th>Skill</th><th>{{ ui('behavior') }}</th><th>{{ ui('outcome') }}</th><th>{{ ui('certification') }}</th><th>{{ ui('time') }}</th></tr></thead>
        <tbody><tr v-for="item in items" :key="item.id" :class="{ selected:item.id === selectedId }" @click="selectedId = item.id">
          <td><button class="skill-name" :aria-pressed="item.id === selectedId" @click.stop="selectedId = item.id"><FileTextOutlined />{{ name(item) }}</button><small v-if="!item.skill.name && !item.certification?.name">{{ item.skill.path }}</small></td>
          <td>{{ ui(item.skill.behavior) }}</td><td><a-tag :color="outcomeTone(item.stage)">{{ phase(item) }}</a-tag></td>
          <td><a-tag :color="tone(item.certification?.status)">{{ tr(item.certification?.status || 'pending') }}</a-tag></td><td><time>{{ time(item.first_at) }}</time></td>
        </tr></tbody>
      </table></div>
      <footer><span class="muted">{{ ui('loadedCount', { count:items.length }) }}</span><a-button v-if="hasMore" :loading="loading" :disabled="loading" @click="load(true)">{{ items.length ? tr('more') : ui('continueSearch') }}</a-button></footer>
    </div>
    <AidrSkillUseDetail v-if="selectedId" :key="clientId + ':' + selectedId" ref="detailPane" class="skill-detail" :client-id="clientId" :usage-id="selectedId" @close="selectedId = ''" @collection="$emit('collection')" @updated="updateItem" />
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { FileTextOutlined } from '@ant-design/icons-vue'
import { getClientAidrSkillUses } from '../api'
import AidrSkillUseDetail from './AidrSkillUseDetail.vue'
import { useSkillAuditLabels } from '../utils/skillAudit'
const props = defineProps({ clientId:String, agent:String, sessionId:String })
defineEmits(['collection'])
const { t } = useI18n()
const { name, time, phase, tone, outcomeTone } = useSkillAuditLabels()
const tr = (key, args) => t('aidr.skillUse.' + key, args), ui = (key, args) => tr('review.' + key, args)
const behavior = ref(''), certification = ref(''), result = ref(''), order = ref('newest'), search = ref(''), keyword = ref(''), turnSearch = ref(''), turn = ref('')
const items = ref([]), loading = ref(false), error = ref(false), hasMore = ref(false), cursor = ref(''), selectedId = ref(''), detailPane = ref(null)
let request = 0, timer, failedAppend = false
const options = (keys, all) => [{ value:'', label:tr(all) }, ...keys.map(value => ({ value, label:tr(value) }))]
const behaviorOptions = computed(() => options(['invocation','file_access'], 'allBehaviors'))
const checkOptions = computed(() => options(['pending','verified','verified_content','unregistered','unapproved','content_changed','revoked','unauthorized'], 'allChecks'))
const resultOptions = computed(() => [{ value:'', label:ui('allResults') }, ...['attempted','host_confirmed','denied','failed','unknown'].map(value => ({ value, label:tr(value) }))])
const orderOptions = computed(() => ['newest','oldest'].map(value => ({ value, label:ui(value) })))
async function load(append = false) {
  if (append && loading.value) return
  const id = ++request; loading.value = true; error.value = false; failedAppend = append
  try {
    const data = await getClientAidrSkillUses(props.clientId, { agent:props.agent, session_id:props.sessionId, behavior:behavior.value, certification:certification.value, result:result.value, keyword:keyword.value, turn_id:turn.value, order:order.value, after:append ? cursor.value : 0 })
    if (id !== request) return
    items.value = append ? [...items.value, ...data.items.filter(item => !items.value.some(old => old.id === item.id))] : data.items
    hasMore.value = data.has_more; cursor.value = data.next_cursor
  } catch { if (id === request) error.value = true }
  finally { if (id === request) loading.value = false }
}
function updateItem(data) { items.value = items.value.map(item => item.id === data.id ? { ...item, stage:data.stage, certification:data.certification } : item).filter(item => (!certification.value || item.certification?.status === certification.value) && (!result.value || item.stage === result.value)) }
function searchNow() { clearTimeout(timer); keyword.value = search.value.trim(); turn.value = turnSearch.value.trim() }
function refresh() { const changed = keyword.value !== search.value.trim() || turn.value !== turnSearch.value.trim(); searchNow(); if (!changed) load(); detailPane.value?.refresh() }
watch([search, turnSearch], () => { clearTimeout(timer); timer = setTimeout(searchNow, 300) })
watch([behavior, certification, result, order, keyword, turn], () => { items.value = []; cursor.value = ''; hasMore.value = false; selectedId.value = ''; load() })
watch(() => [props.clientId, props.agent, props.sessionId], () => { clearTimeout(timer); selectedId.value = ''; items.value = []; cursor.value = ''; hasMore.value = false; load() }, { immediate:true })
onBeforeUnmount(() => { request++; clearTimeout(timer) })
defineExpose({ refresh })
</script>
<style scoped>
.skill-uses { display:flex; flex:1; min-height:0; min-width:0; overflow:hidden; container-type:inline-size; }.skill-list { flex:1 1 55%; min-width:0; padding:18px; overflow:auto; }.skill-detail { flex:0 1 46%; min-width:330px; border-left:1px solid #e5e9ef; }
header { display:flex; align-items:center; justify-content:space-between; gap:12px; } h3 { font-size:20px; margin:0; }.muted,time { color:#68798c; font-size:12px; } time { font-variant-numeric:tabular-nums; }
.skill-filters { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; }.skill-filters > * { flex:1 1 200px; min-width:0; }.skill-filters > .ant-input-affix-wrapper { flex-basis:190px; }.skill-table-scroll { overflow:auto; }.skill-table { width:100%; border-collapse:collapse; font-size:13px; table-layout:fixed; }.skill-table th { background:#f6f8fb; font-weight:600; text-align:left; }.skill-table th,.skill-table td { padding:14px 10px; border-bottom:1px solid #e9edf2; overflow-wrap:anywhere; vertical-align:top; }.skill-table th:first-child { width:22%; }.skill-table th:nth-child(2) { width:18%; }.skill-table th:last-child { width:19%; }.skill-table tr.selected td { background:#edf4ff; }.skill-table tbody tr { cursor:pointer; }.skill-table tbody tr:hover td { background:#f5f8fc; }.skill-table :deep(.ant-tag) { white-space:normal; margin:0; }.skill-name { display:inline-flex; align-items:center; gap:8px; text-align:left; background:none; border:0; padding:0; font:inherit; color:#202630; cursor:pointer; overflow-wrap:anywhere; }.skill-name .anticon { color:#315fbd; flex-shrink:0; }.skill-name:focus-visible { outline:2px solid #315fbd; outline-offset:4px; } td small { display:block; color:#68798c; margin-top:6px; } footer { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:18px; }
@container (max-width:900px) { .skill-list:has(+ .skill-detail) { display:none; }.skill-detail { flex:1; border-left:0; min-width:0; } }
@media(max-width:600px) { .skill-list { padding:12px; }.skill-table { min-width:540px; } }
</style>
