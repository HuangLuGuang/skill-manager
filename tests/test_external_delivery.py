import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from httpx import AsyncClient

from backend.external_access_models import (ExternalResultEvent, ExternalGatewayEvent, ExternalDelivery,
    ExternalDeliveryEndpoint, ExternalDeliveryAttempt, ExternalPlatform)
from backend.routers import external_deliveries
from backend.services import external_delivery as service
from backend.security_scan_controls import unprotect_secret
from tests.test_openapi_agents import api, setup, register, ready, evaluate, claim, complete, bearer


@pytest.fixture
def delivery_api(api):
    api[0].app.include_router(external_deliveries.router, prefix="/api/v1")
    return api


def endpoint(api, kind="callback", **changes):
    if kind == "gateway":
        from backend.models import ExternalAIGateway
        from backend.security_scan_controls import protect_secret
        with api[1]() as db:
            gateway = db.query(ExternalAIGateway).first()
            if gateway is None:
                gateway = ExternalAIGateway(name="Existing gateway", management_base_url="http://gateway.test",
                    model_base_url="http://gateway.test", token_id="test", token_value_encrypted=protect_secret("management-secret"))
                db.add(gateway)
                db.commit()
            changes.setdefault("external_gateway_id", gateway.id)
    body = {"kind": kind, "config_id": "callback" if kind == "callback" else "gateway", "version": "1",
            "platform_ids": ["partner"], "url": "http://receiver.test/results", "bearer_token": "test-delivery-secret",
            "retry_delays_seconds": [1, 2], **changes}
    if kind == "gateway":
        body.pop("url")
        body.pop("bearer_token")
        body.setdefault("gateway_path", "/results")
    response = api[0].post("/api/v1/external-access/delivery-endpoints", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def skill_event(api, task_id="skill-1", **changes):
    payload = {"schema_version": "security-result-event.v1", "event_id": "ev_" + task_id,
        "task_id": task_id, "task_type": "skill_scan", "platform_id": "partner", "business_request_id": "skill-business",
        "result_ready": True, "result": {"report_id": "rpt_skill", "report_version": 1, "risk_level": "suspicious"}}
    with api[1]() as db:
        db.add(ExternalResultEvent(event_id=payload["event_id"], task_id=task_id, source_platform_id="partner",
            callback_id="callback", callback_version="1", payload_json=json.dumps(payload), **changes))
        db.commit()
    return payload


def mock_transport(monkeypatch, handler):
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kw: AsyncClient(transport=httpx.MockTransport(handler), **kw))


def deliver():
    work = service.claim()
    assert work
    result = asyncio.run(service.transmit(work))
    service.finish(work, result)
    return work, result


def rows(api):
    result = api[0].get("/api/v1/external-access/deliveries")
    assert result.status_code == 200, result.text
    return result.json()["items"]


def due(api, task_id="skill-1"):
    with api[1]() as db:
        row = db.query(ExternalDelivery).filter_by(task_id=task_id).one()
        row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()


def test_skill_callback_uses_frozen_payload_and_keeps_token_private(delivery_api, monkeypatch):
    api = delivery_api
    configured = endpoint(api)
    payload = skill_event(api)
    seen = []
    def handle(request):
        seen.append(request)
        assert json.loads(request.content) == payload
        assert request.headers["Authorization"] == "Bearer test-delivery-secret"
        return httpx.Response(200, json={"event_id": payload["event_id"], "accepted": True, "ignored": "private response"})
    mock_transport(monkeypatch, handle)
    deliver()
    assert service.claim() is None and len(seen) == 1
    row = rows(api)[0]
    assert row["status"] == "delivered" and row["attempts"] == 1
    detail = api[0].get("/api/v1/external-access/deliveries/" + row["delivery_id"]).json()
    assert detail["attempt_records"][0]["http_status"] == 200
    assert "private response" not in json.dumps(detail) and "test-delivery-secret" not in json.dumps(detail)
    with api[1]() as db:
        stored = db.get(ExternalDeliveryEndpoint, configured["endpoint_id"])
        assert stored.token_encrypted != "test-delivery-secret" and unprotect_secret(stored.token_encrypted) == "test-delivery-secret"
        assert db.query(ExternalResultEvent).one().status == "delivered"
    assert "token_encrypted" not in configured and "bearer_token" not in configured


@pytest.mark.parametrize("code", [408, 429, 500, 503])
def test_retry_http_status_and_retry_after(delivery_api, monkeypatch, code):
    api = delivery_api
    endpoint(api)
    payload = skill_event(api)
    mock_transport(monkeypatch, lambda request: httpx.Response(code, headers={"Retry-After": "120"}))
    deliver()
    row = rows(api)[0]
    assert row["status"] == "retrying" and row["attempts"] == 1
    if code == 429:
        assert datetime.fromisoformat(row["next_retry_at"]) >= datetime.utcnow() + timedelta(seconds=110)
    assert service.claim() is None
    due(api)
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"event_id": payload["event_id"], "accepted": True}))
    deliver()
    assert rows(api)[0]["status"] == "delivered"


