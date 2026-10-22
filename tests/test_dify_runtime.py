import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler, validation_error_handler
from backend.config import settings
from backend.routers import dify_runtime
from backend.sqlite_db import Base, get_db


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "dify-runtime-test")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = models.User(username="tester", hashed_password="unused", role="admin")
        db.add(user)
        db.flush()
        db.add(models.ManagedAgent(agent_id="agent-dify", name="Dify"))
        db.add(models.SecurityTarget(target_id="target", name="Dify", target_type="agent", endpoint_url="http://dify",
                                    connector_type="dify", owner_user_id=user.id, created_by=user.username,
                                    config_json='{"workspace_id":"workspace","app_id":"app"}'))
        db.add(models.AccessToken(name="Dify", token_type="agent_runtime", token_prefix="test",
            token_hash=hashlib.sha256(b"test-dify-token").hexdigest(), bound_agent_id="agent-dify",
            user_id=user.id, scopes_json='["runtime:trace","runtime:govern"]'))
        db.commit()
    def get_session():
        with factory() as db:
            yield db
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[auth.get_current_admin_user] = lambda: user
    app.include_router(dify_runtime.router)
    with TestClient(app, headers={"Authorization": "Bearer test-dify-token"}) as client:
        response = client.post("/v1/dify-runtime/bindings", json={
            "target_id": "target", "agent_id": "agent-dify", "instance_id": "local"})
        assert response.status_code == 200, response.text
        yield client, response.json(), factory


def configure(api, rules=None, **policy):
    client, binding, _ = api
    response = client.put("/v1/dify-runtime/bindings/" + binding["binding_id"], json={
        "revision": binding["revision"], "mode": "enforce", "policy": {"rules": rules or [], **policy}})
    assert response.status_code == 200, response.text
    binding.update(response.json())


def start(api, run_id="run"):
    client, binding, _ = api
    response = client.post(f"/v1/dify-runtime/bindings/{binding['binding_id']}/runs", json={
        "run_id": run_id, "workspace_id": "workspace", "app_id": "app",
        "workflow_id": "workflow", "graph_digest": "a"*64})
    assert response.status_code == 200, response.text
    return "/v1/dify-runtime/runs/" + response.json()["task_id"]


def call(call_id="one", **fields):
    return {"call_id": call_id, "node_id": "node", "execution_id": call_id, "node_type": "http-request",
            "host": "receiver", "method": "POST", "input_digest": "b"*64, **fields}


def test_binding_run_idempotency_and_identity(api):
    client, binding, _ = api
    assert start(api) == start(api)
    response = client.post(f"/v1/dify-runtime/bindings/{binding['binding_id']}/runs", json={
        "run_id": "run", "workspace_id": "another", "app_id": "app", "workflow_id": "workflow", "graph_digest": "a"*64})
    assert response.status_code == 403


def test_deny_version_and_observe(api):
    client, binding, _ = api
    configure(api, [{"rule_id": "external", "host": "receiver", "effect": "deny"}])
    path = start(api)
    result = client.post(path + "/authorize", json=call()).json()
    assert result["status"] == "blocked"
    configure(api, approved_graphs=["c"*64])
    assert client.post(path + "/authorize", json=call("version")).json()["reasons"] == ["unapproved_graph"]
    with api[2]() as db:
        assert db.query(models.RuntimeTraceEvent).filter_by(type="runtime.blocked").count() == 2


def test_host_and_method_rules_are_canonical(api):
    client, _, _ = api
    configure(api, [{"rule_id": "external", "host": "Receiver.", "method": "post", "effect": "deny"}])
    response = client.post(start(api) + "/authorize", json=call(host="RECEIVER.")).json()
    assert response["status"] == "blocked"


