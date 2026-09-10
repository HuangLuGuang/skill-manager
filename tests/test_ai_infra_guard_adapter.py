from __future__ import annotations

import hashlib
import importlib
import json
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from backend.config import settings
from backend.routers import security_scans
from backend.security_scan_controls import SUPPORTED_AGENT_PROVIDER_TYPES, sanitize_untrusted_value, unprotect_secret
from backend.sqlite_db import Base, get_db

WORKER_DIR = Path("services/agent-security-worker").resolve()
VENDOR_DIR = WORKER_DIR / "vendor/ai-infra-guard/agent-scan"
for path in (str(WORKER_DIR), str(VENDOR_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

aig_adapter = importlib.import_module("aig_adapter")
credential_envelope = importlib.import_module("credential_envelope")


@pytest.fixture()
def p2_api(tmp_path, monkeypatch):
    database_path = tmp_path / "p2.db"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "AUDIT_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "audit.pem"))
    monkeypatch.setattr(settings, "SECURITY_AUDIT_EXPORT_PATH", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "p2-test-secret-key")
    with session_factory() as db:
        admin = models.User(username="admin", hashed_password="x", role="admin")
        auditor = models.User(username="auditor", hashed_password="x", role="security_auditor")
        owner = models.User(username="owner", hashed_password="x", role="user")
        provider = models.ModelProvider(name="test-evaluator", base_url="https://example.test/v1", api_key="test")
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(provider_id=provider.id, name="test-judge"))
        db.add_all([admin, auditor, owner])
        db.commit()
        for row in (admin, auditor, owner):
            db.refresh(row)
    users = {"admin": admin, "auditor": auditor, "owner": owner}
    state = {"user": admin}

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def current_user():
        return state["user"]

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[auth.get_current_active_user] = current_user
    app.include_router(security_scans.router, prefix="/api")
    client = TestClient(app)
    yield client, session_factory, state, users
    client.close()
    engine.dispose()


def _target(client: TestClient, **overrides) -> dict:
    payload = {
        "name": f"target-{time.time_ns()}",
        "target_type": "openai",
        "endpoint_url": "https://8.8.8.8/v1",
        "config": {"model": "mock-model"},
    }
    payload.update(overrides)
    response = client.post("/api/v1/agent-security/targets", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _policy(client: TestClient, **overrides) -> dict:
    payload = {"name": f"policy-{time.time_ns()}"}
    payload.update(overrides)
    response = client.post("/api/v1/agent-security/policies", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _agent_task(client: TestClient, target_id: str, policy_id: str, **overrides) -> dict:
    payload = {
        "target_id": target_id,
        "policy_id": policy_id,
        "idempotency_key": f"p2-{time.time_ns()}",
        "scan_kind": "agent_risk_scan", "evaluation_model": "test-judge",
        "conversation_mode": "multi_turn",
        "reset_session": True,
    }
    payload.update(overrides)
    response = client.post("/api/v1/agent-security/tasks", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _worker(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/agent-security/workers",
        json={"name": f"p2-worker-{time.time_ns()}", "capabilities": ["agent_risk_scan"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_p6_agent_preview_lists_fixed_skills_but_marks_runtime_details_dynamic(p2_api):
    client, session_factory, _state, _users = p2_api
    target = _target(client)
    policy = _policy(client, execution_mode="active_safe", max_rounds=23, max_tokens=45678)
    preview = client.post(
        "/api/v1/agent-security/tasks/preview",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "scan_kind": "agent_risk_scan", "evaluation_model": "test-judge",
            "conversation_mode": "multi_turn",
            "prompt": "check-private-object-123456789",
        },
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["scan_kind"] == "agent_risk_scan"
    assert len(payload["cases"]) == 12
    assert payload["cases"][0]["case_key"] == "agent_info_collection"
    assert payload["cases"][-1]["case_key"] == "agent_vulnerability_review"
    assert all(item["dynamic"] is True and item["planned_rounds"] is None for item in payload["cases"])
    assert payload["tool_plan"] == {
        "mode": "runtime_dynamic",
        "dynamic": True,
        "tools": [
            {
                "name": "dialogue",
                "source": "ai_infra_guard_agent_scan",
                "access_mode": "target_interaction",
                "will_call": True,
            }
        ],
    }
    assert payload["budget"]["max_rounds"] == 23
    assert payload["budget"]["max_tokens"] == 45678
    assert {"runtime_generated_cases", "runtime_tool_inventory_unknown"} <= set(payload["limitations"])
    assert "check-private-object-123456789" not in preview.text
    with session_factory() as db:
        assert db.query(models.SecurityScanTask).count() == 0


def _register_and_claim(client: TestClient, worker: dict, key_pair, task_id: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    registered = client.post(
        "/api/v1/agent-security/worker/key",
        headers=headers,
        json={"algorithm": credential_envelope.ALGORITHM, "public_key": key_pair.public_key},
    )
    assert registered.status_code == 200, registered.text
    claimed = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["agent_risk_scan"]},
    )
    assert claimed.status_code == 200, claimed.text
    payload = claimed.json()
    assert payload["task"]
    if task_id:
        assert payload["task"]["task_id"] == task_id
    return payload


def _complete(client: TestClient, worker: dict, claim: dict, *, code: str, session: str | None = None) -> dict:
    raw = json.dumps({"schema_version": "agent-security-report@1", "code": code}, sort_keys=True)
    payload = {
        "lease_token": claim["lease_token"],
        "status": "succeeded",
        "usage": {
            "rounds": 2,
            "tokens": 20,
            "cost_microunits": 0,
            "concurrent_requests": 1,
            "response_bytes": len(raw),
        },
        "cases": [
            {
                "external_case_id": code,
                "category": "ASI01",
                "title": f"<b>{code}</b>",
                "status": "failed",
                "request_summary": {"prompt": "Authorization: Bearer sk-secret-123456789"},
                "response_summary": {"response": "<script>alert(1)</script>"},
                "round_count": 2,
            }
        ],
        "findings": [
            {
                "case_external_id": code,
                "finding_code": code,
                "severity": "high",
                "title": f"<img src=x onerror=alert(1)>{code}",
                "description": "token=top-secret-value",
                "evidence": {"html": "<script>alert(1)</script>"},
                "source": "ai_infra_guard",
                "confidence": 0.9,
            }
        ],
        "artifacts": [
            {
                "artifact_type": "aig-agent-scan-report",
                "uri": f"artifact://{claim['task']['task_id']}/report.json",
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "size_bytes": len(raw.encode()),
                "redacted": False,
                "metadata": {"engine_tag": "v4.6.0"},
                "content": raw,
            }
        ],
        "session_state": session,
        "engine_name": aig_adapter.AIG_ENGINE_NAME,
        "engine_version": aig_adapter.AIG_TAG,
    }
    response = client.post(
        f"/api/v1/agent-security/worker/tasks/{claim['task']['task_id']}/complete",
        headers={"Authorization": f"Bearer {worker['token_once']}"},
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_vendored_upstream_hashes_and_provider_catalog_are_locked():
    expected = {
        "agent_scan/core/agent_adapter/providers.yaml": "6b4b9a4bd1f7107f47059bac748a94e98600c7d69411f74ce35823a1430aeace",
        "agent_scan/core/agent_adapter/adapter.py": "5c57fd31f08515bac290c3f958df4289a2017d5a90b17cdf283b22dee2f79dca",
        "requirements.txt": "a2ad10f92a5ad0180fecd5f17ea5ef2d90335426e1a323b4035380fec359606e",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((VENDOR_DIR / relative).read_bytes()).hexdigest() == digest
    assert tuple(SUPPORTED_AGENT_PROVIDER_TYPES) == aig_adapter.SUPPORTED_PROVIDER_TYPES
    assert len(SUPPORTED_AGENT_PROVIDER_TYPES) == 21
    assert (WORKER_DIR / "vendor/ai-infra-guard/LICENSE").exists()
    assert (WORKER_DIR / "vendor/ai-infra-guard/NOTICE").exists()


def test_upstream_logs_do_not_emit_prompt_or_model_response_content():
    prompt_log = aig_adapter._safe_upstream_log_text("Custom prompt: customer account 6222000000000000")
    response_log = aig_adapter._safe_upstream_log_text("LLM Response: private model output")
    ordinary_log = aig_adapter._safe_upstream_log_text("retrying provider after timeout")

    assert prompt_log == "[upstream message content redacted]"
    assert "6222000000000000" not in prompt_log
    assert response_log == "[upstream message content redacted]"
    assert "private model output" not in response_log
    assert "retrying provider after timeout" in ordinary_log


def test_report_projection_redacts_common_pii_types():
    redacted = aig_adapter._redact(
        "alice@example.com 13800138000 11010519491231002X 6222 0202 0004 1234 567 "
        "github_pat_1234567890abcdefghij AKIA1234567890ABCDEF "
        "eyJabcde.eyJfghij.signature"
    )
    keyed = aig_adapter._redact(
        {"credentials": {"default": "s3cr3t-material"}, "secretKey": "another-secret-material"}
    )

    assert "alice@example.com" not in redacted
    assert "13800138000" not in redacted
    assert "11010519491231002X" not in redacted
    assert "6222 0202 0004 1234 567" not in redacted
    assert "github_pat_1234567890abcdefghij" not in redacted
    assert "AKIA1234567890ABCDEF" not in redacted
    assert "eyJabcde.eyJfghij.signature" not in redacted
    assert "s3cr3t-material" not in keyed
    assert "another-secret-material" not in keyed
    assert "[REDACTED]" in redacted
    assert "[REDACTED]" in keyed


@pytest.mark.parametrize("provider_type", aig_adapter.SUPPORTED_PROVIDER_TYPES)
def test_each_locked_provider_routes_through_the_adapter(provider_type):
    config = {"model": "mock-model", "extra": {"bot_id": "bot-1"}}
    if provider_type == "http":
        config.update({"body": {"message": "{{prompt}}"}, "transform_response": "reply"})
    if provider_type == "websocket":
        config.update({"body": {"message": "{{prompt}}"}, "transform_response": "reply"})
    target = {
        "target_id": "ast-provider",
        "target_type": provider_type,
        "endpoint_url": "wss://example.com/ws" if provider_type == "websocket" else "https://example.com/v1",
        "config": config,
    }
    document = aig_adapter.build_provider_document(
        target,
        "bearer",
        "test-credential",
        max_response_bytes=4096,
    )
    from agent_scan.core.agent_adapter.adapter import (
        ProviderConfig,
        ProviderOptions,
        ProviderResponseInfo,
        ProviderTestResult,
    )

    entry = document["targets"][0]
    provider = ProviderOptions(id=entry["id"], config=ProviderConfig(**entry["config"]))
    client = aig_adapter._bounded_client_class(4096)()
    called = []

    def fake_http(url, method, headers, body, transform_response=None):
        called.append((url, method, transform_response))
        return ProviderTestResult(
            success=True,
            message="ok",
            provider_response=ProviderResponseInfo(raw={"reply": "ok"}, output="ok"),
        )

    client._make_http_request = fake_http
    client._call_websocket_provider = lambda _provider, _prompt: fake_http("wss://example.com/ws", "WS", {}, None)
    result = client.call_provider(provider, "hello")
    assert result.success is True
    assert called


def test_target_config_and_policy_fail_closed_for_agent_scan(p2_api):
    client, _, _, _ = p2_api
    unsupported = client.post(
        "/api/v1/agent-security/targets",
        json={"name": "bad", "target_type": "unknown", "endpoint_url": "https://8.8.8.8"},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error_code"] == "agent_security.target_type_unsupported"
    secret_header = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "secret-header",
            "target_type": "http",
            "endpoint_url": "https://8.8.8.8",
            "config": {"headers": {"Authorization": "Bearer bad"}},
        },
    )
    assert secret_header.status_code == 422
    assert secret_header.json()["error_code"] == "agent_security.secret_header_forbidden"
    nested_secret = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "nested-secret",
            "target_type": "http",
            "endpoint_url": "https://8.8.8.8",
            "config": {"extra": {"token": "must-use-credential-store"}},
        },
    )
    assert nested_secret.status_code == 422
    assert nested_secret.json()["error_code"] == "agent_security.secret_config_forbidden"
    incomplete = _target(
        client,
        target_type="http",
        config={"body": {"message": "{{prompt}}"}},
    )
    policy = _policy(client)
    task = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": incomplete["target_id"],
            "policy_id": policy["policy_id"],
            "idempotency_key": "missing-transform",
            "scan_kind": "agent_risk_scan", "evaluation_model": "test-judge",
        },
    )
    assert task.status_code == 422
    assert task.json()["error_code"] == "agent_security.response_transform_required"
    passive = _policy(client, execution_mode="passive")
    complete = _target(
        client,
        target_type="http",
        config={"body": {"message": "{{prompt}}"}, "transform_response": "reply"},
    )
    blocked = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": complete["target_id"],
            "policy_id": passive["policy_id"],
            "idempotency_key": "passive-agent-scan",
            "scan_kind": "agent_risk_scan", "evaluation_model": "test-judge",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "agent_security.active_scan_forbidden_by_policy"


def test_agent_scan_success_requires_current_worker_result_contract(p2_api):
    client, _, _, _ = p2_api
    target = _target(client)
    policy = _policy(client)
    task = _agent_task(client, target["target_id"], policy["policy_id"])
    worker = _worker(client)
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["agent_risk_scan"]},
    ).json()

    response = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/complete",
        headers=headers,
        json={"lease_token": claim["lease_token"], "status": "succeeded"},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "agent_security.worker_result_contract_invalid"


def test_worker_public_key_seals_credentials_and_scan_options(p2_api):
    client, session_factory, _, _ = p2_api
    target = _target(client)
    secret = "target-secret-should-never-be-plain"
    credential = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"credential_type": "bearer", "secret": secret},
    )
    assert credential.status_code == 200
    policy = _policy(client)
    task = _agent_task(
        client,
        target["target_id"],
        policy["policy_id"],
        prompt="private scan instruction",
        skills=["data-leakage-detection"],
    )
    worker = _worker(client)
    key_pair = credential_envelope.generate_worker_key_pair()
    claim = _register_and_claim(client, worker, key_pair, task["task_id"])
    assert secret not in json.dumps(claim)
    envelope = claim["credential"]["secret_envelope"]
    decrypted = credential_envelope.decrypt_secret_envelope(
        envelope,
        key_pair,
        worker_id=worker["worker_id"],
        task_id=task["task_id"],
        credential_id=credential.json()["credential_id"],
    )
    assert decrypted == secret
    assert claim["scan_options"]["prompt"] == "private scan instruction"
    with session_factory() as db:
        row = db.query(models.SecurityScanTask).filter_by(task_id=task["task_id"]).one()
        assert "private scan instruction" not in row.scan_options_encrypted
        assert json.loads(unprotect_secret(row.scan_options_encrypted))["prompt"] == "private scan instruction"


