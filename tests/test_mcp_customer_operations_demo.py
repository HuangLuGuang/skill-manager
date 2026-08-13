from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fastapi.testclient import TestClient


SERVER_PATH = Path(__file__).resolve().parents[1] / "demo" / "mcp-customer-operations" / "server.py"
CALLER_PATH = SERVER_PATH.with_name("call_demo.py")
SPEC = spec_from_file_location("mcp_customer_operations_demo", SERVER_PATH)
assert SPEC and SPEC.loader
server = module_from_spec(SPEC)
SPEC.loader.exec_module(server)
CALLER_SPEC = spec_from_file_location("mcp_customer_operations_caller", CALLER_PATH)
assert CALLER_SPEC and CALLER_SPEC.loader
caller = module_from_spec(CALLER_SPEC)
CALLER_SPEC.loader.exec_module(caller)


def test_customer_operations_demo_lists_searches_and_suspends(monkeypatch):
    monkeypatch.setenv("MCP_DEMO_TOKEN", "test-token")
    server._customers.clear()
    server._customers.update(server.deepcopy(server._initial_customers))
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer test-token"}

    listed = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    ).json()
    assert {tool["name"] for tool in listed["result"]["tools"]} == {"customer_search", "customer_suspend"}

    searched = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "customer_search", "arguments": {"query": "CUST-1001"}},
        },
    ).json()
    assert searched["result"]["structuredContent"]["count"] == 1
    assert searched["result"]["structuredContent"]["customers"][0]["service_status"] == "active"

    suspended = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "customer_suspend",
                "arguments": {
                    "customer_id": "CUST-1001",
                    "reason": "Approved customer request",
                    "ticket_id": "CHG-000123",
                },
            },
        },
    ).json()
    assert suspended["result"]["structuredContent"]["changed"] is True
    assert suspended["result"]["structuredContent"]["customer"]["service_status"] == "suspended"


def test_customer_operations_demo_requires_credential(monkeypatch):
    monkeypatch.setenv("MCP_DEMO_TOKEN", "test-token")
    response = TestClient(server.app).post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401


def test_customer_operations_caller_uses_configured_gateway_and_server_slugs(monkeypatch):
    captured = {}

    def fake_post(url, token, payload):
        captured.update(url=url, token=token, payload=payload)
        return {"jsonrpc": "2.0", "id": 1, "result": {}}

    monkeypatch.setattr(caller, "post", fake_post)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "call_demo.py",
            "search",
            "--base-url",
            "https://manager.example",
            "--token",
            "demo-token",
            "--gateway-slug",
            "business-gateway",
            "--server-slug",
            "customer-service",
        ],
    )

    assert caller.main() == 0
    assert captured["url"] == "https://manager.example/mcp/business-gateway"
    assert captured["payload"]["params"]["name"] == "customer-service__customer_search"
