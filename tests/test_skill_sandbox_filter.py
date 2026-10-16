"""Sandbox 列表筛选以报告中的实际执行记录为准。"""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import (
    RegistryEntry,
    RiskLevel,
    SkillOrigin,
    SkillStatus,
    SourceInfo,
    VettingResult,
)
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.registry import Registry


def _entry(name, report):
    return RegistryEntry(
        skill_id=f"id-{name}", name=name, description="sandbox filter test",
        source=SourceInfo(origin=SkillOrigin.LOCAL), status=SkillStatus.VETTED,
        risk_level=RiskLevel.BENIGN, scan_options={"use_sandbox": True},
        vetting=VettingResult(
            risk_level=RiskLevel.BENIGN, findings_count=0,
            sandbox_triggered=True, sandbox_required_by_policy=True,
            scan_report=report,
        ) if report is not None else None,
    )


@pytest.fixture
def sandbox_list(tmp_path):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    reports = {
        "success": {"executed": True, "exit_code": 0, "risk_level": "LOW"},
        "exit-error": {"executed": True, "exit_code": 1, "risk_level": "LOW"},
        "timeout": {"executed": True, "timed_out": True, "risk_level": "LOW"},
        "no-risk": {"executed": True},
        "legacy": {"executed": True, "risk_level": "MEDIUM"},
        "skipped": {"executed": False, "reason_code": "no_executable_script"},
        "missing-executed": {},
    }
    for name, sandbox in reports.items():
        report = {"sandbox_analysis": sandbox}
        if name != "legacy":
            report["analyzer_timings"] = {"sandbox": {
                "status": "skipped" if name == "skipped" else "completed",
            }}
        manager.registry.add(_entry(name, report))
    manager.registry.add(_entry("missing-analysis", {"analyzer_timings": {
        "sandbox": {"status": "completed"},
    }}))
    manager.registry.add(_entry("no-report", None))
    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    return TestClient(app), manager.registry


EXECUTED = {"success", "exit-error", "timeout", "no-risk", "legacy"}
NOT_EXECUTED = {"skipped", "missing-executed", "missing-analysis", "no-report"}


@pytest.mark.parametrize("executed", [True, False])
@pytest.mark.parametrize("paginated", [True, False])
def test_api_filters_execution_evidence(sandbox_list, executed, paginated):
    client, _registry = sandbox_list
    params = {"sandbox_executed": str(executed).lower(), "sort_by": "name", "sort_order": "asc"}
    if paginated:
        params.update(page=1, page_size=100)
    response = client.get("/api/v1/skills", params=params)
    assert response.status_code == 200
    body = response.json()
    rows = body["items"] if paginated else body
    expected = EXECUTED if executed else NOT_EXECUTED
    assert {row["name"] for row in rows} == expected
    if paginated:
        assert body["total"] == len(expected)


def test_filter_paginates_and_combines_without_changing_triggered(sandbox_list):
    _client, registry = sandbox_list
    params = dict(page_size=2, sandbox_executed=True, sandbox_required_by_policy=True,
                  statuses=[SkillStatus.VETTED], risk_level="benign", sort_by="name", sort_order="asc")
    pages = [registry.list_skill_summaries(page=page, **params) for page in (1, 2, 3)]
    assert [page["total"] for page in pages] == [5, 5, 5]
    assert [row["name"] for page in pages for row in page["items"]] == sorted(EXECUTED)
    assert registry.list_skill_summaries(page=1, q="exit", **params)["total"] == 1
    assert registry.list_skill_summaries(page=1, q="skipped", **params)["total"] == 0
    assert registry.list_skill_summaries(page=1, page_size=10)["total"] == 9
    assert registry.list_skill_summaries(page=1, page_size=10, sandbox_triggered=True)["total"] == 8


def test_historical_execution_status_is_read_only(sandbox_list):
    _client, registry = sandbox_list
    row = registry.list_skill_summaries(page=1, page_size=10, q="legacy")["items"][0]
    assert row["analysis_results"]["sandbox"] == {"status": "completed", "risk_level": "MEDIUM", "executed": True}
    with registry._read_connection() as conn:
        report = json.loads(conn.execute(
            "SELECT report FROM skill_scan_reports WHERE skill_id = ?", ("id-legacy",),
        ).fetchone()[0])
    assert "analyzer_timings" not in report


@pytest.mark.parametrize("current_executed", [True, False])
def test_filter_uses_current_version_report(sandbox_list, current_executed):
    _client, registry = sandbox_list
    old = _entry("versioned", {"sandbox_analysis": {"executed": not current_executed}})
    registry.add(old)
    current = _entry("versioned", {"sandbox_analysis": {"executed": current_executed}})
    current.skill_id = "id-versioned-new"
    current.version_no = 2
    registry.add(current)
    result = registry.list_skill_summaries(page=1, page_size=10, q="versioned", sandbox_executed=True)
    assert result["total"] == int(current_executed)
    assert [row["version_id"] for row in result["items"]] == ([current.skill_id] if current_executed else [])


def test_execution_index_upgrades_existing_reports_and_is_idempotent(sandbox_list):
    _client, registry = sandbox_list
    # 模拟升级前的已有库，确认建索引不改写历史报告。
    with registry._connect() as conn:
        before = list(conn.execute("SELECT * FROM skill_scan_reports ORDER BY skill_id"))
        conn.execute("DROP INDEX idx_skill_scan_reports_sandbox_executed")
    for _ in range(2):
        upgraded = Registry(registry.data_dir)
        assert upgraded.list_skill_summaries(page=1, page_size=10, sandbox_executed=True)["total"] == 5
    with ThreadPoolExecutor(max_workers=4) as pool:
        instances = list(pool.map(lambda _: Registry(registry.data_dir), range(4)))
    assert all(instance.list_skill_summaries(page=1, page_size=10, sandbox_executed=True)["total"] == 5
               for instance in instances)
    with registry._read_connection() as conn:
        assert list(conn.execute("SELECT * FROM skill_scan_reports ORDER BY skill_id")) == before
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT skill_id FROM skill_scan_reports "
            "WHERE json_type(report, '$.sandbox_analysis.executed') = 'true'"
        ).fetchall()
    assert any("COVERING INDEX idx_skill_scan_reports_sandbox_executed" in row[3] for row in plan)


def test_execution_index_tracks_report_updates_and_removal(sandbox_list):
    _client, registry = sandbox_list
    # 重扫更新和报告清除必须立即反映到索引筛选，不能依赖应用缓存。
    for executed in (False, True, False, True):
        registry.update(_entry("success", {"sandbox_analysis": {"executed": executed}}))
        for selected in (True, False):
            result = registry.list_skill_summaries(page=1, page_size=10, q="success", sandbox_executed=selected)
            assert result["total"] == int(executed == selected)
    registry.update(_entry("success", None))
    assert registry.list_skill_summaries(page=1, page_size=10, q="success", sandbox_executed=True)["total"] == 0
    assert registry.list_skill_summaries(page=1, page_size=10, q="success", sandbox_executed=False)["total"] == 1


def test_execution_index_initializes_empty_database(tmp_path):
    registry = Registry(tmp_path / "empty")
    assert registry.list_skill_summaries(page=1, page_size=10, sandbox_executed=True)["total"] == 0
    assert registry.list_skill_summaries(page=1, page_size=10, sandbox_executed=False)["total"] == 0
    with registry._read_connection() as conn:
        indexes = list(conn.execute("PRAGMA index_list(skill_scan_reports)"))
    assert sum(row[1] == "idx_skill_scan_reports_sandbox_executed" for row in indexes) == 1
