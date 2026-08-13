<template>
  <div class="docs-page">
    <header class="docs-header">
      <button class="brand-button" type="button" @click="router.push('/docs')">
        <img :src="logoUrl" class="docs-logo" alt="" />
        <span class="brand-copy">
          <span class="brand-name">{{ t('app.name') }}</span>
          <span class="brand-docs">{{ t('docsUi.docs') }}</span>
        </span>
      </button>

      <div class="header-search">
        <SearchOutlined class="search-icon" />
        <input
          v-model="searchQuery"
          type="search"
          :aria-label="t('docsUi.search')"
          :placeholder="t('docsUi.searchPlaceholder')"
          @focus="searchFocused = true"
          @keydown.esc="closeSearch"
        />
        <div v-if="searchFocused && searchQuery.trim()" class="search-results">
          <button
            v-for="result in searchResults"
            :key="result.slug"
            type="button"
            @mousedown.prevent="navigateToArticle(result.slug)"
          >
            <span>{{ result.title }}</span>
            <small>{{ result.summary }}</small>
          </button>
          <div v-if="!searchResults.length" class="search-empty">{{ t('docsUi.noSearchResults') }}</div>
        </div>
      </div>

      <div class="header-actions">
        <a-button v-if="docsAssistantConfig.enabled" class="ask-ai-button" @click="assistantOpen = true">
          <RobotOutlined />
          {{ t('docsAssistant.askAi') }}
        </a-button>
        <a-select
          v-model:value="locale"
          class="docs-language"
          :aria-label="t('language.label')"
          @change="handleLocaleChange"
        >
          <a-select-option value="zh-CN">{{ t('language.chinese') }}</a-select-option>
          <a-select-option value="en-US">{{ t('language.english') }}</a-select-option>
        </a-select>
        <a-button class="back-button" @click="router.push('/dashboard')">
          <ArrowLeftOutlined />
          {{ t('docsUi.backToPlatform') }}
        </a-button>
        <a-button class="mobile-menu-button" :aria-label="t('docsUi.menu')" @click="mobileNavOpen = true">
          <MenuOutlined />
        </a-button>
      </div>
    </header>

    <div class="docs-layout">
      <aside class="docs-sidebar">
        <DocsNavigation :groups="content.groups" :current-slug="currentSlug" @navigate="navigateToArticle" />
      </aside>

      <main ref="articleScroller" class="docs-article-scroll" @click="searchFocused = false">
        <article class="docs-article">
          <div class="article-heading">
            <div class="eyebrow">{{ article.eyebrow }}</div>
            <h1>{{ article.title }}</h1>
            <p>{{ article.summary }}</p>
          </div>

          <div v-if="article.scenario" class="scenario-brief" :aria-label="article.scenario.label">
            <div class="scenario-brief-mark"><SafetyCertificateOutlined /></div>
            <div v-for="item in article.scenario.items" :key="item.label" class="scenario-brief-item">
              <small>{{ item.label }}</small>
              <strong>{{ item.value }}</strong>
            </div>
          </div>

          <div v-if="article.roles?.length" class="role-grid">
            <button v-for="role in article.roles" :key="role.title" type="button" @click="navigateToArticle(role.slug)">
              <span class="role-mark"><UserOutlined /></span>
              <strong>{{ role.title }}</strong>
              <span>{{ role.text }}</span>
              <ArrowRightOutlined class="role-arrow" />
            </button>
          </div>

          <section v-for="section in article.sections" :id="section.id" :key="section.id" class="article-section">
            <h2><a :href="`#${section.id}`" @click.prevent="scrollToSection(section.id)">{{ section.title }}</a></h2>

            <p v-for="paragraph in section.paragraphs || []" :key="paragraph">{{ paragraph }}</p>

            <ul v-if="section.bullets?.length" class="doc-list">
              <li v-for="bullet in section.bullets" :key="bullet">{{ bullet }}</li>
            </ul>

            <div v-if="section.flow?.length" class="scenario-flow" role="list">
              <template v-for="(node, index) in section.flow" :key="`${section.id}-flow-${index}`">
                <div :class="['scenario-flow-node', node.type || 'default']" role="listitem">
                  <small>{{ node.label }}</small>
                  <strong>{{ node.value }}</strong>
                </div>
                <ArrowRightOutlined v-if="index < section.flow.length - 1" class="scenario-flow-arrow" />
              </template>
            </div>

            <div v-if="section.diagram === 'governance'" class="governance-diagram">
              <div v-for="(label, index) in governanceLabels" :key="label" class="governance-step">
                <span>{{ index + 1 }}</span>
                <strong>{{ label }}</strong>
              </div>
            </div>

            <div
              v-if="section.diagram === 'skill-scan-logic'"
              :class="['skill-scan-logic', { fullscreen: scanLogicFullscreen }]"
              :aria-label="scanLogicLabels.title"
              :aria-modal="scanLogicFullscreen || undefined"
              :role="scanLogicFullscreen ? 'dialog' : 'group'"
            >
              <button
                type="button"
                class="diagram-fullscreen-button"
                :aria-label="scanLogicFullscreen ? scanLogicLabels.exitFullscreen : scanLogicLabels.enterFullscreen"
                :title="scanLogicFullscreen ? scanLogicLabels.exitFullscreen : scanLogicLabels.enterFullscreen"
                @click="scanLogicFullscreen = !scanLogicFullscreen"
              >
                <FullscreenExitOutlined v-if="scanLogicFullscreen" />
                <FullscreenOutlined v-else />
              </button>

              <div class="scan-logic-start">
                <small>{{ scanLogicLabels.input }}</small>
                <strong>{{ scanLogicLabels.pending }}</strong>
                <span>{{ scanLogicLabels.pendingDetail }}</span>
              </div>

              <div class="scan-logic-connector"><span>{{ scanLogicLabels.dispatch }}</span></div>

              <div class="scan-logic-stage">
                <div class="scan-logic-heading"><strong>{{ scanLogicLabels.deterministic }}</strong><span>{{ scanLogicLabels.deterministicDetail }}</span></div>
                <div class="scan-analyzer-grid">
                  <div class="required"><FileSearchOutlined /><strong>{{ scanLogicLabels.scanner }}</strong><span>{{ scanLogicLabels.always }}</span></div>
                  <div><SafetyCertificateOutlined /><strong>{{ scanLogicLabels.rules }}</strong><span>{{ scanLogicLabels.selected }}</span></div>
                  <div><SearchOutlined /><strong>{{ scanLogicLabels.deep }}</strong><span>{{ scanLogicLabels.availableSelected }}</span></div>
                  <div><DesktopOutlined /><strong>Sandbox</strong><span>{{ scanLogicLabels.selectedOrPolicy }}</span></div>
                </div>
              </div>

              <div class="scan-logic-connector"><span>{{ scanLogicLabels.interimRisk }}</span></div>

              <div class="scan-policy-row">
                <div><small>{{ scanLogicLabels.policyCheck }}</small><strong>{{ scanLogicLabels.sandboxRequired }}</strong></div>
                <ArrowRightOutlined />
                <div class="decision"><small>{{ scanLogicLabels.ifMatched }}</small><strong>{{ scanLogicLabels.runSandbox }}</strong></div>
                <ArrowRightOutlined />
                <div><small>{{ scanLogicLabels.merge }}</small><strong>{{ scanLogicLabels.allFindings }}</strong></div>
              </div>

              <div class="scan-logic-connector"><span>{{ scanLogicLabels.classify }}</span></div>

              <div class="scan-logic-stage classification-stage">
                <div class="scan-logic-heading"><strong>{{ scanLogicLabels.classification }}</strong><span>{{ scanLogicLabels.mapping }}</span></div>
                <div class="scan-classification-grid">
                  <div class="blocked"><strong>{{ scanLogicLabels.blocking }}</strong><span>{{ scanLogicLabels.blockingDetail }}</span></div>
                  <div class="suspicious"><strong>{{ scanLogicLabels.suspicious }}</strong><span>{{ scanLogicLabels.suspiciousDetail }}</span></div>
                  <div class="noise"><strong>{{ scanLogicLabels.noise }}</strong><span>{{ scanLogicLabels.noiseDetail }}</span></div>
                </div>
                <div class="scan-deterministic-result"><span>{{ scanLogicLabels.mode }}</span><strong>{{ scanLogicLabels.preLlmRisk }}</strong></div>
              </div>

              <div class="scan-logic-connector"><span>{{ scanLogicLabels.llmRequested }}</span></div>

              <div class="scan-llm-row">
                <div class="scan-llm-card"><ApiOutlined /><span><small>{{ scanLogicLabels.optional }}</small><strong>{{ scanLogicLabels.llm }}</strong></span></div>
                <div class="scan-llm-guard"><SafetyCertificateOutlined /><span><strong>{{ scanLogicLabels.guard }}</strong><small>{{ scanLogicLabels.guardDetail }}</small></span></div>
                <div class="scan-final-risk"><small>{{ scanLogicLabels.reconcile }}</small><strong>benign / suspicious / malicious</strong></div>
              </div>

              <div class="scan-logic-connector"><span>{{ scanLogicLabels.admissionPolicy }}</span></div>

              <div class="scan-admission-grid">
                <div class="approved"><CheckCircleOutlined /><strong>APPROVED</strong><span>{{ scanLogicLabels.approved }}</span></div>
                <div class="vetted"><UserOutlined /><strong>VETTED</strong><span>{{ scanLogicLabels.vetted }}</span></div>
                <div class="rejected"><WarningOutlined /><strong>REJECTED</strong><span>{{ scanLogicLabels.rejected }}</span></div>
              </div>
            </div>

            <div v-if="section.diagram === 'platform'" class="platform-map">
              <button
                v-for="pillar in platformPillars"
                :key="pillar.title"
                type="button"
                class="platform-pillar"
                @click="navigateToArticle(pillar.slug)"
              >
                <span class="platform-pillar-icon"><component :is="pillar.icon" /></span>
                <span class="platform-pillar-copy"><strong>{{ pillar.title }}</strong><small>{{ pillar.summary }}</small></span>
                <ArrowRightOutlined />
              </button>
              <div class="platform-foundation">
                <span>{{ platformFoundation.credentials }}</span>
                <span>{{ platformFoundation.policy }}</span>
                <span>{{ platformFoundation.audit }}</span>
              </div>
            </div>

            <div
              v-if="section.diagram === 'architecture'"
              :class="['system-architecture', { fullscreen: architectureFullscreen }]"
              :aria-label="architectureLabels.title"
              :aria-modal="architectureFullscreen || undefined"
              :role="architectureFullscreen ? 'dialog' : 'group'"
            >
              <button
                type="button"
                class="architecture-fullscreen-button"
                :aria-label="architectureFullscreen ? architectureLabels.exitFullscreen : architectureLabels.enterFullscreen"
                :title="architectureFullscreen ? architectureLabels.exitFullscreen : architectureLabels.enterFullscreen"
                @click="architectureFullscreen = !architectureFullscreen"
              >
                <FullscreenExitOutlined v-if="architectureFullscreen" />
                <FullscreenOutlined v-else />
              </button>

              <div class="architecture-callers">
                <div class="architecture-band-label"><strong>{{ architectureLabels.callers }}</strong></div>
                <div class="architecture-caller-grid">
                  <div><UserOutlined /><span>{{ architectureLabels.admins }}</span></div>
                  <div><FileSearchOutlined /><span>{{ architectureLabels.scanner }}</span></div>
                  <div><DesktopOutlined /><span>{{ architectureLabels.agents }}</span></div>
                  <div><ApiOutlined /><span>{{ architectureLabels.modelApps }}</span></div>
                  <div><SafetyCertificateOutlined /><span>{{ architectureLabels.mcpClients }}</span></div>
                </div>
              </div>

              <div class="architecture-ingress-link"><span>{{ architectureLabels.secureTraffic }}</span></div>

              <div class="architecture-ingress">
                <div><small>{{ architectureLabels.unifiedEntry }}</small><strong>Nginx</strong></div>
                <div class="architecture-ingress-roles">
                  <span v-for="role in architectureLabels.ingressRoles" :key="role">{{ role }}</span>
                </div>
              </div>

              <div class="architecture-control-plane">
                <div class="architecture-plane-heading">
                  <strong>{{ architectureLabels.controlPlane }}</strong>
                  <small>{{ architectureLabels.controlSummary }}</small>
                </div>
                <div class="architecture-control-grid">
                  <div><strong>{{ architectureLabels.identity }}</strong><span>{{ architectureLabels.identityDetail }}</span></div>
                  <div><strong>{{ architectureLabels.policy }}</strong><span>{{ architectureLabels.policyDetail }}</span></div>
                  <div><strong>{{ architectureLabels.console }}</strong><span>{{ architectureLabels.consoleDetail }}</span></div>
                  <div><strong>{{ architectureLabels.orchestration }}</strong><span>{{ architectureLabels.orchestrationDetail }}</span></div>
                </div>
              </div>

              <div class="architecture-plane-link"><span>{{ architectureLabels.policyEnforcement }}</span></div>

              <div class="architecture-runtime-plane">
                <div class="architecture-plane-heading">
                  <strong>{{ architectureLabels.runtimePlane }}</strong>
                  <small>{{ architectureLabels.runtimeSummary }}</small>
                </div>
                <div class="architecture-domain-grid">
                  <div class="architecture-domain skill-domain">
                    <div class="architecture-domain-head"><FileSearchOutlined /><span><small>SKILL</small><strong>{{ architectureLabels.skillDomain }}</strong></span></div>
                    <p>{{ architectureLabels.skillFlow }}</p>
                    <div class="architecture-domain-output">{{ architectureLabels.skillOutput }}</div>
                  </div>
                  <div class="architecture-domain client-domain">
                    <div class="architecture-domain-head"><DesktopOutlined /><span><small>AGENT / CLIENT</small><strong>{{ architectureLabels.clientDomain }}</strong></span></div>
                    <p>{{ architectureLabels.clientFlow }}</p>
                    <div class="architecture-domain-output">{{ architectureLabels.clientOutput }}</div>
                  </div>
                  <div class="architecture-domain model-domain">
                    <div class="architecture-domain-head"><ApiOutlined /><span><small>MODEL</small><strong>{{ architectureLabels.modelDomain }}</strong></span></div>
                    <p>{{ architectureLabels.modelFlow }}</p>
                    <div class="architecture-domain-output">{{ architectureLabels.modelOutput }}</div>
                  </div>
                  <div class="architecture-domain mcp-domain">
                    <div class="architecture-domain-head"><SafetyCertificateOutlined /><span><small>MCP</small><strong>{{ architectureLabels.mcpDomain }}</strong></span></div>
                    <p>{{ architectureLabels.mcpFlow }}</p>
                    <div class="architecture-domain-output">{{ architectureLabels.mcpOutput }}</div>
                  </div>
                </div>
              </div>

              <div class="architecture-foundation-link"><span>{{ architectureLabels.evidenceWrite }}</span></div>

              <div class="architecture-foundation">
                <div class="architecture-plane-heading">
                  <strong>{{ architectureLabels.foundation }}</strong>
                  <small>{{ architectureLabels.foundationSummary }}</small>
                </div>
                <div class="architecture-foundation-grid">
                  <div><strong>{{ architectureLabels.registry }}</strong><span>{{ architectureLabels.registryDetail }}</span></div>
                  <div><strong>{{ architectureLabels.traces }}</strong><span>{{ architectureLabels.tracesDetail }}</span></div>
                  <div><strong>{{ architectureLabels.audit }}</strong><span>{{ architectureLabels.auditDetail }}</span></div>
                </div>
              </div>

              <div class="architecture-dependencies">
                <span>{{ architectureLabels.dependencies }}</span>
                <div><b>Sandbox / nsjail</b><b>{{ architectureLabels.upstreamModels }}</b><b>{{ architectureLabels.mcpServers }}</b></div>
              </div>
            </div>

            <div v-if="section.diagram === 'docker'" class="docker-topology">
              <div class="topology-zone topology-entry">
                <div class="topology-zone-label"><span>ENTRY</span><strong>{{ dockerLabels.entry }}</strong></div>
                <div class="topology-entry-nodes">
                  <div><DesktopOutlined /><span>{{ dockerLabels.console }}</span></div>
                  <div><FileSearchOutlined /><span>{{ dockerLabels.agents }}</span></div>
                  <div><ApiOutlined /><span>{{ dockerLabels.callers }}</span></div>
                </div>
              </div>

              <div class="topology-downlink"><span>{{ dockerLabels.httpTraffic }}</span></div>

              <div class="topology-ingress">
                <div><small>{{ dockerLabels.publicIngress }}</small><strong>Nginx</strong></div>
                <span>{{ dockerLabels.nginxRole }}</span>
              </div>

              <div class="topology-split"><i></i><span>{{ dockerLabels.routeTraffic }}</span><i></i></div>

              <div class="topology-zone topology-control">
                <div class="topology-zone-label"><span>APP NETWORK</span><strong>{{ dockerLabels.controlPlane }}</strong></div>
                <div class="topology-service frontend-service">
                  <small>{{ dockerLabels.webConsole }}</small><strong>Frontend</strong><span>{{ dockerLabels.frontendRole }}</span>
                </div>
                <div class="topology-service backend-service">
                  <small>{{ dockerLabels.governanceApi }}</small><strong>Backend <b>:8000</b></strong><span>{{ dockerLabels.backendRole }}</span>
                </div>
              </div>

              <div class="topology-backend-links">
                <span>{{ dockerLabels.sandboxLink }}</span>
                <span>{{ dockerLabels.volumeLink }}</span>
              </div>

              <div class="topology-bottom">
                <div class="topology-zone topology-execution">
                  <div class="topology-zone-label"><span>SANDBOX-CONTROL</span><strong>{{ dockerLabels.executionPlane }}</strong></div>
                  <div class="topology-service sandbox-service">
                    <small>{{ dockerLabels.backendOnly }}</small><strong>Sandbox <b>:8194</b></strong><span>{{ dockerLabels.sandboxRole }}</span>
                  </div>
                </div>
                <div class="topology-zone topology-data">
                  <div class="topology-zone-label"><span>PERSISTENCE</span><strong>{{ dockerLabels.dataPlane }}</strong></div>
                  <div class="docker-volumes">
                    <span v-for="volume in dockerVolumes" :key="volume">{{ volume }}</span>
                  </div>
                </div>
              </div>

              <div class="topology-note"><InfoCircleOutlined />{{ dockerLabels.boundaryNote }}</div>
            </div>

            <div v-if="section.steps?.length" class="doc-steps">
              <div v-for="(step, index) in section.steps" :key="`${section.id}-${index}`" class="doc-step">
                <div class="step-number">{{ index + 1 }}</div>
                <div class="step-content">
                  <h3>{{ step.title }}</h3>
                  <p>{{ step.body }}</p>
                  <CodeBlock v-if="step.code" :code="step.code" @copy="copyCode" />
                  <div v-if="step.expected" class="expected-result">
                    <CheckCircleOutlined />
                    <div><strong>{{ t('docsUi.expectedResult') }}</strong><span>{{ step.expected }}</span></div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="section.table" class="doc-table-wrap">
              <table class="doc-table">
                <thead><tr><th v-for="column in section.table.columns" :key="column">{{ column }}</th></tr></thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in section.table.rows" :key="rowIndex">
                    <td v-for="(cell, cellIndex) in row" :key="cellIndex">
                      <button
                        v-if="isLinkCell(cell)"
                        type="button"
                        class="table-doc-link"
                        @click="router.push(cell.path)"
                      >
                        <span>{{ cell.label }}</span>
                        <ArrowRightOutlined />
                      </button>
                      <template v-else>{{ cell }}</template>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <CodeBlock v-if="section.code" :code="section.code" @copy="copyCode" />

            <div v-if="section.callout" :class="['doc-callout', section.callout.type]">
              <InfoCircleOutlined v-if="section.callout.type !== 'warning'" />
              <WarningOutlined v-else />
              <div><strong>{{ section.callout.title }}</strong><p>{{ section.callout.body }}</p></div>
            </div>

            <figure v-if="section.image && !failedImages.has(section.image.name)" class="doc-figure">
              <img
                :src="screenshotUrl(section.image.name)"
                :alt="section.image.alt"
                loading="lazy"
                @error="markImageFailed(section.image.name)"
                @click="openImage(section.image)"
              />
              <figcaption>{{ section.image.caption }}</figcaption>
            </figure>

            <a-button v-if="section.link" type="primary" ghost class="feature-link" @click="router.push(section.link.path)">
              {{ section.link.label }}
              <ArrowRightOutlined />
            </a-button>

            <a
              v-if="section.download"
              class="example-download"
              :href="section.download.path"
              :download="section.download.filename || true"
            >
              <DownloadOutlined />
              <span><strong>{{ section.download.label }}</strong><small>{{ section.download.hint }}</small></span>
              <ArrowRightOutlined />
            </a>
          </section>

          <nav class="article-pagination" :aria-label="t('docsUi.docs')">
            <button v-if="previousArticle" type="button" @click="navigateToArticle(previousArticle.slug)">
              <small>{{ t('docsUi.previous') }}</small><span><ArrowLeftOutlined /> {{ previousArticle.title }}</span>
            </button>
            <span v-else></span>
            <button v-if="nextArticle" type="button" class="next" @click="navigateToArticle(nextArticle.slug)">
              <small>{{ t('docsUi.next') }}</small><span>{{ nextArticle.title }} <ArrowRightOutlined /></span>
            </button>
          </nav>
        </article>
      </main>

      <aside class="docs-toc">
        <div class="toc-label">{{ t('docsUi.onThisPage') }}</div>
        <a v-for="section in article.sections" :key="section.id" :href="`#${section.id}`" @click.prevent="scrollToSection(section.id)">
          {{ section.title }}
        </a>
      </aside>
    </div>

    <a-drawer v-model:open="mobileNavOpen" placement="left" :title="t('docsUi.menu')" width="300">
      <DocsNavigation :groups="content.groups" :current-slug="currentSlug" @navigate="navigateFromMobile" />
    </a-drawer>

    <a-modal v-model:open="imagePreviewOpen" :footer="null" width="min(1180px, 94vw)" centered>
      <img v-if="previewImage" :src="screenshotUrl(previewImage.name)" :alt="previewImage.alt" class="preview-image" />
    </a-modal>

    <DocsAssistantPanel
      :open="assistantOpen"
      :config="docsAssistantConfig"
      :content="content"
      :locale="locale"
      :current-slug="currentSlug"
      @close="assistantOpen = false"
      @navigate="navigateFromAssistant"
    />

    <div v-if="copiedVisible" class="copy-toast"><CheckOutlined /> {{ t('docsUi.copied') }}</div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  DesktopOutlined,
  DownloadOutlined,
  FileSearchOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  InfoCircleOutlined,
  MenuOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  UserOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'

