from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SERVICE_PATH = Path("services/aig-scan-service/service.py").resolve()
SPEC = importlib.util.spec_from_file_location("aig_scan_service", SERVICE_PATH)
assert SPEC and SPEC.loader
service = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


class FakeUpstream:
    def __init__(self):
        self.created = []
        self.terminated = []
        self.current_status = "running"

    def health(self):
        return None

    def create_task(self, task_type, content):
        self.created.append((task_type, content))
        return f"session-{len(self.created)}"

    def status(self, session_id):
        return {"session_id": session_id, "status": self.current_status}

    def result(self, session_id):
        return {"session_id": session_id, "results": []}

    def request_termination(self, session_id):
        self.terminated.append(session_id)
        return True


class FakeSupervisor:
    def __init__(self):
        self.running = True
        self.restart_count = 0

    def ensure_running(self):
        self.running = True

    def is_running(self):
        return self.running

    def stop_execution(self):
        self.running = False
        return True

    def restart_after_cancel(self):
        self.restart_count += 1
        self.running = True
        return True


@pytest.mark.parametrize(("message", "suffix"), [
    ("加载模型：qwen3:1.7b 失败: 404 page not found", "model_not_found"),
    ("Error code: 401 invalid key secret", "model_auth_failed"),
    ("Error code: 429", "model_rate_limited"),
    ("Connection error", "model_connection_failed"),
    ("Request timed out", "model_timeout"),
    ("加载模型失败 secret", "model_initialization_failed"),
    ("unexpected secret prompt", "task_failed"),
])
def test_failure_status_classifies_without_exposing_upstream_content(tmp_path, message, suffix):
    runtime, upstream, _ = _runtime(tmp_path)
    runtime.create("model_redteam_report", _redteam_content(), "failure-test-key")
    upstream.status = lambda session: {
        "session_id": session, "status": "error", "error_message": message,
        "log": "Authorization: Bearer secret; private prompt",
    }
    result = runtime.status("session-1")
    assert result == {"session_id": "session-1", "status": "error", "error_code": f"agent_security.aig_{suffix}"}


def _runtime(tmp_path):
    upstream = FakeUpstream()
    supervisor = FakeSupervisor()
    registry = service.TaskRegistry(tmp_path / "jobs.db", max_jobs=10)
    return service.Runtime(upstream, supervisor, registry), upstream, supervisor


def _model(name="target-model", token="short-lived-secret"):
    return {"model": name, "token": token, "base_url": "https://models.example/v1", "limit": 1}


def _infra_content():
    return {
        "target": ["https://8.8.8.8"],
        "headers": {},
        "timeout": 30,
        "model": _model("evaluator-model"),
        "network_policy": {
            "expected_ips": ["8.8.8.8"],
            "allowed_cidrs": [],
            "policy_allowed_cidrs": [],
            "allow_http": False,
        },
    }


def _redteam_content(token="plaintext-target-secret"):
    return {
        "model": [_model(token=token)],
        "eval_model": _model("evaluator-model", "short-lived-evaluator-secret"),
        "dataset": {"dataFile": ["JailBench-Tiny"], "numPrompts": 2, "randomSeed": 42},
        "prompt": "",
        "techniques": ["Raw"],
    }


def test_redteam_target_accepts_empty_token_but_evaluator_requires_credentials():
    content = _redteam_content(token="")
    service._validate_task_content("model_redteam_report", content)
    content["eval_model"]["token"] = ""
    with pytest.raises(service.ServiceError) as error:
        service._validate_task_content("model_redteam_report", content)
    assert error.value.status == 422


@pytest.mark.parametrize("token", [None, 123, "\r\n", "x" * 8193])
def test_redteam_target_still_validates_token_type_and_header_safety(token):
    with pytest.raises(service.ServiceError):
        service._validate_task_content("model_redteam_report", _redteam_content(token=token))


