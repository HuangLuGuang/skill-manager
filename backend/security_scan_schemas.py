from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .feature_flags import EXECUTION_MODES
from .security_redteam_catalog import LLM_REDTEAM_DATASETS
from .security_scan_controls import (
    AGENT_SCAN_SKILLS,
    DEFAULT_SECURITY_SCAN_CAPABILITIES,
    FINDING_STATUSES,
    SECURITY_SCAN_CAPABILITIES,
    SECURITY_ASSET_TYPES,
    SECURITY_CONNECTOR_TYPES,
    SECURITY_CREDENTIAL_PURPOSES,
    SECURITY_SEVERITIES,
    SECURITY_TARGET_ENVIRONMENTS,
    SUPPORTED_SCAN_KINDS,
    legacy_target_classification,
    validate_asset_connector,
)


def _validate_environment(value: str) -> str:
    if value not in SECURITY_TARGET_ENVIRONMENTS:
        raise ValueError("unsupported security target environment")
    return value


def _validate_allowed_capabilities(values: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(values))
    if any(value not in SECURITY_SCAN_CAPABILITIES for value in normalized):
        raise ValueError("unsupported security scan capability")
    return normalized


class SecurityTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    asset_type: str | None = Field(default=None, max_length=32)
    connector_type: str | None = Field(default=None, max_length=64)
    target_type: str | None = Field(default=None, min_length=1, max_length=64)
    environment: str = "test"
    allowed_capabilities: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SECURITY_SCAN_CAPABILITIES), max_length=32
    )
    endpoint_url: str = Field(min_length=1, max_length=2048)
    owner_user_id: int | None = None
    owner_group_id: int | None = None
    allowed_cidrs: list[str] = Field(default_factory=list, max_length=32)
    allow_insecure_transport: bool = False
    config: dict[str, Any] = Field(default_factory=dict)

    _environment = field_validator("environment")(_validate_environment)
    _allowed_capabilities = field_validator("allowed_capabilities")(_validate_allowed_capabilities)

    @model_validator(mode="after")
    def normalize_target_classification(self):
        if self.asset_type is None or self.connector_type is None:
            if not self.target_type:
                raise ValueError("asset_type and connector_type are required")
            asset, connector = legacy_target_classification(self.target_type)
            self.asset_type = asset
            self.connector_type = connector
        else:
            self.asset_type, self.connector_type = validate_asset_connector(
                self.asset_type, self.connector_type
            )
        return self


class SecurityTargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=2048)
    status: Literal["active", "disabled"] | None = None
    environment: str | None = None
    allowed_capabilities: list[str] | None = Field(default=None, max_length=32)
    owner_user_id: int | None = None
    owner_group_id: int | None = None
    allowed_cidrs: list[str] | None = Field(default=None, max_length=32)
    allow_insecure_transport: bool | None = None
    config: dict[str, Any] | None = None
    asset_type: str | None = Field(default=None, max_length=32)
    connector_type: str | None = Field(default=None, max_length=64)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str | None) -> str | None:
        return _validate_environment(value) if value is not None else None

    @field_validator("allowed_capabilities")
    @classmethod
    def validate_allowed_capabilities(cls, values: list[str] | None) -> list[str] | None:
        return _validate_allowed_capabilities(values) if values is not None else None


class SecurityTargetResponse(BaseModel):
    target_id: str
    name: str
    target_type: str
    asset_type: str
    connector_type: str
    environment: str
    allowed_capabilities: list[str]
    endpoint_url: str
    status: str
    owner_user_id: int | None
    owner_group_id: int | None
    allowed_cidrs: list[str]
    resolved_ips: list[str]
    allow_insecure_transport: bool
    config: dict[str, Any]
    credential_configured: bool
    credential_masked: str | None = None
    credentials: list[dict[str, Any]] = Field(default_factory=list)
    engine_available: bool
    engine_error_code: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class SecurityCredentialCreate(BaseModel):
    credential_type: Literal["bearer", "api_key", "basic", "custom"] = "bearer"
    purpose: str | None = None
    secret: str = Field(min_length=1, max_length=8192)

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in SECURITY_CREDENTIAL_PURPOSES:
            raise ValueError("unsupported credential purpose")
        return value


