from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserBase(BaseModel):
    username: str
    email: Optional[EmailStr] = None


class UserCreate(UserBase):
    password: str
    role: str = "admin"
    group_ids: list[int] = []

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("密码长度至少8位")
        return value


class User(UserBase):
    id: int
    is_active: bool
    role: str
    preferred_locale: Optional[str] = None
    group_ids: list[int] = []
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class LocalePreferenceUpdate(BaseModel):
    locale: str

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        if value not in {"zh-CN", "en-US"}:
            raise ValueError("locale must be zh-CN or en-US")
        return value


class LoginLog(BaseModel):
    id: int
    username: str
    ip_address: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class OperationLog(BaseModel):
    id: int
    username: str
    action: str
    target: str
    details: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class LogParseConfigUpdate(BaseModel):
    tenant: str = "default"
    normalize_fields: list[str] = []
    header_fields: list[str] = []
    body_fields: list[str] = []
    computed_fields: list[str] = []
    fields: list[str] = []
    phone_no_field: list[str] = []
    phone_no_field_pos: str = "body"
    static_resource_extensions: list[str] = []
    botgate_log_prefix: str = "botgate_access.log-"


class ModelConfigUpdate(BaseModel):
    uid_parse_error_filter: bool = False
    timestamp_format: str = "dd/MMM/yyyy:HH:mm:ss Z"
    rate_sess_min_req_count: int = 50
    rate_sess_gap: int = 60
    contamination: float = 0
    num_estimators: int = 100
    max_samples: int = 256
    outlier_score: float = 0.65
    micro_sess_gap: int = 5
    micro_sess_max_unq_api_count: int = 20
    sess_api_sim_thresh: float = 0.5
    group_sess_min_count: int = 30
    freq_count: int = 20
    data_sample: float = 0.9
    data_count: int = 30000
    time_series_window_size: int = 600
    window_count: int = 5
    cluster_K: int = 20
    eps: float = 0.1
    min_samples: int = 10
    ts_cluster_group_cnt_thresh: int = 9


class DocsAssistantFaq(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    question_zh: str = Field(min_length=1, max_length=200)
    question_en: str = Field(min_length=1, max_length=200)


class DocsAssistantConfigUpdate(BaseModel):
    enabled: bool = False
    model: Optional[str] = Field(default=None, max_length=128)
    welcome_zh: str = Field(default="你好，我可以根据当前帮助文档帮你定位功能和操作步骤。", max_length=300)
    welcome_en: str = Field(default="Hi, I can help you find features and steps in the current documentation.", max_length=300)
    instruction_zh: str = Field(default="回答简洁、务实，优先给出可执行步骤；文档没有说明时请明确告知。", max_length=1000)
    instruction_en: str = Field(default="Be concise and practical. Prefer actionable steps and say clearly when the docs do not establish an answer.", max_length=1000)
    max_context_sections: int = Field(default=4, ge=2, le=6)
    common_questions: list[DocsAssistantFaq] = Field(default_factory=list, max_length=8)

    @field_validator("model")
    @classmethod
    def normalize_docs_model(cls, value: Optional[str]) -> Optional[str]:
        normalized = (value or "").strip()
        return normalized or None


class DocsAssistantContext(BaseModel):
    slug: str = Field(max_length=160)
    article_title: str = Field(min_length=1, max_length=200)
    section_title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)


class DocsAssistantHistoryMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class DocsAssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    locale: str = Field(default="zh-CN", pattern="^(zh-CN|en-US)$")
    contexts: list[DocsAssistantContext] = Field(min_length=1, max_length=6)
    history: list[DocsAssistantHistoryMessage] = Field(default_factory=list, max_length=6)


class DocsAssistantAnswer(BaseModel):
    answer: str
    model: str


class ScheduledTaskBase(BaseModel):
    display_name: str
    description: Optional[str] = None
    task_type: str = "function"
    cron_expr: Optional[str] = None
    enabled: bool = True


