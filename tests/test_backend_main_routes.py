from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.request_limits import WorkerCompletionBodyLimitMiddleware


def test_access_token_admin_routes_are_mounted_under_api_v1():
    main_py = Path("backend/main.py").read_text(encoding="utf-8")

    assert 'app.include_router(access_tokens.router, prefix=f"{settings.API_PREFIX}/v1")' in main_py
    assert "mcp_gateway.admin_router" in main_py
    assert 'prefix=f"{settings.API_PREFIX}/v1"' in main_py
    assert "app.include_router(mcp_gateway.runtime_router)" in main_py
    assert "app.include_router(security_audit.router, prefix=settings.API_PREFIX)" in main_py
    assert "agent_security.router" in main_py
    assert "Depends(get_current_security_reader)" in main_py
    assert "app.include_router(security_scans.router, prefix=settings.API_PREFIX)" in main_py
    assert "agent_security_p1_v1" in main_py
    assert "agent_security_p2_v1" in main_py
    assert '"scan_options_encrypted": "TEXT"' in main_py
    assert '"public_key_algorithm": "VARCHAR(64)"' in main_py
    assert '"environment": "VARCHAR(32) NOT NULL DEFAULT \'test\'"' in main_py
    assert '"allowed_capabilities_json": "TEXT NOT NULL DEFAULT' in main_py
    assert '"production_target_ids_json": "TEXT NOT NULL DEFAULT \'[]\'"' in main_py
    assert '"maintenance_window_start": "DATETIME"' in main_py
    assert '"maintenance_window_end": "DATETIME"' in main_py
    assert '"dedicated_identity_ref": "VARCHAR(128)"' in main_py
    assert '"approval_id": "VARCHAR(64)"' in main_py
    assert "agent_security_p6_production_approval_v1" in main_py
    assert "ADD COLUMN access_mode VARCHAR(32) NOT NULL DEFAULT 'unknown'" in main_py
    assert '"execution_mode": "VARCHAR(32) NOT NULL DEFAULT \'active_safe\'"' in main_py
    assert '"production_tool_denylist_json": "TEXT NOT NULL DEFAULT \'[]\'"' in main_py
    assert "agent_security_p6_tool_policy_v1" in main_py
    assert '"kill_switch_activated": "BOOLEAN NOT NULL DEFAULT 0"' in main_py
    assert "agent_security_p6_kill_switch_v1" in main_py
    assert '"risk_codes_json": "TEXT NOT NULL DEFAULT \'[]\'"' in main_py
    assert "agent_security_p6_asi_mapping_v1" in main_py


def test_p6_production_approval_schema_upgrades_existing_sqlite(tmp_path, monkeypatch):
    import backend.main as backend_main
    import backend.migrate_compression as migrate_compression

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE security_scan_policies (id INTEGER PRIMARY KEY, policy_id VARCHAR(64))")
        conn.exec_driver_sql("CREATE TABLE security_scan_tasks (id INTEGER PRIMARY KEY, task_id VARCHAR(64))")
        conn.exec_driver_sql("CREATE TABLE security_findings (id INTEGER PRIMARY KEY, finding_id VARCHAR(64))")
        conn.exec_driver_sql("CREATE TABLE runtime_trace_sessions (id INTEGER PRIMARY KEY, trace_id VARCHAR(64))")
        conn.exec_driver_sql("CREATE TABLE runtime_trace_events (id INTEGER PRIMARY KEY, event_id VARCHAR(64))")
        conn.exec_driver_sql("CREATE TABLE mcp_tools (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE mcp_gateways (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr(backend_main, "engine", legacy_engine)
    monkeypatch.setattr(migrate_compression, "migrate", lambda: None)
    backend_main.ensure_sqlite_schema()

    with legacy_engine.connect() as conn:
        policy_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_scan_policies)")}
        task_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_scan_tasks)")}
        approval_table = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'security_scan_approvals'"
        ).first()
        migration = conn.exec_driver_sql(
            "SELECT name FROM backend_schema_migrations WHERE name = 'agent_security_p6_production_approval_v1'"
        ).first()
        tool_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_tools)")}
        gateway_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_gateways)")}
        tool_policy_migration = conn.exec_driver_sql(
            "SELECT name FROM backend_schema_migrations WHERE name = 'agent_security_p6_tool_policy_v1'"
        ).first()
        kill_switch_migration = conn.exec_driver_sql(
            "SELECT name FROM backend_schema_migrations WHERE name = 'agent_security_p6_kill_switch_v1'"
        ).first()
        finding_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_findings)")}
        trace_session_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(runtime_trace_sessions)")}
        trace_event_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(runtime_trace_events)")}
        asi_mapping_migration = conn.exec_driver_sql(
            "SELECT name FROM backend_schema_migrations WHERE name = 'agent_security_p6_asi_mapping_v1'"
        ).first()
        report_contract_migration = conn.exec_driver_sql(
            "SELECT name FROM backend_schema_migrations WHERE name = 'agent_security_p6_report_contract_v1'"
        ).first()

    assert {"production_target_ids_json", "maintenance_window_start", "maintenance_window_end", "dedicated_identity_ref"} <= policy_columns
    assert {"approval_id", "kill_switch_activated", "kill_switch_activated_at", "kill_switch_activated_by", "kill_switch_reason"} <= task_columns
    assert {"report_template_version", "decision_criteria_version", "report_contract_json"} <= task_columns
    assert approval_table == ("security_scan_approvals",)
    assert migration == ("agent_security_p6_production_approval_v1",)
    assert "access_mode" in tool_columns
    assert {"environment", "execution_mode", "production_tool_denylist_json"} <= gateway_columns
    assert tool_policy_migration == ("agent_security_p6_tool_policy_v1",)
    assert kill_switch_migration == ("agent_security_p6_kill_switch_v1",)
    assert {"risk_codes_json", "risk_mapping_json"} <= finding_columns
    assert "decision_criteria_version" in finding_columns
    assert "risk_mapping_version" in trace_session_columns
    assert "risk_mapping_json" in trace_event_columns
    assert asi_mapping_migration == ("agent_security_p6_asi_mapping_v1",)
    assert report_contract_migration == ("agent_security_p6_report_contract_v1",)


