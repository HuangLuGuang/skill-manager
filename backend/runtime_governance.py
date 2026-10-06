"""Bounded device observations and tasks for the existing client worker."""
import json
import hashlib
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from sqlalchemy import Column, ForeignKey, String, Text, DateTime, Boolean
from sqlalchemy.dialects.sqlite import insert

from . import models, aidr_onboarding
from .sqlite_db import Base
from .api_errors import ApiError


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Host(Strict):
    agent: Literal["claude", "codex"]
    host_version: str = Field(max_length=100)
    plugin_version: str | None = Field(default=None, max_length=80)
    version_status: Literal["adapter_target", "unverified"]
    installed: bool | None
    enabled: bool | None
    hook_trust: Literal["unknown", "trusted", "needs_review", "managed"]
    access_mode: Literal["ordinary", "managed"] = "ordinary"
    reported_at: str = Field(max_length=40)
    source_code: str = Field(max_length=100, pattern=r"^aidr_[a-z0-9_]+$")


class ReceiverSupervision(Strict):
    attempts: int = Field(ge=0, le=4294967295)
    retry_count: int = Field(ge=0, le=4294967294)
    mode: Literal["none", "fixed", "continuous"]
    suspended: bool
    code: str = Field(max_length=100, pattern=r"^aidr_[a-z0-9_]+$")
    observed_at: str = Field(max_length=40)
    next_retry_at: str | None = Field(default=None, max_length=40)
    last_failure: str | None = Field(default=None, max_length=100, pattern=r"^aidr_[a-z0-9_]+$")
    last_failure_at: str | None = Field(default=None, max_length=40)


class ChannelReport(Strict):
    mode: Literal["audit", "intercept"] | None = None
    state: Literal["disabled", "starting", "running", "draining", "stopped", "failed", "waiting_authorization", "unsupported", "unknown"]
    code: str = Field(max_length=100, pattern=r"^aidr_[a-z0-9_]+$")
    enabled: bool | None = None
    policy_version: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+(?::[0-9]+)?$")
    reported_at: str = Field(max_length=40)
    transport_code: str | None = Field(default=None, max_length=100, pattern=r"^$|^aidr_[a-z0-9_]+$")
    queued_records: int | None = Field(default=None, ge=0, le=3000000)
    last_ack_at: str | None = Field(default=None, max_length=40)
    coverage_codes: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("reported_at", "last_ack_at")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("aidr_runtime_timestamp_invalid")
        return value

    @field_validator("coverage_codes")
    @classmethod
    def stable_codes(cls, values):
        import re
        if any(not re.fullmatch(r"aidr_[a-z0-9_]{1,90}", value) for value in values):
            raise ValueError("aidr_runtime_code_invalid")
        return values


class ChannelReports(Strict):
    logs: ChannelReport | None = None
    hooks: ChannelReport | None = None
    system: ChannelReport | None = None


class Report(Strict):
    protocol: Literal[0, 1, 2, 3, 4]
    plugin_version: str = Field(max_length=80)
    enabled: bool | None = None
    managed_task: str = Field(default="0", pattern=r"^[0-9]{1,18}$")
    receiver_code: str = Field(max_length=100, pattern=r"^aidr_[a-z0-9_]+$")
    hosts: list[Host] = Field(max_length=2)
    queued_records: int | None = Field(default=None, ge=0, le=3000000)
    last_report: str | None = Field(default=None, max_length=40)
    transport_code: str | None = Field(default=None, max_length=100, pattern=r"^$|^aidr_[a-z0-9_]+$")
    upload_code: str | None = Field(default=None, max_length=100, pattern=r"^$|^aidr_[a-z0-9_]+$")
    control_mode: Literal["audit", "plugin_pre_tool"] | None = None
    control_revision: str | None = Field(default=None, max_length=80)
    hook_sequence: str | None = Field(default=None, pattern=r"^[0-9]{1,20}$")
    audit_policy_version: str | None = Field(default=None, max_length=80)
    audit_redaction_enabled: bool | None = None
    policy_version: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+(?::[0-9]+)?$")
    policy_received_at: str | None = Field(default=None, max_length=40)
    policy_applied_at: str | None = Field(default=None, max_length=40)
    policy_checked_at: str | None = Field(default=None, max_length=40)
    policy_code: str | None = Field(default=None, max_length=100, pattern=r"^aidr_[a-z0-9_]+$")
    receiver_supervision: ReceiverSupervision | None = None
    channels: ChannelReports | None = None

    @model_validator(mode="after")
    def channel_protocol(self):
        if self.protocol not in (3, 4) and (self.channels is not None or self.policy_version and ":" in self.policy_version):
            raise ValueError("aidr_runtime_channel_protocol_required")
        if self.channels:
            if self.channels.logs and self.channels.logs.mode is not None:
                raise ValueError("aidr_runtime_logs_mode_unsupported")
            if self.protocol != 4 and any(channel and channel.mode is not None for channel in (self.channels.hooks, self.channels.system)):
                raise ValueError("aidr_runtime_mode_protocol_required")
        return self