def test_approval_exact_action_consume_replay_and_results(api):
    client, binding, _ = api
    configure(api, [{"rule_id": "review", "node_type": "http-request", "effect": "approval"}])
    path = start(api)
    response = client.post(path + "/authorize", json=call()).json()
    assert response["status"] == "pending"
    action = response["action_id"]
    assert client.post(f"/v1/dify-runtime/actions/{action}/review", json={"approve": True}).status_code == 200
    allowed = client.post(path + "/authorize", json=call()).json()
    assert allowed["status"] == "authorized"
    assert client.post(path + "/authorize", json=call(input_digest="c"*64)).status_code == 409
    payload = {"authorization_token": allowed["authorization_token"], "input_digest": "b"*64}
    consume_path = path + f"/actions/{action}/consume"
    assert client.post(consume_path, json={**payload, "input_digest": "c"*64}).status_code == 403
    assert client.post(consume_path, json=payload).status_code == 200
    assert client.post(consume_path, json=payload).status_code == 403
    result_path = path + f"/actions/{action}/result"
    for _ in range(2):
        assert client.post(result_path, json={"status": "succeeded", "duration_ms": 5}).status_code == 200
    assert client.post(result_path, json={"status": "failed", "duration_ms": 5}).status_code == 409


def test_sequence_uses_completed_actions_and_policy_revocation(api):
    client, _, _ = api
    configure(api, [{"rule_id": "read-send", "host": "receiver", "after_node_type": "knowledge-retrieval", "effect": "deny"}])
    path = start(api)
    early_http = client.post(path + "/authorize", json=call("early-http")).json()
    allowed = client.post(path + "/authorize", json=call("read", node_type="knowledge-retrieval")).json()
    action_path = path + f"/actions/{allowed['action_id']}"
    assert client.post(action_path + "/consume", json={"authorization_token": allowed["authorization_token"],
        "input_digest": "b"*64}).status_code == 200
    assert client.post(action_path + "/result", json={"status": "succeeded", "duration_ms": 1}).status_code == 200
    assert client.post(path + "/authorize", json=call()).json()["status"] == "blocked"
    assert client.post(path + f"/actions/{early_http['action_id']}/consume", json={
        "authorization_token": early_http["authorization_token"], "input_digest": "b"*64}).status_code == 403
    allowed = client.post(path + "/authorize", json=call("other", host="internal")).json()
    configure(api)
    assert client.post(path + f"/actions/{allowed['action_id']}/consume", json={
        "authorization_token": allowed["authorization_token"], "input_digest": "b"*64}).status_code == 403


def test_observation_replay_and_inventory_execution_boundary(api):
    from agent_manager.core.dify_inventory.merger import _apply_runtime
    client, binding, _ = api
    payload = {"run": {"run_id": "observed", "workspace_id": "workspace", "app_id": "app",
                      "workflow_id": "workflow", "graph_digest": "a"*64},
               "event_id": "d"*32, "event_time": "2026-10-20T01:00:00Z", "node_id": "node",
               "execution_id": "execution", "node_type": "http-request", "type": "step.start", "status": "started"}
    for _ in range(2):
        response = client.post(f"/v1/dify-runtime/bindings/{binding['binding_id']}/observations", json=payload)
        assert response.status_code == 200, response.text
    with api[2]() as db:
        assert db.query(models.RuntimeTraceEvent).filter_by(event_id="d"*32).count() == 1
    item = {"details": {"node_id": "node"}, "sources": []}
    _apply_runtime([item], [{"node_id": "node", "type": "runtime.blocked", "status": "blocked"}])
    assert item["executed"] is False
    assert item["details"]["runtime"]["first_executed_at"] is None
    payload.update(event_id="e"*32, type="turn.end", status="succeeded")
    assert client.post(f"/v1/dify-runtime/bindings/{binding['binding_id']}/observations", json=payload).status_code == 200
    with api[2]() as db:
        assert db.query(models.RuntimeTask).filter_by(session_id="observed").one().status == "succeeded"


def test_pending_approval_revocation_and_timeout_are_terminal(api):
    from datetime import datetime, timedelta
    client, _, factory = api
    configure(api, [{"rule_id": "review", "effect": "approval"}])
    path = start(api)
    pending = client.post(path + "/authorize", json=call()).json()
    configure(api)
    revoked = client.post(path + "/authorize", json=call()).json()
    assert revoked["status"] == "blocked"
    assert revoked["approval_status"] == "revoked"
    assert "authorization_token" not in revoked
    assert client.post(f"/v1/dify-runtime/actions/{pending['action_id']}/review", json={"approve": True}).status_code == 409
    configure(api, [{"rule_id": "review", "effect": "approval"}])
    pending = client.post(path + "/authorize", json=call("timeout")).json()
    with factory() as db:
        db.get(models.DifyRuntimeCall, pending["action_id"]).approval_deadline = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    expired = client.post(path + "/authorize", json=call("timeout")).json()
    assert expired["status"] == "expired"
    assert "authorization_token" not in expired


