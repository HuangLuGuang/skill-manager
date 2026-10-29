import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, iam_models as im, models
from backend.api_errors import ApiError, api_error_handler, validation_error_handler
from backend.routers import access_tokens, mcp_gateway
from backend.sqlite_db import Base, get_db


@pytest.mark.parametrize("outcome", ["success", "rpc_error", "tool_error", "tool_error_empty", "credential_limit", "tool_limit"])
def test_call_audit_final_outcomes(tmp_path, monkeypatch, outcome):
    client, sessions = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"jsonrpc": "2.0", "id": 17, "method": "tools/call",
               "params": {"name": "crm__search", "arguments": {"query": "test"}}}
    upstream_calls = []

    async def upstream(*args):
        # 运行中记录只在内存；结束前查询不到本次审计。
        with sessions() as db:
            assert db.query(models.McpCallAudit).count() == 0
        upstream_calls.append(args)
        if outcome == "rpc_error":
            return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "upstream error", "call_status": "denied"}}
        return {"jsonrpc": "2.0", "id": 1, "result": {
            "isError": outcome.startswith("tool_error"),
            "content": [] if outcome == "tool_error_empty" else [{"type": "text", "text": "result text"}],
        }}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", upstream)
    if outcome.endswith("limit"):
        def deny_slots(*args, **kwargs):
            raise mcp_gateway.LeaseLimitExceeded("full", subject_type=(
                "access_token" if outcome == "credential_limit" else "mcp_tool"))
        monkeypatch.setattr(mcp_gateway, "acquire_leases", deny_slots)
    response = client.post("/mcp/readonly", headers=headers, json=payload)
    assert response.status_code == (429 if outcome == "credential_limit" else 200)
    if outcome == "rpc_error":
        assert response.json()["error"]["call_status"] == "error"
    expected = "denied" if outcome.endswith("limit") else "success" if outcome == "success" else "error"
    rows = client.get("/api/v1/mcp/audit", params={"status": expected}).json()
    assert rows["total"] == 1
    assert rows["items"][0]["status"] == expected
    assert bool(upstream_calls) is (not outcome.endswith("limit"))
    if outcome == "tool_error":
        assert rows["items"][0]["error"] == "result text"
    if outcome == "tool_error_empty":
        assert rows["items"][0]["error"] == "mcp.tool_execution_failed"


def test_audit_status_filters_keep_legacy_records_and_pagination(tmp_path, monkeypatch):
    client, sessions = _client(tmp_path, monkeypatch)
    statuses = ["success", "error", "denied"]
    with sessions() as db:
        for status in statuses:
            for number in range(3):
                db.add(models.McpCallAudit(request_id=f"{status}-{number}", token_id=999,
                    gateway_slug="legacy", status=status, error="original reason"))
        db.commit()
    for status in statuses:
        pages = [client.get("/api/v1/mcp/audit", params={
            "status": status, "page_size": 2, "page": page, "sort_order": "asc",
        }).json() for page in (1, 2)]
        assert [page["total"] for page in pages] == [3, 3]
        assert [len(page["items"]) for page in pages] == [2, 1]
        assert [row["request_id"] for page in pages for row in page["items"]] == [f"{status}-{n}" for n in range(3)]
    assert client.get("/api/v1/mcp/audit", params={"status": "invalid"}).status_code == 422



def test_audit_reason_metadata_preserves_stored_evidence(tmp_path, monkeypatch):
    client, sessions = _client(tmp_path, monkeypatch)
    cases = [
        ("denied", "MCP Tool 调用等待管理员审批", "pending", {}),
        ("denied", "MCP Tool 调用已被管理员拒绝", "rejected", {}),
        ("denied", "Tool 参数不符合 Schema", "argumentsInvalid", {}),
        ("denied", "MCP Tool 每分钟调用次数已达上限", "rateLimit", {}),
        ("error", "上游 MCP 调用超时（配置超时：30 秒）", "timeout", {"seconds": 30}),
        ("error", "upstream raw error", None, {}),
        ("error", "MCP Tool 调用等待管理员审批", None, {}),
        ("denied", "unknown platform reason", None, {}),
    ]
    with sessions() as db:
        for index, (status, error, _, _) in enumerate(cases):
            db.add(models.McpCallAudit(request_id=f"reason-{index}", token_id=1,
                                      gateway_slug="test", status=status, error=error))
        db.commit()
    rows = client.get("/api/v1/mcp/audit", params={"sort_order": "asc"}).json()["items"]
    for row, (status, error, code, params) in zip(rows, cases):
        assert (row["status"], row["error"], row["reason_code"], row["reason_params"]) == (status, error, code, params)
    with sessions() as db:
        assert [row.error for row in db.query(models.McpCallAudit).order_by(models.McpCallAudit.id)] == [case[1] for case in cases]


def test_approval_deleted_credential_display(tmp_path, monkeypatch):
    client, sessions = _client(tmp_path, monkeypatch)
    with sessions() as db:
        token = models.AccessToken(name="approval-credential", token_type="mcp_gateway",
                                   token_hash="deleted-test", token_prefix="amat_test", status="revoked")
        db.add(token)
        db.flush()
        token_id = token.id
        db.add(models.McpToolApproval(
            approval_hash="deleted-credential", request_id="deleted-credential", token_id=token_id,
            gateway_slug="test", tool_name="echo", arguments_hash="hash", status="rejected",
            expires_at=datetime(2026, 1, 1), created_by="test",
        ))
        db.commit()
    # 吊销与删除分别判断；删除后历史审批仍能查询。
    for deleted in (False, True):
        if deleted:
            assert client.delete(f"/api/v1/access/tokens/{token_id}").status_code == 200
        detail = client.get("/api/v1/mcp/approval-requests/deleted-credential")
        listing = client.get("/api/v1/mcp/approval-requests", params={"q": "deleted-credential"})
        assert detail.status_code == listing.status_code == 200
        assert listing.json()["total"] == 1
        for row in (detail.json(), listing.json()["items"][0]):
            assert row["token_deleted"] is deleted
            assert row["token_name"] == ("" if deleted else "approval-credential")
            assert row["token_prefix"] == ("" if deleted else "amat_test")
            assert row["status"] == "rejected"


