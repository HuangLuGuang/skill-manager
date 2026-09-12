import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { normalizeFindingTraceability } from '../src/securityFindingTraceability.js'

const read = path => readFile(new URL(path, import.meta.url), 'utf8')

test('retry opens the returned task and ignores a second click while submitting', async () => {
  const view = await read('../src/views/AgentSecurityScans.vue')
  const body = view.match(/const retryTask = async record => \{([\s\S]*?)\n\}/)[1]
  const retryingTaskId = { value: null }
  let resolveRequest
  let calls = 0
  const opened = []
  const retryTask = new Function('retryingTaskId', 'canRetry', 'retrySecurityTask', 'loadCoreData', 'openTaskDetail', 'message', 't', 'errorText',
    `return async record => {${body}}`)(retryingTaskId, () => true,
    () => { calls++; return new Promise(resolve => { resolveRequest = resolve }) },
    async () => {}, async id => opened.push(id), { success() {}, error(error) { throw error } }, key => key, error => error)
  const pending = retryTask({ task_id: 'original' })
  await retryTask({ task_id: 'original' })
  assert.equal(calls, 1)
  resolveRequest({ task_id: 'retried' })
  await pending
  assert.deepEqual(opened, ['retried'])
  assert.equal(retryingTaskId.value, null)
})

test('P5 scan workbench exposes every lifecycle stage through a protected route', async () => {
  const [view, router, navigation] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/router/index.js'),
    read('../src/navigation.js'),
  ])

  for (const stage of ['targets', 'policies', 'tasks', 'findings', 'reports']) {
    assert.match(view, new RegExp(`activeStage === '${stage}'|key: '${stage}'`))
  }
  assert.match(router, /path: '\/agent-security\/scans'/)
  assert.match(router, /feature: 'agent_security_scanning'/)
  assert.match(navigation, /key: '\/agent-security\/scans'/)
  assert.doesNotMatch(view, /legacy\./)
})

test('P5 scan workbench uses the dedicated control-plane APIs and guarded mutations', async () => {
  const [view, api, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
  ])

  for (const endpoint of [
    '/v1/agent-security/targets',
    '/v1/agent-security/policies',
    '/v1/agent-security/tasks',
    '/findings/',
    '/artifacts/',
  ]) assert.ok(api.includes(endpoint), `missing API wrapper for ${endpoint}`)

  assert.match(view, /const canAdmin = computed/)
  assert.match(view, /const canViewRaw = computed/)
  assert.match(view, /if \(submittingTarget\.value \|\| testingConnectivity\.value\) return/)
  assert.match(view, /if \(submittingPolicy\.value/)
  assert.match(view, /if \(submittingTask\.value\) return/)
  assert.match(view, /agentSecurityScans\.tasks\.mcpSafety/)
  assert.match(i18n, /MCP scans inspect a frozen gateway metadata snapshot only/)
  assert.match(i18n, /MCP 扫描只读取网关冻结的元数据快照/)
})

test('P5 scan workbench keeps raw artifacts behind the content permission', async () => {
  const view = await read('../src/views/AgentSecurityScans.vue')
  assert.match(view, /item\.content_available && canViewRaw/)
  assert.match(view, /getSecurityArtifactContent/)
})

test('MCP cases separate execution from risk assessment and explain metadata-only limits', async () => {
  const [view, backend, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../../backend/routers/security_scans.py'),
    read('../src/i18n/index.js'),
  ])

  assert.match(view, /caseExecutionLabel\(item\.execution_status\)/)
  assert.match(view, /caseAssessmentLabel\(item\.assessment_status\)/)
  assert.match(view, /item\.tool_calls_performed/)
  assert.match(view, /agentSecurityScans\.detail\.mcpMetadataBoundary/)
  assert.match(backend, /def _case_execution_status/)
  assert.match(backend, /def _case_assessment_status/)
  assert.match(backend, /"risk_signal_detected"/)
  assert.match(backend, /"false_positive"/)
  assert.match(i18n, /发现表示潜在风险信号，不等于已确认漏洞/)
  assert.match(i18n, /Findings are potential risk signals, not confirmed vulnerabilities/)
  assert.doesNotMatch(view, /statusLabel\(item\.status\)/)
})

