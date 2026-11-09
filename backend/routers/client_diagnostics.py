import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy import func

from backend import iam
from backend.api_errors import ApiError
from backend.client_diagnostics import DiagnosticLog, DiagnosticSettings, DiagnosticDebugLease, LEVELS, RETENTION_DAYS, configuration, initialize_usage, trim_capacity, unresolved_incidents
from backend.sqlite_db import get_db
from backend.services.gateway_db import run_sync
from .clients import _client_or_404, _ensure_visible, _runtime_token

router = APIRouter(prefix="/v1/clients", tags=["client-diagnostics"])


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["INHERIT", "OFF", "DEBUG", "INFO", "WARN", "ERROR"]


class Aggregation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    repeated_count: int = Field(ge=1)
    first_at: str = Field(max_length=40)
    last_at: str = Field(max_length=40)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    time: str = Field(max_length=40)
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    module: str = Field(max_length=1024)
    event: str = Field(max_length=256)
    version: str = Field(max_length=128)
    pid: int = Field(ge=0)
    fields: dict = Field(default_factory=dict)
    aggregation: Aggregation | None = None


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    records: list[Record] = Field(min_length=1, max_length=100)


def invalid():
    return ApiError(422, "client.diagnostics.invalid", "运行日志参数无效或超过限制", "Invalid or oversized runtime log parameters")


def visible(db, user, client_id):
    if client_id:
        _ensure_visible(_client_or_404(db, client_id), user)


@router.get("/diagnostics/settings")
def get_settings(client_id: str | None = None, db=Depends(get_db), user=Depends(iam.require("clients:view"))):
    visible(db, user, client_id)
    return configuration(db, client_id)


@router.put("/diagnostics/settings")
def save_settings(body: SettingsInput, request: Request, client_id: str | None = None, db=Depends(get_db), user=Depends(iam.require("clients:update"))):
    visible(db, user, client_id)
    if not client_id and body.level == "INHERIT":
        raise invalid()
    scope = "client:" + client_id if client_id else "global"
    before = configuration(db, client_id)
    db.execute(insert(DiagnosticSettings).values(scope=scope, level=body.level).on_conflict_do_update(index_elements=["scope"], set_={"level": body.level}))
    if body.level in {"DEBUG", "INFO"}:
        expiry = datetime.utcnow() + timedelta(hours=1)
        db.execute(insert(DiagnosticDebugLease).values(scope=scope, expires_at=expiry).on_conflict_do_update(index_elements=["scope"], set_={"expires_at": expiry}))
    else:
        db.query(DiagnosticDebugLease).filter_by(scope=scope).delete()
    iam.audit(db, request, user, "clients", "update", f"diagnostics:{client_id or 'global'}", before=before, after={"level": body.level})
    db.commit()
    return configuration(db, client_id)


def runtime(db, request, authorization, client_id, scope):
    token = _runtime_token(scope, authorization, request, db)
    if token.bound_client_id != client_id:
        raise ApiError(403, "client.diagnostics.binding", "凭据未绑定此客户端", "Credential is not bound to this client")
    _client_or_404(db, client_id)


@router.get("/{client_id}/diagnostics/config")
def runtime_config(client_id: str, request: Request, authorization: str | None = Header(None), db=Depends(get_db)):
    runtime(db, request, authorization, client_id, "client:read-policy")
    return configuration(db, client_id)


@router.post("/{client_id}/diagnostics/batch")
async def receive(client_id: str, request: Request, authorization: str | None = Header(None), db=Depends(get_db)):
    await run_sync(runtime, db, request, authorization, client_id, "client:report-inventory")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            raise invalid()
    return await run_sync(store_batch, db, client_id, body)


def store_batch(db, client_id, body):
    try:
        batch = Batch.model_validate_json(body)
        entries = []
        minimum = LEVELS.get(configuration(db, client_id)["effective_level"], 100)
        for record in batch.records:
            timestamp = datetime.fromisoformat(record.time.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("timezone required")
            content = json.dumps(record.model_dump(exclude={"id"}, exclude_none=True), ensure_ascii=False, separators=(",", ":"))
            if len(content.encode()) > 65536:
                raise ValueError("record too large")
            incident = record.fields.get("incident_id")
            recovery = (record.level == "INFO" and record.event == "sync_recovered"
                        and isinstance(incident, str) and len(incident) == 32
                        and all(c in "0123456789abcdef" for c in incident))
            if LEVELS[record.level] >= minimum or (minimum <= 40 and recovery):
                entries.append(dict(client_id=client_id, record_id=record.id, occurred_at=timestamp.astimezone(timezone.utc).replace(tzinfo=None), level=record.level, module=record.module, event=record.event, version=record.version, content=content))
    except (ValidationError, ValueError, TypeError, OverflowError):
        raise invalid() from None
    if entries:
        initialize_usage(db)
        db.execute(insert(DiagnosticLog).values(entries).on_conflict_do_nothing(index_elements=["client_id", "record_id"]))
        trim_capacity(db)
        db.commit()
    # Filtered records are intentionally acknowledged when policy changed in flight.
    return {"acknowledged": [record.id for record in batch.records]}


def query_logs(db, client_id, level, module, version, keyword, start, end, unresolved=False):
    query = db.query(DiagnosticLog).filter(DiagnosticLog.client_id == client_id, DiagnosticLog.received_at >= datetime.utcnow() - timedelta(days=RETENTION_DAYS))
    if unresolved:
        incidents = unresolved_incidents(db, [client_id]).subquery()
        query = query.join(incidents, (DiagnosticLog.client_id == incidents.c.client_id) &
            (func.json_extract(DiagnosticLog.content, '$.fields.incident_id') == incidents.c.incident_id))
    for column, value in [(DiagnosticLog.level, level), (DiagnosticLog.module, module), (DiagnosticLog.version, version)]:
        if value:
            query = query.filter(column == value)
    if keyword:
        query = query.filter(DiagnosticLog.content.contains(keyword, autoescape=True))
    for value, lower in [(start, True), (end, False)]:
        if value:
            if value.tzinfo is None:
                raise invalid()
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
            query = query.filter(DiagnosticLog.occurred_at >= value if lower else DiagnosticLog.occurred_at <= value)
    return query


@router.get("/{client_id}/diagnostics/logs")
def logs(client_id: str, request: Request, response: Response, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), level: str = Query("", max_length=16), module: str = Query("", max_length=1024), version: str = Query("", max_length=128), keyword: str = Query("", max_length=200), start: datetime | None = None, end: datetime | None = None, download: bool = False, unresolved: bool = False, sort_order: Literal["asc", "desc"] = "desc", db=Depends(get_db), user=Depends(iam.require("clients:diagnostics"))):
    visible(db, user, client_id)
    if download:
        request.state.iam_permission = "clients:diagnostics-export"
        iam.check(db, user, "clients:diagnostics-export")
    query = query_logs(db, client_id, level, module, version, keyword, start, end, unresolved)
    total = query.count()
    order = [column.asc() if sort_order == "asc" else column.desc() for column in (DiagnosticLog.occurred_at, DiagnosticLog.id)]
    rows = query.order_by(*order).offset((page - 1) * page_size).limit(page_size).all()
    iam.audit(db, request, user, "clients", "diagnostics-export" if download else "diagnostics", client_id, details={"page": page, "count": len(rows)})
    db.commit()
    if download:
        return Response("\n".join(row.content for row in rows), media_type="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="client-runtime-logs.jsonl"', "Cache-Control": "no-store"})
    response.headers["Cache-Control"] = "no-store"
    return {"items": [dict(id=row.record_id, **json.loads(row.content)) for row in rows], "total": total}
