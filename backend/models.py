from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func

from .asset_lifecycle_models import (  # noqa: F401
    AgentAssetLink,
    AgentRiskAssessment,
    AgentRiskIssue,
    AgentScanBinding,
    AssetLifecycleEvent,
    AssetSource,
    AssetSyncRun,
    AssetSyncRunItem,
    SecurityAgentAsset,
)
from .scan_schedule_models import (  # noqa: F401
    SecurityScanSchedule,
    SecurityScanScheduleRun,
    SecurityTaskRiskScore,
    SecurityTaskTrigger,
)
from .sqlite_db import Base
from .external_access_models import ExternalPlatform, ExternalApiRequest  # noqa: F401
from .dify_runtime_models import DifyRuntimeBinding, DifyRuntimeRun, DifyRuntimeCall, DifyRuntimeProcess, DifyRuntimeSkill  # noqa: F401
from .aidr_models import AidrPolicyReceipt, AidrDevice, AidrBatch, AidrEvent, AidrSource, AidrCoverageRecord, AidrLegacyDestination, AidrOperation, AidrAuditState  # noqa: F401
from .aidr_enforcement import AidrEnforcementRevision, AidrRuntimeRecord, AidrResponseCommand  # noqa: F401
from .iam_models import ManagementAudit, Menu, Permission, Role, RolePermission  # noqa: F401


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    role = Column(String(32), default="admin", nullable=False)
    preferred_locale = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    current_session_id = Column(String(64), nullable=True)


