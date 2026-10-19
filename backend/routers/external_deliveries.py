"""Management of versioned receivers and outbound delivery records."""
import json
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth
from ..api_errors import ApiError
from ..external_access_models import ExternalPlatform, ExternalDeliveryEndpoint, ExternalDelivery, ExternalDeliveryAttempt
from ..security_scan_controls import protect_secret
from ..services import external_delivery as service
from ..services.openapi_skills import Identifier
from ..services.openapi_agents import APIKey
from ..sqlite_db import get_db

router = APIRouter(prefix="/external-access", tags=["external-access"])


class EndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["callback", "gateway"]
    config_id: Identifier
    version: Identifier
    external_gateway_id: int | None = Field(default=None, ge=1, strict=True)
    platform_ids: list[str] = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    bearer_token: APIKey | None = None
    gateway_path: str | None = Field(default=None, min_length=1, max_length=2048)
    timeout_seconds: int = Field(10, ge=1, le=60, strict=True)
    retry_delays_seconds: list[int] = Field(default_factory=lambda: [60, 300, 900, 3600, 21600, 86400], max_length=10)
    max_payload_bytes: int = Field(10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024, strict=True)

    @model_validator(mode="after")
    def authentication(self):
        if self.kind == "gateway":
            from ..services.external_gateways import validate_path
            if self.external_gateway_id is None or self.gateway_path is None or self.url is not None or self.bearer_token is not None:
                raise ValueError("Gateway delivery requires a linked gateway and API path")
            validate_path(self.gateway_path)
        elif not self.url or not self.bearer_token or self.gateway_path is not None:
            raise ValueError("Callback delivery requires a receiver URL and Bearer token")
        return self

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Use an HTTP or HTTPS receiver URL without user information or fragment")
        parsed.port
        return value

    @field_validator("retry_delays_seconds", mode="before")
    @classmethod
    def valid_delays(cls, values):
        if not isinstance(values, list) or any(type(v) is not int or not 1 <= v <= 86400 for v in values):
            raise ValueError("Retry delays must be integer seconds from 1 to 86400")
        return values


class EndpointState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def endpoint_response(row):
    return {**{name: getattr(row, name) for name in ("endpoint_id", "kind", "config_id", "version", "url", "enabled",
            "timeout_seconds", "max_payload_bytes", "created_by", "created_at")},
            "platform_ids": json.loads(row.platform_ids_json), "retry_delays_seconds": json.loads(row.retry_delays_json),
            "token_configured": bool(row.token_encrypted), "external_gateway_id": row.external_gateway_id,
            "gateway_path": row.gateway_path}


