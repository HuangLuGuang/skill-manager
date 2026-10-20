"""Skill scan profiles and immutable external reports."""
import asyncio
import base64
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from agent_manager.security_redaction import redact_sensitive_text
from .. import sqlite_db
from ..api_errors import ApiError
from ..external_access_models import ExternalSkillScan, ExternalResultEvent
from ..request_leases import acquire_lease, release_lease, LeaseLimitExceeded

logger = logging.getLogger(__name__)
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, strip_whitespace=False)]
ANALYZERS = ("scanner", "skillspector", "behavioral", "sandbox", "llm")
SEVERITIES = ("critical", "high", "medium", "low", "info")
ACTIVE = ("pending", "running")
_dispatch_lock = threading.RLock()
_executions = {}


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_request_id: Identifier
    skill_id: Identifier
    skill_version: Identifier
    department_id: str = Field(min_length=1, max_length=64)
    profile_id: Identifier
    callback_id: Identifier
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Identifier
    platform_ids: list[str] = Field(min_length=1)
    use_behavioral: bool = False
    use_llm: bool = False
    use_sandbox: bool = True
    use_skillspector: bool = False
    judgement_mode: Literal["balanced", "strict", "permissive"] = "balanced"
    malicious_rule_ids: list[str] = Field(default_factory=list)


class CallbackReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Identifier
    platform_ids: list[str] = Field(min_length=1)


class SkillConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: dict[str, Profile]
    callbacks: dict[str, CallbackReference]


def configuration_path(data_dir):
    return Path(os.environ.get("OPENAPI_SKILL_CONFIG") or Path(data_dir) / "openapi-skills.json")


def configuration(metadata, context, data_dir, db=None):
    try:
        path = configuration_path(data_dir)
        config = SkillConfiguration.model_validate_json(Path(path).read_text())
    except (KeyError, OSError, ValueError):
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Skill 开放接口配置不可用", "Skill API configuration is unavailable") from None
    profile = config.profiles.get(metadata.profile_id)
    if profile is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "检测方案或回调配置不存在", "Profile or callback configuration not found")
    if context.platform_id not in profile.platform_ids:
        raise ApiError(403, "FORBIDDEN", "接入方未获方案或回调配置授权", "The partner is not authorized for this profile or callback")
    from .external_callbacks import resolve
    callback = resolve(db, metadata.callback_id, context.platform_id, "skill_scan", config.callbacks.get(metadata.callback_id))
    return profile, callback


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def options(profile):
    return {key: profile[key] for key in ("use_behavioral", "use_llm", "use_sandbox", "use_skillspector", "judgement_mode")}


def analyzer_states(profile, run, snapshot=None):
    report = (snapshot or {}).get("scan_report", {})
    timings = report.get("analyzer_timings", {})
    live = run.result.get("analyzers", {}) if run else {}
    result = []
    for name in ANALYZERS:
        enabled = name == "scanner" or profile.get("use_" + name, False)
        if name == "sandbox" and (snapshot or {}).get("sandbox_required_by_policy"):
            enabled = True
        timing = timings.get(name, {})
        status = timing.get("status") or live.get(name)
        if not status:
            status = "pending" if enabled else "disabled"
        if status in {"pending", "running"} and run and run.status != "PENDING":
            status = "failed" if enabled else "disabled"
        result.append({"name": name, "status": status, "reason": timing.get("reason")})
    return result


