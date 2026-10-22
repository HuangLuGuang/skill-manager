from __future__ import annotations

import hashlib
import json
import logging
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import RLock
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models
from .retention import BATCH_SIZE, delete_batch
from ..agentic_risk_taxonomy import MAPPING_VERSION, enrich_risk_codes
from ..api_errors import ApiError
from ..config import settings
from ..feature_flags import TRACE_EVENT_SOURCES
from ..runtime_trace_schemas import (
    RUNTIME_TRACE_SCHEMA_VERSION,
    TRACE_EVENT_TYPES,
    RuntimeTraceBatchCreate,
    RuntimeTraceEventInput,
    RuntimeTraceInternalEvent,
)
from ..security_scan_controls import protect_secret, sanitize_mcp_metadata_value

logger = logging.getLogger(__name__)
_METRICS = {
    "publish_attempts": 0,
    "publish_failures": 0,
    "events_accepted": 0,
    "events_deduplicated": 0,
    "traces_cleaned": 0,
}
_RISK_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_INGEST_LOCK = RLock()
MAX_RUNTIME_TRACE_EVENTS = 100_000
MAX_RUNTIME_TRACE_PAYLOAD_BYTES = 256 * 1024 * 1024


@contextmanager
def ingest_transaction(db: Session):
    """Serialize a multi-batch ingest through commit so SQLite writers cannot interleave."""
    with _INGEST_LOCK:
        try:
            yield
            db.commit()
        except Exception:
            db.rollback()
            raise


def _record_publish_failure(exc: Exception) -> None:
    _METRICS["publish_failures"] += 1
    logger.warning("runtime trace publish failed: %s", type(exc).__name__)


def best_effort_trace_publisher(func):
    """Keep event construction and publication outside the primary request failure path."""

    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # best-effort boundary is intentional
            _record_publish_failure(exc)
            return None

    return wrapped


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _normalize_schema_version(value: str) -> None:
    if value != RUNTIME_TRACE_SCHEMA_VERSION:
        raise ApiError(
            422,
            "runtime_trace.schema_version_unsupported",
            "不支持的轨迹 Schema 版本",
            "Unsupported runtime trace schema version",
            params={"expected": RUNTIME_TRACE_SCHEMA_VERSION, "actual": value},
        )


def _validate_event(event: RuntimeTraceEventInput) -> None:
    _normalize_schema_version(event.schema_version)
    if event.source not in TRACE_EVENT_SOURCES:
        raise ApiError(
            422,
            "runtime_trace.source_unsupported",
            "不支持的轨迹事件来源",
            "Unsupported runtime trace event source",
            params={"source": event.source},
        )
    if event.type not in TRACE_EVENT_TYPES:
        raise ApiError(
            422,
            "runtime_trace.event_type_unsupported",
            "不支持的轨迹事件类型",
            "Unsupported runtime trace event type",
            params={"type": event.type},
        )
    if event.type in {"tool.call", "tool.result", "tool.error", "mcp.call", "mcp.result", "mcp.error"}:
        if not event.call_id:
            raise ApiError(
                422,
                "runtime_trace.call_id_required",
                "工具和 MCP 事件必须包含 call_id",
                "Tool and MCP events require call_id",
            )


def _completeness(trace: models.RuntimeTraceSession) -> str:
    if trace.has_agent_events and (trace.has_model_events or trace.has_mcp_events):
        return "full"
    if trace.has_model_events and not trace.has_agent_events and not trace.has_mcp_events:
        return "model_only"
    if trace.has_mcp_events and not trace.has_agent_events and not trace.has_model_events:
        return "mcp_only"
    return "gateway_partial"


def _risk_level(severity: str | None, *, has_signal: bool = False) -> str:
    """Use an explicit producer level; an unclassified signal has a stable low baseline."""
    value = str(severity or "").strip().lower()
    return value if value in _RISK_ORDER else ("low" if has_signal else "info")


def _fingerprint_payload(value: Any) -> Any:
    """Keep replay fingerprints compatible with events before severity existed."""
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if isinstance(payload, dict):
        payload = dict(payload)
        if payload.get("severity") is None:
            payload.pop("severity", None)
        if isinstance(payload.get("events"), list):
            payload["events"] = [_fingerprint_payload(item) for item in payload["events"]]
    return payload


