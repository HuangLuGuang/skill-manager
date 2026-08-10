import os
import logging
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models
from .api_errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .auth import get_current_admin_user, get_password_hash
from .config import settings
from .security import initialize_signing_identity, validate_security_settings
from .routers import access_tokens, agents, auth, clients, config, llm_gateway, mcp_gateway, runtime_governance, security_audit, system, tasks
from .security_audit import append_security_audit, ensure_audit_signing_key
from .sqlite_db import Base, SessionLocal, engine
from .task_runtime import init_default_tasks


load_dotenv(override=True)
base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

os.environ.setdefault("AGENT_MANAGER_REGISTRY_SQLITE_PATH", settings.SQLITE_PATH)

from agent_manager.api.router import (
    get_manager as get_agent_manager,
    router as agent_manager_router,
    runtime_router as agent_runtime_router,
)
from agent_manager.api.scanner_router import admin_router as scanner_admin_router
from agent_manager.api.scanner_router import runtime_router as access_runtime_router
from agent_manager.api.scanner_router import router as scanner_router

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)
logger = logging.getLogger(__name__)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(config.router, prefix=settings.API_PREFIX)
app.include_router(system.router, prefix=settings.API_PREFIX)
app.include_router(tasks.router, prefix=settings.API_PREFIX)
app.include_router(agents.router, prefix=settings.API_PREFIX)
app.include_router(access_tokens.router, prefix=f"{settings.API_PREFIX}/v1")
app.include_router(security_audit.router, prefix=settings.API_PREFIX)
app.include_router(runtime_governance.router, prefix=settings.API_PREFIX)
app.include_router(mcp_gateway.admin_router, prefix=f"{settings.API_PREFIX}/v1", dependencies=[Depends(get_current_admin_user)])
app.include_router(mcp_gateway.runtime_router)
app.include_router(clients.router, prefix=settings.API_PREFIX)
app.include_router(llm_gateway.runtime_router)
app.include_router(llm_gateway.admin_router, prefix=settings.API_PREFIX)
app.include_router(access_runtime_router)
app.include_router(agent_runtime_router, prefix="/api/v1")
app.include_router(agent_manager_router, prefix="/api/v1", dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_admin_router, dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_router)


_AUDITED_ADMIN_PREFIXES = (
    "/api/config/",
    "/api/agents",
    "/api/v1/access/tokens",
    "/api/v1/mcp/",
    "/api/v1/users",
    "/api/v1/groups",
    "/api/v1/model-providers",
    "/api/v1/models",
    "/api/v1/llm-api-keys",
    "/api/v1/privacy-policies",
    "/api/v1/runtime-governance/",
)


@app.middleware("http")
async def append_admin_security_audit(request, call_next):
    response = await call_next(request)
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and any(request.url.path.startswith(prefix) for prefix in _AUDITED_ADMIN_PREFIXES)
        and response.status_code < 500
    ):
        try:
            append_security_audit(
                event_type="admin_mutation",
                actor=getattr(request.state, "security_actor", "authenticated-admin"),
                resource_type="http_route",
                resource_id=request.url.path,
                action=request.method.lower(),
                outcome="success" if response.status_code < 400 else "denied",
                details={"status_code": response.status_code},
            )
        except Exception:
            logger.exception("Failed to append security audit event for %s %s", request.method, request.url.path)
    return response