class UserGroup(Base):
    __tablename__ = "user_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserGroupMember(Base):
    __tablename__ = "user_group_members"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ManagedAgent(Base):
    __tablename__ = "managed_agents"
    __table_args__ = (Index("uq_managed_agent_external_identity", "source_platform_id", "external_agent_id", unique=True),)
    registration_source = Column(String(32), index=True, nullable=True)
    source_platform_id = Column(String(64), index=True, nullable=True)
    external_agent_id = Column(String(128), index=True, nullable=True)
    source_token_id = Column(Integer, nullable=True)
    source_request_id = Column(String(64), nullable=True)

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(128), index=True, nullable=False)
    department_group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    owner = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    channel = Column(String(64), nullable=True)
    status = Column(String(32), default="active", nullable=False)
    default_model = Column(String(128), nullable=True)
    default_model_source = Column(String(32), default="internal", nullable=False)
    external_gateway_id = Column(Integer, ForeignKey("external_ai_gateways.id"), index=True, nullable=True)
    origin_type = Column(String(32), default="platform", index=True, nullable=False)
    skill_names_json = Column(Text, default="[]", nullable=False)
    allowed_mcp_gateways_json = Column(Text, default="[]", nullable=False)
    prompt_names_json = Column(Text, default="[]", nullable=False)
    runtime_token_id = Column(Integer, ForeignKey("access_tokens.id"), nullable=True)
    runtime_token_name = Column(String(128), nullable=True)
    created_by = Column(String(128), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ModelProvider(Base):
    __tablename__ = "model_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    base_url = Column(String(512), nullable=False)
    api_format = Column(String(32), default="openai", nullable=False)
    api_key = Column(Text, nullable=True)
    auth_type = Column(String(16), default="bearer", server_default="bearer", nullable=False)
    custom_headers_encrypted = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    timeout_seconds = Column(Integer, default=180, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("model_providers.id"), index=True, nullable=False)
    name = Column(String(128), unique=True, index=True, nullable=False)
    upstream_name = Column(String(128), nullable=True)
    __table_args__ = (Index("uq_model_provider_upstream", provider_id, func.coalesce(upstream_name, name), unique=True),)
    display_name = Column(String(128), nullable=True)
    supports_multimodal = Column(Boolean, default=False, server_default="0", nullable=False)
    guard_adapter = Column(String(16), default="generic", server_default="generic", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    context_window = Column(Integer, nullable=True)
    max_output_tokens = Column(Integer, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LlmApiKey(Base):
    prompt_guard_business_scope = Column(Text, default="", server_default="", nullable=False)
    __tablename__ = "llm_api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), index=True, nullable=False)
    key_hash = Column(String(128), unique=True, index=True, nullable=False)
    key_prefix = Column(String(16), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    allowed_models_json = Column(Text, default="[]", nullable=False)
    status = Column(String(32), default="active", nullable=False)
    expires_at = Column(DateTime, nullable=True)
    max_body_kb = Column(Integer, default=1024, nullable=False)
    max_concurrent_requests = Column(Integer, default=5, nullable=False)
    # Headroom 智能压缩配置
    enable_compression = Column(Boolean, default=False, nullable=False)
    compression_level = Column(String(32), default="auto", nullable=False)
    prompt_guard_mode = Column(String(32), default="log", nullable=False)
    prompt_guard_llm_review = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)


class AccessToken(Base):
    prompt_guard_business_scope = Column(Text, default="", server_default="", nullable=False)
    __tablename__ = "access_tokens"
    __table_args__ = {"sqlite_autoincrement": True}
    platform_id = Column(String(64), index=True, nullable=True)
    privacy_policy_id = Column(Integer, ForeignKey("privacy_policies.id"), nullable=True)
    allowed_department_ids_json = Column(Text, default="[]", nullable=False)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), index=True, nullable=False)
    token_type = Column(String(32), index=True, nullable=False)
    token_hash = Column(String(128), unique=True, index=True, nullable=False)
    token_prefix = Column(String(24), index=True, nullable=False)
    scopes_json = Column(Text, default="[]", nullable=False)
    bound_agent_id = Column(String(128), index=True, nullable=True)
    bound_client_id = Column(String(128), index=True, nullable=True)
    allow_agent_credential_issuance = Column(Boolean, default=False, nullable=False)
    allow_manual_credential_export = Column(Boolean, default=False, nullable=False)
    issued_by_client_token_id = Column(Integer, index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    allowed_models_json = Column(Text, default="[]", nullable=False)
    allowed_mcp_gateways_json = Column(Text, default="[]", nullable=False)
    allowed_ips_json = Column(Text, default="[]", nullable=False)
    status = Column(String(32), default="active", nullable=False)
    expires_at = Column(DateTime, nullable=True)
    max_body_kb = Column(Integer, default=1024, nullable=False)
    max_concurrent_requests = Column(Integer, default=5, nullable=False)
    max_upload_mb = Column(Integer, default=100, nullable=False)
    max_concurrent_jobs = Column(Integer, default=2, nullable=False)
    enable_compression = Column(Boolean, default=False, nullable=False)
    compression_level = Column(String(32), default="auto", nullable=False)
    prompt_guard_mode = Column(String(32), default="log", nullable=False)
    prompt_guard_llm_review = Column(Boolean, default=False, nullable=False)
    created_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(128), nullable=True)


class RequestLease(Base):
    __tablename__ = "request_leases"

    lease_id = Column(String(64), primary_key=True)
    subject_type = Column(String(32), index=True, nullable=False)
    subject_id = Column(String(128), index=True, nullable=False)
    purpose = Column(String(64), index=True, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(64), unique=True, index=True, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)
    event_type = Column(String(64), index=True, nullable=False)
    actor = Column(String(128), index=True, nullable=False)
    resource_type = Column(String(64), index=True, nullable=False)
    resource_id = Column(String(512), nullable=False)
    action = Column(String(16), nullable=False)
    outcome = Column(String(16), nullable=False)
    details_json = Column(Text, default="{}", nullable=False)
    prev_hash = Column(String(64), nullable=False)
    event_hash = Column(String(64), unique=True, nullable=False)
    key_id = Column(String(16), nullable=False)
    signature = Column(Text, nullable=False)


class RuntimePolicy(Base):
    __tablename__ = "runtime_policies"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(128), unique=True, index=True, nullable=False)
    max_steps = Column(Integer, default=50, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    max_delegation_depth = Column(Integer, default=2, nullable=False)
    max_cost_microunits = Column(Integer, default=1_000_000, nullable=False)
    max_data_bytes = Column(Integer, default=10 * 1024 * 1024, nullable=False)
    max_duration_seconds = Column(Integer, default=1800, nullable=False)
    circuit_failure_threshold = Column(Integer, default=5, nullable=False)
    circuit_cooldown_seconds = Column(Integer, default=300, nullable=False)
    goal_drift_threshold = Column(Float, default=0.85, nullable=False)
    created_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RuntimeTask(Base):
    __tablename__ = "runtime_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), unique=True, index=True, nullable=False)
    token_id = Column(Integer, ForeignKey("access_tokens.id"), index=True, nullable=False)
    agent_id = Column(String(128), index=True, nullable=False)
    tenant_id = Column(String(128), index=True, nullable=False)
    user_id = Column(String(128), index=True, nullable=False)
    session_id = Column(String(128), index=True, nullable=False)
    trace_id = Column(String(64), index=True, nullable=True)
    original_goal = Column(Text, nullable=False)
    goal_digest = Column(String(64), nullable=False)
    allowed_actions_json = Column(Text, default="[]", nullable=False)
    allowed_targets_json = Column(Text, default="[]", nullable=False)
    status = Column(String(32), default="active", index=True, nullable=False)
    preview = Column(Boolean, default=False, nullable=False)
    step_count = Column(Integer, default=0, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    max_delegation_seen = Column(Integer, default=0, nullable=False)
    cost_microunits = Column(Integer, default=0, nullable=False)
    data_bytes = Column(Integer, default=0, nullable=False)
    policy_snapshot_json = Column(Text, default="{}", nullable=False)
    stop_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class RuntimeAction(Base):
    __tablename__ = "runtime_actions"

    id = Column(Integer, primary_key=True, index=True)
    action_id = Column(String(64), unique=True, index=True, nullable=False)
    task_id = Column(String(64), ForeignKey("runtime_tasks.task_id"), index=True, nullable=False)
    parent_action_id = Column(String(64), index=True, nullable=True)
    stage = Column(String(16), nullable=False)
    action_type = Column(String(128), index=True, nullable=False)
    target = Column(String(1024), nullable=False)
    resource = Column(String(1024), nullable=True)
    risk_level = Column(String(16), index=True, nullable=False)
    plan_step = Column(Text, nullable=False)
    parameters_hash = Column(String(64), nullable=False)
    parameters_json = Column(Text, default="{}", nullable=False)
    expected_side_effects_json = Column(Text, default="[]", nullable=False)
    estimated_cost_microunits = Column(Integer, default=0, nullable=False)
    estimated_data_bytes = Column(Integer, default=0, nullable=False)
    approval_context_json = Column(Text, default="{}", nullable=False)
    decision = Column(String(16), index=True, nullable=False)
    decision_reasons_json = Column(Text, default="[]", nullable=False)
    drift_score = Column(Float, default=0.0, nullable=False)
    authorization_hash = Column(String(64), unique=True, nullable=True)
    authorization_expires_at = Column(DateTime, nullable=True)
    authorization_used_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="planned", index=True, nullable=False)
    result_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class RuntimeApproval(Base):
    __tablename__ = "runtime_approvals"

    id = Column(Integer, primary_key=True, index=True)
    approval_id = Column(String(64), unique=True, index=True, nullable=False)
    task_id = Column(String(64), ForeignKey("runtime_tasks.task_id"), index=True, nullable=False)
    action_type = Column(String(128), nullable=False)
    target = Column(String(1024), nullable=False)
    parameters_hash = Column(String(64), nullable=False)
    status = Column(String(16), default="active", index=True, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)
    approved_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    used_at = Column(DateTime, nullable=True)


class RuntimeCircuit(Base):
    __tablename__ = "runtime_circuits"
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", name="uq_runtime_circuit_subject"),)

    id = Column(Integer, primary_key=True, index=True)
    subject_type = Column(String(32), index=True, nullable=False)
    subject_id = Column(String(384), index=True, nullable=False)
    state = Column(String(16), default="closed", index=True, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    opened_at = Column(DateTime, nullable=True)
    open_until = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RuntimeKillSwitch(Base):
    __tablename__ = "runtime_kill_switches"

    id = Column(Integer, primary_key=True, index=True)
    scope_type = Column(String(32), index=True, nullable=False)
    scope_id = Column(String(384), index=True, nullable=False)
    reason = Column(Text, nullable=False)
    active = Column(Boolean, default=True, index=True, nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    released_by = Column(String(128), nullable=True)
    released_at = Column(DateTime, nullable=True)


class RuntimeMemory(Base):
    __tablename__ = "runtime_memories"

    id = Column(Integer, primary_key=True, index=True)
    memory_id = Column(String(64), unique=True, index=True, nullable=False)
    tenant_id = Column(String(128), index=True, nullable=False)
    user_id = Column(String(128), index=True, nullable=False)
    session_id = Column(String(128), index=True, nullable=False)
    agent_id = Column(String(128), index=True, nullable=False)
    source_type = Column(String(32), index=True, nullable=False)
    source_ref = Column(String(1024), nullable=True)
    trust_status = Column(String(32), default="untrusted", index=True, nullable=False)
    current_version = Column(Integer, default=1, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=True)
    quarantined_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RuntimeMemoryRevision(Base):
    __tablename__ = "runtime_memory_revisions"
    __table_args__ = (UniqueConstraint("memory_id", "version", name="uq_runtime_memory_version"),)

    id = Column(Integer, primary_key=True, index=True)
    memory_id = Column(String(64), ForeignKey("runtime_memories.memory_id"), index=True, nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), index=True, nullable=False)
    provenance_json = Column(Text, default="{}", nullable=False)
    scan_findings_json = Column(Text, default="[]", nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    endpoint = Column(String(1024), nullable=False)
    authorization_header = Column(String(128), default="Authorization", nullable=False)
    authorization_value = Column(Text, nullable=True)
    status = Column(String(32), default="draft", index=True, nullable=False)
    health_status = Column(String(32), default="unknown", nullable=False)
    timeout_seconds = Column(Integer, default=30, nullable=False)
    max_response_kb = Column(Integer, default=1024, nullable=False)
    last_checked_at = Column(DateTime, nullable=True)
    created_by = Column(String(128), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class McpTool(Base):
    __tablename__ = "mcp_tools"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("mcp_servers.id"), index=True, nullable=False)
    name = Column(String(255), index=True, nullable=False)
    exposed_name = Column(String(384), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    input_schema_json = Column(Text, default="{}", nullable=False)
    schema_hash = Column(String(64), index=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    access_mode = Column(String(32), default="unknown", index=True, nullable=False)
    risk_level = Column(String(16), default="low", nullable=False)
    rate_limit_per_minute = Column(Integer, default=60, nullable=False)
    max_concurrent = Column(Integer, default=5, nullable=False)
    requires_approval = Column(Boolean, default=False, nullable=False)
    discovered_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class McpGateway(Base):
    __tablename__ = "mcp_gateways"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    environment = Column(String(32), default="test", index=True, nullable=False)
    execution_mode = Column(String(32), default="active_safe", nullable=False)
    production_tool_denylist_json = Column(Text, default="[]", nullable=False)
    status = Column(String(32), default="active", index=True, nullable=False)
    created_by = Column(String(128), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class McpGatewayBinding(Base):
    __tablename__ = "mcp_gateway_bindings"

    id = Column(Integer, primary_key=True, index=True)
    gateway_id = Column(Integer, ForeignKey("mcp_gateways.id"), index=True, nullable=False)
    server_id = Column(Integer, ForeignKey("mcp_servers.id"), index=True, nullable=False)
    allowed_tools_json = Column(Text, default="[]", nullable=False)
    approved_schema_hashes_json = Column(Text, default="{}", nullable=False)


class McpCallAudit(Base):
    __tablename__ = "mcp_call_audits"
    __table_args__ = (
        Index("ix_mcp_call_audits_created_id", "created_at", "id"),
        Index("ix_mcp_call_audits_duration_id", "duration_ms", "id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), unique=True, index=True, nullable=False)
    token_id = Column(Integer, ForeignKey("access_tokens.id"), index=True, nullable=False)
    token_name = Column(String(128), nullable=True)
    bound_agent_id = Column(String(128), index=True, nullable=True)
    gateway_slug = Column(String(128), index=True, nullable=False)
    server_slug = Column(String(128), index=True, nullable=True)
    tool_name = Column(String(255), index=True, nullable=True)
    schema_hash = Column(String(64), nullable=True)
    approval_request_id = Column(String(64), index=True, nullable=True)
    status = Column(String(32), index=True, nullable=False)
    duration_ms = Column(Float, default=0.0, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)


class McpToolApproval(Base):
    __tablename__ = "mcp_tool_approvals"

    id = Column(Integer, primary_key=True, index=True)
    approval_hash = Column(String(64), unique=True, index=True, nullable=False)
    request_id = Column(String(64), unique=True, index=True, nullable=True)
    token_id = Column(Integer, ForeignKey("access_tokens.id"), index=True, nullable=False)
    gateway_slug = Column(String(128), index=True, nullable=False)
    server_slug = Column(String(128), index=True, nullable=True)
    tool_id = Column(Integer, ForeignKey("mcp_tools.id"), index=True, nullable=True)
    tool_name = Column(String(384), index=True, nullable=False)
    schema_hash = Column(String(64), nullable=True)
    arguments_hash = Column(String(64), nullable=False)
    arguments_encrypted = Column(Text, nullable=True)
    client_ip = Column(String(128), nullable=True)
    status = Column(String(16), default="active", index=True, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)
    used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, default=0, nullable=False)
    first_used_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_by = Column(String(128), nullable=False)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ManagedClient(Base):
    __tablename__ = "managed_clients"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    hostname = Column(String(255), nullable=False)
    os = Column(String(32), nullable=False)
    arch = Column(String(32), nullable=False)
    client_version = Column(String(64), nullable=False)
    governance_mode = Column(String(32), default="registry", nullable=False)
    discovery_overrides_json = Column(Text, default="[]", nullable=False)
    policy_mode = Column(String(32), default="audit", nullable=False)
    status = Column(String(32), default="online", nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    registered_by = Column(String(128), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ClientGovernancePolicy(Base):
    __tablename__ = "client_governance_policies"

    scope = Column(String(128), primary_key=True)
    rules_json = Column(Text, default="{}", nullable=False)
    prompt_guard_json = Column(Text, default="null", nullable=False)
    compression_json = Column(Text, default="null", nullable=False)
    model_routing_json = Column(Text, default="null", nullable=False)
    desktop_menu_visibility_json = Column(Text, default="{}", nullable=False)
    desktop_menu_protocol = Column(Integer, default=0, nullable=False)
    desktop_menu_applied_json = Column(Text, nullable=True)
    desktop_menu_reported_at = Column(DateTime, nullable=True)
    runtime_revision = Column(Integer, nullable=True)
    runtime_governance_json = Column(Text, default="null", nullable=False)
    revision = Column(Integer, default=0, nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    protocol = Column(Integer, default=0, nullable=False)
    updated_by = Column(String(128), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExternalAIGateway(Base):
    __tablename__ = "external_ai_gateways"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    management_base_url = Column(String(1024), nullable=False)
    model_base_url = Column(String(1024), nullable=False)
    token_id = Column(String(255), nullable=False)
    token_value_encrypted = Column(Text, nullable=False)
    enabled = Column(Boolean, default=True, index=True, nullable=False)
    last_test_status = Column(String(32), nullable=True)
    last_test_error = Column(Text, nullable=True)
    last_tested_at = Column(DateTime, nullable=True)
    created_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExternalGatewayAgentBinding(Base):
    __tablename__ = "external_gateway_agent_bindings"
    __table_args__ = (
        UniqueConstraint("gateway_id", "managed_agent_id", name="uq_external_gateway_managed_agent"),
        UniqueConstraint("gateway_id", "external_agent_id", name="uq_external_gateway_external_agent"),
    )

    id = Column(Integer, primary_key=True, index=True)
    gateway_id = Column(Integer, ForeignKey("external_ai_gateways.id"), index=True, nullable=False)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), index=True, nullable=True)
    managed_agent_id = Column(String(128), ForeignKey("managed_agents.agent_id"), index=True, nullable=False)
    external_agent_id = Column(String(255), index=True, nullable=False)
    key_id = Column(String(255), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    available_models_json = Column(Text, default="[]", nullable=False)
    models_refreshed_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="active", index=True, nullable=False)
    last_error = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ClientAgent(Base):
    __tablename__ = "client_agents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), index=True, nullable=False)
    local_agent_id = Column(String(128), index=True, nullable=True)
    agent_type = Column(String(64), index=True, nullable=False)
    managed_agent_id = Column(String(128), index=True, nullable=True)
    agent_version = Column(String(128), nullable=True)
    install_path = Column(String(1024), nullable=True)
    skills_path = Column(String(1024), nullable=True)
    skill_management_supported = Column(Boolean, default=True, nullable=False)
    capabilities_json = Column(Text, default="{}", nullable=False)
    desired_model = Column(String(128), nullable=True)
    applied_model = Column(String(128), nullable=True)
    model_config_status = Column(String(32), default="not_configured", nullable=False)
    model_config_error = Column(Text, nullable=True)
    model_config_updated_at = Column(DateTime, nullable=True)
    takeover_status = Column(String(32), default="discovered", nullable=False)
    last_scanned_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ClientSkillInstall(Base):
    __tablename__ = "client_skill_installs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), index=True, nullable=False)
    agent_type = Column(String(64), index=True, nullable=False)
    skill_id = Column(String(128), index=True, nullable=True)
    version_id = Column(String(128), index=True, nullable=True)
    version_no = Column(Integer, nullable=True)
    source_version = Column(String(128), nullable=True)
    skill_name = Column(String(255), index=True, nullable=False)
    skill_path = Column(String(1024), nullable=False)
    signature = Column(String(128), nullable=True)
    governance_json = Column(Text, nullable=True)
    install_mode = Column(String(32), default="observed", nullable=False)
    status = Column(String(32), default="observed", nullable=False)
    installed_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)


class ClientRecoveryRecord(Base):
    __tablename__ = "client_recovery_records"
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), primary_key=True)
    record_id = Column(String(128), primary_key=True)
    details_json = Column(Text, nullable=False)


class ClientTask(Base):
    __tablename__ = "client_tasks"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), index=True, nullable=False)
    task_type = Column(String(32), index=True, nullable=False)
    payload_json = Column(Text, default="{}", nullable=False)
    request_key = Column(String(64), unique=True, index=True, nullable=True)
    status = Column(String(32), default="pending", index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)


class ClientEvent(Base):
    __tablename__ = "client_events"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), index=True, nullable=False)
    event_type = Column(String(64), index=True, nullable=False)
    agent_type = Column(String(64), nullable=True)
    skill_name = Column(String(255), nullable=True)
    details_json = Column(Text, default="{}", nullable=False)
    aggregate_key = Column(String(64), unique=True, index=True, nullable=True)
    observation_count = Column(Integer, default=1, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)


class PrivacyPolicy(Base):
    __tablename__ = "privacy_policies"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("user_groups.id"), unique=True, index=True, nullable=True)
    name = Column(String(128), index=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    entity_types_json = Column(Text, nullable=False)
    entity_rules_json = Column(Text, default="{}", nullable=False)
    detect_system_messages = Column(Boolean, default=False, nullable=False)
    allow_bypass = Column(Boolean, default=False, nullable=False)
    mapping_ttl_days = Column(Integer, default=7, nullable=False)
    dp_enabled = Column(Boolean, default=True, nullable=False)
    dp_epsilon = Column(Float, default=1.0, nullable=False)
    dp_min_count = Column(Integer, default=5, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PseudonymMapping(Base):
    __tablename__ = "pseudonym_mappings"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(128), index=True, nullable=False)
    conversation_id = Column(String(128), index=True, nullable=False)
    token = Column(String(128), index=True, nullable=False)
    entity_type = Column(String(64), index=True, nullable=False)
    original_value = Column(Text, nullable=False)
    normalized_value = Column(Text, nullable=False)
    request_id = Column(String(64), index=True, nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)


class LlmRequestAudit(Base):
    __tablename__ = "llm_request_audit"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), unique=True, index=True, nullable=False)
    tenant_id = Column(String(128), index=True, nullable=False)
    conversation_id = Column(String(128), index=True, nullable=False)
    user_ref = Column(String(128), index=True, nullable=False)
    group_id = Column(Integer, index=True, nullable=True)
    api_key_id = Column(Integer, index=True, nullable=True)
    credential_type = Column(String(32), index=True, nullable=True)
    agent_id = Column(String(128), index=True, nullable=True)
    skill_id = Column(String(128), index=True, nullable=True)
    skill_version_id = Column(String(128), index=True, nullable=True)
    skill_name = Column(String(255), index=True, nullable=True)
    skill_context_source = Column(String(32), nullable=True)
    skill_trust_state = Column(String(32), index=True, nullable=True)
    skill_alert_severity = Column(String(16), index=True, nullable=True)
    skill_alert_codes_json = Column(Text, default="[]", nullable=False)
    model = Column(String(128), index=True, nullable=False)
    traffic_type = Column(String(32), default="pii_checked", nullable=False)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    detected_counts_json = Column(Text, default="{}", nullable=False)
    created_tokens = Column(Integer, default=0, nullable=False)
    reused_tokens = Column(Integer, default=0, nullable=False)
    # 压缩标记
    compression_enabled = Column(Boolean, default=False, nullable=False)
    compression_level = Column(String(32), nullable=True)
    request_duration_ms = Column(Float, default=0.0, nullable=False)
    upstream_duration_ms = Column(Float, default=0.0, nullable=False)
    platform_duration_ms = Column(Float, default=0.0, nullable=False)
    prompt_guard_result_json = Column(Text, default="{}", nullable=False)
    status = Column(String(32), default="success", nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LlmUsageMetric(Base):
    __tablename__ = "llm_usage_metrics"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), unique=True, index=True, nullable=False)
    tenant_id = Column(String(128), index=True, nullable=False)
    conversation_id = Column(String(128), index=True, nullable=False)
    group_id = Column(Integer, index=True, nullable=True)
    api_key_id = Column(Integer, index=True, nullable=True)
    model = Column(String(128), index=True, nullable=False)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    pii_hits_json = Column(Text, default="{}", nullable=False)
    created_tokens = Column(Integer, default=0, nullable=False)
    reused_tokens = Column(Integer, default=0, nullable=False)
    # 压缩统计（仅 enable_compression=True 时填充）
    pre_compression_tokens = Column(Integer, default=0, nullable=False)
    post_compression_tokens = Column(Integer, default=0, nullable=False)
    tokens_saved = Column(Integer, default=0, nullable=False)
    compression_ratio = Column(Float, default=0.0, nullable=False)
    compression_duration_ms = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LlmPipelineTrace(Base):
    __tablename__ = "llm_pipeline_traces"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), index=True, nullable=False)
    stage = Column(String(32), index=True, nullable=False)
    tenant_id = Column(String(128), index=True, nullable=False)
    conversation_id = Column(String(128), index=True, nullable=False)
    model = Column(String(128), index=True, nullable=False)
    bypass_pii = Column(Boolean, default=False, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)


