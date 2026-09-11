from __future__ import annotations

import asyncio
import hashlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_source_child_bootstraps_project_imports_from_task_directory(tmp_path):
    import shutil
    import subprocess
    project = tmp_path / "project"
    worker_dir = project / "services" / "agent-security-worker"
    worker_dir.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    package = project / "agent_manager"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "security_redaction.py").write_text("class ScanStopped(Exception): pass\n")
    (worker_dir / "aig_adapter.py").write_text("from agent_manager.security_redaction import ScanStopped\n")
    shutil.copyfile(Path(__file__).resolve().parents[1] / "services/agent-security-worker/mcp_executor.py", worker_dir / "mcp_executor.py")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    # No config is supplied: successful bootstrap must report the structured configuration error.
    child = subprocess.run([sys.executable, "-S", str(worker_dir / "mcp_executor.py"), str(task_dir)],
                           cwd=task_dir, capture_output=True, text=True)
    assert child.returncode == 1
    assert json.loads((task_dir / "error.json").read_text())["code"] == "mcp_scan.engine_failed"

from backend import models
from backend.api_errors import ApiError
from backend.services import mcp_scan_sources as sources
from backend.security_scan_schemas import SecurityWorkerCompleteRequest
from tests.test_ai_infra_guard_mcp_adapter import p3_api, _configured_gateway, _claim

WORKER = Path(__file__).resolve().parents[1] / "services/agent-security-worker"
sys.path.insert(0, str(WORKER))
from mcp_executor import BoundedDispatcher, ExecutionStopped, TaskRuntime, normalize_result


def test_xml_tool_arguments_are_decoded_before_control_plane_request(tmp_path):
    sys.path.insert(0, str(WORKER / "vendor/ai-infra-guard/mcp-scan"))
    from mcp_scan.utils.parse import parse_tool_invocations
    from backend.services.mcp_scan_control import McpTaskRequest
    invocation = parse_tool_invocations('<function=call_mcp_tool><parameter=tool_name>bing_search__bing_search</parameter>'
        '<parameter=arguments>{"query": "MCP Model Context Protocol", "count": 3}</parameter></function>')
    assert isinstance(invocation['args']['arguments'], str)
    received = []
    def request(suffix, body):
        validated = McpTaskRequest(lease_token='test-lease', **body)
        received.append(validated.arguments)
        return {'call_id': body['call_id'], 'status': 'succeeded', 'response': {}}
    runtime = SimpleNamespace(options={'mcp_mode': 'dynamic'}, calls=[], request=request)
    dispatcher = BoundedDispatcher(runtime, tmp_path)
    asyncio.run(dispatcher.call_tool(invocation['toolName'], invocation['args']))
    assert received == [{'query': 'MCP Model Context Protocol', 'count': 3}]
    for invalid in ['{invalid', '[]', 'null']:
        result = asyncio.run(dispatcher.call_tool('call_mcp_tool', {'arguments': invalid}))
        assert result.startswith('Invalid arguments:')
    assert len(received) == 1


def test_tool_approval_required_stops_with_specific_reason(tmp_path):
    runtime = SimpleNamespace(options={'mcp_mode': 'dynamic'}, calls=[], request=lambda suffix, body: {
        'call_id': body['call_id'], 'status': 'denied', 'response': {'error': {
            'code': -32002, 'data': {'approval_required': True, 'status': 'pending'}}}})
    with pytest.raises(ExecutionStopped, match='^mcp_gateway_approval_required$'):
        asyncio.run(BoundedDispatcher(runtime, tmp_path).call_tool('call_mcp_tool', {'tool_name': 'lookup', 'arguments': {}}))
    assert runtime.calls[0]['status'] == 'denied'


def test_schema_error_string_returns_to_model_without_crashing(tmp_path):
    response = {'error': {'code': -32602, 'message': 'Tool 参数不符合 Schema', 'data': "'query' is a required property"}}
    runtime = SimpleNamespace(options={'mcp_mode': 'dynamic'}, calls=[], request=lambda suffix, body: {
        'call_id': body['call_id'], 'status': 'denied', 'response': response})
    result = asyncio.run(BoundedDispatcher(runtime, tmp_path).call_tool('call_mcp_tool', {'tool_name': 'lookup', 'arguments': {}}))
    assert json.loads(result)['response'] == response
    assert runtime.calls[0]['status'] == 'denied'


