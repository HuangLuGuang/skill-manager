from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent_manager.runtime_trace import RuntimeTraceClient, RuntimeTraceError
from backend import auth, models
from backend.api_errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from backend.config import settings
from backend.routers import llm_gateway, mcp_gateway, runtime_governance, runtime_traces
from backend.runtime_trace_schemas import RuntimeTraceBatchCreate, RuntimeTraceEventInput, RuntimeTraceInternalEvent
from backend.services import runtime_traces as trace_service
from backend.sqlite_db import Base, get_db


@pytest.fixture()
def trace_api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'runtime-trace.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "SECRET_KEY", "runtime-trace-test-key")
    monkeypatch.setattr(settings, "AUDIT_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "audit.pem"))
    monkeypatch.setattr(settings, "SECURITY_AUDIT_EXPORT_PATH", None)
    monkeypatch.setattr(settings, "RUNTIME_TRACE_ENABLED", True)
    plain = "amat_runtime_trace_test"
    with session_factory() as db:
        password_hash = auth.get_password_hash("test-password")
        admin = models.User(username="admin", hashed_password=password_hash, role="admin")
        auditor = models.User(username="auditor", hashed_password=password_hash, role="security_auditor")
        privacy = models.User(username="privacy", hashed_password=password_hash, role="privacy_auditor")
        owner = models.User(username="owner", hashed_password=password_hash, role="user")
        other = models.User(username="other", hashed_password=password_hash, role="user")
        group = models.UserGroup(name="trace-owners")
        db.add_all([admin, auditor, privacy, owner, other, group])
        db.flush()
        db.add(models.UserGroupMember(user_id=owner.id, group_id=group.id))
        token = models.AccessToken(
            name="trace-agent",
            token_type="agent_runtime",
            token_hash=hashlib.sha256(plain.encode()).hexdigest(),
            token_prefix=plain[:12],
            scopes_json='["runtime:trace"]',
            bound_agent_id="agent-trace-1",
            user_id=owner.id,
            group_id=group.id,
            allowed_ips_json="[]",
        )
        db.add(token)
        db.commit()
        for row in (admin, auditor, privacy, owner, other, group):
            db.refresh(row)
        users = {row.username: row for row in (admin, auditor, privacy, owner, other)}

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
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[auth.get_current_active_user] = current_user
    app.dependency_overrides[auth.get_current_security_reader] = current_user
    app.dependency_overrides[auth.get_current_admin_user] = current_user
    app.include_router(runtime_traces.router, prefix="/api")
    client = TestClient(app)
    yield client, session_factory, state, users, plain
    client.close()
    engine.dispose()


def _create(client: TestClient, plain: str) -> str:
    response = client.post(
        "/api/v1/runtime-traces",
        headers={"Authorization": f"Bearer {plain}"},
        json={"session_id": "session-1", "tenant_id": "caller-value"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["agent_id"] == "agent-trace-1"
    assert response.json()["tenant_id"].isdigit()
    return response.json()["trace_id"]


def _batch(trace_id: str):
    return {
        "schema_version": "runtime-trace@1",
        "batch_id": "batch-1",
        "events": [
            {
                "event_id": "event-1",
                "event_time": "2030-01-01T00:00:10Z",
                "source": "agent_sdk",
                "type": "turn.start",
                "turn_id": "turn-1",
                "risk_codes": ["prompt_injection", "future_runtime_signal"],
                "payload": {"email": "alice@example.com", "password": "secret-value"},
            },
            {
                "event_id": "event-2",
                "event_time": "2020-01-01T00:00:00Z",
                "source": "agent_sdk",
                "type": "tool.call",
                "turn_id": "turn-1",
                "step_id": "step-1",
                "call_id": "call-parent",
                "tool_name": "search",
                "payload": {"query": "customer 13800138000"},
            },
            {
                "event_id": "event-3",
                "event_time": "2020-01-01T00:00:01Z",
                "source": "agent_sdk",
                "type": "tool.result",
                "turn_id": "turn-1",
                "step_id": "step-1",
                "call_id": "call-child",
                "parent_call_id": "call-parent",
                "tool_name": "search",
                "payload": {"result": "ok"},
            },
            {
                "event_id": "event-4",
                "event_time": "2020-01-01T00:00:02Z",
                "source": "knowledge_connector",
                "type": "knowledge.retrieval",
                "turn_id": "turn-1",
                "step_id": "step-1",
                "payload": {"knowledge_base": "kb", "document_id": "doc", "chunk_ids": ["c1"]},
            },
        ],
    }


def test_runtime_trace_batch_idempotency_server_sequence_and_permissions(trace_api):
    client, session_factory, state, users, plain = trace_api
    trace_id = _create(client, plain)
    headers = {"Authorization": f"Bearer {plain}"}
    created = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=_batch(trace_id))
    assert created.status_code == 200, created.text
    assert created.json()["accepted_count"] == 4

    replay = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=_batch(trace_id))
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True

    events = client.get(f"/api/v1/runtime-traces/{trace_id}/events").json()["items"]
    assert [item["seq"] for item in events] == [1, 2, 3, 4]
    assert events[0]["event_time"].startswith("2030-")
    assert events[1]["event_time"].startswith("2020-")
    assert events[2]["parent_call_id"] == "call-parent"
    assert events[0]["payload"]["email"] == "[REDACTED]"
    assert events[0]["payload"]["password"] == "[REDACTED]"
    assert events[0]["risk_codes"] == ["prompt_injection", "future_runtime_signal", "ASI01"]
    assert events[0]["risk_mapping"]["status"] == "partial"
    assert events[0]["risk_mapping"]["mapping_version"] == "agent-manager-asi-map@1"
    trace = client.get(f"/api/v1/runtime-traces/{trace_id}").json()
    assert {"prompt_injection", "future_runtime_signal", "ASI01"} <= set(trace["risk_codes"])
    assert trace["risk_mapping_version"] == "agent-manager-asi-map@1"
    turn_tool_events = client.get(
        f"/api/v1/runtime-traces/{trace_id}/events",
        params={"turn_id": "turn-1", "tool_name": "search"},
    ).json()
    assert turn_tool_events["total"] == 2
    assert {item["event_id"] for item in turn_tool_events["items"]} == {"event-2", "event-3"}
    assert client.get(
        f"/api/v1/runtime-traces/{trace_id}/events",
        params={"errors_only": True},
    ).json()["total"] == 0

    state["user"] = users["other"]
    assert client.get(f"/api/v1/runtime-traces/{trace_id}").status_code == 403
    assert client.get(f"/api/v1/runtime-traces/{trace_id}/events/event-1/raw-payload").status_code == 403

    state["user"] = users["auditor"]
    assert client.get(f"/api/v1/runtime-traces/{trace_id}").status_code == 200
    assert client.get(f"/api/v1/runtime-traces/{trace_id}/events/event-1/raw-payload").status_code == 403

    state["user"] = users["privacy"]
    raw = client.get(f"/api/v1/runtime-traces/{trace_id}/events/event-1/raw-payload")
    assert raw.status_code == 200, raw.text
    assert raw.json()["payload"]["email"] == "alice@example.com"
    with session_factory() as db:
        assert db.query(models.SecurityAuditEvent).filter(
            models.SecurityAuditEvent.event_type == "runtime_trace.raw_payload_viewed"
        ).count() == 1


def test_trace_severity_uses_explicit_producer_classification(trace_api):
    client, session_factory, _state, _users, plain = trace_api
    trace_id = _create(client, plain)
    headers = {"Authorization": f"Bearer {plain}"}
    response = client.post(
        f"/api/v1/runtime-traces/{trace_id}/events:batch",
        headers=headers,
        json={
            "batch_id": "severity-explicit",
            "events": [{
                "event_id": "severity-event",
                "event_time": "2026-08-29T00:00:00Z",
                "source": "agent_sdk",
                "type": "security.finding",
                "severity": "high",
                "risk_codes": ["a-code-containing-high-text"],
                "payload": {},
            }],
        },
    )
    assert response.status_code == 200, response.text
    with session_factory() as db:
        trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=trace_id).one()
        event = db.query(models.RuntimeTraceEvent).filter_by(event_id="severity-event").one()
        assert trace.risk_level == "high"
        assert json.loads(event.risk_mapping_json)["severity"] == "high"

    unknown_trace = _create(client, plain)
    unknown = client.post(
        f"/api/v1/runtime-traces/{unknown_trace}/events:batch",
        headers=headers,
        json={
            "batch_id": "severity-unknown",
            "events": [{
                "event_id": "unknown-severity-event",
                "event_time": "2026-08-29T00:00:00Z",
                "source": "agent_sdk",
                "type": "security.finding",
                "risk_codes": ["high-looking-but-unclassified"],
                "payload": {},
            }],
        },
    )
    assert unknown.status_code == 200, unknown.text
    with session_factory() as db:
        trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=unknown_trace).one()
        assert trace.risk_level == "low"