def test_all_bundled_datasets_are_accepted_by_backend_and_service():
    import json
    from backend.security_redteam_catalog import LLM_REDTEAM_DATASETS, LLM_REDTEAM_DATASET_METADATA
    from backend.security_scan_schemas import SecurityTaskPlanRequest

    assert set(LLM_REDTEAM_DATASETS) == service.ALLOWED_DATASETS
    request = SecurityTaskPlanRequest(
        target_id="target", policy_id="policy", scan_kind="llm_redteam_scan",
        datasets=list(LLM_REDTEAM_DATASETS),
    )
    assert len(request.datasets) == 17
    metadata = {item["name"]: item for item in LLM_REDTEAM_DATASET_METADATA}
    for name in request.datasets:
        dataset = json.loads((service.DATASET_DIRECTORY / f"{name}.json").read_text())
        assert dataset["name"] == name
        assert metadata[name]["count"] == len(dataset["data"])
        for key in ("description", "description_zh", "tags", "recommendation", "language"):
            assert metadata[name][key] == dataset.get(key, [] if key == "tags" else "")
        assert "data" not in metadata[name]
        assert dataset["data"] and all(isinstance(item["prompt"], str) for item in dataset["data"])
        content = _redteam_content()
        content["dataset"]["dataFile"] = [name]
        service._validate_task_content("model_redteam_report", content)


def test_wrapper_is_idempotent_serialized_and_does_not_persist_task_secrets(tmp_path):
    runtime, upstream, _ = _runtime(tmp_path)
    first = runtime.create(
        "model_redteam_report",
        _redteam_content(),
        "stable-platform-task-key",
    )
    duplicate = runtime.create(
        "model_redteam_report",
        _redteam_content("different-retry-secret"),
        "stable-platform-task-key",
    )
    assert first == ("session-1", True)
    assert duplicate == ("session-1", False)
    assert len(upstream.created) == 1
    database_bytes = (tmp_path / "jobs.db").read_bytes()
    assert b"plaintext-target-secret" not in database_bytes
    assert b"different-retry-secret" not in database_bytes

    with pytest.raises(service.ServiceError) as busy:
        runtime.create("ai_infra_scan", _infra_content(), "another-task-key")
    assert busy.value.status == 429
    assert busy.value.code == "agent_security.aig_service_unavailable"

    upstream.current_status = "completed"
    assert runtime.status("session-1")["status"] == "completed"
    assert runtime.create(
        "ai_infra_scan",
        _infra_content(),
        "another-task-key",
    ) == ("session-2", True)


def test_wrapper_cancel_requires_owned_session_and_stops_process_group(tmp_path):
    runtime, upstream, supervisor = _runtime(tmp_path)
    runtime.create("ai_infra_scan", _infra_content(), "cancel-task-key")

    result = runtime.cancel("session-1")
    assert result == {
        "session_id": "session-1",
        "status": "cancelled",
        "execution_stopped": True,
        "upstream_acknowledged": True,
    }
    assert upstream.terminated == ["session-1"]
    assert supervisor.restart_count == 1
    assert runtime.registry.by_session("session-1")["status"] == "cancelled"

    with pytest.raises(service.ServiceError) as missing:
        runtime.cancel("not-owned")
    assert missing.value.status == 404


