from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

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

    duplicate = client.post(f"/skills/{pending_entry.skill_id}/rescan")
    assert duplicate.status_code == 200
    assert duplicate.json()["message"] == "该版本正在检测中，无需重复提交。"
    assert len([run for run in manager.list_scan_runs(first.skill_id) if run.status == "PENDING"]) == 1


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
