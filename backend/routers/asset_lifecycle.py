import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..api_errors import ApiError
from ..asset_lifecycle_schemas import AssetLinksUpdate, IssueReview, RunCreate, SourceConfig, SourceCreate, SourceUpdate
from ..feature_flags import require_agent_security_scanning
from ..security_scan_controls import json_dumps, new_resource_id
from ..security_scan_schemas import SecurityTaskCreate
from ..services import agent_risk, asset_sync
from ..sqlite_db import get_db
from . import security_scans as scans

router = APIRouter(
    prefix="/v1/agent-security", tags=["asset-lifecycle"], dependencies=[Depends(require_agent_security_scanning)]
)


def audit(db, user, kind, resource_id, details=None):
    scans._audit(
        db,
        event_type=kind,
        actor=user.username,
        resource_type="asset_lifecycle",
        resource_id=resource_id,
        action=kind,
        details=details or {},
    )


def source_row(db, source_id, user):
    row = db.get(models.AssetSource, source_id)
    if not row:
        raise ApiError(404, "asset_sync.source_not_found", "资产来源不存在", "Asset source not found")
    scans._require_target_access(db, user, scans._target_or_404(db, row.template_target_id))
    return row


def agent_row(db, agent_id, user):
    row = db.get(models.SecurityAgentAsset, agent_id)
    if not row:
        raise ApiError(404, "agent_risk.agent_not_found", "智能体不存在", "Managed agent not found")
    scans._require_target_access(db, user, scans._target_or_404(db, row.target_id))
    return row


def source_payload(row):
    config = SourceConfig(**json.loads(row.config_json))
    cursor = datetime.utcnow()
    next_times = []
    for _ in range(5):
        cursor = asset_sync.next_due(config, cursor, anchor=row.next_run_at)
        next_times.append(cursor.isoformat() + "Z")
    return {
        "source_id": row.source_id,
        "name": row.name,
        "template_target_id": row.template_target_id,
        "policy_id": row.policy_id,
        "version": row.version,
        "enabled": row.enabled,
        "config": config.model_dump(),
        "next_run_at": row.next_run_at.isoformat() + "Z" if row.next_run_at else None,
        "last_success_at": row.last_success_at.isoformat() + "Z" if row.last_success_at else None,
        "active_run_id": row.active_run_id,
        "schedule_preview": next_times,
    }


def validate_source(db, body, user):
    target = scans._target_or_404(db, body.template_target_id)
    if target.connector_type != "dify":
        raise ApiError(422, "asset_sync.dify_required", "请选择 Dify 来源目标", "Select a Dify source target")
    scans._validate_scan_task_request(
        db,
        SecurityTaskCreate(
            target_id=target.target_id,
            policy_id=body.policy_id,
            scan_kind="dify_asset_inventory",
            idempotency_key="source-validation",
        ),
        user,
    )
    if body.config.auto_scan_policy_id:
        policy = scans._policy_or_404(db, body.config.auto_scan_policy_id)
        if not policy.enabled or policy.environment != target.environment:
            raise ApiError(
                422,
                "asset_sync.policy_unavailable",
                "自动扫描策略未启用或环境不匹配",
                "The automatic scan policy is unavailable or has a different environment",
            )


@router.get("/asset-sources")
def list_sources(db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_active_user)):
    return [
        source_payload(row)
        for row in db.query(models.AssetSource).order_by(models.AssetSource.created_at.desc())
        if scans._can_access_target(db, user, scans._target_or_404(db, row.template_target_id))
    ]