def test_completion_sanitizes_evidence_encrypts_raw_artifact_and_supports_disposition_and_compare(p2_api):
    client, session_factory, state, users = p2_api
    target = _target(client)
    policy = _policy(client)
    worker = _worker(client)
    key_pair = credential_envelope.generate_worker_key_pair()
    first = _agent_task(client, target["target_id"], policy["policy_id"])
    first_claim = _register_and_claim(client, worker, key_pair, first["task_id"])
    _complete(client, worker, first_claim, code="agent_goal_hijack", session="session-to-continue")
    detail = client.get(f"/api/v1/agent-security/tasks/{first['task_id']}").json()
    assert detail["cases"][0]["round_count"] == 2
    assert "&lt;script&gt;" in detail["cases"][0]["response_summary"]["response"]
    finding = detail["findings"][0]
    assert finding["fingerprint"]
    assert finding["risk_codes"] == ["ASI01"]
    assert finding["risk_mapping"]["mapping_version"] == "agent-manager-asi-map@1"
    assert finding["risk_mapping"]["framework_version"] == "first-public-draft"
    assert finding["risk_mapping"]["source_codes"] == ["agent_goal_hijack"]
    assert "<img" not in finding["title"]
    assert "[REDACTED]" in finding["description"]
    assert detail["artifacts"][0]["content_available"] is True
    artifact_id = detail["artifacts"][0]["artifact_id"]
    raw = client.get(f"/api/v1/agent-security/tasks/{first['task_id']}/artifacts/{artifact_id}/content")
    assert raw.status_code == 200
    assert raw.json()["content"].startswith("{")
    with session_factory() as db:
        artifact = db.query(models.SecurityScanArtifact).filter_by(artifact_id=artifact_id).one()
        assert artifact.content_encrypted.startswith("enc:")
        assert '"code": "agent_goal_hijack"' not in artifact.content_encrypted

    state["user"] = users["auditor"]
    denied = client.patch(
        f"/api/v1/agent-security/findings/{finding['finding_id']}",
        json={"status": "accepted", "comment": "reviewed"},
    )
    assert denied.status_code == 403
    state["user"] = users["admin"]
    disposed = client.patch(
        f"/api/v1/agent-security/findings/{finding['finding_id']}",
        json={"status": "accepted", "comment": "reviewed"},
    )
    assert disposed.status_code == 200
    assert disposed.json()["status"] == "accepted"
    assert disposed.json()["disposition_comment"] == "reviewed"
    assert disposed.json()["disposition_by"] == "admin"
    assert disposed.json()["disposition_at"]

    second = _agent_task(
        client,
        target["target_id"],
        policy["policy_id"],
        reset_session=False,
        continue_from_task_id=first["task_id"],
    )
    second_claim = _register_and_claim(client, worker, key_pair, second["task_id"])
    assert second_claim["scan_options"]["initial_session_id"] == "session-to-continue"
    _complete(client, worker, second_claim, code="tool_misuse")
    second_finding = client.get(f"/api/v1/agent-security/tasks/{second['task_id']}").json()["findings"][0]
    assert second_finding["risk_codes"] == ["ASI02"]
    compared = client.get(f"/api/v1/agent-security/tasks/{second['task_id']}/compare/{first['task_id']}")
    assert compared.status_code == 200
    comparison = compared.json()
    assert comparison["schema_version"] == "security-scan-comparison@1"
    assert comparison["comparison_status"] == "partial"
    assert comparison["coverage_match"] is False
    assert comparison["engine_match"] is True
    assert [item["finding_code"] for item in comparison["new"]] == ["tool_misuse"]
    assert comparison["resolved"] == []
    assert comparison["unable_to_retest"][0]["finding"]["finding_code"] == "agent_goal_hijack"
    assert comparison["unable_to_retest"][0]["reason_code"] == "coverage_changed"
    assert comparison["summary"] == {"new": 1, "unchanged": 0, "resolved": 0, "unable_to_retest": 1}

    repeated = _agent_task(client, target["target_id"], policy["policy_id"])
    repeated_claim = _register_and_claim(client, worker, key_pair, repeated["task_id"])
    _complete(client, worker, repeated_claim, code="agent_goal_hijack")
    unchanged = client.get(f"/api/v1/agent-security/tasks/{repeated['task_id']}/compare/{first['task_id']}")
    assert unchanged.status_code == 200
    assert [item["finding_code"] for item in unchanged.json()["unchanged"]] == ["agent_goal_hijack"]

    resolved_current = _agent_task(client, target["target_id"], policy["policy_id"])
    resolved_claim = _register_and_claim(client, worker, key_pair, resolved_current["task_id"])
    _complete(client, worker, resolved_claim, code="tool_misuse")
    resolved = client.get(
        f"/api/v1/agent-security/tasks/{resolved_current['task_id']}/compare/{first['task_id']}"
    )
    assert resolved.status_code == 200
    assert resolved.json()["comparison_status"] == "complete"
    assert [item["finding_code"] for item in resolved.json()["resolved"]] == ["agent_goal_hijack"]

    changed_coverage = _agent_task(
        client,
        target["target_id"],
        policy["policy_id"],
        skills=["data-leakage-detection"],
    )
    changed_claim = _register_and_claim(client, worker, key_pair, changed_coverage["task_id"])
    _complete(client, worker, changed_claim, code="tool_misuse")
    partial = client.get(
        f"/api/v1/agent-security/tasks/{changed_coverage['task_id']}/compare/{first['task_id']}"
    )
    assert partial.status_code == 200
    partial_body = partial.json()
    assert partial_body["comparison_status"] == "partial"
    assert partial_body["coverage_match"] is False
    assert partial_body["resolved"] == []
    assert partial_body["unable_to_retest"][0]["finding"]["finding_code"] == "agent_goal_hijack"
    assert partial_body["unable_to_retest"][0]["reason_code"] == "coverage_changed"

    unfinished = _agent_task(client, target["target_id"], policy["policy_id"])
    unfinished_comparison = client.get(
        f"/api/v1/agent-security/tasks/{unfinished['task_id']}/compare/{first['task_id']}"
    )
    assert unfinished_comparison.status_code == 200
    assert unfinished_comparison.json()["unable_to_retest"][0]["reason_code"] == "current_not_succeeded"

    same_task = client.get(f"/api/v1/agent-security/tasks/{first['task_id']}/compare/{first['task_id']}")
    assert same_task.status_code == 409
    assert same_task.json()["error_code"] == "agent_security.comparison_same_task"
    newer_baseline = client.get(f"/api/v1/agent-security/tasks/{first['task_id']}/compare/{second['task_id']}")
    assert newer_baseline.status_code == 409
    assert newer_baseline.json()["error_code"] == "agent_security.comparison_baseline_newer"
    control = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "scan_kind": "control_plane_validation",
            "idempotency_key": f"p6-compare-kind-{time.time_ns()}",
        },
    )
    assert control.status_code == 200
    kind_mismatch = client.get(
        f"/api/v1/agent-security/tasks/{control.json()['task_id']}/compare/{first['task_id']}"
    )
    assert kind_mismatch.status_code == 409
    assert kind_mismatch.json()["error_code"] == "agent_security.comparison_scan_kind_mismatch"

    state["user"] = users["owner"]
    raw_denied = client.get(f"/api/v1/agent-security/tasks/{first['task_id']}/artifacts/{artifact_id}/content")
    assert raw_denied.status_code == 403


