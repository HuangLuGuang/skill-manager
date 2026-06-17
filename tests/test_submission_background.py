"""Regression tests for non-blocking skill submission processing."""

from __future__ import annotations

import io
import time
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy


def _skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "SKILL.md",
            "---\nname: slow-scan-skill\ndescription: Background scan test\n---\n",
        )
    return buffer.getvalue()


def test_submit_zip_returns_before_slow_scan_finishes(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")

    def slow_processing(*_args, **_kwargs):
        time.sleep(0.75)

    monkeypatch.setattr(manager, "process_pending_submission", slow_processing)
    monkeypatch.setattr(api_router, "_manager", manager)

    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager

    with TestClient(app) as client:
        started_at = time.monotonic()
        response = client.post(
            "/skills/submit-zip",
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )
        elapsed = time.monotonic() - started_at

        assert response.status_code == 200
        assert response.json()["status"] == "PENDING"
        assert elapsed < 0.4