class ScheduledTaskCreate(ScheduledTaskBase):
    name: str
    task_func: Optional[str] = None
    command: Optional[str] = None


class ScheduledTaskUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[str] = None
    task_func: Optional[str] = None
    command: Optional[str] = None
    cron_expr: Optional[str] = None
    enabled: Optional[bool] = None


class ScheduledTaskResponse(ScheduledTaskBase):
    id: int
    name: str
    task_func: Optional[str] = None
    command: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    latest_execution_status: Optional[str] = None


class TaskExecutionResponse(BaseModel):
    id: int
    task_id: int
    task_name: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    logs: Optional[str] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class ExecutionLogsResponse(BaseModel):
    logs: str
    total_lines: int
    has_more: bool


class StatsBackfillRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    business_name: Optional[str] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    group_ids: Optional[list[int]] = None


class UserGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    user_ids: list[int] = []
    privacy_policy_id: Optional[int] = None


class UserGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    user_ids: Optional[list[int]] = None
    privacy_policy_id: Optional[int] = None


class UserGroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    user_ids: list[int] = []
    privacy_policy_id: Optional[int] = None
    privacy_policy_name: Optional[str] = None
    created_at: datetime


class ManagedAgentCreate(BaseModel):
    agent_id: str
    name: str
    department_group_id: Optional[int] = None
    owner: Optional[str] = None
    description: Optional[str] = None
    channel: Optional[str] = None
    status: str = "active"
    default_model: Optional[str] = None
    skill_names: list[str] = []
    prompt_names: list[str] = []


class ManagedAgentUpdate(BaseModel):
    agent_id: Optional[str] = None
    name: Optional[str] = None
    department_group_id: Optional[int] = None
    owner: Optional[str] = None
    description: Optional[str] = None
    channel: Optional[str] = None
    status: Optional[str] = None
    default_model: Optional[str] = None
    skill_names: Optional[list[str]] = None
    prompt_names: Optional[list[str]] = None


class ManagedAgentResponse(BaseModel):
    id: int
    agent_id: str
    name: str
    department_group_id: Optional[int] = None
    department_name: Optional[str] = None
    owner: Optional[str] = None
    description: Optional[str] = None
    channel: Optional[str] = None
    status: str
    default_model: Optional[str] = None
    skill_names: list[str] = []
    prompt_names: list[str] = []
    runtime_token_id: Optional[int] = None
    runtime_token_name: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AccessTokenCreate(BaseModel):
    name: str
    token_type: str = Field(pattern="^(model_gateway|agent_runtime|scanner|client|mcp_gateway)$")
    bound_agent_id: Optional[str] = None
    bound_client_id: Optional[str] = None
    allow_agent_credential_issuance: bool = False
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    scopes: list[str] = []
    allowed_models: list[str] = []
    allowed_mcp_gateways: list[str] = []
    allowed_ips: list[str] = []
    expires_at: Optional[datetime] = None
    max_body_kb: int = Field(default=1024, ge=1, le=10240)
    max_concurrent_requests: int = Field(default=5, ge=1, le=100)
    max_upload_mb: int = Field(default=50, ge=1, le=10240)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=100)
    enable_compression: bool = False
    compression_level: str = Field(default="auto", pattern="^(auto|conservative|aggressive)$")
    prompt_guard_mode: str = Field(default="off", pattern="^(off|log|warn|block)$")
    prompt_guard_llm_review: bool = False


