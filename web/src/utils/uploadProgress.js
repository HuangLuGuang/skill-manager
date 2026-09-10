export function createUploadProgressReader(onProgress) {
  let consumed = 0
  let result
  let error
  const feed = text => {
    if (error) return
    try {
      let end
      while ((end = text.indexOf('\n', consumed)) !== -1) {
        const line = text.slice(consumed, end)
        consumed = end + 1
        if (!line.trim()) continue
        const event = JSON.parse(line)
        if (event.type === 'progress') onProgress?.(event)
        if (event.type === 'result') result = event.data
        if (event.type === 'error') throw new Error(event.error_code)
      }
    } catch (cause) {
      error = cause
    }
  }
  return {
    feed,
    finish(text) {
      feed(text)
      if (error || result === undefined) {
        const failure = new Error('ZIP preparation failed')
        failure.apiErrorCode = 'upload.parse_failed'
        throw failure
      }
      return result
    },
  }
}