import { getDocsAssistantConfig, updateMyLocale } from '../api'
import DocsAssistantPanel from '../components/DocsAssistantPanel.vue'
import { docsArticleOrder, docsContent } from '../docs/content'
import { setLocale } from '../i18n'
import { useLocaleText } from '../i18n/useLocaleText'

defineProps({
  logoUrl: { type: String, default: '/logo.png' },
})

const router = useRouter()
const route = useRoute()
const { t, locale } = useI18n()
const { text } = useLocaleText()
const mobileNavOpen = ref(false)
const articleScroller = ref(null)
const searchQuery = ref('')
const searchFocused = ref(false)
const copiedVisible = ref(false)
const copyTimer = ref(null)
const failedImages = ref(new Set())
const imagePreviewOpen = ref(false)
const previewImage = ref(null)
const assistantOpen = ref(false)
const architectureFullscreen = ref(false)
const scanLogicFullscreen = ref(false)
const docsAssistantConfig = ref({ enabled: false, common_questions: [], max_context_sections: 4 })

const DocsNavigation = defineComponent({
  props: {
    groups: { type: Array, required: true },
    currentSlug: { type: String, required: true },
  },
  emits: ['navigate'],
  setup(props, { emit }) {
    return () => h('nav', { class: 'docs-nav' }, props.groups.map(group => {
      let previousSubgroup = null
      const items = group.items.flatMap(item => {
        const nodes = []
        if (item.subgroup && item.subgroup !== previousSubgroup) {
          nodes.push(h('div', {
            class: 'nav-subgroup-title',
            key: `${group.title}-${item.subgroup}`,
          }, item.subgroup))
        }
        previousSubgroup = item.subgroup || null
        nodes.push(h('button', {
          type: 'button',
          class: ['nav-item', item.subgroup ? 'nested' : '', item.slug === props.currentSlug ? 'active' : ''],
          key: item.slug,
          onClick: () => emit('navigate', item.slug),
        }, [h('span', item.title), h('small', item.summary)]))
        return nodes
      })
      return h('div', { class: 'nav-group', key: group.title }, [
        h('div', { class: 'nav-group-title' }, group.title),
        ...items,
      ])
    }))
  },
})