@router.post("/asset-sources")
def create_source(
    body: SourceCreate, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_security_admin)
):
    validate_source(db, body, user)
    existing = db.query(models.AssetSource).filter_by(template_target_id=body.template_target_id).first()
    if existing:
        if (
            existing.name == body.name
            and existing.policy_id == body.policy_id
            and json.loads(existing.config_json) == body.config.model_dump()
        ):
            return source_payload(existing)
        raise ApiError(
            409, "asset_sync.source_exists", "该目标已有资产来源配置", "This target already has an asset source"
        )
    row = models.AssetSource(
        source_id=new_resource_id("aso"),
        name=body.name,
        template_target_id=body.template_target_id,
        policy_id=body.policy_id,
        created_by=user.username,
        config_json=json_dumps(body.config.model_dump()),
        connection_hash=asset_sync.connection_hash(scans._target_or_404(db, body.template_target_id)),
        enabled=body.config.enabled,
        next_run_at=asset_sync.next_due(body.config, datetime.utcnow()),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(
            409, "asset_sync.source_exists", "该目标已有资产来源配置", "This target already has an asset source"
        ) from None
    audit(db, user, "asset_sync.source_created", row.source_id)
    return source_payload(row)


@router.put("/asset-sources/{source_id}")
def update_source(
    source_id: str,
    body: SourceUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_security_admin),
):
    row = source_row(db, source_id, user)
    validate_source(
        db,
        SourceCreate(
            name=body.name, template_target_id=row.template_target_id, policy_id=body.policy_id, config=body.config
        ),
        user,
    )
    try:
        changed = (
            db.query(models.AssetSource)
            .filter_by(source_id=source_id, version=body.version, active_run_id=None)
            .update(
                {
                    "name": body.name,
                    "policy_id": body.policy_id,
                    "config_json": json_dumps(body.config.model_dump()),
                    "version": body.version + 1,
                    "enabled": body.config.enabled,
                    "created_by": user.username,
                    "connection_hash": asset_sync.connection_hash(scans._target_or_404(db, row.template_target_id)),
                    "next_run_at": asset_sync.next_due(body.config, datetime.utcnow()),
                },
                synchronize_session=False,
            )
        )
    except IntegrityError:
        db.rollback()
        raise ApiError(
            409, "asset_sync.source_exists", "该连接已有资产来源配置", "This connection already has an asset source"
        ) from None
    if not changed:
        db.rollback()
        raise ApiError(
            409,
            "asset_sync.config_conflict",
            "配置已变化或仍有同步运行，请刷新后重试",
            "The configuration changed or a synchronization run is active; refresh and retry",
        )
    for agent in db.query(models.SecurityAgentAsset).filter_by(source_id=source_id):
        agent_risk.enqueue(db, agent.target_id, kind="scope_updated")
    db.commit()
    db.refresh(row)
    audit(db, user, "asset_sync.source_updated", source_id, {"version": row.version})
    return source_payload(row)


@router.post("/asset-sources/{source_id}/connection-tests")
def test_source(
    source_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_security_admin)
):
    row = source_row(db, source_id, user)
    client = asset_sync.discovery_client(db, row)
    try:
        client.get_app_detail()
    except asset_sync.DifyConsoleError as exc:
        audit(db, user, "asset_sync.connection_tested", source_id, {"error_code": exc.code})
        return {"reachable": False, "error_code": exc.code}
    audit(db, user, "asset_sync.connection_tested", source_id, {"reachable": True})
    return {"reachable": True}


@router.post("/asset-sources/{source_id}/sync-runs")
def start_sync(
    source_id: str,
    body: RunCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_security_admin),
):
    row = source_row(db, source_id, user)
    asset_sync.source_context(db, row)
    run = asset_sync.start_run(db, row, f"manual:{body.idempotency_key}")
    db.commit()
    audit(db, user, "asset_sync.run_requested", run.run_id)
    return {"run_id": run.run_id, "status": run.status}


