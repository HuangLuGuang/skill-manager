<template>
  <a-config-provider :locale="zhCN">
    <div v-if="authChecking" class="app-loading">
      <a-spin size="large" tip="正在检查登录状态..." />
    </div>
    <a-layout v-else class="app-shell">
      <a-layout-header v-if="!isLoginPage" class="app-header">
        <div class="app-brand">
          <img :src="logoUrl" alt="Logo" class="app-logo" />
          <div>
            <div class="app-title">Agent Manager Console</div>
            <div class="app-subtitle">AI 智能体全生命周期管理平台</div>
          </div>
        </div>
        <div v-if="userInfo" class="app-user">
          <a-dropdown>
            <a class="ant-dropdown-link" @click.prevent>
              {{ userInfo.username }}
              <DownOutlined />
            </a>
            <template #overlay>
              <a-menu>
                <a-menu-item key="password" @click="passwordVisible = true">修改密码</a-menu-item>
                <a-menu-item key="logout" @click="handleLogout">退出登录</a-menu-item>
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
          <router-view />
        </a-layout-content>
      </a-layout>

      <a-layout-content v-else>
        <router-view />
      </a-layout-content>
    </a-layout>

    <a-modal v-model:open="passwordVisible" title="修改密码" @ok="handlePasswordOk">
      <a-form layout="vertical">
        <a-form-item label="旧密码">
          <a-input-password v-model:value="passwordForm.oldPassword" />
        </a-form-item>
        <a-form-item label="新密码">
          <a-input-password v-model:value="passwordForm.newPassword" />
        </a-form-item>
        <a-form-item label="确认新密码">
          <a-input-password v-model:value="passwordForm.confirmPassword" />
        </a-form-item>
      </a-form>
    </a-modal>
  </a-config-provider>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { message } from 'ant-design-vue'
import {
  AuditOutlined,
  BarChartOutlined,
  CheckSquareOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
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

import { changePassword, checkSession, getLogoInfo, getMe } from './api'
import { findMenuOpenKeys, navigationItems, resolveMenuKey } from './navigation'

const router = useRouter()
const route = useRoute()
const userInfo = ref(null)
const authChecking = ref(true)
const passwordVisible = ref(false)
const logoUrl = ref('/logo.png')
const selectedKeys = ref([route.path])
const openKeys = ref(['agent-governance'])
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
  fileSearch: FileSearchOutlined,
  fileText: FileTextOutlined,
  key: KeyOutlined,
  agent: DeploymentUnitOutlined,
  safety: SafetyCertificateOutlined,
  setting: SettingOutlined,
  team: TeamOutlined,
  upload: UploadOutlined,
}

const buildMenuItem = (item) => ({
  key: item.key,
  label: item.label,
  icon: item.icon && iconMap[item.icon] ? h(iconMap[item.icon]) : undefined,
  children: item.children?.map(buildMenuItem),
})

const menuItems = computed(() => navigationItems.map(buildMenuItem))

let sessionCheckTimer = null

const isLoginPage = computed(() => route.name === 'login')

watch(
  () => route.path,
  (path) => {
    selectedKeys.value = [resolveMenuKey(path)]
    const nextOpenKeys = findMenuOpenKeys(path)
    openKeys.value = nextOpenKeys.length ? nextOpenKeys : ['agent-governance']
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
      } catch {
        localStorage.removeItem('token')
        userInfo.value = null
        router.push('/login')
      }
    }
    if (isLogin) {
      userInfo.value = null
      stopSessionCheck()
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

const loadProfile = async () => {
  const me = await getMe()
  userInfo.value = me
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
  router.push('/login')
}

const handlePasswordOk = async () => {
  if (!passwordForm.oldPassword || !passwordForm.newPassword) {
    message.error('请填写完整密码信息')
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    message.error('两次输入的新密码不一致')
    return
  }
  await changePassword(passwordForm.oldPassword, passwordForm.newPassword)
  message.success('密码已更新，请重新登录')
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
  } catch {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    userInfo.value = null
    router.push('/login')
  } finally {
    authChecking.value = false
  }
})

onUnmounted(() => stopSessionCheck())
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

.app-subtitle {
  font-size: 12px;
  color: #5a7188;
  line-height: 1.4;
  margin-top: 4px;
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
