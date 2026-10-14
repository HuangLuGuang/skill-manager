export function createDocsPdfProgressReader(onProgress) {
  let consumed = 0
  let complete = false
  let error
  let fileProgress
  let receivedBytes = 0
  const chunks = []
  const feed = text => {
    if (error) return
    try {
      let end
      while ((end = text.indexOf('\n', consumed)) !== -1) {
        const line = text.slice(consumed, end)
        consumed = end + 1
        if (!line.trim()) continue
        const event = JSON.parse(line)
        if (event.type === 'progress') {
          if (event.stage === 'downloading') fileProgress = event
          onProgress?.(event)
        }
        if (event.type === 'chunk') {
          const bytes = Uint8Array.from(atob(event.data), character => character.charCodeAt(0))
          chunks.push(bytes)
          receivedBytes += bytes.length
          if (fileProgress) onProgress?.({ ...fileProgress, completed_bytes: receivedBytes })
        }
        if (event.type === 'complete') complete = true
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
      if (error) throw error
      if (!complete || !chunks.length) throw new Error('docs_export.incomplete')
      return new Blob(chunks, { type: 'application/pdf' })
    },
  }
}
