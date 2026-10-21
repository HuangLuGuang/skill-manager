"""Partner registrations, native evaluation jobs and frozen external reports."""
import base64
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .. import models, sqlite_db
from ..api_errors import ApiError
from ..config import settings
from ..external_access_models import ExternalAgentRegistration, ExternalAgentJob, ExternalGatewayEvent, ExternalResultEvent
from ..security_scan_controls import (json_dumps, normalize_cidrs, protect_secret, mask_secret,
                                     resolve_target_endpoint, validate_target_type_scheme, TASK_TERMINAL_STATUSES)
from ..security_scan_schemas import SecurityTaskCreate
from .openapi_skills import Identifier, CallbackReference, iso, _text, SEVERITIES

AgentID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=128)]
APIKey = Annotated[str, StringConstraints(min_length=1, max_length=4096, pattern=r"^[!-~]+$")]


class RegistrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    department_id: str = Field(min_length=1, max_length=64)
    department_name: Name
    owner: Name
    environment: Literal["sandbox", "test", "staging", "production"]
    endpoint_url: str = Field(min_length=1, max_length=2048)
    protocol: Literal["openai_chat_completions"]
    model: Name
    api_key: APIKey | None = None
    description: str = Field(default="", max_length=2000)
    gateway_agent_id: Name

    @field_validator("endpoint_url")
    @classmethod
    def endpoint(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use an HTTP or HTTPS base URL without credentials, query or fragment")
        parsed.port
        return value.rstrip("/")


class RegistrationCreate(RegistrationUpdate):
    agent_id: AgentID
    api_key: APIKey


class ConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_revision: int = Field(ge=1, strict=True)


class EvaluationRequest(ConnectionRequest):
    business_request_id: Identifier
    agent_id: AgentID
    connection_test_id: Identifier
    profile_id: Identifier
    callback_id: Identifier
    gateway_id: Identifier


class PartnerConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_cidrs: list[str] = Field(min_length=1)
    connection_policy_ids: dict[str, str]
    connection_approval_ids: dict[str, Identifier] = Field(default_factory=dict)
    connection_ttl_seconds: int = Field(default=300, ge=1, le=86400)


class EvaluationProfile(CallbackReference):
    policy_id: Identifier
    evaluation_model: Name
    skills: list[str] = Field(min_length=1)
    conversation_mode: Literal["single_turn", "multi_turn"] = "single_turn"
    language: Literal["zh", "en"] = "zh"
    approval_id: str | None = None
    malicious_rule_ids: list[str] = Field(default_factory=list)

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, values):
        from ..security_scan_controls import AGENT_SCAN_SKILLS
        if len(set(values)) != len(values) or any(value not in AGENT_SCAN_SKILLS for value in values):
            raise ValueError("Unsupported or duplicate evaluation skill")
        return values


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partners: dict[str, PartnerConfiguration]
    profiles: dict[str, EvaluationProfile]
    callbacks: dict[str, CallbackReference]
    gateways: dict[str, CallbackReference]


def configuration_path():
    return Path(os.environ.get("OPENAPI_AGENT_CONFIG") or Path(settings.DATA_DIR) / "openapi-agents.json")


def configuration():
    try:
        path = configuration_path()
        return Configuration.model_validate_json(Path(path).read_text())
    except (OSError, ValueError):
        raise ApiError(503, "SERVICE_UNAVAILABLE", "智能体开放接口配置不可用", "Agent API configuration is unavailable") from None


def partner_configuration(config, context):
    partner = config.partners.get(context.platform_id)
    if partner is None:
        raise ApiError(403, "FORBIDDEN", "接入方未配置智能体接入", "Agent integration is not configured for this partner")
    return partner


def authorized_reference(values, identifier, context):
    value = values.get(identifier)
    if value is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "方案或投递配置不存在", "Profile or delivery configuration not found")
    if context.platform_id not in value.platform_ids:
        raise ApiError(403, "FORBIDDEN", "接入方未获配置授权", "The partner is not authorized for this configuration")
    return value


def begin_write(db):
    db.rollback()
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def owned_registration(db, agent_id, context):
    row = db.query(ExternalAgentRegistration).filter_by(platform_id=context.platform_id, agent_id=agent_id).first()
    if row is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "智能体未登记", "Agent registration not found")
    if context.department_group(row.department_id) != row.department_group_id:
        raise ApiError(403, "FORBIDDEN", "部门授权与智能体不匹配", "Department authorization does not match the agent")
    return row