const CodeBlock = defineComponent({
  props: { code: { type: String, required: true } },
  emits: ['copy'],
  setup(props, { emit }) {
    return () => h('div', { class: 'code-shell' }, [
      h('button', { type: 'button', class: 'copy-code', onClick: () => emit('copy', props.code) }, t('docsUi.copy')),
      h('pre', [h('code', props.code)]),
    ])
  },
})

const content = computed(() => docsContent[locale.value] || docsContent['zh-CN'])
const normalizedParam = computed(() => {
  const value = route.params.pathMatch
  if (Array.isArray(value)) return value.join('/')
  return value || ''
})
const currentSlug = computed(() => normalizedParam.value.replace(/^\/+|\/+$/g, ''))
const article = computed(() => content.value.articles[currentSlug.value] || content.value.articles[''])
const flatItems = computed(() => content.value.groups.flatMap(group => group.items))
const currentIndex = computed(() => docsArticleOrder.indexOf(currentSlug.value))
const previousArticle = computed(() => currentIndex.value > 0 ? flatItems.value.find(item => item.slug === docsArticleOrder[currentIndex.value - 1]) : null)
const nextArticle = computed(() => currentIndex.value >= 0 && currentIndex.value < docsArticleOrder.length - 1 ? flatItems.value.find(item => item.slug === docsArticleOrder[currentIndex.value + 1]) : null)
const governanceLabels = computed(() => [
  text('提交', 'Submit'),
  text('检测', 'Scan'),
  text('策略判定', 'Policy'),
  text('审核签名', 'Review & sign'),
  text('运行校验', 'Runtime check'),
  text('审计追踪', 'Audit'),
])
const scanLogicLabels = computed(() => ({
  title: text('Skill 检测逻辑', 'Skill detection logic'),
  enterFullscreen: text('全屏查看检测逻辑图', 'View detection logic in full screen'),
  exitFullscreen: text('退出全屏', 'Exit full screen'),
  input: text('Skill 内容与扫描选项', 'Skill content and scan options'),
  pending: 'PENDING',
  pendingDetail: text('保存内容版本并创建后台检测任务', 'Store the content version and create a background scan task'),
  dispatch: text('按本次扫描上下文调度', 'Dispatch from the current scan context'),
  deterministic: text('确定性分析器', 'Deterministic analyzers'),
  deterministicDetail: text('独立执行并保留各自状态：completed / skipped / unavailable / failed', 'Run independently and preserve completed / skipped / unavailable / failed status'),
  scanner: text('基础 Scanner', 'Base Scanner'),
  always: text('每次启动', 'Always starts'),
  rules: text('规则分析', 'Rule analysis'),
  selected: text('按选择执行', 'Runs when selected'),
  deep: text('深度扫描', 'Deep scan'),
  availableSelected: text('可用且已选择', 'Available and selected'),
  selectedOrPolicy: text('手动选择或策略补跑', 'Selected or policy-triggered'),
  interimRisk: text('先合并静态发现，计算中间风险', 'Merge static findings and calculate interim risk'),
  policyCheck: text('策略检查', 'Policy check'),
  sandboxRequired: text('该风险等级是否必须运行 Sandbox？', 'Does this risk require Sandbox?'),
  ifMatched: text('命中时', 'When matched'),
  runSandbox: text('补跑一次 Sandbox', 'Run one Sandbox probe'),
  merge: text('执行后', 'After execution'),
  allFindings: text('合并全部发现项与运行证据', 'Merge all findings and runtime evidence'),
  classify: text('按规则、类别、证据和严重度逐条归类', 'Classify each item by rule, category, evidence, and severity'),
  classification: text('风险项目归类', 'Finding classification'),
  mapping: text('管理员映射优先，其次使用安全回退与严重度规则', 'Administrator mapping first, then security fallbacks and severity rules'),
  blocking: text('阻断项', 'Blocking'),
  blockingDetail: text('确定性高危；直接形成 malicious', 'Deterministic high risk; produces malicious'),
  suspicious: text('可疑项', 'Suspicious'),
  suspiciousDetail: text('结合最高严重度与判定模式', 'Uses highest severity and judgement mode'),
  noise: text('噪声', 'Noise'),
  noiseDetail: text('保留证据，不直接抬升风险', 'Evidence retained; no direct risk escalation'),
  mode: text('严格 / 平衡 / 宽松模式', 'Strict / balanced / permissive mode'),
  preLlmRisk: text('形成 LLM 前风险', 'Produce pre-LLM risk'),
  llmRequested: text('仅在本次请求启用 LLM 时调用一次；失败则使用确定性结果', 'Call once only when LLM is requested; fall back to deterministic result on failure'),
  optional: text('可选语义研判', 'Optional semantic judgement'),
  llm: text('LLM 分析内容与已有证据', 'LLM analyzes content and collected evidence'),
  guard: text('降级保护', 'Downgrade guard'),
  guardDetail: text('阻断项和严格模式不可降级', 'Blocking findings and strict mode cannot be downgraded'),
  reconcile: text('风险汇总', 'Risk reconciliation'),
  admissionPolicy: text('最终风险 + Manifest 阻断约束进入准入策略', 'Final risk + blocking manifest constraints enter admission policy'),
  approved: text('自动批准并签名', 'Auto-approve and sign'),
  vetted: text('进入人工审核', 'Queue for human review'),
  rejected: text('拒绝准入', 'Reject admission'),
}))
const platformPillars = computed(() => [
  { title: text('Skill 可信治理', 'Trusted Skill governance'), summary: text('准入检测、审核、签名与版本', 'Scanning, review, signatures, and versions'), slug: 'skill-governance', icon: FileSearchOutlined },
  { title: text('Agent 与客户端', 'Agents and clients'), summary: text('授权绑定、本地下发与持续巡检', 'Authorization, local delivery, and inspection'), slug: 'client-management', icon: DesktopOutlined },
  { title: text('模型网关', 'Model gateway'), summary: text('隐私防护、调用审计与 Token 压缩', 'Privacy, audits, and token compression'), slug: 'model-gateway', icon: ApiOutlined },
  { title: text('MCP 治理', 'MCP governance'), summary: text('Tool 发布、高风险审批与审计', 'Tool publishing, high-risk approval, and audit'), slug: 'mcp-governance', icon: SafetyCertificateOutlined },
])
const platformFoundation = computed(() => ({
  credentials: text('统一凭证', 'Credentials'),
  policy: text('策略与授权', 'Policy & authorization'),
  audit: text('全链路审计', 'End-to-end audit'),
}))
const architectureLabels = computed(() => ({
  title: text('Agent Manager 系统总体架构', 'Agent Manager system architecture'),
  enterFullscreen: text('全屏查看架构图', 'View architecture in full screen'),
  exitFullscreen: text('退出全屏', 'Exit full screen'),
  callers: text('调用方与管理入口', 'Callers and management entry'),
  admins: text('管理员 / 审核员', 'Administrators / reviewers'),
  scanner: text('Scanner / CI', 'Scanner / CI'),
  agents: text('Agent / 客户端', 'Agents / Clients'),
  modelApps: text('模型应用', 'Model applications'),
  mcpClients: text('MCP Client', 'MCP Clients'),
  secureTraffic: text('管理 API · 模型 API · MCP 数据面', 'Management API · Model API · MCP data plane'),
  unifiedEntry: text('统一入口', 'Unified entry'),
  ingressRoles: [
    text('认证与访问入口', 'Authentication and access'),
    text('静态文档与管理台', 'Docs and admin console'),
    text('API 与网关路径分流', 'API and gateway routing'),
  ],
  controlPlane: text('治理控制面', 'Governance control plane'),
  controlSummary: text('统一定义身份、策略、授权、任务与审计边界', 'Defines identity, policy, authorization, tasks, and audit boundaries'),
  identity: text('身份与凭证', 'Identity and credentials'),
  identityDetail: text('用户、组、Agent 及最小权限 Token', 'Users, groups, Agents, and least-privilege tokens'),
  policy: text('策略与授权', 'Policy and authorization'),
  policyDetail: text('Skill 准入、Agent 绑定、模型与 Tool 范围', 'Skill admission, Agent binding, model and Tool scopes'),
  console: text('管理台与文档', 'Console and documentation'),
  consoleDetail: text('审核、配置、追踪、运维与使用指导', 'Review, configuration, tracing, operations, and guidance'),
  orchestration: text('任务编排', 'Task orchestration'),
  orchestrationDetail: text('扫描队列、客户端任务和高风险审批', 'Scan queue, Client tasks, and high-risk approvals'),
  policyEnforcement: text('下发策略 · 校验身份 · 记录请求上下文', 'Distribute policy · verify identity · record request context'),
  runtimePlane: text('四条运行数据面', 'Four runtime data planes'),
  runtimeSummary: text('不同流量独立执行控制，共享统一身份、策略和审计', 'Independent enforcement with shared identity, policy, and audit'),
  skillDomain: text('Skill 准入治理', 'Skill admission'),
  skillFlow: text('提交 → 规则 / 深度扫描 → 可选 Sandbox / LLM → 策略判定', 'Submit → rules / deep scan → optional Sandbox / LLM → policy decision'),
  skillOutput: text('报告 · 审核 · 签名版本', 'Report · review · signed version'),
  clientDomain: text('Agent 与客户端治理', 'Agent and Client governance'),
  clientFlow: text('发现本地目录 → Agent 绑定 → 下发 / 恢复 → Verifier / Hook 校验', 'Discover roots → bind Agent → deliver / repair → Verifier / Hook checks'),
  clientOutput: text('可信本地 Skill · 任务与事件', 'Trusted local Skills · tasks and events'),
  modelDomain: text('模型网关', 'Model gateway'),
  modelFlow: text('凭证与模型范围 → Prompt 防护 → PII 替换 → 可选压缩 → 上游', 'Credential and model scope → Prompt protection → PII replacement → optional compression → upstream'),
  modelOutput: text('响应还原 · 用量 · Pipeline Trace', 'Response restoration · usage · Pipeline Trace'),
  mcpDomain: text('MCP 网关', 'MCP gateway'),
  mcpFlow: text('凭证与网关范围 → Tool Schema → 并发控制 → 高风险审批 → Server', 'Credential and gateway scope → Tool Schema → concurrency → high-risk approval → Server'),
  mcpOutput: text('受控 Tool 调用 · 调用审计', 'Controlled Tool calls · call audit'),
  evidenceWrite: text('所有准入、运行和管理结果写入可信证据层', 'Admission, runtime, and management outcomes enter the trust layer'),
  foundation: text('信任与证据基础', 'Trust and evidence foundation'),
  foundationSummary: text('可信状态不是页面标签，而是可追踪、可校验的持久化记录', 'Trust is a traceable and verifiable record, not a UI label'),
  registry: text('Registry 与版本', 'Registry and versions'),
  registryDetail: text('内容指纹、状态、签名、报告与策略上下文', 'Digests, states, signatures, reports, and policy context'),
  traces: text('任务、事件与 Trace', 'Tasks, events, and traces'),
  tracesDetail: text('客户端任务、模型链路、MCP 调用和用量', 'Client tasks, model pipeline, MCP calls, and usage'),
  audit: text('签名安全审计', 'Signed security audit'),
  auditDetail: text('哈希链、Ed25519 签名和可选 JSONL 导出', 'Hash chain, Ed25519 signatures, and optional JSONL export'),
  dependencies: text('隔离与外部运行依赖', 'Isolation and external runtime dependencies'),
  upstreamModels: text('上游模型供应商', 'Upstream model providers'),
  mcpServers: text('外部 MCP Server', 'External MCP Servers'),
}))
const dockerLabels = computed(() => ({
  entry: text('调用入口', 'Callers'),
  console: text('管理台浏览器', 'Admin browser'),
  agents: text('Agent / Client / Scanner', 'Agent / Client / Scanner'),
  callers: text('模型应用 / MCP Client', 'Model apps / MCP Client'),
  httpTraffic: text('HTTP / SSE 请求统一进入 80 端口', 'HTTP / SSE traffic enters through port 80'),
  publicIngress: text('统一入口', 'Unified ingress'),
  nginxRole: text('页面、管理 API、模型网关和 MCP 数据面分流', 'Routes console, management API, model gateway, and MCP data plane'),
  routeTraffic: text('按路径转发', 'Route by path'),
  controlPlane: text('控制面与数据面入口', 'Control plane and data-plane entry'),
  webConsole: text('管理界面', 'Management console'),
  frontendRole: text('Vue 静态资源与页面', 'Vue assets and pages'),
  governanceApi: text('治理与网关 API', 'Governance and gateway API'),
  backendRole: text('Skill、Agent、模型、MCP、凭证与审计', 'Skills, Agents, models, MCP, credentials, and audit'),
  executionPlane: text('隔离执行边界', 'Isolated execution boundary'),
  backendOnly: text('Backend 内网调用 · 主机仅回环', 'Backend network call · host loopback only'),
  sandboxRole: text('受限环境执行动态检测', 'Runs dynamic checks in a restricted environment'),
  dataPlane: text('持久化数据', 'Persistent data'),
  sandboxLink: text('Backend → 动态检测请求', 'Backend → dynamic scan'),
  volumeLink: text('Backend → 读写持久化数据', 'Backend → persistent reads and writes'),
  boundaryNote: text('Sandbox 服务同时接入独立的 sandbox-control 网络，8194 只映射到主机回环地址；实际被检测代码仍在 nsjail 的独立网络命名空间中运行，默认无网络。', 'The Sandbox service also joins the separate sandbox-control network, and port 8194 is bound only to host loopback. Analyzed code still runs in an isolated nsjail network namespace with networking disabled by default.'),
}))
const dockerVolumes = ['backend_data', 'backend_uploads', 'backend_sqlite', 'agent_manager_registry']