test('P5-07 finding details navigate to explicitly bound runtime events', async () => {
  const [view, api, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
  ])
  assert.match(api, /getSecurityFinding/)
  assert.match(view, /route\.query\.finding_id/)
  assert.match(view, /getSecurityFinding\(findingId\)/)
  assert.match(await read('../src/views/components/FindingEvidence.vue'), /traceability\.traceId && traceability\.eventId/)
  assert.match(view, /name: 'runtime-traces'/)
  assert.match(view, /trace_id: traceability\.traceId, event_id: traceability\.eventId/)
  assert.match(i18n, /未绑定运行时轨迹事件；系统不会猜测关联/)
  assert.match(i18n, /No runtime trace event is bound/)
})

test('P5-12 keeps the global shell and scan workbench usable on narrow screens', async () => {
  const [app, view] = await Promise.all([
    read('../src/App.vue'),
    read('../src/views/AgentSecurityScans.vue'),
  ])
  assert.match(app, /breakpoint="md"/)
  assert.match(app, /:collapsed-width="narrowNavigation \? 0 : 64"/)
  assert.match(app, /@media \(max-width: 767px\)/)
  assert.match(app, /\.app-content \{ padding: 12px; \}/)
  assert.match(app, /:inert="narrowNavigation && !navigationCollapsed"/)
  assert.match(view, /\.stage-copy small \{[^}]*overflow-wrap: anywhere;/)
  assert.match(view, /\.stage-panel \{ min-width: 0; padding: 14px; overflow: hidden; \}/)
})

test('P6-01 exposes environment and capability boundaries in target and policy workflows', async () => {
  const [view, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/i18n/index.js'),
  ])
  assert.match(view, /const securityEnvironments = \['sandbox', 'test', 'staging', 'production'\]/)
  assert.match(view, /const securityCapabilities = \['conversation', 'multi_turn', 'tool_read', 'tool_write'/)
  assert.match(view, /targetForm\.allowed_capabilities/)
  assert.match(view, /policyForm\.allowed_capabilities/)
  assert.match(view, /policyCompatibleWithTarget\(policy, selectedTaskTarget\.value\)/)
  assert.match(view, /every\(capability => \(target\.allowed_capabilities \|\| \[\]\)\.includes\(capability\)\)/)
  assert.match(view, /environment: targetForm\.environment/)
  assert.match(view, /environment: policyForm\.environment/)
  assert.match(i18n, /environment: '环境'/)
  assert.match(i18n, /environment: 'Environment'/)
  assert.match(i18n, /persistent_memory: '持久记忆'/)
  assert.match(i18n, /persistent_memory: 'Persistent memory'/)
})

test('scan workbench exposes four asset types and bounded AI-Infra-Guard scan options', async () => {
  const [view, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/i18n/index.js'),
  ])

  assert.match(view, /const assetTypes = \['agent', 'mcp', 'llm', 'ai_infrastructure'\]/)
  assert.match(view, /llm: \['llm_redteam_scan'\]/)
  assert.match(view, /ai_infrastructure: \['ai_infrastructure_vulnerability_scan'\]/)
  for (const field of ['datasets', 'num_prompts', 'random_seed', 'techniques', 'evaluation_model']) {
    assert.ok(view.includes(`taskForm.${field}`), `missing LLM red-team field ${field}`)
  }
  for (const field of ['http_authorized', 'private_network_authorized', 'scan_timeout_seconds', 'scan_concurrency']) {
    assert.ok(view.includes(`taskForm.${field}`), `missing infrastructure authorization field ${field}`)
  }
  assert.match(view, /targetForm\.asset_type/)
  assert.match(view, /targetForm\.connector_type/)
  assert.match(view, /asset_type: targetForm\.asset_type/)
  assert.match(view, /connector_type: targetForm\.connector_type/)
  assert.match(i18n, /将向目标模型发送攻击测试请求/)
  assert.match(i18n, /Attack test requests will be sent to the target model/)
  assert.match(view, /agentSecurityScans\.detail\.assessmentScope/)
  assert.match(i18n, /未知指纹或版本保持“证据不足”/)
  assert.match(i18n, /Unknown fingerprints or versions remain Insufficient evidence/)
})