def test_wrapper_http_contract_requires_service_auth_and_true_cancel_ack(tmp_path, monkeypatch):
    runtime, _, _ = _runtime(tmp_path)
    monkeypatch.setenv("AIG_WRAPPER_TOKEN", "service-to-service-secret")
    app = service.create_app(runtime, manage_runtime=False)
    with TestClient(app) as client:
        unauthenticated = client.get("/healthz")
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["error_code"] == "agent_security.aig_service_unavailable"

        headers = {"Authorization": "Bearer service-to-service-secret"}
        health = client.get("/healthz", headers=headers)
        assert health.status_code == 200
        assert health.json()["engine"] == {
            "name": "AI-Infra-Guard",
            "tag": service.ENGINE_TAG,
            "commit": service.ENGINE_COMMIT,
        }
        assert health.json()["cancellation_mode"] == "agent_process_group_termination"

        missing_key = client.post(
            "/v1/tasks",
            headers=headers,
            json={"task_type": "ai_infra_scan", "content": _infra_content()},
        )
        assert missing_key.status_code == 422
        assert missing_key.json()["error_code"] == "agent_security.aig_task_failed"

        created = client.post(
            "/v1/tasks",
            headers={**headers, "Idempotency-Key": "http-contract-task"},
            json={"task_type": "ai_infra_scan", "content": _infra_content()},
        )
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        cancelled = client.post(f"/v1/tasks/{session_id}/cancel", headers=headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["execution_stopped"] is True


def test_wrapper_rejects_unlocked_redteam_inputs_without_echoing_secrets(tmp_path, monkeypatch):
    runtime, _, _ = _runtime(tmp_path)
    monkeypatch.setenv("AIG_WRAPPER_TOKEN", "service-to-service-secret")
    app = service.create_app(runtime, manage_runtime=False)
    with TestClient(app) as client:
        headers = {
            "Authorization": "Bearer service-to-service-secret",
            "Idempotency-Key": "invalid-redteam-task",
        }
        content = _redteam_content("must-never-be-returned")
        content["dataset"]["dataFile"] = ["Unreviewed-Latest-Dataset"]
        response = client.post(
            "/v1/tasks",
            headers=headers,
            json={"task_type": "model_redteam_report", "content": content},
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "agent_security.aig_task_failed"
        assert "must-never-be-returned" not in response.text


def test_wrapper_rechecks_infrastructure_dns_and_http_policy_immediately_before_dispatch(monkeypatch):
    content = _infra_content()
    service._validate_task_content("ai_infra_scan", content)

    rebound = _infra_content()
    monkeypatch.setattr(
        service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(service.socket.AF_INET, service.socket.SOCK_STREAM, 6, "", ("8.8.4.4", 443))],
    )
    with pytest.raises(service.ServiceError) as changed:
        service._validate_task_content("ai_infra_scan", rebound)
    assert changed.value.status == 409
    assert changed.value.code == "agent_security.infra_target_forbidden"

    insecure = _infra_content()
    insecure["target"] = ["http://8.8.8.8"]
    with pytest.raises(service.ServiceError) as http_denied:
        service._validate_task_content("ai_infra_scan", insecure)
    assert http_denied.value.code == "agent_security.infra_target_forbidden"


def test_wrapper_reconciles_finished_upstream_job_before_accepting_next(tmp_path):
    runtime, upstream, _ = _runtime(tmp_path)
    runtime.create("ai_infra_scan", _infra_content(), "first-reconcile-task")
    upstream.current_status = "done"
    assert runtime.create("ai_infra_scan", _infra_content(), "second-reconcile-task") == ("session-2", True)


def test_upstream_result_unwraps_real_ai_infra_guard_transport_envelope(monkeypatch):
    upstream = service.UpstreamClient("http://127.0.0.1:18088")
    report = {"content": [{"results": [{"status": "Safe"}]}]}
    monkeypatch.setattr(
        upstream,
        "_request",
        lambda *_args, **_kwargs: {
            "status": 0,
            "data": {
                "id": "session-real-shape",
                "type": "resultUpdate",
                "timestamp": 1,
                "result": report,
            },
        },
    )

    assert upstream.result("session-real-shape") == report

    monkeypatch.setattr(
        upstream,
        "_request",
        lambda *_args, **_kwargs: {"status": 0, "data": {"result": []}},
    )
    with pytest.raises(service.ServiceError) as invalid:
        upstream.result("session-real-shape")
    assert invalid.value.code == "agent_security.aig_result_invalid"


def test_agent_supervisor_terminates_its_owned_process_group():
    supervisor = service.AgentProcessSupervisor(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        ready_seconds=0,
    )
    supervisor.ensure_running()
    assert supervisor.is_running() is True
    assert supervisor.stop_execution() is True
    assert supervisor.is_running() is False