class SecurityCredentialUpdate(BaseModel):
    secret: str = Field(min_length=1, max_length=8192)


class SecurityCredentialStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]


class SecurityCredentialResponse(BaseModel):
    credential_id: str
    target_id: str
    credential_type: str
    purpose: str
    secret_masked: str
    secret_once: str | None = None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None


class SecurityPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    environment: str = "test"
    execution_mode: str = "read_only"
    allowed_capabilities: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SECURITY_SCAN_CAPABILITIES), max_length=32
    )
    production_target_ids: list[str] = Field(default_factory=list, max_length=128)
    maintenance_window_start: datetime | None = None
    maintenance_window_end: datetime | None = None
    dedicated_identity_ref: str | None = Field(default=None, max_length=128)
    outbound_allowlist: list[str] = Field(default_factory=list, max_length=32)
    max_rounds: int = Field(default=50, ge=1, le=10_000)
    max_tokens: int = Field(default=200_000, ge=1, le=100_000_000)
    max_cost_microunits: int = Field(default=5_000_000, ge=0, le=10_000_000_000)
    max_concurrent_requests: int = Field(default=2, ge=1, le=128)
    max_duration_seconds: int = Field(default=1800, ge=1, le=86_400)
    max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    max_retries: int = Field(default=2, ge=0, le=10)
    task_timeout_seconds: int = Field(default=3600, ge=1, le=7 * 86_400)
    lease_seconds: int = Field(default=60, ge=10, le=600)
    retry_backoff_seconds: int = Field(default=5, ge=0, le=3600)

    _environment = field_validator("environment")(_validate_environment)
    _allowed_capabilities = field_validator("allowed_capabilities")(_validate_allowed_capabilities)

    @field_validator("production_target_ids")
    @classmethod
    def validate_production_target_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(values))
        if any(not value or len(value) > 64 for value in normalized):
            raise ValueError("invalid production target id")
        return normalized

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, value: str) -> str:
        if value not in EXECUTION_MODES:
            raise ValueError("unsupported execution_mode")
        return value


class SecurityPolicyUpdate(BaseModel):
    enabled: bool | None = None
    environment: str | None = None
    execution_mode: str | None = None
    allowed_capabilities: list[str] | None = Field(default=None, max_length=32)
    production_target_ids: list[str] | None = Field(default=None, max_length=128)
    maintenance_window_start: datetime | None = None
    maintenance_window_end: datetime | None = None
    dedicated_identity_ref: str | None = Field(default=None, max_length=128)
    outbound_allowlist: list[str] | None = Field(default=None, max_length=32)
    max_rounds: int | None = Field(default=None, ge=1, le=10_000)
    max_tokens: int | None = Field(default=None, ge=1, le=100_000_000)
    max_cost_microunits: int | None = Field(default=None, ge=0, le=10_000_000_000)
    max_concurrent_requests: int | None = Field(default=None, ge=1, le=128)
    max_duration_seconds: int | None = Field(default=None, ge=1, le=86_400)
    max_response_bytes: int | None = Field(default=None, ge=1, le=1024 * 1024 * 1024)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    task_timeout_seconds: int | None = Field(default=None, ge=1, le=7 * 86_400)
    lease_seconds: int | None = Field(default=None, ge=10, le=600)
    retry_backoff_seconds: int | None = Field(default=None, ge=0, le=3600)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str | None) -> str | None:
        return _validate_environment(value) if value is not None else None

    @field_validator("allowed_capabilities")
    @classmethod
    def validate_allowed_capabilities(cls, values: list[str] | None) -> list[str] | None:
        return _validate_allowed_capabilities(values) if values is not None else None

    @field_validator("production_target_ids")
    @classmethod
    def validate_production_target_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = list(dict.fromkeys(values))
        if any(not value or len(value) > 64 for value in normalized):
            raise ValueError("invalid production target id")
        return normalized

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in EXECUTION_MODES:
            raise ValueError("unsupported execution_mode")
        return value


