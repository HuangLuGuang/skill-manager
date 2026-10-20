import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit, parse_qs
import hashlib
import hmac

import httpx
import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session

from backend import auth, iam, models
from backend.external_access_models import (ExternalGatewayConfig, ExternalDeliveryEndpoint, ExternalDelivery,
    ExternalGatewayEvent, ExternalAgentJob, ExternalSkillScan, upgrade_external_access_schema)
from backend.routers import external_gateways, external_deliveries
from backend.security_scan_controls import unprotect_secret, protect_secret
from backend.services import external_delivery
from tests.test_external_access import setup, partner
from tests.test_openapi_agents import api as agent_api, register, ready, evaluate, claim, complete
from tests.test_external_delivery import endpoint, mock_transport, deliver, rows

ROOT = "/api/v1/external-access/gateways"


@pytest.fixture
def api(agent_api):
    agent_api[0].app.include_router(external_gateways.router, prefix="/api/v1")
    agent_api[0].app.include_router(external_deliveries.router, prefix="/api/v1")
    with agent_api[1]() as db:
        db.add(models.ExternalAIGateway(id=1, name="Existing AI gateway", management_base_url="http://manage.test",
            model_base_url="http://model.test", token_id="management-id", token_value_encrypted=protect_secret("management-secret")))
        db.commit()
    return agent_api


def body(**changes):
    return {"gateway_id": "gateway", "external_gateway_id": 1, "platform_ids": ["partner"],
        "gateway_path": "/results", "enabled": True, **changes}


def create(api, **changes):
    result = api[0].post(ROOT, json=body(**changes))
    assert result.status_code == 201, result.text
    return result.json()


def path(config):
    return ROOT + "/" + quote(config["gateway_id"], safe="")


def update(api, config, **changes):
    values = {key: config[key] for key in ("external_gateway_id", "platform_ids", "gateway_path", "enabled", "revision")}
    return api[0].put(path(config), json={**values, **changes})


def queue(api, config, **changes):
    return api[0].post(path(config) + "/test", json={"revision": config["revision"], "platform_id": "partner", **changes})


def assert_signature(url, raw, secret="management-secret", token_id="management-id"):
    parsed = urlsplit(str(url)); query = parse_qs(parsed.query)
    assert query["tokenid"] == [token_id]
    canonical = "\n".join(["POST", quote(parsed.path, safe="/~"), "", query["timestamp"][0],
        query["nonce"][0], token_id, hashlib.md5(raw).hexdigest()])
    assert query["signature"] == [hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()]
    return parsed.path


def test_crud_reference_revision_concurrency_and_version_api(api):
    config = create(api, gateway_id="部门/网关")
    assert config["token_id"] == "management-id" and "management-secret" not in json.dumps(config)
    with api[1]() as db:
        first_id = db.get(ExternalGatewayConfig, config["gateway_id"]).endpoint_id
        encrypted = db.get(ExternalDeliveryEndpoint, first_id).token_encrypted
        assert encrypted == ""
    with ThreadPoolExecutor(max_workers=2) as pool:
        changes = list(pool.map(lambda suffix: update(api, config, gateway_path="/" + suffix), ["One", "Two"]))
    assert sorted(r.status_code for r in changes) == [200, 409]
    changed = next(r.json() for r in changes if r.status_code == 200)
    assert changed["revision"] == 2 and changed["version"] != config["version"]
    endpoint(api, "gateway", config_id=config["gateway_id"], version="legacy")
    assert api[0].get(ROOT).json()["items"][0]["version"] == changed["version"]
    with api[1]() as db:
        assert db.get(ExternalDeliveryEndpoint, first_id).url == config["url"]
        assert db.get(ExternalDeliveryEndpoint, db.get(ExternalGatewayConfig, config["gateway_id"]).endpoint_id).token_encrypted == encrypted
    assert api[0].delete(path(config), params={"revision": 1}).status_code == 409
    assert api[0].delete(path(config), params={"revision": 2}).status_code == 200
    assert api[0].get(ROOT).json()["items"] == []
    assert api[0].post(ROOT, json=body(gateway_id=config["gateway_id"])).status_code == 409
    with api[1]() as db:
        assert db.query(ExternalDeliveryEndpoint).count() == 3


