import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const desktop = readFileSync(new URL('../src/app.js', import.meta.url), 'utf8')
test('real Agents remain counted when their Skills have shared readers', () => {
  const source = desktop.match(/^const isSharedSkills = .*$/m)[0]
  const agents = [
    { agent_type: 'global-skills', capabilities: { shared_skills: true } },
    { agent_type: 'codex', capabilities: { shared_skills: true } },
    { agent_type: 'claude-code', capabilities: { shared_skills: true } },
    { agent_type: 'custom-team', capabilities: { shared_skills: true } },
  ]
  const count = vm.runInNewContext(`${source}\nagents.filter(agent => !isSharedSkills(agent)).length`, { agents })
  assert.equal(count, 3)
})
const platform = readFileSync(new URL('../../../web/src/components/ClientSkillActions.vue', import.meta.url), 'utf8')
const desktopHelper = desktop.slice(desktop.indexOf('const skillSharedReaders ='), desktop.indexOf('\n}', desktop.indexOf('const skillSharedReaders =')) + 2)
const platformHelper = platform.slice(platform.indexOf('const sharedReaders ='), platform.indexOf('\nwatch(', platform.indexOf('const sharedReaders =')))

for (const [name, source] of [['desktop', desktopHelper], ['platform', platformHelper]]) {
  const evaluate = (capabilities, target) => JSON.parse(JSON.stringify(vm.runInNewContext(
    `${source}\n${name === 'desktop' ? 'skillSharedReaders(props.agent, path.value)' : 'sharedReaders'}`,
    { props: { agent: { capabilities } }, path: { value: target }, computed: fn => fn() },
  )))
  test(`${name} scopes sharing to the selected Skill and recovery directory`, () => {
    const capabilities = {
      shared_skills: true, shared_skill_readers: ['codex', 'hermes'],
      shared_skill_readers_by_path: { '/private/mine': [], '/shared/common': ['codex', 'hermes'] },
      shared_skill_readers_by_root: { '/private': [], '/shared': ['codex', 'hermes'] },
    }
    assert.deepEqual(evaluate(capabilities, '/private/mine'), [])
    assert.deepEqual(evaluate(capabilities, '/shared/common'), ['codex', 'hermes'])
    assert.deepEqual(evaluate(capabilities, '/shared/removed-skill'), ['codex', 'hermes'])
    assert.deepEqual(evaluate(capabilities, '/private/removed-skill'), [])
    assert.deepEqual(evaluate({ shared_skills: true, shared_skill_readers: ['Cursor'] }, '/legacy/sample'), ['Cursor'])
    assert.deepEqual(evaluate({ shared_skill_readers_by_root: { 'C:\\skills': ['codex', 'hermes'] } }, 'C:\\skills\\sample'), ['codex', 'hermes'])
  })
}