@pytest.mark.parametrize("mode", ["401", "422", "302", "wrong-id", "false", "string-true", "malformed", "large"])
def test_permanent_errors_and_invalid_receipts(delivery_api, monkeypatch, mode):
    api = delivery_api
    endpoint(api)
    payload = skill_event(api)
    def handle(request):
        if mode.isdigit():
            return httpx.Response(int(mode), headers={"Location": "http://unexpected.test"})
        if mode == "malformed":
            return httpx.Response(200, content=b"private response")
        if mode == "large":
            return httpx.Response(200, content=b"x" * 65537)
        return httpx.Response(200, json={"event_id": "wrong" if mode == "wrong-id" else payload["event_id"],
                                       "accepted": "true" if mode == "string-true" else mode == "wrong-id"})
    mock_transport(monkeypatch, handle)
    deliver()
    assert rows(api)[0]["status"] == "failed" and service.claim() is None


def test_network_retries_exhaust_and_manual_retry_preserves_history(delivery_api, monkeypatch):
    api = delivery_api
    endpoint(api)
    payload = skill_event(api)
    def fail(request):
        raise httpx.ConnectError("private transport details")
    mock_transport(monkeypatch, fail)
    for _ in range(3):
        due_row = rows(api)[0]
        if due_row["status"] == "retrying":
            due(api)
        deliver()
    row = rows(api)[0]
    assert row["status"] == "failed" and row["attempts"] == 3
    path = "/api/v1/external-access/deliveries/" + row["delivery_id"] + "/retry"
    assert api[0].post(path).status_code == 200
    assert api[0].post(path).status_code == 409
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"event_id": payload["event_id"], "accepted": True}))
    deliver()
    detail = api[0].get(path.removesuffix("/retry")).json()
    assert detail["status"] == "delivered" and detail["attempts"] == 4
    assert [a["number"] for a in detail["attempt_records"]] == [1, 2, 3, 4]
    assert "private transport" not in json.dumps(detail)


def test_concurrent_claim_and_restart_recovery_ignore_stale_completion(delivery_api):
    api = delivery_api
    endpoint(api)
    skill_event(api)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: service.claim(), range(2)))
    old = next(item for item in claimed if item)
    assert sum(item is not None for item in claimed) == 1
    with api[1]() as db:
        db.query(ExternalDelivery).one().lease_until = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert service.claim() is None
    assert rows(api)[0]["status"] == "retrying"
    due(api)
    current = service.claim()
    result = {"http_status": 200, "error_code": None, "retryable": False, "receipt": {"event_id": "ev_skill-1", "accepted": True}}
    service.finish(old, result)
    assert rows(api)[0]["in_flight"]
    service.finish(current, result)
    assert rows(api)[0]["status"] == "delivered"