@pytest.mark.parametrize("changes", [{"gateway_id": " "}, {"external_gateway_id": None}, {"external_gateway_id": 999}, {"external_gateway_id": True}, {"gateway_path": "https://other.test/api"},
    {"gateway_path": "//other.test/api"}, {"gateway_path": "/a/../b"}, {"gateway_path": "/%2e%2e/b"},
    {"gateway_path": "/api?tokenid=other"}, {"gateway_path": "/api#fragment"}, {"gateway_path": "/api\\other"},
    {"gateway_path": "/api\n"}, {"gateway_path": ""}, {"gateway_path": None},
    {"platform_ids": []}, {"platform_ids": ["partner", "partner"]}, {"platform_ids": ["missing"]}])
def test_validation_safe_errors_and_atomic_write(api, changes):
    response = api[0].post(ROOT, json=body(**changes))
    assert response.status_code == 422 and response.json()["error_code"]
    assert "private invalid token" not in response.text
    with api[1]() as db:
        assert db.query(ExternalGatewayConfig).count() == db.query(ExternalDeliveryEndpoint).count() == 0


def test_page_gateway_binds_version_and_delivers_frozen_report(api, monkeypatch):
    config = create(api, gateway_id="page-only")
    register(api)
    checked = ready(api)
    accepted = evaluate(api, checked, gateway_id="page-only")
    assert accepted.status_code == 202, accepted.text
    task_id = accepted.json()["data"]["task_id"]
    with api[1]() as db:
        db.add(models.ExternalAIGateway(id=2, name="Second gateway", management_base_url="http://manage-2.test",
            model_base_url="http://model-2.test", token_id="second-id", token_value_encrypted=protect_secret("second-management-secret")))
        db.commit()
    changed = update(api, config, external_gateway_id=2, gateway_path="/new").json()
    complete(api, claim(api), cases=[{"external_case_id": "aig-rule:data-leakage-detection", "category": "agent_detection_skill",
        "title": "Data leakage", "status": "passed", "round_count": 1}])
    with api[1]() as db:
        job = db.get(ExternalAgentJob, task_id)
        frozen = json.loads(db.get(ExternalGatewayEvent, task_id).payload_json)
        assert job.gateway_version == config["version"]
        assert db.query(ExternalDeliveryEndpoint).filter_by(version=config["version"]).one().external_gateway_id == 1
        assert db.query(ExternalDeliveryEndpoint).filter_by(version=changed["version"]).one().external_gateway_id == 2
        assert frozen["report"] == json.loads(job.report_json) and frozen["findings"] == json.loads(job.findings_json)
    def receive(req):
        payload = json.loads(req.content)
        assert payload == frozen
        assert "Authorization" not in req.headers
        assert_signature(req.url, req.content)
        report = payload["report"]
        return httpx.Response(200, json={"request_id": "ack", "data": {"sync_id": payload["sync_id"],
            "report_id": report["report_id"], "report_version": report["report_version"], "receipt_id": "receipt",
            "status": "accepted", "current": True, "received_at": "2026-10-19T08:00:00Z"}})
    mock_transport(monkeypatch, receive)
    work, _ = deliver()
    assert work["url"] == config["url"]
    assert next(row for row in rows(api) if row["kind"] == "gateway")["status"] == "synced"
    second = evaluate(api, checked, gateway_id="page-only", business_request_id="second")
    assert second.status_code == 202
    with api[1]() as db:
        assert db.get(ExternalAgentJob, second.json()["data"]["task_id"]).gateway_version == changed["version"]
    partner(api[0], "other")
    update(api, changed, platform_ids=["other"])
    assert evaluate(api, checked, gateway_id="page-only").status_code == 403
    assert evaluate(api, checked, gateway_id="missing").status_code == 404


