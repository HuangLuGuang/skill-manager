import { formatMcpFieldError } from './mcpServerForm.js'
import { scanScheduleMessages } from './scanSchedule.js'
import { skillAuditReview } from './skill-audit-review.js'
const errorMessages = {
  'mcp.upstream_timeout': {
    'zh-CN': '上游 MCP 调用超时（配置超时：{timeout_seconds} 秒）',
    'en-US': 'Upstream MCP call timed out (configured timeout: {timeout_seconds} seconds)',
  },
  'mcp.upstream_response_too_large': {
    'zh-CN': '上游 MCP 响应超过限制：{max_response_kb} KB',
    'en-US': 'Upstream MCP response exceeds the limit: {max_response_kb} KB',
  },
  'credential.invalid_allowed_ips': { 'zh-CN': '请检查允许来源 IP / CIDR 的格式', 'en-US': 'Check the allowed source IP / CIDR format' },
  'privacy.policy_not_found': { 'zh-CN': '隐私策略不存在，请重新选择。', 'en-US': 'Privacy policy not found. Select another policy.' },
  'privacy.policy_in_use': { 'zh-CN': '隐私策略已绑定凭证，请先更改凭证的策略。', 'en-US': 'Privacy policy is assigned to credentials. Change their policy first.' },
  'privacy.model_access_required': { 'zh-CN': '仅模型调用或代发模型凭证可指定隐私策略。', 'en-US': 'Privacy policies require model access or delegated model credentials.' },
  'aidr.security.invalid_config': { 'zh-CN': '请检查规则字段、路径集合引用及执行前动作的支持范围。', 'en-US': 'Check rule fields, path set references and supported pre-execution actions.' },
  'aidr.security.config_conflict': { 'zh-CN': '安全规则已更新，请重新读取后保存。', 'en-US': 'Security rules changed. Reload before saving.' },
  'aidr.risk.invalid_command_test': { 'zh-CN': '请检查命令（最多32768 UTF-8字节）、工作目录（规范绝对路径，最多512字节）及规则条件。', 'en-US': 'Check the command (up to 32768 UTF-8 bytes), working directory (normalized absolute path, up to 512 bytes) and rule conditions.' },
  'aidr.risk.invalid_range': { 'zh-CN': '时间范围必须带时区，且开始时间不能晚于结束时间。', 'en-US': 'Use timezone-aware times with start no later than end.' },
  'aidr.risk.invalid_config': { 'zh-CN': '请检查检测设置、规则选择和自定义命令条件。自定义路径须为无通配符的规范绝对路径，每类最多32项、每项最多512字节，不可重复。', 'en-US': 'Check detection settings, selected rules and custom command conditions. Custom paths must be unique normalized absolute paths without wildcards: at most 32 per category and 512 UTF-8 bytes per path.' },
  'aidr.risk.config_conflict': { 'zh-CN': '检测配置已更新，请重新读取后保存。', 'en-US': 'Detection settings changed. Reload before saving.' },
  'aidr.risk.admin_required': { 'zh-CN': '需要管理员权限。', 'en-US': 'Administrator role required.' },
  'aidr.risk.not_found': { 'zh-CN': '风险记录不存在或不可访问。', 'en-US': 'Risk record is unavailable.' },
  'aidr.risk.invalid_disposition': { 'zh-CN': '请选择有效状态并填写 1 至 1000 个字符的非空原因。', 'en-US': 'Select a valid status and provide a nonblank reason of 1 to 1000 characters.' },
  'aidr.risk.disposition_conflict': { 'zh-CN': '处置状态已变化或与目标相同，请重新读取后选择。草稿已保留。', 'en-US': 'Disposition changed or already matches the target. Reload before selecting; your draft is preserved.' },
  'model_provider.invalid_auth_type': { 'zh-CN': '认证方式无效', 'en-US': 'Invalid authentication type' },
  'model_provider.invalid_headers': { 'zh-CN': '请提供最多 32 项 Header 的列表', 'en-US': 'Provide a list of up to 32 headers' },
  'model_provider.invalid_header': { 'zh-CN': '第 {index} 项 Header 无效，请检查名称、重复项、保留头及值', 'en-US': 'Header {index} is invalid; check name, duplicates, reserved headers and value' },
  'model_provider.headers_unreadable': { 'zh-CN': '供应商 Header 无法解密，请重新配置', 'en-US': 'Provider headers cannot be decrypted; configure them again' },
  'client.desktop_menu_invalid': { 'zh-CN': '菜单配置必须使用支持的菜单标识和布尔值', 'en-US': 'Menu configuration requires supported menu IDs and boolean values' },
  'credential.scopes_required': { 'zh-CN': '请至少保留一项权限；停止使用请吊销凭证', 'en-US': 'Keep at least one permission; revoke the credential to stop using it' },
  'credential.revoked': { 'zh-CN': '凭证已吊销，请创建新凭证', 'en-US': 'This credential is revoked; create a new one' },
  "license.invalid": {"zh-CN": "授权文件格式或签名无效", "en-US": "Invalid license format or signature"},
  "license.untrusted_key": {"zh-CN": "签发公钥不受信任，请联系管理员配置", "en-US": "The issuing key is not trusted; contact your administrator"},
  "license.deployment_mismatch": {"zh-CN": "授权与当前部署不匹配", "en-US": "The license belongs to a different deployment"},
  "license.customer_mismatch": {"zh-CN": "授权客户与本部署申请不匹配", "en-US": "The license customer does not match this deployment"},
  "license.rollback": {"zh-CN": "授权修订号低于已接收版本", "en-US": "The license revision is older than an accepted revision"},
  "license.revision_conflict": {"zh-CN": "相同修订号对应不同授权文件", "en-US": "The revision is already associated with a different license"},
  "license.expired_import": {"zh-CN": "不能导入已到期的授权", "en-US": "An expired license cannot be imported"},
  "license.missing": {"zh-CN": "请先导入有效 License", "en-US": "Import a valid license first"},
  "license.expired": {"zh-CN": "授权已到期，保留查看、导出及既有网关与防护", "en-US": "License expired; viewing, exports and existing gateways/protection remain available"},
  "license.future": {"zh-CN": "授权尚未生效", "en-US": "The license is not yet effective"},
  "license.clock_rollback": {"zh-CN": "检测到系统时间回拨，请校准服务器时间", "en-US": "Clock rollback detected; correct the server clock"},
  "license.feature_denied": {"zh-CN": "授权未包含此功能模块", "en-US": "This module is not included in the license"},
  "license.client_limit": {"zh-CN": "已达到注册客户端上限", "en-US": "The registered client limit has been reached"},
  "license.identity_locked": {"zh-CN": "已导入授权的客户标识不可修改", "en-US": "The customer identity is locked after importing a license"},
  "license.unavailable": {"zh-CN": "授权状态存储不可用", "en-US": "License state storage is unavailable"},
  "license.scan_stopped": {"zh-CN": "授权限制已停止本次扫描", "en-US": "This scan was stopped by the license policy"},
  ...Object.fromEntries(Object.keys(skillAuditReview['zh-CN'].reasons).map(code => ['aidr.skill_' + code, { 'zh-CN':skillAuditReview['zh-CN'].reasons[code], 'en-US':skillAuditReview['en-US'].reasons[code] }])),
  'aidr.skill_source_unknown': { 'zh-CN':'无法确认来源路径，请同步客户端清单。', 'en-US':'Source path cannot be verified; synchronize client inventory.' },
  'aidr.skill_agent_identity_unknown': { 'zh-CN':'无法确认唯一的本机实例。', 'en-US':'A unique local instance cannot be verified.' },
  'aidr.skill_audit_disabled': { 'zh-CN':'Skill 认证核对已关闭。', 'en-US':'Skill audit is disabled.' },
  'agent.mcp_gateway_unavailable': { 'zh-CN': '请选择已启用的 MCP 网关；已失效的原有选择可保留或移除', 'en-US': 'Select active MCP gateways; existing unavailable selections may be kept or removed' },
  'agent.mcp_scope_exceeded': { 'zh-CN': 'MCP 网关超出智能体允许范围，请先修改智能体的 MCP 工具访问配置', 'en-US': "MCP gateways exceed the Agent's allowed scope. Update the Agent's MCP tool access first" },
  'mcp.connection_failed': { 'zh-CN': 'MCP Server 连接失败: {reason}', 'en-US': 'MCP Server connection failed: {reason}' },
  'mcp.connection_failed.http_status': {
    'zh-CN': "MCP Server 连接失败：HTTP 请求失败 '{status}'，地址 '{url}'。更多信息请参阅：{info_url}",
    'en-US': "MCP Server connection failed: HTTP request failed '{status}' for URL '{url}'. For more information check: {info_url}",
  },
  'mcp.debug_failed': { 'zh-CN': 'MCP 调试失败: {reason}', 'en-US': 'MCP debugging failed: {reason}' },
  'mcp.debug_failed.http_status': {
    'zh-CN': "MCP 调试失败：HTTP 请求失败 '{status}'，地址 '{url}'。更多信息请参阅：{info_url}",
    'en-US': "MCP debugging failed: HTTP request failed '{status}' for URL '{url}'. For more information check: {info_url}",
  },

  'server.internal_error': { 'zh-CN': '服务器内部错误', 'en-US': 'Internal server error' },
  'request.validation_failed': { 'zh-CN': '请求参数无效', 'en-US': 'Invalid request parameters' },
  'http.500': { 'zh-CN': '服务器内部错误', 'en-US': 'Internal server error' },
  'http.403': { 'zh-CN': '权限不足', 'en-US': 'Permission denied' },
  'sandbox.docker_command_unavailable': {
    'zh-CN': '当前 Backend 运行环境未检测到 Docker 命令，无法使用“本地 Docker”运行方式，请改用“远程服务”。',
    'en-US': 'The current Backend environment has no Docker command. Local Docker is unavailable. Use Remote Service.',
  },
  'sandbox.docker_daemon_unavailable': {
    'zh-CN': '当前 Backend 无法连接 Docker 服务，请检查 Docker 服务及连接权限，或改用“远程服务”。',
    'en-US': 'The current Backend cannot connect to Docker. Check the Docker service and connection permissions, or use Remote Service.',
  },
  'sandbox.image_unavailable': {
    'zh-CN': '无法访问运行镜像 {image}，请确认镜像已安装且 Backend 可访问，或改用“远程服务”。',
    'en-US': 'Cannot access runtime image {image}. Check that the image is installed and accessible to the Backend, or use Remote Service.',
  },
  'sandbox.url_required': { 'zh-CN': '请填写远程 Sandbox 服务地址。', 'en-US': 'Enter the remote Sandbox service URL.' },
  'sandbox.url_too_long': { 'zh-CN': '远程 Sandbox 服务地址最多 2048 个字符。', 'en-US': 'The remote Sandbox service URL must not exceed 2048 characters.' },
  'sandbox.url_invalid': { 'zh-CN': '请输入有效的 HTTP/HTTPS 服务地址，不含空白、查询参数或片段。', 'en-US': 'Enter a valid HTTP/HTTPS service URL without whitespace, query parameters, or fragments.' },
  'mcp_scan.gateway_approval_required': { 'zh-CN': 'MCP 网关要求管理员审批本次工具调用，工具尚未执行。请联系管理员到 MCP 网关查看待审批请求及工具授权配置。当前扫描已结束，完成审批不会自动恢复任务。', 'en-US': 'The MCP gateway requires administrator approval for this tool call. The tool has not run. Ask an administrator to review the pending request and tool authorization settings in the MCP gateway. This scan has ended; approval will not automatically resume it.' },
  'mcp_scan.rounds_limit_reached': { 'zh-CN': '扫描轮次额度已用尽或不足以完成下一轮，扫描尚未完成。请提高扫描策略中的“最大轮次”后重试。', 'en-US': 'The scan round budget is exhausted or insufficient for the next round. The scan is incomplete. Increase the maximum rounds in the scan policy and retry.' },
  'mcp_scan.tokens_limit_reached': { 'zh-CN': '已达到最大 Token 用量，扫描尚未完成。请提高扫描策略中的 Token 上限后重试。', 'en-US': 'The token limit has been reached and the scan is incomplete. Increase the token limit in the scan policy and retry.' },
  'mcp_scan.response_bytes_limit_reached': { 'zh-CN': '已达到响应数据量上限，扫描尚未完成。请提高扫描策略中的响应数据量上限后重试。', 'en-US': 'The response size limit has been reached and the scan is incomplete. Increase the response size limit in the scan policy and retry.' },
  'agent_security.retry_status_invalid': { 'zh-CN': '只有失败或超时的扫描任务可以重试。', 'en-US': 'Only failed or timed-out scans can be retried.' },
  'agent_security.output_markers_agent_only': { 'zh-CN': '受保护输出标记仅适用于智能体动态扫描。', 'en-US': 'Protected output markers apply only to Agent dynamic scans.' },
  'mcp_scan.engine_terminated': { 'zh-CN': 'MCP 扫描进程意外退出，未生成完整报告。请联系管理员检查扫描服务的运行环境和资源状态，修复后重新发起扫描。', 'en-US': 'The MCP scan process exited unexpectedly without a complete report. Ask an administrator to check the scan service environment and resources, then start a new scan after the issue is fixed.' },
  'mcp_scan.engine_failed': { 'zh-CN': 'MCP 扫描执行失败，请检查模型连通性和工具调用证据。', 'en-US': 'MCP scan execution failed. Check model connectivity and tool-call evidence.' },
  'mcp_scan.engine_terminated': { 'zh-CN': 'MCP 扫描进程已终止，请检查 Worker 资源和健康状态。', 'en-US': 'The MCP scan process terminated. Check Worker resources and health.' },
  'mcp_scan.execution_denied': { 'zh-CN': 'MCP 执行被租约、权限或预算限制阻止，请检查任务状态和授权范围。', 'en-US': 'MCP execution was denied by lease, permission or budget controls. Check task status and scope.' },
  'mcp_scan.no_successful_tool_calls': { 'zh-CN': '没有成功的 MCP 工具调用，无法形成动态扫描结论。', 'en-US': 'No MCP tool calls succeeded, so no dynamic assessment can be made.' },
  'mcp_scan.review_output_invalid': { 'zh-CN': '评估模型未生成有效的 MCP 复核报告，请调整模型后重试。', 'en-US': 'The evaluator did not produce a valid MCP review. Choose a suitable model and retry.' },
  'mcp_scan.model_empty_response': { 'zh-CN': 'MCP 评估模型返回空内容，请检查模型配置。', 'en-US': 'The MCP evaluator returned empty content. Check model settings.' },
  'mcp_scan.source_hash_mismatch': { 'zh-CN': 'MCP 源码完整性校验失败，请重新导入源码。', 'en-US': 'MCP source integrity verification failed. Import the source again.' },
  'mcp_scan.source_path_invalid': { 'zh-CN': 'MCP 源码包含无效路径，请检查源码包。', 'en-US': 'MCP source contains an invalid path. Check the source bundle.' },
  'mcp_scan.capability_denied': { 'zh-CN': '当前扫描目标或策略未允许这些工具所需的操作。请检查网络访问、工具读取和工具写入权限；只读策略只能选择只读工具。', 'en-US': 'The scan target or policy does not permit the operations these tools need. Check network access, tool read and tool write permissions. Read-only policies only allow read-only tools.' },
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
  if (detail.code === 'mcp.server.invalid_fields' && Array.isArray(detail.params?.errors)) {
    return detail.params.errors.map(issue => formatMcpFieldError(issue, locale)).join('; ')
  }
  const code = detail.code
  const params = detail.params || {}
  const localMessage = errorMessages[code]?.[locale]
  const serverMessage = detail.messages?.[locale] || detail.message
  return interpolate(localMessage || serverMessage || code || 'Request failed', params, locale)
}

export const getApiErrorCode = detail =>
  detail && typeof detail === 'object' && !Array.isArray(detail) ? detail.code : undefined
