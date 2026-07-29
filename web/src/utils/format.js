import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import { getCurrentLocale } from '../i18n'

dayjs.extend(utc)
dayjs.extend(timezone)

export const formatDateTime = (value) => {
  if (!value) return '-'
  const date = dayjs(value)
  if (!date.isValid()) return String(value)
  return new Intl.DateTimeFormat(getCurrentLocale(), {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date.toDate())
}

export const formatBeijingDateTime = (value) => {
  if (!value) return '-'
  const date = dayjs.utc(value).tz('Asia/Shanghai')
  if (!date.isValid()) return String(value)
  return new Intl.DateTimeFormat(getCurrentLocale(), {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date.toDate())
}

export const formatNumber = value =>
  value === null || value === undefined || value === ''
    ? '-'
    : new Intl.NumberFormat(getCurrentLocale()).format(Number(value))

export const formatCompactNumber = value =>
  value === null || value === undefined || value === ''
    ? '-'
    : new Intl.NumberFormat(getCurrentLocale(), {
        notation: 'compact',
        maximumFractionDigits: 1,
      }).format(Number(value))

export const formatFileSize = value => {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  if (bytes < 1024) return `${formatNumber(bytes)} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = bytes / 1024
  let unit = units[0]
  for (let index = 1; size >= 1024 && index < units.length; index += 1) {
    size /= 1024
    unit = units[index]
  }
  return `${new Intl.NumberFormat(getCurrentLocale(), { maximumFractionDigits: 1 }).format(size)} ${unit}`
}

export const formatDetails = (details, limit = 4) => {
  if (!details || typeof details !== 'object') return '-'
  return Object.entries(details)
    .slice(0, limit)
    .map(([key, value]) => `${key}: ${value}`)
    .join(' | ')
}