def test_adapter_checkpoint_precedes_side_effect_and_queue_survives(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime.client import ApprovalPause, Client
    from am_dify_runtime.hooks import graph_fingerprint
    from agent_manager.core.dify_inventory.schema import graph_digest
    graph = {"nodes": [{"id": "a", "data": {"type": "code"}}], "edges": []}
    assert graph_fingerprint(graph) == graph_digest(graph)
    credentials = tmp_path / "credentials.json"
    credentials.write_text('{"binding":"test"}')
    monkeypatch.setattr("threading.Thread.start", lambda self: None)
    config = {"credentials_file": str(credentials), "queue_dir": str(tmp_path / "queue"), "server_url": "http://test"}
    application = {"binding_id": "binding", "mode": "enforce"}
    client = Client(config, application)
    monkeypatch.setattr(client, "run", lambda ctx: {"task_id": "task", "mode": "enforce"})
    monkeypatch.setattr(client, "post", lambda path, body: {
        "action_id": "action", "status": "pending", "mode": "enforce", "revision": 2})
    called = []
    context = {"run_id": "run", "execution_id": "execution", "node_id": "node", "node_type": "http-request"}
    with pytest.raises(ApprovalPause):
        client.execute(context, {}, {}, lambda: called.append(True))
    assert not called
    client.enqueue("/result", {"status": "succeeded"})
    restarted = Client(config, application)
    with restarted.db() as db:
        assert db.execute("SELECT count(*) FROM queue").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 1
    restarted.set_mode("observe", 3)
    restarted.set_mode("enforce", 4)
    restarted.set_mode("observe", 3)
    assert Client(config, {**application, "mode": "observe"}).mode == "enforce"


def test_adapter_wraps_workflow_and_agent_tool_entrypoints(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime import hooks
    invoked = []
    def invoke(tool, tool_parameters):
        invoked.append(tool_parameters)
        return iter(["result"])
    engine = SimpleNamespace(_invoke=invoke, generic_invoke=invoke)
    decisions = []
    def authorize(fields, parameters, execute):
        decisions.append((fields, parameters))
        return execute()
    monkeypatch.setattr(hooks, "guarded", authorize)
    hooks.patch_tools(SimpleNamespace(ToolEngine=engine))
    tool = SimpleNamespace(entity=SimpleNamespace(identity=SimpleNamespace(name="send")),
                           runtime=SimpleNamespace(runtime_parameters={"default": "value"}))
    for entrypoint in (engine._invoke, engine.generic_invoke):
        assert list(entrypoint(tool, {"argument": "value"})) == ["result"]
    assert len(invoked) == len(decisions) == 2
    assert decisions[0] == ({"tool": "send"}, {"default": "value", "argument": "value"})


def test_adapter_retains_flask_app_from_dify_factory_tuple(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime import hooks
    flask_app, wsgi_app = object(), object()
    module = SimpleNamespace(create_app=lambda: (wsgi_app, flask_app))
    monkeypatch.setattr(hooks, "initialize_clients", lambda: None)
    monkeypatch.setattr(hooks, "flask_app", None)
    hooks.patch_app(module)
    assert module.create_app() == (wsgi_app, flask_app)
    assert hooks.flask_app is flask_app


def test_configured_bootstrap_failure_stops_python():
    import os
    import subprocess
    bootstrap = Path(__file__).parents[1] / "integrations/dify-runtime/bootstrap"
    result = subprocess.run([sys.executable, "-c", "print('application started')"],
        env={**os.environ, "PYTHONPATH": str(bootstrap), "AM_DIFY_CONFIG": "/unused"},
        capture_output=True, text=True)
    assert result.returncode == 78
    assert result.stdout == ""
    assert result.stderr == "dify_runtime.bootstrap_failed\n"
