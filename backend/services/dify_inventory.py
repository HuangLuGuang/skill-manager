from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..api_errors import ApiError
from ..security_scan_controls import hash_value, json_dumps, new_resource_id, protect_secret


_ASSET_KEYS = ("nodes", "prompts", "mcp", "tools", "knowledge_bases")
_VERIFICATION_STATUSES = {"verified", "declared", "inferred", "unverified", "unavailable", "partially_verified"}


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def validate_inventory_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or report.get("schema_version") != "dify-asset-inventory@1":
        raise ApiError(
            422, "dify_inventory.response_invalid",
            "Dify 资产清单产物格式无效", "The Dify asset inventory artifact is invalid",
        )
    if report.get("engine_name") != "agent-manager-dify-inventory":
        raise ApiError(422, "dify_inventory.response_invalid", "Dify 资产清单引擎无效", "Invalid Dify inventory engine")
    if not isinstance(report.get("agent_profile"), dict) or not isinstance(report.get("coverage"), dict):
        raise ApiError(422, "dify_inventory.response_invalid", "Dify 资产清单缺少档案或覆盖信息", "Dify inventory profile or coverage is missing")
    return report


def inventory_artifact_projection(report: dict[str, Any]) -> dict[str, Any]:
    """Return the durable artifact view without separately protected Prompt text."""
    projected = deepcopy(report)
    for section in _ASSET_KEYS:
        for item in projected.get(section, []):
            if isinstance(item, dict):
                item.pop("sensitive_content", None)
    return projected


def persist_inventory_snapshot(db: Session, task: models.SecurityScanTask, report: dict[str, Any]) -> models.SecurityAssetInventorySnapshot:
    report = validate_inventory_report(report)
    profile = report["agent_profile"]
    app_id = str((profile.get("app_id") or {}).get("value") or "").strip()
    if not app_id:
        raise ApiError(422, "dify_inventory.response_invalid", "Dify 资产清单缺少 App ID", "Dify inventory App ID is missing")
    existing = db.query(models.SecurityAssetInventorySnapshot).filter(
        models.SecurityAssetInventorySnapshot.task_id == task.task_id
    ).first()
    if existing:
        raise ApiError(409, "dify_inventory.snapshot_exists", "任务资产快照已存在", "The task inventory snapshot already exists")
    collected_at = _parse_timestamp((profile.get("last_collected_at") or {}).get("value"))
    snapshot = models.SecurityAssetInventorySnapshot(
        snapshot_id=new_resource_id("ais"), task_id=task.task_id, target_id=task.target_id, app_id=app_id,
        schema_version="dify-asset-inventory@1", engine_name="agent-manager-dify-inventory",
        agent_profile_json=json_dumps(profile), summary_json=json_dumps(report.get("summary", {})),
        coverage_json=json_dumps(report.get("coverage", {})), limitations_json=json_dumps(report.get("limitations", [])),
        collected_at=collected_at,
    )
    db.add(snapshot)
    db.flush()
    for section in _ASSET_KEYS:
        values = report.get(section, [])
        if not isinstance(values, list):
            raise ApiError(422, "dify_inventory.response_invalid", "Dify 资产列表格式无效", "Invalid Dify inventory item list")
        for raw in values:
            if not isinstance(raw, dict):
                raise ApiError(422, "dify_inventory.response_invalid", "Dify 资产项格式无效", "Invalid Dify inventory item")
            asset_id = str(raw.get("asset_id") or "")
            asset_type = str(raw.get("asset_type") or "")
            status = str(raw.get("verification_status") or "unverified")
            if not asset_id or len(asset_id) > 512 or not asset_type or status not in _VERIFICATION_STATUSES:
                raise ApiError(422, "dify_inventory.response_invalid", "Dify 资产项标识或状态无效", "Invalid Dify inventory asset identity or status")
            details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
            sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
            sensitive = raw.get("sensitive_content")
            fingerprint = hash_value(json_dumps({
                "asset_id": asset_id, "asset_type": asset_type, "configured": bool(raw.get("configured")),
                "discovered": bool(raw.get("discovered")), "executed": bool(raw.get("executed")),
                "verification_status": status, "details": details, "sources": sources,
            }))
            item = models.SecurityAssetInventoryItem(
                item_id=new_resource_id("aii"), snapshot_id=snapshot.snapshot_id, asset_id=asset_id,
                asset_type=asset_type, name=str(raw.get("name") or asset_id)[:512],
                configured=bool(raw.get("configured")), discovered=bool(raw.get("discovered")), executed=bool(raw.get("executed")),
                verification_status=status, details_json=json_dumps(details),
                sensitive_content_encrypted=protect_secret(str(sensitive)) if isinstance(sensitive, str) else None,
                fingerprint=fingerprint,
            )
            db.add(item)
            db.flush()
            for evidence in sources:
                if not isinstance(evidence, dict) or not evidence.get("source_type"):
                    continue
                metadata = {key: value for key, value in evidence.items() if key not in {"source_type", "source_identifier"}}
                db.add(models.SecurityAssetInventoryEvidence(
                    evidence_id=new_resource_id("aie"), item_id=item.item_id,
                    source_type=str(evidence["source_type"])[:64],
                    source_identifier=str(evidence.get("source_identifier"))[:2048] if evidence.get("source_identifier") else None,
                    metadata_json=json_dumps(metadata),
                ))
    return snapshot


def snapshot_payload(db: Session, snapshot: models.SecurityAssetInventorySnapshot, *, mask_workspace: bool = True) -> dict[str, Any]:
    profile = json.loads(snapshot.agent_profile_json or "{}")
    workspace = profile.get("workspace_id") if isinstance(profile.get("workspace_id"), dict) else None
    if mask_workspace and workspace and workspace.get("value"):
        value = str(workspace["value"])
        workspace["value"] = f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "********"
    items = db.query(models.SecurityAssetInventoryItem).filter(
        models.SecurityAssetInventoryItem.snapshot_id == snapshot.snapshot_id
    ).order_by(models.SecurityAssetInventoryItem.id).all()
    evidence_rows = db.query(models.SecurityAssetInventoryEvidence).filter(
        models.SecurityAssetInventoryEvidence.item_id.in_([item.item_id for item in items])
    ).order_by(models.SecurityAssetInventoryEvidence.id).all() if items else []
    evidence_by_item: dict[str, list[dict[str, Any]]] = {}
    for row in evidence_rows:
        evidence_by_item.setdefault(row.item_id, []).append({
            "source_type": row.source_type, "source_identifier": row.source_identifier,
            "metadata": json.loads(row.metadata_json or "{}"),
        })
    return {
        "snapshot_id": snapshot.snapshot_id, "task_id": snapshot.task_id, "target_id": snapshot.target_id,
        "app_id": snapshot.app_id, "schema_version": snapshot.schema_version, "engine_name": snapshot.engine_name,
        "agent_profile": profile, "summary": json.loads(snapshot.summary_json or "{}"),
        "coverage": json.loads(snapshot.coverage_json or "{}"), "limitations": json.loads(snapshot.limitations_json or "[]"),
        "collected_at": snapshot.collected_at,
        "items": [{
            "item_id": item.item_id, "asset_id": item.asset_id, "asset_type": item.asset_type, "name": item.name,
            "configured": item.configured, "discovered": item.discovered, "executed": item.executed,
            "verification_status": item.verification_status, "details": json.loads(item.details_json or "{}"),
            "sensitive_content_available": bool(item.sensitive_content_encrypted),
            "fingerprint": item.fingerprint, "sources": evidence_by_item.get(item.item_id, []),
        } for item in items],
    }
