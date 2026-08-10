import hashlib
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from jsonschema import ValidationError, validate
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..config import settings
from ..gateway_skill_context import (
    GatewaySkillAssessment,
    declared_skill_context,
    evaluate_gateway_skill_context,
)
from ..request_leases import LeaseLimitExceeded, acquire_lease, release_lease
from ..security_audit import append_security_audit
from ..sqlite_db import get_db
from .access_tokens import (
    _json_loads,
    acquire_access_token_slot,
    release_access_token_slot,
    resolve_access_token,
)
from .llm_gateway import _mask_secret, _protect_secret, _unprotect_secret


admin_router = APIRouter(prefix="/mcp", tags=["mcp-admin"])
runtime_router = APIRouter(prefix="/mcp", tags=["mcp-gateway"])
MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_MCP_PROTOCOL_VERSIONS = {MCP_PROTOCOL_VERSION, "2025-06-18", "2025-03-26"}
APPROVAL_REQUEST_TTL_SECONDS = 600
MAX_PENDING_APPROVALS_PER_TOKEN = 100
logger = logging.getLogger(__name__)


def _json(value: str | None, default):
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def _validate_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise HTTPException(status_code=400, detail="MCP Endpoint 必须是有效的 HTTP/HTTPS 地址")
    if parsed.scheme == "http" and not settings.MCP_ALLOW_HTTP:
        raise HTTPException(status_code=400, detail="MCP Endpoint 必须使用 HTTPS；开发环境可显式启用 MCP_ALLOW_HTTP")
    if parsed.hostname.lower() == "localhost":
        raise HTTPException(status_code=400, detail="MCP Endpoint 不允许 localhost")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return value
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise HTTPException(status_code=400, detail="MCP Endpoint 不允许环回、链路本地或组播地址")
    return value


def _outbound_allowlist() -> list[str]:
    return [item.strip().lower() for item in settings.MCP_OUTBOUND_ALLOWLIST.split(",") if item.strip()]


def _allowlist_matches(hostname: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None) -> bool:
    hostname = hostname.lower().rstrip(".")
    for item in _outbound_allowlist():
        if item.startswith("*.") and (hostname == item[2:] or hostname.endswith(item[1:])):
            return True
        if item == hostname:
            return True
        if address is not None:
            try:
                if address in ipaddress.ip_network(item, strict=False):
                    return True
            except ValueError:
                pass
    return False


def _address_explicitly_allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    for item in _outbound_allowlist():
        try:
            if address in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    return False


def _validate_resolved_endpoint(endpoint: str) -> list[str]:
    parsed = urlsplit(_validate_endpoint(endpoint))
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"MCP Endpoint DNS 解析失败: {hostname}") from exc
    addresses = sorted({record[4][0] for record in records})
    if not addresses:
        raise HTTPException(status_code=400, detail=f"MCP Endpoint DNS 未返回地址: {hostname}")
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        forbidden = (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        )
        # A hostname allowlist alone must never authorize rebinding to a private
        # address. Private enterprise targets require an explicit IP/CIDR entry.
        if forbidden and not _address_explicitly_allowed(address):
            raise HTTPException(status_code=400, detail=f"MCP Endpoint 解析到不允许的地址: {raw}")
    if _outbound_allowlist() and not any(
        _allowlist_matches(hostname, ipaddress.ip_address(raw)) for raw in addresses
    ):
        raise HTTPException(status_code=400, detail="MCP Endpoint 不在出站白名单中")
    return addresses


def _validate_header(name: str) -> str:
    value = name.strip()
    if not value or any(char in value for char in "\r\n:"):
        raise HTTPException(status_code=400, detail="MCP 鉴权 Header 名称无效")
    return value


def _schema_hash(schema: dict) -> str:
    canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _arguments_hash(arguments: dict) -> str:
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tool_response(row: models.McpTool) -> schemas.McpToolResponse:
    return schemas.McpToolResponse(
        id=row.id,
        server_id=row.server_id,
        name=row.name,
        exposed_name=row.exposed_name,
        description=row.description,
        input_schema=_json(row.input_schema_json, {}),
        schema_hash=row.schema_hash,
        enabled=row.enabled,
        risk_level=row.risk_level,
        rate_limit_per_minute=row.rate_limit_per_minute,
        max_concurrent=row.max_concurrent,
        requires_approval=row.requires_approval,
        discovered_at=row.discovered_at,
    )


def _server_response(db: Session, row: models.McpServer) -> schemas.McpServerResponse:
    tools = db.query(models.McpTool).filter(models.McpTool.server_id == row.id).order_by(models.McpTool.name).all()
    return schemas.McpServerResponse(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        endpoint=row.endpoint,
        authorization_header=row.authorization_header,
        authorization_masked=_mask_secret(row.authorization_value),
        status=row.status,
        health_status=row.health_status,
        timeout_seconds=row.timeout_seconds,
        max_response_kb=row.max_response_kb,
        last_checked_at=row.last_checked_at,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        tools=[_tool_response(tool) for tool in tools],
    )


def _binding_response(db: Session, row: models.McpGatewayBinding) -> schemas.McpGatewayBindingResponse:
    server = db.query(models.McpServer).filter(models.McpServer.id == row.server_id).first()
    return schemas.McpGatewayBindingResponse(
        server_id=row.server_id,
        server_slug=server.slug if server else "",
        server_name=server.name if server else "已删除",
        allowed_tools=_json(row.allowed_tools_json, []),
        approved_schema_hashes=_json(row.approved_schema_hashes_json, {}),
    )