class SecurityPolicyResponse(SecurityPolicyCreate):
    policy_id: str
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class SecurityTaskPlanRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=64)
    policy_id: str = Field(min_length=1, max_length=64)
    approval_id: str | None = Field(default=None, min_length=1, max_length=64)
    scan_kind: str = "control_plane_validation"
    language: Literal["zh", "en"] = "zh"
    skills: list[str] = Field(default_factory=list, max_length=10)
    prompt: str = Field(default="", max_length=4096)
    conversation_mode: Literal["single_turn", "multi_turn"] = "single_turn"
    continue_from_task_id: str | None = Field(default=None, min_length=1, max_length=64)
    reset_session: bool = True
    datasets: list[str] = Field(default_factory=list, max_length=len(LLM_REDTEAM_DATASETS))
    num_prompts: Literal[-1] | Annotated[int, Field(ge=1, le=100)] = 10
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    techniques: list[str] = Field(default_factory=list, max_length=7)
    evaluation_model: str | None = Field(default=None, max_length=128)
    http_authorized: bool = False
    private_network_authorized: bool = False
    scan_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    scan_concurrency: int | None = Field(default=None, ge=1, le=16)
    inventory_source: Literal["console_api", "manual_dsl"] = "console_api"
    manual_dsl: str | None = Field(default=None, max_length=10 * 1024 * 1024)
    include_prompt_text: bool = False
    infer_agent_intent: bool = False
    intent_inference_model: str | None = Field(default=None, max_length=128)
    knowledge_content_authorized: bool = False
    max_knowledge_documents: int = Field(default=100, ge=1, le=1000)
    max_knowledge_segments: int = Field(default=1000, ge=1, le=10000)
    max_knowledge_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)

    @field_validator("scan_kind")
    @classmethod
    def validate_scan_kind(cls, value: str) -> str:
        if value not in SUPPORTED_SCAN_KINDS:
            raise ValueError("scan_kind is not available")
        return value

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(value not in AGENT_SCAN_SKILLS for value in values):
            raise ValueError("unsupported or duplicate agent scan skill")
        return values

    @field_validator("datasets")
    @classmethod
    def validate_datasets(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(values))
        if any(value not in LLM_REDTEAM_DATASETS for value in normalized):
            raise ValueError("unsupported LLM red-team dataset")
        return normalized

    @field_validator("techniques")
    @classmethod
    def validate_techniques(cls, values: list[str]) -> list[str]:
        allowed = {
            "Raw",
            "BaseEncoding",
            "Leetspeak",
            "PromptInjection",
            "Roleplay",
            "ROTEncoding",
            "SystemOverride",
        }
        normalized = list(dict.fromkeys(values))
        if any(value not in allowed for value in normalized):
            raise ValueError("unsupported LLM red-team technique")
        return normalized

    @model_validator(mode="after")
    def validate_scan_specific_options(self):
        if self.scan_kind == "llm_redteam_scan":
            if self.datasets and self.prompt.strip():
                raise ValueError("LLM red-team dataset and custom prompt are mutually exclusive")
        elif self.datasets or self.techniques or self.evaluation_model:
            raise ValueError("LLM red-team options are only valid for LLM red-team scans")
        if self.scan_kind != "ai_infrastructure_vulnerability_scan" and (
            self.http_authorized
            or self.private_network_authorized
            or self.scan_timeout_seconds is not None
            or self.scan_concurrency is not None
        ):
            raise ValueError("infrastructure options are only valid for infrastructure scans")
        if self.scan_kind == "dify_asset_inventory":
            if self.inventory_source == "manual_dsl" and not (self.manual_dsl or "").strip():
                raise ValueError("manual Dify inventory requires a DSL document")
            if self.inventory_source == "console_api" and self.manual_dsl:
                raise ValueError("Console API inventory cannot include a manual DSL document")
            if self.skills or self.prompt or self.continue_from_task_id or self.datasets or self.techniques:
                raise ValueError("Dify inventory does not accept dynamic scan options")
        elif (
            self.manual_dsl
            or self.include_prompt_text
            or self.infer_agent_intent
            or self.intent_inference_model
            or self.knowledge_content_authorized
        ):
            raise ValueError("Dify inventory options are only valid for Dify inventory scans")
        if self.intent_inference_model and not self.infer_agent_intent:
            raise ValueError("intent inference model requires intent inference to be enabled")
        return self


