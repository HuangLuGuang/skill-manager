<template>
  <nav class="turn-navigation" :aria-label="t('aidr.sessions.turns')">
    <div class="mobile-turn"><label>{{ t('aidr.sessions.turns') }}<select :value="active" @change="$emit('select', $event.target.value)"><option value="">{{ t('aidr.sessions.allTurns') }}</option><option v-for="(turn, index) in items" :key="turn.key" :value="turn.key">{{ label(turn, index) }} · {{ date(turn.started_at) }} · {{ question(turn) }}</option></select></label></div>
    <div class="turn-rail">
      <span class="rail-label">{{ t('aidr.sessions.turns') }}</span>
      <button type="button" class="all-turns" :aria-pressed="!active" @click="$emit('select', '')">{{ t('aidr.sessions.allTurns') }}</button>
      <div class="rail-marks">
        <a-popover v-for="(turn, index) in items" :key="turn.key" placement="right" :trigger="['hover', 'focus']">
          <template #content><div class="turn-preview"><p>{{ label(turn, index) }} · {{ date(turn.started_at) }}</p><strong>{{ question(turn) }}</strong><p>{{ t('aidr.sessions.counts', { logs: turn.log_count, messages: turn.message_count || 0, hooks: turn.hook_count }) }}</p></div></template>
          <button type="button" :aria-label="`${label(turn, index)} · ${date(turn.started_at)} · ${question(turn)}`" :aria-current="active === turn.key ? 'step' : undefined" @click="$emit('select', turn.key)" @keydown="moveFocus($event, index)"><span class="tick" /></button>
        </a-popover>
      </div>
      <span v-if="activeIndex >= 0 && active !== 'unassigned'" class="rail-label">{{ numberedItems.findIndex(item => item.key === active) + 1 }}/{{ numberedItems.length }}{{ hasMore ? '+' : '' }}</span>
    </div>
    <a-button v-if="error || hasMore" size="small" :loading="loading" :disabled="loading" class="more-turns" @click="$emit('more')">{{ t(error ? 'aidr.sessions.retryTurns' : 'aidr.sessions.moreTurns') }}</a-button>
    <span v-else-if="loading" class="rail-label">{{ t('aidr.sessions.loading') }}</span>
  </nav>
</template>
<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
const props = defineProps({ items: { type: Array, required: true }, active: { type: String, default: '' }, loading: Boolean, hasMore: Boolean, error: Boolean, canRead: Boolean })
defineEmits(['select', 'more'])
const { t, locale } = useI18n()
const activeIndex = computed(() => props.items.findIndex(item => item.key === props.active))
const numberedItems = computed(() => props.items.filter(item => item.key !== 'unassigned'))
const label = (turn, index) => turn.key === 'unassigned' ? t('aidr.sessions.unassignedTurn') : t('aidr.sessions.round', { n: props.items.slice(0, index + 1).filter(item => item.key !== 'unassigned').length })
const question = turn => turn.key === 'unassigned' ? t('aidr.sessions.unassignedTurnHelp') : !props.canRead ? t('aidr.sessions.questionRestricted') : turn.question?.display_text || t('aidr.sessions.questionMissing')
const date = value => value ? new Date(value).toLocaleString(locale.value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'
function moveFocus(event, index) {
  if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const buttons = event.currentTarget.closest('.rail-marks').querySelectorAll('button')
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
  buttons[next]?.focus()
}
</script>
<style scoped>
.turn-navigation { min-width: 0; position: sticky; top: 16px; align-self: start; }
.turn-rail { display: flex; flex-direction: column; align-items: center; }
.rail-label { color: #667085; font-size: 11px; text-align: center; margin: 6px 0; overflow-wrap: anywhere; }
.all-turns { width: 48px; padding: 5px 3px; margin-bottom: 6px; border: 1px solid #e4e8ef; border-radius: 5px; background: white; color: #667085; font-size: 11px; line-height: 1.4; text-wrap: balance; cursor: pointer; }
.all-turns[aria-pressed=true] { color: #245fe5; border-color: #245fe5; background: #eef4ff; }
.rail-marks { max-height: max(120px, min(40vh, calc(100dvh - 500px))); overflow-y: auto; width: 48px; scrollbar-width: thin; }
.rail-marks button { width: 40px; min-height: 28px; display: flex; align-items: center; background: none; border: 0; padding: 8px 5px; cursor: pointer; }
.tick { display: block; width: 14px; height: 3px; background: #b7c0ce; }
button[aria-current=step] .tick { width: 28px; background: #245fe5; }
.rail-marks button:hover .tick, .rail-marks button:focus-visible .tick { width: 28px; background: #344054; }
button:focus-visible { outline: 2px solid #245fe5; outline-offset: -2px; }
.turn-preview { max-width: min(320px, 75vw); overflow-wrap: anywhere; }
.turn-preview strong { display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; font-weight: 500; white-space: pre-wrap; }
.turn-preview p { color: #667085; margin: 6px 0; font-size: 12px; }
.more-turns { height: auto; white-space: normal; padding: 3px; width: 48px; font-size: 11px; }
.mobile-turn { display: none; }
@media(max-width: 900px) { .turn-navigation { position: static; } .turn-rail { display: none; } .mobile-turn { display: block; } .mobile-turn label { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #667085; } select { display: block; flex: 1; min-width: 0; max-width: 100%; margin: 0; padding: 6px; border: 1px solid #d9d9d9; border-radius: 6px; background: white; color: #344054; } .more-turns { width: auto; padding: 5px 10px; } }
@media(pointer: coarse) { .rail-marks button { width: 44px; min-height: 44px; } select { font-size: 16px; } }
</style>
