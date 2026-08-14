const normalizeText = value => String(value ?? '')

const copyWithSelection = (text, documentRef) => {
  if (!documentRef?.body || typeof documentRef.createElement !== 'function') return false
  if (typeof documentRef.execCommand !== 'function') return false

  const previousFocus = documentRef.activeElement
  const textarea = documentRef.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.inset = '0 auto auto 0'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  documentRef.body.appendChild(textarea)

  try {
    textarea.focus()
    textarea.select()
    textarea.setSelectionRange?.(0, text.length)
    return documentRef.execCommand('copy') === true
  } catch {
    return false
  } finally {
    textarea.remove()
    previousFocus?.focus?.()
  }
}

export class ClipboardCopyError extends Error {
  constructor() {
    super('Unable to copy text to the clipboard')
    this.name = 'ClipboardCopyError'
  }
}

export const copyText = async (value, environment = {}) => {
  const text = normalizeText(value)
  const navigatorRef = environment.navigator ?? globalThis.navigator
  const documentRef = environment.document ?? globalThis.document

  if (typeof navigatorRef?.clipboard?.writeText === 'function') {
    try {
      await navigatorRef.clipboard.writeText(text)
      return 'clipboard'
    } catch {
      // A denied or unavailable secure-context API should still use the
      // user-initiated selection fallback below.
    }
  }

  if (copyWithSelection(text, documentRef)) return 'selection'
  throw new ClipboardCopyError()
}

export const promptManualCopy = (value, instruction, windowRef = globalThis.window) => {
  if (typeof windowRef?.prompt !== 'function') return false
  windowRef.prompt(instruction, normalizeText(value))
  return true
}
