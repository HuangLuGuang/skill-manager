"""Cross-batch regressions for the agreed partner contract, sections 3–9."""
import asyncio
import json
from datetime import datetime, timedelta

import httpx
import pytest

from backend import models
from backend.external_access_models import ExternalApiRequest, ExternalAgentJob, ExternalResultEvent, ExternalGatewayEvent, ExternalSkillScan, ExternalDelivery
from backend.routers import external_deliveries
from backend.services import external_delivery
from tests.test_external_access import setup, partner, token, bearer
from tests.test_openapi_agents import api as agent_api, register, registration_body, ready, evaluate, claim, complete
from tests.test_openapi_skills import api as skill_api, submit, url


def test_caller_trace_ids_preserve_separate_requests_and_sources(agent_api):
    client, sessions, issued, *_ = agent_api
    headers = {**bearer(issued), "X-Request-ID": "partner_trace-001"}
    for agent_id in ("agent-a", "agent-b"):
        response = client.post("/openapi/v1/agents", headers=headers, json=registration_body(agent_id=agent_id))
        assert response.status_code == 201
        assert response.json()["request_id"] == response.headers["x-request-id"] == "partner_trace-001"
    other = partner(client, "second", 2)
    other_token = token(client, platform_id=other["platform_id"])
    denied = client.get("/openapi/v1/agents/agent-a", headers={**bearer(other_token), "X-Request-ID": "partner_trace-001"})
    assert denied.status_code == 404 and denied.json()["request_id"] == "partner_trace-001"
    records = client.get("/api/v1/external-access/requests", params={"request_id": "partner_trace-001"}).json()
    assert records["total"] == 3 and len({r["request_id"] for r in records["items"]}) == 3
    with sessions() as db:
        for agent in db.query(models.ManagedAgent).all():
            record = db.query(ExternalApiRequest).filter_by(request_id=agent.source_request_id).one()
            assert record.resource_id == agent.agent_id and record.client_request_id == "partner_trace-001"


@pytest.mark.parametrize("value", ["", "a" * 65, "has space", "has.dot", "<private>"])
def test_invalid_trace_id_has_contract_error_and_no_business_write(agent_api, value):
    client, sessions, issued, *_ = agent_api
    response = client.post("/openapi/v1/agents", headers={**bearer(issued), "X-Request-ID": value}, json=registration_body())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["details"] == [{"field": "X-Request-ID", "reason": "string_pattern_mismatch"}]
    with sessions() as db:
        assert db.query(models.ManagedAgent).count() == 0
        assert db.query(ExternalApiRequest).one().client_request_id is None


@pytest.mark.parametrize("state", ["invalid", "disabled", "revoked", "expired"])
def test_authentication_errors_are_401_and_permissions_remain_403(agent_api, state):
    client, sessions, issued, *_ = agent_api
    register(agent_api)
    with sessions() as db:
        row = db.get(models.AccessToken, issued["record"]["id"])
        if state in {"disabled", "revoked"}:
            row.status = state
        elif state == "expired":
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    headers = bearer(issued) if state != "invalid" else {"Authorization": "Bearer invalid"}
    response = client.get("/openapi/v1/agents/agent-1", headers=headers)
    assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHORIZED"
    limited = token(client, scopes=["openapi:skill-read"])
    forbidden = client.get("/openapi/v1/agents/agent-1", headers=bearer(limited))
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"


def test_validation_fields_and_unknown_resource_use_public_envelope(agent_api):
    client, _, issued, *_ = agent_api
    body = registration_body()
    del body["agent_id"]
    result = client.post("/openapi/v1/agents", headers=bearer(issued), json=body)
    assert result.json()["error"]["details"] == [{"field": "agent_id", "reason": "required"}]
    invalid_port = client.post("/openapi/v1/agents", headers=bearer(issued), json=registration_body(endpoint_url="http://10.1.1.1:invalid/v1"))
    assert invalid_port.status_code == 422
    result = client.get("/openapi/v1/not-found", headers=bearer(issued))
    assert result.status_code == 404 and result.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert result.json()["request_id"] == result.headers["x-request-id"]
    assert client.get("/api/v1/not-found").json() == {"detail": "Not Found"}


def test_authentication_storage_failure_uses_public_error(agent_api, monkeypatch, caplog):
    from backend import external_access
    def unavailable(_):
        raise RuntimeError("private database information")
    monkeypatch.setattr(external_access, "_start_request", unavailable)
    response = agent_api[0].get("/openapi/v1/agents/agent-1", headers={**bearer(agent_api[2]), "X-Request-ID": "trace-1"})
    assert response.status_code == 503
    assert response.json()["request_id"] == response.headers["x-request-id"] == "trace-1"
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE" and response.json()["error"]["retryable"]
    assert "private database information" not in response.text + caplog.text