const collectSearchText = value => {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(collectSearchText).join(' ')
  if (value && typeof value === 'object') return Object.values(value).map(collectSearchText).join(' ')
  return ''
}

const isLinkCell = cell => Boolean(cell && typeof cell === 'object' && cell.path && cell.label)

const searchResults = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) return []
  return flatItems.value.filter(item => {
    const articleValue = content.value.articles[item.slug]
    const haystack = [item.title, item.summary, collectSearchText(articleValue)].join(' ').toLocaleLowerCase()
    return haystack.includes(query)
  }).slice(0, 8)
})

const docsPath = slug => slug ? `/docs/${slug}` : '/docs'
const navigateToArticle = slug => {
  searchQuery.value = ''
  searchFocused.value = false
  router.push(docsPath(slug))
}
const navigateFromMobile = slug => {
  mobileNavOpen.value = false
  navigateToArticle(slug)
}
const navigateFromAssistant = slug => {
  navigateToArticle(slug)
}
const closeSearch = () => {
  searchQuery.value = ''
  searchFocused.value = false
}
const handleLocaleChange = async value => {
  setLocale(value)
  try {
    await updateMyLocale(value)
  } catch {
    // Keep the local language choice when profile persistence is unavailable.
  }
}
const scrollToSection = id => {
  const element = document.getElementById(id)
  element?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  history.replaceState(null, '', `${route.path}#${id}`)
}
const screenshotUrl = name => `/docs/screenshots/${locale.value}/${name}.png`
const markImageFailed = name => {
  failedImages.value = new Set([...failedImages.value, name])
}
const openImage = image => {
  previewImage.value = image
  imagePreviewOpen.value = true
}
const copyWithFallback = code => {
  const textarea = document.createElement('textarea')
  textarea.value = code
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}
const copyCode = async code => {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
    await navigator.clipboard.writeText(code)
  } catch {
    copyWithFallback(code)
  }
  copiedVisible.value = true
  if (copyTimer.value) window.clearTimeout(copyTimer.value)
  copyTimer.value = window.setTimeout(() => { copiedVisible.value = false }, 1600)
}
const handleDocumentKeydown = event => {
  if (event.key !== 'Escape') return
  architectureFullscreen.value = false
  scanLogicFullscreen.value = false
}