class RuntimeTraceSession(Base):
    __tablename__ = "runtime_trace_sessions"

    id = Column(Integer, primary_key=True, index=True)
    trace_id = Column(String(64), unique=True, index=True, nullable=False)
    schema_version = Column(String(32), default="runtime-trace@1", nullable=False)
    tenant_id = Column(String(128), index=True, nullable=False)
    agent_id = Column(String(128), index=True, nullable=True)
    session_id = Column(String(128), index=True, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    owner_group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    created_by = Column(String(128), nullable=True)
    status = Column(String(32), default="active", index=True, nullable=False)
    completeness = Column(String(32), default="gateway_partial", index=True, nullable=False)
    has_agent_events = Column(Boolean, default=False, nullable=False)
    has_model_events = Column(Boolean, default=False, nullable=False)
    has_mcp_events = Column(Boolean, default=False, nullable=False)
    has_runtime_events = Column(Boolean, default=False, nullable=False)
    has_knowledge_events = Column(Boolean, default=False, nullable=False)
    event_count = Column(Integer, default=0, nullable=False)
    next_seq = Column(Integer, default=1, nullable=False)
    risk_level = Column(String(16), default="info", index=True, nullable=False)
    risk_codes_json = Column(Text, default="[]", nullable=False)
    risk_mapping_version = Column(String(64), nullable=True)
    first_event_at = Column(DateTime, nullable=True)
    last_event_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)


