from __future__ import annotations

import asyncio
import importlib.util
import json
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from backend.config import Settings, settings
from backend.routers import security_scans
from backend.services import dify_intent_inference
from backend.security_scan_controls import (
    hash_value,
    json_dumps,
    protect_secret,
    resolve_target_endpoint,
    unprotect_secret,
    verify_dns_pin,
)
from backend.security_scan_schemas import SecurityCaseInput, SecurityWorkerCompleteRequest
from backend.security_worker_bootstrap import (
    BUILTIN_WORKER_CAPABILITIES,
    BUILTIN_WORKER_CREATED_BY,
    BUILTIN_WORKER_NAME,
    SecurityWorkerBootstrapError,
    bootstrap_builtin_security_worker,
    bootstrap_builtin_security_worker_once,
)
from backend.sqlite_db import Base, get_db


def test_security_case_schema_accepts_unverified_execution_evidence_status():
    case = SecurityCaseInput(
        external_case_id="aig-rule:data-leakage-detection",
        category="agent_detection_skill",
        title="data-leakage-detection",
        status="unverified",
        response_summary={"dialogue_calls": 0, "reason": "missing_execution_evidence"},
    )
    assert case.status == "unverified"


@pytest.fixture()
def p1_api(tmp_path, monkeypatch):
    database_path = tmp_path / "p1.db"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "AUDIT_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "audit.pem"))
    monkeypatch.setattr(settings, "SECURITY_AUDIT_EXPORT_PATH", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "p1-test-secret-key")

    with session_factory() as db:
        admin = models.User(username="admin", hashed_password="x", role="admin")
        auditor = models.User(username="auditor", hashed_password="x", role="security_auditor")
        owner = models.User(username="owner", hashed_password="x", role="user")
        other = models.User(username="other", hashed_password="x", role="user")
        group = models.UserGroup(name="security-target-users")
        db.add_all([admin, auditor, owner, other, group])
        db.flush()
        db.add(models.UserGroupMember(user_id=owner.id, group_id=group.id))
        db.commit()
        for row in (admin, auditor, owner, other, group):
            db.refresh(row)
        users = {
            "admin": admin,
            "auditor": auditor,
            "owner": owner,
            "other": other,
            "group": group,
        }

    state = {"user": users["admin"]}

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
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[auth.get_current_active_user] = current_user
    app.include_router(security_scans.router, prefix="/api")
    client = TestClient(app)
    yield client, session_factory, state, users
    client.close()
    engine.dispose()


def _create_target(client: TestClient, **overrides):
    payload = {
        "name": "Public test target",
        "target_type": "openai",
        "endpoint_url": "https://8.8.8.8/v1",
    }
    payload.update(overrides)
    response = client.post("/api/v1/agent-security/targets", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _create_policy(client: TestClient, **overrides):
    payload = {"name": f"policy-{overrides.pop('suffix', 'default')}"}
    payload.update(overrides)
    response = client.post("/api/v1/agent-security/policies", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _create_task(client: TestClient, target_id: str, policy_id: str, key: str = "idem-key-0001"):
    response = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target_id,
            "policy_id": policy_id,
            "idempotency_key": key,
            "scan_kind": "control_plane_validation",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_worker(client: TestClient, name: str = "p1-worker"):
    response = client.post(
        "/api/v1/agent-security/workers",
        json={"name": name, "capabilities": ["control_plane_validation"], "max_concurrency": 1},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _claim_control_plane_task(client: TestClient):
    target = _create_target(client)
    policy = _create_policy(client, lease_seconds=30, suffix=secrets.token_hex(8))
    task = _create_task(client, target["target_id"], policy["policy_id"], key=f"p1-task-{secrets.token_hex(8)}")
    worker = _create_worker(client, name=f"p1-worker-{secrets.token_hex(8)}")
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    claimed = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={})
    assert claimed.status_code == 200, claimed.text
    return task["task_id"], headers, claimed.json()["lease_token"]


def _completion_finding():
    return {
        "case_external_id": "case-1",
        "finding_code": "prompt_injection.detected",
        "severity": "high",
        "title": "Injection accepted",
        "description": "Injection accepted",
        "evidence": {"observed": True},
        "source": "review",
        "confidence": 0.9,
    }


def test_worker_absolute_timeout_stops_heartbeat(p1_api):
    client, factory, _, _ = p1_api
    task_id, headers, lease_token = _claim_control_plane_task(client)
    with factory() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        task.timeout_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    heartbeat = client.post(
        f"/api/v1/agent-security/worker/tasks/{task_id}/heartbeat",
        headers=headers,
        json={"lease_token": lease_token, "usage": {}},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "timed_out"
    assert heartbeat.json()["stop_reason"] == "task_timeout"


def test_worker_cancel_wins_over_completion(p1_api):
    client, factory, _, _ = p1_api
    task_id, headers, lease_token = _claim_control_plane_task(client)
    cancelled = client.post(f"/api/v1/agent-security/tasks/{task_id}/cancel")
    assert cancelled.json()["cancel_requested"] is True
    completed = client.post(
        f"/api/v1/agent-security/worker/tasks/{task_id}/complete",
        headers=headers,
        json={"lease_token": lease_token, "status": "succeeded", "usage": {}, "cases": [], "findings": []},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "cancelled"


@pytest.mark.parametrize("pending", [False, True])
def test_worker_cancel_is_persisted_on_lease_recovery(p1_api, pending):
    client, factory, _, _ = p1_api
    task_id, _, _ = _claim_control_plane_task(client)
    assert client.post(f"/api/v1/agent-security/tasks/{task_id}/cancel").status_code == 200
    with factory() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        task.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        if pending:
            task.status = "pending"
            security_scans._clear_lease(task)
        db.commit()
        security_scans.recover_stale_tasks(db)
    with factory() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        assert task.status == "cancelled"
        assert task.stop_reason == "cancel_requested"
        assert task.worker_id is None
        assert task.lease_token_hash is None


@pytest.mark.parametrize("endpoint", ["heartbeat", "complete", "infer-intent"])
def test_worker_deadline_with_capped_expired_lease(p1_api, monkeypatch, endpoint):
    client, factory, _, _ = p1_api

    class Clock(datetime):
        current = datetime.utcnow()

        @classmethod
        def utcnow(cls):
            return cls.current

    monkeypatch.setattr(security_scans, "datetime", Clock)
    target = _create_target(client)
    policy = _create_policy(client, lease_seconds=30, task_timeout_seconds=10)
    task = _create_task(client, target["target_id"], policy["policy_id"])
    worker = _create_worker(client)
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    claimed = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={})
    assert claimed.status_code == 200, claimed.text
    with factory() as db:
        row = db.query(models.SecurityScanTask).filter_by(task_id=task["task_id"]).one()
        deadline = row.timeout_at
        assert row.lease_expires_at == deadline == Clock.current + timedelta(seconds=10)
        if endpoint == "infer-intent":
            row.scan_kind = "dify_asset_inventory"
            row.scan_options_encrypted = protect_secret(json_dumps({"infer_agent_intent": True}))
            db.commit()

    async def unexpected_inference(*args, **kwargs):
        pytest.fail("An expired task must not invoke the intent model")

    monkeypatch.setattr(security_scans, "run_intent_inference", unexpected_inference)
    Clock.current = deadline + timedelta(seconds=1)
    payload = {"lease_token": claimed.json()["lease_token"], "usage": {}}
    if endpoint == "complete":
        payload["status"] = "succeeded"
    elif endpoint == "infer-intent":
        payload["summary"] = {}
    response = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/{endpoint}", headers=headers, json=payload,
    )
    assert response.status_code == 200, response.text
    assert response.json()["stop_reason"] == "task_timeout"
    with factory() as db:
        row = db.query(models.SecurityScanTask).filter_by(task_id=task["task_id"]).one()
        assert row.status == "timed_out"
        assert row.worker_id is None
        assert row.lease_token_hash is None
        assert row.lease_expires_at is None


@pytest.mark.parametrize("finding_count", [1001, 2000])
def test_worker_completion_accepts_large_findings_and_batches_trace_events(p1_api, finding_count):
    client, factory, _, _ = p1_api
    task_id, headers, lease_token = _claim_control_plane_task(client)
    response = client.post(
        f"/api/v1/agent-security/worker/tasks/{task_id}/complete",
        headers=headers,
        json={
            "lease_token": lease_token,
            "status": "succeeded",
            "usage": {},
            "cases": [{"external_case_id": "case-1", "category": "prompt_injection", "title": "Injection", "status": "failed"}],
            "findings": [_completion_finding() for _ in range(finding_count)],
        },
    )
    assert response.status_code == 200, response.text
    with factory() as db:
        stored_task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        assert stored_task.status == "succeeded"
        assert db.query(models.SecurityFinding).filter_by(task_id=task_id).count() == finding_count
        trace_id = f"trc_scan_{task_id}"
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id=trace_id).count() == 1
        events = db.query(models.RuntimeTraceEvent).filter_by(trace_id=trace_id).order_by(models.RuntimeTraceEvent.seq).all()
        assert len(events) == finding_count
        assert [event.seq for event in events] == list(range(1, finding_count + 1))
        assert db.query(models.RuntimeTracePayload).filter_by(trace_id=trace_id).count() == finding_count
        assert db.query(models.RuntimeTraceIngestBatch).filter_by(trace_id=trace_id).count() == 2
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id=trace_id, risk_level="high").count() == 1


def test_worker_completion_rolls_back_all_batches_and_can_retry(p1_api, monkeypatch):
    client, factory, _, _ = p1_api
    task_id, headers, lease_token = _claim_control_plane_task(client)
    payload = {
        "lease_token": lease_token, "status": "succeeded", "usage": {},
        "cases": [{"external_case_id": "case-1", "category": "prompt_injection", "title": "Injection", "status": "failed"}],
        "findings": [_completion_finding() for _ in range(1001)],
    }
    ingest = security_scans.ingest_runtime_trace_batch
    calls = 0

    def fail_after_second_batch(*args, **kwargs):
        nonlocal calls
        result = ingest(*args, **kwargs)
        calls += 1
        if calls == 2:
            raise ApiError(503, "test.batch_failure", "批次故障测试", "Injected batch failure")
        return result

    monkeypatch.setattr(security_scans, "ingest_runtime_trace_batch", fail_after_second_batch)
    url = f"/api/v1/agent-security/worker/tasks/{task_id}/complete"
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 503, response.text
    assert calls == 2
    trace_id = f"trc_scan_{task_id}"
    with factory() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        assert task.status == "running"
        assert task.completed_at is None
        assert task.lease_token_hash == hash_value(lease_token)
        for model in (models.SecurityFinding, models.SecurityScanCase, models.SecurityScanArtifact):
            assert db.query(model).filter_by(task_id=task_id).count() == 0
        for model in (
            models.RuntimeTraceSession, models.RuntimeTraceEvent,
            models.RuntimeTracePayload, models.RuntimeTraceIngestBatch,
        ):
            assert db.query(model).filter_by(trace_id=trace_id).count() == 0

    monkeypatch.setattr(security_scans, "ingest_runtime_trace_batch", ingest)
    retried = client.post(url, headers=headers, json=payload)
    assert retried.status_code == 200, retried.text
    with factory() as db:
        assert db.query(models.SecurityScanTask).filter_by(task_id=task_id).one().status == "succeeded"
        assert db.query(models.SecurityFinding).filter_by(task_id=task_id).count() == 1001
        assert db.query(models.RuntimeTraceEvent).filter_by(trace_id=trace_id).count() == 1001


def _worker_settings(token: str | None) -> Settings:
    return Settings(_env_file=None, AGENT_SECURITY_WORKER_TOKEN=token)


def test_p1_tables_and_unified_model_are_created():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "security_targets",
        "security_target_credentials",
        "security_scan_policies",
        "security_scan_tasks",
        "security_scan_cases",
        "security_findings",
        "security_scan_artifacts",
        "security_scan_workers",
    }.issubset(tables)
    assert models.SecurityFinding.severity.nullable is False
    assert models.SecurityFinding.evidence_json.nullable is False


