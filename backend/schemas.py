from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserBase(BaseModel):
    username: str
    email: Optional[EmailStr] = None


class UserCreate(UserBase):
    password: str
    role: str = "admin"

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


class ModelProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: Optional[str] = None
    enabled: bool = True
    timeout_seconds: int = Field(default=60, ge=1, le=600)


class ModelProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=600)


class ModelProviderResponse(BaseModel):
    id: int
    name: str
    base_url: str
    enabled: bool
    timeout_seconds: int
    api_key_configured: bool
    api_key_masked: Optional[str] = None
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


class LlmApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    allowed_models: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern="^(active|disabled|revoked)$")
    expires_at: Optional[datetime] = None
    max_body_kb: Optional[int] = Field(default=None, ge=1, le=10240)
    max_concurrent_requests: Optional[int] = Field(default=None, ge=1, le=100)


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
    created_at: datetime
    last_used_at: Optional[datetime] = None


class PrivacyPolicyPayload(BaseModel):
    name: str = "默认隐私策略"
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