test('scan workbench bounds leading columns and long credential masks', async () => {
  const view = await read('../src/views/AgentSecurityScans.vue')

  assert.match(view, /targets\.name'\), key: 'name', width: 160, ellipsis: true/)
  assert.match(view, /policies\.name'\), key: 'name', width: 160, ellipsis: true/)
  const taskWidth = view.match(/detail\.task'\), key: 'task_id', width: (\d+), ellipsis: true/)
  assert.ok(taskWidth && Number(taskWidth[1]) >= 140 && Number(taskWidth[1]) <= 240)
  assert.match(view, /:scroll="\{ x: 930 \}"/)
  const credentialWidth = view.match(/key: 'credential', width: (\d+), ellipsis: true/)
  assert.ok(credentialWidth && Number(credentialWidth[1]) >= 100 && Number(credentialWidth[1]) <= 180)
  assert.match(view, /:title="targetCredentialLabel\(record\)"/)
  assert.match(view, /\.credential-tag__text \{[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/)
})

test('report drawer and asset inventory keep trailing actions visible', async () => {
  const [view, inventory] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/views/components/DifyAssetInventory.vue'),
  ])

  assert.match(view, /width="min\(1440px, 96vw\)"/)
  assert.match(inventory, /key: 'details', width: 90, fixed: 'right'/)
  assert.match(inventory, /key: 'actions', width: 96, fixed: 'right'/)
  assert.match(inventory, /:scroll="\{ x: 1000 \}"/)
})

test('asset inventory filters apply immediately and ignore stale responses', async () => {
  const inventory = await read('../src/views/components/DifyAssetInventory.vue')

  assert.doesNotMatch(inventory, /agentSecurityScans\.inventory\.applyFilters/)
  assert.match(inventory, /filters\.asset_type, filters\.source_type, filters\.verification_status/)
  assert.match(inventory, /watch\(\(\) => filters\.node_id/)
  assert.match(inventory, /setTimeout\(loadInventory, value\.trim\(\) \? 300 : 0\)/)
  assert.match(inventory, /requestSequence === inventoryRequestSequence/)
  assert.match(inventory, /summaryKeyByAssetType = \{ node: 'nodes', prompt: 'prompts', mcp: 'mcp', tool: 'tools', knowledge: 'knowledge_bases' \}/)
  assert.match(inventory, /inventory\.value\?\.summary\?\.\[summaryKeyByAssetType\[type\]\]/)
})

test('Dify inventory exposes intent diagnostics and reliable knowledge reference mapping', async () => {
  const [view, inventory, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/views/components/DifyAssetInventory.vue'),
    read('../src/i18n/index.js'),
  ])

  assert.match(view, /dify_knowledge_bindings_json/)
  assert.match(view, /knowledge_bindings: knowledgeBindings/)
  assert.match(inventory, /dataset_reference_status/)
  assert.match(inventory, /datasetReferenceUnmapped/)
  assert.match(inventory, /dify_console_draft_workflow/)
  assert.match(inventory, /draftWorkflowMapped/)
  assert.match(inventory, /diagnostic_code/)
  assert.match(inventory, /intentDiagnosticLabel/)
  assert.match(i18n, /导出 DSL 隐藏了知识库标识，且未能从草稿工作流可靠映射/)
  assert.match(i18n, /Dataset UUID 来自 Dify 草稿工作流 · 草稿可能与已发布版本不同/)
  assert.match(i18n, /The export DSL concealed the Dataset identifier/)
  assert.match(i18n, /draft may differ from the published version/)
  assert.match(i18n, /confidence_invalid/)
})

test('Dify MCP bindings use snapshot-backed explicit server selection and preview counts', async () => {
  const [view, api, i18n, errors] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
    read('../src/i18n/errors.js'),
  ])

  assert.doesNotMatch(view, /v-model:value="targetForm\.dify_mcp_bindings_json"/)
  assert.match(view, /class="mcp-binding-editor"/)
  assert.match(view, /v-for="binding in targetForm\.dify_mcp_bindings"/)
  assert.match(view, /v-model:value="binding\.server_id"/)
  assert.match(view, /server\.health_status/)
  assert.match(view, /server\.tools_list_at/)
  assert.match(view, /server\.tool_count/)
  assert.match(view, /taskPreview\.tool_plan\.dify_mcp_bindings/)
  assert.match(view, /getDifyMcpBindingOptions\(record\.target_id\)/)
  assert.doesNotMatch(view, /similar|相似度/)
  assert.match(api, /targets\/\$\{targetId\}\/dify-mcp-binding-options/)
  assert.match(i18n, /configured_tool_not_discovered/)
  assert.match(errors, /dify_inventory\.mcp_server_not_found/)
})

test('Dify intent layout gives long system inference the full content width', async () => {
  const inventory = await read('../src/views/components/DifyAssetInventory.vue')

  assert.match(inventory, /class="intent-source-strip"/)
  assert.match(inventory, /\.intent-overview \{[^}]*grid-template-columns: minmax\(0, 1fr\)/)
  assert.match(inventory, /\.intent-source-strip \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(inventory, /\.intent-entry ul \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
  assert.match(inventory, /@media \(max-width: 560px\)[^{]*\{[^}]*\.profile-header[^}]*\}\.profile-status[^}]*\}\.intent-source-strip \{ grid-template-columns: 1fr;/)
})

test('P6-02 prevents selecting active-full mode for production policies', async () => {
  const [view, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/i18n/index.js'),
  ])
  assert.match(view, /:disabled="policyForm\.environment === 'production' && mode === 'active_full'"/)
  assert.match(view, /@change="handlePolicyEnvironmentChange"/)
  assert.match(view, /environment === 'production' && policyForm\.execution_mode === 'active_full'/)
  assert.match(view, /policyForm\.execution_mode = 'read_only'/)
  assert.match(view, /agentSecurityScans\.policies\.productionModeBoundary/)
  assert.match(i18n, /生产环境禁止使用“完整主动”模式/)
  assert.match(i18n, /Active-full mode is forbidden in production/)
})

