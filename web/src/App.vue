<template>
  <a-config-provider :locale="antdLocale" :theme="appTheme">
    <div v-if="authChecking" class="app-loading">
      <a-spin size="large" :tip="$t('legacy.1ns3eta')" />
    </div>
    <a-layout v-else class="app-shell">
      <a-layout-header v-if="!isLoginPage && !isDocsPage" class="app-header">
        <a-tooltip :title="t(navigationCollapsed ? 'iam.expandNavigation' : 'iam.collapseNavigation')">
          <a-button type="text" :aria-label="t(navigationCollapsed ? 'iam.expandNavigation' : 'iam.collapseNavigation')" :aria-expanded="!navigationCollapsed" aria-controls="app-navigation" @click="navigationCollapsed = !navigationCollapsed">
            <MenuUnfoldOutlined v-if="navigationCollapsed" />
            <MenuFoldOutlined v-else />
          </a-button>
        </a-tooltip>
        <div class="app-brand">
          <img :src="logoUrl" alt="Logo" class="app-logo" />
          <div class="app-brand-text">
            <div class="app-title" :title="systemName">{{ systemName }}</div>
            <div v-if="companyName" class="app-company" :title="companyName">{{ companyName }}</div>
          </div>
        </div>
        <div class="app-user">
          <a-select
            v-model:value="locale"
            class="language-select"
            :aria-label="t('language.label')"
            @change="handleLocaleChange"
          >
            <a-select-option value="zh-CN">{{ t('language.chinese') }}</a-select-option>
            <a-select-option value="en-US">{{ t('language.english') }}</a-select-option>
          </a-select>
          <a-dropdown :trigger="['click']">
            <template v-if="userInfo">
            <a-button type="text" class="ant-dropdown-link" aria-haspopup="menu">
              {{ userInfo.username }}
              <DownOutlined />
            </a-button>
            </template>
            <template #overlay>
              <a-menu>
                <a-menu-item key="help" @click="openDocs">
                  <QuestionCircleOutlined />
                  {{ t('docsUi.help') }}
                </a-menu-item>
                <a-menu-divider />
                <a-menu-item key="password" @click="passwordVisible = true">
                  <LockOutlined />
                  {{ $t("legacy.1pt7oo1") }}
                </a-menu-item>
                <a-menu-item key="logout" @click="handleLogout">
                  <LogoutOutlined />
                  {{ $t("legacy.12hokt7") }}
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </a-layout-header>
      <div v-if="navigationPending" class="navigation-progress" role="status" :aria-label="t('uiExperience.loading')" />

      <a-layout v-if="!isLoginPage && !isDocsPage" class="app-main-layout" @keydown.esc="navigationCollapsed = narrowNavigation || navigationCollapsed">
        <a-layout-sider id="app-navigation" v-model:collapsed="navigationCollapsed" :width="216" breakpoint="md" :collapsed-width="narrowNavigation ? 0 : 64" :trigger="null" class="app-sider" @breakpoint="narrow => { narrowNavigation = narrow; navigationCollapsed = narrow }">
          <a-menu
            v-if="!narrowNavigation || !navigationCollapsed"
            :items="menuItems"
            :selectedKeys="selectedKeys"
            :openKeys="openKeys"
            mode="inline"
            @click="handleMenuClick"
            @openChange="keys => openKeys = keys"
          />
        </a-layout-sider>
        <button v-if="narrowNavigation && !navigationCollapsed" class="navigation-backdrop" :aria-label="t('iam.collapseNavigation')" @click="navigationCollapsed = true" />
        <a-layout-content ref="mainContent" class="app-content" :inert="narrowNavigation && !navigationCollapsed">
          <LicenseBanner />
          <!-- 响应式文案页面在切换语言时保留未保存输入和校验错误。 -->
          <router-view :key="['/policy', '/license', '/mcp-governance/debug', '/model-gateway/prompt-guard', '/model-gateway/stats'].includes(route.path) ? route.path : locale" />
        </a-layout-content>
      </a-layout>

      <a-layout-content v-else-if="isLoginPage" class="login-content">
        <a-select
          v-model:value="locale"
          class="login-language-select"
          :aria-label="t('language.label')"
          @change="handleLocaleChange"
        >
          <a-select-option value="zh-CN">{{ t('language.chinese') }}</a-select-option>
          <a-select-option value="en-US">{{ t('language.english') }}</a-select-option>
        </a-select>
        <router-view :key="locale" />
      </a-layout-content>

      <a-layout-content v-else class="docs-content">
        <router-view :key="locale" :logo-url="logoUrl" />
      </a-layout-content>
    </a-layout>

    <a-modal v-model:open="passwordVisible" :title="$t('legacy.1pt7oo1')" :confirm-loading="passwordSaving"
      :ok-button-props="{ disabled: passwordSaving }" :cancel-button-props="{ disabled: passwordSaving }"
      :closable="!passwordSaving" :mask-closable="!passwordSaving" :keyboard="!passwordSaving" @ok="handlePasswordOk">
      <a-form layout="vertical">
        <a-form-item :label="$t('legacy.ib9p03')">
          <a-input-password v-model:value="passwordForm.oldPassword" />
        </a-form-item>
        <a-form-item :label="$t('legacy.9sfqbi')">
          <a-input-password v-model:value="passwordForm.newPassword" />
        </a-form-item>
        <a-form-item :label="$t('legacy.1b253gw')">
          <a-input-password v-model:value="passwordForm.confirmPassword" />
        </a-form-item>
      </a-form>
    </a-modal>
  </a-config-provider>