class AccessTokenUpdate(BaseModel):
    name: Optional[str] = None
    bound_agent_id: Optional[str] = None
    bound_client_id: Optional[str] = None
    allow_agent_credential_issuance: Optional[bool] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    scopes: Optional[list[str]] = None
    allowed_models: Optional[list[str]] = None
    allowed_mcp_gateways: Optional[list[str]] = None
    allowed_ips: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern="^(active|disabled|revoked)$")
    expires_at: Optional[datetime] = None
    max_body_kb: Optional[int] = Field(default=None, ge=1, le=10240)
    max_concurrent_requests: Optional[int] = Field(default=None, ge=1, le=100)
    max_upload_mb: Optional[int] = Field(default=None, ge=1, le=10240)
    max_concurrent_jobs: Optional[int] = Field(default=None, ge=1, le=100)
    enable_compression: Optional[bool] = None
    compression_level: Optional[str] = Field(default=None, pattern="^(auto|conservative|aggressive)$")
    prompt_guard_mode: Optional[str] = Field(default=None, pattern="^(off|log|warn|block)$")
    prompt_guard_llm_review: Optional[bool] = None


class AccessTokenResponse(BaseModel):
    id: int
    name: str
    token_type: str
    token_prefix: str
    token: Optional[str] = None
    token_hash: Optional[str] = None
    bound_agent_id: Optional[str] = None
    bound_client_id: Optional[str] = None
    allow_agent_credential_issuance: bool = False
    issued_by_client_token_id: Optional[int] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    scopes: list[str] = []
    allowed_models: list[str] = []
    allowed_mcp_gateways: list[str] = []
    allowed_ips: list[str] = []
    status: str
    expires_at: Optional[datetime] = None
    max_body_kb: int
    max_concurrent_requests: int
    max_upload_mb: int
    max_concurrent_jobs: int
    enable_compression: bool = False
    compression_level: str = "auto"
    prompt_guard_mode: str = "off"
    prompt_guard_llm_review: bool = False
    created_by: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None


class AccessTokenCreateResponse(BaseModel):
    token: str
    record: AccessTokenResponse


class AccessTokenListResponse(BaseModel):
    items: list[AccessTokenResponse]


class McpServerCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,127}$")
    name: str
    description: Optional[str] = None
    endpoint: str
    authorization_header: str = "Authorization"
    authorization_value: Optional[str] = None
    status: str = Field(default="draft", pattern="^(draft|active|disabled)$")
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_response_kb: int = Field(default=1024, ge=1, le=10240)


class McpServerUpdate(BaseModel):
    slug: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,127}$")
    name: Optional[str] = None
    description: Optional[str] = None
    endpoint: Optional[str] = None
    authorization_header: Optional[str] = None
    authorization_value: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|active|disabled)$")
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=300)
    max_response_kb: Optional[int] = Field(default=None, ge=1, le=10240)


class McpToolResponse(BaseModel):
    id: int
    server_id: int
    name: str
    exposed_name: str
    description: Optional[str] = None
    input_schema: dict[str, Any] = {}
    schema_hash: str
    enabled: bool
    risk_level: str = "low"
    rate_limit_per_minute: int = 60
    max_concurrent: int = 5
    requires_approval: bool = False
    discovered_at: datetime


class McpServerResponse(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    endpoint: str
    authorization_header: str
    authorization_masked: Optional[str] = None
    status: str
    health_status: str
    timeout_seconds: int
    max_response_kb: int
    last_checked_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tools: list[McpToolResponse] = []


class McpGatewayBindingInput(BaseModel):
    server_id: int
    allowed_tools: list[str] = []


class McpGatewayCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,127}$")
    name: str
    description: Optional[str] = None
    status: str = Field(default="active", pattern="^(active|disabled)$")
    bindings: list[McpGatewayBindingInput] = []


class McpGatewayUpdate(BaseModel):
    slug: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,127}$")
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|disabled)$")
    bindings: Optional[list[McpGatewayBindingInput]] = None


class McpGatewayBindingResponse(BaseModel):
    server_id: int
    server_slug: str
    server_name: str
    allowed_tools: list[str] = []
    approved_schema_hashes: dict[str, str] = {}


