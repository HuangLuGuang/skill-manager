// 纯格式化逻辑供上传大小和通用展示复用，避免小文件被 MiB 舍入为零。
export const formatFileSize = (value, locale, { byteUnit = 'B', fractionDigits } = {}) => {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  if (bytes < 1024) return `${new Intl.NumberFormat(locale).format(bytes)} ${byteUnit}`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = bytes / 1024
  let unit = units[0]
  for (let index = 1; size >= 1024 && index < units.length; index += 1) {
    size /= 1024
    unit = units[index]
  }
  return `${new Intl.NumberFormat(locale, { minimumFractionDigits: fractionDigits ?? 0, maximumFractionDigits: fractionDigits ?? 1 }).format(size)} ${unit}`
}
