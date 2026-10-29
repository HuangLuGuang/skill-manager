"""Permission-scoped, metadata-only aggregates for the platform overview."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from agent_manager.api.router import get_manager
from agent_manager.core.manager import AgentManager
from .. import auth, iam, models
from ..aidr_models import AidrEvent, AidrHookEvent
from ..sqlite_db import get_db
from .clients import _CLIENT_ONLINE_WINDOW
from ..dashboard_agents import analytics
from ..api_errors import ApiError
from ..model_switch import AGENTS
from ..client_discovery import SEEDS

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


def _reported_instances(db, user):
    agent = models.ClientAgent
    local_id = func.coalesce(func.nullif(func.trim(agent.local_agent_id), ''), agent.agent_type)
    rows = db.query(agent.id, agent.client_id, local_id.label('local_agent_id'),
                    func.coalesce(func.nullif(func.trim(agent.agent_type), ''), '').label('product'),
                    func.row_number().over(partition_by=(agent.client_id, local_id),
                        order_by=(agent.last_scanned_at.desc(), agent.id.desc())).label('position'))
    if user.role != 'super_admin':
        rows = rows.filter(agent.client_id.in_(select(models.ManagedClient.client_id).where(
            models.ManagedClient.registered_by == user.username)))
    ranked = rows.subquery()
    return db.query(ranked.c.id, ranked.c.client_id, ranked.c.local_agent_id, ranked.c.product).filter(ranked.c.position == 1)


@router.get('/agent-instances')
def agent_instances(
    products: list[str] = Query(..., min_length=1, max_length=100),
    page: int = Query(1, ge=1, le=100000), page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_active_user),
):
    iam.check(db, user, 'dashboard:view')
    iam.check(db, user, 'clients:view')
    instances = _reported_instances(db, user).subquery()
    query = db.query(instances).filter(instances.c.product.in_(products), instances.c.product != 'global-skills')
    total = query.count()
    page = min(page, max(1, (total + page_size - 1) // page_size))
    selected = query.order_by(instances.c.client_id, instances.c.local_agent_id).offset((page - 1) * page_size).limit(page_size).subquery()
    rows = db.query(selected.c.id, selected.c.client_id, models.ManagedClient.name.label('client_name'),
                    selected.c.local_agent_id, selected.c.product, models.ClientAgent.agent_version,
                    models.ClientAgent.install_path, models.ClientAgent.last_scanned_at).join(
        models.ClientAgent, models.ClientAgent.id == selected.c.id).join(
        models.ManagedClient, models.ManagedClient.client_id == selected.c.client_id).order_by(selected.c.client_id, selected.c.local_agent_id).all()
    return {'items': [{**dict(row._mapping), 'last_scanned_at': _stamp(row.last_scanned_at)} for row in rows], 'total': total, 'page': page}


@router.get('/agent-analytics')
def agent_analytics(
    kind: Literal['behavior', 'risk'],
    source: Literal['', 'hooks', 'logs', 'system'] = '',
    days: int = Query(7, ge=7, le=30),
    details: bool = False,
    page: int = Query(1, ge=1, le=100000), page_size: int = Query(10, ge=1, le=100),
    client_id: str = Query('', max_length=128), agent: str = Query('', max_length=32),
    unknown_agent: bool = False,
    scope: Literal['current', 'period'] = 'current',
    since: int | None = Query(None, ge=0, le=253402300798),
    until: int | None = Query(None, ge=1, le=253402300799),
    category: Literal['', 'commands', 'other', 'failures'] = '',
    tool: str = Query('', max_length=256),
    program: str = Query('', max_length=64),
    severity: Literal['', 'high', 'medium'] = '',
    risk_code: str = Query('', max_length=64),
    disposition: Literal['', 'open', 'accepted', 'false_positive', 'resolved'] = '',
    sort_by: Literal['time', 'client_id', 'agent', 'tool', 'severity'] = 'time',
    sort_order: Literal['asc', 'desc'] = 'desc',
    db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_active_user),
):
    iam.check(db, user, 'dashboard:view')
    iam.check(db, user, 'clients:view')
    if (days not in (7, 30) or (since is None) != (until is None) or
            (since is not None and not 0 < until - since <= 30 * 86400) or
            (kind == 'behavior' and source == 'system')):
        raise ApiError(422, 'aidr.overview_range_invalid', '统计范围无效', 'Invalid analytics range')
    return analytics(db, user, kind=kind, source=(source or 'hooks') if kind == 'behavior' else source,
                     days=days, now=datetime.utcnow(), details=details, page=page, page_size=page_size,
                     client_id=client_id, agent=agent, unknown_agent=unknown_agent, scope=scope, since=since, until=until,
                     category=category, tool=tool, program=program, severity=severity, risk_code=risk_code, disposition=disposition,
                     sort_by=sort_by, sort_order=sort_order)


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
              "runtime": {}, "trend": None}
    assets, todos = result["assets"], result["todos"]

    if "agents:view" in permissions:
        query = db.query(models.ManagedAgent)
        if user.role != "super_admin":
            query = query.filter(models.ManagedAgent.created_by == user.username)
        assets["agents"] = query.count()
    if "models:view" in permissions:
        assets["models"] = db.query(models.ModelEndpoint).count()

    if "skills:view" in permissions:
        summary = manager.dashboard_stats()
        assets["skills"] = summary["total"]
        result["skills"] = {key: summary[key] for key in ("total", "risk_counts")}
        todos["counts"]["skill"] = summary["status_counts"].get("VETTED", 0)
        for row in summary["todos"]:
            todos["items"].append({"id": f"skill-{row['skill_id']}", "type": "skill",
                "name": row["name"], "risk": row["risk_level"], "created_at": row["submitted_at"],
                "target_id": row["skill_id"], "context": ""})

    if "mcp:view" in permissions:
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
        # MCP 今日与调用审计日期筛选统一使用北京时间，数据库保留 UTC。
        mcp_today = (now + timedelta(hours=8)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
        result["runtime"]["mcp_denied_today"] = audits.filter(
            models.McpCallAudit.created_at >= mcp_today,
            models.McpCallAudit.created_at < mcp_today + timedelta(days=1),
            models.McpCallAudit.status == "denied").count()

    if "clients:view" in permissions:
        clients = db.query(models.ManagedClient)
        if user.role != "super_admin":
            clients = clients.filter(models.ManagedClient.registered_by == user.username)
        assets["clients"] = {"total": clients.count(), "online": clients.filter(
            models.ManagedClient.last_seen_at >= now - _CLIENT_ONLINE_WINDOW).count()}
        visible = clients.with_entities(models.ManagedClient.client_id).subquery()
        ids = select(visible.c.client_id)
        reported_agents = db.query(models.ClientAgent).filter(models.ClientAgent.client_id.in_(ids))
        instances = _reported_instances(db, user).subquery()
        product_counts = db.query(instances.c.product, func.count()).group_by(instances.c.product).order_by(func.count().desc(), instances.c.product).all()
        product_labels = {**{key: spec['label'] for key, spec in AGENTS.items()}, **{key: name for key, name, _ in SEEDS}}
        result['agent_products'] = [{'key': key, 'name': product_labels.get(key, key), 'value': count} for key, count in product_counts if key != 'global-skills']
        result['reported_assets'] = {
            'agents': sum(count for _, count in product_counts),
            'skills': db.query(models.ClientSkillInstall).filter(models.ClientSkillInstall.client_id.in_(ids)).count(),
        }
        inventory = models.ClientAgent.capabilities_json
        result['reported_assets']['mcp'] = reported_agents.with_entities(func.coalesce(func.sum(func.json_array_length(inventory, '$.asset_inventory.mcp_servers')), 0)).scalar()
        result['reported_assets']['plugins'] = reported_agents.with_entities(func.coalesce(func.sum(func.json_array_length(inventory, '$.asset_inventory.plugins')), 0)).scalar()
        snapshots = reported_agents.with_entities(inventory).subquery()
        plugins = func.json_each(snapshots.c.capabilities_json, '$.asset_inventory.plugins').table_valued('value').alias('plugins')
        plugin_counts = db.query(func.coalesce(func.sum(func.json_array_length(plugins.c.value, '$.mcp_servers')), 0),
                                 func.coalesce(func.sum(func.json_array_length(plugins.c.value, '$.skills')), 0)).select_from(snapshots).join(plugins, true()).one()
        result['reported_assets']['mcp'] += plugin_counts[0]
        result['reported_assets']['pluginSkills'] = plugin_counts[1]
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
    return result