def test_api_entrypoints_use_supported_lifespan_startup():
    backend_main = Path("backend/main.py").read_text(encoding="utf-8")
    api_cli = Path("agent_manager/api/api_cli.py").read_text(encoding="utf-8")

    assert "lifespan=application_lifespan" in backend_main
    assert "cleanup_runtime_traces_once()" in backend_main
    assert "asyncio.create_task(runtime_trace_retention_loop())" in backend_main
    assert "lifespan=lifespan_with_startup(warmup_skill_scanner)" in api_cli
    assert 'add_event_handler("startup"' not in backend_main
    assert 'add_event_handler("startup"' not in api_cli


def test_worker_completion_body_limit_runs_before_endpoint_parsing():
    app = FastAPI()
    app.add_middleware(WorkerCompletionBodyLimitMiddleware, max_bytes=32)

    @app.post("/api/v1/agent-security/worker/tasks/{task_id}/complete")
    async def complete(task_id: str, request: Request):
        return {"task_id": task_id, "size": len(await request.body())}

    with TestClient(app) as client:
        allowed = client.post("/api/v1/agent-security/worker/tasks/task-1/complete", content=b"x" * 32)
        rejected = client.post("/api/v1/agent-security/worker/tasks/task-1/complete", content=b"x" * 33)

    assert allowed.status_code == 200
    assert allowed.json()["size"] == 32
    assert rejected.status_code == 413
    assert rejected.json()["error_code"] == "agent_security.worker_completion_body_too_large"


def test_deploy_smoke_checks_backend_image_before_replacing_production():
    gitlab_ci = Path(".gitlab-ci.yml").read_text(encoding="utf-8")

    build_position = gitlab_ci.index('./build.sh -t "$IMAGE_TAG" -p linux/amd64 --all')
    smoke_position = gitlab_ci.index("from backend.main import app")
    deploy_position = gitlab_ci.index('install -m 0644 docker-compose.yaml "$DEPLOY_DIR/docker-compose.yaml"')

    assert build_position < smoke_position < deploy_position
    assert "with TestClient(app) as client:" in gitlab_ci
    assert 'response = client.get("/health")' in gitlab_ci
    assert "response.raise_for_status()" in gitlab_ci
    assert "BUILD_SECURITY_WORKER=true" in Path("build.sh").read_text(encoding="utf-8")


def test_mcp_runtime_is_proxied_in_dev_and_deployment():
    vite_config = Path("web/vite.config.js").read_text(encoding="utf-8")
    nginx_config = Path("deploy/nginx/default.conf").read_text(encoding="utf-8")

    assert "'/mcp/':" in vite_config
    assert "location /mcp/" in nginx_config
    assert "proxy_pass http://skill_manager_backend;" in nginx_config
