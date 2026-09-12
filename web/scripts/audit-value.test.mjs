import test from 'node:test'
import assert from 'node:assert/strict'
import { formatAuditValue } from '../src/utils/auditValue.js'
import { domainMessages } from '../src/i18n/domain.js'
import { validateServiceEndpoint } from '../src/utils/serviceEndpoint.js'
import { uiExperienceMessages } from '../src/i18n/uiExperience.js'

test('MCP endpoint validation distinguishes missing, malformed and supported URLs', () => {
  assert.equal(validateServiceEndpoint('  '), 'uiExperience.endpointRequired')
  for (const value of ['localhost', 'file:///tmp/mcp', 'not a url']) assert.equal(validateServiceEndpoint(value), 'uiExperience.endpointInvalid')
  for (const value of ['https://example.com/mcp', ' http://localhost:8194/mcp ']) assert.equal(validateServiceEndpoint(value), '')
  assert.deepEqual(Object.keys(uiExperienceMessages['zh-CN']).sort(), Object.keys(uiExperienceMessages['en-US']).sort())
})

for (const locale of ['zh-CN', 'en-US']) {
  test(`audit values render domain labels and preserve evidence in ${locale}`, () => {
    const translate = (category, value, fallback) => domainMessages[locale][category]?.[value] ?? fallback
    assert.equal(formatAuditValue('risk_level', 'benign', translate), locale === 'zh-CN' ? '安全' : 'Safe')
    assert.equal(formatAuditValue('status', 'APPROVED', translate), locale === 'zh-CN' ? '已批准' : 'Approved')
    assert.equal(formatAuditValue('max_severity', 'INFO', translate), domainMessages[locale].risk.info)
    assert.equal(formatAuditValue('reason', 'benign', translate), 'benign')
    assert.equal(formatAuditValue('risk_level', 'future-risk', translate), 'future-risk')
    assert.equal(formatAuditValue('violations', [{ evidence: '原文' }], translate), '[{"evidence":"原文"}]')
  })
}
