"""Permission-scoped, metadata-only aggregates for the platform overview."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from agent_manager.api.router import get_manager
from agent_manager.core.manager import AgentManager
from .. import auth, iam, models
from ..aidr_models import AidrEvent, AidrHookEvent
from ..config import settings
from ..sqlite_db import get_db
from .clients import _CLIENT_ONLINE_WINDOW
from .security_scans import _accessible_tasks_query

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


def _stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


@router.get("/overview")
def overview(
    days: int = Query(7, ge=7, le=30),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
    manager: AgentManager = Depends(get_manager),
):
    iam.check(db, user, "dashboard:view")
    permissions = iam.permission_codes(db, user)
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = {"as_of": _stamp(now), "timezone": "UTC", "assets": {}, "skills": None,
              "todos": {"counts": {}, "items": [], "limit_per_type": 20},
              "runtime": {}, "activity": [], "activity_sources": [], "trend": None}
    assets, todos, activity = result["assets"], result["todos"], result["activity"]

    if "agents:view" in permissions:
        query = db.query(models.ManagedAgent)
        if user.role != "super_admin":
            query = query.filter(models.ManagedAgent.created_by == user.username)
        assets["agents"] = query.count()
    if "models:view" in permissions:
        assets["models"] = db.query(models.ModelEndpoint).count()

    if "skills:view" in permissions:
        result["activity_sources"].append("skill")
        summary = manager.dashboard_stats()
        assets["skills"] = summary["total"]
        result["skills"] = {key: summary[key] for key in ("total", "risk_counts")}
        todos["counts"]["skill"] = summary["status_counts"].get("VETTED", 0)
        for row in summary["todos"]:
            todos["items"].append({"id": f"skill-{row['skill_id']}", "type": "skill",
                "name": row["name"], "risk": row["risk_level"], "created_at": row["submitted_at"],
                "target_id": row["skill_id"], "context": ""})
        for event in manager.audit(since=(now - timedelta(days=7)).replace(tzinfo=timezone.utc), limit=8):
            activity.append({"id": f"skill-{event.event_id}", "source": "skill",
                "event": event.event_type, "name": event.skill_name or event.skill_id or "",
                "created_at": _stamp(event.timestamp), "target_id": event.skill_id})

    if "mcp:view" in permissions:
        result["activity_sources"].append("mcp")
        assets["mcp"] = db.query(models.McpServer).count()
        pending = db.query(models.McpToolApproval).filter(
            models.McpToolApproval.request_id.is_not(None),
            models.McpToolApproval.status == "pending",
            models.McpToolApproval.expires_at >= now,
        )
        todos["counts"]["mcp"] = pending.count()
        rows = (pending.outerjoin(models.McpTool, models.McpTool.id == models.McpToolApproval.tool_id)
                .add_columns(models.McpTool.risk_level)
                .order_by(models.McpToolApproval.created_at.desc(), models.McpToolApproval.id.desc()).limit(20).all())
        for row, risk in rows:
            todos["items"].append({"id": f"mcp-{row.request_id}", "type": "mcp", "name": row.tool_name,
                "risk": risk or "high", "created_at": _stamp(row.created_at),
                "target_id": row.request_id, "context": row.gateway_slug})
        audits = db.query(models.McpCallAudit)
        result["runtime"]["mcp_denied_today"] = audits.filter(
            models.McpCallAudit.created_at >= today, models.McpCallAudit.created_at <= now,
            models.McpCallAudit.status == "denied").count()
        for row in audits.options(load_only(models.McpCallAudit.id, models.McpCallAudit.status,
                models.McpCallAudit.tool_name, models.McpCallAudit.gateway_slug,
                models.McpCallAudit.created_at, models.McpCallAudit.approval_request_id)).filter(models.McpCallAudit.created_at >= now - timedelta(days=7),
                                 models.McpCallAudit.created_at <= now).order_by(
                models.McpCallAudit.created_at.desc(), models.McpCallAudit.id.desc()).limit(8):
            activity.append({"id": f"mcp-{row.id}", "source": "mcp", "event": row.status,
                "name": row.tool_name or row.gateway_slug, "created_at": _stamp(row.created_at),
                "target_id": row.approval_request_id})

    if "scans:view" in permissions and settings.AGENT_SECURITY_SCANNING_ENABLED:
        result["activity_sources"].append("scan")
        occurred_at = func.coalesce(models.SecurityScanTask.completed_at, models.SecurityScanTask.updated_at)
        for row in _accessible_tasks_query(db, user).options(load_only(
                models.SecurityScanTask.id, models.SecurityScanTask.task_id, models.SecurityScanTask.status,
                models.SecurityScanTask.target_id, models.SecurityScanTask.completed_at, models.SecurityScanTask.updated_at)).filter(
                occurred_at >= now - timedelta(days=7), occurred_at <= now,
        ).order_by(occurred_at.desc(), models.SecurityScanTask.id.desc()).limit(8):
            activity.append({"id": f"scan-{row.task_id}", "source": "scan", "event": row.status,
                "name": row.target_id, "created_at": _stamp(row.completed_at or row.updated_at),
                "target_id": row.task_id})

    if "clients:view" in permissions:
        clients = db.query(models.ManagedClient)
        if user.role != "super_admin":
            clients = clients.filter(models.ManagedClient.registered_by == user.username)
        assets["clients"] = {"total": clients.count(), "online": clients.filter(
            models.ManagedClient.last_seen_at >= now - _CLIENT_ONLINE_WINDOW).count()}
        visible = clients.with_entities(models.ManagedClient.client_id).subquery()
        reporting_clients = set()
        evidence_count = 0
        for model in (AidrEvent, AidrHookEvent):
            records = db.query(model.client_id, func.count(model.id)).filter(
                model.client_id.in_(select(visible.c.client_id)), model.received_at >= now - timedelta(hours=24),
                model.received_at <= now, model.expired_at.is_(None))
            for client_id, count in records.group_by(model.client_id):
                evidence_count += count
                reporting_clients.add(client_id)
        result["runtime"]["aidr"] = {"reporting_clients": len(reporting_clients),
            "records": evidence_count, "hours": 24}

    if "privacy_audit:view" in permissions:
        result["runtime"]["model_blocked_today"] = db.query(models.LlmRequestAudit).filter(
            models.LlmRequestAudit.created_at >= today, models.LlmRequestAudit.created_at <= now,
            models.LlmRequestAudit.status == "blocked").count()
        start = today - timedelta(days=days - 1)
        rows = db.query(func.date(models.LlmUsageMetric.created_at), func.count(models.LlmUsageMetric.id)).filter(
            models.LlmUsageMetric.created_at >= start, models.LlmUsageMetric.created_at <= now,
        ).group_by(func.date(models.LlmUsageMetric.created_at)).all()
        counts = dict(rows)
        result["trend"] = {"days": days, "series": [
            {"date": (start + timedelta(days=index)).date().isoformat(),
             "requests": counts.get((start + timedelta(days=index)).date().isoformat(), 0)}
            for index in range(days)]}

    todos["items"].sort(key=lambda row: row["created_at"], reverse=True)
    result["activity"] = sorted(activity, key=lambda row: row["created_at"], reverse=True)[:8]
    return result
