<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <img :src="logoUrl" alt="Logo" class="login-logo" />
        <h2 class="login-title">Agent Manager Console</h2>
        <p class="login-desc">AI 智能体全生命周期管理平台</p>
      </div>
      <a-form layout="vertical" :model="formState" @finish="onFinish">
        <a-form-item label="用户名/邮箱" name="username" :rules="[{ required: true, message: '请输入用户名或邮箱' }]">
          <a-input v-model:value="formState.username" placeholder="admin / email@example.com" size="large">
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="密码" name="password" :rules="[{ required: true, message: '请输入密码' }]">
          <a-input-password v-model:value="formState.password" placeholder="请输入密码" size="large">
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>
        <a-form-item label="验证码" name="captchaCode" :rules="[{ required: true, message: '请输入验证码' }]">
          <div class="captcha-wrapper">
            <div class="captcha-input-wrapper">
              <a-input v-model:value="formState.captchaCode" placeholder="请输入验证码" size="large">
                <template #prefix><SafetyCertificateOutlined /></template>
              </a-input>
              <a class="captcha-refresh-link" @click="refreshCaptcha">看不清？换一个</a>
            </div>
            <img v-if="captchaImage" :src="captchaImage" alt="验证码" class="captcha-img" @click="refreshCaptcha" />
          </div>
        </a-form-item>
        <a-form-item>
          <a-button type="primary" html-type="submit" :loading="loading" block size="large">登录</a-button>
        </a-form-item>
      </a-form>
      <div class="login-footer">默认账号 `admin`，默认密码 `Admin@123`</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons-vue'

import { getCaptcha, getLogoInfo, getMe, login } from '../api'

const router = useRouter()
const loading = ref(false)
const captchaImage = ref('')
const captchaId = ref('')
const logoUrl = ref('/logo.png')

const formState = reactive({
  username: 'admin',
  password: 'Admin@123',
  captchaCode: '',
})

const refreshCaptcha = async () => {
  try {
    const res = await getCaptcha()
    captchaId.value = res.captcha_id
    captchaImage.value = res.image
    formState.captchaCode = ''
  } catch {
    message.error('获取验证码失败')
  }
}

const onFinish = async () => {
  loading.value = true
  try {
    const res = await login(formState.username, formState.password, captchaId.value, formState.captchaCode)
    localStorage.setItem('token', res.access_token)
    const me = await getMe()
    localStorage.setItem('username', me.username)
    message.success('登录成功')
    router.push('/dashboard')
  } catch (error) {
    message.error(error.response?.data?.detail || '登录失败')
    refreshCaptcha()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await refreshCaptcha()
  try {
    const res = await getLogoInfo()
    if (res.logo_url) {
      logoUrl.value = `${res.logo_url}?t=${Date.now()}`
    }
  } catch {
    // ignore
  }
})
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f7fafc 0%, #e6f4ff 100%);
}

.login-box {
  width: 400px;
  padding: 32px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.12);
}

.login-header {
  text-align: center;
  margin-bottom: 28px;
}

.login-logo {
  height: 56px;
  margin-bottom: 16px;
}

.login-title {
  margin-bottom: 8px;
}

.login-desc {
  color: #8c8c8c;
  font-size: 13px;
}

.captcha-wrapper {
  display: flex;
  gap: 12px;
}

.captcha-input-wrapper {
  flex: 1;
}

.captcha-refresh-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
}

.captcha-img {
  width: 132px;
  height: 40px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
}

.login-footer {
  margin-top: 16px;
  font-size: 12px;
  color: #8c8c8c;
  text-align: center;
}
</style>
