import importlib
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import auth, models
from backend.api_errors import http_error_handler
from backend.config import settings
from backend.external_access import OPENAPI_SCOPES
from backend.external_access_models import ExternalAgentRegistration, ExternalAgentJob, ExternalGatewayEvent, ExternalResultEvent
from backend.routers import openapi_agents, security_scans
from backend.security_scan_controls import unprotect_secret
from backend.services import openapi_agents as service
from tests.test_external_access import setup, partner, token, bearer


@pytest.fixture
def api(setup, tmp_path, monkeypatch):
    client, sessions = setup
    monkeypatch.setattr(settings, "AUDIT_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "audit.pem"))
    monkeypatch.setattr(settings, "SECURITY_AUDIT_EXPORT_PATH", None)
    client.app.add_exception_handler(HTTPException, http_error_handler)
    client.app.include_router(openapi_agents.router)
    client.app.include_router(security_scans.router, prefix="/api")
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: models.User(id=1, username="admin", role="super_admin")
    with sessions() as db:
        provider = models.ModelProvider(name="Judge", base_url="http://10.1.1.2/v1")
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(name="judge", provider_id=provider.id))
        db.add(models.SecurityScanPolicy(policy_id="policy", name="Policy", created_by="admin", execution_mode="active_safe",
                                         outbound_allowlist_json='["10.0.0.0/8"]'))
        db.commit()
    config = {"partners": {"partner": {"allowed_cidrs": ["10.0.0.0/8"], "connection_policy_ids": {"test": "policy"}}},
              "profiles": {"standard": {"version": "1", "platform_ids": ["partner"], "policy_id": "policy", "evaluation_model": "judge",
                                         "skills": ["data-leakage-detection"], "malicious_rule_ids": ["confirmed-exfiltration"]}},
              "callbacks": {"callback": {"version": "1", "platform_ids": ["partner"]}},
              "gateways": {"gateway": {"version": "1", "platform_ids": ["partner"]}}}
    path = tmp_path / "openapi-agents.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("OPENAPI_AGENT_CONFIG", str(path))
    partner(client)
    issued = token(client, scopes=OPENAPI_SCOPES, max_concurrent_jobs=10)
    monkeypatch.syspath_prepend(str(Path("services/agent-security-worker").resolve()))
    envelope = importlib.import_module("credential_envelope")
    key = envelope.generate_worker_key_pair()
    response = client.post("/api/v1/agent-security/workers", json={"name": "Test", "capabilities": ["control_plane_validation", "agent_risk_scan"]})
    assert response.status_code == 200, response.text
    worker = response.json()
    worker_headers = {"Authorization": "Bearer " + worker["token_once"]}
    response = client.post("/api/v1/agent-security/worker/key", headers=worker_headers,
                           json={"algorithm": envelope.ALGORITHM, "public_key": key.public_key})
    assert response.status_code == 200, response.text
    yield client, sessions, issued, worker_headers, key, path


def registration_body(**kwargs):
    return {"agent_id": "agent-1", "name": "Agent", "department_id": "ops", "department_name": "Operations",
            "owner": "Team", "environment": "test", "endpoint_url": "http://10.1.1.1/v1",
            "protocol": "openai_chat_completions", "model": "target-model", "api_key": "test-target-secret", "gateway_agent_id": "gateway-agent", **kwargs}