def create_trace(
    db: Session,
    *,
    tenant_id: str,
    agent_id: str | None,
    session_id: str,
    owner_user_id: int | None,
    owner_group_id: int | None,
    created_by: str | None,
    retention_days: int = 30,
    trace_id: str | None = None,
    commit: bool = True,
) -> models.RuntimeTraceSession:
    trace_id = trace_id or _new_id("trc")
    existing = db.query(models.RuntimeTraceSession).filter(models.RuntimeTraceSession.trace_id == trace_id).first()
    if existing:
        if (
            existing.tenant_id != tenant_id
            or existing.session_id != session_id
            or (existing.agent_id is not None and existing.agent_id != agent_id)
            or (existing.owner_user_id is not None and owner_user_id is not None and existing.owner_user_id != owner_user_id)
            or (
                existing.owner_group_id is not None
                and owner_group_id is not None
                and existing.owner_group_id != owner_group_id
            )
        ):
            raise ApiError(
                409,
                "runtime_trace.identity_conflict",
                "轨迹 ID 已绑定到其他会话或智能体",
                "The trace ID is already bound to another session or Agent",
            )
        if existing.agent_id is None and agent_id:
            existing.agent_id = agent_id
        return existing
    now = datetime.utcnow()
    row = models.RuntimeTraceSession(
        trace_id=trace_id,
        schema_version=RUNTIME_TRACE_SCHEMA_VERSION,
        tenant_id=tenant_id,
        agent_id=agent_id,
        session_id=session_id,
        owner_user_id=owner_user_id,
        owner_group_id=owner_group_id,
        created_by=created_by,
        expires_at=now + timedelta(days=retention_days),
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def _event_fingerprint(event: RuntimeTraceEventInput) -> str:
    return _fingerprint(_fingerprint_payload(event))


def _ingest_batch_locked(
    db: Session,
    trace: models.RuntimeTraceSession,
    batch: RuntimeTraceBatchCreate,
    *,
    expected_agent_id: str | None = None,
    allowed_sources: set[str] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    _normalize_schema_version(batch.schema_version)
    if trace.expires_at <= datetime.utcnow():
        raise ApiError(404, "runtime_trace.not_found", "调用轨迹不存在", "Runtime trace not found")
    batch_fingerprint = _fingerprint(_fingerprint_payload(batch))
    existing_batch = (
        db.query(models.RuntimeTraceIngestBatch)
        .filter(
            models.RuntimeTraceIngestBatch.trace_id == trace.trace_id,
            models.RuntimeTraceIngestBatch.batch_id == batch.batch_id,
        )
        .first()
    )
    if existing_batch:
        if existing_batch.request_fingerprint != batch_fingerprint:
            raise ApiError(
                409,
                "runtime_trace.batch_id_conflict",
                "batch_id 已用于不同内容",
                "The batch_id was already used for different content",
            )
        _METRICS["events_deduplicated"] += len(batch.events)
        return {
            "trace_id": trace.trace_id,
            "batch_id": batch.batch_id,
            "accepted_count": existing_batch.accepted_count,
            "duplicate_count": len(batch.events),
            "first_seq": existing_batch.first_seq,
            "last_seq": existing_batch.last_seq,
            "completeness": trace.completeness,
            "replayed": True,
        }

    accepted: list[models.RuntimeTraceEvent] = []
    duplicate_count = 0
    batch_event_fingerprints: dict[str, str] = {}
    stored_payload_bytes = int(
        db.query(func.coalesce(func.sum(models.RuntimeTracePayload.size_bytes), 0))
        .filter(models.RuntimeTracePayload.trace_id == trace.trace_id)
        .scalar()
        or 0
    )
    accepted_payload_bytes = 0
    now = datetime.utcnow()
    for event in batch.events:
        _validate_event(event)
        enriched_risk_codes, risk_mapping = enrich_risk_codes(event.risk_codes)
        risk_mapping = {**risk_mapping, "severity": _risk_level(event.severity, has_signal=bool(event.risk_codes))}
        if allowed_sources is not None and event.source not in allowed_sources:
            raise ApiError(
                422,
                "runtime_trace.source_not_allowed_for_credential",
                "当前凭证不能上报该来源的轨迹事件",
                "The credential cannot publish this runtime trace event source",
                params={"source": event.source, "allowed_sources": sorted(allowed_sources)},
            )
        fingerprint = _event_fingerprint(event)
        batch_fingerprint_for_event = batch_event_fingerprints.get(event.event_id)
        if batch_fingerprint_for_event is not None:
            if batch_fingerprint_for_event != fingerprint:
                raise ApiError(
                    409,
                    "runtime_trace.event_id_conflict",
                    "event_id 已用于不同内容",
                    "The event_id was already used for different content",
                    params={"event_id": event.event_id},
                )
            duplicate_count += 1
            continue
        existing_event = (
            db.query(models.RuntimeTraceEvent)
            .filter(
                models.RuntimeTraceEvent.trace_id == trace.trace_id,
                models.RuntimeTraceEvent.event_id == event.event_id,
            )
            .first()
        )
        if existing_event:
            if existing_event.content_fingerprint != fingerprint:
                raise ApiError(
                    409,
                    "runtime_trace.event_id_conflict",
                    "event_id 已用于不同内容",
                    "The event_id was already used for different content",
                    params={"event_id": event.event_id},
                )
            duplicate_count += 1
            batch_event_fingerprints[event.event_id] = fingerprint
            continue

        batch_event_fingerprints[event.event_id] = fingerprint

        raw_json = _json_dumps(event.payload)
        raw_size = len(raw_json.encode("utf-8"))
        if trace.event_count >= MAX_RUNTIME_TRACE_EVENTS:
            raise ApiError(
                413,
                "runtime_trace.event_quota_exceeded",
                "单条轨迹的事件数量已达到上限",
                "The event limit for this runtime trace has been reached",
                params={"max_events": MAX_RUNTIME_TRACE_EVENTS},
            )
        if stored_payload_bytes + accepted_payload_bytes + raw_size > MAX_RUNTIME_TRACE_PAYLOAD_BYTES:
            raise ApiError(
                413,
                "runtime_trace.payload_quota_exceeded",
                "单条轨迹的 Payload 存储量已达到上限",
                "The payload storage limit for this runtime trace has been reached",
                params={"max_payload_bytes": MAX_RUNTIME_TRACE_PAYLOAD_BYTES},
            )
        accepted_payload_bytes += raw_size
        # Trace quotas bound storage; message histories need more space than MCP metadata.
        if event.redacted_payload is None:
            redacted, _ = sanitize_mcp_metadata_value(event.payload, max_depth=16, max_items=None)
        else:
            redacted, _ = sanitize_mcp_metadata_value(event.redacted_payload, max_depth=16, max_items=None)
        payload_id = _new_id("rtp")
        payload = models.RuntimeTracePayload(
            payload_id=payload_id,
            trace_id=trace.trace_id,
            event_id=event.event_id,
            raw_payload_encrypted=protect_secret(raw_json),
            redacted_json=_json_dumps(redacted),
            raw_sha256=hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
            size_bytes=raw_size,
            expires_at=trace.expires_at,
        )
        row = models.RuntimeTraceEvent(
            event_id=event.event_id,
            content_fingerprint=fingerprint,
            trace_id=trace.trace_id,
            seq=trace.next_seq,
            schema_version=event.schema_version,
            event_time=(
                event.event_time.astimezone(timezone.utc).replace(tzinfo=None)
                if event.event_time.tzinfo is not None
                else event.event_time
            ),
            received_at=now,
            tenant_id=trace.tenant_id,
            agent_id=expected_agent_id or trace.agent_id,
            session_id=trace.session_id,
            turn_id=event.turn_id,
            step_id=event.step_id,
            source=event.source,
            type=event.type,
            request_id=event.request_id,
            call_id=event.call_id,
            parent_call_id=event.parent_call_id,
            status=event.status,
            tool_name=event.tool_name,
            duration_ms=event.duration_ms,
            risk_codes_json=_json_dumps(enriched_risk_codes),
            risk_mapping_json=_json_dumps(risk_mapping),
            payload_id=payload_id,
        )
        db.add(payload)
        db.add(row)
        accepted.append(row)
        trace.next_seq += 1
        trace.event_count += 1
        trace.first_event_at = trace.first_event_at or now
        trace.last_event_at = now
        trace.has_agent_events = trace.has_agent_events or event.source in {"agent_sdk", "dify_adapter"}
        trace.has_model_events = trace.has_model_events or event.source == "model_gateway"
        trace.has_mcp_events = trace.has_mcp_events or event.source == "mcp_gateway"
        trace.has_runtime_events = trace.has_runtime_events or event.source in {"runtime_governance", "dify_adapter"}
        trace.has_knowledge_events = trace.has_knowledge_events or event.type == "knowledge.retrieval"
        existing_codes = set(json.loads(trace.risk_codes_json or "[]"))
        existing_codes.update(enriched_risk_codes)
        trace.risk_codes_json = _json_dumps(sorted(existing_codes))
        if enriched_risk_codes:
            trace.risk_mapping_version = MAPPING_VERSION
        candidate = _risk_level(event.severity, has_signal=bool(event.risk_codes))
        if _RISK_ORDER[candidate] > _RISK_ORDER.get(trace.risk_level, 0):
            trace.risk_level = candidate

    trace.completeness = _completeness(trace)
    trace.updated_at = now
    batch_row = models.RuntimeTraceIngestBatch(
        trace_id=trace.trace_id,
        batch_id=batch.batch_id,
        request_fingerprint=batch_fingerprint,
        accepted_count=len(accepted),
        duplicate_count=duplicate_count,
        first_seq=accepted[0].seq if accepted else None,
        last_seq=accepted[-1].seq if accepted else None,
    )
    db.add(batch_row)
    if commit:
        db.commit()
    else:
        db.flush()
    _METRICS["events_accepted"] += len(accepted)
    _METRICS["events_deduplicated"] += duplicate_count
    return {
        "trace_id": trace.trace_id,
        "batch_id": batch.batch_id,
        "accepted_count": len(accepted),
        "duplicate_count": duplicate_count,
        "first_seq": batch_row.first_seq,
        "last_seq": batch_row.last_seq,
        "completeness": trace.completeness,
        "replayed": False,
    }


def ingest_batch(
    db: Session,
    trace: models.RuntimeTraceSession,
    batch: RuntimeTraceBatchCreate,
    *,
    expected_agent_id: str | None = None,
    allowed_sources: set[str] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    # The production backend currently uses one SQLite writer process. Serialize
    # sequence allocation inside that process so concurrent request threads cannot
    # observe the same next_seq value.
    with _INGEST_LOCK:
        db.refresh(trace)
        return _ingest_batch_locked(
            db,
            trace,
            batch,
            expected_agent_id=expected_agent_id,
            allowed_sources=allowed_sources,
            commit=commit,
        )


def publish_events_best_effort(db: Session, events: list[RuntimeTraceInternalEvent], *, commit: bool = True) -> str | None:
    """Publish optional events; commit=False joins the caller's locked transaction.

    Joined callers own rollback and the best-effort exception boundary.
    """
    if not events or not settings.RUNTIME_TRACE_ENABLED:
        return None
    _METRICS["publish_attempts"] += 1
    try:
        # Take the trace lock before create_trace flushes a SQLite write.
        with ingest_transaction(db) if commit else nullcontext():
            first = events[0]
            trace_id = first.trace_id or _new_id("trc")
            trace = create_trace(
                db,
                trace_id=trace_id,
                tenant_id=first.tenant_id,
                agent_id=first.agent_id,
                session_id=first.session_id,
                owner_user_id=first.owner_user_id,
                owner_group_id=first.owner_group_id,
                created_by="internal_gateway",
                commit=False,
            )
            inputs = [
                RuntimeTraceEventInput(
                    event_id=item.event_id or _new_id("evt"),
                    event_time=item.event_time or datetime.utcnow(),
                    source=item.source,
                    type=item.type,
                    turn_id=item.turn_id,
                    step_id=item.step_id,
                    request_id=item.request_id,
                    call_id=item.call_id,
                    parent_call_id=item.parent_call_id,
                    status=item.status,
                    tool_name=item.tool_name,
                    duration_ms=item.duration_ms,
                    severity=item.severity,
                    risk_codes=item.risk_codes,
                    payload=item.payload,
                    redacted_payload=item.redacted_payload,
                )
                for item in events
            ]
            ingest_batch(
                db,
                trace,
                RuntimeTraceBatchCreate(batch_id=_new_id("bat"), events=inputs),
                expected_agent_id=first.agent_id,
                commit=False,
            )
            return trace_id
    except Exception as exc:  # best-effort boundary is intentional
        if not commit:
            # The caller owns the trace lock and rollback boundary.
            raise
        db.rollback()
        _record_publish_failure(exc)
        return None


def cleanup_expired(db: Session, *, now: datetime | None = None, limit: int = BATCH_SIZE) -> dict[str, int | bool]:
    """Bound child rows as well as sessions; each table releases its write lock."""
    if not 1 <= limit <= BATCH_SIZE:
        raise ValueError("runtime_trace_retention_budget_invalid")
    now = now or datetime.utcnow()
    trace_ids = [
        row[0]
        for row in db.query(models.RuntimeTraceSession.trace_id)
        .filter(models.RuntimeTraceSession.expires_at <= now)
        .order_by(models.RuntimeTraceSession.expires_at, models.RuntimeTraceSession.id)
        .limit(limit)
        .all()
    ]
    counts = {}
    children = (
        ("exports", models.RuntimeTraceExport),
        ("payloads", models.RuntimeTracePayload),
        ("events", models.RuntimeTraceEvent),
        ("batches", models.RuntimeTraceIngestBatch),
        ("authorizations", models.RuntimeTraceRawExportAuthorization),
    )
    for name, model in children:
        predicate = model.trace_id.in_(trace_ids)
        if model is models.RuntimeTraceExport:
            predicate = or_(predicate, model.expires_at <= now)
        counts[name] = delete_batch(db, model, predicate, limit=limit)
        db.commit()
    requests = db.query(models.GatewaySessionRequest.request_id).filter(models.GatewaySessionRequest.trace_id.in_(trace_ids))
    delete_batch(db, models.GatewaySessionFingerprint,
                 models.GatewaySessionFingerprint.request_id.in_(requests), limit=limit)
    db.commit()
    delete_batch(db, models.GatewaySessionRequest,
                 models.GatewaySessionRequest.trace_id.in_(trace_ids) & ~db.query(models.GatewaySessionFingerprint).filter(
                     models.GatewaySessionFingerprint.request_id == models.GatewaySessionRequest.request_id).exists(), limit=limit)
    db.commit()
    delete_batch(db, models.GatewaySessionGroup,
                 models.GatewaySessionGroup.trace_id.in_(trace_ids) & ~db.query(models.GatewaySessionRequest).filter(
                     models.GatewaySessionRequest.trace_id == models.GatewaySessionGroup.trace_id).exists(), limit=limit)
    db.commit()
    removed_scopes = delete_batch(db, models.GatewaySessionScope, ~db.query(models.GatewaySessionGroup).filter(
        models.GatewaySessionGroup.scope_id == models.GatewaySessionScope.scope_id).exists(), limit=limit)
    db.commit()
    removable = db.query(models.RuntimeTraceSession).filter(models.RuntimeTraceSession.trace_id.in_(trace_ids))
    for model in [*(model for _, model in children), models.GatewaySessionGroup]:
        removable = removable.filter(~db.query(model).filter(model.trace_id == models.RuntimeTraceSession.trace_id).exists())
    counts["traces"] = removable.delete(synchronize_session=False) if trace_ids else 0
    db.commit()
    _METRICS["traces_cleaned"] += counts["traces"]
    counts["more"] = bool(
        removed_scopes == limit
        or db.query(models.RuntimeTraceSession.id).filter(models.RuntimeTraceSession.expires_at <= now).first()
        or db.query(models.RuntimeTraceExport.id).filter(models.RuntimeTraceExport.expires_at <= now).first()
    )
    return counts


def metrics_snapshot(db: Session) -> dict[str, Any]:
    pending_exports = db.query(models.RuntimeTraceExport).filter(models.RuntimeTraceExport.status == "pending").count()
    stored_bytes = db.query(func.coalesce(func.sum(models.RuntimeTracePayload.size_bytes), 0)).scalar()
    return {
        **_METRICS,
        "trace_count": db.query(models.RuntimeTraceSession).count(),
        "event_count": db.query(models.RuntimeTraceEvent).count(),
        "payload_bytes": int(stored_bytes or 0),
        "export_backlog": pending_exports,
    }
