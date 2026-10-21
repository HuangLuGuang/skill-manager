import asyncio
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models
from .api_errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    routing_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .auth import get_current_admin_user, get_current_security_reader, get_password_hash
from .config import settings
from .dify_inventory_migration import migrate_dify_asset_inventory
from .request_limits import WorkerCompletionBodyLimitMiddleware
from .license_policy import enforce_license_request, license_error_handler
from agent_manager.core.licensing import LicenseError
from .routers import license as license_routes
from .routers import (
    access_tokens,
    aidr,
    aidr_enforcement,
    agent_security,
    agents,
    asset_lifecycle,
    auth,
    clients,
    dashboard,
    external_ai_gateways,
    iam,
    config,
    llm_gateway,
    mcp_gateway,
    runtime_governance,
    runtime_traces,
    dify_runtime,
    security_audit,
    audit_trail,
    security_scans,
    scan_schedules,
    system,
    tasks,
)
from .security import initialize_signing_identity, validate_security_settings
from .security_audit import append_security_audit, ensure_audit_signing_key
from .security_target_migration import migrate_security_target_classification
from .security_worker_bootstrap import bootstrap_builtin_security_worker_once
from .services.runtime_traces import cleanup_expired
from .services.retention import retention_loop
from .services.pipeline_trace_retention import cleanup_once as cleanup_pipeline_traces_once
from .sqlite_db import Base, SessionLocal, engine
from .task_runtime import init_default_tasks

load_dotenv(override=True)
base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

os.environ.setdefault("AGENT_MANAGER_REGISTRY_SQLITE_PATH", settings.SQLITE_PATH)

from agent_manager.api.router import (
    get_manager as get_agent_manager,
)
from agent_manager.api.router import (
    router as agent_manager_router,
)
from agent_manager.api.router import (
    runtime_router as agent_runtime_router,
)
from agent_manager.api.scanner_router import admin_router as scanner_admin_router
from agent_manager.api.scanner_router import router as scanner_router
from agent_manager.api.scanner_router import runtime_router as access_runtime_router
from agent_manager.core.vetting import warmup_scanner

logger = logging.getLogger(__name__)


def warmup_skill_scanner() -> None:
    manager = get_agent_manager()
    warmup_scanner(manager.policy.scanner_policy)


def cleanup_runtime_traces_once() -> bool:
    db = SessionLocal()
    try:
        return cleanup_expired(db)["more"]
    finally:
        db.close()


async def runtime_trace_retention_loop() -> None:
    await retention_loop(cleanup_runtime_traces_once, "runtime trace")


