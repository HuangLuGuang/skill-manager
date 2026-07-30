import { createI18n } from 'vue-i18n'

import { domainKey, domainMessages } from './domain.js'
import { legacyKey, legacyMessages } from './legacy.js'

export const LOCALE_STORAGE_KEY = 'agent-manager-locale'
export const SUPPORTED_LOCALES = ['zh-CN', 'en-US']

const detectLocale = () => {
  const saved = localStorage.getItem(LOCALE_STORAGE_KEY)
  if (SUPPORTED_LOCALES.includes(saved)) return saved
  return navigator.language?.toLowerCase().startsWith('en') ? 'en-US' : 'zh-CN'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': {
      app: {
        name: '智能体生命周期管理系统',
        subtitle: 'AI 智能体全生命周期管理平台',
      },
      language: {
        label: '语言',
        chinese: '简体中文',
        english: 'English',
      },
      login: {
        defaultCredentials: '默认账号 `admin`，默认密码 `Admin{at}123`',
      },
      skillVersions: {
        versions: '版本',
        diff: '版本差异',
        version: '版本',
        sourceVersion: '来源版本',
        status: '状态',
        risk: '风险',
        scannedAt: '检测时间',
        actions: '操作',
        latest: '最新版本',
        latestTrusted: '最新可信版本',
        trustedOnlyHint: '客户端只能安装或恢复已批准的可信版本。',
        baseVersion: '基准版本',
        targetVersion: '目标版本',
        sideBySide: '并排对比',
        inline: '单栏对比',
        swapVersions: '交换左右版本',
        selectFile: '选择差异文件',
        before: '基准版本',
        after: '目标版本',
        file: '文件',
        fileAdded: '新增文件',
        fileDeleted: '删除文件',
        fileChanged: '已修改',
        additions: '新增',
        deletions: '删除',
        noChanges: '两个版本没有文本文件差异',
        rescan: '重新检测',
        scanning: '检测中',
        download: '下载版本',
        scanRuns: '检测记录',
        runStatus: '执行状态',
        startedAt: '开始时间',
        finishedAt: '结束时间',
        forced: '强制检测',
        reusedFrom: '复用来源记录',
        yes: '是',
        no: '否',
        scanRunsLoadFailed: '读取检测记录失败',
        loadFailed: '读取版本失败',
        diffLoadFailed: '读取版本差异失败',
        downloadFailed: '下载版本失败',
        rescanSubmitted: '已提交重新检测',
        rescanFailed: '重新检测失败',
      },
      policySettings: {
        submissionAndScan: '提交与检测',
        reuseScanResults: '复用相同内容的检测结果',
        reuseScanResultsHint: '仅当内容指纹和检测上下文完全一致时复用；平台“重新检测”始终强制执行新检测。',
      },
      domain: domainMessages['zh-CN'],
      legacy: legacyMessages['zh-CN'],
    },
    'en-US': {
      app: {
        name: 'Agent Manager',
        subtitle: 'AI agent lifecycle governance platform',
      },
      language: {
        label: 'Language',
        chinese: '简体中文',
        english: 'English',
      },
      login: {
        defaultCredentials: 'Default account: `admin`; default password: `Admin{at}123`',
      },
      skillVersions: {
        versions: 'Versions',
        diff: 'Diff',
        version: 'Version',
        sourceVersion: 'Source Version',
        status: 'Status',
        risk: 'Risk',
        scannedAt: 'Scanned At',
        actions: 'Actions',
        latest: 'Latest',
        latestTrusted: 'Latest Trusted',
        trustedOnlyHint: 'Clients can only install or restore approved trusted versions.',
        baseVersion: 'Base Version',
        targetVersion: 'Target Version',
        sideBySide: 'Side-by-side',
        inline: 'Inline',
        swapVersions: 'Swap versions',
        selectFile: 'Select changed file',
        before: 'Base',
        after: 'Target',
        file: 'File',
        fileAdded: 'Added',
        fileDeleted: 'Deleted',
        fileChanged: 'Changed',
        additions: 'Additions',
        deletions: 'Deletions',
        noChanges: 'No text-file differences between these versions',
        rescan: 'Rescan',
        scanning: 'Scanning',
        download: 'Download Version',
        scanRuns: 'Scan Runs',
        runStatus: 'Run Status',
        startedAt: 'Started At',
        finishedAt: 'Finished At',
        forced: 'Forced',
        reusedFrom: 'Reused From',
        yes: 'Yes',
        no: 'No',
        scanRunsLoadFailed: 'Failed to load scan runs',
        loadFailed: 'Failed to load versions',
        diffLoadFailed: 'Failed to load version diff',
        downloadFailed: 'Failed to download version',
        rescanSubmitted: 'Rescan submitted',
        rescanFailed: 'Failed to rescan',
      },
      policySettings: {
        submissionAndScan: 'Submission and Scanning',
        reuseScanResults: 'Reuse results for identical content',
        reuseScanResultsHint: 'Results are reused only when content and scan context match. Rescan always runs a fresh scan.',
      },
      domain: domainMessages['en-US'],
      legacy: legacyMessages['en-US'],
    },
  },
})

export const setLocale = (locale) => {
  const next = SUPPORTED_LOCALES.includes(locale) ? locale : 'zh-CN'
  i18n.global.locale.value = next
  localStorage.setItem(LOCALE_STORAGE_KEY, next)
  document.documentElement.lang = next
  document.title = i18n.global.t('app.name')
  window.dispatchEvent(new CustomEvent('agent-manager-locale-change', { detail: next }))
}

export const getCurrentLocale = () => i18n.global.locale.value
export const translateLegacy = source =>
  i18n.global.t(String(source).startsWith('legacy.') ? source : legacyKey(source))
export const translateText = (chinese, english) =>
  getCurrentLocale() === 'en-US' ? english : chinese
export const translateDomain = (category, value, fallback = value) => {
  const key = domainKey(category, value)
  return i18n.global.te(key) ? i18n.global.t(key) : fallback
}