@pytest.mark.parametrize("callback_status", [200, 401, 503])
def test_agent_callback_and_gateway_receipt_match_report(delivery_api, monkeypatch, callback_status):
    api = delivery_api
    endpoint(api)
    endpoint(api, "gateway")
    register(api)
    task_id = evaluate(api, ready(api)).json()["data"]["task_id"]
    complete(api, claim(api), status="failed", error_code="test_failure")
    report = api[0].get(f"/openapi/v1/agent-evaluations/{task_id}/result", headers=bearer(api[2])).json()["data"]
    seen = []
    def handle(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if "event_id" in payload:
            assert payload["result"]["risk_score"] == report["risk_score"]
            return httpx.Response(callback_status, json={"event_id": payload["event_id"], "accepted": True})
        assert payload["report"] == report
        return httpx.Response(200, json={"request_id": "gateway-request-1", "data": {"sync_id": payload["sync_id"], "report_id": report["report_id"],
            "report_version": 1, "receipt_id": "receipt-1", "status": "accepted", "current": False,
            "received_at": "2026-10-19T00:00:00Z"}})
    mock_transport(monkeypatch, handle)
    deliver()
    deliver()
    assert len(seen) == 2
    progress = api[0].get(f"/openapi/v1/agent-evaluations/{task_id}", headers=bearer(api[2])).json()["data"]
    assert progress["callback"]["status"] == {200: "delivered", 401: "failed", 503: "retrying"}[callback_status]
    assert progress["gateway_sync"]["status"] == "synced"
    assert progress["gateway_sync"]["receipt_id"] == "receipt-1"


def test_config_version_and_missing_receiver(delivery_api, monkeypatch):
    api = delivery_api
    skill_event(api)
    assert service.claim() is None
    row = rows(api)[0]
    assert row["last_error_code"] == "DELIVERY_CONFIG_MISSING"
    endpoint(api, version="2", url="http://new.test/results", bearer_token="new-secret")
    endpoint(api, version="1")
    api[0].post("/api/v1/external-access/deliveries/" + row["delivery_id"] + "/retry")
    work = service.claim()
    assert work["url"] == "http://receiver.test/results" and work["token"] == "test-delivery-secret"
    duplicate = api[0].post("/api/v1/external-access/delivery-endpoints", json={"kind": "callback", "config_id": "callback",
        "version": "1", "platform_ids": ["partner"], "url": "http://different.test/results", "bearer_token": "replacement"})
    assert duplicate.status_code == 409


@pytest.mark.parametrize("native_status", ["succeeded", "failed"])
def test_unavailable_agent_report_still_delivers_callback(delivery_api, monkeypatch, native_status):
    from backend.routers import security_scans
    api = delivery_api
    endpoint(api)
    endpoint(api, "gateway")
    register(api)
    task_id = evaluate(api, ready(api)).json()["data"]["task_id"]
    original = security_scans._task_detail
    def incomplete_detail(*args):
        detail = original(*args)
        detail["cases"] = [{"case_id": "case-1", "external_case_id": "case-1", "category": "test",
            "title": "Unfinished case", "status": "running", "execution_status": "running",
            "assessment_status": "unassessed", "round_count": 0}]
        return detail
    monkeypatch.setattr(security_scans, "_task_detail", incomplete_detail)
    complete(api, claim(api), status=native_status, error_code="test_failure" if native_status == "failed" else None,
        cases=[{"external_case_id": "aig-rule:data-leakage-detection", "category": "agent_detection_skill",
                "title": "Probe", "status": "passed", "round_count": 1,
                "response_summary": {"execution_status": "completed", "dialogue_calls": 1}}])
    seen = []
    def handle(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["result"] is None and payload["result_ready"] is False
        return httpx.Response(200, json={"event_id": payload["event_id"], "accepted": True})
    mock_transport(monkeypatch, handle)
    deliver()
    assert service.claim() is None and len(seen) == 1
    gateway = next(row for row in rows(api) if row["kind"] == "gateway")
    assert gateway["status"] == "failed" and gateway["last_error_code"] == "REPORT_UNAVAILABLE"
    assert gateway["attempts"] == 0
    assert api[0].post("/api/v1/external-access/deliveries/" + gateway["delivery_id"] + "/retry").status_code == 409
    progress = api[0].get(f"/openapi/v1/agent-evaluations/{task_id}", headers=bearer(api[2])).json()["data"]
    assert progress["status"] == seen[0]["status"] == "failed"
    assert progress["callback"]["status"] == "delivered" and progress["gateway_sync"]["status"] == "failed"


def test_retry_after_http_date():
    value = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=2), usegmt=True)
    assert 118 <= service.retry_after(value) <= 120
    assert service.retry_after("invalid") is None


@pytest.mark.parametrize("field,value", [("sync_id", "wrong"), ("report_id", "wrong"), ("report_version", 2),
    ("report_version", True), ("receipt_id", ""), ("status", "pending"), ("current", "true"), ("received_at", "invalid")])
def test_gateway_rejects_mismatched_receipt(field, value):
    payload = {"sync_id": "sync-1", "report": {"report_id": "report-1", "report_version": 1}}
    data = {"sync_id": "sync-1", "report_id": "report-1", "report_version": 1, "receipt_id": "receipt-1",
            "status": "accepted", "current": True, "received_at": "2026-10-19T00:00:00Z", field: value}
    assert service.receipt("gateway", payload, {"request_id": "gateway-request-1", "data": data}) is None


@pytest.mark.parametrize("request_id", [None, "", 1, "x" * 129])
def test_gateway_requires_documented_response_envelope(request_id):
    payload = {"sync_id": "sync-1", "report": {"report_id": "report-1", "report_version": 1}}
    data = {"sync_id": "sync-1", "report_id": "report-1", "report_version": 1, "receipt_id": "receipt-1",
            "status": "accepted", "current": False, "received_at": "2026-10-19T00:00:00Z"}
    assert service.receipt("gateway", payload, {"request_id": request_id, "data": data}) is None


@pytest.mark.parametrize("failure,code", [("disabled", "DELIVERY_CONFIG_DISABLED"), ("partner", "DELIVERY_PARTNER_DISABLED"),
    ("forbidden", "DELIVERY_FORBIDDEN"), ("large", "DELIVERY_PAYLOAD_TOO_LARGE"), ("changed", "DELIVERY_SNAPSHOT_INVALID")])