def ensure_sqlite_schema() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(privacy_policies)").fetchall()}
        if "enabled" not in columns:
            conn.exec_driver_sql("ALTER TABLE privacy_policies ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 1")
        if "entity_rules_json" not in columns:
            conn.exec_driver_sql("ALTER TABLE privacy_policies ADD COLUMN entity_rules_json TEXT NOT NULL DEFAULT '{}'")
        user_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()}
        if "preferred_locale" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN preferred_locale VARCHAR(16)")
        agent_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(managed_agents)").fetchall()}
        if "runtime_token_id" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE managed_agents ADD COLUMN runtime_token_id INTEGER")
        if "created_by" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE managed_agents ADD COLUMN created_by VARCHAR(128)")
        access_token_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(access_tokens)").fetchall()}
        if "bound_client_id" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN bound_client_id VARCHAR(128)")
        if "allowed_mcp_gateways_json" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN allowed_mcp_gateways_json TEXT NOT NULL DEFAULT '[]'")
        if "prompt_guard_mode" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN prompt_guard_mode VARCHAR(32) NOT NULL DEFAULT 'off'")
        if "prompt_guard_llm_review" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN prompt_guard_llm_review BOOLEAN NOT NULL DEFAULT 0")
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS backend_schema_migrations (name VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL)"
        )
        migration = conn.exec_driver_sql(
            "SELECT name FROM backend_schema_migrations WHERE name = 'agent_runtime_prompt_guard_block_v1'"
        ).first()
        if not migration:
            conn.exec_driver_sql(
                "UPDATE access_tokens SET prompt_guard_mode = 'block' WHERE token_type = 'agent_runtime' AND prompt_guard_mode = 'off'"
            )
            conn.exec_driver_sql(
                "INSERT INTO backend_schema_migrations (name, applied_at) VALUES ('agent_runtime_prompt_guard_block_v1', CURRENT_TIMESTAMP)"
            )
        llm_key_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(llm_api_keys)").fetchall()}
        if "prompt_guard_mode" not in llm_key_columns:
            conn.exec_driver_sql("ALTER TABLE llm_api_keys ADD COLUMN prompt_guard_mode VARCHAR(32) NOT NULL DEFAULT 'off'")
        if "prompt_guard_llm_review" not in llm_key_columns:
            conn.exec_driver_sql("ALTER TABLE llm_api_keys ADD COLUMN prompt_guard_llm_review BOOLEAN NOT NULL DEFAULT 0")
        audit_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(llm_request_audit)").fetchall()}
        if "prompt_guard_result_json" not in audit_columns:
            conn.exec_driver_sql("ALTER TABLE llm_request_audit ADD COLUMN prompt_guard_result_json TEXT NOT NULL DEFAULT '{}'")
        if "credential_type" not in audit_columns:
            conn.exec_driver_sql("ALTER TABLE llm_request_audit ADD COLUMN credential_type VARCHAR(32)")
        if "agent_id" not in audit_columns:
            conn.exec_driver_sql("ALTER TABLE llm_request_audit ADD COLUMN agent_id VARCHAR(128)")
        gateway_skill_audit_columns = {
            "skill_id": "VARCHAR(128)",
            "skill_version_id": "VARCHAR(128)",
            "skill_name": "VARCHAR(255)",
            "skill_context_source": "VARCHAR(32)",
            "skill_trust_state": "VARCHAR(32)",
            "skill_alert_severity": "VARCHAR(16)",
            "skill_alert_codes_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column_name, column_type in gateway_skill_audit_columns.items():
            if column_name not in audit_columns:
                conn.exec_driver_sql(f"ALTER TABLE llm_request_audit ADD COLUMN {column_name} {column_type}")
        mcp_audit_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_call_audits)").fetchall()}
        mcp_gateway_skill_columns = {
            "agent_id": "VARCHAR(128)",
            **gateway_skill_audit_columns,
        }
        for column_name, column_type in mcp_gateway_skill_columns.items():
            if mcp_audit_columns and column_name not in mcp_audit_columns:
                conn.exec_driver_sql(f"ALTER TABLE mcp_call_audits ADD COLUMN {column_name} {column_type}")
        mcp_server_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_servers)").fetchall()}
        if mcp_server_columns and "max_response_kb" not in mcp_server_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_servers ADD COLUMN max_response_kb INTEGER NOT NULL DEFAULT 1024")
        mcp_tool_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_tools)").fetchall()}
        if mcp_tool_columns and "risk_level" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN risk_level VARCHAR(16) NOT NULL DEFAULT 'low'")
        if mcp_tool_columns and "rate_limit_per_minute" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN rate_limit_per_minute INTEGER NOT NULL DEFAULT 60")
        if mcp_tool_columns and "max_concurrent" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN max_concurrent INTEGER NOT NULL DEFAULT 5")
        if mcp_tool_columns and "requires_approval" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN requires_approval BOOLEAN NOT NULL DEFAULT 0")
        managed_client_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(managed_clients)").fetchall()}
        if managed_client_columns and "policy_mode" not in managed_client_columns:
            conn.exec_driver_sql("ALTER TABLE managed_clients ADD COLUMN policy_mode VARCHAR(32) NOT NULL DEFAULT 'audit'")
        if managed_client_columns and "governance_mode" not in managed_client_columns:
            conn.exec_driver_sql("ALTER TABLE managed_clients ADD COLUMN governance_mode VARCHAR(32) NOT NULL DEFAULT 'registry'")
        client_skill_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(client_skill_installs)").fetchall()}
        if client_skill_columns and "version_id" not in client_skill_columns:
            conn.exec_driver_sql("ALTER TABLE client_skill_installs ADD COLUMN version_id VARCHAR(128)")
        if client_skill_columns and "version_no" not in client_skill_columns:
            conn.exec_driver_sql("ALTER TABLE client_skill_installs ADD COLUMN version_no INTEGER")
        if client_skill_columns and "source_version" not in client_skill_columns:
            conn.exec_driver_sql("ALTER TABLE client_skill_installs ADD COLUMN source_version VARCHAR(128)")

    # Headroom 压缩字段 migration
    from backend.migrate_compression import migrate as migrate_compression
    migrate_compression()