watch(currentSlug, async slug => {
  architectureFullscreen.value = false
  scanLogicFullscreen.value = false
  if (!content.value.articles[slug]) {
    router.replace('/docs')
    return
  }
  await nextTick()
  articleScroller.value?.scrollTo({ top: 0 })
  document.title = `${article.value.title} · ${t('app.name')}`
}, { immediate: true })

onMounted(async () => {
  document.addEventListener('keydown', handleDocumentKeydown)
  if (route.hash) nextTick(() => document.querySelector(route.hash)?.scrollIntoView({ block: 'start' }))
  try {
    docsAssistantConfig.value = await getDocsAssistantConfig()
  } catch {
    docsAssistantConfig.value = { enabled: false, common_questions: [], max_context_sections: 4 }
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleDocumentKeydown)
  if (copyTimer.value) window.clearTimeout(copyTimer.value)
})
</script>

<style scoped>
.docs-page {
  --docs-ink: #0b1f33;
  --docs-muted: #526579;
  --docs-blue: #2563eb;
  --docs-green: #15803d;
  --docs-amber: #d97706;
  --docs-surface: #f6f8fb;
  --docs-line: #dce3ec;
  height: 100vh;
  min-width: 320px;
  overflow: hidden;
  color: var(--docs-ink);
  background: var(--docs-surface);
}

.docs-header {
  position: relative;
  z-index: 20;
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(300px, 520px) minmax(240px, 1fr);
  align-items: center;
  height: 68px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--docs-line);
  backdrop-filter: blur(12px);
}

.brand-button {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  gap: 12px;
  padding: 4px;
  color: inherit;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.brand-button:focus-visible,
.nav-item:focus-visible,
.role-grid button:focus-visible,
.article-pagination button:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.28);
  outline-offset: 2px;
}

.docs-logo { width: auto; height: 36px; }
.brand-copy { display: flex; align-items: baseline; gap: 9px; text-align: left; }
.brand-name { max-width: 260px; overflow: hidden; font-size: 15px; font-weight: 720; text-overflow: ellipsis; white-space: nowrap; }
.brand-docs { padding-left: 9px; color: var(--docs-muted); font-size: 13px; border-left: 1px solid var(--docs-line); }