def test_session_runtime_handles_single_multi_continue_and_reset():
    heartbeats = []
    target_checks = []

    def heartbeat(usage):
        heartbeats.append(dict(usage))
        return {"continue_allowed": True, "status": "running"}

    provider = SimpleNamespace(config=SimpleNamespace(extra={}, body={"message": "{{prompt}}"}))

    class FakeClient:
        def __init__(self):
            self.seen = []

        def call_provider(self, current_provider, prompt):
            self.seen.append(dict(current_provider.config.extra))
            session_id = "session-1" if len(self.seen) == 1 else "session-2"
            response = SimpleNamespace(raw={"reply": prompt}, output=prompt, session_id=session_id)
            return SimpleNamespace(success=True, provider_response=response)

    multi = aig_adapter.ScanRuntime(
        heartbeat,
        conversation_mode="multi_turn",
        initial_session_id="continued-session",
        input_cost_rate=0,
        output_cost_rate=0,
        target_check=lambda: target_checks.append(True),
    )
    client = FakeClient()
    multi.call_target(client, provider, "one", stage_id="2a")
    multi.call_target(client, provider, "two", stage_id="2a")
    assert client.seen[0]["conversation_id"] == "continued-session"
    assert client.seen[1]["conversation_id"] == "session-1"
    assert multi.session_id == "session-2"
    assert multi.target_calls_by_stage == {"2a": 2}
    assert len(target_checks) == 2
    normalized = aig_adapter._normalize_report(
        {"schema_version": "agent-security-report@1", "results": []},
        multi,
        task_id="asj-transcript",
        skills=[],
    )
    assert [case["external_case_id"] for case in normalized["cases"]] == [
        "aig-rule:unverified-summary"
    ]
    artifact_report = json.loads(normalized["artifacts"][0]["content"])
    transcript = artifact_report["execution_evidence"]["transcript"]
    assert [turn["round"] for turn in transcript] == [1, 2]
    assert artifact_report["execution_evidence"]["successful_calls"] == 2
    assert transcript[0]["session_id_hash"]

    single = aig_adapter.ScanRuntime(
        heartbeat,
        conversation_mode="single_turn",
        initial_session_id="must-reset",
        input_cost_rate=0,
        output_cost_rate=0,
    )
    single_client = FakeClient()
    single.call_target(single_client, provider, "single")
    assert "conversation_id" not in single_client.seen[0]
    assert single.session_id is None
    assert heartbeats