def _text(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return redact_sensitive_text(value)


def project_findings(raw, skill_path):
    items = []
    for index, finding in enumerate(raw):
        severity = str(finding.get("severity", "")).lower()
        if severity not in SEVERITIES:
            raise ValueError("Unmapped finding severity")
        location = finding.get("location") or {}
        file = finding.get("file_path") or finding.get("file") or (location.get("file") if isinstance(location, dict) else None)
        line = finding.get("line_number") or finding.get("line") or (location.get("line") if isinstance(location, dict) else None)
        if file:
            path = Path(str(file))
            if path.is_absolute():
                try:
                    file = path.relative_to(skill_path).as_posix()
                except ValueError:
                    file = None
            elif ".." in PurePosixPath(str(file).replace("\\", "/")).parts:
                file = None
        items.append({
            "finding_id": f"f_{index + 1:06d}",
            "rule_id": finding.get("rule_id") or finding.get("rule") or None,
            "category": finding.get("category") or None, "severity": severity,
            "title": _text(finding.get("title") or finding.get("rule_id") or finding.get("rule") or "Finding"),
            "description": _text(finding.get("description") or finding.get("message") or finding.get("explanation") or ""),
            "location": {"file": _text(file), "line": line if type(line) is int and line > 0 else None} if file else None,
            "evidence_summary": _text(finding.get("evidence_summary") or finding.get("code_snippet") or finding.get("evidence")),
            "recommendation": _text(finding.get("recommendation") or finding.get("remediation")),
        })
    return items


def build_report(row, run, snapshot, skill_path):
    profile = json.loads(row.profile_json)
    scan_report = snapshot["scan_report"]
    raw = scan_report.get("findings", [])
    findings = project_findings(raw, skill_path)
    analyzers = analyzer_states(profile, run, snapshot)
    required = [a for a in analyzers if a["name"] == "scanner" or profile.get("use_" + a["name"]) or
                (a["name"] == "sandbox" and snapshot.get("sandbox_required_by_policy"))]
    complete = all(a["status"] == "completed" for a in required)
    coverage = "complete" if complete else "partial" if findings or any(a["status"] == "completed" for a in required) else "none"
    malicious_rules = set(profile["malicious_rule_ids"])
    malicious = any(f["rule_id"] in malicious_rules and f["evidence_summary"] for f in findings)
    suspicious = any(f["severity"] != "info" for f in findings)
    risk = "malicious" if malicious else "suspicious" if suspicious else "benign" if complete else None
    # An LLM-only signal remains a risk to investigate until a configured rule
    # and its evidence establish malicious behavior.
    if risk in {None, "benign"} and scan_report.get("risk_reconciliation", {}).get("llm_risk_level") in {"suspicious", "malicious"}:
        risk = "suspicious"
    completed_at = iso(row.completed_at)
    report = {
        "task_id": row.task_id, "report_id": "rpt_" + row.task_id[4:], "report_version": 1,
        "task_type": "skill_scan", "task_status": "succeeded", "business_request_id": row.business_request_id,
        "skill_id": row.external_skill_id, "skill_version": row.skill_version, "department_id": row.department_id,
        "profile_id": row.profile_id, "profile_version": profile["version"], "risk_level": risk, "coverage": coverage,
        "finding_counts": {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES},
        "limitations": [f'{a["name"]}:{a["reason"] or a["status"]}' for a in required if a["status"] != "completed"],
        "completed_at": completed_at,
    }
    return report, findings, analyzers


def sync_task(db, row, mgr):
    if row.status not in ACTIVE:
        return row
    run = next((r for r in mgr.list_scan_runs(row.version_id) if r.scan_run_id == row.scan_run_id), None)
    if run is None:
        row.status, row.error_code = "failed", "REPORT_UNAVAILABLE"
        row.completed_at = datetime.utcnow()
    elif run.status == "PENDING":
        stage = run.result.get("progress_stage", "queued")
        state = "pending" if stage == "queued" else "running"
        analyzers = json.dumps(analyzer_states(json.loads(row.profile_json), run))
        if row.status != state or row.analyzers_json != analyzers:
            row.status, row.analyzers_json, row.updated_at = state, analyzers, datetime.utcnow()
            return save_task(db, row, terminal=False)
        return row
    else:
        row.status = {"COMPLETED": "succeeded", "REUSED": "succeeded", "FAILED": "failed", "CANCELLED": "cancelled"}[run.status]
        # The external task completes when its report is published, including
        # requests that reuse an execution completed before they were accepted.
        row.completed_at = datetime.utcnow()
        row.analyzers_json = json.dumps(analyzer_states(json.loads(row.profile_json), run))
        if row.status == "succeeded":
            snapshot = mgr.registry.get_scan_run_report(row.scan_run_id)
            entry = mgr.get_skill(row.version_id, include_scan_report=False)
            try:
                if snapshot is None or entry is None:
                    raise ValueError("Missing execution report")
                report, findings, analyzers = build_report(row, run, snapshot, entry.skill_path)
                row.report_json = json.dumps(report, ensure_ascii=False)
                row.findings_json = json.dumps(findings, ensure_ascii=False)
                row.analyzers_json = json.dumps(analyzers)
            except (ValueError, TypeError, KeyError):
                row.status, row.error_code = "failed", "REPORT_UNAVAILABLE"
        elif row.status == "failed":
            row.error_code = "EXECUTION_FAILED"
        elif row.status == "cancelled":
            row.error_code = "REPORT_UNAVAILABLE"
    row.updated_at = datetime.utcnow()
    return save_task(db, row, terminal=True)


def save_task(db, row, *, terminal):
    """Publish a terminal report and its notification event in one transaction."""
    task_id = row.task_id
    values = {name: getattr(row, name) for name in ("status", "report_json", "findings_json", "analyzers_json", "error_code", "updated_at", "completed_at")}
    db.expunge(row)
    changed = db.query(ExternalSkillScan).filter(ExternalSkillScan.task_id == task_id,
        ExternalSkillScan.status.in_(ACTIVE)).update(values, synchronize_session=False)
    if terminal and changed:
        report = json.loads(row.report_json) if row.report_json else None
        payload = {"schema_version": "security-result-event.v1", "event_id": "ev_" + task_id,
            "event_type": "skill_scan.terminal", "occurred_at": iso(row.completed_at),
            "platform_id": row.source_platform_id, "task_id": task_id, "task_type": "skill_scan",
            "business_request_id": row.business_request_id, "status": row.status, "result_ready": report is not None,
            "subject": {"skill_id": row.external_skill_id, "skill_version": row.skill_version, "department_id": row.department_id},
            "result": {k: report[k] for k in ("report_id", "report_version", "risk_level", "coverage", "finding_counts")} if report else None,
            "error": task_error(row)}
        db.add(ExternalResultEvent(event_id=payload["event_id"], task_id=task_id, source_platform_id=row.source_platform_id,
            callback_id=row.callback_id, callback_version=row.callback_version, payload_json=json.dumps(payload, ensure_ascii=False)))
    db.commit()
    return db.get(ExternalSkillScan, task_id)


def get_owned_task(db, task_id, context, mgr):
    row = db.query(ExternalSkillScan).filter_by(task_id=task_id, source_platform_id=context.platform_id).first()
    if row is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "检测任务不存在", "Scan task not found")
    if context.department_group(row.department_id) != row.department_group_id:
        raise ApiError(403, "FORBIDDEN", "部门授权与任务不匹配", "Department authorization does not match the task")
    return sync_task(db, row, mgr)