def save_registration(db, body, context, *, agent_id=None):
    from ..security_scan_controls import DEFAULT_SECURITY_SCAN_CAPABILITIES
    partner = partner_configuration(configuration(), context)
    group_id = context.department_group(body.department_id)
    cidrs = normalize_cidrs(partner.allowed_cidrs)
    validate_target_type_scheme("openai", body.endpoint_url)
    resolved = resolve_target_endpoint(body.endpoint_url, allowed_cidrs=cidrs, allow_insecure_transport=body.endpoint_url.startswith("http://"))
    begin_write(db)
    now = datetime.utcnow()
    if agent_id is None:
        agent_id = body.agent_id
        if db.query(ExternalAgentRegistration).filter_by(platform_id=context.platform_id, agent_id=agent_id).first():
            raise ApiError(409, "AGENT_ALREADY_EXISTS", "智能体已登记", "Agent is already registered")
        row = ExternalAgentRegistration(registration_id="ear_" + uuid.uuid4().hex, platform_id=context.platform_id,
            agent_id=agent_id, managed_agent_id="ext_" + uuid.uuid4().hex, target_revision=1, evaluation_sequence=0,
            created_at=now)
        agent = models.ManagedAgent(agent_id=row.managed_agent_id, **context.agent_source(agent_id), created_by=context.username)
        db.add_all([row, agent])
        old_credential = None
    else:
        row = owned_registration(db, agent_id, context)
        old_credential = db.query(models.SecurityTargetCredential).filter_by(credential_id=row.credential_id).one()
        agent = db.query(models.ManagedAgent).filter_by(agent_id=row.managed_agent_id).one()
        row.target_revision += 1
    if "api_key" in body.model_fields_set and body.api_key is None:
        raise ApiError(422, "INVALID_ARGUMENT", "api_key提供时不能为空", "api_key must be nonempty when provided")
    if not body.api_key and old_credential.status != "active":
        raise ApiError(422, "INVALID_ARGUMENT", "原凭据不可用，请提供新的api_key", "The previous credential is unavailable; provide a new api_key")
    # Each revision owns its target and credential, so accepted tasks retain their configuration.
    target_id, credential_id = "ast_" + uuid.uuid4().hex, "asc_" + uuid.uuid4().hex
    target = models.SecurityTarget(target_id=target_id, name=body.name, target_type="openai", asset_type="agent",
        connector_type="openai_compatible", environment=body.environment, endpoint_url=body.endpoint_url,
        owner_group_id=group_id, allowed_cidrs_json=json_dumps(cidrs), resolved_ips_json=json_dumps(resolved),
        allowed_capabilities_json=json_dumps(list(DEFAULT_SECURITY_SCAN_CAPABILITIES)),
        config_json=json_dumps({"model": body.model, "allow_insecure_transport": body.endpoint_url.startswith("http://")}),
        created_by=context.username)
    credential = models.SecurityTargetCredential(credential_id=credential_id, target_id=target_id,
        purpose="agent_runtime", credential_type="bearer", version=row.target_revision,
        secret_encrypted=protect_secret(body.api_key) if body.api_key else old_credential.secret_encrypted,
        secret_masked=mask_secret(body.api_key) if body.api_key else old_credential.secret_masked, created_by=context.username)
    row.target_id, row.credential_id = target_id, credential_id
    row.department_id, row.department_group_id = body.department_id, group_id
    row.registration_json = json_dumps({**body.model_dump(exclude={"api_key", "agent_id"}), "agent_id": agent_id})
    row.updated_at = now
    agent.name, agent.owner, agent.description = body.name, body.owner, body.description
    agent.department_group_id, agent.default_model = group_id, body.model
    agent.updated_at = now
    db.add_all([target, credential])
    db.commit()
    return row


def check_revision(row, revision):
    if row.target_revision != revision:
        raise ApiError(409, "TARGET_REVISION_CONFLICT", "登记版本已变化，请重新验证连接", "Registration has changed; validate the current revision")