class SecurityTaskPreviewRequest(SecurityTaskPlanRequest):
    pass


class SecurityTaskCreate(SecurityTaskPlanRequest):
    idempotency_key: str = Field(min_length=8, max_length=128)
    preview_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SecurityTaskKillSwitchRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("kill switch reason is required")
        return normalized


class SecurityTaskPreviewResponse(BaseModel):
    schema_version: Literal["scan-preview@1"] = "scan-preview@1"
    preview_fingerprint: str
    target: dict[str, Any]
    policy: dict[str, Any]
    scan_kind: str
    cases: list[dict[str, Any]]
    tool_plan: dict[str, Any]
    budget: dict[str, int]
    safety: dict[str, Any]
    limitations: list[str] = Field(default_factory=list)


class SecurityLiveCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)
    status: Literal["queued", "running", "passed", "failed", "error", "unverified"]
    attack_method: str = Field(default="", max_length=128)
    vulnerability: str = Field(default="", max_length=256)
    prompt: str = Field(default="", max_length=8192)
    response: str = Field(default="", max_length=8192)
    reason: str = Field(default="", max_length=2048)


class SecurityLiveProgress(BaseModel):
    observed_total: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    cases: list[SecurityLiveCase] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.completed + self.running > self.observed_total or self.errors > self.completed:
            raise ValueError("Invalid scan progress counts")
        return self


class SecurityTaskResponse(BaseModel):
    task_id: str
    target_id: str
    policy_id: str
    approval_id: str | None = None
    scan_kind: str
    status: str
    idempotency_key: str
    created_by: str
    worker_id: str | None
    attempt: int
    max_attempts: int
    cancel_requested: bool
    kill_switch_activated: bool
    kill_switch_activated_at: datetime | None
    kill_switch_activated_by: str | None
    kill_switch_reason: str | None
    stop_reason: str | None
    error_code: str | None
    error_message: str | None
    usage: dict[str, int]
    progress: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    timeout_at: datetime
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    scan_options: dict[str, Any] = Field(default_factory=dict)
    continued_from_task_id: str | None = None
    session_continuation_available: bool = False
    engine: dict[str, str] = Field(default_factory=dict)
    report_template_version: str | None = None
    decision_criteria_version: str | None = None
    report_contract_status: Literal["frozen", "legacy_unversioned"] = "legacy_unversioned"


class SecurityScanApprovalCreate(BaseModel):
    target_id: str = Field(min_length=1, max_length=64)
    policy_id: str = Field(min_length=1, max_length=64)


class SecurityScanApprovalResponse(BaseModel):
    approval_id: str
    target_id: str
    policy_id: str
    credential_id: str
    credential_version: int
    dedicated_identity_ref: str
    maintenance_window_start: datetime
    maintenance_window_end: datetime
    status: str
    approved_by: str
    created_at: datetime
    used_by: str | None = None
    used_task_id: str | None = None
    used_at: datetime | None = None


class SecurityWorkerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    capabilities: list[str] = Field(
        default_factory=lambda: ["control_plane_validation", "agent_risk_scan", "mcp_risk_scan"],
        min_length=1,
        max_length=32,
    )
    max_concurrency: int = Field(default=1, ge=1, le=128)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: list[str]) -> list[str]:
        if any(value not in SUPPORTED_SCAN_KINDS for value in values):
            raise ValueError("worker capability is not available")
        return values