test('P6-03 requires bound one-time approval for production active-safe scans', async () => {
  const [view, api, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
  ])

  assert.match(api, /\/v1\/agent-security\/scan-approvals/)
  for (const field of ['production_target_ids', 'maintenance_window_start', 'maintenance_window_end', 'dedicated_identity_ref']) {
    assert.ok(view.includes(field), `missing production control field ${field}`)
  }
  assert.match(view, /const requiresProductionApproval = computed/)
  assert.match(view, /createSecurityScanApproval\(\{ target_id: taskForm\.target_id, policy_id: taskForm\.policy_id \}\)/)
  assert.match(view, /approval_id: requiresProductionApproval\.value \? taskForm\.approval_id : null/)
  assert.match(view, /requiresProductionApproval\.value && !taskForm\.approval_id/)
  assert.match(view, /selectedTaskTarget\?\.credential_configured/)
  assert.match(i18n, /创建一个任务后立即失效/)
  assert.match(i18n, /expires after one task is created/)
})

test('P6-04 exposes server-enforced Tool access and production denylist controls', async () => {
  const [view, i18n] = await Promise.all([
    read('../src/views/McpGateway.vue'),
    read('../src/i18n/index.js'),
  ])

  assert.match(view, /toolPolicyForm\.access_mode/)
  assert.match(view, /\['unknown', 'read', 'write', 'destructive'\]/)
  assert.match(view, /environment: gatewayForm\.environment/)
  assert.match(view, /execution_mode: gatewayForm\.execution_mode/)
  assert.match(view, /production_tool_denylist: \[\.\.\.gatewayForm\.production_tool_denylist\]/)
  assert.match(view, /gatewayForm\.environment === 'production' && value === 'active_full'/)
  assert.match(view, /toolPolicyForm\.access_mode === 'destructive'/)
  assert.match(i18n, /未分类 Tool 在只读模式下按非只读处理并拒绝调用/)
  assert.match(i18n, /Unclassified Tools fail closed as non-read operations in read-only mode/)
  assert.match(i18n, /不采信调用方传入的环境标记/)
  assert.match(i18n, /caller-supplied environment markers are ignored/)
})