@pytest.mark.parametrize("day", [
    datetime(2026, 10, 23), datetime(2026, 11, 1), datetime(2027, 1, 1),
])
@pytest.mark.parametrize("elapsed", [
    timedelta(), timedelta(hours=7), timedelta(hours=7, minutes=59, seconds=59),
    timedelta(hours=8), timedelta(hours=9), timedelta(days=1, microseconds=-1),
])
def test_approval_stats_use_beijing_calendar_day(tmp_path, monkeypatch, day, elapsed):
    client, sessions = _client(tmp_path, monkeypatch)
    now_utc = day + elapsed - timedelta(hours=8)

    class FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return now_utc

        @classmethod
        def now(cls, tz=None):
            # 模拟非北京时间的服务器，统计边界必须显式指定时区。
            if tz is None:
                return now_utc - timedelta(hours=5)
            return now_utc.replace(tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(mcp_gateway, "datetime", FixedDatetime)
    start = day - timedelta(hours=8)
    end = start + timedelta(days=1)
    # UTC 存储覆盖北京时间昨日末尾、今日零点、凌晨及次日零点。
    times = [start - timedelta(microseconds=1), start, start + timedelta(hours=6, minutes=30),
             end - timedelta(microseconds=1), end, None]
    with sessions() as db:
        for status in ("approved", "used", "expired", "rejected"):
            for index, reviewed_at in enumerate([*times, start]):
                key = f"{status}-{index}"
                db.add(models.McpToolApproval(
                    approval_hash=key, request_id=key if index < len(times) else None,
                    token_id=1, gateway_slug="stats-test", tool_name="test_tool",
                    arguments_hash="hash", status=status, expires_at=datetime(2099, 1, 1),
                    created_by="test", created_at=start - timedelta(days=2),
                    reviewed_at=reviewed_at,
                ))
        db.add(models.McpToolApproval(
            approval_hash="pending", request_id="pending", token_id=1,
            gateway_slug="stats-test", tool_name="test_tool", arguments_hash="hash",
            status="pending", expires_at=datetime(2099, 1, 1), created_by="test",
        ))
        db.commit()
    response = client.get("/api/v1/mcp/approval-requests/stats")
    assert response.status_code == 200
    assert response.json() == {
        "pending": 1, "approved_today": 9, "rejected_today": 3, "expired": 6,
        "timed_out_today": 0, "approved_expired_today": 3,
    }


@pytest.mark.parametrize("day", [datetime(2026, 10, 28), datetime(2026, 11, 1), datetime(2027, 1, 1)])
def test_approval_statistics_drilldown_and_display(tmp_path, monkeypatch, day):
    client, sessions = _client(tmp_path, monkeypatch)
    start = day - timedelta(hours=8)
    now = start + timedelta(hours=12)

    class FixedDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return now

    monkeypatch.setattr(mcp_gateway, "datetime", FixedDatetime)
    # 申请日不同于审批日；跨日到期、未审批超时和拒绝分别保留业务含义。
    fixtures = [
        ("pending", "pending", None, now + timedelta(seconds=1), "pending", None),
        ("valid", "approved", start, now + timedelta(hours=1), "approved", "valid"),
        ("expired", "approved", start, now - timedelta(seconds=1), "approved", "expired"),
        ("old-approved", "approved", start - timedelta(microseconds=1), now - timedelta(seconds=1), "approved", "expired"),
        ("rejected", "rejected", start, start, "rejected", None),
        ("timeout", "pending", None, start, "timed_out", None),
        ("old-timeout", "expired", None, start - timedelta(microseconds=1), "timed_out", None),
        ("used", "used", start, now - timedelta(seconds=1), "approved", "used"),
        ("legacy-used", "used", None, start, "used", "used"),
        ("cancelled", "cancelled", None, start, "cancelled", None),
        ("active", "active", None, now + timedelta(hours=1), "active", None),
        ("boundary", "pending", None, now, "pending", None),
    ]
    with sessions() as db:
        for key, state, reviewed, expires, _, _ in fixtures:
            db.add(models.McpToolApproval(
                approval_hash=key, request_id=key, token_id=1,
                gateway_slug="stats-test", tool_name="test_tool", arguments_hash="hash",
                status=state, expires_at=expires, created_by="test",
                reviewed_at=reviewed, created_at=start - timedelta(days=2),
            ))
        db.commit()
    stats = client.get("/api/v1/mcp/approval-requests/stats").json()
    expected = {
        "pending": {"pending", "boundary"}, "approved_today": {"valid", "expired", "used"},
        "rejected_today": {"rejected"}, "timed_out_today": {"timeout"},
        "approved_expired_today": {"expired"},
    }
    for scope, ids in expected.items():
        response = client.get("/api/v1/mcp/approval-requests", params={"statistic": scope})
        assert response.status_code == 200
        assert response.json()["total"] == stats[scope] == len(ids)
        assert {item["request_id"] for item in response.json()["items"]} == ids
        paged_ids = set()
        for page in range(1, len(ids) + 1):
            data = client.get("/api/v1/mcp/approval-requests", params={"statistic": scope, "page_size": 1, "page": page}).json()
            assert data["total"] == len(ids)
            paged_ids.add(data["items"][0]["request_id"])
        assert paged_ids == ids
        narrowed = client.get("/api/v1/mcp/approval-requests", params={"statistic": scope, "q": "no-match"}).json()
        assert narrowed["total"] == 0
    assert client.get("/api/v1/mcp/approval-requests", params={"statistic": "unknown"}).status_code == 422
    listed = {row["request_id"]: row for row in client.get("/api/v1/mcp/approval-requests").json()["items"]}
    for key, _, _, _, result, authorization in fixtures:
        detail = client.get(f"/api/v1/mcp/approval-requests/{key}")
        assert detail.status_code == 200
        for row in (listed[key], detail.json()):
            assert (row["approval_result"], row["authorization_status"]) == (result, authorization)
    assert listed["rejected"]["status"] == "rejected"
    # 派生状态不写回，原生命周期状态和历史审批时间保留。
    with sessions() as db:
        assert db.query(models.McpToolApproval).filter_by(request_id="expired").one().reviewed_at == start


@pytest.mark.parametrize("status", [None, "pending", "approved,rejected,used,expired,cancelled"])
@pytest.mark.parametrize("bounds", [
    ("2026-10-13T04:43:03+08:00", "2026-10-13T09:00:00+08:00"),
    ("2026-10-12T20:43:03Z", "2026-10-13T01:00:00Z"),
    ("2026-10-12T20:43:03", "2026-10-13T01:00:00"),
])
def test_approval_requested_time_filter_timezone_and_boundaries(tmp_path, monkeypatch, status, bounds):
    client, sessions = _client(tmp_path, monkeypatch)
    start = datetime(2026, 10, 12, 20, 43, 3)
    end = datetime(2026, 10, 13, 1)
    times = [start - timedelta(seconds=1), start, start + timedelta(minutes=1), end, end + timedelta(seconds=1)]
    expected = set()
    with sessions() as db:
        for state in ("pending", "rejected", "expired"):
            for index, created_at in enumerate(times):
                request_id = f"{state}-{index}"
                db.add(models.McpToolApproval(
                    approval_hash=request_id, request_id=request_id, token_id=1,
                    gateway_slug="time-test", tool_name="test_tool", arguments_hash="hash",
                    status=state, expires_at=datetime(2099, 1, 1), created_by="test",
                    created_at=created_at,
                ))
                if index in (1, 2, 3) and (status is None or state in status.split(",")):
                    expected.add(request_id)
        db.commit()
    params = {"created_from": bounds[0], "created_to": bounds[1], "gateway_slug": "time-test"}
    if status:
        params["status"] = status
    response = client.get("/api/v1/mcp/approval-requests", params=params)
    assert response.status_code == 200
    assert {row["request_id"] for row in response.json()["items"]} == expected
    assert response.json()["total"] == len(expected)


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

    async def fake_post(server, payload, session_id=None, protocol_version=mcp_gateway.MCP_PROTOCOL_VERSION, *, client=None):
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

    async def fake_call(server, method, params, **_kwargs):
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
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1, username="admin", hashed_password="x", role="super_admin", is_active=True
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


def test_admin_can_debug_unsaved_endpoint_with_stored_or_temporary_credentials(tmp_path, monkeypatch):
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
        ("https://other.example.com/mcp", "Bearer stored-secret", "tools/list", {}),
        ("https://new.example.com/mcp", "Bearer temporary-secret", "ping", {}),
    ]
    assert client.post(
        "/api/v1/mcp/debug/upstream",
        json={"endpoint": "http://localhost:3000/mcp", "method": "ping"},
    ).status_code == 400


@pytest.mark.parametrize("endpoint", [
    "https://private.example.com/mcp",
    "https://private.example.com/mcp?changed=1",
    "https://private.example.com/updated",
    "https://other.example.com/mcp",
])
def test_edit_connection_uses_same_credentials_before_and_after_save(
    tmp_path, monkeypatch, endpoint,
):
    client, sessions = _client(tmp_path, monkeypatch)
    original_endpoint = "https://private.example.com/mcp"
    server = client.post("/api/v1/mcp/servers", json={
        "slug": "retention", "name": "Credential retention",
        "endpoint": original_endpoint, "authorization_value": "Bearer stored-secret",
    }).json()
    calls = []

    async def authenticated_call(target, method, params, **_kwargs):
        # 用真实请求入口验证测试与发现使用同一凭证，避免仅断言临时对象。
        secret = mcp_gateway._unprotect_secret(target.authorization_value)
        calls.append((target.endpoint, secret))
        if secret != "Bearer stored-secret":
            raise httpx.HTTPStatusError(
                "401 Unauthorized", request=httpx.Request("POST", target.endpoint),
                response=httpx.Response(401),
            )
        return {"result": {"tools": [
            {"name": f"tool_{index}", "inputSchema": {"type": "object"}}
            for index in range(6)
        ]}}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", authenticated_call)
    before = client.post("/api/v1/mcp/debug/upstream", json={
        "server_id": server["id"], "endpoint": endpoint, "method": "tools/list",
    })
    assert before.status_code == 200
    assert len(before.json()["response"]["result"]["tools"]) == 6
    assert "stored-secret" not in before.text
    with sessions() as db:
        stored = db.get(models.McpServer, server["id"])
        assert stored.endpoint == original_endpoint
        assert mcp_gateway._unprotect_secret(stored.authorization_value) == "Bearer stored-secret"
        assert db.query(models.McpTool).count() == 0
    saved = client.put(f"/api/v1/mcp/servers/{server['id']}", json={"endpoint": endpoint})
    assert saved.status_code == 200
    after = client.post(f"/api/v1/mcp/servers/{server['id']}/discover")
    assert after.status_code == 200
    assert len(after.json()["tools"]) == 6
    assert calls == [(endpoint, "Bearer stored-secret")] * 2


