from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, load_only

from agent_manager.core.runtime_trace_pdf import build_runtime_trace_pdf

from .. import auth, iam, models
from ..api_errors import ApiError
from ..feature_flags import require_runtime_trace
from ..runtime_trace_schemas import (
    RUNTIME_TRACE_SCHEMA_VERSION,
    RuntimeTraceBatchCreate,
    RuntimeTraceCreate,
    RuntimeTraceExportCreate,
    RuntimeTraceRawExportAuthorizationCreate,
)
from ..security_audit import append_security_audit
from ..security_scan_controls import protect_secret, unprotect_secret
from ..services import gateway_sessions
from ..services.runtime_traces import cleanup_expired, create_trace, ingest_batch, metrics_snapshot
from ..sqlite_db import get_db
from .access_tokens import (
    acquire_access_token_slot,
    release_access_token_slot,
    resolve_access_token,
)

router = APIRouter(
    prefix="/v1/runtime-traces",
    tags=["runtime-traces"],
    dependencies=[Depends(require_runtime_trace)],
)
MAX_RUNTIME_TRACE_EXPORT_EVENTS = 20_000
MAX_RUNTIME_TRACE_EXPORT_PAYLOAD_BYTES = 64 * 1024 * 1024
MAX_RUNTIME_TRACE_PDF_EVENTS = 5_000
RAW_EXPORT_AUTHORIZATION_TTL_MINUTES = 5
RUNTIME_TRACE_ERROR_STATUSES = ("error", "failed", "timed_out")


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _trace_dict(row: models.RuntimeTraceSession) -> dict[str, Any]:
    return {
        "trace_id": row.trace_id,
        "schema_version": row.schema_version,
        "tenant_id": row.tenant_id,
        "agent_id": row.agent_id,
        "session_id": row.session_id,
        "status": row.status,
        "completeness": row.completeness,
        "event_count": row.event_count,
        "risk_level": row.risk_level,
        "risk_codes": _loads(row.risk_codes_json, []),
        "risk_mapping_version": row.risk_mapping_version,
        "first_event_at": row.first_event_at,
        "last_event_at": row.last_event_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "expires_at": row.expires_at,
    }


def _event_dict(row: models.RuntimeTraceEvent, payload: models.RuntimeTracePayload | None = None) -> dict[str, Any]:
    return {
        "schema_version": row.schema_version,
        "event_id": row.event_id,
        "trace_id": row.trace_id,
        "seq": row.seq,
        "event_time": row.event_time,
        "received_at": row.received_at,
        "tenant_id": row.tenant_id,
        "agent_id": row.agent_id,
        "session_id": row.session_id,
        "turn_id": row.turn_id,
        "step_id": row.step_id,
        "source": row.source,
        "type": row.type,
        "request_id": row.request_id,
        "call_id": row.call_id,
        "parent_call_id": row.parent_call_id,
        "status": row.status,
        "tool_name": row.tool_name,
        "duration_ms": row.duration_ms,
        "risk_codes": _loads(row.risk_codes_json, []),
        "risk_mapping": _loads(row.risk_mapping_json, {}),
        "payload_ref": row.payload_id,
        "payload": _loads(payload.redacted_json, {}) if payload else None,
    }


async def _writer_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> AsyncIterator[models.AccessToken]:
    token = resolve_access_token(
        db,
        authorization,
        required_scope="runtime:trace",
        request=request,
        allowed_token_types={"agent_runtime"},
    )
    raw_body = await request.body()
    if len(raw_body) > token.max_body_kb * 1024:
        raise ApiError(
            413,
            "runtime_trace.body_too_large",
            "轨迹请求体超过凭证限制",
            "The runtime trace request body exceeds the credential limit",
            params={"max_body_kb": token.max_body_kb},
        )
    acquire_access_token_slot(token)
    try:
        yield token
    finally:
        release_access_token_slot(token)