class McpGatewayResponse(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    status: str
    bindings: list[McpGatewayBindingResponse] = []
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class McpCallAuditResponse(BaseModel):
    id: int
    request_id: str
    token_id: int
    gateway_slug: str
    server_slug: Optional[str] = None
    tool_name: Optional[str] = None
    schema_hash: Optional[str] = None
    approval_request_id: Optional[str] = None
    status: str
    duration_ms: float
    error: Optional[str] = None
    created_at: datetime


class McpUpstreamDebugRequest(BaseModel):
    server_id: Optional[int] = None
    endpoint: Optional[str] = None
    authorization_header: Optional[str] = None
    authorization_value: Optional[str] = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    method: str = Field(pattern="^(ping|tools/list|tools/call)$")
    params: dict[str, Any] = {}


class McpToolPolicyUpdate(BaseModel):
    risk_level: str = Field(pattern="^(low|medium|high)$")
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)
    max_concurrent: int = Field(default=5, ge=1, le=100)
    requires_approval: bool = False


class McpToolApprovalCreate(BaseModel):
    token_id: int
    gateway_slug: str
    tool_name: str
    arguments: dict[str, Any] = {}
    ttl_seconds: int = Field(default=300, ge=10, le=600)


class McpToolApprovalResponse(BaseModel):
    approval_token: str
    expires_at: datetime


class McpApprovalRequestReview(BaseModel):
    ttl_seconds: int = Field(default=300, ge=60, le=600)
    comment: Optional[str] = Field(default=None, max_length=1000)


