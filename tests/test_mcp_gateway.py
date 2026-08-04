import asyncio
import json

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.routers import access_tokens, mcp_gateway
from backend.sqlite_db import Base, get_db


def test_streamable_http_sse_response_is_parsed():
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text='event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n',
        request=httpx.Request("POST", "https://mcp.example.com/mcp"),
    )

    assert mcp_gateway._parse_upstream_response(response)["result"] == {"tools": []}


def test_streamable_http_sse_skips_notifications_before_response():
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=(
            'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
            'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n\n'
        ),
        request=httpx.Request("POST", "https://mcp.example.com/mcp"),
    )

    assert mcp_gateway._parse_upstream_response(response, 2)["id"] == 2


def test_upstream_negotiated_protocol_version_is_reused(monkeypatch):
    calls = []

    async def fake_post(server, payload, session_id=None, protocol_version=mcp_gateway.MCP_PROTOCOL_VERSION):
        calls.append((payload["method"], protocol_version))
        if payload["method"] == "initialize":
            return {"result": {"protocolVersion": "2025-06-18"}}, "session-1"
        if payload["method"] == "notifications/initialized":
            return {}, session_id
        return {"result": {"tools": []}}, session_id

    monkeypatch.setattr(mcp_gateway, "_post_upstream", fake_post)
    server = models.McpServer(slug="test", timeout_seconds=30)
    result = asyncio.run(mcp_gateway._call_upstream(server, "tools/list", {}))

    assert result == {"result": {"tools": []}}
    assert calls == [
        ("initialize", "2025-11-25"),
        ("notifications/initialized", "2025-06-18"),
        ("tools/list", "2025-06-18"),
    ]


def test_endpoint_requires_https_and_rejects_private_dns(monkeypatch):
    with pytest.raises(HTTPException):
        mcp_gateway._validate_endpoint("http://public.example.com/mcp")

    monkeypatch.setattr(
        mcp_gateway.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(HTTPException) as exc:
        mcp_gateway._validate_resolved_endpoint("https://public.example.com/mcp")
    assert "不允许的地址" in str(exc.value.detail)

    monkeypatch.setattr(mcp_gateway.settings, "MCP_OUTBOUND_ALLOWLIST", "public.example.com")
    with pytest.raises(HTTPException):
        mcp_gateway._validate_resolved_endpoint("https://public.example.com/mcp")

    monkeypatch.setattr(mcp_gateway.settings, "MCP_OUTBOUND_ALLOWLIST", "public.example.com,127.0.0.1/32")
    assert mcp_gateway._validate_resolved_endpoint("https://public.example.com/mcp") == ["127.0.0.1"]


def _client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'mcp.db'}", connect_args={"check_same_thread": False})
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    async def fake_call(server, method, params):
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": "upstream",
                "result": {
                    "tools": [
                        {
                            "name": "search",
                            "description": "Search records",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                        },
                        {"name": "delete", "inputSchema": {"type": "object"}},
                    ]
                },
            }
        assert server.slug == "crm"
        assert method == "tools/call"
        return {"jsonrpc": "2.0", "id": "upstream", "result": {"content": [{"type": "text", "text": params["arguments"]["query"]}]}}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", fake_call)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1, username="admin", hashed_password="x", role="super_admin"
    )
    app.include_router(
        mcp_gateway.admin_router,
        prefix="/api/v1",
        dependencies=[Depends(auth.get_current_admin_user)],
    )
    app.include_router(access_tokens.router, prefix="/api/v1")
    app.include_router(mcp_gateway.runtime_router)
    return TestClient(app), testing_session


def _configured_gateway(client):
    server = client.post(
        "/api/v1/mcp/servers",
        json={
            "slug": "crm",
            "name": "CRM",
            "endpoint": "https://mcp.example.com/mcp",
            "authorization_value": "Bearer upstream-secret",
            "status": "active",
        },
    )
    assert server.status_code == 200
    assert server.json()["authorization_masked"].endswith("cret")
    assert "upstream-secret" not in server.text

    discovered = client.post(f"/api/v1/mcp/servers/{server.json()['id']}/discover")
    assert discovered.status_code == 200
    assert {tool["name"] for tool in discovered.json()["tools"]} == {"search", "delete"}

    gateway = client.post(
        "/api/v1/mcp/gateways",
        json={
            "slug": "readonly",
            "name": "只读能力",
            "bindings": [{"server_id": server.json()["id"], "allowed_tools": ["search"]}],
        },
    )
    assert gateway.status_code == 200
    return gateway.json()


def _gateway_token(client):
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "readonly-client",
            "token_type": "mcp_gateway",
            "allowed_mcp_gateways": ["readonly"],
        },
    )
    assert created.status_code == 200
    assert created.json()["record"]["scopes"] == ["mcp:connect", "mcp:list-tools", "mcp:call-tools"]
    return created.json()["token"]


