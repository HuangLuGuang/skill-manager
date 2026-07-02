from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from .sqlite_db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    role = Column(String(32), default="admin", nullable=False)
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

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(128), index=True, nullable=False)
    department_group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    owner = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    channel = Column(String(64), nullable=True)
    status = Column(String(32), default="active", nullable=False)
    default_model = Column(String(128), nullable=True)
    skill_names_json = Column(Text, default="[]", nullable=False)
    prompt_names_json = Column(Text, default="[]", nullable=False)
    runtime_token_id = Column(Integer, ForeignKey("access_tokens.id"), nullable=True)
    runtime_token_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ModelProvider(Base):
    __tablename__ = "model_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    base_url = Column(String(512), nullable=False)
    api_key = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    timeout_seconds = Column(Integer, default=60, nullable=False)
    # Provider 级别压缩默认值（API Key 设置优先）
    enable_compression = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("model_providers.id"), index=True, nullable=False)
    name = Column(String(128), unique=True, index=True, nullable=False)
    display_name = Column(String(128), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    context_window = Column(Integer, nullable=True)
    max_output_tokens = Column(Integer, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class LlmApiKey(Base):
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
    prompt_guard_mode = Column(String(32), default="off", nullable=False)
    prompt_guard_llm_review = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)


class AccessToken(Base):
    __tablename__ = "access_tokens"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), index=True, nullable=False)
    token_type = Column(String(32), index=True, nullable=False)
    token_hash = Column(String(128), unique=True, index=True, nullable=False)
    token_prefix = Column(String(24), index=True, nullable=False)
    scopes_json = Column(Text, default="[]", nullable=False)
    bound_agent_id = Column(String(128), index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    group_id = Column(Integer, ForeignKey("user_groups.id"), index=True, nullable=True)
    allowed_models_json = Column(Text, default="[]", nullable=False)
    allowed_ips_json = Column(Text, default="[]", nullable=False)
    status = Column(String(32), default="active", nullable=False)
    expires_at = Column(DateTime, nullable=True)
    max_body_kb = Column(Integer, default=1024, nullable=False)
    max_concurrent_requests = Column(Integer, default=5, nullable=False)
    max_upload_mb = Column(Integer, default=50, nullable=False)
    max_concurrent_jobs = Column(Integer, default=2, nullable=False)
    enable_compression = Column(Boolean, default=False, nullable=False)
    compression_level = Column(String(32), default="auto", nullable=False)
    prompt_guard_mode = Column(String(32), default="off", nullable=False)
    prompt_guard_llm_review = Column(Boolean, default=False, nullable=False)
    created_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(128), nullable=True)


class PrivacyPolicy(Base):
    __tablename__ = "privacy_policies"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("user_groups.id"), unique=True, index=True, nullable=True)
    name = Column(String(128), index=True, nullable=False)
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


class LoginLog(Base):
    __tablename__ = "login_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), index=True, nullable=False)
    ip_address = Column(String(128), nullable=False)
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