</template>

<script setup>
import { translateLegacy as phrase } from './i18n'
import LicenseBanner from './components/LicenseBanner.vue'
import { useBranding, loadBranding } from './branding'
import { iconMap } from './menuIcons'

import { computed, h, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import enUS from 'ant-design-vue/es/locale/en_US'
import { message } from 'ant-design-vue'
import {
  DownOutlined,
  LockOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  LogoutOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons-vue'

const narrowNavigation = ref(false)
const navigationCollapsed = ref(false)

import { changePassword, checkSession, getMcpApprovalRequestStats, getMe, getSystemCapabilities, updateMyLocale } from './api'
import { DEFAULT_FEATURE_FLAGS, filterNavigationByFeatures, normalizeFeatureFlags } from './features'
import { setLocale, translateLegacy } from './i18n'
import { resolveMenuKey } from './navigation'
import { accessState, navigationEntries, navigationParents, refreshAccess, clearAccess, pageAllowed, can } from './access'

const router = useRouter()
const route = useRoute()
const mainContent = ref(null)
const navigationPending = ref(false)
const removeNavigationStart = router.beforeEach(() => { navigationPending.value = true })
const removeNavigationEnd = router.afterEach(() => { navigationPending.value = false })
const removeNavigationError = router.onError(() => { navigationPending.value = false })
watch(() => route.path, async () => {
  await nextTick()
  mainContent.value?.$el?.scrollTo({ top: 0, left: 0, behavior: 'instant' })
})
const { t, locale } = useI18n()
const userInfo = ref(null)
const authChecking = ref(true)
const passwordVisible = ref(false)
const passwordSaving = ref(false)
const { logoUrl, systemName, companyName } = useBranding()
watch([systemName, locale], ([value]) => { document.title = value }, { immediate: true })
const selectedKeys = ref([route.path])
const openKeys = ref(['capability-governance'])
const pendingMcpApprovals = ref(0)
const featureFlags = ref({ ...DEFAULT_FEATURE_FLAGS })
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})



