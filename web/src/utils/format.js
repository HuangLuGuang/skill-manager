import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)

export const formatDateTime = (value) => {
  if (!value) return '-'
  const date = dayjs(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm:ss') : String(value)
}

export const formatBeijingDateTime = (value) => {
  if (!value) return '-'
  const date = dayjs.utc(value).tz('Asia/Shanghai')
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm:ss') : String(value)
}

export const formatDetails = (details, limit = 4) => {
  if (!details || typeof details !== 'object') return '-'
  return Object.entries(details)
    .slice(0, limit)
    .map(([key, value]) => `${key}: ${value}`)
    .join(' | ')
}