def test_wrapped_inventory_operation_is_corrected_without_target_call(tmp_path):
    requests = []
    runtime = SimpleNamespace(options={'mcp_mode': 'dynamic'}, calls=[], request=lambda suffix, body: requests.append(body) or {'tools': []})
    dispatcher = BoundedDispatcher(runtime, tmp_path)
    result = asyncio.run(dispatcher.call_tool('call_mcp_tool', {'tool_name': 'list_mcp_tools', 'arguments': {}}))
    assert '<function=list_mcp_tools></function>' in result
    assert not requests
    assert json.loads(asyncio.run(dispatcher.call_tool('list_mcp_tools', {}))) == {'tools': []}
    assert requests == [{'method': 'tools/list'}]


@pytest.mark.parametrize("field,limit", [("rounds", "max_rounds"), ("tokens", "max_tokens"), ("response_bytes", "max_response_bytes")])
def test_model_budget_reports_specific_limit_before_request(tmp_path, field, limit):
    runtime = TaskRuntime({"claim": {"scan_options": {}, "policy": {limit: 5}},
                           "usage": {"rounds": 0, "tokens": 0, "response_bytes": 0, field: 5}}, tmp_path)
    try:
        with pytest.raises(ExecutionStopped, match=f"^mcp_{field}_limit_reached$"):
            runtime.chat("model", [])
    finally:
        runtime.client.close()


def test_diagnostics_omit_http_payload_and_exception_text(tmp_path):
    import httpx
    runtime = TaskRuntime({'claim': {'scan_options': {}}, 'usage': {}}, tmp_path)
    runtime.client.close()
    def fail(request):
        raise httpx.ConnectError('secret-token-in-error', request=request)
    runtime.client = httpx.Client(transport=httpx.MockTransport(fail))
    try:
        with pytest.raises(httpx.ConnectError):
            runtime.post('model', 'https://example.invalid', json={'prompt': 'private-input'}, headers={'Authorization': 'secret-token'})
        content = (tmp_path / 'diagnostics.json').read_text()
        assert 'private-input' not in content and 'secret-token' not in content
        assert json.loads(content)[-1]['error_type'] == 'ConnectError'
    finally:
        runtime.client.close()


def archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        for name, content in entries:
            bundle.writestr(name, content)
    return stream.getvalue()


@pytest.mark.parametrize("name", ["../escape.py", "/absolute.py", "a/../../escape.py", "a\\escape.py", "C:/escape.py"])
def test_source_rejects_escaping_paths(name):
    with pytest.raises(ApiError):
        sources.normalize_bundle(archive([(name, "x")]))


def test_source_rejects_symlink_and_keeps_binary_coverage():
    entry = zipfile.ZipInfo("link")
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ApiError):
        sources.normalize_bundle(archive([(entry, "outside")]))
    files = sources.normalize_bundle(archive([("repo/main.py", "print('test')"), ("repo/logo.png", b"\x89PNG\0")]))
    assert files[0]["path"] == "logo.png"
    assert files[0]["content"] is None
    assert files[0]["sha256"] == hashlib.sha256(b"\x89PNG\0").hexdigest()


def test_source_immutable_snapshot_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.settings, "DATA_DIR", str(tmp_path))
    content = archive([("src/main.py", "print('test')")])
    first = sources.save_source(content, 1, origin="upload")
    assert sources.save_source(content, 1, origin="upload") == first
    assert not list(sources.source_root().glob("*.tmp"))
    path = sources.source_root() / (first["source_id"] + ".json")
    record = json.loads(path.read_text())
    record["files"][0]["content"] = "changed"
    path.write_text(json.dumps(record))
    with pytest.raises(ApiError):
        sources.load_source(first["source_id"])


