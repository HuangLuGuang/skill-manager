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
from .routers import auth, config, system, tasks
from .sqlite_db import Base, SessionLocal, engine
from .task_runtime import init_default_tasks


load_dotenv(override=True)
base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from skill_manager.api.router import router as skill_manager_router
from skill_manager.api.scanner_router import admin_router as scanner_admin_router
from skill_manager.api.scanner_router import router as scanner_router

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
app.include_router(skill_manager_router, dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_admin_router, dependencies=[Depends(get_current_admin_user)])
app.include_router(scanner_router)

Base.metadata.create_all(bind=engine)

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
