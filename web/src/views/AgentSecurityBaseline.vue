<template>
  <section class="baseline-page">
    <a-page-header :title="t(`${messageKey}.title`)" :sub-title="t(`${messageKey}.subtitle`)" />

    <a-alert
      type="info"
      show-icon
      :message="t(`${messageKey}.scopeTitle`)"
      :description="t(`${messageKey}.scopeDescription`)"
    />

    <a-spin :spinning="loading">
      <a-result v-if="error" status="error" :title="t(`${messageKey}.loadFailed`)" :sub-title="error" />
      <a-card v-else-if="baseline" class="baseline-card">
        <a-descriptions bordered :column="1">
          <a-descriptions-item :label="t('agentSecurityBaseline.feature')">
            {{ baseline.feature }}
          </a-descriptions-item>
          <a-descriptions-item :label="t('agentSecurityBaseline.version')">
            {{ baseline.integration.tag }}
          </a-descriptions-item>
          <a-descriptions-item :label="t('agentSecurityBaseline.commit')">
            <a-typography-text code copyable>{{ baseline.integration.commit }}</a-typography-text>
          </a-descriptions-item>
          <a-descriptions-item :label="t('agentSecurityBaseline.license')">
            {{ baseline.integration.license.spdx }}
          </a-descriptions-item>
          <a-descriptions-item
            v-if="baseline.integration.license.attribution"
            :label="t('agentSecurityBaseline.attribution')"
          >
            {{ baseline.integration.license.attribution }}
          </a-descriptions-item>
          <a-descriptions-item :label="t('agentSecurityBaseline.runtimeFetch')">
            <a-tag color="green">{{ t('agentSecurityBaseline.disabled') }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item
            v-if="baseline.integration.agent_scan"
            :label="t('agentSecurityBaseline.providers')"
          >
            <a-space wrap>
              <a-tag v-for="provider in baseline.integration.agent_scan.provider_types" :key="provider">
                {{ provider }}
              </a-tag>
            </a-space>
          </a-descriptions-item>
          <a-descriptions-item :label="t('agentSecurityBaseline.limitations')">
            <ul class="limitation-list">
              <li v-for="item in baseline.integration.known_limitations" :key="item.code">
                {{ item[locale] || item['en-US'] }}
              </li>
            </ul>
          </a-descriptions-item>
        </a-descriptions>
      </a-card>
    </a-spin>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { getAgentSecurityBaseline, getRuntimeTraceBaseline } from '../api'

const route = useRoute()
const { t, locale } = useI18n()
const loading = ref(true)
const baseline = ref(null)
const error = ref('')
const isTrace = computed(() => route.meta.baselineKind === 'runtime-trace')
const messageKey = computed(() => isTrace.value ? 'runtimeTraceBaseline' : 'agentSecurityBaseline')

onMounted(async () => {
  try {
    baseline.value = isTrace.value
      ? await getRuntimeTraceBaseline()
      : await getAgentSecurityBaseline()
  } catch (requestError) {
    error.value = requestError.response?.data?.detail || t(`${messageKey.value}.loadFailed`)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.baseline-page {
  max-width: 1180px;
  margin: 0 auto;
}

.baseline-card {
  margin-top: 20px;
}

.limitation-list {
  margin: 0;
  padding-left: 20px;
}

.limitation-list li + li {
  margin-top: 6px;
}
</style>
