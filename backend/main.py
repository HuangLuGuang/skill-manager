import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models
from .auth import get_current_admin_user, get_password_hash
from .config import settings
from .routers import access_tokens, agents, auth, config, llm_gateway, system, tasks
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
app.include_router(llm_gateway.runtime_router)
app.include_router(llm_gateway.admin_router, prefix=settings.API_PREFIX)
app.include_router(access_runtime_router)
app.include_router(agent_runtime_router, prefix="/api/v1")
app.include_router(agent_manager_router, prefix="/api/v1", dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_admin_router, dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_router)

def ensure_sqlite_schema() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(privacy_policies)").fetchall()}
        if "entity_rules_json" not in columns:
            conn.exec_driver_sql("ALTER TABLE privacy_policies ADD COLUMN entity_rules_json TEXT NOT NULL DEFAULT '{}'")
        agent_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(managed_agents)").fetchall()}
        if "runtime_token_id" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE managed_agents ADD COLUMN runtime_token_id INTEGER")
        if "created_by" not in agent_columns:
            conn.exec_driver_sql("ALTER TABLE managed_agents ADD COLUMN created_by VARCHAR(128)")
        access_token_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(access_tokens)").fetchall()}
        if "prompt_guard_mode" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN prompt_guard_mode VARCHAR(32) NOT NULL DEFAULT 'off'")
        if "prompt_guard_llm_review" not in access_token_columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN prompt_guard_llm_review BOOLEAN NOT NULL DEFAULT 0")
        llm_key_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(llm_api_keys)").fetchall()}
        if "prompt_guard_mode" not in llm_key_columns:
            conn.exec_driver_sql("ALTER TABLE llm_api_keys ADD COLUMN prompt_guard_mode VARCHAR(32) NOT NULL DEFAULT 'off'")
        if "prompt_guard_llm_review" not in llm_key_columns:
            conn.exec_driver_sql("ALTER TABLE llm_api_keys ADD COLUMN prompt_guard_llm_review BOOLEAN NOT NULL DEFAULT 0")
        audit_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(llm_request_audit)").fetchall()}
        if "prompt_guard_result_json" not in audit_columns:
            conn.exec_driver_sql("ALTER TABLE llm_request_audit ADD COLUMN prompt_guard_result_json TEXT NOT NULL DEFAULT '{}'")

    # Headroom 压缩字段 migration
    from backend.migrate_compression import migrate as migrate_compression
    migrate_compression()


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
        admin = db.query(models.User).filter(models.User.username == "admin").first()
        if not admin:
            db.add(
                models.User(
                    username="admin",
                    email="admin@example.com",
                    hashed_password=get_password_hash("Admin@123"),
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
