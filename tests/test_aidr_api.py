import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from backend.routers import aidr
from backend.routers.access_tokens import _hash_token
from backend.sqlite_db import Base, get_db


@pytest.fixture
def service(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'aidr.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, autoflush=False)
    Base.metadata.create_all(engine)
    with factory() as db:
        db.add(models.User(id=1, username="owner", hashed_password="unused", role="admin"))
        for cid in ("one", "two"):
            db.add(models.ManagedClient(client_id=cid, name=cid, hostname=cid, os="darwin", arch="arm64", client_version="test", registered_by="owner" if cid == "one" else "another-owner"))
            db.add(models.AidrDevice(client_id=cid, created_by="owner"))
            db.add(models.AccessToken(name=cid, token_type="client", token_hash=_hash_token("test-" + cid), token_prefix="test", scopes_json='["aidr:heartbeat","aidr:report-events"]', bound_client_id=cid, created_by="owner"))
        db.commit()
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1, username="owner", role="admin")
    app.include_router(aidr.router, prefix="/api")
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def batch():
    vector_path = Path(__file__).parents[1] / "scanner/internal/aidr/agentlog/testdata/contracts.json"
    event = next(x["event"] for x in json.loads(vector_path.read_text()) if x["valid"])
    return {"schema_version": 1, "records": [{"sequence": "1", "kind": "event", "record_id": event["logical_event_id"], "payload": event}]}


def submit(client, value=None, *, key=None, credential="one", target="one", extra_headers=None):
    raw = json.dumps(value or batch(), separators=(",", ":")).encode()
    headers = {"authorization": "Bearer test-" + credential, "idempotency-key": key or hashlib.sha256(raw).hexdigest(), "x-aidr-stream-id": "a" * 32, "content-type": "application/json", **(extra_headers or {})}
    return client.post(f"/api/v1/clients/{target}/aidr/events:batch", content=raw, headers=headers)


def test_batch_replay_conflict_and_projection(service):
    client, factory = service
    for _ in range(3):
        result = submit(client)
        assert result.status_code == 200, result.text
        assert result.json()["durable"] is True
    items = client.get("/api/v1/clients/one/aidr/events").json()["items"]
    assert len(items) == 1 and items[0]["event"]["record_offset"] == "9007199254740993"
    changed = batch()
    changed["records"][0]["payload"]["tool"] = "AnotherTool"
    result = submit(client, changed, key=result.json()["batch_id"])
    assert result.status_code == 409 and result.json()["error_code"] == "aidr.idempotency_conflict"
    result = submit(client, changed)
    assert result.status_code == 409 and result.json()["error_code"] == "aidr.event_conflict"
    with factory() as db:
        assert db.query(models.AidrBatch).count() == 1
        assert db.query(models.AidrEvent).count() == 1


def test_frozen_batch_with_cursor_tool_binding_and_legacy_replay(service):
    client, factory = service
    source = "b" * 64
    cursor = dict(schema_version=1, parser_version="agentlog/1", source_id=source,
                  file_identity="owned", generation="1", discarding_oversized_record=False,
                  discard_start="0", offset="100", anchor="c" * 64,
                  session_id="owned-session", turn_id="owned-turn", agent_version="0.160.0",
                  since="2026-10-04T00:00:00Z", gap_codes=[],
                  call_turns=[{"call": "owned-call", "turn": "owned-turn", "ambiguous": False, "tool": "exec"}])
    coverage = dict(gaps=[], gap_details_truncated=False, status="complete", reason_codes=[],
                    records=2, ignored=0, filtered=0, skipped_bytes=0, bytes=100)
    value = batch()
    value["records"].append({"sequence": "2", "kind": "coverage", "record_id": source + ":1",
                             "payload": {"source_id": source, "revision": "1", "cursor": cursor, "coverage": coverage}})
    original = json.dumps(value, separators=(",", ":")).encode()
    for _ in range(2):
        response = submit(client, value)
        assert response.status_code == 200, response.text
        ack = response.json()
        assert ack["durable"] and ack["accepted"] == 2
        assert ack["digest"] == hashlib.sha256(original).hexdigest()
    legacy = batch()
    legacy_cursor = {**cursor, "call_turns": [{"call": "old-call", "turn": "owned-turn", "ambiguous": False}]}
    legacy["records"].append({"sequence": "3", "kind": "coverage", "record_id": source + ":2",
                              "payload": {"source_id": source, "revision": "2", "cursor": legacy_cursor, "coverage": coverage}})
    assert submit(client, legacy).status_code == 200
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 1
        assert db.query(models.AidrBatch).count() == 2
        assert db.query(models.AidrCoverageRecord).count() == 2
        latest = json.loads(db.query(models.AidrSource).filter_by(source_id=source).one().payload_json)
        assert "tool" not in latest["cursor"]["call_turns"][0]


