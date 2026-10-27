"""同版本复用事务与生命周期操作交错的回归测试。"""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import pytest

from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RegistryEntry, SkillStatus
from agent_manager.core.policy import CompanyPolicy


@pytest.fixture
def manager_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "agent_manager.core.vetting._run_scanner",
        lambda *_: {"findings": [], "max_severity": "SAFE"},
    )
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: reuse-transaction-test\ndescription: Reuse regression\n---\nSummarize text.\n",
        encoding="utf-8",
    )
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    entry = manager.submit(skill)
    other = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    # 模拟独立进程的本地锁，验证一致性由数据库事务保证。
    other.registry._lock = threading.RLock()
    return skill, manager, other, entry


def before_reuse(
    monkeypatch: pytest.MonkeyPatch,
    manager: AgentManager,
    operation: Callable[[], None],
) -> None:
    put = manager.scan_cache.put

    def interleave(*args, **kwargs):
        put(*args, **kwargs)
        operation()

    monkeypatch.setattr(manager.scan_cache, "put", interleave)


def test_reuse_does_not_finish_concurrent_forced_rescan(manager_pair, monkeypatch):
    skill, manager, other, entry = manager_pair
    before_reuse(monkeypatch, manager, lambda: other.request_rescan(entry.skill_id))
    returned, should_process, resolution = manager.prepare_submission(skill)
    runs = other.list_scan_runs(entry.skill_id)
    assert returned.skill_id == entry.skill_id
    assert should_process is False
    assert resolution == "scan_in_progress"
    assert len(runs) == 2
    assert runs[0].status == "PENDING"
    assert runs[0].forced is True
    assert runs[0].reused_from_scan_run_id is None
    other.process_pending_submission(entry.skill_id, force_scan=True)
    assert other.list_scan_runs(entry.skill_id)[0].status == "COMPLETED"
    assert other.registry.get_scan_run_report(runs[0].scan_run_id) is not None


@pytest.mark.parametrize("operation", ["retire", "approve", "reject", "deploy"])
def test_reuse_preserves_latest_lifecycle(manager_pair, monkeypatch, operation):
    skill, manager, other, entry = manager_pair
    if operation in {"approve", "reject"}:
        entry.status = SkillStatus.VETTED
        manager.registry.update(entry)
    decisions: list[RegistryEntry] = []

    def decide():
        if operation == "retire":
            result = other.retire(entry.skill_id, reason="Revoke", actor="admin")
        elif operation == "approve":
            result = other.approve(entry.skill_id, approver="admin", note="Reviewed")
        elif operation == "reject":
            result = other.reject(entry.skill_id, reviewer="admin", reason="Denied")
        else:
            result = other.deploy(entry.skill_id, actor="admin")
        decisions.append(result)

    before_reuse(monkeypatch, manager, decide)
    returned, should_process, resolution = manager.prepare_submission(skill)
    saved = other.get_skill(entry.skill_id)
    assert should_process is False
    assert resolution == "existing_version_reused"
    for field in (
        "status", "risk_level", "signature", "approved_at", "approved_by", "approval_note",
        "rejection_reason", "retire_reason", "retired_at", "deployed_at",
    ):
        assert getattr(returned, field) == getattr(decisions[0], field)
        assert getattr(saved, field) == getattr(decisions[0], field)
    assert saved.scan_reused is True
    if operation == "retire":
        assert saved.status == SkillStatus.RETIRED
        assert not saved.is_loadable()
    run = other.list_scan_runs(entry.skill_id)[0]
    assert run.result["status"] == decisions[0].status.value


@pytest.mark.parametrize("changed", ["context", "content", "report"])
def test_reuse_rechecks_current_result(manager_pair, monkeypatch, changed):
    skill, manager, other, entry = manager_pair

    def change_result():
        current = other.get_skill(entry.skill_id)
        if changed == "context":
            current.scan_context_fingerprint = "different-context"
        elif changed == "content":
            current.content_fingerprint = "different-content"
        else:
            current.vetting = None
        current.approval_note = "Latest state"
        other.registry.update(current)

    before_reuse(monkeypatch, manager, change_result)
    returned, should_process, resolution = manager.prepare_submission(skill)
    assert should_process is True
    assert resolution == "existing_version_rescan"
    assert returned.approval_note == "Latest state"
    assert returned.scan_reused is False
    assert [run.status for run in other.list_scan_runs(entry.skill_id)] == ["PENDING", "COMPLETED"]


@pytest.mark.parametrize("table", ["skill_scan_runs", "skill_scan_run_reports"])
def test_reuse_failure_rolls_back_all_writes(manager_pair, table):
    skill, manager, other, entry = manager_pair
    tables = ("skill_registry", "skill_scan_reports", "skill_families", "skill_scan_runs", "skill_scan_run_reports")

    def snapshot():
        with other.registry._read_connection() as conn:
            return {name: [tuple(row) for row in conn.execute(f"SELECT * FROM {name}")] for name in tables}

    with other.registry._connect() as conn:
        conn.execute(
            f"CREATE TRIGGER reject_reuse BEFORE INSERT ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'reuse write rejected'); END"
        )
    original = snapshot()
    with pytest.raises(sqlite3.IntegrityError, match="reuse write rejected"):
        manager.prepare_submission(skill)
    assert snapshot() == original
    assert other.get_skill(entry.skill_id).scan_reused is False


def test_independent_connections_serialize_reuse_records(manager_pair, monkeypatch):
    skill, manager, other, entry = manager_pair
    inserted = threading.Event()
    second_begin = threading.Event()
    insert = manager.registry._insert_scan_run
    connect = other.registry._connect

    def pause_after_insert(conn, run):
        insert(conn, run)
        inserted.set()
        assert second_begin.wait(5), "second writer did not attempt its transaction"

    def trace_second_connection():
        conn = connect()
        conn.set_trace_callback(
            lambda sql: second_begin.set() if sql == "BEGIN IMMEDIATE" else None
        )
        return conn

    monkeypatch.setattr(manager.registry, "_insert_scan_run", pause_after_insert)
    monkeypatch.setattr(other.registry, "_connect", trace_second_connection)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(manager.prepare_submission, skill)
        assert inserted.wait(5), "first writer did not reach its transaction"
        second = pool.submit(other.prepare_submission, skill)
        assert first.result(timeout=10)[2] == "existing_version_reused"
        assert second.result(timeout=10)[2] == "existing_version_reused"
    runs = other.list_scan_runs(entry.skill_id)
    assert [run.status for run in runs] == ["REUSED", "REUSED", "COMPLETED"]
    assert len({run.scan_run_id for run in runs}) == 3
    assert all(run.reused_from_scan_run_id == runs[-1].scan_run_id for run in runs[:2])
    assert all(other.registry.get_scan_run_report(run.scan_run_id) for run in runs)


def test_reuse_does_not_recreate_deleted_version(manager_pair, monkeypatch):
    skill, manager, other, entry = manager_pair
    before_reuse(monkeypatch, manager, lambda: other.registry.delete(entry.skill_id))
    with pytest.raises(KeyError, match="not found"):
        manager.prepare_submission(skill)
    assert other.get_skill(entry.skill_id) is None
    assert other.list_scan_runs(entry.skill_id) == []
