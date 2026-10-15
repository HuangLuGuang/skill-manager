"""Database-coordinated discovery and inventory task orchestration."""

import asyncio
import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent_manager.core.dify_console_client import DifyConsoleClient, DifyConsoleClientConfig, DifyConsoleError

from .. import models
from ..api_errors import ApiError
from ..asset_lifecycle_schemas import SourceConfig
from ..security_scan_controls import hash_value, json_dumps, new_resource_id, resolve_target_endpoint, unprotect_secret
from ..security_scan_schemas import SecurityTaskCreate
from ..sqlite_db import SessionLocal
from . import agent_risk

logger = logging.getLogger(__name__)
TERMINAL = {"succeeded", "partial", "failed", "cancelled"}


def next_due(config: SourceConfig, after: datetime, *, anchor: datetime | None = None) -> datetime:
    after = after.replace(tzinfo=timezone.utc) if after.tzinfo is None else after.astimezone(timezone.utc)
    if config.schedule_kind == "interval":
        step = timedelta(minutes=config.interval_minutes)
        base = anchor or after
        base = base.replace(tzinfo=timezone.utc) if base.tzinfo is None else base.astimezone(timezone.utc)
        if base > after:
            return base.replace(tzinfo=None)
        return (base + max(1, (after - base) // step + 1) * step).replace(tzinfo=None)
    expression = config.cron
    if config.schedule_kind == "daily":
        hour, minute = config.daily_time.split(":")
        expression = f"{int(minute)} {int(hour)} * * *"
    return (
        croniter(expression, after.astimezone(ZoneInfo(config.timezone)))
        .get_next(datetime)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def connection_hash(target: models.SecurityTarget) -> str:
    config = json.loads(target.config_json)
    return hash_value(
        json_dumps(
            {
                "console_base_url": config.get("console_base_url"),
                "workspace_id": config.get("workspace_id"),
                "endpoint_url": target.endpoint_url,
                "environment": target.environment,
                "owner_user_id": target.owner_user_id,
                "owner_group_id": target.owner_group_id,
                "allowed_cidrs": json.loads(target.allowed_cidrs_json),
            }
        )
    )


def source_context(db: Session, source: models.AssetSource):
    from ..routers import security_scans as scans

    target = scans._target_or_404(db, source.template_target_id)
    user = db.query(models.User).filter_by(username=source.created_by, is_active=True).first()
    if not user or user.role not in scans.SECURITY_ADMIN_ROLES:
        raise ApiError(
            403,
            "asset_sync.owner_unavailable",
            "同步授权账号已失效",
            "The synchronization authorizing account is unavailable",
        )
    if target.connector_type != "dify" or target.status != "active":
        raise ApiError(
            409, "asset_sync.target_unavailable", "Dify 来源目标未启用", "The Dify source target is unavailable"
        )
    if source.connection_hash != connection_hash(target):
        raise ApiError(
            409,
            "asset_sync.connection_changed",
            "来源连接或归属已变化，请重新保存资产来源",
            "The source connection or ownership changed; save the asset source again",
        )
    return target, user


def inherited_credential(db: Session, target_id: str, purpose: str):
    if purpose not in {"dify_console_api", "dify_knowledge_api"}:
        return None
    agent = db.query(models.SecurityAgentAsset).filter_by(target_id=target_id).first()
    source = db.get(models.AssetSource, agent.source_id) if agent and agent.source_id else None
    if not source or source.template_target_id == target_id:
        return None
    try:
        template, _ = source_context(db, source)
    except ApiError:
        return None
    target = db.query(models.SecurityTarget).filter_by(target_id=target_id).first()
    original, current = json.loads(template.config_json), json.loads(target.config_json)
    if any(original.get(key) != current.get(key) for key in ("console_base_url", "workspace_id")):
        return None
    if (target.owner_user_id, target.owner_group_id) != (template.owner_user_id, template.owner_group_id):
        return None
    return (
        db.query(models.SecurityTargetCredential)
        .filter_by(
            target_id=template.target_id,
            purpose=purpose,
            status="active",
        )
        .order_by(models.SecurityTargetCredential.version.desc())
        .first()
    )


def discovery_client(db: Session, source: models.AssetSource) -> DifyConsoleClient:
    from ..routers import security_scans as scans

    target, _ = source_context(db, source)
    config = json.loads(target.config_json)
    credential = scans._active_credential(db, target.target_id, "dify_console_api")
    if not credential:
        raise ApiError(
            409,
            "dify_inventory.console_credential_required",
            "缺少 Console API 凭据",
            "Console API credentials are required",
        )
    policy = scans._policy_or_404(db, source.policy_id)
    if not policy.enabled or policy.environment != target.environment:
        raise ApiError(
            409,
            "asset_sync.policy_unavailable",
            "同步策略未启用或环境不匹配",
            "The synchronization policy is unavailable or has a different environment",
        )
    url = config.get("console_base_url") or target.endpoint_url
    insecure = bool(config.get("allow_insecure_transport"))
    ips = resolve_target_endpoint(
        url, allowed_cidrs=json.loads(target.allowed_cidrs_json), allow_insecure_transport=insecure
    )
    resolve_target_endpoint(
        url, allowed_cidrs=json.loads(policy.outbound_allowlist_json), allow_insecure_transport=insecure
    )
    return DifyConsoleClient(
        DifyConsoleClientConfig(
            base_url=url,
            workspace_id=config["workspace_id"],
            app_id=config["app_id"],
            admin_api_key=unprotect_secret(credential.secret_encrypted),
            allowed_cidrs=tuple(json.loads(target.allowed_cidrs_json)),
            expected_ips=tuple(ips),
            allow_insecure_transport=insecure,
            max_retries=1,
            read_timeout_seconds=15,
        )
    )


def start_run(
    db: Session, source: models.AssetSource, request_key: str, *, now: datetime | None = None
) -> models.AssetSyncRun:
    from agent_manager.core.licensing import require_license
    require_license("security_scanning")
    now = now or datetime.utcnow()
    existing = db.query(models.AssetSyncRun).filter_by(source_id=source.source_id, request_key=request_key).first()
    if existing:
        return existing
    run_id = new_resource_id("asr")
    claimed = (
        db.query(models.AssetSource)
        .filter_by(source_id=source.source_id, active_run_id=None, version=source.version)
        .update(
            {"active_run_id": run_id},
            synchronize_session=False,
        )
    )
    if claimed != 1:
        raise ApiError(
            409,
            "asset_sync.source_busy",
            "该来源已有同步批次运行中",
            "A synchronization run is already active for this source",
        )
    frozen = json.loads(source.config_json)
    frozen["policy_id"] = source.policy_id
    row = models.AssetSyncRun(
        run_id=run_id,
        source_id=source.source_id,
        request_key=request_key,
        source_version=source.version,
        config_json=json_dumps(frozen),
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


def dispatch_due(db: Session, now: datetime) -> int:
    from agent_manager.core.licensing import scan_allowed
    if not scan_allowed():
        return 0
    count = 0
    if db.bind.dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    rows = (
        db.query(models.AssetSource)
        .filter(models.AssetSource.enabled.is_(True), models.AssetSource.next_run_at <= now)
        .all()
    )
    for source in rows:
        due = source.next_run_at
        if source.active_run_id:
            continue
        try:
            with db.begin_nested():
                start_run(db, source, f"schedule:{source.version}:{due.isoformat()}", now=now)
                db.query(models.AssetSource).filter_by(source_id=source.source_id, version=source.version).update(
                    {"next_run_at": next_due(SourceConfig(**json.loads(source.config_json)), now, anchor=due)},
                    synchronize_session=False,
                )
                count += 1
        except (ApiError, IntegrityError):
            continue
    db.commit()
    return count


def _lease(db: Session, run_id: str, token: str) -> models.AssetSyncRun:
    changed = (
        db.query(models.AssetSyncRun)
        .filter(
            models.AssetSyncRun.run_id == run_id,
            models.AssetSyncRun.lease_token == token,
            models.AssetSyncRun.status.in_(["pending", "running"]),
            models.AssetSyncRun.lease_expires_at > datetime.utcnow(),
        )
        .update({"lease_expires_at": datetime.utcnow() + timedelta(minutes=5)}, synchronize_session=False)
    )
    if changed != 1:
        raise ApiError(409, "asset_sync.lease_lost", "同步任务租约已失效", "The synchronization lease was lost")
    db.expire_all()
    return db.get(models.AssetSyncRun, run_id)


def _ensure_target(db: Session, source: models.AssetSource, app: dict) -> models.SecurityAgentAsset:
    from agent_manager.core.licensing import require_license
    require_license("security_scanning")
    template, user = source_context(db, source)
    agent = db.query(models.SecurityAgentAsset).filter_by(source_id=source.source_id, external_id=app["id"]).first()
    if agent:
        agent.observation_status = "observed"
        agent.last_observed_at = datetime.utcnow()
        return agent
    config = deepcopy(json.loads(template.config_json))
    if config.get("app_id") == app["id"]:
        agent = agent_risk.managed_agent(db, template.target_id)
        agent.source_id, agent.external_id = source.source_id, app["id"]
    else:
        config["app_id"] = app["id"]
        for key in ("workflow_id", "declared_intent", "mcp_bindings", "knowledge_bindings"):
            config.pop(key, None)
        target = models.SecurityTarget(
            target_id=new_resource_id("ast"),
            name=app["name"],
            asset_type="agent",
            connector_type="dify",
            target_type="dify",
            environment=template.environment,
            allowed_capabilities_json=template.allowed_capabilities_json,
            endpoint_url=template.endpoint_url,
            status="active",
            owner_user_id=template.owner_user_id,
            owner_group_id=template.owner_group_id,
            allowed_cidrs_json=template.allowed_cidrs_json,
            resolved_ips_json=template.resolved_ips_json,
            config_json=json_dumps(config),
            created_by=user.username,
        )
        db.add(target)
        db.flush()
        agent = agent_risk.managed_agent(db, target.target_id)
        agent.source_id, agent.external_id = source.source_id, app["id"]
    agent.last_observed_at = datetime.utcnow()
    return agent


def _finish(db: Session, run: models.AssetSyncRun, status: str) -> None:
    run.status, run.completed_at = status, datetime.utcnow()
    run.lease_token, run.lease_expires_at = None, None
    updates = {"active_run_id": None}
    if status == "succeeded":
        updates["last_success_at"] = run.completed_at
    db.query(models.AssetSource).filter_by(source_id=run.source_id, active_run_id=run.run_id).update(
        updates, synchronize_session=False
    )


def process_run(run_id: str, factory=SessionLocal) -> None:
    from agent_manager.core.licensing import scan_allowed
    if not scan_allowed():
        return
    from ..routers import security_scans as scans

    token = new_resource_id("lease")
    with factory() as db:
        now = datetime.utcnow()
        claimed = (
            db.query(models.AssetSyncRun)
            .filter(
                models.AssetSyncRun.run_id == run_id,
                models.AssetSyncRun.status.in_(["pending", "running"]),
                or_(models.AssetSyncRun.lease_expires_at.is_(None), models.AssetSyncRun.lease_expires_at <= now),
            )
            .update(
                {
                    "lease_token": token,
                    "lease_expires_at": now + timedelta(minutes=5),
                    "status": "running",
                    "updated_at": now,
                    "attempt": models.AssetSyncRun.attempt + 1,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if not claimed:
            return
    try:
        with factory() as db:
            run = db.get(models.AssetSyncRun, run_id)
            source = db.get(models.AssetSource, run.source_id)
            config = json.loads(run.config_json)
            if run.discovered_json is None and not run.cancel_requested:
                client = discovery_client(db, source)
                # Network I/O occurs outside a database write transaction.
                db.rollback()
                apps = (
                    client.list_apps()
                    if config["scope"] == "workspace"
                    else [{"id": app_id, "name": app_id} for app_id in config["app_ids"]]
                )
                run = _lease(db, run_id, token)
                if not run.cancel_requested:
                    run.discovered_json = json_dumps(apps)
                    run.enumeration_complete = True
                db.commit()
        with factory() as db:
            run = _lease(db, run_id, token)
            source = db.get(models.AssetSource, run.source_id)
            _, user = source_context(db, source)
            apps = json.loads(run.discovered_json or "[]")
            db.commit()
            for app in apps:
                run = _lease(db, run_id, token)
                if run.cancel_requested:
                    db.commit()
                    break
                item = db.query(models.AssetSyncRunItem).filter_by(run_id=run_id, external_id=app["id"]).first()
                if item and (item.task_id or item.status == "failed"):
                    db.commit()
                    continue
                agent = _ensure_target(db, source, app)
                if item is None:
                    item = models.AssetSyncRunItem(
                        item_id=new_resource_id("asi"),
                        run_id=run_id,
                        external_id=app["id"],
                        target_id=agent.target_id,
                        previous_fingerprint=agent.config_fingerprint,
                    )
                    db.add(item)
                item_id = item.item_id
                db.commit()
                try:
                    result = asyncio.run(
                        scans.create_task(
                            SecurityTaskCreate(
                                target_id=agent.target_id,
                                policy_id=config["policy_id"],
                                scan_kind="dify_asset_inventory",
                                language=config["language"],
                                idempotency_key=f"sync:{item_id}",
                            ),
                            db,
                            user,
                        )
                    )
                    run = _lease(db, run_id, token)
                    db.get(models.AssetSyncRunItem, item_id).task_id = result.task_id
                except ApiError as exc:
                    db.rollback()
                    run = _lease(db, run_id, token)
                    item = db.get(models.AssetSyncRunItem, item_id)
                    item.status, item.error_code = "failed", exc.code
                db.commit()
            run = _lease(db, run_id, token)
            items = db.query(models.AssetSyncRunItem).filter_by(run_id=run_id).all()
            if run.cancel_requested:
                for item in items:
                    if item.task_id:
                        task = db.query(models.SecurityScanTask).filter_by(task_id=item.task_id).first()
                        if task and task.status in {"pending", "running"}:
                            task.cancel_requested = True
                            if task.status == "pending":
                                task.status, task.completed_at = "cancelled", datetime.utcnow()
                    if item.status == "pending":
                        item.status = "cancelled"
                _finish(db, run, "cancelled")
            else:
                for item in items:
                    if item.task_id:
                        task = db.query(models.SecurityScanTask).filter_by(task_id=item.task_id).first()
                        if task.status not in {"pending", "running"}:
                            item.status = "succeeded" if task.status == "succeeded" else "failed"
                            item.error_code = task.error_code
                            agent = db.query(models.SecurityAgentAsset).filter_by(target_id=item.target_id).first()
                            item.change_kind = (
                                "added"
                                if not item.previous_fingerprint
                                else "unchanged"
                                if item.previous_fingerprint == agent.config_fingerprint
                                else "changed"
                            )
                if all(x.status != "pending" for x in items) and len(items) == len(apps):
                    failed = sum(x.status == "failed" for x in items)
                    _finish(
                        db, run, "partial" if failed and failed < len(items) else "failed" if failed else "succeeded"
                    )
                    # Absence only means not observed: a Console credential may have lost visibility.
                    if run.enumeration_complete and source.version == run.source_version:
                        seen = {x["id"] for x in apps}
                        for agent in db.query(models.SecurityAgentAsset).filter_by(source_id=source.source_id).all():
                            if agent.external_id not in seen:
                                agent.observation_status = (
                                    "not_observed" if config["scope"] == "workspace" else "excluded"
                                )
                                agent_risk.enqueue(db, agent.target_id, kind="inventory_updated")
                else:
                    run.lease_token, run.lease_expires_at = None, None
            db.commit()
    except Exception as exc:
        if isinstance(exc, ApiError) and exc.code == "asset_sync.lease_lost":
            return
        with factory() as db:
            run = db.get(models.AssetSyncRun, run_id)
            if run and run.lease_token == token:
                run.error_code = (
                    exc.code if isinstance(exc, (ApiError, DifyConsoleError)) else "asset_sync.execution_failed"
                )
                _finish(db, run, "failed")
                db.commit()
        logger.warning("asset synchronization failed: %s", type(exc).__name__)


def process_events(factory=SessionLocal) -> None:
    from ..routers import security_scans as scans

    with factory() as db:
        ids = [
            x.event_id
            for x in db.query(models.AssetLifecycleEvent)
            .filter(
                models.AssetLifecycleEvent.processed_at.is_(None),
                or_(
                    models.AssetLifecycleEvent.next_attempt_at.is_(None),
                    models.AssetLifecycleEvent.next_attempt_at <= datetime.utcnow(),
                ),
            )
            .order_by(models.AssetLifecycleEvent.created_at)
            .limit(100)
        ]
    for event_id in ids:
        with factory() as db:
            # Claim and calculation share one transaction; a crash leaves the event pending.
            claimed = (
                db.query(models.AssetLifecycleEvent)
                .filter_by(event_id=event_id, processed_at=None)
                .update({"processed_at": datetime.utcnow()}, synchronize_session=False)
            )
            if not claimed:
                db.rollback()
                continue
            event = db.get(models.AssetLifecycleEvent, event_id)
            target = db.query(models.SecurityTarget).filter_by(target_id=event.target_id).first()
            if not target or target.asset_type != "agent":
                for link in db.query(models.AgentAssetLink).filter_by(target_id=event.target_id):
                    linked_agent = db.get(models.SecurityAgentAsset, link.agent_id)
                    if linked_agent:
                        agent_risk.calculate(db, linked_agent)
                db.commit()
                continue
            agent = agent_risk.managed_agent(db, target.target_id)
            agent_risk.calculate(db, agent)
            source = db.get(models.AssetSource, agent.source_id) if agent.source_id else None
            config = json.loads(source.config_json) if source else {}
            if (
                event.kind == "inventory_updated"
                and config.get("auto_scan_policy_id")
                and config.get("scan_new_apps" if agent.revision == 1 else "scan_changed_apps", True)
                and agent.observation_status == "observed"
            ):
                # The scan API applies its normal environment, credential and approval checks.
                try:
                    _, user = source_context(db, source)
                    scan_key = f"asset-change:{agent.agent_id}:{agent.revision}"
                    exists = (
                        db.query(models.SecurityScanTask)
                        .filter_by(created_by=user.username, idempotency_key=scan_key)
                        .first()
                    )
                    if not exists:
                        asyncio.run(
                            scans.create_task(
                                SecurityTaskCreate(
                                    target_id=target.target_id,
                                    policy_id=config["auto_scan_policy_id"],
                                    scan_kind="agent_risk_scan",
                                    skills=config["skills"],
                                    evaluation_model=config.get("evaluation_model"),
                                    language=config["language"],
                                    conversation_mode="multi_turn",
                                    idempotency_key=scan_key,
                                ),
                                db,
                                user,
                            )
                        )
                except ApiError as exc:
                    db.rollback()
                    event = db.get(models.AssetLifecycleEvent, event_id)
                    event.error_code = exc.code
                    event.next_attempt_at = datetime.utcnow() + timedelta(minutes=5)
                    db.commit()
                    continue
            event.error_code = None
            event.next_attempt_at = None
            db.commit()


def tick(factory=SessionLocal) -> None:
    from ..config import settings

    if not settings.AGENT_SECURITY_SCANNING_ENABLED:
        return
    with factory() as db:
        from ..routers.security_scans import recover_stale_tasks

        recover_stale_tasks(db)
        dispatch_due(db, datetime.utcnow())
        run_ids = [
            x.run_id
            for x in db.query(models.AssetSyncRun)
            .filter(models.AssetSyncRun.status.in_(["pending", "running"]))
            .order_by(models.AssetSyncRun.updated_at)
            .limit(20)
        ]
    for run_id in run_ids:
        process_run(run_id, factory)
    process_events(factory)


async def lifecycle_loop() -> None:
    while True:
        try:
            from .scan_schedules import tick as scan_tick

            await asyncio.to_thread(scan_tick)
            await asyncio.to_thread(tick)
        except Exception as exc:
            logger.warning("asset lifecycle tick failed: %s", type(exc).__name__)
        await asyncio.sleep(10)
