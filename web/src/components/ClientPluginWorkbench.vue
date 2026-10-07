<template>
  <section class="plugin-workbench" :aria-busy="loading">
    <header class="workbench-toolbar">
      <div><h3>{{ tr('title') }}</h3><p>{{ tr('subtitle') }}</p></div>
      <a-space wrap><a-button @click="emit('policy')"><SettingOutlined />{{ tr('policy') }}</a-button><a-button :loading="loading" :disabled="loading || !!busy" @click="emit('refresh')"><ReloadOutlined />{{ tr('refresh') }}</a-button></a-space>
    </header>
    <div class="workbench-alerts"><slot name="alerts" /></div>
    <div v-if="loading && !state" class="workbench-loading" role="status"><a-spin /><p>{{ tr('loading') }}</p></div>
    <div v-else class="workbench-columns">
      <nav class="product-navigation" :aria-label="tr('products')">
        <button v-for="group in groups" :key="group.id" :aria-pressed="selectedGroup.id === group.id" :class="{ selected: selectedGroup.id === group.id }" @click="selectGroup(group)">
          <span class="product-logo"><AgentProductLogo :product-id="group.id" /></span>
          <span class="product-label"><strong>{{ group.name }}</strong><small :class="tone(groupStatus(group))">{{ statusLabel(groupStatus(group)) }}</small><small v-if="group.entries.length > 1">{{ tr('entries', { count: group.entries.length }) }}</small></span><RightOutlined />
        </button>
      </nav>
      <main ref="detailPane" class="product-detail" tabindex="0" :aria-label="selectedGroup.name">
        <div class="receiver-strip" :class="{ running: receiver === 'running' }"><CheckCircleFilled v-if="receiver === 'running'" /><InfoCircleOutlined v-else /><span>{{ tr('receiver') }} · {{ runtimeLabel('channelStates', receiver) }}<small>{{ tr('receiverNote') }}</small></span><a-button type="link" @click="emit('collection')">{{ tr('collection') }}<RightOutlined /></a-button></div>
        <header class="product-heading"><span class="product-logo"><AgentProductLogo :product-id="selectedGroup.id" /></span><div><h2>{{ selectedGroup.name }}<a-tag :color="tagColor(status)">{{ statusLabel(status) }}</a-tag></h2><p>{{ tr(selected.hooks === 'native-plugin' ? 'nativeName' : 'hookName') }}</p></div></header>
        <nav v-if="selectedGroup.entries.length > 1" class="entry-navigation" :aria-label="tr('entry')"><button v-for="entry in selectedGroup.entries" :key="entry.id" :aria-pressed="entry.id === selected.id" :class="{ selected: entry.id === selected.id }" @click="selectedEntry = entry.id">{{ entryLabel(entry) }}<small>{{ statusLabel(entryStatus(entry)) }}</small></button></nav>
        <ol class="connection-steps" :aria-label="tr('steps')"><li v-for="step in steps" :key="step.key" :class="step.state"><CheckCircleFilled v-if="step.state === 'confirmed'" /><ExclamationCircleOutlined v-else-if="step.state === 'attention'" /><ClockCircleOutlined v-else /><strong>{{ tr('step.' + step.key) }}</strong><small>{{ step.label }}</small></li></ol>
        <section class="next-step" :class="{ attention: tone(status) === 'attention' }">
          <h3>{{ tr('next.' + nextKind + '.title') }}</h3><p>{{ tr('next.' + nextKind + '.body') }}</p>
          <ol v-if="nextKind === 'authorize' && needsCodexReview" class="authorization-steps"><li v-for="key in ['review','trust','session']" :key="key">{{ tr('codex.' + key) }}</li></ol>
          <a-space wrap>
            <a-button v-if="primaryAction === 'install' && canExecute" type="primary" :loading="busy === 'install' + selected.id" :disabled="isActionBlocked('install', selected.id)" @click="emit('action', 'install', selected.id)">{{ tr('install') }}</a-button>
            <a-button v-else-if="primaryAction === 'inspect' && canExecute" type="primary" :loading="busy === 'inspect' + selected.id" :disabled="isActionBlocked('inspect', selected.id)" @click="emit('action', 'inspect', selected.id)">{{ tr('inspect') }}</a-button>
            <a-button v-else-if="primaryAction === 'policy'" type="primary" @click="emit('policy')">{{ tr('policy') }}</a-button>
            <a-button v-else-if="primaryAction === 'collection'" type="primary" @click="emit('collection')">{{ tr('collection') }}</a-button>
            <a-button v-else type="primary" @click="guideOpen = true">{{ tr('guide') }}</a-button>
            <a-button v-if="primaryAction !== 'inspect' && canExecute" :loading="busy === 'inspect' + selected.id" :disabled="isActionBlocked('inspect', selected.id)" @click="emit('action', 'inspect', selected.id)">{{ tr('inspect') }}</a-button>
          </a-space>
        </section>
        <section class="current-status"><h4>{{ tr('current') }}</h4><dl><div><dt>{{ tr('hostVersion') }}</dt><dd>{{ observedHost?.host_version || tr('unknown') }}</dd></div><div><dt>{{ tr('latestEvent') }}</dt><dd>{{ recentArrival(selected.id) ? stamp(recentArrival(selected.id)) : tr('noEvent') }}</dd></div><div><dt>{{ tr('pluginVersion') }}</dt><dd>{{ observedHost?.plugin_version || tr('unknown') }}</dd></div><div><dt>{{ tr('reportedAt') }}</dt><dd>{{ stamp(connection(selected.id)?.observed_at) }}</dd></div></dl><p v-if="status === 'stale'" class="historical-note">{{ tr('historical') }}</p></section>
        <details :key="selected.id" class="workbench-disclosure"><summary>{{ tr('capability') }}</summary><p>{{ entryLabel(selected) }} · {{ selected.hook_os.join(' / ') }}</p><p>{{ runtimeLabel('', observedHost?.version_status) }}</p><AidrProductCapabilities :product-ids="capabilityIds" /><a-button v-if="canExecute && installation === 'installed'" :loading="busy === 'upgrade' + selected.id" :disabled="isActionBlocked('upgrade', selected.id)" @click="emit('action', 'upgrade', selected.id)">{{ tr('upgrade') }}</a-button></details>
        <details class="workbench-disclosure"><summary>{{ tr('diagnostics') }}</summary><slot name="diagnostics" /></details>
        <details class="workbench-disclosure"><summary>{{ tr('tasks') }}</summary><slot name="tasks" /></details>
      </main>
    </div>
    <a-modal v-model:open="guideOpen" :title="tr('guide')" :footer="null"><p>{{ tr('guidePath') }}</p><p>{{ selectedGroup.name }} · {{ entryLabel(selected) }}</p><ol class="guide-list"><li>{{ tr('guideDevice') }}</li><li>{{ needsCodexReview ? tr('codex.review') : tr('guideHost') }}</li><li>{{ tr('guideVerify') }}</li></ol><p>{{ tr('guideBoundary') }}</p><a-button @click="guideOpen = false">{{ tr('close') }}</a-button></a-modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircleFilled, ClockCircleOutlined, ExclamationCircleOutlined, InfoCircleOutlined, ReloadOutlined, RightOutlined, SettingOutlined } from '@ant-design/icons-vue'
