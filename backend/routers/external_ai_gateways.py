"""Administration API for external AI gateway connections."""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import auth, models
from ..api_errors import ApiError
from ..external_ai_gateway import gateway_client, delete_binding_remote
from ..security_audit import append_security_audit
from ..security_scan_controls import protect_secret, unprotect_secret
from ..sqlite_db import get_db
from .access_tokens import ensure_token_agent_allowed, resolve_access_token


router = APIRouter(prefix="/v1/external-ai-gateways", tags=["external-ai-gateways"])
runtime_router = APIRouter(prefix="/v1/runtime/external-model", tags=["external-model-runtime"])


class GatewayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    management_base_url: str = Field(min_length=1, max_length=1024)
    model_base_url: str = Field(min_length=1, max_length=1024)
    token_id: str = Field(min_length=1, max_length=255)
    token_value: str = Field(min_length=1, max_length=4096)
    enabled: bool = True


class GatewayUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    management_base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    model_base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    token_id: str | None = Field(default=None, min_length=1, max_length=255)
    token_value: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None


class KeyRevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=4096)


def _base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ApiError(422, "external_gateway.url_invalid", "外部网关地址无效", "The external gateway URL is invalid")
    return normalized


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 8}{value[-4:]}"


def _response(row: models.ExternalAIGateway) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "management_base_url": row.management_base_url,
        "model_base_url": row.model_base_url,
        "token_id": row.token_id,
        "token_value_masked": "********",
        "enabled": row.enabled,
        "last_test_status": row.last_test_status,
        "last_test_error": row.last_test_error,
        "last_tested_at": row.last_tested_at,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row(db: Session, gateway_id: int) -> models.ExternalAIGateway:
    row = db.get(models.ExternalAIGateway, gateway_id)
    if not row:
        raise ApiError(404, "external_gateway.not_found", "外部 AI 网关不存在", "External AI gateway not found")
    return row


def _binding_row(db: Session, gateway_id: int, binding_id: int) -> models.ExternalGatewayAgentBinding:
    row = db.query(models.ExternalGatewayAgentBinding).filter_by(id=binding_id, gateway_id=gateway_id).first()
    if not row:
        raise ApiError(404, "external_gateway.agent_key_not_found", "外部 Agent API Key 记录不存在", "External Agent API key record not found")
    return row