def test_p6_environment_and_capability_boundaries_are_snapshotted_for_workers(p1_api):
    client, _, _, _ = p1_api
    target = _create_target(
        client,
        environment="staging",
        allowed_capabilities=["conversation", "multi_turn", "tool_read"],
    )
    assert target["environment"] == "staging"
    assert target["allowed_capabilities"] == ["conversation", "multi_turn", "tool_read"]

    wrong_environment = _create_policy(
        client,
        suffix="wrong-environment",
        environment="test",
        allowed_capabilities=["conversation"],
    )
    rejected_environment = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": wrong_environment["policy_id"],
            "idempotency_key": "p6-wrong-environment",
        },
    )
    assert rejected_environment.status_code == 409
    assert rejected_environment.json()["error_code"] == "agent_security.policy_environment_mismatch"

    excessive_policy = _create_policy(
        client,
        suffix="excessive-capability",
        environment="staging",
        allowed_capabilities=["conversation", "code_execution"],
    )
    rejected_capability = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": excessive_policy["policy_id"],
            "idempotency_key": "p6-excessive-capability",
        },
    )
    assert rejected_capability.status_code == 409
    assert rejected_capability.json()["error_code"] == "agent_security.policy_capability_mismatch"
    assert rejected_capability.json()["error_params"]["unsupported_capabilities"] == ["code_execution"]

    policy = _create_policy(
        client,
        suffix="staging-compatible",
        environment="staging",
        execution_mode="active_safe",
        allowed_capabilities=["conversation", "tool_read"],
    )
    task = _create_task(client, target["target_id"], policy["policy_id"], key="p6-compatible-task")
    worker = _create_worker(client, name="p6-boundary-worker")
    claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers={"Authorization": f"Bearer {worker['token_once']}"},
        json={"capabilities": ["control_plane_validation"]},
    )
    assert claim.status_code == 200, claim.text


def test_builtin_worker_bootstrap_disabled_and_invalid_token_is_secret_safe(p1_api):
    _, session_factory, _, _ = p1_api
    with session_factory() as db:
        result = bootstrap_builtin_security_worker(db, _worker_settings(None))
        assert result.action == "disabled"
        assert db.query(models.SecurityScanWorker).count() == 0

    invalid_token = "amsw_too-short-sensitive-value"
    with session_factory() as db, pytest.raises(SecurityWorkerBootstrapError) as exc_info:
        bootstrap_builtin_security_worker(db, _worker_settings(invalid_token))
    assert invalid_token not in str(exc_info.value)
    with session_factory() as db:
        assert db.query(models.SecurityScanWorker).count() == 0


def test_builtin_worker_bootstrap_logs_never_include_the_configured_token(p1_api, caplog):
    _, session_factory, _, _ = p1_api
    token = "amsw_" + "l" * 32
    bootstrap_builtin_security_worker_once(_worker_settings(token), session_factory)
    bootstrap_builtin_security_worker_once(_worker_settings(token), session_factory)
    assert token not in caplog.text


def test_builtin_worker_bootstrap_is_idempotent_and_preserves_runtime_state(p1_api):
    client, session_factory, _, _ = p1_api
    token = "amsw_" + "a" * 32
    with session_factory() as db:
        created = bootstrap_builtin_security_worker(db, _worker_settings(token))
        assert created.action == "created"
        row = db.query(models.SecurityScanWorker).one()
        assert row.worker_id == created.worker_id
        assert row.name == BUILTIN_WORKER_NAME
        assert row.created_by == BUILTIN_WORKER_CREATED_BY
        assert row.token_hash == hash_value(token)
        assert row.token_hash != token
        assert row.token_prefix == token[:12]
        assert json.loads(row.capabilities_json) == list(BUILTIN_WORKER_CAPABILITIES)
        assert row.max_concurrency == 1
        row.public_key_algorithm = "x25519-hkdf-sha256-aesgcm-v1"
        row.public_key = "stored-public-key"
        row.public_key_fingerprint = "f" * 64
        row.public_key_registered_at = datetime.utcnow()
        row.last_heartbeat_at = datetime.utcnow()
        db.commit()
        original_worker_id = row.worker_id
        original_heartbeat = row.last_heartbeat_at

    with session_factory() as db:
        unchanged = bootstrap_builtin_security_worker(db, _worker_settings(token))
        assert unchanged.action == "unchanged"
        assert unchanged.worker_id == original_worker_id
        row = db.query(models.SecurityScanWorker).one()
        assert row.public_key == "stored-public-key"
        assert row.public_key_fingerprint == "f" * 64
        assert row.last_heartbeat_at == original_heartbeat
        created_events = (
            db.query(models.SecurityAuditEvent)
            .filter(models.SecurityAuditEvent.event_type == "security_scan_worker.created")
            .all()
        )
        assert len(created_events) == 1
        assert token not in created_events[0].details_json

    listed = client.get("/api/v1/agent-security/workers")
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload) == 1
    assert payload[0]["worker_id"] == original_worker_id
    assert payload[0]["token_once"] is None
    assert token not in listed.text


def test_builtin_worker_bootstrap_rejects_manual_name_conflict(p1_api):
    _, session_factory, _, _ = p1_api
    manual_token = "amsw_" + "m" * 32
    with session_factory() as db:
        db.add(
            models.SecurityScanWorker(
                worker_id="asw_manual_conflict",
                name=BUILTIN_WORKER_NAME,
                token_hash=hash_value(manual_token),
                token_prefix=manual_token[:12],
                capabilities_json='["control_plane_validation"]',
                max_concurrency=1,
                created_by="admin",
            )
        )
        db.commit()
    configured_token = "amsw_" + "n" * 32
    with session_factory() as db, pytest.raises(SecurityWorkerBootstrapError) as exc_info:
        bootstrap_builtin_security_worker(db, _worker_settings(configured_token))
    assert configured_token not in str(exc_info.value)
    with session_factory() as db:
        row = db.query(models.SecurityScanWorker).one()
        assert row.worker_id == "asw_manual_conflict"
        assert row.created_by == "admin"
        assert row.token_hash == hash_value(manual_token)


def test_builtin_worker_token_rotation_invalidates_old_token_and_clears_runtime_state(p1_api):
    client, session_factory, _, _ = p1_api
    old_token = "amsw_" + "o" * 32
    new_token = "amsw_" + "p" * 32
    with session_factory() as db:
        created = bootstrap_builtin_security_worker(db, _worker_settings(old_token))
        row = db.query(models.SecurityScanWorker).one()
        row.public_key_algorithm = "x25519-hkdf-sha256-aesgcm-v1"
        row.public_key = "old-public-key"
        row.public_key_fingerprint = "e" * 64
        row.public_key_registered_at = datetime.utcnow()
        row.last_heartbeat_at = datetime.utcnow()
        db.commit()
        worker_id = created.worker_id

    assert client.post(
        "/api/v1/agent-security/worker/heartbeat",
        headers={"Authorization": f"Bearer {old_token}"},
    ).status_code == 200
    with session_factory() as db:
        rotated = bootstrap_builtin_security_worker(db, _worker_settings(new_token))
        assert rotated.action == "rotated"
        assert rotated.worker_id == worker_id
        row = db.query(models.SecurityScanWorker).one()
        assert row.worker_id == worker_id
        assert row.token_hash == hash_value(new_token)
        assert row.token_prefix == new_token[:12]
        assert row.status == "active"
        assert row.public_key_algorithm is None
        assert row.public_key is None
        assert row.public_key_fingerprint is None
        assert row.public_key_registered_at is None
        assert row.last_heartbeat_at is None
        rotation = (
            db.query(models.SecurityAuditEvent)
            .filter(models.SecurityAuditEvent.event_type == "security_scan_worker.token_rotated")
            .one()
        )
        assert old_token not in rotation.details_json
        assert new_token not in rotation.details_json

    old_auth = client.post(
        "/api/v1/agent-security/worker/heartbeat",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert old_auth.status_code == 401
    assert old_token not in old_auth.text
    new_auth = client.post(
        "/api/v1/agent-security/worker/heartbeat",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert new_auth.status_code == 200


def test_revoked_builtin_worker_requires_a_new_token_to_reactivate(p1_api):
    client, session_factory, _, _ = p1_api
    old_token = "amsw_" + "r" * 32
    new_token = "amsw_" + "s" * 32
    with session_factory() as db:
        created = bootstrap_builtin_security_worker(db, _worker_settings(old_token))
        worker_id = created.worker_id
    revoked = client.post(f"/api/v1/agent-security/workers/{worker_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    with session_factory() as db:
        unchanged = bootstrap_builtin_security_worker(db, _worker_settings(old_token))
        assert unchanged.action == "revoked"
        assert db.query(models.SecurityScanWorker).one().status == "revoked"
    assert client.post(
        "/api/v1/agent-security/worker/heartbeat",
        headers={"Authorization": f"Bearer {old_token}"},
    ).status_code == 401

    with session_factory() as db:
        rotated = bootstrap_builtin_security_worker(db, _worker_settings(new_token))
        assert rotated.action == "rotated"
        row = db.query(models.SecurityScanWorker).one()
        assert row.worker_id == worker_id
        assert row.status == "active"
        assert row.revoked_at is None
        assert row.revoked_by is None
    assert client.post(
        "/api/v1/agent-security/worker/heartbeat",
        headers={"Authorization": f"Bearer {new_token}"},
    ).status_code == 200


def test_concurrent_builtin_worker_bootstrap_creates_one_identity(p1_api):
    _, session_factory, _, _ = p1_api
    token = "amsw_" + "c" * 32

    def initialize():
        with session_factory() as db:
            return bootstrap_builtin_security_worker(db, _worker_settings(token))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: initialize(), range(16)))
    assert {result.worker_id for result in results} == {results[0].worker_id}
    assert sum(result.action == "created" for result in results) == 1
    with session_factory() as db:
        assert db.query(models.SecurityScanWorker).count() == 1
        assert (
            db.query(models.SecurityAuditEvent)
            .filter(models.SecurityAuditEvent.event_type == "security_scan_worker.created")
            .count()
            == 1
        )


def test_environment_bootstrapped_worker_registers_key_heartbeats_and_claims_pending_task(
    p1_api, monkeypatch
):
    client, session_factory, _, _ = p1_api
    token = "amsw_" + "w" * 32
    target = _create_target(client)
    policy = _create_policy(client)
    task = _create_task(client, target["target_id"], policy["policy_id"], key="builtin-worker-claim")
    with session_factory() as db:
        worker = bootstrap_builtin_security_worker(db, _worker_settings(token))

    monkeypatch.setenv("AGENT_SECURITY_WORKER_TOKEN", token)
    worker_path = "services/agent-security-worker/worker.py"
    spec = importlib.util.spec_from_file_location("agent_security_builtin_worker_test", worker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.WORKER_TOKEN == token

    def control_plane_request(path, payload):
        response = client.post(
            f"/api/v1/agent-security{path}",
            headers={"Authorization": f"Bearer {module.WORKER_TOKEN}"},
            json=payload,
        )
        assert response.status_code == 200, response.text
        return response.json()

    module._request = control_plane_request
    key_pair = module.generate_worker_key_pair()
    assert module._register_key(key_pair) == worker.worker_id
    heartbeat = module._request("/worker/heartbeat", {})
    assert heartbeat["worker_id"] == worker.worker_id
    claim = module._request(
        "/worker/claim",
        {"capabilities": ["control_plane_validation", "agent_risk_scan", "mcp_risk_scan"]},
    )
    assert claim["task"]["task_id"] == task["task_id"]


def test_p6_environment_and_capability_values_are_validated(p1_api):
    client, _, _, _ = p1_api
    invalid_environment = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "invalid environment",
            "target_type": "openai",
            "endpoint_url": "https://8.8.8.8/v1",
            "environment": "customer-production",
        },
    )
    assert invalid_environment.status_code == 422
    assert invalid_environment.json()["error_code"] == "request.validation_failed"

    invalid_capability = client.post(
        "/api/v1/agent-security/policies",
        json={"name": "invalid capability", "allowed_capabilities": ["shell_root"]},
    )
    assert invalid_capability.status_code == 422
    assert invalid_capability.json()["error_code"] == "request.validation_failed"


