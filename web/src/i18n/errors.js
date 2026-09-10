import { scanScheduleMessages } from './scanSchedule.js'
const errorMessages = {
  'policy.simulation_invalid': { 'zh-CN': '模拟参数无效，请检查分析器状态、发现项和策略配置。', 'en-US': 'Invalid simulation inputs. Check analyzer states, findings, and policy settings.' },
  'skill_not_found': { 'zh-CN': 'Skill 不存在', 'en-US': 'Skill not found' },
  'agent_security.llm_coverage_incomplete': { 'zh-CN': '测试覆盖不完整：实际用例少于计划数量，请检查扫描引擎并重新扫描', 'en-US': 'Incomplete test coverage: fewer cases than planned. Check the scan engine and run again.' },
  ...Object.fromEntries(Object.keys(scanScheduleMessages['zh-CN'].errors).map(code => [code, { 'zh-CN': scanScheduleMessages['zh-CN'].errors[code], 'en-US': scanScheduleMessages['en-US'].errors[code] }])),
  'asset_sync.source_busy': { 'zh-CN': '该来源已有同步批次运行中', 'en-US': 'A synchronization run is already active for this source' },
  'asset_sync.source_exists': { 'zh-CN': '该工作空间或目标已有资产来源配置', 'en-US': 'This workspace or target already has an asset source' },
  'asset_sync.source_not_found': { 'zh-CN': '资产来源不存在', 'en-US': 'Asset source not found' },
  'asset_sync.run_not_found': { 'zh-CN': '同步批次不存在', 'en-US': 'Synchronization run not found' },
  'asset_sync.config_conflict': { 'zh-CN': '配置已变化或仍有同步运行，请刷新后重试', 'en-US': 'The configuration changed or a synchronization run is active; refresh and retry' },
  'asset_sync.owner_unavailable': { 'zh-CN': '同步授权账号已失效，请由管理员重新保存来源', 'en-US': 'The authorizing account is unavailable; an administrator must save the source again' },
  'asset_sync.target_unavailable': { 'zh-CN': 'Dify 来源目标未启用', 'en-US': 'The Dify source target is unavailable' },
  'asset_sync.connection_changed': { 'zh-CN': '来源连接或归属已变化，请重新保存资产来源', 'en-US': 'The source connection or ownership changed; save the asset source again' },
  'asset_sync.policy_unavailable': { 'zh-CN': '同步或扫描策略未启用，或目标环境不匹配', 'en-US': 'The inventory or scan policy is unavailable or has a different environment' },
  'asset_sync.dify_required': { 'zh-CN': '请选择 Dify 来源目标', 'en-US': 'Select a Dify source target' },
  'asset_sync.pagination_invalid': { 'zh-CN': '应用分页结果不完整或重复，请检查 Dify 接口版本及权限', 'en-US': 'Application pagination is incomplete or repeated; check the Dify API version and permissions' },
  'asset_sync.scope_limit_exceeded': { 'zh-CN': '应用数量超过本次同步上限，请缩小范围', 'en-US': 'The application count exceeds the synchronization limit; narrow the scope' },
  'asset_sync.discovery_timeout': { 'zh-CN': '应用发现超时，请检查来源连接后重试', 'en-US': 'Application discovery timed out; check the source connection and retry' },
  'asset_sync.execution_failed': { 'zh-CN': '同步执行失败，请检查服务日志后重试', 'en-US': 'Synchronization failed; check the service logs and retry' },
  'asset_sync.lease_lost': { 'zh-CN': '同步租约已失效，等待任务重新领取', 'en-US': 'The synchronization lease expired; waiting for another claim' },
  'agent_risk.agent_not_found': { 'zh-CN': '智能体不存在', 'en-US': 'Managed agent not found' },
  'agent_risk.issue_not_found': { 'zh-CN': '风险项不存在', 'en-US': 'Risk issue not found' },
  'agent_risk.closure_unverified': { 'zh-CN': '缺少当前资产版本的可比复扫关闭证据', 'en-US': 'Comparable rescan closure evidence for the current asset version is required' },
  'agent_risk.link_scope_invalid': { 'zh-CN': '关联 MCP 目标必须具有相同归属和访问范围', 'en-US': 'Linked MCP targets must have the same ownership and access scope' },
  'auth.username_already_registered': {
    'zh-CN': '用户名已存在',
    'en-US': 'Username is already registered',
  },
  'auth.captcha_expired': {
    'zh-CN': '验证码无效或已过期',
    'en-US': 'The verification code is invalid or expired',
  },
  'auth.captcha_incorrect': {
    'zh-CN': '验证码错误',
    'en-US': 'The verification code is incorrect',
  },
  'auth.invalid_credentials': {
    'zh-CN': '用户名或密码错误',
    'en-US': 'Incorrect username or password',
  },
  'auth.invalid_token': {
    'zh-CN': '登录凭证无效',
    'en-US': 'Could not validate credentials',
  },
  'auth.session_expired_elsewhere': {
    'zh-CN': '当前账号已在其他位置登录，请重新登录',
    'en-US': 'This account signed in elsewhere. Sign in again.',
  },
  'auth.account_disabled': {
    'zh-CN': '账号已被禁用',
    'en-US': 'The account is disabled',
  },
  'auth.permission_denied': {
    'zh-CN': '权限不足',
    'en-US': 'Permission denied',
  },
  'auth.old_password_incorrect': {
    'zh-CN': '旧密码不正确',
    'en-US': 'The current password is incorrect',
  },
  'credential.missing': {
    'zh-CN': '缺少接入凭证',
    'en-US': 'Missing access credential',
  },
  'credential.invalid_or_disabled': {
    'zh-CN': '接入凭证无效或已禁用',
    'en-US': 'The access credential is invalid or disabled',
  },
  'credential.expired': {
    'zh-CN': '接入凭证已过期',
    'en-US': 'The access credential has expired',
  },
  'credential.scope_missing': {
    'zh-CN': '接入凭证缺少权限：{scopes}',
    'en-US': 'The access credential requires scope: {scopes}',
  },
  'credential.ip_not_allowed': {
    'zh-CN': '接入凭证不允许当前来源 IP',
    'en-US': 'The source IP is not allowed by this credential',
  },
  'credential.concurrency_limit': {
    'zh-CN': '接入凭证并发请求数已达上限',
    'en-US': 'The credential concurrency limit has been reached',
  },
  'credential.name_required': {
    'zh-CN': '凭证名称不能为空',
    'en-US': 'Credential name is required',
  },
  'credential.not_found': {
    'zh-CN': '接入凭证不存在',
    'en-US': 'Access credential not found',
  },
  'agent.id_missing': {
    'zh-CN': '缺少 agent_id',
    'en-US': 'Missing agent_id',
  },
  'agent.id_mismatch': {
    'zh-CN': 'agent_id 与 X-Agent-ID 不一致',
    'en-US': 'agent_id does not match X-Agent-ID',
  },
  'agent.credential_binding_mismatch': {
    'zh-CN': '接入凭证绑定的智能体不匹配',
    'en-US': 'The credential is bound to a different Agent',
  },
  'agent.not_found': {
    'zh-CN': '智能体不存在',
    'en-US': 'Agent not found',
  },
  'agent.disabled': {
    'zh-CN': '智能体未启用',
    'en-US': 'Agent is disabled',
  },
  'agent.skill_not_allowed': {
    'zh-CN': '智能体未授权使用该 Skill',
    'en-US': 'The Agent is not authorized to use this Skill',
  },
  'agent.prompt_not_allowed': {
    'zh-CN': '智能体未授权使用该 Prompt',
    'en-US': 'The Agent is not authorized to use this Prompt',
  },
  'docs_assistant.disabled': {
    'zh-CN': '文档助手当前未启用',
    'en-US': 'The documentation assistant is currently disabled',
  },
  'docs_assistant.model_required': {
    'zh-CN': '启用文档助手前请选择模型',
    'en-US': 'Select a model before enabling the documentation assistant',
  },
  'docs_assistant.model_unavailable': {
    'zh-CN': '文档助手配置的模型当前不可用',
    'en-US': 'The model configured for the documentation assistant is unavailable',
  },
  'docs_assistant.upstream_failed': {
    'zh-CN': '文档助手暂时无法调用所选模型',
    'en-US': 'The documentation assistant could not call the selected model',
  },
  'docs_assistant.empty_response': {
    'zh-CN': '模型没有返回可用的文档回答',
    'en-US': 'The model did not return a usable documentation answer',
  },
  'agent_security.feature_disabled': {
    'zh-CN': 'AI 安全扫描功能未启用',
    'en-US': 'AI security scanning is not enabled',
  },
  'runtime_trace.feature_disabled': {
    'zh-CN': '统一调用轨迹功能未启用',
    'en-US': 'Runtime trace is not enabled',
  },
  'agent_security.baseline_unavailable': {
    'zh-CN': 'AI 安全上游版本清单不存在',
    'en-US': 'The AI Security upstream lock is unavailable',
  },
  'agent_security.baseline_invalid': {
    'zh-CN': 'AI 安全上游版本清单校验失败',
    'en-US': 'The AI Security upstream lock is invalid',
  },
  'agent_security.usage_not_monotonic': {
    'zh-CN': 'Worker 上报的累计用量不能减少',
    'en-US': 'Worker cumulative usage must not decrease',
  },
  'agent_security.worker_lease_lost': {
    'zh-CN': 'Worker 租约已丢失',
    'en-US': 'The Worker lease was lost',
  },
  'agent_security.finding_trace_reference_invalid': {
    'zh-CN': '安全发现关联的运行时轨迹事件不存在',
    'en-US': 'The runtime trace event linked by the finding does not exist',
  },
  'agent_security.finding_trace_scope_mismatch': {
    'zh-CN': '安全发现与运行时轨迹事件的归属范围不一致',
    'en-US': 'The finding and runtime trace event have different ownership scopes',
  },
  'agent_security.comparison_same_task': {
    'zh-CN': '当前任务和基线任务不能相同',
    'en-US': 'The current task and baseline task must be different',
  },
  'agent_security.comparison_target_mismatch': {
    'zh-CN': '只能比较同一扫描目标的任务',
    'en-US': 'Only tasks for the same scan target can be compared',
  },
  'agent_security.comparison_scan_kind_mismatch': {
    'zh-CN': '只能比较同一扫描类型的任务',
    'en-US': 'Only tasks with the same scan type can be compared',
  },
  'agent_security.comparison_baseline_newer': {
    'zh-CN': '基线任务必须早于当前任务',
    'en-US': 'The baseline task must be older than the current task',
  },
  'dify_inventory.console_auth_failed': {
    'zh-CN': 'Dify Console Admin API Key 无效或已过期',
    'en-US': 'The Dify Console Admin API key is invalid or expired',
  },
  'dify_inventory.console_forbidden': {
    'zh-CN': 'Dify Console 凭据无权访问该应用或工作区',
    'en-US': 'The Dify Console credential cannot access this app or workspace',
  },
  'dify_inventory.app_not_found': {
    'zh-CN': 'Dify 应用不存在，或当前工作区不可见',
    'en-US': 'The Dify app does not exist or is not visible in this workspace',
  },
  'dify_inventory.export_not_supported': {
    'zh-CN': '当前 Dify 版本或应用不支持 Console DSL 导出',
    'en-US': 'This Dify version or app does not support Console DSL export',
  },
  'dify_inventory.response_too_large': {
    'zh-CN': 'Dify Console 响应超过 10 MiB 安全上限',
    'en-US': 'The Dify Console response exceeds the 10 MiB safety limit',
  },
  'dify_inventory.response_invalid': {
    'zh-CN': 'Dify Console 返回了无法识别的响应',
    'en-US': 'Dify Console returned an unrecognized response',
  },
  'dify_inventory.dsl_invalid': {
    'zh-CN': 'Dify 工作流 DSL 格式无效',
    'en-US': 'The Dify workflow DSL is invalid',
  },
  'dify_inventory.upstream_unavailable': {
    'zh-CN': 'Dify Console 暂时不可用，或目标未通过出站安全校验',
    'en-US': 'Dify Console is unavailable or failed outbound security validation',
  },
  'dify_inventory.console_credential_required': {
    'zh-CN': '自动采集需要配置 Dify Console Admin API 凭据',
    'en-US': 'Console API collection requires a Dify Console Admin API credential',
  },
  'dify_inventory.knowledge_credential_required': {
    'zh-CN': '知识库内容检查需要配置 Dify Knowledge API 凭据',
    'en-US': 'Knowledge content inspection requires a Dify Knowledge API credential',
  },
  'dify_inventory.dataset_not_found': {
    'zh-CN': 'Dify 数据集不存在，或当前 Knowledge API 凭据不可见',
    'en-US': 'The Dify Dataset does not exist or is not visible to this Knowledge API credential',
  },
  'dify_inventory.dataset_forbidden': {
    'zh-CN': 'Dify Knowledge API 凭据无权访问该数据集',
    'en-US': 'The Dify Knowledge API credential cannot access this Dataset',
  },
  'dify_inventory.dataset_reference_unmapped': {
    'zh-CN': 'DSL 知识库引用无法映射到 Knowledge API 数据集',
    'en-US': 'The DSL knowledge reference cannot be mapped to a Knowledge API Dataset',
  },
  'dify_inventory.dataset_reference_ambiguous': {
    'zh-CN': 'DSL 知识库引用对应多个可靠数据集标识，无法唯一映射',
    'en-US': 'The DSL knowledge reference has multiple reliable Dataset identifiers and cannot be mapped uniquely',
  },
  'dify_inventory.draft_workflow_unavailable': {
    'zh-CN': 'Dify 草稿工作流接口不可用，无法辅助解析知识库标识',
    'en-US': 'The Dify draft workflow endpoint is unavailable, so Dataset references cannot be resolved from it',
  },
  'dify_inventory.draft_workflow_invalid': {
    'zh-CN': 'Dify 草稿工作流响应格式无效，无法辅助解析知识库标识',
    'en-US': 'The Dify draft workflow response is invalid, so Dataset references cannot be resolved from it',
  },
  'dify_inventory.mcp_server_not_found': {
    'zh-CN': '绑定的 MCP Server 不存在，请重新选择',
    'en-US': 'The bound MCP Server does not exist; select another server',
  },
  'dify_inventory.prompt_confirmation_required': {
    'zh-CN': '查看 Prompt 原文前必须再次确认',
    'en-US': 'Viewing raw Prompt text requires explicit confirmation',
  },
  'dify_inventory.prompt_content_unavailable': {
    'zh-CN': '该快照未采集 Prompt 原文',
    'en-US': 'Raw Prompt text was not collected for this snapshot',
  },
  'dify_inventory.credential_active_conflict': {
    'zh-CN': '该用途已有活动凭据，请先禁用或吊销当前凭据',
    'en-US': 'This purpose already has an active credential; disable or revoke it first',
  },
  'dify_inventory.intent_inference_access_denied': {
    'zh-CN': '只有管理员可以启用智能体意图推断',
    'en-US': 'Only administrators can enable agent intent inference',
  },
  'dify_inventory.intent_model_invalid': {
    'zh-CN': '选择的意图推断模型不存在或未启用',
    'en-US': 'The selected intent inference model does not exist or is disabled',
  },
  'dify_inventory.intent_inference_task_invalid': {
    'zh-CN': '只有 Dify 资产清单任务可以推断智能体意图',
    'en-US': 'Only Dify asset inventory tasks can infer agent intent',
  },
  'dify_inventory.intent_inference_not_authorized': {
    'zh-CN': '当前任务未授权智能体意图推断',
    'en-US': 'Agent intent inference was not authorized for this task',
  },
  'dify_inventory.intent_privacy_processing_failed': {
    'zh-CN': '隐私策略处理失败，未调用意图推断模型',
    'en-US': 'Privacy policy processing failed, so the intent model was not called',
  },
}

const interpolate = (value, params = {}, locale = 'zh-CN') =>
  String(value).replace(/\{(\w+)\}/g, (_, key) => {
    const parameter = params[key]
    if (Array.isArray(parameter)) return parameter.join(locale === 'en-US' ? ' or ' : ' 或 ')
    return parameter ?? `{${key}}`
  })

export const localizeApiError = (detail, locale) => {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return detail
  const code = detail.code
  const params = detail.params || {}
  const localMessage = errorMessages[code]?.[locale]
  const serverMessage = detail.messages?.[locale] || detail.message
  return interpolate(localMessage || serverMessage || code || 'Request failed', params, locale)
}

export const getApiErrorCode = detail =>
  detail && typeof detail === 'object' && !Array.isArray(detail) ? detail.code : undefined