def _normalization_runtime(*, turns: int = 1):
    runtime = aig_adapter.ScanRuntime(
        lambda _usage: {"continue_allowed": True},
        conversation_mode="single_turn",
        initial_session_id=None,
        input_cost_rate=0,
        output_cost_rate=0,
    )
    runtime.turns = [
        {
            "prompt": f"probe-{index}",
            "response": f"response-{index}",
            "success": True,
            "session_id_hash": None,
        }
        for index in range(turns)
    ]
    runtime.successful_target_calls = turns
    return runtime


def test_detection_skills_become_independent_passed_cases_and_transcript_stays_artifact_only():
    skills = list(security_scans.AGENT_SCAN_SKILLS)
    report = {
        "schema_version": "agent-security-report@1",
        "results": [],
        "detection_executions": [
            {
                "skill_name": skill,
                "stage_id": f"2{chr(ord('a') + index)}",
                "status": "completed",
                "dialogue_calls": index + 1,
                "finding_count": 0,
                "error_type": None,
                "error_message": None,
            }
            for index, skill in enumerate(skills)
        ],
    }

    normalized = aig_adapter._normalize_report(
        report, _normalization_runtime(turns=34), task_id="asj-rules", skills=skills
    )

    assert len(normalized["cases"]) == 10
    assert {case["status"] for case in normalized["cases"]} == {"passed"}
    assert all(case["external_case_id"].startswith("aig-rule:") for case in normalized["cases"])
    assert all(case["external_case_id"] != "agent-dialogue-transcript" for case in normalized["cases"])
    artifact = normalized["artifacts"][0]
    artifact_report = json.loads(artifact["content"])
    assert len(artifact_report["execution_evidence"]["transcript"]) == 34
    assert artifact["metadata"]["coverage"] == {
        "planned_rules": 10,
        "executed_rules": 10,
        "passed_rules": 10,
        "failed_rules": 0,
        "error_rules": 0,
        "blocked_rules": 0,
        "unverified_rules": 0,
    }


def test_one_detection_error_does_not_report_all_ten_rules_as_passed():
    skills = list(security_scans.AGENT_SCAN_SKILLS)
    executions = [
        {
            "skill_name": skill,
            "stage_id": f"2{chr(97 + index)}",
            "status": "completed",
            "dialogue_calls": 1,
        }
        for index, skill in enumerate(skills)
    ]
    executions[1].update(
        {
            "status": "error",
            "dialogue_calls": 0,
            "error_type": "RuntimeError",
            "error_message": "Authorization: Bearer secret-value Cookie=session-secret",
        }
    )
    report = {
        "results": [],
        "detection_executions": executions,
    }

    normalized = aig_adapter._normalize_report(
        report, _normalization_runtime(), task_id="asj-partial", skills=skills
    )
    cases = {case["title"]: case for case in normalized["cases"]}
    assert cases[skills[0]]["status"] == "passed"
    assert cases[skills[1]]["status"] == "error"
    assert [case["status"] for case in normalized["cases"]].count("passed") == 9
    assert [case["status"] for case in normalized["cases"]].count("error") == 1
    error_message = cases[skills[1]]["response_summary"]["error_message"]
    assert "secret-value" not in error_message
    assert "session-secret" not in error_message
    assert error_message.count("[REDACTED]") == 2


def test_completed_detection_without_an_actual_target_call_is_unverified():
    skill = "indirect-injection-detection"
    normalized = aig_adapter._normalize_report(
        {
            "results": [],
            "detection_executions": [
                {
                    "skill_name": skill,
                    "stage_id": "2c",
                    "status": "completed",
                    "dialogue_calls": 0,
                }
            ],
        },
        _normalization_runtime(),
        task_id="asj-zero-dialogue",
        skills=[skill],
    )
    assert normalized["cases"][0]["status"] == "unverified"


def test_findings_use_only_controlled_skill_provenance_and_leave_unknown_sources_unmapped():
    skills = ["data-leakage-detection", "tool-abuse-detection"]
    base_finding = {
        "type": "ASI02: Tool Misuse",
        "title": "Observed misuse",
        "description": "Confirmed behavior",
        "level": "High",
        "owasp": ["ASI02"],
        "conversation": [{"prompt": "probe", "response": "unsafe"}],
    }
    report = {
        "detection_executions": [
            {"skill_name": skill, "stage_id": f"2{chr(97 + index)}", "status": "completed", "dialogue_calls": 1}
            for index, skill in enumerate(skills)
        ],
        "results": [
            dict(
                base_finding,
                id="mapped-finding",
                source_skill="tool-abuse-detection",
                source_mapping="worker_context",
            ),
            dict(base_finding, id="unmapped-finding", source_skill="data-leakage-detection"),
        ],
    }

    normalized = aig_adapter._normalize_report(
        report, _normalization_runtime(), task_id="asj-findings", skills=skills
    )
    findings = {item["evidence"]["upstream_finding_id"]: item for item in normalized["findings"]}
    assert findings["mapped-finding"]["case_external_id"] == "aig-rule:tool-abuse-detection"
    assert findings["mapped-finding"]["evidence"]["source_skill"] == "tool-abuse-detection"
    assert findings["unmapped-finding"]["case_external_id"] == "aig-rule:unmapped"
    assert findings["unmapped-finding"]["evidence"]["mapping_status"] == "unmapped"
    cases = {case["external_case_id"]: case for case in normalized["cases"]}
    assert cases["aig-rule:tool-abuse-detection"]["status"] == "failed"
    assert cases["aig-rule:unmapped"]["status"] == "unverified"


