from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..agentic_risk_taxonomy import map_risk_codes
from ..api_errors import ApiError
from ..config import settings
from ..runtime_trace_schemas import RuntimeTraceBatchCreate, RuntimeTraceEventInput
from ..security_audit import append_security_audit
from ..security_report_contract import build_report_contract, legacy_unversioned_report_contract
from ..security_scan_controls import (
    AGENT_SCAN_SKILLS,
    ASSET_SCAN_KINDS,
    MCP_GATEWAY_TARGET_TYPE,
    TASK_ACTIVE_STATUSES,
    TASK_TERMINAL_STATUSES,
    hash_value,
    json_dumps,
    json_loads,
    legacy_target_classification,
    legacy_target_type_for,
    mask_secret,
    new_resource_id,
    normalize_cidrs,
    protect_secret,
    request_fingerprint,
    resolve_target_endpoint,
    sanitize_mcp_metadata_text,
    sanitize_mcp_metadata_value,
    sanitize_untrusted_text,
    sanitize_untrusted_value,
    seal_secret_for_worker,
    unprotect_secret,
    validate_agent_target_config,
    validate_dify_inventory_target_config,
    validate_asset_connector,
    validate_infrastructure_target_config,
    validate_llm_target_config,
    validate_target_type_scheme,
    validate_worker_public_key,
    verify_dns_pin,
)
from ..security_scan_schemas import (
    SecurityCredentialCreate,
    SecurityCredentialResponse,
    SecurityCredentialStatusUpdate,
    SecurityCredentialUpdate,
    SecurityFindingDisposition,
    SecurityFindingResponse,
    SecurityIntentInferenceRequest,
    SecurityIntentInferenceResponse,
    SecurityPolicyCreate,
    SecurityPolicyResponse,
    SecurityPolicyUpdate,
    SecurityScanApprovalCreate,
    SecurityScanApprovalResponse,
    SecurityTargetCreate,
    SecurityTargetResponse,
    SecurityTargetUpdate,
    SecurityTaskComparisonResponse,
    SecurityTaskCreate,
    SecurityTaskKillSwitchRequest,
    SecurityTaskPlanRequest,
    SecurityTaskPreviewRequest,
    SecurityTaskPreviewResponse,
    SecurityTaskResponse,
    SecurityTaskUsage,
    SecurityWorkerClaimRequest,
    SecurityWorkerClaimResponse,
    SecurityWorkerCompleteRequest,
    SecurityWorkerCreate,
    SecurityWorkerHeartbeatRequest,
    SecurityWorkerHeartbeatResponse,
    SecurityWorkerKeyRegister,
    SecurityWorkerKeyResponse,
    SecurityWorkerResponse,
)
from ..services.runtime_traces import create_trace as create_runtime_trace_session
from ..services.runtime_traces import ingest_batch as ingest_runtime_trace_batch
from ..services.runtime_traces import ingest_transaction as runtime_trace_transaction
from ..services.dify_inventory import (
    inventory_artifact_projection,
    persist_inventory_snapshot,
    snapshot_payload,
    validate_inventory_report,
)
from ..services.dify_intent_inference import run_intent_inference
from ..sqlite_db import get_db
from agent_manager.core.mcp_parameter_risk import classify_mcp_parameter, normalize_mcp_identifier

router = APIRouter(prefix="/v1/agent-security", tags=["agent-security"])
logger = logging.getLogger(__name__)
SECURITY_READER_ROLES = {"admin", "super_admin", "security_auditor"}
SECURITY_ADMIN_ROLES = {"admin", "super_admin"}
_WORKER_RESULT_CONTRACTS = {
    "agent_risk_scan": {
        "engine_name": "tencent-ai-infra-guard-agent-scan",
        "version_prefix": "v4.6.0",
        "artifact_type": "aig-agent-scan-report",
    },
    "mcp_risk_scan": {
        "engine_name": "agent-manager-mcp-metadata-adapter",
        "version_prefix": "1+aig-contract-v4.6.0",
        "artifact_type": "mcp-metadata-scan-report",
    },
    "llm_redteam_scan": {
        "engine_name": "tencent-ai-infra-guard-model-redteam",
        "version_prefix": "v4.6.0",
        "artifact_type": "aig-llm-redteam-report",
    },
    "ai_infrastructure_vulnerability_scan": {
        "engine_name": "tencent-ai-infra-guard-infrastructure-scan",
        "version_prefix": "v4.6.0",
        "artifact_type": "aig-infrastructure-scan-report",
    },
    "dify_asset_inventory": {
        "engine_name": "agent-manager-dify-inventory",
        "version_prefix": "1",
        "artifact_type": "dify-asset-inventory",
    },
}
_MCP_RAW_INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous|above)\s+instructions?"),
    re.compile(r"(?i)(?:system|developer)\s*(?:prompt|message|override)\s*:"),
    re.compile(r"(?i)(?:send|upload|exfiltrate)\s+.*(?:secret|token|credential|password|environment)"),
    re.compile(r"(?:忽略|无视).{0,20}(?:之前|以上|系统).{0,20}(?:指令|提示)"),
    re.compile(r"(?:系统|开发者).{0,10}(?:指令|提示词).{0,5}[:：]"),
)
_MCP_RAW_SIDE_EFFECT_RULES = (
    ("delete", re.compile(r"(?i)(?:^|\s)(delete|remove|drop|destroy|purge|revoke)(?:$|\s)|删除|清空|销毁|撤销")),
    ("write", re.compile(r"(?i)(?:^|\s)(write|create|update|modify|set|execute|run|deploy)(?:$|\s)|写入|创建|修改|执行|发布")),
    ("transfer", re.compile(r"(?i)(?:^|\s)(transfer|pay|payment|withdraw|refund|trade)(?:$|\s)|转账|付款|支付|提现|退款|交易")),
    ("external_send", re.compile(r"(?i)(?:^|\s)(send|email|message|upload|export|publish)(?:$|\s)|发送|外发|上传|导出")),
)
_AIG_HEALTH_CACHE: dict[str, Any] = {"key": None, "expires_at": 0.0, "available": False}
_AIG_HEALTH_LOCK = threading.Lock()


