"""Regression tests for non-blocking skill submission processing."""

from __future__ import annotations

import io
import json
import stat
import threading
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.api.router import _safe_extract_zip
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RiskLevel, SkillStatus
from agent_manager.core.policy import CompanyPolicy


def _skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "SKILL.md",
            "---\nname: slow-scan-skill\ndescription: Background scan test\n---\n",
        )
    return buffer.getvalue()


def _mixed_skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("valid/SKILL.md", "---\nname: valid-skill\n---\n")
        archive.writestr("invalid/SKILL.md", "# Skill without frontmatter\n")
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


def test_prepare_upload_zip_keeps_valid_candidates_and_reports_invalid_ones(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    monkeypatch.setattr(api_router, "_manager", manager)

    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager

    response = TestClient(app).post(
        "/skills/prepare-upload-zip",
        files={"file": ("skill.zip", _mixed_skill_zip(), "application/zip")},
    )

    assert response.status_code == 200
    items = {item["relative_path"]: item for item in response.json()["items"]}
    assert items["valid"]["name"] == "valid-skill"
    assert items["valid"]["error"] == ""
    assert items["invalid"]["error"] == "SKILL.md 缺少 name 字段（格式：name: your-skill-name）"


def test_prepare_zip_requires_confirmation_and_records_skipped_links(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("valid/SKILL.md", "---\nname: valid-skill\n---\n")
        for path in ("valid/资源.svg", "invalid/SKILL.md"):
            info = zipfile.ZipInfo(path)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/outside/target")
    client = TestClient(app)
    files = {"file": ("skill.zip", buffer.getvalue(), "application/zip")}
    preview = client.post("/skills/prepare-upload-zip", files=files).json()
    assert preview["requires_symlink_confirmation"] is True
    assert preview["session_id"]
    assert preview["items"] == []
    session_id = preview["session_id"]
    assert client.post("/skills/submit-upload-selected", json={
        "session_id": session_id, "paths": [str(Path(preview["root_path"]) / "valid")],
    }).status_code == 409
    def unexpected_extraction(*args, **kwargs):
        raise AssertionError("Confirmation must reuse extracted files")
    monkeypatch.setattr(api_router, "_safe_extract_zip", unexpected_extraction)
    response = client.post("/skills/confirm-upload-zip", json={"session_id": session_id, "confirmed": True})
    assert response.status_code == 200
    result = response.json()
    assert result["requires_symlink_confirmation"] is False
    assert result["skipped_symlinks"] == ["valid/资源.svg", "invalid/SKILL.md"]
    assert [item["name"] for item in result["items"]] == ["valid-skill"]
    assert not (Path(result["root_path"]) / "valid/资源.svg").exists()
    assert (manager.registry.data_dir / "upload_import_metadata" / f"{result['session_id']}.json").exists()
    repeated = client.post("/skills/confirm-upload-zip", json={"session_id": session_id, "confirmed": True})
    assert repeated.json() == result


def test_cancel_upload_confirmation_removes_session(tmp_path):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)
    preview = client.post("/skills/prepare-upload-zip", files={"file": ("skill.zip", _skill_zip(), "application/zip")}).json()
    session_id = preview["session_id"]
    response = client.post("/skills/confirm-upload-zip", json={"session_id": session_id, "confirmed": False})
    assert response.status_code == 200
    assert not Path(preview["root_path"]).exists()
    assert not (manager.registry.data_dir / "upload_import_metadata" / f"{session_id}.json").exists()
    assert client.post("/skills/confirm-upload-zip", json={"session_id": "../outside", "confirmed": False}).status_code == 422


def test_zip_stream_reports_actual_work_and_final_candidates(tmp_path):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)
    response = client.post("/skills/prepare-upload-zip?stream=true", files={"file": ("skill.zip", _mixed_skill_zip(), "application/zip")})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.headers["x-accel-buffering"] == "no"
    assert events[-1]["type"] == "result"
    assert events[-1]["data"]["count"] == 2
    for stage in ("extracting", "identifying"):
        progress = [event for event in events if event.get("stage") == stage and event["total"] > 0]
        assert progress[-1]["completed"] == progress[-1]["total"] == 2
    failed = client.post("/skills/prepare-upload-zip?stream=true", files={"file": ("bad.zip", b"invalid", "application/zip")})
    assert json.loads(failed.text.splitlines()[-1]) == {"type": "error", "error_code": "upload.parse_failed"}