def _gateway_response(db: Session, row: models.McpGateway) -> schemas.McpGatewayResponse:
    bindings = db.query(models.McpGatewayBinding).filter(models.McpGatewayBinding.gateway_id == row.id).all()
    return schemas.McpGatewayResponse(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        status=row.status,
        bindings=[_binding_response(db, binding) for binding in bindings],
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _save_bindings(db: Session, gateway: models.McpGateway, bindings: list[schemas.McpGatewayBindingInput]) -> None:
    db.query(models.McpGatewayBinding).filter(models.McpGatewayBinding.gateway_id == gateway.id).delete()
    for item in bindings:
        server = db.query(models.McpServer).filter(models.McpServer.id == item.server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP Server 不存在: {item.server_id}")
        tools = db.query(models.McpTool).filter(models.McpTool.server_id == server.id, models.McpTool.enabled.is_(True)).all()
        by_name = {tool.name: tool for tool in tools}
        missing = set(item.allowed_tools) - set(by_name)
        if missing:
            raise HTTPException(status_code=400, detail=f"MCP Tool 不存在或已停用: {', '.join(sorted(missing))}")
        names = list(dict.fromkeys(item.allowed_tools))
        db.add(
            models.McpGatewayBinding(
                gateway_id=gateway.id,
                server_id=server.id,
                allowed_tools_json=json.dumps(names, ensure_ascii=False),
                approved_schema_hashes_json=json.dumps(
                    {name: by_name[name].schema_hash for name in names}, ensure_ascii=False
                ),
            )
        )


def _parse_upstream_response(response: httpx.Response, request_id=None) -> dict:
    if response.status_code == 202:
        return {}
    response.raise_for_status()
    if not response.content:
        return {}
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        messages = []
        data_lines = []
        for line in response.text.splitlines():
            if not line:
                if data_lines:
                    messages.append(json.loads("\n".join(data_lines)))
                    data_lines = []
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            messages.append(json.loads("\n".join(data_lines)))
        if request_id is not None:
            match = next((item for item in messages if isinstance(item, dict) and item.get("id") == request_id), None)
            if match is not None:
                return match
        if messages and isinstance(messages[0], dict):
            return messages[0]
        raise ValueError("上游 MCP 返回了空 SSE 响应")
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("上游 MCP 返回格式无效")
    return data


async def _post_upstream(
    server: models.McpServer,
    payload: dict,
    session_id: str | None = None,
    protocol_version: str = MCP_PROTOCOL_VERSION,
) -> tuple[dict, str | None]:
    _validate_resolved_endpoint(server.endpoint)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": protocol_version,
    }
    secret = _unprotect_secret(server.authorization_value)
    if secret:
        headers[server.authorization_header] = secret
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    max_bytes = max(1, int(getattr(server, "max_response_kb", settings.MCP_MAX_RESPONSE_KB) or settings.MCP_MAX_RESPONSE_KB)) * 1024
    async with httpx.AsyncClient(timeout=server.timeout_seconds, follow_redirects=False) as client:
        async with client.stream("POST", server.endpoint, json=payload, headers=headers) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError(f"上游 MCP 响应超过限制: {max_bytes // 1024} KB")
            buffered = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=response.request,
            )
    return _parse_upstream_response(buffered, payload.get("id")), buffered.headers.get("Mcp-Session-Id") or session_id


async def _call_upstream(server: models.McpServer, method: str, params: dict) -> dict:
    # ponytail: initialize per call keeps the MVP stateless; cache sessions only when measured latency requires it.
    request_id = uuid.uuid4().hex
    initialized, session_id = await _post_upstream(
        server,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agent-manager", "version": "0.1.0"},
            },
        },
    )
    if initialized.get("error"):
        return initialized
    protocol_version = initialized.get("result", {}).get("protocolVersion", MCP_PROTOCOL_VERSION)
    if protocol_version not in SUPPORTED_MCP_PROTOCOL_VERSIONS:
        raise ValueError(f"上游 MCP 返回不支持的协议版本: {protocol_version}")
    await _post_upstream(
        server,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        session_id,
        protocol_version,
    )
    result, _ = await _post_upstream(
        server,
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        session_id,
        protocol_version,
    )
    return result


@admin_router.get("/servers", response_model=list[schemas.McpServerResponse])
async def list_servers(db: Session = Depends(get_db)):
    return [_server_response(db, row) for row in db.query(models.McpServer).order_by(models.McpServer.id.desc()).all()]


