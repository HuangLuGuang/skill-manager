"""Regression tests for non-blocking skill submission processing."""

from __future__ import annotations

import io
import stat
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.api.router import _safe_extract_zip
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


def test_safe_extract_zip_preserves_utf8_names_without_flag(tmp_path):
    zip_path = tmp_path / "skill.zip"
    raw_name = "references/常用查询模板.md"
    with zip_path.open("wb") as file:
        with zipfile.ZipFile(file, "w") as archive:
            archive.writestr(raw_name, "select 1")
    data = bytearray(zip_path.read_bytes())
    data[6] &= ~0x08
    data[7] &= ~0x08
    central = data.index(b"PK\x01\x02")
    data[central + 8] &= ~0x08
    data[central + 9] &= ~0x08
    zip_path.write_bytes(data)

    _safe_extract_zip(zip_path, tmp_path / "out")

    assert (tmp_path / "out" / Path(raw_name)).read_text(encoding="utf-8") == "select 1"


def test_safe_extract_zip_rejects_symlinks(tmp_path):
    zip_path = tmp_path / "skill.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        info = zipfile.ZipInfo("current")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "releases/v1")

    response = None
    try:
        _safe_extract_zip(zip_path, tmp_path / "out")
    except Exception as exc:
        response = exc

    assert response is not None
    assert "Symlinks are not allowed" in response.detail
