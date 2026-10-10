"""Bounded P1 log projections shared with the Go local outbox.

Device identity comes from authentication, never these records.
Unknown fields are rejected so raw tool arguments cannot enter default storage.
"""
from __future__ import annotations

from .aidr_products import LogAgentID
import json
from .aidr_skill_contract import SkillUse
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from .api_errors import ApiError
from .aidr_behavior import Behavior
from .aidr_behavior import AuditPolicy
from .aidr_content import Content, ContentStatus, validate_contents

MAX_BATCH_BYTES = 1 << 20
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Token = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:/@+\-]{1,256}$")]
Position = Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]{0,18})$")]
Generation = Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]{0,19})$")]
Short = Annotated[str, StringConstraints(max_length=256)]
Reason = Annotated[str, StringConstraints(pattern=r"^aidr_[a-z0-9_]{1,75}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def integer_schema(cls, value):
        if type(value) is not int:
            raise ValueError("invalid_schema_version")
        return value


class Message(Contract):
    role: Literal['user', 'assistant']
    phase: Literal['unspecified', 'commentary', 'final']
    policy: AuditPolicy
    contents: list[Content] = Field(max_length=4)
    content_status: ContentStatus

    @model_validator(mode='after')
    def check(self):
        if self.policy.message_schema != 1 or self.policy.capture is None or (self.policy.lifecycle and not self.policy.lifecycle.enabled):
            raise ValueError('message_collection_disabled')
        if self.role == 'user' and self.phase != 'unspecified':
            raise ValueError('message_phase_invalid')
        kind, field = ('prompt', 'message.input') if self.role == 'user' else ('model_response', 'message.output')
        fields = {field, field + '.request', field + '.context'} if self.role == 'user' else {field}
        if any(c.kind != kind or c.source_field not in fields for c in self.contents):
            raise ValueError('message_content_source_invalid')
        validate_contents(self.contents, self.content_status, self.policy)
        return self


class ModelContext(Contract):
    model: Token | None = None
    provider: Token | None = None
    reasoning_effort: Token | None = None
    reasoning_summary: Token | None = None
    source: Literal['codex.turn_context', 'claude.message.model', 'qoder-cli.message.model', 'workbuddy.providerData.model', 'opencode.message']


class Event(Contract):
    model_context: ModelContext | None = None
    user_scope: str | None = Field(default=None, pattern=r'^(0|[1-9][0-9]{0,9})$')
    skill_use: SkillUse | None = None
    schema_version: Literal[1, 2, 3]
    message: Message | None = None
    behavior: Behavior | None = None
    logical_event_id: Hash
    event_id: Hash
    source_id: Hash
    source_instance_id: Hash
    source_seq: Position
    record_offset: Position
    block: int = Field(ge=0, le=4096)
    agent: LogAgentID
    agent_version: Annotated[str, StringConstraints(max_length=80)]
    source: Literal["agent_log"]
    session_id: Short
    turn_id: Short
    native_call_id: Token
    logical_call_id: Hash
    kind: Literal["tool_call", "tool_result", "user_message", "assistant_message"]
    tool: Short
    outcome: Literal["unknown", "success", "error"]
    observed_at: str = Field(max_length=40)
    received_at: str = Field(max_length=40)
    content_digest: Hash
    content_bytes: int = Field(ge=1, le=4 << 20)
    evidence_digest: Hash
    process_relation: Literal["unknown"]

    @model_validator(mode="after")
    def consistent(self):
        if self.model_context:
            if not any(getattr(self.model_context, k) for k in ('model', 'provider', 'reasoning_effort', 'reasoning_summary')):
                raise ValueError('model_context_empty')
            expected = {'codex': 'codex.turn_context', 'claude': 'claude.message.model',
                        'qoder-cli': 'qoder-cli.message.model', 'workbuddy': 'workbuddy.providerData.model', 'opencode': 'opencode.message'}
            if expected.get(self.agent) != self.model_context.source or not self.session_id:
                raise ValueError('model_context_source_invalid')
            if self.agent == 'codex' and not self.turn_id:
                raise ValueError('model_context_turn_missing')
        if self.schema_version == 3:
            if not self.message or self.behavior or self.kind != self.message.role + '_message' or self.tool or self.outcome != 'unknown':
                raise ValueError('message_version_mismatch')
        elif self.message or self.kind not in {'tool_call', 'tool_result'}:
            raise ValueError('message_version_mismatch')
        if (self.schema_version == 1 and self.behavior is not None) or (self.schema_version == 2 and self.behavior is None):
            raise ValueError("behavior_version_mismatch")
        seq, offset = int(self.source_seq), int(self.record_offset)
        if seq > 2**63 - 1 or offset > 2**63 - 1 or seq - offset != self.block:
            raise ValueError("invalid_position")
        if self.kind == "tool_call" and not self.tool:
            raise ValueError("missing_tool")
        if self.skill_use:
            self.skill_use.validate_source(self.agent, self.tool, self.kind, not self.behavior or not self.behavior.policy or self.behavior.policy.enabled)
        for value in (self.observed_at, self.received_at):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.year == 1:
                raise ValueError("invalid_timestamp")
        return self


class Gap(Contract):
    start: Position
    end: Position
    reason_code: Reason
    evidence_digest: Hash | None = None

    @model_validator(mode="after")
    def consistent(self):
        if int(self.start) > int(self.end) or int(self.end) > 2**63 - 1:
            raise ValueError("invalid_gap")
        return self


class Coverage(Contract):
    gaps: list[Gap] | None = Field(max_length=32)
    gap_details_truncated: bool
    status: Literal["complete", "partial", "unavailable"]
    reason_codes: list[Reason] = Field(max_length=32)
    records: int = Field(ge=0, le=64 << 20)
    ignored: int = Field(ge=0, le=64 << 20)
    filtered: int = Field(ge=0, le=64 << 20)
    skipped_bytes: int = Field(ge=0, le=64 << 20)
    bytes: int = Field(ge=0, le=64 << 20)

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "complete" and (self.reason_codes or self.gaps or self.gap_details_truncated):
            raise ValueError("complete_with_gap")
        if self.skipped_bytes > self.bytes:
            raise ValueError("invalid_counts")
        return self


class CallTurn(Contract):
    call: Token
    turn: Short
    ambiguous: bool
    tool: Token | None = None
    completed: bool | None = None
    content_digest: Hash | None = None


class QoderLink(Contract):
    id: Token
    turn: Token


class Cursor(Contract):
    # Accept already-frozen development batches; current clients keep this local.
    qoder_links: list[QoderLink] | None = Field(default=None, max_length=512)
    model_context: ModelContext | None = None
    model_provider: Token | None = None
    model_turn: Token | None = None
    model_header_read: bool | None = None
    context_repair_version: int | None = Field(default=None, ge=0, le=2)
    context_repair: Cursor | None = None
    recovery_gaps: list[Gap] | None = Field(default=None, max_length=32)
    recovery_details_truncated: bool | None = None
    projection_version: int | None = Field(default=None,ge=0,le=2)
    call_turns: list[CallTurn] | None = Field(default=None,max_length=512)
    schema_version: Literal[0, 1]
    parser_version: str = Field(max_length=80)
    source_id: str = Field(max_length=64)
    file_identity: str = Field(max_length=128)
    generation: Generation
    discarding_oversized_record: bool
    discard_start: Position
    offset: Position
    anchor: str = Field(max_length=64)
    session_id: Short
    turn_id: Short
    agent_version: str = Field(max_length=80)
    since: str = Field(max_length=40)
    gap_codes: list[Reason] | None = Field(max_length=32)

    @field_validator('context_repair', mode='before')
    @classmethod
    def bounded_repair(cls, value):
        if isinstance(value, dict) and value.get('context_repair') is not None:
            raise ValueError('nested_context_repair')
        return value

    @model_validator(mode='after')
    def repair_scope(self):
        r = self.context_repair
        if r and (r.source_id != self.source_id or r.file_identity != self.file_identity or int(r.offset) > int(self.offset)):
            raise ValueError('context_repair_scope')
        return self


class CoverageRecord(Contract):
    source_id: Hash
    revision: Position
    cursor: Cursor
    coverage: Coverage

    @model_validator(mode="after")
    def consistent(self):
        c = self.cursor
        if int(self.revision) < 1 or int(self.revision) > 2**63 - 1:
            raise ValueError("invalid_revision")
        if int(c.offset) > 2**63 - 1 or int(c.discard_start) > int(c.offset) or int(c.generation) > 2**64 - 1:
            raise ValueError("invalid_cursor")
        for gap in c.recovery_gaps or []:
            if int(gap.end) > int(c.offset) or gap.evidence_digest is None:
                raise ValueError("invalid_recovery_gap")
        if c.schema_version == 0:
            if self.coverage.status != "unavailable" or c.source_id or int(c.offset) or int(c.generation):
                raise ValueError("uninitialized_cursor")
        elif c.source_id != self.source_id or not int(c.generation) or c.parser_version != "agentlog/1":
            raise ValueError("invalid_cursor")
        return self


class Record(Contract):
    sequence: Position
    kind: Literal["event", "coverage"]
    record_id: str = Field(max_length=85)
    payload: dict


class Batch(Contract):
    schema_version: Literal[1]
    records: list[Record] = Field(min_length=1, max_length=500)


def invalid_batch():
    return ApiError(422, "aidr.invalid_batch", "事件批次格式不符合契约", "Event batch violates the contract")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def parse_batch(raw: bytes) -> tuple[Batch, list[Event | CoverageRecord]]:
    if len(raw) > MAX_BATCH_BYTES:
        raise ApiError(413, "aidr.batch_too_large", "事件批次超过 1 MiB", "Event batch exceeds 1 MiB")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        batch = Batch.model_validate(data)
        parsed = []
        previous = 0
        ids = set()
        for record in batch.records:
            seq = int(record.sequence)
            if seq <= previous or seq > 2**63 - 1 or record.record_id in ids:
                raise ValueError("invalid_sequence")
            previous = seq
            ids.add(record.record_id)
            value = Event.model_validate(record.payload) if record.kind == "event" else CoverageRecord.model_validate(record.payload)
            expected = value.logical_event_id if record.kind == "event" else f"{value.source_id}:{value.revision}"
            if record.record_id != expected:
                raise ValueError("record_identity_mismatch")
            parsed.append(value)
        return batch, parsed
    except (ValueError, TypeError, RecursionError, ValidationError, UnicodeDecodeError) as exc:
        raise invalid_batch() from exc


LOG_SOURCE_FIELDS = ("source_id", "agent", "session_id", "turn_id", "native_call_id", "logical_call_id", "kind", "tool", "outcome", "content_digest")


def logical_projection(event: Event) -> str:
    """Identity-bearing fields only; observation timestamps may differ on replay."""
    values = [getattr(event, name) for name in LOG_SOURCE_FIELDS]
    if event.schema_version == 2:
        values.append(event.behavior.model_dump(exclude_none=True))
    if event.message:
        values.append(event.message.model_dump(exclude_none=True))
    return json.dumps(values, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def same_log_source(stored_payload: str, incoming: Event) -> bool:
    """A replay keeps its first projection when source identity and content match."""
    stored = json.loads(stored_payload)
    return all(stored.get(name) == getattr(incoming, name) for name in LOG_SOURCE_FIELDS)