def test_test_delivery_retry_and_snapshot_metadata(api, monkeypatch):
    config = create(api)
    queued = queue(api, config)
    assert queued.status_code == 202, queued.text
    record = queued.json()
    assert record["task_id"] is None and record["purpose"] == "test" and record["created_by"] == "admin"
    mock_transport(monkeypatch, lambda req: httpx.Response(503))
    first, _ = deliver()
    assert rows(api)[0]["status"] == "retrying"
    update(api, config, gateway_path="/new")
    with api[1]() as db:
        item = db.get(ExternalDelivery, record["delivery_id"])
        item.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    mock_transport(monkeypatch, lambda req: httpx.Response(200, json={"sync_id": "wrong", "accepted": True}))
    second, _ = deliver()
    assert (first["payload"], first["url"], first["token"]) == (second["payload"], second["url"], second["token"])
    path = "/api/v1/external-access/deliveries/" + record["delivery_id"]
    assert api[0].get(path).json()["last_error_code"] == "DELIVERY_RECEIPT_INVALID"
    assert api[0].post(path + "/retry").status_code == 200
    def receive(req):
        payload = json.loads(req.content)
        assert payload["schema_version"] == "security-gateway-test.v1" and payload["event_type"] == "gateway.test"
        assert "report" not in payload and "task_id" not in payload
        return httpx.Response(200, json={"sync_id": payload["sync_id"], "accepted": True, "ignored": "private content"})
    mock_transport(monkeypatch, receive)
    deliver()
    result = api[0].get(path).json()
    assert result["status"] == "synced" and result["completed_at"] and len(result["attempt_records"]) == 3
    assert "private content" not in json.dumps(result) and "gateway-test-secret" not in json.dumps(result)
    assert api[0].get("/api/v1/external-access/deliveries", params={"kind": "gateway", "config_id": "gateway", "purpose": "test"}).json()["total"] == 1
    with api[1]() as db:
        assert db.query(ExternalAgentJob).count() == db.query(ExternalSkillScan).count() == 0


@pytest.mark.parametrize("mode", ["disable", "delete"])
def test_disable_delete_blocks_tasks_tests_and_queued_deliveries(api, mode):
    config = create(api)
    queued = queue(api, config).json()
    if mode == "delete":
        assert api[0].delete(path(config), params={"revision": 1}).status_code == 200
    else:
        assert api[0].patch(path(config) + "/state", json={"revision": 1, "enabled": False}).status_code == 200
    register(api)
    checked = ready(api)
    assert evaluate(api, checked).status_code == (404 if mode == "delete" else 403)
    assert queue(api, {**config, "revision": 2}).status_code == (404 if mode == "delete" else 409)
    assert external_delivery.claim() is None
    item = rows(api)[0]
    assert item["last_error_code"] == ("DELIVERY_CONFIG_DELETED" if mode == "delete" else "DELIVERY_CONFIG_DISABLED")
    retry = "/api/v1/external-access/deliveries/" + queued["delivery_id"] + "/retry"
    assert api[0].post(retry).status_code == 409
    if mode == "disable":
        assert api[0].patch(path(config) + "/state", json={"revision": 2, "enabled": True}).status_code == 200
        assert api[0].post(retry).status_code == 200
        assert external_delivery.claim()


def test_test_scope_revision_and_queue_rollback(api, monkeypatch):
    config = create(api)
    partner(api[0], "other")
    assert queue(api, config, platform_id="other").status_code == 422
    assert queue(api, config, platform_id="missing").status_code == 409
    assert queue(api, config, revision=999).status_code == 409
    def fail(db, **kwargs):
        raise RuntimeError("injected enqueue failure")
    monkeypatch.setattr(external_delivery, "enqueue", fail)
    assert queue(api, config).status_code == 500
    with api[1]() as db:
        assert db.query(ExternalGatewayEvent).count() == db.query(ExternalDelivery).count() == 0


