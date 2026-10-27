"""RENA-1495：真实协议交互中的分页、预算和发现事务回归。"""

import asyncio
import json
import time

import httpx
import pytest

from backend import models
from backend.routers import mcp_gateway
from tests.test_mcp_gateway import _client


def _tool(name):
    return {"name": name, "inputSchema": {"type": "object"}}


def _setup(tmp_path, monkeypatch, pages, *, sse=False, max_response_kb=1024):
    real_call = mcp_gateway._call_upstream
    real_client = httpx.AsyncClient
    client, sessions = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_gateway, "_call_upstream", real_call)
    monkeypatch.setattr(mcp_gateway, "_validate_resolved_endpoint", lambda _: ["93.184.216.34"])
    calls = []
    closed = []

    class Stream(httpx.AsyncByteStream):
        def __init__(self, raw):
            self.raw = raw

        async def __aiter__(self):
            yield self.raw

        async def aclose(self):
            closed.append(True)

    def respond(request):
        body = json.loads(request.content)
        calls.append((body, dict(request.headers)))
        if body["method"] == "initialize":
            result = {"protocolVersion": "2025-06-18"}
        elif body["method"] == "notifications/initialized":
            return httpx.Response(202)
        else:
            index = sum(item[0]["method"] == "tools/list" for item in calls) - 1
            result = pages[index] if isinstance(pages, list) else pages(index)
            if isinstance(result, Exception):
                raise result
            if isinstance(result, httpx.Response):
                return result
        envelope = {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
        if isinstance(result, dict) and "error" in result:
            envelope = {"jsonrpc": "2.0", "id": body["id"], **result}
        raw = json.dumps(envelope).encode()
        if sse:
            raw = b"data: " + raw + b"\n\n"
        return httpx.Response(200, headers={
            "Mcp-Session-Id": "pagination-session",
            "Content-Type": "text/event-stream" if sse else "application/json",
        }, stream=Stream(raw))

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(mcp_gateway.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    server = client.post("/api/v1/mcp/servers", json={
        "slug": "paginated", "name": "Paginated", "endpoint": "https://mcp.example.com/mcp",
        "max_response_kb": max_response_kb, "timeout_seconds": 1,
    }).json()
    return client, sessions, server, calls, closed


@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.parametrize("pages, expected", [
    ([{"tools": []}], []),
    ([{"tools": [_tool("one")]}], ["one"]),
    ([{"tools": [_tool("one")], "nextCursor": " opaque cursor "},
      {"tools": [], "nextCursor": "last"}, {"tools": [_tool("two")]}], ["one", "two"]),
])
def test_discovery_collects_pages_in_one_session(tmp_path, monkeypatch, sse, pages, expected):
    client, sessions, server, calls, closed = _setup(tmp_path, monkeypatch, pages, sse=sse)
    response = client.post(f"/api/v1/mcp/servers/{server['id']}/discover")
    assert response.status_code == 200, response.text
    assert [tool["name"] for tool in response.json()["tools"]] == expected
    assert response.json()["health_status"] == "healthy"
    assert [call[0]["method"] for call in calls] == ["initialize", "notifications/initialized"] + ["tools/list"] * len(pages)
    for index, (body, headers) in enumerate(calls[2:]):
        assert headers["mcp-session-id"] == "pagination-session"
        assert headers["mcp-protocol-version"] == "2025-06-18"
        assert body["params"] == ({} if index == 0 else {"cursor": pages[index - 1]["nextCursor"]})
    assert len({call[0]["id"] for call in calls[2:]}) == len(pages)
    assert len(closed) == len(pages) + 1
    with sessions() as db:
        assert sorted(tool.name for tool in db.query(models.McpTool).all()) == expected


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
@pytest.mark.parametrize("bad_page, code", [
    ({"tools": [], "nextCursor": "again"}, "mcp.discovery.repeated_cursor"),
    ({"tools": {}}, "mcp.discovery.invalid_page"),
    ({}, "mcp.discovery.invalid_page"),
    ([], "mcp.discovery.invalid_page"),
    ({"tools": [None]}, "mcp.discovery.invalid_page"),
    ({"tools": [], "nextCursor": 123}, "mcp.discovery.invalid_cursor"),
    ({"error": {"code": -32602, "message": "bad cursor"}}, "mcp.connection_failed"),
    (httpx.ReadTimeout("page timeout"), "mcp.upstream_timeout"),
    (httpx.Response(500), "mcp.connection_failed.http_status"),
])
def test_discovery_failure_preserves_snapshot(tmp_path, monkeypatch, locale, bad_page, code):
    pages = [{"tools": [_tool("new")], "nextCursor": "again"}, bad_page]
    client, sessions, server, calls, _ = _setup(tmp_path, monkeypatch, pages)
    with sessions() as db:
        db.add(models.McpTool(server_id=server["id"], name="old", exposed_name="paginated__old",
                             input_schema_json="{}", schema_hash="old", enabled=True,
                             access_mode="write", risk_level="high", requires_approval=True))
        db.commit()
    response = client.post(f"/api/v1/mcp/servers/{server['id']}/discover", headers={"Accept-Language": locale})
    assert response.status_code in (502, 504), response.text
    assert response.json()["error_code"] == code
    if code.startswith("mcp.discovery."):
        assert ("MCP" in response.json()["detail"])
        assert ("discovery" in response.json()["detail"]) == (locale == "en-US")
    assert len(calls) == 4
    with sessions() as db:
        tool = db.query(models.McpTool).one()
        assert (tool.name, tool.enabled, tool.risk_level, tool.requires_approval) == ("old", True, "high", True)
        assert db.get(models.McpServer, server["id"]).health_status == "unhealthy"


@pytest.mark.parametrize("limit, extra", [("pages", 0), ("pages", 1), ("tools", 0), ("tools", 1)])
def test_discovery_count_limits(tmp_path, monkeypatch, limit, extra):
    count = (100 if limit == "pages" else 10000) + extra

    def pages(index):
        result = {"tools": [_tool(f"tool-{index}")] if limit == "pages" else [_tool(f"tool-{n}") for n in range(count)]}
        if limit == "pages" and index < count - 1:
            result["nextCursor"] = str(index + 1)
        return result

    client, sessions, server, calls, _ = _setup(tmp_path, monkeypatch, pages, max_response_kb=10240)
    response = client.post(f"/api/v1/mcp/servers/{server['id']}/discover")
    if extra:
        assert response.status_code == 502
        assert response.json()["error_code"] == f"mcp.discovery.{'page' if limit == 'pages' else 'tool'}_limit"
        with sessions() as db:
            assert db.query(models.McpTool).count() == 0
    else:
        assert response.status_code == 200, response.text
        assert len(response.json()["tools"]) == count
    assert len(calls) == (min(count, 100) if limit == "pages" else 1) + 2


def test_discovery_cumulative_response_budget(tmp_path, monkeypatch):
    pages = [{"tools": [_tool(str(n))], "nextCursor": str(n + 1), "padding": "x" * 400} for n in range(3)]
    client, sessions, server, calls, closed = _setup(tmp_path, monkeypatch, pages, max_response_kb=1)
    response = client.post(f"/api/v1/mcp/servers/{server['id']}/discover")
    assert response.status_code == 502
    assert response.json()["error_code"] == "mcp.upstream_response_too_large"
    assert len(closed) == len(calls) - 1
    with sessions() as db:
        assert db.query(models.McpTool).count() == 0


def test_discovery_total_timeout_cancels_request(tmp_path, monkeypatch):
    client, sessions, server, calls, _ = _setup(tmp_path, monkeypatch, [])
    cancelled = []

    async def slow_post(server, payload, session_id=None, *args, **kwargs):
        try:
            await asyncio.sleep(0.4)
            if payload["method"] == "initialize":
                return {"result": {"protocolVersion": "2025-06-18"}}, "session"
            if payload["method"] == "notifications/initialized":
                return {}, session_id
            return {"result": {"tools": []}}, session_id
        finally:
            cancelled.append(payload["method"])

    monkeypatch.setattr(mcp_gateway, "_post_upstream", slow_post)
    response = client.post(f"/api/v1/mcp/servers/{server['id']}/discover")
    assert response.status_code == 504
    assert response.json()["error_code"] == "mcp.upstream_timeout"
    assert cancelled == ["initialize", "notifications/initialized", "tools/list"]


def test_rediscovery_updates_schema_and_preserves_governance(tmp_path, monkeypatch):
    pages = [{"tools": [_tool("one")], "nextCursor": "two"}, {"tools": [_tool("two")]}]
    client, sessions, server, calls, _ = _setup(tmp_path, monkeypatch, pages)
    with sessions() as db:
        for name in ("one", "old"):
            db.add(models.McpTool(server_id=server["id"], name=name, exposed_name=f"paginated__{name}",
                                 input_schema_json="{}", schema_hash="old", enabled=True,
                                 access_mode="write", risk_level="high", requires_approval=True))
        db.commit()
    for attempt in range(2):
        calls.clear()
        response = client.post(f"/api/v1/mcp/servers/{server['id']}/discover")
        assert response.status_code == 200, response.text
        with sessions() as db:
            tools = {tool.name: tool for tool in db.query(models.McpTool).all()}
            assert len(tools) == 3
            assert tools["one"].enabled and tools["two"].enabled
            assert not tools["old"].enabled
            assert (tools["one"].risk_level, tools["one"].requires_approval) == ("high", True)
            assert json.loads(tools["one"].input_schema_json) == {"type": "object"}


def test_debug_list_keeps_one_page(tmp_path, monkeypatch):
    pages = [{"tools": [_tool("one")], "nextCursor": "next"}]
    client, _, server, calls, _ = _setup(tmp_path, monkeypatch, pages)
    response = client.post("/api/v1/mcp/debug/upstream", json={"server_id": server["id"], "method": "tools/list"})
    assert response.status_code == 200, response.text
    assert len(calls) == 3


def test_discovery_counts_synchronous_response_processing(monkeypatch):
    async def post(server, payload, session_id=None, *args, **kwargs):
        if payload["method"] == "initialize":
            return {"result": {"protocolVersion": "2025-06-18"}}, "session"
        if payload["method"] == "notifications/initialized":
            return {}, session_id
        # 模拟最后一页同步解析占满预算；取消回调需等解析结束才能运行。
        time.sleep(1.05)
        return {"result": {"tools": []}}, session_id

    monkeypatch.setattr(mcp_gateway, "_post_upstream", post)
    server = models.McpServer(timeout_seconds=1, max_response_kb=1)
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(mcp_gateway._call_upstream(server, "tools/list", {}, paginate_tools=True))