def test_p6_task_preview_is_server_derived_permission_scoped_and_stale_safe(p1_api):
    client, session_factory, state, users = p1_api
    target = _create_target(client)
    policy = _create_policy(
        client,
        suffix="preview",
        max_rounds=17,
        max_tokens=12345,
        max_cost_microunits=4567,
        max_concurrent_requests=3,
        max_duration_seconds=321,
        max_response_bytes=654321,
    )
    preview_payload = {
        "target_id": target["target_id"],
        "policy_id": policy["policy_id"],
        "scan_kind": "control_plane_validation",
    }
    state["user"] = users["other"]
    forbidden = client.post("/api/v1/agent-security/tasks/preview", json=preview_payload)
    assert forbidden.status_code == 403
    state["user"] = users["admin"]

    preview = client.post("/api/v1/agent-security/tasks/preview", json=preview_payload)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["schema_version"] == "scan-preview@1"
    assert len(body["preview_fingerprint"]) == 64
    assert body["cases"] == [
        {
            "case_key": "control_plane_validation",
            "category": "control_plane",
            "dynamic": False,
            "planned_rounds": 1,
        }
    ]
    assert body["tool_plan"] == {"mode": "none", "dynamic": False, "tools": []}
    assert body["budget"] == {
        "max_rounds": 17,
        "max_tokens": 12345,
        "max_cost_microunits": 4567,
        "max_concurrent_requests": 3,
        "max_duration_seconds": 321,
        "max_response_bytes": 654321,
        "max_attempts": 3,
        "task_timeout_seconds": 3600,
    }
    with session_factory() as db:
        assert db.query(models.SecurityScanTask).count() == 0

    created = client.post(
        "/api/v1/agent-security/tasks",
        json={
            **preview_payload,
            "preview_fingerprint": body["preview_fingerprint"],
            "idempotency_key": "preview-create-current",
        },
    )
    assert created.status_code == 200, created.text

    fresh_preview = client.post("/api/v1/agent-security/tasks/preview", json=preview_payload).json()
    changed = client.patch(
        f"/api/v1/agent-security/policies/{policy['policy_id']}",
        json={"max_tokens": 99999},
    )
    assert changed.status_code == 200, changed.text
    stale = client.post(
        "/api/v1/agent-security/tasks",
        json={
            **preview_payload,
            "preview_fingerprint": fresh_preview["preview_fingerprint"],
            "idempotency_key": "preview-create-stale",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "agent_security.scan_preview_stale"


def test_p6_production_active_full_is_rejected_on_policy_mutations_and_task_creation(p1_api):
    client, session_factory, _, _ = p1_api
    create_rejected = client.post(
        "/api/v1/agent-security/policies",
        json={
            "name": "production active full",
            "environment": "production",
            "execution_mode": "active_full",
        },
    )
    assert create_rejected.status_code == 422
    assert create_rejected.json()["error_code"] == "agent_security.production_active_full_forbidden"

    test_full = _create_policy(
        client,
        suffix="test-active-full",
        environment="test",
        execution_mode="active_full",
    )
    environment_rejected = client.patch(
        f"/api/v1/agent-security/policies/{test_full['policy_id']}",
        json={"environment": "production"},
    )
    assert environment_rejected.status_code == 422
    assert environment_rejected.json()["error_code"] == "agent_security.production_active_full_forbidden"

    production_read_only = _create_policy(
        client,
        suffix="production-read-only",
        environment="production",
        execution_mode="read_only",
    )
    mode_rejected = client.patch(
        f"/api/v1/agent-security/policies/{production_read_only['policy_id']}",
        json={"execution_mode": "active_full"},
    )
    assert mode_rejected.status_code == 422
    assert mode_rejected.json()["error_code"] == "agent_security.production_active_full_forbidden"

    target = _create_target(client, name="legacy production target", environment="production")
    with session_factory() as db:
        db.add(
            models.SecurityScanPolicy(
                policy_id="asp_legacy_production_active_full",
                name="legacy production active full",
                environment="production",
                execution_mode="active_full",
                allowed_capabilities_json=json_dumps(["conversation"]),
                outbound_allowlist_json="[]",
                created_by="legacy-migration",
            )
        )
        db.commit()
    task_rejected = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": "asp_legacy_production_active_full",
            "idempotency_key": "legacy-production-full-task",
        },
    )
    assert task_rejected.status_code == 409
    assert task_rejected.json()["error_code"] == "agent_security.production_active_full_forbidden"


def test_p6_production_active_safe_requires_complete_controls_and_single_use_approval(p1_api):
    client, session_factory, _, _ = p1_api
    target = _create_target(client, name="approved production target", environment="production")
    missing_controls = client.post(
        "/api/v1/agent-security/policies",
        json={
            "name": "missing production controls",
            "environment": "production",
            "execution_mode": "active_safe",
        },
    )
    assert missing_controls.status_code == 422
    assert missing_controls.json()["error_code"] == "agent_security.production_active_safe_controls_required"
    assert set(missing_controls.json()["error_params"]["missing_fields"]) == {
        "production_target_ids",
        "maintenance_window_start",
        "maintenance_window_end",
        "dedicated_identity_ref",
    }

    now = datetime.utcnow()
    window_start = now - timedelta(minutes=5)
    window_end = now + timedelta(hours=1)
    policy = _create_policy(
        client,
        suffix="production-active-safe",
        environment="production",
        execution_mode="active_safe",
        production_target_ids=[target["target_id"]],
        maintenance_window_start=window_start.isoformat(),
        maintenance_window_end=window_end.isoformat(),
        dedicated_identity_ref="bank-prod-security-test-user",
    )
    assert policy["production_target_ids"] == [target["target_id"]]
    assert policy["dedicated_identity_ref"] == "bank-prod-security-test-user"

    no_credential = client.post(
        "/api/v1/agent-security/scan-approvals",
        json={"target_id": target["target_id"], "policy_id": policy["policy_id"]},
    )
    assert no_credential.status_code == 409
    assert no_credential.json()["error_code"] == "agent_security.production_dedicated_credential_required"
    credential = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"credential_type": "bearer", "secret": "dedicated-production-scan-secret"},
    ).json()

    no_approval = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "idempotency_key": "production-without-approval",
        },
    )
    assert no_approval.status_code == 409
    assert no_approval.json()["error_code"] == "agent_security.production_active_safe_approval_required"

    approved = client.post(
        "/api/v1/agent-security/scan-approvals",
        json={"target_id": target["target_id"], "policy_id": policy["policy_id"]},
    )
    assert approved.status_code == 200, approved.text
    approval = approved.json()
    assert approval["status"] == "approved"
    assert approval["credential_id"] == credential["credential_id"]
    preview = client.post(
        "/api/v1/agent-security/tasks/preview",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "approval_id": approval["approval_id"],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["safety"]["approval_required"] is True
    assert preview.json()["safety"]["approval_id"] == approval["approval_id"]
    approval_after_preview = client.get(
        "/api/v1/agent-security/scan-approvals",
        params={"target_id": target["target_id"]},
    ).json()
    assert next(item for item in approval_after_preview if item["approval_id"] == approval["approval_id"])["status"] == "approved"
    task = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "approval_id": approval["approval_id"],
            "preview_fingerprint": preview.json()["preview_fingerprint"],
            "idempotency_key": "production-approved-task",
        },
    )
    assert task.status_code == 200, task.text
    assert task.json()["approval_id"] == approval["approval_id"]
    repeated = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "approval_id": approval["approval_id"],
            "idempotency_key": "production-approved-task",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["task_id"] == task.json()["task_id"]
    replayed = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "approval_id": approval["approval_id"],
            "idempotency_key": "production-approval-replay",
        },
    )
    assert replayed.status_code == 409
    assert replayed.json()["error_code"] == "agent_security.production_active_safe_approval_invalid"
    approvals = client.get(
        "/api/v1/agent-security/scan-approvals",
        params={"target_id": target["target_id"]},
    ).json()
    stored_approval = next(item for item in approvals if item["approval_id"] == approval["approval_id"])
    assert stored_approval["status"] == "used"
    assert stored_approval["used_task_id"] == task.json()["task_id"]

    worker = _create_worker(client, name="production-approved-worker")
    claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers={"Authorization": f"Bearer {worker['token_once']}"},
        json={"capabilities": ["control_plane_validation"]},
    )
    assert claim.status_code == 200, claim.text
    controls = claim.json()["target"]["production_controls"]
    assert controls["approval_id"] == approval["approval_id"]
    assert controls["credential_id"] == credential["credential_id"]
    assert controls["dedicated_identity_ref"] == "bank-prod-security-test-user"
    with session_factory() as db:
        stored_task = db.query(models.SecurityScanTask).filter_by(task_id=task.json()["task_id"]).one()
        assert stored_task.timeout_at <= window_end


def test_p6_production_approval_is_bound_to_window_allowlist_and_credential_version(p1_api):
    client, _, _, _ = p1_api
    target = _create_target(client, name="credential-bound production target", environment="production")
    other_target = _create_target(client, name="other production target", environment="production")
    now = datetime.utcnow()
    invalid_window = client.post(
        "/api/v1/agent-security/policies",
        json={
            "name": "overlong production window",
            "environment": "production",
            "execution_mode": "active_safe",
            "production_target_ids": [target["target_id"]],
            "maintenance_window_start": now.isoformat(),
            "maintenance_window_end": (now + timedelta(hours=25)).isoformat(),
            "dedicated_identity_ref": "prod-test-id",
        },
    )
    assert invalid_window.status_code == 422
    assert invalid_window.json()["error_code"] == "agent_security.production_maintenance_window_invalid"

    policy = _create_policy(
        client,
        suffix="credential-bound-production",
        environment="production",
        execution_mode="active_safe",
        production_target_ids=[target["target_id"]],
        maintenance_window_start=(now - timedelta(minutes=1)).isoformat(),
        maintenance_window_end=(now + timedelta(hours=1)).isoformat(),
        dedicated_identity_ref="prod-test-id",
    )
    not_allowlisted = client.post(
        "/api/v1/agent-security/scan-approvals",
        json={"target_id": other_target["target_id"], "policy_id": policy["policy_id"]},
    )
    assert not_allowlisted.status_code == 409
    assert not_allowlisted.json()["error_code"] == "agent_security.production_target_not_allowlisted"

    first_credential = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"credential_type": "bearer", "secret": "first-dedicated-secret"},
    ).json()
    approval = client.post(
        "/api/v1/agent-security/scan-approvals",
        json={"target_id": target["target_id"], "policy_id": policy["policy_id"]},
    ).json()
    assert approval["credential_id"] == first_credential["credential_id"]
    client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"credential_type": "bearer", "secret": "rotated-dedicated-secret"},
    )
    stale_approval = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "approval_id": approval["approval_id"],
            "idempotency_key": "stale-credential-approval",
        },
    )
    assert stale_approval.status_code == 409
    assert stale_approval.json()["error_code"] == "agent_security.production_active_safe_approval_invalid"


def test_target_validation_blocks_private_metadata_and_dns_rebinding(p1_api, monkeypatch):
    client, _, _, _ = p1_api
    private = client.post(
        "/api/v1/agent-security/targets",
        json={"name": "private", "target_type": "http", "endpoint_url": "https://127.0.0.1"},
    )
    assert private.status_code == 422
    assert private.json()["error_code"] == "agent_security.non_routable_address_forbidden"
    loopback_allowlist = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "loopback-allowlist",
            "target_type": "http",
            "endpoint_url": "https://127.0.0.1",
            "allowed_cidrs": ["127.0.0.0/8"],
        },
    )
    assert loopback_allowlist.status_code == 422
    assert loopback_allowlist.json()["error_code"] == "agent_security.non_routable_address_forbidden"

    metadata = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "metadata",
            "target_type": "http",
            "endpoint_url": "https://169.254.169.254",
            "allowed_cidrs": ["169.254.0.0/16"],
        },
    )
    assert metadata.status_code == 422
    assert metadata.json()["error_code"] == "agent_security.cloud_metadata_forbidden"

    allowed_internal = _create_target(
        client,
        name="explicit internal",
        endpoint_url="https://10.20.30.40",
        allowed_cidrs=["10.20.30.0/24"],
    )
    assert allowed_internal["resolved_ips"] == ["10.20.30.40"]
    public_only_policy = _create_policy(client, suffix="public-only")
    blocked_by_policy = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": allowed_internal["target_id"],
            "policy_id": public_only_policy["policy_id"],
            "idempotency_key": "private-policy-blocked",
        },
    )
    assert blocked_by_policy.status_code == 422
    assert blocked_by_policy.json()["error_code"] == "agent_security.private_address_forbidden"
    internal_policy = _create_policy(
        client,
        suffix="internal-allowed",
        outbound_allowlist=["10.20.30.0/24"],
    )
    assert (
        _create_task(
            client,
            allowed_internal["target_id"],
            internal_policy["policy_id"],
            key="private-policy-allowed",
        )["status"]
        == "pending"
    )

    answers = [[("", "", "", "", ("8.8.8.8", 443))], [("", "", "", "", ("1.1.1.1", 443))]]
    monkeypatch.setattr("socket.getaddrinfo", lambda *_args, **_kwargs: answers.pop(0))
    pinned = resolve_target_endpoint("https://public.example")
    with pytest.raises(ApiError) as exc:
        verify_dns_pin("https://public.example", pinned)
    assert exc.value.code == "agent_security.dns_rebinding_detected"