test('P6-05 requires a server-derived scan preview before task creation', async () => {
  const [view, api, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
  ])

  assert.match(api, /\/v1\/agent-security\/tasks\/preview/)
  assert.match(view, /previewSecurityTask\(payload\)/)
  assert.match(view, /:disabled="submittingTask \|\| previewingTask \|\| evaluatorSelectionMissing \|\| \(executionMode === \'now\' \? !taskPreview/)
  assert.match(view, /preview_fingerprint: taskPreview\.value\.preview_fingerprint/)
  assert.match(view, /error_code === 'agent_security\.scan_preview_stale'/)
  assert.match(view, /taskPreview\.cases/)
  assert.match(view, /taskPreview\.tool_plan\.tools/)
  assert.match(view, /taskPreview\.budget\.max_rounds/)
  assert.match(view, /runtimeDynamic/)
  assert.match(i18n, /具体测试 Prompt 和轮次由运行时生成/)
  assert.match(i18n, /concrete prompts and rounds are generated at runtime/)
})

test('P6-06 exposes an admin-only audited task Kill Switch with an explicit boundary', async () => {
  const [view, api, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
  ])

  assert.match(api, /\/v1\/agent-security\/tasks\/\$\{taskId\}\/kill-switch/)
  assert.match(view, /const canKill = record => canAdmin\.value/)
  assert.match(view, /!record\.kill_switch_activated/)
  assert.match(view, /activateSecurityTaskKillSwitch\(killSwitchTask\.value\.task_id/)
  assert.match(view, /!killSwitchReason\.value\.trim\(\)/)
  assert.match(view, /taskDetail\.task\.kill_switch_activated_by/)
  assert.match(i18n, /已经发出的请求由目标或评估器客户端的请求超时结束/)
  assert.match(i18n, /Requests already in flight finish through the target or evaluator client timeout/)
})

test('P6-07 displays pinned OWASP ASI mappings without guessing unknown findings', async () => {
  const [view, taxonomy, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/agenticRiskTaxonomy.js'),
    read('../src/i18n/index.js'),
  ])

  assert.match(view, /record\.risk_codes/)
  assert.match(await read('../src/views/components/FindingEvidence.vue'), /finding\.risk_mapping\?\.mapping_version/)
  assert.match(view, /selectedFinding\.risk_codes/)
  assert.match(view, /agenticRiskLabel/)
  assert.match(taxonomy, /ASI_CODE = \/\^ASI/)
  assert.match(taxonomy, /return String\(code \|\| ''\)/)
  assert.match(i18n, /未映射到 OWASP ASI/)
  assert.match(i18n, /Not mapped to OWASP ASI/)
})

test('P6-08 separates resolved findings from risks that could not be retested', async () => {
  const [view, api, backend, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/api/index.js'),
    read('../../backend/routers/security_scans.py'),
    read('../src/i18n/index.js'),
  ])

  assert.match(api, /compareSecurityTasks/)
  assert.match(api, /\/compare\/\$\{baselineTaskId\}/)
  assert.match(view, /comparisonResult\.comparison_status/)
  assert.match(view, /comparisonResult\.coverage_match/)
  assert.match(view, /unable_to_retest/)
  assert.match(view, /comparisonReasonLabel/)
  assert.match(backend, /security-scan-comparison@1/)
  assert.match(backend, /current_not_succeeded/)
  assert.match(backend, /coverage_changed/)
  assert.match(backend, /engine_changed/)
  assert.match(i18n, /测试范围及引擎一致时/)
  assert.match(i18n, /Complete evaluations, matching coverage and engine versions/)
})

test('P6-09 displays the frozen report template and decision criteria versions', async () => {
  const [view, contract, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../../backend/security_report_contract.py'),
    read('../src/i18n/index.js'),
  ])

  assert.match(contract, /security-report-contract@4/)
  assert.match(contract, /agent-security-report-template@4/)
  assert.match(contract, /agent-security-decision-criteria@2/)
  assert.match(contract, /empty_findings_is_not_safe/)
  assert.match(contract, /case_blocked_or_error_is_unverified/)
  assert.match(view, /taskDetail\.task\.decision_criteria_version/)
  assert.match(view, /taskDetail\.task\.report_template_version/)
  assert.match(await read('../src/views/components/FindingEvidence.vue'), /traceability\.decisionCriteriaVersion/)
  assert.match(i18n, /判定口径版本/)
  assert.match(i18n, /Decision criteria version/)
})

