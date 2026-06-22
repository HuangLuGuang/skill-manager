from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_manager.api.router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.sandbox import SandboxConfig


def test_system_status_reports_sandbox_closed_when_disabled(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")

    class AvailableRunner:
        config = SandboxConfig(enabled=False, runtime="docker")

        def is_available(self):
            return True

    monkeypatch.setattr(
        api_router.SandboxConfig,
        "load",
        classmethod(lambda cls: SandboxConfig(enabled=False, runtime="docker")),
    )
    monkeypatch.setattr(api_router, "get_sandbox_runner", lambda _config: AvailableRunner())

    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sandbox_enabled"] is False
    assert payload["sandbox_available"] is False
