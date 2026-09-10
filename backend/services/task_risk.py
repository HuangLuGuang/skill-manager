"""Task-scoped risk snapshots: later dispositions cannot rewrite report results."""

import json

from sqlalchemy.dialects.sqlite import insert

from .. import models
from ..scan_schedule_models import SecurityScanSchedule, SecurityScanScheduleRun, SecurityTaskRiskScore
from ..security_scan_controls import AGENT_SCAN_SKILLS, json_dumps, unprotect_secret
from .agent_risk import SCORE_VERSION, issue_key, score_issues


def report_score(db, task):
    existing = db.get(SecurityTaskRiskScore, task.task_id)
    if existing:
        return json.loads(existing.payload_json)
    if task.scan_kind in {"dify_asset_inventory", "control_plane_validation"}:
        return None
    findings = db.query(models.SecurityFinding).filter_by(task_id=task.task_id).all()
    distinct = {}
    unverified_findings = 0
    for row in findings:
        evidence = json.loads(row.evidence_json or '{}')
        if task.scan_kind == 'mcp_risk_scan' and evidence.get('model_assessment') and evidence.get('confirmed_vulnerability') is False:
            unverified_findings += 1
            continue
        key = issue_key(row)
        value = {"issue_id": key, "finding_id": row.finding_id, "severity": row.severity}
        if key not in distinct or score_issues([value])[0] > score_issues([distinct[key]])[0]:
            distinct[key] = value
    score, contributions = score_issues(list(distinct.values()))
    cases = db.query(models.SecurityScanCase).filter_by(task_id=task.task_id).all()
    planned_count = len(cases)
    if task.scan_kind == "agent_risk_scan":
        options = json.loads(unprotect_secret(task.scan_options_encrypted) or "{}")
        planned_count = len(options.get("skills") or AGENT_SCAN_SKILLS)
        cases = [c for c in cases if (c.external_case_id or "").startswith("aig-rule:")]
        completed = sum(
            c.status in {"passed", "failed"}
            and json.loads(c.response_summary_json).get("execution_status") == "completed"
            and json.loads(c.response_summary_json).get("dialogue_calls", 0) > 0
            for c in cases
        )
    else:
        completed = sum(c.status in {"passed", "failed"} for c in cases)
    complete = bool(cases) and completed == planned_count and task.status == "succeeded"
    score = score if score or (complete and not unverified_findings) else None
    binding = db.get(models.AgentScanBinding, task.task_id)
    result = {
        "score": score,
        "unverified_findings": unverified_findings,
        "status": "complete" if complete and not unverified_findings else "partial" if completed or findings else "unassessed",
        "level": "unassessed"
        if score is None
        else "critical"
        if score >= 90
        else "high"
        if score >= 65
        else "medium"
        if score >= 35
        else "low"
        if score
        else "info",
        "algorithm_version": SCORE_VERSION,
        "completed_checks": completed,
        "total_checks": planned_count,
        "contributions": contributions,
        "config_fingerprint": binding.config_fingerprint if binding else None,
        "assessed_at": task.completed_at.isoformat() + "Z" if task.completed_at else None,
    }
    if task.status in {"succeeded", "failed", "cancelled", "timed_out", "blocked"}:
        db.execute(
            insert(SecurityTaskRiskScore)
            .values(task_id=task.task_id, payload_json=json_dumps(result))
            .on_conflict_do_nothing(index_elements=["task_id"])
        )
    return result


def origins_for_tasks(db, tasks):
    tasks = {task.task_id: task for task in tasks}
    result = {task_id: [] for task_id in tasks}
    if not tasks:
        return result
    rows = (
        db.query(SecurityScanScheduleRun, SecurityScanSchedule)
        .join(SecurityScanSchedule, SecurityScanScheduleRun.schedule_id == SecurityScanSchedule.schedule_id)
        .filter(SecurityScanScheduleRun.task_id.in_(tasks))
        .all()
    )
    for run, plan in rows:
        origin = {"kind": "scheduled", "schedule_id": plan.schedule_id, "name": plan.name, "deleted": bool(plan.deleted_at)}
        if origin not in result[run.task_id]:
            result[run.task_id].append(origin)
    changed = {row.task_id for row in db.query(models.SecurityTaskTrigger).filter(
        models.SecurityTaskTrigger.task_id.in_(tasks), models.SecurityTaskTrigger.kind == "asset_change"
    ).all()}
    for task_id, task in tasks.items():
        if (task.idempotency_key or "").startswith("asset-change:") or task_id in changed:
            result[task_id].append({"kind": "asset_change"})
        if not result[task_id]:
            result[task_id] = [{"kind": "manual"}]
    return result


def origins(db, task):
    return origins_for_tasks(db, [task])[task.task_id]
