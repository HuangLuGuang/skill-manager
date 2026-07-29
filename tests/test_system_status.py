from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_manager.api.router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import ReviewRequest, RiskLevel
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.sandbox import SandboxConfig, SandboxConnectionTest


def test_system_status_uses_current_registry_counts(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    manager.registry.enqueue_review(ReviewRequest(
        skill_id="pending",
        skill_name="pending",
        risk_level=RiskLevel.SUSPICIOUS,
        findings_summary={"medium": 1},
        submitted_at=datetime.now(timezone.utc),
    ))
    monkeypatch.setattr(api_router.SandboxConfig, "load", classmethod(lambda cls: SandboxConfig(enabled=False)))
    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager

    payload = TestClient(app).get("/api/v1/system/status").json()

    assert payload["registry_entries"] == 0
    assert payload["review_queue"] == 1
    assert payload["skillspector_version"] is None


def test_system_status_reports_sandbox_closed_when_disabled(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")

    monkeypatch.setattr(
        api_router.SandboxConfig,
        "load",
        classmethod(lambda cls: SandboxConfig(enabled=False, runtime="docker")),
    )
    monkeypatch.setattr(
        api_router,
        "test_sandbox_connection",
        lambda _config, timeout_seconds=2: SandboxConnectionTest(
            available=True,
            runtime="docker",
            target="agent-manager-sandbox-runtime:latest",
            message="Docker Sandbox 镜像可用",
            duration_ms=1,
        ),
    )

    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sandbox_enabled"] is False
    assert payload["sandbox_available"] is False


def test_system_status_reports_sandbox_unavailable_when_probe_fails(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")

    monkeypatch.setattr(
        api_router.SandboxConfig,
        "load",
        classmethod(lambda cls: SandboxConfig(enabled=True, runtime="remote", remote_url="http://sandbox:8194")),
    )
    monkeypatch.setattr(
        api_router,
        "test_sandbox_connection",
        lambda _config, timeout_seconds=2: SandboxConnectionTest(
            available=False,
            runtime="remote",
            target="http://sandbox:8194/run-code",
            message="远程 Sandbox 连接失败：Name or service not known",
            duration_ms=3,
        ),
    )

    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sandbox_enabled"] is True
    assert payload["sandbox_available"] is False
    assert payload["sandbox_target"] == "http://sandbox:8194/run-code"
    assert payload["sandbox_status_message"].startswith("远程 Sandbox 连接失败")
