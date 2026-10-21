// 翻译资源契约检查，不挂载或测试 UI 组件。
import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { createI18n } from '../web/node_modules/vue-i18n/dist/vue-i18n.node.mjs'
import { deepScanMessages } from '../web/src/i18n/deepScan.js'

const catalog = JSON.parse(fs.readFileSync(new URL('../agent_manager/core/deep_scan_catalog.json', import.meta.url), 'utf8'))
const placeholders = value => [...value.matchAll(/\{(p\d+)\}/g)].map(match => match[1]).sort()

test('all known rules have bilingual names, explanations, and recommendations', () => {
  assert.equal(catalog.rules.length, 64)
  for (const rule of catalog.rules) {
    for (const locale of ['zh-CN', 'en-US']) {
      const messages = deepScanMessages[locale]
      for (const field of ['name', 'explanation', 'remediation']) assert.ok(messages[`${rule}_${field}`])
    }
  }
})

test('every recognized template has matching semantic resources and safe interpolation', () => {
  const warnings = []
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: deepScanMessages, warnHtmlMessage: false, onWarn: warning => warnings.push(warning) })
  for (const [code, entry] of Object.entries(catalog.texts)) {
    const en = deepScanMessages['en-US'][code]
    const zh = deepScanMessages['zh-CN'][code]
    assert.equal(typeof en, 'string', code)
    assert.equal(typeof zh, 'string', code)
    assert.deepEqual(placeholders(en), placeholders(zh), code)
    assert.deepEqual(placeholders(entry.template), placeholders(en), code)
    const params = Object.fromEntries(placeholders(en).map(name => [name, `raw-${name}-目录/{token}/x@host\nnext`]))
    for (const locale of ['zh-CN', 'en-US']) {
      const rendered = i18n.global.t(code, params, { locale })
      assert.notEqual(rendered, code)
      for (const value of Object.values(params)) assert.ok(rendered.includes(value), `${code} preserves raw parameter`)
      assert.ok(!rendered.includes('legacy.'))
    }
  }
  assert.deepEqual(warnings, [])
  assert.deepEqual(Object.keys(deepScanMessages['zh-CN']).sort(), Object.keys(deepScanMessages['en-US']).sort())
})

test('TP2 mixed-script advice and other subtypes retain distinct meanings', () => {
  const zh = deepScanMessages['zh-CN']
  assert.equal(zh.TP2_mixed_script_remediation, '标识符中的字符应来自同一种 Unicode 文字系统，优先使用 ASCII 字符命名。')
  assert.match(zh.TP2_direction_remediation, /文字方向覆盖/)
  assert.match(zh.TP2_invisible_remediation, /U\+00AD/)
  assert.match(zh.TP2_homoglyph_remediation, /CI/)
  assert.match(zh.TP2_local_message, /方向覆盖或零宽字符/)
})

test('scanner translations preserve source text, code points, and qualifiers', () => {
  // 英文直接保留来源模板；中文核对编码及关键语义，避免翻译改变检测说明。
  const codePoints = value => [...value.matchAll(/U\+[0-9A-F]{4,6}/g)].map(match => match[0])
  for (const [code, entry] of Object.entries(catalog.texts)) {
    if (entry.source !== 'skillspector') continue
    assert.equal(deepScanMessages['en-US'][code], entry.template, code)
    assert.deepEqual(codePoints(deepScanMessages['zh-CN'][code]), codePoints(entry.template), code)
  }
  const zh = deepScanMessages['zh-CN']
  assert.match(zh.TP2_direction_explanation, /文本方向控制字符.*改变文字的显示顺序.*看起来无害/)
  assert.match(zh.P5_explanation, /可能.*人身伤害/)
  assert.match(zh.PE3_remediation, /生产代码的执行流程/)
  assert.match(zh.TP1_zero_width_explanation, /跟随可见文本时，表示/)
  assert.match(zh.TP3_length_remediation, /少于 \{p0\} 个字符/)
})