def test_ingest_batch_can_join_an_outer_transaction(trace_api):
    _client, session_factory, _state, _users, _plain = trace_api
    with session_factory() as db:
        trace = trace_service.create_trace(
            db, tenant_id="tenant", agent_id="agent", session_id="session",
            owner_user_id=None, owner_group_id=None, created_by="test", commit=False,
            trace_id="outer-transaction-trace",
        )
        result = trace_service.ingest_batch(
            db, trace,
            RuntimeTraceBatchCreate(batch_id="outer-batch", events=[RuntimeTraceEventInput(
                event_id="outer-event", event_time=datetime.utcnow(), source="agent_sdk",
                type="message.user", payload={},
            )]),
            commit=False,
        )
        assert result["accepted_count"] == 1
        db.rollback()
    with session_factory() as db:
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id="outer-transaction-trace").count() == 0


def test_multi_batch_transaction_serializes_concurrent_writer(trace_api, monkeypatch):
    _client, factory, _state, _users, _plain = trace_api
    with factory() as db:
        for trace_id in ("multi-writer", "other-writer"):
            trace_service.create_trace(
                db, tenant_id="test", agent_id=None, session_id=trace_id,
                trace_id=trace_id, owner_user_id=None, owner_group_id=None, created_by="test",
            )
    first_written = Event()
    other_started = Event()
    other_entered = Event()
    locked_ingest = trace_service._ingest_batch_locked

    def observe_ingest(db, trace, *args, **kwargs):
        if trace.trace_id == "other-writer":
            other_entered.set()
        return locked_ingest(db, trace, *args, **kwargs)

    monkeypatch.setattr(trace_service, "_ingest_batch_locked", observe_ingest)

    def batch(event_id):
        return RuntimeTraceBatchCreate(batch_id=event_id, events=[RuntimeTraceEventInput(
            event_id=event_id, event_time=datetime.utcnow(), source="agent_sdk", type="message.user",
        )])

    def multi_writer():
        with factory() as db, trace_service.ingest_transaction(db):
            trace = db.query(models.RuntimeTraceSession).filter_by(trace_id="multi-writer").one()
            trace_service.ingest_batch(db, trace, batch("first"), commit=False)
            first_written.set()
            assert other_started.wait(2)
            # Give the competing request a chance to enter its write path.
            assert not other_entered.wait(0.1)
            trace_service.ingest_batch(db, trace, batch("second"), commit=False)

    def other_writer():
        assert first_written.wait(2)
        with factory() as db:
            trace = db.query(models.RuntimeTraceSession).filter_by(trace_id="other-writer").one()
            other_started.set()
            trace_service.ingest_batch(db, trace, batch("other"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(multi_writer), executor.submit(other_writer)]
        for future in futures:
            future.result(timeout=5)
    assert other_entered.is_set()
    with factory() as db:
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id="multi-writer").one().event_count == 2
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id="other-writer").one().event_count == 1


