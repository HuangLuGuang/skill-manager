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
from backend.routers import dify_runtime, agents
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
        db.add(models.ManagedAgent(agent_id="agent-dify", name="Dify", created_by="tester"))
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
    app.include_router(agents.router)
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


@pytest.mark.parametrize("boundary", ["publish-check", "runtime-check"])
def test_skill_admission_uses_exact_package_and_live_approval(api, boundary):
    from types import SimpleNamespace
    from unittest.mock import Mock
    client, bound, factory = api
    configure(api)
    entry = SimpleNamespace(status=SimpleNamespace(value="VETTED"), risk_level=None,
                            skill_id="version", signature="signed", skill_path="/scan")
    mgr = SimpleNamespace(get_skill=lambda *a, **k: entry, list_scan_runs=lambda _: [],
                          runtime=SimpleNamespace(can_load=Mock(return_value=(True, entry, "allowed"))))
    client.app.dependency_overrides[dify_runtime.get_manager] = lambda: mgr
    with factory() as db:
        db.add(models.DifyRuntimeSkill(binding_id=bound['binding_id'], dify_agent_id='native',
            archive_hash='a'*64, skill_name='example', version_id='version'))
        db.commit()
    url=f"/v1/dify-runtime/bindings/{bound['binding_id']}/skills/{boundary}"
    body={'dify_agent_id':'native','skills':[{'name':'example','archive_hash':'a'*64}]}
    assert not client.post(url,json=body).json()['allowed']
    with factory() as db:
        db.get(models.DifyRuntimeBinding,bound['binding_id']).mode='observe'
        db.commit()
    assert client.post(url,json=body).json()['allowed']
    with factory() as db:
        db.get(models.DifyRuntimeBinding,bound['binding_id']).mode='enforce'
        db.commit()
    entry.status.value='APPROVED'
    assert client.post(url,json=body).json()['allowed']
    mgr.runtime.can_load.assert_called_once()
    assert mgr.runtime.can_load.call_args.kwargs['audit_metadata']['source'] == ('dify_runtime' if boundary == 'runtime-check' else 'dify_publish')
    mgr.runtime.can_load.return_value=(False,entry,'tampered')
    assert not client.post(url,json=body).json()['allowed']
    mgr.runtime.can_load.return_value=(True,entry,'allowed')
    body['skills'][0]['archive_hash']='b'*64
    assert not client.post(url,json=body).json()['allowed']
    body['skills'][0]['archive_hash']='a'*64
    body['dify_agent_id']='another-agent'
    assert not client.post(url,json=body).json()['allowed']
    body['dify_agent_id']='native'
    entry.status.value='RETIRED'
    assert not client.post(url,json=body).json()['allowed']
    entry.status.value='APPROVED'
    mgr.list_scan_runs=lambda _: [SimpleNamespace(status='PENDING')]
    assert not client.post(url,json=body).json()['allowed']


def test_skill_upload_scans_full_package_once(api, tmp_path, monkeypatch):
    import base64, io, zipfile
    from types import SimpleNamespace
    from backend.services import dify_skills
    client,bound,factory=api
    entry=SimpleNamespace(skill_id='version',status=SimpleNamespace(value='VETTED'),risk_level=None)
    mgr=SimpleNamespace(registry=SimpleNamespace(data_dir=tmp_path),
                        get_skill=lambda *a,**k:entry,list_scan_runs=lambda _:[])
    client.app.dependency_overrides[dify_runtime.get_manager]=lambda:mgr
    calls=[]
    def scan(manager,tasks,path,source,*options):
        assert (path/'scripts'/'test.py').read_text()=='print("test")'
        calls.append(path)
        return SimpleNamespace(name='example',version_id='version')
    monkeypatch.setattr(dify_skills,'_submit_directory_for_processing',scan)
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        archive.writestr('SKILL.md','---\nname: example\ndescription: test\n---\nTest.')
        archive.writestr('scripts/test.py','print("test")')
    url=f"/v1/dify-runtime/bindings/{bound['binding_id']}/skills/upload"
    body={'dify_agent_id':'native','archive_base64':base64.b64encode(data.getvalue()).decode()}
    for _ in range(2):
        response=client.post(url,json=body)
        assert response.status_code==200,response.text
        assert response.json()['status']=='VETTED'
    assert len(calls)==1
    response=client.get(f"/v1/dify-runtime/bindings/{bound['binding_id']}/skills")
    assert len(response.json()['items'])==1
    with factory() as db:
        db.add(models.DifyRuntimeSkill(binding_id=bound['binding_id'],dify_agent_id='native',
            archive_hash='b'*64,skill_name='example',version_id='version'))
        db.commit()
    response=client.get(f"/v1/dify-runtime/bindings/{bound['binding_id']}/skills")
    assert response.json()['total']==1
    assert client.post(url,json={**body,'archive_base64':'!'}).status_code==400