def require_evaluator_access(db, task):
    job = db.get(ExternalAgentJob, task.task_id)
    token = db.get(models.AccessToken, task.source_token_id) if task.source_token_id else None
    platform = db.get(models.ExternalPlatform, task.source_platform_id) if task.source_platform_id else None
    group = db.get(models.UserGroup, task.owner_group_id) if task.owner_group_id else None
    if (not job or job.kind != "evaluation" or job.platform_id != task.source_platform_id
            or job.department_group_id != task.owner_group_id
            or not token or token.token_type != "openapi" or token.status != "active"
            or token.platform_id != job.platform_id
            or (token.expires_at and token.expires_at <= datetime.utcnow())
            or "openapi:evaluation-submit" not in json.loads(token.scopes_json)
            or job.department_id not in json.loads(token.allowed_department_ids_json)
            or not platform or not platform.enabled or not group or not group.is_active
            or {d["department_id"]: d["group_id"] for d in json.loads(platform.departments_json)}.get(job.department_id) != job.department_group_id):
        raise ApiError(403, "agent_security.evaluation_not_authorized", "任务的接入方或部门授权已失效", "The task's partner or department authorization is no longer valid")


def owned_job(db, task_id, context, kind):
    row = db.query(ExternalAgentJob).filter_by(task_id=task_id, platform_id=context.platform_id, kind=kind).first()
    if row is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "任务不存在", "Task not found")
    if context.department_group(row.department_id) != row.department_group_id:
        raise ApiError(403, "FORBIDDEN", "部门授权与任务不匹配", "Department authorization does not match the task")
    return row


def connection_ready(row, registration):
    return bool(row.status == "succeeded" and row.expires_at and row.expires_at > datetime.utcnow()
                and row.target_revision == registration.target_revision and row.registration_id == registration.registration_id)


