from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "demo" / "agent-security-full-integration" / "full_agent.py"
SPEC = importlib.util.spec_from_file_location("agent_security_full_demo", MODULE_PATH)
assert SPEC and SPEC.loader
full_demo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = full_demo
SPEC.loader.exec_module(full_demo)


@pytest.fixture()
def demo_gateway():
    state = {"requests": [], "events": [], "mcp_error": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            state["requests"].append({"path": self.path, "body": body, "authorization": self.headers.get("Authorization")})
            if self.path == "/api/v1/runtime-traces":
                response = {"trace_id": "trc_full_demo"}
            elif self.path == "/api/v1/runtime-traces/trc_full_demo/events:batch":
                state["events"].extend(body["events"])
                response = {"accepted_count": len(body["events"]), "replayed": False}
            elif self.path == "/v1/chat/completions":
                response = {"choices": [{"message": {"content": "internal model summary"}}]}
            elif self.path == "/mcp/demo-gateway":
                response = state["mcp_error"] or {"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}}
            else:
                self.send_response(404)
                self.end_headers()
                return
            encoded = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _config(base_url):
    return full_demo.DemoConfig(
        base_url=base_url,
        token="amat_demo_token",
        model="demo-model",
        mcp_gateway="demo-gateway",
        mcp_tool="policy__lookup",
        mcp_arguments={"query": "agent security"},
        mcp_approval_request=None,
        timeout_seconds=2,
    )


def test_full_demo_correlates_sdk_model_mcp_local_tool_and_knowledge(demo_gateway):
    base_url, state = demo_gateway
    result = full_demo.run_demo(_config(base_url))

    assert result["status"] == "completed"
    assert result["trace_id"] == "trc_full_demo"
    assert result["accepted_count"] == len(state["events"])
    assert all(item["authorization"] == "Bearer amat_demo_token" for item in state["requests"])

    model_request = next(item["body"] for item in state["requests"] if item["path"] == "/v1/chat/completions")
    mcp_request = next(item["body"] for item in state["requests"] if item["path"] == "/mcp/demo-gateway")
    model_meta = model_request["metadata"]
    mcp_meta = mcp_request["params"]["_meta"]
    for key in ("trace_id", "session_id", "turn_id"):
        assert model_meta[key] == mcp_meta[key]
    assert model_meta["trace_id"] == "trc_full_demo"
    assert model_meta["step_id"] != mcp_meta["step_id"]
    assert mcp_meta["call_id"] == result["mcp_call_id"] == mcp_request["id"]

    events = state["events"]
    event_types = {item["type"] for item in events}
    assert {"turn.start", "turn.end", "knowledge.retrieval", "message.assistant", "tool.call", "tool.result"} <= event_types
    retrieval = next(item for item in events if item["type"] == "knowledge.retrieval")
    assert retrieval["source"] == "knowledge_connector"
    assert retrieval["payload"] == retrieval["redacted_payload"] == {
        "knowledge_base": "agent-security-policy",
        "document_id": "policy-demo-2026",
        "chunk_ids": ["chunk-redacted-7", "chunk-redacted-8"],
        "summary": "命中两段已脱敏的智能体安全制度摘要",
    }
    assert any(item.get("tool_name") == "local_policy_cache" for item in events)
    mcp_events = [item for item in events if item.get("call_id") == result["mcp_call_id"]]
    assert {item["type"] for item in mcp_events} == {"tool.call", "tool.result"}
    assistant = next(item for item in events if item["type"] == "message.assistant")
    assert assistant["payload"]["content"] == "internal model summary"
    assert assistant["redacted_payload"]["content"] == "[MODEL_OUTPUT_REDACTED]"


def test_full_demo_stops_at_mcp_approval_without_faking_success(demo_gateway):
    base_url, state = demo_gateway
    state["mcp_error"] = {
        "jsonrpc": "2.0",
        "id": "ignored",
        "error": {
            "code": -32002,
            "message": "approval required",
            "data": {"approval_request_id": "mcpapr_demo"},
        },
    }

    result = full_demo.run_demo(_config(base_url))

    assert result["status"] == "approval_pending"
    assert result["approval_request_id"] == "mcpapr_demo"
    events = state["events"]
    blocked = [item for item in events if item["type"] == "tool.error"]
    assert len(blocked) == 1
    assert blocked[0]["status"] == "blocked"
    assert blocked[0]["payload"] == {"error_code": -32002, "approval_request_id": "mcpapr_demo"}
    assert not any(
        item["type"] == "tool.result" and item.get("call_id") == result["mcp_call_id"]
        for item in events
    )


def test_full_demo_passes_explicit_mcp_approval_request(demo_gateway):
    base_url, state = demo_gateway
    config = _config(base_url)
    config = full_demo.DemoConfig(
        base_url=config.base_url,
        token=config.token,
        model=config.model,
        mcp_gateway=config.mcp_gateway,
        mcp_tool=config.mcp_tool,
        mcp_arguments=config.mcp_arguments,
        mcp_approval_request="mcpapr_approved_demo",
        timeout_seconds=config.timeout_seconds,
    )

    result = full_demo.run_demo(config)

    assert result["status"] == "completed"
    mcp_request = next(item["body"] for item in state["requests"] if item["path"] == "/mcp/demo-gateway")
    assert mcp_request["params"]["_meta"]["agent_manager_approval_request"] == "mcpapr_approved_demo"


def test_full_demo_config_rejects_missing_or_non_object_arguments(monkeypatch):
    for key in (
        "AGENT_RUNTIME_TOKEN",
        "AGENT_MANAGER_MODEL",
        "AGENT_MANAGER_MCP_GATEWAY",
        "AGENT_MANAGER_MCP_TOOL",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(full_demo.DemoError, match="missing required environment variables"):
        full_demo.DemoConfig.from_env()

    monkeypatch.setenv("AGENT_RUNTIME_TOKEN", "token")
    monkeypatch.setenv("AGENT_MANAGER_MODEL", "model")
    monkeypatch.setenv("AGENT_MANAGER_MCP_GATEWAY", "gateway")
    monkeypatch.setenv("AGENT_MANAGER_MCP_TOOL", "tool")
    monkeypatch.setenv("AGENT_MANAGER_MCP_ARGUMENTS", "[]")
    with pytest.raises(full_demo.DemoError, match="must be a JSON object"):
        full_demo.DemoConfig.from_env()