validate_security_settings(settings)
initialize_signing_identity(allow_create=not settings.ENFORCE_SECURE_STARTUP)
ensure_audit_signing_key()
ensure_sqlite_schema()
get_agent_manager()

uploads_dir = Path(settings.UPLOADS_DIR)
uploads_dir.mkdir(parents=True, exist_ok=True)
data_dir = Path(settings.DATA_DIR)
data_dir.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
frontend_dist = base_dir / "web" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


def bootstrap_admin_user() -> None:
    db = SessionLocal()
    try:
        username = settings.INITIAL_ADMIN_USERNAME.strip() or "admin"
        admin = db.query(models.User).filter(models.User.username == username).first()
        if not admin:
            password = settings.INITIAL_ADMIN_PASSWORD
            if settings.ENFORCE_SECURE_STARTUP:
                if not password or len(password) < 12:
                    raise RuntimeError(
                        "first secure startup requires INITIAL_ADMIN_PASSWORD with at least 12 characters"
                    )
            elif not password:
                password_path = Path(settings.DATA_DIR) / "initial-admin-password"
                password_path.parent.mkdir(parents=True, exist_ok=True)
                if password_path.exists():
                    password = password_path.read_text(encoding="utf-8").strip()
                else:
                    password = secrets.token_urlsafe(24)
                    password_path.write_text(password, encoding="utf-8")
                    password_path.chmod(0o600)
                    print(
                        f"Initial admin password was written to {password_path}; "
                        "delete the file after the first successful login.",
                        file=sys.stderr,
                    )
            db.add(
                models.User(
                    username=username,
                    email="admin@example.com",
                    hashed_password=get_password_hash(password),
                    role="super_admin",
                )
            )
            db.commit()
        init_default_tasks(db)
    finally:
        db.close()


bootstrap_admin_user()


@app.get("/health")
def health_check():
    return {"status": "ok"}


if not frontend_dist.exists():
    @app.get("/")
    def frontend_not_built():
        return JSONResponse(
            {
                "status": "frontend_not_built",
                "message": "Please build the frontend in web/ first.",
            }
        )
