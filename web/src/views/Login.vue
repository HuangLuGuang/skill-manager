<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <img :src="logoUrl" alt="Logo" class="login-logo" />
        <h2 class="login-title">{{ systemName }}</h2><p v-if="companyName" class="login-company">{{ companyName }}</p>
      </div>
      <a-form layout="vertical" :model="formState" @finish="onFinish">
        <a-form-item :label="$t('legacy.lleewp')" name="username" :rules="[{ required: true, message: $t('legacy.1d52hvl') }]">
          <a-input v-model:value="formState.username" placeholder="admin / email@example.com" size="large">
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item :label="$t('legacy.1aph6eg')" name="password" :rules="[{ required: true, message: $t('legacy.f478sb') }]">
          <a-input-password v-model:value="formState.password" :placeholder="$t('legacy.f478sb')" size="large">
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>
        <a-form-item :label="$t('legacy.jyzd1p')" name="captchaCode" :rules="[{ required: true, message: $t('legacy.royb2k') }]">
          <div class="captcha-wrapper">
            <div class="captcha-input-wrapper">
              <a-input v-model:value="formState.captchaCode" :placeholder="$t('legacy.royb2k')" size="large">
                <template #prefix><SafetyCertificateOutlined /></template>
              </a-input>
              <a class="captcha-refresh-link" @click="refreshCaptcha">{{ $t("legacy.gfum6v") }}</a>
            </div>
            <img v-if="captchaImage" :src="captchaImage" :alt="$t('legacy.jyzd1p')" class="captcha-img" @click="refreshCaptcha" />
          </div>
        </a-form-item>
        <a-form-item>
          <a-button type="primary" html-type="submit" :loading="loading" block size="large">{{ $t("legacy.1yggxgd") }}</a-button>
        </a-form-item>
      </a-form>
    </div>
  </div>
</template>

<script setup>
import { translateLegacy as phrase } from '../i18n'

import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons-vue'

import { getCaptcha, getMe, login } from '../api'
import { setLocale } from '../i18n'
import { useBranding, loadBranding } from '../branding'

const router = useRouter()
const { t } = useI18n()
const loading = ref(false)
const captchaImage = ref('')
const captchaId = ref('')
const { logoUrl, systemName, companyName } = useBranding()

const formState = reactive({
  username: 'admin',
  password: '',
  captchaCode: '',
})

const refreshCaptcha = async () => {
  try {
    const res = await getCaptcha()
    captchaId.value = res.captcha_id
    captchaImage.value = res.image
    formState.captchaCode = ''
  } catch {
    message.error(phrase('legacy.vlz0kc'))
  }
}

const onFinish = async () => {
  loading.value = true
  try {
    const res = await login(formState.username, formState.password, captchaId.value, formState.captchaCode)
    localStorage.setItem('token', res.access_token)
    const me = await getMe()
    localStorage.setItem('username', me.username)
    if (me.preferred_locale) setLocale(me.preferred_locale)
    message.success(phrase('legacy.1snukxk'))
    router.push(me.default_path || '/access-denied')
  } catch (error) {
    message.error(error.response?.data?.detail || phrase('legacy.rn5blf'))
    refreshCaptcha()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await refreshCaptcha()
  try {
    await loadBranding()
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
  max-width: calc(100vw - 24px);
  box-sizing: border-box;
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
  max-width: 100%;
  object-fit: contain;
  margin-bottom: 16px;
}

.login-title {
  margin-bottom: 8px;
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
</style>

<style scoped>
.login-company { text-align: center; color: #64748b; overflow-wrap: anywhere; }
.login-title { overflow-wrap: anywhere; }
</style>
