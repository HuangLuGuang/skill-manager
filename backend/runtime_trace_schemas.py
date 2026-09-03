from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RUNTIME_TRACE_SCHEMA_VERSION = "runtime-trace@1"
TRACE_EVENT_TYPES = (
    "turn.start",
    "turn.end",
    "step.start",
    "step.end",
    "message.user",
    "context.injected",
    "model.request",
    "model.response",
    "model.error",
    "tool.call",
    "tool.result",
    "tool.error",
    "mcp.call",
    "mcp.result",
    "mcp.error",
    "knowledge.retrieval",
    "policy.decision",
    "approval.requested",
    "approval.resolved",
    "runtime.blocked",
    "runtime.killed",
    "security.finding",
)


class RuntimeTraceCreate(BaseModel):
    schema_version: str = RUNTIME_TRACE_SCHEMA_VERSION
    session_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=128)
    retention_days: int = Field(default=30, ge=1, le=30)


class RuntimeTraceEventInput(BaseModel):
    schema_version: str = RUNTIME_TRACE_SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=64)
    event_time: datetime
    source: str = Field(min_length=1, max_length=32)
    type: str = Field(min_length=1, max_length=64)
    turn_id: str | None = Field(default=None, max_length=128)
    step_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    call_id: str | None = Field(default=None, max_length=128)
    parent_call_id: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=32)
    tool_name: str | None = Field(default=None, max_length=256)
    duration_ms: float | None = Field(default=None, ge=0)
    risk_codes: list[str] = Field(default_factory=list, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    redacted_payload: dict[str, Any] | None = None


class RuntimeTraceBatchCreate(BaseModel):
    schema_version: str = RUNTIME_TRACE_SCHEMA_VERSION
    batch_id: str = Field(min_length=1, max_length=64)
    events: list[RuntimeTraceEventInput] = Field(min_length=1, max_length=1000)


class RuntimeTraceExportCreate(BaseModel):
    redaction_level: Literal["redacted", "raw"] = "redacted"
    format: Literal["json", "pdf"] = "json"
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    raw_authorization_token: str | None = Field(default=None, min_length=32, max_length=512)
    acknowledge_sensitive_content: bool = False


class RuntimeTraceRawExportAuthorizationCreate(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    acknowledge_sensitive_content: Literal[True]


class RuntimeTraceInternalEvent(BaseModel):
    trace_id: str | None = None
    tenant_id: str = "default"
    agent_id: str | None = None
    session_id: str
    owner_user_id: int | None = None
    owner_group_id: int | None = None
    source: str
    type: str
    event_id: str | None = None
    event_time: datetime | None = None
    turn_id: str | None = None
    step_id: str | None = None
    request_id: str | None = None
    call_id: str | None = None
    parent_call_id: str | None = None
    status: str | None = None
    tool_name: str | None = None
    duration_ms: float | None = None
    risk_codes: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    redacted_payload: dict[str, Any] | None = None