def _binding_response(db: Session, row: models.ExternalGatewayAgentBinding) -> dict:
    agent = db.query(models.ManagedAgent).filter_by(agent_id=row.managed_agent_id).first()
    plain = unprotect_secret(row.api_key_encrypted)
    try:
        available_models = json.loads(row.available_models_json or "[]")
    except (TypeError, ValueError):
        available_models = []
    return {
        "id": row.id,
        "external_agent_id": row.external_agent_id,
        "key_id": row.key_id,
        "api_key_masked": _mask(plain) if plain else "********",
        "managed_agent_id": row.managed_agent_id,
        "managed_agent_name": agent.name if agent else row.managed_agent_id,
        "managed_agent_status": agent.status if agent else None,
        "client_id": row.client_id,
        "status": row.status,
        "model_count": len(available_models) if isinstance(available_models, list) else 0,
        "models_refreshed_at": row.models_refreshed_at,
        "last_synced_at": row.last_synced_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("")
def list_gateways(
    db: Session = Depends(get_db),
    _user: models.User = Depends(auth.get_current_admin_user),
):
    return [_response(row) for row in db.query(models.ExternalAIGateway).order_by(models.ExternalAIGateway.id).all()]


@router.post("")
def create_gateway(
    body: GatewayCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_admin_user),
):
    name = body.name.strip()
    if db.query(models.ExternalAIGateway).filter_by(name=name).first():
        raise ApiError(409, "external_gateway.name_exists", "外部网关名称已存在", "External gateway name already exists")
    row = models.ExternalAIGateway(
        name=name,
        management_base_url=_base_url(body.management_base_url),
        model_base_url=_base_url(body.model_base_url),
        token_id=body.token_id.strip(),
        token_value_encrypted=protect_secret(body.token_value),
        enabled=body.enabled,
        created_by=user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _response(row)


@router.get("/{gateway_id}")
def get_gateway(
    gateway_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(auth.get_current_admin_user),
):
    return _response(_row(db, gateway_id))


@router.get("/{gateway_id}/agent-keys")
def list_agent_keys(
    gateway_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(auth.get_current_admin_user),
):
    _row(db, gateway_id)
    rows = db.query(models.ExternalGatewayAgentBinding).filter_by(gateway_id=gateway_id).order_by(
        models.ExternalGatewayAgentBinding.id.desc()
    ).all()
    return [_binding_response(db, item) for item in rows]


@router.post("/{gateway_id}/agent-keys/{binding_id}/reveal")
def reveal_agent_key(
    gateway_id: int,
    binding_id: int,
    body: KeyRevealRequest,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_admin_user),
):
    binding = _binding_row(db, gateway_id, binding_id)
    if not auth.verify_password(body.password, user.hashed_password):
        append_security_audit(
            event_type="external_gateway.agent_key_reveal_failed",
            actor=user.username,
            resource_type="external_gateway_agent_key",
            resource_id=str(binding.id),
            action="reveal",
            outcome="failure",
            details={"gateway_id": gateway_id, "managed_agent_id": binding.managed_agent_id},
            bind=db.get_bind(),
        )
        raise ApiError(403, "external_gateway.reauthentication_failed", "当前密码验证失败", "Current password verification failed")
    plain = unprotect_secret(binding.api_key_encrypted)
    if not plain:
        raise ApiError(409, "external_gateway.credential_unavailable", "外部 Agent API Key 不可用", "External Agent API key is unavailable")
    append_security_audit(
        event_type="external_gateway.agent_key_revealed",
        actor=user.username,
        resource_type="external_gateway_agent_key",
        resource_id=str(binding.id),
        action="reveal",
        outcome="success",
        details={"gateway_id": gateway_id, "managed_agent_id": binding.managed_agent_id, "key_id": binding.key_id},
        bind=db.get_bind(),
    )
    response.headers["Cache-Control"] = "no-store"
    return {"id": binding.id, "key_id": binding.key_id, "api_key": plain}


@router.put("/{gateway_id}")
def update_gateway(
    gateway_id: int,
    body: GatewayUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(auth.get_current_admin_user),
):
    row = _row(db, gateway_id)
    values = body.model_dump(exclude_unset=True)
    if "name" in values:
        name = values["name"].strip()
        duplicate = db.query(models.ExternalAIGateway).filter(
            models.ExternalAIGateway.name == name, models.ExternalAIGateway.id != gateway_id
        ).first()
        if duplicate:
            raise ApiError(409, "external_gateway.name_exists", "外部网关名称已存在", "External gateway name already exists")
        row.name = name
    for field in ("management_base_url", "model_base_url"):
        if field in values:
            setattr(row, field, _base_url(values[field]))
    if "token_id" in values:
        row.token_id = values["token_id"].strip()
    if values.get("token_value"):
        row.token_value_encrypted = protect_secret(values["token_value"])
    if "enabled" in values:
        row.enabled = values["enabled"]
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _response(row)


@router.post("/{gateway_id}/test")
def test_gateway(
    gateway_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(auth.get_current_admin_user),
):
    row = _row(db, gateway_id)
    management = gateway_client(row).request("GET", "/api/v1/agents/__aitm_connection_test__")
    management_ok = management.status_code in {200, 404}
    try:
        data_response = httpx.get(f"{row.model_base_url.rstrip('/')}/v1/models", timeout=15)
        model_api_ok = data_response.status_code in {200, 401, 403}
        model_api_status = data_response.status_code
    except httpx.RequestError:
        model_api_ok = False
        model_api_status = None
    ok = management_ok and model_api_ok
    row.last_test_status = "success" if ok else "failed"
    row.last_test_error = None if ok else "external_gateway.connection_test_failed"
    row.last_tested_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.commit()
    if not ok:
        raise ApiError(502, "external_gateway.connection_test_failed", "外部 AI 网关连接测试失败", "External AI gateway connection test failed")
    return {
        "ok": True,
        "management_status": management.status_code,
        "model_api_status": model_api_status,
        "tested_at": row.last_tested_at,
    }