@pytest.mark.parametrize("value", [None, "", "Bearer temporary-secret"])
def test_edit_connection_explicit_credential_does_not_change_saved_value(
    tmp_path, monkeypatch, value,
):
    client, sessions = _client(tmp_path, monkeypatch)
    server = client.post("/api/v1/mcp/servers", json={
        "slug": "temporary", "name": "Temporary credential",
        "endpoint": "https://private.example.com/mcp",
        "authorization_value": "Bearer stored-secret",
    }).json()
    calls = []

    async def fake_call(target, method, params):
        calls.append(mcp_gateway._unprotect_secret(target.authorization_value))
        return {"result": {"tools": []}}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", fake_call)
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "server_id": server["id"], "endpoint": "https://private.example.com/mcp?changed=1",
        "authorization_value": value, "method": "tools/list",
    })
    assert response.status_code == 200
    assert calls == ["Bearer stored-secret" if value is None else value or None]
    with sessions() as db:
        stored = db.get(models.McpServer, server["id"])
        assert mcp_gateway._unprotect_secret(stored.authorization_value) == "Bearer stored-secret"


@pytest.mark.parametrize("can_update", [False, True])
@pytest.mark.parametrize("endpoint, credentials, has_secret, needs_update", [
    ("https://private.example.com/mcp", {}, True, False),
    ("https://private.example.com/mcp?changed=1", {}, True, True),
    ("https://private.example.com/updated", {"authorization_value": None}, True, True),
    ("https://other.example.com/mcp", {}, True, True),
    ("https://other.example.com/mcp", {"authorization_value": "Bearer temporary"}, True, False),
    ("https://other.example.com/mcp", {"authorization_value": ""}, True, False),
    ("https://other.example.com/mcp", {}, False, False),
])
def test_debug_saved_credential_endpoint_change_requires_update_permission(
    tmp_path, monkeypatch, can_update, endpoint, credentials, has_secret, needs_update,
):
    client, sessions = _client(tmp_path, monkeypatch)
    original_endpoint = "https://private.example.com/mcp"
    saved_secret = "Bearer saved-test-secret" if has_secret else None
    server = client.post("/api/v1/mcp/servers", json={
        "slug": "permission-test", "name": "Permission test",
        "endpoint": original_endpoint, "authorization_value": saved_secret,
    }).json()
    with sessions() as db:
        db.add(im.Role(name="mcp_test_role", display_name="MCP test role"))
        db.flush()
        permissions = ["mcp:execute"] + (["mcp:update"] if can_update else [])
        db.add_all(im.RolePermission(role_name="mcp_test_role", permission_code=code)
                   for code in permissions)
        db.add(models.User(
            username="mcp_test_user", hashed_password="unused",
            role="mcp_test_role", is_active=True,
        ))
        db.commit()
    # 保留真实认证与路由授权，验证执行权限不能代替编辑权限。
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({
        "sub": "mcp_test_user",
    })
    calls = []

    async def fake_call(target, method, params):
        calls.append((target.endpoint, mcp_gateway._unprotect_secret(target.authorization_value)))
        return {"result": {"tools": []}}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", fake_call)
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "server_id": server["id"], "endpoint": endpoint,
        "method": "tools/list", **credentials,
    })
    if needs_update and not can_update:
        assert response.status_code == 403
        assert response.json()["error_code"] == "iam.permission_denied"
        assert response.json()["error_params"]["permission"] == "mcp:update"
        assert calls == []
    else:
        assert response.status_code == 200
        value = credentials.get("authorization_value")
        expected = saved_secret if value is None else value or None
        assert calls == [(endpoint, expected)]
    assert "saved-test-secret" not in response.text
    with sessions() as db:
        stored = db.get(models.McpServer, server["id"])
        assert stored.endpoint == original_endpoint
        assert mcp_gateway._unprotect_secret(stored.authorization_value) == saved_secret


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
    assert denied.json()["error"]["call_status"] == "denied"

    invalid = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "crm__search", "arguments": {}}},
    )
    assert invalid.json()["error"]["message"] == "Tool 参数不符合 Schema"
    assert invalid.json()["error"]["call_status"] == "denied"

    called = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "crm__search", "arguments": {"query": "alice"}}},
    )
    assert called.json()["id"] == 5
    assert called.json()["result"]["content"][0]["text"] == "alice"

    audit = client.get("/api/v1/mcp/audit").json()["items"]
    assert [row["status"] for row in audit].count("denied") == 2
    success = next(row for row in audit if row["status"] == "success")
    assert success["gateway_slug"] == "readonly"
    assert success["server_slug"] == "crm"
    assert success["tool_name"] == "search"
    assert all(row["token_name"] == "readonly-client" and row["token_exists"] for row in audit)
    token_id = success["token_id"]
    with _testing_session() as db:
        db.get(models.AccessToken, token_id).name = "renamed-client"
        db.add(models.McpCallAudit(
            request_id="legacy-without-name", token_id=token_id,
            gateway_slug="readonly", status="success",
        ))
        db.commit()
    renamed = client.get("/api/v1/mcp/audit").json()["items"]
    assert renamed[0]["token_name"] == "renamed-client"
    assert all(row["token_name"] == "readonly-client" for row in renamed[1:])
    assert client.delete(f"/api/v1/access/tokens/{token_id}").status_code == 200
    deleted = client.get("/api/v1/mcp/audit").json()["items"]
    assert all(not row["token_exists"] for row in deleted)
    assert deleted[0]["token_name"] is None
    assert all(row["token_name"] == "readonly-client" for row in deleted[1:])


def test_audit_paginates_all_records_and_sorts_before_pagination(tmp_path, monkeypatch):
    client, sessions = _client(tmp_path, monkeypatch)
    with sessions() as db:
        db.add_all([
            models.McpCallAudit(
                request_id=f"page-{i:03}", token_id=25, token_name="Deleted credential",
                gateway_slug="gateway", status="success", duration_ms=(234 - i) // 2,
                created_at=datetime(2026, 10, 1) + timedelta(minutes=i),
            ) for i in range(235)
        ])
        db.commit()
    endpoint = "/api/v1/mcp/audit"
    first = client.get(endpoint).json()
    assert (first["total"], first["page"], first["page_size"], len(first["items"])) == (235, 1, 10, 10)
    assert first["items"][0]["request_id"] == "page-234"
    pages = [client.get(endpoint, params={"page": page, "page_size": 100}).json() for page in (1, 2, 3)]
    assert [len(page["items"]) for page in pages] == [100, 100, 35]
    assert len({row["id"] for page in pages for row in page["items"]}) == 235
    assert pages[-1]["items"][-1]["request_id"] == "page-000"
    for field in ("created_at", "duration_ms"):
        result = client.get(endpoint, params={"sort_by": field, "sort_order": "asc", "page": 2, "page_size": 100}).json()
        expected = ("page-100", "page-199") if field == "created_at" else ("page-133", "page-036")
        assert (result["items"][0]["request_id"], result["items"][-1]["request_id"]) == expected
    slowest = client.get(endpoint, params={"sort_by": "duration_ms", "sort_order": "desc"}).json()
    assert [row["request_id"] for row in slowest["items"][:3]] == ["page-000", "page-002", "page-001"]
    assert client.get(endpoint, params={"page": 99}).json()["items"] == []
    for params in ({"page_size": 101}, {"page": 0}, {"sort_by": "token_hash"}, {"sort_order": "invalid"}):
        assert client.get(endpoint, params=params).status_code == 422


