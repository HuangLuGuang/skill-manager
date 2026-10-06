"""Immutable plugin evidence. Host claims do not authorize OS operations."""
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy.dialects.sqlite import insert

from . import aidr_policy
from .aidr_behavior import AuditPolicy, Behavior, Strict
from .aidr_content import Content, ContentStatus, validate_contents
from .aidr_contract import _unique_object, invalid_batch
from .aidr_models import AidrHookBatch, AidrHookEvent
from .aidr_operations import stamp
from .api_errors import ApiError

KINDS = {
    "SessionStart": "session.start", "SessionEnd": "session.end",
    "UserPromptSubmit": "turn.submit", "PreToolUse": "tool.pre",
    "PostToolUse": "tool.post", "PostToolUseFailure": "tool.failure",
    "PermissionRequest": "permission.request", "PermissionDenied": "permission.denied",
    "SubagentStart": "agent.start", "SubagentStop": "agent.stop",
    "PreCompact": "context.compact.start", "PostCompact": "context.compact.end",
    "Stop": "turn.stop", "Interrupt": "turn.interrupt", "Notification": "notification",
    "TaskCompleted": "task.completed", "TeammateIdle": "agent.idle",
}
CLAUDE_ONLY = {"PostToolUseFailure", "PermissionDenied", "Notification", "TaskCompleted", "TeammateIdle"}


class HookEvent(Strict):
    schema_version: Literal[1, 2, 3]
    agent: Literal["claude", "codex"]
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
        if KINDS.get(self.hook_event) != self.kind or (self.agent == "codex" and self.hook_event in CLAUDE_ONLY) or (self.agent == "claude" and self.hook_event == "Interrupt"):
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
    inserted = db.execute(insert(AidrHookBatch).values(client_id=batch.client_id, stream_id=batch.stream_id, digest=digest, record_count=len(batch.records)).on_conflict_do_nothing())
    if inserted.rowcount:
        for record in batch.records:
            # Validate the server-issued policy receipt, not the client's claim.
            aidr_policy.validate_receipt(db, batch.client_id, batch.stream_id, int(record.source_seq), record.event.policy)
            projected = record.model_dump(exclude_none=True)
            if not record.receiver_instance:
                projected.pop("receiver_instance", None)
            payload = json.dumps(projected, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            db.execute(insert(AidrHookEvent).values(client_id=batch.client_id, stream_id=batch.stream_id, event_id=record.event_id, source_seq=int(record.source_seq), content_hash=content_hash, payload_json=payload).on_conflict_do_nothing())
            existing = db.query(AidrHookEvent).filter_by(client_id=batch.client_id, stream_id=batch.stream_id, event_id=record.event_id).first()
            if existing is None or existing.content_hash != content_hash:
                db.rollback()
                raise ApiError(409, "aidr.hook_event_conflict", "插件事件身份或序号冲突", "Plugin event identity or sequence conflict")
    db.commit()
    return {"schema_version": 1, "client_id": batch.client_id, "stream_id": batch.stream_id, "digest": digest, "accepted": len(batch.records), "durable": True}