def test_credentials_are_encrypted_masked_rotatable_and_revocable(p1_api):
    client, session_factory, _, _ = p1_api
    target = _create_target(client)
    plain = "sk-live-super-secret-value"
    created = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"credential_type": "api_key", "secret": plain},
    )
    assert created.status_code == 200
    assert created.json()["secret_once"] == plain
    assert plain not in created.json()["secret_masked"]

    with session_factory() as db:
        row = db.query(models.SecurityTargetCredential).one()
        assert row.secret_encrypted.startswith("enc:")
        assert plain not in row.secret_encrypted
        assert unprotect_secret(row.secret_encrypted) == plain

    target_response = client.get(f"/api/v1/agent-security/targets/{target['target_id']}")
    assert plain not in target_response.text
    credential_id = created.json()["credential_id"]
    rotated = client.patch(
        f"/api/v1/agent-security/credentials/{credential_id}",
        json={"secret": "replacement-secret-value"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["secret_once"] is None
    assert "replacement-secret-value" not in rotated.text
    disabled = client.patch(
        f"/api/v1/agent-security/credentials/{credential_id}/status",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    disabled_target = client.get(f"/api/v1/agent-security/targets/{target['target_id']}").json()
    assert disabled_target["credential_configured"] is False
    assert disabled_target["credentials"] == [{
        "credential_id": credential_id,
        "purpose": "agent_runtime",
        "credential_type": "api_key",
        "secret_masked": rotated.json()["secret_masked"],
        "status": "disabled",
        "version": 2,
    }]
    enabled = client.patch(
        f"/api/v1/agent-security/credentials/{credential_id}/status",
        json={"status": "active"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"
    revoked = client.post(f"/api/v1/agent-security/credentials/{credential_id}/revoke")
    assert revoked.json()["status"] == "revoked"
    with session_factory() as db:
        events = {row.event_type for row in db.query(models.SecurityAuditEvent).all()}
        assert "security_target.credential_disabled" in events
        assert "security_target.credential_enabled" in events


def test_task_idempotency_authorization_and_auditor_read_only(p1_api):
    client, _, state, users = p1_api
    target = _create_target(client, owner_user_id=users["owner"].id)
    group_target = _create_target(
        client,
        name="group target",
        endpoint_url="https://1.1.1.1/v1",
        owner_user_id=users["admin"].id,
        owner_group_id=users["group"].id,
    )
    policy = _create_policy(client)

    state["user"] = users["owner"]
    assert client.get(f"/api/v1/agent-security/targets/{group_target['target_id']}").status_code == 200
    first = _create_task(client, target["target_id"], policy["policy_id"])
    repeated = _create_task(client, target["target_id"], policy["policy_id"])
    assert repeated["task_id"] == first["task_id"]

    state["user"] = users["admin"]
    second_policy = _create_policy(client, suffix="second")
    state["user"] = users["owner"]
    conflict = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": target["target_id"],
            "policy_id": second_policy["policy_id"],
            "idempotency_key": "idem-key-0001",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "agent_security.idempotency_conflict"

    state["user"] = users["other"]
    assert client.get(f"/api/v1/agent-security/targets/{target['target_id']}").status_code == 403
    assert client.get(f"/api/v1/agent-security/tasks/{first['task_id']}").status_code == 403

    state["user"] = users["auditor"]
    assert client.get(f"/api/v1/agent-security/tasks/{first['task_id']}").status_code == 200
    denied = client.post(f"/api/v1/agent-security/tasks/{first['task_id']}/cancel")
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "auth.permission_denied"


def test_worker_claim_heartbeat_completion_and_unified_results(p1_api):
    client, session_factory, _, _ = p1_api
    target = _create_target(client)
    credential = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"credential_type": "bearer", "secret": "worker-must-not-see-this"},
    ).json()
    policy = _create_policy(client, lease_seconds=30)
    task = _create_task(client, target["target_id"], policy["policy_id"])
    assert task["report_template_version"] == "agent-security-report-template@3"
    assert task["decision_criteria_version"] == "agent-security-decision-criteria@2"
    assert task["report_contract_status"] == "frozen"
    worker = _create_worker(client)
    token = worker["token_once"]
    headers = {"Authorization": f"Bearer {token}"}

    with session_factory() as db:
        stored = db.query(models.SecurityScanWorker).one()
        assert stored.token_hash == hash_value(token)
        assert token not in stored.token_hash

    listed = client.get("/api/v1/agent-security/workers")
    assert listed.json()[0]["token_once"] is None
    claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["control_plane_validation"]},
    )
    assert claim.status_code == 200, claim.text
    claimed = claim.json()
    assert claimed["task"]["task_id"] == task["task_id"]
    assert claimed["credential"]["credential_id"] == credential["credential_id"]
    assert claimed["credential"]["secret_delivery"] == "not_available_in_p1"
    assert "worker-must-not-see-this" not in claim.text
    assert client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()["task"] is None

    usage = {
        "rounds": 1,
        "tokens": 100,
        "cost_microunits": 10,
        "concurrent_requests": 1,
        "response_bytes": 200,
    }
    heartbeat = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/heartbeat",
        headers=headers,
        json={"lease_token": claimed["lease_token"], "usage": usage},
    )
    assert heartbeat.json()["continue_allowed"] is True
    completed = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/complete",
        headers=headers,
        json={
            "lease_token": claimed["lease_token"],
            "status": "succeeded",
            "usage": usage,
            "cases": [
                {
                    "external_case_id": "case-1",
                    "category": "prompt_injection",
                    "title": "Injection test",
                    "status": "failed",
                    "round_count": 1,
                }
            ],
            "findings": [
                {
                    "case_external_id": "case-1",
                    "finding_code": "prompt_injection.detected",
                    "severity": "high",
                    "title": "Prompt injection accepted",
                    "description": "The test response followed an injected instruction.",
                    "evidence": {"redacted": True},
                    "source": "p1-test",
                    "confidence": 0.9,
                }
            ],
            "artifacts": [
                {
                    "artifact_type": "raw_result",
                    "uri": "artifact://p1/result.json",
                    "sha256": "a" * 64,
                    "size_bytes": 42,
                    "redacted": True,
                }
            ],
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded"
    detail = client.get(f"/api/v1/agent-security/tasks/{task['task_id']}").json()
    assert detail["cases"][0]["external_case_id"] == "case-1"
    assert detail["findings"][0]["severity"] == "high"
    assert detail["findings"][0]["case_id"] == detail["cases"][0]["case_id"]
    assert detail["findings"][0]["decision_criteria_version"] == "agent-security-decision-criteria@2"
    assert detail["findings"][0]["traceability"]["status"] == "complete"
    assert detail["findings"][0]["traceability"]["case_id"] == detail["cases"][0]["case_id"]
    assert detail["findings"][0]["traceability"]["trace_id"].startswith("trc_scan_")
    assert detail["findings"][0]["traceability"]["event_id"]
    assert len(detail["findings"][0]["traceability"]["evidence_sha256"]) == 64
    assert detail["findings"][0]["traceability"]["decision_criteria_version"] == "agent-security-decision-criteria@2"
    assert detail["findings"][0]["traceability"]["missing"] == []
    assert detail["artifacts"][0]["redacted"] is True
    assert detail["report_contract"]["snapshot_status"] == "frozen"
    assert detail["report_contract"]["scan_kind"] == "control_plane_validation"
    assert detail["report_contract"]["standards"]["tc260"]["catalog"]["control_count"] == 31
    assert detail["report_contract"]["standards"]["tc260"]["summary"] == {
        "verified": 0,
        "partial": 7,
        "uncovered": 24,
        "total": 31,
        "coverage_percentage": None,
    }
    exported = client.post(f"/api/v1/agent-security/tasks/{task['task_id']}/export").json()
    assert exported["report_contract"] == detail["report_contract"]

    with session_factory() as db:
        legacy = db.query(models.SecurityScanTask).filter_by(task_id=task["task_id"]).one()
        legacy.report_template_version = None
        legacy.decision_criteria_version = None
        legacy.report_contract_json = "{}"
        db.commit()
    legacy_detail = client.get(f"/api/v1/agent-security/tasks/{task['task_id']}").json()
    assert legacy_detail["task"]["report_contract_status"] == "legacy_unversioned"
    assert legacy_detail["report_contract"]["schema_version"] is None

    cancellable = _create_task(
        client,
        target["target_id"],
        policy["policy_id"],
        key="running-cancel-0001",
    )
    running = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()
    cancelled = client.post(f"/api/v1/agent-security/tasks/{cancellable['task_id']}/cancel")
    assert cancelled.json()["cancel_requested"] is True
    stopped = client.post(
        f"/api/v1/agent-security/worker/tasks/{cancellable['task_id']}/heartbeat",
        headers=headers,
        json={"lease_token": running["lease_token"], "usage": {}},
    )
    assert stopped.json()["continue_allowed"] is False
    assert stopped.json()["status"] == "cancelled"
    revoked = client.post(f"/api/v1/agent-security/workers/{worker['worker_id']}/revoke")
    assert revoked.json()["status"] == "revoked"
    rejected = client.post("/api/v1/agent-security/worker/heartbeat", headers=headers, json={})
    assert rejected.status_code == 401
    assert rejected.json()["error_code"] == "agent_security.worker_token_invalid"


def test_task_kill_switch_stops_pending_and_running_work_without_success_overwrite(p1_api):
    client, session_factory, state, users = p1_api
    target = _create_target(client, name="Kill switch target")
    policy = _create_policy(client, suffix="kill-switch")
    worker = _create_worker(client, name="kill-switch-worker")
    headers = {"Authorization": f"Bearer {worker['token_once']}"}

    pending = _create_task(client, target["target_id"], policy["policy_id"], key="kill-pending-0001")
    missing_reason = client.post(
        f"/api/v1/agent-security/tasks/{pending['task_id']}/kill-switch",
        json={"reason": "   "},
    )
    assert missing_reason.status_code == 422
    state["user"] = users["owner"]
    denied = client.post(
        f"/api/v1/agent-security/tasks/{pending['task_id']}/kill-switch",
        json={"reason": "owner cannot activate emergency stop"},
    )
    assert denied.status_code == 403

    state["user"] = users["admin"]
    killed_pending = client.post(
        f"/api/v1/agent-security/tasks/{pending['task_id']}/kill-switch",
        json={"reason": "Unexpected outbound behavior"},
    )
    assert killed_pending.status_code == 200, killed_pending.text
    pending_payload = killed_pending.json()
    assert pending_payload["status"] == "cancelled"
    assert pending_payload["stop_reason"] == "kill_switch.activated_before_start"
    assert pending_payload["kill_switch_activated"] is True
    assert pending_payload["kill_switch_activated_by"] == "admin"
    assert pending_payload["kill_switch_reason"] == "Unexpected outbound behavior"
    assert client.post(
        f"/api/v1/agent-security/tasks/{pending['task_id']}/kill-switch",
        json={"reason": "idempotent retry"},
    ).json()["kill_switch_reason"] == "Unexpected outbound behavior"
    assert client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()["task"] is None

    running_task = _create_task(client, target["target_id"], policy["policy_id"], key="kill-running-0001")
    running = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()
    assert running["task"]["task_id"] == running_task["task_id"]
    activated = client.post(
        f"/api/v1/agent-security/tasks/{running_task['task_id']}/kill-switch",
        json={"reason": "Target started returning sensitive content"},
    )
    assert activated.json()["status"] == "running"
    assert activated.json()["stop_reason"] == "kill_switch.activated"
    completed = client.post(
        f"/api/v1/agent-security/worker/tasks/{running_task['task_id']}/complete",
        headers=headers,
        json={"lease_token": running["lease_token"], "status": "succeeded", "usage": {}},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "cancelled"
    assert completed.json()["stop_reason"] == "kill_switch.activated"

    heartbeat_task = _create_task(client, target["target_id"], policy["policy_id"], key="kill-heartbeat-0001")
    heartbeat_claim = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()
    client.post(
        f"/api/v1/agent-security/tasks/{heartbeat_task['task_id']}/kill-switch",
        json={"reason": "Emergency heartbeat stop"},
    )
    stopped = client.post(
        f"/api/v1/agent-security/worker/tasks/{heartbeat_task['task_id']}/heartbeat",
        headers=headers,
        json={"lease_token": heartbeat_claim["lease_token"], "usage": {}},
    )
    assert stopped.json() == {
        "continue_allowed": False,
        "status": "cancelled",
        "stop_reason": "kill_switch.activated",
        "lease_expires_at": None,
    }

    abandoned_task = _create_task(client, target["target_id"], policy["policy_id"], key="kill-recover-0001")
    abandoned_claim = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()
    assert abandoned_claim["task"]["task_id"] == abandoned_task["task_id"]
    client.post(
        f"/api/v1/agent-security/tasks/{abandoned_task['task_id']}/kill-switch",
        json={"reason": "Worker stopped responding"},
    )
    with session_factory() as db:
        stored = db.query(models.SecurityScanTask).filter_by(task_id=abandoned_task["task_id"]).one()
        stored.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        assert security_scans.recover_stale_tasks(db) == {"timed_out": 0, "retried": 0, "failed": 0}
        db.refresh(stored)
        assert stored.status == "cancelled"
        assert stored.stop_reason == "kill_switch.activated"

    with session_factory() as db:
        events = db.query(models.SecurityAuditEvent).filter(
            models.SecurityAuditEvent.event_type == "security_scan_task.kill_switch_activated"
        ).all()
    assert {event.resource_id for event in events} >= {pending["task_id"], running_task["task_id"], heartbeat_task["task_id"]}


def test_finding_trace_event_links_are_validated_and_permission_scoped(p1_api):
    client, session_factory, state, users = p1_api
    target = _create_target(client, name="Trace-linked target", owner_group_id=users["group"].id)
    policy = _create_policy(client, suffix="trace-links")
    task = _create_task(client, target["target_id"], policy["policy_id"], key="trace-link-task")
    worker = _create_worker(client, name="trace-link-worker")
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    claim = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()

    with session_factory() as db:
        trace = models.RuntimeTraceSession(
            trace_id="trc-linked",
            tenant_id=str(users["group"].id),
            session_id="session-linked",
            owner_user_id=users["admin"].id,
            owner_group_id=users["group"].id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        event = models.RuntimeTraceEvent(
            event_id="evt-linked",
            content_fingerprint="f" * 64,
            trace_id=trace.trace_id,
            seq=1,
            event_time=datetime.utcnow(),
            tenant_id=str(users["group"].id),
            session_id=trace.session_id,
            source="agent_sdk",
            type="security.finding",
            status="observed",
        )
        db.add_all([trace, event])
        db.commit()
        task_row = db.query(models.SecurityScanTask).filter_by(task_id=task["task_id"]).one()
        security_scans._validate_finding_trace_reference(
            db, task_row, trace_id="trc-linked", event_id="evt-linked"
        )
        with pytest.raises(ApiError) as missing_reference:
            security_scans._validate_finding_trace_reference(
                db, task_row, trace_id="trc-linked", event_id="evt-missing"
            )
        assert missing_reference.value.code == "agent_security.finding_trace_reference_invalid"
        mismatched_task = SimpleNamespace(
            owner_user_id=users["other"].id,
            owner_group_id=users["group"].id,
        )
        with pytest.raises(ApiError) as scope_mismatch:
            security_scans._validate_finding_trace_reference(
                db, mismatched_task, trace_id="trc-linked", event_id="evt-linked"
            )
        assert scope_mismatch.value.code == "agent_security.finding_trace_scope_mismatch"

    completed = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/complete",
        headers=headers,
        json={
            "lease_token": claim["lease_token"],
            "status": "succeeded",
            "cases": [{
                "external_case_id": "runtime-linked-case",
                "category": "runtime",
                "title": "Runtime linked case",
                "status": "failed",
            }],
            "findings": [{
                "case_external_id": "runtime-linked-case",
                "trace_id": "trc-linked",
                "event_id": "evt-linked",
                "finding_code": "runtime.prompt_injection",
                "severity": "high",
                "title": "Linked runtime finding",
                "description": "A stable runtime event reference is available.",
                "evidence": {"redacted": True},
                "source": "p5-link-test",
                "confidence": 0.9,
            }],
        },
    )
    assert completed.status_code == 200, completed.text
    finding = client.get(f"/api/v1/agent-security/tasks/{task['task_id']}").json()["findings"][0]
    assert finding["trace_id"] == "trc-linked"
    assert finding["event_id"] == "evt-linked"
    assert client.get(f"/api/v1/agent-security/findings/{finding['finding_id']}").status_code == 200
    linked = client.get(
        "/api/v1/agent-security/findings/links",
        params={"trace_id": "trc-linked", "event_id": "evt-linked"},
    )
    assert [item["finding_id"] for item in linked.json()] == [finding["finding_id"]]

    state["user"] = users["owner"]
    assert client.get(f"/api/v1/agent-security/findings/{finding['finding_id']}").status_code == 200
    state["user"] = users["other"]
    assert client.get(f"/api/v1/agent-security/findings/{finding['finding_id']}").status_code == 403
    hidden = client.get(
        "/api/v1/agent-security/findings/links",
        params={"trace_id": "trc-linked", "event_id": "evt-linked"},
    )
    assert hidden.json() == []


def test_finding_trace_reference_requires_a_complete_existing_pair():
    with pytest.raises(ValueError):
        SecurityWorkerCompleteRequest(
            lease_token="x" * 16,
            status="succeeded",
            findings=[{
                "trace_id": "trc-only",
                "finding_code": "runtime.invalid_link",
                "severity": "medium",
                "title": "Invalid link",
                "description": "Missing event id.",
                "source": "p5-link-test",
            }],
        )


def test_worker_claim_enforces_concurrency_atomically(p1_api):
    client, _, _, _ = p1_api
    target = _create_target(client, suffix="atomic-claim")
    policy = _create_policy(client, suffix="atomic-claim")
    _create_task(client, target["target_id"], policy["policy_id"], key="atomic-claim-0001")
    _create_task(client, target["target_id"], policy["policy_id"], key="atomic-claim-0002")
    worker = _create_worker(client, name="atomic-claim-worker")
    headers = {"Authorization": f"Bearer {worker['token_once']}"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}),
                range(2),
            )
        )

    assert all(response.status_code == 200 for response in responses)
    assert sum(response.json()["task"] is not None for response in responses) == 1