def test_dispatcher_cannot_read_worker_files_or_execute_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("safe data\nneedle\n")
    (tmp_path / "secret").write_text("worker-token")
    (source / "link").symlink_to(tmp_path / "secret")
    dispatcher = BoundedDispatcher(SimpleNamespace(options={"mcp_mode": "source"}), source)
    for path in ("../secret", str(tmp_path / "secret"), "link"):
        assert "worker-token" not in asyncio.run(dispatcher.call_tool("read_file", {"file_path": path}))
    assert "unavailable" in asyncio.run(dispatcher.call_tool("execute_shell", {"command": "touch owned"}))
    assert "2: needle" in asyncio.run(dispatcher.call_tool("read_file", {"file_path": "main.py"}))
    assert not (source / "owned").exists()


def add_model(factory):
    with factory() as db:
        provider = models.ModelProvider(name="mcp-evaluator", base_url="https://model.example/v1", enabled=True)
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(name="mcp-eval", provider_id=provider.id, enabled=True))
        db.commit()


def test_source_task_preview_claim_and_result_contract(p3_api):
    client, factory, _ = p3_api
    add_model(factory)
    upload = client.post("/api/v1/agent-security/mcp-sources", content=archive([("main.py", "print('test')")]))
    assert upload.status_code == 200, upload.text
    source_id = upload.json()["source_id"]
    target = client.post("/api/v1/agent-security/targets", json={"name": "Source MCP", "asset_type": "mcp",
        "connector_type": "mcp_source", "endpoint_url": "mcp-source://" + source_id, "config": {"source_id": source_id}})
    assert target.status_code == 200, target.text
    policy = client.post("/api/v1/agent-security/policies", json={"name": "source-audit"}).json()
    payload = {"target_id": target.json()["target_id"], "policy_id": policy["policy_id"], "scan_kind": "mcp_risk_scan",
               "mcp_mode": "source", "evaluation_model": "mcp-eval"}
    preview = client.post("/api/v1/agent-security/tasks/preview", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["tool_plan"]["mode"] == "source_audit"
    task = client.post("/api/v1/agent-security/tasks", json={**payload, "idempotency_key": "source-test-idem"})
    assert task.status_code == 200, task.text
    worker, claim = _claim(client)
    read = client.post(f"/api/v1/agent-security/worker/tasks/{claim['task']['task_id']}/mcp/source", json={"lease_token": claim["lease_token"]})
    assert read.status_code == 200, read.text
    assert read.json()["files"][0]["content"] == "print('test')"
    result = normalize_result(claim, {"report": {"scan_mode": "source", "calls": [], "results": [
        {"title": "Unvalidated input", "file": "main.py", "line_start": 1, "suggestion": "Validate input before use."}
    ]}, "sarif": {},
        "usage": {"rounds": 1, "tokens": 10, "cost_microunits": 0, "concurrent_requests": 1, "response_bytes": 100}})
    validated = SecurityWorkerCompleteRequest(lease_token=claim["lease_token"], **result)
    assert validated.findings[0].evidence["remediation"][0]["message"] == "Validate input before use."
    assert validated.findings[0].evidence["file"] == "main.py"
    complete = client.post(f"/api/v1/agent-security/worker/tasks/{claim['task']['task_id']}/complete",
        headers={"Authorization": "Bearer " + worker["token_once"]}, json={"lease_token": claim["lease_token"], **result})
    assert complete.status_code == 200, complete.text
    detail = client.get(f"/api/v1/agent-security/tasks/{claim['task']['task_id']}").json()
    assert detail['risk_score']['score'] is None
    assert detail['risk_score']['unverified_findings'] == 1


def test_dynamic_call_scope_deduplication_schema_and_evidence(p3_api, monkeypatch):
    from backend.routers import security_scans
    from backend import security_scan_controls
    client, factory, upstream = p3_api
    add_model(factory)
    gateway = _configured_gateway(client, factory)
    with factory() as db:
        tool = db.query(models.McpTool).filter_by(name="lookup_customer").one()
        tool.access_mode = "read"
        tool.requires_approval = False
        tool.risk_level = "low"
        tool_name = tool.exposed_name
        db.commit()
    monkeypatch.setattr(security_scans, "resolve_target_endpoint", lambda *a, **k: ["93.184.216.34"])
    monkeypatch.setattr(security_scan_controls, "resolve_target_endpoint", lambda *a, **k: ["93.184.216.34"])
    target = client.post("/api/v1/agent-security/targets", json={"name": "Live MCP", "target_type": "mcp_gateway",
        "endpoint_url": f"mcp-gateway://{gateway['slug']}", "config": {"gateway_id": gateway["id"]}}).json()
    policy = client.post("/api/v1/agent-security/policies", json={"name": "dynamic-audit"}).json()
    payload = {"target_id": target["target_id"], "policy_id": policy["policy_id"], "scan_kind": "mcp_risk_scan",
        "mcp_mode": "dynamic", "mcp_route": "server", "mcp_tools": [tool_name], "mcp_call_limit": 2, "evaluation_model": "mcp-eval"}
    created = client.post("/api/v1/agent-security/tasks", json={**payload, "idempotency_key": "live-test-idem"})
    assert created.status_code == 200, created.text
    _worker, claim = _claim(client)
    url = f"/api/v1/agent-security/worker/tasks/{claim['task']['task_id']}/mcp"
    call = {"lease_token": claim["lease_token"], "method": "tools/call", "tool_name": tool_name,
            "call_id": "dedup-call-001", "arguments": {"customer_id": "customer-1"}}
    denied = client.post(url, json={**call, "tool_name": "customer-ops__transfer_funds"})
    assert denied.status_code == 403
    assert upstream.tool_calls == 0
    result = client.post(url, json=call)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded", result.text
    assert upstream.tool_calls == 1
    assert client.post(url, json=call).status_code == 409
    assert upstream.tool_calls == 1
    evidence = client.get(f"/api/v1/agent-security/tasks/{claim['task']['task_id']}/mcp-calls")
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["items"][0]["route"] == "server"
    with factory() as db:
        tool = db.query(models.McpTool).filter_by(name="lookup_customer").one()
        tool.schema_hash = "changed"
        db.commit()
    changed = client.post(url, json={**call, "call_id": "dedup-call-002"})
    assert changed.status_code == 409
    assert changed.json()["error_code"] == "mcp_scan.schema_changed"
    assert upstream.tool_calls == 1


@pytest.mark.parametrize("mode,depth", [("source", "quick"), ("source", "full"), ("dynamic", "full")])
def test_locked_upstream_pipeline_executes_with_bounded_dispatcher(tmp_path, monkeypatch, mode, depth):
    pytest.importorskip("mcp")
    pytest.importorskip("loguru")
    sys.path.insert(0, str(WORKER / "vendor/ai-infra-guard/mcp-scan"))
    import mcp_executor
    monkeypatch.chdir(tmp_path)
    files = [{"path": "main.py", "content": "print('test')", "sha256": hashlib.sha256(b"print('test')").hexdigest()}]
    digest = hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    observations = {"model": 0, "tool_calls": 0}
    def request(self, suffix, body):
        if suffix == "/mcp/source":
            return {"files": files, "sha256": digest}
        if body.get("method") == "tools/list":
            return {"tools": [{"name": "lookup", "inputSchema": {"type": "object"}}]}
        assert body["tool_name"] == "lookup"
        observations["tool_calls"] += 1
        return {"call_id": body["call_id"], "status": "succeeded", "response": {"result": {"content": [{"type": "text", "text": "customer-1"}]}}}
    def chat(self, model, messages):
        observations["model"] += 1
        if observations["model"] == 1:
            if mode == "source":
                return '<function=read_file><parameter=file_path>main.py</parameter></function>', {"total_tokens": 5}
            return '<function=call_mcp_tool><parameter=tool_name>lookup</parameter><parameter=arguments>{}</parameter></function>', {"total_tokens": 5}
        return '<empty>\n<function=finish></function>', {"total_tokens": 5}
    monkeypatch.setattr(TaskRuntime, "request", request)
    monkeypatch.setattr(TaskRuntime, "chat", chat)
    config = {"claim": {"scan_options": {"mcp_mode": mode, "mcp_depth": depth, "evaluation_model": "test-model",
        "mcp_source_sha256": digest}}, "usage": {}, "task_url": "https://example.invalid"}
    asyncio.run(mcp_executor.execute_child(config, tmp_path))
    report = json.loads((tmp_path / "result.json").read_text())["report"]
    assert len(report["stages"]) == (1 if depth == "quick" else 3 if mode == "source" else 4)
    assert observations["model"] >= len(report["stages"])
    assert observations["tool_calls"] == (1 if mode == "dynamic" else 0)


@pytest.mark.parametrize("strategy", ["crescendo", "tap"])
def test_upstream_redteam_uses_distinct_roles_and_live_tool_results(tmp_path, monkeypatch, strategy):
    pytest.importorskip("mcp")
    pytest.importorskip("loguru")
    sys.path.insert(0, str(WORKER / "vendor/ai-infra-guard/mcp-scan"))
    from mcp_executor import run_redteam
    monkeypatch.chdir(tmp_path)
    runtime = TaskRuntime({"claim": {"lease_token": "task-lease", "scan_options": {"mcp_mode": "redteam",
        "mcp_strategy": strategy, "mcp_call_limit": 2, "evaluation_model": "judge", "attack_model": "attacker", "analysis_model": "analyst"}},
        "usage": {}, "task_url": "https://example.invalid"}, tmp_path)
    role_calls = []
    def chat(model, messages):
        role_calls.append(model)
        if model == "attacker":
            return json.dumps({"message": "test lookup", "attack_technique": "test"}), {}
        if model == "analyst":
            return json.dumps({"tool_name": "lookup", "arguments": {"id": "test"}}), {}
        assert "fixture-tool-result" in json.dumps(messages)
        return json.dumps({"score": 10, "is_successful": True, "on_topic": True, "reason": "test signal"}), {}
    def request(suffix, body):
        if body.get("method") == "tools/list":
            return {"tools": [{"name": "lookup", "inputSchema": {"type": "object"}}]}
        assert body["arguments"] == {"id": "test"}
        return {"call_id": body["call_id"], "status": "succeeded", "response": "fixture-tool-result"}
    runtime.chat, runtime.request = chat, request
    result = asyncio.run(run_redteam(runtime, BoundedDispatcher(runtime, tmp_path), "test objective"))
    assert set(role_calls) == {"attacker", "analyst", "judge"}
    assert runtime.calls
    assert result["redteam"]["best_score"] == 10


def test_cancel_terminates_task_process_and_removes_temporary_files(tmp_path, monkeypatch):
    import os
    import subprocess
    import mcp_executor
    from aig_adapter import EvaluatorConfig, ScanStopped
    launched = []
    real_popen = subprocess.Popen
    def start(_args, **kwargs):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        launched.append((process, kwargs["cwd"]))
        return process
    monkeypatch.setattr(subprocess, "Popen", start)
    evaluator = EvaluatorConfig(api_key="lease", model="judge", base_url="https://example.invalid/evaluator/v1")
    with pytest.raises(ScanStopped):
        mcp_executor.execute_mcp_aig_scan({"task": {"task_id": "test"}, "scan_options": {}},
            lambda usage: {"continue_allowed": False, "stop_reason": "cancel_requested"}, evaluator, initial_usage={})
    process, folder = launched[0]
    assert process.poll() is not None
    assert not Path(folder).exists()
    with pytest.raises(ProcessLookupError):
        os.kill(process.pid, 0)


def test_scan_transport_pins_ip_and_preserves_tls_hostname(monkeypatch):
    import httpx
    from backend.routers import mcp_gateway
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "call", "result": {}})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(upstream), **kwargs))
    monkeypatch.setattr(mcp_gateway, "_validate_resolved_endpoint", lambda endpoint: ["93.184.216.34"])
    server = models.McpServer(endpoint="https://mcp.example.test/mcp", authorization_header="Authorization", timeout_seconds=5, max_response_kb=1)
    server._scan_resolved_ips = ["93.184.216.34"]
    asyncio.run(mcp_gateway._post_upstream(server, {"jsonrpc": "2.0", "id": "call", "method": "tools/list"}))
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "mcp.example.test"
    assert seen[0].extensions["sni_hostname"] == "mcp.example.test"
    server._scan_resolved_ips = ["93.184.216.35"]
    with pytest.raises(ValueError, match="DNS snapshot changed"):
        asyncio.run(mcp_gateway._post_upstream(server, {"id": "call"}))
    assert len(seen) == 1