class Action(Strict):
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    action: Literal["install", "upgrade", "enable", "disable", "inspect"]
    agent: Literal["", "claude", "codex"] = ""
    plugin_version: str = Field(min_length=1, max_length=80)


class Observation(Base):
    __tablename__ = "client_runtime_governance"
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), primary_key=True)
    report_json = Column(Text, nullable=False)
    reported_at = Column(DateTime, nullable=False)
    supports_tasks = Column(Boolean, default=False, nullable=False)


def record(db, client_id, report):
    values = dict(client_id=client_id, report_json=json.dumps(report.model_dump(), separators=(",", ":")), reported_at=datetime.utcnow(), supports_tasks=report.protocol in (1, 2, 3, 4))
    db.execute(insert(Observation).values(**values).on_conflict_do_update(
        index_elements=[Observation.client_id], set_={"report_json": values["report_json"], "reported_at": values["reported_at"], "supports_tasks": values["supports_tasks"]}))


def hook_target(target):
    channels = target.get("channels")
    return target["enabled"] and (channels is None or channels["hooks"])


def channel_health(requested, target_version, observation, stale):
    """Policy expectation and per-channel evidence are separate facts."""
    state, severity = 'policy_unknown', 'info'
    if requested is False:
        state = 'not_requested'
        if observation and not stale and (observation.get('enabled') is True or observation.get('state') in ('running', 'starting', 'waiting_authorization')):
            if observation.get('policy_version') == target_version:
                state, severity = 'disable_not_applied', 'warning'
            else:
                state = 'awaiting_stop'
    elif requested is True:
        if not observation:
            state, severity = 'unreported', 'warning'
        elif observation.get('policy_version') != target_version:
            state = 'awaiting_application'
        elif stale:
            state, severity = 'stale', 'warning'
        elif observation.get('enabled') is not True:
            state = 'awaiting_application'
        else:
            state = observation['state']
            severity = 'warning' if state in ('failed', 'stopped', 'disabled', 'unsupported', 'waiting_authorization') else 'info'
    return {'state': state, 'code': 'aidr_channel_' + state, 'severity': severity}


def channel_view(policy, report):
    from datetime import timezone
    target = policy["runtime_governance"]
    explicit = target.get("channels")
    actual = (report or {}).get("channels") or {}
    output = {}
    for name in ("logs", "hooks", "system"):
        requested = None if not policy["runtime_governance_configured"] else bool(target["enabled"] and (explicit[name] if explicit is not None else name == "hooks"))
        observation = actual.get(name)
        observed_at = observation.get("reported_at") if observation else None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(observed_at.replace("Z", "+00:00")) if observation else None
        stale = age is None or age < timedelta(seconds=-5) or age > timedelta(seconds=30)
        health = channel_health(requested, policy["runtime_governance_version"], observation, stale)
        mode = (target.get("modes") or {}).get(name)
        mode_matches = mode is None or bool(observation and observation.get("mode") == mode)
        if requested and mode and (report or {}).get("protocol", 0) < 4:
            health = {'state': 'mode_upgrade_required', 'code': 'aidr_channel_mode_upgrade_required', 'severity': 'warning'}
        elif requested and not mode_matches:
            health = {'state': 'mode_pending', 'code': 'aidr_channel_mode_pending', 'severity': 'warning'}
        if not policy["runtime_governance_configured"]:
            health = {'state': 'not_configured', 'code': 'aidr_channel_not_configured', 'severity': 'info'}
        output[name] = {"target_enabled": requested, "target_mode": mode, "target_version": policy["runtime_governance_version"],
                        "report": observation, "stale": stale, "health": health,
                        "code": "aidr_channel_unreported" if not observation else observation["code"],
                        "applied": bool(mode_matches and observation and not stale and observation.get("policy_version") == policy["runtime_governance_version"] and observation.get("enabled") == requested and observation["state"] in (("running",) if requested else ("disabled", "draining", "stopped")))}
    return output