def test_legacy_event_and_batch_fingerprints_replay_after_severity_upgrade(trace_api):
    client, session_factory, _state, _users, plain = trace_api
    trace_id = _create(client, plain)
    event = RuntimeTraceEventInput(
        event_id="legacy-event", event_time=datetime.utcnow(), source="agent_sdk",
        type="message.user", payload={"content": "legacy"},
    )
    legacy_event = event.model_dump(mode="json")
    legacy_event.pop("severity", None)
    legacy_batch = {"schema_version": "runtime-trace@1", "batch_id": "legacy-batch", "events": [legacy_event]}
    with session_factory() as db:
        trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=trace_id).one()
        db.add(models.RuntimeTraceEvent(
            event_id=event.event_id,
            content_fingerprint=trace_service._fingerprint(legacy_event),
            trace_id=trace_id, seq=1, schema_version="runtime-trace@1",
            event_time=event.event_time, received_at=datetime.utcnow(), tenant_id=trace.tenant_id,
            agent_id=trace.agent_id, session_id=trace.session_id, source=event.source,
            type=event.type, risk_codes_json="[]", risk_mapping_json="{}",
        ))
        db.add(models.RuntimeTraceIngestBatch(
            trace_id=trace_id, batch_id="legacy-batch",
            request_fingerprint=trace_service._fingerprint(legacy_batch), accepted_count=1,
            duplicate_count=0, first_seq=1, last_seq=1,
        ))
        trace.event_count = 1
        trace.next_seq = 2
        db.commit()
    headers = {"Authorization": f"Bearer {plain}"}
    replay = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=legacy_batch)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    new_batch = {**legacy_batch, "batch_id": "new-batch"}
    duplicate = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=new_batch)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["accepted_count"] == 0
    assert duplicate.json()["duplicate_count"] == 1


def test_severity_conflict_and_maximum_aggregation_are_explicit(trace_api):
    client, session_factory, _state, _users, plain = trace_api
    trace_id = _create(client, plain)
    headers = {"Authorization": f"Bearer {plain}"}
    base = {
        "event_id": "severity-conflict-event", "event_time": "2026-08-29T00:00:00Z",
        "source": "agent_sdk", "type": "security.finding", "payload": {},
    }
    high = {"batch_id": "severity-high", "events": [{**base, "severity": "high", "risk_codes": ["critical-looking"]}]}
    assert client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=high).status_code == 200
    low = {"batch_id": "severity-low", "events": [{**base, "severity": "low", "risk_codes": ["critical-looking"]}]}
    conflict = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=low)
    assert conflict.status_code == 409

    same_batch_trace = _create(client, plain)
    same_batch = client.post(
        f"/api/v1/runtime-traces/{same_batch_trace}/events:batch", headers=headers,
        json={"batch_id": "same-batch-severity", "events": [
            {**base, "event_id": "same-batch-event", "severity": "high", "risk_codes": ["same-signal"]},
            {**base, "event_id": "same-batch-event", "severity": "low", "risk_codes": ["same-signal"]},
        ]},
    )
    assert same_batch.status_code == 409

    lower_trace = _create(client, plain)
    explicit_low = {"batch_id": "explicit-low", "events": [{**base, "event_id": "explicit-low-event", "severity": "low", "risk_codes": ["critical"]}]}
    response = client.post(f"/api/v1/runtime-traces/{lower_trace}/events:batch", headers=headers, json=explicit_low)
    assert response.status_code == 200, response.text
    lower_event = {**base, "event_id": "explicit-lower-event", "severity": "low", "risk_codes": ["another-signal"]}
    lower_batch = client.post(
        f"/api/v1/runtime-traces/{lower_trace}/events:batch", headers=headers,
        json={"batch_id": "explicit-lower", "events": [lower_event]},
    )
    assert lower_batch.status_code == 200, lower_batch.text
    with session_factory() as db:
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id=trace_id).one().risk_level == "high"
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id=lower_trace).one().risk_level == "low"


