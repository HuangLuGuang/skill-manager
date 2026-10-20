import asyncio
import copy
import importlib.util
import json
import sys
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace, ModuleType

import pytest

from backend import models
from backend.external_access_models import ExternalAgentJob, ExternalResultEvent, ExternalGatewayEvent
from backend.security_scan_controls import unprotect_secret
from tests.test_external_access import setup
from tests.test_openapi_agents import api, register, ready, evaluate, claim, complete, bearer
from tests.test_ai_infra_guard_adapter import aig_adapter, WORKER_DIR


def worker_module(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("agent_live_worker", WORKER_DIR / "worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HEALTH_PATH", tmp_path / "worker.healthy")
    return module


def test_detection_counts_track_overlapping_workers_and_exclude_recon_review():
    claim_data = {}
    progress = aig_adapter.AgentScanProgress(claim_data, ["first", "second"], lambda i: f"2{i}")
    snapshots = []
    async def exercise():
        first_running, release = asyncio.Event(), asyncio.Event()
        async def run(*args, **kwargs):
            snapshots.append(copy.deepcopy(claim_data["scan_progress"]))
            if kwargs["stage_id"] == "20":
                first_running.set()
                await release.wait()
                return "result", {"dialogue": 7}
            if kwargs["stage_id"] == "21":
                raise ValueError("private model response")
            return "recon/review", {}
        tracked = progress.wrap(run)
        await tracked(stage_id="1", context_data={})
        first = asyncio.create_task(tracked(stage_id="20", context_data={"Assigned Skill": "first"}))
        await first_running.wait()
        with pytest.raises(ValueError):
            await tracked(stage_id="21", context_data={"Assigned Skill": "second"})
        assert claim_data["scan_progress"] == {"observed_total": 2, "completed": 1, "running": 1, "errors": 1}
        release.set()
        assert await first == ("result", {"dialogue": 7})
        await tracked(stage_id="3", context_data={})
        assert claim_data["scan_progress"] == {"observed_total": 2, "completed": 2, "running": 0, "errors": 1}
    asyncio.run(exercise())
    assert snapshots[0]["running"] == snapshots[0]["completed"] == 0
    assert snapshots[2]["running"] == 2
    assert "private" not in json.dumps(claim_data)
    assert snapshots[1]["completed"] == 0  # Published snapshots remain immutable.


def test_worker_retries_unsent_progress_without_duplicates(monkeypatch, tmp_path):
    module = worker_module(monkeypatch, tmp_path)
    bodies = []
    attempts = 0
    def request(path, body):
        nonlocal attempts
        if path.endswith("heartbeat"):
            bodies.append(copy.deepcopy(body))
            attempts += 1
            if attempts == 1:
                raise module.urllib.error.URLError("temporary")
        return {"continue_allowed": True}
    def execute(job, secret, evaluator, heartbeat, *, initial_usage):
        job["scan_progress"] = {"observed_total": 3, "completed": 1, "running": 1, "errors": 0}
        with pytest.raises(module.urllib.error.URLError): heartbeat(initial_usage)
        assert "reported_scan_progress" not in job
        heartbeat(initial_usage)
        heartbeat(initial_usage)
        job["scan_progress"] = {"observed_total": 3, "completed": 2, "running": 1, "errors": 1}
        heartbeat(initial_usage)
        return {"status": "succeeded", "usage": initial_usage, "cases": [], "findings": [], "artifacts": []}
    monkeypatch.setattr(module, "_request", request)
    monkeypatch.setattr(module, "execute_agent_scan", execute)
    module._run_agent_scan({"task": {"task_id": "task"}, "lease_token": "lease", "credential": {}}, SimpleNamespace(), "worker")
    assert bodies[0]["scan_progress"] == bodies[1]["scan_progress"]
    assert "scan_progress" not in bodies[2]
    assert bodies[3]["scan_progress"]["completed"] == 2


def test_keepalive_sends_progress_during_blocked_agent_execution(monkeypatch, tmp_path):
    module = worker_module(monkeypatch, tmp_path)
    received = threading.Event()
    def request(path, body):
        if path.endswith("heartbeat") and body.get("scan_progress", {}).get("running") == 1:
            received.set()
        return {"continue_allowed": True}
    def execute(job, secret, evaluator, heartbeat, *, initial_usage):
        job["scan_progress"] = {"observed_total": 2, "completed": 0, "running": 1, "errors": 0}
        assert received.wait(4), "keepalive did not publish progress while execution was blocked"
        return {"status": "succeeded", "usage": initial_usage, "cases": [], "findings": [], "artifacts": []}
    monkeypatch.setattr(module, "_request", request)
    monkeypatch.setattr(module, "execute_agent_scan", execute)
    module._run_agent_scan({"task": {"task_id": "task"}, "lease_token": "lease", "lease_seconds": 3, "credential": {}}, SimpleNamespace(), "worker")


def running(api):
    register(api)
    connection = ready(api)
    response = evaluate(api, connection)
    assert response.status_code == 202, response.text
    return claim(api)


def heartbeat(api, job, progress, **extra):
    return api[0].post(f"/api/v1/agent-security/worker/tasks/{job['task']['task_id']}/heartbeat", headers=api[3],
        json={"lease_token": job["lease_token"], "scan_progress": progress, **extra})


def external_progress(api, task_id):
    response = api[0].get("/openapi/v1/agent-evaluations/" + task_id, headers=bearer(api[2]))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_running_queries_share_counts_and_terminal_uses_report_snapshot(api):
    job = running(api)
    client, sessions = api[:2]
    task_id = job["task"]["task_id"]
    counts = {"observed_total": 4, "completed": 2, "running": 1, "errors": 1}
    assert heartbeat(api, job, counts).status_code == 200
    public = external_progress(api, task_id)
    assert {key: public["progress"][key] for key in counts} == counts
    assert public["status"] == "running" and not public["result_ready"]
    assert public["progress"]["percent"] is None
    detail = client.get("/api/v1/agent-security/tasks/" + task_id).json()["task"]["progress"]
    listed = next(row for row in client.get("/api/v1/agent-security/tasks").json() if row["task_id"] == task_id)["progress"]
    assert detail["planned"] == listed["planned"] == 4
    assert {key: detail[key] for key in counts} == {key: listed[key] for key in counts} == counts
    assert detail["updated_at"]
    with sessions() as db:
        row = db.get(ExternalAgentJob, task_id)
        assert row.report_json is None
        assert db.query(ExternalResultEvent).filter_by(task_id=task_id).count() == 0
        assert db.query(ExternalGatewayEvent).filter_by(task_id=task_id).count() == 0
    complete(api, job, cases=[{"external_case_id": "a", "category": "agent_detection_skill", "title": "A", "status": "passed"},
                              {"external_case_id": "b", "category": "agent_detection_skill", "title": "B", "status": "error"}])
    final = external_progress(api, task_id)
    assert final["progress"] == {"stage": "finished", "percent": None, "observed_total": 2, "completed": 2, "running": 0, "errors": 1}
    detail = client.get("/api/v1/agent-security/tasks/" + task_id).json()["task"]["progress"]
    listed = next(row for row in client.get("/api/v1/agent-security/tasks").json() if row["task_id"] == task_id)["progress"]
    assert detail["planned"] == listed["planned"] == 4
    assert detail["completed"] == listed["completed"] == 2
    assert detail["errors"] == listed["errors"] == 1 and detail["running"] == listed["running"] == 0
    with sessions() as db:
        saved = (db.get(ExternalAgentJob, task_id).report_json,
                 db.query(ExternalResultEvent).filter_by(task_id=task_id).one().payload_json,
                 db.get(ExternalGatewayEvent, task_id).payload_json)
    assert heartbeat(api, job, counts).status_code == 409
    with sessions() as db:
        assert saved == (db.get(ExternalAgentJob, task_id).report_json,
                         db.query(ExternalResultEvent).filter_by(task_id=task_id).one().payload_json,
                         db.get(ExternalGatewayEvent, task_id).payload_json)


@pytest.mark.parametrize("counts", [
    {"observed_total": 1, "completed": 1, "running": 1},
    {"observed_total": 1, "completed": 0, "errors": 1},
    {"observed_total": -1},
])
def test_invalid_counts_do_not_replace_saved_progress(api, counts):
    job = running(api)
    before = {"observed_total": 3, "completed": 1, "running": 1, "errors": 0}
    assert heartbeat(api, job, before).status_code == 200
    assert heartbeat(api, job, counts).status_code == 422
    actual = external_progress(api, job["task"]["task_id"])["progress"]
    assert {key: actual[key] for key in before} == before


def test_retry_starts_with_fresh_counts_and_rejects_old_lease(api):
    job = running(api)
    task_id = job["task"]["task_id"]
    counts = {"observed_total": 3, "completed": 1, "running": 1, "errors": 0}
    assert heartbeat(api, job, counts).status_code == 200
    with api[1]() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        task.max_attempts = 3
        db.commit()
    response = api[0].post(f"/api/v1/agent-security/worker/tasks/{task_id}/complete", headers=api[3], json={
        "lease_token": job["lease_token"], "status": "failed", "retryable": True, "error_code": "temporary", "cases": [], "findings": [], "artifacts": []})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert external_progress(api, task_id)["progress"]["completed"] == 0
    with api[1]() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        task.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    new_job = claim(api)
    assert new_job["task"]["task_id"] == task_id
    assert external_progress(api, task_id)["progress"]["completed"] == 0
    with api[1]() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        assert "live_progress" not in json.loads(unprotect_secret(task.scan_options_encrypted))
    assert heartbeat(api, job, counts).status_code == 401
    fresh = {"observed_total": 3, "completed": 0, "running": 1, "errors": 0}
    assert heartbeat(api, new_job, fresh).status_code == 200
    assert external_progress(api, task_id)["progress"]["completed"] == 0


@pytest.mark.parametrize("fail", [False, True])
def test_execute_installs_tracking_and_restores_hooks(monkeypatch, fail):
    import agent_scan.core
    import agent_scan.utils
    module = ModuleType("agent_scan.core.agent")
    context_module = ModuleType("agent_scan.utils.tool_context")
    class Context:
        def call_provider(self, prompt): return prompt
    context_module.ToolContext = Context
    old_provider = Context.call_provider
    job = {"task": {"task_id": "test"}, "target": {"config": {}}, "policy": {},
           "scan_options": {"skills": ["data-leakage-detection"]}}
    snapshots = []
    async def run_agent(**kwargs):
        snapshots.append(copy.deepcopy(job["scan_progress"]))
        if fail: raise RuntimeError("engine failed")
        return "result", {"dialogue": 2}
    module.run_agent = run_agent
    module._WORKER_CONCURRENCY = 4
    module._worker_stage_id = lambda i: f"2{i}"
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(sys.modules, context_module.__name__, context_module)
    monkeypatch.setattr(agent_scan.core, "agent", module, raising=False)
    class Agent:
        def __init__(self, **kwargs): self.skills = kwargs["skills"]
        async def scan(self, *args):
            await module.run_agent(stage_id="20", context_data={"Assigned Skill": self.skills[0]})
            return {}
    monkeypatch.setattr(aig_adapter, "_upstream_types", lambda: (Agent, None, None, None, None))
    monkeypatch.setattr(aig_adapter, "_bounded_client_class", lambda _: object)
    monkeypatch.setattr(aig_adapter, "_instrumented_llm_class", lambda _: lambda **kw: object())
    monkeypatch.setattr(aig_adapter, "build_provider_document", lambda *args, **kwargs: {})
    monkeypatch.setattr(aig_adapter, "verify_worker_dns_pin", lambda _: None)
    monkeypatch.setattr(aig_adapter.ScanRuntime, "ensure_trustworthy_result", lambda _: None)
    monkeypatch.setattr(aig_adapter, "_normalize_report", lambda *args, **kwargs: {"artifacts": []})
    def execute():
        return aig_adapter.execute_agent_scan(job, None, aig_adapter.EvaluatorConfig("placeholder", "judge", "http://model.test"),
            lambda _: {"continue_allowed": True})
    if fail:
        with pytest.raises(RuntimeError): execute()
    else:
        execute()
    assert snapshots[0]["running"] == 1 and snapshots[0]["completed"] == 0
    assert job["scan_progress"] == {"observed_total": 1, "completed": 1, "running": 0, "errors": int(fail)}
    assert module.run_agent is run_agent and module._WORKER_CONCURRENCY == 4
    assert Context.call_provider is old_provider