def test_audit_filters_share_total_and_preserve_snapshot_names(tmp_path, monkeypatch):
    client, sessions = _client(tmp_path, monkeypatch)
    with sessions() as db:
        token = models.AccessToken(name="Current name", token_type="mcp_gateway", token_hash="test", token_prefix="test")
        db.add(token)
        db.flush()
        start = datetime(2026, 10, 25, 16)
        end = datetime(2026, 10, 26, 15, 59, 59, 999999)
        for index, stamp in enumerate((start - timedelta(microseconds=1), start, end, end + timedelta(microseconds=1))):
            db.add(models.McpCallAudit(
                request_id=f"request_{index}", token_id=token.id, token_name="Original name",
                gateway_slug="finance", server_slug="crm", tool_name="search", status="denied", created_at=stamp,
            ))
        db.add(models.McpCallAudit(
            request_id="legacy", token_id=token.id, gateway_slug="finance", status="success",
        ))
        db.commit()
    endpoint = "/api/v1/mcp/audit"
    params = {
        "request_id": "request_", "target": "crm", "token_name": "Original", "status": "denied",
        "created_from": "2026-10-26T00:00:00+08:00", "created_to": "2026-10-26T23:59:59.999999+08:00",
        "page_size": 1,
    }
    result = client.get(endpoint, params=params).json()
    assert result["total"] == 2
    assert [item["request_id"] for item in result["items"]] == ["request_2"]
    assert client.get(endpoint, params={**params, "page": 2}).json()["items"][0]["request_id"] == "request_1"
    assert client.get(endpoint, params={"token_name": "Current"}).json()["items"][0]["request_id"] == "legacy"
    assert client.get(endpoint, params={"request_id": "%"}).json()["total"] == 0
    assert client.get(endpoint, params={"request_id": "_"}).json()["total"] == 4
    for target in ("finance", "search"):
        assert client.get(endpoint, params={**params, "target": target}).json()["total"] == 2


def test_p6_tool_access_modes_and_production_denylist_are_enforced_before_upstream(tmp_path, monkeypatch):
    client, testing_session = _client(tmp_path, monkeypatch)
    gateway = _configured_gateway(client)
    server = client.get("/api/v1/mcp/servers").json()[0]
    tools = {tool["name"]: tool for tool in server["tools"]}
    for name, access_mode in (("search", "read"), ("delete", "destructive")):
        response = client.put(
            f"/api/v1/mcp/tools/{tools[name]['id']}/policy",
            json={
                "access_mode": access_mode,
                "risk_level": "high" if access_mode == "destructive" else "low",
                "rate_limit_per_minute": 60,
                "max_concurrent": 5,
                "requires_approval": False,
            },
        )
        assert response.status_code == 200
        assert response.json()["access_mode"] == access_mode
    configured = client.put(
        f"/api/v1/mcp/gateways/{gateway['id']}",
        json={
            "environment": "production",
            "execution_mode": "read_only",
            "bindings": [{"server_id": server["id"], "allowed_tools": ["search", "delete"]}],
            "production_tool_denylist": ["crm__delete"],
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["production_tool_denylist"] == ["crm__delete"]
    token = _gateway_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    listed = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    ).json()
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["crm__search"]
    read_only_denied = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "crm__delete", "arguments": {}}},
    ).json()
    assert read_only_denied["error"]["code"] == -32005
    assert read_only_denied["error"]["data"]["error_code"] == "mcp.write_tool_blocked_by_read_only_mode"

    updated = client.put(
        f"/api/v1/mcp/gateways/{gateway['id']}",
        json={"execution_mode": "active_safe"},
    )
    assert updated.status_code == 200
    denylisted = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "crm__delete", "arguments": {}}},
    ).json()
    assert denylisted["error"]["code"] == -32006
    assert denylisted["error"]["data"]["error_code"] == "mcp.tool_blocked_by_production_denylist"

    db = testing_session()
    try:
        denied_audits = db.query(models.McpCallAudit).filter(models.McpCallAudit.status == "denied").all()
        assert {row.error for row in denied_audits} >= {
            "只读 MCP 网关禁止调用非只读 Tool",
            "Tool 已被生产环境 denylist 阻断",
        }
        risk_codes = {
            code
            for event in db.query(models.RuntimeTraceEvent).filter(models.RuntimeTraceEvent.type == "mcp.error").all()
            for code in json.loads(event.risk_codes_json)
        }
        assert "mcp.write_tool_blocked_by_read_only_mode" in risk_codes
        assert "mcp.tool_blocked_by_production_denylist" in risk_codes
    finally:
        db.close()


def test_p6_production_gateway_rejects_active_full_and_unbound_denylist(tmp_path, monkeypatch):
    client, testing_session = _client(tmp_path, monkeypatch)
    gateway = _configured_gateway(client)
    forbidden = client.put(
        f"/api/v1/mcp/gateways/{gateway['id']}",
        json={"environment": "production", "execution_mode": "active_full"},
    )
    assert forbidden.status_code == 422
    assert forbidden.json()["error_code"] == "mcp.production_active_full_forbidden"
    invalid = client.put(
        f"/api/v1/mcp/gateways/{gateway['id']}",
        json={"environment": "production", "production_tool_denylist": ["crm__delete"]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "mcp.production_tool_denylist_invalid"

    with testing_session() as db:
        row = db.query(models.McpGateway).filter(models.McpGateway.id == gateway["id"]).first()
        row.environment = "production"
        row.execution_mode = "active_full"
        db.commit()
    headers = {"Authorization": f"Bearer {_gateway_token(client)}"}
    listed = client.post(
        "/mcp/readonly",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    ).json()
    assert listed["result"]["tools"] == []
    denied = client.post(
        "/mcp/readonly",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "crm__search", "arguments": {"query": "alice"}},
        },
    ).json()
    assert denied["error"]["code"] == -32005
    assert denied["error"]["data"]["error_code"] == "mcp.production_active_full_forbidden"


