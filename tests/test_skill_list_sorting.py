"""Skill 列表按实际字段值排序的回归测试。"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RegistryEntry, RiskLevel, SkillStatus, SourceInfo
from agent_manager.core.policy import CompanyPolicy


@pytest.fixture
def sorting_client(tmp_path):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    # 插入顺序、名称、ID、状态、风险、审批人和时间次序刻意不同。
    cases = [
        ("Zulu", "b", SkillStatus.VETTED, RiskLevel.BENIGN, "bob", 12),
        ("alpha", "c", SkillStatus.APPROVED, RiskLevel.MALICIOUS, "CAROL", 11),
        ("Bravo", "a", SkillStatus.REJECTED, RiskLevel.SUSPICIOUS, "Alan", 13),
    ]
    for name, family_id, status, risk, approver, day in cases:
        entry = RegistryEntry(
            skill_id=f"version-{name}", family_id=family_id, name=name,
            description="Sorting fixture", source=SourceInfo(),
            status=status, risk_level=risk, approved_by=approver,
            updated_at=datetime(2026, 10, day, tzinfo=timezone.utc),
        )
        with patch("agent_manager.core.registry.datetime", wraps=datetime) as clock:
            clock.now.return_value = entry.updated_at
            manager.registry.add(entry)
    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    return TestClient(app), manager


@pytest.mark.parametrize("field,ascending", [
    ("name", ["alpha", "Bravo", "Zulu"]),
    ("skill_id", ["Bravo", "Zulu", "alpha"]),
    ("status", ["alpha", "Bravo", "Zulu"]),
    ("risk_level", ["Zulu", "alpha", "Bravo"]),
    ("approved_by", ["Bravo", "Zulu", "alpha"]),
    ("updated_at", ["alpha", "Zulu", "Bravo"]),
])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_paginated_skills_sort_actual_values(sorting_client, field, ascending, direction):
    client, _ = sorting_client
    expected = ascending if direction == "asc" else ascending[::-1]
    actual = []
    # 跨页核对全局次序，避免只在当前页排序。
    for page in (1, 2):
        response = client.get("/api/v1/skills", params={
            "sort_by": field, "sort_order": direction, "page": page, "page_size": 2,
        })
        assert response.status_code == 200
        assert response.json()["total"] == 3
        actual.extend(row["name"] for row in response.json()["items"])
    assert actual == expected


@pytest.mark.parametrize("paginated", [False, True])
@pytest.mark.parametrize("direction,expected", [
    ("asc", [None, "benign", "malicious", "suspicious"]),
    ("desc", ["suspicious", "malicious", "benign", None]),
])
def test_risk_code_order_preserves_missing_values(sorting_client, paginated, direction, expected):
    client, manager = sorting_client
    manager.registry.add(RegistryEntry(
        skill_id="version-unscanned", family_id="unscanned", name="unscanned",
        description="Unscanned fixture", source=SourceInfo(),
        status=SkillStatus.PENDING,
    ))
    params = {"sort_by": "risk_level", "sort_order": direction}
    if paginated:
        params.update(page=1, page_size=10)
    response = client.get("/api/v1/skills", params=params)
    assert response.status_code == 200
    rows = response.json()["items"] if paginated else response.json()
    assert [row["risk_level"] for row in rows] == expected
