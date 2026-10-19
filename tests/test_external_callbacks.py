import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx
import pytest
from sqlalchemy import create_engine, inspect, event
from sqlalchemy.orm import Session

from backend import models, auth, iam
from backend.api_errors import ApiError
from backend.external_access_models import (ExternalCallbackConfig, ExternalDeliveryEndpoint, ExternalDelivery,
    ExternalResultEvent, ExternalSkillScan, ExternalAgentJob, upgrade_external_access_schema)
from backend.routers import external_callbacks, external_deliveries
from backend.services import external_delivery
from backend.security_scan_controls import protect_secret, unprotect_secret
from tests.test_external_access import setup, partner
from tests.test_openapi_agents import api as agent_api, register, ready, evaluate, claim, complete
from tests.test_openapi_skills import api as skill_api, submit, url
from tests.test_external_delivery import endpoint, mock_transport, deliver, rows

ROOT = "/api/v1/external-access/callbacks"


@pytest.fixture
def api(agent_api):
    agent_api[0].app.include_router(external_callbacks.router, prefix="/api/v1")
    agent_api[0].app.include_router(external_deliveries.router, prefix="/api/v1")
    return agent_api


def body(**kwargs):
    return {"callback_id": "callback", "name": "Results", "platform_ids": ["partner"],
        "url": "http://receiver.test/results", "bearer_token": "callback-secret-for-tests",
        "notification_types": ["skill_scan", "agent_evaluation"], "enabled": True, **kwargs}


def create(api, **kwargs):
    result = api[0].post(ROOT, json=body(**kwargs))
    assert result.status_code == 201, result.text
    return result.json()


def update(api, config, **changes):
    data = {key: config[key] for key in ("name", "platform_ids", "url", "notification_types", "enabled", "revision")}
    return api[0].put(ROOT + "/" + quote(config["callback_id"], safe=""), json={**data, **changes})


def test_request(api, config, **changes):
    return api[0].post(ROOT + "/" + quote(config["callback_id"], safe="") + "/test", json={
        "revision": config["revision"], "platform_id": "partner", "notification_type": "skill_scan", **changes})


test_request.__test__ = False


def test_crud_encryption_blank_token_revision_and_deleted_history(api):
    config = create(api)
    assert config["bearer_token_masked"] == "********"
    assert "callback-secret-for-tests" not in json.dumps(config)
    with api[1]() as db:
        first = db.get(ExternalDeliveryEndpoint, db.get(ExternalCallbackConfig, "callback").endpoint_id)
        encrypted, first_id = first.token_encrypted, first.endpoint_id
        assert encrypted != "callback-secret-for-tests" and unprotect_secret(encrypted) == "callback-secret-for-tests"
    changed = update(api, config, name="Changed", url="https://receiver.test/new", bearer_token="").json()
    assert changed["revision"] == 2 and changed["version"] != config["version"]
    assert update(api, config, name="Stale").status_code == 409
    with api[1]() as db:
        current = db.get(ExternalDeliveryEndpoint, db.get(ExternalCallbackConfig, "callback").endpoint_id)
        assert current.token_encrypted == encrypted
        assert db.get(ExternalDeliveryEndpoint, first_id).url == "http://receiver.test/results"
    assert api[0].delete(ROOT + "/callback", params={"revision": 1}).status_code == 409
    assert api[0].delete(ROOT + "/callback", params={"revision": 2}).status_code == 200
    assert api[0].get(ROOT).json()["items"] == []
    assert api[0].post(ROOT, json=body()).status_code == 409
    with api[1]() as db:
        assert db.query(ExternalDeliveryEndpoint).count() == 2
        assert db.get(ExternalCallbackConfig, "callback").deleted_at


@pytest.mark.parametrize("changes", [
    {"name": " "}, {"callback_id": " "}, {"url": "file:///tmp/example"},
    {"url": "http://receiver.test:70000"}, {"url": "https://user:secret@receiver.test"},
    {"bearer_token": "private invalid token"}, {"notification_types": []},
    {"bearer_token": ""}, {"bearer_token": None},
    {"notification_types": ["skill_scan", "skill_scan"]}, {"notification_types": ["unknown"]},
    {"platform_ids": ["partner", "partner"]}, {"platform_ids": ["missing"]},
])
def test_validation_safe_errors_and_no_partial_write(api, changes):
    response = api[0].post(ROOT, json=body(**changes))
    assert response.status_code == 422, response.text
    assert response.json()["error_code"]
    assert "private invalid token" not in response.text
    with api[1]() as db:
        assert db.query(ExternalCallbackConfig).count() == db.query(ExternalDeliveryEndpoint).count() == 0