def test_runtime_publishers_and_sdk_transmit_severity(monkeypatch):
    published = []
    monkeypatch.setattr(llm_gateway, "publish_events_best_effort", lambda _db, events: published.extend(events))
    llm_gateway._publish_model_runtime_trace(
        None, key=None, trace_context={"session_id": "s"}, tenant_id="t", request_id="r",
        model_name="model", prompt_security={"risk_level": "HIGH", "risk_codes": ["prompt_injection"]},
        request_payload={},
    )
    assert published and published[-1].severity == "high"

    published.clear()
    token = SimpleNamespace(token_type="agent_runtime", bound_agent_id="agent", group_id=None, user_id=None, id=1)
    monkeypatch.setattr(mcp_gateway, "publish_events_best_effort", lambda _db, events: published.extend(events))
    mcp_gateway._publish_mcp_runtime_trace(
        None, token=token, meta={}, request_id="r", gateway_slug="g", tool_name="tool", severity="high",
        error="denied", error_code="mcp_dangerous_tool_unprotected",
    )
    assert published and all(event.severity == "high" for event in published)

    published.clear()
    task = SimpleNamespace(trace_id="tr", tenant_id="t", agent_id="a", session_id="s", user_id="1", task_id="task")
    monkeypatch.setattr(runtime_governance, "publish_events_best_effort", lambda _db, events: published.extend(events))
    runtime_governance._publish_governance_event(None, task, "policy.decision", status="deny", payload={}, severity="medium")
    assert published and published[0].severity == "medium"

    sdk = RuntimeTraceClient("http://example.test", "token")
    sdk.emit("security.finding", risk_codes=["signal"])
    assert "severity" not in sdk._events[-1]
    sdk.emit("security.finding", severity="high", risk_codes=["signal"])
    assert sdk._events[-1]["severity"] == "high"


