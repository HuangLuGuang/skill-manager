"""Latest plugin observations and retained readable baselines, never authority."""
from .aidr_products import HookAgentID
import json
import time
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from .aidr_behavior import Strict
from .api_errors import ApiError
from .sqlite_db import Base


class PluginStatusRow(Base):
    __tablename__ = "aidr_plugin_status"
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), primary_key=True)
    stream_id = Column(String(32), primary_key=True)
    scope_id = Column(String(64), primary_key=True)
    sequence = Column(Integer, nullable=False)
    received_at = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False)
    baseline = Column(Text, nullable=False)
    change = Column(Text, nullable=False)


class PluginStatus(Strict):
    agent: HookAgentID
    host_version: str = Field(max_length=100)
    version_status: Literal["unverified", "adapter_target", "adapter_available", "interface_compatible"]
    installed: bool | None
    enabled: bool | None
    plugin_version: str = Field(max_length=80)
    plugin_id: str = Field(max_length=256)
    source_code: Literal["aidr_plugin_source_unreadable", "aidr_plugin_multiple_sources", "aidr_plugin_not_installed", "aidr_plugin_disabled", "aidr_plugin_enabled_trust_unknown"]
    hook_trust: Literal["unknown"]
    reported_at: str = Field(min_length=20, max_length=40)
    receiver_code: Literal["aidr_hook_receiver_not_checked", "aidr_hook_receiver_unavailable", "aidr_hook_healthy"]
    configuration_digest: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    source_kind: Literal["unknown", "native_install_path", "declared_local_source", "settings"]
    files_code: Literal["aidr_plugin_files_unknown", "aidr_plugin_files_unreadable", "aidr_plugin_files_observed"]
    files_digest: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def consistent(self):
        unreadable = self.source_code in ("aidr_plugin_source_unreadable", "aidr_plugin_multiple_sources")
        if unreadable and (self.installed is not None or self.enabled is not None or self.configuration_digest):
            raise ValueError("aidr_plugin_status_inconsistent")
        if not unreadable and (self.installed is None or self.enabled is None or not self.configuration_digest):
            raise ValueError("aidr_plugin_status_inconsistent")
        if (self.files_code == "aidr_plugin_files_observed") != bool(self.files_digest):
            raise ValueError("aidr_plugin_status_inconsistent")
        if self.source_code == "aidr_plugin_disabled" and (self.installed is not True or self.enabled is not False):
            raise ValueError("aidr_plugin_status_inconsistent")
        if self.source_code == "aidr_plugin_enabled_trust_unknown" and (self.installed is not True or self.enabled is not True):
            raise ValueError("aidr_plugin_status_inconsistent")
        if self.source_code == "aidr_plugin_not_installed" and self.installed is not False:
            raise ValueError("aidr_plugin_status_inconsistent")
        if self.files_digest and (self.installed is not True or self.source_kind == "unknown"):
            raise ValueError("aidr_plugin_status_inconsistent")
        return self


class PluginReport(Strict):
    schema_version: Literal[1]
    stream_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    receiver_instance: str = Field(pattern=r"^[0-9a-f]{32}$")
    report_sequence: str = Field(pattern=r"^[1-9][0-9]{0,17}$")
    status: PluginStatus


def receive(db, client_id, report):
    table = PluginStatusRow
    db.connection().exec_driver_sql("UPDATE aidr_plugin_status SET sequence=sequence WHERE 0")
    key = (client_id, report.stream_id, report.status.scope_digest)
    row = db.get(table, key)
    ack = {"code": "aidr_plugin_report_received", "stream_id": report.stream_id, "report_sequence": report.report_sequence}
    if row is not None and row.sequence >= int(report.report_sequence):
        db.rollback()
        return ack
    if row is None and db.query(table).filter_by(client_id=client_id).count() >= 64:
        raise ApiError(429, "aidr.plugin_status_capacity", "插件来源状态达到容量上限", "Plugin source status capacity reached")
    now = int(time.time())
    current = report.status.model_dump()
    baseline = json.loads(row.baseline) if row else {}
    change = json.loads(row.change) if row else {"code": "aidr_plugin_baseline_unknown", "fields": [], "received_at": None}
    if current["configuration_digest"]:
        fields = []
        if baseline:
            if current["configuration_digest"] != baseline["configuration_digest"]:
                fields.append("native_configuration")
            if current["host_version"] and baseline["host_version"] and current["host_version"] != baseline["host_version"]:
                fields.append("host_version")
            if current["files_digest"] and baseline.get("files_digest") and current["source_kind"] == baseline["source_kind"] and current["files_digest"] != baseline["files_digest"]:
                fields.append("declared_files")
            if fields:
                change = {"code": "aidr_plugin_drift_changed", "fields": fields, "received_at": str(now),
                          "before": baseline, "after": current}
        else:
            change = {"code": "aidr_plugin_baseline_established", "fields": [], "received_at": str(now)}
        # A transient file read failure preserves the last comparable file sample.
        retained = current.copy()
        retained["files_reported_at"] = current["reported_at"] if current["files_digest"] else None
        if baseline and not current["files_digest"] and baseline["configuration_digest"] == current["configuration_digest"]:
            retained["files_digest"] = baseline.get("files_digest", "")
            retained["files_code"] = baseline["files_code"]
            retained["files_reported_at"] = baseline.get("files_reported_at")
        baseline = retained
    if row is None:
        row = table(client_id=key[0], stream_id=key[1], scope_id=key[2])
        db.add(row)
    row.sequence = int(report.report_sequence)
    row.received_at = now
    row.payload = json.dumps(report.model_dump(), separators=(",", ":"))
    row.baseline = json.dumps(baseline, separators=(",", ":"))
    row.change = json.dumps(change, separators=(",", ":"))
    db.commit()
    return ack


def view(db, client_id):
    now = int(time.time())
    rows = db.query(PluginStatusRow).filter_by(client_id=client_id).order_by(PluginStatusRow.received_at.desc(), PluginStatusRow.scope_id).limit(21).all()
    return {"evidence_type": "plugin_configuration_report", "checked_at": str(now), "truncated": len(rows) > 20,
            "items": [{"report": json.loads(r.payload), "change": json.loads(r.change), "received_at": str(r.received_at),
                       "stale": now-r.received_at > 180} for r in rows[:20]]}