class SecurityWorkerResponse(BaseModel):
    worker_id: str
    name: str
    token_prefix: str
    token_once: str | None = None
    status: str
    capabilities: list[str]
    max_concurrency: int
    last_heartbeat_at: datetime | None
    created_at: datetime
    public_key_fingerprint: str | None = None
    public_key_registered_at: datetime | None = None


class SecurityWorkerKeyRegister(BaseModel):
    algorithm: Literal["x25519-hkdf-sha256-aesgcm-v1"]
    public_key: str = Field(min_length=40, max_length=128)


class SecurityWorkerKeyResponse(BaseModel):
    worker_id: str
    algorithm: str
    public_key_fingerprint: str
    registered_at: datetime


class SecurityWorkerClaimRequest(BaseModel):
    capabilities: list[str] = Field(default_factory=list, max_length=32)


class SecurityWorkerClaimResponse(BaseModel):
    task: SecurityTaskResponse | None
    lease_token: str | None = None
    lease_seconds: int | None = None
    target: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    credential: dict[str, Any] | None = None
    credentials: list[dict[str, Any]] = Field(default_factory=list)
    scan_options: dict[str, Any] | None = None


class SecurityTaskUsage(BaseModel):
    rounds: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    cost_microunits: int = Field(default=0, ge=0)
    concurrent_requests: int = Field(default=0, ge=0)
    response_bytes: int = Field(default=0, ge=0)


class SecurityWorkerHeartbeatRequest(BaseModel):
    lease_token: str = Field(min_length=16, max_length=512)
    usage: SecurityTaskUsage = Field(default_factory=SecurityTaskUsage)
    session_state: str | None = Field(default=None, max_length=2048)
    scan_progress: SecurityLiveProgress | None = None


class SecurityWorkerHeartbeatResponse(BaseModel):
    continue_allowed: bool
    status: str
    stop_reason: str | None = None
    lease_expires_at: datetime | None = None


class SecurityIntentInferenceRequest(BaseModel):
    lease_token: str = Field(min_length=16, max_length=512)
    usage: SecurityTaskUsage = Field(default_factory=SecurityTaskUsage)
    summary: dict[str, Any]

    @model_validator(mode="after")
    def validate_summary_size(self):
        if len(self.model_dump_json().encode("utf-8")) > 128 * 1024:
            raise ValueError("intent inference request exceeds 128 KiB")
        return self


class SecurityIntentInferenceResponse(BaseModel):
    status: Literal["inferred", "unavailable"]
    intent: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_summary: list[str] = Field(default_factory=list, max_length=8)
    model: str | None = None
    provider: str | None = None
    rule_version: str = "intent-inference@1"
    error_code: str | None = None
    diagnostic_code: Literal[
        "empty_content", "json_decode_failed", "unexpected_fields",
        "confidence_invalid", "evidence_invalid", "output_too_large",
    ] | None = None
    collected_at: datetime
    usage: SecurityTaskUsage
    continue_allowed: bool = True
    stop_reason: str | None = None


