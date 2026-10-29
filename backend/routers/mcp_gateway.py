import asyncio
import hashlib
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from jsonschema import ValidationError, validate
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import auth, iam, models, schemas
from ..api_errors import ApiError, request_locale
from ..agent_mcp import ensure_agent_mcp_scope
from ..config import settings
from ..mcp_audit_display import audit_reason_metadata
from ..mcp_validation import field_issue, fields_error
from ..request_leases import LeaseLimitExceeded, LeaseRequest, acquire_leases, release_leases, delete_leases
from ..runtime_trace_schemas import RuntimeTraceInternalEvent
from ..security_audit import append_security_audit
from ..services.gateway_db import run_db, run_sync
from ..services.runtime_traces import best_effort_trace_publisher, publish_events_best_effort
from ..sqlite_db import get_db
from .access_tokens import (
    _json_loads,
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


@best_effort_trace_publisher
def _publish_mcp_runtime_trace(
    db: Session,
    *,
    token: models.AccessToken,
    meta: dict,
    request_id,
    gateway_slug: str,
    tool_name: str,
    arguments: dict | None = None,
    result: dict | None = None,
    error: str | None = None,
    error_code: str | None = None,
    schema_hash: str | None = None,
    approval_request_id: str | None = None,
    duration_ms: float = 0.0,
    severity: str | None = None,
) -> None:
    call_id = str(meta.get("call_id") or request_id or f"mcp_{uuid.uuid4().hex}")[:128]
    trusted_agent_id = token.bound_agent_id if token.token_type == "agent_runtime" else None
    common = {
        "trace_id": meta.get("trace_id") if trusted_agent_id else None,
        "tenant_id": str(token.group_id) if token.group_id is not None else "default",
        "agent_id": trusted_agent_id,
        "session_id": str(meta.get("session_id") or f"mcp-token-{token.id}"),
        "owner_user_id": token.user_id,
        "owner_group_id": token.group_id,
        "source": "mcp_gateway",
        "turn_id": meta.get("turn_id"),
        "step_id": meta.get("step_id"),
        "request_id": str(request_id) if request_id is not None else None,
        "call_id": call_id,
        "parent_call_id": meta.get("parent_call_id"),
        "tool_name": tool_name or None,
    }
    events = [
        RuntimeTraceInternalEvent(
            **common,
            type="mcp.call",
            severity=severity,
            status="submitted" if not error else "denied",
            risk_codes=[error_code] if error_code else [],
            payload={
                "gateway": gateway_slug,
                "tool": tool_name,
                "arguments": arguments or {},
                "schema_hash": schema_hash,
                "approval_request_id": approval_request_id,
                "error_code": error_code,
            },
        )
    ]
    if approval_request_id:
        events.append(
            RuntimeTraceInternalEvent(
                **common,
                type="approval.requested" if error and "等待" in error else "approval.resolved",
                severity=severity,
                status="pending" if error and "等待" in error else ("denied" if error else "approved"),
                payload={"approval_request_id": approval_request_id, "message": error},
            )
        )
    events.append(
        RuntimeTraceInternalEvent(
            **common,
            type="mcp.error" if error else "mcp.result",
            severity=severity,
            status="error" if error else "completed",
            risk_codes=[error_code] if error_code else [],
            duration_ms=max(0.0, duration_ms),
            payload={"result": result} if not error else {"error": error, "error_code": error_code},
            redacted_payload={"result": result} if not error else {"error": "[mcp-error]", "error_code": error_code},
        )
    )
    publish_events_best_effort(db, events)


def _json(value: str | None, default):
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def _validate_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise fields_error([field_issue("endpoint", "url")], 400) from exc
    if any(char.isspace() for char in value) or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise fields_error([field_issue("endpoint", "url")], 400)
    if parsed.scheme == "http" and not settings.MCP_ALLOW_HTTP:
        raise fields_error([field_issue("endpoint", "https")], 400)
    if parsed.hostname.lower() == "localhost":
        raise fields_error([field_issue("endpoint", "address")], 400)
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return value
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise fields_error([field_issue("endpoint", "address")], 400)
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
        access_mode=row.access_mode,
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
        environment=row.environment,
        execution_mode=row.execution_mode,
        production_tool_denylist=_json(row.production_tool_denylist_json, []),
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


def _bound_gateway_tool_names(db: Session, gateway: models.McpGateway) -> set[str]:
    db.flush()
    names: set[str] = set()
    bindings = db.query(models.McpGatewayBinding).filter(models.McpGatewayBinding.gateway_id == gateway.id).all()
    for binding in bindings:
        server = db.query(models.McpServer).filter(models.McpServer.id == binding.server_id).first()
        if server:
            names.update(f"{server.slug}__{name}" for name in _json(binding.allowed_tools_json, []))
    return names


def _apply_gateway_execution_policy(
    db: Session,
    gateway: models.McpGateway,
    *,
    environment: str,
    execution_mode: str,
    production_tool_denylist: list[str],
) -> None:
    if environment == "production" and execution_mode == "active_full":
        raise ApiError(
            422,
            "mcp.production_active_full_forbidden",
            "生产 MCP 网关禁止使用完整主动模式",
            "Active-full mode is forbidden for production MCP gateways",
        )
    normalized = list(dict.fromkeys(item.strip() for item in production_tool_denylist if item.strip()))
    invalid = sorted(set(normalized) - _bound_gateway_tool_names(db, gateway))
    if invalid:
        raise ApiError(
            422,
            "mcp.production_tool_denylist_invalid",
            "生产 Tool denylist 包含未绑定到当前网关的 Tool",
            "The production Tool denylist contains tools not bound to this gateway",
            params={"invalid_tools": invalid},
        )
    gateway.environment = environment
    gateway.execution_mode = execution_mode
    gateway.production_tool_denylist_json = json.dumps(normalized, ensure_ascii=False)


def _runtime_tool_policy_denial(
    gateway: models.McpGateway,
    tool: models.McpTool,
) -> tuple[int, str, str] | None:
    if gateway.environment == "production" and gateway.execution_mode == "active_full":
        return -32005, "生产 MCP 网关禁止使用完整主动模式", "mcp.production_active_full_forbidden"
    if gateway.execution_mode == "passive":
        return -32005, "被动 MCP 网关禁止调用 Tool", "mcp.tool_blocked_by_passive_mode"
    if gateway.execution_mode == "read_only" and tool.access_mode != "read":
        return -32005, "只读 MCP 网关禁止调用非只读 Tool", "mcp.write_tool_blocked_by_read_only_mode"
    denylist = set(_json(gateway.production_tool_denylist_json, []))
    if gateway.environment == "production" and tool.exposed_name in denylist:
        return -32006, "Tool 已被生产环境 denylist 阻断", "mcp.tool_blocked_by_production_denylist"
    return None


class McpResponseTooLargeError(ValueError):
    """携带实际响应上限，避免从提示文本识别错误。"""

    def __init__(self, max_response_kb: int) -> None:
        self.max_response_kb = max_response_kb
        super().__init__(f"上游 MCP 响应超过限制: {max_response_kb} KB")


def _upstream_limit_error(exc: Exception, timeout_seconds: int) -> ApiError | None:
    """将超时及响应超限转换为可本地化的具体原因。"""
    if isinstance(exc, httpx.TimeoutException):
        return ApiError(
            504, "mcp.upstream_timeout",
            f"上游 MCP 调用超时（配置超时：{timeout_seconds} 秒）",
            f"Upstream MCP call timed out (configured timeout: {timeout_seconds} seconds)",
            params={"timeout_seconds": timeout_seconds},
        )
    if isinstance(exc, McpResponseTooLargeError):
        return ApiError(
            502, "mcp.upstream_response_too_large",
            f"上游 MCP 响应超过限制：{exc.max_response_kb} KB",
            f"Upstream MCP response exceeds the limit: {exc.max_response_kb} KB",
            params={"max_response_kb": exc.max_response_kb},
        )
    return None


def _upstream_connection_error(
    exc: Exception, *, timeout_seconds: int, debug: bool = False,
) -> ApiError:
    """将 HTTP 客户端固定说明结构化，避免中文界面混入英文提示。"""
    if isinstance(exc, ApiError):
        return exc
    limit_error = _upstream_limit_error(exc, timeout_seconds)
    if limit_error is not None:
        return limit_error
    code = "mcp.debug_failed" if debug else "mcp.connection_failed"
    zh_prefix = "MCP 调试失败" if debug else "MCP Server 连接失败"
    en_prefix = "MCP debugging failed" if debug else "MCP Server connection failed"
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        params = {
            "status": f"{response.status_code} {response.reason_phrase}",
            "url": str(exc.request.url),
            "info_url": (
                "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/"
                f"{response.status_code}"
            ),
        }
        return ApiError(
            502, f"{code}.http_status",
            (f"{zh_prefix}：HTTP 请求失败 '{{status}}'，地址 '{{url}}'。"
             "更多信息请参阅：{info_url}").format(**params),
            (f"{en_prefix}: HTTP request failed '{{status}}' for URL '{{url}}'. "
             "For more information check: {info_url}").format(**params),
            params=params,
        )
    # 上游原始原因保留原文，仅翻译平台提示。
    return ApiError(
        502, code, f"{zh_prefix}: {exc}", f"{en_prefix}: {exc}",
        params={"reason": str(exc)},
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
    *,
    client: httpx.AsyncClient | None = None,
    response_budget: dict[str, int] | None = None,
) -> tuple[dict, str | None]:
    if client is None:
        async with httpx.AsyncClient(timeout=server.timeout_seconds, follow_redirects=False,
                                     trust_env=not bool(getattr(server, "_scan_resolved_ips", None))) as owned:
            return await _post_upstream(server, payload, session_id, protocol_version,
                                        client=owned, response_budget=response_budget)
    resolved = await run_in_threadpool(_validate_resolved_endpoint, server.endpoint)
    scan_addresses = getattr(server, "_scan_resolved_ips", None)
    if scan_addresses is not None and set(resolved) != set(scan_addresses):
        raise ValueError("MCP scan DNS snapshot changed")
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
    endpoint = server.endpoint
    extensions = {}
    if scan_addresses:
        original = httpx.URL(endpoint)
        headers["Host"] = original.netloc.decode("ascii")
        extensions["sni_hostname"] = original.host
        endpoint = str(original.copy_with(host=scan_addresses[0]))
    # 调试只保存实际发送边界的脱敏副本，保留原始参数与鉴权行为。
    if hasattr(server, "_debug_request"):
        server._debug_request = _mask_approval_arguments(payload)
    async with client.stream("POST", endpoint, json=payload, headers=headers, extensions=extensions) as response:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            # 分页发现累计计算所有响应，避免每翻一页重置资源预算。
            if response_budget is not None:
                response_budget["remaining"] -= len(chunk)
                if response_budget["remaining"] < 0:
                    raise McpResponseTooLargeError(max_bytes // 1024)
            content.extend(chunk)
            if len(content) > max_bytes:
                raise McpResponseTooLargeError(max_bytes // 1024)
        buffered = httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=bytes(content),
            request=response.request,
        )
    return _parse_upstream_response(buffered, payload.get("id")), buffered.headers.get("Mcp-Session-Id") or session_id


async def _call_upstream(
    server: models.McpServer, method: str, params: dict, *, paginate_tools: bool = False,
) -> dict:
    # Reuse TCP within one protocol exchange; sessions and credentials remain
    # scoped to this invocation, and every step still validates the destination.
    async with httpx.AsyncClient(timeout=server.timeout_seconds, follow_redirects=False,
                                 trust_env=not bool(getattr(server, "_scan_resolved_ips", None))) as client:
        if not paginate_tools:
            return await _exchange_upstream(server, method, params, client)
        # 初始化、分页及响应处理共用总超时，超时取消后由上下文释放连接。
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                _exchange_upstream(server, method, params, client, paginate_tools=True),
                timeout=server.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise httpx.ReadTimeout("MCP discovery timed out") from exc
        # 同步 JSON 处理期间无法调度取消，完成后仍核对总预算。
        if time.monotonic() - started >= server.timeout_seconds:
            raise httpx.ReadTimeout("MCP discovery timed out")
        return result


def _discovery_error(reason: str, **params: int) -> ApiError:
    messages = {
        "invalid_page": ("MCP 工具发现失败：上游工具列表格式无效", "MCP tool discovery failed: invalid upstream tool list"),
        "invalid_cursor": ("MCP 工具发现失败：上游分页游标格式无效", "MCP tool discovery failed: invalid upstream pagination cursor"),
        "repeated_cursor": ("MCP 工具发现失败：上游返回重复分页游标", "MCP tool discovery failed: repeated upstream pagination cursor"),
        "page_limit": ("MCP 工具发现超过 {limit} 页上限", "MCP tool discovery exceeds the {limit}-page limit"),
        "tool_limit": ("MCP 工具发现超过 {limit} 个工具上限", "MCP tool discovery exceeds the {limit}-tool limit"),
    }
    zh, en = messages[reason]
    return ApiError(502, f"mcp.discovery.{reason}", zh.format(**params), en.format(**params), params=params)


async def _exchange_upstream(server, method, params, client, *, paginate_tools=False):
    post_options = {"client": client}
    if paginate_tools:
        post_options["response_budget"] = {"remaining": server.max_response_kb * 1024}
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
        **post_options,
    )
    if initialized.get("error"):
        return initialized
    protocol_version = initialized.get("result", {}).get("protocolVersion", MCP_PROTOCOL_VERSION)
    if protocol_version not in SUPPORTED_MCP_PROTOCOL_VERSIONS:
        raise ValueError(f"上游 MCP 返回不支持的协议版本: {protocol_version}")
    _, session_id = await _post_upstream(
        server,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        session_id,
        protocol_version,
        **post_options,
    )
    tools = []
    cursors = set()
    for page in range(100 if paginate_tools else 1):
        result, session_id = await _post_upstream(
            server,
            {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": params},
            session_id,
            protocol_version,
            **post_options,
        )
        if not paginate_tools or result.get("error"):
            return result
        data = result.get("result")
        if (not isinstance(data, dict) or not isinstance(data.get("tools"), list)
                or any(not isinstance(tool, dict) for tool in data["tools"])):
            raise _discovery_error("invalid_page")
        tools.extend(data["tools"])
        if len(tools) > 10000:
            raise _discovery_error("tool_limit", limit=10000)
        cursor = data.get("nextCursor")
        if cursor is None or cursor == "":
            # 全部分页成功后交给既有事务统一写入，失败保留原快照。
            data["tools"] = tools
            data.pop("nextCursor", None)
            return result
        if not isinstance(cursor, str):
            raise _discovery_error("invalid_cursor")
        if cursor in cursors:
            raise _discovery_error("repeated_cursor")
        if page == 99:
            raise _discovery_error("page_limit", limit=100)
        cursors.add(cursor)
        params = {**params, "cursor": cursor}


@admin_router.get("/servers/options")
async def server_options() -> dict[str, bool]:
    """提供当前地址协议要求，供表单说明与即时校验使用。"""
    return {"allow_http": settings.MCP_ALLOW_HTTP}


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
        raise fields_error([field_issue("slug", "duplicate")], 400)
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
        raise fields_error([field_issue("slug", "immutable")], 400)
    data.pop("slug", None)
    if "endpoint" in data:
        data["endpoint"] = _validate_endpoint(data["endpoint"])
    if "authorization_header" in data:
        data["authorization_header"] = _validate_header(data["authorization_header"])
    connection_changed = any(
        field in data and data[field] != getattr(row, field)
        for field in ("endpoint", "authorization_header")
    )
    if "authorization_value" in data:
        value = data.pop("authorization_value")
        if value is not None:
            connection_changed |= (value or None) != _unprotect_secret(row.authorization_value)
            row.authorization_value = _protect_secret(value) if value else None
    if "name" in data and not data["name"].strip():
        raise HTTPException(status_code=400, detail="MCP Server 名称不能为空")
    for field, value in data.items():
        setattr(row, field, value.strip() if field == "name" else value)
    if connection_changed:
        # 旧检测只适用于原连接配置，实际变更后等待重新检测。
        row.health_status = "unknown"
        row.last_checked_at = None
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
        response = await _call_upstream(row, "tools/list", {}, paginate_tools=True)
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
        raise _upstream_connection_error(exc, timeout_seconds=row.timeout_seconds) from exc


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
    tool.access_mode = body.access_mode
    tool.risk_level = body.risk_level
    tool.rate_limit_per_minute = body.rate_limit_per_minute
    tool.max_concurrent = body.max_concurrent
    tool.requires_approval = body.requires_approval or body.risk_level == "high" or body.access_mode == "destructive"
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
        models.AccessToken.token_type.in_(["mcp_gateway", "agent_runtime"]),
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
    ensure_agent_mcp_scope(db, token, [body.gateway_slug])
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


def _expire_approval_requests(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
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


# 审批结论和授权生命周期分别展示，保留原状态供执行路径使用。
def _approval_display_state(row: models.McpToolApproval) -> tuple[str, str | None]:
    if row.status == "expired":
        return ("approved", "expired") if row.reviewed_at else ("timed_out", None)
    if row.status == "approved":
        return "approved", "valid"
    if row.status == "used":
        return ("approved" if row.reviewed_at else "used"), "used"
    return row.status, None


ApprovalStatistic = Literal[
    "pending", "approved_today", "rejected_today", "timed_out_today", "approved_expired_today",
]


def _approval_statistic_conditions(now: datetime) -> dict:
    # 卡片和列表共用北京时间日界线及 SQL 条件，批准过期按批准日期计入。
    today = (now + timedelta(hours=8)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    tomorrow = today + timedelta(days=1)
    row = models.McpToolApproval
    reviewed_today = and_(row.reviewed_at >= today, row.reviewed_at < tomorrow)
    return {
        "pending": and_(row.status == "pending", row.expires_at >= now),
        "approved_today": and_(row.status.in_(["approved", "used", "expired"]), reviewed_today),
        "rejected_today": and_(row.status == "rejected", reviewed_today),
        "timed_out_today": and_(
            row.status == "expired", row.reviewed_at.is_(None),
            row.expires_at >= today, row.expires_at < tomorrow, row.expires_at < now,
        ),
        "approved_expired_today": and_(row.status == "expired", reviewed_today),
    }


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
    approval_result, authorization_status = _approval_display_state(row)
    return schemas.McpApprovalRequestResponse(
        request_id=row.request_id or "",
        token_id=row.token_id,
        token_name=token.name if token else "",
        token_deleted=token is None,
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
        approval_result=approval_result,
        authorization_status=authorization_status,
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
    now = datetime.utcnow()
    _expire_approval_requests(db, now)
    query = db.query(models.McpToolApproval).filter(models.McpToolApproval.request_id.is_not(None))
    counts = {key: query.filter(condition).count() for key, condition in _approval_statistic_conditions(now).items()}
    return schemas.McpApprovalRequestStatsResponse(
        **counts,
        expired=query.filter(models.McpToolApproval.status == "expired").count(),
    )


@admin_router.get("/approval-requests", response_model=schemas.McpApprovalRequestListResponse)
async def list_approval_requests(
    status: str | None = None,
    statistic: ApprovalStatistic | None = None,
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
    now = datetime.utcnow()
    _expire_approval_requests(db, now)
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    query = db.query(models.McpToolApproval).outerjoin(
        models.AccessToken, models.AccessToken.id == models.McpToolApproval.token_id
    ).filter(models.McpToolApproval.request_id.is_not(None))
    if statistic:
        query = query.filter(_approval_statistic_conditions(now)[statistic])
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
        # 查询边界统一为数据库使用的UTC无时区时间，正确处理带偏移的输入。
        if created_from.tzinfo:
            created_from = created_from.astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(models.McpToolApproval.created_at >= created_from)
    if created_to:
        if created_to.tzinfo:
            created_to = created_to.astimezone(timezone.utc).replace(tzinfo=None)
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
        models.AccessToken.token_type.in_(["mcp_gateway", "agent_runtime"]),
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
    ensure_agent_mcp_scope(db, token, [row.gateway_slug])
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
        environment=body.environment,
        execution_mode=body.execution_mode,
        status=body.status,
        created_by=current_user.username,
    )
    if not row.name:
        raise HTTPException(status_code=400, detail="MCP 网关名称不能为空")
    db.add(row)
    db.flush()
    _save_bindings(db, row, body.bindings)
    _apply_gateway_execution_policy(
        db,
        row,
        environment=body.environment,
        execution_mode=body.execution_mode,
        production_tool_denylist=body.production_tool_denylist,
    )
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
    production_tool_denylist = data.pop("production_tool_denylist", None)
    environment = data.pop("environment", row.environment)
    execution_mode = data.pop("execution_mode", row.execution_mode)
    if "name" in data and not data["name"].strip():
        raise HTTPException(status_code=400, detail="MCP 网关名称不能为空")
    for field, value in data.items():
        setattr(row, field, value.strip() if field == "name" else value)
    if bindings is not None:
        _save_bindings(db, row, [schemas.McpGatewayBindingInput(**item) for item in bindings])
    _apply_gateway_execution_policy(
        db,
        row,
        environment=environment,
        execution_mode=execution_mode,
        production_tool_denylist=(
            production_tool_denylist
            if production_tool_denylist is not None
            else _json(row.production_tool_denylist_json, [])
        ),
    )
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


@admin_router.get("/audit", response_model=schemas.McpCallAuditListResponse)
async def list_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    request_id: str | None = None,
    target: str | None = None,
    token_name: str | None = None,
    status: Literal['success', 'denied', 'error', 'running'] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort_by: Literal['created_at', 'duration_ms'] = 'created_at',
    sort_order: Literal['asc', 'desc'] = 'desc',
    db: Session = Depends(get_db),
):
    query = db.query(models.McpCallAudit, models.AccessToken.name, models.AccessToken.id).outerjoin(
        models.AccessToken, models.AccessToken.id == models.McpCallAudit.token_id
    )
    if request_id and request_id.strip():
        query = query.filter(models.McpCallAudit.request_id.contains(request_id.strip(), autoescape=True))
    if target and target.strip():
        query = query.filter(or_(*[
            column.contains(target.strip(), autoescape=True) for column in (
                models.McpCallAudit.gateway_slug, models.McpCallAudit.server_slug, models.McpCallAudit.tool_name,
            )
        ]))
    if token_name and token_name.strip():
        query = query.filter(func.coalesce(models.McpCallAudit.token_name, models.AccessToken.name).contains(
            token_name.strip(), autoescape=True,
        ))
    if status:
        query = query.filter(models.McpCallAudit.status == status)
    if created_from:
        if created_from.tzinfo:
            created_from = created_from.astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(models.McpCallAudit.created_at >= created_from)
    if created_to:
        if created_to.tzinfo:
            created_to = created_to.astimezone(timezone.utc).replace(tzinfo=None)
        query = query.filter(models.McpCallAudit.created_at <= created_to)
    total = query.count()
    column = getattr(models.McpCallAudit, sort_by)
    order = (column.asc(), models.McpCallAudit.id.asc()) if sort_order == 'asc' else (column.desc(), models.McpCallAudit.id.desc())
    rows = query.order_by(*order).offset((page - 1) * page_size).limit(page_size).all()
    items = [
        schemas.McpCallAuditResponse(
            id=row.id,
            request_id=row.request_id,
            token_id=row.token_id,
            token_name=row.token_name if row.token_name is not None else current_name,
            token_exists=current_id is not None,
            gateway_slug=row.gateway_slug,
            server_slug=row.server_slug,
            tool_name=row.tool_name,
            schema_hash=row.schema_hash,
            approval_request_id=row.approval_request_id,
            status=row.status,
            duration_ms=row.duration_ms,
            error=row.error,
            **audit_reason_metadata(row.status, row.error),
            created_at=row.created_at,
        )
        for row, current_name, current_id in rows
    ]
    return schemas.McpCallAuditListResponse(items=items, total=total, page=page, page_size=page_size)


@admin_router.post("/debug/upstream")
async def debug_upstream(
    body: schemas.McpUpstreamDebugRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    stored = None
    if body.server_id is not None:
        stored = db.query(models.McpServer).filter(models.McpServer.id == body.server_id).first()
        if not stored:
            raise HTTPException(status_code=404, detail="MCP Server 不存在")
    if not body.endpoint and not stored:
        raise HTTPException(status_code=400, detail="请填写 MCP Endpoint")

    endpoint = _validate_endpoint(body.endpoint or stored.endpoint)
    header = _validate_header(body.authorization_header or (stored.authorization_header if stored else "Authorization"))
    if body.authorization_value is not None:
        protected_secret = _protect_secret(body.authorization_value) if body.authorization_value else None
    else:
        # 编辑时沿用已保存凭证，与保存后连接发现的处理保持一致。
        protected_secret = stored.authorization_value if stored else None
        if protected_secret and endpoint != stored.endpoint:
            # 将已存凭证用于新地址属于编辑操作，执行权限不能代替编辑授权。
            iam.check(db, current_user, "mcp:update")

    transient = models.McpServer(
        slug=stored.slug if stored else "debug",
        name=stored.name if stored else "MCP Debug",
        endpoint=endpoint,
        authorization_header=header,
        authorization_value=protected_secret,
        timeout_seconds=body.timeout_seconds,
    )
    transient._debug_request = None
    started = time.perf_counter()
    try:
        result = await _call_upstream(transient, body.method, body.params)
    except Exception as exc:
        error = _upstream_connection_error(exc, timeout_seconds=transient.timeout_seconds, debug=True)
        if transient._debug_request is not None:
            error.params = {**error.params, "debug_request": transient._debug_request}
        raise error from exc
    return {
        "request": transient._debug_request,
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


def _jsonrpc_error(request_id, code: int, message: str, data=None, *, call_status=None) -> dict:
    error = {"code": code, "message": message}
    if call_status:
        error["call_status"] = call_status
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
) -> None:
    db.add(
        models.McpCallAudit(
            request_id=uuid.uuid4().hex,
            token_id=token.id,
            token_name=token.name,
            bound_agent_id=token.bound_agent_id if token.token_type == "agent_runtime" else None,
            gateway_slug=gateway_slug,
            server_slug=server_slug[:128] if server_slug else None,
            tool_name=tool_name[:255] or None,
            schema_hash=schema_hash,
            approval_request_id=approval_request_id,
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
        allowed_token_types={"mcp_gateway", "agent_runtime"},
    )
    ensure_agent_mcp_scope(db, token, [gateway_slug])
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
        return _jsonrpc_error(body.get("id"), -32600, "Invalid Request", call_status="denied")
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
        return _jsonrpc_error(request_id, -32601, "Method not found", call_status="denied")
    token = await run_db(db, resolve_access_token,
        db,
        authorization,
        required_scope=required_scope,
        request=request,
        allowed_token_types={"mcp_gateway", "agent_runtime"},
    )
    return await invoke_gateway_with_token(gateway_slug, body, request, response, token, db)


async def invoke_gateway_with_token(
    gateway_slug: str,
    body: dict,
    request: Request,
    response: Response,
    token: models.AccessToken,
    db: Session,
    *,
    apply_gateway_policy: bool = True,
):
    prepared = await run_db(
        db, _prepare_gateway_invocation, gateway_slug, body, request, response, token, db,
        apply_gateway_policy=apply_gateway_policy,
    )
    if callable(prepared):
        return await prepared()
    return prepared


def _prepare_gateway_invocation(
    gateway_slug: str,
    body: dict,
    request: Request,
    response: Response,
    token: models.AccessToken,
    db: Session,
    *,
    apply_gateway_policy: bool = True,
):
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _jsonrpc_error(body.get("id"), -32600, "Invalid Request", call_status="denied")
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
        return _jsonrpc_error(request_id, -32601, "Method not found", call_status="denied")
    allowed_gateways = _json_loads(token.allowed_mcp_gateways_json, [])
    if gateway_slug not in allowed_gateways:
        raise HTTPException(status_code=403, detail="凭证未授权访问该 MCP 网关")
    try:
        ensure_agent_mcp_scope(db, token, [gateway_slug])
    except ApiError as exc:
        if method == "tools/call":
            params = body.get("params")
            tool_name = str(params.get("name") or "") if isinstance(params, dict) else ""
            _record_denied_call(db, token, gateway_slug, tool_name, exc.code)
        raise
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
                    if approved_hash == tool.schema_hash and _runtime_tool_policy_denial(gateway, tool) is None
                ]
            },
        }

    params = body.get("params") or {}
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params", call_status="denied")
    approval_meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
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
        _publish_mcp_runtime_trace(
            db, token=token, meta=approval_meta, request_id=request_id,
            gateway_slug=gateway.slug, tool_name=exposed_name, error="Tool 未授权或不存在",
        )
        return _jsonrpc_error(request_id, -32602, "Tool 未授权或不存在", call_status="denied")
    server, tool, approved_hash = match
    policy_denial = _runtime_tool_policy_denial(gateway, tool) if apply_gateway_policy else None
    if policy_denial:
        rpc_code, error, error_code = policy_denial
        _record_denied_call(
            db,
            token,
            gateway.slug,
            tool.name,
            error,
            server_slug=server.slug,
            schema_hash=tool.schema_hash,
        )
        _publish_mcp_runtime_trace(
            db,
            token=token,
            meta=approval_meta,
            request_id=request_id,
            gateway_slug=gateway.slug,
            tool_name=tool.name,
            arguments=params.get("arguments") if isinstance(params.get("arguments"), dict) else {},
            error=error,
            severity=tool.risk_level,
            error_code=error_code,
            schema_hash=tool.schema_hash,
        )
        return _jsonrpc_error(request_id, rpc_code, error, {"error_code": error_code}, call_status="denied")
    if apply_gateway_policy and approved_hash != tool.schema_hash:
        _record_denied_call(
            db,
            token,
            gateway.slug,
            tool.name,
            "Tool Schema 已变化，需要重新审核",
            server_slug=server.slug,
            schema_hash=tool.schema_hash,
        )
        _publish_mcp_runtime_trace(
            db, token=token, meta=approval_meta, request_id=request_id,
            gateway_slug=gateway.slug, tool_name=tool.name,
            error="Tool Schema 已变化，需要重新审核", schema_hash=tool.schema_hash,
            severity=tool.risk_level,
        )
        return _jsonrpc_error(request_id, -32001, "Tool Schema 已变化，需要重新审核", call_status="denied")
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
        _publish_mcp_runtime_trace(
            db, token=token, meta=approval_meta, request_id=request_id,
            gateway_slug=gateway.slug, tool_name=tool.name, arguments=arguments,
            error="Tool 参数不符合 Schema", schema_hash=tool.schema_hash,
            severity=tool.risk_level,
        )
        return _jsonrpc_error(request_id, -32602, "Tool 参数不符合 Schema", exc.message, call_status="denied")

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
            approval_request_id=approval_request_id,
        )
        _publish_mcp_runtime_trace(
            db, token=token, meta=approval_meta, request_id=request_id,
            gateway_slug=gateway.slug, tool_name=tool.name, arguments=arguments,
            error=approval_error, schema_hash=tool.schema_hash,
            approval_request_id=approval_request_id,
            severity=tool.risk_level,
        )
        return _jsonrpc_error(request_id, -32002, approval_error, approval_data, call_status="denied")
    if _tool_rate_limit_exceeded(db, tool):
        error = "MCP Tool 每分钟调用次数已达上限"
        _record_denied_call(
            db, token, gateway.slug, tool.name, error,
            server_slug=server.slug, schema_hash=tool.schema_hash,
            approval_request_id=approval_request_id,
        )
        _publish_mcp_runtime_trace(
            db, token=token, meta=approval_meta, request_id=request_id,
            gateway_slug=gateway.slug, tool_name=tool.name, arguments=arguments,
            error=error, schema_hash=tool.schema_hash,
            approval_request_id=approval_request_id,
            severity=tool.risk_level,
        )
        return _jsonrpc_error(request_id, -32003, error, call_status="denied")

    started = time.perf_counter()
    audit = models.McpCallAudit(
        request_id=uuid.uuid4().hex,
        token_id=token.id,
        token_name=token.name,
        bound_agent_id=token.bound_agent_id if token.token_type == "agent_runtime" else None,
        gateway_slug=gateway.slug,
        server_slug=server.slug,
        tool_name=tool.name,
        schema_hash=tool.schema_hash,
        approval_request_id=approval_request_id,
        status="running",
    )
    bind = db.get_bind()
    # Values used by the network phase stay loaded after the transaction ends.
    db.commit()

    def finish(trace_result, lease_ids):
        audit.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        delete_leases(db.connection(), lease_ids)
        db.add(audit)
        db.commit()
        lease_ids.clear()
        _publish_mcp_runtime_trace(
            db,
            token=token,
            meta=approval_meta,
            request_id=request_id,
            gateway_slug=gateway.slug,
            tool_name=tool.name,
            arguments=arguments,
            result=trace_result,
            error=audit.error,
            schema_hash=tool.schema_hash,
            approval_request_id=approval_request_id,
            duration_ms=audit.duration_ms,
            severity=tool.risk_level,
        )

    async def execute():
        lease_ids = []
        trace_result = None
        try:
            # Store both leases before run_sync propagates request cancellation.
            def acquire_slots():
                nonlocal lease_ids
                lease_ids = acquire_leases([
                    LeaseRequest("access_token", token.id, "request", token.max_concurrent_requests),
                    LeaseRequest("mcp_tool", tool.id, "call", tool.max_concurrent, server.timeout_seconds + 30),
                ], bind=bind)
            try:
                await run_sync(acquire_slots)
            except LeaseLimitExceeded as exc:
                if exc.subject_type == "access_token":
                    audit.status = "denied"
                    audit.error = "credential.concurrency_limit"
                    raise ApiError(429, "credential.concurrency_limit", "接入凭证并发请求数已达上限",
                                   "The credential concurrency limit has been reached") from exc
                audit.status = "denied"
                audit.error = "MCP Tool 并发调用数已达上限"
                return _jsonrpc_error(request_id, -32004, audit.error, call_status="denied")
            upstream = await _call_upstream(server, "tools/call", {"name": tool.name, "arguments": arguments})
            trace_result = upstream
            result = upstream.get("result")
            tool_failed = isinstance(result, dict) and result.get("isError") is True
            audit.status = "error" if upstream.get("error") or tool_failed else "success"
            if upstream.get("error"):
                # 分类由平台写入，避免上游扩展字段把执行错误标成平台拒绝。
                upstream["error"]["call_status"] = "error"
                audit.error = str(upstream["error"].get("message", "上游 MCP 返回错误"))[:1000]
            elif tool_failed:
                # 工具业务错误仍通过 result 返回，审计应记录失败及原始文本原因。
                audit.error = "\n".join(
                    item["text"] for item in result.get("content", [])
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                )[:1000] or "mcp.tool_execution_failed"
            upstream["id"] = request_id
            return upstream
        except HTTPException as exc:
            if not lease_ids:
                raise
            audit.status = "error"
            audit.error = str(exc)[:1000]
            return _jsonrpc_error(request_id, -32000, "上游 MCP 调用失败")
        except Exception as exc:
            audit.status = "error"
            limit_error = _upstream_limit_error(exc, server.timeout_seconds)
            if limit_error is not None:
                audit.error = limit_error.zh_message
                message = (
                    limit_error.en_message if request_locale(request) == "en-US"
                    else limit_error.zh_message
                )
                return _jsonrpc_error(request_id, -32000, message, {
                    "error_code": limit_error.code, "error_params": limit_error.params,
                })
            audit.error = str(exc)[:1000]
            return _jsonrpc_error(request_id, -32000, "上游 MCP 调用失败")
        except BaseException:
            audit.status = "error"
            audit.error = "gateway.request_interrupted"
            raise
        finally:
            try:
                if audit.status != "running":
                    await run_db(db, finish, trace_result, lease_ids)
            finally:
                # Audit failure must not leave successful acquisitions occupied.
                if lease_ids:
                    await run_sync(release_leases, lease_ids, bind=bind)

    return execute
