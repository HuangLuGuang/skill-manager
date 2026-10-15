"""Dispatch recurring scans through the normal authorization and Worker pipeline."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import text

from .. import models
from ..api_errors import ApiError
from ..scan_schedule_models import SecurityScanSchedule as Schedule
from ..scan_schedule_models import SecurityScanScheduleRun as Run
from ..scan_schedule_schemas import ScanTiming
from ..security_scan_controls import new_resource_id, unprotect_secret
from ..security_scan_schemas import SecurityTaskCreate
from ..sqlite_db import SessionLocal

logger = logging.getLogger(__name__)


def next_due(timing: ScanTiming, after: datetime) -> datetime:
    if timing.kind == "interval":
        return after + timedelta(minutes=timing.interval_minutes)
    minute, hour = timing.time.split(":")[1], timing.time.split(":")[0]
    expr = (
        timing.cron
        if timing.kind == "cron"
        else f"{minute} {hour} * * {timing.weekday if timing.kind == 'weekly' else '*'}"
    )
    local = after.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timing.timezone))
    return croniter(expr, local).get_next(datetime).astimezone(timezone.utc).replace(tzinfo=None)


def begin_write(db):
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def queue_run(db, plan, key, trigger, actor=None):
    existing = db.query(Run).filter_by(schedule_id=plan.schedule_id, request_key=key).first()
    if existing:
        return existing
    active = (
        db.query(Run).filter(Run.schedule_id == plan.schedule_id, Run.status.in_(["queued", "dispatching"])).first()
    )
    if not active:
        active = (
            db.query(Run)
            .join(models.SecurityScanTask, Run.task_id == models.SecurityScanTask.task_id)
            .filter(Run.schedule_id == plan.schedule_id, models.SecurityScanTask.status.in_(["pending", "running"]))
            .first()
        )
    run = Run(
        run_id=new_resource_id("ssr"),
        schedule_id=plan.schedule_id,
        request_key=key,
        task_json=plan.task_json,
        created_by=actor or plan.created_by,
        trigger=trigger,
        status="skipped" if active else "queued",
        error_code="scan_schedule.previous_running" if active else None,
    )
    db.add(run)
    db.flush()
    return run


def dispatch_due(factory=SessionLocal, now=None):
    from agent_manager.core.licensing import scan_allowed
    if not scan_allowed():
        return
    now = now or datetime.utcnow()
    with factory() as db:
        begin_write(db)
        for plan in (
            db.query(Schedule)
            .filter(Schedule.enabled.is_(True), Schedule.deleted_at.is_(None), Schedule.next_run_at <= now)
            .all()
        ):
            queue_run(db, plan, f"due:{plan.version}:{plan.next_run_at.isoformat()}", "scheduled")
            plan.next_run_at = next_due(ScanTiming(**json.loads(plan.timing_json)), now)
        db.commit()


def process_run(run_id, factory=SessionLocal):
    from agent_manager.core.licensing import scan_allowed
    if not scan_allowed():
        return
    from ..routers import security_scans as scans

    now = datetime.utcnow()
    with factory() as db:
        begin_write(db)
        run = db.get(Run, run_id)
        if not run or run.status not in {"queued", "dispatching"} or (run.lease_until and run.lease_until > now):
            db.rollback()
            return
        trigger = (
            db.query(models.SecurityTaskTrigger)
            .filter_by(actor=run.created_by, request_key=f"schedule:{run_id}")
            .first()
        )
        if trigger:
            run.task_id, run.status, run.lease_until = trigger.task_id, "submitted", None
            db.commit()
            return
        plan = db.get(Schedule, run.schedule_id)
        if plan.deleted_at or (run.trigger == "scheduled" and not plan.enabled):
            run.status, run.lease_until = "cancelled", None
            db.commit()
            return
        run.status, run.lease_until = "dispatching", now + timedelta(minutes=5)
        db.commit()
        try:
            user = db.query(models.User).filter_by(username=run.created_by, is_active=True).first()
            if not user or user.role == "security_auditor":
                raise ApiError(
                    403,
                    "scan_schedule.actor_unavailable",
                    "计划执行账号不可用",
                    "The schedule execution account is unavailable",
                )
            payload = json.loads(unprotect_secret(run.task_json))
            # Production approvals are single-use. Resolve a current approval on each occurrence.
            policy = scans._policy_or_404(db, payload["policy_id"])
            if policy.environment == "production" and policy.execution_mode == "active_safe":
                approval = (
                    db.query(models.SecurityScanApproval)
                    .filter_by(target_id=payload["target_id"], policy_id=payload["policy_id"], status="approved")
                    .order_by(models.SecurityScanApproval.created_at.desc())
                    .first()
                )
                payload["approval_id"] = approval.approval_id if approval else None
            result = asyncio.run(
                scans.create_task(SecurityTaskCreate(**payload, idempotency_key=f"schedule:{run_id}"), db, user)
            )
            run = db.get(Run, run_id)
            run.task_id, run.status, run.error_code = result.task_id, "submitted", None
        except ApiError as exc:
            db.rollback()
            run = db.get(Run, run_id)
            run.status = "awaiting_approval" if "approval" in exc.code else "failed"
            run.error_code = exc.code
        except Exception as exc:
            logger.warning("Scheduled scan dispatch failed for %s: %s", run_id, type(exc).__name__)
            db.rollback()
            run = db.get(Run, run_id)
            run.status, run.error_code = "failed", "scan_schedule.dispatch_failed"
        run.lease_until = None
        db.commit()


def tick(factory=SessionLocal):
    from ..config import settings

    if not settings.AGENT_SECURITY_SCANNING_ENABLED:
        return
    dispatch_due(factory)
    with factory() as db:
        ids = [
            x.run_id
            for x in db.query(Run).filter(Run.status.in_(["queued", "dispatching"])).order_by(Run.created_at).limit(50)
        ]
    for run_id in ids:
        process_run(run_id, factory)
