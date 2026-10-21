"""Task-scoped source and MCP execution interfaces."""
from __future__ import annotations

import json
import secrets
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..api_errors import ApiError
from ..security_scan_controls import hash_value, json_dumps, json_loads, protect_secret, unprotect_secret
from ..sqlite_db import get_db
from .mcp_scan_sources import MAX_BYTES, load_source, save_source


class McpTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_token: str = Field(min_length=1, max_length=512)
    method: str = "tools/list"
    tool_name: str = Field(default="", max_length=384)
    arguments: dict = Field(default_factory=dict)
    call_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{8,64}$")


class McpRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    ref: str = Field(default="HEAD", max_length=128)


def authorize(db, task_id, lease_token):
    from agent_manager.core.licensing import require_license
    require_license("security_scanning")
    from ..routers import security_scans as scans
    task = scans._task_or_404(db, task_id)
    worker = db.query(models.SecurityScanWorker).filter_by(worker_id=task.worker_id, status="active").first()
    if not worker:
        raise ApiError(401, "agent_security.task_lease_invalid", "任务租约无效", "Invalid task lease")
    scans._verify_lease(task, worker, lease_token)
    if task.scan_kind != "mcp_risk_scan":
        raise ApiError(403, "mcp_scan.task_invalid", "任务不是 MCP 扫描", "Task is not an MCP scan")
    if task.cancel_requested or task.kill_switch_activated or scans._budget_reason(task, datetime.utcnow()):
        raise ApiError(409, "mcp_scan.stopped", "扫描已停止或达到预算上限", "Scan stopped or reached its budget")
    owner = db.query(models.User).filter_by(id=task.owner_user_id, is_active=True).first()
    if not owner:
        raise ApiError(403, "mcp_scan.owner_inactive", "任务所有者已停用", "Task owner is inactive")
    target = scans._target_or_404(db, task.target_id)
    scans._require_target_access(db, owner, target)
    policy = scans._policy_or_404(db, task.policy_id)
    if target.status != "active" or not policy.enabled:
        raise ApiError(409, "mcp_scan.scope_disabled", "目标或策略已停用", "Target or policy is disabled")
    return task, json_loads(unprotect_secret(task.scan_options_encrypted), {})


