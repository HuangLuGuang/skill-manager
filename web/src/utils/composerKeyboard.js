export const shouldSubmitComposerOnEnter = (event, composing = false) => (
  event.key === 'Enter'
  && !event.shiftKey
  && !event.ctrlKey
  && !event.altKey
  && !event.metaKey
  && !composing
  && !event.isComposing
  && event.keyCode !== 229
)