def test_legacy_report_without_detection_executions_is_unverified_not_passed():
    normalized = aig_adapter._normalize_report(
        {"schema_version": "agent-security-report@1", "results": []},
        _normalization_runtime(turns=5),
        task_id="asj-legacy",
        skills=["data-leakage-detection", "tool-abuse-detection"],
    )
    assert [(case["external_case_id"], case["status"]) for case in normalized["cases"]] == [
        ("aig-rule:unverified-summary", "unverified")
    ]
    coverage = normalized["artifacts"][0]["metadata"]["coverage"]
    assert coverage["passed_rules"] == 0
    assert coverage["unverified_rules"] == 2


def test_vendor_worker_outcomes_keep_execution_errors_and_program_controlled_source_refs():
    execution_module = importlib.import_module("agent_scan.core.detection_execution")
    outcomes = [
        (
            "<vuln><title>Issue</title><desc>Evidence</desc><risk_type>ASI02</risk_type></vuln>",
            {"dialogue": 3},
        ),
        RuntimeError("Authorization: Bearer top-secret Cookie=session-secret"),
    ]
    merged, stats, executions, source_map = execution_module.merge_worker_outcomes(
        outcomes, ["tool-abuse-detection", "data-leakage-detection"]
    )
    assert stats["dialogue"] == 3
    assert len(source_map) == 1
    assert set(source_map.values()) == {"tool-abuse-detection"}
    assert "<source_ref>" in merged
    report_module = importlib.import_module("agent_scan.core.report")
    reviewed_result = report_module.generate_report_from_xml(merged).model_dump()["results"][0]
    assert reviewed_result["source_ref"] == next(iter(source_map))
    assert executions[0]["status"] == "completed"
    assert executions[0]["finding_count"] == 1
    assert executions[1]["status"] == "error"
    assert "top-secret" not in executions[1]["error_message"]
    assert "session-secret" not in executions[1]["error_message"]
    source_ref = next(iter(source_map))
    reviewed = [{"source_ref": source_ref}, {"source_ref": "invented-ref"}]
    execution_module.attach_controlled_sources(reviewed, source_map)
    assert reviewed[0] == {
        "source_skill": "tool-abuse-detection",
        "source_mapping": "worker_context",
    }
    assert reviewed[1] == {"source_skill": None, "source_mapping": "unmapped"}


def test_scan_runtime_continues_task_level_usage_baseline():
    heartbeats = []
    baseline = {
        "rounds": 22,
        "tokens": 481423,
        "cost_microunits": 1200,
        "concurrent_requests": 4,
        "response_bytes": 4096,
    }
    runtime = aig_adapter.ScanRuntime(
        lambda usage: heartbeats.append(dict(usage)) or {"continue_allowed": True},
        conversation_mode="single_turn",
        initial_session_id=None,
        input_cost_rate=1_000_000,
        output_cost_rate=1_000_000,
        initial_usage=baseline,
    )

    assert runtime.snapshot() == baseline
    runtime._begin(target_round=True)
    runtime._end(response_bytes=128, input_tokens=30, output_tokens=47)

    assert runtime.snapshot() == {
        "rounds": 23,
        "tokens": 481500,
        "cost_microunits": 1277,
        "concurrent_requests": 4,
        "response_bytes": 4224,
    }
    assert heartbeats[0]["rounds"] == 23
    assert heartbeats[-1]["tokens"] == 481500


def test_kill_switch_heartbeat_prevents_next_target_request():
    calls = []
    runtime = aig_adapter.ScanRuntime(
        lambda _usage: {
            "continue_allowed": False,
            "status": "cancelled",
            "stop_reason": "kill_switch.activated",
        },
        conversation_mode="single_turn",
        initial_session_id=None,
        input_cost_rate=0,
        output_cost_rate=0,
    )
    provider = SimpleNamespace(config=SimpleNamespace(extra={}, body={"message": "{{prompt}}"}))

    class NeverCalledClient:
        def call_provider(self, _provider, _prompt):
            calls.append(True)

    with pytest.raises(aig_adapter.ScanStopped, match="kill_switch.activated"):
        runtime.call_target(NeverCalledClient(), provider, "must not be sent", stage_id="2a")
    assert calls == []
    assert runtime.target_calls_by_stage == {}


def test_unknown_risk_is_unmapped_and_malicious_content_is_safe():
    runtime = aig_adapter.ScanRuntime(
        lambda _usage: {"continue_allowed": True},
        conversation_mode="single_turn",
        initial_session_id=None,
        input_cost_rate=0,
        output_cost_rate=0,
    )
    report = {
        "schema_version": "agent-security-report@1",
        "score": 99,
        "risk_type": "safe",
        "results": [
            {
                "id": "future-risk",
                "type": "new_upstream_future_risk",
                "title": "<script>alert(1)</script>",
                "description": "Authorization: Bearer sk-private-123456789",
                "level": "Low",
                # Locked upstream defaults an unclassified risk_type to ASI10.
                "owasp": ["ASI10"],
                "conversation": [{"prompt": "<b>attack</b>", "response": "token=secret-value"}],
            }
        ],
    }
    normalized = aig_adapter._normalize_report(report, runtime, task_id="asj-test", skills=[])
    finding = normalized["findings"][0]
    assert finding["finding_code"] == "unmapped"
    assert finding["severity"] == "medium"
    assert finding["evidence"]["mapping_status"] == "unmapped"
    assert "<script>" not in finding["title"]
    assert "[REDACTED]" in finding["description"]
    assert normalized["artifacts"][0]["content"].find("new_upstream_future_risk") >= 0

    explicit_asi10 = dict(report)
    explicit_asi10["results"] = [dict(report["results"][0], type="ASI10: Rogue Agent", owasp=["ASI10"])]
    mapped = aig_adapter._normalize_report(explicit_asi10, runtime, task_id="asj-test", skills=[])
    assert mapped["findings"][0]["finding_code"] == "rogue_agent"

    report["results"][0]["level"] = "Critical"
    critical = aig_adapter._normalize_report(report, runtime, task_id="asj-test", skills=[])
    assert critical["findings"][0]["severity"] == "critical"


def test_redaction_handles_quoted_json_secrets_and_blocks_prototype_keys():
    value = {
        "__proto__": {"polluted": True},
        "payload": '{"apiKey": "quoted-secret-value", "token": "another-secret"}',
    }
    safe = sanitize_untrusted_value(value)
    assert "__proto__" not in safe
    assert safe["[blocked-key:__proto__]"]["polluted"] is True
    assert "quoted-secret-value" not in safe["payload"]
    assert "another-secret" not in safe["payload"]
    assert safe["payload"].count("[REDACTED]") == 2
    assert "quoted-secret-value" not in aig_adapter._redact(json.dumps(value))