def test_skill_submit_resolves_page_config_and_freezes_version(skill_api, monkeypatch):
    api = skill_api
    api[0].app.include_router(external_callbacks.router, prefix="/api/v1")
    api[0].app.include_router(external_deliveries.router, prefix="/api/v1")
    config = create(api, callback_id="page-only")
    first_url = url(submit(api, callback_id="page-only"))
    changed = update(api, config, bearer_token="replacement-secret", url="http://receiver.test/new").json()
    second_url = url(submit(api, callback_id="page-only", business_request_id="another"))
    api[3].finish()
    first = api[0].get(first_url, headers={"Authorization": "Bearer " + api[4]["token"]})
    assert first.status_code == 200
    with api[1]() as db:
        assert db.get(ExternalSkillScan, first_url.rsplit("/", 1)[1]).callback_version == config["version"]
        assert db.get(ExternalSkillScan, second_url.rsplit("/", 1)[1]).callback_version == changed["version"]
    mock_transport(monkeypatch, lambda req: httpx.Response(200, json={"event_id": json.loads(req.content)["event_id"], "accepted": True}))
    work, _ = deliver()
    assert work["url"] == config["url"] and work["token"] == "callback-secret-for-tests"
    work, _ = deliver()
    assert work["url"] == changed["url"] and work["token"] == "replacement-secret"
    assert submit(api, callback_id="missing").status_code == 404


def test_agent_uses_page_callback_without_file_reference_and_checks_scope(api):
    config = create(api, callback_id="page-agent", notification_types=["skill_scan"])
    register(api)
    checked = ready(api)
    rejected = evaluate(api, checked, callback_id="page-agent")
    assert rejected.status_code == 403, rejected.text
    changed = update(api, config, notification_types=["agent_evaluation"]).json()
    accepted = evaluate(api, checked, callback_id="page-agent")
    assert accepted.status_code == 202, accepted.text
    task = accepted.json()["data"]["task_id"]
    complete(api, claim(api), cases=[{"external_case_id": "aig-rule:data-leakage-detection", "category": "agent_detection_skill",
        "title": "Data leakage", "status": "passed", "round_count": 1}])
    with api[1]() as db:
        assert db.get(ExternalAgentJob, task).callback_version == changed["version"]
        assert db.query(ExternalResultEvent).filter_by(task_id=task).one().callback_version == changed["version"]
    partner(api[0], "other")
    changed = update(api, changed, platform_ids=["other"]).json()
    assert evaluate(api, checked, callback_id="page-agent").status_code == 403


def test_test_notification_receipt_failure_retry_and_record_metadata(api, monkeypatch):
    config = create(api)
    result = test_request(api, config)
    assert result.status_code == 202, result.text
    delivery = result.json()
    assert delivery["purpose"] == "test" and delivery["task_id"] is None
    assert delivery["created_by"] == "admin" and delivery["task_type"] == "skill_scan"
    seen = []
    def receive(req):
        payload = json.loads(req.content)
        seen.append(payload)
        assert req.headers["Authorization"] == "Bearer callback-secret-for-tests"
        assert payload["schema_version"] == "security-callback-test.v1"
        assert payload["event_type"] == "callback.test" and "task_id" not in payload
        return httpx.Response(401)
    mock_transport(monkeypatch, receive)
    deliver()
    path = "/api/v1/external-access/deliveries/" + delivery["delivery_id"]
    detail = api[0].get(path).json()
    assert detail["status"] == "failed" and detail["attempt_records"][0]["http_status"] == 401
    assert api[0].post(path + "/retry").status_code == 200
    mock_transport(monkeypatch, lambda req: httpx.Response(200, json={"event_id": seen[0]["event_id"], "accepted": True}))
    deliver()
    detail = api[0].get(path).json()
    assert detail["status"] == "delivered" and detail["completed_at"] and len(detail["attempt_records"]) == 2
    assert api[0].get("/api/v1/external-access/deliveries", params={"config_id": "callback", "purpose": "test"}).json()["total"] == 1
    assert api[0].get("/api/v1/external-access/deliveries", params={"config_id": "another"}).json()["total"] == 0
    with api[1]() as db:
        assert db.query(ExternalAgentJob).count() == db.query(ExternalSkillScan).count() == 0