class SecurityCaseInput(BaseModel):
    external_case_id: str | None = Field(default=None, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    status: Literal["passed", "failed", "blocked", "error", "unverified"]
    request_summary: dict[str, Any] = Field(default_factory=dict)
    response_summary: dict[str, Any] = Field(default_factory=dict)
    round_count: int = Field(default=0, ge=0)


class SecurityFindingInput(BaseModel):
    case_external_id: str | None = Field(default=None, max_length=256)
    asset_id: str | None = Field(default=None, max_length=512)
    trace_id: str | None = Field(default=None, min_length=1, max_length=64)
    event_id: str | None = Field(default=None, min_length=1, max_length=64)
    finding_code: str = Field(min_length=1, max_length=128)
    severity: str
    status: str = "open"
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(min_length=1, max_length=16_384)
    evidence: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(min_length=1, max_length=64)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_trace_reference(self):
        if bool(self.trace_id) != bool(self.event_id):
            raise ValueError("trace_id and event_id must be provided together")
        return self

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        if value not in SECURITY_SEVERITIES:
            raise ValueError("unsupported severity")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in FINDING_STATUSES:
            raise ValueError("unsupported finding status")
        return value


class SecurityArtifactInput(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=64)
    uri: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(default=0, ge=0)
    redacted: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: str | None = Field(default=None, max_length=12 * 1024 * 1024)


class SecurityWorkerCompleteRequest(BaseModel):
    lease_token: str = Field(min_length=16, max_length=512)
    status: Literal["succeeded", "failed"]
    retryable: bool = False
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=8192)
    usage: SecurityTaskUsage = Field(default_factory=SecurityTaskUsage)
    cases: list[SecurityCaseInput] = Field(default_factory=list, max_length=2_000)
    findings: list[SecurityFindingInput] = Field(default_factory=list, max_length=2_000)
    artifacts: list[SecurityArtifactInput] = Field(default_factory=list, max_length=100)
    session_state: str | None = Field(default=None, max_length=2048)
    engine_name: str | None = Field(default=None, max_length=128)
    engine_version: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_aggregate_size(self):
        encoded_size = len(self.model_dump_json().encode("utf-8"))
        if encoded_size > 16 * 1024 * 1024:
            raise ValueError("worker completion payload exceeds 16 MiB")
        return self


class SecurityFindingTraceability(BaseModel):
    status: Literal["complete", "incomplete"]
    case_id: str | None = None
    trace_id: str | None = None
    event_id: str | None = None
    evidence_sha256: str | None = None
    decision_criteria_version: str | None = None
    missing: list[Literal["case", "event", "evidence", "decision_criteria"]] = Field(default_factory=list)


class SecurityFindingResponse(BaseModel):
    finding_id: str
    task_id: str
    case_id: str | None
    asset_id: str | None = None
    trace_id: str | None = None
    event_id: str | None = None
    finding_code: str
    risk_codes: list[str] = Field(default_factory=list)
    risk_mapping: dict[str, Any] = Field(default_factory=dict)
    decision_criteria_version: str | None = None
    severity: str
    status: str
    title: str
    description: str
    evidence: dict[str, Any]
    source: str
    confidence: float
    fingerprint: str
    traceability: SecurityFindingTraceability
    disposition_comment: str | None = None
    disposition_by: str | None = None
    disposition_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SecurityFindingListItem(SecurityFindingResponse):
    target_id: str
    target_name: str
    scan_kind: str
    scan_created_at: datetime


class SecurityFindingListResponse(BaseModel):
    items: list[SecurityFindingListItem]
    total: int
    severity_counts: dict[str, int]


class SecurityComparisonUnavailableItem(BaseModel):
    finding: SecurityFindingResponse
    reason_code: Literal[
        "baseline_not_succeeded",
        "current_not_succeeded",
        "coverage_changed",
        "engine_changed",
    ]


class SecurityTaskComparisonResponse(BaseModel):
    schema_version: Literal["security-scan-comparison@1"] = "security-scan-comparison@1"
    task_id: str
    baseline_task_id: str
    comparison_status: Literal["complete", "partial"]
    coverage_match: bool
    coverage_fingerprint: str
    baseline_coverage_fingerprint: str
    engine_match: bool
    new: list[SecurityFindingResponse] = Field(default_factory=list)
    unchanged: list[SecurityFindingResponse] = Field(default_factory=list)
    resolved: list[SecurityFindingResponse] = Field(default_factory=list)
    unable_to_retest: list[SecurityComparisonUnavailableItem] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class SecurityFindingDisposition(BaseModel):
    status: Literal["open", "accepted", "resolved", "false_positive"]
    comment: str = Field(default="", max_length=4096)