@router.get("/asset-sources/{source_id}/sync-runs")
def list_runs(
    source_id: str,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    source_row(db, source_id, user)
    return [
        {
            "run_id": r.run_id,
            "status": r.status,
            "created_at": r.created_at.isoformat() + "Z",
            "error_code": r.error_code,
        }
        for r in db.query(models.AssetSyncRun)
        .filter_by(source_id=source_id)
        .order_by(models.AssetSyncRun.created_at.desc())
        .limit(limit)
    ]


def run_row(db, run_id, user):
    run = db.get(models.AssetSyncRun, run_id)
    if not run:
        raise ApiError(404, "asset_sync.run_not_found", "同步批次不存在", "Synchronization run not found")
    source_row(db, run.source_id, user)
    return run


@router.get("/asset-sync-runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_active_user)):
    run = run_row(db, run_id, user)
    items = db.query(models.AssetSyncRunItem).filter_by(run_id=run_id).all()
    return {
        "run_id": run_id,
        "status": run.status,
        "error_code": run.error_code,
        "enumeration_complete": run.enumeration_complete,
        "discovered_count": len(json.loads(run.discovered_json or "[]")),
        "items": [
            {
                "external_id": x.external_id,
                "target_id": x.target_id,
                "task_id": x.task_id,
                "status": x.status,
                "change_kind": x.change_kind,
                "error_code": x.error_code,
            }
            for x in items
        ],
    }


@router.post("/asset-sync-runs/{run_id}/cancel")
def cancel_run(
    run_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_security_admin)
):
    run = run_row(db, run_id, user)
    if run.status not in asset_sync.TERMINAL:
        run.cancel_requested = True
        db.commit()
        audit(db, user, "asset_sync.run_cancel_requested", run_id)
    return {"run_id": run_id, "status": run.status, "cancel_requested": run.cancel_requested}


@router.get("/managed-agents")
def list_agents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    query = db.query(models.SecurityTarget).filter(models.SecurityTarget.asset_type == "agent")
    if user.role not in scans.SECURITY_READER_ROLES:
        groups = scans._group_ids(db, user.id)
        query = query.filter(
            or_(models.SecurityTarget.owner_user_id == user.id, models.SecurityTarget.owner_group_id.in_(groups))
        )
    total = query.count()
    result = []
    for target in (
        query.order_by(models.SecurityTarget.name, models.SecurityTarget.target_id).offset(offset).limit(limit)
    ):
        agent = agent_risk.managed_agent(db, target.target_id)
        # Serialize assessment updates on SQLite before reading the input snapshot.
        db.query(models.SecurityAgentAsset).filter_by(agent_id=agent.agent_id).update(
            {"revision": models.SecurityAgentAsset.revision}, synchronize_session=False
        )
        db.refresh(agent)
        result.append(
            {
                "agent_id": agent.agent_id,
                "target_id": target.target_id,
                "source_id": agent.source_id,
                "name": agent.display_name or target.name,
                "observation_status": agent.observation_status,
                "risk": agent_risk.calculate(db, agent),
            }
        )
    db.commit()
    return {"items": result, "total": total}


@router.get("/managed-agents/{agent_id}/risk")
def get_risk(agent_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_active_user)):
    agent = agent_row(db, agent_id, user)
    db.query(models.SecurityAgentAsset).filter_by(agent_id=agent_id).update(
        {"revision": models.SecurityAgentAsset.revision}, synchronize_session=False
    )
    db.refresh(agent)
    payload = agent_risk.calculate(db, agent)
    db.commit()
    return payload


@router.get("/managed-agents/{agent_id}/risk-history")
def get_history(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    agent_row(db, agent_id, user)
    return [
        {**json.loads(x.payload_json), "assessment_id": x.assessment_id, "assessed_at": x.created_at.isoformat() + "Z"}
        for x in db.query(models.AgentRiskAssessment)
        .filter_by(agent_id=agent_id)
        .order_by(models.AgentRiskAssessment.created_at.desc())
        .limit(limit)
    ]


@router.get("/managed-agents/{agent_id}/risk-issues")
def get_issues(agent_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_active_user)):
    agent = agent_row(db, agent_id, user)
    db.query(models.SecurityAgentAsset).filter_by(agent_id=agent_id).update(
        {"revision": models.SecurityAgentAsset.revision}, synchronize_session=False
    )
    db.refresh(agent)
    rows = agent_risk.reconcile_issues(db, agent)
    payload = [
        {
            "issue_id": x.issue_id,
            "status": x.status,
            "severity": x.severity,
            "finding_id": x.finding_id,
            "evidence_ids": json.loads(x.evidence_json),
            "closure_task_id": x.closure_task_id,
            "reviewed_by": x.reviewed_by,
            "reviewed_at": x.reviewed_at,
            "review_comment": x.review_comment,
        }
        for x in rows
    ]
    db.commit()
    return payload