@pytest.mark.parametrize("mode", ["disable", "delete"])
def test_disable_delete_stop_queued_and_block_file_fallback(api, mode):
    config = create(api)
    queued = test_request(api, config).json()
    if mode == "delete":
        result = api[0].delete(ROOT + "/callback", params={"revision": config["revision"]})
    else:
        result = api[0].patch(ROOT + "/callback/state", json={"revision": config["revision"], "enabled": False})
    assert result.status_code == 200
    assert external_delivery.claim() is None
    record = rows(api)[0]
    assert record["status"] == "failed"
    assert record["last_error_code"] == ("DELIVERY_CONFIG_DELETED" if mode == "delete" else "DELIVERY_CONFIG_DISABLED")
    assert test_request(api, {**config, "revision": 2}).status_code in {404, 409}
    from backend.services.external_callbacks import resolve
    from types import SimpleNamespace
    with api[1]() as db, pytest.raises(ApiError) as exc:
        resolve(db, "callback", "partner", "skill_scan", SimpleNamespace(version="1", platform_ids=["partner"]))
    assert exc.value.status_code == (404 if mode == "delete" else 403)
    retry_path = "/api/v1/external-access/deliveries/" + queued["delivery_id"] + "/retry"
    assert api[0].post(retry_path).status_code == 409
    if mode == "disable":
        assert api[0].patch(ROOT + "/callback/state", json={"revision": 2, "enabled": True}).status_code == 200
        assert api[0].post(retry_path).status_code == 200
        assert external_delivery.claim()


def test_scope_conflict_and_legacy_endpoint_management(api):
    old = endpoint(api)
    config = api[0].get(ROOT).json()["items"][0]
    assert config["version"] == old["version"]
    assert test_request(api, config, platform_id="other").status_code == 409
    assert test_request(api, config, revision=999).status_code == 409
    update(api, config, notification_types=["agent_evaluation"])
    assert test_request(api, {**config, "revision": 2}).status_code == 422


def test_concurrent_edits_have_one_winner_and_preserve_versions(api):
    config = create(api)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda name: update(api, config, name=name).status_code, ["First", "Second"]))
    assert sorted(outcomes) == [200, 409]
    with api[1]() as db:
        assert db.query(ExternalDeliveryEndpoint).count() == 2
        assert db.get(ExternalCallbackConfig, "callback").revision == 2


def test_legacy_disabled_receiver_can_be_enabled_in_callback_page(api):
    configured = endpoint(api)
    api[0].put("/api/v1/external-access/delivery-endpoints/" + configured["endpoint_id"], json={"enabled": False})
    config = api[0].get(ROOT).json()["items"][0]
    assert not config["enabled"]
    updated = api[0].patch(ROOT + "/callback/state", json={"enabled": True, "revision": config["revision"]}).json()
    assert test_request(api, updated).status_code == 202
    assert external_delivery.claim()


def test_legacy_version_creation_does_not_edit_managed_configuration(api):
    config = create(api, enabled=False)
    endpoint(api, version="another", url="http://receiver.test/another")
    current = api[0].get(ROOT).json()["items"][0]
    assert current["version"] == config["version"] and not current["enabled"]
    assert current["revision"] == config["revision"]


def test_failed_test_enqueue_rolls_back_event_and_delivery(api, monkeypatch):
    config = create(api)
    def fail(db, **kwargs):
        raise RuntimeError("injected queue failure")
    monkeypatch.setattr(external_delivery, "enqueue", fail)
    assert test_request(api, config).status_code == 500
    with api[1]() as db:
        assert db.query(ExternalResultEvent).count() == db.query(ExternalDelivery).count() == 0


def test_non_ascii_callback_id_is_editable(api):
    config = create(api, callback_id="部门/回调")
    assert update(api, config, name="Updated").status_code == 200


def test_test_notification_automatic_retry_preserves_event_and_version(api, monkeypatch):
    config = create(api)
    queued = test_request(api, config).json()
    mock_transport(monkeypatch, lambda req: httpx.Response(503))
    first, _ = deliver()
    item = rows(api)[0]
    assert item["status"] == "retrying" and item["next_retry_at"]
    changed = update(api, config, url="http://receiver.test/new", bearer_token="new-test-secret").json()
    with api[1]() as db:
        row = db.get(ExternalDelivery, queued["delivery_id"])
        row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    mock_transport(monkeypatch, lambda req: httpx.Response(200, json={"event_id": json.loads(req.content)["event_id"], "accepted": True}))
    second, _ = deliver()
    assert first["payload"] == second["payload"] and first["token"] == second["token"]
    assert second["url"] == config["url"] != changed["url"]
    assert rows(api)[0]["status"] == "delivered"