def _require_trace(db: Session, trace_id: str) -> models.RuntimeTraceSession:
    row = db.query(models.RuntimeTraceSession).filter(
        models.RuntimeTraceSession.trace_id == trace_id,
        models.RuntimeTraceSession.expires_at > datetime.utcnow(),
    ).first()
    if not row:
        raise ApiError(404, "runtime_trace.not_found", "调用轨迹不存在", "Runtime trace not found")
    return row


def _group_ids(db: Session, user_id: int) -> set[int]:
    return {
        int(row[0])
        for row in db.query(models.UserGroupMember.group_id)
        .filter(models.UserGroupMember.user_id == user_id)
        .all()
    }


def _ensure_read_allowed(db: Session, row: models.RuntimeTraceSession, user: models.User) -> None:
    if user.role in {"admin", "super_admin", "security_auditor", "privacy_auditor"}:
        return
    if row.owner_user_id == user.id or (row.owner_group_id and row.owner_group_id in _group_ids(db, user.id)):
        return
    raise ApiError(403, "runtime_trace.read_forbidden", "无权查看该调用轨迹", "Not allowed to view this runtime trace")


def _ensure_raw_allowed(db: Session, user: models.User) -> None:
    if user.role not in {"admin", "super_admin", "privacy_auditor"}:
        raise ApiError(
            403,
            "runtime_trace.raw_payload_forbidden",
            "当前角色无权查看原始轨迹内容",
            "The current role cannot view raw trace payloads",
        )

    iam.check(db, user, "traces:raw")


def _consume_raw_export_authorization(
    db: Session,
    *,
    trace_id: str,
    user: models.User,
    raw_token: str | None,
) -> None:
    if not raw_token:
        raise ApiError(
            403,
            "runtime_trace.raw_export_authorization_required",
            "原始轨迹导出需要二次授权",
            "Raw trace export requires secondary authorization",
        )
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.utcnow()
    updated = (
        db.query(models.RuntimeTraceRawExportAuthorization)
        .filter(
            models.RuntimeTraceRawExportAuthorization.token_hash == token_hash,
            models.RuntimeTraceRawExportAuthorization.trace_id == trace_id,
            models.RuntimeTraceRawExportAuthorization.user_id == user.id,
            models.RuntimeTraceRawExportAuthorization.expires_at > now,
            models.RuntimeTraceRawExportAuthorization.used_at.is_(None),
        )
        .update({"used_at": now}, synchronize_session=False)
    )
    if updated != 1:
        raise ApiError(
            403,
            "runtime_trace.raw_export_authorization_invalid",
            "原始轨迹导出授权无效、已使用或已过期",
            "The raw trace export authorization is invalid, used, or expired",
        )


@router.post("")
def create_runtime_trace(
    body: RuntimeTraceCreate,
    token: models.AccessToken = Depends(_writer_token),
    db: Session = Depends(get_db),
):
    if body.schema_version != RUNTIME_TRACE_SCHEMA_VERSION:
        raise ApiError(
            422,
            "runtime_trace.schema_version_unsupported",
            "不支持的轨迹 Schema 版本",
            "Unsupported runtime trace schema version",
            params={"expected": RUNTIME_TRACE_SCHEMA_VERSION, "actual": body.schema_version},
        )
    tenant_id = str(token.group_id) if token.group_id is not None else body.tenant_id
    row = create_trace(
        db,
        tenant_id=tenant_id,
        agent_id=token.bound_agent_id,
        session_id=body.session_id,
        owner_user_id=token.user_id,
        owner_group_id=token.group_id,
        created_by=token.name,
        retention_days=body.retention_days,
    )
    return _trace_dict(row)


@router.post("/{trace_id}/events:batch")
def ingest_runtime_trace_events(
    trace_id: str,
    body: RuntimeTraceBatchCreate,
    token: models.AccessToken = Depends(_writer_token),
    db: Session = Depends(get_db),
):
    row = _require_trace(db, trace_id)
    if row.agent_id != token.bound_agent_id:
        raise ApiError(
            403,
            "runtime_trace.agent_binding_mismatch",
            "轨迹与凭证绑定的智能体不匹配",
            "The trace does not match the Agent bound to the credential",
        )
    if row.owner_group_id is not None and row.owner_group_id != token.group_id:
        raise ApiError(403, "runtime_trace.tenant_mismatch", "轨迹租户不匹配", "Runtime trace tenant mismatch")
    if row.owner_group_id is None and row.owner_user_id is not None and row.owner_user_id != token.user_id:
        raise ApiError(403, "runtime_trace.owner_mismatch", "轨迹所属用户不匹配", "Runtime trace owner mismatch")
    return ingest_batch(
        db,
        row,
        body,
        expected_agent_id=token.bound_agent_id,
        allowed_sources={"agent_sdk", "knowledge_connector"},
    )


