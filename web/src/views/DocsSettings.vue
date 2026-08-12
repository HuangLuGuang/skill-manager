<template>
  <div class="docs-settings-page">
    <DocsAssistantSettings />
  </div>
</template>

<script setup>
import DocsAssistantSettings from '../components/DocsAssistantSettings.vue'
</script>

<style scoped>
.docs-settings-page {
  width: min(1280px, 100%);
  margin: 0 auto;
}

.docs-settings-page :deep(.assistant-settings) {
  min-height: calc(100vh - 120px);
  margin-top: 0;
}
</style>
