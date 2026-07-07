from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RegistryEntry, ReviewRequest, RiskLevel, SkillOrigin, SkillStatus, SourceInfo
from agent_manager.core.policy import CompanyPolicy


def _client(tmp_path):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    return TestClient(app), manager


def _entry(name: str, status: SkillStatus, submitted_at: datetime) -> RegistryEntry:
    return RegistryEntry(
        skill_id=f"id-{name}",
        name=name,
        description="review test",
        source=SourceInfo(origin=SkillOrigin.LOCAL, author="test"),
        status=status,
        risk_level=RiskLevel.SUSPICIOUS,
        submitted_at=submitted_at,
        updated_at=submitted_at,
    )


def test_review_queue_rejects_unknown_review_status(tmp_path):
    client, _manager = _client(tmp_path)

    response = client.get("/api/v1/review", params={"review_status": "pendng"})

    assert response.status_code == 400
    assert "review_status must be one of" in response.json()["detail"]


def test_review_queue_reviewed_item_keeps_queue_and_review_times_separate(tmp_path):
    client, manager = _client(tmp_path)
    submitted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    approved_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    updated_at = datetime(2026, 1, 4, tzinfo=timezone.utc)
    entry = _entry("approved-review", SkillStatus.APPROVED, submitted_at)
    entry.approved_at = approved_at
    entry.updated_at = updated_at
    entry.approval_note = "人工复核通过"
    entry.approved_by = "alice"
    manager.registry.add(entry)

    response = client.get("/api/v1/review", params={"review_status": "reviewed"})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["queued_at"] == "2026-01-01T00:00:00+00:00"
    assert rows[0]["reviewed_at"] == "2026-01-03T00:00:00+00:00"
    assert rows[0]["sort_at"] == "2026-01-03T00:00:00+00:00"
    assert rows[0]["approval_note"] == "人工复核通过"
    assert rows[0]["review_note"] == "人工复核通过"


def test_review_queue_all_sorts_pending_and_reviewed_by_sort_at(tmp_path):
    client, manager = _client(tmp_path)
    pending = _entry("pending-review", SkillStatus.VETTED, datetime(2026, 1, 2, tzinfo=timezone.utc))
    reviewed = _entry("reviewed-skill", SkillStatus.REJECTED, datetime(2026, 1, 1, tzinfo=timezone.utc))
    reviewed.updated_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    reviewed.rejection_reason = "风险不可接受"
    manager.registry.add(pending)
    manager.registry.add(reviewed)
    manager.registry.enqueue_review(ReviewRequest(
        skill_id=pending.skill_id,
        skill_name=pending.name,
        risk_level=RiskLevel.SUSPICIOUS,
        findings_summary={"medium": 1},
        submitted_at=pending.submitted_at,
        queued_at=pending.submitted_at,
        notes="需要人工审核",
    ))

    response = client.get("/api/v1/review", params={"review_status": "all", "sort_by": "sort_at", "sort_order": "desc"})

    assert response.status_code == 200
    rows = response.json()
    assert [row["skill_name"] for row in rows] == ["reviewed-skill", "pending-review"]
    assert rows[0]["rejection_reason"] == "风险不可接受"
    assert rows[0]["review_note"] == "风险不可接受"
    assert rows[1]["review_note"] == "需要人工审核"