def task_error(row, english=False):
    if not row.error_code:
        return None
    messages = {"REPORT_UNAVAILABLE": ("本次报告不可用", "This scan report is unavailable"),
                "EXECUTION_FAILED": ("本次检测执行失败", "This scan execution failed")}
    zh, en = messages[row.error_code]
    return {"code": row.error_code, "message": en if english else zh, "retryable": False}


def progress(row, mgr, english=False, event=None):
    stage = "finished"
    if row.status in ACTIVE:
        run = next((r for r in mgr.list_scan_runs(row.version_id) if r.scan_run_id == row.scan_run_id), None)
        native = run.result.get("progress_stage", "queued") if run else "queued"
        stage = {"queued": "pending", "preparing": "validating", "finalizing": "finalizing"}.get(native, "analyzing")
    return {"task_id": row.task_id, "business_request_id": row.business_request_id, "status": row.status,
            "result_ready": row.report_json is not None, "progress": {"stage": stage, "percent": None},
            "analyzers": json.loads(row.analyzers_json),
            "callback": {"status": event.status if event else "pending", "attempts": event.attempts if event else 0,
                         "last_attempt_at": iso(event.last_attempt_at) if event else None,
                         "next_retry_at": iso(event.next_retry_at) if event else None,
                         "last_error_code": event.last_error_code if event else None,
                         "delivered_at": iso(event.delivered_at) if event else None},
            "created_at": iso(row.created_at), "updated_at": iso(row.updated_at), "completed_at": iso(row.completed_at),
            "error": task_error(row, english)}


def require_report(row):
    if row.status in ACTIVE:
        raise ApiError(409, "RESULT_NOT_READY", "检测结果尚未生成", "The scan result is not ready")
    if row.report_json is None:
        raise ApiError(409, "REPORT_UNAVAILABLE", "本次报告不可用", "This scan report is unavailable")


