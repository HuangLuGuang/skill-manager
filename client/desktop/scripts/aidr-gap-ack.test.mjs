import test from 'node:test'
import assert from 'node:assert/strict'
import '../src/aidr-gap-ack.js'
const ack = globalThis.clientAidrGapAck
const diagnostic = () => ({device:'client-a',queue:'/state/hooks',audit_gap:{observed_at:'2026-10-09T07:32:48Z',agent:'codex',hook:'PostToolUse',cause:'aidr_hook_record_oversized',code:'aidr_hook_audit_gap'}})
const storage = () => {
  const data = new Map()
  return {getItem:key=>data.get(key) ?? null,setItem:(key,value)=>data.set(key,value)}
}
test('acknowledges exactly the displayed record without changing diagnostic evidence', () => {
  const store=storage(), original=diagnostic(), before=JSON.stringify(original)
  assert.equal(ack.isAcknowledged(store,original),false)
  assert.equal(ack.acknowledge(store,original),true)
  assert.equal(ack.isAcknowledged(store,JSON.parse(before)),true)
  assert.equal(JSON.stringify(original),before)
  for(const change of [{observed_at:'2026-10-21T12:00:00Z'},{agent:'workbuddy'},{cause:'aidr_hook_receiver_busy'}]) {
    assert.equal(ack.isAcknowledged(store,{...original,audit_gap:{...original.audit_gap,...change}}),false)
  }
  assert.equal(ack.isAcknowledged(store,{...original,device:'client-b'}),false)
  assert.equal(ack.isAcknowledged(store,{...original,queue:'/other/hooks'}),false)
})
test('missing records are not acknowledged and storage failures remain visible',()=>{
  const broken={getItem(){throw Error('unavailable')},setItem(){throw Error('quota')}}
  assert.equal(ack.isAcknowledged(broken,diagnostic()),false)
  assert.throws(()=>ack.acknowledge(broken,diagnostic()),/quota/)
  assert.equal(ack.acknowledge(broken,{}),false)
})