def test_evaluator_terminal_error_is_tracked_fail_closed(monkeypatch):
    from agent_scan.utils.llm import LLM

    runtime = aig_adapter.ScanRuntime(
        lambda _usage: {"continue_allowed": True},
        conversation_mode="single_turn",
        initial_session_id=None,
        input_cost_rate=0,
        output_cost_rate=0,
    )
    monkeypatch.setattr(LLM, "chat", lambda *_args, **_kwargs: "[LLM Error: unavailable]")
    instrumented = aig_adapter._instrumented_llm_class(runtime)("model", "key", "https://example.com/v1")
    assert instrumented.chat([]).startswith("[LLM Error:")
    assert runtime.model_errors == 1
    with pytest.raises(aig_adapter.EvaluatorUnavailable):
        runtime.ensure_trustworthy_result()


def test_scan_without_a_successful_target_dialogue_fails_closed():
    runtime = aig_adapter.ScanRuntime(
        lambda _usage: {"continue_allowed": True},
        conversation_mode="single_turn",
        initial_session_id=None,
        input_cost_rate=0,
        output_cost_rate=0,
    )
    with pytest.raises(aig_adapter.TargetUnavailable):
        runtime.ensure_trustworthy_result()

    provider = SimpleNamespace(config=SimpleNamespace(extra={}, body={"message": "{{prompt}}"}))
    failure = SimpleNamespace(
        success=False,
        provider_response=SimpleNamespace(raw=None, output="", session_id=None),
    )
    runtime.call_target(SimpleNamespace(call_provider=lambda *_args: failure), provider, "hello")
    with pytest.raises(aig_adapter.TargetUnavailable):
        runtime.ensure_trustworthy_result()