@router.get("")
def list_runtime_traces(
    session_id: str | None = Query(default=None, min_length=1, max_length=128),
    agent_id: str | None = Query(default=None, min_length=1, max_length=128),
    turn_id: str | None = Query(default=None, min_length=1, max_length=128),
    risk_level: str | None = Query(default=None, min_length=1, max_length=16),
    request_id: str | None = Query(default=None, min_length=1, max_length=128),
    tool_name: str | None = Query(default=None, min_length=1, max_length=256),
    has_error: bool = False,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    query = db.query(models.RuntimeTraceSession).filter(models.RuntimeTraceSession.expires_at > datetime.utcnow())
    if user.role not in {"admin", "super_admin", "security_auditor", "privacy_auditor"}:
        groups = _group_ids(db, user.id)
        query = query.filter(
            or_(
                models.RuntimeTraceSession.owner_user_id == user.id,
                models.RuntimeTraceSession.owner_group_id.in_(groups or {-1}),
            )
        )
    if session_id:
        query = query.filter(models.RuntimeTraceSession.session_id == session_id)
    if agent_id:
        query = query.filter(models.RuntimeTraceSession.agent_id == agent_id)
    if risk_level:
        query = query.filter(models.RuntimeTraceSession.risk_level == risk_level)
    if created_from:
        normalized_from = (
            created_from.astimezone(timezone.utc).replace(tzinfo=None)
            if created_from.tzinfo is not None
            else created_from
        )
        query = query.filter(models.RuntimeTraceSession.created_at >= normalized_from)
    if created_to:
        normalized_to = (
            created_to.astimezone(timezone.utc).replace(tzinfo=None)
            if created_to.tzinfo is not None
            else created_to
        )
        query = query.filter(models.RuntimeTraceSession.created_at <= normalized_to)
    if request_id:
        request_traces = db.query(models.RuntimeTraceEvent.trace_id).filter(
            models.RuntimeTraceEvent.request_id == request_id
        )
        query = query.filter(models.RuntimeTraceSession.trace_id.in_(request_traces))
    if tool_name:
        tool_traces = db.query(models.RuntimeTraceEvent.trace_id).filter(
            models.RuntimeTraceEvent.tool_name == tool_name
        )
        query = query.filter(models.RuntimeTraceSession.trace_id.in_(tool_traces))
    if turn_id:
        turn_traces = db.query(models.RuntimeTraceEvent.trace_id).filter(
            models.RuntimeTraceEvent.turn_id == turn_id
        )
        query = query.filter(models.RuntimeTraceSession.trace_id.in_(turn_traces))
    if has_error:
        error_traces = db.query(models.RuntimeTraceEvent.trace_id).filter(
            or_(
                models.RuntimeTraceEvent.type.like("%.error"),
                models.RuntimeTraceEvent.status.in_(RUNTIME_TRACE_ERROR_STATUSES),
            )
        )
        query = query.filter(models.RuntimeTraceSession.trace_id.in_(error_traces))
    total = query.count()
    rows = query.order_by(models.RuntimeTraceSession.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    associations = gateway_sessions.summaries(db, [row.trace_id for row in rows])
    return {"items": [{**_trace_dict(row), "aggregation": associations.get(row.trace_id),
                       "status": associations.get(row.trace_id, {}).get("status", row.status)} for row in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/metrics")
def runtime_trace_metrics(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_security_reader),
):
    return metrics_snapshot(db)


@router.post("/maintenance/cleanup")
def cleanup_runtime_traces(
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_current_admin_user),
):
    return cleanup_expired(db)


@router.get("/exports/{export_id}/download")
def download_runtime_trace_export(
    export_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    row = db.query(models.RuntimeTraceExport).filter(models.RuntimeTraceExport.export_id == export_id).first()
    if not row or row.expires_at <= datetime.utcnow():
        raise ApiError(404, "runtime_trace.export_not_found", "轨迹导出不存在或已过期", "Trace export not found or expired")
    trace = _require_trace(db, row.trace_id)
    _ensure_read_allowed(db, trace, user)
    if row.redaction_level == "raw":
        _ensure_raw_allowed(db, user)
    protected_content = unprotect_secret(row.content_encrypted)
    if protected_content is None:
        raise ApiError(500, "runtime_trace.export_decrypt_failed", "轨迹导出解密失败", "Failed to decrypt trace export")
    if row.format == "pdf":
        try:
            content = base64.b64decode(protected_content, validate=True)
        except (ValueError, TypeError):
            raise ApiError(500, "runtime_trace.export_decode_failed", "轨迹 PDF 解码失败", "Failed to decode trace PDF export")
        media_type = "application/pdf"
        suffix = "pdf"
    else:
        content = protected_content.encode("utf-8")
        media_type = "application/json"
        suffix = "json"
    row.downloaded_at = datetime.utcnow()
    db.commit()
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{export_id}.{suffix}"'},
    )


@router.get("/{trace_id}")
def get_runtime_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    row = _require_trace(db, trace_id)
    _ensure_read_allowed(db, row, user)
    aggregation = gateway_sessions.summaries(db, [trace_id]).get(trace_id)
    return {**_trace_dict(row), "aggregation": aggregation,
            "status": aggregation["status"] if aggregation else row.status}


@router.get("/{trace_id}/requests")
def list_gateway_session_requests(
    trace_id: str,
    after_index: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    row = _require_trace(db, trace_id)
    _ensure_read_allowed(db, row, user)
    requests = db.query(models.GatewaySessionRequest).filter(
        models.GatewaySessionRequest.trace_id == trace_id,
        models.GatewaySessionRequest.request_index > after_index,
    ).order_by(models.GatewaySessionRequest.request_index).limit(limit + 1).all()
    return {"items": [{"request_id": item.request_id, "request_index": item.request_index,
                       "status": item.status, "match_reason": item.match_reason,
                       "matched_request_id": item.matched_request_id,
                       "matched_message_count": item.matched_message_count,
                       "message_count": item.message_count, "created_at": item.created_at,
                       "completed_at": item.completed_at} for item in requests[:limit]],
            "has_more": len(requests) > limit}


@router.get("/{trace_id}/events")
def list_runtime_trace_events(
    trace_id: str,
    event_id: str | None = Query(default=None, min_length=1, max_length=64),
    event_type: str | None = Query(default=None, min_length=1, max_length=64),
    turn_id: str | None = Query(default=None, min_length=1, max_length=128),
    tool_name: str | None = Query(default=None, min_length=1, max_length=256),
    request_id: str | None = Query(default=None, min_length=1, max_length=128),
    errors_only: bool = False,
    after_seq: int | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    trace = _require_trace(db, trace_id)
    _ensure_read_allowed(db, trace, user)
    query = db.query(models.RuntimeTraceEvent).filter(models.RuntimeTraceEvent.trace_id == trace_id)
    if event_id:
        query = query.filter(models.RuntimeTraceEvent.event_id == event_id)
    if event_type:
        query = query.filter(models.RuntimeTraceEvent.type == event_type)
    if turn_id:
        query = query.filter(models.RuntimeTraceEvent.turn_id == turn_id)
    if tool_name:
        query = query.filter(models.RuntimeTraceEvent.tool_name == tool_name)
    if request_id:
        query = query.filter(models.RuntimeTraceEvent.request_id == request_id)
    if errors_only:
        query = query.filter(
            or_(
                models.RuntimeTraceEvent.type.like("%.error"),
                models.RuntimeTraceEvent.status.in_(RUNTIME_TRACE_ERROR_STATUSES),
            )
        )
    total = query.count()
    if after_seq is not None:
        ordered = query.filter(models.RuntimeTraceEvent.seq > after_seq).order_by(models.RuntimeTraceEvent.seq.asc())
        window = ordered.limit(page_size + 1).all()
        has_more = len(window) > page_size
        rows = window[:page_size]
    else:
        ordered = query.order_by(models.RuntimeTraceEvent.seq.asc())
        rows = ordered.offset((page - 1) * page_size).limit(page_size).all()
        has_more = page * page_size < total
    payloads = {
        row.payload_id: row
        for row in db.query(models.RuntimeTracePayload)
        .options(load_only(models.RuntimeTracePayload.payload_id, models.RuntimeTracePayload.redacted_json))
        .filter(models.RuntimeTracePayload.payload_id.in_([event.payload_id for event in rows if event.payload_id]))
        .all()
    }
    return {
        "items": [_event_dict(row, payloads.get(row.payload_id)) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "next_after_seq": rows[-1].seq if rows and has_more else None,
    }


@router.get("/{trace_id}/events/{event_id}/raw-payload")
def get_runtime_trace_raw_payload(
    trace_id: str,
    event_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    trace = _require_trace(db, trace_id)
    _ensure_read_allowed(db, trace, user)
    _ensure_raw_allowed(db, user)
    payload = (
        db.query(models.RuntimeTracePayload)
        .filter(models.RuntimeTracePayload.trace_id == trace_id, models.RuntimeTracePayload.event_id == event_id)
        .first()
    )
    if not payload:
        raise ApiError(404, "runtime_trace.payload_not_found", "轨迹 Payload 不存在", "Trace payload not found")
    raw = unprotect_secret(payload.raw_payload_encrypted)
    if raw is None:
        raise ApiError(500, "runtime_trace.payload_decrypt_failed", "轨迹 Payload 解密失败", "Failed to decrypt trace payload")
    append_security_audit(
        event_type="runtime_trace.raw_payload_viewed",
        actor=user.username,
        resource_type="runtime_trace_event",
        resource_id=f"{trace_id}:{event_id}",
        action="read",
        outcome="success",
        details={"trace_id": trace_id, "event_id": event_id},
        bind=db.get_bind(),
    )
    return {"trace_id": trace_id, "event_id": event_id, "payload": _loads(raw, {})}


@router.post("/{trace_id}/exports")
def create_runtime_trace_export(
    trace_id: str,
    body: RuntimeTraceExportCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    trace = _require_trace(db, trace_id)
    _ensure_read_allowed(db, trace, user)
    if body.redaction_level == "raw":
        _ensure_raw_allowed(db, user)
        if body.format != "json":
            raise ApiError(
                422,
                "runtime_trace.raw_pdf_not_supported",
                "原始轨迹仅允许导出 JSON",
                "Raw runtime traces can only be exported as JSON",
            )
        if not body.acknowledge_sensitive_content:
            raise ApiError(
                422,
                "runtime_trace.raw_export_acknowledgement_required",
                "请确认原始轨迹可能包含敏感信息",
                "Acknowledge that the raw trace may contain sensitive information",
            )
        _consume_raw_export_authorization(
            db,
            trace_id=trace_id,
            user=user,
            raw_token=body.raw_authorization_token,
        )
    payload_bytes = int(
        db.query(func.coalesce(func.sum(models.RuntimeTracePayload.size_bytes), 0))
        .filter(models.RuntimeTracePayload.trace_id == trace_id)
        .scalar()
        or 0
    )
    if trace.event_count > MAX_RUNTIME_TRACE_EXPORT_EVENTS or payload_bytes > MAX_RUNTIME_TRACE_EXPORT_PAYLOAD_BYTES:
        raise ApiError(
            413,
            "runtime_trace.export_too_large",
            "轨迹过大，不能同步导出",
            "The runtime trace is too large for synchronous export",
            params={
                "max_events": MAX_RUNTIME_TRACE_EXPORT_EVENTS,
                "max_payload_bytes": MAX_RUNTIME_TRACE_EXPORT_PAYLOAD_BYTES,
            },
        )
    if body.format == "pdf" and trace.event_count > MAX_RUNTIME_TRACE_PDF_EVENTS:
        raise ApiError(
            413,
            "runtime_trace.pdf_export_too_large",
            "轨迹事件过多，不能同步生成 PDF",
            "The runtime trace has too many events for synchronous PDF generation",
            params={"max_events": MAX_RUNTIME_TRACE_PDF_EVENTS},
        )
    events = db.query(models.RuntimeTraceEvent).filter(models.RuntimeTraceEvent.trace_id == trace_id).order_by(models.RuntimeTraceEvent.seq).all()
    payloads = {
        row.event_id: row
        for row in db.query(models.RuntimeTracePayload).filter(models.RuntimeTracePayload.trace_id == trace_id).all()
    }
    output_events = []
    for event in events:
        payload = payloads.get(event.event_id)
        item = _event_dict(event, payload)
        if body.redaction_level == "raw" and payload:
            item["payload"] = _loads(unprotect_secret(payload.raw_payload_encrypted), {})
        output_events.append(item)
    export_payload = {"trace": _trace_dict(trace), "events": output_events}
    if body.format == "pdf":
        content_bytes = build_runtime_trace_pdf(export_payload["trace"], output_events, language=body.language)
        protected_content = base64.b64encode(content_bytes).decode("ascii")
    else:
        content_bytes = json.dumps(export_payload, ensure_ascii=False, default=str).encode("utf-8")
        protected_content = content_bytes.decode("utf-8")
    export_id = f"rte_{hashlib.sha256((trace_id + user.username + datetime.utcnow().isoformat()).encode()).hexdigest()[:32]}"
    row = models.RuntimeTraceExport(
        export_id=export_id,
        trace_id=trace_id,
        requested_by=user.username,
        redaction_level=body.redaction_level,
        format=body.format,
        content_encrypted=protect_secret(protected_content),
        sha256=hashlib.sha256(content_bytes).hexdigest(),
        size_bytes=len(content_bytes),
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(row)
    db.commit()
    append_security_audit(
        event_type="runtime_trace.exported",
        actor=user.username,
        resource_type="runtime_trace",
        resource_id=trace_id,
        action="export",
        outcome="success",
        details={"export_id": export_id, "redaction_level": body.redaction_level, "format": body.format},
        bind=db.get_bind(),
    )
    return {
        "export_id": export_id,
        "status": "ready",
        "redaction_level": body.redaction_level,
        "format": body.format,
        "expires_at": row.expires_at,
    }


@router.post("/{trace_id}/exports/raw-authorization")
def authorize_raw_runtime_trace_export(
    trace_id: str,
    body: RuntimeTraceRawExportAuthorizationCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_active_user),
):
    trace = _require_trace(db, trace_id)
    _ensure_read_allowed(db, trace, user)
    _ensure_raw_allowed(db, user)
    if not auth.verify_password(body.password, user.hashed_password):
        append_security_audit(
            event_type="runtime_trace.raw_export_reauthentication_failed",
            actor=user.username,
            resource_type="runtime_trace",
            resource_id=trace_id,
            action="authorize_export",
            outcome="failure",
            details={},
            bind=db.get_bind(),
        )
        raise ApiError(
            403,
            "runtime_trace.raw_export_reauthentication_failed",
            "当前密码验证失败",
            "Current password verification failed",
        )
    raw_token = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(minutes=RAW_EXPORT_AUTHORIZATION_TTL_MINUTES)
    db.add(
        models.RuntimeTraceRawExportAuthorization(
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            trace_id=trace_id,
            user_id=user.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    append_security_audit(
        event_type="runtime_trace.raw_export_authorized",
        actor=user.username,
        resource_type="runtime_trace",
        resource_id=trace_id,
        action="authorize_export",
        outcome="success",
        details={"expires_at": expires_at.isoformat()},
        bind=db.get_bind(),
    )
    return {"authorization_token": raw_token, "expires_at": expires_at}