@asynccontextmanager
async def application_lifespan(_: FastAPI):
    warmup_skill_scanner()
    retention_task = asyncio.create_task(runtime_trace_retention_loop())
    pipeline_retention_task = asyncio.create_task(retention_loop(cleanup_pipeline_traces_once, "pipeline trace"))
    from .request_leases import cleanup_expired_leases
    lease_retention_task = asyncio.create_task(retention_loop(cleanup_expired_leases, "request leases"))
    from .aidr_retention import retention_loop as aidr_retention_loop
    aidr_retention_task = asyncio.create_task(aidr_retention_loop())
    from .aidr_skill_usage import audit_loop
    skill_audit_task = asyncio.create_task(audit_loop())
    from .aidr_overview import projection_loop
    overview_task = asyncio.create_task(projection_loop())
    from .services.asset_sync import lifecycle_loop
    asset_task = asyncio.create_task(lifecycle_loop())
    from .services.openapi_skills import report_loop
    skill_report_task = asyncio.create_task(report_loop())
    from .services.external_delivery import delivery_loop
    delivery_task = asyncio.create_task(delivery_loop())
    try:
        yield
    finally:
        retention_task.cancel()
        pipeline_retention_task.cancel()
        lease_retention_task.cancel()
        aidr_retention_task.cancel()
        skill_audit_task.cancel()
        overview_task.cancel()
        asset_task.cancel()
        skill_report_task.cancel()
        delivery_task.cancel()
        with suppress(asyncio.CancelledError):
            await delivery_task
        with suppress(asyncio.CancelledError):
            await skill_report_task
        with suppress(asyncio.CancelledError):
            await asset_task
        with suppress(asyncio.CancelledError):
            await retention_task
        with suppress(asyncio.CancelledError):
            await pipeline_retention_task
        with suppress(asyncio.CancelledError):
            await lease_retention_task
        with suppress(asyncio.CancelledError):
            await aidr_retention_task
        with suppress(asyncio.CancelledError):
            await skill_audit_task
        with suppress(asyncio.CancelledError):
            await overview_task


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=application_lifespan,
    dependencies=[Depends(enforce_license_request)],
)
app.add_exception_handler(LicenseError, license_error_handler)
app.include_router(license_routes.router, prefix=settings.API_PREFIX)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(StarletteHTTPException, routing_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.add_middleware(WorkerCompletionBodyLimitMiddleware)
from .external_access import ExternalAccessMiddleware
from .routers import external_access
app.add_middleware(ExternalAccessMiddleware)
app.include_router(external_access.router, prefix=f"{settings.API_PREFIX}/v1")
from .routers import external_deliveries
app.include_router(external_deliveries.router, prefix=f"{settings.API_PREFIX}/v1")
from .routers import external_callbacks
app.include_router(external_callbacks.router, prefix=f"{settings.API_PREFIX}/v1")
from .routers import external_gateways
app.include_router(external_gateways.router, prefix=f"{settings.API_PREFIX}/v1")
from .routers import openapi_profiles
app.include_router(openapi_profiles.router, prefix=f"{settings.API_PREFIX}/v1")
app.include_router(external_access.openapi_router)
from .routers import openapi_skills
app.include_router(openapi_skills.router)
from .routers import openapi_agents
app.include_router(openapi_agents.router)
from .iam_middleware import management_audit_middleware
app.middleware("http")(management_audit_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(iam.router, prefix=settings.API_PREFIX)
app.include_router(config.router, prefix=settings.API_PREFIX)
app.include_router(system.router, prefix=settings.API_PREFIX)
app.include_router(tasks.router, prefix=settings.API_PREFIX)
app.include_router(agents.router, prefix=settings.API_PREFIX)
app.include_router(access_tokens.router, prefix=f"{settings.API_PREFIX}/v1")
app.include_router(security_audit.router, prefix=settings.API_PREFIX)
app.include_router(audit_trail.router, prefix=settings.API_PREFIX)
app.include_router(
    agent_security.router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_security_reader)]
)
app.include_router(security_scans.router, prefix=settings.API_PREFIX)
app.include_router(asset_lifecycle.router, prefix=settings.API_PREFIX)
app.include_router(scan_schedules.router, prefix=settings.API_PREFIX)
app.include_router(runtime_governance.router, prefix=settings.API_PREFIX)
app.include_router(runtime_traces.router, prefix=settings.API_PREFIX)
app.include_router(dify_runtime.router, prefix=settings.API_PREFIX)
app.include_router(mcp_gateway.admin_router, prefix=f"{settings.API_PREFIX}/v1", dependencies=[Depends(get_current_admin_user)])
app.include_router(mcp_gateway.runtime_router)
app.include_router(clients.router, prefix=settings.API_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_PREFIX)
app.include_router(aidr.router, prefix=settings.API_PREFIX)
app.include_router(aidr.global_tool_router, prefix=settings.API_PREFIX)
app.include_router(aidr_enforcement.router, prefix=settings.API_PREFIX)
app.include_router(external_ai_gateways.router, prefix=settings.API_PREFIX)
app.include_router(external_ai_gateways.runtime_router, prefix=settings.API_PREFIX)
app.include_router(llm_gateway.runtime_router)
app.include_router(llm_gateway.admin_router, prefix=settings.API_PREFIX)
app.include_router(access_runtime_router)
app.include_router(agent_runtime_router, prefix="/api/v1")
app.include_router(agent_manager_router, prefix="/api/v1", dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_admin_router, dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_router)