class McpApprovalRequestReject(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class McpApprovalRequestResponse(BaseModel):
    request_id: str
    token_id: int
    token_name: str
    token_prefix: str
    gateway_slug: str
    gateway_name: Optional[str] = None
    server_slug: Optional[str] = None
    tool_id: Optional[int] = None
    tool_name: str
    tool_description: Optional[str] = None
    risk_level: str = "high"
    schema_hash: Optional[str] = None
    current_schema_hash: Optional[str] = None
    schema_changed: bool = False
    arguments: dict[str, Any] = {}
    arguments_revealed: bool = False
    client_ip: Optional[str] = None
    status: str
    expires_at: datetime
    created_by: str
    created_at: datetime
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    used_at: Optional[datetime] = None
    use_count: int = 0
    first_used_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class McpApprovalRequestListResponse(BaseModel):
    items: list[McpApprovalRequestResponse]
    total: int
    page: int
    page_size: int


class McpApprovalRequestStatsResponse(BaseModel):
    pending: int = 0
    approved_today: int = 0
    rejected_today: int = 0
    expired: int = 0


class McpApprovalRuntimeStatusResponse(BaseModel):
    request_id: str
    status: str
    expires_at: datetime
    review_comment: Optional[str] = None


class RuntimePolicyUpdate(BaseModel):
    max_steps: int = Field(default=50, ge=1, le=10000)
    max_retries: int = Field(default=3, ge=0, le=100)
    max_delegation_depth: int = Field(default=2, ge=0, le=32)
    max_cost_microunits: int = Field(default=1_000_000, ge=0)
    max_data_bytes: int = Field(default=10 * 1024 * 1024, ge=0)
    max_duration_seconds: int = Field(default=1800, ge=1, le=604800)
    circuit_failure_threshold: int = Field(default=5, ge=1, le=1000)
    circuit_cooldown_seconds: int = Field(default=300, ge=1, le=86400)
    goal_drift_threshold: float = Field(default=0.85, ge=0, le=1)


class RuntimeTaskStart(BaseModel):
    agent_id: str
    tenant_id: str
    user_id: str
    session_id: str
    original_goal: str = Field(min_length=1, max_length=20000)
    allowed_actions: list[str] = []
    allowed_targets: list[str] = []
    preview: bool = False


class RuntimeActionAuthorize(BaseModel):
    parent_action_id: Optional[str] = None
    stage: str = Field(default="executor", pattern="^(planner|executor)$")
    action_type: str
    target: str
    resource: Optional[str] = None
    risk_level: str = Field(default="low", pattern="^(low|medium|high)$")
    plan_step: str = Field(min_length=1, max_length=20000)
    parameters: dict[str, Any] = {}
    expected_side_effects: list[str] = []
    approval_context: dict[str, Any] = {}
    retry_count: int = Field(default=0, ge=0)
    delegation_depth: int = Field(default=0, ge=0)
    estimated_cost_microunits: int = Field(default=0, ge=0)
    estimated_data_bytes: int = Field(default=0, ge=0)
    network_access: bool = False
    state_change: bool = False


class RuntimeActionConsume(BaseModel):
    authorization_token: str
    parameters: dict[str, Any] = {}


class RuntimeApprovalCreate(BaseModel):
    task_id: str
    action_type: str
    target: str
    parameters: dict[str, Any] = {}
    ttl_seconds: int = Field(default=300, ge=10, le=3600)


class RuntimeActionResult(BaseModel):
    status: str = Field(pattern="^(succeeded|failed|cancelled)$")
    result: dict[str, Any] = {}
    actual_data_bytes: int = Field(default=0, ge=0)
    actual_cost_microunits: int = Field(default=0, ge=0)
    error: Optional[str] = None


class RuntimeTaskComplete(BaseModel):
    status: str = Field(default="completed", pattern="^(completed|failed|cancelled)$")
    reason: Optional[str] = None


class RuntimeKillSwitchCreate(BaseModel):
    scope_type: str = Field(pattern="^(global|tenant|user|agent|tool)$")
    scope_id: str = "*"
    reason: str = Field(min_length=1, max_length=2000)


class RuntimeMemoryIngest(BaseModel):
    memory_id: Optional[str] = None
    agent_id: str
    tenant_id: str
    user_id: str
    session_id: str
    source_type: str = Field(pattern="^(user|tool|rag|file|web|model_output)$")
    source_ref: Optional[str] = None
    content: str = Field(min_length=1, max_length=1_000_000)
    provenance: dict[str, Any] = {}
    expires_at: Optional[datetime] = None
    preview: bool = False


class RuntimeMemoryReview(BaseModel):
    trust_status: str = Field(pattern="^(trusted|untrusted|quarantined)$")
    reason: Optional[str] = None


class RuntimeMemoryRollback(BaseModel):
    version: int = Field(ge=1)


class ClientSkillInventory(BaseModel):
    skill_id: Optional[str] = None
    version_id: Optional[str] = None
    version_no: Optional[int] = None
    source_version: Optional[str] = None
    name: str
    path: str
    signature: Optional[str] = None
    status: str = "observed"
    install_mode: str = "observed"


class ClientAgentInventory(BaseModel):
    local_agent_id: Optional[str] = None
    agent_type: str
    version: Optional[str] = None
    install_path: Optional[str] = None
    skills_path: Optional[str] = None
    skill_management_supported: bool = True
    capabilities: dict[str, Any] = {}
    managed_agent_id: Optional[str] = None
    skills: list[ClientSkillInventory] = []


class ClientRegisterRequest(BaseModel):
    client_id: str
    name: str
    hostname: str
    os: str
    arch: str
    client_version: str
    agents: list[ClientAgentInventory] = []


class ClientHeartbeatRequest(BaseModel):
    client_id: str
    client_version: Optional[str] = None


class ClientPolicyUpdate(BaseModel):
    mode: Optional[str] = Field(default=None, pattern="^(audit|repair|block)$")
    governance_mode: Optional[str] = Field(default=None, pattern="^(registry|strict)$")


class ClientAgentBindingUpdate(BaseModel):
    managed_agent_id: Optional[str] = None


class ClientInventoryRequest(BaseModel):
    agents: list[ClientAgentInventory] = []


class ClientEventCreate(BaseModel):
    event_type: str
    agent_type: Optional[str] = None
    skill_name: Optional[str] = None
    details: dict[str, Any] = {}


class ClientTaskCreate(BaseModel):
    task_type: str = Field(pattern="^(install_skill|remove_skill|rescan|repair_skill|apply_model_config)$")
    payload: dict[str, Any] = {}


class ClientTaskResult(BaseModel):
    status: str = Field(pattern="^(running|succeeded|failed|cancelled)$")
    error: Optional[str] = None


class ClientAgentCredentialResponse(BaseModel):
    token: str
    token_prefix: str
    bound_agent_id: str
    allowed_models: list[str] = []
    allowed_mcp_gateways: list[str] = []


class ClientSkillCompareItem(BaseModel):
    skill_id: Optional[str] = None
    version_id: Optional[str] = None
    name: str
    path: Optional[str] = None
    signature: Optional[str] = None


class ClientAgentCompare(BaseModel):
    agent_type: str
    managed_agent_id: Optional[str] = None
    skills: list[ClientSkillCompareItem] = []


class ClientCompareRequest(BaseModel):
    agents: list[ClientAgentCompare] = []


class ClientTakeoverReport(BaseModel):
    backup: str
    managed_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)



