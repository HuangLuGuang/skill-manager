"""Immutable plugin evidence. Host claims do not authorize OS operations."""
from .aidr_products import HookAgentID, BY_ID
import hashlib
import json
from .aidr_skill_contract import SkillUse
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import lambda_stmt
from sqlalchemy.dialects.sqlite import insert

from . import aidr_policy
from .aidr_behavior import AuditPolicy, Behavior, Strict, safe
from .aidr_content import Content, ContentStatus, validate_contents
from .aidr_contract import _unique_object, invalid_batch
from .aidr_models import AidrHookBatch, AidrHookEvent
from .aidr_operations import stamp
from .api_errors import ApiError

_BATCH_INSERT = lambda_stmt(lambda: insert(AidrHookBatch.__table__).on_conflict_do_nothing())
_EVENT_INSERT = lambda_stmt(lambda: insert(AidrHookEvent.__table__).on_conflict_do_nothing())

class HostContext(Strict):
    model: str = Field(default='', max_length=256)
    cwd: str = Field(default='', max_length=512)
    workspace_roots: list[str] = Field(default_factory=list, max_length=8)
    redacted: bool = False
    truncated: bool = False

    @model_validator(mode='after')
    def bounded(self):
        safe(self.model, 256, False)
        safe(self.cwd, 512, False)
        for root in self.workspace_roots:
            safe(root, 512, False)
        return self


from .aidr_command_rules import CommandObservation


class ControlDecision(Strict):
    decision: Literal['allow', 'deny', 'ask']
    rule_id: str = Field(default='', pattern=r'^$|^[A-Za-z0-9_-]{1,64}$')
    matched_rule_ids: list[str] = Field(max_length=128)
    policy_revision: str = Field(default='', pattern=r'^$|^[1-9][0-9]{0,17}$')
    code: str = Field(pattern=r'^aidr_hook_[a-z0-9_]{1,64}$')
    unresolved: bool = False

    @model_validator(mode='after')
    def bounded(self):
        import re
        if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', item) for item in self.matched_rule_ids):
            raise ValueError('hook_control_rule_invalid')
        return self


class HookEvent(Strict):
    control_decision: ControlDecision | None = None
    command_match: CommandObservation | None = None
    context: HostContext | None = None
    skill_use: SkillUse | None = None
    schema_version: Literal[1, 2, 3]
    agent: HookAgentID
    hook_event: str = Field(max_length=32)
    kind: str = Field(max_length=32)
    session_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(default="", max_length=256)
    native_call_id: str = Field(default="", max_length=256)
    native_agent_id: str = Field(default="", max_length=256)
    tool: str = Field(default="", max_length=256)
    behavior: Behavior | None = None
    policy: AuditPolicy
    contents: list[Content] | None = Field(default=None, max_length=4)
    content_status: ContentStatus | None = None
    input_digest: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    process_relation: Literal["unknown"]

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.control_decision and self.kind != 'tool.pre':
            raise ValueError('hook_control_decision_scope_invalid')
        if self.command_match and (self.kind != 'tool.pre' or not self.input_digest):
            raise ValueError('hook_command_observation_scope_invalid')
        if self.context and self.policy.enabled:
            from .aidr_redaction import redact_values
            if any(redact_values(v) != v for v in [self.context.model, self.context.cwd, *self.context.workspace_roots]):
                raise ValueError('hook_context_redaction_required')
        if BY_ID[self.agent]['hook_events'].get(self.hook_event) != self.kind:
            raise ValueError("hook_unsupported")
        for value in (self.session_id, self.turn_id, self.native_call_id, self.native_agent_id, self.tool):
            if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("hook_identity_invalid")
        tool_event = self.kind.startswith(("tool.", "permission."))
        if tool_event != (self.behavior is not None) or tool_event != bool(self.tool):
            raise ValueError("hook_projection_invalid")
        if self.schema_version == 1 and (self.policy.capture is not None or self.contents is not None or self.content_status is not None):
            raise ValueError('hook_content_version_invalid')
        if self.schema_version < 3 and self.policy.lifecycle is not None:
            raise ValueError('hook_lifecycle_version_invalid')
        if self.schema_version == 3 and (self.policy.lifecycle is None or not self.policy.lifecycle.enabled):
            raise ValueError('hook_collection_disabled')
        if self.schema_version >= 2:
            if self.policy.capture is None or self.content_status is None:
                raise ValueError('hook_content_policy_missing')
            validate_contents(self.contents, self.content_status, self.policy)
            if self.contents and (self.kind != 'turn.submit' or any(item.kind != 'prompt' for item in self.contents)):
                raise ValueError('hook_content_source_invalid')
        if self.behavior and (self.behavior.version != self.schema_version + 2 or self.behavior.policy != self.policy):
            raise ValueError("hook_policy_mismatch")
        if self.policy.version == "0" and (not self.policy.enabled or self.policy.receipt):
            raise ValueError("hook_policy_invalid")
        if self.kind in {"tool.pre", "permission.request", "permission.denied"} and self.behavior.method == "result_fields":
            raise ValueError("hook_call_invalid")
        if self.kind in {"tool.post", "tool.failure"} and self.behavior.method != "result_fields":
            raise ValueError("hook_result_invalid")
        if self.skill_use:
            self.skill_use.validate_source(self.agent, self.tool, self.kind, self.policy.enabled)
        return self


