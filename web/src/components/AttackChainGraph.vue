<template>
  <div class="attack-chain-container">
    <div ref="graphContainer" class="graph-container"></div>
    <div class="steps-detail-container">
      <h4 style="margin-bottom: 12px;">攻击链步骤详情</h4>
      <a-list :data-source="attackChain" bordered size="small">
        <template #renderItem="{ item }">
          <a-list-item>
            <div class="step-detail-item">
              <div class="step-title">
                <a-tag color="blue">步骤 {{ item.step }}</a-tag>
                <span class="tactic-name">{{ item.tactic }}</span>
              </div>
              <div class="techniques-container">
                <span class="label">技术:</span>
                <a-space wrap>
                  <a-tag v-for="tech in item.techniques" :key="tech.id" color="orange">
                    {{ tech.name ? `${tech.name} (${tech.id})` : tech.id }}
                  </a-tag>
                </a-space>
              </div>
              <div class="description-container">
                <span class="label">行为描述:</span>
                <div class="description-text">{{ item.description }}</div>
              </div>
            </div>
          </a-list-item>
        </template>
      </a-list>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, onBeforeUnmount } from 'vue'
import { Graph } from '@antv/x6'

const props = defineProps({
  attackChain: {
    type: Array,
    default: () => []
  }
})

const graphContainer = ref(null)
let graph = null

const initGraph = () => {
  graph = new Graph({
    container: graphContainer.value,
    grid: true,
    panning: true,
    mousewheel: false,
    autoResize: false,
    background: { color: '#F2F7FA' },
  })
}

const getFullText = (step) => {
  const lines = []
  lines.push(step.tactic)
  step.techniques.forEach(t => {
    lines.push(t.name ? `${t.name} (${t.id})` : t.id)
  })
  return lines.join('\n')
}

const renderAttackChain = () => {
  if (!graph || !props.attackChain?.length) return
  graph.clearCells()
  const nodes = []

  props.attackChain.forEach((step, index) => {
    const x = 50 + index * 350
    const y = 50

    const node = graph.addNode({
      x,
      y,
      width: 320,
      height: 200,
      data: step,
      attrs: {
        body: {
          stroke: '#1890FF',
          strokeWidth: 2,
          fill: '#fff',
          rx: 8,
          ry: 8,
        },
        label: {
          text: getFullText(step),
          fontSize: 18,
          fill: '#333',
          textAnchor: 'middle',
          textVerticalAnchor: 'middle', // Vertically center the whole text block
          y: 0, // Center of the 200px tall node
          lineHeight: 25, // Keep existing line spacing
        },
      },
      ports: {
        groups: {
          in: { position: 'left', attrs: { circle: { r: 6, magnet: true, stroke: '#5F95FF', fill: '#fff' }}},
          out: { position: 'right', attrs: { circle: { r: 6, magnet: true, stroke: '#5F95FF', fill: '#fff' }}},
        },
        items: [{ id: 'in', group: 'in' }, { id: 'out', group: 'out' }],
      },
    })

    nodes.push(node)

    if (index > 0) {
      graph.addEdge({
        source: { cell: nodes[index - 1], port: 'out' },
        target: { cell: node, port: 'in' },
        attrs: { line: { stroke: '#A2B1C3', strokeWidth: 2, targetMarker: { name: 'block', width: 12, height: 8 }}},
      })
    }
  })
}

onMounted(() => {
  initGraph()
  renderAttackChain()
})

watch(() => props.attackChain, () => renderAttackChain(), { deep: true })
onBeforeUnmount(() => graph?.dispose())
</script>

<style scoped>
.attack-chain-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.graph-container {
  height: 350px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  overflow: auto;
}

.steps-detail-container {
  flex: 1;
}

.step-detail-item {
  width: 100%;
}

.step-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.tactic-name {
  font-weight: 600;
  font-size: 15px;
}

.techniques-container,
.description-container {
  margin-bottom: 8px;
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.label {
  font-weight: 500;
  color: #666;
  flex-shrink: 0;
}

.description-text {
  color: #333;
  line-height: 1.6;
}
</style>