@pytest.mark.parametrize("kind", ["connection", "evaluation"])
def test_task_limit_includes_retry_after(agent_api, kind):
    client, sessions, issued, *_ = agent_api
    register(agent_api)
    test_id = ready(agent_api) if kind == "evaluation" else None
    with sessions() as db:
        db.get(models.AccessToken, issued["record"]["id"]).max_concurrent_jobs = 1
        db.commit()
    def start():
        return evaluate(agent_api, test_id) if test_id else client.post(
            "/openapi/v1/agents/agent-1/connection-tests", headers=bearer(issued), json={"target_revision": 1})
    assert start().status_code == 202
    limited = start()
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.parametrize("native_code,expected", [
    ("CONNECTION_AUTH_FAILED", "TARGET_AUTH_FAILED"), ("CONNECTION_NETWORK_FAILED", "TARGET_UNREACHABLE"),
    ("CONNECTION_TLS_FAILED", "TARGET_UNREACHABLE"), ("CONNECTION_PROTOCOL_INVALID", "TARGET_PROTOCOL_INVALID"),
    ("CONNECTION_TIMED_OUT", "TASK_TIMEOUT"),
])
def test_connection_errors_are_public_codes(agent_api, native_code, expected):
    client, _, issued, *_ = agent_api
    register(agent_api)
    response = client.post("/openapi/v1/agents/agent-1/connection-tests", headers=bearer(issued), json={"target_revision": 1})
    test_id = response.json()["data"]["test_id"]
    complete(agent_api, claim(agent_api), status="failed", error_code=native_code)
    result = client.get("/openapi/v1/connection-tests/" + test_id, headers=bearer(issued)).json()["data"]
    assert result["error"]["code"] == expected and result["ready"] is False
    assert result["status"] == ("timed_out" if expected == "TASK_TIMEOUT" else "failed")


@pytest.mark.parametrize("status,expected", [("timed_out", "TASK_TIMEOUT"), ("blocked", "POLICY_BLOCKED")])
def test_evaluation_terminal_error_and_snapshot_envelopes_agree(agent_api, status, expected):
    client, sessions, issued, *_ = agent_api
    register(agent_api)
    task_id = evaluate(agent_api, ready(agent_api)).json()["data"]["task_id"]
    from backend.routers.security_scans import recover_stale_tasks
    with sessions() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        if status == "timed_out":
            task.timeout_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
            recover_stale_tasks(db)
        else:
            db.query(models.SecurityTarget).filter_by(target_id=task.target_id).one().status = "disabled"
            db.commit()
    if status == "blocked":
        blocked = client.post("/api/v1/agent-security/worker/claim", headers=agent_api[3], json={})
        assert blocked.status_code == 200 and blocked.json()["task"] is None
    progress = client.get("/openapi/v1/agent-evaluations/" + task_id, headers=bearer(issued)).json()["data"]
    report = client.get("/openapi/v1/agent-evaluations/" + task_id + "/result", headers=bearer(issued)).json()["data"]
    with sessions() as db:
        callback = json.loads(db.query(ExternalResultEvent).filter_by(task_id=task_id).one().payload_json)
        gateway = json.loads(db.get(ExternalGatewayEvent, task_id).payload_json)
    assert progress["error"]["code"] == callback["error"]["code"] == expected
    assert progress["status"] == callback["status"] == report["task_status"] == status
    assert set(callback["result"]) == {"report_id", "report_version", "risk_level", "risk_score", "coverage", "finding_counts"}
    assert all(callback["result"][key] == report[key] for key in callback["result"])
    assert gateway["report"] == report
    assert all(gateway[key] == report[key] for key in ("agent_id", "gateway_agent_id", "department_id", "target_revision", "evaluation_sequence"))


def test_real_skill_snapshot_is_delivered_unchanged_after_rescan(skill_api, monkeypatch):
    client, sessions, manager, queue, issued, config = skill_api
    client.app.include_router(external_deliveries.router, prefix="/api/v1")
    created = client.post("/api/v1/external-access/delivery-endpoints", json={"kind": "callback", "config_id": "result",
        "version": "1", "platform_ids": ["partner"], "url": "http://receiver.test/result", "bearer_token": "receiver-secret",
        "retry_delays_seconds": [1]})
    assert created.status_code == 201
    path = url(submit(skill_api))
    queue.finish()
    report = client.get(path + "/result", headers=bearer(issued)).json()["data"]
    findings = client.get(path + "/findings", headers=bearer(issued)).json()["data"]
    first = external_delivery.claim()
    assert first
    original = httpx.AsyncClient
    monkeypatch.setattr(external_delivery.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(503)), **kw))
    external_delivery.finish(first, asyncio.run(external_delivery.transmit(first)))
    with sessions() as db:
        task = db.get(ExternalSkillScan, report["task_id"])
        manager.request_rescan(task.version_id)
        manager.process_pending_submission(task.version_id, use_sandbox=False, force_scan=True)
        delivery = db.query(ExternalDelivery).one()
        delivery.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    configuration = json.loads(config.read_text())
    configuration["callbacks"]["result"]["version"] = "2"
    config.write_text(json.dumps(configuration))
    retried = external_delivery.claim()
    assert retried["payload"] == first["payload"] and retried["url"] == first["url"]
    callback = json.loads(retried["payload"])
    assert set(callback["result"]) == {"report_id", "report_version", "risk_level", "coverage", "finding_counts"}
    assert all(callback["result"][key] == report[key] for key in callback["result"])
    assert client.get(path + "/result", headers=bearer(issued)).json()["data"] == report
    assert client.get(path + "/findings", headers=bearer(issued)).json()["data"] == findings
