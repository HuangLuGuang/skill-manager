import hashlib
import ipaddress
import json
import time
import uuid
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from jsonschema import ValidationError, validate
from sqlalchemy.orm import Session

from .. import auth, models, schemas
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
    if parsed.hostname.lower() == "localhost":
        raise HTTPException(status_code=400, detail="MCP Endpoint 不允许 localhost")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return value
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise HTTPException(status_code=400, detail="MCP Endpoint 不允许环回、链路本地或组播地址")
    return value


def _validate_header(name: str) -> str:
    value = name.strip()
    if not value or any(char in value for char in "\r\n:"):
        raise HTTPException(status_code=400, detail="MCP 鉴权 Header 名称无效")
    return value


def _schema_hash(schema: dict) -> str:
    canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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
    async with httpx.AsyncClient(timeout=server.timeout_seconds, follow_redirects=False) as client:
        response = await client.post(server.endpoint, json=payload, headers=headers)
    return _parse_upstream_response(response, payload.get("id")), response.headers.get("Mcp-Session-Id") or session_id


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
) -> None:
    db.add(
        models.McpCallAudit(
            request_id=uuid.uuid4().hex,
            token_id=token.id,
            gateway_slug=gateway_slug,
            server_slug=server_slug[:128] if server_slug else None,
            tool_name=tool_name[:255] or None,
            schema_hash=schema_hash,
            status="denied",
            duration_ms=0,
            error=error[:1000],
        )
    )
    db.commit()


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
    token = resolve_access_token(db, authorization, required_scope=required_scope, request=request)
    if token.token_type != "mcp_gateway":
        raise HTTPException(status_code=403, detail="凭证类型不是 MCP 网关凭证")
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
        )
        return _jsonrpc_error(request_id, -32602, "Tool 参数不符合 Schema", exc.message)

    started = time.perf_counter()
    audit = models.McpCallAudit(
        request_id=uuid.uuid4().hex,
        token_id=token.id,
        gateway_slug=gateway.slug,
        server_slug=server.slug,
        tool_name=tool.name,
        schema_hash=tool.schema_hash,
        status="running",
    )
    acquire_access_token_slot(token)
    try:
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
        release_access_token_slot(token)
        audit.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        db.add(audit)
        db.commit()