import products from '../aidr-products.json'
import { groupProductEntries, productGroupId } from '../aidr-product-groups'
import AgentProductLogo from './AgentProductLogo.vue'
import AidrProductCapabilities from './AidrProductCapabilities.vue'
const props = defineProps({ state: Object, loading: Boolean, busy: String, canExecute: Boolean, isActionBlocked: { type: Function, required: true }, clientId: String })
const emit = defineEmits(['refresh','policy','collection','action'])
const { t, te, locale } = useI18n()
const tr = (key, values) => t('pluginWorkbench.' + key, values || {})
const groups = groupProductEntries(products.filter(p => p.hooks))
const selectedProduct = ref(groups[0].id), selectedEntry = ref(''), detailPane = ref(null), guideOpen = ref(false)
const now = ref(Date.now())
const timer = setInterval(() => { now.value = Date.now() }, 5000)
onBeforeUnmount(() => clearInterval(timer))
const parse = value => value ? Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z') : NaN
const fresh = (value, seconds) => Number.isFinite(parse(value)) && now.value - parse(value) <= seconds * 1000 && now.value - parse(value) >= -5000
const stamp = value => Number.isFinite(parse(value)) ? new Date(parse(value)).toLocaleString(locale.value) : tr('unknown')
const connection = id => props.state?.hook_connections?.find(item => item.agent === id)
const currentReport = computed(() => props.state && !props.state.stale && fresh(props.state.reported_at, 30))
const hostFresh = id => currentReport.value && !connection(id)?.stale && fresh(connection(id)?.observed_at, 480)
const recentArrival = id => fresh(connection(id)?.event_received_at, 900) ? connection(id).event_received_at : null
const selectedGroup = computed(() => groups.find(group => group.id === selectedProduct.value) || groups[0])
const selected = computed(() => selectedGroup.value.entries.find(entry => entry.id === selectedEntry.value) || selectedGroup.value.entries[0])
const observedHost = computed(() => props.state?.report?.hosts?.find(host => host.agent === selected.value.id))
const capabilityIds = computed(() => products.filter(p => productGroupId(p.id) === selectedGroup.value.id).map(p => p.id))
const receiver = computed(() => currentReport.value && fresh(props.state?.channels?.hooks?.report?.reported_at, 30) ? props.state.channels.hooks.report.state : 'unknown')
const installation = computed(() => hostFresh(selected.value.id) ? connection(selected.value.id)?.installation : 'unknown')
const runtimeLabel = (section, value) => { const key = `agentRuntimeGovernance.${section ? section + '.' : ''}${value || 'unknown'}`; return te(key) ? t(key) : tr('unknown') }
const entryLabel = entry => t('agentRuntimeGovernance.catalog.entries.' + entry.entry)
function entryStatus(entry) {
  const c = connection(entry.id)
  if (!props.state) return 'unknown'
  if (props.state.target_configured && c?.requested === false) return 'not_requested'
  if (!currentReport.value || c?.stale) return 'stale'
  if (!hostFresh(entry.id)) return 'unknown'
  if (c.installation === 'host_missing') return 'host_missing'
  if (['review_required','admin_required','cancelled','failed','interrupted'].includes(c.authorization)) return 'authorization'
  if (c.installation === 'not_installed') return 'not_installed'
  if (c.enabled === false) return 'disabled'
  if (recentArrival(entry.id)) return 'received'
  if (c.installation === 'installed' && c.enabled === true) return 'waiting'
  return 'unknown'
}
const needsCodexReview = computed(() => selected.value.id === 'codex' && connection(selected.value.id)?.authorization === 'review_required')
const status = computed(() => entryStatus(selected.value))
const groupStatus = group => { const states = [...new Set(group.entries.map(entryStatus))]; return states.length === 1 ? states[0] : 'mixed' }
const statusLabel = value => tr('states.' + value)
const tone = value => value === 'received' ? 'success' : ['authorization','disabled','not_installed'].includes(value) ? 'attention' : 'neutral'
const tagColor = value => tone(value) === 'success' ? 'green' : tone(value) === 'attention' ? 'orange' : undefined
const steps = computed(() => {
  const c = hostFresh(selected.value.id) ? connection(selected.value.id) : null
  const step = (key, value, confirmed, attention = []) => ({ key, state: confirmed ? 'confirmed' : attention.includes(value) ? 'attention' : 'pending', label: key === 'installation' || key === 'authorization' ? runtimeLabel('connection.' + key + 'States', value) : key === 'enabled' ? runtimeLabel('connection', value === true ? 'enabledYes' : value === false ? 'enabledNo' : 'unknown') : value ? stamp(value) : tr('noEvent') })
  return [step('installation', c?.installation, c?.installation === 'installed', ['not_installed']), step('authorization', c?.authorization, ['authorized','managed'].includes(c?.authorization), ['review_required','admin_required','cancelled','failed','interrupted']), step('enabled', c?.enabled, c?.enabled === true, [false]), step('arrival', recentArrival(selected.value.id), !!recentArrival(selected.value.id))]
})
const nextKind = computed(() => {
  if (status.value === 'not_requested') return 'policy'
  if (['unknown','stale','mixed'].includes(status.value)) return 'inspect'
  if (status.value === 'host_missing') return 'host'
  if (status.value === 'authorization') return 'authorize'
  if (status.value === 'not_installed') return ['interface_compatible','adapter_available'].includes(observedHost.value?.version_status) ? 'install' : 'inspect'
  if (status.value === 'disabled') return 'enable'
  if (receiver.value !== 'running') return 'receiver'
  return status.value === 'received' ? 'received' : 'verify'
})
const primaryAction = computed(() => ({ policy: 'policy', inspect: 'inspect', install: 'install', receiver: 'collection', received: 'collection' }[nextKind.value] || 'guide'))
function selectGroup(group) { selectedProduct.value = group.id; selectedEntry.value = ''; if (detailPane.value) detailPane.value.scrollTop = 0 }
watch(() => props.clientId, () => { selectedProduct.value = groups[0].id; selectedEntry.value = ''; guideOpen.value = false })
</script>

