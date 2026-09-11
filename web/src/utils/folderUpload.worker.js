import { BlobReader, BlobWriter, ZipWriter } from '@zip.js/zip.js'
self.onmessage = async ({ data: entries }) => {
  try {
    const writer = new ZipWriter(new BlobWriter('application/zip'), { useWebWorkers: false })
    const total = entries.reduce((sum, entry) => sum + entry.file.size, 0)
    let done = 0, last = 0
    const progress = (loaded, completed) => {
      const now = Date.now()
      if (now - last < 100 && completed !== entries.length) return
      last = now
      self.postMessage({ type: 'progress', percent: total ? Math.min(99, Math.floor((done + loaded) / total * 100)) : 0, completed, total: entries.length })
    }
    for (let i = 0; i < entries.length; i++) {
      const { path, file } = entries[i]
      await writer.add(path, new BlobReader(file), { level: 1, onprogress: loaded => progress(loaded, i) })
      done += file.size
      progress(0, i + 1)
    }
    self.postMessage({ type: 'result', blob: await writer.close() })
  } catch {
    self.postMessage({ type: 'error' })
  }
}