@router.get("/delivery-endpoints")
def endpoints(db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {"items": [endpoint_response(row) for row in db.query(ExternalDeliveryEndpoint).order_by(
        ExternalDeliveryEndpoint.created_at.desc()).all()]}


@router.post("/delivery-endpoints", status_code=201)
def create_endpoint(body: EndpointCreate, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    service.locked(db)
    if body.external_gateway_id is not None:
        if body.kind != "gateway":
            raise ApiError(422, "external_gateways.invalid_kind", "外部 AI 网关关联用于评测结果同步", "External AI gateway links are used for evaluation result synchronization")
        from ..services.external_gateways import linked_gateway, receiver_url
        gateway = linked_gateway(db, body.external_gateway_id)
    ids = set(body.platform_ids)
    if len(ids) != len(body.platform_ids) or db.query(ExternalPlatform).filter(ExternalPlatform.platform_id.in_(ids)).count() != len(ids):
        raise ApiError(422, "external_access.delivery_partner_invalid", "请选择有效且不重复的接入方", "Select valid, distinct partners")
    row = ExternalDeliveryEndpoint(endpoint_id="oe_" + uuid.uuid4().hex, kind=body.kind, config_id=body.config_id,
        external_gateway_id=body.external_gateway_id,
        gateway_path=body.gateway_path,
        version=body.version, platform_ids_json=json.dumps(body.platform_ids),
        url=receiver_url(gateway, body.gateway_path) if body.kind == "gateway" else body.url,
        token_encrypted=protect_secret(body.bearer_token) if body.kind == "callback" else "", timeout_seconds=body.timeout_seconds,
        retry_delays_json=json.dumps(body.retry_delays_seconds), max_payload_bytes=body.max_payload_bytes, created_by=user.username,
        enabled=True)
    db.add(row)
    try:
        if body.kind == "callback":
            from ..services.external_callbacks import register_endpoint
        else:
            from ..services.external_gateways import register_endpoint
        register_endpoint(db, row)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "external_access.delivery_version_exists", "该接收端版本已存在，请使用新版本号", "Receiver version exists; use a new version") from None
    return endpoint_response(row)


@router.put("/delivery-endpoints/{endpoint_id}")
def set_endpoint_state(endpoint_id: str, body: EndpointState, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    service.locked(db)
    row = db.get(ExternalDeliveryEndpoint, endpoint_id)
    if not row:
        raise ApiError(404, "external_access.delivery_endpoint_not_found", "接收端配置不存在", "Receiver configuration not found")
    row.enabled = body.enabled
    config = db.get(service.CONFIGS[row.kind], row.config_id)
    if config and config.endpoint_id == endpoint_id:
        config.enabled = body.enabled
        config.revision += 1
        config.updated_at = datetime.utcnow()
    db.commit()
    return endpoint_response(row)


def delivery_response(row):
    return {**{name: getattr(row, name) for name in ("delivery_id", "kind", "task_id", "platform_id", "business_request_id",
        "config_id", "config_version", "message_id", "status", "attempts", "last_attempt_at", "next_retry_at",
        "last_error_code", "completed_at", "created_at", "updated_at", "purpose", "task_type", "created_by")},
        "task_id": None if row.purpose == "test" else row.task_id,
        "in_flight": row.lease_token is not None, "receipt": json.loads(row.receipt_json) if row.receipt_json else None}


@router.get("/deliveries")
def deliveries(kind: Literal["callback", "gateway"] | None = None, platform_id: str | None = None,
        status: Literal["pending", "retrying", "delivered", "synced", "failed"] | None = None,
        task_id: str | None = None, message_id: str | None = None, business_request_id: str | None = None,
        config_id: str | None = None, purpose: Literal["result", "test"] | None = None,
        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
        db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    service.locked(db)
    service.enqueue(db)
    db.commit()
    query = db.query(ExternalDelivery)
    for name, value in {"kind": kind, "platform_id": platform_id, "status": status, "task_id": task_id,
                        "message_id": message_id, "business_request_id": business_request_id,
                        "config_id": config_id, "purpose": purpose}.items():
        if value is not None:
            query = query.filter(getattr(ExternalDelivery, name) == value)
    return {"total": query.count(), "items": [delivery_response(row) for row in query.order_by(
        ExternalDelivery.created_at.desc(), ExternalDelivery.delivery_id).offset((page - 1) * page_size).limit(page_size).all()]}


def get_delivery(db, delivery_id):
    row = db.get(ExternalDelivery, delivery_id)
    if not row:
        raise ApiError(404, "external_access.delivery_not_found", "投递记录不存在", "Delivery record not found")
    return row


@router.get("/deliveries/{delivery_id}")
def delivery_detail(delivery_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    row = get_delivery(db, delivery_id)
    attempts = db.query(ExternalDeliveryAttempt).filter_by(delivery_id=delivery_id).order_by(ExternalDeliveryAttempt.number).all()
    return {**delivery_response(row), "attempt_records": [{**{name: getattr(attempt, name) for name in (
        "attempt_id", "number", "status", "started_at", "finished_at", "http_status", "error_code")},
        "receipt": json.loads(attempt.receipt_json) if attempt.receipt_json else None} for attempt in attempts]}


@router.post("/deliveries/{delivery_id}/retry")
def redeliver(delivery_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    service.locked(db)
    row = get_delivery(db, delivery_id)
    if row.status != "failed" or row.lease_token:
        raise ApiError(409, "external_access.delivery_not_failed", "只有失败的投递可以重新发送", "Only failed deliveries can be retried")
    if not service.event_for(db, row).payload_json:
        raise ApiError(409, "external_access.delivery_report_unavailable", "该任务没有可同步的报告", "The task has no report to synchronize")
    config = db.get(service.CONFIGS[row.kind], row.config_id)
    if config and (config.deleted_at or not config.enabled):
        if row.kind == "callback":
            raise ApiError(409, "external_callbacks.retry_disabled", "回调配置已停用或删除，无法重新投递", "Callback configuration is disabled or deleted; delivery cannot be retried")
        raise ApiError(409, "external_gateways.retry_disabled", "网关配置已停用或删除，无法重新投递", "Gateway configuration is disabled or deleted; delivery cannot be retried")
    row.status, row.cycle_attempts = "pending", 0
    row.next_retry_at = row.last_error_code = None
    row.updated_at = datetime.utcnow()
    service.mirror(db, row)
    db.commit()
    return delivery_response(row)