def test_runtime_trace_ten_thousand_event_cursor_pagination(trace_api):
    client, session_factory, _state, users, _plain = trace_api
    now = datetime.utcnow()
    trace_id = "trace-large-10000"
    with session_factory() as db:
        db.add(
            models.RuntimeTraceSession(
                trace_id=trace_id,
                tenant_id="large-test",
                agent_id="agent-large",
                session_id="session-large",
                owner_user_id=users["admin"].id,
                status="completed",
                schema_version="runtime-trace@1",
                completeness="full",
                has_agent_events=True,
                has_model_events=False,
                has_mcp_events=False,
                has_runtime_events=False,
                has_knowledge_events=False,
                event_count=10_000,
                next_seq=10_001,
                risk_level="info",
                risk_codes_json="[]",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        db.bulk_save_objects([
            models.RuntimeTraceEvent(
                event_id=f"large-event-{seq}",
                content_fingerprint=f"fingerprint-{seq}",
                trace_id=trace_id,
                seq=seq,
                schema_version="runtime-trace@1",
                event_time=now,
                received_at=now,
                tenant_id="large-test",
                agent_id="agent-large",
                session_id="session-large",
                turn_id=f"turn-{(seq - 1) // 100}",
                source="agent_sdk",
                type="tool.result",
                tool_name="search" if seq % 2 == 0 else "read",
                risk_codes_json="[]",
                created_at=now,
            )
            for seq in range(1, 10_001)
        ])
        db.commit()

    first = client.get(
        f"/api/v1/runtime-traces/{trace_id}/events",
        params={"tool_name": "search", "page_size": 200},
    )
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert first_page["total"] == 5_000
    assert len(first_page["items"]) == 200
    assert [item["seq"] for item in first_page["items"][:3]] == [2, 4, 6]
    assert first_page["has_more"] is True
    assert first_page["next_after_seq"] == 400
    assert all(item["payload"] is None for item in first_page["items"])

    second = client.get(
        f"/api/v1/runtime-traces/{trace_id}/events",
        params={"tool_name": "search", "after_seq": first_page["next_after_seq"], "page_size": 200},
    )
    assert second.status_code == 200, second.text
    second_page = second.json()
    assert second_page["total"] == 5_000
    assert second_page["items"][0]["seq"] == 402
    assert second_page["next_after_seq"] == 800
    assert {item["event_id"] for item in first_page["items"]}.isdisjoint(
        item["event_id"] for item in second_page["items"]
    )


def test_p7_long_session_max_batch_and_large_payload_ingest_are_bounded(trace_api):
    client, session_factory, _state, _users, plain = trace_api
    trace_id = _create(client, plain)
    headers = {"Authorization": f"Bearer {plain}"}
    with session_factory() as db:
        token = db.query(models.AccessToken).filter_by(name="trace-agent").one()
        token.max_body_kb = 10_240
        db.commit()
    now = datetime.utcnow().isoformat()
    events = [
        {
            "event_id": f"p7-batch-{index:04d}",
            "event_time": now,
            "source": "agent_sdk",
            "type": "tool.result" if index % 2 else "model.response",
            "turn_id": f"turn-{index // 10:03d}",
            "step_id": f"step-{index:04d}",
            "call_id": f"call-{index:04d}",
            "status": "completed",
            "payload": {"summary": "x" * 1024, "index": index},
            "redacted_payload": {"summary": "[REDACTED]", "index": index},
        }
        for index in range(1_000)
    ]
    started = time.perf_counter()
    batch = client.post(
        f"/api/v1/runtime-traces/{trace_id}/events:batch",
        headers=headers,
        json={"batch_id": "p7-max-batch", "events": events},
    )
    batch_elapsed = time.perf_counter() - started
    assert batch.status_code == 200, batch.text
    assert batch.json()["accepted_count"] == 1_000
    assert batch.json()["first_seq"] == 1
    assert batch.json()["last_seq"] == 1_000
    assert batch_elapsed < 30

    large_value = "y" * (4 * 1024 * 1024)
    started = time.perf_counter()
    large = client.post(
        f"/api/v1/runtime-traces/{trace_id}/events:batch",
        headers=headers,
        json={
            "batch_id": "p7-large-payload",
            "events": [
                {
                    "event_id": "p7-large-event",
                    "event_time": now,
                    "source": "agent_sdk",
                    "type": "knowledge.retrieval",
                    "turn_id": "turn-large",
                    "payload": {"private_document": large_value},
                    "redacted_payload": {"private_document": "[REDACTED]"},
                }
            ],
        },
    )
    large_elapsed = time.perf_counter() - started
    assert large.status_code == 200, large.text
    assert large.json()["accepted_count"] == 1
    assert large_elapsed < 30

    page = client.get(
        f"/api/v1/runtime-traces/{trace_id}/events",
        params={"after_seq": 990, "page_size": 20},
    )
    assert page.status_code == 200, page.text
    assert [item["seq"] for item in page.json()["items"]] == list(range(991, 1002))
    with session_factory() as db:
        trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=trace_id).one()
        payload = db.query(models.RuntimeTracePayload).filter_by(event_id="p7-large-event").one()
        assert trace.event_count == 1_001
        assert trace.next_seq == 1_002
        assert payload.size_bytes >= 4 * 1024 * 1024
        assert large_value not in payload.raw_payload_encrypted
        assert large_value not in payload.redacted_json


def test_completeness_query_export_cleanup_and_metrics(trace_api):
    client, session_factory, state, users, plain = trace_api
    trace_id = _create(client, plain)
    client.post(
        f"/api/v1/runtime-traces/{trace_id}/events:batch",
        headers={"Authorization": f"Bearer {plain}"},
        json=_batch(trace_id),
    )
    with session_factory() as db:
        group = db.query(models.UserGroup).filter_by(name="trace-owners").one()
        token = db.query(models.AccessToken).filter_by(name="trace-agent").one()
        llm_gateway._publish_model_runtime_trace(
            db,
            key=token,
            trace_context={
                "trace_id": trace_id,
                "session_id": "session-1",
                "turn_id": "turn-1",
                "step_id": "step-1",
                "call_id": None,
                "parent_call_id": None,
            },
            tenant_id=f"group-{group.id}",
            request_id="request-42",
            model_name="test-model",
            request_payload={"messages": [{"role": "user", "content": "hello"}]},
            response_payload={"choices": [{"message": {"content": "ok"}}]},
            usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            duration_ms=12.5,
            upstream_duration_ms=9.0,
            ttft_ms=4.25,
        )

    detail = client.get(f"/api/v1/runtime-traces/{trace_id}").json()
    assert detail["completeness"] == "full"
    queried = client.get("/api/v1/runtime-traces", params={"request_id": "request-42", "tool_name": "search"})
    assert queried.status_code == 200
    assert queried.json()["total"] == 1
    events = client.get(f"/api/v1/runtime-traces/{trace_id}/events").json()["items"]
    model_response = next(item for item in events if item["type"] == "model.response")
    exact_event = client.get(
        f"/api/v1/runtime-traces/{trace_id}/events",
        params={"event_id": model_response["event_id"], "page_size": 1},
    )
    assert exact_event.status_code == 200
    assert exact_event.json()["total"] == 1
    assert exact_event.json()["items"][0]["event_id"] == model_response["event_id"]
    request_events = client.get(
        f"/api/v1/runtime-traces/{trace_id}/events",
        params={"request_id": "request-42"},
    ).json()
    assert request_events["total"] == 2
    assert {item["type"] for item in request_events["items"]} == {"model.request", "model.response"}
    assert model_response["payload"]["usage"] == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
    assert model_response["payload"]["performance"] == {
        "request_duration_ms": 12.5,
        "upstream_duration_ms": 9.0,
        "platform_duration_ms": 3.5,
        "ttft_ms": 4.25,
    }

    missing_authorization = client.post(
        f"/api/v1/runtime-traces/{trace_id}/exports",
        json={"redaction_level": "raw", "format": "json", "acknowledge_sensitive_content": True},
    )
    assert missing_authorization.status_code == 403
    assert missing_authorization.json()["error_code"] == "runtime_trace.raw_export_authorization_required"

    bad_password = client.post(
        f"/api/v1/runtime-traces/{trace_id}/exports/raw-authorization",
        json={"password": "wrong-password", "acknowledge_sensitive_content": True},
    )
    assert bad_password.status_code == 403
    raw_authorization = client.post(
        f"/api/v1/runtime-traces/{trace_id}/exports/raw-authorization",
        json={"password": "test-password", "acknowledge_sensitive_content": True},
    )
    assert raw_authorization.status_code == 200, raw_authorization.text
    authorization_token = raw_authorization.json()["authorization_token"]
    exported = client.post(
        f"/api/v1/runtime-traces/{trace_id}/exports",
        json={
            "redaction_level": "raw",
            "format": "json",
            "acknowledge_sensitive_content": True,
            "raw_authorization_token": authorization_token,
        },
    )
    assert exported.status_code == 200, exported.text
    downloaded = client.get(f"/api/v1/runtime-traces/exports/{exported.json()['export_id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/json")
    assert "alice@example.com" in downloaded.text
    replayed_authorization = client.post(
        f"/api/v1/runtime-traces/{trace_id}/exports",
        json={
            "redaction_level": "raw",
            "format": "json",
            "acknowledge_sensitive_content": True,
            "raw_authorization_token": authorization_token,
        },
    )
    assert replayed_authorization.status_code == 403
    assert replayed_authorization.json()["error_code"] == "runtime_trace.raw_export_authorization_invalid"

    pdf_export = client.post(
        f"/api/v1/runtime-traces/{trace_id}/exports",
        json={"redaction_level": "redacted", "format": "pdf", "language": "en-US"},
    )
    assert pdf_export.status_code == 200, pdf_export.text
    pdf_download = client.get(f"/api/v1/runtime-traces/exports/{pdf_export.json()['export_id']}/download")
    assert pdf_download.status_code == 200
    assert pdf_download.headers["content-type"].startswith("application/pdf")
    assert pdf_download.content.startswith(b"%PDF-")
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_download.content)).pages)
    assert "Runtime Trace Evidence Report" in pdf_text
    assert "REDACTED PROJECTION" in pdf_text
    assert "alice@example.com" not in pdf_text
    assert client.get("/api/v1/runtime-traces/metrics").json()["event_count"] == 6

    with session_factory() as db:
        event_types = {
            row.event_type
            for row in db.query(models.SecurityAuditEvent)
            .filter(models.SecurityAuditEvent.resource_id == trace_id)
            .all()
        }
        assert "runtime_trace.raw_export_reauthentication_failed" in event_types
        assert "runtime_trace.raw_export_authorized" in event_types
        assert "runtime_trace.exported" in event_types

    with session_factory() as db:
        trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=trace_id).one()
        trace.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.query(models.RuntimeTracePayload).filter_by(trace_id=trace_id).update(
            {models.RuntimeTracePayload.expires_at: trace.expires_at}
        )
        db.commit()
    cleaned = client.post("/api/v1/runtime-traces/maintenance/cleanup")
    assert cleaned.status_code == 200
    assert cleaned.json()["traces"] == 1


