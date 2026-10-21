import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend import auth, models, sqlite_db
from backend.api_errors import ApiError, api_error_handler, routing_error_handler, unhandled_error_handler, validation_error_handler
from backend.external_access import ExternalAccessMiddleware, link_external_resource, require_openapi_scope
from backend.external_access_models import upgrade_external_access_schema
from backend.routers import access_tokens, agents, external_access


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'external.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    models.Base.metadata.create_all(engine)
    monkeypatch.setattr(sqlite_db, "SessionLocal", sessions)
    with sessions() as db:
        db.add_all([models.UserGroup(id=1, name="One"), models.UserGroup(id=2, name="Two")])
        db.commit()
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, routing_error_handler)
    app.add_middleware(ExternalAccessMiddleware)
    from backend import iam_middleware
    monkeypatch.setattr(iam_middleware, "SessionLocal", sessions)
    app.middleware("http")(iam_middleware.management_audit_middleware)
    def get_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[sqlite_db.get_db] = get_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1, username="admin", role="super_admin")
    app.include_router(access_tokens.router, prefix="/api/v1")
    app.include_router(external_access.router, prefix="/api/v1")
    app.include_router(external_access.openapi_router)
    app.include_router(agents.router, prefix="/api")

    @app.post("/openapi/v1/test-resource/{department}")
    def resource(department: str, request: Request, context=Depends(require_openapi_scope("openapi:agent-manage"))):
        context.department_group(department)
        link_external_resource(request, "agent", "agent-1", department, business_request_id="business-1")
        return context.agent_source("external-1")

    @app.get("/openapi/v1/test-failure")
    def failure():
        raise RuntimeError("private upstream payload")

    @app.get("/openapi/v1/test-validation")
    def validation(limit: int):
        return {"limit": limit}

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, sessions
    engine.dispose()


def partner(client, platform_id="partner", group_id=1):
    body = {"platform_id": platform_id, "name": "Partner", "departments": [{"department_id": "ops", "group_id": group_id}]}
    response = client.post("/api/v1/external-access/platforms", json=body)
    assert response.status_code == 201, response.text
    return body