test('P7-03 presents complete traceability and keeps legacy gaps explicit', async () => {
  const complete = normalizeFindingTraceability({
    case_id: 'ascase_1',
    trace_id: 'trc_1',
    event_id: 'evt_1',
    decision_criteria_version: 'criteria@1',
    traceability: {
      status: 'complete',
      case_id: 'ascase_1',
      trace_id: 'trc_1',
      event_id: 'evt_1',
      evidence_sha256: 'a'.repeat(64),
      decision_criteria_version: 'criteria@1',
      missing: [],
    },
  })
  assert.deepEqual(complete, {
    status: 'complete',
    caseId: 'ascase_1',
    traceId: 'trc_1',
    eventId: 'evt_1',
    evidenceSha256: 'a'.repeat(64),
    decisionCriteriaVersion: 'criteria@1',
    missing: [],
  })

  const legacy = normalizeFindingTraceability({ finding_id: 'asf_legacy' })
  assert.equal(legacy.status, 'incomplete')
  assert.deepEqual(legacy.missing, ['case', 'event', 'evidence', 'decision_criteria'])
  assert.equal(legacy.traceId, null)
  assert.equal(legacy.eventId, null)

  const [view, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/i18n/index.js'),
  ])
  assert.match(view, /normalizeFindingTraceability/)
  assert.match(await read('../src/views/components/FindingEvidence.vue'), /traceability\.evidenceSha256/)
  assert.match(view, /selectedFindingTraceability\.missing/)
  assert.match(i18n, /完整可追溯/)
  assert.match(i18n, /Complete and traceable/)
})


test('failed scan details separate execution failure from a successful zero-finding report', async () => {
  const [view, i18n] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/i18n/index.js'),
  ])

  assert.match(view, /taskDetail\.task\.error_code/)
  assert.match(view, /taskErrorExplanation\(taskDetail\.task\)/)
  assert.match(view, /taskReasonLabel\(taskDetail\.task\.stop_reason\)/)
  assert.match(view, /taskDetail\.task\.heartbeat_at/)
  assert.match(view, /taskDetail\.task\.lease_expires_at/)
  assert.match(view, /taskHasNoFinalReport/)
  assert.match(view, /successfulTaskHasNoFindings/)
  assert.match(i18n, /本任务未形成最终扫描报告/)
  assert.match(i18n, /实时记录显示已完成/)
  assert.match(i18n, /No final scan report was produced/)
  assert.match(i18n, /must not be interpreted as proof that the target is absolutely safe/)
  for (const code of [
    'agent_security.usage_not_monotonic',
    'agent_security.worker_lease_lost',
    'lease_expired_retry',
    'lease_expired_attempts_exhausted',
    'worker_requested_retry',
    'budget.max_tokens_exceeded',
  ]) assert.match(view, new RegExp(code.replaceAll('.', '\\.')))
})

test('agent scan cases show per-rule evidence states without treating transcripts as passed rules', async () => {
  const [view, i18n, backendSchema] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/i18n/index.js'),
    read('../../backend/security_scan_schemas.py'),
  ])

  assert.match(backendSchema, /"passed", "failed", "blocked", "error", "unverified"/)
  assert.match(view, /caseCoverage\.planned_cases/)
  assert.match(view, /caseCoverage\.passed_cases/)
  assert.match(view, /caseCoverage\.failed_cases/)
  assert.match(view, /caseCoverage\.error_cases/)
  assert.match(view, /caseCoverage\.blocked_cases/)
  assert.match(view, /caseCoverage\.unverified_cases/)
  assert.match(view, /response_summary\?\.dialogue_calls/)
  assert.match(view, /response_summary\?\.finding_count/)
  assert.match(view, /unverified: 'default'/)
  assert.doesNotMatch(view, /agent-dialogue-transcript/)
  assert.match(i18n, /计划规则/)
  assert.match(i18n, /证据不足/)
  assert.match(i18n, /plannedCases|Planned cases|Recorded cases/)
  assert.match(i18n, /Insufficient evidence/)
  assert.match(i18n, /target.*safe|safe.*target/i)
})