def test_p7_concurrent_scan_claims_fill_capacity_without_duplicate_leases(p1_api):
    client, session_factory, _, _ = p1_api
    target = _create_target(client, suffix="p7-load")
    policy = _create_policy(client, suffix="p7-load")
    task_ids = {
        _create_task(client, target["target_id"], policy["policy_id"], key=f"p7-load-{index:04d}")["task_id"]
        for index in range(24)
    }
    worker_response = client.post(
        "/api/v1/agent-security/workers",
        json={
            "name": "p7-load-worker",
            "capabilities": ["control_plane_validation"],
            "max_concurrency": 8,
        },
    )
    assert worker_response.status_code == 200, worker_response.text
    worker = worker_response.json()
    headers = {"Authorization": f"Bearer {worker['token_once']}"}

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=24) as executor:
        responses = list(
            executor.map(
                lambda _: client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}),
                range(24),
            )
        )
    elapsed = time.perf_counter() - started

    assert all(response.status_code == 200 for response in responses)
    claimed_ids = [response.json()["task"]["task_id"] for response in responses if response.json()["task"]]
    assert len(claimed_ids) == 8
    assert len(set(claimed_ids)) == 8
    assert set(claimed_ids) <= task_ids
    assert elapsed < 30
    with session_factory() as db:
        assert db.query(models.SecurityScanTask).filter_by(status="running").count() == 8
        assert db.query(models.SecurityScanTask).filter_by(status="pending").count() == 16


def test_worker_lease_expiry_retries_then_fails_explicitly(p1_api):
    client, session_factory, _, _ = p1_api
    target = _create_target(client)
    policy = _create_policy(client, max_retries=1, retry_backoff_seconds=0, lease_seconds=10)
    task = _create_task(client, target["target_id"], policy["policy_id"])
    worker = _create_worker(client)
    headers = {"Authorization": f"Bearer {worker['token_once']}"}

    first = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()
    with session_factory() as db:
        row = db.query(models.SecurityScanTask).filter_by(task_id=task["task_id"]).one()
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        recovered = security_scans.recover_stale_tasks(db)
        db.refresh(row)
        assert recovered == {"timed_out": 0, "retried": 1, "failed": 0}
        assert row.status == "pending"

    second = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()
    assert second["task"]["attempt"] == 2
    assert second["lease_token"] != first["lease_token"]
    with session_factory() as db:
        row = db.query(models.SecurityScanTask).filter_by(task_id=task["task_id"]).one()
        row.error_code = "agent_security.evaluator_unavailable"
        row.error_message = "Evaluator unavailable before result submission."
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        recovered = security_scans.recover_stale_tasks(db)
        db.refresh(row)
        assert recovered == {"timed_out": 0, "retried": 0, "failed": 1}
        assert row.status == "failed"
        assert row.stop_reason == "lease_expired_attempts_exhausted"
        assert row.error_code == "agent_security.evaluator_unavailable"
        assert row.error_message == "Evaluator unavailable before result submission."

    no_original_error = _create_task(
        client,
        target["target_id"],
        policy["policy_id"],
        key="lease-no-original-error",
    )
    claim_without_error = client.post(
        "/api/v1/agent-security/worker/claim", headers=headers, json={}
    ).json()
    assert claim_without_error["task"]["task_id"] == no_original_error["task_id"]
    with session_factory() as db:
        row = db.query(models.SecurityScanTask).filter_by(task_id=no_original_error["task_id"]).one()
        row.attempt = row.max_attempts
        row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        security_scans.recover_stale_tasks(db)
        db.refresh(row)
        assert row.status == "failed"
        assert row.error_code == "agent_security.worker_lease_lost"

    pending = _create_task(
        client,
        target["target_id"],
        policy["policy_id"],
        key="pending-timeout-0001",
    )
    with session_factory() as db:
        row = db.query(models.SecurityScanTask).filter_by(task_id=pending["task_id"]).one()
        row.timeout_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        recovered = security_scans.recover_stale_tasks(db)
        db.refresh(row)
        assert recovered == {"timed_out": 1, "retried": 0, "failed": 0}
        assert row.status == "timed_out"


@pytest.mark.parametrize(
    ("policy_field", "task_field", "actual", "reason"),
    [
        ("max_rounds", "rounds_used", 2, "budget.max_rounds_exceeded"),
        ("max_tokens", "tokens_used", 2, "budget.max_tokens_exceeded"),
        ("max_cost_microunits", "cost_microunits_used", 2, "budget.max_cost_microunits_exceeded"),
        ("max_concurrent_requests", "max_concurrency_seen", 2, "budget.max_concurrent_requests_exceeded"),
        ("max_response_bytes", "response_bytes_used", 2, "budget.max_response_bytes_exceeded"),
    ],
)
def test_each_numeric_budget_has_a_stable_stop_reason(policy_field, task_field, actual, reason):
    policy = {
        "max_rounds": 100,
        "max_tokens": 100,
        "max_cost_microunits": 100,
        "max_concurrent_requests": 100,
        "max_response_bytes": 100,
        "max_duration_seconds": 100,
    }
    policy[policy_field] = 1
    task = models.SecurityScanTask(
        policy_snapshot_json=json_dumps(policy),
        rounds_used=0,
        tokens_used=0,
        cost_microunits_used=0,
        max_concurrency_seen=0,
        response_bytes_used=0,
        started_at=datetime.utcnow(),
    )
    setattr(task, task_field, actual)
    assert security_scans._budget_reason(task, datetime.utcnow()) == reason


def test_budget_boundaries_stop_new_cumulative_work_but_allow_configured_parallelism():
    policy = {
        "max_rounds": 1,
        "max_tokens": 10,
        "max_cost_microunits": 10,
        "max_concurrent_requests": 1,
        "max_response_bytes": 10,
        "max_duration_seconds": 100,
    }
    task = models.SecurityScanTask(
        policy_snapshot_json=json_dumps(policy),
        rounds_used=1,
        tokens_used=0,
        cost_microunits_used=0,
        max_concurrency_seen=1,
        response_bytes_used=0,
        started_at=datetime.utcnow(),
    )
    assert security_scans._budget_reason(task, datetime.utcnow()) is None
    for field, reason in (
        ("tokens_used", "budget.max_tokens_exceeded"),
        ("cost_microunits_used", "budget.max_cost_microunits_exceeded"),
        ("response_bytes_used", "budget.max_response_bytes_exceeded"),
    ):
        setattr(task, field, 10)
        assert security_scans._budget_reason(task, datetime.utcnow()) == reason
        setattr(task, field, 0)


def test_worker_completion_payload_has_an_aggregate_size_limit():
    with pytest.raises(ValueError, match="exceeds 16 MiB"):
        SecurityWorkerCompleteRequest(
            lease_token="x" * 32,
            status="succeeded",
            cases=[
                {
                    "category": "oversized",
                    "title": "oversized evidence",
                    "status": "failed",
                    "request_summary": {"content": "x" * (17 * 1024 * 1024)},
                }
            ],
        )


def test_duration_budget_and_runtime_heartbeat_stop_new_work(p1_api):
    client, _, _, _ = p1_api
    target = _create_target(client)
    policy = _create_policy(client, max_rounds=1, suffix="budget")
    task = _create_task(client, target["target_id"], policy["policy_id"], key="budget-key-0001")
    worker = _create_worker(client, name="budget-worker")
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    claim = client.post("/api/v1/agent-security/worker/claim", headers=headers, json={}).json()
    stopped = client.post(
        f"/api/v1/agent-security/worker/tasks/{task['task_id']}/heartbeat",
        headers=headers,
        json={"lease_token": claim["lease_token"], "usage": {"rounds": 2}},
    )
    assert stopped.status_code == 200
    assert stopped.json() == {
        "continue_allowed": False,
        "status": "blocked",
        "stop_reason": "budget.max_rounds_exceeded",
        "lease_expires_at": None,
    }

    transient = models.SecurityScanTask(
        policy_snapshot_json=json_dumps(
            {
                "max_rounds": 100,
                "max_tokens": 100,
                "max_cost_microunits": 100,
                "max_concurrent_requests": 100,
                "max_response_bytes": 100,
                "max_duration_seconds": 1,
            }
        ),
        rounds_used=0,
        tokens_used=0,
        cost_microunits_used=0,
        max_concurrency_seen=0,
        response_bytes_used=0,
        started_at=datetime.utcnow() - timedelta(seconds=2),
    )
    assert security_scans._budget_reason(transient, datetime.utcnow()) == "budget.max_duration_seconds_exceeded"


