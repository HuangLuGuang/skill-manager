<template>
  <a-config-provider :locale="antdLocale">
    <div v-if="authChecking" class="app-loading">
      <a-spin size="large" :tip="$t('legacy.1ns3eta')" />
    </div>
    <a-layout v-else class="app-shell">
      <a-layout-header v-if="!isLoginPage" class="app-header">
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
                <a-menu-item key="password" @click="passwordVisible = true">{{ $t("legacy.1pt7oo1") }}</a-menu-item>
                <a-menu-item key="logout" @click="handleLogout">{{ $t("legacy.12hokt7") }}</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </a-layout-header>

      <a-layout v-if="!isLoginPage" class="app-main-layout">
        <a-layout-sider width="240" class="app-sider">
          <a-menu
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

      <a-layout-content v-else class="login-content">
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
    </a-layout>

    <a-modal v-model:open="passwordVisible" :title="$t('legacy.1pt7oo1')" @ok="handlePasswordOk">
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
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'

import { changePassword, checkSession, getLogoInfo, getMcpApprovalRequestStats, getMe, updateMyLocale } from './api'
import { setLocale, translateLegacy } from './i18n'
import { findMenuOpenKeys, navigationItems, resolveMenuKey } from './navigation'

const router = useRouter()
const route = useRoute()
const { t, locale } = useI18n()
const userInfo = ref(null)
const authChecking = ref(true)
const passwordVisible = ref(false)
const logoUrl = ref('/logo.png')
const selectedKeys = ref([route.path])
const openKeys = ref(['capability-governance'])
const pendingMcpApprovals = ref(0)
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
  const label = item.label.includes('.') ? t(item.label) : translateLegacy(item.label)
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

const menuItems = computed(() => navigationItems.map(buildMenuItem))

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

watch(
  () => route.path,
  (path) => {
    selectedKeys.value = [resolveMenuKey(path)]
    const nextOpenKeys = findMenuOpenKeys(path)
    openKeys.value = nextOpenKeys.length ? nextOpenKeys : ['capability-governance']
  },
  { immediate: true },
)

watch(
  isLoginPage,
  async (isLogin, wasLogin) => {
    if (!isLogin && wasLogin && localStorage.getItem('token')) {
      try {
        await loadProfile()
        startSessionCheck()
        startApprovalStatsCheck()
      } catch {
        localStorage.removeItem('token')
        userInfo.value = null
        router.push('/login')
      }
    }
    if (isLogin) {
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
  userInfo.value = me
  if (me.preferred_locale && me.preferred_locale !== locale.value) {
    setLocale(me.preferred_locale)
  } else if (!me.preferred_locale) {
    await updateMyLocale(locale.value)
    me.preferred_locale = locale.value
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

const handleMenuClick = ({ key }) => router.push(key)

const handleLogout = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  userInfo.value = null
  stopSessionCheck()
  stopApprovalStatsCheck()
  router.push('/login')
}

const handlePasswordOk = async () => {
  if (!passwordForm.oldPassword || !passwordForm.newPassword) {
    message.error(phrase('legacy.ot6dw7'))
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    message.error(phrase('legacy.1c6u5vm'))
    return
  }
  await changePassword(passwordForm.oldPassword, passwordForm.newPassword)
  message.success(phrase('legacy.1fshup6'))
  passwordVisible.value = false
  handleLogout()
}

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
  height: calc(100vh - 72px);
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
  height: 100%;
  padding: 24px;
  overflow-y: auto;
  background: linear-gradient(180deg, #fffdf7 0%, #f7fbff 100%);
}
</style>