def compatibility_view(report, supports_tasks, stale):
    """Protocol evidence, never an inference from a marketing version string."""
    protocol = report.get('protocol') if report else None
    known_protocol = type(protocol) is int and protocol in (0, 1, 2, 3, 4)
    observed = {'task_control': bool(supports_tasks) if report else None,
                'runtime_policy': protocol in (2, 3, 4) if known_protocol else None,
                'channel_policy': protocol in (3, 4) if known_protocol else None}
    reported_state = 'unknown' if not known_protocol else 'legacy' if protocol not in (3, 4) else 'partial' if not supports_tasks else 'reported_current'
    return {'state': 'unknown' if stale else reported_state, 'reported_state': reported_state,
            'protocol': protocol, 'current': {key: None if stale else value for key, value in observed.items()},
            'observed': observed, 'stale': stale, 'evidence_type': 'client_protocol_report'}


def view(db, client_id):
    from .client_governance import policy_view
    policy = policy_view(db, client_id)
    row = db.get(Observation, client_id)
    tasks = db.query(models.ClientTask).filter_by(client_id=client_id, task_type="aidr_plugin_action").order_by(models.ClientTask.id.desc()).limit(20).all()
    report = json.loads(row.report_json) if row else None
    stale = not row or datetime.utcnow()-row.reported_at > timedelta(seconds=30)
    client = db.query(models.ManagedClient).filter_by(client_id=client_id).first()
    compatibility = compatibility_view(report, bool(row and row.supports_tasks), stale)
    compatibility["reported_at"] = row.reported_at.isoformat()+"Z" if row else None
    return {"report": report,
            "client_version": client.client_version if client else None,
            "compatibility": compatibility,
            "onboarding": aidr_onboarding.view(db, client_id, policy, report, stale, compatibility),
            "channels_supported": bool(report and report.get("protocol") in (3, 4)),
            "channels": channel_view(policy, report),
            "target": policy["runtime_governance"],
            "target_configured": policy["runtime_governance_configured"],
            "target_version": policy["runtime_governance_version"],
            "supports_tasks": bool(row and row.supports_tasks),
            "reported_at": row.reported_at.isoformat()+"Z" if row else None,
            "stale": stale,
            "tasks": [{"id": str(t.id), "status": t.status, "error_code": t.error,
                       "payload": json.loads(t.payload_json), "created_at": t.created_at.isoformat()+"Z"} for t in tasks]}


def error(status, code, zh, en):
    raise ApiError(status, "aidr."+code, zh, en)


def create(db, client, payload):
    action = Action.model_validate(payload)
    from .client_governance import policy_view
    if action.action in {"enable", "disable"} and policy_view(db, client.client_id)["runtime_governance_configured"]:
        error(409, "runtime_policy_managed", "请在客户端策略中配置运行目标", "Configure the runtime target in client policies")
    if (action.action in {"install", "upgrade", "inspect"}) != bool(action.agent):
        error(422, "runtime_target_invalid", "请核对目标宿主", "Check the target host")
    # Serialize task creation per device, using the existing SQLite transaction.
    db.connection().exec_driver_sql("UPDATE managed_clients SET id=id WHERE client_id=?", (client.client_id,))
    key = f"aidr-runtime:{client.client_id}:{action.request_id}"
    prior = db.query(models.ClientTask).filter_by(request_key=key).first()
    if prior:
        original = json.loads(prior.payload_json)
        if any(original.get(k) != v for k,v in action.model_dump().items()):
            error(409, "runtime_request_conflict", "请求标识已用于其他操作", "Request identity already belongs to another operation")
        return prior
    observation = db.get(Observation, client.client_id)
    report = Report.model_validate_json(observation.report_json) if observation else None
    if not report or report.protocol not in (1, 2, 3, 4) or not observation.supports_tasks:
        error(409, "runtime_client_unsupported", "客户端尚未报告远程插件管理能力，请升级并连接", "Upgrade and connect a client that reports remote plugin management support")
    if report.plugin_version != action.plugin_version:
        error(409, "runtime_package_unavailable", "目标插件版本不在客户端安装包内，请先更新客户端", "Update the client package before selecting this plugin version")
    active = db.query(models.ClientTask).filter_by(client_id=client.client_id, task_type="aidr_plugin_action").filter(models.ClientTask.status.in_(("pending", "running"))).first()
    if active:
        error(409, "runtime_task_active", "已有接入任务等待执行或正在执行，请先查看其结果", "An access task is pending or running; check its result first")
    body = action.model_dump()
    body["expires_at"] = (datetime.utcnow()+timedelta(hours=24)).isoformat(timespec="seconds")+"Z"
    task = models.ClientTask(client_id=client.client_id, task_type="aidr_plugin_action", payload_json=json.dumps(body,separators=(",", ":")), request_key=key)
    db.add(task)
    db.flush()
    return task