def registration_response(db, row):
    latest = db.query(ExternalAgentJob).filter_by(registration_id=row.registration_id, kind="connection",
        target_revision=row.target_revision).order_by(ExternalAgentJob.created_at.desc()).first()
    state = "not_tested"
    if latest:
        sync_job(db, db.query(models.SecurityScanTask).filter_by(task_id=latest.task_id).one())
        state = "testing" if latest.status in {"pending", "running"} else "ready" if connection_ready(latest, row) else "expired" if latest.status == "succeeded" else "failed"
    credential = db.query(models.SecurityTargetCredential).filter_by(credential_id=row.credential_id).first()
    return {**json.loads(row.registration_json), "target_revision": row.target_revision,
            "credential_configured": bool(credential and credential.status == "active"), "connection_status": state,
            "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


def create_job(db, registration, context, *, body=None):
    from ..routers import security_scans as native
    config = configuration()
    partner = partner_configuration(config, context)
    registration_data = json.loads(registration.registration_json)
    evaluation = body is not None
    if evaluation:
        profile = authorized_reference(config.profiles, body.profile_id, context)
        from .external_callbacks import resolve
        callback = resolve(db, body.callback_id, context.platform_id, "agent_evaluation", config.callbacks.get(body.callback_id))
        from .external_gateways import resolve as resolve_gateway
        gateway = resolve_gateway(db, body.gateway_id, context.platform_id, config.gateways.get(body.gateway_id))
        check = owned_job(db, body.connection_test_id, context, "connection")
        sync_job(db, db.query(models.SecurityScanTask).filter_by(task_id=check.task_id).one())
        if not connection_ready(check, registration):
            raise ApiError(409, "CONNECTION_TEST_REQUIRED", "连接验证未通过或已失效", "Connection verification has not passed or has expired")
        kwargs = profile.model_dump(exclude={"version", "platform_ids", "malicious_rule_ids"})
        profile_data = profile.model_dump()
    else:
        policy_id = partner.connection_policy_ids.get(registration_data["environment"])
        if not policy_id:
            raise ApiError(503, "SERVICE_UNAVAILABLE", "当前环境未配置连接验证策略", "No connection policy is configured for this environment")
        kwargs = {"policy_id": policy_id, "approval_id": partner.connection_approval_ids.get(registration.agent_id)}
        profile_data = {"connection_ttl_seconds": partner.connection_ttl_seconds}
        policy = native._policy_or_404(db, policy_id)
        if policy.execution_mode == "passive" or "conversation" not in json.loads(policy.allowed_capabilities_json):
            raise ApiError(403, "FORBIDDEN", "连接验证策略需允许对话", "The connection policy must allow conversation")
    credential = db.get(models.AccessToken, context.token_id)
    active = db.query(models.SecurityScanTask).filter_by(source_token_id=context.token_id).filter(
        models.SecurityScanTask.status.in_(["pending", "running"])).count()
    if active >= credential.max_concurrent_jobs:
        raise ApiError(429, "RATE_LIMITED", "凭证并发任务数已达上限", "The credential's concurrent task limit has been reached")
    task_body = SecurityTaskCreate(target_id=registration.target_id, scan_kind="agent_risk_scan" if evaluation else "control_plane_validation",
                                  idempotency_key="openapi:" + uuid.uuid4().hex, **kwargs)
    holder = {}

    def attach(session, task):
        for key, value in context.task_source(task.task_id, body.business_request_id if evaluation else None).items():
            setattr(task, key, value)
        if not evaluation:
            snapshot = json.loads(task.target_snapshot_json)
            snapshot["openapi_connection_test"] = True
            task.target_snapshot_json = json_dumps(snapshot)
        else:
            registration.evaluation_sequence += 1
        job = ExternalAgentJob(task_id=task.task_id, kind="evaluation" if evaluation else "connection",
            registration_id=registration.registration_id, platform_id=context.platform_id,
            department_id=registration.department_id, department_group_id=registration.department_group_id,
            agent_id=registration.agent_id, target_revision=registration.target_revision,
            credential_id=registration.credential_id, registration_json=registration.registration_json,
            profile_json=json_dumps(profile_data),
            business_request_id=body.business_request_id if evaluation else None,
            profile_id=body.profile_id if evaluation else None, callback_id=body.callback_id if evaluation else None,
            callback_version=callback.version if evaluation else None, gateway_id=body.gateway_id if evaluation else None,
            gateway_version=gateway.version if evaluation else None,
            connection_test_id=body.connection_test_id if evaluation else None,
            evaluation_sequence=registration.evaluation_sequence if evaluation else None)
        session.add(job)
        holder["job"] = job
    native.create_scan_task(db, task_body, context, before_commit=attach)
    return holder["job"]


def error(row, english=False):
    if not row.error_code:
        return None
    messages = {
        "REPORT_UNAVAILABLE": ("本次报告不可用", "The report is unavailable"),
        "EXECUTION_FAILED": ("评测未成功完成，请查看任务执行状态", "Evaluation did not complete successfully; check the task status"),
        "CONNECTION_FAILED": ("连接验证未通过", "Connection verification did not pass"),
        "CONNECTION_AUTH_FAILED": ("目标接口认证失败，请检查智能体访问密钥", "Target authentication failed; check the Agent API key"),
        "CONNECTION_PROTOCOL_INVALID": ("目标未返回有效的Chat Completions文本响应", "The target did not return a valid Chat Completions text response"),
        "CONNECTION_TIMED_OUT": ("目标接口连接验证超时", "Target connection verification timed out"),
        "CONNECTION_NETWORK_FAILED": ("Worker无法连接登记的目标地址", "The Worker could not connect to the registered target"),
        "CONNECTION_TLS_FAILED": ("目标TLS证书验证失败", "Target TLS certificate verification failed"),
        "TASK_TIMEOUT": ("任务执行超时", "Task execution timed out"),
        "POLICY_BLOCKED": ("任务被策略阻断", "The task was blocked by policy"),
    }
    zh, en = messages.get(row.error_code, messages["CONNECTION_FAILED"])
    code = {"CONNECTION_AUTH_FAILED": "TARGET_AUTH_FAILED", "CONNECTION_PROTOCOL_INVALID": "TARGET_PROTOCOL_INVALID",
            "CONNECTION_TIMED_OUT": "TASK_TIMEOUT", "CONNECTION_NETWORK_FAILED": "TARGET_UNREACHABLE",
            "CONNECTION_TLS_FAILED": "TARGET_UNREACHABLE", "CONNECTION_FAILED": "EXECUTION_FAILED"}.get(row.error_code, row.error_code)
    return {"code": code, "message": en if english else zh, "retryable": False}


def sync_job(db, task):
    """Join the caller's transaction, including Worker completion and finding changes."""
    row = db.get(ExternalAgentJob, task.task_id)
    if row is None or row.status in TASK_TERMINAL_STATUSES:
        return row
    claimed = db.query(ExternalAgentJob).filter(ExternalAgentJob.task_id == task.task_id,
        ExternalAgentJob.status.in_(["pending", "running"])).update({"status": task.status}, synchronize_session=False)
    if not claimed:
        db.refresh(row)
        return row
    row.status = task.status
    if task.status not in TASK_TERMINAL_STATUSES:
        return row
    row.completed_at = task.completed_at or datetime.utcnow()
    if row.kind == "connection":
        cases = db.query(models.SecurityScanCase).filter_by(task_id=task.task_id).all()
        checks = {key: "pending" for key in ("network", "tls", "authentication", "protocol")}
        for case in cases:
            if case.external_case_id == "openapi-connection":
                checks.update(json.loads(case.response_summary_json).get("checks", {}))
        secure = json.loads(row.registration_json)["endpoint_url"].startswith("https://")
        passed = (all(checks[key] == "passed" for key in ("network", "authentication", "protocol"))
                  and checks["tls"] == ("passed" if secure else "skipped"))
        row.checked_at = row.completed_at
        if task.status == "succeeded" and passed:
            row.expires_at = row.checked_at + timedelta(seconds=json.loads(row.profile_json)["connection_ttl_seconds"])
        else:
            row.status = "timed_out" if task.status == "timed_out" or task.error_code == "CONNECTION_TIMED_OUT" else "failed"
            row.error_code = ("TASK_TIMEOUT" if row.status == "timed_out" else "POLICY_BLOCKED" if task.status == "blocked"
                              else task.error_code if task.error_code in {"CONNECTION_AUTH_FAILED", "CONNECTION_PROTOCOL_INVALID",
                                  "CONNECTION_NETWORK_FAILED", "CONNECTION_TLS_FAILED"} else "CONNECTION_FAILED")
        row.report_json = json_dumps(checks)
        return row
    from ..routers.security_scans import _task_detail
    detail = _task_detail(db, task)
    cases = [{key: item[key] for key in ("case_id", "external_case_id", "category", "title", "status",
              "execution_status", "assessment_status", "round_count")} for item in detail["cases"]]
    findings = []
    for item in detail["findings"]:
        findings.append({**{key: item[key] for key in ("finding_id", "case_id", "finding_code", "severity", "status",
                         "title", "description", "source", "confidence")},
                         "evidence_summary": _text(item["evidence"].get("conversation") or item["evidence"].get("evidence_summary") or None),
                         "recommendation": _text(item["evidence"].get("suggestion"))})
        for key in ("title", "description"):
            findings[-1][key] = _text(findings[-1][key])
    for case in cases:
        case["title"] = _text(case["title"])
    score = detail["risk_score"]
    coverage = {"complete": "complete", "partial": "partial", "unassessed": "none"}[score["status"]]
    profile = json.loads(row.profile_json)
    malicious = any(f["finding_code"] in profile["malicious_rule_ids"] and f["evidence_summary"]
                    and f["status"] == "open" for f in findings)
    suspicious = any(f["status"] == "open" and f["severity"] != "info" for f in findings)
    risk = "malicious" if malicious else "suspicious" if suspicious else "benign" if coverage == "complete" else None
    counts = {key: sum(c["status"] == key for c in cases) for key in ("passed", "failed", "blocked", "error", "unverified")}
    if sum(counts.values()) != len(cases) or any(f["severity"] not in SEVERITIES for f in findings):
        row.status = "failed"
        row.error_code = "REPORT_UNAVAILABLE"
        report = None
    else:
        limitations = [] if coverage == "complete" else ["Planned checks were not fully assessed."]
        if task.error_code:
            limitations.append(_text(task.error_code))
        report = {"task_id": row.task_id, "task_type": "agent_evaluation", "task_status": row.status,
            "risk_level": risk, "report_id": "rpt_" + row.task_id, "report_version": 1,
            "business_request_id": row.business_request_id, "department_id": row.department_id,
            "agent_id": row.agent_id, "target_revision": row.target_revision,
            "gateway_agent_id": json.loads(row.registration_json)["gateway_agent_id"],
            "evaluation_sequence": row.evaluation_sequence, "profile_id": row.profile_id,
            "profile_version": profile["version"], "coverage": coverage, "risk_score": score,
            "case_counts": {"total": len(cases), **counts},
            "finding_counts": {key: sum(f["severity"] == key for f in findings) for key in SEVERITIES},
            "limitations": limitations, "completed_at": iso(row.completed_at)}
        row.report_json, row.cases_json, row.findings_json = json_dumps(report), json_dumps(cases), json_dumps(findings)
        row.error_code = {"timed_out": "TASK_TIMEOUT", "blocked": "POLICY_BLOCKED"}.get(
            task.status, "EXECUTION_FAILED" if task.status != "succeeded" else None)
    payload = {"schema_version": "security-result-event.v1", "event_id": "ev_" + row.task_id,
        "event_type": "agent_evaluation.terminal", "occurred_at": iso(row.completed_at), "platform_id": row.platform_id,
        "task_id": row.task_id, "task_type": "agent_evaluation", "business_request_id": row.business_request_id,
        "status": row.status, "result_ready": report is not None,
        "subject": {"agent_id": row.agent_id, "department_id": row.department_id, "target_revision": row.target_revision},
        "result": {k: report[k] for k in ("report_id", "report_version", "risk_level", "coverage", "finding_counts", "risk_score")} if report else None,
        "error": error(row)}
    db.add(ExternalResultEvent(event_id=payload["event_id"], task_id=row.task_id, source_platform_id=row.platform_id,
        callback_id=row.callback_id, callback_version=row.callback_version, payload_json=json_dumps(payload)))
    db.add(ExternalGatewayEvent(task_id=row.task_id, gateway_id=row.gateway_id, gateway_version=row.gateway_version,
        payload_json=json_dumps({"schema_version": "agent-evaluation-result.v1", "sync_id": "sync_" + row.task_id + "_v1",
                               "platform_id": row.platform_id, "agent_id": row.agent_id,
                               "gateway_agent_id": report["gateway_agent_id"], "department_id": row.department_id,
                               "evaluation_sequence": row.evaluation_sequence, "target_revision": row.target_revision,
                               "report": report, "findings": findings}) if report else None,
        status="pending" if report else "failed", last_error_code=None if report else "REPORT_UNAVAILABLE"))
    return row


def reconcile():
    from ..routers.security_scans import recover_stale_tasks
    with sqlite_db.SessionLocal() as db:
        recover_stale_tasks(db)
        begin_write(db)
        for row in db.query(ExternalAgentJob).filter(ExternalAgentJob.status.in_(["pending", "running"])).all():
            task = db.query(models.SecurityScanTask).filter_by(task_id=row.task_id).one()
            sync_job(db, task)
        db.commit()


def delivery(event, *, gateway=False):
    fields = ("status", "attempts", "last_attempt_at", "next_retry_at", "last_error_code")
    values = {key: getattr(event, key) if event else ("pending" if key == "status" else 0 if key == "attempts" else None) for key in fields}
    for key in ("last_attempt_at", "next_retry_at"):
        values[key] = iso(values[key])
    values["synced_at" if gateway else "delivered_at"] = iso(getattr(event, "synced_at" if gateway else "delivered_at")) if event else None
    if gateway:
        values["receipt_id"] = event.receipt_id if event else None
    return values


def report_page(row, kind, cursor, limit):
    items = json.loads(row.cases_json if kind == "cases" else row.findings_json)
    report_id = json.loads(row.report_json)["report_id"]
    offset = 0
    if cursor:
        try:
            data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if data["report_id"] != report_id or data["kind"] != kind or type(data["offset"]) is not int or not 0 <= data["offset"] < len(items):
                raise ValueError()
            offset = data["offset"]
        except (ValueError, TypeError, KeyError):
            raise ApiError(422, "INVALID_ARGUMENT", "分页游标无效", "Invalid pagination cursor") from None
    end = offset + limit
    following = base64.urlsafe_b64encode(json.dumps({"report_id": report_id, "kind": kind, "offset": end}).encode()).decode() if end < len(items) else None
    return {"items": items[offset:end], "next_cursor": following}