def execution_token(db, task, gateway_slug):
    session = db.query(models.SecurityMcpScanSession).filter_by(task_id=task.task_id).first()
    if not session:
        policy = json_loads(task.policy_snapshot_json, {})
        token = models.AccessToken(name=f"MCP scan {task.task_id}", token_type="mcp_gateway",
            token_hash=hash_value(secrets.token_urlsafe(48)), token_prefix="scan-internal",
            scopes_json=json_dumps(["mcp:connect", "mcp:list-tools", "mcp:call-tools"]),
            allowed_mcp_gateways_json=json_dumps([gateway_slug]), user_id=task.owner_user_id,
            group_id=task.owner_group_id, status="active", expires_at=task.timeout_at,
            max_body_kb=1024, max_concurrent_requests=int(policy.get("max_concurrent_requests", 2)),
            created_by="security-scan-service")
        db.add(token)
        db.flush()
        db.add(models.SecurityMcpScanSession(task_id=task.task_id, token_id=token.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        session = db.query(models.SecurityMcpScanSession).filter_by(task_id=task.task_id).one()
    token = db.query(models.AccessToken).filter_by(id=session.token_id, status="active").first()
    if not token or token.expires_at <= datetime.utcnow():
        raise ApiError(403, "mcp_scan.credential_revoked", "扫描调用身份已失效", "Scan execution identity is no longer active")
    return token


def register_routes(router):
    def record_source(db, user, metadata):
        from ..routers import security_scans as scans
        scans._audit(db, event_type="mcp_scan.source_imported", actor=user.username,
                     resource_type="security_mcp_source", resource_id=metadata["source_id"], action="import",
                     details={"sha256": metadata["sha256"], "file_count": metadata["file_count"], "revision": metadata["revision"]})
        return metadata

    @router.get("/targets/{target_id}/mcp-tools")
    async def target_tools(target_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
        from ..routers import security_scans as scans
        target = scans._target_or_404(db, target_id)
        scans._require_target_access(db, user, target)
        if target.connector_type != "mcp_gateway":
            return {"tools": []}
        assets = scans._mcp_gateway_assets_snapshot(db, json_loads(target.config_json, {})["gateway_id"])
        return {"tools": [{"name": t["exposed_name"], "access_mode": t.get("access_mode"), "risk_level": t.get("risk_level"),
                           "schema_hash": t.get("schema_hash")} for s in assets["servers"] for t in s["tools"]
                          if not t.get("missing") and t.get("enabled")]}

    @router.post("/mcp-sources")
    async def upload_source(request: Request, db: Session = Depends(get_db), user=Depends(auth.get_current_security_admin)):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise ApiError(413, "mcp_scan.source_too_large", "源码包超过 20 MiB", "Source bundle exceeds 20 MiB")
        return record_source(db, user, save_source(bytes(content), user.id, origin="upload"))

    @router.post("/mcp-sources/github")
    async def import_github(body: McpRepositoryRequest, db: Session = Depends(get_db), user=Depends(auth.get_current_security_admin)):
        import re
        try:
            parsed = urlsplit(body.url)
        except ValueError as exc:
            raise ApiError(422, "mcp_scan.repository_invalid", "仓库地址无效", "Invalid repository URL") from exc
        if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
            raise ApiError(422, "mcp_scan.repository_invalid", "请输入 GitHub HTTPS 仓库地址", "Enter a GitHub HTTPS repository URL")
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        ref = body.ref or "HEAD"
        if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,128}", ref):
            raise ApiError(422, "mcp_scan.repository_invalid", "仓库或版本无效", "Invalid repository or revision")
        from urllib.parse import quote
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                commit = await client.get(f"https://api.github.com/repos/{'/'.join(parts)}/commits/{quote(ref, safe='')}")
                commit.raise_for_status()
                sha = commit.json()["sha"]
                if not re.fullmatch(r"[0-9a-f]{40}", sha):
                    raise ValueError("invalid commit")
                content = bytearray()
                async with client.stream("GET", f"https://codeload.github.com/{'/'.join(parts)}/zip/{sha}") as archive:
                    archive.raise_for_status()
                    async for chunk in archive.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            raise ValueError("source too large")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ApiError(422, "mcp_scan.repository_download_failed", "仓库下载失败，请检查地址、版本或上传 ZIP", "Repository download failed; check the URL and revision or upload a ZIP") from exc
        return record_source(db, user, save_source(bytes(content), user.id, origin=f"https://github.com/{'/'.join(parts)}", revision=sha))

    @router.post("/worker/tasks/{task_id}/mcp/source")
    async def read_source(task_id: str, body: McpTaskRequest, db: Session = Depends(get_db)):
        task, options = authorize(db, task_id, body.lease_token)
        if options.get("mcp_mode") != "source":
            raise ApiError(403, "mcp_scan.source_not_authorized", "任务未授权源码读取", "Source reading is not authorized")
        source = load_source(options["mcp_source_id"])
        if source["sha256"] != options["mcp_source_sha256"]:
            raise ApiError(409, "mcp_scan.source_changed", "源码快照已变化", "Source snapshot has changed")
        return source

    @router.post("/worker/tasks/{task_id}/mcp")
    async def invoke(task_id: str, body: McpTaskRequest, request: Request, response: Response, db: Session = Depends(get_db)):
        from ..routers import mcp_gateway
        task, options = authorize(db, task_id, body.lease_token)
        if options.get("mcp_mode") not in {"dynamic", "redteam"}:
            raise ApiError(403, "mcp_scan.calls_not_authorized", "当前模式未授权工具调用", "Tool calls are not authorized for this mode")
        snapshot = json_loads(task.target_snapshot_json, {})
        assets = snapshot.get("mcp_assets", {})
        tools = {t["exposed_name"]: (s, t) for s in assets.get("servers", []) for t in s.get("tools", []) if not t.get("missing")}
        selected = set(options.get("mcp_tools") or [])
        if body.method == "tools/list":
            return {"authentication_context": {"route": options.get("mcp_route", "gateway"),
                        "credentials_applied_by_gateway": True, "unauthenticated_access_tested": False,
                        "servers": [{"name": s.get("server_slug"), "authentication_configured": s.get("authentication_configured")}
                                    for s in assets.get("servers", [])]},
                    "tools": [{"name": name, "description": t.get("description", ""), "inputSchema": t.get("input_schema", {})}
                              for name, (_s, t) in tools.items() if name in selected]}
        if body.method != "tools/call" or body.tool_name not in selected or body.tool_name not in tools or not body.call_id:
            raise ApiError(403, "mcp_scan.tool_not_authorized", "工具或调用未获授权", "Tool or call is not authorized")
        server_snapshot, frozen = tools[body.tool_name]
        tool = db.query(models.McpTool).filter_by(id=frozen["tool_id"], enabled=True).first()
        if not tool or tool.schema_hash != frozen.get("schema_hash"):
            raise ApiError(409, "mcp_scan.schema_changed", "工具 Schema 已变化，请重新创建扫描", "Tool schema changed; create a new scan")
        policy = json_loads(task.policy_snapshot_json, {})
        caps = set(policy.get("effective_capabilities", []))
        required = "tool_read" if tool.access_mode == "read" else "tool_write"
        if required not in caps or "network_egress" not in caps or (policy.get("execution_mode") in {"passive", "read_only"} and required != "tool_read"):
            raise ApiError(403, "mcp_scan.capability_denied", "当前扫描目标或策略未允许这些工具所需的操作。请检查网络访问、工具读取和工具写入权限；只读策略只能选择只读工具。", "The scan target or policy does not permit the operations these tools need. Check network access, tool read and tool write permissions. Read-only policies only allow read-only tools.")
        server = db.query(models.McpServer).filter_by(id=tool.server_id, status="active").first()
        if not server:
            raise ApiError(409, "mcp_scan.server_unavailable", "MCP 服务未启用", "MCP server is unavailable")
        if server.endpoint != server_snapshot.get("endpoint"):
            raise ApiError(409, "mcp_scan.endpoint_changed", "MCP 地址已变化，请重新创建扫描", "MCP endpoint changed; create a new scan")
        from ..security_scan_controls import resolve_target_endpoint
        for allowed in (snapshot.get("allowed_cidrs", []), snapshot.get("policy_outbound_allowlist", [])):
            resolved = resolve_target_endpoint(server.endpoint, allowed_cidrs=allowed,
                                              allow_insecure_transport=snapshot.get("allow_insecure_transport", False))
            if set(resolved) != set(server_snapshot.get("resolved_ips", [])):
                raise ApiError(409, "mcp_scan.dns_changed", "MCP DNS 解析已变化，请重新创建扫描", "MCP DNS resolution changed; create a new scan")
        # Session-local connection context, consumed by the shared upstream transport.
        server._scan_resolved_ips = list(server_snapshot["resolved_ips"])
        token = execution_token(db, task, assets["gateway_slug"])
        # Reserve each call atomically before crossing the network boundary.
        db.rollback()
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        previous = db.query(models.SecurityMcpScanCall).filter_by(call_id=body.call_id).first()
        if previous:
            db.rollback()
            raise ApiError(409, "mcp_scan.call_duplicate", "调用标识已使用，禁止重复执行", "Call ID already used; execution will not be repeated")
        count = db.query(models.SecurityMcpScanCall).filter_by(task_id=task_id).count()
        if count >= int(options.get("mcp_call_limit", 20)):
            db.rollback()
            raise ApiError(409, "mcp_scan.call_budget_exceeded", "工具调用次数已达上限", "Tool call budget exhausted")
        row = models.SecurityMcpScanCall(call_id=body.call_id, task_id=task_id, tool_name=body.tool_name,
            schema_hash=tool.schema_hash, route=options.get("mcp_route", "gateway"), status="running")
        db.add(row)
        db.commit()
        rpc = {"jsonrpc": "2.0", "id": body.call_id, "method": "tools/call", "params": {"name": body.tool_name,
            "arguments": body.arguments, "_meta": {"scan_task_id": task_id}}}
        try:
            result = await mcp_gateway.invoke_gateway_with_token(assets["gateway_slug"], rpc, request, response, token, db,
                apply_gateway_policy=options.get("mcp_route", "gateway") == "gateway")
            row.evidence_encrypted = protect_secret(json_dumps({"request": rpc, "response": result}))
            payload = result.get("result")
            row.status = "denied" if result.get("error") else "error" if not isinstance(payload, dict) or payload.get("isError") else "succeeded"
            return {"call_id": body.call_id, "status": row.status, "response": result}
        finally:
            # Gateway DB phases detach snapshots when returning the connection.
            # Reattach before reading expired state on an early rejection.
            db.add(row)
            if row.status == "running":
                row.status = "failed"
            db.commit()

    @router.get("/tasks/{task_id}/mcp-calls")
    async def calls(task_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_security_admin)):
        from ..routers import security_scans as scans
        task = scans._task_or_404(db, task_id)
        scans._require_task_access(db, user, task)
        rows = db.query(models.SecurityMcpScanCall).filter_by(task_id=task_id).order_by(models.SecurityMcpScanCall.created_at).all()
        scans._audit(db, event_type="mcp_scan.evidence_read", actor=user.username, resource_type="security_scan_task",
                     resource_id=task_id, action="read", details={"call_count": len(rows)})
        return {"items": [{"call_id": r.call_id, "tool_name": r.tool_name, "schema_hash": r.schema_hash,
            "route": r.route, "status": r.status, "evidence": json_loads(unprotect_secret(r.evidence_encrypted), {})}
            for r in rows]}
