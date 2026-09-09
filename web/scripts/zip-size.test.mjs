import test from 'node:test'
import assert from 'node:assert/strict'
import { BlobReader, BlobWriter, TextReader, TextWriter, ZipReader, ZipWriter } from '@zip.js/zip.js'
import { analyzeZipSize, isZipTooLarge, ZIP_UPLOAD_LIMIT, removeMacOSMetadata } from '../src/utils/zipSize.js'

test('upload size accepts the limit and rejects one byte above', () => {
  assert.equal(isZipTooLarge({ size: ZIP_UPLOAD_LIMIT }), false)
  assert.equal(isZipTooLarge({ size: ZIP_UPLOAD_LIMIT + 1 }), true)
  assert.equal(isZipTooLarge({ size: 200 * 1024 * 1024 }), true)
})

for (const zip64 of [false, true]) {
  test(`directory totals include descendants and root files (ZIP64=${zip64})`, async () => {
    const writer = new ZipWriter(new BlobWriter(), { level: 0, zip64, useWebWorkers: false })
    await writer.add('skill/assets/icons/deep/大图.svg', new TextReader('1234567890'))
    await writer.add('skill/SKILL.md', new TextReader('12345'))
    await writer.add('README.md', new TextReader('12'))
    const result = await analyzeZipSize(await writer.close())
    assert.equal(result.fileCount, 3)
    assert.deepEqual(result.folders, [
      { path: 'skill/', compressed: 15, original: 15, count: 2 },
      { path: 'skill/assets/', compressed: 10, original: 10, count: 1 },
      { path: '.', compressed: 2, original: 2, count: 1 },
    ])
  })
}

test('ranking is limited to ten folders and uses compressed size', async () => {
  const writer = new ZipWriter(new BlobWriter(), { level: 0, useWebWorkers: false })
  for (let i = 1; i <= 12; i++) await writer.add(`folder${i}/data`, new TextReader('x'.repeat(i)))
  const result = await analyzeZipSize(await writer.close())
  assert.equal(result.folders.length, 10)
  assert.equal(result.folders[0].path, 'folder12/')
  assert.equal(result.folders.at(-1).path, 'folder3/')
})

test('invalid archive fails without returning misleading totals', async () => {
  await assert.rejects(analyzeZipSize(new Blob(['not a ZIP'])))
})

test('macOS cleanup preserves file contents, compression and symlink attributes', async () => {
  const writer = new ZipWriter(new BlobWriter(), { useWebWorkers: false })
  await writer.add('__MACOSX/._SKILL.md', new TextReader('metadata'))
  await writer.add('skill/SKILL.md', new TextReader('name: example\n'.repeat(100)))
  await writer.add('skill/link', new TextReader('SKILL.md'), {
    versionMadeBy: 0x031e, externalFileAttributes: (0o120777 << 16) >>> 0,
  })
  const original = new File([await writer.close()], 'skill.zip')
  const progress = []
  const cleaned = await removeMacOSMetadata(original, value => progress.push(value))
  assert.deepEqual(progress.at(-1), { stage: 'cleaning', completed: 3, total: 3 })
  assert.ok(progress.some(value => value.stage === 'reading' && value.completed === 3))
  assert.equal(cleaned.name, original.name)
  const reader = new ZipReader(new BlobReader(cleaned))
  const entries = await reader.getEntries()
  assert.deepEqual(entries.map(entry => entry.filename), ['skill/SKILL.md', 'skill/link'])
  assert.equal(await entries[0].getData(new TextWriter()), 'name: example\n'.repeat(100))
  assert.equal(entries[0].compressionMethod, 8)
  assert.equal(entries[1].externalFileAttributes >>> 16, 0o120777)
  assert.equal(await entries[1].getData(new TextWriter()), 'SKILL.md')
  await reader.close()
})

test('ZIP without root macOS metadata is returned unchanged', async () => {
  const writer = new ZipWriter(new BlobWriter(), { level: 0, useWebWorkers: false })
  await writer.add('skill/__MACOSX/data', new TextReader('user content'))
  const file = new File([await writer.close()], 'skill.zip')
  assert.equal(await removeMacOSMetadata(file), file)
})

for (const zip64 of [false, true]) {
  test(`range cleanup handles interleaved metadata and encrypted content (ZIP64=${zip64})`, async () => {
    const writer = new ZipWriter(new BlobWriter(), { zip64, useWebWorkers: false })
    await writer.add('a.txt', new TextReader('first'))
    await writer.add('__MACOSX/one', new TextReader('remove'.repeat(100)))
    await writer.add('secret.txt', new TextReader('secret'), { password: 'test-password', zipCrypto: true })
    await writer.add('__MACOSX/two', new TextReader('remove'))
    await writer.add('last.txt', new TextReader('last'))
    const original = new File([await writer.close(new TextEncoder().encode('comment'))], 'mixed.zip')
    const cleaned = await removeMacOSMetadata(original)
    assert.ok(cleaned.size < original.size)
    const reader = new ZipReader(new BlobReader(cleaned))
    const entries = await reader.getEntries()
    assert.deepEqual(entries.map(e => e.filename), ['a.txt', 'secret.txt', 'last.txt'])
    assert.equal(await entries[0].getData(new TextWriter()), 'first')
    assert.equal(await entries[1].getData(new TextWriter(), { password: 'test-password' }), 'secret')
    assert.equal(await entries[2].getData(new TextWriter()), 'last')
    assert.equal(new TextDecoder().decode(reader.comment), 'comment')
    await reader.close()
  })
}

test('removing metadata-only archive produces an empty valid ZIP', async () => {
  const writer = new ZipWriter(new BlobWriter(), { useWebWorkers: false })
  await writer.add('__MACOSX/a', new TextReader('remove'))
  const cleaned = await removeMacOSMetadata(new File([await writer.close()], 'empty.zip'))
  const reader = new ZipReader(new BlobReader(cleaned))
  assert.deepEqual(await reader.getEntries(), [])
  await reader.close()
})

test('many retained files are copied as a contiguous range without per-file reads', async () => {
  const writer = new ZipWriter(new BlobWriter(), { level: 0, useWebWorkers: false })
  await writer.add('__MACOSX/junk', new TextReader('metadata'))
  for (let i = 0; i < 100; i++) await writer.add(`skill/${i}.svg`, new TextReader('<svg/>'))
  let slices = 0
  class ObservedFile extends File {
    slice(...args) {
      slices++
      return super.slice(...args)
    }
  }
  const cleaned = await removeMacOSMetadata(new ObservedFile([await writer.close()], 'many.zip'))
  assert.ok(slices < 20, `Expected bounded archive reads, got ${slices}`)
  const reader = new ZipReader(new BlobReader(cleaned))
  assert.equal((await reader.getEntries()).length, 100)
  await reader.close()
})
