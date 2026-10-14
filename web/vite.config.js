import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { docsContentPlugin } from './docs-content-plugin.js'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue(), docsContentPlugin()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue', 'vue-router'],
          antd: ['ant-design-vue', '@ant-design/icons-vue'],
          charts: ['echarts'],
          x6: ['@antv/x6', '@antv/x6-vue-shape'],
          markdown: ['marked'],
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        // rewrite: (path) => path.replace(/^\/api/, '') // Backend prefix is /api, so no rewrite needed if backend expects /api
      },
      '/mcp/': {
        target: 'http://127.0.0.1:8001',
        // Keep the browser Host/Origin aligned with the MCP DNS-rebinding check.
        changeOrigin: false,
      }
    }
  }
})
