<template>
  <section v-if="analysis" class="parsed-commands">
    <h4>{{ t('aidr.commandParsing.title', { count: analysis.commands.length }) }}</h4>
    <p class="note">{{ t('aidr.commandParsing.boundary') }}</p>
    <p v-if="analysis.status !== 'complete'" class="note">{{ t('aidr.commandParsing.status.' + analysis.status) }}</p>
    <ol v-if="analysis.commands.length">
      <li v-for="(command, index) in analysis.commands" :key="index">
        <div><strong>{{ command.program || t('aidr.commandParsing.dynamic') }}</strong><span>{{ t('aidr.commandParsing.line', { line: command.line }) }}</span></div>
        <pre>{{ command.text }}</pre>
        <small v-if="command.text_truncated">{{ t('aidr.commandParsing.shortened') }}</small>
      </li>
    </ol>
  </section>
</template>
<script setup>
import { useI18n } from 'vue-i18n'
defineProps({ analysis: { type: Object, default: null } })
const { t } = useI18n()
</script>
<style scoped>
.parsed-commands{margin:16px 0;border-left:3px solid #dbe5f6;padding-left:14px;min-width:0}h4{margin:0 0 8px}.note,span,small{color:#667085;font-size:12px}ol{padding-left:24px}li{padding:5px 0}li>div{display:flex;gap:12px;flex-wrap:wrap}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;border-radius:6px;padding:10px 12px;margin:6px 0;max-height:24vh;overflow:auto}
</style>
