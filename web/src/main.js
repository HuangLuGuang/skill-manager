import { createApp } from 'vue'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'

import App from './App.vue'
import { i18n } from './i18n'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(Antd)
app.use(i18n)
app.use(router)
router.isReady().then(() => {
  app.mount('#app')
})
