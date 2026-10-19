"""Manage callback configuration and enqueue auditable test notifications."""
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from .. import auth
from ..api_errors import ApiError
from ..external_access_models import (ExternalCallbackConfig, ExternalDeliveryEndpoint,
    ExternalPlatform, ExternalResultEvent, ExternalDelivery)
from ..security_scan_controls import protect_secret
from ..services import external_delivery as delivery
from ..sqlite_db import get_db
from .external_deliveries import EndpointCreate, delivery_response
from ..services.openapi_agents import APIKey
from ..services.openapi_skills import Identifier

router = APIRouter(prefix="/external-access/callbacks", tags=["external-access"])
NotificationType = Literal["skill_scan", "agent_evaluation"]


class ReceiverSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform_ids: list[str] = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    bearer_token: APIKey | None = None
    enabled: bool = True

    @field_validator("bearer_token", mode="before")
    @classmethod
    def keep_empty_token(cls, value):
        return None if value == "" else value

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        return EndpointCreate.valid_url(value)

    @field_validator("platform_ids")
    @classmethod
    def distinct(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate values")
        return value


class CallbackSettings(ReceiverSettings):
    name: str = Field(min_length=1, max_length=128)
    notification_types: list[NotificationType] = Field(min_length=1, max_length=2)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name is required")
        return value

    @field_validator("notification_types")
    @classmethod
    def distinct_types(cls, value):
        return cls.distinct(value)


class CallbackCreate(CallbackSettings):
    callback_id: Identifier
    bearer_token: APIKey

    @field_validator("callback_id")
    @classmethod
    def nonblank_id(cls, value):
        if not value.strip():
            raise ValueError("Callback ID is required")
        return value


class CallbackUpdate(CallbackSettings):
    revision: int = Field(ge=1, strict=True)


class CallbackState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    enabled: bool


class CallbackTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    platform_id: str
    notification_type: NotificationType


def get_config(db, callback_id, revision=None):
    row = db.get(ExternalCallbackConfig, callback_id)
    if row is None or row.deleted_at:
        raise ApiError(404, "external_callbacks.not_found", "回调配置不存在", "Callback configuration not found")
    if revision is not None and row.revision != revision:
        raise ApiError(409, "external_callbacks.conflict", "回调配置已变更，请刷新后重试", "Callback configuration changed; refresh and retry")
    return row


def response(db, row):
    endpoint = db.get(ExternalDeliveryEndpoint, row.endpoint_id)
    return {"callback_id": row.callback_id, "name": row.name, "enabled": row.enabled,
        "revision": row.revision, "version": endpoint.version,
        "platform_ids": json.loads(endpoint.platform_ids_json), "url": endpoint.url,
        "bearer_token_masked": "********", "notification_types": json.loads(endpoint.notification_types_json),
        "created_by": row.created_by, "created_at": row.created_at, "updated_at": row.updated_at}


def validate_partners(db, ids):
    if db.query(ExternalPlatform).filter(ExternalPlatform.platform_id.in_(ids)).count() != len(ids):
        raise ApiError(422, "external_access.delivery_partner_invalid", "请选择有效的接入方", "Select valid integration partners")


def new_endpoint(db, config_id, body, username, previous=None, *, kind="callback"):
    if kind == "gateway":
        from ..services.external_gateways import linked_gateway, receiver_url
        url = receiver_url(linked_gateway(db, body.external_gateway_id), body.gateway_path)
        token = ""
    else:
        url = body.url
        token = protect_secret(body.bearer_token) if body.bearer_token else previous.token_encrypted
    endpoint = ExternalDeliveryEndpoint(endpoint_id="oe_" + uuid.uuid4().hex,
        kind=kind, config_id=config_id, version="v_" + uuid.uuid4().hex,
        external_gateway_id=body.external_gateway_id if kind == "gateway" else None,
        gateway_path=body.gateway_path if kind == "gateway" else None,
        platform_ids_json=json.dumps(body.platform_ids),
        notification_types_json=json.dumps(body.notification_types if kind == "callback" else ["agent_evaluation"]),
        url=url, token_encrypted=token,
        enabled=True, timeout_seconds=previous.timeout_seconds if previous else 10,
        retry_delays_json=previous.retry_delays_json if previous else "[60, 300, 900, 3600, 21600, 86400]",
        max_payload_bytes=previous.max_payload_bytes if previous else 10 * 1024 * 1024, created_by=username)
    db.add(endpoint)
    db.flush()
    return endpoint


@router.get("")
def list_callbacks(db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {"items": [response(db, row) for row in db.query(ExternalCallbackConfig).filter(
        ExternalCallbackConfig.deleted_at.is_(None)).order_by(ExternalCallbackConfig.created_at.desc()).all()]}


@router.post("", status_code=201)
def create(body: CallbackCreate, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    if db.get(ExternalCallbackConfig, body.callback_id):
        raise ApiError(409, "external_callbacks.exists", "回调编号已使用，请使用新编号", "Callback ID is already used; choose a new ID")
    validate_partners(db, body.platform_ids)
    endpoint = new_endpoint(db, body.callback_id, body, user.username)
    row = ExternalCallbackConfig(callback_id=body.callback_id, name=body.name, endpoint_id=endpoint.endpoint_id,
        enabled=body.enabled, created_by=user.username)
    db.add(row)
    db.commit()
    return response(db, row)


@router.put("/{callback_id:path}")
def update(callback_id: str, body: CallbackUpdate, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, callback_id, body.revision)
    validate_partners(db, body.platform_ids)
    endpoint = new_endpoint(db, callback_id, body, user.username, db.get(ExternalDeliveryEndpoint, row.endpoint_id))
    row.name, row.enabled, row.endpoint_id = body.name, body.enabled, endpoint.endpoint_id
    row.revision += 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return response(db, row)


@router.patch("/{callback_id:path}/state")
def set_state(callback_id: str, body: CallbackState, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, callback_id, body.revision)
    row.enabled = body.enabled
    db.get(ExternalDeliveryEndpoint, row.endpoint_id).enabled = body.enabled
    row.revision += 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return response(db, row)


@router.delete("/{callback_id:path}")
def delete(callback_id: str, revision: int = Query(ge=1), db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, callback_id, revision)
    row.deleted_at = row.updated_at = datetime.utcnow()
    row.enabled = False
    row.revision += 1
    db.commit()
    return {"callback_id": callback_id, "deleted": True}


@router.post("/{callback_id:path}/test", status_code=202)
def test_notification(callback_id: str, body: CallbackTest, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, callback_id, body.revision)
    endpoint = db.get(ExternalDeliveryEndpoint, row.endpoint_id)
    platform = db.get(ExternalPlatform, body.platform_id)
    if not row.enabled or not endpoint.enabled or not platform or not platform.enabled:
        raise ApiError(409, "external_callbacks.test_disabled", "请先启用回调配置和接入方", "Enable the callback configuration and integration partner first")
    if body.platform_id not in json.loads(endpoint.platform_ids_json) or body.notification_type not in json.loads(endpoint.notification_types_json):
        raise ApiError(422, "external_callbacks.test_scope", "请选择已授权的接入方和通知类型", "Select an authorized partner and notification type")
    test_id = "cbtest_" + uuid.uuid4().hex
    payload = {"schema_version": "security-callback-test.v1", "event_id": "ev_" + test_id,
        "event_type": "callback.test", "occurred_at": datetime.now(timezone.utc).isoformat(),
        "platform_id": body.platform_id, "callback_id": callback_id, "notification_type": body.notification_type}
    db.add(ExternalResultEvent(event_id=payload["event_id"], task_id=test_id, source_platform_id=body.platform_id,
        callback_id=callback_id, callback_version=endpoint.version, payload_json=json.dumps(payload), created_by=user.username))
    db.flush()
    delivery.enqueue(db, task_id=test_id)
    item = db.query(ExternalDelivery).filter_by(kind="callback", task_id=test_id).one()
    db.commit()
    return delivery_response(item)