const antdLocale = computed(() => locale.value === 'en-US' ? enUS : zhCN)
const appTheme = {
  token: {
    colorPrimary: '#2563eb',
    colorText: '#202630',
    colorTextSecondary: '#626b78',
    colorBorder: '#d7dce3',
    colorBorderSecondary: '#e7eaf0',
    borderRadius: 8,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  components: {
    Button: { primaryShadow: 'none', defaultShadow: 'none', dangerShadow: 'none' },
    Table: { headerBg: '#f6f7f9', headerColor: '#454e5c' },
    Menu: { itemSelectedBg: '#e9effc', itemSelectedColor: '#1d4ed8' },
  },
}

const buildMenuLabel = item => {
  const label = item.title_key ? t(item.title_key) : (locale.value === 'en-US' ? item.title_en : item.title_zh)
  if (item.badge !== 'mcpApprovals' || pendingMcpApprovals.value <= 0) return label
  return h('span', { style: 'display:flex;align-items:center;justify-content:space-between;width:100%;gap:8px' }, [
    h('span', label),
    h('span', {
      style: 'min-width:20px;height:20px;padding:0 6px;border-radius:10px;background:#cf1322;color:#fff;font-size:12px;line-height:20px;text-align:center',
    }, pendingMcpApprovals.value > 99 ? '99+' : String(pendingMcpApprovals.value)),
  ])
}

const buildMenuItem = (item) => ({
  key: item.key,
  label: buildMenuLabel(item),
  icon: item.icon && iconMap[item.icon] ? h(iconMap[item.icon]) : undefined,
  children: item.children?.map(buildMenuItem),
})

const menuItems = computed(() => filterNavigationByFeatures(navigationEntries(), featureFlags.value).map(buildMenuItem))

const handleLocaleChange = async (value) => {
  setLocale(value)
  if (localStorage.getItem('token')) {
    try {
      await updateMyLocale(value)
      if (userInfo.value) userInfo.value.preferred_locale = value
    } catch {
      // The local choice remains available when the server is temporarily unreachable.
    }
  }
}

let sessionCheckTimer = null
let approvalStatsTimer = null

const isLoginPage = computed(() => route.name === 'login')
const isDocsPage = computed(() => route.meta.layout === 'docs')

watch(
  () => route.path,
  (path) => {
    selectedKeys.value = [resolveMenuKey(path)]
    openKeys.value = navigationParents(path)
  },
  { immediate: true },
)

watch(
  isLoginPage,
  async (isLogin, wasLogin) => {
    if (!isLogin && wasLogin && localStorage.getItem('token')) {
      try {
        await loadProfile()
        await loadCapabilities()
        startSessionCheck()
        startApprovalStatsCheck()
      } catch {
        localStorage.removeItem('token')
        userInfo.value = null
        router.push('/login')
      }
    }
    if (isLogin) {
      clearAccess()
      userInfo.value = null
      stopSessionCheck()
      stopApprovalStatsCheck()
    }
  },
)

const startSessionCheck = () => {
  if (sessionCheckTimer) return
  sessionCheckTimer = setInterval(async () => {
    try {
      await checkSession()
      await refreshAccess()
      if (!pageAllowed(route.path)) router.replace(accessState.default_path)
    } catch {
      stopSessionCheck()
    }
  }, 15000)
}

const stopSessionCheck = () => {
  if (sessionCheckTimer) {
    clearInterval(sessionCheckTimer)
    sessionCheckTimer = null
  }
}

const refreshApprovalStats = async () => {
  if (!can('mcp:view')) return
  try {
    const data = await getMcpApprovalRequestStats()
    pendingMcpApprovals.value = Number(data.pending || 0)
  } catch {
    // Keep navigation available when the stats request temporarily fails.
  }
}

const startApprovalStatsCheck = () => {
  if (approvalStatsTimer) return
  refreshApprovalStats()
  approvalStatsTimer = setInterval(refreshApprovalStats, 15000)
}

const stopApprovalStatsCheck = () => {
  if (approvalStatsTimer) {
    clearInterval(approvalStatsTimer)
    approvalStatsTimer = null
  }
  pendingMcpApprovals.value = 0
}

const handleApprovalStatsEvent = event => {
  pendingMcpApprovals.value = Number(event.detail?.pending || 0)
}

const loadProfile = async () => {
  const me = await getMe()
  await refreshAccess()
  openKeys.value = navigationParents(route.path)
  userInfo.value = me
  if (me.preferred_locale && me.preferred_locale !== locale.value) {
    setLocale(me.preferred_locale)
  } else if (!me.preferred_locale) {
    await updateMyLocale(locale.value)
    me.preferred_locale = locale.value
  }
}

const loadCapabilities = async () => {
  try {
    const capabilities = await getSystemCapabilities()
    featureFlags.value = normalizeFeatureFlags(capabilities.features)
  } catch {
    featureFlags.value = { ...DEFAULT_FEATURE_FLAGS }
  }
}

const loadLogo = async () => { try { await loadBranding() } catch { /* Keep defaults when unavailable. */ } }

const handleMenuClick = ({ key }) => {
  if (narrowNavigation.value) navigationCollapsed.value = true
  router.push(key)
}

const openDocs = () => {
  const url = router.resolve('/docs').href
  window.open(url, '_blank', 'noopener,noreferrer')
}

const handleLogout = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  userInfo.value = null
  featureFlags.value = { ...DEFAULT_FEATURE_FLAGS }
  stopSessionCheck()
  stopApprovalStatsCheck()
  router.push('/login')
}

const handlePasswordOk = async () => {
  if (passwordSaving.value) return
  if (!passwordForm.oldPassword || !passwordForm.newPassword) {
    message.error(phrase('legacy.ot6dw7'))
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    message.error(phrase('legacy.1c6u5vm'))
    return
  }
  passwordSaving.value = true
  try {
    await changePassword(passwordForm.oldPassword, passwordForm.newPassword)
    message.success(phrase('legacy.1fshup6'))
    passwordVisible.value = false
    handleLogout()
  } catch (error) {
    message.error(error.response?.data?.detail || t('iam.failed'))
  } finally {
    passwordSaving.value = false
  }
}