def test_admin_can_debug_unsaved_endpoint_without_leaking_stored_secret(tmp_path, monkeypatch):
    client, _testing_session = _client(tmp_path, monkeypatch)
    server = client.post(
        "/api/v1/mcp/servers",
        json={
            "slug": "private",
            "name": "Private MCP",
            "endpoint": "https://private.example.com/mcp",
            "authorization_value": "Bearer stored-secret",
        },
    ).json()
    calls = []

    async def fake_call(target, method, params):
        calls.append((target.endpoint, mcp_gateway._unprotect_secret(target.authorization_value), method, params))
        return {"jsonrpc": "2.0", "id": "debug", "result": {"tools": []}}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", fake_call)

    same = client.post(
        "/api/v1/mcp/debug/upstream",
        json={"server_id": server["id"], "method": "tools/list"},
    )
    changed = client.post(
        "/api/v1/mcp/debug/upstream",
        json={
            "server_id": server["id"],
            "endpoint": "https://other.example.com/mcp",
            "method": "tools/list",
        },
    )
    unsaved = client.post(
        "/api/v1/mcp/debug/upstream",
        json={
            "endpoint": "https://new.example.com/mcp",
            "authorization_value": "Bearer temporary-secret",
            "method": "ping",
        },
    )

    assert same.status_code == changed.status_code == unsaved.status_code == 200
    assert calls == [
        ("https://private.example.com/mcp", "Bearer stored-secret", "tools/list", {}),
        ("https://other.example.com/mcp", None, "tools/list", {}),
        ("https://new.example.com/mcp", "Bearer temporary-secret", "ping", {}),
    ]
    assert client.post(
        "/api/v1/mcp/debug/upstream",
        json={"endpoint": "http://localhost:3000/mcp", "method": "ping"},
    ).status_code == 400


def test_mcp_gateway_discovers_filters_calls_and_audits(tmp_path, monkeypatch):
    client, _testing_session = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    initialized = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "agent-manager/readonly"

    compatible = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 11, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    )
    assert compatible.json()["result"]["protocolVersion"] == "2025-06-18"

    listed = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert [tool["name"] for tool in listed.json()["result"]["tools"]] == ["crm__search"]

    denied = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "crm__delete", "arguments": {}}},
    )
    assert denied.json()["error"]["code"] == -32602

    invalid = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "crm__search", "arguments": {}}},
    )
    assert invalid.json()["error"]["message"] == "Tool 参数不符合 Schema"

    called = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "crm__search", "arguments": {"query": "alice"}}},
    )
    assert called.json()["id"] == 5
    assert called.json()["result"]["content"][0]["text"] == "alice"

    audit = client.get("/api/v1/mcp/audit").json()
    assert [row["status"] for row in audit].count("denied") == 2
    success = next(row for row in audit if row["status"] == "success")
    assert success["gateway_slug"] == "readonly"
    assert success["server_slug"] == "crm"
    assert success["tool_name"] == "search"


def test_mcp_gateway_blocks_schema_drift_and_wrong_gateway_token(tmp_path, monkeypatch):
    client, testing_session = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    db = testing_session()
    tool = db.query(models.McpTool).filter(models.McpTool.name == "search").one()
    tool.input_schema_json = json.dumps({"type": "object"})
    tool.schema_hash = "changed"
    db.commit()
    db.close()

    listed = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert listed.json()["result"]["tools"] == []

    called = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "crm__search", "arguments": {}}},
    )
    assert called.json()["error"]["message"] == "Tool Schema 已变化，需要重新审核"
    assert client.get("/api/v1/mcp/audit").json()[0]["status"] == "denied"

    wrong_token = client.post(
        "/api/v1/access/tokens",
        json={"name": "no-access", "token_type": "mcp_gateway", "allowed_mcp_gateways": []},
    ).json()["token"]
    forbidden = client.post(
        "/mcp/readonly",
        headers={"Authorization": f"Bearer {wrong_token}"},
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
    )
    assert forbidden.status_code == 403


def test_high_risk_tool_requires_single_use_argument_bound_approval(tmp_path, monkeypatch):
    client, _testing_session = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    servers = client.get("/api/v1/mcp/servers").json()
    search_tool = next(tool for tool in servers[0]["tools"] if tool["name"] == "search")
    policy = client.put(
        f"/api/v1/mcp/tools/{search_tool['id']}/policy",
        json={
            "risk_level": "high",
            "rate_limit_per_minute": 10,
            "max_concurrent": 1,
            "requires_approval": True,
        },
    )
    assert policy.status_code == 200
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "approved-client",
            "token_type": "mcp_gateway",
            "allowed_mcp_gateways": ["readonly"],
        },
    ).json()
    headers = {"Authorization": f"Bearer {created['token']}"}
    call = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "crm__search", "arguments": {"query": "approved"}},
    }

    missing = client.post("/mcp/readonly", headers=headers, json=call)
    assert missing.json()["error"]["code"] == -32002

    approval = client.post(
        "/api/v1/mcp/approvals",
        json={
            "token_id": created["record"]["id"],
            "gateway_slug": "readonly",
            "tool_name": "crm__search",
            "arguments": {"query": "approved"},
            "ttl_seconds": 60,
        },
    )
    assert approval.status_code == 200
    call["params"]["_meta"] = {"agent_manager_approval": approval.json()["approval_token"]}

    allowed = client.post("/mcp/readonly", headers=headers, json=call)
    replayed = client.post("/mcp/readonly", headers=headers, json=call)

    assert allowed.json()["result"]["content"][0]["text"] == "approved"
    assert replayed.json()["error"]["code"] == -32002
