import dayjs from 'dayjs'

export const formatDateTime = (value) => {
  if (!value) return '-'
  const date = dayjs(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm:ss') : String(value)
}

export const formatDetails = (details, limit = 4) => {
  if (!details || typeof details !== 'object') return '-'
  return Object.entries(details)
    .slice(0, limit)
    .map(([key, value]) => `${key}: ${value}`)
    .join(' | ')
}