@router.put("/managed-agents/{agent_id}/related-targets")
def set_related_targets(
    agent_id: str,
    body: AssetLinksUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_security_admin),
):
    agent = agent_row(db, agent_id, user)
    owner = scans._target_or_404(db, agent.target_id)
    target_ids = sorted(set(body.target_ids))
    for target_id in target_ids:
        target = scans._target_or_404(db, target_id)
        if target.asset_type != "mcp" or (target.owner_user_id, target.owner_group_id) != (
            owner.owner_user_id,
            owner.owner_group_id,
        ):
            raise ApiError(
                422,
                "agent_risk.link_scope_invalid",
                "关联 MCP 目标必须具有相同归属和访问范围",
                "Linked MCP targets must have the same ownership and access scope",
            )
    db.query(models.AgentAssetLink).filter_by(agent_id=agent_id).delete(synchronize_session=False)
    for target_id in target_ids:
        db.add(models.AgentAssetLink(agent_id=agent_id, target_id=target_id, created_by=user.username))
    agent_risk.enqueue(db, agent.target_id, kind="scope_updated")
    db.commit()
    audit(db, user, "agent_risk.links_updated", agent_id, {"target_ids": target_ids})
    return {"target_ids": target_ids}


@router.patch("/managed-agents/{agent_id}/risk-issues/{issue_id}")
def review_issue(
    agent_id: str,
    issue_id: str,
    body: IssueReview,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_security_admin),
):
    agent = agent_row(db, agent_id, user)
    issue = db.query(models.AgentRiskIssue).filter_by(agent_id=agent_id, issue_id=issue_id).first()
    if not issue:
        raise ApiError(404, "agent_risk.issue_not_found", "风险项不存在", "Risk issue not found")
    if body.status == "resolved" and (
        not body.closure_task_id or not agent_risk.verify_closure(db, agent, issue, body.closure_task_id)
    ):
        raise ApiError(
            409,
            "agent_risk.closure_unverified",
            "缺少当前资产版本的可比复扫关闭证据",
            "Comparable rescan closure evidence for the current asset version is required",
        )
    issue.status, issue.review_comment = body.status, body.comment
    issue.reviewed_by, issue.reviewed_at = user.username, datetime.utcnow()
    issue.reviewed_config_fingerprint = agent.config_fingerprint
    issue.closure_task_id = body.closure_task_id if body.status == "resolved" else None
    agent_risk.enqueue(db, agent.target_id, kind="finding_updated")
    db.commit()
    audit(
        db,
        user,
        "agent_risk.issue_reviewed",
        issue_id,
        {"status": body.status, "closure_task_id": issue.closure_task_id},
    )
    return {"issue_id": issue_id, "status": issue.status}


@router.get("/targets/{target_id}/risk-profile")
def target_risk_profile(target_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    target = scans._target_or_404(db, target_id)
    scans._require_target_access(db, user, target)
    agent = agent_risk.managed_agent(db, target_id)
    risk = agent_risk.calculate(db, agent)
    source = db.get(models.AssetSource, agent.source_id) if agent.source_id else None
    latest = (
        db.query(models.SecurityScanTask)
        .filter_by(target_id=target_id)
        .order_by(models.SecurityScanTask.created_at.desc())
        .first()
    )
    plans = db.query(models.SecurityScanSchedule).filter_by(target_id=target_id, deleted_at=None).all()
    db.commit()
    return {
        "agent_id": agent.agent_id,
        "target_id": target_id,
        "name": target.name,
        "risk": risk,
        "observation_status": agent.observation_status,
        "latest_scan": {"task_id": latest.task_id, "created_at": latest.created_at.isoformat() + "Z"}
        if latest
        else None,
        "schedules": [{"schedule_id": p.schedule_id, "name": p.name, "enabled": p.enabled} for p in plans],
        "source": source_payload(source) if source else None,
    }