def test_test_notification_can_enqueue_with_event_backlog(api):
    config = create(api)
    with api[1]() as db:
        for number in range(101):
            db.add(ExternalGatewayEvent(task_id=f"old-test-{number}", gateway_id=config["gateway_id"],
                gateway_version=config["version"], payload_json=json.dumps({"event_type": "gateway.test",
                    "sync_id": f"old-{number}", "platform_id": "partner"})))
        db.commit()
    result = queue(api, config)
    assert result.status_code == 202, result.text
    with api[1]() as db:
        assert db.query(ExternalDelivery).count() == 1
        assert db.get(ExternalDelivery, result.json()["delivery_id"]).message_id == result.json()["message_id"]


def test_permissions_and_audit(api):
    client, sessions = api[:2]
    config = create(api)
    with sessions() as db:
        iam.initialize(db)
        db.add(models.Role(name="gateway_reader", display_name="Reader"))
        db.add(models.RolePermission(role_name="gateway_reader", permission_code="external_access:view"))
        db.add_all([models.User(username="reader", role="gateway_reader", hashed_password="unused"),
                    models.User(username="operator", role="super_admin", hashed_password="unused")])
        db.commit()
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    client.app.dependency_overrides.pop(auth.get_current_active_user, None)
    assert client.get(ROOT).status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "reader"})
    assert client.get(ROOT).status_code == 200
    options = client.get(ROOT + "/options")
    assert options.status_code == 200 and options.json()["items"] == [{"id": 1, "name": "Existing AI gateway", "enabled": True,
        "management_base_url": "http://manage.test", "token_id": "management-id"}]
    assert client.post(ROOT, json=body(gateway_id="new")).status_code == 403
    assert update(api, config).status_code == 403
    assert queue(api, config).status_code == 403
    assert client.patch(path(config) + "/state", json={"revision": 1, "enabled": False}).status_code == 403
    assert client.delete(path(config), params={"revision": 1}).status_code == 403
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "operator"})
    assert queue(api, config).status_code == 202
    assert client.delete(path(config), params={"revision": 1}).status_code == 200
    with sessions() as db:
        logs = db.query(models.ManagementAudit).filter_by(module="external_access").all()
        assert any(row.action == "delete" and row.outcome == "success" for row in logs)
        assert any(row.action == "update" and row.outcome == "success" for row in logs)
        assert "gateway-test-secret" not in str([row.__dict__ for row in logs])


