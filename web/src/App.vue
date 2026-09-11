<template>
  <a-config-provider :locale="antdLocale">
    <div v-if="authChecking" class="app-loading">
      <a-spin size="large" :tip="$t('legacy.1ns3eta')" />
    </div>
    <a-layout v-else class="app-shell">
      <a-layout-header v-if="!isLoginPage && !isDocsPage" class="app-header">
        <a-button v-if="narrowNavigation" type="text" :aria-label="t('iam.toggleNavigation')" :aria-expanded="!navigationCollapsed" @click="navigationCollapsed = !navigationCollapsed">
          <MenuOutlined />
        </a-button>
        <div class="app-brand">
          <img :src="logoUrl" alt="Logo" class="app-logo" />
          <div>
            <div class="app-title">{{ t('app.name') }}</div>
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
          <a-dropdown>
            <template v-if="userInfo">
            <a class="ant-dropdown-link" @click.prevent>
              {{ userInfo.username }}
              <DownOutlined />
            </a>
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

      <a-layout v-if="!isLoginPage && !isDocsPage" class="app-main-layout">
        <a-layout-sider v-model:collapsed="navigationCollapsed" width="240" breakpoint="md" :collapsed-width="0" :trigger="null" class="app-sider" @breakpoint="narrow => { narrowNavigation = narrow; navigationCollapsed = narrow }">
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
        <a-layout-content class="app-content">
          <router-view :key="locale" />
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

import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import enUS from 'ant-design-vue/es/locale/en_US'
import { message } from 'ant-design-vue'
import {
  AuditOutlined,
  BarChartOutlined,
  CheckSquareOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  DesktopOutlined,
  DownOutlined,
  ApiOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  KeyOutlined,
  LockOutlined,
  MenuOutlined,
  LogoutOutlined,
  QuestionCircleOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'

const narrowNavigation = ref(false)
const navigationCollapsed = ref(false)

import { changePassword, checkSession, getLogoInfo, getMcpApprovalRequestStats, getMe, getSystemCapabilities, updateMyLocale } from './api'
import { DEFAULT_FEATURE_FLAGS, filterNavigationByFeatures, normalizeFeatureFlags } from './features'
import { setLocale, translateLegacy } from './i18n'
import { resolveMenuKey } from './navigation'
import { accessState, navigationEntries, navigationParents, refreshAccess, clearAccess, pageAllowed, can } from './access'

const router = useRouter()
const route = useRoute()
const { t, locale } = useI18n()
const userInfo = ref(null)
const authChecking = ref(true)
const passwordVisible = ref(false)
const passwordSaving = ref(false)
const logoUrl = ref('/logo.png')
const selectedKeys = ref([route.path])
const openKeys = ref(['capability-governance'])
const pendingMcpApprovals = ref(0)
const featureFlags = ref({ ...DEFAULT_FEATURE_FLAGS })
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const iconMap = {
  api: ApiOutlined,
  audit: AuditOutlined,
  barChart: BarChartOutlined,
  checkSquare: CheckSquareOutlined,
  dashboard: DashboardOutlined,
  deployment: DeploymentUnitOutlined,
  desktop: DesktopOutlined,
  fileSearch: FileSearchOutlined,
  fileText: FileTextOutlined,
  key: KeyOutlined,
  agent: DeploymentUnitOutlined,
  safety: SafetyCertificateOutlined,
  setting: SettingOutlined,
  team: TeamOutlined,
  upload: UploadOutlined,
}

const antdLocale = computed(() => locale.value === 'en-US' ? enUS : zhCN)

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

const loadLogo = async () => {
  try {
    const res = await getLogoInfo()
    if (res.logo_url) {
      logoUrl.value = `${res.logo_url}?t=${Date.now()}`
    }
  } catch {
    // ignore
  }
}

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
  align-items: center;
  justify-content: space-between;
  background: #f7fbff;
  border-bottom: 1px solid #d9e6f2;
  padding-inline: 24px;
  min-height: 72px;
  height: auto;
}

.app-main-layout {
  min-height: 0;
  flex: 1;
  height: auto;
  overflow: hidden;
}

.app-brand {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 72px;
  padding-block: 10px;
}

.app-logo {
  height: 42px;
}

.app-title {
  font-size: 18px;
  font-weight: 700;
  color: #16324f;
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
  background: #fffdf7;
  border-right: 1px solid #eee2c4;
  height: 100%;
  overflow-y: auto;
}

.app-content {
  min-width: 0;
  height: 100%;
  padding: 24px;
  overflow-y: auto;
  background: linear-gradient(180deg, #fffdf7 0%, #f7fbff 100%);
}

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

  .app-logo { height: 32px; }
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
  .app-content { padding: 14px 12px 20px; }
  .app-main-layout { position: relative; }
  .app-sider {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: 20;
  }
  .app-sider :deep(.ant-layout-sider-children) { overflow-y: auto; }
}
</style>