class GatewaySessionScope(Base):
    __tablename__ = "gateway_session_scopes"

    scope_id = Column(String(64), primary_key=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class GatewaySessionGroup(Base):
    __tablename__ = "gateway_session_groups"
    __table_args__ = (Index("ix_gateway_group_explicit", "scope_id", "explicit_digest"),)

    trace_id = Column(String(64), ForeignKey("runtime_trace_sessions.trace_id"), primary_key=True)
    scope_id = Column(String(64), nullable=False)
    explicit_digest = Column(String(64), nullable=True)
    method = Column(String(32), nullable=False)
    source = Column(String(64), nullable=False)
    request_count = Column(Integer, default=0, nullable=False)


class GatewaySessionRequest(Base):
    __tablename__ = "gateway_session_requests"
    __table_args__ = (
        Index("ix_gateway_request_prefix", "scope_id", "history_digest"),
        Index("ix_gateway_request_order", "trace_id", "request_index", unique=True),
    )

    request_id = Column(String(128), primary_key=True)
    trace_id = Column(String(64), ForeignKey("gateway_session_groups.trace_id"), index=True, nullable=False)
    scope_id = Column(String(64), nullable=False)
    history_digest = Column(String(64), nullable=False)
    message_count = Column(Integer, nullable=False)
    request_index = Column(Integer, nullable=False)
    match_reason = Column(String(32), nullable=False)
    matched_request_id = Column(String(128), nullable=True)
    matched_message_count = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="running", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class GatewaySessionFingerprint(Base):
    """Versioned, content-free evidence for optional gateway association."""
    __tablename__ = "gateway_session_fingerprints"
    __table_args__ = (Index("ix_gateway_fingerprint_match", "scope_id", "kind", "digest"),)
    request_id = Column(String(128), ForeignKey("gateway_session_requests.request_id"), primary_key=True)
    kind = Column(String(32), primary_key=True)
    scope_id = Column(String(64), nullable=False)
    digest = Column(String(64), nullable=False)
    message_count = Column(Integer, nullable=False)


class RuntimeTraceEvent(Base):
    __tablename__ = "runtime_trace_events"
    __table_args__ = (
        UniqueConstraint("trace_id", "event_id", name="uq_runtime_trace_event"),
        UniqueConstraint("trace_id", "seq", name="uq_runtime_trace_seq"),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(64), index=True, nullable=False)
    content_fingerprint = Column(String(64), nullable=False)
    trace_id = Column(String(64), ForeignKey("runtime_trace_sessions.trace_id"), index=True, nullable=False)
    seq = Column(Integer, nullable=False)
    schema_version = Column(String(32), default="runtime-trace@1", nullable=False)
    event_time = Column(DateTime, index=True, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    tenant_id = Column(String(128), index=True, nullable=False)
    agent_id = Column(String(128), index=True, nullable=True)
    session_id = Column(String(128), index=True, nullable=False)
    turn_id = Column(String(128), index=True, nullable=True)
    step_id = Column(String(128), index=True, nullable=True)
    source = Column(String(32), index=True, nullable=False)
    type = Column(String(64), index=True, nullable=False)
    request_id = Column(String(128), index=True, nullable=True)
    call_id = Column(String(128), index=True, nullable=True)
    parent_call_id = Column(String(128), index=True, nullable=True)
    status = Column(String(32), index=True, nullable=True)
    tool_name = Column(String(256), index=True, nullable=True)
    duration_ms = Column(Float, nullable=True)
    risk_codes_json = Column(Text, default="[]", nullable=False)
    risk_mapping_json = Column(Text, default="{}", nullable=False)
    payload_id = Column(String(64), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RuntimeTracePayload(Base):
    __tablename__ = "runtime_trace_payloads"

    id = Column(Integer, primary_key=True, index=True)
    payload_id = Column(String(64), unique=True, index=True, nullable=False)
    trace_id = Column(String(64), index=True, nullable=False)
    event_id = Column(String(64), index=True, nullable=False)
    raw_payload_encrypted = Column(Text, nullable=False)
    redacted_json = Column(Text, default="{}", nullable=False)
    raw_sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)


class RuntimeTraceIngestBatch(Base):
    __tablename__ = "runtime_trace_ingest_batches"
    __table_args__ = (UniqueConstraint("trace_id", "batch_id", name="uq_runtime_trace_batch"),)

    id = Column(Integer, primary_key=True, index=True)
    trace_id = Column(String(64), index=True, nullable=False)
    batch_id = Column(String(64), index=True, nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    accepted_count = Column(Integer, default=0, nullable=False)
    duplicate_count = Column(Integer, default=0, nullable=False)
    first_seq = Column(Integer, nullable=True)
    last_seq = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RuntimeTraceExport(Base):
    __tablename__ = "runtime_trace_exports"

    id = Column(Integer, primary_key=True, index=True)
    export_id = Column(String(64), unique=True, index=True, nullable=False)
    trace_id = Column(String(64), index=True, nullable=False)
    requested_by = Column(String(128), index=True, nullable=False)
    redaction_level = Column(String(16), nullable=False)
    format = Column(String(16), default="json", nullable=False)
    status = Column(String(16), default="ready", index=True, nullable=False)
    content_encrypted = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    downloaded_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, index=True, nullable=False)


class RuntimeTraceRawExportAuthorization(Base):
    __tablename__ = "runtime_trace_raw_export_authorizations"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    trace_id = Column(String(64), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, index=True, nullable=False)
    used_at = Column(DateTime, nullable=True)


class LoginLog(Base):
    __tablename__ = "login_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), index=True, nullable=False)
    ip_address = Column(String(128), nullable=False)
    request_id = Column(String(64), default="", nullable=False)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), index=True, nullable=False)
    action = Column(String(128), nullable=False)
    target = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SystemConfig(Base):
    __tablename__ = "system_configs"

    key = Column(String(128), primary_key=True, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    display_name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    task_type = Column(String(32), default="function", nullable=False)
    task_func = Column(String(128), nullable=True)
    command = Column(Text, nullable=True)
    cron_expr = Column(String(64), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TaskExecution(Base):
    __tablename__ = "task_executions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, index=True, nullable=False)
    task_name = Column(String(128), index=True, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    logs = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SystemMetric(Base):
    __tablename__ = "system_metrics"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    cpu_percent = Column(Float, nullable=False)
    memory_percent = Column(Float, nullable=False)
    disk_percent = Column(Float, nullable=False)


class SecurityTarget(Base):
    __tablename__ = "security_targets"

    id = Column(Integer, primary_key=True, index=True)
    target_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), index=True, nullable=False)
    target_type = Column(String(64), index=True, nullable=False)
    asset_type = Column(String(32), default="agent", index=True, nullable=False)
    connector_type = Column(String(64), default="custom_http", index=True, nullable=False)
    environment = Column(String(32), default="test", index=True, nullable=False)
    allowed_capabilities_json = Column(
        Text,
        default='["conversation","multi_turn","tool_read","tool_write","network_egress","file_read","file_write","code_execution","persistent_memory"]',
        nullable=False,
    )
    endpoint_url = Column(String(2048), nullable=False)
    status = Column(String(32), default="active", index=True, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    owner_group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    allowed_cidrs_json = Column(Text, default="[]", nullable=False)
    resolved_ips_json = Column(Text, default="[]", nullable=False)
    config_json = Column(Text, default="{}", nullable=False)
    created_by = Column(String(128), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityTargetCredential(Base):
    __tablename__ = "security_target_credentials"
    __table_args__ = (
        UniqueConstraint("target_id", "purpose", "version", name="uq_security_target_credential_purpose_version"),
    )

    id = Column(Integer, primary_key=True, index=True)
    credential_id = Column(String(64), unique=True, index=True, nullable=False)
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), index=True, nullable=False)
    purpose = Column(String(64), default="agent_runtime", index=True, nullable=False)
    credential_type = Column(String(32), nullable=False)
    secret_encrypted = Column(Text, nullable=False)
    secret_masked = Column(String(512), nullable=False)
    status = Column(String(32), default="active", index=True, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(128), nullable=True)


class SecurityScanPolicy(Base):
    __tablename__ = "security_scan_policies"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), unique=True, index=True, nullable=False)
    environment = Column(String(32), default="test", index=True, nullable=False)
    execution_mode = Column(String(32), default="read_only", nullable=False)
    allowed_capabilities_json = Column(
        Text,
        default='["conversation","multi_turn","tool_read","tool_write","network_egress","file_read","file_write","code_execution","persistent_memory"]',
        nullable=False,
    )
    production_target_ids_json = Column(Text, default="[]", nullable=False)
    maintenance_window_start = Column(DateTime, nullable=True)
    maintenance_window_end = Column(DateTime, index=True, nullable=True)
    dedicated_identity_ref = Column(String(128), nullable=True)
    enabled = Column(Boolean, default=True, index=True, nullable=False)
    outbound_allowlist_json = Column(Text, default="[]", nullable=False)
    max_rounds = Column(Integer, default=50, nullable=False)
    max_tokens = Column(Integer, default=200_000, nullable=False)
    max_cost_microunits = Column(Integer, default=5_000_000, nullable=False)
    max_concurrent_requests = Column(Integer, default=2, nullable=False)
    max_duration_seconds = Column(Integer, default=1800, nullable=False)
    max_response_bytes = Column(Integer, default=10 * 1024 * 1024, nullable=False)
    max_retries = Column(Integer, default=2, nullable=False)
    task_timeout_seconds = Column(Integer, default=3600, nullable=False)
    lease_seconds = Column(Integer, default=60, nullable=False)
    retry_backoff_seconds = Column(Integer, default=5, nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityScanApproval(Base):
    __tablename__ = "security_scan_approvals"

    id = Column(Integer, primary_key=True, index=True)
    approval_id = Column(String(64), unique=True, index=True, nullable=False)
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), index=True, nullable=False)
    policy_id = Column(String(64), ForeignKey("security_scan_policies.policy_id"), index=True, nullable=False)
    credential_id = Column(String(64), ForeignKey("security_target_credentials.credential_id"), nullable=False)
    credential_version = Column(Integer, nullable=False)
    dedicated_identity_ref = Column(String(128), nullable=False)
    maintenance_window_start = Column(DateTime, nullable=False)
    maintenance_window_end = Column(DateTime, index=True, nullable=False)
    status = Column(String(32), default="approved", index=True, nullable=False)
    approved_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    used_by = Column(String(128), nullable=True)
    used_task_id = Column(String(64), index=True, nullable=True)
    used_at = Column(DateTime, nullable=True)