def test_agent_runtime_composite_token_can_use_bound_mcp_gateway(tmp_path, monkeypatch):
    client, testing_session = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    db = testing_session()
    db.add(
        models.ManagedAgent(
            agent_id="research-agent",
            name="Research Agent",
            allowed_mcp_gateways_json='["readonly"]',
            status="active",
            skill_names_json="[]",
            prompt_names_json="[]",
        )
    )
    db.commit()
    db.close()
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "research-runtime",
            "token_type": "agent_runtime",
            "bound_agent_id": "research-agent",
            "scopes": [
                "runtime:verify-signature",
                "runtime:can-load",
                "runtime:check-tool",
                "model:chat",
                "mcp:connect",
                "mcp:list-tools",
                "mcp:call-tools",
            ],
            "allowed_mcp_gateways": ["readonly"],
        },
    )
    assert created.status_code == 200

    listed = client.post(
        "/mcp/readonly",
        headers={"Authorization": f"Bearer {created.json()['token']}"},
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}},
    )

    assert listed.status_code == 200
    assert [tool["name"] for tool in listed.json()["result"]["tools"]] == ["crm__search"]


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
    assert client.get("/api/v1/mcp/audit").json()["items"][0]["status"] == "denied"

    db = testing_session()
    db.add(models.McpGateway(slug="other", name="Other Gateway", status="active"))
    db.commit()
    db.close()
    wrong_token = client.post(
        "/api/v1/access/tokens",
        json={"name": "no-access", "token_type": "mcp_gateway", "allowed_mcp_gateways": ["other"]},
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


@pytest.mark.parametrize("risk_level", ["low", "medium", "high"])
def test_risk_level_call_creates_time_bound_tool_authorization(
    tmp_path, monkeypatch, risk_level,
):
    client, testing_session = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    search_tool = next(tool for tool in client.get("/api/v1/mcp/servers").json()[0]["tools"] if tool["name"] == "search")
    client.put(
        f"/api/v1/mcp/tools/{search_tool['id']}/policy",
        json={
            "risk_level": risk_level,
            "rate_limit_per_minute": 10,
            "max_concurrent": 1,
            "requires_approval": True,
        },
    )
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "workflow-client",
            "token_type": "mcp_gateway",
            "allowed_mcp_gateways": ["readonly"],
        },
    ).json()
    headers = {"Authorization": f"Bearer {created['token']}"}
    arguments = {"query": "approved", "api_token": "sensitive-value"}
    call = {
        "jsonrpc": "2.0",
        "id": 31,
        "method": "tools/call",
        "params": {"name": "crm__search", "arguments": arguments},
    }

    first = client.post("/mcp/readonly", headers=headers, json=call).json()
    different_arguments_call = {
        **call,
        "params": {"name": "crm__search", "arguments": {"query": "different while pending"}},
    }
    duplicate = client.post("/mcp/readonly", headers=headers, json=different_arguments_call).json()
    request_id = first["error"]["data"]["approval_request_id"]
    assert first["error"]["data"]["status"] == "pending"
    assert first["error"]["call_status"] == "denied"
    assert duplicate["error"]["data"]["approval_request_id"] == request_id

    listed = client.get("/api/v1/mcp/approval-requests", params={"status": "pending"}).json()
    assert listed["total"] == 1
    # 启用审批不改变工具风险等级，列表与详情返回同一等级。
    assert listed["items"][0]["risk_level"] == risk_level
    assert listed["items"][0]["token_name"] == "workflow-client"
    assert listed["items"][0]["arguments"]["api_token"] == "******"
    revealed = client.get(
        f"/api/v1/mcp/approval-requests/{request_id}",
        params={"reveal_arguments": True},
    ).json()
    assert revealed["risk_level"] == risk_level
    assert revealed["arguments"]["api_token"] == "sensitive-value"

    approved = client.post(
        f"/api/v1/mcp/approval-requests/{request_id}/approve",
        json={"ttl_seconds": 60, "comment": "verified"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    status = client.get(f"/mcp/readonly/approvals/{request_id}", headers=headers).json()
    assert status["status"] == "approved"

    allowed = client.post("/mcp/readonly", headers=headers, json=call).json()
    replayed = client.post("/mcp/readonly", headers=headers, json=different_arguments_call).json()
    assert allowed["result"]["content"][0]["text"] == "approved"
    assert replayed["result"]["content"][0]["text"] == "different while pending"

    db = testing_session()
    try:
        row = db.query(models.McpToolApproval).filter(models.McpToolApproval.request_id == request_id).one()
        assert row.status == "approved"
        assert row.reviewed_by == "admin"
        assert row.use_count == 2
        assert row.first_used_at is not None
        assert row.last_used_at is not None
        successes = db.query(models.McpCallAudit).filter(models.McpCallAudit.status == "success").all()
        assert len(successes) == 2
        assert {success.approval_request_id for success in successes} == {request_id}
        assert db.query(models.McpCallAudit).filter_by(status="denied").count() == 2
    finally:
        db.close()


def test_rejected_mcp_approval_request_cannot_be_consumed(tmp_path, monkeypatch):
    client, _testing_session = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    search_tool = next(tool for tool in client.get("/api/v1/mcp/servers").json()[0]["tools"] if tool["name"] == "search")
    client.put(
        f"/api/v1/mcp/tools/{search_tool['id']}/policy",
        json={
            "risk_level": "high",
            "rate_limit_per_minute": 10,
            "max_concurrent": 1,
            "requires_approval": True,
        },
    )
    token = _gateway_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    call = {
        "jsonrpc": "2.0",
        "id": 41,
        "method": "tools/call",
        "params": {"name": "crm__search", "arguments": {"query": "blocked"}},
    }
    request_id = client.post("/mcp/readonly", headers=headers, json=call).json()["error"]["data"]["approval_request_id"]
    rejected = client.post(
        f"/api/v1/mcp/approval-requests/{request_id}/reject",
        json={"reason": "scope is too broad"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    call["params"]["_meta"] = {"agent_manager_approval_request": request_id}
    denied = client.post("/mcp/readonly", headers=headers, json=call).json()
    assert denied["error"]["message"] == "MCP Tool 调用已被管理员拒绝"
    assert denied["error"]["data"]["reason"] == "scope is too broad"
    assert denied["error"]["call_status"] == "denied"
    # 拒绝只影响重试结果；原待审批调用保持当时状态。
    rows = client.get("/api/v1/mcp/audit").json()["items"]
    assert [row["status"] for row in rows] == ["denied", "denied"]
    assert {row["approval_request_id"] for row in rows} == {request_id}
    call["params"].pop("_meta")
    new_request = client.post("/mcp/readonly", headers=headers, json=call).json()
    assert new_request["error"]["data"]["approval_request_id"] != request_id
    assert client.get("/api/v1/mcp/audit").json()["items"][0]["status"] == "denied"


@pytest.mark.parametrize("operation", ["connection_failed", "debug_failed"])
@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_mcp_http_failure_is_localized(tmp_path, monkeypatch, operation, locale):
    client, session_factory = _client(tmp_path, monkeypatch)
    server = client.post("/api/v1/mcp/servers", json={
        "slug": "failure", "name": "Failure", "endpoint": "https://mcp.example.com/mcp",
    }).json()

    async def fail_call(*_args, **_kwargs):
        response = httpx.Response(405, request=httpx.Request("POST", server["endpoint"]))
        response.raise_for_status()

    monkeypatch.setattr(mcp_gateway, "_call_upstream", fail_call)
    path = (f"/api/v1/mcp/servers/{server['id']}/discover"
            if operation == "connection_failed" else "/api/v1/mcp/debug/upstream")
    response = client.post(path, json={"server_id": server["id"], "method": "tools/list"},
                           headers={"Accept-Language": locale})
    assert response.status_code == 502
    data = response.json()
    assert data["error_code"] == f"mcp.{operation}.http_status"
    assert "405 Method Not Allowed" in data["detail"]
    assert server["endpoint"] in data["detail"]
    assert "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/405" in data["detail"]
    if locale == "zh-CN":
        assert "更多信息请参阅" in data["detail"]
        assert "For more information" not in data["detail"]
        assert "Client error" not in data["detail"]
    else:
        assert "For more information check" in data["detail"]
    if operation == "connection_failed":
        with session_factory() as db:
            assert db.get(models.McpServer, server["id"]).health_status == "unhealthy"


def test_mcp_non_http_failure_preserves_original_reason(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)

    async def fail_call(*_args):
        raise ValueError("upstream original reason")

    monkeypatch.setattr(mcp_gateway, "_call_upstream", fail_call)
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "endpoint": "https://mcp.example.com/mcp", "method": "tools/list",
    }, headers={"Accept-Language": "en-US"})
    assert response.status_code == 502
    assert response.json()["error_code"] == "mcp.debug_failed"
    assert response.json()["detail"] == "MCP debugging failed: upstream original reason"


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_mcp_server_field_errors_are_specific_and_safe(tmp_path, monkeypatch, locale):
    client, _ = _client(tmp_path, monkeypatch)
    base = {"slug": "valid", "name": "Valid", "endpoint": "https://mcp.example.com/mcp"}
    server_id = client.post("/api/v1/mcp/servers", json=base).json()["id"]
    base["slug"] = "candidate"
    cases = [
        ("name", "  ", "required"), ("name", "😀" * 129, "length"),
        ("slug", "test -github", "slug"), ("slug", "A", "slug"),
        ("slug", "a" * 129, "length"),
        ("endpoint", "https://mcp.example.com/" + "a" * 1024, "length"),
        ("endpoint", "not-url", "url"), ("endpoint", "https://example.com:bad", "url"),
        ("endpoint", "https://example.com/a b", "url"),
        ("authorization_header", "a" * 129, "length"),
        ("authorization_header", "Bad Header", "header"),
        ("authorization_header", " ", "required"),
        ("authorization_value", "secret" * 700, "length"),
        ("authorization_value", "secret\nvalue", "value"),
        ("description", "😀" * 2001, "length"),
        ("status", "bad", "status"),
        ("timeout_seconds", 0, "integer"), ("timeout_seconds", 301, "integer"),
        ("timeout_seconds", 1.5, "integer"), ("timeout_seconds", None, "required"),
        ("max_response_kb", 10241, "integer"), ("max_response_kb", True, "integer"),
        ("max_response_kb", "9" * 5000, "integer"),
    ]
    for field, value, reason in cases:
        for update in (False, True):
            if update and field == "slug":
                continue
            path = f"/api/v1/mcp/servers/{server_id}" if update else "/api/v1/mcp/servers"
            payload = {field: value} if update else {**base, field: value}
            response = (client.put if update else client.post)(
                path, json=payload, headers={"Accept-Language": locale},
            )
            assert response.status_code in {400, 422}, (field, response.text)
            data = response.json()
            assert data["error_code"] == "mcp.server.invalid_fields"
            assert data["error_params"]["errors"][0]["field"] == field
            assert data["error_params"]["errors"][0]["reason"] == reason
            assert "请求参数无效" not in data["detail"]
            if field == "authorization_value":
                assert "secret" not in response.text


def test_mcp_limits_boundaries_and_partial_update_compatibility(tmp_path, monkeypatch):
    from backend.schemas import McpServerCreate

    body = McpServerCreate(
        name="  " + "😀" * 128 + "  ", slug="a" * 128,
        endpoint="https://mcp.example.com/" + "a" * (1024 - len("https://mcp.example.com/")),
        authorization_header="a" * 128, authorization_value="a" * 4096,
        description="😀" * 2000, timeout_seconds=300, max_response_kb=10240,
    )
    assert len(body.name) == 128
    assert len(body.endpoint) == 1024
    assert McpServerCreate(name="n", slug="s", endpoint="https://example.com",
                           timeout_seconds=1, max_response_kb=1).timeout_seconds == 1
    client, sessions = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/mcp/servers", json={
        "name": "Name", "slug": "unique", "endpoint": "https://mcp.example.com/mcp",
        "authorization_value": "Bearer private-secret",
    }).json()
    with sessions() as db:
        record = db.get(models.McpServer, created["id"])
        secret = record.authorization_value
        record.description = "x" * 2500
        db.commit()
    updated = client.put(f"/api/v1/mcp/servers/{created['id']}", json={"status": "disabled"})
    assert updated.status_code == 200
    with sessions() as db:
        record = db.get(models.McpServer, created["id"])
        assert record.authorization_value == secret
        assert len(record.description) == 2500
    duplicate = client.post("/api/v1/mcp/servers", json={
        "name": "Other", "slug": "unique", "endpoint": "https://mcp.example.com/mcp",
    }).json()
    assert duplicate["error_params"]["errors"][0]["reason"] == "duplicate"
    invalid = client.post("/api/v1/mcp/servers", json={"name": "", "slug": ""}).json()
    assert {item["field"] for item in invalid["error_params"]["errors"]} == {"name", "slug", "endpoint"}


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
@pytest.mark.parametrize("value", [" ", "   ", "\t", "\r\n", "\u3000"])
def test_mcp_debug_rejects_whitespace_credentials(tmp_path, monkeypatch, locale, value):
    client, sessions = _client(tmp_path, monkeypatch)
    saved = client.post("/api/v1/mcp/servers", json={
        "name": "Debug", "slug": "debug-auth", "endpoint": "https://mcp.example.com/mcp",
        "authorization_value": "Bearer saved-test-token",
    }).json()

    async def unexpected_call(*args, **kwargs):
        pytest.fail("纯空白鉴权值不得发送上游请求")

    monkeypatch.setattr(mcp_gateway, "_call_upstream", unexpected_call)
    response = client.post(
        "/api/v1/mcp/debug/upstream", headers={"Accept-Language": locale},
        json={"server_id": saved["id"], "authorization_value": value, "method": "tools/list"},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "mcp.server.invalid_fields"
    assert data["error_params"]["errors"] == [
        {"field": "authorization_value", "reason": "whitespace"},
    ]
    expected = "不能仅包含空白字符" if locale == "zh-CN" else "must not contain only whitespace"
    assert expected in data["detail"]
    assert "saved-test-token" not in response.text
    with sessions() as db:
        stored = db.get(models.McpServer, saved["id"])
        assert mcp_gateway._unprotect_secret(stored.authorization_value) == "Bearer saved-test-token"


@pytest.mark.parametrize("credentials, expected", [
    ({}, "Bearer saved-test-token"),
    ({"authorization_value": None}, "Bearer saved-test-token"),
    ({"authorization_value": ""}, None),
    ({"authorization_value": "Bearer temporary-test-token"}, "Bearer temporary-test-token"),
    ({"authorization_value": "Custom token with spaces"}, "Custom token with spaces"),
])
def test_mcp_debug_preserves_valid_credential_semantics(
    tmp_path, monkeypatch, credentials, expected,
):
    client, sessions = _client(tmp_path, monkeypatch)
    saved = client.post("/api/v1/mcp/servers", json={
        "name": "Debug", "slug": "debug-auth", "endpoint": "https://mcp.example.com/mcp",
        "authorization_value": "Bearer saved-test-token",
    }).json()
    calls = []

    async def capture_call(server, method, params):
        calls.append(mcp_gateway._unprotect_secret(server.authorization_value))
        return {"jsonrpc": "2.0", "id": "debug", "result": {"tools": []}}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", capture_call)
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "server_id": saved["id"], "method": "tools/list", **credentials,
    })
    assert response.status_code == 200
    assert calls == [expected]
    # 临时鉴权值仅用于本次调试，不覆盖服务配置。
    with sessions() as db:
        stored = db.get(models.McpServer, saved["id"])
        assert mcp_gateway._unprotect_secret(stored.authorization_value) == "Bearer saved-test-token"