def findings_page(row, cursor, limit):
    report_id = json.loads(row.report_json)["report_id"]
    findings = json.loads(row.findings_json)
    offset = 0
    if cursor:
        try:
            data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if data["report_id"] != report_id or type(data["offset"]) is not int or not 0 <= data["offset"] < len(findings):
                raise ValueError("Invalid cursor")
            offset = data["offset"]
        except (ValueError, TypeError, KeyError):
            raise ApiError(422, "INVALID_ARGUMENT", "分页游标无效", "Invalid pagination cursor") from None
    end = offset + limit
    next_cursor = base64.urlsafe_b64encode(json.dumps({"report_id": report_id, "offset": end}).encode()).decode() if end < len(findings) else None
    return {"items": findings[offset:end], "next_cursor": next_cursor}


def execute_scan(task_id, mgr):
    from agent_manager.api.router import _process_pending_submission_task
    with sqlite_db.SessionLocal() as db:
        row = db.get(ExternalSkillScan, task_id)
        profile, version_id = json.loads(row.profile_json), row.version_id
        run = next((r for r in mgr.list_scan_runs(version_id) if r.scan_run_id == row.scan_run_id), None)
        if not run or run.status != "PENDING":
            sync_task(db, row, mgr)
            return
    frozen = AgentManager(policy=CompanyPolicy(profile["policy"]), registry=mgr.registry)
    opts = options(profile)
    _process_pending_submission_task(frozen, version_id, opts["use_behavioral"], opts["use_llm"],
                                    opts["use_sandbox"], opts["use_skillspector"], False, opts["judgement_mode"])
    reconcile(mgr)


def reconcile(mgr):
    with sqlite_db.SessionLocal() as db:
        for row in db.query(ExternalSkillScan).filter(ExternalSkillScan.status.in_(ACTIVE)).all():
            sync_task(db, row, mgr)


def dispatch(task_id, mgr):
    """Lease execution by native run so restart recovery cannot double-dispatch it."""
    from agent_manager.api import router as native
    with sqlite_db.SessionLocal() as db:
        row = db.get(ExternalSkillScan, task_id)
        if not row or not row.owns_scan or row.status not in ACTIVE:
            return
        run_id, bind = row.scan_run_id, db.get_bind()
    with _dispatch_lock:
        if run_id in _executions:
            return
        try:
            lease = acquire_lease("openapi_skill_run", run_id, "execute", 1, ttl_seconds=120, bind=bind)
        except LeaseLimitExceeded:
            return
        _executions[run_id] = (lease, bind)

    def work():
        try:
            execute_scan(task_id, mgr)
        except Exception as exc:
            logger.error("External Skill execution failed task=%s type=%s", task_id, type(exc).__name__)
        finally:
            with _dispatch_lock:
                _executions.pop(run_id, None)
                release_lease(lease, bind=bind)
    try:
        native._scan_executor.submit(work)
    except Exception:
        with _dispatch_lock:
            _executions.pop(run_id, None)
            release_lease(lease, bind=bind)
        raise


def maintain(mgr):
    # Keep leases alive while queued or executing; an exited process stops renewing.
    with _dispatch_lock:
        for lease, bind in _executions.values():
            with bind.begin() as connection:
                connection.exec_driver_sql("UPDATE request_leases SET expires_at = ? WHERE lease_id = ?",
                                           (datetime.utcnow() + timedelta(seconds=120), lease))
    reconcile(mgr)
    with sqlite_db.SessionLocal() as db:
        task_ids = [r.task_id for r in db.query(ExternalSkillScan).filter(
            ExternalSkillScan.status.in_(ACTIVE), ExternalSkillScan.owns_scan.is_(True)).all()]
    for task_id in task_ids:
        dispatch(task_id, mgr)


async def report_loop():
    from agent_manager.api.router import get_manager
    while True:
        try:
            await run_in_threadpool(maintain, get_manager())
        except Exception as exc:
            logger.error("External Skill report synchronization failed type=%s", type(exc).__name__)
        try:
            from .openapi_agents import reconcile as reconcile_agents
            await run_in_threadpool(reconcile_agents)
        except Exception as exc:
            logger.error("External Agent report synchronization failed type=%s", type(exc).__name__)
        await asyncio.sleep(5)