test('Dify inventory exposes structured collection controls, evidence filters, and audited Prompt reveal', async () => {
  const [view, inventory, api, i18n, errors] = await Promise.all([
    read('../src/views/AgentSecurityScans.vue'),
    read('../src/views/components/DifyAssetInventory.vue'),
    read('../src/api/index.js'),
    read('../src/i18n/index.js'),
    read('../src/i18n/errors.js'),
  ])

  assert.match(view, /scan_kind === 'dify_asset_inventory'/)
  for (const field of ['dify_console_base_url', 'dify_workspace_id', 'dify_app_id', 'dify_workflow_id', 'dify_declared_intent', 'dify_mcp_bindings']) {
    assert.ok(view.includes(`targetForm.${field}`), `missing structured Dify field ${field}`)
  }
  assert.match(view, /taskForm\.inventory_source/)
  assert.match(view, /taskForm\.include_prompt_text/)
  assert.match(view, /taskForm\.infer_agent_intent/)
  assert.match(view, /taskForm\.intent_inference_model/)
  assert.match(view, /listModelEndpoints/)
  assert.match(view, /v-model:checked="taskForm\.include_prompt_text" :disabled="!canCollectPrivateContent"/)
  assert.match(view, /v-model:checked="taskForm\.infer_agent_intent" :disabled="!canCollectPrivateContent"/)
  assert.match(view, /taskForm\.knowledge_content_authorized/)
  assert.match(api, /\/tasks\/\$\{taskId\}\/inventory/)
  assert.match(api, /\/inventory\/compare/)
  assert.match(api, /\/inventory\/items\/\$\{itemId\}\/content/)
  assert.match(api, /\/credentials\/\$\{credentialId\}\/status/)
  assert.match(inventory, /getSecurityInventoryPromptContent/)
  assert.match(inventory, /Modal\.confirm/)
  assert.match(inventory, /verification_status/)
  assert.match(inventory, /source_type/)
  assert.match(inventory, /record\.configured/)
  assert.match(inventory, /record\.discovered/)
  assert.match(inventory, /record\.executed/)
  assert.match(inventory, /key: 'configuration'/)
  assert.match(inventory, /key: 'verification_summary'/)
  assert.doesNotMatch(inventory, /key: 'facts'/)
  assert.doesNotMatch(inventory, /key: 'sources'/)
  assert.match(inventory, /assetDetailPayload/)
  assert.match(inventory, /sources: record\.sources/)
  assert.match(inventory, /intent_alignment.*potential_mismatch/)
  assert.match(inventory, /inferred_intent/)
  for (const field of ['name', 'description', 'updated_at', 'last_collected_at', 'verification_status']) {
    assert.ok(inventory.includes(`'${field}'`), `missing Dify profile field ${field}`)
  }
  assert.match(view, /toggleCredentialStatus/)
  assert.match(view, /credentialStatusUpdating/)
  assert.match(view, /item\.status !== 'revoked'/)
  assert.match(i18n, /系统推断/)
  assert.match(i18n, /System inferred/)
  assert.match(i18n, /任务成功不代表资产全部验证完成/)
  assert.match(i18n, /Task success does not mean all assets are verified/)
  assert.match(i18n, /脱敏后的 Prompt 和工作流摘要/)
  assert.match(i18n, /system-inferred, not a confirmed fact/)
  assert.match(i18n, /DSL 已确认 · 未发现执行证据/)
  assert.match(i18n, /Confirmed by DSL · no execution evidence observed/)
  for (const code of [
    'dify_inventory.console_auth_failed',
    'dify_inventory.console_forbidden',
    'dify_inventory.app_not_found',
    'dify_inventory.export_not_supported',
    'dify_inventory.response_too_large',
    'dify_inventory.response_invalid',
    'dify_inventory.dsl_invalid',
    'dify_inventory.upstream_unavailable',
  ]) assert.ok(errors.includes(`'${code}'`), `missing localized Dify error ${code}`)
})