<style scoped>
.plugin-workbench{display:flex;flex-direction:column;height:100%;min-height:0;color:#243348;overflow-wrap:anywhere}
.workbench-toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex:none;padding:14px 4px 20px}.workbench-toolbar h3{font-size:21px;margin:0 0 5px}.workbench-toolbar p{margin:0;color:#76869b;font-size:13px}.workbench-alerts{flex:none;max-height:25%;overflow:auto}.workbench-alerts:empty{display:none}.workbench-alerts :deep(.ant-alert){margin-bottom:10px}.workbench-loading{display:grid;place-content:center;flex:1;gap:16px;color:#76869b}.workbench-columns{display:grid;grid-template-columns:265px minmax(0,1fr);flex:1;min-height:0;border-top:1px solid #e3e9f0}
.product-navigation{overflow-y:auto;overscroll-behavior:contain;border-right:1px solid #e3e9f0;padding:18px 14px 18px 0}.product-navigation button{display:flex;align-items:center;gap:14px;width:100%;padding:18px 12px;text-align:left;background:white;border:0;border-left:3px solid transparent;border-bottom:1px solid #eef1f5;border-radius:5px;cursor:pointer;color:inherit}.product-navigation button.selected{background:#edf4ff;border-left-color:#245ef5}.product-navigation button:hover{background:#f4f7fc}.product-logo{display:inline-flex;flex:none;width:38px;height:38px}.product-label{flex:1;min-width:0}.product-label strong{display:block;font-size:16px}.product-label small{display:block;font-size:12px;color:#76869b;margin-top:6px}.product-label small.success{color:#238653}.product-label small.attention{color:#b97819}.product-navigation .anticon{font-size:11px;color:#75869c}
.product-detail{overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;min-height:0;padding:20px 0 28px 24px}.receiver-strip{display:flex;align-items:center;gap:12px;padding:12px 16px;border:1px solid #e3e9f0;border-radius:6px;background:#f7f9fc;color:#60738b;font-size:13px}.receiver-strip.running{background:#f2faf7;border-color:#cfe8dc}.receiver-strip>.anticon{font-size:18px}.receiver-strip.running>.anticon{color:#238653}.receiver-strip>span:not(.anticon){flex:1}.receiver-strip small{display:block;font-size:11px;color:#73879a;margin-top:4px}.receiver-strip :deep(.ant-btn){padding:0;height:auto;white-space:normal}.product-heading{display:flex;align-items:center;gap:16px;margin:26px 0 22px}.product-heading .product-logo{width:48px;height:48px}.product-heading h2{display:flex;align-items:center;flex-wrap:wrap;gap:12px;font-size:25px;line-height:1.4;margin:0 0 5px}.product-heading p{font-size:13px;color:#76869b;margin:0}
.entry-navigation{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}.entry-navigation button{border:1px solid #dce4ed;border-radius:5px;background:white;padding:8px 12px;text-align:left;cursor:pointer;font-size:13px;color:#526873}.entry-navigation button.selected{border-color:#245ef5;color:#245ef5;background:#f4f8ff}.entry-navigation small{display:block;color:#76869b;font-size:11px;margin-top:3px}
.connection-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:0;margin:0 0 24px;list-style:none}.connection-steps li{position:relative;text-align:center;min-width:0}.connection-steps li:not(:last-child):after{content:'';position:absolute;top:12px;left:calc(50% + 20px);width:calc(100% - 30px);border-top:1px solid #dce4ed}.connection-steps .anticon{font-size:25px;color:#9cacc0;background:#fff;position:relative;z-index:1}.connection-steps .confirmed .anticon{color:#238653}.connection-steps .attention .anticon{color:#c38b22}.connection-steps strong{display:block;font-size:13px;margin:10px 0 4px;font-weight:500}.connection-steps small{display:block;font-size:11px;color:#7c8ca2;line-height:1.6}
.next-step{background:#f4f8ff;border:1px solid #e3edff;border-radius:7px;padding:20px}.next-step h3{font-size:18px;margin:0 0 8px}.next-step>p{font-size:13px;color:#637996;line-height:1.8;margin:0 0 18px}.authorization-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;padding:0 0 0 20px;margin:20px 0 24px;font-size:13px;line-height:1.8}.authorization-steps li::marker{color:#245ef5;font-weight:600}.next-step :deep(.ant-btn){height:auto;min-height:34px;white-space:normal}.current-status{margin:23px 0 19px}.current-status h4{font-size:14px;margin:0 0 12px}.current-status dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 26px;margin:0;font-size:12px}.current-status dl>div{display:grid;grid-template-columns:95px minmax(0,1fr);gap:10px;align-items:baseline}.current-status dt{color:#7c8ca2}.current-status dd{margin:0;color:#415672}.historical-note{font-size:12px;color:#b97819;margin-top:12px}.workbench-disclosure{border-top:1px solid #e3e9f0;padding:15px 0;font-size:13px}.workbench-disclosure>summary{cursor:pointer;color:#415672;font-weight:500}.workbench-disclosure>p{margin-top:12px;color:#75869c}.guide-list{padding-left:20px;line-height:1.8}.guide-list li{margin:14px 0}button:focus-visible,summary:focus-visible{outline:2px solid #245ef5;outline-offset:2px}
@media(max-width:1000px){.workbench-columns{grid-template-columns:215px minmax(0,1fr)}.product-detail{padding-left:18px}.product-navigation{padding-right:10px}.product-navigation button{gap:9px;padding:16px 8px}.product-label strong{font-size:14px}.product-logo{width:30px;height:30px}.current-status dl{grid-template-columns:1fr}.authorization-steps{grid-template-columns:1fr;gap:8px}}
@media(max-width:650px){.workbench-toolbar{align-items:flex-start;flex-wrap:wrap;padding-bottom:12px;gap:8px}.workbench-toolbar h3{font-size:18px}.workbench-toolbar p{font-size:12px;line-height:1.5}.workbench-toolbar :deep(.ant-btn){font-size:12px;padding:4px 8px}.workbench-columns{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr)}.product-navigation{display:flex;overflow-x:auto;overflow-y:hidden;gap:5px;padding:8px 0;border-right:0;border-bottom:1px solid #e3e9f0}.product-navigation button{width:170px;flex:none;padding:10px 8px;gap:8px}.product-navigation button>.anticon{display:none}.product-detail{padding:16px 0}.product-heading{margin:20px 0}.product-heading h2{font-size:22px}.receiver-strip{gap:8px;padding:10px;flex-wrap:wrap}.connection-steps{gap:5px}.connection-steps strong{font-size:12px}.next-step{padding:16px}.next-step h3{font-size:16px}.current-status dl>div{grid-template-columns:90px minmax(0,1fr)}}
</style>
