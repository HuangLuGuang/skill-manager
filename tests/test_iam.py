import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, iam, iam_models as im, models
from backend.api_errors import ApiError, api_error_handler, http_error_handler, unhandled_error_handler, validation_error_handler
from backend.routers import iam as routes
from backend.sqlite_db import Base, get_db


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'iam.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        iam.initialize(db)
        db.add_all([
            models.User(username="root", role="super_admin", hashed_password=auth.get_password_hash("Password123!")),
            models.User(username="admin", role="admin", hashed_password=auth.get_password_hash("Password123!")),
            models.User(username="reader", role="user", hashed_password=auth.get_password_hash("Password123!")),
        ])
        db.commit()
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(routes.router, prefix="/api")
    from backend import iam_middleware, sqlite_db
    from backend.routers import agents, auth as login_routes, config, llm_gateway, security_scans, system
    monkeypatch.setattr(sqlite_db, "SessionLocal", sessions)
    monkeypatch.setattr(iam_middleware, "SessionLocal", sessions)
    app.middleware("http")(iam_middleware.management_audit_middleware)
    app.include_router(agents.router, prefix="/api")
    app.include_router(login_routes.router, prefix="/api")
    app.include_router(llm_gateway.admin_router, prefix="/api")
    app.include_router(security_scans.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {auth.create_access_token({'sub': 'root'})}"
    yield client, sessions
    engine.dispose()


def as_user(client, name, session_id=None):
    data = {"sub": name}
    if session_id:
        data["session_id"] = session_id
    client.headers["Authorization"] = f"Bearer {auth.create_access_token(data)}"


PREFIX = "/api/v1/iam"


def test_target_update_records_field_changes_without_connection_secrets(api, monkeypatch):
    from backend.routers import security_scans
    c, sessions = api
    monkeypatch.setattr(security_scans, 'resolve_target_endpoint', lambda *args, **kwargs: ['192.0.2.1'])
    monkeypatch.setattr(security_scans, 'validate_agent_target_config', lambda kind, config: config)
    with sessions() as db:
        db.add(models.SecurityTarget(target_id='audit-target', name='Before', target_type='custom_http',
                                     endpoint_url='https://example.com', created_by='root',
                                     config_json='{"token":"private-test-value"}'))
        db.commit()
    response = c.patch('/api/v1/agent-security/targets/audit-target', json={'name': 'After', 'status': 'disabled'})
    assert response.status_code == 200, response.text
    with sessions() as db:
        events = db.query(im.ManagementAudit).filter_by(module='targets', action='update').all()
        assert len(events) == 1
        event = events[0]
        details = json.loads(event.details_json)
        assert details['before']['name'] == 'Before'
        assert details['after']['name'] == 'After'
        assert details['before']['status'] == 'active'
        assert details['after']['status'] == 'disabled'
        assert details['target_name'] == 'After'
        assert 'private-test-value' not in event.details_json
        assert event.target == 'audit-target'


def test_page_visits_validate_access_and_record_one_event(api):
    c, sessions = api
    paths = ['/dashboard', '/agent-security/scans', '/runtime-traces', '/model-gateway/stats']
    for path in paths:
        assert c.post(f'{PREFIX}/page-visits', json={'path': path}).status_code == 200
    with sessions() as db:
        events = db.query(im.ManagementAudit).filter_by(action='page_view').all()
        assert len(events) == len(paths)
        assert {event.target for event in events} == set(paths)
        assert all(event.actor == 'root' and event.outcome == 'success' for event in events)
    result = c.get(f'{PREFIX}/audit/operation', params={'action': 'page_view'}).json()
    assert set(paths) <= {item['target'] for item in result['items']}
    assert c.post(f'{PREFIX}/page-visits', json={'path': '/dashboard?token=secret'}).status_code == 400
    as_user(c, 'reader')
    assert c.post(f'{PREFIX}/page-visits', json={'path': '/runtime-traces'}).status_code == 403
    c.headers.pop('Authorization')
    assert c.post(f'{PREFIX}/page-visits', json={'path': '/dashboard'}).status_code == 401


def test_branding_defaults_permissions_persistence_and_audit(api):
    c, sessions = api
    initial = c.get('/api/system/branding').json()
    assert initial['system_name_zh'] == '智能体生命周期管理系统'
    data = {'system_name_zh': '客户管理平台', 'system_name_en': 'Customer Console', 'company_name': 'Example Company'}
    as_user(c, 'reader')
    assert c.put('/api/system/branding', json=data).status_code == 403
    as_user(c, 'root')
    assert c.put('/api/system/branding', json={**data, 'system_name_zh': ' '}).status_code == 422
    assert c.put('/api/system/branding', json=data).status_code == 200
    with sessions() as db:
        assert json.loads(db.get(models.SystemConfig, 'system_branding').value) == data
        event = db.query(im.ManagementAudit).filter_by(target='system_branding', outcome='success').one()
        assert json.loads(event.details_json)['after'] == data
    c.headers.pop('Authorization')
    public = c.get('/api/system/branding').json()
    assert all(public[key] == value for key, value in data.items())
    assert set(public) == set(data) | {'logo_url', 'has_custom_logo'}


def test_brand_logo_validates_content_and_can_restore(api, tmp_path, monkeypatch):
    import base64
    from backend.routers import system
    c, _ = api
    monkeypatch.setattr(system, 'LOGO_DIR', str(tmp_path / 'logos'))
    assert c.post('/api/system/logo', files={'file': ('bad.png', b'<html>bad</html>', 'image/png')}).status_code == 400
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZQAAAABJRU5ErkJggg==')
    assert c.post('/api/system/logo', files={'file': ('brand.png', png, 'image/png')}).status_code == 200
    assert c.get('/api/system/branding').json()['has_custom_logo'] is True
    assert c.delete('/api/system/logo').status_code == 200
    assert c.get('/api/system/branding').json()['has_custom_logo'] is False


def test_audit_business_action_filter_groups_http_aliases_without_rewriting_records(api):
    c, sessions = api
    with sessions() as db:
        for action in ["update", "put", "patch", "create", "post", "view", "get", "read"]:
            db.add(im.ManagementAudit(actor="filter-test", module="users", action=action,
                                      target=action, outcome="failed" if action in {"put", "patch"} else "success",
                                      client_ip="127.0.0.1", request_id=action, details_json="{}"))
        db.commit()
    for action, expected in [("update", {"update", "put", "patch"}), ("view", {"view", "get", "read"}),
                             ("create", {"create"}), ("submit", {"post"})]:
        result = c.get(f"{PREFIX}/audit/operation", params={"actor": "filter-test", "action": action}).json()
        assert result["total"] == len(expected)
        assert {row["action"] for row in result["items"]} == expected
    result = c.get(f"{PREFIX}/audit/operation", params={"actor": "filter-test", "action": "update", "outcome": "failed"}).json()
    assert result["total"] == 2


def test_audit_action_filter_matches_display_category(api):
    c, sessions = api
    records = [('dashboard', 'page_view'), ('audit', 'login'), ('audit', 'operation'),
               ('audit', 'security'), ('users', 'get'), ('users', 'read'),
               ('users', 'view'), ('users', 'put'), ('users', 'patch')]
    with sessions() as db:
        for module, action in records:
            db.add(im.ManagementAudit(actor='category-test', module=module, action=action,
                                      target=action, outcome='success', details_json='{}'))
        db.commit()
    for category, expected in [('view', 6), ('page_view', 1), ('update', 2)]:
        result = c.get(f'{PREFIX}/audit/operation', params={'actor': 'category-test', 'action': category}).json()
        assert result['total'] == expected
        assert {row['action_category'] for row in result['items']} == {category}
    with sessions() as db:
        assert {row.action for row in db.query(im.ManagementAudit).filter_by(actor='category-test')} == {action for _, action in records}


def test_security_audit_event_identity_and_failure_filter(api):
    from datetime import datetime
    c, sessions = api
    with sessions() as db:
        db.add(models.SecurityAuditEvent(
            event_id="security-event-123", timestamp=datetime.utcnow(),
            event_type="runtime_trace.raw_export_reauthentication_failed", actor="root",
            resource_type="runtime_trace", resource_id="trace-42", action="export",
            outcome="failure", details_json="{}", prev_hash="0" * 64,
            event_hash="1" * 64, key_id="test", signature="test",
        ))
        db.commit()
    for keyword in ("security-event-123", "raw_export_reauthentication_failed"):
        response = c.get(f"{PREFIX}/audit/security", params={"outcome": "failed", "q": keyword})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        event = response.json()["items"][0]
        assert event["event_id"] == "security-event-123"
        assert event["event_type"] == "runtime_trace.raw_export_reauthentication_failed"
        assert event["request_id"] == ""
        assert event["outcome"] == "failed"
    assert c.get(f"{PREFIX}/audit/security", params={"outcome": "success"}).json()["total"] == 0


def test_account_lifecycle_and_audit(api):
    c, sessions = api
    result = c.post(f"{PREFIX}/users", json={"username": "new", "password": "Password123!", "role": "user"})
    assert result.status_code == 200, result.text
    uid = result.json()["id"]
    assert "hashed_password" not in result.json()
    assert c.post(f"{PREFIX}/users", json={"username": "new", "password": "Password123!"}).status_code == 409
    assert c.put(f"{PREFIX}/users/{uid}", json={"email": "new@example.com"}).status_code == 200
    assert c.get(f"{PREFIX}/users", params={"q": "new@example.com"}).json()["total"] == 1
    assert c.post(f"{PREFIX}/users/{uid}/password", json={"password": "short"}).status_code == 422
    assert c.post(f"{PREFIX}/users/{uid}/password", json={"password": "NewPassword!"}).status_code == 200
    as_user(c, "new")
    assert c.get(f"{PREFIX}/access").status_code == 401
    as_user(c, "root")
    assert c.put(f"{PREFIX}/users/{uid}", json={"is_active": False}).status_code == 200
    assert c.delete(f"{PREFIX}/users/{uid}").status_code == 200
    events = c.get(f"{PREFIX}/audit/operation", params={"target": str(uid)}).json()["items"]
    assert {"create", "update", "reset_password", "set_status", "delete"} <= {r["action"] for r in events}
    assert "NewPassword!" not in json.dumps(events)


def test_reader_cannot_mutate_and_permissions_update_immediately(api):
    c, sessions = api
    assert c.post(f"{PREFIX}/roles", json={"name": "operator", "display_name": "Operator"}).status_code == 200
    assert c.put(f"{PREFIX}/roles/operator/permissions", json={"permissions": ["users:view"], "default_path": "/users"}).status_code == 200
    with sessions() as db:
        db.query(models.User).filter_by(username="reader").one().role = "operator"
        db.commit()
    as_user(c, "reader")
    assert c.get(f"{PREFIX}/users").status_code == 200
    assert c.post(f"{PREFIX}/users", json={"username": "evil", "password": "Password123!"}).status_code == 403
    as_user(c, "root")
    assert c.put(f"{PREFIX}/roles/operator/permissions", json={"permissions": [], "default_path": ""}).status_code == 200
    as_user(c, "reader")
    assert c.get(f"{PREFIX}/users").status_code == 403
    assert c.get(f"{PREFIX}/access").json()["default_path"] == "/access-denied"


def test_delegated_account_admin_cannot_escalate(api):
    c, sessions = api
    c.post(f"{PREFIX}/roles", json={"name": "account_operator", "display_name": "Operator"})
    codes = ["users:view", "users:create", "users:assign_role", "users:update", "dashboard:view", "skills:view"]
    assert c.put(f"{PREFIX}/roles/account_operator/permissions", json={"permissions": codes}).status_code == 200
    with sessions() as db:
        db.query(models.User).filter_by(username="reader").one().role = "account_operator"
        db.commit()
    as_user(c, "reader")
    assert c.post(f"{PREFIX}/users", json={"username": "ok", "password": "Password123!", "role": "user"}).status_code == 200
    assert c.post(f"{PREFIX}/users", json={"username": "evil", "password": "Password123!", "role": "super_admin"}).status_code == 403
    assert c.put(f"{PREFIX}/users/1", json={"email": "evil@example.com"}).status_code == 403


def test_role_integrity_home_and_delete(api):
    c, _ = api
    c.post(f"{PREFIX}/roles", json={"name": "custom", "display_name": "Custom"})
    for codes in [["users:view", "users:view"], ["madeup:view"]]:
        assert c.put(f"{PREFIX}/roles/custom/permissions", json={"permissions": codes}).status_code == 400
    assert c.put(f"{PREFIX}/roles/custom/permissions", json={"permissions": ["users:view"], "default_path": "/roles"}).status_code == 400
    assert c.put(f"{PREFIX}/roles/custom/permissions", json={"permissions": ["privacy_audit:raw"]}).status_code == 400
    assert c.delete(f"{PREFIX}/roles/admin").status_code == 400
    assert c.delete(f"{PREFIX}/roles/custom").status_code == 200


def test_menu_cycle_depth_sort_and_navigation(api):
    c, _ = api
    menu = {"name": "custom", "title_zh": "测试", "title_en": "Test", "icon": "setting", "path": None}
    assert c.post(f"{PREFIX}/menus", json=menu).status_code == 200
    child = {**menu, "name": "child", "parent_name": "custom", "path": "/users"}
    assert c.post(f"{PREFIX}/menus", json=child).status_code == 200
    assert c.delete(f"{PREFIX}/menus/custom").status_code == 409
    assert c.put(f"{PREFIX}/menus/custom", json={k: v for k, v in {**menu, "parent_name": "custom"}.items() if k != "name"}).status_code == 400
    assert c.post(f"{PREFIX}/menus/child/move", json={"direction": "up"}).status_code == 200
    assert c.put(f"{PREFIX}/menus/custom", json={k: v for k, v in {**menu, "is_active": False}.items() if k != "name"}).status_code == 200
    nav = c.get(f"{PREFIX}/access").json()["menus"]
    assert not any(m["name"] == "custom" for m in nav)
    assert c.delete(f"{PREFIX}/menus/child").status_code == 200
    assert c.delete(f"{PREFIX}/menus/custom").status_code == 200


def test_account_dependencies_and_disabled_token(api):
    c, sessions = api
    with sessions() as db:
        reader = db.query(models.User).filter_by(username="reader").one()
        reader.is_active = False
        db.add(models.UserGroup(name="linked"))
        db.commit()
    as_user(c, "reader")
    assert c.get(f"{PREFIX}/access").status_code == 403
    as_user(c, "root")
    assert c.delete(f"{PREFIX}/users/1").status_code == 400


def test_audit_filters_pagination_and_legacy_records(api):
    c, sessions = api
    with sessions() as db:
        db.add(models.OperationLog(username="old", action="修改设置", target="test", details="original"))
        db.add(models.LoginLog(username="old", ip_address="127.0.0.1", status="Failed"))
        db.commit()
    data = c.get(f"{PREFIX}/audit/operation", params={"actor": "old", "page_size": 1}).json()
    assert data["total"] == 1 and data["items"][0]["details"] == {"original": "original"}
    assert c.get(f"{PREFIX}/audit/login", params={"outcome": "failed"}).json()["total"] == 1
    assert c.get(f"{PREFIX}/audit/login", params={"outcome": "success"}).json()["total"] == 0
    as_user(c, "reader")
    assert c.get(f"{PREFIX}/audit/operation").status_code == 403


def test_initialization_preserves_configuration(api):
    _, sessions = api
    with sessions() as db:
        db.get(im.Menu, "users").title_en = "People"
        db.commit()
        iam.initialize(db)
        assert db.get(im.Menu, "users").title_en == "People"


def test_builtin_role_translation_migration_preserves_custom_names(api):
    _, sessions = api
    with sessions() as db:
        admin = db.get(im.Role, "admin")
        admin.display_key = None
        auditor = db.get(im.Role, "auditor")
        auditor.display_key = None
        auditor.display_name = "Compliance team"
        db.commit()
        iam.initialize(db)
        assert admin.display_key == "iam.roleNames.admin"
        assert auditor.display_key is None
        assert auditor.display_name == "Compliance team"


def test_permission_catalog_upgrade_preserves_custom_grants_and_fixed_admin_access(api):
    _, sessions = api
    with sessions() as db:
        db.add(im.Permission(code="retired:operation", module="retired", action="operation"))
        db.flush()
        db.add(im.RolePermission(role_name="user", permission_code="retired:operation"))
        db.query(im.RolePermission).filter_by(role_name="admin", permission_code="roles:view").delete()
        db.query(im.RolePermission).filter_by(role_name="auditor", permission_code="audit:security").delete()
        db.commit()
        iam.initialize(db)
        assert db.get(im.Permission, "retired:operation") is None
        assert db.get(im.RolePermission, ("user", "retired:operation")) is None
        assert db.get(im.RolePermission, ("admin", "roles:view")) is not None
        assert db.get(im.RolePermission, ("auditor", "audit:security")) is None


def test_legacy_registration_uses_management_authorization(api):
    c, sessions = api
    c.headers.pop("Authorization")
    response = c.post("/api/auth/register", json={"username": "bypass", "password": "Password123!", "role": "super_admin"})
    assert response.status_code == 401
    with sessions() as db:
        assert db.query(models.User).filter_by(username="bypass").first() is None


def test_account_validation_is_shared_by_legacy_and_new_entrypoints(api):
    c, sessions = api
    for path in (f"{PREFIX}/users", "/api/auth/register", "/api/v1/users"):
        for username in ("   ", "中文账号", "user name", "user@test", "user/abc", "usér", "user\n"):
            response = c.post(path, json={"username": username, "password": "Password123!", "role": "user"})
            assert response.status_code == 422, response.text
            assert response.json().get("error_code")
    response = c.post(f"{PREFIX}/users", json={"username": "User_01.test-name", "password": "Password123!", "role": "user"})
    assert response.status_code == 200, response.text
    uid = response.json()["id"]
    for field in ("role", "is_active", "group_ids"):
        response = c.put(f"/api/v1/users/{uid}", json={field: None})
        assert response.status_code == 422, response.text
        assert response.json()["error_code"] == "iam.invalid_account"
    with sessions() as db:
        user = db.get(models.User, uid)
        assert user.role == "user"
        assert user.is_active is True


def test_scan_view_permission_does_not_reveal_sensitive_originals(api):
    c, sessions = api
    with sessions() as db:
        db.add(im.Role(name="scan_viewer", display_name="Scan viewer"))
        db.flush()
        db.add(im.RolePermission(role_name="scan_viewer", permission_code="scans:view"))
        db.query(models.User).filter_by(username="reader").one().role = "scan_viewer"
        db.commit()
    as_user(c, "reader")
    endpoints = {
        "/api/v1/agent-security/tasks/missing/artifacts/missing/content": "scans:raw",
        "/api/v1/agent-security/tasks/missing/inventory/items/missing/content": "privacy_audit:raw",
    }
    for path, code in endpoints.items():
        response = c.get(path)
        assert response.status_code == 403, response.text
        with sessions() as db:
            audit = db.query(im.ManagementAudit).filter_by(target=path, outcome="denied").one()
            assert f"{audit.module}:{audit.action}" == code


def test_permission_editor_options_follow_sensitive_roles_and_enabled_navigation(api):
    c, _ = api
    options = c.get(f"{PREFIX}/options").json()
    roles = {row["name"]: row for row in options["roles"]}
    assert "privacy_audit:raw" not in roles["user"]["grantable_permissions"]
    assert "privacy_audit:raw" in roles["privacy_auditor"]["grantable_permissions"]
    assert roles["super_admin"]["grantable_permissions"] == []
    assert "/users" in options["home_pages"]
    assert c.post(f"{PREFIX}/menus/system-admin/status", json={"is_active": False}).status_code == 200
    assert "/users" not in c.get(f"{PREFIX}/options").json()["home_pages"]


def test_privacy_upsert_checks_actual_create_or_update_permission(api):
    c, sessions = api
    with sessions() as db:
        db.add(im.Role(name="policy_editor", display_name="Policy editor"))
        db.flush()
        db.add(im.RolePermission(role_name="policy_editor", permission_code="privacy:update"))
        db.query(models.User).filter_by(username="reader").one().role = "policy_editor"
        db.add(models.PrivacyPolicy(name="Existing policy", entity_types_json="[]"))
        db.commit()
        policy_id = db.query(models.PrivacyPolicy).filter_by(name="Existing policy").one().id
    as_user(c, "reader")
    assert c.post("/api/v1/privacy-policies", json={"name": "New policy"}).status_code == 403
    response = c.post("/api/v1/privacy-policies", json={"id": policy_id, "name": "Updated policy"})
    assert response.status_code == 200, response.text
    assert c.put(f"/api/v1/privacy-policies/{policy_id}/default").status_code == 200
    with sessions() as db:
        db.query(im.RolePermission).filter_by(role_name="policy_editor").delete()
        db.add(im.RolePermission(role_name="policy_editor", permission_code="privacy:create"))
        db.commit()
    assert c.post("/api/v1/privacy-policies", json={"id": policy_id, "name": "Forbidden update"}).status_code == 403
    assert c.put(f"/api/v1/privacy-policies/{policy_id}/default").status_code == 403


def test_credential_policy_options_do_not_require_policy_edit_permission(api):
    from backend.routers import access_tokens
    c, sessions = api
    c.app.include_router(access_tokens.router, prefix="/api/v1")
    with sessions() as db:
        db.add(im.Role(name="credential_editor", display_name="Credential editor"))
        db.flush()
        db.add(im.RolePermission(role_name="credential_editor", permission_code="credentials:update"))
        db.query(models.User).filter_by(username="reader").one().role = "credential_editor"
        db.commit()
    as_user(c, "reader")
    response = c.get("/api/v1/access/tokens/privacy-policies")
    assert response.status_code == 200
    assert set(response.json()[0]) == {"id", "name", "is_default"}
    assert c.put(f"/api/v1/privacy-policies/{response.json()[0]['id']}/default").status_code == 403
    with sessions() as db:
        db.query(im.RolePermission).filter_by(role_name="credential_editor").delete()
        db.commit()
    assert c.get("/api/v1/access/tokens/privacy-policies").status_code == 403


def test_audit_date_ranges_normalize_offsets_and_record_read_permission(api):
    c, sessions = api
    response = c.get(f"{PREFIX}/audit/login", params={"since": "2026-09-10T08:00:00+08:00", "until": "2026-09-10T01:00:00"})
    assert response.status_code == 200, response.text
    with sessions() as db:
        row = db.query(im.ManagementAudit).filter_by(target=f"{PREFIX}/audit/login").order_by(im.ManagementAudit.id.desc()).first()
        assert (row.module, row.action) == ("audit", "login")
    response = c.get(f"{PREFIX}/audit/login", params={"since": "2026-09-10T10:00:00+08:00", "until": "2026-09-10T01:00:00"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "iam.invalid_date_range"


def test_login_request_correlation_and_personal_password_audit(api):
    c, sessions = api
    failed = c.post("/api/auth/token", data={"username": "root", "password": "wrong", "captcha_id": "missing", "captcha_code": "missing"})
    assert failed.status_code == 400
    with sessions() as db:
        log = db.query(models.LoginLog).order_by(models.LoginLog.id.desc()).first()
        assert log.request_id == failed.headers["X-Request-ID"]
        assert log.status == "captcha_expired"
    response = c.post("/api/auth/users/me/password", json={"old_password": "wrong-password", "new_password": "ChangedPassword123!"})
    assert response.status_code == 400
    response = c.post("/api/auth/users/me/password", json={"old_password": "Password123!", "new_password": "ChangedPassword123!"})
    assert response.status_code == 200, response.text
    assert c.get(f"{PREFIX}/access").status_code == 401
    with sessions() as db:
        logs = db.query(im.ManagementAudit).filter_by(module="auth", action="change_password").all()
        assert {row.outcome for row in logs} == {"failed", "success"}
        assert all(row.request_id for row in logs)
        assert all("Password" not in row.details_json and "password" not in row.details_json for row in logs)


def test_iam_schema_upgrade_preserves_old_login_records(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old-schema.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE iam_roles (name TEXT PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE iam_menus (name TEXT PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE login_logs (id INTEGER PRIMARY KEY, username TEXT)")
        connection.exec_driver_sql("INSERT INTO login_logs (id, username) VALUES (1, 'historical-user')")
    iam.migrate(engine)
    iam.migrate(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT username, request_id FROM login_logs").one() == ("historical-user", "")
    engine.dispose()


def test_real_business_route_permissions_and_denied_audit(api):
    c, sessions = api
    c.post(f"{PREFIX}/roles", json={"name": "agent_reader", "display_name": "Agent reader"})
    c.put(f"{PREFIX}/roles/agent_reader/permissions", json={"permissions": ["agents:view"]})
    with sessions() as db:
        db.query(models.User).filter_by(username="reader").one().role = "agent_reader"
        db.commit()
    as_user(c, "reader")
    assert c.get("/api/agents").status_code == 200
    assert c.post("/api/agents", json={"agent_id": "denied", "name": "denied"}).status_code == 403
    with sessions() as db:
        event = db.query(im.ManagementAudit).filter_by(actor="reader", module="agents", outcome="denied").one()
        assert event.action == "create"
        assert event.request_id
        assert db.query(models.ManagedAgent).filter_by(agent_id="denied").first() is None


def test_failed_account_change_rolls_back_and_records_failure(api):
    c, sessions = api
    uid = c.post(f"{PREFIX}/users", json={"username": "rollback", "password": "Password123!"}).json()["id"]
    response = c.put(f"{PREFIX}/users/{uid}", json={"email": "changed@example.com", "group_ids": [9999]})
    assert response.status_code == 400
    with sessions() as db:
        assert db.get(models.User, uid).email is None
        assert db.query(im.ManagementAudit).filter_by(outcome="failed", target=f"{PREFIX}/users/{uid}").count() == 1


def test_unexpected_account_failure_rolls_back_and_audits_without_exception_secrets(api, monkeypatch):
    c, sessions = api
    uid = c.post(f"{PREFIX}/users", json={"username": "exception-test", "password": "Password123!"}).json()["id"]

    def fail_update(db, request, actor, account, changes):
        account.email = changes["email"]
        db.flush()
        raise RuntimeError("upstream-secret-must-not-be-logged")

    monkeypatch.setattr(iam, "update_account", fail_update)
    with TestClient(c.app, raise_server_exceptions=False) as client:
        response = client.put(f"{PREFIX}/users/{uid}", headers=c.headers, json={"email": "rollback@example.com"})
    assert response.status_code == 500
    with sessions() as db:
        assert db.get(models.User, uid).email is None
        event = db.query(im.ManagementAudit).filter_by(target=f"{PREFIX}/users/{uid}", outcome="failed").one()
        assert event.actor == "root"
        assert event.request_id == response.headers["X-Request-ID"]
        assert json.loads(event.details_json) == {"status_code": 500}


def test_group_audit_and_account_dependency_check(api):
    c, sessions = api
    with sessions() as db:
        group = models.UserGroup(name="team")
        db.add(group)
        db.commit()
        gid = group.id
    result = c.post(f"{PREFIX}/users", json={"username": "member", "password": "Password123!", "group_ids": [gid]})
    assert result.status_code == 200, result.text
    uid = result.json()["id"]
    with sessions() as db:
        entry = db.query(im.ManagementAudit).filter_by(module="users", action="create", target=str(uid)).one()
        assert json.loads(entry.details_json)["after"]["group_ids"] == [gid]
        db.add(models.LlmApiKey(name="linked", key_hash="hash", key_prefix="test", user_id=uid))
        db.commit()
    assert c.delete(f"{PREFIX}/users/{uid}").status_code == 409


def test_concurrent_duplicate_account_is_idempotently_rejected(api):
    from concurrent.futures import ThreadPoolExecutor
    c, sessions = api
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: c.post(f"{PREFIX}/users", json={"username": "concurrent", "password": "Password123!"}), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with sessions() as db:
        assert db.query(models.User).filter_by(username="concurrent").count() == 1
        assert db.query(im.ManagementAudit).filter_by(module="users", action="create", outcome="success").count() == 1


def test_concurrent_admin_disables_preserve_one_active_administrator(api):
    from concurrent.futures import ThreadPoolExecutor
    c, sessions = api
    with sessions() as db:
        db.query(models.User).filter_by(username="root").one().is_active = False
        db.query(models.User).filter_by(username="reader").one().role = "admin"
        db.commit()
        ids = {user.username: user.id for user in db.query(models.User)}

    def disable_other(pair):
        actor, target = pair
        token = auth.create_access_token({"sub": actor})
        return c.put(f"{PREFIX}/users/{ids[target]}", json={"is_active": False}, headers={"Authorization": f"Bearer {token}"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(disable_other, [("admin", "reader"), ("reader", "admin")]))
    assert sum(response.status_code == 200 for response in responses) == 1
    assert all(response.status_code in {200, 401, 403} for response in responses)
    with sessions() as db:
        assert db.query(models.User).filter(models.User.role == "admin", models.User.is_active.is_(True)).count() == 1
        assert db.query(im.ManagementAudit).filter_by(module="users", action="set_status", outcome="success").count() == 1


def test_documentation_editor_can_load_its_configuration_without_reader_grant(api):
    c, sessions = api
    with sessions() as db:
        db.add(im.Role(name="docs_editor", display_name="Documentation editor"))
        db.flush()
        db.add(im.RolePermission(role_name="docs_editor", permission_code="docs:update"))
        db.query(models.User).filter_by(username="reader").one().role = "docs_editor"
        db.commit()
    as_user(c, "reader")
    path = "/api/config/docs-assistant"
    response = c.get(path)
    assert response.status_code == 200, response.text
    config = response.json()
    config["welcome_en"] = "Updated documentation welcome"
    assert c.post(path, json=config).status_code == 200
    assert c.get(path).json()["welcome_en"] == config["welcome_en"]
    with sessions() as db:
        db.query(im.RolePermission).filter_by(role_name="docs_editor").delete()
        db.add(im.RolePermission(role_name="docs_editor", permission_code="docs:view"))
        db.commit()
    assert c.get(path).status_code == 200
    assert c.post(path, json=config).status_code == 403


def test_prompt_guard_menu_title_upgrade_preserves_custom_names(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'menu-upgrade.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        iam.initialize(db)
        menu = db.get(im.Menu, 'prompt-guard')
        menu.title_zh, menu.title_en, menu.title_key = 'Prompt 防护测试', 'Prompt Guard Test', None
        db.commit()
        iam.initialize(db)
        iam.initialize(db)
        assert (menu.title_zh, menu.title_en, menu.title_key) == ('Prompt 防护', 'Prompt Guard', 'iam.navigation.prompt-guard')
        menu.title_zh, menu.title_en, menu.title_key = '企业提示防护', 'Enterprise Guard', None
        db.commit()
        iam.initialize(db)
        assert (menu.title_zh, menu.title_en, menu.title_key) == ('企业提示防护', 'Enterprise Guard', None)


def test_user_stats_menu_is_consolidated_on_new_and_upgraded_installs(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'stats-menu.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        iam.initialize(db)
        assert db.get(im.Menu, 'user-stats') is None
        db.add(im.Menu(name='user-stats', parent_name='model-gateway', title_zh='用户 Token 分析',
                       title_en='User Token Analytics', path='/model-gateway/user-stats', is_system=True))
        db.commit()
        iam.initialize(db)
        iam.initialize(db)
        assert db.get(im.Menu, 'user-stats').is_active is False
        nav = json.dumps(iam.visible_navigation(db, {'privacy_audit:view'}))
        assert '/model-gateway/stats' in nav
        assert '/model-gateway/user-stats' not in nav
    engine.dispose()