_AUDITED_ADMIN_PREFIXES = (
    "/api/v1/skills/submit-upload-selected",
    "/api/config/",
    "/api/agents",
    "/api/v1/access/tokens",
    "/api/v1/mcp/",
    "/api/v1/users",
    "/api/v1/groups",
    "/api/v1/model-providers",
    "/api/v1/models",
    "/api/v1/external-ai-gateways",
    "/api/v1/llm-api-keys",
    "/api/v1/privacy-policies",
    "/api/v1/runtime-governance/",
    "/api/v1/agent-security/",
    "/api/v1/runtime-traces/",
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
    from .external_access_models import upgrade_external_access_schema
    upgrade_external_access_schema(engine)
    Base.metadata.create_all(bind=engine)
    from .aidr_migrations import upgrade_aidr_schema
    upgrade_aidr_schema(engine)
    from .aidr_tool_policy_scope import initialize_global_policy
    with SessionLocal() as policy_db:
        initialize_global_policy(policy_db)
        policy_db.commit()
    from .iam import initialize as initialize_iam, migrate as migrate_iam
    migrate_iam(engine)
    with SessionLocal() as iam_db:
        initialize_iam(iam_db)
    from .asset_lifecycle_migrations import upgrade_asset_lifecycle_schema

    upgrade_asset_lifecycle_schema(engine)
    for index in models.GatewaySessionRequest.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
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
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_managed_agents_created_by ON managed_agents (created_by)"
        )
        if "default_model_source" not in agent_columns:
            conn.exec_driver_sql(
                "ALTER TABLE managed_agents ADD COLUMN default_model_source VARCHAR(32) NOT NULL DEFAULT 'internal'"
            )
        if "external_gateway_id" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE managed_agents ADD COLUMN external_gateway_id INTEGER")
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_managed_agents_external_gateway_id "
                "ON managed_agents (external_gateway_id)"
            )
        if "origin_type" not in agent_columns:
            conn.exec_driver_sql(
                "ALTER TABLE managed_agents ADD COLUMN origin_type VARCHAR(32) NOT NULL DEFAULT 'platform'"
            )
            conn.exec_driver_sql(
                "UPDATE managed_agents SET origin_type = 'client_discovery' "
                "WHERE agent_id LIKE 'client-%' AND agent_id IN ("
                "SELECT managed_agent_id FROM client_agents WHERE managed_agent_id IS NOT NULL)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_managed_agents_origin_type ON managed_agents (origin_type)"
            )
        external_binding_columns = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(external_gateway_agent_bindings)"
            ).fetchall()
        }
        if external_binding_columns and "available_models_json" not in external_binding_columns:
            conn.exec_driver_sql(
                "ALTER TABLE external_gateway_agent_bindings "
                "ADD COLUMN available_models_json TEXT NOT NULL DEFAULT '[]'"
            )
        if external_binding_columns and "models_refreshed_at" not in external_binding_columns:
            conn.exec_driver_sql(
                "ALTER TABLE external_gateway_agent_bindings "
                "ADD COLUMN models_refreshed_at DATETIME"
            )
        governance_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(client_governance_policies)").fetchall()}
        if "prompt_guard_json" not in governance_columns:
            conn.exec_driver_sql("ALTER TABLE client_governance_policies ADD COLUMN prompt_guard_json TEXT NOT NULL DEFAULT 'null'")
        if "compression_json" not in governance_columns:
            conn.exec_driver_sql("ALTER TABLE client_governance_policies ADD COLUMN compression_json TEXT NOT NULL DEFAULT 'null'")
        if "model_routing_json" not in governance_columns:
            conn.exec_driver_sql("ALTER TABLE client_governance_policies ADD COLUMN model_routing_json TEXT NOT NULL DEFAULT 'null'")
        if "runtime_governance_json" not in governance_columns:
            conn.exec_driver_sql("ALTER TABLE client_governance_policies ADD COLUMN runtime_governance_json TEXT NOT NULL DEFAULT 'null'")
        access_token_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(access_tokens)").fetchall()}
        if "bound_client_id" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN bound_client_id VARCHAR(128)")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_access_tokens_bound_client_id ON access_tokens (bound_client_id)"
        )
        if "allow_agent_credential_issuance" not in access_token_columns:
            conn.exec_driver_sql(
                "ALTER TABLE access_tokens ADD COLUMN allow_agent_credential_issuance BOOLEAN NOT NULL DEFAULT 0"
            )
        if "issued_by_client_token_id" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN issued_by_client_token_id INTEGER")
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_access_tokens_issued_by_client_token_id "
                "ON access_tokens (issued_by_client_token_id)"
            )
        if "allowed_mcp_gateways_json" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN allowed_mcp_gateways_json TEXT NOT NULL DEFAULT '[]'")
        if "prompt_guard_mode" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN prompt_guard_mode VARCHAR(32) NOT NULL DEFAULT 'log'")
        if "prompt_guard_llm_review" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN prompt_guard_llm_review BOOLEAN NOT NULL DEFAULT 0")
        runtime_task_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(runtime_tasks)").fetchall()}
        if runtime_task_columns and "trace_id" not in runtime_task_columns:
            conn.exec_driver_sql("ALTER TABLE runtime_tasks ADD COLUMN trace_id VARCHAR(64)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_runtime_tasks_trace_id ON runtime_tasks (trace_id)")
        runtime_trace_session_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(runtime_trace_sessions)").fetchall()
        }
        if runtime_trace_session_columns and "risk_mapping_version" not in runtime_trace_session_columns:
            conn.exec_driver_sql("ALTER TABLE runtime_trace_sessions ADD COLUMN risk_mapping_version VARCHAR(64)")
        runtime_trace_event_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(runtime_trace_events)").fetchall()
        }
        if runtime_trace_event_columns and "risk_mapping_json" not in runtime_trace_event_columns:
            conn.exec_driver_sql("ALTER TABLE runtime_trace_events ADD COLUMN risk_mapping_json TEXT NOT NULL DEFAULT '{}'")
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS backend_schema_migrations (name VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL)"
        )
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p1_v1', CURRENT_TIMESTAMP)"
        )
        security_task_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_scan_tasks)").fetchall()
        }
        security_target_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_targets)").fetchall()
        }
        security_target_additive_columns = {
            "environment": "VARCHAR(32) NOT NULL DEFAULT 'test'",
            "allowed_capabilities_json": "TEXT NOT NULL DEFAULT '[\"conversation\",\"multi_turn\",\"tool_read\",\"tool_write\",\"network_egress\",\"file_read\",\"file_write\",\"code_execution\",\"persistent_memory\"]'",
        }
        for column_name, column_type in security_target_additive_columns.items():
            if security_target_columns and column_name not in security_target_columns:
                conn.exec_driver_sql(f"ALTER TABLE security_targets ADD COLUMN {column_name} {column_type}")
        if security_target_columns:
            migrate_security_target_classification(conn)
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_targets_environment ON security_targets (environment)"
            )
        security_policy_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_scan_policies)").fetchall()
        }
        security_policy_additive_columns = {
            "environment": "VARCHAR(32) NOT NULL DEFAULT 'test'",
            "allowed_capabilities_json": "TEXT NOT NULL DEFAULT '[\"conversation\",\"multi_turn\",\"tool_read\",\"tool_write\",\"network_egress\",\"file_read\",\"file_write\",\"code_execution\",\"persistent_memory\"]'",
            "production_target_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "maintenance_window_start": "DATETIME",
            "maintenance_window_end": "DATETIME",
            "dedicated_identity_ref": "VARCHAR(128)",
        }
        for column_name, column_type in security_policy_additive_columns.items():
            if security_policy_columns and column_name not in security_policy_columns:
                conn.exec_driver_sql(f"ALTER TABLE security_scan_policies ADD COLUMN {column_name} {column_type}")
        if security_policy_columns:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_scan_policies_environment "
                "ON security_scan_policies (environment)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_scan_policies_maintenance_window_end "
                "ON security_scan_policies (maintenance_window_end)"
            )
        migrate_dify_asset_inventory(conn)
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p6_environment_capabilities_v1', CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p6_production_approval_v1', CURRENT_TIMESTAMP)"
        )
        security_task_additive_columns = {
            "approval_id": "VARCHAR(64)",
            "scan_options_encrypted": "TEXT",
            "continued_from_task_id": "VARCHAR(64)",
            "session_state_encrypted": "TEXT",
            "engine_name": "VARCHAR(128)",
            "engine_version": "VARCHAR(128)",
            "report_template_version": "VARCHAR(64)",
            "decision_criteria_version": "VARCHAR(64)",
            "report_contract_json": "TEXT NOT NULL DEFAULT '{}'",
            "kill_switch_activated": "BOOLEAN NOT NULL DEFAULT 0",
            "kill_switch_activated_at": "DATETIME",
            "kill_switch_activated_by": "VARCHAR(128)",
            "kill_switch_reason": "TEXT",
        }
        for column_name, column_type in security_task_additive_columns.items():
            if security_task_columns and column_name not in security_task_columns:
                conn.exec_driver_sql(f"ALTER TABLE security_scan_tasks ADD COLUMN {column_name} {column_type}")
        if security_task_columns:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_scan_tasks_continued_from_task_id "
                "ON security_scan_tasks (continued_from_task_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_scan_tasks_approval_id ON security_scan_tasks (approval_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_scan_tasks_kill_switch_activated "
                "ON security_scan_tasks (kill_switch_activated)"
            )
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p6_kill_switch_v1', CURRENT_TIMESTAMP)"
        )
        security_finding_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_findings)").fetchall()
        }
        security_finding_additive_columns = {
            "fingerprint": "VARCHAR(64) NOT NULL DEFAULT ''",
            "disposition_comment": "TEXT",
            "disposition_by": "VARCHAR(128)",
            "disposition_at": "DATETIME",
            "trace_id": "VARCHAR(64)",
            "event_id": "VARCHAR(64)",
            "risk_codes_json": "TEXT NOT NULL DEFAULT '[]'",
            "risk_mapping_json": "TEXT NOT NULL DEFAULT '{}'",
            "decision_criteria_version": "VARCHAR(64)",
        }
        for column_name, column_type in security_finding_additive_columns.items():
            if security_finding_columns and column_name not in security_finding_columns:
                conn.exec_driver_sql(f"ALTER TABLE security_findings ADD COLUMN {column_name} {column_type}")
        if security_finding_columns:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_findings_trace_id ON security_findings (trace_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_security_findings_event_id ON security_findings (event_id)"
            )
        security_artifact_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_scan_artifacts)").fetchall()
        }
        if security_artifact_columns and "content_encrypted" not in security_artifact_columns:
            conn.exec_driver_sql("ALTER TABLE security_scan_artifacts ADD COLUMN content_encrypted TEXT")
        security_worker_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(security_scan_workers)").fetchall()
        }
        security_worker_additive_columns = {
            "public_key_algorithm": "VARCHAR(64)",
            "public_key": "TEXT",
            "public_key_fingerprint": "VARCHAR(64)",
            "public_key_registered_at": "DATETIME",
        }
        for column_name, column_type in security_worker_additive_columns.items():
            if security_worker_columns and column_name not in security_worker_columns:
                conn.exec_driver_sql(f"ALTER TABLE security_scan_workers ADD COLUMN {column_name} {column_type}")
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p2_v1', CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p6_asi_mapping_v1', CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p6_report_contract_v1', CURRENT_TIMESTAMP)"
        )
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('runtime_trace_p4_v1', CURRENT_TIMESTAMP)"
        )
        llm_key_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(llm_api_keys)").fetchall()}
        if "prompt_guard_mode" not in llm_key_columns:
            conn.exec_driver_sql("ALTER TABLE llm_api_keys ADD COLUMN prompt_guard_mode VARCHAR(32) NOT NULL DEFAULT 'log'")
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
        mcp_audit_additive_columns = {
            "approval_request_id": "VARCHAR(64)",
        }
        for column_name, column_type in mcp_audit_additive_columns.items():
            if mcp_audit_columns and column_name not in mcp_audit_columns:
                conn.exec_driver_sql(f"ALTER TABLE mcp_call_audits ADD COLUMN {column_name} {column_type}")
        mcp_server_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_servers)").fetchall()}
        if mcp_server_columns and "max_response_kb" not in mcp_server_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_servers ADD COLUMN max_response_kb INTEGER NOT NULL DEFAULT 1024")
        mcp_tool_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_tools)").fetchall()}
        if mcp_tool_columns and "access_mode" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN access_mode VARCHAR(32) NOT NULL DEFAULT 'unknown'")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_mcp_tools_access_mode ON mcp_tools (access_mode)")
        if mcp_tool_columns and "risk_level" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN risk_level VARCHAR(16) NOT NULL DEFAULT 'low'")
        if mcp_tool_columns and "rate_limit_per_minute" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN rate_limit_per_minute INTEGER NOT NULL DEFAULT 60")
        if mcp_tool_columns and "max_concurrent" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN max_concurrent INTEGER NOT NULL DEFAULT 5")
        if mcp_tool_columns and "requires_approval" not in mcp_tool_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_tools ADD COLUMN requires_approval BOOLEAN NOT NULL DEFAULT 0")
        mcp_gateway_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_gateways)").fetchall()}
        mcp_gateway_additive_columns = {
            "environment": "VARCHAR(32) NOT NULL DEFAULT 'test'",
            "execution_mode": "VARCHAR(32) NOT NULL DEFAULT 'active_safe'",
            "production_tool_denylist_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column_name, column_type in mcp_gateway_additive_columns.items():
            if mcp_gateway_columns and column_name not in mcp_gateway_columns:
                conn.exec_driver_sql(f"ALTER TABLE mcp_gateways ADD COLUMN {column_name} {column_type}")
        if mcp_gateway_columns:
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_mcp_gateways_environment ON mcp_gateways (environment)")
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) "
            "VALUES ('agent_security_p6_tool_policy_v1', CURRENT_TIMESTAMP)"
        )
        mcp_approval_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_tool_approvals)").fetchall()}
        mcp_approval_request_columns = {
            "request_id": "VARCHAR(64)",
            "server_slug": "VARCHAR(128)",
            "tool_id": "INTEGER",
            "schema_hash": "VARCHAR(64)",
            "arguments_encrypted": "TEXT",
            "client_ip": "VARCHAR(128)",
            "reviewed_by": "VARCHAR(128)",
            "reviewed_at": "DATETIME",
            "review_comment": "TEXT",
            "use_count": "INTEGER NOT NULL DEFAULT 0",
            "first_used_at": "DATETIME",
            "last_used_at": "DATETIME",
        }
        for column_name, column_type in mcp_approval_request_columns.items():
            if mcp_approval_columns and column_name not in mcp_approval_columns:
                conn.exec_driver_sql(f"ALTER TABLE mcp_tool_approvals ADD COLUMN {column_name} {column_type}")
        if mcp_approval_columns:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_mcp_tool_approvals_request_id "
                "ON mcp_tool_approvals (request_id) WHERE request_id IS NOT NULL"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_mcp_tool_approvals_server_slug ON mcp_tool_approvals (server_slug)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_mcp_tool_approvals_tool_id ON mcp_tool_approvals (tool_id)"
            )
        if mcp_audit_columns:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_mcp_call_audits_approval_request_id "
                "ON mcp_call_audits (approval_request_id)"
            )
        managed_client_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(managed_clients)").fetchall()}
        if managed_client_columns and "policy_mode" not in managed_client_columns:
            conn.exec_driver_sql("ALTER TABLE managed_clients ADD COLUMN policy_mode VARCHAR(32) NOT NULL DEFAULT 'audit'")
        if managed_client_columns and "governance_mode" not in managed_client_columns:
            conn.exec_driver_sql("ALTER TABLE managed_clients ADD COLUMN governance_mode VARCHAR(32) NOT NULL DEFAULT 'registry'")
        client_agent_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(client_agents)").fetchall()}
        client_agent_additions = {
            "local_agent_id": "VARCHAR(128)",
            "desired_model": "VARCHAR(128)",
            "applied_model": "VARCHAR(128)",
            "model_config_status": "VARCHAR(32) NOT NULL DEFAULT 'not_configured'",
            "model_config_error": "TEXT",
            "model_config_updated_at": "DATETIME",
        }
        for column, definition in client_agent_additions.items():
            if client_agent_columns and column not in client_agent_columns:
                conn.exec_driver_sql(f"ALTER TABLE client_agents ADD COLUMN {column} {definition}")
        client_skill_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(client_skill_installs)").fetchall()}
        client_task_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(client_tasks)").fetchall()}
        if client_task_columns:
            if "request_key" not in client_task_columns:
                conn.exec_driver_sql("ALTER TABLE client_tasks ADD COLUMN request_key VARCHAR(64)")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_client_tasks_request_key ON client_tasks(request_key)")
        client_event_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(client_events)").fetchall()}
        for column, definition in {
            "aggregate_key": "VARCHAR(64)",
            "observation_count": "INTEGER NOT NULL DEFAULT 1",
            "last_seen_at": "DATETIME",
        }.items():
            if client_event_columns and column not in client_event_columns:
                conn.exec_driver_sql(f"ALTER TABLE client_events ADD COLUMN {column} {definition}")
        if client_event_columns:
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_client_events_aggregate_key ON client_events(aggregate_key)")
        if "governance_json" not in client_skill_columns:
            conn.exec_driver_sql("ALTER TABLE client_skill_installs ADD COLUMN governance_json TEXT")
        if client_skill_columns and "version_id" not in client_skill_columns:
            conn.exec_driver_sql("ALTER TABLE client_skill_installs ADD COLUMN version_id VARCHAR(128)")
        if client_skill_columns and "version_no" not in client_skill_columns:
            conn.exec_driver_sql("ALTER TABLE client_skill_installs ADD COLUMN version_no INTEGER")
        if client_skill_columns and "source_version" not in client_skill_columns:
            conn.exec_driver_sql("ALTER TABLE client_skill_installs ADD COLUMN source_version VARCHAR(128)")

    from .agent_mcp import migrate_agent_mcp_scope
    migrate_agent_mcp_scope(engine)

    # Headroom 压缩字段 migration
    from backend.migrate_compression import migrate as migrate_compression
    migrate_compression()


validate_security_settings(settings)
initialize_signing_identity(allow_create=not settings.ENFORCE_SECURE_STARTUP)
ensure_audit_signing_key()
ensure_sqlite_schema()
with SessionLocal() as identity_db:
    if clients.backfill_client_inventory_identities(identity_db):
        identity_db.commit()
bootstrap_builtin_security_worker_once(settings, SessionLocal)
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