def test_gateway_publish_failure_is_non_blocking_and_counted(trace_api, monkeypatch):
    _, session_factory, _, _, _ = trace_api
    before = None
    with session_factory() as db:
        before = trace_service.metrics_snapshot(db)["publish_failures"]
        monkeypatch.setattr(trace_service, "create_trace", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        result = trace_service.publish_events_best_effort(
            db,
            [
                RuntimeTraceInternalEvent(
                    session_id="s",
                    source="model_gateway",
                    type="model.error",
                    payload={"secret": "must-not-be-logged"},
                )
            ],
        )
        assert result is None
        assert trace_service.metrics_snapshot(db)["publish_failures"] == before + 1


def test_partial_completeness_and_conflicting_idempotency_keys(trace_api):
    client, session_factory, _, _, plain = trace_api
    trace_id = _create(client, plain)
    headers = {"Authorization": f"Bearer {plain}"}
    payload = _batch(trace_id)
    assert client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=payload).status_code == 200
    payload["events"][0]["payload"] = {"changed": True}
    conflict = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "runtime_trace.batch_id_conflict"

    spoofed = {
        "batch_id": "spoofed-source",
        "events": [
            {
                "event_id": "spoofed-model-event",
                "event_time": "2026-08-29T00:00:00Z",
                "source": "model_gateway",
                "type": "model.response",
                "payload": {"fake": True},
            }
        ],
    }
    rejected = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=spoofed)
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "runtime_trace.source_not_allowed_for_credential"

    with session_factory() as db:
        token = db.query(models.AccessToken).filter_by(name="trace-agent").one()
        token.max_body_kb = 1
        db.commit()
    oversized = {
        "batch_id": "oversized",
        "events": [
            {
                "event_id": "oversized-event",
                "event_time": "2026-08-29T00:00:00Z",
                "source": "agent_sdk",
                "type": "message.user",
                "payload": {"content": "x" * 2048},
            }
        ],
    }
    too_large = client.post(f"/api/v1/runtime-traces/{trace_id}/events:batch", headers=headers, json=oversized)
    assert too_large.status_code == 413
    assert too_large.json()["error_code"] == "runtime_trace.body_too_large"

    with session_factory() as db:
        existing_count = db.query(models.RuntimeTraceEvent).filter_by(trace_id=trace_id).count()
        assert trace_service.publish_events_best_effort(
            db,
            [
                RuntimeTraceInternalEvent(
                    trace_id=trace_id,
                    tenant_id=str(db.query(models.UserGroup).filter_by(name="trace-owners").one().id),
                    agent_id=None,
                    session_id="session-1",
                    source="model_gateway",
                    type="model.response",
                    payload={"untrusted": True},
                )
            ],
        ) is None
        assert db.query(models.RuntimeTraceEvent).filter_by(trace_id=trace_id).count() == existing_count

        model_trace = trace_service.publish_events_best_effort(
            db,
            [RuntimeTraceInternalEvent(session_id="model-session", source="model_gateway", type="model.error", payload={})],
        )
        mcp_trace = trace_service.publish_events_best_effort(
            db,
            [
                RuntimeTraceInternalEvent(
                    session_id="mcp-session",
                    source="mcp_gateway",
                    type="mcp.error",
                    call_id="mcp-call",
                    payload={},
                )
            ],
        )
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id=model_trace).one().completeness == "model_only"
        assert db.query(models.RuntimeTraceSession).filter_by(trace_id=mcp_trace).one().completeness == "mcp_only"

        gateway_trace = "trc-gateway-only-combined"
        assert trace_service.publish_events_best_effort(
            db,
            [
                RuntimeTraceInternalEvent(
                    trace_id=gateway_trace,
                    session_id="gateway-only-session",
                    source="model_gateway",
                    type="model.response",
                    payload={"status": "ok"},
                )
            ],
        ) == gateway_trace
        assert trace_service.publish_events_best_effort(
            db,
            [
                RuntimeTraceInternalEvent(
                    trace_id=gateway_trace,
                    session_id="gateway-only-session",
                    source="mcp_gateway",
                    type="mcp.result",
                    call_id="gateway-only-call",
                    payload={"status": "ok"},
                )
            ],
        ) == gateway_trace
        combined = db.query(models.RuntimeTraceSession).filter_by(trace_id=gateway_trace).one()
        assert combined.completeness == "gateway_partial"
        assert combined.has_agent_events is False
        combined_events = db.query(models.RuntimeTraceEvent).filter_by(trace_id=gateway_trace).all()
        assert {item.source for item in combined_events} == {"model_gateway", "mcp_gateway"}
        assert all(item.turn_id is None and item.step_id is None for item in combined_events)

    error_traces = client.get("/api/v1/runtime-traces", params={"has_error": True}).json()
    assert error_traces["total"] == 2
    assert {item["trace_id"] for item in error_traces["items"]} == {model_trace, mcp_trace}
    assert client.get(
        f"/api/v1/runtime-traces/{model_trace}/events",
        params={"errors_only": True},
    ).json()["total"] == 1
    turn_traces = client.get("/api/v1/runtime-traces", params={"turn_id": "turn-1"}).json()
    assert turn_traces["total"] == 1
    assert turn_traces["items"][0]["trace_id"] == trace_id