.header-search { position: relative; width: 100%; }
.header-search input {
  width: 100%;
  height: 40px;
  padding: 0 16px 0 40px;
  color: var(--docs-ink);
  background: #f2f5f9;
  border: 1px solid transparent;
  border-radius: 10px;
  outline: none;
  transition: 160ms ease;
}
.header-search input:focus { background: #fff; border-color: #93b4fb; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }
.search-icon { position: absolute; z-index: 1; top: 12px; left: 14px; color: #718096; }
.search-results {
  position: absolute;
  top: 48px;
  right: 0;
  left: 0;
  overflow: hidden;
  padding: 7px;
  background: #fff;
  border: 1px solid var(--docs-line);
  border-radius: 12px;
  box-shadow: 0 18px 50px rgba(11, 31, 51, 0.16);
}
.search-results button { display: flex; width: 100%; flex-direction: column; gap: 3px; padding: 10px 12px; text-align: left; background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.search-results button:hover { background: #f2f6ff; }
.search-results span { font-weight: 650; }
.search-results small { color: var(--docs-muted); }
.search-empty { padding: 18px; color: var(--docs-muted); text-align: center; }

.header-actions { display: flex; align-items: center; justify-self: end; gap: 10px; }
.ask-ai-button {
  color: #174f91;
  background: #edf5ff;
  border-color: #c6daf2;
  box-shadow: none;
  font-weight: 650;
}
.ask-ai-button:hover { color: #fff !important; background: #2468bd !important; border-color: #2468bd !important; }
.docs-language { width: 128px; }
.mobile-menu-button { display: none; }

.docs-layout {
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr) 224px;
  height: calc(100vh - 68px);
  width: 100%;
}
.docs-sidebar { overflow-y: auto; padding: 28px 14px 48px 16px; background: #f6f8fb; border-right: 1px solid var(--docs-line); }
:deep(.docs-nav) { display: flex; flex-direction: column; gap: 22px; }
:deep(.nav-group-title) { margin: 0 6px 8px; color: #7a8999; font-size: 11px; font-weight: 750; letter-spacing: 0.1em; text-transform: uppercase; }
:deep(.nav-subgroup-title) { display: flex; align-items: center; gap: 8px; margin: 12px 6px 5px; color: #526579; font-size: 12px; font-weight: 720; }
:deep(.nav-subgroup-title)::after { flex: 1; height: 1px; background: #dfe6ee; content: ''; }
:deep(.nav-item) { display: flex; width: 100%; flex-direction: column; gap: 2px; padding: 9px 8px; color: #33485f; text-align: left; background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
:deep(.nav-item.nested) { margin-left: 8px; width: calc(100% - 8px); padding-left: 12px; }
:deep(.nav-item:hover) { background: #edf2f8; }
:deep(.nav-item.active) { color: #174ea6; background: #e8f0ff; box-shadow: inset 3px 0 0 var(--docs-blue); }
:deep(.nav-item span) { font-size: 14px; font-weight: 650; }
:deep(.nav-item small) { overflow: hidden; color: #7a8999; font-size: 11px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
:deep(.nav-item.active small) { color: #5274aa; }

.docs-article-scroll { overflow-y: auto; scroll-behavior: smooth; background: #fff; }
.docs-article { width: min(820px, calc(100% - 64px)); margin: 0 auto; padding: 66px 0 80px; }
.article-heading { padding-bottom: 34px; border-bottom: 1px solid var(--docs-line); }
.eyebrow { margin-bottom: 13px; color: var(--docs-blue); font-size: 12px; font-weight: 760; letter-spacing: 0.12em; text-transform: uppercase; }
.article-heading h1 { margin: 0; color: var(--docs-ink); font-size: clamp(34px, 4vw, 48px); font-weight: 760; letter-spacing: -0.035em; line-height: 1.08; }
.article-heading p { max-width: 720px; margin: 18px 0 0; color: var(--docs-muted); font-size: 17px; line-height: 1.8; }

.scenario-brief { display: grid; grid-template-columns: 44px repeat(3, minmax(0, 1fr)); align-items: stretch; margin: -1px 0 46px; color: #dce9f5; background: #102c46; border-radius: 0 0 12px 12px; }
.scenario-brief-mark { display: grid; place-items: center; color: #8fc5ff; background: #173c5d; font-size: 18px; }
.scenario-brief-item { display: flex; min-width: 0; flex-direction: column; gap: 5px; padding: 14px 16px; border-left: 1px solid #2d4d69; }
.scenario-brief-item small { color: #91aac0; font-size: 10px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; }
.scenario-brief-item strong { overflow: hidden; font-size: 12px; font-weight: 650; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }

.role-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin: 0 0 54px; }
.role-grid button { position: relative; display: flex; min-height: 150px; flex-direction: column; align-items: flex-start; gap: 9px; padding: 20px; color: inherit; text-align: left; background: #f8fafc; border: 1px solid var(--docs-line); border-radius: 12px; cursor: pointer; transition: 160ms ease; }
.role-grid button:hover { border-color: #aac3f6; box-shadow: 0 10px 28px rgba(11, 31, 51, 0.08); transform: translateY(-2px); }
.role-grid button strong { font-size: 15px; }
.role-grid button > span:not(.role-mark) { color: var(--docs-muted); font-size: 13px; line-height: 1.6; }
.role-mark { display: grid; width: 30px; height: 30px; place-items: center; color: #174ea6; background: #e8f0ff; border-radius: 8px; }
.role-arrow { position: absolute; right: 18px; bottom: 18px; color: var(--docs-blue); }

.article-section { scroll-margin-top: 24px; padding: 54px 0 0; }
.article-section h2 { margin: 0 0 18px; font-size: 26px; letter-spacing: -0.02em; }
.article-section h2 a { color: var(--docs-ink); }
.article-section h2 a:hover::after { margin-left: 8px; color: #9aabba; content: '#'; font-weight: 400; }
.article-section > p { margin: 0 0 16px; color: #3d5268; font-size: 15px; line-height: 1.85; }
.doc-list { display: grid; gap: 10px; margin: 18px 0; padding-left: 21px; color: #3d5268; line-height: 1.75; }
.doc-list li::marker { color: var(--docs-blue); }

.scenario-flow { display: flex; align-items: stretch; gap: 7px; margin: 22px 0; padding: 14px; overflow-x: auto; background: #f5f8fb; border: 1px solid var(--docs-line); border-radius: 12px; }
.scenario-flow-node { display: flex; min-width: 112px; flex: 1 0 112px; flex-direction: column; justify-content: center; gap: 5px; min-height: 72px; padding: 11px 12px; background: #fff; border: 1px solid #d7e0e9; border-top: 3px solid #6e8ba6; border-radius: 8px; }
.scenario-flow-node small { color: #75889a; font-size: 9px; font-weight: 750; letter-spacing: 0.07em; text-transform: uppercase; }
.scenario-flow-node strong { color: #2d445a; font-size: 11px; line-height: 1.45; }
.scenario-flow-node.success { border-top-color: #2c8464; background: #f4fbf7; }
.scenario-flow-node.decision { border-top-color: #d08a24; background: #fffaf1; }
.scenario-flow-node.blocked { border-top-color: #c24747; background: #fff6f6; }
.scenario-flow-arrow { align-self: center; flex: 0 0 auto; color: #8aa0b4; font-size: 11px; }

.governance-diagram { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin: 24px 0; }
.governance-step { position: relative; display: flex; min-height: 86px; flex-direction: column; justify-content: center; gap: 8px; padding: 13px; background: #f5f8fc; border: 1px solid var(--docs-line); border-radius: 9px; }
.governance-step span { color: var(--docs-blue); font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }
.governance-step strong { font-size: 12px; }

.skill-scan-logic { --scan-blue: #2f6fad; --scan-green: #4c806d; --scan-amber: #ad7b35; --scan-red: #a95050; position: relative; box-sizing: border-box; width: 100%; margin: 26px 0; padding: 18px; color: #29445b; background: #f7f9fc; border: 1px solid #d5e0ea; border-radius: 14px; box-shadow: 0 12px 30px rgba(35, 66, 93, .06); }
.skill-scan-logic.fullscreen { position: fixed; z-index: 1000; inset: 0; width: 100vw; height: 100vh; margin: 0; padding: 24px max(24px, calc((100vw - 1180px) / 2)); overflow: auto; border: 0; border-radius: 0; box-shadow: none; }
.skill-scan-logic.fullscreen .diagram-fullscreen-button { position: fixed; top: 18px; right: 20px; width: 40px; height: 40px; font-size: 17px; }
.diagram-fullscreen-button { position: absolute; z-index: 2; top: 12px; right: 12px; display: grid; width: 34px; height: 34px; place-items: center; color: #47647c; background: rgba(255, 255, 255, .9); border: 1px solid #cfdae4; border-radius: 8px; box-shadow: 0 5px 14px rgba(35, 66, 93, .08); cursor: pointer; transition: 160ms ease; }
.diagram-fullscreen-button:hover { color: #1f5f96; background: #fff; border-color: #9ebbd3; }
.diagram-fullscreen-button:focus-visible { outline: 3px solid rgba(47, 111, 173, .24); outline-offset: 2px; }
.scan-logic-start { display: grid; grid-template-columns: minmax(140px, .5fr) minmax(110px, .4fr) minmax(0, 1.4fr); align-items: center; gap: 12px; min-height: 68px; padding: 13px 16px; color: #285374; background: #e8f2fb; border: 1px solid #c5dced; border-left: 4px solid var(--scan-blue); border-radius: 9px; }
.scan-logic-start small { color: #6886a1; font-size: 9px; font-weight: 750; letter-spacing: .07em; text-transform: uppercase; }
.scan-logic-start strong { font-size: 16px; }
.scan-logic-start span { color: #557087; font-size: 11px; line-height: 1.55; }
.scan-logic-connector { position: relative; display: grid; min-height: 46px; place-items: center; color: #71879a; font-size: 10px; line-height: 1.4; text-align: center; }
.scan-logic-connector::before { position: absolute; top: 0; bottom: 7px; left: 50%; width: 1px; background: #9eb1c2; content: ''; }
.scan-logic-connector::after { position: absolute; bottom: 5px; left: calc(50% - 4px); width: 8px; height: 8px; border-right: 1px solid #9eb1c2; border-bottom: 1px solid #9eb1c2; content: ''; transform: rotate(45deg); }
.scan-logic-connector span { z-index: 1; max-width: 88%; padding: 3px 9px; background: #f7f9fc; }
.scan-logic-stage { padding: 15px; background: #fff; border: 1px solid #d2dde7; border-top: 4px solid #76a7d2; border-radius: 10px; }
.scan-logic-heading { display: grid; grid-template-columns: minmax(170px, .65fr) minmax(0, 1.35fr); align-items: center; gap: 13px; margin-bottom: 13px; }
.scan-logic-heading strong { color: #263f56; font-size: 15px; line-height: 1.35; }
.scan-logic-heading span { color: #6c8193; font-size: 11px; line-height: 1.55; }
.scan-analyzer-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }
.scan-analyzer-grid > div { display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: center; gap: 3px 9px; min-width: 0; min-height: 76px; padding: 12px; background: #f7f9fc; border: 1px solid #dbe4ec; border-radius: 8px; }
.scan-analyzer-grid .anticon { grid-row: 1 / 3; color: #5d7890; font-size: 18px; }
.scan-analyzer-grid strong { color: #304b62; font-size: 11.5px; line-height: 1.35; }
.scan-analyzer-grid span { color: #74899b; font-size: 9.5px; line-height: 1.4; }
.scan-analyzer-grid .required { background: #edf5fc; border-color: #cbdfee; }
.scan-analyzer-grid .required .anticon { color: var(--scan-blue); }
.scan-policy-row { display: grid; grid-template-columns: minmax(0, 1fr) 18px minmax(0, .72fr) 18px minmax(0, .9fr); align-items: stretch; gap: 8px; }
.scan-policy-row > div { display: flex; min-width: 0; min-height: 70px; flex-direction: column; justify-content: center; gap: 5px; padding: 12px 14px; background: #fff; border: 1px solid #d7e1ea; border-radius: 8px; }
.scan-policy-row > .anticon { align-self: center; color: #91a5b6; }
.scan-policy-row small { color: #7a8ea0; font-size: 9px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.scan-policy-row strong { color: #304b62; font-size: 11px; line-height: 1.45; }
.scan-policy-row .decision { background: #fdf8ee; border-color: #e6d7b8; }
.scan-policy-row .decision strong { color: #785925; }
.classification-stage { border-top-color: #7ca9a0; }
.scan-classification-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; }
.scan-classification-grid > div { display: flex; min-width: 0; min-height: 74px; flex-direction: column; justify-content: center; gap: 5px; padding: 12px 14px; border: 1px solid; border-radius: 8px; }
.scan-classification-grid strong { font-size: 12px; }
.scan-classification-grid span { font-size: 10px; line-height: 1.45; }
.scan-classification-grid .blocked { color: #844545; background: #fff4f4; border-color: #edcece; }
.scan-classification-grid .suspicious { color: #806027; background: #fdf8ee; border-color: #e6d7b8; }
.scan-classification-grid .noise { color: #607588; background: #f3f6f8; border-color: #d9e1e7; }
.scan-deterministic-result { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; padding: 10px 13px; color: #49677e; background: #edf4f9; border-radius: 7px; font-size: 10px; }
.scan-deterministic-result strong { color: #2f536e; font-size: 11px; }
.scan-llm-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr) minmax(0, 1fr); gap: 10px; }
.scan-llm-row > div { display: flex; min-width: 0; min-height: 78px; align-items: center; gap: 11px; padding: 12px 14px; background: #fff; border: 1px solid #d7e1ea; border-radius: 8px; }
.scan-llm-row .anticon { flex: 0 0 auto; color: var(--scan-blue); font-size: 18px; }
.scan-llm-row span { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.scan-llm-row small { color: #768b9d; font-size: 9.5px; line-height: 1.4; }
.scan-llm-row strong { color: #304b62; font-size: 10.5px; line-height: 1.45; }
.scan-llm-guard { background: #fff7f3 !important; border-color: #ead6ca !important; }
.scan-llm-guard .anticon { color: var(--scan-red); }
.scan-final-risk { flex-direction: column; align-items: flex-start !important; justify-content: center; background: #edf5fc !important; border-color: #cbdfee !important; }
.scan-final-risk strong { color: #285374; }
.scan-admission-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.scan-admission-grid > div { display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: center; gap: 3px 9px; min-width: 0; min-height: 78px; padding: 12px 14px; background: #fff; border: 1px solid #d7e1ea; border-top: 4px solid; border-radius: 9px; }
.scan-admission-grid .anticon { grid-row: 1 / 3; font-size: 18px; }
.scan-admission-grid strong { font-size: 12px; }
.scan-admission-grid span { color: #718698; font-size: 10px; line-height: 1.4; }
.scan-admission-grid .approved { border-top-color: var(--scan-green); }
.scan-admission-grid .approved .anticon, .scan-admission-grid .approved strong { color: #3d755f; }
.scan-admission-grid .vetted { border-top-color: var(--scan-amber); }
.scan-admission-grid .vetted .anticon, .scan-admission-grid .vetted strong { color: #856224; }
.scan-admission-grid .rejected { border-top-color: var(--scan-red); }
.scan-admission-grid .rejected .anticon, .scan-admission-grid .rejected strong { color: #914747; }

.platform-map { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 24px 0; }
.platform-pillar { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: 12px; min-height: 96px; padding: 17px; color: var(--docs-ink); text-align: left; background: #f8fafc; border: 1px solid var(--docs-line); border-radius: 11px; cursor: pointer; transition: 160ms ease; }
.platform-pillar:hover { border-color: #9eb9ed; box-shadow: 0 10px 24px rgba(11, 31, 51, 0.08); transform: translateY(-1px); }
.platform-pillar:focus-visible { outline: 3px solid rgba(37, 99, 235, 0.28); outline-offset: 2px; }
.platform-pillar-icon { display: grid; width: 38px; height: 38px; place-items: center; color: #174ea6; background: #e8f0ff; border-radius: 9px; font-size: 18px; }
.platform-pillar-copy { display: flex; min-width: 0; flex-direction: column; gap: 5px; }
.platform-pillar-copy strong { font-size: 14px; }
.platform-pillar-copy small { color: var(--docs-muted); font-size: 12px; line-height: 1.5; }
.platform-pillar > .anticon { color: #7791ad; }
.platform-foundation { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(3, 1fr); overflow: hidden; color: #dce9f5; background: var(--docs-ink); border-radius: 9px; }
.platform-foundation span { padding: 11px 14px; font-size: 11px; font-weight: 650; letter-spacing: 0.04em; text-align: center; }
.platform-foundation span + span { border-left: 1px solid #36536e; }

.system-architecture { --arch-blue: #2f6fad; --arch-cyan: #397f8a; --arch-green: #4c806d; --arch-amber: #ad7b35; position: relative; box-sizing: border-box; width: 100%; margin: 26px 0; padding: 18px; color: #253f55; background: #f7f9fc; border: 1px solid #d5e0ea; border-radius: 14px; box-shadow: 0 12px 30px rgba(35, 66, 93, 0.06); }
.system-architecture.fullscreen { position: fixed; z-index: 1000; inset: 0; width: 100vw; height: 100vh; margin: 0; padding: 24px; overflow: auto; border: 0; border-radius: 0; box-shadow: none; }
.architecture-fullscreen-button { position: absolute; z-index: 2; top: 12px; right: 12px; display: grid; width: 34px; height: 34px; place-items: center; color: #47647c; background: rgba(255, 255, 255, .9); border: 1px solid #cfdae4; border-radius: 8px; box-shadow: 0 5px 14px rgba(35, 66, 93, .08); cursor: pointer; transition: 160ms ease; }
.architecture-fullscreen-button:hover { color: #1f5f96; background: #fff; border-color: #9ebbd3; }
.architecture-fullscreen-button:focus-visible { outline: 3px solid rgba(47, 111, 173, .24); outline-offset: 2px; }
.system-architecture.fullscreen .architecture-fullscreen-button { position: fixed; top: 18px; right: 20px; width: 40px; height: 40px; font-size: 17px; }
.architecture-band-label { display: flex; align-items: center; margin-bottom: 12px; color: #263f56; }
.architecture-band-label strong { font-size: 15px; line-height: 1.35; }
.architecture-caller-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.architecture-caller-grid > div { display: flex; min-width: 0; min-height: 54px; align-items: center; justify-content: center; gap: 8px; padding: 9px 10px; color: #3f5870; background: #fff; border: 1px solid #d8e2eb; border-radius: 8px; font-size: 11px; font-weight: 680; line-height: 1.4; text-align: center; }
.architecture-caller-grid .anticon { flex: 0 0 auto; color: var(--arch-blue); font-size: 17px; }
.architecture-ingress-link, .architecture-plane-link, .architecture-foundation-link { position: relative; display: grid; min-height: 46px; place-items: center; color: #71879a; font-size: 10px; line-height: 1.4; text-align: center; }
.architecture-ingress-link::before, .architecture-plane-link::before, .architecture-foundation-link::before { position: absolute; top: 0; bottom: 7px; left: 50%; width: 1px; background: #9eb1c2; content: ''; }
.architecture-ingress-link::after, .architecture-plane-link::after, .architecture-foundation-link::after { position: absolute; bottom: 5px; left: calc(50% - 4px); width: 8px; height: 8px; border-right: 1px solid #9eb1c2; border-bottom: 1px solid #9eb1c2; content: ''; transform: rotate(45deg); }
.architecture-ingress-link span, .architecture-plane-link span, .architecture-foundation-link span { z-index: 1; max-width: 86%; padding: 3px 9px; background: #f7f9fc; }
.architecture-ingress { display: grid; grid-template-columns: minmax(130px, .55fr) minmax(0, 2.45fr); align-items: stretch; gap: 16px; min-height: 70px; padding: 14px 16px; color: #294a66; background: #e8f2fb; border: 1px solid #c5dced; border-left: 4px solid var(--arch-blue); border-radius: 9px; }
.architecture-ingress > div { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.architecture-ingress small { color: #6886a1; font-size: 9px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
.architecture-ingress strong { color: #1f527c; font-size: 18px; }
.architecture-ingress > .architecture-ingress-roles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.architecture-ingress-roles span { display: flex; min-width: 0; align-items: center; justify-content: center; padding: 8px 10px; color: #4e6c85; background: rgba(255, 255, 255, .62); border: 1px solid #d1e2f0; border-radius: 7px; font-size: 10.5px; font-weight: 650; line-height: 1.45; text-align: center; }
.architecture-control-plane, .architecture-runtime-plane, .architecture-foundation { padding: 15px; background: #fff; border: 1px solid #d2dde7; border-radius: 10px; }
.architecture-control-plane { border-top: 4px solid #76a7d2; }
.architecture-runtime-plane { border-top: 4px solid #72a9ae; }
.architecture-foundation { color: #29465e; background: #edf4f9; border-color: #cbdce8; border-top: 4px solid #83aeca; }
.architecture-plane-heading { display: grid; grid-template-columns: minmax(180px, .65fr) minmax(0, 1.35fr); align-items: center; gap: 13px; margin-bottom: 13px; }
.architecture-plane-heading > strong { color: #263f56; font-size: 15px; line-height: 1.35; }
.architecture-plane-heading > small { min-width: 0; color: #6c8193; font-size: 11px; line-height: 1.55; }
.architecture-foundation .architecture-plane-heading > strong { color: #29465e; }
.architecture-foundation .architecture-plane-heading > small { color: #667f92; }
.architecture-control-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.architecture-control-grid > div, .architecture-foundation-grid > div { display: flex; min-width: 0; min-height: 80px; flex-direction: column; justify-content: center; gap: 7px; padding: 14px 16px; background: #f6f9fc; border: 1px solid #dbe4ec; border-radius: 8px; }
.architecture-control-grid strong, .architecture-foundation-grid strong { color: #304b62; font-size: 12px; line-height: 1.35; }
.architecture-control-grid span, .architecture-foundation-grid span { color: #6c8193; font-size: 11px; line-height: 1.55; }
.architecture-domain-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.architecture-domain { display: flex; min-width: 0; min-height: 164px; flex-direction: column; padding: 14px; background: #f9fbfd; border: 1px solid #d7e1ea; border-left: 4px solid var(--arch-blue); border-radius: 9px; }
.architecture-domain.client-domain { border-left-color: var(--arch-green); }
.architecture-domain.model-domain { border-left-color: var(--arch-cyan); }
.architecture-domain.mcp-domain { border-left-color: var(--arch-amber); }
.architecture-domain-head { display: flex; min-width: 0; align-items: center; gap: 11px; }
.architecture-domain-head > .anticon { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; color: #fff; background: var(--arch-blue); border-radius: 8px; font-size: 16px; }
.client-domain .architecture-domain-head > .anticon { background: var(--arch-green); }
.model-domain .architecture-domain-head > .anticon { background: var(--arch-cyan); }
.mcp-domain .architecture-domain-head > .anticon { background: var(--arch-amber); }
.architecture-domain-head > span { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.architecture-domain-head small { color: #8193a3; font-family: "SFMono-Regular", Consolas, monospace; font-size: 8px; letter-spacing: .08em; }
.architecture-domain-head strong { color: #29445b; font-size: 13px; line-height: 1.35; }
.architecture-domain p { flex: 1; margin: 14px 0; color: #5f7689; font-size: 11.5px; line-height: 1.75; }
.architecture-domain-output { padding-top: 10px; color: #3f5f78; border-top: 1px dashed #c8d5df; font-size: 10.5px; font-weight: 700; line-height: 1.5; }
.architecture-foundation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.architecture-foundation-grid > div { background: #fff; border-color: #d1dfe9; }
.architecture-foundation-grid strong { color: #2d4b63; }
.architecture-foundation-grid span { color: #698194; }
.architecture-dependencies { display: grid; grid-template-columns: minmax(150px, auto) minmax(0, 1fr); align-items: center; gap: 16px; margin-top: 12px; padding: 12px 14px; color: #60788b; background: #eef2f6; border: 1px solid #dbe3ea; border-radius: 8px; font-size: 10px; }
.architecture-dependencies > span { font-weight: 750; letter-spacing: .04em; }
.architecture-dependencies > div { display: flex; min-width: 0; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.architecture-dependencies b { padding: 7px 10px; color: #4b6579; background: #fff; border: 1px solid #d1dce5; border-radius: 6px; font-size: 10px; font-weight: 650; }

.docker-topology { --topology-navy: #17334f; --topology-blue: #2e68b2; --topology-green: #28715e; margin: 24px 0; padding: 22px; overflow: hidden; background: #f6f8fb; border: 1px solid #d8e0e9; border-radius: 14px; }
.topology-zone { position: relative; padding: 38px 14px 14px; background: rgba(255, 255, 255, 0.78); border: 1px solid #cfdae5; border-radius: 10px; }
.topology-zone-label { position: absolute; top: 0; left: 0; display: flex; align-items: center; gap: 9px; padding: 8px 11px; color: #4d6277; font-size: 10px; }
.topology-zone-label span { color: #75899e; font-family: "SFMono-Regular", Consolas, monospace; font-size: 9px; letter-spacing: 0.08em; }
.topology-zone-label strong { font-size: 11px; }
.topology-entry-nodes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; }
.topology-entry-nodes > div { display: flex; min-height: 52px; align-items: center; justify-content: center; gap: 8px; padding: 9px; color: #334b61; background: #fff; border: 1px solid #dde4eb; border-radius: 7px; font-size: 11px; font-weight: 650; text-align: center; }
.topology-entry-nodes .anticon { color: var(--topology-blue); font-size: 16px; }
.topology-downlink { position: relative; display: grid; height: 48px; place-items: center; color: #75889b; font-size: 10px; }
.topology-downlink::before { position: absolute; top: 0; bottom: 8px; left: 50%; width: 1px; background: #9aadc0; content: ''; }
.topology-downlink::after { position: absolute; bottom: 5px; left: calc(50% - 4px); width: 8px; height: 8px; border-right: 1px solid #9aadc0; border-bottom: 1px solid #9aadc0; content: ''; transform: rotate(45deg); }
.topology-downlink span { z-index: 1; padding: 3px 8px; background: #f6f8fb; }
.topology-ingress { display: grid; grid-template-columns: 180px 1fr; align-items: center; gap: 16px; min-height: 68px; padding: 13px 16px; color: #fff; background: var(--topology-navy); border-radius: 9px; box-shadow: 0 12px 28px rgba(23, 51, 79, 0.16); }
.topology-ingress > div { display: flex; flex-direction: column; gap: 4px; }
.topology-ingress small { color: #9fb8cf; font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase; }
.topology-ingress strong { font-size: 18px; }
.topology-ingress b, .topology-service b { color: #72a8ef; font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }
.topology-ingress > span { color: #c9d8e7; font-size: 11px; line-height: 1.55; }
.topology-split { display: grid; height: 43px; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 9px; color: #75889b; font-size: 10px; }
.topology-split i { height: 1px; background: #9aadc0; }
.topology-control { display: grid; grid-template-columns: 0.72fr 1.28fr; gap: 12px; border-color: #aebfd2; background: #edf3f9; }
.topology-service { display: flex; min-height: 92px; flex-direction: column; justify-content: center; gap: 5px; padding: 15px; background: #fff; border: 1px solid #cbd7e2; border-radius: 8px; box-shadow: 0 6px 16px rgba(39, 67, 94, 0.06); }
.topology-service small { color: #74879a; font-size: 9px; letter-spacing: 0.06em; text-transform: uppercase; }
.topology-service strong { color: #22394e; font-size: 16px; }
.topology-service > span { color: #6c7e90; font-size: 10px; line-height: 1.5; }
.backend-service { border-left: 3px solid var(--topology-blue); }
.topology-backend-links { display: grid; grid-template-columns: 1fr 1.18fr; gap: 12px; margin-top: 5px; color: #73879a; font-size: 9px; text-align: center; }
.topology-backend-links span { position: relative; padding-top: 18px; }
.topology-backend-links span::before { position: absolute; top: 0; left: 50%; width: 1px; height: 14px; background: #9aadc0; content: ''; }
.topology-backend-links span::after { position: absolute; top: 8px; left: calc(50% - 3px); width: 6px; height: 6px; border-right: 1px solid #9aadc0; border-bottom: 1px solid #9aadc0; content: ''; transform: rotate(45deg); }
.topology-bottom { display: grid; grid-template-columns: 1fr 1.18fr; gap: 12px; margin-top: 12px; }
.topology-execution { border-color: #afcfbf; background: #edf7f2; }
.sandbox-service { min-height: 86px; border-color: #b7d5c5; border-left: 3px solid var(--topology-green); }
.sandbox-service strong, .sandbox-service b { color: #1e6553; }
.topology-data { border-color: #d8c6a8; background: #faf5ec; }
.docker-volumes { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.docker-volumes span { padding: 9px 8px; color: #665642; background: #fff; border: 1px solid #e3d7c5; border-radius: 6px; font-family: "SFMono-Regular", Consolas, monospace; font-size: 9px; text-align: center; }
.topology-note { display: flex; align-items: flex-start; gap: 8px; margin-top: 13px; padding: 10px 11px; color: #52687b; background: #fff; border-left: 3px solid var(--topology-green); font-size: 10px; line-height: 1.55; }
.topology-note .anticon { margin-top: 2px; color: var(--topology-green); }

.doc-steps { display: grid; gap: 0; margin: 18px 0; }
.doc-step { display: grid; grid-template-columns: 38px 1fr; gap: 16px; }
.step-number { position: relative; z-index: 1; display: grid; width: 30px; height: 30px; place-items: center; color: #fff; background: var(--docs-blue); border: 4px solid #fff; border-radius: 50%; box-shadow: 0 0 0 1px #9eb9ed; font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }
.doc-step:not(:last-child) .step-number::after { position: absolute; z-index: -1; top: 30px; left: 13px; width: 1px; height: calc(100% + 34px); background: var(--docs-line); content: ''; }
.step-content { padding: 2px 0 30px; }
.step-content h3 { margin: 0 0 7px; font-size: 16px; }
.step-content > p { margin: 0 0 12px; color: var(--docs-muted); line-height: 1.7; }
.expected-result { display: flex; gap: 10px; margin-top: 12px; padding: 11px 13px; color: #135c2d; background: #edf9f0; border-radius: 8px; }
.expected-result div { display: flex; flex-direction: column; gap: 2px; }
.expected-result span { color: #356d46; font-size: 13px; }

.doc-table-wrap { overflow-x: auto; margin: 20px 0; border: 1px solid var(--docs-line); border-radius: 10px; }
.doc-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.doc-table th { padding: 12px 14px; color: #40546a; text-align: left; background: #f1f5f9; border-bottom: 1px solid var(--docs-line); }
.doc-table td { padding: 12px 14px; color: #41566c; line-height: 1.55; border-bottom: 1px solid #edf1f5; vertical-align: top; }
.doc-table tr:last-child td { border-bottom: 0; }
.table-doc-link { display: inline-flex; align-items: center; gap: 6px; padding: 0; color: var(--docs-blue); font: inherit; font-weight: 650; text-align: left; background: transparent; border: 0; cursor: pointer; }
.table-doc-link:hover span { text-decoration: underline; text-underline-offset: 3px; }
.table-doc-link:focus-visible { outline: 3px solid rgba(37, 99, 235, 0.24); outline-offset: 3px; border-radius: 3px; }
.table-doc-link .anticon { font-size: 11px; transition: transform 160ms ease; }
.table-doc-link:hover .anticon { transform: translateX(2px); }

:deep(.code-shell) { position: relative; overflow: hidden; margin: 16px 0; background: #0b1f33; border: 1px solid #243d56; border-radius: 10px; }
:deep(.code-shell pre) { margin: 0; padding: 20px; overflow-x: auto; color: #dce9f5; font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; line-height: 1.75; }
:deep(.copy-code) { position: absolute; top: 9px; right: 9px; padding: 4px 8px; color: #b9cadb; background: #17334f; border: 1px solid #36536e; border-radius: 5px; cursor: pointer; }
:deep(.copy-code:hover) { color: #fff; }

.doc-callout { display: flex; gap: 12px; margin: 20px 0; padding: 15px 16px; color: #174e91; background: #eef5ff; border-left: 3px solid var(--docs-blue); border-radius: 0 8px 8px 0; }
.doc-callout.warning { color: #81510d; background: #fff7e8; border-left-color: var(--docs-amber); }
.doc-callout strong { display: block; margin-bottom: 3px; }
.doc-callout p { margin: 0; color: inherit; font-size: 13px; line-height: 1.65; }

.doc-figure { margin: 24px 0; overflow: hidden; background: #f8fafc; border: 1px solid var(--docs-line); border-radius: 12px; }
.doc-figure img { display: block; width: 100%; cursor: zoom-in; }
.doc-figure figcaption { padding: 11px 14px; color: #6b7b8b; font-size: 12px; border-top: 1px solid var(--docs-line); }
.preview-image { display: block; width: 100%; max-height: 82vh; object-fit: contain; }
.feature-link { margin-top: 8px; }
.example-download { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: 12px; margin-top: 16px; padding: 14px 16px; color: #174f91; background: #f3f8ff; border: 1px solid #cbdcf0; border-radius: 10px; transition: 160ms ease; }
.example-download:hover { color: #123f75; border-color: #8fb4df; box-shadow: 0 8px 22px rgba(23, 79, 145, 0.09); transform: translateY(-1px); }
.example-download > .anticon:first-child { display: grid; width: 34px; height: 34px; place-items: center; background: #e1edfb; border-radius: 8px; font-size: 17px; }
.example-download > span { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.example-download strong { font-size: 13px; }
.example-download small { overflow: hidden; color: #607c98; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }

.article-pagination { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 70px; padding-top: 24px; border-top: 1px solid var(--docs-line); }
.article-pagination button { display: flex; min-height: 74px; flex-direction: column; align-items: flex-start; gap: 6px; padding: 14px 16px; color: var(--docs-ink); text-align: left; background: #f8fafc; border: 1px solid var(--docs-line); border-radius: 10px; cursor: pointer; }
.article-pagination button:hover { border-color: #9eb9ed; }
.article-pagination button.next { align-items: flex-end; text-align: right; }
.article-pagination small { color: #7a8999; }
.article-pagination span { font-weight: 650; }

.docs-toc { overflow-y: auto; padding: 36px 24px 48px 20px; background: #fff; border-left: 1px solid var(--docs-line); }
.toc-label { margin-bottom: 12px; color: #7a8999; font-size: 11px; font-weight: 750; letter-spacing: 0.08em; text-transform: uppercase; }
.docs-toc a { display: block; padding: 6px 0; color: #6a7b8d; font-size: 12px; line-height: 1.5; }
.docs-toc a:hover { color: var(--docs-blue); }
.copy-toast { position: fixed; z-index: 60; right: 24px; bottom: 24px; padding: 9px 14px; color: #fff; background: var(--docs-ink); border-radius: 8px; box-shadow: 0 12px 30px rgba(11, 31, 51, 0.2); }

@media (max-width: 1180px) {
  .docs-header { grid-template-columns: minmax(220px, 1fr) minmax(260px, 420px) auto; }
  .docs-layout { grid-template-columns: 250px minmax(0, 1fr); }
  .docs-toc { display: none; }
  .back-button span:not(.anticon) { display: none; }
  .ask-ai-button span:not(.anticon) { display: none; }
}

@media (max-width: 820px) {
  .docs-header { grid-template-columns: minmax(0, 1fr) auto; gap: 10px; padding: 0 14px; }
  .header-search, .docs-sidebar, .back-button { display: none; }
  .header-actions { gap: 8px; }
  .mobile-menu-button { display: inline-flex; }
  .docs-language { width: 106px; }
  .brand-name { max-width: 180px; font-size: 13px; }
  .docs-layout { display: block; }
  .docs-article-scroll { height: 100%; }
  .docs-article { width: min(100% - 32px, 760px); padding-top: 40px; }
  .article-heading h1 { font-size: 34px; }
  .scenario-brief { grid-template-columns: 40px 1fr; }
  .scenario-brief-mark { grid-row: 1 / 4; }
  .scenario-brief-item { padding: 10px 13px; }
  .scenario-flow { flex-direction: column; overflow-x: visible; }
  .scenario-flow-node { min-width: 0; flex: none; width: 100%; min-height: 62px; }
  .scenario-flow-arrow { transform: rotate(90deg); }
  .governance-diagram { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .skill-scan-logic { padding: 14px; }
  .skill-scan-logic.fullscreen { padding: 64px 14px 20px; }
  .scan-logic-start, .scan-logic-heading { grid-template-columns: 1fr; }
  .scan-analyzer-grid, .scan-classification-grid, .scan-llm-row, .scan-admission-grid { grid-template-columns: 1fr; }
  .scan-policy-row { grid-template-columns: 1fr; }
  .scan-policy-row > .anticon { transform: rotate(90deg); }
  .scan-deterministic-result { align-items: flex-start; flex-direction: column; }
  .role-grid { grid-template-columns: 1fr; }
  .platform-map { grid-template-columns: 1fr; }
  .platform-foundation { grid-column: 1; }
  .system-architecture { padding: 14px; }
  .system-architecture.fullscreen { padding: 64px 14px 20px; }
  .architecture-caller-grid, .architecture-control-grid, .architecture-domain-grid, .architecture-foundation-grid { grid-template-columns: 1fr; }
  .architecture-ingress { grid-template-columns: 1fr; gap: 5px; }
  .architecture-ingress > .architecture-ingress-roles { grid-template-columns: 1fr; }
  .architecture-plane-heading { grid-template-columns: 1fr; }
  .architecture-plane-heading > small { grid-column: 1; }
  .architecture-dependencies { grid-template-columns: 1fr; }
  .architecture-dependencies > div { flex-wrap: wrap; justify-content: flex-start; }
  .topology-entry-nodes { grid-template-columns: 1fr; }
  .topology-ingress { grid-template-columns: 1fr; gap: 5px; }
  .topology-control, .topology-bottom, .topology-backend-links { grid-template-columns: 1fr; }
  .topology-backend-links { display: none; }
  .article-section { padding-top: 44px; }
}

@media (max-width: 520px) {
  .brand-docs { display: none; }
  .brand-name { max-width: 138px; }
  .docs-logo { height: 30px; }
  .article-heading p { font-size: 15px; }
  .docker-topology { padding: 14px; }
  .docker-volumes { grid-template-columns: 1fr; }
  .article-pagination { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; }
}
</style>