def token(client, platform_id="partner", **kwargs):
    response = client.post("/api/v1/access/tokens", json={"name": "Integration", "token_type": "openapi",
        "platform_id": platform_id, "allowed_department_ids": ["ops"], "scopes": ["openapi:agent-read", "openapi:agent-manage"], **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def bearer(issued):
    return {"Authorization": f"Bearer {issued['token']}"}


def test_lifecycle_and_request_records(setup):
    client, sessions = setup
    partner(client)
    issued = token(client)
    response = client.get("/openapi/v1/access-context?api_key=never-store", headers={**bearer(issued), "X-Platform-ID": "spoof", "X-Request-ID": "spoof"})
    assert response.status_code == 200
    assert response.json()["platform_id"] == "partner"
    request_id = response.headers["x-request-id"]
    assert response.json()["request_id"] == request_id == "spoof"
    record = client.get("/api/v1/external-access/requests", params={"request_id": request_id}).json()["items"][0]
    assert record["client_request_id"] == request_id
    request_id = record["request_id"]
    assert record["platform_id"] == "partner" and record["token_id"] == issued["record"]["id"]
    assert record["route"] == "/openapi/v1/access-context" and record["status_code"] == 200
    assert "never-store" not in json.dumps(record) and issued["token"] not in json.dumps(record)
    listing = client.get("/api/v1/access/tokens").json()
    assert issued["token"] not in json.dumps(listing)
    with sessions() as db:
        row = db.get(models.AccessToken, issued["record"]["id"])
        assert row.token_hash != issued["token"] and row.last_used_at is not None
    url = f"/api/v1/access/tokens/{issued['record']['id']}"
    assert client.put(url, json={"status": "disabled"}).status_code == 200
    assert client.get("/openapi/v1/access-context", headers=bearer(issued)).status_code == 401
    assert client.get("/api/v1/external-access/requests", params={"token_id": issued["record"]["id"], "outcome": "failed"}).json()["total"] == 1
    assert client.put(url, json={"status": "active"}).status_code == 200
    assert client.post(url + "/revoke").status_code == 200
    assert client.put(url, json={"status": "active"}).status_code == 409
    replacement = token(client)
    assert client.get("/openapi/v1/access-context", headers=bearer(replacement)).status_code == 200
    assert client.get(f"/api/v1/external-access/requests/{request_id}").json()["token_id"] == issued["record"]["id"]


def test_scopes_departments_platform_disable_and_failures(setup, caplog):
    client, sessions = setup
    body = partner(client)
    issued = token(client)
    resource = client.post("/openapi/v1/test-resource/ops", headers=bearer(issued), json={"api_key": "private"})
    assert resource.status_code == 200 and resource.json()["registration_source"] == "external_api"
    detail = client.get("/api/v1/external-access/requests/" + resource.headers["x-request-id"]).json()
    assert detail["resource_id"] == "agent-1" and detail["department_id"] == "ops"
    assert client.post("/openapi/v1/test-resource/other", headers=bearer(issued)).status_code == 403
    read_only = token(client, scopes=["openapi:agent-read"])
    denied = client.post("/openapi/v1/test-resource/ops", headers=bearer(read_only))
    assert denied.status_code == 403
    assert client.get("/api/v1/external-access/requests/" + denied.headers["x-request-id"]).json()["error_code"] == "credential.scope_missing"
    failure = client.get("/openapi/v1/test-failure", headers=bearer(issued))
    assert failure.status_code == 503 and failure.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert client.get("/api/v1/external-access/requests/" + failure.headers["x-request-id"]).json()["error_code"] == "server.internal_error"
    assert "private upstream payload" not in caplog.text
    assert client.get("/openapi/v1/not-real?token=private", headers=bearer(issued)).status_code == 404
    invalid = client.get("/openapi/v1/access-context", headers={"Authorization": "Bearer bad", "X-Platform-ID": "partner"})
    assert invalid.status_code == 401 and invalid.json()["error"]["code"] == "UNAUTHORIZED"
    assert client.get("/api/v1/external-access/requests/" + invalid.headers["x-request-id"]).json()["platform_id"] is None
    body.pop("platform_id")
    assert client.put("/api/v1/external-access/platforms/partner", json={**body, "enabled": False}).status_code == 200
    assert client.put(f"/api/v1/access/tokens/{issued['record']['id']}", json={"allowed_department_ids": ["ops"], "expires_at": None}).status_code == 200
    assert client.get("/openapi/v1/access-context", headers=bearer(issued)).status_code == 403
    failed = client.get("/api/v1/external-access/requests", params={"outcome": "failed", "page_size": 2}).json()
    assert failed["total"] == 6 and len(failed["items"]) == 2
    assert client.get("/api/v1/external-access/requests", params={"platform_id": "unknown"}).json()["total"] == 0
    assert client.get("/api/v1/external-access/requests", params={"resource_id": "agent-1"}).json()["total"] == 1
    assert client.get("/api/v1/external-access/requests", params={"business_request_id": "business-1", "method": "POST", "route": "/openapi/v1/test-resource/{department}"}).json()["total"] == 1
    assert "private" not in json.dumps(client.get("/api/v1/external-access/requests").json())


def test_binding_expiry_validation_and_department_isolation(setup):
    client, sessions = setup
    partner(client)
    partner(client, "second", 2)
    issued = token(client, expires_at=(datetime.now(timezone(timedelta(hours=8))) + timedelta(hours=1)).isoformat())
    assert client.get("/openapi/v1/access-context", headers=bearer(issued)).status_code == 200
    with sessions() as db:
        row = db.get(models.AccessToken, issued["record"]["id"])
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/openapi/v1/access-context", headers=bearer(issued)).json()["error"]["code"] == "UNAUTHORIZED"
    base = {"name": "Test", "token_type": "openapi", "platform_id": "partner", "allowed_department_ids": ["ops"], "scopes": ["openapi:agent-read"]}
    for change in ({"scopes": []}, {"scopes": ["model:chat"]}, {"allowed_department_ids": ["unknown"]}, {"platform_id": "unknown"}):
        assert client.post("/api/v1/access/tokens", json={**base, **change}).status_code == 400
    assert client.put("/api/v1/external-access/platforms/partner", json={"name": "Partner", "departments": [{"department_id": "ops", "group_id": 2}]}).status_code == 409
    from backend.external_access import ExternalAccessContext
    first = ExternalAccessContext("partner", 1, (), {"ops": 1}, "request")
    second = ExternalAccessContext("second", 2, (), {"ops": 2}, "request2")
    assert first.department_group("ops") == 1 and second.department_group("ops") == 2
    assert first.agent_source("a")["source_platform_id"] != second.agent_source("a")["source_platform_id"]
    assert first.task_source()["trigger_source"] == "external_api"


def test_migration_preserves_unknown_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        for table in ("managed_agents", "security_scan_tasks", "access_tokens"):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
            connection.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
    upgrade_external_access_schema(engine)
    upgrade_external_access_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT registration_source FROM managed_agents")).scalar() is None
        assert connection.execute(text("SELECT trigger_source FROM security_scan_tasks")).scalar() is None
        assert connection.execute(text("SELECT allowed_department_ids_json FROM access_tokens")).scalar() == "[]"
    engine.dispose()


def test_request_record_and_partner_management_permissions(setup):
    from backend import iam
    client, sessions = setup
    partner(client)
    with sessions() as db:
        iam.initialize(db)
        db.add(models.Role(name="integration_reader", display_name="Integration reader"))
        db.add(models.RolePermission(role_name="integration_reader", permission_code="external_access:view"))
        db.add_all([models.User(username="reader", role="integration_reader", hashed_password="unused"),
                    models.User(username="root", role="super_admin", hashed_password="unused"),
                    models.User(username="ordinary", role="user", hashed_password="unused")])
        db.commit()
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    assert client.get("/api/v1/external-access/requests").status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "ordinary"})
    assert client.get("/api/v1/external-access/requests").status_code == 403
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "reader"})
    assert client.get("/api/v1/external-access/requests").status_code == 200
    assert client.get("/api/v1/external-access/options").status_code == 200
    assert client.post("/api/v1/external-access/platforms", json={"platform_id": "denied", "name": "Denied"}).status_code == 403
    assert client.get("/api/v1/access/tokens").status_code == 403
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "root"})
    assert client.put("/api/v1/external-access/platforms/partner", json={"name": "Renamed", "departments": [{"department_id": "ops", "group_id": 1}]}).status_code == 200
    with sessions() as db:
        assert db.query(models.ManagementAudit).filter_by(module="external_access", action="update", outcome="success").count() == 1