class SecurityScanTask(Base):
    __tablename__ = "security_scan_tasks"
    trigger_source = Column(String(32), index=True, nullable=True)
    source_platform_id = Column(String(64), index=True, nullable=True)
    external_task_id = Column(String(128), index=True, nullable=True)
    business_request_id = Column(String(128), index=True, nullable=True)
    source_token_id = Column(Integer, nullable=True)
    source_request_id = Column(String(64), nullable=True)
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_security_scan_task_idempotency"),)

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), unique=True, index=True, nullable=False)
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), index=True, nullable=False)
    policy_id = Column(String(64), ForeignKey("security_scan_policies.policy_id"), index=True, nullable=False)
    approval_id = Column(String(64), ForeignKey("security_scan_approvals.approval_id"), index=True, nullable=True)
    scan_kind = Column(String(64), default="control_plane_validation", index=True, nullable=False)
    status = Column(String(32), default="pending", index=True, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    policy_snapshot_json = Column(Text, default="{}", nullable=False)
    target_snapshot_json = Column(Text, default="{}", nullable=False)
    report_template_version = Column(String(64), nullable=True)
    decision_criteria_version = Column(String(64), nullable=True)
    report_contract_json = Column(Text, default="{}", nullable=False)
    scan_options_encrypted = Column(Text, nullable=True)
    continued_from_task_id = Column(String(64), index=True, nullable=True)
    session_state_encrypted = Column(Text, nullable=True)
    engine_name = Column(String(128), nullable=True)
    engine_version = Column(String(128), nullable=True)
    created_by = Column(String(128), index=True, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    owner_group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    worker_id = Column(String(64), ForeignKey("security_scan_workers.worker_id"), index=True, nullable=True)
    lease_token_hash = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, index=True, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    attempt = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=1, nullable=False)
    next_attempt_at = Column(DateTime, index=True, nullable=True)
    cancel_requested = Column(Boolean, default=False, nullable=False)
    kill_switch_activated = Column(Boolean, default=False, index=True, nullable=False)
    kill_switch_activated_at = Column(DateTime, nullable=True)
    kill_switch_activated_by = Column(String(128), nullable=True)
    kill_switch_reason = Column(Text, nullable=True)
    timeout_at = Column(DateTime, index=True, nullable=False)
    rounds_used = Column(Integer, default=0, nullable=False)
    tokens_used = Column(Integer, default=0, nullable=False)
    cost_microunits_used = Column(Integer, default=0, nullable=False)
    max_concurrency_seen = Column(Integer, default=0, nullable=False)
    response_bytes_used = Column(Integer, default=0, nullable=False)
    stop_reason = Column(String(128), nullable=True)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class SecurityScanCase(Base):
    __tablename__ = "security_scan_cases"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(String(64), unique=True, index=True, nullable=False)
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), index=True, nullable=False)
    external_case_id = Column(String(256), index=True, nullable=True)
    category = Column(String(128), index=True, nullable=False)
    title = Column(String(512), nullable=False)
    status = Column(String(32), index=True, nullable=False)
    request_summary_json = Column(Text, default="{}", nullable=False)
    response_summary_json = Column(Text, default="{}", nullable=False)
    round_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityFinding(Base):
    __tablename__ = "security_findings"

    id = Column(Integer, primary_key=True, index=True)
    finding_id = Column(String(64), unique=True, index=True, nullable=False)
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), index=True, nullable=False)
    case_id = Column(String(64), ForeignKey("security_scan_cases.case_id"), index=True, nullable=True)
    asset_id = Column(String(512), index=True, nullable=True)
    trace_id = Column(String(64), index=True, nullable=True)
    event_id = Column(String(64), index=True, nullable=True)
    finding_code = Column(String(128), index=True, nullable=False)
    risk_codes_json = Column(Text, default="[]", nullable=False)
    risk_mapping_json = Column(Text, default="{}", nullable=False)
    decision_criteria_version = Column(String(64), nullable=True)
    severity = Column(String(16), index=True, nullable=False)
    status = Column(String(32), default="open", index=True, nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=False)
    evidence_json = Column(Text, default="{}", nullable=False)
    source = Column(String(64), nullable=False)
    confidence = Column(Float, default=0.0, nullable=False)
    fingerprint = Column(String(64), index=True, nullable=False, default="")
    disposition_comment = Column(Text, nullable=True)
    disposition_by = Column(String(128), nullable=True)
    disposition_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityScanArtifact(Base):
    __tablename__ = "security_scan_artifacts"

    id = Column(Integer, primary_key=True, index=True)
    artifact_id = Column(String(64), unique=True, index=True, nullable=False)
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), index=True, nullable=False)
    artifact_type = Column(String(64), index=True, nullable=False)
    uri = Column(String(2048), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, default=0, nullable=False)
    redacted = Column(Boolean, default=True, nullable=False)
    metadata_json = Column(Text, default="{}", nullable=False)
    content_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityAssetInventorySnapshot(Base):
    __tablename__ = "security_asset_inventory_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(String(64), unique=True, index=True, nullable=False)
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), unique=True, index=True, nullable=False)
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), index=True, nullable=False)
    app_id = Column(String(128), index=True, nullable=False)
    schema_version = Column(String(64), default="dify-asset-inventory@1", nullable=False)
    engine_name = Column(String(128), default="agent-manager-dify-inventory", nullable=False)
    agent_profile_json = Column(Text, default="{}", nullable=False)
    summary_json = Column(Text, default="{}", nullable=False)
    coverage_json = Column(Text, default="{}", nullable=False)
    limitations_json = Column(Text, default="[]", nullable=False)
    collected_at = Column(DateTime, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityAssetInventoryItem(Base):
    __tablename__ = "security_asset_inventory_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "asset_id", name="uq_security_asset_inventory_snapshot_asset"),
    )

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(String(64), unique=True, index=True, nullable=False)
    snapshot_id = Column(String(64), ForeignKey("security_asset_inventory_snapshots.snapshot_id"), index=True, nullable=False)
    asset_id = Column(String(512), index=True, nullable=False)
    asset_type = Column(String(64), index=True, nullable=False)
    name = Column(String(512), nullable=False)
    configured = Column(Boolean, default=False, nullable=False)
    discovered = Column(Boolean, default=False, nullable=False)
    executed = Column(Boolean, default=False, nullable=False)
    verification_status = Column(String(32), index=True, nullable=False)
    details_json = Column(Text, default="{}", nullable=False)
    sensitive_content_encrypted = Column(Text, nullable=True)
    fingerprint = Column(String(64), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityAssetInventoryEvidence(Base):
    __tablename__ = "security_asset_inventory_evidence"

    id = Column(Integer, primary_key=True, index=True)
    evidence_id = Column(String(64), unique=True, index=True, nullable=False)
    item_id = Column(String(64), ForeignKey("security_asset_inventory_items.item_id"), index=True, nullable=False)
    source_type = Column(String(64), index=True, nullable=False)
    source_identifier = Column(String(2048), nullable=True)
    metadata_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityScanWorker(Base):
    __tablename__ = "security_scan_workers"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), unique=True, index=True, nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    token_prefix = Column(String(24), index=True, nullable=False)
    status = Column(String(32), default="active", index=True, nullable=False)
    capabilities_json = Column(Text, default="[]", nullable=False)
    max_concurrency = Column(Integer, default=1, nullable=False)
    public_key_algorithm = Column(String(64), nullable=True)
    public_key = Column(Text, nullable=True)
    public_key_fingerprint = Column(String(64), nullable=True)
    public_key_registered_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, index=True, nullable=True)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(128), nullable=True)


class SecurityMcpScanSession(Base):
    __tablename__ = "security_mcp_scan_sessions"
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), primary_key=True)
    token_id = Column(Integer, ForeignKey("access_tokens.id"), nullable=False)


class SecurityMcpScanCall(Base):
    __tablename__ = "security_mcp_scan_calls"
    call_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), index=True, nullable=False)
    tool_name = Column(String(384), nullable=False)
    schema_hash = Column(String(128), nullable=False)
    route = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    evidence_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