@router.delete("/{gateway_id}")
def delete_gateway(
    gateway_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(auth.get_current_admin_user),
):
    row = _row(db, gateway_id)
    if db.query(models.ManagedAgent).filter_by(external_gateway_id=gateway_id).first():
        raise ApiError(
            409,
            "external_gateway.agent_in_use",
            "外部网关仍被平台智能体使用，请先修改智能体的模型来源",
            "The external gateway is still used by a managed Agent",
        )
    defaults = db.query(models.ClientGovernancePolicy).all()
    for policy in defaults:
        try:
            routing = json.loads(policy.model_routing_json or "null") or {}
        except (TypeError, ValueError):
            routing = {}
        if routing.get("external_gateway_id") == gateway_id:
            raise ApiError(
                409,
                "external_gateway.policy_in_use",
                "外部网关仍被客户端策略引用，请先修改策略",
                "The external gateway is still referenced by a client policy",
            )
    bindings = db.query(models.ExternalGatewayAgentBinding).filter_by(gateway_id=gateway_id).all()
    for binding in bindings:
        if binding.status != "deleted":
            delete_binding_remote(db, binding)
        db.delete(binding)
    db.delete(row)
    db.commit()
    return {"ok": True}


@runtime_router.get("/credential")
def resolve_external_model_credential(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    token = resolve_access_token(
        db,
        authorization,
        required_scope="model:chat",
        request=request,
        allowed_token_types={"agent_runtime"},
    )
    agent = ensure_token_agent_allowed(db, token, token.bound_agent_id)
    if (agent.default_model_source or "internal") != "external_gateway" or not agent.external_gateway_id:
        raise ApiError(409, "agent.external_model_not_configured", "智能体未配置外部网关模型", "The Agent has no external gateway model configured")
    gateway = db.get(models.ExternalAIGateway, agent.external_gateway_id)
    if not gateway or not gateway.enabled:
        raise ApiError(409, "external_gateway.not_available", "外部 AI 网关不存在或未启用", "External AI gateway is missing or disabled")
    binding = db.query(models.ExternalGatewayAgentBinding).filter_by(
        gateway_id=gateway.id,
        managed_agent_id=agent.agent_id,
        status="active",
    ).first()
    if not binding:
        raise ApiError(409, "agent.external_binding_required", "智能体没有有效的外部网关身份", "The Agent has no active external gateway identity")
    try:
        allowed_models = json.loads(token.allowed_models_json or "[]")
    except (TypeError, ValueError):
        allowed_models = []
    if allowed_models and agent.default_model not in allowed_models:
        raise ApiError(403, "credential.model_not_allowed", "运行凭证不允许使用该模型", "The runtime credential does not allow this model")
    api_key = unprotect_secret(binding.api_key_encrypted)
    if not api_key:
        raise ApiError(409, "external_gateway.credential_unavailable", "外部 Agent API Key 不可用", "External Agent API key is unavailable")
    append_security_audit(
        event_type="external_gateway.agent_key_resolved",
        actor=agent.agent_id,
        resource_type="external_gateway_agent_key",
        resource_id=str(binding.id),
        action="resolve",
        outcome="success",
        details={"gateway_id": gateway.id, "managed_agent_id": agent.agent_id, "key_id": binding.key_id, "model": agent.default_model},
        bind=db.get_bind(),
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "gateway_id": gateway.id,
        "gateway_name": gateway.name,
        "model_base_url": gateway.model_base_url,
        "model": agent.default_model,
        "protocol": "openai-compatible",
        "external_agent_id": binding.external_agent_id,
        "key_id": binding.key_id,
        "api_key": api_key,
    }