def coordinate(db, client, report):
    """One durable reconciliation per policy revision; manual tasks share its lock.

    A failed or interrupted installer needs explicit retry or a new policy, not
    another authorization prompt on every heartbeat.
    """
    from .client_governance import policy_view
    policy = policy_view(db, client.client_id)
    if not policy["runtime_governance_configured"] or report.protocol not in (2, 3, 4):
        return None
    version = policy["runtime_governance_version"]
    target = policy["runtime_governance"]
    # An old binary cannot apply explicit channel targets; preserve its reports
    # and expose the missing capability instead of sending a misleading task.
    if target.get("modes") is not None and report.protocol < 4:
        return None
    if target.get("channels") is not None and report.protocol not in (3, 4):
        return None
    if ":" in version and report.protocol not in (3, 4):
        return None
    receiver_enabled = hook_target(target)
    observed = {host.agent: host for host in report.hosts}
    needs_host_change = any(
        host and ((target["installation"] == "automatic" and host.installed is False)
                  or (target["updates"] == "automatic" and host.installed is True and host.plugin_version != report.plugin_version))
        for host in (observed.get(agent) for agent in target["hosts"]))
    if report.policy_version == version and report.policy_code == "aidr_desktop_policy_applied" and report.enabled == receiver_enabled and (not receiver_enabled or not needs_host_change):
        return None
    db.connection().exec_driver_sql("UPDATE managed_clients SET id=id WHERE client_id=?", (client.client_id,))
    # A host appearing, disappearing or changing version can require a fresh
    # check under the same target. Timestamps and health/retry ticks do not.
    state = {"hosts": [
        {key: host.model_dump()[key] for key in ("agent", "host_version", "version_status", "plugin_version", "installed", "enabled", "source_code", "access_mode")}
        for host in sorted(report.hosts, key=lambda host: host.agent)]}
    identity = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    key = f"aidr-reconcile:{client.client_id}:{version}:{report.plugin_version}:{identity}"
    prior = db.query(models.ClientTask).filter_by(request_key=key).first()
    if prior:
        return prior
    active = db.query(models.ClientTask).filter_by(client_id=client.client_id, task_type="aidr_plugin_action").filter(models.ClientTask.status.in_(("pending", "running"))).all()
    for task in active:
        body = json.loads(task.payload_json)
        if task.status == "running" or body.get("action") != "reconcile":
            return None
        task.status, task.error, task.finished_at = "cancelled", "aidr_desktop_task_superseded", datetime.utcnow()
    body = {"request_id": "policy-"+version, "action": "reconcile", "agent": "", "plugin_version": report.plugin_version,
            "policy_version": version, "target": policy["runtime_governance"],
            "expires_at": (datetime.utcnow()+timedelta(hours=24)).isoformat(timespec="seconds")+"Z"}
    task = models.ClientTask(client_id=client.client_id, task_type="aidr_plugin_action", payload_json=json.dumps(body, separators=(",", ":")), request_key=key)
    db.add(task)
    db.flush()
    return task


def retry_reconcile(db, client, original):
    from .client_governance import policy_view
    payload = json.loads(original.payload_json)
    policy = policy_view(db, client.client_id)
    if not policy["runtime_governance_configured"] or payload.get("policy_version") != policy["runtime_governance_version"]:
        error(409, "runtime_task_superseded", "请按当前策略执行", "Use the current policy")
    observation = db.get(Observation, client.client_id)
    report = Report.model_validate_json(observation.report_json) if observation else None
    if not report or payload.get("target") != policy["runtime_governance"] or payload.get("plugin_version") != report.plugin_version:
        error(409, "runtime_task_superseded", "请按当前策略及安装包执行", "Use the current policy and client package")
    db.connection().exec_driver_sql("UPDATE managed_clients SET id=id WHERE client_id=?", (client.client_id,))
    key = f"aidr-reconcile-retry:{client.client_id}:{original.id}"
    prior = db.query(models.ClientTask).filter_by(request_key=key).first()
    if prior:
        return prior
    latest = db.query(models.ClientTask).filter_by(client_id=client.client_id, task_type="aidr_plugin_action").order_by(models.ClientTask.id.desc()).first()
    if latest and latest.id != original.id:
        error(409, "runtime_task_superseded", "已有较新任务", "A newer task exists")
    payload.pop("receipt", None)
    payload["request_id"] = f"retry-{original.id}"
    payload["expires_at"] = (datetime.utcnow()+timedelta(hours=24)).isoformat(timespec="seconds")+"Z"
    task = models.ClientTask(client_id=client.client_id, task_type="aidr_plugin_action", payload_json=json.dumps(payload, separators=(",", ":")), request_key=key)
    db.add(task)
    db.flush()
    return task