class ModelProviderCreate(BaseModel):
    name: str
    base_url: str
    api_format: str = Field(default="openai", pattern="^(openai|anthropic)$")
    api_key: Optional[str] = None
    enabled: bool = True
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    enable_compression: bool = False


class ModelProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_format: Optional[str] = Field(default=None, pattern="^(openai|anthropic)$")
    api_key: Optional[str] = None
    clear_api_key: bool = False
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=600)
    enable_compression: Optional[bool] = None


class ModelProviderResponse(BaseModel):
    id: int
    name: str
    base_url: str
    api_format: str = "openai"
    enabled: bool
    timeout_seconds: int
    api_key_configured: bool
    api_key_masked: Optional[str] = None
    enable_compression: bool = False
    created_at: datetime
    updated_at: datetime


class ModelEndpointCreate(BaseModel):
    provider_id: int
    name: str
    display_name: Optional[str] = None
    enabled: bool = True
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    is_default: bool = False


class ModelEndpointUpdate(BaseModel):
    provider_id: Optional[int] = None
    name: Optional[str] = None
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    is_default: Optional[bool] = None


class ModelEndpointResponse(BaseModel):
    id: int
    provider_id: int
    provider_name: Optional[str] = None
    name: str
    display_name: Optional[str] = None
    enabled: bool
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class LlmApiKeyCreate(BaseModel):
    name: str
    allowed_models: list[str] = []
    expires_at: Optional[datetime] = None
    max_body_kb: int = Field(default=1024, ge=1, le=10240)
    max_concurrent_requests: int = Field(default=5, ge=1, le=100)
    enable_compression: bool = False
    compression_level: str = Field(default="auto", pattern="^(auto|conservative|aggressive)$")
    prompt_guard_mode: str = Field(default="off", pattern="^(off|log|warn|block)$")
    prompt_guard_llm_review: bool = False


class LlmApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    allowed_models: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern="^(active|disabled|revoked)$")
    expires_at: Optional[datetime] = None
    max_body_kb: Optional[int] = Field(default=None, ge=1, le=10240)
    max_concurrent_requests: Optional[int] = Field(default=None, ge=1, le=100)
    enable_compression: Optional[bool] = None
    compression_level: Optional[str] = Field(default=None, pattern="^(auto|conservative|aggressive)$")
    prompt_guard_mode: Optional[str] = Field(default=None, pattern="^(off|log|warn|block)$")
    prompt_guard_llm_review: Optional[bool] = None


class LlmApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    token: Optional[str] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    allowed_models: list[str] = []
    status: str
    expires_at: Optional[datetime] = None
    max_body_kb: int
    max_concurrent_requests: int
    enable_compression: bool = False
    compression_level: str = "auto"
    prompt_guard_mode: str = "off"
    prompt_guard_llm_review: bool = False
    created_at: datetime
    last_used_at: Optional[datetime] = None


