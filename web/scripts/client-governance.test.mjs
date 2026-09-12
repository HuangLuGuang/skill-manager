import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const clientsSource = await readFile(new URL('../src/views/Clients.vue', import.meta.url), 'utf8')
const sharedPredicate = clientsSource.match(/const isSharedSkillsRecord = ([^\n]+)/)[1]
const isShared = new Function(`return (${sharedPredicate})`)()
assert.equal(isShared({agent_type:'codex',capabilities:{shared_skills:true}}), false)
assert.equal(isShared({agent_type:'custom-example',capabilities:{shared_skills:true}}), false)
assert.equal(isShared({agent_type:'global-skills',capabilities:{shared_skills:true}}), true)
const { ref, reactive, computed, watch, nextTick, effectScope } = require('vue')
const source = await readFile(new URL('../src/components/ClientGovernancePolicy.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve=yes; reject=no }); return { promise, resolve, reject } }
const rules = { unverified: 'record', malicious: 'record', trusted_content_changed: 'record', unverified_content_changed: 'record' }
const props = reactive({ open: true, clientId: 'A' })
const emitted = [], notices = [], previews = [], saves = []
let loads = 0
const deps = { ref, computed, watch, defineProps: () => props, defineEmits: () => (...args) => emitted.push(args), useI18n: () => ({ t: x => x }), can: () => true,
message: Object.fromEntries(['error', 'success', 'warning'].map(key => [key, x => notices.push([key,x])])),
getClientGovernance: async id => ({ version: `${id}:${++loads}`, supported: true, enabled: true, overrides: {...rules}, defaults: {...rules, malicious: 'record_only'}, rules: {...rules} }),
previewClientGovernance: (id, body) => { const d=deferred(); previews.push({id, body, ...d}); return d.promise },
saveClientGovernance: (id, body) => { const d=deferred(); saves.push({id, body, ...d}); return d.promise } }
const scope = effectScope()
const component = scope.run(() => new Function(...Object.keys(deps), script + '\nreturn {preview, save, policy, impact, busy, rules, setRule, draftAction, rejectionRule};')(...Object.values(deps)))
const tick = async () => { await nextTick(); await Promise.resolve(); await nextTick() }
await tick()
component.setRule('malicious', '')
assert.equal(component.draftAction('malicious'), 'record_only')
component.setRule('malicious', 'record')
assert.equal(component.draftAction('malicious'), 'record')
assert.equal(component.rejectionRule('trusted_content_changed'), 'trusted_scan_rejected')
assert.equal(component.rejectionRule('unverified_content_changed'), 'unverified_scan_rejected')
const old = component.preview()
props.clientId = 'B'; await tick()
const fresh = component.preview()
previews[0].resolve({preview_id:'old'}); await old
assert.equal(component.impact.value, null)
assert.equal(component.busy.value, true)
previews[1].resolve({preview_id:'fresh'}); await fresh
assert.equal(component.impact.value.preview_id, 'fresh')
component.impact.value.incompatible_clients = [{client_id:'B', rules:['unverified']}]
await component.save()
assert.equal(saves.length, 0)
component.impact.value.incompatible_clients = []
const save = component.save()
await component.save(); assert.equal(saves.length,1)
assert.equal(saves[0].id,'B'); assert.equal(saves[0].body.expected_version,'B:2')
props.clientId = 'C'; await tick()
saves[0].resolve({}); await save
assert.deepEqual(emitted,[])
assert.equal(component.policy.value.version,'C:3')
const conflict = component.preview()
previews[2].reject({apiErrorCode:'client.policy_changed'}); await conflict; await tick()
assert.equal(component.policy.value.version,'C:4')
assert.equal(component.impact.value,null)
assert.equal(component.busy.value,false)
const close = component.preview(); props.open=false; await tick()
previews[3].resolve({preview_id:'closed'}); await close
assert.equal(component.impact.value,null)
assert.equal(notices.filter(x => x[0] === 'success').length,0)
scope.stop()
console.log('PASS: preview switch race, busy isolation, duplicate save, stale save response, version reload, closed modal response')