class BridgeProcess(Strict):
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    pid: str = Field(pattern=r"^[1-9][0-9]{0,9}$")
    pidversion: str = Field(pattern=r"^[1-9][0-9]{0,9}$")
    start_us: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    method: Literal["macos_socket_audit_token_sysctl"]
    role: Literal["ipc_bridge"]

    @model_validator(mode="after")
    def bounds(self):
        if int(self.pid) >= 2**31 or int(self.pidversion) >= 2**32 or int(self.start_us) >= 2**63:
            raise ValueError("hook_bridge_identity_invalid")
        return self


class HookRecord(Strict):
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_seq: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    user_scope: str = Field(pattern=r"^(0|[1-9][0-9]{0,9})$")
    received_at: str = Field(max_length=40)
    event: HookEvent
    receiver_instance: str = Field(default="", pattern=r"^$|^[0-9a-f]{32}$")
    bridge_process: BridgeProcess | None = None


class HookBatch(Strict):
    schema_version: Literal[1]
    client_id: str = Field(min_length=1, max_length=128)
    stream_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    records: list[HookRecord] = Field(min_length=1, max_length=100)


def parse(raw):
    try:
        batch = HookBatch.model_validate(json.loads(raw, object_pairs_hook=_unique_object))
        previous, ids = 0, set()
        for record in batch.records:
            seq = int(record.source_seq)
            if not previous < seq < 2**63 or record.event_id in ids:
                raise ValueError("hook_sequence_invalid")
            stamp(record.received_at)
            ids.add(record.event_id)
            previous = seq
        return batch
    except (ValueError, TypeError, RecursionError, UnicodeDecodeError) as exc:
        raise invalid_batch() from exc


def save(db, device, raw):
    batch = parse(raw)
    if batch.client_id != device.client_id:
        raise ApiError(403, "aidr.device_binding_mismatch", "凭证绑定的设备不匹配", "Credential device binding mismatch")
    digest = hashlib.sha256(raw).hexdigest()
    prepared = []
    for record in batch.records:
        projected = record.model_dump(exclude_none=True)
        if not record.receiver_instance:
            projected.pop("receiver_instance", None)
        payload = json.dumps(projected, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        prepared.append(dict(client_id=batch.client_id, stream_id=batch.stream_id, event_id=record.event_id,
            source_seq=int(record.source_seq), content_hash=hashlib.sha256(payload.encode()).hexdigest(), payload_json=payload))
    inserted = db.execute(_BATCH_INSERT, dict(client_id=batch.client_id, stream_id=batch.stream_id,
        digest=digest, record_count=len(batch.records)))
    if inserted.rowcount:
        receipts = aidr_policy.load_receipts(db, [record.event.policy for record in batch.records])
        for record in batch.records:
            # Validate the server-issued policy receipt, not the client's claim.
            aidr_policy.validate_receipt(db, batch.client_id, batch.stream_id, int(record.source_seq), record.event.policy, receipts=receipts)
        event_ids = [record.event_id for record in batch.records]
        existing = {row.event_id: row for row in db.query(AidrHookEvent).filter(
            AidrHookEvent.client_id == batch.client_id, AidrHookEvent.stream_id == batch.stream_id,
            AidrHookEvent.event_id.in_(event_ids)).all()}
        new = [values for values in prepared if values['event_id'] not in existing]
        if new:
            db.execute(_EVENT_INSERT, new)
            existing.update({row.event_id: row for row in db.query(AidrHookEvent).filter(
                AidrHookEvent.client_id == batch.client_id, AidrHookEvent.stream_id == batch.stream_id,
                AidrHookEvent.event_id.in_([values['event_id'] for values in new])).all()})
        for values in prepared:
            row = existing.get(values['event_id'])
            if row is None or row.content_hash != values['content_hash']:
                db.rollback()
                raise ApiError(409, "aidr.hook_event_conflict", "插件事件身份或序号冲突", "Plugin event identity or sequence conflict")
        from .aidr_skill_usage import merge_many
        merge_many(db, "hook", [existing[values['event_id']] for values in new])
    db.commit()
    return {"schema_version": 1, "client_id": batch.client_id, "stream_id": batch.stream_id, "digest": digest, "accepted": len(batch.records), "durable": True}