class ModelSkillAlertItem(BaseModel):
    id: int
    request_id: str
    created_at: datetime
    severity: Optional[str] = None
    trust_state: Optional[str] = None
    alert_codes: list[str] = Field(default_factory=list)
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    skill_id: Optional[str] = None
    skill_version_id: Optional[str] = None
    skill_name: Optional[str] = None
    context_source: Optional[str] = None
    model: str
    credential_type: Optional[str] = None
    credential_name: Optional[str] = None
    request_status: str


class ModelSkillAlertSummary(BaseModel):
    actionable: int = 0
    missing: int = 0
    observations: int = 0
    affected_agents: int = 0


class ModelSkillAlertListResponse(BaseModel):
    items: list[ModelSkillAlertItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    days: int
    summary: ModelSkillAlertSummary


class PrivacyPolicyPayload(BaseModel):
    id: Optional[int] = None
    name: str = "默认隐私策略"
    enabled: bool = True
    group_id: Optional[int] = None
    entity_types: list[str] = []
    entity_rules: dict[str, str] = Field(default_factory=dict)
    detect_system_messages: bool = False
    allow_bypass: bool = False
    mapping_ttl_days: int = Field(default=7, ge=1, le=365)
    dp_enabled: bool = True
    dp_epsilon: float = Field(default=1.0, gt=0)
    dp_min_count: int = Field(default=5, ge=1)


class PrivacyPolicyResponse(PrivacyPolicyPayload):
    id: int
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class ChatMessage(BaseModel):
    model_config = {"extra": "allow"}

    role: str
    content: Any = ""


class ChatCompletionRequest(BaseModel):
    model_config = {"extra": "forbid", "populate_by_name": True}

    model: Optional[str] = None
    messages: list[ChatMessage]
    stream: bool = False
    conversation_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    stop: Optional[Any] = None
    n: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[dict[str, Any]] = None
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[Any] = None
    response_format: Optional[dict[str, Any]] = None
    stream_options: Optional[dict[str, Any]] = None
    seed: Optional[int] = None
    user: Optional[str] = None
    reasoning_effort: Optional[str] = None
    service_tier: Optional[str] = Field(default=None, alias="serviceTier")
    verbosity: Optional[str] = None
    anthropic_options: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator(
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "stop",
        "n",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "tools",
        "tool_choice",
        "response_format",
        "stream_options",
        "seed",
        "user",
        "reasoning_effort",
        "service_tier",
        "verbosity",
        mode="before",
    )
    @classmethod
    def normalize_undefined(cls, value: Any) -> Any:
        if isinstance(value, str) and value in {"[undefined]", "undefined", ""}:
            return None
        return value

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if not value:
            raise ValueError("messages must not be empty")
        return value


class AnthropicMessage(BaseModel):
    model_config = {"extra": "forbid"}

    role: str = Field(pattern="^(system|user|assistant)$")
    content: Any


class AnthropicMessagesRequest(BaseModel):
    model_config = {"extra": "forbid"}

    model: str
    messages: list[AnthropicMessage]
    max_tokens: int = Field(gt=0)
    system: Optional[Any] = None
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    thinking: Optional[dict[str, Any]] = None
    service_tier: Optional[str] = None
    context_management: Optional[dict[str, Any]] = None
    output_config: Optional[dict[str, Any]] = None

    @field_validator("messages")
    @classmethod
    def validate_anthropic_messages(cls, value: list[AnthropicMessage]) -> list[AnthropicMessage]:
        if not value:
            raise ValueError("messages must not be empty")
        return value


class PromptGuardTestRequest(BaseModel):
    mode: str = Field(default="log", pattern="^(off|log|warn|block)$")
    messages: list[ChatMessage]
    llm_review: bool = False

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if not value:
            raise ValueError("messages must not be empty")
        return value
