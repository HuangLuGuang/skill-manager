<template>
  <div class="aidr-architecture" role="group" :aria-label="t('docsArchitecture.title')">
    <div v-if="!expanded" class="aidr-title">
      <strong>{{ t('docsArchitecture.title') }}</strong>
      <button type="button" @click="open = true" :aria-label="t('docsArchitecture.expand')" :title="t('docsArchitecture.expand')"><FullscreenOutlined /></button>
    </div>
    <section class="aidr-zone">
      <header><strong>{{ t('docsArchitecture.endpoint') }}</strong><span>{{ t('docsArchitecture.endpointHint') }}</span></header>
      <div class="aidr-nodes three">
        <div v-for="channel in ['logs', 'hooks', 'system']" :key="channel" class="aidr-node">
          <strong>{{ t(`docsArchitecture.${channel}Title`) }}</strong>
          <p>{{ t(`docsArchitecture.${channel}Body`) }}</p>
          <small>{{ t(`docsArchitecture.${channel}Note`) }}</small>
        </div>
      </div>
    </section>
    <div class="aidr-connector">{{ t('docsArchitecture.collect') }}</div>
    <section class="aidr-zone client-zone">
      <header><strong>{{ t('docsArchitecture.client') }}</strong><span>{{ t('docsArchitecture.clientHint') }}</span></header>
      <div class="aidr-nodes two">
        <div v-for="part in ['local', 'control']" :key="part" class="aidr-node">
          <strong>{{ t(`docsArchitecture.${part}Title`) }}</strong><p>{{ t(`docsArchitecture.${part}Body`) }}</p>
        </div>
      </div>
    </section>
    <div class="aidr-transport"><span>{{ t('docsArchitecture.upload') }}</span><span>{{ t('docsArchitecture.return') }}</span></div>
    <section class="aidr-zone platform-zone">
      <header><strong>{{ t('docsArchitecture.platform') }}</strong><span>{{ t('docsArchitecture.platformHint') }}</span></header>
      <div class="aidr-nodes three">
        <div v-for="part in ['ingest', 'audit', 'policy']" :key="part" class="aidr-node">
          <strong>{{ t(`docsArchitecture.${part}Title`) }}</strong><p>{{ t(`docsArchitecture.${part}Body`) }}</p>
        </div>
      </div>
    </section>
    <section class="aidr-decision">
      <strong>{{ t('docsArchitecture.decisionTitle') }}</strong>
      <div class="aidr-decision-flow"><span>{{ t('docsArchitecture.decisionHost') }}</span><b aria-hidden="true">→</b><span>{{ t('docsArchitecture.decisionLocal') }}</span><b aria-hidden="true">→</b><span>{{ t('docsArchitecture.decisionResult') }}</span></div>
      <p>{{ t('docsArchitecture.decisionNote') }}</p>
    </section>
    <p class="aidr-boundary">{{ t('docsArchitecture.boundary') }}</p>
    <a-modal v-if="!expanded" v-model:open="open" :title="t('docsArchitecture.title')" :footer="null" width="min(1200px, calc(100vw - 32px))" :style="{ top: '24px' }" :body-style="{ maxHeight: 'calc(100dvh - 140px)', overflowY: 'auto' }" :destroy-on-close="true">
      <DocsAidrArchitecture expanded />
    </a-modal>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { FullscreenOutlined } from '@ant-design/icons-vue'

defineProps({ expanded: Boolean })
const { t } = useI18n()
const open = ref(false)
</script>

<style scoped>
.aidr-architecture { container-type: inline-size; box-sizing: border-box; margin: 24px 0; padding: 18px; color: #29445b; background: #f7f9fc; border: 1px solid #d5e0ea; border-radius: 14px; overflow-wrap: anywhere; }
.aidr-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; font-size: 16px; }
.aidr-title button { flex-shrink: 0; display: grid; place-items: center; width: 34px; height: 34px; color: #47647c; background: #fff; border: 1px solid #cfdae4; border-radius: 8px; cursor: pointer; }
.aidr-title button:focus-visible { outline: 3px solid #9ebbd3; outline-offset: 2px; }
.aidr-zone { padding: 16px; border: 1px solid #d5e0ea; border-top: 3px solid #78a4ca; border-radius: 10px; background: #fff; }
.aidr-zone header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 18px; margin-bottom: 12px; }
.aidr-zone header strong { font-size: 14px; }
.aidr-zone header span { color: #61788c; font-size: 12px; }
.aidr-nodes { display: grid; gap: 10px; }
.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.aidr-node { min-width: 0; padding: 13px; background: #f5f8fc; border: 1px solid #dbe4ec; border-radius: 8px; }
.aidr-node strong { font-size: 13px; }
.aidr-node p, .aidr-decision p { margin: 8px 0 0; color: #536d82; font-size: 12px; line-height: 1.7; }
.aidr-node small { display: block; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #c9d6e2; color: #516b80; font-size: 11px; line-height: 1.6; }
.client-zone { border-top-color: #64a599; }
.platform-zone { border-top-color: #7c88b9; }
.aidr-connector { padding: 14px 8px; text-align: center; color: #506e88; font-size: 12px; }
.aidr-transport { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 14px 0; font-size: 12px; line-height: 1.7; }
.aidr-transport span { padding: 10px 12px; background: #e9f2fa; border-radius: 8px; }
.aidr-transport span + span { color: #486e61; background: #eaf4ef; }
.aidr-decision { margin-top: 16px; padding: 16px; background: #fff8ec; border: 1px solid #e5d6b9; border-radius: 10px; font-size: 13px; }
.aidr-decision-flow { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; gap: 10px; align-items: center; margin-top: 12px; font-size: 12px; line-height: 1.6; }
.aidr-decision-flow span { padding: 10px; background: #fff; border: 1px solid #e6dcc9; border-radius: 6px; text-align: center; }
.aidr-boundary { margin: 14px 0 0; color: #596f81; font-size: 12px; line-height: 1.7; }
@container (max-width: 620px) {
  .three, .two, .aidr-transport, .aidr-decision-flow { grid-template-columns: 1fr; }
  .aidr-decision-flow b { text-align: center; transform: rotate(90deg); }
  .aidr-zone { padding: 12px; }
}
</style>
