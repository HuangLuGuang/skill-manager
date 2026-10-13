<template>
  <div class="integration-map" role="group" :aria-label="title">
    <div class="map-start"><span class="map-start-dot" aria-hidden="true"></span><strong>{{ decision.start }}</strong></div>
    <div class="map-columns" aria-hidden="true"><span v-for="column in decision.columns" :key="column">{{ column }}</span></div>
    <div class="map-branches">
      <div v-for="route in decision.routes" :key="route.id" class="map-route">
        <div class="map-scenario"><strong>{{ route.scenario }}</strong><small>{{ route.examples }}</small></div>
        <div class="map-condition"><span aria-hidden="true">→</span><p>{{ route.condition }}</p><span aria-hidden="true">→</span></div>
        <div class="map-solutions">
          <RouterLink v-for="link in route.links" :key="link.path" :to="link.path" class="map-node">
            <strong>{{ link.label }} <span aria-hidden="true">↗</span></strong><small>{{ link.detail }}</small>
          </RouterLink>
        </div>
      </div>
    </div>
    <p class="map-coverage">{{ decision.unavailable }}</p>
    <div class="map-additions">
      <strong>{{ decision.additionalTitle }}</strong>
      <div class="map-addition-grid">
        <RouterLink v-for="link in decision.additional" :key="link.path" :to="link.path" class="map-node">
          <strong>{{ link.label }} <span aria-hidden="true">↗</span></strong><small>{{ link.detail }}</small>
        </RouterLink>
      </div>
    </div>
  </div>
</template>

<script setup>
import { RouterLink } from 'vue-router'

defineProps({ decision: { type: Object, required: true }, title: { type: String, required: true } })
</script>

<style scoped>
.integration-map { container-type: inline-size; margin: 24px 0; padding: 22px; color: #29445b; background: #f7f9fc; border: 1px solid #d5e0ea; border-radius: 14px; overflow-wrap: anywhere; }
.map-start { display: flex; align-items: center; gap: 10px; width: fit-content; max-width: 100%; padding: 13px 18px; color: #234f79; background: #e9f2fc; border: 1px solid #bad0e5; border-radius: 9px; font-size: 15px; }
.map-start-dot { flex: 0 0 9px; height: 9px; border: 3px solid #a6c5e4; border-radius: 50%; background: #2f6fad; }
.map-columns, .map-route { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr) minmax(0, 1.65fr); gap: 12px; }
.map-columns { padding: 20px 0 10px 22px; color: #687e91; font-size: 11px; }
.map-branches { position: relative; display: grid; gap: 14px; padding-left: 22px; }
.map-branches::before { position: absolute; left: 0; top: -36px; bottom: 0; width: 2px; background: #c7d8e7; content: ''; }
.map-route { position: relative; align-items: center; }
.map-route::before { position: absolute; top: 50%; left: -22px; width: 22px; height: 2px; background: #c7d8e7; content: ''; }
.map-scenario { min-width: 0; padding: 12px; background: #fff; border: 1px solid #d5e0ea; border-radius: 8px; }
.map-scenario strong, .map-node strong { display: block; font-size: 13px; line-height: 1.6; }
.map-scenario small, .map-node small { display: block; margin-top: 6px; color: #596f83; font-size: 12px; line-height: 1.65; }
.map-condition { display: flex; align-items: center; gap: 8px; color: #6f88a0; }
.map-condition p { flex: 1; margin: 0; color: #536d82; font-size: 12px; line-height: 1.7; text-align: center; }
.map-solutions { display: grid; gap: 8px; }
.map-node { display: block; min-width: 0; padding: 12px 14px; color: #235b8b; background: #eef5fc; border: 1px solid #bad0e5; border-left: 3px solid #4d85b6; border-radius: 8px; text-decoration: none; transition: background .15s, border-color .15s; }
.map-node strong span { float: right; margin-left: 6px; }
.map-node:hover { color: #184b79; border-color: #6597c3; background: #e2eefb; }
.map-node:focus-visible { outline: 3px solid #87b2dc; outline-offset: 3px; }
.map-coverage { margin: 18px 0; color: #596f83; font-size: 12px; line-height: 1.7; }
.map-additions { padding-top: 18px; border-top: 1px dashed #bdccda; }
.map-additions > strong { display: block; margin-bottom: 12px; font-size: 14px; line-height: 1.6; }
.map-addition-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.map-addition-grid .map-node { background: #f0f6f3; border-color: #bfd6cc; border-left-color: #659884; color: #376b56; }
.map-addition-grid .map-node:hover { background: #e3f0e9; border-color: #659884; }
@container (max-width: 620px) {
  .map-columns { display: none; }
  .map-branches { margin-top: 22px; gap: 22px; padding-left: 16px; }
  .map-branches::before { top: -22px; }
  .map-route { grid-template-columns: 1fr; gap: 8px; }
  .map-route::before { top: 26px; left: -16px; width: 16px; }
  .map-condition { flex-direction: column; gap: 4px; }
  .map-condition span { transform: rotate(90deg); }
  .map-addition-grid { grid-template-columns: 1fr; }
}
</style>
