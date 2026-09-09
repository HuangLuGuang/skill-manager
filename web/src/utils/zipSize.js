import { BlobReader, ZipReader } from '@zip.js/zip.js'

export const ZIP_UPLOAD_LIMIT = 100 * 1024 * 1024
export const isZipTooLarge = file => file.size > ZIP_UPLOAD_LIMIT
export const formatZipSize = bytes => `${(bytes / 1024 / 1024).toFixed(2)} MiB`

// Local records (including compressed bytes and data descriptors) remain verbatim.
// Only central-directory offsets and end records change when ranges are removed.
async function copyZipRanges(file, reader, entries, onProgress) {
  onProgress?.({ stage: 'cleaning', completed: 0, total: entries.length })
  const ordered = [...entries].sort((a, b) => a.offset - b.offset)
  const parts = []
  const offsets = new Map()
  let outputSize = ordered[0]?.offset || 0
  let rangeStart = 0
  let rangeEnd = outputSize
  for (let i = 0; i < ordered.length; i++) {
    const entry = ordered[i]
    const end = ordered[i + 1]?.offset ?? reader.directoryOffset
    if (end <= entry.offset || end > reader.directoryOffset) throw new Error('Invalid ZIP record range')
    if (entry.filename.startsWith('__MACOSX/')) {
      if (rangeEnd > rangeStart) parts.push(file.slice(rangeStart, rangeEnd))
      rangeStart = end
      rangeEnd = end
    } else {
      offsets.set(entry, outputSize)
      outputSize += end - entry.offset
      rangeEnd = end
    }
  }
  if (rangeEnd > rangeStart) parts.push(file.slice(rangeStart, rangeEnd))

  const source = new Uint8Array(await file.slice(reader.directoryOffset, reader.directoryOffset + reader.directoryLength).arrayBuffer())
  const directory = new Uint8Array(source.length)
  let sourceOffset = 0
  let directorySize = 0
  let count = 0
  for (let i = 0; i < entries.length; i++) {
    const header = new DataView(source.buffer, sourceOffset)
    if (header.getUint32(0, true) !== 0x02014b50) throw new Error('Invalid ZIP directory')
    const nameLength = header.getUint16(28, true)
    const extraLength = header.getUint16(30, true)
    const length = 46 + nameLength + extraLength + header.getUint16(32, true)
    if (sourceOffset + length > source.length) throw new Error('Truncated ZIP directory')
    const offset = offsets.get(entries[i])
    if (offset !== undefined) {
      if (header.getUint32(42, true) === 0xffffffff) {
        let pos = 46 + nameLength
        let patched = false
        while (pos + 4 <= 46 + nameLength + extraLength) {
          const id = header.getUint16(pos, true)
          const size = header.getUint16(pos + 2, true)
          if (id === 1) {
            const field = pos + 4 + (header.getUint32(24, true) === 0xffffffff ? 8 : 0)
              + (header.getUint32(20, true) === 0xffffffff ? 8 : 0)
            if (field + 8 > pos + 4 + size) throw new Error('Invalid ZIP64 offset')
            header.setBigUint64(field, BigInt(offset), true)
            patched = true
            break
          }
          pos += 4 + size
        }
        if (!patched) throw new Error('Missing ZIP64 offset')
      } else {
        header.setUint32(42, offset, true)
      }
      directory.set(source.subarray(sourceOffset, sourceOffset + length), directorySize)
      directorySize += length
      count++
    }
    sourceOffset += length
    if (i % 2048 === 2047 || i === entries.length - 1) {
      onProgress?.({ stage: 'cleaning', completed: i + 1, total: entries.length })
      await new Promise(resolve => setTimeout(resolve, 0))
    }
  }
  parts.push(directory.subarray(0, directorySize))
  const zip64 = count >= 0xffff || outputSize >= 0xffffffff || directorySize >= 0xffffffff
  if (zip64) {
    const end64 = new Uint8Array(76)
    const view = new DataView(end64.buffer)
    view.setUint32(0, 0x06064b50, true)
    view.setBigUint64(4, 44n, true)
    view.setUint16(12, 45, true)
    view.setUint16(14, 45, true)
    view.setBigUint64(24, BigInt(count), true)
    view.setBigUint64(32, BigInt(count), true)
    view.setBigUint64(40, BigInt(directorySize), true)
    view.setBigUint64(48, BigInt(outputSize), true)
    view.setUint32(56, 0x07064b50, true)
    view.setBigUint64(64, BigInt(outputSize + directorySize), true)
    view.setUint32(72, 1, true)
    parts.push(end64)
  }
  const end = new Uint8Array(22 + reader.comment.length)
  const view = new DataView(end.buffer)
  view.setUint32(0, 0x06054b50, true)
  view.setUint16(8, zip64 ? 0xffff : count, true)
  view.setUint16(10, zip64 ? 0xffff : count, true)
  view.setUint32(12, zip64 ? 0xffffffff : directorySize, true)
  view.setUint32(16, zip64 ? 0xffffffff : outputSize, true)
  view.setUint16(20, reader.comment.length, true)
  end.set(reader.comment, 22)
  parts.push(end)
  return new File(parts, file.name, { type: 'application/zip', lastModified: file.lastModified })
}

export async function removeMacOSMetadata(file, onProgress) {
  onProgress?.({ stage: 'reading', completed: 0, total: 0 })
  const reader = new ZipReader(new BlobReader(file))
  try {
    const entries = await reader.getEntries({ onprogress: entryProgress('reading', onProgress) })
    if (!entries.some(entry => entry.filename.startsWith('__MACOSX/'))) return file
    return await copyZipRanges(file, reader, entries, onProgress)
  } finally {
    await reader.close()
  }
}

// Read only archive directory metadata; file contents are never decompressed.
export async function analyzeZipSize(file, onProgress) {
  onProgress?.({ stage: 'analyzing', completed: 0, total: 0 })
  const reader = new ZipReader(new BlobReader(file))
  const folders = new Map()
  let fileCount = 0
  try {
    for await (const entry of reader.getEntriesGenerator({ onprogress: entryProgress('analyzing', onProgress) })) {
      if (entry.directory) continue
      fileCount++
      const parts = entry.filename.split('/')
      parts.pop()
      parts.length = Math.min(parts.length, 2)
      const paths = parts.length ? parts.map((_, i) => parts.slice(0, i + 1).join('/') + '/') : ['.']
      for (const path of paths) {
        const row = folders.get(path) || { path, compressed: 0, original: 0, count: 0 }
        row.compressed += entry.compressedSize
        row.original += entry.uncompressedSize
        row.count++
        folders.set(path, row)
      }
    }
    return {
      fileCount,
      folders: [...folders.values()].sort((a, b) => b.compressed - a.compressed || a.path.localeCompare(b.path)).slice(0, 10),
    }
  } finally {
    await reader.close()
  }
}

function entryProgress(stage, onProgress) {
  return (completed, total) => {
    if (completed % 2048 === 0 || completed === total) {
      onProgress?.({ stage, completed, total })
      return new Promise(resolve => setTimeout(resolve, 0))
    }
  }
}