def test_device_binding_and_credential_restrictions(service):
    client, factory = service
    assert submit(client).status_code == 200
    assert submit(client, target="two").status_code == 403
    assert submit(client, target="missing").status_code == 403
    for field, value, code in [
        ("scopes_json", '["aidr:heartbeat"]', "credential.scope_missing"),
        ("expires_at", datetime.utcnow() - timedelta(seconds=1), "credential.expired"),
        ("status", "revoked", "credential.invalid_or_disabled"),
        ("allowed_ips_json", '["192.0.2.1"]', "credential.ip_not_allowed"),
        ("bound_client_id", None, "aidr.device_binding_mismatch"),
    ]:
        with factory() as db:
            token = db.query(models.AccessToken).filter_by(name="one").one()
            old = getattr(token, field)
            setattr(token, field, value)
            db.commit()
        response = submit(client)
        assert response.status_code == 403 and response.json()["error_code"] == code
        with factory() as db:
            setattr(db.query(models.AccessToken).filter_by(name="one").one(), field, old)
            db.commit()


def test_no_raw_fields_or_unbounded_compression(service):
    client, factory = service
    value = batch()
    value["records"][0]["payload"]["arguments"] = "synthetic-private-marker"
    response = submit(client, value)
    assert response.status_code == 422
    assert "synthetic-private-marker" not in response.text
    assert submit(client, extra_headers={"content-encoding": "gzip"}).status_code == 415
    raw = b" " * ((1 << 20) + 1)
    assert client.post("/api/v1/clients/one/aidr/events:batch", content=raw, headers={"authorization": "Bearer test-one", "idempotency-key": "a"*64, "x-aidr-stream-id": "a"*32}).status_code == 413
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 0


def test_concurrent_duplicate_batch(service):
    client, factory = service
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: submit(client), range(3)))
    assert [r.status_code for r in results] == [200, 200, 200]
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 1
        assert db.query(models.AidrBatch).count() == 1


def test_heartbeat_configuration_and_pause_resume(service):
    client, factory = service
    with factory() as db:
        db.delete(db.get(models.AidrDevice, "one"))
        db.commit()
    assert submit(client).status_code == 403
    assert client.put("/api/v1/clients/one/aidr/configuration", json={"enabled": True}).status_code == 200
    body = {"stream_id": "a"*32, "capabilities": [], "queued_records": 4, "logical_events": 3, "evicted_event_payloads": 1}
    response = client.post("/api/v1/clients/one/aidr/heartbeat", json=body, headers={"authorization": "Bearer test-one"})
    assert response.status_code == 200 and response.json()["schema_version"] == 2
    state = client.get("/api/v1/clients/one/aidr/status").json()
    assert state["online"] and state["health"]["queued_records"] == 4
    assert submit(client).status_code == 200
    assert client.put("/api/v1/clients/one/aidr/configuration", json={"enabled": False}).status_code == 200
    assert submit(client).json()["error_code"] == "aidr.reporting_disabled"
    # Reporting pause leaves authenticated health and policy delivery available.
    assert client.post("/api/v1/clients/one/aidr/heartbeat", json=body, headers={"authorization": "Bearer test-one"}).status_code == 200
    policy_request = {"stream_id": "a" * 32, "last_sequence": "1"}
    assert client.post("/api/v1/clients/one/aidr/audit-policy", json=policy_request, headers={"authorization": "Bearer test-one"}).status_code == 200
    assert client.post("/api/v1/clients/one/aidr/state-migration", json={}, headers={"authorization": "Bearer test-one"}).status_code == 200
    assert client.post("/api/v1/clients/one/aidr/audit-policy", json=policy_request, headers={"authorization": "Bearer test-two"}).status_code == 403
    with factory() as db:
        token = db.query(models.AccessToken).filter_by(name="one").one()
        token.status = "disabled"
        db.commit()
    assert client.post("/api/v1/clients/one/aidr/heartbeat", json=body, headers={"authorization": "Bearer test-one"}).status_code == 403
    with factory() as db:
        db.query(models.AccessToken).filter_by(name="one").one().status = "active"
        db.commit()
    assert client.put("/api/v1/clients/one/aidr/configuration", json={"enabled": True}).status_code == 200
    assert submit(client).status_code == 200
    with factory() as db:
        assert db.query(models.AidrEvent).count() == 1
        assert db.query(models.UserGroup).count() == 0
        assert db.query(models.AccessToken).filter_by(name="one").one().group_id is None


def test_device_ownership(service):
    client, factory = service
    for endpoint in ("status", "events", "sources"):
        assert client.get(f"/api/v1/clients/two/aidr/{endpoint}").status_code == 404
    assert client.put("/api/v1/clients/two/aidr/configuration", json={"enabled": True}).status_code == 404