def test_mcp_preview_field_validation_and_other_api_errors_unchanged(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "endpoint": "https://mcp.example.com/mcp", "method": "tools/list",
        "authorization_value": "private-secret\r\nheader",
    })
    assert response.status_code == 422
    assert "private-secret" not in response.text
    assert response.json()["error_params"]["errors"][0]["field"] == "authorization_value"
    assert client.post("/api/v1/mcp/gateways", json={}).json()["error_code"] == "request.validation_failed"


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
@pytest.mark.parametrize("invalid_field", [{"method": "invalid-method"}, {"server_id": "invalid-id"}])
@pytest.mark.parametrize("secret", ["private-secret\ninvalid", "private-secret" * 400])
def test_mcp_mixed_validation_errors_do_not_echo_credentials(
    tmp_path, monkeypatch, locale, invalid_field, secret,
):
    client, _ = _client(tmp_path, monkeypatch)
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "endpoint": "https://mcp.example.com/mcp", "method": "tools/list",
        "authorization_value": secret, **invalid_field,
    }, headers={"Accept-Language": locale})
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "request.validation_failed"
    errors = data["error_params"]["errors"]
    assert {error["loc"][-1] for error in errors} == {"authorization_value", *invalid_field}
    assert all(set(error) == {"loc", "type"} for error in errors)
    assert "private-secret" not in response.text


def test_mcp_debug_optional_null_fields_keep_saved_configuration(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    record = client.post("/api/v1/mcp/servers", json={
        "slug": "optional", "name": "Optional", "endpoint": "https://mcp.example.com/mcp",
    }).json()
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "server_id": record["id"], "endpoint": None, "authorization_header": None,
        "authorization_value": None, "method": "tools/list",
    })
    assert response.status_code == 200


@pytest.mark.parametrize("allow_http", [False, True])
def test_mcp_server_options_match_endpoint_protocol_policy(tmp_path, monkeypatch, allow_http):
    client, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_gateway.settings, "MCP_ALLOW_HTTP", allow_http)
    options = client.get("/api/v1/mcp/servers/options")
    assert options.status_code == 200
    assert options.json() == {"allow_http": allow_http}
    response = client.post("/api/v1/mcp/servers", json={
        "name": "Protocol", "slug": "protocol", "endpoint": "http://mcp.example.com/mcp",
    })
    if allow_http:
        assert response.status_code == 200
    else:
        assert response.status_code == 400
        assert response.json()["error_params"]["errors"][0] == {
            "field": "endpoint", "reason": "https",
        }


