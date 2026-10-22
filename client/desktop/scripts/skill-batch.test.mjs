import test from 'node:test'
import assert from 'node:assert/strict'
import '../src/skill-batch.js'
const {isCertified, isScanActive, execute} = globalThis.clientSkillBatch

test('background completion requires the same snapshot and a new confirmed submission', () => {
  const result = {status:'failed',error:'skill_action_busy',item:{path:'/skill',signature:'a'}}
  const skill = {path:'/skill',signature:'a',governance:{signature:'a'}}
  const scan = {skill_id:'family',submitted_at:'2026-10-21T09:00:01Z'}
  const started = Date.parse('2026-10-21T09:00:00Z')
  const check = globalThis.clientSkillBatch.completedInBackground
  assert.equal(check(result,skill,scan,started),true)
  assert.equal(check(result,skill,scan,started+2000),false)
  assert.equal(check(result,{...skill,signature:'b'},scan,started),false)
  assert.equal(check(result,skill,{...scan,skill_id:''},started),false)
  assert.equal(check({...result,error:'skill_content_changed'},skill,scan,started),false)
})

test('a local snapshot awaiting upload remains retryable after submission failure', () => {
  assert.equal(isScanActive({status:'pending'}),false)
  assert.equal(isScanActive(null),false)
  for (const status of ['submitted','PENDING','VETTED']) assert.equal(isScanActive({status}),true)
})

test('certification belongs to exact nonempty content, not its name or previous version', () => {
  assert.equal(isCertified({signature:'a',governance:{signature:'a',certification:'certified'}}),true)
  for (const skill of [{}, {signature:'',governance:{signature:'',certification:'certified'}}, {signature:'b',governance:{signature:'a',certification:'certified'}}, {signature:'a',governance:{signature:'a',certification:'unverified'}}]) assert.equal(isCertified(skill),false)
})
test('batch continues after failure, preserves per-item results and never runs concurrently', async () => {
  let active = 0
  const called = [], progress = []
  const result = await execute([1,2,3,4],async item => {
    assert.equal(++active,1)
    called.push(item)
    await new Promise(resolve=>setTimeout(resolve,1))
    active--
    if (item===2) throw new Error('permission_denied')
    return item===3 ? {skipped:'certified'} : item===4 ? {already_submitted:true} : {}
  }, (result, count)=>progress.push([result.item,count]))
  assert.deepEqual(called,[1,2,3,4])
  assert.deepEqual(result.map(r=>r.status),['succeeded','failed','skipped','succeeded'])
  assert.match(result[1].error,/permission_denied/)
  assert.equal(result[3].reason,'already_submitted')
  assert.deepEqual(progress,[[1,1],[2,2],[3,3],[4,4]])
  assert.deepEqual(await execute([],()=>assert.fail()),[])
})
