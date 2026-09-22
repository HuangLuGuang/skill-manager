import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
const context = vm.createContext({})
for (const name of ['isCustomAgent', 'isSharedSkills', 'visibleAgent']) {
  vm.runInContext(source.split('\n').find(line => line.startsWith(`const ${name} =`)), context)
}
const certification = source.slice(source.indexOf('const skillCertification ='), source.indexOf('const filteredAgentSkills ='))
vm.runInContext(certification, context)
const evaluate = (expression, value) => {
  context.value = value
  return vm.runInContext(expression, context)
}

test('directory-based Agents remain reachable without an executable path', () => {
  assert.equal(evaluate('visibleAgent(value)', { agent_type: 'claude-code', skills_path: '/home/user/.claude/skills', skills: [{ name: 'retained' }] }), true)
})
test('installed empty Agents, custom Agents and shared Skills remain reachable', () => {
  for (const agent of [
    { agent_type: 'claude-code', install_path: '/home/user/.local/bin/claude', skills: [] },
    { agent_type: 'custom-local', capabilities: { custom: true }, skills: [] },
    { agent_type: 'global-skills', skills: [] },
  ]) assert.equal(evaluate('visibleAgent(value)', agent), true)
})
test('certification filters apply only to the exact observed content', () => {
  assert.equal(evaluate('skillCertification(value)', { signature: 'new', governance: { signature: 'old', certification: 'certified' } }), 'confirmation_pending')
  assert.equal(evaluate('skillCertification(value)', { signature: 'same', governance: { signature: 'same', certification: 'certified' } }), 'trusted')
  assert.equal(evaluate('skillCertification(value)', { signature: 'same', governance: { signature: 'same', certification: 'unverified', malicious: true } }), 'malicious')
})

const carouselHarness = () => {
  const handlers = new Map()
  const windowHandlers = new Map()
  const strip = {
    scrollWidth: 1200, clientWidth: 500, scrollLeft: 0,
    classList: { add() {}, remove() {} },
    addEventListener(name, handler) { handlers.set(name, handler) },
    setPointerCapture() {}, hasPointerCapture() { return false },
    scrollBy({ left }) { this.scrollLeft += left },
  }
  const buttons = new Map(['left', 'right'].map(direction => [`#agent-scroll-${direction}`, { addEventListener() {} }]))
  const switches = []
  const sandbox = vm.createContext({
    $: id => id === '#agent-tabs' ? strip : buttons.get(id),
    window: { addEventListener: (name, handler) => windowHandlers.set(name, handler) },
    ResizeObserver: class { observe() {} },
    performance: { now: () => 100 },
    syncAgentScroll() {}, agentScrollBehavior: () => 'auto',
    switchAgent: id => switches.push(id),
  })
  vm.runInContext(source.slice(source.indexOf('let agentDrag ='), source.indexOf("$('#agent-tabs').addEventListener('keydown'")), sandbox)
  return { handlers, windowHandlers, strip, switches }
}

test('mouse wheel scrolls Agent strip and releases page scrolling at its boundary', () => {
  const { handlers, strip } = carouselHarness()
  let prevented = false
  const event = { currentTarget: strip, deltaX: 0, deltaY: 120, deltaMode: 0, preventDefault() { prevented = true } }
  handlers.get('wheel')(event)
  assert.equal(strip.scrollLeft, 120)
  assert.equal(prevented, true)
  strip.scrollLeft = 700
  prevented = false
  handlers.get('wheel')(event)
  assert.equal(prevented, false)
  // Trackpad horizontal deltas retain the browser's native scrolling.
  handlers.get('wheel')({ ...event, deltaX: 160, deltaY: 0 })
  assert.equal(prevented, false)
})

test('dragging scrolls without accidentally switching the Agent; ordinary clicks still switch', () => {
  const { handlers, windowHandlers, strip, switches } = carouselHarness()
  const event = { currentTarget: strip, pointerType: 'mouse', button: 0, pointerId: 1, clientX: 300, preventDefault() {} }
  handlers.get('pointerdown')(event)
  handlers.get('pointermove')({ ...event, clientX: 180 })
  windowHandlers.get('pointerup')(event)
  handlers.get('click')({ preventDefault() {}, target: { closest: () => ({ dataset: { agentTab: 'codex' } }) } })
  assert.equal(strip.scrollLeft, 120)
  assert.deepEqual(switches, [])
  const fresh = carouselHarness()
  fresh.handlers.get('click')({ target: { closest: () => ({ dataset: { agentTab: 'codex' } }) } })
  assert.deepEqual(fresh.switches, ['codex'])
})

test('every built-in Agent logo is packaged locally, including shared and custom Agents', () => {
  const sandbox = vm.createContext({})
  vm.runInContext(source.slice(source.indexOf('const agentLogoFile ='), source.indexOf('const agentLogo =')), sandbox)
  for (const type of ['claude-code', 'codex', 'gemini', 'opencode', 'hermes', 'openclaw', 'trae-cn', 'trae', 'cursor', 'codebuddy', 'workbuddy', 'teleagent', 'global-skills', 'custom-local']) {
    sandbox.agent = { agent_type: type }
    const file = vm.runInContext('agentLogoFile(agent)', sandbox)
    assert.ok(fs.existsSync(new URL(`../src/assets/icons/${file}.${['workbuddy', 'teleagent'].includes(file) ? 'png' : 'svg'}`, import.meta.url)), `Missing logo for ${type}`)
  }
})

test('history follows the selected Agent and is empty without a selection', () => {
  let selected = { agent_type: 'claude-code' }
  const sandbox = vm.createContext({ selectedAgent: () => selected })
  vm.runInContext(source.split('\n').find(line => line.startsWith('const scopeIncludes =')), sandbox)
  const includes = agentType => {
    sandbox.item = { agent_type: agentType }
    return vm.runInContext('scopeIncludes(item)', sandbox)
  }
  assert.equal(includes('claude-code'), true)
  assert.equal(includes('codex'), false)
  selected = { agent_type: 'codex' }
  assert.equal(includes('claude-code'), false)
  assert.equal(includes('codex'), true)
  selected = undefined
  assert.equal(includes(undefined), false)
})