@pytest.mark.parametrize("health", ["healthy", "unhealthy"])
@pytest.mark.parametrize("changes, reset", [
    ({"endpoint": "https://mcp.example.com/alternate"}, True),
    ({"authorization_header": "X-Api-Key"}, True),
    ({"authorization_value": "Bearer changed-test-secret"}, True),
    ({"authorization_value": ""}, True),
    ({"endpoint": " https://mcp.example.com/mcp "}, False),
    ({"authorization_header": " Authorization "}, False),
    ({"authorization_value": "Bearer upstream-secret"}, False),
    ({"authorization_value": None}, False),
    ({"name": "Renamed", "description": "Updated description"}, False),
    ({"status": "disabled", "timeout_seconds": 60, "max_response_kb": 2048}, False),
    ({}, False),
])
def test_server_health_tracks_effective_connection_changes(tmp_path, monkeypatch, health, changes, reset):
    """连接配置实际变化才使旧检测失效，留空保留凭据等编辑沿用原结果。"""
    client, sessions = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    server = client.get("/api/v1/mcp/servers").json()[0]
    checked_at = datetime(2026, 10, 18, 1, 2, 3)
    with sessions() as db:
        row = db.get(models.McpServer, server["id"])
        row.health_status = health
        row.last_checked_at = checked_at
        db.commit()
    response = client.put(f"/api/v1/mcp/servers/{server['id']}", json=changes)
    assert response.status_code == 200
    expected_health = "unknown" if reset else health
    expected_time = None if reset else checked_at
    assert response.json()["health_status"] == expected_health
    assert response.json()["last_checked_at"] == (expected_time.isoformat() if expected_time else None)
    assert len(response.json()["tools"]) == 2
    with sessions() as db:
        row = db.get(models.McpServer, server["id"])
        assert row.health_status == expected_health
        assert row.last_checked_at == expected_time
        expected_secret = changes.get("authorization_value")
        if expected_secret is None:
            expected_secret = "Bearer upstream-secret"
        assert mcp_gateway._unprotect_secret(row.authorization_value) == (expected_secret or None)
    listed = client.get("/api/v1/mcp/servers").json()
    assert next(row for row in listed if row["id"] == server["id"])["health_status"] == expected_health


def test_server_health_recovers_after_authentication_failure(tmp_path, monkeypatch):
    """验证正常、配置变更、401 失败和恢复的完整服务端状态流。"""
    client, _sessions = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    server = client.get("/api/v1/mcp/servers").json()[0]
    path = f"/api/v1/mcp/servers/{server['id']}"

    async def authenticated_call(target, _method, _params, **_kwargs):
        if mcp_gateway._unprotect_secret(target.authorization_value) != "Bearer upstream-secret":
            httpx.Response(401, request=httpx.Request("POST", target.endpoint)).raise_for_status()
        return {"result": {"tools": [{"name": "search", "inputSchema": {"type": "object"}}]}}

    monkeypatch.setattr(mcp_gateway, "_call_upstream", authenticated_call)
    changed = client.put(path, json={"authorization_value": "Bearer wrong-test-secret"})
    assert changed.json()["health_status"] == "unknown"
    failed = client.post(f"{path}/discover")
    assert failed.status_code == 502
    assert failed.json()["error_code"] == "mcp.connection_failed.http_status"
    listed = client.get("/api/v1/mcp/servers").json()
    assert next(row for row in listed if row["id"] == server["id"])["health_status"] == "unhealthy"
    restored = client.put(path, json={"authorization_value": "Bearer upstream-secret"})
    assert restored.json()["health_status"] == "unknown"
    discovered = client.post(f"{path}/discover")
    assert discovered.status_code == 200
    assert discovered.json()["health_status"] == "healthy"
    assert discovered.json()["last_checked_at"] is not None


@pytest.mark.parametrize("value", [None, "", "Bearer added-test-secret"])
def test_server_health_without_existing_authentication(tmp_path, monkeypatch, value):
    """无凭据时保留空值不使检测失效，新增凭据需要重新检测。"""
    client, _sessions = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/mcp/servers", json={
        "slug": "no-auth", "name": "No auth", "endpoint": "https://mcp.example.com/mcp",
    }).json()
    path = f"/api/v1/mcp/servers/{created['id']}"
    discovered = client.post(f"{path}/discover").json()
    assert discovered["health_status"] == "healthy"
    updated = client.put(path, json={"authorization_value": value})
    assert updated.status_code == 200
    assert updated.json()["health_status"] == ("unknown" if value else "healthy")
    assert updated.json()["last_checked_at"] == (None if value else discovered["last_checked_at"])


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
@pytest.mark.parametrize("failure", [
    "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout", "json_limit", "sse_limit",
])
def test_gateway_upstream_limits_return_specific_errors_and_release_slots(
    tmp_path, monkeypatch, locale, failure,
):
    client, sessions = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)
    with sessions() as db:
        server = db.query(models.McpServer).one()
        server.timeout_seconds = 4
        server.max_response_kb = 1
        db.query(models.McpTool).filter_by(name="search").one().max_concurrent = 1
        db.commit()

    async def failing_call(server, method, params):
        if failure.endswith("Timeout"):
            raise getattr(httpx, failure)("")
        content_type = "text/event-stream" if failure == "sse_limit" else "application/json"
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": content_type}, content=b"x" * 1025,
        ))
        async with httpx.AsyncClient(transport=transport) as upstream:
            result, _ = await mcp_gateway._post_upstream(server, {"id": 1}, client=upstream)
            return result

    monkeypatch.setattr(mcp_gateway, "_validate_resolved_endpoint", lambda _: ["93.184.216.34"])
    monkeypatch.setattr(mcp_gateway, "_call_upstream", failing_call)
    payload = {"jsonrpc": "2.0", "id": 17, "method": "tools/call",
               "params": {"name": "crm__search", "arguments": {"query": "repro"}}}
    headers = {"Authorization": f"Bearer {token}", "Accept-Language": locale}
    response = client.post("/mcp/readonly", headers=headers, json=payload)
    error = response.json()["error"]
    assert response.status_code == 200
    assert response.json()["id"] == 17
    assert error["code"] == -32000
    timeout = failure.endswith("Timeout")
    expected_code = "mcp.upstream_timeout" if timeout else "mcp.upstream_response_too_large"
    expected_params = {"timeout_seconds": 4} if timeout else {"max_response_kb": 1}
    assert error["data"] == {"error_code": expected_code, "error_params": expected_params}
    expected = {
        (True, "zh-CN"): "上游 MCP 调用超时（配置超时：4 秒）",
        (True, "en-US"): "Upstream MCP call timed out (configured timeout: 4 seconds)",
        (False, "zh-CN"): "上游 MCP 响应超过限制：1 KB",
        (False, "en-US"): "Upstream MCP response exceeds the limit: 1 KB",
    }[timeout, locale]
    assert error["message"] == expected
    audit = client.get("/api/v1/mcp/audit").json()["items"]
    assert audit[0]["status"] == "error"
    assert audit[0]["error"] == {
        True: "上游 MCP 调用超时（配置超时：4 秒）",
        False: "上游 MCP 响应超过限制：1 KB",
    }[timeout]

    # 失败后再调用同一并发上限为1的工具，验证租约已释放。
    async def success(*args):
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
    monkeypatch.setattr(mcp_gateway, "_call_upstream", success)
    assert "result" in client.post("/mcp/readonly", headers=headers, json=payload).json()