def test_errors_are_stable_and_localized_and_actions_are_audited(p1_api):
    client, session_factory, _, _ = p1_api
    zh = client.post(
        "/api/v1/agent-security/targets",
        json={"name": "private-zh", "target_type": "http", "endpoint_url": "https://127.0.0.1"},
    )
    en = client.post(
        "/api/v1/agent-security/targets",
        headers={"Accept-Language": "en-US"},
        json={"name": "private-en", "target_type": "http", "endpoint_url": "https://127.0.0.1"},
    )
    assert zh.json()["error_code"] == en.json()["error_code"] == "agent_security.non_routable_address_forbidden"
    assert "环回" in zh.json()["detail"]
    assert "Loopback" in en.json()["detail"]

    target = _create_target(client)
    credential = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"credential_type": "bearer", "secret": "audit-secret"},
    )
    policy = _create_policy(client, suffix="audit")
    task = _create_task(client, target["target_id"], policy["policy_id"], key="audit-key-0001")
    client.post(f"/api/v1/agent-security/tasks/{task['task_id']}/export")
    client.post(f"/api/v1/agent-security/tasks/{task['task_id']}/cancel")
    client.post(f"/api/v1/agent-security/credentials/{credential.json()['credential_id']}/revoke")

    with session_factory() as db:
        event_types = {row.event_type for row in db.query(models.SecurityAuditEvent).all()}
    assert {
        "security_target.created",
        "security_target.credential_rotated",
        "security_target.credential_revoked",
        "security_scan_policy.created",
        "security_scan_task.created",
        "security_scan_report.exported",
        "security_scan_task.cancelled",
    }.issubset(event_types)


def test_p1_routes_require_user_or_worker_credentials(p1_api):
    client, _, _, _ = p1_api
    worker_missing = client.post("/api/v1/agent-security/worker/claim", json={})
    assert worker_missing.status_code == 401
    assert worker_missing.json()["error_code"] == "agent_security.worker_token_missing"

    active_override = client.app.dependency_overrides.pop(auth.get_current_active_user)
    try:
        unauthenticated = client.get("/api/v1/agent-security/targets")
    finally:
        client.app.dependency_overrides[auth.get_current_active_user] = active_override
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error_code"] == "http.401"


def test_independent_worker_executes_control_plane_protocol_without_target_secret():
    worker_path = "services/agent-security-worker/worker.py"
    spec = importlib.util.spec_from_file_location("agent_security_worker", worker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def fake_request(path, payload):
        calls.append((path, payload))
        if path.endswith("/heartbeat"):
            return {"continue_allowed": True}
        return {"status": "succeeded"}

    module._request = fake_request
    module._complete_control_plane_validation(
        {
            "task": {
                "task_id": "asj_test",
                "usage": {
                    "rounds": 22,
                    "tokens": 481423,
                    "cost_microunits": 1200,
                    "concurrent_requests": 3,
                    "response_bytes": 4096,
                },
            },
            "lease_token": "lease-token",
        }
    )
    assert [path for path, _ in calls] == [
        "/worker/tasks/asj_test/heartbeat",
        "/worker/tasks/asj_test/complete",
    ]
    assert calls[0][1]["usage"] == {
        "rounds": 23,
        "tokens": 481423,
        "cost_microunits": 1200,
        "concurrent_requests": 3,
        "response_bytes": 4096,
    }
    assert calls[1][1]["cases"][0]["external_case_id"] == "p1-control-plane"
    source = Path(worker_path).read_text(encoding="utf-8")
    assert "secret_encrypted" not in source
    assert "unprotect_secret" not in source


def test_security_target_classification_supports_legacy_and_new_asset_types(p1_api, monkeypatch):
    client, session_factory, _, _ = p1_api
    monkeypatch.setattr(settings, "AIG_SERVICE_URL", "")
    monkeypatch.setattr(settings, "AIG_SERVICE_TOKEN", None)

    legacy = _create_target(client, name="Legacy OpenAI target")
    assert legacy["target_type"] == "openai"
    assert legacy["asset_type"] == "agent"
    assert legacy["connector_type"] == "openai_compatible"
    assert legacy["engine_available"] is True

    agent = _create_target(
        client,
        name="Explicit custom Agent",
        target_type=None,
        asset_type="agent",
        connector_type="custom_http",
    )
    assert agent["target_type"] == "http"
    assert agent["asset_type"] == "agent"
    assert agent["connector_type"] == "custom_http"

    llm = _create_target(
        client,
        name="Red-team model",
        target_type=None,
        asset_type="llm",
        connector_type="openai_compatible",
        config={"model": "mock-model", "chat_completions_path": "/v1/chat/completions"},
    )
    assert llm["asset_type"] == "llm"
    assert llm["connector_type"] == "openai_compatible"
    assert llm["engine_available"] is False
    assert llm["engine_error_code"] == "agent_security.aig_service_unavailable"

    infrastructure = _create_target(
        client,
        name="Explicit infrastructure endpoints",
        target_type=None,
        asset_type="ai_infrastructure",
        connector_type="network_endpoint",
        endpoint_url="https://8.8.8.8",
        config={"endpoints": ["https://8.8.8.8", "https://1.1.1.1"]},
    )
    assert infrastructure["asset_type"] == "ai_infrastructure"
    assert infrastructure["connector_type"] == "network_endpoint"
    assert infrastructure["config"]["endpoints"] == ["https://8.8.8.8", "https://1.1.1.1"]
    assert infrastructure["resolved_ips"] == ["8.8.8.8", "1.1.1.1"]
    assert infrastructure["engine_available"] is False

    with session_factory() as db:
        gateway = models.McpGateway(
            slug="classification-gateway",
            name="Classification Gateway",
            environment="test",
            status="active",
        )
        db.add(gateway)
        db.commit()
        db.refresh(gateway)
        gateway_id = gateway.id
    mcp = _create_target(
        client,
        name="Registered MCP Gateway",
        target_type=None,
        asset_type="mcp",
        connector_type="mcp_gateway",
        endpoint_url="mcp-gateway://classification-gateway",
        config={"gateway_id": gateway_id},
    )
    assert mcp["asset_type"] == "mcp"
    assert mcp["connector_type"] == "mcp_gateway"
    assert mcp["target_type"] == "mcp_gateway"
    assert mcp["engine_available"] is True


def test_aig_engine_availability_requires_authenticated_live_health(monkeypatch):
    class HealthResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int):
            return self.payload

    requests = []

    def healthy(request, timeout):
        requests.append((request, timeout))
        return HealthResponse(b'{"status":"ok","engine":{"tag":"v4.6.0"}}')

    monkeypatch.setattr(settings, "AIG_SERVICE_URL", "http://aig-health.internal:8093/")
    monkeypatch.setattr(settings, "AIG_SERVICE_TOKEN", "health-test-token")
    monkeypatch.setattr(security_scans.urllib.request, "urlopen", healthy)
    security_scans._AIG_HEALTH_CACHE.update({"key": None, "expires_at": 0.0, "available": False})

    assert security_scans._aig_engine_available() is True
    assert len(requests) == 1
    assert requests[0][0].full_url == "http://aig-health.internal:8093/healthz"
    assert requests[0][0].get_header("Authorization") == "Bearer health-test-token"
    assert requests[0][1] == 2.0
    assert security_scans._aig_engine_available() is True
    assert len(requests) == 1, "the short health cache should avoid repeated service calls"

    monkeypatch.setattr(settings, "AIG_SERVICE_TOKEN", "different-token")
    monkeypatch.setattr(
        security_scans.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: HealthResponse(b'{"status":"ok"}'),
    )
    assert security_scans._aig_engine_available() is False

    monkeypatch.setattr(settings, "AIG_SERVICE_TOKEN", "network-error-token")
    monkeypatch.setattr(
        security_scans.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(security_scans.urllib.error.URLError("down")),
    )
    assert security_scans._aig_engine_available() is False


def test_security_target_rejects_invalid_asset_connector_and_secret_config(p1_api):
    client, _, _, _ = p1_api
    mismatch = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "Invalid model connector",
            "asset_type": "llm",
            "connector_type": "dify",
            "endpoint_url": "https://8.8.8.8/v1",
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error_code"] == "agent_security.asset_connector_mismatch"

    secret_header = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "Leaky model target",
            "asset_type": "llm",
            "connector_type": "openai_compatible",
            "endpoint_url": "https://8.8.8.8/v1",
            "config": {
                "model": "mock-model",
                "headers": {"Authorization": "Bearer plaintext-secret"},
            },
        },
    )
    assert secret_header.status_code == 422
    assert secret_header.json()["error_code"] == "agent_security.secret_config_forbidden"
    assert "plaintext-secret" not in secret_header.text


def test_infrastructure_target_validates_every_explicit_endpoint(p1_api):
    client, _, _, _ = p1_api
    private_secondary = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "Private secondary endpoint",
            "asset_type": "ai_infrastructure",
            "connector_type": "network_endpoint",
            "endpoint_url": "https://8.8.8.8",
            "config": {"endpoints": ["https://8.8.8.8", "https://10.0.0.2:11434"]},
        },
    )
    assert private_secondary.status_code == 422
    assert private_secondary.json()["error_code"] == "agent_security.infra_private_address_forbidden"

    insecure_secondary = client.post(
        "/api/v1/agent-security/targets",
        json={
            "name": "Insecure secondary endpoint",
            "asset_type": "ai_infrastructure",
            "connector_type": "network_endpoint",
            "endpoint_url": "https://8.8.8.8",
            "config": {"endpoints": ["https://8.8.8.8", "http://1.1.1.1:11434"]},
        },
    )
    assert insecure_secondary.status_code == 422
    assert insecure_secondary.json()["error_code"] == "agent_security.insecure_transport_forbidden"


def test_scan_kind_is_checked_against_asset_and_engine_availability(p1_api, monkeypatch):
    client, _, _, _ = p1_api
    monkeypatch.setattr(settings, "AIG_SERVICE_URL", "")
    monkeypatch.setattr(settings, "AIG_SERVICE_TOKEN", None)
    policy = _create_policy(client, suffix="target-classification")
    agent = _create_target(client, name="Agent classification target")
    llm = _create_target(
        client,
        name="Unavailable LLM engine",
        target_type=None,
        asset_type="llm",
        connector_type="openai_compatible",
        config={"model": "mock-model"},
    )

    mismatch = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": agent["target_id"],
            "policy_id": policy["policy_id"],
            "idempotency_key": "classification-mismatch",
            "scan_kind": "llm_redteam_scan",
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"] == "agent_security.scan_kind_asset_mismatch"

    unavailable = client.post(
        "/api/v1/agent-security/tasks",
        json={
            "target_id": llm["target_id"],
            "policy_id": policy["policy_id"],
            "idempotency_key": "classification-engine-unavailable",
            "scan_kind": "llm_redteam_scan",
        },
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "agent_security.aig_service_unavailable"


def test_llm_task_preview_contract_and_upstream_session_survive_worker_retry(p1_api, monkeypatch):
    client, session_factory, _, _ = p1_api
    monkeypatch.setattr(settings, "AIG_SERVICE_URL", "http://aig-scan-service:8093")
    monkeypatch.setattr(settings, "AIG_SERVICE_TOKEN", "internal-service-token")
    monkeypatch.setattr(security_scans, "_aig_engine_available", lambda: True)
    target = _create_target(
        client,
        name="LLM retry target",
        target_type=None,
        asset_type="llm",
        connector_type="openai_compatible",
        config={"model": "target-model", "chat_completions_path": "/v1/chat/completions"},
    )
    policy = _create_policy(client, suffix="llm-session-retry", retry_backoff_seconds=0)
    request = {
        "target_id": target["target_id"],
        "policy_id": policy["policy_id"],
        "scan_kind": "llm_redteam_scan",
        "num_prompts": 3,
        "techniques": ["Raw", "Roleplay"],
    }
    preview = client.post("/api/v1/agent-security/tasks/preview", json=request)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["cases"]) == 3
    assert preview.json()["limitations"] == ["attack_resisted_is_prompt_scoped", "evaluator_required"]

    created = client.post(
        "/api/v1/agent-security/tasks",
        json={**request, "idempotency_key": "llm-session-retry-0001"},
    )
    assert created.status_code == 200, created.text
    detail = client.get(f"/api/v1/agent-security/tasks/{created.json()['task_id']}")
    assert detail.json()["report_contract"]["scan_kind"] == "llm_redteam_scan"

    worker_response = client.post(
        "/api/v1/agent-security/workers",
        json={"name": "llm-worker", "capabilities": ["llm_redteam_scan"], "max_concurrency": 1},
    )
    headers = {"Authorization": f"Bearer {worker_response.json()['token_once']}"}
    first_claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["llm_redteam_scan"]},
    ).json()
    assert first_claim["scan_options"]["datasets"] == ["JailBench-Tiny"]
    assert "upstream_session_id" not in first_claim["scan_options"]

    heartbeat = client.post(
        f"/api/v1/agent-security/worker/tasks/{created.json()['task_id']}/heartbeat",
        headers=headers,
        json={
            "lease_token": first_claim["lease_token"],
            "session_state": "aig-upstream-session-1",
            "usage": {"rounds": 2, "tokens": 100},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    failed = client.post(
        f"/api/v1/agent-security/worker/tasks/{created.json()['task_id']}/complete",
        headers=headers,
        json={
            "lease_token": first_claim["lease_token"],
            "status": "failed",
            "retryable": True,
            "error_code": "agent_security.aig_service_unavailable",
            "usage": {"rounds": 2, "tokens": 100},
        },
    )
    assert failed.json()["status"] == "pending"

    second_claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["llm_redteam_scan"]},
    ).json()
    assert second_claim["scan_options"]["upstream_session_id"] == "aig-upstream-session-1"
    assert second_claim["task"]["usage"]["rounds"] == 2
    assert second_claim["task"]["usage"]["tokens"] == 100
    with session_factory() as db:
        stored = db.query(models.SecurityScanTask).filter_by(task_id=created.json()["task_id"]).one()
        assert stored.session_state_encrypted.startswith("enc:")
        assert "aig-upstream-session-1" not in stored.session_state_encrypted


