import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

import { lifecycleVersionId } from '../src/utils/skillVersions.js'

test('lifecycle mutations prefer the immutable version ID', () => {
  assert.equal(
    lifecycleVersionId({ skill_id: 'family-1', version_id: 'version-2' }),
    'version-2',
  )
})

test('legacy records without version_id keep their exact skill ID', () => {
  assert.equal(lifecycleVersionId({ skill_id: 'version-1' }), 'version-1')
  assert.equal(lifecycleVersionId(null), '')
})

test('family list actions pass immutable version IDs to lifecycle APIs', () => {
  const skills = fs.readFileSync(new URL('../src/views/Skills.vue', import.meta.url), 'utf8')
  const deployments = fs.readFileSync(new URL('../src/views/Deployments.vue', import.meta.url), 'utf8')
  assert.match(skills, /rescanSkill\(lifecycleVersionId\(record\)\)/)
  assert.match(skills, /rejectSkill\(lifecycleVersionId\(record\),/)
  assert.match(deployments, /deploySkill\(lifecycleVersionId\(record\)\)/)
  assert.match(deployments, /retireSkill\(lifecycleVersionId\(selectedRecord\.value\),/)
  assert.doesNotMatch(skills, /(?:rescanSkill|rejectSkill)\(record\.skill_id/)
  assert.doesNotMatch(deployments, /(?:deploySkill|retireSkill)\([^\n]*\.skill_id/)
})
