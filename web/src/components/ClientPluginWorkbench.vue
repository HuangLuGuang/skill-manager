<template>
  <section class="plugin-workbench" :class="{ scoped: fixedAgent }" :aria-busy="loading">
    <header class="workbench-toolbar">
      <a-space wrap><a-button @click="emit('policy')"><SettingOutlined />{{ tr('policy') }}</a-button><a-button :loading="loading" :disabled="loading || !!busy" @click="emit('refresh')"><ReloadOutlined />{{ tr('refresh') }}</a-button></a-space>
    </header>
    <div class="workbench-alerts"><slot name="alerts" /></div>
    <div v-if="loading && !state" class="workbench-loading" role="status"><a-spin /><p>{{ tr('loading') }}</p></div>
    <div v-else class="workbench-columns">
      <nav v-if="!fixedAgent" class="product-navigation" :aria-label="tr('products')">
        <button v-for="group in groups" :key="group.id" :aria-pressed="selectedGroup.id === group.id" :class="{ selected: selectedGroup.id === group.id }" @click="selectGroup(group)">
          <span class="product-logo"><AgentProductLogo :product-id="group.id" /></span>
          <span class="product-label"><strong>{{ group.name }}</strong><small :class="tone(groupStatus(group))">{{ statusLabel(groupStatus(group)) }}</small><small v-if="groupArrival(group)" :title="stamp(groupArrival(group))">{{ tr('latestEvent') }} · {{ shortStamp(groupArrival(group)) }}</small><small v-if="groupDelayed(group)" class="attention">{{ tr('delayed') }}</small></span><RightOutlined />
        </button>
      </nav>
      <main ref="detailPane" class="product-detail" tabindex="0" :aria-label="selectedGroup.name">
        <div class="receiver-strip" :class="{ running: receiver === 'running' }"><a-tooltip :title="tr('receiverNote')"><InfoCircleOutlined tabindex="0" :aria-label="tr('receiverNote')" /></a-tooltip><span>{{ tr('receiver') }} · {{ runtimeLabel('channelStates', receiver) }}</span><a-button type="link" @click="emit('collection')">{{ tr('collection') }}<RightOutlined /></a-button></div>
        <header class="product-heading"><span class="product-logo"><AgentProductLogo :product-id="selectedGroup.id" /></span><div><h2>{{ selectedGroup.name }}<a-tag :color="tagColor(status)">{{ statusLabel(status) }}</a-tag></h2><p>{{ tr(selected.hooks === 'native-plugin' ? 'nativeName' : 'hookName') }}</p></div></header>
        <div v-if="selectedGroup.entries.length > 1" class="entry-choice"><label>{{ tr('entry') }}</label><a-select :value="selected.id" :options="entryOptions" @update:value="selectedEntry = $event" :aria-label="tr('entry')" /></div>
        <p v-if="delayed(selected.id)" class="historical-note">{{ tr('historical', { at: stamp(observedHost?.reported_at) }) }}</p>
        <ol class="connection-steps" :style="{ '--step-count': steps.length }" :aria-label="tr('steps')"><li v-for="step in steps" :key="step.key" :class="step.state"><CheckCircleFilled v-if="step.state === 'confirmed'" /><ExclamationCircleOutlined v-else-if="step.state === 'attention'" /><ClockCircleOutlined v-else /><strong>{{ tr('step.' + (step.key === 'installation' && selected.hooks !== 'native-plugin' ? 'configuration' : step.key)) }}</strong><small>{{ step.label }}</small></li></ol>
        <section v-if="nextKind" class="next-step" :class="{ attention: tone(status) === 'attention' }">
          <h3>{{ tr('next.' + nextKind + '.title') }}</h3><p>{{ tr(configurationOnly && ['inspect', 'install'].includes(nextKind) ? 'configurationGuide' : 'next.' + nextKind + '.body') }}</p>
          <ol v-if="nextKind === 'authorize' && needsCodexReview" class="authorization-steps"><li v-for="key in ['review','trust','session']" :key="key">{{ tr('codex.' + key) }}</li></ol>
          <a-space wrap>
            <a-button v-if="primaryAction === 'install' && canExecute" type="primary" :loading="busy === 'install' + selected.id" :disabled="isActionBlocked('install', selected.id)" @click="emit('action', 'install', selected.id)">{{ tr('install') }}</a-button>
            <a-button v-else-if="primaryAction === 'inspect' && canExecute" type="primary" :loading="busy === 'inspect' + selected.id" :disabled="isActionBlocked('inspect', selected.id)" @click="emit('action', 'inspect', selected.id)">{{ tr('inspect') }}</a-button>
            <a-button v-else-if="primaryAction === 'policy'" type="primary" @click="emit('policy')">{{ tr('policy') }}</a-button>
            <a-button v-else type="primary" @click="guideOpen = true">{{ tr('guide') }}</a-button>
          </a-space>
        </section>
        <div class="event-summary"><span>{{ tr('latestEvent') }}<strong>{{ arrival(selected.id) ? stamp(arrival(selected.id)) : tr('noEvent') }}</strong></span><a-button @click="emit('events', selectedGroup.id)">{{ tr('viewEvents') }}<RightOutlined /></a-button></div>
        <section class="current-status"><dl><div><dt>{{ tr('hostVersion') }}</dt><dd>{{ observedHost?.host_version || tr('unknown') }}</dd></div><div><dt>{{ tr('pluginVersion') }}</dt><dd>{{ observedHost?.plugin_version || tr('unknown') }}</dd></div><div><dt>{{ tr('reportedAt') }}</dt><dd>{{ stamp(observedHost?.reported_at) }}</dd></div></dl></section>
        <slot name="tasks" :agent="selected.id" />
        <details :key="selected.id" class="workbench-disclosure"><summary>{{ tr('diagnostics') }}</summary>
          <p>{{ entryLabel(selected) }} · {{ selected.hook_os.join(' / ') }}</p><p>{{ runtimeLabel('', observedHost?.version_status) }}</p>
          <a-space wrap><a-button v-if="canExecute && primaryAction !== 'inspect'" :loading="busy === 'inspect' + selected.id" :disabled="isActionBlocked('inspect', selected.id)" @click="emit('action', 'inspect', selected.id)">{{ tr('inspect') }}</a-button><a-button v-if="canExecute && installation === 'installed'" :loading="busy === 'upgrade' + selected.id" :disabled="isActionBlocked('upgrade', selected.id)" @click="emit('action', 'upgrade', selected.id)">{{ tr('upgrade') }}</a-button><a-button @click="guideOpen = true">{{ tr('guide') }}</a-button></a-space>
          <slot name="diagnostics" :agent="selected.id" />
        </details>
      </main>
    </div>
    <a-modal v-model:open="guideOpen" :title="tr('guide')" :footer="null"><p>{{ tr('guidePath') }}</p><p>{{ selectedGroup.name }} · {{ entryLabel(selected) }}</p><ol class="guide-list"><li>{{ tr('guideDevice') }}</li><li>{{ configurationOnly ? tr('configurationGuide') : needsCodexReview ? tr('codex.review') : tr('guideHost') }}</li><li>{{ tr('guideVerify') }}</li></ol><p>{{ tr(configurationOnly ? 'configurationBoundary' : 'guideBoundary') }}</p><a-button @click="guideOpen = false">{{ tr('close') }}</a-button></a-modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircleFilled, ClockCircleOutlined, ExclamationCircleOutlined, InfoCircleOutlined, ReloadOutlined, RightOutlined, SettingOutlined } from '@ant-design/icons-vue'