def test_duplicate_event_ids_inside_one_batch_are_deduplicated_or_rejected(trace_api):
    client, session_factory, _, _, plain = trace_api
    trace_id = _create(client, plain)
    headers = {"Authorization": f"Bearer {plain}"}
    event = {
        "event_id": "same-event",
        "event_time": "2026-08-29T00:00:00Z",
        "source": "agent_sdk",
        "type": "message.user",
        "payload": {"content": "same"},
    }
    accepted = client.post(
        f"/api/v1/runtime-traces/{trace_id}/events:batch",
        headers=headers,
        json={"batch_id": "same-event-batch", "events": [event, event]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted_count"] == 1
    assert accepted.json()["duplicate_count"] == 1
    with session_factory() as db:
        assert db.query(models.RuntimeTraceEvent).filter_by(trace_id=trace_id).count() == 1

    other_trace_id = _create(client, plain)
    conflicting = dict(event)
    conflicting["payload"] = {"content": "different"}
    rejected = client.post(
        f"/api/v1/runtime-traces/{other_trace_id}/events:batch",
        headers=headers,
        json={"batch_id": "conflicting-event-batch", "events": [event, conflicting]},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "runtime_trace.event_id_conflict"


def test_ungrouped_trace_writer_cannot_cross_user_boundary(trace_api):
    client, session_factory, _, users, _ = trace_api
    owner_token = "amat_owner_without_group"
    other_token = "amat_other_without_group"
    with session_factory() as db:
        db.add_all(
            [
                models.AccessToken(
                    name="owner-without-group",
                    token_type="agent_runtime",
                    token_hash=hashlib.sha256(owner_token.encode()).hexdigest(),
                    token_prefix=owner_token[:12],
                    scopes_json='["runtime:trace"]',
                    bound_agent_id="agent-trace-1",
                    user_id=users["owner"].id,
                    allowed_ips_json="[]",
                ),
                models.AccessToken(
                    name="other-without-group",
                    token_type="agent_runtime",
                    token_hash=hashlib.sha256(other_token.encode()).hexdigest(),
                    token_prefix=other_token[:12],
                    scopes_json='["runtime:trace"]',
                    bound_agent_id="agent-trace-1",
                    user_id=users["other"].id,
                    allowed_ips_json="[]",
                ),
            ]
        )
        db.commit()

    created = client.post(
        "/api/v1/runtime-traces",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"session_id": "ungrouped-session", "tenant_id": "tenant-a"},
    )
    assert created.status_code == 200, created.text
    denied = client.post(
        f"/api/v1/runtime-traces/{created.json()['trace_id']}/events:batch",
        headers={"Authorization": f"Bearer {other_token}"},
        json={
            "batch_id": "cross-user",
            "events": [
                {
                    "event_id": "cross-user-event",
                    "event_time": "2026-08-29T00:00:00Z",
                    "source": "agent_sdk",
                    "type": "message.user",
                    "payload": {},
                }
            ],
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "runtime_trace.owner_mismatch"


def test_trace_create_rejects_unknown_schema_version(trace_api):
    client, _, _, _, plain = trace_api
    response = client.post(
        "/api/v1/runtime-traces",
        headers={"Authorization": f"Bearer {plain}"},
        json={"schema_version": "runtime-trace@999", "session_id": "bad-schema"},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "runtime_trace.schema_version_unsupported"


def test_sdk_flush_restores_events_after_transport_failure(monkeypatch):
    sdk = RuntimeTraceClient("http://trace.invalid", "token")
    sdk.trace_id = "trc-test"
    sdk.session_id = "session-test"
    sdk.emit("message.user", payload={"content": "must retry"})

    def fail_request(*_args, **_kwargs):
        raise RuntimeTraceError("transport failed")

    monkeypatch.setattr(sdk, "_request", fail_request)
    with pytest.raises(RuntimeTraceError, match="transport failed"):
        sdk.flush()
    assert len(sdk._events) == 1

    monkeypatch.setattr(sdk, "_request", lambda *_args, **_kwargs: {"accepted_count": 1})
    assert sdk.flush()["accepted_count"] == 1
    assert sdk._events == []


def test_trace_retention_and_storage_quotas_are_server_bounded(trace_api, monkeypatch):
    client, session_factory, _, _, plain = trace_api
    headers = {"Authorization": f"Bearer {plain}"}
    excessive_retention = client.post(
        "/api/v1/runtime-traces",
        headers=headers,
        json={"session_id": "retention", "retention_days": 31},
    )
    assert excessive_retention.status_code == 422

    event_trace = _create(client, plain)
    monkeypatch.setattr(trace_service, "MAX_RUNTIME_TRACE_EVENTS", 1)
    event = {
        "event_id": "quota-event-1",
        "event_time": "2026-08-29T00:00:00Z",
        "source": "agent_sdk",
        "type": "message.user",
        "payload": {},
    }
    second = {**event, "event_id": "quota-event-2"}
    event_limited = client.post(
        f"/api/v1/runtime-traces/{event_trace}/events:batch",
        headers=headers,
        json={"batch_id": "event-quota", "events": [event, second]},
    )
    assert event_limited.status_code == 413
    assert event_limited.json()["error_code"] == "runtime_trace.event_quota_exceeded"
    with session_factory() as db:
        assert db.query(models.RuntimeTraceEvent).filter_by(trace_id=event_trace).count() == 0

    payload_trace = _create(client, plain)
    monkeypatch.setattr(trace_service, "MAX_RUNTIME_TRACE_EVENTS", 100_000)
    monkeypatch.setattr(trace_service, "MAX_RUNTIME_TRACE_PAYLOAD_BYTES", 8)
    payload_limited = client.post(
        f"/api/v1/runtime-traces/{payload_trace}/events:batch",
        headers=headers,
        json={
            "batch_id": "payload-quota",
            "events": [{**event, "event_id": "payload-quota-event", "payload": {"content": "too large"}}],
        },
    )
    assert payload_limited.status_code == 413
    assert payload_limited.json()["error_code"] == "runtime_trace.payload_quota_exceeded"


def test_synchronous_trace_export_has_amplification_limits(trace_api, monkeypatch):
    client, _, _, _, plain = trace_api
    trace_id = _create(client, plain)
    client.post(
        f"/api/v1/runtime-traces/{trace_id}/events:batch",
        headers={"Authorization": f"Bearer {plain}"},
        json=_batch(trace_id),
    )
    monkeypatch.setattr(runtime_traces, "MAX_RUNTIME_TRACE_EXPORT_EVENTS", 0)

    response = client.post(f"/api/v1/runtime-traces/{trace_id}/exports", json={"redaction_level": "redacted"})

    assert response.status_code == 413
    assert response.json()["error_code"] == "runtime_trace.export_too_large"
