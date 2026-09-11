from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillStatus
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.signer import compute_content_digest, compute_signature


def _write_skill(path: Path, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: versioned-skill\ndescription: Version test\n---\n{body}\n",
        encoding="utf-8",
    )


def _manager(tmp_path: Path, **policy) -> AgentManager:
    return AgentManager(
        policy=CompanyPolicy({"auto_approve_max_risk": "MEDIUM", **policy}),
        data_dir=tmp_path / "data",
    )


def _ensure_trusted(manager: AgentManager, entry):
    if entry.is_loadable():
        return entry
    entry.status = SkillStatus.APPROVED
    entry.signature = compute_signature(entry.skill_path)
    entry.approved_at = datetime.now(timezone.utc)
    entry.approved_by = "test"
    manager.registry.update(entry)
    return entry


def test_detection_stage_is_visible_during_processing(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    _write_skill(skill, "# Progress")
    manager = _manager(tmp_path)
    observed = []

    def scanner(*_args):
        row = manager.list_skill_summaries(page=1, page_size=10)["items"][0]
        observed.append(row["scan_progress_stage"])
        assert row["scan_pending"] is True
        return {"findings": [], "max_severity": "SAFE"}

    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", scanner)
    manager.submit(skill, use_skillspector=False)
    assert observed == ["analyzers"]
    row = manager.list_skill_summaries(page=1, page_size=10)["items"][0]
    assert row["scan_progress_stage"] is None
    assert row["scan_pending"] is False


@pytest.mark.parametrize("status", [SkillStatus.APPROVED, SkillStatus.VETTED, SkillStatus.REJECTED])
def test_cancel_rescan_preserves_effective_decision(tmp_path, status):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    entry = manager.submit(skill)
    entry.status = status
    manager.registry.update(entry)
    manager.request_rescan(entry.skill_id)
    before = manager.get_skill(entry.skill_id).model_dump()
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    response = client.post(f"/skills/{entry.skill_id}/cancel", json={"reviewer": "admin"})
    assert response.status_code == 200
    assert response.json()["outcome"] == "cancelled"
    assert manager.get_skill(entry.skill_id).model_dump() == before
    assert manager.list_scan_runs(entry.skill_id)[0].status == "CANCELLED"
    assert manager.list_skill_summaries(page=1, page_size=10)["items"][0]["scan_pending"] is False
    repeated = client.post(f"/skills/{entry.skill_id}/cancel", json={"reviewer": "admin"})
    assert repeated.status_code == 200
    assert repeated.json()["outcome"] == "no_pending_scan"
    manager.mark_submission_failed(entry.skill_id, "late worker failure")
    assert manager.get_skill(entry.skill_id).model_dump() == before
    assert manager.list_scan_runs(entry.skill_id)[0].status == "CANCELLED"


def test_cancel_api_marks_initial_scan_cancelled(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    entry, _, _ = manager.prepare_submission(skill)
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)
    assert client.post(f"/skills/{entry.skill_id}/cancel", json={"reviewer": "admin"}).status_code == 200
    assert manager.get_skill(entry.skill_id).status == SkillStatus.REJECTED
    assert manager.list_scan_runs(entry.skill_id)[0].status == "CANCELLED"
    response = client.post("/skills/missing/cancel", json={"reviewer": "admin"})
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "skill_not_found"


@pytest.mark.parametrize("overrides,expected", [
    ({}, (True, True, True, True, True)),
    ({"use_behavioral": False, "use_llm": False, "use_sandbox": False, "use_skillspector": False}, (False, False, False, False, True)),
    ({"use_behavioral": False, "use_llm": True, "use_sandbox": True, "use_skillspector": True}, (False, True, True, True, True)),
])
def test_rescan_options_are_forwarded_to_worker(tmp_path, monkeypatch, overrides, expected):
    from types import SimpleNamespace

    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    entry = manager.submit(skill)
    entry.vetting.scan_report = {
        "analyzers_used": ["behavioral:local", "llm:test", "sandbox:local", "skillspector:test"],
    }
    entry.scan_options = None
    manager.registry.update(entry)
    calls = []
    monkeypatch.setattr(api_router, "_scan_executor", SimpleNamespace(
        submit=lambda fn, mgr, version_id, *options: calls.append((version_id, options)),
    ))
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    response = TestClient(app).post(f"/skills/{entry.skill_id}/rescan", params=overrides)
    assert response.status_code == 200
    assert calls == [(entry.skill_id, expected)]
    detail = TestClient(app).get(f"/skills/{entry.skill_id}").json()
    assert detail["scan_options_source"] == "submitted"
    assert detail["scan_options"] == dict(zip(
        ("use_behavioral", "use_llm", "use_sandbox", "use_skillspector"), expected[:4],
    ))


def test_detail_options_available_before_scan_and_preserved_for_duplicate(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    entry, _, _ = manager.prepare_submission(skill, use_skillspector=True, use_llm=True)
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)
    detail = client.get(f"/skills/{entry.skill_id}").json()
    assert detail["scan_options_source"] == "submitted"
    assert detail["scan_options"] == {
        "use_behavioral": False, "use_llm": True, "use_sandbox": False, "use_skillspector": True,
    }
    client.post(f"/skills/{entry.skill_id}/rescan", params={"use_llm": False})
    assert client.get(f"/skills/{entry.skill_id}").json()["scan_options"] == detail["scan_options"]


def test_detail_legacy_options_use_report_with_source(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    entry = manager.submit(skill)
    entry.scan_options = None
    entry.vetting.scan_report = {"analyzers_used": ["llm:test", "sandbox:local"]}
    manager.registry.update(entry)
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    result = TestClient(app).get(f"/skills/{entry.skill_id}").json()
    assert result["scan_options_source"] == "report"
    assert result["scan_options"]["use_llm"] is True
    assert result["scan_options"]["use_sandbox"] is True
    assert result["scan_options"]["use_skillspector"] is False


def test_same_content_reuses_one_version_and_one_scan(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)

    first = _ensure_trusted(manager, manager.submit(skill))
    second, should_process, resolution = manager.prepare_submission(skill)

    assert second.skill_id == first.skill_id
    assert second.family_id == first.family_id
    assert second.version_no == 1
    assert should_process is False
    assert resolution == "existing_version_reused"
    assert len(manager.list_skill_versions(first.family_id)) == 1
    assert len(manager.list_scan_runs(first.skill_id)) == 1


def test_changed_content_creates_new_immutable_version(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    first = manager.submit(skill)

    _write_skill(skill, "# Second")
    second = manager.submit(skill)

    versions = manager.list_skill_versions(first.family_id)
    assert second.family_id == first.family_id
    assert second.skill_id != first.skill_id
    assert [item.version_no for item in versions] == [2, 1]
    assert Path(first.skill_path, "SKILL.md").read_text(encoding="utf-8").endswith("# First\n")
    assert Path(second.skill_path, "SKILL.md").read_text(encoding="utf-8").endswith("# Second\n")
    assert manager.dashboard_stats()["total"] == 1


def test_global_reuse_switch_forces_new_scan_run_not_new_version(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path, scan_result_reuse_enabled=False)
    first = manager.submit(skill)

    second, should_process, resolution = manager.prepare_submission(skill)

    assert second.skill_id == first.skill_id
    assert should_process is True
    assert resolution == "existing_version_rescan"
    assert len(manager.list_skill_versions(first.family_id)) == 1
    assert [run.status for run in manager.list_scan_runs(first.skill_id)] == ["PENDING", "COMPLETED"]


def test_rescan_failure_preserves_previous_trusted_result(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    approved = _ensure_trusted(manager, manager.submit(skill))
    manager.rescan_skill(approved.skill_id)

    preserved = manager.mark_submission_failed(approved.skill_id, "scanner unavailable")

    assert preserved.status == approved.status
    assert preserved.vetting is not None
    assert manager.get_trusted_skill(approved.family_id).skill_id == approved.skill_id
    assert manager.list_scan_runs(approved.skill_id)[0].status == "FAILED"


def test_versions_and_diff_api(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    first = _ensure_trusted(manager, manager.submit(skill))
    _write_skill(skill, "# Second")
    second = manager.submit(skill)

    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    versions = client.get(f"/skills/{first.family_id}/versions")
    assert versions.status_code == 200
    assert [item["version_id"] for item in versions.json()["items"]] == [second.skill_id, first.skill_id]

    diff = client.get(
        f"/skills/{first.family_id}/diff",
        params={"base": first.skill_id, "target": second.skill_id},
    )
    assert diff.status_code == 200
    item = next(row for row in diff.json()["items"] if row["path"] == "SKILL.md")
    assert item["status"] == "changed"
    assert "# First" in item["before"]
    assert "# Second" in item["after"]
    assert "" not in item["diff"].splitlines()

    pending_entry, started = manager.request_rescan(first.skill_id)
    assert started is True
    versions = client.get(f"/skills/{first.family_id}/versions")
    first_summary = next(item for item in versions.json()["items"] if item["version_id"] == first.skill_id)
    assert first_summary["scan_pending"] is True
    assert first_summary["rescanned"] is True
    assert first_summary["scan_run_count"] >= 2
    assert first_summary["submitted_at"]
    assert first_summary["last_scanned_at"]
    assert first_summary["risk_chain"]["static_risk_level"]
    assert first_summary["risk_chain"]["final_risk_level"]

    duplicate = client.post(f"/skills/{pending_entry.skill_id}/rescan")
    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "already_scanning"
    assert duplicate.json()["message"] == "该版本正在检测中，无需重复提交。"
    assert len([run for run in manager.list_scan_runs(first.skill_id) if run.status == "PENDING"]) == 1


def test_same_version_diff_resolves_aliases_without_reading_files(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    _write_skill(skill, "# Single version")
    manager = _manager(tmp_path)
    entry, _, _ = manager.prepare_submission(skill)
    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    def unexpected_read(_entry):
        pytest.fail("Comparing a version to itself must not traverse or read its files")

    monkeypatch.setattr(api_router, "_version_text_files", unexpected_read)
    for params in ({}, {"base": entry.skill_id, "target": entry.skill_id}, {"base": "v1", "target": "1"}):
        response = client.get(f"/skills/{entry.family_id}/diff", params=params)
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["base"]["version_id"] == entry.skill_id
        assert response.json()["target"]["version_id"] == entry.skill_id
    invalid = client.get(f"/skills/{entry.family_id}/diff", params={"base": "missing", "target": "missing"})
    assert invalid.status_code == 404


def test_version_diff_prunes_excluded_directories_before_traversal(tmp_path, monkeypatch):
    from types import SimpleNamespace

    skill = tmp_path / "skill"
    _write_skill(skill, "# Compare content")
    excluded = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
    for name in excluded:
        nested = skill / name / "nested"
        nested.mkdir(parents=True)
        (nested / "ignored.txt").write_text("ignored")
    (skill / "binary.dat").write_bytes(b"\xff\xfe")
    (skill / "large.txt").write_bytes(b"x" * (1024 * 1024 + 1))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside")
    (skill / "linked").symlink_to(outside, target_is_directory=True)
    (skill / "linked.txt").symlink_to(outside / "secret.txt")
    scanned = []
    original_scandir = api_router.os.scandir

    def record_scandir(path):
        scanned.append(Path(path))
        return original_scandir(path)

    monkeypatch.setattr(api_router.os, "scandir", record_scandir)
    files = api_router._version_text_files(SimpleNamespace(skill_path=str(skill)))
    assert list(files) == ["SKILL.md"]
    assert "# Compare content" in "".join(files["SKILL.md"])
    assert scanned == [skill.resolve()]


def test_versions_api_uses_batch_scan_and_activity_queries(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    first = manager.submit(skill)
    _write_skill(skill, "# Second")
    second = manager.submit(skill)

    calls = {"runs": 0, "activity": 0}
    original_runs = manager.list_scan_runs_for_versions
    original_activity = manager.skill_version_activity

    def batch_runs(version_ids):
        calls["runs"] += 1
        assert set(version_ids) == {first.skill_id, second.skill_id}
        return original_runs(version_ids)

    def batch_activity(version_ids):
        calls["activity"] += 1
        assert set(version_ids) == {first.skill_id, second.skill_id}
        return original_activity(version_ids)

    monkeypatch.setattr(manager, "list_scan_runs_for_versions", batch_runs)
    monkeypatch.setattr(manager, "skill_version_activity", batch_activity)
    monkeypatch.setattr(manager, "list_scan_runs", lambda _version_id: pytest.fail("per-version scan query used"))
    monkeypatch.setattr(manager, "audit", lambda **_kwargs: pytest.fail("per-version audit query used"))

    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    response = TestClient(app).get(f"/skills/{first.family_id}/versions")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert calls == {"runs": 1, "activity": 1}


def test_manual_approval_targets_selected_version_not_latest_family_version(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    first = manager.submit(skill)
    first.status = SkillStatus.VETTED
    first.signature = None
    first.approved_at = None
    first.approved_by = None
    manager.registry.update(first)

    _write_skill(skill, "# Second")
    second = _ensure_trusted(manager, manager.submit(skill))
    assert second.status == SkillStatus.APPROVED

    app = FastAPI()
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    client = TestClient(app)

    ambiguous = client.post(
        f"/skills/{first.family_id}/approve",
        json={"approver": "admin", "note": "wrong identifier"},
    )
    approved = client.post(
        f"/skills/{first.skill_id}/approve",
        json={"approver": "admin", "note": "reviewed V1"},
    )

    assert ambiguous.status_code == 400
    assert "Skill version ID" in ambiguous.json()["detail"]
    assert approved.status_code == 200
    assert approved.json()["skill_id"] == first.skill_id
    assert manager.get_skill(first.skill_id).status == SkillStatus.APPROVED
    assert manager.get_skill(second.skill_id).status == SkillStatus.APPROVED


def test_runtime_name_lookup_and_signature_accept_latest_matching_trusted_version(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    first = _ensure_trusted(manager, manager.submit(skill))
    _write_skill(skill, "# Second")
    second = manager.submit(skill)
    second.status = SkillStatus.REJECTED
    manager.registry.update(second)

    allowed, resolved, _ = manager.runtime.can_load(first.name, verify_sig=False)
    signature_allowed, signature_entry, _ = manager.runtime.verify_local_signature(
        first.name,
        compute_content_digest(first.skill_path),
    )

    assert allowed is True
    assert resolved.skill_id == first.skill_id
    assert signature_allowed is True
    assert signature_entry.skill_id == first.skill_id


def test_delete_family_removes_all_versions_and_snapshots(tmp_path):
    skill = tmp_path / "skill"
    _write_skill(skill, "# First")
    manager = _manager(tmp_path)
    first = manager.submit(skill)
    _write_skill(skill, "# Second")
    second = manager.submit(skill)
    snapshots = [Path(first.skill_path), Path(second.skill_path)]

    manager.delete_skill(first.family_id)

    assert manager.list_skill_versions(first.family_id) == []
    assert all(not path.exists() for path in snapshots)


@pytest.mark.parametrize("force_scan", [True, False])
def test_legacy_duplicate_without_fingerprint_can_be_scanned(tmp_path, force_scan):
    from agent_manager.core.models import RegistryEntry, SourceInfo, SkillOrigin
    from agent_manager.core.scan_cache import compute_content_fingerprint

    skill = tmp_path / "skill"
    _write_skill(skill, "# Historical duplicate")
    manager = _manager(tmp_path, require_sandbox_for_risk=[])
    owner = manager.submit(skill)
    owner_before = manager.registry.get_by_id(owner.skill_id).model_dump()
    legacy = RegistryEntry(
        skill_id="legacy-duplicate", name=owner.name, family_id=owner.family_id,
        description=owner.description,
        version_no=2, skill_path=str(skill), source=SourceInfo(origin=SkillOrigin.LOCAL),
        status=SkillStatus.REJECTED,
        rejection_reason="后台分析失败: UNIQUE constraint failed: index 'idx_skill_registry_family_fingerprint'",
    )
    manager.registry.add(legacy)
    manager.request_rescan(legacy.skill_id)

    result = manager.process_pending_submission(legacy.skill_id, force_scan=force_scan)

    assert result.skill_id == legacy.skill_id
    assert result.content_fingerprint is None
    assert result.rejection_reason is None
    assert result.vetting.scan_report["content_fingerprint"] == compute_content_fingerprint(skill)
    assert not result.vetting.scan_report.get("vetting_failed")
    assert manager.list_scan_runs(legacy.skill_id)[0].status == ("COMPLETED" if force_scan else "REUSED")
    assert manager.registry.get_by_id(owner.skill_id).model_dump() == owner_before
    assert len(manager.registry.list_versions(owner.name)) == 2
    assert manager.registry.find_version_by_content(owner.name, owner.content_fingerprint).skill_id == owner.skill_id
