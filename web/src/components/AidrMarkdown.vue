<template>
  <pre v-if="mode === 'source'" class="audit-source">{{ text }}</pre>
  <div v-else class="audit-markdown" v-html="html"></div>
</template>

<script setup>
import { computed } from 'vue'
import { renderSafeMarkdown } from '../utils/markdown'
const props = defineProps({ text: { type: String, default: '' }, mode: { type: String, default: 'rendered' } })
const html = computed(() => props.mode === 'rendered' ? renderSafeMarkdown(props.text, { literalHtml: true }) : '')
</script>

<style scoped>
.audit-source { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; padding: 8px 10px; border: 1px solid #dce3ec; border-radius: 5px; background: #f6f8fa; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; line-height: 1.65; }
.audit-markdown { overflow-wrap: anywhere; line-height: 1.65; }
.audit-markdown :deep(> :first-child) { margin-top: 0; }
.audit-markdown :deep(> :last-child) { margin-bottom: 0; }
.audit-markdown :deep(p) { margin: 0 0 10px; white-space: normal; }
.audit-markdown :deep(h1), .audit-markdown :deep(h2), .audit-markdown :deep(h3), .audit-markdown :deep(h4), .audit-markdown :deep(h5), .audit-markdown :deep(h6) { margin: 16px 0 8px; font-size: 1.1em; font-weight: 600; }
.audit-markdown :deep(ul), .audit-markdown :deep(ol) { padding-left: 24px; margin: 8px 0; }
.audit-markdown :deep(blockquote) { margin: 10px 0; padding-left: 12px; border-left: 3px solid #b9c7db; color: #667085; }
.audit-markdown :deep(pre) { white-space: pre; overflow-x: auto; max-width: 100%; padding: 10px 12px; border-radius: 5px; background: #f1f3f6; }
.audit-markdown :deep(code) { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .92em; background: #edf0f5; border-radius: 3px; padding: 1px 4px; }
.audit-markdown :deep(pre code) { padding: 0; background: none; }
.audit-markdown :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; margin: 10px 0; }
.audit-markdown :deep(th), .audit-markdown :deep(td) { border: 1px solid #d8e0eb; padding: 5px 9px; text-align: left; }
.audit-markdown :deep(a) { color: #245fe5; text-decoration: underline; }
</style>
