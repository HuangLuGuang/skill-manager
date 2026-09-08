import json
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, models
from ..api_errors import ApiError
from ..asset_lifecycle_schemas import RunCreate
from ..feature_flags import require_agent_security_scanning
from ..scan_schedule_models import SecurityScanSchedule as Schedule
from ..scan_schedule_models import SecurityScanScheduleRun as Run
from ..scan_schedule_schemas import ScanScheduleCreate, ScanScheduleUpdate, ScanTiming
from ..security_scan_controls import json_dumps, new_resource_id, protect_secret, unprotect_secret
from ..services import scan_schedules as scheduler
from ..sqlite_db import get_db
from . import security_scans as scans
from .asset_lifecycle import audit

router = APIRouter(
    prefix="/v1/agent-security", tags=["scan-schedules"], dependencies=[Depends(require_agent_security_scanning)]
)


def iso(value):
    return value.isoformat() + "Z" if value else None


def run_payload(db, run):
    task = None
    if run.task_id:
        task = db.query(models.SecurityScanTask).filter_by(task_id=run.task_id).first()
    return {
        "run_id": run.run_id,
        "task_id": run.task_id,
        "status": task.status if task else run.status,
        "error_code": task.error_code if task and task.error_code else run.error_code,
        "trigger": run.trigger,
        "created_at": iso(run.created_at),
    }


def payload(db, row, include_task=True):
    last = db.query(Run).filter_by(schedule_id=row.schedule_id).order_by(Run.created_at.desc()).first()
    cursor, preview = datetime.utcnow(), []
    timing = ScanTiming(**json.loads(row.timing_json))
    for _ in range(3):
        cursor = scheduler.next_due(timing, cursor)
        preview.append(iso(cursor))
    return {
        "schedule_id": row.schedule_id,
        "name": row.name,
        "target_id": row.target_id,
        "task": json.loads(unprotect_secret(row.task_json)) if include_task else None,
        "timing": timing.model_dump(),
        "enabled": row.enabled,
        "version": row.version,
        "next_run_at": iso(row.next_run_at) if row.enabled else None,
        "last_run": run_payload(db, last) if last else None,
        "preview": preview,
    }


def get_plan(db, plan_id, user):
    row = db.get(Schedule, plan_id)
    if not row or row.deleted_at:
        raise ApiError(404, "scan_schedule.not_found", "定时计划不存在", "Scan schedule not found")
    scans._require_target_access(db, user, scans._target_or_404(db, row.target_id))
    return row


def validate_task(db, task, user):
    scans._validate_scan_task_request(db, task, user)
    if task.continue_from_task_id or (
        task.scan_kind == "dify_asset_inventory" and task.inventory_source == "manual_dsl"
    ):
        raise ApiError(
            422,
            "scan_schedule.options_unsupported",
            "定时扫描需要独立会话和在线采集配置",
            "Scheduled scans require independent sessions and online inventory",
        )


@router.post("/scan-schedules/preview")
def preview_timing(body: ScanTiming, user=Depends(auth.get_current_active_user)):
    cursor, values = datetime.utcnow(), []
    for _ in range(3):
        cursor = scheduler.next_due(body, cursor)
        values.append(iso(cursor))
    return {"times": values}


@router.get("/scan-schedules")
def list_schedules(db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    return [
        payload(db, row, include_task=user.role in {"admin", "super_admin"})
        for row in db.query(Schedule).filter(Schedule.deleted_at.is_(None)).order_by(Schedule.created_at.desc())
        if scans._can_access_target(db, user, scans._target_or_404(db, row.target_id))
    ]


@router.post("/scan-schedules")
def create_schedule(
    body: ScanScheduleCreate, db: Session = Depends(get_db), user=Depends(auth.get_current_security_admin)
):
    scheduler.begin_write(db)
    validate_task(db, body.task, user)
    existing = db.query(Schedule).filter_by(created_by=user.username, request_key=body.idempotency_key).first()
    if existing:
        if (
            existing.name != body.name
            or json.loads(unprotect_secret(existing.task_json)) != body.task.model_dump()
            or json.loads(existing.timing_json) != body.timing.model_dump()
        ):
            raise ApiError(
                409,
                "agent_security.idempotency_conflict",
                "幂等键已用于不同请求",
                "Idempotency key already used for another request",
            )
        return payload(db, existing)
    row = Schedule(
        schedule_id=new_resource_id("ssc"),
        name=body.name,
        target_id=body.task.target_id,
        created_by=user.username,
        request_key=body.idempotency_key,
        task_json=protect_secret(json_dumps(body.task.model_dump())),
        timing_json=json_dumps(body.timing.model_dump()),
        enabled=body.enabled,
        next_run_at=scheduler.next_due(body.timing, datetime.utcnow()),
    )
    db.add(row)
    db.flush()
    if body.run_immediately:
        scheduler.queue_run(db, row, "initial", "manual")
    db.commit()
    audit(db, user, "scan_schedule.created", row.schedule_id)
    return payload(db, row)


@router.put("/scan-schedules/{plan_id}")
def update_schedule(
    plan_id: str, body: ScanScheduleUpdate, db: Session = Depends(get_db), user=Depends(auth.get_current_security_admin)
):
    scheduler.begin_write(db)
    row = get_plan(db, plan_id, user)
    if row.version != body.version:
        raise ApiError(409, "scan_schedule.conflict", "计划已变更，请刷新", "The schedule changed; refresh and retry")
    if body.task:
        validate_task(db, body.task, user)
        row.task_json, row.target_id = protect_secret(json_dumps(body.task.model_dump())), body.task.target_id
    changed_timing = json.loads(row.timing_json) != body.timing.model_dump()
    if changed_timing or (body.enabled and not row.enabled):
        row.next_run_at = scheduler.next_due(body.timing, datetime.utcnow())
    row.name, row.timing_json, row.enabled = body.name, json_dumps(body.timing.model_dump()), body.enabled
    row.version += 1
    db.commit()
    audit(db, user, "scan_schedule.updated", plan_id)
    return payload(db, row)


@router.delete("/scan-schedules/{plan_id}")
def delete_schedule(plan_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_security_admin)):
    scheduler.begin_write(db)
    row = get_plan(db, plan_id, user)
    row.enabled, row.deleted_at = False, datetime.utcnow()
    db.commit()
    audit(db, user, "scan_schedule.deleted", plan_id)
    return {"schedule_id": plan_id}


@router.post("/scan-schedules/{plan_id}/runs")
def run_schedule(
    plan_id: str, body: RunCreate, db: Session = Depends(get_db), user=Depends(auth.get_current_security_admin)
):
    scheduler.begin_write(db)
    row = get_plan(db, plan_id, user)
    run = scheduler.queue_run(db, row, f"manual:{body.idempotency_key}", "manual", actor=user.username)
    db.commit()
    audit(db, user, "scan_schedule.triggered", plan_id)
    return run_payload(db, run)


@router.get("/scan-schedules/{plan_id}/runs")
def list_runs(plan_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    get_plan(db, plan_id, user)
    return [
        run_payload(db, r)
        for r in db.query(Run).filter_by(schedule_id=plan_id).order_by(Run.created_at.desc()).limit(100)
    ]