@admin_router.post("/servers", response_model=schemas.McpServerResponse)
async def create_server(
    body: schemas.McpServerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if db.query(models.McpServer).filter(models.McpServer.slug == body.slug).first():
        raise HTTPException(status_code=400, detail="MCP Server 标识已存在")
    row = models.McpServer(
        slug=body.slug,
        name=body.name.strip(),
        description=body.description,
        endpoint=_validate_endpoint(body.endpoint),
        authorization_header=_validate_header(body.authorization_header),
        authorization_value=_protect_secret(body.authorization_value),
        status=body.status,
        timeout_seconds=body.timeout_seconds,
        max_response_kb=body.max_response_kb,
        created_by=current_user.username,
    )
    if not row.name:
        raise HTTPException(status_code=400, detail="MCP Server 名称不能为空")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _server_response(db, row)


@admin_router.put("/servers/{server_id}", response_model=schemas.McpServerResponse)
async def update_server(server_id: int, body: schemas.McpServerUpdate, db: Session = Depends(get_db)):
    row = db.query(models.McpServer).filter(models.McpServer.id == server_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    data = body.model_dump(exclude_unset=True)
    if "slug" in data and data["slug"] != row.slug:
        raise HTTPException(status_code=400, detail="MCP Server 标识创建后不可修改")
    data.pop("slug", None)
    if "endpoint" in data:
        data["endpoint"] = _validate_endpoint(data["endpoint"])
    if "authorization_header" in data:
        data["authorization_header"] = _validate_header(data["authorization_header"])
    if "authorization_value" in data:
        value = data.pop("authorization_value")
        if value is not None:
            row.authorization_value = _protect_secret(value) if value else None
    if "name" in data and not data["name"].strip():
        raise HTTPException(status_code=400, detail="MCP Server 名称不能为空")
    for field, value in data.items():
        setattr(row, field, value.strip() if field == "name" else value)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _server_response(db, row)


@admin_router.delete("/servers/{server_id}")
async def delete_server(server_id: int, db: Session = Depends(get_db)):
    row = db.query(models.McpServer).filter(models.McpServer.id == server_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    if db.query(models.McpGatewayBinding).filter(models.McpGatewayBinding.server_id == server_id).first():
        raise HTTPException(status_code=400, detail="请先从 MCP 网关中移除该 Server")
    db.query(models.McpTool).filter(models.McpTool.server_id == server_id).delete()
    db.delete(row)
    db.commit()
    return {"ok": True}


@admin_router.post("/servers/{server_id}/discover", response_model=schemas.McpServerResponse)
async def discover_server(server_id: int, db: Session = Depends(get_db)):
    row = db.query(models.McpServer).filter(models.McpServer.id == server_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP Server 不存在")
    try:
        response = await _call_upstream(row, "tools/list", {})
        if response.get("error"):
            raise ValueError(response["error"].get("message", "上游 MCP 返回错误"))
        tools = response.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise ValueError("上游 tools/list 返回格式无效")
        existing = {
            tool.name: tool
            for tool in db.query(models.McpTool).filter(models.McpTool.server_id == row.id).all()
        }
        discovered = set()
        for item in tools:
            name = str(item.get("name", "")).strip()
            schema = item.get("inputSchema") or {}
            if not name or len(name) > 255 or len(f"{row.slug}__{name}") > 384 or not isinstance(schema, dict):
                continue
            discovered.add(name)
            tool = existing.get(name) or models.McpTool(
                server_id=row.id,
                name=name,
                exposed_name=f"{row.slug}__{name}",
            )
            tool.description = item.get("description")
            tool.input_schema_json = json.dumps(schema, ensure_ascii=False)
            tool.schema_hash = _schema_hash(schema)
            tool.enabled = True
            tool.discovered_at = datetime.utcnow()
            db.add(tool)
        for name, tool in existing.items():
            if name not in discovered:
                tool.enabled = False
        row.health_status = "healthy"
        row.last_checked_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        return _server_response(db, row)
    except Exception as exc:
        db.rollback()
        row = db.query(models.McpServer).filter(models.McpServer.id == server_id).first()
        row.health_status = "unhealthy"
        row.last_checked_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail=f"MCP Server 连接失败: {exc}") from exc


@admin_router.get("/gateways", response_model=list[schemas.McpGatewayResponse])
async def list_gateways(db: Session = Depends(get_db)):
    return [_gateway_response(db, row) for row in db.query(models.McpGateway).order_by(models.McpGateway.id.desc()).all()]


@admin_router.put("/tools/{tool_id}/policy", response_model=schemas.McpToolResponse)
async def update_tool_policy(
    tool_id: int,
    body: schemas.McpToolPolicyUpdate,
    db: Session = Depends(get_db),
):
    tool = db.query(models.McpTool).filter(models.McpTool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="MCP Tool 不存在")
    tool.risk_level = body.risk_level
    tool.rate_limit_per_minute = body.rate_limit_per_minute
    tool.max_concurrent = body.max_concurrent
    tool.requires_approval = body.requires_approval or body.risk_level == "high"
    db.commit()
    db.refresh(tool)
    return _tool_response(tool)


@admin_router.post("/approvals", response_model=schemas.McpToolApprovalResponse)
async def create_tool_approval(
    body: schemas.McpToolApprovalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    token = db.query(models.AccessToken).filter(
        models.AccessToken.id == body.token_id,
        models.AccessToken.token_type == "mcp_gateway",
        models.AccessToken.status == "active",
    ).first()
    if not token:
        raise HTTPException(status_code=404, detail="MCP 接入凭证不存在或未启用")
    gateway = db.query(models.McpGateway).filter(
        models.McpGateway.slug == body.gateway_slug,
        models.McpGateway.status == "active",
    ).first()
    if not gateway:
        raise HTTPException(status_code=404, detail="MCP 网关不存在或未启用")
    match = next((item for item in _gateway_tools(db, gateway) if item[1].exposed_name == body.tool_name), None)
    if not match:
        raise HTTPException(status_code=404, detail="MCP Tool 未在网关中授权")
    tool = match[1]
    if not tool.requires_approval:
        raise HTTPException(status_code=400, detail="该 MCP Tool 不需要高风险审批")
    allowed_gateways = _json_loads(token.allowed_mcp_gateways_json, [])
    if body.gateway_slug not in allowed_gateways:
        raise HTTPException(status_code=403, detail="凭证未授权访问该 MCP 网关")
    plain = "mcpap_" + secrets.token_urlsafe(24)
    expires_at = datetime.utcnow() + timedelta(seconds=body.ttl_seconds)
    db.add(models.McpToolApproval(
        approval_hash=hashlib.sha256(plain.encode("utf-8")).hexdigest(),
        token_id=token.id,
        gateway_slug=gateway.slug,
        tool_name=tool.exposed_name,
        arguments_hash=_arguments_hash(body.arguments),
        expires_at=expires_at,
        created_by=current_user.username,
    ))
    db.commit()
    return schemas.McpToolApprovalResponse(approval_token=plain, expires_at=expires_at)


_SENSITIVE_ARGUMENT_PARTS = (
    "password", "passwd", "secret", "token", "authorization", "api_key",
    "apikey", "access_key", "private_key", "credential",
)


def _mask_approval_arguments(value, key: str = ""):
    normalized_key = key.lower().replace("-", "_")
    if key and any(part in normalized_key for part in _SENSITIVE_ARGUMENT_PARTS):
        return "******"
    if isinstance(value, dict):
        return {str(item_key): _mask_approval_arguments(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_mask_approval_arguments(item) for item in value]
    return value


def _approval_arguments(row: models.McpToolApproval) -> dict:
    decrypted = _unprotect_secret(row.arguments_encrypted)
    return _json(decrypted, {}) if decrypted else {}


def _append_approval_audit(
    db: Session,
    row: models.McpToolApproval,
    event_type: str,
    actor: str,
    action: str,
    outcome: str = "success",
) -> None:
    try:
        append_security_audit(
            event_type=event_type,
            actor=actor,
            resource_type="mcp_approval_request",
            resource_id=row.request_id or str(row.id),
            action=action,
            outcome=outcome,
            details={
                "token_id": row.token_id,
                "gateway_slug": row.gateway_slug,
                "server_slug": row.server_slug,
                "tool_name": row.tool_name,
                "arguments_hash": row.arguments_hash,
                "schema_hash": row.schema_hash,
                "status": row.status,
            },
            bind=db.get_bind(),
        )
    except Exception:
        logger.exception("Failed to append MCP approval audit event for %s", row.request_id or row.id)


def _expire_approval_requests(db: Session) -> None:
    now = datetime.utcnow()
    rows = db.query(models.McpToolApproval).filter(
        models.McpToolApproval.request_id.is_not(None),
        models.McpToolApproval.status.in_(["pending", "approved"]),
        models.McpToolApproval.expires_at < now,
    ).all()
    if not rows:
        return
    for row in rows:
        row.status = "expired"
    db.commit()
    for row in rows:
        _append_approval_audit(db, row, "mcp.approval.expired", "system", "expire")


def _approval_request_response(
    db: Session,
    row: models.McpToolApproval,
    *,
    reveal_arguments: bool = False,
) -> schemas.McpApprovalRequestResponse:
    token = db.query(models.AccessToken).filter(models.AccessToken.id == row.token_id).first()
    gateway = db.query(models.McpGateway).filter(models.McpGateway.slug == row.gateway_slug).first()
    tool = db.query(models.McpTool).filter(models.McpTool.id == row.tool_id).first() if row.tool_id else None
    arguments = _approval_arguments(row)
    return schemas.McpApprovalRequestResponse(
        request_id=row.request_id or "",
        token_id=row.token_id,
        token_name=token.name if token else f"Token #{row.token_id}",
        token_prefix=token.token_prefix if token else "",
        gateway_slug=row.gateway_slug,
        gateway_name=gateway.name if gateway else None,
        server_slug=row.server_slug,
        tool_id=row.tool_id,
        tool_name=row.tool_name,
        tool_description=tool.description if tool else None,
        risk_level=tool.risk_level if tool else "high",
        schema_hash=row.schema_hash,
        current_schema_hash=tool.schema_hash if tool else None,
        schema_changed=bool(tool and row.schema_hash and tool.schema_hash != row.schema_hash),
        arguments=arguments if reveal_arguments else _mask_approval_arguments(arguments),
        arguments_revealed=reveal_arguments,
        client_ip=row.client_ip,
        status=row.status,
        expires_at=row.expires_at,
        created_by=row.created_by,
        created_at=row.created_at,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        review_comment=row.review_comment,
        used_at=row.used_at,
        use_count=row.use_count or 0,
        first_used_at=row.first_used_at,
        last_used_at=row.last_used_at,
    )


@admin_router.get("/approval-requests/stats", response_model=schemas.McpApprovalRequestStatsResponse)
async def approval_request_stats(db: Session = Depends(get_db)):
    _expire_approval_requests(db)
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    query = db.query(models.McpToolApproval).filter(models.McpToolApproval.request_id.is_not(None))
    return schemas.McpApprovalRequestStatsResponse(
        pending=query.filter(models.McpToolApproval.status == "pending").count(),
        approved_today=query.filter(
            models.McpToolApproval.status.in_(["approved", "used", "expired"]),
            models.McpToolApproval.reviewed_at >= today,
        ).count(),
        rejected_today=query.filter(
            models.McpToolApproval.status == "rejected",
            models.McpToolApproval.reviewed_at >= today,
        ).count(),
        expired=query.filter(models.McpToolApproval.status == "expired").count(),
    )


@admin_router.get("/approval-requests", response_model=schemas.McpApprovalRequestListResponse)
async def list_approval_requests(
    status: str | None = None,
    gateway_slug: str | None = None,
    tool_name: str | None = None,
    token_name: str | None = None,
    token_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    _expire_approval_requests(db)
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    query = db.query(models.McpToolApproval).outerjoin(
        models.AccessToken, models.AccessToken.id == models.McpToolApproval.token_id
    ).filter(models.McpToolApproval.request_id.is_not(None))
    if status:
        statuses = [item.strip() for item in status.split(",") if item.strip()]
        if statuses:
            query = query.filter(models.McpToolApproval.status.in_(statuses))
    if gateway_slug:
        query = query.filter(models.McpToolApproval.gateway_slug == gateway_slug)
    if tool_name:
        query = query.filter(models.McpToolApproval.tool_name.ilike(f"%{tool_name.strip()}%"))
    if token_name:
        query = query.filter(models.AccessToken.name.ilike(f"%{token_name.strip()}%"))
    if token_id is not None:
        query = query.filter(models.McpToolApproval.token_id == token_id)
    if created_from:
        query = query.filter(models.McpToolApproval.created_at >= created_from)
    if created_to:
        query = query.filter(models.McpToolApproval.created_at <= created_to)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            models.McpToolApproval.request_id.ilike(pattern),
            models.McpToolApproval.tool_name.ilike(pattern),
            models.McpToolApproval.gateway_slug.ilike(pattern),
            models.AccessToken.name.ilike(pattern),
        ))
    total = query.count()
    rows = query.order_by(models.McpToolApproval.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.McpApprovalRequestListResponse(
        items=[_approval_request_response(db, row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@admin_router.get("/approval-requests/{request_id}", response_model=schemas.McpApprovalRequestResponse)
async def get_approval_request(
    request_id: str,
    reveal_arguments: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    _expire_approval_requests(db)
    row = db.query(models.McpToolApproval).filter(models.McpToolApproval.request_id == request_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP 审批申请不存在")
    if reveal_arguments:
        _append_approval_audit(db, row, "mcp.approval.arguments_revealed", current_user.username, "read")
    return _approval_request_response(db, row, reveal_arguments=reveal_arguments)


def _reviewable_approval_request(db: Session, request_id: str) -> models.McpToolApproval:
    _expire_approval_requests(db)
    row = db.query(models.McpToolApproval).filter(models.McpToolApproval.request_id == request_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP 审批申请不存在")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="MCP 审批申请已被处理或已过期")
    return row


@admin_router.post("/approval-requests/{request_id}/approve", response_model=schemas.McpApprovalRequestResponse)
async def approve_approval_request(
    request_id: str,
    body: schemas.McpApprovalRequestReview,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _reviewable_approval_request(db, request_id)
    token = db.query(models.AccessToken).filter(
        models.AccessToken.id == row.token_id,
        models.AccessToken.token_type == "mcp_gateway",
        models.AccessToken.status == "active",
    ).first()
    gateway = db.query(models.McpGateway).filter(
        models.McpGateway.slug == row.gateway_slug,
        models.McpGateway.status == "active",
    ).first()
    tool = db.query(models.McpTool).filter(
        models.McpTool.id == row.tool_id,
        models.McpTool.enabled.is_(True),
    ).first()
    if not token or (token.expires_at and token.expires_at < datetime.utcnow()):
        raise HTTPException(status_code=409, detail="MCP 接入凭证已失效，不能批准")
    if not gateway:
        raise HTTPException(status_code=409, detail="MCP 网关已停用，不能批准")
    match = next((item for item in _gateway_tools(db, gateway) if item[1].id == row.tool_id), None)
    if not tool or not match or not tool.requires_approval:
        raise HTTPException(status_code=409, detail="MCP Tool 已停用、移除或不再需要审批")
    if tool.schema_hash != row.schema_hash or match[2] != tool.schema_hash:
        raise HTTPException(status_code=409, detail="MCP Tool Schema 已变化，需要重新发起调用")
    if row.gateway_slug not in _json_loads(token.allowed_mcp_gateways_json, []):
        raise HTTPException(status_code=409, detail="MCP 接入凭证不再允许访问该网关")
    now = datetime.utcnow()
    updated = db.query(models.McpToolApproval).filter(
        models.McpToolApproval.id == row.id,
        models.McpToolApproval.status == "pending",
    ).update({
        "status": "approved",
        "expires_at": now + timedelta(seconds=body.ttl_seconds),
        "reviewed_by": current_user.username,
        "reviewed_at": now,
        "review_comment": body.comment,
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="MCP 审批申请已被其他管理员处理")
    db.commit()
    db.refresh(row)
    _append_approval_audit(db, row, "mcp.approval.approved", current_user.username, "approve")
    return _approval_request_response(db, row)


@admin_router.post("/approval-requests/{request_id}/reject", response_model=schemas.McpApprovalRequestResponse)
async def reject_approval_request(
    request_id: str,
    body: schemas.McpApprovalRequestReject,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _reviewable_approval_request(db, request_id)
    now = datetime.utcnow()
    updated = db.query(models.McpToolApproval).filter(
        models.McpToolApproval.id == row.id,
        models.McpToolApproval.status == "pending",
    ).update({
        "status": "rejected",
        "reviewed_by": current_user.username,
        "reviewed_at": now,
        "review_comment": body.reason.strip(),
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="MCP 审批申请已被其他管理员处理")
    db.commit()
    db.refresh(row)
    _append_approval_audit(db, row, "mcp.approval.rejected", current_user.username, "reject")
    return _approval_request_response(db, row)


@admin_router.post("/gateways", response_model=schemas.McpGatewayResponse)
async def create_gateway(
    body: schemas.McpGatewayCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if db.query(models.McpGateway).filter(models.McpGateway.slug == body.slug).first():
        raise HTTPException(status_code=400, detail="MCP 网关标识已存在")
    row = models.McpGateway(
        slug=body.slug,
        name=body.name.strip(),
        description=body.description,
        status=body.status,
        created_by=current_user.username,
    )
    if not row.name:
        raise HTTPException(status_code=400, detail="MCP 网关名称不能为空")
    db.add(row)
    db.flush()
    _save_bindings(db, row, body.bindings)
    db.commit()
    db.refresh(row)
    return _gateway_response(db, row)


@admin_router.put("/gateways/{gateway_id}", response_model=schemas.McpGatewayResponse)
async def update_gateway(gateway_id: int, body: schemas.McpGatewayUpdate, db: Session = Depends(get_db)):
    row = db.query(models.McpGateway).filter(models.McpGateway.id == gateway_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP 网关不存在")
    data = body.model_dump(exclude_unset=True)
    if "slug" in data and data["slug"] != row.slug:
        raise HTTPException(status_code=400, detail="MCP 网关标识创建后不可修改")
    data.pop("slug", None)
    bindings = data.pop("bindings", None)
    if "name" in data and not data["name"].strip():
        raise HTTPException(status_code=400, detail="MCP 网关名称不能为空")
    for field, value in data.items():
        setattr(row, field, value.strip() if field == "name" else value)
    if bindings is not None:
        _save_bindings(db, row, [schemas.McpGatewayBindingInput(**item) for item in bindings])
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _gateway_response(db, row)


@admin_router.delete("/gateways/{gateway_id}")
async def delete_gateway(gateway_id: int, db: Session = Depends(get_db)):
    row = db.query(models.McpGateway).filter(models.McpGateway.id == gateway_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP 网关不存在")
    db.query(models.McpGatewayBinding).filter(models.McpGatewayBinding.gateway_id == gateway_id).delete()
    db.delete(row)
    db.commit()
    return {"ok": True}


@admin_router.get("/audit", response_model=list[schemas.McpCallAuditResponse])
async def list_audit(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(models.McpCallAudit).order_by(models.McpCallAudit.id.desc()).limit(min(max(limit, 1), 500)).all()
    return [
        schemas.McpCallAuditResponse(
            id=row.id,
            request_id=row.request_id,
            token_id=row.token_id,
            gateway_slug=row.gateway_slug,
            server_slug=row.server_slug,
            tool_name=row.tool_name,
            schema_hash=row.schema_hash,
            approval_request_id=row.approval_request_id,
            agent_id=row.agent_id,
            skill_id=row.skill_id,
            skill_version_id=row.skill_version_id,
            skill_name=row.skill_name,
            skill_context_source=row.skill_context_source,
            skill_trust_state=row.skill_trust_state,
            skill_alert_severity=row.skill_alert_severity,
            skill_alert_codes=_json(row.skill_alert_codes_json, []),
            status=row.status,
            duration_ms=row.duration_ms,
            error=row.error,
            created_at=row.created_at,
        )
        for row in rows
    ]


@admin_router.post("/debug/upstream")
async def debug_upstream(body: schemas.McpUpstreamDebugRequest, db: Session = Depends(get_db)):
    stored = None
    if body.server_id is not None:
        stored = db.query(models.McpServer).filter(models.McpServer.id == body.server_id).first()
        if not stored:
            raise HTTPException(status_code=404, detail="MCP Server 不存在")
    if not body.endpoint and not stored:
        raise HTTPException(status_code=400, detail="请填写 MCP Endpoint")

    endpoint = _validate_endpoint(body.endpoint or stored.endpoint)
    same_endpoint = bool(stored and endpoint == stored.endpoint)
    header = _validate_header(body.authorization_header or (stored.authorization_header if stored else "Authorization"))
    if body.authorization_value is not None:
        protected_secret = _protect_secret(body.authorization_value) if body.authorization_value else None
    else:
        protected_secret = stored.authorization_value if same_endpoint else None

    transient = models.McpServer(
        slug=stored.slug if stored else "debug",
        name=stored.name if stored else "MCP Debug",
        endpoint=endpoint,
        authorization_header=header,
        authorization_value=protected_secret,
        timeout_seconds=body.timeout_seconds,
    )
    started = time.perf_counter()
    try:
        result = await _call_upstream(transient, body.method, body.params)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MCP 调试失败: {exc}") from exc
    return {
        "endpoint": endpoint,
        "method": body.method,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "response": result,
    }


def _gateway_tools(db: Session, gateway: models.McpGateway) -> list[tuple[models.McpServer, models.McpTool, str]]:
    result = []
    bindings = db.query(models.McpGatewayBinding).filter(models.McpGatewayBinding.gateway_id == gateway.id).all()
    for binding in bindings:
        server = db.query(models.McpServer).filter(
            models.McpServer.id == binding.server_id,
            models.McpServer.status == "active",
        ).first()
        if not server:
            continue
        approved = _json(binding.approved_schema_hashes_json, {})
        names = _json(binding.allowed_tools_json, [])
        tools = db.query(models.McpTool).filter(
            models.McpTool.server_id == server.id,
            models.McpTool.name.in_(names),
            models.McpTool.enabled.is_(True),
        ).all()
        result.extend((server, tool, approved.get(tool.name, "")) for tool in tools)
    return result


def _jsonrpc_error(request_id, code: int, message: str, data=None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _record_denied_call(
    db: Session,
    token: models.AccessToken,
    gateway_slug: str,
    tool_name: str,
    error: str,
    *,
    server_slug: str | None = None,
    schema_hash: str | None = None,
    approval_request_id: str | None = None,
    skill_assessment: GatewaySkillAssessment | None = None,
) -> None:
    db.add(
        models.McpCallAudit(
            request_id=uuid.uuid4().hex,
            token_id=token.id,
            gateway_slug=gateway_slug,
            server_slug=server_slug[:128] if server_slug else None,
            tool_name=tool_name[:255] or None,
            schema_hash=schema_hash,
            approval_request_id=approval_request_id,
            **(skill_assessment or GatewaySkillAssessment()).audit_fields(),
            status="denied",
            duration_ms=0,
            error=error[:1000],
        )
    )
    db.commit()


def _ensure_approval_request(
    db: Session,
    *,
    token: models.AccessToken,
    gateway_slug: str,
    server: models.McpServer,
    tool: models.McpTool,
    arguments: dict,
    client_ip: str | None,
) -> tuple[models.McpToolApproval | None, str | None]:
    _expire_approval_requests(db)
    arguments_hash = _arguments_hash(arguments)
    existing = db.query(models.McpToolApproval).filter(
        models.McpToolApproval.request_id.is_not(None),
        models.McpToolApproval.token_id == token.id,
        models.McpToolApproval.gateway_slug == gateway_slug,
        models.McpToolApproval.tool_id == tool.id,
        models.McpToolApproval.schema_hash == tool.schema_hash,
        models.McpToolApproval.status == "pending",
        models.McpToolApproval.expires_at > datetime.utcnow(),
    ).order_by(models.McpToolApproval.id.desc()).first()
    if existing:
        return existing, None
    pending_count = db.query(models.McpToolApproval).filter(
        models.McpToolApproval.token_id == token.id,
        models.McpToolApproval.request_id.is_not(None),
        models.McpToolApproval.status == "pending",
    ).count()
    if pending_count >= MAX_PENDING_APPROVALS_PER_TOKEN:
        return None, "该 MCP 凭证的待审批申请数量已达上限"
    row = models.McpToolApproval(
        approval_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        request_id="mcpapr_" + uuid.uuid4().hex,
        token_id=token.id,
        gateway_slug=gateway_slug,
        server_slug=server.slug,
        tool_id=tool.id,
        tool_name=tool.exposed_name,
        schema_hash=tool.schema_hash,
        arguments_hash=arguments_hash,
        arguments_encrypted=_protect_secret(json.dumps(arguments, ensure_ascii=False, sort_keys=True)),
        client_ip=client_ip,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(seconds=APPROVAL_REQUEST_TTL_SECONDS),
        created_by=f"mcp-token:{token.id}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _append_approval_audit(db, row, "mcp.approval.requested", f"mcp-token:{token.id}", "request")
    return row, None


def _approval_error_data(row: models.McpToolApproval) -> dict:
    return {
        "approval_required": True,
        "approval_request_id": row.request_id,
        "status": row.status,
        "expires_at": row.expires_at.isoformat(),
    }


def _record_approval_request_use(db: Session, row: models.McpToolApproval) -> bool:
    now = datetime.utcnow()
    updated = db.query(models.McpToolApproval).filter(
        models.McpToolApproval.id == row.id,
        models.McpToolApproval.status == "approved",
        models.McpToolApproval.expires_at > now,
    ).update({
        "use_count": models.McpToolApproval.use_count + 1,
        "first_used_at": func.coalesce(models.McpToolApproval.first_used_at, now),
        "last_used_at": now,
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        return False
    db.commit()
    db.refresh(row)
    _append_approval_audit(db, row, "mcp.approval.used", f"mcp-token:{row.token_id}", "authorize")
    return True


def _approved_tool_authorization(
    db: Session,
    *,
    token: models.AccessToken,
    gateway_slug: str,
    tool: models.McpTool,
) -> models.McpToolApproval | None:
    _expire_approval_requests(db)
    return db.query(models.McpToolApproval).filter(
        models.McpToolApproval.request_id.is_not(None),
        models.McpToolApproval.token_id == token.id,
        models.McpToolApproval.gateway_slug == gateway_slug,
        models.McpToolApproval.tool_id == tool.id,
        models.McpToolApproval.schema_hash == tool.schema_hash,
        models.McpToolApproval.status == "approved",
        models.McpToolApproval.expires_at > datetime.utcnow(),
    ).order_by(
        models.McpToolApproval.reviewed_at.desc(),
        models.McpToolApproval.id.desc(),
    ).first()


def _consume_tool_approval(
    db: Session,
    *,
    token: models.AccessToken,
    gateway_slug: str,
    server: models.McpServer,
    tool: models.McpTool,
    arguments: dict,
    approval_token: str | None,
    approval_request_id: str | None,
    client_ip: str | None,
) -> tuple[str | None, dict | None, str | None]:
    if not tool.requires_approval:
        return None, None, None
    _expire_approval_requests(db)
    if approval_request_id:
        row = db.query(models.McpToolApproval).filter(
            models.McpToolApproval.request_id == approval_request_id,
            models.McpToolApproval.token_id == token.id,
            models.McpToolApproval.gateway_slug == gateway_slug,
            models.McpToolApproval.tool_name == tool.exposed_name,
        ).first()
        if not row:
            return "高风险 Tool 审批申请无效", None, approval_request_id
        if row.status in {"pending", "approved"} and row.expires_at < datetime.utcnow():
            row.status = "expired"
            db.commit()
            _append_approval_audit(db, row, "mcp.approval.expired", "system", "expire")
        if row.status == "pending":
            return "MCP Tool 调用等待管理员审批", _approval_error_data(row), row.request_id
        if row.status == "rejected":
            data = _approval_error_data(row)
            data["reason"] = row.review_comment
            return "MCP Tool 调用已被管理员拒绝", data, row.request_id
        if row.status == "expired":
            return "高风险 Tool 审批申请已过期", _approval_error_data(row), row.request_id
        if row.status == "used":
            return "高风险 Tool 审批申请已被使用", _approval_error_data(row), row.request_id
        if row.status != "approved":
            return "高风险 Tool 审批申请状态无效", _approval_error_data(row), row.request_id
        if row.schema_hash != tool.schema_hash:
            return "高风险 Tool 审批时的 Schema 已变化", _approval_error_data(row), row.request_id
        if not _record_approval_request_use(db, row):
            _expire_approval_requests(db)
            return "高风险 Tool 审批申请已过期", _approval_error_data(row), row.request_id
        return None, None, row.request_id
    approved = _approved_tool_authorization(
        db,
        token=token,
        gateway_slug=gateway_slug,
        tool=tool,
    )
    if approved:
        if not _record_approval_request_use(db, approved):
            _expire_approval_requests(db)
            return "高风险 Tool 审批申请已过期", _approval_error_data(approved), approved.request_id
        return None, None, approved.request_id
    if approval_token:
        approval_hash = hashlib.sha256(approval_token.encode("utf-8")).hexdigest()
        row = db.query(models.McpToolApproval).filter(
            models.McpToolApproval.approval_hash == approval_hash,
            models.McpToolApproval.token_id == token.id,
            models.McpToolApproval.gateway_slug == gateway_slug,
            models.McpToolApproval.tool_name == tool.exposed_name,
            models.McpToolApproval.status == "active",
        ).first()
        if not row or row.expires_at < datetime.utcnow():
            return "高风险 Tool 审批凭证无效或已过期", None, None
        if row.arguments_hash != _arguments_hash(arguments):
            return "高风险 Tool 审批参数与调用参数不一致", None, None
        consumed = db.query(models.McpToolApproval).filter(
            models.McpToolApproval.id == row.id,
            models.McpToolApproval.status == "active",
        ).update({"status": "used", "used_at": datetime.utcnow()}, synchronize_session=False)
        if consumed != 1:
            db.rollback()
            return "高风险 Tool 审批凭证已被使用", None, None
        db.commit()
        return None, None, None
    row, create_error = _ensure_approval_request(
        db,
        token=token,
        gateway_slug=gateway_slug,
        server=server,
        tool=tool,
        arguments=arguments,
        client_ip=client_ip,
    )
    if create_error:
        return create_error, None, None
    return "MCP Tool 调用等待管理员审批", _approval_error_data(row), row.request_id


def _tool_rate_limit_exceeded(db: Session, tool: models.McpTool) -> bool:
    since = datetime.utcnow() - timedelta(minutes=1)
    count = db.query(models.McpCallAudit).filter(
        models.McpCallAudit.server_slug == tool.exposed_name.partition("__")[0],
        models.McpCallAudit.tool_name == tool.name,
        models.McpCallAudit.created_at >= since,
        models.McpCallAudit.status.in_(["running", "success", "error"]),
    ).count()
    return count >= max(1, tool.rate_limit_per_minute)


@runtime_router.get(
    "/{gateway_slug}/approvals/{request_id}",
    response_model=schemas.McpApprovalRuntimeStatusResponse,
)
async def get_runtime_approval_status(
    gateway_slug: str,
    request_id: str,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = resolve_access_token(
        db,
        authorization,
        required_scope="mcp:call-tools",
        request=request,
        allowed_token_types={"mcp_gateway"},
    )
    row = db.query(models.McpToolApproval).filter(
        models.McpToolApproval.request_id == request_id,
        models.McpToolApproval.token_id == token.id,
        models.McpToolApproval.gateway_slug == gateway_slug,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="MCP 审批申请不存在")
    if row.status in {"pending", "approved"} and row.expires_at < datetime.utcnow():
        row.status = "expired"
        db.commit()
        _append_approval_audit(db, row, "mcp.approval.expired", "system", "expire")
    return schemas.McpApprovalRuntimeStatusResponse(
        request_id=row.request_id,
        status=row.status,
        expires_at=row.expires_at,
        review_comment=row.review_comment if row.status == "rejected" else None,
    )


@runtime_router.post("/{gateway_slug}")
async def invoke_gateway(
    gateway_slug: str,
    body: dict,
    request: Request,
    response: Response,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _jsonrpc_error(body.get("id"), -32600, "Invalid Request")
    method = body.get("method")
    request_id = body.get("id")
    required_scope = {
        "initialize": "mcp:connect",
        "notifications/initialized": "mcp:connect",
        "ping": "mcp:connect",
        "tools/list": "mcp:list-tools",
        "tools/call": "mcp:call-tools",
    }.get(method)
    if not required_scope:
        return _jsonrpc_error(request_id, -32601, "Method not found")
    token = resolve_access_token(
        db,
        authorization,
        required_scope=required_scope,
        request=request,
        allowed_token_types={"mcp_gateway"},
    )
    allowed_gateways = _json_loads(token.allowed_mcp_gateways_json, [])
    if gateway_slug not in allowed_gateways:
        raise HTTPException(status_code=403, detail="凭证未授权访问该 MCP 网关")
    gateway = db.query(models.McpGateway).filter(
        models.McpGateway.slug == gateway_slug,
        models.McpGateway.status == "active",
    ).first()
    if not gateway:
        raise HTTPException(status_code=404, detail="MCP 网关不存在或未启用")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname != request.url.hostname:
        raise HTTPException(status_code=403, detail="Origin 不允许访问 MCP 网关")
    size = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    if size > token.max_body_kb * 1024:
        raise HTTPException(status_code=413, detail="请求体超过凭证限制")
    if method == "notifications/initialized":
        response.status_code = 202
        return None
    if method == "initialize":
        requested_version = (body.get("params") or {}).get("protocolVersion")
        protocol_version = requested_version if requested_version in SUPPORTED_MCP_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"agent-manager/{gateway.slug}", "version": "0.1.0"},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    tools = _gateway_tools(db, gateway)
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": tool.exposed_name,
                        "description": tool.description,
                        "inputSchema": _json(tool.input_schema_json, {}),
                    }
                    for _server, tool, approved_hash in tools
                    if approved_hash == tool.schema_hash
                ]
            },
        }

    params = body.get("params") or {}
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params")
    call_meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    declared_skill = declared_skill_context(call_meta)
    manager = None
    if any(declared_skill.values()):
        from agent_manager.api.router import get_manager

        manager = get_manager()
    skill_assessment = evaluate_gateway_skill_context(
        db,
        token,
        call_meta,
        manager=manager,
        source="mcp_meta",
    )
    exposed_name = str(params.get("name", ""))
    match = next((item for item in tools if item[1].exposed_name == exposed_name), None)
    if not match:
        _record_denied_call(
            db,
            token,
            gateway.slug,
            exposed_name,
            "Tool 未授权或不存在",
            server_slug=exposed_name.partition("__")[0] or None,
            skill_assessment=skill_assessment,
        )
        return _jsonrpc_error(request_id, -32602, "Tool 未授权或不存在")
    server, tool, approved_hash = match
    if approved_hash != tool.schema_hash:
        _record_denied_call(
            db,
            token,
            gateway.slug,
            tool.name,
            "Tool Schema 已变化，需要重新审核",
            server_slug=server.slug,
            schema_hash=tool.schema_hash,
            skill_assessment=skill_assessment,
        )
        return _jsonrpc_error(request_id, -32001, "Tool Schema 已变化，需要重新审核")
    arguments = params.get("arguments") or {}
    try:
        validate(arguments, _json(tool.input_schema_json, {}))
    except ValidationError as exc:
        _record_denied_call(
            db,
            token,
            gateway.slug,
            tool.name,
            "Tool 参数不符合 Schema",
            server_slug=server.slug,
            schema_hash=tool.schema_hash,
            skill_assessment=skill_assessment,
        )
        return _jsonrpc_error(request_id, -32602, "Tool 参数不符合 Schema", exc.message)

    approval_meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    approval_error, approval_data, approval_request_id = _consume_tool_approval(
        db,
        token=token,
        gateway_slug=gateway.slug,
        server=server,
        tool=tool,
        arguments=arguments,
        approval_token=approval_meta.get("agent_manager_approval"),
        approval_request_id=approval_meta.get("agent_manager_approval_request"),
        client_ip=request.client.host if request.client else None,
    )
    if approval_error:
        _record_denied_call(
            db, token, gateway.slug, tool.name, approval_error,
            server_slug=server.slug, schema_hash=tool.schema_hash,
            approval_request_id=approval_request_id, skill_assessment=skill_assessment,
        )
        return _jsonrpc_error(request_id, -32002, approval_error, approval_data)
    if _tool_rate_limit_exceeded(db, tool):
        error = "MCP Tool 每分钟调用次数已达上限"
        _record_denied_call(
            db, token, gateway.slug, tool.name, error,
            server_slug=server.slug, schema_hash=tool.schema_hash,
            approval_request_id=approval_request_id, skill_assessment=skill_assessment,
        )
        return _jsonrpc_error(request_id, -32003, error)

    started = time.perf_counter()
    audit = models.McpCallAudit(
        request_id=uuid.uuid4().hex,
        token_id=token.id,
        gateway_slug=gateway.slug,
        server_slug=server.slug,
        tool_name=tool.name,
        schema_hash=tool.schema_hash,
        approval_request_id=approval_request_id,
        **skill_assessment.audit_fields(),
        status="running",
    )
    acquire_access_token_slot(token)
    tool_lease_id = None
    try:
        try:
            tool_lease_id = acquire_lease(
                "mcp_tool", tool.id, "call", tool.max_concurrent, ttl_seconds=server.timeout_seconds + 30, bind=db.get_bind()
            )
        except LeaseLimitExceeded:
            audit.status = "denied"
            audit.error = "MCP Tool 并发调用数已达上限"
            return _jsonrpc_error(request_id, -32004, audit.error)
        upstream = await _call_upstream(server, "tools/call", {"name": tool.name, "arguments": arguments})
        audit.status = "error" if upstream.get("error") else "success"
        if upstream.get("error"):
            audit.error = str(upstream["error"].get("message", "上游 MCP 返回错误"))[:1000]
        upstream["id"] = request_id
        return upstream
    except Exception as exc:
        audit.status = "error"
        audit.error = str(exc)[:1000]
        return _jsonrpc_error(request_id, -32000, "上游 MCP 调用失败")
    finally:
        release_lease(tool_lease_id, bind=db.get_bind())
        release_access_token_slot(token)
        audit.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        db.add(audit)
        db.commit()