import products from '../aidr-products.json'
import { groupProductEntries } from '../aidr-product-groups'
import AgentProductLogo from './AgentProductLogo.vue'
const props = defineProps({ state: Object, loading: Boolean, busy: String, canExecute: Boolean, isActionBlocked: { type: Function, required: true }, clientId: String, fixedAgent: { type: String, default: '' } })
const emit = defineEmits(['refresh','policy','collection','action','events'])
const { t, te, locale } = useI18n()
const tr = (key, values) => t('pluginWorkbench.' + key, values || {})
const groups = groupProductEntries(products.filter(p => p.hooks && (!props.fixedAgent || p.id === props.fixedAgent)))
const selectedProduct = ref(groups[0].id), selectedEntry = ref(''), detailPane = ref(null), guideOpen = ref(false)
const now = ref(Date.now())
const timer = setInterval(() => { now.value = Date.now() }, 5000)
onBeforeUnmount(() => clearInterval(timer))
const parse = value => value ? Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z') : NaN
const fresh = (value, seconds) => Number.isFinite(parse(value)) && now.value - parse(value) <= seconds * 1000 && now.value - parse(value) >= -5000
const stamp = value => Number.isFinite(parse(value)) ? new Date(parse(value)).toLocaleString(locale.value) : tr('unknown')
const shortStamp = value => new Date(parse(value)).toLocaleString(locale.value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const connection = id => props.state?.hook_connections?.find(item => item.agent === id)
const currentReport = computed(() => props.state && !props.state.stale && fresh(props.state.reported_at, 30))
const hostFresh = id => currentReport.value && !connection(id)?.stale && fresh(connection(id)?.observed_at, 480)
const arrival = id => connection(id)?.event_received_at || null
const host = id => props.state?.report?.hosts?.find(item => item.agent === id)
const delayed = id => !!host(id)?.reported_at && !hostFresh(id)
const observed = id => {
  if (hostFresh(id)) return connection(id)
  const h = host(id)
  return h ? { installation: h.source_code === 'aidr_desktop_host_missing' ? 'host_missing' : h.installed === true ? 'installed' : h.installed === false ? 'not_installed' : 'unknown', authorization: ({ trusted: 'authorized', managed: 'managed', needs_review: 'review_required' })[h.hook_trust] || 'unknown', enabled: h.enabled } : null
}
const detectedEntries = group => group.entries.filter(entry => {
  const h = host(entry.id)
  return h && h.source_code !== 'aidr_desktop_host_missing' && (h.host_version || h.installed === true)
})
const selectedGroup = computed(() => groups.find(group => group.id === selectedProduct.value) || groups[0])
const selected = computed(() => selectedGroup.value.entries.find(entry => entry.id === selectedEntry.value) || detectedEntries(selectedGroup.value)[0] || selectedGroup.value.entries[0])
const observedHost = computed(() => host(selected.value.id))
const entryOptions = computed(() => selectedGroup.value.entries.map(entry => ({ value: entry.id, label: entryLabel(entry) + (detectedEntries(selectedGroup.value).includes(entry) ? ` · ${tr('detected')}` : '') })))
const receiver = computed(() => currentReport.value && fresh(props.state?.channels?.hooks?.report?.reported_at, 30) ? props.state.channels.hooks.report.state : 'unknown')
const installation = computed(() => hostFresh(selected.value.id) ? connection(selected.value.id)?.installation : 'unknown')
const runtimeLabel = (section, value) => { const key = `agentRuntimeGovernance.${section ? section + '.' : ''}${value || 'unknown'}`; return te(key) ? t(key) : tr('unknown') }
const entryLabel = entry => t('agentRuntimeGovernance.catalog.entries.' + entry.entry)
const requiresAuthorization = entry => entry.hook_setup?.host_authorization !== false
const requiresEnablement = entry => entry.hook_setup?.host_enablement !== false
const configurationOnly = computed(() => !requiresAuthorization(selected.value) && !requiresEnablement(selected.value))
function entryStatus(entry) {
  const c = observed(entry.id)
  if (!props.state) return 'unknown'
  if (props.state.target_configured && connection(entry.id)?.requested === false) return 'not_requested'
  if (!c) return 'unknown'
  if (c.installation === 'host_missing') return 'host_missing'
  if (requiresAuthorization(entry) && ['review_required','admin_required','cancelled','failed','interrupted'].includes(c.authorization)) return 'authorization'
  if (c.installation === 'not_installed') return 'not_installed'
  if (requiresEnablement(entry) && c.enabled === false) return 'disabled'
  if (c.installation === 'installed' && (!requiresEnablement(entry) || c.enabled === true)) return 'configured'
  return 'unknown'
}
const needsCodexReview = computed(() => selected.value.id === 'codex' && connection(selected.value.id)?.authorization === 'review_required')
const status = computed(() => entryStatus(selected.value))
const groupEntries = group => detectedEntries(group).length ? detectedEntries(group) : group.entries
const groupStatus = group => { const states = [...new Set(groupEntries(group).map(entryStatus))]; return states.length === 1 ? states[0] : 'mixed' }
const groupDelayed = group => groupEntries(group).some(entry => entryStatus(entry) !== 'not_requested' && delayed(entry.id))
const groupArrival = group => group.entries.map(entry => arrival(entry.id)).filter(Boolean).sort((a, b) => parse(b) - parse(a))[0]
const statusLabel = value => tr('states.' + value)
const tone = value => ['authorization','disabled','not_installed'].includes(value) ? 'attention' : 'neutral'
const tagColor = value => tone(value) === 'success' ? 'green' : tone(value) === 'attention' ? 'orange' : undefined
const steps = computed(() => {
  const c = observed(selected.value.id)
  const step = (key, value, confirmed, attention = []) => ({ key, state: delayed(selected.value.id) ? 'historical' : confirmed ? 'confirmed' : attention.includes(value) ? 'attention' : 'pending', label: key === 'installation' || key === 'authorization' ? runtimeLabel('connection.' + key + 'States', value) : runtimeLabel('connection', value === true ? 'enabledYes' : value === false ? 'enabledNo' : 'unknown') })
  const result = [step('installation', c?.installation, c?.installation === 'installed', ['not_installed'])]
  if (requiresAuthorization(selected.value)) result.push(step('authorization', c?.authorization, ['authorized','managed'].includes(c?.authorization), ['review_required','admin_required','cancelled','failed','interrupted']))
  if (requiresEnablement(selected.value)) result.push(step('enabled', c?.enabled, c?.enabled === true, [false]))
  return result
})
const nextKind = computed(() => {
  if (status.value === 'not_requested') return 'policy'
  if (delayed(selected.value.id) || status.value === 'unknown') return 'inspect'
  if (status.value === 'host_missing') return 'host'
  if (status.value === 'authorization') return 'authorize'
  if (status.value === 'not_installed') return ['interface_compatible','adapter_available'].includes(observedHost.value?.version_status) ? 'install' : 'inspect'
  if (status.value === 'disabled') return 'enable'
  return arrival(selected.value.id) ? '' : 'verify'
})
const primaryAction = computed(() => ({ policy: 'policy', inspect: 'inspect', install: 'install' }[nextKind.value] || (nextKind.value ? 'guide' : '')))
function selectGroup(group) { selectedProduct.value = group.id; selectedEntry.value = ''; if (detailPane.value) detailPane.value.scrollTop = 0 }
watch(() => props.clientId, () => { selectedProduct.value = groups[0].id; selectedEntry.value = ''; guideOpen.value = false })
</script>

<style scoped>
.plugin-workbench.scoped .workbench-columns { grid-template-columns: minmax(0, 1fr); }
.plugin-workbench.scoped .product-detail { border-left: 0; }
.entry-choice { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; color: #60738b; font-size: 13px; }
.entry-choice :deep(.ant-select) { min-width: 160px; max-width: 100%; flex: 1; }
.event-summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 0; border-bottom: 1px solid #e3e9f0; color: #60738b; font-size: 12px; }
.event-summary strong { display: block; color: #243348; font-size: 14px; font-weight: 500; margin-top: 6px; }
.event-summary :deep(.ant-btn) { height: auto; min-height: 32px; white-space: normal; }
.plugin-workbench{display:flex;flex-direction:column;height:100%;min-height:0;color:#243348;overflow-wrap:anywhere}
.workbench-toolbar{display:flex;justify-content:flex-end;align-items:center;gap:8px;flex:none;padding:0 0 8px}.workbench-alerts{flex:none;max-height:25%;overflow:auto}.workbench-alerts:empty{display:none}.workbench-alerts :deep(.ant-alert){margin-bottom:10px}.workbench-loading{display:grid;place-content:center;flex:1;gap:16px;color:#76869b}.workbench-columns{display:grid;grid-template-columns:265px minmax(0,1fr);flex:1;min-height:0;border-top:1px solid #e3e9f0}
.product-navigation{overflow-y:auto;overscroll-behavior:contain;border-right:1px solid #e3e9f0;padding:8px 12px 8px 0}.product-navigation button{display:flex;align-items:center;gap:14px;width:100%;padding:12px;text-align:left;background:white;border:0;border-left:3px solid transparent;border-bottom:1px solid #eef1f5;border-radius:5px;cursor:pointer;color:inherit}.product-navigation button.selected{background:#edf4ff;border-left-color:#245ef5}.product-navigation button:hover{background:#f4f7fc}.product-logo{display:inline-flex;flex:none;width:38px;height:38px}.product-label{flex:1;min-width:0}.product-label strong{display:block;font-size:16px}.product-label small{display:block;font-size:12px;color:#76869b;margin-top:6px}.product-label small.success{color:#238653}.product-label small.attention{color:#b97819}.product-navigation .anticon{font-size:11px;color:#75869c}
.product-detail{overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;min-height:0;padding:8px 0 12px 16px}.receiver-strip{display:flex;align-items:center;gap:12px;padding:12px 16px;border:1px solid #e3e9f0;border-radius:6px;background:#f7f9fc;color:#60738b;font-size:13px}.receiver-strip.running{background:#f2faf7;border-color:#cfe8dc}.receiver-strip>.anticon{font-size:18px}.receiver-strip.running>.anticon{color:#238653}.receiver-strip>span:not(.anticon){flex:1}.receiver-strip small{display:block;font-size:11px;color:#73879a;margin-top:4px}.receiver-strip :deep(.ant-btn){padding:0;height:auto;white-space:normal}.product-heading{display:flex;align-items:center;gap:16px;margin:12px 0}.product-heading .product-logo{width:48px;height:48px}.product-heading h2{display:flex;align-items:center;flex-wrap:wrap;gap:12px;font-size:25px;line-height:1.4;margin:0 0 5px}.product-heading p{font-size:13px;color:#76869b;margin:0}
.connection-steps{display:grid;grid-template-columns:repeat(var(--step-count,3),minmax(0,1fr));gap:10px;padding:14px;margin:0 0 16px;list-style:none;background:#f8fafc;border:1px solid #e3e9f0;border-radius:8px}.connection-steps li{display:grid;grid-template-columns:20px minmax(0,1fr);column-gap:8px;text-align:left;min-width:0}.connection-steps .anticon{grid-row:span 2;font-size:18px;color:#9cacc0;margin-top:2px}.connection-steps .historical strong,.connection-steps .historical small{color:#8a7755}.connection-steps .confirmed .anticon{color:#238653}.connection-steps .attention .anticon{color:#c38b22}.connection-steps strong{display:block;font-size:13px;margin:0 0 4px;font-weight:500}.connection-steps small{display:block;font-size:11px;color:#7c8ca2;line-height:1.6}
.next-step{background:#f4f8ff;border:1px solid #e3edff;border-radius:7px;padding:14px 16px}.next-step h3{font-size:15px;margin:0 0 8px}.next-step>p{font-size:13px;color:#637996;line-height:1.6;margin:0 0 12px}.authorization-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;padding:0 0 0 20px;margin:20px 0 24px;font-size:13px;line-height:1.8}.authorization-steps li::marker{color:#245ef5;font-weight:600}.next-step :deep(.ant-btn){height:auto;min-height:34px;white-space:normal}.current-status{margin:12px 0}.current-status h4{font-size:14px;margin:0 0 12px}.current-status dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 26px;margin:0;font-size:12px}.current-status dl>div{display:grid;grid-template-columns:95px minmax(0,1fr);gap:10px;align-items:baseline}.current-status dt{color:#7c8ca2}.current-status dd{margin:0;color:#415672}.historical-note{font-size:12px;color:#b97819;margin-top:12px}.workbench-disclosure{border-top:1px solid #e3e9f0;padding:12px 0;font-size:13px}.workbench-disclosure>summary{cursor:pointer;color:#415672;font-weight:500}.workbench-disclosure>p{margin-top:12px;color:#75869c}.guide-list{padding-left:20px;line-height:1.8}.guide-list li{margin:14px 0}button:focus-visible,summary:focus-visible{outline:2px solid #245ef5;outline-offset:2px}
@media(max-width:1000px){.workbench-columns{grid-template-columns:215px minmax(0,1fr)}.product-detail{padding-left:18px}.product-navigation{padding-right:10px}.product-navigation button{gap:9px;padding:12px 8px}.product-label strong{font-size:14px}.product-logo{width:30px;height:30px}.current-status dl{grid-template-columns:1fr}.authorization-steps{grid-template-columns:1fr;gap:8px}}
@media(max-width:650px){.workbench-toolbar{align-items:flex-start;flex-wrap:wrap;padding-bottom:12px;gap:8px}.workbench-toolbar :deep(.ant-btn){font-size:12px;padding:4px 8px}.workbench-columns{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr)}.product-navigation{display:flex;overflow-x:auto;overflow-y:hidden;gap:5px;padding:8px 0;border-right:0;border-bottom:1px solid #e3e9f0}.product-navigation button{width:170px;flex:none;padding:10px 8px;gap:8px}.product-navigation button>.anticon{display:none}.product-detail{padding:12px 0}.product-heading{margin:12px 0}.product-heading h2{font-size:22px}.receiver-strip{gap:8px;padding:10px;flex-wrap:wrap}.connection-steps{grid-template-columns:1fr;gap:12px}.event-summary{flex-wrap:wrap}.connection-steps strong{font-size:12px}.next-step{padding:16px}.next-step h3{font-size:16px}.current-status dl>div{grid-template-columns:90px minmax(0,1fr)}}
</style>
