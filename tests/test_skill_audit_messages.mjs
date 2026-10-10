import assert from 'node:assert/strict'
import test from 'node:test'
import { domainMessages } from '../web/src/i18n/domain.js'

test('audit event, detail and switch resources have complete bilingual keys', () => {
  for (const category of ['auditEvent', 'auditDetail', 'auditValue']) {
    const zh = domainMessages['zh-CN'][category]
    const en = domainMessages['en-US'][category]
    assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort())
    for (const messages of [zh, en]) {
      for (const value of Object.values(messages)) {
        assert.ok(value.trim())
        assert.ok(!value.includes('legacy.'))
      }
    }
  }
  assert.equal(domainMessages['zh-CN'].auditDetail.skill_path, '技能路径')
  assert.equal(domainMessages['en-US'].auditValue.false, 'Disabled')
})