@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.parametrize("extra", [0, 1])
def test_upstream_response_byte_limit_boundary(monkeypatch, sse, extra):
    monkeypatch.setattr(mcp_gateway, "_validate_resolved_endpoint", lambda _: ["93.184.216.34"])
    raw = b'data: {"id":1,"result":{}}\n\n' if sse else b'{"id":1,"result":{}}'
    raw += b" " * (1024 + extra - len(raw))
    closed = []

    class ResponseStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw[:1000]
            yield raw[1000:]

        async def aclose(self):
            closed.append(True)

    async def run():
        server = models.McpServer(endpoint="https://mcp.example.com/mcp", max_response_kb=1)
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream" if sse else "application/json"},
            stream=ResponseStream(),
        ))
        async with httpx.AsyncClient(transport=transport) as upstream:
            if extra:
                with pytest.raises(ValueError, match="1 KB"):
                    await mcp_gateway._post_upstream(server, {"id": 1}, client=upstream)
            else:
                result, _ = await mcp_gateway._post_upstream(server, {"id": 1}, client=upstream)
                assert result == {"id": 1, "result": {}}
    asyncio.run(run())
    assert closed == [True]


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
@pytest.mark.parametrize("timeout", [True, False])
@pytest.mark.parametrize("operation", ["debug", "discover"])
def test_admin_reports_upstream_limits(tmp_path, monkeypatch, locale, timeout, operation):
    client, sessions = _client(tmp_path, monkeypatch)
    server = client.post("/api/v1/mcp/servers", json={
        "slug": "limits", "name": "Limits", "endpoint": "https://mcp.example.com/mcp",
        "timeout_seconds": 4,
    }).json()

    async def failing_call(server, method, params, **_kwargs):
        if timeout:
            raise httpx.ReadTimeout("")
        # 使用真实流式读取边界产生超限异常。
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, content=b"x" * (1024 * 1024 + 1),
        ))
        async with httpx.AsyncClient(transport=transport) as upstream:
            return await mcp_gateway._post_upstream(server, {"id": 1}, client=upstream)
    monkeypatch.setattr(mcp_gateway, "_call_upstream", failing_call)
    monkeypatch.setattr(mcp_gateway, "_validate_resolved_endpoint", lambda _: ["93.184.216.34"])
    path = "/api/v1/mcp/debug/upstream"
    body = {
        "endpoint": server["endpoint"], "timeout_seconds": 4,
        "method": "tools/call", "params": {"name": "slow_echo", "arguments": {}},
    }
    if operation == "discover":
        path = f"/api/v1/mcp/servers/{server['id']}/discover"
        body = {}
    response = client.post(path, headers={"Accept-Language": locale}, json=body)
    assert response.status_code == (504 if timeout else 502)
    expected_code = "mcp.upstream_timeout" if timeout else "mcp.upstream_response_too_large"
    expected_params = {"timeout_seconds": 4} if timeout else {"max_response_kb": 1024}
    if operation == "debug" and not timeout:
        expected_params["debug_request"] = {"id": 1}
    assert response.json()["error_code"] == expected_code
    assert response.json()["error_params"] == expected_params
    if locale == "en-US":
        expected = "timed out" if timeout else "exceeds the limit"
    else:
        expected = "超时" if timeout else "超过限制"
    assert expected in response.json()["detail"]
    if operation == "discover":
        with sessions() as db:
            assert db.get(models.McpServer, server["id"]).health_status == "unhealthy"


def test_unknown_gateway_error_stays_generic(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    token = _gateway_token(client)

    async def fail(*args):
        raise ValueError("internal detail that must not be exposed")
    monkeypatch.setattr(mcp_gateway, "_call_upstream", fail)
    result = client.post("/mcp/readonly", headers={"Authorization": f"Bearer {token}"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "crm__search", "arguments": {"query": "repro"}},
    }).json()
    assert result["error"] == {"code": -32000, "message": "上游 MCP 调用失败"}


@pytest.mark.parametrize("method,params", [
    ("tools/list", {}), ("ping", {}),
    ("tools/call", {"name": "echo", "arguments": {"text": "原文", "api_key": "private-input"}}),
])
@pytest.mark.parametrize("failure", [None, "initialize", "business", "http", "notification", "timeout", "destination"])
def test_debug_history_uses_sent_request(tmp_path, monkeypatch, method, params, failure):
    """调试历史来自真实发送边界；脱敏副本不改变上游参数。"""
    real_call = mcp_gateway._call_upstream
    real_async_client = httpx.AsyncClient
    client, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_gateway, "_call_upstream", real_call)
    sent = []

    def validate(_endpoint):
        if failure == "destination":
            raise ValueError("destination rejected")
        return ["93.184.216.34"]

    def handle(request):
        payload = json.loads(request.content)
        sent.append(payload)
        assert request.headers["Authorization"] == "Bearer header-secret"
        if failure == "timeout" and payload["method"] == method:
            raise httpx.ReadTimeout("test timeout", request=request)
        if (failure == "http" and payload["method"] == method
                or failure == "notification" and payload["method"] == "notifications/initialized"):
            return httpx.Response(503)
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        if (failure == "initialize" and payload["method"] == "initialize"
                or failure == "business" and payload["method"] == method):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"],
                                          "error": {"code": -32000, "message": "test error"}})
        result = {"protocolVersion": mcp_gateway.MCP_PROTOCOL_VERSION} if payload["method"] == "initialize" else {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    monkeypatch.setattr(mcp_gateway, "_validate_resolved_endpoint", validate)
    monkeypatch.setattr(mcp_gateway.httpx, "AsyncClient", lambda **kwargs: real_async_client(
        **kwargs, transport=httpx.MockTransport(handle),
    ))
    response = client.post("/api/v1/mcp/debug/upstream", json={
        "endpoint": "https://mcp.example.com/mcp", "authorization_value": "Bearer header-secret",
        "method": method, "params": params,
    })
    data = response.json()
    if failure in {"http", "notification", "timeout", "destination"}:
        assert response.status_code == (504 if failure == "timeout" else 502)
        recorded = data["error_params"].get("debug_request")
    else:
        assert response.status_code == 200
        recorded = data["request"]
        assert recorded["id"] == data["response"]["id"]
    if failure == "destination":
        assert recorded is None
        assert not sent
    else:
        assert recorded == mcp_gateway._mask_approval_arguments(sent[-1])
        assert len(sent) == (1 if failure == "initialize" else 2 if failure == "notification" else 3)
        if failure not in {"initialize", "notification"}:
            assert sent[-1]["params"] == params
    assert "header-secret" not in response.text
    if method == "tools/call" and failure not in {"initialize", "notification", "destination"}:
        assert "private-input" not in response.text


@pytest.mark.parametrize("access_mode", ["unknown", "read", "write", "destructive"])
@pytest.mark.parametrize("risk_level", ["low", "medium", "high"])
def test_tool_policy_approval_matches_effective_conditions(tmp_path, monkeypatch, access_mode, risk_level):
    """审批界面与保存接口共用高风险、破坏性工具的强制审批语义。"""
    client, sessions = _client(tmp_path, monkeypatch)
    _configured_gateway(client)
    tool = client.get("/api/v1/mcp/servers").json()[0]["tools"][0]
    for draft in (False, True):
        response = client.put(f"/api/v1/mcp/tools/{tool['id']}/policy", json={
            "access_mode": access_mode, "risk_level": risk_level,
            "requires_approval": draft, "rate_limit_per_minute": 60, "max_concurrent": 5,
        })
        expected = access_mode == "destructive" or risk_level == "high" or draft
        assert response.status_code == 200
        assert response.json()["requires_approval"] is expected
        with sessions() as db:
            saved = db.get(models.McpTool, tool["id"])
            assert saved.requires_approval is expected
            assert saved.access_mode == access_mode
            assert saved.risk_level == risk_level


def test_approval_request_keyword_filter(tmp_path, monkeypatch):
    client, sessions = _client(tmp_path, monkeypatch)
    with sessions() as db:
        for request_id in ("mcpapr_aaaaaaaa", "mcpapr_bbbbbbbb"):
            db.add(models.McpToolApproval(
                approval_hash=request_id, request_id=request_id, token_id=999,
                gateway_slug="test", tool_name="echo", arguments_hash="hash",
                status="rejected", expires_at=datetime(2026, 1, 1), created_by="test",
            ))
        db.commit()
    for request_id, expected in (("mcpapr_aaaaaaaa", ["mcpapr_aaaaaaaa"]), ("missing", [])):
        data = client.get("/api/v1/mcp/approval-requests", params={"q": request_id}).json()
        assert data["total"] == len(expected)
        assert [row["request_id"] for row in data["items"]] == expected
    assert client.get("/api/v1/mcp/approval-requests").json()["total"] == 2