def register(api, **kwargs):
    client, _, issued, *_ = api
    response = client.post("/openapi/v1/agents", headers=bearer(issued), json=registration_body(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def claim(api):
    client, _, _, headers, *_ = api
    response = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={})
    assert response.status_code == 200, response.text
    assert response.json()["task"] is not None
    return response.json()


def complete(api, claimed, *, cases=None, findings=None, status="succeeded", **kwargs):
    client, _, _, headers, *_ = api
    artifacts = []
    if claimed["task"]["scan_kind"] == "agent_risk_scan":
        raw = json.dumps({"cases": cases or [], "findings": findings or []})
        artifacts = [{"artifact_type": "aig-agent-scan-report", "uri": "artifact://report.json", "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                      "size_bytes": len(raw.encode()), "content": raw}]
        kwargs.update(engine_name="tencent-ai-infra-guard-agent-scan", engine_version="v4.6.0")
    response = client.post(f"/api/v1/agent-security/worker/tasks/{claimed['task']['task_id']}/complete", headers=headers,
        json={"lease_token": claimed["lease_token"], "status": status, "usage": {},
              "cases": cases or [], "findings": findings or [], "artifacts": artifacts, **kwargs})
    assert response.status_code == 200, response.text


def ready(api):
    client, _, issued, *_ = api
    response = client.post("/openapi/v1/agents/agent-1/connection-tests", headers=bearer(issued), json={"target_revision": 1})
    assert response.status_code == 202, response.text
    test_id = response.json()["data"]["test_id"]
    claimed = claim(api)
    assert claimed["target"]["openapi_connection_test"]
    complete(api, claimed, cases=[{"external_case_id": "openapi-connection", "category": "connection", "title": "Probe",
        "status": "passed", "response_summary": {"checks": {"network": "passed", "tls": "skipped", "authentication": "passed", "protocol": "passed"}}}])
    result = client.get("/openapi/v1/connection-tests/" + test_id, headers=bearer(issued))
    assert result.json()["data"]["ready"], result.text
    return test_id


def evaluate(api, test_id, **kwargs):
    client, _, issued, *_ = api
    return client.post("/openapi/v1/agent-evaluations", headers=bearer(issued), json={
        "agent_id": "agent-1", "business_request_id": "business-1", "target_revision": 1, "connection_test_id": test_id,
        "profile_id": "standard", "callback_id": "callback", "gateway_id": "gateway", **kwargs})


@pytest.mark.parametrize("change", [None, "disabled_token", "expired_token", "scope", "department", "platform", "mapping", "group", "job", "source"])
def test_external_evaluator_uses_partner_authorization(api, monkeypatch, change):
    from backend.routers import llm_gateway
    client, sessions, issued, *_ = api
    register(api)
    response = evaluate(api, ready(api))
    assert response.status_code == 202, response.text
    task_id = response.json()["data"]["task_id"]
    claimed = claim(api)
    # Updating registration must not invalidate an accepted task's frozen target.
    update = registration_body(endpoint_url="http://10.1.1.3/v1")
    update.pop("agent_id")
    assert client.put("/openapi/v1/agents/agent-1", headers=bearer(issued), json=update).status_code == 200
    with sessions() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        assert task.owner_user_id is None and task.owner_group_id == 1
        credential = db.get(models.AccessToken, issued["record"]["id"])
        platform = db.get(models.ExternalPlatform, "partner")
        if change == "disabled_token": credential.status = "disabled"
        elif change == "expired_token": credential.expires_at = datetime.utcnow() - timedelta(seconds=1)
        elif change == "scope": credential.scopes_json = '["openapi:evaluation-read"]'
        elif change == "department": credential.allowed_department_ids_json = '[]'
        elif change == "platform": platform.enabled = False
        elif change == "mapping": platform.departments_json = '[{"department_id":"ops","group_id":2}]'
        elif change == "group": db.get(models.UserGroup, 1).is_active = False
        elif change == "job": db.delete(db.get(ExternalAgentJob, task_id))
        elif change == "source": task.source_platform_id = "other"
        db.commit()
    calls = []
    async def gateway(body, response, key, db, request=None):
        calls.append(body.model)
        assert key.user_id is None and key.group_id == 1
        assert json.loads(key.allowed_models_json) == ["judge"]
        assert body.metadata["scan_task_id"] == task_id
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    monkeypatch.setattr(llm_gateway, "_chat_completions_with_key", gateway)
    url = f"/api/v1/agent-security/worker/tasks/{task_id}/evaluator/v1/chat/completions"
    body = {"model": "judge", "messages": [{"role": "user", "content": "evaluate"}]}
    assert client.post(url, headers={"Authorization": "Bearer invalid"}, json=body).status_code == 401
    headers = {"Authorization": "Bearer " + claimed["lease_token"]}
    assert client.post(url, headers=headers, json={**body, "model": "other"}).status_code == 403
    result = client.post(url, headers=headers, json=body)
    assert result.status_code == (403 if change else 200), result.text
    assert len(calls) == (0 if change else 1)
    if change:
        assert result.json()["error_code"] == "agent_security.evaluation_not_authorized"


def test_registration_update_keeps_accepted_target_and_credentials(api):
    client, sessions, issued, _, key, _ = api
    record = register(api)
    assert record["target_revision"] == 1 and record["connection_status"] == "not_tested"
    assert record["description"] == "" and "api_key" not in record
    test_id = ready(api)
    response = evaluate(api, test_id)
    assert response.status_code == 202, response.text
    task_id = response.json()["data"]["task_id"]
    body = registration_body(endpoint_url="http://10.1.1.3/v1", api_key="test-new-secret")
    body.pop("agent_id")
    response = client.put("/openapi/v1/agents/agent-1", headers=bearer(issued), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["target_revision"] == 2
    assert response.json()["data"]["connection_status"] == "not_tested"
    claimed = claim(api)
    assert claimed["task"]["task_id"] == task_id
    assert claimed["target"]["endpoint_url"] == "http://10.1.1.1/v1"
    envelope = importlib.import_module("credential_envelope")
    assert envelope.decrypt_secret_envelope(claimed["credential"]["secret_envelope"], key,
        worker_id=claimed["task"]["worker_id"], task_id=task_id,
        credential_id=claimed["credential"]["credential_id"]) == "test-target-secret"
    assert not client.get("/openapi/v1/connection-tests/" + test_id, headers=bearer(issued)).json()["data"]["ready"]
    assert evaluate(api, test_id).status_code == 409
    with sessions() as db:
        agent = db.query(models.ManagedAgent).filter_by(external_agent_id="agent-1").one()
        assert agent.registration_source == "external_api" and agent.source_platform_id == "partner"
        job = db.get(ExternalAgentJob, task_id)
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        assert job.target_revision == 1 and task.business_request_id == "business-1"
        assert task.source_token_id == issued["record"]["id"] and task.trigger_source == "external_api"
        assert "test-target-secret" not in json.dumps(json.loads(job.registration_json))
        credential = db.query(models.SecurityTargetCredential).filter_by(credential_id=job.credential_id).one()
        assert credential.secret_encrypted != "test-target-secret"
        assert unprotect_secret(credential.secret_encrypted) == "test-target-secret"


@pytest.mark.parametrize("finding_code,severity,evidence,expected", [
    (None, None, None, "benign"), ("agent_goal_hijack", "critical", {"conversation": ["Observed behavior"]}, "suspicious"),
    ("confirmed-exfiltration", "low", {"conversation": ["Observed exfiltration"]}, "malicious"),
    ("confirmed-exfiltration", "high", {"suggestion": "Investigate"}, "suspicious"),
])
def test_full_evaluation_freezes_reports_and_delivery_payloads(api, finding_code, severity, evidence, expected):
    client, sessions, issued, *_ = api
    register(api)
    test_id = ready(api)
    response = evaluate(api, test_id)
    assert response.status_code == 202, response.text
    assert response.json()["data"]["evaluation_sequence"] == 1
    task_id = response.json()["data"]["task_id"]
    root = "/openapi/v1/agent-evaluations/" + task_id
    assert client.get(root + "/result", headers=bearer(issued)).status_code == 409
    claimed = claim(api)
    findings = [{"case_external_id": "aig-rule:data-leakage-detection", "finding_code": finding_code,
        "severity": severity, "title": "Risk", "description": "Description", "source": "ai_infra_guard", "evidence": evidence}] if finding_code else []
    complete(api, claimed, cases=[{"external_case_id": "aig-rule:data-leakage-detection", "category": "agent_detection_skill",
        "title": "Check", "status": "failed" if findings else "passed", "round_count": 1,
        "response_summary": {"execution_status": "completed", "dialogue_calls": 1}}], findings=findings)
    with sessions() as db:
        # Completion itself publishes snapshots, before the first external read.
        job = db.get(ExternalAgentJob, task_id)
        assert job.report_json
        callback = db.query(ExternalResultEvent).filter_by(task_id=task_id).one()
        gateway = db.get(ExternalGatewayEvent, task_id)
        report = json.loads(job.report_json)
        assert report["risk_level"] == expected and report["coverage"] == "complete"
        assert report["risk_score"]["score"] == (0 if not findings else {"low": 10, "high": 65, "critical": 90}[severity])
        assert json.loads(callback.payload_json)["result"]["risk_level"] == expected
        assert json.loads(gateway.payload_json)["report"] == report
        assert json.loads(gateway.payload_json)["findings"] == json.loads(job.findings_json)
        for finding in db.query(models.SecurityFinding).filter_by(task_id=task_id):
            finding.status, finding.severity = "resolved", "info"
        db.commit()
    assert client.get(root + "/result", headers=bearer(issued)).json()["data"] == report
    assert client.get(root + "/cases", headers=bearer(issued)).json()["data"]["items"][0]["status"] == ("failed" if findings else "passed")
    progress = client.get(root, headers=bearer(issued)).json()["data"]
    assert progress["result_ready"] and progress["callback"]["status"] == progress["gateway_sync"]["status"] == "pending"
    assert progress["progress"]["completed"] == 1
    log = client.get("/api/v1/external-access/requests/" + response.headers["x-request-id"]).json()
    assert log["resource_id"] == task_id and log["business_request_id"] == "business-1"
    replacement = token(client, scopes=OPENAPI_SCOPES)
    assert client.get(root + "/result", headers=bearer(replacement)).json()["data"] == report


def test_authorization_revisions_expiry_and_failed_connection(api):
    client, sessions, issued, *_ = api
    register(api)
    assert client.post("/openapi/v1/agents", headers=bearer(issued), json=registration_body()).status_code == 409
    reader = token(client, scopes=["openapi:agent-read"])
    assert client.post("/openapi/v1/agents", headers=bearer(reader), json=registration_body(agent_id="denied")).status_code == 403
    partner(client, "second", 2)
    other = token(client, platform_id="second", scopes=OPENAPI_SCOPES)
    assert client.get("/openapi/v1/agents/agent-1", headers=bearer(other)).status_code == 404
    conflict = client.post("/openapi/v1/agents/agent-1/connection-tests", headers=bearer(issued), json={"target_revision": 99})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "TARGET_REVISION_CONFLICT"
    response = client.post("/openapi/v1/agents/agent-1/connection-tests", headers=bearer(issued), json={"target_revision": 1})
    test_id = response.json()["data"]["test_id"]
    complete(api, claim(api))  # A successful control-plane task is not a successful connection probe.
    assert not client.get("/openapi/v1/connection-tests/" + test_id, headers=bearer(issued)).json()["data"]["ready"]
    assert evaluate(api, test_id).json()["error"]["code"] == "CONNECTION_TEST_REQUIRED"
    test_id = ready(api)
    with sessions() as db:
        db.get(ExternalAgentJob, test_id).expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert evaluate(api, test_id).status_code == 409
    assert client.get("/openapi/v1/agents/agent-1", headers=bearer(issued)).json()["data"]["connection_status"] == "expired"


def test_registration_atomic_failure_and_key_omission(api, monkeypatch):
    client, sessions, issued, *_ = api
    def fail(_):
        raise RuntimeError("simulated encryption failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "protect_secret", fail)
        assert client.post("/openapi/v1/agents", headers=bearer(issued), json=registration_body()).status_code == 503
    with sessions() as db:
        assert db.query(ExternalAgentRegistration).count() == db.query(models.ManagedAgent).count() == db.query(models.SecurityTarget).count() == 0
    register(api)
    body = registration_body()
    body.pop("agent_id")
    body.pop("api_key")
    response = client.put("/openapi/v1/agents/agent-1", headers=bearer(issued), json=body)
    assert response.status_code == 200, response.text
    with sessions() as db:
        row = db.query(ExternalAgentRegistration).one()
        credential = db.query(models.SecurityTargetCredential).filter_by(credential_id=row.credential_id).one()
        assert unprotect_secret(credential.secret_encrypted) == "test-target-secret"
    for value in (None, "", "has space"):
        assert client.put("/openapi/v1/agents/agent-1", headers=bearer(issued), json={**body, "api_key": value}).status_code == 422


def test_partial_report_has_no_benign_verdict(api):
    client, _, issued, *_ = api
    register(api)
    response = evaluate(api, ready(api))
    assert response.status_code == 202, response.text
    task_id = response.json()["data"]["task_id"]
    complete(api, claim(api), status="failed", error_code="execution_failed")
    report = client.get(f"/openapi/v1/agent-evaluations/{task_id}/result", headers=bearer(issued)).json()["data"]
    assert report["risk_level"] is None and report["coverage"] == "none" and report["risk_score"]["score"] is None


def test_worker_connection_probe_uses_sealed_credential_and_records_real_response(api, monkeypatch):
    import httpx
    client, _, issued, worker_headers, key, _ = api
    register(api)
    response = client.post("/openapi/v1/agents/agent-1/connection-tests", headers=bearer(issued), json={"target_revision": 1})
    test_id = response.json()["data"]["test_id"]
    claimed = claim(api)
    worker = importlib.import_module("worker")
    probe_module = importlib.import_module("connection_probe")
    original_client = httpx.Client
    def transport(request):
        assert str(request.url) == "http://10.1.1.1/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-target-secret"
        assert json.loads(request.content)["model"] == "target-model"
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    def control(path, payload):
        result = client.post("/api/v1/agent-security" + path, headers=worker_headers, json=payload)
        assert result.status_code == 200, result.text
        return result.json()
    monkeypatch.setattr(worker, "_request", control)
    monkeypatch.setattr(probe_module.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(transport), **kw))
    worker._run_connection_test(claimed, key, claimed["task"]["worker_id"])
    result = client.get("/openapi/v1/connection-tests/" + test_id, headers=bearer(issued)).json()["data"]
    assert result["ready"] and result["checks"] == {"network": "passed", "tls": "skipped", "authentication": "passed", "protocol": "passed"}


def test_profile_department_and_target_network_boundaries(api):
    client, sessions, issued, *_ = api
    denied = client.post("/openapi/v1/agents", headers=bearer(issued), json=registration_body(endpoint_url="http://192.168.1.1/v1"))
    assert denied.status_code == 422, denied.text
    register(api)
    test_id = ready(api)
    assert evaluate(api, test_id, profile_id="unknown").status_code == 404
    with sessions() as db:
        platform = db.get(models.ExternalPlatform, "partner")
        platform.departments_json = '[{"department_id":"ops","group_id":2}]'
        db.commit()
    assert client.get("/openapi/v1/agents/agent-1", headers=bearer(issued)).status_code == 403
    assert evaluate(api, test_id).status_code == 403


def test_evaluation_sequence_and_failed_creation_are_atomic(api, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    client, sessions, _, *_ = api
    register(api)
    test_id = ready(api)
    from backend.services import agent_risk
    with monkeypatch.context() as patch:
        patch.setattr(agent_risk, "bind_scan", lambda *args: (_ for _ in ()).throw(RuntimeError("simulated failure")))
        assert evaluate(api, test_id).status_code == 503
    with sessions() as db:
        assert db.query(ExternalAgentRegistration).one().evaluation_sequence == 0
        assert db.query(ExternalAgentJob).filter_by(kind="evaluation").count() == 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda n: evaluate(api, test_id, business_request_id=f"request-{n}"), range(2)))
    assert all(result.status_code == 202 for result in results), [r.text for r in results]
    assert sorted(r.json()["data"]["evaluation_sequence"] for r in results) == [1, 2]


def test_evaluation_isolation_and_snapshot_pagination(api):
    client, sessions, issued, *_ = api
    register(api)
    test_id = ready(api)
    task_id = evaluate(api, test_id).json()["data"]["task_id"]
    root = "/openapi/v1/agent-evaluations/" + task_id
    complete(api, claim(api), cases=[{"external_case_id": f"case-{n}", "category": "test", "title": f"Case {n}",
                                    "status": "unverified"} for n in range(3)])
    first = client.get(root + "/cases?limit=1", headers=bearer(issued)).json()["data"]
    second = client.get(root + "/cases", params={"limit": 2, "cursor": first["next_cursor"]}, headers=bearer(issued)).json()["data"]
    assert len(first["items"]) == 1 and len(second["items"]) == 2 and second["next_cursor"] is None
    assert len({item["case_id"] for item in first["items"] + second["items"]}) == 3
    assert client.get(root + "/findings", params={"cursor": first["next_cursor"]}, headers=bearer(issued)).status_code == 422
    next_id = evaluate(api, test_id).json()["data"]["task_id"]
    complete(api, claim(api), cases=[{"external_case_id": "case-other", "category": "test", "title": "Other", "status": "unverified"}])
    assert client.get(f"/openapi/v1/agent-evaluations/{next_id}/cases", params={"cursor": first["next_cursor"]}, headers=bearer(issued)).status_code == 422
    partner(client, "other", 2)
    other = token(client, platform_id="other", scopes=OPENAPI_SCOPES)
    reader = token(client, scopes=["openapi:agent-read"])
    for suffix in ("", "/result", "/cases", "/findings"):
        assert client.get(root + suffix, headers=bearer(other)).status_code == 404
        assert client.get(root + suffix, headers=bearer(reader)).status_code == 403
    with sessions() as db:
        db.get(models.ExternalPlatform, "partner").departments_json = '[{"department_id":"ops","group_id":2}]'
        db.commit()
    for suffix in ("", "/result", "/cases", "/findings"):
        assert client.get(root + suffix, headers=bearer(issued)).status_code == 403


def test_terminal_report_and_events_rollback_and_recover(api):
    from sqlalchemy import event
    client, sessions, issued, *_ = api
    register(api)
    task_id = evaluate(api, ready(api)).json()["data"]["task_id"]
    # Simulate a terminal task persisted by a timeout/cancellation path, then restart reconciliation.
    with sessions() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        task.status, task.completed_at = "cancelled", datetime.utcnow()
        db.commit()
    def fail_publication(*args):
        raise RuntimeError("simulated event storage failure")
    event.listen(ExternalGatewayEvent, "before_insert", fail_publication)
    try:
        with pytest.raises(RuntimeError):
            service.reconcile()
    finally:
        event.remove(ExternalGatewayEvent, "before_insert", fail_publication)
    with sessions() as db:
        assert db.get(ExternalAgentJob, task_id).report_json is None
        assert db.get(ExternalAgentJob, task_id).status == "pending"
        assert db.query(ExternalResultEvent).filter_by(task_id=task_id).count() == 0
    service.reconcile()
    service.reconcile()
    report = client.get(f"/openapi/v1/agent-evaluations/{task_id}/result", headers=bearer(issued)).json()["data"]
    assert report["task_status"] == "cancelled" and report["risk_level"] is None
    with sessions() as db:
        assert db.query(ExternalResultEvent).filter_by(task_id=task_id).count() == 1
        assert db.query(ExternalGatewayEvent).filter_by(task_id=task_id).count() == 1


def test_connection_policy_and_revoked_pinned_credential(api):
    client, sessions, issued, *_ = api
    register(api)
    with sessions() as db:
        db.query(models.SecurityScanPolicy).filter_by(policy_id="policy").one().execution_mode = "passive"
        db.commit()
    path = "/openapi/v1/agents/agent-1/connection-tests"
    assert client.post(path, headers=bearer(issued), json={"target_revision": 1}).status_code == 403
    with sessions() as db:
        db.query(models.SecurityScanPolicy).filter_by(policy_id="policy").one().execution_mode = "active_safe"
        db.commit()
    task_id = evaluate(api, ready(api)).json()["data"]["task_id"]
    with sessions() as db:
        job = db.get(ExternalAgentJob, task_id)
        db.query(models.SecurityTargetCredential).filter_by(credential_id=job.credential_id).one().status = "revoked"
        db.commit()
    response = client.post("/api/v1/agent-security/worker/claim", headers=api[3], json={})
    assert response.status_code == 200 and response.json()["task"] is None
    result = client.get(f"/openapi/v1/agent-evaluations/{task_id}", headers=bearer(issued)).json()["data"]
    assert result["status"] == "blocked" and result["result_ready"]
    assert result["error"]["code"] == "POLICY_BLOCKED"


def test_production_connection_and_evaluation_use_separate_native_approvals(api):
    client, sessions, issued, _, _, config_path = api
    register(api, environment="production")
    with sessions() as db:
        registration = db.query(ExternalAgentRegistration).one()
        target_id = registration.target_id
        policy = db.query(models.SecurityScanPolicy).filter_by(policy_id="policy").one()
        policy.environment = "production"
        policy.production_target_ids_json = json.dumps([target_id])
        policy.maintenance_window_start = datetime.utcnow() - timedelta(minutes=5)
        policy.maintenance_window_end = datetime.utcnow() + timedelta(hours=1)
        policy.dedicated_identity_ref = "production-test-identity"
        db.commit()
    config = json.loads(config_path.read_text())
    config["partners"]["partner"]["connection_policy_ids"] = {"production": "policy"}
    config_path.write_text(json.dumps(config))
    path = "/openapi/v1/agents/agent-1/connection-tests"
    denied = client.post(path, headers=bearer(issued), json={"target_revision": 1})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
    def approve():
        response = client.post("/api/v1/agent-security/scan-approvals", json={"target_id": target_id, "policy_id": "policy"})
        assert response.status_code == 200, response.text
        return response.json()["approval_id"]
    connection_approval = approve()
    config["partners"]["partner"]["connection_approval_ids"] = {"agent-1": connection_approval}
    config_path.write_text(json.dumps(config))
    test_id = ready(api)
    assert client.post(path, headers=bearer(issued), json={"target_revision": 1}).status_code == 403
    assert evaluate(api, test_id).status_code == 403
    evaluation_approval = approve()
    config["profiles"]["standard"]["approval_id"] = evaluation_approval
    config_path.write_text(json.dumps(config))
    response = evaluate(api, test_id)
    assert response.status_code == 202, response.text
    with sessions() as db:
        approvals = db.query(models.SecurityScanApproval).filter(models.SecurityScanApproval.approval_id.in_(
            [connection_approval, evaluation_approval])).all()
        assert len(approvals) == 2 and all(row.status == "used" for row in approvals)
        assert {row.used_task_id for row in approvals} == {test_id, response.json()["data"]["task_id"]}