def _aig_engine_available() -> bool:
    base_url = settings.AIG_SERVICE_URL.strip().rstrip("/")
    token = settings.AIG_SERVICE_TOKEN or ""
    if not base_url or not token:
        return False
    cache_key = hashlib.sha256(f"{base_url}\0{token}".encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _AIG_HEALTH_LOCK:
        if _AIG_HEALTH_CACHE["key"] == cache_key and now < float(_AIG_HEALTH_CACHE["expires_at"]):
            return bool(_AIG_HEALTH_CACHE["available"])
    request = urllib.request.Request(
        f"{base_url}/healthz",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    available = False
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            raw = response.read(64 * 1024 + 1)
        body = json_loads(raw.decode("utf-8"), {}) if len(raw) <= 64 * 1024 else {}
        engine = body.get("engine") if isinstance(body, dict) else None
        available = body.get("status") == "ok" and isinstance(engine, dict)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError):
        available = False
    with _AIG_HEALTH_LOCK:
        _AIG_HEALTH_CACHE.update(
            {"key": cache_key, "expires_at": time.monotonic() + 5.0, "available": available}
        )
    return available

def _audit(
    db: Session,
    *,
    event_type: str,
    actor: str,
    resource_type: str,
    resource_id: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        append_security_audit(
            event_type=event_type,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            outcome="success",
            details=details or {},
            bind=db.get_bind(),
        )
    except Exception:
        logger.exception("Failed to append agent-security audit event %s", event_type)


def _group_ids(db: Session, user_id: int) -> set[int]:
    return {
        int(row.group_id)
        for row in db.query(models.UserGroupMember).filter(models.UserGroupMember.user_id == user_id).all()
    }


def _can_access_target(db: Session, user: models.User, target: models.SecurityTarget) -> bool:
    if user.role in SECURITY_READER_ROLES:
        return True
    if target.owner_user_id == user.id:
        return True
    return bool(target.owner_group_id and target.owner_group_id in _group_ids(db, user.id))


def _require_target_access(db: Session, user: models.User, target: models.SecurityTarget) -> None:
    if not _can_access_target(db, user, target):
        raise ApiError(
            403,
            "agent_security.target_access_denied",
            "当前用户无权访问该扫描目标",
            "The current user cannot access this scan target",
            params={"target_id": target.target_id},
        )


def _target_or_404(db: Session, target_id: str) -> models.SecurityTarget:
    row = db.query(models.SecurityTarget).filter(models.SecurityTarget.target_id == target_id).first()
    if not row:
        raise ApiError(
            404,
            "agent_security.target_not_found",
            "扫描目标不存在",
            "Scan target not found",
            params={"target_id": target_id},
        )
    return row


def _policy_or_404(db: Session, policy_id: str) -> models.SecurityScanPolicy:
    row = db.query(models.SecurityScanPolicy).filter(models.SecurityScanPolicy.policy_id == policy_id).first()
    if not row:
        raise ApiError(
            404,
            "agent_security.policy_not_found",
            "扫描策略不存在",
            "Scan policy not found",
            params={"policy_id": policy_id},
        )
    return row


def _task_or_404(db: Session, task_id: str) -> models.SecurityScanTask:
    row = db.query(models.SecurityScanTask).filter(models.SecurityScanTask.task_id == task_id).first()
    if not row:
        raise ApiError(
            404,
            "agent_security.task_not_found",
            "扫描任务不存在",
            "Scan task not found",
            params={"task_id": task_id},
        )
    return row


def _require_task_access(db: Session, user: models.User, task: models.SecurityScanTask) -> None:
    if user.role in SECURITY_READER_ROLES or task.owner_user_id == user.id:
        return
    if task.owner_group_id and task.owner_group_id in _group_ids(db, user.id):
        return
    raise ApiError(
        403,
        "agent_security.task_access_denied",
        "当前用户无权访问该扫描任务",
        "The current user cannot access this scan task",
        params={"task_id": task.task_id},
    )


def _active_credential(
    db: Session, target_id: str, purpose: str | None = None
) -> models.SecurityTargetCredential | None:
    query = db.query(models.SecurityTargetCredential).filter(
        models.SecurityTargetCredential.target_id == target_id,
        models.SecurityTargetCredential.status == "active",
    )
    if purpose:
        query = query.filter(models.SecurityTargetCredential.purpose == purpose)
    else:
        query = query.filter(models.SecurityTargetCredential.purpose.in_(("agent_runtime", "dify_app_api")))
    return query.order_by(models.SecurityTargetCredential.version.desc()).first()


def _active_credentials(db: Session, target_id: str) -> list[models.SecurityTargetCredential]:
    return db.query(models.SecurityTargetCredential).filter(
        models.SecurityTargetCredential.target_id == target_id,
        models.SecurityTargetCredential.status == "active",
    ).order_by(models.SecurityTargetCredential.purpose, models.SecurityTargetCredential.version.desc()).all()


def _latest_credentials(db: Session, target_id: str) -> list[models.SecurityTargetCredential]:
    rows = db.query(models.SecurityTargetCredential).filter(
        models.SecurityTargetCredential.target_id == target_id,
    ).order_by(
        models.SecurityTargetCredential.purpose,
        models.SecurityTargetCredential.version.desc(),
    ).all()
    latest_by_purpose: dict[str, models.SecurityTargetCredential] = {}
    for row in rows:
        latest_by_purpose.setdefault(row.purpose, row)
    return list(latest_by_purpose.values())


def _target_response(db: Session, row: models.SecurityTarget) -> SecurityTargetResponse:
    credential = _active_credential(db, row.target_id)
    credentials = _latest_credentials(db, row.target_id)
    config = json_loads(row.config_json, {})
    external_engine_required = row.asset_type in {"llm", "ai_infrastructure"}
    engine_available = not external_engine_required or _aig_engine_available()
    return SecurityTargetResponse(
        target_id=row.target_id,
        name=row.name,
        target_type=row.target_type,
        asset_type=row.asset_type,
        connector_type=row.connector_type,
        environment=row.environment,
        allowed_capabilities=json_loads(row.allowed_capabilities_json, []),
        endpoint_url=row.endpoint_url,
        status=row.status,
        owner_user_id=row.owner_user_id,
        owner_group_id=row.owner_group_id,
        allowed_cidrs=json_loads(row.allowed_cidrs_json, []),
        resolved_ips=json_loads(row.resolved_ips_json, []),
        allow_insecure_transport=bool(config.pop("allow_insecure_transport", False)),
        config=config,
        credential_configured=credential is not None,
        credential_masked=credential.secret_masked if credential else None,
        credentials=[
            {"credential_id": item.credential_id, "purpose": item.purpose,
             "credential_type": item.credential_type, "secret_masked": item.secret_masked,
             "status": item.status, "version": item.version}
            for item in credentials
        ],
        engine_available=engine_available,
        engine_error_code=None if engine_available else "agent_security.aig_service_unavailable",
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _credential_response(
    row: models.SecurityTargetCredential,
    *,
    secret_once: str | None = None,
) -> SecurityCredentialResponse:
    return SecurityCredentialResponse(
        credential_id=row.credential_id,
        target_id=row.target_id,
        credential_type=row.credential_type,
        purpose=row.purpose,
        secret_masked=row.secret_masked,
        secret_once=secret_once,
        status=row.status,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        revoked_at=row.revoked_at,
    )


def _policy_payload(row: models.SecurityScanPolicy) -> dict[str, Any]:
    return {
        "policy_id": row.policy_id,
        "name": row.name,
        "environment": row.environment,
        "execution_mode": row.execution_mode,
        "allowed_capabilities": json_loads(row.allowed_capabilities_json, []),
        "production_target_ids": json_loads(row.production_target_ids_json, []),
        "maintenance_window_start": row.maintenance_window_start,
        "maintenance_window_end": row.maintenance_window_end,
        "dedicated_identity_ref": row.dedicated_identity_ref,
        "enabled": row.enabled,
        "outbound_allowlist": json_loads(row.outbound_allowlist_json, []),
        "max_rounds": row.max_rounds,
        "max_tokens": row.max_tokens,
        "max_cost_microunits": row.max_cost_microunits,
        "max_concurrent_requests": row.max_concurrent_requests,
        "max_duration_seconds": row.max_duration_seconds,
        "max_response_bytes": row.max_response_bytes,
        "max_retries": row.max_retries,
        "task_timeout_seconds": row.task_timeout_seconds,
        "lease_seconds": row.lease_seconds,
        "retry_backoff_seconds": row.retry_backoff_seconds,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _policy_snapshot(row: models.SecurityScanPolicy) -> dict[str, Any]:
    return {
        "policy_id": row.policy_id,
        "environment": row.environment,
        "execution_mode": row.execution_mode,
        "allowed_capabilities": json_loads(row.allowed_capabilities_json, []),
        "production_target_ids": json_loads(row.production_target_ids_json, []),
        "maintenance_window_start": row.maintenance_window_start.isoformat() if row.maintenance_window_start else None,
        "maintenance_window_end": row.maintenance_window_end.isoformat() if row.maintenance_window_end else None,
        "dedicated_identity_ref": row.dedicated_identity_ref,
        "outbound_allowlist": json_loads(row.outbound_allowlist_json, []),
        "max_rounds": row.max_rounds,
        "max_tokens": row.max_tokens,
        "max_cost_microunits": row.max_cost_microunits,
        "max_concurrent_requests": row.max_concurrent_requests,
        "max_duration_seconds": row.max_duration_seconds,
        "max_response_bytes": row.max_response_bytes,
        "max_retries": row.max_retries,
        "task_timeout_seconds": row.task_timeout_seconds,
        "lease_seconds": row.lease_seconds,
        "retry_backoff_seconds": row.retry_backoff_seconds,
    }


def _reject_production_active_full(environment: str, execution_mode: str, *, status_code: int = 422) -> None:
    if environment == "production" and execution_mode == "active_full":
        raise ApiError(
            status_code,
            "agent_security.production_active_full_forbidden",
            "生产环境禁止使用完整主动扫描模式",
            "Active-full scanning is forbidden in production environments",
        )


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _validate_production_active_safe_controls(
    db: Session,
    *,
    environment: str,
    execution_mode: str,
    production_target_ids: list[str],
    maintenance_window_start: datetime | None,
    maintenance_window_end: datetime | None,
    dedicated_identity_ref: str | None,
) -> tuple[datetime | None, datetime | None, str | None]:
    window_start = _utc_naive(maintenance_window_start)
    window_end = _utc_naive(maintenance_window_end)
    identity_ref = (dedicated_identity_ref or "").strip() or None
    if environment != "production" or execution_mode != "active_safe":
        return window_start, window_end, identity_ref
    missing = []
    if not production_target_ids:
        missing.append("production_target_ids")
    if window_start is None:
        missing.append("maintenance_window_start")
    if window_end is None:
        missing.append("maintenance_window_end")
    if identity_ref is None:
        missing.append("dedicated_identity_ref")
    if missing:
        raise ApiError(
            422,
            "agent_security.production_active_safe_controls_required",
            "生产主动安全扫描必须配置维护窗口、目标白名单和专用身份",
            "Production active-safe scanning requires a maintenance window, target allowlist, and dedicated identity",
            params={"missing_fields": missing},
        )
    if window_end <= window_start or window_end - window_start > timedelta(hours=24):
        raise ApiError(
            422,
            "agent_security.production_maintenance_window_invalid",
            "生产扫描维护窗口必须大于零且不超过 24 小时",
            "The production scan maintenance window must be greater than zero and no longer than 24 hours",
        )
    rows = db.query(models.SecurityTarget).filter(models.SecurityTarget.target_id.in_(production_target_ids)).all()
    valid_ids = {row.target_id for row in rows if row.environment == "production"}
    invalid_ids = sorted(set(production_target_ids) - valid_ids)
    if invalid_ids:
        raise ApiError(
            422,
            "agent_security.production_target_allowlist_invalid",
            "生产扫描目标白名单包含不存在或非生产环境的目标",
            "The production target allowlist contains missing or non-production targets",
            params={"invalid_target_ids": invalid_ids},
        )
    return window_start, window_end, identity_ref


def _approval_response(row: models.SecurityScanApproval) -> SecurityScanApprovalResponse:
    return SecurityScanApprovalResponse(
        approval_id=row.approval_id,
        target_id=row.target_id,
        policy_id=row.policy_id,
        credential_id=row.credential_id,
        credential_version=row.credential_version,
        dedicated_identity_ref=row.dedicated_identity_ref,
        maintenance_window_start=row.maintenance_window_start,
        maintenance_window_end=row.maintenance_window_end,
        status=row.status,
        approved_by=row.approved_by,
        created_at=row.created_at,
        used_by=row.used_by,
        used_task_id=row.used_task_id,
        used_at=row.used_at,
    )


def _report_contract_snapshot(row: models.SecurityScanTask) -> dict[str, Any]:
    snapshot = json_loads(row.report_contract_json, {})
    if (
        isinstance(snapshot, dict)
        and snapshot.get("snapshot_status") == "frozen"
        and snapshot.get("report_template_version") == row.report_template_version
        and snapshot.get("decision_criteria_version") == row.decision_criteria_version
    ):
        return snapshot
    return legacy_unversioned_report_contract()


def _task_response(row: models.SecurityScanTask) -> SecurityTaskResponse:
    protected_options = unprotect_secret(row.scan_options_encrypted)
    raw_options = json_loads(protected_options, {}) if protected_options else {}
    safe_options = {
        "language": raw_options.get("language", "zh"),
        "skills": raw_options.get("skills", []),
        "conversation_mode": raw_options.get("conversation_mode", "single_turn"),
        "reset_session": bool(raw_options.get("reset_session", True)),
        "prompt_configured": bool(raw_options.get("prompt")),
        "metadata_only": bool(raw_options.get("metadata_only", False)),
        "side_effect_tool_calls": raw_options.get("side_effect_tool_calls"),
        "upstream_dynamic_mode": raw_options.get("upstream_dynamic_mode"),
        "datasets": raw_options.get("datasets", []),
        "num_prompts": raw_options.get("num_prompts"),
        "random_seed": raw_options.get("random_seed"),
        "techniques": raw_options.get("techniques", []),
        "evaluation_model": raw_options.get("evaluation_model"),
        "http_authorized": bool(raw_options.get("http_authorized", False)),
        "private_network_authorized": bool(raw_options.get("private_network_authorized", False)),
        "scan_timeout_seconds": raw_options.get("scan_timeout_seconds"),
        "scan_concurrency": raw_options.get("scan_concurrency"),
        "inventory_source": raw_options.get("inventory_source"),
        "manual_dsl_configured": bool(raw_options.get("manual_dsl")),
        "include_prompt_text": bool(raw_options.get("include_prompt_text", False)),
        "infer_agent_intent": bool(raw_options.get("infer_agent_intent", False)),
        "intent_inference_model": raw_options.get("intent_inference_model"),
        "knowledge_content_authorized": bool(raw_options.get("knowledge_content_authorized", False)),
        "max_knowledge_documents": raw_options.get("max_knowledge_documents"),
        "max_knowledge_segments": raw_options.get("max_knowledge_segments"),
        "max_knowledge_bytes": raw_options.get("max_knowledge_bytes"),
    }
    return SecurityTaskResponse(
        task_id=row.task_id,
        target_id=row.target_id,
        policy_id=row.policy_id,
        approval_id=row.approval_id,
        scan_kind=row.scan_kind,
        status=row.status,
        idempotency_key=row.idempotency_key,
        created_by=row.created_by,
        worker_id=row.worker_id,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        cancel_requested=row.cancel_requested,
        kill_switch_activated=row.kill_switch_activated,
        kill_switch_activated_at=row.kill_switch_activated_at,
        kill_switch_activated_by=row.kill_switch_activated_by,
        kill_switch_reason=row.kill_switch_reason,
        stop_reason=row.stop_reason,
        error_code=row.error_code,
        error_message=row.error_message,
        usage={
            "rounds": row.rounds_used,
            "tokens": row.tokens_used,
            "cost_microunits": row.cost_microunits_used,
            "concurrent_requests": row.max_concurrency_seen,
            "response_bytes": row.response_bytes_used,
        },
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        timeout_at=row.timeout_at,
        heartbeat_at=row.heartbeat_at,
        lease_expires_at=row.lease_expires_at,
        scan_options=safe_options,
        continued_from_task_id=row.continued_from_task_id,
        session_continuation_available=bool(row.session_state_encrypted),
        engine={
            "name": row.engine_name or "",
            "version": row.engine_version or "",
        },
        report_template_version=row.report_template_version,
        decision_criteria_version=row.decision_criteria_version,
        report_contract_status=_report_contract_snapshot(row)["snapshot_status"],
    )


def _worker_response(row: models.SecurityScanWorker, *, token_once: str | None = None) -> SecurityWorkerResponse:
    return SecurityWorkerResponse(
        worker_id=row.worker_id,
        name=row.name,
        token_prefix=row.token_prefix,
        token_once=token_once,
        status=row.status,
        capabilities=json_loads(row.capabilities_json, []),
        max_concurrency=row.max_concurrency,
        last_heartbeat_at=row.last_heartbeat_at,
        created_at=row.created_at,
        public_key_fingerprint=row.public_key_fingerprint,
        public_key_registered_at=row.public_key_registered_at,
    )


def _validate_owner(db: Session, user_id: int | None, group_id: int | None) -> None:
    if user_id is not None and not db.query(models.User).filter(models.User.id == user_id).first():
        raise ApiError(422, "agent_security.owner_user_not_found", "目标所属用户不存在", "Target owner user not found")
    if group_id is not None and not db.query(models.UserGroup).filter(models.UserGroup.id == group_id).first():
        raise ApiError(
            422, "agent_security.owner_group_not_found", "目标所属用户组不存在", "Target owner group not found"
        )


def _validate_mcp_gateway_target(
    db: Session,
    *,
    endpoint_url: str,
    config: dict[str, Any],
    allowed_cidrs: list[str],
    allow_insecure_transport: bool,
    environment: str,
) -> tuple[dict[str, Any], models.McpGateway]:
    if allowed_cidrs or allow_insecure_transport:
        raise ApiError(
            422,
            "agent_security.mcp_target_network_config_forbidden",
            "MCP Gateway 元数据扫描不接受网络白名单或不安全传输配置",
            "MCP Gateway metadata scans do not accept network allowlists or insecure transport",
        )
    normalized = validate_agent_target_config(MCP_GATEWAY_TARGET_TYPE, config)
    gateway = db.query(models.McpGateway).filter(models.McpGateway.id == normalized["gateway_id"]).first()
    if not gateway:
        raise ApiError(
            404,
            "agent_security.mcp_gateway_not_found",
            "MCP Gateway 不存在",
            "The MCP Gateway does not exist",
            params={"gateway_id": normalized["gateway_id"]},
        )
    expected_endpoint = f"mcp-gateway://{gateway.slug}"
    if endpoint_url != expected_endpoint:
        raise ApiError(
            422,
            "agent_security.mcp_gateway_endpoint_mismatch",
            "MCP Gateway 扫描目标地址与 gateway_id 不匹配",
            "The MCP Gateway scan target URL does not match gateway_id",
            params={"expected_endpoint_url": expected_endpoint},
        )
    if gateway.environment != environment:
        raise ApiError(
            422,
            "agent_security.mcp_gateway_environment_mismatch",
            "MCP Gateway 环境与扫描目标环境不一致",
            "The MCP Gateway environment does not match the scan target environment",
            params={"gateway_environment": gateway.environment, "target_environment": environment},
        )
    return normalized, gateway


def _validate_infrastructure_endpoints(
    *,
    endpoint_url: str,
    config: dict[str, Any],
    allowed_cidrs: list[str],
    allow_insecure_transport: bool,
) -> tuple[dict[str, Any], list[str]]:
    normalized = validate_infrastructure_target_config(config)
    endpoints = normalized.get("endpoints") or [endpoint_url]
    if endpoints[0] != endpoint_url:
        raise ApiError(
            422,
            "agent_security.infra_target_required",
            "基础设施目标主地址必须与 URL 列表第一项一致",
            "The infrastructure target URL must match the first endpoint in the list",
        )

    resolved_ips: list[str] = []
    for endpoint in endpoints:
        validate_target_type_scheme("http", endpoint)
        try:
            endpoint_ips = resolve_target_endpoint(
                endpoint,
                allowed_cidrs=allowed_cidrs,
                allow_insecure_transport=allow_insecure_transport,
            )
        except ApiError as exc:
            if exc.code == "agent_security.private_address_forbidden":
                raise ApiError(
                    exc.status_code,
                    "agent_security.infra_private_address_forbidden",
                    "基础设施私网目标未被 CIDR 白名单明确授权",
                    "The private infrastructure target is not explicitly authorized by the CIDR allowlist",
                    params=exc.params,
                ) from exc
            raise
        for address in endpoint_ips:
            if address not in resolved_ips:
                resolved_ips.append(address)

    normalized["endpoints"] = endpoints
    normalized["allow_insecure_transport"] = allow_insecure_transport
    return normalized, resolved_ips


@router.post("/targets", response_model=SecurityTargetResponse)
async def create_target(
    body: SecurityTargetCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    owner_user_id = body.owner_user_id if body.owner_user_id is not None else current_user.id
    _validate_owner(db, owner_user_id, body.owner_group_id)
    cidrs = normalize_cidrs(body.allowed_cidrs)
    asset_type, connector_type = validate_asset_connector(body.asset_type, body.connector_type)
    legacy_target_type = legacy_target_type_for(asset_type, connector_type)
    validate_target_type_scheme(legacy_target_type, body.endpoint_url)
    if connector_type == MCP_GATEWAY_TARGET_TYPE:
        config, _gateway = _validate_mcp_gateway_target(
            db,
            endpoint_url=body.endpoint_url,
            config=dict(body.config),
            allowed_cidrs=cidrs,
            allow_insecure_transport=body.allow_insecure_transport,
            environment=body.environment,
        )
        resolved: list[str] = []
    elif asset_type == "llm":
        resolved = resolve_target_endpoint(
            body.endpoint_url,
            allowed_cidrs=cidrs,
            allow_insecure_transport=body.allow_insecure_transport,
        )
        config = validate_llm_target_config(dict(body.config), require_complete=True)
        config["allow_insecure_transport"] = body.allow_insecure_transport
    elif asset_type == "ai_infrastructure":
        config, resolved = _validate_infrastructure_endpoints(
            endpoint_url=body.endpoint_url,
            config=dict(body.config),
            allowed_cidrs=cidrs,
            allow_insecure_transport=body.allow_insecure_transport,
        )
    else:
        resolved = resolve_target_endpoint(
            body.endpoint_url,
            allowed_cidrs=cidrs,
            allow_insecure_transport=body.allow_insecure_transport,
        )
        config = validate_agent_target_config(legacy_target_type, dict(body.config))
        if connector_type == "dify":
            _validate_dify_mcp_servers(db, config)
        config["allow_insecure_transport"] = body.allow_insecure_transport
    row = models.SecurityTarget(
        target_id=new_resource_id("ast"),
        name=body.name,
        target_type=legacy_target_type,
        asset_type=asset_type,
        connector_type=connector_type,
        environment=body.environment,
        allowed_capabilities_json=json_dumps(body.allowed_capabilities),
        endpoint_url=body.endpoint_url,
        owner_user_id=owner_user_id,
        owner_group_id=body.owner_group_id,
        allowed_cidrs_json=json_dumps(cidrs),
        resolved_ips_json=json_dumps(resolved),
        config_json=json_dumps(config),
        created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_target.created",
        actor=current_user.username,
        resource_type="security_target",
        resource_id=row.target_id,
        action="create",
        details={
            "target_type": row.target_type,
            "asset_type": row.asset_type,
            "connector_type": row.connector_type,
            "environment": row.environment,
            "allowed_capabilities": body.allowed_capabilities,
            "owner_user_id": owner_user_id,
            "owner_group_id": body.owner_group_id,
        },
    )
    return _target_response(db, row)


@router.get("/targets", response_model=list[SecurityTargetResponse])
async def list_targets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    rows = db.query(models.SecurityTarget).order_by(models.SecurityTarget.id.desc()).all()
    return [_target_response(db, row) for row in rows if _can_access_target(db, current_user, row)]


@router.get("/targets/{target_id}", response_model=SecurityTargetResponse)
async def get_target(
    target_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    row = _target_or_404(db, target_id)
    _require_target_access(db, current_user, row)
    return _target_response(db, row)


@router.get("/targets/{target_id}/dify-mcp-binding-options")
async def get_dify_mcp_binding_options(
    target_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = _target_or_404(db, target_id)
    if row.connector_type != "dify":
        raise ApiError(
            409,
            "dify_inventory.target_kind_invalid",
            "该目标不是 Dify 智能体",
            "This target is not a Dify agent",
        )
    return _dify_mcp_binding_options(db, row)


@router.patch("/targets/{target_id}", response_model=SecurityTargetResponse)
async def update_target(
    target_id: str,
    body: SecurityTargetUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = _target_or_404(db, target_id)
    data = body.model_dump(exclude_unset=True)
    owner_user_id = data.get("owner_user_id", row.owner_user_id)
    owner_group_id = data.get("owner_group_id", row.owner_group_id)
    _validate_owner(db, owner_user_id, owner_group_id)
    cidrs = normalize_cidrs(data.get("allowed_cidrs", json_loads(row.allowed_cidrs_json, [])))
    config = json_loads(row.config_json, {})
    if "config" in data:
        config = dict(data["config"])
    allow_insecure = data.get("allow_insecure_transport", config.get("allow_insecure_transport", False))
    endpoint = data.get("endpoint_url", row.endpoint_url)
    asset_type, connector_type = validate_asset_connector(
        data.get("asset_type", row.asset_type),
        data.get("connector_type", row.connector_type),
    )
    legacy_target_type = legacy_target_type_for(asset_type, connector_type)
    validate_target_type_scheme(legacy_target_type, endpoint)
    if connector_type == MCP_GATEWAY_TARGET_TYPE:
        config, _gateway = _validate_mcp_gateway_target(
            db,
            endpoint_url=endpoint,
            config=config,
            allowed_cidrs=cidrs,
            allow_insecure_transport=allow_insecure,
            environment=data.get("environment", row.environment),
        )
        resolved = []
    elif asset_type == "llm":
        config = validate_llm_target_config(config, require_complete=True)
        config["allow_insecure_transport"] = allow_insecure
        resolved = resolve_target_endpoint(endpoint, allowed_cidrs=cidrs, allow_insecure_transport=allow_insecure)
    elif asset_type == "ai_infrastructure":
        config, resolved = _validate_infrastructure_endpoints(
            endpoint_url=endpoint,
            config=config,
            allowed_cidrs=cidrs,
            allow_insecure_transport=allow_insecure,
        )
    else:
        config = validate_agent_target_config(legacy_target_type, config)
        if connector_type == "dify":
            _validate_dify_mcp_servers(db, config)
        config["allow_insecure_transport"] = allow_insecure
        resolved = resolve_target_endpoint(endpoint, allowed_cidrs=cidrs, allow_insecure_transport=allow_insecure)
    for field in ("name", "status"):
        if field in data:
            setattr(row, field, data[field])
    if "environment" in data:
        row.environment = data["environment"]
    if "allowed_capabilities" in data:
        row.allowed_capabilities_json = json_dumps(data["allowed_capabilities"])
    row.endpoint_url = endpoint
    row.target_type = legacy_target_type
    row.asset_type = asset_type
    row.connector_type = connector_type
    row.owner_user_id = owner_user_id
    row.owner_group_id = owner_group_id
    row.allowed_cidrs_json = json_dumps(cidrs)
    row.resolved_ips_json = json_dumps(resolved)
    row.config_json = json_dumps(config)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_target.updated",
        actor=current_user.username,
        resource_type="security_target",
        resource_id=row.target_id,
        action="update",
        details={
            "environment": row.environment,
            "asset_type": row.asset_type,
            "connector_type": row.connector_type,
            "allowed_capabilities": json_loads(row.allowed_capabilities_json, []),
        },
    )
    return _target_response(db, row)


@router.post("/targets/{target_id}/credentials", response_model=SecurityCredentialResponse)
async def create_target_credential(
    target_id: str,
    body: SecurityCredentialCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    target = _target_or_404(db, target_id)
    purpose = body.purpose or ("dify_app_api" if target.connector_type == "dify" else "agent_runtime")
    if target.target_type == MCP_GATEWAY_TARGET_TYPE:
        raise ApiError(
            409,
            "agent_security.mcp_target_credential_forbidden",
            "MCP Gateway 元数据扫描不需要也不接收目标凭据",
            "MCP Gateway metadata scans do not require or accept target credentials",
        )
    now = datetime.utcnow()
    if purpose.startswith("dify_") and target.connector_type != "dify":
        raise ApiError(
            409, "dify_inventory.credential_target_mismatch",
            "Dify 凭据只能绑定 Dify 扫描目标", "Dify credentials can only be bound to a Dify target",
        )
    active = _active_credential(db, target_id, purpose)
    if active:
        active.status = "revoked"
        active.revoked_at = now
        active.revoked_by = current_user.username
        active.updated_at = now
    # Keep the sequence target-global so upgraded SQLite databases that still
    # enforce the historical (target_id, version) uniqueness remain writable.
    # Purpose still scopes active selection, rotation, and Worker delivery.
    latest = (
        db.query(models.SecurityTargetCredential)
        .filter(models.SecurityTargetCredential.target_id == target_id)
        .order_by(models.SecurityTargetCredential.version.desc())
        .first()
    )
    row = models.SecurityTargetCredential(
        credential_id=new_resource_id("asc"),
        target_id=target_id,
        purpose=purpose,
        credential_type=body.credential_type,
        secret_encrypted=protect_secret(body.secret),
        secret_masked=mask_secret(body.secret),
        version=(latest.version + 1) if latest else 1,
        created_by=current_user.username,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_target.credential_rotated",
        actor=current_user.username,
        resource_type="security_target_credential",
        resource_id=row.credential_id,
        action="create",
        details={"target_id": target_id, "purpose": row.purpose, "version": row.version},
    )
    # User-supplied Dify administrative keys are never reflected in an API
    # response. The encrypted Worker envelope is their only plaintext egress.
    secret_once = None if purpose in {"dify_console_api", "dify_knowledge_api"} else body.secret
    return _credential_response(row, secret_once=secret_once)


@router.patch("/credentials/{credential_id}", response_model=SecurityCredentialResponse)
async def update_target_credential(
    credential_id: str,
    body: SecurityCredentialUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = (
        db.query(models.SecurityTargetCredential)
        .filter(models.SecurityTargetCredential.credential_id == credential_id)
        .first()
    )
    if not row:
        raise ApiError(404, "agent_security.credential_not_found", "目标凭据不存在", "Target credential not found")
    if row.status != "active":
        raise ApiError(409, "agent_security.credential_revoked", "目标凭据已吊销", "Target credential is revoked")
    row.secret_encrypted = protect_secret(body.secret)
    row.secret_masked = mask_secret(body.secret)
    row.version += 1
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_target.credential_rotated",
        actor=current_user.username,
        resource_type="security_target_credential",
        resource_id=row.credential_id,
        action="update",
        details={"target_id": row.target_id, "purpose": row.purpose, "version": row.version},
    )
    return _credential_response(row)


@router.patch("/credentials/{credential_id}/status", response_model=SecurityCredentialResponse)
async def update_target_credential_status(
    credential_id: str,
    body: SecurityCredentialStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = db.query(models.SecurityTargetCredential).filter(
        models.SecurityTargetCredential.credential_id == credential_id
    ).first()
    if not row:
        raise ApiError(404, "agent_security.credential_not_found", "目标凭据不存在", "Target credential not found")
    if row.status == "revoked":
        raise ApiError(409, "agent_security.credential_revoked", "目标凭据已吊销", "Target credential is revoked")
    if body.status == "active":
        conflicting = _active_credential(db, row.target_id, row.purpose)
        if conflicting and conflicting.credential_id != row.credential_id:
            raise ApiError(
                409, "dify_inventory.credential_active_conflict",
                "该用途已有活动凭据", "This credential purpose already has an active credential",
            )
    if row.status != body.status:
        row.status = body.status
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        _audit(
            db,
            event_type=f"security_target.credential_{'enabled' if body.status == 'active' else 'disabled'}",
            actor=current_user.username,
            resource_type="security_target_credential",
            resource_id=row.credential_id,
            action="update",
            details={"target_id": row.target_id, "purpose": row.purpose, "status": row.status},
        )
    return _credential_response(row)


@router.post("/credentials/{credential_id}/revoke", response_model=SecurityCredentialResponse)
async def revoke_target_credential(
    credential_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = (
        db.query(models.SecurityTargetCredential)
        .filter(models.SecurityTargetCredential.credential_id == credential_id)
        .first()
    )
    if not row:
        raise ApiError(404, "agent_security.credential_not_found", "目标凭据不存在", "Target credential not found")
    if row.status == "active":
        row.status = "revoked"
        row.revoked_at = datetime.utcnow()
        row.revoked_by = current_user.username
        row.updated_at = row.revoked_at
        db.commit()
        db.refresh(row)
        _audit(
            db,
            event_type="security_target.credential_revoked",
            actor=current_user.username,
            resource_type="security_target_credential",
            resource_id=row.credential_id,
            action="revoke",
            details={"target_id": row.target_id, "purpose": row.purpose},
        )
    return _credential_response(row)


@router.post("/policies", response_model=SecurityPolicyResponse)
async def create_policy(
    body: SecurityPolicyCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    _reject_production_active_full(body.environment, body.execution_mode)
    if db.query(models.SecurityScanPolicy).filter(models.SecurityScanPolicy.name == body.name).first():
        raise ApiError(
            409, "agent_security.policy_name_conflict", "扫描策略名称已存在", "Scan policy name already exists"
        )
    values = body.model_dump()
    allowlist = normalize_cidrs(values.pop("outbound_allowlist"))
    allowed_capabilities = values.pop("allowed_capabilities")
    production_target_ids = values.pop("production_target_ids")
    window_start, window_end, identity_ref = _validate_production_active_safe_controls(
        db,
        environment=body.environment,
        execution_mode=body.execution_mode,
        production_target_ids=production_target_ids,
        maintenance_window_start=body.maintenance_window_start,
        maintenance_window_end=body.maintenance_window_end,
        dedicated_identity_ref=body.dedicated_identity_ref,
    )
    values["maintenance_window_start"] = window_start
    values["maintenance_window_end"] = window_end
    values["dedicated_identity_ref"] = identity_ref
    row = models.SecurityScanPolicy(
        policy_id=new_resource_id("asp"),
        outbound_allowlist_json=json_dumps(allowlist),
        allowed_capabilities_json=json_dumps(allowed_capabilities),
        production_target_ids_json=json_dumps(production_target_ids),
        created_by=current_user.username,
        **values,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_scan_policy.created",
        actor=current_user.username,
        resource_type="security_scan_policy",
        resource_id=row.policy_id,
        action="create",
        details={
            "environment": row.environment,
            "execution_mode": row.execution_mode,
            "allowed_capabilities": allowed_capabilities,
            "production_target_ids": production_target_ids,
            "maintenance_window_start": window_start.isoformat() if window_start else None,
            "maintenance_window_end": window_end.isoformat() if window_end else None,
            "dedicated_identity_ref": identity_ref,
        },
    )
    return SecurityPolicyResponse(**_policy_payload(row))


@router.get("/policies", response_model=list[SecurityPolicyResponse])
async def list_policies(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    query = db.query(models.SecurityScanPolicy)
    if current_user.role not in SECURITY_READER_ROLES:
        query = query.filter(models.SecurityScanPolicy.enabled.is_(True))
    return [
        SecurityPolicyResponse(**_policy_payload(row)) for row in query.order_by(models.SecurityScanPolicy.id).all()
    ]


@router.patch("/policies/{policy_id}", response_model=SecurityPolicyResponse)
async def update_policy(
    policy_id: str,
    body: SecurityPolicyUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = _policy_or_404(db, policy_id)
    data = body.model_dump(exclude_unset=True)
    _reject_production_active_full(
        data.get("environment", row.environment),
        data.get("execution_mode", row.execution_mode),
    )
    production_target_ids = data.get(
        "production_target_ids", json_loads(row.production_target_ids_json, [])
    )
    window_start, window_end, identity_ref = _validate_production_active_safe_controls(
        db,
        environment=data.get("environment", row.environment),
        execution_mode=data.get("execution_mode", row.execution_mode),
        production_target_ids=production_target_ids,
        maintenance_window_start=data.get("maintenance_window_start", row.maintenance_window_start),
        maintenance_window_end=data.get("maintenance_window_end", row.maintenance_window_end),
        dedicated_identity_ref=data.get("dedicated_identity_ref", row.dedicated_identity_ref),
    )
    if "outbound_allowlist" in data:
        row.outbound_allowlist_json = json_dumps(normalize_cidrs(data.pop("outbound_allowlist") or []))
    if "allowed_capabilities" in data:
        row.allowed_capabilities_json = json_dumps(data.pop("allowed_capabilities") or [])
    if "production_target_ids" in data:
        row.production_target_ids_json = json_dumps(data.pop("production_target_ids") or [])
    if "maintenance_window_start" in data:
        data["maintenance_window_start"] = window_start
    if "maintenance_window_end" in data:
        data["maintenance_window_end"] = window_end
    if "dedicated_identity_ref" in data:
        data["dedicated_identity_ref"] = identity_ref
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_scan_policy.updated",
        actor=current_user.username,
        resource_type="security_scan_policy",
        resource_id=row.policy_id,
        action="update",
        details={
            "environment": row.environment,
            "execution_mode": row.execution_mode,
            "allowed_capabilities": json_loads(row.allowed_capabilities_json, []),
            "production_target_ids": json_loads(row.production_target_ids_json, []),
            "maintenance_window_start": row.maintenance_window_start.isoformat() if row.maintenance_window_start else None,
            "maintenance_window_end": row.maintenance_window_end.isoformat() if row.maintenance_window_end else None,
            "dedicated_identity_ref": row.dedicated_identity_ref,
        },
    )
    return SecurityPolicyResponse(**_policy_payload(row))


def _expire_scan_approvals(db: Session, *, now: datetime | None = None) -> None:
    current = now or datetime.utcnow()
    db.query(models.SecurityScanApproval).filter(
        models.SecurityScanApproval.status == "approved",
        models.SecurityScanApproval.maintenance_window_end <= current,
    ).update({"status": "expired"}, synchronize_session=False)


@router.get("/scan-approvals", response_model=list[SecurityScanApprovalResponse])
async def list_scan_approvals(
    target_id: str | None = Query(default=None, max_length=64),
    policy_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    _expire_scan_approvals(db)
    db.commit()
    query = db.query(models.SecurityScanApproval)
    if target_id:
        query = query.filter(models.SecurityScanApproval.target_id == target_id)
    if policy_id:
        query = query.filter(models.SecurityScanApproval.policy_id == policy_id)
    if status:
        query = query.filter(models.SecurityScanApproval.status == status)
    rows = query.order_by(models.SecurityScanApproval.id.desc()).limit(500).all()
    visible = []
    for row in rows:
        target = _target_or_404(db, row.target_id)
        if _can_access_target(db, current_user, target):
            visible.append(_approval_response(row))
    return visible


@router.post("/scan-approvals", response_model=SecurityScanApprovalResponse)
async def create_scan_approval(
    body: SecurityScanApprovalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    now = datetime.utcnow()
    target = _target_or_404(db, body.target_id)
    policy = _policy_or_404(db, body.policy_id)
    if target.environment != "production" or policy.environment != "production" or policy.execution_mode != "active_safe":
        raise ApiError(
            409,
            "agent_security.production_active_safe_approval_not_applicable",
            "该目标和策略不属于生产主动安全扫描审批范围",
            "The target and policy are not eligible for production active-safe approval",
        )
    target_ids = json_loads(policy.production_target_ids_json, [])
    window_start, window_end, identity_ref = _validate_production_active_safe_controls(
        db,
        environment=policy.environment,
        execution_mode=policy.execution_mode,
        production_target_ids=target_ids,
        maintenance_window_start=policy.maintenance_window_start,
        maintenance_window_end=policy.maintenance_window_end,
        dedicated_identity_ref=policy.dedicated_identity_ref,
    )
    if target.target_id not in target_ids:
        raise ApiError(
            409,
            "agent_security.production_target_not_allowlisted",
            "生产扫描目标不在策略白名单中",
            "The production scan target is not allowlisted by the policy",
        )
    if window_end <= now:
        raise ApiError(
            409,
            "agent_security.production_maintenance_window_expired",
            "生产扫描维护窗口已结束",
            "The production scan maintenance window has ended",
        )
    credential = _active_credential(db, target.target_id)
    if not credential:
        raise ApiError(
            409,
            "agent_security.production_dedicated_credential_required",
            "生产主动安全扫描必须为目标配置专用凭据",
            "Production active-safe scanning requires a dedicated target credential",
        )
    existing = db.query(models.SecurityScanApproval).filter(
        models.SecurityScanApproval.target_id == target.target_id,
        models.SecurityScanApproval.policy_id == policy.policy_id,
        models.SecurityScanApproval.credential_id == credential.credential_id,
        models.SecurityScanApproval.credential_version == credential.version,
        models.SecurityScanApproval.dedicated_identity_ref == identity_ref,
        models.SecurityScanApproval.maintenance_window_start == window_start,
        models.SecurityScanApproval.maintenance_window_end == window_end,
        models.SecurityScanApproval.status == "approved",
    ).first()
    if existing:
        return _approval_response(existing)
    row = models.SecurityScanApproval(
        approval_id=new_resource_id("asa"),
        target_id=target.target_id,
        policy_id=policy.policy_id,
        credential_id=credential.credential_id,
        credential_version=credential.version,
        dedicated_identity_ref=identity_ref,
        maintenance_window_start=window_start,
        maintenance_window_end=window_end,
        approved_by=current_user.username,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_scan_approval.approved",
        actor=current_user.username,
        resource_type="security_scan_approval",
        resource_id=row.approval_id,
        action="approve",
        details={
            "target_id": row.target_id,
            "policy_id": row.policy_id,
            "credential_id": row.credential_id,
            "credential_version": row.credential_version,
            "dedicated_identity_ref": row.dedicated_identity_ref,
            "maintenance_window_start": row.maintenance_window_start.isoformat(),
            "maintenance_window_end": row.maintenance_window_end.isoformat(),
        },
    )
    return _approval_response(row)


def _normalize_mcp_identifier_text(value: str) -> str:
    return normalize_mcp_identifier(value)


def _mcp_full_schema_signals(schema: Any) -> tuple[list[dict[str, str]], bool]:
    signals: dict[tuple[str, str], dict[str, str]] = {}
    visited = 0
    analysis_limited = False

    def visit(value: Any, *, path: str, depth: int) -> None:
        nonlocal visited, analysis_limited
        if analysis_limited:
            return
        visited += 1
        if visited > 100_000 or depth > 64:
            analysis_limited = True
            return
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = f"{path}.{key}"
                description = str(child.get("description") or "") if isinstance(child, dict) else ""
                for category in classify_mcp_parameter(key, description=description, parent_path=path):
                    if len(signals) < 100:
                        safe_path, _truncated = sanitize_mcp_metadata_text(child_path, max_length=512)
                        signals[(safe_path, category)] = {"path": safe_path, "category": category}
                visit(child, path=child_path, depth=depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path=f"{path}[{index}]", depth=depth + 1)

    visit(schema, path="$", depth=0)
    return list(signals.values()), analysis_limited


def _mcp_gateway_assets_snapshot(db: Session, gateway_id: int) -> dict[str, Any]:
    gateway = db.query(models.McpGateway).filter(models.McpGateway.id == gateway_id).first()
    if not gateway:
        raise ApiError(
            404,
            "agent_security.mcp_gateway_not_found",
            "MCP Gateway 不存在",
            "The MCP Gateway does not exist",
            params={"gateway_id": gateway_id},
        )
    servers: list[dict[str, Any]] = []
    bindings = (
        db.query(models.McpGatewayBinding)
        .filter(models.McpGatewayBinding.gateway_id == gateway.id)
        .order_by(models.McpGatewayBinding.id)
        .all()
    )
    for binding in bindings:
        server = db.query(models.McpServer).filter(models.McpServer.id == binding.server_id).first()
        if not server:
            continue
        allowed_names = [str(value) for value in json_loads(binding.allowed_tools_json, [])]
        approved_hashes = json_loads(binding.approved_schema_hashes_json, {})
        rows = (
            db.query(models.McpTool)
            .filter(models.McpTool.server_id == server.id, models.McpTool.name.in_(allowed_names))
            .order_by(models.McpTool.id)
            .all()
            if allowed_names
            else []
        )
        by_name = {row.name: row for row in rows}
        tools = []
        for tool_name in allowed_names:
            tool = by_name.get(tool_name)
            if not tool:
                tools.append(
                    {
                        "tool_id": None,
                        "name": tool_name,
                        "exposed_name": f"{server.slug}__{tool_name}",
                        "missing": True,
                        "approved_schema_hash": approved_hashes.get(tool_name),
                    }
                )
                continue
            raw_description = tool.description or ""
            raw_input_schema = json_loads(tool.input_schema_json, {})
            safe_description, description_truncated = sanitize_mcp_metadata_text(raw_description)
            safe_input_schema, schema_projection = sanitize_mcp_metadata_value(raw_input_schema)
            full_parameter_signals, analysis_limited = _mcp_full_schema_signals(raw_input_schema)
            full_operation_text = _normalize_mcp_identifier_text(f"{tool.name} {raw_description}")
            tools.append(
                {
                    "tool_id": tool.id,
                    "name": tool.name,
                    "exposed_name": tool.exposed_name,
                    # MCP metadata is untrusted input. Workers only need a bounded,
                    # redacted projection; retain hashes for correlation with the
                    # inventory without copying raw credentials or common PII values.
                    "description": safe_description,
                    "description_sha256": hashlib.sha256(raw_description.encode("utf-8")).hexdigest(),
                    "input_schema": safe_input_schema,
                    "input_schema_sha256": hashlib.sha256(
                        json_dumps(raw_input_schema).encode("utf-8")
                    ).hexdigest(),
                    "raw_analysis": {
                        "description_injection_detected": any(
                            pattern.search(raw_description) for pattern in _MCP_RAW_INJECTION_PATTERNS
                        ),
                        "side_effect_categories": [
                            category
                            for category, pattern in _MCP_RAW_SIDE_EFFECT_RULES
                            if pattern.search(full_operation_text)
                        ],
                        "parameter_signals": full_parameter_signals,
                        "analysis_limited": analysis_limited,
                    },
                    "projection": {
                        "description_truncated": description_truncated,
                        **schema_projection,
                    },
                    "schema_hash": tool.schema_hash,
                    "approved_schema_hash": approved_hashes.get(tool.name),
                    "enabled": bool(tool.enabled),
                    "access_mode": tool.access_mode,
                    "risk_level": tool.risk_level,
                    "requires_approval": bool(tool.requires_approval),
                    "rate_limit_per_minute": tool.rate_limit_per_minute,
                    "max_concurrent": tool.max_concurrent,
                    "missing": False,
                }
            )
        servers.append(
            {
                "server_id": server.id,
                "server_slug": server.slug,
                "server_name": server.name,
                "server_status": server.status,
                "tools": tools,
            }
        )
    return {
        "gateway_id": gateway.id,
        "gateway_slug": gateway.slug,
        "gateway_name": gateway.name,
        "gateway_status": gateway.status,
        "gateway_environment": gateway.environment,
        "gateway_execution_mode": gateway.execution_mode,
        "production_tool_denylist": json_loads(gateway.production_tool_denylist_json, []),
        "servers": servers,
    }


def _target_snapshot(db: Session, target: models.SecurityTarget) -> dict[str, Any]:
    config = json_loads(target.config_json, {})
    snapshot = {
        "target_id": target.target_id,
        "target_type": target.target_type,
        "asset_type": target.asset_type,
        "connector_type": target.connector_type,
        "environment": target.environment,
        "allowed_capabilities": json_loads(target.allowed_capabilities_json, []),
        "endpoint_url": target.endpoint_url,
        "resolved_ips": json_loads(target.resolved_ips_json, []),
        "allowed_cidrs": json_loads(target.allowed_cidrs_json, []),
        "allow_insecure_transport": bool(config.get("allow_insecure_transport", False)),
        "config": {key: value for key, value in config.items() if key != "allow_insecure_transport"},
    }
    if target.connector_type == MCP_GATEWAY_TARGET_TYPE:
        mcp_assets = _mcp_gateway_assets_snapshot(db, int(config["gateway_id"]))
        if not any(server.get("tools") for server in mcp_assets.get("servers", [])):
            raise ApiError(
                409,
                "agent_security.mcp_assets_empty",
                "MCP Gateway 没有可扫描的已绑定 Tool",
                "The MCP Gateway has no bound tools to scan",
            )
        snapshot["mcp_assets"] = mcp_assets
        snapshot["scan_transport"] = "metadata_snapshot_only"
    return snapshot


def _dify_mcp_inventory_snapshot(db: Session, bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    server_ids = {int(item["server_id"]) for item in bindings}
    if not server_ids:
        return []
    servers = db.query(models.McpServer).filter(models.McpServer.id.in_(server_ids)).all()
    result = []
    for server in servers:
        tools = db.query(models.McpTool).filter(models.McpTool.server_id == server.id).order_by(models.McpTool.id).all()
        result.append({
            "server_id": server.id, "server_slug": server.slug, "server_name": server.name,
            "discovered_at": server.last_checked_at.isoformat() if server.last_checked_at else None,
            "tools": [{
                "name": tool.name, "description": sanitize_mcp_metadata_text(tool.description or ""),
                "input_schema": sanitize_mcp_metadata_value(json_loads(tool.input_schema_json, {})),
                "schema_hash": tool.schema_hash, "access_mode": tool.access_mode,
                "risk_level": tool.risk_level, "requires_approval": bool(tool.requires_approval),
            } for tool in tools if tool.enabled],
        })
    return result


def _validate_dify_mcp_servers(db: Session, config: dict[str, Any]) -> None:
    bindings = list(config.get("mcp_bindings") or [])
    server_ids = {int(item["server_id"]) for item in bindings}
    if not server_ids:
        return
    existing_ids = {
        row[0] for row in db.query(models.McpServer.id).filter(models.McpServer.id.in_(server_ids)).all()
    }
    missing_ids = sorted(server_ids - existing_ids)
    if missing_ids:
        raise ApiError(
            404,
            "dify_inventory.mcp_server_not_found",
            "绑定的 MCP Server 不存在",
            "A bound MCP Server does not exist",
            params={"server_id": missing_ids[0]},
        )


def _dify_mcp_binding_options(db: Session, target: models.SecurityTarget) -> dict[str, Any]:
    config = json_loads(target.config_json, {})
    configured_bindings = {
        str(item.get("provider_id")): int(item["server_id"])
        for item in config.get("mcp_bindings", [])
        if isinstance(item, dict) and item.get("provider_id") and isinstance(item.get("server_id"), int)
    }
    latest_snapshot = (
        db.query(models.SecurityAssetInventorySnapshot)
        .filter(models.SecurityAssetInventorySnapshot.target_id == target.target_id)
        .order_by(models.SecurityAssetInventorySnapshot.id.desc())
        .first()
    )
    provider_tools: dict[str, set[str]] = {}
    if latest_snapshot:
        item_rows = db.query(models.SecurityAssetInventoryItem).filter(
            models.SecurityAssetInventoryItem.snapshot_id == latest_snapshot.snapshot_id,
            models.SecurityAssetInventoryItem.asset_type == "mcp",
        ).order_by(models.SecurityAssetInventoryItem.id).all()
        for item in item_rows:
            details = json_loads(item.details_json, {})
            provider_id = str(details.get("provider_id") or "").strip()
            tool_name = str(details.get("tool_name") or item.name or "").strip()
            if provider_id:
                provider_tools.setdefault(provider_id, set())
                if tool_name:
                    provider_tools[provider_id].add(tool_name)
    for provider_id in configured_bindings:
        provider_tools.setdefault(provider_id, set())

    server_rows = db.query(models.McpServer).order_by(models.McpServer.name, models.McpServer.id).all()
    server_payloads = []
    tools_by_server: dict[int, set[str]] = {}
    for server in server_rows:
        tools = db.query(models.McpTool).filter(
            models.McpTool.server_id == server.id,
            models.McpTool.enabled.is_(True),
        ).order_by(models.McpTool.name).all()
        tool_names = {tool.name for tool in tools}
        tools_by_server[server.id] = tool_names
        server_payloads.append({
            "server_id": server.id,
            "name": server.name,
            "slug": server.slug,
            "status": server.status,
            "health_status": server.health_status,
            "tools_list_at": server.last_checked_at.isoformat() if server.last_checked_at else None,
            "tool_count": len(tool_names),
            "tool_names": sorted(tool_names),
        })

    counts = {"verified": 0, "unbound": 0, "configured_tool_not_discovered": 0}
    providers = []
    for provider_id in sorted(provider_tools):
        tool_names = sorted(provider_tools[provider_id])
        server_id = configured_bindings.get(provider_id)
        if server_id is None:
            binding_status = "unbound"
        elif not set(tool_names).issubset(tools_by_server.get(server_id, set())):
            binding_status = "configured_tool_not_discovered"
        else:
            binding_status = "verified"
        counts[binding_status] += 1
        providers.append({
            "provider_id": provider_id,
            "tool_names": tool_names,
            "server_id": server_id,
            "binding_status": binding_status,
            "source": "latest_dify_asset_snapshot" if latest_snapshot and tool_names else "configured_binding",
        })
    return {
        "snapshot_id": latest_snapshot.snapshot_id if latest_snapshot else None,
        "providers": providers,
        "servers": server_payloads,
        "summary": counts,
    }


def _dify_runtime_inventory_snapshot(
    db: Session, *, app_id: str, owner_user_id: int | None, owner_group_id: int | None
) -> list[dict[str, Any]]:
    traces = db.query(models.RuntimeTraceSession).filter(
        models.RuntimeTraceSession.agent_id == app_id,
        models.RuntimeTraceSession.owner_user_id == owner_user_id,
        models.RuntimeTraceSession.owner_group_id == owner_group_id,
    ).order_by(models.RuntimeTraceSession.id.desc()).limit(100).all()
    trace_ids = [row.trace_id for row in traces]
    if not trace_ids:
        return []
    events = db.query(models.RuntimeTraceEvent).filter(
        models.RuntimeTraceEvent.trace_id.in_(trace_ids)
    ).order_by(models.RuntimeTraceEvent.event_time).limit(5000).all()
    return [{
        "trace_id": event.trace_id, "event_id": event.event_id,
        "event_time": event.event_time.isoformat(), "type": event.type,
        "status": event.status, "tool_name": event.tool_name, "node_id": event.step_id,
    } for event in events]


def _verify_target_snapshot_dns(snapshot: dict[str, Any], *, allowed_cidrs: list[str]) -> None:
    if snapshot.get("asset_type") != "ai_infrastructure":
        verify_dns_pin(
            snapshot["endpoint_url"],
            snapshot.get("resolved_ips", []),
            allowed_cidrs=allowed_cidrs,
            allow_insecure_transport=bool(snapshot.get("allow_insecure_transport", False)),
        )
        return

    endpoints = snapshot.get("config", {}).get("endpoints") or [snapshot["endpoint_url"]]
    current_ips: list[str] = []
    for endpoint in endpoints:
        for address in resolve_target_endpoint(
            endpoint,
            allowed_cidrs=allowed_cidrs,
            allow_insecure_transport=bool(snapshot.get("allow_insecure_transport", False)),
        ):
            if address not in current_ips:
                current_ips.append(address)
    if set(current_ips) != set(snapshot.get("resolved_ips", [])):
        raise ApiError(
            409,
            "agent_security.dns_rebinding_detected",
            "目标地址解析结果已变化，任务已阻止",
            "The target DNS resolution changed and the task was blocked",
        )


def _production_active_safe_approval(
    db: Session,
    *,
    target: models.SecurityTarget,
    policy: models.SecurityScanPolicy,
    approval_id: str | None,
    now: datetime,
) -> tuple[models.SecurityScanApproval | None, models.SecurityTargetCredential | None]:
    if policy.environment != "production" or policy.execution_mode != "active_safe":
        return None, None
    target_ids = json_loads(policy.production_target_ids_json, [])
    window_start, window_end, identity_ref = _validate_production_active_safe_controls(
        db,
        environment=policy.environment,
        execution_mode=policy.execution_mode,
        production_target_ids=target_ids,
        maintenance_window_start=policy.maintenance_window_start,
        maintenance_window_end=policy.maintenance_window_end,
        dedicated_identity_ref=policy.dedicated_identity_ref,
    )
    if target.target_id not in target_ids:
        raise ApiError(
            409,
            "agent_security.production_target_not_allowlisted",
            "生产扫描目标不在策略白名单中",
            "The production scan target is not allowlisted by the policy",
        )
    if now < window_start or now >= window_end:
        raise ApiError(
            409,
            "agent_security.production_maintenance_window_inactive",
            "当前时间不在生产扫描维护窗口内",
            "The current time is outside the production scan maintenance window",
        )
    if not approval_id:
        raise ApiError(
            409,
            "agent_security.production_active_safe_approval_required",
            "生产主动安全扫描必须提供有效人工审批",
            "Production active-safe scanning requires a valid human approval",
        )
    credential = _active_credential(db, target.target_id)
    if not credential:
        raise ApiError(
            409,
            "agent_security.production_dedicated_credential_required",
            "生产主动安全扫描必须为目标配置专用凭据",
            "Production active-safe scanning requires a dedicated target credential",
        )
    approval = db.query(models.SecurityScanApproval).filter(
        models.SecurityScanApproval.approval_id == approval_id,
        models.SecurityScanApproval.target_id == target.target_id,
        models.SecurityScanApproval.policy_id == policy.policy_id,
        models.SecurityScanApproval.credential_id == credential.credential_id,
        models.SecurityScanApproval.credential_version == credential.version,
        models.SecurityScanApproval.dedicated_identity_ref == identity_ref,
        models.SecurityScanApproval.maintenance_window_start == window_start,
        models.SecurityScanApproval.maintenance_window_end == window_end,
        models.SecurityScanApproval.status == "approved",
    ).first()
    if not approval:
        raise ApiError(
            409,
            "agent_security.production_active_safe_approval_invalid",
            "生产主动安全扫描审批无效、已使用或与当前配置不匹配",
            "The production active-safe approval is invalid, used, or does not match the current configuration",
        )
    return approval, credential


def _validate_scan_task_request(
    db: Session,
    body: SecurityTaskPlanRequest,
    current_user: models.User,
) -> dict[str, Any]:
    target = _target_or_404(db, body.target_id)
    _require_target_access(db, current_user, target)
    if target.status != "active":
        raise ApiError(409, "agent_security.target_disabled", "扫描目标未启用", "Scan target is not active")
    policy = _policy_or_404(db, body.policy_id)
    if not policy.enabled:
        raise ApiError(409, "agent_security.policy_disabled", "扫描策略未启用", "Scan policy is not enabled")
    _reject_production_active_full(policy.environment, policy.execution_mode, status_code=409)
    if target.environment != policy.environment:
        raise ApiError(
            409,
            "agent_security.policy_environment_mismatch",
            "扫描策略环境与目标环境不一致",
            "The scan policy environment does not match the target environment",
        )
    target_capabilities = set(json_loads(target.allowed_capabilities_json, []))
    policy_capabilities = set(json_loads(policy.allowed_capabilities_json, []))
    unsupported_capabilities = sorted(policy_capabilities - target_capabilities)
    if unsupported_capabilities:
        raise ApiError(
            409,
            "agent_security.policy_capability_mismatch",
            "扫描策略包含目标未授权的能力",
            "The scan policy includes capabilities not authorized by the target",
            params={"unsupported_capabilities": unsupported_capabilities},
        )
    supported_kinds = ASSET_SCAN_KINDS.get(target.asset_type, set())
    if body.scan_kind not in supported_kinds:
        raise ApiError(
            409,
            "agent_security.scan_kind_asset_mismatch",
            "扫描类型与扫描对象不兼容",
            "The scan kind is incompatible with the target asset",
            params={"asset_type": target.asset_type, "scan_kind": body.scan_kind},
        )
    if target.asset_type in {"llm", "ai_infrastructure"} and not _aig_engine_available():
        raise ApiError(
            503,
            "agent_security.aig_service_unavailable",
            "AI-Infra-Guard 扫描引擎尚未配置或不可用",
            "The AI-Infra-Guard scanning engine is not configured or available",
        )
    if body.scan_kind == "mcp_risk_scan":
        if target.target_type != MCP_GATEWAY_TARGET_TYPE:
            raise ApiError(
                409,
                "agent_security.mcp_scan_target_required",
                "MCP 风险扫描必须绑定 MCP Gateway 扫描目标",
                "MCP risk scans require an MCP Gateway scan target",
            )
        if body.skills or body.prompt or body.continue_from_task_id or body.conversation_mode != "single_turn":
            raise ApiError(
                422,
                "agent_security.mcp_scan_options_invalid",
                "MCP 元数据扫描不接受 Agent 技能、会话继续或多轮会话选项",
                "MCP metadata scans do not accept Agent skills, session continuation, or multi-turn options",
            )
    elif target.target_type == MCP_GATEWAY_TARGET_TYPE:
        raise ApiError(
            409,
            "agent_security.mcp_target_scan_kind_mismatch",
            "MCP Gateway 扫描目标只能执行 MCP 风险扫描",
            "MCP Gateway scan targets only support MCP risk scans",
        )
    continuation_state: str | None = None
    if body.scan_kind == "agent_risk_scan":
        target_config = json_loads(target.config_json, {})
        target_config.pop("allow_insecure_transport", None)
        validate_agent_target_config(target.target_type, target_config, require_complete=True)
        if policy.execution_mode == "passive":
            raise ApiError(
                409,
                "agent_security.active_scan_forbidden_by_policy",
                "被动策略不能创建主动 Agent 风险扫描",
                "Passive policies cannot create active Agent risk scans",
            )
        if body.continue_from_task_id and body.reset_session:
            raise ApiError(
                422,
                "agent_security.session_action_conflict",
                "继续会话和重置会话不能同时启用",
                "Session continuation and reset cannot both be enabled",
            )
        if body.continue_from_task_id:
            previous = _task_or_404(db, body.continue_from_task_id)
            _require_task_access(db, current_user, previous)
            if previous.target_id != target.target_id or previous.scan_kind != "agent_risk_scan":
                raise ApiError(
                    409,
                    "agent_security.session_target_mismatch",
                    "只能继续同一扫描目标的 Agent 风险扫描会话",
                    "Only Agent risk scan sessions for the same target can be continued",
                )
            continuation_state = unprotect_secret(previous.session_state_encrypted)
            if not continuation_state:
                raise ApiError(
                    409,
                    "agent_security.session_not_available",
                    "来源任务没有可继续的会话",
                    "The source task has no resumable session",
                )
    elif body.scan_kind == "llm_redteam_scan":
        target_config = validate_llm_target_config(
            json_loads(target.config_json, {}),
            require_complete=True,
        )
        if policy.execution_mode == "passive":
            raise ApiError(
                409,
                "agent_security.active_scan_forbidden_by_policy",
                "被动策略不能创建大模型红队扫描",
                "Passive policies cannot create LLM red-team scans",
            )
    elif body.scan_kind == "ai_infrastructure_vulnerability_scan":
        target_config, _resolved = _validate_infrastructure_endpoints(
            endpoint_url=target.endpoint_url,
            config=json_loads(target.config_json, {}),
            allowed_cidrs=json_loads(target.allowed_cidrs_json, []),
            allow_insecure_transport=bool(json_loads(target.config_json, {}).get("allow_insecure_transport", False)),
        )
        endpoints = target_config.get("endpoints") or [target.endpoint_url]
        if any(urlsplit(endpoint).scheme.lower() == "http" for endpoint in endpoints) and not body.http_authorized:
            raise ApiError(
                409,
                "agent_security.infra_target_forbidden",
                "HTTP 基础设施扫描需要任务级显式授权",
                "HTTP infrastructure scanning requires explicit task authorization",
            )
        resolved_addresses = [ipaddress.ip_address(value) for value in json_loads(target.resolved_ips_json, [])]
        if any(address.is_private for address in resolved_addresses) and not body.private_network_authorized:
            raise ApiError(
                409,
                "agent_security.infra_private_address_forbidden",
                "私网基础设施扫描需要任务级显式授权",
                "Private infrastructure scanning requires explicit task authorization",
            )
        if policy.execution_mode == "passive":
            raise ApiError(
                409,
                "agent_security.active_scan_forbidden_by_policy",
                "被动策略不能创建基础设施主动探测任务",
                "Passive policies cannot create active infrastructure probes",
            )
    elif body.scan_kind == "dify_asset_inventory":
        if target.connector_type != "dify":
            raise ApiError(
                409, "dify_inventory.dify_target_required",
                "Dify 资产清单必须绑定 Dify 扫描目标", "Dify inventory requires a Dify scan target",
            )
        target_config = validate_dify_inventory_target_config(
            json_loads(target.config_json, {}), require_complete=True
        )
        if body.include_prompt_text and current_user.role not in SECURITY_ADMIN_ROLES:
            raise ApiError(
                403, "dify_inventory.prompt_access_denied",
                "当前用户无权采集 Prompt 原文", "The current user cannot collect raw Prompt text",
            )
        if body.infer_agent_intent and current_user.role not in SECURITY_ADMIN_ROLES:
            raise ApiError(
                403, "dify_inventory.intent_inference_access_denied",
                "只有管理员可以启用智能体意图推断", "Only administrators can enable agent intent inference",
            )
        if body.intent_inference_model:
            inference_model = db.query(models.ModelEndpoint).filter(
                models.ModelEndpoint.name == body.intent_inference_model,
                models.ModelEndpoint.enabled.is_(True),
            ).first()
            inference_provider = (
                db.query(models.ModelProvider).filter(
                    models.ModelProvider.id == inference_model.provider_id,
                    models.ModelProvider.enabled.is_(True),
                ).first()
                if inference_model else None
            )
            if not inference_model or not inference_provider:
                raise ApiError(
                    422, "dify_inventory.intent_model_invalid",
                    "选择的意图推断模型不存在或未启用", "The selected intent inference model does not exist or is disabled",
                )
        if body.inventory_source == "console_api" and not _active_credential(db, target.target_id, "dify_console_api"):
            raise ApiError(
                409, "dify_inventory.console_credential_required",
                "Console API 自动采集需要 Dify Admin API Key", "Console API collection requires a Dify Admin API key",
            )
        if body.knowledge_content_authorized and not _active_credential(db, target.target_id, "dify_knowledge_api"):
            raise ApiError(
                409, "dify_inventory.knowledge_credential_required",
                "知识库内容采集需要独立知识库凭据", "Knowledge content collection requires a dedicated knowledge credential",
            )
        console_base_url = target_config["console_base_url"]
        allow_insecure = bool(target_config.get("allow_insecure_transport", False))
        target_ips = resolve_target_endpoint(
            console_base_url,
            allowed_cidrs=json_loads(target.allowed_cidrs_json, []),
            allow_insecure_transport=allow_insecure,
        )
        resolve_target_endpoint(
            console_base_url,
            allowed_cidrs=json_loads(policy.outbound_allowlist_json, []),
            allow_insecure_transport=allow_insecure,
        )
        target_config["console_resolved_ips"] = target_ips
    scan_options = {
        "language": body.language,
        "skills": body.skills,
        "prompt": body.prompt,
        "conversation_mode": body.conversation_mode,
        "reset_session": body.reset_session,
        "initial_session_id": continuation_state,
        "approval_id": body.approval_id,
        "datasets": body.datasets or (["JailBench-Tiny"] if body.scan_kind == "llm_redteam_scan" and not body.prompt else []),
        "num_prompts": body.num_prompts,
        "random_seed": body.random_seed,
        "techniques": body.techniques,
        "evaluation_model": body.evaluation_model,
        "http_authorized": body.http_authorized,
        "private_network_authorized": body.private_network_authorized,
        "scan_timeout_seconds": body.scan_timeout_seconds,
        "scan_concurrency": body.scan_concurrency,
        "inventory_source": body.inventory_source,
        "manual_dsl": body.manual_dsl,
        "include_prompt_text": body.include_prompt_text,
        "infer_agent_intent": body.infer_agent_intent,
        "intent_inference_model": body.intent_inference_model,
        "knowledge_content_authorized": body.knowledge_content_authorized,
        "max_knowledge_documents": body.max_knowledge_documents,
        "max_knowledge_segments": body.max_knowledge_segments,
        "max_knowledge_bytes": body.max_knowledge_bytes,
    }
    if body.scan_kind == "mcp_risk_scan":
        scan_options.update(
            {
                "metadata_only": True,
                "side_effect_tool_calls": "forbidden",
                "upstream_dynamic_mode": "disabled_by_policy",
            }
        )
    elif body.scan_kind == "dify_asset_inventory":
        scan_options.update({
            "metadata_only": True,
            "side_effect_tool_calls": "forbidden",
            "inventory_source": body.inventory_source,
        })
    return {
        "target": target,
        "policy": policy,
        "target_capabilities": target_capabilities,
        "policy_capabilities": policy_capabilities,
        "effective_capabilities": sorted(target_capabilities & policy_capabilities),
        "continuation_state": continuation_state,
        "scan_options": scan_options,
    }


def _build_scan_task_plan(
    db: Session,
    body: SecurityTaskPlanRequest,
    context: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    target: models.SecurityTarget = context["target"]
    policy: models.SecurityScanPolicy = context["policy"]
    approval, approved_credential = _production_active_safe_approval(
        db,
        target=target,
        policy=policy,
        approval_id=body.approval_id,
        now=now,
    )
    snapshot = _target_snapshot(db, target)
    policy_snapshot = _policy_snapshot(policy)
    effective_capabilities = context["effective_capabilities"]
    snapshot["effective_capabilities"] = effective_capabilities
    policy_snapshot["effective_capabilities"] = effective_capabilities
    if approval and approved_credential:
        production_controls = {
            "approval_id": approval.approval_id,
            "approved_by": approval.approved_by,
            "credential_id": approved_credential.credential_id,
            "credential_version": approved_credential.version,
            "dedicated_identity_ref": approval.dedicated_identity_ref,
            "maintenance_window_start": approval.maintenance_window_start.isoformat(),
            "maintenance_window_end": approval.maintenance_window_end.isoformat(),
        }
        snapshot["production_controls"] = production_controls
        policy_snapshot["production_controls"] = production_controls
    policy_allowlist = json_loads(policy.outbound_allowlist_json, [])
    if target.target_type != MCP_GATEWAY_TARGET_TYPE:
        _verify_target_snapshot_dns(snapshot, allowed_cidrs=snapshot["allowed_cidrs"])
        _verify_target_snapshot_dns(snapshot, allowed_cidrs=policy_allowlist)
    snapshot["policy_outbound_allowlist"] = policy_allowlist
    if body.scan_kind == "dify_asset_inventory":
        dify_config = validate_dify_inventory_target_config(snapshot.get("config", {}), require_complete=True)
        console_base_url = dify_config["console_base_url"]
        console_ips = resolve_target_endpoint(
            console_base_url,
            allowed_cidrs=snapshot["allowed_cidrs"],
            allow_insecure_transport=bool(snapshot.get("allow_insecure_transport", False)),
        )
        resolve_target_endpoint(
            console_base_url,
            allowed_cidrs=policy_allowlist,
            allow_insecure_transport=bool(snapshot.get("allow_insecure_transport", False)),
        )
        dify_config["console_resolved_ips"] = console_ips
        snapshot["config"] = dify_config
        snapshot["dify_mcp_servers"] = _dify_mcp_inventory_snapshot(db, dify_config.get("mcp_bindings", []))
        snapshot["dify_runtime_events"] = _dify_runtime_inventory_snapshot(
            db,
            app_id=dify_config["app_id"],
            owner_user_id=target.owner_user_id,
            owner_group_id=target.owner_group_id,
        )

    cases: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    limitations: list[str] = []
    tool_mode = "none"
    dify_mcp_binding_summary: dict[str, int] | None = None
    if body.scan_kind == "control_plane_validation":
        cases.append(
            {
                "case_key": "control_plane_validation",
                "category": "control_plane",
                "dynamic": False,
                "planned_rounds": 1,
            }
        )
        limitations.append("control_plane_only")
    elif body.scan_kind == "agent_risk_scan":
        selected_skills = list(body.skills or AGENT_SCAN_SKILLS)
        cases.append(
            {"case_key": "agent_info_collection", "category": "recon", "dynamic": True, "planned_rounds": None}
        )
        cases.extend(
            {
                "case_key": skill,
                "category": "agent_detection_skill",
                "dynamic": True,
                "planned_rounds": None,
            }
            for skill in selected_skills
        )
        cases.append(
            {"case_key": "agent_vulnerability_review", "category": "review", "dynamic": True, "planned_rounds": None}
        )
        tool_mode = "runtime_dynamic"
        tools.append(
            {
                "name": "dialogue",
                "source": "ai_infra_guard_agent_scan",
                "access_mode": "target_interaction",
                "will_call": True,
            }
        )
        limitations.extend(["runtime_generated_cases", "runtime_tool_inventory_unknown"])
    elif body.scan_kind == "mcp_risk_scan":
        tool_mode = "metadata_snapshot_only"
        for server in snapshot.get("mcp_assets", {}).get("servers", []):
            for tool in server.get("tools", []):
                exposed_name = tool.get("exposed_name") or f"{server.get('server_slug')}__{tool.get('name')}"
                cases.append(
                    {
                        "case_key": f"mcp_tool:{exposed_name}",
                        "category": "mcp_tool_metadata",
                        "dynamic": False,
                        "planned_rounds": 1,
                    }
                )
                tools.append(
                    {
                        "name": exposed_name,
                        "source": server.get("server_slug"),
                        "access_mode": tool.get("access_mode", "unknown"),
                        "risk_level": tool.get("risk_level", "low"),
                        "will_call": False,
                    }
                )
        limitations.append("metadata_only_no_tool_calls")
    elif body.scan_kind == "llm_redteam_scan":
        selected_datasets = body.datasets or (["JailBench-Tiny"] if not body.prompt else [])
        planned_count = body.num_prompts if selected_datasets else 1
        cases.extend(
            {
                "case_key": f"llm-attack:{index + 1}",
                "category": "llm_redteam_prompt",
                "dynamic": True,
                "planned_rounds": 1,
            }
            for index in range(planned_count)
        )
        tool_mode = "runtime_dynamic"
        tools.append(
            {
                "name": "chat_completions",
                "source": "ai_infra_guard_model_redteam",
                "access_mode": "target_interaction",
                "will_call": True,
            }
        )
        limitations.extend(["attack_resisted_is_prompt_scoped", "evaluator_required"])
    elif body.scan_kind == "ai_infrastructure_vulnerability_scan":
        endpoints = snapshot.get("config", {}).get("endpoints") or [snapshot.get("endpoint_url")]
        cases.extend(
            {
                "case_key": f"infra-endpoint:{index + 1}",
                "category": "ai_infrastructure_endpoint",
                "endpoint": endpoint,
                "dynamic": True,
                "planned_rounds": 1,
            }
            for index, endpoint in enumerate(endpoints)
        )
        tool_mode = "active_network_probe"
        tools.append(
            {
                "name": "ai_infrastructure_fingerprint_and_cve",
                "source": "ai_infra_guard",
                "access_mode": "network_egress",
                "will_call": True,
            }
        )
        limitations.extend(["explicit_urls_only", "unknown_version_is_unverified"])
    elif body.scan_kind == "dify_asset_inventory":
        dify_mcp_binding_summary = _dify_mcp_binding_options(db, target)["summary"]
        for key, category in (
            ("dify_console_api", "source_collection"),
            ("dsl", "asset_extraction"),
            ("dify_knowledge_api", "source_collection"),
            ("mcp_tools_list", "source_collection"),
            ("runtime_trace", "source_collection"),
            ("asset_risk_analysis", "risk_analysis"),
        ):
            cases.append({"case_key": f"dify-inventory:{key}", "category": category, "dynamic": False, "planned_rounds": 1})
        tool_mode = "metadata_collection"
        tools.extend([
            {"name": "dify_console_export", "source": "dify_console_api", "access_mode": "read_only", "will_call": body.inventory_source == "console_api"},
            {"name": "mcp_tools_list", "source": "platform_mcp_snapshot", "access_mode": "read_only", "will_call": False},
            {"name": "runtime_trace", "source": "platform_trace_snapshot", "access_mode": "read_only", "will_call": False},
        ])
        limitations.extend(["asset_inventory_not_complete_verification", "prompt_text_omitted_by_default"])

    budget = {
        "max_rounds": policy.max_rounds,
        "max_tokens": policy.max_tokens,
        "max_cost_microunits": policy.max_cost_microunits,
        "max_concurrent_requests": policy.max_concurrent_requests,
        "max_duration_seconds": policy.max_duration_seconds,
        "max_response_bytes": policy.max_response_bytes,
        "max_attempts": policy.max_retries + 1,
        "task_timeout_seconds": policy.task_timeout_seconds,
    }
    public_preview = {
        "schema_version": "scan-preview@1",
        "target": {
            "target_id": target.target_id,
            "name": target.name,
            "target_type": target.target_type,
            "environment": target.environment,
        },
        "policy": {
            "policy_id": policy.policy_id,
            "name": policy.name,
            "execution_mode": policy.execution_mode,
            "effective_capabilities": effective_capabilities,
        },
        "scan_kind": body.scan_kind,
        "cases": cases,
        "tool_plan": {
            "mode": tool_mode,
            "dynamic": tool_mode == "runtime_dynamic",
            "tools": tools,
            **({"dify_mcp_bindings": dify_mcp_binding_summary} if dify_mcp_binding_summary is not None else {}),
        },
        "budget": budget,
        "safety": {
            "approval_required": bool(target.environment == "production" and policy.execution_mode == "active_safe"),
            "approval_id": approval.approval_id if approval else None,
            "metadata_only": body.scan_kind == "mcp_risk_scan",
            "side_effect_tool_calls": "forbidden" if body.scan_kind == "mcp_risk_scan" else "policy_bounded",
        },
        "limitations": limitations,
    }
    public_preview["preview_fingerprint"] = request_fingerprint(
        {
            "target_snapshot": snapshot,
            "policy_snapshot": policy_snapshot,
            "scan_options": context["scan_options"],
            "scan_kind": body.scan_kind,
            "cases": cases,
            "tool_plan": public_preview["tool_plan"],
            "budget": budget,
        }
    )
    return {
        **public_preview,
        "_approval": approval,
        "_approved_credential": approved_credential,
        "_target_snapshot": snapshot,
        "_policy_snapshot": policy_snapshot,
    }


@router.post("/tasks/preview", response_model=SecurityTaskPreviewResponse)
async def preview_task(
    body: SecurityTaskPreviewRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    context = _validate_scan_task_request(db, body, current_user)
    plan = _build_scan_task_plan(db, body, context, now=datetime.utcnow())
    return SecurityTaskPreviewResponse(**{key: value for key, value in plan.items() if not key.startswith("_")})


@router.post("/tasks", response_model=SecurityTaskResponse)
async def create_task(
    body: SecurityTaskCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    context = _validate_scan_task_request(db, body, current_user)
    target: models.SecurityTarget = context["target"]
    policy: models.SecurityScanPolicy = context["policy"]
    scan_options = context["scan_options"]
    fingerprint = request_fingerprint(
        {
            "target_id": body.target_id,
            "policy_id": body.policy_id,
            "scan_kind": body.scan_kind,
            "scan_options": scan_options,
            "continue_from_task_id": body.continue_from_task_id,
        }
    )
    existing = (
        db.query(models.SecurityScanTask)
        .filter(
            models.SecurityScanTask.created_by == current_user.username,
            models.SecurityScanTask.idempotency_key == body.idempotency_key,
        )
        .first()
    )
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                409,
                "agent_security.idempotency_conflict",
                "幂等键已用于不同的扫描请求",
                "The idempotency key was already used for a different scan request",
                params={"idempotency_key": body.idempotency_key},
            )
        return _task_response(existing)

    now = datetime.utcnow()
    plan = _build_scan_task_plan(db, body, context, now=now)
    if body.preview_fingerprint and body.preview_fingerprint != plan["preview_fingerprint"]:
        raise ApiError(
            409,
            "agent_security.scan_preview_stale",
            "扫描配置已变化，请重新预览后再创建任务",
            "The scan configuration changed; preview it again before creating the task",
        )
    approval = plan["_approval"]
    snapshot = plan["_target_snapshot"]
    policy_snapshot = plan["_policy_snapshot"]
    effective_capabilities = context["effective_capabilities"]
    timeout_at = now + timedelta(seconds=policy.task_timeout_seconds)
    if approval:
        timeout_at = min(timeout_at, approval.maintenance_window_end)
    task_id = new_resource_id("asj")
    report_contract = build_report_contract(body.scan_kind)
    row = models.SecurityScanTask(
        task_id=task_id,
        target_id=target.target_id,
        policy_id=policy.policy_id,
        approval_id=approval.approval_id if approval else None,
        scan_kind=body.scan_kind,
        idempotency_key=body.idempotency_key,
        request_fingerprint=fingerprint,
        policy_snapshot_json=json_dumps(policy_snapshot),
        target_snapshot_json=json_dumps(snapshot),
        report_template_version=report_contract["report_template_version"],
        decision_criteria_version=report_contract["decision_criteria_version"],
        report_contract_json=json_dumps(report_contract),
        scan_options_encrypted=protect_secret(json_dumps(scan_options)),
        continued_from_task_id=body.continue_from_task_id,
        created_by=current_user.username,
        owner_user_id=target.owner_user_id,
        owner_group_id=target.owner_group_id,
        max_attempts=policy.max_retries + 1,
        next_attempt_at=now,
        timeout_at=timeout_at,
        created_at=now,
        updated_at=now,
    )
    if approval:
        consumed = db.query(models.SecurityScanApproval).filter(
            models.SecurityScanApproval.id == approval.id,
            models.SecurityScanApproval.status == "approved",
            models.SecurityScanApproval.maintenance_window_start <= now,
            models.SecurityScanApproval.maintenance_window_end > now,
        ).update(
            {
                "status": "used",
                "used_by": current_user.username,
                "used_task_id": task_id,
                "used_at": now,
            },
            synchronize_session=False,
        )
        if consumed != 1:
            db.rollback()
            raise ApiError(
                409,
                "agent_security.production_active_safe_approval_invalid",
                "生产主动安全扫描审批已被使用或已失效",
                "The production active-safe approval has already been used or expired",
            )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(models.SecurityScanTask)
            .filter(
                models.SecurityScanTask.created_by == current_user.username,
                models.SecurityScanTask.idempotency_key == body.idempotency_key,
            )
            .first()
        )
        if existing and existing.request_fingerprint == fingerprint:
            return _task_response(existing)
        raise ApiError(
            409,
            "agent_security.idempotency_conflict",
            "幂等键已用于不同的扫描请求",
            "The idempotency key was already used for a different scan request",
            params={"idempotency_key": body.idempotency_key},
        ) from None
    db.refresh(row)
    _audit(
        db,
        event_type="security_scan_task.created",
        actor=current_user.username,
        resource_type="security_scan_task",
        resource_id=row.task_id,
        action="create",
        details={
            "target_id": row.target_id,
            "policy_id": row.policy_id,
            "scan_kind": row.scan_kind,
            "environment": target.environment,
            "execution_mode": policy.execution_mode,
            "effective_capabilities": effective_capabilities,
            "approval_id": row.approval_id,
        },
    )
    return _task_response(row)


def _accessible_tasks_query(db: Session, user: models.User):
    query = db.query(models.SecurityScanTask)
    if user.role in SECURITY_READER_ROLES:
        return query
    group_ids = _group_ids(db, user.id)
    filters = [models.SecurityScanTask.owner_user_id == user.id]
    if group_ids:
        filters.append(models.SecurityScanTask.owner_group_id.in_(group_ids))
    return query.filter(or_(*filters))


@router.get("/tasks", response_model=list[SecurityTaskResponse])
async def list_tasks(
    status: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    scan_kind: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    recover_stale_tasks(db)
    query = _accessible_tasks_query(db, current_user)
    if status:
        if status not in {*TASK_ACTIVE_STATUSES, *TASK_TERMINAL_STATUSES}:
            raise ApiError(422, "agent_security.invalid_task_status", "扫描任务状态无效", "Invalid scan task status")
        query = query.filter(models.SecurityScanTask.status == status)
    if target_id:
        query = query.filter(models.SecurityScanTask.target_id == target_id)
    if scan_kind:
        query = query.filter(models.SecurityScanTask.scan_kind == scan_kind)
    return [
        _task_response(row)
        for row in query.order_by(models.SecurityScanTask.id.desc()).offset(offset).limit(limit).all()
    ]


_CASE_EXECUTION_STATUSES = {"completed", "error", "blocked", "unverified"}


def _case_execution_status(row: models.SecurityScanCase, response_summary: dict[str, Any]) -> str:
    explicit = response_summary.get("execution_status")
    if explicit in _CASE_EXECUTION_STATUSES:
        return str(explicit)
    return {
        "passed": "completed",
        "failed": "completed",
        "error": "error",
        "blocked": "blocked",
        "unverified": "unverified",
    }.get(row.status, "unverified")


def _case_assessment_status(
    row: models.SecurityScanCase,
    findings: list[models.SecurityFinding],
    execution_status: str,
) -> str:
    statuses = [item.status for item in findings]
    if "open" in statuses:
        return "risk_signal_detected"
    if statuses:
        if "accepted" in statuses:
            return "risk_accepted"
        if all(status == "resolved" for status in statuses):
            return "resolved"
        if all(status == "false_positive" for status in statuses):
            return "false_positive"
        # Mixed resolved/false-positive findings have no active risk signal.
        if all(status in {"resolved", "false_positive"} for status in statuses):
            return "resolved"
        return "unverified"
    if execution_status != "completed" or row.status == "failed":
        return "unverified"
    return "no_risk_observed"


def _case_payload(
    row: models.SecurityScanCase,
    *,
    findings: list[models.SecurityFinding] | None = None,
    scan_kind: str | None = None,
) -> dict[str, Any]:
    response_summary = json_loads(row.response_summary_json, {})
    related_findings = findings or []
    execution_status = _case_execution_status(row, response_summary)
    assessment_status = _case_assessment_status(row, related_findings, execution_status)
    scan_mode = response_summary.get("scan_mode")
    if not scan_mode and scan_kind == "mcp_risk_scan":
        scan_mode = "metadata_snapshot_only"
    tool_calls_performed = response_summary.get("tool_calls_performed")
    if tool_calls_performed is None and scan_kind == "mcp_risk_scan":
        tool_calls_performed = 0
    return {
        "case_id": row.case_id,
        "external_case_id": row.external_case_id,
        "category": row.category,
        "title": row.title,
        "status": row.status,
        "request_summary": json_loads(row.request_summary_json, {}),
        "response_summary": response_summary,
        "round_count": row.round_count,
        "execution_status": execution_status,
        "assessment_status": assessment_status,
        "finding_count": len(related_findings),
        "active_finding_count": sum(item.status == "open" for item in related_findings),
        "scan_mode": scan_mode,
        "tool_calls_performed": tool_calls_performed,
        "created_at": row.created_at,
    }


def _finding_payload(row: models.SecurityFinding) -> SecurityFindingResponse:
    evidence = json_loads(row.evidence_json, {})
    missing = []
    if not row.case_id:
        missing.append("case")
    if not row.trace_id or not row.event_id:
        missing.append("event")
    if not evidence:
        missing.append("evidence")
    if not row.decision_criteria_version:
        missing.append("decision_criteria")
    return SecurityFindingResponse(
        finding_id=row.finding_id,
        task_id=row.task_id,
        case_id=row.case_id,
        asset_id=row.asset_id,
        trace_id=row.trace_id,
        event_id=row.event_id,
        finding_code=row.finding_code,
        risk_codes=json_loads(row.risk_codes_json, []),
        risk_mapping=json_loads(row.risk_mapping_json, {}),
        decision_criteria_version=row.decision_criteria_version,
        severity=row.severity,
        status=row.status,
        title=row.title,
        description=row.description,
        evidence=evidence,
        source=row.source,
        confidence=row.confidence,
        fingerprint=row.fingerprint,
        traceability={
            "status": "incomplete" if missing else "complete",
            "case_id": row.case_id,
            "trace_id": row.trace_id,
            "event_id": row.event_id,
            "evidence_sha256": hash_value(json_dumps(evidence)) if evidence else None,
            "decision_criteria_version": row.decision_criteria_version,
            "missing": missing,
        },
        disposition_comment=row.disposition_comment,
        disposition_by=row.disposition_by,
        disposition_at=row.disposition_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_COMPARISON_POLICY_FIELDS = (
    "environment",
    "execution_mode",
    "allowed_capabilities",
    "outbound_allowlist",
    "max_rounds",
    "max_tokens",
    "max_cost_microunits",
    "max_concurrent_requests",
    "max_duration_seconds",
    "max_response_bytes",
)


def _comparison_coverage(task: models.SecurityScanTask) -> tuple[str, dict[str, Any]]:
    protected_options = unprotect_secret(task.scan_options_encrypted)
    options = json_loads(protected_options, {}) if protected_options else {}
    policy = json_loads(task.policy_snapshot_json, {})
    profile = {
        "scan_kind": task.scan_kind,
        "scan_options": {
            "language": options.get("language", "zh"),
            "skills": sorted(str(value) for value in options.get("skills", [])),
            "conversation_mode": options.get("conversation_mode", "single_turn"),
            "reset_session": bool(options.get("reset_session", True)),
            "prompt_sha256": hash_value(str(options.get("prompt") or "")),
            "metadata_only": bool(options.get("metadata_only", False)),
            "side_effect_tool_calls": options.get("side_effect_tool_calls"),
            "upstream_dynamic_mode": options.get("upstream_dynamic_mode"),
        },
        "policy": {field: policy.get(field) for field in _COMPARISON_POLICY_FIELDS},
    }
    return request_fingerprint(profile), profile


def _finding_comparison_key(
    row: models.SecurityFinding,
    cases_by_id: dict[str, models.SecurityScanCase],
) -> tuple[str, str]:
    case = cases_by_id.get(row.case_id or "")
    scope = (case.external_case_id or "") if case else ""
    return row.fingerprint, scope


def _group_comparison_findings(
    rows: list[models.SecurityFinding],
    cases_by_id: dict[str, models.SecurityScanCase],
) -> dict[tuple[str, str], list[models.SecurityFinding]]:
    grouped: dict[tuple[str, str], list[models.SecurityFinding]] = {}
    for row in sorted(rows, key=lambda item: (item.fingerprint, item.finding_id)):
        grouped.setdefault(_finding_comparison_key(row, cases_by_id), []).append(row)
    return grouped


def _validate_finding_trace_reference(
    db: Session,
    task: models.SecurityScanTask,
    *,
    trace_id: str | None,
    event_id: str | None,
) -> None:
    if trace_id is None and event_id is None:
        return
    trace = db.query(models.RuntimeTraceSession).filter(models.RuntimeTraceSession.trace_id == trace_id).first()
    event = (
        db.query(models.RuntimeTraceEvent)
        .filter(models.RuntimeTraceEvent.trace_id == trace_id, models.RuntimeTraceEvent.event_id == event_id)
        .first()
    )
    if not trace or not event:
        raise ApiError(
            422,
            "agent_security.finding_trace_reference_invalid",
            "Finding 关联的轨迹事件不存在",
            "The runtime trace event referenced by the finding does not exist",
        )
    if (
        trace.owner_user_id != task.owner_user_id
        or trace.owner_group_id != task.owner_group_id
    ):
        raise ApiError(
            403,
            "agent_security.finding_trace_scope_mismatch",
            "Finding 与轨迹事件的归属范围不一致",
            "The finding and runtime trace event do not share the same ownership scope",
        )


def _create_scan_finding_trace(
    db: Session,
    task: models.SecurityScanTask,
    rows: list[models.SecurityFinding],
    *,
    now: datetime,
) -> None:
    if not rows:
        return
    trace_id = f"trc_scan_{task.task_id}"
    tenant_id = str(task.owner_group_id) if task.owner_group_id is not None else f"user-{task.owner_user_id or 'system'}"
    trace = create_runtime_trace_session(
        db,
        trace_id=trace_id,
        tenant_id=tenant_id,
        agent_id=None,
        session_id=f"security-scan:{task.task_id}",
        owner_user_id=task.owner_user_id,
        owner_group_id=task.owner_group_id,
        created_by="security_worker",
        commit=False,
    )
    events = []
    for row in rows:
        event_id = new_resource_id("evt")
        row.trace_id = trace_id
        row.event_id = event_id
        evidence = json_loads(row.evidence_json, {})
        payload = {
            "task_id": task.task_id,
            "finding_id": row.finding_id,
            "case_id": row.case_id,
            "finding_code": row.finding_code,
            "evidence_sha256": hash_value(json_dumps(evidence)),
            "decision_criteria_version": row.decision_criteria_version,
            "report_template_version": task.report_template_version,
        }
        events.append(
            RuntimeTraceEventInput(
                event_id=event_id,
                event_time=now,
                source="security_worker",
                type="security.finding",
                status="observed",
                risk_codes=[row.finding_code],
                severity=row.severity,
                payload=payload,
                redacted_payload=payload,
            )
        )
    for batch_number, offset in enumerate(range(0, len(events), 1000), start=1):
        ingest_runtime_trace_batch(
            db,
            trace,
            RuntimeTraceBatchCreate(
                batch_id=f"bat_scan_{task.task_id}_{batch_number}",
                events=events[offset : offset + 1000],
            ),
            allowed_sources={"security_worker"},
            commit=False,
        )


def _artifact_payload(row: models.SecurityScanArtifact) -> dict[str, Any]:
    return {
        "artifact_id": row.artifact_id,
        "artifact_type": row.artifact_type,
        "uri": row.uri,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "redacted": row.redacted,
        "metadata": json_loads(row.metadata_json, {}),
        "content_available": bool(row.content_encrypted),
        "created_at": row.created_at,
    }


def _task_detail(db: Session, task: models.SecurityScanTask) -> dict[str, Any]:
    case_rows = (
        db.query(models.SecurityScanCase)
        .filter(models.SecurityScanCase.task_id == task.task_id)
        .order_by(models.SecurityScanCase.id)
        .all()
    )
    finding_rows = (
        db.query(models.SecurityFinding)
        .filter(models.SecurityFinding.task_id == task.task_id)
        .order_by(models.SecurityFinding.id)
        .all()
    )
    findings_by_case: dict[str, list[models.SecurityFinding]] = {}
    for finding in finding_rows:
        if finding.case_id:
            findings_by_case.setdefault(finding.case_id, []).append(finding)
    inventory_snapshot = db.query(models.SecurityAssetInventorySnapshot).filter(
        models.SecurityAssetInventorySnapshot.task_id == task.task_id
    ).first()
    return {
        "task": _task_response(task).model_dump(),
        "report_contract": _report_contract_snapshot(task),
        "cases": [
            _case_payload(
                row,
                findings=findings_by_case.get(row.case_id, []),
                scan_kind=task.scan_kind,
            )
            for row in case_rows
        ],
        "findings": [
            _finding_payload(row).model_dump()
            for row in finding_rows
        ],
        "artifacts": [
            _artifact_payload(row)
            for row in db.query(models.SecurityScanArtifact)
            .filter(models.SecurityScanArtifact.task_id == task.task_id)
            .order_by(models.SecurityScanArtifact.id)
            .all()
        ],
        "inventory": {
            "available": inventory_snapshot is not None,
            "snapshot_id": inventory_snapshot.snapshot_id if inventory_snapshot else None,
        },
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    recover_stale_tasks(db)
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    return _task_detail(db, task)


def _inventory_snapshot_or_404(db: Session, task_id: str) -> models.SecurityAssetInventorySnapshot:
    row = db.query(models.SecurityAssetInventorySnapshot).filter(
        models.SecurityAssetInventorySnapshot.task_id == task_id
    ).first()
    if not row:
        raise ApiError(
            404, "dify_inventory.snapshot_not_found",
            "Dify 资产清单快照不存在", "Dify asset inventory snapshot not found",
        )
    return row


@router.get("/tasks/{task_id}/inventory")
async def get_dify_inventory(
    task_id: str,
    asset_type: str | None = Query(default=None, max_length=64),
    source_type: str | None = Query(default=None, max_length=64),
    node_id: str | None = Query(default=None, max_length=256),
    verification_status: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    if task.scan_kind != "dify_asset_inventory":
        raise ApiError(409, "dify_inventory.task_kind_invalid", "该任务不是 Dify 资产清单", "This task is not a Dify inventory task")
    snapshot = _inventory_snapshot_or_404(db, task_id)
    payload = snapshot_payload(db, snapshot)
    items = payload["items"]
    if asset_type:
        items = [item for item in items if item["asset_type"] == asset_type]
    if verification_status:
        items = [item for item in items if item["verification_status"] == verification_status]
    if node_id:
        items = [item for item in items if str(item.get("details", {}).get("node_id") or "") == node_id]
    if source_type:
        items = [item for item in items if any(source.get("source_type") == source_type for source in item["sources"])]
    payload["items"] = items
    return payload


@router.get("/tasks/{task_id}/inventory/compare")
async def compare_dify_inventory(
    task_id: str,
    baseline_task_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    current = _inventory_snapshot_or_404(db, task_id)
    query = db.query(models.SecurityAssetInventorySnapshot).filter(
        models.SecurityAssetInventorySnapshot.target_id == current.target_id,
        models.SecurityAssetInventorySnapshot.id < current.id,
    )
    if baseline_task_id:
        query = query.filter(models.SecurityAssetInventorySnapshot.task_id == baseline_task_id)
    baseline = query.order_by(models.SecurityAssetInventorySnapshot.id.desc()).first()
    if not baseline:
        return {"status": "baseline_unavailable", "baseline_task_id": None, "added": [], "removed": [], "changed": []}
    current_items = {row.asset_id: row for row in db.query(models.SecurityAssetInventoryItem).filter(
        models.SecurityAssetInventoryItem.snapshot_id == current.snapshot_id
    ).all()}
    baseline_items = {row.asset_id: row for row in db.query(models.SecurityAssetInventoryItem).filter(
        models.SecurityAssetInventoryItem.snapshot_id == baseline.snapshot_id
    ).all()}
    added = sorted(set(current_items) - set(baseline_items))
    removed = sorted(set(baseline_items) - set(current_items))
    changed = sorted(asset_id for asset_id in set(current_items) & set(baseline_items) if current_items[asset_id].fingerprint != baseline_items[asset_id].fingerprint)
    return {
        "status": "completed", "baseline_task_id": baseline.task_id,
        "added": added, "removed": removed, "changed": changed,
        "summary": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }


@router.get("/tasks/{task_id}/inventory/items/{item_id}/content")
async def get_dify_inventory_sensitive_content(
    task_id: str,
    item_id: str,
    confirm: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    if not confirm:
        raise ApiError(
            409, "dify_inventory.prompt_confirmation_required",
            "查看 Prompt 原文需要明确确认", "Explicit confirmation is required to view raw Prompt text",
        )
    snapshot = _inventory_snapshot_or_404(db, task_id)
    item = db.query(models.SecurityAssetInventoryItem).filter(
        models.SecurityAssetInventoryItem.snapshot_id == snapshot.snapshot_id,
        models.SecurityAssetInventoryItem.item_id == item_id,
        models.SecurityAssetInventoryItem.asset_type == "prompt",
    ).first()
    content = unprotect_secret(item.sensitive_content_encrypted) if item else None
    if not item or content is None:
        raise ApiError(404, "dify_inventory.prompt_content_unavailable", "Prompt 原文未采集", "Raw Prompt text was not collected")
    _audit(
        db, event_type="dify_inventory.prompt_content_revealed", actor=current_user.username,
        resource_type="security_asset_inventory_item", resource_id=item.item_id, action="read",
        details={"task_id": task_id, "asset_id": item.asset_id},
    )
    return {"item_id": item.item_id, "asset_id": item.asset_id, "content": content}


@router.get("/tasks/{task_id}/mcp-assessment")
async def get_mcp_assessment(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    if task.scan_kind != "mcp_risk_scan":
        raise ApiError(
            409,
            "agent_security.mcp_assessment_unavailable",
            "该任务不是 MCP 风险扫描",
            "This task is not an MCP risk scan",
        )
    snapshot = json_loads(task.target_snapshot_json, {}).get("mcp_assets", {})
    assets = []
    for server in snapshot.get("servers", []):
        for tool in server.get("tools", []):
            assets.append(
                {
                    "gateway_id": snapshot.get("gateway_id"),
                    "gateway_slug": snapshot.get("gateway_slug"),
                    "server_id": server.get("server_id"),
                    "server_slug": server.get("server_slug"),
                    "tool_id": tool.get("tool_id"),
                    "tool_name": tool.get("name"),
                    "exposed_name": tool.get("exposed_name"),
                    "schema_hash": tool.get("schema_hash"),
                    "approved_schema_hash": tool.get("approved_schema_hash"),
                    "schema_changed": bool(
                        tool.get("schema_hash")
                        and tool.get("approved_schema_hash")
                        and tool.get("schema_hash") != tool.get("approved_schema_hash")
                    ),
                    "enabled": tool.get("enabled"),
                    "risk_level": tool.get("risk_level"),
                    "requires_approval": tool.get("requires_approval"),
                    "missing": bool(tool.get("missing")),
                }
            )
    findings = db.query(models.SecurityFinding).filter(models.SecurityFinding.task_id == task.task_id).all()
    recommendations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding in findings:
        evidence = json_loads(finding.evidence_json, {})
        for item in evidence.get("remediation", []):
            key = json_dumps(item)
            if key not in seen:
                seen.add(key)
                recommendations.append(item)
    return {
        "task_id": task.task_id,
        "status": task.status,
        "scan_mode": "metadata_snapshot_only",
        "side_effect_tool_calls": "forbidden",
        "automatic_policy_changes": False,
        "assets": assets,
        "findings": [_finding_payload(row).model_dump() for row in findings],
        "recommendations": recommendations,
    }


@router.post("/tasks/{task_id}/cancel", response_model=SecurityTaskResponse)
async def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    if current_user.role == "security_auditor":
        raise ApiError(403, "auth.permission_denied", "安全审计员没有取消权限", "Security auditors cannot cancel tasks")
    now = datetime.utcnow()
    if task.status == "pending":
        task.status = "cancelled"
        task.stop_reason = "cancelled_by_user"
        task.completed_at = now
    elif task.status == "running":
        task.cancel_requested = True
        task.stop_reason = "cancel_requested"
    elif task.status not in TASK_TERMINAL_STATUSES:
        raise ApiError(
            409, "agent_security.task_not_cancellable", "扫描任务当前无法取消", "The scan task cannot be cancelled"
        )
    task.updated_at = now
    db.commit()
    db.refresh(task)
    _audit(
        db,
        event_type="security_scan_task.cancelled",
        actor=current_user.username,
        resource_type="security_scan_task",
        resource_id=task.task_id,
        action="cancel",
        details={"status": task.status, "cancel_requested": task.cancel_requested},
    )
    return _task_response(task)


@router.post("/tasks/{task_id}/kill-switch", response_model=SecurityTaskResponse)
async def activate_task_kill_switch(
    task_id: str,
    body: SecurityTaskKillSwitchRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    task = _task_or_404(db, task_id)
    if task.kill_switch_activated:
        return _task_response(task)
    if task.status in TASK_TERMINAL_STATUSES:
        raise ApiError(
            409,
            "agent_security.kill_switch_task_terminal",
            "终止状态的扫描任务不能启用 Kill Switch",
            "The Kill Switch cannot be activated for a terminal scan task",
        )
    now = datetime.utcnow()
    previous_status = task.status
    task.kill_switch_activated = True
    task.kill_switch_activated_at = now
    task.kill_switch_activated_by = current_user.username
    task.kill_switch_reason = sanitize_untrusted_text(body.reason, max_length=1000).strip()
    task.cancel_requested = True
    if task.status == "pending":
        task.status = "cancelled"
        task.stop_reason = "kill_switch.activated_before_start"
        task.completed_at = now
    elif task.status == "running":
        task.stop_reason = "kill_switch.activated"
    else:
        raise ApiError(
            409,
            "agent_security.kill_switch_task_not_active",
            "扫描任务当前不能启用 Kill Switch",
            "The Kill Switch cannot be activated for the current scan task state",
        )
    task.updated_at = now
    db.commit()
    db.refresh(task)
    _audit(
        db,
        event_type="security_scan_task.kill_switch_activated",
        actor=current_user.username,
        resource_type="security_scan_task",
        resource_id=task.task_id,
        action="kill_switch",
        details={
            "previous_status": previous_status,
            "status": task.status,
            "stop_reason": task.stop_reason,
            "reason": task.kill_switch_reason,
        },
    )
    return _task_response(task)


@router.post("/tasks/{task_id}/export")
async def export_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    payload = _task_detail(db, task)
    _audit(
        db,
        event_type="security_scan_report.exported",
        actor=current_user.username,
        resource_type="security_scan_task",
        resource_id=task.task_id,
        action="export",
        details={"format": "json"},
    )
    return payload


@router.get("/tasks/{task_id}/findings", response_model=list[SecurityFindingResponse])
async def list_task_findings(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    rows = db.query(models.SecurityFinding).filter(models.SecurityFinding.task_id == task_id).all()
    return [_finding_payload(row) for row in rows]


@router.get("/findings/links", response_model=list[SecurityFindingResponse])
async def list_findings_for_trace_event(
    trace_id: str = Query(min_length=1, max_length=64),
    event_id: str = Query(min_length=1, max_length=64),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    rows = db.query(models.SecurityFinding).filter(
        models.SecurityFinding.trace_id == trace_id,
        models.SecurityFinding.event_id == event_id,
    ).all()
    visible: list[SecurityFindingResponse] = []
    for row in rows:
        task = _task_or_404(db, row.task_id)
        try:
            _require_task_access(db, current_user, task)
        except ApiError as error:
            if error.status_code == 403:
                continue
            raise
        visible.append(_finding_payload(row))
    return visible


@router.get("/findings/{finding_id}", response_model=SecurityFindingResponse)
async def get_finding(
    finding_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    row = db.query(models.SecurityFinding).filter(models.SecurityFinding.finding_id == finding_id).first()
    if not row:
        raise ApiError(404, "agent_security.finding_not_found", "安全发现不存在", "Security finding not found")
    task = _task_or_404(db, row.task_id)
    _require_task_access(db, current_user, task)
    return _finding_payload(row)


@router.patch("/findings/{finding_id}", response_model=SecurityFindingResponse)
async def dispose_finding(
    finding_id: str,
    body: SecurityFindingDisposition,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = db.query(models.SecurityFinding).filter(models.SecurityFinding.finding_id == finding_id).first()
    if not row:
        raise ApiError(404, "agent_security.finding_not_found", "安全发现不存在", "Security finding not found")
    task = _task_or_404(db, row.task_id)
    _require_task_access(db, current_user, task)
    now = datetime.utcnow()
    row.status = body.status
    row.disposition_comment = body.comment
    row.disposition_by = current_user.username
    row.disposition_at = now
    row.updated_at = now
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_finding.disposition_changed",
        actor=current_user.username,
        resource_type="security_finding",
        resource_id=row.finding_id,
        action="update_disposition",
        details={"status": row.status},
    )
    return _finding_payload(row)


@router.get(
    "/tasks/{task_id}/compare/{baseline_task_id}",
    response_model=SecurityTaskComparisonResponse,
)
async def compare_tasks(
    task_id: str,
    baseline_task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    current = _task_or_404(db, task_id)
    baseline = _task_or_404(db, baseline_task_id)
    _require_task_access(db, current_user, current)
    _require_task_access(db, current_user, baseline)
    if current.task_id == baseline.task_id:
        raise ApiError(
            409,
            "agent_security.comparison_same_task",
            "当前任务和基线任务不能相同",
            "The current task and baseline task must be different",
        )
    if current.target_id != baseline.target_id:
        raise ApiError(
            409,
            "agent_security.comparison_target_mismatch",
            "只能比较同一扫描目标的任务",
            "Only tasks for the same scan target can be compared",
        )
    if current.scan_kind != baseline.scan_kind:
        raise ApiError(
            409,
            "agent_security.comparison_scan_kind_mismatch",
            "只能比较同一扫描类型的任务",
            "Only tasks with the same scan type can be compared",
        )
    if current.created_at < baseline.created_at:
        raise ApiError(
            409,
            "agent_security.comparison_baseline_newer",
            "基线任务必须早于当前任务",
            "The baseline task must be older than the current task",
        )
    current_rows = db.query(models.SecurityFinding).filter(models.SecurityFinding.task_id == task_id).all()
    baseline_rows = db.query(models.SecurityFinding).filter(models.SecurityFinding.task_id == baseline_task_id).all()
    case_rows = (
        db.query(models.SecurityScanCase)
        .filter(models.SecurityScanCase.task_id.in_([task_id, baseline_task_id]))
        .all()
    )
    cases_by_id = {row.case_id: row for row in case_rows}
    current_groups = _group_comparison_findings(current_rows, cases_by_id)
    baseline_groups = _group_comparison_findings(baseline_rows, cases_by_id)
    new_rows: list[models.SecurityFinding] = []
    unchanged_rows: list[models.SecurityFinding] = []
    missing_baseline_rows: list[models.SecurityFinding] = []
    for key in sorted(set(current_groups) | set(baseline_groups)):
        current_group = current_groups.get(key, [])
        baseline_group = baseline_groups.get(key, [])
        shared_count = min(len(current_group), len(baseline_group))
        unchanged_rows.extend(current_group[:shared_count])
        new_rows.extend(current_group[shared_count:])
        missing_baseline_rows.extend(baseline_group[shared_count:])

    current_coverage, _ = _comparison_coverage(current)
    baseline_coverage, _ = _comparison_coverage(baseline)
    coverage_match = current_coverage == baseline_coverage
    engine_match = (current.engine_name or "", current.engine_version or "") == (
        baseline.engine_name or "",
        baseline.engine_version or "",
    )
    unable_reason: str | None = None
    if baseline.status != "succeeded":
        unable_reason = "baseline_not_succeeded"
    elif current.status != "succeeded":
        unable_reason = "current_not_succeeded"
    elif not coverage_match:
        unable_reason = "coverage_changed"
    elif not engine_match:
        unable_reason = "engine_changed"
    resolved_rows = [] if unable_reason else missing_baseline_rows
    unable_rows = missing_baseline_rows if unable_reason else []
    comparison_status = "partial" if unable_reason else "complete"
    result = {
        "schema_version": "security-scan-comparison@1",
        "task_id": task_id,
        "baseline_task_id": baseline_task_id,
        "comparison_status": comparison_status,
        "coverage_match": coverage_match,
        "coverage_fingerprint": current_coverage,
        "baseline_coverage_fingerprint": baseline_coverage,
        "engine_match": engine_match,
        "new": [_finding_payload(row).model_dump() for row in new_rows],
        "unchanged": [_finding_payload(row).model_dump() for row in unchanged_rows],
        "resolved": [_finding_payload(row).model_dump() for row in resolved_rows],
        "unable_to_retest": [
            {"finding": _finding_payload(row).model_dump(), "reason_code": unable_reason}
            for row in unable_rows
        ],
        "summary": {
            "new": len(new_rows),
            "unchanged": len(unchanged_rows),
            "resolved": len(resolved_rows),
            "unable_to_retest": len(unable_rows),
        },
        "limitations": [
            "absence_is_resolved_only_when_successful_coverage_and_engine_match",
            "dynamic_agent_prompts_may_not_reproduce_identical_runtime_paths",
        ],
    }
    return SecurityTaskComparisonResponse.model_validate(result)


@router.get("/tasks/{task_id}/artifacts/{artifact_id}/content")
async def get_artifact_content(
    task_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_reader),
):
    task = _task_or_404(db, task_id)
    _require_task_access(db, current_user, task)
    row = (
        db.query(models.SecurityScanArtifact)
        .filter(
            models.SecurityScanArtifact.task_id == task_id,
            models.SecurityScanArtifact.artifact_id == artifact_id,
        )
        .first()
    )
    if not row or not row.content_encrypted:
        raise ApiError(
            404,
            "agent_security.artifact_content_not_found",
            "扫描产物原始内容不存在",
            "The raw scan artifact content is not available",
        )
    content = unprotect_secret(row.content_encrypted)
    if content is None:
        raise ApiError(
            503,
            "agent_security.artifact_decryption_failed",
            "扫描产物无法解密",
            "The scan artifact could not be decrypted",
        )
    _audit(
        db,
        event_type="security_scan_artifact.raw_viewed",
        actor=current_user.username,
        resource_type="security_scan_artifact",
        resource_id=row.artifact_id,
        action="view_raw",
    )
    return JSONResponse(
        content={
            "artifact_id": row.artifact_id,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
            "content": content,
        }
    )


@router.post("/workers", response_model=SecurityWorkerResponse)
async def create_worker(
    body: SecurityWorkerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    if db.query(models.SecurityScanWorker).filter(models.SecurityScanWorker.name == body.name).first():
        raise ApiError(409, "agent_security.worker_name_conflict", "Worker 名称已存在", "Worker name already exists")
    plain = f"amsw_{secrets.token_urlsafe(32)}"
    row = models.SecurityScanWorker(
        worker_id=new_resource_id("asw"),
        name=body.name,
        token_hash=hash_value(plain),
        token_prefix=plain[:12],
        capabilities_json=json_dumps(list(dict.fromkeys(body.capabilities))),
        max_concurrency=body.max_concurrency,
        created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(
        db,
        event_type="security_scan_worker.created",
        actor=current_user.username,
        resource_type="security_scan_worker",
        resource_id=row.worker_id,
        action="create",
    )
    return _worker_response(row, token_once=plain)


@router.get("/workers", response_model=list[SecurityWorkerResponse])
async def list_workers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_reader),
):
    return [
        _worker_response(row)
        for row in db.query(models.SecurityScanWorker).order_by(models.SecurityScanWorker.id).all()
    ]


@router.post("/workers/{worker_id}/revoke", response_model=SecurityWorkerResponse)
async def revoke_worker(
    worker_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    row = db.query(models.SecurityScanWorker).filter(models.SecurityScanWorker.worker_id == worker_id).first()
    if not row:
        raise ApiError(404, "agent_security.worker_not_found", "扫描 Worker 不存在", "Scan worker not found")
    if row.status == "active":
        row.status = "revoked"
        row.revoked_at = datetime.utcnow()
        row.revoked_by = current_user.username
        db.commit()
        db.refresh(row)
        _audit(
            db,
            event_type="security_scan_worker.revoked",
            actor=current_user.username,
            resource_type="security_scan_worker",
            resource_id=row.worker_id,
            action="revoke",
        )
    return _worker_response(row)


async def resolve_security_worker(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> models.SecurityScanWorker:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "agent_security.worker_token_missing", "缺少 Worker Token", "Worker token is missing")
    plain = authorization.split(" ", 1)[1].strip()
    row = db.query(models.SecurityScanWorker).filter(models.SecurityScanWorker.token_hash == hash_value(plain)).first()
    if not row or row.status != "active":
        raise ApiError(
            401,
            "agent_security.worker_token_invalid",
            "Worker Token 无效或已吊销",
            "Worker token is invalid or revoked",
        )
    return row


@router.post("/worker/key", response_model=SecurityWorkerKeyResponse)
async def register_worker_key(
    body: SecurityWorkerKeyRegister,
    db: Session = Depends(get_db),
    worker: models.SecurityScanWorker = Depends(resolve_security_worker),
):
    public_key, fingerprint = validate_worker_public_key(body.public_key)
    now = datetime.utcnow()
    worker.public_key_algorithm = body.algorithm
    worker.public_key = public_key
    worker.public_key_fingerprint = fingerprint
    worker.public_key_registered_at = now
    worker.last_heartbeat_at = now
    db.commit()
    _audit(
        db,
        event_type="security_scan_worker.key_registered",
        actor=f"worker:{worker.worker_id}",
        resource_type="security_scan_worker",
        resource_id=worker.worker_id,
        action="register_key",
        details={"fingerprint": fingerprint, "algorithm": body.algorithm},
    )
    return SecurityWorkerKeyResponse(
        worker_id=worker.worker_id,
        algorithm=body.algorithm,
        public_key_fingerprint=fingerprint,
        registered_at=now,
    )


def _verify_lease(task: models.SecurityScanTask, worker: models.SecurityScanWorker, lease_token: str) -> None:
    if task.worker_id != worker.worker_id or task.status != "running":
        raise ApiError(
            409,
            "agent_security.task_lease_not_owned",
            "Worker 未持有该任务租约",
            "The worker does not own this task lease",
        )
    if not task.lease_token_hash or not secrets.compare_digest(task.lease_token_hash, hash_value(lease_token)):
        raise ApiError(401, "agent_security.task_lease_invalid", "任务租约令牌无效", "Task lease token is invalid")
    now = datetime.utcnow()
    if (
        task.lease_expires_at
        and task.lease_expires_at < now
        and (not task.timeout_at or task.timeout_at > now)
    ):
        raise ApiError(409, "agent_security.task_lease_expired", "任务租约已过期", "Task lease has expired")


def _usage_values(usage: SecurityTaskUsage) -> dict[str, int]:
    return {
        "rounds_used": usage.rounds,
        "tokens_used": usage.tokens,
        "cost_microunits_used": usage.cost_microunits,
        "max_concurrency_seen": usage.concurrent_requests,
        "response_bytes_used": usage.response_bytes,
    }


def _apply_usage(task: models.SecurityScanTask, usage: SecurityTaskUsage) -> None:
    incoming = _usage_values(usage)
    for field, value in incoming.items():
        if value < getattr(task, field):
            raise ApiError(
                409,
                "agent_security.usage_not_monotonic",
                "Worker 上报的预算用量不能减少",
                "Worker budget usage must be monotonic",
                params={"field": field},
            )
        setattr(task, field, value)


def _task_usage(task: models.SecurityScanTask) -> SecurityTaskUsage:
    return SecurityTaskUsage(
        rounds=task.rounds_used,
        tokens=task.tokens_used,
        cost_microunits=task.cost_microunits_used,
        concurrent_requests=task.max_concurrency_seen,
        response_bytes=task.response_bytes_used,
    )


def _budget_reason(task: models.SecurityScanTask, now: datetime) -> str | None:
    if task.timeout_at and task.timeout_at <= now:
        return "task_timeout"
    policy = json_loads(task.policy_snapshot_json, {})
    request_entry_checks = (
        ("max_rounds", task.rounds_used),
        ("max_concurrent_requests", task.max_concurrency_seen),
    )
    for name, actual in request_entry_checks:
        if actual > int(policy.get(name, 0)):
            return f"budget.{name}_exceeded"
    cumulative_checks = (
        ("max_tokens", task.tokens_used),
        ("max_cost_microunits", task.cost_microunits_used),
        ("max_response_bytes", task.response_bytes_used),
    )
    for name, actual in cumulative_checks:
        limit = int(policy.get(name, 0))
        if actual > 0 and actual >= limit:
            return f"budget.{name}_exceeded"
    if task.started_at and (now - task.started_at).total_seconds() >= int(policy.get("max_duration_seconds", 0)):
        return "budget.max_duration_seconds_exceeded"
    return None


def _validate_worker_result_contract(
    task: models.SecurityScanTask,
    body: SecurityWorkerCompleteRequest,
) -> None:
    if body.status != "succeeded":
        return
    contract = _WORKER_RESULT_CONTRACTS.get(task.scan_kind)
    if not contract:
        return
    artifact_types = {item.artifact_type for item in body.artifacts}
    if (
        body.engine_name != contract["engine_name"]
        or not (body.engine_version or "").startswith(contract["version_prefix"])
        or not body.cases
        or contract["artifact_type"] not in artifact_types
    ):
        raise ApiError(
            422,
            "agent_security.worker_result_contract_invalid",
            "Worker 成功结果不符合当前扫描引擎契约",
            "The successful Worker result does not match the current scan engine contract",
            params={
                "scan_kind": task.scan_kind,
                "expected_engine": contract["engine_name"],
                "expected_artifact_type": contract["artifact_type"],
            },
        )


def _clear_lease(task: models.SecurityScanTask) -> None:
    task.worker_id = None
    task.lease_token_hash = None
    task.lease_expires_at = None


def recover_stale_tasks(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    current = now or datetime.utcnow()
    timed_out = 0
    retried = 0
    failed = 0
    kill_switch_cancelled = False
    pending = (
        db.query(models.SecurityScanTask)
        .filter(
            models.SecurityScanTask.status == "pending",
            or_(
                models.SecurityScanTask.cancel_requested.is_(True),
                models.SecurityScanTask.timeout_at <= current,
            ),
        )
        .all()
    )
    for task in pending:
        if task.cancel_requested:
            task.status = "cancelled"
            task.stop_reason = "cancel_requested"
            kill_switch_cancelled = True
        elif task.timeout_at <= current:
            task.status = "timed_out"
            task.stop_reason = "task_timeout"
            timed_out += 1
        else:
            continue
        task.completed_at = current
        task.updated_at = current
    expired = (
        db.query(models.SecurityScanTask)
        .filter(
            models.SecurityScanTask.status == "running",
            models.SecurityScanTask.lease_expires_at.is_not(None),
            models.SecurityScanTask.lease_expires_at <= current,
        )
        .all()
    )
    for task in expired:
        if task.kill_switch_activated:
            task.status = "cancelled"
            task.stop_reason = "kill_switch.activated"
            task.completed_at = current
            kill_switch_cancelled = True
        elif task.cancel_requested:
            task.status = "cancelled"
            task.stop_reason = "cancel_requested"
            task.completed_at = current
            kill_switch_cancelled = True
        elif task.timeout_at <= current:
            task.status = "timed_out"
            task.stop_reason = "task_timeout"
            task.completed_at = current
            timed_out += 1
        elif task.attempt < task.max_attempts:
            policy = json_loads(task.policy_snapshot_json, {})
            task.status = "pending"
            task.stop_reason = "lease_expired_retry"
            task.next_attempt_at = current + timedelta(seconds=int(policy.get("retry_backoff_seconds", 0)))
            retried += 1
        else:
            task.status = "failed"
            task.stop_reason = "lease_expired_attempts_exhausted"
            if not task.error_code:
                task.error_code = "agent_security.worker_lease_lost"
            task.completed_at = current
            failed += 1
        task.updated_at = current
        _clear_lease(task)
    if timed_out or retried or failed or kill_switch_cancelled:
        db.commit()
    return {"timed_out": timed_out, "retried": retried, "failed": failed}


@router.post("/workers/recover")
async def recover_workers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_security_admin),
):
    result = recover_stale_tasks(db)
    _audit(
        db,
        event_type="security_scan_task.recovered",
        actor=current_user.username,
        resource_type="security_scan_task",
        resource_id="stale",
        action="recover",
        details=result,
    )
    return result


@router.post("/worker/heartbeat")
async def worker_heartbeat(
    db: Session = Depends(get_db),
    worker: models.SecurityScanWorker = Depends(resolve_security_worker),
):
    worker.last_heartbeat_at = datetime.utcnow()
    db.commit()
    return {"worker_id": worker.worker_id, "status": "active", "server_time": worker.last_heartbeat_at}


@router.post("/worker/claim", response_model=SecurityWorkerClaimResponse)
async def claim_task(
    body: SecurityWorkerClaimRequest,
    db: Session = Depends(get_db),
    worker: models.SecurityScanWorker = Depends(resolve_security_worker),
):
    now = datetime.utcnow()
    recover_stale_tasks(db, now=now)
    running = (
        db.query(models.SecurityScanTask)
        .filter(models.SecurityScanTask.worker_id == worker.worker_id, models.SecurityScanTask.status == "running")
        .count()
    )
    worker.last_heartbeat_at = now
    if running >= worker.max_concurrency:
        db.commit()
        return SecurityWorkerClaimResponse(task=None)
    registered = set(json_loads(worker.capabilities_json, []))
    requested = set(body.capabilities) if body.capabilities else registered
    capabilities = sorted(registered & requested)
    if not capabilities:
        db.commit()
        return SecurityWorkerClaimResponse(task=None)
    candidates = (
        db.query(models.SecurityScanTask)
        .filter(
            models.SecurityScanTask.status == "pending",
            models.SecurityScanTask.cancel_requested.is_(False),
            models.SecurityScanTask.kill_switch_activated.is_(False),
            models.SecurityScanTask.scan_kind.in_(capabilities),
            or_(models.SecurityScanTask.next_attempt_at.is_(None), models.SecurityScanTask.next_attempt_at <= now),
        )
        .order_by(models.SecurityScanTask.created_at.asc())
        .limit(10)
        .all()
    )
    for candidate in candidates:
        target = _target_or_404(db, candidate.target_id)
        snapshot = json_loads(candidate.target_snapshot_json, {})
        if target.status != "active":
            candidate.status = "blocked"
            candidate.stop_reason = "target_disabled"
            candidate.completed_at = now
            candidate.updated_at = now
            db.commit()
            continue
        if target.target_type != MCP_GATEWAY_TARGET_TYPE:
            try:
                _verify_target_snapshot_dns(snapshot, allowed_cidrs=snapshot.get("allowed_cidrs", []))
                _verify_target_snapshot_dns(snapshot, allowed_cidrs=snapshot.get("policy_outbound_allowlist", []))
            except ApiError as exc:
                candidate.status = "blocked"
                candidate.stop_reason = "dns_rebinding_detected"
                candidate.error_code = exc.code
                candidate.error_message = exc.zh_message
                candidate.completed_at = now
                candidate.updated_at = now
                db.commit()
                continue
        policy = json_loads(candidate.policy_snapshot_json, {})
        protected_options = unprotect_secret(candidate.scan_options_encrypted)
        worker_scan_options = json_loads(protected_options, {}) if protected_options else {}
        lease_seconds = int(policy.get("lease_seconds", 60))
        credential_purposes: list[str] = []
        if candidate.scan_kind == "dify_asset_inventory":
            if worker_scan_options.get("inventory_source", "console_api") == "console_api":
                credential_purposes.append("dify_console_api")
            if _active_credential(db, target.target_id, "dify_knowledge_api"):
                credential_purposes.append("dify_knowledge_api")
        elif candidate.scan_kind in {"agent_risk_scan", "llm_redteam_scan", "ai_infrastructure_vulnerability_scan"}:
            credential_purposes.append("dify_app_api" if target.connector_type == "dify" else "agent_runtime")
        credentials = [
            item for purpose in credential_purposes
            if (item := _active_credential(db, target.target_id, purpose)) is not None
        ]
        credential = credentials[0] if credentials else _active_credential(db, target.target_id)
        required_purposes: list[str] = []
        if candidate.scan_kind == "dify_asset_inventory":
            if worker_scan_options.get("inventory_source", "console_api") == "console_api":
                required_purposes.append("dify_console_api")
            if worker_scan_options.get("knowledge_content_authorized"):
                required_purposes.append("dify_knowledge_api")
        missing_purposes = [
            purpose for purpose in required_purposes
            if not _active_credential(db, target.target_id, purpose)
        ]
        if candidate.scan_kind == "dify_asset_inventory" and missing_purposes:
            candidate.status = "blocked"
            candidate.stop_reason = "required_credential_unavailable"
            candidate.error_code = (
                "dify_inventory.knowledge_credential_required"
                if missing_purposes[0] == "dify_knowledge_api"
                else "dify_inventory.console_credential_required"
            )
            candidate.error_message = "Dify 资产采集所需凭据已轮换、吊销或禁用"
            candidate.completed_at = now
            candidate.updated_at = now
            db.commit()
            continue
        production_controls = snapshot.get("production_controls") or {}
        if production_controls and (
            not credential
            or credential.credential_id != production_controls.get("credential_id")
            or credential.version != production_controls.get("credential_version")
        ):
            candidate.status = "blocked"
            candidate.stop_reason = "dedicated_credential_changed"
            candidate.error_code = "agent_security.production_dedicated_credential_changed"
            candidate.error_message = "生产扫描专用凭据已轮换或失效"
            candidate.completed_at = now
            candidate.updated_at = now
            db.commit()
            continue
        if credentials and not worker.public_key:
            raise ApiError(
                409,
                "agent_security.worker_public_key_required",
                "Agent 扫描 Worker 必须先注册临时凭据加密公钥",
                "Agent scan workers must register a credential-encryption public key before claiming tasks",
            )
        lease_plain = secrets.token_urlsafe(32)
        running_count = (
            select(func.count(models.SecurityScanTask.id))
            .where(
                models.SecurityScanTask.worker_id == worker.worker_id,
                models.SecurityScanTask.status == "running",
            )
            .scalar_subquery()
        )
        updated = (
            db.query(models.SecurityScanTask)
            .filter(
                models.SecurityScanTask.id == candidate.id,
                models.SecurityScanTask.status == "pending",
                models.SecurityScanTask.cancel_requested.is_(False),
                models.SecurityScanTask.kill_switch_activated.is_(False),
                running_count < worker.max_concurrency,
            )
            .update(
                {
                    "status": "running",
                    "worker_id": worker.worker_id,
                    "lease_token_hash": hash_value(lease_plain),
                    "lease_expires_at": min(now + timedelta(seconds=lease_seconds), candidate.timeout_at),
                    "heartbeat_at": now,
                    "attempt": candidate.attempt + 1,
                    "started_at": candidate.started_at or now,
                    "updated_at": now,
                    "stop_reason": None,
                },
                synchronize_session=False,
            )
        )
        if not updated:
            db.rollback()
            continue
        db.commit()
        claimed = _task_or_404(db, candidate.task_id)
        credential_payload: dict[str, Any] = {
            "configured": credential is not None,
            "credential_id": credential.credential_id if credential else None,
            "credential_type": credential.credential_type if credential else None,
            "purpose": credential.purpose if credential else None,
            "secret_masked": credential.secret_masked if credential else None,
            "secret_delivery": "not_available_in_p1" if candidate.scan_kind == "control_plane_validation" else "none",
        }
        credential_payloads: list[dict[str, Any]] = []
        for selected_credential in credentials:
            secret = unprotect_secret(selected_credential.secret_encrypted)
            if not secret:
                claimed.status = "blocked"
                claimed.stop_reason = "credential_decryption_failed"
                claimed.error_code = "agent_security.credential_decryption_failed"
                claimed.completed_at = now
                _clear_lease(claimed)
                db.commit()
                raise ApiError(
                    409,
                    "agent_security.credential_decryption_failed",
                    "目标凭据无法解密，任务已阻止",
                    "The target credential could not be decrypted and the task was blocked",
                )
            item_payload = {
                "configured": True,
                "credential_id": selected_credential.credential_id,
                "credential_type": selected_credential.credential_type,
                "purpose": selected_credential.purpose,
                "secret_masked": selected_credential.secret_masked,
                "secret_delivery": "sealed_envelope",
                "secret_envelope": seal_secret_for_worker(
                secret,
                worker.public_key,
                worker_id=worker.worker_id,
                task_id=claimed.task_id,
                credential_id=selected_credential.credential_id,
                expires_at=claimed.lease_expires_at,
                ),
            }
            credential_payloads.append(item_payload)
        if credential_payloads:
            credential_payload = credential_payloads[0]
        upstream_session = unprotect_secret(claimed.session_state_encrypted)
        if upstream_session and candidate.scan_kind in {
            "llm_redteam_scan",
            "ai_infrastructure_vulnerability_scan",
        }:
            worker_scan_options["upstream_session_id"] = upstream_session
        return SecurityWorkerClaimResponse(
            task=_task_response(claimed),
            lease_token=lease_plain,
            lease_seconds=lease_seconds,
            target=snapshot,
            policy=policy,
            credential=credential_payload,
            credentials=credential_payloads,
            scan_options=worker_scan_options,
        )
    db.commit()
    return SecurityWorkerClaimResponse(task=None)


@router.post("/worker/tasks/{task_id}/heartbeat", response_model=SecurityWorkerHeartbeatResponse)
async def task_heartbeat(
    task_id: str,
    body: SecurityWorkerHeartbeatRequest,
    db: Session = Depends(get_db),
    worker: models.SecurityScanWorker = Depends(resolve_security_worker),
):
    task = _task_or_404(db, task_id)
    _verify_lease(task, worker, body.lease_token)
    now = datetime.utcnow()
    _apply_usage(task, body.usage)
    if body.session_state:
        task.session_state_encrypted = protect_secret(body.session_state)
    if task.kill_switch_activated:
        task.status = "cancelled"
        task.stop_reason = "kill_switch.activated"
        task.completed_at = now
        _clear_lease(task)
        task.updated_at = now
        db.commit()
        return SecurityWorkerHeartbeatResponse(continue_allowed=False, status=task.status, stop_reason=task.stop_reason)
    if task.cancel_requested:
        task.status = "cancelled"
        task.stop_reason = "cancel_requested"
        task.completed_at = now
        _clear_lease(task)
        task.updated_at = now
        db.commit()
        return SecurityWorkerHeartbeatResponse(continue_allowed=False, status=task.status, stop_reason=task.stop_reason)
    reason = _budget_reason(task, now)
    if reason:
        task.status = "timed_out" if reason == "task_timeout" else "blocked"
        task.stop_reason = reason
        task.completed_at = now
        _clear_lease(task)
        task.updated_at = now
        db.commit()
        return SecurityWorkerHeartbeatResponse(continue_allowed=False, status=task.status, stop_reason=reason)
    policy = json_loads(task.policy_snapshot_json, {})
    task.heartbeat_at = now
    lease_expires_at = now + timedelta(seconds=int(policy.get("lease_seconds", 60)))
    task.lease_expires_at = min(lease_expires_at, task.timeout_at)
    task.updated_at = now
    worker.last_heartbeat_at = now
    db.commit()
    return SecurityWorkerHeartbeatResponse(
        continue_allowed=True,
        status=task.status,
        lease_expires_at=task.lease_expires_at,
    )


@router.post("/worker/tasks/{task_id}/infer-intent", response_model=SecurityIntentInferenceResponse)
async def infer_dify_agent_intent(
    task_id: str,
    body: SecurityIntentInferenceRequest,
    db: Session = Depends(get_db),
    worker: models.SecurityScanWorker = Depends(resolve_security_worker),
):
    task = _task_or_404(db, task_id)
    _verify_lease(task, worker, body.lease_token)
    if task.scan_kind != "dify_asset_inventory":
        raise ApiError(
            409, "dify_inventory.intent_inference_task_invalid",
            "只有 Dify 资产清单任务可以推断智能体意图",
            "Only Dify asset inventory tasks can infer agent intent",
        )
    protected_options = unprotect_secret(task.scan_options_encrypted)
    options = json_loads(protected_options, {}) if protected_options else {}
    if not options.get("infer_agent_intent"):
        raise ApiError(
            403, "dify_inventory.intent_inference_not_authorized",
            "当前任务未授权智能体意图推断",
            "Agent intent inference was not authorized for this task",
        )

    now = datetime.utcnow()
    _apply_usage(task, body.usage)
    reason = _budget_reason(task, now)
    if task.kill_switch_activated or task.cancel_requested or reason:
        stop_reason = (
            "kill_switch.activated" if task.kill_switch_activated
            else "cancel_requested" if task.cancel_requested
            else reason
        )
        task.status = (
            "cancelled"
            if task.kill_switch_activated or task.cancel_requested
            else "timed_out" if reason == "task_timeout" else "blocked"
        )
        task.stop_reason = stop_reason
        task.completed_at = now
        task.updated_at = now
        _clear_lease(task)
        db.commit()
        return SecurityIntentInferenceResponse(
            status="unavailable",
            error_code="dify_inventory.intent_inference_stopped",
            collected_at=now,
            usage=_task_usage(task),
            continue_allowed=False,
            stop_reason=stop_reason,
        )

    policy = json_loads(task.policy_snapshot_json, {})
    task.heartbeat_at = now
    task.lease_expires_at = min(now + timedelta(seconds=int(policy.get("lease_seconds", 60))), task.timeout_at)
    task.updated_at = now
    worker.last_heartbeat_at = now
    db.commit()

    inference = await run_intent_inference(
        db,
        requested_model=options.get("intent_inference_model"),
        summary=body.summary,
        owner_user_id=task.owner_user_id,
        owner_group_id=task.owner_group_id,
    )

    db.expire_all()
    task = _task_or_404(db, task_id)
    _verify_lease(task, worker, body.lease_token)
    usage_delta = inference.get("usage_delta") if isinstance(inference.get("usage_delta"), dict) else {}
    current_usage = _task_usage(task)
    accumulated_usage = SecurityTaskUsage(
        rounds=current_usage.rounds + max(0, int(usage_delta.get("rounds") or 0)),
        tokens=current_usage.tokens + max(0, int(usage_delta.get("tokens") or 0)),
        cost_microunits=current_usage.cost_microunits + max(0, int(usage_delta.get("cost_microunits") or 0)),
        concurrent_requests=max(current_usage.concurrent_requests, body.usage.concurrent_requests),
        response_bytes=current_usage.response_bytes + max(0, int(usage_delta.get("response_bytes") or 0)),
    )
    _apply_usage(task, accumulated_usage)
    completed_at = datetime.utcnow()
    reason = _budget_reason(task, completed_at)
    continue_allowed = reason is None and not task.kill_switch_activated and not task.cancel_requested
    stop_reason = reason
    if not continue_allowed:
        if task.kill_switch_activated:
            task.status = "cancelled"
            stop_reason = "kill_switch.activated"
        elif task.cancel_requested:
            task.status = "cancelled"
            stop_reason = "cancel_requested"
        else:
            task.status = "timed_out" if reason == "task_timeout" else "blocked"
        task.stop_reason = stop_reason
        task.completed_at = completed_at
        _clear_lease(task)
        inference = {
            "status": "unavailable",
            "error_code": "dify_inventory.intent_inference_stopped",
            "model": inference.get("model"),
            "provider": inference.get("provider"),
        }
    else:
        task.heartbeat_at = completed_at
        task.lease_expires_at = min(
            completed_at + timedelta(seconds=int(policy.get("lease_seconds", 60))), task.timeout_at
        )
    task.updated_at = completed_at
    worker.last_heartbeat_at = completed_at
    db.commit()
    _audit(
        db,
        event_type="security_scan_task.intent_inferred",
        actor=f"worker:{worker.worker_id}",
        resource_type="security_scan_task",
        resource_id=task.task_id,
        action="infer_intent",
        details={
            "status": inference.get("status"),
            "model": inference.get("model"),
            "provider": inference.get("provider"),
            "error_code": inference.get("error_code"),
            "diagnostic_code": inference.get("diagnostic_code"),
            "usage": accumulated_usage.model_dump(),
        },
    )
    return SecurityIntentInferenceResponse(
        status=inference.get("status", "unavailable"),
        intent=inference.get("intent"),
        confidence=inference.get("confidence"),
        evidence_summary=inference.get("evidence_summary") or [],
        model=inference.get("model"),
        provider=inference.get("provider"),
        rule_version=inference.get("rule_version") or "intent-inference@1",
        error_code=inference.get("error_code"),
        diagnostic_code=inference.get("diagnostic_code"),
        collected_at=completed_at,
        usage=accumulated_usage,
        continue_allowed=continue_allowed,
        stop_reason=stop_reason,
    )


@router.post("/worker/tasks/{task_id}/complete", response_model=SecurityTaskResponse)
async def complete_task(
    task_id: str,
    body: SecurityWorkerCompleteRequest,
    db: Session = Depends(get_db),
    worker: models.SecurityScanWorker = Depends(resolve_security_worker),
):
    task = _task_or_404(db, task_id)
    _verify_lease(task, worker, body.lease_token)
    now = datetime.utcnow()
    auto_trace_findings: list[models.SecurityFinding] = []
    inventory_report: dict[str, Any] | None = None
    _apply_usage(task, body.usage)
    if task.kill_switch_activated:
        task.status = "cancelled"
        task.stop_reason = "kill_switch.activated"
        task.completed_at = now
        _clear_lease(task)
        task.updated_at = now
        worker.last_heartbeat_at = now
        db.commit()
        db.refresh(task)
        _audit(
            db,
            event_type="security_scan_task.kill_switch_stopped",
            actor=f"worker:{worker.worker_id}",
            resource_type="security_scan_task",
            resource_id=task.task_id,
            action="complete",
            details={"status": task.status, "stop_reason": task.stop_reason},
        )
        return _task_response(task)
    if task.cancel_requested:
        task.status = "cancelled"
        task.stop_reason = "cancel_requested"
        task.completed_at = now
        _clear_lease(task)
        task.updated_at = now
        worker.last_heartbeat_at = now
        db.commit()
        db.refresh(task)
        _audit(
            db,
            event_type="security_scan_task.cancelled",
            actor=f"worker:{worker.worker_id}",
            resource_type="security_scan_task",
            resource_id=task.task_id,
            action="complete",
            details={"status": task.status, "stop_reason": task.stop_reason},
        )
        return _task_response(task)
    _validate_worker_result_contract(task, body)
    budget_reason = _budget_reason(task, now)
    if budget_reason:
        task.status = "timed_out" if budget_reason == "task_timeout" else "blocked"
        task.stop_reason = budget_reason
        task.completed_at = now
    elif body.status == "failed" and body.retryable and task.attempt < task.max_attempts:
        policy = json_loads(task.policy_snapshot_json, {})
        task.status = "pending"
        task.stop_reason = "worker_requested_retry"
        task.error_code = body.error_code or "agent_security.worker_retryable_failure"
        task.error_message = body.error_message
        task.next_attempt_at = now + timedelta(seconds=int(policy.get("retry_backoff_seconds", 0)))
    else:
        task.status = body.status
        task.stop_reason = None if body.status == "succeeded" else "worker_reported_failure"
        task.error_code = body.error_code
        task.error_message = body.error_message
        task.completed_at = now
        task.engine_name = body.engine_name
        task.engine_version = body.engine_version
        task.session_state_encrypted = protect_secret(body.session_state) if body.session_state else None
        case_ids: dict[str, str] = {}
        for item in body.cases:
            case_id = new_resource_id("ascase")
            if item.external_case_id:
                case_ids[item.external_case_id] = case_id
            db.add(
                models.SecurityScanCase(
                    case_id=case_id,
                    task_id=task.task_id,
                    external_case_id=item.external_case_id,
                    category=sanitize_untrusted_text(item.category, max_length=128),
                    title=sanitize_untrusted_text(item.title, max_length=512),
                    status=item.status,
                    request_summary_json=json_dumps(sanitize_untrusted_value(item.request_summary)),
                    response_summary_json=json_dumps(sanitize_untrusted_value(item.response_summary)),
                    round_count=item.round_count,
                )
            )
        for item in body.findings:
            if not item.case_external_id:
                raise ApiError(
                    422,
                    "agent_security.finding_case_reference_required",
                    "Finding 必须关联本次扫描用例",
                    "A finding must reference a case from this scan",
                )
            case_id = case_ids.get(item.case_external_id)
            if not case_id:
                raise ApiError(
                    422,
                    "agent_security.finding_case_reference_invalid",
                    "Finding 关联的扫描用例不存在",
                    "The scan case referenced by the finding does not exist",
                )
            safe_evidence = sanitize_untrusted_value(item.evidence)
            if not safe_evidence:
                raise ApiError(
                    422,
                    "agent_security.finding_evidence_required",
                    "Finding 必须包含可审计证据",
                    "A finding must contain auditable evidence",
                )
            if not task.decision_criteria_version:
                raise ApiError(
                    422,
                    "agent_security.finding_decision_criteria_required",
                    "Finding 缺少冻结的判定口径版本",
                    "A finding requires a frozen decision-criteria version",
                )
            _validate_finding_trace_reference(
                db,
                task,
                trace_id=item.trace_id,
                event_id=item.event_id,
            )
            safe_title = sanitize_untrusted_text(item.title, max_length=512)
            fingerprint = request_fingerprint(
                {"finding_code": item.finding_code, "title": safe_title.strip(), "source": item.source}
            )
            risk_mapping = map_risk_codes([item.finding_code])
            finding = models.SecurityFinding(
                finding_id=new_resource_id("asf"),
                task_id=task.task_id,
                case_id=case_id,
                asset_id=sanitize_untrusted_text(item.asset_id, max_length=512) if item.asset_id else None,
                trace_id=item.trace_id,
                event_id=item.event_id,
                finding_code=item.finding_code,
                risk_codes_json=json_dumps(risk_mapping["risk_codes"]),
                risk_mapping_json=json_dumps(risk_mapping),
                decision_criteria_version=task.decision_criteria_version,
                severity=item.severity,
                status=item.status,
                title=safe_title,
                description=sanitize_untrusted_text(item.description),
                evidence_json=json_dumps(safe_evidence),
                source=item.source,
                confidence=item.confidence,
                fingerprint=fingerprint,
                created_at=now,
                updated_at=now,
            )
            db.add(finding)
            if item.trace_id is None:
                auto_trace_findings.append(finding)
        for item in body.artifacts:
            content_encrypted = None
            stored_sha256 = item.sha256
            stored_size_bytes = item.size_bytes
            stored_redacted = item.redacted
            stored_metadata = sanitize_untrusted_value(item.metadata)
            if item.content is not None:
                content_bytes = item.content.encode("utf-8")
                if hash_value(item.content) != item.sha256 or len(content_bytes) != item.size_bytes:
                    raise ApiError(
                        422,
                        "agent_security.artifact_integrity_mismatch",
                        "扫描产物的哈希或大小校验失败",
                        "The scan artifact hash or size does not match its content",
                    )
                if task.scan_kind == "dify_asset_inventory" and item.artifact_type == "dify-asset-inventory":
                    try:
                        inventory_report = validate_inventory_report(json_loads(item.content, None))
                    except (TypeError, ValueError) as exc:
                        raise ApiError(
                            422, "dify_inventory.response_invalid",
                            "Dify 资产清单产物无法解析", "The Dify asset inventory artifact cannot be parsed",
                        ) from exc
                    projected_content = json_dumps(inventory_artifact_projection(inventory_report))
                    content_encrypted = protect_secret(projected_content)
                    stored_sha256 = hash_value(projected_content)
                    stored_size_bytes = len(projected_content.encode("utf-8"))
                    stored_redacted = True
                    stored_metadata = {
                        **stored_metadata,
                        "prompt_text_included": False,
                        "prompt_text_stored_separately": bool(item.metadata.get("prompt_text_included")),
                    }
                else:
                    content_encrypted = protect_secret(item.content)
            db.add(
                models.SecurityScanArtifact(
                    artifact_id=new_resource_id("asa"),
                    task_id=task.task_id,
                    artifact_type=item.artifact_type,
                    uri=item.uri,
                    sha256=stored_sha256,
                    size_bytes=stored_size_bytes,
                    redacted=stored_redacted,
                    metadata_json=json_dumps(stored_metadata),
                    content_encrypted=content_encrypted,
                    created_at=now,
                )
            )
        if task.scan_kind == "dify_asset_inventory" and body.status == "succeeded":
            if inventory_report is None:
                raise ApiError(
                    422, "dify_inventory.response_invalid",
                    "Dify 资产清单任务缺少可持久化产物", "The Dify inventory task has no persistable artifact",
                )
            persist_inventory_snapshot(db, task, inventory_report)
    _clear_lease(task)
    task.updated_at = now
    worker.last_heartbeat_at = now
    if auto_trace_findings:
        with runtime_trace_transaction(db):
            _create_scan_finding_trace(db, task, auto_trace_findings, now=now)
    else:
        db.commit()
    db.refresh(task)
    _audit(
        db,
        event_type="security_scan_task.completed"
        if task.status in {"succeeded", "failed"}
        else "security_scan_task.updated",
        actor=f"worker:{worker.worker_id}",
        resource_type="security_scan_task",
        resource_id=task.task_id,
        action="complete",
        details={"status": task.status, "attempt": task.attempt, "stop_reason": task.stop_reason},
    )
    return _task_response(task)
