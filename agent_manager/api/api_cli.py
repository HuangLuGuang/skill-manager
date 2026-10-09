"""Entry point for the API server."""

import click
import uvicorn


@click.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8080, show_default=True)
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on code changes")
def main(host: str, port: int, reload: bool):
    """Start the agent manager API server."""
    from fastapi import FastAPI

    from backend.api_errors import ApiError, api_error_handler

    from agent_manager.api.lifecycle import lifespan_with_startup
    from agent_manager.core.vetting import warmup_scanner

    from .router import get_manager, router
    from .scanner_router import admin_router as scanner_admin_router
    from .scanner_router import router as scanner_router
    from .scanner_router import runtime_router as access_runtime_router

    def warmup_skill_scanner() -> None:
        warmup_scanner(get_manager().policy.scanner_policy)

    app = FastAPI(
        title="Agent Manager API",
        description="Enterprise skill lifecycle manager for AI agents",
        version="0.1.0",
        lifespan=lifespan_with_startup(warmup_skill_scanner),
    )
    # 独立入口复用管理后台的错误协议，保留稳定编码和双语提示。
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(router)
    app.include_router(scanner_admin_router)
    app.include_router(access_runtime_router)
    app.include_router(scanner_router)

    uvicorn.run(app, host=host, port=port, reload=reload)
