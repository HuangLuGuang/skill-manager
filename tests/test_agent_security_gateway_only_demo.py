from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "demo" / "agent-security-gateway-only" / "gateway_only.py"
SPEC = importlib.util.spec_from_file_location("agent_security_gateway_only_demo", MODULE_PATH)
assert SPEC and SPEC.loader
gateway_demo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway_demo
SPEC.loader.exec_module(gateway_demo)


@pytest.fixture()
def gateway_api():
    state = {"requests": [], "completeness": "gateway_partial", "events": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def _reply(self, payload):
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            state["requests"].append({"method": "POST", "path": self.path, "body": body})
            if self.path == "/v1/chat/completions":
                self._reply({"choices": [{"message": {"content": "ok"}}]})
            elif self.path == "/mcp/demo-gateway":
                self._reply({"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            state["requests"].append({"method": "GET", "path": self.path, "authorization": self.headers.get("Authorization")})
            if self.path.endswith("/events?limit=200"):
                self._reply({"items": state["events"]})
            elif self.path.startswith("/api/v1/runtime-traces/"):
                self._reply({"completeness": state["completeness"]})
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _config(base_url, *, mode="combined", read_token="jwt-read"):
    return gateway_demo.DemoConfig(
        base_url=base_url,
        gateway_token="amat-gateway-only",
        mode=mode,
        model="demo-model" if mode in {"model", "combined"} else None,
        mcp_gateway="demo-gateway" if mode in {"mcp", "combined"} else None,
        mcp_tool="demo__health" if mode in {"mcp", "combined"} else None,
        mcp_arguments={},
        trace_read_token=read_token,
        timeout_seconds=2,
    )


def test_combined_gateway_only_is_partial_and_never_sends_turn_or_step(gateway_api):
    base_url, state = gateway_api
    state["events"] = [
        {"source": "model_gateway", "type": "model.request", "turn_id": None, "step_id": None},
        {"source": "mcp_gateway", "type": "mcp.call", "turn_id": None, "step_id": None},
    ]

    result = gateway_demo.run_demo(_config(base_url))

    assert result["status"] == "verified"
    assert result["actual_completeness"] == "gateway_partial"
    model = next(item["body"] for item in state["requests"] if item["path"] == "/v1/chat/completions")
    mcp = next(item["body"] for item in state["requests"] if item["path"] == "/mcp/demo-gateway")
    model_meta = model["metadata"]
    mcp_meta = mcp["params"]["_meta"]
    assert model_meta["trace_id"] == mcp_meta["trace_id"] == result["trace_id"]
    assert model_meta["session_id"] == mcp_meta["session_id"] == result["session_id"]
    assert "turn_id" not in model_meta and "step_id" not in model_meta
    assert "turn_id" not in mcp_meta and "step_id" not in mcp_meta
    assert all(item.get("authorization") == "Bearer jwt-read" for item in state["requests"] if item["method"] == "GET")


@pytest.mark.parametrize(
    ("mode", "completeness", "source"),
    [("model", "model_only", "model_gateway"), ("mcp", "mcp_only", "mcp_gateway")],
)
def test_single_gateway_modes_verify_exact_completeness(gateway_api, mode, completeness, source):
    base_url, state = gateway_api
    state["completeness"] = completeness
    state["events"] = [{"source": source, "turn_id": None, "step_id": None}]

    result = gateway_demo.run_demo(_config(base_url, mode=mode))

    assert result["status"] == "verified"
    assert result["actual_completeness"] == completeness


def test_gateway_only_without_read_token_does_not_claim_verification(gateway_api):
    base_url, state = gateway_api

    result = gateway_demo.run_demo(_config(base_url, mode="model", read_token=None))

    assert result["status"] == "submitted_unverified"
    assert result["expected_completeness"] == "model_only"
    assert result["actual_completeness"] is None
    assert not any(item["method"] == "GET" for item in state["requests"])


def test_gateway_only_verification_rejects_fabricated_turns(gateway_api):
    base_url, state = gateway_api
    state["events"] = [
        {"source": "model_gateway", "turn_id": "fake-turn", "step_id": None},
        {"source": "mcp_gateway", "turn_id": None, "step_id": None},
    ]

    with pytest.raises(gateway_demo.DemoError, match="fabricated Turn/Step"):
        gateway_demo.run_demo(_config(base_url))
