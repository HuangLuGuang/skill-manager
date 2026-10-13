<template>
  <div class="asset-lifecycle">
    <a-drawer v-model:open="sourcesOpen" :title="t('scanSchedule.sources')" width="min(1100px, 100vw)">
        <div class="toolbar"><p>{{ t('assetLifecycle.sourceHelp') }}</p><a-button v-if="hasAccess('targets:create')" type="primary" @click="editSource()">{{ t('assetLifecycle.add') }}</a-button></div>
        <a-table :columns="sourceColumns" :data-source="sources" row-key="source_id" :loading="loading" :scroll="{ x: 1050 }" :locale="{ emptyText: t('assetLifecycle.emptySources') }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'schedule'">{{ t(`assetLifecycle.${record.config.schedule_kind}`) }}<small>{{ record.config.timezone }}</small></template>
            <template v-else-if="column.key === 'nextRun'">{{ record.enabled ? date(record.next_run_at) : '—' }}</template>
            <template v-else-if="column.key === 'lastSuccess'">{{ date(record.last_success_at) }}</template>
            <template v-else-if="column.key === 'actions'"><a-space wrap>
              <a-button v-if="hasAccess('targets:update')" size="small" :disabled="!!record.active_run_id" @click="editSource(record)">{{ t('assetLifecycle.edit') }}</a-button>
              <a-button v-if="hasAccess('targets:sync')" size="small" :loading="busy === record.source_id" :disabled="!!busy || !!record.active_run_id" @click="sync(record)">{{ t('assetLifecycle.sync') }}</a-button>
              <a-button size="small" @click="openRuns(record)">{{ t('assetLifecycle.runs') }}</a-button>
            </a-space></template>
          </template>
        </a-table>

    </a-drawer>
    <a-modal v-model:open="sourceOpen" :title="t(editing ? 'assetLifecycle.edit' : 'assetLifecycle.add')" width="min(760px, calc(100vw - 24px))" :footer="null">
      <a-form :model="form" layout="vertical" @finish="saveSource">
        <div class="form-grid">
          <a-form-item :label="t('assetLifecycle.name')" required><a-input v-model:value="form.name" :maxlength="128" /></a-form-item>
          <a-form-item :label="t('assetLifecycle.target')" required><a-select v-model:value="form.template_target_id" :disabled="!!editing" :options="difyTargets" @change="selectTarget" /></a-form-item>
          <a-form-item :label="t('assetLifecycle.policy')" required><a-select v-model:value="form.policy_id" :options="policyOptions" /></a-form-item>
          <a-form-item :label="t('assetLifecycle.scope')"><a-select v-model:value="form.config.scope" :options="scopeOptions" /></a-form-item>
        </div>
        <a-form-item v-if="form.config.scope === 'selected'" :label="t('assetLifecycle.appIds')" required><a-textarea v-model:value="appIds" :rows="3" /></a-form-item>
        <div class="form-grid">
          <a-form-item :label="t('assetLifecycle.schedule')"><a-select v-model:value="form.config.schedule_kind" :options="scheduleOptions" /></a-form-item>
          <a-form-item :label="t('assetLifecycle.timezone')"><TimezoneSelect v-model="form.config.timezone" /></a-form-item>
          <a-form-item v-if="form.config.schedule_kind === 'interval'" :label="t('assetLifecycle.minutes')"><a-input-number v-model:value="form.config.interval_minutes" :min="5" :max="525600" /></a-form-item>
          <a-form-item v-else-if="form.config.schedule_kind === 'daily'" :label="t('assetLifecycle.dailyTime')"><a-input v-model:value="form.config.daily_time" type="time" /></a-form-item>
          <a-form-item v-else :label="t('assetLifecycle.cron')"><a-input v-model:value="form.config.cron" /></a-form-item>
          <a-form-item :label="t('assetLifecycle.enabled')"><a-switch v-model:checked="form.config.enabled" /></a-form-item>
          <a-form-item :label="t('assetLifecycle.autoPolicy')"><a-select v-model:value="form.config.auto_scan_policy_id" allow-clear :options="policyOptions" /></a-form-item>
          <a-form-item v-if="form.config.auto_scan_policy_id" :label="t('assetLifecycle.evaluationModel')" :extra="t('assetLifecycle.evaluationModelHelp')" required><a-select v-model:value="form.config.evaluation_model" show-search option-filter-prop="label" :options="evaluationModelOptions" /></a-form-item>
          <a-form-item :label="t('assetLifecycle.validity')"><a-input-number v-model:value="form.config.validity_hours" :min="1" :max="8760" /></a-form-item>
        </div>
        <a-space v-if="form.config.auto_scan_policy_id" wrap><a-checkbox v-model:checked="form.config.scan_new_apps">{{ t('scanSchedule.scanNew') }}</a-checkbox><a-checkbox v-model:checked="form.config.scan_changed_apps">{{ t('scanSchedule.scanChanged') }}</a-checkbox></a-space>
        <p>{{ t('assetLifecycle.autoHelp') }}</p>
        <a-form-item :label="t('assetLifecycle.skills')"><a-select v-model:value="form.config.skills" mode="multiple" :options="skillOptions" /></a-form-item>
        <a-button type="primary" html-type="submit" :loading="saving" :disabled="saving">{{ t('assetLifecycle.save') }}</a-button>
      </a-form>
    </a-modal>

    <a-drawer v-model:open="runsOpen" :title="t('assetLifecycle.runs')" width="min(960px, 100vw)">
      <a-table :columns="runColumns" :data-source="runs" row-key="run_id" :scroll="{ x: 650 }">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">{{ label(record.status) }}</template>
          <template v-else-if="column.key === 'actions'"><a-space wrap><a-button @click="showRun(record.run_id)">{{ t('assetLifecycle.details') }}</a-button><a-button v-if="hasAccess('targets:sync') && ['pending', 'running'].includes(record.status)" :loading="busy === record.run_id" :disabled="!!busy" @click="cancelRun(record.run_id)">{{ t('assetLifecycle.cancel') }}</a-button></a-space></template>
        </template>
      </a-table>
      <template v-if="runDetail">
        <p>{{ t('assetLifecycle.totalDiscovered', { count: runDetail.discovered_count }) }}</p>
        <a-alert v-if="runDetail.error_code" type="warning" :message="errorCode(runDetail.error_code)" />
        <a-table :columns="itemColumns" :data-source="runDetail.items" row-key="external_id" :scroll="{ x: 700 }">
          <template #bodyCell="{ column, record }"><template v-if="['status', 'change_kind'].includes(column.key)">{{ label(record[column.key]) }}</template><template v-else-if="column.key === 'error_code'">{{ record.error_code ? errorCode(record.error_code) : '—' }}</template><template v-else-if="column.key === 'task_id'"><a v-if="record.task_id" @click="openTask(record.task_id)">{{ record.task_id }}</a></template></template>
        </a-table>
        <a-button @click="showRaw(runDetail)">{{ t('assetLifecycle.raw') }}</a-button>
      </template>
    </a-drawer>

    <a-drawer v-model:open="riskOpen" :title="selectedAgent?.name" width="min(1000px, 100vw)">
      <a-spin :spinning="riskLoading">
        <template v-if="risk">
          <a-alert v-if="risk.rescan_error_code" type="warning" show-icon :message="t('assetLifecycle.rescanDeferred')" :description="errorCode(risk.rescan_error_code)" />
          <h3>{{ t('scanSchedule.currentScore') }}</h3><p>{{ t('assetLifecycle.scoreHelp') }}</p><p v-if="selectedAgent?.source">{{ t('scanSchedule.sources') }}: {{ selectedAgent.source.name }} · {{ date(selectedAgent.source.last_success_at) }} <a-button type="link" @click="openSources">{{ t('assetLifecycle.edit') }}</a-button></p><div class="risk-overview"><strong class="risk-score" :class="`risk-${risk.level}`">{{ risk.score ?? '—' }}</strong><div><a-tag :color="color(risk.status)">{{ label(risk.status) }}</a-tag><p>{{ t('assetLifecycle.formula') }}</p><small>{{ t('assetLifecycle.scoreVersion') }}: {{ risk.algorithm_version }} · {{ t('assetLifecycle.revision') }}: {{ risk.revision }}</small></div></div>
          <a-tabs default-active-key="contributions">
            <a-tab-pane key="overview" :tab="t('agentSecurityScans.detail.summary')"><p v-if="selectedAgent?.latest_scan">{{ t('scanSchedule.latestScan') }}: <a @click="openTask(selectedAgent.latest_scan.task_id)">{{ date(selectedAgent.latest_scan.created_at) }}</a></p><p>{{ t('scanSchedule.title') }}</p><a-list :data-source="selectedAgent?.schedules || []"><template #renderItem="{ item }"><a-list-item><a @click="openPlan(item.schedule_id)">{{ item.name }}</a><a-tag>{{ t(item.enabled ? 'scanSchedule.enabled' : 'scanSchedule.paused') }}</a-tag></a-list-item></template></a-list></a-tab-pane>
            <a-tab-pane v-if="hasAccess('targets:update')" key="links" :tab="t('assetLifecycle.relatedTargets')"><p>{{ t('assetLifecycle.relatedHelp') }}</p><a-select v-model:value="relatedTargets" mode="multiple" :options="mcpOptions" style="width: 100%; margin-bottom: 16px" /><a-button :loading="linksSaving" :disabled="linksSaving" @click="saveLinks">{{ t('assetLifecycle.saveLinks') }}</a-button></a-tab-pane>
            <a-tab-pane key="contributions" :tab="t('assetLifecycle.contributions')">
              <a-table :columns="issueColumns" :data-source="issues" row-key="issue_id" :scroll="{ x: 800 }">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'severity'">{{ label(record.severity) }}</template><template v-else-if="column.key === 'status'">{{ label(record.status) }}</template>
                  <template v-else-if="column.key === 'points'">{{ risk.contributions.find(x => x.issue_id === record.issue_id)?.points ?? 0 }}</template>
                  <template v-else-if="column.key === 'actions'"><a-space wrap><a-button size="small" @click="router.push({ path: '/agent-security/scans', query: { finding_id: record.finding_id } })">{{ t('assetLifecycle.evidence') }}</a-button><a-button v-if="hasAccess('targets:update')" size="small" @click="openReview(record)">{{ t('assetLifecycle.review') }}</a-button></a-space></template>
                </template>
              </a-table>
            </a-tab-pane>
            <a-tab-pane key="checks" :tab="t('assetLifecycle.checks')"><a-list :data-source="risk.coverage"><template #renderItem="{ item }"><a-list-item><span>{{ checkLabel(item.check) }}</span><a-space wrap><a-tag :color="color(item.status)">{{ label(item.status) }}</a-tag><a v-if="item.task_id" @click="openTask(item.task_id)">{{ t('assetLifecycle.evidence') }}</a></a-space></a-list-item></template></a-list></a-tab-pane>
            <a-tab-pane key="history" :tab="t('assetLifecycle.history')"><a-table :columns="historyColumns" :data-source="history" row-key="assessment_id" :scroll="{ x: 650 }"><template #bodyCell="{ column, record }"><template v-if="column.key === 'status'">{{ label(record.status) }}</template><template v-else-if="column.key === 'score'">{{ record.score ?? '—' }}</template></template></a-table></a-tab-pane>
          </a-tabs>
          <a-button @click="showRaw({ risk, issues, history })">{{ t('assetLifecycle.raw') }}</a-button>
        </template>
      </a-spin>
    </a-drawer>
    <a-modal v-model:open="reviewOpen" :title="t('assetLifecycle.review')" :footer="null">
      <a-form :model="review" layout="vertical" @finish="saveReview"><a-form-item :label="t('assetLifecycle.coverage')"><a-select v-model:value="review.status" :options="reviewOptions" /></a-form-item><a-form-item :label="t('assetLifecycle.comment')" required><a-textarea v-model:value="review.comment" :maxlength="2000" /></a-form-item><a-form-item v-if="review.status === 'resolved'" :label="t('assetLifecycle.closureTask')" required><a-input v-model:value="review.closure_task_id" /></a-form-item><a-button type="primary" html-type="submit" :loading="reviewSaving" :disabled="reviewSaving || !review.comment.trim()">{{ t('assetLifecycle.submitReview') }}</a-button></a-form>
    </a-modal>
    <a-modal v-model:open="rawOpen" :title="t('assetLifecycle.raw')" width="min(1000px, 100vw)" :footer="null"><a-button @click="downloadRaw">{{ t('assetLifecycle.download') }}</a-button><pre class="raw-content">{{ raw }}</pre></a-modal>
  </div>