watch(passwordVisible, open => {
  if (!open) Object.assign(passwordForm, { oldPassword: '', newPassword: '', confirmPassword: '' })
})

onMounted(async () => {
  if (isLoginPage.value) {
    authChecking.value = false
    await loadLogo()
    return
  }
  if (!localStorage.getItem('token')) {
    authChecking.value = false
    router.push('/login')
    return
  }
  try {
    await loadProfile()
    await loadCapabilities()
    await loadLogo()
    startSessionCheck()
    startApprovalStatsCheck()
  } catch {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    userInfo.value = null
    router.push('/login')
  } finally {
    authChecking.value = false
  }
})

onMounted(() => window.addEventListener('mcp-approval-stats', handleApprovalStatsEvent))

onUnmounted(() => {
  removeNavigationStart()
  removeNavigationEnd()
  removeNavigationError()
  stopSessionCheck()
  stopApprovalStatsCheck()
  window.removeEventListener('mcp-approval-stats', handleApprovalStatsEvent)
})
</script>

<style scoped>
.app-loading,
.app-shell {
  min-height: 100vh;
}

.app-loading {
  display: flex;
  align-items: center;
  justify-content: center;
}

.app-shell {
  height: 100vh;
  overflow: hidden;
}

.app-header {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e7eaf0;
  padding-inline: 24px;
  min-height: 64px;
  height: auto;
  line-height: normal;
}

.app-main-layout {
  min-height: 0;
  flex: 1;
  height: auto;
  overflow: hidden;
}

.app-brand {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 16px;
  min-height: 64px;
  padding-block: 10px;
}

.app-logo {
  height: 36px;
  max-width: 160px;
  object-fit: contain;
}

.app-title {
  font-size: 18px;
  font-weight: 600;
  color: #202630;
  line-height: 1.3;
}

.app-user {
  display: flex;
  align-items: center;
  gap: 16px;
}

.language-select {
  width: 132px;
}

.login-content {
  position: relative;
}

.docs-content {
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
  background: #f6f8fb;
}

.login-language-select {
  position: fixed;
  z-index: 20;
  top: 20px;
  right: 24px;
  width: 132px;
}

.app-sider {
  background: #f8f9fb;
  border-right: 1px solid #e7eaf0;
  height: 100%;
  overflow-y: auto;
}

.app-content {
  min-width: 0;
  height: 100%;
  padding: 24px;
  overflow-y: auto;
  background: #f5f6f8;
}

.app-content :deep(.ant-page-header) { padding: 0; }
.navigation-backdrop { position: absolute; inset: 0; z-index: 19; padding: 0; border: 0; background: rgb(15 23 42 / 24%); cursor: pointer; }
.navigation-progress { position: absolute; top: 0; left: 0; z-index: 100; height: 3px; width: 100%; background: #2563eb; transform-origin: left; animation: navigation-loading 1s ease-in-out infinite alternate; }
@keyframes navigation-loading { from { transform: scaleX(.15); } to { transform: scaleX(.9); } }

@media (max-width: 767px) {
  .app-header {
    min-height: 60px;
    gap: 12px;
    padding-inline: 12px;
  }

  .app-brand {
    min-width: 0;
    min-height: 60px;
    gap: 8px;
    padding-block: 8px;
  }

  .app-logo { height: 32px; max-width: 72px; }
  .app-title { display: none; }
  .app-user { min-width: 0; gap: 8px; }
  .language-select { width: 108px; }
  .ant-dropdown-link {
    display: block;
    max-width: 88px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .app-content { padding: 12px; }
  .app-content :deep(.ant-page-header-heading-left) { flex-wrap: wrap; min-width: 0; }
  .app-content :deep(.ant-page-header-heading-title),
  .app-content :deep(.ant-page-header-heading-sub-title) { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
  .app-content :deep(.ant-page-header-heading-sub-title) { flex-basis: 100%; }
  .app-main-layout { position: relative; }
  .app-sider {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: 20;
  }
  .app-sider :deep(.ant-layout-sider-children) { overflow-y: auto; }
}
</style>

<style scoped>
.app-brand-text { display: flex; flex-direction: column; justify-content: center; gap: 4px; min-width: 0; }
.app-company { font-size: 12px; line-height: 1.4; color: #64748b; width: 100%; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-title { max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 767px) { .app-company { max-width: 80px; } }
</style>
