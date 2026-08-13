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

            <div v-if="section.diagram === 'governance'" class="governance-diagram">
              <div v-for="(label, index) in governanceLabels" :key="label" class="governance-step">
                <span>{{ index + 1 }}</span>
                <strong>{{ label }}</strong>
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
                <div><small>{{ dockerLabels.publicIngress }}</small><strong>Nginx <b>:80</b></strong></div>
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
  FileSearchOutlined,
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

watch(currentSlug, async slug => {
  if (!content.value.articles[slug]) {
    router.replace('/docs')
    return
  }
  await nextTick()
  articleScroller.value?.scrollTo({ top: 0 })
  document.title = `${article.value.title} · ${t('app.name')}`
}, { immediate: true })

onMounted(async () => {
  if (route.hash) nextTick(() => document.querySelector(route.hash)?.scrollIntoView({ block: 'start' }))
  try {
    docsAssistantConfig.value = await getDocsAssistantConfig()
  } catch {
    docsAssistantConfig.value = { enabled: false, common_questions: [], max_context_sections: 4 }
  }
})
onBeforeUnmount(() => {
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
  grid-template-columns: 268px minmax(0, 1fr) 224px;
  height: calc(100vh - 68px);
  max-width: 1600px;
  margin: 0 auto;
}
.docs-sidebar { overflow-y: auto; padding: 28px 20px 48px 24px; background: #f6f8fb; border-right: 1px solid var(--docs-line); }
:deep(.docs-nav) { display: flex; flex-direction: column; gap: 22px; }
:deep(.nav-group-title) { margin: 0 10px 8px; color: #7a8999; font-size: 11px; font-weight: 750; letter-spacing: 0.1em; text-transform: uppercase; }
:deep(.nav-subgroup-title) { display: flex; align-items: center; gap: 8px; margin: 12px 10px 5px; color: #526579; font-size: 12px; font-weight: 720; }
:deep(.nav-subgroup-title)::after { flex: 1; height: 1px; background: #dfe6ee; content: ''; }
:deep(.nav-item) { display: flex; width: 100%; flex-direction: column; gap: 2px; padding: 9px 10px; color: #33485f; text-align: left; background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
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

.governance-diagram { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin: 24px 0; }
.governance-step { position: relative; display: flex; min-height: 86px; flex-direction: column; justify-content: center; gap: 8px; padding: 13px; background: #f5f8fc; border: 1px solid var(--docs-line); border-radius: 9px; }
.governance-step span { color: var(--docs-blue); font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }
.governance-step strong { font-size: 12px; }

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
  .governance-diagram { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .role-grid { grid-template-columns: 1fr; }
  .platform-map { grid-template-columns: 1fr; }
  .platform-foundation { grid-column: 1; }
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