def test_permissions_and_audit_do_not_expose_credentials(api):
    client, sessions = api[:2]
    config = create(api)
    with sessions() as db:
        iam.initialize(db)
        db.add(models.Role(name="callback_reader", display_name="Reader"))
        db.add(models.RolePermission(role_name="callback_reader", permission_code="external_access:view"))
        db.add_all([models.User(username="reader", role="callback_reader", hashed_password="unused"),
                    models.User(username="operator", role="super_admin", hashed_password="unused")])
        db.commit()
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    client.app.dependency_overrides.pop(auth.get_current_active_user, None)
    assert client.get(ROOT).status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "reader"})
    assert client.get(ROOT).status_code == 200
    assert client.post(ROOT, json=body(callback_id="second")).status_code == 403
    assert update(api, config).status_code == 403
    assert test_request(api, config).status_code == 403
    assert client.delete(ROOT + "/callback", params={"revision": 1}).status_code == 403
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "operator"})
    assert test_request(api, config).status_code == 202
    assert client.delete(ROOT + "/callback", params={"revision": 1}).status_code == 200
    with sessions() as db:
        logs = db.query(models.ManagementAudit).filter_by(module="external_access").all()
        assert any(row.action == "delete" and row.outcome == "success" for row in logs)
        assert any(row.action == "update" and row.outcome == "success" for row in logs)
        assert "callback-secret-for-tests" not in str([row.__dict__ for row in logs])


def test_legacy_database_upgrade_preserves_versions_and_repeated_start(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        for i in (1, 2):
            db.add(ExternalDeliveryEndpoint(endpoint_id=f"old-{i}", kind="callback", config_id="old", version=str(i),
                platform_ids_json='["partner"]', url=f"http://receiver.test/{i}", token_encrypted=protect_secret("legacy-secret"),
                timeout_seconds=10, retry_delays_json="[60]", max_payload_bytes=1048576,
                created_by="admin", created_at=datetime(2026, 1, i)))
        db.add(ExternalResultEvent(event_id="old-event", task_id="old-task", source_platform_id="partner", callback_id="old",
            callback_version="1", payload_json='{"event_id":"old-event"}'))
        db.commit()
    with engine.begin() as conn:
        ExternalCallbackConfig.__table__.drop(conn)
        for table, columns in {"external_delivery_endpoints": ["notification_types_json"],
            "external_result_events": ["created_by"], "external_deliveries": ["purpose", "task_type", "created_by"]}.items():
            for column in columns:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
    upgrade_external_access_schema(engine)
    with Session(engine) as db:
        config = db.get(ExternalCallbackConfig, "old")
        assert config.endpoint_id == "old-2"
        config.name, config.deleted_at = "Edited", datetime.utcnow()
        db.commit()
    upgrade_external_access_schema(engine)
    with Session(engine) as db:
        assert db.get(ExternalCallbackConfig, "old").name == "Edited"
        assert db.get(ExternalCallbackConfig, "old").deleted_at
        assert db.query(ExternalDeliveryEndpoint).count() == 2
        assert unprotect_secret(db.get(ExternalDeliveryEndpoint, "old-1").token_encrypted) == "legacy-secret"
        assert db.get(ExternalResultEvent, "old-event").callback_version == "1"
        assert json.loads(db.get(ExternalDeliveryEndpoint, "old-1").notification_types_json) == ["skill_scan", "agent_evaluation"]
    engine.dispose()


def test_callback_migration_rolls_back_and_recovers(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        ExternalCallbackConfig.__table__.drop(conn)
        conn.exec_driver_sql('ALTER TABLE external_delivery_endpoints DROP COLUMN notification_types_json')
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("CREATE TABLE external_callback_configs"):
            raise RuntimeError("injected DDL failure")
    event.listen(engine, "before_cursor_execute", fail)
    with pytest.raises(RuntimeError):
        upgrade_external_access_schema(engine)
    assert "notification_types_json" not in {c["name"] for c in inspect(engine).get_columns("external_delivery_endpoints")}
    event.remove(engine, "before_cursor_execute", fail)
    upgrade_external_access_schema(engine)
    assert inspect(engine).has_table("external_callback_configs")
    engine.dispose()
