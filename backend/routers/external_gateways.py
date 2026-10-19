"""Manage versioned gateway configurations and durable test notifications."""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from .. import auth
from ..models import ExternalAIGateway
from ..services.external_gateways import linked_gateway, validate_path, require_path
from ..api_errors import ApiError
from ..external_access_models import (ExternalGatewayConfig, ExternalDeliveryEndpoint,
    ExternalPlatform, ExternalGatewayEvent, ExternalDelivery)
from ..services import external_delivery as delivery
from ..sqlite_db import get_db
from ..services.openapi_skills import Identifier
from .external_callbacks import ReceiverSettings, CallbackState, new_endpoint, validate_partners
from .external_deliveries import delivery_response

router = APIRouter(prefix="/external-access/gateways", tags=["external-access"])


class GatewaySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_gateway_id: int = Field(ge=1, strict=True)
    platform_ids: list[str] = Field(min_length=1, max_length=200)
    gateway_path: str = Field(min_length=1, max_length=2048)
    enabled: bool = True

    _path = field_validator("gateway_path")(validate_path)
    _platforms = field_validator("platform_ids")(ReceiverSettings.distinct)


class GatewayCreate(GatewaySettings):
    gateway_id: Identifier

    @field_validator("gateway_id")
    @classmethod
    def nonblank_id(cls, value):
        if not value.strip():
            raise ValueError("Gateway ID is required")
        return value


class GatewayUpdate(GatewaySettings):
    revision: int = Field(ge=1, strict=True)


class GatewayTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    platform_id: str


def get_config(db, gateway_id, revision=None):
    row = db.get(ExternalGatewayConfig, gateway_id)
    if row is None or row.deleted_at:
        raise ApiError(404, "external_gateways.not_found", "网关配置不存在", "Gateway configuration not found")
    if revision is not None and row.revision != revision:
        raise ApiError(409, "external_gateways.conflict", "网关配置已变更，请刷新后重试", "Gateway configuration changed; refresh and retry")
    return row


def response(db, row):
    endpoint = db.get(ExternalDeliveryEndpoint, row.endpoint_id)
    gateway = db.get(ExternalAIGateway, endpoint.external_gateway_id) if endpoint.external_gateway_id is not None else None
    return {"gateway_id": row.gateway_id, "name": gateway.name if gateway else row.name, "enabled": row.enabled,
        "external_gateway_id": endpoint.external_gateway_id, "binding_required": endpoint.external_gateway_id is None,
        "path_required": not bool(endpoint.gateway_path), "gateway_path": endpoint.gateway_path,
        "token_id": gateway.token_id if gateway else None,
        "external_gateway_enabled": gateway.enabled if gateway else None,
        "revision": row.revision, "version": endpoint.version,
        "platform_ids": json.loads(endpoint.platform_ids_json), "url": endpoint.url,
        "created_by": row.created_by,
        "created_at": row.created_at, "updated_at": row.updated_at}


@router.get("")
def list_gateways(db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {"items": [response(db, row) for row in db.query(ExternalGatewayConfig).filter(
        ExternalGatewayConfig.deleted_at.is_(None)).order_by(ExternalGatewayConfig.created_at.desc()).all()]}


@router.get("/options")
def options(db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {"items": [{"id": row.id, "name": row.name, "enabled": row.enabled,
                       "management_base_url": row.management_base_url, "token_id": row.token_id}
        for row in db.query(ExternalAIGateway).order_by(ExternalAIGateway.name).all()]}


@router.post("", status_code=201)
def create(body: GatewayCreate, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    if db.get(ExternalGatewayConfig, body.gateway_id):
        raise ApiError(409, "external_gateways.exists", "网关编号已使用，请使用新编号", "Gateway ID is already used; choose a new ID")
    validate_partners(db, body.platform_ids)
    gateway = linked_gateway(db, body.external_gateway_id)
    endpoint = new_endpoint(db, body.gateway_id, body, user.username, kind="gateway")
    row = ExternalGatewayConfig(gateway_id=body.gateway_id, name=gateway.name, endpoint_id=endpoint.endpoint_id,
        enabled=body.enabled, created_by=user.username)
    db.add(row)
    db.commit()
    return response(db, row)


@router.put("/{gateway_id:path}")
def update(gateway_id: str, body: GatewayUpdate, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, gateway_id, body.revision)
    validate_partners(db, body.platform_ids)
    gateway = linked_gateway(db, body.external_gateway_id)
    endpoint = new_endpoint(db, gateway_id, body, user.username, db.get(ExternalDeliveryEndpoint, row.endpoint_id), kind="gateway")
    row.name, row.enabled, row.endpoint_id = gateway.name, body.enabled, endpoint.endpoint_id
    row.revision += 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return response(db, row)


@router.patch("/{gateway_id:path}/state")
def set_state(gateway_id: str, body: CallbackState, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, gateway_id, body.revision)
    if body.enabled:
        endpoint = db.get(ExternalDeliveryEndpoint, row.endpoint_id)
        linked_gateway(db, endpoint.external_gateway_id)
        require_path(endpoint)
    row.enabled = body.enabled
    db.get(ExternalDeliveryEndpoint, row.endpoint_id).enabled = body.enabled
    row.revision += 1
    row.updated_at = datetime.utcnow()
    db.commit()
    return response(db, row)


@router.delete("/{gateway_id:path}")
def delete(gateway_id: str, revision: int = Query(ge=1), db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, gateway_id, revision)
    row.deleted_at = row.updated_at = datetime.utcnow()
    row.enabled = False
    row.revision += 1
    db.commit()
    return {"gateway_id": gateway_id, "deleted": True}


@router.post("/{gateway_id:path}/test", status_code=202)
def test_notification(gateway_id: str, body: GatewayTest, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    delivery.locked(db)
    row = get_config(db, gateway_id, body.revision)
    endpoint = db.get(ExternalDeliveryEndpoint, row.endpoint_id)
    require_path(endpoint)
    linked_gateway(db, endpoint.external_gateway_id)
    platform = db.get(ExternalPlatform, body.platform_id)
    if not row.enabled or not endpoint.enabled or not platform or not platform.enabled:
        raise ApiError(409, "external_gateways.test_disabled", "请先启用网关配置和接入方", "Enable the gateway configuration and integration partner first")
    if body.platform_id not in json.loads(endpoint.platform_ids_json):
        raise ApiError(422, "external_gateways.test_scope", "请选择已授权的接入方", "Select an authorized partner")
    test_id = "gwtest_" + uuid.uuid4().hex
    payload = {"schema_version": "security-gateway-test.v1", "sync_id": "sync_" + test_id,
        "event_type": "gateway.test", "occurred_at": datetime.now(timezone.utc).isoformat(),
        "platform_id": body.platform_id, "gateway_id": gateway_id}
    db.add(ExternalGatewayEvent(task_id=test_id, gateway_id=gateway_id, gateway_version=endpoint.version,
        payload_json=json.dumps(payload), created_by=user.username))
    db.flush()
    delivery.enqueue(db, task_id=test_id)
    item = db.query(ExternalDelivery).filter_by(kind="gateway", task_id=test_id).one()
    db.commit()
    return delivery_response(item)
