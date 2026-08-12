from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api.lifecycle import lifespan_with_startup


def test_lifespan_runs_startup_callback_before_requests():
    startup_calls: list[str] = []
    app = FastAPI(lifespan=lifespan_with_startup(lambda: startup_calls.append("started")))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    assert startup_calls == []
    with TestClient(app) as client:
        assert startup_calls == ["started"]
        assert client.get("/health").json() == {"status": "ok"}

    assert startup_calls == ["started"]
