"""Entry point for the API server."""

import click
import uvicorn


@click.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8080, show_default=True)
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on code changes")
def main(host: str, port: int, reload: bool):
    """Start the skill manager API server."""
    from fastapi import FastAPI
    from .router import router

    app = FastAPI(
        title="Skill Manager API",
        description="Enterprise skill lifecycle manager for AI agents",
        version="0.1.0",
    )
    app.include_router(router)

    uvicorn.run(app, host=host, port=port, reload=reload)