def test_preflight_restrictions_send_nothing(delivery_api, failure, code):
    api = delivery_api
    configured = endpoint(api, max_payload_bytes=1024)
    skill_event(api)
    rows(api)
    with api[1]() as db:
        receiver = db.get(ExternalDeliveryEndpoint, configured["endpoint_id"])
        event = db.query(ExternalResultEvent).one()
        if failure == "disabled":
            receiver.enabled = False
        elif failure == "partner":
            db.get(ExternalPlatform, "partner").enabled = False
        elif failure == "forbidden":
            receiver.platform_ids_json = '["other"]'
        elif failure in {"large", "changed"}:
            event.payload_json = json.dumps({"text": "x" * 2000})
            if failure == "large":
                db.query(ExternalDelivery).one().payload_sha256 = service.digest(event.payload_json)
        db.commit()
    assert service.claim() is None
    row = rows(api)[0]
    assert row["status"] == "failed" and row["last_error_code"] == code and row["attempts"] == 0


def test_timeout_is_bounded_and_retryable(monkeypatch):
    async def stalled(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})
    mock_transport(monkeypatch, stalled)
    result = asyncio.run(service.transmit({"kind": "callback", "url": "http://receiver.test", "token": "test",
                                           "timeout": 0.01, "payload": '{"event_id":"ev-1"}'}))
    assert result["error_code"] == "DELIVERY_TIMEOUT" and result["retryable"]


def test_local_http_receiver_and_restart_read_saved_receipt(delivery_api):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    api = delivery_api
    payload = skill_event(api)
    received = []
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, self.headers["Authorization"], json.loads(body)))
            response = json.dumps({"event_id": json.loads(body)["event_id"], "accepted": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint(api, url=f"http://127.0.0.1:{server.server_port}/integration/v1/security-results")
        deliver()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert received == [("/integration/v1/security-results", "Bearer test-delivery-secret", payload)]
    assert service.claim() is None
    with api[1]() as db:
        assert db.query(ExternalDelivery).one().receipt_json
        assert db.query(ExternalResultEvent).one().delivered_at


def test_finish_failure_rolls_back_delivery_and_original_event(delivery_api, monkeypatch):
    from sqlalchemy import event
    api = delivery_api
    endpoint(api)
    skill_event(api)
    work = service.claim()
    result = {"http_status": 200, "error_code": None, "retryable": False, "receipt": {"event_id": "ev_skill-1", "accepted": True}}
    def fail(*args):
        raise RuntimeError("simulated storage failure")
    event.listen(ExternalResultEvent, "before_update", fail)
    try:
        with pytest.raises(RuntimeError):
            service.finish(work, result)
    finally:
        event.remove(ExternalResultEvent, "before_update", fail)
    with api[1]() as db:
        assert db.query(ExternalDelivery).one().lease_token == work["lease_token"]
        assert db.query(ExternalResultEvent).one().status == "pending"
        assert db.query(ExternalDeliveryAttempt).one().status == "sending"
    service.finish(work, result)
    assert rows(api)[0]["status"] == "delivered"


def test_management_permissions_and_retry_audit(delivery_api):
    from backend import iam, auth, models
    api = delivery_api
    client, sessions = api[:2]
    configured = endpoint(api)
    skill_event(api, status="failed")
    row = rows(api)[0]
    with sessions() as db:
        iam.initialize(db)
        db.add(models.Role(name="delivery_reader", display_name="Delivery reader"))
        db.add(models.RolePermission(role_name="delivery_reader", permission_code="external_access:view"))
        db.add_all([models.User(username="delivery-reader", role="delivery_reader", hashed_password="unused"),
                    models.User(username="delivery-admin", role="super_admin", hashed_password="unused")])
        db.commit()
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    client.app.dependency_overrides.pop(auth.get_current_active_user)
    root = "/api/v1/external-access"
    assert client.get(root + "/deliveries").status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "delivery-reader"})
    assert client.get(root + "/deliveries").status_code == 200
    assert client.get(root + "/delivery-endpoints").status_code == 200
    assert client.post(root + "/deliveries/" + row["delivery_id"] + "/retry").status_code == 403
    assert client.put(root + "/delivery-endpoints/" + configured["endpoint_id"], json={"enabled": False}).status_code == 403
    assert client.post(root + "/delivery-endpoints", json={}).status_code == 403
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "delivery-admin"})
    assert client.post(root + "/deliveries/" + row["delivery_id"] + "/retry").status_code == 200
    with sessions() as db:
        assert db.query(models.ManagementAudit).filter_by(module="external_access", action="update", outcome="success").count() == 1


def test_receiver_validation_does_not_echo_token(delivery_api):
    client = delivery_api[0]
    response = client.post("/api/v1/external-access/delivery-endpoints", json={"kind": "callback", "config_id": "cb",
        "version": "1", "platform_ids": ["partner"], "url": "http://receiver.test", "bearer_token": "private invalid token"})
    assert response.status_code == 422 and "private invalid token" not in response.text
