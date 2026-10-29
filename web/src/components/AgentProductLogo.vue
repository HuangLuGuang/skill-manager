<template>
  <img v-if="src" class="agent-product-logo" :src="src" alt="" aria-hidden="true" draggable="false" />
  <span v-else class="agent-product-initial" aria-hidden="true">{{ productId.slice(0, 1).toUpperCase() }}</span>
</template>

<script setup>
import { computed } from 'vue'
import claude from '../assets/agent-logos/claude-color.svg'
import codex from '../assets/agent-logos/codex.png'
import workbuddy from '../assets/agent-logos/workbuddy.png'
import qoder from '../assets/agent-logos/qoder.png'
import cursor from '../assets/agent-logos/cursor.svg'
import opencode from '../assets/agent-logos/opencode.svg'
import openclaw from '../assets/agent-logos/openclaw-color.svg'
import trae from '../assets/agent-logos/trae.svg'
import codebuddy from '../assets/agent-logos/codebuddy-color.svg'
import teleagent from '../assets/agent-logos/teleagent.png'
import doubaowork from '../assets/agent-logos/doubaowork.png'
import qwenwork from '../assets/agent-logos/qwenwork.png'
import zcode from '../assets/agent-logos/zcode.png'
import gemini from '../assets/agent-logos/gemini-color.svg'
import hermes from '../assets/agent-logos/hermesagent.svg'
const props = defineProps({ productId: { type: String, required: true } })
const logos = { claude, 'claude-code': claude, codex, workbuddy, codebuddy, teleagent, doubaowork, qwenwork, zcode, gemini, hermes, qoder, 'qoder-cli': qoder, 'qoder-hooks': qoder, 'qoder-ide': qoder, 'qoder-work': qoder, cursor, opencode, openclaw, trae, 'trae-cn': trae, traework: trae }
const src = computed(() => logos[props.productId])
</script>

<style scoped>
.agent-product-logo { width: 100%; height: 100%; object-fit: contain; display: block; }
.agent-product-initial { font-size: 15px; font-weight: 600; color: #526579; }
</style>