</template>

<script setup>
import { can as hasAccess } from '../../access'
import { createRequestId } from '../../utils/requestId'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { localizeApiError } from '../../i18n/errors'
import TimezoneSelect from './TimezoneSelect.vue'
import { getSecurityRedteamOptions, setManagedAgentRelatedTargets } from '../../api'
import { listSecurityTargets, listSecurityPolicies, listAssetSources, createAssetSource, updateAssetSource, startAssetSync, listAssetSyncRuns, getAssetSyncRun, cancelAssetSyncRun, getTargetRiskProfile, getManagedAgentRisk, getManagedAgentRiskHistory, getManagedAgentRiskIssues, reviewManagedAgentRisk } from '../../api'

const { t, te, locale } = useI18n(), router = useRouter()
const sources = ref([]), targets = ref([]), policies = ref([]), sourcesOpen = ref(false)
const evaluationModels = ref([])
const loading = ref(false), error = ref(''), busy = ref(''), saving = ref(false)
const sourceOpen = ref(false), editing = ref(null), appIds = ref(''), form = reactive({ config: {} })
const runsOpen = ref(false), runs = ref([]), runDetail = ref(null), runSource = ref(null)
const riskOpen = ref(false), riskLoading = ref(false), selectedAgent = ref(null), risk = ref(null), issues = ref([]), history = ref([])
const reviewOpen = ref(false), reviewSaving = ref(false), reviewIssue = ref(null), review = reactive({ status: 'open', comment: '', closure_task_id: '' })
const rawOpen = ref(false), raw = ref('')
const relatedTargets = ref([]), linksSaving = ref(false)
const skills = ['data-leakage-detection', 'tool-abuse-detection', 'indirect-injection-detection', 'authorization-bypass-detection', 'web-exfiltration-detection', 'agentic-supply-chain-detection', 'unexpected-code-execution-detection', 'inter-agent-comm-security-detection', 'cascading-failure-detection', 'human-agent-trust-exploit-detection']
const mcpOptions = computed(() => { const owner = targets.value.find(x => x.target_id === selectedAgent.value?.target_id); return targets.value.filter(x => x.asset_type === 'mcp' && x.owner_user_id === owner?.owner_user_id && x.owner_group_id === owner?.owner_group_id).map(x => ({ value: x.target_id, label: x.name })) })
const label = value => value && te(`assetLifecycle.states.${value}`) ? t(`assetLifecycle.states.${value}`) : value || '—'
const checkLabel = value => value === 'inventory' ? label(value) : (te(`assetLifecycle.ruleNames.${value}`) ? t(`assetLifecycle.ruleNames.${value}`) : value)
const errorCode = code => localizeApiError({ code }, locale.value)
const color = value => ({ complete: 'green', completed: 'green', failed: 'red', partial: 'orange', stale: 'orange', running: 'blue' }[value] || 'default')
const date = value => value ? new Date(value).toLocaleString(locale.value) : '—'
const columns = entries => entries.map(([key, title, width]) => ({ key, dataIndex: key, title: t(`assetLifecycle.${title || key}`), width }))
const sourceColumns = computed(() => columns([['name', null, 200], ['schedule', null, 150], ['nextRun', null, 190], ['lastSuccess', null, 190], ['actions', null, 300]]))
const runColumns = computed(() => columns([['run_id', 'run', 240], ['status', 'coverage', 130], ['actions', null, 240]]))
const itemColumns = computed(() => columns([['external_id', 'appId', 180], ['status', 'coverage', 130], ['change_kind', 'change', 110], ['task_id', 'task', 240], ['error_code', 'error', 200]]))
const issueColumns = computed(() => columns([['issue_id', 'issue', 200], ['severity', null, 100], ['status', 'coverage', 150], ['points', null, 90], ['actions', null, 260]]))
const historyColumns = computed(() => columns([['assessed_at', 'assessedAt', 210], ['score', null, 100], ['status', 'coverage', 180], ['revision', null, 100]]))
const difyTargets = computed(() => targets.value.filter(x => x.connector_type === 'dify').map(x => ({ value: x.target_id, label: x.name })))
const policyOptions = computed(() => policies.value.filter(x => x.enabled && x.environment === targets.value.find(y => y.target_id === form.template_target_id)?.environment).map(x => ({ value: x.policy_id, label: x.name })))
const evaluationModelOptions = computed(() => evaluationModels.value.map(model => ({ value: model.name, label: `${model.display_name || model.name} · ${model.provider_name}` })))
const scopeOptions = computed(() => ['selected', 'workspace'].map(value => ({ value, label: t(`assetLifecycle.${value}`) })))
const scheduleOptions = computed(() => ['interval', 'daily', 'cron'].map(value => ({ value, label: t(`assetLifecycle.${value}`) })))
const skillOptions = computed(() => skills.map(value => ({ value, label: checkLabel(value) })))
const reviewOptions = computed(() => ['open', 'accepted', 'false_positive', 'pending_verification', 'resolved'].map(value => ({ value, label: label(value) })))
const fail = e => { error.value = e.response?.data?.detail || t('assetLifecycle.failed'); message.error(error.value) }
async function load() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try { const values = await Promise.all([listAssetSources(), listSecurityTargets(), hasAccess('scans:view') ? listSecurityPolicies() : [], hasAccess('scans:view') ? getSecurityRedteamOptions() : {}]); sources.value = values[0]; targets.value = values[1]; policies.value = values[2]; evaluationModels.value = values[3].evaluation_models || [] } catch (e) { fail(e) } finally { loading.value = false }
}
function editSource(row) {
  editing.value = row || null
  Object.assign(form, row ? structuredClone({ name: row.name, template_target_id: row.template_target_id, policy_id: row.policy_id, config: JSON.parse(JSON.stringify(row.config)) }) : { name: '', template_target_id: undefined, policy_id: undefined, config: { scope: 'selected', app_ids: [], schedule_kind: 'interval', timezone: 'Asia/Shanghai', interval_minutes: 360, daily_time: '02:00', cron: '0 2 * * *', enabled: true, auto_scan_policy_id: null, scan_new_apps: true, scan_changed_apps: true, validity_hours: 168, language: locale.value === 'en-US' ? 'en' : 'zh', skills: [...skills] } })
  appIds.value = form.config.app_ids.join('\n'); sourceOpen.value = true
}
function selectTarget(id) { const target = targets.value.find(x => x.target_id === id); if (target) { appIds.value = target.config?.app_id || ''; if (!form.name) form.name = target.name }; form.policy_id = undefined; form.config.auto_scan_policy_id = null }
async function saveSource() {
  if (saving.value) return
  form.config.app_ids = [...new Set(appIds.value.split('\n').map(x => x.trim()).filter(Boolean))]
  if (!form.name.trim() || !form.template_target_id || !form.policy_id || (form.config.scope === 'selected' && !form.config.app_ids.length)) return message.warning(t('assetLifecycle.required'))
  if (form.config.auto_scan_policy_id && !form.config.evaluation_model) return message.warning(t('assetLifecycle.evaluationModelRequired'))
  saving.value = true
  try { const payload = { name: form.name.trim(), policy_id: form.policy_id, config: { ...form.config, auto_scan_policy_id: form.config.auto_scan_policy_id || null } }; if (editing.value) await updateAssetSource(editing.value.source_id, { ...payload, version: editing.value.version }); else await createAssetSource({ ...payload, template_target_id: form.template_target_id }); sourceOpen.value = false; message.success(t('assetLifecycle.saved')); await load() } catch (e) { fail(e) } finally { saving.value = false }
}
const syncKeys = new Map()
async function sync(row) { if (busy.value) return; busy.value = row.source_id; try { if (!syncKeys.has(row.source_id)) syncKeys.set(row.source_id, createRequestId()); const run = await startAssetSync(row.source_id, syncKeys.get(row.source_id)); syncKeys.delete(row.source_id); message.success(t('assetLifecycle.requested')); await load(); await openRuns(row); await showRun(run.run_id) } catch (e) { fail(e) } finally { busy.value = '' } }
async function openRuns(row) { runSource.value = row; runsOpen.value = true; runDetail.value = null; try { runs.value = await listAssetSyncRuns(row.source_id) } catch (e) { fail(e) } }
async function showRun(id) { try { runDetail.value = await getAssetSyncRun(id) } catch (e) { fail(e) } }
async function cancelRun(id) { if (busy.value) return; busy.value = id; try { await cancelAssetSyncRun(id); message.success(t('assetLifecycle.cancelled')); runs.value = await listAssetSyncRuns(runSource.value.source_id); await showRun(id) } catch (e) { fail(e) } finally { busy.value = '' } }
async function openRisk(agent) { if (riskLoading.value) return; selectedAgent.value = agent; riskOpen.value = true; riskLoading.value = true; risk.value = null; try { risk.value = await getManagedAgentRisk(agent.agent_id); relatedTargets.value = risk.value.related_target_ids || []; [issues.value, history.value] = await Promise.all([getManagedAgentRiskIssues(agent.agent_id), getManagedAgentRiskHistory(agent.agent_id)]) } catch (e) { fail(e) } finally { riskLoading.value = false } }
function openTask(id) { riskOpen.value = false; runsOpen.value = false; router.push({ path: '/agent-security/scans', query: { task_id: id } }) }
async function saveLinks() { if (linksSaving.value) return; linksSaving.value = true; try { await setManagedAgentRelatedTargets(selectedAgent.value.agent_id, relatedTargets.value); message.success(t('assetLifecycle.saved')); await openRisk(selectedAgent.value); await load() } catch (e) { fail(e) } finally { linksSaving.value = false } }
function openReview(issue) { reviewIssue.value = issue; Object.assign(review, { status: issue.status, comment: '', closure_task_id: '' }); reviewOpen.value = true }
async function saveReview() { if (reviewSaving.value || !review.comment.trim()) return; reviewSaving.value = true; try { await reviewManagedAgentRisk(selectedAgent.value.agent_id, reviewIssue.value.issue_id, { ...review, closure_task_id: review.closure_task_id || null }); reviewOpen.value = false; message.success(t('assetLifecycle.reviewed')); await openRisk(selectedAgent.value); await load() } catch (e) { fail(e) } finally { reviewSaving.value = false } }
function showRaw(value) { raw.value = JSON.stringify(value, null, 2); rawOpen.value = true }
function downloadRaw() { const url = URL.createObjectURL(new Blob([raw.value], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = 'asset-risk-report.json'; link.click(); URL.revokeObjectURL(url) }
let timer
onMounted(() => { timer = setInterval(async () => { if (runsOpen.value && runSource.value && !busy.value) { try { runs.value = await listAssetSyncRuns(runSource.value.source_id); if (runDetail.value) await showRun(runDetail.value.run_id) } catch { /* The next explicit refresh presents request errors. */ } } }, 10000) })
onUnmounted(() => clearInterval(timer))
function openPlan(id) { riskOpen.value = false; router.push({ path: '/agent-security/scans', query: { stage: 'schedules', schedule_id: id } }) }
async function openSources() { sourcesOpen.value = true; await load() }
async function openTarget(target) { await load(); try { const agent = await getTargetRiskProfile(target.target_id); await openRisk(agent) } catch (e) { fail(e) } }
defineExpose({ openSources, openTarget })
</script>

<style scoped>
.asset-lifecycle { color: #182338; min-width: 0; }
.page-heading, .toolbar { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 16px; margin-bottom: 20px; }
.page-heading h1 { margin: 0 0 8px; font-size: 24px; font-weight: 650; }
.page-heading p, .toolbar p, .explanation { color: #667085; margin: 0; max-width: 760px; line-height: 1.65; }
.explanation { margin-bottom: 20px; }
small { display: block; color: #667085; overflow-wrap: anywhere; }
.risk-score { display: inline-block; font-size: 28px; font-weight: 650; font-variant-numeric: tabular-nums; line-height: 1.3; }
.risk-high, .risk-critical { color: #b42318; }.risk-medium { color: #ad6800; }.risk-unassessed { color: #667085; }
.risk-overview { display: flex; align-items: center; gap: 24px; padding: 8px 0 24px; border-bottom: 1px solid #dce3ec; margin-bottom: 16px; }
.risk-overview > .risk-score { font-size: 48px; min-width: 70px; }.risk-overview p { line-height: 1.6; }
.form-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0 20px; }
.form-grid :deep(.ant-input-number) { width: 100%; }
.asset-lifecycle :deep(.ant-table-cell), .asset-lifecycle :deep(.ant-select-selection-item) { overflow-wrap: anywhere; }
.raw-content { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 65vh; overflow: auto; font-size: 12px; padding: 16px; background: #f5f7fa; }
@media (max-width: 600px) { .form-grid { grid-template-columns: minmax(0, 1fr); }.risk-overview { gap: 12px; align-items: flex-start; }.page-heading h1 { font-size: 21px; } }
</style>
