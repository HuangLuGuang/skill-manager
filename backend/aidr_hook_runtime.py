"""Bounded receiver telemetry, separate from immutable audit and authority."""
import json
import time
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import insert

from .aidr_behavior import Strict, AuditPolicy
from .api_errors import ApiError
from .sqlite_db import Base


class HookRuntimeRow(Base):
    __tablename__ = "aidr_hook_runtime"
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), primary_key=True)
    stream_id = Column(String(32), primary_key=True)
    receiver_instance = Column(String(32), primary_key=True)
    sequence = Column(Integer, nullable=False)
    received_at = Column(Integer, nullable=False, index=True)
    payload = Column(Text, nullable=False)


class RuntimeReport(Strict):
    schema_version: Literal[1]
    stream_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    receiver_instance: str = Field(pattern=r"^[0-9a-f]{32}$")
    report_sequence: str = Field(pattern=r"^[1-9][0-9]{0,17}$")
    control_mode: Literal["audit", "plugin_pre_tool"]
    control_revision: str = Field(default="", pattern=r"^$|^[1-9][0-9]{0,17}$")
    control_code: Literal["aidr_hook_audit_only", "aidr_hook_policy_missing", "aidr_hook_policy_ready", "aidr_hook_policy_expired"]
    queued_records: int = Field(ge=0, le=100000)
    upload_code: Literal["", "aidr_upload_reporting_paused", "aidr_upload_auth_rejected",
                         "aidr_upload_transport", "aidr_upload_server_unavailable",
                         "aidr_upload_request_invalid", "aidr_upload_response_invalid",
                         "aidr_upload_request_rejected", "aidr_hook_ack_invalid"] | None = None
    next_upload_at: str | None = Field(default=None, max_length=40)
    last_event_ack_at: str | None = Field(default=None, max_length=40)
    content_schema: Literal[2] | None = None
    lifecycle_schema: Literal[1] | None = None
    audit_suppressed_recent: int | None = Field(default=None, ge=0, le=1000000)
    audit_policy: AuditPolicy | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.control_mode == "audit":
            valid = self.control_code == "aidr_hook_audit_only" and not self.control_revision
        else:
            valid = (self.control_code == "aidr_hook_policy_missing" and not self.control_revision) or (
                self.control_code in ("aidr_hook_policy_ready", "aidr_hook_policy_expired") and bool(self.control_revision))
        if not valid:
            raise ValueError("aidr_hook_runtime_inconsistent")
        from .aidr_operations import stamp
        for value in (self.next_upload_at, self.last_event_ack_at):
            if value:
                stamp(value)
        if self.next_upload_at and not self.upload_code:
            raise ValueError("aidr_hook_runtime_upload_inconsistent")
        if (self.content_schema is None) != (self.audit_policy is None) or (self.audit_policy is not None and self.audit_policy.capture is None):
            raise ValueError("aidr_hook_runtime_content_inconsistent")
        if (self.lifecycle_schema is not None) != (self.audit_policy is not None and self.audit_policy.lifecycle is not None):
            raise ValueError('aidr_hook_runtime_lifecycle_inconsistent')
        if self.audit_suppressed_recent is not None and self.lifecycle_schema is None:
            raise ValueError('aidr_hook_runtime_lifecycle_inconsistent')
        return self


def receive(db, client_id, report):
    now = int(time.time())
    # The write lock serializes capacity checks and reports from concurrent receivers.
    db.connection().exec_driver_sql("UPDATE aidr_hook_runtime SET sequence=sequence WHERE 0")
    table = HookRuntimeRow
    db.query(table).filter_by(client_id=client_id).filter(table.received_at < now - 7 * 86400).delete()
    key = dict(client_id=client_id, stream_id=report.stream_id, receiver_instance=report.receiver_instance)
    existing = db.get(table, (client_id, report.stream_id, report.receiver_instance))
    if existing is None and db.query(table).filter_by(client_id=client_id).count() >= 256:
        raise ApiError(429, "aidr.hook_runtime_capacity", "接收器状态记录达到容量上限", "Receiver status capacity reached")
    values = dict(sequence=int(report.report_sequence), received_at=now,
                  payload=json.dumps(report.model_dump(exclude_none=True), separators=(",", ":")))
    stmt = insert(table).values(**key, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=list(key), set_=values,
                                         where=table.sequence < int(report.report_sequence)))
    db.commit()
    return {"code": "aidr_hook_runtime_received", "receiver_instance": report.receiver_instance,
            "report_sequence": report.report_sequence}


def view(db, client_id, revision):
    now = int(time.time())
    rows = db.query(HookRuntimeRow).filter_by(client_id=client_id).order_by(
        HookRuntimeRow.received_at.desc(), HookRuntimeRow.receiver_instance).limit(21).all()
    items = []
    for row in rows[:20]:
        payload = json.loads(row.payload)
        items.append({**payload, "received_at": str(row.received_at),
                      "code": "aidr_hook_runtime_recent" if now - row.received_at <= 90 else "aidr_hook_runtime_stale",
                      "matches_published_revision": bool(revision != "0" and payload["control_revision"] == revision)})
    return {"evidence_type": "receiver_self_report", "checked_at": str(now), "items": items,
            "truncated": len(rows) > 20, "stale_after_seconds": 90}