def test_infrastructure_task_requires_explicit_http_authorization_and_builds_endpoint_cases(p1_api, monkeypatch):
    client, _, _, _ = p1_api
    monkeypatch.setattr(settings, "AIG_SERVICE_URL", "http://aig-scan-service:8093")
    monkeypatch.setattr(settings, "AIG_SERVICE_TOKEN", "internal-service-token")
    monkeypatch.setattr(security_scans, "_aig_engine_available", lambda: True)
    target = _create_target(
        client,
        name="HTTP infrastructure target",
        target_type=None,
        asset_type="ai_infrastructure",
        connector_type="network_endpoint",
        endpoint_url="http://8.8.8.8:11434",
        allow_insecure_transport=True,
        config={"endpoints": ["http://8.8.8.8:11434", "https://1.1.1.1"]},
    )
    policy = _create_policy(client, suffix="infra-http")
    payload = {
        "target_id": target["target_id"],
        "policy_id": policy["policy_id"],
        "scan_kind": "ai_infrastructure_vulnerability_scan",
    }
    denied = client.post("/api/v1/agent-security/tasks/preview", json=payload)
    assert denied.status_code == 409
    assert denied.json()["error_code"] == "agent_security.infra_target_forbidden"

    preview = client.post(
        "/api/v1/agent-security/tasks/preview",
        json={**payload, "http_authorized": True, "scan_timeout_seconds": 15, "scan_concurrency": 2},
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["cases"]) == 2
    assert preview.json()["tool_plan"]["mode"] == "active_network_probe"


def test_dify_inventory_multi_purpose_credentials_and_snapshot_api(p1_api):
    client, session_factory, _, _ = p1_api
    target = _create_target(
        client,
        name="Dify inventory target",
        target_type=None,
        asset_type="agent",
        connector_type="dify",
        endpoint_url="https://8.8.8.8/v1",
        config={
            "app_id": "app-inventory",
            "workspace_id": "workspace-sensitive-001",
            "console_base_url": "https://8.8.8.8",
            "declared_intent": "Analyze approved business data",
        },
    )
    app_credential = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"purpose": "dify_app_api", "credential_type": "api_key", "secret": "app-secret-value"},
    )
    console_credential = client.post(
        f"/api/v1/agent-security/targets/{target['target_id']}/credentials",
        json={"purpose": "dify_console_api", "credential_type": "bearer", "secret": "console-admin-secret"},
    )
    assert app_credential.status_code == console_credential.status_code == 200
    assert app_credential.json()["version"] == 1
    assert console_credential.json()["version"] == 2
    assert console_credential.json()["secret_once"] is None
    assert "console-admin-secret" not in console_credential.text
    refreshed_target = client.get(f"/api/v1/agent-security/targets/{target['target_id']}").json()
    assert {item["purpose"] for item in refreshed_target["credentials"]} == {
        "dify_app_api", "dify_console_api"
    }
    assert "app-secret-value" not in json.dumps(refreshed_target)
    assert "console-admin-secret" not in json.dumps(refreshed_target)

    policy = _create_policy(client, suffix="dify-inventory", execution_mode="read_only")
    dsl_text = Path("demo/dify-control-plane-poc/example-app.yml").read_text()
    request = {
        "target_id": target["target_id"],
        "policy_id": policy["policy_id"],
        "scan_kind": "dify_asset_inventory",
        "inventory_source": "manual_dsl",
        "manual_dsl": dsl_text,
        "include_prompt_text": True,
    }
    preview = client.post("/api/v1/agent-security/tasks/preview", json=request)
    assert preview.status_code == 200, preview.text
    assert any(item["case_key"] == "dify-inventory:dsl" for item in preview.json()["cases"])
    created = client.post(
        "/api/v1/agent-security/tasks",
        json={
            **request,
            "idempotency_key": "dify-inventory-manual-0001",
            "preview_fingerprint": preview.json()["preview_fingerprint"],
        },
    )
    assert created.status_code == 200, created.text
    worker = client.post(
        "/api/v1/agent-security/workers",
        json={"name": "dify-inventory-worker", "capabilities": ["dify_asset_inventory"], "max_concurrency": 1},
    ).json()
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["dify_asset_inventory"]},
    ).json()
    assert claim["task"]["task_id"] == created.json()["task_id"]
    assert claim["credentials"] == []
    assert "manual_dsl" in claim["scan_options"]
    assert dsl_text not in json.dumps(claim["task"])

    adapter_path = Path("services/agent-security-worker/dify_inventory_adapter.py")
    spec = importlib.util.spec_from_file_location("dify_inventory_adapter_e2e", adapter_path)
    assert spec and spec.loader
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    result = adapter.execute_dify_inventory(
        claim, {}, lambda _usage: {"continue_allowed": True}, initial_usage={}
    )
    completed = client.post(
        f"/api/v1/agent-security/worker/tasks/{created.json()['task_id']}/complete",
        headers=headers,
        json={"lease_token": claim["lease_token"], **result},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded"

    detail = client.get(f"/api/v1/agent-security/tasks/{created.json()['task_id']}").json()
    assert detail["inventory"]["available"] is True
    assert any(item["artifact_type"] == "dify-asset-inventory" for item in detail["artifacts"])
    inventory = client.get(f"/api/v1/agent-security/tasks/{created.json()['task_id']}/inventory").json()
    assert inventory["agent_profile"]["workspace_id"]["value"] == "work…-001"
    assert inventory["agent_profile"]["intent"]["status"] == "declared"
    assert inventory["coverage"]["dsl"] == "completed"
    assert any(item["asset_type"] == "prompt" for item in inventory["items"])
    filtered_inventory = client.get(
        f"/api/v1/agent-security/tasks/{created.json()['task_id']}/inventory",
        params={"asset_type": "prompt", "source_type": "dsl"},
    ).json()
    prompts = filtered_inventory["items"]
    assert prompts and all(item["asset_type"] == "prompt" for item in prompts)
    assert filtered_inventory["summary"] == inventory["summary"]
    assert all(item["sensitive_content_available"] for item in prompts)
    prompt_content = client.get(
        f"/api/v1/agent-security/tasks/{created.json()['task_id']}/inventory/items/{prompts[0]['item_id']}/content",
        params={"confirm": True},
    )
    assert prompt_content.status_code == 200
    assert prompt_content.json()["content"] in dsl_text
    inventory_artifact = next(item for item in detail["artifacts"] if item["artifact_type"] == "dify-asset-inventory")
    durable_artifact = client.get(
        f"/api/v1/agent-security/tasks/{created.json()['task_id']}/artifacts/{inventory_artifact['artifact_id']}/content"
    )
    assert durable_artifact.status_code == 200
    assert "Answer only from approved support material." not in durable_artifact.json()["content"]
    assert "sensitive_content" not in durable_artifact.json()["content"]
    comparison = client.get(
        f"/api/v1/agent-security/tasks/{created.json()['task_id']}/inventory/compare"
    ).json()
    assert comparison["status"] == "baseline_unavailable"

    with session_factory() as db:
        assert db.query(models.SecurityAssetInventorySnapshot).count() == 1
        assert db.query(models.SecurityAssetInventoryItem).count() == len(inventory["items"])
        assert db.query(models.SecurityAssetInventoryEvidence).count() >= len(inventory["items"])
        artifact = db.query(models.SecurityScanArtifact).filter_by(task_id=created.json()["task_id"]).one()
        assert artifact.content_encrypted.startswith("enc:")
        assert "Customer support assistant" not in artifact.content_encrypted

        snapshot = db.query(models.SecurityAssetInventorySnapshot).one()
        server = models.McpServer(
            slug="inventory-search", name="Inventory Search", endpoint="https://mcp.example.test/mcp",
            status="active", health_status="healthy", last_checked_at=datetime.utcnow(),
        )
        db.add(server)
        db.flush()
        server_id = server.id
        db.add(models.SecurityAssetInventoryItem(
            item_id="aii_mcp_binding_candidate", snapshot_id=snapshot.snapshot_id,
            asset_id="tool:mcp-node:provider/mcp:search", asset_type="mcp", name="search",
            configured=True, discovered=True, executed=False, verification_status="unverified",
            details_json=json.dumps({"provider_id": "provider/mcp", "tool_name": "search"}),
            fingerprint="a" * 64,
        ))
        db.commit()

    options = client.get(
        f"/api/v1/agent-security/targets/{target['target_id']}/dify-mcp-binding-options"
    )
    assert options.status_code == 200, options.text
    assert options.json()["providers"] == [{
        "provider_id": "provider/mcp", "tool_names": ["search"], "server_id": None,
        "binding_status": "unbound", "source": "latest_dify_asset_snapshot",
    }]
    assert options.json()["servers"][0]["health_status"] == "healthy"
    assert options.json()["servers"][0]["tool_count"] == 0

    target_config = dict(refreshed_target["config"])
    target_config["mcp_bindings"] = [{"provider_id": "provider/mcp", "server_id": 999999}]
    missing_server = client.patch(
        f"/api/v1/agent-security/targets/{target['target_id']}", json={"config": target_config},
    )
    assert missing_server.status_code == 404
    assert missing_server.json()["error_code"] == "dify_inventory.mcp_server_not_found"

    target_config["mcp_bindings"] = [{"provider_id": "provider/mcp", "server_id": server_id}]
    saved_missing_tool = client.patch(
        f"/api/v1/agent-security/targets/{target['target_id']}", json={"config": target_config},
    )
    assert saved_missing_tool.status_code == 200, saved_missing_tool.text
    missing_tool_options = client.get(
        f"/api/v1/agent-security/targets/{target['target_id']}/dify-mcp-binding-options"
    ).json()
    assert missing_tool_options["summary"] == {
        "verified": 0, "unbound": 0, "configured_tool_not_discovered": 1,
    }
    missing_tool_preview = client.post("/api/v1/agent-security/tasks/preview", json=request)
    assert missing_tool_preview.status_code == 200, missing_tool_preview.text
    assert missing_tool_preview.json()["tool_plan"]["dify_mcp_bindings"] == missing_tool_options["summary"]

    with session_factory() as db:
        db.add(models.McpTool(
            server_id=server_id, name="search", exposed_name="inventory-search__search",
            input_schema_json="{}", schema_hash="b" * 64, enabled=True,
        ))
        db.commit()
    verified_options = client.get(
        f"/api/v1/agent-security/targets/{target['target_id']}/dify-mcp-binding-options"
    ).json()
    assert verified_options["summary"] == {
        "verified": 1, "unbound": 0, "configured_tool_not_discovered": 0,
    }

    changed_dsl_text = dsl_text.replace(
        "Answer only from approved support material.",
        "Answer only from approved support material. Cite the source.",
    )
    changed_request = {**request, "manual_dsl": changed_dsl_text}
    changed_preview = client.post("/api/v1/agent-security/tasks/preview", json=changed_request).json()
    changed_task = client.post(
        "/api/v1/agent-security/tasks",
        json={
            **changed_request,
            "idempotency_key": "dify-inventory-manual-0002",
            "preview_fingerprint": changed_preview["preview_fingerprint"],
        },
    ).json()
    changed_claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["dify_asset_inventory"]},
    ).json()
    changed_result = adapter.execute_dify_inventory(
        changed_claim, {}, lambda _usage: {"continue_allowed": True}, initial_usage={}
    )
    changed_completed = client.post(
        f"/api/v1/agent-security/worker/tasks/{changed_task['task_id']}/complete",
        headers=headers,
        json={"lease_token": changed_claim["lease_token"], **changed_result},
    )
    assert changed_completed.status_code == 200, changed_completed.text
    changed_comparison = client.get(
        f"/api/v1/agent-security/tasks/{changed_task['task_id']}/inventory/compare"
    ).json()
    assert changed_comparison["status"] == "completed"
    assert changed_comparison["baseline_task_id"] == created.json()["task_id"]
    assert any(asset_id.startswith("prompt:llm-1:system:") for asset_id in changed_comparison["changed"])

    envelope_spec = importlib.util.spec_from_file_location(
        "dify_inventory_envelope_test",
        Path("services/agent-security-worker/credential_envelope.py"),
    )
    assert envelope_spec and envelope_spec.loader
    envelope_module = importlib.util.module_from_spec(envelope_spec)
    sys.modules[envelope_spec.name] = envelope_module
    envelope_spec.loader.exec_module(envelope_module)
    key_pair = envelope_module.generate_worker_key_pair()
    registered = client.post(
        "/api/v1/agent-security/worker/key",
        headers=headers,
        json={"algorithm": envelope_module.ALGORITHM, "public_key": key_pair.public_key},
    )
    assert registered.status_code == 200, registered.text
    console_request = {
        "target_id": target["target_id"], "policy_id": policy["policy_id"],
        "scan_kind": "dify_asset_inventory", "inventory_source": "console_api",
    }
    console_preview = client.post("/api/v1/agent-security/tasks/preview", json=console_request).json()
    console_task = client.post(
        "/api/v1/agent-security/tasks",
        json={**console_request, "idempotency_key": "dify-inventory-console-0001", "preview_fingerprint": console_preview["preview_fingerprint"]},
    ).json()
    console_claim = client.post(
        "/api/v1/agent-security/worker/claim", headers=headers,
        json={"capabilities": ["dify_asset_inventory"]},
    ).json()
    assert console_claim["task"]["task_id"] == console_task["task_id"]
    assert [item["purpose"] for item in console_claim["credentials"]] == ["dify_console_api"]
    sealed = console_claim["credentials"][0]
    assert "console-admin-secret" not in json.dumps(console_claim)
    assert envelope_module.decrypt_secret_envelope(
        sealed["secret_envelope"], key_pair, worker_id=worker["worker_id"],
        task_id=console_task["task_id"], credential_id=sealed["credential_id"],
    ) == "console-admin-secret"