def test_bounded_http_adapter_handles_normal_timeout_and_oversize():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length))
            message = payload.get("message")
            if message == "timeout":
                time.sleep(1.2)
                body = json.dumps({"reply": "late"}).encode()
            elif message == "oversize":
                body = json.dumps({"reply": "X" * 4096}).encode()
            else:
                body = json.dumps({"reply": "ok"}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from agent_scan.core.agent_adapter.adapter import ProviderConfig, ProviderOptions

        provider = ProviderOptions(
            id="http",
            config=ProviderConfig(
                url=f"http://127.0.0.1:{server.server_port}",
                body={"message": "{{prompt}}"},
                transform_response="reply",
            ),
        )
        client = aig_adapter._bounded_client_class(512)(timeout=1)
        assert client.call_provider(provider, "normal").success is True
        timeout = client.call_provider(provider, "timeout")
        assert timeout.success is False
        assert timeout.provider_response.error == "timeout"
        oversize = client.call_provider(provider, "oversize")
        assert oversize.success is False
        assert oversize.provider_response.error == "response_size_limit"
        assert oversize.provider_response.raw is None
    finally:
        server.shutdown()
        server.server_close()


def test_websocket_adapter_connects_to_bounded_local_target():
    from agent_scan.core.agent_adapter.adapter import ProviderConfig, ProviderOptions
    from websockets.sync.server import serve

    def handler(websocket):
        payload = json.loads(websocket.recv())
        websocket.send(json.dumps({"reply": f"safe {payload['message']}"}))
        websocket.send(json.dumps({"event": "done"}))

    server = serve(handler, "127.0.0.1", 0, max_size=2048)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.socket.getsockname()[1]
        provider = ProviderOptions(
            id="websocket",
            config=ProviderConfig(
                url=f"ws://127.0.0.1:{port}",
                body={"message": "{{prompt}}"},
                transform_response="reply",
                timeout_ms=1000,
            ),
        )
        result = aig_adapter._bounded_client_class(1024)(timeout=1).call_provider(provider, "hello")
        assert result.success is True
        assert result.provider_response.output == "safe hello"
        assert result.provider_response.metadata["transport"] == "websocket"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_mock_target_covers_required_p2_scenarios():
    source = Path("demo/agent-security-mock-target/server.py").read_text(encoding="utf-8")
    assert "[timeout]" in source
    assert "[oversize]" in source
    assert "[malicious]" in source
    assert "conversation_id" in source
    cases = json.loads(Path("demo/agent-security-mock-target/cases.json").read_text(encoding="utf-8"))
    assert {case["id"] for case in cases["cases"]} == {
        "prompt-injection",
        "sensitive-information-leak",
        "authorization-bypass",
        "tool-abuse",
    }
    assert all(case["expected_risk_code"] for case in cases["cases"])


def test_worker_keeps_lease_and_health_alive_during_long_agent_call(monkeypatch, tmp_path):
    worker_path = WORKER_DIR / "worker.py"
    spec = importlib.util.spec_from_file_location("agent_security_worker_p2", worker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HEALTH_PATH", tmp_path / "worker.healthy")
    calls = []

    transient_failure = {"remaining": 1}

    def fake_request(path, payload):
        calls.append((path, payload))
        if path.endswith("/heartbeat"):
            if transient_failure["remaining"]:
                transient_failure["remaining"] -= 1
                raise module.urllib.error.URLError("temporary")
            return {"continue_allowed": True}
        return {"status": "succeeded"}

    def fake_execute(_claim, _secret, _evaluator, _heartbeat, *, initial_usage=None):
        assert initial_usage == {
            "rounds": 22,
            "tokens": 481423,
            "cost_microunits": 0,
            "concurrent_requests": 1,
            "response_bytes": 128,
        }
        time.sleep(3.2)
        return {
            "status": "succeeded",
            "usage": {**initial_usage, "rounds": 23, "tokens": 481500},
            "cases": [],
            "findings": [],
            "artifacts": [],
        }

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "execute_agent_scan", fake_execute)
    claim = {
        "task": {
            "task_id": "asj_keepalive",
            "usage": {
                "rounds": 22,
                "tokens": 481423,
                "cost_microunits": 0,
                "concurrent_requests": 1,
                "response_bytes": 128,
            },
        },
        "lease_token": "lease-token",
        "lease_seconds": 3,
        "credential": {"configured": False},
    }
    module._run_agent_scan(claim, SimpleNamespace(), "worker-test")
    paths = [path for path, _ in calls]
    assert paths.count("/worker/tasks/asj_keepalive/heartbeat") >= 3
    assert paths[-1] == "/worker/tasks/asj_keepalive/complete"
    assert module._healthcheck() == 0


def test_worker_stops_attempt_after_backend_rejects_lease(monkeypatch, tmp_path, capsys):
    worker_path = WORKER_DIR / "worker.py"
    spec = importlib.util.spec_from_file_location("agent_security_worker_lost_lease", worker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HEALTH_PATH", tmp_path / "worker.healthy")
    secret_marker = "must-not-appear-worker-token"

    def fake_request(path, _payload):
        if path.endswith("/heartbeat"):
            raise module.ControlPlaneError(409, "agent_security.task_lease_expired")
        return {"status": "succeeded"}

    def fake_execute(_claim, _secret, _evaluator, heartbeat, *, initial_usage=None):
        time.sleep(1.2)
        response = heartbeat(initial_usage)
        assert response == {
            "continue_allowed": False,
            "stop_reason": "agent_security.task_lease_expired",
        }
        raise module.ScanStopped("agent_security.task_lease_expired")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "execute_agent_scan", fake_execute)
    claim = {
        "task": {"task_id": "asj_lost_lease", "usage": {}},
        "lease_token": secret_marker,
        "lease_seconds": 3,
        "credential": {"configured": False},
    }
    with pytest.raises(module.ScanStopped, match="task_lease_expired"):
        module._run_agent_scan(claim, SimpleNamespace(), "worker-test")
    captured = capsys.readouterr()
    assert "status=409" in captured.err
    assert "code=agent_security.task_lease_expired" in captured.err
    assert secret_marker not in captured.err


def test_p7_worker_api_finding_traceability_round_trip(p2_api, monkeypatch):
    client, session_factory, _state, _users = p2_api
    target = _target(client)
    policy = _policy(client)
    task = _agent_task(client, target["target_id"], policy["policy_id"])
    worker = _worker(client)
    key_pair = credential_envelope.generate_worker_key_pair()
    claim = _register_and_claim(client, worker, key_pair, task["task_id"])

    worker_path = WORKER_DIR / "worker.py"
    spec = importlib.util.spec_from_file_location("agent_security_worker_p7_e2e", worker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def api_request(path, payload):
        response = client.post(
            f"/api/v1/agent-security{path}",
            headers={"Authorization": f"Bearer {worker['token_once']}"},
            json=payload,
        )
        if response.status_code >= 400:
            body = response.json()
            raise module.ControlPlaneError(response.status_code, body.get("error_code", "unknown"))
        return response.json()

    raw_report = json.dumps(
        {"schema_version": "agent-security-report@1", "case": "p7-e2e-prompt-injection"},
        sort_keys=True,
    )

    def execute_agent_scan(_claim, _secret, _evaluator, heartbeat, *, initial_usage=None):
        assert initial_usage == {
            "rounds": 0,
            "tokens": 0,
            "cost_microunits": 0,
            "concurrent_requests": 0,
            "response_bytes": 0,
        }
        heartbeat(
            {
                "rounds": 1,
                "tokens": 12,
                "cost_microunits": 0,
                "concurrent_requests": 1,
                "response_bytes": len(raw_report.encode()),
            }
        )
        return {
            "status": "succeeded",
            "usage": {
                "rounds": 1,
                "tokens": 12,
                "cost_microunits": 0,
                "concurrent_requests": 1,
                "response_bytes": len(raw_report.encode()),
            },
            "cases": [
                {
                    "external_case_id": "p7-e2e-prompt-injection",
                    "category": "ASI01",
                    "title": "Prompt injection changes the Agent goal",
                    "status": "failed",
                    "request_summary": {"scenario": "authorized deterministic fixture"},
                    "response_summary": {"observation": "goal changed"},
                    "round_count": 1,
                }
            ],
            "findings": [
                {
                    "case_external_id": "p7-e2e-prompt-injection",
                    "finding_code": "agent_goal_hijack",
                    "severity": "high",
                    "title": "Agent goal hijack observed",
                    "description": "The deterministic fixture observed an unauthorized goal change.",
                    "evidence": {"observation": "goal changed", "fixture": "p7-e2e"},
                    "source": "ai_infra_guard",
                    "confidence": 0.98,
                }
            ],
            "artifacts": [
                {
                    "artifact_type": "aig-agent-scan-report",
                    "uri": f"artifact://{task['task_id']}/report.json",
                    "sha256": hashlib.sha256(raw_report.encode()).hexdigest(),
                    "size_bytes": len(raw_report.encode()),
                    "redacted": False,
                    "metadata": {"fixture": "p7-e2e"},
                    "content": raw_report,
                }
            ],
            "engine_name": aig_adapter.AIG_ENGINE_NAME,
            "engine_version": aig_adapter.AIG_TAG,
        }

    monkeypatch.setattr(module, "_request", api_request)
    monkeypatch.setattr(module, "execute_agent_scan", execute_agent_scan)
    module._run_agent_scan(claim, key_pair, worker["worker_id"])

    detail_response = client.get(f"/api/v1/agent-security/tasks/{task['task_id']}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["task"]["status"] == "succeeded"
    assert len(detail["cases"]) == len(detail["findings"]) == len(detail["artifacts"]) == 1
    finding = detail["findings"][0]
    traceability = finding["traceability"]
    assert traceability["status"] == "complete"
    assert traceability["case_id"] == detail["cases"][0]["case_id"]
    assert traceability["trace_id"].startswith("trc_scan_")
    assert traceability["event_id"].startswith("evt_")
    assert len(traceability["evidence_sha256"]) == 64
    assert traceability["decision_criteria_version"] == "agent-security-decision-criteria@2"
    assert traceability["missing"] == []

    linked = client.get(
        "/api/v1/agent-security/findings/links",
        params={"trace_id": traceability["trace_id"], "event_id": traceability["event_id"]},
    )
    assert linked.status_code == 200, linked.text
    assert [item["finding_id"] for item in linked.json()] == [finding["finding_id"]]
    exported = client.post(f"/api/v1/agent-security/tasks/{task['task_id']}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["findings"][0]["traceability"] == traceability

    with session_factory() as db:
        event = db.query(models.RuntimeTraceEvent).filter_by(event_id=traceability["event_id"]).one()
        assert event.source == "security_worker"
        assert event.type == "security.finding"
        assert event.turn_id is None
        assert event.step_id is None
        payload = db.query(models.RuntimeTracePayload).filter_by(event_id=event.event_id).one()
        assert payload.raw_payload_encrypted
        assert payload.raw_sha256


def test_worker_retry_continues_accumulated_usage_and_completes_report_without_findings(p2_api, monkeypatch):
    client, _session_factory, _state, _users = p2_api
    target = _target(client)
    policy = _policy(client, max_retries=1, retry_backoff_seconds=0, max_rounds=50, max_tokens=2_000_000)
    task = _agent_task(client, target["target_id"], policy["policy_id"])
    worker = _worker(client)
    key_pair = credential_envelope.generate_worker_key_pair()
    first_claim = _register_and_claim(client, worker, key_pair, task["task_id"])
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    first_usage = {
        "rounds": 22,
        "tokens": 481423,
        "cost_microunits": 1200,
        "concurrent_requests": 2,
        "response_bytes": 4096,
    }
    first_heartbeat = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/heartbeat",
        headers=headers,
        json={"lease_token": first_claim["lease_token"], "usage": first_usage},
    )
    assert first_heartbeat.status_code == 200, first_heartbeat.text
    retry = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/complete",
        headers=headers,
        json={
            "lease_token": first_claim["lease_token"],
            "status": "failed",
            "retryable": True,
            "error_code": "agent_security.evaluator_unavailable",
            "error_message": "Evaluator unavailable before final report submission.",
            "usage": first_usage,
        },
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "pending"

    second_response = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["agent_risk_scan"]},
    )
    assert second_response.status_code == 200, second_response.text
    second_claim = second_response.json()
    assert second_claim["task"]["attempt"] == 2
    assert second_claim["task"]["usage"] == first_usage

    worker_path = WORKER_DIR / "worker.py"
    spec = importlib.util.spec_from_file_location("agent_security_worker_retry", worker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed_heartbeats = []

    def api_request(path, payload):
        response = client.post(
            f"/api/v1/agent-security{path}",
            headers=headers,
            json=payload,
        )
        if response.status_code >= 400:
            body = response.json()
            raise module.ControlPlaneError(response.status_code, body.get("error_code", "unknown"))
        if path.endswith("/heartbeat"):
            observed_heartbeats.append(dict(payload["usage"]))
        return response.json()

    raw_report = json.dumps({"schema_version": "agent-security-report@1", "results": []}, sort_keys=True)
    final_usage = {
        **first_usage,
        "rounds": 23,
        "tokens": 481500,
        "response_bytes": first_usage["response_bytes"] + len(raw_report),
    }

    def successful_retry(_claim, _secret, _evaluator, heartbeat, *, initial_usage=None):
        assert initial_usage == first_usage
        assert heartbeat(initial_usage)["continue_allowed"] is True
        assert heartbeat(final_usage)["continue_allowed"] is True
        return {
            "status": "succeeded",
            "usage": final_usage,
            "cases": [
                {
                    "external_case_id": "retry-success-case",
                    "category": "ASI01",
                    "title": "Retry completed",
                    "status": "passed",
                    "round_count": 1,
                }
            ],
            "findings": [],
            "artifacts": [
                {
                    "artifact_type": "aig-agent-scan-report",
                    "uri": f"artifact://{task['task_id']}/retry-report.json",
                    "sha256": hashlib.sha256(raw_report.encode()).hexdigest(),
                    "size_bytes": len(raw_report.encode()),
                    "redacted": False,
                    "content": raw_report,
                }
            ],
            "engine_name": aig_adapter.AIG_ENGINE_NAME,
            "engine_version": aig_adapter.AIG_TAG,
        }

    monkeypatch.setattr(module, "_request", api_request)
    monkeypatch.setattr(module, "execute_agent_scan", successful_retry)
    module._run_agent_scan(second_claim, key_pair, worker["worker_id"])

    assert observed_heartbeats[0]["rounds"] >= 22
    assert observed_heartbeats[0]["tokens"] >= 481423
    assert observed_heartbeats[-1]["rounds"] == 23
    assert observed_heartbeats[-1]["tokens"] > 481423
    detail = client.get(f"/api/v1/agent-security/tasks/{task['task_id']}").json()
    assert detail["task"]["status"] == "succeeded"
    assert detail["task"]["usage"] == final_usage
    assert detail["task"]["heartbeat_at"] is not None
    assert len(detail["cases"]) == 1
    assert len(detail["artifacts"]) == 1
    assert detail["findings"] == []


def test_p7_worker_completion_fails_closed_when_finding_traceability_is_incomplete(p2_api):
    client, _session_factory, _state, _users = p2_api
    target = _target(client)
    policy = _policy(client)
    task = _agent_task(client, target["target_id"], policy["policy_id"])
    worker = _worker(client)
    claim = _register_and_claim(
        client,
        worker,
        credential_envelope.generate_worker_key_pair(),
        task["task_id"],
    )
    raw = json.dumps({"schema_version": "agent-security-report@1"}, sort_keys=True)
    finding = {
        "finding_code": "agent_goal_hijack",
        "severity": "high",
        "title": "Goal hijack",
        "description": "Observed by a deterministic fixture.",
        "evidence": {"observation": "goal changed"},
        "source": "ai_infra_guard",
        "confidence": 0.9,
    }
    payload = {
        "lease_token": claim["lease_token"],
        "status": "succeeded",
        "usage": {
            "rounds": 1,
            "tokens": 1,
            "cost_microunits": 0,
            "concurrent_requests": 1,
            "response_bytes": len(raw.encode()),
        },
        "cases": [
            {
                "external_case_id": "case-1",
                "category": "ASI01",
                "title": "Prompt injection",
                "status": "failed",
                "round_count": 1,
            }
        ],
        "findings": [finding],
        "artifacts": [
            {
                "artifact_type": "aig-agent-scan-report",
                "uri": f"artifact://{task['task_id']}/report.json",
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "size_bytes": len(raw.encode()),
                "redacted": False,
                "content": raw,
            }
        ],
        "engine_name": aig_adapter.AIG_ENGINE_NAME,
        "engine_version": aig_adapter.AIG_TAG,
    }
    url = f"/api/v1/agent-security/worker/tasks/{task['task_id']}/complete"
    headers = {"Authorization": f"Bearer {worker['token_once']}"}

    missing_case = client.post(url, headers=headers, json=payload)
    assert missing_case.status_code == 422, missing_case.text
    assert missing_case.json()["error_code"] == "agent_security.finding_case_reference_required"

    payload["findings"][0]["case_external_id"] = "case-1"
    payload["findings"][0]["evidence"] = {}
    missing_evidence = client.post(url, headers=headers, json=payload)
    assert missing_evidence.status_code == 422, missing_evidence.text
    assert missing_evidence.json()["error_code"] == "agent_security.finding_evidence_required"

    detail = client.get(f"/api/v1/agent-security/tasks/{task['task_id']}").json()
    assert detail["task"]["status"] == "running"
    assert detail["cases"] == []
    assert detail["findings"] == []


def test_p7_long_scan_result_and_large_artifact_complete_with_bounded_overhead(p2_api):
    client, session_factory, _state, _users = p2_api
    target = _target(client)
    policy = _policy(
        client,
        max_rounds=2_000,
        max_tokens=200_000,
        max_concurrent_requests=8,
        max_response_bytes=8 * 1024 * 1024,
    )
    task = _agent_task(client, target["target_id"], policy["policy_id"], conversation_mode="multi_turn")
    worker = _worker(client)
    claim = _register_and_claim(
        client,
        worker,
        credential_envelope.generate_worker_key_pair(),
        task["task_id"],
    )
    case_count = 120
    large_report = json.dumps(
        {
            "schema_version": "agent-security-report@1",
            "conversation_rounds": case_count * 10,
            "padding": "x" * (2 * 1024 * 1024),
        },
        sort_keys=True,
    )
    payload = {
        "lease_token": claim["lease_token"],
        "status": "succeeded",
        "usage": {
            "rounds": case_count * 10,
            "tokens": 100_000,
            "cost_microunits": 0,
            "concurrent_requests": 4,
            "response_bytes": len(large_report.encode()),
        },
        "cases": [
            {
                "external_case_id": f"long-case-{index:03d}",
                "category": "ASI01",
                "title": f"Long-session case {index}",
                "status": "failed",
                "request_summary": {"round": index * 10},
                "response_summary": {"observation": "deterministic fixture"},
                "round_count": 10,
            }
            for index in range(case_count)
        ],
        "findings": [
            {
                "case_external_id": f"long-case-{index:03d}",
                "finding_code": "agent_goal_hijack",
                "severity": "high",
                "title": f"Long-session finding {index}",
                "description": "Deterministic long-session load fixture.",
                "evidence": {"case_index": index, "observation": "goal changed"},
                "source": "ai_infra_guard",
                "confidence": 0.9,
            }
            for index in range(case_count)
        ],
        "artifacts": [
            {
                "artifact_type": "aig-agent-scan-report",
                "uri": f"artifact://{task['task_id']}/large-report.json",
                "sha256": hashlib.sha256(large_report.encode()).hexdigest(),
                "size_bytes": len(large_report.encode()),
                "redacted": False,
                "content": large_report,
            }
        ],
        "session_state": "s" * 2048,
        "engine_name": aig_adapter.AIG_ENGINE_NAME,
        "engine_version": aig_adapter.AIG_TAG,
    }

    started = time.perf_counter()
    completed = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/complete",
        headers={"Authorization": f"Bearer {worker['token_once']}"},
        json=payload,
    )
    elapsed = time.perf_counter() - started

    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded"
    assert elapsed < 30
    detail = client.get(f"/api/v1/agent-security/tasks/{task['task_id']}").json()
    assert len(detail["cases"]) == case_count
    assert len(detail["findings"]) == case_count
    assert all(item["traceability"]["status"] == "complete" for item in detail["findings"])
    assert detail["artifacts"][0]["size_bytes"] == len(large_report.encode())
    with session_factory() as db:
        assert db.query(models.RuntimeTraceEvent).filter_by(trace_id=f"trc_scan_{task['task_id']}").count() == case_count
        stored = db.query(models.SecurityScanArtifact).filter_by(task_id=task["task_id"]).one()
        assert stored.content_encrypted
        assert large_report not in stored.content_encrypted