def test_existing_request_log_schema_is_upgraded_without_losing_records(setup):
    client, sessions = setup
    with sessions() as db:
        engine = db.get_bind()
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_external_api_requests_business_request_id")
        connection.exec_driver_sql("ALTER TABLE external_api_requests DROP COLUMN business_request_id")
        connection.exec_driver_sql("INSERT INTO external_api_requests (request_id, method, created_at) VALUES ('old-request', 'GET', '2026-10-19 00:00:00')")
    assert client.get("/api/v1/external-access/requests?page=1&page_size=20").status_code == 500
    upgrade_external_access_schema(engine)
    upgrade_external_access_schema(engine)
    response = client.get("/api/v1/external-access/requests?page=1&page_size=20")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["request_id"] == "old-request"
    assert response.json()["items"][0]["business_request_id"] is None
    with sessions() as db:
        db.add(models.ExternalApiRequest(request_id="new-request", method="POST", business_request_id="business-1"))
        db.commit()
    filtered = client.get("/api/v1/external-access/requests", params={"business_request_id": "business-1"})
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["request_id"] == "new-request"
    from sqlalchemy import inspect
    assert "ix_external_api_requests_business_request_id" in {i["name"] for i in inspect(engine).get_indexes("external_api_requests")}


def test_missing_credentials_and_temporal_request_filters(setup):
    client, sessions = setup
    missing = client.get("/openapi/v1/access-context")
    assert missing.status_code == 401
    row = client.get("/api/v1/external-access/requests/" + missing.headers["x-request-id"]).json()
    assert row["route"] == "/openapi/v1/access-context" and row["token_id"] is None
    instant = datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8))).isoformat()
    assert client.get("/api/v1/external-access/requests", params={"started_at": instant, "ended_at": instant}).json()["total"] == 1
    assert client.get("/api/v1/external-access/requests", params={"started_at": "2030-01-01", "ended_at": "2029-01-01"}).status_code == 400


def test_validation_does_not_echo_sensitive_values(setup):
    client, _ = setup
    partner(client)
    issued = token(client)
    response = client.get("/openapi/v1/test-validation", params={"limit": "sensitive-input"}, headers=bearer(issued))
    assert response.status_code == 422
    assert "sensitive-input" not in response.text
    record = client.get("/api/v1/external-access/requests/" + response.headers["x-request-id"]).json()
    assert record["error_code"] == "request.validation_failed"
    assert "sensitive-input" not in json.dumps(record)


def test_agent_source_survives_console_edits_and_token_replacement(setup):
    from backend.external_access import ExternalAccessContext
    client, sessions = setup
    partner(client)
    issued = token(client)
    context = ExternalAccessContext("partner", issued["record"]["id"], (), {"ops": 1}, "registration-request")
    with sessions() as db:
        row = models.ManagedAgent(agent_id="internal-agent", name="External agent", department_group_id=1,
                                  **context.agent_source("their-agent"))
        db.add(row)
        db.commit()
        agent_id = row.id
    response = client.put(f"/api/agents/{agent_id}", json={"name": "Updated in console", "registration_source": "console"})
    assert response.status_code == 200, response.text
    assert response.json()["registration_source"] == "external_api"
    assert response.json()["source_platform_name"] == "Partner"
    assert client.post(f"/api/v1/access/tokens/{issued['record']['id']}/revoke").status_code == 200
    token(client)
    items = client.get("/api/agents/assets", params={"registration_source": "external_api", "source_platform_id": "partner"}).json()["items"]
    assert len(items) == 1 and items[0]["source_token_id"] == issued["record"]["id"]
    assert items[0]["external_agent_id"] == "their-agent"