def test_dify_intent_inference_is_admin_authorized_worker_scoped_and_budgeted(p1_api, monkeypatch):
    client, session_factory, state, users = p1_api
    target = _create_target(
        client,
        name="Dify intent target",
        target_type=None,
        asset_type="agent",
        connector_type="dify",
        endpoint_url="https://8.8.8.8/v1",
        config={
            "app_id": "app-intent",
            "workspace_id": "workspace-intent",
            "console_base_url": "https://8.8.8.8",
            "declared_intent": "Administrator declaration",
        },
    )
    policy = _create_policy(client, suffix="dify-intent", execution_mode="read_only", max_tokens=5000)
    dsl_text = Path("demo/dify-control-plane-poc/example-app.yml").read_text()
    request = {
        "target_id": target["target_id"],
        "policy_id": policy["policy_id"],
        "scan_kind": "dify_asset_inventory",
        "inventory_source": "manual_dsl",
        "manual_dsl": dsl_text,
        "infer_agent_intent": True,
    }

    state["user"] = users["auditor"]
    denied = client.post("/api/v1/agent-security/tasks/preview", json=request)
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "dify_inventory.intent_inference_access_denied"
    state["user"] = users["admin"]

    missing_model = client.post(
        "/api/v1/agent-security/tasks/preview",
        json={**request, "intent_inference_model": "missing-model"},
    )
    assert missing_model.status_code == 422
    assert missing_model.json()["error_code"] == "dify_inventory.intent_model_invalid"

    with session_factory() as db:
        provider = models.ModelProvider(
            name="intent-provider", base_url="https://model.example.test/v1", enabled=True,
        )
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(
            provider_id=provider.id, name="intent-model", enabled=True, is_default=True,
        ))
        db.commit()

    selected_request = {**request, "intent_inference_model": "intent-model"}
    preview = client.post("/api/v1/agent-security/tasks/preview", json=selected_request)
    assert preview.status_code == 200, preview.text
    created = client.post(
        "/api/v1/agent-security/tasks",
        json={
            **selected_request,
            "idempotency_key": "dify-intent-inference-0001",
            "preview_fingerprint": preview.json()["preview_fingerprint"],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["scan_options"]["infer_agent_intent"] is True
    assert created.json()["scan_options"]["intent_inference_model"] == "intent-model"

    worker = client.post(
        "/api/v1/agent-security/workers",
        json={"name": "dify-intent-worker", "capabilities": ["dify_asset_inventory"], "max_concurrency": 1},
    ).json()
    headers = {"Authorization": f"Bearer {worker['token_once']}"}
    claim = client.post(
        "/api/v1/agent-security/worker/claim",
        headers=headers,
        json={"capabilities": ["dify_asset_inventory"]},
    ).json()
    assert claim["task"]["task_id"] == created.json()["task_id"]

    async def mock_inference(
        _db, *, requested_model, summary, owner_user_id, owner_group_id,
    ):
        assert requested_model == "intent-model"
        assert owner_user_id == users["admin"].id
        assert owner_group_id is None
        assert summary["content_policy"]["prompt_is_untrusted_data"] is True
        assert "raw-secret-prompt" not in json.dumps(summary)
        return {
            "status": "inferred",
            "intent": "Generate verified analytics queries",
            "confidence": 0.82,
            "evidence_summary": ["The workflow includes query generation and result validation"],
            "model": "intent-model",
            "provider": "intent-provider",
            "rule_version": "intent-inference@1",
            "usage_delta": {"rounds": 1, "tokens": 321, "cost_microunits": 9, "response_bytes": 144},
        }

    monkeypatch.setattr(security_scans, "run_intent_inference", mock_inference)
    inference = client.post(
        f"/api/v1/agent-security/worker/tasks/{claim['task']['task_id']}/infer-intent",
        headers=headers,
        json={
            "lease_token": claim["lease_token"],
            "usage": {"rounds": 2, "tokens": 100, "cost_microunits": 0, "concurrent_requests": 1, "response_bytes": 500},
            "summary": {
                "application": {"name": "Analytics"},
                "prompts": [{"text": "redacted workflow purpose"}],
                "content_policy": {
                    "prompt_is_untrusted_data": True,
                    "knowledge_base_content_included": False,
                    "full_dsl_included": False,
                },
            },
        },
    )
    assert inference.status_code == 200, inference.text
    payload = inference.json()
    assert payload["status"] == "inferred"
    assert payload["usage"] == {
        "rounds": 3,
        "tokens": 421,
        "cost_microunits": 9,
        "concurrent_requests": 1,
        "response_bytes": 644,
    }
    with session_factory() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=claim["task"]["task_id"]).one()
        assert task.tokens_used == 421
        assert task.rounds_used == 3
        audit_payload = "\n".join(row.details_json for row in db.query(models.SecurityAuditEvent).all())
        assert "redacted workflow purpose" not in audit_payload
        assert "raw-secret-prompt" not in audit_payload


def test_dify_intent_inference_applies_owner_privacy_policy_without_reversible_mapping(
    p1_api, monkeypatch,
):
    _client, session_factory, _state, users = p1_api
    captured = {}

    async def mock_upstream(_db, _model, payload):
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": json.dumps({
                "intent": "Analyze internal project information",
                "confidence": 0.75,
                "evidence_summary": ["The workflow references an internal project"],
            })}}],
            "usage": {"total_tokens": 20},
        }

    monkeypatch.setattr(dify_intent_inference, "_call_upstream", mock_upstream)
    with session_factory() as db:
        provider = models.ModelProvider(
            name="privacy-intent-provider", base_url="https://model.example.test/v1", enabled=True,
        )
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(
            provider_id=provider.id, name="privacy-intent-model", enabled=True, is_default=True,
        ))
        db.add(models.PrivacyPolicy(
            group_id=users["group"].id,
            name="intent-owner-policy",
            enabled=True,
            entity_types_json=json.dumps(["INTERNAL_PROJECT_CODE"]),
            entity_rules_json=json.dumps({"INTERNAL_PROJECT_CODE": r"RISK-[0-9]{4}"}),
            detect_system_messages=True,
        ))
        db.commit()

        result = asyncio.run(dify_intent_inference.run_intent_inference(
            db,
            requested_model="privacy-intent-model",
            summary={
                "application": {"name": "Project RISK-2048 analysis"},
                "prompts": [{"role": "system", "text": "Review RISK-2048"}],
                "content_policy": {
                    "prompt_is_untrusted_data": True,
                    "knowledge_base_content_included": False,
                    "full_dsl_included": False,
                },
            },
            owner_user_id=users["owner"].id,
        ))

        serialized_payload = json.dumps(captured["payload"], ensure_ascii=False)
        assert result["status"] == "inferred"
        assert "RISK-2048" not in serialized_payload
        assert "<INTERNAL_PROJECT_CODE:REDACTED>" in serialized_payload
        assert db.query(models.PseudonymMapping).count() == 0


def test_dify_intent_inference_repairs_invalid_output_once_and_accumulates_usage(
    p1_api, monkeypatch,
):
    _client, session_factory, _state, _users = p1_api
    calls = []
    first_output = (
        '{"intent":"Analyze approved data","confidence":0.81,'
        '"evidence_summary":["Workflow validates queries"],"explanation":"must never be persisted"}'
    )

    async def mock_upstream(_db, _model, payload):
        calls.append(payload)
        if len(calls) == 1:
            raise HTTPException(status_code=400, detail="structured output unsupported")
        if len(calls) == 2:
            return {
                "choices": [{"message": {"content": first_output}}],
                "usage": {"total_tokens": 11, "cost_microunits": 2},
            }
        return {
            "choices": [{"message": {"content": [{
                "type": "text",
                "text": "INTENT: Analyze approved data\nCONFIDENCE: 0.81\nEVIDENCE:\n- Workflow validates queries",
            }]}}],
            "usage": {"total_tokens": 17, "cost_microunits": 3},
        }

    monkeypatch.setattr(dify_intent_inference, "_call_upstream", mock_upstream)
    with session_factory() as db:
        provider = models.ModelProvider(name="repair-provider", base_url="https://model.example.test/v1", enabled=True)
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(
            provider_id=provider.id, name="repair-model", enabled=True, is_default=True,
        ))
        db.commit()
        result = asyncio.run(dify_intent_inference.run_intent_inference(
            db,
            requested_model="repair-model",
            summary={
                "application": {"name": "Analytics"},
                "content_policy": {
                    "prompt_is_untrusted_data": True,
                    "knowledge_base_content_included": False,
                    "full_dsl_included": False,
                },
            },
        ))
        assert result["status"] == "inferred"
        assert result["confidence"] == 0.81
        assert result["usage_delta"]["rounds"] == 3
        assert result["usage_delta"]["tokens"] == 28
        assert result["usage_delta"]["cost_microunits"] == 5
        assert result["usage_delta"]["response_bytes"] > len(first_output)
        assert calls[0]["response_format"]["type"] == "json_schema"
        assert calls[1]["response_format"]["type"] == "json_object"
        assert "response_format" not in calls[2]
        assert "untrusted_previous_output" not in calls[2]["messages"][1]["content"]
        assert "minimized_inventory" in calls[2]["messages"][1]["content"]
        assert "Analytics" in calls[2]["messages"][1]["content"]
        persisted = "\n".join(
            str(value) for row in db.identity_map.values() for value in vars(row).values()
        )
        assert first_output not in persisted


def test_dify_intent_inference_two_invalid_outputs_return_diagnostic_without_raw_content(
    p1_api, monkeypatch,
):
    _client, session_factory, _state, _users = p1_api
    raw_outputs = ["invalid-one", "INTENT: ok\nCONFIDENCE: 2\nEVIDENCE:\n- evidence"]

    async def mock_upstream(_db, _model, _payload):
        content = raw_outputs.pop(0)
        return {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 5}}

    monkeypatch.setattr(dify_intent_inference, "_call_upstream", mock_upstream)
    with session_factory() as db:
        provider = models.ModelProvider(name="invalid-provider", base_url="https://model.example.test/v1", enabled=True)
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(provider_id=provider.id, name="invalid-model", enabled=True, is_default=True))
        db.commit()
        result = asyncio.run(dify_intent_inference.run_intent_inference(
            db,
            requested_model="invalid-model",
            summary={
                "content_policy": {
                    "prompt_is_untrusted_data": True,
                    "knowledge_base_content_included": False,
                    "full_dsl_included": False,
                },
            },
        ))
        assert result["status"] == "unavailable"
        assert result["error_code"] == "dify_inventory.intent_output_invalid"
        assert result["diagnostic_code"] == "confidence_invalid"
        assert result["usage_delta"]["rounds"] == 2
        assert result["usage_delta"]["tokens"] == 10
        assert "invalid-one" not in json.dumps(result)