def test_skill_gate_requires_govern_scope(api):
    client,bound,factory=api
    with factory() as db:
        db.query(models.AccessToken).update({'scopes_json':'["runtime:trace"]'})
        db.commit()
    response=client.post(f"/v1/dify-runtime/bindings/{bound['binding_id']}/skills/publish-check",
                         json={'dify_agent_id':'native','skills':[]})
    assert response.status_code==403


def test_adapter_skill_gate_does_not_publish_rejected_content(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from werkzeug.exceptions import Forbidden, ServiceUnavailable
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime import skills
    from am_dify_runtime.client import Blocked
    original=Mock(return_value='published')
    class Composer:
        _create_config_version=classmethod(original)
    module=SimpleNamespace(AgentComposerService=Composer,
                           AgentConfigRevisionOperation=SimpleNamespace(PUBLISH_DRAFT='publish'))
    gate=Mock(side_effect=Forbidden('pending'))
    monkeypatch.setattr(skills,'check_soul',gate)
    skills.patch_composer(module)
    kwargs=dict(session=object(),tenant_id='workspace',agent_id='agent',agent_soul=object(),operation='publish')
    with pytest.raises(Forbidden):Composer._create_config_version(**kwargs)
    original.assert_not_called()
    gate.side_effect=None
    assert Composer._create_config_version(**kwargs)=='published'
    gate.reset_mock()
    Composer._create_config_version(**{**kwargs,'operation':'save_draft'})
    gate.assert_not_called()
    client=SimpleNamespace(binding='binding',post=Mock(side_effect=Blocked('unavailable')))
    with pytest.raises(ServiceUnavailable):skills.send_package(client,'agent',b'zip')


def test_run_audit_status_orders_by_creation_time(api, monkeypatch):
    from datetime import datetime
    from backend import iam
    monkeypatch.setattr(iam, 'permission_codes', lambda db, user: {'traces:view'})
    client, binding, factory = api
    start(api, "older")
    start(api, "newer")
    with factory() as db:
        for run_id, timestamp in [("older", datetime(2026, 1, 1)), ("newer", datetime(2026, 1, 2))]:
            run = db.query(models.DifyRuntimeRun).filter_by(run_id=run_id).one()
            task = db.query(models.RuntimeTask).filter_by(task_id=run.task_id).one()
            task.created_at = timestamp
            task.status = "succeeded"
            task.completed_at = timestamp
        db.commit()
    result = client.get(f"/v1/dify-runtime/bindings/{binding['binding_id']}/status")
    assert result.status_code == 200
    runs = result.json()["runs"]
    assert [run["run_id"] for run in runs] == ["newer", "older"]
    assert all(run["status"] == "succeeded" and run["completed_at"] and run["trace_id"] for run in runs)
    monkeypatch.setattr(iam, 'permission_codes', lambda db, user: set())
    assert client.get(f"/v1/dify-runtime/bindings/{binding['binding_id']}/status").json()['runs'] == []


def test_binding_run_idempotency_and_identity(api):
    client, binding, _ = api
    assert start(api) == start(api)
    response = client.post(f"/v1/dify-runtime/bindings/{binding['binding_id']}/runs", json={
        "run_id": "run", "workspace_id": "another", "app_id": "app", "workflow_id": "workflow", "graph_digest": "a"*64})
    assert response.status_code == 403


def test_register_application_without_scan_target_and_atomic_conflict(api):
    client, _, factory = api
    identity = {"instance_id": "new-instance", "workspace_id": "workspace", "app_id": "new-app"}
    response = client.post("/agents", json={"agent_id": "new-agent", "name": "New", "dify": identity})
    assert response.status_code == 200, response.text
    agent = response.json()
    assert agent["dify"] == identity
    items = client.get("/v1/dify-runtime/bindings", params={"agent_id": "new-agent"}).json()["items"]
    assert len(items) == 1 and items[0]["target_id"] is None
    with factory() as db:
        assert db.query(models.SecurityTarget).count() == 1
        token = db.query(models.AccessToken).first()
        token.bound_agent_id = "new-agent"
        db.commit()
    response = client.post(f"/v1/dify-runtime/bindings/{items[0]['binding_id']}/runs", json={
        "run_id": "new-run", "workspace_id": "workspace", "app_id": "new-app",
        "workflow_id": "workflow", "graph_digest": "a" * 64})
    assert response.status_code == 200, response.text
    duplicate = client.post("/agents", json={"agent_id": "duplicate", "name": "Duplicate", "dify": identity})
    assert duplicate.status_code == 409
    with factory() as db:
        assert db.query(models.ManagedAgent).filter_by(agent_id="duplicate").first() is None
    assert client.put(f"/agents/{agent['id']}", json={"name": "Renamed", "dify": identity}).status_code == 200
    assert client.put(f"/agents/{agent['id']}", json={"agent_id": "changed"}).status_code == 409
    assert client.delete(f"/agents/{agent['id']}").status_code == 409


def test_runtime_binding_management_is_scoped_to_agent_owner(api):
    client, record, factory = api
    with factory() as db:
        db.query(models.ManagedAgent).filter_by(agent_id="agent-dify").one().created_by = "another-user"
        db.commit()
    assert client.get("/v1/dify-runtime/bindings").json()["items"] == []
    assert client.get(f"/v1/dify-runtime/bindings/{record['binding_id']}/status").status_code == 404
    assert client.put(f"/v1/dify-runtime/bindings/{record['binding_id']}", json={
        "revision": 1, "mode": "enforce", "policy": {}}).status_code == 404


def test_runtime_ownership_survives_scan_target_removal(api):
    client, record, factory = api
    with factory() as db:
        db.delete(db.query(models.SecurityTarget).first())
        db.commit()
    assert start(api)
    with factory() as db:
        db.query(models.AccessToken).first().user_id = 999
        db.commit()
    response = client.post(f"/v1/dify-runtime/bindings/{record['binding_id']}/runs", json={
        "run_id": "wrong-owner", "workspace_id": "workspace", "app_id": "app",
        "workflow_id": "workflow", "graph_digest": "a" * 64})
    assert response.status_code == 403


def test_dify_registration_validation(api):
    client, _, _ = api
    response = client.post("/agents", json={"agent_id": "bad", "name": "Bad", "dify": {
        "instance_id": " ", "workspace_id": "workspace", "app_id": "app"}})
    assert response.status_code == 422
    response = client.post("/agents", json={"agent_id": "unused", "name": "Unused", "dify": {
        "instance_id": "instance", "workspace_id": "workspace", "app_id": "unused"}})
    assert response.status_code == 200
    assert client.delete(f"/agents/{response.json()['id']}").status_code == 200
    assert client.get("/v1/dify-runtime/bindings", params={"agent_id": "unused"}).json()["items"] == []


def test_optional_scan_binding_checks_identity_and_owner(api):
    from backend.routers.security_scans import _validate_dify_runtime_agent, _dify_runtime_inventory_snapshot
    client, record, factory = api
    path = start(api)
    assert client.post(path + "/authorize", json=call()).status_code == 200
    with factory() as db:
        user = db.query(models.User).filter_by(username="tester").one()
        config = {"runtime_agent_id": "agent-dify", "workspace_id": "workspace", "app_id": "app"}
        row = _validate_dify_runtime_agent(db, config, user)
        assert row.binding_id == record["binding_id"]
        with pytest.raises(ApiError):
            _validate_dify_runtime_agent(db, {**config, "app_id": "other"}, user)
        with pytest.raises(ApiError):
            _validate_dify_runtime_agent(db, {**config, "runtime_agent_id": ["agent-dify"]}, user)
        assert _dify_runtime_inventory_snapshot(db, app_id="app", agent_id="agent-dify", owner_user_id=user.id, owner_group_id=None)
        assert not _dify_runtime_inventory_snapshot(db, app_id="app", agent_id="agent-dify", owner_user_id=999, owner_group_id=None)


def test_dify_management_permission_mapping():
    from starlette.requests import Request
    from backend.iam_routes import route_permission
    for method, path, expected in (
        ("POST", "/api/agents", "agents:create"),
        ("GET", "/api/v1/dify-runtime/bindings", "agents:view"),
        ("GET", "/api/v1/dify-runtime/bindings/b/status", "runtime:view"),
        ("PUT", "/api/v1/dify-runtime/bindings/b", "runtime:update"),
        ("POST", "/api/v1/dify-runtime/actions/a/review", "runtime:execute"),
        ("GET", "/api/v1/runtime-traces", "traces:view"),
    ):
        assert route_permission(Request({"type": "http", "method": method, "path": path, "headers": []})) == expected


def test_dify_migration_retains_binding_and_children(tmp_path):
    from backend.dify_runtime_migration import upgrade_dify_runtime_schema
    from sqlalchemy import inspect
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE TABLE dify_runtime_bindings (
            binding_id VARCHAR(64) PRIMARY KEY, target_id VARCHAR(64) NOT NULL UNIQUE,
            agent_id VARCHAR(128) NOT NULL UNIQUE, instance_id VARCHAR(128) NOT NULL,
            workspace_id VARCHAR(128) NOT NULL, app_id VARCHAR(128) NOT NULL,
            mode VARCHAR(16) NOT NULL, revision INTEGER NOT NULL, policy_json TEXT NOT NULL,
            updated_at DATETIME NOT NULL, UNIQUE(instance_id, workspace_id, app_id))""")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(models.ManagedAgent(agent_id="agent", name="Agent"))
        db.add(models.SecurityTarget(target_id="target", name="Target", target_type="agent", endpoint_url="http://dify",
                                    owner_user_id=12, owner_group_id=34, created_by="original"))
        db.commit()
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO dify_runtime_bindings VALUES ('binding','target','agent','instance','workspace','app','enforce',7,'{}','2026-10-20 00:00:00')")
        conn.exec_driver_sql("INSERT INTO dify_runtime_processes (binding_id,process_id,report_json,seen_at) VALUES ('binding','process','{}','2026-10-20 00:00:00')")
    upgrade_dify_runtime_schema(engine)
    upgrade_dify_runtime_schema(engine)
    with sessionmaker(bind=engine)() as db:
        row = db.get(models.DifyRuntimeBinding, "binding")
        assert (row.owner_user_id, row.owner_group_id, row.revision, row.mode) == (12, 34, 7, "enforce")
        assert db.query(models.DifyRuntimeProcess).one().binding_id == row.binding_id
        assert next(c for c in inspect(engine).get_columns("dify_runtime_bindings") if c["name"] == "target_id")["nullable"]


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
    original = {"text": '<tag>"quoted"</tag>\n' * 1000, "usage": {"prompt_tokens": 123}, "api_key": "private"}
    text = json.dumps(original)
    payload["content"] = {"outputs": [text[i:i+1000] for i in range(0, len(text), 1000)]}
    for _ in range(2):
        response = client.post(f"/v1/dify-runtime/bindings/{binding['binding_id']}/observations", json=payload)
        assert response.status_code == 200, response.text
    with api[2]() as db:
        assert db.query(models.RuntimeTraceEvent).filter_by(event_id="d"*32).count() == 1
        stored = json.loads(db.query(models.RuntimeTracePayload).filter_by(event_id="d"*32).one().redacted_json)
        restored = json.loads("".join(stored["content"]["outputs"]))
        assert restored == {**original, "api_key": "[REDACTED]"}
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


@pytest.mark.parametrize("version,message,terminal", [
    ("0.6.0", "agent-manager:approval", True),
    ("0.6.0", "human input", False),
    ("0.5.3", "agent-manager:approval", False),
])
def test_adapter_pause_closes_stream_without_aborting_resume(monkeypatch, version, message, terminal):
    from types import SimpleNamespace
    from threading import Event
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime import hooks
    class Paused:
        reasons = [SimpleNamespace(message=message)]
    class Queue:
        def __init__(self):
            self._execution_terminal = Event()
        def _publish(self, event, pub_from):
            return (event, pub_from)
    monkeypatch.setattr(hooks.importlib.metadata, "version", lambda name: version)
    monkeypatch.setitem(sys.modules, "core.app.entities.queue_entities", SimpleNamespace(QueueWorkflowPausedEvent=Paused))
    hooks.patch_pause_queue(SimpleNamespace(WorkflowAppQueueManager=Queue))
    queue, event = Queue(), Paused()
    assert queue._publish(event, "test") == (event, "test")
    assert queue._execution_terminal.is_set() is terminal
    other = Queue()
    other._publish(object(), "test")
    assert not other._execution_terminal.is_set()


def test_execution_preview_redacts_and_bounds_content(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime.client import preview
    value = json.loads(preview({"count": 2, "nested": {"api_key": "private"}, "message": "Bearer private"}))
    assert value == {"count": 2, "nested": {"api_key": "[REDACTED]"}, "message": "Bearer [REDACTED]"}
    assert len(preview({"result": "x" * 10000})) == 8000


def test_node_observation_preserves_execution_failure(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime.hooks import scoped_generator
    observed = []
    client = SimpleNamespace(observe=lambda *args, **kwargs: observed.append((args, kwargs)))
    event = SimpleNamespace(node_run_result=SimpleNamespace(status="failed", inputs={"order": ""}, outputs={}, error="Order required"))
    assert list(scoped_generator(iter([event]), client, {}, None)) == [event]
    assert observed == [(({}, "step.end", "failed"), {"inputs": {"order": ""}, "outputs": {}, "error": "Order required"})]


def test_adapter_full_content_chunks_and_limits(monkeypatch):
    from backend.dify_runtime_schemas import Observation
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime.client import Client
    client = object.__new__(Client)
    client.binding = "binding"
    messages = []
    client.enqueue = lambda path, body: messages.append(body)
    context = dict(run_id="run", workspace_id="workspace", app_id="app", workflow_id="workflow", graph_digest="a"*64,
                   node_id="node", execution_id="execution", node_type="llm")
    text = "<完整内容>" * 4000
    client.observe(context, "model.response", "succeeded", outputs={"text": text, "api_key": "secret"})
    body = Observation.model_validate(messages[-1])
    assert not body.truncated
    assert json.loads("".join(body.content["outputs"])) == {"text": text, "api_key": "[REDACTED]"}
    client.observe(context, "model.response", "succeeded", outputs="123")
    assert json.loads("".join(messages[-1]["content"]["outputs"])) == "123"
    client.observe(context, "model.response", "succeeded", outputs="x" * 1_100_000)
    assert Observation.model_validate(messages[-1]).truncated


@pytest.mark.parametrize("stream,fail", [(False, False), (True, False), (True, True)])
def test_model_capture_preserves_return_and_partial_failure(monkeypatch, stream, fail):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime import hooks
    result = SimpleNamespace(message="full reply")
    chunk = SimpleNamespace(delta={"message": {"content": "partial"}})
    class Model:
        model_name = "test-model"
        provider = "local-test"
        def invoke_llm(self, prompt_messages, stream=True):
            def chunks():
                yield chunk
                if fail:
                    raise ValueError("model failed")
            return chunks() if stream else result
    module = SimpleNamespace(ModelInstance=Model)
    hooks.patch_models(module)
    observed = []
    client = SimpleNamespace(observe=lambda *args, **kwargs: observed.append((args, kwargs)))
    token = hooks.current.set((client, {}))
    try:
        response = Model().invoke_llm([{"role": "user", "content": "question"}], stream=stream)
        if stream:
            assert next(response) is chunk
            with pytest.raises(ValueError if fail else StopIteration):
                next(response)
        else:
            assert response is result
    finally:
        hooks.current.reset(token)
    assert observed[0][1]["inputs"]["prompt_messages"][0]["content"] == "question"
    assert len({details["request_id"] for _, details in observed}) == 1
    assert observed[-1][0][1:] == (("model.error", "failed") if fail else ("model.response", "succeeded"))


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


@pytest.mark.parametrize('mode,allowed,reason', [('observe', True, 'observe_unapproved'), ('enforce', False, 'unapproved_blocked')])
def test_skill_admission_audit_keeps_certification_separate_from_allow(monkeypatch, mode, allowed, reason):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'integrations/dify-runtime/python'))
    from am_dify_runtime import agent_backend as adapter
    from am_dify_runtime.client import Blocked
    client = SimpleNamespace(binding='binding', post=lambda *a, **k: {
        'allowed': allowed, 'mode': mode,
        'skills': [{'name': 'review-skill', 'status': 'VETTED', 'allowed': False, 'reason': 'vetted'}]})
    observe = AsyncMock()
    monkeypatch.setattr(adapter, 'observe', observe)
    call = adapter.check_package((client, {'execution_id': 'parent'}, SimpleNamespace(agent_id='native')), 'review-skill', b'archive')
    if allowed:
        asyncio.run(call)
    else:
        with pytest.raises(Blocked, match='skill_not_approved'):
            asyncio.run(call)
    payload = observe.await_args.kwargs['execution']['skill_admission']
    assert payload == {'name': 'review-skill', 'status': 'VETTED', 'certified': False,
                       'allowed': allowed, 'mode': mode, 'reason': reason, 'check_reason': 'vetted'}
    assert observe.await_args.args[0][1]['execution_id'] != 'parent'
    assert observe.await_args.args[2] == ('succeeded' if allowed else 'blocked')


def test_agent_skill_pull_rejects_before_delivering_bytes(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime import agent_backend as adapter
    from am_dify_runtime.client import Blocked
    class Handler:
        async def pull_skill(self, **kwargs):
            return b'full archive'
    class Rejected(RuntimeError):
        def __init__(self, code, message):
            self.code = code
            super().__init__(message)
    module = SimpleNamespace(DifyApiAgentStubConfigRequestHandler=Handler, AgentStubConfigRequestError=Rejected)
    adapter.patch_skill_pull(module)
    state = (None, {}, None)
    monkeypatch.setattr(adapter, 'context_for', lambda *a: state)
    async def controlled(state, kind, title, params, invoke, **kwargs):
        return await invoke()
    monkeypatch.setattr(adapter, 'controlled', controlled)
    monkeypatch.setattr(adapter, 'observe', AsyncMock())
    checker = AsyncMock(side_effect=Blocked('retired'))
    monkeypatch.setattr(adapter, 'check_package', checker)
    principal = SimpleNamespace(execution_context=None, token_id='native-token-id')
    with pytest.raises(Rejected) as error:
        asyncio.run(Handler().pull_skill(principal=principal, name='test'))
    assert error.value.code == 403
    checker.assert_awaited_once_with(state, 'test', b'full archive')
    checker.side_effect = None
    checker.return_value = {'allowed': True}
    assert asyncio.run(Handler().pull_skill(principal=principal, name='test')) == b'full archive'


def test_shell_denial_and_revocation_never_invoke_command(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime import agent_backend as adapter
    from am_dify_runtime.client import Blocked
    invoked = []
    class Shell:
        async def _tool_run(self, script):
            invoked.append(script)
            return 'OK'
        _tool_input = _tool_run
        _tool_wait = _tool_run
        _tool_interrupt = _tool_run
        _bootstrap_workspace = _tool_run
    adapter.patch_shell(SimpleNamespace(DifyShellLayer=Shell))
    check = AsyncMock()
    monkeypatch.setattr(adapter, 'check_config', check)
    async def deny(*args, **kwargs):
        raise Blocked('denied')
    monkeypatch.setattr(adapter, 'controlled', deny)
    marker = adapter.active.set((None, {}, None))
    try:
        with pytest.raises(Blocked):
            asyncio.run(Shell()._tool_run('touch marker'))
        assert not invoked
        async def allow(state, kind, title, params, invoke, **kwargs):
            return await invoke()
        monkeypatch.setattr(adapter, 'controlled', allow)
        check.side_effect = Blocked('retired')
        with pytest.raises(Blocked):
            asyncio.run(Shell()._tool_run('touch marker'))
        assert not invoked
        check.side_effect = None
        assert asyncio.run(Shell()._tool_run('printf OK')) == 'OK'
        assert invoked == ['printf OK']
    finally:
        adapter.active.reset(marker)


@pytest.mark.parametrize("decision,raises", [("authorized", False), ("authorized", True), ("blocked", False), ("expired", False)])
def test_agent_async_authorization_waits_and_reports_completion(tmp_path, monkeypatch, decision, raises):
    import asyncio
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "integrations/dify-runtime/python"))
    from am_dify_runtime.client import Client, Blocked
    credentials = tmp_path/'credentials.json'
    credentials.write_text('{"binding":"test"}')
    monkeypatch.setattr('threading.Thread.start', lambda self: None)
    monkeypatch.setattr('am_dify_runtime.client.time.sleep', lambda _: None)
    client = Client({'credentials_file':str(credentials),'queue_dir':str(tmp_path/'queue'),'server_url':'http://test'},
                    {'binding_id':'binding','mode':'enforce'})
    monkeypatch.setattr(client,'run',lambda _: {'task_id':'task'})
    phases = []
    def post(path, body):
        if path.endswith('/authorize'):
            phases.append('authorize')
            return {'action_id':'action','status':'pending' if len(phases)==1 else decision,
                    'mode':'enforce','revision':1,'authorization_token':'once'}
        if path.endswith('/consume'):
            phases.append('consume')
            return {'authorized':True}
        assert path.endswith('/result')
        phases.append(body['status'])
        return {'accepted':True}
    monkeypatch.setattr(client,'post',post)
    async def command():
        phases.append('invoke')
        if raises:raise ValueError('command failure')
        return 'stdout'
    context={'run_id':'run','execution_id':'execution','node_id':'node','node_type':'shell'}
    if decision!='authorized':
        with pytest.raises(Blocked):client.execute(context,{}, {},command)
        assert phases==['authorize','authorize']
    else:
        result=client.execute(context,{}, {},command)
        assert phases==['authorize','authorize','consume']
        if raises:
            with pytest.raises(ValueError):asyncio.run(result)
        else:assert asyncio.run(result)=='stdout'
        assert phases[-2:]==['invoke','failed' if raises else 'succeeded']