def test_upgrade_preserves_old_versions_events_and_current_edits(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        for i in (1, 2):
            db.add(ExternalDeliveryEndpoint(endpoint_id=f"old-{i}", kind="gateway", config_id="old", version=str(i),
                platform_ids_json='["partner"]', url=f"http://gateway.test/{i}", token_encrypted=protect_secret("old-secret"),
                timeout_seconds=10, retry_delays_json="[60]", max_payload_bytes=1048576, enabled=False,
                created_by="admin", created_at=datetime(2026, 1, i)))
        db.add(ExternalGatewayEvent(task_id="old-task", gateway_id="old", gateway_version="1", payload_json='{"sync_id":"old"}'))
        db.commit()
    with engine.begin() as conn:
        ExternalGatewayConfig.__table__.drop(conn)
        conn.exec_driver_sql('DROP INDEX ix_external_delivery_endpoints_external_gateway_id')
        conn.exec_driver_sql('ALTER TABLE external_delivery_endpoints DROP COLUMN external_gateway_id')
        conn.exec_driver_sql('ALTER TABLE external_delivery_endpoints DROP COLUMN gateway_path')
        conn.exec_driver_sql('ALTER TABLE external_gateway_events DROP COLUMN created_by')
    upgrade_external_access_schema(engine)
    with Session(engine) as db:
        config = db.get(ExternalGatewayConfig, "old")
        assert config.endpoint_id == "old-2" and not config.enabled
        config.name, config.revision, config.deleted_at = "Edited", 5, datetime.utcnow()
        db.commit()
    upgrade_external_access_schema(engine)
    with Session(engine) as db:
        config = db.get(ExternalGatewayConfig, "old")
        assert config.name == "Edited" and config.revision == 5 and config.deleted_at
        assert db.query(ExternalDeliveryEndpoint).count() == 2
        assert db.get(ExternalDeliveryEndpoint, "old-1").external_gateway_id is None
        assert db.get(ExternalDeliveryEndpoint, "old-1").gateway_path is None
        assert unprotect_secret(db.get(ExternalDeliveryEndpoint, "old-1").token_encrypted) == "old-secret"
        event = db.get(ExternalGatewayEvent, "old-task")
        assert event.gateway_version == "1" and event.payload_json == '{"sync_id":"old"}' and event.created_by is None
    assert "ix_external_delivery_endpoints_external_gateway_id" in {i["name"] for i in inspect(engine).get_indexes("external_delivery_endpoints")}
    engine.dispose()


def test_migration_failure_rolls_back_and_can_restart(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        ExternalGatewayConfig.__table__.drop(conn)
        conn.exec_driver_sql('DROP INDEX ix_external_delivery_endpoints_external_gateway_id')
        conn.exec_driver_sql('ALTER TABLE external_delivery_endpoints DROP COLUMN external_gateway_id')
        conn.exec_driver_sql('ALTER TABLE external_delivery_endpoints DROP COLUMN gateway_path')
        conn.exec_driver_sql('ALTER TABLE external_gateway_events DROP COLUMN created_by')
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("CREATE TABLE external_gateway_configs"):
            raise RuntimeError("injected DDL failure")
    event.listen(engine, "before_cursor_execute", fail)
    with pytest.raises(RuntimeError):
        upgrade_external_access_schema(engine)
    assert "created_by" not in {c["name"] for c in inspect(engine).get_columns("external_gateway_events")}
    assert "external_gateway_id" not in {c["name"] for c in inspect(engine).get_columns("external_delivery_endpoints")}
    assert "gateway_path" not in {c["name"] for c in inspect(engine).get_columns("external_delivery_endpoints")}
    event.remove(engine, "before_cursor_execute", fail)
    upgrade_external_access_schema(engine)
    assert inspect(engine).has_table("external_gateway_configs")
    engine.dispose()


def test_gateway_selection_name_refresh_and_shared_credentials(api):
    config = create(api)
    assert config["name"] == "Existing AI gateway" and config["external_gateway_id"] == 1
    assert not config["binding_required"]
    with api[1]() as db:
        gateway = db.get(models.ExternalAIGateway, 1)
        gateway.name, gateway.management_base_url = "Renamed gateway", "http://management-new.test"
        gateway.token_value_encrypted = protect_secret("rotated-management-secret")
        db.commit()
    current = api[0].get(ROOT).json()["items"][0]
    assert current["name"] == "Renamed gateway" and current["version"] == config["version"]
    assert current["url"] == config["url"]
    with api[1]() as db:
        endpoint = db.get(ExternalDeliveryEndpoint, db.get(ExternalGatewayConfig, "gateway").endpoint_id)
        assert endpoint.token_encrypted == ""
        engine = db.get_bind()
    upgrade_external_access_schema(engine)
    upgrade_external_access_schema(engine)
    restarted = api[0].get(ROOT).json()["items"][0]
    assert restarted["external_gateway_id"] == 1 and restarted["version"] == config["version"]
    assert "management-secret" not in api[0].get(ROOT + "/options").text


def test_retry_uses_current_gateway_credentials_and_frozen_report(api, monkeypatch):
    config = create(api, gateway_path="/结果")
    queued = queue(api, config).json()
    seen = []
    def first(req):
        assert_signature(req.url, req.content)
        seen.append((str(req.url), req.content))
        return httpx.Response(503)
    mock_transport(monkeypatch, first)
    deliver()
    with api[1]() as db:
        gateway = db.get(models.ExternalAIGateway, 1)
        gateway.token_id, gateway.token_value_encrypted = "new-id", protect_secret("new-value")
        db.get(ExternalDelivery, queued["delivery_id"]).next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    def retry(req):
        assert_signature(req.url, req.content, "new-value", "new-id")
        assert req.content == seen[0][1] and str(req.url) != seen[0][0]
        assert req.url.path == "/结果"
        return httpx.Response(200, json={"sync_id": json.loads(req.content)["sync_id"], "accepted": True})
    mock_transport(monkeypatch, retry)
    assert deliver()[1]["receipt"]["accepted"]
    assert rows(api)[0]["config_version"] == config["version"]


def test_changed_management_address_stops_old_destination_and_new_version_uses_new_address(api):
    config = create(api)
    queue(api, config)
    with api[1]() as db:
        db.get(models.ExternalAIGateway, 1).management_base_url = "https://new.test/prefix"
        db.commit()
    assert external_delivery.claim() is None
    assert rows(api)[0]["last_error_code"] == "DELIVERY_GATEWAY_ADDRESS_CHANGED"
    changed = update(api, config).json()
    assert changed["url"] == "https://new.test/prefix/results" and changed["version"] != config["version"]
    queue(api, changed)
    assert external_delivery.claim()["url"] == changed["url"]


def test_disabled_external_gateway_blocks_submission_test_and_delivery(api):
    config = create(api)
    queued = queue(api, config).json()
    with api[1]() as db:
        db.get(models.ExternalAIGateway, 1).enabled = False
        db.commit()
    assert api[0].post(ROOT, json=body(gateway_id="second")).status_code == 422
    assert update(api, config).status_code == 422
    assert queue(api, config).status_code == 422
    register(api)
    assert evaluate(api, ready(api)).status_code == 403
    assert external_delivery.claim() is None
    assert rows(api)[0]["last_error_code"] == "DELIVERY_GATEWAY_UNAVAILABLE"
    with api[1]() as db:
        db.get(models.ExternalAIGateway, 1).enabled = True
        db.commit()
    assert api[0].post("/api/v1/external-access/deliveries/" + queued["delivery_id"] + "/retry").status_code == 200
    assert external_delivery.claim()


def test_unlinked_history_delivers_while_new_tasks_require_binding(api, monkeypatch):
    legacy = endpoint(api, "gateway")
    with api[1]() as db:
        item = db.get(ExternalDeliveryEndpoint, legacy["endpoint_id"])
        item.external_gateway_id = item.gateway_path = None
        item.token_encrypted = protect_secret("test-delivery-secret")
        db.commit()
    config = api[0].get(ROOT).json()["items"][0]
    assert config["binding_required"] and config["gateway_id"] == "gateway"
    with api[1]() as db:
        db.add(ExternalGatewayEvent(task_id="historical", gateway_id="gateway", gateway_version=legacy["version"],
            payload_json=json.dumps({"event_type": "gateway.test", "sync_id": "historical-sync", "platform_id": "partner"})))
        db.commit()
    register(api)
    checked = ready(api)
    rejected = evaluate(api, checked)
    assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert queue(api, config).status_code == 409
    changed = update(api, config, external_gateway_id=1, gateway_path="/results").json()
    assert changed["gateway_id"] == config["gateway_id"] and changed["version"] != config["version"]
    assert not changed["binding_required"]
    mock_transport(monkeypatch, lambda req: httpx.Response(200, json={"sync_id": "historical-sync", "accepted": True}))
    work, result = deliver()
    assert work["url"] == legacy["url"] and work["token"] == "test-delivery-secret"
    assert result["error_code"] is None
    assert evaluate(api, checked).status_code == 202
    with api[1]() as db:
        assert db.get(ExternalDeliveryEndpoint, legacy["endpoint_id"]).external_gateway_id is None


def test_linked_legacy_config_requires_path_for_new_evaluations_and_tests(api):
    config = create(api)
    with api[1]() as db:
        saved = db.get(ExternalDeliveryEndpoint, db.get(ExternalGatewayConfig, config["gateway_id"]).endpoint_id)
        saved.gateway_path = None
        saved.token_encrypted = protect_secret("historical-receiver-secret")
        db.commit()
    register(api)
    response = evaluate(api, ready(api))
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["retryable"] is False
    assert queue(api, config).json()["error_code"] == "external_gateways.path_required"
    changed = update(api, config).json()
    assert changed["gateway_id"] == config["gateway_id"] and changed["gateway_path"] == "/results"
    assert queue(api, changed).status_code == 202


def test_external_gateway_deletion_preserves_sync_version_references(api):
    from backend.routers import external_ai_gateways
    api[0].app.include_router(external_ai_gateways.router, prefix="/api")
    config = create(api)
    result = api[0].delete("/api/v1/external-ai-gateways/1")
    assert result.status_code == 409, result.text
    assert result.json()["error_code"] == "external_gateway.result_sync_in_use"
    assert api[0].delete(path(config), params={"revision": 1}).status_code == 200
    assert api[0].delete("/api/v1/external-ai-gateways/1").status_code == 409


def test_real_http_gateway_test_report_and_retry_keep_saved_version(api):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    received = []
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.loads(raw)
            assert "Authorization" not in self.headers
            path = assert_signature(self.path, raw)
            received.append((path, raw, payload))
            if payload.get("event_type") == "gateway.test":
                code, ack = 200, {"sync_id": payload["sync_id"], "accepted": True}
            else:
                report = payload["report"]
                code = 503 if len(received) == 2 else 200
                ack = {"request_id": "local-ack", "data": {"sync_id": payload["sync_id"],
                    "report_id": report["report_id"], "report_version": report["report_version"],
                    "receipt_id": "local-receipt", "status": "accepted", "current": True,
                    "received_at": "2026-10-19T08:00:00Z"}}
            raw = json.dumps(ack).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with api[1]() as db:
            db.get(models.ExternalAIGateway, 1).management_base_url = f"http://127.0.0.1:{server.server_port}"
            db.commit()
        config = create(api, gateway_path="/original")
        assert queue(api, config).status_code == 202
        assert deliver()[1]["receipt"]["accepted"] is True
        register(api)
        accepted = evaluate(api, ready(api))
        assert accepted.status_code == 202, accepted.text
        task_id = accepted.json()["data"]["task_id"]
        assert update(api, config, gateway_path="/new").status_code == 200
        complete(api, claim(api), cases=[{"external_case_id": "aig-rule:data-leakage-detection",
            "category": "agent_detection_skill", "title": "Data leakage", "status": "passed", "round_count": 1}])
        assert deliver()[1]["http_status"] == 503
        with api[1]() as db:
            delivery = db.query(ExternalDelivery).filter_by(kind="gateway", task_id=task_id).one()
            assert delivery.status == "retrying"
            delivery.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
            frozen = json.loads(db.get(ExternalGatewayEvent, task_id).payload_json)
            assert frozen["report"] == json.loads(db.get(ExternalAgentJob, task_id).report_json)
            db.commit()
        assert deliver()[1]["receipt"]["receipt_id"] == "local-receipt"
        history = next(row for row in rows(api) if row["kind"] == "gateway" and row["task_id"] == task_id)
        detail = api[0].get("/api/v1/external-access/deliveries/" + history["delivery_id"]).json()
        assert detail["status"] == "synced" and detail["config_version"] == config["version"]
        assert [row["http_status"] for row in detail["attempt_records"]] == [503, 200]
        assert received[1] == received[2] and received[1][0] == "/original" and received[1][2] == frozen
        assert received[0][0] == "/original"
        assert external_delivery.claim() is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