def test_real_jwt_read_only_role_and_device_boundary(service):
    from backend import iam
    client, factory = service
    assert submit(client).status_code == 200
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    with factory() as db:
        iam.initialize(db)
        db.add(models.Role(name="aidr_test_reader", display_name="AIDR test reader", default_path="/clients"))
        db.flush()
        db.add(models.RolePermission(role_name="aidr_test_reader", permission_code="clients:view"))
        user = db.get(models.User, 1)
        user.role = "aidr_test_reader"
        user.current_session_id = "test-session"
        db.commit()
    token = auth.create_access_token({"sub": "owner", "session_id": "test-session"})
    headers = {"Authorization": "Bearer " + token}
    response = client.get("/api/v1/clients/one/aidr/events", headers=headers)
    assert response.status_code == 200, response.text
    assert set(response.json()["items"][0]["event"]) == set(batch()["records"][0]["payload"])
    assert client.put("/api/v1/clients/one/aidr/configuration", headers=headers, json={"enabled": False}).status_code == 403
    assert client.get("/api/v1/clients/two/aidr/events", headers=headers).status_code == 404
    assert client.get("/api/v1/clients/one/aidr/events").status_code == 401


def test_out_of_order_coverage_and_conflict(service):
    client, factory = service
    def coverage(revision, status):
        reasons = ["aidr_log_record_too_large"] if status == "partial" else []
        payload = {"source_id": "a"*64, "revision": str(revision),
                   "cursor": {"schema_version": 1, "parser_version": "agentlog/1", "source_id": "a"*64,
                              "file_identity": "1:2", "generation": "1", "discarding_oversized_record": False,
                              "discard_start": "0", "offset": "2990", "anchor": "b"*64,
                              "session_id": "test", "turn_id": "", "agent_version": "2.1.220",
                              "since": "2026-09-23T00:00:00Z", "gap_codes": reasons},
                   "coverage": {"status": status, "gaps": None, "gap_details_truncated": False,
                                "reason_codes": reasons, "records": 10, "ignored": 0, "filtered": 0,
                                "skipped_bytes": 0, "bytes": 2990}}
        return {"schema_version": 1, "records": [{"sequence": str(revision), "kind": "coverage", "record_id": "a"*64+":"+str(revision), "payload": payload}]}
    assert submit(client, coverage(2, "partial")).status_code == 200
    assert submit(client, coverage(1, "complete")).status_code == 200
    page = client.get("/api/v1/clients/one/aidr/sources").json()
    assert page["items"][0]["revision"] == "2"
    assert page["items"][0]["coverage"]["status"] == "partial"
    result = submit(client, coverage(2, "complete"))
    assert result.status_code == 409 and result.json()["error_code"] == "aidr.coverage_conflict"
    with factory() as db:
        assert db.query(models.AidrCoverageRecord).count() == 2
        assert db.query(models.AidrBatch).count() == 2


def test_legacy_migration_proof_uses_device_auth(service):
    client, factory = service
    path = '/api/v1/clients/one/aidr/state-migration'
    headers = {'authorization':'Bearer test-one'}
    assert client.post(path, headers=headers).json() == {'schema_version':2, 'client_id':'one', 'legacy_suffix':None}
    with factory() as db:
        db.add(models.AidrLegacyDestination(client_id='one', suffix='17'))
        db.commit()
    assert client.post(path, headers=headers).json()['legacy_suffix'] == '17'
    assert client.post(path, headers={'authorization':'Bearer test-two'}).status_code == 403
    with factory() as db:
        db.query(models.AccessToken).filter_by(name='one').one().scopes_json='["aidr:heartbeat"]'
        db.commit()
    assert client.post(path, headers=headers).json()['error_code'] == 'credential.scope_missing'


def test_discovery_progress_remains_separate_from_transport(service):
    client, _ = service
    body = {"stream_id": "a"*32, "capabilities": [], "queued_records": 0, "logical_events": 0, "evicted_event_payloads": 0,
            "discovery": [{"agent": "codex", "status": "partial", "reason_codes": ["aidr_log_discovery_budget"],
                           "progress": {"known_sources": 240, "pending_sources": 80, "pending_directories": 2,
                                        "scanned_entries": 64, "status": "partial", "reason_codes": ["aidr_log_discovery_budget"]}}]}
    url = "/api/v1/clients/one/aidr/heartbeat"
    assert client.post(url, json=body, headers={"authorization": "Bearer test-one"}).status_code == 200
    state = client.get("/api/v1/clients/one/aidr/status").json()
    assert state["online"] is True
    assert state["health"]["discovery"][0]["progress"]["pending_sources"] == 80
    body["discovery"][0]["progress"]["scanned_entries"] = 10001
    assert client.post(url, json=body, headers={"authorization": "Bearer test-one"}).status_code == 422