def test_selected_upload_creates_snapshot_directly_from_session(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    monkeypatch.setattr(manager, "process_pending_submission", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)
    prepared = client.post("/skills/prepare-upload-zip", files={"file": ("skill.zip", _skill_zip(), "application/zip")}).json()
    skill_path = Path(prepared["items"][0]["path"])
    release = threading.Event()
    entered = threading.Event()
    original_prepare = manager.prepare_submission
    def slow_prepare(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_prepare(*args, **kwargs)
    monkeypatch.setattr(manager, "prepare_submission", slow_prepare)
    body = {"session_id": prepared["session_id"], "paths": [str(skill_path)]}
    try:
        started = time.monotonic()
        response = client.post("/skills/submit-upload-selected", json=body)
        assert response.status_code == 202
        assert time.monotonic() - started < 0.5
        assert entered.wait(2)
        assert client.post("/skills/submit-upload-selected", json=body).json()["job_id"] == response.json()["job_id"]
        assert client.post("/skills/confirm-upload-zip", json={"session_id": prepared["session_id"], "confirmed": False}).status_code == 409
        release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = client.get("/skills/upload-import-jobs").json()["items"][0]
            if job["status"] == "COMPLETED":
                break
            time.sleep(0.02)
        assert job["status"] == "COMPLETED"
        assert job["results"][0]["status"] == "PENDING"
        assert not (manager.registry.data_dir / "uploaded_skills").exists()
        snapshots = list((manager.registry.data_dir / "skill_versions").rglob("SKILL.md"))
        assert len(snapshots) == 1
        original = snapshots[0].read_text()
        (skill_path / "SKILL.md").write_text("changed session content")
        assert snapshots[0].read_text() == original
    finally:
        release.set()
        api_router._get_upload_jobs(manager).close()


def test_upload_preserves_nested_archive_without_extracting_links(tmp_path):
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        info = zipfile.ZipInfo("资源.svg")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target.svg")
    zip_path = tmp_path / "outer.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("nested.zip", nested.getvalue())
    skipped = []
    api_router._safe_extract_zip(zip_path, tmp_path / "out", skipped_symlinks=skipped)
    assert skipped == []
    assert (tmp_path / "out/nested.zip").read_bytes() == nested.getvalue()
    assert not (tmp_path / "out/nested/资源.svg").exists()


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


def test_list_skills_can_filter_cancelled_tasks(tmp_path):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    cancelled_path = tmp_path / "cancelled-skill"
    cancelled_path.mkdir()
    rejected_path = tmp_path / "rejected-skill"
    rejected_path.mkdir()
    cancelled = manager.create_pending_submission(cancelled_path)
    cancelled.status = SkillStatus.REJECTED
    cancelled.risk_level = RiskLevel.BENIGN
    cancelled.rejection_reason = "用户取消后台分析任务"
    manager.registry.update(cancelled)
    rejected = manager.create_pending_submission(rejected_path)
    rejected.status = SkillStatus.REJECTED
    rejected.risk_level = RiskLevel.SUSPICIOUS
    rejected.rejection_reason = "策略拒绝"
    manager.registry.update(rejected)

    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager

    response = TestClient(app).get("/skills", params={"status": "cancelled"})

    assert response.status_code == 200
    rows = response.json()
    assert [row["skill_id"] for row in rows] == [cancelled.family_id]
    assert rows[0]["version_id"] == cancelled.skill_id
    assert rows[0]["rejection_reason"] == "用户取消后台分析任务"


def test_list_skills_paginated_uses_summary_query(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    second = manager.create_pending_submission(tmp_path)
    second.status = SkillStatus.REJECTED
    second.risk_level = RiskLevel.BENIGN
    second.rejection_reason = "用户取消后台分析任务"
    manager.registry.update(second)

    monkeypatch.setattr(manager, "list_skills", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full list should not be used")))

    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager

    response = TestClient(app).get("/skills", params={
        "page": 1,
        "page_size": 10,
        "status": "cancelled",
        "sort_by": "updated_at",
        "sort_order": "desc",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["skill_id"] == second.family_id
    assert body["items"][0]["version_id"] == second.skill_id
    assert body["items"][0]["rejection_reason"] == "用户取消后台分析任务"
