"""Signed external AI gateway management and model data-plane client."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy.orm import Session

from . import models
from .api_errors import ApiError
from .security_scan_controls import protect_secret, unprotect_secret


EMPTY_MD5_HEX = "d41d8cd98f00b204e9800998ecf8427e"
SIGN_KEYS = {"timestamp", "nonce", "tokenid", "signature"}
BODY_LIMIT = 1 << 20


def canonical_path(raw_path: str) -> str:
    return quote(raw_path, safe="/~")


def canonical_query(raw_query: str) -> str:
    pairs: list[tuple[str, str]] = []
    for pair in raw_query.split("&") if raw_query else []:
        key, _, value = pair.partition("=")
        if key not in SIGN_KEYS:
            pairs.append((key, value))
    return "&".join(f"{key}={value}" for key, value in sorted(pairs))


def body_md5(body: bytes) -> str:
    return hashlib.md5(body).hexdigest() if body else EMPTY_MD5_HEX


def string_to_sign(
    method: str,
    raw_path: str,
    raw_query: str,
    body: bytes,
    timestamp: str,
    nonce: str,
    token_id: str,
) -> str:
    return "\n".join(
        [method.upper(), canonical_path(raw_path), canonical_query(raw_query), timestamp, nonce, token_id, body_md5(body)]
    )


def sign(token_value: str, value: str) -> str:
    return hmac.new(token_value.encode(), value.encode(), hashlib.sha256).hexdigest()


def signed_request_url(url: str, method: str, body: bytes, token_id: str, token_value: str) -> str:
    parsed = urlsplit(url)
    timestamp, nonce = str(int(time.time())), secrets.token_hex(8)
    signature = sign(token_value, string_to_sign(method, parsed.path, parsed.query, body, timestamp, nonce, token_id))
    query = "&".join(part for part in (parsed.query, f"tokenid={quote(token_id, safe='')}",
        f"timestamp={timestamp}", f"nonce={nonce}", f"signature={signature}") if part)
    return parsed._replace(query=query).geturl()


@dataclass
class GatewayResponse:
    status_code: int
    data: dict | list | None
    text: str


class SignedClient:
    def __init__(self, base_url: str, token_id: str, token_value: str, *, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token_id = token_id
        self._token_value = token_value
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict | None = None, query: str = "") -> GatewayResponse:
        wire_path = quote(path, safe="/")
        body = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else b""
        )
        if len(body) > BODY_LIMIT:
            raise ApiError(413, "external_gateway.body_too_large", "外部网关请求体超过 1 MiB", "External gateway request body exceeds 1 MiB")
        url = signed_request_url(f"{self.base_url}{wire_path}" + ("?" + query if query else ""),
                                 method, body, self.token_id, self._token_value)
        headers = {"Content-Type": "application/json"} if body else {}
        try:
            response = httpx.request(
                method.upper(),
                url,
                content=body or None,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.RequestError as exc:
            raise ApiError(502, "external_gateway.unreachable", "无法连接外部 AI 网关", "External AI gateway is unreachable") from exc
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = None
        return GatewayResponse(response.status_code, data, response.text[:2000])

    def _required(self, response: GatewayResponse, expected: set[int], operation: str) -> dict:
        if response.status_code not in expected or not isinstance(response.data, dict):
            raise ApiError(
                502,
                f"external_gateway.{operation}_failed",
                f"外部网关{operation}失败（HTTP {response.status_code}）",
                f"External gateway {operation} failed (HTTP {response.status_code})",
            )
        return response.data

    def register_agent(self, payload: dict) -> dict:
        return self._required(self.request("POST", "/api/v1/agents/register", payload), {200, 201}, "register")

    def get_agent(self, agent_id: str) -> dict:
        return self._required(self.request("GET", f"/api/v1/agents/{agent_id}"), {200}, "query")

    def update_agent(self, agent_id: str, changes: dict) -> dict:
        current = self.get_agent(agent_id)
        payload = {**current, **changes, "id": agent_id, "apiKeys": current.get("apiKeys", [])}
        return self._required(self.request("PUT", f"/api/v1/agents/{agent_id}", payload), {200}, "update")

    def delete_agent(self, agent_id: str) -> dict:
        response = self.request("DELETE", f"/api/v1/agents/{agent_id}")
        if response.status_code in {204, 404}:
            return {"deleted": agent_id, "already_missing": response.status_code == 404}
        return self._required(response, {200}, "delete")


def gateway_client(row: models.ExternalAIGateway) -> SignedClient:
    token_value = unprotect_secret(row.token_value_encrypted)
    if not token_value:
        raise ApiError(409, "external_gateway.credential_unavailable", "外部网关鉴权凭据不可用", "External gateway credential is unavailable")
    return SignedClient(row.management_base_url, row.token_id, token_value)


def fetch_models(row: models.ExternalAIGateway, api_key: str) -> list[dict[str, str]]:
    try:
        response = httpx.get(
            f"{row.model_base_url.rstrip('/')}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
    except httpx.RequestError as exc:
        raise ApiError(502, "external_gateway.model_api_unreachable", "无法连接外部网关模型接口", "External gateway model API is unreachable") from exc
    if response.status_code == 401:
        raise ApiError(502, "external_gateway.api_key_rejected", "外部网关拒绝了 Agent API Key", "The external gateway rejected the Agent API key")
    if response.status_code != 200:
        raise ApiError(502, "external_gateway.models_failed", "获取外部网关模型失败", "Failed to retrieve external gateway models")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiError(502, "external_gateway.models_invalid", "外部网关返回了无效模型列表", "The external gateway returned an invalid model catalog") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ApiError(502, "external_gateway.models_invalid", "外部网关返回了无效模型列表", "The external gateway returned an invalid model catalog")
    result = []
    seen = set()
    for item in data:
        model_id = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
        if model_id and model_id not in seen:
            seen.add(model_id)
            result.append({"id": model_id, "name": model_id})
    return result


def external_agent_id(agent_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent_id).strip("-.") or "agent"
    digest = hashlib.sha256(agent_id.encode()).hexdigest()[:10]
    return f"aitm-{normalized[:80]}-{digest}"


def ensure_binding(
    db: Session,
    gateway: models.ExternalAIGateway,
    agent: models.ManagedAgent,
    *,
    client_id: str | None,
) -> models.ExternalGatewayAgentBinding:
    existing = db.query(models.ExternalGatewayAgentBinding).filter_by(
        gateway_id=gateway.id, managed_agent_id=agent.agent_id
    ).first()
    if existing and existing.status == "active" and unprotect_secret(existing.api_key_encrypted):
        if client_id and not existing.client_id:
            existing.client_id = client_id
        return existing
    payload = {
        "id": existing.external_agent_id if existing else external_agent_id(agent.agent_id),
        "name": agent.name,
        "owner": agent.owner or agent.created_by or "aitm",
        "department": "AITM",
        "permissions": {"tools": []},
        "metadata": {"source": "aitm", "managedAgentId": agent.agent_id, "clientId": client_id or ""},
    }
    registered = gateway_client(gateway).register_agent(payload)
    api_key = str(registered.get("key") or "")
    key_id = str(registered.get("keyId") or "")
    if not api_key or not key_id:
        raise ApiError(502, "external_gateway.register_response_invalid", "外部网关注册响应缺少 Key", "External gateway registration response is missing the key")
    if existing is None:
        existing = models.ExternalGatewayAgentBinding(
            gateway_id=gateway.id,
            client_id=client_id,
            managed_agent_id=agent.agent_id,
            external_agent_id=str(registered.get("id") or payload["id"]),
            key_id=key_id,
            api_key_encrypted=protect_secret(api_key),
        )
        db.add(existing)
    else:
        existing.client_id = client_id or existing.client_id
        existing.external_agent_id = str(registered.get("id") or payload["id"])
        existing.key_id = key_id
        existing.api_key_encrypted = protect_secret(api_key)
        existing.status = "active"
        existing.last_error = None
    existing.last_synced_at = datetime.utcnow()
    existing.updated_at = datetime.utcnow()
    db.flush()
    return existing


def binding_models(db: Session, gateway: models.ExternalAIGateway, binding: models.ExternalGatewayAgentBinding) -> list[dict[str, str]]:
    api_key = unprotect_secret(binding.api_key_encrypted)
    if not api_key:
        binding.status = "error"
        binding.last_error = "external_gateway.credential_unavailable"
        raise ApiError(409, "external_gateway.credential_unavailable", "外部 Agent API Key 不可用", "External Agent API key is unavailable")
    try:
        catalog = fetch_models(gateway, api_key)
    except ApiError as exc:
        binding.status = "error"
        binding.last_error = exc.code
        binding.updated_at = datetime.utcnow()
        db.flush()
        raise
    binding.available_models_json = json.dumps(catalog, ensure_ascii=False)
    binding.models_refreshed_at = datetime.utcnow()
    binding.last_synced_at = datetime.utcnow()
    binding.status = "active"
    binding.last_error = None
    binding.updated_at = datetime.utcnow()
    db.flush()
    return catalog


def delete_binding_remote(db: Session, binding: models.ExternalGatewayAgentBinding) -> None:
    gateway = db.get(models.ExternalAIGateway, binding.gateway_id)
    if gateway:
        gateway_client(gateway).delete_agent(binding.external_agent_id)
    binding.status = "deleted"
    binding.api_key_encrypted = ""
    binding.updated_at = datetime.utcnow()
    db.flush()
